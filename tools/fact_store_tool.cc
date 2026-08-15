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
               "usage: fact_store_tool <verify|create-empty> --root <dir>\n");
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

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 2)
    return Usage();
  const char* command = argv[1];
  path root;
  for (int index = 2; index + 1 < argc; index += 2) {
    if (std::strcmp(argv[index], "--root") == 0) {
      root = path(argv[index + 1]);
    } else {
      return Usage();
    }
  }
  if (root.empty())
    return Usage();
  if (std::strcmp(command, "verify") == 0)
    return RunVerify(root);
  if (std::strcmp(command, "create-empty") == 0)
    return RunCreateEmpty(root);
  return Usage();
}
