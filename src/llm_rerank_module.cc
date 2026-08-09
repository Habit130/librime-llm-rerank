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

RIME_REGISTER_MODULE(llm_rerank)
