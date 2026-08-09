import threading
import time
import unittest

from coordinator import MaintenanceCoordinator
from maintenance import MaintenanceError


class Handle:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Builder:
    def __init__(self):
        self.stopped = False
        self.idle = False

    def request_stop(self):
        self.stopped = True

    def wait_idle(self):
        self.idle = True


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.identity = {"store_epoch": "epoch-a", "hlc_physical_ms": 9,
                         "hlc_logical": 1}
        self.coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: dict(self.identity))

    def test_prepare_gates_before_drain_and_closes_all_handles(self):
        started = threading.Event()
        release = threading.Event()

        def request():
            self.assertTrue(self.coordinator.begin_request())
            started.set()
            release.wait()
            self.coordinator.end_request()

        worker = threading.Thread(target=request)
        worker.start()
        started.wait(1)
        handle = Handle()
        builder = Builder()
        self.assertTrue(self.coordinator.register_handle(handle))
        self.assertTrue(self.coordinator.register_builder(builder))
        result = {}
        preparing = threading.Thread(
            target=lambda: result.update(self.coordinator.prepare("op-a")))
        preparing.start()
        for _ in range(100):
            if not self.coordinator.begin_request():
                break
            self.coordinator.end_request()
            time.sleep(0.001)
        self.assertFalse(self.coordinator.register_handle(Handle()))
        self.assertFalse(self.coordinator.register_builder(Builder()))
        release.set()
        worker.join(1)
        preparing.join(1)
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["open_handles"])
        self.assertTrue(handle.closed)
        self.assertTrue(builder.stopped)
        self.assertTrue(builder.idle)
        self.assertFalse(self.coordinator.begin_request())

    def test_reopen_requires_matching_operation_and_provable_epoch(self):
        self.assertTrue(self.coordinator.prepare("op-a")["ok"])
        self.assertEqual("operation_id_mismatch",
                         self.coordinator.reopen("op-b")["code"])
        self.identity["store_epoch"] = "epoch-b"
        result = self.coordinator.reopen("op-a")
        self.assertFalse(result["ok"])
        self.assertEqual("blocked", result["state"])
        self.assertFalse(self.coordinator.begin_request())

    def test_eof_recovery_fails_closed_for_unreadable_epoch(self):
        self.assertTrue(self.coordinator.prepare("op-a")["ok"])

        def unreadable(_root):
            raise MaintenanceError("epoch_unverifiable")

        self.coordinator._identity_reader = unreadable
        self.coordinator.lease_lost("op-a")
        self.assertEqual("blocked", self.coordinator.health()["maintenance_state"])
        self.assertFalse(self.coordinator.begin_request())
