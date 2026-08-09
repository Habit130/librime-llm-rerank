"""Owner-only maintenance control socket. It is separate from scoring."""

import json
import os
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


def _serve_connection(connection, coordinator):
    operation_id = None
    lease_id = object()
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
                response = coordinator.prepare(request["operation_id"], lease_id)
                if response.get("ok"):
                    operation_id = request["operation_id"]
            elif action == "reopen":
                response = coordinator.reopen(request["operation_id"], lease_id)
                if response.get("ok"):
                    operation_id = None
            else:
                response = {"ok": False, "code": "invalid_request"}
            _send(connection, {"version": CONTROL_VERSION, **response})
    finally:
        if operation_id is not None:
            coordinator.lease_lost(operation_id, lease_id)
        connection.close()


def run_control_server(path, coordinator, ready=None):
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
            threading.Thread(target=_serve_connection,
                             args=(connection, coordinator), daemon=True).start()
    finally:
        server.close()
        if os.path.lexists(path):
            os.unlink(path)
