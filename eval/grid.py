#!/usr/bin/env python3
"""Pre-declared grid scan with safety gates (Habit130/squirrel#70/#77).

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
- α is frozen at 0 (AC-106-v2).  Grid cells do not vary α.
- No continuous optimizer is used anywhere: the scan is a flat pre-declared
  product grid.

Rank / safety denominator (AC-77-v1 seam 3): an event enters the top-1 /
MRR / mispromotion / safety / pollution / event-count gates iff it is
**group-complete** (saved same-group competition size < N, N=32).  The
persisted ``competition_complete`` bit is a diagnostic only.

Gates applied per configuration (spec #43, AC-77-v1 seams 7-10):

1. **Δ₁ single-event safety boundary**: Δ₁ = γ/(1+k) must satisfy
   Δ₁ <= min(0.5, P10(margin_base)).  On real snapshots margin_base is
   unavailable (facts do not persist per-candidate base scores), so the
   engine enforces the hard cap Δ₁ <= 0.5 and records the unavailable state
   explicitly; synthetic fixtures inject base scores and pin the full
   boundary.  Configurations violating the boundary are eliminated.
2. **Finite-H gates**: each finite H vs H=inf must simultaneously satisfy
   top-1 paired-difference 95% CI lower bound >= -1pp, mispromotion-rate
   difference CI upper bound <= +1pp and majority-pollution-rate difference
   CI upper bound <= +1pp, all on the common actionable group-complete
   union.  When no finite H passes, H=inf alone cannot be a production
   stand-in (it is reported, never shortlisted on its own).
3. **Overall safety** on all group-complete targets: top-1 paired CI lower
   bound >= -0.5pp and MRR paired CI lower bound >= -0.005.
4. **Mispromotion**: denominator = actionable group-complete events where
   the shadow baseline already ranked the selection first; point <= 2% and
   95% CI upper <= 3%.
5. **Majority pollution**: point <= 5% and 95% CI upper <= 7.5%.
6. **#69 fixed-benchmark elimination** (quoted F1, not re-adjudicated):
   a representation that failed the fixed benchmark cannot enter the exact
   quality shortlist.  Its walk-forward still runs and is reported.

The #70 D7 selection-milestone gates are **superseded** (AC-77-v1): the
start gate is #76's group-complete replayable >= 1000 and keys >= 100, and
the milestone gates (1000 actionable-complete / 200 explicit_indexed / 200
rank>1) are claim/stratum rules, not start gates.  `+3pp` is a claim
condition, not a ticket-fail.

No raw text is produced: results carry representation ids, parameter
values, numbers and event counts.
"""

import math

from bootstrap import bootstrap_rate, paired_difference
from calibration import MIN_HARD_NEGATIVE_QUERIES, calibrate_tau
from metrics import (majority_pollution_rate, mispromotion_events,
                     mispromotion_rate, pollution_distribution,
                     pollution_mass, top1, mrr)
from walkforward import (DELTA_ONE_CAP, GROUP_COMPLETE_N, OracleParams,
                         delta_one, margin_base_unavailable)


class GridError(Exception):
    """A true fault in the grid scan inputs."""


# Pre-declared candidate space (spec #43).
HALF_LIVES = (8, 32, 128, 512, float("inf"))
K_EVIDENCE = (8, 16, 32, 64)
GAMMAS = (0.5, 1.0, 2.0, 4.0)
SATURATION_KS = (1, 3, 7)

# AC-77 hard-gate constants (spec #43, frozen).
# Finite-H vs H=inf paired gates on the common actionable union.
FINITE_H_TOP1_LOWER = -0.01      # top-1 CI lower >= -1pp
FINITE_H_MISPROMOTION_UPPER = 0.01   # mispromotion CI upper <= +1pp
FINITE_H_POLLUTION_UPPER = 0.01      # majority-pollution CI upper <= +1pp
# Overall safety on all group-complete targets.
SAFETY_TOP1_LOWER = -0.005       # top-1 CI lower >= -0.5pp
SAFETY_MRR_LOWER = -0.005        # MRR CI lower >= -0.005
# Mispromotion hard gates.
MISPROMOTION_POINT = 0.02        # point <= 2%
MISPROMOTION_CI_UPPER = 0.03     # 95% CI upper <= 3%
# Majority-pollution hard gates.
POLLUTION_POINT = 0.05           # point <= 5%
POLLUTION_CI_UPPER = 0.075       # 95% CI upper <= 7.5%
# +3pp own-actionable lift claim condition.
LIFT_PP = 0.03
# Rerun milestones (可作用组完整) when no shortlist forms.
RERUN_MILESTONES = (1500, 2000, 3000, 5000)
RERUN_STEP = 2500


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


def data_counts(outcomes):
    """Data-state counts over the replayable outcomes (AC-77 seam 10).

    Returns the group-complete counts and the report-only strata
    (explicit_indexed / rank>1 / coverage / hard-negative pool) that are
    never start gates and never claim layers when thin.
    """
    group_complete = [o for o in outcomes if o.group_complete]
    keys = set(o.key for o in group_complete)
    explicit_indexed = sum(1 for o in group_complete
                           if o.confirmation_source == "explicit_indexed")
    rank_gt1 = sum(1 for o in group_complete
                   if o.baseline_rank != 1)
    actionable = [o for o in group_complete if o.actionable]
    actionable_keys = set(o.key for o in actionable)
    return {
        "replayable": len(outcomes),
        "group_complete": len(group_complete),
        "keys": len(keys),
        "explicit_indexed": explicit_indexed,
        "rank_gt1": rank_gt1,
        "actionable_group_complete": len(actionable),
        "actionable_keys": len(actionable_keys),
        "coverage": (len(group_complete) / len(outcomes)
                     if outcomes else 0.0),
    }


def start_gate_passed(counts, min_group_complete=1000, min_keys=100):
    """The #76 start gate (AC-77 seam 10, #70 D7 superseded).

    Group-complete replayable events >= 1000 and >= 100 choice-problem
    keys.  The strata (explicit_indexed / rank>1 / coverage / hard-neg /
    actionable) are report-only and never block the milestone run.
    """
    return (counts["group_complete"] >= min_group_complete
            and counts["keys"] >= min_keys)


def rerun_milestones(actionable_group_complete):
    """Next rerun milestones at 可作用组完整 counts (spec #43).

    1500 / 2000 / 3000 / 5000, then every +2500.  Used when no legal
    shortlist forms and live γ stays 0.
    """
    milestones = list(RERUN_MILESTONES)
    if actionable_group_complete > RERUN_MILESTONES[-1]:
        next_milestone = RERUN_MILESTONES[-1] + RERUN_STEP
        while next_milestone <= actionable_group_complete:
            next_milestone += RERUN_STEP
        milestones.append(next_milestone)
    return milestones


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
            if outcome.scheme_rank is None:
                return None
            return 1.0 if outcome.scheme_rank == 1 else 0.0
        raise GridError("unknown rate metric %r" % metric)
    return fn


def _stratum_gates(outcomes, seed, replicates=10000):
    """Per-stratum quality gates (spec #43 / #77 claim rules).

    Any stratum (confirmation source x confirmation rank) reaching >=200
    actionable **group-complete** events must satisfy, on that stratum's
    own events:

    - top-1 non-inferiority vs the shadow baseline: the key-clustered
      paired-difference 95% CI lower bound >= -1pp;
    - mispromotion: point estimate <= 2% and 95% CI upper bound <= 3%
      (denominator = actionable group-complete events where the baseline
      ranked the selection first).

    Strata below 200 events are reported with ``applicable: false`` and
    no gate result — a thin stratum is reported, never claimed, and never
    fails the whole run (AC-77 seam 10).
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
            if o.scheme_rank is None:
                return None  # non-reconstructable: excluded, never a miss
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
    key-clustered, fixed seed, >=10000 replicates) for top-1, MRR,
    mispromotion and majority pollution on the cell's own actionable
    **group-complete** events (AC-77 seam 3; the persisted
    ``competition_complete`` bit is diagnostic only).  The hard-gate
    results (safety / mispromotion / pollution) are attached as
    ``hard_gates`` so the shortlist assembler can apply them.
    """
    outcomes, summary = _cell_outcomes(replay, cell)
    actionable_complete = [o for o in outcomes
                           if o.actionable and o.group_complete]
    top1_point = top1(outcomes, complete_only=True, actionable_only=True)
    mrr_point = mrr(outcomes, complete_only=True, actionable_only=True)
    mp_den, mp_num = mispromotion_events(outcomes, complete_only=True)
    mp_rate = (len(mp_num) / len(mp_den)) if mp_den else None
    poll = pollution_distribution(outcomes)
    majority = poll["majority_share"] if poll else None

    def top1_fn(o):
        if o.scheme_rank is None:
            return None  # non-reconstructable: excluded, never a miss
        return 1.0 if o.scheme_rank == 1 else 0.0

    def baseline_fn(o):
        return 1.0 if o.baseline_rank == 1 else 0.0

    def mrr_fn(o):
        if o.scheme_rank is None:
            return None
        return 1.0 / o.scheme_rank

    def baseline_mrr_fn(o):
        return 1.0 / o.baseline_rank

    top1_diff = paired_difference(actionable_complete, top1_fn, baseline_fn,
                                  replicates=replicates, seed=seed)
    mrr_diff = paired_difference(actionable_complete, mrr_fn,
                                 baseline_mrr_fn, replicates=replicates,
                                 seed=seed)
    # Overall safety on ALL group-complete targets (spec #43 总体安全).
    all_complete = [o for o in outcomes if o.group_complete]
    safety_top1 = paired_difference(all_complete, top1_fn, baseline_fn,
                                    replicates=replicates, seed=seed)
    safety_mrr = paired_difference(all_complete, mrr_fn, baseline_mrr_fn,
                                   replicates=replicates, seed=seed)

    # Mispromotion CI: bootstrap the rate on the denominator events.
    mp_ci = (None, None)
    if mp_den:
        _, mp_ci = bootstrap_rate(
            mp_den, lambda o: 0.0 if o.scheme_rank == 1 else 1.0,
            replicates=replicates, seed=seed)

    # Majority-pollution rate CI (spec #43 证据污染门槛).
    poll_ci = (None, None)
    if poll and poll["count"]:
        _, poll_ci = bootstrap_rate(
            actionable_complete,
            lambda o: 1.0 if (pollution_mass(o) or 0.0) >= 0.5 else 0.0,
            replicates=replicates, seed=seed)

    safety_top1_ok = (safety_top1[1][0] is None
                      or safety_top1[1][0] >= SAFETY_TOP1_LOWER)
    safety_mrr_ok = (safety_mrr[1][0] is None
                     or safety_mrr[1][0] >= SAFETY_MRR_LOWER)
    mp_point_ok = mp_rate is None or mp_rate <= MISPROMOTION_POINT
    mp_ci_ok = mp_ci[1] is None or mp_ci[1] <= MISPROMOTION_CI_UPPER
    poll_point_ok = majority is None or majority <= POLLUTION_POINT
    poll_ci_ok = poll_ci[1] is None or poll_ci[1] <= POLLUTION_CI_UPPER
    hard_pass = (safety_top1_ok and safety_mrr_ok and mp_point_ok
                 and mp_ci_ok and poll_point_ok and poll_ci_ok)
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
            "actionable_group_complete": len(actionable_complete),
            "group_complete": len(all_complete),
        },
        "ci": {
            "top1_vs_baseline": top1_diff,
            "mrr_vs_baseline": mrr_diff,
            "safety_top1_vs_baseline": safety_top1,
            "safety_mrr_vs_baseline": safety_mrr,
            "mispromotion": mp_ci,
            "majority_pollution": poll_ci,
        },
        "stratum_gates": _stratum_gates(outcomes, seed, replicates),
        "delta_one": delta_one(cell["gamma"], cell["saturation_k"]),
        "delta_one_ok": delta_one_ok(cell["gamma"], cell["saturation_k"],
                                     margin_base=None),
        "hard_gates": {
            "pass": hard_pass,
            "safety_top1_ok": safety_top1_ok,
            "safety_mrr_ok": safety_mrr_ok,
            "mispromotion_point_ok": mp_point_ok,
            "mispromotion_ci_ok": mp_ci_ok,
            "pollution_point_ok": poll_point_ok,
            "pollution_ci_ok": poll_ci_ok,
        },
    }


def run_representation(replay, name, seed, replicates=10000,
                       max_cells=None):
    """Run the whole grid for one representation (all τ candidates).

    Returns the per-cell results, the τ calibration state and the data
    state (group-complete counts / keys / strata).  The replay is re-walked
    per cell — deterministic and pure, so cells are independent and
    reproducible.  The data counts come from a scheme-independent reference
    replay (τ = 0, K = 8, H = inf, k = 1, γ = 0), which measures the
    data's group-complete / actionable union without depending on any
    candidate's parameters.  ``max_cells`` limits evaluated cells (driver
    smoke / test use only; the report then carries a ``partial_scan``
    marker).

    #70 D7 milestone gates are superseded (AC-77-v1): the start gate is
    #76's group-complete replayable >= 1000 and keys >= 100; the strata
    (explicit_indexed / rank>1 / actionable / hard-neg) are report-only.
    The terminal shortlist decision is assembled by ``shortlist.py``.
    """
    status = calibrate_tau(replay)
    cells = []
    reference_outcomes, _ = _cell_outcomes(replay, {
        "tau": 0.0,
        "k_evidence": K_EVIDENCE[0],
        "half_life": HALF_LIVES[-1],
        "saturation_k": SATURATION_KS[0],
    }, gamma=0.0)
    counts = data_counts(reference_outcomes)
    if status["state"] != "calibratable":
        # τ not calibratable: the τ-dependent evaluation cells cannot run
        # (no invented τ).  The Δ₁ single-event safety boundary is a pure
        # parameter function, so it is still reported over the whole
        # pre-declared space; the data state comes from the reference
        # replay so the diagnostic always carries the data-readiness state.
        for cell in predeclared_cells(name):
            cell = dict(cell, tau=None, tau_quantile=None)
            if not delta_one_ok(cell["gamma"], cell["saturation_k"]):
                cells.append({"cell": cell, "eliminated": "delta_one"})
            else:
                cells.append({"cell": cell, "eliminated": "tau_not_calibratable"})
        result = {
            "representation": name,
            "tau": status,
            "cells": cells,
            "data": counts,
            "selection": "not_run",
        }
        if max_cells is not None:
            result["partial_scan"] = True
        return result
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
    # H=inf alone cannot be a production stand-in; it is reported, never
    # shortlisted on its own).
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
    result = {
        "representation": name,
        "tau": status,
        "cells": cells,
        "data": counts,
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
    event id).  top-1 is only computed over group-complete events;
    mispromotion over the spec's denominator (actionable group-complete
    events where the baseline ranked the selection first); pollution over
    actionable events.
    """
    from collections import defaultdict

    inf_by_id = {o.event_id: o for o in inf_cell["outcomes"]}
    finite_by_id = {o.event_id: o for o in finite_cell["outcomes"]}
    union_ids = sorted(set(inf_by_id) & set(finite_by_id))

    def top1_fn(outcome):
        if not outcome.group_complete or not outcome.actionable:
            return None
        if outcome.scheme_rank is None:
            return None  # non-reconstructable: excluded, never a miss
        return 1.0 if outcome.scheme_rank == 1 else 0.0

    def mispromotion_fn(outcome):
        if not outcome.group_complete or not outcome.actionable:
            return None
        if outcome.baseline_rank != 1:
            return None
        if outcome.scheme_rank is None:
            return None
        return 0.0 if outcome.scheme_rank == 1 else 1.0

    def majority_pollution_fn(outcome):
        """1.0 iff the event's pollution mass is >= 0.5 (spec's
        majority-pollution indicator); None when not measurable."""
        if not outcome.actionable:
            return None
        mass = pollution_mass(outcome)
        if mass is None:
            return None
        return 1.0 if mass >= 0.5 else 0.0

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
    # Spec: majority-pollution-RATE difference CI upper bound <= +1pp.
    # The per-event indicator is pollution_mass >= 0.5, so the gated
    # statistic is the difference in the majority-polluted event share.
    poll_diff = diff_for(majority_pollution_fn, pairs_finite, pairs_inf)

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
