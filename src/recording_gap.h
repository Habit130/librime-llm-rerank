//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_RECORDING_GAP_H_
#define RIME_RECORDING_GAP_H_

#include <cstdint>
#include <string>

#include <rime/common.h>

namespace rime {

// Persistent recording-gap record (spec "记录缺口" / "错误协议").
//
// A gap is a known missing slice of selection history: events that became
// valid but were not persisted because the maintenance buffer overflowed,
// the store failed, or the process exited with buffered batches. Gaps must
// be explicitly diagnosable and must never be confused with "no selections
// happened". The record lives at `<facts root>/recording_gap.json` with
// mode 0600 and is written atomically (temp file, fsync, rename, directory
// fsync).
//
// Privacy contract: the record carries only stable reason codes, batch and
// event counts, byte counts and timestamps — never 上文, candidate text,
// canonical input, or embeddings. The `store_epoch` field names the fact
// store instance the gap refers to when it is provable (empty otherwise).
struct RecordingGapRecord {
  static constexpr int kGapVersion = 1;

  string reason;              // stable code, see coordinator reason strings
  int64_t dropped_batches = 0;
  int64_t dropped_events = 0;
  int64_t buffer_bytes = 0;   // queue byte size that caused the overflow
  int64_t first_occurred_at_ms = 0;
  int64_t last_occurred_at_ms = 0;
  string store_epoch;         // empty when not provable

  // Writes the record atomically under the facts root with mode 0600.
  // Returns true on success; a failure is silent (the caller reports the
  // gap through the in-memory session properties instead).
  bool Write(const path& root_dir) const;

  // Reads an existing record; returns false when the file is missing or
  // malformed (the caller then treats the gap state as unknown).
  static bool Read(const path& root_dir, RecordingGapRecord* out);
};

}  // namespace rime

#endif  // RIME_RECORDING_GAP_H_
