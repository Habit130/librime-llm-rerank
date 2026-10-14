//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include "input_archive_producer.h"

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <utility>

#include <rapidjson/stringbuffer.h>
#include <rapidjson/writer.h>

namespace rime {
namespace {

constexpr int kMaxEventBytes = 65536;
constexpr int kFreshnessMs = 2000;
constexpr int kHeartbeatMs = 500;
constexpr int kConnectTimeoutMs = 1000;
constexpr int kMaxRetries = 3;
constexpr int kBatchSize = 64;

const char* kDenied[] = {
    "cloudstorage",   "dropbox",        "onedrive",
    "mobile documents", "icloud",       "google drive",
    "com~apple~clouddocs", "box sync",  "synologydrive",
};

std::atomic<int> g_secure_override{-1};

string Lower(string value) {
  for (char& ch : value) {
    if (ch >= 'A' && ch <= 'Z')
      ch = static_cast<char>(ch - 'A' + 'a');
  }
  return value;
}

bool DeniedComponent(const string& part) {
  const string folded = Lower(part);
  for (const char* denied : kDenied) {
    if (folded == denied)
      return true;
  }
  return false;
}

bool ExistingChainSafe(const string& path) {
  if (path.empty() || path[0] != '/')
    return false;
  const size_t leaf = path.rfind('/');
  if (leaf == string::npos || leaf == 0)
    return false;
  string current;
  size_t cursor = 1;
  while (cursor < path.size()) {
    size_t slash = path.find('/', cursor);
    if (slash == string::npos)
      slash = path.size();
    const string part = path.substr(cursor, slash - cursor);
    cursor = slash + 1;
    if (part.empty() || part == ".")
      continue;
    if (part == ".." || DeniedComponent(part))
      return false;
    current.push_back('/');
    current += part;
    struct stat info;
    if (lstat(current.c_str(), &info) != 0) {
      if (errno == ENOENT)
        continue;
      return false;
    }
    if (S_ISLNK(info.st_mode))
      return false;
    const bool is_leaf = current.size() == path.size();
    if (!is_leaf && !S_ISDIR(info.st_mode))
      return false;
  }
  return true;
}

int64_t SteadyNs() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

void JsonString(rapidjson::Writer<rapidjson::StringBuffer>* writer,
                const string& value) {
  writer->String(value.data(), static_cast<rapidjson::SizeType>(value.size()));
}

void AddToken(rapidjson::Writer<rapidjson::StringBuffer>* writer,
              const char* key,
              const string& value) {
  writer->Key(key);
  if (value.empty())
    writer->Null();
  else
    JsonString(writer, value);
}

string SerializeObservation(const InputArchiveObservation& item) {
  rapidjson::StringBuffer buffer;
  rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
  writer.StartObject();
  writer.Key("envelope_version");
  writer.Int(1);
  writer.Key("content_version");
  writer.Int(1);
  writer.Key("observation_kind");
  JsonString(&writer, item.observation_kind);
  writer.Key("schema_id");
  JsonString(&writer, item.schema_id.empty() ? "unknown" : item.schema_id);
  writer.Key("source_instance_id");
  JsonString(&writer, item.source_instance_id);
  writer.Key("source_local_sequence");
  writer.Int64(item.source_local_sequence);
  writer.Key("process_id");
  JsonString(&writer, item.process_id);
  AddToken(&writer, "update_id", item.update_id);
  AddToken(&writer, "parent_update_id", item.parent_update_id);
  AddToken(&writer, "continuity_segment_id", item.continuity_segment_id);
  writer.Key("outcome");
  JsonString(&writer, item.outcome.empty() ? "unknown" : item.outcome);
  if (!item.reason.empty()) {
    writer.Key("reason");
    JsonString(&writer, item.reason);
  }
  writer.Key("eligibility");
  JsonString(&writer, item.eligibility);
  writer.Key("host_persistence");
  writer.String("unknown");
  if (item.observation_kind == "plugin_observation") {
    writer.Key("plugin_observation_version");
    writer.Int(item.plugin_observation_version);
    writer.Key("plugin_stage");
    JsonString(&writer, item.plugin_stage);
    writer.Key("association_role");
    JsonString(&writer, item.association_role);
    writer.Key("association_read");
    JsonString(&writer, item.association_read);
    AddToken(&writer, "referenced_source_id", item.referenced_source_id);
    AddToken(&writer, "referenced_process_id", item.referenced_process_id);
    AddToken(&writer, "referenced_update_id", item.referenced_update_id);
    AddToken(&writer, "referenced_segment_id", item.referenced_segment_id);
    writer.Key("coverage");
    JsonString(&writer, item.coverage);
    writer.Key("coverage_basis");
    JsonString(&writer, item.coverage_basis);
    writer.Key("target_membership");
    JsonString(&writer, item.target_membership);
    if (item.captured_candidate_count >= 0) {
      writer.Key("captured_candidate_count");
      writer.Int(item.captured_candidate_count);
    }
    if (item.group_member_count >= 0) {
      writer.Key("group_member_count");
      writer.Int(item.group_member_count);
    }
    AddToken(&writer, "window_id", item.window_id);
    AddToken(&writer, "group_id", item.group_id);
    AddToken(&writer, "plan_identity", item.plan_identity);
    writer.Key("lm_request_state");
    JsonString(&writer, item.lm_request_state);
    if (item.lm_request_state != "no_request")
      AddToken(&writer, "lm_request_id", item.lm_request_id);
    writer.Key("apply_state");
    JsonString(&writer, item.apply_state);
    writer.Key("submission");
    JsonString(&writer, item.submission);
    writer.Key("order_changed");
    writer.Bool(item.order_changed);
    writer.Key("emission_matches_upstream");
    writer.Bool(item.emission_matches_upstream);
    writer.Key("score_weight_state");
    JsonString(&writer, item.score_weight_state);
    writer.Key("score_quality_state");
    JsonString(&writer, item.score_quality_state);
    writer.Key("score_lm_state");
    JsonString(&writer, item.score_lm_state);
    writer.Key("score_evidence_state");
    JsonString(&writer, item.score_evidence_state);
    writer.Key("payload");
    writer.StartObject();
    writer.Key("text");
    JsonString(&writer, item.payload_text);
    writer.Key("preceding_text");
    JsonString(&writer, item.preceding_text);
    writer.Key("input");
    JsonString(&writer, item.input_text);
    writer.Key("candidates");
    writer.StartArray();
    for (const auto& candidate : item.candidates) {
      writer.StartObject();
      writer.Key("merge_order");
      writer.Int(candidate.merge_order);
      writer.Key("start");
      writer.Int(candidate.start);
      writer.Key("end");
      writer.Int(candidate.end);
      writer.Key("category");
      JsonString(&writer, candidate.category);
      writer.Key("text");
      JsonString(&writer, candidate.text);
      writer.Key("weight_state");
      writer.String(candidate.weight_known ? "observed" : "unknown");
      if (candidate.weight_known) {
        writer.Key("weight");
        writer.Double(candidate.weight);
        writer.Key("weight_unit");
        writer.String("log_weight");
      }
      writer.Key("quality_state");
      writer.String(candidate.quality_known ? "observed" : "unknown");
      if (candidate.quality_known) {
        writer.Key("quality");
        writer.Double(candidate.quality);
        writer.Key("quality_unit");
        writer.String("probability");
      }
      writer.Key("lm_state");
      writer.String(candidate.lm_known ? "observed" : "unknown");
      if (candidate.lm_known) {
        writer.Key("lm_score");
        writer.Double(candidate.lm_score);
        writer.Key("lm_unit");
        writer.String("log_weight");
      }
      writer.Key("evidence_state");
      writer.String(candidate.evidence_known ? "observed" : "unknown");
      if (candidate.evidence_known) {
        writer.Key("retrieval_evidence");
        writer.Double(candidate.evidence);
        writer.Key("evidence_unit");
        writer.String("log_evidence");
      }
      writer.EndObject();
    }
    writer.EndArray();
    writer.Key("groups");
    writer.StartArray();
    for (const auto& group : item.groups) {
      writer.StartObject();
      writer.Key("identity");
      JsonString(&writer, group.identity);
      writer.Key("start");
      writer.Int(group.start);
      writer.Key("end");
      writer.Int(group.end);
      writer.Key("category");
      JsonString(&writer, group.category);
      writer.Key("plan_complete");
      writer.Bool(group.plan_complete);
      writer.Key("member_indexes");
      writer.StartArray();
      for (int index : group.member_indexes)
        writer.Int(index);
      writer.EndArray();
      writer.EndObject();
    }
    writer.EndArray();
    writer.Key("upstream_order");
    writer.StartArray();
    for (int index : item.upstream_order)
      writer.Int(index);
    writer.EndArray();
    writer.Key("emission_order");
    writer.StartArray();
    for (int index : item.emission_order)
      writer.Int(index);
    writer.EndArray();
    writer.EndObject();
  }
  writer.EndObject();
  return string(buffer.GetString(), buffer.GetSize());
}

string Frame(const string& json_object) {
  const uint32_t size = static_cast<uint32_t>(json_object.size());
  string frame(4, '\0');
  frame[0] = static_cast<char>((size >> 24) & 0xff);
  frame[1] = static_cast<char>((size >> 16) & 0xff);
  frame[2] = static_cast<char>((size >> 8) & 0xff);
  frame[3] = static_cast<char>(size & 0xff);
  frame += json_object;
  return frame;
}

string RequestFrame(const string& op, const string& body_json) {
  string json = "{\"interface_version\":\"input-archive-v1\",\"envelope_version\":1,"
                "\"content_version\":1,\"op\":\"";
  json += op;
  json += "\",\"request_id\":\"plugin-worker\",\"body\":";
  json += body_json;
  json += "}";
  return Frame(json);
}

std::mutex g_cwd_lock;

int ConnectSocket(const string& path, int timeout_ms) {
  if (path.empty() || path[0] != '/')
    return -1;
  const size_t slash = path.rfind('/');
  if (slash == string::npos || slash + 1 >= path.size())
    return -1;
  const string directory = path.substr(0, slash);
  const string name = path.substr(slash + 1);
  if (name.size() >= sizeof(sockaddr_un::sun_path))
    return -1;
  int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0)
    return -1;
  int nosigpipe = 1;
#ifdef SO_NOSIGPIPE
  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &nosigpipe, sizeof(nosigpipe));
#endif
  sockaddr_un addr;
  std::memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  std::memcpy(addr.sun_path, name.data(), name.size());
#ifdef __APPLE__
  addr.sun_len = static_cast<unsigned char>(offsetof(sockaddr_un, sun_path) + name.size() + 1);
#endif
  const socklen_t address_length =
      static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + name.size() + 1);
  bool connected = false;
  {
    std::lock_guard<std::mutex> cwd(g_cwd_lock);
    char previous[PATH_MAX];
    if (!getcwd(previous, sizeof(previous))) {
      close(fd);
      return -1;
    }
    if (chdir(directory.c_str()) == 0) {
      const int flags = fcntl(fd, F_GETFL, 0);
      fcntl(fd, F_SETFL, flags | O_NONBLOCK);
      const int rc = ::connect(fd, reinterpret_cast<sockaddr*>(&addr), address_length);
      connected = rc == 0 || errno == EINPROGRESS || errno == EAGAIN;
      chdir(previous);
    }
  }
  if (!connected) {
    close(fd);
    return -1;
  }
  fd_set writes;
  FD_ZERO(&writes);
  FD_SET(fd, &writes);
  timeval tv;
  tv.tv_sec = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;
  int ready = select(fd + 1, nullptr, &writes, nullptr, &tv);
  if (ready <= 0) {
    close(fd);
    return -1;
  }
  int error = 0;
  socklen_t length = sizeof(error);
  if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) != 0 || error != 0) {
    close(fd);
    return -1;
  }
  fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) & ~O_NONBLOCK);
  struct timeval sock_tv;
  sock_tv.tv_sec = timeout_ms / 1000;
  sock_tv.tv_usec = (timeout_ms % 1000) * 1000;
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &sock_tv, sizeof(sock_tv));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &sock_tv, sizeof(sock_tv));
  return fd;
}

bool WriteAll(int fd, const string& bytes) {
  size_t sent = 0;
  while (sent < bytes.size()) {
    ssize_t n = ::send(fd, bytes.data() + sent, bytes.size() - sent, 0);
    if (n < 0) {
      if (errno == EINTR)
        continue;
      return false;
    }
    if (n == 0)
      return false;
    sent += static_cast<size_t>(n);
  }
  return true;
}

bool ReadExact(int fd, char* data, size_t size) {
  size_t got = 0;
  while (got < size) {
    ssize_t n = ::recv(fd, data + got, size - got, 0);
    if (n < 0) {
      if (errno == EINTR)
        continue;
      return false;
    }
    if (n == 0)
      return false;
    got += static_cast<size_t>(n);
  }
  return true;
}

string Exchange(const string& socket_path, const string& frame) {
  int fd = ConnectSocket(socket_path, kConnectTimeoutMs);
  if (fd < 0)
    return "";
  bool ok = WriteAll(fd, frame);
  string response;
  if (ok) {
    char header[4];
    if (ReadExact(fd, header, 4)) {
      uint32_t size = (static_cast<unsigned char>(header[0]) << 24) |
                      (static_cast<unsigned char>(header[1]) << 16) |
                      (static_cast<unsigned char>(header[2]) << 8) |
                      static_cast<unsigned char>(header[3]);
      if (size > 0 && size <= 4 * 1024 * 1024) {
        response.resize(size);
        if (!ReadExact(fd, &response[0], size))
          response.clear();
      }
    }
  }
  close(fd);
  return response;
}

bool ResponseUnavailable(const string& response) {
  return response.empty() ||
         response.find("\"collector_unavailable\"") != string::npos ||
         response.find("\"ok\":false") != string::npos &&
             response.find("collector_unavailable") != string::npos;
}

string JsonFindString(const string& json, const string& key) {
  const string pattern = "\"" + key + "\":\"";
  size_t pos = json.find(pattern);
  if (pos == string::npos)
    return "";
  pos += pattern.size();
  string value;
  for (size_t i = pos; i < json.size(); ++i) {
    if (json[i] == '\\' && i + 1 < json.size()) {
      value.push_back(json[++i]);
      continue;
    }
    if (json[i] == '"')
      break;
    value.push_back(json[i]);
  }
  return value;
}

int JsonFindInt(const string& json, const string& key, int fallback) {
  const string pattern = "\"" + key + "\":";
  size_t pos = json.find(pattern);
  if (pos == string::npos)
    return fallback;
  pos += pattern.size();
  if (pos < json.size() && json[pos] == '"')
    return fallback;
  return std::atoi(json.c_str() + pos);
}

using SecureFn = unsigned char (*)();

bool PlatformSecureInput() {
  static SecureFn fn = nullptr;
  static bool resolved = false;
  if (!resolved) {
    void* carbon = dlopen(
        "/System/Library/Frameworks/Carbon.framework/Carbon", RTLD_LAZY);
    if (carbon)
      fn = reinterpret_cast<SecureFn>(dlsym(carbon, "IsSecureEventInputEnabled"));
    resolved = true;
  }
  if (!fn)
    return true;  // unobservable gate fails closed for text admission
  return fn() != 0;
}

bool HighStage(const string& stage) {
  return stage == "commit" || stage == "cancellation" || stage == "retraction" ||
         stage == "loss" || stage == "exclusion";
}

}  // namespace

int InputArchiveBudgetBytes(const InputArchiveObservation& observation) {
  int bytes = 64;
  auto add = [&bytes](const string& value) { bytes += static_cast<int>(value.size()); };
  add(observation.observation_kind);
  add(observation.plugin_stage);
  add(observation.schema_id);
  add(observation.source_instance_id);
  add(observation.process_id);
  add(observation.payload_text);
  add(observation.preceding_text);
  add(observation.input_text);
  add(observation.plan_identity);
  add(observation.lm_request_id);
  for (const auto& candidate : observation.candidates) {
    add(candidate.text);
    add(candidate.category);
    bytes += 32;
  }
  for (const auto& group : observation.groups) {
    add(group.identity);
    add(group.category);
    bytes += 16;
  }
  return bytes;
}

struct InputArchiveProducer::Impl {
  Impl(string socket_path, string source_instance_id)
      : socket_path(std::move(socket_path)),
        source_instance_id(std::move(source_instance_id)) {
    RefreshDestination();
    worker = std::thread([this] { WorkerLoop(); });
  }

  ~Impl() {
    stop.store(true, std::memory_order_release);
    if (worker.joinable())
      worker.join();
  }

  void RefreshDestination() {
    const bool safe = !socket_path.empty() && socket_path[0] == '/' &&
                      ExistingChainSafe(socket_path);
    destination_safe.store(safe, std::memory_order_release);
  }

  bool PolicyAllows() const {
    if (!policy_valid.load(std::memory_order_acquire))
      return false;
    if (observed_desired.load(std::memory_order_acquire) != 2)
      return false;
    const int64_t seen = observed_at_ns.load(std::memory_order_acquire);
    if (seen <= 0)
      return false;
    return SteadyNs() - seen <= static_cast<int64_t>(kFreshnessMs) * 1000000LL;
  }

  string PolicyCode() const {
    if (!policy_valid.load(std::memory_order_acquire))
      return "policy_not_effective";
    const int desired = observed_desired.load(std::memory_order_acquire);
    if (desired == 1 || desired == 3)
      return "capture_disabled";
    return "policy_not_effective";
  }

  InputArchiveAdmission TryAdmit(InputArchiveObservation observation) {
    InputArchiveAdmission result;
    result.durable = false;
    if (!destination_safe.load(std::memory_order_acquire)) {
      result.code = "unsafe_root";
      return result;
    }
    observation.binding_generation =
        binding_generation.load(std::memory_order_acquire);
    observation.budget_bytes = InputArchiveBudgetBytes(observation);
    if (observation.budget_bytes > kMaxEventBytes) {
      result.code = "event_too_large";
      return result;
    }
    if (observation.observation_kind != "loss_notice" && !PolicyAllows()) {
      result.code = PolicyCode();
      return result;
    }
    if (!mu.try_lock()) {
      contended.fetch_add(1, std::memory_order_relaxed);
      result.code = "queue_saturated";
      return result;
    }
    capture_seq += 1;
    result.capture_seq = capture_seq;
    const bool high = observation.observation_kind == "loss_notice" ||
                      observation.observation_kind == "exclusion_notice" ||
                      HighStage(observation.plugin_stage);
    auto fits = [this](int size) {
      return static_cast<int>(queue.size()) + 1 <= queue_count_limit.load() &&
             bytes + size <= queue_byte_limit.load();
    };
    if (fits(observation.budget_bytes)) {
      queue.push_back(std::move(observation));
      bytes += queue.back().budget_bytes;
      result.admitted = true;
      result.code = "admitted";
      mu.unlock();
      return result;
    }
    if (high) {
      for (size_t i = 0; i < queue.size(); ++i) {
        const bool old_high = queue[i].observation_kind == "loss_notice" ||
                              queue[i].observation_kind == "exclusion_notice" ||
                              HighStage(queue[i].plugin_stage);
        if (!old_high) {
          RememberLossLocked(std::move(queue[i]), "displaced_for_priority");
          bytes -= queue[i].budget_bytes;
          queue.erase(queue.begin() + static_cast<std::ptrdiff_t>(i));
          queue.push_back(std::move(observation));
          bytes += queue.back().budget_bytes;
          result.admitted = true;
          result.code = "admitted";
          mu.unlock();
          return result;
        }
      }
    }
    RememberLossLocked(std::move(observation), "queue_saturated");
    result.code = "queue_saturated";
    mu.unlock();
    return result;
  }

  void RememberLossLocked(InputArchiveObservation dropped, const char* reason) {
    InputArchiveObservation loss;
    loss.observation_kind = "loss_notice";
    loss.schema_id = "unknown";
    loss.source_instance_id = source_instance_id;
    loss.source_local_sequence = dropped.source_local_sequence;
    loss.process_id = dropped.process_id.empty() ? "loss" : dropped.process_id;
    loss.reason = reason;
    loss.eligibility = "excluded";
    loss.binding_generation = dropped.binding_generation;
    loss.budget_bytes = 128;
    losses.push_back(std::move(loss));
    if (losses.size() > 64)
      losses.erase(losses.begin(), losses.end() - 64);
    known_dropped += 1;
  }

  void AbandonQueue() {
    std::lock_guard<std::mutex> guard(mu);
    queue.clear();
    losses.clear();
    bytes = 0;
    binding_generation.fetch_add(1, std::memory_order_acq_rel);
  }

  void WorkerLoop() {
    while (!stop.load(std::memory_order_acquire)) {
      string hold;
      {
        std::lock_guard<std::mutex> guard(mu);
        hold = hold_fifo;
      }
      if (!hold.empty()) {
        BlockFifo(hold);
        continue;
      }
      PollPolicy();
      vector<InputArchiveObservation> batch;
      vector<InputArchiveObservation> loss_batch;
      int generation = binding_generation.load(std::memory_order_acquire);
      {
        std::lock_guard<std::mutex> guard(mu);
        worker_busy = true;
        loss_batch.swap(losses);
        size_t take = std::min(queue.size(), static_cast<size_t>(kBatchSize));
        batch.insert(batch.end(), queue.begin(), queue.begin() + take);
        queue.erase(queue.begin(), queue.begin() + take);
        for (const auto& item : batch)
          bytes -= item.budget_bytes;
      }
      if (!loss_batch.empty())
        SendLosses(loss_batch, generation);
      if (batch.empty()) {
        {
          std::lock_guard<std::mutex> guard(mu);
          worker_busy = false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }
      if (!SendBatch(batch, generation))
        Requeue(batch);
      std::lock_guard<std::mutex> guard(mu);
      worker_busy = false;
    }
  }

  void BlockFifo(const string& path) {
    int fd = open(path.c_str(), O_RDONLY | O_NONBLOCK);
    if (fd < 0)
      return;
    while (!stop.load(std::memory_order_acquire)) {
      string current;
      {
        std::lock_guard<std::mutex> guard(mu);
        current = hold_fifo;
      }
      if (current != path)
        break;
      fd_set reads;
      FD_ZERO(&reads);
      FD_SET(fd, &reads);
      timeval tv;
      tv.tv_sec = 0;
      tv.tv_usec = 50000;
      int ready = select(fd + 1, &reads, nullptr, nullptr, &tv);
      if (ready > 0) {
        char byte = 0;
        if (read(fd, &byte, 1) > 0)
          break;
      }
    }
    close(fd);
  }

  void PollPolicy() {
    int64_t token = 0;
    string path;
    string source;
    int declared = 0;
    {
      std::lock_guard<std::mutex> guard(poll_mu);
      const int64_t now = SteadyNs();
      if (last_poll_ns != 0 &&
          now - last_poll_ns < static_cast<int64_t>(kHeartbeatMs) * 1000000LL)
        return;
      last_poll_ns = now;
      token = ++poll_token;
      path = socket_path;
      source = source_instance_id;
      declared = observed_revision.load(std::memory_order_acquire);
    }
    RefreshDestination();
    if (!destination_safe.load(std::memory_order_acquire)) {
      std::lock_guard<std::mutex> guard(poll_mu);
      if (token == poll_token)
        policy_valid.store(false, std::memory_order_release);
      return;
    }
    string body = "{\"source_instance_id\":\"";
    body += source;
    body += "\",\"observed_revision\":";
    body += declared < 0 ? "0" : std::to_string(declared);
    body += "}";
    string response = Exchange(path, RequestFrame("policy_observe", body));
    std::lock_guard<std::mutex> guard(poll_mu);
    // An older in-flight poll must not clear a newer successful observation.
    if (token != poll_token)
      return;
    if (response.empty() || response.find("\"ok\":true") == string::npos) {
      policy_valid.store(false, std::memory_order_release);
      return;
    }
    const string desired = JsonFindString(response, "desired_policy");
    int code = 0;
    if (desired == "off")
      code = 1;
    else if (desired == "enabled")
      code = 2;
    else if (desired == "paused")
      code = 3;
    observed_desired.store(code, std::memory_order_release);
    observed_revision.store(JsonFindInt(response, "desired_revision", 0),
                            std::memory_order_release);
    observed_at_ns.store(SteadyNs(), std::memory_order_release);
    policy_valid.store(code != 0, std::memory_order_release);
  }

  bool SendBatch(const vector<InputArchiveObservation>& batch, int generation) {
    if (generation != binding_generation.load(std::memory_order_acquire))
      return true;  // dropped, do not retarget
    if (!destination_safe.load(std::memory_order_acquire))
      return true;
    string body = "{\"observations\":[";
    for (size_t i = 0; i < batch.size(); ++i) {
      if (i)
        body += ",";
      body += SerializeObservation(batch[i]);
    }
    body += "]}";
    string response = Exchange(socket_path, RequestFrame("admit_batch", body));
    if (ResponseUnavailable(response))
      return false;
    return true;
  }

  void SendLosses(const vector<InputArchiveObservation>& batch, int generation) {
    if (generation != binding_generation.load(std::memory_order_acquire))
      return;
    SendBatch(batch, generation);
  }

  void Requeue(vector<InputArchiveObservation> batch) {
    std::lock_guard<std::mutex> guard(mu);
    for (auto it = batch.rbegin(); it != batch.rend(); ++it) {
      if (it->binding_generation != binding_generation.load())
        continue;
      it->retries += 1;
      if (it->retries > kMaxRetries) {
        RememberLossLocked(std::move(*it), "requeue_saturated");
        continue;
      }
      if (static_cast<int>(queue.size()) + 1 > queue_count_limit.load() ||
          bytes + it->budget_bytes > queue_byte_limit.load()) {
        RememberLossLocked(std::move(*it), "requeue_saturated");
        continue;
      }
      bytes += it->budget_bytes;
      queue.insert(queue.begin(), std::move(*it));
    }
  }

  string socket_path;
  string source_instance_id;
  std::mutex mu;
  std::thread worker;
  vector<InputArchiveObservation> queue;
  vector<InputArchiveObservation> losses;
  int bytes = 0;
  int64_t capture_seq = 0;
  int known_dropped = 0;
  bool worker_busy = false;
  string hold_fifo;
  std::mutex poll_mu;
  int64_t poll_token = 0;
  int64_t last_poll_ns = 0;
  std::atomic<bool> stop{false};
  std::atomic<bool> destination_safe{false};
  std::atomic<int> binding_generation{1};
  std::atomic<int> queue_count_limit{256};
  std::atomic<int> queue_byte_limit{1048576};
  std::atomic<int> observed_desired{0};
  std::atomic<int> observed_revision{-1};
  std::atomic<int64_t> observed_at_ns{0};
  std::atomic<bool> policy_valid{false};
  std::atomic<int> contended{0};
};

void InputArchiveProducer::SetSecureInputOverrideForTesting(int mode) {
  g_secure_override.store(mode, std::memory_order_release);
}

bool InputArchiveProducer::SecureInputActive() {
  const int override = g_secure_override.load(std::memory_order_acquire);
  if (override == 0)
    return false;
  if (override > 0)
    return true;
  return PlatformSecureInput();
}

InputArchiveProducer::InputArchiveProducer(string socket_path,
                                           string source_instance_id)
    : impl_(new Impl(std::move(socket_path), std::move(source_instance_id))) {}

InputArchiveProducer::~InputArchiveProducer() = default;

InputArchiveAdmission InputArchiveProducer::TryAdmit(
    InputArchiveObservation observation) {
  return impl_->TryAdmit(std::move(observation));
}

const string& InputArchiveProducer::source_instance_id() const {
  return impl_->source_instance_id;
}

const string& InputArchiveProducer::socket_path() const {
  return impl_->socket_path;
}

int InputArchiveProducer::binding_generation() const {
  return impl_->binding_generation.load(std::memory_order_acquire);
}

bool InputArchiveProducer::destination_safe() const {
  return impl_->destination_safe.load(std::memory_order_acquire);
}

bool InputArchiveProducer::locally_effective() const {
  return destination_safe() && impl_->PolicyAllows();
}

void InputArchiveProducer::PollPolicyForTesting() {
  {
    std::lock_guard<std::mutex> guard(impl_->poll_mu);
    impl_->last_poll_ns = 0;
  }
  impl_->PollPolicy();
}

bool InputArchiveProducer::FlushForTesting(int timeout_ms) {
  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::milliseconds(timeout_ms);
  while (std::chrono::steady_clock::now() < deadline) {
    impl_->last_poll_ns = 0;
    bool idle = false;
    {
      std::lock_guard<std::mutex> guard(impl_->mu);
      idle = impl_->queue.empty() && impl_->losses.empty() && !impl_->worker_busy;
    }
    if (idle && impl_->policy_valid.load(std::memory_order_acquire))
      return true;
    if (idle)
      impl_->PollPolicy();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  std::lock_guard<std::mutex> guard(impl_->mu);
  return impl_->queue.empty() && impl_->losses.empty();
}

void InputArchiveProducer::SetQueueLimitsForTesting(int count, int bytes) {
  if (count > 0)
    impl_->queue_count_limit.store(count, std::memory_order_release);
  if (bytes > 0)
    impl_->queue_byte_limit.store(bytes, std::memory_order_release);
}

void InputArchiveProducer::HoldWorkerForTesting(const string& fifo) {
  std::lock_guard<std::mutex> guard(impl_->mu);
  impl_->hold_fifo = fifo;
}

void InputArchiveProducer::RetargetForTesting(const string& socket_path) {
  {
    std::lock_guard<std::mutex> guard(impl_->mu);
    impl_->queue.clear();
    impl_->losses.clear();
    impl_->bytes = 0;
    impl_->socket_path = socket_path;
    impl_->binding_generation.fetch_add(1, std::memory_order_acq_rel);
    impl_->policy_valid.store(false, std::memory_order_release);
  }
  impl_->RefreshDestination();
}

void InputArchiveProducer::AbandonQueue() {
  impl_->AbandonQueue();
}

}  // namespace rime
