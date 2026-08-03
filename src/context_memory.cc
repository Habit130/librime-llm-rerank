//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <charconv>
#include <limits>

#include <leveldb/db.h>
#include <rime/dict/user_db.h>

#include "context_memory.h"

namespace rime {

ContextReadStatus ClassifyLevelDbReadStatus(const leveldb::Status& status) {
  if (status.ok())
    return ContextReadStatus::kFound;
  return status.IsNotFound() ? ContextReadStatus::kMissing
                             : ContextReadStatus::kError;
}

namespace {

class LevelDbContextStore : public ContextStore {
 public:
  explicit LevelDbContextStore(leveldb::DB* db) : db_(db) {}

  ContextReadStatus Fetch(const string& key, string* value) override {
    if (!value)
      return ContextReadStatus::kError;
    const leveldb::Status status = db_->Get(leveldb::ReadOptions(), key, value);
    return ClassifyLevelDbReadStatus(status);
  }

  bool Update(const string& key, const string& value) override {
    return db_->Put(leveldb::WriteOptions(), key, value).ok();
  }

 private:
  the<leveldb::DB> db_;
};

bool ParseCommitCount(const string& value, int* count) {
  if (!count)
    return false;
  bool found = false;
  int parsed_count = 0;
  size_t start = 0;
  while (start <= value.size()) {
    const size_t end = value.find(' ', start);
    const size_t length =
        end == string::npos ? value.size() - start : end - start;
    if (length >= 2 && value.compare(start, 2, "c=") == 0) {
      if (found || length == 2)
        return false;
      const char* first = value.data() + start + 2;
      const char* last = value.data() + start + length;
      int candidate_count;
      auto [parsed_end, error] = std::from_chars(first, last, candidate_count);
      if (error != std::errc() || parsed_end != last || candidate_count < 0)
        return false;
      parsed_count = candidate_count;
      found = true;
    }
    if (end == string::npos)
      break;
    start = end + 1;
  }
  if (!found)
    return false;
  *count = parsed_count;
  return true;
}

}  // namespace

// Keys must round-trip through the plain-userdb snapshot format, which splits a
// key on a single tab into two non-empty parts and forces a trailing space onto
// the first part on restore. Building keys as "<code> \t<phrase>" with the code
// already ending in a space makes that restore step idempotent, so counts keep
// the same key across backup and sync.
static string MakeKey(const string& code, const string& phrase) {
  string key = code;
  if (key.empty() || key.back() != ' ')
    key += ' ';
  key += '\t';
  key += phrase;
  return key;
}

bool ContextMemory::FetchCount(const string& key, int* count) {
  if (!count || !store_)
    return false;
  string value;
  const ContextReadStatus status = store_->Fetch(key, &value);
  if (status == ContextReadStatus::kMissing) {
    *count = 0;
    return true;
  }
  if (status != ContextReadStatus::kFound)
    return false;
  return ParseCommitCount(value, count);
}

void ContextMemory::BumpCount(const string& key) {
  if (!store_)
    return;
  UserDbValue v;
  string value;
  const ContextReadStatus status = store_->Fetch(key, &value);
  if (status == ContextReadStatus::kError)
    return;
  if (status == ContextReadStatus::kFound) {
    int count;
    if (!ParseCommitCount(value, &count) || !v.Unpack(value))
      return;
    v.commits = count;
  }
  if (v.commits == std::numeric_limits<int>::max())
    return;
  v.commits += 1;
  store_->Update(key, v.Pack());
}

the<ContextMemory> ContextMemory::OpenLevelDb(const path& file_path) {
  leveldb::Options options;
  options.create_if_missing = false;
  leveldb::DB* db = nullptr;
  const leveldb::Status status =
      leveldb::DB::Open(options, file_path.string(), &db);
  if (!status.ok())
    return nullptr;
  return make_unique<ContextMemory>(New<LevelDbContextStore>(db));
}

bool ContextMemory::PairCount(const string& prev_word,
                              const string& candidate,
                              int* count) {
  return FetchCount(MakeKey("p " + prev_word, candidate), count);
}

bool ContextMemory::TotalCount(const string& prev_word, int* count) {
  return FetchCount(MakeKey("t " + prev_word, "*"), count);
}

void ContextMemory::Record(const string& prev_word, const string& selected) {
  if (prev_word.empty() || selected.empty())
    return;
  BumpCount(MakeKey("r " + prev_word, selected));
  BumpCount(MakeKey("p " + prev_word, selected));
  BumpCount(MakeKey("t " + prev_word, "*"));
}

}  // namespace rime
