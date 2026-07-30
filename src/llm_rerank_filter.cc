//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/config.h>
#include <rime/schema.h>
#include <rime/ticket.h>
#include <rime/translation.h>

#include "llm_rerank_filter.h"

namespace rime {

// Identity rerank translation (T1 tracer bullet): emits candidates in exactly
// the order received. The PrefetchTranslation + cache_.splice shape follows
// SingleCharFilter (librime gear/single_char_filter.cc); the grouping and
// rescoring logic of later tickets plugs into Replenish().
//
// Pull timing must stay 1:1 with the downstream consumer: this filter sits at
// the end of the chain, after uniquifier, whose dedup window is the menu's
// already-emitted candidate list. Prefetching faster than the consumer pulls
// (e.g. draining the upstream in the constructor) would let uniquifier's
// duplicates leak through — observed as extra post-simplification duplicate
// candidates with zh_hans on.
class LlmRerankTranslation : public PrefetchTranslation {
 public:
  explicit LlmRerankTranslation(an<Translation> translation)
      : PrefetchTranslation(translation) {}

 protected:
  virtual bool Replenish();
};

bool LlmRerankTranslation::Replenish() {
  if (translation_->exhausted()) {
    return false;
  }
  CandidateQueue reranked;
  reranked.push_back(translation_->Peek());
  translation_->Next();
  cache_.splice(cache_.end(), reranked);
  return !cache_.empty();
}

LlmRerankFilter::LlmRerankFilter(const Ticket& ticket) : Filter(ticket) {
  // An unaliased filter gets the generic namespace "filter" from the engine;
  // fall back to the component's own name, as Simplifier and
  // ReverseLookupFilter do (gear/simplifier.cc, gear/reverse_lookup_filter.cc).
  if (name_space_ == "filter") {
    name_space_ = "llm_rerank";
  }
  if (!ticket.schema)
    return;
  if (Config* config = ticket.schema->config()) {
    config->GetBool(name_space_ + "/enable", &enabled_);
  }
  LOG(INFO) << name_space_ << ": enable = " << (enabled_ ? "true" : "false");
}

an<Translation> LlmRerankFilter::Apply(an<Translation> translation,
                                       CandidateList* candidates) {
  if (!enabled_) {
    return translation;
  }
  return New<LlmRerankTranslation>(translation);
}

}  // namespace rime
