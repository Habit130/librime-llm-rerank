//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_RECORDER_H_
#define RIME_LLM_RERANK_RECORDER_H_

#include <rime/processor.h>

#include <memory>

#include "recorder_session.h"

namespace rime {

class Context;
class KeyEvent;

// Observe-only processor that records explicit candidate selections into the
// local fact store. It never consumes key events (always returns kNoop). The
// event lifecycle follows the spec "选择事件生命周期 seam":
//
// - `select_notifier` creates or replaces a tentative per-segment event.
// - `commit_notifier` validates the final composition and persists still-valid
//   events atomically with the HLC advance, in one short transaction.
// - abort, composition reset (update with empty composition) and commit-time
//   validation drop tentative events that did not make it into the commit.
//
// Immediate undo: a commit that persisted events arms a retraction window
// bound to that commit. The next key press consumes it — an unmodified,
// unhandled BackSpace appends a retraction fact for the whole commit; any
// other key press (or another commit) disarms without retracting. Repeated
// BackSpace after the first is a no-op, so stepping back across older commits
// never happens silently.
//
// Recording is off by default (`llm_rerank/recording_enabled`, user story 26:
// upgrades must not start collecting raw preceding text silently).
class LlmRerankRecorder : public Processor {
 public:
  explicit LlmRerankRecorder(const Ticket& ticket);
  ~LlmRerankRecorder() override;

  ProcessResult ProcessKeyEvent(const KeyEvent& key_event) override;

 private:
  void OnSelect(Context* ctx);
  void OnCommit(Context* ctx);
  void OnAbort(Context* ctx);
  void OnContextUpdate(Context* ctx);
  void OnUnhandledKey(Context* ctx, const KeyEvent& key_event);
  void ReportGap(const char* reason);
  void UpdateStatusProperties();

  std::shared_ptr<RecorderSession> session_;
  connection select_connection_;
  connection commit_connection_;
  connection abort_connection_;
  connection update_connection_;
  connection unhandled_key_connection_;
  int last_keycode_ = 0;
  bool key_in_flight_ = false;
  string last_fault_property_;
  string last_gap_property_;
  // Immediate-undo window: armed by the last event-bearing commit, consumed
  // by the first key press after it.
  bool retraction_armed_ = false;
  bool retraction_pending_ = false;  // current key is a plain BackSpace
  string retraction_commit_id_;
  bool recording_enabled_ = false;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_RECORDER_H_
