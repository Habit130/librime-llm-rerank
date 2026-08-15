#!/usr/bin/env python3
"""Deterministic tests for the online fact backup and offline verification
(Habit130/squirrel#55, contract AC-55-v1).

Seams under test:

- Step level: `create_operation` + `try_run_pending_steps` with max_steps
  stepping, `fault_hook` crash injection and injectable file-system seams
  (probe medium, ZIP writer, link, final-manifest reader). No wall-clock
  sleep drives any assertion.
- Verify level: `verify_backup` against valid containers, tampered
  containers and a hand-built malicious ZIP corpus (traversal, duplicates,
  symlinks, encryption, sizes, ratios, malformed structures).
- CLI level: the real `squirrel-semantic-memory` entry point in a
  subprocess with a sandboxed environment and the real C++ fact-store
  helper binary, including the insecure-destination confirmation protocol,
  the detached executor, Ctrl-C detachment and single-document JSON stdout.

Test fixtures write fact rows directly with SQL only to simulate a store
populated by the plugin; the implementation under test never interprets
fact rows in Python (that is exactly what the C++ helper owns). Fixture
text is deliberately private-looking so privacy assertions can prove that
no output, manifest, log or error leaks it.
"""

import binascii
import hashlib
import io
import json
import os
import shutil
import signal
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
import zlib
from datetime import datetime, timezone

DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(DAEMON_DIR, "squirrel-semantic-memory")
sys.path.insert(0, DAEMON_DIR)

import backup_operation  # noqa: E402
import cli  # noqa: E402
import clear_operation  # noqa: E402
import operations as operations_module  # noqa: E402
from backup_operation import (  # noqa: E402
    BackupError,
    BackupSpec,
    BACKUP_DIRNAME,
    CONFIRMATION_PREFIX,
    FACTS_MEMBER,
    MANIFEST_MEMBER,
    SENSITIVE_DECLARATION,
    ZIP_MEMBERS,
    _ensure_backup_dir,
    _staging_manifest_path,
    _staging_root,
    _temp_artifact_path,
    read_backup_manifest,
    validate_manifest,
    verify_backup,
)
from clear_operation import (  # noqa: E402
    FactStoreHelper,
)
from operations import (  # noqa: E402
    OperationError,
    OperationStore,
    OperationIdConflict,
    SimulatedCrash,
    cancel_operation,
    create_operation,
    run_pending_steps,
    try_run_pending_steps,
)

TOOL_PATH = os.path.normpath(os.path.join(
    DAEMON_DIR, "..", "..", "..", "build", "plugins", "llm-rerank", "bin",
    "fact_store_tool"))

SECRET_PRECEDING = "秘密上文机密内容"
SECRET_CANDIDATE = "机密候选词"

EVENT_IDS = ("seed-event-a", "seed-event-b")

# The rows below mirror the C++ fact schema only as fixture input; the
# backup implementation never reads or writes fact rows from Python.
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


class BackupEnv(unittest.TestCase):
    """Sandboxed environment shared by all backup tests."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="backup_test_")
        self.root = os.path.join(self._tmp, "SemanticMemory")
        self.dest_dir = os.path.join(self._tmp, "dest")
        os.makedirs(self.dest_dir, mode=0o700)
        self.output = os.path.join(self.dest_dir, "facts.squirrel-memory"
                                                 "-backup")
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
        """Create a live store at the root via the C++ seam and (optionally)
        seed facts with private-looking text."""
        identity = self.helper.create_empty(self.root)
        if seed:
            self.seed_events(identity["store_epoch"])
        return identity

    def seed_events(self, store_epoch, with_retraction=False):
        """Simulate the plugin having recorded facts (fixture only). The
        meta clock is deliberately left untouched so the durable identity
        stays exactly what the C++ seam reported."""
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

    def make_registry(self, **seams):
        """A registry containing one backup.create spec with the given
        seams (which may override the defaults)."""
        registry = operations_module.OperationRegistry()
        defaults = {"helper": self.helper, "program_version": "0.1.0",
                    "euid": os.geteuid()}
        defaults.update(seams)
        registry.register(BackupSpec(self.root, **defaults).build())
        return registry

    def run_operation(self, registry, parameters, operation_id=None,
                      max_steps=None, fault_hook=None, retry_blocked=False):
        """Create and run one backup.create operation to completion."""
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  parameters, operation_id=operation_id)
        record = run_pending_steps(store, registry, record["operation_id"],
                                   max_steps=max_steps,
                                   fault_hook=fault_hook,
                                   retry_blocked=retry_blocked)
        return store, record

    def source_identity(self):
        identity, _empty = self.helper.verify(self.root)
        return identity

    def make_container(self, members=None, manifest_override=None,
                       db_path=None, manifest_payload=None):
        """Build a well-formed two-member container for fixture use."""
        members = members if members is not None else ZIP_MEMBERS
        db = db_path
        if db is None:
            snapshot = os.path.join(self._tmp, "fixture-snapshot.sqlite3")
            self.helper.snapshot(self.root, snapshot)
            db = snapshot
        payload = manifest_payload
        if payload is None:
            stats = self.helper.inspect(db)
            sha = hashlib.sha256()
            with open(db, "rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    sha.update(chunk)
            payload = {
                "manifest_version": 1,
                "backup_format_version": 1,
                "backup_id": str(uuid.uuid4()),
                "history_id": stats["history_id"],
                "store_epoch": stats["store_epoch"],
                "fact_schema_version": stats["fact_schema_version"],
                "event_format_version_min": stats["event_format_version_min"],
                "event_format_version_max": stats["event_format_version_max"],
                "commit_count": stats["commit_count"],
                "event_count": stats["event_count"],
                "candidate_count": stats["candidate_count"],
                "retraction_count": stats["retraction_count"],
                "hlc_high_water": {"physical_ms": stats["hlc_physical_ms"],
                                   "logical": stats["hlc_logical"]},
                "event_hlc_high_water": (
                    {"physical_ms": stats["event_hlc_physical_ms"],
                     "logical": stats["event_hlc_logical"]}
                    if stats["event_hlc_physical_ms"] >= 0 else None),
                "created_at": "2026-08-15T00:00:00+00:00",
                "producer": {"program": "squirrel-semantic-memory",
                             "program_version": "0.1.0",
                             "fact_store_helper": "fact_store_tool"},
                "database_size": os.lstat(db).st_size,
                "database_sha256": sha.hexdigest(),
                "insecure_destination": False,
                "plaintext_sensitive": True,
                "sensitive_declaration": SENSITIVE_DECLARATION,
                "member_names": list(ZIP_MEMBERS),
            }
        if manifest_override:
            payload.update(manifest_override)
        container = os.path.join(self._tmp, "fixture.squirrel-memory-backup")
        with zipfile.ZipFile(container, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for name in members:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o600 | 0x8000) << 16
                if name == FACTS_MEMBER:
                    with open(db, "rb") as stream:
                        archive.writestr(info, stream.read())
                else:
                    archive.writestr(info, json.dumps(
                        payload, ensure_ascii=False).encode("utf-8"))
        return container, payload


# ---------------------------------------------------------------------------
# Step-level: create machine
# ---------------------------------------------------------------------------

class BackupCreateStepsTest(BackupEnv):

    def test_happy_path_creates_exact_two_member_container(self):
        self.make_live_store()
        registry = self.make_registry()
        store, record = self.run_operation(registry, {"output": self.output})
        self.assertEqual("succeeded", record["state"], record)
        result = record["result"]
        self.assertEqual("1", str(result["backup_version"]))
        self.assertTrue(os.path.isfile(self.output))
        st = os.lstat(self.output)
        self.assertEqual(os.geteuid(), st.st_uid)
        self.assertEqual(0o600, stat.S_IMODE(st.st_mode))
        with zipfile.ZipFile(self.output) as archive:
            names = archive.infolist()
            self.assertEqual([FACTS_MEMBER, MANIFEST_MEMBER],
                             [info.filename for info in names])
        # The container verifies.
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"], outcome)
        self.assertEqual(2, outcome["event_count"])
        # Staging was cleaned up.
        self.assertFalse(os.path.exists(_staging_root(self.root,
                                                      record["operation_id"])))
        self.assertFalse(os.path.exists(os.path.join(
            self.root, BACKUP_DIRNAME)))

    def test_empty_store_marks_events_absent(self):
        self.make_live_store(seed=False)
        registry = self.make_registry()
        _store, record = self.run_operation(registry,
                                            {"output": self.output})
        self.assertEqual("succeeded", record["state"])
        result = record["result"]
        self.assertEqual(0, result["event_count"])
        self.assertEqual(0, result["commit_count"])
        self.assertIsNone(result["event_hlc_high_water"])
        manifest = read_backup_manifest(self.output)
        self.assertEqual(-1, manifest["event_format_version_min"])
        self.assertIsNone(manifest["event_hlc_high_water"])

    def test_retracted_store_reports_retraction_count(self):
        self.make_live_store()
        connection = sqlite3.connect(os.path.join(self.root, "facts.sqlite3"))
        connection.execute(_INSERT_RETRACTION, (
            "r" * 32, "c" * 32, 1700000000100, 100, 1700000000100))
        connection.commit()
        connection.close()
        registry = self.make_registry()
        _store, record = self.run_operation(registry, {"output": self.output})
        self.assertEqual("succeeded", record["state"])
        self.assertEqual(1, record["result"]["retraction_count"])
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])
        self.assertEqual(1, outcome["retraction_count"])

    def test_manifest_matches_cpp_snapshot_field_by_field(self):
        self.make_live_store()
        registry = self.make_registry()
        _store, record = self.run_operation(registry, {"output": self.output})
        self.assertEqual("succeeded", record["state"])
        manifest = read_backup_manifest(self.output)
        db_path = os.path.join(self._tmp, "extract.sqlite3")
        with zipfile.ZipFile(self.output) as archive:
            with archive.open(FACTS_MEMBER) as source:
                with open(db_path, "wb") as target:
                    shutil.copyfileobj(source, target)
        stats = self.helper.inspect(db_path)
        for key in ("history_id", "store_epoch", "fact_schema_version",
                    "event_format_version_min", "event_format_version_max",
                    "commit_count", "event_count", "candidate_count",
                    "retraction_count", "hlc_physical_ms", "hlc_logical",
                    "event_hlc_physical_ms", "event_hlc_logical"):
            self.assertEqual(stats[key], manifest_key(manifest, key), key)

    def test_destination_exists_fails_closed(self):
        self.make_live_store()
        with open(self.output, "w") as stream:
            stream.write("occupied")
        os.chmod(self.output, 0o600)
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_exists", record["error"]["code"])
        with open(self.output) as stream:
            self.assertEqual("occupied", stream.read())

    def test_destination_symlink_fails_closed(self):
        self.make_live_store()
        real = os.path.join(self._tmp, "real-target")
        with open(real, "w") as stream:
            stream.write("keep")
        os.symlink(real, self.output)
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_exists", record["error"]["code"])
        with open(real) as stream:
            self.assertEqual("keep", stream.read())

    def test_missing_parent_fails_closed(self):
        self.make_live_store()
        missing = os.path.join(self.dest_dir, "no", "such", "dir",
                               "out.squirrel-memory-backup")
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": missing})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_parent_unsafe",
                         record["error"]["code"])
        self.assertFalse(os.path.exists(missing))

    def test_symlink_parent_fails_closed(self):
        self.make_live_store()
        real_dir = os.path.join(self._tmp, "real-dir")
        os.makedirs(real_dir, mode=0o700)
        link_dir = os.path.join(self._tmp, "link-dir")
        os.symlink(real_dir, link_dir)
        output = os.path.join(link_dir, "out.squirrel-memory-backup")
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_parent_unsafe",
                         record["error"]["code"])

    def test_insecure_medium_refused_without_override(self):
        self.make_live_store()
        registry = self.make_registry(probe_medium=lambda output, op: False)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("insecure_destination", record["error"]["code"])
        self.assertFalse(os.path.exists(self.output))
        # No success-looking artifacts remain and staging is cleaned.
        entries = os.listdir(self.dest_dir)
        self.assertEqual([], entries)
        self.assertFalse(os.path.exists(os.path.join(self.root,
                                                     BACKUP_DIRNAME)))

    def test_insecure_medium_confirmed_marks_manifest(self):
        self.make_live_store()
        registry = self.make_registry(probe_medium=lambda output, op: False)
        _store, record = self.run_operation(
            registry, {"output": self.output, "allow_insecure": True})
        self.assertEqual("succeeded", record["state"], record)
        self.assertTrue(record["result"]["insecure_destination"])
        manifest = read_backup_manifest(self.output)
        self.assertIs(True, manifest["insecure_destination"])
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])
        self.assertIs(True, outcome["insecure_destination"])
        # Owner-only mode is still enforced where the medium allows it.
        st = os.lstat(self.output)
        self.assertEqual(0o600, stat.S_IMODE(st.st_mode))

    def test_override_flag_on_secure_medium_is_not_a_skip(self):
        self.make_live_store()
        registry = self.make_registry()
        _store, record = self.run_operation(
            registry, {"output": self.output, "allow_insecure": True})
        self.assertEqual("succeeded", record["state"], record)
        self.assertFalse(record["result"]["insecure_destination"])
        manifest = read_backup_manifest(self.output)
        self.assertIs(False, manifest["insecure_destination"])

    def test_real_non_0600_temp_succeeds_only_when_confirmed(self):
        """A medium whose temp file is really not 0600 after chmod (the
        filesystem ignores owner-only modes) must fail closed without the
        explicit confirmation and succeed with it, carrying the permanent
        insecure warning. The temp is genuinely created with a non-0600
        mode — not just reported by a probe."""
        self.make_live_store()

        def write_zip_non_0600(temp, snapshot, manifest, parent):
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
            try:
                os.fchmod(fd, 0o600)
                raw = os.fdopen(fd, "wb")
                fd = None
                try:
                    with zipfile.ZipFile(raw, "w",
                                         compression=zipfile.ZIP_DEFLATED
                                         ) as archive:
                        for name in ZIP_MEMBERS:
                            info = zipfile.ZipInfo(name)
                            info.create_system = 3
                            info.external_attr = (0o600 | 0x8000) << 16
                            if name == FACTS_MEMBER:
                                with open(snapshot, "rb") as source:
                                    archive.writestr(info, source.read())
                            else:
                                archive.writestr(
                                    info, json.dumps(
                                        manifest, ensure_ascii=False,
                                        indent=2).encode("utf-8"))
                    raw.flush()
                    os.fsync(raw.fileno())
                finally:
                    raw.close()
            finally:
                if fd is not None:
                    os.close(fd)
            # The medium then fails to honor the 0600 mode: the real on-disk
            # mode is read back as 0644 despite the fchmod.
            os.chmod(temp, 0o644)

        insecure_registry = self.make_registry(
            probe_medium=lambda output, op: False,
            write_zip=write_zip_non_0600)
        # Without the confirmed override the real non-0600 temp fails closed
        # and leaves nothing behind.
        store = OperationStore(self.root)
        record = create_operation(
            store, insecure_registry, "backup.create",
            {"output": self.output, "allow_insecure": False})
        record = run_pending_steps(store, insecure_registry,
                                   record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("insecure_destination", record["error"]["code"])
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual([], os.listdir(self.dest_dir))
        # With the confirmed override the same real non-0600 temp succeeds.
        store = OperationStore(self.root)
        record = create_operation(
            store, insecure_registry, "backup.create",
            {"output": self.output, "allow_insecure": True})
        record = run_pending_steps(store, insecure_registry,
                                   record["operation_id"])
        self.assertEqual("succeeded", record["state"], record)
        self.assertIs(True, record["result"]["insecure_destination"])
        st = os.lstat(self.output)
        self.assertEqual(0o644, stat.S_IMODE(st.st_mode))
        self.assertEqual(os.geteuid(), st.st_uid)
        self.assertTrue(stat.S_ISREG(st.st_mode))
        manifest = read_backup_manifest(self.output)
        self.assertIs(True, manifest["insecure_destination"])
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])
        self.assertIs(True, outcome["insecure_destination"])

    def test_wrong_owner_temp_never_accepted_as_insecure(self):
        """A temp that is a symlink, directory or device (or not regular)
        can never be accepted as an insecure destination; only a regular
        non-0600 file may."""
        self.make_live_store()
        wrong = []

        def write_zip_symlink(temp, snapshot, manifest, parent):
            os.symlink(os.path.join(parent, "does-not-exist"), temp)
            wrong.append(temp)

        registry = self.make_registry(
            probe_medium=lambda output, op: False,
            write_zip=write_zip_symlink)
        store = OperationStore(self.root)
        record = create_operation(
            store, registry, "backup.create",
            {"output": self.output, "allow_insecure": True})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("insecure_destination", record["error"]["code"])
        self.assertFalse(os.path.exists(self.output))
        # The symlink temp was removed again.
        self.assertEqual([], os.listdir(self.dest_dir))

    def test_incomplete_staging_retry_converges(self):
        """A crash between the staging directory creation and the durable
        manifest write leaves an incomplete staging root. A retry with the
        same operation ID must remove it symlink-safely, rebuild, and
        converge to exactly one backup ID and one final destination with no
        staging or temp residue — never a leaked FileExistsError."""
        self.make_live_store()
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        # Simulate the crash residue: staging root exists, manifest was
        # never durably written.
        os.makedirs(_staging_root(self.root, operation_id), mode=0o700)
        self.assertFalse(os.path.exists(_staging_manifest_path(
            self.root, operation_id)))
        record = run_pending_steps(store, registry, operation_id)
        self.assertEqual("succeeded", record["state"], record)
        manifest = read_backup_manifest(self.output)
        self.assertTrue(manifest["backup_id"])
        self.assertEqual(manifest["backup_id"],
                         record["result"]["backup_id"])
        self.assertFalse(os.path.exists(_staging_root(
            self.root, operation_id)))
        self.assertFalse(os.path.exists(os.path.join(
            self.root, BACKUP_DIRNAME)))
        self.assertEqual([f for f in os.listdir(self.dest_dir)
                          if f.startswith(".")], [])

    def test_incomplete_staging_with_symlink_root_converges(self):
        """A hostile or stale symlink at the staging root of this operation
        is unlinked, never followed, and the retry converges."""
        self.make_live_store()
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        _ensure_backup_dir(self.root, os.geteuid())
        target = os.path.join(self._tmp, "symlink-target")
        os.makedirs(target, mode=0o700)
        os.symlink(target, _staging_root(self.root, operation_id))
        record = run_pending_steps(store, registry, operation_id)
        self.assertEqual("succeeded", record["state"], record)
        self.assertTrue(os.path.exists(self.output))
        self.assertTrue(os.path.isdir(target))
        self.assertEqual([], os.listdir(target))

    def test_cleanup_crash_recovers_full_result_from_final(self):
        """A crash after the cleanup step ran but before the operation
        record was persisted deletes the staging manifest. The retry must
        rebuild the identical full result from the durable final container
        — never a generic {'completed': true}."""
        self.make_live_store()
        fixed_now = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        registry = self.make_registry(now=lambda: fixed_now)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        for _ in range(3):
            record = run_pending_steps(store, registry, operation_id,
                                       max_steps=1)
        self.assertEqual("cleanup", record["phase"])
        spec = registry.get("backup.create")
        cleanup_step = spec.steps["cleanup"]
        # The crash window: the cleanup step runs (building the result and
        # deleting staging) and its return value is lost before the record
        # is persisted.
        first = cleanup_step(store.load(operation_id))
        self.assertIn("backup_id", first["result"])
        self.assertNotIn("completed", first["result"])
        # The durable record still shows cleanup (the step's outcome was
        # never persisted) and staging is gone.
        persisted = store.load(operation_id)
        self.assertEqual("cleanup", persisted["phase"])
        self.assertFalse(os.path.exists(_staging_manifest_path(
            self.root, operation_id)))
        # Retry to terminal: the result is recovered from the final
        # container and is field-for-field identical.
        record = run_pending_steps(store, registry, operation_id)
        self.assertEqual("succeeded", record["state"])
        self.assertEqual(first["result"], record["result"])
        self.assertEqual(record["result"]["destination"], self.output)
        for key in ("backup_id", "history_id", "store_epoch",
                    "fact_schema_version", "event_format_version_min",
                    "event_format_version_max", "commit_count", "event_count",
                    "candidate_count", "retraction_count", "hlc_high_water",
                    "event_hlc_high_water", "created_at", "producer",
                    "database_size", "database_sha256",
                    "insecure_destination", "plaintext_sensitive"):
            self.assertIn(key, record["result"])
        self.assertEqual("succeeded", record["state"])

    def test_cancel_before_publish_cleans_and_goes_cancelled(self):
        self.make_live_store()
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        # Run preflight only, then cancel while still in staging.
        run_pending_steps(store, registry, record["operation_id"],
                          max_steps=1)
        cancel_operation(store, record["operation_id"])
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("cancelled", record["state"])
        self.assertFalse(os.path.exists(self.output))
        self.assertFalse(os.path.exists(_staging_root(
            self.root, record["operation_id"])))
        self.assertEqual([], os.listdir(self.dest_dir))

    def test_cancel_after_publish_is_uncancellable(self):
        self.make_live_store()
        registry = self.make_registry()
        store, record = self.run_operation(registry, {"output": self.output})
        self.assertEqual("succeeded", record["state"])
        _record, disposition = cancel_operation(store,
                                                record["operation_id"])
        # A finished operation is terminal; the cancel is refused (it can
        # no longer be requested), never overwriting the outcome.
        self.assertEqual("terminal", disposition)
        self.assertTrue(os.path.exists(self.output))

    def test_same_operation_reuses_backup_id_without_resnapshot(self):
        self.make_live_store()
        snapshots = []
        helper = CountingHelper(self.helper, snapshots)
        registry = self.make_registry(helper=helper)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        run_pending_steps(store, registry, operation_id)
        run_pending_steps(store, registry, operation_id)
        record = run_pending_steps(store, registry, operation_id)
        self.assertEqual("succeeded", record["state"])
        # Staging was reached exactly once (one snapshot, one manifest).
        self.assertEqual(1, len(snapshots))
        self.assertEqual(1, record["result"]["backup_version"])

    def test_operation_id_conflict_on_different_parameters(self):
        self.make_live_store()
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        with self.assertRaises(OperationIdConflict):
            create_operation(store, registry, "backup.create",
                             {"output": os.path.join(
                                 self.dest_dir, "other.squirrel-memory"
                                                "-backup")},
                             operation_id=operation_id)

    def test_crash_before_publish_resumes_idempotently(self):
        self.make_live_store()
        registry = self.make_registry()
        # Each crash point gets its own operation and destination, so every
        # combination can actually reach its target step.
        combinations = []
        for phase in ("preflight", "staging", "publishing", "cleanup"):
            for point in ("before_step", "after_step"):
                combinations.append((phase, point))
        phase_order = ("preflight", "staging", "publishing", "cleanup")
        for index, (phase, point) in enumerate(combinations):
            output = os.path.join(self.dest_dir, "crash%d.squirrel-memory"
                                                  "-backup" % index)
            store = OperationStore(self.root)
            record = create_operation(store, registry, "backup.create",
                                      {"output": output})
            operation_id = record["operation_id"]
            # Advance through the phases before the target one.
            for _ in range(phase_order.index(phase)):
                run_pending_steps(store, registry, operation_id,
                                  max_steps=1)
            with self.assertRaises(SimulatedCrash, msg=(phase, point)):
                run_pending_steps(
                    store, registry, operation_id, max_steps=1,
                    fault_hook=lambda p, i, pt,
                    phase=phase, point=point: (
                        _crash_at(p, i, pt, phase, point)))
            record = run_pending_steps(store, registry, operation_id)
            self.assertEqual("succeeded", record["state"],
                             (phase, point, record.get("error")))
            self.assertTrue(os.path.exists(output), (phase, point))
            outcome = verify_backup(output, helper=self.helper)
            self.assertTrue(outcome["valid"], (phase, point))

    def test_crash_after_publication_keeps_single_final(self):
        self.make_live_store()
        registry = self.make_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        run_pending_steps(store, registry, operation_id, max_steps=1)
        run_pending_steps(store, registry, operation_id, max_steps=1)
        # Crash right after the publishing step ran (link done, record not
        # yet persisted).
        with self.assertRaises(SimulatedCrash):
            run_pending_steps(
                store, registry, operation_id, max_steps=1,
                fault_hook=lambda p, i, pt: _crash_at(
                    p, i, pt, "publishing", "after_step"))
        record = run_pending_steps(store, registry, operation_id)
        self.assertEqual("succeeded", record["state"])
        self.assertTrue(os.path.exists(self.output))
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])
        # Exactly one final target, no leftover temp in the parent.
        self.assertEqual(1, len(os.listdir(self.dest_dir)))

    def test_different_operation_same_target_fails_closed(self):
        self.make_live_store()
        registry = self.make_registry()
        store, record = self.run_operation(registry, {"output": self.output})
        self.assertEqual("succeeded", record["state"])
        first = read_backup_manifest(self.output)["backup_id"]
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_exists", record["error"]["code"])
        self.assertEqual(first, read_backup_manifest(self.output)[
            "backup_id"])

    def test_zip_write_failure_leaves_no_target(self):
        self.make_live_store()

        def fail_zip(temp, snapshot, manifest, parent):
            raise backup_operation.OperationFailed(
                "staging_write_failed", phase="publishing", retryable=True)

        registry = self.make_registry(write_zip=fail_zip)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("failed", record["state"])
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual([], os.listdir(self.dest_dir))

    def test_failure_after_publish_keeps_final(self):
        self.make_live_store()

        def fail_after_link(temp, output):
            # The final was published, then a crash-equivalent failure hits
            # before the record is persisted.
            os.link(temp, output)
            raise backup_operation.OperationFailed(
                "publish_failed", phase="publishing", retryable=True)

        registry = self.make_registry(link=fail_after_link)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("failed", record["state"])
        self.assertTrue(os.path.exists(self.output))
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])

    def test_publication_race_is_never_overwritten(self):
        self.make_live_store()

        def race_link(temp, output):
            # A concurrent create won the destination first.
            raise OSError(17, "File exists")

        registry = self.make_registry(link=race_link)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", record["state"])
        self.assertEqual("destination_exists", record["error"]["code"])
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual([], os.listdir(self.dest_dir))

    def test_faults_leave_source_untouched(self):
        self.make_live_store()
        before = self.source_identity()
        before_db = os.lstat(os.path.join(self.root, "facts.sqlite3"))
        faults = []

        def fail_helper(*args, **kwargs):
            raise backup_operation.OperationFailed(
                "fact_store_helper_failed", phase="staging", retryable=True)

        # Snapshot failure at every possible point must not change the
        # source store.
        helper = CountingHelper(self.helper, [], fail_snapshot=True)
        registry = self.make_registry(helper=helper)
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        record = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("failed", record["state"])
        after = self.source_identity()
        after_db = os.lstat(os.path.join(self.root, "facts.sqlite3"))
        self.assertEqual(before["store_epoch"], after["store_epoch"])
        self.assertEqual(before["history_id"], after["history_id"])
        self.assertEqual(before["hlc_physical_ms"], after["hlc_physical_ms"])
        self.assertEqual(before["hlc_logical"], after["hlc_logical"])
        self.assertEqual(before_db.st_size, after_db.st_size)
        self.assertFalse(os.path.exists(self.output))

    def test_operation_show_wait_cancel_support_backup_type(self):
        self.make_live_store()
        registry = self.make_registry()
        store, record = self.run_operation(registry, {"output": self.output})
        self.assertEqual("succeeded", record["state"])
        shown = store.load(record["operation_id"])
        self.assertEqual("backup.create", shown["type"])
        self.assertEqual("succeeded", shown["state"])
        self.assertEqual("cleanup", shown["phase"])


# ---------------------------------------------------------------------------
# Verify: offline validation and malicious containers
# ---------------------------------------------------------------------------

class BackupVerifyTest(BackupEnv):

    def setUp(self):
        super().setUp()
        self.make_live_store()

    def test_valid_container_reports_full_fields(self):
        container, payload = self.make_container()
        outcome = verify_backup(container, helper=self.helper)
        self.assertTrue(outcome["valid"])
        self.assertEqual(payload["backup_id"], outcome["backup_id"])
        self.assertEqual(payload["history_id"], outcome["history_id"])
        self.assertEqual(payload["store_epoch"], outcome["store_epoch"])
        self.assertEqual(2, outcome["event_count"])
        self.assertEqual(1, outcome["commit_count"])
        self.assertEqual(4, outcome["candidate_count"])
        self.assertEqual(0, outcome["retraction_count"])
        self.assertEqual(payload["database_sha256"],
                         outcome["database_sha256"])
        self.assertEqual(payload["database_size"],
                         outcome["database_size"])
        self.assertIs(False, outcome["insecure_destination"])
        self.assertIs(True, outcome["plaintext_sensitive"])

    def test_verify_never_touches_live_state(self):
        container, _payload = self.make_container()
        live_root = self.root
        outcome = verify_backup(container, helper=self.helper)
        self.assertTrue(outcome["valid"])
        # The live root still exists unchanged and no operation store or
        # backup staging was created anywhere.
        self.assertTrue(os.path.isdir(live_root))
        self.assertFalse(os.path.exists(os.path.join(
            live_root, "operations")))
        self.assertFalse(os.path.exists(os.path.join(live_root,
                                                     BACKUP_DIRNAME)))

    def test_verify_with_no_root_and_no_sockets(self):
        # Point every daemon/socket env at nonexistent paths and run verify
        # in a fresh HOME-like environment: it must still succeed offline.
        container, _payload = self.make_container()
        env = dict(os.environ)
        env["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = os.path.join(
            self._tmp, "no-such-root")
        env["SQUIRREL_DAEMON_SOCKET"] = os.path.join(self._tmp, "no.sock")
        env["SQUIRREL_DAEMON_CONTROL_SOCKET"] = os.path.join(
            self._tmp, "no-control.sock")
        result = subprocess.run(
            [sys.executable, ENTRY, "backup", "verify", "--json", container],
            capture_output=True, text=True, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(os.path.exists(os.path.join(
            self._tmp, "no-such-root")))

    def test_verify_cleans_temp_directory(self):
        container, _payload = self.make_container()
        created = []

        original = tempfile.mkdtemp
        def spy(*args, **kwargs):
            path = original(*args, **kwargs)
            created.append(path)
            return path
        tempfile.mkdtemp = spy
        try:
            outcome = verify_backup(container, helper=self.helper)
        finally:
            tempfile.mkdtemp = original
        self.assertTrue(outcome["valid"])
        self.assertEqual(1, len(created))
        self.assertFalse(os.path.exists(created[0]))

    def test_tampered_db_fails_checksum(self):
        container, payload = self.make_container()
        with zipfile.ZipFile(container, "r") as archive:
            members = {info.filename: info for info in archive.infolist()}
            with archive.open(FACTS_MEMBER) as source:
                data = bytearray(source.read())
            with archive.open(MANIFEST_MEMBER) as source:
                manifest_bytes = source.read()
        data[4096] ^= 0xFF
        rewritten = os.path.join(self._tmp, "tampered.squirrel-memory-backup")
        with zipfile.ZipFile(rewritten, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for name, info in members.items():
                zinfo = zipfile.ZipInfo(name)
                zinfo.create_system = 3
                zinfo.external_attr = (0o600 | 0x8000) << 16
                archive.writestr(
                    zinfo, bytes(data) if name == FACTS_MEMBER else
                    manifest_bytes)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(rewritten, helper=self.helper)
        self.assertEqual("checksum_mismatch", ctx.exception.code)

    def test_tampered_manifest_size_fails(self):
        container, payload = self.make_container()
        payload["database_size"] += 1
        self._rewrite_manifest(container, payload)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(container, helper=self.helper)
        self.assertEqual("size_mismatch", ctx.exception.code)

    def test_tampered_manifest_counts_fail(self):
        container, payload = self.make_container()
        payload["event_count"] += 1
        self._rewrite_manifest(container, payload)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(container, helper=self.helper)
        self.assertEqual("backup_mismatch", ctx.exception.code)

    def test_tampered_manifest_identity_fails(self):
        container, payload = self.make_container()
        payload["history_id"] = "x" * 32
        self._rewrite_manifest(container, payload)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(container, helper=self.helper)
        self.assertEqual("backup_mismatch", ctx.exception.code)

    def _rewrite_manifest(self, container, payload):
        with zipfile.ZipFile(container, "r") as archive:
            db_data = archive.read(FACTS_MEMBER)
        with zipfile.ZipFile(container, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            zinfo = zipfile.ZipInfo(FACTS_MEMBER)
            zinfo.create_system = 3
            zinfo.external_attr = (0o600 | 0x8000) << 16
            archive.writestr(zinfo, db_data)
            zinfo = zipfile.ZipInfo(MANIFEST_MEMBER)
            zinfo.create_system = 3
            zinfo.external_attr = (0o600 | 0x8000) << 16
            archive.writestr(zinfo, json.dumps(
                payload, ensure_ascii=False).encode("utf-8"))

    def test_corrupt_db_fails(self):
        container, payload = self.make_container()
        with zipfile.ZipFile(container, "r") as archive:
            data = bytearray(archive.read(FACTS_MEMBER))
        data[4096] ^= 0xFF
        # Re-hash the corrupted database so the checksum matches; the
        # database integrity check must still reject it.
        corrupted = hashlib.sha256(bytes(data)).hexdigest()
        payload["database_sha256"] = corrupted
        rewritten = os.path.join(self._tmp, "corrupt.squirrel-memory-backup")
        with zipfile.ZipFile(rewritten, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            zinfo = zipfile.ZipInfo(FACTS_MEMBER)
            zinfo.create_system = 3
            zinfo.external_attr = (0o600 | 0x8000) << 16
            archive.writestr(zinfo, bytes(data))
            zinfo = zipfile.ZipInfo(MANIFEST_MEMBER)
            zinfo.create_system = 3
            zinfo.external_attr = (0o600 | 0x8000) << 16
            archive.writestr(zinfo, json.dumps(
                payload, ensure_ascii=False).encode("utf-8"))
        with self.assertRaises(BackupError) as ctx:
            verify_backup(rewritten, helper=self.helper)
        self.assertEqual("fact_store_invalid", ctx.exception.code)

    def test_wal_dependent_db_fails(self):
        wal_db = os.path.join(self._tmp, "wal.sqlite3")
        connection = sqlite3.connect(wal_db)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE t(x)")
        connection.execute("INSERT INTO t VALUES(1)")
        connection.commit()
        connection.close()
        # A WAL database whose main file alone is not complete must be
        # rejected even when its manifest claims otherwise. The manifest is
        # built from the file's own bytes so only the WAL dependency can
        # fail it.
        sha = hashlib.sha256()
        with open(wal_db, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                sha.update(chunk)
        payload = {
            "manifest_version": 1, "backup_format_version": 1,
            "backup_id": str(uuid.uuid4()),
            "history_id": "h" * 32, "store_epoch": "e" * 32,
            "fact_schema_version": 1,
            "event_format_version_min": 1,
            "event_format_version_max": 1,
            "commit_count": 1, "event_count": 0, "candidate_count": 0,
            "retraction_count": 0,
            "hlc_high_water": {"physical_ms": 1, "logical": 0},
            "event_hlc_high_water": None,
            "created_at": "2026-08-15T00:00:00+00:00",
            "producer": {"program": "squirrel-semantic-memory",
                         "program_version": "0.1.0",
                         "fact_store_helper": "fact_store_tool"},
            "database_size": os.lstat(wal_db).st_size,
            "database_sha256": sha.hexdigest(),
            "insecure_destination": False,
            "plaintext_sensitive": True,
            "sensitive_declaration": SENSITIVE_DECLARATION,
            "member_names": list(ZIP_MEMBERS),
        }
        container = os.path.join(self._tmp, "wal.squirrel-memory-backup")
        with zipfile.ZipFile(container, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in ((FACTS_MEMBER, open(wal_db, "rb").read()),
                               (MANIFEST_MEMBER, json.dumps(
                                   payload, ensure_ascii=False).encode(
                                       "utf-8"))):
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o600 | 0x8000) << 16
                archive.writestr(info, data)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(container, helper=self.helper)
        self.assertEqual("fact_store_invalid", ctx.exception.code)

    def test_missing_backup_fails(self):
        missing = os.path.join(self._tmp, "missing.squirrel-memory-backup")
        with self.assertRaises(BackupError) as ctx:
            verify_backup(missing, helper=self.helper)
        self.assertEqual("backup_not_found", ctx.exception.code)

    def test_symlink_backup_fails(self):
        container, _payload = self.make_container()
        link = os.path.join(self._tmp, "link.squirrel-memory-backup")
        os.symlink(container, link)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(link, helper=self.helper)
        self.assertEqual("backup_symlink", ctx.exception.code)

    def test_directory_backup_fails(self):
        with self.assertRaises(BackupError) as ctx:
            verify_backup(self.dest_dir, helper=self.helper)
        self.assertEqual("backup_not_regular", ctx.exception.code)


class MaliciousContainerTest(BackupEnv):
    """Hand-built malicious containers (spec #55 SCN-55-10): every rejection
    must happen before any member content is trusted, and no failure may
    modify application state."""

    def setUp(self):
        super().setUp()
        self.make_live_store()
        self._fixture_snapshot_path = os.path.join(
            self._tmp, "fixture-snapshot.sqlite3")

    def _ensure_snapshot(self):
        """Snapshot once per test; later calls reuse the file (the live
        store is not modified between them)."""
        if not os.path.exists(self._fixture_snapshot_path):
            self.helper.snapshot(self.root, self._fixture_snapshot_path)
        return self._fixture_snapshot_path

    def _snapshot_bytes(self):
        with open(self._ensure_snapshot(), "rb") as stream:
            return stream.read()

    def _valid_manifest_bytes(self):
        snapshot = self._ensure_snapshot()
        stats = self.helper.inspect(snapshot)
        sha = hashlib.sha256()
        with open(snapshot, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                sha.update(chunk)
        payload = {
            "manifest_version": 1, "backup_format_version": 1,
            "backup_id": str(uuid.uuid4()),
            "history_id": stats["history_id"],
            "store_epoch": stats["store_epoch"],
            "fact_schema_version": 1,
            "event_format_version_min": stats["event_format_version_min"],
            "event_format_version_max": stats["event_format_version_max"],
            "commit_count": stats["commit_count"],
            "event_count": stats["event_count"],
            "candidate_count": stats["candidate_count"],
            "retraction_count": stats["retraction_count"],
            "hlc_high_water": {"physical_ms": stats["hlc_physical_ms"],
                               "logical": stats["hlc_logical"]},
            "event_hlc_high_water": (
                {"physical_ms": stats["event_hlc_physical_ms"],
                 "logical": stats["event_hlc_logical"]}
                if stats["event_hlc_physical_ms"] >= 0 else None),
            "created_at": "2026-08-15T00:00:00+00:00",
            "producer": {"program": "squirrel-semantic-memory",
                         "program_version": "0.1.0",
                         "fact_store_helper": "fact_store_tool"},
            "database_size": os.lstat(snapshot).st_size,
            "database_sha256": sha.hexdigest(),
            "insecure_destination": False,
            "plaintext_sensitive": True,
            "sensitive_declaration": SENSITIVE_DECLARATION,
            "member_names": list(ZIP_MEMBERS),
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _assert_rejected(self, path, expected_codes):
        try:
            outcome = verify_backup(path, helper=self.helper)
        except BackupError as error:
            self.assertIn(error.code, expected_codes, error.code)
            return
        self.fail("expected rejection, got %r" % (outcome,))

    def _write_container(self, members):
        """members: list of (name, data, extra_attrs, compress_type) tuples.
        Uses the real zipfile writer."""
        path = os.path.join(self._tmp, "malicious.squirrel-memory-backup")
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o600 | 0x8000) << 16
                archive.writestr(info, data)
        return path

    def test_extra_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), (MANIFEST_MEMBER, manifest),
            ("extra.sqlite3", b"stray")])
        self._assert_rejected(path, ("zip_member_set_invalid",
                                     "zip_member_name_invalid"))

    def test_missing_member_rejected(self):
        db = self._snapshot_bytes()
        path = self._write_container([(FACTS_MEMBER, db)])
        self._assert_rejected(path, ("zip_member_set_invalid",))

    def test_directory_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), ("manifest.json/", manifest)])
        self._assert_rejected(path, ("zip_member_type_invalid",))

    def test_absolute_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), ("/etc/passwd", manifest)])
        self._assert_rejected(path, ("zip_member_name_invalid",))

    def test_traversal_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), ("../manifest.json", manifest)])
        self._assert_rejected(path, ("zip_member_name_invalid",))

    def test_backslash_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), ("..\\manifest.json", manifest)])
        self._assert_rejected(path, ("zip_member_name_invalid",))

    def test_unicode_lookalike_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), ("manifest\u2028.json", manifest)])
        self._assert_rejected(path, ("zip_member_name_invalid",))

    def test_duplicate_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._write_container([
            (FACTS_MEMBER, db), (FACTS_MEMBER, db),
            (MANIFEST_MEMBER, manifest)])
        self._assert_rejected(path, ("zip_member_duplicate",
                                     "zip_member_set_invalid"))

    def test_symlink_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = os.path.join(self._tmp, "symlink.squirrel-memory-backup")
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in ((FACTS_MEMBER, db), (MANIFEST_MEMBER,
                                                    manifest)):
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = ((0o120600) << 16)  # symlink 0600
                archive.writestr(info, data)
        self._assert_rejected(path, ("zip_member_type_invalid",))

    def test_encrypted_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._raw_zip(
            [(FACTS_MEMBER, db, {"flag_bits": 0x1}),
             (MANIFEST_MEMBER, manifest, {"flag_bits": 0x1})])
        self._assert_rejected(path, ("zip_member_encrypted",))

    def test_unsupported_compression_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = os.path.join(self._tmp, "bzip.squirrel-memory-backup")
        with zipfile.ZipFile(path, "w",
                             compression=zipfile.ZIP_BZIP2) as archive:
            for name, data in ((FACTS_MEMBER, db), (MANIFEST_MEMBER,
                                                    manifest)):
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o600 | 0x8000) << 16
                info.compress_type = zipfile.ZIP_BZIP2
                archive.writestr(info, data)
        # zipfile re-interprets unsupported methods as STORED, so the
        # decompressed bytes fail CRC; either rejection is acceptable.
        self._assert_rejected(path, ("zip_compression_unsupported",
                                     "zip_malformed"))

    def test_oversized_member_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._raw_zip(
            [(FACTS_MEMBER, db, {"file_size": 3 * 1024 ** 3}),
             (MANIFEST_MEMBER, manifest, {})])
        self._assert_rejected(path, ("zip_size_limit",))

    def test_excessive_ratio_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._raw_zip(
            [(FACTS_MEMBER, db, {"file_size": 2000 * 1024 ** 2}),
             (MANIFEST_MEMBER, manifest, {})])
        self._assert_rejected(path, ("zip_ratio_limit",))

    def test_ratio_exact_boundary_1000_allows_into_later_checks(self):
        """file_size == 1000 * compress_size is exactly at the limit and
        must pass the ratio gate into the later validation stages (the
        forged sizes then fail those stages, but not with zip_ratio_limit).
        """
        from backup_operation import parse_zip_structure
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        compress = max(1, len(db) // 1000)
        path = self._raw_zip(
            [(FACTS_MEMBER, db, {"file_size": 1000 * compress,
                                 "compress_size": compress}),
             (MANIFEST_MEMBER, manifest, {})])
        structure = parse_zip_structure(path)
        self.assertEqual(2, len(structure))
        try:
            outcome = verify_backup(path, helper=self.helper)
        except BackupError as error:
            # The boundary itself passed; a later stage rejects the forged
            # sizes, and that later stage must not be the ratio gate.
            self.assertNotEqual("zip_ratio_limit", error.code)
            return
        self.assertFalse(outcome["valid"])

    def test_ratio_exact_boundary_1001_rejected(self):
        """file_size == 1000 * compress_size + 1 exceeds the limit and is
        rejected with zip_ratio_limit."""
        from backup_operation import parse_zip_structure, MAX_COMPRESSION_RATIO
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        compress = max(1, len(db) // 1000)
        path = self._raw_zip(
            [(FACTS_MEMBER, db, {"file_size": MAX_COMPRESSION_RATIO
                                 * compress + 1,
                                 "compress_size": compress}),
             (MANIFEST_MEMBER, manifest, {})])
        with self.assertRaises(BackupError) as ctx:
            parse_zip_structure(path)
        self.assertEqual("zip_ratio_limit", ctx.exception.code)

    def test_ratio_zero_compress_size_rejected(self):
        """A member with zero compressed size but nonzero data has an
        infinite ratio and is safely rejected."""
        from backup_operation import parse_zip_structure
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        path = self._raw_zip(
            [(FACTS_MEMBER, db, {"file_size": len(db),
                                 "compress_size": 0}),
             (MANIFEST_MEMBER, manifest, {})])
        with self.assertRaises(BackupError) as ctx:
            parse_zip_structure(path)
        self.assertEqual("zip_ratio_limit", ctx.exception.code)

    def test_malformed_zip_rejected(self):
        path = os.path.join(self._tmp, "truncated.squirrel-memory-backup")
        with open(path, "wb") as stream:
            stream.write(b"PK\x03\x04garbage not a real zip file at all")
        self._assert_rejected(path, ("zip_malformed", "backup_unreadable"))

    def test_manifest_duplicate_key_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        duplicated = b'{"manifest_version":1,' + manifest[
            manifest.find(b"{") + 1:]
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, duplicated)])
        self._assert_rejected(path, ("manifest_malformed",
                                     "manifest_invalid"))

    def test_manifest_bad_json_rejected(self):
        db = self._snapshot_bytes()
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, b"{not json")])
        self._assert_rejected(path, ("manifest_malformed",))

    def test_manifest_unsupported_version_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        modified = manifest.replace(b'"backup_format_version": 1',
                                    b'"backup_format_version": 2')
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, modified)])
        self._assert_rejected(path, ("manifest_version_unsupported",))

    def test_manifest_missing_field_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        modified = manifest.replace(b'"database_size":', b'"database_sizes":')
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, modified)])
        self._assert_rejected(path, ("manifest_invalid",))

    def test_manifest_bad_type_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        modified = manifest.replace(b'"event_count": 2', b'"event_count": "2"')
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, modified)])
        self._assert_rejected(path, ("manifest_invalid",))

    def test_manifest_bad_sha_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        modified = manifest.replace(b'"database_sha256": "',
                                    b'"database_sha256": "zz')
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, modified)])
        self._assert_rejected(path, ("manifest_invalid",))

    def test_manifest_bad_members_rejected(self):
        db = self._snapshot_bytes()
        manifest = self._valid_manifest_bytes()
        modified = manifest.replace(b'"member_names": ["facts.sqlite3",'
                                    b' "manifest.json"]',
                                    b'"member_names": ["facts.sqlite3"]')
        path = self._write_container([(FACTS_MEMBER, db),
                                      (MANIFEST_MEMBER, modified)])
        self._assert_rejected(path, ("manifest_invalid",))

    def _raw_zip(self, members):
        """Hand-build a ZIP with forged central-directory fields (sizes,
        flags) that the real writer cannot express."""
        local = b""
        central = b""
        offsets = []
        index = 0
        for name, data, attrs in members:
            name_bytes = name.encode("utf-8")
            file_size = attrs.get("file_size", len(data))
            compress_size = attrs.get("compress_size", len(data))
            method = attrs.get("method", 0)
            crc = binascii.crc32(data) & 0xFFFFFFFF
            flag_bits = attrs.get("flag_bits", 0)
            header = struct.pack(
                "<IHHHHHIIIHH", 0x04034b50, 20, flag_bits, method, 0, 0,
                crc, compress_size, file_size, len(name_bytes), 0)
            local += header + name_bytes + data
            offsets.append((index, name_bytes, crc, compress_size,
                            file_size, method, flag_bits))
            index += 1
        for (index, name_bytes, crc, compress_size, file_size, method,
             flag_bits) in offsets:
            external_attr = (0o600 | 0x8000) << 16
            central += struct.pack(
                "<IHHHHHHIIIHHHHHII", 0x02014b50, 20, 20, flag_bits,
                method, 0, 0, crc, compress_size, file_size,
                len(name_bytes), 0, 0, 0, 0, external_attr, offsets[index][0])
            central += name_bytes
        count = len(members)
        central_size = len(central)
        offset = len(local)
        eocd = struct.pack("<IHHHHIIH", 0x06054b50, 0, 0, count, count,
                           central_size, offset, 0)
        path = os.path.join(self._tmp, "raw.squirrel-memory-backup")
        with open(path, "wb") as stream:
            stream.write(local + central + eocd)
        return path


# ---------------------------------------------------------------------------
# CLI level
# ---------------------------------------------------------------------------

class BackupCliTest(BackupEnv):

    def run_cli(self, argv, stdin=None, env=None):
        base = dict(os.environ)
        if env:
            base.update(env)
        return subprocess.run(
            [sys.executable, ENTRY] + argv,
            capture_output=True, text=True, input=stdin, env=base,
            timeout=180)

    def test_cli_create_json_single_document(self):
        self.make_live_store()
        result = self.run_cli(
            ["backup", "create", "--json", "--output", self.output])
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("succeeded", payload["state"])
        self.assertEqual("backup.create", payload["type"])
        self.assertTrue(os.path.exists(self.output))
        # Started envelope on stderr, terminal record on stdout.
        self.assertIn("backup.create", result.stderr)
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])

    def test_cli_create_human_output(self):
        self.make_live_store()
        result = self.run_cli(
            ["backup", "create", "--output", self.output])
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertIn("backup create started: operation", result.stdout)
        self.assertIn("sha256:", result.stdout)
        self.assertIn("backup ", result.stdout)
        self.assertNotIn(SECRET_PRECEDING, result.stdout)
        self.assertNotIn(SECRET_CANDIDATE, result.stdout)

    def test_cli_verify_human_and_json(self):
        self.make_live_store()
        container, _payload = self.make_container()
        human = self.run_cli(["backup", "verify", container])
        self.assertEqual(0, human.returncode, human.stderr + human.stdout)
        self.assertIn("backup: valid", human.stdout)
        self.assertNotIn(SECRET_PRECEDING, human.stdout)
        self.assertNotIn(SECRET_CANDIDATE, human.stdout)
        json_result = self.run_cli(["backup", "verify", "--json", container])
        self.assertEqual(0, json_result.returncode, json_result.stderr)
        payload = json.loads(json_result.stdout)
        self.assertTrue(payload["valid"])

    def test_cli_verify_invalid_exit_1(self):
        self.make_live_store()
        container, _payload = self.make_container()
        self._rewrite_manifest(container, {"event_count": 999})
        result = self.run_cli(["backup", "verify", container])
        self.assertEqual(1, result.returncode)
        self.assertIn("backup: invalid", result.stdout + result.stderr)
        self.assertIn("backup_mismatch", result.stdout + result.stderr)
        json_result = self.run_cli(
            ["backup", "verify", "--json", container])
        self.assertEqual(1, json_result.returncode)
        payload = json.loads(json_result.stdout)
        self.assertFalse(payload["valid"])
        self.assertEqual("backup_mismatch", payload["error"]["code"])

    def _rewrite_manifest(self, container, overrides):
        with zipfile.ZipFile(container, "r") as archive:
            db_data = archive.read(FACTS_MEMBER)
            manifest = json.loads(archive.read(MANIFEST_MEMBER))
        manifest.update(overrides)
        with zipfile.ZipFile(container, "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in ((FACTS_MEMBER, db_data),
                               (MANIFEST_MEMBER, json.dumps(
                                   manifest, ensure_ascii=False).encode(
                                       "utf-8"))):
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o600 | 0x8000) << 16
                archive.writestr(info, data)

    def test_cli_insecure_confirmation_exact_string(self):
        self.make_live_store()
        confirmation = CONFIRMATION_PREFIX + self.output
        result = self.run_cli(
            ["backup", "create", "--allow-insecure-destination",
             "--output", self.output], stdin=confirmation + "\n")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        manifest = read_backup_manifest(self.output)
        self.assertIs(False, manifest["insecure_destination"])
        self.assertIn("ALLOW INSECURE BACKUP AT", result.stderr)

    def test_cli_insecure_confirmation_wrong_string(self):
        self.make_live_store()
        result = self.run_cli(
            ["backup", "create", "--allow-insecure-destination",
             "--output", self.output],
            stdin=CONFIRMATION_PREFIX + "different\n")
        self.assertEqual(1, result.returncode)
        self.assertIn("confirmation_failed", result.stderr)
        self.assertFalse(os.path.exists(self.output))
        self.assertFalse(os.path.exists(os.path.join(self.root,
                                                     "operations")))

    def test_cli_insecure_confirmation_case_sensitive(self):
        self.make_live_store()
        result = self.run_cli(
            ["backup", "create", "--allow-insecure-destination",
             "--output", self.output],
            stdin=(CONFIRMATION_PREFIX + self.output).lower() + "\n")
        self.assertEqual(1, result.returncode)
        self.assertFalse(os.path.exists(self.output))

    def test_cli_insecure_confirmation_eof_cancels(self):
        self.make_live_store()
        result = self.run_cli(
            ["backup", "create", "--allow-insecure-destination",
             "--output", self.output], stdin="")
        self.assertEqual(1, result.returncode)
        self.assertIn("confirmation_failed", result.stderr)
        self.assertFalse(os.path.exists(self.output))

    def test_cli_create_existing_target_reports_destination_exists(self):
        self.make_live_store()
        with open(self.output, "w") as stream:
            stream.write("occupied")
        result = self.run_cli(["backup", "create", "--output", self.output])
        self.assertEqual(1, result.returncode)
        # Human-mode failures report on stdout (the same convention as
        # `clear`); the stable code appears in the human text.
        self.assertIn("destination_exists", result.stdout)
        self.assertIn("destination_exists", result.stderr
                      or result.stdout)
        with open(self.output) as stream:
            self.assertEqual("occupied", stream.read())

    def test_cli_ctrl_c_detaches_and_executor_finishes(self):
        self.make_live_store()
        env = dict(os.environ)
        env["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = self.root
        process = subprocess.Popen(
            [sys.executable, ENTRY, "backup", "create", "--json",
             "--output", self.output],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env)
        started = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = process.stderr.readline()
            if not line:
                break
            if "backup.create" in line:
                started = True
                break
        self.assertTrue(started, "started envelope not seen")
        process.send_signal(signal.SIGINT)
        _out, _err = process.communicate(timeout=30)
        self.assertEqual(130, process.returncode)
        # The detached executor must finish the operation on its own.
        store = OperationStore(self.root)
        ids = store.list_ids()
        self.assertTrue(ids)
        operation_id = ids[0]
        record = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            record = store.load(operation_id)
            if record["state"] in ("succeeded", "failed", "blocked",
                                   "cancelled"):
                break
            time.sleep(0.1)
        self.assertIsNotNone(record)
        self.assertIn(record["state"], ("succeeded", "failed", "blocked",
                                        "cancelled"))
        if record["state"] == "succeeded":
            self.assertTrue(os.path.exists(self.output))
            outcome = verify_backup(self.output, helper=self.helper)
            self.assertTrue(outcome["valid"])

    def test_cli_concurrent_writer_is_not_blocked(self):
        self.make_live_store()
        stop = threading.Event()
        failures = []

        def writer():
            connection = sqlite3.connect(
                os.path.join(self.root, "facts.sqlite3"), timeout=30)
            batch = 0
            try:
                while not stop.is_set():
                    commit_id = "cli-%d" % batch
                    try:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.execute(_INSERT_COMMIT,
                                           (commit_id, 1700000000000 + batch))
                        for index in range(2):
                            connection.execute(_INSERT_EVENT, (
                                "cli-event-%d-%d" % (batch, index), commit_id,
                                1, "luna_pinyin", "shijie", 0, 6, "word",
                                "", 1, "测试", "explicit_current", None, 1, 1,
                                "cli-session", index, 1700000000100 + index,
                                index, 1700000000000 + batch,
                                1700000000000 + batch))
                            connection.execute(
                                _INSERT_CANDIDATE,
                                ("cli-event-%d-%d" % (batch, index),
                                 0, "测试"))
                        connection.commit()
                        batch += 1
                    except sqlite3.OperationalError as error:
                        failures.append(str(error))
                        time.sleep(0.01)
            finally:
                connection.close()

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            result = self.run_cli(
                ["backup", "create", "--json", "--output", self.output])
        finally:
            stop.set()
            thread.join()
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual([], failures)
        outcome = verify_backup(self.output, helper=self.helper)
        self.assertTrue(outcome["valid"])
        connection = sqlite3.connect(os.path.join(self.root,
                                                  "facts.sqlite3"))
        final_count = connection.execute(
            "SELECT COUNT(*) FROM selection_events").fetchone()[0]
        connection.close()
        self.assertGreater(final_count, 2)
        self.assertGreaterEqual(outcome["event_count"], 2)

    def test_cli_operation_show_wait_cancel_backup_type(self):
        self.make_live_store()
        registry = cli.default_registry()
        store = OperationStore(self.root)
        record = create_operation(store, registry, "backup.create",
                                  {"output": self.output})
        operation_id = record["operation_id"]
        shown = self.run_cli(["operation", "show", operation_id])
        self.assertEqual(0, shown.returncode, shown.stderr + shown.stdout)
        self.assertIn("backup.create", shown.stdout)
        waited = self.run_cli(
            ["operation", "run", operation_id], stdin="")
        self.assertEqual(0, waited.returncode, waited.stderr + waited.stdout)
        terminal = self.run_cli(["operation", "show", "--json",
                                 operation_id])
        payload = json.loads(terminal.stdout)
        self.assertEqual("succeeded", payload["state"])
        self.assertEqual("backup.create", payload["type"])


def manifest_key(manifest, key):
    """Map a C++ stats key onto the manifest's nested shape."""
    if key == "hlc_physical_ms":
        return manifest["hlc_high_water"]["physical_ms"]
    if key == "hlc_logical":
        return manifest["hlc_high_water"]["logical"]
    if key == "event_hlc_physical_ms":
        watermark = manifest["event_hlc_high_water"]
        return None if watermark is None else watermark["physical_ms"]
    if key == "event_hlc_logical":
        watermark = manifest["event_hlc_high_water"]
        return None if watermark is None else watermark["logical"]
    return manifest[key]


class CountingHelper:
    """Records helper calls and optionally fails snapshot/inspect."""

    def __init__(self, inner, snapshots, fail_snapshot=False):
        self.inner = inner
        self.snapshots = snapshots
        self.fail_snapshot = fail_snapshot

    def verify(self, root):
        return self.inner.verify(root)

    def snapshot(self, root, output, phase="staging"):
        if self.fail_snapshot:
            raise backup_operation.OperationFailed(
                "fact_store_helper_failed", phase="staging", retryable=True)
        self.snapshots.append(output)
        return self.inner.snapshot(root, output, phase)

    def inspect(self, db_path, phase="staging"):
        return self.inner.inspect(db_path, phase)


def _crash_at(phase, step_index, point, target_phase, target_point):
    if phase == target_phase and point == target_point:
        raise SimulatedCrash()


if __name__ == "__main__":
    unittest.main()
