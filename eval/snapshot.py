#!/usr/bin/env python3
"""Frozen fact-snapshot acquisition for the #70 walk-forward evaluation.

SCN-70-7: snapshotting must never disturb the live recorder.  The snapshot
is taken with the SQLite Online Backup API (``Connection.backup``), which
is the same non-blocking, consistent mechanism the fact store's own backup
command uses:

- The source is opened read-only; the backup API copies a consistent
  database image even while the live daemon keeps writing (WAL).
- Nothing is written to the live store, no daemon restart, no touch of
  ``~/Library/Rime`` or the librime build tree.
- The resulting copy is integrity-checked and fingerprinted (SHA-256), and
  the live status watermark is captured before and after the copy so the
  report can prove the recorder stayed continuous (no gap, watermark
  monotonic).

The snapshot file is treated as private data: it is never uploaded and the
report only carries its SHA-256.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile


class SnapshotError(Exception):
    """A true fault in snapshot acquisition or verification."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def live_status(status_cli):
    """Capture the live status JSON (read-only; never starts the daemon)."""
    try:
        output = subprocess.run(
            [status_cli, "status", "--json"], capture_output=True,
            text=True, timeout=30, check=False).stdout
        parsed = json.loads(output)
    except Exception as error:  # noqa: BLE001
        raise SnapshotError("cannot read live status: %s" % error) from error
    facts = parsed.get("facts", {})
    return {
        "snapshot_ok": parsed.get("snapshot_ok"),
        "active_events": facts.get("active_events"),
        "retracted_commits": facts.get("retracted_commits"),
        "total_events": facts.get("total_events"),
        "fact_high_water": facts.get("fact_high_water"),
        "gap_state": (facts.get("recording_gaps") or {}).get("state"),
        "store_epoch": facts.get("store_epoch"),
        "history_id": facts.get("history_id"),
    }


def assert_status_continuous(before, after):
    """SCN-70-7: the recorder must stay continuous across the snapshot.

    Both statuses must be healthy (snapshot_ok), gap state must be "none"
    before and after, and the fact high-water must be non-decreasing.
    """
    problems = []
    if not before.get("snapshot_ok") or not after.get("snapshot_ok"):
        problems.append("status snapshot not ok")
    if before.get("gap_state") != "none":
        problems.append("gap state before snapshot: %r"
                        % before.get("gap_state"))
    if after.get("gap_state") != "none":
        problems.append("gap state after snapshot: %r"
                        % after.get("gap_state"))
    before_hw = before.get("fact_high_water") or {}
    after_hw = after.get("fact_high_water") or {}
    before_key = (before_hw.get("hlc_physical_ms"),
                  before_hw.get("hlc_logical"))
    after_key = (after_hw.get("hlc_physical_ms"),
                 after_hw.get("hlc_logical"))
    if None not in before_key and None not in after_key:
        if after_key < before_key:
            problems.append("high-water decreased across snapshot")
    elif before_key != after_key:
        problems.append("high-water not comparable across snapshot")
    if before.get("store_epoch") != after.get("store_epoch"):
        problems.append("store epoch changed across snapshot")
    if problems:
        raise SnapshotError("live recorder continuity violated: %s"
                            % "; ".join(problems))
    return True


def take_snapshot(source_db, target_dir, status_cli=None):
    """Take one consistent frozen snapshot copy.

    Returns a dict with the snapshot path, SHA-256, identity and the
    before/after live status watermarks (proving SCN-70-7).  When
    ``status_cli`` is None the continuity check is skipped and the record
    carries ``status_check: "skipped"``.
    """
    if not os.path.isfile(source_db):
        raise SnapshotError("source fact store not found: %s" % source_db)
    os.makedirs(target_dir, exist_ok=True)
    status = {"status_check": "skipped"}
    if status_cli is not None:
        status["before"] = live_status(status_cli)
    fd, snapshot_path = tempfile.mkstemp(
        prefix="facts-snapshot-", suffix=".sqlite3", dir=target_dir)
    os.close(fd)
    try:
        source = sqlite3.connect(source_db, timeout=3.0)
        # Read-only enforcement: the Online Backup API is the only
        # operation and performs no writes, but a stray write path must
        # fail closed (mirrors the oracle's query_only guard).
        source.execute("PRAGMA query_only=ON;")
        try:
            target = sqlite3.connect(snapshot_path)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    except sqlite3.Error as error:
        raise SnapshotError("online backup failed: %s" % error) from error

    conn = sqlite3.connect(snapshot_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SnapshotError("snapshot integrity check failed: %s"
                                % integrity)
        identity = dict(conn.execute("SELECT key, value FROM meta"))
    except sqlite3.Error as error:
        raise SnapshotError("snapshot verification failed: %s"
                            % error) from error
    finally:
        conn.close()

    if status_cli is not None:
        status["after"] = live_status(status_cli)
        assert_status_continuous(status["before"], status["after"])
        status["status_check"] = "ok"

    return {
        "path": snapshot_path,
        "sha256": sha256_file(snapshot_path),
        "identity": identity,
        "status": status,
    }
