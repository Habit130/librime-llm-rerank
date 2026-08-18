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
#include <filesystem>
#include <string>
#include <vector>

extern char** environ;

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "fact_store.h"
#include "maintenance_lock.h"

using namespace rime;

namespace fs = std::filesystem;

namespace {

std::string MakeTempDir() {
  char tmpl[] = "/tmp/llm_rerank_store_XXXXXX";
  char* dir = mkdtemp(tmpl);
  if (!dir)
    return "";
  return std::string(dir);
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

bool OpenDbReadOnly(const fs::path& db_path, sqlite3** db) {
  return sqlite3_open_v2(db_path.c_str(), db,
                         SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK;
}

FactStore::Event MakeEvent(int seq) {
  FactStore::Event event;
  event.event_id = "event-" + std::to_string(seq);
  event.schema_id = "test";
  event.canonical_segment_input = "shijie";
  event.span_start = 0;
  event.span_end = 6;
  event.category = "word";
  event.preceding_text = "";
  event.competition_complete = true;
  event.final_selection_text = "世界";
  event.confirmation_source = "explicit_indexed";
  event.trigger_keycode = 0x32;
  event.display_rank = 1;
  event.display_page = 1;
  event.session_id = "session-" + std::to_string(seq);
  event.session_seq = seq;
  event.utc_confirmed_at_ms = 1700000000000LL + seq;
  event.candidates = {{0, "世界"}, {1, "时界"}, {2, "石阶"}};
  return event;
}

struct RetractionRow {
  std::string retraction_id;
  std::string commit_id;
  long long hlc_physical_ms = 0;
  long long hlc_logical = 0;
  long long utc_retracted_at_ms = 0;
};

bool ReadRetractions(sqlite3* db, std::vector<RetractionRow>* out) {
  const char* sql = "SELECT retraction_id, commit_id, hlc_physical_ms,"
      " hlc_logical, utc_retracted_at_ms FROM retractions"
      " ORDER BY hlc_physical_ms, hlc_logical;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    RetractionRow row;
    row.retraction_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    row.commit_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    row.hlc_physical_ms = sqlite3_column_int64(stmt, 2);
    row.hlc_logical = sqlite3_column_int64(stmt, 3);
    row.utc_retracted_at_ms = sqlite3_column_int64(stmt, 4);
    out->push_back(std::move(row));
  }
  sqlite3_finalize(stmt);
  return true;
}

// Canonical dump of all event and candidate rows; used to prove a retraction
// leaves the original facts byte-for-byte untouched.
std::string DumpFacts(sqlite3* db) {
  std::string out;
  const char* kEvents =
      "SELECT event_id, commit_id, event_format_version, schema_id,"
      " canonical_segment_input, span_start, span_end, category,"
      " preceding_text, competition_complete, final_selection_text,"
      " confirmation_source, trigger_keycode, display_rank, display_page,"
      " session_id, session_seq, hlc_physical_ms, hlc_logical,"
      " utc_confirmed_at_ms, utc_committed_at_ms FROM selection_events"
      " ORDER BY hlc_physical_ms, hlc_logical, event_id;";
  sqlite3_stmt* stmt = nullptr;
  sqlite3_prepare_v2(db, kEvents, -1, &stmt, nullptr);
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    for (int i = 0; i < sqlite3_column_count(stmt); ++i) {
      const unsigned char* text = sqlite3_column_text(stmt, i);
      out += text ? reinterpret_cast<const char*>(text) : "";
      out += "|";
    }
    out += "\n";
  }
  sqlite3_finalize(stmt);
  const char* kCandidates =
      "SELECT event_id, merge_order, text FROM selection_candidates"
      " ORDER BY event_id, merge_order;";
  stmt = nullptr;
  sqlite3_prepare_v2(db, kCandidates, -1, &stmt, nullptr);
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    for (int i = 0; i < sqlite3_column_count(stmt); ++i) {
      const unsigned char* text = sqlite3_column_text(stmt, i);
      out += text ? reinterpret_cast<const char*>(text) : "";
      out += "|";
    }
    out += "\n";
  }
  sqlite3_finalize(stmt);
  return out;
}

// Reads the persisted HLC clock from meta; used as the "current" replay point.
std::pair<int64_t, int64_t> ReadMetaClock(const fs::path& db_path) {
  sqlite3* db = nullptr;
  std::pair<int64_t, int64_t> clock = {0, 0};
  if (!OpenDbReadOnly(db_path, &db))
    return clock;
  clock.first =
      QueryCount(db, "SELECT value FROM meta WHERE key='hlc_physical_ms';");
  clock.second =
      QueryCount(db, "SELECT value FROM meta WHERE key='hlc_logical';");
  sqlite3_close(db);
  return clock;
}

// Flag used to relaunch this test binary as the second writer process of
// ConcurrentWritersBothPersistAtomically (see SpawnConcurrentWriter).
constexpr const char* kSpawnedWriterFlag = "--llm-rerank-spawned-writer";
constexpr int kConcurrentBatches = 8;

// Writer loop of the second, independent process of
// ConcurrentWritersBothPersistAtomically. Exit codes mirror the original
// fork-based test: 2 = store failed to open, 3 = a batch failed to persist,
// 0 = all batches persisted. Runs in-process and _exit()s.
void RunSpawnedWriterLoop(const fs::path& root) {
  FactStore store{root};
  if (store.Open() != FactStore::Status::kOk)
    _exit(2);
  for (int i = 0; i < kConcurrentBatches; ++i) {
    std::vector<FactStore::Event> events{MakeEvent(100 + i)};
    if (!store.PersistBatch(1700000000000LL + i, &events))
      _exit(3);
  }
  _exit(0);
}

}  // namespace

// Dispatches to the spawned-writer code path when this binary was relaunched
// with kSpawnedWriterFlag. Invoked from main() before gtest initializes;
// never returns in that case. External linkage so main() (in another test
// translation unit) can call it.
void RunSpawnedWriterMode(int argc, char** argv) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::strcmp(argv[i], kSpawnedWriterFlag) != 0)
      continue;
    RunSpawnedWriterLoop(fs::path(argv[i + 1]));
  }
}

// Launches an independent second writer by re-execing this binary in
// spawned-writer mode. posix_spawn gives the child a fresh process image;
// a bare fork() would instead inherit this process's libsystem_trace os_log
// signpost state, which SIGSEGVs inside sqlite3_open on macOS (the flake
// tracked in Habit130/squirrel#92). Returns the child pid, or -1 on failure.
pid_t SpawnConcurrentWriter(const fs::path& root) {
  char self_path[4096];
  uint32_t path_size = sizeof(self_path);
  if (_NSGetExecutablePath(self_path, &path_size) != 0)
    return -1;
  char* argv[] = {self_path, const_cast<char*>(kSpawnedWriterFlag),
                  const_cast<char*>(root.c_str()), nullptr};
  pid_t pid = -1;
  if (posix_spawn(&pid, self_path, nullptr, nullptr, argv, environ) != 0)
    return -1;
  return pid;
}

class FactStoreTest : public ::testing::Test {
 protected:
  void SetUp() override {
    tmp_dir_ = MakeTempDir();
    ASSERT_FALSE(tmp_dir_.empty());
    root_ = fs::path(tmp_dir_) / "SemanticMemory";
  }

  void TearDown() override { fs::remove_all(tmp_dir_); }

  fs::path root_;
  std::string tmp_dir_;
};

TEST_F(FactStoreTest, OpenCreatesOwnerOnlyRootAndDb) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  ASSERT_TRUE(store.is_open());
  ASSERT_EQ(FactStore::Status::kOk, store.status());

  struct stat st;
  ASSERT_EQ(0, lstat(root_.c_str(), &st));
  ASSERT_TRUE(S_ISDIR(st.st_mode));
  ASSERT_EQ(0700u, st.st_mode & 0777);
  ASSERT_EQ(getuid(), st.st_uid);

  fs::path db_path = root_ / "facts.sqlite3";
  ASSERT_EQ(0, lstat(db_path.c_str(), &st));
  ASSERT_TRUE(S_ISREG(st.st_mode));
  ASSERT_EQ(0600u, st.st_mode & 0777);
  ASSERT_EQ(getuid(), st.st_uid);

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(db_path, &db));
  ASSERT_EQ("wal", QueryText(db, "PRAGMA journal_mode;"));
  ASSERT_EQ("1", QueryText(db, "SELECT value FROM meta WHERE key='fact_schema_version';"));
  ASSERT_EQ("1", QueryText(db, "SELECT value FROM meta WHERE key='event_format_version';"));
  ASSERT_FALSE(QueryText(db, "SELECT value FROM meta WHERE key='history_id';").empty());
  ASSERT_FALSE(QueryText(db, "SELECT value FROM meta WHERE key='store_epoch';").empty());
  ASSERT_EQ(0LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, PersistBatchWritesCommitEventAndCandidates) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> events{MakeEvent(1)};
  ASSERT_TRUE(store.PersistBatch(1700000001000LL, &events));

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  ASSERT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  ASSERT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  ASSERT_EQ(3LL, QueryCount(db, "SELECT COUNT(*) FROM selection_candidates;"));
  ASSERT_EQ(1LL, QueryCount(db,
      "SELECT COUNT(*) FROM selection_events e JOIN commits c"
      " ON e.commit_id = c.commit_id WHERE c.utc_committed_at_ms = 1700000001000;"));
  // HLC was assigned inside the transaction.
  ASSERT_GT(events[0].hlc_physical_ms, 0LL);
  ASSERT_GE(events[0].hlc_logical, 0LL);
  ASSERT_EQ(events[0].hlc_physical_ms,
            QueryCount(db, "SELECT value FROM meta WHERE key='hlc_physical_ms';"));
  long long stored_logical =
      QueryCount(db, "SELECT value FROM meta WHERE key='hlc_logical';");
  ASSERT_GE(stored_logical, 0LL);
  ASSERT_EQ(events[0].hlc_logical, stored_logical);
  sqlite3_close(db);
}

TEST_F(FactStoreTest, HlcAdvancesInConfirmationOrderAndAcrossBatches) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> first{MakeEvent(1), MakeEvent(2)};
  ASSERT_TRUE(store.PersistBatch(1700000002000LL, &first));
  ASSERT_GT(first[1].hlc_physical_ms, 0LL);
  ASSERT_LT(std::make_pair(first[0].hlc_physical_ms, first[0].hlc_logical),
            std::make_pair(first[1].hlc_physical_ms, first[1].hlc_logical));

  std::vector<FactStore::Event> second{MakeEvent(3)};
  ASSERT_TRUE(store.PersistBatch(1700000003000LL, &second));
  ASSERT_LT(std::make_pair(first[1].hlc_physical_ms, first[1].hlc_logical),
            std::make_pair(second[0].hlc_physical_ms, second[0].hlc_logical));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  ASSERT_EQ(3LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  ASSERT_EQ(2LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, ReopenContinuesTheSameHistoryAndClock) {
  int64_t saved_physical = 0;
  int64_t saved_logical = 0;
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    std::vector<FactStore::Event> events{MakeEvent(1)};
    ASSERT_TRUE(store.PersistBatch(1700000004000LL, &events));
    saved_physical = events[0].hlc_physical_ms;
    saved_logical = events[0].hlc_logical;
  }
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  ASSERT_TRUE(store.is_open());
  std::vector<FactStore::Event> events{MakeEvent(2)};
  ASSERT_TRUE(store.PersistBatch(1700000005000LL, &events));
  ASSERT_LT(std::make_pair(saved_physical, saved_logical),
            std::make_pair(events[0].hlc_physical_ms, events[0].hlc_logical));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  ASSERT_EQ(2LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, WriteFailureIsReportedWithoutTouchingExistingRows) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> first{MakeEvent(1)};
  ASSERT_TRUE(store.PersistBatch(1700000006000LL, &first));
  // Break the schema out from under the open connection: any insert inside
  // the transaction must fail, roll back, and report a write fault.
  sqlite3* tamper = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((root_ / "facts.sqlite3").c_str(),
                                       &tamper, SQLITE_OPEN_READWRITE,
                                       nullptr));
  ASSERT_EQ(SQLITE_OK,
            sqlite3_exec(tamper, "DROP TABLE selection_events;", nullptr,
                         nullptr, nullptr));
  sqlite3_close(tamper);
  std::vector<FactStore::Event> second{MakeEvent(2)};
  ASSERT_FALSE(store.PersistBatch(1700000007000LL, &second));
  ASSERT_EQ(FactStore::Status::kDbWriteFailed, store.status());
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  ASSERT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, PermissiveRootStopsRecording) {
  fs::create_directories(root_);
  chmod(root_.c_str(), 0755);
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kRootPermission, store.Open());
  ASSERT_FALSE(store.is_open());
  ASSERT_FALSE(fs::exists(root_ / "facts.sqlite3"));
  EXPECT_STREQ("root_permission", FactStore::StatusCode(store.status()));
}

TEST_F(FactStoreTest, SymlinkedRootStopsRecording) {
  fs::path real_dir = fs::path(tmp_dir_) / "real";
  fs::create_directories(real_dir);
  chmod(real_dir.c_str(), 0700);
  ASSERT_EQ(0, symlink(real_dir.c_str(), root_.c_str()));
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kRootSymlink, store.Open());
  ASSERT_FALSE(store.is_open());
}

TEST_F(FactStoreTest, SymlinkedDbFileStopsRecording) {
  fs::create_directories(root_);
  chmod(root_.c_str(), 0700);
  fs::path target = fs::path(tmp_dir_) / "elsewhere";
  {
    FILE* f = fopen(target.c_str(), "w");
    ASSERT_TRUE(f);
    fclose(f);
  }
  chmod(target.c_str(), 0600);
  ASSERT_EQ(0, symlink(target.c_str(), (root_ / "facts.sqlite3").c_str()));
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kDbSymlink, store.Open());
  ASSERT_FALSE(store.is_open());
}

TEST_F(FactStoreTest, WrongDbFileModeStopsRecording) {
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  chmod((root_ / "facts.sqlite3").c_str(), 0644);
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kDbPermission, store.Open());
  ASSERT_FALSE(store.is_open());
}

TEST_F(FactStoreTest, UnsupportedSchemaVersionStopsRecording) {
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((root_ / "facts.sqlite3").c_str(),
                                       &db, SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(db, "PRAGMA journal_mode=DELETE;", nullptr,
                                    nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK,
            sqlite3_exec(db, "UPDATE meta SET value='99' WHERE"
                             " key='fact_schema_version';",
                         nullptr, nullptr, nullptr));
  sqlite3_close(db);
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kDbUnsupportedVersion, store.Open());
  ASSERT_FALSE(store.is_open());
}

TEST_F(FactStoreTest, SupportedOldSchemaNeedsMigrationInRecorderMode) {
  // With a registered test predecessor step (decision B) a below-head store
  // is supported-old: the recorder must refuse to write (kNeedsMigration,
  // recording stops) while the maintenance open may snapshot it.
  RegisterTestMigrationStep(1, 2, false, "stamp");
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((root_ / "facts.sqlite3").c_str(),
                                       &db, SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "UPDATE meta SET value='1' WHERE key='fact_schema_version';",
      nullptr, nullptr, nullptr));
  sqlite3_close(db);
  // Recorder open: supported-old -> kNeedsMigration, closed, no writing.
  {
    FactStore recorder(root_);
    ASSERT_EQ(FactStore::Status::kNeedsMigration, recorder.Open());
    ASSERT_FALSE(recorder.is_open());
    EXPECT_STREQ("needs_migration", FactStore::StatusCode(recorder.status()));
  }
  // Maintenance open: supported-old opens read-write so the migrate
  // operation can snapshot it; facts are not modified.
  {
    FactStore maintenance(root_);
    ASSERT_EQ(FactStore::Status::kOk,
              maintenance.Open(FactStore::OpenMode::kMaintenance));
    ASSERT_TRUE(maintenance.is_open());
  }
  ResetTestMigrationSteps();
}

TEST_F(FactStoreTest, SupportedOldSchemaWithoutStepFailsClosed) {
  // No test step registered: a below-head store (version 0) is a missing
  // step, never silently migratable or writable — it fails closed in both
  // modes.
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((root_ / "facts.sqlite3").c_str(),
                                       &db, SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "UPDATE meta SET value='0' WHERE key='fact_schema_version';",
      nullptr, nullptr, nullptr));
  sqlite3_close(db);
  FactStore recorder(root_);
  ASSERT_EQ(FactStore::Status::kDbUnsupportedVersion, recorder.Open());
  FactStore maintenance(root_);
  ASSERT_EQ(FactStore::Status::kDbUnsupportedVersion,
            maintenance.Open(FactStore::OpenMode::kMaintenance));
}

TEST_F(FactStoreTest, CorruptDbStopsRecording) {
  fs::create_directories(root_);
  chmod(root_.c_str(), 0700);
  {
    FILE* f = fopen((root_ / "facts.sqlite3").c_str(), "w");
    ASSERT_TRUE(f);
    fwrite("this is not a sqlite database at all, just garbage bytes", 1, 56,
           f);
    fclose(f);
  }
  chmod((root_ / "facts.sqlite3").c_str(), 0600);
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kDbCorrupt, store.Open());
  ASSERT_FALSE(store.is_open());
}

TEST_F(FactStoreTest, MissingHomeMeansNoRoot) {
  FactStore store{path()};
  ASSERT_EQ(FactStore::Status::kNoHome, store.Open());
  ASSERT_FALSE(store.is_open());
  EXPECT_STREQ("no_home", FactStore::StatusCode(store.status()));
}

TEST_F(FactStoreTest, ClockRollbackOnlyAdvancesLogicalComponent) {
  // Simulate the wall clock moving backwards between batches: the physical
  // component must stay put and only the logical component may advance.
  // A rollback happens whenever NowMs() <= the persisted clock.
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    std::vector<FactStore::Event> events{MakeEvent(1)};
    ASSERT_TRUE(store.PersistBatch(1700000001000LL, &events));
  }
  sqlite3* tamper = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((root_ / "facts.sqlite3").c_str(),
                                       &tamper, SQLITE_OPEN_READWRITE,
                                       nullptr));
  // Rewind the persisted clock far into the future so the next real-time
  // NowMs() is smaller: a clock rollback in the store's eyes.
  ASSERT_EQ(SQLITE_OK,
            sqlite3_exec(tamper, "UPDATE meta SET value = '7000000000000'"
                                 " WHERE key = 'hlc_physical_ms';",
                         nullptr, nullptr, nullptr));
  sqlite3_close(tamper);

  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> events{MakeEvent(2)};
  ASSERT_TRUE(store.PersistBatch(1700000002000LL, &events));
  // The wall clock is behind the persisted clock, so the physical component
  // is untouched; only the logical component advances.
  EXPECT_EQ(7000000000000LL, events[0].hlc_physical_ms);
  EXPECT_GT(events[0].hlc_logical, 0LL);
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(7000000000000LL,
            QueryCount(db, "SELECT value FROM meta WHERE key='hlc_physical_ms';"));
  EXPECT_EQ(events[0].hlc_logical,
            QueryCount(db, "SELECT value FROM meta WHERE key='hlc_logical';"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, CrashMidBatchLeavesNothingVisible) {
  // A crash inside a batch (a writer dies mid-transaction, never COMMITting)
  // must leave no half-visible facts: a fresh reader sees only the complete
  // earlier commit, and a new store can still open and write afterwards.
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> first{MakeEvent(1)};
  ASSERT_TRUE(store.PersistBatch(1700000001000LL, &first));

  // Simulate a second writer that dies right after BEGIN IMMEDIATE with a
  // commit row and events inserted but never COMMITted.
  sqlite3* crashed = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2((root_ / "facts.sqlite3").c_str(),
                                       &crashed, SQLITE_OPEN_READWRITE,
                                       nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(crashed, "BEGIN IMMEDIATE;", nullptr,
                                    nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK,
            sqlite3_exec(crashed,
                         "INSERT INTO commits(commit_id, utc_committed_at_ms)"
                         " VALUES('crashed', 1700000002000);",
                         nullptr, nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK,
            sqlite3_exec(crashed,
                         "INSERT INTO selection_events(event_id, commit_id,"
                         " event_format_version, schema_id,"
                         " canonical_segment_input, span_start, span_end,"
                         " category, preceding_text, competition_complete,"
                         " final_selection_text, confirmation_source,"
                         " trigger_keycode, display_rank, display_page,"
                         " session_id, session_seq, hlc_physical_ms,"
                         " hlc_logical, utc_confirmed_at_ms,"
                         " utc_committed_at_ms)"
                         " VALUES('crashed-event', 'crashed', 1, 'test',"
                         " 'shijie', 0, 6, 'word', '', 0, '时界',"
                         " 'explicit_indexed', 2, 2, 1, 'crashed-session',"
                         " 1, 1, 0, 1700000002000, 1700000002000);",
                         nullptr, nullptr, nullptr));
  // Die without COMMIT or ROLLBACK: the transaction is abandoned.
  sqlite3_close(crashed);

  // A fresh reader must see the pre-crash batch only.
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(0LL, QueryCount(db,
      "SELECT COUNT(*) FROM selection_events"
      " WHERE event_id = 'crashed-event';"));
  EXPECT_EQ(0LL, QueryCount(db,
      "SELECT COUNT(*) FROM commits WHERE commit_id = 'crashed';"));
  sqlite3_close(db);

  // The store survives the crash and keeps recording.
  FactStore store2(root_);
  ASSERT_EQ(FactStore::Status::kOk, store2.Open());
  std::vector<FactStore::Event> second{MakeEvent(2)};
  ASSERT_TRUE(store2.PersistBatch(1700000004000LL, &second));
  sqlite3* db2 = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db2));
  EXPECT_EQ(2LL, QueryCount(db2, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db2);
}

TEST_F(FactStoreTest, ConcurrentWritersBothPersistAtomically) {
  // Two independent store handles on the same facts root, writing batches
  // concurrently (a multi-process write competition). Each batch must land
  // whole or not at all, and no batch may be lost.
  // Establish the database before spawning so both writers race on writes
  // only, never on schema/meta initialization.
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    std::vector<FactStore::Event> bootstrap{MakeEvent(0)};
    ASSERT_TRUE(store.PersistBatch(1699999999000LL, &bootstrap));
  }

  // Second writer as an independent process: this binary relaunched in
  // spawned-writer mode (see RunSpawnedWriterMode / SpawnConcurrentWriter).
  pid_t pid = SpawnConcurrentWriter(root_);
  ASSERT_GE(pid, 0);
  // Parent writer on the same root, racing the child.
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    for (int i = 0; i < kConcurrentBatches; ++i) {
      std::vector<FactStore::Event> events{MakeEvent(200 + i)};
      ASSERT_TRUE(store.PersistBatch(1700000001000LL + i, &events));
    }
  }
  int exit_code = 0;
  waitpid(pid, &exit_code, 0);
  ASSERT_TRUE(WIFEXITED(exit_code));
  ASSERT_EQ(0, WEXITSTATUS(exit_code));

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  // Every batch from both writers became exactly one commit row, plus the
  // bootstrap commit.
  EXPECT_EQ(2LL * kConcurrentBatches + 1,
            QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(2LL * kConcurrentBatches + 1,
            QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  // Each event must have its full candidate set — no torn batches.
  EXPECT_EQ(3LL * (2 * kConcurrentBatches + 1),
            QueryCount(db, "SELECT COUNT(*) FROM selection_candidates;"));
  EXPECT_EQ(0LL, QueryCount(db,
      "SELECT COUNT(*) FROM commits c LEFT JOIN selection_events e"
      " ON c.commit_id = e.commit_id WHERE e.event_id IS NULL;"));
  // The clock is read only after BEGIN IMMEDIATE. Even writers that opened
  // their handles before another writer committed therefore cannot allocate a
  // stale duplicate timestamp.
  EXPECT_EQ(0LL, QueryCount(db,
      "SELECT COUNT(*) FROM (SELECT hlc_physical_ms, hlc_logical, COUNT(*) c"
      " FROM selection_events GROUP BY hlc_physical_ms, hlc_logical"
      " HAVING c > 1);"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, SharedLeaseClosesBeforeExclusiveMaintenance) {
  MaintenanceLock exclusive;
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    EXPECT_FALSE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  }
  EXPECT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
}

TEST_F(FactStoreTest, AppendRetractionKeepsOriginalFactsUntouched) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> events{MakeEvent(1), MakeEvent(2)};
  std::string commit_id;
  ASSERT_TRUE(store.PersistBatch(1700000001000LL, &events, &commit_id));
  ASSERT_FALSE(commit_id.empty());
  ASSERT_EQ(commit_id, events[0].commit_id);
  ASSERT_EQ(commit_id, events[1].commit_id);

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  const std::string before = DumpFacts(db);
  sqlite3_close(db);

  std::string retraction_id;
  ASSERT_TRUE(store.AppendRetraction(commit_id, 1700000002000LL,
                                     &retraction_id));
  ASSERT_FALSE(retraction_id.empty());
  ASSERT_NE(retraction_id, commit_id);

  db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  // The retraction is an independent appended fact: the original event and
  // candidate rows are byte-for-byte identical.
  EXPECT_EQ(before, DumpFacts(db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM retractions;"));
  std::vector<RetractionRow> retractions;
  ASSERT_TRUE(ReadRetractions(db, &retractions));
  ASSERT_EQ(1u, retractions.size());
  EXPECT_EQ(commit_id, retractions[0].commit_id);
  EXPECT_EQ(retraction_id, retractions[0].retraction_id);
  EXPECT_EQ(1700000002000LL, retractions[0].utc_retracted_at_ms);
  // The retraction's HLC is later than every event of the retracted commit.
  const auto last_event_hlc = std::make_pair(events[1].hlc_physical_ms,
                                             events[1].hlc_logical);
  EXPECT_LT(last_event_hlc, std::make_pair(retractions[0].hlc_physical_ms,
                                           retractions[0].hlc_logical));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, AppendRetractionIsIdempotent) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> events{MakeEvent(1)};
  std::string commit_id;
  ASSERT_TRUE(store.PersistBatch(1700000001000LL, &events, &commit_id));
  ASSERT_TRUE(store.AppendRetraction(commit_id, 1700000002000LL));
  ASSERT_TRUE(store.AppendRetraction(commit_id, 1700000003000LL));
  // A repeated retraction is a no-op: exactly one retraction row, no torn
  // state.
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM retractions;"));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, AppendRetractionOfUnknownCommitIsNoop) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  ASSERT_TRUE(store.AppendRetraction("no-such-commit", 1700000001000LL));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(0LL, QueryCount(db, "SELECT COUNT(*) FROM retractions;"));
  EXPECT_EQ(0LL, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, ActiveProjectionIsTemporalAndDeterministic) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  std::vector<FactStore::Event> batch_a{MakeEvent(1), MakeEvent(2)};
  std::string commit_a;
  ASSERT_TRUE(store.PersistBatch(1700000001000LL, &batch_a, &commit_a));
  std::vector<FactStore::Event> batch_b{MakeEvent(3)};
  std::string commit_b;
  ASSERT_TRUE(store.PersistBatch(1700000002000LL, &batch_b, &commit_b));

  std::string retraction_id;
  ASSERT_TRUE(store.AppendRetraction(commit_a, 1700000003000LL,
                                     &retraction_id));
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  std::vector<RetractionRow> retractions;
  ASSERT_TRUE(ReadRetractions(db, &retractions));
  ASSERT_EQ(1u, retractions.size());
  const RetractionRow& r = retractions[0];
  sqlite3_close(db);

  // Replaying at each retracted event's own HLC still sees it active: a
  // future retraction never backfills into an earlier replay point.
  std::vector<FactStore::Event> at_e1;
  ASSERT_TRUE(store.QueryActiveEventsAsOf(batch_a[0].hlc_physical_ms,
                                          batch_a[0].hlc_logical, &at_e1));
  ASSERT_EQ(1u, at_e1.size());
  EXPECT_EQ(batch_a[0].event_id, at_e1[0].event_id);

  // Replaying at the last committed point before the retraction sees the
  // whole batch active.
  const auto last_hlc = std::max(std::make_pair(batch_a[1].hlc_physical_ms,
                                                batch_a[1].hlc_logical),
                                 std::make_pair(batch_b[0].hlc_physical_ms,
                                                batch_b[0].hlc_logical));
  std::vector<FactStore::Event> before_retraction;
  ASSERT_TRUE(store.QueryActiveEventsAsOf(last_hlc.first, last_hlc.second,
                                          &before_retraction));
  ASSERT_EQ(3u, before_retraction.size());

  // Replaying at/after the retraction point sees only the surviving batch.
  std::vector<FactStore::Event> at_retraction;
  ASSERT_TRUE(store.QueryActiveEventsAsOf(r.hlc_physical_ms, r.hlc_logical,
                                          &at_retraction));
  ASSERT_EQ(1u, at_retraction.size());
  EXPECT_EQ(commit_b, at_retraction[0].commit_id);
  EXPECT_EQ(batch_b[0].event_id, at_retraction[0].event_id);
}

TEST_F(FactStoreTest, ActiveProjectionIsStableAcrossReopen) {
  std::vector<FactStore::Event> first_active;
  int64_t point_phys = 0;
  int64_t point_log = 0;
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    std::vector<FactStore::Event> batch_a{MakeEvent(1), MakeEvent(2)};
    std::string commit_a;
    ASSERT_TRUE(store.PersistBatch(1700000001000LL, &batch_a, &commit_a));
    ASSERT_TRUE(store.AppendRetraction(commit_a, 1700000002000LL));
    std::vector<FactStore::Event> batch_b{MakeEvent(3)};
    std::string commit_b;
    ASSERT_TRUE(store.PersistBatch(1700000003000LL, &batch_b, &commit_b));
    sqlite3* db = nullptr;
    ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
    point_phys =
        QueryCount(db, "SELECT value FROM meta WHERE key='hlc_physical_ms';");
    point_log =
        QueryCount(db, "SELECT value FROM meta WHERE key='hlc_logical';");
    sqlite3_close(db);
    ASSERT_TRUE(store.QueryActiveEventsAsOf(point_phys, point_log,
                                            &first_active));
  }
  ASSERT_EQ(1u, first_active.size());
  // A fresh store handle derives the same projection from the facts alone:
  // the active set is a deterministic derivation, not in-memory residue.
  FactStore reopened(root_);
  ASSERT_EQ(FactStore::Status::kOk, reopened.Open());
  std::vector<FactStore::Event> second_active;
  ASSERT_TRUE(reopened.QueryActiveEventsAsOf(point_phys, point_log,
                                             &second_active));
  ASSERT_EQ(first_active.size(), second_active.size());
  EXPECT_EQ(first_active[0].event_id, second_active[0].event_id);
  EXPECT_EQ(first_active[0].commit_id, second_active[0].commit_id);
  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  EXPECT_EQ(1LL, QueryCount(db, "SELECT COUNT(*) FROM active_events;"));
  sqlite3_close(db);
}

TEST_F(FactStoreTest, RetractionExitsWholeBatchFromAgeClockAtOnce) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  // All events share one choice problem key (schema "test", word, "shijie").
  std::vector<FactStore::Event> batch_a{MakeEvent(1), MakeEvent(2)};
  std::string commit_a;
  ASSERT_TRUE(store.PersistBatch(1700000001000LL, &batch_a, &commit_a));
  std::vector<FactStore::Event> batch_b{MakeEvent(3)};
  std::string commit_b;
  ASSERT_TRUE(store.PersistBatch(1700000002000LL, &batch_b, &commit_b));

  auto previous_event_count = [](const std::vector<FactStore::Event>& active,
                                 const FactStore::Event& target) {
    int count = 0;
    for (const auto& e : active) {
      if (std::make_pair(e.hlc_physical_ms, e.hlc_logical) >
          std::make_pair(target.hlc_physical_ms, target.hlc_logical))
        ++count;
    }
    return count;
  };

  auto point = ReadMetaClock(root_ / "facts.sqlite3");
  std::vector<FactStore::Event> active;
  ASSERT_TRUE(store.QueryActiveEventsAsOf(point.first, point.second, &active));
  ASSERT_EQ(3u, active.size());
  EXPECT_EQ(2, previous_event_count(active, batch_a[0]));  // e2 and e3 follow
  EXPECT_EQ(1, previous_event_count(active, batch_a[1]));
  EXPECT_EQ(0, previous_event_count(active, batch_b[0]));

  ASSERT_TRUE(store.AppendRetraction(commit_a, 1700000003000LL));

  point = ReadMetaClock(root_ / "facts.sqlite3");
  active.clear();
  ASSERT_TRUE(store.QueryActiveEventsAsOf(point.first, point.second, &active));
  // One retraction removed BOTH events of the batch from the active set and
  // the age clock simultaneously; the surviving event's age re-projects.
  ASSERT_EQ(1u, active.size());
  EXPECT_EQ(commit_b, active[0].commit_id);
  EXPECT_EQ(0, previous_event_count(active, batch_b[0]));
}
