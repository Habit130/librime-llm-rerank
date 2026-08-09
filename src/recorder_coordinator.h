//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_RECORDER_COORDINATOR_H_
#define RIME_RECORDER_COORDINATOR_H_

#include <condition_variable>
#include <deque>
#include <mutex>
#include <thread>

#include "fact_store.h"

namespace rime {

// Process-wide recorder coordinator. It is the sole route from a committed
// composition or its immediate retraction to the fact store, which makes a
// buffered commit and following BackSpace one causal FIFO sequence.
class RecorderCoordinator {
 public:
  enum class Outcome { kPersisted, kBuffered, kGap };
  struct SubmitResult {
    Outcome outcome = Outcome::kGap;
    string commit_id;
    string fault_code;
  };

  static RecorderCoordinator& ForRoot(const path& root);
  static void ShutdownAll();

  ~RecorderCoordinator();

  SubmitResult SubmitBatch(int64_t utc_committed_at_ms,
                           vector<FactStore::Event>* events);
  SubmitResult SubmitRetraction(const string& commit_id,
                                int64_t utc_retracted_at_ms);

  // Deterministic accounting seam. Logical bytes are the UTF-8 payload sizes,
  // fixed-width scalar encodings and fixed item headers below, never allocator
  // capacity or implementation-dependent object layout.
  static int64_t BatchLogicalBytes(const vector<FactStore::Event>& events);

 private:
  enum class Kind { kBatch, kRetraction };
  struct Item {
    Kind kind = Kind::kBatch;
    string commit_id;
    int64_t utc_ms = 0;
    vector<FactStore::Event> events;
    int64_t bytes = 0;
  };

  explicit RecorderCoordinator(path root);
  RecorderCoordinator(const RecorderCoordinator&) = delete;
  RecorderCoordinator& operator=(const RecorderCoordinator&) = delete;

  bool Persist(const Item& item, string* fault_code);
  void EnqueueOrGap(Item item, SubmitResult* result);
  void RecordGap(const char* reason,
                 int64_t batches,
                 int64_t events,
                 int64_t retractions,
                 int64_t bytes);
  void FlushLoop();
  void Shutdown();

  path root_;
  std::mutex mutex_;
  std::condition_variable changed_;
  std::deque<Item> queue_;
  int64_t queued_batches_ = 0;
  int64_t queued_bytes_ = 0;
  // One direct persistence may be probing the nonblocking maintenance lock.
  // Reserve its FIFO slot so concurrent submissions cannot overtake it in the
  // narrow interval before a maintenance-locked result is enqueued.
  bool direct_in_flight_ = false;
  int64_t reserved_batches_ = 0;
  int64_t reserved_bytes_ = 0;
  bool stopping_ = false;
  std::thread flush_thread_;
};

}  // namespace rime

#endif  // RIME_RECORDER_COORDINATOR_H_
