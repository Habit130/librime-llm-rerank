"""Private, bounded, non-repairing I/O for collector-owned management artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from archive.interface import InterfaceError, canonical_bytes
from archive.safety import UnsafeRoot, validate_root

CHUNK = 65536
DOCUMENT = 8 * 1048576
MAX_FILES = 8192
MAX_BYTES = 2 * 1024 * 1048576
MAX_JOBS = 128
PAGE = 32


def directory(path):
    path = Path(path)
    validate_root(str(path))
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise UnsafeRoot("management_directory")
    return path


def mkdir(path):
    path = Path(path)
    directory(path.parent)
    os.mkdir(path, 0o700)
    sync(path.parent)
    return directory(path)


def regular(path):
    path = Path(path)
    directory(path.parent)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600:
        raise UnsafeRoot("management_file")
    return st


def open_read(path):
    before = regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
        os.close(fd)
        raise UnsafeRoot("management_file_changed")
    return os.fdopen(fd, "rb")


def sync(path):
    directory(path)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_all(fd, raw):
    raw = memoryview(raw)
    while raw:
        n = os.write(fd, raw)
        if n <= 0:
            raise OSError("short_write")
        raw = raw[n:]


def write_new(path, raw):
    directory(Path(path).parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    sync(Path(path).parent)


def publish(path, value):
    """Only content-free descriptors: failed pending bytes stay named and owned."""
    path = Path(path)
    directory(path.parent)
    if os.path.lexists(path):
        regular(path)
    temporary = path.with_name(path.name + ".pending")
    if os.path.lexists(temporary):
        regular(temporary)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        raw = canonical_bytes(value)
        if len(raw) > DOCUMENT:
            raise InterfaceError("management_bound")
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    sync(path.parent)


def read_json(path):
    with open_read(path) as stream:
        raw = stream.read(DOCUMENT + 1)
    if len(raw) > DOCUMENT:
        raise InterfaceError("management_bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise InterfaceError("management_corrupt")
    return value


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def identifier(value, length=64):
    if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
        raise InterfaceError("invalid_request")
    return value


def relative(value):
    if not isinstance(value, str) or len(value) > 256:
        raise UnsafeRoot("management_relative_path")
    parts = value.split("/")
    if not parts or len(parts) > 4 or any(not p or p in (".", "..") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in p) for p in parts):
        raise UnsafeRoot("management_relative_path")
    return parts


def resolve(root, name):
    path = directory(root)
    parts = relative(name)
    for part in parts[:-1]:
        path = directory(path / part)
    return path / parts[-1]


def optional(root, name):
    """Validate present parents without requiring a reserved copy to exist."""
    path = directory(root)
    parts = relative(name)
    for part in parts[:-1]:
        child = path / part
        if not os.path.lexists(child):
            return None
        path = directory(child)
    return path / parts[-1]


def measure(path, length=None):
    size, h = 0, hashlib.sha256()
    st = regular(path)
    target = st.st_size if length is None else length
    if type(target) is not int or target < 0 or target > MAX_BYTES:
        raise InterfaceError("management_bound")
    if st.st_size < target:
        raise InterfaceError("management_incomplete")
    with open_read(path) as stream:
        while size < target:
            raw = stream.read(min(CHUNK, target - size))
            if not raw:
                raise InterfaceError("management_incomplete")
            h.update(raw)
            size += len(raw)
    return {"size": size, "sha256": h.hexdigest()}


def copy(source, target, expected, progress):
    """One fixed buffer, no hardlinks, no mutation/repair of the source."""
    directory(Path(target).parent)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    size, h = 0, hashlib.sha256()
    try:
        with open_read(source) as stream:
            while size < expected["size"]:
                raw = stream.read(min(CHUNK, expected["size"] - size))
                if not raw:
                    raise InterfaceError("management_incomplete")
                write_all(fd, raw)
                size += len(raw)
                h.update(raw)
                progress(len(raw))
        if h.hexdigest() != expected["sha256"]:
            raise InterfaceError("management_tampered")
        os.fsync(fd)
    finally:
        os.close(fd)
    sync(Path(target).parent)
