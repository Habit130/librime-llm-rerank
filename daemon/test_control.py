import os
import socket
import tempfile
import threading
import time
import unittest

import control
import server
from coordinator import MaintenanceCoordinator


class ControlTest(unittest.TestCase):
    def test_rejects_loose_or_symlinked_control_root(self):
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
        time.sleep(0.05)
        self.assertEqual("prepared", coordinator.health()["maintenance_state"])
        right.close()
        worker.join(1)
        self.assertEqual("serving", coordinator.health()["maintenance_state"])

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
