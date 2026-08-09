"""Shared maintenance locking and fact-identity primitives.

The plugin is the only fact writer. Python uses this module only to coordinate
daemon read handles and a future CLI replacement callback; it never explains
or writes fact rows.
"""

import ctypes
import errno
import fcntl
import json
import os
import sqlite3
import stat
import time


LOCK_NAME = "maintenance.lock"
LOCK_MODE = 0o600
ROOT_MODE = 0o700


class MaintenanceError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class MaintenanceLock:
    """A directory-fd anchored flock lease released by the kernel on death."""

    def __init__(self, root, exclusive=False, nonblocking=False, create=True):
        self.root = root
        self.exclusive = exclusive
        self.nonblocking = nonblocking
        self.create = create
        self.root_fd = None
        self.fd = None

    def acquire(self):
        try:
            self.root_fd = os.open(self.root, os.O_RDONLY | os.O_NOFOLLOW)
            root_stat = os.fstat(self.root_fd)
        except OSError as error:
            raise MaintenanceError("root_unavailable") from error
        if (not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.getuid()
                or stat.S_IMODE(root_stat.st_mode) != ROOT_MODE):
            self.release()
            raise MaintenanceError("root_unsafe")
        try:
            flags = os.O_RDWR | os.O_NOFOLLOW
            if self.create:
                flags |= os.O_CREAT
            self.fd = os.open(LOCK_NAME, flags, LOCK_MODE, dir_fd=self.root_fd)
            if self.create:
                os.fchmod(self.fd, LOCK_MODE)
            lock_stat = os.fstat(self.fd)
            if (not stat.S_ISREG(lock_stat.st_mode)
                    or lock_stat.st_uid != os.getuid()
                    or stat.S_IMODE(lock_stat.st_mode) != LOCK_MODE):
                raise MaintenanceError("maintenance_lock_unsafe")
            operation = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
            if self.nonblocking:
                operation |= fcntl.LOCK_NB
            fcntl.flock(self.fd, operation)
        except MaintenanceError:
            self.release()
            raise
        except BlockingIOError as error:
            self.release()
            raise MaintenanceError("maintenance_locked") from error
        except OSError as error:
            self.release()
            raise MaintenanceError("maintenance_lock_unavailable") from error
        return self

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.root_fd is not None:
            os.close(self.root_fd)
            self.root_fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def acquire_exclusive(root, timeout_s=5.0, now=time.monotonic, sleep=time.sleep):
    """Bounded exclusive acquisition with no fact-target I/O before success."""
    deadline = now() + timeout_s
    while True:
        lock = MaintenanceLock(root, exclusive=True, nonblocking=True)
        try:
            return lock.acquire()
        except MaintenanceError as error:
            if error.code != "maintenance_locked" or now() >= deadline:
                if error.code == "maintenance_locked":
                    raise MaintenanceError("quiesce_timeout") from error
                raise
            sleep(min(0.01, max(0.0, deadline - now())))


def run_maintenance(preflight, prepare, root, replacement, reopen,
                    timeout_s=5.0, now=time.monotonic, sleep=time.sleep):
    """Reusable preflight -> prepare -> lock -> replace -> reopen seam."""
    preflight()
    prepared = prepare()
    if not prepared.get("ok"):
        return prepared
    lease = None
    recovery = None
    try:
        lease = acquire_exclusive(root, timeout_s=timeout_s, now=now, sleep=sleep)
        replacement(lease)
    finally:
        if lease is not None:
            lease.release()
        # A failed acquisition is still after prepare, so the daemon must not
        # remain quiesced merely because no replacement callback ran.
        recovery = reopen()
    return recovery


def read_fact_identity(root):
    """Read only durable epoch and HLC under the full read-handle lease."""
    with MaintenanceLock(root, exclusive=False, nonblocking=True):
        db_name = "facts.sqlite3"
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            try:
                db_fd = os.open(db_name, os.O_RDONLY | os.O_NOFOLLOW,
                                dir_fd=root_fd)
            except OSError as error:
                raise MaintenanceError("db_unavailable") from error
            try:
                db_stat = os.fstat(db_fd)
                if (not stat.S_ISREG(db_stat.st_mode)
                        or db_stat.st_uid != os.getuid()
                        or stat.S_IMODE(db_stat.st_mode) != 0o600):
                    raise MaintenanceError("db_unsafe")
            finally:
                os.close(db_fd)
        finally:
            os.close(root_fd)
        path = os.path.join(root, db_name)
        try:
            connection = sqlite3.connect("file:%s?mode=ro" % path,
                                         uri=True, timeout=0)
        except sqlite3.Error as error:
            raise MaintenanceError("db_unavailable") from error
        try:
            rows = dict(connection.execute("SELECT key, value FROM meta"))
            epoch = rows.get("store_epoch")
            physical = int(rows.get("hlc_physical_ms", "-1"))
            logical = int(rows.get("hlc_logical", "-1"))
            if not epoch or physical < 0 or logical < 0:
                raise MaintenanceError("epoch_unverifiable")
            return {"store_epoch": epoch,
                    "hlc_physical_ms": physical,
                    "hlc_logical": logical}
        except (sqlite3.Error, TypeError, ValueError) as error:
            if isinstance(error, MaintenanceError):
                raise
            raise MaintenanceError("epoch_unverifiable") from error
        finally:
            connection.close()


def read_recording_gap(root):
    """Read the privacy-safe gap record. Unknown data is never interpreted as 0."""
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return {"state": "unknown", "reason": "root_unavailable"}
    try:
        try:
            fd = os.open("recording_gap.json", os.O_RDONLY | os.O_NOFOLLOW,
                         dir_fd=root_fd)
        except FileNotFoundError:
            return {"state": "none"}
        except OSError:
            return {"state": "unknown", "reason": "gap_unreadable"}
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                return {"state": "unknown", "reason": "gap_unsafe"}
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return {"state": "unknown", "reason": "gap_invalid"}
        required = {"gap_version", "reason", "dropped_batches",
                    "dropped_events", "dropped_retractions", "dropped_bytes",
                    "updated_at_ms"}
        if (not isinstance(value, dict) or set(value) != required
                or value.get("gap_version") != 1
                or not isinstance(value.get("reason"), str)
                or any(type(value.get(key)) is not int or value[key] < 0
                       for key in ("dropped_batches", "dropped_events",
                                   "dropped_retractions", "dropped_bytes",
                                   "updated_at_ms"))):
            return {"state": "unknown", "reason": "gap_invalid"}
        return {"state": "present", **value}
    finally:
        os.close(root_fd)


def peer_uid(sock):
    """Return the macOS getpeereid UID, never its GID."""
    getpeereid = getattr(sock, "getpeereid", None)
    if getpeereid is not None:
        uid, _gid = getpeereid()
        return uid
    getpeereid = getattr(socket_module(), "getpeereid", None)
    if getpeereid is not None:
        uid, _gid = getpeereid(sock)
        return uid
    uid = ctypes.c_uint()
    gid = ctypes.c_uint()
    function = ctypes.CDLL(None).getpeereid
    function.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint),
                         ctypes.POINTER(ctypes.c_uint)]
    function.restype = ctypes.c_int
    if function(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        raise OSError(ctypes.get_errno(), "getpeereid failed")
    return uid.value


def socket_module():
    # Keeps the fallback injectable in tests without changing the public API.
    import socket
    return socket
