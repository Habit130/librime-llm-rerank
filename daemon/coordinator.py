"""Daemon maintenance state machine: request leases, fact handles and recovery."""

import os
import threading

from maintenance import FactHandle, read_fact_identity


class _RequestLease:
    """Counts a scoring request until its terminal response write finishes."""

    def __init__(self, coordinator):
        self._coordinator = coordinator
        self._completed = False

    def complete(self):
        if self._completed:
            return
        self._completed = True
        self._coordinator._complete_request()


class _NoopDerivedRecovery:
    """Current daemon has no persisted derived cache to rebuild yet.

    Keeping this explicit lets the future builder replace a synchronous no-op
    without changing the epoch gate. A changed epoch is invalidated before the
    completion callback may make scoring available again.
    """

    def invalidate(self, previous_epoch, target_epoch):
        del previous_epoch, target_epoch

    def rebuild(self, target_epoch, complete):
        complete(target_epoch)


class MaintenanceCoordinator:
    def __init__(self, facts_root, identity_reader=read_fact_identity,
                 recovery=None, fact_handle_factory=FactHandle.open,
                 prepare_wait_hook=None, auto_open_fact_handle=False):
        self._facts_root = facts_root
        self._identity_reader = identity_reader
        self._recovery = recovery or _NoopDerivedRecovery()
        self._fact_handle_factory = fact_handle_factory
        self._prepare_wait_hook = prepare_wait_hook
        self._condition = threading.Condition()
        self._state = "serving"
        self._block_code = None
        self._closed = False
        self._prepare_active = False
        self._operation_id = None
        self._lease_id = None
        self._requests = 0
        self._opening_handles = 0
        self._handles = set()
        self._builders = set()
        self._prepared_epoch = None
        self._active_derived_epoch = None
        self._target_epoch = None
        self._auto_open_fact_handle = auto_open_fact_handle
        if auto_open_fact_handle:
            self._initialize_fact_epoch()

    def _facts_database_exists(self):
        return bool(self._facts_root) and os.path.isfile(
            os.path.join(self._facts_root, "facts.sqlite3"))

    @staticmethod
    def _valid_identity(identity):
        return (
            isinstance(identity, dict)
            and isinstance(identity.get("store_epoch"), str)
            and 1 <= len(identity["store_epoch"]) <= 64
            and all(character in
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                    for character in identity["store_epoch"])
            and type(identity.get("hlc_physical_ms")) is int
            and identity["hlc_physical_ms"] >= 0
            and type(identity.get("hlc_logical")) is int
            and identity["hlc_logical"] >= 0
        )

    def _initialize_fact_epoch(self):
        """Start serving only with a proven epoch when a fact store exists.

        A pristine installation has no fact database and therefore no derived
        state that could be stale. Once a database exists, failure to acquire
        and retain its shared lease is fail-closed rather than serving an
        unverifiable epoch.
        """
        if not self._facts_database_exists():
            return
        handle = None
        try:
            handle = self._fact_handle_factory(
                self._facts_root, on_close=self._handle_closed)
            if not isinstance(handle, FactHandle) or not handle.lease_held:
                try:
                    handle.close()
                except Exception:
                    pass
                self._state = "blocked"
                self._block_code = "fact_handle_unverifiable"
                return
            identity = handle.read_identity()
            if not self._valid_identity(identity):
                raise RuntimeError("fact identity is invalid")
        except Exception as error:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            self._state = "blocked"
            self._block_code = getattr(error, "code", "epoch_unverifiable")
            return
        self._handles.add(handle)
        self._active_derived_epoch = identity["store_epoch"]

    def begin_request(self):
        with self._condition:
            if self._closed or self._state != "serving":
                return None
            self._requests += 1
            return _RequestLease(self)

    def _complete_request(self):
        with self._condition:
            if self._requests:
                self._requests -= 1
                self._condition.notify_all()

    def end_request(self):
        """Compatibility completion for in-process callers without a lease."""
        self._complete_request()

    def _handle_closed(self, handle):
        with self._condition:
            self._handles.discard(handle)
            self._condition.notify_all()

    def assert_prepared(self, operation_id, lease_id=None):
        with self._condition:
            if (self._state != "prepared" or operation_id != self._operation_id
                    or lease_id is not self._lease_id):
                return {"ok": False, "code": "operation_id_mismatch",
                        "state": self._state}
            return {"ok": True, "state": "prepared"}

    def open_fact_handle(self):
        """Open and register a real read handle under a shared lock.

        Opening is counted before filesystem work begins, so prepare cannot
        acknowledge zero handles while a concurrent factory is still acquiring
        the shared lease or SQLite connection.
        """
        with self._condition:
            if self._closed or self._state != "serving":
                return None
            self._opening_handles += 1
        try:
            handle = self._fact_handle_factory(self._facts_root,
                                                on_close=self._handle_closed)
        except Exception:
            with self._condition:
                self._opening_handles -= 1
                self._condition.notify_all()
            raise
        with self._condition:
            if (self._state == "serving" and isinstance(handle, FactHandle)
                    and handle.lease_held):
                self._handles.add(handle)
                self._opening_handles -= 1
                self._condition.notify_all()
                return handle
            # Keep the opening count live until this rejected handle has
            # released its shared lease below. Otherwise prepare could observe
            # an empty registry while the lease still blocks replacement.
            self._condition.notify_all()
        close_error = None
        try:
            handle.close()
        except Exception as error:
            close_error = error
            self._block("fact_handle_close_failed")
        finally:
            with self._condition:
                self._opening_handles -= 1
                self._condition.notify_all()
        if close_error is not None:
            raise close_error
        return None

    def register_builder(self, builder):
        with self._condition:
            if self._closed or self._state != "serving":
                return False
            self._builders.add(builder)
            return True

    def unregister_builder(self, builder):
        with self._condition:
            self._builders.discard(builder)
            self._condition.notify_all()

    def _block(self, code):
        with self._condition:
            self._state = "blocked"
            self._block_code = code
            self._condition.notify_all()
        return {"ok": False, "code": code, "state": "blocked"}

    def _prepare_failure(self, code):
        """Leave no shared fact lease behind after a partial prepare."""
        self._close_registered_handles()
        with self._condition:
            self._builders.clear()
            self._condition.notify_all()
        return self._block(code)

    def prepare(self, operation_id, lease_id=None, lease_alive=None):
        with self._condition:
            if self._closed or self._state != "serving":
                return {"ok": False, "code": "maintenance_in_progress"}
            # Publish the lease before waiting. A control EOF can therefore
            # cancel a prepare that has not yet produced its response.
            self._state = "preparing"
            self._operation_id = operation_id
            self._lease_id = lease_id
            self._prepare_active = True
            drained_requests = self._requests
            notified_waiter = False
        try:
            with self._condition:
                while self._requests or self._opening_handles:
                    if self._state != "preparing" or self._closed:
                        return {"ok": False, "code": self._block_code,
                                "state": self._state}
                    if lease_alive is not None and not lease_alive():
                        return self._prepare_failure("control_lease_lost")
                    if not notified_waiter and self._prepare_wait_hook is not None:
                        notified_waiter = True
                        self._prepare_wait_hook()
                    self._condition.wait(0.05 if lease_alive is not None else None)
            with self._condition:
                builders = tuple(self._builders)
            for builder in builders:
                with self._condition:
                    if self._state != "preparing" or self._closed:
                        return self._prepare_failure(self._block_code or
                                                     "control_lease_lost")
                stop = getattr(builder, "request_stop", None) or getattr(
                    builder, "stop", None)
                if stop is None:
                    return self._prepare_failure("builder_not_quiesceable")
                try:
                    stop()
                    wait_idle = getattr(builder, "wait_idle", None)
                    if wait_idle is None or wait_idle() is False:
                        return self._prepare_failure("builder_not_idle")
                except Exception:
                    return self._prepare_failure("builder_quiesce_failed")
                self.unregister_builder(builder)
            with self._condition:
                handles = tuple(self._handles)
            for handle in handles:
                try:
                    handle.close()
                except Exception:
                    return self._prepare_failure("fact_handle_close_failed")
            with self._condition:
                while (self._requests or self._opening_handles or self._handles
                       or self._builders):
                    if self._state != "preparing" or self._closed:
                        return {"ok": False, "code": self._block_code,
                                "state": self._state}
                    if lease_alive is not None and not lease_alive():
                        return self._prepare_failure("control_lease_lost")
                    self._condition.wait(0.05 if lease_alive is not None else None)
            try:
                identity = self._identity_reader(self._facts_root)
            except Exception:
                identity = None
            if identity is None and self._facts_database_exists():
                return self._prepare_failure("epoch_unverifiable")
            if identity is not None and not self._valid_identity(identity):
                return self._prepare_failure("epoch_unverifiable")
            with self._condition:
                if self._closed or self._state != "preparing":
                    return {"ok": False, "code": self._block_code,
                            "state": self._state}
                self._prepared_epoch = identity["store_epoch"] if identity else None
                self._state = "prepared"
                return {
                    "ok": True,
                    "drained_requests": drained_requests,
                    "closed_handles": len(handles),
                    "open_handles": 0,
                    "builder_stopped": len(builders),
                    "last_fact_hlc": None if identity is None else {
                        "hlc_physical_ms": identity["hlc_physical_ms"],
                        "hlc_logical": identity["hlc_logical"],
                    },
                    "store_epoch": None if identity is None else identity["store_epoch"],
                }
        finally:
            with self._condition:
                self._prepare_active = False
                self._condition.notify_all()

    def reopen(self, operation_id, lease_id=None):
        with self._condition:
            if (self._state != "prepared" or operation_id != self._operation_id
                    or lease_id is not self._lease_id):
                return {"ok": False, "code": "operation_id_mismatch"}
        return self._recover(operation_id, explicit=True)

    def lease_lost(self, operation_id, lease_id=None):
        with self._condition:
            if (operation_id != self._operation_id
                    or lease_id is not self._lease_id):
                return
            if self._state == "preparing":
                self._block("control_lease_lost")
                return
            if self._state != "prepared":
                return
        self._recover(operation_id, explicit=False)

    def _clear_lease_locked(self):
        self._operation_id = None
        self._lease_id = None

    def _close_registered_handles(self):
        with self._condition:
            handles = tuple(self._handles)
        for handle in handles:
            try:
                handle.close()
            except Exception:
                pass

    def close(self):
        """Release daemon-owned fact leases during process shutdown."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._state = "blocked"
            self._block_code = "coordinator_closed"
            self._clear_lease_locked()
            self._condition.notify_all()
            while self._prepare_active or self._opening_handles:
                self._condition.wait()
        self._close_registered_handles()
        with self._condition:
            self._condition.notify_all()

    def _recover(self, operation_id, explicit):
        handle = None
        if self._facts_database_exists():
            with self._condition:
                if self._closed:
                    return self._block("coordinator_closed")
                self._opening_handles += 1
            try:
                try:
                    handle = self._fact_handle_factory(
                        self._facts_root, on_close=self._handle_closed)
                    if (not isinstance(handle, FactHandle)
                            or not handle.lease_held):
                        raise RuntimeError("fact handle has no shared lease")
                    identity = handle.read_identity()
                    if not self._valid_identity(identity):
                        raise RuntimeError("fact identity is invalid")
                finally:
                    with self._condition:
                        self._opening_handles -= 1
                        self._condition.notify_all()
            except Exception:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
                return self._block("epoch_unverifiable")
            with self._condition:
                if self._closed:
                    close_handle = handle
                else:
                    close_handle = None
            if close_handle is not None:
                try:
                    close_handle.close()
                except Exception:
                    pass
                return self._block("coordinator_closed")
        else:
            try:
                identity = self._identity_reader(self._facts_root)
            except Exception:
                identity = None
            if identity is None:
                return self._block("epoch_unverifiable")
            if not self._valid_identity(identity):
                return self._block("epoch_unverifiable")
        target_epoch = identity["store_epoch"]
        with self._condition:
            if self._closed:
                close_handle = handle
            elif target_epoch == self._prepared_epoch:
                close_handle = None
                if handle is not None:
                    self._handles.add(handle)
                self._active_derived_epoch = target_epoch
                self._target_epoch = None
                self._state = "serving"
                self._clear_lease_locked()
                return {"ok": True, "state": "serving", "explicit": explicit,
                        "store_epoch": target_epoch, "serving_ready": True}
            else:
                close_handle = None
                previous_epoch = self._active_derived_epoch or self._prepared_epoch
                if handle is not None:
                    self._handles.add(handle)
                self._active_derived_epoch = None
                self._target_epoch = target_epoch
                self._state = "catching_up"
                self._clear_lease_locked()
        if close_handle is not None:
            try:
                close_handle.close()
            except Exception:
                pass
            return self._block("coordinator_closed")
        try:
            self._recovery.invalidate(previous_epoch, target_epoch)
            self._recovery.rebuild(target_epoch, self.complete_recovery)
        except Exception:
            self._close_registered_handles()
            return self._block("epoch_recovery_failed")
        with self._condition:
            state = self._state
        return {"ok": True, "state": state, "explicit": explicit,
                "store_epoch": target_epoch, "serving_ready": state == "serving"}

    def complete_recovery(self, target_epoch):
        """Publish recovered derived state only after re-proving disk epoch."""
        with self._condition:
            if self._closed:
                close = tuple(self._handles)
            else:
                close = None
            handles = tuple(self._handles)
        if close is not None:
            for registered in close:
                try:
                    registered.close()
                except Exception:
                    pass
            return False
        handle = handles[0] if handles else None
        if handle is None:
            try:
                identity = self._identity_reader(self._facts_root)
            except Exception:
                identity = None
        else:
            try:
                identity = handle.read_identity()
            except Exception:
                self._close_registered_handles()
                self._block("epoch_unverifiable")
                return False
        with self._condition:
            if (self._closed or self._state != "catching_up"
                    or target_epoch != self._target_epoch):
                return False
            if (not self._valid_identity(identity)
                    or identity["store_epoch"] != target_epoch):
                self._state = "blocked"
                self._block_code = "epoch_changed_during_recovery"
                self._condition.notify_all()
                close = tuple(self._handles)
            else:
                self._active_derived_epoch = target_epoch
                self._target_epoch = None
                self._state = "serving"
                self._condition.notify_all()
                return True
        for registered in close:
            try:
                registered.close()
            except Exception:
                pass
        return False

    def health(self):
        with self._condition:
            return {
                "maintenance_state": self._state,
                "open_handles": len(self._handles),
                "opening_fact_handles": self._opening_handles,
                "active_derived_epoch": self._active_derived_epoch,
                "target_epoch": self._target_epoch,
            }
