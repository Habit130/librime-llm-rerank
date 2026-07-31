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
#include <rime/context.h>
#include <rime/engine.h>
#include <rime/schema.h>
#include <rime/ticket.h>
#include <rime/translation.h>
#include <rime/commit_history.h>
#include <rime/dict/db.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_filter.h"
#include "llm_scorer.h"

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

double ContextScorer::EvidenceStrength(int pair_count,
                                       int total_count,
                                       double saturate_k) {
  if (total_count <= 0 || pair_count <= 0)
    return 0.0;
  double relative_preference = (double)pair_count / (double)total_count;
  double evidence = (double)pair_count / ((double)pair_count + saturate_k);
  return relative_preference * evidence;
}

bool ContextScorer::Score(const an<Candidate>& cand, double* score) {
  *score = 0.0;
  if (!counter_ || prev_word_.empty())
    return true;
  const string& text = cand->text();
  int pair_count = counter_->PairCount(prev_word_, text);
  int total_count = counter_->TotalCount(prev_word_);
  double s = EvidenceStrength(pair_count, total_count, saturate_k_);
  *score = gamma_ * s;
  if (verbose_) {
    LOG(INFO) << "llm_rerank context: prev_word=" << prev_word_
              << " text=" << text << " pair=" << pair_count
              << " total=" << total_count << " s=" << s << " score=" << *score;
  }
  return true;
}

bool CompositeScorer::Score(const an<Candidate>& cand, double* score) {
  double weight_score;
  if (!weight_->Score(cand, &weight_score))
    return false;
  double context_score = 0.0;
  if (context_)
    context_->Score(cand, &context_score);
  double llm_score = 0.0;
  if (llm_)
    llm_->Score(cand, &llm_score);
  *score = weight_score + context_score + llm_score;
  return true;
}

void CompositeScorer::Prepare(const vector<string>& candidate_texts) {
  if (llm_)
    llm_->Prepare(candidate_texts);
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
  bool RerankWindow(const vector<an<Candidate>>& buffer,
                    bool truncated,
                    CandidateQueue* out);

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

  bool truncated = (int)buffer.size() >= window_ && !translation_->exhausted();
  CandidateQueue result;
  if (!scorer_ || !RerankWindow(buffer, truncated, &result)) {
    for (auto& c : buffer)
      result.push_back(c);
  }
  cache_.splice(cache_.end(), result);
  return !cache_.empty();
}

bool LlmRerankTranslation::RerankWindow(const vector<an<Candidate>>& buffer,
                                        bool truncated,
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

  // The last word group is only possibly incomplete when the window cut off a
  // still-running translation; exclude it (keep original order) only then. A
  // complete window (translation exhausted) scores every group, including the
  // last one — otherwise a single-group window would never be scored at all.
  int excluded_group = truncated ? last_word_group : -1;

  vector<double> scores(n, 0.0);
  vector<string> texts;
  for (int i = 0; i < n; i++) {
    if (!slots[i].is_word || slots[i].group_id == excluded_group)
      continue;
    texts.push_back(buffer[i]->text());
  }
  scorer_->Prepare(texts);
  for (int i = 0; i < n; i++) {
    if (!slots[i].is_word || slots[i].group_id == excluded_group)
      continue;
    if (!scorer_->Score(buffer[i], &scores[i]))
      return false;
  }

  vector<int> word_order;
  for (int gid = 0; gid < (int)group_keys.size(); gid++) {
    if (gid == excluded_group)
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
    if (slots[i].is_word && slots[i].group_id == excluded_group)
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

static bool HasNonAscii(const string& text) {
  for (char c : text) {
    if ((unsigned char)c >= 0x80)
      return true;
  }
  return false;
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
    config->GetDouble(name_space_ + "/alpha", &alpha_);
    config->GetDouble(name_space_ + "/sys_coeff", &sys_coeff_);
    config->GetDouble(name_space_ + "/usr_coeff", &usr_coeff_);
    config->GetDouble(name_space_ + "/gamma", &gamma_);
    config->GetDouble(name_space_ + "/saturate_k", &saturate_k_);
    config->GetBool(name_space_ + "/verbose", &verbose_);
    config->GetString(name_space_ + "/socket_path", &socket_path_);
  }
  if (socket_path_.empty()) {
    const char* home = getenv("HOME");
    if (home) {
      socket_path_ = string(home) +
                     "/Library/Application Support/Squirrel/llm-rerank.sock";
    }
  }
  auto weight_scorer = New<WeightScorer>(sys_coeff_, usr_coeff_, verbose_);
  scorer_ = weight_scorer;
  if (alpha_ > 0.0 && !socket_path_.empty()) {
    llm_scorer_ = New<LlmScorer>(socket_path_, alpha_, verbose_);
  }
  if (engine_) {
    an<Db> db;
    if (auto component = Db::Require("userdb")) {
      string db_name = ticket.schema->schema_id() + ".llm_rerank";
      Db* raw = component->Create(db_name);
      if (raw && raw->Open()) {
        raw->CreateMetadata();
        db.reset(raw);
      } else {
        delete raw;
      }
    }
    if (db) {
      memory_.reset(new ContextMemory(db));
      context_scorer_ =
          New<ContextScorer>(memory_.get(), gamma_, saturate_k_, verbose_);
      scorer_ = New<CompositeScorer>(weight_scorer, context_scorer_, llm_scorer_);
      Context* ctx = engine_->context();
      commit_connection_ = ctx->commit_notifier().connect(
          [this](Context* c) { OnCommit(c); });
    } else {
      LOG(WARNING) << name_space_
                   << ": failed to open user db; context term disabled";
      if (llm_scorer_) {
        scorer_ = New<CompositeScorer>(weight_scorer, nullptr, llm_scorer_);
      }
    }
  }
  LOG(INFO) << name_space_ << ": enable = " << (enabled_ ? "true" : "false")
            << ", window = " << window_ << ", alpha = " << alpha_
            << ", sys_coeff = " << sys_coeff_
            << ", usr_coeff = " << usr_coeff_ << ", gamma = " << gamma_
            << ", saturate_k = " << saturate_k_
            << ", verbose = " << (verbose_ ? "true" : "false");
}

LlmRerankFilter::~LlmRerankFilter() {
  commit_connection_.disconnect();
}

void LlmRerankFilter::OnCommit(Context* ctx) {
  if (!memory_ || !ctx)
    return;
  string selected = ctx->GetCommitText();
  if (selected.empty() || !HasNonAscii(selected))
    return;
  memory_->Record(last_word_, selected);
  last_word_ = selected;
}

string LlmRerankFilter::BuildContext() {
  if (!engine_)
    return "";
  Context* ctx = engine_->context();
  if (!ctx)
    return "";
  const CommitHistory& history = ctx->commit_history();
  string result;
  for (const auto& record : history) {
    if (record.text.empty())
      continue;
    if (!HasNonAscii(record.text))
      continue;
    result += record.text;
  }
  return result;
}

an<Translation> LlmRerankFilter::Apply(an<Translation> translation,
                                       CandidateList* candidates) {
  if (!enabled_) {
    return translation;
  }
  if (context_scorer_) {
    context_scorer_->set_prev_word(last_word_);
  }
  if (llm_scorer_) {
    llm_scorer_->set_context(BuildContext());
  }
  return New<LlmRerankTranslation>(translation, scorer_, window_);
}

}  // namespace rime
