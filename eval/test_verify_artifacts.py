#!/usr/bin/env python3
"""Rank-derived calibration artifact checks (Habit130/squirrel#137).

Verification must recompute decision-driving metrics and harmful-regression
counts from committed case_ranks. Copied summaries that disagree with those
ranks fail closed. Model-free: no console, daemon, model, or live Rime dir.
"""

import copy
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from calibrate import harmful_regressions_for_run, metrics_from_ranks
from verify_artifacts import verify_rank_derived_summaries


EVAL_DIR = Path(__file__).resolve().parent


def _load_committed():
    results = json.loads((EVAL_DIR / "results.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (EVAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    return results, manifest


class RankDerivedSummariesTest(unittest.TestCase):
    def setUp(self):
        self.results, self.manifest = _load_committed()

    def test_committed_artifacts_agree_with_case_ranks(self):
        # SCN-137-1 / SCN-137-4
        self.assertEqual(
            verify_rank_derived_summaries(self.results, self.manifest), [])

    def test_mutated_ranks_with_old_summaries_fail(self):
        # SCN-137-2
        results = copy.deepcopy(self.results)
        ranks = results["case_ranks"]["mean_alpha_2.0"]["word"]
        self.assertEqual(ranks[0], 1)
        ranks[0] = 9
        failures = verify_rank_derived_summaries(results, self.manifest)
        self.assertTrue(
            any("mean_alpha_2.0" in item and "metrics" in item
                for item in failures),
            failures)

    def test_mutated_results_metrics_with_kept_ranks_fail(self):
        # SCN-137-3
        results = copy.deepcopy(self.results)
        word = results["runs"]["mean_alpha_2.0"]["metrics"]["word"]
        word["top1"] = word["top1"] + 1
        word["top1_rate"] = word["top1"] / word["samples"]
        failures = verify_rank_derived_summaries(results, self.manifest)
        self.assertTrue(
            any("mean_alpha_2.0" in item and "results metrics" in item
                for item in failures),
            failures)

    def test_mutated_manifest_metrics_with_kept_ranks_fail(self):
        # SCN-137-3
        manifest = copy.deepcopy(self.manifest)
        word = manifest["runs"]["mean_alpha_2.0"]["metrics"]["word"]
        word["top1"] = word["top1"] + 1
        word["top1_rate"] = word["top1"] / word["samples"]
        failures = verify_rank_derived_summaries(self.results, manifest)
        self.assertTrue(
            any("mean_alpha_2.0" in item and "manifest metrics" in item
                for item in failures),
            failures)

    def test_mutated_harmful_regression_summary_fails(self):
        results = copy.deepcopy(self.results)
        stored = results["harmful_regressions"]["mean_alpha_2.0"]
        stored["count"] = stored["count"] + 1
        failures = verify_rank_derived_summaries(results, self.manifest)
        self.assertTrue(
            any("harmful_regressions" in item and "results" in item
                for item in failures),
            failures)

    def test_stale_decision_after_consistent_rank_rewrite_fails(self):
        results = copy.deepcopy(self.results)
        manifest = copy.deepcopy(self.manifest)
        key = "mean_alpha_0.5"
        results["case_ranks"][key]["word"] = [1] * len(
            results["case_ranks"][key]["word"])
        derived = metrics_from_ranks(results["case_ranks"][key])
        results["runs"][key]["metrics"] = derived
        manifest["runs"][key]["metrics"] = derived
        regressions = harmful_regressions_for_run(
            results["case_ranks"]["baseline"]["word"],
            results["case_ranks"][key]["word"])
        results["harmful_regressions"][key] = regressions
        manifest["runs"][key]["harmful_regressions"] = regressions
        failures = verify_rank_derived_summaries(results, manifest)
        self.assertTrue(any("decision field" in item for item in failures),
                        failures)

    def test_missing_case_ranks_fail_closed(self):
        results = copy.deepcopy(self.results)
        del results["case_ranks"]["mean_alpha_2.0"]
        failures = verify_rank_derived_summaries(results, self.manifest)
        self.assertTrue(
            any("mean_alpha_2.0" in item and "missing" in item
                for item in failures),
            failures)


if __name__ == "__main__":
    unittest.main()
