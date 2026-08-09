//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_MAINTENANCE_LOCK_H_
#define RIME_MAINTENANCE_LOCK_H_

#include <sys/types.h>

#include <cstdint>
#include <string>

#include <rime/common.h>

namespace rime {

// Kernel-released advisory lock that gates fact-store maintenance
// (Habit130/squirrel#43 "维护锁与 quiesce").
//
// A single `maintenance.lock` file lives at the facts root with exact mode
// 0600. Every fact write transaction holds the lock SHARED and closes its
// SQLite connection before releasing it; restore / clear / migration take
// the lock EXCLUSIVE so no plugin transaction can be in flight while the
// fact store is replaced. The lock is a BSD flock: it is released by the
// kernel when the owning process dies, so a crashed writer or maintenance
// process can never wedge the store, and no wall-clock lease is involved.
//
// Writers use the non-blocking shared acquisition: when the exclusive lock
// is held they return `kMaintenanceLocked` immediately and the caller
// buffers the commit batch instead of waiting, so a text commit never waits
// on maintenance. Exclusive acquisition is bounded (default 5 s in the
// maintenance CLI) and on timeout nothing is modified.
class MaintenanceLock {
 public:
  enum class Status {
    kOk,
    kNoHome,            // HOME is not set; cannot locate the facts root
    kRootCreateFailed,  // root directory could not be created
    kRootNotDirectory,  // root exists but is not a directory
    kRootSymlink,       // root is a symlink
    kRootOwner,         // root is owned by another user
    kRootPermission,    // root mode is not exactly 0700
    kLockSymlink,       // maintenance.lock is a symlink
    kLockNotRegular,    // maintenance.lock is not a regular file
    kLockOwner,         // maintenance.lock is owned by another user
    kLockPermission,    // maintenance.lock mode is not exactly 0600
    kLockOpenFailed,    // maintenance.lock could not be opened
    kLockTimeout,       // exclusive acquisition exceeded its deadline
    kMaintenanceLocked, // the exclusive lock is held by another party
  };

  explicit MaintenanceLock(const path& root_dir);
  ~MaintenanceLock();

  MaintenanceLock(const MaintenanceLock&) = delete;
  MaintenanceLock& operator=(const MaintenanceLock&) = delete;

  static path DefaultPath(const path& root_dir);

  // Non-blocking shared acquisition; returns kMaintenanceLocked when the
  // exclusive lock is held. Verifies (and creates, 0600) the lock file.
  Status TryAcquireShared();

  // Non-blocking exclusive acquisition.
  Status TryAcquireExclusive();

  // Bounded exclusive acquisition: polls `TryAcquireExclusive` until the
  // deadline (default 5 s per spec) or `clock` says otherwise. On timeout
  // returns kLockTimeout with nothing modified. `clock` is injectable for
  // deterministic tests; nullptr means the wall clock.
  Status AcquireExclusive(int64_t timeout_ms,
                          int64_t (*clock)() = nullptr);

  // Releases the lock and closes the fd. Safe to call when not held.
  void Release();

  bool is_held() const { return fd_ >= 0; }

  // Stable code strings for diagnostics; never contains raw text.
  static const char* StatusCode(Status status);

 private:
  // Verifies the root and creates/verifies maintenance.lock (0600, regular,
  // owned by the current user, not a symlink). No fd is retained.
  Status EnsureFile();
  Status Acquire(int operation);

  path root_;
  int fd_ = -1;
};

}  // namespace rime

#endif  // RIME_MAINTENANCE_LOCK_H_
