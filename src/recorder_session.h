//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_RECORDER_SESSION_H_
#define RIME_RECORDER_SESSION_H_

#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include <rime/common.h>

#include "fact_store.h"

namespace rime {

class Engine;

// How the user confirmed a selection, per spec "选择事件成立边界":
// `explicit_current` covers space/Return confirming the highlighted candidate;
// `explicit_indexed` covers digit keys, custom select keys, and mouse clicks.
// Any other trigger (punctuation, auto-select during letter typing, API
// selection without a key event) forms no event.
enum class ConfirmationSource { kNone, kExplicitCurrent, kExplicitIndexed };

const char* ConfirmationSourceName(ConfirmationSource source);

// Plugin-wide small utilities: a random 128-bit identifier (hex text) and the
// current UTC time in milliseconds.
string RandomUuid();
int64_t NowMs();

// Pure classification rule, testable without an engine. `key_in_flight` is
// true only when the select notifier fires synchronously inside the key event
// that triggered it; a mouse/API selection has no key in flight and is always
// explicit_indexed.
ConfirmationSource ClassifyConfirmationSource(int keycode,
                                              bool key_in_flight,
                                              const string& select_keys);

// One competition candidate as materialized before reranking.
struct RecordedCandidate {
  size_t merge_order = 0;
  size_t start = 0;
  size_t end = 0;
  string category;
  string text;
};

// Pre-rerank competition snapshot for one segment, captured by the rerank
// filter when candidates are materialized.
struct CompetitionSnapshot {
  size_t segment_start = 0;
  string preceding_text;
  vector<RecordedCandidate> candidates;
  bool complete = false;  // false when the upstream list was not fully pulled
};

// A tentative selection event formed at confirm time; persisted only if the
// composition is committed with the selection still in place.
struct PendingEvent {
  size_t segment_start = 0;
  string canonical_segment_input;
  size_t span_start = 0;
  size_t span_end = 0;
  string category;
  string preceding_text;
  vector<RecordedCandidate> competition;
  bool competition_complete = false;
  string final_selection_text;
  ConfirmationSource source = ConfirmationSource::kNone;
  int trigger_keycode = -1;
  int display_rank = 0;
  int display_page = 0;
  string event_id;
  string session_id;
  int session_seq = 0;
  int64_t utc_confirmed_at_ms = 0;
  uint64_t confirm_seq = 0;  // creation order, used for HLC ordering
};

// Per-engine session state shared by the recorder processor (which owns it)
// and the rerank filter (which pushes competition snapshots into it). One
// instance per engine; created by the recorder, resolved through the
// registry. Not thread-safe by itself; a librime engine processes keys on one
// thread.
class RecorderSession {
 public:
  RecorderSession(string schema_id, int page_size, string select_keys);

  // Immutable configuration snapshot.
  string schema_id;
  int page_size;
  string select_keys;
  // Anonymous session identity for event rows.
  string session_id;

  void PushSnapshot(CompetitionSnapshot snapshot);
  void ClearSnapshots();
  void DropPending();
  void ReplacePending(PendingEvent event);  // keyed by segment_start

  // mutable recording state
  std::map<size_t, CompetitionSnapshot> snapshots;
  std::map<size_t, PendingEvent> pending;
  uint64_t next_confirm_seq = 0;
  int session_seq = 0;
  std::unique_ptr<FactStore> store;
  string fault_code;  // stable code; empty means healthy
  int gap_count = 0;
};

// Resolves the RecorderSession for an engine. The recorder processor creates
// and registers it in its constructor and removes it in its destructor; the
// filter only reads. Returns null when the schema has no recorder processor.
class RecorderSessionRegistry {
 public:
  static std::shared_ptr<RecorderSession> GetForEngine(Engine* engine);
  static void Register(Engine* engine, std::shared_ptr<RecorderSession> session);
  static void Unregister(Engine* engine);

 private:
  static std::mutex& mutex();
};

}  // namespace rime

#endif  // RIME_RECORDER_SESSION_H_
