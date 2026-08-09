//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <algorithm>
#include <utility>

#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/config.h>
#include <rime/context.h>
#include <rime/engine.h>
#include <rime/key_event.h>
#include <rime/key_table.h>
#include <rime/schema.h>
#include <rime/segmentation.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_config.h"
#include "llm_rerank_recorder.h"
#include "recorder_coordinator.h"
#include "rerank_plan.h"

namespace rime {

namespace {

// Mirrors the filter's category classification (llm_rerank_filter.cc):
// system- and user-dictionary candidates are both `word`; everything else
// keeps its own type as the category.
string CategoryOfCandidate(const an<Candidate>& cand) {
  auto phrase = As<Phrase>(Candidate::GetGenuineCandidate(cand));
  const string& type = phrase ? phrase->type() : cand->type();
  if (type == "table" || type == "phrase" || type == "user_table" ||
      type == "user_phrase") {
    return "word";
  }
  return type;
}

// An unmodified BackSpace: no modifiers except Shift (a soft modifier that
// does not change the key's meaning), matching the memory.cc precedent.
bool IsPlainBackspace(const KeyEvent& key) {
  return key.keycode() == XK_BackSpace &&
         (key.modifier() & ~kShiftMask) == 0;
}

}  // namespace

LlmRerankRecorder::LlmRerankRecorder(const Ticket& ticket)
    : Processor(ticket) {
  // Switch resolution shared with the filter (llm_rerank_config.h): recording
  // is enabled only by an explicit v2 `recording_enabled: true`; legacy and
  // not_configured never record (user story 26: upgrades must not start
  // collecting silently).
  SwitchConfig switches = ResolveSwitchConfig(
      ticket.schema && ticket.schema->config()
          ? ticket.schema->config()
          : nullptr,
      "llm_rerank");
  const bool recording_enabled = switches.recording_enabled;
  recording_enabled_ = recording_enabled;
  if (switches.deprecation_warning) {
    LOG(WARNING) << "llm_rerank recorder: legacy 'enable' key is deprecated "
                    "and ignored; v2 switch keys take precedence";
  }
  const string schema_id = ticket.schema ? ticket.schema->schema_id() : "";
  const int page_size = ticket.schema ? ticket.schema->page_size() : 5;
  const string select_keys =
      ticket.schema ? ticket.schema->select_keys() : string();
  session_ = std::make_shared<RecorderSession>(schema_id, page_size,
                                               select_keys);
  RecorderSessionRegistry::Register(engine_, session_);

  if (!recording_enabled) {
    LOG(INFO) << "llm_rerank recorder: recording_enabled=false"
              << " source=" << SwitchConfigSourceName(switches.source)
              << " schema=" << schema_id;
    session_->fault_code = "";
  } else {
    // Initialize eagerly so a recording-enabled schema has a provable zero
    // event store, but do not retain the handle: its destructor closes SQLite
    // before releasing the shared maintenance lease.
    FactStore store(FactStore::DefaultRootDir());
    FactStore::Status status = store.Open();
    if (status != FactStore::Status::kOk) {
      session_->fault_code = FactStore::StatusCode(status);
      LOG(WARNING) << "llm_rerank recorder: code=recording_disabled"
                   << " reason=" << session_->fault_code
                   << " schema=" << schema_id;
    } else {
      session_->fault_code = "";
    }
  }
  if (Context* ctx = engine_ ? engine_->context() : nullptr) {
    // Front insertion is essential: the engine's own select handler runs
    // first with a plain connect() and may commit the composition right away
    // (`_auto_commit` in express_editor). The tentative event must exist
    // before the commit notifier fires, and the commit handler must run
    // before the engine delivers the committed text.
    select_connection_ = ctx->select_notifier().connect(
        [this](Context* c) { OnSelect(c); }, boost::signals2::at_front);
    commit_connection_ = ctx->commit_notifier().connect(
        [this](Context* c) { OnCommit(c); }, boost::signals2::at_front);
    abort_connection_ =
        ctx->abort_notifier().connect([this](Context* c) { OnAbort(c); });
    update_connection_ = ctx->update_notifier().connect(
        [this](Context* c) { OnContextUpdate(c); });
    unhandled_key_connection_ = ctx->unhandled_key_notifier().connect(
        [this](Context* c, const KeyEvent& key) { OnUnhandledKey(c, key); });
  }
  UpdateStatusProperties();
}

LlmRerankRecorder::~LlmRerankRecorder() {
  select_connection_.disconnect();
  commit_connection_.disconnect();
  abort_connection_.disconnect();
  update_connection_.disconnect();
  unhandled_key_connection_.disconnect();
  RecorderSessionRegistry::Unregister(engine_);
}

ProcessResult LlmRerankRecorder::ProcessKeyEvent(const KeyEvent& key_event) {
  // A new key means the previous key's processing has finished; the select
  // notifier can only fire synchronously during the triggering key's
  // processing (mouse clicks and API selections fire outside any key event).
  key_in_flight_ = false;
  retraction_pending_ = false;
  if (!key_event.release() && retraction_armed_) {
    if (IsPlainBackspace(key_event)) {
      // The key may or may not be handled by the engine; if it ends up
      // unhandled, OnUnhandledKey retracts the armed commit.
      retraction_pending_ = true;
    } else {
      // Any other key press consumes the window: only the first key after a
      // commit counts as an immediate undo BackSpace. (Releases, e.g. of the
      // confirming key, never disarm.)
      retraction_armed_ = false;
    }
  }
  if (!key_event.release() && engine_ && engine_->context() &&
      engine_->context()->HasMenu() && session_ &&
      ClassifyConfirmationSource(key_event.keycode(), true,
                                 session_->select_keys) !=
          ConfirmationSource::kNone) {
    last_keycode_ = key_event.keycode();
    key_in_flight_ = true;
  }
  return kNoop;
}

void LlmRerankRecorder::OnSelect(Context* ctx) {
  if (!recording_enabled_ || !session_)
    return;
  if (!ctx)
    return;
  // This handler runs before the engine's own select handler (front
  // insertion), so the just-selected segment is still the last one and has
  // not been closed yet. Mirror Segment::Close()'s span adjustment: a
  // partially matched candidate shrinks the segment's end.
  if (ctx->composition().empty())
    return;
  Segment& seg = ctx->composition().back();
  if (seg.status < Segment::kSelected)
    return;
  auto cand = seg.GetSelectedCandidate();
  if (!cand)
    return;
  if (CategoryOfCandidate(cand) != "word")
    return;
  auto snap = session_->snapshots.find(seg.start);
  if (snap == session_->snapshots.end()) {
    LOG(WARNING) << "llm_rerank recorder: code=missing_competition_snapshot"
                 << " schema=" << session_->schema_id;
    return;
  }
  size_t span_end = seg.end;
  if (cand->end() < span_end)
    span_end = cand->end();
  vector<RecordedCandidate> competition;
  for (const auto& rc : snap->second.candidates) {
    if (rc.category == "word" && rc.start == seg.start && rc.end == span_end) {
      competition.push_back(rc);
    }
  }
  // A selection event requires real competition: at least two word candidates
  // in the same rerank group.
  if (competition.size() < 2)
    return;
  bool selected_present = false;
  for (const auto& rc : competition) {
    if (rc.text == cand->text()) {
      selected_present = true;
      break;
    }
  }
  if (!selected_present) {
    LOG(WARNING) << "llm_rerank recorder: code=selection_outside_snapshot"
                 << " schema=" << session_->schema_id;
    return;
  }
  int trigger_keycode = -1;
  ConfirmationSource source = ConfirmationSource::kNone;
  if (key_in_flight_) {
    trigger_keycode = last_keycode_;
    source = ClassifyConfirmationSource(last_keycode_, true,
                                        session_->select_keys);
  } else {
    source = ConfirmationSource::kExplicitIndexed;
  }
  if (source == ConfirmationSource::kNone)
    return;
  key_in_flight_ = false;

  PendingEvent event;
  event.segment_start = seg.start;
  event.span_start = seg.start;
  event.span_end = span_end;
  event.category = "word";
  event.preceding_text = snap->second.preceding_text;
  event.competition = std::move(competition);
  event.competition_complete = snap->second.complete;
  event.final_selection_text = cand->text();
  event.source = source;
  event.trigger_keycode = trigger_keycode;
  const size_t input_length = ctx->input().size();
  const size_t span_length =
      span_end <= input_length ? span_end - seg.start : 0;
  event.canonical_segment_input =
      CanonicalizeInput(ctx->input().substr(seg.start, span_length));
  const int page_size = session_->page_size > 0 ? session_->page_size : 5;
  event.display_rank = static_cast<int>(seg.selected_index % page_size) + 1;
  event.display_page =
      static_cast<int>(seg.selected_index / page_size) + 1;
  event.event_id = RandomUuid();
  event.session_id = session_->session_id;
  event.utc_confirmed_at_ms = NowMs();
  event.confirm_seq = session_->next_confirm_seq++;
  session_->ReplacePending(std::move(event));
}

void LlmRerankRecorder::OnCommit(Context* ctx) {
  if (!recording_enabled_ || !session_)
    return;
  if (!ctx || session_->pending.empty()) {
    // A commit with no tentative events (plain text, auto-selection) still
    // consumes any earlier retraction window: it is no longer the commit just
    // before the next BackSpace.
    retraction_armed_ = false;
    return;
  }
  // Validate the tentative events against the final composition: the segment
  // must still be selected with the same candidate. Reopened, replaced or
  // dropped segments fail this check and leave no record.
  vector<PendingEvent> valid;
  for (const auto& entry : session_->pending) {
    const Segment* seg = nullptr;
    for (const Segment& s : ctx->composition()) {
      if (s.start == entry.first) {
        seg = &s;
        break;
      }
    }
    if (!seg || seg->status < Segment::kSelected)
      continue;
    auto cand = seg->GetSelectedCandidate();
    if (!cand || cand->text() != entry.second.final_selection_text)
      continue;
    valid.push_back(entry.second);
  }
  if (valid.empty()) {
    session_->pending.clear();
    retraction_armed_ = false;
    return;
  }
  // HLC is assigned in confirmation order inside the commit transaction.
  std::sort(valid.begin(), valid.end(),
            [](const PendingEvent& a, const PendingEvent& b) {
              return a.confirm_seq < b.confirm_seq;
            });
  vector<FactStore::Event> events;
  events.reserve(valid.size());
  for (const auto& pending : valid) {
    FactStore::Event event;
    event.event_id = pending.event_id;
    event.schema_id = session_->schema_id;
    event.canonical_segment_input = pending.canonical_segment_input;
    event.span_start = pending.span_start;
    event.span_end = pending.span_end;
    event.category = pending.category;
    event.preceding_text = pending.preceding_text;
    event.competition_complete = pending.competition_complete;
    event.final_selection_text = pending.final_selection_text;
    event.confirmation_source = ConfirmationSourceName(pending.source);
    event.trigger_keycode = pending.trigger_keycode;
    event.display_rank = pending.display_rank;
    event.display_page = pending.display_page;
    event.session_id = pending.session_id;
    event.session_seq = ++session_->session_seq;
    event.utc_confirmed_at_ms = pending.utc_confirmed_at_ms;
    event.candidates.reserve(pending.competition.size());
    for (const auto& candidate : pending.competition) {
      event.candidates.push_back(
          {static_cast<int64_t>(candidate.merge_order), candidate.text});
    }
    events.push_back(std::move(event));
  }
  auto result = RecorderCoordinator::ForRoot(FactStore::DefaultRootDir())
                    .SubmitBatch(NowMs(), &events);
  if (result.outcome == RecorderCoordinator::Outcome::kGap) {
    ReportGap(result.fault_code.c_str());
    session_->pending.clear();
    retraction_armed_ = false;
    return;
  }
  session_->fault_code = "";
  for (const auto& pending : valid) {
    session_->pending.erase(pending.segment_start);
  }
  // Arm the immediate-undo window for the whole batch just persisted.
  retraction_commit_id_ = result.commit_id;
  retraction_armed_ = true;
  UpdateStatusProperties();
}

void LlmRerankRecorder::OnAbort(Context* ctx) {
  if (!session_)
    return;
  session_->DropPending();
  session_->ClearSnapshots();
}

void LlmRerankRecorder::OnContextUpdate(Context* ctx) {
  if (!session_ || !ctx)
    return;
  if (ctx->composition().empty()) {
    // The composition was cleared (Escape, API clear, abort): tentative
    // events and stale snapshots die with it.
    session_->DropPending();
    session_->ClearSnapshots();
  }
}

void LlmRerankRecorder::OnUnhandledKey(Context* ctx, const KeyEvent& key) {
  if (key.release())
    return;  // press-only: the confirming key's release must not trigger
  if (!retraction_pending_ || !retraction_armed_)
    return;
  if (!recording_enabled_ || !session_)
    return;
  retraction_pending_ = false;
  retraction_armed_ = false;
  auto result = RecorderCoordinator::ForRoot(FactStore::DefaultRootDir())
                    .SubmitRetraction(retraction_commit_id_, NowMs());
  if (result.outcome == RecorderCoordinator::Outcome::kGap) {
    ReportGap(result.fault_code.c_str());
    return;
  }
  session_->fault_code = "";
  LOG(INFO) << "llm_rerank recorder: code=retracted_commit"
            << " commit_id=" << retraction_commit_id_
            << " schema=" << session_->schema_id;
  UpdateStatusProperties();
}

void LlmRerankRecorder::ReportGap(const char* reason) {
  if (!session_)
    return;
  session_->gap_count += 1;
  LOG(WARNING) << "llm_rerank recorder: code=recording_gap"
               << " reason=" << reason
               << " gap_count=" << session_->gap_count
               << " schema=" << session_->schema_id;
  UpdateStatusProperties();
}

void LlmRerankRecorder::UpdateStatusProperties() {
  if (!session_ || !engine_ || !engine_->context())
    return;
  string fault =
      session_->fault_code.empty() ? "none" : session_->fault_code;
  string gaps = std::to_string(session_->gap_count);
  if (fault != last_fault_property_) {
    engine_->context()->set_property("llm_rerank.recording_fault", fault);
    last_fault_property_ = fault;
  }
  if (gaps != last_gap_property_) {
    engine_->context()->set_property("llm_rerank.recording_gap_count", gaps);
    last_gap_property_ = gaps;
  }
}

}  // namespace rime
