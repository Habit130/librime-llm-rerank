import json
import os
import stat
import tempfile
import unittest

from maintenance import (MaintenanceError, MaintenanceLock, acquire_exclusive,
                         read_recording_gap, run_maintenance)


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, "SemanticMemory")
        os.mkdir(self.root, 0o700)

    def tearDown(self):
        self.temp.cleanup()

    def test_exclusive_timeout_does_not_create_fact_targets(self):
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
            json.dump({"gap_version": 2}, stream)
        os.chmod(path, 0o600)
        self.assertEqual("unknown", read_recording_gap(self.root)["state"])
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"gap_version": 1, "reason": "overflow",
                       "dropped_batches": -1, "dropped_events": 0,
                       "dropped_retractions": 0, "dropped_bytes": 0,
                       "updated_at_ms": 1}, stream)
        os.chmod(path, 0o600)
        self.assertEqual("unknown", read_recording_gap(self.root)["state"])

    def test_preflight_precedes_prepare_and_timeout_skips_replacement(self):
        steps = []
        shared = MaintenanceLock(self.root, exclusive=False).acquire()
        try:
            with self.assertRaisesRegex(MaintenanceError, "quiesce_timeout"):
                run_maintenance(lambda: steps.append("preflight"),
                                lambda: steps.append("prepare") or {"ok": True},
                                self.root,
                                lambda _lease: steps.append("replacement"),
                                lambda: steps.append("reopen"), timeout_s=0,
                                now=lambda: 1)
        finally:
            shared.release()
        self.assertEqual(["preflight", "prepare", "reopen"], steps)
