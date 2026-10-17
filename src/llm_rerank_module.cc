//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <rime/common.h>
#include <rime/component.h>
#include <rime/registry.h>
#include <rime_api.h>

#include "input_archive_session.h"
#include "llm_rerank_filter.h"
#include "llm_rerank_recorder.h"
#include "recorder_coordinator.h"

static void rime_llm_rerank_initialize() {
  using namespace rime;

  LOG(INFO) << "registering components from module 'llm_rerank'.";
  Registry& r = Registry::instance();
  r.Register("llm_rerank", new Component<LlmRerankFilter>);
  r.Register("llm_rerank_recorder", new Component<LlmRerankRecorder>);
}

static void rime_llm_rerank_finalize() {
  rime::InputArchiveRegistry::ShutdownAll();
  rime::RecorderCoordinator::ShutdownAll();
}

// The e2e binary links plugin objects for unit coverage while librime loads the
// production dylib for engine coverage. This C seam reaches the loaded dylib's
// worker so tests can establish a durable observation point without polling.
extern "C" void rime_llm_rerank_flush_recorder_for_testing(const char* root) {
  if (!root)
    return;
  rime::RecorderCoordinator::ForRoot(rime::path(root))->FlushForTesting();
}

extern "C" void rime_llm_rerank_shutdown_recorder_for_testing() {
  rime::RecorderCoordinator::ShutdownAll();
}

extern "C" void rime_llm_rerank_set_io_hook_for_testing(int (*hook)(const char*)) {
  rime::RecorderCoordinator::SetIOHookForTesting(
      hook ? rime::RecorderIOHook(hook) : rime::RecorderIOHook());
}

extern "C" void rime_llm_rerank_archive_set_secure_input_for_testing(int mode) {
  rime::InputArchiveRegistry::SetSecureInputOverrideForTesting(mode);
}

extern "C" void rime_llm_rerank_archive_set_queue_limits_for_testing(int count,
                                                                    int bytes) {
  rime::InputArchiveRegistry::SetQueueLimitsForTesting(count, bytes);
}

extern "C" void rime_llm_rerank_archive_hold_worker_for_testing(const char* fifo) {
  rime::InputArchiveRegistry::HoldWorkersForTesting(fifo ? fifo : "");
}

extern "C" void rime_llm_rerank_archive_poll_for_testing(void) {
  rime::InputArchiveRegistry::PollForTesting();
}

extern "C" int rime_llm_rerank_archive_flush_for_testing(int timeout_ms) {
  return rime::InputArchiveRegistry::FlushForTesting(timeout_ms) ? 1 : 0;
}

extern "C" int rime_llm_rerank_archive_effective_for_testing(void) {
  return rime::InputArchiveRegistry::EffectiveForTesting();
}

extern "C" void rime_llm_rerank_archive_reset_continuity_for_testing(void) {
  rime::InputArchiveRegistry::ResetContinuityForTesting();
}

extern "C" void rime_llm_rerank_archive_retarget_for_testing(const char* socket_path) {
  rime::InputArchiveRegistry::RetargetForTesting(socket_path ? socket_path : "");
}

RIME_REGISTER_MODULE(llm_rerank)
