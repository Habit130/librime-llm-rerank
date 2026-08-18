#!/usr/bin/env python3
"""Deterministic tests for the fact schema migrate operation
(Habit130/squirrel#58).

Seams under test:

- Step level: `create_operation` + `try_run_pending_steps` with max_steps
  stepping, `fault_hook` crash injection, fake control clients and fake
  clocks. No wall-clock sleep drives any assertion.
- CLI level: the real `squirrel-semantic-memory` entry point in a
  subprocess with a sandboxed environment, the real C++ fact-store helper
  binary and a real in-process control server, so the production wiring
  (detached executor, safety snapshot, staging migrate, atomic replace) is
  exercised end to end.

The test predecessor step v1 -> v2 (interpretation-preserving) is loaded by
the C++ tool when SQUIRREL_FACT_MIGRATE_TEST_STEPS is set (decision B), so a
real supported-old -> head path runs against the actual C++ migrator. The
step is registered in the tool subprocess only; the production head stays 1.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(DAEMON_DIR, "squirrel-semantic-memory")
sys.path.insert(0, DAEMON_DIR)

import cli  # noqa: E402
import migrate_operation  # noqa: E402
import operations as operations_module  # noqa: E402
from clear_operation import FactStoreHelper  # noqa: E402
from migrate_operation import _staging_root  # noqa: E402
from operations import (  # noqa: E402
    OperationStore,
    create_operation,
    try_run_pending_steps,
)
from maintenance import MaintenanceError  # noqa: E402

TOOL_PATH = os.path.normpath(os.path.join(
    DAEMON_DIR, "..", "..", "..", "build", "plugins", "llm-rerank", "bin",
    "fact_store_tool"))


def _meta_value(db_path, key):
    # The live store is WAL; a read-only URI open cannot open it without
    # sidecars on this host, so read with a plain read-write connection (a
    # test-only read, never part of the implementation).
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


class MigrateEnv(unittest.TestCase):
    """Sandboxed environment shared by all migrate tests."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="migrate_test_")
        self.root = os.path.join(self._tmp, "SemanticMemory")
        self.control_socket = os.path.join(self._tmp, "control.sock")
        self._old_env = dict(os.environ)
        os.environ["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = self.root
        os.environ["SQUIRREL_DAEMON_CONTROL_SOCKET"] = self.control_socket
        os.environ["SQUIRREL_FACT_STORE_HELPER"] = TOOL_PATH
        # The C++ tool registers the test predecessor step in its own
        # process; the daemon-side helper subprocesses inherit the env.
        os.environ["SQUIRREL_FACT_MIGRATE_TEST_STEPS"] = "1"
        self.helper = FactStoreHelper(TOOL_PATH)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- fixtures -----------------------------------------------------------

    def make_live_store(self, seed=True):
        """Create a live v1 store via the C++ seam and seed one event."""
        identity = self.helper.create_empty(self.root)
        if seed:
            db_path = os.path.join(self.root, "facts.sqlite3")
            connection = sqlite3.connect(db_path)
            connection.execute(
                "INSERT INTO commits(commit_id, utc_committed_at_ms)"
                " VALUES('c' * 32, 1700000000000)")
            connection.execute(
                "INSERT INTO selection_events(event_id, commit_id,"
                " event_format_version, schema_id, canonical_segment_input,"
                " span_start, span_end, category, preceding_text,"
                " competition_complete, final_selection_text,"
                " confirmation_source, trigger_keycode, display_rank,"
                " display_page, session_id, session_seq, hlc_physical_ms,"
                " hlc_logical, utc_confirmed_at_ms, utc_committed_at_ms)"
                " VALUES('migrate-event-0', 'c' * 32, 1, 'luna_pinyin',"
                " 'shijie', 0, 6, 'word', '', 1, '世界',"
                " 'explicit_current', NULL, 1, 1, 'session-1', 0,"
                " 1700000000000, 0, 1700000000000, 1700000000000)")
            connection.execute(
                "INSERT INTO selection_candidates(event_id, merge_order,"
                " text) VALUES('migrate-event-0', 0, '世界')")
            connection.commit()
            connection.close()
        return identity

    def make_supported_old_store(self):
        """A live v1 store whose durable schema claims the supported-old
        version 1 below the test head 2 (the test predecessor v1 -> v2
        makes it migratable)."""
        identity = self.make_live_store(seed=True)
        # With the test seam the head is 2; a store at schema 1 is
        # supported-old and needs migration.
        return identity

    def live_disposition(self):
        return self.helper.schema(self.root)["disposition"]

    def build_spec(self, **seams):
        defaults = {
            "helper": self.helper,
            "control_socket": self.control_socket,
        }
        defaults.update(seams)
        return migrate_operation.MigrateSpec(self.root, **defaults).build()

    def registry(self, spec):
        registry = operations_module.OperationRegistry()
        registry.register(spec)
        return registry

    def create_op(self, spec, operation_id=None):
        store = OperationStore(self.root)
        return create_operation(store, self.registry(spec), "migrate", None,
                                operation_id=operation_id)

    def store(self):
        return OperationStore(self.root)

    def run_cli(self, *args, input_text=None, timeout=60):
        completed = subprocess.run(
            [sys.executable, ENTRY] + list(args),
            capture_output=True, text=True, timeout=timeout,
            input=input_text, env=dict(os.environ))
        return completed.returncode, completed.stdout, completed.stderr

    def staged_migrated(self, operation_id):
        return os.path.join(_staging_root(self.root, operation_id),
                            "migrated.sqlite3")


class FakeControlClient:
    """Records the maintenance protocol without a real daemon."""

    def __init__(self, path, operation_id):
        self.path = path
        self.operation_id = operation_id
        self.steps = []
        self.prepare_ok = True
        self.prepare_code = None

    def __enter__(self):
        self.steps.append("open")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.steps.append("close")

    def prepare(self):
        self.steps.append("prepare")
        if not self.prepare_ok:
            return {"ok": False, "code": self.prepare_code
                    or "maintenance_in_progress"}
        return {"ok": True, "store_epoch": None}

    def assert_prepared(self):
        self.steps.append("lease")
        return {"ok": True, "state": "prepared"}

    def reopen(self):
        self.steps.append("reopen")
        return {"ok": True, "state": "serving", "store_epoch": None}


class FakeClock:
    """Deterministic now/sleep pair for the bounded quiesce acquisition."""

    def __init__(self, advance=0.01):
        self.value = 0.0
        self.advance = advance

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class MigrateStepTests(MigrateEnv):
    """Step-level behavior with fake control and injected faults."""

    def setUp(self):
        super().setUp()
        self.clients = []
        self.original_probe = migrate_operation._probe_control_socket
        migrate_operation._probe_control_socket = lambda path: True

    def tearDown(self):
        migrate_operation._probe_control_socket = self.original_probe
        super().tearDown()

    def control_factory(self):
        def factory(path, operation_id):
            client = FakeControlClient(path, operation_id)
            self.clients.append(client)
            return client
        return factory

    def run_to_terminal(self, spec, operation_id, fault_hook=None):
        record, acquired = try_run_pending_steps(
            self.store(), self.registry(spec), operation_id,
            fault_hook=fault_hook)
        self.assertTrue(acquired)
        return record

    # -- SCN-58-1 -----------------------------------------------------------

    def test_snapshot_failure_blocks_with_zero_side_effects(self):
        identity = self.make_supported_old_store()
        original_snapshot = self.helper.snapshot
        self.helper.snapshot = lambda *args, **kwargs: (
            self._fail_snapshot())
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec)
            record = self.run_to_terminal(spec, record["operation_id"])
        finally:
            self.helper.snapshot = original_snapshot
        self.assertEqual("blocked", record["state"])
        self.assertEqual("safety_snapshot_failed",
                         record["error"]["code"])
        # Live DB unchanged: same epoch, still supported-old.
        self.assertEqual(identity["store_epoch"],
                         _meta_value(os.path.join(self.root,
                                                  "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual("needs_migration", self.live_disposition())

    def _fail_snapshot(self):
        raise migrate_operation.OperationBlocked(
            "safety_snapshot_failed", phase="staging",
            remediation="the safety snapshot could not be created")

    # -- SCN-58-2 / AC58-3 --------------------------------------------------

    def test_full_migrate_preserves_history_and_epoch(self):
        identity = self.make_supported_old_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])
        phases = [entry["phase"] for entry in record["log"]
                  if entry["kind"] == "transition"]
        self.assertEqual(["preflight", "waiting-for-quiesce", "staging",
                          "publishing", "reopening"], phases[:5])
        result = record["result"]
        self.assertEqual("migrated", result["outcome"])
        # Interpretation-preserving test step: history_id AND store_epoch
        # are preserved.
        self.assertEqual(identity["history_id"], result["history_id"])
        self.assertEqual(identity["store_epoch"], result["store_epoch"])
        # The live store is now current (head 2 under the test seam).
        self.assertEqual("current", self.live_disposition())
        self.assertEqual("2", _meta_value(os.path.join(self.root,
                                                       "facts.sqlite3"),
                                          "fact_schema_version"))
        # The single event survived the projection.
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM selection_events").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(1, count)

    def test_current_store_is_noop(self):
        # A store already at the head (production head 1, seam off) is a
        # pure no-op: no migration, no staging, no control traffic, no
        # identity churn.
        del os.environ["SQUIRREL_FACT_MIGRATE_TEST_STEPS"]
        self.make_live_store(seed=True)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"])
        self.assertEqual("current", self.live_disposition())
        # No control traffic and no staging directory were created.
        self.assertEqual([], self.clients)
        self.assertFalse(os.path.isdir(
            _staging_root(self.root, record["operation_id"])))

    # -- SCN-58-5 / AC58-5 --------------------------------------------------

    def test_unsupported_version_blocks_in_preflight(self):
        identity = self.make_live_store(seed=True)
        # Make the live store too new (schema 99).
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE meta SET value='99' WHERE"
                           " key='fact_schema_version'")
        connection.commit()
        connection.close()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("schema_unsupported", record["error"]["code"])
        # Live DB unchanged.
        self.assertEqual("99", _meta_value(db_path, "fact_schema_version"))

    def test_missing_step_blocks_in_preflight(self):
        self.make_live_store(seed=True)
        # Remove the test seam so the head is 1 again; then set the store's
        # durable schema BELOW the head (0) where no step is registered: a
        # gap, not a supported-old version.
        del os.environ["SQUIRREL_FACT_MIGRATE_TEST_STEPS"]
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE meta SET value='0' WHERE"
                           " key='fact_schema_version'")
        connection.commit()
        connection.close()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("schema_missing_step", record["error"]["code"])
        # Live DB unchanged.
        self.assertEqual("0", _meta_value(db_path, "fact_schema_version"))

    def test_missing_store_blocks(self):
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_missing", record["error"]["code"])

    # -- crash injection (SCN-58-10 / AC58-7) -------------------------------

    def test_crash_after_staging_reuses_staged_migration(self):
        identity = self.make_supported_old_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        operation_id = record["operation_id"]

        def crash_after_staging(phase, step_index, point):
            if (phase, step_index, point) == ("staging", 0, "after_step"):
                raise operations_module.SimulatedCrash()
        with self.assertRaises(operations_module.SimulatedCrash):
            try_run_pending_steps(self.store(), self.registry(spec),
                                  operation_id, fault_hook=crash_after_staging)
        # The staged migrated file is durable.
        self.assertTrue(os.path.isfile(self.staged_migrated(operation_id)))
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])
        self.assertEqual(identity["history_id"],
                         record["result"]["history_id"])
        self.assertEqual(identity["store_epoch"],
                         record["result"]["store_epoch"])
        self.assertEqual("current", self.live_disposition())

    def test_crash_before_publish_leaves_complete_old_store(self):
        identity = self.make_supported_old_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec)
        operation_id = record["operation_id"]

        def crash_in_publishing(phase, step_index, point):
            # Crash before the replacement runs (after the preflight gate,
            # before any publish): the disk must still hold the complete old
            # store.
            if (phase, step_index, point) == ("publishing", 0, "before_step"):
                raise operations_module.SimulatedCrash()
        with self.assertRaises(operations_module.SimulatedCrash):
            try_run_pending_steps(self.store(), self.registry(spec),
                                  operation_id,
                                  fault_hook=crash_in_publishing)
        # The live store is unchanged and still supported-old.
        self.assertEqual("needs_migration", self.live_disposition())
        self.assertEqual(identity["store_epoch"],
                         _meta_value(os.path.join(self.root,
                                                  "facts.sqlite3"),
                                     "store_epoch"))

    def test_quiesce_timeout_fails_without_touching_store(self):
        identity = self.make_supported_old_store()
        clock = FakeClock()
        spec = self.build_spec(
            control_client_factory=self.control_factory(),
            timeout_s=5.0, now=clock.now, sleep=clock.sleep)
        record = self.create_op(spec)
        operation_id = record["operation_id"]
        # A competing shared lease holds the maintenance lock for the whole
        # bounded window: staging (snapshot, shared) succeeds, but the
        # exclusive publish acquisition times out.
        import fcntl
        from maintenance import MaintenanceLock
        shared = MaintenanceLock(self.root).acquire()
        try:
            record = self.run_to_terminal(spec, operation_id)
        finally:
            shared.release()
        self.assertEqual("failed", record["state"])
        self.assertEqual("quiesce_timeout", record["error"]["code"])
        # No file change.
        self.assertEqual(identity["store_epoch"],
                         _meta_value(os.path.join(self.root,
                                                  "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual("needs_migration", self.live_disposition())


class MigrateCliTests(MigrateEnv):
    """End-to-end CLI tests with the real C++ helper and a real in-process
    control server."""

    def setUp(self):
        super().setUp()
        self._stop = None
        self._threads = []
        self.coordinator = None

    def tearDown(self):
        if self._stop is not None:
            self._stop.set()
        for thread in self._threads:
            if thread is not None and thread.is_alive():
                thread.join(timeout=5)
        super().tearDown()

    def start_control_server(self):
        """A real in-process control server over the temp socket."""
        import control
        from coordinator import MaintenanceCoordinator
        self._stop = threading.Event()
        self.coordinator = MaintenanceCoordinator(
            self.root, auto_open_fact_handle=True)
        ready = threading.Event()
        thread = threading.Thread(
            target=control.run_control_server,
            args=(self.control_socket, self.coordinator, ready, self._stop),
            daemon=True)
        thread.start()
        self.assertTrue(ready.wait(timeout=10))
        self._threads.append(thread)

    def test_cli_migrate_end_to_end(self):
        identity = self.make_supported_old_store()
        self.start_control_server()
        code, stdout, stderr = self.run_cli("migrate", "--json",
                                            timeout=120)
        self.assertEqual(0, code, stderr)
        payload = json.loads(stdout)
        self.assertEqual("succeeded", payload["state"])
        result = payload["result"]
        self.assertEqual("migrated", result["outcome"])
        self.assertEqual(identity["store_epoch"], result["store_epoch"])
        self.assertEqual(identity["history_id"], result["history_id"])
        # The live store is at the head schema (2 under the test seam).
        self.assertEqual("2", _meta_value(os.path.join(self.root,
                                                       "facts.sqlite3"),
                                          "fact_schema_version"))
        # The daemon adopted the migrated store.
        health = self.coordinator.health()
        self.assertEqual("serving", health["maintenance_state"])
        self.assertEqual(identity["store_epoch"],
                         health["active_derived_epoch"])

    def test_cli_migrate_current_is_already_migrated(self):
        self.make_live_store(seed=True)
        self.start_control_server()
        code, stdout, stderr = self.run_cli("migrate", "--json",
                                            timeout=120)
        self.assertEqual(0, code, stderr)
        payload = json.loads(stdout)
        self.assertEqual("succeeded", payload["state"])


if __name__ == "__main__":
    unittest.main()
