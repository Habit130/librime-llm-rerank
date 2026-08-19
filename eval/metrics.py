#!/usr/bin/env python3
"""Metric computation and stratification for the #70 walk-forward replay.

Per-event outcomes from ``walkforward.WalkForwardReplay`` are aggregated
into the spec's metric families on their exact denominators:

- **Group-complete events** (saved competition size ``< 32``, the #76/#77
  rewrite) are the only events entering top-1 / MRR / mispromotion /
  safety / pollution / event-count gates.  The persisted
  ``competition_complete`` bit is reported as a diagnostic only.
- **Actionable events** (the scheme had non-zero evidence at replay time)
  are the main denominator for the scheme's ranking ability.
- **Actionable union**: events actionable for *any* candidate scheme in a
  comparison round.  A scheme without evidence on a union event is scored
  by its shadow baseline (recorded confirmation rank) per spec #43.
- **Mispromotion** denominator: actionable complete-competition events
  where the shadow baseline (recorded confirmation rank) had the user's
  final selection first; numerator: those where the scheme moved it out of
  first.
- **Pollution**: for target selection y, per kept contribution with
  ``history selection != y``, pollution_mass = sum(a_i | !=y) / sum(a_i).
  Majority pollution = pollution_mass >= 0.5.
- **Coverage**: complete-competition / all replayable targets, overall and
  per major stratum.

Stratification axes: confirmation source (explicit_current /
explicit_indexed) x confirmation rank (1 / >1) x choice-problem frequency
band.  No raw text leaves this module: only event ids and numbers.
"""

from collections import Counter, defaultdict

from walkforward import EventOutcome


class MetricsError(Exception):
    """A true fault in metric aggregation inputs."""


def _eligible(outcomes, complete_only=False, actionable_only=False):
    result = []
    for outcome in outcomes:
        if complete_only and not outcome.group_complete:
            continue
        if actionable_only and not outcome.actionable:
            continue
        result.append(outcome)
    return result


def top1(outcomes, complete_only=False, actionable_only=False):
    """top-1 rate: fraction of eligible events ranked first by the scheme.

    Events whose base position is not reconstructable (page > 1, or
    selection absent from the recorded competition) have
    ``scheme_rank=None`` and are excluded from both numerator and
    denominator: they are reported in the reconstruction-fidelity
    diagnostic, not silently counted as misses.
    """
    eligible = _eligible(outcomes, complete_only, actionable_only)
    eligible = [o for o in eligible if o.scheme_rank is not None]
    if not eligible:
        return None
    hits = sum(1 for o in eligible if o.scheme_rank == 1)
    return hits / len(eligible)


def mrr(outcomes, complete_only=False, actionable_only=False):
    """Mean reciprocal rank of the user's final selection.

    Non-reconstructable events (scheme_rank None) are excluded from the
    mean for the same reason as top1.
    """
    eligible = _eligible(outcomes, complete_only, actionable_only)
    eligible = [o for o in eligible if o.scheme_rank is not None]
    if not eligible:
        return None
    total = 0.0
    count = 0
    for o in eligible:
        total += 1.0 / o.scheme_rank
        count += 1
    return total / count if count else None


def baseline_top1(outcomes, complete_only=False, actionable_only=False):
    """Recorded shadow-baseline top-1 rate over the same eligible events.

    The baseline rank is always recorded (it is the observed confirmation
    position), so no exclusion applies.
    """
    eligible = _eligible(outcomes, complete_only, actionable_only)
    if not eligible:
        return None
    hits = sum(1 for o in eligible if o.baseline_rank == 1)
    return hits / len(eligible)


def mispromotion_events(outcomes, complete_only=True):
    """(denominator, numerator) per spec #43 mispromotion definition.

    Denominator: actionable complete-competition events where the recorded
    shadow baseline ranked the user's final selection first.  Numerator:
    those where the scheme moved the selection out of first.  Events whose
    base position is not reconstructable (scheme_rank None, e.g. page > 1)
    are excluded from both sides — the outcome is unknown, never a
    confirmed mispromotion.
    """
    denominator = []
    numerator = []
    for o in outcomes:
        if complete_only and not o.group_complete:
            continue
        if not o.actionable:
            continue
        if o.baseline_rank != 1:
            continue
        if o.scheme_rank is None:
            continue
        denominator.append(o)
        if o.scheme_rank != 1:
            numerator.append(o)
    return denominator, numerator


def mispromotion_rate(outcomes, complete_only=True):
    denominator, numerator = mispromotion_events(outcomes, complete_only)
    if not denominator:
        return None
    return len(numerator) / len(denominator)


def pollution_mass(outcome):
    """pollution_mass for one event: mass of kept with selection != y.

    Spec #43: pollution_mass = sum(a_i | 历史选择 != y) / sum(a_i) over the
    kept contributions of the target event.  ``kept_matches`` is -1 when
    the history selection matched no candidate, which is also != y.
    """
    if not outcome.kept_weights:
        return None
    total = sum(outcome.kept_weights)
    if total <= 0.0:
        return None
    polluted = sum(weight for weight, matched in zip(
        outcome.kept_weights, outcome.kept_matches)
        if matched != outcome.selection_index)
    return polluted / total


def pollution_distribution(outcomes, actionable_only=True):
    """Mean / p50 / p95 / >0 share / majority (>=0.5) share over events."""
    eligible = _eligible(outcomes, actionable_only=actionable_only)
    values = [pollution_mass(o) for o in eligible]
    values = [v for v in values if v is not None]
    if not values:
        return None
    values.sort()
    n = len(values)
    def quantile(q):
        index = int(round(q * (n - 1)))
        return values[index]
    majority = sum(1 for v in values if v >= 0.5)
    positive = sum(1 for v in values if v > 0.0)
    return {
        "mean": sum(values) / n,
        "p50": quantile(0.50),
        "p95": quantile(0.95),
        "positive_share": positive / n,
        "majority_share": majority / n,
        "count": n,
    }


def majority_pollution_rate(outcomes, actionable_only=True):
    dist = pollution_distribution(outcomes, actionable_only)
    return dist["majority_share"] if dist else None


def coverage_report(outcomes):
    """Coverage: group-complete / replayable targets, overall+strata.

    Both count families are reported: the group-complete gate (size < 32,
    the #76/#77 denominator) and the persisted competition_complete bit
    (diagnostic only).
    """
    total = len(outcomes)
    group_complete = sum(1 for o in outcomes if o.group_complete)
    bit_complete = sum(1 for o in outcomes if o.competition_complete)
    strata = {}
    for o in outcomes:
        key = (o.confirmation_source,
               "1" if o.baseline_rank == 1 else ">1")
        entry = strata.setdefault(key, {"replayable": 0, "complete": 0})
        entry["replayable"] += 1
        entry["complete"] += int(o.group_complete)
    strata_report = {}
    for key, entry in strata.items():
        strata_report["%s/%s" % key] = {
            "replayable": entry["replayable"],
            "complete": entry["complete"],
            "coverage": (entry["complete"] / entry["replayable"]
                         if entry["replayable"] else 0.0),
        }
    return {
        "replayable": total,
        "group_complete": group_complete,
        "competition_complete_bit": bit_complete,
        "coverage": group_complete / total if total else 0.0,
        "strata": strata_report,
    }


def strata_of(outcomes, complete_only=False):
    """outcomes -> {(source, rank) : [outcomes]} cross-strata groups."""
    groups = defaultdict(list)
    for o in outcomes:
        if complete_only and not o.group_complete:
            continue
        key = (o.confirmation_source,
               "1" if o.baseline_rank == 1 else ">1")
        groups[key].append(o)
    return dict(groups)


def key_frequency(outcomes):
    """choice-problem key -> event count, for frequency-band stratification."""
    return Counter(o.key for o in outcomes)


def frequency_band(count):
    """spec's frequency bands: >=100 / 20..99 / 1..19 events per key."""
    if count >= 100:
        return ">=100"
    if count >= 20:
        return "20-99"
    return "1-19"


def stratified_metrics(outcomes, complete_only=True, actionable_only=True):
    """Per-stratum (source x rank x frequency band) metric table.

    Each stratum reports its own event count, top-1, MRR, mispromotion rate
    and coverage so the >=200-event per-stratum gate can be applied by the
    grid scan.  Returns a list of dicts; no raw text.
    """
    counts = key_frequency(outcomes)
    table = []
    for (source, rank), group in strata_of(
            outcomes, complete_only=complete_only).items():
        bands = defaultdict(list)
        for o in group:
            bands[frequency_band(counts[o.key])].append(o)
        for band, band_outcomes in sorted(bands.items()):
            denominator, numerator = mispromotion_events(
                band_outcomes, complete_only=True)
            table.append({
                "confirmation_source": source,
                "confirmation_rank": rank,
                "frequency_band": band,
                "count": len(band_outcomes),
                "complete_count": sum(1 for o in band_outcomes
                                      if o.group_complete),
                "top1": top1(band_outcomes, complete_only=complete_only,
                             actionable_only=actionable_only),
                "mrr": mrr(band_outcomes, complete_only=complete_only,
                           actionable_only=actionable_only),
                "mispromotion_rate": mispromotion_rate(
                    band_outcomes, complete_only=True),
                "mispromotion_denominator": len(denominator),
                "mispromotion_numerator": len(numerator),
            })
    return table
