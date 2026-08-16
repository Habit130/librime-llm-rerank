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
import threading
import time


LOCK_NAME = "maintenance.lock"
LOCK_MODE = 0o600
ROOT_MODE = 0o700
GAP_LOCK_NAME = "recording_gap.lock"
GAP_INTENT_PREFIX = ".recording_gap_intent."
PROCESS_MARKER_PREFIX = ".recording_process."
_GAP_LOCK_SAFE = b"safe\n"
_GAP_LOCK_PRESENT = b"present\n"
_GAP_LOCK_UNKNOWN = b"unknown\n"
_PRESENT_GAP_REASONS = frozenset((
    "buffer_overflow_batches",
    "buffer_overflow_bytes",
    "recording_gap",
    "shutdown_unpersisted",
    "store_write_failed",
))
_UNKNOWN_GAP_REASONS = frozenset((
    "gap_persistence_failed",
    "gap_update_in_progress",
))
_GAP_FIELDS = (
    "gap_version",
    "state",
    "reason",
    "store_epoch",
    "dropped_batches",
    "dropped_events",
    "dropped_retractions",
    "dropped_bytes",
    "updated_at_ms",
)


class MaintenanceError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _reject_duplicate_json_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


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


class FactHandle:
    """A daemon fact reader whose shared lease spans its SQLite lifetime.

    The coordinator owns registration separately, but this object owns the
    ordering that matters to maintenance: close SQLite first, then release the
    shared maintenance lease, then notify its registry.
    """

    def __init__(self, root, connection_factory=sqlite3.connect, on_close=None):
        self.root = root
        self._connection_factory = connection_factory
        self._on_close = on_close
        self._lease = None
        self.connection = None
        self._closed = False
        self._connection_lock = threading.RLock()

    @classmethod
    def open(cls, root, connection_factory=sqlite3.connect, on_close=None):
        handle = cls(root, connection_factory=connection_factory,
                     on_close=on_close)
        handle._open()
        return handle

    def _open(self):
        self._lease = MaintenanceLock(self.root, exclusive=False,
                                      nonblocking=True, create=False).acquire()
        try:
            root_fd = os.open(self.root, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                try:
                    db_fd = os.open("facts.sqlite3", os.O_RDONLY | os.O_NOFOLLOW,
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
            path = os.path.join(self.root, "facts.sqlite3")
            # Read-only open semantics (AC-65-v1 repair): sqlite 3.54.0
            # returns SQLITE_CANTOPEN for a ``file:...?mode=ro`` URI open
            # of a WAL store with an active in-process writer (3.53.3
            # succeeds; docs/publish-atomic.md).  Open the plain path and
            # enforce read-only in the engine with ``PRAGMA query_only=ON``
            # -- every write statement fails with SQLITE_READONLY, the
            # same fail-closed guarantee, independent of the versioned URI
            # behavior.  The db safety check above proves the file exists
            # and is safe, so the plain open can never create it.
            self.connection = self._connection_factory(
                path,
                timeout=0,
                check_same_thread=False,
            )
            self.connection.execute("PRAGMA query_only=ON;")
        except MaintenanceError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise MaintenanceError("db_unavailable") from error

    @property
    def is_closed(self):
        return self._closed

    @property
    def lease_held(self):
        return self._lease is not None and self._lease.fd is not None

    def read_identity(self):
        with self._connection_lock:
            if self._closed or self.connection is None:
                raise MaintenanceError("db_unavailable")
            try:
                rows = dict(self.connection.execute("SELECT key, value FROM meta"))
                epoch = rows.get("store_epoch")
                physical = int(rows.get("hlc_physical_ms", "-1"))
                logical = int(rows.get("hlc_logical", "-1"))
                if not epoch or physical < 0 or logical < 0:
                    raise MaintenanceError("epoch_unverifiable")
                identity = {"store_epoch": epoch,
                            "hlc_physical_ms": physical,
                            "hlc_logical": logical}
                # history_id is additive: older test stores may not carry it
                # and the epoch gate never depends on it.
                if rows.get("history_id"):
                    identity["history_id"] = rows["history_id"]
                return identity
            except MaintenanceError:
                raise
            except (sqlite3.Error, TypeError, ValueError) as error:
                raise MaintenanceError("epoch_unverifiable") from error

    def close(self):
        close_error = None
        with self._connection_lock:
            if self._closed:
                return
            try:
                if self.connection is not None:
                    self.connection.close()
                    self.connection = None
            except Exception as error:
                close_error = error
                self.connection = None
            finally:
                # SQLite must be closed before the shared lease is released,
                # including the error path. A failed close must never strand
                # the maintenance lock.
                self._closed = True
                if self._lease is not None:
                    self._lease.release()
                    self._lease = None
        if self._on_close is not None:
            self._on_close(self)
        if close_error is not None:
            raise MaintenanceError("db_close_failed") from close_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def run_maintenance(preflight, root, replacement, control_socket, operation_id,
                    timeout_s=5.0, now=time.monotonic, sleep=time.sleep,
                    control_client_factory=None):
    """Run the production control lease around one exclusive replacement.

    The replacement itself remains an operation-specific concern for later
    tickets. This seam owns the non-negotiable ordering and keeps prepare and
    reopen on one authenticated control connection.
    """
    if control_client_factory is None:
        from control import MaintenanceControlClient
        control_client_factory = MaintenanceControlClient
    # Preflight is deliberately outside the control lease. It may perform
    # expensive validation, but it must not quiesce the daemon or acquire the
    # exclusive fact lock until all validation has passed.
    preflight()
    with control_client_factory(control_socket, operation_id) as control:
        prepared = control.prepare()
        if not prepared.get("ok"):
            return prepared
        lease = None
        try:
            control.assert_prepared()
            lease = acquire_exclusive(root, timeout_s=timeout_s, now=now,
                                      sleep=sleep)
            # A dead control connection must not be allowed to reach the
            # replacement callback. The second check is immediately adjacent
            # to the first target mutation and is also asserted after it.
            control.assert_prepared()
            replacement(lease)
            control.assert_prepared()
        finally:
            if lease is not None:
                lease.release()
            # A failed acquisition is still after prepare, so the daemon must
            # not remain quiesced merely because no replacement ran.
            recovery = control.reopen()
        return recovery


def replace_fact_database(root, replacement_path, _lease=None,
                          _connect=sqlite3.connect, _unlink=os.unlink,
                          _replace=os.replace, _fsync=os.fsync,
                          _after_checkpoint=None):
    """Replace only the fact database under an already-held exclusive lease.

    Publication is staged so a failure or crash can only ever expose the
    complete old store or the complete new store:

    1. The existing main database is validated as a regular, owner-owned
       `0600` file through the root directory fd (O_NOFOLLOW, so a symlink
       is rejected without ever following its target). Then the old database
       is checkpointed (committed WAL pages merged into the main file) while
       the exclusive lease still blocks every other connection, the main
       file is fsynced, and leftover WAL/SHM sidecars are removed.
    2. Only then is the new main database published with one atomic rename.

    A failed validation, a busy or incomplete checkpoint, or a failed
    sidecar removal aborts before the main file is touched, so the old store
    stays complete; after the rename the new store is complete and no old
    sidecar can be paired with it.

    Destructive command policy, backup validation and operation persistence
    remain caller-owned by later maintenance operations. Underscore
    parameters are the deterministic test seams for fault injection.
    """
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise MaintenanceError("root_unavailable") from error
    try:
        root_stat = os.fstat(root_fd)
        if (not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.getuid()
                or stat.S_IMODE(root_stat.st_mode) != ROOT_MODE):
            raise MaintenanceError("root_unsafe")
        source_stat = os.lstat(replacement_path)
        if (not stat.S_ISREG(source_stat.st_mode)
                or source_stat.st_uid != os.getuid()
                or stat.S_IMODE(source_stat.st_mode) != 0o600):
            raise MaintenanceError("replacement_unsafe")
        main_path = os.path.join(root, "facts.sqlite3")
        # Validate the existing main database through the directory fd before
        # any SQLite connection, checkpoint or file modification. A symlink is
        # rejected by O_NOFOLLOW without ever following the target; owner,
        # mode and file type are proven on the very fd that was opened, which
        # matches the safety seam of every other fact-store opener in this
        # module.
        try:
            main_fd = os.open("facts.sqlite3", os.O_RDONLY | os.O_NOFOLLOW,
                              dir_fd=root_fd)
        except FileNotFoundError:
            main_fd = None
        except OSError as error:
            raise MaintenanceError("replacement_failed") from error
        if main_fd is not None:
            try:
                main_stat = os.fstat(main_fd)
                if (not stat.S_ISREG(main_stat.st_mode)
                        or main_stat.st_uid != os.getuid()
                        or stat.S_IMODE(main_stat.st_mode) != 0o600):
                    raise MaintenanceError("replacement_failed")
            finally:
                os.close(main_fd)
            try:
                connection = _connect(main_path, timeout=0)
            except sqlite3.Error as error:
                raise MaintenanceError("replacement_failed") from error
            try:
                row = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
                # SQLite reports busy as 1 in the first result column; any
                # non-zero value means the checkpoint did not complete. An
                # incomplete checkpoint must abort before sidecar removal or
                # publication, because the old main file alone would not be a
                # complete old store.
                if row is None or row[0] != 0:
                    raise MaintenanceError("replacement_failed")
            except sqlite3.Error as error:
                raise MaintenanceError("replacement_failed") from error
            finally:
                connection.close()
            # The close-time checkpoint has already removed any real WAL/SHM.
            # Make the merged main file durable before anything can rename it.
            try:
                main_fd = os.open("facts.sqlite3", os.O_RDONLY | os.O_NOFOLLOW,
                                  dir_fd=root_fd)
            except OSError as error:
                raise MaintenanceError("replacement_failed") from error
            try:
                _fsync(main_fd)
            finally:
                os.close(main_fd)
        for suffix in ("-wal", "-shm"):
            try:
                _unlink(os.path.join(root, "facts.sqlite3" + suffix))
            except FileNotFoundError:
                continue
            except OSError as error:
                # Abort before publication: the old main database is still
                # complete (checkpointed), and a leftover disposable sidecar
                # is a conservative reason to refuse the replacement.
                raise MaintenanceError("replacement_failed") from error
        if _after_checkpoint is not None:
            _after_checkpoint()
        _replace(replacement_path, main_path)
        os.chmod(main_path, 0o600)
        _fsync(root_fd)
    except MaintenanceError:
        raise
    except OSError as error:
        raise MaintenanceError("replacement_failed") from error
    finally:
        os.close(root_fd)


def run_fact_replacement(preflight, root, replacement_path, control_socket,
                         operation_id, timeout_s=5.0, now=time.monotonic,
                         sleep=time.sleep, control_client_factory=None):
    """Production entrypoint for a validated exclusive fact replacement."""
    return run_maintenance(
        preflight, root,
        lambda lease: replace_fact_database(root, replacement_path, lease),
        control_socket, operation_id, timeout_s=timeout_s, now=now,
        sleep=sleep, control_client_factory=control_client_factory)


def read_fact_identity(root):
    """Read durable identity through a full-lifetime shared fact handle."""
    with FactHandle.open(root) as handle:
        return handle.read_identity()


def read_identity_under_exclusive(root, connection_factory=sqlite3.connect):
    """Read identity meta while the caller already holds the exclusive
    maintenance lease.

    This deliberately skips the shared maintenance lock (the caller owns the
    exclusive lease, so acquiring a shared lock would deadlock). It is the
    epoch re-verification seam used by the clear operation between taking the
    lease and replacing the database; it opens the same read-only identity
    projection as FactHandle and never interprets fact rows.

    The connection is opened read-write on purpose: on this host a WAL
    database without -wal/-shm sidecars cannot be opened read-only at all,
    and a freshly published clear store has none. Under the exclusive lease
    there is no other legitimate writer, and the same open materializes the
    sidecars the daemon's read-only reopen needs.
    """
    root_fd = None
    try:
        try:
            root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as error:
            raise MaintenanceError("root_unavailable") from error
        try:
            root_stat = os.fstat(root_fd)
            if (not stat.S_ISDIR(root_stat.st_mode)
                    or root_stat.st_uid != os.getuid()
                    or stat.S_IMODE(root_stat.st_mode) != ROOT_MODE):
                raise MaintenanceError("root_unsafe")
            try:
                db_fd = os.open("facts.sqlite3", os.O_RDONLY | os.O_NOFOLLOW,
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
            path = os.path.join(root, "facts.sqlite3")
            connection = connection_factory(path, timeout=0)
            try:
                rows = dict(connection.execute("SELECT key, value FROM meta"))
            finally:
                connection.close()
            epoch = rows.get("store_epoch")
            history_id = rows.get("history_id")
            physical = int(rows.get("hlc_physical_ms", "-1"))
            logical = int(rows.get("hlc_logical", "-1"))
            if not epoch or not history_id or physical < 0 or logical < 0:
                raise MaintenanceError("epoch_unverifiable")
            return {"store_epoch": epoch,
                    "history_id": history_id,
                    "hlc_physical_ms": physical,
                    "hlc_logical": logical}
        except MaintenanceError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as error:
            raise MaintenanceError("epoch_unverifiable") from error
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _gap_unknown(reason):
    return {"state": "unknown", "reason": reason}


def _gap_intent_exists(root_fd):
    try:
        return any(name.startswith(GAP_INTENT_PREFIX) for name in os.listdir(root_fd))
    except OSError:
        return True


def _recording_process_marker_status(root_fd):
    """Return whether a recorder crashed or has an uncommitted gap state.

    A live recorder holds an exclusive flock on its per-process marker. The
    marker is intentionally privacy-free; a stale marker is durable evidence
    that the process may have died between accepting an event and publishing
    its gap state. A live marker in pending/unknown state is also fail-closed.
    """
    try:
        names = [name for name in os.listdir(root_fd)
                 if name.startswith(PROCESS_MARKER_PREFIX)]
    except OSError:
        return True, "recording_marker_unreadable"
    for name in names:
        fd = None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                return True, "recording_marker_unsafe"
            state = os.pread(fd, 32, 0)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                live = False
            except BlockingIOError:
                live = True
            except OSError:
                return True, "recording_marker_unreadable"
            if state not in (b"clean\n", b"pending\n", b"unknown\n"):
                return True, "recording_marker_invalid"
            if not live or state != b"clean\n":
                return True, "recorder_process_crashed" if not live else \
                    "recording_gap_unpublished"
        except OSError:
            return True, "recording_marker_unreadable"
        finally:
            if fd is not None:
                os.close(fd)
    return False, None


def _open_gap_lock(root_fd):
    fd = None
    keep = False
    try:
        fd = os.open(GAP_LOCK_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, "gap_lock_unreadable"
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            return None, "gap_lock_unsafe"
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return None, "gap_update_in_progress"
        state = os.read(fd, 32)
        if os.read(fd, 1):
            return None, "gap_lock_invalid"
        keep = True
        return fd, state
    except OSError:
        return None, "gap_lock_unreadable"
    finally:
        # A successful caller owns the fd until it has read the JSON record.
        if fd is not None and not keep:
            os.close(fd)


def _read_gap_json(root_fd):
    try:
        fd = os.open("recording_gap.json", os.O_RDONLY | os.O_NOFOLLOW,
                     dir_fd=root_fd)
    except FileNotFoundError:
        return None, "gap_missing"
    except OSError:
        return None, "gap_unreadable"
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            return None, "gap_unsafe"
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            value = json.load(stream,
                              object_pairs_hook=_reject_duplicate_json_fields)
        fd = None
        return value, None
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None, "gap_invalid"
    finally:
        if fd is not None:
            os.close(fd)


def _validate_gap(value):
    v2_required = set(_GAP_FIELDS)
    v2_legacy_required = v2_required - {"store_epoch"}
    v1_required = v2_legacy_required - {"state"}
    if not isinstance(value, dict):
        return None
    if (set(value) == v1_required
            and type(value.get("gap_version")) is int
            and value.get("gap_version") == 1):
        value = {**value, "gap_version": 2, "state": "present",
                 "store_epoch": "unknown"}
    elif set(value) == v2_legacy_required and type(
            value.get("gap_version")) is int and value.get("gap_version") == 2:
        # The first unreleased v2 writer did not include store_epoch. Treating
        # it as unknown preserves the durable gap without echoing arbitrary
        # legacy content.
        value = {**value, "store_epoch": "unknown"}
    if (set(value) != v2_required or type(value.get("gap_version")) is not int
            or value.get("gap_version") != 2
            or value.get("state") not in ("none", "present", "unknown")
            or not isinstance(value.get("reason"), str)
            or not isinstance(value.get("store_epoch"), str)
            or not value.get("store_epoch")
            or len(value["store_epoch"]) > 64
            or any(character not in
                   "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                   for character in value["store_epoch"])
            or any(type(value.get(key)) is not int or value[key] < 0
                    for key in ("dropped_batches", "dropped_events",
                                "dropped_retractions", "dropped_bytes",
                                "updated_at_ms"))):
        return None
    state = value["state"]
    if (state == "none" and (value["reason"] != "none" or any(
            value[key] for key in ("dropped_batches", "dropped_events",
                                   "dropped_retractions", "dropped_bytes")))):
        return None
    if state == "present" and value["reason"] not in _PRESENT_GAP_REASONS:
        return None
    if state == "unknown" and value["reason"] not in _UNKNOWN_GAP_REASONS:
        return None
    return value


def read_recording_gap(root):
    """Read a stable gap record; incomplete persistence is always unknown."""
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return _gap_unknown("root_unavailable")
    try:
        root_stat = os.fstat(root_fd)
        if (not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.getuid()
                or stat.S_IMODE(root_stat.st_mode) != ROOT_MODE):
            return _gap_unknown("root_unsafe")
    except OSError:
        return _gap_unknown("root_unavailable")
    lock_fd = None
    try:
        marker_uncertain, marker_reason = _recording_process_marker_status(root_fd)
        if marker_uncertain and marker_reason != "recorder_process_crashed":
            return _gap_unknown(marker_reason)
        if _gap_intent_exists(root_fd):
            return _gap_unknown("gap_update_in_progress")
        lock_fd, lock_state = _open_gap_lock(root_fd)
        if lock_state is not None and lock_fd is None:
            return _gap_unknown(lock_state)
        # Recheck under the shared lock so a writer cannot create an intent
        # between the first directory scan and the JSON snapshot.
        if _gap_intent_exists(root_fd):
            return _gap_unknown("gap_update_in_progress")
        value, error = _read_gap_json(root_fd)
        if error is not None:
            if error == "gap_missing":
                if lock_fd is None:
                    if _gap_intent_exists(root_fd):
                        return _gap_unknown("gap_update_in_progress")
                    if marker_uncertain:
                        return _gap_unknown(marker_reason)
                    return {
                        "state": "none",
                        "reason": "none",
                        "store_epoch": None,
                        "dropped_batches": 0,
                        "dropped_events": 0,
                        "dropped_retractions": 0,
                        "dropped_bytes": 0,
                        "updated_at_ms": None,
                    }
                return _gap_unknown("gap_missing_after_initialization")
            return _gap_unknown(error)
        value = _validate_gap(value)
        if value is None:
            return _gap_unknown("gap_invalid")
        # An intent may be created after the first scan while this reader is
        # holding the shared gap lock. Recheck before returning a "none" or
        # "present" snapshot so a concurrent durable update is never hidden.
        if _gap_intent_exists(root_fd):
            return _gap_unknown("gap_update_in_progress")
        if value["state"] == "none":
            if lock_state != _GAP_LOCK_SAFE:
                return _gap_unknown("gap_lock_unverifiable")
            if marker_uncertain:
                return _gap_unknown(marker_reason)
        elif value["state"] == "present":
            if lock_state not in (None, _GAP_LOCK_SAFE, _GAP_LOCK_PRESENT):
                return _gap_unknown("gap_update_in_progress")
        return value
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
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
    try:
        function = ctypes.CDLL(None).getpeereid
    except AttributeError as error:
        raise OSError("getpeereid is unavailable") from error
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
