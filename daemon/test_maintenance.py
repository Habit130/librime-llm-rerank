import json
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

import control
from coordinator import MaintenanceCoordinator
from maintenance import (MaintenanceError, MaintenanceLock, acquire_exclusive,
                         read_recording_gap, replace_fact_database,
                         run_fact_replacement, run_maintenance)


class _FakeClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, duration):
        self.value += duration


class _FakeControlClient:
    def __init__(self, _path, _operation_id, steps):
        self.steps = steps

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def prepare(self):
        self.steps.append("prepare")
        return {"ok": True}

    def assert_prepared(self):
        self.steps.append("lease")
        return {"ok": True, "state": "prepared"}

    def reopen(self):
        self.steps.append("reopen")
        return {"ok": True, "state": "serving"}


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, "SemanticMemory")
        os.mkdir(self.root, 0o700)

    def tearDown(self):
        self.temp.cleanup()

    def read_target(self, name):
        with open(os.path.join(self.root, name), "rb") as stream:
            return stream.read()

    def _write_store(self, epoch):
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("store_epoch", epoch), ("hlc_physical_ms", "9"),
             ("hlc_logical", "1")],
        )
        connection.commit()
        connection.close()
        os.chmod(db_path, 0o600)
        return db_path

    def _write_replacement(self, epoch, name="replacement.sqlite3"):
        path = os.path.join(self.temp.name, name)
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("store_epoch", epoch), ("hlc_physical_ms", "10"),
             ("hlc_logical", "0")],
        )
        connection.commit()
        connection.close()
        os.chmod(path, 0o600)
        return path

    def _read_epoch(self):
        connection = sqlite3.connect(
            f"file:{os.path.join(self.root, 'facts.sqlite3')}?mode=ro", uri=True)
        try:
            return connection.execute(
                "SELECT value FROM meta WHERE key='store_epoch'").fetchone()[0]
        finally:
            connection.close()

    def test_sidecar_removal_failure_aborts_before_publication(self):
        self._write_store("epoch-a")
        with open(os.path.join(self.root, "facts.sqlite3-shm"), "wb") as stream:
            stream.write(b"stale")
        os.chmod(os.path.join(self.root, "facts.sqlite3-shm"), 0o600)
        replacement = self._write_replacement("epoch-b")
        replaced = []

        def failing_unlink(path):
            if path.endswith("-shm"):
                raise OSError(13, "injected unlink failure")
            return os.unlink(path)

        with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
            replace_fact_database(self.root, replacement,
                                  _unlink=failing_unlink,
                                  _replace=lambda *_: replaced.append(True))
        # The failed attempt must leave the complete old store untouched and
        # must never have published the new main database.
        self.assertEqual([], replaced)
        self.assertEqual("epoch-a", self._read_epoch())
        self.assertTrue(os.path.exists(replacement))

    def test_checkpoint_failure_aborts_before_publication(self):
        self._write_store("epoch-a")
        replacement = self._write_replacement("epoch-b")

        def failing_connect(path, **kwargs):
            del path, kwargs
            raise sqlite3.DatabaseError("injected checkpoint failure")

        with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
            replace_fact_database(self.root, replacement,
                                  _connect=failing_connect)
        self.assertEqual("epoch-a", self._read_epoch())
        self.assertTrue(os.path.exists(replacement))

    def test_successful_replacement_removes_stale_sidecars(self):
        self._write_store("epoch-a")
        for suffix in ("-shm",):
            with open(os.path.join(self.root, "facts.sqlite3" + suffix),
                      "wb") as stream:
                stream.write(b"stale")
            os.chmod(os.path.join(self.root, "facts.sqlite3" + suffix), 0o600)
        replacement = self._write_replacement("epoch-b")
        replace_fact_database(self.root, replacement)
        self.assertEqual("epoch-b", self._read_epoch())
        self.assertFalse(os.path.exists(replacement))
        self.assertFalse(os.path.exists(os.path.join(self.root,
                                                     "facts.sqlite3-shm")))
        self.assertFalse(os.path.exists(os.path.join(self.root,
                                                     "facts.sqlite3-wal")))

    def test_crash_between_checkpoint_and_publication_leaves_complete_old_store(self):
        self._write_store("epoch-a")
        replacement = self._write_replacement("epoch-b")
        daemon_dir = os.path.dirname(os.path.abspath(__import__(
            "maintenance").__file__))
        script = (
            "import os, sys\n"
            "sys.path.insert(0, %r)\n"
            "import maintenance\n"
            "def crash():\n"
            "    os._exit(9)\n"
            "maintenance.replace_fact_database(%r, %r,"
            " _after_checkpoint=crash)\n"
            "os._exit(0)\n" % (daemon_dir, self.root, replacement)
        )
        completed = subprocess.run([sys.executable, "-c", script],
                                   check=False, timeout=60)
        # The child died after the checkpoint and sidecar cleanup but before
        # the atomic rename: only the complete old store may be observable.
        self.assertEqual(9, completed.returncode)
        self.assertEqual("epoch-a", self._read_epoch())
        self.assertTrue(os.path.exists(replacement))
        self.assertFalse(os.path.exists(os.path.join(self.root,
                                                     "facts.sqlite3-wal")))

    def test_gap_lock_unknown_state_is_reported_unknown(self):
        self._write_store("epoch-a")
        lock = os.path.join(self.root, "recording_gap.lock")
        with open(lock, "wb") as stream:
            stream.write(b"unknown\n")
        os.chmod(lock, 0o600)
        gap = read_recording_gap(self.root)
        self.assertEqual("unknown", gap["state"])
        self.assertEqual("gap_missing_after_initialization", gap["reason"])


    def test_default_timeout_preserves_every_maintenance_target(self):
        targets = ["facts.sqlite3", "facts.sqlite3-wal", "facts.sqlite3-shm",
                   "replacement.marker", "derived.marker"]
        for name in targets:
            with open(os.path.join(self.root, name), "wb") as stream:
                stream.write(name.encode("ascii"))
            os.chmod(os.path.join(self.root, name), 0o600)
        before = {
            name: self.read_target(name)
            for name in targets
        }
        steps = []
        clock = _FakeClock()
        shared = MaintenanceLock(self.root, exclusive=False).acquire()
        try:
            with self.assertRaisesRegex(MaintenanceError, "quiesce_timeout"):
                run_maintenance(
                    lambda: steps.append("preflight"), self.root,
                    lambda _lease: steps.append("replacement"),
                    "unused.sock", "op-timeout", now=clock.now,
                    sleep=clock.sleep,
                    control_client_factory=lambda path, operation: _FakeControlClient(
                        path, operation, steps),
                )
        finally:
            shared.release()
        self.assertEqual(["preflight", "prepare", "lease", "reopen"], steps)
        self.assertGreaterEqual(clock.value, 5.0)
        self.assertEqual(
            before,
            {name: self.read_target(name)
             for name in targets},
        )

    def test_acquire_exclusive_timeout_does_not_create_fact_targets(self):
        shared = MaintenanceLock(self.root, exclusive=False).acquire()
        try:
            with self.assertRaisesRegex(MaintenanceError, "quiesce_timeout"):
                acquire_exclusive(self.root, timeout_s=0, now=lambda: 1)
            self.assertFalse(os.path.exists(os.path.join(self.root, "facts.sqlite3")))
            self.assertFalse(os.path.exists(os.path.join(self.root, "facts.sqlite3-wal")))
            self.assertFalse(os.path.exists(os.path.join(self.root, "facts.sqlite3-shm")))
        finally:
            shared.release()

    def test_gap_rejects_unknown_version_and_negative_counts(self):
        path = os.path.join(self.root, "recording_gap.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"gap_version": 1}, stream)
        os.chmod(path, 0o600)
        self.assertEqual("unknown", read_recording_gap(self.root)["state"])

        with open(path, "w", encoding="utf-8") as stream:
            json.dump({
                "gap_version": 2.0,
                "state": "present",
                "reason": "buffer_overflow_batches",
                "store_epoch": "epoch",
                "dropped_batches": 1,
                "dropped_events": 1,
                "dropped_retractions": 0,
                "dropped_bytes": 1,
                "updated_at_ms": 1,
            }, stream)
        os.chmod(path, 0o600)
        self.assertEqual("unknown", read_recording_gap(self.root)["state"])

        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"gap_version": 2, "state": "present", "reason": "overflow",
                       "dropped_batches": -1, "dropped_events": 0,
                       "dropped_retractions": 0, "dropped_bytes": 0,
                       "updated_at_ms": 1}, stream)
        os.chmod(path, 0o600)
        self.assertEqual("unknown", read_recording_gap(self.root)["state"])

    def test_stale_recorder_marker_is_fail_closed_without_gap_text(self):
        marker = os.path.join(self.root, ".recording_process.crashed")
        with open(marker, "wb") as stream:
            stream.write(b"clean\n")
        os.chmod(marker, 0o600)
        gap = read_recording_gap(self.root)
        self.assertEqual("unknown", gap["state"])
        self.assertEqual("recorder_process_crashed", gap["reason"])

    def test_real_control_lease_runs_successful_replacement_and_reopen(self):
        lock = MaintenanceLock(self.root, exclusive=False).acquire()
        lock.release()
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("store_epoch", "epoch-a"), ("hlc_physical_ms", "9"),
             ("hlc_logical", "1")],
        )
        connection.commit()
        connection.close()
        os.chmod(db_path, 0o600)
        replacement_path = os.path.join(self.temp.name, "replacement.sqlite3")
        replacement_db = sqlite3.connect(replacement_path)
        replacement_db.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        replacement_db.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("store_epoch", "epoch-b"), ("hlc_physical_ms", "10"),
             ("hlc_logical", "0")],
        )
        replacement_db.commit()
        replacement_db.close()
        os.chmod(replacement_path, 0o600)
        coordinator = MaintenanceCoordinator(
            self.root)
        socket_path = os.path.join(self.root, "control.sock")
        ready = threading.Event()
        stop = threading.Event()
        server = threading.Thread(
            target=control.run_control_server,
            args=(socket_path, coordinator, ready, stop),
        )
        server.start()
        ready.wait()
        steps = []
        try:
            def preflight():
                steps.append("preflight")
                self.assertEqual("serving",
                                 coordinator.health()["maintenance_state"])

            result = run_fact_replacement(
                preflight, self.root, replacement_path, socket_path,
                "op-success")
        finally:
            stop.set()
            wake = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            wake.connect(socket_path)
            wake.close()
            server.join()
        self.assertEqual(["preflight"], steps)
        self.assertTrue(result["ok"])
        self.assertEqual("serving", result["state"])
        self.assertEqual("epoch-b", result["store_epoch"])
        self.assertFalse(os.path.exists(replacement_path))
        self.assertEqual("serving", coordinator.health()["maintenance_state"])
        self.assertEqual(1, coordinator.health()["open_handles"])
        coordinator.close()


class _FakeCheckpointResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeCheckpointConnection:
    """A connection seam returning an exact wal_checkpoint result shape."""

    def __init__(self, row):
        self._row = row
        self.closed = False

    def execute(self, sql):
        if sql != "PRAGMA wal_checkpoint(TRUNCATE);":
            raise AssertionError("unexpected sql: %r" % sql)
        return _FakeCheckpointResult(self._row)

    def close(self):
        self.closed = True


class ReplacementStagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, "SemanticMemory")
        os.mkdir(self.root, 0o700)
        db_path = os.path.join(self.root, "facts.sqlite3")
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("store_epoch", "epoch-a"), ("hlc_physical_ms", "9"),
             ("hlc_logical", "1")],
        )
        connection.commit()
        connection.close()
        os.chmod(db_path, 0o600)
        with open(os.path.join(self.root, "facts.sqlite3-shm"), "wb") as stream:
            stream.write(b"stale")
        os.chmod(os.path.join(self.root, "facts.sqlite3-shm"), 0o600)
        self.replacement = os.path.join(self.temp.name, "replacement.sqlite3")
        connection = sqlite3.connect(self.replacement)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [("store_epoch", "epoch-b"), ("hlc_physical_ms", "10"),
             ("hlc_logical", "0")],
        )
        connection.commit()
        connection.close()
        os.chmod(self.replacement, 0o600)

    def tearDown(self):
        self.temp.cleanup()

    def _read_main_epoch(self):
        connection = sqlite3.connect(
            f"file:{os.path.join(self.root, 'facts.sqlite3')}?mode=ro", uri=True)
        try:
            return connection.execute(
                "SELECT value FROM meta WHERE key='store_epoch'").fetchone()[0]
        finally:
            connection.close()

    def test_checkpoint_busy_aborts_before_publication(self):
        events = []

        def recording_unlink(path):
            events.append(("unlink", path))
            return os.unlink(path)

        def recording_replace(source, target):
            events.append(("replace", source, target))

        connection = _FakeCheckpointConnection((1, 7, 0))
        with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
            replace_fact_database(
                self.root, self.replacement,
                _connect=lambda path, **kwargs: connection,
                _unlink=recording_unlink,
                _replace=recording_replace)
        self.assertTrue(connection.closed)
        # A busy checkpoint must not remove sidecars or publish the new main.
        self.assertEqual([], events)
        self.assertEqual("epoch-a", self._read_main_epoch())
        self.assertTrue(os.path.exists(os.path.join(self.root,
                                                    "facts.sqlite3-shm")))
        self.assertTrue(os.path.exists(self.replacement))

    def test_checkpoint_success_still_publishes(self):
        connection = _FakeCheckpointConnection((0, -1, -1))
        replace_fact_database(
            self.root, self.replacement,
            _connect=lambda path, **kwargs: connection)
        self.assertTrue(connection.closed)
        self.assertEqual("epoch-b", self._read_main_epoch())
        self.assertFalse(os.path.exists(self.replacement))
        self.assertFalse(os.path.exists(os.path.join(self.root,
                                                     "facts.sqlite3-shm")))

    def test_symlinked_existing_main_rejected_before_connect(self):
        # Move the real database outside the root and symlink it in: the
        # replacement must reject the link without ever connecting to or
        # modifying the target.
        os.rename(os.path.join(self.root, "facts.sqlite3"),
                  os.path.join(self.temp.name, "real-facts.sqlite3"))
        os.symlink(os.path.join(self.temp.name, "real-facts.sqlite3"),
                   os.path.join(self.root, "facts.sqlite3"))
        events = []

        def recording_connect(path, **kwargs):
            events.append(("connect", path))
            raise AssertionError("symlink target must not be opened")

        def recording_unlink(path):
            events.append(("unlink", path))
            return os.unlink(path)

        def recording_replace(source, target):
            events.append(("replace", source, target))

        with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
            replace_fact_database(
                self.root, self.replacement,
                _connect=recording_connect,
                _unlink=recording_unlink,
                _replace=recording_replace)
        self.assertEqual([], events)
        # The target is untouched and the sidecar and replacement remain.
        target = sqlite3.connect(
            f"file:{os.path.join(self.temp.name, 'real-facts.sqlite3')}"
            "?mode=ro", uri=True)
        try:
            self.assertEqual("epoch-a", target.execute(
                "SELECT value FROM meta WHERE key='store_epoch'").fetchone()[0])
        finally:
            target.close()
        self.assertTrue(os.path.exists(os.path.join(self.root,
                                                    "facts.sqlite3-shm")))
        self.assertTrue(os.path.exists(self.replacement))

    def test_wrong_mode_existing_main_rejected_before_connect(self):
        os.chmod(os.path.join(self.root, "facts.sqlite3"), 0o644)
        events = []

        def recording_connect(path, **kwargs):
            events.append(("connect", path))
            raise AssertionError("unsafe main must not be opened")

        with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
            replace_fact_database(self.root, self.replacement,
                                  _connect=recording_connect,
                                  _unlink=lambda _: events.append(("unlink",)),
                                  _replace=lambda *_: events.append(("replace",)))
        self.assertEqual([], events)
        self.assertTrue(os.path.exists(self.replacement))

    def test_wrong_owner_existing_main_rejected_before_connect(self):
        import maintenance as maintenance_module
        real_fstat = maintenance_module.os.fstat
        events = []

        def flipped_owner_fstat(fd):
            result = real_fstat(fd)
            if stat.S_ISREG(result.st_mode):
                parts = list(result)
                parts[4] = result.st_uid + 1
                return os.stat_result(parts)
            return result

        try:
            maintenance_module.os.fstat = flipped_owner_fstat
            with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
                replace_fact_database(
                    self.root, self.replacement,
                    _connect=lambda *args, **kwargs: events.append(
                        ("connect",)),
                    _unlink=lambda _: events.append(("unlink",)),
                    _replace=lambda *_: events.append(("replace",)))
        finally:
            maintenance_module.os.fstat = real_fstat
        self.assertEqual([], events)
        self.assertTrue(os.path.exists(self.replacement))

    def test_non_regular_existing_main_rejected_before_connect(self):
        os.unlink(os.path.join(self.root, "facts.sqlite3"))
        os.mkdir(os.path.join(self.root, "facts.sqlite3"))
        events = []

        with self.assertRaisesRegex(MaintenanceError, "replacement_failed"):
            replace_fact_database(
                self.root, self.replacement,
                _connect=lambda *args, **kwargs: events.append(("connect",)),
                _unlink=lambda _: events.append(("unlink",)),
                _replace=lambda *_: events.append(("replace",)))
        self.assertEqual([], events)
        self.assertTrue(os.path.exists(self.replacement))


if __name__ == "__main__":
    unittest.main()
