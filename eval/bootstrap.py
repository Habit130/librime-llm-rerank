#!/usr/bin/env python3
"""Cluster bootstrap with 95% confidence intervals for the #70 metrics.

Spec #43 pairing & CI clauses:

- All rank comparisons are paired on the same events.
- Bootstrap resamples **choice-problem keys as clusters** (never single
  events), with a fixed random seed, at least 10,000 replicates, reporting
  the 95% CI.
- Cross-scheme comparisons must never compare on different easy subsets:
  the paired differences are computed on the common actionable union.

The implementation is deterministic: it uses the seeded stdlib ``random``
RNG (no numpy), so a re-run with the same seed and the same outcomes
produces byte-identical CIs.  Event-level contributions are aggregated per
choice-problem key once, then each replicate resamples keys with
replacement and recomputes the metric from the per-key aggregates.

No raw text is produced: metrics are numbers over event ids.
"""

import random
import statistics

from walkforward import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, CI_LEVEL


class BootstrapError(Exception):
    """A true fault in bootstrap inputs."""


def _ci(percentiles, values):
    """Two-sided percentile CI at the requested level."""
    values = sorted(values)
    n = len(values)
    lower_index = int(((1.0 - percentiles) / 2.0) * (n - 1))
    upper_index = int(((1.0 + percentiles) / 2.0) * (n - 1))
    return values[lower_index], values[upper_index]


def _cluster_sums(outcomes, value_fn):
    """choice-problem key -> list of per-event values (paired per event)."""
    groups = {}
    for outcome in outcomes:
        value = value_fn(outcome)
        if value is None:
            continue
        groups.setdefault(outcome.key, []).append(value)
    return groups


def _replicate_values(groups, keys, rng, value_fn):
    """One replicate: resample keys, aggregate per-event values."""
    # Each resampled key contributes its full cluster of event values.
    total = 0.0
    count = 0
    for _ in range(len(keys)):
        key = rng.choice(keys)
        for value in groups[key]:
            total += value
            count += 1
    return total, count


def bootstrap_rate(outcomes, value_fn, replicate_value_fn=None,
                   replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED,
                   ci_level=CI_LEVEL):
    """Bootstrap a rate over key clusters.

    ``value_fn`` maps an outcome to its 0/1 contribution (None to skip).
    Returns (point, ci) where point is the observed rate and ci the
    percentile interval across replicates; uses per-key aggregation so the
    resampling is cluster-correct.
    """
    if replicates < 10000:
        raise BootstrapError("replicates must be at least 10000")
    groups = _cluster_sums(outcomes, value_fn)
    keys = list(groups)
    total_events = sum(len(v) for v in groups.values())
    if not keys or total_events == 0:
        return None, (None, None)
    point = sum(sum(v) for v in groups.values()) / total_events
    rng = random.Random(seed)
    rates = []
    for _ in range(replicates):
        total, count = _replicate_values(groups, keys, rng, value_fn)
        if count == 0:
            continue
        rates.append(total / count)
    if not rates:
        return point, (None, None)
    return point, _ci(ci_level, rates)


def bootstrap_mean(outcomes, value_fn,
                   replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED,
                   ci_level=CI_LEVEL):
    """Bootstrap a mean (e.g. MRR) over key clusters."""
    if replicates < 10000:
        raise BootstrapError("replicates must be at least 10000")
    groups = _cluster_sums(outcomes, value_fn)
    keys = list(groups)
    all_values = [v for values in groups.values() for v in values]
    if not keys or not all_values:
        return None, (None, None)
    point = sum(all_values) / len(all_values)
    rng = random.Random(seed)
    means = []
    for _ in range(replicates):
        total = 0.0
        count = 0
        for _ in range(len(keys)):
            key = rng.choice(keys)
            for value in groups[key]:
                total += value
                count += 1
        if count == 0:
            continue
        means.append(total / count)
    if not means:
        return point, (None, None)
    return point, _ci(ci_level, means)


def paired_difference(outcomes, scheme_value_fn, baseline_value_fn,
                      replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED,
                      ci_level=CI_LEVEL):
    """Bootstrap the paired scheme-baseline difference of a rate.

    Per event, the difference is computed on the SAME event (paired), then
    the mean difference is bootstrapped by choice-problem-key clusters.
    Returns (point_diff, ci).
    """
    if replicates < 10000:
        raise BootstrapError("replicates must be at least 10000")
    differences = {}
    for outcome in outcomes:
        scheme = scheme_value_fn(outcome)
        baseline = baseline_value_fn(outcome)
        if scheme is None or baseline is None:
            continue
        differences.setdefault(outcome.key, []).append(
            float(scheme) - float(baseline))
    keys = list(differences)
    all_values = [v for values in differences.values() for v in values]
    if not keys or not all_values:
        return None, (None, None)
    point = sum(all_values) / len(all_values)
    rng = random.Random(seed)
    deltas = []
    for _ in range(replicates):
        total = 0.0
        count = 0
        for _ in range(len(keys)):
            key = rng.choice(keys)
            for value in differences[key]:
                total += value
                count += 1
        if count == 0:
            continue
        deltas.append(total / count)
    if not deltas:
        return point, (None, None)
    return point, _ci(ci_level, deltas)


def top1_difference_ci(union_outcomes, scheme_fn, baseline_fn,
                       replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED,
                       ci_level=CI_LEVEL):
    """CI for the top-1 (or any rate) difference on a common event set.

    ``scheme_fn`` / ``baseline_fn`` map an outcome to its 0/1 value on the
    union; the bootstrap clusters by choice-problem key.
    """
    return paired_difference(union_outcomes, scheme_fn, baseline_fn,
                             replicates, seed, ci_level)
