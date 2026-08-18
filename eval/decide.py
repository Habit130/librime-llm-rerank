#!/usr/bin/env python3
"""decide_final for the #106 α recalibration (primary-only selection).

Selection keys (spec #43 / #46, frozen): primary group-complete top-1 rate,
then MRR, then the smaller α as a stable tie-break.  The selection domain is
the primary denominator ONLY — control-denominator metrics never enter
``decide_final`` (SCN-106-6, AC106-3).

Boundary extension rule (#46): sweep the pre-declared grid
``{0, 0.5, 1, 2, 3, 4, 5, 7, 10}``; if the primary-denominator winner is the
upper bound ``10``, extend by ``{14, 20}`` and re-run those two only.  If
the winner is still the upper bound after extension, ``internal_optimum`` is
false and the bound is NOT reported as calibrated (SCN-106-11).

The α=0 grid point is included in the selection domain.  No continuous
optimizer; no mixing of external text into the decision.
"""

from typing import Dict, List, Optional

from recalibrate import ALPHA_EXTENSION, ALPHA_GRID, AlphaMetrics


class DecisionError(Exception):
    """A true fault in the decision inputs."""


def grid_extension_triggered(winner_alpha: float,
                             grid: List[float] = ALPHA_GRID,
                             extension: List[float] = ALPHA_EXTENSION
                             ) -> bool:
    """True iff the winner sits on the grid's upper boundary (extension)."""
    return bool(extension) and winner_alpha == grid[-1]


def select_alpha(metrics_by_alpha: Dict[float, AlphaMetrics],
                 domain: List[float]) -> float:
    """The primary-only winner: top-1, then MRR, then smaller α.

    ``metrics_by_alpha`` maps α -> AlphaMetrics (primary denominator).
    ``domain`` is the ordered grid actually swept (including extension
    points when triggered).  Raises DecisionError when the domain is empty.
    """
    available = [a for a in domain if a in metrics_by_alpha]
    if not available:
        raise DecisionError("no α metrics available for the selection domain")
    best = max(
        available,
        key=lambda a: (metrics_by_alpha[a].top1_rate,
                       metrics_by_alpha[a].mrr,
                       -a),
    )
    return best


def decide_final(metrics_by_alpha: Dict[float, AlphaMetrics],
                 grid: List[float] = ALPHA_GRID,
                 extension: List[float] = ALPHA_EXTENSION,
                 min_primary_events: int = 1000,
                 min_primary_keys: int = 100,
                 primary_event_count: Optional[int] = None,
                 primary_key_count: Optional[int] = None) -> Dict:
    """The full decision record (written into the manifest/report).

    SCN-106-10: when the remaining primary set after 无法重放 falls below
    ``min_primary_events`` or ``min_primary_keys``, no α* is declared and the
    state is ``specification_blocker`` (the driver hands back the blocker to
    the owner with desensitized drop-off counts).
    """
    # SCN-106-10 gate.
    if primary_event_count is not None and \
            primary_event_count < min_primary_events:
        return {
            "state": "specification_blocker",
            "reason": (
                "primary replayable events %d < %d after 无法重放 "
                "(SCN-106-10)" % (primary_event_count, min_primary_events)),
            "primary_events": primary_event_count,
            "primary_keys": primary_key_count,
            "min_primary_events": min_primary_events,
            "min_primary_keys": min_primary_keys,
            "final_alpha_value": None,
            "internal_optimum": None,
            "positive_alpha_qualified": None,
            "final_alpha_rationale": None,
        }
    if primary_key_count is not None and primary_key_count < min_primary_keys:
        return {
            "state": "specification_blocker",
            "reason": (
                "primary choice-problem keys %d < %d after 无法重放 "
                "(SCN-106-10)" % (primary_key_count, min_primary_keys)),
            "primary_events": primary_event_count,
            "primary_keys": primary_key_count,
            "min_primary_events": min_primary_events,
            "min_primary_keys": min_primary_keys,
            "final_alpha_value": None,
            "internal_optimum": None,
            "positive_alpha_qualified": None,
            "final_alpha_rationale": None,
        }

    winner = select_alpha(metrics_by_alpha, grid)
    winner_metrics = metrics_by_alpha[winner]

    # Extension rule: winner on the grid's upper bound -> extend.
    # The driver may already have pre-swept the extension points and passed
    # them inside ``grid``; extend only when they are not already present,
    # so the swept domain never lists a point twice (the domain feeds the
    # internal-optimum boundary check and the report grid).
    swept_domain = list(grid)
    if grid_extension_triggered(winner, grid, extension):
        missing = [a for a in extension
                   if a in metrics_by_alpha and a not in swept_domain]
        swept_domain.extend(missing)
        if missing:
            winner = select_alpha(metrics_by_alpha, swept_domain)
            winner_metrics = metrics_by_alpha[winner]

    baseline = metrics_by_alpha.get(0.0)
    positive_qualified = any(
        a > 0.0 and metrics_by_alpha[a].top1_rate > (baseline.top1_rate
                                                     if baseline else 0.0)
        for a in swept_domain if a > 0.0 and a in metrics_by_alpha)

    # internal_optimum: the winner is an interior point of the swept domain.
    # A boundary winner (lower or upper, including after extension) is not an
    # internal optimum.
    interior = swept_domain[1:-1]
    internal_optimum = winner in interior

    if winner == 0.0:
        rationale = (
            "α=0 (weight-only) wins the primary denominator on top-1 "
            "(%s) and MRR (%s); no positive α qualifies "
            "(positive_alpha_qualified=false)."
            % (_fmt(winner_metrics.top1_rate), _fmt(winner_metrics.mrr)))
        final_alpha_value = 0.0
    else:
        extension_note = ""
        if winner in extension:
            extension_note = ("; the winner sits on the grid's upper "
                              "boundary after the pre-declared extension "
                              "{%s} — it is NOT reported as a calibrated "
                              "internal optimum (SCN-106-11)"
                              % ", ".join(str(a) for a in extension))
        elif not internal_optimum:
            extension_note = ("; the winner sits on the grid's lower "
                              "boundary — no internal optimum is declared")
        rationale = (
            "α=%s wins the primary denominator on top-1 (%s) and MRR (%s)%s."
            % (winner, _fmt(winner_metrics.top1_rate),
               _fmt(winner_metrics.mrr), extension_note))
        final_alpha_value = winner

    return {
        "state": "decided",
        "reason": "selection keys: primary top-1, then MRR, then smaller α",
        "primary_events": primary_event_count,
        "primary_keys": primary_key_count,
        "min_primary_events": min_primary_events,
        "min_primary_keys": min_primary_keys,
        "final_alpha_value": final_alpha_value,
        "internal_optimum": internal_optimum,
        "positive_alpha_qualified": positive_qualified,
        "final_alpha_rationale": rationale,
        "swept_domain": swept_domain,
    }


def _fmt(value: float) -> str:
    return "%.4f" % value
