//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Fault probes for SQLite terminal-error handling on fact validation,
// migration, restore and active-event projection (Habit130/squirrel#136).
#include <sys/stat.h>
#include <unistd.h>

#include <atomic>
#include <cstring>
#include <filesystem>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "fact_migrator.h"
#include "fact_restore.h"
#include "fact_store.h"

using namespace rime;

namespace fs = std::filesystem;

namespace {

std::string MakeTempDir() {
  char tmpl[] = "/tmp/llm_rerank_sqlite_term_XXXXXX";
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

FactStore::Event MakeEvent(int seq) {
  FactStore::Event event;
  event.event_id = "term-event-" + std::to_string(seq);
  event.schema_id = "test";
  event.canonical_segment_input = "shijie";
  event.span_start = 0;
  event.span_end = 6;
  event.category = "word";
  event.preceding_text = "上文" + std::to_string(seq);
  event.competition_complete = true;
  event.final_selection_text = "世界";
  event.confirmation_source = "explicit_indexed";
  event.display_rank = 1;
  event.display_page = 1;
  event.session_id = "session";
  event.session_seq = seq;
  event.utc_confirmed_at_ms = 1700000000000LL + seq;
  event.candidates = {{0, "世界"}, {1, "时界"}};
  return event;
}

std::string DumpCanonical(const fs::path& path) {
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK)
    return "";
  std::string out;
  out += QueryText(db, "SELECT value FROM meta WHERE key='store_epoch';");
  out += "|";
  out += QueryText(db, "SELECT value FROM meta WHERE key='history_id';");
  out += "|";
  out += QueryText(db, "SELECT value FROM meta WHERE key='fact_schema_version';");
  out += "|";
  out += std::to_string(QueryCount(db, "SELECT COUNT(*) FROM selection_events;"));
  out += "\n";
  const char* kEvents =
      "SELECT event_id, event_format_version, preceding_text,"
      " hlc_physical_ms, hlc_logical FROM selection_events"
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
  sqlite3_close(db);
  return out;
}

struct SqlProbe {
  sqlite3* db = nullptr;
  const char* needle = nullptr;
  int hits = 0;
};

int OnMatchingSql(void* udp) {
  auto* probe = static_cast<SqlProbe*>(udp);
  for (sqlite3_stmt* stmt = sqlite3_next_stmt(probe->db, nullptr); stmt;
       stmt = sqlite3_next_stmt(probe->db, stmt)) {
    const char* sql = sqlite3_sql(stmt);
    if (sql && std::strstr(sql, probe->needle)) {
      ++probe->hits;
      return 1;
    }
  }
  return 0;
}

std::atomic<bool> g_ioerr_armed{false};
sqlite3_vfs* g_root_vfs = nullptr;
sqlite3_vfs g_ioerr_vfs;
sqlite3_io_methods g_ioerr_methods;
int (*g_orig_read)(sqlite3_file*, void*, int, sqlite3_int64) = nullptr;

int IoerrRead(sqlite3_file* file, void* buf, int amt, sqlite3_int64 off) {
  if (g_ioerr_armed.load())
    return SQLITE_IOERR_READ;
  return g_orig_read(file, buf, amt, off);
}

int IoerrOpen(sqlite3_vfs* vfs, const char* name, sqlite3_file* file,
              int flags, int* out_flags) {
  int rc = g_root_vfs->xOpen(g_root_vfs, name, file, flags, out_flags);
  if (rc == SQLITE_OK && file->pMethods) {
    if (!g_orig_read) {
      g_ioerr_methods = *file->pMethods;
      g_orig_read = file->pMethods->xRead;
      g_ioerr_methods.xRead = IoerrRead;
    }
    file->pMethods = &g_ioerr_methods;
  }
  return rc;
}

void RegisterIoerrVfs() {
  if (g_root_vfs)
    return;
  g_root_vfs = sqlite3_vfs_find(nullptr);
  ASSERT_TRUE(g_root_vfs);
  g_ioerr_vfs = *g_root_vfs;
  g_ioerr_vfs.zName = "llm-ioerr";
  g_ioerr_vfs.xOpen = IoerrOpen;
  g_ioerr_vfs.pNext = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_vfs_register(&g_ioerr_vfs, 0));
}

void SetSchemaVersion(const fs::path& path, int schema_version) {
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &db,
                                       SQLITE_OPEN_READWRITE, nullptr));
  sqlite3_stmt* stmt = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_prepare_v2(
      db, "UPDATE meta SET value = ? WHERE key = ?;", -1, &stmt, nullptr));
  sqlite3_bind_text(stmt, 1, std::to_string(schema_version).c_str(), -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, "fact_schema_version", -1, SQLITE_TRANSIENT);
  ASSERT_EQ(SQLITE_DONE, sqlite3_step(stmt));
  sqlite3_finalize(stmt);
  sqlite3_close(db);
}

class FactSqliteTerminalTest : public ::testing::Test {
 protected:
  void SetUp() override {
    tmp_dir_ = MakeTempDir();
    ASSERT_FALSE(tmp_dir_.empty());
    root_ = fs::path(tmp_dir_) / "SemanticMemory";
    ResetTestMigrationSteps();
    SetMigrationStepHookForTesting(nullptr);
    SetInspectSnapshotHookForTesting(nullptr);
  }

  void TearDown() override {
    SetInspectSnapshotHookForTesting(nullptr);
    ResetTestMigrationSteps();
    SetMigrationStepHookForTesting(nullptr);
    fs::remove_all(tmp_dir_);
  }

  void Populate(int event_count) {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk,
              store.Open(FactStore::OpenMode::kMaintenance));
    for (int i = 0; i < event_count; ++i) {
      std::vector<FactStore::Event> events{MakeEvent(i)};
      ASSERT_TRUE(store.PersistBatch(1700000000000LL + i, &events));
    }
  }

  void WriteSnapshot(const fs::path& snapshot, int event_count) {
    const fs::path tmp_root =
        fs::path(tmp_dir_) / (snapshot.stem().string() + "-root");
    FactStore store(tmp_root);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
    for (int i = 0; i < event_count; ++i) {
      std::vector<FactStore::Event> events{MakeEvent(i)};
      ASSERT_TRUE(store.PersistBatch(1700000000000LL + i, &events));
    }
    FactStore::SnapshotStats stats;
    ASSERT_EQ(FactStore::Status::kOk, store.SnapshotTo(snapshot, &stats));
  }

  sqlite3* OpenWritable(const fs::path& path) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(path.c_str(), &db, SQLITE_OPEN_READWRITE, nullptr) !=
        SQLITE_OK)
      return nullptr;
    return db;
  }

  std::string tmp_dir_;
  fs::path root_;
};

TEST_F(FactSqliteTerminalTest, ForeignKeyInterruptFailsClosedOnRestore) {
  const fs::path snapshot = fs::path(tmp_dir_) / "restore.sqlite3";
  WriteSnapshot(snapshot, 3);
  const std::string before = DumpCanonical(snapshot);
  sqlite3* db = OpenWritable(snapshot);
  ASSERT_TRUE(db);
  SqlProbe probe;
  probe.db = db;
  probe.needle = "foreign_key_check";
  sqlite3_progress_handler(db, 1, OnMatchingSql, &probe);
  FactRestoreResult result = PrepareRestoreFile(db);
  sqlite3_close(db);
  EXPECT_GT(probe.hits, 0);
  EXPECT_NE(FactRestoreStatus::kOk, result.status);
  EXPECT_EQ(before, DumpCanonical(snapshot));
}

TEST_F(FactSqliteTerminalTest, ForeignKeyInterruptFailsClosedOnInspect) {
  const fs::path snapshot = fs::path(tmp_dir_) / "inspect.sqlite3";
  WriteSnapshot(snapshot, 3);
  const std::string before = DumpCanonical(snapshot);
  SqlProbe probe;
  probe.needle = "foreign_key_check";
  SetInspectSnapshotHookForTesting([&](sqlite3* db) {
    probe.db = db;
    sqlite3_progress_handler(db, 1, OnMatchingSql, &probe);
  });
  FactStore::SnapshotStats stats;
  EXPECT_EQ(FactStore::Status::kDbCorrupt,
            FactStore::InspectSnapshotFile(snapshot, &stats));
  EXPECT_GT(probe.hits, 0);
  EXPECT_EQ(before, DumpCanonical(snapshot));
}

TEST_F(FactSqliteTerminalTest, ForeignKeyInterruptFailsClosedOnMigrate) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path snapshot = fs::path(tmp_dir_) / "migrate.sqlite3";
  WriteSnapshot(snapshot, 3);
  SetSchemaVersion(snapshot, 1);
  const std::string before = DumpCanonical(snapshot);
  sqlite3* db = OpenWritable(snapshot);
  ASSERT_TRUE(db);
  SqlProbe probe;
  probe.db = db;
  probe.needle = "foreign_key_check";
  sqlite3_progress_handler(db, 1, OnMatchingSql, &probe);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  EXPECT_GT(probe.hits, 0);
  EXPECT_NE(FactMigrationStatus::kOk, result.status);
  EXPECT_NE(FactMigrationStatus::kNoMigration, result.status);
  EXPECT_EQ(before, DumpCanonical(snapshot));
}

TEST_F(FactSqliteTerminalTest, ProjectionInterruptFailsClosedOnMigrate) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path snapshot = fs::path(tmp_dir_) / "project.sqlite3";
  WriteSnapshot(snapshot, 4);
  SetSchemaVersion(snapshot, 1);
  const std::string before = DumpCanonical(snapshot);
  sqlite3* db = OpenWritable(snapshot);
  ASSERT_TRUE(db);
  SqlProbe probe;
  probe.db = db;
  probe.needle = "utc_committed_at_ms FROM selection_events";
  sqlite3_progress_handler(db, 1, OnMatchingSql, &probe);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  EXPECT_GT(probe.hits, 0);
  EXPECT_EQ(FactMigrationStatus::kDbError, result.status);
  EXPECT_EQ(before, DumpCanonical(snapshot));
}

TEST_F(FactSqliteTerminalTest, IoerrDuringForeignKeyCheckFailsClosed) {
  const fs::path snapshot = fs::path(tmp_dir_) / "ioerr.sqlite3";
  WriteSnapshot(snapshot, 3);
  const std::string before = DumpCanonical(snapshot);
  RegisterIoerrVfs();
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(snapshot.c_str(), &db,
                                       SQLITE_OPEN_READWRITE, "llm-ioerr"));
  SqlProbe probe;
  probe.db = db;
  probe.needle = "foreign_key_check";
  sqlite3_progress_handler(db, 1, [](void* udp) {
    auto* p = static_cast<SqlProbe*>(udp);
    for (sqlite3_stmt* stmt = sqlite3_next_stmt(p->db, nullptr); stmt;
         stmt = sqlite3_next_stmt(p->db, stmt)) {
      const char* sql = sqlite3_sql(stmt);
      if (sql && std::strstr(sql, p->needle)) {
        ++p->hits;
        g_ioerr_armed.store(true);
        return 0;
      }
    }
    return 0;
  }, &probe);
  FactRestoreResult result = PrepareRestoreFile(db);
  g_ioerr_armed.store(false);
  sqlite3_close(db);
  EXPECT_GT(probe.hits, 0);
  EXPECT_NE(FactRestoreStatus::kOk, result.status);
  EXPECT_EQ(before, DumpCanonical(snapshot));
}

TEST_F(FactSqliteTerminalTest, PrepareFailureFailsClosedWithoutCommit) {
  const fs::path restore_path = fs::path(tmp_dir_) / "prepare-restore.sqlite3";
  WriteSnapshot(restore_path, 2);
  const std::string restore_before = DumpCanonical(restore_path);
  sqlite3* restore_db = OpenWritable(restore_path);
  ASSERT_TRUE(restore_db);
  sqlite3_limit(restore_db, SQLITE_LIMIT_SQL_LENGTH, 8);
  FactRestoreResult restore = PrepareRestoreFile(restore_db);
  sqlite3_close(restore_db);
  EXPECT_NE(FactRestoreStatus::kOk, restore.status);
  EXPECT_EQ(restore_before, DumpCanonical(restore_path));

  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path migrate_path = fs::path(tmp_dir_) / "prepare-migrate.sqlite3";
  WriteSnapshot(migrate_path, 2);
  SetSchemaVersion(migrate_path, 1);
  const std::string migrate_before = DumpCanonical(migrate_path);
  sqlite3* migrate_db = OpenWritable(migrate_path);
  ASSERT_TRUE(migrate_db);
  sqlite3_limit(migrate_db, SQLITE_LIMIT_SQL_LENGTH, 8);
  FactMigrationResult migrate = MigrateFile(migrate_db);
  sqlite3_close(migrate_db);
  EXPECT_NE(FactMigrationStatus::kOk, migrate.status);
  EXPECT_NE(FactMigrationStatus::kNoMigration, migrate.status);
  EXPECT_EQ(migrate_before, DumpCanonical(migrate_path));
}

TEST_F(FactSqliteTerminalTest, InspectPrepareFailureFailsClosed) {
  const fs::path snapshot = fs::path(tmp_dir_) / "inspect-prepare.sqlite3";
  WriteSnapshot(snapshot, 1);
  const std::string before = DumpCanonical(snapshot);
  SetInspectSnapshotHookForTesting([](sqlite3* db) {
    sqlite3_limit(db, SQLITE_LIMIT_SQL_LENGTH, 8);
  });
  FactStore::SnapshotStats stats;
  EXPECT_NE(FactStore::Status::kOk,
            FactStore::InspectSnapshotFile(snapshot, &stats));
  EXPECT_EQ(before, DumpCanonical(snapshot));
}

TEST_F(FactSqliteTerminalTest, HealthyEmptyForeignKeyCheckSucceeds) {
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  const fs::path snapshot = fs::path(tmp_dir_) / "empty.sqlite3";
  FactStore::SnapshotStats stats;
  ASSERT_EQ(FactStore::Status::kOk, store.SnapshotTo(snapshot, &stats));
  EXPECT_EQ(0, stats.event_count);
  FactStore::SnapshotStats inspected;
  EXPECT_EQ(FactStore::Status::kOk,
            FactStore::InspectSnapshotFile(snapshot, &inspected));
  EXPECT_EQ(0, inspected.event_count);
  sqlite3* db = OpenWritable(snapshot);
  ASSERT_TRUE(db);
  FactRestoreResult result = PrepareRestoreFile(db);
  sqlite3_close(db);
  EXPECT_EQ(FactRestoreStatus::kOk, result.status);
  EXPECT_EQ(0, result.event_count);
}

TEST_F(FactSqliteTerminalTest, HealthyMigrationBackupRestoreRemainGreen) {
  const fs::path snapshot = fs::path(tmp_dir_) / "healthy.sqlite3";
  WriteSnapshot(snapshot, 2);
  FactStore::SnapshotStats inspected;
  ASSERT_EQ(FactStore::Status::kOk,
            FactStore::InspectSnapshotFile(snapshot, &inspected));
  EXPECT_EQ(2, inspected.event_count);
  sqlite3* restore_db = OpenWritable(snapshot);
  ASSERT_TRUE(restore_db);
  FactRestoreResult restore = PrepareRestoreFile(restore_db);
  sqlite3_close(restore_db);
  ASSERT_EQ(FactRestoreStatus::kOk, restore.status);
  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path migrate_path = fs::path(tmp_dir_) / "healthy-migrate.sqlite3";
  WriteSnapshot(migrate_path, 2);
  SetSchemaVersion(migrate_path, 1);
  sqlite3* migrate_db = OpenWritable(migrate_path);
  ASSERT_TRUE(migrate_db);
  FactMigrationResult migrate = MigrateFile(migrate_db);
  sqlite3_close(migrate_db);
  ASSERT_EQ(FactMigrationStatus::kOk, migrate.status);
  EXPECT_EQ(2, migrate.events_projected);
}

TEST_F(FactSqliteTerminalTest, ActiveEventsInterruptFailsClosed) {
  Populate(3);
  FactStore store(root_);
  ASSERT_EQ(FactStore::Status::kOk, store.Open());
  const std::string before = DumpCanonical(root_ / "facts.sqlite3");
  std::vector<FactStore::Event> healthy;
  ASSERT_TRUE(store.QueryActiveEventsAsOf(9999999999999LL, 0, &healthy));
  EXPECT_EQ(3u, healthy.size());
  store.InstallProgressHandlerForTesting(
      1, [](void*) { return 1; }, nullptr);
  std::vector<FactStore::Event> active;
  EXPECT_FALSE(store.QueryActiveEventsAsOf(9999999999999LL, 0, &active));
  EXPECT_TRUE(active.empty());
  EXPECT_EQ(before, DumpCanonical(root_ / "facts.sqlite3"));
}

}  // namespace
