//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_CONTEXT_MEMORY_H_
#define RIME_CONTEXT_MEMORY_H_

#include <leveldb/status.h>
#include <rime/common.h>

namespace rime {

enum class ContextReadStatus { kFound, kMissing, kError };

ContextReadStatus ClassifyLevelDbReadStatus(const leveldb::Status& status);

struct ContextStoreIdentity {
  string db_name;
  string db_type;
  string user_id;
};

// Raw status-preserving seam used by the production store and deterministic
// fault injection. The production implementation owns one leveldb::DB handle.
class ContextDbBackend {
 public:
  virtual ~ContextDbBackend() = default;
  virtual leveldb::Status Fetch(const string& key, string* value) = 0;
  virtual leveldb::Status Update(const string& key, const string& value) = 0;
  virtual leveldb::Status WriteMetadata(
      const vector<std::pair<string, string>>& entries) = 0;
};

// Count operations are synchronized by the shared production store so a
// read-modify-write cannot lose increments from concurrent sessions.
class ContextStore {
 public:
  virtual ~ContextStore() = default;
  virtual bool FetchCount(const string& key, int* count) = 0;
  virtual bool BumpCount(const string& key) = 0;
};

// Supplies the bigram counts behind the context-personalization term:
// n(prev_word, candidate) and n(prev_word). Injectable so rerank behavior can
// be asserted against in-memory fakes, with no userdb file on disk.
class ContextCounter {
 public:
  virtual ~ContextCounter() = default;
  // Times `candidate` was committed immediately after `prev_word`.
  virtual bool PairCount(const string& prev_word,
                         const string& candidate,
                         int* count) = 0;
  // Times anything was committed immediately after `prev_word`.
  virtual bool TotalCount(const string& prev_word, int* count) = 0;
};

// Store-backed counter and recording layer. Records keep the raw text of the
// preceding word and the selected candidate, decoupled from the scoring
// granularity so a future granularity can be re-derived from them; the
// pair/total counts are a derived index over those records. Values reuse the
// engine's user-db format so entries survive backup and sync.
class ContextMemory : public ContextCounter {
 public:
  explicit ContextMemory(an<ContextStore> store) : store_(store) {}

  static the<ContextMemory> OpenLevelDb(
      const path& file_path,
      const ContextStoreIdentity& expected_identity);
  static the<ContextMemory> OpenBackendForTesting(
      the<ContextDbBackend> backend,
      const ContextStoreIdentity& expected_identity,
      bool initialize_new);

  bool PairCount(const string& prev_word,
                 const string& candidate,
                 int* count) override;
  bool TotalCount(const string& prev_word, int* count) override;

  // Records one observation: immediately after `prev_word` the user committed
  // `selected`. A no-op when either is empty (no bigram to record).
  void Record(const string& prev_word, const string& selected);

 private:
  void BumpCount(const string& key);

  an<ContextStore> store_;
};

}  // namespace rime

#endif  // RIME_CONTEXT_MEMORY_H_
