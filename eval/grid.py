#!/usr/bin/env python3
"""Pre-declared grid scan with safety gates (Habit130/squirrel#70).

Candidate space (spec #43, frozen verbatim):

- representations: exact L14/L21/L28 last-token + RMSNorm + cosine, and the
  pre-declared split-reuse representation (from #60); nothing else is
  introduced.
- H in {8, 32, 128, 512, inf}; K_evidence in {8, 16, 32, 64};
  gamma in {0.5, 1, 2, 4}; k in {1, 3, 7}.
- τ per representation_id, only from the τ calibration protocol (dev
  prefix, ≥200 hard-negative queries, Q95/Q97.5/Q99/Q99.5); a
  representation without a calibratable τ is reported as such and its
  τ-dependent cells are skipped — no invented τ.
- No continuous optimizer is used anywhere: the scan is a flat pre-declared
  product grid.

Gates applied per configuration (spec #43):

1. **Δ₁ single-event safety boundary**: Δ₁ = γ/(1+k) must satisfy
   Δ₁ <= min(0.5, P10(margin_base)).  On real snapshots margin_base is
   unavailable (facts do not persist per-candidate base scores), so the
   engine enforces the hard cap Δ₁ <= 0.5 and records the unavailable state
   explicitly; synthetic fixtures inject base scores and pin the full
   boundary.  Configurations violating the boundary are eliminated.
2. **Finite-H gates**: each finite H vs H=inf must simultaneously satisfy
   top-1 paired-difference 95% CI lower bound >= -1pp, mispromotion-rate
   difference CI upper bound <= +1pp and majority-pollution-rate difference
   CI upper bound <= +1pp, all on the common actionable union.  When no
   finite H passes, γ=0 stays (nothing is shipped).
3. **Milestones**: 250/500 actionable complete-competition events produce a
   diagnostic report only; the earliest scheme selection additionally needs
   >=1000 such events, >=100 choice-problem keys, >=200 explicit_indexed
   and >=200 confirmation-rank >1 events.  Below the thresholds the report
   states "诊断报告,不选方案" and no scheme is chosen.

No raw text is produced: results carry representation ids, parameter
values, numbers and event counts.
"""

import math

from bootstrap import paired_difference
from calibration import MIN_HARD_NEGATIVE_QUERIES, calibrate_tau
from metrics import (majority_pollution_rate, mispromotion_events,
                     mispromotion_rate, pollution_distribution,
                     pollution_mass, top1, mrr)
from walkforward import (DELTA_ONE_CAP, OracleParams, delta_one,
                         margin_base_unavailable)


class GridError(Exception):
    """A true fault in the grid scan inputs."""


# Pre-declared candidate space (spec #43).
HALF_LIVES = (8, 32, 128, 512, float("inf"))
K_EVIDENCE = (8, 16, 32, 64)
GAMMAS = (0.5, 1.0, 2.0, 4.0)
SATURATION_KS = (1, 3, 7)

# Selection milestones (spec #43, verbatim).
MILESTONE_DIAGNOSTIC = 250
MILESTONE_500 = 500
MILESTONE_SELECT = 1000
MILESTONE_KEYS = 100
MILESTONE_EXPLICIT_INDEXED = 200
MILESTONE_RANK_GT1 = 200


def predeclared_cells(representation_id):
    """The flat product grid for one representation (no τ yet).

    Ordering: (K_evidence, gamma, k, H) with H innermost, so every
    (K, gamma, k) group carries all five H values contiguously — the
    H=inf twin of each finite-H cell is always in the same group, which
    is what the finite-H gate needs.
    """
    cells = []
    for k_evidence in K_EVIDENCE:
        for gamma in GAMMAS:
            for saturation_k in SATURATION_KS:
                for half_life in HALF_LIVES:
                    cells.append({
                        "representation_id": representation_id,
                        "half_life": half_life,
                        "k_evidence": k_evidence,
                        "gamma": gamma,
                        "saturation_k": saturation_k,
                    })
    return cells


def delta_one_ok(gamma, saturation_k, margin_base=None):
    """Δ₁ boundary: Δ₁ <= min(0.5, P10(margin_base)).

    ``margin_base`` is the P10 value from the (fixture-injected) base-score
    margin distribution, or None when unavailable (real snapshots): then
    only the 0.5 hard cap applies and the report records the unavailable
    state.
    """
    d1 = delta_one(gamma, saturation_k)
    if margin_base is None:
        return d1 <= DELTA_ONE_CAP
    return d1 <= min(DELTA_ONE_CAP, margin_base)


def milestone_counts(outcomes):
    """(actionable_complete, keys, explicit_indexed, rank_gt1).

    The milestone counts are **scheme-independent**: they count the
    replayable events that are complete-competition and actionable under
    the scheme-agnostic actionable union (any evidence at all, i.e. any
    same-key active history above threshold under a reference parameter
    set), so the milestone reflects the data, not one cell's parameters.
    """
    keys = set()
    explicit_indexed = 0
    rank_gt1 = 0
    actionable_complete = 0
    for o in outcomes:
        if not o.actionable or not o.competition_complete:
            continue
        actionable_complete += 1
        keys.add(o.key)
        if o.confirmation_source == "explicit_indexed":
            explicit_indexed += 1
        if o.baseline_rank != 1:
            rank_gt1 += 1
    return actionable_complete, len(keys), explicit_indexed, rank_gt1


def milestone_state(actionable_complete, key_count, explicit_indexed,
                    rank_gt1):
    """The spec's milestone state for the current sample size.

    Returns ("diagnostic", reason) — no scheme may be selected below the
    selection milestone; 250/500 only upgrade the diagnostic depth.
    """
    if actionable_complete >= MILESTONE_SELECT and \
            key_count >= MILESTONE_KEYS and \
            explicit_indexed >= MILESTONE_EXPLICIT_INDEXED and \
            rank_gt1 >= MILESTONE_RANK_GT1:
        return ("selectable", "all selection milestones met")
    return ("diagnostic",
            "诊断报告,不选方案: actionable complete=%d (need >=%d), "
            "keys=%d (need >=%d), explicit_indexed=%d (need >=%d), "
            "rank>1=%d (need >=%d)"
            % (actionable_complete, MILESTONE_SELECT, key_count,
               MILESTONE_KEYS, explicit_indexed, MILESTONE_EXPLICIT_INDEXED,
               rank_gt1, MILESTONE_RANK_GT1))


def _cell_outcomes(replay, cell, gamma=None):
    """Run one cell: replay under its params and return (outcomes, summary).

    ``cell`` carries the oracle params; ``gamma`` defaults to the cell's
    gamma when absent (the grid path), and is passed explicitly for the
    scheme-independent reference replay (γ=0).
    """
    params = OracleParams(tau=cell["tau"], k_evidence=cell["k_evidence"],
                          half_life=cell["half_life"],
                          saturation_k=cell["saturation_k"])
    if gamma is None:
        gamma = cell["gamma"]
    return replay.replay(params, gamma)


def _rate_fn(metric):
    def fn(outcome):
        if metric == "top1":
            return 1.0 if outcome.scheme_rank == 1 else 0.0
        raise GridError("unknown rate metric %r" % metric)
    return fn


def _stratum_gates(outcomes, seed, replicates=10000):
    """Per-stratum quality gates (spec #43).

    Any stratum (confirmation source x confirmation rank) reaching >=200
    actionable complete-competition events must satisfy, on that stratum's
    own events:

    - top-1 non-inferiority vs the shadow baseline: the key-clustered
      paired-difference 95% CI lower bound >= -1pp;
    - mispromotion: point estimate <= 2% and 95% CI upper bound <= 3%
      (denominator = actionable complete events where the baseline ranked
      the selection first).

    Strata below 200 events are reported with ``applicable: false`` and
    no gate result.  Returns a list of per-stratum gate dicts.
    """
    from metrics import strata_of

    results = []
    strata = strata_of(outcomes, complete_only=True)
    for (source, rank), stratum_outcomes in sorted(strata.items()):
        actionable_complete = [o for o in stratum_outcomes if o.actionable]
        if len(actionable_complete) < 200:
            results.append({
                "stratum": "%s/%s" % (source, rank),
                "applicable": False,
                "count": len(actionable_complete),
            })
            continue

        def top1_fn(o):
            return 1.0 if o.scheme_rank == 1 else 0.0

        def baseline_fn(o):
            return 1.0 if o.baseline_rank == 1 else 0.0

        top1_diff = paired_difference(actionable_complete, top1_fn,
                                      baseline_fn, replicates=replicates,
                                      seed=seed)
        mp_den, mp_num = mispromotion_events(actionable_complete,
                                             complete_only=True)
        mp_point = (len(mp_num) / len(mp_den)) if mp_den else None

        # Mispromotion CI: bootstrap the rate on the denominator events.
        mp_ci = (None, None)
        if mp_den:
            from bootstrap import bootstrap_rate
            _, mp_ci = bootstrap_rate(
                mp_den, lambda o: 0.0 if o.scheme_rank == 1 else 1.0,
                replicates=replicates, seed=seed)

        top1_ok = top1_diff[1][0] is None or top1_diff[1][0] >= -0.01
        mp_point_ok = mp_point is None or mp_point <= 0.02
        mp_ci_ok = mp_ci[1] is None or mp_ci[1] <= 0.03
        results.append({
            "stratum": "%s/%s" % (source, rank),
            "applicable": True,
            "count": len(actionable_complete),
            "top1_diff": top1_diff,
            "mispromotion_point": mp_point,
            "mispromotion_ci": mp_ci,
            "pass": top1_ok and mp_point_ok and mp_ci_ok,
        })
    return results


def run_cell(replay, cell, seed, replicates=10000):
    """Run one grid cell and its per-cell metrics + bootstrap CIs.

    Returns a dict with point estimates and the bootstrap CI (95%,
    key-clustered, fixed seed, >=10000 replicates) for top-1 and
    mispromotion on the cell's own actionable complete-competition events.
    """
    outcomes, summary = _cell_outcomes(replay, cell)
    actionable_complete = [o for o in outcomes
                           if o.actionable and o.competition_complete]
    top1_point = top1(outcomes, complete_only=True, actionable_only=True)
    mrr_point = mrr(outcomes, complete_only=True, actionable_only=True)
    mp_den, mp_num = mispromotion_events(outcomes, complete_only=True)
    mp_rate = (len(mp_num) / len(mp_den)) if mp_den else None
    poll = pollution_distribution(outcomes)
    majority = poll["majority_share"] if poll else None

    def top1_fn(o):
        return 1.0 if o.scheme_rank == 1 else 0.0

    def baseline_fn(o):
        return 1.0 if o.baseline_rank == 1 else 0.0

    top1_diff = paired_difference(actionable_complete, top1_fn, baseline_fn,
                                  replicates=replicates, seed=seed)
    return {
        "cell": cell,
        "outcomes": outcomes,  # internal: used by the finite-H gate only
        "summary": summary,
        "metrics": {
            "top1": top1_point,
            "mrr": mrr_point,
            "mispromotion_rate": mp_rate,
            "mispromotion_denominator": len(mp_den),
            "mispromotion_numerator": len(mp_num),
            "pollution": poll,
            "majority_pollution_rate": majority,
            "actionable_complete": len(actionable_complete),
        },
        "ci": {
            "top1_vs_baseline": top1_diff,
        },
        "stratum_gates": _stratum_gates(outcomes, seed, replicates),
        "delta_one": delta_one(cell["gamma"], cell["saturation_k"]),
        "delta_one_ok": delta_one_ok(cell["gamma"], cell["saturation_k"],
                                     margin_base=None),
    }


def run_representation(replay, name, seed, replicates=10000,
                       max_cells=None):
    """Run the whole grid for one representation (all τ candidates).

    Returns the per-cell results, the τ calibration state and the milestone
    state.  The replay is re-walked per cell — deterministic and pure, so
    cells are independent and reproducible.  The milestone counts come from
    a scheme-independent reference replay (τ = 0, K = 8, H = inf, k = 1,
    γ = 0), which measures the data's actionable union without depending on
    any candidate's parameters.  ``max_cells`` limits evaluated cells
    (driver smoke / test use only; the report then carries a
    ``partial_scan`` marker).
    """
    status = calibrate_tau(replay)
    cells = []
    if status["state"] != "calibratable":
        # τ not calibratable: the τ-dependent evaluation cells cannot run
        # (no invented τ).  The Δ₁ single-event safety boundary is a pure
        # parameter function, so it is still reported over the whole
        # pre-declared space; the milestone comes from the reference
        # replay so the diagnostic always carries the data-readiness state.
        for cell in predeclared_cells(name):
            cell = dict(cell, tau=None, tau_quantile=None)
            if not delta_one_ok(cell["gamma"], cell["saturation_k"]):
                cells.append({"cell": cell, "eliminated": "delta_one"})
            else:
                cells.append({"cell": cell, "eliminated": "tau_not_calibratable"})
        reference_outcomes, _ = _cell_outcomes(replay, {
            "tau": 0.0,
            "k_evidence": K_EVIDENCE[0],
            "half_life": HALF_LIVES[-1],
            "saturation_k": SATURATION_KS[0],
        }, gamma=0.0)
        counts = milestone_counts(reference_outcomes)
        milestone_state_name, milestone_reason = milestone_state(*counts)
        return {
            "representation": name,
            "tau": status,
            "cells": cells,
            "milestone": {"state": milestone_state_name,
                          "reason": "%s (τ not calibratable: %d hard-negative "
                                    "queries < %d)"
                                    % (milestone_reason, status["queries"],
                                       MIN_HARD_NEGATIVE_QUERIES),
                          "counts": {
                              "actionable_complete": counts[0],
                              "keys": counts[1],
                              "explicit_indexed": counts[2],
                              "rank_gt1": counts[3],
                          }},
            "selection": "not_run",
        }
    for quantile, tau_value in sorted(
            status["quantiles"].items(),
            key=lambda item: float(item[0])):
        for cell in predeclared_cells(name):
            cell = dict(cell, tau=tau_value, tau_quantile=quantile)
            if not delta_one_ok(cell["gamma"], cell["saturation_k"]):
                cells.append({"cell": cell, "eliminated": "delta_one"})
                continue
            try:
                cells.append(run_cell(replay, cell, seed,
                                      replicates=replicates))
            except Exception as error:  # noqa: BLE001
                raise GridError(
                    "cell failed for %s %r: %s" % (name, cell, error)
                ) from error
            if max_cells is not None and \
                    len([c for c in cells if "eliminated" not in c]) >= \
                    max_cells:
                break
        if max_cells is not None and \
                len([c for c in cells if "eliminated" not in c]) >= \
                max_cells:
            break

    # Finite-H gates: every finite-H cell is compared against its H=inf
    # twin (same tau / K / gamma / k) on the common actionable union.  The
    # result is attached to the finite-H cell as ``finite_h_gate`` and the
    # H=inf cell as ``finite_h_reference``; a failed gate means the finite-H
    # cell is not acceptable relative to H=inf (spec: no finite H passes ->
    # keep γ=0, never ship H=inf either).
    finite_h = {}
    for cell_record in cells:
        if "eliminated" in cell_record:
            continue
        cell = cell_record["cell"]
        if cell["half_life"] == float("inf"):
            continue
        key = (cell["tau_quantile"], cell["k_evidence"],
               cell["gamma"], cell["saturation_k"])
        finite_h.setdefault(key, []).append(cell_record)
    inf_cells = {}
    for cell_record in cells:
        if "eliminated" in cell_record:
            continue
        cell = cell_record["cell"]
        if cell["half_life"] == float("inf"):
            key = (cell["tau_quantile"], cell["k_evidence"],
                   cell["gamma"], cell["saturation_k"])
            inf_cells[key] = cell_record
    for key, finite_records in finite_h.items():
        inf_record = inf_cells.get(key)
        if inf_record is None:
            continue
        for finite_record in finite_records:
            gate = finite_h_gate(inf_record, finite_record, seed,
                                 replicates=replicates)
            finite_record["finite_h_gate"] = {
                "pass": gate["pass"],
                "union_events": gate["union_events"],
                "top1_diff": gate["top1_diff"],
                "mispromotion_diff": gate["mispromotion_diff"],
                "majority_pollution_diff": gate["majority_pollution_diff"],
            }
        inf_record["finite_h_reference"] = True
    reference_outcomes, _ = _cell_outcomes(replay, {
        "tau": 0.0,
        "k_evidence": K_EVIDENCE[0],
        "half_life": HALF_LIVES[-1],
        "saturation_k": SATURATION_KS[0],
    }, gamma=0.0)
    counts = milestone_counts(reference_outcomes)
    result = {
        "representation": name,
        "tau": status,
        "cells": cells,
        "milestone": {"state": milestone_state(*counts)[0],
                      "reason": milestone_state(*counts)[1],
                      "counts": {
                          "actionable_complete": counts[0],
                          "keys": counts[1],
                          "explicit_indexed": counts[2],
                          "rank_gt1": counts[3],
                      }},
        "selection": "not_run",
    }
    if max_cells is not None:
        result["partial_scan"] = True
    return result


def finite_h_gate(inf_cell, finite_cell, seed, replicates=10000,
                  ci_level=0.95):
    """Finite-H vs H=inf paired gates on the common actionable union.

    All three paired-difference CIs must hold simultaneously:
    top-1 lower bound >= -1pp, mispromotion upper bound <= +1pp,
    majority-pollution upper bound <= +1pp.  Both cells' outcomes must
    cover the same event set (the driver passes union outcomes aligned by
    event id).  top-1 is only computed over complete-competition events;
    mispromotion over the spec's denominator (actionable complete events
    where the baseline ranked the selection first); pollution over
    actionable events.
    """
    from collections import defaultdict

    inf_by_id = {o.event_id: o for o in inf_cell["outcomes"]}
    finite_by_id = {o.event_id: o for o in finite_cell["outcomes"]}
    union_ids = sorted(set(inf_by_id) & set(finite_by_id))

    def top1_fn(outcome):
        if not outcome.competition_complete or not outcome.actionable:
            return None
        return 1.0 if outcome.scheme_rank == 1 else 0.0

    def mispromotion_fn(outcome):
        if not outcome.competition_complete or not outcome.actionable:
            return None
        if outcome.baseline_rank != 1:
            return None
        if outcome.scheme_rank is None:
            return None
        return 0.0 if outcome.scheme_rank == 1 else 1.0

    def pollution_fn(outcome):
        if not outcome.actionable:
            return None
        return pollution_mass(outcome)

    def diff_for(fn, events_left, events_right):
        values = []
        for left, right in zip(events_left, events_right):
            a = fn(left)
            b = fn(right)
            if a is None or b is None:
                continue
            values.append((left.key, a - b))
        if not values:
            return None, (None, None)
        groups = defaultdict(list)
        for key, value in values:
            groups[key].append(value)
        keys = list(groups)
        point = sum(sum(v) for v in groups.values()) / len(values)
        rng = __import__("random").Random(seed)
        deltas = []
        for _ in range(replicates):
            total = 0.0
            count = 0
            for _ in range(len(keys)):
                key = rng.choice(keys)
                for value in groups[key]:
                    total += value
                    count += 1
            if count:
                deltas.append(total / count)
        deltas.sort()
        lower_index = int(((1.0 - ci_level) / 2.0) * (len(deltas) - 1))
        upper_index = int(((1.0 + ci_level) / 2.0) * (len(deltas) - 1))
        return point, (deltas[lower_index], deltas[upper_index])

    pairs_finite = [finite_by_id[event_id] for event_id in union_ids]
    pairs_inf = [inf_by_id[event_id] for event_id in union_ids]

    top1_diff = diff_for(top1_fn, pairs_finite, pairs_inf)
    misp_diff = diff_for(mispromotion_fn, pairs_finite, pairs_inf)
    poll_diff = diff_for(pollution_fn, pairs_finite, pairs_inf)

    top1_ok = top1_diff[1][0] is None or top1_diff[1][0] >= -0.01
    misp_ok = misp_diff[1][1] is None or misp_diff[1][1] <= 0.01
    poll_ok = poll_diff[1][1] is None or poll_diff[1][1] <= 0.01
    return {
        "pass": top1_ok and misp_ok and poll_ok,
        "union_events": len(union_ids),
        "top1_diff": top1_diff,
        "mispromotion_diff": misp_diff,
        "majority_pollution_diff": poll_diff,
    }
