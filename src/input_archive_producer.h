//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_INPUT_ARCHIVE_PRODUCER_H_
#define RIME_INPUT_ARCHIVE_PRODUCER_H_

#include <memory>
#include <string>
#include <vector>

#include <rime/common.h>

namespace rime {

// Owned snapshot admitted by the input path. The worker serializes it later.
// Text fields are copied here and are not logged.
struct InputArchiveCandidate {
  int merge_order = 0;
  int start = 0;
  int end = 0;
  string category;
  string text;
  bool weight_known = false;
  double weight = 0;
  bool quality_known = false;
  double quality = 0;
  bool lm_known = false;
  double lm_score = 0;
  bool evidence_known = false;
  double evidence = 0;
};

struct InputArchiveGroup {
  string identity;
  int start = 0;
  int end = 0;
  string category;
  bool plan_complete = false;
  vector<int> member_indexes;
};

struct InputArchiveObservation {
  string observation_kind = "plugin_observation";
  int plugin_observation_version = 1;
  string plugin_stage;
  string schema_id;
  string source_instance_id;
  int64_t source_local_sequence = 0;
  string process_id;
  string update_id;
  string parent_update_id;
  string continuity_segment_id;
  string outcome = "observed_attempt";
  string reason;
  string eligibility = "included";
  string association_role = "absent";
  string association_read = "absent";
  string referenced_source_id;
  string referenced_process_id;
  string referenced_update_id;
  string referenced_segment_id;
  string coverage = "unknown";
  string coverage_basis = "unspecified";
  string window_id;
  string group_id;
  string plan_identity;
  string lm_request_id;
  string lm_request_state = "no_request";
  string apply_state = "unknown";
  string submission = "not_applicable";
  string target_membership = "unknown";
  int captured_candidate_count = -1;
  int group_member_count = -1;
  bool order_changed = false;
  bool emission_matches_upstream = true;
  string score_weight_state = "unknown";
  string score_quality_state = "unknown";
  string score_lm_state = "unknown";
  string score_evidence_state = "unknown";
  string payload_text;
  string preceding_text;
  string input_text;
  vector<int> upstream_order;
  vector<int> emission_order;
  vector<InputArchiveCandidate> candidates;
  vector<InputArchiveGroup> groups;
  int binding_generation = 0;
  int retries = 0;
  int budget_bytes = 0;
  // Internal worker-owned dependency markers; never serialized.
  // retractable_commit marks a commit the session locally considered
  // eligible so the worker can bind its per-item collector result to a
  // possible immediate retraction. dependency_update_id marks a
  // content-free retraction intent that references the originating commit.
  bool retractable_commit = false;
  string dependency_update_id;
};

struct InputArchiveAdmission {
  bool admitted = false;
  string code;
  int64_t capture_seq = -1;
  bool durable = false;
};

// Bounded non-blocking admission. TryAdmit copies an owned snapshot and
// returns. It does not serialize, connect, or wait for the collector.
class InputArchiveProducer {
 public:
  InputArchiveProducer(string socket_path, string source_instance_id);
  ~InputArchiveProducer();

  InputArchiveProducer(const InputArchiveProducer&) = delete;
  InputArchiveProducer& operator=(const InputArchiveProducer&) = delete;

  InputArchiveAdmission TryAdmit(InputArchiveObservation observation);
  const string& source_instance_id() const;
  const string& socket_path() const;
  int binding_generation() const;
  bool destination_safe() const;
  bool locally_effective() const;

  void PollPolicyForTesting();
  bool FlushForTesting(int timeout_ms);
  void SetQueueLimitsForTesting(int count, int bytes);
  void HoldWorkerForTesting(const string& fifo);
  void RetargetForTesting(const string& socket_path);
  void AbandonQueue();

  static void SetSecureInputOverrideForTesting(int mode);
  static bool SecureInputActive();

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

int InputArchiveBudgetBytes(const InputArchiveObservation& observation);

}  // namespace rime

#endif  // RIME_INPUT_ARCHIVE_PRODUCER_H_
