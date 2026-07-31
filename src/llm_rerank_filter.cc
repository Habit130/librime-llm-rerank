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

// System- vs user-dictionary word candidates. table_translator emits
// "table"/"user_table"; script_translator (pinyin) emits "phrase"/"user_phrase".
static bool IsSysWordType(const string& type) {
  return type == "table" || type == "phrase";
}

static bool IsUsrWordType(const string& type) {
  return type == "user_table" || type == "user_phrase";
}

bool WeightScorer::Score(const an<Candidate>& cand, double* score) {
  auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(cand));
  if (!phrase)
    return false;
  double coeff;
  const char* source;
  if (IsSysWordType(phrase->type())) {
    coeff = sys_coeff_;
    source = "sys";
  } else if (IsUsrWordType(phrase->type())) {
    coeff = usr_coeff_;
    source = "usr";
  } else {
    return false;
  }
  double weight = phrase->weight();
  *score = coeff * weight;
  if (verbose_) {
    LOG(INFO) << "llm_rerank weight: text=" << phrase->text()
              << " source=" << source << " weight=" << weight
              << " coeff=" << coeff << " score=" << *score;
  }
  return true;
}

static string CategoryOf(const string& type) {
  if (IsSysWordType(type) || IsUsrWordType(type))
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
    if (!scorer_->Score(buffer[i], &scores[i]))
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
    config->GetDouble(name_space_ + "/sys_coeff", &sys_coeff_);
    config->GetDouble(name_space_ + "/usr_coeff", &usr_coeff_);
    config->GetBool(name_space_ + "/verbose", &verbose_);
  }
  scorer_ = New<WeightScorer>(sys_coeff_, usr_coeff_, verbose_);
  LOG(INFO) << name_space_ << ": enable = " << (enabled_ ? "true" : "false")
            << ", window = " << window_ << ", sys_coeff = " << sys_coeff_
            << ", usr_coeff = " << usr_coeff_
            << ", verbose = " << (verbose_ ? "true" : "false");
}

an<Translation> LlmRerankFilter::Apply(an<Translation> translation,
                                       CandidateList* candidates) {
  if (!enabled_) {
    return translation;
  }
  return New<LlmRerankTranslation>(translation, scorer_, window_);
}

}  // namespace rime
