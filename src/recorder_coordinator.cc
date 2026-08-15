//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include "recorder_coordinator.h"
#include "recorder_session.h"

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <charconv>
#include <chrono>
#include <cerrno>
#include <dirent.h>
#include <limits>
#include <map>
#include <memory>
#include <system_error>

namespace rime {
namespace {

constexpr int64_t kMaxBatches = 256;
constexpr int64_t kMaxBytes = 16 * 1024 * 1024;
constexpr int64_t kBatchHeaderBytes = 64;
constexpr int64_t kEventFixedBytes = 16;
constexpr int64_t kRetractionHeaderBytes = 64;
constexpr mode_t kFileMode = 0600;
constexpr mode_t kRootMode = 0700;
constexpr char kGapLockName[] = "recording_gap.lock";
constexpr char kGapIntentPrefix[] = ".recording_gap_intent.";
constexpr char kGapLockSafe[] = "safe\n";
constexpr char kGapLockPresent[] = "present\n";
constexpr char kGapLockUnknown[] = "unknown\n";
constexpr char kProcessMarkerPrefix[] = ".recording_process.";
constexpr char kProcessMarkerClean[] = "clean\n";
constexpr char kProcessMarkerPending[] = "pending\n";
constexpr char kProcessMarkerUnknown[] = "unknown\n";

struct CoordinatorRegistry {
  std::mutex mutex;
  std::condition_variable changed;
  bool shutting_down = false;
  std::map<path, std::shared_ptr<RecorderCoordinator>> coordinators;
};

CoordinatorRegistry& Registry() {
  static CoordinatorRegistry registry;
  return registry;
}

bool WriteAll(int fd, const string& text) {
  const char* data = text.data();
  size_t remaining = text.size();
  while (remaining) {
    ssize_t written = write(fd, data, remaining);
    if (written <= 0)
      return false;
    data += written;
    remaining -= static_cast<size_t>(written);
  }
  return true;
}

bool AddWithoutOverflow(int64_t* value, int64_t delta) {
  if (!value || delta < 0 || *value < 0 ||
      *value > std::numeric_limits<int64_t>::max() - delta) {
    return false;
  }
  *value += delta;
  return true;
}

void SaturatingAdd(int64_t* value, int64_t delta) {
  if (!value || delta < 0 ||
      *value > std::numeric_limits<int64_t>::max() - delta) {
    *value = std::numeric_limits<int64_t>::max();
    return;
  }
  *value += delta;
}

// The gap format deliberately has no private text. The parser only accepts the
// exact fields the writer emits; malformed prior data is never merged over or
// treated as a zero gap.
bool ReadNonNegative(const string& input, const char* key, int64_t* value) {
  const string prefix = string("\"") + key + "\":";
  size_t start = input.find(prefix);
  if (start == string::npos)
    return false;
  start += prefix.size();
  size_t end = start;
  while (end < input.size() && input[end] >= '0' && input[end] <= '9')
    ++end;
  if (end == start)
    return false;
  const char* first = input.data() + start;
  const char* last = input.data() + end;
  int64_t parsed = 0;
  const auto result = std::from_chars(first, last, parsed);
  if (result.ec != std::errc() || result.ptr != last || parsed < 0)
    return false;
  *value = parsed;
  return true;
}

bool ReadString(const string& input, const char* key, string* value) {
  const string prefix = string("\"") + key + "\":\"";
  size_t start = input.find(prefix);
  if (start == string::npos)
    return false;
  start += prefix.size();
  size_t end = input.find('"', start);
  if (end == string::npos || end == start)
    return false;
  *value = input.substr(start, end - start);
  return true;
}

struct GapFile {
  string state = "none";
  string reason = "none";
  string store_epoch = "unknown";
  int64_t batches = 0;
  int64_t events = 0;
  int64_t retractions = 0;
  int64_t bytes = 0;
};

enum class GapUpdateStatus { kOk, kFailed };

enum class GapLockState { kEmpty, kSafe, kPresent, kUnknown, kInvalid };

bool IsPresentGapReason(const string& reason) {
  return reason == "buffer_overflow_batches" ||
         reason == "buffer_overflow_bytes" || reason == "recording_gap" ||
         reason == "shutdown_unpersisted" || reason == "store_write_failed";
}

bool IsUnknownGapReason(const string& reason) {
  return reason == "gap_persistence_failed" ||
         reason == "gap_update_in_progress";
}

bool IsSafeEpoch(const string& epoch) {
  return !epoch.empty() && epoch.size() <= 64 &&
         epoch.find_first_not_of(
             "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") ==
             string::npos;
}

bool IsValidGap(const GapFile& gap) {
  if (gap.state == "none") {
    return gap.reason == "none" && !gap.batches && !gap.events &&
           !gap.retractions && !gap.bytes;
  }
  if (gap.state == "present")
    return IsPresentGapReason(gap.reason) && IsSafeEpoch(gap.store_epoch);
  if (gap.state == "unknown")
    return IsUnknownGapReason(gap.reason) && IsSafeEpoch(gap.store_epoch);
  return false;
}

bool ReadGapFile(int root_fd, bool* exists, GapFile* gap) {
  int fd = openat(root_fd, "recording_gap.json", O_RDONLY | O_NOFOLLOW);
  if (fd < 0) {
    if (errno == ENOENT) {
      *exists = false;
      *gap = GapFile();
      return true;
    }
    return false;
  }
  struct stat stat_buffer;
  if (fstat(fd, &stat_buffer) != 0 || !S_ISREG(stat_buffer.st_mode) ||
      stat_buffer.st_uid != getuid() ||
      (stat_buffer.st_mode & 0777) != kFileMode) {
    close(fd);
    return false;
  }
  string content;
  char buffer[1024];
  for (;;) {
    const ssize_t count = read(fd, buffer, sizeof(buffer));
    if (count < 0) {
      close(fd);
      return false;
    }
    if (count == 0)
      break;
    content.append(buffer, static_cast<size_t>(count));
  }
  if (close(fd) != 0)
    return false;
  int64_t version = 0;
  int64_t updated_at_ms = 0;
  GapFile parsed;
  if (!ReadNonNegative(content, "gap_version", &version) ||
      !ReadString(content, "reason", &parsed.reason) ||
      !ReadNonNegative(content, "dropped_batches", &parsed.batches) ||
      !ReadNonNegative(content, "dropped_events", &parsed.events) ||
      !ReadNonNegative(content, "dropped_retractions", &parsed.retractions) ||
      !ReadNonNegative(content, "dropped_bytes", &parsed.bytes) ||
       !ReadNonNegative(content, "updated_at_ms", &updated_at_ms)) {
    return false;
  }
  const bool has_epoch = content.find("\"store_epoch\":") != string::npos;
  if (has_epoch && !ReadString(content, "store_epoch", &parsed.store_epoch))
    return false;
  if (version == 1) {
    parsed.state = "present";
  } else if (version == 2 && ReadString(content, "state", &parsed.state)) {
  } else {
    return false;
  }
  if (!IsValidGap(parsed))
    return false;
  *exists = true;
  *gap = std::move(parsed);
  return true;
}

string GapPayload(const char* state, const char* reason, const GapFile& gap) {
  return "{\"gap_version\":2,\"state\":\"" + string(state) +
         "\",\"reason\":\"" + string(reason) +
         "\",\"store_epoch\":\"" + gap.store_epoch +
         "\",\"dropped_batches\":" + std::to_string(gap.batches) +
         ",\"dropped_events\":" + std::to_string(gap.events) +
         ",\"dropped_retractions\":" + std::to_string(gap.retractions) +
         ",\"dropped_bytes\":" + std::to_string(gap.bytes) +
         ",\"updated_at_ms\":" + std::to_string(NowMs()) + "}";
}

bool WriteGapFile(int root_fd,
                  const char* state,
                  const char* reason,
                  const GapFile& gap) {
  const string temp = ".recording_gap." + RandomUuid() + ".tmp";
  int fd = openat(root_fd, temp.c_str(), O_WRONLY | O_CREAT | O_EXCL |
                  O_NOFOLLOW, kFileMode);
  if (fd < 0)
    return false;
  bool ok = fchmod(fd, kFileMode) == 0 &&
            WriteAll(fd, GapPayload(state, reason, gap)) && fsync(fd) == 0;
  if (close(fd) != 0)
    ok = false;
  if (ok) {
    ok = renameat(root_fd, temp.c_str(), root_fd, "recording_gap.json") == 0 &&
         fsync(root_fd) == 0;
  }
  if (!ok)
    unlinkat(root_fd, temp.c_str(), 0);
  return ok;
}

bool OpenGapRoot(const path& root, int* root_fd) {
  *root_fd = open(root.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
  if (*root_fd < 0)
    return false;
  struct stat root_stat;
  if (fstat(*root_fd, &root_stat) != 0 || !S_ISDIR(root_stat.st_mode) ||
      root_stat.st_uid != getuid() ||
      (root_stat.st_mode & 0777) != kRootMode) {
    close(*root_fd);
    *root_fd = -1;
    return false;
  }
  return true;
}

bool WriteProcessMarkerState(int fd, const char* state) {
  return ftruncate(fd, 0) == 0 && lseek(fd, 0, SEEK_SET) == 0 &&
         WriteAll(fd, state) && fsync(fd) == 0;
}

bool OpenProcessMarker(const path& root, int* marker_fd, string* marker_name) {
  *marker_fd = -1;
  marker_name->clear();
  int root_fd = -1;
  if (!OpenGapRoot(root, &root_fd))
    return false;
  bool ok = false;
  for (int attempt = 0; attempt < 4 && !ok; ++attempt) {
    const string candidate = string(kProcessMarkerPrefix) + RandomUuid();
    const int fd = openat(root_fd, candidate.c_str(),
                          O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW,
                          kFileMode);
    if (fd < 0)
      continue;
    ok = fchmod(fd, kFileMode) == 0 &&
         flock(fd, LOCK_EX | LOCK_NB) == 0 &&
         WriteProcessMarkerState(fd, kProcessMarkerClean) &&
         fsync(root_fd) == 0;
    if (!ok) {
      close(fd);
      unlinkat(root_fd, candidate.c_str(), 0);
    } else {
      *marker_fd = fd;
      *marker_name = candidate;
    }
  }
  if (!ok)
    fsync(root_fd);
  close(root_fd);
  return ok;
}

bool RemoveProcessMarker(const path& root, const string& name) {
  if (name.empty())
    return true;
  int root_fd = -1;
  if (!OpenGapRoot(root, &root_fd))
    return false;
  const bool ok = unlinkat(root_fd, name.c_str(), 0) == 0 &&
                  fsync(root_fd) == 0;
  close(root_fd);
  return ok;
}

// Gap persistence runs off the input thread, so it may briefly take a shared
// fact lease to associate the diagnostic with the epoch that is currently on
// disk. Missing or unreadable facts are represented by the stable value
// "unknown", never by arbitrary database content.
string CurrentStoreEpoch(const path& root) {
  MaintenanceLock lease;
  if (!lease.Acquire(root, MaintenanceLock::Mode::kShared, true))
    return "unknown";
  struct stat db_stat;
  const path db_path = root / "facts.sqlite3";
  if (lstat(db_path.c_str(), &db_stat) != 0 || !S_ISREG(db_stat.st_mode) ||
      db_stat.st_uid != getuid() || (db_stat.st_mode & 0777) != kFileMode)
    return "unknown";
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    if (db)
      sqlite3_close(db);
    return "unknown";
  }
  sqlite3_stmt* statement = nullptr;
  string epoch;
  if (sqlite3_prepare_v2(db,
                         "SELECT value FROM meta WHERE key='store_epoch';",
                         -1, &statement, nullptr) == SQLITE_OK &&
      sqlite3_step(statement) == SQLITE_ROW) {
    const unsigned char* value = sqlite3_column_text(statement, 0);
    if (value)
      epoch = reinterpret_cast<const char*>(value);
  }
  if (statement)
    sqlite3_finalize(statement);
  sqlite3_close(db);
  return IsSafeEpoch(epoch) ? epoch : "unknown";
}

GapUpdateStatus OpenGapLock(const path& root, int* root_fd, int* lock_fd) {
  *lock_fd = -1;
  if (!OpenGapRoot(root, root_fd))
    return GapUpdateStatus::kFailed;
  *lock_fd = openat(*root_fd, kGapLockName,
                    O_RDWR | O_CREAT | O_NOFOLLOW, kFileMode);
  if (*lock_fd < 0) {
    close(*root_fd);
    *root_fd = -1;
    return GapUpdateStatus::kFailed;
  }
  struct stat lock_stat;
  if (fstat(*lock_fd, &lock_stat) != 0 || !S_ISREG(lock_stat.st_mode) ||
      lock_stat.st_uid != getuid() || fchmod(*lock_fd, kFileMode) != 0 ||
      (lock_stat.st_mode & 0777) != kFileMode) {
    close(*lock_fd);
    close(*root_fd);
    *lock_fd = -1;
    *root_fd = -1;
    return GapUpdateStatus::kFailed;
  }
  // This function is only called by the recorder worker, never by the input
  // notifier. Blocking here serializes cross-process gap accumulation without
  // making the hot path wait on flock or fsync.
  if (flock(*lock_fd, LOCK_EX) != 0) {
    close(*lock_fd);
    close(*root_fd);
    *lock_fd = -1;
    *root_fd = -1;
    return GapUpdateStatus::kFailed;
  }
  return GapUpdateStatus::kOk;
}

void CloseGapLock(int root_fd, int lock_fd) {
  if (lock_fd >= 0)
    close(lock_fd);
  if (root_fd >= 0)
    close(root_fd);
}

GapLockState ReadGapLockState(int lock_fd) {
  char buffer[16];
  const ssize_t count = pread(lock_fd, buffer, sizeof(buffer), 0);
  if (count == 0)
    return GapLockState::kEmpty;
  const string value(buffer, count > 0 ? static_cast<size_t>(count) : 0);
  if (value == kGapLockSafe)
    return GapLockState::kSafe;
  if (value == kGapLockPresent)
    return GapLockState::kPresent;
  if (value == kGapLockUnknown)
    return GapLockState::kUnknown;
  return GapLockState::kInvalid;
}

bool WriteGapLockState(int lock_fd, const char* state) {
  return ftruncate(lock_fd, 0) == 0 && lseek(lock_fd, 0, SEEK_SET) == 0 &&
         WriteAll(lock_fd, state) && fsync(lock_fd) == 0;
}

bool HasGapIntent(int root_fd, bool* present) {
  *present = false;
  const int copy = dup(root_fd);
  if (copy < 0)
    return false;
  DIR* directory = fdopendir(copy);
  if (!directory) {
    close(copy);
    return false;
  }
  errno = 0;
  while (dirent* entry = readdir(directory)) {
    const string name(entry->d_name);
    if (name.compare(0, sizeof(kGapIntentPrefix) - 1, kGapIntentPrefix) == 0) {
      *present = true;
      break;
    }
  }
  const bool ok = errno == 0;
  closedir(directory);
  return ok;
}

bool CreateGapIntent(const path& root, string* name) {
  int root_fd = -1;
  if (!OpenGapRoot(root, &root_fd))
    return false;
  bool ok = false;
  for (int attempt = 0; attempt < 4 && !ok; ++attempt) {
    const string candidate = string(kGapIntentPrefix) + RandomUuid();
    const int fd = openat(root_fd, candidate.c_str(),
                          O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
                          kFileMode);
    if (fd < 0) {
      if (errno == EEXIST)
        continue;
      break;
    }
    ok = fchmod(fd, kFileMode) == 0 && WriteAll(fd, kGapLockUnknown) &&
         fsync(fd) == 0;
    if (close(fd) != 0)
      ok = false;
    if (ok)
      ok = fsync(root_fd) == 0;
    if (!ok)
      unlinkat(root_fd, candidate.c_str(), 0);
    else
      *name = candidate;
  }
  close(root_fd);
  return ok;
}

bool RemoveGapIntent(const path& root, const string& name) {
  if (name.empty())
    return true;
  int root_fd = -1;
  if (!OpenGapRoot(root, &root_fd))
    return false;
  const bool ok = unlinkat(root_fd, name.c_str(), 0) == 0 &&
                  fsync(root_fd) == 0;
  close(root_fd);
  return ok;
}

GapUpdateStatus EnsureGapState(const path& root) {
  int root_fd = -1;
  int lock_fd = -1;
  GapUpdateStatus status = OpenGapLock(root, &root_fd, &lock_fd);
  if (status != GapUpdateStatus::kOk)
    return status;
  bool has_intent = false;
  bool exists = false;
  GapFile gap;
  bool ok = HasGapIntent(root_fd, &has_intent) &&
            ReadGapFile(root_fd, &exists, &gap);
  if (ok && has_intent) {
    CloseGapLock(root_fd, lock_fd);
    return GapUpdateStatus::kOk;
  }
  const GapLockState lock_state = ok ? ReadGapLockState(lock_fd)
                                      : GapLockState::kInvalid;
  if (ok && !exists) {
    gap.store_epoch = CurrentStoreEpoch(root);
    ok = lock_state == GapLockState::kEmpty &&
         WriteGapLockState(lock_fd, kGapLockSafe) &&
         WriteGapFile(root_fd, "none", "none", gap);
  } else if (ok && gap.state == "none") {
    ok = lock_state == GapLockState::kSafe;
  } else if (ok && gap.state == "present" &&
             lock_state == GapLockState::kEmpty) {
    ok = WriteGapLockState(lock_fd, kGapLockPresent);
  } else if (ok && gap.state == "present") {
    ok = lock_state == GapLockState::kSafe ||
         lock_state == GapLockState::kPresent;
  } else if (ok && gap.state == "unknown") {
    ok = lock_state == GapLockState::kUnknown;
  }
  CloseGapLock(root_fd, lock_fd);
  return ok ? GapUpdateStatus::kOk : GapUpdateStatus::kFailed;
}

GapUpdateStatus UpdateGap(const path& root,
                          const char* reason,
                          int64_t batches,
                          int64_t events,
                          int64_t retractions,
                          int64_t bytes) {
  int root_fd = -1;
  int lock_fd = -1;
  GapUpdateStatus status = OpenGapLock(root, &root_fd, &lock_fd);
  if (status != GapUpdateStatus::kOk)
    return status;
  bool exists = false;
  GapFile gap;
  bool ok = WriteGapLockState(lock_fd, kGapLockUnknown) &&
            ReadGapFile(root_fd, &exists, &gap);
  if (ok && gap.state == "unknown") {
    CloseGapLock(root_fd, lock_fd);
    return GapUpdateStatus::kOk;
  }
  ok = ok && AddWithoutOverflow(&gap.batches, batches) &&
       AddWithoutOverflow(&gap.events, events) &&
       AddWithoutOverflow(&gap.retractions, retractions) &&
       AddWithoutOverflow(&gap.bytes, bytes);
  if (gap.store_epoch == "unknown")
    gap.store_epoch = CurrentStoreEpoch(root);
  // The lock state is already durable unknown. A failed replacement cannot
  // make an older state=none record trustworthy again.
  if (ok)
    ok = WriteGapFile(root_fd, "unknown", "gap_update_in_progress", gap);
  if (ok)
    ok = WriteGapFile(root_fd, "present", reason, gap);
  if (ok)
    ok = WriteGapLockState(lock_fd, kGapLockPresent);
  CloseGapLock(root_fd, lock_fd);
  return ok ? GapUpdateStatus::kOk : GapUpdateStatus::kFailed;
}

GapUpdateStatus MarkGapUnknown(const path& root) {
  int root_fd = -1;
  int lock_fd = -1;
  GapUpdateStatus status = OpenGapLock(root, &root_fd, &lock_fd);
  if (status != GapUpdateStatus::kOk)
    return status;
  GapFile gap;
  bool exists = false;
  bool ok = WriteGapLockState(lock_fd, kGapLockUnknown);
  if (ok && ReadGapFile(root_fd, &exists, &gap)) {
    if (gap.store_epoch == "unknown")
      gap.store_epoch = CurrentStoreEpoch(root);
    WriteGapFile(root_fd, "unknown", "gap_persistence_failed", gap);
  }
  CloseGapLock(root_fd, lock_fd);
  return ok ? GapUpdateStatus::kOk : GapUpdateStatus::kFailed;
}

}  // namespace

std::shared_ptr<RecorderCoordinator> RecorderCoordinator::ForRoot(
    const path& root) {
  CoordinatorRegistry& registry = Registry();
  std::unique_lock<std::mutex> lock(registry.mutex);
  registry.changed.wait(lock, [&registry] { return !registry.shutting_down; });
  auto& coordinator = registry.coordinators[root];
  if (!coordinator)
    coordinator = std::shared_ptr<RecorderCoordinator>(new RecorderCoordinator(root));
  return coordinator;
}

void RecorderCoordinator::ShutdownAll() {
  CoordinatorRegistry& registry = Registry();
  std::map<path, std::shared_ptr<RecorderCoordinator>> coordinators;
  {
    std::unique_lock<std::mutex> lock(registry.mutex);
    registry.changed.wait(lock, [&registry] { return !registry.shutting_down; });
    registry.shutting_down = true;
    coordinators.swap(registry.coordinators);
  }
  for (auto& item : coordinators)
    item.second->Shutdown();
  {
    std::lock_guard<std::mutex> lock(registry.mutex);
    registry.shutting_down = false;
  }
  registry.changed.notify_all();
}

RecorderCoordinator::RecorderCoordinator(path root) : root_(std::move(root)) {
  process_marker_ready_ =
      OpenProcessMarker(root_, &process_marker_fd_, &process_marker_name_);
  process_marker_clean_ = process_marker_ready_;
  flush_thread_ = std::thread(&RecorderCoordinator::FlushLoop, this);
}

RecorderCoordinator::~RecorderCoordinator() {
  Shutdown();
  CleanupProcessMarker();
}

void RecorderCoordinator::SetProcessMarkerState(const char* state, bool clean) {
  std::lock_guard<std::mutex> lock(mutex_);
  SetProcessMarkerStateLocked(state, clean);
}

void RecorderCoordinator::SetProcessMarkerStateLocked(const char* state,
                                                       bool clean) {
  if (!process_marker_ready_ || process_marker_fd_ < 0)
    return;
  if (!WriteProcessMarkerState(process_marker_fd_, state)) {
    process_marker_clean_ = false;
    return;
  }
  process_marker_clean_ = clean;
}

void RecorderCoordinator::CleanupProcessMarker() {
  int marker_fd = -1;
  string marker_name;
  bool remove = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (process_marker_fd_ < 0)
      return;
    marker_fd = process_marker_fd_;
    process_marker_fd_ = -1;
    marker_name = process_marker_name_;
    process_marker_name_.clear();
    remove = process_marker_clean_;
    process_marker_ready_ = false;
  }
  close(marker_fd);
  if (remove && !RemoveProcessMarker(root_, marker_name))
    LOG(WARNING) << "llm_rerank recorder: code=recording_marker_cleanup_failed";
}

int64_t RecorderCoordinator::BatchLogicalBytes(
    const vector<FactStore::Event>& events) {
  int64_t total = kBatchHeaderBytes;
  const auto add_size = [&total](size_t size) {
    if (size > static_cast<size_t>(std::numeric_limits<int64_t>::max())) {
      total = std::numeric_limits<int64_t>::max();
      return;
    }
    SaturatingAdd(&total, static_cast<int64_t>(size));
  };
  for (const auto& event : events) {
    // The logical payload is independent of allocator capacity: a fixed batch
    // header, ten 64-bit scalar columns, the competition boolean, a fixed
    // per-event header, then UTF-8 strings and candidate entries.
    SaturatingAdd(&total, 10 * 8 + 1 + kEventFixedBytes);
    add_size(event.event_id.size());
    add_size(event.commit_id.size());
    add_size(event.schema_id.size());
    add_size(event.canonical_segment_input.size());
    add_size(event.category.size());
    add_size(event.preceding_text.size());
    add_size(event.final_selection_text.size());
    add_size(event.confirmation_source.size());
    add_size(event.session_id.size());
    for (const auto& candidate : event.candidates) {
      SaturatingAdd(&total, 8);
      add_size(candidate.second.size());
    }
  }
  return total;
}

bool RecorderCoordinator::Persist(const Item& item, string* fault_code) {
  FactStore store(root_);
  FactStore::Status status = store.Open();
  if (status != FactStore::Status::kOk) {
    *fault_code = FactStore::StatusCode(status);
    return false;
  }
  bool ok = item.kind == Kind::kBatch
                ? store.PersistBatch(item.utc_ms,
                                     const_cast<vector<FactStore::Event>*>(&item.events),
                                     nullptr, &item.commit_id)
                : store.AppendRetraction(item.commit_id, item.utc_ms);
  if (!ok)
    *fault_code = FactStore::StatusCode(store.status());
  return ok;
}

void RecorderCoordinator::AddGapLocked(const char* reason,
                                       int64_t batches,
                                       int64_t events,
                                       int64_t retractions,
                                       int64_t bytes) {
  Gap gap;
  gap.reason = reason;
  gap.batches = batches;
  gap.events = events;
  gap.retractions = retractions;
  gap.bytes = bytes;
  AddGapLocked(std::move(gap));
}

void RecorderCoordinator::AddGapLocked(Gap gap) {
  if (gap.empty())
    return;
  if (pending_gap_.empty()) {
    pending_gap_ = std::move(gap);
    return;
  }
  if (pending_gap_.intent.empty())
    pending_gap_.intent = std::move(gap.intent);
  if (pending_gap_.reason != gap.reason)
    pending_gap_.reason = "recording_gap";
  SaturatingAdd(&pending_gap_.batches, gap.batches);
  SaturatingAdd(&pending_gap_.events, gap.events);
  SaturatingAdd(&pending_gap_.retractions, gap.retractions);
  SaturatingAdd(&pending_gap_.bytes, gap.bytes);
}

void RecorderCoordinator::RemoveFrontLocked() {
  if (queue_.empty())
    return;
  const Item& item = queue_.front();
  if (item.kind == Kind::kBatch && queued_batches_ > 0)
    --queued_batches_;
  if (queued_bytes_ >= item.bytes)
    queued_bytes_ -= item.bytes;
  else
    queued_bytes_ = 0;
  queue_.pop_front();
}

void RecorderCoordinator::MoveQueuedItemsToShutdownGapLocked() {
  while (!queue_.empty()) {
    const Item& item = queue_.front();
    AddGapLocked("shutdown_unpersisted", item.kind == Kind::kBatch,
                 static_cast<int64_t>(item.events.size()),
                 item.kind == Kind::kRetraction, item.bytes);
    RemoveFrontLocked();
  }
}

void RecorderCoordinator::EnqueueOrGap(Item item, SubmitResult* result) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (stopping_) {
    result->outcome = Outcome::kGap;
    result->fault_code = "recorder_stopped";
    AddGapLocked("shutdown_unpersisted", item.kind == Kind::kBatch,
                 static_cast<int64_t>(item.events.size()),
                 item.kind == Kind::kRetraction, item.bytes);
    SetProcessMarkerStateLocked(kProcessMarkerUnknown, false);
    changed_.notify_all();
    return;
  }
  if (!process_marker_ready_) {
    result->outcome = Outcome::kGap;
    result->fault_code = "recording_marker_unavailable";
    AddGapLocked("recording_gap", item.kind == Kind::kBatch,
                 static_cast<int64_t>(item.events.size()),
                 item.kind == Kind::kRetraction, item.bytes);
    changed_.notify_all();
    return;
  }
  const bool batch_overflow = item.kind == Kind::kBatch &&
                              queued_batches_ >= kMaxBatches;
  const bool bytes_overflow = item.bytes > kMaxBytes ||
                              queued_bytes_ > kMaxBytes - item.bytes;
  if (batch_overflow || bytes_overflow) {
    const char* reason = batch_overflow ? "buffer_overflow_batches"
                                        : "buffer_overflow_bytes";
    result->outcome = Outcome::kGap;
    result->fault_code = reason;
    AddGapLocked(reason, item.kind == Kind::kBatch,
                 static_cast<int64_t>(item.events.size()),
                 item.kind == Kind::kRetraction, item.bytes);
    changed_.notify_all();
    return;
  }
  if (item.kind == Kind::kBatch)
    ++queued_batches_;
  queued_bytes_ += item.bytes;
  result->outcome = Outcome::kBuffered;
  result->commit_id = item.commit_id;
  queue_.push_back(std::move(item));
  changed_.notify_one();
}

RecorderCoordinator::SubmitResult RecorderCoordinator::SubmitBatch(
    int64_t utc_committed_at_ms,
    vector<FactStore::Event>* events) {
  SubmitResult result;
  if (!events || events->empty()) {
    result.fault_code = "no_events";
    return result;
  }
  Item item;
  item.kind = Kind::kBatch;
  item.commit_id = RandomUuid();
  item.utc_ms = utc_committed_at_ms;
  // The assigned id is part of the canonical logical payload and is also what
  // FactStore will write into every event row.
  for (auto& event : *events)
    event.commit_id = item.commit_id;
  item.bytes = BatchLogicalBytes(*events);
  item.events = std::move(*events);
  EnqueueOrGap(std::move(item), &result);
  return result;
}

RecorderCoordinator::SubmitResult RecorderCoordinator::SubmitRetraction(
    const string& commit_id,
    int64_t utc_retracted_at_ms) {
  SubmitResult result;
  Item item;
  item.kind = Kind::kRetraction;
  item.commit_id = commit_id;
  item.utc_ms = utc_retracted_at_ms;
  item.bytes = kRetractionHeaderBytes;
  if (commit_id.size() > static_cast<size_t>(std::numeric_limits<int64_t>::max()))
    item.bytes = std::numeric_limits<int64_t>::max();
  else
    SaturatingAdd(&item.bytes, static_cast<int64_t>(commit_id.size()));
  EnqueueOrGap(std::move(item), &result);
  return result;
}

void RecorderCoordinator::FlushLoop() {
  for (;;) {
    Gap gap;
    Item item;
    bool flushing_gap = false;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      changed_.wait(lock, [this] {
        return stopping_ || !pending_gap_.empty() || !queue_.empty();
      });
      if (stopping_)
        MoveQueuedItemsToShutdownGapLocked();
      if (!pending_gap_.empty()) {
        gap = std::move(pending_gap_);
        pending_gap_ = Gap();
        flushing_gap = true;
        processing_ = true;
      } else if (stopping_) {
        worker_stopped_ = true;
        drained_.notify_all();
        return;
      } else {
        item = queue_.front();
        processing_ = true;
      }
    }

    if (flushing_gap) {
      SetProcessMarkerState(kProcessMarkerPending, false);
      bool intent_created = !gap.intent.empty() || CreateGapIntent(root_, &gap.intent);
      GapUpdateStatus status = GapUpdateStatus::kFailed;
      bool persisted = false;
      if (intent_created) {
        status = UpdateGap(root_, gap.reason.c_str(), gap.batches, gap.events,
                           gap.retractions, gap.bytes);
        persisted = status == GapUpdateStatus::kOk;
      }
      if (status == GapUpdateStatus::kFailed) {
        MarkGapUnknown(root_);
      }
      if (persisted && !RemoveGapIntent(root_, gap.intent)) {
        // Retaining the marker is conservative: status remains unknown until
        // an administrator can inspect the incomplete durable transition.
        persisted = false;
      }
      if (persisted) {
        SetProcessMarkerState(kProcessMarkerClean, true);
      } else {
        SetProcessMarkerState(kProcessMarkerUnknown, false);
      }
      std::lock_guard<std::mutex> lock(mutex_);
      processing_ = false;
      drained_.notify_all();
      if (!persisted) {
        LOG(WARNING) << "llm_rerank recorder: code=recording_gap_unknown";
      }
      continue;
    }

    string fault;
    if (Persist(item, &fault)) {
      const GapUpdateStatus initialized = EnsureGapState(root_);
      if (initialized == GapUpdateStatus::kFailed) {
        MarkGapUnknown(root_);
        SetProcessMarkerState(kProcessMarkerUnknown, false);
      }
      std::lock_guard<std::mutex> lock(mutex_);
      RemoveFrontLocked();
      processing_ = false;
      drained_.notify_all();
      continue;
    }

    if (fault == "maintenance_locked") {
      std::unique_lock<std::mutex> lock(mutex_);
      processing_ = false;
      drained_.notify_all();
      if (!stopping_)
        changed_.wait_for(lock, std::chrono::milliseconds(50));
      continue;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    RemoveFrontLocked();
    AddGapLocked("store_write_failed", item.kind == Kind::kBatch,
                 static_cast<int64_t>(item.events.size()),
                 item.kind == Kind::kRetraction, item.bytes);
    processing_ = false;
    changed_.notify_all();
    drained_.notify_all();
  }
}

void RecorderCoordinator::FlushForTesting() {
  std::unique_lock<std::mutex> lock(mutex_);
  changed_.notify_all();
  drained_.wait(lock, [this] {
    return worker_stopped_ ||
           (queue_.empty() && pending_gap_.empty() && !processing_);
  });
}

void RecorderCoordinator::Shutdown() {
  std::lock_guard<std::mutex> shutdown_lock(shutdown_mutex_);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_ && !flush_thread_.joinable())
      return;
    stopping_ = true;
  }
  changed_.notify_all();
  if (flush_thread_.joinable())
    flush_thread_.join();
}

}  // namespace rime
