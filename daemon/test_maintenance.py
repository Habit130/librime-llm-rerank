import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest

import control
from coordinator import MaintenanceCoordinator
from maintenance import (MaintenanceError, MaintenanceLock, acquire_exclusive,
                         read_recording_gap, run_fact_replacement,
                         run_maintenance)


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


if __name__ == "__main__":
    unittest.main()
