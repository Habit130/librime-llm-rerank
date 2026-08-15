//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/stat.h>
#include <sys/wait.h>

#include <mach-o/dyld.h>
#include <spawn.h>
#include <unistd.h>

#include <cerrno>
#include <condition_variable>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "maintenance_lock.h"
#include "recorder_coordinator.h"

namespace fs = std::filesystem;
using namespace rime;

extern char** environ;

namespace {

// Installs a process-wide recorder I/O hook and restores the no-hook state on
// destruction. Tests must release any blocking hook before the guard dies.
class IOHookGuard {
 public:
  explicit IOHookGuard(RecorderIOHook hook) {
    RecorderCoordinator::SetIOHookForTesting(std::move(hook));
  }
  ~IOHookGuard() { RecorderCoordinator::SetIOHookForTesting(nullptr); }
};

// Blocks the worker at the first observed recorder I/O operation until
// Release() is called; later operations pass through untouched. Deterministic
// via barriers: WaitUntilEntered() returns exactly when the worker is parked
// inside the hook, and Release() is the only event that lets it proceed.
class BlockingIOHook {
 public:
  BlockingIOHook() {
    RecorderCoordinator::SetIOHookForTesting([this](const char* op) -> int {
      (void)op;
      std::unique_lock<std::mutex> lock(mutex_);
      if (blocked_once_)
        return 0;
      blocked_once_ = true;
      entered_ = true;
      entered_cv_.notify_all();
      release_cv_.wait(lock, [this] { return release_; });
      return 0;
    });
  }
  ~BlockingIOHook() {
    Release();
    RecorderCoordinator::SetIOHookForTesting(nullptr);
  }
  void WaitUntilEntered() {
    std::unique_lock<std::mutex> lock(mutex_);
    entered_cv_.wait(lock, [this] { return entered_; });
  }
  void Release() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      release_ = true;
    }
    release_cv_.notify_all();
  }

 private:
  std::mutex mutex_;
  std::condition_variable entered_cv_;
  std::condition_variable release_cv_;
  bool entered_ = false;
  bool release_ = false;
  bool blocked_once_ = false;
};

std::string MakeTempDir() {
  char template_path[] = "/tmp/llm_rerank_coordinator_XXXXXX";
  char* result = mkdtemp(template_path);
  return result ? result : "";
}

FactStore::Event MakeEvent(const std::string& id) {
  FactStore::Event event;
  event.event_id = id;
  event.schema_id = "test";
  event.canonical_segment_input = "shi";
  event.span_end = 3;
  event.category = "word";
  event.competition_complete = true;
  event.final_selection_text = "是";
  event.confirmation_source = "explicit_current";
  event.session_id = "test";
  event.candidates = {{0, "是"}, {1, "时"}};
  return event;
}

int64_t QueryCount(const fs::path& db_path, const char* sql) {
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    if (db)
      sqlite3_close(db);
    return -1;
  }
  sqlite3_stmt* statement = nullptr;
  int64_t result = -1;
  if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK &&
      sqlite3_step(statement) == SQLITE_ROW) {
    result = sqlite3_column_int64(statement, 0);
  }
  if (statement)
    sqlite3_finalize(statement);
  sqlite3_close(db);
  return result;
}

std::string QueryText(const fs::path& db_path, const char* sql) {
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    if (db)
      sqlite3_close(db);
    return "";
  }
  sqlite3_stmt* statement = nullptr;
  std::string result;
  if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK &&
      sqlite3_step(statement) == SQLITE_ROW) {
    const unsigned char* value = sqlite3_column_text(statement, 0);
    if (value)
      result = reinterpret_cast<const char*>(value);
  }
  if (statement)
    sqlite3_finalize(statement);
  sqlite3_close(db);
  return result;
}

std::vector<std::string> QueryEventOrder(const fs::path& db_path) {
  sqlite3* db = nullptr;
  std::vector<std::string> result;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    if (db)
      sqlite3_close(db);
    return result;
  }
  sqlite3_stmt* statement = nullptr;
  if (sqlite3_prepare_v2(
          db, "SELECT event_id FROM selection_events ORDER BY hlc_physical_ms,"
              " hlc_logical, event_id;",
          -1, &statement, nullptr) == SQLITE_OK) {
    while (sqlite3_step(statement) == SQLITE_ROW) {
      const unsigned char* value = sqlite3_column_text(statement, 0);
      if (value)
        result.emplace_back(reinterpret_cast<const char*>(value));
    }
  }
  if (statement)
    sqlite3_finalize(statement);
  sqlite3_close(db);
  return result;
}

std::pair<int64_t, int64_t> QueryEventHlc(const fs::path& db_path,
                                          const std::string& event_id) {
  sqlite3* db = nullptr;
  std::pair<int64_t, int64_t> result = {-1, -1};
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    if (db)
      sqlite3_close(db);
    return result;
  }
  sqlite3_stmt* statement = nullptr;
  const char* sql = "SELECT hlc_physical_ms, hlc_logical FROM selection_events"
                    " WHERE event_id = ?;";
  if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
    sqlite3_bind_text(statement, 1, event_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(statement) == SQLITE_ROW) {
      result.first = sqlite3_column_int64(statement, 0);
      result.second = sqlite3_column_int64(statement, 1);
    }
  }
  if (statement)
    sqlite3_finalize(statement);
  sqlite3_close(db);
  return result;
}

std::string ReadFile(const fs::path& path) {
  std::ifstream stream(path);
  return std::string(std::istreambuf_iterator<char>(stream),
                     std::istreambuf_iterator<char>());
}

constexpr const char* kSpawnedGapWriterFlag =
    "--llm-rerank-spawned-gap-writer";
constexpr const char* kSpawnedCrashWriterFlag =
    "--llm-rerank-spawned-crash-writer";

void RunSpawnedGapWriter(const fs::path& root) {
  MaintenanceLock exclusive;
  if (!exclusive.Acquire(root, MaintenanceLock::Mode::kExclusive))
    _exit(2);
  auto coordinator = RecorderCoordinator::ForRoot(root);
  for (int index = 0; index < 257; ++index) {
    std::vector<FactStore::Event> events{
        MakeEvent("child-gap-" + std::to_string(index))};
    const auto result = coordinator->SubmitBatch(1700000001000LL + index, &events);
    if ((index < 256 && result.outcome != RecorderCoordinator::Outcome::kBuffered) ||
        (index == 256 && result.outcome != RecorderCoordinator::Outcome::kGap)) {
      _exit(3);
    }
  }
  exclusive.Release();
  coordinator->FlushForTesting();
  RecorderCoordinator::ShutdownAll();
  _exit(0);
}

void RunSpawnedCrashWriter(const fs::path& root) {
  // The crash point is deterministic: the child dies exactly after its
  // process marker was created and written, while a buffered batch is still
  // unpersisted behind the exclusive maintenance lease.
  std::mutex sync;
  std::condition_variable marker_written;
  bool written = false;
  RecorderCoordinator::SetIOHookForTesting([&](const char* op) -> int {
    if (strcmp(op, "marker_state_write") == 0) {
      std::lock_guard<std::mutex> lock(sync);
      written = true;
      marker_written.notify_all();
    }
    return 0;
  });
  MaintenanceLock exclusive;
  if (!exclusive.Acquire(root, MaintenanceLock::Mode::kExclusive))
    _exit(2);
  auto coordinator = RecorderCoordinator::ForRoot(root);
  std::vector<FactStore::Event> events{MakeEvent("crash-event")};
  if (coordinator->SubmitBatch(1700000000000LL, &events).outcome !=
      RecorderCoordinator::Outcome::kBuffered) {
    _exit(3);
  }
  {
    std::unique_lock<std::mutex> lock(sync);
    marker_written.wait(lock, [&] { return written; });
  }
  // Crash: no shutdown, no marker cleanup. The kernel releases the marker
  // flock; the stale file is the durable crash evidence.
  _exit(9);
}

pid_t SpawnGapWriter(const fs::path& root) {
  char self_path[4096];
  uint32_t path_size = sizeof(self_path);
  if (_NSGetExecutablePath(self_path, &path_size) != 0)
    return -1;
  char* argv[] = {self_path, const_cast<char*>(kSpawnedGapWriterFlag),
                  const_cast<char*>(root.c_str()), nullptr};
  pid_t pid = -1;
  if (posix_spawn(&pid, self_path, nullptr, nullptr, argv, environ) != 0)
    return -1;
  return pid;
}

pid_t SpawnCrashWriter(const fs::path& root) {
  char self_path[4096];
  uint32_t path_size = sizeof(self_path);
  if (_NSGetExecutablePath(self_path, &path_size) != 0)
    return -1;
  char* argv[] = {self_path, const_cast<char*>(kSpawnedCrashWriterFlag),
                  const_cast<char*>(root.c_str()), nullptr};
  pid_t pid = -1;
  if (posix_spawn(&pid, self_path, nullptr, nullptr, argv, environ) != 0)
    return -1;
  return pid;
}

}  // namespace

// Invoked from main before gtest initialization when the test binary is
// re-executed as the second process in the gap-accumulation test.
void RunSpawnedRecorderGapMode(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index) {
    if (std::string(argv[index]) == kSpawnedGapWriterFlag)
      RunSpawnedGapWriter(fs::path(argv[index + 1]));
    if (std::string(argv[index]) == kSpawnedCrashWriterFlag)
      RunSpawnedCrashWriter(fs::path(argv[index + 1]));
  }
}

namespace {

class RecorderCoordinatorTest : public ::testing::Test {
 protected:
  void SetUp() override {
    temp_ = MakeTempDir();
    ASSERT_FALSE(temp_.empty());
    root_ = fs::path(temp_) / "SemanticMemory";
  }

  void TearDown() override {
    RecorderCoordinator::ShutdownAll();
    fs::remove_all(temp_);
  }

  fs::path root_;
  std::string temp_;
};

TEST_F(RecorderCoordinatorTest, ExclusiveLockPreventsFreshOpenMutation) {
  fs::create_directories(root_);
  ASSERT_EQ(0, chmod(root_.c_str(), 0700));
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));

  FactStore store(root_);
  EXPECT_EQ(FactStore::Status::kMaintenanceLocked, store.Open());
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3"));
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3-wal"));
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3-shm"));
}

TEST_F(RecorderCoordinatorTest, BufferedCommitAndRetractionStayCausal) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> events{MakeEvent("buffered-event")};
  auto commit = coordinator->SubmitBatch(1700000000000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, commit.outcome);
  ASSERT_FALSE(commit.commit_id.empty());
  auto retraction = coordinator->SubmitRetraction(commit.commit_id,
                                                   1700000000001LL);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, retraction.outcome);

  exclusive.Release();
  coordinator->FlushForTesting();
  const fs::path db_path = root_ / "facts.sqlite3";
  EXPECT_EQ(1, QueryCount(db_path, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(1, QueryCount(db_path, "SELECT COUNT(*) FROM selection_events;"));
  EXPECT_EQ(1, QueryCount(db_path, "SELECT COUNT(*) FROM retractions;"));
  EXPECT_EQ(0, QueryCount(db_path, "SELECT COUNT(*) FROM active_events;"));
}

TEST_F(RecorderCoordinatorTest, InputOnlyQueuesWhileMaintenanceOwnsTheStore) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> events{MakeEvent("queued-only")};
  auto result = coordinator->SubmitBatch(1700000000000LL, &events);
  EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered, result.outcome);
  // The submission has no store side effect while the worker is denied the
  // maintenance lease. It returned before any SQLite/FULL-sync path ran.
  EXPECT_EQ(0, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
  exclusive.Release();
  coordinator->FlushForTesting();
  EXPECT_EQ(1, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
}

TEST_F(RecorderCoordinatorTest, NewCommitCannotOvertakeAnOlderBufferedBatch) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> first{MakeEvent("fifo-first")};
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &first).outcome);
  // The maintenance lease is released before the second commit arrives, so
  // the worker may already be flushing while the newer batch lands in the
  // queue. The FIFO enqueue order must still win.
  exclusive.Release();
  std::vector<FactStore::Event> second{MakeEvent("fifo-second")};
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000001LL, &second).outcome);
  coordinator->FlushForTesting();
  const auto order = QueryEventOrder(root_ / "facts.sqlite3");
  ASSERT_EQ(2u, order.size());
  EXPECT_EQ("fifo-first", order[0]);
  EXPECT_EQ("fifo-second", order[1]);
}

TEST_F(RecorderCoordinatorTest,
       RetractionAfterReleaseAppliesToEarlierBufferedBatch) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> events{MakeEvent("late-retraction")};
  auto commit = coordinator->SubmitBatch(1700000000000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, commit.outcome);
  exclusive.Release();
  // The retraction arrives after the lease release, while its target batch
  // may still be buffered. It must follow the batch in FIFO order and take
  // effect instead of becoming an unknown no-op.
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitRetraction(commit.commit_id, 1700000000001LL)
                .outcome);
  coordinator->FlushForTesting();
  const fs::path db_path = root_ / "facts.sqlite3";
  EXPECT_EQ(1, QueryCount(db_path, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(1, QueryCount(db_path, "SELECT COUNT(*) FROM retractions;"));
  EXPECT_EQ(0, QueryCount(db_path, "SELECT COUNT(*) FROM active_events;"));
}

TEST_F(RecorderCoordinatorTest, OverflowPreservesQueuedBatchesAndPublishesGap) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  for (int index = 0; index < 256; ++index) {
    std::vector<FactStore::Event> events{MakeEvent("batch-" +
                                                     std::to_string(index))};
    EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered,
              coordinator->SubmitBatch(1700000000000LL + index, &events).outcome);
  }
  std::vector<FactStore::Event> overflow{MakeEvent("batch-overflow")};
  overflow.front().preceding_text = "PRIVATE_RECORDING_GAP_MARKER";
  auto result = coordinator->SubmitBatch(1700000000257LL, &overflow);
  EXPECT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_batches", result.fault_code);

  exclusive.Release();
  coordinator->FlushForTesting();
  const fs::path db_path = root_ / "facts.sqlite3";
  EXPECT_EQ(256, QueryCount(db_path, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(256, QueryCount(db_path, "SELECT COUNT(*) FROM selection_events;"));
  EXPECT_EQ(0, QueryCount(db_path,
                          "SELECT COUNT(*) FROM selection_events"
                          " WHERE event_id = 'batch-overflow';"));
  const std::string gap = ReadFile(root_ / "recording_gap.json");
  EXPECT_NE(std::string::npos, gap.find("\"gap_version\":2"));
  EXPECT_NE(std::string::npos, gap.find("\"state\":\"present\""));
  EXPECT_NE(std::string::npos, gap.find("buffer_overflow_batches"));
  EXPECT_NE(std::string::npos, gap.find("\"store_epoch\":\""));
  EXPECT_NE(std::string::npos, gap.find("\"dropped_batches\":1"));
  EXPECT_EQ(std::string::npos, gap.find("PRIVATE_RECORDING_GAP_MARKER"));
}

TEST_F(RecorderCoordinatorTest, GapAccumulatesAcrossIndependentProcesses) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  for (int index = 0; index < 257; ++index) {
    std::vector<FactStore::Event> events{
        MakeEvent("parent-gap-" + std::to_string(index))};
    const auto result = coordinator->SubmitBatch(1700000002000LL + index, &events);
    ASSERT_EQ(index < 256 ? RecorderCoordinator::Outcome::kBuffered
                          : RecorderCoordinator::Outcome::kGap,
              result.outcome);
  }
  exclusive.Release();
  coordinator->FlushForTesting();
  const pid_t child = SpawnGapWriter(root_);
  ASSERT_GE(child, 0);
  coordinator->FlushForTesting();

  int status = 0;
  pid_t waited;
  do {
    waited = waitpid(child, &status, 0);
  } while (waited < 0 && errno == EINTR);
  ASSERT_EQ(child, waited);
  ASSERT_TRUE(WIFEXITED(status));
  ASSERT_EQ(0, WEXITSTATUS(status));

  const std::string gap = ReadFile(root_ / "recording_gap.json");
  EXPECT_NE(std::string::npos, gap.find("\"dropped_batches\":2"));
  EXPECT_NE(std::string::npos, gap.find("\"dropped_events\":2"));
}

TEST_F(RecorderCoordinatorTest, CrashedRecorderLeavesDurableCrashEvidence) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  const pid_t child = SpawnCrashWriter(root_);
  ASSERT_GE(child, 0);
  int status = 0;
  pid_t waited;
  do {
    waited = waitpid(child, &status, 0);
  } while (waited < 0 && errno == EINTR);
  ASSERT_EQ(child, waited);
  ASSERT_TRUE(WIFEXITED(status));
  ASSERT_EQ(9, WEXITSTATUS(status));
  // The crashed child performed no marker cleanup: the stale marker file is
  // the durable crash evidence. The status reader interprets a non-live
  // marker as unknown (daemon/test_maintenance.py), and the buffered batch
  // never reached the store.
  bool marker_found = false;
  for (const auto& entry : fs::directory_iterator(root_)) {
    if (entry.path().filename().string().rfind(".recording_process.", 0) == 0)
      marker_found = true;
  }
  EXPECT_TRUE(marker_found);
  EXPECT_EQ(0, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
}

TEST_F(RecorderCoordinatorTest, FailedGapPublicationLeavesAnIntentMarker) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> initial{MakeEvent("initialize-gap-state")};
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &initial).outcome);
  coordinator->FlushForTesting();
  ASSERT_TRUE(fs::is_regular_file(root_ / "recording_gap.json"));

  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  fs::remove(root_ / "recording_gap.json");
  ASSERT_TRUE(fs::create_directory(root_ / "recording_gap.json"));
  for (int index = 0; index < 257; ++index) {
    std::vector<FactStore::Event> events{
        MakeEvent("failed-gap-" + std::to_string(index))};
    ASSERT_EQ(index < 256 ? RecorderCoordinator::Outcome::kBuffered
                          : RecorderCoordinator::Outcome::kGap,
              coordinator->SubmitBatch(1700000003000LL + index, &events).outcome);
  }
  exclusive.Release();
  coordinator->FlushForTesting();

  bool found_intent = false;
  for (const auto& entry : fs::directory_iterator(root_)) {
    if (entry.path().filename().string().rfind(".recording_gap_intent.", 0) == 0) {
      found_intent = true;
      break;
    }
  }
  EXPECT_TRUE(found_intent);
}

TEST_F(RecorderCoordinatorTest, LegacyV1GapIsMigratedWithoutLosingCounts) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  {
    std::ofstream stream(root_ / "recording_gap.json");
    stream << "{\"gap_version\":1,\"reason\":\"buffer_overflow_batches\","
              "\"dropped_batches\":1,\"dropped_events\":2,"
              "\"dropped_retractions\":0,\"dropped_bytes\":3,"
              "\"updated_at_ms\":1}";
  }
  ASSERT_EQ(0, chmod((root_ / "recording_gap.json").c_str(), 0600));

  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  for (int index = 0; index < 257; ++index) {
    std::vector<FactStore::Event> events{
        MakeEvent("legacy-gap-" + std::to_string(index))};
    ASSERT_EQ(index < 256 ? RecorderCoordinator::Outcome::kBuffered
                          : RecorderCoordinator::Outcome::kGap,
              coordinator->SubmitBatch(1700000004000LL + index, &events).outcome);
  }
  exclusive.Release();
  coordinator->FlushForTesting();

  const std::string gap = ReadFile(root_ / "recording_gap.json");
  EXPECT_NE(std::string::npos, gap.find("\"gap_version\":2"));
  EXPECT_NE(std::string::npos, gap.find("\"dropped_batches\":2"));
  EXPECT_NE(std::string::npos, gap.find("\"dropped_events\":3"));
}

TEST_F(RecorderCoordinatorTest, StaleOwnerAfterShutdownCannotStrandTheWorker) {
  auto stale = RecorderCoordinator::ForRoot(root_);
  RecorderCoordinator::ShutdownAll();

  std::vector<FactStore::Event> events{MakeEvent("stale-owner")};
  const auto result = stale->SubmitBatch(1700000000000LL, &events);
  EXPECT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("recorder_stopped", result.fault_code);
  stale->FlushForTesting();
}

TEST_F(RecorderCoordinatorTest, RecorderProcessMarkerIsPrivateAndCleaned) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  // The marker is established by the worker before the first flush; the
  // drain point makes its existence deterministic.
  coordinator->FlushForTesting();
  fs::path marker;
  for (const auto& entry : fs::directory_iterator(root_)) {
    if (entry.path().filename().string().rfind(".recording_process.", 0) == 0) {
      marker = entry.path();
      break;
    }
  }
  ASSERT_FALSE(marker.empty());
  EXPECT_EQ("clean\n", ReadFile(marker));
  EXPECT_EQ(std::string::npos, ReadFile(marker).find("preceding_text"));

  RecorderCoordinator::ShutdownAll();
  coordinator.reset();
  EXPECT_FALSE(fs::exists(marker));
}

TEST_F(RecorderCoordinatorTest, RejectsTheFirstBatchPast16MiB) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> exact{MakeEvent("byte-boundary")};
  // SubmitBatch assigns a 32-byte commit id before accounting the canonical
  // payload, so the independent boundary fixture includes that final field.
  exact.front().commit_id.assign(32, '0');
  const int64_t base = RecorderCoordinator::BatchLogicalBytes(exact);
  ASSERT_LT(base, 16LL * 1024 * 1024);
  exact.front().preceding_text.assign(
      static_cast<size_t>(16LL * 1024 * 1024 - base), 'x');
  ASSERT_EQ(16LL * 1024 * 1024,
            RecorderCoordinator::BatchLogicalBytes(exact));
  EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &exact).outcome);
  std::vector<FactStore::Event> over{MakeEvent("byte-overflow")};
  auto result = coordinator->SubmitBatch(1700000000001LL, &over);
  EXPECT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_bytes", result.fault_code);
}

TEST_F(RecorderCoordinatorTest, FlushesBufferedBatchIntoReplacementEpoch) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  const fs::path replacement_root = fs::path(temp_) / "replacement";
  int64_t replacement_physical = 0;
  int64_t replacement_logical = 0;
  std::string replacement_epoch;
  {
    FactStore replacement(replacement_root);
    ASSERT_EQ(FactStore::Status::kOk, replacement.Open());
    std::vector<FactStore::Event> bootstrap{MakeEvent("replacement-bootstrap")};
    ASSERT_TRUE(replacement.PersistBatch(1700000000000LL, &bootstrap));
    ASSERT_EQ(FactStore::Status::kOk,
              replacement.ReadStoreIdentity(&replacement_physical,
                                            &replacement_logical,
                                            &replacement_epoch));
  }

  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> queued{MakeEvent("replacement-queued")};
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000001000LL, &queued).outcome);
  for (const char* suffix : {"", "-wal", "-shm"})
    fs::remove(root_ / (std::string("facts.sqlite3") + suffix));
  for (const char* suffix : {"", "-wal", "-shm"}) {
    const fs::path source = replacement_root / (std::string("facts.sqlite3") + suffix);
    if (fs::exists(source))
      fs::rename(source, root_ / source.filename());
  }
  exclusive.Release();

  coordinator->FlushForTesting();
  const fs::path db_path = root_ / "facts.sqlite3";
  EXPECT_EQ(replacement_epoch,
            QueryText(db_path, "SELECT value FROM meta WHERE key='store_epoch';"));
  const auto queued_hlc = QueryEventHlc(db_path, "replacement-queued");
  EXPECT_LT(std::make_pair(replacement_physical, replacement_logical), queued_hlc);
  EXPECT_EQ(1, QueryCount(db_path,
                          "SELECT COUNT(*) FROM selection_events"
                          " WHERE event_id = 'replacement-queued';"));
}

TEST_F(RecorderCoordinatorTest, ShutdownLeftoversPublishAPersistentGap) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> events{MakeEvent("shutdown-event")};
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &events).outcome);

  RecorderCoordinator::ShutdownAll();
  const std::string gap = ReadFile(root_ / "recording_gap.json");
  EXPECT_NE(std::string::npos, gap.find("shutdown_unpersisted"));
  EXPECT_NE(std::string::npos, gap.find("\"state\":\"present\""));
  EXPECT_EQ(0, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
}

TEST_F(RecorderCoordinatorTest, LogicalBytesAreIndependentOfVectorCapacity) {
  std::vector<FactStore::Event> compact{MakeEvent("event")};
  std::vector<FactStore::Event> reserved = compact;
  reserved.reserve(128);
  reserved.front().candidates.reserve(128);
  EXPECT_EQ(RecorderCoordinator::BatchLogicalBytes(compact),
            RecorderCoordinator::BatchLogicalBytes(reserved));
}

TEST_F(RecorderCoordinatorTest, MarkerFsyncCannotBlockACommitSubmission) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  BlockingIOHook hook;
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  hook.WaitUntilEntered();
  // The worker is deterministically parked inside marker fsync right now. A
  // commit must still complete from memory alone; if the input path waited
  // on the worker's durable I/O, this submission would never return and the
  // test deadlocks instead of asserting.
  std::vector<FactStore::Event> events{MakeEvent("hot-path")};
  EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &events).outcome);
  hook.Release();
  coordinator->FlushForTesting();
  EXPECT_EQ(1, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
}

TEST_F(RecorderCoordinatorTest, MarkerCreationFailureDoesNotRejectEvents) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  // The marker is crash evidence, not a precondition for recording: while it
  // cannot be created the healthy store keeps receiving every committed
  // batch, so no artificial loss is created.
  IOHookGuard hook([](const char* op) -> int {
    return strcmp(op, "marker_create") == 0 ? -1 : 0;
  });
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> events{MakeEvent("marker-down")};
  EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &events).outcome);
  coordinator->FlushForTesting();
  EXPECT_EQ(1, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
  bool marker_found = false;
  for (const auto& entry : fs::directory_iterator(root_)) {
    if (entry.path().filename().string().rfind(".recording_process.", 0) == 0)
      marker_found = true;
  }
  EXPECT_FALSE(marker_found);
}

TEST_F(RecorderCoordinatorTest,
       GapPersistenceFailureLeavesDurableUnknownLockState) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  // Establish the evidence primitives (marker, gap lock, gap record) before
  // any loss can occur.
  coordinator->FlushForTesting();
  ASSERT_TRUE(fs::is_regular_file(root_ / "recording_gap.lock"));
  ASSERT_TRUE(fs::is_regular_file(root_ / "recording_gap.json"));

  // Every gap publication attempt now fails, including the intent fallback.
  // The pre-existing gap lock must still carry the durable unknown state, so
  // after a process restart status reads unknown instead of none.
  IOHookGuard hook([](const char* op) -> int {
    return (strcmp(op, "gap_json_write") == 0 ||
            strcmp(op, "intent_create") == 0)
               ? -1
               : 0;
  });
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  for (int index = 0; index < 257; ++index) {
    std::vector<FactStore::Event> events{
        MakeEvent("failed-gap-" + std::to_string(index))};
    ASSERT_EQ(index < 256 ? RecorderCoordinator::Outcome::kBuffered
                          : RecorderCoordinator::Outcome::kGap,
              coordinator->SubmitBatch(1700000003000LL + index, &events)
                  .outcome);
  }
  exclusive.Release();
  coordinator->FlushForTesting();

  EXPECT_EQ("unknown\n", ReadFile(root_ / "recording_gap.lock"));
  // The durable unknown marker survives a clean coordinator shutdown: it is
  // the restart evidence, not a live process handle.
  bool marker_found = false;
  for (const auto& entry : fs::directory_iterator(root_)) {
    if (entry.path().filename().string().rfind(".recording_process.", 0) == 0)
      marker_found = true;
  }
  EXPECT_TRUE(marker_found);
}

TEST_F(RecorderCoordinatorTest,
       FirstCommitDoesNotCreateStoreOrEvidenceSynchronously) {
  BlockingIOHook hook;
  // The coordinator is constructed exactly where the commit notifier builds
  // it; the worker immediately parks at its first evidence step.
  auto coordinator = RecorderCoordinator::ForRoot(root_);
  hook.WaitUntilEntered();
  // The first commit must return having touched nothing durable: no store,
  // no marker, no gap record. Initialization belongs to the worker.
  std::vector<FactStore::Event> events{MakeEvent("first-commit")};
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator->SubmitBatch(1700000000000LL, &events).outcome);
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3"));
  EXPECT_FALSE(fs::exists(root_ / "recording_gap.json"));
  EXPECT_FALSE(fs::exists(root_ / "recording_gap.lock"));
  hook.Release();
  coordinator->FlushForTesting();
  EXPECT_EQ(1, QueryCount(root_ / "facts.sqlite3",
                          "SELECT COUNT(*) FROM selection_events;"));
}

}  // namespace
