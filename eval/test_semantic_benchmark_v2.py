#!/usr/bin/env python3
"""Model-free contract tests for the frozen candidate-conditioned v2 set."""

import os
import copy
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from semantic_benchmark_v2 import (  # noqa: E402
    AXES,
    BenchmarkProtocolError,
    PRIVACY_MARKERS,
    V1_BENCHMARK_DIGEST,
    V1_BENCHMARK_VERSION,
    V2_BENCHMARK_VERSION,
    V2_FAMILY_DISTRIBUTION,
    accept_one_shot_report,
    benchmark_manifest_v2,
    benchmark_cases_v2,
    build_fixture_report,
    canonical_manifest_digest,
    family_specs_v2,
    freeze_inputs,
    run_fixture_gate,
    render_review_table,
    route_matrix,
    route_matrix_digest,
    validate_route_matrix,
    validate_v2_cases,
    verify_artifact_privacy,
)


class SemanticBenchmarkV2CalibrationTest(unittest.TestCase):
    def _observations(self, values=None):
        from semantic_benchmark_v2 import v1_benchmark_cases  # noqa: PLC0415
        cases = [case for case in v1_benchmark_cases()
                 if case.relation == "hard_negative"]
        if values is None:
            values = [value / 100.0 for value in range(100)]
        return [{
            "case_id": case.case_id,
            "benchmark_version": V1_BENCHMARK_VERSION,
            "relation": "hard_negative",
            "cosine": value,
        } for case, value in zip(cases, values)]

    def test_nearest_rank_q95_uses_v1_hard_negatives_only(self):
        from semantic_benchmark_v2 import calibrate_v1_q95  # noqa: PLC0415

        result = calibrate_v1_q95(self._observations())
        self.assertEqual(V1_BENCHMARK_VERSION,
                         result["source_benchmark_version"])
        self.assertEqual("hard_negative", result["source_relation"])
        self.assertEqual(100, result["source_case_count"])
        self.assertEqual("Q95", result["quantile"])
        self.assertEqual("nearest_rank", result["quantile_method"])
        self.assertEqual(0.94, result["tau"])

    def test_ties_and_equality_use_strict_greater_than(self):
        from semantic_benchmark_v2 import (  # noqa: PLC0415
            calibrate_v1_q95,
            strict_cosine_above_threshold,
        )

        result = calibrate_v1_q95(self._observations([0.5] * 100))
        self.assertEqual(0.5, result["tau"])
        self.assertFalse(strict_cosine_above_threshold(0.5, result["tau"]))
        self.assertTrue(strict_cosine_above_threshold(0.500001,
                                                      result["tau"]))

    def test_v2_or_positive_or_malformed_inputs_are_rejected(self):
        from semantic_benchmark_v2 import calibrate_v1_q95  # noqa: PLC0415

        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(self._observations()[:-1])

        leaked_version = self._observations()
        leaked_version[0]["benchmark_version"] = V2_BENCHMARK_VERSION
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(leaked_version)

        leaked_relation = self._observations()
        leaked_relation[0]["relation"] = "positive"
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(leaked_relation)

        malformed = self._observations()
        malformed[0]["cosine"] = float("nan")
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(malformed)

        malformed = self._observations()
        malformed[0]["cosine"] = float("inf")
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(malformed)

        malformed = self._observations()
        malformed[0]["cosine"] = True
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(malformed)

        malformed = self._observations()
        malformed[0]["cosine"] = "not-a-cosine"
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(malformed)

        duplicate = self._observations()
        duplicate[1]["case_id"] = duplicate[0]["case_id"]
        with self.assertRaises(BenchmarkProtocolError):
            calibrate_v1_q95(duplicate)


class SemanticBenchmarkV2ShapeTest(unittest.TestCase):
    def test_family_and_case_distribution(self):
        families = family_specs_v2()
        cases = benchmark_cases_v2()
        self.assertEqual(50, len(families))
        self.assertEqual(200, len(cases))
        self.assertEqual(100, sum(case.relation == "positive" for case in cases))
        self.assertEqual(100, sum(case.relation == "hard_negative" for case in cases))
        self.assertEqual(
            V2_FAMILY_DISTRIBUTION,
            {axis: sum(axis in family.axes for family in families)
             for axis in AXES},
        )

    def test_case_expansion_is_deterministic(self):
        first = [case.case_id for case in benchmark_cases_v2()]
        second = [case.case_id for case in benchmark_cases_v2()]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_v1_identity_is_preserved(self):
        manifest = benchmark_manifest_v2()
        self.assertEqual(V1_BENCHMARK_DIGEST,
                         manifest["v1"]["benchmark_digest"])
        self.assertEqual(V1_BENCHMARK_VERSION,
                         manifest["v1"]["benchmark_version"])
        self.assertEqual(50, manifest["v1"]["family_count"])
        self.assertEqual(200, manifest["v1"]["case_count"])

    def test_every_case_is_candidate_conditioned_and_versioned(self):
        for case in validate_v2_cases():
            self.assertEqual(case.relation, case.expected_relation)
            self.assertEqual(case.query_candidate,
                             case.historical_selected_candidate)
            self.assertIn(case.query_candidate, case.candidates)
            self.assertEqual(case.query_preceding_text,
                             case.source_query_text[-64:])
            self.assertEqual(case.recorded_preceding_text,
                             case.source_recorded_text[-64:])
            payload = case.payload()
            self.assertEqual(V2_BENCHMARK_VERSION,
                             payload["benchmark_version"])
            self.assertEqual(case.query_candidate,
                             payload["query"]["candidate"])
            self.assertEqual(case.historical_selected_candidate,
                             payload["history"]["selected_candidate"])
            self.assertTrue(case.version_summary)
            self.assertEqual(24, len(case.version_summary))

    def test_boundary_axes_are_structural(self):
        cases = benchmark_cases_v2()
        bpe = [case for case in cases if "bpe_seam" in case.axes]
        self.assertEqual(32, len(bpe))
        self.assertTrue(all(case.boundary_probe == {
            "suffix": "今天天气?",
            "boundary": "今/天",
            "boundary_char_index": 1,
            "tokenizer_independent": True,
        } for case in bpe))
        self.assertTrue(all(case.source_query_text.endswith(
                                case.boundary_probe["suffix"])
                            and case.source_recorded_text.endswith(
                                case.boundary_probe["suffix"])
                            for case in bpe))
        window = [case for case in cases if "window_64" in case.axes]
        self.assertEqual(32, len(window))
        self.assertTrue(all({len(case.source_query_text),
                             len(case.source_recorded_text)} == {64, 65}
                            for case in window))
        self.assertTrue(all(len(case.query_preceding_text) <= 64
                            and len(case.recorded_preceding_text) <= 64
                            for case in window))

    def test_manifest_is_deterministic_and_binds_protocol(self):
        first = benchmark_manifest_v2()
        second = benchmark_manifest_v2()
        self.assertEqual(first, second)
        self.assertEqual({"total": 200, "positive": 100,
                          "hard_negative": 100}, {
                              "total": first["v2"]["case_count"],
                              **first["v2"]["relation_counts"],
                          })
        self.assertEqual(
            {axis: count * 4 for axis, count in V2_FAMILY_DISTRIBUTION.items()},
            first["v2"]["axis_counts"],
        )
        self.assertEqual(route_matrix_digest(),
                         first["route_matrix_digest"])
        self.assertEqual(
            "592f42dbd59a06e56f44f07a824ab7aec73758026db15ee058f62e656633b602",
            first["route_matrix_digest"],
        )
        self.assertEqual(8, first["k_evidence"])
        self.assertEqual("cosine > tau",
                         first["threshold_protocol"]["comparison"])
        self.assertFalse(first["threshold_protocol"][
            "v2_cases_in_calibration"])
        self.assertEqual(200, len(first["case_summaries"]))
        self.assertEqual("not_run", first["selection"])
        self.assertEqual("not_run", first["production_enablement"])
        self.assertEqual(
            "4d2ed16b607f127c125f1d5c4cd2bfaced0ad9829550bf3788e637727429e01c",
            first["benchmark_digest"],
        )

    def test_manifest_mutation_changes_canonical_digest(self):
        manifest = benchmark_manifest_v2()
        mutated = copy.deepcopy(manifest)
        mutated["k_evidence"] = manifest["k_evidence"] + 1
        self.assertNotEqual(manifest["benchmark_digest"],
                            canonical_manifest_digest(mutated))

    def test_route_matrix_rejects_missing_extra_and_drift(self):
        routes = route_matrix()
        validate_route_matrix(routes)
        self.assertEqual(7, len(routes))
        self.assertEqual(2, sum(route["kind"] == "dedicated_embedding"
                                for route in routes))
        self.assertTrue(all(route["payload"] == "candidate-conditioned-query-history-v1"
                            and route["window_chars"] == 64
                            and route["candidate_conditioned"]
                            and route["vector_format"] == "fp32_l2_normalized"
                            and route["metric"] == "cosine"
                            and route["representation_id"].startswith("ac108-v2:")
                            for route in routes))
        self.assertEqual(
            [14, 21, 28],
            [route["layer"] for route in routes
             if route.get("pooling") == "candidate_span_mean"],
        )
        control = routes[5]
        self.assertTrue(control["control"])
        projection = routes[6]["projection"]
        self.assertEqual({"kind": "linear", "input_dim": 3072,
                          "output_dim": 256}, projection)
        with self.assertRaises(BenchmarkProtocolError):
            validate_route_matrix(routes[:-1])
        with self.assertRaises(BenchmarkProtocolError):
            validate_route_matrix(routes + (routes[0],))
        changed = route_matrix()
        changed[0]["model"] = "changed"
        with self.assertRaises(BenchmarkProtocolError):
            validate_route_matrix(changed)

    def test_review_table_is_stable_and_desensitized(self):
        table = render_review_table()
        self.assertEqual(table, render_review_table())
        self.assertEqual(200, table.count("| positive |")
                         + table.count("| hard_negative |"))
        for marker in PRIVACY_MARKERS:
            self.assertNotIn(marker, table)

    def test_overlap_mutations_are_rejected(self):
        import semantic_benchmark_v2 as module  # noqa: PLC0415

        family = module.FAMILY_SPECS[0]
        with patch.object(module, "FAMILY_SPECS", (
                replace(family, family_id="negation-01"),
                *module.FAMILY_SPECS[1:])):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        v1_pair = module._v1_families()[0]["positive"]
        with patch.object(module, "FAMILY_SPECS", (
                replace(family, positive=tuple(v1_pair)),
                *module.FAMILY_SPECS[1:])):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        v1_choice = module._v1_families()[0]
        with patch.object(module, "FAMILY_SPECS", (
                replace(family, choice_problem=v1_choice["choice_problem"],
                        candidates=tuple(v1_choice["candidates"])),
                *module.FAMILY_SPECS[1:])):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        other = module.FAMILY_SPECS[1]
        with patch.object(module, "FAMILY_SPECS", (
                replace(family, positive=other.positive),
                *module.FAMILY_SPECS[1:])):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        with patch.object(module, "FAMILY_SPECS", (
                replace(family, choice_problem=other.choice_problem,
                        candidates=other.candidates),
                *module.FAMILY_SPECS[1:])):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        with patch.object(module, "FAMILY_SPECS", (
                replace(family, axes=("negation", "unknown_axis")),
                *module.FAMILY_SPECS[1:])):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

    def test_v2_is_disjoint_from_v1_case_sentence_and_competition_sets(self):
        import semantic_benchmark_v2 as module  # noqa: PLC0415

        v1_families = module._v1_families()
        v1_sentences = module._v1_source_sentences()
        v1_triplets = module._v1_case_triplets()
        v1_choice_problems = module._v1_choice_problems()
        v1_candidate_sets = module._v1_candidate_sets()
        v2_families = module.family_specs_v2()
        v2_cases = module.benchmark_cases_v2()
        self.assertFalse({family.family_id for family in v2_families}
                         & {family["family_id"] for family in v1_families})
        self.assertFalse({sentence for family in v2_families
                          for relation in (family.positive, family.negative)
                          for sentence in relation} & v1_sentences)
        self.assertFalse({(case.query_preceding_text,
                           case.recorded_preceding_text,
                           case.query_candidate) for case in v2_cases}
                         & v1_triplets)
        self.assertFalse({family.choice_problem for family in v2_families}
                         & v1_choice_problems)
        self.assertFalse({frozenset(family.candidates) for family in v2_families}
                         & v1_candidate_sets)

    def test_previous_exact_leak_classes_are_rejected(self):
        import semantic_benchmark_v2 as module  # noqa: PLC0415

        v1_family = next(family for family in module._v1_families()
                         if family["family_id"] == "preference-03")
        current = next(family for family in module.FAMILY_SPECS
                       if family.family_id == "v2-preference-03")

        v1_case = next(case for case in module.v1_benchmark_cases()
                       if case.case_id == "hard_negative-preference-03-02")
        current_case = next(case for case in module.benchmark_cases_v2()
                            if case.case_id ==
                            "hard_negative-v2-preference-03-02")
        exact_triplet_leak = replace(
            current_case,
            query_preceding_text=v1_case.query_preceding_text,
            recorded_preceding_text=v1_case.recorded_preceding_text,
            query_candidate=v1_case.expected_candidate,
            historical_selected_candidate=v1_case.expected_candidate,
            candidates=(v1_case.expected_candidate, current_case.candidates[-1]),
            source_query_text="全新修订查询句",
            source_recorded_text="全新修订历史句",
        )
        patched_cases = tuple(
            exact_triplet_leak if case.case_id == current_case.case_id
            else case for case in module.benchmark_cases_v2()
        )
        with patch.object(module, "benchmark_cases_v2",
                          return_value=patched_cases):
            with self.assertRaisesRegex(
                    BenchmarkProtocolError, "expanded case overlaps v1"):
                validate_v2_cases()

        exact_case_leak = replace(
            current,
            choice_problem="repair_unique_case_leak",
            candidates=("稳定", "新候选"),
            target="稳定",
            positive=tuple(v1_family["positive"]),
            negative=tuple(v1_family["negative"]),
        )
        with patch.object(module, "FAMILY_SPECS", tuple(
                exact_case_leak if family.family_id == current.family_id
                else family for family in module.FAMILY_SPECS)):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        source_sentence_leak = replace(
            current,
            choice_problem="repair_unique_sentence_leak",
            candidates=("可靠", "新候选"),
            positive=(v1_family["positive"][0], current.positive[1]),
        )
        with patch.object(module, "FAMILY_SPECS", tuple(
                source_sentence_leak if family.family_id == current.family_id
                else family for family in module.FAMILY_SPECS)):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()

        candidate_set_leak = replace(
            current,
            choice_problem="repair_unique_candidate_set_leak",
            candidates=tuple(v1_family["candidates"]),
            target=v1_family["target"],
        )
        with patch.object(module, "FAMILY_SPECS", tuple(
                candidate_set_leak if family.family_id == current.family_id
                else family for family in module.FAMILY_SPECS)):
            with self.assertRaises(BenchmarkProtocolError):
                validate_v2_cases()


class SemanticBenchmarkV2ProtocolTest(unittest.TestCase):
    def test_report_requires_frozen_inputs_and_is_one_shot(self):
        with tempfile.TemporaryDirectory(prefix="ac108-v2-test-") as root:
            with self.assertRaises(BenchmarkProtocolError):
                accept_one_shot_report(root, {})
            with self.assertRaises(BenchmarkProtocolError):
                run_fixture_gate(root)
            manifest = freeze_inputs(root)
            fixture = run_fixture_gate(root)
            self.assertTrue(all(result["top_k_order_passed"] == 200
                                for result in fixture["routes"].values()))
            report = build_fixture_report(root, fixture)
            accepted = accept_one_shot_report(root, report)
            self.assertTrue(os.path.isfile(accepted["report_path"]))
            with open(accepted["receipt_path"], encoding="utf-8") as handle:
                receipt = json.load(handle)
            self.assertEqual(report["one_shot_identity"],
                             receipt["one_shot_identity"])
            self.assertEqual("not_run", report["v2_quality"])
            tampered = copy.deepcopy(report)
            tampered["manifest_digest"] = "0" * 64
            tampered_without_digest = {
                key: value for key, value in tampered.items()
                if key != "report_digest"
            }
            from semantic_benchmark_v2 import (  # noqa: PLC0415
                canonical_json,
                sha256_text,
            )
            tampered["report_digest"] = sha256_text(
                canonical_json(tampered_without_digest))
            with self.assertRaises(BenchmarkProtocolError):
                accept_one_shot_report(root, tampered)
            with self.assertRaises(BenchmarkProtocolError):
                accept_one_shot_report(root, report)
            serialized = json.dumps(report, ensure_ascii=False)
            for case in benchmark_cases_v2():
                self.assertNotIn(case.source_query_text, serialized)
                self.assertNotIn(case.source_recorded_text, serialized)
            for name in os.listdir(root):
                path = os.path.join(root, name)
                if not os.path.isfile(path):
                    continue
                with open(path, encoding="utf-8") as handle:
                    artifact = handle.read()
                for marker in PRIVACY_MARKERS:
                    self.assertNotIn(marker, artifact, name)
            self.assertTrue(verify_artifact_privacy(root))

    def test_privacy_probe_rejects_injected_live_content(self):
        with tempfile.TemporaryDirectory(prefix="ac108-v2-privacy-") as root:
            freeze_inputs(root)
            with open(os.path.join(root, "unexpected.txt"), "w",
                      encoding="utf-8") as handle:
                handle.write("private user credential from live facts")
            with self.assertRaises(BenchmarkProtocolError):
                accept_one_shot_report(root, {})

    def test_artifact_boundary_rejects_preexisting_and_unmarked_content(self):
        with tempfile.TemporaryDirectory(prefix="ac108-v2-boundary-") as root:
            with open(os.path.join(root, "semantic_benchmark_v2_report.json"),
                      "w", encoding="utf-8") as handle:
                handle.write("用户输入，不含黑名单关键词")
            with self.assertRaises(BenchmarkProtocolError):
                freeze_inputs(root)

    def test_frozen_manifest_mutation_is_rejected_before_report(self):
        with tempfile.TemporaryDirectory(prefix="ac108-v2-mutation-") as root:
            freeze_inputs(root)
            path = os.path.join(root, "semantic_benchmark_v2_manifest.json")
            with open(path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            manifest["k_evidence"] += 1
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, sort_keys=True)
            with self.assertRaises(BenchmarkProtocolError):
                accept_one_shot_report(root, {})


if __name__ == "__main__":
    unittest.main()
