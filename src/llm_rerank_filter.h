//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_FILTER_H_
#define RIME_LLM_RERANK_FILTER_H_

#include <rime/filter.h>

#include "context_memory.h"

namespace rime {

class Context;
class LlmScorer;

class Scorer {
 public:
  virtual ~Scorer() = default;
  virtual bool Score(const an<Candidate>& cand, double* score) = 0;
  virtual void Prepare(const vector<string>& candidate_texts) {}
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

  bool Score(const an<Candidate>& cand, double* score) override;

 private:
  double sys_coeff_;
  double usr_coeff_;
  bool verbose_;
};

// Scores a candidate by the context-personalization term: gamma times a bounded
// evidence strength s(prev_word, candidate) = relative preference * saturating
// evidence. A miss (nothing recorded after prev_word) scores zero, so the
// additive term falls back to the other terms with no extra branch or floor.
class ContextScorer : public Scorer {
 public:
  ContextScorer(ContextCounter* counter,
                double gamma,
                double saturate_k,
                bool verbose = false)
      : counter_(counter),
        gamma_(gamma),
        saturate_k_(saturate_k),
        verbose_(verbose) {}

  bool Score(const an<Candidate>& cand, double* score) override;

  void set_prev_word(const string& prev_word) { prev_word_ = prev_word; }

  // Bounded evidence strength in [0, 1). Zero on a miss (total_count <= 0); a
  // single observation reaches only 1 / (1 + saturate_k), never the bound.
  static double EvidenceStrength(int pair_count,
                                 int total_count,
                                 double saturate_k);

 private:
  ContextCounter* counter_;
  double gamma_;
  double saturate_k_;
  string prev_word_;
  bool verbose_;
};

// Sums a weight score, an optional LLM score, and a context score. Candidates
// the weight scorer rejects (no dictionary weight) are rejected outright so
// non-word candidates keep their place; the LLM and context terms only ever add
// to an accepted candidate. When the LLM scorer fails (daemon unavailable),
// its term is simply omitted.
class CompositeScorer : public Scorer {
 public:
  CompositeScorer(an<Scorer> weight, an<Scorer> context, an<Scorer> llm = nullptr)
      : weight_(weight), context_(context), llm_(llm) {}

  bool Score(const an<Candidate>& cand, double* score) override;
  void Prepare(const vector<string>& candidate_texts) override;

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

 private:
  void OnCommit(Context* ctx);
  string BuildContext();

  bool enabled_ = true;
  int window_ = 32;
  double alpha_ = 2.0;
  double sys_coeff_ = 1.0;
  double usr_coeff_ = 1.0;
  double gamma_ = 2.0;
  double saturate_k_ = 3.0;
  bool verbose_ = false;
  string socket_path_;
  an<Scorer> scorer_;
  an<ContextScorer> context_scorer_;
  an<LlmScorer> llm_scorer_;
  the<ContextMemory> memory_;
  connection commit_connection_;
  string last_word_;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_FILTER_H_
