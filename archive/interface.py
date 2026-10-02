"""Versioned input-archive Interface shared by producer, CLI, and TUI.

CLI and TUI call this module. They do not open archive storage.
"""

from __future__ import annotations

import json
import os
import select
import socket
import stat
import struct
import threading

from archive.limits import DEFAULTS

INTERFACE_VERSION = "input-archive-v1"
ENVELOPE_VERSION = 1
CONTENT_VERSION = 1
SUPPORTED_SCHEMA = "luna_pinyin"
ORDERING = "durable_seq_ascending"

ERROR_MESSAGES = {
    "unsupported_version": "envelope or content version is not supported",
    "unsupported_schema": "schema is not a supported input-process interpretation",
    "malformed_frame": "frame is malformed",
    "event_too_large": "event exceeds the configured size limit",
    "capture_disabled": "archive capture is not enabled",
    "policy_not_effective": "producer has no fresh enabled policy observation",
    "stale_revision": "policy revision does not match the durable revision",
    "identity_conflict": "source identity was reused with different content",
    "queue_saturated": "admission queue is saturated",
    "capacity_stop": "archive capacity stop is in effect",
    "storage_failure": "archive storage failed",
    "collector_unavailable": "collector is not accepting admission",
    "unsafe_root": "archive root was rejected before writing",
    "not_found": "requested record was not found",
    "invalid_request": "request is invalid",
    "page_bound": "page size exceeds the configured bound",
    "collector_already_running": "a collector is already running for this root",
    "admission_refused": "admission was refused",
    "shutdown": "collector is shutting down",
}

CONTENT_KEYS = {
    "payload",
    "text",
    "composition",
    "candidates",
    "committed_text",
    "raw",
    "preedit",
    "comment",
}


class InterfaceError(Exception):
    def __init__(self, code):
        self.code = code if code in ERROR_MESSAGES else "invalid_request"
        super().__init__(ERROR_MESSAGES[self.code])


def error_body(code):
    stable = code if code in ERROR_MESSAGES else "invalid_request"
    return {
        "code": stable,
        "message": ERROR_MESSAGES[stable],
        "retryable": stable in {"collector_unavailable", "queue_saturated", "storage_failure"},
        "content_included": False,
    }


def failure(op, request_id, code, envelope_version=ENVELOPE_VERSION):
    return {
        "interface_version": INTERFACE_VERSION,
        "envelope_version": envelope_version if envelope_version == ENVELOPE_VERSION else ENVELOPE_VERSION,
        "op": op if isinstance(op, str) else "unknown",
        "request_id": request_id if isinstance(request_id, str) else "",
        "ok": False,
        "error": error_body(code),
        "content_included": False,
    }


def encode_frame(obj, max_bytes=None):
    limit = DEFAULTS["max_frame_bytes"] if max_bytes is None else max_bytes
    data = json.dumps(
        obj,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(data) > limit:
        raise InterfaceError("event_too_large")
    return struct.pack(">I", len(data)) + data


def _read_exact(conn, size):
    chunks = []
    remaining = size
    while remaining:
        try:
            chunk = conn.recv(remaining)
        except socket.timeout:
            return None
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(conn, max_bytes=None):
    limit = DEFAULTS["max_frame_bytes"] if max_bytes is None else max_bytes
    header = _read_exact(conn, 4)
    if header is None:
        return None
    (size,) = struct.unpack(">I", header)
    if size <= 0 or size > limit:
        raise InterfaceError("event_too_large")
    payload = _read_exact(conn, size)
    if payload is None:
        raise InterfaceError("malformed_frame")
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise InterfaceError("malformed_frame")
    if not isinstance(obj, dict):
        raise InterfaceError("malformed_frame")
    return obj


def strip_content(value):
    """Return a copy with payload-bearing keys removed."""
    if isinstance(value, list):
        return [strip_content(item) for item in value]
    if not isinstance(value, dict):
        return value
    redacted = {}
    for key, item in value.items():
        if key in CONTENT_KEYS:
            continue
        redacted[key] = strip_content(item)
    return redacted


_CWD_LOCK = threading.Lock()


def bind_unix_socket(abs_path):
    """Bind a Unix socket inside a long archive path.

    macOS sun_path is 104 bytes. Bind uses the basename after chdir so the
    inode stays in the archive root without a shorter external socket path.
    """
    directory, name = _socket_name(abs_path)
    with _CWD_LOCK:
        previous = os.getcwd()
        try:
            os.chdir(directory)
            if os.path.lexists(name):
                if stat.S_ISLNK(os.lstat(name).st_mode):
                    raise InterfaceError("unsafe_root")
                os.unlink(name)
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.bind(name)
            return conn
        finally:
            os.chdir(previous)


def connect_unix_socket(abs_path, timeout, sndbuf=None):
    """Connect without holding the cwd lock across a blocking wait."""
    directory, name = _socket_name(abs_path)
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        if sndbuf:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, int(sndbuf))
        conn.setblocking(False)
        with _CWD_LOCK:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                try:
                    conn.connect(name)
                except BlockingIOError:
                    pass
            finally:
                os.chdir(previous)
        _wait_connected(conn, timeout)
        conn.settimeout(timeout)
        return conn
    except Exception:
        conn.close()
        raise


def _socket_name(abs_path):
    if not isinstance(abs_path, str) or not os.path.isabs(abs_path):
        raise InterfaceError("invalid_request")
    directory = os.path.dirname(abs_path)
    name = os.path.basename(abs_path)
    if not directory or not name or len(name.encode("utf-8")) > 100:
        raise InterfaceError("invalid_request")
    return directory, name


def _wait_connected(conn, timeout):
    _readable, writable, _errors = select.select([], [conn], [], timeout)
    if not writable:
        raise socket.timeout("connect")
    err = conn.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
    if err:
        raise OSError(err, os.strerror(err))


def canonical_bytes(obj):
    return json.dumps(
        obj,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class Client(object):
    """Management-path client. Calls may block up to the given timeout.

    This is not the input-path admission API. Producers use archive.producer.
    """

    def __init__(self, socket_path, timeout=None, sndbuf=None):
        if not isinstance(socket_path, str) or not socket_path:
            raise InterfaceError("invalid_request")
        self.socket_path = socket_path
        self.sndbuf = sndbuf
        self.timeout = (
            DEFAULTS["management_timeout_ms"] / 1000.0 if timeout is None else timeout
        )

    def call(self, op, body=None, envelope_version=ENVELOPE_VERSION, content_version=CONTENT_VERSION, request_id=""):
        request = {
            "interface_version": INTERFACE_VERSION,
            "envelope_version": envelope_version,
            "content_version": content_version,
            "op": op,
            "request_id": request_id,
            "body": body or {},
        }
        try:
            frame = encode_frame(request)
        except InterfaceError as exc:
            return failure(op, request_id, exc.code)
        try:
            conn = connect_unix_socket(self.socket_path, self.timeout, self.sndbuf)
        except (OSError, socket.timeout, InterfaceError):
            return failure(op, request_id, "collector_unavailable")
        try:
            try:
                conn.sendall(frame)
                response = read_frame(conn)
            except InterfaceError as exc:
                return failure(op, request_id, exc.code)
            except (OSError, socket.timeout):
                return failure(op, request_id, "collector_unavailable")
        finally:
            conn.close()
        if response is None:
            return failure(op, request_id, "collector_unavailable")
        if response.get("envelope_version") != ENVELOPE_VERSION:
            return failure(op, request_id, "unsupported_version")
        if response.get("interface_version") != INTERFACE_VERSION:
            return failure(op, request_id, "unsupported_version")
        return response

    def status(self):
        return self.call("status")

    def query(self, view, **kwargs):
        body = {"view": view}
        body.update(kwargs)
        return self.call("query", body)

    def set_policy(self, desired, expected_revision):
        return self.call(
            "set_policy",
            {"desired": desired, "expected_revision": expected_revision},
        )

    def checkpoint(self):
        return self.call("checkpoint")

    def shutdown(self):
        return self.call("shutdown")
