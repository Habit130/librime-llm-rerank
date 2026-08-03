//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_SCORER_H_
#define RIME_LLM_SCORER_H_

#include <rime/common.h>

#include "llm_rerank_filter.h"

namespace rime {

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

  void set_context(const string& context) { context_ = context; }

  bool Prepare(const string& plan_identity,
               const vector<string>& candidate_texts) override;

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
  string context_;
  map<string, double> score_cache_;
  bool prepared_ = false;
};

}  // namespace rime

#endif  // RIME_LLM_SCORER_H_
