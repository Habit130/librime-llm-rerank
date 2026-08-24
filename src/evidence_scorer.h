//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_EVIDENCE_SCORER_H_
#define RIME_EVIDENCE_SCORER_H_

#include <cstdint>
#include <string>
#include <vector>

#include <rime/common.h>

namespace rime {

// Plugin-side client for the daemon's retrieval-evidence protocol
// (Habit130/squirrel#61, AC61-1/AC61-2).  One request per rerank group: the
// daemon computes the canonical oracle's candidate-level evidence s_c from
// read-only facts with the configured injectable representation seam, and
// the plugin applies gamma * s_c to the base score only when the response is
// complete and identity-bound.  Any fault (transport, protocol, identity,
// watermark) makes ScoreGroup return false so the filter passes the whole
// window through in original order.
class EvidenceScorer {
 public:
  struct FactHighWater {
    bool present = false;
    string store_epoch;
    int64_t hlc_physical_ms = 0;
    int64_t hlc_logical = 0;
  };

  // Trial envelope (Habit130/squirrel#74): the plugin's γ=0 base scores for
  // desensitized trace recording.  The daemon replays the same group with
  // γ=0 (shadow) and with the served evidence (final) and compares the emit
  // orders.  Identity/numbers only -- never 上文, candidate text or
  // embeddings.
  struct Trial {
    bool actionable = false;       // request has a complete comparable group
    vector<double> base_scores;    // γ=0 scores, one per group candidate
    bool present = false;
  };

  struct GroupRequest {
    string plan_identity;
    string schema_id;
    string category;
    string canonical_segment_input;
    string preceding_text;  // last 64 chars of 上文, as the plan carries it
    string config_identity;
    FactHighWater fact_high_water;
    vector<string> candidate_texts;  // current group in merge order
    Trial trial;                     // #74; absent when !trial.present
  };

  EvidenceScorer(const string& socket_path,
                 const string& config_identity,
                 int deadline_ms = 200,
                 bool verbose = false)
      : socket_path_(socket_path),
        config_identity_(config_identity),
        deadline_ms_(deadline_ms),
        verbose_(verbose) {}

  // Returns per-candidate s_c in [0, 1) only on a complete, identity-bound
  // success response; zero evidence is a success with all-zero s_c.  Any
  // fault returns false.  remaining_deadline_ms is the leftover budget for
  // this group's connect/write/read; callers share one absolute window
  // deadline across groups.  The two-argument form uses the instance
  // deadline as a single-request budget.
  bool ScoreGroup(const GroupRequest& request, vector<double>* s_c) {
    return ScoreGroup(request, s_c, deadline_ms_);
  }
  virtual bool ScoreGroup(const GroupRequest& request,
                          vector<double>* s_c,
                          int remaining_deadline_ms);

  // Canonical evidence config identity shared with the daemon
  // (daemon/evidence.py compose_config_identity).  The double formatting must
  // stay byte-identical on both sides: defaultfloat, six significant digits,
  // "inf" for infinity.
  static string ComposeConfigIdentity(const string& representation_id,
                                      double tau,
                                      int k_evidence,
                                      double half_life,
                                      double saturation_k,
                                      double gamma);

  // Read-only fact high-water (store_epoch + max change HLC) for the request
  // watermark.  A missing store or unreadable meta leaves present=false (the
  // request then carries no watermark; the daemon serves its own snapshot).
  static bool ReadFactHighWater(const path& facts_root, FactHighWater* out);

 private:
  bool SendRequest(const GroupRequest& request,
                   const string& request_id,
                   int remaining_deadline_ms,
                   string* response);

  string socket_path_;
  string config_identity_;
  int deadline_ms_;
  bool verbose_;
};

}  // namespace rime

#endif  // RIME_EVIDENCE_SCORER_H_
