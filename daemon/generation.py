#!/usr/bin/env python3
"""Immutable shadow generation containers (Habit130/squirrel#62).

Given the immutable selection facts in a facts.sqlite3 store and an injected
deterministic representation provider (the #61 ``RepresentationProvider``
seam; a real hidden-state provider behind it in ``hidden_state.py``), the
builder produces a fully self-describing, byte-deterministic generation of
row-major FP32 event vectors and publishes it under ``generations/``.

Container layout (spec #43 "Generation 与精确 oracle"):

    <derived_root>/staging/<generation_id>/      in-progress / blocked builds
        progress.json                            transient progress manifest
        manifest.json                            final manifest (written once)
        metadata.json                            read-only row mapping
        vectors.fp32                             row-major little-endian FP32
    <derived_root>/generations/<generation_id>/  immutable published generation
        manifest.json, metadata.json, vectors.fp32

Identity composition (AC62-2 / spec "每代绑定..."):

- ``generation_id = shadow-gen-v1:<sha256(identity + rows_fingerprint)>``;
  the identity covers ``store_epoch``, the source HLC watermark ``H0``, the
  complete ``representation_id``, the vector dimension and format, the
  builder version, and the retrieval backend and its parameters.  The rows
  fingerprint covers the deterministic ordered active-event list, so two
  builds from the same snapshot and identity produce the same id and
  byte-identical files (SCN-62-1 / SCN-62-5).
- ``manifest.files`` carries size + sha256 for every published file except
  the manifest itself, whose checksum is the hash of its canonical
  serialization without that self entry.  ``manifest.chunks`` records each
  build chunk's row range, byte count and sha256, exactly as the spec's
  chunked staging build prescribes; the chunk checksums are re-verified at
  reopen.
- ``metadata.json`` is the read-only ``row -> event`` projection: every row
  binds event_id, the derived choice problem key, the final selection
  candidate text and the event HLC.  The mapping is verified as a bijection
  (row == index, distinct event ids) at reopen (AC62-3).

Determinism and failure semantics:

- The event list is the active set as of ``H0`` ordered by
  ``(hlc, event_id)`` -- the same projection the canonical oracle computes
  on, read inside one read-only SQLite transaction.  The store identity is
  re-read at the end of the snapshot read and again before publish; a
  changed epoch or watermark invalidates the staging (spec "构建期间 epoch
  改变时整次 staging 作废").
- A deterministic parse, representation or model error names the blocking
  event(s) in ``progress.json`` (``status: blocked``) and raises
  ``BuildBlockedError``; nothing is silently skipped (SCN-62-7).
- Reopen (``open_generation``) re-verifies every file: checksums, chunk
  records, the row/event bijection, finiteness and unit norm of every
  vector, and the fixed exact-oracle probes recorded in the manifest (the
  probes recompute entirely from the container, without the facts store).
  Any failure raises ``GenerationRejected``; a corrupt or identity-unknown
  generation is never loaded as an empty memory (SCN-62-3).
- ``replay_exact`` replays one query against the container and the facts:
  it pins the oracle's as-of point to the generation's watermark, requires
  the facts epoch to match and the container event set to equal the facts'
  active set at ``H0``, and serves vectors from the mmap'd FP32 file, so the
  evidence is bit-identical to the canonical oracle on the same vectors
  (SCN-62-4).

The #64 resumable staging machine (``staging.py``) reuses the shared build
core below (``_read_snapshot`` / ``_prepare_target`` / ``_build_chunks`` /
``_compute_probes`` / ``_compose_manifest``), so a staged build and a
one-shot ``build_generation`` of the same target produce the same
generation id and byte-identical files.
"""

import hashlib
import json
import math
import mmap
import os
import sqlite3
import struct
import tempfile

from compat import (  # noqa: E402
    EXACT_BACKEND,
    FP32_ROW_MAJOR_LE,
    SUPPORTED_BACKENDS,
    compose_backend_fingerprint,
    compose_index_fingerprint,
)
from evidence import (EvidenceError, RepresentationProvider)
from oracle import (FactReader, OracleError, OracleParams, OracleQuery,
                    StoredEvent, choice_problem_key, compute_evidence)

BUILD_VERSION = "shadow-generation-builder-v1"
MANIFEST_VERSION = "shadow-generation-manifest-v1"
PROGRESS_VERSION = "shadow-generation-progress-v1"
GENERATION_ID_PREFIX = "shadow-gen-v1"
VECTOR_FORMAT = FP32_ROW_MAJOR_LE
RETRIEVAL_BACKEND = EXACT_BACKEND
RETRIEVAL_PARAMS = {}
# #66: the projection semantics of the served active state (row projection,
# retraction handling, choice-problem keys, HLC metadata interpretation).
# Bound into every generation identity so a projection change is a comparable
# identity change, not a forever-constant (executor decision; SCN-66-3/4).
PROJECTION_VERSION = "delta-schema-v1+generation-manifest-v1"
# Spec #43: builder 按确定事件清单分块构建,每块记录 row 范围和 checksum.
CHUNK_ROWS = 256
# Fixed exact-oracle probes recorded in the manifest (spec "精确 oracle 和
# ANN 固定探针"; ANN deferred to #78/#79).  The probe params are a
# verification fixture, not a winner declaration.
PROBE_COUNT = 4
PROBE_PARAMS = OracleParams(tau=0.0, k_evidence=8, half_life=float("inf"),
                            saturation_k=1.0)
# L2 unit-norm tolerance: vectors are stored FP32, so a few ulps of rounding
# are legitimate; anything beyond that is a dirty vector.
UNIT_NORM_TOLERANCE = 1e-3

GENERATION_FILES = ("manifest.json", "metadata.json", "vectors.fp32")
PROGRESS_FILENAME = "progress.json"


class GenerationError(Exception):
    """Base fault of the generation path (never an empty-memory result)."""


class GenerationRejected(GenerationError):
    """A generation exists but cannot be trusted; it must not be loaded.

    Carries a ``reason`` string describing the first failing check, so
    diagnosis points at the concrete mismatch (checksum, identity, event
    set, vector, probe).
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class BuildError(GenerationError):
    """The build could not start or finish."""


class BuildTargetExistsError(BuildError):
    """The identical generation (or its staging) already exists.

    The spec's rebuild path is explicit deletion then rebuild (SCN-62-5);
    the builder never silently overwrites immutable state.
    """


class BuildEpochChangedError(BuildError):
    """The fact store identity changed during the build.

    Spec #43: a changed epoch or source watermark during the build makes the
    whole staging build invalid; the staging directory is marked discarded.
    """


class BuildBlockedError(BuildError):
    """A deterministic error blocked the build; the blocking event is named.

    ``blocked_events`` are the event ids that could not be represented; the
    build must not skip them and must not publish a partial generation.
    """

    def __init__(self, message, blocked_events, phase="vector"):
        super().__init__(message)
        self.message = message
        self.blocked_events = tuple(blocked_events)
        self.phase = phase


class BuildProgressError(BuildError):
    """A recorded progress manifest cannot be trusted.

    The staging machine discards the whole staging on this fault: a build
    whose recorded chunk checksums no longer match the vectors file (or
    whose records are structurally invalid) is never resumed in part
    (SCN-64-3 "四要素一致才续跑"; verified chunks only).
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Canonical serialization and fingerprints
# ---------------------------------------------------------------------------

def _canonical_json(value):
    """Byte-deterministic JSON: sorted keys, compact separators.

    Used for every fingerprint and for the files themselves, so identical
    builds produce byte-identical containers.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _sha256_hex(content):
    return hashlib.sha256(content).hexdigest()


def _metadata_row(event_id, key, candidate, hlc):
    return {
        "event_id": event_id,
        "choice_problem_key": [key[0], key[1], key[2]],
        "candidate": candidate,
        "hlc": [hlc[0], hlc[1]],
    }


def _rows_fingerprint(rows):
    """sha256 over the canonical ordered row projection.

    ``rows`` are the ``_metadata_row`` dicts in build (row) order.  The
    fingerprint is recomputed from ``metadata.json`` at reopen, so a drifted
    event list is a container-identity mismatch, never a silent change.
    """
    payload = _canonical_json([
        {key: row[key] for key in ("event_id", "choice_problem_key",
                                   "candidate", "hlc")}
        for row in rows
    ])
    return _sha256_hex(payload.encode("utf-8"))


def _compose_generation_id(identity, rows_fingerprint):
    payload = _canonical_json(identity) + "\0" + rows_fingerprint
    return "%s:%s" % (
        GENERATION_ID_PREFIX,
        _sha256_hex(payload.encode("utf-8"))[:32])


def _probe_results_fingerprint(result):
    """sha256 over the canonical numeric decomposition of an oracle result.

    Uses %.17g (exact double round-trip) and the event ids of the kept
    contributions; recomputation at reopen must reproduce it bit for bit.
    """
    lines = [
        "same_key_active=%d" % result.same_key_active,
        "total_mass=%.17g" % result.total_mass,
    ]
    for candidate in result.candidates:
        lines.append("candidate=%d:m=%.17g:s=%.17g" % (
            candidate.index, candidate.m, candidate.s))
    for kept in result.kept:
        lines.append("kept=%s:cos=%.17g:r=%.17g:age=%d:d=%.17g:a=%.17g"
                     ":match=%d" % (
                         kept.event_id, kept.cosine, kept.relevance,
                         kept.usage_age, kept.age_factor, kept.weight,
                         kept.matched_candidate))
    return _sha256_hex("\n".join(lines).encode("utf-8"))


# ---------------------------------------------------------------------------
# Fact snapshot reading (read-only, consistent, immutable)
# ---------------------------------------------------------------------------

def _read_fact_identity(conn):
    rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    store_epoch = rows.get("store_epoch")
    try:
        physical = int(rows.get("hlc_physical_ms", "-1"))
        logical = int(rows.get("hlc_logical", "-1"))
    except (TypeError, ValueError) as error:
        raise BuildError("fact store meta clock is malformed") from error
    if not store_epoch or physical < 0 or logical < 0:
        raise BuildError("fact store identity is incomplete")
    return store_epoch, (physical, logical)


def _read_active_event_rows(conn, hlc):
    """The deterministic ordered active-event projection as of ``hlc``.

    Same SQL shape as the canonical oracle's ``FactReader`` (same at-or-before
    commit/retraction semantics, same ordering) plus the raw ``preceding_text``
    the representation provider needs to recompute the event vector from
    facts.
    """
    physical, logical = hlc
    try:
        rows = conn.execute(
            "SELECT e.event_id, e.commit_id, e.schema_id,"
            " e.canonical_segment_input, e.category,"
            " e.final_selection_text, e.preceding_text,"
            " e.hlc_physical_ms, e.hlc_logical"
            " FROM selection_events e"
            " WHERE (e.hlc_physical_ms < ?1 OR (e.hlc_physical_ms = ?1"
            "        AND e.hlc_logical <= ?2))"
            " AND NOT EXISTS(SELECT 1 FROM retractions r"
            "                WHERE r.commit_id = e.commit_id"
            "                  AND (r.hlc_physical_ms < ?1"
            "                       OR (r.hlc_physical_ms = ?1"
            "                           AND r.hlc_logical <= ?2)))"
            " ORDER BY e.hlc_physical_ms, e.hlc_logical, e.event_id;",
            (physical, logical)).fetchall()
    except sqlite3.Error as error:
        raise BuildError("fact store query failed: %s" % error)
    events = []
    for row in rows:
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
    return events


def _competition_candidates(conn, event_id):
    """The materialized competition set in original merge order (probes only)."""
    try:
        rows = conn.execute(
            "SELECT text FROM selection_candidates WHERE event_id = ?"
            " ORDER BY merge_order;", (event_id,)).fetchall()
    except sqlite3.Error as error:
        raise BuildError("fact store query failed: %s" % error)
    return [row["text"] for row in rows]


def _open_fact_store(facts_root):
    db_path = os.path.join(facts_root, "facts.sqlite3")
    if not os.path.isfile(db_path):
        raise BuildError("fact store not found: %s" % db_path)
    try:
        # Read-only open semantics (AC-65-v1 repair): sqlite 3.54.0 returns
        # SQLITE_CANTOPEN for a ``file:...?mode=ro`` URI open of a WAL
        # store with an active in-process writer (3.53.3 succeeds; see
        # docs/publish-atomic.md).  Open the plain path and enforce
        # read-only in the engine with ``PRAGMA query_only=ON`` (every
        # write statement fails with SQLITE_READONLY -- the same
        # fail-closed guarantee, independent of the versioned URI
        # behavior).  The macOS WAL -shm concurrent-open transient
        # (SQLITE_BUSY) is absorbed by a short busy wait.
        conn = sqlite3.connect(db_path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON;")
        return conn
    except sqlite3.Error as error:
        raise BuildError("cannot open fact store: %s" % error)


# ---------------------------------------------------------------------------
# The vector file (row-major FP32, mmap-able, no second resident copy)
# ---------------------------------------------------------------------------

class _VectorFile:
    """Random access over the canonical row-major FP32 vector file.

    ``vector(row)`` reads one row through mmap without copying the whole
    file; the file itself has no header -- dimension, row count and format
    live in the manifest, which is what makes the file directly mmap-able
    (spec "规范 FP32 向量文件采用 row-major 布局,可通过 mmap 使用").
    """

    def __init__(self, path, rows, dimension):
        self._path = path
        self._rows = rows
        self._dimension = dimension
        self._row_bytes = dimension * 4
        self._mm = None
        if rows > 0:
            size = os.path.getsize(path)
            if size != rows * self._row_bytes:
                raise GenerationRejected(
                    "vectors file size %d does not match %d rows x %d dims"
                    % (size, rows, dimension))
            with open(path, "rb") as handle:
                # ACCESS_COPY: the Accelerate backend (#72) reads the file
                # through a ctypes writable-buffer view (copy-on-write) so it
                # can hand the matrix address to vecLib without ever writing
                # back; physical pages stay shared read-only until written.
                self._mm = mmap.mmap(handle.fileno(), 0,
                                     access=mmap.ACCESS_COPY)

    def vector(self, row):
        if not (0 <= row < self._rows):
            raise GenerationRejected(
                "row %d out of range (rows=%d)" % (row, self._rows))
        if self._mm is None:
            return ()
        return struct.unpack_from("<%df" % self._dimension,
                                  self._mm, row * self._row_bytes)

    def buffer(self):
        """The raw read-only mmap buffer (None for a zero-row file)."""
        return self._mm

    def close(self):
        if self._mm is not None:
            try:
                self._mm.close()
            except Exception:  # noqa: BLE001 - best effort on close
                pass
            self._mm = None


# ---------------------------------------------------------------------------
# Oracle probe computation (self-contained, no facts store at reopen)
# ---------------------------------------------------------------------------

class _ProjectionReader:
    """Read-only stand-in over the generation's stored event projection.

    The stored rows are exactly the active events as of the source watermark,
    so the container's fixed oracle probes recompute without touching the
    facts store (spec "重新打开全部文件,验证...精确 oracle 固定探针").
    """

    def __init__(self, events):
        self._events = list(events)

    def read_active_events(self, as_of=None):
        return list(self._events)

    def default_as_of(self):
        raise OracleError("projection reader has no clock")

    def close(self):
        pass


def _compute_probe(probe, events, vfile, row_index, params, as_of):
    """Run the canonical oracle on the container's projection for one probe."""
    query = OracleQuery(
        schema_id=probe["schema_id"],
        canonical_segment_input=probe["canonical_segment_input"],
        candidates=list(probe["candidates"]),
        query_vector=list(probe["query_vector"]),
        category=probe.get("category", "word"),
        as_of=as_of,
    )

    def vector_for(event_id):
        row = row_index.get(event_id)
        if row is None:
            raise OracleError("no stored row for probe event %s" % event_id)
        return vfile.vector(row)

    reader = _ProjectionReader(events)
    try:
        return compute_evidence(reader, params, query, vector_for)
    finally:
        reader.close()


def _probe_params_dict(params):
    return {"tau": params.tau, "k_evidence": params.k_evidence,
            "half_life": params.half_life, "saturation_k": params.saturation_k}


def _probe_params_from_dict(value):
    return OracleParams(tau=float(value["tau"]),
                        k_evidence=int(value["k_evidence"]),
                        half_life=float(value["half_life"]),
                        saturation_k=float(value["saturation_k"]))


# ---------------------------------------------------------------------------
# Staging I/O helpers (owner-only, fsynced, atomically advanced)
# ---------------------------------------------------------------------------

def _write_file(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    try:
        view = memoryview(content) if isinstance(content, bytes) else content
        written = 0
        while written < len(view):
            written += os.write(fd, view[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path, content):
    """Atomic replacement with fsync (used for the progress manifest)."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        view = memoryview(content) if isinstance(content, bytes) else content
        written = 0
        while written < len(view):
            written += os.write(fd, view[written:])
        os.fsync(fd)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        _fsync_directory(directory)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _fsync_directory(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json_file(path, label):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as error:
        raise GenerationRejected("%s: cannot read/parse: %s" % (label, error))
    if not isinstance(value, dict):
        raise GenerationRejected("%s: must be a JSON object" % label)
    return value


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------

def _validate_event(stored):
    """Structural parse validation; a violation blocks with the event named."""
    if not stored.event_id or not isinstance(stored.event_id, str):
        return "empty event_id"
    for label, value in (
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


def _mark_progress(staging_dir, progress):
    _write_atomic(os.path.join(staging_dir, PROGRESS_FILENAME),
                  _canonical_json(progress).encode("utf-8"))


def _mark_blocked(staging_dir, generation_id, blocked_events, reason, phase):
    _mark_progress(staging_dir, {
        "progress_version": PROGRESS_VERSION,
        "generation_id": generation_id,
        "status": "blocked",
        "total_rows": None,
        "chunks": [],
        "blocked_events": list(blocked_events),
        "reason": reason,
        "phase": phase,
    })


def _mark_discarded(staging_dir, generation_id, reason):
    _mark_progress(staging_dir, {
        "progress_version": PROGRESS_VERSION,
        "generation_id": generation_id,
        "status": "discarded",
        "total_rows": None,
        "chunks": [],
        "reason": reason,
    })


def _check_identity_unchanged(facts_root, store_epoch, source_hlc):
    conn = _open_fact_store(facts_root)
    try:
        now_epoch, now_hlc = _read_fact_identity(conn)
    finally:
        conn.close()
    if now_epoch != store_epoch or now_hlc != source_hlc:
        raise BuildEpochChangedError(
            "fact store identity changed during the build "
            "(%s/%s -> %s/%s)" % (store_epoch, source_hlc, now_epoch, now_hlc))


# ---------------------------------------------------------------------------
# Shared build core (used by build_generation and the #64 staging machine)
# ---------------------------------------------------------------------------
#
# The resumable staging machine (#64) and the one-shot builder share every
# step that determines container bytes, so a staged build and a direct build
# of the same target produce the same generation id and byte-identical
# files (spec "并发重建与蓝绿发布"; determinism across both paths).

def _read_snapshot(facts_root, as_of=None):
    """(store_epoch, source_hlc, events) on one consistent read-only snapshot.

    ``as_of=None`` pins the source watermark to the store's current clock
    and requires that clock unchanged across the read (the #62 guarantee:
    the builder fixes ``H0`` on a consistent snapshot).  A caller-provided
    ``as_of`` reads the active projection at that fixed watermark instead;
    only the epoch must stay unchanged during the read -- facts are
    immutable within one epoch, so the pinned projection is stable even
    while new facts commit (the staging machine's resume path).
    """
    conn = _open_fact_store(facts_root)
    pinned = as_of is not None
    try:
        conn.execute("BEGIN")
        store_epoch, current_hlc = _read_fact_identity(conn)
        if as_of is None:
            as_of = current_hlc
        events = _read_active_event_rows(conn, as_of)
        after_epoch, after_hlc = _read_fact_identity(conn)
        conn.execute("COMMIT")
    except sqlite3.Error as error:
        raise BuildError("fact store read failed: %s" % error)
    finally:
        conn.close()
    if after_epoch != store_epoch:
        raise BuildEpochChangedError(
            "fact store epoch changed during the snapshot read (%s -> %s)"
            % (store_epoch, after_epoch))
    if not pinned and after_hlc != current_hlc:
        raise BuildEpochChangedError(
            "fact store identity changed during the snapshot read "
            "(%s/%s -> %s/%s)" % (store_epoch, current_hlc, after_epoch,
                                  after_hlc))
    return store_epoch, as_of, events


def _prepare_target(events, provider, store_epoch, source_hlc,
                    projection_version=PROJECTION_VERSION,
                    index_fingerprint=None, rebuild_tag=None,
                    retrieval_backend=RETRIEVAL_BACKEND,
                    retrieval_params=RETRIEVAL_PARAMS):
    """The deterministic build target over one frozen snapshot.

    Validates every event (a violation blocks with the event named), derives
    the ordered row projection and the rows fingerprint, and composes the
    container identity and generation id (spec: staging 固定目标 epoch、H0、
    全部 fingerprints、builder 版本与确定事件清单).  Returns a dict with
    ``rows``, ``rows_fingerprint``, ``identity`` and ``generation_id``.

    ``projection_version`` and ``index_fingerprint`` are the #66 layered
    identity fields (spec "分层兼容身份"): they are bound into the generation
    identity (and therefore the content-addressed generation id), so a
    projection or index-fingerprint change produces a different generation
    and the compatibility matrix can compare them item by item.  The default
    values are the daemon's current projection semantics and the composed
    exact-only index fingerprint; the staging machine passes the desired
    values from its config seam.

    ``retrieval_backend`` / ``retrieval_params`` (#72) name the exact
    retrieval implementation that interprets the canonical FP32 file
    (``exact`` oracle or ``accelerate-cblas-sgemv``).  They are bound into the
    identity AND the index fingerprint (SCN-72-4), so an Accelerate build
    mints a different generation id than the oracle build of the same facts.

    ``rebuild_tag`` (Squirrel#68) is the explicit-rebuild nonce: ``None``
    keeps the fully content-addressed target, while an explicit ``--full``
    rebuild passes a fresh tag so the SAME fingerprint mints a NEW
    generation id (spec: 只有显式 full 为同一 fingerprint 创建新代).  The
    tag is part of the generation identity but NOT one of the compatibility
    matrix's orthogonal layers, so a tagged full rebuild of an identical
    active is still an explicit build -- never a matrix no-op -- and the
    resulting generation remains fully compatible with the active layers.
    """
    if retrieval_backend not in SUPPORTED_BACKENDS:
        raise BuildError("unsupported retrieval backend %r"
                         % (retrieval_backend,))
    rows = []
    for stored in events:
        problem = _validate_event(stored)
        if problem is not None:
            raise BuildBlockedError(
                "cannot build generation: %s (event %s)"
                % (problem, stored.event_id), [stored.event_id],
                phase="parse")
        key = choice_problem_key(stored.schema_id, stored.category,
                                 stored.canonical_segment_input)
        rows.append(_metadata_row(stored.event_id, key,
                                  stored.final_selection_text, stored.hlc))
    fingerprint = _rows_fingerprint(rows)
    if index_fingerprint is None:
        # The backend's library/ABI version is bound here (SCN-72-4): an
        # Accelerate build must never carry the oracle's ``oracle-exact-v1``
        # library version, even though the backend token already differs.
        # ``compose_backend_fingerprint`` binds the per-backend library
        # version; ``compose_index_fingerprint`` with the default version
        # would be a fingerprint forgery for the Accelerate backend.
        index_fingerprint = compose_backend_fingerprint(
            backend=retrieval_backend, params=retrieval_params)
    identity = {
        "store_epoch": store_epoch,
        "source_hlc": [source_hlc[0], source_hlc[1]],
        "representation_id": provider.representation_id(),
        "vector_dimension": provider.vector_dimension(),
        "vector_format": VECTOR_FORMAT,
        "projection_version": projection_version,
        "index_fingerprint": index_fingerprint,
        "builder_version": BUILD_VERSION,
        "retrieval_backend": retrieval_backend,
        "retrieval_params": retrieval_params,
    }
    if rebuild_tag is not None:
        identity["rebuild_tag"] = rebuild_tag
    generation_id = _compose_generation_id(identity, fingerprint)
    return {
        "rows": rows,
        "rows_fingerprint": fingerprint,
        "identity": identity,
        "generation_id": generation_id,
    }


def _build_chunks(staging_dir, vectors_path, events, provider, dimension,
                  chunk_rows, generation_id, progress, start_row=0,
                  prefix_digest=None, chunk_limit=None, vector_source=None):
    """Embed vector chunks [start_row, ...) and advance progress.

    ``start_row`` is the first row NOT yet covered by a verified chunk
    record; when it is > 0 the file is truncated to ``start_row`` rows
    first (a crash mid-chunk leaves garbage after the last committed
    chunk) and embedding continues from there.  ``prefix_digest`` must be
    the sha256 hash object over the verified prefix when resuming (None
    from scratch); it is copied so the returned whole-file digest covers
    the prefix plus the newly written bytes.  ``chunk_limit`` bounds the
    number of chunks embedded in one call (the staging machine embeds one
    chunk per state-machine cycle, so every intermediate state is a
    crashable resting state).  Every chunk is fsynced before the progress
    manifest is atomically advanced, so a crash at any point resumes from
    the last verified chunk.  Returns ``(chunks, full_sha256)`` where
    ``chunks`` are the newly written records; ``full_sha256`` covers the
    whole file.

    ``vector_source`` (#66) is the #66 reuse seam: a callable
    ``(stored) -> vector`` that the matrix may substitute for the provider's
    ``event_vector`` when the compatibility matrix explicitly permits vector
    reuse (projection-only change with identical representation and verified
    old checksums, or a registered tested-equivalent format converter).  When
    None, the provider embeds as before.  A ``vector_source`` that raises
    ``EvidenceError`` blocks the build naming the event, exactly like a
    provider fault -- reuse is never a silent fallback.
    """
    chunks = []
    full_sha = prefix_digest.copy() if prefix_digest else hashlib.sha256()
    flags = os.O_WRONLY | os.O_NOFOLLOW
    if start_row == 0:
        flags |= os.O_CREAT | os.O_EXCL
    vector_fd = os.open(vectors_path, flags, 0o600)
    try:
        if start_row > 0:
            os.ftruncate(vector_fd, start_row * dimension * 4)
            os.lseek(vector_fd, 0, os.SEEK_END)
        start = start_row
        embedded = 0
        while start < len(events):
            if chunk_limit is not None and embedded >= chunk_limit:
                break
            end = min(start + chunk_rows, len(events))
            buffers = []
            for stored in events[start:end]:
                event_id = stored.event_id
                try:
                    if vector_source is not None:
                        vector = vector_source(stored)
                    else:
                        vector = provider.event_vector(stored)
                except EvidenceError as error:
                    raise BuildBlockedError(
                        "cannot build generation: %s (event %s)"
                        % (error.message, event_id), [event_id],
                        phase="vector")
                except Exception as error:  # noqa: BLE001 - fail closed
                    raise BuildBlockedError(
                        "cannot build generation: representation error for "
                        "event %s: %s" % (event_id, error), [event_id],
                        phase="vector")
                problem = _validate_vector(vector, dimension)
                if problem is not None:
                    raise BuildBlockedError(
                        "cannot build generation: dirty vector for event %s: "
                        "%s" % (event_id, problem), [event_id],
                        phase="vector")
                buffers.append(struct.pack("<%df" % dimension,
                                           *[float(v) for v in vector]))
            chunk_bytes = b"".join(buffers)
            view = memoryview(chunk_bytes)
            written = 0
            while written < len(view):
                written += os.write(vector_fd, view[written:])
            full_sha.update(chunk_bytes)
            record = {"start_row": start, "end_row": end,
                      "bytes": len(chunk_bytes),
                      "sha256": _sha256_hex(chunk_bytes)}
            chunks.append(record)
            progress["chunks"].append(record)
            _mark_progress(staging_dir, progress)
            os.fsync(vector_fd)
            embedded += 1
            start = end
    finally:
        os.close(vector_fd)
    return chunks, full_sha.hexdigest()


def _verify_progress_chunks(progress, vectors_path, dimension):
    """Re-verify the recorded chunk records against the vectors file.

    Returns ``(next_row, prefix_digest)``: ``next_row`` is the first row
    after the last fully verified chunk (the resume point) and
    ``prefix_digest`` the sha256 hash object over the verified prefix (the
    builder copies it to extend the final whole-file checksum).  Raises
    ``BuildProgressError`` on the first structural or checksum mismatch --
    a staging whose progress cannot be re-verified is discarded in full,
    never resumed in part.
    """
    chunks = progress.get("chunks")
    if not isinstance(chunks, list):
        raise BuildProgressError("progress chunks are not a list")
    row_bytes = dimension * 4
    digest = hashlib.sha256()
    if not chunks:
        # No chunks recorded yet (fresh build): nothing to verify, and the
        # vectors file may not even exist -- the first embed creates it.
        return 0, digest
    next_row = 0
    try:
        handle = open(vectors_path, "rb")
    except OSError as error:
        raise BuildProgressError("cannot open the staging vectors file: %s"
                                 % error)
    try:
        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                raise BuildProgressError("chunk %d is not an object" % index)
            start = chunk.get("start_row")
            end = chunk.get("end_row")
            if not (isinstance(start, int) and isinstance(end, int)
                    and 0 <= start < end and start == next_row):
                raise BuildProgressError("chunk %d row range invalid" % index)
            if chunk.get("bytes") != (end - start) * row_bytes:
                raise BuildProgressError(
                    "chunk %d byte count mismatch" % index)
            expected = chunk.get("sha256")
            if not isinstance(expected, str) or not expected:
                raise BuildProgressError("chunk %d checksum missing" % index)
            handle.seek(start * row_bytes)
            data = handle.read((end - start) * row_bytes)
            if len(data) != (end - start) * row_bytes:
                raise BuildProgressError("chunk %d is truncated" % index)
            if _sha256_hex(data) != expected:
                raise BuildProgressError("chunk %d checksum mismatch" % index)
            digest.update(data)
            next_row = end
    finally:
        handle.close()
    return next_row, digest


def _write_metadata(metadata_path, rows):
    _write_file(metadata_path, _canonical_json([
        dict(row, row=index) for index, row in enumerate(rows)
    ]).encode("utf-8"))


def _compute_probes(facts_root, provider, events, rows, vectors_path,
                    dimension, probe_params, source_hlc):
    """The fixed exact-oracle probes over the finished vectors file.

    Recomputes the probe query vectors from the raw 上文 in the facts and
    runs the canonical oracle against the container's own projection, so
    the recorded result fingerprints are reproducible at reopen without the
    facts store.  A deterministic probe fault raises ``BuildBlockedError``
    (phase "probe") naming the event; the caller marks the staging blocked.
    """
    probes = {"params": _probe_params_dict(probe_params), "items": []}
    probe_events = events[:PROBE_COUNT] if PROBE_COUNT > 0 else []
    row_index = {row["event_id"]: index for index, row in enumerate(rows)}
    vfile = None
    try:
        vfile = _VectorFile(vectors_path, len(rows), dimension)
        probe_reader = _open_fact_store(facts_root)
        try:
            for stored in probe_events:
                event_id = stored.event_id
                candidates = _competition_candidates(probe_reader, event_id)
                if not candidates:
                    candidates = [stored.final_selection_text]
                try:
                    query_vector = list(provider.query_vector(
                        stored.preceding_text))
                except EvidenceError as error:
                    raise BuildBlockedError(
                        "cannot build generation: probe query vector for "
                        "event %s: %s" % (event_id, error.message),
                        [event_id], phase="probe")
                except Exception as error:  # noqa: BLE001 - fail closed
                    raise BuildBlockedError(
                        "cannot build generation: probe query vector for "
                        "event %s: %s" % (event_id, error), [event_id],
                        phase="probe")
                probe = {
                    "schema_id": stored.schema_id,
                    "category": stored.category,
                    "canonical_segment_input": stored.canonical_segment_input,
                    "candidates": list(candidates),
                    "query_vector": query_vector,
                }
                result = _compute_probe(probe, events, vfile, row_index,
                                        probe_params, source_hlc)
                probes["items"].append(dict(probe, results_fingerprint=(
                    _probe_results_fingerprint(result))))
        finally:
            probe_reader.close()
    finally:
        if vfile is not None:
            vfile.close()
    return probes


def _compose_manifest(identity, generation_id, rows_fingerprint, row_count,
                      chunks, probes, metadata_path, vectors_path,
                      vectors_sha256):
    """The final manifest bytes (checksums + self-checksum, exactly the #62
    format so a staged build and a direct build are byte-identical)."""
    files = {
        "metadata.json": {"size": os.path.getsize(metadata_path),
                          "sha256": _file_sha256(metadata_path)},
        "vectors.fp32": {"size": os.path.getsize(vectors_path),
                         "sha256": vectors_sha256},
    }
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generation_id": generation_id,
        "identity": identity,
        "rows": {"count": row_count, "fingerprint": rows_fingerprint},
        "chunks": chunks,
        "probes": probes,
        "files": files,
    }
    self_check = dict(manifest)
    self_check["files"] = dict(self_check["files"])
    self_sha = _sha256_hex(_canonical_json(self_check).encode("utf-8"))
    manifest["files"]["manifest.json"] = {"sha256": self_sha}
    return _canonical_json(manifest).encode("utf-8")


def build_generation(facts_root, provider, output_root,
                     chunk_rows=CHUNK_ROWS, probe_params=PROBE_PARAMS,
                     retrieval_backend=RETRIEVAL_BACKEND,
                     retrieval_params=RETRIEVAL_PARAMS):
    """Build and publish one immutable generation over a facts snapshot.

    ``provider`` must be a ``RepresentationProvider`` (the #61 seam) whose
    ``event_vector`` deterministically recomputes the event representation
    from the stored event (including its raw ``preceding_text``) and whose
    ``query_vector`` does the same for probe query text.  The build runs on
    the caller's facts_root read-only; the caller owns the root layout.

    ``retrieval_backend`` (#72) selects the exact retrieval implementation
    that interprets the generated FP32 file (``exact`` or
    ``accelerate-cblas-sgemv``); it is bound into the generation identity and
    index fingerprint (SCN-72-4).  The FP32 file itself is identical for both
    backends (same canonical format, dimension and row order).

    Raises ``BuildBlockedError`` (with the blocking events) on any
    deterministic parse/representation error, ``BuildEpochChangedError`` if
    the store identity changes mid-build, ``BuildTargetExistsError`` if the
    identical generation already exists, and ``GenerationRejected`` if the
    finished staging cannot be re-verified.  Returns the published
    (fully verified) ``Generation``.
    """
    if not isinstance(chunk_rows, int) or chunk_rows < 1:
        raise BuildError("chunk_rows must be a positive integer")
    if not isinstance(provider, RepresentationProvider):
        raise BuildError("provider must be a RepresentationProvider")
    representation_id_value = provider.representation_id()
    if not representation_id_value or not isinstance(
            representation_id_value, str):
        raise BuildError("provider representation_id must be a non-empty "
                         "string")
    dimension = provider.vector_dimension()
    if not isinstance(dimension, int) or dimension < 1:
        raise BuildError("provider vector_dimension must be a positive "
                         "integer")
    if retrieval_backend not in SUPPORTED_BACKENDS:
        raise BuildError("unsupported retrieval backend %r"
                         % (retrieval_backend,))

    store_epoch, source_hlc, events = _read_snapshot(facts_root)
    target = _prepare_target(events, provider, store_epoch, source_hlc,
                             retrieval_backend=retrieval_backend,
                             retrieval_params=retrieval_params)
    rows = target["rows"]
    fingerprint = target["rows_fingerprint"]
    identity = target["identity"]
    generation_id = target["generation_id"]

    staging_dir = os.path.join(output_root, "staging", generation_id)
    published_dir = os.path.join(output_root, "generations", generation_id)
    if os.path.exists(published_dir):
        raise BuildTargetExistsError(
            "generation %s already exists at %s" % (generation_id,
                                                    published_dir))
    if os.path.exists(staging_dir):
        raise BuildTargetExistsError(
            "staging build for %s already exists at %s" % (generation_id,
                                                           staging_dir))
    os.makedirs(staging_dir, mode=0o700)
    vectors_path = os.path.join(staging_dir, "vectors.fp32")
    metadata_path = os.path.join(staging_dir, "metadata.json")
    manifest_path = os.path.join(staging_dir, "manifest.json")

    progress = {
        "progress_version": PROGRESS_VERSION,
        "generation_id": generation_id,
        "status": "running",
        "total_rows": len(rows),
        "chunks": [],
    }
    _mark_progress(staging_dir, progress)

    # -- chunked vector build (spec: 每块记录 row 范围和 checksum) ----------
    try:
        chunks, vectors_sha256 = _build_chunks(
            staging_dir, vectors_path, events, provider, dimension,
            chunk_rows, generation_id, progress)
    except BuildBlockedError as error:
        _mark_blocked(staging_dir, generation_id, error.blocked_events,
                      error.message, error.phase)
        raise

    # -- read-only row metadata ---------------------------------------------
    _write_metadata(metadata_path, rows)

    # -- fixed exact-oracle probes ------------------------------------------
    try:
        probes = _compute_probes(facts_root, provider, events, rows,
                                 vectors_path, dimension, probe_params,
                                 source_hlc)
    except BuildBlockedError as error:
        _mark_blocked(staging_dir, generation_id, error.blocked_events,
                      error.message, error.phase)
        raise

    # -- final manifest -------------------------------------------------------
    manifest_bytes = _compose_manifest(identity, generation_id, fingerprint,
                                       len(rows), chunks, probes,
                                       metadata_path, vectors_path,
                                       vectors_sha256)
    _write_file(manifest_path, manifest_bytes)
    _fsync_directory(staging_dir)

    # -- reopen self-verification (spec clause 6) ----------------------------
    # progress.json is transient build state, not part of the immutable
    # container, so it is removed before the reopen verification and the
    # publish (the verification failure of a completed build is itself the
    # diagnosis record).
    try:
        os.unlink(os.path.join(staging_dir, PROGRESS_FILENAME))
    except OSError:
        pass
    try:
        opened = open_generation(staging_dir)
        opened.close()
    except GenerationRejected as error:
        raise GenerationRejected(
            "staging self-verification failed: %s" % error.reason) from error

    # -- final identity check, then publish (atomic rename) ------------------
    try:
        _check_identity_unchanged(facts_root, store_epoch, source_hlc)
    except BuildEpochChangedError:
        _mark_discarded(staging_dir, generation_id,
                        "store epoch or watermark changed during the build")
        raise
    os.makedirs(os.path.join(output_root, "generations"), mode=0o700,
                exist_ok=True)
    os.rename(staging_dir, published_dir)
    _fsync_directory(os.path.join(output_root, "generations"))
    _fsync_directory(os.path.join(output_root, "staging"))
    return open_generation(published_dir)


# ---------------------------------------------------------------------------
# Reopen and verification
# ---------------------------------------------------------------------------

def _verify_identity(manifest):
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        raise GenerationRejected("manifest: identity missing")
    for key, label in (
            ("store_epoch", "store_epoch"),
            ("representation_id", "representation_id"),
            ("builder_version", "builder_version"),
            ("projection_version", "projection_version"),
            ("index_fingerprint", "index_fingerprint")):
        value = identity.get(key)
        if not isinstance(value, str) or not value:
            raise GenerationRejected(
                "manifest: identity %s missing or empty" % label)
    if identity.get("retrieval_backend") not in SUPPORTED_BACKENDS:
        raise GenerationRejected(
            "manifest: unsupported retrieval backend %r"
            % identity.get("retrieval_backend"))
    if identity.get("vector_format") != VECTOR_FORMAT:
        raise GenerationRejected(
            "manifest: unsupported vector format %r"
            % identity.get("vector_format"))
    dimension = identity.get("vector_dimension")
    if not isinstance(dimension, int) or dimension < 1:
        raise GenerationRejected(
            "manifest: vector_dimension must be a positive integer")
    source_hlc = identity.get("source_hlc")
    if (not isinstance(source_hlc, list) or len(source_hlc) != 2
            or not all(isinstance(value, int) and value >= 0
                       for value in source_hlc)):
        raise GenerationRejected("manifest: source_hlc malformed")
    if not isinstance(identity.get("retrieval_params"), dict):
        raise GenerationRejected("manifest: retrieval_params must be an "
                                 "object")


def _verify_rows(manifest, metadata):
    rows_value = manifest.get("rows")
    if (not isinstance(rows_value, dict)
            or not isinstance(rows_value.get("count"), int)
            or rows_value["count"] < 0
            or not isinstance(rows_value.get("fingerprint"), str)
            or not rows_value["fingerprint"]):
        raise GenerationRejected("manifest: rows malformed")
    count = rows_value["count"]
    if not isinstance(metadata, list) or len(metadata) != count:
        raise GenerationRejected(
            "metadata: %d rows, manifest declares %d"
            % (len(metadata) if isinstance(metadata, list) else -1, count))
    seen = set()
    for index, row in enumerate(metadata):
        if not isinstance(row, dict) or row.get("row") != index:
            raise GenerationRejected(
                "metadata: row %d index mismatch" % index)
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise GenerationRejected(
                "metadata: row %d event_id missing" % index)
        if event_id in seen:
            raise GenerationRejected(
                "metadata: duplicate event_id %s" % event_id)
        seen.add(event_id)
        key = row.get("choice_problem_key")
        if (not isinstance(key, list) or len(key) != 3
                or any(not isinstance(part, str) or not part
                       for part in key)):
            raise GenerationRejected(
                "metadata: row %d choice_problem_key malformed" % index)
        if not isinstance(row.get("candidate"), str) or not row["candidate"]:
            raise GenerationRejected(
                "metadata: row %d candidate missing" % index)
        hlc = row.get("hlc")
        if (not isinstance(hlc, list) or len(hlc) != 2
                or not all(isinstance(value, int) and value >= 0
                           for value in hlc)):
            raise GenerationRejected(
                "metadata: row %d hlc malformed" % index)
    fingerprint = _rows_fingerprint(metadata)
    if fingerprint != rows_value["fingerprint"]:
        raise GenerationRejected("rows fingerprint mismatch")
    return count


def _verify_chunks(manifest, rows, dimension, vectors_path):
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        raise GenerationRejected("manifest: chunks must be a list")
    row_bytes = dimension * 4
    expected = 0
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise GenerationRejected("manifest: chunk %d malformed" % index)
        start = chunk.get("start_row")
        end = chunk.get("end_row")
        if not (isinstance(start, int) and isinstance(end, int)
                and 0 <= start < end <= rows and start == expected):
            raise GenerationRejected(
                "manifest: chunk %d row range invalid" % index)
        if chunk.get("bytes") != (end - start) * row_bytes:
            raise GenerationRejected(
                "manifest: chunk %d byte count mismatch" % index)
        if not isinstance(chunk.get("sha256"), str) or not chunk["sha256"]:
            raise GenerationRejected(
                "manifest: chunk %d checksum missing" % index)
        with open(vectors_path, "rb") as handle:
            handle.seek(start * row_bytes)
            data = handle.read((end - start) * row_bytes)
        if _sha256_hex(data) != chunk["sha256"]:
            raise GenerationRejected(
                "manifest: chunk %d checksum mismatch" % index)
        expected = end
    if expected != rows:
        raise GenerationRejected(
            "manifest: chunks cover %d rows, need %d" % (expected, rows))


def _verify_vectors(vfile, rows, dimension):
    for row in range(rows):
        problem = _validate_vector(vfile.vector(row), dimension)
        if problem is not None:
            raise GenerationRejected(
                "vectors: row %d %s" % (row, problem))


def _verify_probes(manifest, events, vfile, row_index, source_hlc):
    probes = manifest.get("probes")
    if not isinstance(probes, dict) or not isinstance(
            probes.get("items"), list):
        raise GenerationRejected("manifest: probes malformed")
    try:
        params = _probe_params_from_dict(probes.get("params", {}))
    except (KeyError, TypeError, ValueError) as error:
        raise GenerationRejected("manifest: probe params malformed: %s"
                                 % error)
    if len(probes["items"]) > min(PROBE_COUNT, len(events)):
        raise GenerationRejected("manifest: unexpected probe count")
    for index, probe in enumerate(probes["items"]):
        if not isinstance(probe, dict):
            raise GenerationRejected("manifest: probe %d malformed" % index)
        result = _compute_probe(probe, events, vfile, row_index, params,
                                source_hlc)
        expected = probe.get("results_fingerprint")
        if not isinstance(expected, str) or (
                _probe_results_fingerprint(result) != expected):
            raise GenerationRejected(
                "probe %d results fingerprint mismatch" % index)


def open_generation(generation_dir):
    """Verify and load one immutable generation.

    Runs the full reopen verification (spec clause 6): checksum and size of
    every file, the chunk records, the row/event bijection, the rows
    fingerprint, finiteness and unit norm of every vector, and the fixed
    exact-oracle probes.  Raises ``GenerationRejected`` on the first failing
    check -- a corrupt or identity-unknown generation is a fault, never an
    empty memory.
    """
    generation_dir = os.path.abspath(generation_dir)
    directory_name = os.path.basename(generation_dir)
    manifest_path = os.path.join(generation_dir, "manifest.json")
    metadata_path = os.path.join(generation_dir, "metadata.json")
    vectors_path = os.path.join(generation_dir, "vectors.fp32")
    try:
        entries = set(os.listdir(generation_dir))
    except OSError as error:
        raise GenerationRejected("cannot list generation directory: %s"
                                 % error)
    if entries != set(GENERATION_FILES):
        raise GenerationRejected(
            "generation directory must contain exactly %s, found %s"
            % (", ".join(GENERATION_FILES),
               ", ".join(sorted(entries)) or "nothing"))
    for path in (manifest_path, metadata_path, vectors_path):
        if not os.path.isfile(path):
            raise GenerationRejected(
                "missing file %s" % os.path.basename(path))

    manifest = _read_json_file(manifest_path, "manifest")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise GenerationRejected(
            "manifest: unsupported manifest version %r"
            % manifest.get("manifest_version"))
    generation_id = manifest.get("generation_id")
    if not isinstance(generation_id, str) or not generation_id:
        raise GenerationRejected("manifest: generation_id missing")
    if directory_name != generation_id:
        raise GenerationRejected(
            "identity: directory %r does not match manifest generation %r"
            % (directory_name, generation_id))
    _verify_identity(manifest)
    identity = manifest["identity"]
    dimension = identity["vector_dimension"]
    source_hlc = tuple(identity["source_hlc"])

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(GENERATION_FILES):
        raise GenerationRejected(
            "manifest: files must cover exactly %s"
            % ", ".join(GENERATION_FILES))
    for name in GENERATION_FILES:
        entry = files[name]
        if not isinstance(entry, dict) or not isinstance(
                entry.get("sha256"), str) or not entry["sha256"]:
            raise GenerationRejected(
                "manifest: files.%s malformed" % name)
    for name in ("metadata.json", "vectors.fp32"):
        path = os.path.join(generation_dir, name)
        entry = files[name]
        if entry.get("size") != os.path.getsize(path):
            raise GenerationRejected(
                "manifest: %s size %r != disk %d"
                % (name, entry.get("size"), os.path.getsize(path)))
        if entry.get("sha256") != _file_sha256(path):
            raise GenerationRejected(
                "manifest: %s checksum mismatch" % name)

    # Manifest self-consistency: the recorded own-checksum is the hash of its
    # canonical serialization without the self entry.
    self_check = dict(manifest)
    self_check["files"] = dict(self_check["files"])
    del self_check["files"]["manifest.json"]
    if files["manifest.json"]["sha256"] != _sha256_hex(
            _canonical_json(self_check).encode("utf-8")):
        raise GenerationRejected("manifest: self-checksum mismatch")

    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (OSError, ValueError) as error:
        raise GenerationRejected("metadata: cannot read/parse: %s" % error)
    count = _verify_rows(manifest, metadata)
    _verify_chunks(manifest, count, dimension, vectors_path)
    expected_size = count * dimension * 4
    if os.path.getsize(vectors_path) != expected_size:
        raise GenerationRejected(
            "vectors: file size %d != %d rows x %d dims x 4"
            % (os.path.getsize(vectors_path), count, dimension))

    # Identity binding: the declared id must be derivable from the declared
    # identity plus the verified rows fingerprint (SCN-62-3 "身份未知").
    if _compose_generation_id(identity, manifest["rows"]["fingerprint"]) \
            != generation_id:
        raise GenerationRejected(
            "identity: generation_id does not match the bound identity")

    vfile = _VectorFile(vectors_path, count, dimension)
    _verify_vectors(vfile, count, dimension)
    row_index = {row["event_id"]: row["row"] for row in metadata}
    events = [
        StoredEvent(
            event_id=row["event_id"],
            commit_id="",
            schema_id=row["choice_problem_key"][0],
            canonical_segment_input=row["choice_problem_key"][2],
            category=row["choice_problem_key"][1],
            final_selection_text=row["candidate"],
            hlc=(row["hlc"][0], row["hlc"][1]))
        for row in metadata
    ]
    _verify_probes(manifest, events, vfile, row_index, source_hlc)
    return Generation(generation_dir, manifest, metadata, vfile, row_index)


# ---------------------------------------------------------------------------
# The loaded generation
# ---------------------------------------------------------------------------

class Generation:
    """A verified, loaded immutable generation.

    Owns an mmap over the FP32 vector file (no second resident copy) and the
    read-only row metadata.  All accessors are pure reads; the generation is
    immutable by construction -- rebuilding is delete-then-rebuild, never an
    in-place update.
    """

    def __init__(self, generation_dir, manifest, metadata, vfile, row_index):
        self._generation_dir = generation_dir
        self._manifest = manifest
        self._metadata = metadata
        self._vfile = vfile
        self._row_index = row_index

    # -- identity ---------------------------------------------------------

    @property
    def generation_id(self):
        return self._manifest["generation_id"]

    @property
    def generation_dir(self):
        return self._generation_dir

    @property
    def store_epoch(self):
        return self._manifest["identity"]["store_epoch"]

    @property
    def source_hlc(self):
        return tuple(self._manifest["identity"]["source_hlc"])

    @property
    def representation_id(self):
        return self._manifest["identity"]["representation_id"]

    @property
    def projection_version(self):
        return self._manifest["identity"]["projection_version"]

    @property
    def index_fingerprint(self):
        return self._manifest["identity"]["index_fingerprint"]

    @property
    def vector_dimension(self):
        return self._manifest["identity"]["vector_dimension"]

    @property
    def builder_version(self):
        return self._manifest["identity"]["builder_version"]

    @property
    def retrieval_backend(self):
        return self._manifest["identity"]["retrieval_backend"]

    def identity(self):
        """A copy of the bound identity (read-only by value)."""
        return json.loads(json.dumps(self._manifest["identity"]))

    def manifest(self):
        """A copy of the manifest (read-only by value)."""
        return json.loads(json.dumps(self._manifest))

    # -- rows -------------------------------------------------------------

    @property
    def row_count(self):
        return len(self._metadata)

    def event_ids(self):
        return [row["event_id"] for row in self._metadata]

    def row_event(self, row):
        """row -> event metadata dict (event_id, key, candidate, hlc)."""
        if not (0 <= row < len(self._metadata)):
            raise GenerationError("row %d out of range" % row)
        return json.loads(json.dumps(self._metadata[row]))

    def event_row(self, event_id):
        """event_id -> row index; unknown ids raise GenerationError."""
        row = self._row_index.get(event_id)
        if row is None:
            raise GenerationError("no row for event %s" % event_id)
        return row

    def event_rows(self):
        """A copy of the event_id -> row mapping (read-only by value)."""
        return dict(self._row_index)

    def vector(self, row):
        """The FP32 row vector as a tuple of floats (via mmap)."""
        return self._vfile.vector(row)

    def event_vector(self, event_id):
        return self._vfile.vector(self.event_row(event_id))

    def vector_buffer(self):
        """The raw read-only FP32 buffer (mmap) for zero-copy backends.

        #72: the Accelerate exact backend (``accelerate-cblas-sgemv``) reads
        the same canonical row-major little-endian FP32 file through a
        ctypes/numpy view of this buffer; no second resident copy.  The
        buffer is immutable; callers must not hold it past the generation's
        lifetime (the generation owns the mmap).
        """
        return self._vfile.buffer()

    def close(self):
        self._vfile.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


# ---------------------------------------------------------------------------
# Generation-backed representation provider (the #61 seam)
# ---------------------------------------------------------------------------

class GenerationRepresentationProvider(RepresentationProvider):
    """Serve one representation identity from a verified generation.

    ``query_vector`` delegates to the underlying ``query_provider`` (which
    must declare the identical representation id -- a mismatch is a fault,
    never a silently different representation); ``event_vector`` reads the
    stored FP32 row of the event from the generation.  This is the seam #61
    defined for the online path; ``replay_exact`` below is the offline
    evidence entry that #70's real-data replay will consume.
    """

    def __init__(self, generation, query_provider):
        if not isinstance(generation, Generation):
            raise EvidenceError("representation_fault",
                                "generation must be a Generation")
        if not isinstance(query_provider, RepresentationProvider):
            raise EvidenceError("representation_fault",
                                "query_provider must be a "
                                "RepresentationProvider")
        if query_provider.representation_id() != generation.representation_id:
            raise EvidenceError(
                "representation_fault",
                "query provider identity %r does not match generation %r"
                % (query_provider.representation_id(),
                   generation.representation_id))
        self._generation = generation
        self._query_provider = query_provider

    def representation_id(self):
        return self._generation.representation_id

    def query_vector(self, preceding_text):
        return self._query_provider.query_vector(preceding_text)

    def event_vector(self, event):
        return self._generation.event_vector(event.event_id)

    def vector_dimension(self):
        return self._generation.vector_dimension


class VectorReuseSource:
    """#66: serve stored vectors from a verified old generation.

    The compatibility matrix substitutes this source for the provider's
    ``event_vector`` when it explicitly permits vector reuse: a
    projection-only change with an identical representation and verified old
    vector checksums (``reuse_vectors``), or a vector-format change routed
    through a registered tested-equivalent converter (``convert_vectors``).

    ``generation`` must be an already-verified ``Generation`` (its checksums
    were verified by ``open_generation`` -- that is the checksum gate the
    matrix requires before reuse is allowed).  ``converter`` is an optional
    registered ``VectorFormatConverter`` whose ``convert`` maps the stored
    rows to the desired format and whose equivalence test is the converter's
    own responsibility.  An event missing from the old generation raises
    ``EvidenceError``: the builder then blocks naming the event -- reuse is
    never a silent re-embed, and the matrix never guesses (SCN-66-4).
    """

    def __init__(self, generation, converter=None):
        if not isinstance(generation, Generation):
            raise EvidenceError("representation_fault",
                                "reuse source needs a verified Generation")
        self._generation = generation
        self._converter = converter
        self._event_rows = {}
        for row in range(generation.row_count):
            meta = generation.row_event(row)
            self._event_rows[meta["event_id"]] = row

    def event_vector(self, event):
        row = self._event_rows.get(event.event_id)
        if row is None:
            raise EvidenceError(
                "representation_fault",
                "vector reuse: event %s not in the old generation"
                % event.event_id)
        vector = self._generation.vector(row)
        if self._converter is not None:
            vector = self._converter.convert(vector)
        return vector

    def close(self):
        try:
            self._generation.close()
        except Exception:  # noqa: BLE001 - best effort on close
            pass


# ---------------------------------------------------------------------------
# Exact replay against the generation (offline evidence entry)
# ---------------------------------------------------------------------------

def _check_replay_watermark(request_watermark, store_epoch, source_hlc):
    """The #61 catch-up gate, pinned to the generation's source watermark.

    A declared watermark must match the store epoch and lie at or before the
    generation's ``H0``; a later watermark means the generation has not
    caught up (delta catch-up is #63), which is a true fault, never a stale
    success.
    """
    if request_watermark is None:
        return
    if not isinstance(request_watermark, dict):
        raise EvidenceError("invalid_request",
                            "fact_high_water must be an object")
    expected = request_watermark.get("store_epoch")
    physical_want = request_watermark.get("hlc_physical_ms")
    logical_want = request_watermark.get("hlc_logical")
    if (not isinstance(expected, str) or not expected
            or not isinstance(physical_want, int) or physical_want < 0
            or not isinstance(logical_want, int) or logical_want < 0):
        raise EvidenceError("invalid_request", "fact_high_water is malformed")
    if expected != store_epoch:
        raise EvidenceError("fact_identity_mismatch",
                            "fact store epoch does not match the request")
    if (physical_want, logical_want) > tuple(source_hlc):
        raise EvidenceError(
            "not_caught_up",
            "request watermark is beyond the generation source watermark")


def replay_exact(generation, facts_root, params, query,
                 request_watermark=None):
    """Replay one exact oracle query through a verified generation.

    The oracle's as-of point is pinned to the generation's source watermark
    (the generation covers exactly its snapshot); the facts must carry the
    same ``store_epoch`` and their active set at ``H0`` must equal the
    generation's row set, or the replay is a fault.  Event vectors are read
    from the mmap'd FP32 file, so on the same facts and the same vectors the
    evidence is bit-identical to the canonical oracle (SCN-62-4).

    Raises ``EvidenceError`` (never a silent zero) for identity, watermark,
    event-set or vector faults; returns the canonical ``OracleResult``.
    """
    if not isinstance(generation, Generation):
        raise EvidenceError("oracle_fault", "generation must be a Generation")
    if not isinstance(params, OracleParams):
        raise EvidenceError("oracle_fault", "params must be OracleParams")
    if not isinstance(query, OracleQuery):
        raise EvidenceError("oracle_fault", "query must be an OracleQuery")
    reader = None
    try:
        reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
        store_epoch, physical, logical = reader.read_fact_identity()
        if store_epoch != generation.store_epoch:
            raise EvidenceError(
                "fact_identity_mismatch",
                "fact store epoch %r does not match generation %r"
                % (store_epoch, generation.store_epoch))
        if (physical, logical) < tuple(generation.source_hlc):
            raise EvidenceError(
                "not_caught_up",
                "fact store clock is behind the generation source watermark")
        _check_replay_watermark(request_watermark, store_epoch,
                                generation.source_hlc)

        as_of = tuple(generation.source_hlc)
        active = reader.read_active_events(as_of)
        actual = {event.event_id for event in active}
        expected = set(generation.event_ids())
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise EvidenceError(
                "event_set_mismatch",
                "generation event set differs from facts at source watermark "
                "(missing=%d extra=%d)" % (len(missing), len(extra)))

        def vector_for(event_id):
            return generation.event_vector(event_id)

        pinned = OracleQuery(
            schema_id=query.schema_id,
            canonical_segment_input=query.canonical_segment_input,
            candidates=list(query.candidates),
            query_vector=list(query.query_vector),
            category=query.category,
            as_of=as_of,
            exclude_event_ids=query.exclude_event_ids,
        )
        return compute_evidence(reader, params, pinned, vector_for)
    except EvidenceError:
        raise
    except OracleError as error:
        raise EvidenceError("oracle_fault", str(error)) from error
    finally:
        if reader is not None:
            reader.close()
