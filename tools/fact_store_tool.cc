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
//       to one consistent SQLite read point.
//
//   fact_store_tool inspect --db <path>
//       Read-only validation and stats of one standalone fact store
//       database file (a snapshot or an extracted backup member). Rejects
//       WAL-dependent, corrupt or version-incompatible files. Never touches
//       the live facts root.
//
// Success output is a single JSON line. Failures print
// {"ok":false,"status":"<stable code>"} and exit 1. Output never contains
// private fact text.
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstring>
#include <string>

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
                rime::kFactSchemaVersion);
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

bool PathExists(const path& target) {
  struct stat st;
  return lstat(target.c_str(), &st) == 0;
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
               "usage: fact_store_tool <verify|create-empty|snapshot|inspect>"
               " --root <dir>|--db <path> [--output <path>]\n");
  return 2;
}

int RunVerify(const path& root) {
  path db_path = root / "facts.sqlite3";
  if (!PathExists(db_path)) {
    EmitFailure("no_store");
    return 1;
  }
  FactStore store(root);
  FactStore::Status status = store.Open();
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
  FactStore::Status status = store.Open();
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
  return Usage();
}
