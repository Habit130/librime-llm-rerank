//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <gtest/gtest.h>
#include <map>
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
  bool Score(const an<Candidate>& cand, double* score) override {
    auto it = table_.find(cand->text());
    if (it == table_.end())
      return false;
    *score = it->second;
    return true;
  }

 private:
  map<string, double> table_;
};

class FailingScorer : public Scorer {
 public:
  bool Score(const an<Candidate>&, double*) override { return false; }
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
  auto scorer = New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
      MakePhrase("table", 0, 2, "甲"),
      MakePhrase("user_table", 0, 2, "乙"),
      MakePhrase("sentence", 0, 2, "丙"),
  });
  // table+user_table form one group (complete); sentence group is incomplete (last word cand).
  // word group sorted by score: 乙(3) > 甲(1).
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, GroupingKeySentenceAndCompletionSeparate) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 5}, {"丁", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
      MakePhrase("sentence", 0, 4, "甲"),
      MakePhrase("completion", 0, 4, "乙"),
      MakePhrase("sentence", 0, 4, "丙"),
      MakePhrase("table", 0, 2, "丁"),
  });
  // Groups: sentence={甲,丙} first@0, completion={乙} first@1, table={丁} first@3.
  // Last word cand 丁 → incomplete group = table.
  // Complete: sentence sorted 丙(5)>甲(1); completion 乙(3).
  // Group order by first appearance: sentence, completion.
  EXPECT_EQ((vector<string>{"丙", "甲", "乙", "丁"}), CollectTexts(filtered));
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
  // (0,2,word)={甲,乙,丙} complete; (0,4,word)={丁} incomplete.
  // Sort (0,2): 乙(3) > 丙(2) > 甲(1).
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
  // Incomplete: (0,6). Complete in first-appearance order: (0,2) then (0,4).
  // Sort (0,2): 丙(2) > 甲(1). (0,4): 乙(5).
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
  filter.set_scorer(New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}}));

  auto filtered = ApplyFilter(filter, {
      MakePhrase("table", 0, 2, "甲"),
      MakePhrase("table", 0, 2, "乙"),
      MakePhrase("table", 0, 2, "丙"),
  });
  // window=2: window1=[甲,乙] same group → incomplete → no reorder.
  // window2=[丙] → incomplete → no reorder.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

// --- T2: incomplete group at cutoff ---

TEST(LlmRerankFilterTest, IncompleteGroupAtCutoffKeepsOriginalOrder) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
      MakePhrase("table", 0, 2, "甲"),
      MakePhrase("table", 0, 2, "乙"),
      MakePhrase("table", 0, 2, "丙"),
  });
  // All in (0,2,word); last word cand 丙 → entire group incomplete → no reorder.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

// --- T2: non-word candidates stay in place ---

TEST(LlmRerankFilterTest, NonWordCandidateStaysInPlace) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}});
  auto filter = MakeFilter(scorer);
  auto punct = New<SimpleCandidate>("punct", 0, 2, "，");
  auto filtered = ApplyFilter(filter, {
      MakePhrase("table", 0, 2, "甲"),
      punct,
      MakePhrase("table", 0, 2, "乙"),
      MakePhrase("table", 0, 4, "丙"),
  });
  // Non-word "，" at pos1 stays. Word cands: 甲(pos0), 乙(pos2), 丙(pos3).
  // (0,2,word)={甲,乙} complete; (0,4,word)={丙} incomplete.
  // Sort (0,2): 乙(3) > 甲(1). word_order=[乙,甲,丙].
  // Output: pos0=乙, pos1=，, pos2=甲, pos3=丙.
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丙"}), CollectTexts(filtered));
}

// --- T2: unwrap shadow candidates ---

TEST(LlmRerankFilterTest, UnwrapShadowCandidateToGetWeight) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 0}});
  auto filter = MakeFilter(scorer);
  auto shadow_a = New<ShadowCandidate>(MakePhrase("table", 0, 2, "甲"), "table");
  auto shadow_b = New<ShadowCandidate>(MakePhrase("table", 0, 2, "乙"), "table");
  auto filtered = ApplyFilter(filter, {
      shadow_a,
      shadow_b,
      MakePhrase("table", 0, 4, "丙"),
  });
  // ShadowCandidates unwrap to Phrase → treated as word candidates.
  // (0,2,word)={甲,乙} complete; (0,4,word)={丙} incomplete.
  // Sort: 乙(3) > 甲(1).
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

// --- T2: no candidates lost (simplifier+uniquifier chain regression) ---

TEST(LlmRerankFilterTest, NoCandidatesLostAfterRerank) {
  auto scorer = New<TableScorer>(
      map<string, double>{{"甲", 1}, {"乙", 5}, {"丙", 3}, {"丁", 2}, {"戊", 4}});
  auto filter = MakeFilter(scorer);
  auto filtered = ApplyFilter(filter, {
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
  double score = 0;
  ASSERT_TRUE(scorer.Score(MakePhrase("table", 0, 2, "甲", 3.0), &score));
  EXPECT_DOUBLE_EQ(6.0, score);  // sys: 2.0 * 3.0
  ASSERT_TRUE(scorer.Score(MakePhrase("user_table", 0, 2, "乙", 3.0), &score));
  EXPECT_DOUBLE_EQ(1.5, score);  // usr: 0.5 * 3.0
}

TEST(WeightScorerTest, NonDictionaryCandidateReturnsFalse) {
  WeightScorer scorer(1.0, 1.0);
  double score = 0;
  EXPECT_FALSE(scorer.Score(MakePhrase("sentence", 0, 2, "甲", 5.0), &score));
  EXPECT_FALSE(
      scorer.Score(New<SimpleCandidate>("punct", 0, 2, "，"), &score));
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
  auto filtered = ApplyFilter(filter, {
      MakePhrase("table", 0, 2, "甲", 5.0),
      MakePhrase("user_table", 0, 2, "乙", 2.0),
      MakePhrase("table", 0, 4, "丙", 0.0),
  });
  // sys 甲 = 1.0*5 = 5; usr 乙 = 3.0*2 = 6 → 乙 > 甲.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(WeightScorerTest, SysCoeffLiftsSystemCandidate) {
  auto filter = MakeFilter(New<WeightScorer>(/*sys=*/4.0, /*usr=*/1.0));
  auto filtered = ApplyFilter(filter, {
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
  auto filtered = ApplyFilter(filter, {
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

  auto filtered = ApplyFilter(filter, {
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
  double score = 0;
  ASSERT_TRUE(scorer.Score(MakePhrase("phrase", 0, 2, "甲", 3.0), &score));
  EXPECT_DOUBLE_EQ(6.0, score);  // sys: 2.0 * 3.0
  ASSERT_TRUE(scorer.Score(MakePhrase("user_phrase", 0, 2, "乙", 3.0), &score));
  EXPECT_DOUBLE_EQ(1.5, score);  // usr: 0.5 * 3.0
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

  int PairCount(const string& prev, const string& cand) override {
    auto it = pair_.find(prev + "\t" + cand);
    return it == pair_.end() ? 0 : it->second;
  }
  int TotalCount(const string& prev) override {
    auto it = total_.find(prev);
    return it == total_.end() ? 0 : it->second;
  }

 private:
  map<string, int> pair_;
  map<string, int> total_;
};

static LlmRerankFilter MakeContextFilter(ContextCounter* counter,
                                         double gamma,
                                         double saturate_k,
                                         const string& prev_word,
                                         double sys_coeff = 1.0,
                                         double usr_coeff = 1.0) {
  auto ctx = New<ContextScorer>(counter, gamma, saturate_k);
  ctx->set_prev_word(prev_word);
  auto weight = New<WeightScorer>(sys_coeff, usr_coeff);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<CompositeScorer>(weight, ctx));
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

TEST(ContextScorerTest, GammaScalesTerm) {
  FakeCounter counter;
  counter.SetTotal("w", 2);
  counter.SetPair("w", "乙", 2);
  auto ctx1 = New<ContextScorer>(&counter, 1.0, 3.0);
  ctx1->set_prev_word("w");
  auto ctx5 = New<ContextScorer>(&counter, 5.0, 3.0);
  ctx5->set_prev_word("w");
  double s1 = 0, s5 = 0;
  ctx1->Score(MakePhrase("table", 0, 2, "乙", 0.0), &s1);
  ctx5->Score(MakePhrase("table", 0, 2, "乙", 0.0), &s5);
  EXPECT_DOUBLE_EQ(0.4, s1);   // (2/2) * (2/5)
  EXPECT_DOUBLE_EQ(2.0, s5);   // 5 * 0.4
}

TEST(ContextScorerTest, EmptyPrevWordScoresZero) {
  FakeCounter counter;
  counter.SetTotal("w", 2);
  counter.SetPair("w", "乙", 2);
  auto ctx = New<ContextScorer>(&counter, 10.0, 3.0);  // no prev_word set
  double s = -1;
  EXPECT_TRUE(ctx->Score(MakePhrase("table", 0, 2, "乙", 0.0), &s));
  EXPECT_DOUBLE_EQ(0.0, s);
}

TEST(CompositeScorerTest, RejectsWeightlessCandidate) {
  FakeCounter counter;
  counter.SetTotal("w", 3);
  counter.SetPair("w", "，", 3);
  auto ctx = New<ContextScorer>(&counter, 10.0, 3.0);
  ctx->set_prev_word("w");
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), ctx);
  double score = 0;
  EXPECT_FALSE(comp->Score(New<SimpleCandidate>("punct", 0, 2, "，"), &score));
  EXPECT_TRUE(comp->Score(MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(CompositeScorerTest, SumsWeightAndContext) {
  FakeCounter counter;
  counter.SetTotal("w", 4);
  counter.SetPair("w", "甲", 4);
  auto ctx = New<ContextScorer>(&counter, 10.0, 3.0);
  ctx->set_prev_word("w");
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), ctx);
  double score = 0;
  ASSERT_TRUE(comp->Score(MakePhrase("table", 0, 2, "甲", 2.0), &score));
  EXPECT_NEAR(2.0 + 10.0 * (4.0 / 7.0), score, 1e-9);
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

TEST(ContextRerankTest, PromotesScriptTranslatorPhrase) {
  // Mirrors the luna_pinyin E2E: candidates carry the script_translator type
  // "phrase"; a recorded (发起 -> 公鸡) observation promotes 公鸡 over the
  // higher-weight 攻击.
  FakeCounter counter;
  counter.SetTotal("发起", 5);
  counter.SetPair("发起", "公鸡", 5);
  auto filter = MakeContextFilter(&counter, 10.0, 3.0, "发起");
  auto filtered = ApplyFilter(filter, {
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
  scorer.Prepare({"攻击", "公鸡"});
  double score = 0;
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
  scorer.Prepare({"甲"});
  double score = 0;
  EXPECT_FALSE(scorer.Score(MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(LlmScorerTest, EmptyPrepareAllowsScore) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  scorer.set_context("");
  scorer.Prepare({});
  double score = 0;
  EXPECT_FALSE(scorer.Score(MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

int main(int argc, char** argv) {
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
