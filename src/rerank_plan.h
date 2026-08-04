//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_RERANK_PLAN_H_
#define RIME_RERANK_PLAN_H_

#include <optional>

#include <rime/common.h>

namespace rime {

constexpr int kRerankPlanVersion = 1;
constexpr int kRerankScoreResultVersion = 1;

// Presence is part of the replay contract: decoded records keep missing fields
// empty so validation cannot confuse them with explicit default values.
struct RerankPlanConfig {
  std::optional<int> version;
  std::optional<int> window;
};

struct RerankScoringPolicy {
  std::optional<int> version;
  std::optional<string> baseline_policy_id;
  std::optional<string> retrieval_policy_id;
  std::optional<double> alpha;
  std::optional<double> sys_coeff;
  std::optional<double> usr_coeff;
  std::optional<double> gamma;
  std::optional<double> saturate_k;
};

struct RerankPlanCandidate {
  std::optional<size_t> merge_order;
  std::optional<size_t> start;
  std::optional<size_t> end;
  std::optional<string> category;
  std::optional<string> source_type;
  std::optional<string> text;
  std::optional<bool> rerankable;
};

struct RerankPlanGroup {
  std::optional<string> identity;
  std::optional<size_t> start;
  std::optional<size_t> end;
  std::optional<string> category;
  std::optional<string> canonical_input;
  std::optional<bool> complete;
  std::optional<vector<size_t>> candidate_indexes;
};

struct RerankPlan {
  std::optional<int> version;
  std::optional<string> identity;
  std::optional<string> schema_id;
  std::optional<string> canonical_input;
  std::optional<string> preceding_text;
  std::optional<string> previous_word;
  std::optional<RerankPlanConfig> config;
  std::optional<RerankScoringPolicy> scoring_policy;
  std::optional<bool> window_truncated;
  std::optional<vector<RerankPlanCandidate>> candidates;
  std::optional<vector<RerankPlanGroup>> groups;
};

struct RerankCandidateScore {
  std::optional<double> base_score;
  std::optional<double> retrieval_evidence;
  std::optional<double> comparison_score;
};

struct RerankScoreResult {
  std::optional<int> version;
  std::optional<string> plan_identity;
  std::optional<vector<RerankCandidateScore>> candidate_scores;
};

RerankPlanConfig DefaultRerankPlanConfig();
RerankScoringPolicy DefaultRerankScoringPolicy();

std::optional<string> LastUnicodeCharacters(const string& text, size_t limit);
string CanonicalizeInput(const string& input);

RerankPlan BuildRerankPlan(const string& schema_id,
                           const string& input,
                           const string& preceding_text,
                           const string& previous_word,
                           const RerankPlanConfig& config,
                           const RerankScoringPolicy& scoring_policy,
                           const vector<RerankPlanCandidate>& candidates,
                           bool window_truncated);

RerankCandidateScore MakeRerankCandidateScore(double base_score,
                                              double retrieval_evidence,
                                              double gamma);

bool ReplayRerankPlan(const RerankPlan& plan,
                      const RerankScoreResult& scores,
                      vector<size_t>* emission_order);

}  // namespace rime

#endif  // RIME_RERANK_PLAN_H_
