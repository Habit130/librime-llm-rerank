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

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
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

}  // namespace
