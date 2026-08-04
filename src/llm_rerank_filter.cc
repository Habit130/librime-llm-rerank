//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <cmath>
#include <set>
#include <utility>

#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/config.h>
#include <rime/context.h>
#include <rime/engine.h>
#include <rime/schema.h>
#include <rime/service.h>
#include <rime/ticket.h>
#include <rime/translation.h>
#include <rime/commit_history.h>
#include <rime/dict/db.h>
#include <rime/dict/level_db.h>
#include <rime/dict/user_db.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_filter.h"
#include "llm_scorer.h"

namespace rime {

static void LogWindowFailure(const char* code,
                             const char* phase,
                             size_t candidate_count) {
  LOG(WARNING) << "llm_rerank: code=" << code << " phase=" << phase
               << " plan_version=" << kRerankPlanVersion
               << " candidate_count=" << candidate_count;
}

// System- vs user-dictionary word candidates. table_translator emits
// "table"/"user_table"; script_translator (pinyin) emits
// "phrase"/"user_phrase".
static bool IsSysWordType(const string& type) {
  return type == "table" || type == "phrase";
}

static bool IsUsrWordType(const string& type) {
  return type == "user_table" || type == "user_phrase";
}

bool WeightScorer::Score(const an<Candidate>& cand, ScoreComponents* score) {
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
  score->base_score = coeff * weight;
  score->retrieval_evidence = 0.0;
  if (verbose_) {
    LOG(INFO) << "llm_rerank weight: source=" << source << " weight=" << weight
              << " coeff=" << coeff << " score=" << score->base_score;
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

bool ContextScorer::Score(const an<Candidate>& cand, ScoreComponents* score) {
  score->base_score = 0.0;
  score->retrieval_evidence = 0.0;
  if (!counter_ || prev_word_.empty())
    return true;
  int pair_count;
  int total_count;
  if (!counter_->PairCount(prev_word_, cand->text(), &pair_count) ||
      !counter_->TotalCount(prev_word_, &total_count) || pair_count < 0 ||
      total_count < 0 || pair_count > total_count) {
    return false;
  }
  double s = EvidenceStrength(pair_count, total_count, saturate_k_);
  if (!std::isfinite(s) || s < 0.0 || s >= 1.0)
    return false;
  score->retrieval_evidence = s;
  if (verbose_) {
    LOG(INFO) << "llm_rerank context: pair=" << pair_count
              << " total=" << total_count << " evidence=" << s;
  }
  return true;
}

bool ContextScorer::Prepare(const ScoringRequest& request) {
  prev_word_ = request.previous_word;
  return true;
}

bool CompositeScorer::Score(const an<Candidate>& cand, ScoreComponents* score) {
  ScoreComponents weight_score;
  if (!weight_ || !weight_->Score(cand, &weight_score))
    return false;
  ScoreComponents context_score;
  if (context_ && !context_->Score(cand, &context_score))
    return false;
  ScoreComponents llm_score;
  if (llm_ && !llm_->Score(cand, &llm_score))
    return false;
  score->base_score = weight_score.base_score + llm_score.base_score;
  score->retrieval_evidence = context_score.retrieval_evidence;
  return true;
}

bool CompositeScorer::Prepare(const ScoringRequest& request) {
  return weight_ && weight_->Prepare(request) &&
         (!context_ || context_->Prepare(request)) &&
         (!llm_ || llm_->Prepare(request));
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
                       int window,
                        string schema_id,
                        string input,
                        string preceding_text,
                        string previous_word,
                        RerankScoringPolicy scoring_policy)
      : PrefetchTranslation(translation),
        scorer_(scorer),
        window_(window),
        schema_id_(std::move(schema_id)),
        input_(std::move(input)),
        preceding_text_(std::move(preceding_text)),
        previous_word_(std::move(previous_word)),
        scoring_policy_(std::move(scoring_policy)) {}

 protected:
  virtual bool Replenish();

 private:
  bool RerankWindow(const vector<an<Candidate>>& buffer,
                    bool truncated,
                    CandidateQueue* out);

  an<Scorer> scorer_;
  int window_;
  string schema_id_;
  string input_;
  string preceding_text_;
  string previous_word_;
  RerankScoringPolicy scoring_policy_;
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
  bool reranked = false;
  if (!scorer_) {
    LogWindowFailure("scoring_unavailable", "prepare", buffer.size());
  } else {
    reranked = RerankWindow(buffer, truncated, &result);
  }
  if (!reranked) {
    for (auto& c : buffer)
      result.push_back(c);
  }
  cache_.splice(cache_.end(), result);
  return !cache_.empty();
}

bool LlmRerankTranslation::RerankWindow(const vector<an<Candidate>>& buffer,
                                        bool truncated,
                                        CandidateQueue* out) {
  vector<RerankPlanCandidate> candidates;
  candidates.reserve(buffer.size());
  for (size_t i = 0; i < buffer.size(); ++i) {
    auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(buffer[i]));
    const string source_type = phrase ? phrase->type() : buffer[i]->type();
    const string category = CategoryOf(source_type);
    candidates.push_back({i, buffer[i]->start(), buffer[i]->end(), category,
                          source_type, buffer[i]->text(),
                          phrase && category == "word"});
  }

  RerankPlanConfig config = DefaultRerankPlanConfig();
  config.window = window_;
  RerankPlan plan =
      BuildRerankPlan(schema_id_, input_, preceding_text_, previous_word_,
                      config, scoring_policy_, candidates, truncated);
  if (!plan.identity || !plan.groups) {
    LogWindowFailure("invalid_plan", "plan", buffer.size());
    return false;
  }
  vector<bool> scored_candidate(buffer.size(), false);
  vector<string> texts;
  for (const auto& group : *plan.groups) {
    if (!*group.complete)
      continue;
    for (size_t index : *group.candidate_indexes) {
      scored_candidate[index] = true;
      texts.push_back(buffer[index]->text());
    }
  }
  ScoringRequest request{*plan.identity, *plan.preceding_text,
                         *plan.previous_word, std::move(texts)};
  if (!scorer_->Prepare(request)) {
    LogWindowFailure("scoring_prepare_failed", "prepare", buffer.size());
    return false;
  }

  RerankScoreResult result;
  result.version = kRerankScoreResultVersion;
  result.plan_identity = plan.identity;
  result.candidate_scores = vector<RerankCandidateScore>();
  result.candidate_scores->reserve(buffer.size());
  for (size_t i = 0; i < buffer.size(); ++i) {
    ScoreComponents score;
    if (scored_candidate[i] && !scorer_->Score(buffer[i], &score)) {
      LogWindowFailure("candidate_scoring_failed", "score", buffer.size());
      return false;
    }
    result.candidate_scores->push_back(MakeRerankCandidateScore(
        score.base_score, score.retrieval_evidence, *scoring_policy_.gamma));
  }

  vector<size_t> emission_order;
  if (!ReplayRerankPlan(plan, result, &emission_order)) {
    LogWindowFailure("replay_validation_failed", "replay", buffer.size());
    return false;
  }
  for (size_t index : emission_order)
    out->push_back(buffer[index]);
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
  schema_id_ = ticket.schema->schema_id();
  if (Config* config = ticket.schema->config()) {
    config->GetBool(name_space_ + "/enable", &enabled_);
    config->GetInt(name_space_ + "/window", &window_);
    config->GetDouble(name_space_ + "/alpha", &alpha_);
    config->GetDouble(name_space_ + "/sys_coeff", &sys_coeff_);
    config->GetDouble(name_space_ + "/usr_coeff", &usr_coeff_);
    config->GetDouble(name_space_ + "/gamma", &gamma_);
    config->GetDouble(name_space_ + "/saturate_k", &saturate_k_);
    config->GetInt(name_space_ + "/deadline_ms", &deadline_ms_);
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
    llm_scorer_ =
        New<LlmScorer>(socket_path_, alpha_, verbose_, deadline_ms_);
  }
  if (engine_) {
    if (auto component = UserDb::Require("userdb")) {
      string db_name = ticket.schema->schema_id() + ".llm_rerank";
      Db* raw = component->Create(db_name);
      if (raw && dynamic_cast<LevelDb*>(raw))
        memory_ = ContextMemory::OpenLevelDb(
            raw->file_path(),
            {db_name, "userdb", Service::instance().deployer().user_id});
      delete raw;
    }
    if (memory_) {
      context_scorer_ =
          New<ContextScorer>(memory_.get(), saturate_k_, verbose_);
      scorer_ = New<CompositeScorer>(
          weight_scorer, gamma_ > 0.0 ? context_scorer_ : nullptr, llm_scorer_);
    } else {
      LOG(WARNING) << name_space_
                   << ": failed to open user db; context scoring unavailable";
      if (gamma_ > 0.0) {
        scorer_.reset();
      } else if (llm_scorer_) {
        scorer_ = New<CompositeScorer>(weight_scorer, nullptr, llm_scorer_);
      }
    }
    Context* ctx = engine_->context();
    if (ctx) {
      for (const auto& record : ctx->commit_history())
        preceding_text_ += record.text;
      if (auto suffix = LastUnicodeCharacters(preceding_text_, 64)) {
        preceding_text_ = *suffix;
      } else {
        preceding_text_.clear();
        preceding_text_valid_ = false;
      }
      commit_connection_ =
          ctx->commit_notifier().connect([this](Context* c) { OnCommit(c); });
    }
    commit_text_connection_ = engine_->sink().connect(
        [this](const string& text) { OnCommitText(text); });
  }
  if (alpha_ > 0.0 && !llm_scorer_) {
    LOG(WARNING) << name_space_ << ": LLM scoring unavailable";
    scorer_.reset();
  }
  LOG(INFO) << name_space_ << ": enable = " << (enabled_ ? "true" : "false")
            << ", window = " << window_ << ", alpha = " << alpha_
            << ", sys_coeff = " << sys_coeff_ << ", usr_coeff = " << usr_coeff_
            << ", gamma = " << gamma_ << ", saturate_k = " << saturate_k_
            << ", deadline_ms = " << deadline_ms_
            << ", verbose = " << (verbose_ ? "true" : "false");
}

LlmRerankFilter::~LlmRerankFilter() {
  commit_connection_.disconnect();
  commit_text_connection_.disconnect();
}

void LlmRerankFilter::OnCommit(Context* ctx) {
  if (!ctx)
    return;
  string selected = ctx->GetCommitText();
  if (selected.empty())
    return;
  if (!memory_ || !HasNonAscii(selected))
    return;
  memory_->Record(last_word_, selected);
  last_word_ = selected;
}

void LlmRerankFilter::OnCommitText(const string& text) {
  if (!preceding_text_valid_)
    return;
  string updated = preceding_text_ + text;
  if (auto suffix = LastUnicodeCharacters(updated, 64)) {
    preceding_text_ = *suffix;
  } else {
    preceding_text_.clear();
    preceding_text_valid_ = false;
  }
}

string LlmRerankFilter::BuildContext() {
  if (!preceding_text_valid_)
    return string(1, static_cast<char>(0xff));
  string result = preceding_text_;
  if (!engine_ || !engine_->context())
    return result;
  Context* context = engine_->context();
  for (const Segment& segment : context->composition()) {
    if (segment.status < Segment::kSelected)
      continue;
    auto candidate = segment.GetSelectedCandidate();
    if (candidate) {
      result += candidate->text();
    } else if (segment.start <= segment.end &&
               segment.end <= context->input().size()) {
      result +=
          context->input().substr(segment.start, segment.end - segment.start);
    }
  }
  auto suffix = LastUnicodeCharacters(result, 64);
  return suffix ? *suffix : result;
}

an<Translation> LlmRerankFilter::Apply(an<Translation> translation,
                                       CandidateList* candidates) {
  if (!enabled_) {
    return translation;
  }
  const string preceding_text = BuildContext();
  RerankScoringPolicy scoring_policy = DefaultRerankScoringPolicy();
  scoring_policy.alpha = alpha_;
  scoring_policy.sys_coeff = sys_coeff_;
  scoring_policy.usr_coeff = usr_coeff_;
  scoring_policy.gamma = gamma_;
  scoring_policy.saturate_k = saturate_k_;
  string input = input_;
  if (engine_ && engine_->context())
    input = engine_->context()->input();
  return New<LlmRerankTranslation>(translation, scorer_, window_, schema_id_,
                                   input, preceding_text, last_word_,
                                   scoring_policy);
}

}  // namespace rime
