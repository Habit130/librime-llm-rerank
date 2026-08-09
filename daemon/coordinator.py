"""Daemon maintenance state machine: gate, drain, close and fail closed."""

import threading

from maintenance import MaintenanceError, read_fact_identity


class MaintenanceCoordinator:
    def __init__(self, facts_root, identity_reader=read_fact_identity):
        self._facts_root = facts_root
        self._identity_reader = identity_reader
        self._condition = threading.Condition()
        self._state = "serving"
        self._operation_id = None
        self._lease_id = None
        self._requests = 0
        self._handles = set()
        self._builders = set()
        self._derived_epoch = None

    def begin_request(self):
        with self._condition:
            if self._state != "serving":
                return False
            self._requests += 1
            return True

    def end_request(self):
        with self._condition:
            self._requests -= 1
            self._condition.notify_all()

    def register_handle(self, handle):
        with self._condition:
            if self._state != "serving":
                return False
            self._handles.add(handle)
            return True

    def unregister_handle(self, handle):
        with self._condition:
            self._handles.discard(handle)
            self._condition.notify_all()

    def register_builder(self, builder):
        with self._condition:
            if self._state != "serving":
                return False
            self._builders.add(builder)
            return True

    def unregister_builder(self, builder):
        with self._condition:
            self._builders.discard(builder)
            self._condition.notify_all()

    def prepare(self, operation_id, lease_id=None):
        with self._condition:
            if self._state != "serving":
                return {"ok": False, "code": "maintenance_in_progress"}
            # This state transition shares the registration linearization lock.
            self._state = "preparing"
            drained_requests = self._requests
            while self._requests:
                self._condition.wait()
            builders = tuple(self._builders)
            handles = tuple(self._handles)
        for builder in builders:
            stop = getattr(builder, "request_stop", None) or getattr(builder, "stop")
            if stop is None:
                with self._condition:
                    self._state = "blocked"
                return {"ok": False, "code": "builder_not_quiesceable"}
            stop()
            wait_idle = getattr(builder, "wait_idle", None)
            if wait_idle is None or wait_idle() is False:
                with self._condition:
                    self._state = "blocked"
                return {"ok": False, "code": "builder_not_idle"}
        for handle in handles:
            closed = handle.close()
            wait_closed = getattr(handle, "wait_closed", None)
            if wait_closed is not None:
                wait_closed()
            is_closed = getattr(handle, "is_closed", None)
            if closed is False or (is_closed is not None and not is_closed()):
                continue
            with self._condition:
                self._handles.discard(handle)
        with self._condition:
            self._builders.difference_update(builders)
            while self._handles or self._builders:
                self._condition.wait()
            try:
                identity = self._identity_reader(self._facts_root)
            except MaintenanceError:
                identity = None
            self._derived_epoch = identity["store_epoch"] if identity else None
            self._operation_id = operation_id
            self._lease_id = lease_id
            self._state = "prepared"
            return {"ok": True, "drained_requests": drained_requests,
                    "closed_handles": len(handles), "open_handles": 0,
                    "builder_stopped": len(builders),
                    "last_fact_hlc": None if identity is None else {
                        "hlc_physical_ms": identity["hlc_physical_ms"],
                        "hlc_logical": identity["hlc_logical"]},
                    "store_epoch": None if identity is None else identity["store_epoch"]}

    def reopen(self, operation_id, lease_id=None):
        with self._condition:
            if (self._state != "prepared" or operation_id != self._operation_id
                    or lease_id is not self._lease_id):
                return {"ok": False, "code": "operation_id_mismatch"}
        return self._recover(operation_id, explicit=True)

    def lease_lost(self, operation_id, lease_id=None):
        with self._condition:
            if (self._state != "prepared" or operation_id != self._operation_id
                    or lease_id is not self._lease_id):
                return
        self._recover(operation_id, explicit=False)

    def _recover(self, operation_id, explicit):
        try:
            identity = self._identity_reader(self._facts_root)
        except MaintenanceError:
            identity = None
        with self._condition:
            if identity is None or identity["store_epoch"] != self._derived_epoch:
                self._state = "blocked"
                return {"ok": False, "code": "epoch_unverifiable",
                        "state": "blocked"}
            self._state = "serving"
            self._operation_id = None
            self._lease_id = None
            return {"ok": True, "state": "serving", "explicit": explicit,
                    "store_epoch": identity["store_epoch"]}

    def health(self):
        with self._condition:
            return {"maintenance_state": self._state,
                    "open_handles": len(self._handles)}
