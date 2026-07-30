//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_FILTER_H_
#define RIME_LLM_RERANK_FILTER_H_

#include <rime/filter.h>

namespace rime {

class LlmRerankFilter : public Filter {
 public:
  explicit LlmRerankFilter(const Ticket& ticket);

  virtual an<Translation> Apply(an<Translation> translation,
                                CandidateList* candidates);

 private:
  bool enabled_ = true;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_FILTER_H_
