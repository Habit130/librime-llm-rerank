//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sqlite3.h>

#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "fact_migrator.h"
#include "fact_store.h"
#include "recorder_session.h"

namespace rime {

namespace {

const char* kMetaFactSchemaVersion = "fact_schema_version";
const char* kMetaEventFormatVersion = "event_format_version";
const char* kMetaHistoryId = "history_id";
const char* kMetaStoreEpoch = "store_epoch";
const char* kMetaClockPhysicalMs = "hlc_physical_ms";
const char* kMetaClockLogical = "hlc_logical";

// One ordered migration step registered in the step table.
struct MigrationStep {
  int from = 0;
  int to = 0;
  bool changes_interpretation = false;
  string projection;  // "stamp" | "recode" | "dup_hlc"
};

// The ordered step table, keyed by the version the step migrates FROM. In
// production it is empty (head stays kFactSchemaVersion); the test seam
// registers predecessors so the supported-old -> head path is real.
std::map<int, MigrationStep> g_steps;

// Crash-injection seam (tests only): called after each completed step,
// before validation and COMMIT. Returning false aborts like a crash and
// rolls the whole chain back.
MigrationStepHook g_step_hook;

// ---------------------------------------------------------------------------
// Small sqlite helpers (mirroring fact_store.cc's file-local helpers; the
// migrator is a separate translation unit and must not depend on privates).
// ---------------------------------------------------------------------------

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
  bool ok = sqlite3_step(stmt) == SQLITE_ROW;
  if (ok) {
    const unsigned char* text = sqlite3_column_text(stmt, 0);
    *value = text ? reinterpret_cast<const char*>(text) : string();
  }
  sqlite3_finalize(stmt);
  return ok;
}

bool SetMetaText(sqlite3* db, const char* key, const string& value) {
  sqlite3_stmt* stmt = nullptr;
  const char* sql = "UPDATE meta SET value = ? WHERE key = ?;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  sqlite3_bind_text(stmt, 1, value.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, key, -1, SQLITE_TRANSIENT);
  bool ok = sqlite3_step(stmt) == SQLITE_DONE;
  sqlite3_finalize(stmt);
  return ok;
}

bool QueryCount(sqlite3* db, const std::string& sql, int64_t* count) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  bool ok = sqlite3_step(stmt) == SQLITE_ROW;
  if (ok) {
    *count = sqlite3_column_int64(stmt, 0);
  }
  sqlite3_finalize(stmt);
  return ok;
}

bool QueryQuickCheck(sqlite3* db, bool* ok) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, "PRAGMA quick_check;", -1, &stmt, nullptr) !=
      SQLITE_OK) {
    return false;
  }
  bool got_row = sqlite3_step(stmt) == SQLITE_ROW;
  if (got_row) {
    const unsigned char* text = sqlite3_column_text(stmt, 0);
    *ok = text && std::strcmp(reinterpret_cast<const char*>(text), "ok") == 0;
  } else {
    *ok = false;
  }
  sqlite3_finalize(stmt);
  return got_row;
}

// Foreign-key check must produce zero rows.
bool QueryForeignKeyCheck(sqlite3* db) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, "PRAGMA foreign_key_check;", -1, &stmt, nullptr) !=
      SQLITE_OK) {
    return false;
  }
  bool ok = sqlite3_step(stmt) != SQLITE_ROW;
  sqlite3_finalize(stmt);
  return ok;
}

bool ReadIdentity(sqlite3* db, string* store_epoch, string* history_id) {
  string value;
  if (!ReadMetaText(db, kMetaStoreEpoch, &value) || value.empty()) {
    return false;
  }
  *store_epoch = value;
  if (!ReadMetaText(db, kMetaHistoryId, &value) || value.empty()) {
    return false;
  }
  *history_id = value;
  return true;
}

// ---------------------------------------------------------------------------
// Canonical event row (the v1 / head selection_events layout)
// ---------------------------------------------------------------------------

struct CanonicalRow {
  string event_id;
  string commit_id;
  string schema_id;
  string canonical_segment_input;
  int64_t span_start = 0;
  int64_t span_end = 0;
  string category;
  string preceding_text;
  int competition_complete = 0;
  string final_selection_text;
  string confirmation_source;
  bool has_trigger_keycode = false;
  int trigger_keycode = 0;
  int display_rank = 0;
  int display_page = 0;
  string session_id;
  int session_seq = 0;
  int64_t hlc_physical_ms = 0;
  int64_t hlc_logical = 0;
  int64_t utc_confirmed_at_ms = 0;
  int64_t utc_committed_at_ms = 0;
  bool missing_required_field = false;
};

const char* kSelectHead =
    "SELECT event_id, commit_id, event_format_version, schema_id,"
    " canonical_segment_input, span_start, span_end, category,"
    " preceding_text, competition_complete, final_selection_text,"
    " confirmation_source, trigger_keycode, display_rank, display_page,"
    " session_id, session_seq, hlc_physical_ms, hlc_logical,"
    " utc_confirmed_at_ms, utc_committed_at_ms FROM selection_events"
    " ORDER BY hlc_physical_ms, hlc_logical, event_id;";

bool ColumnIsNull(sqlite3_stmt* stmt, int index) {
  return sqlite3_column_type(stmt, index) == SQLITE_NULL;
}

// Reads one row under the head layout. Every NOT NULL column that is NULL in
// the row marks the row unconvertible (SCN-58-4: a missing field blocks the
// migration; the row is never skipped). Text columns are copied only when
// non-NULL.
CanonicalRow ReadRow(sqlite3_stmt* stmt) {
  CanonicalRow row;
  if (!ColumnIsNull(stmt, 0))
    row.event_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
  else
    row.missing_required_field = true;
  if (!ColumnIsNull(stmt, 1))
    row.commit_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
  else
    row.missing_required_field = true;
  // Column 2 is event_format_version (metadata of the row, not projected
  // content).
  if (!ColumnIsNull(stmt, 3))
    row.schema_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
  else
    row.missing_required_field = true;
  if (!ColumnIsNull(stmt, 4))
    row.canonical_segment_input =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
  else
    row.missing_required_field = true;
  if (ColumnIsNull(stmt, 5))
    row.missing_required_field = true;
  row.span_start = sqlite3_column_int64(stmt, 5);
  if (ColumnIsNull(stmt, 6))
    row.missing_required_field = true;
  row.span_end = sqlite3_column_int64(stmt, 6);
  if (!ColumnIsNull(stmt, 7))
    row.category =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
  else
    row.missing_required_field = true;
  if (!ColumnIsNull(stmt, 8))
    row.preceding_text =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
  else
    row.missing_required_field = true;
  if (ColumnIsNull(stmt, 9))
    row.missing_required_field = true;
  row.competition_complete = sqlite3_column_int(stmt, 9);
  if (!ColumnIsNull(stmt, 10))
    row.final_selection_text =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
  else
    row.missing_required_field = true;
  if (!ColumnIsNull(stmt, 11))
    row.confirmation_source =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
  else
    row.missing_required_field = true;
  if (!ColumnIsNull(stmt, 12)) {
    row.has_trigger_keycode = true;
    row.trigger_keycode = sqlite3_column_int(stmt, 12);
  }
  if (ColumnIsNull(stmt, 13))
    row.missing_required_field = true;
  row.display_rank = sqlite3_column_int(stmt, 13);
  if (ColumnIsNull(stmt, 14))
    row.missing_required_field = true;
  row.display_page = sqlite3_column_int(stmt, 14);
  if (!ColumnIsNull(stmt, 15))
    row.session_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15));
  else
    row.missing_required_field = true;
  if (ColumnIsNull(stmt, 16))
    row.missing_required_field = true;
  row.session_seq = sqlite3_column_int(stmt, 16);
  if (ColumnIsNull(stmt, 17))
    row.missing_required_field = true;
  row.hlc_physical_ms = sqlite3_column_int64(stmt, 17);
  if (ColumnIsNull(stmt, 18))
    row.missing_required_field = true;
  row.hlc_logical = sqlite3_column_int64(stmt, 18);
  if (ColumnIsNull(stmt, 19))
    row.missing_required_field = true;
  row.utc_confirmed_at_ms = sqlite3_column_int64(stmt, 19);
  if (ColumnIsNull(stmt, 20))
    row.missing_required_field = true;
  row.utc_committed_at_ms = sqlite3_column_int64(stmt, 20);
  return row;
}

// ---------------------------------------------------------------------------
// UTF-8 helpers for the interpretation-changing ("recode") projection
// ---------------------------------------------------------------------------

// Returns true when `text` is well-formed UTF-8.
bool IsValidUtf8(const string& text) {
  const unsigned char* p =
      reinterpret_cast<const unsigned char*>(text.data());
  const unsigned char* end = p + text.size();
  while (p < end) {
    if (*p < 0x80) {
      ++p;
      continue;
    }
    int length = 0;
    if ((*p & 0xe0) == 0xc0)
      length = 2;
    else if ((*p & 0xf0) == 0xe0)
      length = 3;
    else if ((*p & 0xf8) == 0xf0)
      length = 4;
    else
      return false;
    if (p + length > end)
      return false;
    for (int i = 1; i < length; ++i) {
      if ((p[i] & 0xc0) != 0x80)
        return false;
    }
    if (length == 2 && p[0] < 0xc2)
      return false;  // overlong
    if (length == 3 && p[0] == 0xe0 && p[1] < 0xa0)
      return false;  // overlong
    if (length == 3 && p[0] == 0xed && p[1] >= 0xa0)
      return false;  // surrogate
    if (length == 4 && p[0] == 0xf0 && p[1] < 0x90)
      return false;  // overlong
    if (length == 4 && p[0] == 0xf4 && p[1] >= 0x90)
      return false;  // beyond U+10FFFF
    p += length;
  }
  return true;
}

// Last `max_chars` Unicode code points of `text` (canonical preceding_text
// truncation: "截取最后 64 个 Unicode 字符"). Input must already be valid
// UTF-8; bytes of a multi-byte character are never split.
string TruncateToLastUnicodeChars(const string& text, size_t max_chars) {
  if (max_chars == 0)
    return "";
  const unsigned char* p =
      reinterpret_cast<const unsigned char*>(text.data());
  const unsigned char* end = p + text.size();
  // Walk forward, remembering the byte offset of every character, then take
  // the substring that starts at the `max_chars`-th character from the end.
  std::vector<size_t> char_starts;
  size_t offset = 0;
  while (p < end) {
    char_starts.push_back(offset);
    if (*p < 0x80) {
      ++p;
      offset += 1;
      continue;
    }
    int length = 0;
    if ((*p & 0xe0) == 0xc0)
      length = 2;
    else if ((*p & 0xf0) == 0xe0)
      length = 3;
    else
      length = 4;
    p += length;
    offset += static_cast<size_t>(length);
  }
  if (char_starts.size() <= max_chars)
    return text;
  return text.substr(char_starts[char_starts.size() - max_chars]);
}

// ---------------------------------------------------------------------------
// Projection
// ---------------------------------------------------------------------------

// Deterministically projects one old-format row to the canonical form.
// Returns false (unconvertible) when a required field is missing or the
// row cannot be deterministically converted. A false return blocks the
// migration; the row is never skipped.
bool ProjectRow(CanonicalRow* row, const string& projection) {
  if (row->missing_required_field)
    return false;
  if (projection == "recode") {
    if (!IsValidUtf8(row->preceding_text))
      return false;
    row->preceding_text = TruncateToLastUnicodeChars(row->preceding_text, 64);
  } else if (projection == "dup_hlc") {
    // Test-only: make every row share one HLC so pre-commit validation
    // fails and proves rollback.
    row->hlc_physical_ms = 1;
    row->hlc_logical = 1;
  }
  return true;
}

bool UpdateRow(sqlite3* db, const CanonicalRow& row) {
  const char* kUpdate =
      "UPDATE selection_events SET event_format_version = ?1,"
      " schema_id = ?2, canonical_segment_input = ?3, span_start = ?4,"
      " span_end = ?5, category = ?6, preceding_text = ?7,"
      " competition_complete = ?8, final_selection_text = ?9,"
      " confirmation_source = ?10, trigger_keycode = ?11,"
      " display_rank = ?12, display_page = ?13, session_id = ?14,"
      " session_seq = ?15, hlc_physical_ms = ?16, hlc_logical = ?17,"
      " utc_confirmed_at_ms = ?18, utc_committed_at_ms = ?19"
      " WHERE event_id = ?20;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, kUpdate, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  sqlite3_bind_int(stmt, 1, kEventFormatVersion);
  sqlite3_bind_text(stmt, 2, row.schema_id.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 3, row.canonical_segment_input.c_str(), -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_int64(stmt, 4, row.span_start);
  sqlite3_bind_int64(stmt, 5, row.span_end);
  sqlite3_bind_text(stmt, 6, row.category.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 7, row.preceding_text.c_str(), -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_int(stmt, 8, row.competition_complete);
  sqlite3_bind_text(stmt, 9, row.final_selection_text.c_str(), -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 10, row.confirmation_source.c_str(), -1,
                    SQLITE_TRANSIENT);
  if (row.has_trigger_keycode) {
    sqlite3_bind_int(stmt, 11, row.trigger_keycode);
  } else {
    sqlite3_bind_null(stmt, 11);
  }
  sqlite3_bind_int(stmt, 12, row.display_rank);
  sqlite3_bind_int(stmt, 13, row.display_page);
  sqlite3_bind_text(stmt, 14, row.session_id.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_int(stmt, 15, row.session_seq);
  sqlite3_bind_int64(stmt, 16, row.hlc_physical_ms);
  sqlite3_bind_int64(stmt, 17, row.hlc_logical);
  sqlite3_bind_int64(stmt, 18, row.utc_confirmed_at_ms);
  sqlite3_bind_int64(stmt, 19, row.utc_committed_at_ms);
  sqlite3_bind_text(stmt, 20, row.event_id.c_str(), -1, SQLITE_TRANSIENT);
  bool ok = sqlite3_step(stmt) == SQLITE_DONE;
  sqlite3_finalize(stmt);
  return ok;
}

// The canonical active-events view (the v1 store creates it at Open(); a
// migrated store must expose the same view).
const char* kCreateActiveEventsView =
    "CREATE VIEW IF NOT EXISTS active_events AS"
    " SELECT e.event_id, e.commit_id, e.event_format_version, e.schema_id,"
    "  e.canonical_segment_input, e.span_start, e.span_end, e.category,"
    "  e.preceding_text, e.competition_complete, e.final_selection_text,"
    "  e.confirmation_source, e.trigger_keycode, e.display_rank,"
    "  e.display_page, e.session_id, e.session_seq, e.hlc_physical_ms,"
    "  e.hlc_logical, e.utc_confirmed_at_ms, e.utc_committed_at_ms"
    " FROM selection_events e"
    " WHERE NOT EXISTS (SELECT 1 FROM retractions r"
    "                   WHERE r.commit_id = e.commit_id);";

// Applies one step: reads every row under the head layout, projects it
// deterministically to the canonical form and rewrites the rows by event_id,
// then ensures the active-events view exists. Runs inside the chain
// transaction; any unconvertible row aborts with kProjectionFailed so the
// whole chain rolls back.
FactMigrationStatus ApplyStep(sqlite3* db, const MigrationStep& step) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, kSelectHead, -1, &stmt, nullptr) != SQLITE_OK)
    return FactMigrationStatus::kDbError;
  std::vector<CanonicalRow> rows;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    CanonicalRow row = ReadRow(stmt);
    if (!ProjectRow(&row, step.projection)) {
      sqlite3_finalize(stmt);
      return FactMigrationStatus::kProjectionFailed;
    }
    rows.push_back(std::move(row));
  }
  sqlite3_finalize(stmt);
  if (Exec(db, kCreateActiveEventsView) != SQLITE_OK)
    return FactMigrationStatus::kDbError;
  for (const CanonicalRow& row : rows) {
    if (!UpdateRow(db, row))
      return FactMigrationStatus::kDbError;
  }
  return FactMigrationStatus::kOk;
}

// ---------------------------------------------------------------------------
// Pre-commit validation (SCN-58-7): runs inside the chain transaction, so a
// failure rolls the whole migration back and leaves the file unchanged.
// ---------------------------------------------------------------------------

bool ValidateMigratedStore(sqlite3* db) {
  bool quick_ok = false;
  if (!QueryQuickCheck(db, &quick_ok) || !quick_ok)
    return false;
  if (!QueryForeignKeyCheck(db))
    return false;
  int64_t count = -1;
  // Every row must carry the canonical event format.
  if (!QueryCount(db, "SELECT COUNT(*) FROM selection_events WHERE"
                      " event_format_version <> " +
                          std::to_string(kEventFormatVersion) + ";",
                  &count) ||
      count != 0)
    return false;
  // Every event must reference a real commit and carry at least one
  // materialized candidate (a canonical selection event always has its
  // competition set).
  if (!QueryCount(db, "SELECT COUNT(*) FROM selection_events e WHERE"
                      " NOT EXISTS (SELECT 1 FROM commits c"
                      "             WHERE c.commit_id = e.commit_id);",
                  &count) ||
      count != 0)
    return false;
  if (!QueryCount(db, "SELECT COUNT(*) FROM selection_events e WHERE"
                      " NOT EXISTS (SELECT 1 FROM selection_candidates sc"
                      "             WHERE sc.event_id = e.event_id);",
                  &count) ||
      count != 0)
    return false;
  // Every commit must carry at least one event.
  if (!QueryCount(db, "SELECT COUNT(*) FROM commits c WHERE"
                      " NOT EXISTS (SELECT 1 FROM selection_events e"
                      "             WHERE e.commit_id = c.commit_id);",
                  &count) ||
      count != 0)
    return false;
  // No two events may share one HLC pair.
  if (!QueryCount(db, "SELECT COUNT(*) FROM (SELECT hlc_physical_ms,"
                      " hlc_logical FROM selection_events"
                      " GROUP BY hlc_physical_ms, hlc_logical"
                      " HAVING COUNT(*) > 1);",
                  &count) ||
      count != 0)
    return false;
  // HLC total order: rows must be strictly increasing when ordered by
  // (physical, logical, event_id) — the same order the plugin assigns.
  {
    sqlite3_stmt* stmt = nullptr;
    const char* kOrdered =
        "SELECT hlc_physical_ms, hlc_logical FROM selection_events"
        " ORDER BY hlc_physical_ms, hlc_logical, event_id;";
    if (sqlite3_prepare_v2(db, kOrdered, -1, &stmt, nullptr) != SQLITE_OK)
      return false;
    bool previous = false;
    int64_t prev_physical = 0;
    int64_t prev_logical = 0;
    bool ordered = true;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      int64_t physical = sqlite3_column_int64(stmt, 0);
      int64_t logical = sqlite3_column_int64(stmt, 1);
      if (previous &&
          !(std::make_pair(physical, logical) >
            std::make_pair(prev_physical, prev_logical))) {
        ordered = false;
        break;
      }
      prev_physical = physical;
      prev_logical = logical;
      previous = true;
    }
    sqlite3_finalize(stmt);
    if (!ordered)
      return false;
  }
  // Durable clock never falls below the highest event HLC.
  {
    string value;
    int64_t clock_physical = 0;
    int64_t clock_logical = 0;
    if (!ReadMetaText(db, kMetaClockPhysicalMs, &value) ||
        !ParseInt64(value, &clock_physical) || clock_physical < 0 ||
        !ReadMetaText(db, kMetaClockLogical, &value) ||
        !ParseInt64(value, &clock_logical) || clock_logical < 0)
      return false;
    sqlite3_stmt* stmt = nullptr;
    const char* kMaxEventHlc =
        "SELECT hlc_physical_ms, hlc_logical FROM selection_events"
        " ORDER BY hlc_physical_ms DESC, hlc_logical DESC LIMIT 1;";
    if (sqlite3_prepare_v2(db, kMaxEventHlc, -1, &stmt, nullptr) != SQLITE_OK)
      return false;
    bool has_event = sqlite3_step(stmt) == SQLITE_ROW;
    int64_t event_physical = -1;
    int64_t event_logical = -1;
    if (has_event) {
      event_physical = sqlite3_column_int64(stmt, 0);
      event_logical = sqlite3_column_int64(stmt, 1);
    }
    sqlite3_finalize(stmt);
    if (has_event &&
        !(std::make_pair(event_physical, event_logical) <=
          std::make_pair(clock_physical, clock_logical)))
      return false;
  }
  // Identity rows must be present and non-empty.
  {
    string store_epoch;
    string history_id;
    if (!ReadIdentity(db, &store_epoch, &history_id))
      return false;
  }
  return true;
}

}  // namespace

const char* FactMigrationStatusCode(FactMigrationStatus status) {
  switch (status) {
    case FactMigrationStatus::kOk:
      return "migrated";
    case FactMigrationStatus::kNoMigration:
      return "no_migration";
    case FactMigrationStatus::kUnsupportedVersion:
      return "unsupported_version";
    case FactMigrationStatus::kMissingStep:
      return "missing_step";
    case FactMigrationStatus::kProjectionFailed:
      return "projection_failed";
    case FactMigrationStatus::kValidationFailed:
      return "validation_failed";
    case FactMigrationStatus::kDbError:
      return "db_error";
  }
  return "unknown";
}

const char* FactMigrationStatusMessage(FactMigrationStatus status) {
  switch (status) {
    case FactMigrationStatus::kOk:
      return "fact store migrated to the current schema";
    case FactMigrationStatus::kNoMigration:
      return "fact store is already at the current schema";
    case FactMigrationStatus::kUnsupportedVersion:
      return "fact store schema is newer than this program supports";
    case FactMigrationStatus::kMissingStep:
      return "no migration step covers the store's schema version";
    case FactMigrationStatus::kProjectionFailed:
      return "an event could not be deterministically projected; the "
             "migration is blocked and no event was skipped";
    case FactMigrationStatus::kValidationFailed:
      return "pre-commit validation failed; the migration was rolled back";
    case FactMigrationStatus::kDbError:
      return "the fact store database could not be migrated";
  }
  return "unknown migration fault";
}

int CurrentSchemaHead() {
  int head = kFactSchemaVersion;
  for (const auto& entry : g_steps) {
    head = std::max(head, entry.second.to);
  }
  return head;
}

SchemaDispositionCode DispositionFor(int version) {
  const int head = CurrentSchemaHead();
  if (version == head)
    return SchemaDispositionCode::kCurrent;
  if (version > head || version < 0)
    return SchemaDispositionCode::kUnsupported;
  int current = version;
  while (current < head) {
    auto it = g_steps.find(current);
    if (it == g_steps.end())
      return SchemaDispositionCode::kMissingStep;
    current = it->second.to;
  }
  return SchemaDispositionCode::kNeedsMigration;
}

bool IsMigratable(int version) {
  return DispositionFor(version) == SchemaDispositionCode::kNeedsMigration;
}

void RegisterTestMigrationStep(int from_version, int to_version,
                               bool changes_interpretation,
                               const char* projection) {
  if (to_version != from_version + 1 || from_version < 0 || !projection)
    return;
  MigrationStep step;
  step.from = from_version;
  step.to = to_version;
  step.changes_interpretation = changes_interpretation;
  step.projection = projection;
  g_steps[from_version] = std::move(step);
}

void ResetTestMigrationSteps() {
  g_steps.clear();
  g_step_hook = MigrationStepHook();
}

void SetMigrationStepHookForTesting(MigrationStepHook hook) {
  g_step_hook = std::move(hook);
}

FactMigrationResult MigrateFile(sqlite3* db) {
  FactMigrationResult result;
  if (!db)
    return result;
  string version_text;
  int64_t version = -1;
  if (!ReadMetaText(db, kMetaFactSchemaVersion, &version_text) ||
      !ParseInt64(version_text, &version) || version < 0) {
    return result;  // kDbError: not a readable fact store
  }
  result.from_version = static_cast<int>(version);
  const int head = CurrentSchemaHead();
  if (version == head) {
    result.status = FactMigrationStatus::kNoMigration;
    result.to_version = head;
    int64_t total = 0;
    if (!QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &total))
      return result;
    result.events_preserved = total;
    if (!ReadIdentity(db, &result.store_epoch, &result.history_id))
      return result;
    return result;
  }
  if (version > head) {
    result.status = FactMigrationStatus::kUnsupportedVersion;
    return result;
  }
  // Build the ordered forward-only chain from the store's version to head.
  std::vector<MigrationStep> chain;
  int current = static_cast<int>(version);
  while (current < head) {
    auto it = g_steps.find(current);
    if (it == g_steps.end()) {
      result.status = FactMigrationStatus::kMissingStep;
      return result;
    }
    chain.push_back(it->second);
    current = it->second.to;
  }

  int64_t total_events = 0;
  if (!QueryCount(db, "SELECT COUNT(*) FROM selection_events;",
                  &total_events)) {
    return result;
  }

  // ONE SQLite transaction covers the whole ordered chain (pinned decision):
  // a crash at any point leaves the complete old schema; only COMMIT exposes
  // the complete new schema.
  if (Exec(db, "BEGIN IMMEDIATE;") != SQLITE_OK)
    return result;

  bool ok = true;
  bool epoch_changed = false;
  for (size_t index = 0; index < chain.size() && ok; ++index) {
    FactMigrationStatus step_status = ApplyStep(db, chain[index]);
    if (step_status != FactMigrationStatus::kOk) {
      ok = false;
      result.status = step_status;
      break;
    }
    if (chain[index].changes_interpretation)
      epoch_changed = true;
    if (ok && g_step_hook && !g_step_hook(static_cast<int>(index + 1))) {
      // Simulated crash (test seam): abort exactly like a process kill after
      // this step; the transaction is never committed.
      ok = false;
      result.status = FactMigrationStatus::kDbError;
      break;
    }
  }

  // Version metadata is only rewritten after every step applied; a changing
  // chain generates ONE new store_epoch (history_id is preserved).
  if (ok && epoch_changed) {
    if (!SetMetaText(db, kMetaStoreEpoch, RandomUuid()))
      ok = false;
  }
  if (ok) {
    if (!SetMetaText(db, kMetaFactSchemaVersion, std::to_string(head)) ||
        !SetMetaText(db, kMetaEventFormatVersion,
                     std::to_string(kEventFormatVersion))) {
      ok = false;
    }
  }
  if (ok && !ValidateMigratedStore(db)) {
    ok = false;
    result.status = FactMigrationStatus::kValidationFailed;
  }
  if (ok && Exec(db, "COMMIT;") != SQLITE_OK) {
    ok = false;
    result.status = FactMigrationStatus::kDbError;
  }
  if (!ok) {
    Exec(db, "ROLLBACK;");
    result.epoch_changed = false;
    return result;
  }

  result.status = FactMigrationStatus::kOk;
  result.to_version = head;
  result.epoch_changed = epoch_changed;
  // Every row of the store passed through a deterministic projection during
  // the chain; none were skipped and none existed in an unprojected form.
  result.events_projected = total_events;
  result.events_preserved = 0;
  if (!ReadIdentity(db, &result.store_epoch, &result.history_id))
    result.status = FactMigrationStatus::kDbError;
  return result;
}

}  // namespace rime
