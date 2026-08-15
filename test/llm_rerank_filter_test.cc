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

class InterleavingCounter : public FakeCounter {
 public:
  bool PairCount(const string& prev, const string& cand, int* count) override {
    if (!interleaved_ && interleave_) {
      interleaved_ = true;
      interleave_();
    }
    return FakeCounter::PairCount(prev, cand, count);
  }

  std::function<void()> interleave_;

 private:
  bool interleaved_ = false;
};

class FailingCounter : public ContextCounter {
 public:
  bool PairCount(const string&, const string&, int*) override { return false; }
  bool TotalCount(const string&, int*) override { return false; }
};

class InjectedContextDbBackend : public ContextDbBackend {
 public:
  InjectedContextDbBackend(
      leveldb::Status data_status,
      string data_value = "",
      leveldb::Status metadata_status = leveldb::Status::OK(),
      leveldb::Status update_status = leveldb::Status::OK(),
      int fail_update_at = 1,
      leveldb::Status empty_status = leveldb::Status::OK(),
      bool is_empty = true,
      leveldb::Status metadata_write_status = leveldb::Status::OK())
      : data_status_(std::move(data_status)),
        data_value_(std::move(data_value)),
        metadata_status_(std::move(metadata_status)),
        update_status_(std::move(update_status)),
        fail_update_at_(fail_update_at),
        empty_status_(std::move(empty_status)),
        is_empty_(is_empty),
        metadata_write_status_(std::move(metadata_write_status)) {}

  leveldb::Status Fetch(const string& key, string* value) override {
    if (key == "\x01/db_name" || key == "\x01/db_type" ||
        key == "\x01/user_id") {
      for (const auto& [written_key, written_value] : written_metadata_) {
        if (written_key == key) {
          if (value)
            *value = written_value;
          return leveldb::Status::OK();
        }
      }
      if (metadata_status_.ok()) {
        if (key == "\x01/db_name")
          *value = "test.llm_rerank";
        else if (key == "\x01/db_type")
          *value = "userdb";
        else
          *value = "test-user";
      }
      return metadata_status_;
    }
    if (data_status_.ok())
      *value = data_value_;
    return data_status_;
  }

  leveldb::Status Update(const string&, const string&) override {
    ++update_count_;
    return !update_status_.ok() && update_count_ >= fail_update_at_
               ? update_status_
               : leveldb::Status::OK();
  }

  leveldb::Status WriteMetadata(
      const vector<std::pair<string, string>>& entries) override {
    written_metadata_ = entries;
    return metadata_write_status_;
  }

  leveldb::Status IsEmpty(bool* empty) override {
    if (empty)
      *empty = is_empty_;
    return empty_status_;
  }

  vector<std::pair<string, string>> written_metadata_;

 private:
  leveldb::Status data_status_;
  string data_value_;
  leveldb::Status metadata_status_;
  leveldb::Status update_status_;
  int fail_update_at_;
  int update_count_ = 0;
  leveldb::Status empty_status_;
  bool is_empty_;
  leveldb::Status metadata_write_status_;
};

static ContextStoreIdentity TestContextIdentity() {
  return {"test.llm_rerank", "userdb", "test-user"};
}

static string ContextPairKey(const string& previous, const string& candidate) {
  return "p " + previous + " \t" + candidate;
}

static path TemporaryContextDbPath() {
  static std::atomic<unsigned int> sequence{0};
  return std::filesystem::temp_directory_path() /
         ("llm-rerank-context-" + std::to_string(getpid()) + "-" +
          std::to_string(sequence++) + ".userdb");
}

static path TemporaryContextRoot() {
  return path(TemporaryContextDbPath().string() + ".root");
}

static void CreateContextDb(
    const path& db_path,
    const ContextStoreIdentity& identity,
    const vector<std::pair<string, string>>& entries = {}) {
  leveldb::Options options;
  options.create_if_missing = true;
  leveldb::DB* raw_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  leveldb::WriteBatch batch;
  batch.Put("\x01/db_name", identity.db_name);
  batch.Put("\x01/db_type", identity.db_type);
  batch.Put("\x01/user_id", identity.user_id);
  for (const auto& [key, value] : entries)
    batch.Put(key, value);
  ASSERT_TRUE(raw_db->Write(leveldb::WriteOptions(), &batch).ok());
  delete raw_db;
}

static void DestroyContextDb(const path& db_path) {
  leveldb::Options options;
  options.create_if_missing = false;
  ASSERT_TRUE(leveldb::DestroyDB(db_path.string(), options).ok());
}

static void ExpectUnavailableMemoryPassesThrough(the<ContextMemory> memory) {
  EXPECT_FALSE(memory);
  auto filter = MakeFilter(nullptr);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

static LlmRerankFilter MakeContextFilter(ContextCounter* counter,
                                         double gamma,
                                         double saturate_k,
                                         const string& prev_word,
                                         double sys_coeff = 1.0,
                                         double usr_coeff = 1.0) {
  auto ctx = New<ContextScorer>(counter, saturate_k);
  auto weight = New<WeightScorer>(sys_coeff, usr_coeff);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<CompositeScorer>(weight, ctx));
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  filter.set_last_word(prev_word);
  filter.set_gamma(gamma);
  return filter;
}

TEST(LlmRerankFilterTest, InterleavedLazyTranslationsKeepScoringBatchesOwned) {
  FakeCounter counter;
  counter.SetTotal("context-a", 5);
  counter.SetPair("context-a", "乙", 5);
  counter.SetTotal("context-b", 5);
  counter.SetPair("context-b", "甲", 5);
  auto weight = New<InterleavingWeightScorer>();
  auto context = New<ContextScorer>(&counter, 3.0);
  auto filter = MakeFilter(New<CompositeScorer>(weight, context));
  filter.set_gamma(10.0);
  filter.set_last_word("context-a");
  auto translation_a = ApplyFilter(filter, {
                                               MakePhrase("table", 0, 2, "甲"),
                                               MakePhrase("table", 0, 2, "乙"),
                                           });
  filter.set_last_word("context-b");
  auto translation_b = ApplyFilter(filter, {
                                               MakePhrase("table", 0, 2, "甲"),
                                               MakePhrase("table", 0, 2, "乙"),
                                           });
  vector<string> emitted_b;
  weight->interleave_ = [&] { emitted_b = CollectTexts(translation_b); };

  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectTexts(translation_a));
  EXPECT_EQ((vector<string>{"甲", "乙"}), emitted_b);
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
  ScoreComponents score;
  ASSERT_TRUE(ScoreSingle(ctx.get(), {"plan", "mean-token-lm-v1", "", "w", {}},
                          MakePhrase("table", 0, 2, "乙", 0.0), &score));
  EXPECT_DOUBLE_EQ(0.0, score.base_score);
  EXPECT_DOUBLE_EQ(0.4, score.retrieval_evidence);  // (2/2) * (2/5)
}

TEST(ContextScorerTest, EmptyPrevWordScoresZero) {
  FakeCounter counter;
  counter.SetTotal("w", 2);
  counter.SetPair("w", "乙", 2);
  auto ctx = New<ContextScorer>(&counter, 3.0);
  ScoreComponents score;
  EXPECT_TRUE(ScoreSingle(ctx.get(), {"plan", "mean-token-lm-v1", "", "", {}},
                          MakePhrase("table", 0, 2, "乙", 0.0), &score));
  EXPECT_DOUBLE_EQ(0.0, score.retrieval_evidence);
}

TEST(ContextScorerTest, InterleavedRequestsDoNotReplacePreviousWord) {
  InterleavingCounter counter;
  counter.SetTotal("context-a", 1);
  counter.SetPair("context-a", "乙", 1);
  counter.SetTotal("context-b", 1);
  counter.SetPair("context-b", "甲", 1);
  auto scorer = New<ContextScorer>(&counter, 3.0);
  ScoreComponents nested_score;
  counter.interleave_ = [&] {
    ASSERT_TRUE(ScoreSingle(scorer.get(),
                            {"plan-b", "mean-token-lm-v1", "", "context-b", {}},
                            MakePhrase("table", 0, 2, "甲"), &nested_score));
  };
  ScoreComponents score;

  ASSERT_TRUE(ScoreSingle(scorer.get(),
                          {"plan-a", "mean-token-lm-v1", "", "context-a", {}},
                          MakePhrase("table", 0, 2, "乙"), &score));
  EXPECT_DOUBLE_EQ(0.25, nested_score.retrieval_evidence);
  EXPECT_DOUBLE_EQ(0.25, score.retrieval_evidence);
}

TEST(ContextScorerTest, CounterFailurePassesThroughWholeWindow) {
  FailingCounter counter;
  auto filter = MakeContextFilter(&counter, 2.0, 3.0, "上文");

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(ContextScorerTest,
     TargetReadErrorWithReadableMetadataPassesThroughWindow) {
  auto memory = ContextMemory::OpenBackendForTesting(
      make_unique<InjectedContextDbBackend>(
          leveldb::Status::IOError("target read failed")),
      TestContextIdentity(), false);
  ASSERT_TRUE(memory);
  auto filter = MakeContextFilter(memory.get(), 2.0, 3.0, "上文");

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(ContextScorerTest, RealLevelDbMissingKeyIsSuccessfulZeroEvidence) {
  const path db_path = TemporaryContextDbPath();
  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);

  vector<string> emitted;
  {
    auto filter = MakeContextFilter(memory.get(), 10.0, 3.0, "上文");
    emitted = CollectTexts(
        ApplyFilter(filter, {
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
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, ConcurrentOwnersReuseOneProductionLevelDbHandle) {
  const path db_path = TemporaryContextDbPath();
  const path aliased_path(std::filesystem::path(db_path).parent_path() / "." /
                          db_path.filename());
  auto first = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  auto second = ContextMemory::OpenLevelDb(aliased_path, TestContextIdentity());
  ASSERT_TRUE(first);
  ASSERT_TRUE(second);
  std::thread first_writer([&] {
    for (int i = 0; i < 50; ++i)
      first->Record("上文", "乙");
  });
  std::thread second_writer([&] {
    for (int i = 0; i < 50; ++i)
      second->Record("上文", "乙");
  });
  first_writer.join();
  second_writer.join();

  int first_count = 0;
  int second_count = 0;
  EXPECT_TRUE(first->PairCount("上文", "乙", &first_count));
  EXPECT_TRUE(second->PairCount("上文", "乙", &second_count));
  EXPECT_EQ(100, first_count);
  EXPECT_EQ(first_count, second_count);

  first.reset();
  second.reset();
  leveldb::Options options;
  options.create_if_missing = false;
  leveldb::DB* raw_db = nullptr;
  EXPECT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  delete raw_db;
  auto reopened = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(reopened);
  EXPECT_TRUE(reopened->PairCount("上文", "乙", &first_count));
  EXPECT_EQ(100, first_count);
  reopened.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, WrongIdentityCannotReuseOrDisruptLiveStore) {
  const path db_path = TemporaryContextDbPath();
  auto owner = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(owner);

  EXPECT_FALSE(ContextMemory::OpenLevelDb(
      db_path, {"other-schema.llm_rerank", "userdb", "test-user"}));
  owner->Record("上文", "乙");
  int count = 0;
  EXPECT_TRUE(owner->PairCount("上文", "乙", &count));
  EXPECT_EQ(1, count);

  owner.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, ConcurrentLastReleaseAndReopenNeverDoubleOpens) {
  const path db_path = TemporaryContextDbPath();
  auto owner = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(owner);

  for (int iteration = 0; iteration < 20; ++iteration) {
    std::atomic<bool> start{false};
    the<ContextMemory> reopened;
    std::thread opener([&] {
      while (!start.load())
        std::this_thread::yield();
      reopened = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
    });
    start = true;
    owner.reset();
    opener.join();
    ASSERT_TRUE(reopened) << "iteration " << iteration;
    owner = std::move(reopened);
  }

  owner.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, EmptyDatabaseWithoutMetadataIsRecovered) {
  // First initialization died after LevelDB created its internal files but
  // before the identity metadata batch landed: the directory holds a fully
  // empty LevelDB database.
  const path db_path = TemporaryContextDbPath();
  leveldb::Options options;
  options.create_if_missing = true;
  leveldb::DB* raw_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  delete raw_db;

  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  int count = 99;
  EXPECT_TRUE(memory->PairCount("上文", "候选", &count));
  EXPECT_EQ(0, count);
  memory.reset();

  options.create_if_missing = false;
  leveldb::DB* check_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &check_db).ok());
  string value;
  EXPECT_TRUE(
      check_db->Get(leveldb::ReadOptions(), "\x01/db_name", &value).ok());
  EXPECT_EQ(TestContextIdentity().db_name, value);
  EXPECT_TRUE(
      check_db->Get(leveldb::ReadOptions(), "\x01/db_type", &value).ok());
  EXPECT_EQ(TestContextIdentity().db_type, value);
  EXPECT_TRUE(
      check_db->Get(leveldb::ReadOptions(), "\x01/user_id", &value).ok());
  EXPECT_EQ(TestContextIdentity().user_id, value);
  delete check_db;
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, DatabaseWithDataButWithoutMetadataIsUnavailable) {
  // An unknown database that already carries business data must never be
  // claimed, even when the identity metadata is missing entirely.
  const path db_path = TemporaryContextDbPath();
  leveldb::Options options;
  options.create_if_missing = true;
  leveldb::DB* raw_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  ASSERT_TRUE(raw_db
                  ->Put(leveldb::WriteOptions(), ContextPairKey("上文", "候选"),
                        "c=1 d=0 t=0")
                  .ok());
  delete raw_db;

  ExpectUnavailableMemoryPassesThrough(
      ContextMemory::OpenLevelDb(db_path, TestContextIdentity()));
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, EmptyFirstInitResidueIsRecoveredAndInitialized) {
  auto backend = make_unique<InjectedContextDbBackend>(
      leveldb::Status::NotFound("no data"), "",
      leveldb::Status::NotFound("no metadata"), leveldb::Status::OK(), 1,
      leveldb::Status::OK(), true, leveldb::Status::OK());
  InjectedContextDbBackend* raw = backend.get();
  auto memory = ContextMemory::OpenBackendForTesting(
      std::move(backend), TestContextIdentity(), false);
  ASSERT_TRUE(memory);

  const ContextStoreIdentity identity = TestContextIdentity();
  ASSERT_EQ(4u, raw->written_metadata_.size());
  EXPECT_EQ("\x01/db_name", raw->written_metadata_[0].first);
  EXPECT_EQ(identity.db_name, raw->written_metadata_[0].second);
  EXPECT_EQ("\x01/db_type", raw->written_metadata_[1].first);
  EXPECT_EQ(identity.db_type, raw->written_metadata_[1].second);
  EXPECT_EQ("\x01/user_id", raw->written_metadata_[2].first);
  EXPECT_EQ(identity.user_id, raw->written_metadata_[2].second);
  EXPECT_EQ("\x01/rime_version", raw->written_metadata_[3].first);
  int count = 99;
  EXPECT_TRUE(memory->PairCount("上文", "候选", &count));
  EXPECT_EQ(0, count);
}

TEST(ContextMemoryTest, MetadataWriteFailureOnEmptyResidueIsUnavailable) {
  ExpectUnavailableMemoryPassesThrough(ContextMemory::OpenBackendForTesting(
      make_unique<InjectedContextDbBackend>(
          leveldb::Status::NotFound("no data"), "",
          leveldb::Status::NotFound("no metadata"), leveldb::Status::OK(), 1,
          leveldb::Status::OK(), true,
          leveldb::Status::IOError("metadata write failed")),
      TestContextIdentity(), false));
}

TEST(ContextMemoryTest, EmptyScanErrorOnResidueIsUnavailable) {
  // A failed emptiness scan must fail closed; it is never treated as empty.
  ExpectUnavailableMemoryPassesThrough(ContextMemory::OpenBackendForTesting(
      make_unique<InjectedContextDbBackend>(
          leveldb::Status::NotFound("no data"), "",
          leveldb::Status::NotFound("no metadata"), leveldb::Status::OK(), 1,
          leveldb::Status::IOError("scan failed"), true),
      TestContextIdentity(), false));
}

TEST(ContextMemoryTest, NewDatabaseInitializesAndValidatesMetadata) {
  const path db_path = TemporaryContextDbPath();
  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  memory.reset();

  leveldb::Options options;
  options.create_if_missing = false;
  leveldb::DB* raw_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  string value;
  EXPECT_TRUE(raw_db->Get(leveldb::ReadOptions(), "\x01/db_name", &value).ok());
  EXPECT_EQ(TestContextIdentity().db_name, value);
  EXPECT_TRUE(raw_db->Get(leveldb::ReadOptions(), "\x01/db_type", &value).ok());
  EXPECT_EQ(TestContextIdentity().db_type, value);
  EXPECT_TRUE(raw_db->Get(leveldb::ReadOptions(), "\x01/user_id", &value).ok());
  EXPECT_EQ(TestContextIdentity().user_id, value);
  delete raw_db;
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, UserDbPathNeverFallsBackToExistingSharedDatabase) {
  const path root = TemporaryContextRoot();
  const path user_data_dir = root / "user";
  const path shared_data_dir = root / "shared";
  ASSERT_TRUE(std::filesystem::create_directories(user_data_dir));
  ASSERT_TRUE(std::filesystem::create_directories(shared_data_dir));
  const path shared_db = shared_data_dir / "test.llm_rerank.userdb";
  CreateContextDb(shared_db, TestContextIdentity(),
                  {{ContextPairKey("上文", "候选"), "c=7 d=0 t=0"}});

  auto memory = ContextMemory::OpenUserLevelDb(user_data_dir, "test.llm_rerank",
                                               TestContextIdentity());
  ASSERT_TRUE(memory);
  memory->Record("上文", "候选");
  memory.reset();

  EXPECT_TRUE(
      std::filesystem::is_directory(user_data_dir / "test.llm_rerank.userdb"));
  leveldb::Options options;
  leveldb::DB* raw_shared = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, shared_db.string(), &raw_shared).ok());
  string value;
  EXPECT_TRUE(
      raw_shared
          ->Get(leveldb::ReadOptions(), ContextPairKey("上文", "候选"), &value)
          .ok());
  EXPECT_EQ("c=7 d=0 t=0", value);
  delete raw_shared;
  std::filesystem::remove_all(root);
}

TEST(ContextMemoryTest, UserDbPathRejectsDatabaseSymlink) {
  const path root = TemporaryContextRoot();
  const path user_data_dir = root / "user";
  ASSERT_TRUE(std::filesystem::create_directories(user_data_dir));
  const path outside_db = root / "outside.userdb";
  CreateContextDb(outside_db, TestContextIdentity());
  std::error_code error;
  std::filesystem::create_directory_symlink(
      outside_db, user_data_dir / "test.llm_rerank.userdb", error);
  ASSERT_FALSE(error) << error.message();

  EXPECT_FALSE(ContextMemory::OpenUserLevelDb(user_data_dir, "test.llm_rerank",
                                              TestContextIdentity()));
  EXPECT_TRUE(std::filesystem::is_directory(outside_db));
  std::filesystem::remove_all(root);
}

TEST(ContextMemoryTest, UserDbPathRejectsEscapingDatabaseName) {
  const path root = TemporaryContextRoot();
  const path user_data_dir = root / "user";
  ASSERT_TRUE(std::filesystem::create_directories(user_data_dir));
  auto escaping_identity = TestContextIdentity();
  escaping_identity.db_name = "../escaped";
  const string nul_name("escaped\0ignored", 15);
  auto nul_identity = TestContextIdentity();
  nul_identity.db_name = nul_name;

  EXPECT_FALSE(ContextMemory::OpenUserLevelDb(user_data_dir, "../escaped",
                                              escaping_identity));
  EXPECT_FALSE(
      ContextMemory::OpenUserLevelDb(user_data_dir, nul_name, nul_identity));
  EXPECT_FALSE(std::filesystem::exists(root / "escaped.userdb"));
  std::filesystem::remove_all(root);
}

TEST(ContextMemoryTest, HealthyExistingDatabaseIsAvailable) {
  const path db_path = TemporaryContextDbPath();
  CreateContextDb(db_path, TestContextIdentity());

  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  int count = 99;
  EXPECT_TRUE(memory->PairCount("上文", "候选", &count));
  EXPECT_EQ(0, count);
  memory.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, HealthyExistingMetadataIsNotOverwritten) {
  const path db_path = TemporaryContextDbPath();
  CreateContextDb(db_path, TestContextIdentity(),
                  {{"\x01/rime_version", "existing-version"}});

  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  memory.reset();

  leveldb::Options options;
  options.create_if_missing = false;
  leveldb::DB* raw_db = nullptr;
  ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
  string value;
  EXPECT_TRUE(
      raw_db->Get(leveldb::ReadOptions(), "\x01/rime_version", &value).ok());
  EXPECT_EQ("existing-version", value);
  delete raw_db;
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, WrongDatabaseIdentityIsUnavailable) {
  for (const ContextStoreIdentity& actual :
       {ContextStoreIdentity{"wrong.llm_rerank", "userdb", "test-user"},
        ContextStoreIdentity{"test.llm_rerank", "wrong-type", "test-user"},
        ContextStoreIdentity{"test.llm_rerank", "userdb", "wrong-user"}}) {
    SCOPED_TRACE(actual.db_name + ":" + actual.db_type);
    const path db_path = TemporaryContextDbPath();
    CreateContextDb(db_path, actual);
    ExpectUnavailableMemoryPassesThrough(
        ContextMemory::OpenLevelDb(db_path, TestContextIdentity()));
    DestroyContextDb(db_path);
  }
}

TEST(ContextMemoryTest, MissingOrMalformedIdentityIsUnavailable) {
  const vector<vector<std::pair<string, string>>> metadata_cases{
      {{"\x01/db_name", "test.llm_rerank"}, {"\x01/user_id", "test-user"}},
      {{"\x01/db_type", "userdb"}, {"\x01/user_id", "test-user"}},
      {{"\x01/db_name", "test.llm_rerank"}, {"\x01/db_type", "userdb"}},
      {{"\x01/db_name", ""},
       {"\x01/db_type", "userdb"},
       {"\x01/user_id", "test-user"}},
      {{"\x01/db_name", string("test.llm_rerank\0replacement", 27)},
       {"\x01/db_type", "userdb"},
       {"\x01/user_id", "test-user"}},
      // Partial metadata: only the version banner exists, all three identity
      // keys are missing. LevelDB batch atomicity means our own initializer
      // never leaves this shape; it must not be claimed as a residue.
      {{"\x01/rime_version", "1.2.3"}},
  };
  for (const auto& metadata : metadata_cases) {
    const path db_path = TemporaryContextDbPath();
    leveldb::Options options;
    options.create_if_missing = true;
    leveldb::DB* raw_db = nullptr;
    ASSERT_TRUE(leveldb::DB::Open(options, db_path.string(), &raw_db).ok());
    leveldb::WriteBatch batch;
    for (const auto& [key, value] : metadata)
      batch.Put(key, value);
    ASSERT_TRUE(raw_db->Write(leveldb::WriteOptions(), &batch).ok());
    delete raw_db;

    ExpectUnavailableMemoryPassesThrough(
        ContextMemory::OpenLevelDb(db_path, TestContextIdentity()));
    DestroyContextDb(db_path);
  }
}

TEST(ContextMemoryTest, MetadataReadErrorIsUnavailable) {
  ExpectUnavailableMemoryPassesThrough(ContextMemory::OpenBackendForTesting(
      make_unique<InjectedContextDbBackend>(
          leveldb::Status::NotFound("data"), "",
          leveldb::Status::IOError("metadata read failed")),
      TestContextIdentity(), false));
}

TEST(ContextMemoryTest, ReplacementAtPathIsRejectedByFinalHandle) {
  const path db_path = TemporaryContextDbPath();
  const path original_path(db_path.string() + ".original");
  CreateContextDb(db_path, TestContextIdentity());
  std::filesystem::rename(db_path, original_path);
  CreateContextDb(db_path, {"replacement.llm_rerank", "userdb", "test-user"});

  ExpectUnavailableMemoryPassesThrough(
      ContextMemory::OpenLevelDb(db_path, TestContextIdentity()));
  DestroyContextDb(db_path);
  DestroyContextDb(original_path);
}

TEST(ContextMemoryTest, ValidProductionValueReturnsCommitCount) {
  const path db_path = TemporaryContextDbPath();
  CreateContextDb(db_path, TestContextIdentity(),
                  {{ContextPairKey("上文", "候选"), "c=5 d=1.25 t=42"}});
  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  int count = 0;
  EXPECT_TRUE(memory->PairCount("上文", "候选", &count));
  EXPECT_EQ(5, count);
  memory.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, UserDbTombstoneIsADeletedZeroCount) {
  const path db_path = TemporaryContextDbPath();
  UserDbValue value;
  value.commits = -1;
  value.dee = 0.25;
  value.tick = 42;
  CreateContextDb(db_path, TestContextIdentity(),
                  {{ContextPairKey("上文", "候选"), value.Pack()}});
  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  int count = 99;

  EXPECT_TRUE(memory->PairCount("上文", "候选", &count));
  EXPECT_EQ(0, count);
  memory.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, RecordingRestartsUserDbTombstoneFromZero) {
  const path db_path = TemporaryContextDbPath();
  UserDbValue value;
  value.commits = -1;
  CreateContextDb(db_path, TestContextIdentity(),
                  {{ContextPairKey("上文", "候选"), value.Pack()}});
  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);

  memory->Record("上文", "候选");
  int pair_count = 0;
  int total_count = 0;
  EXPECT_TRUE(memory->PairCount("上文", "候选", &pair_count));
  EXPECT_TRUE(memory->TotalCount("上文", &total_count));
  EXPECT_EQ(1, pair_count);
  EXPECT_EQ(1, total_count);
  memory.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, AcceptsExactPackOutputInCurrentLocale) {
  ScopedGlobalLocale locale(
      std::locale(std::locale::classic(), new PunctuatedNumberLocale));
  const path db_path = TemporaryContextDbPath();
  UserDbValue value;
  value.commits = 1234;
  value.dee = 1.25;
  value.tick = 5678;
  const string packed = value.Pack();
  ASSERT_EQ("c=1.234 d=1,25 t=5.678", packed);
  CreateContextDb(db_path, TestContextIdentity(),
                  {{ContextPairKey("上文", "候选"), packed}});
  auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
  ASSERT_TRUE(memory);
  int count = 0;

  EXPECT_TRUE(memory->PairCount("上文", "候选", &count));
  EXPECT_EQ(1234, count);
  memory.reset();
  DestroyContextDb(db_path);
}

TEST(ContextMemoryTest, MalformedProductionValuesFailClosed) {
  const vector<string> invalid_values{"d=0 t=0",
                                      "c=",
                                      "c=not-a-number d=0 t=0",
                                      "c=1 c=2 d=0 t=0",
                                      "c=5 d=broken t=0",
                                      "c=5 d=0 t=broken",
                                      "c=5 d=0 t=0 trailing",
                                      "c=5 d=0 t=0x",
                                      "c=5 d=nan t=0",
                                      "c=5 d=inf t=0",
                                      "c=5 d=0 t=18446744073709551616",
                                      "c=2147483648 d=0 t=0",
                                      "c=5 d=0 t=0 unknown=1",
                                      "c=5 d=0 d=1 t=0",
                                      "c=5 d=0 t=0 t=1",
                                      "d=0 c=5 t=0",
                                      "c=5  d=0 t=0",
                                      "c=5 d=1e999 t=0",
                                      "c=5 d=0x t=0",
                                      "c=5 d=0 t=-1",
                                      "c=5x d=0 t=0"};
  for (const string& value : invalid_values) {
    SCOPED_TRACE(value);
    const path db_path = TemporaryContextDbPath();
    CreateContextDb(db_path, TestContextIdentity(),
                    {{ContextPairKey("上文", "甲"), value}});
    auto memory = ContextMemory::OpenLevelDb(db_path, TestContextIdentity());
    ASSERT_TRUE(memory);
    int count = 99;
    EXPECT_FALSE(memory->PairCount("上文", "甲", &count));
    EXPECT_EQ(99, count);
    auto filter = MakeContextFilter(memory.get(), 2.0, 3.0, "上文");
    EXPECT_EQ(kFailureWindowOriginalOrder,
              CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
    memory.reset();
    DestroyContextDb(db_path);
  }
}

TEST(ContextMemoryTest, UpdateFailurePoisonsSubsequentScoringReads) {
  for (int fail_update_at : {1, 2, 3}) {
    SCOPED_TRACE(fail_update_at);
    auto memory = ContextMemory::OpenBackendForTesting(
        make_unique<InjectedContextDbBackend>(
            leveldb::Status::NotFound("missing"), "", leveldb::Status::OK(),
            leveldb::Status::IOError("write failed"), fail_update_at),
        TestContextIdentity(), false);
    ASSERT_TRUE(memory);
    memory->Record("上文", "甲");
    int count = 99;
    EXPECT_FALSE(memory->PairCount("上文", "甲", &count));
    auto filter = MakeContextFilter(memory.get(), 2.0, 3.0, "上文");
    EXPECT_EQ(kFailureWindowOriginalOrder,
              CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
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
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), ctx);
  ScoreComponents score;
  EXPECT_FALSE(ScoreSingle(comp.get(),
                           {"plan", "mean-token-lm-v1", "", "w", {}},
                           New<SimpleCandidate>("punct", 0, 2, "，"), &score));
  EXPECT_TRUE(ScoreSingle(comp.get(), {"plan", "mean-token-lm-v1", "", "w", {}},
                          MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(CompositeScorerTest, SumsWeightAndContext) {
  FakeCounter counter;
  counter.SetTotal("w", 4);
  counter.SetPair("w", "甲", 4);
  auto ctx = New<ContextScorer>(&counter, 3.0);
  auto comp = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), ctx);
  ScoreComponents score;
  ASSERT_TRUE(ScoreSingle(comp.get(), {"plan", "mean-token-lm-v1", "", "w", {}},
                          MakePhrase("table", 0, 2, "甲", 2.0), &score));
  EXPECT_DOUBLE_EQ(2.0, score.base_score);
  EXPECT_NEAR(4.0 / 7.0, score.retrieval_evidence, 1e-9);
}

TEST(CompositeScorerTest, EnabledContextFailurePassesThroughWholeWindow) {
  auto scorer =
      New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), New<FailingScorer>());
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledWeightFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<FailingScorer>(), nullptr, nullptr);
  auto filter = MakeFilter(scorer);

  EXPECT_EQ(kFailureWindowOriginalOrder,
            CollectTexts(ApplyFilter(filter, FailureWindowCandidates())));
}

TEST(CompositeScorerTest, EnabledBatchFailurePassesThroughWholeWindow) {
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0),
                                     New<BatchFailingScorer>(), nullptr);
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
                           {"plan", "mean-token-lm-v1", "发起", "", {}},
                           MakePhrase("table", 0, 2, "攻击", 1.0), &score));
}

TEST(LlmScorerTest, DaemonUnavailablePassthroughOrder) {
  auto llm = New<LlmScorer>("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  auto weight = New<WeightScorer>(1.0, 1.0);
  auto comp = New<CompositeScorer>(weight, nullptr, llm);
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
                           {"plan", "mean-token-lm-v1", "test", "", {}},
                           MakePhrase("table", 0, 2, "甲", 1.0), &score));
}

TEST(LlmScorerTest, EmptyBatchReturnsNoScores) {
  LlmScorer scorer("/tmp/nonexistent-llm-rerank-test.sock", 1.0);
  vector<ScoreComponents> scores{{1.0, 1.0}};

  EXPECT_TRUE(
      scorer.ScoreBatch({"plan", "mean-token-lm-v1", "", "", {}}, {}, &scores));
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
