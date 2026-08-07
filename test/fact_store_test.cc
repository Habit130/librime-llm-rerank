//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "fact_store.h"

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

}  // namespace

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
  const int kBatches = 8;
  // Establish the database before forking so both writers race on writes
  // only, never on schema/meta initialization.
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    std::vector<FactStore::Event> bootstrap{MakeEvent(0)};
    ASSERT_TRUE(store.PersistBatch(1699999999000LL, &bootstrap));
  }

  pid_t pid = fork();
  ASSERT_GE(pid, 0);
  int exit_code = 0;
  if (pid == 0) {
    // Child writer: its own store handle; loops, then exits cleanly.
    FactStore store(root_);
    FactStore::Status status = store.Open();
    if (status != FactStore::Status::kOk)
      _exit(2);
    for (int i = 0; i < kBatches; ++i) {
      std::vector<FactStore::Event> events{MakeEvent(100 + i)};
      if (!store.PersistBatch(1700000000000LL + i, &events))
        _exit(3);
    }
    _exit(0);
  }
  // Parent writer on the same root, racing the child.
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    for (int i = 0; i < kBatches; ++i) {
      std::vector<FactStore::Event> events{MakeEvent(200 + i)};
      ASSERT_TRUE(store.PersistBatch(1700000001000LL + i, &events));
    }
  }
  waitpid(pid, &exit_code, 0);
  ASSERT_TRUE(WIFEXITED(exit_code));
  ASSERT_EQ(0, WEXITSTATUS(exit_code));

  sqlite3* db = nullptr;
  ASSERT_TRUE(OpenDbReadOnly(root_ / "facts.sqlite3", &db));
  // Every batch from both writers became exactly one commit row, plus the
  // bootstrap commit.
  EXPECT_EQ(2LL * kBatches + 1, QueryCount(db, "SELECT COUNT(*) FROM commits;"));
  EXPECT_EQ(2LL * kBatches + 1,
            QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  // Each event must have its full candidate set — no torn batches.
  EXPECT_EQ(3LL * (2 * kBatches + 1),
            QueryCount(db, "SELECT COUNT(*) FROM selection_candidates;"));
  EXPECT_EQ(0LL, QueryCount(db,
      "SELECT COUNT(*) FROM commits c LEFT JOIN selection_events e"
      " ON c.commit_id = e.commit_id WHERE e.event_id IS NULL;"));
  sqlite3_close(db);
}
