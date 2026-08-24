//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_SQLITE_STEP_H_
#define RIME_SQLITE_STEP_H_

#include <sqlite3.h>

namespace rime {

// A row-producing statement completed with no remaining rows and no error.
// SQLITE_INTERRUPT, SQLITE_IOERR and every other terminal code fail closed.
inline bool SqliteIsDone(int step_rc) {
  return step_rc == SQLITE_DONE;
}

inline bool SqliteIsRowOrDone(int step_rc) {
  return step_rc == SQLITE_ROW || step_rc == SQLITE_DONE;
}

// Finalize `stmt` and succeed only if the last step was SQLITE_DONE and
// finalize itself succeeded.
inline bool SqliteFinishDone(sqlite3_stmt* stmt, int step_rc) {
  const int finalize_rc = sqlite3_finalize(stmt);
  return step_rc == SQLITE_DONE && finalize_rc == SQLITE_OK;
}

// Finalize `stmt` and succeed only if the last step was SQLITE_ROW or
// SQLITE_DONE (optional single-row queries) and finalize succeeded.
inline bool SqliteFinishRowOrDone(sqlite3_stmt* stmt, int step_rc) {
  const int finalize_rc = sqlite3_finalize(stmt);
  return SqliteIsRowOrDone(step_rc) && finalize_rc == SQLITE_OK;
}

}  // namespace rime

#endif  // RIME_SQLITE_STEP_H_
