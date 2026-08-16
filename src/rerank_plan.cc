//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include "rerank_plan.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <map>
#include <sstream>
#include <tuple>

#include <boost/uuid/detail/sha1.hpp>

namespace rime {
namespace {

constexpr size_t kPrecedingTextCharacters = 64;

void AppendField(string* canonical, const string& name, const string& value) {
  *canonical += std::to_string(name.size()) + ":" + name;
  *canonical += std::to_string(value.size()) + ":" + value;
}

void AppendField(string* canonical, const string& name, size_t value) {
  AppendField(canonical, name, std::to_string(value));
}

void AppendField(string* canonical, const string& name, int value) {
  AppendField(canonical, name, std::to_string(value));
}

void AppendField(string* canonical, const string& name, bool value) {
  AppendField(canonical, name, value ? "1" : "0");
}

string CanonicalDouble(double value) {
  if (value == 0.0)
    value = 0.0;
  static_assert(sizeof(double) == sizeof(uint64_t));
  uint64_t bits;
  std::memcpy(&bits, &value, sizeof(bits));
  std::ostringstream stream;
  stream << std::hex << std::setfill('0') << std::setw(16) << bits;
  return stream.str();
}

void AppendField(string* canonical, const string& name, double value) {
  AppendField(canonical, name, CanonicalDouble(value));
}

string ContentIdentity(const string& kind, const string& canonical) {
  boost::uuids::detail::sha1 sha1;
  sha1.process_bytes(canonical.data(), canonical.size());
  boost::uuids::detail::sha1::digest_type digest;
  sha1.get_digest(digest);

  std::ostringstream stream;
  stream << kind << ":sha1:" << std::hex << std::setfill('0');
  if constexpr (sizeof(digest[0]) == 1) {
    for (unsigned char part : digest)
      stream << std::setw(2) << static_cast<unsigned int>(part);
  } else {
    for (unsigned int part : digest)
      stream << std::setw(8) << part;
  }
  return stream.str();
}

void AppendConfig(string* canonical, const RerankPlanConfig& config) {
  AppendField(canonical, "config_version", *config.version);
  AppendField(canonical, "window", *config.window);
}

void AppendScoringPolicy(string* canonical, const RerankScoringPolicy& policy) {
  AppendField(canonical, "scoring_policy_version", *policy.version);
  AppendField(canonical, "baseline_policy_id", *policy.baseline_policy_id);
  AppendField(canonical, "retrieval_policy_id", *policy.retrieval_policy_id);
  AppendField(canonical, "alpha", *policy.alpha);
  AppendField(canonical, "sys_coeff", *policy.sys_coeff);
  AppendField(canonical, "usr_coeff", *policy.usr_coeff);
  AppendField(canonical, "gamma", *policy.gamma);
  AppendField(canonical, "saturate_k", *policy.saturate_k);
}

void AppendCandidate(string* canonical, const RerankPlanCandidate& candidate) {
  AppendField(canonical, "merge_order", *candidate.merge_order);
  AppendField(canonical, "start", *candidate.start);
  AppendField(canonical, "end", *candidate.end);
  AppendField(canonical, "category", *candidate.category);
  AppendField(canonical, "source_type", *candidate.source_type);
  AppendField(canonical, "text", *candidate.text);
  AppendField(canonical, "rerankable", *candidate.rerankable);
}

string ComputeGroupIdentity(const string& schema_id,
                            const RerankPlanGroup& group,
                            const vector<RerankPlanCandidate>& candidates) {
  string canonical;
  AppendField(&canonical, "group_format", 1);
  AppendField(&canonical, "schema_id", schema_id);
  AppendField(&canonical, "canonical_input", *group.canonical_input);
  AppendField(&canonical, "start", *group.start);
  AppendField(&canonical, "end", *group.end);
  AppendField(&canonical, "category", *group.category);
  AppendField(&canonical, "candidate_count", group.candidate_indexes->size());
  for (size_t index : *group.candidate_indexes) {
    AppendField(&canonical, "candidate_index", index);
    AppendCandidate(&canonical, candidates[index]);
  }
  return ContentIdentity("rerank-group-v1", canonical);
}

string ComputePlanIdentity(const RerankPlan& plan) {
  string canonical;
  AppendField(&canonical, "plan_version", *plan.version);
  AppendField(&canonical, "schema_id", *plan.schema_id);
  AppendField(&canonical, "canonical_input", *plan.canonical_input);
  AppendField(&canonical, "preceding_text", *plan.preceding_text);
  AppendField(&canonical, "previous_word", *plan.previous_word);
  AppendConfig(&canonical, *plan.config);
  AppendScoringPolicy(&canonical, *plan.scoring_policy);
  AppendField(&canonical, "window_truncated", *plan.window_truncated);
  AppendField(&canonical, "candidate_count", plan.candidates->size());
  for (const auto& candidate : *plan.candidates)
    AppendCandidate(&canonical, candidate);
  AppendField(&canonical, "group_count", plan.groups->size());
  for (const auto& group : *plan.groups) {
    AppendField(&canonical, "group_identity", *group.identity);
    AppendField(&canonical, "group_complete", *group.complete);
  }
  return ContentIdentity("rerank-plan-v2", canonical);
}

bool ValidConfig(const RerankPlanConfig& config) {
  return config.version && *config.version == 1 && config.window &&
         *config.window > 0;
}

bool ValidScoringPolicy(const RerankScoringPolicy& policy) {
  return policy.version && *policy.version == 1 && policy.baseline_policy_id &&
         !policy.baseline_policy_id->empty() && policy.retrieval_policy_id &&
         !policy.retrieval_policy_id->empty() && policy.alpha &&
         std::isfinite(*policy.alpha) && policy.sys_coeff &&
         std::isfinite(*policy.sys_coeff) && policy.usr_coeff &&
         std::isfinite(*policy.usr_coeff) && policy.gamma &&
         std::isfinite(*policy.gamma) && policy.saturate_k &&
         std::isfinite(*policy.saturate_k) && *policy.alpha >= 0.0 &&
         *policy.sys_coeff >= 0.0 && *policy.usr_coeff >= 0.0 &&
         *policy.gamma >= 0.0 && *policy.saturate_k > 0.0;
}

double ComparisonScore(double base_score,
                       double retrieval_evidence,
                       double gamma) {
  return std::fma(gamma, retrieval_evidence, base_score);
}

bool ValidPlan(const RerankPlan& plan) {
  if (!plan.version || *plan.version != kRerankPlanVersion || !plan.identity ||
      plan.identity->empty() || !plan.schema_id || plan.schema_id->empty() ||
      !plan.canonical_input ||
      *plan.canonical_input != CanonicalizeInput(*plan.canonical_input) ||
      !plan.preceding_text || !plan.previous_word || !plan.config ||
      !ValidConfig(*plan.config) || !plan.scoring_policy ||
      !ValidScoringPolicy(*plan.scoring_policy) || !plan.window_truncated ||
      !plan.candidates || !plan.groups) {
    return false;
  }
  auto preceding_text =
      LastUnicodeCharacters(*plan.preceding_text, kPrecedingTextCharacters);
  if (!preceding_text || *preceding_text != *plan.preceding_text) {
    return false;
  }

  vector<bool> grouped(plan.candidates->size(), false);
  for (size_t i = 0; i < plan.candidates->size(); ++i) {
    const auto& candidate = (*plan.candidates)[i];
    if (!candidate.merge_order || *candidate.merge_order != i ||
        !candidate.start || !candidate.end ||
        *candidate.start > *candidate.end || !candidate.category ||
        candidate.category->empty() || !candidate.source_type ||
        candidate.source_type->empty() || !candidate.text ||
        candidate.text->empty() || !candidate.rerankable ||
        *candidate.end > plan.canonical_input->size() ||
        (*candidate.rerankable && *candidate.category != "word")) {
      return false;
    }
  }

  size_t previous_first_index = 0;
  bool has_previous_group = false;
  size_t boundary_group = 0;
  size_t boundary_candidate = 0;
  bool has_boundary_group = false;
  for (size_t group_index = 0; group_index < plan.groups->size();
       ++group_index) {
    const auto& group = (*plan.groups)[group_index];
    if (!group.identity || group.identity->empty() || !group.start ||
        !group.end || !group.category || *group.category != "word" ||
        *group.start > *group.end || !group.canonical_input ||
        *group.end > plan.canonical_input->size() ||
        *group.canonical_input !=
            plan.canonical_input->substr(*group.start,
                                         *group.end - *group.start) ||
        !group.complete || !group.candidate_indexes ||
        group.candidate_indexes->empty()) {
      return false;
    }
    size_t previous_candidate_index = 0;
    bool has_previous_candidate = false;
    for (size_t candidate_index : *group.candidate_indexes) {
      if (candidate_index >= plan.candidates->size() ||
          grouped[candidate_index])
        return false;
      const auto& candidate = (*plan.candidates)[candidate_index];
      if (!*candidate.rerankable || candidate.start != group.start ||
          candidate.end != group.end || candidate.category != group.category ||
          (has_previous_candidate &&
           candidate_index <= previous_candidate_index)) {
        return false;
      }
      grouped[candidate_index] = true;
      previous_candidate_index = candidate_index;
      has_previous_candidate = true;
      if (!has_boundary_group || candidate_index > boundary_candidate) {
        boundary_group = group_index;
        boundary_candidate = candidate_index;
        has_boundary_group = true;
      }
    }
    const size_t first_index = group.candidate_indexes->front();
    if (has_previous_group && first_index <= previous_first_index)
      return false;
    previous_first_index = first_index;
    has_previous_group = true;
    if (*group.identity !=
        ComputeGroupIdentity(*plan.schema_id, group, *plan.candidates)) {
      return false;
    }
  }

  for (size_t i = 0; i < plan.candidates->size(); ++i) {
    if (*(*plan.candidates)[i].rerankable != grouped[i])
      return false;
  }
  for (size_t group_index = 0; group_index < plan.groups->size();
       ++group_index) {
    const bool expected_complete =
        !*plan.window_truncated || group_index != boundary_group;
    if (*(*plan.groups)[group_index].complete != expected_complete)
      return false;
  }
  return *plan.identity == ComputePlanIdentity(plan);
}

}  // namespace

RerankPlanConfig DefaultRerankPlanConfig() {
  RerankPlanConfig config;
  config.version = 1;
  config.window = 32;
  return config;
}

RerankScoringPolicy DefaultRerankScoringPolicy() {
  RerankScoringPolicy policy;
  policy.version = 1;
  // mean-token policy (docs/token-attribution.md): the LM term is the mean
  // log probability of the candidate's own tokens. The id pins the
  // normalization semantics; alpha is hashed into the plan identity
  // separately, so changing either changes the identity.
  //
  // Default alpha = 0 (owner decision, Habit130/squirrel#46): on the
  // canonical 120/402 fixture no positive alpha qualifies (alpha=0 beats
  // every positive grid point on top-1 and MRR; see eval/manifest.json).
  // The LM term stays disabled by default and can be enabled explicitly via
  // the schema; a future contextual fixture decides a positive default.
  policy.baseline_policy_id = "mean-token-lm-v1";
  // The retrieval-evidence policy (Squirrel#61): the semantic oracle evidence
  // term replaces the first-stage bigram term. When evidence is active the
  // filter overrides this id with the full evidence config identity it was
  // scored under, so the plan identity binds the exact evidence config.
  policy.retrieval_policy_id = "exact-oracle-evidence-v1";
  policy.alpha = 0.0;
  policy.sys_coeff = 1.0;
  policy.usr_coeff = 1.0;
  policy.gamma = 2.0;
  policy.saturate_k = 3.0;
  return policy;
}

std::optional<string> LastUnicodeCharacters(const string& text, size_t limit) {
  vector<size_t> scalar_starts;
  size_t position = 0;
  while (position < text.size()) {
    scalar_starts.push_back(position);
    const unsigned char leading = text[position];
    size_t length;
    uint32_t scalar;
    uint32_t minimum;
    if (leading <= 0x7f) {
      length = 1;
      scalar = leading;
      minimum = 0;
    } else if (leading >= 0xc2 && leading <= 0xdf) {
      length = 2;
      scalar = leading & 0x1f;
      minimum = 0x80;
    } else if (leading >= 0xe0 && leading <= 0xef) {
      length = 3;
      scalar = leading & 0x0f;
      minimum = 0x800;
    } else if (leading >= 0xf0 && leading <= 0xf4) {
      length = 4;
      scalar = leading & 0x07;
      minimum = 0x10000;
    } else {
      return std::nullopt;
    }
    if (length > text.size() - position)
      return std::nullopt;
    for (size_t i = 1; i < length; ++i) {
      const unsigned char continuation = text[position + i];
      if ((continuation & 0xc0) != 0x80)
        return std::nullopt;
      scalar = (scalar << 6) | (continuation & 0x3f);
    }
    if (scalar < minimum || (scalar >= 0xd800 && scalar <= 0xdfff) ||
        scalar > 0x10ffff) {
      return std::nullopt;
    }
    position += length;
  }

  if (limit == 0)
    return string();
  const size_t first = scalar_starts.size() > limit
                           ? scalar_starts[scalar_starts.size() - limit]
                           : 0;
  return text.substr(first);
}

string CanonicalizeInput(const string& input) {
  string canonical = input;
  for (char& character : canonical) {
    if (character >= 'A' && character <= 'Z')
      character += 'a' - 'A';
  }
  return canonical;
}

RerankPlan BuildRerankPlan(const string& schema_id,
                           const string& input,
                           const string& preceding_text,
                           const string& previous_word,
                           const RerankPlanConfig& config,
                           const RerankScoringPolicy& scoring_policy,
                           const vector<RerankPlanCandidate>& candidates,
                           bool window_truncated) {
  RerankPlan plan;
  plan.version = kRerankPlanVersion;
  plan.schema_id = schema_id;
  plan.canonical_input = CanonicalizeInput(input);
  plan.preceding_text =
      LastUnicodeCharacters(preceding_text, kPrecedingTextCharacters);
  plan.previous_word = previous_word;
  plan.config = config;
  plan.scoring_policy = scoring_policy;
  plan.window_truncated = window_truncated;
  plan.candidates = candidates;
  plan.groups = vector<RerankPlanGroup>();

  if (!plan.preceding_text || schema_id.empty() || !ValidConfig(config) ||
      !ValidScoringPolicy(scoring_policy)) {
    return plan;
  }

  using GroupKey = std::tuple<size_t, size_t, string>;
  map<GroupKey, size_t> group_indexes;
  size_t boundary_group = 0;
  bool has_boundary_group = false;
  for (size_t i = 0; i < plan.candidates->size(); ++i) {
    auto& candidate = (*plan.candidates)[i];
    candidate.merge_order = i;
    if (!candidate.start || !candidate.end || !candidate.category ||
        !candidate.source_type || !candidate.text || !candidate.rerankable) {
      return plan;
    }
    if (*candidate.start > *candidate.end ||
        *candidate.end > plan.canonical_input->size()) {
      return plan;
    }
    if (!*candidate.rerankable)
      continue;
    const GroupKey key(*candidate.start, *candidate.end, *candidate.category);
    auto [it, inserted] = group_indexes.emplace(key, plan.groups->size());
    if (inserted) {
      RerankPlanGroup group;
      group.start = candidate.start;
      group.end = candidate.end;
      group.category = candidate.category;
      if (*candidate.end > plan.canonical_input->size())
        return plan;
      group.canonical_input = plan.canonical_input->substr(
          *candidate.start, *candidate.end - *candidate.start);
      group.complete = true;
      group.candidate_indexes = vector<size_t>();
      plan.groups->push_back(std::move(group));
    }
    (*plan.groups)[it->second].candidate_indexes->push_back(i);
    boundary_group = it->second;
    has_boundary_group = true;
  }
  if (window_truncated && has_boundary_group)
    (*plan.groups)[boundary_group].complete = false;
  for (auto& group : *plan.groups) {
    group.identity = ComputeGroupIdentity(schema_id, group, *plan.candidates);
  }
  plan.identity = ComputePlanIdentity(plan);
  return plan;
}

RerankCandidateScore MakeRerankCandidateScore(double base_score,
                                              double retrieval_evidence,
                                              double gamma) {
  RerankCandidateScore score;
  score.base_score = base_score;
  score.retrieval_evidence = retrieval_evidence;
  score.comparison_score =
      ComparisonScore(base_score, retrieval_evidence, gamma);
  return score;
}

bool ReplayRerankPlan(const RerankPlan& plan,
                      const RerankScoreResult& scores,
                      vector<size_t>* emission_order) {
  if (!emission_order || !ValidPlan(plan) || !scores.version ||
      *scores.version != kRerankScoreResultVersion || !scores.plan_identity ||
      scores.plan_identity != plan.identity || !scores.candidate_scores ||
      scores.candidate_scores->size() != plan.candidates->size()) {
    return false;
  }

  const double gamma = *plan.scoring_policy->gamma;
  vector<double> comparison_scores;
  comparison_scores.reserve(scores.candidate_scores->size());
  for (const auto& score : *scores.candidate_scores) {
    if (!score.base_score || !score.retrieval_evidence ||
        !score.comparison_score || !std::isfinite(*score.base_score) ||
        !std::isfinite(*score.retrieval_evidence) ||
        !std::isfinite(*score.comparison_score) ||
        *score.retrieval_evidence < 0.0 || *score.retrieval_evidence >= 1.0) {
      return false;
    }
    const double comparison_score =
        ComparisonScore(*score.base_score, *score.retrieval_evidence, gamma);
    if (*score.comparison_score != comparison_score)
      return false;
    comparison_scores.push_back(comparison_score);
  }

  vector<size_t> word_order;
  for (const auto& group : *plan.groups) {
    vector<size_t> members = *group.candidate_indexes;
    if (*group.complete) {
      std::stable_sort(
          members.begin(), members.end(), [&](size_t left, size_t right) {
            return comparison_scores[left] > comparison_scores[right];
          });
    }
    word_order.insert(word_order.end(), members.begin(), members.end());
  }

  vector<size_t> replayed;
  replayed.reserve(plan.candidates->size());
  size_t word_index = 0;
  for (size_t i = 0; i < plan.candidates->size(); ++i) {
    if (*(*plan.candidates)[i].rerankable)
      replayed.push_back(word_order[word_index++]);
    else
      replayed.push_back(i);
  }
  *emission_order = std::move(replayed);
  return true;
}

}  // namespace rime
