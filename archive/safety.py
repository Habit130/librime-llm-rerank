"""Root validation, private permissions, and content-free rendering.

The threat model is one personal macOS account. These checks reject unsafe
destinations before any archive write. They do not defend same-account
compromise, and they do not claim universal sensitive-text detection.
"""

from __future__ import annotations

import os
import stat
import tempfile

DENIED_COMPONENTS = (
    "CloudStorage",
    "Dropbox",
    "OneDrive",
    "Mobile Documents",
    "iCloud",
    "Google Drive",
    "com~apple~CloudDocs",
    "Box Sync",
    "SynologyDrive",
)

UNSAFE_ROOT = "unsafe_root"


class UnsafeRoot(Exception):
    def __init__(self, reason):
        self.reason = reason
        self.code = UNSAFE_ROOT
        super().__init__(reason)


def _denied(path):
    denied = {part.casefold() for part in DENIED_COMPONENTS}
    for part in path.split(os.sep):
        if part.casefold() in denied:
            return True
    return False


def validate_root(path):
    """Reject symlink, non-owner, and known synchronized destinations.

    Does not create the root and does not follow symlinks. The parent must
    already exist so validation does not walk off creating arbitrary trees.
    """
    if not isinstance(path, str) or not path or path[0] != os.sep:
        raise UnsafeRoot("root_must_be_absolute")
    if _denied(path):
        raise UnsafeRoot("synchronized_destination")
    parent = os.path.dirname(path)
    if not parent or parent == path:
        raise UnsafeRoot("parent_missing")
    _assert_existing_chain(parent)
    if not os.path.isdir(parent):
        raise UnsafeRoot("parent_missing")
    parent_stat = os.lstat(parent)
    if parent_stat.st_uid != os.geteuid():
        raise UnsafeRoot("parent_not_owner")
    if os.path.lexists(path):
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeRoot("symlink_root")
        if not stat.S_ISDIR(info.st_mode):
            raise UnsafeRoot("root_not_directory")
        if info.st_uid != os.geteuid():
            raise UnsafeRoot("root_not_owner")
    return path


def _assert_existing_chain(path):
    current = os.sep
    relative = path[1:] if path.startswith(os.sep) else path
    for part in relative.split(os.sep):
        if not part or part == ".":
            continue
        if part == "..":
            raise UnsafeRoot("parent_escape")
        current = os.path.join(current, part) if current != os.sep else os.sep + part
        if not os.path.lexists(current):
            raise UnsafeRoot("parent_missing")
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeRoot("symlink_component")


def ensure_private_dir(path):
    validate_root(path)
    if not os.path.lexists(path):
        os.mkdir(path, 0o700)
    os.chmod(path, 0o700)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise UnsafeRoot("root_not_directory")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise UnsafeRoot("root_permissions")
    return path


def assert_private_tree(path):
    """Return whether every inode under path is owner-only."""
    problems = []
    for current, dirs, files in os.walk(path, followlinks=False):
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            problems.append("directory")
        for name in dirs + files:
            child = os.path.join(current, name)
            child_info = os.lstat(child)
            mode = stat.S_IMODE(child_info.st_mode)
            if stat.S_ISLNK(child_info.st_mode):
                problems.append("symlink")
            elif stat.S_ISDIR(child_info.st_mode):
                if mode & 0o077:
                    problems.append("directory")
            elif mode & 0o077:
                problems.append("file")
    return problems


def atomic_write(path, data):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.fchmod(fd, 0o600)
        os.close(fd)
        fd = -1
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def write_bytes(path, data):
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def escape_terminal_data(text):
    """Render untrusted text as data. No C0/C1 control byte is emitted."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    parts = []
    for char in text:
        code = ord(char)
        if code < 32 or code == 127 or 128 <= code <= 159:
            parts.append("\\u%04x" % code)
        else:
            parts.append(char)
    return "".join(parts)


_SAFE_TOKEN = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")


def safe_token(value, limit=128):
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    if any(ch not in _SAFE_TOKEN for ch in value):
        return None
    return value


def ordinary_token(value):
    token = safe_token(value)
    if token is None:
        return "redacted"
    return token
