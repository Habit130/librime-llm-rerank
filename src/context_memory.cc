//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <rime/dict/user_db.h>

#include "context_memory.h"

namespace rime {

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
  if (!count || !db_ || !db_->loaded() || db_->disabled())
    return false;
  string value;
  if (!db_->Fetch(key, &value)) {
    string db_name;
    if (!db_->MetaFetch("/db_name", &db_name) || db_name != db_->name())
      return false;
    *count = 0;
    return true;
  }
  UserDbValue parsed;
  if (!parsed.Unpack(value))
    return false;
  *count = parsed.commits;
  return *count >= 0;
}

void ContextMemory::BumpCount(const string& key) {
  if (!db_)
    return;
  UserDbValue v;
  string value;
  if (db_->Fetch(key, &value))
    v.Unpack(value);
  v.commits += 1;
  db_->Update(key, v.Pack());
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
