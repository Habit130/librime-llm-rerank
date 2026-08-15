//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_RECORDER_COORDINATOR_H_
#define RIME_RECORDER_COORDINATOR_H_

#include <condition_variable>
#include <deque>
#include <memory>
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

  // A shared owner prevents an input notifier from using a coordinator after
  // plugin shutdown has removed it from the process registry.
  static std::shared_ptr<RecorderCoordinator> ForRoot(const path& root);
  static void ShutdownAll();

  ~RecorderCoordinator();

  SubmitResult SubmitBatch(int64_t utc_committed_at_ms,
                           vector<FactStore::Event>* events);
  SubmitResult SubmitRetraction(const string& commit_id,
                                int64_t utc_retracted_at_ms);

  // Deterministic accounting seam. Logical bytes are a 64-byte batch header,
  // then per event: ten 8-byte scalar columns, one byte for
  // competition_complete, a 16-byte fixed event header, every UTF-8 text
  // field, and every candidate's 8-byte merge order plus UTF-8 text. The
  // formula never uses allocator capacity or implementation object layout.
  static int64_t BatchLogicalBytes(const vector<FactStore::Event>& events);

  // The production worker flushes asynchronously. Tests explicitly request a
  // drain instead of using wall-clock polling.
  void FlushForTesting();

 private:
  enum class Kind { kBatch, kRetraction };
  struct Item {
    Kind kind = Kind::kBatch;
    string commit_id;
    int64_t utc_ms = 0;
    vector<FactStore::Event> events;
    int64_t bytes = 0;
  };

  struct Gap {
    string reason;
    string intent;
    int64_t batches = 0;
    int64_t events = 0;
    int64_t retractions = 0;
    int64_t bytes = 0;

    bool empty() const {
      return batches == 0 && events == 0 && retractions == 0 && bytes == 0;
    }
  };

  explicit RecorderCoordinator(path root);
  RecorderCoordinator(const RecorderCoordinator&) = delete;
  RecorderCoordinator& operator=(const RecorderCoordinator&) = delete;

  bool Persist(const Item& item, string* fault_code);
  void EnqueueOrGap(Item item, SubmitResult* result);
  void AddGapLocked(const char* reason,
                    int64_t batches,
                    int64_t events,
                    int64_t retractions,
                    int64_t bytes);
  void AddGapLocked(Gap gap);
  void RemoveFrontLocked();
  void MoveQueuedItemsToShutdownGapLocked();
  void FlushLoop();
  void Shutdown();
  void SetProcessMarkerStateLocked(const char* state, bool clean);
  void SetProcessMarkerState(const char* state, bool clean);
  void CleanupProcessMarker();

  path root_;
  std::mutex mutex_;
  std::condition_variable changed_;
  std::deque<Item> queue_;
  int64_t queued_batches_ = 0;
  int64_t queued_bytes_ = 0;
  Gap pending_gap_;
  bool stopping_ = false;
  bool processing_ = false;
  bool worker_stopped_ = false;
  int process_marker_fd_ = -1;
  string process_marker_name_;
  bool process_marker_ready_ = false;
  bool process_marker_clean_ = false;
  std::condition_variable drained_;
  std::mutex shutdown_mutex_;
  std::thread flush_thread_;
};

}  // namespace rime

#endif  // RIME_RECORDER_COORDINATOR_H_
