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

int ContextMemory::FetchCount(const string& key) {
  if (!db_)
    return 0;
  string value;
  if (!db_->Fetch(key, &value))
    return 0;
  return UserDbValue(value).commits;
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

int ContextMemory::PairCount(const string& prev_word, const string& candidate) {
  return FetchCount(MakeKey("p " + prev_word, candidate));
}

int ContextMemory::TotalCount(const string& prev_word) {
  return FetchCount(MakeKey("t " + prev_word, "*"));
}

void ContextMemory::Record(const string& prev_word, const string& selected) {
  if (prev_word.empty() || selected.empty())
    return;
  BumpCount(MakeKey("r " + prev_word, selected));
  BumpCount(MakeKey("p " + prev_word, selected));
  BumpCount(MakeKey("t " + prev_word, "*"));
}

}  // namespace rime
