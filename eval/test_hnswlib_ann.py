#!/usr/bin/env python3
"""Model-free gate for AC-79-v1 hnswlib ANN qualification."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from suffix_walkforward_ac164 import (  # noqa: E402
    PINNED_HISTORY_ID, PINNED_SNAPSHOT_SHA256, PINNED_STORE_EPOCH)
from hnswlib_ann import (  # noqa: E402
    AC164_REPORT_SHA256, AC78_FREEZE_SHA256, AC78_REPORT_SHA256, CONTRACT_ID,
    LEGAL_TERMINALS, ROUTE_ID, Ann79Error, assert_ac78_identities,
    assert_freeze_closed, build_freeze, build_report, cell_identity,
    decide_terminal, directory_bytes, is_finite_h, load_shortlist_cells,
    published_generation_bytes, query_recall, render_markdown, scheme_order,
    select_preset, summarize_cell_queries, verify_privacy)



def _cell(half_life, k_evidence=8, gamma=0.5, saturation_k=1):
    return {
        "route_id": ROUTE_ID,
        "tau_quantile": "0.995",
        "tau": 0.9976091526745896,
        "half_life": half_life,
        "k_evidence": k_evidence,
        "gamma": gamma,
        "saturation_k": saturation_k,
        "margin_p10": 1.0,
    }


class ShortlistAndFreezeTest(unittest.TestCase):

    def test_load_shortlist_from_committed_ac164_report(self):
        path = Path(_ROOT) / "suffix_walkforward_ac164" / (
            "suffix_walkforward_report.json")
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(AC164_REPORT_SHA256, report["report_sha256"])
        finite, controls = load_shortlist_cells(report)
        self.assertEqual(144, len(finite))
        self.assertEqual(36, len(controls))
        self.assertTrue(all(is_finite_h(cell["half_life"]) for cell in finite))
        self.assertTrue(all(not is_finite_h(cell["half_life"])
                            for cell in controls))

    def test_ac78_identities_are_bound(self):
        assert_ac78_identities()
        self.assertEqual(
            "dd888a45c07d3f656effca15cf4ab04fa17c79fa81ddccbaff580921e31032dc",
            AC78_FREEZE_SHA256)
        self.assertEqual(
            "08afd526795885e218271ab7ecc55829701ac6ca28252243ebe32e91bf4c14ab",
            AC78_REPORT_SHA256)

    def test_freeze_fail_closed_on_hash_mismatch(self):
        finite = [_cell(8)] * 144
        controls = [_cell(float("inf"))] * 36
        with self.assertRaises(Ann79Error):
            build_freeze("deadbeef", "0" * 64, PINNED_HISTORY_ID,
                         PINNED_STORE_EPOCH, AC164_REPORT_SHA256,
                         finite, controls, {"route_id": ROUTE_ID})
        freeze = build_freeze(
            "abc", PINNED_SNAPSHOT_SHA256, PINNED_HISTORY_ID,
            PINNED_STORE_EPOCH, AC164_REPORT_SHA256, finite, controls,
            {"route_id": ROUTE_ID, "instruction": "none"})
        self.assertEqual(CONTRACT_ID, freeze["contract"])
        self.assertEqual("hnswlib-hnsw", freeze["ann_backend"])
        self.assertTrue(freeze["declared_before_build"])
        self.assertTrue(freeze["usearch_preset_not_copied"])
        self.assertEqual(4, len(freeze["ann_build_presets"]))
        self.assertEqual([2, 4, 8], freeze["overfetch_multipliers"])
        self.assertEqual([32, 64, 128, 256], freeze["query_search_values"])
        self.assertEqual(AC78_FREEZE_SHA256, freeze["ac78_freeze_sha256"])
        with self.assertRaises(Ann79Error):
            assert_freeze_closed(freeze, PINNED_SNAPSHOT_SHA256,
                                 AC164_REPORT_SHA256, "other")

    def test_privacy_rejects_machine_paths(self):
        with self.assertRaises(Ann79Error):
            verify_privacy({"leak": "/Users/habit/secret"})


class MetricsTest(unittest.TestCase):

    def test_empty_oracle_k_stays_in_denominator(self):
        self.assertEqual(1.0, query_recall((), ()))
        self.assertEqual(0.0, query_recall((), ("a",)))
        self.assertEqual(0.0, query_recall(("a",), ()))
        self.assertEqual(1.0, query_recall(("a", "b"), ("b", "a")))
        self.assertEqual(0.5, query_recall(("a", "b"), ("a",)))
        self.assertEqual(0.0, query_recall(("a",), ("a",), omitted=True))

    def test_summarize_gates(self):
        n = 100
        recalls = [1.0] * n
        summary = summarize_cell_queries(recalls, [True] * n, [True] * n)
        self.assertTrue(summary["pass"])
        bad = summarize_cell_queries([0.5] * n, [True] * n, [True] * n)
        self.assertFalse(bad["pass"])
        self.assertEqual("recall_macro", bad["reason"])
        unmeasured = summarize_cell_queries([], [], [])
        self.assertFalse(unmeasured["pass"])
        self.assertEqual("unmeasured", unmeasured["reason"])

    def test_scheme_order_gamma_zero_matches_baseline(self):
        target = SimpleNamespace(
            final_selection_text="我",
            competition=("握", "我"),
            display_page=1,
            display_rank=2)
        order = scheme_order(target, [0.0, 0.0], 0.0)
        self.assertEqual((0, 1), order)

    def test_select_preset_tie_break(self):
        rows = [
            {"preset_id": "m8-efc100", "overfetch_multiplier": 2,
             "query_search": 32, "meets_ann79_5": True,
             "passing_cells": 2, "hotkey_p95_ms": 12.0,
             "generation_size": 100, "M": 8, "ef_construction": 100},
            {"preset_id": "m16-efc200", "overfetch_multiplier": 4,
             "query_search": 64, "meets_ann79_5": True,
             "passing_cells": 2, "hotkey_p95_ms": 9.0,
             "generation_size": 80, "M": 16, "ef_construction": 200},
        ]
        chosen = select_preset(rows)
        self.assertEqual("m16-efc200", chosen["preset_id"])
        none = [
            {"preset_id": "only", "meets_ann79_5": False,
             "passing_cells": 0, "hotkey_p95_ms": 1.0,
             "generation_size": 1, "overfetch_multiplier": 2,
             "query_search": 32, "M": 8, "ef_construction": 100},
        ]
        fallback = select_preset(none)
        self.assertFalse(fallback["eligible_on_prefix"])

    def test_terminals(self):
        cells = [{"finite_h": True, "pass": True}]
        terminal, passing = decide_terminal(cells, True, True, True)
        self.assertEqual("hnswlib_qualified", terminal)
        self.assertEqual(1, len(passing))
        terminal, passing = decide_terminal(cells, False, True, True)
        self.assertEqual("hnswlib_disqualified", terminal)
        with self.assertRaises(Ann79Error):
            decide_terminal(cells, True, True, False)
        self.assertEqual(
            ("hnswlib_qualified", "hnswlib_disqualified"), LEGAL_TERMINALS)

    def test_report_privacy_and_sha(self):
        finite = [_cell(8)] * 144
        controls = [_cell(float("inf"))] * 36
        freeze = build_freeze(
            "abc", PINNED_SNAPSHOT_SHA256, PINNED_HISTORY_ID,
            PINNED_STORE_EPOCH, AC164_REPORT_SHA256, finite, controls,
            {"route_id": ROUTE_ID})
        selection = {
            "preset_id": "m16-efc200", "M": 16,
            "ef_construction": 200, "overfetch_multiplier": 4,
            "query_search": 64, "eligible_on_prefix": True,
        }
        suffix = [{
            "cell": cell_identity(_cell(8)),
            "finite_h": True,
            "pass": False,
            "reason": "recall_macro",
            "recall_macro": 0.5,
            "recall_p5": 0.4,
            "top1": 0.9,
            "emission": 0.9,
            "n": 10,
        }]
        report = build_report(
            freeze, selection, suffix,
            {"freq": {"pass": False}, "hotkey": {"pass": False}},
            {"pass": False},
            {"pass": True},
            True, "hnswlib_disqualified", "abc")
        self.assertTrue(verify_privacy(report))
        self.assertIn("report_sha256", report)
        self.assertFalse(report["usearch_numbers_substituted"])
        self.assertEqual("usearch_disqualified",
                         report["ac78_terminal_context"])
        markdown = render_markdown(report)
        self.assertIn("hnswlib_disqualified", markdown)
        self.assertIn("## Lifecycle", markdown)
        self.assertNotIn("/Users/", markdown)
        self.assertTrue(markdown.endswith("\n"))
        self.assertFalse(markdown.endswith("\n\n"))


class FixtureRunnerTest(unittest.TestCase):

    def test_fixture_runner_writes_legal_terminal(self):
        import run_hnswlib_ann_qualification as runner
        tmp = tempfile.mkdtemp(prefix="ac79-fix-")
        work = Path(tmp) / "work"
        artifacts = Path(tmp) / "artifacts"
        committed = Path(tmp) / "committed"
        result = runner.run_fixture(work, artifacts, committed)
        self.assertIn(result["terminal"], LEGAL_TERMINALS)
        freeze_path = artifacts / "hnswlib_ann_freeze.json"
        report_path = artifacts / "hnswlib_ann_report.json"
        self.assertTrue(freeze_path.is_file())
        self.assertTrue(report_path.is_file())
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        self.assertTrue(freeze["declared_before_build"])
        self.assertEqual("hnswlib-hnsw", freeze["ann_backend"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(0.0, report["live_gamma"])
        self.assertFalse(report["live_evidence"])
        markdown = (artifacts / "HNSWLIB_ANN_REPORT.md").read_text(
            encoding="utf-8")
        self.assertTrue(markdown.endswith("\n"))
        self.assertFalse(markdown.endswith("\n\n"))


class HarnessContractTest(unittest.TestCase):

    def test_100k_harness_uses_daemon_evidence_service(self):
        text = Path(_ROOT, "hnswlib_ann_100k.py").read_text(encoding="utf-8")
        self.assertNotIn("class _FastService", text)
        self.assertNotIn("class _Zero", text)
        self.assertNotIn("BruteForceIndex", text)
        self.assertIn("daemon-EvidenceService", text)
        self.assertIn("gamma0_control", text)
        daemon = Path(_ROOT, "ac79_evidence_daemon.py").read_text(
            encoding="utf-8")
        self.assertIn("build_evidence_service_from_config", daemon)
        self.assertIn("hnswlib-hnsw", daemon)
        self.assertIn("control_gamma", daemon)
        self.assertNotIn("usearch-hnsw", daemon)

    def test_generation_disk_walks_fp32_and_ann(self):
        tmp = tempfile.mkdtemp(prefix="ac79-disk-")
        gen = Path(tmp) / "generations" / "g1"
        ann = Path(tmp) / "index" / "g1"
        gen.mkdir(parents=True)
        ann.mkdir(parents=True)
        (gen / "vectors.fp32").write_bytes(b"x" * 100)
        (gen / "metadata.json").write_bytes(b"y" * 20)
        (ann / "index.ann").write_bytes(b"z" * 30)
        self.assertEqual(150, published_generation_bytes(tmp, "g1"))
        self.assertEqual(150, directory_bytes(tmp))

    def test_does_not_overwrite_usearch_artifacts(self):
        from hnswlib_ann import committed_artifact_dir
        usearch = Path(_ROOT) / "usearch_ann_qualification"
        self.assertTrue((usearch / "usearch_ann_freeze.json").is_file())
        runner = Path(_ROOT, "run_hnswlib_ann_qualification.py").read_text(
            encoding="utf-8")
        self.assertNotIn("usearch_ann_qualification", runner)
        self.assertEqual("hnswlib_ann_qualification",
                         committed_artifact_dir().name)


if __name__ == "__main__":
    unittest.main()
