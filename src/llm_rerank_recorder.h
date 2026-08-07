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
  void ReportGap(const char* reason);
  void UpdateStatusProperties();

  std::shared_ptr<RecorderSession> session_;
  connection select_connection_;
  connection commit_connection_;
  connection abort_connection_;
  connection update_connection_;
  int last_keycode_ = 0;
  bool key_in_flight_ = false;
  string last_fault_property_;
  string last_gap_property_;
};

}  // namespace rime

#endif  // RIME_LLM_RERANK_RECORDER_H_
