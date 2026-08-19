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

Checkpoint layout (spec clause "持久 delta 与立即可见性"; #65 makes the
checkpoint per-generation so the active and the staging generation each own
one, "active generation 与 staging generation 各自拥有独立 delta checkpoint"):

    <derived_root>/delta/<generation_id>/delta.sqlite3
                                             single WAL, synchronous=FULL
                                             checkpoint bound to that base
                                             generation (the staging
                                             machine's builds and the #65
                                             publish create one per staging)

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

Publish switch (#65): ``publish_switch`` is the in-memory query-pointer
swap of the blue-green publish.  The #65 publisher durably prepares the new
base generation (already moved into ``generations/``), its own delta
checkpoint (``delta/<generation_id>/delta.sqlite3``, covering ``(H0, H1]``)
and the replaced active manifest; then this machine's worker atomically
swaps generation, provider, checkpoint mirror and snapshot under the
machine condition -- a query sees either the complete old identity or the
complete new identity, never a mix (SCN-65-5).  The swap is synchronous for
the publisher (a condition handshake with a deadline); a worker parked by
maintenance delays the handshake to the deadline, and the publisher retries
on its next poll.  After the swap the catch-up worker continues on the new
checkpoint, absorbing facts past ``H1`` before the next successful query
(SCN-65-4).
"""

import contextlib
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
DELTA_DIRNAME = "delta"
DELTA_FILENAME = "delta.sqlite3"
# Spec: delta 使用 WAL 和 synchronous=FULL.
DELTA_JOURNAL_MODE = "wal"
DELTA_SYNC_MODE = "full"
# Default deadline for the #65 publish-switch handshake when the caller does
# not pass one (the switch reopens and re-verifies the whole generation, so
# the wait is bounded but generous).
DEFAULT_PUBLISH_SWITCH_DEADLINE_S = 60.0
# Same standard the generation builder applies to its vectors (unit norm
# within FP32 rounding tolerance); a dirty vector blocks the batch.
UNIT_NORM_TOLERANCE = 1e-3
# Defaults; configurable via config keys (catch_up_deadline_ms,
# poll_interval_ms).
DEFAULT_CATCH_UP_DEADLINE_S = 5.0
DEFAULT_POLL_INTERVAL_S = 0.5

# -- Dirty-scheduling thresholds (spec "压代、保留与回退") -------------------
# Same fingerprint: delta 的新增向量数加 tombstone 数达到
# max(2048, base active 行数的 5%) 时进入 soft-dirty (daemon 空闲时后台压代);
# 达到 20,000 条变更或 128MiB 时进入 hard-dirty (即使持续有输入也以低优先级
# 启动压代).  One builder at a time -- the compaction trigger hands the
# request to the staging machine, which serializes on the shared builder lock.
SOFT_DIRTY_MIN_CHANGES = 2048
SOFT_DIRTY_RATIO = 0.05
HARD_DIRTY_CHANGES = 20000
HARD_DIRTY_BYTES = 128 * 1024 * 1024

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

# The fact-store WAL on macOS can transiently return SQLITE_BUSY when two
# threads open fresh read-only connections at the same instant (the -shm
# read-marker handshake).  The daemon's hot path runs exactly that pattern
# (worker catch-up + query gate + the #65 publisher/switch), so fact reads
# get a short busy wait instead of a spurious fail-fast fault; a genuinely
# held exclusive lock (maintenance) still faults after the wait.
#
# Read-only open semantics (AC-65-v1 repair): sqlite 3.54.0 returns
# SQLITE_CANTOPEN ("unable to open database file") for a
# ``file:<path>?mode=ro`` URI open of a WAL database whose data was written
# before the WAL switch, while an in-process writer connection is open
# (sqlite 3.53.3 succeeds; docs/publish-atomic.md "WAL read-only open
# semantics across sqlite versions").  Fact reads therefore open the plain
# path and enforce read-only in the engine instead: ``PRAGMA query_only=ON``
# rejects every data-modifying statement with SQLITE_READONLY -- the same
# fail-closed guarantee as ``mode=ro``, without depending on the versioned
# URI behavior.  The file must already exist (a plain open would otherwise
# create it), so callers that can reach a missing store must check first.
FACT_READ_BUSY_TIMEOUT_S = 2.0


def _open_facts_ro(facts_root):
    db_path = os.path.join(facts_root, "facts.sqlite3")
    if not os.path.isfile(db_path):
        raise DeltaError("fact store not found: %s" % db_path)
    try:
        conn = sqlite3.connect(db_path, timeout=FACT_READ_BUSY_TIMEOUT_S)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON;")
    except sqlite3.Error as error:
        raise DeltaError("cannot open fact store: %s" % error)
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


def read_facts_schema_version(facts_root):
    """The fact store's ``fact_schema_version``, or None when the store is
    missing (#66: the fact schema is part of the layered compat identity --
    ``fact_schema_version`` bounds the decodable range of the fact tables,
    event format and HLC).  A store without a provable schema version is a
    true fault (refuse), never an implicit default."""
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
    version = rows.get("fact_schema_version")
    if not version or not isinstance(version, str):
        raise DeltaError("fact store schema version is missing or malformed")
    return version


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

    ``query_provider`` (#65) is the representation provider current when the
    snapshot was published: the snapshot's query vectors are bound to the
    snapshot's own representation, so a single query can never mix the old
    and the new representation/projection/index identity (SCN-65-5), even
    while a publish switch is in flight.
    """

    def __init__(self, store_epoch, base_generation_id, representation_id,
                 vector_dimension, consumed, events, row_source, generation,
                 delta_vectors, change_seq, query_provider=None):
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
        self._query_provider = query_provider

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

    def query_vector(self, preceding_text):
        """The query vector in THIS snapshot's representation (#65).

        Bound to the provider current at publish time, so a query served
        from this snapshot always uses the same representation as the
        stored event vectors it is compared against.
        """
        if self._query_provider is None:
            raise DeltaError("snapshot has no query provider")
        return self._query_provider.query_vector(preceding_text)


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
        if change_seq < -1:
            raise DeltaRejected("delta change_seq is negative")
        # change_seq == -1 is the legitimate fresh state of a generation
        # with no post-H0 changes (the #65 publish writes an empty
        # checkpoint for an empty (H0,H1] window); the max_row_seq check
        # below still rejects any row that contradicts it.
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
                 now=time.monotonic, sleep=time.sleep, start_worker=True,
                 builder_lock=None, refuse_reason=None,
                 soft_dirty_min_changes=SOFT_DIRTY_MIN_CHANGES,
                 soft_dirty_ratio=SOFT_DIRTY_RATIO,
                 hard_dirty_changes=HARD_DIRTY_CHANGES,
                 hard_dirty_bytes=HARD_DIRTY_BYTES,
                 disk_budget_bytes=None):
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
        self._builder_lock = builder_lock
        self._soft_dirty_min_changes = soft_dirty_min_changes
        self._soft_dirty_ratio = soft_dirty_ratio
        self._hard_dirty_changes = hard_dirty_changes
        self._hard_dirty_bytes = hard_dirty_bytes
        # #67: derived-disk budget for the pre-build space estimate (spec
        # "构建前预估三份派生状态的峰值空间").  None = no limit (backwards
        # compatible with #63/#65/#66); the config seam wires the 3 GiB
        # spec gate by default.  A short budget keeps the current active and
        # reports the error, never deleting the only rollback (SCN-67-3).
        self._disk_budget_bytes = disk_budget_bytes
        # #67: the compaction trigger (normally the staging machine's
        # ``request_compaction``), wired by the config seam after both
        # machines exist.  None keeps the machine fully self-contained (the
        # #63/#65 behavior); dirty state is then only observable.
        self._compaction_trigger = None
        # #67: set by ``_recover_via_rollback`` when no healthy rollback
        # exists -- the semantic path must fail closed and a background
        # rebuild from facts must be queued (AC67-6).  The config seam reads
        # it to force the staging machine's build.
        self._force_rebuild_requested = False
        # #66 refuse-load: a present-but-invalid / unknown active manifest
        # refuses the load of derived state (SCN-66-10); the machine never
        # falls back to the config-declared active.  Requests fail closed
        # (pass-through) and status reports the refusal.
        self._refuse_reason = refuse_reason
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
        self._pending_publish = None  # #65 publish-switch record or None
        self._publish_result = None   # (ok, error) of the last switch
        self._last_error = None
        self._worker = None  # type: Optional[threading.Thread]

        # #65: the checkpoint is per-generation (spec: active 与 staging 各自
        # 拥有独立 delta checkpoint), under delta/<generation_id>/.
        self._delta_path = os.path.join(
            derived_root, DELTA_DIRNAME, generation_id, DELTA_FILENAME)
        try:
            os.makedirs(os.path.dirname(self._delta_path), mode=0o700,
                        exist_ok=True)
        except OSError as error:
            raise DeltaError("cannot create delta checkpoint root: %s"
                             % error)
        try:
            os.makedirs(derived_root, mode=0o700, exist_ok=True)
        except OSError as error:
            raise DeltaError("cannot create derived root: %s" % error)

        # -- load (or build) the base generation -------------------------
        if self._refuse_reason is not None:
            # #66: refuse to load derived state per an unknown/broken active
            # manifest.  #67: still try the explicit rollback pointer first --
            # a corrupt active manifest (discovered here or injected by the
            # server's resolver) is recoverable when a healthy rollback
            # exists.  Only when no healthy rollback exists does the machine
            # park in the refused state (fail-closed passthrough + background
            # rebuild), and a publish of a fresh, valid generation clears it.
            generation = self._recover_via_rollback(
                refuse_reason=self._refuse_reason,
                damage=self._refuse_reason, isolate=False)
            if generation is None:
                if start_worker:
                    self._worker = threading.Thread(
                        target=self._run, name="delta-catch-up", daemon=True)
                    self._worker.start()
                return
        else:
            try:
                generation = self._load_or_build_generation()
            except DeltaBlocked as error:
                # A deterministic build block at startup degrades to the
                # blocked state (requests fail with representation_fault
                # until retry()) instead of taking the daemon down; the
                # block re-derives on restart the same way.
                self._blocked = error
                generation = None
        if generation is None:
            # Either a deterministic build block (above) or a #66
            # refuse-on-broken-published-identity (``_refuse_reason`` was set
            # by ``_load_or_build_generation``).  Both park the worker; every
            # request fails closed (representation_fault / active_identity_
            # refused) until retry()/a valid publish clears the state.
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
        """Load the declared active generation, or rebuild from facts.

        Two distinct paths (AC66-8 / SCN-66-10 / SCN-66-12):

        - **Nothing published yet** (no active manifest, or a manifest
          naming a different generation): the #63 rebuild-from-facts path
          applies -- there is nothing to refuse, and the declared id is the
          desired active.  A missing generation directory, or one that is
          simply absent, rebuilds deterministically (spec: 删除 generation
          后可确定性全量重建).
        - **A present-but-invalid / unknown active manifest**: refuse the
          load (SCN-66-10); never a config-active fallback, never a rebuild
          into the refused identity.
        - **A published identity is present but broken**: a durable active
          manifest names a generation whose directory is missing or whose
          ``open_generation`` fails (checksum / unknown format / unsupported
          backend / identity mismatch).  This *refuses* the load rather than
          rebuilding into the broken identity; the machine must not serve a
          freshly built container as the successful active for a broken
          published identity.  ``_build_generation_now()`` is never called
          for it; the worker parks in the refused state and only a valid
          publish clears it.
        """
        generation_dir = self._generation_dir(self._declared_generation_id)
        published, refuse_reason = self._published_identity_state()
        if refuse_reason is not None:
            # A present-but-invalid / unknown active manifest refuses the
            # load (SCN-66-10): never a config-active fallback, never a
            # rebuild into the refused identity.  #67: try the explicit
            # rollback pointer before giving up (SCN-67-5) -- a corrupt
            # active manifest is recoverable when a healthy rollback exists.
            # ``isolate=False``: the damage is the manifest itself, so no
            # generation is provably bad -- the config-declared directory is
            # left untouched (never a guess).
            return self._recover_via_rollback(
                refuse_reason=refuse_reason, damage=refuse_reason,
                isolate=False)
        if not os.path.isdir(generation_dir):
            if published:
                # A durable publish names a generation directory that is
                # missing: a broken published identity -> #67 rollback
                # recovery (never rebuild-and-serve into the refused
                # identity; AC66-8 keeps refusing only when no healthy
                # rollback exists).
                return self._recover_via_rollback(
                    refuse_reason=(
                        "published generation %s is missing"
                        % self._declared_generation_id),
                    damage="published generation %s is missing"
                           % self._declared_generation_id)
            # Nothing published for the declared identity: rebuild from facts.
            return self._build_generation_now()
        try:
            generation = open_generation(generation_dir)
        except GenerationRejected as error:
            if published:
                # A durable publish names a generation that fails reopen: a
                # broken published identity -> #67 rollback recovery (isolate
                # the damaged active, re-verify + catch up the rollback, then
                # serve it; only when no healthy rollback exists does the load
                # refuse and a background rebuild-from-facts get queued).
                return self._recover_via_rollback(
                    refuse_reason=error.reason, damage=error.reason)
            # No durable publish: the config-declared active is still
            # "nothing published yet" -> #63 rebuild-from-facts.
            return self._build_generation_now()
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
            # derived state must never be reinterpreted across epochs.  This
            # is an epoch change (rebuild), not a broken identity (refuse):
            # no active manifest promised this generation for the new epoch.
            try:
                generation.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        return self._build_generation_now()

    def _recover_via_rollback(self, refuse_reason, damage, isolate=True):
        """#67 rollback recovery for a damaged published active.

        Called only for a *published* identity that cannot be served (corrupt
        active manifest, missing generation directory, or a generation that
        fails ``open_generation`` -- base / metadata / checksum damage).
        Follows spec "损坏处理" exactly:

        1. Isolate the damaged active generation (``isolated/`` under the
           derived root) -- it must never be served and must never become a
           rollback (SCN-67-2).  When the damage is the active manifest
           itself (``isolate=False``) no generation is provably bad -- the
           config-declared directory is left untouched (never a guess).
        2. Read the EXPLICIT rollback pointer only (never scan
           ``generations/`` -- SCN-67-7).
        3. If a rollback exists and is healthy (``open_generation`` re-verifies
           identity + checksums + probes) and its layered identity matches the
           current facts epoch / runtime, catch its delta checkpoint up to the
           current facts watermark (``publish._build_staging_delta``), durably
           make it the active (write the active manifest), and return it for
           serving.  A catch-up failure is NOT a semantic success: the load
           refuses (AC67-5).
        4. No healthy rollback -> refuse the load (semantic requests fail
           closed / pass through) and record ``force_rebuild_requested`` so
           the config seam queues a background rebuild from facts (AC67-6) --
           fact recording / IME commit keep working (nothing here writes
           facts).
        """
        from publish import (  # noqa: F401  (local import: publish imports delta)
            _build_staging_delta, _compose_active_manifest, _read_fact_schema_version,
            write_active_manifest,
        )
        from retention import (clear_rollback_manifest, isolate_generation,
                               read_rollback_manifest, retention_sweep)
        # 1. Isolate the damaged active generation (best effort; a directory
        #    that no longer exists has nothing to isolate).
        if isolate:
            isolate_generation(self._derived_root, self._declared_generation_id,
                               "active generation damaged: %s" % damage)
        # 2. The explicit rollback pointer -- never a scan (SCN-67-7).
        rollback, rollback_reason = read_rollback_manifest(self._derived_root)
        if rollback is None:
            # No healthy rollback: keep the ORIGINAL diagnosis as the
            # fail-closed refusal (the #66 message contract is preserved --
            # e.g. "active manifest unreadable: ..." / "checksum failure")
            # and record that a background rebuild-from-facts must be queued
            # (AC67-6; the config seam reads ``force_rebuild_requested``).
            # A stale/unusable pointer is appended to the reason.
            return self._refuse_recovery(
                "%s%s" % (refuse_reason or damage,
                          ("; unusable rollback pointer: %s" % rollback_reason)
                          if rollback_reason else ""))
        rollback_id = rollback["generation_id"]
        if rollback_id == self._declared_generation_id:
            # The pointer names the damaged generation itself: unusable.
            return self._refuse_recovery(
                "rollback pointer names the damaged active %s" % rollback_id,
                clear_pointer=True)
        try:
            rollback_gen = open_generation(
                self._generation_dir(rollback_id))
        except GenerationRejected as error:
            return self._refuse_recovery(
                "rollback %s is damaged: %s" % (rollback_id, error.reason),
                clear_pointer=True)
        try:
            facts_identity = read_facts_identity(self._facts_root)
        except DeltaError as error:
            try:
                rollback_gen.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
            raise DeltaError("fact store read failed: %s" % error)
        if facts_identity is None:
            return self._refuse_recovery("fact store is missing",
                                         generation=rollback_gen)
        facts_epoch, facts_max = facts_identity
        # 3a. Re-verify identity + fingerprints + runtime support range
        #     (AC67-5): the rollback must bind the current facts epoch and
        #     the runtime's representation / dimension.
        if rollback_gen.store_epoch != facts_epoch:
            return self._refuse_recovery(
                "rollback %s belongs to store epoch %r, facts are %r"
                % (rollback_id, rollback_gen.store_epoch, facts_epoch),
                generation=rollback_gen, clear_pointer=True)
        if (rollback_gen.representation_id
                != self._provider.representation_id()
                or rollback_gen.vector_dimension
                != self._provider.vector_dimension()):
            return self._refuse_recovery(
                "rollback %s identity does not match the runtime "
                "(representation/dimension)" % rollback_id,
                generation=rollback_gen)
        # 3b. Catch the rollback's own delta checkpoint up to the current
        #     facts watermark (AC67-5): only then may it serve.  A catch-up
        #     failure (deterministic embed fault, epoch change) is NOT a
        #     semantic success -- the load refuses.
        progress = {
            "generation_id": rollback_id,
            "identity": {
                "store_epoch": rollback_gen.store_epoch,
                "source_hlc": list(rollback_gen.source_hlc),
                "representation_id": rollback_gen.representation_id,
                "vector_dimension": rollback_gen.vector_dimension,
            },
        }
        try:
            checkpoint_path = _build_staging_delta(
                self._facts_root, self._derived_root, progress,
                self._provider, facts_max)
        except Exception as error:  # noqa: BLE001 - fail closed
            return self._refuse_recovery(
                "rollback catch-up failed: %s" % error,
                generation=rollback_gen)
        # 3c. Durable: the rollback becomes the active (the manifest is the
        #     source of truth after recovery; a restart loads it directly).
        try:
            fact_schema_version = _read_fact_schema_version(self._facts_root)
            if not fact_schema_version:
                raise DeltaError("fact store schema version missing")
            manifest = _compose_active_manifest(
                rollback_gen, checkpoint_path, fact_schema_version)
            write_active_manifest(self._derived_root, manifest)
        except Exception as error:  # noqa: BLE001 - fail closed
            return self._refuse_recovery(
                "rollback activation failed: %s" % error,
                generation=rollback_gen)
        clear_rollback_manifest(self._derived_root)
        from retention import live_staging_generation_ids
        retention_sweep(self._derived_root, active_id=rollback_id,
                        live_staging_ids=live_staging_generation_ids(
                            self._derived_root))
        # The machine now serves the recovered rollback as the active.
        self._declared_generation_id = rollback_id
        self._delta_path = os.path.join(
            self._derived_root, DELTA_DIRNAME, rollback_id, DELTA_FILENAME)
        self._refuse_reason = None
        return rollback_gen

    def _refuse_recovery(self, reason, generation=None, clear_pointer=False):
        """#67 shared recovery-failure exit: park in the fail-closed refused
        state and record that a background rebuild-from-facts must be queued
        (AC67-6).  Closes the opened rollback generation (best effort) and
        optionally clears an unusable rollback pointer.  Returns None so the
        recovery path can ``return self._refuse_recovery(...)`` directly."""
        if generation is not None:
            try:
                generation.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        if clear_pointer:
            from retention import clear_rollback_manifest
            clear_rollback_manifest(self._derived_root)
        self._refuse_reason = reason
        self._force_rebuild_requested = True
        return None

    def _published_identity_state(self):
        """``(published, refuse_reason)`` for the declared generation id.

        The active manifest is the durable source of truth for what is
        published (#65/#66):

        - no manifest -> ``(False, None)``: nothing published yet, the
          #63 rebuild-from-facts path applies (AC66-8);
        - a present-but-invalid / unknown manifest -> ``(False, reason)``:
          refuse the load (SCN-66-10), never a config-active fallback;
        - a valid manifest naming the declared id -> ``(True, None)``: the
          generation must reopen cleanly or the load refuses (AC66-8);
        - a valid manifest naming a *different* id -> ``(False, None)``: the
          declared id is not the published one (stale config), so there is
          nothing published for it.
        """
        from publish import read_active_manifest
        manifest, reason = read_active_manifest(self._derived_root)
        if reason is not None:
            return False, reason
        if manifest is None:
            return False, None
        return (manifest.get("generation_id") == self._declared_generation_id,
                None)

    def _build_generation_now(self):
        # The single-builder constraint (spec "一次只运行一个 builder"):
        # when the daemon wires a shared builder lock, this rebuild path and
        # the staging machine's embed steps serialize on it, so two builders
        # never run the model concurrently.
        lease = self._builder_lock or contextlib.nullcontext()
        with lease:
            # #67 pre-build space estimate (spec "构建前预估三份派生状态的峰值
            # 空间"): a short derived-disk budget keeps the current active and
            # reports the error, never deleting the only rollback (SCN-67-3).
            # A projected container is estimated from the active row count x
            # dimension x 4 bytes; the estimate is best-effort (the build is
            # the fail-closed authority for its own space needs).
            # #67 pre-build space estimate (spec "构建前预估三份派生状态的峰值
            # 空间"): a short derived-disk budget keeps the current active and
            # reports the error, never deleting the only rollback (SCN-67-3).
            # A projected container is estimated from the active row count x
            # dimension x 4 bytes; the estimate is best-effort (the build is
            # the fail-closed authority for its own space needs).  Without a
            # budget (None) the estimate is skipped entirely.
            if self._disk_budget_bytes is not None:
                try:
                    from generation import _read_snapshot
                    from retention import check_build_space
                    _store_epoch, _source_hlc, rows = _read_snapshot(
                        self._facts_root)
                    dimension = self._provider.vector_dimension()
                    ok, reason = check_build_space(
                        self._derived_root, self._disk_budget_bytes,
                        projected_staging_bytes=len(rows) * dimension * 4
                        + 4096)
                except Exception as error:  # noqa: BLE001 - fail closed
                    ok, reason = False, "space estimate failed: %s" % error
                if not ok:
                    raise DeltaError(
                        "cannot rebuild the generation: %s" % reason)
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

    def _build_snapshot(self, generation, provider, base_commits, checkpoint):
        """Project one committed state into a new snapshot (no side effects).

        Base rows keep their vectors behind the generation mmap (no second
        resident copy); delta rows are served from the unpacked mirror.
        ``checkpoint`` is a dict with ``events``, ``retractions``,
        ``consumed`` and ``change_seq`` -- either the machine's in-memory
        mirror or a freshly parsed publish checkpoint.
        """
        items = []
        for index in range(generation.row_count):
            row = generation.row_event(index)
            event_id = row["event_id"]
            commit_id = base_commits.get(event_id)
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
        for item in checkpoint["events"]:
            items.append(dict(item, source="delta"))
        active = _project_active(items, checkpoint["retractions"])
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
        return DeltaSnapshot(
            store_epoch=generation.store_epoch,
            base_generation_id=generation.generation_id,
            representation_id=generation.representation_id,
            vector_dimension=generation.vector_dimension,
            consumed=checkpoint["consumed"],
            events=snapshot_events,
            row_source=row_source,
            generation=generation,
            delta_vectors=delta_vectors,
            change_seq=checkpoint["change_seq"],
            query_provider=provider)

    def _publish_snapshot_locked(self):
        """Project the current committed state into a new snapshot.

        Must be called with ``self._condition`` held; publishes the new
        snapshot and wakes every waiting request.
        """
        checkpoint = {
            "events": self._delta_events,
            "retractions": self._retractions,
            "consumed": self._delta_consumed,
            "change_seq": self._delta_change_seq,
        }
        self._snapshot = self._build_snapshot(
            self._generation, self._provider, self._base_commits, checkpoint)
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
        """One worker iteration: pending publish, pending rebuild, then
        catch-up attempt.

        A pending publish switch (#65) is processed first: it is the
        linearization point of the blue-green transaction, and it clears any
        deterministic catch-up block (a publish is a representation/config
        change -- spec: 输入、配置或实现改变 clears a block).  While a
        deterministic block is recorded the worker parks: catch-up stays
        halted (no repeated embedding of the failing batch, no repeated
        diagnosis writes) until ``retry()`` or a rebuild clears it.  This
        also keeps the delta free of concurrent writers during the
        maintenance ``retry()`` path.
        """
        with self._condition:
            pending_publish = self._pending_publish
            pending = self._pending_rebuild
            snapshot = self._snapshot
            blocked = self._blocked
            refuse_reason = self._refuse_reason
        if pending_publish is not None:
            # A publish switch is processed even while refused (#66): it is
            # the linearization point that reopens and re-verifies a fresh,
            # complete generation, and it clears the refusal on success --
            # queries fail closed until a valid publish, then recover.
            self._perform_publish_switch(pending_publish)
            return
        if refuse_reason is not None:
            # #66 refuse-load: park the worker; only a publish of a fresh,
            # valid generation (publish_switch, above) clears the refusal.
            # No catch-up, no rebuild -- the active identity cannot be trusted.
            return
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
        self._maybe_request_compaction(facts_identity)

    def _maybe_request_compaction(self, facts_identity):
        """#67 dirty scheduling: ask the single builder to compact.

        - hard-dirty -> trigger even under input (low priority);
        - soft-dirty -> trigger only when caught up (daemon idle).

        The trigger is normally the staging machine's ``request_compaction``;
        it is a no-op when none is wired.  The staging machine serializes
        every build on the shared builder lock, so compaction never runs a
        second builder (SCN-67-1).
        """
        with self._condition:
            trigger = self._compaction_trigger
            if trigger is None:
                return
            snapshot = self._snapshot
            if snapshot is None:
                return
            consumed = snapshot.consumed
        try:
            state = self.dirty_state()
        except Exception:  # noqa: BLE001 - scheduling is best effort
            return
        if state["hard_dirty"]:
            trigger()
            return
        if not state["soft_dirty"]:
            return
        _facts_epoch, facts_max = facts_identity
        if consumed >= facts_max:
            trigger()

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
            # A queued publish switch is aborted by the epoch change; the
            # old active stays intact and the manifest keeps pointing at it
            # until the next publish overwrites it.  The handshake waiter
            # gets the explicit abort (never a silent no-result).
            if self._pending_publish is not None:
                self._pending_publish = None
                self._publish_result = (
                    False, "store epoch changed; publish aborted (SCN-65-7)")
                self._condition.notify_all()
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
            self._delta_path = os.path.join(
                self._derived_root, DELTA_DIRNAME, generation.generation_id,
                DELTA_FILENAME)
            try:
                os.makedirs(os.path.dirname(self._delta_path), mode=0o700,
                            exist_ok=True)
            except OSError:
                pass  # the next write re-creates it; nothing is lost
            self._publish_snapshot_locked()
        if pending is not None and pending[1] is not None:
            pending[1](pending[0])
        # #67: an epoch change discards ALL derived state -- the rollback
        # pointer belongs to the old epoch (never reinterpreted) and every
        # old-epoch generation is superseded; the retention sweep keeps only
        # the freshly rebuilt active (SCN-67-8: facts untouched).  Runs
        # after the completion callback so the coordinator handshake is not
        # delayed by filesystem cleanup.  A live staging build is never
        # deleted (the sweep is told the live staging ids).
        try:
            from retention import (clear_rollback_manifest,
                                   live_staging_generation_ids,
                                   retention_sweep)
            clear_rollback_manifest(self._derived_root)
            retention_sweep(self._derived_root,
                            active_id=generation.generation_id,
                            live_staging_ids=live_staging_generation_ids(
                                self._derived_root))
        except Exception:  # noqa: BLE001 - best effort cleanup
            pass

    # ------------------------------------------------------------------
    # Publish switch (#65): the in-memory query-pointer swap
    # ------------------------------------------------------------------

    def publish_switch(self, generation_id, checkpoint_path, provider,
                       expected_epoch, deadline=None):
        """The #65 in-memory pointer swap, synchronous for the publisher.

        Queues the switch on the worker thread and waits (bounded by
        ``deadline``, default ``DEFAULT_PUBLISH_SWITCH_DEADLINE_S``) for it
        to complete: the worker reopens and re-verifies the published
        generation and its delta checkpoint, then atomically swaps
        generation / provider / checkpoint mirror / snapshot under the
        machine condition.  Returns ``(ok, error)``; on failure the old
        active identity is left serving untouched.  A second caller joins
        the in-flight switch instead of queueing a second one.

        The caller (the #65 publisher) has already made the active manifest
        durable before calling; a crash after this point therefore loads
        the complete new generation on restart, exactly the SCN-65-3
        semantics.
        """
        if not generation_id or not isinstance(generation_id, str):
            raise DeltaError("generation_id must be a non-empty string")
        if not checkpoint_path or not isinstance(checkpoint_path, str):
            raise DeltaError("checkpoint_path must be a non-empty string")
        if not isinstance(provider, RepresentationProvider):
            raise DeltaError("provider must be a RepresentationProvider")
        if not expected_epoch or not isinstance(expected_epoch, str):
            raise DeltaError("expected_epoch must be a non-empty string")
        if deadline is None:
            deadline = self._now() + DEFAULT_PUBLISH_SWITCH_DEADLINE_S
        with self._condition:
            if self._closed:
                return False, "delta machine is closed"
            if self._pending_publish is None:
                self._pending_publish = (generation_id, checkpoint_path,
                                         provider, expected_epoch)
                self._publish_result = None
                self._wake_event.set()
            while self._pending_publish is not None:
                remaining = deadline - self._now()
                if remaining <= 0:
                    # The record stays queued: a worker parked by
                    # maintenance processes it once resumed, and the
                    # publisher retries the handshake on its next poll.
                    return False, "publish switch timed out waiting for " \
                                  "the worker"
                self._condition.wait(min(remaining, self._poll_interval))
        result = self._publish_result
        if result is None:
            return False, "publish switch produced no result"
        return result

    def _perform_publish_switch(self, pending):
        """Worker-side swap: verify, then swap, then publish (SCN-65-5).

        Nothing is swapped until every verification passed: the facts epoch
        still matches the publish's expected epoch (SCN-65-7 aborts the
        switch, leaving the old active untouched), the published generation
        reopens with the full verification (checksums, event set, row
        mapping, vectors, exact-oracle probes), its delta checkpoint binds
        to it, and the projected active set equals the facts at the
        checkpoint's consumed watermark.  The swap itself happens under the
        machine condition, so ``ensure_caught_up`` observers atomically see
        either the complete old snapshot or the complete new one.
        """
        generation_id, checkpoint_path, provider, expected_epoch = pending
        generation = None
        if not os.path.isabs(checkpoint_path):
            # The publisher addresses the checkpoint manifest-relative
            # ("delta/<id>/delta.sqlite3"); resolve against the derived
            # root for the verification and as the new active path.
            checkpoint_path = os.path.join(self._derived_root, checkpoint_path)
        try:
            identity = read_facts_identity(self._facts_root)
            if identity is None or identity[0] != expected_epoch:
                self._finish_publish(
                    False, "store epoch changed; publish aborted (SCN-65-7)")
                return
            generation = open_generation(
                self._generation_dir(generation_id))
            checkpoint = open_delta_checkpoint(
                checkpoint_path, generation, provider, self._facts_root)
            base_commits = _read_base_commit_ids(
                self._facts_root, tuple(generation.source_hlc))
            missing = [event_id for event_id in generation.event_ids()
                       if event_id not in base_commits]
            if missing:
                raise DeltaRejected(
                    "published generation rows lack fact commits: %s"
                    % ", ".join(sorted(missing)[:5]))
            snapshot = self._build_snapshot(generation, provider,
                                            base_commits, checkpoint)
            self._verify_snapshot_vs_facts(snapshot)
        except (DeltaRejected, DeltaError, GenerationRejected) as error:
            if generation is not None:
                try:
                    generation.close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
            reason = getattr(error, "reason", None) or str(error)
            self._finish_publish(False,
                                 "publish switch rejected: %s" % reason)
            return
        with self._condition:
            if self._closed:
                try:
                    generation.close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
                self._finish_publish(False, "delta machine is closed")
                return
            self._generation = generation
            self._generations.append(generation)
            self._provider = provider
            self._base_commits = base_commits
            self._delta_events = checkpoint["events"]
            self._retractions = checkpoint["retractions"]
            self._delta_consumed = checkpoint["consumed"]
            self._delta_change_seq = checkpoint["change_seq"]
            self._delta_path = checkpoint_path
            self._declared_generation_id = generation_id
            # A publish is a representation/config change: any deterministic
            # catch-up block of the old identity no longer applies, and a
            # #66 refuse-load is cleared by a freshly published, fully
            # verified generation (a valid active now exists).
            self._blocked = None
            self._refuse_reason = None
            self._snapshot = snapshot
            self._condition.notify_all()
        self._finish_publish(True, None)

    def _finish_publish(self, ok, error):
        with self._condition:
            self._pending_publish = None
            self._publish_result = (ok, error)
            self._condition.notify_all()

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
        with self._condition:
            if self._refuse_reason is not None:
                # #66 refuse-load: the active identity is unknown / broken /
                # missing a compat declaration.  Requests fail closed
                # (pass-through), never a silent fallback to the
                # config-declared active (SCN-66-10).
                raise EvidenceError(
                    "active_identity_refused", self._refuse_reason)
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

    def snapshot_representation_id(self):
        """The representation identity currently served (#65).

        Follows the published snapshot so the evidence service's config
        identity switches exactly when the served identity switches; falls
        back to the configured provider while no snapshot is published.
        """
        with self._condition:
            snapshot = self._snapshot
            if snapshot is not None:
                return snapshot.representation_id
            return self._provider.representation_id()

    def delta_checkpoint_path(self):
        """The active checkpoint path (follows rebuilds and publish
        switches, so operators and tests always address the served
        checkpoint)."""
        with self._condition:
            return self._delta_path

    # ------------------------------------------------------------------
    # Dirty scheduling and compaction (#67)
    # ------------------------------------------------------------------

    def set_compaction_trigger(self, trigger):
        """Wire the compaction trigger (the staging machine's
        ``request_compaction``).  The worker calls it when the delta crosses
        the soft/hard-dirty thresholds so the single staging builder can
        compact the active fingerprint (spec "一次只运行一个 builder")."""
        if trigger is not None and not callable(trigger):
            raise DeltaError("compaction trigger must be callable or None")
        with self._condition:
            self._compaction_trigger = trigger

    def dirty_state(self):
        """The dirty-scheduling state of the served delta (#67, AC67-1).

        Counts new vectors + tombstones against the base active row count of
        the current generation -- recomputed from the in-memory mirror and
        the checkpoint size, never a directory scan of old generations
        (seam 5):

        - ``soft_dirty``: changes >= max(soft_dirty_min_changes,
          soft_dirty_ratio * base_rows) -> compact when the daemon is idle.
        - ``hard_dirty``: changes >= hard_dirty_changes OR the checkpoint
          (incl. WAL sidecars) >= hard_dirty_bytes -> compact even under
          input, at low priority.
        """
        with self._condition:
            generation = self._generation
            delta_events = len(self._delta_events)
            retractions = len(self._retractions)
            delta_path = self._delta_path
        base_rows = generation.row_count if generation is not None else 0
        changes = delta_events + retractions
        soft = max(self._soft_dirty_min_changes,
                   int(self._soft_dirty_ratio * base_rows))
        delta_bytes = 0
        if delta_path:
            for suffix in ("", "-wal", "-shm"):
                try:
                    delta_bytes += os.path.getsize(delta_path + suffix)
                except OSError:
                    pass
        return {
            "base_rows": base_rows,
            "delta_changes": changes,
            "soft_threshold": soft,
            "soft_dirty": changes >= soft,
            "hard_dirty": (changes >= self._hard_dirty_changes
                           or delta_bytes >= self._hard_dirty_bytes),
            "hard_changes_threshold": self._hard_dirty_changes,
            "hard_bytes_threshold": self._hard_dirty_bytes,
            "delta_bytes": delta_bytes,
        }

    def force_rebuild_requested(self):
        """True when recovery found no healthy rollback (AC67-6).

        The config seam reads this to force the staging machine's background
        rebuild-from-facts; the semantic path fails closed meanwhile.
        """
        with self._condition:
            return self._force_rebuild_requested

    def refuse_reason(self):
        """The current refuse-load reason, or None when the machine serves
        (or is merely blocked).  The config seam uses this (not the
        manifest-level resolution) to decide the staging machine's gate,
        because the delta machine's rollback recovery may have cleared a
        manifest-level refusal."""
        with self._condition:
            return self._refuse_reason

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
            if self._pending_publish is not None:
                self._pending_publish = None
                self._publish_result = (
                    False, "publish aborted by derived-state invalidation")
                self._condition.notify_all()
            else:
                self._publish_result = None
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
                "delta_refuse_reason": self._refuse_reason,
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

def build_delta_machine_from_config(facts_root, config, builder_lock=None,
                                    active_generation_id=None,
                                    active_representation_id=None,
                                    refuse_reason=None):
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
    ``builder_lock`` (#64) is the shared single-builder lease: the machine's
    rebuild path acquires it around every generation build so it never
    embeds concurrently with the staging machine.

    ``active_generation_id`` / ``active_representation_id`` (#65) override
    the config's declared active with the durable active manifest (the
    runtime publish replaces the active without any config edit, so the
    manifest -- not the config -- is the source of truth for what is
    active after a restart).  The representation override is what lets the
    fixture seam serve the published representation; the real hidden-state
    provider plugs at the same seam.

    ``refuse_reason`` (#66) refuses the load of derived state (a present-but-
    invalid / unknown active manifest): the machine never falls back to the
    config-declared active; requests fail closed with
    ``active_identity_refused`` and status reports the refusal.
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
        if active_generation_id is not None:
            if not isinstance(active_generation_id, str) \
                    or not active_generation_id:
                raise ValueError("active_generation_id must be a non-empty "
                                 "string")
            generation_id = active_generation_id
        representation_id = config["representation_id"]
        if (not representation_id or not isinstance(representation_id, str)):
            raise ValueError("representation_id must be a non-empty string")
        if active_representation_id is not None:
            if not isinstance(active_representation_id, str) \
                    or not active_representation_id:
                raise ValueError("active_representation_id must be a "
                                 "non-empty string")
            representation_id = active_representation_id
        deadline = float(config.get("catch_up_deadline_ms", 5000)) / 1000.0
        poll = float(config.get("poll_interval_ms", 500)) / 1000.0
        if deadline <= 0 or poll <= 0:
            raise ValueError("deadlines must be positive")
        # #67 pre-build space budget (spec #43 disk gate); the default
        # applies when the config does not declare one.
        from retention import DEFAULT_DERIVED_DISK_BUDGET_BYTES
        budget = config.get("derived_disk_budget_bytes",
                            DEFAULT_DERIVED_DISK_BUDGET_BYTES)
        try:
            budget = int(budget)
        except (TypeError, ValueError) as error:
            raise ValueError("malformed derived_disk_budget_bytes: %s"
                             % error)
        if budget < 0:
            raise ValueError("derived_disk_budget_bytes must be non-negative")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed delta config: %s" % error)
    provider = _build_provider_from_config(config,
                                           representation_id=representation_id)
    return DeltaStateMachine(facts_root, derived_root, provider,
                             generation_id, catch_up_deadline=deadline,
                             poll_interval=poll, builder_lock=builder_lock,
                             refuse_reason=refuse_reason,
                             disk_budget_bytes=budget)


def _build_provider_from_config(config, representation_id=None):
    """The injectable representation seam behind the config (mirrors evidence.py).

    Kept here (not imported from evidence.py) to avoid a module-level import
    cycle: delta.py already imports evidence.py for the seam and the faults.
    ``representation_id`` (#65) overrides the config's declared id so the
    active manifest's published representation can be served.
    """
    from evidence import FixtureRepresentationProvider
    try:
        representation_id = representation_id or config["representation_id"]
        kind = config.get("provider_kind", "fixture")
        if kind == "seed_vectors":
            from seed_vectors import build_seed_provider_from_config
            return build_seed_provider_from_config(config)
        if kind != "fixture":
            raise EvidenceError(
                "evidence_unavailable",
                "unknown provider_kind %r (expected fixture or seed_vectors)"
                % kind)
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
