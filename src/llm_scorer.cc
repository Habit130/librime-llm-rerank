//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>

#include <rime/candidate.h>
#include <rime/common.h>

#include "llm_scorer.h"

namespace rime {

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
                           const vector<string>& candidates) {
  string json = "{\"context\":\"";
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

static bool ParseScores(const string& response, vector<double>* scores) {
  auto key_pos = response.find("\"scores\"");
  if (key_pos == string::npos)
    return false;
  auto bracket = response.find('[', key_pos);
  if (bracket == string::npos)
    return false;
  auto end_bracket = response.find(']', bracket);
  if (end_bracket == string::npos)
    return false;

  string inner = response.substr(bracket + 1, end_bracket - bracket - 1);
  scores->clear();
  size_t pos = 0;
  while (pos < inner.size()) {
    while (pos < inner.size() &&
           (inner[pos] == ' ' || inner[pos] == ',' || inner[pos] == '\n' ||
            inner[pos] == '\r' || inner[pos] == '\t'))
      pos++;
    if (pos >= inner.size())
      break;
    char* end = nullptr;
    double val = strtod(inner.c_str() + pos, &end);
    if (end == inner.c_str() + pos)
      return false;
    scores->push_back(val);
    pos = end - inner.c_str();
  }
  return true;
}

bool LlmScorer::SendRequest(const string& context,
                            const vector<string>& candidates,
                            string* response) {
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    LOG(WARNING) << "llm_scorer: socket() failed: " << strerror(errno);
    return false;
  }

  struct sockaddr_un addr;
  memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  if (socket_path_.size() >= sizeof(addr.sun_path)) {
    close(fd);
    LOG(WARNING) << "llm_scorer: socket path too long";
    return false;
  }
  strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

  if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
    close(fd);
    LOG(WARNING) << "llm_scorer: connect failed: " << strerror(errno);
    return false;
  }

  struct timeval tv;
  tv.tv_sec = 0;
  tv.tv_usec = 200000;  // 200ms
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

  string request = BuildRequest(context, candidates);
  ssize_t sent = write(fd, request.data(), request.size());
  if (sent < 0 || (size_t)sent != request.size()) {
    close(fd);
    LOG(WARNING) << "llm_scorer: write failed: " << strerror(errno);
    return false;
  }
  shutdown(fd, SHUT_WR);

  string buf;
  char chunk[4096];
  while (true) {
    ssize_t n = read(fd, chunk, sizeof(chunk));
    if (n < 0) {
      close(fd);
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        LOG(WARNING) << "llm_scorer: recv timeout (200ms)";
      } else {
        LOG(WARNING) << "llm_scorer: read failed: " << strerror(errno);
      }
      return false;
    }
    if (n == 0)
      break;
    buf.append(chunk, n);
    if (buf.find('\n') != string::npos)
      break;
  }
  close(fd);

  if (buf.empty()) {
    LOG(WARNING) << "llm_scorer: empty response";
    return false;
  }
  *response = buf;
  return true;
}

void LlmScorer::Prepare(const vector<string>& candidate_texts) {
  score_cache_.clear();
  prepared_ = false;

  if (candidate_texts.empty()) {
    prepared_ = true;
    return;
  }

  string response;
  if (!SendRequest(context_, candidate_texts, &response))
    return;

  if (response.find("\"error\"") != string::npos) {
    LOG(WARNING) << "llm_scorer: daemon error: " << response;
    return;
  }

  vector<double> scores;
  if (!ParseScores(response, &scores)) {
    LOG(WARNING) << "llm_scorer: failed to parse response: " << response;
    return;
  }
  if (scores.size() != candidate_texts.size()) {
    LOG(WARNING) << "llm_scorer: score count mismatch: got " << scores.size()
                 << " expected " << candidate_texts.size();
    return;
  }

  for (size_t i = 0; i < candidate_texts.size(); i++) {
    score_cache_[candidate_texts[i]] = scores[i];
  }
  prepared_ = true;

  if (verbose_) {
    for (size_t i = 0; i < candidate_texts.size(); i++) {
      LOG(INFO) << "llm_scorer: text=" << candidate_texts[i]
                << " lm_score=" << scores[i];
    }
  }
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
