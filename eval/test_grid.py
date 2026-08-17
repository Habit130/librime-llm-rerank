#!/usr/bin/env python3
"""Tests for the pre-declared grid, Δ₁ gate and milestones (SCN-70-5).

Pins: the frozen candidate space (representations x H x K x gamma x k), the
Δ₁ single-event safety boundary with the unavailable-margin handling, the
replicate/seed floor, elimination of Δ₁-violating cells, and the diagnostic
milestone ("诊断报告,不选方案") at small sample sizes.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from walkforward import DELTA_ONE_CAP, delta_one  # noqa: E402

from grid import (GAMMAS, HALF_LIVES, K_EVIDENCE,  # noqa: E402
                  MILESTONE_DIAGNOSTIC, MILESTONE_SELECT, SATURATION_KS,
                  delta_one_ok, finite_h_gate, milestone_state,
                  predeclared_cells, run_representation)


class GridDeltaOneMilestoneTest(unittest.TestCase):

    def test_predeclared_space_exact(self):
        """The scan space is exactly spec #43's grid, product order."""
        self.assertEqual(HALF_LIVES, (8, 32, 128, 512, float("inf")))
        self.assertEqual(K_EVIDENCE, (8, 16, 32, 64))
        self.assertEqual(GAMMAS, (0.5, 1.0, 2.0, 4.0))
        self.assertEqual(SATURATION_KS, (1, 3, 7))
        cells = predeclared_cells("repr")
        self.assertEqual(len(cells), 5 * 4 * 4 * 3)
        for cell in cells:
            self.assertEqual(cell["representation_id"], "repr")
            self.assertIn(cell["half_life"], HALF_LIVES)
            self.assertIn(cell["k_evidence"], K_EVIDENCE)
            self.assertIn(cell["gamma"], GAMMAS)
            self.assertIn(cell["saturation_k"], SATURATION_KS)

    def test_delta_one_formula(self):
        self.assertEqual(delta_one(2.0, 3), 0.5)     # γ/(1+k)
        self.assertEqual(delta_one(2.0, 1), 1.0)
        self.assertEqual(delta_one(0.5, 7), 0.5 / 8)

    def test_delta_one_cap_only_cells(self):
        """margin_base unavailable (real snapshots): only the 0.5 cap."""
        self.assertFalse(delta_one_ok(4.0, 1, margin_base=None))   # 2 > .5
        self.assertFalse(delta_one_ok(2.0, 1, margin_base=None))   # 1 > .5
        self.assertTrue(delta_one_ok(2.0, 3, margin_base=None))    # .5 <= .5
        self.assertTrue(delta_one_ok(0.5, 1, margin_base=None))    # .25

    def test_delta_one_full_bound_with_margin(self):
        """Fixture-injected margin_base: Δ₁ <= min(0.5, P10)."""
        self.assertTrue(delta_one_ok(0.5, 1, margin_base=1.0))
        # Δ₁=0.25 <= min(0.5, 1.0)
        self.assertFalse(delta_one_ok(2.0, 1, margin_base=0.5))
        # Δ₁=1.0 > min(0.5, 0.5)
        self.assertFalse(delta_one_ok(4.0, 3, margin_base=0.75))
        # Δ₁=1.0 > min(0.5, 0.75)=0.5

    def test_milestone_diagnostic_below_selection(self):
        state, reason = milestone_state(999, 100, 200, 200)
        self.assertEqual(state, "diagnostic")
        self.assertIn("诊断报告" if False else "actionable complete", reason)

    def test_milestone_requires_all_four(self):
        self.assertEqual(milestone_state(
            MILESTONE_SELECT, 99, 200, 200)[0], "diagnostic")
        self.assertEqual(milestone_state(
            MILESTONE_SELECT, 100, 199, 200)[0], "diagnostic")
        self.assertEqual(milestone_state(
            MILESTONE_SELECT, 100, 200, 199)[0], "diagnostic")
        self.assertEqual(milestone_state(
            MILESTONE_SELECT, 99, 200, 199)[0], "diagnostic")

    def test_milestone_selectable_only_when_all_met(self):
        state, _ = milestone_state(MILESTONE_SELECT, 200, 300, 250)
        self.assertEqual(state, "selectable")

    def test_diagnostic_threshold_constant(self):
        self.assertEqual(
            MILESTONE_DIAGNOSTIC, 250, "250 milestone per spec #43")

    def test_delta_one_cap_constant(self):
        self.assertEqual(DELTA_ONE_CAP, 0.5)

    def test_not_calibratable_reports_delta_one_eliminations(self):
        """When τ is not calibratable, every pre-declared cell is reported
        as eliminated (Δ₁ boundary first, then τ-dependence) and the
        milestone still carries the reference-replay counts — no invented
        τ, no silent skip."""
        from calibration import calibrate_tau
        from fixture_facts import SyntheticFacts, fixture_provider
        from walkforward import FrozenFacts, VectorTable, WalkForwardReplay

        facts = SyntheticFacts()
        try:
            # 30 events, 3 keys: far below the 200-query τ gate.
            query_vectors = {}
            event_vectors = {}
            for key_index in range(3):
                canonical = "k%d" % key_index
                query_vectors["ctx-%d" % key_index] = (1.0, 0.0, 0.0, 0.0)
                event_vectors[("luna_pinyin", canonical, "a")] = \
                    (0.9, 0.4358898943540673, 0.0, 0.0)
                event_vectors[("luna_pinyin", canonical, "b")] = \
                    (0.0, 1.0, 0.0, 0.0)
            for index in range(30):
                key_index = index % 3
                canonical = "k%d" % key_index
                facts.add_event(
                    "e%d" % index, canonical, "ctx-%d" % key_index,
                    "a" if index % 2 == 0 else "b",
                    ("a", "b"), (1000 + index, 0))
            provider = fixture_provider(query_vectors, event_vectors)
            frozen = FrozenFacts(facts.db_path)
            try:
                vectors = VectorTable(frozen.events(), provider)
                replay = WalkForwardReplay(frozen, vectors)
                result = run_representation(replay, "fixture", 42)
                self.assertEqual(result["tau"]["state"],
                                 "not_calibratable")
                self.assertEqual(len(result["cells"]),
                                 len(predeclared_cells("fixture")))
                eliminated = {c["eliminated"] for c in result["cells"]}
                self.assertIn("delta_one", eliminated)
                self.assertIn("tau_not_calibratable", eliminated)
                self.assertEqual(result["milestone"]["state"],
                                 "diagnostic")
            finally:
                frozen.close()
        finally:
            facts.close()

    def test_finite_h_gate_same_event_set_passes(self):
        """A finite-H cell identical to its H=inf twin on the same event
        set passes all three paired gates (top-1 lb >= -1pp, mispromotion
        ub <= +1pp, pollution ub <= +1pp)."""
        from walkforward import EventOutcome

        def outcomes(event_ids):
            return [EventOutcome(
                event_id=event_id, hlc=(1000, 0),
                key=("s", "word", "k"),
                confirmation_source="explicit_current",
                competition_complete=True, baseline_rank=1,
                scheme_rank=1, actionable=True, total_mass=1.0,
                candidate_count=2, selection_index=0,
                kept_ids=("h1",), kept_weights=(1.0,),
                kept_matches=(0,)) for event_id in event_ids]

        ids = ["e%d" % i for i in range(12)]
        inf_cell = {"outcomes": outcomes(ids)}
        finite_cell = {"outcomes": outcomes(ids)}
        gate = finite_h_gate(inf_cell, finite_cell, seed=42,
                             replicates=10000)
        self.assertTrue(gate["pass"])
        self.assertEqual(gate["union_events"], 12)
        self.assertEqual(gate["top1_diff"][0], 0.0)
        self.assertEqual(gate["mispromotion_diff"][0], 0.0)
        self.assertEqual(gate["majority_pollution_diff"][0], 0.0)

    def test_finite_h_gate_rejects_top1_regression(self):
        """A finite-H cell that pushes selections out of first (top-1 -5pp
        on 20 events) fails the top-1 lower-bound gate."""
        from walkforward import EventOutcome

        def make(event_ids, scheme_rank):
            return [EventOutcome(
                event_id=event_id, hlc=(1000, 0),
                key=("s", "word", "k%d" % (i % 2)),
                confirmation_source="explicit_current",
                competition_complete=True, baseline_rank=1,
                scheme_rank=scheme_rank, actionable=True, total_mass=1.0,
                candidate_count=2, selection_index=0,
                kept_ids=("h1",), kept_weights=(1.0,),
                kept_matches=(0,)) for i, event_id in enumerate(event_ids)]

        ids = ["e%d" % i for i in range(20)]
        inf_cell = {"outcomes": make(ids, 1)}
        # finite-H: 1 of 20 stays first -> top-1 drops from 1.0 to 0.05.
        finite_outcomes = make(ids, 2)
        finite_outcomes[0] = EventOutcome(
            event_id="e0", hlc=(1000, 0), key=("s", "word", "k0"),
            confirmation_source="explicit_current",
            competition_complete=True, baseline_rank=1, scheme_rank=1,
            actionable=True, total_mass=1.0, candidate_count=2,
            selection_index=0, kept_ids=("h1",), kept_weights=(1.0,),
            kept_matches=(0,))
        finite_cell = {"outcomes": finite_outcomes}
        gate = finite_h_gate(inf_cell, finite_cell, seed=42,
                             replicates=10000)
        self.assertFalse(gate["pass"])
        self.assertLess(gate["top1_diff"][1][0], -0.01)

    def test_calibratable_path_attaches_finite_h_gates(self):
        """When τ is calibratable, evaluated cells carry the finite-H gate
        against their H=inf twin (a limited max_cells scan keeps the test
        fast)."""
        from fixture_facts import SyntheticFacts, fixture_provider
        from walkforward import FrozenFacts, VectorTable, WalkForwardReplay

        facts = SyntheticFacts()
        query_vectors = {}
        event_vectors = {}
        for key_index in range(10):
            canonical = "k%d" % key_index
            query_vectors["ctx-%d" % key_index] = (1.0, 0.0, 0.0, 0.0)
            event_vectors[("luna_pinyin", canonical, "a")] = \
                (0.95, 0.31224989991991994, 0.0, 0.0)
            event_vectors[("luna_pinyin", canonical, "b")] = \
                (0.0, 1.0, 0.0, 0.0)
        for index in range(500):
            key_index = index % 10
            canonical = "k%d" % key_index
            facts.add_event(
                "e%d" % index, canonical, "ctx-%d" % key_index,
                "a" if (index // 10) % 2 == 0 else "b",
                ("a", "b"), (1000 + index, 0))
        provider = fixture_provider(query_vectors, event_vectors)
        frozen = FrozenFacts(facts.db_path)
        try:
            vectors = VectorTable(frozen.events(), provider)
            replay = WalkForwardReplay(frozen, vectors)
            # 15 cells = one full (tau, K, gamma) group: 5 H x 3 k, so the
            # finite-H cells have their H=inf twins present.
            result = run_representation(replay, "fixture", 42,
                                        replicates=10000, max_cells=15)
            self.assertEqual(result["tau"]["state"], "calibratable")
            self.assertTrue(result.get("partial_scan"))
            evaluated = [c for c in result["cells"]
                         if "eliminated" not in c]
            self.assertTrue(evaluated)
            finite = [c for c in evaluated
                      if c["cell"]["half_life"] != float("inf")]
            for cell_record in finite:
                self.assertIn("finite_h_gate", cell_record)
                self.assertIn("pass", cell_record["finite_h_gate"])
        finally:
            frozen.close()
            facts.close()

    def test_stratum_gate_applies_at_200_events(self):
        """A stratum with >=200 actionable complete-competition events is
        gated (top-1 non-inferiority + mispromotion <=2%/<=3% CI); below
        200 it is reported as not applicable."""
        from grid import _stratum_gates
        from walkforward import EventOutcome

        def make(count, scheme_rank, source="explicit_current", rank=1):
            return [EventOutcome(
                event_id="e%d" % i, hlc=(1000 + i, 0),
                key=("s", "word", "k%d" % (i % 10)),
                confirmation_source=source,
                competition_complete=True,
                baseline_rank=rank,
                scheme_rank=scheme_rank,
                actionable=True, total_mass=1.0, candidate_count=2,
                selection_index=0, kept_ids=("h1",), kept_weights=(1.0,),
                kept_matches=(0,)) for i in range(count)]

        # 250 events all ranked first by the scheme, baseline also first:
        # top-1 diff 0 (non-inferior), mispromotion 0 -> pass.
        outcomes = make(250, 1)
        gates = _stratum_gates(outcomes, seed=42)
        self.assertEqual(len(gates), 1)
        self.assertTrue(gates[0]["applicable"])
        self.assertEqual(gates[0]["count"], 250)
        self.assertTrue(gates[0]["pass"])

        # 250 events where the scheme never ranks first but baseline does:
        # top-1 diff -1.0 (fail non-inferiority), mispromotion 1.0 (fail).
        outcomes = make(250, 2)
        gates = _stratum_gates(outcomes, seed=42)
        self.assertFalse(gates[0]["pass"])
        self.assertLess(gates[0]["top1_diff"][1][0], -0.01)
        self.assertGreater(gates[0]["mispromotion_point"], 0.02)

        # A small stratum is not applicable.
        gates = _stratum_gates(make(150, 1), seed=42)
        self.assertFalse(gates[0]["applicable"])


if __name__ == "__main__":
    unittest.main()
