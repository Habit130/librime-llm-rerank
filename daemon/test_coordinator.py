#!/usr/bin/env python3
"""Tests for the daemon maintenance coordinator (Habit130/squirrel#53).

Proves the prepare_maintenance contract with injected fakes — active
requests, a builder and real fact handles — plus the reopen and lease-recovery
semantics. No MLX, no real model: the facts DBs are tiny sqlite fixtures in
temporary directories.
"""

import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from coordinator import (  # noqa: E402
    CoordinatorError,
    FactHandle,
    MaintenanceCoordinator,
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


def wait_until(predicate, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FakeBuilder:
    """Test double: records stop() calls so prepare can be proven to stop
    the builder."""

    def __init__(self):
        self.stopped = threading.Event()
        self.stop_count = 0

    def stop(self):
        self.stop_count += 1
        self.stopped.set()


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_coord_")
        self.facts_root = os.path.join(self._tmp, "facts")
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o700)
        self.coordinator = MaintenanceCoordinator(self.facts_root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_facts_store(self, epoch="epoch-1", clock=(1000, 0),
                          events=2):
        db_path = os.path.join(self.facts_root, "facts.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.executescript(FACT_DDL)
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("fact_schema_version", "1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("event_format_version", "1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("history_id", "history-1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("store_epoch", epoch))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("hlc_physical_ms", str(clock[0])))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("hlc_logical", str(clock[1])))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("created_at_ms", "900"))
        for i in range(events):
            conn.execute(
                "INSERT INTO commits(commit_id, utc_committed_at_ms)"
                " VALUES(?, ?)", (f"commit-{i}", 1000 + i))
            conn.execute(
                "INSERT INTO selection_events(event_id, commit_id,"
                " event_format_version, schema_id, canonical_segment_input,"
                " span_start, span_end, category, preceding_text,"
                " competition_complete, final_selection_text,"
                " confirmation_source, trigger_keycode, display_rank,"
                " display_page, session_id, session_seq, hlc_physical_ms,"
                " hlc_logical, utc_confirmed_at_ms, utc_committed_at_ms)"
                " VALUES(?, ?, 1, 's', 'input', 0, 2, 'word', 'prev', 1,"
                " 'cand', 'explicit_current', 32, 1, 1, 'sess', 1, 1000, 0,"
                " 990, 1000)",
                (f"event-{i}", f"commit-{i}"))
        conn.commit()
        conn.close()
        os.chmod(db_path, 0o600)

    # -- prepare_maintenance ------------------------------------------------

    def test_prepare_reports_real_zeroes_with_no_work(self):
        self.write_facts_store()
        result = self.coordinator.prepare_maintenance("op-1")
        self.assertEqual("prepared", result["state"])
        self.assertEqual("op-1", result["operation_id"])
        self.assertEqual(0, result["drained_requests"])
        self.assertEqual(0, result["open_handles"])
        self.assertFalse(result["builder_stopped"])
        self.assertIsNotNone(result["last_fact_hlc"])
        self.assertEqual("epoch-1",
                         result["last_fact_hlc"]["store_epoch"])
        self.assertEqual(1000,
                         result["last_fact_hlc"]["hlc_physical_ms"])
        self.assertTrue(self.coordinator.rejects_new_scoring())

    def test_prepare_drains_active_requests(self):
        self.write_facts_store()
        self.assertTrue(self.coordinator.begin_request("req-1"))
        self.assertTrue(self.coordinator.begin_request("req-2"))
        result_box = {}

        def prepare():
            result_box["result"] = self.coordinator.prepare_maintenance("op-1")

        thread = threading.Thread(target=prepare)
        thread.start()
        # Deterministic: prepare waits for the requests to drain; release
        # them once it is in the drain phase.
        self.assertTrue(wait_until(lambda: self.coordinator.state
                                   == "preparing"))
        self.assertTrue(self.coordinator.rejects_new_scoring())
        self.coordinator.end_request("req-1")
        self.coordinator.end_request("req-2")
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        result = result_box["result"]
        self.assertEqual(2, result["drained_requests"])
        self.assertEqual(0, self.coordinator.snapshot()["active_requests"])

    def test_prepare_rejects_new_requests_during_drain(self):
        self.write_facts_store()
        self.assertTrue(self.coordinator.begin_request("req-1"))

        def prepare():
            self.coordinator.prepare_maintenance("op-1")

        result_box = {}

        def prepare():
            result_box["result"] = self.coordinator.prepare_maintenance("op-1")

        thread = threading.Thread(target=prepare)
        thread.start()
        self.assertTrue(wait_until(lambda: self.coordinator.state
                                   == "preparing"))
        # New scoring requests are refused while preparing/prepared.
        self.assertFalse(self.coordinator.begin_request("late"))
        self.coordinator.end_request("req-1")
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        result = result_box["result"]
        self.assertEqual(1, result["rejected_requests"])

    def test_prepare_stops_builder_and_closes_handles(self):
        self.write_facts_store()
        builder = FakeBuilder()
        self.coordinator.register_builder(builder)
        handle = self.coordinator.open_fact_handle("handle-1")
        self.assertEqual(1, self.coordinator.handle_count())
        # The handle really holds the shared maintenance lock.
        import fcntl
        lock_path = os.path.join(self.facts_root, "maintenance.lock")
        probe_fd = os.open(lock_path, os.O_RDONLY)
        try:
            try:
                fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fail("shared lock not held by the open handle")
            except OSError:
                pass
        finally:
            os.close(probe_fd)

        result = self.coordinator.prepare_maintenance("op-1")
        self.assertTrue(result["builder_stopped"])
        self.assertTrue(builder.stopped.is_set())
        self.assertEqual(1, result["open_handles"])
        self.assertEqual(0, self.coordinator.handle_count())
        # The handle's connection was closed before the shared lock release.
        self.assertFalse(handle.open_connections)
        # After prepare the shared lock is free again (exclusive acquirable).
        probe_fd = os.open(lock_path, os.O_RDONLY)
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe_fd)

    def test_second_prepare_is_refused_while_prepared(self):
        self.write_facts_store()
        self.coordinator.prepare_maintenance("op-1")
        with self.assertRaises(CoordinatorError) as ctx:
            self.coordinator.prepare_maintenance("op-2")
        self.assertEqual("maintenance_in_progress", ctx.exception.code)

    # -- reopen -------------------------------------------------------------

    def test_reopen_requires_same_operation_id(self):
        self.write_facts_store()
        self.coordinator.prepare_maintenance("op-1")
        with self.assertRaises(CoordinatorError) as ctx:
            self.coordinator.reopen("op-other")
        self.assertEqual("operation_id_mismatch", ctx.exception.code)
        result = self.coordinator.reopen("op-1")
        self.assertEqual("serving", result["state"])
        self.assertEqual("epoch-1", result["store_epoch"])
        self.assertEqual("current", result["derived_state"])
        self.assertFalse(self.coordinator.rejects_new_scoring())

    def test_reopen_without_prepare_is_refused(self):
        with self.assertRaises(CoordinatorError) as ctx:
            self.coordinator.reopen("op-1")
        self.assertEqual("not_prepared", ctx.exception.code)

    def test_reopen_reads_new_epoch_and_marks_derived_rebuild(self):
        self.write_facts_store(epoch="epoch-1")
        self.coordinator.prepare_maintenance("op-1")
        # Maintenance replaced the store under the exclusive lock: new epoch.
        os.remove(os.path.join(self.facts_root, "facts.sqlite3"))
        self.write_facts_store(epoch="epoch-2")
        result = self.coordinator.reopen("op-1")
        self.assertEqual("epoch-2", result["store_epoch"])
        # The old epoch's derived state must never serve again: the honest
        # seam reports a rebuild is required.
        self.assertEqual("needs_rebuild", result["derived_state"])

    # -- lease drop / auto recovery ------------------------------------------

    def test_control_drop_auto_recovers_per_disk_epoch(self):
        self.write_facts_store(epoch="epoch-1")
        result = self.coordinator.prepare_maintenance("op-1")
        self.assertEqual("prepared", result["state"])
        recovery = self.coordinator.auto_recover()
        self.assertEqual("serving", recovery["state"])
        self.assertEqual("epoch-1", recovery["store_epoch"])
        self.assertEqual("op-1", recovery["recovered_from_operation"])
        self.assertFalse(self.coordinator.rejects_new_scoring())
        self.assertIsNone(self.coordinator.snapshot()["prepared_operation_id"])

    def test_auto_recover_is_noop_when_not_prepared(self):
        self.assertIsNone(self.coordinator.auto_recover())
        self.assertEqual("serving", self.coordinator.state)

    # -- fact handle seam ----------------------------------------------------

    def test_fact_handle_holds_shared_lock_and_releases_on_close(self):
        self.write_facts_store()
        handle = FactHandle("h1", self.facts_root)
        try:
            self.assertTrue(handle.open_connections)
        finally:
            handle.close()
        self.assertFalse(handle.open_connections)

    def test_scoring_gate_refuses_during_prepared(self):
        self.write_facts_store()
        self.assertTrue(self.coordinator.begin_request("r1"))
        result_box = {}

        def prepare():
            result_box["result"] = self.coordinator.prepare_maintenance("op-1")

        thread = threading.Thread(target=prepare)
        thread.start()
        self.assertTrue(wait_until(lambda: self.coordinator.state
                                   == "preparing"))
        # An already-registered request is drained; new ones are refused.
        self.assertFalse(self.coordinator.begin_request("r2"))
        self.coordinator.end_request("r1")
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(1, result_box["result"]["drained_requests"])
        self.coordinator.reopen("op-1")
        self.assertTrue(self.coordinator.begin_request("r3"))
        self.coordinator.end_request("r3")


if __name__ == "__main__":
    unittest.main()
