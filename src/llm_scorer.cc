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

#include <rapidjson/document.h>
#include <rime/candidate.h>
#include <rime/common.h>

#include "llm_scorer.h"

namespace rime {
namespace {

constexpr int kLlmScoringProtocolVersion = 1;
constexpr size_t kMaximumResponseBytes = 64 * 1024;

enum class WaitStatus { kReady, kTimeout, kError };

WaitStatus WaitFor(int fd,
                   short events,
                   std::chrono::steady_clock::time_point deadline) {
  while (true) {
    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
        deadline - std::chrono::steady_clock::now());
    if (remaining.count() <= 0)
      return WaitStatus::kTimeout;
    struct pollfd poll_fd { fd, events, 0 };
    int result = poll(&poll_fd, 1, static_cast<int>(remaining.count()));
    if (result > 0) {
      if (poll_fd.revents & (events | POLLHUP | POLLERR))
        return WaitStatus::kReady;
      return WaitStatus::kError;
    }
    if (result == 0)
      return WaitStatus::kTimeout;
    if (errno != EINTR)
      return WaitStatus::kError;
  }
}

void LogFailure(const char* code,
                const char* phase,
                size_t candidate_count) {
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
                           const string& plan_identity) {
  string json = "{\"version\":" +
                std::to_string(kLlmScoringProtocolVersion) +
                ",\"request_id\":\"" + JsonEscape(request_id) +
                "\",\"plan_identity\":\"" + JsonEscape(plan_identity) +
                "\",\"context\":\"";
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

static bool ParseScores(const string& response,
                        const string& expected_request_id,
                        const string& expected_plan_identity,
                        size_t expected_count,
                        vector<double>* scores,
                        const char** error_code) {
  const size_t newline = response.find('\n');
  if (newline == string::npos || newline == 0) {
    *error_code = "invalid_protocol";
    return false;
  }
  for (size_t i = newline + 1; i < response.size(); ++i) {
    if (response[i] != ' ' && response[i] != '\t' && response[i] != '\r' &&
        response[i] != '\n') {
      *error_code = "invalid_protocol";
      return false;
    }
  }

  rapidjson::Document document;
  document.Parse<rapidjson::kParseNanAndInfFlag>(response.data(), newline);
  if (document.HasParseError() || !document.IsObject()) {
    *error_code = "invalid_protocol";
    return false;
  }
  if (!document.HasMember("version") || !document["version"].IsInt() ||
      document["version"].GetInt() != kLlmScoringProtocolVersion ||
      !document.HasMember("request_id") ||
      !document["request_id"].IsString() ||
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
    if (document.MemberCount() != 4 || !document["error"].IsObject()) {
      *error_code = "invalid_protocol";
      return false;
    }
    *error_code = "daemon_error";
    return false;
  }
  if (document.MemberCount() != 4 || !document.HasMember("scores") ||
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

bool LlmScorer::SendRequest(const string& context,
                             const vector<string>& candidates,
                             const string& request_id,
                             const string& plan_identity,
                             string* response) {
  if (deadline_ms_ <= 0) {
    LogFailure("deadline_invalid", "prepare", candidates.size());
    return false;
  }
  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::milliseconds(deadline_ms_);
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    LogFailure("socket_failed", "connect", candidates.size());
    return false;
  }

  struct sockaddr_un addr;
  memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  if (socket_path_.size() >= sizeof(addr.sun_path)) {
    close(fd);
    LogFailure("socket_path_invalid", "connect", candidates.size());
    return false;
  }
  strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

  const int flags = fcntl(fd, F_GETFL, 0);
  if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
    close(fd);
    LogFailure("socket_setup_failed", "connect", candidates.size());
    return false;
  }
#ifdef SO_NOSIGPIPE
  int no_sigpipe = 1;
  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe, sizeof(no_sigpipe));
#endif

  if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
    if (errno != EINPROGRESS) {
      close(fd);
      LogFailure("connection_failed", "connect", candidates.size());
      return false;
    }
    WaitStatus wait = WaitFor(fd, POLLOUT, deadline);
    if (wait != WaitStatus::kReady) {
      close(fd);
      LogFailure(wait == WaitStatus::kTimeout ? "deadline_exceeded"
                                              : "connection_failed",
                 "connect", candidates.size());
      return false;
    }
    int socket_error = 0;
    socklen_t socket_error_size = sizeof(socket_error);
    if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &socket_error,
                   &socket_error_size) < 0 ||
        socket_error != 0) {
      close(fd);
      LogFailure("connection_failed", "connect", candidates.size());
      return false;
    }
  }

  string request =
      BuildRequest(context, candidates, request_id, plan_identity);
  size_t sent = 0;
  while (sent < request.size()) {
    WaitStatus wait = WaitFor(fd, POLLOUT, deadline);
    if (wait != WaitStatus::kReady) {
      close(fd);
      LogFailure(wait == WaitStatus::kTimeout ? "deadline_exceeded"
                                              : "write_failed",
                 "write", candidates.size());
      return false;
    }
    ssize_t size = send(fd, request.data() + sent, request.size() - sent, 0);
    if (size > 0) {
      sent += size;
      continue;
    }
    if (size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    close(fd);
    LogFailure("write_failed", "write", candidates.size());
    return false;
  }
  shutdown(fd, SHUT_WR);

  string buf;
  char chunk[4096];
  while (true) {
    WaitStatus wait = WaitFor(fd, POLLIN, deadline);
    if (wait != WaitStatus::kReady) {
      close(fd);
      LogFailure(wait == WaitStatus::kTimeout ? "deadline_exceeded"
                                              : "read_failed",
                 "read", candidates.size());
      return false;
    }
    ssize_t n = recv(fd, chunk, sizeof(chunk), 0);
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    if (n < 0) {
      close(fd);
      LogFailure("read_failed", "read", candidates.size());
      return false;
    }
    if (n == 0)
      break;
    buf.append(chunk, n);
    if (buf.size() > kMaximumResponseBytes) {
      close(fd);
      LogFailure("response_too_large", "read", candidates.size());
      return false;
    }
  }
  close(fd);

  if (buf.empty()) {
    LogFailure("empty_response", "read", candidates.size());
    return false;
  }
  *response = buf;
  return true;
}

bool LlmScorer::Prepare(const string& plan_identity,
                        const vector<string>& candidate_texts) {
  score_cache_.clear();
  prepared_ = false;

  if (candidate_texts.empty()) {
    prepared_ = true;
    return true;
  }

  static std::atomic<uint64_t> next_request{0};
  const string request_id = "llm-score-request-v1:" +
                            std::to_string(getpid()) + ":" +
                            std::to_string(next_request++);
  string response;
  if (!SendRequest(context_, candidate_texts, request_id, plan_identity,
                   &response))
    return false;

  vector<double> scores;
  const char* error_code = "invalid_protocol";
  if (!ParseScores(response, request_id, plan_identity, candidate_texts.size(),
                   &scores, &error_code)) {
    LogFailure(error_code, "validate", candidate_texts.size());
    return false;
  }

  for (size_t i = 0; i < candidate_texts.size(); i++) {
    score_cache_[candidate_texts[i]] = scores[i];
  }
  prepared_ = true;

  if (verbose_)
    LOG(INFO) << "llm_scorer: scored candidate_count=" << scores.size();
  return true;
}

bool LlmScorer::Score(const an<Candidate>& cand, ScoreComponents* score) {
  if (!prepared_)
    return false;
  auto it = score_cache_.find(cand->text());
  if (it == score_cache_.end())
    return false;
  score->base_score = alpha_ * it->second;
  score->retrieval_evidence = 0.0;
  return true;
}

}  // namespace rime
