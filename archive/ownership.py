"""Root-local exclusive collector ownership.

At most one collector owns an archive root. Ownership is an OS-backed,
non-blocking, exclusive descriptor lock (`fcntl.flock`) on the private regular
artifact `collector.lock` inside the validated root:

- acquisition precedes every managed read or mutation, so a refused contender
  never reloads, reconciles, truncates, or rebinds the winner's paths;
- the owner holds it for its whole lifetime, through active service and final
  cleanup, so a replacement cannot mutate the root while an owner is stopping;
- the kernel drops it when the owning process ends, including SIGKILL, so a
  dead owner never leaves a permanent lock and no manual unlock is required;
- the path is opened `O_NOFOLLOW` and is never unlinked or replaced, so every
  contender locks the same inode and a replacement cannot create a second lock
  domain.

A stale `collector.pid`, socket, or `collector.lock` file is metadata, not
ownership: only a currently held descriptor lock excludes. Contention is a
bounded content-free refusal, never a wait.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat

from archive.safety import UnsafeRoot, reject_alias

LOCK_NAME = "collector.lock"
REFUSED_CODE = "collector_already_running"


class OwnershipRefused(Exception):
    """Another collector holds this root. Content-free and bounded."""

    def __init__(self, code=REFUSED_CODE):
        self.code = code
        super().__init__(code)


class OwnerLock(object):
    """A stable root-local descriptor lock held for one collector lifetime."""

    def __init__(self, path):
        self.path = path
        self._fd = None

    @property
    def held(self):
        return self._fd is not None

    def acquire(self):
        if self._fd is not None:
            return
        reject_alias(self.path)
        fd = os.open(
            self.path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise UnsafeRoot("artifact_alias")
            if info.st_uid != os.geteuid():
                raise UnsafeRoot("artifact_not_owner")
            os.fchmod(fd, 0o600)
            # flock is intentionally not replaced by an existence check: the
            # check-then-write window it leaves open is exactly the defect.
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise OwnershipRefused()
                raise
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd

    def release(self):
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
