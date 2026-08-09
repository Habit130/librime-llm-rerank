#!/usr/bin/env python3
"""Shared/exclusive advisory lock on the fact store (Habit130/squirrel#53).

The facts root holds a single `maintenance.lock` file with exact mode 0600.
Every fact write transaction (C++ plugin) and every daemon fact-handle
lifetime holds the lock SHARED; restore / clear / migration take it
EXCLUSIVE. The lock is a BSD `flock`: the kernel releases it when the owning
process dies, so a crashed writer or maintenance process can never wedge the
store and no wall-clock lease is involved.

This module is the Python counterpart of the C++ `maintenance_lock.cc`
(plugin side); both verify the same invariants (real root 0700, lock file
0600, regular, owned by the current user, never a symlink) and fail closed
instead of auto-relaxing.

Usage:
    lock = MaintenanceLock(root)
    with lock.shared(timeout_ms=2000):
        ...read or write the fact store...
    guard = lock.exclusive(timeout_ms=5000)
    try:
        ...replace the fact store...
    finally:
        guard.close()
"""

import errno
import fcntl
import os
import stat
import time

LOCK_FILENAME = "maintenance.lock"
LOCK_MODE = 0o600
ROOT_MODE = 0o700
DEFAULT_QUIESCE_TIMEOUT_MS = 5000


class MaintenanceLockError(Exception):
    """A stable-code lock fault (root or lock file verification, timeout)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _Guard:
    """RAII holder for an acquired flock; close() releases it."""

    def __init__(self, fd):
        self._fd = fd

    def close(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _exact_mode(path, mode):
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == mode
    except OSError:
        return False


class MaintenanceLock:
    """Verification + flock around `<root>/maintenance.lock`."""

    def __init__(self, root_dir, euid=None):
        self.root_dir = root_dir
        self.euid = os.geteuid() if euid is None else euid

    def lock_path(self):
        return os.path.join(self.root_dir, LOCK_FILENAME)

    def _verify_root(self):
        if not self.root_dir:
            raise MaintenanceLockError("no_home")
        try:
            st = os.lstat(self.root_dir)
        except OSError:
            raise MaintenanceLockError("root_unavailable") from None
        if stat.S_ISLNK(st.st_mode):
            raise MaintenanceLockError("root_symlink")
        if not stat.S_ISDIR(st.st_mode):
            raise MaintenanceLockError("root_not_directory")
        if st.st_uid != self.euid:
            raise MaintenanceLockError("root_owner")
        if not _exact_mode(self.root_dir, ROOT_MODE):
            raise MaintenanceLockError("root_permission")

    def _ensure_file(self):
        """Verify (and create, 0600) the lock file. Never follows a symlink
        on the final component and never relaxes a wrong mode/owner."""
        self._verify_root()
        lock_path = self.lock_path()
        try:
            st = os.lstat(lock_path)
        except OSError:
            try:
                fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             LOCK_MODE)
                os.close(fd)
            except OSError:
                # A racing creator won; fall through to re-verify their file.
                pass
            try:
                st = os.lstat(lock_path)
            except OSError:
                raise MaintenanceLockError("lock_open_failed") from None
        if stat.S_ISLNK(st.st_mode):
            raise MaintenanceLockError("lock_symlink")
        if not stat.S_ISREG(st.st_mode):
            raise MaintenanceLockError("lock_not_regular")
        if st.st_uid != self.euid:
            raise MaintenanceLockError("lock_owner")
        if not _exact_mode(lock_path, LOCK_MODE):
            raise MaintenanceLockError("lock_permission")
        return lock_path

    def _open(self):
        try:
            return os.open(self._ensure_file(), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            raise MaintenanceLockError("lock_open_failed") from None

    def try_shared(self):
        """Non-blocking shared acquisition; returns a guard or None when the
        exclusive lock is held (never blocks, never waits on maintenance)."""
        try:
            fd = self._open()
        except MaintenanceLockError:
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None
        return _Guard(fd)

    def shared(self, timeout_ms=None, clock=time.monotonic):
        """Bounded shared acquisition for readers (status, handles). On
        timeout raises MaintenanceLockError("lock_busy")."""
        deadline = None if timeout_ms is None else clock() + timeout_ms / 1000.0
        while True:
            guard = self.try_shared()
            if guard is not None:
                return guard
            if deadline is not None and clock() >= deadline:
                raise MaintenanceLockError("lock_busy")
            time.sleep(0.01)

    def try_exclusive(self):
        """Non-blocking exclusive acquisition; returns a guard or None."""
        try:
            fd = self._open()
        except MaintenanceLockError:
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None
        return _Guard(fd)

    def exclusive(self, timeout_ms=DEFAULT_QUIESCE_TIMEOUT_MS,
                  clock=time.monotonic):
        """Bounded exclusive acquisition (the maintenance quiesce window).

        On timeout raises MaintenanceLockError("lock_timeout") with nothing
        modified; the caller must not touch any fact or derived file then.
        `clock` is injectable for deterministic tests.
        """
        deadline = clock() + timeout_ms / 1000.0
        while True:
            guard = self.try_exclusive()
            if guard is not None:
                return guard
            if clock() >= deadline:
                raise MaintenanceLockError("lock_timeout")
            time.sleep(0.01)
