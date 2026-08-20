//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <unistd.h>

#include <atomic>
#include <filesystem>
#include <functional>
#include <limits>
#include <locale>
#include <map>
#include <thread>
#include <utility>

#include <gtest/gtest.h>
#include <leveldb/db.h>
#include <leveldb/write_batch.h>
#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/config.h>
#include <rime/dict/user_db.h>
#include <rime/schema.h>
#include <rime/translation.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_filter.h"
#include "llm_scorer.h"

using namespace rime;

class CandidateScorer : public Scorer {
 public:
  bool ScoreBatch(const ScoringRequest&,
                  const vector<an<Candidate>>& candidates,
                  vector<ScoreComponents>* scores) override {
    if (!scores)
      return false;
    vector<ScoreComponents> result;
    result.reserve(candidates.size());
    for (const auto& candidate : candidates) {
      ScoreComponents score;
      if (!Score(candidate, &score))
        return false;
      result.push_back(score);
    }
    *scores = std::move(result);
    return true;
  }

  virtual bool Score(const an<Candidate>& cand, ScoreComponents* score) = 0;
};

class TableScorer : public CandidateScorer {
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

class FailingScorer : public CandidateScorer {
 public:
  bool Score(const an<Candidate>&, ScoreComponents*) override { return false; }
};

class BatchFailingScorer : public Scorer {
 public:
  bool ScoreBatch(const ScoringRequest&,
                  const vector<an<Candidate>>&,
                  vector<ScoreComponents>*) override {
    return false;
  }
};

class LateFailingScorer : public CandidateScorer {
 public:
  bool Score(const an<Candidate>& cand, ScoreComponents* score) override {
    if (cand->text() == "丁")
      return false;
    score->base_score = 99.0;
    score->retrieval_evidence = 0.0;
    return true;
  }
};

class NonFiniteScorer : public CandidateScorer {
 public:
  bool Score(const an<Candidate>&, ScoreComponents* score) override {
    score->base_score = std::numeric_limits<double>::quiet_NaN();
    score->retrieval_evidence = 0.0;
    return true;
  }
};

class CapturingRequestScorer : public Scorer {
 public:
  bool ScoreBatch(const ScoringRequest& request,
                  const vector<an<Candidate>>& candidates,
                  vector<ScoreComponents>* scores) override {
    if (!scores)
      return false;
    requests.push_back(request);
    vector<ScoreComponents> result;
    for (const auto& candidate : candidates) {
      result.push_back({candidate->text() == "乙" ? 10.0 : 0.0, 0.0});
    }
    *scores = std::move(result);
    return true;
  }

  vector<ScoringRequest> requests;
};

class InterleavingWeightScorer : public CandidateScorer {
 public:
  bool Score(const an<Candidate>& cand, ScoreComponents* score) override {
    if (!interleaved_ && interleave_) {
      interleaved_ = true;
      interleave_();
    }
    score->base_score = cand->text() == "甲" ? 2.0 : 1.0;
    score->retrieval_evidence = 0.0;
    return true;
  }

  std::function<void()> interleave_;

 private:
  bool interleaved_ = false;
};

class PunctuatedNumberLocale : public std::numpunct<char> {
 protected:
  char do_decimal_point() const override { return ','; }
  char do_thousands_sep() const override { return '.'; }
  string do_grouping() const override { return "\3"; }
};

class ScopedGlobalLocale {
 public:
  explicit ScopedGlobalLocale(const std::locale& locale)
      : previous_(std::locale::global(locale)) {}
  ~ScopedGlobalLocale() { std::locale::global(previous_); }

 private:
  std::locale previous_;
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

static bool ScoreSingle(Scorer* scorer,
                        ScoringRequest request,
                        const an<Candidate>& candidate,
                        ScoreComponents* score) {
  if (!scorer || !candidate || !score)
    return false;
  request.candidate_texts = {candidate->text()};
  vector<ScoreComponents> scores;
  if (!scorer->ScoreBatch(request, {candidate}, &scores) || scores.size() != 1)
    return false;
  *score = scores.front();
  return true;
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

static const vector<string> kFailureWindowOriginalOrder{"甲", "，", "乙",
                                                        "丙", "丁", "整句"};

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

TEST(LlmRerankFilterTest, LazyTranslationsKeepTheirOwnScoringContext) {
  auto scorer = New<CapturingRequestScorer>();
  auto filter = MakeFilter(scorer);
  filter.set_preceding_text("上文甲");
  auto translation_a = ApplyFilter(filter, {
                                               MakePhrase("table", 0, 2, "甲"),
                                               MakePhrase("table", 0, 2, "乙"),
                                           });
  filter.set_preceding_text("上文乙");
  auto translation_b = ApplyFilter(filter, {
                                               MakePhrase("table", 0, 2, "甲"),
                                               MakePhrase("table", 0, 2, "乙"),
                                           });

  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectTexts(translation_a));
  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectTexts(translation_b));
  ASSERT_EQ(2u, scorer->requests.size());
  EXPECT_EQ("上文甲", scorer->requests[0].preceding_text);
  EXPECT_EQ("上文乙", scorer->requests[1].preceding_text);
  EXPECT_NE(scorer->requests[0].plan_identity,
            scorer->requests[1].plan_identity);
  EXPECT_EQ((vector<string>{"甲", "乙"}), scorer->requests[0].candidate_texts);
  EXPECT_EQ((vector<string>{"甲", "乙"}), scorer->requests[1].candidate_texts);
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
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 0, 4, "丙"),
                                      });
  // (0,2,word) is complete; scorer fails → passthrough.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, BatchFailurePassesThroughWholeWindow) {
  auto filter = MakeFilter(New<BatchFailingScorer>());

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

// --- T5: retrieval-evidence term (Squirrel#61) ---

// The evidence term is per rerank group: the filter asks the daemon (through
// an EvidenceScorer) for the canonical oracle's candidate-level evidence s_c
// and applies gamma * s_c to the base score only on a complete, identity-bound
// success response. Zero evidence is a success with all-zero s_c; every fault
// (transport, protocol, identity, watermark) passes the whole window through
// in original order. The old first-stage bigram term is gone; there is no
// second term to double-count.

class FakeEvidenceScorer : public EvidenceScorer {
 public:
  FakeEvidenceScorer() : EvidenceScorer("", "") {}

  bool ScoreGroup(const GroupRequest& request,
                  vector<double>* s_c) override {
    requests.push_back(request);
    if (fail_)
      return false;
    auto it = scripted_.find(request.canonical_segment_input);
    if (it == scripted_.end()) {
      // Unscripted group: served as success-zero evidence, exactly like the
      // daemon serves an empty store or no qualified history.
      *s_c = vector<double>(request.candidate_texts.size(), 0.0);
      return true;
    }
    if (it->second.size() != request.candidate_texts.size())
      return false;
    *s_c = it->second;
    return true;
  }

  bool fail_ = false;
  map<string, vector<double>> scripted_;
  vector<GroupRequest> requests;
};

static const EvidenceScorer::GroupRequest* FindGroupRequest(
    const vector<EvidenceScorer::GroupRequest>& requests,
    const string& canonical_input) {
  for (const auto& request : requests) {
    if (request.canonical_segment_input == canonical_input)
      return &request;
  }
  return nullptr;
}

static path EvidenceFactsRoot() {
  static std::atomic<unsigned int> sequence{0};
  return std::filesystem::temp_directory_path() /
         ("llm-rerank-evidence-" + std::to_string(getpid()) + "-" +
          std::to_string(sequence++));
}

static LlmRerankFilter MakeEvidenceFilter(an<FakeEvidenceScorer> evidence,
                                          double gamma = 2.0) {
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<WeightScorer>(1.0, 1.0));
  filter.set_evidence_scorer(evidence);
  filter.set_evidence_active(true);
  filter.set_evidence_config_identity(
      EvidenceScorer::ComposeConfigIdentity("repr-v1", 0.5, 8, 32.0, 3.0,
                                            gamma));
  filter.set_facts_root(EvidenceFactsRoot());
  filter.set_gamma(gamma);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  return filter;
}

TEST(EvidenceRerankTest, HitPromotesCandidateWithinGroup) {
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.5};
  auto filter = MakeEvidenceFilter(evidence, 10.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  // 乙 = 1 + 10*0.5 = 6 > 甲 = 3; 丙 untouched.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(EvidenceRerankTest, ZeroEvidenceKeepsBaseScoreOrder) {
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.0};
  auto filter = MakeEvidenceFilter(evidence, 10.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  // All-zero evidence is a success: comparison equals the base score.
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
}

TEST(EvidenceRerankTest, GammaZeroKeepsBaseScoreOrder) {
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.5};
  auto filter = MakeEvidenceFilter(evidence, 0.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(EvidenceRerankTest, EvidenceFailurePassesThroughWholeWindow) {
  auto evidence = New<FakeEvidenceScorer>();
  evidence->fail_ = true;
  auto filter = MakeEvidenceFilter(evidence, 10.0);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(EvidenceRerankTest, EvidenceOnlyChangesWithinGroup) {
  // Two word groups in one window: (0,2)={甲,乙} gets evidence, (2,4)={丙,丁}
  // has none; the group boundary never leaks.
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.5, 0.0};
  evidence->scripted_["cd"] = {0.0, 0.0};
  auto filter = MakeEvidenceFilter(evidence, 10.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 2, 4, "丙", 5.0),
                                          MakePhrase("table", 2, 4, "丁", 4.0),
                                      });
  // (0,2): 甲 = 1 + 10*0.5 = 6 > 乙 = 3. (2,4): zero evidence, base order
  // 丙(5) > 丁(4). Evidence never crosses the group boundary.
  EXPECT_EQ((vector<string>{"甲", "乙", "丙", "丁"}), CollectTexts(filtered));
}

TEST(EvidenceRerankTest, SupporterMissingLeavesGroupUnchanged) {
  // A group whose history's final selection is absent from the current
  // candidates contributes zero evidence (all s = 0) -> base order.
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.0};
  auto filter = MakeEvidenceFilter(evidence, 10.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                      });
  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectTexts(filtered));
}

// --- T6: trial envelope (Habit130/squirrel#74) ---

TEST(EvidenceRerankTest, TrialEnvelopeCarriesBaseScores) {
  // The trial rides on every complete-group evidence request: it declares
  // the group actionable and carries the γ=0 base scores (identity-only,
  // one per group candidate, in merge order).  The daemon replays shadow
  // vs final emit order from these numbers.
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.5};
  auto filter = MakeEvidenceFilter(evidence, 10.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  EXPECT_EQ((vector<string>{"乙", "甲", "丙"}), CollectTexts(filtered));
  const auto* ab = FindGroupRequest(evidence->requests, "ab");
  ASSERT_NE(nullptr, ab);
  const auto& trial = ab->trial;
  EXPECT_TRUE(trial.present);
  EXPECT_TRUE(trial.actionable);
  ASSERT_EQ(2u, trial.base_scores.size());
  EXPECT_DOUBLE_EQ(3.0, trial.base_scores[0]);
  EXPECT_DOUBLE_EQ(1.0, trial.base_scores[1]);
}

TEST(EvidenceRerankTest, TrialEnvelopeTracksEachGroup) {
  // Each complete group gets its own trial with that group's base scores
  // (never the whole window's).
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.5};
  evidence->scripted_["cd"] = {0.0, 0.0};
  auto filter = MakeEvidenceFilter(evidence, 10.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 3.0),
                                          MakePhrase("table", 0, 2, "乙", 1.0),
                                          MakePhrase("table", 2, 4, "丙", 5.0),
                                          MakePhrase("table", 2, 4, "丁", 4.0),
                                      });
  // Consume the lazy translation so every group request is sent.
  CollectTexts(filtered);
  ASSERT_FALSE(evidence->requests.empty());
  for (const auto& request : evidence->requests) {
    EXPECT_TRUE(request.trial.present);
    EXPECT_TRUE(request.trial.actionable);
    EXPECT_EQ(request.candidate_texts.size(),
              request.trial.base_scores.size());
  }
}

TEST(EvidenceRerankTest, RequestCarriesGroupBinding) {
  // AC61-1: the evidence request carries schema, choice problem, recent
  // 64-char context, the current candidate group, config identity and the
  // fact high-water (absent here: no store in this unit fixture).
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.0};
  auto filter = MakeEvidenceFilter(evidence, 2.0);
  filter.set_preceding_text("敏感测试上文");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                      });
  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectTexts(filtered));
  ASSERT_EQ(1u, evidence->requests.size());
  const auto& req = evidence->requests[0];
  EXPECT_EQ("test", req.schema_id);
  EXPECT_EQ("word", req.category);
  EXPECT_EQ("ab", req.canonical_segment_input);
  EXPECT_EQ("敏感测试上文", req.preceding_text);
  EXPECT_EQ(EvidenceScorer::ComposeConfigIdentity("repr-v1", 0.5, 8, 32.0,
                                                  3.0, 2.0),
            req.config_identity);
  EXPECT_FALSE(req.fact_high_water.present);
  EXPECT_EQ((vector<string>{"甲", "乙"}), req.candidate_texts);
}

TEST(EvidenceRerankTest, EvidenceRequestsAreOnePerCompleteGroup) {
  auto evidence = New<FakeEvidenceScorer>();
  evidence->scripted_["ab"] = {0.0, 0.0};
  evidence->scripted_["cd"] = {0.0, 0.0};
  auto filter = MakeEvidenceFilter(evidence, 2.0);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 2, 4, "丙", 5.0),
                                          MakePhrase("table", 2, 4, "丁", 4.0),
                                      });
  EXPECT_EQ(4u, CollectTexts(filtered).size());
  ASSERT_EQ(2u, evidence->requests.size());
  EXPECT_EQ("ab", evidence->requests[0].canonical_segment_input);
  EXPECT_EQ("cd", evidence->requests[1].canonical_segment_input);
}

TEST(EvidenceRerankTest, IncompleteGroupSendsNoEvidenceRequest) {
  auto evidence = New<FakeEvidenceScorer>();
  auto filter = MakeEvidenceFilter(evidence, 2.0);
  filter.set_window(2);
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 0, 2, "丙", 2.0),
                                      });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
  // The truncated first window holds the boundary group without requesting
  // evidence; the trailing single-candidate complete group is scored.
  ASSERT_EQ(1u, evidence->requests.size());
  EXPECT_EQ("ab", evidence->requests[0].canonical_segment_input);
}

TEST(EvidenceConfigIdentityTest, ComposeMatchesDaemonFormat) {
  // Byte-identical with daemon/evidence.py compose_config_identity; the
  // daemon test pins the same string.
  EXPECT_EQ("evidence-v1:repr=repr-v1:tau=0.5:kev=8:H=32:sat=3:gamma=2",
            EvidenceScorer::ComposeConfigIdentity("repr-v1", 0.5, 8, 32.0,
                                                  3.0, 2.0));
  EXPECT_EQ("evidence-v1:repr=repr-v1:tau=0:kev=8:H=inf:sat=3:gamma=2",
            EvidenceScorer::ComposeConfigIdentity(
                "repr-v1", 0.0, 8,
                std::numeric_limits<double>::infinity(), 3.0, 2.0));
}

// --- CompositeScorer (weight + LLM, no context term) ---

TEST(CompositeScorerTest, RejectsWeightlessCandidate) {
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0));
  ScoreComponents score;
  EXPECT_FALSE(ScoreSingle(comp.get(), {"plan", "mean-token-lm-v1", "", {}},
                           New<SimpleCandidate>("punct", 0, 2, "，"), &score));
  EXPECT_TRUE(ScoreSingle(comp.get(), {"plan", "mean-token-lm-v1", "", {}},
                          MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(CompositeScorerTest, SumsWeightAndLlm) {
  auto llm = New<TableScorer>(map<string, double>{{"甲", 1.0}});
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), llm);
  ScoreComponents score;
  ASSERT_TRUE(ScoreSingle(comp.get(), {"plan", "mean-token-lm-v1", "", {}},
                          MakePhrase("table", 0, 2, "甲", 2.0), &score));
  EXPECT_DOUBLE_EQ(3.0, score.base_score);  // 2.0 weight + 1.0 llm
  EXPECT_DOUBLE_EQ(0.0, score.retrieval_evidence);
}

TEST(CompositeScorerTest, EnabledWeightFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<FailingScorer>());
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledBatchFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0),
                                     New<BatchFailingScorer>());
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledLlmFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0),
                                     New<FailingScorer>());
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, DisabledOptionalTermsDoNotFailScoring) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0));
  auto filter = MakeFilter(scorer);

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}


// --- T4: LlmScorer failure paths ---

// --- #51: three-switch behavior at the filter seam ---

// Holds the Schema (and its owned Config) alive for the filter's lifetime:
// the filter only reads config at construction, but the Schema must outlive
// the ctor call.
struct SchemaFilter {
  std::unique_ptr<Schema> schema;
  LlmRerankFilter filter;

  static SchemaFilter From(Config* config) {
    auto schema = std::make_unique<Schema>("test", config);
    Ticket ticket;
    ticket.schema = schema.get();
    ticket.name_space = "llm_rerank";
    return SchemaFilter{std::move(schema), LlmRerankFilter(ticket)};
  }
};

TEST(LlmRerankFilterTest, RerankingOffReturnsIdentityAndSkipsScoring) {
  auto* config = new Config;
  config->SetBool("llm_rerank/reranking_enabled", false);
  config->SetBool("llm_rerank/recording_enabled", false);
  config->SetBool("llm_rerank/evidence_enabled", false);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  auto captured = New<CapturingRequestScorer>();
  filter.set_scorer(captured);
  auto translation = New<VecTranslation>(std::vector<an<Candidate>>{
      MakePhrase("table", 0, 2, "甲", 1.0),
      MakePhrase("table", 0, 2, "乙", 3.0),
  });
  CandidateList candidates;
  auto filtered = filter.Apply(translation, &candidates);
  // The very same translation object passes through untouched: no wrapping,
  // no scoring, no reordering.
  EXPECT_EQ(translation.get(), filtered.get());
  EXPECT_EQ((vector<string>{"甲", "乙"}), CollectTexts(filtered));
  EXPECT_TRUE(captured->requests.empty());
}

TEST(LlmRerankFilterTest, RerankingOffSkipsScoringEvenWithOnCombo) {
  // Reranking off + recording on: still no synchronous model scoring and no
  // reordering. (The snapshot-only wrap needs a recorder session, which only
  // exists inside a real engine — covered by the E2E
  // RecorderE2ETest.RerankingOffStillRecordsEvents.)
  auto* config = new Config;
  config->SetBool("llm_rerank/reranking_enabled", false);
  config->SetBool("llm_rerank/recording_enabled", true);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  auto captured = New<CapturingRequestScorer>();
  filter.set_scorer(captured);
  auto translation = New<VecTranslation>(std::vector<an<Candidate>>{
      MakePhrase("table", 0, 2, "甲", 1.0),
      MakePhrase("table", 0, 2, "乙", 3.0),
  });
  CandidateList candidates;
  auto filtered = filter.Apply(translation, &candidates);
  EXPECT_EQ((vector<string>{"甲", "乙"}), CollectTexts(filtered));
  EXPECT_TRUE(captured->requests.empty());
}

TEST(LlmRerankFilterTest, SwitchSnapshotIsTakenAtConstruction) {
  // The three switches form an immutable snapshot at Engine/schema instance
  // creation; mutating the config afterwards never changes behavior
  // mid-composition (spec: "配置在 Engine/schema 实例创建时形成不可变快照").
  auto* config = new Config;
  config->SetBool("llm_rerank/reranking_enabled", false);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  auto captured = New<CapturingRequestScorer>();
  filter.set_scorer(captured);
  // The config changes behind the filter's back; the instance must not adopt
  // it.
  config->SetBool("llm_rerank/reranking_enabled", true);
  auto translation = New<VecTranslation>(std::vector<an<Candidate>>{
      MakePhrase("table", 0, 2, "甲", 1.0),
      MakePhrase("table", 0, 2, "乙", 3.0),
  });
  CandidateList candidates;
  auto filtered = filter.Apply(translation, &candidates);
  EXPECT_EQ(translation.get(), filtered.get());
  EXPECT_TRUE(captured->requests.empty());
}

TEST(LlmRerankFilterTest, LegacyEnableKeepsVisibleReranking) {
  auto* config = new Config;
  config->SetBool("llm_rerank/enable", true);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  filter.set_scorer(
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}}));
  filter.set_input("abcdef");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                      });
  // First-stage visible reranking is maintained under legacy config.
  EXPECT_EQ((vector<string>{"乙", "丙", "甲"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, LegacyEnableFalsePassesThrough) {
  auto* config = new Config;
  config->SetBool("llm_rerank/enable", false);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  filter.set_scorer(
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}}));
  auto translation = New<VecTranslation>(std::vector<an<Candidate>>{
      MakePhrase("table", 0, 2, "甲"),
      MakePhrase("table", 0, 2, "乙"),
  });
  CandidateList candidates;
  auto filtered = filter.Apply(translation, &candidates);
  EXPECT_EQ(translation.get(), filtered.get());
}

TEST(LlmRerankFilterTest, V2RerankingOnStillReranks) {
  auto* config = new Config;
  config->SetBool("llm_rerank/reranking_enabled", true);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  filter.set_scorer(
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}}));
  filter.set_input("abcdef");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                      });
  EXPECT_EQ((vector<string>{"乙", "丙", "甲"}), CollectTexts(filtered));
}

TEST(LlmRerankFilterTest, V2CoexistV2WinsOverLegacyEnable) {
  // New and old keys coexist: v2 takes precedence (and a deprecation warning
  // is logged). `enable: false` must be ignored — reranking stays on.
  auto* config = new Config;
  config->SetBool("llm_rerank/enable", false);
  config->SetBool("llm_rerank/reranking_enabled", true);
  auto holder = SchemaFilter::From(config);
  auto& filter = holder.filter;
  filter.set_scorer(
      New<TableScorer>(map<string, double>{{"甲", 1}, {"乙", 3}, {"丙", 2}}));
  filter.set_input("abcdef");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲"),
                                          MakePhrase("table", 0, 2, "乙"),
                                          MakePhrase("table", 0, 2, "丙"),
                                      });
  EXPECT_EQ((vector<string>{"乙", "丙", "甲"}), CollectTexts(filtered));
}

TEST(LlmScorerTest, DaemonUnavailableReturnsFalse) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  ScoreComponents score;
  EXPECT_FALSE(ScoreSingle(&scorer,
                           {"plan", "mean-token-lm-v1", "发起", {}},
                           MakePhrase("table", 0, 2, "攻击", 1.0), &score));
}

TEST(LlmScorerTest, DaemonUnavailablePassthroughOrder) {
  auto llm = New<LlmScorer>("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  auto weight = New<WeightScorer>(1.0, 1.0);
  auto comp = New<CompositeScorer>(weight, llm);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(comp);
  filter.set_preceding_text("发起");
  auto filtered = ApplyFilter(filter, {
                                          MakePhrase("table", 0, 2, "甲", 1.0),
                                          MakePhrase("table", 0, 2, "乙", 3.0),
                                          MakePhrase("table", 0, 4, "丙", 0.0),
                                      });
  EXPECT_EQ((vector<string>{"甲", "乙", "丙"}), CollectTexts(filtered));
}

TEST(LlmScorerTest, MalformedResponseReturnsFalse) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  ScoreComponents score;
  EXPECT_FALSE(ScoreSingle(&scorer,
                           {"plan", "mean-token-lm-v1", "test", {}},
                           MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(LlmScorerTest, EmptyBatchReturnsNoScores) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  vector<ScoreComponents> scores{{1.0, 1.0}};

  EXPECT_TRUE(
      scorer.ScoreBatch({"plan", "mean-token-lm-v1", "", {}}, {}, &scores));
  EXPECT_TRUE(scores.empty());
}

// Spawned-writer mode of ConcurrentWritersBothPersistAtomically (see
// fact_store_test.cc): _exit()s inside when this process was relaunched as
// the second writer, before gtest ever initializes.
void RunSpawnedWriterMode(int argc, char** argv);
void RunSpawnedRecorderGapMode(int argc, char** argv);

int main(int argc, char** argv) {
  RunSpawnedWriterMode(argc, argv);
  RunSpawnedRecorderGapMode(argc, argv);
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
