//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <utility>

#include "recorder_coordinator.h"
#include "recorder_session.h"

namespace rime {

namespace {

// Stable gap reason codes (recorded verbatim in recording_gap.json; also
// reported through the session properties).
constexpr const char* kGapReasonOverflowBatches = "buffer_overflow_batches";
constexpr const char* kGapReasonOverflowBytes = "buffer_overflow_bytes";
constexpr const char* kGapReasonShutdown = "shutdown_unpersisted";

constexpr const char* kGapReasonStoreFault = "store_write_failed";
constexpr const char* kGapReasonLockFault = "store_lock_failed";

// Stable code for "no fault / not yet classified".
constexpr const char* kFaultNone = "";

}  // namespace

int64_t RecorderCoordinator::BatchByteSize(
    const vector<FactStore::Event>& events) {
  int64_t total = 0;
  for (const auto& event : events) {
    total += kFixedEventOverheadBytes;
    total += static_cast<int64_t>(event.event_id.size());
    total += static_cast<int64_t>(event.commit_id.size());
    total += static_cast<int64_t>(event.schema_id.size());
    total += static_cast<int64_t>(event.canonical_segment_input.size());
    total += static_cast<int64_t>(event.category.size());
    total += static_cast<int64_t>(event.preceding_text.size());
    total += static_cast<int64_t>(event.final_selection_text.size());
    total += static_cast<int64_t>(event.confirmation_source.size());
    total += static_cast<int64_t>(event.session_id.size());
    // Numeric fields: 8 bytes each for the fixed-size columns.
    total += 8 * 10;  // span_start, span_end, hlc x2, utc_confirmed,
                      // utc_committed, display_rank, display_page,
                      // session_seq, trigger_keycode
    total += 1;       // competition_complete
    for (const auto& candidate : event.candidates) {
      total += 8 + static_cast<int64_t>(candidate.second.size());
    }
  }
  return total;
}

RecorderCoordinator::RecorderCoordinator(const path& root_dir)
    : root_provider_([root_dir] { return root_dir; }) {
  flush_thread_ = std::thread(&RecorderCoordinator::FlushLoop, this);
}

RecorderCoordinator::RecorderCoordinator()
    : root_provider_([] { return FactStore::DefaultRootDir(); }) {
  flush_thread_ = std::thread(&RecorderCoordinator::FlushLoop, this);
}

RecorderCoordinator::~RecorderCoordinator() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    shutdown_ = true;
  }
  changed_.notify_all();
  if (flush_thread_.joinable())
    flush_thread_.join();
  // Final best-effort drain; anything that cannot be persisted (exclusive
  // lock still held, store broken) is a known, persistent recording gap.
  int64_t leftover_batches = 0;
  int64_t leftover_events = 0;
  for (;;) {
    QueueItem item;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (queue_.empty())
        break;
      item = queue_.front();
    }
    if (FlushFront(item)) {
      std::lock_guard<std::mutex> lock(mutex_);
      queue_.pop_front();
      if (item.kind == QueueItem::Kind::kBatch)
        --queued_batches_;
      queued_bytes_ -= item.bytes;
      continue;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    queue_.pop_front();
    if (item.kind == QueueItem::Kind::kBatch) {
      ++leftover_batches;
      leftover_events += static_cast<int64_t>(item.events.size());
    } else {
      // A lost retraction is a lost fact too.
      leftover_events += 1;
    }
  }
  if (leftover_batches > 0) {
    RecordingGapRecord gap;
    gap.reason = kGapReasonShutdown;
    gap.dropped_batches = leftover_batches;
    gap.dropped_events = leftover_events;
    gap.first_occurred_at_ms = NowMs();
    gap.last_occurred_at_ms = gap.first_occurred_at_ms;
    FactStore store(Root());
    string epoch;
    int64_t physical = 0;
    int64_t logical = 0;
    if (store.ReadStoreIdentity(&physical, &logical, &epoch) ==
        FactStore::Status::kOk) {
      gap.store_epoch = epoch;
    }
    gap.Write(Root());
  }
}

path RecorderCoordinator::Root() const {
  return root_provider_();
}

RecorderCoordinator::SubmitResult RecorderCoordinator::SubmitBatch(
    int64_t utc_committed_at_ms, vector<FactStore::Event>* events) {
  SubmitResult result;
  if (!events || events->empty()) {
    result.outcome = Outcome::kGap;
    result.fault_code = "no_events";
    return result;
  }
  // Fast path: persist synchronously unless the exclusive maintenance lock
  // is held. This never blocks: FactStore's shared acquisition is
  // non-blocking and returns kMaintenanceLocked immediately.
  FactStore store(Root());
  string commit_id;
  FactStore::Status status = store.PersistBatch(utc_committed_at_ms, events,
                                                &commit_id);
  if (status == FactStore::Status::kOk) {
    result.outcome = Outcome::kPersisted;
    result.commit_id = commit_id;
    return result;
  }
  if (status == FactStore::Status::kMaintenanceLocked) {
    // Buffer the whole batch (never split, never drop) if the limits allow;
    // otherwise refuse it and persist the gap.
    QueueItem item;
    item.kind = QueueItem::Kind::kBatch;
    item.commit_id = RandomUuid();
    item.utc_ms = utc_committed_at_ms;
    item.events = std::move(*events);
    item.bytes = BatchByteSize(item.events);
    const string buffered_commit_id = item.commit_id;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (shutdown_) {
        result.outcome = Outcome::kGap;
        result.fault_code = kGapReasonShutdown;
        return result;
      }
      const bool overflow_batches =
          queued_batches_ >= kMaxBufferedBatches;
      const bool overflow_bytes =
          queued_bytes_ + item.bytes > kMaxBufferedBytes;
      if (overflow_batches || overflow_bytes) {
        const char* reason = overflow_batches ? kGapReasonOverflowBatches
                                              : kGapReasonOverflowBytes;
        RecordGapLocked(reason,
                        static_cast<int64_t>(item.events.size()), item.bytes);
        result.outcome = Outcome::kGap;
        result.fault_code = reason;
        return result;
      }
      queue_.push_back(std::move(item));
      ++queued_batches_;
      queued_bytes_ += item.bytes;
    }
    changed_.notify_all();
    result.outcome = Outcome::kBuffered;
    result.commit_id = buffered_commit_id;
    return result;
  }
  // A real store fault: it forms a persistent recording gap (never a
  // silent zero-evidence). Deterministic faults also stop recording.
  result.outcome = Outcome::kGap;
  result.fault_code = FactStore::StatusCode(status);
  result.fatal = FactStore::IsFatalStatus(status);
  RecordGap(FactStore::IsFatalStatus(status) ? kGapReasonLockFault
                                             : kGapReasonStoreFault,
            static_cast<int64_t>(events->size()),
            BatchByteSize(*events));
  return result;
}

RecorderCoordinator::SubmitResult RecorderCoordinator::SubmitRetraction(
    const string& commit_id, int64_t utc_retracted_at_ms) {
  SubmitResult result;
  FactStore store(Root());
  FactStore::Status status =
      store.AppendRetraction(commit_id, utc_retracted_at_ms);
  if (status == FactStore::Status::kOk) {
    result.outcome = Outcome::kPersisted;
    return result;
  }
  if (status == FactStore::Status::kMaintenanceLocked) {
    QueueItem item;
    item.kind = QueueItem::Kind::kRetraction;
    item.commit_id = commit_id;
    item.utc_ms = utc_retracted_at_ms;
    item.bytes = 32 + static_cast<int64_t>(commit_id.size());
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (shutdown_) {
        result.outcome = Outcome::kGap;
        result.fault_code = kGapReasonShutdown;
        return result;
      }
      if (queued_bytes_ + item.bytes > kMaxBufferedBytes) {
        RecordGapLocked(kGapReasonOverflowBytes, 0, item.bytes);
        result.outcome = Outcome::kGap;
        result.fault_code = kGapReasonOverflowBytes;
        return result;
      }
      queue_.push_back(std::move(item));
      queued_bytes_ += item.bytes;
    }
    changed_.notify_all();
    result.outcome = Outcome::kBuffered;
    result.commit_id = commit_id;
    return result;
  }
  result.outcome = Outcome::kGap;
  result.fault_code = FactStore::StatusCode(status);
  result.fatal = FactStore::IsFatalStatus(status);
  RecordGap(kGapReasonStoreFault, 0, 0);
  return result;
}

void RecorderCoordinator::RecordGap(const string& reason,
                                    int64_t dropped_events,
                                    int64_t buffer_bytes) {
  std::lock_guard<std::mutex> lock(mutex_);
  RecordGapLocked(reason, dropped_events, buffer_bytes);
}

// Must be called with mutex_ held. Merges the new gap event into the
// in-memory record (loaded once from disk so counts survive restarts) and
// rewrites the record atomically. A write failure is silent: the in-memory
// counts still feed the session properties.
void RecorderCoordinator::RecordGapLocked(const string& reason,
                                          int64_t dropped_events,
                                          int64_t buffer_bytes) {
  if (!gap_loaded_) {
    RecordingGapRecord existing;
    if (RecordingGapRecord::Read(Root(), &existing)) {
      gap_ = existing;
    }
    gap_loaded_ = true;
  }
  if (gap_.dropped_batches == 0) {
    gap_.first_occurred_at_ms = NowMs();
  }
  gap_.dropped_batches += 1;
  gap_.dropped_events += dropped_events;
  gap_.buffer_bytes = std::max<int64_t>(gap_.buffer_bytes, buffer_bytes);
  gap_.last_occurred_at_ms = NowMs();
  if (gap_.reason.empty() || gap_.reason == "unknown") {
    gap_.reason = reason;
  }
  if (gap_.store_epoch.empty()) {
    FactStore store(Root());
    string epoch;
    int64_t physical = 0;
    int64_t logical = 0;
    if (store.ReadStoreIdentity(&physical, &logical, &epoch) ==
        FactStore::Status::kOk) {
      gap_.store_epoch = epoch;
    }
  }
  gap_.Write(Root());
}

bool RecorderCoordinator::FlushFront(const QueueItem& item) {
  FactStore store(Root());
  if (item.kind == QueueItem::Kind::kBatch) {
    vector<FactStore::Event> events = item.events;
    string commit_id = item.commit_id;
    FactStore::Status status = store.PersistBatch(item.utc_ms, &events,
                                                  &commit_id);
    return status == FactStore::Status::kOk;
  }
  FactStore::Status status =
      store.AppendRetraction(item.commit_id, item.utc_ms);
  return status == FactStore::Status::kOk;
}

void RecorderCoordinator::FlushLoop() {
  std::unique_lock<std::mutex> lock(mutex_);
  for (;;) {
    if (shutdown_)
      return;
    if (queue_.empty()) {
      changed_.wait_for(lock, std::chrono::milliseconds(poll_interval_ms_));
      continue;
    }
    // Peek, never pop-before-persist: the buffered item keeps counting
    // against the process-wide limits until it is really on disk, so the
    // 256-batch / 16 MiB rejection boundary stays exact under contention.
    QueueItem item = queue_.front();
    flushing_ = true;
    lock.unlock();
    bool persisted = FlushFront(item);
    lock.lock();
    flushing_ = false;
    if (persisted) {
      queue_.pop_front();
      if (item.kind == QueueItem::Kind::kBatch)
        --queued_batches_;
      queued_bytes_ -= item.bytes;
      changed_.notify_all();
    } else {
      // Exclusive lock still held or store transiently unavailable: retry
      // later, preserving FIFO order (nothing may overtake the front item).
      changed_.wait_for(lock, std::chrono::milliseconds(poll_interval_ms_));
    }
  }
}

FactStore::Status RecorderCoordinator::VerifyStore() {
  FactStore store(Root());
  return store.Open();
}

void RecorderCoordinator::SetPollIntervalMs(int64_t ms) {
  std::lock_guard<std::mutex> lock(mutex_);
  poll_interval_ms_ = std::max<int64_t>(1, ms);
}

bool RecorderCoordinator::WaitUntilDrained(int64_t timeout_ms) {
  std::unique_lock<std::mutex> lock(mutex_);
  auto deadline = std::chrono::steady_clock::now() +
                  std::chrono::milliseconds(timeout_ms);
  while (!queue_.empty() || flushing_) {
    if (changed_.wait_until(lock, deadline) == std::cv_status::timeout)
      return queue_.empty() && !flushing_;
  }
  return true;
}

int64_t RecorderCoordinator::queued_batches() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return queued_batches_;
}

int64_t RecorderCoordinator::queued_bytes() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return queued_bytes_;
}

int64_t RecorderCoordinator::gap_dropped_batches() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return gap_.dropped_batches;
}

std::shared_ptr<RecorderCoordinator> RecorderCoordinator::Instance() {
  static std::shared_ptr<RecorderCoordinator> instance =
      std::make_shared<RecorderCoordinator>();
  return instance;
}

}  // namespace rime
