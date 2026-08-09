//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_FACT_STORE_H_
#define RIME_FACT_STORE_H_

#include <sqlite3.h>

#include <cstdint>
#include <string>
#include <vector>

#include <rime/common.h>

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
// Connection lifecycle (spec "维护锁与 quiesce"): there is NO long-lived
// SQLite connection. Every write transaction opens a fresh connection, holds
// the shared maintenance lock (`maintenance.lock`, see MaintenanceLock) for
// the whole transaction, closes the connection, and only then releases the
// lock. An exclusive lock holder can therefore replace the fact store
// without ever racing an in-flight write, and a crashed writer releases the
// lock automatically. A write attempted while the exclusive lock is held
// returns `kMaintenanceLocked` immediately (never blocks): the caller
// buffers the commit batch instead of waiting.
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
    kDbUnsupportedVersion,  // fact schema or event format version mismatch
    kDbClockInvalid,    // meta clock/history rows are missing or malformed
    kDbOpenFailed,      // sqlite could not open the database
    kDbWriteFailed,     // a persist transaction failed
    kMaintenanceLocked,  // exclusive maintenance lock held; write must buffer
    kLockSymlink,       // maintenance.lock is a symlink
    kLockNotRegular,    // maintenance.lock is not a regular file
    kLockOwner,         // maintenance.lock is owned by another user
    kLockPermission,    // maintenance.lock mode is not exactly 0600
    kLockOpenFailed,    // maintenance.lock could not be opened
    kLockTimeout,       // exclusive acquisition exceeded its deadline
  };

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

  // Verifies the root and database, applies WAL / foreign keys /
  // synchronous=FULL and the v1 schema, validates or initializes the meta
  // clock, and closes the connection again. Returns kOk only when recording
  // may proceed; any other status leaves the files untouched. This is a
  // readiness probe, not a long-lived connection.
  Status Open();
  bool is_open() const { return status_ == Status::kOk; }
  Status status() const { return status_; }

  // Persists a commit batch: one commit row, the events in the given order
  // (HLC assigned in that order), their candidate rows, and the advanced
  // clock, in a single BEGIN IMMEDIATE transaction under the shared
  // maintenance lock. When `commit_id` is non-empty it is used as the commit
  // identity (a batch that was buffered during maintenance already owns one);
  // otherwise a fresh identifier is generated and written back. Returns
  // kOk, kMaintenanceLocked (exclusive lock held; nothing written), or a
  // stable fault status (transaction rolled back, files untouched).
  Status PersistBatch(int64_t utc_committed_at_ms,
                      vector<Event>* events,
                      string* commit_id = nullptr);

  // Appends a retraction fact for `commit_id` in one short transaction under
  // the shared maintenance lock, advancing the HLC. Retraction is an
  // independent append-only fact: the original commit and event rows are
  // never modified or deleted. Idempotent: retracting an already-retracted
  // (or unknown) commit is a no-op that leaves the facts untouched and
  // returns kOk. Returns kMaintenanceLocked or a stable fault status on
  // failure.
  Status AppendRetraction(const string& commit_id,
                          int64_t utc_retracted_at_ms,
                          string* retraction_id = nullptr);

  // Deterministic projection of the active event set as of the given HLC
  // point: an event is active iff it was committed at or before the point and
  // no retraction of its commit took effect at or before the point. Future
  // retractions (HLC after the point) never backfill into an earlier replay.
  // Returns events in HLC order. All state is derived from the fact tables;
  // nothing is cached in memory. Runs on its own connection under the shared
  // maintenance lock.
  bool QueryActiveEventsAsOf(int64_t hlc_physical_ms,
                             int64_t hlc_logical,
                             vector<Event>* out);

  // Reads the current store identity (HLC clock and store_epoch) from meta
  // on a fresh connection under the shared maintenance lock. Used to stamp
  // persistent recording-gap records with the epoch they describe. Returns
  // kOk with the values, or a stable status when the store cannot be read.
  Status ReadStoreIdentity(int64_t* hlc_physical_ms,
                           int64_t* hlc_logical,
                           string* store_epoch);

  // Deterministic store faults (owner / permission / symlink / corruption /
  // unsupported version / invalid clock): recording must stop and be
  // reported, never auto-relaxed. Transient conditions (lock held, open or
  // write failures) instead form a recording gap and are retried.
  static bool IsFatalStatus(Status status);

  // Stable code strings for diagnostics; never contains raw text.
  static const char* StatusCode(Status status);
  static const char* StatusMessage(Status status);

  Status VerifyRoot();
  Status VerifyDbFile();

 private:
  path root_;
  Status status_ = Status::kOk;
};

}  // namespace rime

#endif  // RIME_FACT_STORE_H_
