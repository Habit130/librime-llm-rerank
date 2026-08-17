#!/usr/bin/env python3
"""Model-free acceptance tests for the fixed semantic benchmark (#69)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from semantic_benchmark import (  # noqa: E402
    AXES,
    BENCHMARK_K_EVIDENCE,
    BENCHMARK_TAU,
    FIXTURE_DISTRACTOR_PRECEDING_TEXTS,
    SyntheticFacts,
    _benchmark_params,
    _case_passed,
    _run_oracle_case,
    _unit_vector,
    benchmark_cases,
    benchmark_manifest,
    case_version_summary,
    run_fixture_gate,
)
from oracle import FactReader  # noqa: E402


class SemanticBenchmarkShapeTest(unittest.TestCase):
    def test_counts_and_stable_ids(self):
        cases = benchmark_cases()
        self.assertGreaterEqual(sum(c.relation == "positive" for c in cases),
                                100)
        self.assertGreaterEqual(sum(c.relation == "hard_negative" for c in cases),
                                100)
        self.assertEqual(len(cases), len({case.case_id for case in cases}))
        self.assertEqual(
            [case.case_id for case in cases],
            [case.case_id for case in benchmark_cases()],
        )

    def test_every_case_has_contract_fields_and_recomputed_summary(self):
        for case in benchmark_cases():
            self.assertIn(case.relation, ("positive", "hard_negative"))
            self.assertTrue(case.choice_problem)
            self.assertTrue(case.candidates)
            self.assertIn(case.expected_candidate, case.candidates)
            self.assertIn(case.history_selection, case.candidates)
            self.assertNotEqual(case.query_preceding_text,
                                case.recorded_preceding_text)
            self.assertTrue(set(case.axes).issubset(set(AXES)))
            self.assertTrue(case.version_summary.startswith(
                "semantic-regression-benchmark-v1:"))
            self.assertEqual(case.version_summary, case_version_summary(case))

    def test_all_six_axes_are_present_and_annotated(self):
        cases = benchmark_cases()
        for axis in AXES:
            selected = [case for case in cases if axis in case.axes]
            self.assertTrue(selected, axis)
            self.assertTrue(all(axis in case.axes for case in selected))

        bpe = [case for case in cases if "bpe_seam" in case.axes]
        self.assertTrue(all(case.query_preceding_text.endswith("今天天气?")
                            for case in bpe))
        window = [case for case in cases if "window_64" in case.axes]
        self.assertTrue(all({len(case.query_preceding_text),
                             len(case.recorded_preceding_text)} == {64, 65}
                            for case in window))

    def test_manifest_is_deterministic_and_scope_is_elimination_only(self):
        first = benchmark_manifest()
        second = benchmark_manifest()
        self.assertEqual(first, second)
        self.assertEqual(first["counts"]["total"], len(benchmark_cases()))
        self.assertEqual(first["decision_scope"],
                         "eliminate_obvious_regressions_only")
        self.assertEqual(first["selection"], "not_run")
        self.assertEqual(first["production_enablement"], "not_run")

    def test_fixed_content_has_no_live_history_markers(self):
        forbidden = ("/Users/", "~/Library/Rime", "Library/Application Support",
                     "facts.sqlite3", "socket")
        for case in benchmark_cases():
            content = json.dumps(case.payload(), ensure_ascii=False)
            for marker in forbidden:
                self.assertNotIn(marker, content)


class SemanticBenchmarkOracleFixtureTest(unittest.TestCase):
    def test_fixture_gate_passes_for_all_first_round_representations(self):
        report = run_fixture_gate()
        self.assertEqual("AC-69-v1", report["contract"])
        self.assertEqual(4, len(report["representations"]))
        for result in report["representations"].values():
            self.assertEqual(1.0, result["positive"]["rate"])
            self.assertEqual(1.0, result["hard_negative"]["rate"])
            self.assertTrue(result["gate_pass"])
        serialized = json.dumps(report, ensure_ascii=False)
        for case in benchmark_cases():
            self.assertNotIn(case.query_preceding_text, serialized)
            self.assertNotIn(case.recorded_preceding_text, serialized)

    def test_fixture_exercises_threshold_and_exact_top_k(self):
        case = benchmark_cases()[0]
        fixture = SyntheticFacts(case, FIXTURE_DISTRACTOR_PRECEDING_TEXTS)
        try:
            vectors = {
                fixture.target_event_id: _unit_vector(0.97),
            }
            for index in range(len(FIXTURE_DISTRACTOR_PRECEDING_TEXTS)):
                event_id = "distractor-%s-%02d" % (case.case_id, index + 1)
                vectors[event_id] = _unit_vector(0.95 - index * 0.005)
            reader = FactReader(fixture.db_path)
            try:
                result = _run_oracle_case(
                    case, reader, (1.0, 0.0, 0.0, 0.0), vectors,
                    _benchmark_params(),
                )
            finally:
                reader.close()
            self.assertEqual(BENCHMARK_K_EVIDENCE, len(result.kept))
            self.assertTrue(_case_passed(case, result, fixture.target_event_id))
            self.assertTrue(all(entry.cosine > BENCHMARK_TAU
                                for entry in result.kept))
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
