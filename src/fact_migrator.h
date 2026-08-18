//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Fact schema migration (Habit130/squirrel#58): the only writer of fact
// schema evolution. Fact interpretation, the ordered step table, event-format
// projection and pre-commit validation live here in C++; Python only
// orchestrates quiesce, staging and the atomic replace through the
// fact_store_tool seam and never re-derives fact semantics.
//
// Contract (spec #43 "事实 schema 迁移"):
//   - Migrations are version-by-version, forward-only, executed inside ONE
//     SQLite transaction, and validated before commit (event/commit counts,
//     event and commit identities, HLC total order, foreign keys, schema
//     invariants).
//   - A migration that does not change the interpretation of existing events
//     preserves history_id and store_epoch. A migration that changes event,
//     HLC-order or other fact interpretation generates a new store_epoch
//     (history_id is preserved).
//   - Every old event is deterministically projected to the current canonical
//     event through its event_format_version. A missing field or an
//     unconvertible event blocks the migration and the build; the event is
//     never silently skipped.
//   - A store whose version is higher than the program supports, a missing
//     migration step, a validation failure, or an unconvertible event leaves
//     the original database unchanged, stops event recording and reports a
//     stable fault. Downgrades, best-effort in-place repair and creating an
//     empty database to paper over a failure are all refused.
//
// The migrator is callable on any standalone database file (a staging copy or
// an extracted backup member), never on the live locked root; the caller owns
// quiesce and publication. Because the whole ordered step chain runs inside
// one SQLite transaction, a crash at any point leaves the file at the
// complete old schema; only a COMMIT exposes the complete new schema.
#ifndef RIME_FACT_MIGRATOR_H_
#define RIME_FACT_MIGRATOR_H_

#include <sqlite3.h>

#include <cstdint>
#include <functional>
#include <string>

#include <rime/common.h>

namespace rime {

// The outcome of a migration attempt on one standalone database file.
enum class FactMigrationStatus {
  kOk,              // every ordered step ran; the file is at the head version
  kNoMigration,     // the file is already at the head version (no-op success)
  kUnsupportedVersion,  // file version higher than the program supports
  kMissingStep,     // a gap in the ordered step table (unknown predecessor)
  kProjectionFailed,    // an event field is missing or unconvertible
  kValidationFailed,    // pre-commit invariants failed
  kDbError,         // the file could not be opened or written
};

const char* FactMigrationStatusCode(FactMigrationStatus status);
const char* FactMigrationStatusMessage(FactMigrationStatus status);

// Result envelope for one migrated file.
struct FactMigrationResult {
  FactMigrationStatus status = FactMigrationStatus::kDbError;
  int from_version = 0;
  int to_version = 0;
  int64_t events_projected = 0;  // old-format rows projected to canonical
  int64_t events_preserved = 0;  // rows already in the canonical format
  string store_epoch;            // durable epoch of the migrated file
  string history_id;             // durable history of the migrated file
  bool epoch_changed = false;    // the chain regenerated store_epoch
};

// Schema disposition of one store version, derived only from the C++ step
// table (Python never re-derives it).
enum class SchemaDispositionCode {
  kCurrent,          // at the head version; no migration needed
  kNeedsMigration,   // below the head and a step chain covers it
  kUnsupported,      // higher than the program supports
  kMissingStep,      // below the head but no step covers it (gap)
};

SchemaDispositionCode DispositionFor(int version);
int CurrentSchemaHead();
bool IsMigratable(int version);

// Test seam (decision B): registers one ordered migration step
// `from_version` -> `to_version` (to must be from + 1). Re-registering the
// same from_version replaces the step; ResetTestMigrationSteps clears the
// whole table. Production ships no steps (head stays kFactSchemaVersion);
// the seam is how the supported-old -> head path, the epoch rules and the
// crash boundaries are exercised. The fact_store_tool binary activates the
// same seam when SQUIRREL_FACT_MIGRATE_TEST_STEPS is set, so the daemon
// operation tests can drive a real chain.
//
// `changes_interpretation` selects the epoch rule for the step: false keeps
// history_id AND store_epoch (interpretation preserved), true generates a
// new store_epoch (history_id preserved). `projection` selects the
// deterministic row projection: "stamp" rewrites every row to the canonical
// format without changing content, "recode" additionally canonicalizes
// preceding_text to the last 64 Unicode characters, and "dup_hlc" makes the
// rows share one HLC so pre-commit validation fails (rollback proof).
void RegisterTestMigrationStep(int from_version, int to_version,
                               bool changes_interpretation,
                               const char* projection);
void ResetTestMigrationSteps();

// Crash-injection seam for tests: called after each completed step, before
// validation and COMMIT. Returning false aborts like a crash (the whole
// transaction rolls back and the file stays at the old schema). Never used
// in production.
using MigrationStepHook = std::function<bool(int completed_steps)>;
void SetMigrationStepHookForTesting(MigrationStepHook hook);

// Migrates one standalone fact store database file in place to the current
// schema head. `db` must be a writable connection to a file that is NOT the
// live locked root (the caller owns staging). On success the file is at the
// head version and remains a valid single-file store; on any failure the
// file's facts are unchanged (the step chain runs inside one SQLite
// transaction that is rolled back). Version metadata is only rewritten after
// every step of the chain has applied.
FactMigrationResult MigrateFile(sqlite3* db);

}  // namespace rime

#endif  // RIME_FACT_MIGRATOR_H_
