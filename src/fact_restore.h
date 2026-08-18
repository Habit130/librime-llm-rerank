//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Whole-store restore epoch minting (Habit130/squirrel#56): the only writer
// of a NEW store_epoch during restore.
//
// Contract (spec #43 "整库恢复"):
//   - Restore always replaces the whole store: the backup's history_id,
//     event IDs, commit IDs, candidates, retractions and HLC state are
//     preserved verbatim; every successful restore mints a fresh random
//     store_epoch. Python never UPDATEs meta itself.
//   - The file must already be at the current schema head. Supported-old
//     backups are migrated on the staging copy by the migrate seam BEFORE
//     prepare-restore runs (the restore operation owns that ordering); a
//     file that is supported-old, too new or missing a step fails closed.
//   - The mint runs inside ONE SQLite transaction: a crash before COMMIT
//     leaves the file at the old epoch with all facts intact; only COMMIT
//     exposes the new epoch. After commit the file is re-validated and the
//     durable identity/counts are reported (never any private fact text).
//
// The function is callable on any standalone database file (a staging copy
// of an extracted backup member), never on the live locked root; the caller
// owns quiesce and publication.
#ifndef RIME_FACT_RESTORE_H_
#define RIME_FACT_RESTORE_H_

#include <sqlite3.h>

#include <cstdint>
#include <string>

#include <rime/common.h>

namespace rime {

enum class FactRestoreStatus {
  kOk,                   // new store_epoch minted, fsynced by the caller
  kNeedsMigration,       // supported-old file: migrate the staging copy first
  kUnsupportedVersion,   // schema or event format is too new / a step is missing
  kValidationFailed,     // integrity, identity or clock invariants failed
  kDbError,              // the file could not be opened or written
};

const char* FactRestoreStatusCode(FactRestoreStatus status);
const char* FactRestoreStatusMessage(FactRestoreStatus status);

// Result envelope for one prepared (epoch-minted) restore staging file.
struct FactRestoreResult {
  FactRestoreStatus status = FactRestoreStatus::kDbError;
  string history_id;              // preserved from the backup
  string store_epoch;             // the NEW minted epoch
  string previous_store_epoch;    // the backup's own epoch, now replaced
  int fact_schema_version = -1;
  int event_format_version = -1;
  int64_t hlc_physical_ms = 0;    // preserved clock state
  int64_t hlc_logical = 0;
  int64_t commit_count = 0;       // preserved fact counts
  int64_t event_count = 0;
  int64_t candidate_count = 0;
  int64_t retraction_count = 0;
};

// Mints a NEW random store_epoch in one standalone facts file (a staging
// copy of an extracted backup member), preserving history_id, every
// event/commit/candidate/retraction row, the HLC state and the schema.
// `db` must be a writable connection to a file that is NOT the live locked
// root. The file must be at the current schema head; otherwise the function
// fails closed with the corresponding status and the file is unchanged. On
// success the new epoch is durable inside one committed SQLite transaction
// and the file is re-validated before returning; the caller (the
// fact_store_tool command) fsyncs the file after the connection closes so
// the mint is durable on the staging medium before any publication.
FactRestoreResult PrepareRestoreFile(sqlite3* db);

}  // namespace rime

#endif  // RIME_FACT_RESTORE_H_
