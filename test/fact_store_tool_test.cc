//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Deterministic tests for the fact_store_tool seam used by the physical
// clear operation (Habit130/squirrel#54): fresh empty-store creation, durable
// identity verification, and the empty/HLC/reset semantics the Python
// executor must never re-derive on its own.
#include <mach-o/dyld.h>
#include <spawn.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <thread>
#include <vector>

extern char** environ;

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "fact_store.h"
#include "recorder_session.h"

using namespace rime;

namespace fs = std::filesystem;

namespace {

std::string MakeTempDir() {
  char tmpl[] = "/tmp/llm_rerank_tool_XXXXXX";
  char* dir = mkdtemp(tmpl);
  if (!dir)
    return "";
  return std::string(dir);
}

// Runs the helper binary with posix_spawn (fork + sqlite3 in the same
// process image is unsafe on macOS; see Habit130/squirrel#92) and captures
// its stdout. Returns (exit status, trimmed output).
std::pair<int, std::string> RunTool(std::vector<std::string> args) {
  int pipe_fds[2];
  if (pipe(pipe_fds) != 0)
    return {-1, ""};
  std::vector<char*> argv;
  argv.push_back(const_cast<char*>(LLM_RERANK_FACT_STORE_TOOL));
  for (auto& arg : args)
    argv.push_back(const_cast<char*>(arg.c_str()));
  argv.push_back(nullptr);
  posix_spawn_file_actions_t actions;
  posix_spawn_file_actions_init(&actions);
  posix_spawn_file_actions_adddup2(&actions, pipe_fds[1], STDOUT_FILENO);
  posix_spawn_file_actions_addclose(&actions, pipe_fds[0]);
  pid_t pid = -1;
  int spawn_rc = posix_spawn(&pid, argv[0], &actions, nullptr,
                             argv.data(), environ);
  posix_spawn_file_actions_destroy(&actions);
  close(pipe_fds[1]);
  if (spawn_rc != 0) {
    close(pipe_fds[0]);
    return {-1, ""};
  }
  std::string output;
  char buffer[512];
  ssize_t count;
  while ((count = read(pipe_fds[0], buffer, sizeof(buffer))) > 0)
    output.append(buffer, static_cast<size_t>(count));
  close(pipe_fds[0]);
  int status = 0;
  waitpid(pid, &status, 0);
  while (!output.empty() && (output.back() == '\n' || output.back() == '\r'))
    output.pop_back();
  int exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
  return {exit_code, output};
}

std::string JsonField(const std::string& payload, const char* key) {
  std::string needle = std::string("\"") + key + "\":";
  size_t pos = payload.find(needle);
  if (pos == std::string::npos)
    return "";
  pos += needle.size();
  while (pos < payload.size() && payload[pos] == ' ')
    ++pos;
  if (pos >= payload.size())
    return "";
  if (payload[pos] == '"') {
    ++pos;
    size_t end = payload.find('"', pos);
    return end == std::string::npos ? "" : payload.substr(pos, end - pos);
  }
  size_t end = payload.find_first_of(",}", pos);
  return payload.substr(pos, end == std::string::npos
                               ? std::string::npos : end - pos);
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

class FactStoreToolTest : public ::testing::Test {
 protected:
  void SetUp() override {
    tmp_dir_ = MakeTempDir();
    ASSERT_FALSE(tmp_dir_.empty());
    store_root_ = fs::path(tmp_dir_) / "SemanticMemory";
    staging_root_ = fs::path(tmp_dir_) / "staging";
  }

  void TearDown() override { fs::remove_all(tmp_dir_); }

  // Populates the live root with one committed event so it is a non-empty
  // store with a proven high HLC watermark.
  void PopulateLiveStore() {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    std::vector<FactStore::Event> events(1);
    events[0].event_id = "live-event-1";
    events[0].schema_id = "test";
    events[0].canonical_segment_input = "shijie";
    events[0].category = "word";
    events[0].preceding_text = "";
    events[0].competition_complete = true;
    events[0].final_selection_text = "世界";
    events[0].confirmation_source = "explicit_indexed";
    events[0].session_id = "session-1";
    events[0].session_seq = 1;
    events[0].utc_confirmed_at_ms = 1700000000000LL;
    events[0].candidates = {{0, "世界"}, {1, "时界"}};
    ASSERT_TRUE(store.PersistBatch(1700000000000LL, &events));
  }

  std::string tmp_dir_;
  fs::path store_root_;
  fs::path staging_root_;
};

TEST_F(FactStoreToolTest, VerifyMissingStoreReportsNoStore) {
  auto result = RunTool({"verify", "--root", store_root_.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos, result.second.find("\"no_store\""));
}

TEST_F(FactStoreToolTest, CreateEmptyProducesFreshValidatedStore) {
  const int64_t before_ms = NowMs();
  auto result =
      RunTool({"create-empty", "--root", staging_root_.string()});
  ASSERT_EQ(0, result.first) << result.second;
  const int64_t after_ms = NowMs();
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":true"));
  EXPECT_NE(std::string::npos, result.second.find("\"empty\":true"));
  EXPECT_NE(std::string::npos, result.second.find("\"created\":true"));
  const std::string history_id = JsonField(result.second, "history_id");
  const std::string store_epoch = JsonField(result.second, "store_epoch");
  EXPECT_EQ(32u, history_id.size());
  EXPECT_EQ(32u, store_epoch.size());
  EXPECT_NE(history_id, store_epoch);
  EXPECT_EQ("0", JsonField(result.second, "hlc_logical"));
  const std::string physical = JsonField(result.second, "hlc_physical_ms");
  ASSERT_FALSE(physical.empty());
  const long long physical_ms = std::atoll(physical.c_str());
  // The initial HLC physical component is the creation-time wall clock, not
  // a carried-over watermark.
  EXPECT_GE(physical_ms, before_ms);
  EXPECT_LE(physical_ms, after_ms);
  // Exactly the main database, owner-owned 0600, no residual WAL/SHM.
  struct stat st;
  const fs::path db_path = staging_root_ / "facts.sqlite3";
  ASSERT_EQ(0, lstat(db_path.c_str(), &st));
  EXPECT_TRUE(S_ISREG(st.st_mode));
  EXPECT_EQ(0600u, st.st_mode & 0777);
  EXPECT_EQ(getuid(), st.st_uid);
  EXPECT_FALSE(fs::exists(staging_root_ / "facts.sqlite3-wal"));
  EXPECT_FALSE(fs::exists(staging_root_ / "facts.sqlite3-shm"));
  // The fresh store verifies back through the same C++ fact semantics.
  auto verify = RunTool({"verify", "--root", staging_root_.string()});
  ASSERT_EQ(0, verify.first) << verify.second;
  EXPECT_EQ(history_id, JsonField(verify.second, "history_id"));
  EXPECT_EQ(store_epoch, JsonField(verify.second, "store_epoch"));
  EXPECT_NE(std::string::npos, verify.second.find("\"empty\":true"));
}

TEST_F(FactStoreToolTest, CreateEmptyNeverReusesRootOrIdentity) {
  auto first =
      RunTool({"create-empty", "--root", staging_root_.string()});
  ASSERT_EQ(0, first.first);
  // Recreating over the same directory is refused: the Python executor owns
  // the staging directory lifecycle and never silently reuses a root.
  auto second =
      RunTool({"create-empty", "--root", staging_root_.string()});
  ASSERT_EQ(1, second.first);
  EXPECT_NE(std::string::npos, second.second.find("\"root_exists\""));
  // A second staging root gets fresh, distinct identities.
  const fs::path other = fs::path(tmp_dir_) / "staging2";
  auto third = RunTool({"create-empty", "--root", other.string()});
  ASSERT_EQ(0, third.first);
  EXPECT_NE(JsonField(first.second, "history_id"),
            JsonField(third.second, "history_id"));
  EXPECT_NE(JsonField(first.second, "store_epoch"),
            JsonField(third.second, "store_epoch"));
}

TEST_F(FactStoreToolTest, VerifyPopulatedStoreReportsIdentityAndNonEmpty) {
  PopulateLiveStore();
  int64_t physical = 0;
  int64_t logical = 0;
  std::string epoch;
  std::string history_id;
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    ASSERT_EQ(FactStore::Status::kOk,
              store.ReadStoreIdentity(&physical, &logical, &epoch,
                                      &history_id));
  }
  auto result = RunTool({"verify", "--root", store_root_.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_EQ(epoch, JsonField(result.second, "store_epoch"));
  EXPECT_EQ(history_id, JsonField(result.second, "history_id"));
  EXPECT_NE(std::string::npos, result.second.find("\"empty\":false"));
  EXPECT_EQ(std::to_string(logical),
            JsonField(result.second, "hlc_logical"));
}

TEST_F(FactStoreToolTest, VerifyCorruptStoreFailsClosed) {
  PopulateLiveStore();
  // Flip bytes in the middle of the main database file.
  const fs::path db_path = store_root_ / "facts.sqlite3";
  {
    FILE* file = std::fopen(db_path.c_str(), "r+");
    ASSERT_NE(nullptr, file);
    ASSERT_EQ(0, std::fseek(file, 4096, SEEK_SET));
    const char garbage = static_cast<char>('\xff');
    ASSERT_EQ(1u, std::fwrite(&garbage, 1, 1, file));
    std::fclose(file);
  }
  auto result = RunTool({"verify", "--root", store_root_.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos, result.second.find("\"db_corrupt\""));
}

TEST_F(FactStoreToolTest, VerifyUnsupportedVersionFailsClosed) {
  PopulateLiveStore();
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK,
            sqlite3_open_v2((store_root_ / "facts.sqlite3").c_str(), &db,
                            SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "UPDATE meta SET value='999'"
          " WHERE key='fact_schema_version';", nullptr, nullptr, nullptr));
  sqlite3_close(db);
  auto result = RunTool({"verify", "--root", store_root_.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos,
            result.second.find("\"db_unsupported_version\""));
}

TEST_F(FactStoreToolTest, ClearIdentityResetDoesNotCarryHighWatermark) {
  // A live store with an artificially huge HLC physical watermark.
  PopulateLiveStore();
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK,
            sqlite3_open_v2((store_root_ / "facts.sqlite3").c_str(), &db,
                            SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "UPDATE meta SET value='999999999999999'"
          " WHERE key='hlc_physical_ms';", nullptr, nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "UPDATE meta SET value='999999'"
          " WHERE key='hlc_logical';", nullptr, nullptr, nullptr));
  sqlite3_close(db);
  auto result =
      RunTool({"create-empty", "--root", staging_root_.string()});
  ASSERT_EQ(0, result.first) << result.second;
  // The new store's clock starts fresh: logical zero, physical is the wall
  // clock at creation, far below the artificially advanced watermark.
  EXPECT_EQ("0", JsonField(result.second, "hlc_logical"));
  const long long physical_ms =
      std::atoll(JsonField(result.second, "hlc_physical_ms").c_str());
  EXPECT_LT(physical_ms, 999999999999999LL);
  EXPECT_GT(physical_ms, 0LL);
}

TEST_F(FactStoreToolTest, VerifyEmptyTracksFactTablesDirectly) {
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    bool empty = false;
    ASSERT_EQ(FactStore::Status::kOk, store.VerifyEmpty(&empty));
    EXPECT_TRUE(empty);
  }
  PopulateLiveStore();
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    bool empty = true;
    ASSERT_EQ(FactStore::Status::kOk, store.VerifyEmpty(&empty));
    EXPECT_FALSE(empty);
  }
}

// ---------------------------------------------------------------------------
// Online Backup snapshot seam (Habit130/squirrel#55)
// ---------------------------------------------------------------------------

// Direct stats query against the snapshot with the shared fact schema (the
// test owns the fixture; the implementation never interprets fact rows in
// Python). The fixture's own single-event batch is excluded from the
// batch-atomicity check, which only counts the concurrent writer's batches.
namespace {

bool QuerySnapshotIntegrity(const std::string& db_path, int64_t* commits,
                            int64_t* events, int64_t* partial_batches,
                            int64_t* hlc_physical, int64_t* hlc_logical) {
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    return false;
  }
  auto run_count = [&](const char* sql) -> int64_t {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
      return -1;
    int64_t value = sqlite3_step(stmt) == SQLITE_ROW
                        ? sqlite3_column_int64(stmt, 0)
                        : -1;
    sqlite3_finalize(stmt);
    return value;
  };
  bool ok = true;
  *commits = run_count("SELECT COUNT(*) FROM commits;");
  *events = run_count("SELECT COUNT(*) FROM selection_events;");
  *partial_batches = run_count(
      "SELECT COUNT(*) FROM (SELECT commit_id FROM selection_events"
      " WHERE event_id LIKE 'concurrent-%'"
      " GROUP BY commit_id HAVING COUNT(*) <> 3);");
  sqlite3_stmt* clock = nullptr;
  if (sqlite3_prepare_v2(db,
                         "SELECT value FROM meta WHERE key = "
                         "'hlc_physical_ms';", -1, &clock, nullptr) !=
      SQLITE_OK) {
    ok = false;
  }
  if (ok && sqlite3_step(clock) == SQLITE_ROW) {
    *hlc_physical = sqlite3_column_int64(clock, 0);
  } else {
    ok = false;
  }
  sqlite3_finalize(clock);
  sqlite3_close(db);
  return ok;
}

}  // namespace

TEST_F(FactStoreToolTest, SnapshotProducesValidatedSingleFile) {
  PopulateLiveStore();
  int64_t physical = 0;
  int64_t logical = 0;
  std::string epoch;
  std::string history_id;
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    ASSERT_EQ(FactStore::Status::kOk,
              store.ReadStoreIdentity(&physical, &logical, &epoch,
                                      &history_id));
  }
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  auto result = RunTool({"snapshot", "--root", store_root_.string(),
                         "--output", output.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":true"));
  EXPECT_EQ(history_id, JsonField(result.second, "history_id"));
  EXPECT_EQ(epoch, JsonField(result.second, "store_epoch"));
  EXPECT_EQ("1", JsonField(result.second, "fact_schema_version"));
  EXPECT_EQ("1", JsonField(result.second, "event_format_version_min"));
  EXPECT_EQ("1", JsonField(result.second, "event_format_version_max"));
  EXPECT_EQ("1", JsonField(result.second, "commit_count"));
  EXPECT_EQ("1", JsonField(result.second, "event_count"));
  EXPECT_EQ("2", JsonField(result.second, "candidate_count"));
  EXPECT_EQ("0", JsonField(result.second, "retraction_count"));
  EXPECT_EQ(std::to_string(logical),
            JsonField(result.second, "hlc_logical"));
  // The snapshot is a single regular owner-owned 0600 file with no WAL/SHM
  // sidecars and no dependency on the live store.
  struct stat st;
  ASSERT_EQ(0, lstat(output.c_str(), &st));
  EXPECT_TRUE(S_ISREG(st.st_mode));
  EXPECT_EQ(0600u, st.st_mode & 0777);
  EXPECT_EQ(getuid(), st.st_uid);
  EXPECT_FALSE(fs::exists(output.string() + "-wal"));
  EXPECT_FALSE(fs::exists(output.string() + "-shm"));
  // The live store was not modified or blocked by the snapshot.
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    int64_t now_physical = 0;
    int64_t now_logical = 0;
    std::string now_epoch;
    ASSERT_EQ(FactStore::Status::kOk,
              store.ReadStoreIdentity(&now_physical, &now_logical, &now_epoch,
                                      nullptr));
    EXPECT_EQ(epoch, now_epoch);
    EXPECT_EQ(physical, now_physical);
    EXPECT_EQ(logical, now_logical);
  }
  // inspect re-validates the standalone snapshot file.
  auto inspect = RunTool({"inspect", "--db", output.string()});
  ASSERT_EQ(0, inspect.first) << inspect.second;
  EXPECT_EQ(history_id, JsonField(inspect.second, "history_id"));
}

TEST_F(FactStoreToolTest, SnapshotOfEmptyStoreReportsEmptyMarkers) {
  auto created = RunTool({"create-empty", "--root", staging_root_.string()});
  ASSERT_EQ(0, created.first) << created.second;
  const fs::path output = fs::path(tmp_dir_) / "empty-snapshot.sqlite3";
  auto result = RunTool({"snapshot", "--root", store_root_.string(),
                         "--output", output.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_EQ("0", JsonField(result.second, "commit_count"));
  EXPECT_EQ("0", JsonField(result.second, "event_count"));
  EXPECT_EQ("-1", JsonField(result.second, "event_format_version_min"));
  EXPECT_EQ("-1", JsonField(result.second, "event_format_version_max"));
  EXPECT_EQ("-1", JsonField(result.second, "event_hlc_physical_ms"));
  EXPECT_EQ("0", JsonField(result.second, "hlc_logical"));
  EXPECT_NE(JsonField(result.second, "store_epoch"),
            JsonField(created.second, "store_epoch"));
}

TEST_F(FactStoreToolTest, SnapshotRefusesExistingOutput) {
  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  auto second = RunTool({"snapshot", "--root", store_root_.string(),
                         "--output", output.string()});
  ASSERT_EQ(1, second.first);
  EXPECT_NE(std::string::npos, second.second.find("\"output_exists\""));
}

TEST_F(FactStoreToolTest, InspectRejectsNonSqliteAndCorruptFiles) {
  const fs::path text = fs::path(tmp_dir_) / "not-a-db.sqlite3";
  {
    FILE* file = std::fopen(text.c_str(), "w");
    ASSERT_NE(nullptr, file);
    std::fputs("this is not a database", file);
    std::fclose(file);
  }
  auto text_result = RunTool({"inspect", "--db", text.string()});
  ASSERT_EQ(1, text_result.first);
  // A non-SQLite file either fails to open or fails integrity; both are
  // stable fail-closed codes, never success.
  EXPECT_NE(std::string::npos, text_result.second.find("\"ok\":false"));

  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  {
    FILE* file = std::fopen(output.c_str(), "r+");
    ASSERT_NE(nullptr, file);
    ASSERT_EQ(0, std::fseek(file, 4096, SEEK_SET));
    const char garbage = static_cast<char>('\xff');
    ASSERT_EQ(1u, std::fwrite(&garbage, 1, 1, file));
    std::fclose(file);
  }
  auto corrupt = RunTool({"inspect", "--db", output.string()});
  ASSERT_EQ(1, corrupt.first);
  EXPECT_NE(std::string::npos, corrupt.second.find("\"ok\":false"));
}

TEST_F(FactStoreToolTest, InspectRejectsWalDependentDatabase) {
  // A WAL-mode database whose main file was never checkpointed is not a
  // complete single-file snapshot and must be rejected by inspect.
  const fs::path wal_db = fs::path(tmp_dir_) / "wal-db.sqlite3";
  {
    sqlite3* db = nullptr;
    ASSERT_EQ(SQLITE_OK,
              sqlite3_open_v2(wal_db.c_str(), &db, SQLITE_OPEN_READWRITE
                              | SQLITE_OPEN_CREATE, nullptr));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(db, "PRAGMA journal_mode=WAL;",
                                      nullptr, nullptr, nullptr));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(db, "CREATE TABLE t(x);", nullptr,
                                      nullptr, nullptr));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(db, "INSERT INTO t VALUES(1);",
                                      nullptr, nullptr, nullptr));
    sqlite3_close(db);
  }
  auto result = RunTool({"inspect", "--db", wal_db.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":false"));
}

TEST_F(FactStoreToolTest, ConcurrentWriterSnapshotIsConsistent) {
  // A writer keeps committing 3-event batches in a tight loop while the
  // snapshot runs. The snapshot must correspond to one consistent read
  // point: every commit batch appears wholly or not at all, integrity
  // holds, and the writer is never blocked or rolled back.
  PopulateLiveStore();
  std::atomic<bool> stop{false};
  std::atomic<int64_t> written_batches{0};
  std::thread writer([&]() {
    FactStore store(store_root_);
    if (store.Open() != FactStore::Status::kOk)
      return;
    int64_t batch = 0;
    while (!stop.load()) {
      std::vector<FactStore::Event> events(3);
      for (int index = 0; index < 3; ++index) {
        events[index].event_id = "concurrent-" +
            std::to_string(batch) + "-" + std::to_string(index);
        events[index].schema_id = "test";
        events[index].category = "word";
        events[index].competition_complete = true;
        events[index].final_selection_text = "世";
        events[index].confirmation_source = "explicit_current";
        events[index].session_id = "concurrent-session";
        events[index].session_seq = static_cast<int>(batch * 3 + index);
        events[index].utc_confirmed_at_ms = 1700000000000LL + batch;
        events[index].candidates = {{0, "世"}, {1, "是"}};
      }
      if (store.PersistBatch(1700000000000LL + batch, &events)) {
        ++written_batches;
      }
      ++batch;
    }
  });
  const fs::path output = fs::path(tmp_dir_) / "concurrent-snapshot.sqlite3";
  auto result = RunTool({"snapshot", "--root", store_root_.string(),
                         "--output", output.string()});
  stop.store(true);
  writer.join();
  ASSERT_EQ(0, result.first) << result.second;
  // The writer progressed during the snapshot: the snapshot contains a
  // prefix of the batches, and every commit in it is complete.
  int64_t commits = 0;
  int64_t events = 0;
  int64_t partial = -1;
  int64_t clock_physical = 0;
  int64_t clock_logical = 0;
  ASSERT_TRUE(QuerySnapshotIntegrity(output.string(), &commits, &events,
                                     &partial, &clock_physical,
                                     &clock_logical));
  EXPECT_GT(written_batches.load(), 0);
  EXPECT_GE(commits, 2);
  // The fixture commit carries one event; every concurrent batch is whole.
  EXPECT_EQ((commits - 1) * 3 + 1, events);
  EXPECT_EQ(0, partial);
  // The writer's own connection still sees a healthy, complete store.
  FactStore store(store_root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  int64_t final_physical = 0;
  int64_t final_logical = 0;
  std::string final_epoch;
  ASSERT_EQ(FactStore::Status::kOk,
            store.ReadStoreIdentity(&final_physical, &final_logical,
                                    &final_epoch, nullptr));
  // The durable clock advanced past the snapshot's read point and the
  // snapshot never exceeded what existed on disk.
  EXPECT_GE(final_physical, clock_physical);
}

// ---------------------------------------------------------------------------
// Schema disposition seam (Habit130/squirrel#58)
// ---------------------------------------------------------------------------

TEST_F(FactStoreToolTest, SchemaReportsCurrentDisposition) {
  PopulateLiveStore();
  auto result = RunTool({"schema", "--root", store_root_.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":true"));
  EXPECT_NE(std::string::npos, result.second.find("\"disposition\":\"current\""));
  EXPECT_EQ("1", JsonField(result.second, "fact_schema_version"));
  EXPECT_EQ("1", JsonField(result.second, "event_format_version"));
  EXPECT_FALSE(JsonField(result.second, "store_epoch").empty());
}

TEST_F(FactStoreToolTest, SchemaMissingStoreReportsNoStore) {
  auto result = RunTool({"schema", "--root", store_root_.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos, result.second.find("\"no_store\""));
}

TEST_F(FactStoreToolTest, SchemaTooNewEventFormatReportsUnsupported) {
  // A store whose event_format_version exceeds the canonical format this
  // build writes is too new (SCN-58-5): the recorder Open() fails closed on
  // it, so the migrate operation must see `unsupported`, never `current`.
  PopulateLiveStore();
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((store_root_ / "facts.sqlite3").c_str(),
                                       &db, SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "UPDATE meta SET value='5' WHERE key='event_format_version';",
      nullptr, nullptr, nullptr));
  sqlite3_close(db);
  auto result = RunTool({"schema", "--root", store_root_.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_NE(std::string::npos,
            result.second.find("\"disposition\":\"unsupported\""));
  EXPECT_EQ("5", JsonField(result.second, "event_format_version"));
}

TEST_F(FactStoreToolTest, MigrateCurrentFileIsNoOp) {
  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  // Without the test seam the production head is 1 and the snapshot is
  // already current: migrating is a validated no-op.
  auto result = RunTool({"migrate", "--db", output.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_NE(std::string::npos, result.second.find("\"status\":\"no_migration\""));
  EXPECT_EQ("1", JsonField(result.second, "to_version"));
}

// ---------------------------------------------------------------------------
// Migrate seam with the test predecessor step (decision B)
// ---------------------------------------------------------------------------

TEST_F(FactStoreToolTest, MigrateSnapshotWithTestStepToHead) {
  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  // The snapshot is a v1 store; the test predecessor v1 -> v2 (preserving)
  // is registered by the env seam in the migrate subprocess.
  setenv("SQUIRREL_FACT_MIGRATE_TEST_STEPS", "1", 1);
  auto result = RunTool({"migrate", "--db", output.string()});
  unsetenv("SQUIRREL_FACT_MIGRATE_TEST_STEPS");
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_NE(std::string::npos,
            result.second.find("\"status\":\"migrated\""));
  EXPECT_EQ("1", JsonField(result.second, "from_version"));
  EXPECT_EQ("2", JsonField(result.second, "to_version"));
  EXPECT_EQ("false", JsonField(result.second, "epoch_changed"));
  // Verify the migrated file's durable meta directly: schema version 2,
  // canonical event format, facts intact, epoch preserved (interpretation-
  // preserving step).
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(output.c_str(), &db,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("2", QueryText(db,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_EQ("1", QueryText(db,
      "SELECT value FROM meta WHERE key='event_format_version';"));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  EXPECT_EQ(0LL, QueryCount(db,
      "SELECT COUNT(*) FROM selection_events WHERE"
      " event_format_version <> 1;"));
  sqlite3_close(db);
}

// ---------------------------------------------------------------------------
// Restore epoch-minting seam (Habit130/squirrel#56)
// ---------------------------------------------------------------------------

TEST_F(FactStoreToolTest, PrepareRestoreMintsNewEpochKeepingHistory) {
  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  // The snapshot's own durable epoch/history, read directly.
  sqlite3* before = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(output.c_str(), &before,
                                       SQLITE_OPEN_READONLY, nullptr));
  const std::string snapshot_epoch = QueryText(
      before, "SELECT value FROM meta WHERE key='store_epoch';");
  const std::string snapshot_history = QueryText(
      before, "SELECT value FROM meta WHERE key='history_id';");
  sqlite3_close(before);

  auto result = RunTool({"prepare-restore", "--db", output.string()});
  ASSERT_EQ(0, result.first) << result.second;
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":true"));
  EXPECT_NE(std::string::npos,
            result.second.find("\"status\":\"prepared\""));
  const std::string new_epoch = JsonField(result.second, "store_epoch");
  EXPECT_EQ(32u, new_epoch.size());
  EXPECT_NE(snapshot_epoch, new_epoch);
  EXPECT_EQ(snapshot_epoch,
            JsonField(result.second, "previous_store_epoch"));
  // history_id is preserved; the facts and HLC are preserved verbatim.
  EXPECT_EQ(snapshot_history, JsonField(result.second, "history_id"));
  EXPECT_EQ("1", JsonField(result.second, "event_count"));
  EXPECT_EQ("2", JsonField(result.second, "candidate_count"));
  EXPECT_EQ("0", JsonField(result.second, "retraction_count"));
  // The durable meta now carries the new epoch and the old one is gone.
  sqlite3* after = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(output.c_str(), &after,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ(new_epoch, QueryText(
      after, "SELECT value FROM meta WHERE key='store_epoch';"));
  EXPECT_EQ(snapshot_history, QueryText(
      after, "SELECT value FROM meta WHERE key='history_id';"));
  EXPECT_EQ(1LL, QueryCount(after, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(after);
  // The prepared file still validates as a standalone store.
  auto inspect = RunTool({"inspect", "--db", output.string()});
  ASSERT_EQ(0, inspect.first) << inspect.second;
  EXPECT_EQ(new_epoch, JsonField(inspect.second, "store_epoch"));
  EXPECT_EQ(snapshot_history, JsonField(inspect.second, "history_id"));
}

TEST_F(FactStoreToolTest, PrepareRestoreRejectsSupportedOldWithoutMigration) {
  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  // With the test predecessor step the head is 2; a v1 file is supported-old
  // and must fail closed (the restore operation migrates the staging copy
  // first, never here).
  setenv("SQUIRREL_FACT_MIGRATE_TEST_STEPS", "1", 1);
  auto result = RunTool({"prepare-restore", "--db", output.string()});
  unsetenv("SQUIRREL_FACT_MIGRATE_TEST_STEPS");
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos,
            result.second.find("\"needs_migration\""));
  // The file's facts and epoch are unchanged.
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(output.c_str(), &db,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("1", QueryText(db,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(db);
}

TEST_F(FactStoreToolTest, PrepareRestoreRejectsTooNewVersion) {
  PopulateLiveStore();
  const fs::path output = fs::path(tmp_dir_) / "snapshot.sqlite3";
  ASSERT_EQ(0, RunTool({"snapshot", "--root", store_root_.string(),
                        "--output", output.string()}).first);
  {
    sqlite3* db = nullptr;
    ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(output.c_str(), &db,
                                         SQLITE_OPEN_READWRITE, nullptr));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(
        db, "UPDATE meta SET value='99' WHERE key='fact_schema_version';",
        nullptr, nullptr, nullptr));
    sqlite3_close(db);
  }
  auto result = RunTool({"prepare-restore", "--db", output.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos,
            result.second.find("\"unsupported_version\""));
}

TEST_F(FactStoreToolTest, PrepareRestoreFailsClosedOnCorruptFile) {
  const fs::path text = fs::path(tmp_dir_) / "not-a-db.sqlite3";
  {
    FILE* file = std::fopen(text.c_str(), "w");
    ASSERT_NE(nullptr, file);
    std::fputs("this is not a database", file);
    std::fclose(file);
  }
  auto result = RunTool({"prepare-restore", "--db", text.string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":false"));
}

TEST_F(FactStoreToolTest, PrepareRestoreNeverTouchesTheLiveRoot) {
  // A stale staging path must never point at the live root; prepare-restore
  // takes --db only and a live store is WAL-mode, which the seam refuses, so
  // the live store's epoch must be untouched.
  PopulateLiveStore();
  int64_t physical = 0;
  int64_t logical = 0;
  std::string epoch;
  std::string history_id;
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    ASSERT_EQ(FactStore::Status::kOk,
              store.ReadStoreIdentity(&physical, &logical, &epoch,
                                      &history_id));
  }
  auto result = RunTool({"prepare-restore", "--db",
                         (store_root_ / "facts.sqlite3").string()});
  ASSERT_EQ(1, result.first);
  EXPECT_NE(std::string::npos, result.second.find("\"ok\":false"));
  {
    FactStore store(store_root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    int64_t now_physical = 0;
    int64_t now_logical = 0;
    std::string now_epoch;
    ASSERT_EQ(FactStore::Status::kOk,
              store.ReadStoreIdentity(&now_physical, &now_logical, &now_epoch,
                                      nullptr));
    EXPECT_EQ(epoch, now_epoch);
    EXPECT_EQ(physical, now_physical);
    EXPECT_EQ(logical, now_logical);
  }
}

}  // namespace
