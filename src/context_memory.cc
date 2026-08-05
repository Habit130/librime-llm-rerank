//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <cmath>
#include <filesystem>
#include <functional>
#include <limits>
#include <locale>
#include <map>
#include <mutex>
#include <optional>
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

bool Consume(std::istream* input, const string& expected) {
  if (!input)
    return false;
  for (char expected_character : expected) {
    char actual_character;
    if (!input->get(actual_character) || actual_character != expected_character)
      return false;
  }
  return true;
}

// Match the exact current-locale representation emitted by UserDbValue::Pack.
// Its migration parser is intentionally permissive, so a Pack round trip is
// still required to reject unknown, reordered, or trailing fields.
bool ParseUserDbValue(const string& value, UserDbValue* parsed) {
  if (!parsed)
    return false;
  std::istringstream input(value);
  input.imbue(std::locale());
  input >> std::noskipws;
  UserDbValue result;
  if (!Consume(&input, "c=") || !(input >> result.commits) ||
      !Consume(&input, " d=") || !(input >> result.dee) ||
      !Consume(&input, " t=") || !(input >> result.tick) ||
      input.rdbuf()->sgetc() != std::char_traits<char>::eof() ||
      !std::isfinite(result.dee) || result.Pack() != value) {
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

  leveldb::Status IsEmpty(bool* empty) override {
    if (!empty)
      return leveldb::Status::InvalidArgument("null empty");
    std::unique_ptr<leveldb::Iterator> iterator(
        db_->NewIterator(leveldb::ReadOptions()));
    iterator->SeekToFirst();
    const bool has_any_key = iterator->Valid();
    const leveldb::Status status = iterator->status();
    if (!status.ok())
      return status;
    *empty = !has_any_key;
    return leveldb::Status::OK();
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
    if (name_status == ContextReadStatus::kMissing &&
        type_status == ContextReadStatus::kMissing &&
        user_status == ContextReadStatus::kMissing) {
      // Either a brand-new database or a first-initialization residue left by
      // a process that died after LevelDB created its internal files but
      // before the identity metadata batch landed. The only provably safe
      // recovery condition is a database that contains no keys at all: any
      // key - metadata or business data, ours or unknown - means the
      // directory is not an empty first-init residue and must not be claimed.
      if (!initialize_new) {
        bool empty = false;
        const leveldb::Status scan_status = backend_->IsEmpty(&empty);
        if (!scan_status.ok() || !empty) {
          healthy_ = false;
          return false;
        }
      }
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
    *count = (std::max)(0, parsed.commits);
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
    if (parsed.commits < 0)
      parsed.commits = 0;
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

std::optional<path> UserDbPath(const path& user_data_dir,
                               const string& db_name) {
  const path name(db_name);
  if (user_data_dir.empty() || db_name.empty() || name.has_root_path() ||
      name.has_parent_path() || name.filename() != name || name == "." ||
      name == ".." || db_name.find('\0') != string::npos) {
    return std::nullopt;
  }
  std::error_code error;
  const path root = std::filesystem::weakly_canonical(
      std::filesystem::absolute(user_data_dir, error), error);
  if (error || !std::filesystem::is_directory(root, error) || error)
    return std::nullopt;
  const path requested = root / (db_name + ".userdb");
  const auto status = std::filesystem::symlink_status(requested, error);
  if (error && error != std::errc::no_such_file_or_directory)
    return std::nullopt;
  if (!error && std::filesystem::is_symlink(status))
    return std::nullopt;
  error.clear();
  const path resolved = std::filesystem::weakly_canonical(requested, error);
  if (error || resolved.parent_path() != root)
    return std::nullopt;
  return resolved;
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
  using Release = std::function<void(an<LevelDbContextStore>* released_store)>;

  ContextStoreLease(an<LevelDbContextStore> store, Release release)
      : store_(std::move(store)), release_(std::move(release)) {}

  ~ContextStoreLease() override { release_(&store_); }

  bool FetchCount(const string& key, int* count) override {
    return store_->FetchCount(key, count);
  }

  bool BumpCount(const string& key) override { return store_->BumpCount(key); }

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
    auto* raw_store =
        new LevelDbContextStore(make_unique<OwnedLevelDbBackend>(db), identity);
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

the<ContextMemory> ContextMemory::OpenUserLevelDb(
    const path& user_data_dir,
    const string& db_name,
    const ContextStoreIdentity& expected_identity) {
  if (expected_identity.db_name != db_name)
    return nullptr;
  auto file_path = UserDbPath(user_data_dir, db_name);
  return file_path ? OpenLevelDb(*file_path, expected_identity) : nullptr;
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
  return store_ &&
         store_->FetchCount(MakeKey("p " + prev_word, candidate), count);
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
