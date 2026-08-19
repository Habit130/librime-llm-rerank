"""Owner-only maintenance control socket. It is separate from scoring."""

import json
import os
import select
import socket
import stat
import threading

from maintenance import MaintenanceError, peer_uid


CONTROL_VERSION = 1


def _valid_operation_id(value):
    return (isinstance(value, str) and 1 <= len(value) <= 64
            and all(character.isalnum() or character in "-_" for character in value))


def _verify_parent(path):
    parent = os.path.dirname(path)
    if not os.path.lexists(parent):
        try:
            os.mkdir(parent, 0o700)
        except OSError as error:
            raise MaintenanceError("control_root_unavailable") from error
    try:
        fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise MaintenanceError("control_root_unavailable") from error
    try:
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise MaintenanceError("control_root_unsafe")
    finally:
        os.close(fd)


def _remove_stale_socket(path):
    if not os.path.lexists(path):
        return
    info = os.lstat(path)
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise MaintenanceError("control_socket_unsafe")
    os.unlink(path)


def validate_control_path(path):
    """Fail before the scoring daemon starts if control cannot be safe."""
    _verify_parent(path)
    _remove_stale_socket(path)


def _send(connection, payload):
    connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))


class MaintenanceControlClient:
    """One authenticated control connection for a complete maintenance lease.

    `prepare` and `reopen` deliberately share this socket. Closing it without
    reopening is the daemon's fail-safe lease-loss signal, not a replacement
    for a successful reopen.
    """

    def __init__(self, path, operation_id, socket_factory=socket.socket):
        self.path = path
        self.operation_id = operation_id
        self._socket_factory = socket_factory
        self.connection = None
        self._reader = None

    def __enter__(self):
        self.connection = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.connect(self.path)
        self._reader = self.connection.makefile("rb")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def close(self):
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _request(self, action, extra=None):
        if self.connection is None or self._reader is None:
            raise MaintenanceError("control_unavailable")
        payload = {
            "version": CONTROL_VERSION,
            "action": action,
            "operation_id": self.operation_id,
        }
        if extra:
            payload.update(extra)
        try:
            _send(self.connection, payload)
            line = self._reader.readline()
        except (OSError, ValueError) as error:
            raise MaintenanceError("control_unavailable") from error
        if not line:
            raise MaintenanceError("control_unavailable")
        try:
            response = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise MaintenanceError("control_protocol_invalid") from error
        if (not isinstance(response, dict)
                or response.get("version") != CONTROL_VERSION
                or not isinstance(response.get("ok"), bool)):
            raise MaintenanceError("control_protocol_invalid")
        return response

    def prepare(self, expect_unreadable=False):
        extra = {"expect_unreadable": True} if expect_unreadable else None
        return self._request("prepare", extra)

    def reopen(self):
        return self._request("reopen")

    def assert_prepared(self):
        """Prove the control lease is still live before target mutation."""
        response = self._request("lease")
        if (not response.get("ok")
                or response.get("state") != "prepared"):
            raise MaintenanceError(response.get("code", "control_unavailable"))
        return response


def _watch_connection_eof(connection, lost, stop):
    """Observe EOF without consuming bytes from the protocol stream."""
    flags = getattr(socket, "MSG_DONTWAIT", 0)
    while not stop.wait(0.05):
        try:
            readable, _, _ = select.select([connection], [], [], 0)
            if not readable:
                continue
            data = connection.recv(1, socket.MSG_PEEK | flags)
            if not data:
                lost.set()
                return
        except (OSError, ValueError):
            lost.set()
            return


def _serve_connection(connection, coordinator):
    operation_id = None
    lease_id = object()
    lease_lost = threading.Event()
    watcher_stop = threading.Event()
    watcher = threading.Thread(target=_watch_connection_eof,
                               args=(connection, lease_lost, watcher_stop),
                               daemon=True)
    watcher.start()
    try:
        if peer_uid(connection) != os.getuid():
            return
        stream = connection.makefile("rb")
        while True:
            # There is deliberately no read deadline: only EOF drops a lease.
            line = stream.readline()
            if not line:
                break
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeError, ValueError):
                _send(connection, {"version": CONTROL_VERSION,
                                   "ok": False, "code": "invalid_request"})
                continue
            if (not isinstance(request, dict) or request.get("version") != CONTROL_VERSION
                    or not _valid_operation_id(request.get("operation_id"))):
                _send(connection, {"version": CONTROL_VERSION,
                                   "ok": False, "code": "invalid_request"})
                continue
            action = request.get("action")
            if action == "prepare":
                # The connection only owns the lease for a prepare the
                # coordinator actually accepted. Remembering a rejected
                # operation id here would make EOF recovery pass the wrong id
                # and strand the live lease of the first, successful prepare.
                response = coordinator.prepare(
                    request["operation_id"], lease_id,
                    lease_alive=lambda: not lease_lost.is_set(),
                    expect_unreadable=bool(request.get("expect_unreadable")))
                if response.get("ok"):
                    operation_id = request["operation_id"]
            elif action == "lease":
                response = coordinator.assert_prepared(request["operation_id"],
                                                       lease_id)
            elif action == "reopen":
                response = coordinator.reopen(request["operation_id"], lease_id)
                if response.get("ok"):
                    operation_id = None
            else:
                response = {"ok": False, "code": "invalid_request"}
            _send(connection, {"version": CONTROL_VERSION, **response})
    except (OSError, ValueError):
        # A client that drops the lease while prepare is draining may also
        # close before its failure response can be written.
        pass
    finally:
        watcher_stop.set()
        if operation_id is not None:
            coordinator.lease_lost(operation_id, lease_id)
        connection.close()


def run_control_server(path, coordinator, ready=None, stop=None):
    validate_control_path(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(5)
    if ready is not None:
        ready.set()
    try:
        while True:
            connection, _ = server.accept()
            if stop is not None and stop.is_set():
                connection.close()
                break
            threading.Thread(target=_serve_connection,
                             args=(connection, coordinator), daemon=True).start()
    finally:
        server.close()
        if os.path.lexists(path):
            os.unlink(path)
