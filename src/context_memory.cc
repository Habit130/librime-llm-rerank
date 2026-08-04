//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <charconv>
#include <cmath>
#include <filesystem>
#include <functional>
#include <limits>
#include <locale>
#include <map>
#include <mutex>
#include <sstream>
#include <system_error>

#include <leveldb/db.h>
#include <leveldb/write_batch.h>
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

constexpr char kMetadataPrefix = '\x01';

string MetadataKey(const string& key) {
  return string(1, kMetadataPrefix) + key;
}

bool ParseInteger(const string& text, int* value) {
  if (!value || text.empty())
    return false;
  const char* first = text.data();
  const char* last = first + text.size();
  auto [parsed_end, error] = std::from_chars(first, last, *value);
  return error == std::errc() && parsed_end == last;
}

bool ParseTick(const string& text, TickCount* value) {
  if (!value || text.empty())
    return false;
  const char* first = text.data();
  const char* last = first + text.size();
  auto [parsed_end, error] = std::from_chars(first, last, *value);
  return error == std::errc() && parsed_end == last;
}

bool ParseDouble(const string& text, double* value) {
  if (!value || text.empty())
    return false;
  std::istringstream input(text);
  input.imbue(std::locale::classic());
  input >> std::noskipws >> *value;
  return input && input.peek() == std::char_traits<char>::eof() &&
         std::isfinite(*value);
}

// UserDbValue::Pack emits exactly "c=<int> d=<double> t=<uint64>". Validate
// that complete grammar instead of relying on its intentionally permissive
// migration parser, which ignores unknown and trailing tokens.
bool ParseUserDbValue(const string& value, UserDbValue* parsed) {
  if (!parsed || value.compare(0, 2, "c=") != 0)
    return false;
  const size_t commits_end = value.find(' ');
  if (commits_end == string::npos ||
      value.compare(commits_end, 3, " d=") != 0) {
    return false;
  }
  const size_t dee_start = commits_end + 3;
  const size_t dee_end = value.find(' ', dee_start);
  if (dee_end == string::npos || value.compare(dee_end, 3, " t=") != 0 ||
      value.find(' ', dee_end + 1) != string::npos) {
    return false;
  }
  UserDbValue result;
  if (!ParseInteger(value.substr(2, commits_end - 2), &result.commits) ||
      result.commits < 0 ||
      !ParseDouble(value.substr(dee_start, dee_end - dee_start), &result.dee) ||
      !ParseTick(value.substr(dee_end + 3), &result.tick)) {
    return false;
  }
  *parsed = result;
  return true;
}

class OwnedLevelDbBackend : public ContextDbBackend {
 public:
  explicit OwnedLevelDbBackend(leveldb::DB* db) : db_(db) {}

  leveldb::Status Fetch(const string& key, string* value) override {
    if (!value)
      return leveldb::Status::InvalidArgument("null value");
    return db_->Get(leveldb::ReadOptions(), key, value);
  }

  leveldb::Status Update(const string& key, const string& value) override {
    return db_->Put(leveldb::WriteOptions(), key, value);
  }

  leveldb::Status WriteMetadata(
      const vector<std::pair<string, string>>& entries) override {
    leveldb::WriteBatch batch;
    for (const auto& [key, value] : entries)
      batch.Put(key, value);
    return db_->Write(leveldb::WriteOptions(), &batch);
  }

 private:
  the<leveldb::DB> db_;
};

class LevelDbContextStore : public ContextStore {
 public:
  LevelDbContextStore(the<ContextDbBackend> backend,
                      ContextStoreIdentity identity)
      : backend_(std::move(backend)), identity_(std::move(identity)) {}

  bool InitializeAndValidate(bool initialize_new) {
    std::lock_guard<std::mutex> lock(mutex_);
    string db_name;
    string db_type;
    string user_id;
    ContextReadStatus name_status = ReadMetadata("/db_name", &db_name);
    ContextReadStatus type_status = ReadMetadata("/db_type", &db_type);
    ContextReadStatus user_status = ReadMetadata("/user_id", &user_id);
    if (initialize_new && name_status == ContextReadStatus::kMissing &&
        type_status == ContextReadStatus::kMissing &&
        user_status == ContextReadStatus::kMissing) {
      const leveldb::Status write_status = backend_->WriteMetadata({
          {MetadataKey("/db_name"), identity_.db_name},
          {MetadataKey("/db_type"), identity_.db_type},
          {MetadataKey("/user_id"), identity_.user_id},
          {MetadataKey("/rime_version"), RIME_VERSION},
      });
      if (!write_status.ok()) {
        healthy_ = false;
        return false;
      }
      name_status = ReadMetadata("/db_name", &db_name);
      type_status = ReadMetadata("/db_type", &db_type);
      user_status = ReadMetadata("/user_id", &user_id);
    }
    if (name_status != ContextReadStatus::kFound ||
        type_status != ContextReadStatus::kFound ||
        user_status != ContextReadStatus::kFound ||
        db_name != identity_.db_name || db_type != identity_.db_type ||
        user_id != identity_.user_id) {
      healthy_ = false;
      return false;
    }
    return true;
  }

  bool MatchesIdentity(const ContextStoreIdentity& identity) const {
    return identity.db_name == identity_.db_name &&
           identity.db_type == identity_.db_type &&
           identity.user_id == identity_.user_id;
  }

  bool FetchCount(const string& key, int* count) override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!healthy_ || !count)
      return false;
    string value;
    const ContextReadStatus status = Read(key, &value);
    if (status == ContextReadStatus::kMissing) {
      *count = 0;
      return true;
    }
    UserDbValue parsed;
    if (status != ContextReadStatus::kFound ||
        !ParseUserDbValue(value, &parsed)) {
      healthy_ = false;
      return false;
    }
    *count = parsed.commits;
    return true;
  }

  bool BumpCount(const string& key) override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!healthy_)
      return false;
    string value;
    const ContextReadStatus status = Read(key, &value);
    UserDbValue parsed;
    if (status == ContextReadStatus::kFound) {
      if (!ParseUserDbValue(value, &parsed)) {
        healthy_ = false;
        return false;
      }
    } else if (status != ContextReadStatus::kMissing) {
      healthy_ = false;
      return false;
    }
    if (parsed.commits == std::numeric_limits<int>::max()) {
      healthy_ = false;
      return false;
    }
    ++parsed.commits;
    if (!backend_->Update(key, parsed.Pack()).ok()) {
      healthy_ = false;
      return false;
    }
    return true;
  }

 private:
  ContextReadStatus Read(const string& key, string* value) {
    const ContextReadStatus status =
        ClassifyLevelDbReadStatus(backend_->Fetch(key, value));
    if (status == ContextReadStatus::kError)
      healthy_ = false;
    return status;
  }

  ContextReadStatus ReadMetadata(const string& key, string* value) {
    return Read(MetadataKey(key), value);
  }

  the<ContextDbBackend> backend_;
  ContextStoreIdentity identity_;
  std::mutex mutex_;
  bool healthy_ = true;
};

string NormalizePath(const path& file_path) {
  std::error_code error;
  path absolute = std::filesystem::absolute(file_path, error);
  if (error)
    return string();
  path normalized = std::filesystem::weakly_canonical(absolute, error);
  return error ? string() : normalized.string();
}

struct ContextStoreRegistryState {
  struct Entry {
    std::weak_ptr<LevelDbContextStore> weak_store;
    an<LevelDbContextStore> keep_alive;
    size_t owner_count = 0;
  };

  std::mutex mutex;
  std::map<string, Entry> stores;
};

class ContextStoreLease : public ContextStore {
 public:
  using Release =
      std::function<void(an<LevelDbContextStore>* released_store)>;

  ContextStoreLease(an<LevelDbContextStore> store, Release release)
      : store_(std::move(store)), release_(std::move(release)) {}

  ~ContextStoreLease() override { release_(&store_); }

  bool FetchCount(const string& key, int* count) override {
    return store_->FetchCount(key, count);
  }

  bool BumpCount(const string& key) override {
    return store_->BumpCount(key);
  }

 private:
  an<LevelDbContextStore> store_;
  Release release_;
};

class ContextStoreRegistry {
 public:
  ContextStoreRegistry()
      : state_(std::make_shared<ContextStoreRegistryState>()) {}

  static ContextStoreRegistry& instance() {
    static ContextStoreRegistry registry;
    return registry;
  }

  an<ContextStore> Open(const path& file_path,
                        const ContextStoreIdentity& identity) {
    const string normalized_path = NormalizePath(file_path);
    if (normalized_path.empty() || identity.db_name.empty() ||
        identity.db_type.empty() || identity.user_id.empty()) {
      return nullptr;
    }
    auto state = state_;
    std::lock_guard<std::mutex> lock(state->mutex);
    auto found = state->stores.find(normalized_path);
    if (found != state->stores.end()) {
      auto store = found->second.weak_store.lock();
      if (!store || !store->MatchesIdentity(identity))
        return nullptr;
      ++found->second.owner_count;
      return MakeLease(state, normalized_path, std::move(store));
    }

    std::error_code create_error;
    const bool initialize_new =
        std::filesystem::create_directory(normalized_path, create_error);
    if (create_error)
      return nullptr;
    leveldb::Options options;
    options.create_if_missing = initialize_new;
    leveldb::DB* db = nullptr;
    const leveldb::Status open_status =
        leveldb::DB::Open(options, normalized_path, &db);
    if (!open_status.ok())
      return nullptr;
    auto* raw_store = new LevelDbContextStore(
        make_unique<OwnedLevelDbBackend>(db), identity);
    if (!raw_store->InitializeAndValidate(initialize_new)) {
      delete raw_store;
      return nullptr;
    }
    auto store = an<LevelDbContextStore>(raw_store);
    state->stores[normalized_path] = {store, store, 1};
    return MakeLease(state, normalized_path, std::move(store));
  }

 private:
  static an<ContextStore> MakeLease(
      const std::shared_ptr<ContextStoreRegistryState>& state,
      const string& normalized_path,
      an<LevelDbContextStore> store) {
    return New<ContextStoreLease>(
        std::move(store),
        [state, normalized_path](an<LevelDbContextStore>* released_store) {
          std::lock_guard<std::mutex> release_lock(state->mutex);
          auto found = state->stores.find(normalized_path);
          if (found != state->stores.end() && found->second.owner_count > 0 &&
              --found->second.owner_count == 0) {
            found->second.keep_alive.reset();
            state->stores.erase(found);
          }
          // The last lease closes LevelDB while the registry lock still
          // excludes a replacement Open for the same normalized path.
          released_store->reset();
        });
  }

  std::shared_ptr<ContextStoreRegistryState> state_;
};

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

void ContextMemory::BumpCount(const string& key) {
  if (!store_)
    return;
  store_->BumpCount(key);
}

the<ContextMemory> ContextMemory::OpenLevelDb(
    const path& file_path,
    const ContextStoreIdentity& expected_identity) {
  auto store =
      ContextStoreRegistry::instance().Open(file_path, expected_identity);
  if (!store)
    return nullptr;
  return make_unique<ContextMemory>(store);
}

the<ContextMemory> ContextMemory::OpenBackendForTesting(
    the<ContextDbBackend> backend,
    const ContextStoreIdentity& expected_identity,
    bool initialize_new) {
  if (!backend || expected_identity.db_name.empty() ||
      expected_identity.db_type.empty() || expected_identity.user_id.empty()) {
    return nullptr;
  }
  auto store = New<LevelDbContextStore>(std::move(backend), expected_identity);
  if (!store->InitializeAndValidate(initialize_new))
    return nullptr;
  return make_unique<ContextMemory>(store);
}

bool ContextMemory::PairCount(const string& prev_word,
                              const string& candidate,
                              int* count) {
  return store_ && store_->FetchCount(MakeKey("p " + prev_word, candidate),
                                      count);
}

bool ContextMemory::TotalCount(const string& prev_word, int* count) {
  return store_ && store_->FetchCount(MakeKey("t " + prev_word, "*"), count);
}

void ContextMemory::Record(const string& prev_word, const string& selected) {
  if (prev_word.empty() || selected.empty())
    return;
  BumpCount(MakeKey("r " + prev_word, selected));
  BumpCount(MakeKey("p " + prev_word, selected));
  BumpCount(MakeKey("t " + prev_word, "*"));
}

}  // namespace rime
