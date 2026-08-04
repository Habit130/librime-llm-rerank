//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_SCORER_H_
#define RIME_LLM_SCORER_H_

#include <sys/socket.h>

#include <chrono>

#include <rime/common.h>

#include "llm_rerank_filter.h"

namespace rime {

struct SocketCallResult {
  int result;
  int error;
};

class ConnectSyscalls {
 public:
  virtual ~ConnectSyscalls() = default;
  virtual SocketCallResult Connect(int fd,
                                   const struct sockaddr* address,
                                   socklen_t address_size) = 0;
  virtual SocketCallResult Poll(int fd,
                                short events,
                                int timeout_ms,
                                short* returned_events) = 0;
  virtual SocketCallResult GetSocketError(int fd, int* socket_error) = 0;
};

enum class NonBlockingConnectStatus { kConnected, kTimeout, kError };

NonBlockingConnectStatus ConnectNonBlockingWithDeadline(
    int fd,
    const struct sockaddr* address,
    socklen_t address_size,
    std::chrono::steady_clock::time_point deadline,
    ConnectSyscalls* syscalls);

class LlmScorer : public Scorer {
 public:
  LlmScorer(const string& socket_path,
            double alpha,
            bool verbose = false,
            int deadline_ms = 200)
      : socket_path_(socket_path),
        alpha_(alpha),
        verbose_(verbose),
        deadline_ms_(deadline_ms) {}

  bool Score(const an<Candidate>& cand, ScoreComponents* score) override;

  bool Prepare(const ScoringRequest& request) override;

 private:
  bool SendRequest(const string& context,
                   const vector<string>& candidates,
                   const string& request_id,
                   const string& plan_identity,
                   string* response);

  string socket_path_;
  double alpha_;
  bool verbose_;
  int deadline_ms_;
  map<string, double> score_cache_;
  bool prepared_ = false;
};

}  // namespace rime

#endif  // RIME_LLM_SCORER_H_
