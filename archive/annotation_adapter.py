"""Bounded private input and safe rendering shared by annotation Adapters."""

import json
import os
import stat
import termios

from archive.annotations import LINE_BYTES
from archive.interface import InterfaceError
from archive.safety import UnsafeRoot, _assert_existing_chain, escape_terminal_data


def read_private_json(stream=None, path=None, bound=LINE_BYTES):
    """No supplied content enters argv or diagnostics; refuse aliased files."""
    fd = None
    old = None
    try:
        if path is not None and path != "-":
            path = os.path.abspath(path)
            _assert_existing_chain(os.path.dirname(path))
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                raise UnsafeRoot("private_input")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                raise UnsafeRoot("private_input")
            with os.fdopen(fd, "rb") as handle:
                fd = None
                raw = handle.read(bound + 1)
        else:
            if stream is None:
                raise InterfaceError("invalid_request")
            if hasattr(stream, "isatty") and stream.isatty():
                fd_num = stream.fileno()
                old = termios.tcgetattr(fd_num)
                hidden = list(old)
                hidden[3] &= ~termios.ECHO
                termios.tcsetattr(fd_num, termios.TCSANOW, hidden)
            # One JSON line permits the TUI stream to continue after the value.
            raw = stream.readline(bound + 1)
        if len(raw) > bound or isinstance(raw, str) and len(raw.encode("utf-8")) > bound:
            raise InterfaceError("annotation_input_bound")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise InterfaceError("invalid_request")
        return value
    except (OSError, ValueError, UnicodeError, termios.error):
        raise InterfaceError("invalid_request")
    finally:
        if old is not None:
            termios.tcsetattr(stream.fileno(), termios.TCSANOW, old)
        if fd is not None:
            os.close(fd)


def render(response, private=False):
    # JSON escapes *all* controls and provides the same explicit field names
    # on both screens. No Adapter reconstructs joins or effective semantics.
    from archive.interface import strip_content

    value = response if private else strip_content(response)
    return escape_terminal_data(json.dumps(value, sort_keys=True, ensure_ascii=True)) + "\n"
