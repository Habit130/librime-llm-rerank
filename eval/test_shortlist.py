#!/usr/bin/env python3
"""Tests for the AC-77-v1 terminal-outcome assembly (shortlist.py).

Pins the four legal terminal outcomes and the hard-gate application on the
group-complete denominator: #69 benchmark elimination (RISK-77-1),
Δ₁ / τ elimination, finite-H family rules (H=inf alone is never a
production stand-in), the +3pp claim gating on thin strata, and the
rerun-milestone schedule when 无合格方案.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from shortlist import (STRATUM_MIN, assemble_shortlist,  # noqa: E402
                       finite_h_family_map)


def _cell(representation_id="exact_l14", half_life=float("inf"),
          k_evidence=8, gamma=1.0, saturation_k=3, tau_quantile="Q95",
          tau=0.5, hard_pass=True, delta_ok=True, finite_pass=None,
          eliminated=None):
    cell = {
        "representation_id": representation_id,
        "half_life": half_life,
        "k_evidence": k_evidence,
        "gamma": gamma,
        "saturation_k": saturation_k,
        "tau_quantile": tau_quantile,
        "tau": tau,
    }
    record = {"cell": cell, "delta_one_ok": delta_ok,
              "hard_gates": {"pass": hard_pass},
              "metrics": {"top1": 0.9, "mrr": 0.95,
                          "actionable_group_complete": 500},
              "ci": {"top1_vs_baseline": (0.01, (0.0, 0.02))}}
    if finite_pass is not None:
        record["finite_h_gate"] = {"pass": finite_pass,
                                   "union_events": 500}
    if eliminated is not None:
        record["eliminated"] = eliminated
    return record


def _data(actionable=1200, rank_gt1=250, explicit_indexed=250,
          group_complete=1448, keys=451):
    return {
        "replayable": 2114, "group_complete": group_complete,
        "keys": keys, "explicit_indexed": explicit_indexed,
        "rank_gt1": rank_gt1, "actionable_group_complete": actionable,
        "actionable_keys": 300, "coverage": 0.68,
    }


class ShortlistTest(unittest.TestCase):

    def test_no_quality_cells_and_benchmark_fail_is_无合格方案(self):
        """All four representations fail #69 (quoted F1) and nothing is
        eligible -> 无合格方案; live γ stays 0 (RISK-77-1)."""
        result = {
            "representation": "exact_l14",
            "cells": [_cell(half_life=8, finite_pass=True),
                      _cell(half_life=float("inf"))],
        }
        decision = assemble_shortlist(
            [result], _data(), benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "无合格方案")
        self.assertEqual(decision["live_gamma"], 0.0)
        self.assertFalse(decision["lift_claimable"])
        # The cells ran (evaluated) but the #69 benchmark gate eliminated
        # the whole representation: quality shortlist impossible.
        self.assertTrue(decision["any_evaluated"] or False)
        self.assertIn("#69 fixed-benchmark elimination",
                      decision["lift_reason"])

    def test_benchmark_fail_cannot_sit_on_exact_shortlist(self):
        """A #69-failed representation's cells can never sit on the exact
        quality shortlist even if every gate passes (AC-77 seam 8)."""
        # Build a plausible grid: H=inf cell passes every hard gate, and
        # one finite-H twin passes its finite-H gate.
        cells = [
            _cell(half_life=8, finite_pass=True),
            _cell(half_life=32, finite_pass=True),
            _cell(half_life=float("inf")),
        ]
        result = {"representation": "exact_l14", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(), benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "无合格方案")
        per = decision["per_representation"][0]
        self.assertTrue(per["benchmark_69_fail"])
        self.assertEqual(per["eligible_cells"], 0)
        self.assertIn("eliminated:benchmark_69",
                      per["eliminated_by_reason"])

    def test_exact_shortlist_when_all_gates_pass_and_lift_claimable(self):
        """A #69-passing representation with every hard gate + finite-H
        family passing and sufficient strata -> exact quality shortlist."""
        cells = [
            _cell(half_life=8, finite_pass=True),
            _cell(half_life=32, finite_pass=True),
            _cell(half_life=float("inf")),
        ]
        result = {"representation": "split_l28", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(), benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "exact_quality_shortlist")
        self.assertTrue(decision["lift_claimable"])
        per = decision["per_representation"][0]
        self.assertFalse(per["benchmark_69_fail"])
        self.assertEqual(per["eligible_cells"], 3)

    def test_narrowed_claim_when_lift_not_claimable(self):
        """Hard gates pass but the actionable group-complete sample is thin
        (< 1000) -> 收窄声称 shortlist (no +3pp claim)."""
        cells = [
            _cell(half_life=8, finite_pass=True),
            _cell(half_life=float("inf")),
        ]
        result = {"representation": "split_l28", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(actionable=900, rank_gt1=150),
            benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "narrowed_claim_shortlist")
        self.assertFalse(decision["lift_claimable"])
        self.assertIn("actionable group-complete 900 < 1000",
                      decision["lift_reason"])

    def test_narrowed_claim_when_correction_stratum_thin(self):
        """Hard gates pass but the correction stratum (rank>1) is thin ->
        收窄声称 shortlist; the 纠错 lift is not claimed (AC-77 seam 10)."""
        cells = [
            _cell(half_life=8, finite_pass=True),
            _cell(half_life=float("inf")),
        ]
        result = {"representation": "split_l28", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(actionable=1200, rank_gt1=120,
                            explicit_indexed=250),
            benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "narrowed_claim_shortlist")
        self.assertFalse(decision["lift_claimable"])
        self.assertIn("correction stratum (rank>1) 120 < 200",
                      decision["lift_reason"])

    def test_仅安全_涨幅未测准_when_hard_gates_fail_but_cells_evaluated(self):
        """Cells evaluated (safety/mispromotion/pollution reported) but no
        cell passes the full gate set (e.g. overall safety fails) and lift
        is unclaimable -> 仅安全、涨幅未测准."""
        cells = [_cell(half_life=float("inf"), hard_pass=False)]
        result = {"representation": "split_l28", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(actionable=1200),
            benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "仅安全、涨幅未测准")
        self.assertTrue(decision["any_evaluated"])
        per = decision["per_representation"][0]
        self.assertEqual(per["evaluated_cells"], 1)
        self.assertEqual(per["eligible_cells"], 0)

    def test_无合格方案_when_tau_not_calibratable(self):
        """τ not calibratable: every cell eliminated by Δ₁/τ, nothing
        evaluated -> 无合格方案 (RISK-77-1)."""
        cells = [_cell(eliminated="tau_not_calibratable"),
                 _cell(eliminated="delta_one")]
        result = {"representation": "exact_l14", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(), benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "无合格方案")
        self.assertFalse(decision["any_evaluated"])

    def test_inf_alone_not_shortlisted_without_passing_finite_family(self):
        """H=inf is never a production stand-in: without a passing finite-H
        twin, the family cannot shortlist (spec #43 有限 H 门槛)."""
        cells = [
            _cell(half_life=float("inf")),  # passes hard gates
        ]
        result = {"representation": "split_l28", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(), benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "无合格方案")
        self.assertIn("eliminated:finite_h_family",
                      decision["per_representation"][0]
                      ["eliminated_by_reason"])

    def test_finite_h_family_map(self):
        """A family is ok iff at least one finite-H twin passed its gate."""
        cells = [
            _cell(half_life=8, finite_pass=True),
            _cell(half_life=32, finite_pass=False),
            _cell(half_life=float("inf")),
        ]
        families = finite_h_family_map(cells, benchmark_fail=False)
        key = ("exact_l14", "Q95", 8, 1.0, 3)
        self.assertIn(key, families)
        self.assertTrue(families[key]["ok"])
        self.assertEqual(families[key]["n_finite_pass"], 1)
        # Benchmark-failed representation: no family is ok.
        families_fail = finite_h_family_map(cells, benchmark_fail=True)
        self.assertFalse(families_fail[key]["ok"])

    def test_rerun_milestones_when_无合格方案(self):
        """无合格方案 reports the next rerun milestones (可作用组完整)."""
        cells = [_cell(eliminated="tau_not_calibratable")]
        result = {"representation": "exact_l14", "cells": cells}
        decision = assemble_shortlist(
            [result], _data(actionable=997), benchmark_fail_reprs={"exact_l14"})
        self.assertEqual(decision["outcome"], "无合格方案")
        self.assertEqual(decision["rerun_milestones"],
                         [1500, 2000, 3000, 5000])


if __name__ == "__main__":
    unittest.main()
