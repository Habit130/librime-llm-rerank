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

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>

namespace rime {
namespace {

constexpr int64_t kMaxBatches = 256;
constexpr int64_t kMaxBytes = 16 * 1024 * 1024;
constexpr int64_t kBatchHeaderBytes = 64;
constexpr int64_t kRetractionHeaderBytes = 64;
constexpr mode_t kFileMode = 0600;

std::mutex& CoordinatorsMutex() {
  static std::mutex mutex;
  return mutex;
}

std::map<path, std::unique_ptr<RecorderCoordinator>>& Coordinators() {
  static std::map<path, std::unique_ptr<RecorderCoordinator>> coordinators;
  return coordinators;
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

// The gap format deliberately has no private text. This parser accepts only
// the exact versioned shape written below; malformed prior data is never
// treated as a zero gap or merged over.
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
  char* parsed_end = nullptr;
  long long parsed = strtoll(input.substr(start, end - start).c_str(),
                             &parsed_end, 10);
  if (!parsed_end || *parsed_end || parsed < 0)
    return false;
  *value = parsed;
  return true;
}

bool UpdateGap(const path& root,
               const char* reason,
               int64_t batches,
               int64_t events,
               int64_t retractions,
               int64_t bytes) {
  int root_fd = open(root.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
  if (root_fd < 0)
    return false;
  struct stat root_stat;
  if (fstat(root_fd, &root_stat) != 0 || !S_ISDIR(root_stat.st_mode) ||
      root_stat.st_uid != getuid() || (root_stat.st_mode & 0777) != 0700) {
    close(root_fd);
    return false;
  }
  int lock_fd = openat(root_fd, "recording_gap.lock",
                       O_RDWR | O_CREAT | O_NOFOLLOW, kFileMode);
  if (lock_fd < 0) {
    close(root_fd);
    return false;
  }
  struct stat lock_stat;
  bool ok = fstat(lock_fd, &lock_stat) == 0 && S_ISREG(lock_stat.st_mode) &&
            lock_stat.st_uid == getuid() &&
            (lock_stat.st_mode & 0777) == kFileMode &&
            flock(lock_fd, LOCK_EX) == 0;
  int64_t old_batches = 0;
  int64_t old_events = 0;
  int64_t old_retractions = 0;
  int64_t old_bytes = 0;
  if (ok) {
    int fd = openat(root_fd, "recording_gap.json", O_RDONLY | O_NOFOLLOW);
    if (fd >= 0) {
      struct stat gap_stat;
      if (fstat(fd, &gap_stat) != 0 || !S_ISREG(gap_stat.st_mode) ||
          gap_stat.st_uid != getuid() ||
          (gap_stat.st_mode & 0777) != kFileMode) {
        close(fd);
        ok = false;
      }
      string content;
      char buffer[1024];
      ssize_t read_count = 0;
      while (ok && (read_count = read(fd, buffer, sizeof(buffer))) > 0)
        content.append(buffer, static_cast<size_t>(read_count));
      if (ok)
        close(fd);
      int64_t version = 0;
      ok = read_count == 0 && ReadNonNegative(content, "gap_version", &version) &&
           version == 1 && ReadNonNegative(content, "dropped_batches", &old_batches) &&
           ReadNonNegative(content, "dropped_events", &old_events) &&
           ReadNonNegative(content, "dropped_retractions", &old_retractions) &&
           ReadNonNegative(content, "dropped_bytes", &old_bytes);
    } else if (errno != ENOENT) {
      ok = false;
    }
  }
  if (ok) {
    string payload = "{\"gap_version\":1,\"reason\":\"" + string(reason) +
        "\",\"dropped_batches\":" + std::to_string(old_batches + batches) +
        ",\"dropped_events\":" + std::to_string(old_events + events) +
        ",\"dropped_retractions\":" + std::to_string(old_retractions + retractions) +
        ",\"dropped_bytes\":" + std::to_string(old_bytes + bytes) +
        ",\"updated_at_ms\":" + std::to_string(NowMs()) + "}";
    string temp = ".recording_gap." + RandomUuid() + ".tmp";
    int fd = openat(root_fd, temp.c_str(), O_WRONLY | O_CREAT | O_EXCL |
                    O_NOFOLLOW, kFileMode);
    ok = fd >= 0;
    if (ok) {
      ok = fchmod(fd, kFileMode) == 0 && WriteAll(fd, payload) && fsync(fd) == 0;
      close(fd);
      if (ok)
        ok = renameat(root_fd, temp.c_str(), root_fd, "recording_gap.json") == 0 &&
             fsync(root_fd) == 0;
      if (!ok)
        unlinkat(root_fd, temp.c_str(), 0);
    }
  }
  close(lock_fd);
  close(root_fd);
  return ok;
}

}  // namespace

RecorderCoordinator& RecorderCoordinator::ForRoot(const path& root) {
  std::lock_guard<std::mutex> lock(CoordinatorsMutex());
  auto& coordinator = Coordinators()[root];
  if (!coordinator)
    coordinator.reset(new RecorderCoordinator(root));
  return *coordinator;
}

void RecorderCoordinator::ShutdownAll() {
  std::map<path, std::unique_ptr<RecorderCoordinator>> coordinators;
  {
    std::lock_guard<std::mutex> lock(CoordinatorsMutex());
    coordinators.swap(Coordinators());
  }
  for (auto& item : coordinators)
    item.second->Shutdown();
}

RecorderCoordinator::RecorderCoordinator(path root) : root_(std::move(root)) {
  flush_thread_ = std::thread(&RecorderCoordinator::FlushLoop, this);
}

RecorderCoordinator::~RecorderCoordinator() {
  Shutdown();
}

int64_t RecorderCoordinator::BatchLogicalBytes(
    const vector<FactStore::Event>& events) {
  int64_t total = kBatchHeaderBytes;
  for (const auto& event : events) {
    // Ten 64-bit scalar columns plus the boolean use a canonical fixed size.
    total += 10 * 8 + 1;
    total += event.event_id.size() + event.commit_id.size() + event.schema_id.size() +
             event.canonical_segment_input.size() + event.category.size() +
             event.preceding_text.size() + event.final_selection_text.size() +
             event.confirmation_source.size() + event.session_id.size();
    for (const auto& candidate : event.candidates)
      total += 8 + static_cast<int64_t>(candidate.second.size());
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

void RecorderCoordinator::RecordGap(const char* reason,
                                    int64_t batches,
                                    int64_t events,
                                    int64_t retractions,
                                    int64_t bytes) {
  // A failed durable update is observable as unknown: status validates this
  // versioned file rather than ever reporting an absent/failed write as zero.
  if (!UpdateGap(root_, reason, batches, events, retractions, bytes))
    LOG(WARNING) << "llm_rerank recorder: code=recording_gap_unknown";
}

void RecorderCoordinator::EnqueueOrGap(Item item, SubmitResult* result) {
  std::lock_guard<std::mutex> lock(mutex_);
  const bool batch_overflow = item.kind == Kind::kBatch &&
                              queued_batches_ + reserved_batches_ >= kMaxBatches;
  const bool bytes_overflow = queued_bytes_ + reserved_bytes_ + item.bytes >
                              kMaxBytes;
  if (batch_overflow || bytes_overflow || stopping_) {
    const char* reason = batch_overflow ? "buffer_overflow_batches"
                                        : "buffer_overflow_bytes";
    result->outcome = Outcome::kGap;
    result->fault_code = reason;
    RecordGap(reason, item.kind == Kind::kBatch, item.events.size(),
              item.kind == Kind::kRetraction, item.bytes);
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
  item.bytes = BatchLogicalBytes(*events);
  const string item_commit_id = item.commit_id;
  bool queued = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    queued = !queue_.empty() || direct_in_flight_;
    if (!queued) {
      direct_in_flight_ = true;
      reserved_batches_ = 1;
      reserved_bytes_ = item.bytes;
    }
  }
  if (queued) {
    item.events = std::move(*events);
    EnqueueOrGap(std::move(item), &result);
    return result;
  }
  string fault;
  item.events = std::move(*events);
  bool persisted = Persist(item, &fault);
  bool bufferable = true;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    direct_in_flight_ = false;
    reserved_batches_ = 0;
    reserved_bytes_ = 0;
    if (!persisted && fault == "maintenance_locked") {
      // Existing queued items arrived after this direct probe. Preserve the
      // probe's causality by making it the new queue head.
      if (queued_batches_ >= kMaxBatches || queued_bytes_ + item.bytes > kMaxBytes) {
        bufferable = false;
      } else {
        ++queued_batches_;
        queued_bytes_ += item.bytes;
        queue_.push_front(std::move(item));
      }
    }
    changed_.notify_all();
  }
  if (persisted) {
    result.outcome = Outcome::kPersisted;
    result.commit_id = item_commit_id;
    return result;
  }
  if (fault == "maintenance_locked") {
    if (!bufferable) {
      result.fault_code = "buffer_overflow_bytes";
      RecordGap(result.fault_code.c_str(), 1, item.events.size(), 0, item.bytes);
      return result;
    }
    result.outcome = Outcome::kBuffered;
    result.commit_id = item_commit_id;
    return result;
  }
  result.fault_code = fault;
  RecordGap("store_write_failed", 1, item.events.size(), 0, item.bytes);
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
  item.bytes = kRetractionHeaderBytes + static_cast<int64_t>(commit_id.size());
  bool queued = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    queued = !queue_.empty() || direct_in_flight_;
    if (!queued) {
      direct_in_flight_ = true;
      reserved_bytes_ = item.bytes;
    }
  }
  if (queued) {
    EnqueueOrGap(std::move(item), &result);
    return result;
  }
  string fault;
  bool persisted = Persist(item, &fault);
  bool bufferable = true;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    direct_in_flight_ = false;
    reserved_bytes_ = 0;
    if (!persisted && fault == "maintenance_locked") {
      if (queued_bytes_ + item.bytes > kMaxBytes) {
        bufferable = false;
      } else {
        queued_bytes_ += item.bytes;
        queue_.push_front(std::move(item));
      }
    }
    changed_.notify_all();
  }
  if (persisted) {
    result.outcome = Outcome::kPersisted;
    result.commit_id = commit_id;
    return result;
  }
  if (fault == "maintenance_locked") {
    if (!bufferable) {
      result.fault_code = "buffer_overflow_bytes";
      RecordGap(result.fault_code.c_str(), 0, 0, 1, item.bytes);
      return result;
    }
    result.outcome = Outcome::kBuffered;
    result.commit_id = commit_id;
    return result;
  }
  result.fault_code = fault;
  RecordGap("store_write_failed", 0, 0, 1, item.bytes);
  return result;
}

void RecorderCoordinator::FlushLoop() {
  for (;;) {
    Item item;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      changed_.wait_for(lock, std::chrono::milliseconds(50), [this] {
        return stopping_ || (!queue_.empty() && !direct_in_flight_);
      });
      if (stopping_)
        return;
      if (queue_.empty() || direct_in_flight_)
        continue;
      item = queue_.front();
    }
    string fault;
    if (!Persist(item, &fault)) {
      if (fault == "maintenance_locked")
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
      if (fault == "maintenance_locked")
        continue;
      std::lock_guard<std::mutex> lock(mutex_);
      queue_.pop_front();
      if (item.kind == Kind::kBatch)
        --queued_batches_;
      queued_bytes_ -= item.bytes;
      RecordGap("store_write_failed", item.kind == Kind::kBatch,
                item.events.size(), item.kind == Kind::kRetraction, item.bytes);
      continue;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    queue_.pop_front();
    if (item.kind == Kind::kBatch)
      --queued_batches_;
    queued_bytes_ -= item.bytes;
  }
}

void RecorderCoordinator::Shutdown() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_)
      return;
    stopping_ = true;
  }
  changed_.notify_all();
  if (flush_thread_.joinable())
    flush_thread_.join();
  int64_t batches = 0;
  int64_t events = 0;
  int64_t retractions = 0;
  int64_t bytes = 0;
  std::lock_guard<std::mutex> lock(mutex_);
  for (const auto& item : queue_) {
    batches += item.kind == Kind::kBatch;
    events += item.events.size();
    retractions += item.kind == Kind::kRetraction;
    bytes += item.bytes;
  }
  queue_.clear();
  if (batches || events || retractions)
    RecordGap("shutdown_unpersisted", batches, events, retractions, bytes);
}

}  // namespace rime
