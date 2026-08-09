#!/usr/bin/env python3
"""Tests for the daemon control socket (Habit130/squirrel#53).

The control socket is separate from the scoring socket, owner-only with mode
0600, verifies the peer UID via getpeereid(), and acts as the quiesce lease:
the daemon stays `prepared` until the connection sends `reopen` or drops,
then auto-recovers per the on-disk store epoch. No MLX, no model; the facts
DB is a tiny sqlite fixture.
"""

import json
import os
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from control import (  # noqa: E402
    ControlClient,
    peer_uid_matches,
    run_control_server,
)

from coordinator import MaintenanceCoordinator  # noqa: E402
from server import handle_request, serve_connection  # noqa: E402

from test_coordinator import FACT_DDL, wait_until  # noqa: E402


class StubState:
    """Model-free scoring state double for serve_connection tests."""

    def __init__(self):
        self.scoring_strategy = "mean_token"
        self.context_window = 64
        self.cache_limit_mb = 0
        self.started_at = None
        self.calls = []

    def score(self, context, candidates):
        self.calls.append((context, list(candidates)))
        return [0.5] * len(candidates)

    @property
    def loaded(self):
        return False


class StubPeerSocket:
    """Socket double with a configurable getpeereid for the UID gate."""

    def __init__(self, uid):
        self._uid = uid

    def getpeereid(self):
        return (4242, self._uid)


class ControlProtocolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lrc_")
        self.facts_root = os.path.join(self._tmp, "facts")
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o700)
        self.control_sock = os.path.join(self.facts_root,
                                         "llm-rerank-control.sock")
        self.coordinator = MaintenanceCoordinator(self.facts_root)
        self.server = run_control_server(self.control_sock,
                                         self.coordinator)
        self.client = None

    def tearDown(self):
        if self.client is not None:
            self.client.close()
        self.server["stop"]()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_facts_store(self, epoch="epoch-1", clock=(1000, 0)):
        db_path = os.path.join(self.facts_root, "facts.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.executescript(FACT_DDL)
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("fact_schema_version", "1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("event_format_version", "1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("history_id", "history-1"))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("store_epoch", epoch))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("hlc_physical_ms", str(clock[0])))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("hlc_logical", str(clock[1])))
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                     ("created_at_ms", "900"))
        conn.commit()
        conn.close()
        os.chmod(db_path, 0o600)

    def connect(self):
        self.client = ControlClient(self.control_sock)
        self.client.connect()
        return self.client

    # -- socket identity ------------------------------------------------------

    def test_control_socket_is_0600_under_owner_only_root(self):
        st = os.lstat(self.control_sock)
        self.assertTrue(stat.S_ISSOCK(st.st_mode))
        self.assertEqual(0o600, stat.S_IMODE(st.st_mode))
        self.assertEqual(os.getuid(), st.st_uid)
        # The directory is the verified 0700 facts root.
        self.assertEqual(0o700, stat.S_IMODE(os.lstat(self.facts_root)
                                             .st_mode))

    def test_peer_uid_gate(self):
        other_uid = 0 if os.geteuid() != 0 else 1
        self.assertTrue(peer_uid_matches(StubPeerSocket(os.geteuid()),
                                         os.geteuid()))
        self.assertFalse(peer_uid_matches(StubPeerSocket(other_uid),
                                          os.geteuid()))

    # -- prepare / reopen over the wire ---------------------------------------

    def test_prepare_then_reopen_same_operation(self):
        self.write_facts_store(epoch="epoch-1")
        client = self.connect()
        result = client.send("prepare_maintenance", "op-1")
        self.assertEqual("prepared", result["state"])
        self.assertEqual("op-1", result["operation_id"])
        self.assertEqual("epoch-1", result["last_fact_hlc"]["store_epoch"])
        self.assertEqual(1000, result["last_fact_hlc"]["hlc_physical_ms"])
        self.assertEqual(0, result["open_handles"])
        self.assertTrue(self.coordinator.rejects_new_scoring())

        result = client.send("reopen", "op-1")
        self.assertEqual("serving", result["state"])
        self.assertEqual("epoch-1", result["store_epoch"])
        self.assertFalse(self.coordinator.rejects_new_scoring())

    def test_reopen_with_wrong_operation_id_is_rejected(self):
        self.write_facts_store()
        client = self.connect()
        client.send("prepare_maintenance", "op-1")
        with self.assertRaises(RuntimeError) as ctx:
            client.send("reopen", "op-other")
        self.assertEqual("operation_id_mismatch", str(ctx.exception))

    def test_reopen_without_prepare_is_rejected(self):
        self.write_facts_store()
        client = self.connect()
        with self.assertRaises(RuntimeError) as ctx:
            client.send("reopen", "op-1")
        self.assertEqual("not_prepared", str(ctx.exception))

    def test_second_prepare_while_prepared_is_rejected(self):
        self.write_facts_store()
        client = self.connect()
        client.send("prepare_maintenance", "op-1")
        with self.assertRaises(RuntimeError) as ctx:
            client.send("prepare_maintenance", "op-2")
        self.assertEqual("maintenance_in_progress", str(ctx.exception))

    def test_malformed_control_requests_are_rejected(self):
        client = self.connect()
        # Control requests are not scoring requests and vice versa: the
        # scoring protocol has no "kind", and the control protocol requires
        # the exact field set. The control connection stays open (quiesce
        # lease), so the client reads exactly one response document.
        sock = client._conn
        sock.sendall((json.dumps({"version": 2, "request_id": "x",
                                  "kind": "health"}) + "\n").encode("utf-8"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        payload = b"".join(chunks)
        self.assertEqual(1, payload.count(b"\n"))
        response = json.loads(payload.decode("utf-8"))
        self.assertIn("error", response)
        self.assertEqual("invalid_request", response["error"]["code"])

    # -- quiesce lease ---------------------------------------------------------

    def test_lease_drop_auto_recovers_per_disk_epoch(self):
        self.write_facts_store(epoch="epoch-1")
        client = self.connect()
        client.send("prepare_maintenance", "op-1")
        self.assertEqual("prepared", self.coordinator.state)
        # The maintenance client dies without reopen: the control connection
        # EOF must make the daemon exit the dangling prepared state and
        # recover per the disk epoch, with serving resumed.
        client.close()
        self.client = None
        self.assertTrue(wait_until(
            lambda: self.coordinator.state == "serving"))
        self.assertFalse(self.coordinator.rejects_new_scoring())
        self.assertIsNone(
            self.coordinator.snapshot()["prepared_operation_id"])
        self.assertEqual("epoch-1",
                         self.coordinator.snapshot()["serving_epoch"])

class ScoringGateTest(unittest.TestCase):
    """serve_connection-level gate: scoring requests are tracked and refused
    while the coordinator is preparing/prepared."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lrg_")
        self.facts_root = os.path.join(self._tmp, "facts")
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o700)
        self.coordinator = MaintenanceCoordinator(self.facts_root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _request(self, request_id="r1"):
        return json.dumps({
            "version": 2, "request_id": request_id, "plan_identity": "p",
            "baseline_policy_id": "mean-token-lm-v1", "context": "ctx",
            "candidates": ["a"],
        }) + "\n"

    def _serve(self, request_text):
        left, right = socket.socketpair()
        right.sendall(request_text.encode("utf-8"))
        right.shutdown(socket.SHUT_WR)
        serve_connection(StubState(), self.coordinator, left)
        # Closing the serving end makes the reader hit EOF after the
        # response (a real server closes the connection per request).
        left.shutdown(socket.SHUT_WR)
        left.close()
        data = b""
        while True:
            chunk = right.recv(65536)
            if not chunk:
                break
            data += chunk
        right.close()
        return json.loads(data.decode("utf-8"))

    def test_serving_request_is_tracked_and_served(self):
        response = self._serve(self._request("r1"))
        self.assertIn("scores", response)
        self.assertEqual(0, self.coordinator.snapshot()["active_requests"])

    def test_request_during_prepared_is_refused(self):
        self.coordinator.begin_request("blocking")
        result_box = {}

        def prepare():
            result_box["result"] = self.coordinator.prepare_maintenance("op-1")

        thread = threading.Thread(target=prepare)
        thread.start()
        self.assertTrue(wait_until(lambda: self.coordinator.state
                                   == "preparing"))
        response = self._serve(self._request("r2"))
        self.assertEqual("maintenance_in_progress",
                         response["error"]["code"])
        self.coordinator.end_request("blocking")
        thread.join(timeout=10)
        self.assertEqual(1, result_box["result"]["drained_requests"])


if __name__ == "__main__":
    unittest.main()
