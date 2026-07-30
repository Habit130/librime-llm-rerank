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
    if (++cursor_ >= candies_.size())
      set_exhausted(true);
    return true;
  }

  an<Candidate> Peek() {
    if (exhausted())
      return nullptr;
    return candies_[cursor_];
  }

 private:
  vector<of<Candidate>> candies_;
  size_t cursor_;
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

// Minimal main: unlike librime's rime_test_main.cc, this test needs no rime
// service (no engine, no dictionary, no deployed data directory).
int main(int argc, char** argv) {
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
