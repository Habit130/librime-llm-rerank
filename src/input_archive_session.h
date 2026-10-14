//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_INPUT_ARCHIVE_SESSION_H_
#define RIME_INPUT_ARCHIVE_SESSION_H_

#include <memory>
#include <string>
#include <vector>

#include <rime/common.h>
#include <rime/candidate.h>

#include "input_archive_producer.h"

namespace rime {

class Config;
class Context;
class Engine;

struct ArchiveCandidateFact {
  size_t merge_order = 0;
  size_t start = 0;
  size_t end = 0;
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

struct ArchiveGroupFact {
  string identity;
  size_t start = 0;
  size_t end = 0;
  string category;
  bool plan_complete = false;
  vector<size_t> member_indexes;
};

// Already-materialized window. Observation must not pull or score to fill this.
struct ArchiveWindowFact {
  bool have_plan = false;
  bool truncated = false;
  bool rerank_attempted = false;
  string plan_identity;
  string apply_state = "not_applicable";
  string lm_request_id;
  string lm_request_state = "no_request";
  string input_text;
  string preceding_text;
  vector<ArchiveCandidateFact> upstream;
  vector<size_t> emission_order;
  vector<ArchiveGroupFact> groups;
};

class InputArchiveSession {
 public:
  InputArchiveSession(string socket_path, string source_instance_id);
  ~InputArchiveSession();

  void ObserveMaterializedWindow(Engine* engine, const ArchiveWindowFact& fact);
  void ObserveDemandCandidate(Engine* engine, const an<Candidate>& candidate);
  void NoteDemandExhausted(Engine* engine, bool exhausted);
  void FlushDemand(Engine* engine);
  void ObserveTemporarySelection(Engine* engine, Context* ctx);
  void ObserveCommit(Engine* engine, Context* ctx);
  void ObserveAbort(Engine* engine, Context* ctx);
  void ObserveUpdate(Engine* engine, Context* ctx);
  void NoteInputKey(bool plain_backspace);
  void ObserveRetraction(Engine* engine);

  InputArchiveProducer* producer() const { return producer_.get(); }
  void CloseCompositionForTesting() { CloseComposition(); }
  const string& source_instance_id() const { return source_instance_id_; }

 private:
  struct EntryContext {
    string role = "absent";
    string read = "absent";
    string source;
    string process;
    string update;
    string segment;
  };
  struct HeldGroup {
    string identity;
    size_t start = 0;
    size_t end = 0;
    string category;
    bool plan_complete = false;
    bool truncated = false;
    vector<string> texts;
  };

  EntryContext ReadEntry(Engine* engine) const;
  string SchemaId(Engine* engine) const;
  bool ContentEligible(Engine* engine, string* schema, bool* secure) const;
  void CutContinuity(const char* basis);
  void CloseComposition();
  int64_t NextSequence();
  string NextToken(const char* prefix);
  void FillEntry(InputArchiveObservation* observation, const EntryContext& entry) const;
  void Admit(InputArchiveObservation observation);
  void AdmitExclusion(Engine* engine, const char* basis);
  bool CompositionOpen() const { return composition_open_; }

  std::unique_ptr<InputArchiveProducer> producer_;
  string source_instance_id_;
  string process_id_;
  string segment_id_;
  string parent_update_id_;
  int64_t sequence_ = 0;
  int composition_serial_ = 0;
  int window_serial_ = 0;
  bool composition_open_ = false;
  bool content_excluded_ = false;
  bool retraction_armed_ = false;
  bool retraction_pending_ = false;
  bool explicit_selection_ = false;
  string selected_text_;
  size_t selected_start_ = 0;
  size_t selected_end_ = 0;
  string selected_category_;
  string last_commit_text_;
  string last_commit_update_;
  string last_commit_process_;
  string window_id_;
  string plan_identity_;
  bool window_truncated_ = false;
  bool window_have_plan_ = false;
  vector<HeldGroup> held_groups_;
  vector<ArchiveCandidateFact> demand_;
  bool demand_exhausted_ = false;
};

class InputArchiveRegistry {
 public:
  static std::shared_ptr<InputArchiveSession> Acquire(Engine* engine,
                                                      const string& socket_path);
  static void Release(Engine* engine);
  static void ShutdownAll();
  static std::shared_ptr<InputArchiveSession> Find(Engine* engine);
  static void SetSecureInputOverrideForTesting(int mode);
  static void SetQueueLimitsForTesting(int count, int bytes);
  static void HoldWorkersForTesting(const string& fifo);
  static void PollForTesting();
  static bool FlushForTesting(int timeout_ms);
  static int EffectiveForTesting();
  static void ResetContinuityForTesting();
  static void RetargetForTesting(const string& socket_path);
};

string ReadInputArchiveSocket(Config* config);

}  // namespace rime

#endif  // RIME_INPUT_ARCHIVE_SESSION_H_
