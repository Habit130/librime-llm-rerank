#!/usr/bin/env python3
"""Deterministic tests for the physical clear operation (Habit130/squirrel#54).

Seams under test:

- Step level: `create_operation` + `try_run_pending_steps` with max_steps
  stepping, `fault_hook` crash injection, fake control clients and fake
  clocks. No wall-clock sleep drives any assertion.
- CLI level: the real `squirrel-semantic-memory` entry point in a
  subprocess with a sandboxed environment, the real C++ fact-store helper
  binary and a real in-process control server, so the production wiring
  (confirmation protocol, detached executor, epoch CAS) is exercised end to
  end.

Test fixtures write fact rows directly with SQL only to simulate a store
populated by the plugin; the implementation under test never interprets
fact rows in Python (that is exactly what the C++ helper owns).
"""

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(DAEMON_DIR, "squirrel-semantic-memory")
sys.path.insert(0, DAEMON_DIR)

import cli  # noqa: E402
import clear_operation  # noqa: E402
import maintenance  # noqa: E402
import operations as operations_module  # noqa: E402
from clear_operation import (  # noqa: E402
    ClearSpec,
    FactStoreHelper,
    PUBLISHED_MARKER,
    IDENTITY_FILE,
    OLD_IDENTITY_FILE,
    _staging_root,
    _staging_store_dir,
)
from operations import (  # noqa: E402
    OperationStore,
    create_operation,
    run_pending_steps,
    try_run_pending_steps,
    cancel_operation,
)
from maintenance import MaintenanceError  # noqa: E402

TOOL_PATH = os.path.normpath(os.path.join(
    DAEMON_DIR, "..", "..", "..", "build", "plugins", "llm-rerank", "bin",
    "fact_store_tool"))

EVENT_IDS = ("seed-event-a", "seed-event-b")

# The rows below mirror the C++ fact schema only as fixture input; the clear
# implementation never reads or writes fact rows from Python.
_INSERT_COMMIT = ("INSERT INTO commits(commit_id, utc_committed_at_ms)"
                  " VALUES(?, ?);")
_INSERT_EVENT = (
    "INSERT INTO selection_events(event_id, commit_id, event_format_version,"
    " schema_id, canonical_segment_input, span_start, span_end, category,"
    " preceding_text, competition_complete, final_selection_text,"
    " confirmation_source, trigger_keycode, display_rank, display_page,"
    " session_id, session_seq, hlc_physical_ms, hlc_logical,"
    " utc_confirmed_at_ms, utc_committed_at_ms)"
    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);")
_INSERT_CANDIDATE = ("INSERT INTO selection_candidates(event_id, merge_order,"
                     " text) VALUES(?, ?, ?);")


def _write_schema_switches(rime_dir):
    """The three schema switches live outside the semantic root (rime_dir)."""
    build_dir = os.path.join(rime_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    path = os.path.join(build_dir, "luna_pinyin.schema.yaml")
    content = (
        "patch:\n"
        "  llm_rerank/reranking_enabled: true\n"
        "  llm_rerank/recording_enabled: true\n"
        "  llm_rerank/evidence_enabled: false\n")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(content)
    os.chmod(path, 0o644)
    return path, content


class ClearEnv(unittest.TestCase):
    """Sandboxed environment shared by all clear tests."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="clear_test_")
        self.root = os.path.join(self._tmp, "SemanticMemory")
        self.rime_dir = os.path.join(self._tmp, "Rime")
        os.makedirs(self.rime_dir, mode=0o700)
        self.scoring_socket = os.path.join(self._tmp, "scoring.sock")
        self.control_socket = os.path.join(self._tmp, "control.sock")
        self._old_env = dict(os.environ)
        os.environ["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = self.root
        os.environ["SQUIRREL_RIME_DIR"] = self.rime_dir
        os.environ["SQUIRREL_DAEMON_SOCKET"] = self.scoring_socket
        os.environ["SQUIRREL_DAEMON_CONTROL_SOCKET"] = self.control_socket
        os.environ["SQUIRREL_FACT_STORE_HELPER"] = TOOL_PATH
        self.helper = FactStoreHelper(TOOL_PATH)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- fixtures -----------------------------------------------------------

    def make_live_store(self, seed=True):
        """Create a live store at the root via the C++ seam.

        Returns (identity, empty) matching FactStoreHelper.verify; `empty`
        is False whenever the fixture seeded facts.
        """
        identity = self.helper.create_empty(self.root)
        if seed:
            self.seed_events(identity["store_epoch"])
        return identity, not seed

    def seed_events(self, store_epoch):
        """Simulate the plugin having recorded facts (fixture only).

        The meta clock is deliberately left untouched so the seeded store's
        durable identity stays exactly what the C++ seam reported.
        """
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        commit_id = "c" * 32
        connection.execute(_INSERT_COMMIT, (commit_id, 1700000000000))
        for index, event_id in enumerate(EVENT_IDS):
            connection.execute(_INSERT_EVENT, (
                event_id, commit_id, 1, "luna_pinyin", "shijie", 0, 6,
                "word", "", 1, "世界", "explicit_current", None, 1, 1,
                "session-1", index, 1700000000000 + index, index,
                1700000000000, 1700000000000))
            connection.execute(_INSERT_CANDIDATE, (event_id, 0, "世界"))
            connection.execute(_INSERT_CANDIDATE, (event_id, 1, "时界"))
        connection.commit()
        connection.close()
        return store_epoch

    def live_identity(self):
        return self.helper.verify(self.root)

    def build_spec(self, **seams):
        defaults = {
            "helper": self.helper,
            "control_socket": self.control_socket,
            "scoring_socket": self.scoring_socket,
        }
        defaults.update(seams)
        return ClearSpec(self.root, **defaults).build()

    def registry(self, spec):
        registry = operations_module.OperationRegistry()
        registry.register(spec)
        return registry

    def create_op(self, spec, epoch, operation_id=None):
        store = OperationStore(self.root)
        return create_operation(store, self.registry(spec), "clear",
                                {"expect_store_epoch": epoch},
                                operation_id=operation_id)

    def store(self):
        return OperationStore(self.root)

    def run_cli(self, *args, input_text=None, timeout=60):
        completed = subprocess.run(
            [sys.executable, ENTRY] + list(args),
            capture_output=True, text=True, timeout=timeout,
            input=input_text, env=dict(os.environ))
        return completed.returncode, completed.stdout, completed.stderr

    def spec_identity_file(self, operation_id):
        return os.path.join(_staging_root(self.root, operation_id),
                            IDENTITY_FILE)


class FakeControlClient:
    """Records the maintenance protocol without a real daemon."""

    def __init__(self, path, operation_id):
        self.path = path
        self.operation_id = operation_id
        self.steps = []
        self.prepare_ok = True
        self.prepare_code = None
        self.reopen_response = None

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
        if self.reopen_response is not None:
            return self.reopen_response
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


class ClearStepTests(ClearEnv):
    """Step-level behavior with fake control and injected faults."""

    def setUp(self):
        super().setUp()
        self.clients = []
        self.original_probe = clear_operation._probe_control_socket
        clear_operation._probe_control_socket = lambda path: True

    def tearDown(self):
        clear_operation._probe_control_socket = self.original_probe
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

    def run_stepwise(self, spec, operation_id, count):
        """Run exactly `count` steps, returning the final record."""
        record = None
        for _ in range(count):
            record, acquired = try_run_pending_steps(
                self.store(), self.registry(spec), operation_id, max_steps=1)
            self.assertTrue(acquired)
        return record

    # -- SCN-54-1 / SCN-54-3 ------------------------------------------------

    def test_full_clear_phase_progression_and_identity_reset(self):
        old_identity, old_empty = self.make_live_store()
        self.assertFalse(old_empty)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, old_identity["store_epoch"])
        operation_id = record["operation_id"]
        self.assertEqual("queued", record["state"])
        self.assertEqual("preflight", record["phase"])
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])
        phases = [entry["phase"] for entry in record["log"]
                  if entry["kind"] == "transition"]
        self.assertEqual(["preflight", "waiting-for-quiesce", "staging",
                          "publishing", "reopening", "cleanup"], phases[:6])
        result = record["result"]
        self.assertEqual("cleared", result["outcome"])
        self.assertTrue(result["cleanup_complete"])
        self.assertEqual(old_identity["store_epoch"],
                         result["old"]["store_epoch"])
        new_identity, empty = self.live_identity()
        self.assertTrue(empty)
        self.assertEqual(new_identity["store_epoch"],
                         result["new"]["store_epoch"])
        self.assertEqual(new_identity["history_id"],
                         result["new"]["history_id"])
        self.assertNotEqual(old_identity["store_epoch"],
                            new_identity["store_epoch"])
        self.assertNotEqual(old_identity["history_id"],
                            new_identity["history_id"])
        self.assertEqual(0, new_identity["hlc_logical"])
        # The control connection used the operation's own random id.
        self.assertEqual([operation_id], [c.operation_id for c in self.clients
                                          if c.steps])
        steps = [step for client in self.clients for step in client.steps]
        self.assertEqual(["open", "prepare", "lease", "lease", "lease",
                          "reopen", "close"], steps)
        # No staging residue; the published main database is a complete
        # store (sidecars may reappear when a reader opens WAL, which is the
        # normal operating state).
        self.assertFalse(os.path.lexists(
            _staging_root(self.root, operation_id)))

    def test_stale_epoch_cas_blocks_with_zero_side_effects(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, "f" * 32)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("preflight", record["phase"])
        self.assertEqual("store_epoch_mismatch", record["error"]["code"])
        # Zero side effects: no staging, no publish, no control traffic, and
        # the store is still the same populated one.
        self.assertFalse(os.path.lexists(
            _staging_root(self.root, record["operation_id"])))
        self.assertEqual([], self.clients)
        live, empty = self.live_identity()
        self.assertEqual(identity, live)
        self.assertFalse(empty)

    def test_pristine_with_expected_epoch_blocks(self):
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, "f" * 32)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_epoch_mismatch", record["error"]["code"])

    def test_epoch_reverified_under_exclusive_lease(self):
        # The epoch changed between staging and the exclusive lease: the
        # publishing step must refuse before replacing anything.
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]
        # Three steps execute preflight, waiting-for-quiesce and staging;
        # the record now sits at publishing with the lease-taking step not
        # yet run.
        record = self.run_stepwise(spec, operation_id, 3)
        self.assertEqual("publishing", record["phase"])
        # Simulate a concurrent store replacement under the lease.
        original = clear_operation.read_identity_under_exclusive
        clear_operation.read_identity_under_exclusive = \
            lambda root: {"store_epoch": "e" * 32, "history_id": "h" * 32,
                          "hlc_physical_ms": 1, "hlc_logical": 0}
        try:
            record = self.run_to_terminal(spec, operation_id)
        finally:
            clear_operation.read_identity_under_exclusive = original
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_epoch_mismatch", record["error"]["code"])
        # Nothing published: the populated store is untouched.
        live, empty = self.live_identity()
        self.assertEqual(identity, live)
        self.assertFalse(empty)

    def test_production_registry_loads_clear(self):
        registry = clear_operation.production_registry(
            self.root, helper=self.helper, control_socket=self.control_socket,
            scoring_socket=self.scoring_socket)
        self.assertIsNotNone(registry.get("clear"))

    # -- SCN-54-7 / SCN-54-8 ------------------------------------------------

    def test_crash_after_staging_reuses_staged_identity(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]

        def crash_after_staging(phase, step_index, point):
            if (phase, step_index, point) == ("staging", 0, "after_step"):
                raise operations_module.SimulatedCrash()
        with self.assertRaises(operations_module.SimulatedCrash):
            try_run_pending_steps(self.store(), self.registry(spec),
                                  operation_id, fault_hook=crash_after_staging)
        staged = self.spec_identity_file(operation_id)
        self.assertTrue(os.path.exists(staged))
        with open(staged, "r", encoding="utf-8") as stream:
            first_identity = json.load(stream)
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])
        self.assertEqual(first_identity["store_epoch"],
                         record["result"]["new"]["store_epoch"])
        self.assertEqual(first_identity["history_id"],
                         record["result"]["new"]["history_id"])
        live, _empty = self.live_identity()
        self.assertEqual(first_identity["store_epoch"], live["store_epoch"])

    def test_crash_after_publish_does_not_republish_or_regenerate(self):
        identity, _empty = self.make_live_store()
        publishes = []
        original_replace = clear_operation.replace_fact_database
        clear_operation.replace_fact_database = (
            lambda root, path, lease: (publishes.append(1),
                                       original_replace(root, path, lease))[1])
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, identity["store_epoch"])
            operation_id = record["operation_id"]

            def crash_after_publish(phase, step_index, point):
                if (phase, step_index, point) == ("publishing", 0,
                                                  "after_step"):
                    raise operations_module.SimulatedCrash()
            with self.assertRaises(operations_module.SimulatedCrash):
                try_run_pending_steps(self.store(), self.registry(spec),
                                      operation_id,
                                      fault_hook=crash_after_publish)
            self.assertEqual(1, len(publishes))
            staged = self.spec_identity_file(operation_id)
            with open(staged, "r", encoding="utf-8") as stream:
                first_identity = json.load(stream)
            record = self.run_to_terminal(spec, operation_id)
            self.assertEqual("succeeded", record["state"])
            # The retry recognized the published store: no second publish,
            # no regenerated identity, no restored old epoch.
            self.assertEqual(1, len(publishes))
            self.assertEqual(first_identity["store_epoch"],
                             record["result"]["new"]["store_epoch"])
            live, empty = self.live_identity()
            self.assertTrue(empty)
            self.assertEqual(first_identity["store_epoch"],
                             live["store_epoch"])
        finally:
            clear_operation.replace_fact_database = original_replace

    def test_crash_between_replace_and_marker_recovers(self):
        identity, _empty = self.make_live_store()
        original_write = clear_operation._write_json_atomic
        marker_writes = []

        def crashing_write(path, payload, euid):
            if (os.path.basename(path) == clear_operation.PUBLISHED_MARKER
                    and not marker_writes):
                marker_writes.append(1)
                raise operations_module.SimulatedCrash()
            return original_write(path, payload, euid)
        clear_operation._write_json_atomic = crashing_write
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, identity["store_epoch"])
            operation_id = record["operation_id"]
            with self.assertRaises(operations_module.SimulatedCrash):
                try_run_pending_steps(self.store(), self.registry(spec),
                                      operation_id)
            # The atomic replace happened, the marker write "crashed": the
            # disk already carries the staged identity. The retry must
            # recognize it, finish the marker and never replace again.
            staged = self.spec_identity_file(operation_id)
            with open(staged, "r", encoding="utf-8") as stream:
                first_identity = json.load(stream)
            live, empty = self.live_identity()
            self.assertTrue(empty)
            self.assertEqual(first_identity["store_epoch"],
                             live["store_epoch"])
            record = self.run_to_terminal(spec, operation_id)
            self.assertEqual("succeeded", record["state"])
            self.assertEqual(first_identity["store_epoch"],
                             record["result"]["new"]["store_epoch"])
            self.assertEqual(1, len(marker_writes))
        finally:
            clear_operation._write_json_atomic = original_write

    def test_crash_before_rename_leaves_complete_old_store(self):
        identity, _empty = self.make_live_store()
        original_replace = clear_operation.replace_fact_database
        crashed = []

        def crashing_replace(root, path, lease):
            def crash():
                if crashed:
                    return
                crashed.append(1)
                raise operations_module.SimulatedCrash()
            original_replace(root, path, lease, _after_checkpoint=crash)
        clear_operation.replace_fact_database = crashing_replace
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, identity["store_epoch"])
            operation_id = record["operation_id"]
            with self.assertRaises(operations_module.SimulatedCrash):
                try_run_pending_steps(self.store(), self.registry(spec),
                                      operation_id)
            # The crash point is before the rename: the complete old store
            # is still observable, and the staged identity is durable for
            # the retry.
            staged = self.spec_identity_file(operation_id)
            with open(staged, "r", encoding="utf-8") as stream:
                first_identity = json.load(stream)
            live, _empty = self.live_identity()
            self.assertEqual(identity["store_epoch"], live["store_epoch"])
            record = self.run_to_terminal(spec, operation_id)
            self.assertEqual("succeeded", record["state"])
            # The retry published the SAME staged identity (no regeneration).
            self.assertEqual(first_identity["store_epoch"],
                             record["result"]["new"]["store_epoch"])
        finally:
            clear_operation.replace_fact_database = original_replace

    def test_crash_mid_cleanup_retries_idempotently(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]

        def crash_in_cleanup(phase, step_index, point):
            if (phase, step_index, point) == ("cleanup", 0, "after_step"):
                raise operations_module.SimulatedCrash()
        with self.assertRaises(operations_module.SimulatedCrash):
            try_run_pending_steps(self.store(), self.registry(spec),
                                  operation_id, fault_hook=crash_in_cleanup)
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])
        self.assertTrue(record["result"]["cleanup_complete"])

    def test_terminal_retry_returns_the_same_result(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]
        first = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", first["state"])
        second = self.run_to_terminal(spec, operation_id)
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(first["rev"], second["rev"])

    def test_same_operation_id_different_parameters_conflicts(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"],
                                operation_id="op-clear-1")
        with self.assertRaises(operations_module.OperationIdConflict):
            self.create_op(spec, "a" * 32, operation_id="op-clear-1")

    def test_same_operation_id_same_parameters_idempotent(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        first = self.create_op(spec, identity["store_epoch"],
                               operation_id="op-clear-2")
        again = self.create_op(spec, identity["store_epoch"],
                               operation_id="op-clear-2")
        self.assertEqual(first["rev"], again["rev"])

    # -- SCN-54-9 -----------------------------------------------------------

    def test_already_clear_pristine(self):
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, "")
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"])
        self.assertEqual("already_clear", record["result"]["outcome"])
        self.assertTrue(record["result"]["cleanup_complete"])
        self.assertIsNone(record["result"]["old"])
        self.assertIsNone(record["result"]["new"])
        # No store was created, no control traffic happened.
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "facts.sqlite3")))
        self.assertEqual([], self.clients)

    def test_already_clear_empty_store_keeps_identity(self):
        identity = self.helper.create_empty(self.root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"])
        self.assertEqual("already_clear", record["result"]["outcome"])
        live, empty = self.live_identity()
        self.assertTrue(empty)
        self.assertEqual(identity["store_epoch"], live["store_epoch"])
        self.assertEqual(identity["history_id"], live["history_id"])
        self.assertEqual(identity["store_epoch"],
                         record["result"]["new"]["store_epoch"])
        self.assertEqual([], self.clients)

    def test_empty_store_with_derived_leftovers_publishes_once(self):
        identity = self.helper.create_empty(self.root)
        # A present gap from the old history counts as app-controlled data
        # pending cleanup: the clear must publish a new empty store exactly
        # once and remove the gap.
        gap = {
            "gap_version": 2, "state": "present",
            "reason": "buffer_overflow_batches",
            "store_epoch": identity["store_epoch"],
            "dropped_batches": 1, "dropped_events": 1,
            "dropped_retractions": 0, "dropped_bytes": 0,
            "updated_at_ms": 1700000000000,
        }
        with open(os.path.join(self.root, "recording_gap.json"), "w",
                  encoding="utf-8") as stream:
            json.dump(gap, stream)
        os.chmod(os.path.join(self.root, "recording_gap.json"), 0o600)
        with open(os.path.join(self.root, "recording_gap.lock"), "wb") as s:
            s.write(b"present\n")
        os.chmod(os.path.join(self.root, "recording_gap.lock"), 0o600)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"])
        self.assertEqual("cleared", record["result"]["outcome"])
        live, empty = self.live_identity()
        self.assertTrue(empty)
        self.assertNotEqual(identity["store_epoch"], live["store_epoch"])
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "recording_gap.json")))
        # A second clear of the now-empty system reports already_clear and
        # keeps the identity.
        spec2 = self.build_spec(control_client_factory=self.control_factory())
        record2 = self.create_op(spec2, live["store_epoch"])
        record2 = self.run_to_terminal(spec2, record2["operation_id"])
        self.assertEqual("already_clear", record2["result"]["outcome"])
        live2, _empty = self.live_identity()
        self.assertEqual(live["store_epoch"], live2["store_epoch"])

    # -- SCN-54-10 ----------------------------------------------------------

    def test_cancel_before_publish_reopens_old_state(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]
        record = self.run_stepwise(spec, operation_id, 2)
        self.assertEqual("staging", record["phase"])
        record, disposition = cancel_operation(self.store(), operation_id)
        self.assertEqual("requested", disposition)
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("cancelled", record["state"])
        # Compensation: the old populated store is untouched and the staging
        # directory is removed. The daemon was never prepared, so there is
        # nothing to reopen (no control traffic at all).
        live, empty = self.live_identity()
        self.assertEqual(identity, live)
        self.assertFalse(empty)
        self.assertFalse(os.path.lexists(
            _staging_root(self.root, operation_id)))
        self.assertEqual([], [step for client in self.clients
                              for step in client.steps])

    def test_cancel_after_publish_is_uncancellable(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]
        # Step into the irreversible phase before its lease-taking step has
        # run: the persisted phase alone decides uncancellability.
        record = self.run_stepwise(spec, operation_id, 3)
        self.assertEqual("publishing", record["phase"])
        record, disposition = cancel_operation(self.store(), operation_id)
        self.assertEqual("uncancellable", disposition)
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])

    def test_quiesce_timeout_fails_without_touching_targets(self):
        identity, _empty = self.make_live_store()
        clock = FakeClock()
        spec = self.build_spec(control_client_factory=self.control_factory(),
                               now=clock.now, sleep=clock.sleep)
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]
        # A competing shared lease holds the maintenance lock for the whole
        # bounded window.
        shared = maintenance.MaintenanceLock(self.root).acquire()
        try:
            record = self.run_to_terminal(spec, operation_id)
        finally:
            shared.release()
        self.assertEqual("failed", record["state"])
        self.assertEqual("quiesce_timeout", record["error"]["code"])
        self.assertGreaterEqual(clock.value, 5.0)
        # Nothing changed: facts, identity, derived state and configuration
        # are exactly as before (the staging artifact stays recoverable and
        # is removed by the next successful clear).
        live, empty = self.live_identity()
        self.assertEqual(identity, live)
        self.assertFalse(empty)
        self.assertFalse(os.path.exists(
            os.path.join(_staging_root(self.root, operation_id),
                         PUBLISHED_MARKER)))

    def test_daemon_unreachable_fails_before_staging(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        operation_id = record["operation_id"]
        record = self.run_stepwise(spec, operation_id, 1)
        self.assertEqual("waiting-for-quiesce", record["phase"])
        clear_operation._probe_control_socket = lambda path: False
        try:
            record = self.run_to_terminal(spec, operation_id)
        finally:
            clear_operation._probe_control_socket = lambda path: True
        self.assertEqual("failed", record["state"])
        self.assertEqual("daemon_unavailable", record["error"]["code"])
        # No staging work was performed.
        self.assertFalse(os.path.lexists(
            _staging_root(self.root, operation_id)))

    # -- SCN-54-6 / SCN-54-11 / SCN-54-12 -----------------------------------

    def test_cleanup_allowlist_removes_only_application_owned_paths(self):
        identity, _empty = self.make_live_store()
        # Derived/quarantine/snapshot fixtures owned by the app.
        for name in ("generations", "staging", "quarantine"):
            os.makedirs(os.path.join(self.root, name), mode=0o700)
            with open(os.path.join(self.root, name, "data.bin"), "wb") as s:
                s.write(b"derived" * 100)
        for name in ("delta.sqlite3", "delta.sqlite3-wal",
                     "active_manifest.json", ".snapshot-42"):
            with open(os.path.join(self.root, name), "wb") as s:
                s.write(b"derived" * 50)
        # An old terminal operation with its lock and temp files.
        ops_dir = os.path.join(self.root, "operations")
        os.makedirs(ops_dir, mode=0o700)
        old_record = {
            "operation_version": 1, "operation_id": "old-op-1",
            "type": "clear", "state": "succeeded", "phase": "cleanup",
            "phases": ["cleanup"], "irreversible_phase": "cleanup",
            "cancel_phase": None,
            "parameters": {"expect_store_epoch": "z" * 32},
            "parameters_fingerprint": "f" * 64,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "cancel_requested": False, "cancel_requested_at": None,
            "progress": {"events": 0, "bytes": 0, "chunks": 0},
            "result": None, "error": None, "log": [], "rev": 1,
            "runner_claim": None,
        }
        with open(os.path.join(ops_dir, "old-op-1.json"), "w",
                  encoding="utf-8") as stream:
            json.dump(old_record, stream)
        os.chmod(os.path.join(ops_dir, "old-op-1.json"), 0o600)
        for extra in ("old-op-1.lock", "old-op-1.tmp-1-x"):
            with open(os.path.join(ops_dir, extra), "wb") as s:
                s.write(b"lock")
        with open(os.path.join(self.root, ".operation-old-op-1.run"),
                  "wb") as s:
            s.write(b"run")
        # A user-owned file inside the root that is NOT app-owned.
        user_file = os.path.join(self.root, "user-notes.txt")
        with open(user_file, "w", encoding="utf-8") as stream:
            stream.write("private user notes")
        # Configuration sentinels and an external backup outside the root.
        schema_path, schema_content = _write_schema_switches(self.rime_dir)
        backup_path = os.path.join(self._tmp, "external-backup.bin")
        with open(backup_path, "wb") as stream:
            stream.write(b"external backup bytes" * 10)
        with open(backup_path, "rb") as stream:
            backup_bytes = stream.read()

        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"])
        self.assertTrue(record["result"]["cleanup_complete"])

        for name in ("generations", "staging", "quarantine", "delta.sqlite3",
                     "delta.sqlite3-wal", "active_manifest.json",
                     ".snapshot-42", ".clear"):
            self.assertFalse(os.path.lexists(os.path.join(self.root, name)),
                             name)
        for extra in ("old-op-1.json", "old-op-1.lock", "old-op-1.tmp-1-x"):
            self.assertFalse(os.path.exists(os.path.join(ops_dir, extra)))
        self.assertFalse(os.path.exists(
            os.path.join(self.root, ".operation-old-op-1.run")))
        # Kept: the current operation's idempotency record, its lock and run
        # lock, the maintenance lock, the current fact store, and files the
        # application does not own.
        operation_id = record["operation_id"]
        self.assertTrue(os.path.exists(
            os.path.join(ops_dir, "%s.json" % operation_id)))
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "maintenance.lock")))
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "facts.sqlite3")))
        with open(user_file, "r", encoding="utf-8") as stream:
            self.assertEqual("private user notes", stream.read())
        # Byte-for-byte unchanged: schema switches and the external backup.
        with open(schema_path, "r", encoding="utf-8") as stream:
            self.assertEqual(schema_content, stream.read())
        with open(backup_path, "rb") as stream:
            self.assertEqual(backup_bytes, stream.read())
        # The current record holds no private text: only the epoch UUID is
        # in the parameters.
        current = self.store().load(operation_id)
        self.assertEqual({"expect_store_epoch": identity["store_epoch"]},
                         current["parameters"])
        for word in ("世界", "时界", "shijie", "private"):
            self.assertNotIn(word, json.dumps(current["result"]))

    def test_cleanup_leaves_blocked_operations_and_live_markers(self):
        # A blocked operation awaiting an explicit retry is kept; a live
        # recorder marker is never deleted (SCN-54-6 keep list).
        identity = self.helper.create_empty(self.root)
        marker = os.path.join(self.root, ".recording_process.test")
        with open(marker, "wb") as stream:
            stream.write(b"clean\n")
        os.chmod(marker, 0o600)
        import fcntl
        live_fd = os.open(marker, os.O_RDWR)
        fcntl.flock(live_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            ops_dir = os.path.join(self.root, "operations")
            os.makedirs(ops_dir, mode=0o700)
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, identity["store_epoch"])
            operation_id = record["operation_id"]
            record = self.run_to_terminal(spec, operation_id)
            self.assertEqual("already_clear", record["result"]["outcome"])
            self.assertTrue(os.path.exists(marker))
        finally:
            os.close(live_fd)

    def test_symlinked_derived_dir_is_unlinked_not_followed(self):
        identity, _empty = self.make_live_store()
        outside = os.path.join(self._tmp, "outside-dir")
        os.makedirs(outside, mode=0o700)
        with open(os.path.join(outside, "precious.bin"), "wb") as stream:
            stream.write(b"precious")
        os.symlink(outside, os.path.join(self.root, "generations"))
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"])
        # The symlink itself is gone, its target is untouched.
        self.assertFalse(os.path.lexists(
            os.path.join(self.root, "generations")))
        self.assertTrue(os.path.exists(
            os.path.join(outside, "precious.bin")))

    # -- SCN-54-13 ----------------------------------------------------------

    def test_root_symlink_fails_closed(self):
        target = os.path.join(self._tmp, "elsewhere")
        os.makedirs(target, mode=0o700)
        os.symlink(target, self.root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        with self.assertRaises(operations_module.StoreBlocked):
            self.create_op(spec, "")

    def test_elevated_privilege_refused(self):
        store = OperationStore(self.root, euid=0)
        with self.assertRaises(operations_module.UnsupportedPrivilege):
            store.open(create=False)

    def test_result_carries_media_residue_disclaimer(self):
        identity, _empty = self.make_live_store()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, identity["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertTrue(record["result"]["application_level_deletion"])
        for fragment in ("APFS snapshots", "wear-leveling",
                         "system backups", "copied elsewhere"):
            self.assertIn(fragment,
                          record["result"]["media_residue_disclaimer"])


class ClearCliTests(ClearEnv):
    """Production CLI wiring: confirmation protocol, exit codes, executor."""

    def setUp(self):
        super().setUp()
        self._stop = None
        self._threads = []

    def tearDown(self):
        for thread in self._threads:
            if thread is not None and thread.is_alive():
                self._stop.set()
        for thread in self._threads:
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

    def read_stdout_docs(self, output):
        """--json prints a started envelope then the final record."""
        lines = [line for line in output.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 1)
        docs = []
        buffer = []
        for line in lines:
            buffer.append(line)
            try:
                docs.append(json.loads("\n".join(buffer)))
                buffer = []
            except ValueError:
                continue
        self.assertFalse(buffer)
        return docs

    # -- SCN-54-1 -----------------------------------------------------------

    def test_noninteractive_clear_end_to_end(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        rc, out, err = self.run_cli(
            "clear", "--yes", "--expect-store-epoch",
            identity["store_epoch"], "--json")
        self.assertEqual(0, rc, out + err)
        docs = self.read_stdout_docs(out)
        self.assertEqual(2, len(docs))
        envelope, final = docs
        self.assertEqual("running", envelope["state"])
        operation_id = envelope["operation_id"]
        self.assertEqual("succeeded", final["state"])
        self.assertEqual("cleared", final["result"]["outcome"])
        self.assertTrue(final["result"]["cleanup_complete"])
        self.assertEqual(identity["store_epoch"],
                         final["result"]["old"]["store_epoch"])
        live, empty = self.live_identity()
        self.assertTrue(empty)
        self.assertEqual(live["store_epoch"],
                         final["result"]["new"]["store_epoch"])
        self.assertNotEqual(identity["store_epoch"], live["store_epoch"])
        self.assertNotEqual(identity["history_id"], live["history_id"])
        # The daemon adopted the new epoch (real reopen).
        health = self.coordinator.health()
        self.assertEqual("serving", health["maintenance_state"])
        self.assertEqual(live["store_epoch"],
                         health["active_derived_epoch"])

    def test_human_output_reports_deletion_scope(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        rc, out, _ = self.run_cli(
            "clear", "--yes", "--expect-store-epoch",
            identity["store_epoch"])
        self.assertEqual(0, rc, out)
        self.assertIn("cleared", out)
        self.assertIn("cleanup_complete: True", out)
        self.assertIn("application-level deletion", out)
        self.assertIn("APFS snapshots", out)
        self.assertIn("new history:", out)

    def test_interactive_exact_confirmation_succeeds(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        confirmation = "CLEAR %s AT %s\n" % (identity["history_id"],
                                             identity["store_epoch"])
        rc, out, _ = self.run_cli("clear", input_text=confirmation)
        self.assertEqual(0, rc, out)
        self.assertIn("cleared", out)

    def test_interactive_mismatch_cancels_with_zero_side_effects(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        variants = [
            "",                                      # EOF / empty input
            "CLEAR WRONG AT WRONG\n",
            "clear %s at %s\n" % (identity["history_id"],
                                  identity["store_epoch"]),   # case change
            "CLEAR %s AT %s extra\n" % (identity["history_id"],
                                        identity["store_epoch"]),
            "CLEAR %s AT %s\n" % (identity["history_id"], "f" * 32),
        ]
        for entered in variants:
            with self.subTest(entered=entered):
                rc, out, err = self.run_cli("clear", input_text=entered)
                self.assertEqual(1, rc)
                self.assertIn("confirmation_failed", out + err)
        # Zero side effects: no operation records, no staging, the
        # populated store is untouched.
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "operations")))
        self.assertFalse(os.path.lexists(
            os.path.join(self.root, ".clear")))
        live, empty = self.live_identity()
        self.assertEqual(identity["history_id"], live["history_id"])
        self.assertFalse(empty)

    def test_noninteractive_requires_both_confirmation_and_epoch(self):
        identity, _ = self.make_live_store()
        rc, out, err = self.run_cli("clear", "--yes")
        self.assertEqual(2, rc)
        self.assertIn("confirmation_required", out + err)
        rc, out, err = self.run_cli(
            "clear", "--expect-store-epoch", identity["store_epoch"])
        self.assertEqual(2, rc)
        self.assertIn("confirmation_required", out + err)

    def test_no_force_flag_exists(self):
        self.make_live_store()
        rc, _, err = self.run_cli("clear", "--force", "--yes",
                                  "--expect-store-epoch", "f" * 32)
        self.assertEqual(2, rc)
        self.assertIn("unrecognized arguments", err)

    def test_stale_epoch_noninteractive_is_zero_side_effect(self):
        identity, _ = self.make_live_store()
        rc, out, _ = self.run_cli(
            "clear", "--yes", "--expect-store-epoch", "f" * 32, "--json")
        self.assertEqual(2, rc)
        error = json.loads(out)
        self.assertEqual("store_epoch_mismatch", error["code"])
        live, empty = self.live_identity()
        self.assertEqual(identity["store_epoch"], live["store_epoch"])
        self.assertFalse(empty)

    def test_pristine_interactive_reports_already_clear(self):
        self.start_control_server()
        rc, out, _ = self.run_cli("clear", input_text="CLEAR PRISTINE\n")
        self.assertEqual(0, rc, out)
        self.assertIn("already_clear", out)
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "facts.sqlite3")))

    def test_pristine_wrong_confirmation_cancels(self):
        rc, out, err = self.run_cli("clear", input_text="CLEAR nope\n")
        self.assertEqual(1, rc)
        self.assertIn("confirmation_failed", out + err)

    def test_json_error_protocol(self):
        rc, out, _ = self.run_cli("clear", "--yes", "--json")
        self.assertEqual(2, rc)
        error = json.loads(out)
        self.assertEqual(1, error["error_version"])
        self.assertIn("code", error)
        self.assertIn("remediation", error)

    # -- SCN-54-3 -----------------------------------------------------------

    def test_sigint_detaches_and_operation_continues(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        # Hold a shared lease so the publish step's bounded exclusive
        # acquisition is still waiting when SIGINT lands: the foreground
        # detach is then deterministic instead of a race with a fast clear.
        shared = maintenance.MaintenanceLock(self.root).acquire()
        waiter = subprocess.Popen(
            [sys.executable, ENTRY, "clear", "--yes",
             "--expect-store-epoch", identity["store_epoch"]],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(os.environ))
        # Read the started line, then detach the foreground with SIGINT.
        started = waiter.stdout.readline()
        self.assertIn("clear started: operation", started)
        operation_id = started.rsplit(" ", 1)[1].strip()
        waiter.send_signal(signal.SIGINT)
        stdout, stderr = waiter.communicate(timeout=30)
        self.assertEqual(130, waiter.returncode)
        self.assertIn("detached from operation", stderr)
        shared.release()
        # The operation finished in the background.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = self.store().load(operation_id)
            if record["state"] in ("succeeded", "failed", "blocked",
                                   "cancelled"):
                break
            time.sleep(0.1)
        self.assertEqual("succeeded", record["state"])
        self.assertFalse(record["cancel_requested"])

    def test_operation_show_wait_work_after_clear(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        rc, out, _ = self.run_cli(
            "clear", "--yes", "--expect-store-epoch",
            identity["store_epoch"], "--json")
        self.assertEqual(0, rc, out)
        operation_id = self.read_stdout_docs(out)[0]["operation_id"]
        rc, out, _ = self.run_cli("operation", "show", operation_id,
                                  "--json")
        self.assertEqual(0, rc)
        shown = json.loads(out)
        self.assertEqual("succeeded", shown["state"])
        rc, out, _ = self.run_cli("operation", "wait", operation_id,
                                  "--json")
        self.assertEqual(0, rc)
        waited = json.loads(out)
        self.assertEqual("succeeded", waited["state"])

    def test_old_operation_details_cleaned_but_show_stays_stable(self):
        identity, _ = self.make_live_store()
        self.start_control_server()
        first = self.run_cli(
            "clear", "--yes", "--expect-store-epoch",
            identity["store_epoch"], "--json")
        self.assertEqual(0, first[0], first[1] + first[2])
        first_id = self.read_stdout_docs(first[1])[0]["operation_id"]
        # Second clear: the first record is an "old operation detail" and is
        # removed by cleanup; the second remains queryable. The store exists
        # (empty), so the non-interactive epoch CAS applies.
        first_record = self.read_stdout_docs(first[1])[1]
        self.assertEqual("cleared", first_record["result"]["outcome"])
        live, _empty = self.live_identity()
        second = self.run_cli(
            "clear", "--yes", "--expect-store-epoch", live["store_epoch"],
            "--json")
        self.assertEqual(0, second[0], second[1] + second[2])
        second_id = self.read_stdout_docs(second[1])[0]["operation_id"]
        ops_dir = os.path.join(self.root, "operations")
        names = os.listdir(ops_dir)
        self.assertIn("%s.json" % second_id, names)
        self.assertNotIn("%s.json" % first_id, names)
        rc, out, _ = self.run_cli("operation", "show", second_id, "--json")
        self.assertEqual(0, rc)
        self.assertEqual("succeeded", json.loads(out)["state"])


if __name__ == "__main__":
    unittest.main()
