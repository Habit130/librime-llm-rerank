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

// Maps a maintenance-lock status to the store status vocabulary (the lock
// file lives in the facts root, so its faults are store faults). The mapping
// is 1:1 so diagnostics keep the specific stable code.
FactStore::Status LockFaultToStoreStatus(MaintenanceLock::Status status) {
  switch (status) {
    case MaintenanceLock::Status::kNoHome:
      return FactStore::Status::kNoHome;
    case MaintenanceLock::Status::kRootCreateFailed:
      return FactStore::Status::kRootCreateFailed;
    case MaintenanceLock::Status::kRootNotDirectory:
      return FactStore::Status::kRootNotDirectory;
    case MaintenanceLock::Status::kRootSymlink:
      return FactStore::Status::kRootSymlink;
    case MaintenanceLock::Status::kRootOwner:
      return FactStore::Status::kRootOwner;
    case MaintenanceLock::Status::kRootPermission:
      return FactStore::Status::kRootPermission;
    case MaintenanceLock::Status::kLockSymlink:
      return FactStore::Status::kLockSymlink;
    case MaintenanceLock::Status::kLockNotRegular:
      return FactStore::Status::kLockNotRegular;
    case MaintenanceLock::Status::kLockOwner:
      return FactStore::Status::kLockOwner;
    case MaintenanceLock::Status::kLockPermission:
      return FactStore::Status::kLockPermission;
    case MaintenanceLock::Status::kLockOpenFailed:
      return FactStore::Status::kLockOpenFailed;
    case MaintenanceLock::Status::kLockTimeout:
      return FactStore::Status::kLockTimeout;
    case MaintenanceLock::Status::kMaintenanceLocked:
      return FactStore::Status::kMaintenanceLocked;
    case MaintenanceLock::Status::kOk:
      return FactStore::Status::kOk;
  }
  return FactStore::Status::kLockOpenFailed;
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

// Advances an HLC by one tick against the wall clock: the physical component
// jumps forward only when the wall clock moved ahead; otherwise just the
// logical component advances, so a clock rollback never rewinds old facts.
void GiveTick(int64_t& physical_ms, int64_t& logical) {
  int64_t now = NowMs();
  if (now > physical_ms) {
    physical_ms = now;
    logical = 0;
  } else {
    logical += 1;
  }
}

// Persists the two meta clock rows; must run inside the batch transaction.
bool RecordMetaClock(sqlite3* db, int64_t physical_ms, int64_t logical) {
  const char* update_clock = "UPDATE meta SET value = ? WHERE key = ?;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, update_clock, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  bool ok = true;
  sqlite3_bind_text(stmt, 1, std::to_string(physical_ms).c_str(), -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, kMetaClockPhysicalMs, -1, SQLITE_TRANSIENT);
  if (sqlite3_step(stmt) != SQLITE_DONE)
    ok = false;
  sqlite3_reset(stmt);
  sqlite3_bind_text(stmt, 1, std::to_string(logical).c_str(), -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, kMetaClockLogical, -1, SQLITE_TRANSIENT);
  if (ok && sqlite3_step(stmt) != SQLITE_DONE)
    ok = false;
  sqlite3_finalize(stmt);
  return ok;
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

FactStore::~FactStore() {}

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

bool EnsureFileModes(const path& root) {
  path db_path = root / kDbFileName;
  bool ok = chmod(db_path.c_str(), kFileMode) == 0;
  for (const char* suffix : {"-wal", "-shm"}) {
    path sidecar = root / (string(kDbFileName) + suffix);
    if (access(sidecar.c_str(), F_OK) == 0) {
      ok = chmod(sidecar.c_str(), kFileMode) == 0 && ok;
    }
  }
  return ok;
}

namespace {

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
    ");"
    "CREATE TABLE IF NOT EXISTS retractions ("
    " retraction_id TEXT PRIMARY KEY NOT NULL,"
    " commit_id TEXT NOT NULL REFERENCES commits(commit_id),"
    " hlc_physical_ms INTEGER NOT NULL,"
    " hlc_logical INTEGER NOT NULL,"
    " utc_retracted_at_ms INTEGER NOT NULL"
    ");"
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_retractions_commit_id"
    " ON retractions(commit_id);"
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

// Validates the meta rows and fills the clock and epoch; when the store was
// just created, initializes a fresh identity instead.
FactStore::Status ValidateOrInitializeMeta(sqlite3* db,
                                           int64_t* clock_physical_ms,
                                           int64_t* clock_logical) {
  bool has_meta = false;
  if (!QueryBoolValue(db, "SELECT EXISTS(SELECT 1 FROM meta);", &has_meta))
    return FactStore::Status::kDbClockInvalid;
  if (!has_meta) {
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
      if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) !=
          SQLITE_OK)
        return FactStore::Status::kDbWriteFailed;
      sqlite3_bind_text(stmt, 1, entry.first, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 2, entry.second.c_str(), -1, SQLITE_TRANSIENT);
      bool ok = sqlite3_step(stmt) == SQLITE_DONE;
      sqlite3_finalize(stmt);
      if (!ok)
        return FactStore::Status::kDbWriteFailed;
    }
    *clock_physical_ms = now;
    *clock_logical = 0;
    return FactStore::Status::kOk;
  }
  string value;
  if (!ReadMetaText(db, kMetaFactSchemaVersion, &value) ||
      value != std::to_string(kFactSchemaVersion)) {
    return FactStore::Status::kDbUnsupportedVersion;
  }
  if (!ReadMetaText(db, kMetaEventFormatVersion, &value) ||
      value != std::to_string(kEventFormatVersion)) {
    return FactStore::Status::kDbUnsupportedVersion;
  }
  if (!ReadMetaText(db, kMetaHistoryId, &value) || value.empty() ||
      !ReadMetaText(db, kMetaStoreEpoch, &value) || value.empty()) {
    return FactStore::Status::kDbClockInvalid;
  }
  if (!ReadMetaText(db, kMetaClockPhysicalMs, &value) ||
      !ParseInt64(value, clock_physical_ms) ||
      !ReadMetaText(db, kMetaClockLogical, &value) ||
      !ParseInt64(value, clock_logical) || *clock_physical_ms < 0 ||
      *clock_logical < 0) {
    return FactStore::Status::kDbClockInvalid;
  }
  return FactStore::Status::kOk;
}

// Opens a fresh verified connection: root and db file checks, sqlite open,
// pragmas, schema, meta. On failure closes the connection and returns the
// status; on success leaves `db` open for the caller (who must close it).
FactStore::Status OpenVerifiedConnection(const path& root,
                                         sqlite3** db,
                                         int64_t* clock_physical_ms,
                                         int64_t* clock_logical) {
  *db = nullptr;
  FactStore probe(root);
  if (FactStore::Status root_status = probe.VerifyRoot();
      root_status != FactStore::Status::kOk)
    return root_status;
  if (FactStore::Status file_status = probe.VerifyDbFile();
      file_status != FactStore::Status::kOk)
    return file_status;
  path db_path = root / kDbFileName;
  sqlite3* connection = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &connection,
                      SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE,
                      nullptr) != SQLITE_OK) {
    if (connection) {
      sqlite3_close(connection);
    }
    return FactStore::Status::kDbOpenFailed;
  }
  sqlite3_busy_timeout(connection, kBusyTimeoutMs);

  bool quick_check_ok = false;
  if (!QueryQuickCheck(connection, &quick_check_ok) || !quick_check_ok) {
    sqlite3_close(connection);
    return FactStore::Status::kDbCorrupt;
  }
  if (Exec(connection, "PRAGMA journal_mode=WAL;") != SQLITE_OK ||
      Exec(connection, "PRAGMA synchronous=FULL;") != SQLITE_OK ||
      Exec(connection, "PRAGMA foreign_keys=ON;") != SQLITE_OK) {
    sqlite3_close(connection);
    return FactStore::Status::kDbOpenFailed;
  }
  if (Exec(connection, kSchemaV1) != SQLITE_OK) {
    sqlite3_close(connection);
    return FactStore::Status::kDbOpenFailed;
  }
  FactStore::Status meta_status = ValidateOrInitializeMeta(
      connection, clock_physical_ms, clock_logical);
  if (meta_status != FactStore::Status::kOk) {
    sqlite3_close(connection);
    return meta_status;
  }
  *db = connection;
  return FactStore::Status::kOk;
}

}  // namespace

FactStore::Status FactStore::Open() {
  status_ = Status::kOk;
  int64_t physical = 0;
  int64_t logical = 0;
  sqlite3* db = nullptr;
  if (Status status = OpenVerifiedConnection(root_, &db, &physical, &logical);
      status != Status::kOk) {
    status_ = status;
    return status_;
  }
  // Probe the maintenance lock file too: a symlinked or misowned lock file is
  // a deterministic store fault that must stop recording, and creating it
  // here with 0600 keeps the root self-contained. When the exclusive lock is
  // held the probe still succeeds (the exclusive holder is maintenance in
  // progress, not a store fault).
  MaintenanceLock lock(root_);
  MaintenanceLock::Status ensure = lock.TryAcquireShared();
  if (ensure != MaintenanceLock::Status::kOk &&
      ensure != MaintenanceLock::Status::kMaintenanceLocked) {
    sqlite3_close(db);
    status_ = LockFaultToStoreStatus(ensure);
    return status_;
  }
  lock.Release();
  if (!EnsureFileModes(root_)) {
    sqlite3_close(db);
    status_ = Status::kDbPermission;
    return status_;
  }
  sqlite3_close(db);
  return Status::kOk;
}

FactStore::Status FactStore::PersistBatch(int64_t utc_committed_at_ms,
                                          vector<Event>* events,
                                          string* commit_id) {
  status_ = Status::kOk;
  if (!events || events->empty()) {
    status_ = Status::kDbWriteFailed;
    return status_;
  }
  // Hold the shared maintenance lock across the whole transaction; the
  // connection is opened under the lock and closed before it is released.
  MaintenanceLock lock(root_);
  if (MaintenanceLock::Status lock_status = lock.TryAcquireShared();
      lock_status != MaintenanceLock::Status::kOk) {
    status_ = LockFaultToStoreStatus(lock_status);
    return status_;
  }
  int64_t physical = 0;
  int64_t logical = 0;
  sqlite3* db = nullptr;
  Status open_status =
      OpenVerifiedConnection(root_, &db, &physical, &logical);
  if (open_status != Status::kOk) {
    lock.Release();
    status_ = open_status;
    return status_;
  }
  if (Exec(db, "BEGIN IMMEDIATE;") != SQLITE_OK) {
    sqlite3_close(db);
    lock.Release();
    status_ = Status::kDbWriteFailed;
    return status_;
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
  if (sqlite3_prepare_v2(db, insert_commit, -1, &commit_stmt, nullptr) !=
          SQLITE_OK ||
      sqlite3_prepare_v2(db, insert_event, -1, &event_stmt, nullptr) !=
          SQLITE_OK ||
      sqlite3_prepare_v2(db, insert_candidate, -1, &candidate_stmt, nullptr) !=
          SQLITE_OK) {
    ok = false;
  }
  string generated;
  if (ok) {
    if (commit_id && !commit_id->empty()) {
      generated = *commit_id;
    } else {
      generated = RandomUuid();
    }
    sqlite3_bind_text(commit_stmt, 1, generated.c_str(), -1,
                      SQLITE_TRANSIENT);
    sqlite3_bind_int64(commit_stmt, 2, utc_committed_at_ms);
    ok = sqlite3_step(commit_stmt) == SQLITE_DONE;
  }
  if (ok) {
    for (Event& event : *events) {
      GiveTick(physical, logical);
      event.hlc_physical_ms = physical;
      event.hlc_logical = logical;
      event.commit_id = generated;

      sqlite3_reset(event_stmt);
      sqlite3_bind_text(event_stmt, 1, event.event_id.c_str(), -1,
                        SQLITE_TRANSIENT);
      sqlite3_bind_text(event_stmt, 2, generated.c_str(), -1,
                        SQLITE_TRANSIENT);
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
    if (ok)
      ok = RecordMetaClock(db, physical, logical);
  }
  if (commit_stmt)
    sqlite3_finalize(commit_stmt);
  if (event_stmt)
    sqlite3_finalize(event_stmt);
  if (candidate_stmt)
    sqlite3_finalize(candidate_stmt);
  if (ok) {
    ok = Exec(db, "COMMIT;") == SQLITE_OK;
  } else {
    Exec(db, "ROLLBACK;");
  }
  // The connection must be closed before the shared lock is released: an
  // exclusive maintenance holder may replace the store immediately after.
  sqlite3_close(db);
  lock.Release();
  if (!ok) {
    status_ = Status::kDbWriteFailed;
    return status_;
  }
  if (commit_id)
    *commit_id = generated;
  EnsureFileModes(root_);
  return Status::kOk;
}

FactStore::Status FactStore::AppendRetraction(const string& commit_id,
                                              int64_t utc_retracted_at_ms,
                                              string* retraction_id_out) {
  status_ = Status::kOk;
  MaintenanceLock lock(root_);
  if (MaintenanceLock::Status lock_status = lock.TryAcquireShared();
      lock_status != MaintenanceLock::Status::kOk) {
    status_ = LockFaultToStoreStatus(lock_status);
    return status_;
  }
  int64_t physical = 0;
  int64_t logical = 0;
  sqlite3* db = nullptr;
  Status open_status =
      OpenVerifiedConnection(root_, &db, &physical, &logical);
  if (open_status != Status::kOk) {
    lock.Release();
    status_ = open_status;
    return status_;
  }
  // A single short transaction: decide retractability, append the fact and
  // advance the clock atomically. Retracting an unknown or already-retracted
  // commit is a no-op (idempotency), not a failure.
  if (Exec(db, "BEGIN IMMEDIATE;") != SQLITE_OK) {
    sqlite3_close(db);
    lock.Release();
    status_ = Status::kDbWriteFailed;
    return status_;
  }
  bool ok = true;
  sqlite3_stmt* check = nullptr;
  const char* kCheckRetractable = "SELECT EXISTS("
      "SELECT 1 FROM commits c"
      " WHERE c.commit_id = ?1"
      "   AND NOT EXISTS(SELECT 1 FROM retractions r"
      "                  WHERE r.commit_id = c.commit_id));";
  if (sqlite3_prepare_v2(db, kCheckRetractable, -1, &check, nullptr) !=
      SQLITE_OK) {
    ok = false;
  }
  int retractable = 0;
  if (ok) {
    sqlite3_bind_text(check, 1, commit_id.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(check) != SQLITE_ROW) {
      ok = false;
    } else {
      retractable = sqlite3_column_int(check, 0);
    }
  }
  sqlite3_finalize(check);
  if (!ok) {
    Exec(db, "ROLLBACK;");
    sqlite3_close(db);
    lock.Release();
    status_ = Status::kDbWriteFailed;
    return status_;
  }
  if (!retractable) {
    Exec(db, "COMMIT;");
    sqlite3_close(db);
    lock.Release();
    return Status::kOk;
  }
  GiveTick(physical, logical);
  string retraction_id = RandomUuid();
  sqlite3_stmt* insert = nullptr;
  const char* kInsertRetraction =
      "INSERT INTO retractions(retraction_id, commit_id, hlc_physical_ms,"
      " hlc_logical, utc_retracted_at_ms) VALUES(?1,?2,?3,?4,?5);";
  if (sqlite3_prepare_v2(db, kInsertRetraction, -1, &insert, nullptr) ==
      SQLITE_OK) {
    sqlite3_bind_text(insert, 1, retraction_id.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(insert, 2, commit_id.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(insert, 3, physical);
    sqlite3_bind_int64(insert, 4, logical);
    sqlite3_bind_int64(insert, 5, utc_retracted_at_ms);
    ok = sqlite3_step(insert) == SQLITE_DONE;
    sqlite3_finalize(insert);
  } else {
    ok = false;
  }
  if (ok)
    ok = RecordMetaClock(db, physical, logical);
  if (ok) {
    ok = Exec(db, "COMMIT;") == SQLITE_OK;
  } else {
    Exec(db, "ROLLBACK;");
  }
  sqlite3_close(db);
  lock.Release();
  if (!ok) {
    status_ = Status::kDbWriteFailed;
    return status_;
  }
  if (retraction_id_out)
    *retraction_id_out = retraction_id;
  EnsureFileModes(root_);
  return Status::kOk;
}

bool FactStore::QueryActiveEventsAsOf(int64_t hlc_physical_ms,
                                      int64_t hlc_logical,
                                      vector<Event>* out) {
  if (!out)
    return false;
  MaintenanceLock lock(root_);
  if (lock.TryAcquireShared() != MaintenanceLock::Status::kOk)
    return false;
  sqlite3* db = nullptr;
  int64_t physical = 0;
  int64_t logical = 0;
  if (OpenVerifiedConnection(root_, &db, &physical, &logical) !=
      Status::kOk) {
    lock.Release();
    return false;
  }
  const char* kQueryActiveAsOf =
      "SELECT e.event_id, e.commit_id, e.event_format_version, e.schema_id,"
      " e.canonical_segment_input, e.span_start, e.span_end, e.category,"
      " e.preceding_text, e.competition_complete, e.final_selection_text,"
      " e.confirmation_source, e.display_rank, e.display_page, e.session_id,"
      " e.session_seq, e.hlc_physical_ms, e.hlc_logical,"
      " e.utc_confirmed_at_ms, e.utc_committed_at_ms"
      " FROM selection_events e"
      " WHERE (e.hlc_physical_ms < ?1 OR (e.hlc_physical_ms = ?1"
      "        AND e.hlc_logical <= ?2))"
      " AND NOT EXISTS(SELECT 1 FROM retractions r"
      "                WHERE r.commit_id = e.commit_id"
      "                  AND (r.hlc_physical_ms < ?1 OR (r.hlc_physical_ms = ?1"
      "                       AND r.hlc_logical <= ?2)))"
      " ORDER BY e.hlc_physical_ms, e.hlc_logical, e.event_id;";
  sqlite3_stmt* stmt = nullptr;
  bool ok = false;
  if (sqlite3_prepare_v2(db, kQueryActiveAsOf, -1, &stmt, nullptr) ==
      SQLITE_OK) {
    sqlite3_bind_int64(stmt, 1, hlc_physical_ms);
    sqlite3_bind_int64(stmt, 2, hlc_logical);
    out->clear();
    ok = true;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      Event event;
      event.event_id =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
      event.commit_id =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
      event.schema_id =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
      event.canonical_segment_input =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
      event.span_start = static_cast<size_t>(sqlite3_column_int64(stmt, 5));
      event.span_end = static_cast<size_t>(sqlite3_column_int64(stmt, 6));
      event.category =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
      event.preceding_text =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
      event.competition_complete = sqlite3_column_int64(stmt, 9) != 0;
      event.final_selection_text =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
      event.confirmation_source =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
      event.display_rank = static_cast<int>(sqlite3_column_int64(stmt, 12));
      event.display_page = static_cast<int>(sqlite3_column_int64(stmt, 13));
      event.session_id =
          reinterpret_cast<const char*>(sqlite3_column_text(stmt, 14));
      event.session_seq = static_cast<int>(sqlite3_column_int64(stmt, 15));
      event.hlc_physical_ms = sqlite3_column_int64(stmt, 16);
      event.hlc_logical = sqlite3_column_int64(stmt, 17);
      event.utc_confirmed_at_ms = sqlite3_column_int64(stmt, 18);
      out->push_back(std::move(event));
    }
    sqlite3_finalize(stmt);
  }
  sqlite3_close(db);
  lock.Release();
  return ok;
}

FactStore::Status FactStore::ReadStoreIdentity(int64_t* hlc_physical_ms,
                                               int64_t* hlc_logical,
                                               string* store_epoch) {
  if (!hlc_physical_ms || !hlc_logical || !store_epoch)
    return Status::kDbClockInvalid;
  MaintenanceLock lock(root_);
  if (lock.TryAcquireShared() != MaintenanceLock::Status::kOk)
    return Status::kMaintenanceLocked;
  sqlite3* db = nullptr;
  int64_t physical = 0;
  int64_t logical = 0;
  Status status = OpenVerifiedConnection(root_, &db, &physical, &logical);
  if (status != Status::kOk) {
    lock.Release();
    return status;
  }
  string epoch;
  bool ok = ReadMetaText(db, kMetaStoreEpoch, &epoch) && !epoch.empty();
  sqlite3_close(db);
  lock.Release();
  if (!ok)
    return Status::kDbClockInvalid;
  *hlc_physical_ms = physical;
  *hlc_logical = logical;
  *store_epoch = epoch;
  return Status::kOk;
}

bool FactStore::IsFatalStatus(Status status) {
  switch (status) {
    case Status::kNoHome:
    case Status::kRootNotDirectory:
    case Status::kRootSymlink:
    case Status::kRootOwner:
    case Status::kRootPermission:
    case Status::kDbSymlink:
    case Status::kDbNotRegular:
    case Status::kDbOwner:
    case Status::kDbPermission:
    case Status::kDbCorrupt:
    case Status::kDbUnsupportedVersion:
    case Status::kDbClockInvalid:
    case Status::kLockSymlink:
    case Status::kLockNotRegular:
    case Status::kLockOwner:
    case Status::kLockPermission:
      return true;
    default:
      return false;
  }
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
    case Status::kMaintenanceLocked:
      return "maintenance_locked";
    case Status::kLockSymlink:
      return "lock_symlink";
    case Status::kLockNotRegular:
      return "lock_not_regular";
    case Status::kLockOwner:
      return "lock_owner";
    case Status::kLockPermission:
      return "lock_permission";
    case Status::kLockOpenFailed:
      return "lock_open_failed";
    case Status::kLockTimeout:
      return "lock_timeout";
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
    case Status::kMaintenanceLocked:
      return "exclusive maintenance lock is held; the write was buffered";
    case Status::kLockSymlink:
      return "maintenance.lock is a symlink";
    case Status::kLockNotRegular:
      return "maintenance.lock is not a regular file";
    case Status::kLockOwner:
      return "maintenance.lock is owned by another user";
    case Status::kLockPermission:
      return "maintenance.lock permissions are not 0600";
    case Status::kLockOpenFailed:
      return "maintenance.lock could not be opened";
    case Status::kLockTimeout:
      return "maintenance.lock exclusive acquisition timed out";
  }
  return "unknown fault";
}

}  // namespace rime
