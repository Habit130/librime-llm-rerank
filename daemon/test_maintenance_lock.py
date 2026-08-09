#!/usr/bin/env python3
"""Tests for the shared/exclusive maintenance lock (Habit130/squirrel#53).

The lock protocol is a BSD flock on `maintenance.lock` (0600) under the
facts root: shared for writers/readers, exclusive for maintenance, released
by the kernel on process death (never a wall-clock lease). All fixtures live
in temporary directories.
"""

import fcntl
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from maintenance_lock import (  # noqa: E402
    LOCK_FILENAME,
    MaintenanceLock,
    MaintenanceLockError,
)

from quiesce import acquire_exclusive_guard  # noqa: E402


class LockClock:
    """Injectable monotonic clock: each call advances by a fixed step, so
    bounded waits expire after a couple of polls without sleeping the real
    5 seconds."""

    def __init__(self, step=0.5):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


class MaintenanceLockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_lock_")
        self.root = os.path.join(self._tmp, "SemanticMemory")
        os.makedirs(self.root)
        os.chmod(self.root, 0o700)
        self.lock = MaintenanceLock(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_lock_file_is_created_0600_owner_only(self):
        guard = self.lock.try_shared()
        self.assertIsNotNone(guard)
        guard.close()
        st = os.lstat(os.path.join(self.root, LOCK_FILENAME))
        self.assertTrue(stat.S_ISREG(st.st_mode))
        self.assertEqual(0o600, stat.S_IMODE(st.st_mode))
        self.assertEqual(os.getuid(), st.st_uid)

    def test_shared_locks_coexist_and_exclusive_excludes(self):
        first = self.lock.try_shared()
        self.assertIsNotNone(first)
        second = self.lock.try_shared()
        self.assertIsNotNone(second)
        self.assertIsNone(self.lock.try_exclusive())
        first.close()
        self.assertIsNone(self.lock.try_exclusive())
        second.close()
        guard = self.lock.try_exclusive()
        self.assertIsNotNone(guard)
        # Exclusive excludes both shared and exclusive.
        self.assertIsNone(self.lock.try_shared())
        self.assertIsNone(self.lock.try_exclusive())
        guard.close()

    def test_symlinked_lock_file_is_refused(self):
        guard = self.lock.try_shared()
        guard.close()
        os.remove(os.path.join(self.root, LOCK_FILENAME))
        os.symlink("/dev/null", os.path.join(self.root, LOCK_FILENAME))
        with self.assertRaises(MaintenanceLockError) as ctx:
            self.lock.try_shared()
        self.assertEqual("lock_symlink", ctx.exception.code)

    def test_loose_lock_file_mode_is_refused(self):
        guard = self.lock.try_shared()
        guard.close()
        os.remove(os.path.join(self.root, LOCK_FILENAME))
        with open(os.path.join(self.root, LOCK_FILENAME), "w") as f:
            f.write("")
        os.chmod(os.path.join(self.root, LOCK_FILENAME), 0o644)
        with self.assertRaises(MaintenanceLockError) as ctx:
            self.lock.try_shared()
        self.assertEqual("lock_permission", ctx.exception.code)

    def test_loose_root_is_refused(self):
        os.chmod(self.root, 0o755)
        with self.assertRaises(MaintenanceLockError) as ctx:
            self.lock.try_shared()
        self.assertEqual("root_permission", ctx.exception.code)

    def test_quiesce_timeout_modifies_nothing(self):
        # A first holder takes the exclusive lock.
        holder = MaintenanceLock(self.root)
        guard = holder.try_exclusive()
        self.assertIsNotNone(guard)
        root_listing_before = sorted(os.listdir(self.root))
        clock = LockClock()
        with self.assertRaises(MaintenanceLockError) as ctx:
            acquire_exclusive_guard(self.root, timeout_ms=100, clock=clock)
        self.assertEqual("quiesce_timeout", ctx.exception.code)
        # Nothing was modified: no new files, no fact/db touched (there is
        # no db yet, and no temp or gap file appeared).
        self.assertEqual(root_listing_before, sorted(os.listdir(self.root)))
        guard.close()

    def test_quiesce_succeeds_after_holder_releases(self):
        holder = MaintenanceLock(self.root)
        guard = holder.try_exclusive()
        self.assertIsNotNone(guard)
        guard.close()
        acquired = acquire_exclusive_guard(self.root, timeout_ms=2000)
        try:
            self.assertIsNone(self.lock.try_shared())
        finally:
            acquired.close()
        # Released again: shared works.
        shared = self.lock.try_shared()
        self.assertIsNotNone(shared)
        shared.close()

    def test_lock_is_taken_over_after_process_death(self):
        script = (
            "import fcntl, os, time, sys\n"
            "root = sys.argv[1]\n"
            "path = os.path.join(root, 'maintenance.lock')\n"
            "fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)\n"
            "fcntl.flock(fd, fcntl.LOCK_EX)\n"
            "time.sleep(60)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script, self.root],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # Wait for the child to hold the lock (bounded). When the probe
            # wins the race it must release its own acquisition, or it would
            # block the child forever.
            deadline = time.monotonic() + 5
            child_holds = False
            while time.monotonic() < deadline:
                probe = self.lock.try_exclusive()
                if probe is None:
                    child_holds = True
                    break
                probe.close()
                time.sleep(0.02)
            self.assertTrue(child_holds)
            proc.kill()
            proc.wait(timeout=10)
            # The kernel released the advisory lock: takeover succeeds.
            guard = self.lock.try_exclusive()
            self.assertIsNotNone(guard)
            guard.close()
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
