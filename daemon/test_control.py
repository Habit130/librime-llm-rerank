import json
import os
import socket
import tempfile
import threading
import unittest

import control
import maintenance
import server
from coordinator import MaintenanceCoordinator


class ControlTest(unittest.TestCase):
    def test_peer_uid_uses_uid_not_gid_on_native_and_module_paths(self):
        class NativePeer:
            def getpeereid(self):
                return (1234, 9876)

        self.assertEqual(1234, control.peer_uid(NativePeer()))

        class Module:
            @staticmethod
            def getpeereid(_peer):
                return (2345, 8765)

        original = maintenance.socket_module
        try:
            maintenance.socket_module = lambda: Module
            self.assertEqual(2345, control.peer_uid(object()))
        finally:
            maintenance.socket_module = original

    def test_peer_uid_ctypes_fallback_verifies_a_real_kernel_fd(self):
        left, _right = socket.socketpair()

        class ModuleWithoutNative:
            pass

        class ShallowPeer:
            """Real kernel fd without a socket.getpeereid method, forcing the
            libc ctypes path against the actual peer credential."""

            def __init__(self, sock):
                self._sock = sock

            def fileno(self):
                return self._sock.fileno()

        original = maintenance.socket_module
        try:
            maintenance.socket_module = lambda: ModuleWithoutNative
            self.assertEqual(os.getuid(),
                             control.peer_uid(ShallowPeer(left)))
        finally:
            maintenance.socket_module = original
            left.close()

    def test_rejects_non_owner_only_or_symlinked_control_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            os.mkdir(root, 0o755)
            with self.assertRaisesRegex(Exception, "control_root_unsafe"):
                control.validate_control_path(os.path.join(root, "control.sock"))
            os.chmod(root, 0o700)
            target = os.path.join(temp, "target")
            os.mkdir(target, 0o700)
            linked = os.path.join(temp, "linked")
            os.symlink(target, linked)
            with self.assertRaisesRegex(Exception, "control_root"):
                control.validate_control_path(os.path.join(linked, "control.sock"))

    def test_rejects_peer_with_wrong_uid(self):
        left, right = socket.socketpair()
        original = control.peer_uid
        try:
            control.peer_uid = lambda _connection: os.getuid() + 1
            coordinator = MaintenanceCoordinator(
                "/unused", identity_reader=lambda _root: {
                    "store_epoch": "epoch", "hlc_physical_ms": 0,
                    "hlc_logical": 0})
            control._serve_connection(left, coordinator)
            self.assertEqual("serving", coordinator.health()["maintenance_state"])
        finally:
            control.peer_uid = original
            right.close()

    def test_idle_lease_recovers_only_after_real_eof(self):
        left, right = socket.socketpair()
        coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: {
                "store_epoch": "epoch", "hlc_physical_ms": 0,
                "hlc_logical": 0})
        worker = threading.Thread(target=control._serve_connection,
                                  args=(left, coordinator))
        worker.start()
        right.sendall(b'{"version":1,"action":"prepare","operation_id":"op"}\n')
        self.assertIn(b'"ok": true', right.recv(4096))
        # The server is blocked in readline while the connection remains open.
        # No idle timer participates in lease ownership.
        self.assertEqual("prepared", coordinator.health()["maintenance_state"])
        right.close()
        worker.join()
        self.assertEqual("serving", coordinator.health()["maintenance_state"])
        self.assertEqual(0, coordinator.health()["open_handles"])

    def test_rejected_second_prepare_does_not_orphan_the_live_lease(self):
        left, right = socket.socketpair()
        coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: {
                "store_epoch": "epoch", "hlc_physical_ms": 0,
                "hlc_logical": 0})
        worker = threading.Thread(target=control._serve_connection,
                                  args=(left, coordinator))
        worker.start()
        reader = right.makefile("rb")
        try:
            right.sendall(b'{"version":1,"action":"prepare",'
                          b'"operation_id":"op-a"}\n')
            first = json.loads(reader.readline())
            self.assertTrue(first["ok"])
            self.assertEqual("prepared",
                             coordinator.health()["maintenance_state"])
            # The coordinator keeps the first lease; the second prepare is
            # rejected. The connection must keep serving the first lease, so
            # EOF below has to recover it rather than a stale id.
            right.sendall(b'{"version":1,"action":"prepare",'
                          b'"operation_id":"op-b"}\n')
            second = json.loads(reader.readline())
            self.assertFalse(second["ok"])
            self.assertEqual("maintenance_in_progress", second["code"])
            self.assertEqual("prepared",
                             coordinator.health()["maintenance_state"])
        finally:
            reader.close()
            right.close()
        # EOF is kernel-delivered once the peer closes, so the server thread
        # must observe it, drop the op-a lease and return to serving.
        worker.join()
        self.assertEqual("serving", coordinator.health()["maintenance_state"])
        self.assertEqual(0, coordinator.health()["open_handles"])

    def test_eof_during_prepare_does_not_leave_preparing_state(self):
        left, right = socket.socketpair()
        preparing = threading.Event()
        coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: {
                "store_epoch": "epoch", "hlc_physical_ms": 0,
                "hlc_logical": 0}, prepare_wait_hook=preparing.set)
        request_lease = coordinator.begin_request()
        worker = threading.Thread(target=control._serve_connection,
                                  args=(left, coordinator))
        worker.start()
        right.sendall(b'{"version":1,"action":"prepare",'
                      b'"operation_id":"op"}\n')
        self.assertTrue(preparing.wait())
        right.close()
        # The close is delivered as EOF by the kernel; the server thread must
        # then cancel the draining prepare and exit deterministically.
        worker.join()
        self.assertFalse(worker.is_alive())
        self.assertEqual("blocked", coordinator.health()["maintenance_state"])
        request_lease.complete()

    def test_prepared_daemon_rejects_scoring_without_calling_model(self):
        coordinator = MaintenanceCoordinator(
            "/unused", identity_reader=lambda _root: {
                "store_epoch": "epoch", "hlc_physical_ms": 0,
                "hlc_logical": 0})
        self.assertTrue(coordinator.prepare("op")["ok"])

        class State:
            scoring_strategy = server.SCORING_STRATEGY_MEAN_TOKEN
            score_called = False

            def score(self, context, candidates):
                self.score_called = True
                return [0.0 for _ in candidates]

        state = State()
        request = server.make_request("request", "plan", "private", ["private"])
        response = server.handle_request(state, __import__("json").dumps(request),
                                         coordinator)
        self.assertEqual("maintenance_in_progress", response["error"]["code"])
        self.assertFalse(state.score_called)
