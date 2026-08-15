import os
import sqlite3
import tempfile
import threading
import unittest

from coordinator import MaintenanceCoordinator
from maintenance import FactHandle, MaintenanceError, MaintenanceLock


class Builder:
    def __init__(self):
        self.stopped = False
        self.idle = False

    def request_stop(self):
        self.stopped = True

    def wait_idle(self):
        self.idle = True


class ManualRecovery:
    def __init__(self):
        self.invalidated = []
        self._complete = None

    def invalidate(self, previous_epoch, target_epoch):
        self.invalidated.append((previous_epoch, target_epoch))

    def rebuild(self, target_epoch, complete):
        self.target_epoch = target_epoch
        self._complete = complete

    def complete(self):
        return self._complete(self.target_epoch)


def write_facts(root, epoch="epoch-a"):
    os.mkdir(root, 0o700)
    lock_fd = os.open(os.path.join(root, "maintenance.lock"),
                      os.O_WRONLY | os.O_CREAT, 0o600)
    os.fchmod(lock_fd, 0o600)
    os.close(lock_fd)
    db_path = os.path.join(root, "facts.sqlite3")
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    connection.executemany(
        "INSERT INTO meta(key, value) VALUES(?, ?)",
        [("store_epoch", epoch), ("hlc_physical_ms", "9"),
         ("hlc_logical", "1")],
    )
    connection.commit()
    connection.close()
    os.chmod(db_path, 0o600)


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.identity = {"store_epoch": "epoch-a", "hlc_physical_ms": 9,
                         "hlc_logical": 1}
        self.waiting_for_drain = threading.Event()
        self.coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: dict(self.identity),
            prepare_wait_hook=self.waiting_for_drain.set)

    def test_prepare_waits_for_response_lease_then_stops_builder(self):
        request_started = threading.Event()
        allow_response = threading.Event()
        result = {}

        def request():
            lease = self.coordinator.begin_request()
            request_started.set()
            allow_response.wait()
            lease.complete()

        worker = threading.Thread(target=request)
        worker.start()
        request_started.wait()
        builder = Builder()
        self.assertTrue(self.coordinator.register_builder(builder))

        preparing = threading.Thread(
            target=lambda: result.update(self.coordinator.prepare("op-a")))
        preparing.start()
        self.waiting_for_drain.wait()
        self.assertEqual("preparing", self.coordinator.health()["maintenance_state"])
        self.assertFalse(self.coordinator.register_builder(Builder()))
        self.assertIsNone(self.coordinator.begin_request())
        allow_response.set()
        worker.join()
        preparing.join()

        self.assertTrue(result["ok"])
        self.assertEqual(0, result["open_handles"])
        self.assertTrue(builder.stopped)
        self.assertTrue(builder.idle)
        self.assertIsNone(self.coordinator.begin_request())

    def test_prepare_closes_a_real_shared_lease_fact_handle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root)
            coordinator = MaintenanceCoordinator(root)
            handle = coordinator.open_fact_handle()
            self.assertIsNotNone(handle)
            self.assertTrue(handle.lease_held)
            with self.assertRaisesRegex(MaintenanceError, "maintenance_locked"):
                MaintenanceLock(root, exclusive=True, nonblocking=True).acquire()

            prepared = coordinator.prepare("op-handle")
            self.assertTrue(prepared["ok"])
            self.assertEqual(0, prepared["open_handles"])
            self.assertTrue(handle.is_closed)
            exclusive = MaintenanceLock(root, exclusive=True, nonblocking=True).acquire()
            exclusive.release()

    def test_daemon_startup_retains_a_real_shared_fact_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root, epoch="disk-epoch")
            coordinator = MaintenanceCoordinator(root,
                                                 auto_open_fact_handle=True)
            self.assertEqual("serving",
                             coordinator.health()["maintenance_state"])
            self.assertEqual("disk-epoch",
                             coordinator.health()["active_derived_epoch"])
            self.assertEqual(1, coordinator.health()["open_handles"])
            with self.assertRaisesRegex(MaintenanceError, "maintenance_locked"):
                MaintenanceLock(root, exclusive=True,
                                nonblocking=True).acquire()
            prepared = coordinator.prepare("op-startup")
            self.assertTrue(prepared["ok"])
            self.assertEqual(0, prepared["open_handles"])
            exclusive = MaintenanceLock(root, exclusive=True,
                                        nonblocking=True).acquire()
            exclusive.release()

    def test_fact_handle_releases_lease_after_connection_close_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root)

            class BrokenConnection:
                def close(self):
                    raise RuntimeError("close failed")

                def execute(self, _sql):
                    return []

            handle = FactHandle.open(
                root, connection_factory=lambda *args, **kwargs:
                BrokenConnection())
            with self.assertRaisesRegex(MaintenanceError, "db_close_failed"):
                handle.close()
            self.assertFalse(handle.lease_held)
            exclusive = MaintenanceLock(root, exclusive=True,
                                        nonblocking=True).acquire()
            exclusive.release()

    def test_prepare_closes_a_handle_opened_by_another_thread(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root)
            coordinator = MaintenanceCoordinator(root)
            opened = threading.Event()
            release_owner = threading.Event()
            result = {}

            def owner():
                result["handle"] = coordinator.open_fact_handle()
                opened.set()
                release_owner.wait()

            thread = threading.Thread(target=owner)
            thread.start()
            opened.wait()
            self.assertTrue(coordinator.prepare("op-threaded")["ok"])
            self.assertTrue(result["handle"].is_closed)
            release_owner.set()
            thread.join()

    def test_rejected_open_releases_its_lease_before_prepare_completes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root)
            factory_opened = threading.Event()
            allow_factory_return = threading.Event()
            prepare_waiting = threading.Event()

            def delayed_factory(path, on_close):
                handle = FactHandle.open(path, on_close=on_close)
                factory_opened.set()
                allow_factory_return.wait()
                return handle

            coordinator = MaintenanceCoordinator(
                root,
                fact_handle_factory=delayed_factory,
                prepare_wait_hook=prepare_waiting.set,
            )
            opening = threading.Thread(target=coordinator.open_fact_handle)
            opening.start()
            factory_opened.wait()
            prepared = {}
            preparing = threading.Thread(
                target=lambda: prepared.update(coordinator.prepare("op-race")))
            preparing.start()
            prepare_waiting.wait()
            allow_factory_return.set()
            opening.join()
            preparing.join()
            self.assertTrue(prepared["ok"])
            exclusive = MaintenanceLock(root, exclusive=True, nonblocking=True).acquire()
            exclusive.release()

    def test_close_waits_for_and_rejects_a_racing_handle_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root)
            factory_opened = threading.Event()
            allow_factory_return = threading.Event()

            def delayed_factory(path, on_close):
                handle = FactHandle.open(path, on_close=on_close)
                factory_opened.set()
                allow_factory_return.wait()
                return handle

            coordinator = MaintenanceCoordinator(
                root, fact_handle_factory=delayed_factory)
            opening = threading.Thread(target=coordinator.open_fact_handle)
            opening.start()
            self.assertTrue(factory_opened.wait())
            close_started = threading.Event()
            closed = threading.Event()

            def close_coordinator():
                close_started.set()
                coordinator.close()
                closed.set()

            closing = threading.Thread(target=close_coordinator)
            closing.start()
            self.assertTrue(close_started.wait())
            # close() blocks until the in-flight factory returns; releasing it
            # causally unblocks close(), so both joins are deterministic.
            allow_factory_return.set()
            opening.join()
            closing.join()
            self.assertTrue(closed.is_set())
            self.assertEqual(0, coordinator.health()["open_handles"])
            exclusive = MaintenanceLock(root, exclusive=True,
                                         nonblocking=True).acquire()
            exclusive.release()

    def test_builder_failure_closes_handles_before_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "facts")
            write_facts(root)

            class FailingBuilder:
                def request_stop(self):
                    raise RuntimeError("builder failed")

            coordinator = MaintenanceCoordinator(root)
            handle = coordinator.open_fact_handle()
            self.assertTrue(coordinator.register_builder(FailingBuilder()))
            result = coordinator.prepare("op-builder")
            self.assertFalse(result["ok"])
            self.assertEqual("blocked", result["state"])
            self.assertTrue(handle.is_closed)
            exclusive = MaintenanceLock(root, exclusive=True,
                                         nonblocking=True).acquire()
            exclusive.release()

    def test_changed_epoch_invalidates_then_catches_up_before_serving(self):
        recovery = ManualRecovery()
        coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: dict(self.identity),
            recovery=recovery)
        self.assertTrue(coordinator.prepare("op-a")["ok"])
        self.identity["store_epoch"] = "epoch-b"

        result = coordinator.reopen("op-a")
        self.assertTrue(result["ok"])
        self.assertEqual("catching_up", result["state"])
        self.assertFalse(result["serving_ready"])
        self.assertEqual([("epoch-a", "epoch-b")], recovery.invalidated)
        self.assertIsNone(coordinator.begin_request())

        self.assertTrue(recovery.complete())
        lease = coordinator.begin_request()
        self.assertIsNotNone(lease)
        lease.complete()
        self.assertEqual("serving", coordinator.health()["maintenance_state"])

    def test_eof_recovery_fails_closed_for_unreadable_epoch(self):
        self.assertTrue(self.coordinator.prepare("op-a")["ok"])

        def unreadable(_root):
            raise MaintenanceError("epoch_unverifiable")

        self.coordinator._identity_reader = unreadable
        self.coordinator.lease_lost("op-a")
        self.assertEqual("blocked", self.coordinator.health()["maintenance_state"])
        self.assertIsNone(self.coordinator.begin_request())


if __name__ == "__main__":
    unittest.main()
