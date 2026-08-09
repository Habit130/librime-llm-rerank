//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <cerrno>
#include <cstdlib>
#include <cstring>

#include <rime/common.h>

#include "maintenance_lock.h"
#include "recorder_session.h"

namespace rime {

namespace {

const char* kLockFileName = "maintenance.lock";

constexpr mode_t kDirMode = 0700;
constexpr mode_t kFileMode = 0600;

// Poll interval for bounded exclusive acquisition.
constexpr int64_t kPollIntervalMs = 10;

bool IsExactMode(const struct stat& st, mode_t mode) {
  return (st.st_mode & 0777) == mode;
}

// Creates each missing ancestor of `dir` with mode 0700, bottom-up, so the
// facts root can be established under a freshly provisioned HOME without
// touching any pre-existing directory.
bool CreateAncestors(const path& dir) {
  vector<path> missing;
  struct stat st;
  path current = dir;
  while (!current.empty() && lstat(current.c_str(), &st) != 0 &&
         errno == ENOENT) {
    missing.push_back(current);
    current = current.parent_path();
  }
  for (auto it = missing.rbegin(); it != missing.rend(); ++it) {
    if (mkdir(it->c_str(), kDirMode) != 0 && errno != EEXIST)
      return false;
  }
  return true;
}

}  // namespace

path MaintenanceLock::DefaultPath(const path& root_dir) {
  return root_dir / kLockFileName;
}

MaintenanceLock::MaintenanceLock(const path& root_dir) : root_(root_dir) {}

MaintenanceLock::~MaintenanceLock() {
  Release();
}

MaintenanceLock::Status MaintenanceLock::EnsureFile() {
  if (root_.empty())
    return Status::kNoHome;
  struct stat root_st;
  if (lstat(root_.c_str(), &root_st) != 0) {
    if (errno != ENOENT)
      return Status::kRootNotDirectory;
    if (!CreateAncestors(root_))
      return Status::kRootCreateFailed;
    if (lstat(root_.c_str(), &root_st) != 0)
      return Status::kRootCreateFailed;
  }
  if (S_ISLNK(root_st.st_mode))
    return Status::kRootSymlink;
  if (!S_ISDIR(root_st.st_mode))
    return Status::kRootNotDirectory;
  if (root_st.st_uid != getuid())
    return Status::kRootOwner;
  if (!IsExactMode(root_st, kDirMode))
    return Status::kRootPermission;

  path lock_path = DefaultPath(root_);
  struct stat st;
  if (lstat(lock_path.c_str(), &st) != 0) {
    if (errno != ENOENT)
      return Status::kLockOpenFailed;
    // Exclusive create so a racing creator cannot be silently followed
    // through a symlink; a lost race re-checks the existing file below.
    int fd = open(lock_path.c_str(), O_WRONLY | O_CREAT | O_EXCL, kFileMode);
    if (fd < 0 && errno != EEXIST)
      return Status::kLockOpenFailed;
    if (fd >= 0) {
      close(fd);
    }
    if (lstat(lock_path.c_str(), &st) != 0)
      return Status::kLockOpenFailed;
  }
  if (S_ISLNK(st.st_mode))
    return Status::kLockSymlink;
  if (!S_ISREG(st.st_mode))
    return Status::kLockNotRegular;
  if (st.st_uid != getuid())
    return Status::kLockOwner;
  if (!IsExactMode(st, kFileMode))
    return Status::kLockPermission;
  return Status::kOk;
}

MaintenanceLock::Status MaintenanceLock::Acquire(int operation) {
  if (Status ensure = EnsureFile(); ensure != Status::kOk)
    return ensure;
  path lock_path = DefaultPath(root_);
  // O_NOFOLLOW closes the lstat->open symlink window on the final component.
  int fd = open(lock_path.c_str(), O_RDONLY | O_NOFOLLOW);
  if (fd < 0)
    return Status::kLockOpenFailed;
  if (flock(fd, operation | LOCK_NB) != 0) {
    close(fd);
    if (errno == EWOULDBLOCK || errno == EAGAIN)
      return Status::kMaintenanceLocked;
    return Status::kLockOpenFailed;
  }
  if (fd_ >= 0)
    Release();
  fd_ = fd;
  return Status::kOk;
}

MaintenanceLock::Status MaintenanceLock::TryAcquireShared() {
  return Acquire(LOCK_SH);
}

MaintenanceLock::Status MaintenanceLock::TryAcquireExclusive() {
  return Acquire(LOCK_EX);
}

MaintenanceLock::Status MaintenanceLock::AcquireExclusive(int64_t timeout_ms,
                                                          int64_t (*clock)()) {
  int64_t deadline = (clock ? clock : NowMs)() + timeout_ms;
  for (;;) {
    Status status = TryAcquireExclusive();
    if (status != Status::kMaintenanceLocked)
      return status;
    int64_t now = (clock ? clock : NowMs)();
    if (now >= deadline)
      return Status::kLockTimeout;
    usleep(static_cast<useconds_t>(kPollIntervalMs * 1000));
  }
}

void MaintenanceLock::Release() {
  if (fd_ >= 0) {
    flock(fd_, LOCK_UN);
    close(fd_);
    fd_ = -1;
  }
}

const char* MaintenanceLock::StatusCode(Status status) {
  switch (status) {
    case Status::kOk:
      return "ok";
    case Status::kNoHome:
      return "no_home";
    case Status::kRootCreateFailed:
      return "root_create_failed";
    case Status::kRootNotDirectory:
      return "root_not_directory";
    case Status::kRootSymlink:
      return "root_symlink";
    case Status::kRootOwner:
      return "root_owner";
    case Status::kRootPermission:
      return "root_permission";
    case Status::kLockSymlink:
      return "lock_symlink";
    case Status::kLockNotRegular:
      return "lock_not_regular";
    case Status::kLockOwner:
      return "lock_owner";
    case Status::kLockPermission:
      return "lock_permission";
    case Status::kLockOpenFailed:
      return "lock_open_failed";
    case Status::kLockTimeout:
      return "lock_timeout";
    case Status::kMaintenanceLocked:
      return "maintenance_locked";
  }
  return "unknown";
}

}  // namespace rime
