//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <algorithm>
#include <map>
#include <set>
#include <tuple>
#include <utility>

#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/config.h>
#include <rime/schema.h>
#include <rime/ticket.h>
#include <rime/translation.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_filter.h"

namespace rime {

class FakeScorer : public Scorer {
 public:
  bool Score(const Candidate& cand, double* score) override {
    double s = 0;
    for (unsigned char c : cand.text())
      s += c;
    *score = -s;
    return true;
  }
};

static string CategoryOf(const string& type) {
  if (type == "table" || type == "user_table")
    return "word";
  return type;
}

class LlmRerankTranslation : public PrefetchTranslation {
 public:
  LlmRerankTranslation(an<Translation> translation,
                       an<Scorer> scorer,
                       int window)
      : PrefetchTranslation(translation), scorer_(scorer), window_(window) {}

 protected:
  virtual bool Replenish();

 private:
  bool RerankWindow(const vector<an<Candidate>>& buffer, CandidateQueue* out);

  an<Scorer> scorer_;
  int window_;
};

bool LlmRerankTranslation::Replenish() {
  if (!cache_.empty())
    return true;
  if (translation_->exhausted())
    return false;

  vector<an<Candidate>> buffer;
  set<string> seen;
  while ((int)buffer.size() < window_ && !translation_->exhausted()) {
    auto cand = translation_->Peek();
    translation_->Next();
    if (!cand)
      break;
    if (seen.insert(cand->text()).second)
      buffer.push_back(cand);
  }
  if (buffer.empty())
    return false;

  CandidateQueue result;
  if (!scorer_ || !RerankWindow(buffer, &result)) {
    for (auto& c : buffer)
      result.push_back(c);
  }
  cache_.splice(cache_.end(), result);
  return !cache_.empty();
}

bool LlmRerankTranslation::RerankWindow(const vector<an<Candidate>>& buffer,
                                        CandidateQueue* out) {
  int n = (int)buffer.size();

  struct Slot {
    bool is_word;
    int group_id;
  };
  vector<Slot> slots(n);
  map<std::tuple<size_t, size_t, string>, int> group_map;
  vector<std::tuple<size_t, size_t, string>> group_keys;
  int last_word_group = -1;

  for (int i = 0; i < n; i++) {
    auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(buffer[i]));
    if (!phrase) {
      slots[i] = {false, -1};
      continue;
    }
    auto key = std::make_tuple(buffer[i]->start(), buffer[i]->end(),
                               CategoryOf(phrase->type()));
    int gid;
    auto it = group_map.find(key);
    if (it == group_map.end()) {
      gid = (int)group_keys.size();
      group_map[key] = gid;
      group_keys.push_back(key);
    } else {
      gid = it->second;
    }
    slots[i] = {true, gid};
    last_word_group = gid;
  }

  if (last_word_group < 0) {
    for (auto& c : buffer)
      out->push_back(c);
    return true;
  }

  vector<double> scores(n, 0.0);
  for (int i = 0; i < n; i++) {
    if (!slots[i].is_word || slots[i].group_id == last_word_group)
      continue;
    if (!scorer_->Score(*buffer[i], &scores[i]))
      return false;
  }

  vector<int> word_order;
  for (int gid = 0; gid < (int)group_keys.size(); gid++) {
    if (gid == last_word_group)
      continue;
    vector<int> members;
    for (int i = 0; i < n; i++)
      if (slots[i].is_word && slots[i].group_id == gid)
        members.push_back(i);
    stable_sort(members.begin(), members.end(),
                [&](int a, int b) { return scores[a] > scores[b]; });
    word_order.insert(word_order.end(), members.begin(), members.end());
  }
  for (int i = 0; i < n; i++)
    if (slots[i].is_word && slots[i].group_id == last_word_group)
      word_order.push_back(i);

  set<int> nonword_positions;
  for (int i = 0; i < n; i++)
    if (!slots[i].is_word)
      nonword_positions.insert(i);

  int wi = 0;
  for (int i = 0; i < n; i++) {
    if (nonword_positions.count(i))
      out->push_back(buffer[i]);
    else
      out->push_back(buffer[word_order[wi++]]);
  }
  return true;
}

LlmRerankFilter::LlmRerankFilter(const Ticket& ticket) : Filter(ticket) {
  if (name_space_ == "filter") {
    name_space_ = "llm_rerank";
  }
  if (!ticket.schema)
    return;
  if (Config* config = ticket.schema->config()) {
    config->GetBool(name_space_ + "/enable", &enabled_);
    config->GetInt(name_space_ + "/window", &window_);
  }
  scorer_ = New<FakeScorer>();
  LOG(INFO) << name_space_ << ": enable = " << (enabled_ ? "true" : "false")
            << ", window = " << window_;
}

an<Translation> LlmRerankFilter::Apply(an<Translation> translation,
                                       CandidateList* candidates) {
  if (!enabled_) {
    return translation;
  }
  return New<LlmRerankTranslation>(translation, scorer_, window_);
}

}  // namespace rime
