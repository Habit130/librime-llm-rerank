#!/usr/bin/env python3
"""Maintenance quiesce for the CLI (Habit130/squirrel#53).

Restore / clear / migration replace the fact store, so they must briefly own
the maintenance lock EXCLUSIVELY. The CLI-side protocol (spec "维护锁与
quiesce"):

1. finish the expensive preflight first (never under the lock);
2. request `prepare_maintenance(operation_id)` from the daemon (it drains,
   stops the builder and closes its fact handles);
3. acquire the exclusive lock with a bounded timeout (default 5 s);
4. on timeout, modify nothing — no fact or derived file is touched;
5. after the replacement is fsynced, release the exclusive lock and ask the
   daemon to reopen with the same operation id.

`acquire_exclusive_guard` is step 3. The lock is a kernel `flock`: if the CLI
process dies at any point the kernel releases it, and the daemon's control
connection drop triggers its own recovery — there is no wall-clock lease.
"""

import time

from maintenance_lock import (
    DEFAULT_QUIESCE_TIMEOUT_MS,
    MaintenanceLock,
    MaintenanceLockError,
)

QUIESCE_TIMEOUT_CODE = "quiesce_timeout"


def acquire_exclusive_guard(root_dir, timeout_ms=DEFAULT_QUIESCE_TIMEOUT_MS,
                            clock=time.monotonic):
    """Bounded exclusive acquisition of `<root>/maintenance.lock`.

    Returns a guard that must be closed after the fact replacement. Raises
    `MaintenanceLockError("quiesce_timeout")` on timeout — the caller must
    not have modified any fact or derived file at that point. `clock` is
    injectable for deterministic tests (a short timeout must not sleep the
    full 5 s).
    """
    lock = MaintenanceLock(root_dir)
    try:
        return lock.exclusive(timeout_ms=timeout_ms, clock=clock)
    except MaintenanceLockError as error:
        if error.code == "lock_timeout":
            raise MaintenanceLockError(QUIESCE_TIMEOUT_CODE) from None
        raise
