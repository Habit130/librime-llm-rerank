//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Whole-store restore epoch minting (Habit130/squirrel#56). See
// fact_restore.h for the contract. The implementation mirrors the small
// sqlite helpers of fact_migrator.cc (this is a separate translation unit
// and must not depend on file-local privates) and reuses the migrator's
// disposition table for schema classification.
#include <sqlite3.h>

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <string>

#include "fact_restore.h"
#include "fact_migrator.h"
#include "recorder_session.h"
#include "sqlite_step.h"

namespace rime {

namespace {

const char* kMetaFactSchemaVersion = "fact_schema_version";
const char* kMetaEventFormatVersion = "event_format_version";
const char* kMetaHistoryId = "history_id";
const char* kMetaStoreEpoch = "store_epoch";
const char* kMetaClockPhysicalMs = "hlc_physical_ms";
const char* kMetaClockLogical = "hlc_logical";

int Exec(sqlite3* db, const char* sql) {
  char* error = nullptr;
  int rc = sqlite3_exec(db, sql, nullptr, nullptr, &error);
  if (error) {
    sqlite3_free(error);
  }
  return rc;
}

bool ParseInt64(const string& text, int64_t* value) {
  if (text.empty())
    return false;
  errno = 0;
  char* end = nullptr;
  long long parsed = std::strtoll(text.c_str(), &end, 10);
  if (errno == ERANGE || end != text.c_str() + text.size())
    return false;
  *value = static_cast<int64_t>(parsed);
  return true;
}

bool ReadMetaText(sqlite3* db, const char* key, string* value) {
  sqlite3_stmt* stmt = nullptr;
  const char* sql = "SELECT value FROM meta WHERE key = ?;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  sqlite3_bind_text(stmt, 1, key, -1, SQLITE_TRANSIENT);
  int rc = sqlite3_step(stmt);
  if (rc != SQLITE_ROW) {
    sqlite3_finalize(stmt);
    return false;
  }
  const unsigned char* text = sqlite3_column_text(stmt, 0);
  *value = text ? reinterpret_cast<const char*>(text) : string();
  return sqlite3_finalize(stmt) == SQLITE_OK;
}

bool SetMetaText(sqlite3* db, const char* key, const string& value) {
  sqlite3_stmt* stmt = nullptr;
  const char* sql = "UPDATE meta SET value = ? WHERE key = ?;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  sqlite3_bind_text(stmt, 1, value.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, key, -1, SQLITE_TRANSIENT);
  int rc = sqlite3_step(stmt);
  return SqliteFinishDone(stmt, rc);
}

bool QueryCount(sqlite3* db, const char* sql, int64_t* count) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  int rc = sqlite3_step(stmt);
  if (rc != SQLITE_ROW) {
    sqlite3_finalize(stmt);
    return false;
  }
  *count = sqlite3_column_int64(stmt, 0);
  return sqlite3_finalize(stmt) == SQLITE_OK;
}

bool QueryQuickCheck(sqlite3* db, bool* ok) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, "PRAGMA quick_check;", -1, &stmt, nullptr) !=
      SQLITE_OK) {
    return false;
  }
  int rc = sqlite3_step(stmt);
  if (rc != SQLITE_ROW) {
    *ok = false;
    sqlite3_finalize(stmt);
    return false;
  }
  const unsigned char* text = sqlite3_column_text(stmt, 0);
  *ok = text && std::strcmp(reinterpret_cast<const char*>(text), "ok") == 0;
  return sqlite3_finalize(stmt) == SQLITE_OK;
}

// Foreign-key check must produce zero rows. Only SQLITE_DONE is success;
// SQLITE_INTERRUPT and other terminal errors fail closed.
bool QueryForeignKeyCheck(sqlite3* db) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, "PRAGMA foreign_key_check;", -1, &stmt, nullptr) !=
      SQLITE_OK) {
    return false;
  }
  int rc = sqlite3_step(stmt);
  if (rc == SQLITE_ROW) {
    sqlite3_finalize(stmt);
    return false;
  }
  return SqliteFinishDone(stmt, rc);
}

bool ReadIdentity(sqlite3* db, string* store_epoch, string* history_id) {
  string value;
  if (!ReadMetaText(db, kMetaStoreEpoch, &value) || value.empty())
    return false;
  *store_epoch = value;
  if (!ReadMetaText(db, kMetaHistoryId, &value) || value.empty())
    return false;
  *history_id = value;
  return true;
}

// Re-reads the durable identity and counts after the mint so the report is
// the single source of truth for the restore operation (Python never
// re-derives fact semantics).
bool ReadRestoreStats(sqlite3* db, FactRestoreResult* result) {
  string value;
  int64_t schema_version = -1;
  int64_t event_format_version = -1;
  int64_t clock_physical = -1;
  int64_t clock_logical = -1;
  if (!ReadMetaText(db, kMetaFactSchemaVersion, &value) ||
      !ParseInt64(value, &schema_version) || schema_version < 0 ||
      !ReadMetaText(db, kMetaEventFormatVersion, &value) ||
      !ParseInt64(value, &event_format_version) || event_format_version < 0 ||
      !ReadMetaText(db, kMetaClockPhysicalMs, &value) ||
      !ParseInt64(value, &clock_physical) || clock_physical < 0 ||
      !ReadMetaText(db, kMetaClockLogical, &value) ||
      !ParseInt64(value, &clock_logical) || clock_logical < 0) {
    return false;
  }
  result->fact_schema_version = static_cast<int>(schema_version);
  result->event_format_version = static_cast<int>(event_format_version);
  result->hlc_physical_ms = clock_physical;
  result->hlc_logical = clock_logical;
  if (!QueryCount(db, "SELECT COUNT(*) FROM commits;",
                  &result->commit_count) ||
      !QueryCount(db, "SELECT COUNT(*) FROM selection_events;",
                  &result->event_count) ||
      !QueryCount(db, "SELECT COUNT(*) FROM selection_candidates;",
                  &result->candidate_count) ||
      !QueryCount(db, "SELECT COUNT(*) FROM retractions;",
                  &result->retraction_count)) {
    return false;
  }
  return true;
}

}  // namespace

const char* FactRestoreStatusCode(FactRestoreStatus status) {
  switch (status) {
    case FactRestoreStatus::kOk:
      return "prepared";
    case FactRestoreStatus::kNeedsMigration:
      return "needs_migration";
    case FactRestoreStatus::kUnsupportedVersion:
      return "unsupported_version";
    case FactRestoreStatus::kValidationFailed:
      return "validation_failed";
    case FactRestoreStatus::kDbError:
      return "db_error";
  }
  return "unknown";
}

const char* FactRestoreStatusMessage(FactRestoreStatus status) {
  switch (status) {
    case FactRestoreStatus::kOk:
      return "restore staging file prepared with a new store epoch";
    case FactRestoreStatus::kNeedsMigration:
      return "the backup store is supported-old; migrate the staging copy "
             "before preparing the restore";
    case FactRestoreStatus::kUnsupportedVersion:
      return "the backup store is newer than this program supports (or a "
             "migration step is missing)";
    case FactRestoreStatus::kValidationFailed:
      return "the backup store failed closed validation";
    case FactRestoreStatus::kDbError:
      return "the restore staging file could not be prepared";
  }
  return "unknown restore fault";
}

FactRestoreResult PrepareRestoreFile(sqlite3* db) {
  FactRestoreResult result;
  if (!db)
    return result;
  // The seam operates on ONE standalone staging file (a copy of an
  // extracted backup member), never on a live locked root. A live store is
  // WAL-mode with sidecars; refusing any WAL-dependent file guarantees a
  // prepare-restore can never mint the live root's own database in place.
  {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, "PRAGMA journal_mode;", -1, &stmt, nullptr) !=
        SQLITE_OK) {
      return result;
    }
    int rc = sqlite3_step(stmt);
    const unsigned char* text = rc == SQLITE_ROW ? sqlite3_column_text(stmt, 0)
                                                 : nullptr;
    string mode = text ? reinterpret_cast<const char*>(text) : string();
    if (sqlite3_finalize(stmt) != SQLITE_OK)
      rc = SQLITE_ERROR;
    if (rc != SQLITE_ROW || mode == "wal") {
      result.status = FactRestoreStatus::kValidationFailed;
      return result;
    }
  }
  // The whole mint runs inside ONE SQLite transaction: a crash before COMMIT
  // leaves the file at the old epoch with all facts intact.
  if (Exec(db, "BEGIN IMMEDIATE;") != SQLITE_OK)
    return result;

  bool ok = true;
  // 1. The file must be a readable, current-head store. The migrator's
  //    disposition table is the single source of schema truth (the restore
  //    operation migrates supported-old staging copies BEFORE this seam).
  {
    string value;
    int64_t schema_version = -1;
    int64_t event_format_version = -1;
    if (!ReadMetaText(db, kMetaFactSchemaVersion, &value) ||
        !ParseInt64(value, &schema_version) || schema_version < 0) {
      ok = false;
    }
    if (ok && (!ReadMetaText(db, kMetaEventFormatVersion, &value) ||
               !ParseInt64(value, &event_format_version) ||
               event_format_version < 0)) {
      ok = false;
    }
    if (ok && event_format_version > kEventFormatVersion) {
      // Too-new event format fails closed in every mode.
      result.status = FactRestoreStatus::kUnsupportedVersion;
      ok = false;
    }
    if (ok) {
      SchemaDispositionCode disposition =
          DispositionFor(static_cast<int>(schema_version));
      if (disposition == SchemaDispositionCode::kNeedsMigration) {
        result.status = FactRestoreStatus::kNeedsMigration;
        ok = false;
      } else if (disposition == SchemaDispositionCode::kUnsupported ||
                 disposition == SchemaDispositionCode::kMissingStep) {
        result.status = FactRestoreStatus::kUnsupportedVersion;
        ok = false;
      }
    }
  }
  // 2. Identity and clock must be readable before any mint.
  if (ok && !ReadIdentity(db, &result.previous_store_epoch,
                          &result.history_id)) {
    ok = false;
  }
  // 3. Mint ONE new random store_epoch; history_id is preserved.
  if (ok && !SetMetaText(db, kMetaStoreEpoch, RandomUuid())) {
    ok = false;
  }
  // 4. Re-validate the prepared file before COMMIT: the mint must never
  //    break integrity, foreign keys, the identity rows or the clock.
  if (ok && (!QueryQuickCheck(db, &ok) || !QueryForeignKeyCheck(db))) {
    // QueryQuickCheck already cleared ok on failure; keep a stable code.
    result.status = FactRestoreStatus::kValidationFailed;
    ok = false;
  }
  if (ok) {
    string epoch;
    string history;
    if (!ReadIdentity(db, &epoch, &history)) {
      ok = false;
    } else {
      result.store_epoch = epoch;
      if (epoch.empty() || epoch == result.previous_store_epoch) {
        // The new epoch must differ from the backup's own epoch (a random
        // collision is an impossible sequence or a broken helper).
        ok = false;
      }
    }
  }
  if (ok && Exec(db, "COMMIT;") != SQLITE_OK) {
    ok = false;
    result.status = FactRestoreStatus::kDbError;
  }
  if (!ok) {
    if (result.status == FactRestoreStatus::kOk)
      result.status = FactRestoreStatus::kValidationFailed;
    Exec(db, "ROLLBACK;");
    return result;
  }

  if (!ReadRestoreStats(db, &result)) {
    result.status = FactRestoreStatus::kValidationFailed;
    return result;
  }
  result.status = FactRestoreStatus::kOk;
  return result;
}

}  // namespace rime
