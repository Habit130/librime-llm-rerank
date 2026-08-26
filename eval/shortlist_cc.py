#!/usr/bin/env python3
"""Terminal-outcome assembly for the AC-157-v1 suffix shortlist (#157).

Given the per-route suffix grid results and the split data state, this
module applies the issue-#157 quoted gates on the **suffix claim set** and
forms exactly one of the four frozen legal terminals:

1. **exact shortlist** — at least one cell passes every gate including the
   claim-supportable +3pp own-actionable lift;
2. **收窄声称 shortlist** — gate-passing cells exist but the +3pp lift is
   NOT claimable (suffix actionable group-complete sample < 1000, or the
   measured lift did not reach +3pp with CI lower > 0); "不得把未测准涨幅
   写成通过";
3. **无合格方案** — no route forms a legal shortlist (τ not_calibratable /
   Δ₁ / finite-H family / safety / mispromotion / pollution eliminated
   every cell; H=inf alone is never a stand-in);
4. **数据不足** — the suffix claim set holds no group-complete events (or
   no suffix events past the cutoff): the contract claims cannot be
   evaluated (legal terminal, never an implementation failure).

Gates (issue #157 body, on the suffix claim set; all on the group-complete
denominator, size < 32):

- Δ₁ = gamma/(1+k) <= min(0.5, P10(margin_base)) with margin_base from the
  prefix (shadow baseline already ranked the final selection first; base
  margin vs the runner-up under the frozen base reconstruction).
- finite-H vs H=inf: top-1 CI lower >= -1pp, mispromotion-rate CI upper <=
  +1pp, majority-pollution-rate CI upper <= +1pp against the H=inf twin —
  with the family rule that H=inf alone is never shortlisted.
- overall safety on all suffix group-complete targets: top-1 diff CI lower
  >= -0.5pp, MRR diff CI lower >= -0.005.
- mispromotion: denominator = actionable suffix group-complete events where
  the shadow baseline ranked the final selection first; point <= 2%, CI
  upper <= 3%.
- majority pollution: point <= 5%, CI upper <= 7.5%.
- +3pp claim only when the suffix sample supports it; otherwise 收窄声称.

Legal terminal names are the frozen constants below; no ANN / production
winner is picked here (#80 deferred), live γ stays 0, and public-B accuracy
or the personal 2x2 r never enter the decision.
"""


TERMINAL_EXACT = "exact_shortlist"
TERMINAL_NARROWED = "收窄声称_shortlist"
TERMINAL_NO_QUALIFIED = "无合格方案"
TERMINAL_INSUFFICIENT = "数据不足"

# Suffix claim-support minimum (frozen pre-declared): actionable
# group-complete suffix events required before +3pp may be claimed.
LIFT_CLAIM_MIN_ACTIONABLE = 1000


class ShortlistError(Exception):
    """A true fault in the suffix shortlist decision inputs."""


def cell_gate_state(cell_record):
    """One cell's hard-gate state on the suffix claim set.

    A cell passes iff it ran (no eliminated marker), Δ₁ holds, all seven
    hard gates pass, and the finite-H family rule is satisfied (finite-H
    cells pass their own finite-H gate; H=inf cells require a passing
    finite-H twin).
    """
    if "eliminated" in cell_record:
        return {"pass": False, "reason": "eliminated:%s" % cell_record["eliminated"]}
    cell = cell_record["cell"]
    if cell.get("tau") is None:
        return {"pass": False, "reason": "eliminated:tau_not_calibratable"}
    if not cell_record.get("delta_one_ok", False):
        return {"pass": False, "reason": "eliminated:delta_one"}
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
    if not cell_record.get("finite_h_ok", False):
        return {"pass": False, "reason": "eliminated:finite_h_family"}
    return {"pass": True, "reason": "ok"}


def finite_h_family_map(cells):
    """(route, tau_q, K, gamma, k) -> family gate state.

    A family is ``ok`` iff at least one finite-H cell of it passed its
    finite-H gate (all three paired CIs).  An H=inf cell alone is never a
    valid family (spec #43: "不得用 H=∞ 顶上").
    """
    families = {}
    for record in cells:
        if "eliminated" in record:
            continue
        cell = record["cell"]
        key = (cell["route_id"], cell.get("tau_quantile"),
               cell["k_evidence"], cell["gamma"], cell["saturation_k"])
        half_life = cell["half_life"]
        entry = families.setdefault(
            key, {"ok": False, "has_inf": False, "n_finite_pass": 0})
        if half_life == float("inf"):
            entry["has_inf"] = True
            continue
        gate = record.get("finite_h_gate")
        if gate is not None and gate.get("pass", False):
            entry["n_finite_pass"] += 1
            entry["ok"] = True
    return families


def assemble_shortlist(route_results, data, seed=None, replicates=None):
    """Assemble the per-route eligibility and terminal decision record.

    ``route_results``: per-route records with ``route_id``, ``tau`` (the
    calibration status), ``cells`` (per-cell gate results) and ``data``
    (the prefix/suffix split counts).  ``data`` carries the reference
    split counts used for the 数据不足 check and the claim support check.
    Public-B accuracy and the personal 2x2 r never enter this function.
    """
    if not route_results:
        raise ShortlistError("no route results to decide on")

    # 数据不足: the suffix claim set cannot support the contract gates.
    suffix_data = data.get("suffix") or {}
    if suffix_data.get("group_complete", 0) == 0 or \
            suffix_data.get("actionable_group_complete", 0) == 0:
        return {
            "outcome": TERMINAL_INSUFFICIENT,
            "reason": ("suffix group-complete %d / actionable group-complete "
                       "%d == 0: the contract claims cannot be evaluated "
                       "on the claim set"
                       % (suffix_data.get("group_complete", 0),
                          suffix_data.get("actionable_group_complete", 0))),
            "data": data,
            "per_route": [],
            "total_eligible_cells": 0,
            "live_gamma": 0.0,
        }

    per_route = []
    any_evaluated = False
    total_eligible = 0
    all_not_calibratable = True
    for result in route_results:
        route_id = result["route_id"]
        tau = result.get("tau") or {}
        cells = result.get("cells") or []
        groups = [c for c in cells if "eliminated" not in c]
        any_evaluated = any_evaluated or bool(groups)
        if tau.get("state") == "calibratable":
            all_not_calibratable = False
        families = finite_h_family_map(cells)
        eligible = []
        eliminated_reasons = {}
        for record in cells:
            if "eliminated" in record:
                reason = "eliminated:%s" % record["eliminated"]
                eliminated_reasons[reason] = eliminated_reasons.get(reason, 0) + 1
                continue
            cell = record["cell"]
            key = (cell["route_id"], cell.get("tau_quantile"),
                   cell["k_evidence"], cell["gamma"], cell["saturation_k"])
            half_life = cell["half_life"]
            family = families.get(key)
            if half_life == float("inf"):
                # H=∞ alone is never a production stand-in (spec #43): the
                # family needs at least one passing finite-H twin.
                finite_h_ok = bool(family and family["n_finite_pass"] > 0)
            else:
                # A finite-H cell must pass its own finite-H gate.
                gate = record.get("finite_h_gate")
                finite_h_ok = bool(gate and gate.get("pass", False))
            record = dict(record, finite_h_ok=finite_h_ok)
            state = cell_gate_state(record)
            if state["pass"]:
                eligible.append(record)
            else:
                reason = state["reason"]
                eliminated_reasons[reason] = eliminated_reasons.get(reason, 0) + 1
        per_route.append({
            "route_id": route_id,
            "tau": tau,
            "eligible_cells": len(eligible),
            "eliminated_by_reason": eliminated_reasons,
            "evaluated_cells": len(groups),
            "eligible": [{
                "route_id": c["cell"]["route_id"],
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
                "lift": c.get("lift"),
            } for c in eligible],
        })
        total_eligible += len(eligible)

    # Legal terminal assembly (AC-157-V1).
    eligible_routes = [r for r in per_route if r["eligible_cells"] > 0]
    if all_not_calibratable:
        outcome = TERMINAL_NO_QUALIFIED
        reason = ("all routes τ not_calibratable (prefix hard-negative "
                  "queries < 200); no τ is invented and the suffix gates "
                  "cannot run (RISK-157-3)")
    elif not eligible_routes:
        outcome = TERMINAL_NO_QUALIFIED
        reason = ("no cell passes the full gate set on the suffix claim "
                  "set (Δ₁ / finite-H family / safety / mispromotion / "
                  "pollution)")
    else:
        # Claim supportability of +3pp: the suffix actionable
        # group-complete sample must support the claim (frozen); otherwise
        # 收窄声称 — never write an unmeasured lift as passed.
        suffix_gc_actionable = suffix_data.get("actionable_group_complete", 0)
        claimable_routes = []
        for r in eligible_routes:
            claimable = [c for c in r["eligible"]
                         if (c.get("lift") or {}).get("claimable") is True]
            if claimable:
                claimable_routes.append(r["route_id"])
        if claimable_routes:
            outcome = TERMINAL_EXACT
            reason = ("at least one eligible cell claims the +3pp lift; "
                      "shortlist routes: %s"
                      % ", ".join(sorted(claimable_routes)))
        else:
            outcome = TERMINAL_NARROWED
            reason = ("eligible cells exist but the +3pp lift is not "
                      "claimable on the suffix actionable group-complete "
                      "sample of %d (need >= %d); report the narrowed "
                      "claim (收窄声称)"
                      % (suffix_gc_actionable, LIFT_CLAIM_MIN_ACTIONABLE))

    return {
        "outcome": outcome,
        "reason": reason,
        "data": data,
        "per_route": per_route,
        "total_eligible_cells": total_eligible,
        "any_evaluated": any_evaluated,
        "live_gamma": 0.0,
    }