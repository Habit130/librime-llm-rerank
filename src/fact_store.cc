//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <cstdlib>
#include <cstring>

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
const char* kMetaCreatedAtMs = "created_at_ms";

const char* kDbFileName = "facts.sqlite3";

// Upper bound on waiting for a concurrent writer's short transaction. A
// timeout is a recording gap, never a blocked text commit.
constexpr int kBusyTimeoutMs = 2000;

constexpr mode_t kDirMode = 0700;
constexpr mode_t kFileMode = 0600;

bool IsExactMode(const struct stat& st, mode_t mode) {
  return (st.st_mode & 0777) == mode;
}

// Creates each missing ancestor of `dir` with mode 0700, bottom-up, so the
// facts root can be established under a freshly provisioned HOME without
// touching any pre-existing directory.
bool CreateAncestors(const path& dir) {
  vector<path> missing;
  struct stat st;
  path current = dir;
  while (!current.empty() && lstat(current.c_str(), &st) != 0 &&
         errno == ENOENT) {
    missing.push_back(current);
    current = current.parent_path();
  }
  for (auto it = missing.rbegin(); it != missing.rend(); ++it) {
    if (mkdir(it->c_str(), kDirMode) != 0 && errno != EEXIST)
      return false;
  }
  return true;
}

}  // namespace

path FactStore::DefaultRootDir() {
  const char* home = getenv("HOME");
  if (!home)
    return path();
  return path(home) / "Library" / "Application Support" / "Squirrel" /
         "SemanticMemory";
}

FactStore::FactStore(const path& root_dir) : root_(root_dir) {}

FactStore::~FactStore() {
  if (db_) {
    sqlite3_close(db_);
    db_ = nullptr;
  }
}

FactStore::Status FactStore::VerifyRoot() {
  if (root_.empty())
    return Status::kNoHome;
  struct stat st;
  if (lstat(root_.c_str(), &st) != 0) {
    if (errno != ENOENT)
      return Status::kRootNotDirectory;
    if (!CreateAncestors(root_))
      return Status::kRootCreateFailed;
    if (lstat(root_.c_str(), &st) != 0)
      return Status::kRootCreateFailed;
  }
  if (S_ISLNK(st.st_mode))
    return Status::kRootSymlink;
  if (!S_ISDIR(st.st_mode))
    return Status::kRootNotDirectory;
  if (st.st_uid != getuid())
    return Status::kRootOwner;
  if (!IsExactMode(st, kDirMode))
    return Status::kRootPermission;
  return Status::kOk;
}

FactStore::Status FactStore::VerifyDbFile() {
  path db_path = root_ / kDbFileName;
  struct stat st;
  if (lstat(db_path.c_str(), &st) != 0) {
    if (errno == ENOENT)
      return Status::kOk;
    return Status::kDbNotRegular;
  }
  if (S_ISLNK(st.st_mode))
    return Status::kDbSymlink;
  if (!S_ISREG(st.st_mode))
    return Status::kDbNotRegular;
  if (st.st_uid != getuid())
    return Status::kDbOwner;
  if (!IsExactMode(st, kFileMode))
    return Status::kDbPermission;
  return Status::kOk;
}

bool FactStore::EnsureFileModes() {
  path db_path = root_ / kDbFileName;
  bool ok = chmod(db_path.c_str(), kFileMode) == 0;
  for (const char* suffix : {"-wal", "-shm"}) {
    path sidecar = root_ / (string(kDbFileName) + suffix);
    if (access(sidecar.c_str(), F_OK) == 0) {
      ok = chmod(sidecar.c_str(), kFileMode) == 0 && ok;
    }
  }
  return ok;
}

namespace {

// Runs one statement that produces no rows (or whose rows are irrelevant),
// returning the sqlite result code.
int Exec(sqlite3* db, const char* sql) {
  char* error = nullptr;
  int rc = sqlite3_exec(db, sql, nullptr, nullptr, &error);
  if (error) {
    sqlite3_free(error);
  }
  return rc;
}

bool QueryBoolValue(sqlite3* db, const char* sql, bool* value) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  bool ok = sqlite3_step(stmt) == SQLITE_ROW;
  if (ok) {
    *value = sqlite3_column_int(stmt, 0) != 0;
  }
  sqlite3_finalize(stmt);
  return ok;
}

// quick_check yields one text row ("ok" on success); any other outcome is a
// corruption signal.
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

}  // namespace

FactStore::Status FactStore::InitializeMeta() {
  int64_t now = NowMs();
  const std::pair<const char*, string> entries[] = {
      {kMetaFactSchemaVersion, std::to_string(kFactSchemaVersion)},
      {kMetaEventFormatVersion, std::to_string(kEventFormatVersion)},
      {kMetaHistoryId, RandomUuid()},
      {kMetaStoreEpoch, RandomUuid()},
      {kMetaClockPhysicalMs, std::to_string(now)},
      {kMetaClockLogical, "0"},
      {kMetaCreatedAtMs, std::to_string(now)},
  };
  for (const auto& entry : entries) {
    string sql = "INSERT INTO meta(key, value) VALUES(?, ?);";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK)
      return Status::kDbWriteFailed;
    sqlite3_bind_text(stmt, 1, entry.first, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, entry.second.c_str(), -1, SQLITE_TRANSIENT);
    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    if (!ok)
      return Status::kDbWriteFailed;
  }
  clock_physical_ms_ = now;
  clock_logical_ = 0;
  meta_initialized_ = true;
  return Status::kOk;
}

namespace {

// Reads a single meta row; returns false when the key is missing or has a
// non-text value.
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

bool ParseInt64(const string& text, int64_t* value) {
  if (text.empty())
    return false;
  char* end = nullptr;
  long long parsed = strtoll(text.c_str(), &end, 10);
  if (end != text.c_str() + text.size())
    return false;
  *value = static_cast<int64_t>(parsed);
  return true;
}

}  // namespace

FactStore::Status FactStore::ValidateMeta() {
  string value;
  if (!ReadMetaText(db_, kMetaFactSchemaVersion, &value) ||
      value != std::to_string(kFactSchemaVersion)) {
    return Status::kDbUnsupportedVersion;
  }
  if (!ReadMetaText(db_, kMetaEventFormatVersion, &value) ||
      value != std::to_string(kEventFormatVersion)) {
    return Status::kDbUnsupportedVersion;
  }
  if (!ReadMetaText(db_, kMetaHistoryId, &value) || value.empty() ||
      !ReadMetaText(db_, kMetaStoreEpoch, &value) || value.empty()) {
    return Status::kDbClockInvalid;
  }
  if (!ReadMetaText(db_, kMetaClockPhysicalMs, &value) ||
      !ParseInt64(value, &clock_physical_ms_) ||
      !ReadMetaText(db_, kMetaClockLogical, &value) ||
      !ParseInt64(value, &clock_logical_) || clock_physical_ms_ < 0 ||
      clock_logical_ < 0) {
    return Status::kDbClockInvalid;
  }
  meta_initialized_ = true;
  return Status::kOk;
}

FactStore::Status FactStore::Open() {
  status_ = Status::kOk;
  if (db_) {
    sqlite3_close(db_);
    db_ = nullptr;
  }
  if (Status root_status = VerifyRoot(); root_status != Status::kOk) {
    status_ = root_status;
    return status_;
  }
  if (Status file_status = VerifyDbFile(); file_status != Status::kOk) {
    status_ = file_status;
    return status_;
  }
  path db_path = root_ / kDbFileName;
  if (sqlite3_open_v2(db_path.c_str(), &db_,
                      SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE,
                      nullptr) != SQLITE_OK) {
    status_ = Status::kDbOpenFailed;
    if (db_) {
      sqlite3_close(db_);
      db_ = nullptr;
    }
    return status_;
  }
  sqlite3_busy_timeout(db_, kBusyTimeoutMs);

  bool quick_check_ok = false;
  if (!QueryQuickCheck(db_, &quick_check_ok) || !quick_check_ok) {
    status_ = Status::kDbCorrupt;
    sqlite3_close(db_);
    db_ = nullptr;
    return status_;
  }
  if (Exec(db_, "PRAGMA journal_mode=WAL;") != SQLITE_OK ||
      Exec(db_, "PRAGMA synchronous=FULL;") != SQLITE_OK ||
      Exec(db_, "PRAGMA foreign_keys=ON;") != SQLITE_OK) {
    status_ = Status::kDbOpenFailed;
    sqlite3_close(db_);
    db_ = nullptr;
    return status_;
  }

  const char* kSchemaV1 =
      "CREATE TABLE IF NOT EXISTS meta ("
      " key TEXT PRIMARY KEY NOT NULL,"
      " value TEXT NOT NULL"
      ");"
      "CREATE TABLE IF NOT EXISTS commits ("
      " commit_id TEXT PRIMARY KEY NOT NULL,"
      " utc_committed_at_ms INTEGER NOT NULL"
      ");"
      "CREATE TABLE IF NOT EXISTS selection_events ("
      " event_id TEXT PRIMARY KEY NOT NULL,"
      " commit_id TEXT NOT NULL REFERENCES commits(commit_id),"
      " event_format_version INTEGER NOT NULL,"
      " schema_id TEXT NOT NULL,"
      " canonical_segment_input TEXT NOT NULL,"
      " span_start INTEGER NOT NULL,"
      " span_end INTEGER NOT NULL,"
      " category TEXT NOT NULL,"
      " preceding_text TEXT NOT NULL,"
      " competition_complete INTEGER NOT NULL,"
      " final_selection_text TEXT NOT NULL,"
      " confirmation_source TEXT NOT NULL,"
      " trigger_keycode INTEGER,"
      " display_rank INTEGER NOT NULL,"
      " display_page INTEGER NOT NULL,"
      " session_id TEXT NOT NULL,"
      " session_seq INTEGER NOT NULL,"
      " hlc_physical_ms INTEGER NOT NULL,"
      " hlc_logical INTEGER NOT NULL,"
      " utc_confirmed_at_ms INTEGER NOT NULL,"
      " utc_committed_at_ms INTEGER NOT NULL"
      ");"
      "CREATE INDEX IF NOT EXISTS idx_selection_events_commit_id"
      " ON selection_events(commit_id);"
      "CREATE TABLE IF NOT EXISTS selection_candidates ("
      " event_id TEXT NOT NULL REFERENCES selection_events(event_id),"
      " merge_order INTEGER NOT NULL,"
      " text TEXT NOT NULL,"
      " PRIMARY KEY (event_id, merge_order)"
      ");";
  if (Exec(db_, kSchemaV1) != SQLITE_OK) {
    status_ = Status::kDbOpenFailed;
    sqlite3_close(db_);
    db_ = nullptr;
    return status_;
  }

  bool has_meta = false;
  if (!QueryBoolValue(db_, "SELECT EXISTS(SELECT 1 FROM meta);", &has_meta)) {
    status_ = Status::kDbClockInvalid;
    sqlite3_close(db_);
    db_ = nullptr;
    return status_;
  }
  Status meta_status =
      has_meta ? ValidateMeta() : InitializeMeta();
  if (meta_status != Status::kOk) {
    status_ = meta_status;
    sqlite3_close(db_);
    db_ = nullptr;
    return status_;
  }
  if (!EnsureFileModes()) {
    status_ = Status::kDbPermission;
    sqlite3_close(db_);
    db_ = nullptr;
    return status_;
  }
  return status_;
}

bool FactStore::PersistBatch(int64_t utc_committed_at_ms,
                             vector<Event>* events) {
  if (!db_ || !events || events->empty()) {
    status_ = Status::kDbWriteFailed;
    return false;
  }
  if (Exec(db_, "BEGIN IMMEDIATE;") != SQLITE_OK) {
    status_ = Status::kDbWriteFailed;
    return false;
  }
  bool ok = true;
  const char* insert_commit =
      "INSERT INTO commits(commit_id, utc_committed_at_ms) VALUES(?, ?);";
  const char* insert_event =
      "INSERT INTO selection_events(event_id, commit_id, event_format_version,"
      " schema_id, canonical_segment_input, span_start, span_end, category,"
      " preceding_text, competition_complete, final_selection_text,"
      " confirmation_source, trigger_keycode, display_rank, display_page,"
      " session_id, session_seq, hlc_physical_ms, hlc_logical,"
      " utc_confirmed_at_ms, utc_committed_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,"
      "?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21);";
  const char* insert_candidate =
      "INSERT INTO selection_candidates(event_id, merge_order, text)"
      " VALUES(?, ?, ?);";
  sqlite3_stmt* commit_stmt = nullptr;
  sqlite3_stmt* event_stmt = nullptr;
  sqlite3_stmt* candidate_stmt = nullptr;
  if (sqlite3_prepare_v2(db_, insert_commit, -1, &commit_stmt, nullptr) !=
          SQLITE_OK ||
      sqlite3_prepare_v2(db_, insert_event, -1, &event_stmt, nullptr) !=
          SQLITE_OK ||
      sqlite3_prepare_v2(db_, insert_candidate, -1, &candidate_stmt, nullptr) !=
          SQLITE_OK) {
    ok = false;
  }
  string commit_id = RandomUuid();
  if (ok) {
    sqlite3_bind_text(commit_stmt, 1, commit_id.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(commit_stmt, 2, utc_committed_at_ms);
    ok = sqlite3_step(commit_stmt) == SQLITE_DONE;
  }
  if (ok) {
    int64_t physical = clock_physical_ms_;
    int64_t logical = clock_logical_;
    for (Event& event : *events) {
      int64_t now = NowMs();
      if (now > physical) {
        physical = now;
        logical = 0;
      } else {
        logical += 1;
      }
      event.hlc_physical_ms = physical;
      event.hlc_logical = logical;

      sqlite3_reset(event_stmt);
      sqlite3_bind_text(event_stmt, 1, event.event_id.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_text(event_stmt, 2, commit_id.c_str(), -1, SQLITE_TRANSIENT);
      sqlite3_bind_int(event_stmt, 3, kEventFormatVersion);
      sqlite3_bind_text(event_stmt, 4, event.schema_id.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_text(event_stmt, 5, event.canonical_segment_input.c_str(),
                        -1, SQLITE_TRANSIENT);
      sqlite3_bind_int64(event_stmt, 6, static_cast<int64_t>(event.span_start));
      sqlite3_bind_int64(event_stmt, 7, static_cast<int64_t>(event.span_end));
      sqlite3_bind_text(event_stmt, 8, event.category.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_text(event_stmt, 9, event.preceding_text.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_int(event_stmt, 10, event.competition_complete ? 1 : 0);
      sqlite3_bind_text(event_stmt, 11, event.final_selection_text.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_text(event_stmt, 12, event.confirmation_source.c_str(), -1,
                        SQLITE_TRANSIENT);
      if (event.trigger_keycode >= 0) {
        sqlite3_bind_int(event_stmt, 13, event.trigger_keycode);
      } else {
        sqlite3_bind_null(event_stmt, 13);
      }
      sqlite3_bind_int(event_stmt, 14, event.display_rank);
      sqlite3_bind_int(event_stmt, 15, event.display_page);
      sqlite3_bind_text(event_stmt, 16, event.session_id.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_int(event_stmt, 17, event.session_seq);
      sqlite3_bind_int64(event_stmt, 18, event.hlc_physical_ms);
      sqlite3_bind_int64(event_stmt, 19, event.hlc_logical);
      sqlite3_bind_int64(event_stmt, 20, event.utc_confirmed_at_ms);
      sqlite3_bind_int64(event_stmt, 21, utc_committed_at_ms);
      if (sqlite3_step(event_stmt) != SQLITE_DONE) {
        ok = false;
        break;
      }
      for (const auto& candidate : event.candidates) {
        sqlite3_reset(candidate_stmt);
        sqlite3_bind_text(candidate_stmt, 1, event.event_id.c_str(), -1,
                          SQLITE_TRANSIENT);
        sqlite3_bind_int64(candidate_stmt, 2, candidate.first);
        sqlite3_bind_text(candidate_stmt, 3, candidate.second.c_str(), -1,
                          SQLITE_TRANSIENT);
        if (sqlite3_step(candidate_stmt) != SQLITE_DONE) {
          ok = false;
          break;
        }
      }
      if (!ok)
        break;
    }
    if (ok) {
      clock_physical_ms_ = physical;
      clock_logical_ = logical;
      const char* update_clock =
          "UPDATE meta SET value = ? WHERE key = ?;";
      sqlite3_stmt* clock_stmt = nullptr;
      if (sqlite3_prepare_v2(db_, update_clock, -1, &clock_stmt, nullptr) ==
          SQLITE_OK) {
        sqlite3_bind_text(clock_stmt, 1, std::to_string(physical).c_str(), -1,
                          SQLITE_TRANSIENT);
        sqlite3_bind_text(clock_stmt, 2, kMetaClockPhysicalMs, -1,
                          SQLITE_TRANSIENT);
        if (sqlite3_step(clock_stmt) != SQLITE_DONE) {
          ok = false;
        }
        sqlite3_reset(clock_stmt);
        sqlite3_bind_text(clock_stmt, 1, std::to_string(logical).c_str(), -1,
                          SQLITE_TRANSIENT);
        sqlite3_bind_text(clock_stmt, 2, kMetaClockLogical, -1,
                          SQLITE_TRANSIENT);
        if (ok && sqlite3_step(clock_stmt) != SQLITE_DONE) {
          ok = false;
        }
        sqlite3_finalize(clock_stmt);
      } else {
        ok = false;
      }
    }
  }
  if (commit_stmt)
    sqlite3_finalize(commit_stmt);
  if (event_stmt)
    sqlite3_finalize(event_stmt);
  if (candidate_stmt)
    sqlite3_finalize(candidate_stmt);
  if (ok) {
    ok = Exec(db_, "COMMIT;") == SQLITE_OK;
  } else {
    Exec(db_, "ROLLBACK;");
  }
  if (!ok) {
    status_ = Status::kDbWriteFailed;
    return false;
  }
  EnsureFileModes();
  return true;
}

const char* FactStore::StatusCode(Status status) {
  switch (status) {
    case Status::kOk:
      return "ok";
    case Status::kNoHome:
      return "no_home";
    case Status::kRootCreateFailed:
      return "root_create_failed";
    case Status::kRootNotDirectory:
      return "root_not_directory";
    case Status::kRootSymlink:
      return "root_symlink";
    case Status::kRootOwner:
      return "root_owner";
    case Status::kRootPermission:
      return "root_permission";
    case Status::kDbSymlink:
      return "db_symlink";
    case Status::kDbNotRegular:
      return "db_not_regular";
    case Status::kDbOwner:
      return "db_owner";
    case Status::kDbPermission:
      return "db_permission";
    case Status::kDbCorrupt:
      return "db_corrupt";
    case Status::kDbUnsupportedVersion:
      return "db_unsupported_version";
    case Status::kDbClockInvalid:
      return "db_clock_invalid";
    case Status::kDbOpenFailed:
      return "db_open_failed";
    case Status::kDbWriteFailed:
      return "db_write_failed";
  }
  return "unknown";
}

const char* FactStore::StatusMessage(Status status) {
  switch (status) {
    case Status::kOk:
      return "fact store is healthy";
    case Status::kNoHome:
      return "HOME is not set; facts root cannot be located";
    case Status::kRootCreateFailed:
      return "facts root could not be created";
    case Status::kRootNotDirectory:
      return "facts root is not a directory";
    case Status::kRootSymlink:
      return "facts root is a symlink";
    case Status::kRootOwner:
      return "facts root is owned by another user";
    case Status::kRootPermission:
      return "facts root permissions are not 0700";
    case Status::kDbSymlink:
      return "facts.sqlite3 is a symlink";
    case Status::kDbNotRegular:
      return "facts.sqlite3 is not a regular file";
    case Status::kDbOwner:
      return "facts.sqlite3 is owned by another user";
    case Status::kDbPermission:
      return "facts.sqlite3 permissions are not 0600";
    case Status::kDbCorrupt:
      return "facts.sqlite3 failed the integrity check";
    case Status::kDbUnsupportedVersion:
      return "facts.sqlite3 schema or event format is not supported";
    case Status::kDbClockInvalid:
      return "facts.sqlite3 meta clock state is missing or invalid";
    case Status::kDbOpenFailed:
      return "facts.sqlite3 could not be opened";
    case Status::kDbWriteFailed:
      return "facts.sqlite3 commit transaction failed";
  }
  return "unknown fault";
}

}  // namespace rime
