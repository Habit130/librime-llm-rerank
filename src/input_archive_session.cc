//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include "input_archive_session.h"

#include <unistd.h>

#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <utility>

#include <rime/config.h>
#include <rime/context.h>
#include <rime/engine.h>
#include <rime/schema.h>
#include <rime/gear/translator_commons.h>

namespace rime {
namespace {

std::mutex g_registry_mu;
std::unordered_map<Engine*, std::pair<std::shared_ptr<InputArchiveSession>, int>>
    g_sessions;
uint64_t g_next_source_ordinal = 0;

bool SafeToken(const string& value) {
  if (value.empty() || value.size() > 128)
    return false;
  for (unsigned char ch : value) {
    const bool ok = (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') ||
                    (ch >= '0' && ch <= '9') || ch == '_' || ch == '.' ||
                    ch == ':' || ch == '-';
    if (!ok)
      return false;
  }
  return true;
}

}  // namespace

string ReadInputArchiveSocket(Config* config) {
  if (!config)
    return string();
  string socket;
  if (!config->GetString("llm_rerank/input_archive/socket", &socket))
    return string();
  if (socket.empty() || socket[0] != '/')
    return string();
  return socket;
}

InputArchiveSession::InputArchiveSession(string socket_path,
                                         string source_instance_id)
    : producer_(new InputArchiveProducer(std::move(socket_path),
                                         source_instance_id)),
      source_instance_id_(std::move(source_instance_id)) {
  segment_id_ = NextToken("seg");
  process_id_ = NextToken("pproc");
}

InputArchiveSession::~InputArchiveSession() = default;

string InputArchiveSession::NextToken(const char* prefix) {
  sequence_ += 1;
  return string(prefix) + "-" + source_instance_id_ + "-" +
         std::to_string(sequence_);
}

int64_t InputArchiveSession::NextSequence() {
  sequence_ += 1;
  return sequence_;
}

void InputArchiveSession::CutContinuity(const char* basis) {
  segment_id_ = NextToken("seg");
  content_excluded_ = true;
  held_groups_.clear();
  window_have_plan_ = false;
  explicit_selection_ = false;
  selected_text_.clear();
  (void)basis;
}

void InputArchiveSession::CloseComposition(Engine* engine) {
  // The recorder notifier runs while the menu still owns the demand
  // translation. Flush before clearing, or the later destructor flush sees
  // an empty window and the completed composition loses competition/emission.
  FlushDemand(engine);
  composition_open_ = false;
  content_excluded_ = false;
  explicit_selection_ = false;
  selected_text_.clear();
  held_groups_.clear();
  window_have_plan_ = false;
  demand_.clear();
  demand_exhausted_ = false;
  process_id_ = NextToken("pproc");
  parent_update_id_.clear();
}

InputArchiveSession::EntryContext InputArchiveSession::ReadEntry(
    Engine* engine) const {
  EntryContext entry;
  if (!engine || !engine->context())
    return entry;
  Context* ctx = engine->context();
  const string association = ctx->get_property("squirrel_archive_association");
  const string source = ctx->get_property("squirrel_archive_source");
  const string process = ctx->get_property("squirrel_archive_process");
  const string update = ctx->get_property("squirrel_archive_update");
  const string segment = ctx->get_property("squirrel_archive_segment");
  if (association.empty() && source.empty() && process.empty() &&
      update.empty() && segment.empty()) {
    return entry;
  }
  if (!SafeToken(source) || !SafeToken(process) || !SafeToken(update) ||
      !SafeToken(segment)) {
    entry.role = "invalid";
    entry.read = "malformed";
    return entry;
  }
  entry.source = source;
  entry.process = process;
  entry.update = update;
  entry.segment = segment;
  if (association != "valid") {
    entry.role = "invalid";
    entry.read = "invalid";
    return entry;
  }
  entry.role = "engine_entry_context";
  entry.read = "claimed_valid";
  return entry;
}

string InputArchiveSession::SchemaId(Engine* engine) const {
  if (!engine || !engine->schema())
    return "unknown";
  const string id = engine->schema()->schema_id();
  return id.empty() ? "unknown" : id;
}

bool InputArchiveSession::ContentEligible(Engine* engine,
                                          string* schema,
                                          bool* secure) const {
  *schema = SchemaId(engine);
  *secure = InputArchiveProducer::SecureInputActive();
  if (*secure)
    return false;
  return *schema == "luna_pinyin";
}

void InputArchiveSession::FillEntry(InputArchiveObservation* observation,
                                    const EntryContext& entry) const {
  observation->association_role = entry.role;
  observation->association_read = entry.read;
  observation->referenced_source_id = entry.source;
  observation->referenced_process_id = entry.process;
  observation->referenced_update_id = entry.update;
  observation->referenced_segment_id = entry.segment;
  observation->continuity_segment_id = segment_id_;
  observation->source_instance_id = source_instance_id_;
  observation->process_id = process_id_;
  observation->parent_update_id = parent_update_id_;
}

void InputArchiveSession::Admit(InputArchiveObservation observation) {
  observation.source_local_sequence = NextSequence();
  observation.update_id = string("pupd-") + source_instance_id_ + "-" +
                          std::to_string(observation.source_local_sequence);
  parent_update_id_ = observation.update_id;
  producer_->TryAdmit(std::move(observation));
}

void InputArchiveSession::AdmitExclusion(Engine* engine, const char* basis) {
  content_excluded_ = true;
  if (!composition_open_)
    composition_open_ = true;
  InputArchiveObservation notice;
  notice.observation_kind = "exclusion_notice";
  notice.schema_id = "unknown";
  notice.eligibility = "excluded";
  notice.reason = "deliberate_exclusion";
  notice.outcome = "unknown";
  notice.coverage = "unknown";
  notice.coverage_basis = basis;
  FillEntry(&notice, ReadEntry(engine));
  notice.payload_text.clear();
  notice.preceding_text.clear();
  notice.input_text.clear();
  notice.candidates.clear();
  Admit(std::move(notice));
}

void InputArchiveSession::ObserveMaterializedWindow(
    Engine* engine, const ArchiveWindowFact& fact) {
  string schema;
  bool secure = false;
  const bool eligible = ContentEligible(engine, &schema, &secure);
  if (!producer_->locally_effective() || !eligible || content_excluded_) {
    content_excluded_ = true;
    composition_open_ = true;
    if (producer_->locally_effective())
      AdmitExclusion(engine, secure ? "secure_input" : "unsupported_schema");
    return;
  }
  composition_open_ = true;
  window_serial_ += 1;
  window_id_ = string("win-") + source_instance_id_ + "-" +
               std::to_string(window_serial_);
  plan_identity_ = fact.plan_identity;
  window_truncated_ = fact.truncated;
  window_have_plan_ = fact.have_plan;
  held_groups_.clear();
  const EntryContext entry = ReadEntry(engine);
  bool any_weight = false;
  bool missing_weight = false;
  bool any_quality = false;
  bool missing_quality = false;
  bool any_lm = false;
  bool missing_lm = false;
  bool any_evidence = false;
  bool missing_evidence = false;
  InputArchiveObservation competition;
  competition.plugin_stage = "competition";
  competition.schema_id = schema;
  competition.coverage = fact.have_plan ? "incomplete" : "unknown";
  competition.coverage_basis = fact.have_plan
                                   ? (fact.truncated ? "window_truncated"
                                                     : "captured_competition_target_absent")
                                   : "ordinary_materialized_window_not_a_group";
  competition.target_membership = "absent";
  competition.apply_state = "not_applicable";
  competition.lm_request_state = "no_request";
  competition.window_id = window_id_;
  competition.plan_identity = fact.plan_identity;
  competition.input_text = fact.input_text;
  competition.preceding_text = fact.preceding_text;
  competition.captured_candidate_count = static_cast<int>(fact.upstream.size());
  for (size_t i = 0; i < fact.upstream.size(); ++i) {
    const auto& item = fact.upstream[i];
    InputArchiveCandidate candidate;
    candidate.merge_order = static_cast<int>(item.merge_order);
    candidate.start = static_cast<int>(item.start);
    candidate.end = static_cast<int>(item.end);
    candidate.category = item.category;
    candidate.text = item.text;
    candidate.weight_known = item.weight_known;
    candidate.weight = item.weight;
    candidate.quality_known = item.quality_known;
    candidate.quality = item.quality;
    candidate.lm_known = item.lm_known;
    candidate.lm_score = item.lm_score;
    candidate.evidence_known = item.evidence_known;
    candidate.evidence = item.evidence;
    any_weight = any_weight || item.weight_known;
    missing_weight = missing_weight || !item.weight_known;
    any_quality = any_quality || item.quality_known;
    missing_quality = missing_quality || !item.quality_known;
    any_lm = any_lm || item.lm_known;
    missing_lm = missing_lm || !item.lm_known;
    any_evidence = any_evidence || item.evidence_known;
    missing_evidence = missing_evidence || !item.evidence_known;
    competition.candidates.push_back(std::move(candidate));
    competition.upstream_order.push_back(static_cast<int>(i));
    if (!competition.payload_text.empty())
      competition.payload_text += " / ";
    competition.payload_text += item.text;
  }
  for (const auto& group : fact.groups) {
    InputArchiveGroup stored;
    stored.identity = group.identity;
    stored.start = static_cast<int>(group.start);
    stored.end = static_cast<int>(group.end);
    stored.category = group.category;
    stored.plan_complete = group.plan_complete;
    HeldGroup held;
    held.identity = group.identity;
    held.start = group.start;
    held.end = group.end;
    held.category = group.category;
    held.plan_complete = group.plan_complete;
    held.truncated = fact.truncated;
    for (size_t index : group.member_indexes) {
      stored.member_indexes.push_back(static_cast<int>(index));
      if (index < fact.upstream.size())
        held.texts.push_back(fact.upstream[index].text);
    }
    held_groups_.push_back(std::move(held));
    competition.groups.push_back(std::move(stored));
  }
  if (!fact.groups.empty()) {
    competition.group_id = fact.groups.front().identity;
    competition.group_member_count =
        static_cast<int>(fact.groups.front().member_indexes.size());
  }
  competition.score_weight_state = any_weight && !missing_weight ? "observed" : "unknown";
  competition.score_quality_state =
      any_quality && !missing_quality ? "observed" : "unknown";
  competition.score_lm_state = any_lm && !missing_lm ? "observed" : "unknown";
  competition.score_evidence_state =
      any_evidence && !missing_evidence ? "observed" : "unknown";
  if (any_weight && missing_weight)
    competition.score_weight_state = "unknown";
  FillEntry(&competition, entry);
  Admit(competition);

  InputArchiveObservation emission = competition;
  emission.plugin_stage = "emission";
  emission.candidates = competition.candidates;
  emission.groups = competition.groups;
  emission.emission_order.clear();
  bool same = fact.emission_order.size() == fact.upstream.size();
  for (size_t i = 0; i < fact.emission_order.size(); ++i) {
    emission.emission_order.push_back(static_cast<int>(fact.emission_order[i]));
    if (i >= fact.upstream.size() || fact.emission_order[i] != i)
      same = false;
  }
  emission.apply_state = fact.apply_state;
  emission.order_changed = fact.rerank_attempted && !same;
  emission.emission_matches_upstream = same;
  emission.lm_request_state = fact.lm_request_state;
  emission.lm_request_id = fact.lm_request_id;
  emission.plan_identity = fact.plan_identity;
  emission.coverage = competition.coverage;
  emission.coverage_basis = fact.have_plan ? "emission_of_materialized_window"
                                           : "ordinary_demand_not_a_group";
  emission.payload_text = competition.payload_text;
  FillEntry(&emission, entry);
  Admit(std::move(emission));
}

void InputArchiveSession::ObserveDemandCandidate(Engine* engine,
                                                 const an<Candidate>& candidate) {
  if (!candidate)
    return;
  string schema;
  bool secure = false;
  if (!producer_->locally_effective() || !ContentEligible(engine, &schema, &secure) ||
      content_excluded_) {
    content_excluded_ = true;
    demand_.clear();
    if (producer_->locally_effective())
      AdmitExclusion(engine, secure ? "secure_input" : "unsupported_schema");
    return;
  }
  composition_open_ = true;
  ArchiveCandidateFact fact;
  fact.merge_order = demand_.size();
  fact.start = candidate->start();
  fact.end = candidate->end();
  fact.text = candidate->text();
  auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(candidate));
  fact.category = phrase ? phrase->type() : candidate->type();
  if (fact.category == "phrase" || fact.category == "user_phrase" ||
      fact.category == "table" || fact.category == "user_table") {
    fact.category = "word";
  }
  if (phrase && (phrase->type() == "phrase" || phrase->type() == "user_phrase" ||
                 phrase->type() == "table" || phrase->type() == "user_table")) {
    fact.weight_known = true;
    fact.weight = phrase->weight();
  }
  fact.quality_known = true;
  fact.quality = candidate->quality();
  demand_.push_back(std::move(fact));
}

void InputArchiveSession::NoteDemandExhausted(Engine* engine, bool exhausted) {
  (void)engine;
  demand_exhausted_ = exhausted;
}

void InputArchiveSession::FlushDemand(Engine* engine) {
  if (demand_.empty())
    return;
  ArchiveWindowFact fact;
  fact.have_plan = false;
  fact.truncated = !demand_exhausted_;
  fact.rerank_attempted = false;
  fact.apply_state = "not_applicable";
  fact.lm_request_state = "no_request";
  fact.upstream = demand_;
  for (size_t i = 0; i < demand_.size(); ++i)
    fact.emission_order.push_back(i);
  if (engine && engine->context())
    fact.input_text = engine->context()->input();
  demand_.clear();
  demand_exhausted_ = false;
  ObserveMaterializedWindow(engine, fact);
}

void InputArchiveSession::ObserveTemporarySelection(Engine* engine, Context* ctx) {
  if (!ctx || ctx->composition().empty())
    return;
  const Segment& segment = ctx->composition().back();
  if (segment.status < Segment::kSelected)
    return;
  auto candidate = segment.GetSelectedCandidate();
  if (!candidate)
    return;
  string schema;
  bool secure = false;
  if (!ContentEligible(engine, &schema, &secure) || content_excluded_) {
    AdmitExclusion(engine, secure ? "secure_input" : "excluded_prefix");
    explicit_selection_ = false;
    return;
  }
  const bool reselected = explicit_selection_;
  explicit_selection_ = true;
  selected_text_ = candidate->text();
  selected_start_ = segment.start;
  selected_end_ = candidate->end() < segment.end ? candidate->end() : segment.end;
  auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(candidate));
  selected_category_ = phrase ? phrase->type() : candidate->type();
  if (selected_category_ == "phrase" || selected_category_ == "user_phrase" ||
      selected_category_ == "table" || selected_category_ == "user_table") {
    selected_category_ = "word";
  }
  InputArchiveObservation observation;
  observation.plugin_stage = "temporary_selection";
  observation.schema_id = schema;
  observation.submission = "explicit";
  observation.apply_state = "not_applicable";
  observation.lm_request_state = "no_request";
  observation.window_id = window_id_;
  observation.plan_identity = plan_identity_;
  observation.payload_text = selected_text_;
  observation.outcome = reselected ? "replacement" : "temporary_selection";
  observation.coverage = "unknown";
  observation.coverage_basis = "selection_without_complete_group";
  observation.target_membership = "unknown";
  for (const auto& group : held_groups_) {
    if (group.start != selected_start_ || group.end != selected_end_ ||
        group.category != selected_category_) {
      continue;
    }
    observation.group_id = group.identity;
    bool found = false;
    for (const auto& text : group.texts) {
      if (text == selected_text_)
        found = true;
    }
    observation.target_membership = found ? "present" : "absent";
    observation.captured_candidate_count = static_cast<int>(group.texts.size());
    observation.group_member_count = observation.captured_candidate_count;
    if (group.plan_complete && !group.truncated && found &&
        observation.captured_candidate_count >= 1) {
      observation.coverage = "complete";
      observation.coverage_basis = "captured_group_members_and_target";
    } else if (group.truncated) {
      observation.coverage = "incomplete";
      observation.coverage_basis = "window_truncated";
    } else if (!group.plan_complete) {
      observation.coverage = "incomplete";
      observation.coverage_basis = "group_incomplete";
    } else {
      observation.coverage = "incomplete";
      observation.coverage_basis = found ? "captured_competition_target_present"
                                         : "target_absent";
    }
    break;
  }
  FillEntry(&observation, ReadEntry(engine));
  Admit(std::move(observation));
}

void InputArchiveSession::ObserveCommit(Engine* engine, Context* ctx) {
  if (!ctx)
    return;
  FlushDemand(engine);
  const string text = ctx->GetCommitText();
  if (text.empty()) {
    retraction_armed_ = false;
    return;
  }
  string schema;
  bool secure = false;
  const bool policy_effective = producer_->locally_effective();
  const bool eligible = policy_effective &&
                        ContentEligible(engine, &schema, &secure) &&
                        !content_excluded_;
  InputArchiveObservation observation;
  observation.plugin_stage = "commit";
  observation.schema_id = eligible ? schema : "unknown";
  observation.eligibility = eligible ? "included" : "excluded";
  observation.observation_kind =
      eligible ? "plugin_observation" : "exclusion_notice";
  observation.submission =
      explicit_selection_ && text == selected_text_ ? "explicit" : "default";
  observation.apply_state = "not_applicable";
  observation.lm_request_state = "no_request";
  observation.window_id = window_id_;
  observation.plan_identity = plan_identity_;
  observation.outcome = "observed_attempt";
  observation.coverage = "unknown";
  observation.coverage_basis = "engine_commit_not_frontend_terminal";
  observation.target_membership = "unknown";
  if (eligible)
    observation.payload_text = text;
  else
    observation.reason =
        policy_effective ? "deliberate_exclusion" : "policy_not_effective";
  if (explicit_selection_ && text == selected_text_) {
    for (const auto& group : held_groups_) {
      if (group.start == selected_start_ && group.end == selected_end_ &&
          group.category == selected_category_) {
        observation.group_id = group.identity;
        observation.captured_candidate_count = static_cast<int>(group.texts.size());
        observation.group_member_count = observation.captured_candidate_count;
        bool found = false;
        for (const auto& item : group.texts) {
          if (item == text)
            found = true;
        }
        observation.target_membership = found ? "present" : "absent";
        if (group.plan_complete && !group.truncated && found &&
            observation.captured_candidate_count >= 1) {
          observation.coverage = "complete";
          observation.coverage_basis = "captured_group_members_and_target";
        }
        break;
      }
    }
  }
  FillEntry(&observation, ReadEntry(engine));
  Admit(observation);
  // An ineffective policy is an excluded prefix. Do not retain the commit
  // text for a later retraction after resume; that would backfill it.
  last_commit_text_ = eligible ? text : string();
  last_commit_update_ = parent_update_id_;
  last_commit_process_ = process_id_;
  explicit_selection_ = false;
  CloseComposition(engine);
  retraction_armed_ = true;
}

void InputArchiveSession::ObserveAbort(Engine* engine, Context* ctx) {
  (void)ctx;
  if (!composition_open_ && !explicit_selection_ && demand_.empty())
    return;
  FlushDemand(engine);
  string schema;
  bool secure = false;
  const bool policy_effective = producer_->locally_effective();
  const bool eligible = policy_effective &&
                        ContentEligible(engine, &schema, &secure) &&
                        !content_excluded_;
  InputArchiveObservation observation;
  observation.plugin_stage = "cancellation";
  observation.observation_kind =
      eligible ? "plugin_observation" : "exclusion_notice";
  observation.schema_id = eligible ? schema : "unknown";
  observation.eligibility = eligible ? "included" : "excluded";
  observation.outcome = "cancelled";
  observation.submission = "not_applicable";
  observation.coverage = "unknown";
  observation.coverage_basis = "engine_abort";
  observation.window_id = window_id_;
  if (eligible)
    observation.payload_text = selected_text_;
  else if (!policy_effective)
    observation.reason = "policy_not_effective";
  FillEntry(&observation, ReadEntry(engine));
  Admit(std::move(observation));
  retraction_armed_ = false;
  CloseComposition(engine);
}

void InputArchiveSession::ObserveUpdate(Engine* engine, Context* ctx) {
  if (!ctx)
    return;
  if (ctx->input().empty() && ctx->composition().empty()) {
    if (composition_open_ || content_excluded_ || !demand_.empty())
      CloseComposition(engine);
    return;
  }
  const string schema = SchemaId(engine);
  if (composition_open_ && schema != "luna_pinyin")
    CutContinuity("schema_or_source_change");
}

void InputArchiveSession::NoteInputKey(bool plain_backspace) {
  if (!retraction_armed_)
    return;
  retraction_pending_ = plain_backspace;
  if (!plain_backspace)
    retraction_armed_ = false;
}

void InputArchiveSession::ObserveRetraction(Engine* engine) {
  if (!retraction_armed_ || !retraction_pending_)
    return;
  retraction_armed_ = false;
  retraction_pending_ = false;
  InputArchiveObservation observation;
  observation.plugin_stage = "retraction";
  observation.outcome = "cancelled";
  observation.coverage = "unknown";
  observation.coverage_basis = "known_immediate_retraction";
  observation.submission = "not_applicable";
  observation.parent_update_id = last_commit_update_;
  if (!last_commit_text_.empty()) {
    observation.schema_id = "luna_pinyin";
    observation.payload_text = last_commit_text_;
    observation.observation_kind = "plugin_observation";
  } else {
    observation.observation_kind = "exclusion_notice";
    observation.schema_id = "unknown";
    observation.eligibility = "excluded";
    observation.reason = "deliberate_exclusion";
  }
  FillEntry(&observation, ReadEntry(engine));
  if (!last_commit_process_.empty())
    observation.process_id = last_commit_process_;
  observation.parent_update_id = last_commit_update_;
  Admit(std::move(observation));
  last_commit_text_.clear();
}

std::shared_ptr<InputArchiveSession> InputArchiveRegistry::Acquire(
    Engine* engine, const string& socket_path) {
  if (!engine || socket_path.empty())
    return nullptr;
  std::lock_guard<std::mutex> guard(g_registry_mu);
  auto found = g_sessions.find(engine);
  if (found != g_sessions.end()) {
    found->second.second += 1;
    return found->second.first;
  }
  // Map size repeats ps<pid>e1 after sequential destroy/create and can
  // collide with a live engine when a hole is reused. The ordinal is
  // process-lifetime and only advances under the registry lock.
  string source = string("ps") + std::to_string(getpid()) + "e" +
                  std::to_string(++g_next_source_ordinal);
  auto session = std::make_shared<InputArchiveSession>(socket_path, source);
  g_sessions[engine] = std::make_pair(session, 1);
  return session;
}

void InputArchiveRegistry::Release(Engine* engine) {
  if (!engine)
    return;
  std::shared_ptr<InputArchiveSession> dropped;
  {
    std::lock_guard<std::mutex> guard(g_registry_mu);
    auto found = g_sessions.find(engine);
    if (found == g_sessions.end())
      return;
    found->second.second -= 1;
    if (found->second.second > 0)
      return;
    dropped = found->second.first;
    g_sessions.erase(found);
  }
  if (dropped && dropped->producer())
    dropped->producer()->AbandonQueue();
}

void InputArchiveRegistry::ShutdownAll() {
  std::unordered_map<Engine*, std::pair<std::shared_ptr<InputArchiveSession>, int>>
      taken;
  {
    std::lock_guard<std::mutex> guard(g_registry_mu);
    taken.swap(g_sessions);
  }
  for (auto& item : taken) {
    if (item.second.first && item.second.first->producer())
      item.second.first->producer()->AbandonQueue();
  }
}

std::shared_ptr<InputArchiveSession> InputArchiveRegistry::Find(Engine* engine) {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  auto found = g_sessions.find(engine);
  if (found == g_sessions.end())
    return nullptr;
  return found->second.first;
}

void InputArchiveRegistry::SetSecureInputOverrideForTesting(int mode) {
  InputArchiveProducer::SetSecureInputOverrideForTesting(mode);
}

void InputArchiveRegistry::SetQueueLimitsForTesting(int count, int bytes) {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  for (auto& item : g_sessions) {
    if (item.second.first && item.second.first->producer())
      item.second.first->producer()->SetQueueLimitsForTesting(count, bytes);
  }
}

void InputArchiveRegistry::HoldWorkersForTesting(const string& fifo) {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  for (auto& item : g_sessions) {
    if (item.second.first && item.second.first->producer())
      item.second.first->producer()->HoldWorkerForTesting(fifo);
  }
}

void InputArchiveRegistry::PollForTesting() {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  for (auto& item : g_sessions) {
    if (item.second.first && item.second.first->producer())
      item.second.first->producer()->PollPolicyForTesting();
  }
}

void InputArchiveRegistry::ResetContinuityForTesting() {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  for (auto& item : g_sessions) {
    if (!item.second.first)
      continue;
    item.second.first->CloseCompositionForTesting();
  }
}

int InputArchiveRegistry::EffectiveForTesting() {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  int count = 0;
  int effective = 0;
  for (auto& item : g_sessions) {
    ++count;
    if (item.second.first && item.second.first->producer() &&
        item.second.first->producer()->locally_effective())
      ++effective;
  }
  return count * 100 + effective;
}

bool InputArchiveRegistry::FlushForTesting(int timeout_ms) {
  std::vector<std::shared_ptr<InputArchiveSession>> sessions;
  {
    std::lock_guard<std::mutex> guard(g_registry_mu);
    for (auto& item : g_sessions)
      sessions.push_back(item.second.first);
  }
  bool ok = true;
  for (auto& session : sessions) {
    if (session && session->producer())
      ok = session->producer()->FlushForTesting(timeout_ms) && ok;
  }
  return ok;
}

void InputArchiveRegistry::RetargetForTesting(const string& socket_path) {
  std::lock_guard<std::mutex> guard(g_registry_mu);
  for (auto& item : g_sessions) {
    if (item.second.first && item.second.first->producer())
      item.second.first->producer()->RetargetForTesting(socket_path);
  }
}

}  // namespace rime
