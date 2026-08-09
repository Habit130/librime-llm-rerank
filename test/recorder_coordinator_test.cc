//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <mach-o/dyld.h>
#include <spawn.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <signal.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

extern char** environ;

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "fact_store.h"
#include "maintenance_lock.h"
#include "recorder_coordinator.h"
#include "recording_gap.h"
#include "recorder_session.h"

using namespace rime;

namespace fs = std::filesystem;

namespace {

std::string MakeTempDir() {
  char tmpl[] = "/tmp/llm_rerank_coord_XXXXXX";
  char* dir = mkdtemp(tmpl);
  if (!dir)
    return "";
  return std::string(dir);
}

long long QueryCount(sqlite3* db, const char* sql) {
  sqlite3_stmt* stmt = nullptr;
  long long result = -1;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return result;
  if (sqlite3_step(stmt) == SQLITE_ROW)
    result = sqlite3_column_int64(stmt, 0);
  sqlite3_finalize(stmt);
  return result;
}

std::string QueryText(sqlite3* db, const char* sql) {
  sqlite3_stmt* stmt = nullptr;
  std::string result;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return result;
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    const unsigned char* text = sqlite3_column_text(stmt, 0);
    if (text)
      result = reinterpret_cast<const char*>(text);
  }
  sqlite3_finalize(stmt);
  return result;
}

// The facts store runs in WAL mode; a pure READONLY connection cannot read
// an uncheckpointed WAL after the writer process exits (the -shm file is
// removed on last close and a read-only open cannot rebuild it), so
// verification opens read-write like the store itself does.
bool OpenDbReadOnly(const fs::path& db_path, sqlite3** db) {
  if (sqlite3_open_v2(db_path.c_str(), db,
                      SQLITE_OPEN_READWRITE, nullptr) != SQLITE_OK)
    return false;
  if (*db)
    sqlite3_busy_timeout(*db, 2000);
  return true;
}

// One-event batch with the given text sizes; preceding_text is the main
// variable field used to size batches precisely.
FactStore::Event MakeEvent(int seq, size_t preceding_len = 0,
                           int candidates = 3) {
  FactStore::Event event;
  event.event_id = "event-" + std::to_string(seq);
  event.schema_id = "test";
  event.canonical_segment_input = "shijie";
  event.span_start = 0;
  event.span_end = 6;
  event.category = "word";
  event.preceding_text.assign(preceding_len, 'x');
  event.competition_complete = true;
  event.final_selection_text = "世界";
  event.confirmation_source = "explicit_indexed";
  event.trigger_keycode = 0x32;
  event.display_rank = 1;
  event.display_page = 1;
  event.session_id = "session-" + std::to_string(seq);
  event.session_seq = seq;
  event.utc_confirmed_at_ms = 1700000000000LL + seq;
  for (int i = 0; i < candidates; ++i) {
    event.candidates.push_back(
        {i, std::string("cand-") + std::to_string(i)});
  }
  return event;
}

// Deterministic byte size of a batch whose only variable is
// `preceding_text` length: the coordinator's own formula, recomputed here
// independently from the field structure.
int64_t ExpectedBatchBytes(const std::vector<FactStore::Event>& events) {
  int64_t total = 0;
  for (const auto& event : events) {
    total += 16;
    total += static_cast<int64_t>(event.event_id.size());
    total += static_cast<int64_t>(event.commit_id.size());
    total += static_cast<int64_t>(event.schema_id.size());
    total += static_cast<int64_t>(event.canonical_segment_input.size());
    total += static_cast<int64_t>(event.category.size());
    total += static_cast<int64_t>(event.preceding_text.size());
    total += static_cast<int64_t>(event.final_selection_text.size());
    total += static_cast<int64_t>(event.confirmation_source.size());
    total += static_cast<int64_t>(event.session_id.size());
    total += 8 * 10 + 1;
    for (const auto& candidate : event.candidates) {
      total += 8 + static_cast<int64_t>(candidate.second.size());
    }
  }
  return total;
}

// Bounded wait on an external observable (never a bare sleep race).
bool WaitUntil(bool (*predicate)(const fs::path&), const fs::path& root,
               int64_t timeout_ms) {
  int64_t deadline = NowMs() + timeout_ms;
  while (NowMs() < deadline) {
    if (predicate(root))
      return true;
    usleep(20000);
  }
  return predicate(root);
}

bool HasCommits(const fs::path& root) {
  sqlite3* db = nullptr;
  fs::path db_path = root / "facts.sqlite3";
  if (!fs::exists(db_path) || !OpenDbReadOnly(db_path, &db))
    return false;
  long long count = QueryCount(db, "SELECT COUNT(*) FROM commits;");
  sqlite3_close(db);
  return count >= 1;
}

bool GapFileExists(const fs::path& root) {
  return fs::exists(root / "recording_gap.json");
}

// ---------------------------------------------------------------------------
// Spawned-process modes (multi-process coexistence / lock takeover / cross-
// process buffering). Relaunched via posix_spawn with a mode flag, mirroring
// the fact_store_test.cc spawned-writer precedent.
// ---------------------------------------------------------------------------

constexpr const char* kSpawnedCoordinatorWriter =
    "--llm-rerank-spawned-coord-writer";
constexpr const char* kSpawnedBufferingWriter =
    "--llm-rerank-spawned-buffering-writer";
constexpr const char* kSpawnedLockHolder = "--llm-rerank-spawned-lockholder";
constexpr int kSpawnedBatches = 8;

// Independent writer process: submits kSpawnedBatches through its own
// coordinator (fresh process = fresh per-process buffer). The base event
// sequence is passed in argv so concurrent writers never collide on
// event_ids. Exit 2 = store probe failed, 3 = a submit failed, 0 = all
// persisted.
void RunCoordinatorWriterLoop(const fs::path& root, int base_seq) {
  RecorderCoordinator coordinator(root);
  coordinator.SetPollIntervalMs(10);
  if (coordinator.VerifyStore() != FactStore::Status::kOk)
    _exit(2);
  for (int i = 0; i < kSpawnedBatches; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(base_seq + i)};
    auto result = coordinator.SubmitBatch(1700000000000LL + i, &events);
    if (result.outcome != RecorderCoordinator::Outcome::kPersisted &&
        result.outcome != RecorderCoordinator::Outcome::kBuffered) {
      _exit(3);
    }
  }
  _exit(0);
}

// Buffering writer process: the parent holds the exclusive lock, so every
// batch buffers; the process then waits (bounded) for the parent to release
// the lock and for its own flush thread to persist everything, without a
// single new key press. Exit 2 = probe failed, 3 = a submit was not
// buffered, 4 = flush did not complete in time, 0 = flushed.
long long CommitCount(const fs::path& root) {
  sqlite3* db = nullptr;
  fs::path db_path = root / "facts.sqlite3";
  if (!fs::exists(db_path) || !OpenDbReadOnly(db_path, &db))
    return -1;
  long long count = QueryCount(db, "SELECT COUNT(*) FROM commits;");
  sqlite3_close(db);
  return count;
}

// True when exactly `expected` commits exist (used by the buffering writer
// to wait for its OWN whole queue, not just the first flush).
bool HasExactlyCommits(const fs::path& root, int64_t expected) {
  return CommitCount(root) == expected;
}

// Bounded wait for the child's own whole queue to land.
bool WaitUntilAllCommitted(const fs::path& root, int64_t timeout_ms) {
  int64_t deadline = NowMs() + timeout_ms;
  while (NowMs() < deadline) {
    if (HasExactlyCommits(root, kSpawnedBatches))
      return true;
    usleep(20000);
  }
  return HasExactlyCommits(root, kSpawnedBatches);
}

void RunBufferingWriterLoop(const fs::path& root) {
  RecorderCoordinator coordinator(root);
  coordinator.SetPollIntervalMs(10);
  if (coordinator.VerifyStore() != FactStore::Status::kOk)
    _exit(2);
  for (int i = 0; i < kSpawnedBatches; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(300 + i)};
    auto result = coordinator.SubmitBatch(1700000100000LL + i, &events);
    if (result.outcome != RecorderCoordinator::Outcome::kBuffered)
      _exit(3);
  }
  if (!WaitUntilAllCommitted(root, 15000))
    _exit(4);
  _exit(0);
}

// Lock holder process: takes the exclusive maintenance lock and sleeps.
// Exit 2 = could not acquire, 0 = held until killed by the parent.
void RunLockHolderLoop(const fs::path& root) {
  MaintenanceLock lock(root);
  if (lock.TryAcquireExclusive() != MaintenanceLock::Status::kOk)
    _exit(2);
  sleep(60);
  _exit(0);
}

}  // namespace

// Dispatches spawned modes from main() (declared in llm_rerank_filter_test.cc
// and invoked there before gtest initializes).
void RunSpawnedCoordinatorMode(int argc, char** argv) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::strcmp(argv[i], kSpawnedCoordinatorWriter) == 0) {
      RunCoordinatorWriterLoop(fs::path(argv[i + 1]),
                               std::atoi(argv[i + 2]));
    } else if (std::strcmp(argv[i], kSpawnedBufferingWriter) == 0) {
      RunBufferingWriterLoop(fs::path(argv[i + 1]));
    } else if (std::strcmp(argv[i], kSpawnedLockHolder) == 0) {
      RunLockHolderLoop(fs::path(argv[i + 1]));
    }
  }
}

namespace {

pid_t SpawnSelf(const char* flag, const fs::path& root,
                const char* extra = nullptr) {
  char self_path[4096];
  uint32_t path_size = sizeof(self_path);
  if (_NSGetExecutablePath(self_path, &path_size) != 0)
    return -1;
  char* argv[] = {self_path, const_cast<char*>(flag),
                  const_cast<char*>(root.c_str()),
                  const_cast<char*>(extra ? extra : ""), nullptr};
  pid_t pid = -1;
  if (posix_spawn(&pid, self_path, nullptr, nullptr, argv, environ) != 0)
    return -1;
  return pid;
}

class RecorderCoordinatorTest : public ::testing::Test {
 protected:
  void SetUp() override {
    tmp_dir_ = MakeTempDir();
    ASSERT_FALSE(tmp_dir_.empty());
    root_ = fs::path(tmp_dir_) / "SemanticMemory";
    coordinator_ = std::make_unique<RecorderCoordinator>(root_);
    coordinator_->SetPollIntervalMs(10);
    ASSERT_EQ(FactStore::Status::kOk, coordinator_->VerifyStore());
  }

  void TearDown() override {
    coordinator_.reset();
    fs::remove_all(tmp_dir_);
  }

  std::unique_ptr<RecorderCoordinator> coordinator_;
  fs::path root_;
  std::string tmp_dir_;
};

}  // namespace

TEST_F(RecorderCoordinatorTest, FastPathPersistsSynchronously) {
  std::vector<FactStore::Event> events{MakeEvent(1)};
  auto result = coordinator_->SubmitBatch(1700000001000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kPersisted, result.outcome);
  EXPECT_FALSE(result.commit_id.empty());
  EXPECT_TRUE(result.fault_code.empty());
  EXPECT_FALSE(result.fatal);
  EXPECT_EQ(0, coordinator_->queued_batches());
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, ExclusiveLockBuffersWholeBatchWithoutWaiting) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  std::vector<FactStore::Event> events{MakeEvent(1)};
  auto result = coordinator_->SubmitBatch(1700000001000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome);
  EXPECT_FALSE(result.commit_id.empty());
  // The commit did not wait on the lock: nothing is on disk yet.
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(0LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
  EXPECT_EQ(1, coordinator_->queued_batches());

  lock.Release();
  // The background flush persists the batch with no further input.
  ASSERT_TRUE(coordinator_->WaitUntilDrained(5000));
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, SharedLockHeldDuringTransactionOnly) {
  // While the exclusive lock is held, a write reports kMaintenanceLocked
  // instead of waiting: the write path provably uses the shared lock.
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  FactStore store(root_);
  std::vector<FactStore::Event> events{MakeEvent(1)};
  ASSERT_EQ(FactStore::Status::kMaintenanceLocked,
            store.PersistBatch(1700000001000LL, &events));
  lock.Release();

  // After a successful transaction the shared lock (and its connection) is
  // fully released: an exclusive acquisition succeeds immediately.
  ASSERT_EQ(FactStore::Status::kOk,
            store.PersistBatch(1700000002000LL, &events));
  MaintenanceLock probe(root_);
  EXPECT_EQ(MaintenanceLock::Status::kOk, probe.TryAcquireExclusive());
}

TEST_F(RecorderCoordinatorTest, BufferLimitIsExactly256Batches) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  for (int i = 0; i < RecorderCoordinator::kMaxBufferedBatches; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(i)};
    auto result = coordinator_->SubmitBatch(1700000001000LL + i, &events);
    ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome)
        << "batch " << i;
  }
  EXPECT_EQ(RecorderCoordinator::kMaxBufferedBatches,
            coordinator_->queued_batches());
  // Batch 257 is refused; the old batches are untouched.
  std::vector<FactStore::Event> extra{MakeEvent(1000)};
  auto result = coordinator_->SubmitBatch(1700000009999LL, &extra);
  ASSERT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_batches", result.fault_code);
  EXPECT_EQ(RecorderCoordinator::kMaxBufferedBatches,
            coordinator_->queued_batches());
  EXPECT_EQ(1, coordinator_->gap_dropped_batches());
  EXPECT_TRUE(GapFileExists(root_));

  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(10000));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(256LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, BufferLimitIsExactly16MiB) {
  // Deterministic sizing: batch size is linear in preceding_text length.
  // Target 128 KiB per batch -> 128 batches = exactly 16 MiB, under the
  // 256-batch cap, so the byte limit binds first.
  std::vector<FactStore::Event> sized{MakeEvent(100000)};
  const int64_t base = ExpectedBatchBytes(sized);
  ASSERT_EQ(RecorderCoordinator::BatchByteSize(sized), base);
  const int64_t target_bytes = 128 * 1024;
  const int64_t preceding_len = target_bytes - base;
  ASSERT_GT(preceding_len, 0);
  // Fixed-width sequence numbers (5 digits): event_id/session_id lengths
  // must not change across the loop or the byte accounting drifts.
  std::vector<FactStore::Event> batch{MakeEvent(100000, preceding_len)};
  const int64_t batch_bytes = ExpectedBatchBytes(batch);
  ASSERT_EQ(batch_bytes, RecorderCoordinator::BatchByteSize(batch));
  ASSERT_EQ(target_bytes, batch_bytes);

  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  const int64_t kMaxBytes = RecorderCoordinator::kMaxBufferedBytes;
  const int64_t batch_count = kMaxBytes / batch_bytes;
  ASSERT_EQ(batch_count * batch_bytes, kMaxBytes);  // divides exactly
  for (int64_t i = 0; i < batch_count; ++i) {
    std::vector<FactStore::Event> events{
        MakeEvent(100000 + i, preceding_len)};
    auto result = coordinator_->SubmitBatch(1700000001000LL + i, &events);
    ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome)
        << "batch " << i;
  }
  EXPECT_EQ(kMaxBytes, coordinator_->queued_bytes());
  // The next batch exceeds the byte limit and is refused.
  std::vector<FactStore::Event> extra{MakeEvent(9999, preceding_len)};
  auto result = coordinator_->SubmitBatch(1700000009999LL, &extra);
  ASSERT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_bytes", result.fault_code);
  EXPECT_EQ(kMaxBytes, coordinator_->queued_bytes());

  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(10000));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(batch_count, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, GapRecordIsPrivacyClean) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  for (int i = 0; i < RecorderCoordinator::kMaxBufferedBatches + 1; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(i)};
    coordinator_->SubmitBatch(1700000001000LL + i, &events);
  }
  lock.Release();
  ASSERT_TRUE(GapFileExists(root_));
  RecordingGapRecord gap;
  ASSERT_TRUE(RecordingGapRecord::Read(root_, &gap));
  EXPECT_EQ(1, gap.dropped_batches);
  EXPECT_EQ("buffer_overflow_batches", gap.reason);
  // The record never contains 上文, candidate text or input: read the raw
  // file and prove the privacy markers of MakeEvent are absent.
  std::ifstream file(root_ / "recording_gap.json");
  std::string content((std::istreambuf_iterator<char>(file)),
                      std::istreambuf_iterator<char>());
  EXPECT_EQ(std::string::npos, content.find("世界"));
  EXPECT_EQ(std::string::npos, content.find("shijie"));
  EXPECT_EQ(std::string::npos, content.find("cand-"));
}

TEST_F(RecorderCoordinatorTest, FifoFlushKeepsBatchAtomicityAndOrder) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  std::vector<std::string> commit_ids;
  for (int i = 0; i < 3; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(i), MakeEvent(10 + i)};
    auto result = coordinator_->SubmitBatch(1700000001000LL + i, &events);
    ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome);
    commit_ids.push_back(result.commit_id);
  }
  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(5000));

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(3LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(6LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  // HLCs are strictly increasing in submission order, batch by batch.
  sqlite3_stmt* stmt = nullptr;
  const char* kHlcOrder =
      "SELECT hlc_physical_ms, hlc_logical, commit_id FROM selection_events"
      " ORDER BY hlc_physical_ms, hlc_logical, event_id;";
  ASSERT_EQ(SQLITE_OK, sqlite3_prepare_v2(db, kHlcOrder, -1, &stmt, nullptr));
  std::vector<std::string> seen_commits;
  int64_t prev_physical = -1;
  int64_t prev_logical = -1;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    int64_t physical = sqlite3_column_int64(stmt, 0);
    int64_t logical = sqlite3_column_int64(stmt, 1);
    if (prev_physical >= 0) {
      EXPECT_TRUE(physical > prev_physical ||
                  (physical == prev_physical && logical > prev_logical));
    }
    prev_physical = physical;
    prev_logical = logical;
    seen_commits.push_back(
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)));
  }
  sqlite3_finalize(stmt);
  // FIFO: the first batch's events come first and both events of one commit
  // are adjacent (never split across batches).
  ASSERT_EQ(6u, seen_commits.size());
  EXPECT_EQ(commit_ids[0], seen_commits[0]);
  EXPECT_EQ(commit_ids[0], seen_commits[1]);
  EXPECT_EQ(commit_ids[1], seen_commits[2]);
  EXPECT_EQ(commit_ids[1], seen_commits[3]);
  EXPECT_EQ(commit_ids[2], seen_commits[4]);
  EXPECT_EQ(commit_ids[2], seen_commits[5]);
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, BufferedRetractionLandsAfterItsBatch) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  std::vector<FactStore::Event> events{MakeEvent(1), MakeEvent(2)};
  auto batch = coordinator_->SubmitBatch(1700000001000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, batch.outcome);
  auto retraction =
      coordinator_->SubmitRetraction(batch.commit_id, 1700000002000LL);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, retraction.outcome);
  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(5000));

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM retractions;"));
  // Whole-commit undo: nothing is active afterwards, and the retraction HLC
  // comes strictly after the batch HLC.
  std::string retraction_clock = QueryText(
      db, "SELECT hlc_physical_ms || ':' || hlc_logical FROM retractions;");
  std::string event_clock = QueryText(
      db, "SELECT MAX(hlc_physical_ms || ':' || hlc_logical)"
          " FROM selection_events;");
  EXPECT_GT(retraction_clock, event_clock);
  std::vector<FactStore::Event> active;
  FactStore store(root_);
  ASSERT_TRUE(store.QueryActiveEventsAsOf(NowMs() + 1000000, 0, &active));
  EXPECT_TRUE(active.empty());
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, RetractionOfBufferedBatchNeverTouchesEarlierCommits) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  // Commit A is persisted before maintenance starts.
  lock.Release();
  std::vector<FactStore::Event> first{MakeEvent(1)};
  auto result_a = coordinator_->SubmitBatch(1700000001000LL, &first);
  ASSERT_EQ(RecorderCoordinator::Outcome::kPersisted, result_a.outcome);
  ASSERT_TRUE(coordinator_->WaitUntilDrained(5000));

  // During maintenance: commit B buffers; an immediate BackSpace retracts B
  // (queued behind it), never A.
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  std::vector<FactStore::Event> second{MakeEvent(2)};
  auto result_b = coordinator_->SubmitBatch(1700000003000LL, &second);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result_b.outcome);
  auto retraction = coordinator_->SubmitRetraction(result_b.commit_id,
                                                   1700000004000LL);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, retraction.outcome);
  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(5000));

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(2LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  std::string retracted =
      QueryText(db, "SELECT commit_id FROM retractions;");
  EXPECT_EQ(result_b.commit_id, retracted);
  sqlite3_close(db);
  std::vector<FactStore::Event> active;
  FactStore store(root_);
  ASSERT_TRUE(store.QueryActiveEventsAsOf(NowMs() + 1000000, 0, &active));
  // Only B's event is retracted; A remains active.
  ASSERT_EQ(1u, active.size());
  EXPECT_EQ("event-1", active[0].event_id);
}

TEST_F(RecorderCoordinatorTest, FlushReopensStoreUnderNewEpochWithFreshClock) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  std::vector<FactStore::Event> events{MakeEvent(1)};
  auto result = coordinator_->SubmitBatch(1700000001000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome);
  std::string buffered_commit = result.commit_id;

  // Maintenance replaces the store (restore/clear): new epoch, new clock.
  // The buffered batch must land in the NEW store.
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  std::string old_epoch = QueryText(db, "SELECT value FROM meta WHERE key='store_epoch';");
  sqlite3_close(db);
  fs::remove(root_ / "facts.sqlite3");
  fs::remove(root_ / "facts.sqlite3-wal");
  fs::remove(root_ / "facts.sqlite3-shm");
  FactStore fresh(root_);
  ASSERT_EQ(FactStore::Status::kOk, fresh.Open());
  // Read the NEW store's identity directly (the exclusive lock is still
  // held, so the shared-lock API would refuse; a plain meta read is all the
  // test needs to pin the linearization point).
  sqlite3* fresh_db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &fresh_db));
  std::string new_epoch =
      QueryText(fresh_db, "SELECT value FROM meta WHERE key='store_epoch';");
  int64_t new_clock_physical =
      QueryCount(fresh_db, "SELECT value FROM meta"
                           " WHERE key='hlc_physical_ms';");
  int64_t new_clock_logical =
      QueryCount(fresh_db, "SELECT value FROM meta"
                           " WHERE key='hlc_logical';");
  sqlite3_close(fresh_db);
  ASSERT_NE(old_epoch, new_epoch);

  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(5000));

  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(new_epoch, QueryText(db,
      "SELECT value FROM meta WHERE key='store_epoch';"));
  std::string commit = QueryText(db,
      "SELECT commit_id FROM commits LIMIT 1;");
  EXPECT_EQ(buffered_commit, commit);
  int64_t hlc_physical =
      QueryCount(db, "SELECT hlc_physical_ms FROM selection_events LIMIT 1;");
  int64_t hlc_logical =
      QueryCount(db, "SELECT hlc_logical FROM selection_events LIMIT 1;");
  // HLC is allocated after the new store's clock (the maintenance
  // linearization point), never from the old epoch's pre-assigned clock.
  EXPECT_TRUE(hlc_physical > new_clock_physical ||
              (hlc_physical == new_clock_physical &&
               hlc_logical > new_clock_logical));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, ShutdownLeftoversFormPersistentGap) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  for (int i = 0; i < 3; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(i)};
    ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
              coordinator_->SubmitBatch(1700000001000LL + i, &events)
                  .outcome);
  }
  // Destroy the coordinator while the exclusive lock is still held: the
  // known-but-unpersisted batches become a persistent recording gap.
  coordinator_.reset();
  ASSERT_TRUE(GapFileExists(root_));
  RecordingGapRecord gap;
  ASSERT_TRUE(RecordingGapRecord::Read(root_, &gap));
  EXPECT_EQ(3, gap.dropped_batches);
  EXPECT_EQ("shutdown_unpersisted", gap.reason);
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(0LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, SessionsShareOneProcessWideBufferLimit) {
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  // Two "sessions" interleave submissions into the same coordinator: the
  // limits are process-wide, not per session.
  for (int i = 0; i < RecorderCoordinator::kMaxBufferedBatches; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(i)};
    auto result = coordinator_->SubmitBatch(1700000001000LL + i, &events);
    ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome);
  }
  std::vector<FactStore::Event> extra{MakeEvent(999)};
  auto result = coordinator_->SubmitBatch(1700000009999LL, &extra);
  ASSERT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_batches", result.fault_code);
  lock.Release();
  ASSERT_TRUE(coordinator_->WaitUntilDrained(10000));
}

TEST_F(RecorderCoordinatorTest, FatalStoreFaultStopsRecordingAndFormsGap) {
  // Deterministic store fault: recording must stop (fatal) and the refusal
  // forms a gap; the files are never modified or relaxed.
  chmod(root_.c_str(), 0755);
  std::vector<FactStore::Event> events{MakeEvent(1)};
  auto result = coordinator_->SubmitBatch(1700000001000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_TRUE(result.fatal);
  EXPECT_EQ("root_permission", result.fault_code);
  EXPECT_EQ(1, coordinator_->gap_dropped_batches());
}

TEST_F(RecorderCoordinatorTest, MultiProcessWritersCoexistUnderSharedLock) {
  pid_t pid_a = SpawnSelf(kSpawnedCoordinatorWriter, root_, "200");
  pid_t pid_b = SpawnSelf(kSpawnedCoordinatorWriter, root_, "400");
  ASSERT_GT(pid_a, 0);
  ASSERT_GT(pid_b, 0);
  int status = 0;
  ASSERT_EQ(pid_a, waitpid(pid_a, &status, 0));
  ASSERT_TRUE(WIFEXITED(status));
  EXPECT_EQ(0, WEXITSTATUS(status));
  ASSERT_EQ(pid_b, waitpid(pid_b, &status, 0));
  ASSERT_TRUE(WIFEXITED(status));
  EXPECT_EQ(0, WEXITSTATUS(status));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(2LL * kSpawnedBatches,
            QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, CrossProcessBufferFlushesAfterExclusiveRelease) {
  // Parent holds the exclusive lock; the child's batches must buffer, then
  // flush on its own once the parent releases — with no further input.
  MaintenanceLock lock(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());
  pid_t child = SpawnSelf(kSpawnedBufferingWriter, root_);
  ASSERT_GT(child, 0);
  // Give the child a moment to submit its batches while the lock is held,
  // then verify nothing landed yet (deterministic: flush cannot acquire).
  usleep(300000);
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(0LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
  lock.Release();
  int status = 0;
  ASSERT_EQ(child, waitpid(child, &status, 0));
  ASSERT_TRUE(WIFEXITED(status));
  EXPECT_EQ(0, WEXITSTATUS(status)) << "child could not flush after release";
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(kSpawnedBatches, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(RecorderCoordinatorTest, AdvisoryLockIsTakenOverAfterProcessDeath) {
  pid_t holder = SpawnSelf(kSpawnedLockHolder, root_);
  ASSERT_GT(holder, 0);
  // Wait for the child to grab the lock (bounded), then kill it: the kernel
  // must release the advisory lock so the parent can take it over. The probe
  // releases its own acquisition each round, so it never blocks the child.
  MaintenanceLock probe(root_);
  int64_t deadline = NowMs() + 5000;
  while (NowMs() < deadline) {
    if (probe.TryAcquireExclusive() ==
        MaintenanceLock::Status::kMaintenanceLocked)
      break;
    probe.Release();
    usleep(20000);
  }
  ASSERT_EQ(0, kill(holder, SIGKILL));
  int status = 0;
  ASSERT_EQ(holder, waitpid(holder, &status, 0));
  MaintenanceLock takeover(root_);
  ASSERT_EQ(MaintenanceLock::Status::kOk, takeover.TryAcquireExclusive());
}
