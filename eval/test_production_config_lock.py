#!/usr/bin/env python3
"""Model-free gate for AC-80-v1 production configuration lock."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from production_config_lock import (  # noqa: E402
    BACKENDS, CONTRACT_ID, GATES, LEGAL_TERMINALS, Lock80Error,
    assert_freeze_closed, build_freeze, build_manifest, build_report,
    decide_lock, evaluate_row, load_bound_bundle, render_markdown,
    tie_break, verify_privacy)
from suffix_walkforward_ac164 import (  # noqa: E402
    PINNED_HISTORY_ID, PINNED_SNAPSHOT_SHA256, PINNED_STORE_EPOCH)
from usearch_ann import (  # noqa: E402
    AC164_REPORT_SHA256, cell_identity, is_finite_h)


def _cell(half_life=8, k_evidence=8, gamma=0.5, saturation_k=1):
    return {
        "route_id": "dedicated_bge_m3",
        "tau_quantile": "0.995",
        "tau": 0.9976091526745896,
        "half_life": half_life,
        "k_evidence": k_evidence,
        "gamma": gamma,
        "saturation_k": saturation_k,
    }


def _record(cell=None, claimable=False, lift_pass=None, selected=True,
            quality=True):
    cell = cell or _cell()
    return {
        "cell": cell,
        "selected": selected,
        "delta_one_ok": quality,
        "hard_gates": {
            "evaluated": True,
            "pass": quality,
            "unevaluated": [],
            "safety_top1_ok": True,
            "safety_mrr_ok": True,
            "mispromotion_point_ok": True,
            "mispromotion_ci_ok": True,
            "pollution_point_ok": True,
            "pollution_ci_ok": True,
        },
        "finite_h_gate": {
            "evaluated": True,
            "pass": quality,
        },
        "lift": {
            "claimable": claimable,
            "pass": lift_pass,
            "reason": "ok" if claimable else "+3pp unclaimable",
        },
        "ci": {"top1_vs_baseline": [0.02, [0.01, 0.03]]},
        "metrics": {"actionable_group_complete": 13},
    }


def _backend_state(retrieval=True, retrieval_evaluated=True,
                    resource=True, resource_evaluated=True,
                    retrieval_reason="ok", resource_reason="ok"):
    return {
        "retrieval_equivalence": {
            "evaluated": retrieval_evaluated,
            "pass": retrieval and retrieval_evaluated,
            "reason": retrieval_reason if retrieval_evaluated else "unmeasured",
        },
        "latency_memory_disk": {
            "evaluated": resource_evaluated,
            "pass": resource and resource_evaluated,
            "reason": resource_reason if resource_evaluated else "unmeasured",
        },
    }


class FreezeTest(unittest.TestCase):

    def test_freeze_binds_hashes_rules_and_has_no_terminal(self):
        bundle = load_bound_bundle()
        freeze = build_freeze("a" * 40, bundle)
        self.assertEqual(CONTRACT_ID, freeze["contract"])
        self.assertEqual(PINNED_SNAPSHOT_SHA256, freeze["snapshot_sha256"])
        self.assertEqual(AC164_REPORT_SHA256, freeze["ac164_report_sha256"])
        self.assertEqual(
            "dd888a45c07d3f656effca15cf4ab04fa17c79fa81ddccbaff580921e31032dc",
            freeze["ac78_freeze_sha256"])
        self.assertEqual(
            "08afd526795885e218271ab7ecc55829701ac6ca28252243ebe32e91bf4c14ab",
            freeze["ac78_report_sha256"])
        self.assertEqual(
            "1c39fa4f533b7000f5e97173fbd0525030cc6ef322bc31dc4b0bd1fdaf0bd58c",
            freeze["ac79_freeze_sha256"])
        self.assertEqual(
            "13a99ee56379314098c0e378ff02fcc40c47982e3209bae1b57573ec4a09db71",
            freeze["ac79_report_sha256"])
        self.assertEqual([1787667799562, 0], freeze["cutoff_hlc"])
        self.assertEqual(list(GATES), freeze["elimination_gates"])
        self.assertEqual(list(BACKENDS), freeze["backends"])
        self.assertEqual(list(LEGAL_TERMINALS), freeze["legal_terminals"])
        self.assertEqual("收窄声称_shortlist", freeze["bound_terminals"]["ac164"])
        self.assertEqual("usearch_disqualified", freeze["bound_terminals"]["ac78"])
        self.assertEqual("hnswlib_disqualified", freeze["bound_terminals"]["ac79"])
        self.assertEqual("不合格", freeze["bound_terminals"]["ac72"])
        self.assertEqual("不合格", freeze["bound_terminals"]["ac73"])
        self.assertEqual(
            "not_production_exact_hot_path", freeze["bound_terminals"]["ac71"])
        self.assertTrue(freeze["declared_before_decision"])
        self.assertNotIn("terminal", freeze)
        self.assertEqual(144, len(freeze["qualification_cells"]))
        self.assertTrue(all(is_finite_h(cell["half_life"])
                            for cell in freeze["qualification_cells"]))
        with self.assertRaises(Lock80Error):
            build_freeze("deadbeef", bundle)
        with self.assertRaises(Lock80Error):
            assert_freeze_closed(freeze, PINNED_SNAPSHOT_SHA256,
                                 AC164_REPORT_SHA256, "b" * 40)

    def test_privacy_rejects_machine_paths(self):
        with self.assertRaises(Lock80Error):
            verify_privacy({"leak": "/Users/habit/secret"})


class EliminationTest(unittest.TestCase):

    def test_unclaimable_plus3pp_never_survives(self):
        backends = {
            "exact": _backend_state(),
            "usearch-hnsw": _backend_state(
                resource=False, resource_reason="usearch_disqualified"),
        }
        row = evaluate_row(_record(claimable=False), "exact", backends)
        self.assertFalse(row["survive"])
        self.assertEqual("claimable_plus3pp", row["failing_gate_id"])

    def test_unmeasured_never_survives(self):
        backends = {
            "sqlite-vec": _backend_state(
                retrieval=False, retrieval_evaluated=False,
                resource=False, resource_evaluated=False),
        }
        row = evaluate_row(
            _record(claimable=True, lift_pass=True), "sqlite-vec", backends)
        self.assertFalse(row["survive"])
        self.assertEqual("retrieval_equivalence", row["failing_gate_id"])
        self.assertEqual("unmeasured", row["gates"]["retrieval_equivalence"]["reason"])

    def test_disqualified_ann_fails_resource_after_claimable(self):
        backends = {
            "usearch-hnsw": _backend_state(
                resource=False, resource_reason="usearch_disqualified"),
        }
        row = evaluate_row(
            _record(claimable=True, lift_pass=True), "usearch-hnsw", backends)
        self.assertFalse(row["survive"])
        self.assertEqual("latency_memory_disk", row["failing_gate_id"])

    def test_quality_failure_is_first_gate(self):
        backends = {"exact": _backend_state()}
        row = evaluate_row(
            _record(claimable=True, lift_pass=True, quality=False),
            "exact", backends)
        self.assertFalse(row["survive"])
        self.assertEqual("quality_safety_pollution_finite_h", row["failing_gate_id"])

    def test_all_gates_pass_survives(self):
        backends = {"exact": _backend_state()}
        row = evaluate_row(
            _record(claimable=True, lift_pass=True), "exact", backends)
        self.assertTrue(row["survive"])
        self.assertIsNone(row["failing_gate_id"])


class DecisionTest(unittest.TestCase):

    def test_empty_survivors_are_无合格配置(self):
        bundle = load_bound_bundle()
        freeze = build_freeze("a" * 40, bundle)
        decision = decide_lock(freeze, bundle)
        self.assertEqual("无合格配置", decision["terminal"])
        self.assertEqual(0, decision["survivor_count"])
        self.assertEqual(144 * len(BACKENDS), len(decision["matrix"]))
        self.assertTrue(all(not row["survive"] for row in decision["matrix"]))
        self.assertTrue(all(row["failing_gate_id"] == "claimable_plus3pp"
                            for row in decision["matrix"]))
        self.assertNotIn("inf", [row["cell"]["half_life"]
                                 for row in decision["matrix"]])
        report = build_report(freeze, decision, "a" * 40)
        self.assertEqual(0.0, report["live_alpha"])
        self.assertEqual(0.0, report["live_gamma"])
        self.assertFalse(report["live_evidence"])
        self.assertFalse(report["issue_81_started"])
        self.assertEqual("not_opened", report["prospective_start_hlc"])
        self.assertEqual(5000, report["next_milestone_wait"])
        manifest = report["manifest"]
        for field in ("baseline", "representation", "H", "tau", "K", "gamma",
                      "k", "generation_format", "backend", "search_parameters"):
            self.assertIsNone(manifest[field])
        self.assertEqual("无合格配置", manifest["omitted_reason"])
        self.assertTrue(verify_privacy(report))
        markdown = render_markdown(report)
        self.assertIn("无合格配置", markdown)
        self.assertNotIn("/Users/", markdown)
        self.assertTrue(markdown.endswith("\n"))
        self.assertFalse(markdown.endswith("\n\n"))

    def test_tie_break_only_on_survivors(self):
        rows = [
            {
                "survive": True,
                "backend": "usearch-hnsw",
                "cell": cell_identity(_cell(8, 16, 1.0, 1)),
                "lift_ci_lower": 0.01,
                "resource_p95_ms": 10.0,
                "generation_bytes": 10,
            },
            {
                "survive": True,
                "backend": "exact",
                "cell": cell_identity(_cell(8, 8, 0.5, 7)),
                "lift_ci_lower": 0.01,
                "resource_p95_ms": 12.0,
                "generation_bytes": 10,
            },
            {
                "survive": False,
                "backend": "mlx-exact-matmul",
                "cell": cell_identity(_cell(512, 8, 0.5, 7)),
                "lift_ci_lower": 0.9,
                "resource_p95_ms": 1.0,
                "generation_bytes": 1,
            },
        ]
        chosen = tie_break([row for row in rows if row["survive"]])
        self.assertEqual("exact", chosen["backend"])
        self.assertEqual(8, chosen["cell"]["k_evidence"])

    def test_unique_lock_manifest_and_hlc(self):
        winner = {
            "survive": True,
            "backend": "exact",
            "cell": cell_identity(_cell(32, 8, 0.5, 3)),
            "lift_ci_lower": 0.04,
            "resource_p95_ms": 9.0,
            "generation_bytes": 100,
            "bge": {"route_id": "dedicated_bge_m3", "format": "fp32-l2"},
        }
        manifest = build_manifest(
            "unique_lock", winner,
            prospective_hlc=[1787667799563, 0])
        self.assertEqual(32, manifest["H"])
        self.assertEqual(8, manifest["K"])
        self.assertEqual(0.5, manifest["gamma"])
        self.assertEqual(3, manifest["k"])
        self.assertEqual("exact", manifest["backend"])
        self.assertEqual("fp32-l2", manifest["generation_format"])
        self.assertIsNone(manifest["omitted_reason"])
        with self.assertRaises(Lock80Error):
            build_manifest("unique_lock", winner, prospective_hlc="not_opened")
        empty = build_manifest("无合格配置", None, prospective_hlc="not_opened")
        self.assertEqual("not_opened", empty["prospective_start_hlc"])

    def test_illegal_terminal_rejected(self):
        bundle = load_bound_bundle()
        freeze = build_freeze("a" * 40, bundle)
        decision = decide_lock(freeze, bundle)
        decision = dict(decision)
        decision["terminal"] = "exact_shortlist"
        with self.assertRaises(Lock80Error):
            build_report(freeze, decision, "a" * 40)


class RunnerTest(unittest.TestCase):

    def test_runner_writes_freeze_before_decision(self):
        import run_production_config_lock as runner
        tmp = tempfile.mkdtemp(prefix="ac80-")
        artifacts = Path(tmp) / "artifacts"
        committed = Path(tmp) / "committed"
        result = runner.run_bound(artifacts, committed, code_sha="a" * 40)
        self.assertIn(result["terminal"], LEGAL_TERMINALS)
        freeze_path = artifacts / "production_config_lock_freeze.json"
        report_path = artifacts / "production_config_lock_report.json"
        self.assertTrue(freeze_path.is_file())
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        self.assertTrue(freeze["declared_before_decision"])
        self.assertNotIn("terminal", freeze)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(freeze["freeze_sha256"], report["freeze_sha256"])
        self.assertEqual(0.0, report["live_gamma"])
        self.assertFalse(report["live_evidence"])
        self.assertFalse(report["issue_81_started"])
        self.assertEqual("not_opened", report["prospective_start_hlc"])
        self.assertTrue((committed / "production_config_lock_freeze.json").is_file())
        markdown = (artifacts / "PRODUCTION_CONFIG_LOCK_REPORT.md").read_text(
            encoding="utf-8")
        self.assertTrue(markdown.endswith("\n"))
        self.assertFalse(markdown.endswith("\n\n"))
        self.assertNotIn("/Users/", markdown)


if __name__ == "__main__":
    unittest.main()
