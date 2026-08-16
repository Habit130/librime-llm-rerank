//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <fcntl.h>
#include <poll.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <initializer_list>

#include <rapidjson/document.h>
#include <rime/candidate.h>
#include <rime/common.h>

#include "llm_scorer.h"

namespace rime {
namespace {

constexpr int kLlmScoringProtocolVersion = 2;
constexpr size_t kMaximumResponseBytes = 64 * 1024;

enum class WaitStatus { kReady, kTimeout, kError };

class SystemConnectSyscalls : public ConnectSyscalls {
 public:
  SocketCallResult Connect(int fd,
                           const struct sockaddr* address,
                           socklen_t address_size) override {
    const int result = connect(fd, address, address_size);
    return {result, result < 0 ? errno : 0};
  }

  SocketCallResult Poll(int fd,
                        short events,
                        int timeout_ms,
                        short* returned_events) override {
    struct pollfd poll_fd{fd, events, 0};
    const int result = poll(&poll_fd, 1, timeout_ms);
    if (returned_events)
      *returned_events = poll_fd.revents;
    return {result, result < 0 ? errno : 0};
  }

  SocketCallResult GetSocketError(int fd, int* socket_error) override {
    socklen_t socket_error_size = sizeof(*socket_error);
    const int result =
        getsockopt(fd, SOL_SOCKET, SO_ERROR, socket_error, &socket_error_size);
    return {result, result < 0 ? errno : 0};
  }
};

WaitStatus WaitFor(int fd,
                   short events,
                   std::chrono::steady_clock::time_point deadline,
                   ConnectSyscalls* syscalls) {
  if (!syscalls)
    return WaitStatus::kError;
  while (true) {
    const auto remaining =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - std::chrono::steady_clock::now());
    if (remaining.count() <= 0)
      return WaitStatus::kTimeout;
    short returned_events = 0;
    const SocketCallResult call = syscalls->Poll(
        fd, events, static_cast<int>(remaining.count()), &returned_events);
    if (call.result > 0) {
      if (returned_events & (events | POLLHUP | POLLERR))
        return WaitStatus::kReady;
      return WaitStatus::kError;
    }
    if (call.result == 0)
      return WaitStatus::kTimeout;
    if (call.error != EINTR)
      return WaitStatus::kError;
  }
}

SystemConnectSyscalls& DefaultConnectSyscalls() {
  static SystemConnectSyscalls syscalls;
  return syscalls;
}

void LogFailure(const char* code, const char* phase, size_t candidate_count) {
  LOG(WARNING) << "llm_scorer: code=" << code << " phase=" << phase
               << " protocol_version=" << kLlmScoringProtocolVersion
               << " candidate_count=" << candidate_count;
}

static string JsonEscape(const string& s) {
  string out;
  out.reserve(s.size() + 16);
  for (char c : s) {
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default:
        if ((unsigned char)c < 0x20) {
          char buf[8];
          snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)c);
          out += buf;
        } else {
          out += c;
        }
    }
  }
  return out;
}

static string BuildRequest(const string& context,
                           const vector<string>& candidates,
                           const string& request_id,
                           const string& plan_identity,
                           const string& baseline_policy_id) {
  string json = "{\"version\":" + std::to_string(kLlmScoringProtocolVersion) +
                ",\"request_id\":\"" + JsonEscape(request_id) +
                "\",\"plan_identity\":\"" + JsonEscape(plan_identity) +
                "\",\"baseline_policy_id\":\"" +
                JsonEscape(baseline_policy_id) + "\",\"context\":\"";
  json += JsonEscape(context);
  json += "\",\"candidates\":[";
  for (size_t i = 0; i < candidates.size(); i++) {
    if (i > 0)
      json += ",";
    json += "\"";
    json += JsonEscape(candidates[i]);
    json += "\"";
  }
  json += "]}\n";
  return json;
}

bool HasExactMembers(const rapidjson::Value& object,
                     std::initializer_list<const char*> names) {
  if (!object.IsObject() || object.MemberCount() != names.size())
    return false;
  for (const char* name : names) {
    if (!object.HasMember(name))
      return false;
  }
  return true;
}

static bool ParseScores(const string& response,
                        const string& expected_request_id,
                        const string& expected_plan_identity,
                        size_t expected_count,
                        vector<double>* scores,
                        const char** error_code) {
  const size_t newline = response.find('\n');
  // One terminal LF is the only framing byte allowed after the JSON document.
  if (newline == string::npos || newline == 0 ||
      newline != response.size() - 1 || response[newline - 1] != '}' ||
      response.find('\0') < newline) {
    *error_code = "invalid_protocol";
    return false;
  }

  rapidjson::Document document;
  document.Parse<rapidjson::kParseNanAndInfFlag>(response.data(), newline);
  if (document.HasParseError() || !document.IsObject()) {
    *error_code = "invalid_protocol";
    return false;
  }
  if (!document.HasMember("version") || !document["version"].IsInt() ||
      document["version"].GetInt() != kLlmScoringProtocolVersion ||
      !document.HasMember("request_id") || !document["request_id"].IsString() ||
      !document.HasMember("plan_identity") ||
      !document["plan_identity"].IsString()) {
    *error_code = "invalid_protocol";
    return false;
  }

  const string request_id(document["request_id"].GetString(),
                          document["request_id"].GetStringLength());
  if (request_id != expected_request_id) {
    *error_code = "request_identity_mismatch";
    return false;
  }
  const string plan_identity(document["plan_identity"].GetString(),
                             document["plan_identity"].GetStringLength());
  if (plan_identity != expected_plan_identity) {
    *error_code = "plan_identity_mismatch";
    return false;
  }
  if (document.HasMember("error")) {
    if (!HasExactMembers(document,
                         {"version", "request_id", "plan_identity", "error"})) {
      *error_code = "invalid_protocol";
      return false;
    }
    const auto& error = document["error"];
    if (!HasExactMembers(error, {"code", "message", "occurred_at", "retryable",
                                 "phase", "remediation", "cause"}) ||
        !error["code"].IsString() || !error["message"].IsString() ||
        !error["occurred_at"].IsString() || !error["retryable"].IsBool() ||
        !error["phase"].IsString() || !error["remediation"].IsString() ||
        !error["cause"].IsNull()) {
      *error_code = "invalid_protocol";
      return false;
    }
    *error_code = "daemon_error";
    return false;
  }
  if (!HasExactMembers(document,
                       {"version", "request_id", "plan_identity", "scores"}) ||
      !document["scores"].IsArray()) {
    *error_code = "invalid_protocol";
    return false;
  }

  const auto& values = document["scores"].GetArray();
  if (values.Size() != expected_count) {
    *error_code = "score_count_mismatch";
    return false;
  }
  vector<double> parsed_scores;
  parsed_scores.reserve(values.Size());
  for (const auto& value : values) {
    if (!value.IsNumber() || !std::isfinite(value.GetDouble())) {
      *error_code = "non_finite_score";
      return false;
    }
    parsed_scores.push_back(value.GetDouble());
  }
  *scores = std::move(parsed_scores);
  return true;
}

}  // namespace

NonBlockingConnectStatus ConnectNonBlockingWithDeadline(
    int fd,
    const struct sockaddr* address,
    socklen_t address_size,
    std::chrono::steady_clock::time_point deadline,
    ConnectSyscalls* syscalls) {
  if (!syscalls)
    return NonBlockingConnectStatus::kError;
  bool completion_pending = false;
  while (std::chrono::steady_clock::now() < deadline) {
    if (!completion_pending) {
      const SocketCallResult call =
          syscalls->Connect(fd, address, address_size);
      if (call.result == 0 || call.error == EISCONN)
        return NonBlockingConnectStatus::kConnected;
      if (call.error == EAGAIN || call.error == EWOULDBLOCK) {
        const WaitStatus wait = WaitFor(fd, POLLOUT, deadline, syscalls);
        if (wait == WaitStatus::kTimeout)
          return NonBlockingConnectStatus::kTimeout;
        if (wait == WaitStatus::kError)
          return NonBlockingConnectStatus::kError;
        continue;
      }
      if (call.error != EINTR && call.error != EINPROGRESS &&
          call.error != EALREADY) {
        return NonBlockingConnectStatus::kError;
      }
      completion_pending = true;
    }

    const WaitStatus wait = WaitFor(fd, POLLOUT, deadline, syscalls);
    if (wait == WaitStatus::kTimeout)
      return NonBlockingConnectStatus::kTimeout;
    if (wait == WaitStatus::kError)
      return NonBlockingConnectStatus::kError;

    int socket_error = 0;
    while (true) {
      const SocketCallResult call = syscalls->GetSocketError(fd, &socket_error);
      if (call.result == 0)
        break;
      if (call.error != EINTR && call.error != EAGAIN &&
          call.error != EWOULDBLOCK) {
        return NonBlockingConnectStatus::kError;
      }
      if (std::chrono::steady_clock::now() >= deadline)
        return NonBlockingConnectStatus::kTimeout;
    }
    if (socket_error == 0 || socket_error == EISCONN)
      return NonBlockingConnectStatus::kConnected;
    if (socket_error != EINPROGRESS && socket_error != EALREADY &&
        socket_error != EAGAIN && socket_error != EWOULDBLOCK) {
      return NonBlockingConnectStatus::kError;
    }
  }
  return NonBlockingConnectStatus::kTimeout;
}

bool ExchangeJson(const string& socket_path,
                  const string& request_json,
                  int deadline_ms,
                  string* response) {
  if (!response)
    return false;
  if (deadline_ms <= 0) {
    LogFailure("deadline_invalid", "score", 0);
    return false;
  }
  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::milliseconds(deadline_ms);
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    LogFailure("socket_failed", "connect", 0);
    return false;
  }

  struct sockaddr_un addr;
  memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  if (socket_path.size() >= sizeof(addr.sun_path)) {
    close(fd);
    LogFailure("socket_path_invalid", "connect", 0);
    return false;
  }
  strncpy(addr.sun_path, socket_path.c_str(), sizeof(addr.sun_path) - 1);

  const int flags = fcntl(fd, F_GETFL, 0);
  if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
    close(fd);
    LogFailure("socket_setup_failed", "connect", 0);
    return false;
  }
#ifdef SO_NOSIGPIPE
  int no_sigpipe = 1;
  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe, sizeof(no_sigpipe));
#endif

  const NonBlockingConnectStatus connect_status =
      ConnectNonBlockingWithDeadline(
          fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr), deadline,
          &DefaultConnectSyscalls());
  if (connect_status != NonBlockingConnectStatus::kConnected) {
    close(fd);
    LogFailure(connect_status == NonBlockingConnectStatus::kTimeout
                   ? "deadline_exceeded"
                   : "connection_failed",
               "connect", 0);
    return false;
  }

  size_t sent = 0;
  while (sent < request_json.size()) {
    WaitStatus wait = WaitFor(fd, POLLOUT, deadline, &DefaultConnectSyscalls());
    if (wait != WaitStatus::kReady) {
      close(fd);
      LogFailure(
          wait == WaitStatus::kTimeout ? "deadline_exceeded" : "write_failed",
          "write", 0);
      return false;
    }
    ssize_t size =
        send(fd, request_json.data() + sent, request_json.size() - sent, 0);
    if (size > 0) {
      sent += size;
      continue;
    }
    if (size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    close(fd);
    LogFailure("write_failed", "write", 0);
    return false;
  }
  shutdown(fd, SHUT_WR);

  string buf;
  char chunk[4096];
  while (true) {
    WaitStatus wait = WaitFor(fd, POLLIN, deadline, &DefaultConnectSyscalls());
    if (wait != WaitStatus::kReady) {
      close(fd);
      LogFailure(
          wait == WaitStatus::kTimeout ? "deadline_exceeded" : "read_failed",
          "read", 0);
      return false;
    }
    ssize_t n = recv(fd, chunk, sizeof(chunk), 0);
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    if (n < 0) {
      close(fd);
      LogFailure("read_failed", "read", 0);
      return false;
    }
    if (n == 0)
      break;
    buf.append(chunk, n);
    if (buf.size() > kMaximumResponseBytes) {
      close(fd);
      LogFailure("response_too_large", "read", 0);
      return false;
    }
  }
  close(fd);

  if (buf.empty()) {
    LogFailure("empty_response", "read", 0);
    return false;
  }
  *response = buf;
  return true;
}

bool LlmScorer::SendRequest(const string& context,
                            const vector<string>& candidates,
                            const string& request_id,
                            const string& plan_identity,
                            const string& baseline_policy_id,
                            string* response) {
  string request = BuildRequest(context, candidates, request_id, plan_identity,
                                baseline_policy_id);
  return ExchangeJson(socket_path_, request, deadline_ms_, response);
}

bool LlmScorer::ScoreBatch(const ScoringRequest& request,
                           const vector<an<Candidate>>& candidates,
                           vector<ScoreComponents>* batch_scores) {
  if (!batch_scores || request.candidate_texts.size() != candidates.size())
    return false;
  for (size_t i = 0; i < candidates.size(); ++i) {
    if (!candidates[i] || candidates[i]->text() != request.candidate_texts[i])
      return false;
  }
  if (request.candidate_texts.empty()) {
    batch_scores->clear();
    return true;
  }

  static std::atomic<uint64_t> next_request{0};
  const string request_id = "llm-score-request-v1:" + std::to_string(getpid()) +
                            ":" + std::to_string(next_request++);
  string response;
  if (!SendRequest(request.preceding_text, request.candidate_texts, request_id,
                   request.plan_identity, request.baseline_policy_id,
                   &response))
    return false;

  vector<double> scores;
  const char* error_code = "invalid_protocol";
  if (!ParseScores(response, request_id, request.plan_identity,
                   request.candidate_texts.size(), &scores, &error_code)) {
    LogFailure(error_code, "validate", request.candidate_texts.size());
    return false;
  }

  vector<ScoreComponents> result;
  result.reserve(scores.size());
  for (double score : scores)
    result.push_back({alpha_ * score, 0.0});
  *batch_scores = std::move(result);

  if (verbose_)
    LOG(INFO) << "llm_scorer: scored candidate_count=" << scores.size();
  return true;
}

}  // namespace rime
