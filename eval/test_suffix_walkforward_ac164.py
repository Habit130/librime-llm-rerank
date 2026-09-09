#!/usr/bin/env python3
"""Model-free gate for the AC-164-v1 3000-milestone exact walk-forward."""

import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from fixture_facts import SyntheticFacts  # noqa: E402
from grid_cc import grid_manifest  # noqa: E402
from shortlist_cc import (  # noqa: E402
    TERMINAL_EXACT, TERMINAL_INSUFFICIENT, TERMINAL_NARROWED,
    TERMINAL_NO_QUALIFIED, assemble_shortlist)
from suffix_report import verify_privacy  # noqa: E402
from walkforward_cc import (  # noqa: E402
    BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, PREFIX_HLC_MAX_INCLUSIVE, ROUTE_IDS,
    FrozenFacts, prefix_suffix_split)
from suffix_walkforward_ac164 import (  # noqa: E402
    CONTRACT_ID, ENGINE_CONTRACT, ENTRY_CENSUS, LEGAL_TERMINALS,
    PINNED_HISTORY_ID, PINNED_PREFIX_EVENT_COUNT, PINNED_PREFIX_SHA256,
    PINNED_SNAPSHOT_SHA256, PINNED_STORE_EPOCH, PINNED_SUFFIX_EVENT_COUNT,
    PINNED_SUFFIX_SHA256, Ac164Error, annotate_freeze, annotate_report,
    assert_entry_census, assert_legal_terminal, assert_split,
    bind_preserved_snapshot, ensure_not_historical, entry_census_from_counts,
    file_sha256, isolate_readonly_snapshot)
import run_suffix_walkforward as wf_runner  # noqa: E402
import run_suffix_walkforward_ac164 as ac164_runner  # noqa: E402


def _synthetic_with_split():
    facts = SyntheticFacts()
    cutoff = PREFIX_HLC_MAX_INCLUSIVE
    try:
        facts.add_event("p1", "wo", "前1", "我", ("我", "握"),
                        cutoff, display_rank=1, display_page=1)
        facts.add_event("p2", "wo", "前2", "握", ("我", "握"),
                        (cutoff[0] - 1000, cutoff[1]),
                        display_rank=2, display_page=1)
        facts.add_event("s1", "wo", "后4", "握", ("我", "握"),
                        (cutoff[0] + 1000, cutoff[1]),
                        display_rank=2, display_page=1)
        facts.add_event("s2", "wo", "后5", "我", ("我", "握"),
                        (cutoff[0] + 2000, cutoff[1]),
                        display_rank=1, display_page=1)
        return facts
    except Exception:
        facts.close()
        raise


class IdentityPinTest(unittest.TestCase):

    def test_frozen_identities(self):
        self.assertEqual(CONTRACT_ID, "AC-164-v1")
        self.assertEqual(ENGINE_CONTRACT, "AC-159-v1")
        self.assertEqual(ROUTE_IDS, (
            "dedicated_qwen3_embedding_0_6b",
            "qwen_l28_candidate_span_mean",
            "dedicated_bge_m3"))
        self.assertEqual(PREFIX_HLC_MAX_INCLUSIVE, (1787667799562, 0))
        self.assertEqual(PINNED_SNAPSHOT_SHA256,
                         "111517b4548ad97cb73c801a3099076d70f90afc36bf94eb"
                         "13f3fd1121cd94f5")
        self.assertEqual(PINNED_HISTORY_ID, "dc3ffbf1a21957e0bb4ceed535c9df56")
        self.assertEqual(PINNED_STORE_EPOCH,
                         "8407bd6b456ba5c5a526b4b95951bac3")
        self.assertEqual(PINNED_PREFIX_EVENT_COUNT, 4844)
        self.assertEqual(PINNED_SUFFIX_EVENT_COUNT, 3901)
        self.assertEqual(BOOTSTRAP_SEED, 20260817)
        self.assertEqual(BOOTSTRAP_REPLICATES, 10000)
        self.assertEqual(ENTRY_CENSUS["total_actionable_group_complete"], 4907)
        self.assertEqual(ENTRY_CENSUS["prefix_actionable_keys"], 421)
        self.assertEqual(ENTRY_CENSUS["suffix_actionable_keys"], 479)
        self.assertEqual(ENTRY_CENSUS["total_actionable_keys"], 611)

    def test_grid_is_the_frozen_ac159_space(self):
        manifest = grid_manifest(10000)
        self.assertEqual(manifest["alpha"], 0.0)
        self.assertEqual(manifest["routes"], list(ROUTE_IDS))
        self.assertEqual(manifest["half_lives"], [8, 32, 128, 512, "inf"])
        self.assertEqual(manifest["k_evidence"], [8, 16, 32, 64])
        self.assertEqual(manifest["gamma"], [0.5, 1.0, 2.0, 4.0])
        self.assertEqual(manifest["saturation_k"], [1, 3, 7])
        self.assertEqual(manifest["tau_quantiles"],
                         ["Q95", "Q97.5", "Q99", "Q99.5"])
        self.assertEqual(manifest["replicates"], 10000)

    def test_bind_fixture_snapshot_keeps_synthetic_identity(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        record = bind_preserved_snapshot(facts.db_path, fixture=True)
        self.assertEqual(record["identity"]["history_id"], "synthetic-history")
        self.assertEqual(record["identity"]["store_epoch"], "synthetic-epoch")
        self.assertEqual(record["sha256"], file_sha256(facts.db_path))

    def test_bind_refuses_unpinned_snapshot(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        with self.assertRaises(Ac164Error):
            bind_preserved_snapshot(facts.db_path, fixture=False)

    def test_bind_refuses_missing_store_identity(self):
        facts = SyntheticFacts()
        self.addCleanup(facts.close)
        facts.connection.execute("DELETE FROM meta WHERE key='store_epoch'")
        facts.connection.commit()
        with self.assertRaises(Ac164Error):
            bind_preserved_snapshot(facts.db_path, fixture=True)

    def test_isolate_copy_has_no_wal(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        temp = tempfile.mkdtemp(prefix="ac164_iso_")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        dest = isolate_readonly_snapshot(facts.db_path, temp)
        self.assertTrue(dest.is_file())
        self.assertFalse(dest.with_name(dest.name + "-wal").exists())
        self.assertEqual(file_sha256(dest), file_sha256(facts.db_path))


class SplitAndCensusTest(unittest.TestCase):

    def test_assert_split_rejects_moved_cutoff(self):
        with self.assertRaises(Ac164Error):
            assert_split({"cutoff_hlc": [0, 0]}, fixture=True)

    def test_assert_split_pins_counts_and_hashes(self):
        with self.assertRaises(Ac164Error):
            assert_split({
                "cutoff_hlc": [1787667799562, 0],
                "prefix_event_count": 1,
                "suffix_event_count": PINNED_SUFFIX_EVENT_COUNT,
                "prefix_sha256": PINNED_PREFIX_SHA256,
                "suffix_sha256": PINNED_SUFFIX_SHA256,
                "snapshot_sha256": PINNED_SNAPSHOT_SHA256,
            }, fixture=False)

    def test_entry_census_fail_closed(self):
        prefix = {"actionable_group_complete": 2537, "actionable_keys": 421}
        suffix = {"actionable_group_complete": 2370, "actionable_keys": 479}
        total = {"actionable_group_complete": 4907, "actionable_keys": 611}
        self.assertEqual(assert_entry_census(prefix, suffix, total),
                         ENTRY_CENSUS)
        with self.assertRaises(Ac164Error):
            assert_entry_census(
                prefix, {"actionable_group_complete": 13,
                         "actionable_keys": 12},
                {"actionable_group_complete": 2550, "actionable_keys": 430})

    def test_total_keys_are_union_not_sum(self):
        actual = entry_census_from_counts(
            {"actionable_group_complete": 2537, "actionable_keys": 421},
            {"actionable_group_complete": 2370, "actionable_keys": 479},
            {"actionable_group_complete": 4907, "actionable_keys": 611})
        self.assertNotEqual(
            actual["total_actionable_keys"],
            actual["prefix_actionable_keys"] + actual["suffix_actionable_keys"])


class FreezeReportTest(unittest.TestCase):

    def _base_freeze(self, facts):
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = [event for event in db.events() if not event.retracted]
        prefix, suffix = prefix_suffix_split(events)
        snapshot = bind_preserved_snapshot(facts.db_path, fixture=True)
        freeze = {
            "contract": "AC-159-v1",
            "code_sha": "a" * 40,
            "snapshot_sha256": snapshot["sha256"],
            "seed": BOOTSTRAP_SEED,
            "grid_manifest": grid_manifest(BOOTSTRAP_REPLICATES),
            "routes": {route_id: {"route_id": route_id}
                       for route_id in ROUTE_IDS},
        }
        return snapshot, prefix, suffix, freeze

    def test_annotate_freeze_binds_ac164_identities(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        snapshot, prefix, suffix, freeze = self._base_freeze(facts)
        annotated = annotate_freeze(
            freeze, snapshot, prefix, suffix, fixture=True)
        self.assertEqual(annotated["contract"], "AC-164-v1")
        self.assertEqual(annotated["engine_contract"], "AC-159-v1")
        self.assertEqual(annotated["history_id"], "synthetic-history")
        self.assertEqual(annotated["store_epoch"], "synthetic-epoch")
        self.assertEqual(annotated["cutoff_hlc"], [1787667799562, 0])
        self.assertEqual(annotated["bootstrap_seed"], BOOTSTRAP_SEED)
        self.assertEqual(annotated["bootstrap_replicates"], 10000)
        self.assertEqual(annotated["entry_census_expected"], ENTRY_CENSUS)
        self.assertEqual(annotated["split"]["prefix_event_count"], 2)
        self.assertEqual(annotated["split"]["suffix_event_count"], 2)
        self.assertTrue(verify_privacy(annotated))
        serialized = repr(annotated)
        self.assertNotIn("前1", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_annotate_freeze_requires_three_routes(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        snapshot, prefix, suffix, freeze = self._base_freeze(facts)
        freeze["routes"] = {"dedicated_qwen3_embedding_0_6b": {}}
        with self.assertRaises(Ac164Error):
            annotate_freeze(freeze, snapshot, prefix, suffix, fixture=True)

    def test_annotate_report_privacy_and_contract(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        snapshot, prefix, suffix, freeze = self._base_freeze(facts)
        freeze = annotate_freeze(
            freeze, snapshot, prefix, suffix, fixture=True)
        report = annotate_report(
            {"notes": [], "decision": {"outcome": "无合格方案"}},
            freeze, {"actionable_group_complete": 0}, fixture=True)
        self.assertEqual(report["contract"], "AC-164-v1")
        self.assertIn("report_sha256", report)
        self.assertFalse(report["entry_census"]["matched"])
        self.assertTrue(verify_privacy(report))


class TerminalAndDecisionSurfaceTest(unittest.TestCase):

    def test_legal_terminals(self):
        self.assertEqual(LEGAL_TERMINALS, (
            TERMINAL_EXACT, TERMINAL_NARROWED, TERMINAL_NO_QUALIFIED,
            TERMINAL_INSUFFICIENT))
        assert_legal_terminal({"outcome": "无合格方案", "per_route": []})
        with self.assertRaises(Ac164Error):
            assert_legal_terminal({"outcome": "ann_winner"})

    def test_shortlist_rejects_unmeasured_cell(self):
        with self.assertRaises(Ac164Error):
            assert_legal_terminal({
                "outcome": "exact_shortlist",
                "per_route": [{"eligible": [{
                    "hard_gates": {"pass": True, "evaluated": False,
                                   "unevaluated": ["mispromotion_ci"]},
                }]}],
            })

    def test_public_b_and_personal_r_are_not_decision_inputs(self):
        signature = inspect.signature(assemble_shortlist)
        names = set(signature.parameters)
        self.assertNotIn("public_b", names)
        self.assertNotIn("public_b_accuracy", names)
        self.assertNotIn("personal_r", names)
        self.assertNotIn("r", names)


class HistoricalPathTest(unittest.TestCase):

    def test_historical_dirs_are_read_only(self):
        eval_dir = _ROOT
        with self.assertRaises(Ac164Error):
            ensure_not_historical(
                os.path.join(eval_dir, "suffix_walkforward"),
                eval_dir, "artifact")
        with self.assertRaises(Ac164Error):
            ensure_not_historical(
                os.path.join(eval_dir, "suffix_walkforward_ac159"),
                eval_dir, "artifact")
        with self.assertRaises(Ac164Error):
            ensure_not_historical(
                os.path.join(eval_dir, "actionable_milestone_census"),
                eval_dir, "artifact")
        temp = tempfile.mkdtemp(prefix="ac164_ok_")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        ensure_not_historical(temp, eval_dir, "artifact")


class DriverFixtureTest(unittest.TestCase):

    def _run(self, snapshot_path, extra=None):
        temp = tempfile.mkdtemp(prefix="ac164_test_")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        work = os.path.join(temp, "work")
        artifact = os.path.join(temp, "artifacts")
        committed = os.path.join(temp, "committed")
        argv = ["--delivery", "ac164", "--fixture", "--snapshot",
                snapshot_path, "--work-dir", work,
                "--artifact-dir", artifact,
                "--committed-artifact-dir", committed,
                "--max-cells", "1"]
        if extra:
            argv.extend(extra)
        with mock.patch.object(wf_runner, "current_code_sha",
                               return_value="b" * 40):
            status = wf_runner.main(argv)
        return status, artifact, committed, work

    def test_fixture_driver_writes_ac164_freeze_and_report(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        status, artifact, committed, work = self._run(facts.db_path)
        self.assertEqual(status, 0)
        freeze = json.load(open(os.path.join(
            artifact, "suffix_walkforward_freeze.json"), encoding="utf-8"))
        report = json.load(open(os.path.join(
            artifact, "suffix_walkforward_report.json"), encoding="utf-8"))
        self.assertEqual(freeze["contract"], "AC-164-v1")
        self.assertEqual(freeze["engine_contract"], "AC-159-v1")
        self.assertEqual(freeze["code_sha"], "b" * 40)
        self.assertEqual(set(freeze["routes"]), set(ROUTE_IDS))
        self.assertEqual(freeze["cutoff_hlc"], [1787667799562, 0])
        self.assertEqual(freeze["bootstrap_replicates"], 10000)
        self.assertEqual(report["contract"], "AC-164-v1")
        self.assertIn(report["decision"]["outcome"], LEGAL_TERMINALS)
        self.assertEqual(report["claim_support"]["public_b_unused"], True)
        self.assertEqual(report["claim_support"]["personal_2x2_r_unused"], True)
        self.assertEqual(report["claim_support"]["live_gamma"], 0.0)
        self.assertTrue(os.path.isfile(os.path.join(
            work, "facts-snapshot-ac162.sqlite3")))
        for name in ("suffix_walkforward_freeze.json",
                     "suffix_walkforward_report.json",
                     "SUFFIX_WALKFORWARD_REPORT.md"):
            with open(os.path.join(artifact, name), "rb") as src, \
                    open(os.path.join(committed, name), "rb") as dst:
                self.assertEqual(src.read(), dst.read())
        self.assertTrue(verify_privacy(freeze))
        self.assertTrue(verify_privacy(report))
        serialized = repr(report) + repr(freeze)
        self.assertNotIn("前1", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_live_backup_is_refused(self):
        with mock.patch.object(wf_runner, "take_snapshot") as take, \
                mock.patch.object(wf_runner, "current_code_sha",
                                  return_value="b" * 40):
            status = wf_runner.main(["--delivery", "ac164"])
        self.assertEqual(status, 3)
        take.assert_not_called()
        self.assertEqual(ac164_runner.main([]), 3)

    def test_unpinned_real_snapshot_is_contract_failure(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        temp = tempfile.mkdtemp(prefix="ac164_badpin_")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        with mock.patch.object(wf_runner, "current_code_sha",
                               return_value="b" * 40):
            status = wf_runner.main([
                "--delivery", "ac164", "--snapshot", facts.db_path,
                "--work-dir", temp, "--artifact-dir", temp,
                "--committed-artifact-dir", os.path.join(temp, "out")])
        self.assertEqual(status, 4)

    def test_historical_committed_dir_is_blocker(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        temp = tempfile.mkdtemp(prefix="ac164_hist_")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        with mock.patch.object(wf_runner, "current_code_sha",
                               return_value="b" * 40):
            status = wf_runner.main([
                "--delivery", "ac164", "--fixture",
                "--snapshot", facts.db_path,
                "--work-dir", temp, "--artifact-dir", temp,
                "--committed-artifact-dir",
                os.path.join(_ROOT, "suffix_walkforward_ac159")])
        self.assertEqual(status, 3)


if __name__ == "__main__":
    unittest.main()
