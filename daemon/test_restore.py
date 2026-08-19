#!/usr/bin/env python3
"""Deterministic tests for the whole-store restore operation
(Habit130/squirrel#56, contract AC-56-v1).

Seams under test:

- Step level: `create_operation` + `try_run_pending_steps` with max_steps
  stepping, `fault_hook` crash injection, fake control clients and fake
  clocks. No wall-clock sleep drives any assertion.
- CLI level: the real `squirrel-semantic-memory` entry point in a
  subprocess with a sandboxed environment, the real C++ fact-store helper
  binary and a real in-process control server, so the production wiring
  (detached executor, offline backup verify, staging extract/migrate/
  prepare-restore, atomic replace) is exercised end to end.

The test predecessor step v1 -> v2 (interpretation-preserving) is loaded by
the C++ tool when SQUIRREL_FACT_MIGRATE_TEST_STEPS is set (decision B), so a
real supported-old backup -> head restore path runs against the actual C++
migrator and the C++ prepare-restore epoch mint.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
import uuid
import zipfile

DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(DAEMON_DIR, "squirrel-semantic-memory")
sys.path.insert(0, DAEMON_DIR)

import backup_operation  # noqa: E402
import cli  # noqa: E402
import operations as operations_module  # noqa: E402
import quarantine  # noqa: E402
import restore_operation  # noqa: E402
from backup_operation import (  # noqa: E402
    FACTS_MEMBER,
    MANIFEST_MEMBER,
    SENSITIVE_DECLARATION,
    _staging_root as _backup_staging_root,
    read_backup_manifest,
)
from clear_operation import FactStoreHelper  # noqa: E402
from operations import (  # noqa: E402
    OperationStore,
    SimulatedCrash,
    cancel_operation,
    create_operation,
    try_run_pending_steps,
)
from restore_operation import (  # noqa: E402
    RESTORE_DIRNAME,
    _identity_path,
    _staging_manifest_path,
    _staging_root,
)

TOOL_PATH = os.path.normpath(os.path.join(
    DAEMON_DIR, "..", "..", "..", "build", "plugins", "llm-rerank", "bin",
    "fact_store_tool"))

SECRET_PRECEDING = "秘密上文机密内容"
SECRET_CANDIDATE = "机密候选词"

EVENT_IDS = ("seed-event-a", "seed-event-b")

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
_INSERT_RETRACTION = (
    "INSERT INTO retractions(retraction_id, commit_id, hlc_physical_ms,"
    " hlc_logical, utc_retracted_at_ms) VALUES(?, ?, ?, ?, ?);")


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


class RestoreEnv(unittest.TestCase):
    """Sandboxed environment shared by all restore tests."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="restore_test_")
        self.root = os.path.join(self._tmp, "SemanticMemory")
        self.dest_dir = os.path.join(self._tmp, "dest")
        os.makedirs(self.dest_dir, mode=0o700)
        self.control_socket = os.path.join(self._tmp, "control.sock")
        self.scoring_socket = os.path.join(self._tmp, "scoring.sock")
        self.rime_dir = os.path.join(self._tmp, "Rime")
        os.makedirs(self.rime_dir, mode=0o700)
        self._old_env = dict(os.environ)
        os.environ["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = self.root
        os.environ["SQUIRREL_DAEMON_CONTROL_SOCKET"] = self.control_socket
        os.environ["SQUIRREL_DAEMON_SOCKET"] = self.scoring_socket
        os.environ["SQUIRREL_RIME_DIR"] = self.rime_dir
        os.environ["SQUIRREL_FACT_STORE_HELPER"] = TOOL_PATH
        # The migrate test steps are deliberately NOT set globally: backup
        # fixtures are created with head 1 (v1 = current, backuppable), and
        # the supported-old restore test sets the seam only around the
        # restore operation so v1 is classified as supported-old there.
        self.helper = FactStoreHelper(TOOL_PATH)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- fixtures -----------------------------------------------------------

    def make_live_store(self, seed=True):
        """Create a live store at the root via the C++ seam."""
        identity = self.helper.create_empty(self.root)
        if seed:
            self.seed_events(identity["store_epoch"])
        return identity

    def seed_events(self, store_epoch, with_retraction=False):
        """Simulate the plugin having recorded facts (fixture only)."""
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        commit_id = "c" * 32
        connection.execute(_INSERT_COMMIT, (commit_id, 1700000000000))
        for index, event_id in enumerate(EVENT_IDS):
            connection.execute(_INSERT_EVENT, (
                event_id, commit_id, 1, "luna_pinyin", "shijie", 0, 6,
                "word", SECRET_PRECEDING if index == 0 else "", 1,
                SECRET_CANDIDATE, "explicit_current", None, 1, 1,
                "session-1", index, 1700000000000 + index, index,
                1700000000000, 1700000000000))
            connection.execute(_INSERT_CANDIDATE, (event_id, 0, "世界"))
            connection.execute(_INSERT_CANDIDATE, (event_id, 1, "时界"))
        if with_retraction:
            connection.execute(_INSERT_RETRACTION, (
                "r" * 32, commit_id, 1700000000100, 100, 1700000000100))
        connection.commit()
        connection.close()
        return store_epoch

    def make_backup(self, output=None, seed=True, with_retraction=False):
        """Create a real backup container via the backup.create operation.
        Reuses an existing live root (the caller may have created it)."""
        if not os.path.isdir(self.root):
            self.make_live_store(seed=seed)
        output = output or os.path.join(self.dest_dir,
                                        "backup.squirrel-memory-backup")
        registry = operations_module.OperationRegistry()
        registry.register(backup_operation.BackupSpec(
            self.root, helper=self.helper, euid=os.geteuid(),
            program_version="0.1.0").build())
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": output})
        record = operations_module.run_pending_steps(
            store, registry, record["operation_id"])
        self.assertEqual("succeeded", record["state"], record)
        return output, record["result"]

    def make_backup_from_store(self, source_root, output=None):
        """Create a backup container from an ALREADY-POPULATED source root
        (the "backup machine" is a different facts root than the restore
        target)."""
        output = output or os.path.join(self.dest_dir,
                                        "backup.squirrel-memory-backup")
        registry = operations_module.OperationRegistry()
        registry.register(backup_operation.BackupSpec(
            source_root, helper=self.helper, euid=os.geteuid(),
            program_version="0.1.0").build())
        store = OperationStore(source_root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": output})
        record = operations_module.run_pending_steps(
            store, registry, record["operation_id"])
        self.assertEqual("succeeded", record["state"], record)
        return output, record["result"]

    def seed_backup(self, root, store_epoch):
        """Seed a DIFFERENT single-event store (the backup machine). The
        event HLC must stay consistent with the store's durable meta clock
        (which the C++ prepare-restore re-validates), so it reuses the
        store's own clock rather than a hard-coded timestamp."""
        db_path = os.path.join(root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        clock = connection.execute(
            "SELECT value FROM meta WHERE key='hlc_physical_ms'").fetchone()[0]
        connection.execute(_INSERT_COMMIT, ("cb" * 16, int(clock)))
        connection.execute(_INSERT_EVENT, (
            "backup-event-0", "cb" * 16, 1, "luna_pinyin", "shijie", 0, 6,
            "word", "", 1, "备份选中", "explicit_indexed", None, 1, 1,
            "session-b", 0, int(clock), 0, int(clock), int(clock)))
        connection.execute(_INSERT_CANDIDATE,
                           ("backup-event-0", 0, "备份选中"))
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
            "program_version": "0.1.0",
        }
        defaults.update(seams)
        return restore_operation.RestoreSpec(self.root, **defaults).build()

    def registry(self, spec):
        registry = operations_module.OperationRegistry()
        registry.register(spec)
        return registry

    def create_op(self, spec, from_path, epoch, operation_id=None,
                  backup_current=None, discard_current=True,
                  accept_unreadable_current=False,
                  expect_current_fingerprint="", expect_no_store=False):
        store = OperationStore(self.root)
        return create_operation(
            store, self.registry(spec), "restore",
            {"from_path": from_path,
             "backup_current": backup_current,
             "discard_current": discard_current,
             "expect_store_epoch": epoch,
             "accept_unreadable_current": accept_unreadable_current,
             "expect_current_fingerprint": expect_current_fingerprint,
             "expect_no_store": expect_no_store},
            operation_id=operation_id)

    def store(self):
        return OperationStore(self.root)

    def run_cli(self, *args, input_text=None, timeout=60):
        completed = subprocess.run(
            [sys.executable, ENTRY] + list(args),
            capture_output=True, text=True, timeout=timeout,
            input=input_text, env=dict(os.environ))
        return completed.returncode, completed.stdout, completed.stderr

    def staged_db(self, operation_id):
        return os.path.join(_staging_root(self.root, operation_id), "store",
                            "facts.sqlite3")


class FakeControlClient:
    """Records the maintenance protocol without a real daemon."""

    def __init__(self, path, operation_id):
        self.path = path
        self.operation_id = operation_id
        self.steps = []
        self.prepare_ok = True
        self.prepare_code = None
        self.reopen_store_epoch = None
        self.reopen_state = "serving"
        self.reopen_serving = True

    def __enter__(self):
        self.steps.append("open")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.steps.append("close")

    def prepare(self, expect_unreadable=False):
        self.steps.append("prepare")
        if expect_unreadable:
            self.steps.append("prepare:unreadable")
        if not self.prepare_ok:
            return {"ok": False, "code": self.prepare_code
                    or "maintenance_in_progress"}
        return {"ok": True, "store_epoch": None}

    def assert_prepared(self):
        self.steps.append("lease")
        return {"ok": True, "state": "prepared"}

    def reopen(self):
        self.steps.append("reopen")
        return {"ok": True, "state": self.reopen_state,
                "store_epoch": self.reopen_store_epoch,
                "serving_ready": self.reopen_serving}


class FakeClock:
    """Deterministic now/sleep pair for the bounded quiesce acquisition."""

    def __init__(self, advance=0.01):
        self.value = 0.0
        self.advance = advance

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class RestoreStepTests(RestoreEnv):
    """Step-level behavior with fake control and injected faults."""

    def setUp(self):
        super().setUp()
        self.clients = []
        self.original_probe = restore_operation._probe_control_socket
        restore_operation._probe_control_socket = lambda path: True

    def tearDown(self):
        restore_operation._probe_control_socket = self.original_probe
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
        record = None
        for _ in range(count):
            record, acquired = try_run_pending_steps(
                self.store(), self.registry(spec), operation_id, max_steps=1)
            self.assertTrue(acquired)
        return record

    # -- SCN-56-2 / SCN-56-3 ------------------------------------------------

    def test_full_restore_phase_progression_and_identity(self):
        # The live store is machine A (two events, history A/epoch A). The
        # backup comes from a SEPARATE populated root (machine B: history B,
        # epoch B, one event with a different event id).
        backup_root = os.path.join(self._tmp, "BackupMachine")
        live = self.make_live_store(seed=True)
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, backup_result = self.make_backup_from_store(backup_root)
        self.assertEqual(backup_identity["history_id"],
                         backup_result["history_id"])

        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"], record["error"])
        phases = [entry["phase"] for entry in record["log"]
                  if entry["kind"] == "transition"]
        self.assertEqual(["preflight", "waiting-for-quiesce", "staging",
                          "publishing", "reopening", "cleanup"], phases[:6])
        result = record["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["fact_operation_succeeded"])
        # SCN-56-2: no event-id merge — the live store is replaced wholesale
        # with the backup's events (the live machine A's events are gone).
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        self.assertNotEqual(backup_identity["store_epoch"],
                            new_identity["store_epoch"])
        self.assertNotEqual(live["store_epoch"], new_identity["store_epoch"])
        # SCN-56-3: the backup's events and HLC state are preserved.
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        try:
            events = connection.execute(
                "SELECT event_id FROM selection_events "
                "ORDER BY event_id").fetchall()
            hlc = connection.execute(
                "SELECT value FROM meta WHERE key='hlc_physical_ms'"
                ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual([("backup-event-0",)], events)
        # The backup's HLC state is preserved verbatim (the backup machine's
        # clock, not the live machine A's).
        self.assertEqual(str(backup_result["hlc_high_water"]["physical_ms"]),
                         hlc)
        self.assertEqual(backup_result["history_id"],
                         result["backup_history_id"])
        self.assertEqual(backup_result["store_epoch"],
                         result["backup_store_epoch"])
        # The old live epoch is reported as the old identity.
        self.assertEqual(live["store_epoch"], result["old"]["store_epoch"])
        # serving_ready is reported separately from fact_operation_succeeded.
        self.assertIn("serving_ready", result)
        # The control connection used the operation's own random id.
        self.assertEqual([operation_id],
                         [c.operation_id for c in self.clients if c.steps])

    # -- SCN-56-1 -----------------------------------------------------------

    def test_preflight_bad_zip_blocks_with_zero_side_effects(self):
        live = self.make_live_store(seed=True)
        bad = os.path.join(self.dest_dir, "bad.squirrel-memory-backup")
        with open(bad, "wb") as stream:
            stream.write(b"not a zip at all")
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, bad, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("zip_malformed", record["error"]["code"])
        # Live identity and bytes unchanged.
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual([], self.clients)

    def test_preflight_checksum_mismatch_blocks(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        # Tamper one byte inside the container's facts member.
        with open(backup, "rb+") as stream:
            stream.seek(100)
            byte = stream.read(1)
            stream.seek(100)
            stream.write(bytes([byte[0] ^ 0xFF]))
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertIn(record["error"]["code"],
                      ("checksum_mismatch", "zip_malformed",
                       "zip_size_limit"))
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_preflight_too_new_backup_blocks(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        # Rewrite the manifest to claim an unsupported schema version.
        container = os.path.join(self.dest_dir, "rewritten"
                                 ".squirrel-memory-backup")
        with zipfile.ZipFile(backup, "r") as archive:
            members = archive.infolist()
            db_data = archive.read(FACTS_MEMBER)
            manifest = json.loads(archive.read(MANIFEST_MEMBER).decode("utf-8"))
        manifest["fact_schema_version"] = 99
        with zipfile.ZipFile(container, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for info in members:
                if info.filename == FACTS_MEMBER:
                    archive.writestr(info, db_data)
                else:
                    archive.writestr(info, json.dumps(
                        manifest, ensure_ascii=False).encode("utf-8"))
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, container, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("manifest_version_unsupported",
                         record["error"]["code"])
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    # -- SCN-56-4 / SCN-56-5 ------------------------------------------------

    def test_backup_current_xor_discard_current_required(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        spec = self.build_spec(control_client_factory=self.control_factory())
        # Missing both: usage fail at normalize, no operation record.
        store = OperationStore(self.root)
        with self.assertRaises(ValueError):
            create_operation(
                store, self.registry(spec), "restore",
                {"from_path": backup, "backup_current": None,
                 "discard_current": False,
                 "expect_store_epoch": live["store_epoch"]})
        # Both set: usage fail at normalize, no operation record.
        with self.assertRaises(ValueError):
            create_operation(
                store, self.registry(spec), "restore",
                {"from_path": backup, "backup_current": "/tmp/x",
                 "discard_current": True,
                 "expect_store_epoch": live["store_epoch"]})
        # No mutation happened.
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_backup_current_after_quiesce_before_replace(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine2")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        current_output = os.path.join(self.dest_dir, "current"
                                      ".squirrel-memory-backup")
        publishes = []
        original_replace = restore_operation.replace_fact_database

        def recording_replace(root, path, lease):
            # The backup-current snapshot must exist and verify BEFORE the
            # replace runs.
            self.assertTrue(os.path.isfile(current_output))
            outcome = backup_operation.verify_backup(
                current_output, helper=self.helper)
            self.assertTrue(outcome["valid"], outcome)
            publishes.append(1)
            return original_replace(root, path, lease)

        restore_operation.replace_fact_database = recording_replace
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, live["store_epoch"],
                                    backup_current=current_output,
                                    discard_current=False)
            record = self.run_to_terminal(spec, record["operation_id"])
        finally:
            restore_operation.replace_fact_database = original_replace
        self.assertEqual("succeeded", record["state"], record["error"])
        self.assertEqual(1, len(publishes))
        result = record["result"]
        self.assertEqual(current_output,
                         result["backup_current_destination"])
        # The backup-current container is an independent verified backup of
        # the OLD live store (machine A's history/epoch, two events).
        outcome = backup_operation.verify_backup(
            current_output, helper=self.helper)
        self.assertTrue(outcome["valid"], outcome)
        self.assertEqual(live["history_id"], outcome["history_id"])
        self.assertEqual(live["store_epoch"], outcome["store_epoch"])
        self.assertEqual(2, outcome["event_count"])
        # The live store is now the backup machine B.
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])

    def test_discard_current_writes_no_current_backup(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine3")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"],
                                discard_current=True)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"], record["error"])
        self.assertTrue(record["result"]["discarded_current"])
        # No current backup was written anywhere under the app root.
        self.assertFalse(os.path.exists(os.path.join(
            self.root, backup_operation.BACKUP_DIRNAME)))
        self.assertEqual([], [entry for entry in os.listdir(self.dest_dir)
                              if entry != "backup.squirrel-memory-backup"])

    def test_backup_current_failure_leaves_live_unchanged(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine4")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        # The destination already exists: backup-current must fail with
        # destination_exists BEFORE the replace, leaving live unchanged.
        current_output = os.path.join(self.dest_dir, "occupied"
                                      ".squirrel-memory-backup")
        with open(current_output, "wb") as stream:
            stream.write(b"occupied")
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"],
                                backup_current=current_output,
                                discard_current=False)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_exists", record["error"]["code"])
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual(live["history_id"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "history_id"))

    # -- SCN-56-6 -----------------------------------------------------------

    def test_stale_epoch_cas_blocks_with_zero_side_effects(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "f" * 32)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("preflight", record["phase"])
        self.assertEqual("store_epoch_mismatch", record["error"]["code"])
        self.assertFalse(os.path.exists(
            _staging_root(self.root, record["operation_id"])))
        self.assertEqual([], self.clients)
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_epoch_reverified_under_exclusive_lease(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine5")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]
        record = self.run_stepwise(spec, operation_id, 3)
        self.assertEqual("publishing", record["phase"])
        # Simulate a concurrent store replacement under the lease.
        original = restore_operation.read_identity_under_exclusive
        restore_operation.read_identity_under_exclusive = (
            lambda root: {"store_epoch": "e" * 32, "history_id": "h" * 32,
                          "hlc_physical_ms": 1, "hlc_logical": 0})
        try:
            record = self.run_to_terminal(spec, operation_id)
        finally:
            restore_operation.read_identity_under_exclusive = original
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_epoch_mismatch", record["error"]["code"])
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    # -- SCN-56-7 -----------------------------------------------------------

    def test_result_reports_fact_and_serving_separately(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine6")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"], record["error"])
        result = record["result"]
        self.assertTrue(result["fact_operation_succeeded"])
        # serving_ready is a separate field; with the fake daemon it reports
        # the reopen state (here: serving, no rebuild queued).
        self.assertIn("serving_ready", result)
        self.assertTrue(result["serving_ready"])
        self.assertFalse(result["rebuild_queued"])

    def test_result_reports_queued_rebuild_when_daemon_catching_up(self):
        # The daemon reopen is the authoritative "rebuild durably queued"
        # signal: a new epoch puts the coordinator in catching_up with
        # serving_ready False — the restore reports fact_operation_succeeded
        # True and serving_ready False (rebuild queued, never waited on).
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine6b")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]
        # Configure the fake daemon reopen as a new-epoch catching_up state.
        for client in self.clients:
            client.reopen_state = "catching_up"
            client.reopen_serving = False
        # The reopen response must report the new epoch for the publishing
        # gate to accept it.
        def catching_up_factory(path, opid):
            client = FakeControlClient(path, opid)
            client.reopen_state = "catching_up"
            client.reopen_serving = False
            self.clients.append(client)
            return client
        spec = self.build_spec(control_client_factory=catching_up_factory)
        record = self.create_op(spec, backup, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("succeeded", record["state"], record["error"])
        result = record["result"]
        self.assertTrue(result["fact_operation_succeeded"])
        self.assertFalse(result["serving_ready"])
        self.assertTrue(result["rebuild_queued"])

    # -- SCN-56-8 -----------------------------------------------------------

    def test_crash_before_replace_leaves_complete_old_store(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine7")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]

        def crash_in_publishing(phase, step_index, point):
            if (phase, step_index, point) == ("publishing", 0, "before_step"):
                raise SimulatedCrash()
        with self.assertRaises(SimulatedCrash):
            try_run_pending_steps(self.store(), self.registry(spec),
                                  operation_id,
                                  fault_hook=crash_in_publishing)
        # The live store is unchanged (complete old store).
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual(live["history_id"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "history_id"))

    def test_crash_after_replace_leaves_complete_new_store(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine8")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]

        def crash_after_publish(phase, step_index, point):
            if (phase, step_index, point) == ("publishing", 0, "after_step"):
                raise SimulatedCrash()
        with self.assertRaises(SimulatedCrash):
            try_run_pending_steps(self.store(), self.registry(spec),
                                  operation_id,
                                  fault_hook=crash_after_publish)
        # The live store is the complete NEW store (backup machine B's
        # history, new epoch).
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        self.assertNotEqual(backup_identity["store_epoch"],
                            new_identity["store_epoch"])
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        try:
            events = connection.execute(
                "SELECT event_id FROM selection_events "
                "ORDER BY event_id").fetchall()
        finally:
            connection.close()
        self.assertEqual([("backup-event-0",)], events)
        # The retry recognizes the published store and finishes.
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"], record["error"])
        self.assertTrue(record["result"]["fact_operation_succeeded"])

    def test_crash_between_replace_and_marker_recovers(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine9")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        original_write = restore_operation._write_json_atomic
        marker_writes = []

        def crashing_write(path, payload, euid):
            if (os.path.basename(path)
                    == restore_operation.PUBLISHED_MARKER
                    and not marker_writes):
                marker_writes.append(1)
                raise SimulatedCrash()
            return original_write(path, payload, euid)

        restore_operation._write_json_atomic = crashing_write
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, live["store_epoch"])
            operation_id = record["operation_id"]
            with self.assertRaises(SimulatedCrash):
                try_run_pending_steps(self.store(), self.registry(spec),
                                      operation_id)
            # The atomic replace happened, the marker write "crashed": the
            # disk already carries the staged identity.
            new_identity, _empty = self.live_identity()
            self.assertEqual(backup_identity["history_id"],
                             new_identity["history_id"])
            record = self.run_to_terminal(spec, operation_id)
            self.assertEqual("succeeded", record["state"], record["error"])
            self.assertEqual(1, len(marker_writes))
        finally:
            restore_operation._write_json_atomic = original_write

    # -- SCN-56-9 -----------------------------------------------------------

    def test_supported_old_backup_migrates_staging_copy_only(self):
        live = self.make_live_store(seed=True)
        # A supported-old backup: schema v1 below the test head 2, created
        # with the test predecessor step loaded ONLY around this restore so
        # v1 is classified as supported-old (the backup itself was created
        # with the seam off).
        backup_root = os.path.join(self._tmp, "BackupMachineOld")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        # Record the backup container's facts bytes BEFORE the restore.
        with zipfile.ZipFile(backup, "r") as archive:
            original_db = archive.read(FACTS_MEMBER)
        original_manifest = read_backup_manifest(backup)

        os.environ["SQUIRREL_FACT_MIGRATE_TEST_STEPS"] = "1"
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, live["store_epoch"])
            record = self.run_to_terminal(spec, record["operation_id"])
            # The restored live store is at the head (2 under the test
            # seam); the identity is read with the seam still ON.
            new_identity, _empty = self.live_identity()
        finally:
            del os.environ["SQUIRREL_FACT_MIGRATE_TEST_STEPS"]
        self.assertEqual("succeeded", record["state"], record["error"])
        result = record["result"]
        self.assertTrue(result["fact_operation_succeeded"])
        # The backup ORIGINAL is byte-identical: only the staging copy was
        # migrated (SCN-56-9).
        with zipfile.ZipFile(backup, "r") as archive:
            after_db = archive.read(FACTS_MEMBER)
        self.assertEqual(original_db, after_db)
        self.assertEqual(original_manifest, read_backup_manifest(backup))
        self.assertEqual("2", _meta_value(os.path.join(self.root,
                                                       "facts.sqlite3"),
                                          "fact_schema_version"))
        # history_id from the backup is preserved; epoch is new.
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        self.assertNotEqual(backup_identity["store_epoch"],
                            new_identity["store_epoch"])

    def test_too_new_backup_blocks_in_preflight(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        # Force the extracted DB to claim a too-new schema AND rebuild the
        # container's manifest checksum/size so the only failing check is the
        # version disposition (a coherent container that is too new).
        container = os.path.join(self.dest_dir, "toonew"
                                 ".squirrel-memory-backup")
        with zipfile.ZipFile(backup, "r") as archive:
            members = archive.infolist()
            db_data = archive.read(FACTS_MEMBER)
            manifest = json.loads(archive.read(MANIFEST_MEMBER).decode("utf-8"))
        extracted = os.path.join(self._tmp, "toonew.sqlite3")
        with open(extracted, "wb") as stream:
            stream.write(db_data)
        connection = sqlite3.connect(extracted)
        connection.execute("UPDATE meta SET value='99' WHERE"
                           " key='fact_schema_version'")
        connection.commit()
        connection.close()
        with open(extracted, "rb") as stream:
            new_db = stream.read()
        manifest["fact_schema_version"] = 99
        manifest["database_sha256"] = hashlib.sha256(new_db).hexdigest()
        manifest["database_size"] = len(new_db)
        with zipfile.ZipFile(container, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for info in members:
                if info.filename == FACTS_MEMBER:
                    archive.writestr(info, new_db)
                else:
                    archive.writestr(info, json.dumps(
                        manifest, ensure_ascii=False).encode("utf-8"))
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, container, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("manifest_version_unsupported",
                         record["error"]["code"])
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_insufficient_space_blocks_in_preflight(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        original_statvfs = restore_operation._space_available
        restore_operation._space_available = lambda root: 100  # 100 bytes
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, live["store_epoch"])
            record = self.run_to_terminal(spec, record["operation_id"])
        finally:
            restore_operation._space_available = original_statvfs
        self.assertEqual("blocked", record["state"])
        self.assertEqual("insufficient_space", record["error"]["code"])
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_backup_current_staging_residue_is_cleaned(self):
        # If --backup-current fails after the snapshot staging was created
        # (here: the destination medium is insecure), the .backup staging
        # residue must be removed and the live store unchanged.
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine4b")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        current_output = os.path.join(self.dest_dir, "insecure"
                                      ".squirrel-memory-backup")
        spec = self.build_spec(
            control_client_factory=self.control_factory(),
            probe_medium=lambda output, opid: False)
        record = self.create_op(spec, backup, live["store_epoch"],
                                backup_current=current_output,
                                discard_current=False)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("insecure_destination", record["error"]["code"])
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))
        # No .backup staging residue (the nested backup staging was removed
        # on the failure path, before the replace).
        backup_dir = os.path.join(self.root, backup_operation.BACKUP_DIRNAME)
        self.assertFalse(os.path.exists(backup_dir))
        # The restore's own .restore staging is kept for the explicit retry
        # (a blocked operation never auto-retries but the durable staging is
        # reused verbatim).
        self.assertTrue(os.path.isdir(os.path.join(
            self.root, RESTORE_DIRNAME)))

    # -- SCN-56-10 ----------------------------------------------------------

    def test_quiesce_timeout_fails_without_touching_store(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine10")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        clock = FakeClock()
        spec = self.build_spec(
            control_client_factory=self.control_factory(),
            timeout_s=5.0, now=clock.now, sleep=clock.sleep)
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]
        # A competing shared lease holds the maintenance lock for the whole
        # bounded window: staging succeeds, the exclusive publish
        # acquisition times out.
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
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual(live["history_id"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "history_id"))

    # -- SCN-56-11 ----------------------------------------------------------

    def test_cancel_before_replace_reopens_old_state(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine11")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]
        # Run preflight and waiting-for-quiesce (2 steps); the record now
        # sits at staging, which is still cancelable (before publishing).
        record = self.run_stepwise(spec, operation_id, 2)
        self.assertEqual("staging", record["phase"])
        # Request a cancel BEFORE the irreversible replacement; the runner
        # honors it and moves into the cancel_phase (reopening) compensation.
        record, disposition = cancel_operation(self.store(), operation_id)
        self.assertEqual("requested", disposition)
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("cancelled", record["state"], record["error"])
        # The old store was reopened: live bytes unchanged.
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))
        self.assertEqual(live["history_id"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "history_id"))

    def test_cancel_after_publish_is_uncancellable(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine12")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"])
        # A terminal operation is never cancellable.
        record, disposition = cancel_operation(self.store(), operation_id)
        self.assertEqual("terminal", disposition)

    # -- SCN-56-12 ----------------------------------------------------------

    def test_missing_store_fails_closed(self):
        backup_root = os.path.join(self._tmp, "BackupMachine13")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "e" * 32)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_missing", record["error"]["code"])

    def test_unreadable_current_fails_closed(self):
        # A current store that cannot be read (e.g. corrupt) must fail
        # closed, never be silently replaced.
        live = self.make_live_store(seed=True)
        db_path = os.path.join(self.root, "facts.sqlite3")
        with open(db_path, "rb+") as stream:
            stream.seek(4096)
            stream.write(b"\xff\xff\xff\xff")
        backup_root = os.path.join(self._tmp, "BackupMachine14")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("fact_store_unverifiable",
                         record["error"]["code"])

    # -- #57 unreadable / no-store paths -------------------------------------

    def _make_unreadable_store(self, seed=True):
        """Create a live store, then corrupt its main DB header so the
        identity seam cannot read it. Returns (identity_before, fingerprint)
        where the fingerprint is over the as-is DB+WAL+SHM bytes. Uses the
        C++-seam-on-copy classifier to prove unreadability (any sqlite open
        of the live store would rewrite its WAL/SHM sidecars and change the
        fingerprint)."""
        live = self.make_live_store(seed=seed)
        db_path = os.path.join(self.root, "facts.sqlite3")
        with open(db_path, "rb+") as stream:
            stream.seek(4096)
            stream.write(b"\xff\xff\xff\xff")
        # Prove the seam now fails closed (unreadable) WITHOUT mutating the
        # store: classify_current_store runs the C++ schema seam on a copy.
        disposition, detail = quarantine.classify_current_store(
            self.root, self.helper, os.geteuid())
        self.assertEqual("unreadable", disposition, detail)
        members = {}
        for member in quarantine.QUARANTINE_MEMBERS:
            path = os.path.join(self.root, member)
            if os.path.exists(path):
                with open(path, "rb") as stream:
                    members[member] = stream.read()
        fingerprint = quarantine.fingerprint_bytes(members)
        return live, fingerprint

    def _quarantine_bytes(self, operation_id):
        import quarantine
        path = os.path.join(self.root, quarantine.QUARANTINE_DIRNAME,
                            operation_id, "facts.sqlite3")
        with open(path, "rb") as stream:
            return stream.read()

    def test_unreadable_restore_flag_pair_required(self):
        # Either #57 flag alone is a usage error before any mutation.
        live, fingerprint = self._make_unreadable_store()
        backup_root = os.path.join(self._tmp, "BackupMachine57a")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        # accept without fingerprint
        with self.assertRaises(ValueError):
            self.create_op(spec, backup, "", accept_unreadable_current=True)
        # fingerprint without accept
        with self.assertRaises(ValueError):
            self.create_op(spec, backup, "",
                           expect_current_fingerprint=fingerprint)

    def test_unreadable_current_accepted_with_fingerprint_and_quarantine(
            self):
        # SCN-57-1: unreadable current + correct accept/fingerprint ->
        # quarantine (as-is bytes, verified) then replace.
        live, fingerprint = self._make_unreadable_store()
        db_bytes = self._read_db_bytes()
        backup_root = os.path.join(self._tmp, "BackupMachine57b")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, backup_result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",
                                accept_unreadable_current=True,
                                expect_current_fingerprint=fingerprint)
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"], record["error"])
        result = record["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["fact_operation_succeeded"])
        self.assertEqual(operation_id, result["quarantine_operation_id"])
        self.assertEqual(fingerprint, result["quarantine_fingerprint"])
        # The old (unreadable) store was replaced by the backup's history.
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        self.assertNotEqual(live["store_epoch"], new_identity["store_epoch"])
        # The quarantine copy preserves the as-is main DB bytes verbatim.
        self.assertEqual(db_bytes, self._quarantine_bytes(operation_id))
        # The quarantine metadata is identity-only (no private text).
        import quarantine
        metadata_path = os.path.join(
            self.root, quarantine.QUARANTINE_DIRNAME, operation_id,
            quarantine.METADATA_FILE)
        metadata = json.load(open(metadata_path))
        self.assertEqual(fingerprint, metadata["fingerprint"])
        self.assertNotIn(SECRET_PRECEDING, json.dumps(metadata))
        self.assertNotIn(SECRET_CANDIDATE, json.dumps(metadata))

    def _read_db_bytes(self):
        with open(os.path.join(self.root, "facts.sqlite3"), "rb") as stream:
            return stream.read()

    def test_unreadable_fingerprint_mismatch_no_replace(self):
        # SCN-57-2: fingerprint mismatch aborts with no replace and no
        # successful-looking quarantine.
        live, _fingerprint = self._make_unreadable_store()
        db_bytes = self._read_db_bytes()
        backup_root = os.path.join(self._tmp, "BackupMachine57c")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",
                                accept_unreadable_current=True,
                                expect_current_fingerprint="b" * 64)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("fingerprint_mismatch", record["error"]["code"])
        # The current bytes are untouched.
        self.assertEqual(db_bytes, self._read_db_bytes())
        # No quarantine was published (a partial dir must not look
        # successful).
        import quarantine
        self.assertFalse(os.path.exists(
            os.path.join(self.root, quarantine.QUARANTINE_DIRNAME)))

    def test_unreadable_path_rejects_healthy_store(self):
        # The unreadable path is not a bypass of the epoch CAS: a healthy
        # readable current store is refused.
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine57d")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",
                                accept_unreadable_current=True,
                                expect_current_fingerprint="d" * 64)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_present_unexpected",
                         record["error"]["code"])
        # The healthy store is unchanged.
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_unreadable_path_rejects_too_new_and_migrate_eligible(self):
        # RISK-57-2 pinning: a too-new or supported-old store is classified
        # "readable" by the C++ seam (migrate / #58 stays the only upgrade
        # path); it is never forced through quarantine-restore.
        for bump in (999, 0):
            with self.subTest(schema_version=bump):
                if os.path.isdir(self.root):
                    shutil.rmtree(self.root)
                live = self.make_live_store(seed=True)
                connection = sqlite3.connect(
                    os.path.join(self.root, "facts.sqlite3"))
                connection.execute(
                    "UPDATE meta SET value=? WHERE key='fact_schema_version'",
                    (str(bump),))
                connection.commit()
                connection.close()
                backup_root = os.path.join(
                    self._tmp, "BackupMachine57r%d" % bump)
                backup_identity = self.helper.create_empty(backup_root)
                self.seed_backup(backup_root,
                                 backup_identity["store_epoch"])
                backup, _result = self.make_backup_from_store(
                    backup_root,
                    output=os.path.join(
                        self.dest_dir, "backup57r%d.squirrel-memory-backup"
                        % bump))
                spec = self.build_spec(
                    control_client_factory=self.control_factory())
                record = self.create_op(
                    spec, backup, "",
                    accept_unreadable_current=True,
                    expect_current_fingerprint="d" * 64)
                record = self.run_to_terminal(spec, record["operation_id"])
                self.assertEqual("blocked", record["state"])
                self.assertEqual("store_present_unexpected",
                                 record["error"]["code"])
                self.assertFalse(os.path.exists(
                    os.path.join(self.root, quarantine.QUARANTINE_DIRNAME)))

    def test_unreadable_path_rejects_missing_store(self):
        # A missing store is the --expect-no-store territory, never the
        # unreadable path.
        backup_root = os.path.join(self._tmp, "BackupMachine57e")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",                                accept_unreadable_current=True,
                                expect_current_fingerprint="d" * 64)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_missing", record["error"]["code"])

    def test_expect_no_store_restores_without_quarantine(self):
        # SCN-57-3: missing store + --expect-no-store -> restore without
        # quarantine; no epoch CAS.
        backup_root = os.path.join(self._tmp, "BackupMachine57f")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, backup_result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "", expect_no_store=True)
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"], record["error"])
        result = record["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["no_store"])
        self.assertIsNone(result["old"])
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        # No quarantine was created.
        import quarantine
        self.assertFalse(os.path.exists(
            os.path.join(self.root, quarantine.QUARANTINE_DIRNAME)))

    def test_expect_no_store_rejects_unreadable_file(self):
        # An unreadable present file does NOT satisfy --expect-no-store (the
        # gate is raw presence: the path must be absent, never merely
        # unreadable).
        live, _fingerprint = self._make_unreadable_store()
        backup_root = os.path.join(self._tmp, "BackupMachine57g")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "", expect_no_store=True)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_present_unexpected",
                         record["error"]["code"])

    def test_expect_no_store_rejects_healthy_store(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine57h")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "", expect_no_store=True)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_present_unexpected",
                         record["error"]["code"])

    def test_expect_no_store_rejects_empty_present_file(self):
        # Seam 5 pinning: #56 treats a present (even empty) facts file as a
        # store — `verify` on a 0-byte file CREATES an empty store, so the
        # path exists and is NOT "missing". --expect-no-store therefore
        # refuses a 0-byte present file (the gate is raw presence).
        root = self.root
        os.makedirs(root, mode=0o700)
        os.chmod(root, 0o700)
        with open(os.path.join(root, "facts.sqlite3"), "wb"):
            pass
        os.chmod(os.path.join(root, "facts.sqlite3"), 0o600)
        backup_root = os.path.join(self._tmp, "BackupMachine57m")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "", expect_no_store=True)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("store_present_unexpected",
                         record["error"]["code"])
        # The 0-byte file was not touched (no restore, no quarantine).
        self.assertEqual(0, os.path.getsize(
            os.path.join(root, "facts.sqlite3")))
        self.assertFalse(os.path.exists(
            os.path.join(root, quarantine.QUARANTINE_DIRNAME)))

    def test_unreadable_no_store_conflict_at_normalize(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine57i")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        with self.assertRaises(ValueError):
            self.create_op(spec, backup, "",
                           accept_unreadable_current=True,
                           expect_current_fingerprint="d" * 64,
                           expect_no_store=True)

    def test_restore_then_clear_removes_quarantine(self):
        # SCN-57-7: after a successful unreadable restore the quarantine
        # still verifies; a later clear removes the app-controlled
        # quarantine (external backups untouched).
        live, fingerprint = self._make_unreadable_store()
        backup_root = os.path.join(self._tmp, "BackupMachine57j")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",
                                accept_unreadable_current=True,
                                expect_current_fingerprint=fingerprint)
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"], record["error"])
        import quarantine
        qdir = os.path.join(self.root, quarantine.QUARANTINE_DIRNAME,
                            operation_id)
        self.assertTrue(os.path.isdir(qdir))
        # External backup (a user file outside the root) stays untouched.
        external = os.path.join(self.dest_dir, "external-backup.bin")
        with open(external, "wb") as stream:
            stream.write(b"external")
        # Now clear; the clear deletes app-controlled quarantine.
        import clear_operation
        from clear_operation import ClearSpec
        original_probe = clear_operation._probe_control_socket
        clear_operation._probe_control_socket = lambda path: True
        try:
            clear_spec = ClearSpec(
                self.root, helper=self.helper, euid=os.geteuid(),
                control_socket=self.control_socket,
                scoring_socket=self.scoring_socket,
                control_client_factory=self.control_factory()).build()
            clear_record = create_operation(
                self.store(), self.registry(clear_spec), "clear",
                {"expect_store_epoch":
                 record["result"]["new"]["store_epoch"]})
            clear_record = self.run_to_terminal(clear_spec,
                                                clear_record["operation_id"])
        finally:
            clear_operation._probe_control_socket = original_probe
        self.assertEqual("succeeded", clear_record["state"],
                         clear_record["error"])
        self.assertEqual("cleared", clear_record["result"]["outcome"])
        self.assertFalse(os.path.exists(
            os.path.join(self.root, quarantine.QUARANTINE_DIRNAME)))
        self.assertTrue(os.path.exists(external))

    def test_healthy_restore_still_fail_closed_without_57_flags(self):
        # SCN-57-4: the #56 healthy path is preserved — an unreadable or
        # missing store still fails closed without the #57 flags.
        live, _fingerprint = self._make_unreadable_store()
        backup_root = os.path.join(self._tmp, "BackupMachine57k")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, live["store_epoch"])
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("fact_store_unverifiable",
                         record["error"]["code"])

    # -- #57 fault injection -------------------------------------------------

    def test_quarantine_copy_failure_no_replace_no_partial_dir(self):
        # SCN-57-2: a copy/disk-full failure during quarantine aborts with
        # no replace and no successful-looking quarantine.
        original_open = os.open
        original_publish = restore_operation.publish_quarantine

        def faulty_open(*args, **kwargs):
            if args and isinstance(args[0], str) \
                    and args[0] == "facts.sqlite3" \
                    and len(args) > 1 and (args[1] & os.O_WRONLY):
                raise OSError(28, "No space left on device")
            return original_open(*args, **kwargs)

        def fault_publish(root, operation_id, fds, expected, euid,
                          now=None, disposition="unreadable"):
            with unittest.mock.patch("quarantine.os.open", faulty_open):
                return quarantine.publish_quarantine(
                    root, operation_id, fds, expected, euid, now=now,
                    disposition=disposition)
        restore_operation.publish_quarantine = fault_publish
        try:
            live, fingerprint = self._make_unreadable_store()
            db_bytes = self._read_db_bytes()
            backup_root = os.path.join(self._tmp, "BackupMachine57fault1")
            backup_identity = self.helper.create_empty(backup_root)
            self.seed_backup(backup_root, backup_identity["store_epoch"])
            backup, _result = self.make_backup_from_store(backup_root)
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, "",
                                    accept_unreadable_current=True,
                                    expect_current_fingerprint=fingerprint)
            record = self.run_to_terminal(spec, record["operation_id"])
        finally:
            restore_operation.publish_quarantine = original_publish
        self.assertEqual("blocked", record["state"])
        self.assertEqual("quarantine_failed", record["error"]["code"])
        # The current bytes are untouched.
        self.assertEqual(db_bytes, self._read_db_bytes())
        # No partial quarantine op dir looks successful (the parent
        # `quarantine/` may remain, but never the operation's copy).
        self.assertFalse(os.path.exists(os.path.join(
            self.root, quarantine.QUARANTINE_DIRNAME, record["operation_id"])))

    def test_quarantine_verify_failure_no_replace(self):
        # SCN-57-2: a quarantine verification (byte-identity check of the
        # copies) failure aborts with no replace and removes the partial
        # quarantine.
        original_open = os.open
        original_publish = restore_operation.publish_quarantine
        state = {"db_reads": 0}

        def faulty_open(*args, **kwargs):
            # The verification step re-opens the copied `facts.sqlite3`
            # read-only (O_RDONLY == 0); fail that open so byte-identity
            # verification cannot complete. The write open (O_WRONLY set)
            # and the source fd from open_current_files (which predates the
            # patch) are not affected.
            if args and isinstance(args[0], str) \
                    and args[0] == "facts.sqlite3" \
                    and not (args[1] & os.O_WRONLY):
                raise OSError(5, "Input/output error")
            return original_open(*args, **kwargs)

        def fault_publish(root, operation_id, fds, expected, euid,
                          now=None, disposition="unreadable"):
            with unittest.mock.patch("quarantine.os.open", faulty_open):
                return quarantine.publish_quarantine(
                    root, operation_id, fds, expected, euid, now=now,
                    disposition=disposition)
        restore_operation.publish_quarantine = fault_publish
        try:
            live, fingerprint = self._make_unreadable_store()
            db_bytes = self._read_db_bytes()
            backup_root = os.path.join(self._tmp, "BackupMachine57fault2")
            backup_identity = self.helper.create_empty(backup_root)
            self.seed_backup(backup_root, backup_identity["store_epoch"])
            backup, _result = self.make_backup_from_store(backup_root)
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, "",
                                    accept_unreadable_current=True,
                                    expect_current_fingerprint=fingerprint)
            record = self.run_to_terminal(spec, record["operation_id"])
        finally:
            restore_operation.publish_quarantine = original_publish
        self.assertEqual("blocked", record["state"])
        self.assertEqual("quarantine_failed", record["error"]["code"])
        # The current bytes are untouched (no replace happened).
        self.assertEqual(db_bytes, self._read_db_bytes())
        # The partial quarantine op dir was removed.
        self.assertFalse(os.path.exists(os.path.join(
            self.root, quarantine.QUARANTINE_DIRNAME, record["operation_id"])))

    def test_fingerprint_change_between_plan_and_copy_no_replace(self):
        # SCN-57-2: the fingerprint is recomputed from the opened fds at
        # publish time; a change between plan and copy aborts with no
        # quarantine and no replace.
        live, _fingerprint = self._make_unreadable_store()
        db_bytes = self._read_db_bytes()
        backup_root = os.path.join(self._tmp, "BackupMachine57fault3")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        # Use a DIFFERENT fingerprint than the store's actual bytes.
        wrong = "a" * 64
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",
                                accept_unreadable_current=True,
                                expect_current_fingerprint=wrong)
        record = self.run_to_terminal(spec, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("fingerprint_mismatch", record["error"]["code"])
        self.assertEqual(db_bytes, self._read_db_bytes())
        self.assertFalse(os.path.exists(
            os.path.join(self.root, quarantine.QUARANTINE_DIRNAME)))

    def test_unreadable_space_short_fails_preflight_no_replace(self):
        # SCN-57-2: space short for the quarantine copy fails in preflight
        # with the current state untouched (spec #57: 空间不足时不发布恢复库).
        live, fingerprint = self._make_unreadable_store()
        db_bytes = self._read_db_bytes()
        backup_root = os.path.join(self._tmp, "BackupMachine57fault4")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        original_space = restore_operation._space_available
        restore_operation._space_available = lambda root: 0
        try:
            spec = self.build_spec(
                control_client_factory=self.control_factory())
            record = self.create_op(spec, backup, "",
                                    accept_unreadable_current=True,
                                    expect_current_fingerprint=fingerprint)
            record = self.run_to_terminal(spec, record["operation_id"])
        finally:
            restore_operation._space_available = original_space
        self.assertEqual("blocked", record["state"])
        self.assertEqual("insufficient_space", record["error"]["code"])
        self.assertEqual(db_bytes, self._read_db_bytes())
        self.assertFalse(os.path.exists(
            os.path.join(self.root, quarantine.QUARANTINE_DIRNAME)))

    def test_quarantine_list_has_no_raw_text_after_restore(self):
        # SCN-57-5 / BASE-SAFETY: after an unreadable restore, `quarantine
        # list` output contains only identity (no private text).
        live, fingerprint = self._make_unreadable_store()
        backup_root = os.path.join(self._tmp, "BackupMachine57l")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        record = self.create_op(spec, backup, "",
                                accept_unreadable_current=True,
                                expect_current_fingerprint=fingerprint)
        operation_id = record["operation_id"]
        record = self.run_to_terminal(spec, operation_id)
        self.assertEqual("succeeded", record["state"], record["error"])
        from quarantine import list_quarantine
        entries = list_quarantine(self.root, os.geteuid())
        self.assertEqual(1, len(entries))
        self.assertEqual(operation_id, entries[0]["operation_id"])
        text = json.dumps(entries)
        self.assertNotIn(SECRET_PRECEDING, text)
        self.assertNotIn(SECRET_CANDIDATE, text)

    # -- idempotency --------------------------------------------------------

    def test_same_operation_id_same_parameters_idempotent(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachine15")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        spec = self.build_spec(control_client_factory=self.control_factory())
        first = self.create_op(spec, backup, live["store_epoch"],
                               operation_id="op-restore-1")
        again = self.create_op(spec, backup, live["store_epoch"],
                               operation_id="op-restore-1")
        self.assertEqual(first["rev"], again["rev"])

    def test_same_operation_id_different_parameters_conflicts(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        spec = self.build_spec(control_client_factory=self.control_factory())
        self.create_op(spec, backup, live["store_epoch"],
                       operation_id="op-restore-2")
        with self.assertRaises(operations_module.OperationIdConflict):
            self.create_op(spec, backup, "f" * 32,
                           operation_id="op-restore-2")


class RestoreCliTests(RestoreEnv):
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

    def test_cli_restore_discard_current_end_to_end(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachineCli1")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        self.start_control_server()
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--expect-store-epoch", live["store_epoch"], "--json",
            timeout=120)
        self.assertEqual(0, code, stderr)
        payload = json.loads(stdout)
        self.assertEqual("succeeded", payload["state"])
        result = payload["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["fact_operation_succeeded"])
        # The daemon adopted the new store epoch (rebuild queued, not
        # necessarily serving yet).
        health = self.coordinator.health()
        self.assertIn(health["maintenance_state"],
                      ("serving", "catching_up"))
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        self.assertNotEqual(live["store_epoch"],
                            new_identity["store_epoch"])

    def test_cli_restore_backup_current_end_to_end(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachineCli2")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        current_output = os.path.join(self.dest_dir, "cli-current"
                                      ".squirrel-memory-backup")
        self.start_control_server()
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--backup-current", current_output,
            "--yes", "--expect-store-epoch", live["store_epoch"], "--json",
            timeout=120)
        self.assertEqual(0, code, stderr)
        payload = json.loads(stdout)
        result = payload["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["fact_operation_succeeded"])
        self.assertEqual(current_output,
                         result["backup_current_destination"])
        outcome = backup_operation.verify_backup(
            current_output, helper=self.helper)
        self.assertTrue(outcome["valid"], outcome)
        self.assertEqual(live["history_id"], outcome["history_id"])
        self.assertEqual(live["store_epoch"], outcome["store_epoch"])

    def test_cli_interactive_exact_confirmation_succeeds(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachineCli3")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, result = self.make_backup_from_store(backup_root)
        confirmation = "RESTORE %s OVER %s" % (result["backup_id"],
                                               live["store_epoch"])
        self.start_control_server()
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            input_text=confirmation + "\n", timeout=120)
        self.assertEqual(0, code, stderr)
        self.assertIn("restore restored", stdout)

    def test_cli_interactive_mismatch_cancels_with_zero_side_effects(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            input_text="WRONG CONFIRMATION\n", timeout=120)
        self.assertEqual(1, code)
        self.assertIn("confirmation_failed", stderr)
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_cli_noninteractive_requires_both_confirmation_and_epoch(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        # --yes without --expect-store-epoch is a usage error (exit 2).
        code, _, err = self.run_cli("restore", "--from", backup,
                                    "--discard-current", "--yes")
        self.assertEqual(2, code)
        self.assertIn("confirmation_required", err)
        # --expect-store-epoch without --yes is a usage error.
        code, _, err = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--expect-store-epoch", live["store_epoch"])
        self.assertEqual(2, code)
        self.assertIn("confirmation_required", err)

    def test_cli_stale_epoch_noninteractive_is_zero_side_effect(self):
        live = self.make_live_store(seed=True)
        backup, _result = self.make_backup()
        code, _, err = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--expect-store-epoch", "f" * 32)
        self.assertEqual(2, code)
        self.assertIn("store_epoch_mismatch", err)
        self.assertEqual(live["store_epoch"],
                         _meta_value(os.path.join(self.root, "facts.sqlite3"),
                                     "store_epoch"))

    def test_cli_missing_store_fails_closed(self):
        backup_root = os.path.join(self._tmp, "BackupMachineCli4")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        code, _, err = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--expect-store-epoch", "e" * 32)
        self.assertEqual(2, code)
        self.assertIn("store_missing", err)

    def test_cli_json_stdout_is_a_single_parseable_document(self):
        live = self.make_live_store(seed=True)
        backup_root = os.path.join(self._tmp, "BackupMachineCli5")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        self.start_control_server()
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--expect-store-epoch", live["store_epoch"], "--json",
            timeout=120)
        self.assertEqual(0, code, stderr)
        # stdout is exactly one JSON document.
        payload = json.loads(stdout)
        self.assertEqual("succeeded", payload["state"])
        self.assertNotIn(SECRET_PRECEDING, stdout)
        self.assertNotIn(SECRET_CANDIDATE, stdout)
        self.assertNotIn(SECRET_PRECEDING, stderr)
        self.assertNotIn(SECRET_CANDIDATE, stderr)

    # -- #57 CLI end-to-end -------------------------------------------------

    def test_cli_unreadable_restore_end_to_end_with_quarantine(self):
        # SCN-57-1 end to end through the real CLI + control server: the
        # unreadable store is quarantined (as-is, verified) then replaced.
        # The daemon starts on the healthy store and the store is corrupted
        # afterwards (the realistic crash-scene flow).
        live = self.make_live_store(seed=True)
        self.start_control_server()
        db_path = os.path.join(self.root, "facts.sqlite3")
        with open(db_path, "rb+") as stream:
            stream.seek(4096)
            stream.write(b"\xff\xff\xff\xff")
        fingerprint = quarantine.fingerprint_bytes({
            member: open(os.path.join(self.root, member), "rb").read()
            for member in quarantine.QUARANTINE_MEMBERS
            if os.path.exists(os.path.join(self.root, member))})
        backup_root = os.path.join(self._tmp, "BackupMachineCli57a")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--accept-unreadable-current",
            "--expect-current-fingerprint", fingerprint, "--json",
            timeout=120)
        self.assertEqual(0, code, stderr)
        payload = json.loads(stdout)
        self.assertEqual("succeeded", payload["state"])
        result = payload["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["fact_operation_succeeded"])
        self.assertEqual(fingerprint, result["quarantine_fingerprint"])
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        # The quarantine copy exists and is identity-listed.
        rc, out, err = self.run_cli("quarantine", "list", "--json")
        self.assertEqual(0, rc, err)
        listed = json.loads(out)
        self.assertEqual(1, listed["count"])
        self.assertEqual(fingerprint,
                         listed["entries"][0]["fingerprint"])
        # list carries no private text.
        self.assertNotIn(SECRET_PRECEDING, out)
        self.assertNotIn(SECRET_CANDIDATE, out)

    def test_cli_unreadable_fingerprint_mismatch_no_replace(self):
        # SCN-57-2 end to end: a wrong fingerprint aborts with no replace
        # and no quarantine.
        live = self.make_live_store(seed=True)
        self.start_control_server()
        db_path = os.path.join(self.root, "facts.sqlite3")
        with open(db_path, "rb+") as stream:
            stream.seek(4096)
            stream.write(b"\xff\xff\xff\xff")
        db_bytes = open(db_path, "rb").read()
        backup_root = os.path.join(self._tmp, "BackupMachineCli57b")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--accept-unreadable-current",
            "--expect-current-fingerprint", "b" * 64, "--json",
            timeout=120)
        self.assertEqual(1, code)
        self.assertIn("fingerprint_mismatch", stdout + stderr)
        # The current bytes are untouched.
        self.assertEqual(db_bytes, open(db_path, "rb").read())
        rc, out, err = self.run_cli("quarantine", "list", "--json")
        self.assertEqual(0, rc, err)
        self.assertEqual(0, json.loads(out)["count"])

    def test_cli_expect_no_store_end_to_end(self):
        # SCN-57-3 end to end: missing store + --expect-no-store restores
        # without quarantine.
        backup_root = os.path.join(self._tmp, "BackupMachineCli57c")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        self.start_control_server()
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--expect-no-store", "--json",
            timeout=120)
        self.assertEqual(0, code, stderr)
        payload = json.loads(stdout)
        self.assertEqual("succeeded", payload["state"])
        result = payload["result"]
        self.assertEqual("restored", result["outcome"])
        self.assertTrue(result["no_store"])
        new_identity, _empty = self.live_identity()
        self.assertEqual(backup_identity["history_id"],
                         new_identity["history_id"])
        rc, out, err = self.run_cli("quarantine", "list", "--json")
        self.assertEqual(0, rc, err)
        self.assertEqual(0, json.loads(out)["count"])

    def test_cli_expect_no_store_with_present_unreadable_file_refused(self):
        # SCN-57-3: an unreadable present file never satisfies
        # --expect-no-store (end to end).
        live = self.make_live_store(seed=True)
        db_path = os.path.join(self.root, "facts.sqlite3")
        with open(db_path, "rb+") as stream:
            stream.seek(4096)
            stream.write(b"\xff\xff\xff\xff")
        db_bytes = open(db_path, "rb").read()
        backup_root = os.path.join(self._tmp, "BackupMachineCli57d")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, _result = self.make_backup_from_store(backup_root)
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--yes", "--expect-no-store", "--json",
            timeout=120)
        self.assertEqual(2, code)
        self.assertIn("store_present", stdout + stderr)
        # No store was touched.
        self.assertEqual(db_bytes, open(db_path, "rb").read())

    def test_cli_unreadable_interactive_exact_confirmation(self):
        live = self.make_live_store(seed=True)
        self.start_control_server()
        db_path = os.path.join(self.root, "facts.sqlite3")
        with open(db_path, "rb+") as stream:
            stream.seek(4096)
            stream.write(b"\xff\xff\xff\xff")
        fingerprint = quarantine.fingerprint_bytes({
            member: open(os.path.join(self.root, member), "rb").read()
            for member in quarantine.QUARANTINE_MEMBERS
            if os.path.exists(os.path.join(self.root, member))})
        backup_root = os.path.join(self._tmp, "BackupMachineCli57e")
        backup_identity = self.helper.create_empty(backup_root)
        self.seed_backup(backup_root, backup_identity["store_epoch"])
        backup, result = self.make_backup_from_store(backup_root)
        confirmation = "RESTORE %s OVER UNREADABLE %s" % (
            result["backup_id"], fingerprint)
        code, stdout, stderr = self.run_cli(
            "restore", "--from", backup, "--discard-current",
            "--accept-unreadable-current",
            "--expect-current-fingerprint", fingerprint,
            input_text=confirmation + "\n", timeout=120)
        self.assertEqual(0, code, stderr)
        self.assertIn("restore restored", stdout)
        self.assertIn("quarantined current store", stdout)


if __name__ == "__main__":
    unittest.main()
