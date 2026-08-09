#!/usr/bin/env python3
"""Private daemon control protocol (Habit130/squirrel#53).

The control socket is completely separate from the scoring socket: a
different path, a different protocol version and different request kinds;
the scoring endpoint rejects control requests and the control endpoint
rejects scoring requests. The control socket lives in an owner-only
directory with mode 0600, and every peer is verified with macOS
`getpeereid()` to equal the daemon's (and fact store's) owner UID.

Requests (JSON, one document per LF):

    {"version": 1, "kind": "prepare_maintenance", "operation_id": "..."}
    {"version": 1, "kind": "reopen", "operation_id": "..."}

Responses carry the same version, request_id and kind plus a versioned
`result` object, or a stable error object (code/message/occurred_at/
retryable/phase/remediation/cause).

The quiesce lease: after `prepare_maintenance` succeeds the daemon holds the
control connection open and does NOT accept a second control client. The
client either sends `reopen` (same operation id) or disconnects; a
disconnect while prepared makes the daemon `auto_recover()` — exit the
dangling prepared state, re-read the disk epoch and resume serving. There is
no wall-clock lease: the connection EOF is the only signal and the kernel
releases the flock locks on process death.
"""

import json
import os
import socket
import threading
import time
from datetime import datetime, timezone

CONTROL_PROTOCOL_VERSION = 1
KINDS = ("prepare_maintenance", "reopen")
CONTROL_SOCKET_FILENAME = "llm-rerank-control.sock"
SOCKET_MODE = 0o600
REQUEST_DEADLINE_SECONDS = 10.0


def default_control_socket(facts_root):
    """The control socket lives under the verified owner-only facts root, so
    its directory is guaranteed 0700 and the socket itself 0600."""
    return os.path.join(facts_root, CONTROL_SOCKET_FILENAME)


def make_error(code, phase="control", retryable=False, remediation=None,
               cause=None):
    return {
        "version": CONTROL_PROTOCOL_VERSION,
        "error": {
            "code": code,
            "message": code.replace("_", " "),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "retryable": retryable,
            "phase": phase,
            "remediation": remediation or "retry the request",
            "cause": cause,
        },
    }


def _reject_duplicate_object_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object field")
        value[key] = item
    return value


def _getpeereid_ctypes(fd):
    """macOS getpeereid(2) via libc (socket.getpeereid only exists on
    Python 3.13+; the daemon must run on the system Python too)."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    uid = ctypes.c_uint32()
    gid = ctypes.c_uint32()
    rc = libc.getpeereid(fd, ctypes.byref(uid), ctypes.byref(gid))
    if rc != 0:
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
    return uid.value, gid.value


def peer_uid(conn):
    """Peer UID via macOS getpeereid(); raises OSError when unavailable
    (non-macOS or non-unix socket)."""
    getpeereid = getattr(conn, "getpeereid", None)
    if getpeereid is not None:
        pid, uid = getpeereid()
        return uid
    uid, gid = _getpeereid_ctypes(conn.fileno())
    return uid


def peer_uid_matches(conn, expected_uid):
    """True when the connected peer's real UID equals `expected_uid`. On
    platforms without getpeereid the control connection is refused."""
    try:
        uid = peer_uid(conn)
    except (OSError, AttributeError):
        return False
    return uid == expected_uid


def _validate_request(data):
    """Parses one control request; returns (kind, operation_id) or
    (None, error_object)."""
    try:
        decoder = json.JSONDecoder(
            object_pairs_hook=_reject_duplicate_object_pairs)
        request, parsed_end = decoder.raw_decode(data)
        if parsed_end != len(data):
            return None, make_error("invalid_request")
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, make_error("invalid_json")
    if (not isinstance(request, dict)
            or set(request) != {"version", "kind", "operation_id"}
            or type(request["version"]) is not int
            or request["version"] != CONTROL_PROTOCOL_VERSION
            or request["kind"] not in KINDS
            or not isinstance(request["operation_id"], str)
            or not request["operation_id"]):
        return None, make_error("invalid_request")
    return request["kind"], request["operation_id"]


def _dispatch(coordinator, kind, operation_id):
    from coordinator import CoordinatorError
    try:
        if kind == "prepare_maintenance":
            return {"version": CONTROL_PROTOCOL_VERSION,
                    "kind": kind,
                    "result": coordinator.prepare_maintenance(operation_id)}
        result = coordinator.reopen(operation_id)
        return {"version": CONTROL_PROTOCOL_VERSION,
                "kind": kind,
                "result": result}
    except CoordinatorError as error:
        return make_error(error.code, phase=error.phase,
                          retryable=error.retryable)


def run_control_server(sock_path, coordinator, euid=None, poll_interval=0.05):
    """Serves one control client at a time on `sock_path`.

    Returns a dict with a `stop` callable and a `ready` event, so tests can
    run the server in a thread and shut it down deterministically. The
    server verifies the peer UID, refuses a second control client while a
    lease connection is open, and auto-recovers the coordinator when the
    lease connection drops while prepared.
    """
    if euid is None:
        euid = os.geteuid()
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, SOCKET_MODE)
    srv.listen(1)
    srv.settimeout(poll_interval)
    ready = threading.Event()
    stop_requested = threading.Event()

    def serve_connection(conn):
        try:
            if not peer_uid_matches(conn, euid):
                conn.sendall(
                    (json.dumps(make_error("control_unauthorized")) + "\n")
                    .encode("utf-8"))
                return
            while True:
                data = _read_request(conn)
                if data is None:
                    # EOF: the lease (if prepared) is dropped.
                    coordinator.auto_recover()
                    return
                kind, operation_id = _validate_request(data)
                if kind is None:
                    conn.sendall(
                        (json.dumps(operation_id) + "\n").encode("utf-8"))
                    continue
                response = _dispatch(coordinator, kind, operation_id)
                conn.sendall(
                    (json.dumps(response) + "\n").encode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            coordinator.auto_recover()
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def accept_loop():
        ready.set()
        while not stop_requested.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            serve_connection(conn)
        srv.close()
        try:
            os.unlink(sock_path)
        except OSError:
            pass

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    ready.wait(timeout=5)

    def stop():
        stop_requested.set()
        try:
            os.unlink(sock_path)
        except OSError:
            pass
        thread.join(timeout=5)

    return {"thread": thread, "ready": ready, "stop": stop}


def _read_request(conn):
    """Reads one newline-terminated JSON document with a bounded deadline.
    Returns the decoded string or None on EOF/timeout."""
    chunks = []
    deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        conn.settimeout(min(remaining, 5.0))
        try:
            chunk = conn.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            return None
        chunks.append(chunk)
        if b"\n" in chunk:
            payload = b"".join(chunks)
            if payload.count(b"\n") != 1 or not payload.endswith(b"\n"):
                return None
            return payload[:-1].decode("utf-8")


# ---------------------------------------------------------------------------
# Client side (used by the maintenance CLI and by tests)
# ---------------------------------------------------------------------------

class ControlClient:
    """Connects to the daemon control socket, verifies its identity, and
    sends control requests. The connection doubles as the quiesce lease:
    close()ing it while the daemon is prepared triggers auto-recovery."""

    def __init__(self, sock_path, euid=None):
        self.sock_path = sock_path
        self.euid = os.geteuid() if euid is None else euid
        self._conn = None

    def connect(self, timeout_s=5.0):
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(timeout_s)
        conn.connect(self.sock_path)
        if not peer_uid_matches(conn, self.euid):
            conn.close()
            raise PermissionError("control peer uid mismatch")
        self._conn = conn
        return self

    def send(self, kind, operation_id, timeout_s=30.0):
        if self._conn is None:
            raise RuntimeError("control client is not connected")
        payload = {
            "version": CONTROL_PROTOCOL_VERSION,
            "kind": kind,
            "operation_id": operation_id,
        }
        self._conn.settimeout(timeout_s)
        self._conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        # Read exactly one newline-terminated document: the daemon keeps the
        # connection open after prepare_maintenance (the quiesce lease), so
        # reading to EOF would block forever.
        chunks = []
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("control response deadline exceeded")
            self._conn.settimeout(min(remaining, 5.0))
            try:
                chunk = self._conn.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("control connection closed")
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        payload_bytes = b"".join(chunks)
        if payload_bytes.count(b"\n") != 1 or not payload_bytes.endswith(b"\n"):
            raise RuntimeError("malformed control response framing")
        response = json.loads(payload_bytes.decode("utf-8"))
        if "error" in response:
            raise RuntimeError(response["error"]["code"])
        return response["result"]

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
