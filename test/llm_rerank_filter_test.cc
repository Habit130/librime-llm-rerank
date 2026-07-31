//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <gtest/gtest.h>
#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/translation.h>

#include "llm_rerank_filter.h"

using namespace rime;

// Hand-written translation producing a known candidate sequence, after
// librime's test/menu_test.cc.
class TranslationFixture : public Translation {
 public:
  TranslationFixture() : cursor_(0) {
    candies_.push_back(New<SimpleCandidate>("table", 0, 2, "你好"));
    candies_.push_back(New<SimpleCandidate>("table", 0, 2, "尼好"));
    candies_.push_back(New<SimpleCandidate>("table", 0, 2, "泥嚎"));
  }

  bool Next() {
    if (exhausted())
      return false;
    ++next_count_;
    if (++cursor_ >= candies_.size())
      set_exhausted(true);
    return true;
  }

  an<Candidate> Peek() {
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

  bool Next() { return false; }

  an<Candidate> Peek() { return nullptr; }
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

// Regression: the filter sits after uniquifier, whose dedup window is the
// menu's already-emitted candidate list. Pulling upstream faster than the
// consumer pulls (e.g. draining at construction) defeats that dedup and
// leaks post-simplification duplicates. The wrapper must stay lazy: no pull
// at construction, exactly one upstream candidate per on-demand replenish.
TEST(LlmRerankFilterTest, LazyPullTiming) {
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  auto fixture = New<TranslationFixture>();
  auto* upstream = fixture.get();
  CandidateList candidates;
  auto filtered = filter.Apply(fixture, &candidates);
  ASSERT_TRUE(bool(filtered));

  // Construction must not pull anything.
  EXPECT_EQ(0, upstream->peek_count());
  EXPECT_EQ(0, upstream->next_count());
  EXPECT_FALSE(filtered->exhausted());

  // First Peek pulls exactly one candidate; repeated Peek pulls no more.
  ASSERT_TRUE(bool(filtered->Peek()));
  EXPECT_EQ("你好", filtered->Peek()->text());
  EXPECT_EQ(1, upstream->peek_count());
  EXPECT_EQ(1, upstream->next_count());
  filtered->Peek();
  EXPECT_EQ(1, upstream->peek_count());

  // After Next, the next Peek pulls exactly one more.
  filtered->Next();
  ASSERT_TRUE(bool(filtered->Peek()));
  EXPECT_EQ("尼好", filtered->Peek()->text());
  EXPECT_EQ(2, upstream->peek_count());
  EXPECT_EQ(2, upstream->next_count());
}

// Minimal main: unlike librime's rime_test_main.cc, this test needs no rime
// service (no engine, no dictionary, no deployed data directory).
int main(int argc, char** argv) {
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
