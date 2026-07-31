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
  virtual bool Score(const Candidate& cand, double* score) = 0;
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
  an<Scorer> scorer_;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_FILTER_H_
