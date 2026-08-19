#!/usr/bin/env python3
"""Terminal-outcome assembly for the #77 exact shortlist (AC-77-v1).

Given the per-representation grid results and the group-complete data
state, this module applies the spec #43 / #77 hard gates and forms exactly
one of the four legal terminal outcomes (AC-77-v1 seam 11):

1. **exact quality shortlist** — cells pass every hard gate including the
   #69 fixed-benchmark elimination, and the own-actionable ``+3pp`` lift
   is claimable (sufficient actionable group-complete + strata);
2. **收窄声称 shortlist** — the same hard-gate-passing cells exist but the
   lift is NOT claimed (thin / unmeasured strata);
3. **仅安全、涨幅未测准** — cells were evaluated and their safety /
   mispromotion / pollution were reported, but no cell passes the full
   gate set (e.g. #69 or the finite-H family eliminated the quality
   shortlist) and lift is unclaimable;
4. **无合格方案** — every cell eliminated (by #69 / Δ₁ / τ / finite-H /
   safety; e.g. τ not calibratable and/or #69 eliminated all four
   representations — RISK-77-1).

Hard gates (spec #43, AC-77-v1 seams 7-10), all on the **group-complete**
denominator (size < 32; the persisted ``competition_complete`` bit is
diagnostic only):

- **Δ₁ single-event cap**: Δ₁ = γ/(1+k) <= 0.5 (real snapshots:
  ``margin_base`` unavailable, only the hard cap applies).
- **Finite-H vs H=inf** on the common actionable union: top-1 CI lower >=
  -1pp, mispromotion-rate CI upper <= +1pp, majority-pollution-rate CI
  upper <= +1pp.  No finite H passing -> that ``(repr, K, γ, k, τ)``
  family cannot use H=inf as a production stand-in (H=inf alone is never
  shortlisted).
- **Overall safety** on all group-complete targets: top-1 CI lower >=
  -0.5pp and MRR CI lower >= -0.005.
- **Mispromotion**: denominator = actionable group-complete events where
  the shadow baseline already ranked the selection first; point <= 2% and
  95% CI upper <= 3%.
- **Majority pollution**: point <= 5% and 95% CI upper <= 7.5%.
- **#69 fixed-benchmark elimination** (quoted F1, not re-adjudicated):
  a representation that failed the fixed benchmark cannot enter the exact
  quality shortlist.

Claim rules (AC-77-v1 seam 10):

- ``+3pp`` own-actionable lift (top-1 CI lower > 0 and MRR CI lower >=
  -0.005) may be claimed only when the actionable group-complete sample is
  sufficient and the correction (rank > 1) / explicit_indexed strata are
  sufficient.  Thin strata are reported, never claimed, and never fail the
  whole ticket.

No raw text is produced: the decision carries representation ids,
parameters, numbers and counts only.
"""

from typing import Dict, List

from grid import rerun_milestones

# Strata that must be sufficient before a claim is accepted (spec #43 /
# #77 claim rules; report-only below the threshold).
STRATUM_MIN = 200
# Sufficient actionable group-complete sample before the own-actionable
# +3pp lift may be claimed (the #70 selection milestone repurposed as a
# claim condition — never a start gate, AC-77-v1 seam 10).
ACTIONABLE_LIFT_MIN = 1000


class ShortlistError(Exception):
    """A true fault in the shortlist decision inputs."""


def cell_gate_state(cell_record, benchmark_fail) -> Dict:
    """One cell's hard-gate state (all pass = quality-eligible).

    ``benchmark_fail``: True when the representation failed the #69 fixed
    benchmark (quoted F1) — such cells can never sit on the exact quality
    shortlist (AC-77 seam 8).
    """
    if "eliminated" in cell_record:
        reason = cell_record["eliminated"]
        return {"pass": False, "reason": "eliminated:%s" % reason}
    cell = cell_record["cell"]
    if cell.get("tau") is None:
        return {"pass": False, "reason": "eliminated:tau_not_calibratable"}
    if not cell_record.get("delta_one_ok", False):
        return {"pass": False, "reason": "eliminated:delta_one"}
    if benchmark_fail:
        # The #69 fixed-benchmark elimination applies to the whole
        # representation: the walk-forward still ran (diagnostic), but no
        # cell of it can sit on the exact quality shortlist.
        return {"pass": False, "reason": "eliminated:benchmark_69"}
    hard = cell_record.get("hard_gates") or {}
    if not hard.get("pass", False):
        reasons = []
        if not hard.get("safety_top1_ok", True):
            reasons.append("safety_top1")
        if not hard.get("safety_mrr_ok", True):
            reasons.append("safety_mrr")
        if not hard.get("mispromotion_point_ok", True):
            reasons.append("mispromotion_point")
        if not hard.get("mispromotion_ci_ok", True):
            reasons.append("mispromotion_ci")
        if not hard.get("pollution_point_ok", True):
            reasons.append("pollution_point")
        if not hard.get("pollution_ci_ok", True):
            reasons.append("pollution_ci")
        return {"pass": False, "reason": "hard_gates:%s" % ",".join(reasons)}
    # Finite-H family rule: a finite-H cell must pass against its H=inf
    # twin; the H=inf cell itself must NOT be shortlisted standalone unless
    # at least one finite-H twin of the same (repr, τ, K, γ, k) passes.
    return {"pass": True, "reason": "ok"}


def finite_h_family_map(cells, benchmark_fail) -> Dict:
    """(repr, tau_q, K, gamma, k) -> family gate state.

    A family is ``ok`` iff at least one finite-H cell of it passed its
    finite-H gate (all three paired CIs).  ``benchmark_fail`` propagates to
    the whole family.
    """
    families = {}
    for record in cells:
        if "eliminated" in record:
            continue
        cell = record["cell"]
        key = (cell["representation_id"], cell.get("tau_quantile"),
               cell["k_evidence"], cell["gamma"], cell["saturation_k"])
        half_life = cell["half_life"]
        entry = families.setdefault(key, {"ok": False, "has_inf": False,
                                          "n_finite_pass": 0})
        if benchmark_fail:
            continue
        if half_life == float("inf"):
            entry["has_inf"] = True
            continue
        gate = record.get("finite_h_gate")
        if gate is not None and gate.get("pass", False):
            entry["n_finite_pass"] += 1
            entry["ok"] = True
    return families


def cell_shortlist_eligible(cell_record, benchmark_fail, family_ok) -> bool:
    """A cell is quality-eligible iff every hard gate passes AND its
    finite-H family rule is satisfied.

    ``family_ok``: True when at least one finite-H twin of this cell's
    (repr, τ, K, γ, k) family passed its finite-H gate.  For a finite-H
    cell this is its own gate; for an H=inf cell the family must have a
    passing finite-H twin (H=inf alone is never a production stand-in,
    spec #43).
    """
    state = cell_gate_state(cell_record, benchmark_fail)
    if not state["pass"]:
        return False
    return family_ok


def assemble_shortlist(grid_results, data, benchmark_fail_reprs):
    """Assemble the per-representation eligibility and the terminal
    decision record (exactly one of the four legal outcomes).

    ``grid_results``: per-representation ``run_representation`` records.
    ``data``: the overall data-state dict (``data_counts`` of the reference
    replay).  ``benchmark_fail_reprs``: the set of representation ids that
    failed the #69 fixed benchmark (quoted F1, not re-adjudicated).
    """
    if not grid_results:
        raise ShortlistError("no grid results to decide on")

    per_representation = []
    for result in grid_results:
        name = result["representation"]
        cells = result.get("cells") or []
        benchmark_fail = name in (benchmark_fail_reprs or set())
        families = finite_h_family_map(cells, benchmark_fail)
        eligible = []
        eliminated_reasons = {}
        for record in cells:
            if "eliminated" in record:
                reason = "eliminated:%s" % record["eliminated"]
                eliminated_reasons[reason] = eliminated_reasons.get(reason,
                                                                    0) + 1
                continue
            cell = record["cell"]
            key = (cell["representation_id"], cell.get("tau_quantile"),
                   cell["k_evidence"], cell["gamma"], cell["saturation_k"])
            family_ok = families.get(key, {}).get("ok", False)
            if cell_shortlist_eligible(record, benchmark_fail, family_ok):
                eligible.append(record)
            else:
                state = cell_gate_state(record, benchmark_fail)
                if state["pass"] and not family_ok:
                    # The cell's own hard gates pass but its finite-H
                    # family has no passing finite-H twin (H=inf alone is
                    # never a production stand-in; a finite-H cell whose
                    # own gate failed is counted under its gate).
                    reason = "eliminated:finite_h_family"
                else:
                    reason = state["reason"]
                eliminated_reasons[reason] = eliminated_reasons.get(reason,
                                                                    0) + 1
        per_representation.append({
            "representation": name,
            "benchmark_69_fail": benchmark_fail,
            "eligible_cells": len(eligible),
            "eliminated_by_reason": eliminated_reasons,
            "evaluated_cells": sum(
                1 for c in cells if "eliminated" not in c),
            "eligible": [{
                "representation_id": c["cell"]["representation_id"],
                "half_life": c["cell"]["half_life"],
                "k_evidence": c["cell"]["k_evidence"],
                "gamma": c["cell"]["gamma"],
                "saturation_k": c["cell"]["saturation_k"],
                "tau_quantile": c["cell"].get("tau_quantile"),
                "tau": c["cell"].get("tau"),
                "metrics": c.get("metrics"),
                "ci": c.get("ci"),
                "hard_gates": c.get("hard_gates"),
                "finite_h_gate": c.get("finite_h_gate"),
            } for c in eligible],
        })

    quality_cells = [p for p in per_representation
                     if p["eligible_cells"] > 0]
    any_evaluated = any(p["evaluated_cells"] > 0
                        for p in per_representation)
    # A cell eliminated by the #69 benchmark gate (the whole representation
    # failed the fixed benchmark, quoted F1) or by the finite-H family rule
    # (H=inf alone is never a production stand-in) is a structural
    # elimination, not a measured hard-gate failure.  Only a cell that ran
    # and FAILED a measured gate (safety / mispromotion / pollution) is a
    # hard-gate failure.
    any_benchmark_fail = any(p["benchmark_69_fail"]
                             for p in per_representation)
    hard_gate_failures = 0
    finite_h_family_failures = 0
    for p in per_representation:
        reasons = p.get("eliminated_by_reason") or {}
        for reason, count in reasons.items():
            if reason.startswith("hard_gates"):
                hard_gate_failures += count
        finite_h_family_failures += reasons.get(
            "eliminated:finite_h_family", 0)

    # Claim state (AC-77 seam 10): +3pp is a claim condition, never a
    # ticket-fail.  The correction (rank>1) and explicit_indexed strata are
    # separate report-only layers.
    lift_claimable = False
    lift_reason = None
    actionable_gc = data.get("actionable_group_complete", 0)
    rank_gt1 = data.get("rank_gt1", 0)
    explicit_indexed = data.get("explicit_indexed", 0)
    if actionable_gc < ACTIONABLE_LIFT_MIN:
        lift_reason = ("actionable group-complete %d < %d: own-actionable "
                       "lift unclaimable"
                       % (actionable_gc, ACTIONABLE_LIFT_MIN))
    elif rank_gt1 < STRATUM_MIN:
        lift_reason = ("correction stratum (rank>1) %d < %d: 纠错 top-1 "
                       "lift unclaimable" % (rank_gt1, STRATUM_MIN))
    elif explicit_indexed < STRATUM_MIN:
        lift_reason = ("explicit_indexed %d < %d: stratum unclaimable"
                       % (explicit_indexed, STRATUM_MIN))
    else:
        # The lift itself is measured on the eligible cell's own actionable
        # group-complete events; sample-size sufficiency is handled above,
        # and the actual >=3pp / CI claims are checked per cell by the
        # report (the decision only gates the claimability of the sample).
        lift_claimable = True
        lift_reason = "strata sufficient; per-cell +3pp claim check in report"

    if quality_cells:
        outcome = ("exact_quality_shortlist" if lift_claimable
                   else "narrowed_claim_shortlist")
    elif any_benchmark_fail and not hard_gate_failures:
        # Every representation failed the #69 fixed benchmark (quoted F1):
        # the quality shortlist is impossible regardless of what the
        # walk-forward shows (RISK-77-1).  Report the diagnostic, keep
        # γ=0, and list the rerun milestones.  Lift cannot be claimed.
        outcome = "无合格方案"
        lift_claimable = False
        lift_reason = "#69 fixed-benchmark elimination (quoted F1): " \
                      "no representation may sit on the exact quality " \
                      "shortlist"
    elif finite_h_family_failures and not hard_gate_failures:
        # Every evaluated cell failed only because its finite-H family has
        # no passing finite-H twin (H=inf alone is never a production
        # stand-in, spec #43): the quality shortlist is impossible, and the
        # finite-H diagnostic is reported.  This is a structural
        # elimination -> 无合格方案.
        outcome = "无合格方案"
        lift_claimable = False
        lift_reason = ("no finite H passes the finite-H gates for any "
                       "(repr, τ, K, γ, k) family; H=inf alone is "
                       "never a production stand-in")
    elif any_evaluated and hard_gate_failures:
        # Cells ran and their safety/mispromotion/pollution were reported,
        # but no cell passes the full gate set (measured hard-gate
        # failures) and lift is unclaimable.
        outcome = "仅安全、涨幅未测准"
        lift_claimable = False
        lift_reason = "no cell passes the full hard-gate set"
    else:
        # Nothing evaluated: τ not calibratable and/or Δ₁ eliminated every
        # cell, or #69 eliminated all four representations (RISK-77-1).
        outcome = "无合格方案"
        lift_claimable = False
        lift_reason = "no cell evaluated (τ not calibratable / Δ₁ / #69)"

    return {
        "outcome": outcome,
        "lift_claimable": lift_claimable,
        "lift_reason": lift_reason,
        "data": data,
        "per_representation": per_representation,
        "total_eligible_cells": sum(p["eligible_cells"]
                                    for p in per_representation),
        "any_evaluated": any_evaluated,
        "rerun_milestones": rerun_milestones(actionable_gc),
        "live_gamma": 0.0,
    }
