#!/usr/bin/env python3
"""Persistent exact delta state machine (Habit130/squirrel#63).

The online semantic path of the second-phase spec (#43 "持久 delta 与立即可见
性"): on top of one verified immutable base generation (#62), a single
catch-up worker absorbs newly committed selection events and whole-commit
retractions from the fact store in fact-transaction order, durably advances
one ``delta.sqlite3`` checkpoint, and atomically publishes a new read-only
query snapshot.  Every evidence query first reads the facts' identity
(``store_epoch`` + max change HLC), then succeeds only once the published
snapshot has caught up to that watermark; a snapshot behind the watermark is
a true fault (``not_caught_up``), never a stale success.

Checkpoint layout (spec clause "持久 delta 与立即可见性"):

    <derived_root>/delta.sqlite3     single WAL, synchronous=FULL checkpoint

    meta             delta_schema_version, base_generation_id, store_epoch,
                     representation_id, vector_dimension, base HLC (H0),
                     consumed change HLC, change_seq, optional blocked record
    delta_events     one row per absorbed selection event (never the raw
                     preceding_text -- facts stay the only raw-text source)
    retractions      one row per absorbed whole-commit retraction tombstone

The checkpoint is a fast-recovery cache, never a second fact source: it is
verified against the facts on load (identity, row sanity, and the event-set
equality of the projected active set), and any doubt drops it and replays
from the base watermark ``H0`` (SCN-63-6).  A restart or lost notification
resumes from the checkpoint's consumed HLC and catches up from facts
(SCN-63-5); a changed ``store_epoch`` discards every piece of derived state
(generation + delta + snapshot) and rebuilds from facts (SCN-63-4).

Deterministic replay equivalence (AC63-7): after any of restart / lost
notification / checkpoint corruption / epoch change, a replayed state serves
evidence-level-identical results -- for every query, the per-candidate ``s``
array and the query point equal the pre-failure snapshot's.  File-level
identity is never promised; the checkpoint is derived state.

Concurrency (SCN-63-8): the worker thread is the only writer of the delta
checkpoint and the only publisher of snapshots; requests never write.  A
catch-up batch embeds vectors first, then advances rows + tombstones +
consumed HLC + change sequence inside ONE SQLite transaction; only after that
transaction commits is a new read-only snapshot published (AC63-3/4).  If
publishing fails after a commit, the next cycle resumes from the committed
checkpoint watermark (never re-embeds) and re-publishes.  A catch-up that
cannot finish within a request's deadline fails that request with
``not_caught_up`` (AC63-6); the worker keeps working for the next request.
"""

import json
import math
import os
import sqlite3
import struct
import threading
import time
from typing import (Any, Dict, Optional, Tuple)

from evidence import EvidenceError, RepresentationProvider
from generation import (BuildBlockedError, BuildError, Generation,
                        GenerationRejected, build_generation, open_generation)
from oracle import (FactReader, OracleError, StoredEvent)

DELTA_SCHEMA_VERSION = "delta-schema-v1"
DELTA_FILENAME = "delta.sqlite3"
# Spec: delta 使用 WAL 和 synchronous=FULL.
DELTA_JOURNAL_MODE = "wal"
DELTA_SYNC_MODE = "full"
# Same standard the generation builder applies to its vectors (unit norm
# within FP32 rounding tolerance); a dirty vector blocks the batch.
UNIT_NORM_TOLERANCE = 1e-3
# Defaults; configurable via config keys (catch_up_deadline_ms,
# poll_interval_ms).
DEFAULT_CATCH_UP_DEADLINE_S = 5.0
DEFAULT_POLL_INTERVAL_S = 0.5

_META_KEYS = (
    "delta_schema_version",
    "base_generation_id",
    "store_epoch",
    "representation_id",
    "vector_dimension",
    "base_hlc_physical_ms",
    "base_hlc_logical",
    "consumed_hlc_physical_ms",
    "consumed_hlc_logical",
    "change_seq",
)

_DELTA_DDL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delta_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL,
  schema_id TEXT NOT NULL,
  canonical_segment_input TEXT NOT NULL,
  category TEXT NOT NULL,
  final_selection_text TEXT NOT NULL,
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  vector BLOB NOT NULL,
  change_seq INTEGER NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_delta_events_hlc
  ON delta_events(hlc_physical_ms, hlc_logical);
CREATE TABLE IF NOT EXISTS retractions (
  commit_id TEXT PRIMARY KEY NOT NULL,
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  change_seq INTEGER NOT NULL UNIQUE
);
"""

# ---------------------------------------------------------------------------
# Faults
# ---------------------------------------------------------------------------

class DeltaError(Exception):
    """A true fault of the delta path (never an empty-memory result)."""


class DeltaRejected(DeltaError):
    """The delta checkpoint exists but cannot be trusted.

    Carries a ``reason`` naming the first failing check (identity, rows,
    projection).  The machine drops the checkpoint and replays from the base
    watermark -- the spec's explicit recovery for a damaged checkpoint.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class DeltaBlocked(DeltaError):
    """A deterministic fault blocked catch-up; the blocking events are named.

    Nothing is silently skipped: the batch that contains a blocking event
    stays unconsumed, requests fail with ``representation_fault``, and the
    block is recorded in the checkpoint until ``retry()`` or a restart
    re-attempts it (spec: 确定性失败保持 blocked).
    """

    def __init__(self, message, blocked_events, phase="vector"):
        super().__init__(message)
        self.message = message
        self.blocked_events = tuple(blocked_events)
        self.phase = phase


# ---------------------------------------------------------------------------
# Fact-store read helpers (read-only, mirror the oracle's as-of semantics)
# ---------------------------------------------------------------------------

def _open_facts_ro(facts_root):
    db_path = os.path.join(facts_root, "facts.sqlite3")
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=0)
    conn.row_factory = sqlite3.Row
    return conn


def read_facts_identity(facts_root):
    """(store_epoch, (physical, logical)) from the fact store, or None.

    None means the fact store does not exist yet (a machine configured over a
    not-yet-created store idles and builds once facts appear).  A malformed
    or incomplete identity is a true fault.
    """
    db_path = os.path.join(facts_root, "facts.sqlite3")
    if not os.path.isfile(db_path):
        return None
    conn = None
    try:
        conn = _open_facts_ro(facts_root)
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error as error:
        raise DeltaError("fact store read failed: %s" % error)
    finally:
        if conn is not None:
            conn.close()
    store_epoch = rows.get("store_epoch")
    try:
        physical = int(rows.get("hlc_physical_ms", "-1"))
        logical = int(rows.get("hlc_logical", "-1"))
    except (TypeError, ValueError) as error:
        raise DeltaError("fact store meta clock is malformed") from error
    if not store_epoch or physical < 0 or logical < 0:
        raise DeltaError("fact store identity is incomplete")
    return store_epoch, (physical, logical)


def _read_fact_changes(facts_root, lower, upper):
    """All changes with HLC in (lower, upper], in fact order.

    Returns (events, retractions): events sorted by (hlc, event_id),
    retractions by (hlc, commit_id) -- the fact store's total order, so a
    commit's events always precede a retraction of that commit.  The read
    runs inside one read-only transaction whose identity is re-checked
    before it commits.
    """
    conn = None
    try:
        conn = _open_facts_ro(facts_root)
        conn.execute("BEGIN")
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        store_epoch = rows.get("store_epoch")
        try:
            physical = int(rows.get("hlc_physical_ms", "-1"))
            logical = int(rows.get("hlc_logical", "-1"))
        except (TypeError, ValueError) as error:
            raise DeltaError("fact store meta clock is malformed") from error
        if not store_epoch or physical < 0 or logical < 0:
            raise DeltaError("fact store identity is incomplete")
        upper_point = upper if upper is not None else (physical, logical)
        if upper_point > (physical, logical):
            raise DeltaError("change read exceeds the fact store clock")
        low_p, low_l = lower
        up_p, up_l = upper_point
        event_rows = conn.execute(
            "SELECT e.event_id, e.commit_id, e.schema_id,"
            " e.canonical_segment_input, e.category,"
            " e.final_selection_text, e.preceding_text,"
            " e.hlc_physical_ms, e.hlc_logical"
            " FROM selection_events e"
            " WHERE (e.hlc_physical_ms > ?1"
            "        OR (e.hlc_physical_ms = ?1 AND e.hlc_logical > ?2))"
            " AND (e.hlc_physical_ms < ?3"
            "      OR (e.hlc_physical_ms = ?3 AND e.hlc_logical <= ?4))"
            " ORDER BY e.hlc_physical_ms, e.hlc_logical, e.event_id;",
            (low_p, low_l, up_p, up_l)).fetchall()
        retraction_rows = conn.execute(
            "SELECT commit_id, hlc_physical_ms, hlc_logical"
            " FROM retractions"
            " WHERE (hlc_physical_ms > ?1"
            "        OR (hlc_physical_ms = ?1 AND hlc_logical > ?2))"
            " AND (hlc_physical_ms < ?3"
            "      OR (hlc_physical_ms = ?3 AND hlc_logical <= ?4))"
            " ORDER BY hlc_physical_ms, hlc_logical, commit_id;",
            (low_p, low_l, up_p, up_l)).fetchall()
        after = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        after_epoch = after.get("store_epoch")
        try:
            after_physical = int(after.get("hlc_physical_ms", "-1"))
            after_logical = int(after.get("hlc_logical", "-1"))
        except (TypeError, ValueError) as error:
            raise DeltaError("fact store meta clock is malformed") from error
        conn.execute("COMMIT")
    except sqlite3.Error as error:
        raise DeltaError("fact store read failed: %s" % error)
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    if (after_epoch != store_epoch
            or (after_physical, after_logical) != (physical, logical)):
        raise DeltaError("fact store identity changed during the read")
    events = []
    for row in event_rows:
        preceding = row["preceding_text"]
        events.append(StoredEvent(
            event_id=row["event_id"],
            commit_id=row["commit_id"],
            schema_id=row["schema_id"],
            canonical_segment_input=row["canonical_segment_input"],
            category=row["category"],
            final_selection_text=row["final_selection_text"],
            hlc=(row["hlc_physical_ms"], row["hlc_logical"]),
            preceding_text=preceding if preceding is not None else ""))
    retractions = [
        (row["commit_id"], (row["hlc_physical_ms"], row["hlc_logical"]))
        for row in retraction_rows
    ]
    return events, retractions


def _read_base_commit_ids(facts_root, upper):
    """event_id -> commit_id for every event committed at-or-before ``upper``.

    Facts are immutable within one ``store_epoch``, so this mapping is stable
    for the lifetime of a generation and is what lets the projection apply
    delta tombstones to base-generation rows (whose metadata does not carry
    commit ids).
    """
    conn = None
    try:
        conn = _open_facts_ro(facts_root)
        rows = conn.execute(
            "SELECT event_id, commit_id FROM selection_events"
            " WHERE (hlc_physical_ms < ?1"
            "        OR (hlc_physical_ms = ?1 AND hlc_logical <= ?2));",
            (upper[0], upper[1])).fetchall()
        return {row["event_id"]: row["commit_id"] for row in rows}
    except sqlite3.Error as error:
        raise DeltaError("fact store read failed: %s" % error)
    finally:
        if conn is not None:
            conn.close()


def _facts_active_event_ids(facts_root, as_of):
    reader = None
    try:
        reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
        return {event.event_id for event in reader.read_active_events(as_of)}
    except OracleError as error:
        raise DeltaError("fact store read failed: %s" % error)
    finally:
        if reader is not None:
            reader.close()


# ---------------------------------------------------------------------------
# The read-only query snapshot
# ---------------------------------------------------------------------------

class DeltaSnapshot:
    """One immutable, fully caught-up query snapshot.

    The snapshot is the materialized 活动集合 + 同键年龄序列 of the spec:
    the ordered active-event list and the per-event vector lookup.  It is
    built only from committed delta state and the verified base generation,
    and it is published atomically; readers may keep using an old snapshot
    while a newer one is published (immutability by construction).
    """

    def __init__(self, store_epoch, base_generation_id, representation_id,
                 vector_dimension, consumed, events, row_source, generation,
                 delta_vectors, change_seq):
        self._store_epoch = store_epoch
        self._base_generation_id = base_generation_id
        self._representation_id = representation_id
        self._vector_dimension = vector_dimension
        self._consumed = consumed
        self._events = tuple(events)
        self._row_source = dict(row_source)
        self._generation = generation
        self._delta_vectors = dict(delta_vectors)
        self._change_seq = change_seq

    @property
    def store_epoch(self):
        return self._store_epoch

    @property
    def base_generation_id(self):
        return self._base_generation_id

    @property
    def representation_id(self):
        return self._representation_id

    @property
    def vector_dimension(self):
        return self._vector_dimension

    @property
    def consumed(self):
        return self._consumed

    @property
    def change_seq(self):
        return self._change_seq

    @property
    def active_events(self):
        return tuple(self._events)

    def event_ids(self):
        return [event.event_id for event in self._events]

    def vector_for(self, event_id):
        source = self._row_source.get(event_id)
        if source == "base":
            return self._generation.event_vector(event_id)
        if source == "delta":
            vector = self._delta_vectors.get(event_id)
            if vector is None:
                raise DeltaError("no delta vector for event %s" % event_id)
            return vector
        raise DeltaError("no vector for unknown event %s" % event_id)

    def reader(self):
        """A reader implementing the oracle's read protocol."""
        return DeltaSnapshotReader(self)

    def identity_signature(self):
        """Short stable signature for assertions (tests and health)."""
        return (self._store_epoch, self._consumed, self._change_seq,
                self._base_generation_id)


class DeltaSnapshotReader:
    """Oracle-compatible read-only view over one snapshot.

    ``read_active_events`` returns the snapshot's ordered active event list
    regardless of the requested as-of point: the snapshot is fully caught up
    by construction, and the query gate has already proven its watermark
    against the facts before the snapshot is ever served.
    """

    def __init__(self, snapshot):
        self._snapshot = snapshot

    def read_active_events(self, as_of=None):
        del as_of  # snapshot is a frozen, already-caught-up projection
        return list(self._snapshot.active_events)

    def default_as_of(self):
        return self._snapshot.consumed

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Checkpoint I/O (single writer: the worker thread)
# ---------------------------------------------------------------------------

# Locking behavior of checkpoint connections (docs/delta-state-machine.md
# "Connection classes"): writer and maintenance connections wait up to
# WRITE_BUSY_TIMEOUT_S for a concurrent lock holder -- the worker's own
# transactions are milliseconds, so a maintenance path that fails instead
# of waiting (e.g. retry() racing the worker's write) is a spurious fault.
# Read/verify connections keep sqlite's fail-fast timeout=0: verification
# runs before the worker starts, and a verification that would block is a
# genuine problem -- the checkpoint is dropped and replayed anyway.
WRITE_BUSY_TIMEOUT_S = 5.0
READ_BUSY_TIMEOUT_S = 0.0


def _connect_delta(path, busy_timeout=READ_BUSY_TIMEOUT_S):
    """Open one checkpoint connection.

    ``synchronous=FULL`` is connection-local (spec durability) and is
    applied on every connection -- a checkpoint connection can never
    silently run with weaker durability.  ``journal_mode=WAL`` is durable
    in the database header and is set exactly once, at checkpoint creation
    (``_create_delta_schema``); later connections only verify it (via
    ``_verify_delta_pragmas``).  Re-setting journal_mode on every
    connection would acquire the write lock each time and make maintenance
    connections collide with the worker's write lock (the repaired AC-63-v1
    defect).
    """
    try:
        conn = sqlite3.connect(path, timeout=busy_timeout)
    except sqlite3.Error as error:
        raise DeltaRejected("cannot open delta checkpoint: %s" % error)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA synchronous=%s;" % DELTA_SYNC_MODE)
    except sqlite3.Error as error:
        raise DeltaRejected("cannot set delta synchronous pragma: %s"
                            % error)
    return conn


def _verify_delta_pragmas(conn):
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
    except sqlite3.Error as error:
        raise DeltaRejected("cannot read delta pragmas: %s" % error)
    if mode != DELTA_JOURNAL_MODE:
        raise DeltaRejected("delta journal mode is %r, need %r"
                            % (mode, DELTA_JOURNAL_MODE))
    if int(sync) != 2:  # SQLITE_SYNCHRONOUS_FULL, applied per connection
        raise DeltaRejected("delta synchronous is %r, need full" % sync)


def _create_delta_schema(path):
    """Create the checkpoint file + schema (idempotent, owner-only).

    This is the only place ``journal_mode=WAL`` is set: the mode is durable
    in the database header, and re-setting it on later connections would
    require the write lock for no benefit.  ``synchronous=FULL`` is applied
    here as well (``_connect_delta`` also applies it to every connection).
    """
    conn = None
    try:
        conn = _connect_delta(path, busy_timeout=WRITE_BUSY_TIMEOUT_S)
        has_meta = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master"
            " WHERE type = 'table' AND name = 'meta';").fetchone()[0]
        if not has_meta:
            conn.execute("PRAGMA journal_mode=%s;" % DELTA_JOURNAL_MODE)
            conn.executescript(_DELTA_DDL)
        conn.commit()
        os.chmod(path, 0o600)
        for name in (path + "-wal", path + "-shm"):
            try:
                os.chmod(name, 0o600)
            except OSError:
                pass
    except sqlite3.Error as error:
        raise DeltaError("cannot create delta checkpoint: %s" % error)
    finally:
        if conn is not None:
            conn.close()


def _read_delta_meta(conn):
    rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    return rows


def _write_delta_meta(conn, values):
    for key, value in values.items():
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
            (key, str(value)))


def _pack_vector(vector):
    """Row-major little-endian FP32 BLOB (the delta's vector format)."""
    return struct.pack("<%df" % len(vector), *[float(v) for v in vector])


def _unpack_vector(blob):
    dimension = len(blob) // 4
    return tuple(struct.unpack("<%df" % dimension, bytes(blob)))


def _validate_vector_blob(blob, dimension):
    """Dimension, finiteness and unit norm of one stored FP32 vector."""
    if not isinstance(blob, (bytes, bytearray)):
        return "vector must be a BLOB"
    if len(blob) != dimension * 4:
        return "vector BLOB size %d does not match dimension %d" % (
            len(blob), dimension)
    try:
        values = struct.unpack("<%df" % dimension, bytes(blob))
    except struct.error as error:
        return "vector BLOB unreadable: %s" % error
    for value in values:
        if not math.isfinite(value):
            return "vector BLOB holds a non-finite value"
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm == 0.0:
        return "vector BLOB is zero-norm"
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        return "vector BLOB L2 norm %.6f is not unit" % norm
    return None


def open_delta_checkpoint(path, generation, provider, facts_root):
    """Verify and load one delta checkpoint; raises ``DeltaRejected``.

    The checkpoint is trusted only when every check passes: the SQLite file
    passes ``quick_check`` with the declared WAL/FULL pragmas; the compatible
    identity (schema version, base generation id, store epoch, representation
    id, vector dimension, base watermark) matches the loaded generation and
    the fact store; every stored vector is a finite unit-norm FP32 row of the
    declared dimension; the consumed watermark lies within ``[H0, facts max]``;
    and the change sequence is consistent with the stored rows.  Any doubt
    raises ``DeltaRejected`` and the machine replays from ``H0`` (checkpoint
    只负责快速恢复,不成为第二事实源).
    """
    if not os.path.isfile(path):
        raise DeltaRejected("delta checkpoint not found: %s" % path)
    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise DeltaRejected("delta checkpoint unreadable: %s" % error)
    if size == 0:
        raise DeltaRejected("delta checkpoint is empty")
    conn = None
    try:
        conn = _connect_delta(path)
        _verify_delta_pragmas(conn)
        quick = conn.execute("PRAGMA quick_check;").fetchone()
        if quick is None or quick[0] != "ok":
            raise DeltaRejected(
                "delta quick_check failed: %s"
                % (quick[0] if quick is not None else "no result"))
        meta = _read_delta_meta(conn)
        for key in _META_KEYS:
            if key not in meta:
                raise DeltaRejected("delta meta key %s missing" % key)
        if meta["delta_schema_version"] != DELTA_SCHEMA_VERSION:
            raise DeltaRejected(
                "delta schema version %r unsupported"
                % meta["delta_schema_version"])
        if meta["base_generation_id"] != generation.generation_id:
            raise DeltaRejected(
                "delta base generation %r does not match %r"
                % (meta["base_generation_id"], generation.generation_id))
        if meta["store_epoch"] != generation.store_epoch:
            raise DeltaRejected(
                "delta store epoch %r does not match generation %r"
                % (meta["store_epoch"], generation.store_epoch))
        if meta["representation_id"] != provider.representation_id():
            raise DeltaRejected(
                "delta representation id %r does not match provider %r"
                % (meta["representation_id"], provider.representation_id()))
        try:
            dimension = int(meta["vector_dimension"])
            base_hlc = (int(meta["base_hlc_physical_ms"]),
                        int(meta["base_hlc_logical"]))
            consumed = (int(meta["consumed_hlc_physical_ms"]),
                        int(meta["consumed_hlc_logical"]))
            change_seq = int(meta["change_seq"])
        except (TypeError, ValueError) as error:
            raise DeltaRejected("delta meta numbers malformed: %s" % error)
        if dimension != generation.vector_dimension:
            raise DeltaRejected(
                "delta dimension %d does not match generation %d"
                % (dimension, generation.vector_dimension))
        if base_hlc != tuple(generation.source_hlc):
            raise DeltaRejected(
                "delta base watermark %r does not match generation %r"
                % (base_hlc, tuple(generation.source_hlc)))
        facts_identity = read_facts_identity(facts_root)
        if facts_identity is None:
            raise DeltaRejected("fact store is missing")
        facts_epoch, facts_max = facts_identity
        if facts_epoch != generation.store_epoch:
            raise DeltaRejected(
                "fact store epoch %r does not match generation %r"
                % (facts_epoch, generation.store_epoch))
        if consumed < base_hlc or consumed > facts_max:
            raise DeltaRejected(
                "delta consumed watermark %r outside [H0=%r, facts=%r]"
                % (consumed, base_hlc, facts_max))
        if change_seq < 0:
            raise DeltaRejected("delta change_seq is negative")
        rows = conn.execute(
            "SELECT event_id, commit_id, schema_id, canonical_segment_input,"
            " category, final_selection_text, hlc_physical_ms, hlc_logical,"
            " vector, change_seq FROM delta_events"
            " ORDER BY change_seq;").fetchall()
        tombstones = conn.execute(
            "SELECT commit_id, hlc_physical_ms, hlc_logical, change_seq"
            " FROM retractions ORDER BY change_seq;").fetchall()
        max_row_seq = max(
            [row["change_seq"] for row in rows]
            + [row["change_seq"] for row in tombstones] + [-1])
        if max_row_seq != change_seq:
            raise DeltaRejected(
                "delta change_seq %d does not match stored rows" % change_seq)
        events = []
        for row in rows:
            problem = _validate_vector_blob(row["vector"], dimension)
            if problem is not None:
                raise DeltaRejected(
                    "delta event %s: %s" % (row["event_id"], problem))
            if (row["hlc_physical_ms"], row["hlc_logical"]) <= base_hlc:
                raise DeltaRejected(
                    "delta event %s predates the base watermark"
                    % row["event_id"])
            events.append({
                "event_id": row["event_id"],
                "commit_id": row["commit_id"],
                "schema_id": row["schema_id"],
                "canonical_segment_input": row["canonical_segment_input"],
                "category": row["category"],
                "final_selection_text": row["final_selection_text"],
                "hlc": (row["hlc_physical_ms"], row["hlc_logical"]),
                "vector": row["vector"],
                "change_seq": row["change_seq"],
            })
        retractions = [
            {"commit_id": row["commit_id"],
             "hlc": (row["hlc_physical_ms"], row["hlc_logical"]),
             "change_seq": row["change_seq"]}
            for row in tombstones
        ]
        blocked = meta.get("blocked")
        blocked_events = meta.get("blocked_events")
        blocked_reason = meta.get("blocked_reason")
    except sqlite3.Error as error:
        raise DeltaRejected("delta checkpoint read failed: %s" % error)
    finally:
        if conn is not None:
            conn.close()
    return {
        "events": events,
        "retractions": retractions,
        "consumed": consumed,
        "change_seq": change_seq,
        "blocked": blocked == "1",
        "blocked_events": blocked_events,
        "blocked_reason": blocked_reason,
    }


def _drop_delta_checkpoint(path):
    """Delete the checkpoint plus its WAL/SHM sidecars (best effort)."""
    for name in (path, path + "-wal", path + "-shm"):
        try:
            os.unlink(name)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The active projection
# ---------------------------------------------------------------------------

def _project_active(items, retractions):
    """The ordered active-event list under the whole-commit tombstones.

    ``items`` carries both base rows and delta rows with their commit ids; a
    tombstone removes every event of that commit from the active set, exactly
    as the as-of projection of the facts would.  Order is the fact store's
    total order (hlc, event_id).
    """
    tombstoned = {item["commit_id"] for item in retractions}
    active = [item for item in items if item["commit_id"] not in tombstoned]
    active.sort(key=lambda item: (item["hlc"], item["event_id"]))
    return active


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

class DeltaStateMachine:
    """Single-worker durable delta state machine over one base generation.

    The machine owns: the verified base generation (built or loaded), the
    delta checkpoint (durable mirror of the absorbed changes), the in-memory
    change mirror, the current read-only snapshot, and the only worker thread
    that may write any of them.  ``ensure_caught_up`` is the AC63-1 query
    gate: it re-reads the facts identity on every call and returns the
    published snapshot only after it has caught up to that watermark.
    """

    def __init__(self, facts_root, derived_root, provider, generation_id,
                 catch_up_deadline=DEFAULT_CATCH_UP_DEADLINE_S,
                 poll_interval=DEFAULT_POLL_INTERVAL_S,
                 now=time.monotonic, sleep=time.sleep, start_worker=True):
        if not facts_root:
            raise DeltaError("facts root missing")
        if not derived_root:
            raise DeltaError("derived root missing")
        if not isinstance(provider, RepresentationProvider):
            raise DeltaError("provider must be a RepresentationProvider")
        if not generation_id or not isinstance(generation_id, str):
            raise DeltaError("generation_id must be a non-empty string")
        if not (isinstance(catch_up_deadline, (int, float))
                and catch_up_deadline > 0):
            raise DeltaError("catch_up_deadline must be positive")
        if not (isinstance(poll_interval, (int, float))
                and poll_interval > 0):
            raise DeltaError("poll_interval must be positive")
        self._facts_root = facts_root
        self._derived_root = derived_root
        self._provider = provider
        self._declared_generation_id = generation_id
        self._catch_up_deadline = float(catch_up_deadline)
        self._poll_interval = float(poll_interval)
        self._now = now
        self._sleep = sleep
        self._condition = threading.Condition()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._idle_event = threading.Event()
        if not start_worker:
            self._idle_event.set()
        self._closed = False
        self._snapshot = None  # type: Optional[DeltaSnapshot]
        self._generations = []  # opened generations, kept alive for snapshots
        self._generation = None  # type: Optional[Generation]
        self._base_commits = {}  # type: Dict[str, str]
        self._delta_events = []  # in-memory mirror of delta_events
        self._retractions = []   # in-memory mirror of retractions
        self._delta_consumed = None  # type: Optional[Tuple[int, int]]
        self._delta_change_seq = -1
        self._blocked = None  # type: Optional[DeltaBlocked]
        self._pending_rebuild = None  # (target_epoch, complete or None)
        self._last_error = None
        self._worker = None  # type: Optional[threading.Thread]

        self._delta_path = os.path.join(derived_root, DELTA_FILENAME)
        try:
            os.makedirs(derived_root, mode=0o700, exist_ok=True)
        except OSError as error:
            raise DeltaError("cannot create derived root: %s" % error)

        # -- load (or build) the base generation -------------------------
        try:
            generation = self._load_or_build_generation()
        except DeltaBlocked as error:
            # A deterministic build block at startup degrades to the blocked
            # state (requests fail with representation_fault until retry())
            # instead of taking the daemon down; the block re-derives on
            # restart the same way.
            self._blocked = error
            generation = None
        if generation is None:
            if start_worker:
                self._worker = threading.Thread(
                    target=self._run, name="delta-catch-up", daemon=True)
                self._worker.start()
            return
        if generation.representation_id != provider.representation_id():
            raise DeltaError(
                "generation representation id %r does not match provider %r"
                % (generation.representation_id,
                   provider.representation_id()))
        if generation.vector_dimension != provider.vector_dimension():
            raise DeltaError(
                "generation dimension %d does not match provider %d"
                % (generation.vector_dimension, provider.vector_dimension()))
        self._generation = generation
        self._generations.append(generation)
        base_hlc = tuple(generation.source_hlc)
        facts_identity = read_facts_identity(facts_root)
        if facts_identity is None:
            raise DeltaError("fact store is missing at machine startup")
        facts_epoch, _facts_max = facts_identity
        if facts_epoch != generation.store_epoch:
            raise DeltaError(
                "generation epoch %r does not match facts %r"
                % (generation.store_epoch, facts_epoch))
        base_commits = _read_base_commit_ids(facts_root, base_hlc)
        missing = [event_id for event_id in generation.event_ids()
                   if event_id not in base_commits]
        if missing:
            raise DeltaError(
                "generation rows lack fact commits: %s"
                % ", ".join(sorted(missing)[:5]))
        self._base_commits = base_commits

        # -- load the checkpoint, or replay from H0 ------------------------
        checkpoint = None
        try:
            checkpoint = open_delta_checkpoint(
                self._delta_path, generation, provider, facts_root)
        except DeltaRejected:
            _drop_delta_checkpoint(self._delta_path)
            checkpoint = None
        if checkpoint is not None and checkpoint["blocked"]:
            blocked_reason = checkpoint["blocked_reason"] or \
                "checkpoint records a block"
            try:
                blocked_events = json.loads(checkpoint["blocked_events"] or "[]")
                if not isinstance(blocked_events, list):
                    blocked_events = []
            except (TypeError, ValueError):
                blocked_events = []
            self._blocked = DeltaBlocked(blocked_reason, blocked_events,
                                         phase="restore")
            self._delta_events = checkpoint["events"]
            self._retractions = checkpoint["retractions"]
            self._delta_consumed = checkpoint["consumed"]
            self._delta_change_seq = checkpoint["change_seq"]
            with self._condition:
                # Keep the snapshot at the checkpoint's state (consumed may
                # lag facts while blocked); requests fail with
                # representation_fault until retry().
                self._publish_snapshot_locked()
        else:
            if checkpoint is not None:
                self._delta_events = checkpoint["events"]
                self._retractions = checkpoint["retractions"]
                self._delta_consumed = checkpoint["consumed"]
                self._delta_change_seq = checkpoint["change_seq"]
            else:
                self._delta_events = []
                self._retractions = []
                self._delta_consumed = base_hlc
                self._delta_change_seq = -1
            with self._condition:
                self._publish_snapshot_locked()
            if checkpoint is not None:
                # The strongest load check: the projected active set must
                # equal the facts' active set at the consumed watermark.
                try:
                    self._verify_snapshot_vs_facts(self._snapshot)
                except DeltaRejected:
                    _drop_delta_checkpoint(self._delta_path)
                    self._delta_events = []
                    self._retractions = []
                    self._delta_consumed = base_hlc
                    self._delta_change_seq = -1
                    with self._condition:
                        self._publish_snapshot_locked()

        if start_worker:
            self._worker = threading.Thread(
                target=self._run, name="delta-catch-up", daemon=True)
            self._worker.start()

    # ------------------------------------------------------------------
    # Generation lifecycle
    # ------------------------------------------------------------------

    def _generation_dir(self, generation_id):
        return os.path.join(self._derived_root, "generations", generation_id)

    def _load_or_build_generation(self):
        """The declared active generation if it matches the facts epoch.

        A missing, corrupt, identity-unknown or stale-epoch generation is
        rebuilt from facts (spec: 删除 generation 后可确定性全量重建; the
        declared id is the desired active, and the machine serves whatever
        current generation it had to build).
        """
        generation_dir = self._generation_dir(self._declared_generation_id)
        generation = None
        try:
            generation = open_generation(generation_dir)
        except GenerationRejected:
            generation = None
        if generation is not None:
            identity = read_facts_identity(self._facts_root)
            if identity is None:
                try:
                    generation.close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
                raise DeltaError("fact store is missing at machine startup")
            if identity[0] == generation.store_epoch:
                return generation
            # The declared generation belongs to a different store epoch:
            # derived state must never be reinterpreted across epochs.
            try:
                generation.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        return self._build_generation_now()

    def _build_generation_now(self):
        try:
            return build_generation(self._facts_root, self._provider,
                                    self._derived_root)
        except BuildBlockedError as error:
            raise DeltaBlocked(
                "cannot rebuild the generation: %s" % error.message,
                error.blocked_events, phase=error.phase)
        except BuildError as error:
            raise DeltaError("generation build failed: %s" % error)

    # ------------------------------------------------------------------
    # Snapshot publication (only the worker writes; lock held)
    # ------------------------------------------------------------------

    def _publish_snapshot_locked(self):
        """Project the current committed state into a new snapshot.

        Must be called with ``self._condition`` held; publishes the new
        snapshot and wakes every waiting request.  Base rows keep their
        vectors behind the generation mmap (no second resident copy); delta
        rows are served from the unpacked mirror.
        """
        items = []
        for index in range(self._generation.row_count):
            row = self._generation.row_event(index)
            event_id = row["event_id"]
            commit_id = self._base_commits.get(event_id)
            if commit_id is None:
                raise DeltaRejected(
                    "generation row %s has no fact commit" % event_id)
            key = row["choice_problem_key"]
            items.append({
                "event_id": event_id,
                "commit_id": commit_id,
                "schema_id": key[0],
                "canonical_segment_input": key[2],
                "category": key[1],
                "final_selection_text": row["candidate"],
                "hlc": tuple(row["hlc"]),
                "source": "base",
            })
        for item in self._delta_events:
            items.append(dict(item, source="delta"))
        active = _project_active(items, self._retractions)
        snapshot_events = []
        row_source = {}
        delta_vectors = {}
        for item in active:
            snapshot_events.append(StoredEvent(
                event_id=item["event_id"],
                commit_id=item["commit_id"],
                schema_id=item["schema_id"],
                canonical_segment_input=item["canonical_segment_input"],
                category=item["category"],
                final_selection_text=item["final_selection_text"],
                hlc=item["hlc"]))
            row_source[item["event_id"]] = item["source"]
            if item["source"] == "delta":
                delta_vectors[item["event_id"]] = _unpack_vector(
                    item["vector"])
        self._snapshot = DeltaSnapshot(
            store_epoch=self._generation.store_epoch,
            base_generation_id=self._generation.generation_id,
            representation_id=self._generation.representation_id,
            vector_dimension=self._generation.vector_dimension,
            consumed=self._delta_consumed,
            events=snapshot_events,
            row_source=row_source,
            generation=self._generation,
            delta_vectors=delta_vectors,
            change_seq=self._delta_change_seq)
        self._condition.notify_all()

    def _verify_snapshot_vs_facts(self, snapshot):
        """Event-set equality against the facts at the snapshot watermark."""
        expected = _facts_active_event_ids(self._facts_root,
                                           snapshot.consumed)
        actual = set(snapshot.event_ids())
        if actual != expected:
            raise DeltaRejected(
                "snapshot event set differs from facts at consumed watermark "
                "(missing=%d extra=%d)" % (len(expected - actual),
                                           len(actual - expected)))

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _run(self):
        """Worker thread: cycle while running, park while stopped.

        ``request_stop`` (maintenance prepare) parks the loop on the stop
        flag; ``start``/``rebuild`` resume it.  The thread only exits on
        ``close``.
        """
        while not self._closed:
            if self._stop_event.is_set():
                self._idle_event.set()
                self._wake_event.wait(self._poll_interval)
                self._wake_event.clear()
                continue
            self._idle_event.clear()
            try:
                self._cycle()
            except DeltaBlocked as error:
                self._enter_blocked(error)
            except DeltaError as error:
                with self._condition:
                    self._last_error = str(error)
                    self._condition.notify_all()
            except Exception as error:  # noqa: BLE001 - never die
                with self._condition:
                    self._last_error = "delta worker fault: %s" % error
                    self._condition.notify_all()
            self._wake_event.wait(self._poll_interval)
            self._wake_event.clear()

    def _cycle(self):
        """One worker iteration: pending rebuild, then catch-up attempt.

        While a deterministic block is recorded the worker parks: catch-up
        stays halted (no repeated embedding of the failing batch, no
        repeated diagnosis writes) until ``retry()`` or a rebuild clears
        it.  This also keeps the delta free of concurrent writers during
        the maintenance ``retry()`` path.
        """
        with self._condition:
            pending = self._pending_rebuild
            snapshot = self._snapshot
            blocked = self._blocked
        if pending is not None:
            self._perform_rebuild(pending)
            return
        if blocked is not None:
            return  # parked: blocked until retry()/rebuild
        facts_identity = read_facts_identity(self._facts_root)
        if facts_identity is None:
            return  # store not created yet; retry on the next wake
        facts_epoch, _facts_max = facts_identity
        if snapshot is None or snapshot.store_epoch != facts_epoch:
            self._perform_rebuild(None)
            return
        self._catch_up_batch(facts_identity)
        # Re-publish when a previous publish failed after its commit: the
        # mirror has advanced but the snapshot has not, and nothing new to
        # catch up remains.
        with self._condition:
            current = self._snapshot
            if (current is None
                    or current.consumed != self._delta_consumed
                    or current.change_seq != self._delta_change_seq):
                self._publish_snapshot_locked()

    def _perform_rebuild(self, pending):
        """Discard every piece of derived state and rebuild from facts.

        ``pending`` is ``(target_epoch, complete)`` from the coordinator's
        recovery seam, or None for a worker-detected epoch change.  A
        rebuild within the same epoch reuses the (still valid, verified)
        declared generation -- a rebuild only needs a new one when the
        epoch changed or the declared one is unusable.
        """
        with self._condition:
            if self._closed:
                return
            self._snapshot = None
            self._blocked = None
            self._pending_rebuild = None
            target_epoch = pending[0] if pending is not None else None
        if target_epoch is None:
            identity = read_facts_identity(self._facts_root)
            if identity is not None:
                target_epoch = identity[0]
        _drop_delta_checkpoint(self._delta_path)
        self._delta_events = []
        self._retractions = []
        self._delta_consumed = None
        self._delta_change_seq = -1
        generation = None
        try:
            generation = open_generation(
                self._generation_dir(self._declared_generation_id))
        except GenerationRejected:
            generation = None
        if (generation is None
                or (target_epoch is not None
                    and generation.store_epoch != target_epoch)):
            if generation is not None:
                try:
                    generation.close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
            generation = self._build_generation_now()
        base_commits = _read_base_commit_ids(
            self._facts_root, tuple(generation.source_hlc))
        with self._condition:
            if self._closed:
                return
            self._generation = generation
            self._generations.append(generation)
            self._base_commits = base_commits
            self._delta_consumed = tuple(generation.source_hlc)
            self._publish_snapshot_locked()
        if pending is not None and pending[1] is not None:
            pending[1](pending[0])

    def _enter_blocked(self, blocked):
        # Persist the diagnosis BEFORE publishing the block: when a waiting
        # request observes the blocked flag, the checkpoint record already
        # exists, so a subsequent retry() (which deletes the record) can
        # never race an in-flight diagnosis write.
        self._record_blocked(blocked)
        with self._condition:
            self._blocked = blocked
            self._condition.notify_all()

    def _record_blocked(self, blocked):
        """Persist the block as a diagnosis record in the checkpoint."""
        if self._generation is None or self._delta_consumed is None:
            return  # in-memory only; the block re-derives on restart
        conn = None
        try:
            _create_delta_schema(self._delta_path)
            conn = _connect_delta(self._delta_path,
                                  busy_timeout=WRITE_BUSY_TIMEOUT_S)
            conn.execute("BEGIN IMMEDIATE;")
            _write_delta_meta(conn, {
                "delta_schema_version": DELTA_SCHEMA_VERSION,
                "base_generation_id": self._generation.generation_id,
                "store_epoch": self._generation.store_epoch,
                "representation_id": self._generation.representation_id,
                "vector_dimension": self._generation.vector_dimension,
                "base_hlc_physical_ms": self._generation.source_hlc[0],
                "base_hlc_logical": self._generation.source_hlc[1],
                "consumed_hlc_physical_ms": self._delta_consumed[0],
                "consumed_hlc_logical": self._delta_consumed[1],
                "change_seq": self._delta_change_seq,
                "blocked": "1",
                "blocked_events": json.dumps(list(blocked.blocked_events)),
                "blocked_reason": blocked.message,
            })
            conn.execute("COMMIT;")
        except (sqlite3.Error, DeltaError):
            # Diagnosis record is best effort; the block still applies (and
            # re-derives deterministically on restart either way).  A
            # checkpoint fault must never kill the worker thread.
            pass
        finally:
            if conn is not None:
                conn.close()

    def retry(self):
        """Clear a deterministic block and let the worker re-attempt.

        Spec: 确定性失败保持 blocked,直到输入、配置或实现改变,或维护者显式重试.
        The checkpoint cleanup runs FIRST, while the worker is still parked
        on the block -- so this maintenance path never contends with the
        worker's write lock -- and the block is cleared (and the worker
        woken) only afterwards.  The cleanup waits up to
        ``WRITE_BUSY_TIMEOUT_S`` for any concurrent lock holder instead of
        failing fast (the repaired AC-63-v1 defect).
        """
        conn = None
        try:
            if os.path.isfile(self._delta_path):
                conn = _connect_delta(self._delta_path,
                                      busy_timeout=WRITE_BUSY_TIMEOUT_S)
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "DELETE FROM meta WHERE key IN"
                    " ('blocked', 'blocked_events', 'blocked_reason');")
                conn.execute("COMMIT;")
        except (sqlite3.Error, DeltaError):
            # Best effort, consistent with _record_blocked: the in-memory
            # unblock below is authoritative for this run, and a leftover
            # diagnosis record merely re-derives the block on restart.
            pass
        finally:
            if conn is not None:
                conn.close()
        with self._condition:
            if self._closed:
                return
            self._blocked = None
            self._condition.notify_all()
            self._wake_event.set()

    # ------------------------------------------------------------------
    # The catch-up batch (the only delta writer)
    # ------------------------------------------------------------------

    def _catch_up_batch(self, facts_identity):
        """One batch: embed, one durable delta transaction, one publish."""
        facts_epoch, (physical, logical) = facts_identity
        with self._condition:
            consumed = self._delta_consumed
        if consumed is None:
            return
        if (physical, logical) <= consumed:
            return
        events, retractions = _read_fact_changes(
            self._facts_root, consumed, (physical, logical))
        if not events and not retractions:
            return
        retracted_commits = {commit_id for commit_id, _hlc in retractions}
        to_embed = []
        for event in events:
            problem = _validate_event(event)
            if problem is not None:
                raise DeltaBlocked(
                    "cannot absorb delta event %s: %s"
                    % (event.event_id, problem), [event.event_id],
                    phase="parse")
            if event.commit_id in retracted_commits:
                # The whole commit leaves evidence in this same batch; its
                # vector never needs computing (equivalence: the projected
                # active set is identical either way).
                continue
            to_embed.append(event)
        vectors = {}
        for event in to_embed:
            vectors[event.event_id] = self._embed_vector(event)
        self._write_batch(events, vectors, retractions, facts_epoch,
                          (physical, logical))
        with self._condition:
            self._publish_snapshot_locked()
            self._wake_event.set()

    def _embed_vector(self, event):
        """One deterministic event vector; dirty results block the batch."""
        try:
            vector = self._provider.event_vector(event)
        except EvidenceError as error:
            raise DeltaBlocked(
                "cannot embed delta event %s: %s"
                % (event.event_id, error.message), [event.event_id],
                phase="vector")
        except Exception as error:  # noqa: BLE001 - fail closed
            raise DeltaBlocked(
                "cannot embed delta event %s: %s"
                % (event.event_id, error), [event.event_id], phase="vector")
        problem = _validate_vector(vector, self._generation.vector_dimension)
        if problem is not None:
            raise DeltaBlocked(
                "dirty vector for delta event %s: %s"
                % (event.event_id, problem), [event.event_id], phase="vector")
        return vector

    def _write_batch(self, events, vectors, retractions, facts_epoch,
                     upper):
        """One durable delta transaction: rows + tombstones + watermark.

        The vector embedding happened before this transaction; the commit
        advances ``delta_events``, ``retractions``, the consumed HLC and the
        change sequence atomically.  On any failure nothing is written and
        the in-memory mirror stays put, so the next cycle resumes from the
        old watermark (a committed-but-unpublished transaction is never
        re-embedded: mirror and checkpoint advance together here).
        """
        seq = self._delta_change_seq
        new_events = []
        new_retractions = []
        # Merge surviving events and tombstones into the fact store's total
        # order so the change sequence preserves it across both tables.
        # Events whose whole commit is retracted inside this same batch are
        # equivalent to never entering the checkpoint (their tombstone
        # filters them from the projection anyway) and carry no vector.
        retracted_commits = {commit_id for commit_id, _hlc in retractions}
        merged = []
        for event in events:
            if event.commit_id in retracted_commits:
                continue
            merged.append((event.hlc, event.event_id, "event", event))
        for commit_id, hlc in retractions:
            merged.append((hlc, commit_id, "retraction", commit_id))
        merged.sort(key=lambda item: (item[0], item[1], item[2]))
        path = self._delta_path
        conn = None
        try:
            _create_delta_schema(path)
            conn = _connect_delta(path, busy_timeout=WRITE_BUSY_TIMEOUT_S)
            conn.execute("BEGIN IMMEDIATE;")
            for _hlc, _key, kind, payload in merged:
                seq += 1
                if kind == "event":
                    event = payload
                    blob = _pack_vector(vectors[event.event_id])
                    conn.execute(
                        "INSERT INTO delta_events(event_id, commit_id,"
                        " schema_id, canonical_segment_input, category,"
                        " final_selection_text, hlc_physical_ms, hlc_logical,"
                        " vector, change_seq) VALUES(?,?,?,?,?,?,?,?,?,?);",
                        (event.event_id, event.commit_id, event.schema_id,
                         event.canonical_segment_input, event.category,
                         event.final_selection_text, event.hlc[0],
                         event.hlc[1], blob, seq))
                    new_events.append(event)
                else:
                    conn.execute(
                        "INSERT INTO retractions(commit_id, hlc_physical_ms,"
                        " hlc_logical, change_seq) VALUES(?,?,?,?);",
                        (payload, _hlc[0], _hlc[1], seq))
                    new_retractions.append((payload, _hlc))
            _write_delta_meta(conn, {
                "delta_schema_version": DELTA_SCHEMA_VERSION,
                "base_generation_id": self._generation.generation_id,
                "store_epoch": facts_epoch,
                "representation_id": self._generation.representation_id,
                "vector_dimension": self._generation.vector_dimension,
                "base_hlc_physical_ms": self._generation.source_hlc[0],
                "base_hlc_logical": self._generation.source_hlc[1],
                "consumed_hlc_physical_ms": upper[0],
                "consumed_hlc_logical": upper[1],
                "change_seq": seq,
            })
            conn.execute("COMMIT;")
        except sqlite3.Error as error:
            raise DeltaError("delta transaction failed: %s" % error)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
        self._delta_change_seq = seq
        self._delta_consumed = tuple(upper)
        for event in new_events:
            self._delta_events.append({
                "event_id": event.event_id,
                "commit_id": event.commit_id,
                "schema_id": event.schema_id,
                "canonical_segment_input": event.canonical_segment_input,
                "category": event.category,
                "final_selection_text": event.final_selection_text,
                "hlc": event.hlc,
                "vector": _pack_vector(vectors[event.event_id]),
            })
        for commit_id, hlc in new_retractions:
            self._retractions.append({"commit_id": commit_id, "hlc": hlc})

    # ------------------------------------------------------------------
    # The query gate (AC63-1)
    # ------------------------------------------------------------------

    def ensure_caught_up(self, deadline=None):
        """Return the published snapshot only when it covers the facts' watermark.

        Re-reads ``store_epoch`` + max change HLC from the facts on every
        call (notifications are only a wake optimization); waits for the
        worker with ``deadline``; raises ``EvidenceError(not_caught_up)`` if
        the snapshot cannot catch up in time -- never returns a stale
        snapshot as success (AC63-6 / SCN-63-3/7).
        """
        if deadline is None:
            deadline = self._now() + self._catch_up_deadline
        facts_identity = read_facts_identity(self._facts_root)
        if facts_identity is None:
            raise EvidenceError(
                "fact_store_fault", "fact store is missing")
        facts_epoch, facts_max = facts_identity
        with self._condition:
            while True:
                if self._closed:
                    raise EvidenceError("not_caught_up",
                                        "delta machine is closed")
                if self._blocked is not None:
                    raise EvidenceError(
                        "representation_fault",
                        "delta catch-up blocked: %s" % self._blocked.message)
                snapshot = self._snapshot
                if (snapshot is not None
                        and snapshot.store_epoch == facts_epoch
                        and snapshot.consumed >= facts_max):
                    return snapshot
                if self._stop_event.is_set():
                    raise EvidenceError(
                        "not_caught_up", "delta worker is stopped")
                remaining = deadline - self._now()
                if remaining <= 0:
                    raise EvidenceError(
                        "not_caught_up",
                        "delta catch-up exceeded the request deadline")
                self._wake_event.set()
                self._condition.wait(min(remaining, self._poll_interval))

    def snapshot(self):
        """The current published snapshot (may lag the facts; gate first)."""
        with self._condition:
            return self._snapshot

    # ------------------------------------------------------------------
    # Coordinator seams (maintenance prepare / epoch recovery)
    # ------------------------------------------------------------------

    def request_stop(self):
        """Builder seam: quiesce the worker before maintenance prepare."""
        self._stop_event.set()
        self._wake_event.set()

    def start(self):
        """Builder seam: restart a stopped (parked) worker."""
        self._stop_event.clear()
        self._wake_event.set()

    def wait_idle(self, timeout=30.0):
        """Builder seam: block until the worker has parked (or ended).

        The worker parks instead of exiting on ``request_stop``, so a later
        ``rebuild`` can resume it; "idle" means no cycle is running and no
        delta write or publish can be in flight.
        """
        return self._idle_event.wait(timeout)

    def invalidate(self, previous_epoch, target_epoch):
        """Coordinator recovery seam: discard all derived state.

        Synchronous and safe with in-flight requests: snapshots keep the
        generations they reference alive (the machine only closes them at
        ``close()``), so dropping the current snapshot pointer and the
        checkpoint file never tears state out from under a serving request.
        Callers must quiesce the worker first (maintenance prepare does);
        the worker-detected epoch-change path uses ``_perform_rebuild``
        directly in the worker thread.
        """
        del previous_epoch, target_epoch
        with self._condition:
            self._snapshot = None
            self._blocked = None
            self._condition.notify_all()
        _drop_delta_checkpoint(self._delta_path)
        self._delta_events = []
        self._retractions = []
        self._delta_consumed = None
        self._delta_change_seq = -1
        self._wake_event.set()

    def rebuild(self, target_epoch, complete=None):
        """Coordinator recovery seam: queue a rebuild on the worker thread.

        The worker rebuilds the generation from facts, publishes the new
        base snapshot and then calls ``complete(target_epoch)``.  Requests
        gated through ``ensure_caught_up`` fail with ``not_caught_up`` while
        the rebuild runs (never a stale success).
        """
        with self._condition:
            if self._closed:
                return
            if self._pending_rebuild is None:
                self._pending_rebuild = (target_epoch, complete)
            self._stop_event.clear()
            self._wake_event.set()

    # ------------------------------------------------------------------
    # Health and shutdown
    # ------------------------------------------------------------------

    def health(self):
        with self._condition:
            snapshot = self._snapshot
            return {
                "delta_epoch": (snapshot.store_epoch
                                if snapshot is not None else None),
                "delta_consumed": (snapshot.consumed
                                   if snapshot is not None else None),
                "delta_change_seq": (snapshot.change_seq
                                     if snapshot is not None else -1),
                "delta_blocked": self._blocked is not None,
                "delta_last_error": self._last_error,
                "delta_generation_id": (
                    snapshot.base_generation_id
                    if snapshot is not None else None),
            }

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._stop_event.set()
            self._wake_event.set()
            self._condition.notify_all()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(5.0)
        with self._condition:
            generations = tuple(self._generations)
            self._generations = []
            self._snapshot = None
        for generation in generations:
            try:
                generation.close()
            except Exception:  # noqa: BLE001 - best effort on close
                pass


# ---------------------------------------------------------------------------
# Validation helpers (shared standards with the generation builder)
# ---------------------------------------------------------------------------

def _validate_event(stored):
    """Structural parse validation; a violation blocks with the event named."""
    if not stored.event_id or not isinstance(stored.event_id, str):
        return "empty event_id"
    for label, value in (
            ("commit_id", stored.commit_id),
            ("schema_id", stored.schema_id),
            ("canonical_segment_input", stored.canonical_segment_input),
            ("category", stored.category),
            ("final_selection_text", stored.final_selection_text)):
        if not value or not isinstance(value, str):
            return "empty or non-string %s" % label
    physical, logical = stored.hlc
    if not (isinstance(physical, int) and physical >= 0
            and isinstance(logical, int) and logical >= 0):
        return "invalid HLC"
    return None


def _validate_vector(vector, dimension):
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        return "dimension %d does not match declared %d" % (
            len(vector) if isinstance(vector, (list, tuple)) else -1,
            dimension)
    for value in vector:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return "non-finite vector value"
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not math.isfinite(norm) or norm == 0.0:
        return "zero-norm vector"
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        return "L2 norm %.6f is not unit" % norm
    return None


# ---------------------------------------------------------------------------
# Config wiring (server.py builds the machine when the config declares it)
# ---------------------------------------------------------------------------

def build_delta_machine_from_config(facts_root, config):
    """Construct the delta machine from the evidence config dict.

    The config must declare the active generation explicitly (no directory
    scanning -- spec clause "不扫描目录猜测最新 generation"):

        derived_root: <path>          where delta.sqlite3 + generations/ live
        generation_id: <id>           the active base generation to serve
        catch_up_deadline_ms: <int>   per-request catch-up deadline (default 5000)
        poll_interval_ms: <int>       worker wake/poll interval (default 500)

    Both ``derived_root`` and ``generation_id`` must be present together;
    declaring only one is a configuration fault, not a silent fallback to
    the direct-facts evidence path.  Returns None when neither is declared.
    """
    if "derived_root" not in config and "generation_id" not in config:
        return None
    if "derived_root" not in config or "generation_id" not in config:
        raise EvidenceError(
            "evidence_unavailable",
            "derived_root and generation_id must both be configured")
    try:
        derived_root = config["derived_root"]
        generation_id = config["generation_id"]
        if not derived_root or not isinstance(derived_root, str):
            raise ValueError("derived_root must be a non-empty string")
        if not generation_id or not isinstance(generation_id, str):
            raise ValueError("generation_id must be a non-empty string")
        deadline = float(config.get("catch_up_deadline_ms", 5000)) / 1000.0
        poll = float(config.get("poll_interval_ms", 500)) / 1000.0
        if deadline <= 0 or poll <= 0:
            raise ValueError("deadlines must be positive")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed delta config: %s" % error)
    provider = _build_provider_from_config(config)
    return DeltaStateMachine(facts_root, derived_root, provider,
                             generation_id, catch_up_deadline=deadline,
                             poll_interval=poll)


def _build_provider_from_config(config):
    """The fixture representation seam behind the config (mirrors evidence.py).

    Kept here (not imported from evidence.py) to avoid a module-level import
    cycle: delta.py already imports evidence.py for the seam and the faults.
    """
    from evidence import FixtureRepresentationProvider
    try:
        representation_id = config["representation_id"]
        query_vectors = config.get("query_vectors") or {}
        event_vectors = config.get("event_vectors") or {}
        default_query = config.get("default_query")
        default_event = config.get("default_event")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed evidence config: %s" % error)
    return FixtureRepresentationProvider(
        representation_id,
        query_vectors,
        event_vectors,
        default_query=(default_query if default_query is not None
                       else (1.0, 0.0, 0.0, 0.0)),
        default_event=(default_event if default_event is not None
                       else (0.0, 1.0, 0.0, 0.0)))
