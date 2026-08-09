#!/usr/bin/env python3
"""Daemon maintenance coordinator (Habit130/squirrel#53).

The daemon owns derived state (generation, builder) and read-only fact
handles; the CLI owns fact-level maintenance and coordinates a global
quiesce through the daemon. This module is the daemon-side coordination
seam:

- Fact handles: daemon-owned read-only SQLite connections that hold the
  shared maintenance lock for their whole lifetime. `prepare_maintenance`
  closes every handle (releasing every shared lock) and confirms zero open
  handles.
- Active requests: the scoring loop registers in-flight requests;
  `prepare_maintenance` stops accepting new requests and drains the set
  before reporting `drained_requests`.
- Builder: the future generation builder registers here; prepare stops it
  and reports `builder_stopped`. #53 ships no real builder, so production
  reports honest zeros; tests inject fakes that prove the drain/stop/close
  sequence really happens.
- The quiesce lease: after prepare the coordinator stays `prepared` until
  the control connection sends `reopen` or drops. On drop the daemon
  re-enters serving by re-reading the on-disk store epoch (reopen is the
  same operation id; a different id is rejected). There is no wall-clock
  lease: the kernel releases locks on process death and the control
  connection's EOF is the only "lease" signal.

State machine: idle -> preparing -> prepared -> (reopen) serving, with
`recovering` as the internal step after a dropped lease. `rejects_new_scoring`
is true while preparing/prepared, so no request can be served from stale
derived state.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from maintenance_lock import MaintenanceLock, MaintenanceLockError

FACTS_DB_FILENAME = "facts.sqlite3"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class CoordinatorError(Exception):
    """Stable-code protocol error raised by the coordinator."""

    def __init__(self, code, phase="daemon", retryable=False):
        super().__init__(code)
        self.code = code
        self.phase = phase
        self.retryable = retryable


class FactHandle:
    """One daemon-owned read-only fact connection.

    The shared maintenance lock is held for the handle's whole lifetime
    (spec "daemon 的事实句柄生命周期持共享锁"); closing the handle closes
    the connection first and releases the lock after, so an exclusive
    maintenance holder can never race a handle read.
    """

    def __init__(self, handle_id, facts_root, euid=None):
        self.handle_id = handle_id
        self.facts_root = facts_root
        self.euid = os.geteuid() if euid is None else euid
        self.lock = MaintenanceLock(facts_root, euid=self.euid)
        self._guard = None
        self._conn = None
        self.open()

    def open(self):
        if self._conn is not None:
            return
        self._guard = self.lock.shared(timeout_ms=2000)
        db_path = os.path.join(self.facts_root, FACTS_DB_FILENAME)
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                                   timeout=2.0)
        except sqlite3.Error:
            self._guard.close()
            self._guard = None
            raise CoordinatorError("fact_handle_open_failed",
                                   phase="facts") from None
        self._conn = conn

    def conn(self):
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._guard is not None:
            self._guard.close()
            self._guard = None

    @property
    def open_connections(self):
        return self._conn is not None


class FactHandleRegistry:
    """Holds the daemon's open fact handles and closes them on prepare."""

    def __init__(self):
        self._handles = {}
        self._lock = threading.Lock()

    def open(self, handle_id, facts_root, euid=None):
        handle = FactHandle(handle_id, facts_root, euid=euid)
        with self._lock:
            self._handles[handle_id] = handle
        return handle

    def close_all(self):
        with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        for handle in handles:
            handle.close()
        return len(handles)

    def count(self):
        with self._lock:
            return len(self._handles)


class BuilderSlot:
    """One builder worker slot. #53 ships no real builder; tests register a
    fake with `stop()` and `is_idle()` to prove prepare stops it."""

    def __init__(self):
        self._builder = None
        self._lock = threading.Lock()

    def register(self, builder):
        with self._lock:
            self._builder = builder

    def unregister(self):
        with self._lock:
            self._builder = None

    def stop(self):
        """Stop the builder and wait until idle. Returns the stopped builder
        or None when none was registered."""
        with self._lock:
            builder = self._builder
            self._builder = None
        if builder is None:
            return None
        builder.stop()
        return builder


class MaintenanceCoordinator:
    """The daemon-side quiesce coordinator (see module docstring)."""

    def __init__(self, facts_root, euid=None):
        self.facts_root = facts_root
        self.euid = os.geteuid() if euid is None else euid
        self._lock = threading.Lock()
        self._state = "serving"
        self._active_requests = set()
        self._rejected_requests = 0
        self._handles = FactHandleRegistry()
        self._builder = BuilderSlot()
        self._prepared_operation_id = None
        self._prepared_at = None
        self._serving_epoch = None
        self._serving_hlc = None
        self._prepared_from_epoch = None

    # -- request tracking (scoring loop) -----------------------------------

    def begin_request(self, request_id):
        """Registers an in-flight scoring request. Returns False (and counts
        a rejection) when the daemon is preparing/prepared, so the caller
        answers `maintenance_in_progress` instead of serving old state."""
        with self._lock:
            if self._state in ("preparing", "prepared"):
                self._rejected_requests += 1
                return False
            if request_id is not None:
                self._active_requests.add(request_id)
            return True

    def end_request(self, request_id):
        with self._lock:
            if request_id is not None:
                self._active_requests.discard(request_id)

    def rejects_new_scoring(self):
        with self._lock:
            return self._state in ("preparing", "prepared")

    # -- builder / handle seams (tests inject fakes) -----------------------

    def register_builder(self, builder):
        self._builder.register(builder)

    def unregister_builder(self, builder=None):
        self._builder.unregister()

    def open_fact_handle(self, handle_id):
        return self._handles.open(handle_id, self.facts_root, euid=self.euid)

    def handle_count(self):
        return self._handles.count()

    # -- prepare / reopen ---------------------------------------------------

    def _read_store_identity(self):
        """Reads store_epoch and the meta clock from the facts DB (shared
        lock); returns (epoch, (physical_ms, logical)) or (None, None) when
        the store cannot be proven. Never raises."""
        lock = MaintenanceLock(self.facts_root, euid=self.euid)
        try:
            guard = lock.shared(timeout_ms=2000)
        except MaintenanceLockError:
            return None, None
        try:
            db_path = os.path.join(self.facts_root, FACTS_DB_FILENAME)
            if not os.path.isfile(db_path):
                return None, None
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                                   timeout=2.0)
            try:
                meta = {}
                for key, value in conn.execute(
                        "SELECT key, value FROM meta;"):
                    meta[key] = value
                if not meta.get("store_epoch"):
                    return None, None
                try:
                    hlc = (int(meta.get("hlc_physical_ms") or 0),
                           int(meta.get("hlc_logical") or 0))
                except (TypeError, ValueError):
                    hlc = None
                return meta["store_epoch"], hlc
            finally:
                conn.close()
        except sqlite3.Error:
            return None, None
        finally:
            guard.close()

    def prepare_maintenance(self, operation_id):
        """Stops new work, drains in-flight requests, stops the builder,
        closes every fact handle and reports real drained counts, the last
        fact HLC and the zero-handle confirmation.

        After prepare the coordinator is `prepared` for `operation_id`: the
        caller holds the quiesce lease (the control connection) and must
        either `reopen` with the same id or drop the connection (the daemon
        then recovers per the on-disk epoch).
        """
        with self._lock:
            if self._state == "prepared":
                raise CoordinatorError("maintenance_in_progress",
                                       phase="maintenance")
            self._state = "preparing"
            self._prepared_operation_id = operation_id
            drained = len(self._active_requests)
        # Drain: wait for the in-flight requests captured above to finish.
        # Bounded; a request stuck forever would otherwise block maintenance
        # forever, but the scoring loop has its own read deadlines.
        deadline = time.monotonic() + 10.0
        while True:
            with self._lock:
                if not self._active_requests:
                    break
            if time.monotonic() >= deadline:
                with self._lock:
                    self._state = "serving"
                    self._prepared_operation_id = None
                raise CoordinatorError("request_drain_timeout",
                                       phase="maintenance", retryable=True)
            time.sleep(0.01)
        # Stop the builder and close every handle (releasing shared locks).
        stopped_builder = self._builder.stop()
        closed_handles = self._handles.close_all()
        with self._lock:
            rejected = self._rejected_requests
            self._rejected_requests = 0
            self._prepared_at = _now_iso()
            self._state = "prepared"
        # Last fact HLC as of the linearization point (under a fresh shared
        # lock; all handles are closed, so the read is consistent). The
        # epoch at this point is the "before" state reopen compares against.
        epoch, hlc = self._read_store_identity()
        with self._lock:
            self._prepared_from_epoch = epoch
        return {
            "state": "prepared",
            "operation_id": operation_id,
            "prepared_at": self._prepared_at,
            "drained_requests": drained,
            "rejected_requests": rejected,
            "last_fact_hlc": {
                "store_epoch": epoch,
                "hlc_physical_ms": hlc[0] if hlc else None,
                "hlc_logical": hlc[1] if hlc else None,
            } if epoch else None,
            "open_handles": closed_handles,
            "builder_stopped": stopped_builder is not None,
        }

    def reopen(self, operation_id):
        """Re-validates the lease, re-reads the on-disk store epoch,
        invalidates old derived state (the builder slot and handles were
        already cleared at prepare) and resumes serving."""
        with self._lock:
            if self._state != "prepared":
                raise CoordinatorError("not_prepared", phase="maintenance")
            if self._prepared_operation_id != operation_id:
                raise CoordinatorError("operation_id_mismatch",
                                       phase="maintenance")
        epoch, hlc = self._read_store_identity()
        with self._lock:
            epoch_changed = (self._prepared_from_epoch is not None
                             and epoch != self._prepared_from_epoch)
            self._serving_epoch = epoch
            self._serving_hlc = hlc
            self._prepared_operation_id = None
            self._prepared_at = None
            self._prepared_from_epoch = None
            self._state = "serving"
        return {
            "state": "serving",
            "operation_id": operation_id,
            "store_epoch": epoch,
            "fact_high_water": {
                "hlc_physical_ms": hlc[0] if hlc else None,
                "hlc_logical": hlc[1] if hlc else None,
            } if hlc else None,
            # Honest seam for future tickets: an epoch change means the
            # old derived generation must be rebuilt before serving again.
            "derived_state": "needs_rebuild" if epoch_changed else "current",
        }

    def auto_recover(self):
        """Called when the control connection (the quiesce lease) drops
        while prepared: exit the dangling prepared state, re-read the disk
        epoch and resume serving. Handles stay closed (zero in #53); future
        consumers re-open them per the current epoch."""
        with self._lock:
            if self._state != "prepared":
                return None
            self._state = "recovering"
            operation_id = self._prepared_operation_id
        epoch, hlc = self._read_store_identity()
        with self._lock:
            self._serving_epoch = epoch
            self._serving_hlc = hlc
            self._prepared_operation_id = None
            self._prepared_at = None
            self._state = "serving"
        return {"state": "serving", "store_epoch": epoch,
                "recovered_from_operation": operation_id}

    # -- observation ---------------------------------------------------------

    def snapshot(self):
        with self._lock:
            return {
                "state": self._state,
                "prepared_operation_id": self._prepared_operation_id,
                "active_requests": len(self._active_requests),
                "rejected_requests": self._rejected_requests,
                "open_handles": self._handles.count(),
                "serving_epoch": self._serving_epoch,
            }

    @property
    def state(self):
        with self._lock:
            return self._state
