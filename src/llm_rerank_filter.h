//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_FILTER_H_
#define RIME_LLM_RERANK_FILTER_H_

#include <rime/filter.h>

#include <memory>

#include "evidence_scorer.h"
#include "llm_rerank_config.h"
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
  string baseline_policy_id;
  string preceding_text;
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

// Sums every enabled term into a complete score while keeping evidence
// separate. A failure from any enabled term rejects the whole score.
class CompositeScorer : public Scorer {
 public:
  CompositeScorer(an<Scorer> weight, an<Scorer> llm = nullptr)
      : weight_(weight), llm_(llm) {}

  bool ScoreBatch(const ScoringRequest& request,
                  const vector<an<Candidate>>& candidates,
                  vector<ScoreComponents>* scores) override;

 private:
  an<Scorer> weight_;
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
  void set_evidence_scorer(an<EvidenceScorer> scorer) {
    evidence_scorer_ = scorer;
  }
  void set_evidence_active(bool active) { evidence_active_ = active; }
  void set_evidence_config_identity(const string& identity) {
    evidence_config_identity_ = identity;
  }
  // Test seam: where the fact high-water is read from. Production keeps the
  // spec-fixed HOME-derived root; tests point it at a sandboxed temp root so
  // a unit fixture never reads real private history.
  void set_facts_root(const path& root) { facts_root_ = root; }
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

  // Resolved at construction (per-Engine/schema instance snapshot; never
  // re-read mid-composition). When not configured, phase-1 defaults apply
  // (reranking on, recording off, evidence off) so existing deployments are
  // bit-compatible; the config source is reported by status.
  SwitchConfigSource config_source_ = SwitchConfigSource::kNotConfigured;
  bool reranking_enabled_ = true;
  bool recording_enabled_ = false;
  bool evidence_enabled_ = false;
  int window_ = 32;
  // Default alpha = 0 (owner decision, Habit130/squirrel#46): the canonical
  // 120/402 calibration supports no positive alpha (see
  // eval/manifest.json), so the LM term is disabled unless the schema
  // explicitly sets a positive value.
  double alpha_ = 0.0;
  double sys_coeff_ = 1.0;
  double usr_coeff_ = 1.0;
  double gamma_ = 2.0;
  double saturate_k_ = 3.0;
  int deadline_ms_ = 200;
  bool verbose_ = false;
  // Versioned scoring-policy identity (docs/token-attribution.md); pins the
  // normalization semantics (mean-token since #46). Overridable per machine
  // via the schema so deployments can pin the strategy explicitly.
  string baseline_policy_id_ = "mean-token-lm-v1";
  // Retrieval-evidence parameters (#61): the daemon must be configured with
  // the identical evidence config identity, otherwise evidence requests fail
  // closed and the whole window passes through.
  string representation_id_;
  double tau_ = 0.0;
  int k_evidence_ = 8;
  double half_life_ = std::numeric_limits<double>::infinity();
  string evidence_config_identity_;
  bool evidence_active_ = false;
  string schema_id_;
  string input_;
  string socket_path_;
  path facts_root_;
  an<Scorer> scorer_;
  an<LlmScorer> llm_scorer_;
  an<EvidenceScorer> evidence_scorer_;
  connection commit_connection_;
  connection commit_text_connection_;
  std::shared_ptr<RecorderSession> recorder_session_;
  string last_word_;
  string preceding_text_;
  bool preceding_text_valid_ = true;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_FILTER_H_
