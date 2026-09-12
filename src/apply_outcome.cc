//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include "apply_outcome.h"

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstring>

namespace rime {
namespace {

bool SafeIdentity(const string& value) {
  if (value.empty() || value.size() > 1024)
    return false;
  for (unsigned char byte : value) {
      if (!((byte >= 'a' && byte <= 'z') || (byte >= 'A' && byte <= 'Z') ||
            (byte >= '0' && byte <= '9') || byte == '-' || byte == '_' ||
            byte == '.' || byte == ':' || byte == '+' || byte == '=' ||
            byte == '@' || byte == ',')) {
      return false;
    }
  }
  return true;
}

string JsonEscapeIdentity(const string& value) {
  string out;
  out.reserve(value.size());
  for (char c : value) {
    if (c == '"' || c == '\\')
      out.push_back('\\');
    out.push_back(c);
  }
  return out;
}

bool EnsureOwnerDir(const path& dir, bool chmod_0700) {
  struct stat st;
  if (lstat(dir.string().c_str(), &st) == 0) {
    if (S_ISLNK(st.st_mode) || !S_ISDIR(st.st_mode))
      return false;
    if (st.st_uid != getuid())
      return false;
    if (chmod_0700 && (st.st_mode & 0777) != 0700)
      chmod(dir.string().c_str(), 0700);
    return true;
  }
  return mkdir(dir.string().c_str(), 0700) == 0;
}

}  // namespace

bool IsAckApplyState(const string& apply_state) {
  return apply_state == kApplyStateApplied ||
         apply_state == kApplyStateFallback;
}

bool AppendClientApplyRecord(const path& facts_root,
                             const WindowApplyRecord& record) {
  if (facts_root.empty() || !IsAckApplyState(record.apply_state))
    return false;
  if (record.request_ids.empty())
    return true;
  if (!record.plan_identity.empty() && !SafeIdentity(record.plan_identity))
    return false;
  if (!record.config_identity.empty() &&
      !SafeIdentity(record.config_identity))
    return false;
  for (const auto& request_id : record.request_ids) {
    if (!SafeIdentity(request_id))
      return false;
  }
  path traces_dir = facts_root / "traces";
  if (!EnsureOwnerDir(facts_root, false) || !EnsureOwnerDir(traces_dir, true))
    return false;
  path file = traces_dir / "client_apply.jsonl";
  string json = "{\"apply_state\":\"";
  json += record.apply_state;
  json += "\",\"request_ids\":[";
  for (size_t i = 0; i < record.request_ids.size(); ++i) {
    if (i > 0)
      json += ",";
    json += "\"";
    json += JsonEscapeIdentity(record.request_ids[i]);
    json += "\"";
  }
  json += "]";
  if (!record.plan_identity.empty()) {
    json += ",\"plan_identity\":\"";
    json += JsonEscapeIdentity(record.plan_identity);
    json += "\"";
  }
  if (!record.config_identity.empty()) {
    json += ",\"config_identity\":\"";
    json += JsonEscapeIdentity(record.config_identity);
    json += "\"";
  }
  json += "}\n";
  const int fd = open(file.string().c_str(),
                      O_WRONLY | O_CREAT | O_APPEND | O_NOFOLLOW, 0600);
  if (fd < 0)
    return false;
  struct stat st;
  if (fstat(fd, &st) != 0 || S_ISLNK(st.st_mode) || !S_ISREG(st.st_mode) ||
      st.st_uid != getuid()) {
    close(fd);
    return false;
  }
  if (st.st_size > 1024 * 1024) {
    close(fd);
    return false;
  }
  const ssize_t wrote = write(fd, json.data(), json.size());
  if (wrote < 0 || static_cast<size_t>(wrote) != json.size()) {
    close(fd);
    return false;
  }
  fsync(fd);
  close(fd);
  chmod(file.string().c_str(), 0600);
  return true;
}

}  // namespace rime
