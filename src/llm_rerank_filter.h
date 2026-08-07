//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_FILTER_H_
#define RIME_LLM_RERANK_FILTER_H_

#include <rime/filter.h>

#include <memory>

#include "context_memory.h"
#include "recorder_session.h"
#include "rerank_plan.h"

namespace rime {

class Context;
class LlmScorer;

struct ScoreComponents {
  double base_score = 0.0;
  double retrieval_evidence = 0.0;
};

struct ScoringRequest {
  string plan_identity;
  string preceding_text;
  string previous_word;
  vector<string> candidate_texts;
};

class Scorer {
 public:
  virtual ~Scorer() = default;
  // Scores one immutable request as a positional batch. Implementations must
  // not retain request-specific state after this call returns.
  virtual bool ScoreBatch(const ScoringRequest& request,
                          const vector<an<Candidate>>& candidates,
                          vector<ScoreComponents>* scores) = 0;
};

// Scores a candidate by its dictionary weight (log space) scaled by a
// source-dependent coefficient: system-dictionary candidates ("table") use
// sys_coeff, user-dictionary candidates ("user_table") use usr_coeff.
// Returns false for candidates that carry no dictionary weight, so the rerank
// logic leaves them in place.
class WeightScorer : public Scorer {
 public:
  WeightScorer(double sys_coeff, double usr_coeff, bool verbose = false)
      : sys_coeff_(sys_coeff), usr_coeff_(usr_coeff), verbose_(verbose) {}

  bool ScoreBatch(const ScoringRequest& request,
                  const vector<an<Candidate>>& candidates,
                  vector<ScoreComponents>* scores) override;
  bool Score(const an<Candidate>& cand, ScoreComponents* score);

 private:
  double sys_coeff_;
  double usr_coeff_;
  bool verbose_;
};

// Produces the bounded context evidence s(prev_word, candidate) separately from
// the frozen base score. The replay policy applies gamma only when it derives
// the final comparison score.
class ContextScorer : public Scorer {
 public:
  ContextScorer(ContextCounter* counter,
                double saturate_k,
                bool verbose = false)
      : counter_(counter), saturate_k_(saturate_k), verbose_(verbose) {}

  bool ScoreBatch(const ScoringRequest& request,
                  const vector<an<Candidate>>& candidates,
                  vector<ScoreComponents>* scores) override;

  // Bounded evidence strength in [0, 1). Zero on a miss (total_count <= 0); a
  // single observation reaches only 1 / (1 + saturate_k), never the bound.
  static double EvidenceStrength(int pair_count,
                                 int total_count,
                                 double saturate_k);

 private:
  ContextCounter* counter_;
  double saturate_k_;
  bool verbose_;
};

// Sums every enabled term into a complete score while keeping context evidence
// separate. A failure from any enabled term rejects the whole score.
class CompositeScorer : public Scorer {
 public:
  CompositeScorer(an<Scorer> weight,
                  an<Scorer> context,
                  an<Scorer> llm = nullptr)
      : weight_(weight), context_(context), llm_(llm) {}

  bool ScoreBatch(const ScoringRequest& request,
                  const vector<an<Candidate>>& candidates,
                  vector<ScoreComponents>* scores) override;

 private:
  an<Scorer> weight_;
  an<Scorer> context_;
  an<Scorer> llm_;
};

class LlmRerankFilter : public Filter {
 public:
  explicit LlmRerankFilter(const Ticket& ticket);
  ~LlmRerankFilter() override;
  LlmRerankFilter(LlmRerankFilter&&) = default;
  LlmRerankFilter& operator=(LlmRerankFilter&&) = default;

  an<Translation> Apply(an<Translation> translation,
                        CandidateList* candidates) override;

  void set_scorer(an<Scorer> scorer) { scorer_ = scorer; }
  void set_window(int window) { window_ = window; }
  void set_gamma(double gamma) { gamma_ = gamma; }
  void set_schema_id(const string& schema_id) { schema_id_ = schema_id; }
  void set_input(const string& input) { input_ = input; }
  void set_preceding_text(const string& text) { preceding_text_ = text; }
  void set_last_word(const string& text) { last_word_ = text; }

 private:
  void OnCommit(Context* ctx);
  void OnCommitText(const string& text);
  string BuildContext();

  bool enabled_ = true;
  int window_ = 32;
  double alpha_ = 2.0;
  double sys_coeff_ = 1.0;
  double usr_coeff_ = 1.0;
  double gamma_ = 2.0;
  double saturate_k_ = 3.0;
  int deadline_ms_ = 200;
  bool verbose_ = false;
  string schema_id_;
  string input_;
  string socket_path_;
  an<Scorer> scorer_;
  an<ContextScorer> context_scorer_;
  an<LlmScorer> llm_scorer_;
  the<ContextMemory> memory_;
  connection commit_connection_;
  connection commit_text_connection_;
  std::shared_ptr<RecorderSession> recorder_session_;
  string last_word_;
  string preceding_text_;
  bool preceding_text_valid_ = true;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_FILTER_H_
