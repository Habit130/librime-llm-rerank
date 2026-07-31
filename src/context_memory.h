//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_CONTEXT_MEMORY_H_
#define RIME_CONTEXT_MEMORY_H_

#include <rime/common.h>
#include <rime/dict/db.h>

namespace rime {

// Supplies the bigram counts behind the context-personalization term:
// n(prev_word, candidate) and n(prev_word). Injectable so rerank behavior can
// be asserted against in-memory fakes, with no userdb file on disk.
class ContextCounter {
 public:
  virtual ~ContextCounter() = default;
  // Times `candidate` was committed immediately after `prev_word`.
  virtual int PairCount(const string& prev_word, const string& candidate) = 0;
  // Times anything was committed immediately after `prev_word`.
  virtual int TotalCount(const string& prev_word) = 0;
};

// Db-backed counter and recording layer. Records keep the raw text of the
// preceding word and the selected candidate, decoupled from the scoring
// granularity so a future granularity can be re-derived from them; the
// pair/total counts are a derived index over those records. Values reuse the
// engine's user-db format so entries survive backup and sync.
class ContextMemory : public ContextCounter {
 public:
  explicit ContextMemory(an<Db> db) : db_(db) {}

  int PairCount(const string& prev_word, const string& candidate) override;
  int TotalCount(const string& prev_word) override;

  // Records one observation: immediately after `prev_word` the user committed
  // `selected`. A no-op when either is empty (no bigram to record).
  void Record(const string& prev_word, const string& selected);

 private:
  int FetchCount(const string& key);
  void BumpCount(const string& key);

  an<Db> db_;
};

}  // namespace rime

#endif  // RIME_CONTEXT_MEMORY_H_
