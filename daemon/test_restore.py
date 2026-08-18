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
import uuid
import zipfile

DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(DAEMON_DIR, "squirrel-semantic-memory")
sys.path.insert(0, DAEMON_DIR)

import backup_operation  # noqa: E402
import cli  # noqa: E402
import operations as operations_module  # noqa: E402
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
                  backup_current=None, discard_current=True):
        store = OperationStore(self.root)
        return create_operation(
            store, self.registry(spec), "restore",
            {"from_path": from_path,
             "backup_current": backup_current,
             "discard_current": discard_current,
             "expect_store_epoch": epoch},
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
        self.reopen_serving = True

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
        return {"ok": True, "state": "serving",
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
        # the reopen state (here: serving).
        self.assertIsNotNone(result["serving_ready"])
        self.assertIn("serving_ready", result)

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


if __name__ == "__main__":
    unittest.main()
