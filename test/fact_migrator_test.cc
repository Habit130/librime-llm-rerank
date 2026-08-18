//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Deterministic tests for the fact schema migrator (Habit130/squirrel#58).
//
// The production step table is empty (decision B: head stays 1); these tests
// register the test predecessor v1 -> v2 through the seam and prove the full
// supported-old -> head path: projection, the preserve/new-epoch rules, the
// pre-commit validation matrix, the fail-closed dispositions (too new,
// missing step, unconvertible row) and the crash boundaries (the whole chain
// runs in one SQLite transaction, so a crash at any point leaves the
// complete old schema and only COMMIT exposes the complete new schema).
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <sqlite3.h>

#include "fact_migrator.h"
#include "fact_store.h"
#include "recorder_session.h"

using namespace rime;

namespace fs = std::filesystem;

namespace {

std::string MakeTempDir() {
  char tmpl[] = "/tmp/llm_rerank_migrate_XXXXXX";
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

struct FixtureStore {
  std::string store_epoch;
  std::string history_id;
  std::vector<std::string> event_ids;
};

// Creates a standalone v1 fact store file (a snapshot-like single file) at
// `path` with `event_count` events carrying distinct HLCs and one candidate
// each, and writes its durable epoch/history into `fixture`. The store is
// created by the real FactStore in a throwaway root, then checkpointed and
// the single file is moved to `path` — the same publication shape the
// migrate operation migrates.
void MakeV1Store(const fs::path& path, int event_count,
                 FixtureStore* fixture) {
  fs::path tmp = fs::path(MakeTempDir());
  fs::path root = tmp / "SemanticMemory";
  {
    FactStore store(root);
    EXPECT_EQ(FactStore::Status::kOk, store.Open());
    int64_t physical = 0;
    int64_t logical = 0;
    std::string epoch;
    std::string history;
    ASSERT_EQ(FactStore::Status::kOk,
              store.ReadStoreIdentity(&physical, &logical, &epoch, &history));
    fixture->store_epoch = epoch;
    fixture->history_id = history;
    for (int i = 0; i < event_count; ++i) {
      std::vector<FactStore::Event> events(1);
      events[0].event_id = "migrate-event-" + std::to_string(i);
      events[0].schema_id = "test";
      events[0].canonical_segment_input = "shijie";
      events[0].span_start = 0;
      events[0].span_end = 6;
      events[0].category = "word";
      events[0].preceding_text = "上文" + std::to_string(i);
      events[0].competition_complete = true;
      events[0].final_selection_text = "世界";
      events[0].confirmation_source = "explicit_current";
      events[0].display_rank = 1;
      events[0].display_page = 1;
      events[0].session_id = "session";
      events[0].session_seq = i;
      events[0].utc_confirmed_at_ms = 1700000000000LL + i;
      events[0].candidates = {{0, "世界"}, {1, "时界"}};
      ASSERT_TRUE(store.PersistBatch(1700000000000LL + i, &events));
      fixture->event_ids.push_back(events[0].event_id);
    }
    ASSERT_EQ(FactStore::Status::kOk, store.CheckpointTruncate());
  }
  fs::rename(root / "facts.sqlite3", path);
  fs::remove_all(tmp);
}

// Flips the durable schema version of a standalone file to `version`
// (the migrate operation targets a file whose meta says a supported-old
// version while the physical layout is the current one — the test seam's
// projection path).
void SetSchemaVersion(const fs::path& path, int schema_version,
                      int event_format_version) {
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
  sqlite3_reset(stmt);
  sqlite3_bind_text(stmt, 1, std::to_string(event_format_version).c_str(),
                    -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, "event_format_version", -1, SQLITE_TRANSIENT);
  ASSERT_EQ(SQLITE_DONE, sqlite3_step(stmt));
  sqlite3_finalize(stmt);
  sqlite3_close(db);
}

// Canonical dump of all event rows; used to prove rollback leaves the facts
// unchanged.
std::string DumpEvents(sqlite3* db) {
  std::string out;
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
  return out;
}

// Rebuilds selection_events WITHOUT the NOT NULL constraints (CREATE TABLE
// AS SELECT copies no constraints) and NULLs one required column of one row,
// so the migrator's canonical projection sees a genuinely missing field —
// the only way a required field can be absent in a real v1 store (foreign or
// corrupted rows). The active view is recreated afterwards so the file still
// parses as a v1 store.
void RebuildEventsWithoutNotNullAndNullField(const fs::path& path,
                                             const std::string& event_id) {
  sqlite3* db = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &db,
                                       SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(db, "DROP VIEW IF EXISTS active_events;",
                                    nullptr, nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "CREATE TABLE selection_events_v2 AS"
          " SELECT event_id, commit_id, event_format_version, schema_id,"
          " canonical_segment_input, span_start, span_end, category,"
          " preceding_text, competition_complete, final_selection_text,"
          " confirmation_source, trigger_keycode, display_rank, display_page,"
          " session_id, session_seq, hlc_physical_ms, hlc_logical,"
          " utc_confirmed_at_ms, utc_committed_at_ms"
          " FROM selection_events;", nullptr, nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(db, "DROP TABLE selection_events;",
                                    nullptr, nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "ALTER TABLE selection_events_v2 RENAME TO selection_events;",
      nullptr, nullptr, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      db, "CREATE VIEW IF NOT EXISTS active_events AS"
          " SELECT e.event_id, e.commit_id, e.event_format_version,"
          " e.schema_id, e.canonical_segment_input, e.span_start, e.span_end,"
          " e.category, e.preceding_text, e.competition_complete,"
          " e.final_selection_text, e.confirmation_source, e.trigger_keycode,"
          " e.display_rank, e.display_page, e.session_id, e.session_seq,"
          " e.hlc_physical_ms, e.hlc_logical, e.utc_confirmed_at_ms,"
          " e.utc_committed_at_ms FROM selection_events e"
          " WHERE NOT EXISTS (SELECT 1 FROM retractions r"
          "                   WHERE r.commit_id = e.commit_id);",
      nullptr, nullptr, nullptr));
  std::string sql = "UPDATE selection_events SET utc_confirmed_at_ms = NULL"
                    " WHERE event_id = '" + event_id + "';";
  ASSERT_EQ(SQLITE_OK,
            sqlite3_exec(db, sql.c_str(), nullptr, nullptr, nullptr));
  sqlite3_close(db);
}

class FactMigratorTest : public ::testing::Test {
 protected:
  void SetUp() override {
    tmp_dir_ = MakeTempDir();
    ASSERT_FALSE(tmp_dir_.empty());
    ResetTestMigrationSteps();
    SetMigrationStepHookForTesting(nullptr);
  }

  void TearDown() override {
    ResetTestMigrationSteps();
    SetMigrationStepHookForTesting(nullptr);
    fs::remove_all(tmp_dir_);
  }

  fs::path DbPath(const std::string& name) const {
    return fs::path(tmp_dir_) / name;
  }

  std::string tmp_dir_;
};

// Opens a standalone file read-write for migration.
sqlite3* OpenWritable(const fs::path& path) {
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(path.c_str(), &db, SQLITE_OPEN_READWRITE, nullptr) !=
      SQLITE_OK) {
    return nullptr;
  }
  return db;
}

// ---------------------------------------------------------------------------
// Disposition (SCN-58-5/6, AC58-5)
// ---------------------------------------------------------------------------

TEST_F(FactMigratorTest, CurrentVersionNeedsNoMigration) {
  // Production head stays 1 with no registered steps.
  EXPECT_EQ(1, CurrentSchemaHead());
  EXPECT_EQ(SchemaDispositionCode::kCurrent, DispositionFor(1));
  EXPECT_FALSE(IsMigratable(1));
  // A version below head with no registered step is a missing step, not
  // silently migratable.
  EXPECT_EQ(SchemaDispositionCode::kMissingStep, DispositionFor(0));
  EXPECT_FALSE(IsMigratable(0));
}

TEST_F(FactMigratorTest, RegisteredStepMakesOldVersionMigratable) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  EXPECT_EQ(2, CurrentSchemaHead());
  EXPECT_EQ(SchemaDispositionCode::kNeedsMigration, DispositionFor(1));
  EXPECT_TRUE(IsMigratable(1));
  EXPECT_EQ(SchemaDispositionCode::kCurrent, DispositionFor(2));
  EXPECT_FALSE(IsMigratable(2));
}

TEST_F(FactMigratorTest, TooNewVersionFailsClosed) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  EXPECT_EQ(SchemaDispositionCode::kUnsupported, DispositionFor(3));
  EXPECT_FALSE(IsMigratable(3));
  EXPECT_EQ(SchemaDispositionCode::kUnsupported, DispositionFor(99));
}

TEST_F(FactMigratorTest, GapInStepTableIsMissingStep) {
  RegisterTestMigrationStep(2, 3, false, "stamp");
  // Version 1 is below head 3 but no step covers 1 -> 2.
  EXPECT_EQ(SchemaDispositionCode::kMissingStep, DispositionFor(1));
  EXPECT_FALSE(IsMigratable(1));
}

// ---------------------------------------------------------------------------
// Interpretation-preserving step (SCN-58-2, AC58-2/3)
// ---------------------------------------------------------------------------

TEST_F(FactMigratorTest, PreservingStepKeepsHistoryAndEpoch) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path path = DbPath("preserve.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 3, &fixture);
  SetSchemaVersion(path, 1, 1);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);

  ASSERT_EQ(FactMigrationStatus::kOk, result.status);
  EXPECT_EQ(1, result.from_version);
  EXPECT_EQ(2, result.to_version);
  EXPECT_FALSE(result.epoch_changed);
  EXPECT_EQ(3, result.events_projected);
  // The interpretation did not change: history_id AND store_epoch are
  // preserved.
  EXPECT_EQ(fixture.history_id, result.history_id);
  EXPECT_EQ(fixture.store_epoch, result.store_epoch);
  // The file is at the head version and every row is canonical.
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("2", QueryText(check,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_EQ("1", QueryText(check,
      "SELECT value FROM meta WHERE key='event_format_version';"));
  EXPECT_EQ(0LL, QueryCount(check,
      "SELECT COUNT(*) FROM selection_events WHERE"
      " event_format_version <> 1;"));
  sqlite3_close(check);
}

TEST_F(FactMigratorTest, PreservingStepKeepsEventContent) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path path = DbPath("preserve-content.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 1, &fixture);
  SetSchemaVersion(path, 1, 1);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  sqlite3* before = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &before,
                                       SQLITE_OPEN_READONLY, nullptr));
  const std::string before_dump = DumpEvents(before);
  sqlite3_close(before);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kOk, result.status);
  sqlite3* after = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &after,
                                       SQLITE_OPEN_READONLY, nullptr));
  // The "stamp" projection rewrites the format column only; the event
  // content and HLCs are unchanged.
  EXPECT_EQ(before_dump, DumpEvents(after));
  sqlite3_close(after);
}

// ---------------------------------------------------------------------------
// Interpretation-changing step (SCN-58-3, AC58-3)
// ---------------------------------------------------------------------------

TEST_F(FactMigratorTest, ChangingStepGeneratesNewEpochKeepsHistory) {
  RegisterTestMigrationStep(1, 2, true, "recode");
  const fs::path path = DbPath("changing.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 2, &fixture);
  SetSchemaVersion(path, 1, 1);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);

  ASSERT_EQ(FactMigrationStatus::kOk, result.status);
  EXPECT_TRUE(result.epoch_changed);
  // history_id is preserved; store_epoch is a fresh one.
  EXPECT_EQ(fixture.history_id, result.history_id);
  EXPECT_NE(fixture.store_epoch, result.store_epoch);
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_NE(fixture.store_epoch,
            QueryText(check, "SELECT value FROM meta WHERE key='store_epoch';"));
  EXPECT_EQ(fixture.history_id,
            QueryText(check, "SELECT value FROM meta WHERE key='history_id';"));
  sqlite3_close(check);
}

TEST_F(FactMigratorTest, ChangingStepCanonicalizesPrecedingText) {
  RegisterTestMigrationStep(1, 2, true, "recode");
  const fs::path path = DbPath("recode.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 1, &fixture);
  SetSchemaVersion(path, 1, 1);
  // Make the single event's preceding_text longer than 64 Unicode chars
  // (65 ASCII chars here; "recode" truncates to the last 64).
  sqlite3* seed = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &seed,
                                       SQLITE_OPEN_READWRITE, nullptr));
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      seed, "UPDATE selection_events SET preceding_text ="
            " '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789X'"
            " WHERE event_id = 'migrate-event-0';",
      nullptr, nullptr, nullptr));
  sqlite3_close(seed);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kOk, result.status);
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  std::string text = QueryText(check,
      "SELECT preceding_text FROM selection_events"
      " WHERE event_id = 'migrate-event-0';");
  sqlite3_close(check);
  EXPECT_EQ(64u, text.size());
  EXPECT_EQ('X', text.back());
}

TEST_F(FactMigratorTest, ChangingStepRejectsInvalidUtf8) {
  RegisterTestMigrationStep(1, 2, true, "recode");
  const fs::path path = DbPath("bad-utf8.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 1, &fixture);
  SetSchemaVersion(path, 1, 1);
  sqlite3* seed = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &seed,
                                       SQLITE_OPEN_READWRITE, nullptr));
  // Inject invalid UTF-8 (a bare continuation byte) into preceding_text.
  ASSERT_EQ(SQLITE_OK, sqlite3_exec(
      seed, "UPDATE selection_events SET preceding_text ="
            " CAST(x'FF' AS TEXT) WHERE event_id = 'migrate-event-0';",
      nullptr, nullptr, nullptr));
  sqlite3_close(seed);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  // Unconvertible row -> blocked; nothing was changed.
  ASSERT_EQ(FactMigrationStatus::kProjectionFailed, result.status);
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("1", QueryText(check,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  sqlite3_close(check);
}

// ---------------------------------------------------------------------------
// Unconvertible row (SCN-58-4, AC58-4)
// ---------------------------------------------------------------------------

TEST_F(FactMigratorTest, MissingFieldBlocksMigrationAndSkipsNothing) {
  RegisterTestMigrationStep(1, 2, true, "recode");
  const fs::path path = DbPath("missing-field.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 2, &fixture);
  SetSchemaVersion(path, 1, 1);
  RebuildEventsWithoutNotNullAndNullField(path, "migrate-event-0");
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kProjectionFailed, result.status);
  // The whole chain rolled back: the file is unchanged at v1 and BOTH events
  // are still present (the blocky row was not skipped, the other was not
  // migrated).
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("1", QueryText(check,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_EQ(2LL, QueryCount(check, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(check);
}

// ---------------------------------------------------------------------------
// Validation failure before commit (SCN-58-7, AC58-2/5)
// ---------------------------------------------------------------------------

TEST_F(FactMigratorTest, ValidationFailureRollsBackWholeChain) {
  RegisterTestMigrationStep(1, 2, false, "dup_hlc");
  const fs::path path = DbPath("validation-fail.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 3, &fixture);
  SetSchemaVersion(path, 1, 1);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kValidationFailed, result.status);
  // The chain rolled back: the file is still v1 with the original rows.
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("1", QueryText(check,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_EQ(3LL, QueryCount(check, "SELECT COUNT(*) FROM selection_events;"));
  EXPECT_EQ(0LL, QueryCount(check,
      "SELECT COUNT(*) FROM selection_events WHERE"
      " event_format_version <> 1;"));
  sqlite3_close(check);
}

// ---------------------------------------------------------------------------
// Crash boundaries (SCN-58-10, AC58-7)
// ---------------------------------------------------------------------------

TEST_F(FactMigratorTest, CrashBeforeCommitLeavesCompleteOldSchema) {
  RegisterTestMigrationStep(1, 2, true, "recode");
  const fs::path path = DbPath("crash.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 2, &fixture);
  SetSchemaVersion(path, 1, 1);
  // Simulate a crash right after the step applied but before COMMIT: the
  // whole transaction rolls back and the file stays at the complete old
  // schema with the old epoch and unchanged rows.
  SetMigrationStepHookForTesting(
      [](int completed_steps) { return completed_steps < 1; });
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_NE(FactMigrationStatus::kOk, result.status);
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("1", QueryText(check,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_EQ(fixture.store_epoch,
            QueryText(check, "SELECT value FROM meta WHERE key='store_epoch';"));
  EXPECT_EQ(2LL, QueryCount(check, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(check);

  // A retry after the "crash" completes the migration: the file then shows
  // the complete new schema.
  SetMigrationStepHookForTesting(nullptr);
  sqlite3* retry = OpenWritable(path);
  ASSERT_TRUE(retry);
  FactMigrationResult retried = MigrateFile(retry);
  sqlite3_close(retry);
  ASSERT_EQ(FactMigrationStatus::kOk, retried.status);
  sqlite3* after = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &after,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("2", QueryText(after,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  EXPECT_NE(fixture.store_epoch,
            QueryText(after, "SELECT value FROM meta WHERE key='store_epoch';"));
  EXPECT_EQ(2LL, QueryCount(after, "SELECT COUNT(*) FROM selection_events;"));
  sqlite3_close(after);
}

TEST_F(FactMigratorTest, NoMigrationForAlreadyCurrentFile) {
  const fs::path path = DbPath("current.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 1, &fixture);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kNoMigration, result.status);
  EXPECT_EQ(1, result.from_version);
  EXPECT_EQ(1, result.to_version);
  EXPECT_EQ(fixture.store_epoch, result.store_epoch);
  EXPECT_EQ(fixture.history_id, result.history_id);
}

TEST_F(FactMigratorTest, TooNewFileFailsClosed) {
  RegisterTestMigrationStep(1, 2, false, "stamp");
  const fs::path path = DbPath("too-new.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 1, &fixture);
  SetSchemaVersion(path, 99, 1);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kUnsupportedVersion, result.status);
  sqlite3* check = nullptr;
  ASSERT_EQ(SQLITE_OK, sqlite3_open_v2(path.c_str(), &check,
                                       SQLITE_OPEN_READONLY, nullptr));
  EXPECT_EQ("99", QueryText(check,
      "SELECT value FROM meta WHERE key='fact_schema_version';"));
  sqlite3_close(check);
}

TEST_F(FactMigratorTest, MissingStepFailsClosed) {
  // No step registered (head 1) and the file claims a supported-old
  // event_format_version below the canonical one: the store is neither
  // current nor migratable.
  RegisterTestMigrationStep(2, 3, false, "stamp");  // gap at 1
  const fs::path path = DbPath("missing-step.sqlite3");
  FixtureStore fixture;
  MakeV1Store(path, 1, &fixture);
  SetSchemaVersion(path, 1, 1);
  sqlite3* db = OpenWritable(path);
  ASSERT_TRUE(db);
  FactMigrationResult result = MigrateFile(db);
  sqlite3_close(db);
  ASSERT_EQ(FactMigrationStatus::kMissingStep, result.status);
}

}  // namespace
