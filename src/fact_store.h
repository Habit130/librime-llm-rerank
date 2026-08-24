//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_FACT_STORE_H_
#define RIME_FACT_STORE_H_

#include <sqlite3.h>

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include <rime/common.h>

#include "fact_migrator.h"
#include "maintenance_lock.h"

namespace rime {

constexpr int kFactSchemaVersion = 1;
constexpr int kEventFormatVersion = 1;

// Stable, owner-only local fact store for selection events
// (facts.sqlite3 under ~/Library/Application Support/Squirrel/SemanticMemory).
// The plugin is the sole writer; the daemon reads it read-only. Every batch of
// selection events is persisted in one short BEGIN IMMEDIATE transaction that
// also advances the hybrid logical clock, so a composition's events, commit
// row and clock state are atomic.
//
// Fail-closed policy: the root directory and the database file must be real
// paths (not symlinks) owned by the current user with exact 0700 / 0600
// permissions. Any anomaly disables recording for the session and reports a
// stable fault code; the original files are never modified on failure.
class FactStore {
 public:
  enum class Status {
    kOk,
    kNoHome,            // HOME is not set; cannot locate the facts root
    kRootCreateFailed,  // root directory could not be created
    kRootNotDirectory,  // root exists but is not a directory
    kRootSymlink,       // root is a symlink
    kRootOwner,         // root is owned by another user
    kRootPermission,    // root mode is not exactly 0700
    kDbSymlink,         // facts.sqlite3 is a symlink
    kDbNotRegular,      // facts.sqlite3 is not a regular file
    kDbOwner,           // facts.sqlite3 is owned by another user
    kDbPermission,      // facts.sqlite3 mode is not exactly 0600
    kDbCorrupt,         // quick_check failed
    kDbUnsupportedVersion,  // fact schema is newer than this build supports
    kNeedsMigration,    // supported-old schema: recording must stop until the
                        // migrate operation runs (never migrated in Open())
    kDbClockInvalid,    // meta clock/history rows are missing or malformed
    kDbOpenFailed,      // sqlite could not open the database
    kDbWriteFailed,     // a persist transaction failed
    kMaintenanceLocked, // an exclusive maintenance lease is active
  };

  // How Open() classifies a supported-old schema. The recorder path (the
  // default) must never write: Open() returns kNeedsMigration and stops
  // recording. The maintenance path (fact_store_tool snapshot/verify) opens
  // supported-old stores read-write so the Online Backup API can snapshot
  // them for the migrate operation; fact content is never modified by that
  // open. Too-new or missing-step stores fail closed in BOTH modes.
  // kExclusive is the maintenance semantics WITHOUT acquiring the shared
  // maintenance lock: the caller already holds the exclusive maintenance
  // lease (a restore's backup-current snapshot runs inside the exclusive
  // replacement window), so a shared acquisition would self-deadlock.
  enum class OpenMode { kRecorder, kMaintenance, kExclusive };

  // One immutable selection event destined for the fact store. HLC fields and
  // commit_id are filled in by PersistBatch inside the transaction.
  struct Event {
    string event_id;
    string commit_id;
    string schema_id;
    string canonical_segment_input;
    size_t span_start = 0;
    size_t span_end = 0;
    string category;
    string preceding_text;
    bool competition_complete = false;
    string final_selection_text;
    string confirmation_source;
    int trigger_keycode = -1;  // -1 when no key event triggered the selection
    int display_rank = 0;
    int display_page = 0;
    string session_id;
    int session_seq = 0;
    int64_t utc_confirmed_at_ms = 0;
    int64_t hlc_physical_ms = 0;
    int64_t hlc_logical = 0;
    // Competition candidates in original merge order.
    vector<std::pair<int64_t, string>> candidates;
  };

  explicit FactStore(const path& root_dir);
  ~FactStore();

  FactStore(const FactStore&) = delete;
  FactStore& operator=(const FactStore&) = delete;

  // The spec-fixed facts root, derived from HOME.
  static path DefaultRootDir();

  // Verifies the root, opens (or creates) facts.sqlite3, applies WAL /
  // foreign keys / synchronous=FULL and the v1 schema. Returns kOk only when
  // recording may proceed; any other status leaves the store closed and the
  // files untouched. A supported-old schema returns kNeedsMigration in the
  // default recorder mode without writing (recording stops); the migrate
  // operation owns bringing the store to the current schema. The maintenance
  // mode is used by the fact_store_tool seam so it can snapshot and verify
  // supported-old stores.
  Status Open(OpenMode mode = OpenMode::kRecorder);
  bool is_open() const { return db_ != nullptr; }
  Status status() const { return status_; }

  // Persists a commit batch: one commit row, the events in the given order
  // (HLC assigned in that order), their candidate rows, and the advanced
  // clock, in a single BEGIN IMMEDIATE transaction. Returns false (and leaves
  // the database untouched) on any failure. When `commit_id` is non-null the
  // generated commit identifier is written back so the caller can later
  // retract the whole batch.
  bool PersistBatch(int64_t utc_committed_at_ms,
                    vector<Event>* events,
                    string* commit_id = nullptr,
                    const string* assigned_commit_id = nullptr);

  // Appends a retraction fact for `commit_id` in one short transaction,
  // advancing the HLC. Retraction is an independent append-only fact: the
  // original commit and event rows are never modified or deleted. Idempotent:
  // retracting an already-retracted (or unknown) commit is a no-op that
  // leaves the facts untouched and returns true. Returns false only when the
  // store cannot write (status_ set to a stable fault code).
  bool AppendRetraction(const string& commit_id,
                        int64_t utc_retracted_at_ms,
                        string* retraction_id = nullptr);

  // Deterministic projection of the active event set as of the given HLC
  // point: an event is active iff it was committed at or before the point and
  // no retraction of its commit took effect at or before the point. Future
  // retractions (HLC after the point) never backfill into an earlier replay.
  // Returns events in HLC order. All state is derived from the fact tables;
  // nothing is cached in memory.
  bool QueryActiveEventsAsOf(int64_t hlc_physical_ms,
                             int64_t hlc_logical,
                              vector<Event>* out);

  // Reads the current durable identity and clock while holding a shared lock.
  // Used by maintenance reopen checks and never exposes private event text.
  // `history_id` is optional; pass nullptr when only the epoch is needed.
  Status ReadStoreIdentity(int64_t* hlc_physical_ms,
                           int64_t* hlc_logical,
                           string* store_epoch,
                           string* history_id = nullptr);

  // Proves that every fact table is empty. Used by the clear operation to
  // verify a freshly staged store and to detect an already-empty store;
  // Python never re-derives this from its own copy of the schema.
  Status VerifyEmpty(bool* empty);

  // Merges all WAL pages into the main database and truncates the WAL,
  // preparing a staged store for single-file publication (clear staging).
  // Fails closed (facts untouched) when the checkpoint is busy or fails.
  Status CheckpointTruncate();

  // Deterministic, non-private summary of one fact store snapshot for the
  // backup manifest (spec #43 "完整备份"): durable identity, clock and event
  // HLC high-water marks, fact-table counts and the observed event-format
  // range (-1 for an empty store). Python never derives these from its own
  // copy of the fact schema.
  struct SnapshotStats {
    string history_id;
    string store_epoch;
    int fact_schema_version = -1;  // the store's durable schema version
    int event_format_version = -1;
    int64_t hlc_physical_ms = 0;
    int64_t hlc_logical = 0;
    int64_t event_hlc_physical_ms = -1;  // -1: no events in the snapshot
    int64_t event_hlc_logical = -1;
    int64_t commit_count = 0;
    int64_t event_count = 0;
    int64_t candidate_count = 0;
    int64_t retraction_count = 0;
    int event_format_min = -1;  // -1: empty store
    int event_format_max = -1;
  };

  // Creates a consistent snapshot of the open store with the SQLite Online
  // Backup API and writes it to `output_path` as a single regular owner-owned
  // 0600 file with no WAL/SHM dependency. `output_path` must not exist
  // (exclusive create). The snapshot corresponds to one consistent SQLite
  // read point: concurrent writers are not blocked and their commits appear
  // wholly or not at all. The snapshot is then re-opened and fully validated
  // (integrity_check, foreign-key check, schema/meta/identity invariants)
  // and its stats are reported in `stats`; the file is fsynced before the
  // function returns success. Fails closed: the store's own files are never
  // modified and no partial snapshot is reported as success.
  Status SnapshotTo(const path& output_path, SnapshotStats* stats);

  // Read-only validation and stats for one standalone fact store database
  // file (a backup container member or an extracted snapshot). Requires a
  // single complete non-WAL database file; rejects WAL-dependent files,
  // unsupported schema/event versions, missing or malformed meta, integrity
  // or foreign-key failures and impossible count/clock states. Does not
  // require a root directory structure or a maintenance lease.
  static Status InspectSnapshotFile(const path& db_path, SnapshotStats* stats);

  // Reads the durable identity, clock, fact counts and event HLC high-water
  // of the OPEN store into `stats` (maintenance semantics; never writes).
  // Used by the restore plan display through `fact_store_tool stats`;
  // Python never re-derives fact semantics.
  Status ReadStats(SnapshotStats* stats);

  // Stable code strings for diagnostics; never contains raw text.
  static const char* StatusCode(Status status);
  static const char* StatusMessage(Status status);

  // Test seam: install a SQLite progress handler on the open connection.
  // Production never calls this.
  void InstallProgressHandlerForTesting(int n_ops,
                                        int (*handler)(void*),
                                        void* ctx);

 private:
  Status VerifyRoot();
  Status VerifyDbFile();
  Status InitializeMeta();
  Status ValidateMeta(OpenMode mode);
  bool EnsureFileModes();

  path root_;
  sqlite3* db_ = nullptr;
  Status status_ = Status::kOk;
  int64_t clock_physical_ms_ = 0;
  int64_t clock_logical_ = 0;
  bool meta_initialized_ = false;
  MaintenanceLock maintenance_lock_;
};

// Test seam: invoked after InspectSnapshotFile opens its read-only handle,
// before validation. Production never sets this.
void SetInspectSnapshotHookForTesting(std::function<void(sqlite3*)> hook);

}  // namespace rime

#endif  // RIME_FACT_STORE_H_
