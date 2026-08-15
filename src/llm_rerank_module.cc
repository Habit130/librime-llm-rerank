//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <rime/common.h>
#include <rime/component.h>
#include <rime/registry.h>
#include <rime_api.h>

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

RIME_REGISTER_MODULE(llm_rerank)
