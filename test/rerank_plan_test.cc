//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <gtest/gtest.h>

#include "rerank_plan.h"

using namespace rime;

namespace {

RerankPlanCandidate Candidate(size_t merge_order,
                              size_t start,
                              size_t end,
                              const string& text,
                              bool rerankable = true,
                              const string& category = "word",
                              const string& source_type = "phrase") {
  return {merge_order, start, end, category, source_type, text, rerankable};
}

RerankPlan BuildPlan(vector<RerankPlanCandidate> candidates,
                     const string& preceding_text = "今天讨论部署计划。",
                     RerankPlanConfig config = DefaultRerankPlanConfig(),
                     RerankScoringPolicy policy = DefaultRerankScoringPolicy(),
                     bool truncated = false,
                     const string& input = "gongji",
                     const string& previous_word = "计划") {
  return BuildRerankPlan("luna_pinyin", input, preceding_text, previous_word,
                         config, policy, candidates, truncated);
}

RerankScoreResult Scores(
    const RerankPlan& plan,
    const vector<pair<double, double>>& base_and_evidence) {
  RerankScoreResult result;
  result.version = kRerankScoreResultVersion;
  result.plan_identity = plan.identity;
  result.candidate_scores = vector<RerankCandidateScore>();
  for (const auto& [base, evidence] : base_and_evidence) {
    result.candidate_scores->push_back(
        MakeRerankCandidateScore(base, evidence, *plan.scoring_policy->gamma));
  }
  return result;
}

vector<string> EmitTexts(const RerankPlan& plan,
                         const vector<size_t>& emission_order) {
  vector<string> texts;
  for (size_t index : emission_order)
    texts.push_back(*(*plan.candidates)[index].text);
  return texts;
}

vector<RerankPlanCandidate> TwoGroupsWithPunctuation() {
  return {
      Candidate(0, 0, 2, "甲"),
      Candidate(1, 0, 2, "，", false, "punct", "punct"),
      Candidate(2, 0, 2, "乙", true, "word", "user_phrase"),
      Candidate(3, 2, 4, "丙"),
      Candidate(4, 2, 4, "丁"),
  };
}

string Bytes(std::initializer_list<unsigned int> bytes) {
  string result;
  for (unsigned int byte : bytes)
    result.push_back(static_cast<char>(byte));
  return result;
}

string Repeat(const string& text, size_t count) {
  string result;
  for (size_t i = 0; i < count; ++i)
    result += text;
  return result;
}

}  // namespace

TEST(RerankPlanTest, SameNormalizedContentsHaveStableIdentity) {
  auto first = BuildPlan(TwoGroupsWithPunctuation());
  auto second = BuildPlan(TwoGroupsWithPunctuation());

  EXPECT_EQ(2, kRerankPlanVersion);
  ASSERT_TRUE(first.identity.has_value());
  EXPECT_EQ(first.identity, second.identity);
  EXPECT_EQ("rerank-plan-v2:sha1:de39eff73c7b7da76861a6ffbe551e4eb3776de3",
            *first.identity);
  ASSERT_EQ(2u, first.groups->size());
  EXPECT_EQ((*first.groups)[0].identity, (*second.groups)[0].identity);
  EXPECT_EQ((*first.groups)[1].identity, (*second.groups)[1].identity);
}

TEST(RerankPlanTest, SavesSchemaCandidatesAndOriginalMergeOrder) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());

  ASSERT_TRUE(plan.schema_id.has_value());
  EXPECT_EQ("luna_pinyin", *plan.schema_id);
  ASSERT_EQ(5u, plan.candidates->size());
  EXPECT_EQ("甲", *(*plan.candidates)[0].text);
  EXPECT_EQ(0u, *(*plan.candidates)[0].merge_order);
  EXPECT_EQ("乙", *(*plan.candidates)[2].text);
  EXPECT_EQ(2u, *(*plan.candidates)[2].merge_order);
  ASSERT_EQ(2u, plan.groups->size());
  EXPECT_EQ((vector<size_t>{0, 2}), *(*plan.groups)[0].candidate_indexes);
  EXPECT_EQ((vector<size_t>{3, 4}), *(*plan.groups)[1].candidate_indexes);
  EXPECT_EQ("go", *(*plan.groups)[0].canonical_input);
  EXPECT_EQ("ng", *(*plan.groups)[1].canonical_input);
}

TEST(RerankPlanTest, CandidateChangeChangesIdentity) {
  auto candidates = TwoGroupsWithPunctuation();
  auto first = BuildPlan(candidates);
  candidates[2].text = "异";
  auto changed = BuildPlan(candidates);

  EXPECT_NE(first.identity, changed.identity);
}

TEST(RerankPlanTest, PrecedingTextChangeChangesIdentity) {
  auto first = BuildPlan(TwoGroupsWithPunctuation(), "讨论部署计划。 ");
  auto changed = BuildPlan(TwoGroupsWithPunctuation(), "复盘部署计划。 ");

  EXPECT_NE(first.identity, changed.identity);
}

TEST(RerankPlanTest, PreviousWordChangeChangesIdentity) {
  auto first =
      BuildPlan(TwoGroupsWithPunctuation(), "研究生", DefaultRerankPlanConfig(),
                DefaultRerankScoringPolicy(), false, "gongji", "研究生");
  auto changed =
      BuildPlan(TwoGroupsWithPunctuation(), "研究生", DefaultRerankPlanConfig(),
                DefaultRerankScoringPolicy(), false, "gongji", "生");

  EXPECT_NE(first.identity, changed.identity);
}

TEST(RerankPlanTest, CanonicalInputControlsIdentity) {
  auto uppercase =
      BuildPlan(TwoGroupsWithPunctuation(), "上文", DefaultRerankPlanConfig(),
                DefaultRerankScoringPolicy(), false, "GONGJI");
  auto lowercase =
      BuildPlan(TwoGroupsWithPunctuation(), "上文", DefaultRerankPlanConfig(),
                DefaultRerankScoringPolicy(), false, "gongji");
  auto changed =
      BuildPlan(TwoGroupsWithPunctuation(), "上文", DefaultRerankPlanConfig(),
                DefaultRerankScoringPolicy(), false, "gangji");

  EXPECT_EQ(uppercase.identity, lowercase.identity);
  EXPECT_NE(lowercase.identity, changed.identity);
  ASSERT_FALSE(lowercase.groups->empty());
  EXPECT_EQ((*uppercase.groups)[0].identity, (*lowercase.groups)[0].identity);
  EXPECT_NE((*lowercase.groups)[0].identity, (*changed.groups)[0].identity);
  ASSERT_TRUE(lowercase.canonical_input.has_value());
  EXPECT_EQ("gongji", *lowercase.canonical_input);
}

TEST(RerankPlanTest, SchemaChangeChangesIdentity) {
  auto candidates = TwoGroupsWithPunctuation();
  auto first = BuildRerankPlan("luna_pinyin", "gongji", "上文", "上文",
                               DefaultRerankPlanConfig(),
                               DefaultRerankScoringPolicy(), candidates, false);
  auto changed = BuildRerankPlan(
      "other_schema", "gongji", "上文", "上文", DefaultRerankPlanConfig(),
      DefaultRerankScoringPolicy(), candidates, false);

  EXPECT_NE(first.identity, changed.identity);
}

TEST(RerankPlanTest, ConfigChangeChangesIdentity) {
  RerankPlanConfig first_config = DefaultRerankPlanConfig();
  RerankPlanConfig changed_config = DefaultRerankPlanConfig();
  changed_config.window = 16;

  auto first = BuildPlan(TwoGroupsWithPunctuation(), "上文", first_config);
  auto changed = BuildPlan(TwoGroupsWithPunctuation(), "上文", changed_config);

  EXPECT_NE(first.identity, changed.identity);
}

TEST(RerankPlanTest, ScoringPolicyChangeChangesIdentity) {
  RerankScoringPolicy first_policy = DefaultRerankScoringPolicy();
  RerankScoringPolicy changed_policy = DefaultRerankScoringPolicy();
  changed_policy.alpha = 3.0;

  auto first = BuildPlan(TwoGroupsWithPunctuation(), "上文",
                         DefaultRerankPlanConfig(), first_policy);
  auto changed = BuildPlan(TwoGroupsWithPunctuation(), "上文",
                           DefaultRerankPlanConfig(), changed_policy);

  EXPECT_NE(first.identity, changed.identity);
}

TEST(RerankPlanTest, BaselinePolicyIdChangeChangesIdentity) {
  // The mean-token policy (default) must never share an identity with the
  // old sum-score policy, even at the same alpha.
  RerankScoringPolicy old_policy = DefaultRerankScoringPolicy();
  old_policy.baseline_policy_id = "first-stage-base-v1";
  RerankScoringPolicy new_policy = DefaultRerankScoringPolicy();
  EXPECT_EQ("mean-token-lm-v1", *new_policy.baseline_policy_id);
  EXPECT_EQ(*old_policy.alpha, *new_policy.alpha);

  auto old_plan = BuildPlan(TwoGroupsWithPunctuation(), "上文",
                            DefaultRerankPlanConfig(), old_policy);
  auto new_plan = BuildPlan(TwoGroupsWithPunctuation(), "上文",
                            DefaultRerankPlanConfig(), new_policy);

  EXPECT_NE(old_plan.identity, new_plan.identity);
}

TEST(RerankPlanTest, SamePolicyIdentityIsDeterministic) {
  auto first = BuildPlan(TwoGroupsWithPunctuation());
  auto second = BuildPlan(TwoGroupsWithPunctuation());
  EXPECT_EQ(first.identity, second.identity);
}

TEST(RerankPlanTest, StoresLast64UnicodeCharacters) {
  const string preceding_text = "头" + string(63, 'a') + "。末";
  auto plan = BuildPlan(TwoGroupsWithPunctuation(), preceding_text);

  ASSERT_TRUE(plan.preceding_text.has_value());
  EXPECT_EQ(string(62, 'a') + "。末", *plan.preceding_text);
}

TEST(RerankPlanTest, InvalidUtf8PrecedingTextDoesNotGetIdentity) {
  const vector<pair<string, string>> invalid_cases{
      {"invalid leading byte", Bytes({0xff})},
      {"stray continuation byte", Bytes({0x80})},
      {"invalid continuation byte", Bytes({0xe2, 0x28, 0xa1})},
      {"truncated multibyte sequence", Bytes({0xe4, 0xb8})},
      {"two-byte overlong encoding", Bytes({0xc0, 0xaf})},
      {"three-byte overlong encoding", Bytes({0xe0, 0x80, 0xaf})},
      {"four-byte overlong encoding", Bytes({0xf0, 0x80, 0x80, 0xaf})},
      {"surrogate encoding", Bytes({0xed, 0xa0, 0x80})},
      {"above Unicode maximum", Bytes({0xf4, 0x90, 0x80, 0x80})},
  };

  for (const auto& [name, preceding_text] : invalid_cases) {
    SCOPED_TRACE(name);
    auto plan = BuildPlan(TwoGroupsWithPunctuation(), preceding_text);
    EXPECT_FALSE(plan.identity.has_value());
  }
}

TEST(RerankPlanTest, InvalidUtf8OutsideTruncatedSuffixStillFailsBuild) {
  const string preceding_text =
      string(64, 'a') + Bytes({0xff}) + string(64, 'b');
  auto plan = BuildPlan(TwoGroupsWithPunctuation(), preceding_text);

  EXPECT_FALSE(plan.identity.has_value());
}

TEST(RerankPlanTest, Utf8DecoderAcceptsUnicodeScalarBoundaries) {
  const string valid =
      Bytes({0x00, 0x7f, 0xc2, 0x80, 0xdf, 0xbf, 0xe0, 0xa0, 0x80,
             0xed, 0x9f, 0xbf, 0xee, 0x80, 0x80, 0xef, 0xbf, 0xbf,
             0xf0, 0x90, 0x80, 0x80, 0xf4, 0x8f, 0xbf, 0xbf});
  auto decoded = LastUnicodeCharacters(valid, 10);

  ASSERT_TRUE(decoded.has_value());
  EXPECT_EQ(valid, *decoded);
}

TEST(RerankPlanTest, ZeroLimitStillValidatesUtf8) {
  auto valid = LastUnicodeCharacters("界", 0);
  auto invalid = LastUnicodeCharacters(Bytes({0xff}), 0);

  ASSERT_TRUE(valid.has_value());
  EXPECT_TRUE(valid->empty());
  EXPECT_FALSE(invalid.has_value());
}

TEST(RerankPlanTest, StoresExactly64ValidMultibyteUnicodeScalars) {
  const string preceding_text = Repeat("界", 64);
  auto plan = BuildPlan(TwoGroupsWithPunctuation(), preceding_text);

  ASSERT_TRUE(plan.identity.has_value());
  ASSERT_TRUE(plan.preceding_text.has_value());
  EXPECT_EQ(preceding_text, *plan.preceding_text);
}

TEST(RerankPlanTest, Truncates65ValidMultibyteUnicodeScalarsTo64) {
  const string expected = Repeat("界", 64);
  auto plan = BuildPlan(TwoGroupsWithPunctuation(), "甲" + expected);

  ASSERT_TRUE(plan.identity.has_value());
  ASSERT_TRUE(plan.preceding_text.has_value());
  EXPECT_EQ(expected, *plan.preceding_text);
}

TEST(RerankPlanTest, ReplayRejectsInvalidUtf8PrecedingText) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  plan.preceding_text = Bytes({0xff});
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, ReplaysExactOrderAcrossGroupsAndKeepsNonWordPosition) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {
                                 {1.0, 0.0},
                                 {0.0, 0.0},
                                 {3.0, 0.0},
                                 {0.0, 0.0},
                                 {2.0, 0.0},
                             });
  vector<size_t> emission_order;

  ASSERT_TRUE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙"}),
            EmitTexts(plan, emission_order));
}

TEST(RerankPlanTest, GammaZeroKeepsFrozenBasePolicyActive) {
  RerankScoringPolicy policy = DefaultRerankScoringPolicy();
  policy.gamma = 0.0;
  auto plan = BuildPlan({Candidate(0, 0, 2, "甲"), Candidate(1, 0, 2, "乙")},
                        "上文", DefaultRerankPlanConfig(), policy);
  auto scores = Scores(plan, {{3.0, 0.0}, {1.0, 0.9}});
  vector<size_t> emission_order;

  ASSERT_TRUE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<string>{"甲", "乙"}), EmitTexts(plan, emission_order));
}

TEST(RerankPlanTest, DuplicateCandidatesReplayByMergeOrderNotText) {
  auto plan = BuildPlan({Candidate(0, 0, 2, "同"), Candidate(1, 0, 2, "同"),
                         Candidate(2, 0, 2, "异")});
  auto scores = Scores(plan, {{1.0, 0.0}, {3.0, 0.0}, {2.0, 0.0}});
  vector<size_t> emission_order;

  ASSERT_TRUE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{1, 2, 0}), emission_order);
  EXPECT_EQ((vector<string>{"同", "异", "同"}),
            EmitTexts(plan, emission_order));
}

TEST(RerankPlanTest, TruncatedLastGroupKeepsItsOriginalMergeOrder) {
  auto plan = BuildPlan({Candidate(0, 0, 2, "甲"), Candidate(1, 0, 2, "乙"),
                         Candidate(2, 2, 4, "丙"), Candidate(3, 2, 4, "丁")},
                        "上文", DefaultRerankPlanConfig(),
                        DefaultRerankScoringPolicy(), true);
  auto scores = Scores(plan, {
                                 {1.0, 0.0},
                                 {2.0, 0.0},
                                 {1.0, 0.0},
                                 {9.0, 0.0},
                             });
  vector<size_t> emission_order;

  ASSERT_TRUE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<string>{"乙", "甲", "丙", "丁"}),
            EmitTexts(plan, emission_order));
}

TEST(RerankPlanTest, TruncationFreezesGroupAtBoundaryWhenGroupsInterleave) {
  auto plan = BuildPlan({Candidate(0, 0, 2, "甲"), Candidate(1, 2, 4, "丙"),
                         Candidate(2, 2, 4, "丁"), Candidate(3, 0, 2, "乙")},
                        "上文", DefaultRerankPlanConfig(),
                        DefaultRerankScoringPolicy(), true);
  auto scores = Scores(plan, {
                                 {1.0, 0.0},
                                 {1.0, 0.0},
                                 {2.0, 0.0},
                                 {9.0, 0.0},
                             });
  vector<size_t> emission_order;

  ASSERT_TRUE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{0, 3, 2, 1}), emission_order);
}

TEST(RerankPlanTest, EmptyCandidateSequenceReplaysAsEmpty) {
  auto plan = BuildPlan({});
  auto scores = Scores(plan, {});
  vector<size_t> emission_order{99};

  ASSERT_TRUE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_TRUE(emission_order.empty());
}

TEST(RerankPlanTest, MissingPlanFieldRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  plan.schema_id.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, VersionOnePlanIsRejected) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  plan.version = 1;
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, MissingPreviousWordRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  plan.previous_word.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, MissingNestedPlanFieldRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  plan.scoring_policy->alpha.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, MissingCandidateFieldRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  (*plan.candidates)[2].text.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, InvalidCandidateSpanRejectsWholeReplay) {
  auto plan = BuildPlan({Candidate(0, 0, 99, "甲")});
  RerankScoreResult scores;
  scores.version = kRerankScoreResultVersion;
  scores.plan_identity = plan.identity;
  scores.candidate_scores = vector<RerankCandidateScore>();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, MissingCandidateListIsNotAnEmptyPlan) {
  auto plan = BuildPlan({});
  auto scores = Scores(plan, {});
  plan.candidates.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, MissingScoreFieldRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  (*scores.candidate_scores)[2].base_score.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, MissingScoreListRejectsWholeReplay) {
  auto plan = BuildPlan({});
  auto scores = Scores(plan, {});
  scores.candidate_scores.reset();
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, CandidateCountMismatchRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}});
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, IdentityMismatchRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  scores.plan_identity = "rerank-plan-v2:mismatch";
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}

TEST(RerankPlanTest, ComparisonScoreMismatchRejectsWholeReplay) {
  auto plan = BuildPlan(TwoGroupsWithPunctuation());
  auto scores = Scores(plan, {{1, 0}, {0, 0}, {2, 0}, {3, 0}, {4, 0}});
  (*scores.candidate_scores)[2].comparison_score =
      *(*scores.candidate_scores)[2].comparison_score + 1e-13;
  vector<size_t> emission_order{99};

  EXPECT_FALSE(ReplayRerankPlan(plan, scores, &emission_order));
  EXPECT_EQ((vector<size_t>{99}), emission_order);
}
