//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include "maintenance_lock.h"

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <thread>

namespace rime {
namespace {

constexpr mode_t kLockMode = 0600;
constexpr const char* kLockName = "maintenance.lock";

bool VerifyLockFile(int fd) {
  struct stat st;
  return fstat(fd, &st) == 0 && S_ISREG(st.st_mode) &&
         st.st_uid == getuid() && (st.st_mode & 0777) == kLockMode;
}

int OpenLockFile(const path& root) {
  int root_fd = open(root.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
  if (root_fd < 0)
    return -1;
  int fd = openat(root_fd, kLockName, O_RDWR | O_CREAT | O_NOFOLLOW,
                  kLockMode);
  close(root_fd);
  if (fd < 0)
    return -1;
  if (!VerifyLockFile(fd)) {
    close(fd);
    return -1;
  }
  return fd;
}

}  // namespace

MaintenanceLock::~MaintenanceLock() {
  Release();
  busy_ = false;
}

MaintenanceLock::MaintenanceLock(MaintenanceLock&& other) noexcept
    : fd_(other.fd_) {
  other.fd_ = -1;
}

MaintenanceLock& MaintenanceLock::operator=(MaintenanceLock&& other) noexcept {
  if (this != &other) {
    Release();
    fd_ = other.fd_;
    other.fd_ = -1;
  }
  return *this;
}

bool MaintenanceLock::Acquire(const path& root,
                              Mode mode,
                              bool non_blocking) {
  Release();
  int fd = OpenLockFile(root);
  if (fd < 0)
    return false;
  int operation = mode == Mode::kShared ? LOCK_SH : LOCK_EX;
  if (non_blocking)
    operation |= LOCK_NB;
  if (flock(fd, operation) != 0) {
    busy_ = errno == EWOULDBLOCK || errno == EAGAIN;
    close(fd);
    return false;
  }
  fd_ = fd;
  return true;
}

bool MaintenanceLock::AcquireExclusiveFor(const path& root,
                                           std::chrono::milliseconds timeout) {
  const auto deadline = std::chrono::steady_clock::now() + timeout;
  do {
    if (Acquire(root, Mode::kExclusive, true))
      return true;
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  } while (std::chrono::steady_clock::now() < deadline);
  return false;
}

void MaintenanceLock::Release() {
  if (fd_ >= 0) {
    close(fd_);
    fd_ = -1;
  }
  busy_ = false;
}

}  // namespace rime
