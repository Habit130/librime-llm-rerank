#!/usr/bin/env python3
"""Atomic blue-green publish of a ready staging generation (Habit130/squirrel#65).

On top of the #64 resumable staging machine (a fully re-verified ``ready``
container under ``staging/<generation_id>/``) and the #63 delta machine (the
serving query snapshot), a single publisher performs the spec's publish
transaction (spec #43 "并发重建与蓝绿发布", clauses 7-11):

1. **Publish preconditions (AC65-1)**: under the publish lock, the ready
   record is re-loaded and the full reopen verification re-runs -- file
   checksums, chunk records, row/event bijection, vector finiteness + unit
   norm, and the fixed exact-oracle probes (spec clause 6).  Any failure
   marks the staging ``discarded`` (never published, rebuilt).
2. **Short publish lock + H1 read (AC65-2)**: the transaction runs under
   the shared publish lock (the staging machine's worker serializes every
   cycle on the same lock).  The current facts identity is read as ``H1``
   and the ``(H0, H1]`` changes -- new events and whole-commit retractions
   -- are absorbed into the staging generation's OWN delta checkpoint
   (``delta/<generation_id>/delta.sqlite3``, the spec's "active generation
  与 staging generation 各自拥有独立 delta checkpoint").  Fact writes are
   never blocked: the lock is daemon-internal only (SCN-65-6).  A
   deterministic embed fault blocks the staging with the event named; an
   epoch change aborts the publish with the old active untouched
   (SCN-65-7).
3. **Durability order (AC65-3/4)**: the verified container is renamed into
   ``generations/<generation_id>/`` and both parent directories fsynced;
   the staging delta is committed with ``synchronous=FULL``; the active
   manifest (``<derived_root>/active_manifest.json``) is atomically
   replaced (temp + fsync + rename + parent fsync); only then does the
   delta machine's worker swap the in-memory query pointer (the #65
   ``publish_switch`` handshake, synchronous under the same lock).
4. **Crash semantics (SCN-65-2/3)**: a crash before the manifest replace
   leaves the complete old active (the staging, the orphaned checkpoint or
   the published-but-not-activated generation are harmless leftovers; #66
   owns their retention).  A crash after the manifest replace loads the
   complete new generation on restart -- the manifest, not the config, is
   then the source of truth for the active identity.
5. **Post-H1 facts (SCN-65-4)**: facts committed after ``H1`` (e.g. during
   the publish) are absorbed by the new active's catch-up worker before
   the next successful query -- never a stale-watermark success.
6. **Identity atomicity (SCN-65-5)**: the in-memory swap atomically
   switches generation, representation provider, checkpoint mirror and
   snapshot under the machine condition; the evidence service serves query
   vectors bound to the snapshot's own representation.  One query always
   sees one complete identity.

The active manifest (``active-manifest-v1``) records the orthogonal
identities the spec requires (fact schema version, representation id,
vector format, projection version, index fingerprint) plus the active
generation binding and its delta checkpoint path; the config seam
(``server.py``) resolves the active generation id and representation from
it at startup, so a runtime publish survives a daemon restart without any
config edit.
"""

import contextlib
import json
import os
import sqlite3
import threading
import time

import compat  # noqa: E402
from delta import (  # noqa: E402
    DELTA_FILENAME,
    DELTA_SCHEMA_VERSION,
    DeltaError,
    _connect_delta,
    _create_delta_schema,
    _pack_vector,
    _read_fact_changes,
    _validate_event,
    _validate_vector,
    _write_delta_meta,
    read_facts_identity,
)
from evidence import EvidenceError  # noqa: E402
from generation import (  # noqa: E402
    PROGRESS_FILENAME,
    _canonical_json,
    _fsync_directory,
    _write_atomic,
)
from retention import (  # noqa: E402
    compose_rollback_manifest,
    register_healthy_rollback,
)

ACTIVE_MANIFEST_FILENAME = "active_manifest.json"
ACTIVE_MANIFEST_VERSION = "active-manifest-v1"
# The projection semantics of the served active state (row projection,
# retraction handling, choice-problem keys, HLC metadata): a change to any
# of those needs a new projection version in the manifest (spec "分层兼容
# 身份").  The canonical constant lives in generation.py and is bound into
# every generation identity (#66); the active manifest records the
# generation-bound value, not a separate forever-constant.
DEFAULT_PUBLISH_POLL_INTERVAL_S = 2.0
DEFAULT_SWITCH_DEADLINE_S = 300.0
WRITE_BUSY_TIMEOUT_S = 5.0

_MANIFEST_KEYS = (
    "manifest_version",
    "generation_id",
    "store_epoch",
    "source_hlc",
    "fact_schema_version",
    "representation_id",
    "vector_format_version",
    "projection_version",
    "index_fingerprint",
    "delta_checkpoint",
    "builder_version",
    "published_at_ms",
)


class PublishError(Exception):
    """A true fault of the publish path (never a partial publish)."""


class PublishBlocked(PublishError):
    """A deterministic fault blocked the publish; the events are named.

    The ready staging is marked ``blocked`` (spec: 确定性失败保持 blocked)
    and the old active keeps serving; ``retry()`` on the staging machine
    re-arms the publish.
    """

    def __init__(self, message, blocked_events, phase="delta"):
        super().__init__(message)
        self.message = message
        self.blocked_events = tuple(blocked_events)
        self.phase = phase


# ---------------------------------------------------------------------------
# The active manifest
# ---------------------------------------------------------------------------

def _validate_manifest_value(manifest, reason):
    if not isinstance(manifest, dict):
        return "active manifest must be a JSON object"
    if manifest.get("manifest_version") != ACTIVE_MANIFEST_VERSION:
        return "active manifest version %r unsupported" % (
            manifest.get("manifest_version"))
    for key in _MANIFEST_KEYS:
        if key not in manifest:
            return "active manifest key %s missing" % key
    if not isinstance(manifest["generation_id"], str) \
            or not manifest["generation_id"]:
        return "active manifest generation_id missing"
    if not isinstance(manifest["store_epoch"], str) \
            or not manifest["store_epoch"]:
        return "active manifest store_epoch missing"
    source_hlc = manifest["source_hlc"]
    if (not isinstance(source_hlc, list) or len(source_hlc) != 2
            or not all(isinstance(value, int) and value >= 0
                       for value in source_hlc)):
        return "active manifest source_hlc malformed"
    for key in ("fact_schema_version", "representation_id",
                "vector_format_version", "projection_version",
                "index_fingerprint", "delta_checkpoint", "builder_version"):
        if not isinstance(manifest[key], str) or not manifest[key]:
            return "active manifest %s missing" % key
    checkpoint = os.path.normpath(manifest["delta_checkpoint"])
    if os.path.isabs(checkpoint) or checkpoint.startswith("..") \
            or os.path.basename(checkpoint) != DELTA_FILENAME:
        return "active manifest delta_checkpoint escapes the derived root"
    if not isinstance(manifest["published_at_ms"], int):
        return "active manifest published_at_ms must be an integer"
    return None


def read_active_manifest(derived_root):
    """(manifest, reason): the durable active pointer, or None.

    ``reason`` is None for a missing manifest (the config-declared active
    applies) and a diagnosis string for a present-but-invalid one (the
    caller must not load derived state per an unknown identity; #66 refuses
    the load -- there is no config-active fallback for a broken/unknown
    active manifest).
    """
    path = os.path.join(derived_root, ACTIVE_MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as error:
        return None, "active manifest unreadable: %s" % error
    problem = _validate_manifest_value(value, None)
    if problem is not None:
        return None, problem
    return value, None


def active_identity_from_manifest(manifest):
    """The layered identity recorded by a valid active manifest (#66).

    Maps the active manifest's orthogonal identity fields onto the
    ``IDENTITY_LAYERS`` shape the compatibility matrix compares, so the
    staging / delta / status paths can run ``plan_actions`` against it
    field by field.  Privacy-clean: identity strings and digests only.
    """
    return {
        compat.LAYER_STORE_EPOCH: manifest["store_epoch"],
        compat.LAYER_FACT_SCHEMA: manifest["fact_schema_version"],
        compat.LAYER_REPRESENTATION: manifest["representation_id"],
        compat.LAYER_VECTOR_FORMAT: manifest["vector_format_version"],
        compat.LAYER_PROJECTION: manifest["projection_version"],
        compat.LAYER_INDEX: manifest["index_fingerprint"],
    }


def resolve_active_identity(derived_root, facts_schema_version=None):
    """(active_identity, refuse_reason): the durable active identity.

    - No manifest -> ``(None, None)``: the config-declared active applies
      (nothing published yet; #63/#65 startup).
    - Valid manifest -> the layered identity; the caller then decides build
      actions via the matrix.
    - Present-but-invalid / unknown / missing compat declaration ->
      ``(None, reason)``: REFUSE.  The caller must not load derived state per
      the config-declared active (SCN-66-10) -- semantic requests fail
      closed / pass through, and status reports the refusal.
    """
    manifest, reason = read_active_manifest(derived_root)
    if manifest is None and reason is not None:
        return None, reason
    if manifest is None:
        return None, None
    identity = active_identity_from_manifest(manifest)
    refuse = compat.refuse_load_reason(
        identity, facts_schema_version=facts_schema_version)
    if refuse is not None:
        return None, refuse
    return identity, None


def _compose_active_manifest(generation, checkpoint_path,
                             fact_schema_version):
    """The active manifest over one verified generation (spec "分层兼容
    身份"): the orthogonal identities the startup and the next publish
    compare against.

    ``projection_version`` and ``index_fingerprint`` come from the generation
    identity (#66): the manifest records the generation-bound layers, so the
    active identity is comparable field by field with the desired one and a
    broken or unknown active is never silently reinterpreted.
    """
    identity = generation.identity()
    return {
        "manifest_version": ACTIVE_MANIFEST_VERSION,
        "generation_id": generation.generation_id,
        "store_epoch": identity["store_epoch"],
        "source_hlc": identity["source_hlc"],
        "fact_schema_version": fact_schema_version,
        "representation_id": identity["representation_id"],
        "vector_format_version": identity["vector_format"],
        "projection_version": identity["projection_version"],
        "index_fingerprint": identity["index_fingerprint"],
        "retrieval_params": identity["retrieval_params"],
        "delta_checkpoint": checkpoint_path,
        "builder_version": identity["builder_version"],
        "published_at_ms": int(time.time() * 1000),
    }


def write_active_manifest(derived_root, manifest):
    """Atomically replace the active manifest (temp + fsync + rename +
    parent fsync): the crash-atomic commit point of the publish."""
    _write_atomic(
        os.path.join(derived_root, ACTIVE_MANIFEST_FILENAME),
        _canonical_json(manifest).encode("utf-8"))


def _read_fact_schema_version(facts_root):
    conn = None
    try:
        conn = _open_facts_ro(facts_root)
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error as error:
        raise PublishError("fact store read failed: %s" % error)
    finally:
        if conn is not None:
            conn.close()
    return rows.get("fact_schema_version")


def _open_facts_ro(facts_root):
    db_path = os.path.join(facts_root, "facts.sqlite3")
    if not os.path.isfile(db_path):
        raise PublishError("fact store not found: %s" % db_path)
    try:
        # Read-only open semantics (AC-65-v1 repair): sqlite 3.54.0
        # returns SQLITE_CANTOPEN for a ``file:...?mode=ro`` URI open of a
        # WAL store with an active in-process writer (3.53.3 succeeds;
        # docs/publish-atomic.md).  Open the plain path and enforce
        # read-only in the engine with ``PRAGMA query_only=ON`` -- every
        # write statement fails with SQLITE_READONLY, the same
        # fail-closed guarantee, independent of the versioned URI
        # behavior.  The short busy wait absorbs the macOS WAL -shm
        # concurrent-open SQLITE_BUSY transient, exactly like the delta
        # machine's fact reads (the publish runs beside the query gate).
        conn = sqlite3.connect(db_path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON;")
    except sqlite3.Error as error:
        raise PublishError("cannot open fact store: %s" % error)
    return conn


# ---------------------------------------------------------------------------
# The staging generation's own delta checkpoint (AC65-2)
# ---------------------------------------------------------------------------

def _build_staging_delta(facts_root, derived_root, progress, provider,
                         upper):
    """Absorb ``(H0, H1]`` into ``delta/<generation_id>/delta.sqlite3``.

    Reuses the #63 checkpoint format and validation standards: WAL +
    ``synchronous=FULL``, one durable transaction advancing rows +
    tombstones + consumed HLC + change sequence, events whose whole commit
    is retracted inside the window never embedded (projected active set is
    identical -- evidence equivalence).  Deterministic parse/embed faults
    raise ``PublishBlocked`` naming the event; the store identity is
    re-checked before and after the commit (a changed epoch aborts the
    publish).  Returns the manifest-relative checkpoint path.
    """
    identity = progress["identity"]
    generation_id = progress["generation_id"]
    h0 = (identity["source_hlc"][0], identity["source_hlc"][1])
    epoch = identity["store_epoch"]
    dimension = identity["vector_dimension"]
    if epoch != read_facts_identity(facts_root)[0]:
        raise PublishError("fact store epoch changed before the delta read")
    events, retractions = _read_fact_changes(facts_root, h0, upper)
    retracted_commits = {commit_id for commit_id, _hlc in retractions}
    to_embed = []
    for event in events:
        problem = _validate_event(event)
        if problem is not None:
            raise PublishBlocked(
                "cannot absorb delta event %s: %s"
                % (event.event_id, problem), [event.event_id], phase="parse")
        if event.commit_id in retracted_commits:
            continue  # the whole commit leaves evidence in this window
        to_embed.append(event)
    vectors = {}
    for event in to_embed:
        try:
            vector = provider.event_vector(event)
        except EvidenceError as error:
            raise PublishBlocked(
                "cannot embed delta event %s: %s"
                % (event.event_id, error.message), [event.event_id],
                phase="vector")
        except Exception as error:  # noqa: BLE001 - fail closed
            raise PublishBlocked(
                "cannot embed delta event %s: %s"
                % (event.event_id, error), [event.event_id], phase="vector")
        problem = _validate_vector(vector, dimension)
        if problem is not None:
            raise PublishBlocked(
                "dirty vector for delta event %s: %s"
                % (event.event_id, problem), [event.event_id], phase="vector")
        vectors[event.event_id] = vector
    checkpoint_dir = os.path.join(derived_root, "delta", generation_id)
    try:
        os.makedirs(checkpoint_dir, mode=0o700, exist_ok=True)
    except OSError as error:
        raise PublishError("cannot create the staging delta root: %s"
                           % error)
    path = os.path.join(checkpoint_dir, DELTA_FILENAME)
    if os.path.exists(path):
        # A leftover of a crashed earlier publish of the same generation id
        # (the container is still in staging/, so no committed manifest can
        # reference this checkpoint): deterministic derived state, safe to
        # supersede.
        for name in (path, path + "-wal", path + "-shm"):
            try:
                os.unlink(name)
            except OSError:
                pass
    conn = None
    try:
        _create_delta_schema(path)
        conn = _connect_delta(path, busy_timeout=WRITE_BUSY_TIMEOUT_S)
        conn.execute("BEGIN IMMEDIATE;")
        seq = -1
        merged = []
        for event in to_embed:
            merged.append((event.hlc, event.event_id, "event", event))
        for commit_id, hlc in retractions:
            merged.append((hlc, commit_id, "retraction", commit_id))
        merged.sort(key=lambda item: (item[0], item[1], item[2]))
        for _hlc, _key, kind, payload in merged:
            seq += 1
            if kind == "event":
                event = payload
                conn.execute(
                    "INSERT INTO delta_events(event_id, commit_id, schema_id,"
                    " canonical_segment_input, category, final_selection_text,"
                    " hlc_physical_ms, hlc_logical, vector, change_seq)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?);",
                    (event.event_id, event.commit_id, event.schema_id,
                     event.canonical_segment_input, event.category,
                     event.final_selection_text, event.hlc[0], event.hlc[1],
                     _pack_vector(vectors[event.event_id]), seq))
            else:
                conn.execute(
                    "INSERT INTO retractions(commit_id, hlc_physical_ms,"
                    " hlc_logical, change_seq) VALUES(?,?,?,?);",
                    (payload, _hlc[0], _hlc[1], seq))
        _write_delta_meta(conn, {
            "delta_schema_version": DELTA_SCHEMA_VERSION,
            "base_generation_id": generation_id,
            "store_epoch": epoch,
            "representation_id": identity["representation_id"],
            "vector_dimension": dimension,
            "base_hlc_physical_ms": h0[0],
            "base_hlc_logical": h0[1],
            "consumed_hlc_physical_ms": upper[0],
            "consumed_hlc_logical": upper[1],
            "change_seq": seq,
        })
        conn.execute("COMMIT;")
    except sqlite3.Error as error:
        raise PublishError("staging delta transaction failed: %s" % error)
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    # Durable commit done: the epoch must still match (SCN-65-7).  A later
    # watermark is fine -- facts past H1 are caught up by the new active
    # before the next successful query (SCN-65-4).
    identity_now = read_facts_identity(facts_root)
    if identity_now is None or identity_now[0] != epoch:
        raise PublishError("fact store epoch changed during the publish")
    return os.path.join("delta", generation_id, DELTA_FILENAME)


# ---------------------------------------------------------------------------
# The publish transaction
# ---------------------------------------------------------------------------

def _park_progress(staging_root, generation_id):
    """Move the transient progress record outside the container."""
    progress_path = os.path.join(staging_root, generation_id,
                                 PROGRESS_FILENAME)
    tmp_path = os.path.join(staging_root,
                            ".verify-%s.tmp" % generation_id)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    os.rename(progress_path, tmp_path)
    return tmp_path


def _restore_progress(staging_root, generation_id, tmp_path):
    progress_path = os.path.join(staging_root, generation_id,
                                 PROGRESS_FILENAME)
    os.rename(tmp_path, progress_path)


def publish_ready_staging(facts_root, derived_root, staging_machine,
                          staging_dir, generation_id, provider,
                          delta_machine, publish_lock=None,
                          switch_deadline=DEFAULT_SWITCH_DEADLINE_S,
                          now=time.monotonic):
    """One publish transaction (AC65-1..4; SCN-65-2/3/5/6/7).

    Runs under ``publish_lock`` when given (the staging machine's worker
    serializes on the same lock).  Returns a result dict:

        {"ok": bool, "committed": bool, "error": str|None}

    ``committed`` is True once the active manifest was durably replaced
    (a crash from that point loads the complete new generation on restart);
    ``ok`` additionally requires the in-memory pointer swap to have
    completed.  The old active is left untouched on every pre-commit
    failure; the ready staging is preserved (or marked discarded / blocked
    with the precise diagnosis) so the publisher retries or the operator
    intervenes.
    """
    lease = publish_lock if publish_lock is not None else contextlib.nullcontext()
    with lease:
        return _publish_locked(
            facts_root, derived_root, staging_machine, staging_dir,
            generation_id, provider, delta_machine,
            switch_deadline=switch_deadline, now=now)


def _publish_locked(facts_root, derived_root, staging_machine, staging_dir,
                    generation_id, provider, delta_machine,
                    switch_deadline, now):
    try:
        progress, _pinned = staging_machine.verify_publishable(staging_dir)
    except Exception as error:  # noqa: BLE001 - diagnose and fail closed
        reason = getattr(error, "reason", None) or str(error)
        try:
            staging_machine.publish_reject(
                staging_dir, "publish preconditions failed: %s" % reason)
        except Exception:  # noqa: BLE001 - best effort
            pass
        return {"ok": False, "committed": False,
                "error": "publish preconditions failed: %s" % reason}
    if progress["generation_id"] != generation_id:
        return {"ok": False, "committed": False,
                "error": "staging record generation %r does not match %r"
                         % (progress["generation_id"], generation_id)}
    try:
        facts_identity = read_facts_identity(facts_root)
    except DeltaError as error:
        return {"ok": False, "committed": False,
                "error": "fact store read failed: %s" % error}
    if facts_identity is None:
        return {"ok": False, "committed": False,
                "error": "fact store is missing"}
    epoch, h1 = facts_identity
    try:
        checkpoint_path = _build_staging_delta(
            facts_root, derived_root, progress, provider, h1)
    except PublishBlocked as error:
        try:
            staging_machine.publish_block(
                "publish delta blocked: %s" % error.message,
                error.blocked_events, phase=error.phase)
        except Exception:  # noqa: BLE001 - best effort
            pass
        return {"ok": False, "committed": False,
                "error": error.message}
    except PublishError as error:
        return {"ok": False, "committed": False, "error": str(error)}

    staging_root = os.path.join(derived_root, "staging")
    published_root = os.path.join(derived_root, "generations")
    tmp_progress = None
    try:
        # Container rename: progress parked outside first (the container is
        # exactly the three immutable files), the generation becomes
        # durable under generations/<id>/, both parent directories fsynced.
        # The parked progress stays parked until the commit point: a
        # pre-commit failure must be able to restore it.
        tmp_progress = _park_progress(staging_root, generation_id)
        os.makedirs(published_root, mode=0o700, exist_ok=True)
        os.rename(staging_dir, os.path.join(published_root, generation_id))
        _fsync_directory(published_root)
        _fsync_directory(staging_root)

        # Atomic commit point: the active manifest (temp + fsync + rename +
        # parent fsync).  From here a crash loads the complete new
        # generation.  ``_write_atomic`` only raises before its rename, so
        # any exception below still means the manifest was NOT replaced and
        # the container rename is safe to roll back for the next retry.
        fact_schema_version = _read_fact_schema_version(facts_root)
        if not fact_schema_version:
            raise PublishError("fact store schema version missing")
        from generation import open_generation
        generation = None
        try:
            # #67 rollback registration, BEFORE the manifest swap (crash-
            # robust): the just-retired healthy active becomes the rollback
            # pointer.  A crash after the manifest replace then still loads
            # the complete new generation AND keeps the retired healthy
            # active as the rollback (SCN-67-2).  A damaged retired active
            # is never registered -- the retained rollback (if any) stays
            # in force.  Registration must not start deleting anything
            # mid-switch (seam 1); the retention sweep runs after the
            # successful publish below.
            retired_id = None
            try:
                snapshot = delta_machine.snapshot()
                if snapshot is not None:
                    retired_id = snapshot.base_generation_id
            except Exception:  # noqa: BLE001 - best effort
                retired_id = None
            if retired_id and retired_id != generation_id:
                try:
                    retired = open_generation(
                        os.path.join(published_root, retired_id))
                    try:
                        register_healthy_rollback(
                            derived_root, retired,
                            os.path.join("delta", retired_id, DELTA_FILENAME),
                            fact_schema_version)
                    finally:
                        try:
                            retired.close()
                        except Exception:  # noqa: BLE001 - best effort
                            pass
                except Exception:  # noqa: BLE001 - never register a damaged
                    pass  # retired active (SCN-67-2); keep the old pointer
            generation = open_generation(
                os.path.join(published_root, generation_id))
            manifest = _compose_active_manifest(
                generation, checkpoint_path, fact_schema_version)
            write_active_manifest(derived_root, manifest)
        finally:
            if generation is not None:
                try:
                    generation.close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
        try:
            os.unlink(tmp_progress)
        except OSError:
            pass  # a leftover .verify-<id>.tmp is harmless (#66 cleanup)
        _fsync_directory(staging_root)
    except Exception as error:  # noqa: BLE001 - fail closed, roll back
        reason = getattr(error, "reason", None) or str(error)
        # Pre-commit failure: roll the container rename back so the ready
        # staging survives for the publisher's next attempt (a real crash
        # at any of these points leaves the same two safe outcomes: the
        # complete old active, or the complete old active plus an orphaned
        # published container that #66 retains).
        try:
            if os.path.isdir(os.path.join(published_root, generation_id)):
                os.rename(os.path.join(published_root, generation_id),
                          staging_dir)
                _fsync_directory(staging_root)
            if tmp_progress is not None and os.path.isfile(tmp_progress):
                _restore_progress(staging_root, generation_id, tmp_progress)
        except OSError:
            pass
        return {"ok": False, "committed": False,
                "error": "active manifest write failed: %s" % reason}

    # In-memory pointer swap: synchronous handshake with the delta
    # machine's worker.  A timeout leaves the manifest committed and the
    # publisher retries the handshake on its next poll; an unexpected
    # switch fault (e.g. a crash right at the swap) is treated the same
    # way -- the durable commit stands and a restart loads the new
    # generation.
    try:
        ok, error = delta_machine.publish_switch(
            generation_id, checkpoint_path, provider, epoch,
            deadline=now() + switch_deadline)
    except Exception as error:  # noqa: BLE001 - fail closed, committed
        return {"ok": False, "committed": True,
                "error": "publish switch fault: %s" % error}
    if not ok:
        return {"ok": False, "committed": True, "error": error}
    # #67 retention (seam 1): runs only after a SUCCESSFUL publish, never
    # mid-switch.  The newly published generation is active; the rollback
    # pointer (registered before the swap above, or a surviving older one)
    # is the retained rollback; everything outside {active, rollback,
    # current staging} is deleted.  The only rollback is never deleted
    # (SCN-67-2/3).
    try:
        from retention import sweep_from_manifests
        sweep_from_manifests(derived_root, active_id=generation_id)
    except Exception:  # noqa: BLE001 - best effort; never fail a publish
        pass
    return {"ok": True, "committed": True, "error": None}


# ---------------------------------------------------------------------------
# The publisher worker (daemon wiring)
# ---------------------------------------------------------------------------

class GenerationPublisher:
    """Background publisher: polls the staging machine and publishes ready
    stagings (one at a time, serialized with the staging worker).

    The publisher owns: the publish lock (shared with the staging machine),
    the publish transaction, and the retry state of a committed-but-not-
    yet-switched publish (the manifest was durably replaced but the
    in-memory pointer swap timed out -- the handshake is retried on every
    poll until the worker completes it).  It never writes facts, never
    touches the active checkpoint, and holds no fact leases; like the
    staging machine it is not registered with the maintenance coordinator
    (a publish aborts cleanly on any epoch change).
    """

    def __init__(self, facts_root, derived_root, staging_machine,
                 delta_machine, publish_lock=None,
                 poll_interval=DEFAULT_PUBLISH_POLL_INTERVAL_S,
                 switch_deadline=DEFAULT_SWITCH_DEADLINE_S,
                 start_worker=True):
        if not facts_root or not derived_root:
            raise PublishError("facts root and derived root are required")
        if not isinstance(staging_machine, object) or \
                not hasattr(staging_machine, "status"):
            raise PublishError("staging_machine must expose status()")
        if not hasattr(delta_machine, "publish_switch"):
            raise PublishError("delta_machine must expose publish_switch()")
        self._facts_root = facts_root
        self._derived_root = derived_root
        self._staging_machine = staging_machine
        self._delta_machine = delta_machine
        self._publish_lock = publish_lock or threading.Lock()
        self._poll_interval = float(poll_interval)
        self._switch_deadline = float(switch_deadline)
        self._committed_generation_id = None
        self._committed_epoch = None
        self._committed_provider = None
        self._switched_generation_id = None
        self._last_error = None
        self._last_result = None
        self._publish_success_hooks = []
        self._condition = threading.Condition()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._idle_event = threading.Event()
        if not start_worker:
            self._idle_event.set()
        self._closed = False
        self._worker = None  # type: Optional[threading.Thread]
        if start_worker:
            self._worker = threading.Thread(
                target=self._run, name="generation-publisher", daemon=True)
            self._worker.start()

    def _run(self):
        while not self._closed:
            if self._stop_event.is_set():
                self._idle_event.set()
                self._wake_event.wait(self._poll_interval)
                self._wake_event.clear()
                continue
            self._idle_event.clear()
            try:
                self._cycle()
            except Exception as error:  # noqa: BLE001 - never die
                with self._condition:
                    self._last_error = "publisher fault: %s" % error
                    self._condition.notify_all()
            self._wake_event.wait(self._poll_interval)
            self._wake_event.clear()

    def _cycle(self):
        """One poll: finish a committed-but-unswitched publish, then look
        for a ready staging."""
        if (self._committed_generation_id is not None
                and self._committed_generation_id
                != self._switched_generation_id):
            ok, error = self._delta_machine.publish_switch(
                self._committed_generation_id,
                os.path.join("delta", self._committed_generation_id,
                             DELTA_FILENAME),
                self._committed_provider, self._committed_epoch,
                deadline=time.monotonic() + self._switch_deadline)
            if ok:
                with self._condition:
                    self._switched_generation_id = \
                        self._committed_generation_id
                    self._last_error = None
            else:
                with self._condition:
                    self._last_error = "switch pending: %s" % error
            return
        with self._condition:
            status = self._staging_machine.status()
        ready_id = status.get("ready_generation_id")
        staging_dir = status.get("ready_staging_dir")
        progress = status.get("progress")
        if not ready_id or not staging_dir or not os.path.isdir(staging_dir):
            return
        if progress is None or progress.get("status") != "ready" \
                or progress.get("generation_id") != ready_id:
            return
        provider = self._staging_machine.provider()
        result = publish_ready_staging(
            self._facts_root, self._derived_root, self._staging_machine,
            staging_dir, ready_id, provider,
            self._delta_machine, publish_lock=self._publish_lock,
            switch_deadline=self._switch_deadline)
        with self._condition:
            self._last_result = result
            if result["committed"]:
                self._committed_generation_id = ready_id
                self._committed_epoch = progress["identity"]["store_epoch"]
                self._committed_provider = provider
                if result["ok"]:
                    self._switched_generation_id = ready_id
                    self._last_error = None
                else:
                    self._last_error = result["error"]
            elif not result["ok"]:
                self._last_error = result["error"]
        if result["ok"]:
            self.notify_publish_success()

    # ------------------------------------------------------------------
    # Builder seams (mirror the staging machine)
    # ------------------------------------------------------------------

    def request_stop(self):
        self._stop_event.set()
        self._wake_event.set()

    def start(self):
        self._stop_event.clear()
        self._wake_event.set()

    def add_publish_success_hook(self, hook):
        """#67: register a callback invoked after every fully successful
        publish (the config seam uses it to clear the staging machine's
        forced-build flags once the delta has been absorbed)."""
        if not callable(hook):
            raise PublishError("publish success hook must be callable")
        with self._condition:
            self._publish_success_hooks.append(hook)

    def notify_publish_success(self):
        """#67: fire the publish-success hooks (a fully successful publish
        means the active changed to a fresh generation that absorbed the
        delta -- any forced compaction / no-rollback rebuild is satisfied)."""
        with self._condition:
            hooks = tuple(self._publish_success_hooks)
        for hook in hooks:
            try:
                hook()
            except Exception:  # noqa: BLE001 - best effort
                pass

    def wait_idle(self, timeout=30.0):
        return self._idle_event.wait(timeout)

    def status(self):
        with self._condition:
            return {
                "committed_generation_id": self._committed_generation_id,
                "switched_generation_id": self._switched_generation_id,
                "last_error": self._last_error,
                "last_result": dict(self._last_result)
                if self._last_result is not None else None,
            }

    def health(self):
        with self._condition:
            return {
                "publish_committed_generation_id":
                    self._committed_generation_id,
                "publish_switched_generation_id":
                    self._switched_generation_id,
                "publish_last_error": self._last_error,
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
            self._committed_generation_id = None
            self._switched_generation_id = None


# ---------------------------------------------------------------------------
# Config wiring (server.py builds the publisher when the config declares
# a staging machine)
# ---------------------------------------------------------------------------

def build_publisher_from_config(facts_root, config, staging_machine,
                                delta_machine, publish_lock):
    """Construct the publisher over a declared staging machine.

    Returns None when the config declares no staging machine (nothing to
    publish); a publisher requires both the staging machine (the ready
    staging) and the delta machine (the query-pointer swap).
    """
    if staging_machine is None or delta_machine is None:
        return None
    try:
        derived_root = config["derived_root"]
        if not derived_root or not isinstance(derived_root, str):
            raise ValueError("derived_root must be a non-empty string")
        poll = float(config.get("publish_poll_interval_ms", 2000)) / 1000.0
        if poll <= 0:
            raise ValueError("publish_poll_interval_ms must be positive")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed publish config: %s" % error)
    return GenerationPublisher(
        facts_root, derived_root, staging_machine, delta_machine,
        publish_lock=publish_lock, poll_interval=poll)
