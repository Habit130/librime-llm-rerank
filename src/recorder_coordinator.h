//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_RECORDER_COORDINATOR_H_
#define RIME_RECORDER_COORDINATOR_H_

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <rime/common.h>

#include "fact_store.h"
#include "recording_gap.h"

namespace rime {

// Process-wide coordinator between the recorder processors and the fact
// store (Habit130/squirrel#53 "维护期间并发输入").
//
// One coordinator instance exists per plugin process (never one per
// engine/session), so the bounded maintenance buffer is a process-wide
// resource: every engine's commit batches land in the same queue and count
// against the same 256-batch / 16 MiB limits.
//
// Fast path: when the shared maintenance lock is free, a submitted batch is
// persisted synchronously (the recorder's commit notifier never waits: the
// shared acquisition is non-blocking and a held exclusive lock returns
// immediately, not by blocking).
//
// Buffered path: while the exclusive maintenance lock is held, each complete
// commit batch (and each immediate-undo retraction) enters the in-memory
// queue. A commit_id is assigned at enqueue time, so an immediate BackSpace
// can retract a batch that has not reached the disk yet; the retraction is
// queued behind the batch and both flush in order, preserving the #50 whole-
// commit retraction semantics (no orphan events, no partial undo, no wrong
// undo of an earlier commit).
//
// Limits: at most kMaxBufferedBatches batches or kMaxBufferedBytes total
// queued bytes (deterministically computed, see BatchByteSize), whichever is
// reached first. Further batches are refused (never overwriting or dropping
// old ones) and the refusal is persisted as a recording gap.
//
// Flush: a background thread flushes the queue in FIFO order whenever the
// exclusive lock is free — so buffered batches land after maintenance even
// with no further user input. Every flushed batch is written through a fresh
// connection that re-reads the on-disk store_epoch and clock, so batches
// flushed after a restore/clear land in the new store with HLCs above the
// new clock, after the maintenance linearization point. Known-but-unpersisted
// batches at shutdown form a persistent recording gap.
class RecorderCoordinator {
 public:
  enum class Outcome { kPersisted, kBuffered, kGap };

  // Result of a submit. `commit_id` is always set for kPersisted and
  // kBuffered (assigned at enqueue), so the recorder can arm its
  // immediate-undo window either way. `fatal` marks a deterministic store
  // fault: recording must stop and be reported, never auto-relaxed.
  struct SubmitResult {
    Outcome outcome = Outcome::kGap;
    string commit_id;
    string fault_code;  // stable code; empty when healthy
    bool fatal = false;
  };

  static constexpr int kMaxBufferedBatches = 256;
  static constexpr int64_t kMaxBufferedBytes = 16 * 1024 * 1024;
  // Deterministic byte size of one commit batch (see BatchByteSize doc).
  static constexpr int64_t kFixedEventOverheadBytes = 16;

  // Deterministic serialized size of a batch, independent of any container
  // capacity or allocator behavior: the sum over events of every text
  // field's UTF-8 byte length plus a fixed 8 bytes per numeric field plus a
  // fixed per-event overhead, plus a fixed per-candidate overhead per
  // competition candidate. The exact formula is part of the buffering
  // contract and is mirrored by the tests.
  static int64_t BatchByteSize(const vector<FactStore::Event>& events);

  // Creates a coordinator rooted at `root_dir` (explicit; tests).
  explicit RecorderCoordinator(const path& root_dir);
  // Creates a coordinator whose root is resolved from HOME on every use
  // (the process-wide instance; HOME never changes in production).
  RecorderCoordinator();
  ~RecorderCoordinator();

  RecorderCoordinator(const RecorderCoordinator&) = delete;
  RecorderCoordinator& operator=(const RecorderCoordinator&) = delete;

  // Submits one complete commit batch. Never blocks on the maintenance
  // lock. Returns kPersisted (fast path), kBuffered (maintenance in
  // progress) or kGap (buffer full, store fault, or fatal store condition).
  SubmitResult SubmitBatch(int64_t utc_committed_at_ms,
                           vector<FactStore::Event>* events);

  // Submits one immediate-undo retraction (whole commit, #50 semantics).
  // Never blocks on the maintenance lock.
  SubmitResult SubmitRetraction(const string& commit_id,
                                int64_t utc_retracted_at_ms);

  // Readiness probe used by the recorder constructor: verifies root, db and
  // lock file and creates the store if missing, without holding any
  // connection. Fatal faults disable recording for the session.
  FactStore::Status VerifyStore();

  // Test seams (deterministic synchronization, no sleep races).
  void SetPollIntervalMs(int64_t ms);
  bool WaitUntilDrained(int64_t timeout_ms);
  int64_t queued_batches() const;
  int64_t queued_bytes() const;
  int64_t gap_dropped_batches() const;

  // The process-wide coordinator used by recorder processors.
  static std::shared_ptr<RecorderCoordinator> Instance();

 private:
  struct QueueItem {
    enum class Kind { kBatch, kRetraction };
    Kind kind = Kind::kBatch;
    string commit_id;  // batch identity, assigned at enqueue
    int64_t utc_ms = 0;
    vector<FactStore::Event> events;
    int64_t bytes = 0;
  };

  void FlushLoop();
  // Persists the front item; returns false when it must be retried later
  // (exclusive lock held or store transiently unavailable).
  bool FlushFront(const QueueItem& item);
  void RecordGap(const string& reason, int64_t dropped_events,
                 int64_t buffer_bytes);
  // Merges a gap event into the record; caller holds mutex_.
  void RecordGapLocked(const string& reason, int64_t dropped_events,
                       int64_t buffer_bytes);
  path Root() const;

  std::function<path()> root_provider_;
  mutable std::mutex mutex_;
  std::condition_variable changed_;
  std::deque<QueueItem> queue_;
  int64_t queued_batches_ = 0;
  int64_t queued_bytes_ = 0;
  bool flushing_ = false;
  bool shutdown_ = false;
  int64_t poll_interval_ms_ = 100;
  std::thread flush_thread_;
  RecordingGapRecord gap_;
  bool gap_loaded_ = false;
};

}  // namespace rime

#endif  // RIME_RECORDER_COORDINATOR_H_
