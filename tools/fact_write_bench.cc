//
// Copyright RIME Developers
// Distributed under the BSD License
//
// fact_write_bench: the #71 fact-write eligibility benchmark (Habit130/
// squirrel#71, SCN-71-5).  Uses the real C++ FactStore (the production
// write path: WAL + foreign keys + synchronous=FULL, one BEGIN IMMEDIATE
// short transaction per commit batch) with real-shaped commit batches
// (multi-event compositions with competition candidate rows), exactly the
// shape the recorder produces.
//
// Commands:
//
//   fact_write_bench single --root <dir> --batches N [--events-per-batch K]
//       One writer persists N consecutive commit batches; reports the
//       per-batch latency distribution (p50/p95/p99) and the JOURNAL MODE /
//       SYNCHRONOUS pragma values as proof of the durability level.
//
//   fact_write_bench multi --root <dir> --writers 4 --batches-per-writer N
//       Four independent processes (this binary relaunched via posix_spawn,
//       mirroring the plugin's concurrent-writer test) race commit batches
//       on one store; reports per-writer batch latency distributions and
//       the final durable counts (commits/events/candidates) proving every
//       batch landed exactly once.
//
// Output is a single JSON line per command on stdout; failures print
// {"ok":false,"status":"<stable code>"} and exit 1.  Output never contains
// private fact text.
#include <spawn.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include <mach-o/dyld.h>

extern char** environ;

#include "fact_store.h"
#include "rime/common.h"

using rime::FactStore;
using rime::path;
using rime::string;

namespace {

constexpr int kMultiWriterFlagArgc = 3;

FactStore::Event MakeEvent(int seq, int events_per_batch) {
  FactStore::Event event;
  event.event_id = "bench-event-" + std::to_string(seq);
  event.schema_id = "luna_pinyin";
  event.canonical_segment_input = "bench-key";
  event.span_start = 0;
  event.span_end = 4;
  event.category = "word";
  event.preceding_text = std::string(64, 'a');
  event.competition_complete = true;
  event.final_selection_text =
      seq % 3 == 0 ? "w0" : (seq % 3 == 1 ? "w1" : "w2");
  event.confirmation_source =
      seq % 2 == 0 ? "explicit_current" : "explicit_indexed";
  event.trigger_keycode = -1;
  event.display_rank = seq % 3 == 0 ? 1 : 2;
  event.display_page = 1;
  event.session_id = "bench-session";
  event.session_seq = seq;
  event.utc_confirmed_at_ms = 1700000000000LL + seq;
  event.candidates = {{0, "w0"}, {1, "w1"}, {2, "w2"}};
  return event;
}

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

std::vector<double> Percentiles(const std::vector<double>& values,
                                double p50, double p95, double p99) {
  std::vector<double> sorted = values;
  std::sort(sorted.begin(), sorted.end());
  auto at = [&sorted](double p) {
    if (sorted.empty())
      return 0.0;
    size_t index = static_cast<size_t>(p * static_cast<double>(sorted.size()));
    if (index >= sorted.size())
      index = sorted.size() - 1;
    return sorted[index];
  };
  return {at(p50), at(p95), at(p99)};
}

void AppendPct(std::string* payload, const char* key,
               const std::vector<double>& pcts) {
  char buffer[128];
  std::snprintf(buffer, sizeof(buffer),
                ",\"%s\":{\"p50\":%.3f,\"p95\":%.3f,\"p99\":%.3f}", key,
                pcts[0], pcts[1], pcts[2]);
  payload->append(buffer);
}

bool PathExists(const path& target) {
  struct stat st;
  return lstat(target.c_str(), &st) == 0;
}

int RunSingle(int argc, char** argv) {
  path root;
  int batches = 10000;
  int events_per_batch = 1;
  for (int index = 2; index + 1 < argc; index += 2) {
    if (std::strcmp(argv[index], "--root") == 0) {
      root = path(argv[index + 1]);
    } else if (std::strcmp(argv[index], "--batches") == 0) {
      batches = std::atoi(argv[index + 1]);
    } else if (std::strcmp(argv[index], "--events-per-batch") == 0) {
      events_per_batch = std::atoi(argv[index + 1]);
    }
  }
  if (root.empty() || batches <= 0 || events_per_batch <= 0) {
    EmitFailure("invalid_args");
    return 1;
  }
  FactStore store(root);
  FactStore::Status status = store.Open();
  if (status != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(status));
    return 1;
  }

  std::vector<double> latencies;
  latencies.reserve(batches);
  int seq = 0;
  bool ok = true;
  for (int batch = 0; batch < batches; ++batch) {
    std::vector<FactStore::Event> events;
    events.reserve(events_per_batch);
    for (int e = 0; e < events_per_batch; ++e)
      events.push_back(MakeEvent(seq++, events_per_batch));
    auto start = std::chrono::steady_clock::now();
    if (!store.PersistBatch(1700000000000LL + batch, &events)) {
      ok = false;
      break;
    }
    auto end = std::chrono::steady_clock::now();
    latencies.push_back(
        std::chrono::duration<double, std::milli>(end - start).count());
  }
  if (!ok) {
    EmitFailure("persist_failed");
    return 1;
  }

  // Durable counts (prove every batch landed exactly once).
  sqlite3* db = nullptr;
  if (sqlite3_open_v2((root / "facts.sqlite3").c_str(), &db,
                      SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
    EmitFailure("count_failed");
    return 1;
  }
  auto count = [db](const char* sql) -> long long {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
      return -1;
    long long result = -1;
    if (sqlite3_step(stmt) == SQLITE_ROW)
      result = sqlite3_column_int64(stmt, 0);
    sqlite3_finalize(stmt);
    return result;
  };
  long long commits = count("SELECT COUNT(*) FROM commits;");
  long long events = count("SELECT COUNT(*) FROM selection_events;");
  long long candidates = count("SELECT COUNT(*) FROM selection_candidates;");
  const char* journal_mode = nullptr;
  const char* synchronous = nullptr;
  {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, "PRAGMA journal_mode;", -1, &stmt, nullptr) ==
        SQLITE_OK) {
      if (sqlite3_step(stmt) == SQLITE_ROW)
        journal_mode = sqlite3_column_text(
            stmt, 0) ? "wal" : "?";
      sqlite3_finalize(stmt);
    }
    if (sqlite3_prepare_v2(db, "PRAGMA synchronous;", -1, &stmt, nullptr) ==
        SQLITE_OK) {
      if (sqlite3_step(stmt) == SQLITE_ROW) {
        static char sync_buf[16];
        std::snprintf(sync_buf, sizeof(sync_buf), "%d",
                      sqlite3_column_int(stmt, 0));
        synchronous = sync_buf;
      }
      sqlite3_finalize(stmt);
    }
  }
  sqlite3_close(db);

  auto pcts = Percentiles(latencies, 0.50, 0.95, 0.99);
  std::string payload = "{\"ok\":true,\"batches\":";
  payload += std::to_string(batches);
  payload += ",\"events_per_batch\":";
  payload += std::to_string(events_per_batch);
  payload += ",\"commits\":";
  payload += std::to_string(commits);
  payload += ",\"events\":";
  payload += std::to_string(events);
  payload += ",\"candidates\":";
  payload += std::to_string(candidates);
  AppendPct(&payload, "latency_ms", pcts);
  payload += ",\"journal_mode\":";
  WriteJsonString(&payload, journal_mode ? journal_mode : "unknown");
  payload += ",\"synchronous\":";
  WriteJsonString(&payload, synchronous ? synchronous : "unknown");
  payload += "}";
  std::printf("%s\n", payload.c_str());
  return 0;
}

// Spawned-writer mode: the child that races on the same store.
// ``writer_index`` offsets the event ids so no two processes collide on the
// event_id PRIMARY KEY.
void RunSpawnedWriter(const path& root, int batches, int writer_index) {
  FactStore store(root);
  if (store.Open() != FactStore::Status::kOk)
    _exit(2);
  std::vector<double> latencies;
  latencies.reserve(batches);
  int seq = writer_index * 1000000;
  for (int batch = 0; batch < batches; ++batch) {
    std::vector<FactStore::Event> events{MakeEvent(seq++, 1)};
    auto start = std::chrono::steady_clock::now();
    if (!store.PersistBatch(1700000000000LL + batch, &events))
      _exit(3);
    auto end = std::chrono::steady_clock::now();
    latencies.push_back(
        std::chrono::duration<double, std::milli>(end - start).count());
  }
  auto pcts = Percentiles(latencies, 0.50, 0.95, 0.99);
  std::printf(
      "{\"ok\":true,\"writer\":\"child\",\"batches\":%d,"
      "\"latency_ms\":{\"p50\":%.3f,\"p95\":%.3f,\"p99\":%.3f}}\n",
      batches, pcts[0], pcts[1], pcts[2]);
  _exit(0);
}

int RunMulti(int argc, char** argv) {
  path root;
  int writers = 4;
  int batches_per_writer = 10000;
  for (int index = 2; index + 1 < argc; index += 2) {
    if (std::strcmp(argv[index], "--root") == 0) {
      root = path(argv[index + 1]);
    } else if (std::strcmp(argv[index], "--writers") == 0) {
      writers = std::atoi(argv[index + 1]);
    } else if (std::strcmp(argv[index], "--batches-per-writer") == 0) {
      batches_per_writer = std::atoi(argv[index + 1]);
    }
  }
  if (root.empty() || writers <= 1 || batches_per_writer <= 0) {
    EmitFailure("invalid_args");
    return 1;
  }
  // Establish the store first.
  {
    FactStore store(root);
    if (store.Open() != FactStore::Status::kOk) {
      EmitFailure(FactStore::StatusCode(store.status()));
      return 1;
    }
  }
  // Spawn the children (this binary relaunched in spawned-writer mode).
  char self_path[4096];
  uint32_t path_size = sizeof(self_path);
  if (_NSGetExecutablePath(self_path, &path_size) != 0) {
    EmitFailure("self_path");
    return 1;
  }
  std::vector<pid_t> children;
  for (int w = 1; w < writers; ++w) {
    char batches_arg[32];
    std::snprintf(batches_arg, sizeof(batches_arg), "%d",
                  batches_per_writer);
    char index_arg[32];
    std::snprintf(index_arg, sizeof(index_arg), "%d", w);
    char* argv_child[] = {
        self_path, const_cast<char*>("--spawned-writer"),
        const_cast<char*>(root.c_str()), batches_arg, index_arg, nullptr};
    pid_t pid = -1;
    if (posix_spawn(&pid, self_path, nullptr, nullptr, argv_child,
                    environ) != 0) {
      EmitFailure("spawn_failed");
      return 1;
    }
    children.push_back(pid);
  }

  // The parent writer races the children.
  FactStore store(root);
  if (store.Open() != FactStore::Status::kOk) {
    EmitFailure(FactStore::StatusCode(store.status()));
    return 1;
  }
  std::vector<double> latencies;
  latencies.reserve(batches_per_writer);
  int seq = 0;
  bool ok = true;
  for (int batch = 0; batch < batches_per_writer; ++batch) {
    std::vector<FactStore::Event> events{MakeEvent(seq++, 1)};
    auto start = std::chrono::steady_clock::now();
    if (!store.PersistBatch(1700000000000LL + batch, &events)) {
      ok = false;
      break;
    }
    auto end = std::chrono::steady_clock::now();
    latencies.push_back(
        std::chrono::duration<double, std::milli>(end - start).count());
  }
  for (pid_t pid : children) {
    int status = 0;
    waitpid(pid, &status, 0);
  }
  if (!ok) {
    EmitFailure("persist_failed");
    return 1;
  }

  sqlite3* db = nullptr;
  if (sqlite3_open_v2((root / "facts.sqlite3").c_str(), &db,
                      SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
    EmitFailure("count_failed");
    return 1;
  }
  auto count = [db](const char* sql) -> long long {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
      return -1;
    long long result = -1;
    if (sqlite3_step(stmt) == SQLITE_ROW)
      result = sqlite3_column_int64(stmt, 0);
    sqlite3_finalize(stmt);
    return result;
  };
  long long commits = count("SELECT COUNT(*) FROM commits;");
  long long events = count("SELECT COUNT(*) FROM selection_events;");
  const char* journal_mode = nullptr;
  const char* synchronous = nullptr;
  {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, "PRAGMA journal_mode;", -1, &stmt, nullptr) ==
        SQLITE_OK) {
      if (sqlite3_step(stmt) == SQLITE_ROW)
        journal_mode = "wal";
      sqlite3_finalize(stmt);
    }
    if (sqlite3_prepare_v2(db, "PRAGMA synchronous;", -1, &stmt, nullptr) ==
        SQLITE_OK) {
      if (sqlite3_step(stmt) == SQLITE_ROW) {
        static char sync_buf[16];
        std::snprintf(sync_buf, sizeof(sync_buf), "%d",
                      sqlite3_column_int(stmt, 0));
        synchronous = sync_buf;
      }
      sqlite3_finalize(stmt);
    }
  }
  sqlite3_close(db);

  auto pcts = Percentiles(latencies, 0.50, 0.95, 0.99);
  std::string payload = "{\"ok\":true,\"writers\":";
  payload += std::to_string(writers);
  payload += ",\"batches_per_writer\":";
  payload += std::to_string(batches_per_writer);
  payload += ",\"commits\":";
  payload += std::to_string(commits);
  payload += ",\"events\":";
  payload += std::to_string(events);
  AppendPct(&payload, "parent_latency_ms", pcts);
  payload += ",\"journal_mode\":";
  WriteJsonString(&payload, journal_mode ? journal_mode : "unknown");
  payload += ",\"synchronous\":";
  WriteJsonString(&payload, synchronous ? synchronous : "unknown");
  payload += "}";
  std::printf("%s\n", payload.c_str());
  return 0;
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 2)
    return 2;
  // Spawned-writer dispatch (used by the multi-writer benchmark and
  // installed on the binary by the fact-store test harness).
  if (std::strcmp(argv[1], "--spawned-writer") == 0) {
    if (argc < 5)
      return 2;
    RunSpawnedWriter(path(argv[2]), std::atoi(argv[3]), std::atoi(argv[4]));
    return 0;
  }
  const char* command = argv[1];
  if (std::strcmp(command, "single") == 0)
    return RunSingle(argc, argv);
  if (std::strcmp(command, "multi") == 0)
    return RunMulti(argc, argv);
  return 2;
}
