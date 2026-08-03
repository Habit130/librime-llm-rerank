//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <unistd.h>

#include <atomic>
#include <filesystem>
#include <limits>
#include <map>
#include <utility>

#include <gtest/gtest.h>
#include <leveldb/db.h>
#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/config.h>
#include <rime/schema.h>
#include <rime/translation.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_filter.h"
#include "llm_scorer.h"

using namespace rime;

class TableScorer : public Scorer {
 public:
  explicit TableScorer(map<string, double> table) : table_(table) {}
  bool Score(const an<Candidate>& cand, ScoreComponents* score) override {
    auto it = table_.find(cand->text());
    if (it == table_.end())
      return false;
    score->base_score = it->second;
    score->retrieval_evidence = 0.0;
    return true;
  }

 private:
  map<string, double> table_;
};

class FailingScorer : public Scorer {
 public:
  bool Score(const an<Candidate>&, ScoreComponents*) override { return false; }
};

class PrepareFailingScorer : public Scorer {
 public:
  bool Prepare(const string&, const vector<string>&) override { return false; }
  bool Score(const an<Candidate>&, ScoreComponents*) override { return true; }
};

class LateFailingScorer : public Scorer {
 public:
  bool Score(const an<Candidate>& cand, ScoreComponents* score) override {
    if (cand->text() == "丁")
      return false;
    score->base_score = 99.0;
    score->retrieval_evidence = 0.0;
    return true;
  }
};

class NonFiniteScorer : public Scorer {
 public:
  bool Score(const an<Candidate>&, ScoreComponents* score) override {
    score->base_score = std::numeric_limits<double>::quiet_NaN();
    score->retrieval_evidence = 0.0;
    return true;
  }
};

static an<Phrase> MakePhrase(const string& type,
                             size_t start,
                             size_t end,
                             const string& text,
                             double weight = 0.0) {
  auto entry = New<DictEntry>();
  entry->text = text;
  entry->weight = weight;
  return New<Phrase>(nullptr, type, start, end, entry);
}

static vector<an<Candidate>> FailureWindowCandidates() {
  return {
      MakePhrase("table", 0, 2, "甲", 1.0),
      New<SimpleCandidate>("punct", 0, 2, "，"),
      MakePhrase("user_table", 0, 2, "乙", 4.0),
      MakePhrase("table", 2, 4, "丙", 1.0),
      MakePhrase("user_table", 2, 4, "丁", 3.0),
      MakePhrase("sentence", 0, 6, "整句", 9.0),
  };
}

static const vector<string> kFailureWindowOriginalOrder{
    "甲", "，", "乙", "丙", "丁", "整句"};

class VecTranslation : public Translation {
 public:
  explicit VecTranslation(vector<an<Candidate>> cands)
      : cands_(cands), cursor_(0) {}

  bool Next() override {
    if (exhausted())
      return false;
    ++next_count_;
    if (++cursor_ >= cands_.size())
      set_exhausted(true);
    return true;
  }

  an<Candidate> Peek() override {
    if (exhausted())
      return nullptr;
    ++peek_count_;
    return cands_[cursor_];
  }

  size_t peek_count() const { return peek_count_; }
  size_t next_count() const { return next_count_; }

 private:
  vector<an<Candidate>> cands_;
  size_t cursor_;
  size_t peek_count_ = 0;
  size_t next_count_ = 0;
};

static vector<string> CollectTexts(an<Translation> t) {
  vector<string> texts;
  while (!t->exhausted()) {
    auto c = t->Peek();
    if (!c)
      break;
    texts.push_back(c->text());
    t->Next();
  }
  return texts;
}

static an<Translation> ApplyFilter(LlmRerankFilter& filter,
                                   vector<an<Candidate>> cands) {
  auto translation = New<VecTranslation>(cands);
  CandidateList candidates;
  return filter.Apply(translation, &candidates);
}

static LlmRerankFilter MakeFilter(an<Scorer> scorer) {
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(scorer);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  return filter;
}

// --- T1 regression tests ---

class TranslationFixture : public Translation {
 public:
  TranslationFixture() : cursor_(0) {
    candies_.push_back(New<SimpleCandidate>("table", 0, 2, "你好"));
    candies_.push_back(New<SimpleCandidate>("table", 0, 2, "尼好"));
    candies_.push_back(New<SimpleCandidate>("table", 0, 2, "泥嚎"));
  }

  bool Next() override {
    if (exhausted())
      return false;
    ++next_count_;
    if (++cursor_ >= candies_.size())
      set_exhausted(true);
    return true;
  }

  an<Candidate> Peek() override {
    if (exhausted())
      return nullptr;
    ++peek_count_;
    return candies_[cursor_];
  }

  size_t peek_count() const { return peek_count_; }
  size_t next_count() const { return next_count_; }

 private:
  vector<of<Candidate>> candies_;
  size_t cursor_;
  size_t peek_count_ = 0;
  size_t next_count_ = 0;
};

TEST(LlmRerankFilterTest, IdentityEmission) {
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  auto translation = New<TranslationFixture>();
  CandidateList candidates;
  auto filtered = filter.Apply(translation, &candidates);
  ASSERT_TRUE(bool(filtered));

  vector<string> emitted;
  while (!filtered->exhausted()) {
    auto cand = filtered->Peek();
    ASSERT_TRUE(bool(cand));
    emitted.push_back(cand->text());
    filtered->Next();
  }

  const vector<string> expected{"你好", "尼好", "泥嚎"};
  EXPECT_EQ(expected, emitted);
}

class EmptyTranslation : public Translation {
 public:
  EmptyTranslation() { set_exhausted(true); }
  bool Next() override { return false; }
  an<Candidate> Peek() override { return nullptr; }
};

TEST(LlmRerankFilterTest, EmptyTranslation) {
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  auto translation = New<EmptyTranslation>();
  CandidateList candidates;
  auto filtered = filter.Apply(translation, &candidates);
  ASSERT_TRUE(bool(filtered));
  EXPECT_TRUE(filtered->exhausted());
  EXPECT_FALSE(bool(filtered->Peek()));
}

TEST(LlmRerankFilterTest, LazyPullTiming) {
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  auto fixture = New<TranslationFixture>();
  auto* upstream = fixture.get();
  CandidateList candidates;
  auto filtered = filter.Apply(fixture, &candidates);
  ASSERT_TRUE(bool(filtered));

  EXPECT_EQ(0, upstream->peek_count());
  EXPECT_EQ(0, upstream->next_count());
  EXPECT_FALSE(filtered->exhausted());

  ASSERT_TRUE(bool(filtered->Peek()));
  EXPECT_EQ(3, upstream->peek_count());
  EXPECT_EQ(3, upstream->next_count());

  filtered->Peek();
  EXPECT_EQ(3, upstream->peek_count());
}

// --- T2: grouping key ---

TEST(LlmRerankFilterTest, GroupingKeyTableAndUserTableSameGroup) {
  auto scorer =
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("user_table", 0, 2, "乙"),
                                          MakePhrase("sentence", 0, 2, "丙"),
                                      });
  // table+user_table form one (0,2,word) group; 丙 is a (0,2,sentence) group.
  // Translation exhausted → nothing excluded. word group sorted 乙(3) > 甲(1),
  // then the sentence group 丙(2) by first appearance.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, SentenceAndCompletionCandidatesStayInPlace) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 5}, {"丁", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("sentence", 0, 4, "甲"),
                                          MakePhrase("completion", 0, 4, "乙"),
                                          MakePhrase("sentence", 0, 4, "丙"),
                                          MakePhrase("table", 0, 2, "丁"),
                                      });
  // Only word candidates are rerankable. Sentence and completion candidates
  // retain their original positions, and the lone word candidate cannot move.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙", "丁"}), CollectTexts(filtered));
}

// --- T2: within-group sort ---

TEST(LlmRerankFilterTest, WithinGroupSortByScoreDescending) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}, {"丁", 0}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                          MakePhrase("table", 0, 4, "丁"),
                                      });
  // Not truncated → both groups scored. (0,2)={甲,乙,丙} sorts 乙(3) > 丙(2) >
  // 甲(1); (0,4)={丁} (0) follows by first appearance.
  EXPECT_EQ((vector<string>{"乙", "丙", "甲", "丁"}), CollectTexts(filtered));
}

// --- T2: between-group stable order ---

TEST(LlmRerankFilterTest, BetweenGroupOrderByFirstAppearance) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 5}, {"丙", 2}, {"丁", 0}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 4, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                          MakePhrase("table", 0, 6, "丁"),
                                      });
  // Groups: (0,2)={甲,丙} first@0, (0,4)={乙} first@1, (0,6)={丁} first@3.
  // Not truncated → all scored in first-appearance order: (0,2), (0,4), (0,6).
  // Sort (0,2): 丙(2) > 甲(1). (0,4): 乙(5). (0,6): 丁(0).
  EXPECT_EQ((vector<string>{"丙", "甲", "乙", "丁"}), CollectTexts(filtered));
}

// --- T2: window from config ---

TEST(LlmRerankFilterTest, WindowSizeReadFromConfig) {
  auto* config = new Config;
  config->SetInt("llm_rerank/window", 2);
  Schema schema("test", config);
  Ticket ticket;
  ticket.schema = &schema;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_input("abcdef");
  filter.set_scorer(
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}}));

  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                      });
  // window=2: window1=[甲,乙] is full with 丙 still upstream → truncated → the
  // same group is held at the cutoff → no reorder. window2=[丙] alone.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

// --- T2: incomplete group at cutoff ---

TEST(LlmRerankFilterTest, IncompleteGroupAtCutoffKeepsOriginalOrder) {
  auto scorer =
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  filter.set_window(2);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                      });
  // window=2: window1=[甲,乙] is full while 丙 is still upstream (translation
  // not exhausted) → truncated → the (0,2,word) group may be incomplete at the
  // cutoff and keeps its original order. window2=[丙] alone.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, SingleCompleteGroupSortedWhenNotTruncated) {
  auto scorer =
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                      });
  // window=32 (default) > 3 candidates: the translation is exhausted, so the
  // single (0,2,word) group is complete and must be scored, not skipped.
  // Sort: 乙(3) > 丙(2) > 甲(1).
  EXPECT_EQ((vector<string>{"乙", "丙", "甲"}), CollectTexts(filtered));
}

// --- T2: non-word candidates stay in place ---

TEST(LlmRerankFilterTest, NonWordCandidateStaysInPlace) {
  auto scorer =
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto punct = New<SimpleCandidate>("punct", 0, 2, "，");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          punct,
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 4, "丙"),
                                      });
  // Non-word "，" at pos1 stays. Word cands: 甲(pos0), 乙(pos2), 丙(pos3).
  // Not truncated → both groups scored. Sort (0,2): 乙(3) > 甲(1); (0,4):
  // 丙(2). word_order=[乙,甲,丙]. Output: pos0=乙, pos1=，, pos2=甲, pos3=丙.
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丙"}), CollectTexts(filtered));
}

// --- T2: unwrap shadow candidates ---

TEST(LlmRerankFilterTest, UnwrapShadowCandidateToGetWeight) {
  auto scorer =
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 0}});
  auto filter = MakeFilter(scorer);
  auto shadow_a =
      New<ShadowCandidate>(MakePhrase("table", 0, 2, "甲"), "table");
  auto shadow_b =
      New<ShadowCandidate>(MakePhrase("table", 0, 2, "乙"), "table");
  auto filtered = ApplyFilter(filter, {
                                          shadow_a,
                                          shadow_b,
                                          MakePhrase("table", 0, 4, "丙"),
                                      });
  // ShadowCandidates unwrap to Phrase → treated as word candidates.
  // Not truncated → both groups scored. Sort (0,2): 乙(3) > 甲(1); (0,4):
  // 丙(0).
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

// --- T2: failure passthrough ---

TEST(LlmRerankFilterTest, FailingScorerPassesThroughOriginalOrder) {
  auto filter = MakeFilter(New<FailingScorer>());
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 4, "丙"),
                                      });
  // (0,2,word) is complete; scorer fails → passthrough.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, PrepareFailurePassesThroughWholeWindow) {
  auto filter = MakeFilter(New<PrepareFailingScorer>());

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(LlmRerankFilterTest, LateScoringFailureDiscardsAllPartialScores) {
  auto filter = MakeFilter(New<LateFailingScorer>());

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(LlmRerankFilterTest, ReplayValidationFailurePassesThroughWholeWindow) {
  auto filter = MakeFilter(New<NonFiniteScorer>());

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(LlmRerankFilterTest, FailurePassesThroughTruncatedBoundaryWindow) {
  auto filter = MakeFilter(New<LateFailingScorer>());
  filter.set_window(6);
  vector<an<Candidate>> candidates = {
      MakePhrase("table", 0, 2, "甲", 1.0),
      New<SimpleCandidate>("punct", 0, 2, "，"),
      MakePhrase("user_table", 0, 2, "乙", 4.0),
      MakePhrase("table", 2, 4, "丙", 1.0),
      MakePhrase("user_table", 2, 4, "丁", 3.0),
      MakePhrase("table", 4, 6, "戊", 1.0),
      MakePhrase("user_table", 4, 6, "己", 5.0),
  };

  EXPECT_EQ((vector<string>{"甲", "，", "乙", "丙", "丁", "戊", "己"}),
            CollectTexts(ApplyFilter(filter, candidates)));
}

// --- T2: no candidates lost (simplifier+uniquifier chain regression) ---

TEST(LlmRerankFilterTest, NoCandidatesLostAfterRerank) {
  auto scorer = New<TableScorer>(map<string, double>{
      {"甲", 1}, {"乙", 5}, {"丙", 3}, {"丁", 2}, {"戊", 4}});
  auto filter = MakeFilter(scorer);
  auto filtered =
      ApplyFilter(filter, {
                              MakePhrase("table", 0, 2, "甲"),
                              MakePhrase("table", 0, 2, "乙"),
                              MakePhrase("table", 0, 2, "丙"),
                              MakePhrase("table", 0, 4, "丁"),
                              MakePhrase("table", 0, 4, "戊"),
                              New<SimpleCandidate>("punct", 0, 2, "，"),
                          });
  auto emitted = CollectTexts(filtered);
  set<string> emitted_set(emitted.begin(), emitted.end());
  set<string> input_set{"甲", "乙", "丙", "丁", "戊", "，"};
  EXPECT_EQ(input_set, emitted_set);
  EXPECT_EQ(6u, emitted.size());
}

// --- T3: weight scorer ---

TEST(WeightScorerTest, ScoreEqualsCoeffTimesWeight) {
  WeightScorer scorer(2.0, 0.5);
  ScoreComponents score;
  ASSERT_TRUE(scorer.Score(MakePhrase("table", 0, 2, "甲", 3.0), &score));
  EXPECT_DOUBLE_EQ(6.0, score.base_score);  // sys: 2.0 * 3.0
  ASSERT_TRUE(scorer.Score(MakePhrase("user_table", 0, 2, "乙", 3.0), &score));
  EXPECT_DOUBLE_EQ(1.5, score.base_score);  // usr: 0.5 * 3.0
}

TEST(WeightScorerTest, NonDictionaryCandidateReturnsFalse) {
  WeightScorer scorer(1.0, 1.0);
  ScoreComponents score;
  EXPECT_FALSE(scorer.Score(MakePhrase("sentence", 0, 2, "甲", 5.0), &score));
  EXPECT_FALSE(scorer.Score(New<SimpleCandidate>("punct", 0, 2, "，"), &score));
}

TEST(WeightScorerTest, WithinGroupOrderByWeightDescending) {
  auto filter = MakeFilter(New<WeightScorer>(1.0, 1.0));
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 0, 2, "丙", 2.0),
                                          MakePhrase("table", 0, 4, "丁", 0.0),
                                      });
  // (0,2,word)={甲,乙,丙} complete; weight desc: 乙(3)>丙(2)>甲(1).
  EXPECT_EQ((vector<string>{"乙", "丙", "甲", "丁"}), CollectTexts(filtered));
}

TEST(WeightScorerTest, UnwrapShadowToGetWeight) {
  auto filter = MakeFilter(New<WeightScorer>(1.0, 1.0));
  auto shadow_a =
      New<ShadowCandidate>(MakePhrase("table", 0, 2, "甲", 1.0), "table");
  auto shadow_b =
      New<ShadowCandidate>(MakePhrase("table", 0, 2, "乙", 3.0), "table");
  auto filtered = ApplyFilter(filter, {
                                          shadow_a,
                                          shadow_b,
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  // Shadows unwrap to the underlying phrases; weight desc: 乙(3)>甲(1).
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(WeightScorerTest, UserCoeffLiftsUserCandidate) {
  auto filter = MakeFilter(New<WeightScorer>(/*sys=*/1.0, /*usr=*/3.0));
  auto filtered =
      ApplyFilter(filter, {
                              MakePhrase("table", 0, 2, "甲", 5.0),
                              MakePhrase("user_table", 0, 2, "乙", 2.0),
                              MakePhrase("table", 0, 4, "丙", 0.0),
                          });
  // sys 甲 = 1.0*5 = 5; usr 乙 = 3.0*2 = 6 → 乙 > 甲.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(WeightScorerTest, SysCoeffLiftsSystemCandidate) {
  auto filter = MakeFilter(New<WeightScorer>(/*sys=*/4.0, /*usr=*/1.0));
  auto filtered =
      ApplyFilter(filter, {
                              MakePhrase("user_table", 0, 2, "甲", 3.0),
                              MakePhrase("table", 0, 2, "乙", 1.0),
                              MakePhrase("table", 0, 4, "丙", 0.0),
                          });
  // usr 甲 = 1.0*3 = 3; sys 乙 = 4.0*1 = 4 → 乙 > 甲.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(WeightScorerTest, SelfCheckUnitCoeffsPreserveMergeOrder) {
  // Self-check slice: with both coefficients = 1 the score equals the raw
  // weight, and the engine's merge order already ranks a same-span word group
  // by quality, which is monotonic in weight. Feeding a group in that natural
  // (weight-descending) order must therefore come out unchanged.
  auto filter = MakeFilter(New<WeightScorer>(1.0, 1.0));
  auto filtered =
      ApplyFilter(filter, {
                              MakePhrase("table", 0, 2, "甲", 9.0),
                              MakePhrase("user_table", 0, 2, "乙", 7.0),
                              MakePhrase("table", 0, 2, "丙", 5.0),
                              MakePhrase("user_table", 0, 2, "丁", 3.0),
                              MakePhrase("table", 0, 4, "戊", 1.0),
                          });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙", "丁", "戊"}),
            CollectTexts(filtered));
}

TEST(WeightScorerTest, CoefficientsReadFromConfig) {
  auto* config = new Config;
  config->SetDouble("llm_rerank/sys_coeff", 1.0);
  config->SetDouble("llm_rerank/usr_coeff", 3.0);
  Schema schema("test", config);
  Ticket ticket;
  ticket.schema = &schema;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_input("abcdef");

  auto filtered =
      ApplyFilter(filter, {
                              MakePhrase("table", 0, 2, "甲", 5.0),
                              MakePhrase("user_table", 0, 2, "乙", 2.0),
                              MakePhrase("table", 0, 4, "丙", 0.0),
                          });
  // sys 甲 = 5; usr 乙 = 3*2 = 6 → 乙 first.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

// --- T3 follow-up: script_translator (pinyin) emits "phrase"/"user_phrase" ---

TEST(WeightScorerTest, ScoresScriptTranslatorPhraseTypes) {
  WeightScorer scorer(2.0, 0.5);
  ScoreComponents score;
  ASSERT_TRUE(scorer.Score(MakePhrase("phrase", 0, 2, "甲", 3.0), &score));
  EXPECT_DOUBLE_EQ(6.0, score.base_score);  // sys: 2.0 * 3.0
  ASSERT_TRUE(scorer.Score(MakePhrase("user_phrase", 0, 2, "乙", 3.0), &score));
  EXPECT_DOUBLE_EQ(1.5, score.base_score);  // usr: 0.5 * 3.0
}

TEST(LlmRerankFilterTest, GroupingKeyPhraseAndUserPhraseSameGroup) {
  auto scorer =
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("phrase", 0, 2, "甲"),
                                          MakePhrase("user_phrase", 0, 2, "乙"),
                                          MakePhrase("sentence", 0, 2, "丙"),
                                      });
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

// --- T5: context-personalization term (evidence strength) ---

class FakeCounter : public ContextCounter {
 public:
  void SetPair(const string& prev, const string& cand, int n) {
    pair_[prev + "\t" + cand] = n;
  }
  void SetTotal(const string& prev, int n) { total_[prev] = n; }

  bool PairCount(const string& prev, const string& cand, int* count) override {
    auto it = pair_.find(prev + "\t" + cand);
    *count = it == pair_.end() ? 0 : it->second;
    return true;
  }
  bool TotalCount(const string& prev, int* count) override {
    auto it = total_.find(prev);
    *count = it == total_.end() ? 0 : it->second;
    return true;
  }

 private:
  map<string, int> pair_;
  map<string, int> total_;
};

class FailingCounter : public ContextCounter {
 public:
  bool PairCount(const string&, const string&, int*) override { return false; }
  bool TotalCount(const string&, int*) override { return false; }
};

class InjectedContextStore : public ContextStore {
 public:
  InjectedContextStore(ContextReadStatus data_status, string data_value = "")
      : data_status_(data_status), data_value_(std::move(data_value)) {}

  ContextReadStatus Fetch(const string& key, string* value) override {
    if (!key.empty() && key.front() == '\x01') {
      *value = "test-db";
      return ContextReadStatus::kFound;
    }
    *value = data_value_;
    return data_status_;
  }

  bool Update(const string&, const string&) override { return true; }

 private:
  ContextReadStatus data_status_;
  string data_value_;
};

static path TemporaryContextDbPath() {
  static std::atomic<unsigned int> sequence{0};
  return std::filesystem::temp_directory_path() /
         ("llm-rerank-context-" + std::to_string(getpid()) + "-" +
          std::to_string(sequence++) + ".userdb");
}

static LlmRerankFilter MakeContextFilter(ContextCounter* counter,
                                         double gamma,
                                         double saturate_k,
                                         const string& prev_word,
                                         double sys_coeff = 1.0,
                                         double usr_coeff = 1.0) {
  auto ctx = New<ContextScorer>(counter, saturate_k);
  ctx->set_prev_word(prev_word);
  auto weight = New<WeightScorer>(sys_coeff, usr_coeff);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<CompositeScorer>(weight, ctx));
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  filter.set_gamma(gamma);
  return filter;
}

TEST(ContextScorerTest, EvidenceMissIsZero) {
  EXPECT_DOUBLE_EQ(0.0, ContextScorer::EvidenceStrength(0, 0, 3.0));
  EXPECT_DOUBLE_EQ(0.0, ContextScorer::EvidenceStrength(0, 5, 3.0));
}

TEST(ContextScorerTest, EvidenceSingleObservationNotAtBound) {
  // pair=1, total=1, k=3 -> relative preference 1 * saturate 1/(1+3) = 0.25.
  double s = ContextScorer::EvidenceStrength(1, 1, 3.0);
  EXPECT_DOUBLE_EQ(0.25, s);
  EXPECT_LT(s, 1.0);
}

TEST(ContextScorerTest, EvidenceBoundedBelowOne) {
  double s = ContextScorer::EvidenceStrength(10000, 10000, 3.0);
  EXPECT_LT(s, 1.0);
  EXPECT_GT(s, 0.9);
}

TEST(ContextScorerTest, EvidenceScalesWithRelativePreference) {
  // pair=1, total=4, k=3 -> (1/4) * (1/4) = 0.0625.
  EXPECT_DOUBLE_EQ(0.0625, ContextScorer::EvidenceStrength(1, 4, 3.0));
}

TEST(ContextScorerTest, EvidenceMonotonicInCount) {
  double a = ContextScorer::EvidenceStrength(1, 1, 3.0);
  double b = ContextScorer::EvidenceStrength(5, 5, 3.0);
  double c = ContextScorer::EvidenceStrength(50, 50, 3.0);
  EXPECT_LT(a, b);
  EXPECT_LT(b, c);
}

TEST(ContextScorerTest, SaturateKControlsSaturationSpeed) {
  EXPECT_DOUBLE_EQ(0.5, ContextScorer::EvidenceStrength(1, 1, 1.0));
  EXPECT_DOUBLE_EQ(0.1, ContextScorer::EvidenceStrength(1, 1, 9.0));
}

TEST(ContextScorerTest, ReturnsUnscaledRetrievalEvidence) {
  FakeCounter counter;
  counter.SetTotal("w", 2);
  counter.SetPair("w", "乙", 2);
  auto ctx = New<ContextScorer>(&counter, 3.0);
  ctx->set_prev_word("w");
  ScoreComponents score;
  ctx->Score(MakePhrase("table", 0, 2, "乙", 0.0), &score);
  EXPECT_DOUBLE_EQ(0.0, score.base_score);
  EXPECT_DOUBLE_EQ(0.4, score.retrieval_evidence);  // (2/2) * (2/5)
}

TEST(ContextScorerTest, EmptyPrevWordScoresZero) {
  FakeCounter counter;
  counter.SetTotal("w", 2);
  counter.SetPair("w", "乙", 2);
  auto ctx = New<ContextScorer>(&counter, 3.0);  // no prev_word set
  ScoreComponents score;
  EXPECT_TRUE(ctx->Score(MakePhrase("table", 0, 2, "乙", 0.0), &score));
  EXPECT_DOUBLE_EQ(0.0, score.retrieval_evidence);
}

TEST(ContextScorerTest, CounterFailurePassesThroughWholeWindow) {
  FailingCounter counter;
  auto filter = MakeContextFilter(&counter, 2.0, 3.0, "上文");

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(ContextScorerTest, TargetReadErrorWithReadableMetadataPassesThroughWindow) {
  auto store = New<InjectedContextStore>(ContextReadStatus::kError);
  string metadata;
  ASSERT_EQ(ContextReadStatus::kFound,
            store->Fetch("\x01/db_name", &metadata));
  ContextMemory memory(store);
  auto filter = MakeContextFilter(&memory, 2.0, 3.0, "上文");

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(ContextScorerTest, RealLevelDbMissingKeyIsSuccessfulZeroEvidence) {
  const path db_path = TemporaryContextDbPath();
  leveldb::Options options;
  options.create_if_missing = true;
  leveldb::DB* raw_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  delete raw_db;
  auto memory = ContextMemory::OpenLevelDb(db_path);
  ASSERT_TRUE(memory);

  vector<string> emitted;
  {
    auto filter = MakeContextFilter(memory.get(), 10.0, 3.0, "上文");
    emitted = CollectTexts(ApplyFilter(filter, {
                                                   MakePhrase("table", 0, 2, "甲", 1.0),
                                                   MakePhrase("table", 0, 2, "乙", 3.0),
                                                   MakePhrase("table", 0, 4, "丙", 0.0),
                                               }));
  }
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), emitted);

  memory->Record("上文", "乙");
  int pair_count;
  int total_count;
  EXPECT_TRUE(memory->PairCount("上文", "乙", &pair_count));
  EXPECT_TRUE(memory->TotalCount("上文", &total_count));
  EXPECT_EQ(1, pair_count);
  EXPECT_EQ(1, total_count);

  memory.reset();
  EXPECT_TRUE(leveldb::DestroyDB(db_path.string(), options).ok());
}

TEST(ContextMemoryTest, MissingOrMalformedCommitCountFails) {
  const vector<string> invalid_values{
      "d=0 t=0", "c=", "c=not-a-number d=0 t=0", "c=-1 d=0 t=0",
      "c=1 c=2 d=0 t=0"};
  for (const string& value : invalid_values) {
    SCOPED_TRACE(value);
    ContextMemory memory(
        New<InjectedContextStore>(ContextReadStatus::kFound, value));
    int count = 99;
    EXPECT_FALSE(memory.PairCount("上文", "候选", &count));
    EXPECT_EQ(99, count);
  }
}

TEST(ContextMemoryTest, ProductionLevelDbStatusClassificationIsTriState) {
  EXPECT_EQ(ContextReadStatus::kFound,
            ClassifyLevelDbReadStatus(leveldb::Status::OK()));
  EXPECT_EQ(ContextReadStatus::kMissing,
            ClassifyLevelDbReadStatus(leveldb::Status::NotFound("missing")));
  EXPECT_EQ(ContextReadStatus::kError,
            ClassifyLevelDbReadStatus(leveldb::Status::IOError("read failed")));
  EXPECT_EQ(ContextReadStatus::kError,
            ClassifyLevelDbReadStatus(leveldb::Status::Corruption("damaged")));
}

TEST(CompositeScorerTest, RejectsWeightlessCandidate) {
  FakeCounter counter;
  counter.SetTotal("w", 3);
  counter.SetPair("w", "，", 3);
  auto ctx = New<ContextScorer>(&counter, 3.0);
  ctx->set_prev_word("w");
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), ctx);
  ScoreComponents score;
  EXPECT_FALSE(comp->Score(New<SimpleCandidate>("punct", 0, 2, "，"), &score));
  EXPECT_TRUE(comp->Score(MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(CompositeScorerTest, SumsWeightAndContext) {
  FakeCounter counter;
  counter.SetTotal("w", 4);
  counter.SetPair("w", "甲", 4);
  auto ctx = New<ContextScorer>(&counter, 3.0);
  ctx->set_prev_word("w");
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), ctx);
  ScoreComponents score;
  ASSERT_TRUE(comp->Score(MakePhrase("table", 0, 2, "甲", 2.0), &score));
  EXPECT_DOUBLE_EQ(2.0, score.base_score);
  EXPECT_NEAR(4.0 / 7.0, score.retrieval_evidence, 1e-9);
}

TEST(CompositeScorerTest, EnabledContextFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0),
                                     New<FailingScorer>());
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledWeightFailurePassesThroughWholeWindow) {
  auto scorer =
      New<CompositeScorer>(New<FailingScorer>(), nullptr, nullptr);
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledPrepareFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0),
                                     New<PrepareFailingScorer>(), nullptr);
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledLlmFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), nullptr,
                                     New<FailingScorer>());
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, DisabledOptionalTermsDoNotFailScoring) {
  auto scorer =
      New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), nullptr, nullptr);
  auto filter = MakeFilter(scorer);

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(ContextRerankTest, MissLeavesOrderUnchanged) {
  FakeCounter counter;  // no observations
  auto filter = MakeContextFilter(&counter, 10.0, 3.0, "发起");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(ContextRerankTest, ZeroEvidenceStillUsesCompleteBaseStrategy) {
  FakeCounter counter;  // no observations is a successful zero-evidence result
  auto filter = MakeContextFilter(&counter, 10.0, 3.0, "发起");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });

  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(ContextRerankTest, HitPromotesCandidate) {
  FakeCounter counter;
  counter.SetTotal("发起", 5);
  counter.SetPair("发起", "乙", 5);
  auto filter = MakeContextFilter(&counter, 10.0, 3.0, "发起");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  // 乙 = 1 + 10*(5/5)*(5/8) = 7.25 > 甲 = 3.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(ContextRerankTest, GammaZeroKeepsBaseScoreOrder) {
  FakeCounter counter;
  counter.SetTotal("发起", 5);
  counter.SetPair("发起", "乙", 5);
  auto filter = MakeContextFilter(&counter, 0.0, 3.0, "发起");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });

  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(ContextRerankTest, PromotesScriptTranslatorPhrase) {
  // Mirrors the luna_pinyin E2E: candidates carry the script_translator type
  // "phrase"; a recorded (发起 -> 公鸡) observation promotes 公鸡 over the
  // higher-weight 攻击.
  FakeCounter counter;
  counter.SetTotal("发起", 5);
  counter.SetPair("发起", "公鸡", 5);
  auto filter = MakeContextFilter(&counter, 10.0, 3.0, "发起");
  auto filtered =
      ApplyFilter(filter, {
                              MakePhrase("phrase", 0, 6, "攻击", 3.0),
                              MakePhrase("phrase", 0, 6, "公鸡", 1.0),
                              MakePhrase("phrase", 0, 4, "丙", 0.0),
                          });
  EXPECT_EQ((vector<string>{"公鸡", "攻击", "丙"}), CollectTexts(filtered));
}

TEST(ContextRerankTest, OrderTracksCountState) {
  auto cands = [] {
    return vector<an<Candidate>>{
        MakePhrase("table", 0, 2, "甲", 1.0),
        MakePhrase("table", 0, 2, "乙", 2.0),
        MakePhrase("table", 0, 4, "丙", 0.0),
    };
  };
  FakeCounter favors甲;
  favors甲.SetTotal("上文", 4);
  favors甲.SetPair("上文", "甲", 4);
  auto f1 = MakeContextFilter(&favors甲, 10.0, 3.0, "上文");
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}),
            CollectTexts(ApplyFilter(f1, cands())));

  FakeCounter favors乙;
  favors乙.SetTotal("上文", 4);
  favors乙.SetPair("上文", "乙", 4);
  auto f2 = MakeContextFilter(&favors乙, 10.0, 3.0, "上文");
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}),
            CollectTexts(ApplyFilter(f2, cands())));
}

TEST(ContextRerankTest, SingleObservationCannotOverrideLargeWeightGap) {
  // One observation gives s = 1/(1+k) = 0.25; with gamma=2 the boost is 0.5,
  // far short of a weight gap of 10. A single mis-pick cannot pin the order.
  FakeCounter counter;
  counter.SetTotal("上文", 1);
  counter.SetPair("上文", "乙", 1);
  auto filter = MakeContextFilter(&counter, 2.0, 3.0, "上文");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 10.0),
                                          MakePhrase("table", 0, 2, "乙", 0.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

// --- T4: LlmScorer failure paths ---

TEST(LlmScorerTest, DaemonUnavailableReturnsFalse) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  scorer.set_context("发起");
  scorer.Prepare("plan", {"攻击", "公鸡"});
  ScoreComponents score;
  EXPECT_FALSE(scorer.Score(MakePhrase("table", 0, 2, "攻击", 1.0), &score));
}

TEST(LlmScorerTest, DaemonUnavailablePassthroughOrder) {
  auto llm = New<LlmScorer>("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  llm->set_context("发起");
  auto weight = New<WeightScorer>(1.0, 1.0);
  auto comp = New<CompositeScorer>(weight, nullptr, llm);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(comp);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(LlmScorerTest, MalformedResponseReturnsFalse) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  scorer.set_context("test");
  scorer.Prepare("plan", {"甲"});
  ScoreComponents score;
  EXPECT_FALSE(scorer.Score(MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(LlmScorerTest, EmptyPrepareAllowsScore) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  scorer.set_context("");
  scorer.Prepare("plan", {});
  ScoreComponents score;
  EXPECT_FALSE(scorer.Score(MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

int main(int argc, char** argv) {
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
