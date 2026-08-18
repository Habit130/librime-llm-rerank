//
// Copyright RIME Developers
// Distributed under the BSD License
//
// fact_store_tool: the stable C++ seam through which the maintenance CLI
// creates and verifies empty fact stores without ever re-deriving fact
// semantics in Python.
//
// Commands:
//
//   fact_store_tool verify --root <dir>
//       Open and validate an existing facts store (shared maintenance
//       lease, no creation). Prints its durable identity and whether every
//       fact table is empty. A missing database is reported as
//       {"status":"no_store"} with exit code 1.
//
//   fact_store_tool create-empty --root <dir>
//       Create a brand-new empty facts store at <dir> (the directory must
//       not exist yet). The store receives a fresh history_id, a fresh
//       store_epoch and a fresh HLC (logical 0), then is re-opened and
//       validated: quick_check, meta, empty fact tables, exact owner/mode
//       and no residual WAL/SHM sidecars. Prints the new identity.
//
//   fact_store_tool snapshot --root <dir> --output <path>
//       Create a consistent snapshot of the live store with the SQLite
//       Online Backup API into a brand-new single-file database at <path>
//       (exclusive create, never overwrites), then fully validate the
//       snapshot (integrity, foreign keys, schema/meta/identity invariants,
//       no WAL dependency, owner-only 0600, fsync) and print its stats.
//       Concurrent fact writers are never blocked; the snapshot corresponds
//       to one consistent SQLite read point. Supported-old stores can be
//       snapshotted (maintenance open) so the migrate operation can upgrade
//       a verified snapshot.
//
//   fact_store_tool inspect --db <path>
//       Read-only validation and stats of one standalone fact store
//       database file (a snapshot or an extracted backup member). Rejects
//       WAL-dependent, corrupt, too-new or (in the recorder semantics)
//       supported-old files. Never touches the live facts root.
//
//   fact_store_tool schema --root <dir>
//       Open the live store in the maintenance mode and print its durable
//       schema disposition (fact_schema_version, event_format_version,
//       disposition: current|needs_migration|unsupported|missing_step).
//       Never writes; never migrates. A missing store is reported as
//       {"status":"no_store"}.
//
//   fact_store_tool migrate --db <path>
//       Migrate ONE standalone database file (a snapshot or an extracted
//       backup member) in place to the current schema head. The file must
//       not be the live locked root (the caller owns staging and quiesce).
//       The whole ordered step chain runs in one SQLite transaction with
//       pre-commit validation; on any failure the file's facts are
//       unchanged. When SQUIRREL_FACT_MIGRATE_TEST_STEPS is set the
//       test-registered predecessor step is loaded (decision B), so the
//       operation tests can drive a real supported-old -> head path.
//
// Success output is a single JSON line. Failures print
// {"ok":false,"status":"<stable code>"} and exit 1. Output never contains
// private fact text.
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "fact_migrator.h"
#include "fact_store.h"
#include "rime/common.h"

using rime::FactStore;
using rime::path;
using rime::string;

namespace {

void WriteJsonString(std::string* out, const char* value) {
  out->push_back('"');
  for (const unsigned char* p =
           reinterpret_cast<const unsigned char*>(value);
       p && *p; ++p) {
    switch (*p) {
      case '"':
        out->append("\\\"");
        break;
      case '\\':
        out->append("\\\\");
        break;
      case '\n':
        out->append("\\n");
        break;
      case '\r':
        out->append("\\r");
        break;
      case '\t':
        out->append("\\t");
        break;
      default:
        if (*p < 0x20) {
          char buffer[8];
          std::snprintf(buffer, sizeof(buffer), "\\u%04x", *p);
          out->append(buffer);
        } else {
          out->push_back(static_cast<char>(*p));
        }
    }
  }
  out->push_back('"');
}

void EmitFailure(const char* status) {
  std::string payload = "{\"ok\":false,\"status\":";
  WriteJsonString(&payload, status);
  payload += "}";
  std::printf("%s\n", payload.c_str());
}

void EmitIdentity(const string& history_id, const string& store_epoch,
                  int64_t physical_ms, int64_t logical, bool created,
                  bool empty) {
  std::string payload = "{\"ok\":true,\"created\":";
  payload += created ? "true" : "false";
  payload += ",\"history_id\":";
  WriteJsonString(&payload, history_id.c_str());
  payload += ",\"store_epoch\":";
  WriteJsonString(&payload, store_epoch.c_str());
  payload += ",\"hlc_physical_ms\":";
  payload += std::to_string(physical_ms);
  payload += ",\"hlc_logical\":";
  payload += std::to_string(logical);
  payload += ",\"fact_schema_version\":";
  payload += std::to_string(rime::kFactSchemaVersion);
  payload += ",\"event_format_version\":";
  payload += std::to_string(rime::kEventFormatVersion);
  payload += ",\"empty\":";
  payload += empty ? "true" : "false";
  payload += "}";
  std::printf("%s\n", payload.c_str());
}

void AppendJsonInt(std::string* payload, const char* key, int64_t value) {
  payload->append(",");
  payload->append(key);
  payload->append(":");
  payload->append(std::to_string(value));
}

void AppendJsonString(std::string* payload, const char* key,
                      const string& value) {
  payload->append(",");
  payload->append(key);
  payload->append(":");
  WriteJsonString(payload, value.c_str());
}

// One JSON line with the full snapshot stats (identity, versions, counts,
// clock and event high-water marks); empty-store markers stay -1 so the
// Python manifest can distinguish "no events" from an impossible value.
void EmitSnapshotStats(const rime::FactStore::SnapshotStats& stats) {
  std::string payload = "{\"ok\":true,\"history_id\":";
  WriteJsonString(&payload, stats.history_id.c_str());
  payload += ",\"store_epoch\":";
  WriteJsonString(&payload, stats.store_epoch.c_str());
  AppendJsonInt(&payload, "\"fact_schema_version\"",
                stats.fact_schema_version);
  AppendJsonInt(&payload, "\"event_format_version\"",
                stats.event_format_version);
  AppendJsonInt(&payload, "\"event_format_version_min\"",
                stats.event_format_min);
  AppendJsonInt(&payload, "\"event_format_version_max\"",
                stats.event_format_max);
  AppendJsonInt(&payload, "\"commit_count\"", stats.commit_count);
  AppendJsonInt(&payload, "\"event_count\"", stats.event_count);
  AppendJsonInt(&payload, "\"candidate_count\"", stats.candidate_count);
  AppendJsonInt(&payload, "\"retraction_count\"", stats.retraction_count);
  AppendJsonInt(&payload, "\"hlc_physical_ms\"", stats.hlc_physical_ms);
  AppendJsonInt(&payload, "\"hlc_logical\"", stats.hlc_logical);
  AppendJsonInt(&payload, "\"event_hlc_physical_ms\"",
                stats.event_hlc_physical_ms);
  AppendJsonInt(&payload, "\"event_hlc_logical\"", stats.event_hlc_logical);
  payload += "}";
  std::printf("%s\n", payload.c_str());
}

const char* SchemaDispositionCodeName(rime::SchemaDispositionCode disposition) {
  switch (disposition) {
    case rime::SchemaDispositionCode::kCurrent:
      return "current";
    case rime::SchemaDispositionCode::kNeedsMigration:
      return "needs_migration";
    case rime::SchemaDispositionCode::kUnsupported:
      return "unsupported";
    case rime::SchemaDispositionCode::kMissingStep:
      return "missing_step";
  }
  return "unknown";
}

// One JSON line describing the live store's durable schema disposition.
void EmitSchemaDisposition(const rime::FactStore::SnapshotStats& stats,
                           rime::SchemaDispositionCode disposition) {
  std::string payload = "{\"ok\":true,\"fact_schema_version\":";
  payload += std::to_string(stats.fact_schema_version);
  payload += ",\"event_format_version\":";
  payload += std::to_string(stats.event_format_version);
  payload += ",\"disposition\":";
  WriteJsonString(&payload, SchemaDispositionCodeName(disposition));
  payload += ",\"history_id\":";
  WriteJsonString(&payload, stats.history_id.c_str());
  payload += ",\"store_epoch\":";
  WriteJsonString(&payload, stats.store_epoch.c_str());
  payload += "}";
  std::printf("%s\n", payload.c_str());
}

// One JSON line with the migrate result (identity, versions, epoch rule and
// projection counts; never any event content).
void EmitMigrationResult(const rime::FactMigrationResult& result) {
  std::string payload = "{\"ok\":true,\"status\":";
  WriteJsonString(&payload,
                  rime::FactMigrationStatusCode(result.status));
  payload += ",\"from_version\":";
  payload += std::to_string(result.from_version);
  payload += ",\"to_version\":";
  payload += std::to_string(result.to_version);
  payload += ",\"events_projected\":";
  payload += std::to_string(result.events_projected);
  payload += ",\"events_preserved\":";
  payload += std::to_string(result.events_preserved);
  payload += ",\"epoch_changed\":";
  payload += result.epoch_changed ? "true" : "false";
  payload += ",\"history_id\":";
  WriteJsonString(&payload, result.history_id.c_str());
  payload += ",\"store_epoch\":";
  WriteJsonString(&payload, result.store_epoch.c_str());
  payload += "}";
  std::printf("%s\n", payload.c_str());
}

bool PathExists(const path& target) {
  struct stat st;
  return lstat(target.c_str(), &st) == 0;
}

// Strict integer parse for the durable schema versions; any malformed value
// fails the schema command closed.
bool ParseSchemaInt(const char* text, int64_t* value) {
  if (!text || !*text)
    return false;
  errno = 0;
  char* end = nullptr;
  long long parsed = std::strtoll(text, &end, 10);
  if (errno == ERANGE || end != text + std::strlen(text))
    return false;
  *value = static_cast<int64_t>(parsed);
  return true;
}

bool IsExactOwnerMode(const path& target, mode_t mode) {
  struct stat st;
  if (lstat(target.c_str(), &st) != 0)
    return false;
  return S_ISREG(st.st_mode) && st.st_uid == getuid() &&
         (st.st_mode & 0777) == mode;
}

// The tool is never an interactive user interface; a short fixed usage line
// is enough for an operator to recover a broken invocation.
int Usage() {
  std::fprintf(stderr,
               "usage: fact_store_tool <verify|create-empty|snapshot|inspect|"
               "schema|migrate> --root <dir>|--db <path> [--output <path>]\n");
  return 2;
}

int RunVerify(const path& root) {
  path db_path = root / "facts.sqlite3";
  if (!PathExists(db_path)) {
    EmitFailure("no_store");
    return 1;
  }
  FactStore store(root);
  FactStore::Status status = store.Open(FactStore::OpenMode::kMaintenance);
  if (status != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(status));
    return 1;
  }
  int64_t physical_ms = 0;
  int64_t logical = 0;
  string history_id;
  string store_epoch;
  bool empty = false;
  status = store.ReadStoreIdentity(&physical_ms, &logical, &store_epoch,
                                   &history_id);
  if (status == FactStore::Status::kOk) {
    status = store.VerifyEmpty(&empty);
  }
  if (status != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(status));
    return 1;
  }
  EmitIdentity(history_id, store_epoch, physical_ms, logical, false, empty);
  return 0;
}

int RunCreateEmpty(const path& root) {
  if (PathExists(root)) {
    EmitFailure("root_exists");
    return 1;
  }
  int64_t physical_ms = 0;
  int64_t logical = 0;
  string history_id;
  string store_epoch;
  {
    FactStore store(root);
    FactStore::Status status = store.Open();
    if (status != FactStore::Status::kOk) {
      EmitFailure(FactStore::StatusCode(status));
      return 1;
    }
    bool empty = false;
    status = store.ReadStoreIdentity(&physical_ms, &logical, &store_epoch,
                                     &history_id);
    if (status == FactStore::Status::kOk) {
      status = store.VerifyEmpty(&empty);
    }
    if (status != FactStore::Status::kOk) {
      EmitFailure(FactStore::StatusCode(status));
      return 1;
    }
    // Fresh identities are required by the clear contract: a staged store
    // must never share identity with any previous history.
    if (history_id.empty() || store_epoch.empty() || logical != 0 || !empty) {
      EmitFailure("invalid_empty_store");
      return 1;
    }
    // Merge every WAL page into the main file. The published artifact is a
    // single database file, not a database plus sidecars.
    status = store.CheckpointTruncate();
    if (status != FactStore::Status::kOk) {
      EmitFailure(FactStore::StatusCode(status));
      return 1;
    }
  }
  // The destructor has closed the connection. Remove any sidecars the
  // platform's SQLite left behind (this host keeps -wal/-shm after the last
  // close; the checkpoint above guarantees the main file alone is complete)
  // and prove the published artifact is a single regular owner-owned 0600
  // file.
  if (!IsExactOwnerMode(root / "facts.sqlite3", 0600)) {
    EmitFailure("db_permission");
    return 1;
  }
  for (const char* suffix : {"-wal", "-shm"}) {
    path sidecar = root / (string("facts.sqlite3") + suffix);
    if (PathExists(sidecar) && unlink(sidecar.c_str()) != 0) {
      EmitFailure("sidecar_residual");
      return 1;
    }
  }
  EmitIdentity(history_id, store_epoch, physical_ms, logical, true, true);
  return 0;
}

int RunSnapshot(const path& root, const path& output) {
  if (output.empty()) {
    EmitFailure("no_output");
    return 1;
  }
  if (PathExists(output)) {
    // Exclusive destination: the Python executor owns the staging
    // directory lifecycle and must move stale staging away first.
    EmitFailure("output_exists");
    return 1;
  }
  FactStore store(root);
  FactStore::Status status = store.Open(FactStore::OpenMode::kMaintenance);
  if (status != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(status));
    return 1;
  }
  rime::FactStore::SnapshotStats stats;
  status = store.SnapshotTo(output, &stats);
  if (status != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(status));
    return 1;
  }
  EmitSnapshotStats(stats);
  return 0;
}

// Decision B seam loader: when SQUIRREL_FACT_MIGRATE_TEST_STEPS is set the
// test-registered predecessor step v1 -> v2 (interpretation-preserving) is
// loaded so the supported-old -> head path is real. The env var must never
// be set in production deployments; the operation tests set it per-process.
// Every command that consults the step table (schema, migrate) loads it.
void LoadTestMigrationStepsIfRequested() {
  if (getenv("SQUIRREL_FACT_MIGRATE_TEST_STEPS")) {
    rime::RegisterTestMigrationStep(1, 2, false, "stamp");
  }
}

// Reads the live store's schema disposition. Never writes and never
// migrates; the disposition is derived from the C++ step table (Python
// never re-derives it). Unlike the maintenance open, a too-new or gap store
// is REPORTED with its disposition (exit 0) so the migrate operation can
// give an explicit, distinct report; only unreadable/corrupt stores fail.
int RunSchema(const path& root) {
  LoadTestMigrationStepsIfRequested();
  path db_path = root / "facts.sqlite3";
  if (!PathExists(db_path)) {
    EmitFailure("no_store");
    return 1;
  }
  struct stat st;
  if (lstat(db_path.c_str(), &st) != 0) {
    EmitFailure("no_store");
    return 1;
  }
  if (S_ISLNK(st.st_mode)) {
    EmitFailure("db_symlink");
    return 1;
  }
  if (!S_ISREG(st.st_mode)) {
    EmitFailure("db_not_regular");
    return 1;
  }
  if (st.st_uid != getuid()) {
    EmitFailure("db_owner");
    return 1;
  }
  if ((st.st_mode & 0777) != 0600) {
    EmitFailure("db_permission");
    return 1;
  }
  // Read the durable meta directly with a read-write open (no CREATE, never
  // writes). A WAL live store cannot be opened read-only on this host; the
  // maintenance open would refuse a too-new store, and this command must
  // report that disposition rather than fail. Reading meta alone is the C++
  // fact semantics; Python never re-derives it.
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READWRITE,
                      nullptr) != SQLITE_OK) {
    if (db) {
      sqlite3_close(db);
    }
    EmitFailure("db_open_failed");
    return 1;
  }
  int64_t schema_version = -1;
  int64_t event_format_version = -1;
  string history_id;
  string store_epoch;
  bool ok = true;
  sqlite3_stmt* stmt = nullptr;
  const char* kMeta = "SELECT key, value FROM meta;";
  if (sqlite3_prepare_v2(db, kMeta, -1, &stmt, nullptr) != SQLITE_OK) {
    ok = false;
  }
  while (ok && sqlite3_step(stmt) == SQLITE_ROW) {
    const unsigned char* key = sqlite3_column_text(stmt, 0);
    const unsigned char* value = sqlite3_column_text(stmt, 1);
    if (!key || !value) {
      ok = false;
      break;
    }
    const char* key_text = reinterpret_cast<const char*>(key);
    const char* value_text = reinterpret_cast<const char*>(value);
    if (std::strcmp(key_text, "fact_schema_version") == 0) {
      if (!ParseSchemaInt(value_text, &schema_version))
        ok = false;
    } else if (std::strcmp(key_text, "event_format_version") == 0) {
      if (!ParseSchemaInt(value_text, &event_format_version))
        ok = false;
    } else if (std::strcmp(key_text, "history_id") == 0) {
      history_id = value_text;
    } else if (std::strcmp(key_text, "store_epoch") == 0) {
      store_epoch = value_text;
    }
  }
  if (stmt) {
    sqlite3_finalize(stmt);
  }
  sqlite3_close(db);
  if (!ok || schema_version < 0 || event_format_version < 0 ||
      history_id.empty() || store_epoch.empty()) {
    EmitFailure("db_clock_invalid");
    return 1;
  }
  rime::FactStore::SnapshotStats stats;
  stats.fact_schema_version = static_cast<int>(schema_version);
  stats.event_format_version = static_cast<int>(event_format_version);
  stats.history_id = history_id;
  stats.store_epoch = store_epoch;
  EmitSchemaDisposition(stats, rime::DispositionFor(
      static_cast<int>(schema_version)));
  return 0;
}

// Migrates ONE standalone database file in place (a snapshot or an extracted
// backup member), never the live locked root. The whole ordered step chain
// runs in one SQLite transaction with pre-commit validation; any failure
// leaves the file's facts unchanged. The test seam is loaded when
// SQUIRREL_FACT_MIGRATE_TEST_STEPS is set (decision B).
int RunMigrate(const path& db_path) {
  if (db_path.empty()) {
    EmitFailure("no_db");
    return 1;
  }
  struct stat st;
  if (lstat(db_path.c_str(), &st) != 0) {
    EmitFailure("no_store");
    return 1;
  }
  if (S_ISLNK(st.st_mode)) {
    EmitFailure("db_symlink");
    return 1;
  }
  if (!S_ISREG(st.st_mode)) {
    EmitFailure("db_not_regular");
    return 1;
  }
  if (st.st_uid != getuid() || (st.st_mode & 0777) != 0600) {
    EmitFailure("db_permission");
    return 1;
  }
  LoadTestMigrationStepsIfRequested();
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db,
                      SQLITE_OPEN_READWRITE, nullptr) != SQLITE_OK) {
    if (db) {
      sqlite3_close(db);
    }
    EmitFailure("db_open_failed");
    return 1;
  }
  rime::FactMigrationResult result = rime::MigrateFile(db);
  sqlite3_close(db);
  if (result.status != rime::FactMigrationStatus::kOk &&
      result.status != rime::FactMigrationStatus::kNoMigration) {
    EmitFailure(rime::FactMigrationStatusCode(result.status));
    return 1;
  }
  EmitMigrationResult(result);
  return 0;
}

int RunInspect(const path& db_path) {
  if (db_path.empty()) {
    EmitFailure("no_db");
    return 1;
  }
  struct stat st;
  if (lstat(db_path.c_str(), &st) != 0) {
    EmitFailure("no_store");
    return 1;
  }
  if (S_ISLNK(st.st_mode)) {
    EmitFailure("db_symlink");
    return 1;
  }
  if (!S_ISREG(st.st_mode)) {
    EmitFailure("db_not_regular");
    return 1;
  }
  rime::FactStore::SnapshotStats stats;
  FactStore::Status status =
      rime::FactStore::InspectSnapshotFile(db_path, &stats);
  if (status != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(status));
    return 1;
  }
  EmitSnapshotStats(stats);
  return 0;
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 2)
    return Usage();
  const char* command = argv[1];
  path root;
  path output;
  path db_path;
  for (int index = 2; index + 1 < argc; index += 2) {
    if (std::strcmp(argv[index], "--root") == 0) {
      root = path(argv[index + 1]);
    } else if (std::strcmp(argv[index], "--output") == 0) {
      output = path(argv[index + 1]);
    } else if (std::strcmp(argv[index], "--db") == 0) {
      db_path = path(argv[index + 1]);
    } else {
      return Usage();
    }
  }
  if (std::strcmp(command, "verify") == 0)
    return root.empty() ? Usage() : RunVerify(root);
  if (std::strcmp(command, "create-empty") == 0)
    return root.empty() ? Usage() : RunCreateEmpty(root);
  if (std::strcmp(command, "snapshot") == 0)
    return (root.empty() || output.empty()) ? Usage() : RunSnapshot(root,
                                                                    output);
  if (std::strcmp(command, "inspect") == 0)
    return db_path.empty() ? Usage() : RunInspect(db_path);
  if (std::strcmp(command, "schema") == 0)
    return root.empty() ? Usage() : RunSchema(root);
  if (std::strcmp(command, "migrate") == 0)
    return db_path.empty() ? Usage() : RunMigrate(db_path);
  return Usage();
}
