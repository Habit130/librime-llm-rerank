//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_FILTER_H_
#define RIME_LLM_RERANK_FILTER_H_

#include <rime/filter.h>

namespace rime {

class Scorer {
 public:
  virtual ~Scorer() = default;
  virtual bool Score(const an<Candidate>& cand, double* score) = 0;
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

class LlmRerankFilter : public Filter {
 public:
  explicit LlmRerankFilter(const Ticket& ticket);

  virtual an<Translation> Apply(an<Translation> translation,
                                CandidateList* candidates);

  void set_scorer(an<Scorer> scorer) { scorer_ = scorer; }

 private:
  bool enabled_ = true;
  int window_ = 32;
  double sys_coeff_ = 1.0;
  double usr_coeff_ = 1.0;
  bool verbose_ = false;
  an<Scorer> scorer_;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_FILTER_H_
