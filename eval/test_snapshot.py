#!/usr/bin/env python3
"""Tests for the frozen-snapshot acquisition (SCN-70-7).

Pins: the Online Backup API produces a consistent read-only copy; the copy
passes integrity_check; the SHA-256 fingerprint is stable; and the live
status continuity helper rejects watermarks that regress or gaps that
appear.
"""

import os
import sqlite3
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import snapshot  # noqa: E402


class SnapshotTest(unittest.TestCase):

    def _make_source_db(self, events=5):
        source = tempfile.mktemp(suffix=".sqlite3")
        connector = sqlite3.connect(source)
        connector.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connector.execute(
            "INSERT INTO meta VALUES ('store_epoch','e1')")
        connector.execute(
            "INSERT INTO meta VALUES ('history_id','h1')")
        connector.execute("CREATE TABLE t (x INTEGER)")
        for index in range(events):
            connector.execute("INSERT INTO t VALUES (?)", (index,))
        connector.commit()
        connector.close()
        return source

    def test_backup_produces_consistent_copy(self):
        source = self._make_source_db()
        target_dir = tempfile.mkdtemp(prefix="snapshot_test_")
        try:
            record = snapshot.take_snapshot(source, target_dir)
            self.assertTrue(os.path.isfile(record["path"]))
            self.assertEqual(len(record["sha256"]), 64)
            connector = sqlite3.connect(record["path"])
            try:
                integrity = connector.execute(
                    "PRAGMA integrity_check").fetchone()[0]
                self.assertEqual(integrity, "ok")
                count = connector.execute(
                    "SELECT COUNT(*) FROM t").fetchone()[0]
                self.assertEqual(count, 5)
            finally:
                connector.close()
            self.assertEqual(
                snapshot.sha256_file(record["path"]), record["sha256"])
        finally:
            if os.path.isfile(source):
                os.unlink(source)
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)

    def test_backup_deterministic_fingerprint(self):
        source = self._make_source_db(events=7)
        dirs = [tempfile.mkdtemp(prefix="snap_a_"),
                tempfile.mkdtemp(prefix="snap_b_")]
        try:
            first = snapshot.take_snapshot(source, dirs[0])
            second = snapshot.take_snapshot(source, dirs[1])
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(
                first["identity"].get("store_epoch"), "e1")
        finally:
            if os.path.isfile(source):
                os.unlink(source)
            import shutil
            for directory in dirs:
                shutil.rmtree(directory, ignore_errors=True)

    def test_status_continuity_ok(self):
        before = {"snapshot_ok": True, "gap_state": "none",
                  "fact_high_water": {"hlc_physical_ms": 1000,
                                      "hlc_logical": 0},
                  "store_epoch": "e1"}
        after = {"snapshot_ok": True, "gap_state": "none",
                 "fact_high_water": {"hlc_physical_ms": 1200,
                                     "hlc_logical": 0},
                 "store_epoch": "e1"}
        self.assertTrue(snapshot.assert_status_continuous(before, after))

    def test_status_continuity_rejects_gap(self):
        before = {"snapshot_ok": True, "gap_state": "none",
                  "fact_high_water": {"hlc_physical_ms": 1000,
                                      "hlc_logical": 0},
                  "store_epoch": "e1"}
        after = {"snapshot_ok": True, "gap_state": "none",
                 "fact_high_water": {"hlc_physical_ms": 1200,
                                     "hlc_logical": 0},
                 "store_epoch": "e2"}
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.assert_status_continuous(before, after)

    def test_status_continuity_rejects_regression(self):
        before = {"snapshot_ok": True, "gap_state": "none",
                  "fact_high_water": {"hlc_physical_ms": 1500,
                                      "hlc_logical": 0},
                  "store_epoch": "e1"}
        after = {"snapshot_ok": True, "gap_state": "none",
                 "fact_high_water": {"hlc_physical_ms": 1200,
                                     "hlc_logical": 0},
                 "store_epoch": "e1"}
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.assert_status_continuous(before, after)


if __name__ == "__main__":
    unittest.main()
