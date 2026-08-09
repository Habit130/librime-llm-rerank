//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "recording_gap.h"

namespace rime {

namespace {

const char* kGapFileName = "recording_gap.json";

constexpr mode_t kFileMode = 0600;

// The values we emit are stable codes, counts and timestamps; a restrictive
// character class keeps the hand-rolled JSON emitter escaping-free. Any
// other content is refused (privacy + format safety).
bool IsSafeJsonValue(const string& value) {
  if (value.empty())
    return true;
  for (char ch : value) {
    bool ok = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
              (ch >= '0' && ch <= '9') || ch == '-' || ch == '_' || ch == '.';
    if (!ok)
      return false;
  }
  return true;
}

void AppendJsonString(std::string* out, const char* key,
                      const string& value) {
  out->append("\"");
  out->append(key);
  out->append("\":\"");
  out->append(value);
  out->append("\"");
}

void AppendJsonInt(std::string* out, const char* key, int64_t value) {
  out->append("\"");
  out->append(key);
  out->append("\":");
  out->append(std::to_string(value));
}

}  // namespace

bool RecordingGapRecord::Write(const path& root_dir) const {
  if (!IsSafeJsonValue(reason) || !IsSafeJsonValue(store_epoch))
    return false;
  std::string payload = "{";
  AppendJsonString(&payload, "gap_version", std::to_string(kGapVersion));
  payload.append(",");
  AppendJsonString(&payload, "reason", reason);
  payload.append(",");
  AppendJsonInt(&payload, "dropped_batches", dropped_batches);
  payload.append(",");
  AppendJsonInt(&payload, "dropped_events", dropped_events);
  payload.append(",");
  AppendJsonInt(&payload, "buffer_bytes", buffer_bytes);
  payload.append(",");
  AppendJsonInt(&payload, "first_occurred_at_ms", first_occurred_at_ms);
  payload.append(",");
  AppendJsonInt(&payload, "last_occurred_at_ms", last_occurred_at_ms);
  payload.append(",");
  AppendJsonString(&payload, "store_epoch", store_epoch);
  payload.append("}\n");

  path gap_path = root_dir / kGapFileName;
  // Exclusive-create the temp file with exact 0600, then atomic rename.
  // All paths are absolute (root_dir is), so a crash mid-write never leaks
  // the temp into the working directory.
  std::string tmp_name =
      (root_dir / (std::string(kGapFileName) + ".tmp-" +
                   std::to_string(getpid()))).c_str();
  int fd = open(tmp_name.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
                kFileMode);
  if (fd < 0) {
    // A stale temp from a crashed process: remove and retry once.
    if (errno == EEXIST &&
        unlink(tmp_name.c_str()) == 0) {
      fd = open(tmp_name.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
                kFileMode);
    }
    if (fd < 0)
      return false;
  }
  bool ok = true;
  if (fchmod(fd, kFileMode) != 0)
    ok = false;
  const char* data = payload.data();
  size_t remaining = payload.size();
  while (ok && remaining > 0) {
    ssize_t written = write(fd, data, remaining);
    if (written <= 0) {
      ok = false;
      break;
    }
    data += written;
    remaining -= static_cast<size_t>(written);
  }
  if (ok && fsync(fd) != 0)
    ok = false;
  close(fd);
  if (!ok) {
    unlink(tmp_name.c_str());
    return false;
  }
  if (rename(tmp_name.c_str(), gap_path.c_str()) != 0) {
    unlink(tmp_name.c_str());
    return false;
  }
  // Best-effort directory fsync; a failure leaves a valid renamed file.
  int dir_fd = open(root_dir.c_str(), O_RDONLY | O_NOFOLLOW);
  if (dir_fd >= 0) {
    fsync(dir_fd);
    close(dir_fd);
  }
  return true;
}

namespace {

// Minimal parser for the flat JSON the writer emits. Only our own fields are
// interpreted; malformed input returns false. Numbers are decimal int64,
// strings are quoted with the safe character class above.
bool ParseIntField(const char** cursor, int64_t* value) {
  const char* p = *cursor;
  bool negative = false;
  if (*p == '-') {
    negative = true;
    ++p;
  }
  if (*p < '0' || *p > '9')
    return false;
  long long parsed = 0;
  while (*p >= '0' && *p <= '9') {
    parsed = parsed * 10 + (*p - '0');
    ++p;
  }
  *cursor = p;
  *value = negative ? -parsed : parsed;
  return true;
}

bool ParseStringField(const char** cursor, string* value) {
  const char* p = *cursor;
  if (*p != '"')
    return false;
  ++p;
  string result;
  while (*p && *p != '"') {
    if (*p == '\\' || *p == '\n' || *p == '\r')
      return false;
    result.push_back(*p);
    ++p;
  }
  if (*p != '"')
    return false;
  *cursor = p + 1;
  *value = result;
  return true;
}

// Parses one `"key":value` pair; returns false on malformed input.
bool ParseField(const char** cursor, string* key, string* text) {
  const char* p = *cursor;
  while (*p == ' ' || *p == '\t')
    ++p;
  if (!ParseStringField(&p, key))
    return false;
  while (*p == ' ' || *p == '\t')
    ++p;
  if (*p != ':')
    return false;
  ++p;
  while (*p == ' ' || *p == '\t')
    ++p;
  const char* value_start = p;
  while (*p && *p != ',' && *p != '}')
    ++p;
  *text = string(value_start, p - value_start);
  *cursor = p;
  return true;
}

}  // namespace

bool RecordingGapRecord::Read(const path& root_dir, RecordingGapRecord* out) {
  path gap_path = root_dir / kGapFileName;
  struct stat st;
  if (lstat(gap_path.c_str(), &st) != 0) {
    if (errno == ENOENT)
      return false;  // no gap
    return false;    // cannot prove
  }
  if (S_ISLNK(st.st_mode) || !S_ISREG(st.st_mode) ||
      st.st_uid != getuid() || (st.st_mode & 0777) != kFileMode) {
        return false;
  }
  int fd = open(gap_path.c_str(), O_RDONLY | O_NOFOLLOW);
  if (fd < 0) {
        return false;
  }
  std::string payload;
  char buffer[4096];
  for (;;) {
    ssize_t n = read(fd, buffer, sizeof(buffer));
    if (n < 0) {
            close(fd);
      return false;
    }
    if (n == 0)
      break;
    payload.append(buffer, static_cast<size_t>(n));
  }
  close(fd);

  RecordingGapRecord record;
  const char* cursor = payload.c_str();
  if (*cursor != '{')
    return false;
  ++cursor;  // skip the opening brace
  bool have_version = false;
  bool have_reason = false;
  while (*cursor && *cursor != '}') {
    string key;
    string text;
    if (!ParseField(&cursor, &key, &text)) {
            return false;
    }
    if (key == "gap_version") {
      if (text.size() < 2 || text.front() != '"' || text.back() != '"') {
                return false;
      }
      int64_t version = 0;
      const char* cursor = text.c_str() + 1;
      if (!ParseIntField(&cursor, &version))
        return false;
      have_version = version == RecordingGapRecord::kGapVersion;
    } else if (key == "reason") {
      if (text.size() < 2 || text.front() != '"' || text.back() != '"') {
                return false;
      }
      record.reason = text.substr(1, text.size() - 2);
      have_reason = true;
    } else if (key == "dropped_batches") {
      const char* cursor = text.c_str();
      if (!ParseIntField(&cursor, &record.dropped_batches))
        return false;
    } else if (key == "dropped_events") {
      const char* cursor = text.c_str();
      if (!ParseIntField(&cursor, &record.dropped_events))
        return false;
    } else if (key == "buffer_bytes") {
      const char* cursor = text.c_str();
      if (!ParseIntField(&cursor, &record.buffer_bytes))
        return false;
    } else if (key == "first_occurred_at_ms") {
      const char* cursor = text.c_str();
      if (!ParseIntField(&cursor, &record.first_occurred_at_ms))
        return false;
    } else if (key == "last_occurred_at_ms") {
      const char* cursor = text.c_str();
      if (!ParseIntField(&cursor, &record.last_occurred_at_ms))
        return false;
    } else if (key == "store_epoch") {
      if (text.size() < 2 || text.front() != '"' || text.back() != '"') {
                return false;
      }
      record.store_epoch = text.substr(1, text.size() - 2);
    }
    if (*cursor == ',')
      ++cursor;
  }
  if (*cursor != '}' || !have_version || !have_reason) {
        return false;
  }
  *out = record;
  return true;
}

}  // namespace rime
