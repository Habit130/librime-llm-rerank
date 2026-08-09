//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_MAINTENANCE_LOCK_H_
#define RIME_MAINTENANCE_LOCK_H_

#include <chrono>

#include <rime/common.h>

namespace rime {

// Advisory coordination lock for the fact store. The lock file is owner-only
// and flock is intentionally used so a crashed recorder or maintainer loses
// its lease at process exit.
class MaintenanceLock {
 public:
  enum class Mode { kShared, kExclusive };

  MaintenanceLock() = default;
  ~MaintenanceLock();
  MaintenanceLock(const MaintenanceLock&) = delete;
  MaintenanceLock& operator=(const MaintenanceLock&) = delete;
  MaintenanceLock(MaintenanceLock&& other) noexcept;
  MaintenanceLock& operator=(MaintenanceLock&& other) noexcept;

  // Acquires before any SQLite connection is opened. Non-blocking shared
  // acquisition keeps the input path independent of maintenance latency.
  bool Acquire(const path& root, Mode mode, bool non_blocking = true);
  // Exclusive acquisition is bounded for maintenance callers. A timeout never
  // opens SQLite or touches the replacement target.
  bool AcquireExclusiveFor(const path& root,
                           std::chrono::milliseconds timeout);
  void Release();
  bool held() const { return fd_ >= 0; }
  bool busy() const { return busy_; }

 private:
  int fd_ = -1;
  bool busy_ = false;
};

}  // namespace rime

#endif  // RIME_MAINTENANCE_LOCK_H_
