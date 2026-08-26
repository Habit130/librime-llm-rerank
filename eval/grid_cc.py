#!/usr/bin/env python3
"""Pre-declared grid scan with suffix gates (Habit130/squirrel#157, AC-157-v1).

Candidate space (issue #157 body, frozen verbatim):

- routes: exactly the three frozen candidate-conditioned routes
  (``dedicated_qwen3_embedding_0_6b``, ``qwen_l28_candidate_span_mean``,
  ``dedicated_bge_m3``); nothing else is introduced.
- H in {8, 32, 128, 512, inf}; K_evidence in {8, 16, 32, 64};
  gamma in {0.5, 1, 2, 4}; k in {1, 3, 7}.
- alpha frozen at 0 (AC-106-v2); grid cells do not vary alpha.
- τ per route, only from the prefix calibration protocol (>=200 hard-negative
  queries, Q95/Q97.5/Q99/Q99.5); a route without a calibratable τ reports
  ``not_calibratable`` and leaves the shortlist; no invented τ.
- No continuous optimizer: flat pre-declared product grid, no extra cells.

The replay memory accumulates over the whole snapshot (suffix targets see
prefix history — the exact walk-forward); τ and grid *selection* run on the
prefix, and the quality/safety gates run on the **suffix claim set** only
(issue #157 body).  Public-B accuracy and the personal 2x2 r never enter.

Gates applied on the suffix claim set (issue #157 body, frozen):

1. **Δ₁ single-event boundary**: Δ₁ = gamma/(1+k) <= min(0.5,
   P10(margin_base)) where margin_base is from the prefix (events where the
   shadow baseline already ranked the final selection first; base margin vs
   the runner-up from the frozen base reconstruction — the facts do not
   persist per-candidate base scores, the report records the reconstruction).
   Cells violating the boundary are eliminated.
2. **Finite-H gates**: each finite H cell vs its H=inf twin must satisfy
   top-1 paired-difference 95% CI lower >= -1pp, mispromotion-rate
   difference CI upper <= +1pp and majority-pollution-rate difference CI
   upper <= +1pp, all on the common suffix actionable union.  When no finite
   H passes, the route cannot enter the shortlist (H=inf alone is never a
   production stand-in).
3. **Overall safety** on all group-complete suffix targets: top-1 paired CI
   lower >= -0.5pp and MRR paired CI lower >= -0.005.
4. **Mispromotion**: denominator = actionable suffix group-complete events
   where the shadow baseline ranked the selection first; point <= 2% and
   95% CI upper <= 3%.
5. **Majority pollution**: point <= 5% and 95% CI upper <= 7.5%.
6. **Own-actionable lift (+3pp)**: only when the suffix actionable
   group-complete sample is sufficient for the claim (>= 1000, frozen);
   top-1 absolute lift >= 3pp vs the shadow baseline, paired-difference CI
   lower > 0 and MRR diff CI lower >= -0.005.  When the sample cannot
   support the claim, the report **收窄声称** instead of claiming an
   unmeasured lift.

Bootstrap is key-clustered with a fixed seed and >= 10000 replicates
(``bootstrap.py``); differences are paired per event.  Cells are
deterministic and independent: each cell re-walks the replay.

No raw text is produced: cells carry route ids, parameter values, τ
quantiles and numeric evidence only.
"""

from bootstrap import bootstrap_rate, paired_difference
from metrics import (mispromotion_events, mrr, pollution_distribution,
                     pollution_mass, top1)
from walkforward_cc import (BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED,
                            L28_POOLING_RULE, PAYLOAD_RULE,
                            QWEN3_EMB_QUERY_INSTRUCTION, DELTA_ONE_CAP,
                            CI_LEVEL, delta_one)


class GridError(Exception):
    """A true fault in the suffix grid scan inputs."""


# Pre-declared candidate space (spec #43, frozen verbatim).
HALF_LIVES = (8, 32, 128, 512, float("inf"))
K_EVIDENCE = (8, 16, 32, 64)
GAMMAS = (0.5, 1.0, 2.0, 4.0)
SATURATION_KS = (1, 3, 7)

# AC-157-V1 hard-gate constants (issue #157 body, frozen).
FINITE_H_TOP1_LOWER = -0.01        # top-1 CI lower >= -1pp
FINITE_H_MISPROMOTION_UPPER = 0.01
FINITE_H_POLLUTION_UPPER = 0.01
SAFETY_TOP1_LOWER = -0.005         # top-1 CI lower >= -0.5pp
SAFETY_MRR_LOWER = -0.005          # MRR CI lower >= -0.005
MISPROMOTION_POINT = 0.02
MISPROMOTION_CI_UPPER = 0.03
POLLUTION_POINT = 0.05
POLLUTION_CI_UPPER = 0.075
LIFT_PP = 0.03
# Suffix claim-support minimum for +3pp (frozen pre-declared; below it the
# report 收窄声称 instead of claiming an unmeasured lift).
LIFT_CLAIM_MIN_ACTIONABLE = 1000

# Rerun milestones when no legal shortlist forms.
RERUN_MILESTONES = (1500, 2000, 3000, 5000)
RERUN_STEP = 2500


def predeclared_cells(route_id):
    """The flat product grid for one route (no τ yet).

    Ordering: (K_evidence, gamma, k, H) with H innermost, so every
    (K, gamma, k) group carries all five H values contiguously — the
    H=inf twin of each finite-H cell is always in the same group.
    """
    cells = []
    for k_evidence in K_EVIDENCE:
        for gamma in GAMMAS:
            for saturation_k in SATURATION_KS:
                for half_life in HALF_LIVES:
                    cells.append({
                        "route_id": route_id,
                        "half_life": half_life,
                        "k_evidence": k_evidence,
                        "gamma": gamma,
                        "saturation_k": saturation_k,
                    })
    return cells


def delta_one_ok(gamma, saturation_k, margin_p10=None):
    """Δ₁ boundary: Δ₁ <= min(0.5, P10(margin_base)).

    ``margin_p10`` is the P10 over the prefix's base margins (None when no
    prefix margin event exists: then only the 0.5 hard cap applies).
    """
    return delta_one(gamma, saturation_k) <= min(
        DELTA_ONE_CAP, margin_p10 if margin_p10 is not None else DELTA_ONE_CAP)


def grid_manifest(replicates):
    """The pre-declared grid manifest (frozen before metrics; AC-157-3)."""
    return {
        "declared_before_metrics": True,
        "alpha": 0.0,
        "half_lives": [("inf" if h == float("inf") else h)
                       for h in HALF_LIVES],
        "k_evidence": list(K_EVIDENCE),
        "gamma": list(GAMMAS),
        "saturation_k": list(SATURATION_KS),
        "tau_quantiles": ["Q95", "Q97.5", "Q99", "Q99.5"],
        "payload_rule": PAYLOAD_RULE,
        "qwen3_emb_query_instruction": QWEN3_EMB_QUERY_INSTRUCTION,
        "l28_pooling_rule": L28_POOLING_RULE,
        "replicates": replicates,
    }


def data_counts(outcomes):
    """Data-state counts over the replayable outcomes (AC-157-V1).

    Returns the group-complete counts and the report-only strata
    (explicit_indexed / rank>1 / coverage / hard-negative pool) that are
    never start gates and never claim layers when thin.
    """
    group_complete = [o for o in outcomes if o.group_complete]
    keys = set(o.key_hash for o in group_complete)
    explicit_indexed = sum(1 for o in group_complete
                           if o.confirmation_source == "explicit_indexed")
    rank_gt1 = sum(1 for o in group_complete if o.baseline_rank != 1)
    actionable = [o for o in group_complete if o.actionable]
    return {
        "replayable": len(outcomes),
        "group_complete": len(group_complete),
        "keys": len(keys),
        "explicit_indexed": explicit_indexed,
        "rank_gt1": rank_gt1,
        "actionable_group_complete": len(actionable),
        "actionable_keys": len(set(o.key_hash for o in actionable)),
        "coverage": (len(group_complete) / len(outcomes)
                     if outcomes else 0.0),
    }


def facts_only_data_count(targets):
    """Facts-only counts for the legal 无合格方案 terminal (RISK-157-3).

    When every route is provably `not_calibratable` from the prefix (fewer
    than 200 hard-negative queries, a property of the facts alone), the
    run reports the legal terminal without spending any FX forward; the
    data-state block then carries the counts that are knowable from the
    snapshot (replayable / group-complete / keys / strata).  Actionability
    needs a replay, so it is not invented here.
    """
    group_complete = [t for t in targets if t.group_complete]
    keys = set(t.key_hash for t in group_complete)
    explicit_indexed = sum(1 for t in group_complete
                           if t.confirmation_source == "explicit_indexed")
    rank_gt1 = sum(1 for t in group_complete if (
        not (t.display_page == 1 and t.display_rank == 1)))
    return {
        "replayable": len(targets),
        "group_complete": len(group_complete),
        "keys": len(keys),
        "explicit_indexed": explicit_indexed,
        "rank_gt1": rank_gt1,
        "actionable_group_complete": 0,
        "actionable_keys": 0,
        "coverage": (len(group_complete) / len(targets)
                     if targets else 0.0),
        "actionable_note": "not scored: no route calibratable from the "
                           "prefix (RISK-157-3)",
    }


def run_cell(replay, cell, seed=BOOTSTRAP_SEED, replicates=BOOTSTRAP_REPLICATES):
    """Run one grid cell; suffix gates + prefix selection metrics.

    Returns a dict with point estimates, bootstrap CIs (95%, key-clustered,
    fixed seed, >=10000 replicates), the per-gate pass state on the suffix
    claim set, and the cell's prefix selection metrics (the grid scan runs
    on the prefix; quality/safety gates on the suffix claim set only).
    ``cell`` carries the oracle params, ``route_id`` and
    ``margin_p10`` (prefix-derived).
    """
    from oracle import OracleParams
    params = OracleParams(tau=cell["tau"], k_evidence=cell["k_evidence"],
                          half_life=cell["half_life"],
                          saturation_k=cell["saturation_k"])
    outcomes = replay.replay(params, cell["gamma"])
    suffix = [o for o in outcomes if not o.in_prefix]
    complete = [o for o in suffix if o.group_complete]
    actionable_complete = [o for o in complete if o.actionable]
    prefix = [o for o in outcomes if o.in_prefix]
    prefix_complete = [o for o in prefix if o.group_complete]
    prefix_actionable = [o for o in prefix_complete if o.actionable]

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
    safety_top1 = paired_difference(complete, top1_fn, baseline_fn,
                                    replicates=replicates, seed=seed)
    safety_mrr = paired_difference(complete, mrr_fn, baseline_mrr_fn,
                                   replicates=replicates, seed=seed)

    mp_den, mp_num = mispromotion_events(complete)
    mp_rate = (len(mp_num) / len(mp_den)) if mp_den else None
    mp_ci = (None, None)
    if mp_den:
        _, mp_ci = bootstrap_rate(
            mp_den, lambda o: 0.0 if o.scheme_rank == 1 else 1.0,
            replicates=replicates, seed=seed)

    poll = pollution_distribution(complete)
    majority = poll["majority_share"] if poll else None
    poll_ci = (None, None)
    if poll and poll["count"]:
        _, poll_ci = bootstrap_rate(
            actionable_complete,
            lambda o: 1.0 if (pollution_mass(o) or 0.0) >= 0.5 else 0.0,
            replicates=replicates, seed=seed)

    # Own-actionable +3pp claim: only when the suffix actionable
    # group-complete sample is sufficient (frozen; else 收窄声称).
    top1_point = top1(actionable_complete)
    baseline_point = None
    eligible_point = [o for o in actionable_complete
                      if o.scheme_rank is not None]
    if eligible_point:
        baseline_point = sum(1 for o in eligible_point
                             if o.baseline_rank == 1) / len(eligible_point)
    lift_pass = None
    lift_reason = None
    actionable_claimable = len(actionable_complete) >= LIFT_CLAIM_MIN_ACTIONABLE
    if not actionable_claimable:
        lift_reason = ("suffix actionable group-complete %d < %d: +3pp "
                       "unclaimable"
                       % (len(actionable_complete), LIFT_CLAIM_MIN_ACTIONABLE))
    elif top1_point is None or baseline_point is None:
        lift_pass = False
        lift_reason = "no sufficient actionable sample for a point estimate"
    else:
        lift_pass = (
            top1_point - baseline_point >= LIFT_PP
            and top1_diff[1][0] is not None and top1_diff[1][0] > 0.0
            and mrr_diff[1][0] is not None and mrr_diff[1][0] >= -0.005)
        lift_reason = None if lift_pass else (
            "lift did not reach the +3pp claim (point %.4f, top-1 CI lower "
            "%.4f, MRR CI lower %.4f)"
            % (top1_point - baseline_point, top1_diff[1][0],
               mrr_diff[1][0]))

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
        "prefix_metrics": {
            # The grid scan runs on the prefix (selection table).  Reported
            # counts and points only; never gate the suffix claims.
            "actionable_group_complete": len(prefix_actionable),
            "group_complete": len(prefix_complete),
            "top1": top1(prefix_actionable),
            "baseline_top1": _baseline_point(prefix_actionable),
            "mrr": mrr(prefix_actionable),
        },
        "metrics": {
            "top1": top1_point,
            "baseline_top1": baseline_point,
            "mrr": mrr(actionable_complete),
            "mispromotion_rate": mp_rate,
            "mispromotion_denominator": len(mp_den),
            "mispromotion_numerator": len(mp_num),
            "pollution": poll,
            "majority_pollution_rate": majority,
            "actionable_group_complete": len(actionable_complete),
            "group_complete": len(complete),
        },
        "ci": {
            "top1_vs_baseline": top1_diff,
            "mrr_vs_baseline": mrr_diff,
            "safety_top1_vs_baseline": safety_top1,
            "safety_mrr_vs_baseline": safety_mrr,
            "mispromotion": mp_ci,
            "majority_pollution": poll_ci,
        },
        "delta_one": delta_one(cell["gamma"], cell["saturation_k"]),
        "delta_one_ok": delta_one_ok(
            cell["gamma"], cell["saturation_k"], cell.get("margin_p10")),
        "hard_gates": {
            "pass": hard_pass,
            "safety_top1_ok": safety_top1_ok,
            "safety_mrr_ok": safety_mrr_ok,
            "mispromotion_point_ok": mp_point_ok,
            "mispromotion_ci_ok": mp_ci_ok,
            "pollution_point_ok": poll_point_ok,
            "pollution_ci_ok": poll_ci_ok,
        },
        "lift": {
            "claimable": actionable_claimable and lift_pass is True,
            "pass": lift_pass,
            "reason": lift_reason,
        },
        "suffix_counts": {
            "actionable_group_complete": len(actionable_complete),
            "group_complete": len(complete),
        },
        "_outcomes": outcomes,  # internal: finite-H gate only
    }


def finite_h_gate(inf_cell, finite_cell, seed=BOOTSTRAP_SEED,
                  replicates=BOOTSTRAP_REPLICATES, ci_level=CI_LEVEL):
    """Finite-H vs H=inf paired gates on the common suffix actionable union.

    All three paired-difference CIs must hold simultaneously: top-1 lower
    bound >= -1pp, mispromotion upper bound <= +1pp, majority-pollution
    upper bound <= +1pp.  The comparison runs on the common actionable
    union (events actionable for either cell); an event without evidence
    for one cell scores as that cell's shadow baseline (issue #157 body:
    "无证据事件按该方案影子基线计分").
    """
    from collections import defaultdict

    inf_by_id = {o.event_id: o for o in inf_cell["_outcomes"]}
    finite_by_id = {o.event_id: o for o in finite_cell["_outcomes"]}
    union_ids = sorted(set(inf_by_id) | set(finite_by_id))

    def top1_value(outcome):
        if not outcome.actionable:
            return 1.0 if outcome.baseline_rank == 1 else 0.0
        if outcome.scheme_rank is None:
            return None
        return 1.0 if outcome.scheme_rank == 1 else 0.0

    def mispromotion_value(outcome):
        if outcome.baseline_rank != 1:
            return None
        if not outcome.actionable:
            return 0.0  # no evidence -> the shadow baseline outcome
        if outcome.scheme_rank is None:
            return None
        return 0.0 if outcome.scheme_rank == 1 else 1.0

    def majority_pollution_value(outcome):
        if not outcome.actionable:
            return 0.0  # no evidence -> the shadow baseline outcome
        mass = pollution_mass(outcome)
        if mass is None:
            return None
        return 1.0 if mass >= 0.5 else 0.0

    def diff_for(value_fn):
        values = []
        for event_id in union_ids:
            left = value_fn(finite_by_id[event_id])
            right = value_fn(inf_by_id[event_id])
            if left is None or right is None:
                continue
            values.append((finite_by_id[event_id].key_hash,
                           left - right))
        if not values:
            return None, (None, None)
        groups = defaultdict(list)
        for key_hash, value in values:
            groups[key_hash].append(value)
        keys = list(groups)
        point = sum(sum(v) for v in groups.values()) / len(values)
        import random
        rng = random.Random(seed)
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

    top1_diff = diff_for(top1_value)
    misp_diff = diff_for(mispromotion_value)
    poll_diff = diff_for(majority_pollution_value)

    top1_ok = top1_diff[1][0] is None or top1_diff[1][0] >= FINITE_H_TOP1_LOWER
    misp_ok = (misp_diff[1][1] is None
               or misp_diff[1][1] <= FINITE_H_MISPROMOTION_UPPER)
    poll_ok = (poll_diff[1][1] is None
               or poll_diff[1][1] <= FINITE_H_POLLUTION_UPPER)
    return {
        "pass": top1_ok and misp_ok and poll_ok,
        "union_events": len(union_ids),
        "top1_diff": top1_diff,
        "mispromotion_diff": misp_diff,
        "majority_pollution_diff": poll_diff,
    }


def run_route(replay, route_id, tau_status, data, seed=BOOTSTRAP_SEED,
              replicates=BOOTSTRAP_REPLICATES, max_cells=None,
              margin_p10=None):
    """Run the whole grid for one route.

    ``tau_status`` comes from the prefix calibration protocol (AC-157-V1;
    ``calibration_cc.calibrate_tau``): ``not_calibratable`` -> no τ is
    invented and the route leaves the shortlist.  ``data`` is the split
    data-state passed through for the report.  Returns the per-cell results
    and the data state.
    """
    cells = []
    if tau_status.get("state") != "calibratable":
        for cell in predeclared_cells(route_id):
            cells.append({"cell": cell,
                          "eliminated": "tau_not_calibratable"})
        result = {
            "route_id": route_id,
            "tau": tau_status,
            "cells": cells,
            "data": data,
            "selection": "not_run",
        }
        if max_cells is not None:
            result["partial_scan"] = True
        return result
    for quantile, tau_value in sorted(
            tau_status["quantiles"].items(), key=lambda item: float(item[0])):
        for cell in predeclared_cells(route_id):
            cell = dict(cell, tau=tau_value, tau_quantile=quantile)
            if not delta_one_ok(cell["gamma"], cell["saturation_k"],
                                margin_p10=margin_p10):
                cells.append({"cell": cell, "eliminated": "delta_one"})
                continue
            cells.append(run_cell(replay, dict(cell, margin_p10=margin_p10),
                                  seed=seed, replicates=replicates))
            if max_cells is not None and \
                    len([c for c in cells if "eliminated" not in c]) >= \
                    max_cells:
                return {
                    "route_id": route_id,
                    "tau": tau_status,
                    "cells": cells,
                    "data": data,
                    "selection": "not_run",
                    "partial_scan": True,
                }
    # Finite-H family gates: attach to each finite-H cell.
    _attach_finite_h_gates(cells, seed=seed, replicates=replicates)
    # Strip the internal per-cell outcome lists: the report digest carries
    # ids, numbers and cell identities only, never per-event outcomes.
    for record in cells:
        record.pop("_outcomes", None)
    return {"route_id": route_id, "tau": tau_status, "cells": cells,
            "data": data, "selection": "not_run"}


def _attach_finite_h_gates(cells, seed, replicates):
    finite = {}
    inf = {}
    for record in cells:
        if "eliminated" in record:
            continue
        cell = record["cell"]
        key = (cell["tau_quantile"], cell["k_evidence"], cell["gamma"],
               cell["saturation_k"])
        if cell["half_life"] == float("inf"):
            inf[key] = record
        else:
            finite.setdefault(key, []).append(record)
    for key, finite_records in finite.items():
        inf_record = inf.get(key)
        if inf_record is None:
            continue
        for finite_record in finite_records:
            gate = finite_h_gate(inf_record, finite_record,
                                 seed=seed, replicates=replicates)
            finite_record["finite_h_gate"] = {
                "pass": gate["pass"],
                "union_events": gate["union_events"],
                "top1_diff": gate["top1_diff"],
                "mispromotion_diff": gate["mispromotion_diff"],
                "majority_pollution_diff": gate["majority_pollution_diff"],
            }


def data_insufficient(suffix_counts):
    """数据不足 terminal check (AC-157-V1, legal terminal).

    Suffix has no events past the cutoff (or no group-complete suffix
    events): the claim set cannot support the contract gates -> 数据不足,
    which is a legal terminal, never an implementation failure.
    """
    return suffix_counts["group_complete"] == 0


def rerun_milestones(actionable_group_complete):
    milestones = list(RERUN_MILESTONES)
    if actionable_group_complete > RERUN_MILESTONES[-1]:
        next_milestone = RERUN_MILESTONES[-1] + RERUN_STEP
        while next_milestone <= actionable_group_complete:
            next_milestone += RERUN_STEP
        milestones.append(next_milestone)
    return milestones