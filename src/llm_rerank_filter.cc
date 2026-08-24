//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <chrono>
#include <cmath>
#include <functional>
#include <limits>
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
#include <rime/gear/translator_commons.h>

#include "evidence_scorer.h"
#include "fact_store.h"
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

bool WeightScorer::ScoreBatch(const ScoringRequest& request,
                              const vector<an<Candidate>>& candidates,
                              vector<ScoreComponents>* scores) {
  if (!scores || request.candidate_texts.size() != candidates.size())
    return false;
  vector<ScoreComponents> result;
  result.reserve(candidates.size());
  for (size_t i = 0; i < candidates.size(); ++i) {
    if (!candidates[i] || candidates[i]->text() != request.candidate_texts[i])
      return false;
    ScoreComponents score;
    if (!Score(candidates[i], &score))
      return false;
    result.push_back(score);
  }
  *scores = std::move(result);
  return true;
}

bool CompositeScorer::ScoreBatch(const ScoringRequest& request,
                                 const vector<an<Candidate>>& candidates,
                                 vector<ScoreComponents>* scores) {
  if (!scores || !weight_)
    return false;
  vector<ScoreComponents> weight_scores;
  if (!weight_->ScoreBatch(request, candidates, &weight_scores) ||
      weight_scores.size() != candidates.size()) {
    return false;
  }
  vector<ScoreComponents> llm_scores(candidates.size());
  if (llm_ && (!llm_->ScoreBatch(request, candidates, &llm_scores) ||
               llm_scores.size() != candidates.size())) {
    return false;
  }
  vector<ScoreComponents> result;
  result.reserve(candidates.size());
  for (size_t i = 0; i < candidates.size(); ++i) {
    result.push_back({weight_scores[i].base_score + llm_scores[i].base_score,
                      0.0});
  }
  *scores = std::move(result);
  return true;
}

static string CategoryOf(const string& type) {
  if (IsSysWordType(type) || IsUsrWordType(type))
    return "word";
  return type;
}

static std::chrono::steady_clock::time_point NowOr(
    const std::function<std::chrono::steady_clock::time_point()>& now) {
  return now ? now() : std::chrono::steady_clock::now();
}

static int RemainingDeadlineMs(
    std::chrono::steady_clock::time_point deadline,
    const std::function<std::chrono::steady_clock::time_point()>& now) {
  const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
                             deadline - NowOr(now))
                             .count();
  if (remaining <= 0)
    return 0;
  if (remaining > std::numeric_limits<int>::max())
    return std::numeric_limits<int>::max();
  return static_cast<int>(remaining);
}

class LlmRerankTranslation : public PrefetchTranslation {
 public:
  LlmRerankTranslation(an<Translation> translation,
                       an<Scorer> scorer,
                       an<EvidenceScorer> evidence_scorer,
                       bool evidence_active,
                        path facts_root,
                        int window,
                        int deadline_ms,
                        std::function<std::chrono::steady_clock::time_point()> now,
                        string schema_id,
                        string input,
                       string preceding_text,
                       string previous_word,
                       RerankScoringPolicy scoring_policy,
                       std::shared_ptr<RecorderSession> recorder_session,
                       size_t segment_start,
                       bool record_snapshots,
                       bool snapshot_only)
      : PrefetchTranslation(translation),
        scorer_(scorer),
        evidence_scorer_(std::move(evidence_scorer)),
        evidence_active_(evidence_active),
        facts_root_(std::move(facts_root)),
        window_(window),
        deadline_ms_(deadline_ms),
        now_(std::move(now)),
        schema_id_(std::move(schema_id)),
        input_(std::move(input)),
        preceding_text_(std::move(preceding_text)),
        previous_word_(std::move(previous_word)),
        scoring_policy_(std::move(scoring_policy)),
        recorder_session_(std::move(recorder_session)),
        segment_start_(segment_start),
        record_snapshots_(record_snapshots),
        snapshot_only_(snapshot_only) {}

 protected:
  virtual bool Replenish();

 private:
  bool RerankWindow(const vector<an<Candidate>>& buffer,
                    bool truncated,
                    CandidateQueue* out);

  an<Scorer> scorer_;
  an<EvidenceScorer> evidence_scorer_;
  bool evidence_active_ = false;
  path facts_root_;
  int window_;
  int deadline_ms_ = 200;
  std::function<std::chrono::steady_clock::time_point()> now_;
  string schema_id_;
  string input_;
  string preceding_text_;
  string previous_word_;
  RerankScoringPolicy scoring_policy_;
  std::shared_ptr<RecorderSession> recorder_session_;
  size_t segment_start_ = 0;
  // When reranking is off but recording is on, the translation still wraps
  // the upstream stream so the recorder's competition snapshots keep flowing;
  // it never scores or reorders.
  bool record_snapshots_ = false;
  bool snapshot_only_ = false;
  // Accumulated pre-rerank competition materialization for the recorder.
  vector<RecordedCandidate> materialized_;
  size_t next_merge_order_ = 0;
  bool fully_materialized_ = false;
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

  if (recorder_session_ && record_snapshots_) {
    // Snapshot the materialized window for the recorder: candidates in the
    // order they arrived from upstream (original merge order), after
    // upstream dedup. A window that was not fully pulled leaves the
    // competition set marked incomplete.
    for (const auto& cand : buffer) {
      RecordedCandidate recorded;
      recorded.merge_order = next_merge_order_++;
      recorded.start = cand->start();
      recorded.end = cand->end();
      auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(cand));
      const string source_type = phrase ? phrase->type() : cand->type();
      recorded.category = CategoryOf(source_type);
      recorded.text = cand->text();
      materialized_.push_back(std::move(recorded));
    }
    bool truncated =
        (int)buffer.size() >= window_ && !translation_->exhausted();
    fully_materialized_ = fully_materialized_ || !truncated;
    CompetitionSnapshot snapshot;
    snapshot.segment_start = segment_start_;
    snapshot.preceding_text = preceding_text_;
    snapshot.candidates = materialized_;
    snapshot.complete = fully_materialized_;
    recorder_session_->PushSnapshot(std::move(snapshot));
  }

  bool truncated = (int)buffer.size() >= window_ && !translation_->exhausted();
  CandidateQueue result;
  if (snapshot_only_) {
    // Reranking disabled: emit in original order, no synchronous scoring.
    for (auto& c : buffer)
      result.push_back(c);
    cache_.splice(cache_.end(), result);
    return !cache_.empty();
  }
  bool reranked = false;
  if (!scorer_) {
    LogWindowFailure("scoring_unavailable", "score", buffer.size());
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
  vector<size_t> scored_indexes;
  vector<an<Candidate>> scored_candidates;
  vector<string> texts;
  for (const auto& group : *plan.groups) {
    if (!*group.complete)
      continue;
    for (size_t index : *group.candidate_indexes) {
      scored_indexes.push_back(index);
      scored_candidates.push_back(buffer[index]);
      texts.push_back(buffer[index]->text());
    }
  }
  ScoringRequest request{*plan.identity, *scoring_policy_.baseline_policy_id,
                         *plan.preceding_text, std::move(texts)};
  vector<ScoreComponents> batch_scores;
  if (!scorer_->ScoreBatch(request, scored_candidates, &batch_scores) ||
      batch_scores.size() != scored_candidates.size()) {
    LogWindowFailure("batch_scoring_failed", "score", buffer.size());
    return false;
  }
  vector<ScoreComponents> scores(buffer.size());
  for (size_t i = 0; i < scored_indexes.size(); ++i)
    scores[scored_indexes[i]] = batch_scores[i];

  // Retrieval evidence (#61): one evidence request per complete rerank group
  // (each group is one choice problem). The plugin applies gamma * s_c only
  // on a complete, identity-bound success; any fault passes the whole window
  // through in original order.  All groups in this window share one absolute
  // deadline (connect/write/read included); later groups see only leftover
  // budget.  The trial envelope (#74) rides along: the plugin's γ=0 base
  // scores for this group, so the daemon can replay the same group with γ=0
  // (shadow) and with the served evidence (final) and record an identity-only
  // order-change trace (or aggregates only).  Each complete group is one
  // complete-comparable request (#152); incomplete groups are skipped.
  if (evidence_active_) {
    if (!evidence_scorer_) {
      LogWindowFailure("evidence_unavailable", "evidence", buffer.size());
      return false;
    }
    EvidenceScorer::FactHighWater high_water;
    EvidenceScorer::ReadFactHighWater(
        facts_root_.empty() ? FactStore::DefaultRootDir() : facts_root_,
        &high_water);
    const auto window_deadline =
        NowOr(now_) + std::chrono::milliseconds(deadline_ms_);
    for (const auto& group : *plan.groups) {
      if (!*group.complete)
        continue;
      EvidenceScorer::GroupRequest evidence_request;
      evidence_request.plan_identity = *plan.identity;
      evidence_request.schema_id = schema_id_;
      evidence_request.category = *group.category;
      evidence_request.canonical_segment_input = *group.canonical_input;
      evidence_request.preceding_text = *plan.preceding_text;
      evidence_request.config_identity = *scoring_policy_.retrieval_policy_id;
      evidence_request.fact_high_water = high_water;
      for (size_t index : *group.candidate_indexes) {
        evidence_request.candidate_texts.push_back(buffer[index]->text());
        evidence_request.trial.present = true;
        evidence_request.trial.complete_comparable = true;
        evidence_request.trial.base_scores.push_back(scores[index].base_score);
      }
      vector<double> group_evidence;
      const int remaining = RemainingDeadlineMs(window_deadline, now_);
      if (remaining <= 0 ||
          !evidence_scorer_->ScoreGroup(evidence_request, &group_evidence,
                                        remaining) ||
          group_evidence.size() != group.candidate_indexes->size()) {
        LogWindowFailure("evidence_scoring_failed", "evidence",
                         buffer.size());
        return false;
      }
      for (size_t i = 0; i < group.candidate_indexes->size(); ++i)
        scores[(*group.candidate_indexes)[i]].retrieval_evidence =
            group_evidence[i];
    }
  }

  RerankScoreResult result;
  result.version = kRerankScoreResultVersion;
  result.plan_identity = plan.identity;
  result.candidate_scores = vector<RerankCandidateScore>();
  result.candidate_scores->reserve(buffer.size());
  for (size_t i = 0; i < buffer.size(); ++i) {
    result.candidate_scores->push_back(MakeRerankCandidateScore(
        scores[i].base_score, scores[i].retrieval_evidence,
        *scoring_policy_.gamma));
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
  // Immutable per-instance switch snapshot (spec "三个配置开关"): resolved at
  // Engine/schema instance creation, never re-read mid-composition. New
  // sessions adopt new config after redeploy.
  SwitchConfig switches = ResolveSwitchConfig(
      ticket.schema->config() ? ticket.schema->config() : nullptr,
      name_space_);
  config_source_ = switches.source;
  reranking_enabled_ = switches.reranking_enabled;
  recording_enabled_ = switches.recording_enabled;
  evidence_enabled_ = switches.evidence_enabled;
  if (switches.deprecation_warning) {
    LOG(WARNING) << name_space_
                 << ": legacy 'enable' key is deprecated and ignored; v2 "
                    "switch keys take precedence";
  }
  if (Config* config = ticket.schema->config()) {
    config->GetInt(name_space_ + "/window", &window_);
    config->GetDouble(name_space_ + "/alpha", &alpha_);
    config->GetString(name_space_ + "/baseline_policy_id",
                      &baseline_policy_id_);
    config->GetDouble(name_space_ + "/sys_coeff", &sys_coeff_);
    config->GetDouble(name_space_ + "/usr_coeff", &usr_coeff_);
    config->GetDouble(name_space_ + "/gamma", &gamma_);
    config->GetDouble(name_space_ + "/saturate_k", &saturate_k_);
    config->GetInt(name_space_ + "/deadline_ms", &deadline_ms_);
    config->GetBool(name_space_ + "/verbose", &verbose_);
    config->GetString(name_space_ + "/socket_path", &socket_path_);
    config->GetString(name_space_ + "/representation_id",
                      &representation_id_);
    config->GetDouble(name_space_ + "/tau", &tau_);
    config->GetInt(name_space_ + "/k_evidence", &k_evidence_);
    config->GetDouble(name_space_ + "/half_life", &half_life_);
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
  // Reranking disabled -> the key hot path must not do synchronous model
  // scoring: no LLM scorer is built at all (no socket handle, no attempts).
  // Recording and snapshot production can still continue independently.
  if (reranking_enabled_ && alpha_ > 0.0 && !socket_path_.empty()) {
    llm_scorer_ = New<LlmScorer>(socket_path_, alpha_, verbose_, deadline_ms_);
  }
  // Evidence application (v2): only the explicit `evidence_enabled` switch
  // admits the semantic retrieval evidence term. Legacy and not_configured
  // keep the first-stage base behavior (weight + LLM, no evidence term).
  evidence_active_ =
      (config_source_ == SwitchConfigSource::kV2 && evidence_enabled_ &&
       gamma_ > 0.0);
  if (evidence_active_) {
    evidence_config_identity_ = EvidenceScorer::ComposeConfigIdentity(
        representation_id_, tau_, k_evidence_, half_life_, saturate_k_,
        gamma_);
    if (representation_id_.empty() || socket_path_.empty()) {
      LOG(WARNING) << name_space_
                   << ": evidence enabled but representation seam is not "
                      "configured; evidence requests will fail closed";
    } else {
      evidence_scorer_ = New<EvidenceScorer>(socket_path_,
                                             evidence_config_identity_,
                                             deadline_ms_, verbose_);
    }
  }
  if (llm_scorer_)
    scorer_ = New<CompositeScorer>(weight_scorer, llm_scorer_);
  if (alpha_ > 0.0 && !llm_scorer_) {
    LOG(WARNING) << name_space_ << ": LLM scoring unavailable";
    scorer_.reset();
  }
  if (engine_) {
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
    recorder_session_ = RecorderSessionRegistry::GetForEngine(engine_);
  }
  LOG(INFO) << name_space_ << ": source = "
            << SwitchConfigSourceName(config_source_)
            << ", reranking = " << (reranking_enabled_ ? "true" : "false")
            << ", recording = " << (recording_enabled_ ? "true" : "false")
            << ", evidence = " << (evidence_enabled_ ? "true" : "false")
            << ", evidence_active = " << (evidence_active_ ? "true" : "false")
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
  if (!HasNonAscii(selected))
    return;
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
  // With reranking off, the translation passes through untouched unless the
  // recorder needs competition snapshots (recording can continue while the
  // visible reranking is disabled). No synchronous model scoring ever runs
  // on this path.
  const bool want_snapshots = recording_enabled_ && recorder_session_;
  if (!reranking_enabled_ && !want_snapshots) {
    return translation;
  }
  const string preceding_text = BuildContext();
  RerankScoringPolicy scoring_policy = DefaultRerankScoringPolicy();
  scoring_policy.baseline_policy_id = baseline_policy_id_;
  scoring_policy.alpha = alpha_;
  scoring_policy.sys_coeff = sys_coeff_;
  scoring_policy.usr_coeff = usr_coeff_;
  // v2 with evidence application off: the plan declares gamma = 0 so the
  // evidence term is exactly zero. Legacy and not_configured keep the
  // configured gamma (no evidence term exists on those paths).
  scoring_policy.gamma =
      (config_source_ == SwitchConfigSource::kV2 && !evidence_enabled_)
          ? 0.0
          : gamma_;
  scoring_policy.saturate_k = saturate_k_;
  // The plan binds the exact evidence config identity it was scored under;
  // the evidence request carries the same identity so the daemon serves only
  // a matching evidence configuration (AC61-1 "配置身份").
  if (evidence_active_)
    scoring_policy.retrieval_policy_id = evidence_config_identity_;
  string input = input_;
  if (engine_ && engine_->context())
    input = engine_->context()->input();
  size_t segment_start = 0;
  if (engine_ && engine_->context() &&
      !engine_->context()->composition().empty()) {
    segment_start = engine_->context()->composition().back().start;
  }
  return New<LlmRerankTranslation>(
      translation, reranking_enabled_ ? scorer_ : nullptr,
      evidence_active_ ? evidence_scorer_ : nullptr, evidence_active_,
      facts_root_, window_, deadline_ms_, now_, schema_id_, input,
      preceding_text, last_word_, scoring_policy, recorder_session_,
      segment_start, want_snapshots, !reranking_enabled_);
}

}  // namespace rime
