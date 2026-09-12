//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_APPLY_OUTCOME_H_
#define RIME_APPLY_OUTCOME_H_

#include <rime/common.h>

namespace rime {

// Client emission outcome for one rerank window. "computed" is the daemon
// plan existing; it is not stored here and never proves display.
// Missing acknowledgment is unknown, not success.
const char kApplyStateApplied[] = "applied";
const char kApplyStateFallback[] = "fallback";
const char kApplyStateUnknown[] = "unknown";

struct WindowApplyRecord {
  size_t segment_start = 0;
  string plan_identity;
  string config_identity;
  vector<string> request_ids;
  string apply_state;
};

bool IsAckApplyState(const string& apply_state);

// Best-effort identity-only JSONL under <facts_root>/traces/client_apply.jsonl.
// Never writes raw preceding text, candidate text, or embeddings. Failures
// return false and must not affect candidate emission or text commit.
bool AppendClientApplyRecord(const path& facts_root,
                             const WindowApplyRecord& record);

}  // namespace rime

#endif  // RIME_APPLY_OUTCOME_H_
