//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <rime/candidate.h>
#include <rime/config.h>
#include <rime/schema.h>
#include <rime/ticket.h>
#include <rime/translation.h>

#include "llm_rerank_filter.h"

namespace rime {

// Identity rerank translation (T1 tracer bullet): emits candidates in exactly
// the order received. The PrefetchTranslation + cache_.splice shape follows
// SingleCharFilter (librime gear/single_char_filter.cc); the grouping and
// rescoring logic of later tickets plugs into Rearrange().
class LlmRerankTranslation : public PrefetchTranslation {
 public:
  explicit LlmRerankTranslation(an<Translation> translation);

 private:
  bool Rearrange();
};

LlmRerankTranslation::LlmRerankTranslation(an<Translation> translation)
    : PrefetchTranslation(translation) {
  Rearrange();
}

bool LlmRerankTranslation::Rearrange() {
  if (exhausted()) {
    return false;
  }
  CandidateQueue reranked;
  while (!translation_->exhausted()) {
    reranked.push_back(translation_->Peek());
    translation_->Next();
  }
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
}

an<Translation> LlmRerankFilter::Apply(an<Translation> translation,
                                       CandidateList* candidates) {
  if (!enabled_) {
    return translation;
  }
  return New<LlmRerankTranslation>(translation);
}

}  // namespace rime
