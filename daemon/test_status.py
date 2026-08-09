#!/usr/bin/env python3
"""Tests for the reusable status core (Habit130/squirrel#51).

Model-free: no MLX, no daemon process; the daemon handshake is exercised
against a tiny in-test unix socket server speaking the health protocol. All
filesystem fixtures live in temporary directories.
"""

import json
import os
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from status_core import (  # noqa: E402
    collect_status,
    compute_exit_code,
    render_human,
    resolve_switch_config,
)

FACT_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE commits (
  commit_id TEXT PRIMARY KEY NOT NULL,
  utc_committed_at_ms INTEGER NOT NULL);
CREATE TABLE selection_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL REFERENCES commits(commit_id),
  event_format_version INTEGER NOT NULL,
  schema_id TEXT NOT NULL,
  canonical_segment_input TEXT NOT NULL,
  span_start INTEGER NOT NULL,
  span_end INTEGER NOT NULL,
  category TEXT NOT NULL,
  preceding_text TEXT NOT NULL,
  competition_complete INTEGER NOT NULL,
  final_selection_text TEXT NOT NULL,
  confirmation_source TEXT NOT NULL,
  trigger_keycode INTEGER,
  display_rank INTEGER NOT NULL,
  display_page INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  session_seq INTEGER NOT NULL,
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  utc_confirmed_at_ms INTEGER NOT NULL,
  utc_committed_at_ms INTEGER NOT NULL);
CREATE INDEX idx_selection_events_commit_id
  ON selection_events(commit_id);
CREATE TABLE selection_candidates (
  event_id TEXT NOT NULL REFERENCES selection_events(event_id),
  merge_order INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (event_id, merge_order));
CREATE TABLE retractions (
  retraction_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL REFERENCES commits(commit_id),
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  utc_retracted_at_ms INTEGER NOT NULL);
CREATE UNIQUE INDEX idx_retractions_commit_id ON retractions(commit_id);
CREATE VIEW active_events AS
  SELECT e.event_id, e.commit_id, e.event_format_version, e.schema_id,
    e.canonical_segment_input, e.span_start, e.span_end, e.category,
    e.preceding_text, e.competition_complete, e.final_selection_text,
    e.confirmation_source, e.trigger_keycode, e.display_rank, e.display_page,
    e.session_id, e.session_seq, e.hlc_physical_ms, e.hlc_logical,
    e.utc_confirmed_at_ms, e.utc_committed_at_ms
  FROM selection_events e
  WHERE NOT EXISTS (SELECT 1 FROM retractions r
                    WHERE r.commit_id = e.commit_id);
"""


class StatusCoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_status_")
        self.rime_dir = os.path.join(self._tmp, "rime")
        self.facts_root = os.path.join(self._tmp, "facts")
        os.makedirs(os.path.join(self.rime_dir, "build"))
        self.sock_path = os.path.join(self._tmp, "missing.sock")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- fixtures -----------------------------------------------------------

    def write_default(self, schemas):
        with open(os.path.join(self.rime_dir, "default.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("config_version: \"0.1\"\n")
            f.write("schema_list:\n")
            for schema in schemas:
                f.write(f"  - schema: {schema}\n")

    def write_schema(self, schema_id, llm_rerank=None, engine=None):
        resolved = {"schema": {"schema_id": schema_id}}
        if engine is not None:
            resolved["engine"] = engine
        if llm_rerank is not None:
            resolved["llm_rerank"] = llm_rerank
        with open(os.path.join(self.rime_dir, "build",
                               f"{schema_id}.schema.yaml"), "w",
                  encoding="utf-8") as f:
            json.dump(resolved, f, ensure_ascii=False)

    def write_facts(self, active_events=2, retracted=0, epoch="epoch-1",
                    history="history-1", clock=(1000, 0),
                    marker=None):
        db_path = os.path.join(self.facts_root, "facts.sqlite3")
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o700)
        # A real fact root is initialized by FactStore, which establishes the
        # read/write maintenance lease before creating SQLite.
        lock_fd = os.open(os.path.join(self.facts_root, "maintenance.lock"),
                          os.O_WRONLY | os.O_CREAT, 0o600)
        os.fchmod(lock_fd, 0o600)
        os.close(lock_fd)
        conn = sqlite3.connect(db_path)
        conn.executescript(FACT_DDL)
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("fact_schema_version", "1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("event_format_version", "1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("history_id", history))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("store_epoch", epoch))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("hlc_physical_ms", str(clock[0])))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("hlc_logical", str(clock[1])))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("created_at_ms", "900"))
        for i in range(active_events):
            conn.execute(
                "INSERT INTO commits(commit_id, utc_committed_at_ms)"
                " VALUES(?, ?)", (f"commit-{i}", 1000 + i))
            text = marker if (marker and i == 0) else f"cand-{i}"
            conn.execute(
                "INSERT INTO selection_events(event_id, commit_id,"
                " event_format_version, schema_id, canonical_segment_input,"
                " span_start, span_end, category, preceding_text,"
                " competition_complete, final_selection_text,"
                " confirmation_source, trigger_keycode, display_rank,"
                " display_page, session_id, session_seq, hlc_physical_ms,"
                " hlc_logical, utc_confirmed_at_ms, utc_committed_at_ms)"
                " VALUES(?, ?, 1, 's', 'input', 0, 2, 'word', ?, 1, ?,"
                " 'explicit_current', 32, 1, 1, 'sess', 1, ?, 0, 990, ?)",
                (f"event-{i}", f"commit-{i}",
                 marker if (marker and i == 0) else f"prev-{i}",
                 text, clock[0], 1000 + i))
            conn.execute(
                "INSERT INTO selection_candidates(event_id, merge_order, text)"
                " VALUES(?, 0, ?)",
                (f"event-{i}", marker if (marker and i == 0) else f"cand-{i}"))
        for i in range(retracted):
            conn.execute(
                "INSERT INTO retractions(retraction_id, commit_id,"
                " hlc_physical_ms, hlc_logical, utc_retracted_at_ms)"
                " VALUES(?, ?, 2000, 0, 2000)",
                (f"retraction-{i}", f"commit-{i}"))
        conn.commit()
        conn.close()
        os.chmod(db_path, 0o600)

    def break_facts_root(self):
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o755)

    def start_fake_daemon(self, loaded=False, policy="mean-token-lm-v1"):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(1)

        def serve():
            conn, _ = srv.accept()
            data = b""
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            request = json.loads(data.decode("utf-8"))
            if request.get("kind") == "health":
                response = {
                    "version": 2,
                    "request_id": request.get("request_id"),
                    "kind": "health",
                    "health": {
                        "pid": 4242,
                        "model_loaded": loaded,
                        "scoring_strategy": "mean_token",
                        "policy_id": policy,
                        "context_window": 64,
                        "cache_limit_mb": 512,
                        "telemetry": False,
                    },
                }
            else:
                response = {"version": 2, "error": {"code": "invalid_request"}}
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            conn.close()
            srv.close()

        thread = threading.Thread(target=serve)
        thread.daemon = True
        thread.start()
        return thread

    # -- config resolution --------------------------------------------------

    def test_resolve_not_configured_keeps_phase1_defaults(self):
        resolved = resolve_switch_config(None)
        self.assertEqual("not_configured", resolved["source"])
        self.assertTrue(resolved["configured"]["reranking_enabled"])
        self.assertFalse(resolved["configured"]["recording_enabled"])
        self.assertFalse(resolved["configured"]["evidence_enabled"])
        self.assertFalse(resolved["deprecation_warning"])

    def test_resolve_legacy_enable(self):
        resolved = resolve_switch_config({"enable": True})
        self.assertEqual("legacy", resolved["source"])
        self.assertTrue(resolved["configured"]["reranking_enabled"])
        self.assertFalse(resolved["configured"]["recording_enabled"])
        self.assertFalse(resolved["configured"]["evidence_enabled"])

    def test_resolve_legacy_enable_false(self):
        resolved = resolve_switch_config({"enable": False})
        self.assertEqual("legacy", resolved["source"])
        self.assertFalse(resolved["configured"]["reranking_enabled"])

    def test_resolve_v2_canonical_true_true_false(self):
        resolved = resolve_switch_config({
            "reranking_enabled": True,
            "recording_enabled": True,
            "evidence_enabled": False,
        })
        self.assertEqual("v2", resolved["source"])
        self.assertEqual(
            {"reranking_enabled": True, "recording_enabled": True,
             "evidence_enabled": False},
            resolved["configured"])
        # explicit_keys records presence, not value: all three keys are
        # present even though evidence is explicitly false.
        self.assertEqual(
            {"reranking_enabled": True, "recording_enabled": True,
             "evidence_enabled": True},
            resolved["explicit_keys"])

    def test_resolve_v2_partial_missing_keys_default_false(self):
        resolved = resolve_switch_config({"recording_enabled": True})
        self.assertEqual("v2", resolved["source"])
        self.assertFalse(resolved["configured"]["reranking_enabled"])
        self.assertTrue(resolved["configured"]["recording_enabled"])
        self.assertFalse(resolved["configured"]["evidence_enabled"])

    def test_resolve_v2_all_false_is_explicit(self):
        resolved = resolve_switch_config({
            "reranking_enabled": False,
            "recording_enabled": False,
            "evidence_enabled": False,
        })
        self.assertEqual("v2", resolved["source"])
        self.assertTrue(resolved["explicit_keys"]["reranking_enabled"])
        self.assertTrue(resolved["explicit_keys"]["recording_enabled"])
        self.assertTrue(resolved["explicit_keys"]["evidence_enabled"])

    def test_resolve_coexist_v2_wins_and_warns(self):
        resolved = resolve_switch_config({"enable": False,
                                          "recording_enabled": True})
        self.assertEqual("v2", resolved["source"])
        self.assertTrue(resolved["deprecation_warning"])
        self.assertTrue(resolved["configured"]["recording_enabled"])

    def test_resolve_non_bool_key_counts_as_absent(self):
        resolved = resolve_switch_config({"reranking_enabled": "yes",
                                          "recording_enabled": True})
        self.assertEqual("v2", resolved["source"])
        self.assertFalse(resolved["explicit_keys"]["reranking_enabled"])
        self.assertFalse(resolved["configured"]["reranking_enabled"])

    # -- full report --------------------------------------------------------

    def canonical_schema(self):
        self.write_default(["alpha"])
        self.write_schema(
            "alpha",
            llm_rerank={"reranking_enabled": True, "recording_enabled": True,
                        "evidence_enabled": False},
            engine={"filters": ["uniquifier", "llm_rerank"],
                    "processors": ["llm_rerank_recorder"]})

    def report(self, **kwargs):
        defaults = dict(rime_dir=self.rime_dir, facts_root=self.facts_root,
                        daemon_socket=self.sock_path)
        defaults.update(kwargs)
        return collect_status(**defaults)

    def test_canonical_report_shape_and_healthy_exit(self):
        self.canonical_schema()
        self.write_facts(active_events=0)
        report = self.report()
        self.assertTrue(report["snapshot_ok"])
        self.assertEqual(1, report["status_version"])
        self.assertEqual(0, report["exit_code"])
        self.assertEqual(1, len(report["schemas"]))
        entry = report["schemas"][0]
        self.assertEqual("alpha", entry["schema_id"])
        config = entry["config"]
        self.assertEqual("v2", config["source"])
        self.assertIn("observed_at", config)
        self.assertTrue(config["runtime_effective"]["reranking"]["state"]
                        == "on")
        self.assertTrue(config["runtime_effective"]["recording"]["state"]
                        == "on")
        self.assertEqual("off", config["runtime_effective"]["evidence"]
                         ["state"])
        self.assertEqual("healthy", report["facts"]["health"])
        self.assertIn("observed_at", report["facts"])
        self.assertIn("observed_at", report["serving"])
        self.assertEqual("offline", report["serving"]["state"])
        self.assertIsNone(report["serving"]["model_loaded"])

    def test_v2_switch_combination_matrix(self):
        # All eight explicit combinations; alpha=0 so no daemon dependency.
        expected = {
            (True, True, True): ("on", "on", "on", 0),
            (True, True, False): ("on", "on", "off", 0),
            (True, False, True): ("on", "off", "on", 0),
            (True, False, False): ("on", "off", "off", 0),
            (False, True, True): ("off", "on", "suppressed", 0),
            (False, True, False): ("off", "on", "off", 0),
            (False, False, True): ("off", "off", "suppressed", 0),
            (False, False, False): ("off", "off", "off", 0),
        }
        for (rerank, record, evidence), (er, ec, ee, code) in expected.items():
            with self.subTest(rerank=rerank, record=record, evidence=evidence):
                self.write_default(["m"])
                self.write_schema("m", llm_rerank={
                    "reranking_enabled": rerank,
                    "recording_enabled": record,
                    "evidence_enabled": evidence,
                })
                report = self.report()
                duties = report["schemas"][0]["config"]["runtime_effective"]
                self.assertEqual(er, duties["reranking"]["state"])
                self.assertEqual(ec, duties["recording"]["state"])
                self.assertEqual(ee, duties["evidence"]["state"])
                self.assertEqual(code, report["exit_code"])

    def test_suppressed_evidence_reasons(self):
        self.write_default(["m"])
        self.write_schema("m", llm_rerank={
            "reranking_enabled": False,
            "evidence_enabled": True,
        })
        report = self.report()
        evidence = report["schemas"][0]["config"]["runtime_effective"][
            "evidence"]
        self.assertEqual("suppressed", evidence["state"])
        self.assertEqual("suppressed_by_reranking_disabled",
                         evidence["reason"])

        self.write_schema("m", llm_rerank={
            "reranking_enabled": True,
            "evidence_enabled": True,
            "gamma": 0,
        })
        report = self.report()
        evidence = report["schemas"][0]["config"]["runtime_effective"][
            "evidence"]
        self.assertEqual("suppressed", evidence["state"])
        self.assertEqual("suppressed_by_gamma_zero", evidence["reason"])

    def test_legacy_schema_report(self):
        self.write_default(["m"])
        self.write_schema("m", llm_rerank={"enable": True})
        report = self.report()
        entry = report["schemas"][0]
        self.assertEqual("legacy", entry["config"]["source"])
        self.assertTrue(entry["config"]["legacy_enable"])
        duties = entry["config"]["runtime_effective"]
        self.assertEqual("on", duties["reranking"]["state"])
        self.assertEqual("off", duties["recording"]["state"])
        self.assertEqual("off", duties["evidence"]["state"])
        self.assertEqual(0, report["exit_code"])

    def test_not_configured_schema_report(self):
        self.write_default(["m"])
        self.write_schema("m", llm_rerank=None,
                          engine={"filters": ["uniquifier", "llm_rerank"]})
        report = self.report()
        entry = report["schemas"][0]
        self.assertEqual("not_configured", entry["config"]["source"])
        duties = entry["config"]["runtime_effective"]
        self.assertEqual("on", duties["reranking"]["state"])
        self.assertEqual("off", duties["recording"]["state"])
        self.assertEqual(0, report["exit_code"])

    def test_v2_priority_over_legacy_enable_is_reported(self):
        self.write_default(["m"])
        self.write_schema("m", llm_rerank={"enable": False,
                                           "recording_enabled": True})
        report = self.report()
        entry = report["schemas"][0]
        self.assertEqual("v2", entry["config"]["source"])
        self.assertTrue(entry["config"]["deprecation_warning"])
        self.assertEqual("on", entry["config"]["runtime_effective"][
            "recording"]["state"])

    def test_multi_schema_status_is_isolated(self):
        self.write_default(["a", "b"])
        self.write_schema("a", llm_rerank={"reranking_enabled": True,
                                           "recording_enabled": True,
                                           "evidence_enabled": False})
        self.write_schema("b", llm_rerank={"enable": True})
        self.write_facts(active_events=1)
        report = self.report()
        by_id = {entry["schema_id"]: entry for entry in report["schemas"]}
        self.assertEqual({"a", "b"}, set(by_id))
        self.assertEqual("v2", by_id["a"]["config"]["source"])
        self.assertEqual("legacy", by_id["b"]["config"]["source"])
        self.assertEqual("on", by_id["a"]["config"]["runtime_effective"][
            "recording"]["state"])
        self.assertEqual("off", by_id["b"]["config"]["runtime_effective"][
            "recording"]["state"])
        # The shared facts section is identical for both schemas.
        self.assertEqual(report["facts"]["store_epoch"], "epoch-1")

    def test_schema_without_component_is_not_listed(self):
        self.write_default(["a", "b"])
        self.write_schema("a", llm_rerank={"recording_enabled": True})
        self.write_schema("b", llm_rerank=None,
                          engine={"filters": ["uniquifier"]})
        report = self.report()
        self.assertEqual(["a"], [entry["schema_id"]
                                 for entry in report["schemas"]])

    # -- facts --------------------------------------------------------------

    def test_facts_healthy_fields(self):
        self.canonical_schema()
        self.write_facts(active_events=3, retracted=1, epoch="epoch-9",
                         clock=(5000, 2))
        report = self.report()
        facts = report["facts"]
        self.assertEqual("healthy", facts["health"])
        self.assertEqual("epoch-9", facts["store_epoch"])
        self.assertEqual("history-1", facts["history_id"])
        self.assertEqual(1, facts["fact_schema_version"])
        self.assertEqual(2, facts["active_events"])
        self.assertEqual(1, facts["retracted_commits"])
        self.assertEqual(3, facts["total_events"])
        self.assertEqual({"hlc_physical_ms": 5000, "hlc_logical": 2},
                         facts["fact_high_water"])
        # Last write = max(commit time 1002, retraction time 2000).
        self.assertEqual(2000, facts["last_write_at_ms"])
        self.assertEqual({"state": "none"}, facts["recording_gaps"])
        self.assertEqual(0, report["exit_code"])

    def test_facts_not_created_is_zero_evidence_not_fault(self):
        self.canonical_schema()
        report = self.report()
        self.assertEqual("not_created", report["facts"]["health"])
        self.assertEqual("on", report["schemas"][0]["config"][
            "runtime_effective"]["recording"]["state"])
        self.assertEqual(0, report["exit_code"])

    def test_facts_root_permission_is_blocked_and_exit_one(self):
        self.canonical_schema()
        self.break_facts_root()
        report = self.report()
        self.assertEqual("blocked", report["facts"]["health"])
        self.assertEqual("root_permission", report["facts"]["fault_code"])
        self.assertEqual("blocked", report["schemas"][0]["config"][
            "runtime_effective"]["recording"]["state"])
        self.assertEqual(1, report["exit_code"])

    def test_facts_corrupt_is_blocked(self):
        self.canonical_schema()
        self.write_facts()
        # Overwrite a page so quick_check fails (trailing garbage is outside
        # the page graph and would not be detected).
        with open(os.path.join(self.facts_root, "facts.sqlite3"), "r+b") as f:
            f.seek(4096)
            f.write(b"X" * 4096)
        report = self.report()
        self.assertEqual("blocked", report["facts"]["health"])
        self.assertEqual("db_corrupt", report["facts"]["fault_code"])
        self.assertEqual(1, report["exit_code"])

    def test_facts_unsupported_version_is_blocked(self):
        self.canonical_schema()
        self.write_facts()
        conn = sqlite3.connect(os.path.join(self.facts_root, "facts.sqlite3"))
        conn.execute("UPDATE meta SET value = '99' WHERE key = "
                     "'fact_schema_version'")
        conn.commit()
        conn.close()
        report = self.report()
        self.assertEqual("blocked", report["facts"]["health"])
        self.assertEqual("db_unsupported_version",
                         report["facts"]["fault_code"])
        self.assertEqual(1, report["exit_code"])

    def test_facts_symlink_is_blocked(self):
        self.canonical_schema()
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o700)
        real = os.path.join(self.facts_root, "real.db")
        with open(real, "w"):
            pass
        os.symlink(real, os.path.join(self.facts_root, "facts.sqlite3"))
        report = self.report()
        self.assertEqual("blocked", report["facts"]["health"])
        self.assertEqual("db_symlink", report["facts"]["fault_code"])
        self.assertEqual(1, report["exit_code"])

    # -- serving ------------------------------------------------------------

    def test_daemon_offline_fields_semantics(self):
        # Offline daemon: everything provable from disk is still reported;
        # only the daemon's own fields become unknown/None. No model load, no
        # daemon start (the probe is a plain connect to a missing socket).
        self.canonical_schema()
        self.write_facts(active_events=1)
        report = self.report()
        self.assertEqual("offline", report["serving"]["state"])
        self.assertIsNone(report["serving"]["model_loaded"])
        self.assertIsNone(report["serving"]["policy_id"])
        # Facts still provable from disk.
        self.assertEqual("healthy", report["facts"]["health"])
        self.assertEqual(1, report["facts"]["active_events"])
        # Recording needs no daemon -> exit stays 0.
        self.assertEqual(0, report["exit_code"])

    def test_daemon_up_health_handshake(self):
        self.canonical_schema()
        self.write_facts()
        self.start_fake_daemon(loaded=True)
        report = self.report()
        self.assertEqual("up", report["serving"]["state"])
        self.assertTrue(report["serving"]["model_loaded"])
        self.assertEqual("mean-token-lm-v1", report["serving"]["policy_id"])
        self.assertEqual(4242, report["serving"]["daemon_pid"])
        self.assertEqual(0, report["exit_code"])

    def test_daemon_offline_with_daemon_dependency_is_exit_one(self):
        self.write_default(["m"])
        self.write_schema("m", llm_rerank={
            "reranking_enabled": True,
            "alpha": 1.0,
        })
        report = self.report()
        duties = report["schemas"][0]["config"]["runtime_effective"]
        self.assertEqual("degraded", duties["reranking"]["state"])
        self.assertEqual("daemon_offline", duties["reranking"]["reason"])
        self.assertEqual(1, report["exit_code"])

    def test_daemon_up_with_daemon_dependency_is_healthy(self):
        self.write_default(["m"])
        self.write_schema("m", llm_rerank={
            "reranking_enabled": True,
            "alpha": 1.0,
        })
        self.start_fake_daemon(loaded=False)
        report = self.report()
        duties = report["schemas"][0]["config"]["runtime_effective"]
        self.assertEqual("on", duties["reranking"]["state"])
        self.assertEqual(0, report["exit_code"])

    def test_daemon_reachable_but_invalid_handshake_is_unknown(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(1)

        def serve():
            conn, _ = srv.accept()
            conn.sendall(b"not json at all\n")
            conn.close()
            srv.close()

        thread = threading.Thread(target=serve)
        thread.daemon = True
        thread.start()
        self.write_default(["m"])
        self.write_schema("m", llm_rerank={
            "reranking_enabled": True,
            "alpha": 1.0,
        })
        report = self.report()
        thread.join(timeout=5)
        self.assertEqual("unknown", report["serving"]["state"])
        self.assertEqual("unknown", report["schemas"][0]["config"][
            "runtime_effective"]["reranking"]["state"])
        self.assertEqual(1, report["exit_code"])

    # -- privacy and exit codes ---------------------------------------------

    def test_output_never_contains_raw_text(self):
        marker_context = "PRIVATE_MARKER_上文_上下文"
        marker_candidate = "PRIVATE_MARKER_候选"
        marker_input = "PRIVATE_MARKER_输入"
        self.canonical_schema()
        self.write_facts(active_events=1, marker=marker_context)
        report = self.report()
        rendered = json.dumps(report, ensure_ascii=False)
        for marker in (marker_context, marker_candidate, marker_input,
                       "cand-0", "prev-0", "input"):
            self.assertNotIn(marker, rendered)
        self.assertNotIn(marker_context, render_human(report))

    def test_human_output_is_readable_and_clean(self):
        self.canonical_schema()
        self.write_facts(active_events=1)
        text = render_human(self.report())
        self.assertIn("alpha", text)
        self.assertIn("source=v2", text)
        self.assertIn("facts: healthy", text)
        self.assertIn("exit: 0", text)
        self.assertNotIn("cand", text)
        self.assertNotIn("prev", text)

    def test_snapshot_failure_is_exit_two(self):
        report = self.report(rime_dir=os.path.join(self._tmp, "missing"))
        self.assertFalse(report["snapshot_ok"])
        self.assertEqual(2, report["exit_code"])
        self.assertEqual("rime_dir_unavailable", report["error"]["code"])

    def test_compute_exit_code_passthrough(self):
        report = self.report(rime_dir=os.path.join(self._tmp, "missing"))
        self.assertEqual(2, compute_exit_code(report))
        report["snapshot_ok"] = True
        report["schemas"] = []
        self.assertEqual(0, compute_exit_code(report))
        report["schemas"] = [{"config": {"runtime_effective": {
            "reranking": {"state": "blocked", "reason": "db_corrupt"},
            "recording": {"state": "off", "reason": None},
            "evidence": {"state": "off", "reason": None},
        }}}]
        self.assertEqual(1, compute_exit_code(report))


if __name__ == "__main__":
    unittest.main()
