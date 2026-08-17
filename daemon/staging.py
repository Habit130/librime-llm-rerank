#!/usr/bin/env python3
"""Resumable staging generation build (Habit130/squirrel#64).

While the current healthy generation keeps serving and absorbing delta
(#63), a single background builder chunks the target generation into
``<derived_root>/staging/<generation_id>/``, durably advances one atomic
progress manifest, and leaves the fully re-verified container as a ``ready``
staging for the later publish step (#65).  Builds are resumable across
daemon restarts; deterministic faults block with the offending event
named; a changed target identity or store epoch discards the staging in
full -- never a partial reuse, never a partial publish.

Progress manifest (``progress.json``, owner-only, atomically replaced):

    progress_version   "shadow-generation-progress-v2"
    generation_id      the fixed target (content-addressed)
    status             running | blocked | ready | discarded
    total_rows         deterministic active-event count at H0
    rows_fingerprint   sha256 of the ordered row projection
    identity           store_epoch, H0, representation_id, dimension,
                       format, builder_version, retrieval backend + params
    chunks             [{start_row, end_row, bytes, sha256}] -- every chunk
                       record is real: row range, event count and checksum
                       of the bytes actually written (AC64-2)
    blocked_events     the offending event ids when status == blocked

Restart resume gate (AC64-3): a running staging is resumed only when the
recorded epoch, H0, every fingerprint (rows fingerprint + representation
identity) and the builder version all still match -- verified by
recomputing the pinned target from the facts at the recorded H0.  Any
mismatch discards the staging in full; completed chunks are re-verified
against the vectors file before any continuation (SCN-64-3).

Discard triggers (SCN-64-4): store epoch change, desired representation
change, builder version change, a target that is already published, or a
target that now equals the active generation.  A discarded staging is
never resumed or partially reused; the record is marked ``discarded``
(physical deletion belongs to clear and #66 retention).

Deterministic parse/representation/model faults enter ``blocked`` with the
event ids named and park the worker: no auto-retry, no per-query retry
storm (SCN-64-5/7).  ``retry()`` (maintenance) clears the block and the
build resumes from the last verified chunk.  Transient faults (I/O,
concurrent store replacement) just skip the cycle and resume from the last
verified chunk on the next poll.

Concurrency (SCN-64-6/8): the machine holds no fact handles, never writes
facts, never touches the active generation or the delta checkpoint, and is
never invoked by the query path.  The single-builder constraint ("一次只
运行一个 builder") is enforced by an optional shared ``builder_lock`` that
both this machine and the delta machine's rebuild path acquire around every
embedding step.
"""

import contextlib
import os
import shutil
import threading

from delta import read_facts_identity  # noqa: E402
from evidence import EvidenceError, RepresentationProvider  # noqa: E402
from generation import (  # noqa: E402
    BUILD_VERSION,
    CHUNK_ROWS,
    PROBE_PARAMS,
    PROGRESS_FILENAME,
    BuildBlockedError,
    BuildError,
    BuildProgressError,
    GenerationRejected,
    _build_chunks,
    _canonical_json,
    _compose_manifest,
    _compute_probes,
    _prepare_target,
    _read_json_file,
    _read_snapshot,
    _verify_progress_chunks,
    _write_atomic,
    _write_file,
    _write_metadata,
    open_generation,
)

STAGING_PROGRESS_VERSION = "shadow-generation-progress-v2"
DEFAULT_POLL_INTERVAL_S = 2.0


class StagingError(Exception):
    """A true fault of the staging build path."""


class _ResumeGateError(StagingError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class StagingBuildMachine:
    """Single-worker resumable staging builder over one derived root.

    The machine owns: the deterministic build target (derived from the
    desired provider and the facts snapshot), the staging directory under
    ``<derived_root>/staging/``, and the only worker thread that may write
    it.  It shares the derived root with the delta machine but never writes
    the delta checkpoint, the active generation or the facts.
    """

    def __init__(self, facts_root, derived_root, provider,
                 active_representation_id, active_generation_id,
                 chunk_rows=CHUNK_ROWS, probe_params=PROBE_PARAMS,
                 poll_interval=DEFAULT_POLL_INTERVAL_S,
                 start_worker=True, builder_lock=None, publish_lock=None):
        if not facts_root:
            raise StagingError("facts root missing")
        if not derived_root:
            raise StagingError("derived root missing")
        if not isinstance(provider, RepresentationProvider):
            raise StagingError("provider must be a RepresentationProvider")
        if not active_representation_id or not isinstance(
                active_representation_id, str):
            raise StagingError("active_representation_id must be a "
                               "non-empty string")
        if not active_generation_id or not isinstance(
                active_generation_id, str):
            raise StagingError("active_generation_id must be a non-empty "
                               "string")
        if not isinstance(chunk_rows, int) or chunk_rows < 1:
            raise StagingError("chunk_rows must be a positive integer")
        if not (isinstance(poll_interval, (int, float))
                and poll_interval > 0):
            raise StagingError("poll_interval must be positive")
        representation_id_value = provider.representation_id()
        if not representation_id_value or not isinstance(
                representation_id_value, str):
            raise StagingError("provider representation_id must be a "
                               "non-empty string")
        dimension = provider.vector_dimension()
        if not isinstance(dimension, int) or dimension < 1:
            raise StagingError("provider vector_dimension must be a "
                               "positive integer")
        self._facts_root = facts_root
        self._derived_root = derived_root
        self._provider = provider
        self._active_representation_id = active_representation_id
        self._active_generation_id = active_generation_id
        self._chunk_rows = chunk_rows
        self._probe_params = probe_params
        self._poll_interval = float(poll_interval)
        self._builder_lock = builder_lock
        # #65: the publish transaction and every state-machine cycle that
        # touches the staging namespace serialize on this lock, so the
        # publisher's verify/rename of a ready container can never race a
        # worker cycle (resume/finalize/reverify/discard) over the same
        # directory.  Optional: without a lock the machine behaves exactly
        # as #64 (no publisher wired).
        self._publish_lock = publish_lock
        self._condition = threading.Condition()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._idle_event = threading.Event()
        if not start_worker:
            self._idle_event.set()
        self._closed = False
        self._blocked = None  # type: Optional[BuildBlockedError]
        self._blocked_epoch = None
        self._target_generation_id = None
        self._current_dir = None
        self._current_progress = None
        self._ready_generation_id = None
        self._ready_staging_dir = None
        self._ready_verified = False
        self._last_error = None
        self._last_discard_reason = None
        self._worker = None  # type: Optional[threading.Thread]
        try:
            os.makedirs(derived_root, mode=0o700, exist_ok=True)
        except OSError as error:
            raise StagingError("cannot create derived root: %s" % error)
        if start_worker:
            self._worker = threading.Thread(
                target=self._run, name="staging-builder", daemon=True)
            self._worker.start()

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _run(self):
        """Worker thread: one state-machine cycle per wake/poll.

        The worker parks while stopped (maintenance seam) and only exits on
        ``close``.  Every fault is contained per cycle: deterministic
        faults block, transient faults retry on the next poll at the poll
        cadence -- nothing here is driven by the query path, so a build can
        never turn into a per-query retry storm (SCN-64-7).
        """
        while not self._closed:
            if self._stop_event.is_set():
                self._idle_event.set()
                self._wake_event.wait(self._poll_interval)
                self._wake_event.clear()
                continue
            self._idle_event.clear()
            try:
                # #65: every cycle that touches the staging namespace is
                # serialized against the publish transaction (the publisher
                # holds the same lock for its whole verify/rename/switch).
                if self._publish_lock is not None:
                    with self._publish_lock:
                        self._cycle()
                else:
                    self._cycle()
            except Exception as error:  # noqa: BLE001 - never die
                with self._condition:
                    self._last_error = "staging worker fault: %s" % error
                    self._condition.notify_all()
            self._wake_event.wait(self._poll_interval)
            self._wake_event.clear()

    def _cycle(self):
        """One state-machine step (the resumability/abandon matrix).

        Order matters: the machine first re-derives the fresh target, then
        locates its own live staging record (the build is pinned to the
        H0 of its start, so after facts advanced the record lives under a
        different generation id than the fresh target), then applies the
        no-op gates (already published / desired == active), then the
        per-status continuation (running -> resume, blocked -> park, ready
        -> re-verify).  Records that no longer match the current epoch,
        desired representation or builder version are invalidated
        (SCN-64-4).  Transient read faults (concurrent store replacement)
        surface as errors and retry on the next poll.
        """
        facts_identity = read_facts_identity(self._facts_root)
        if facts_identity is None:
            return  # store not created yet; retry on the next wake
        facts_epoch, _facts_max = facts_identity
        with self._condition:
            blocked = self._blocked
        if blocked is not None:
            progress = self._current_progress
            if progress is None or progress.get("status") != "blocked":
                # A block without a staging record: park unless the input
                # (store epoch) changed -- spec: blocked 保持到输入、配置或
                # 实现改变,或维护者显式重试.
                if self._blocked_epoch == facts_epoch:
                    return
                with self._condition:
                    self._blocked = None
                    self._blocked_epoch = None
        try:
            target = self._compute_target()
        except BuildBlockedError as error:
            self._enter_blocked(error, None, None)
            return
        except BuildError as error:
            self._set_last_error("staging target compute failed: %s" % error)
            return
        desired_repr = target["identity"]["representation_id"]

        if desired_repr == self._active_representation_id:
            # desired == active: never build (spec: desired/active 区分);
            # any leftover record is obsolete.
            self._mark_stale_records_discarded(facts_epoch, desired_repr)
            self._sync_state(target, None)
            return

        found = self._find_own_record(facts_epoch, desired_repr)
        if found is None:
            # No live build: invalidate stale records, then start fresh.
            self._mark_stale_records_discarded(facts_epoch, desired_repr)
            staging_dir = self._staging_dir(target["generation_id"])
            if os.path.isdir(self._published_dir(target["generation_id"])):
                self._sync_state(target, None)
                return
            self._start_build(staging_dir, target)
            self._sync_state(target, self._load_progress(staging_dir))
            return

        staging_dir, progress = found
        with self._condition:
            self._current_dir = staging_dir
            self._current_progress = dict(progress)
            self._target_generation_id = progress["generation_id"]

        # Any other record is obsolete (should not exist; defensive).
        self._mark_stale_records_discarded(facts_epoch, desired_repr,
                                           keep_dir=staging_dir)

        # -- no-op gates ----------------------------------------------------
        if os.path.isdir(self._published_dir(progress["generation_id"])):
            self._discard(staging_dir, "target is already published",
                          own=True)
            self._sync_state(target, None)
            return
        if progress["generation_id"] == self._active_generation_id:
            self._discard(staging_dir, "target matches the active "
                          "generation", own=True)
            self._sync_state(target, None)
            return

        # -- per-status continuation ----------------------------------------
        status = progress.get("status")
        if status == "blocked":
            self._sync_state(target, progress)
            return  # parked: blocked until retry() or a target change
        if status == "ready":
            self._reverify_ready(staging_dir, progress)
        else:
            self._resume_build(staging_dir, progress, target)
        progress = self._load_progress(staging_dir)
        if progress is not None and progress.get("status") == "discarded":
            # The gate or the reopen verification invalidated the staging:
            # start the fresh build right away (one step per cycle).
            self._start_build(staging_dir, target)
            progress = self._load_progress(staging_dir)
        self._sync_state(target, progress)

    # ------------------------------------------------------------------
    # Live-record location and stale invalidation
    # ------------------------------------------------------------------

    def _find_own_record(self, facts_epoch, desired_representation_id):
        """The machine's own live staging record, or None.

        The build is pinned to the H0 of its start, so after facts
        advanced the record lives under a different generation id than
        today's fresh target; the only way to locate it is a read of the
        staging namespace.  A record is "live" only when its epoch, desired
        representation and builder version all match the current
        configuration and its status is running/blocked/ready -- the delta
        machine's transient one-shot staging carries the ACTIVE
        representation and can therefore never be selected here.  This is
        selection of the machine's OWN build, never "scanning the
        directory to guess the latest generation" (spec clause).
        """
        staging_root = os.path.join(self._derived_root, "staging")
        try:
            entries = os.listdir(staging_root)
        except OSError:
            return None
        for entry in sorted(entries):
            path = os.path.join(staging_root, entry)
            if not os.path.isdir(path):
                continue
            progress = self._load_progress(path)
            if progress is None:
                continue
            if progress.get("status") not in ("running", "blocked", "ready"):
                continue
            identity = progress.get("identity") or {}
            if identity.get("store_epoch") != facts_epoch:
                continue
            if identity.get("representation_id") != desired_representation_id:
                continue
            if identity.get("builder_version") != BUILD_VERSION:
                continue
            return path, progress
        return None

    def _mark_stale_records_discarded(self, facts_epoch,
                                      desired_representation_id,
                                      keep_dir=None):
        """Best-effort: invalidate every staging record that is not the
        machine's live build (spec "目标版本或 epoch 改变时废弃旧 staging").

        Records are marked with the precise reason (epoch / desired /
        builder version change, or an obsolete target), never deleted:
        physical cleanup belongs to clear and #66 retention.  The delta
        machine's transient one-shot staging is a different id and a mark
        it never reads is harmless.
        """
        staging_root = os.path.join(self._derived_root, "staging")
        try:
            entries = os.listdir(staging_root)
        except OSError:
            return
        for entry in entries:
            path = os.path.join(staging_root, entry)
            if path == keep_dir or not os.path.isdir(path):
                continue
            progress = self._load_progress(path)
            if progress is None or progress.get("status") == "discarded":
                continue
            identity = progress.get("identity") or {}
            if identity.get("store_epoch") != facts_epoch:
                reason = "fact store epoch changed"
            elif identity.get("representation_id") \
                    != desired_representation_id:
                reason = "desired representation changed"
            elif identity.get("builder_version") != BUILD_VERSION:
                reason = "builder version changed"
            else:
                reason = "obsolete staging of a previous target"
            self._discard(path, reason)

    # ------------------------------------------------------------------
    # Target derivation and the resume gate
    # ------------------------------------------------------------------

    def _compute_target(self):
        """The fresh desired target over the current facts snapshot."""
        store_epoch, source_hlc, events = _read_snapshot(self._facts_root)
        return _prepare_target(events, self._provider, store_epoch,
                               source_hlc)

    def _resume_gate(self, progress):
        """AC64-3 gate: epoch, H0, all fingerprints and the builder version
        must all match the recorded target, or the staging is discarded.

        Recomputes the pinned target from the facts at the recorded H0
        (facts are immutable within one epoch, so a mismatch is a genuine
        drift -- tampered record, replaced store, changed representation or
        code), compares the composed generation id and the rows
        fingerprint, and returns ``(events, pinned)``: the pinned event
        list and the pinned target dict for continuation.
        """
        recorded = progress["identity"]
        store_epoch, source_hlc, events = _read_snapshot(
            self._facts_root,
            as_of=(recorded["source_hlc"][0], recorded["source_hlc"][1]))
        if store_epoch != recorded["store_epoch"]:
            raise _ResumeGateError(
                "fact store epoch %r does not match the recorded %r"
                % (store_epoch, recorded["store_epoch"]))
        try:
            pinned = _prepare_target(events, self._provider, store_epoch,
                                     source_hlc)
        except BuildBlockedError as error:
            raise _ResumeGateError(
                "pinned events no longer validate: %s" % error.message)
        if pinned["generation_id"] != progress["generation_id"]:
            raise _ResumeGateError(
                "target identity or fingerprints no longer match the "
                "recorded target (recorded %s, recomputed %s)"
                % (progress["generation_id"], pinned["generation_id"]))
        if pinned["rows_fingerprint"] != progress.get("rows_fingerprint"):
            raise _ResumeGateError(
                "rows fingerprint no longer matches the recorded target")
        return events, pinned

    # ------------------------------------------------------------------
    # Build steps
    # ------------------------------------------------------------------

    def _start_build(self, staging_dir, target):
        """Begin a fresh build: own the directory and fix the target.

        A stale directory for the same (content-addressed) target is
        cleared first -- it is this machine's own staging and was never
        verified, so removing it loses nothing.  The chunk embedding runs
        on the next cycle via ``_resume_build`` (one state-machine step
        per cycle: no unbounded recursion on repeated failures).
        """
        try:
            if os.path.isdir(staging_dir) and not os.path.islink(
                    staging_dir):
                shutil.rmtree(staging_dir)
            elif os.path.lexists(staging_dir):
                os.unlink(staging_dir)
            os.makedirs(staging_dir, mode=0o700)
        except OSError as error:
            self._set_last_error("cannot start the staging build: %s"
                                 % error)
            return
        progress = {
            "progress_version": STAGING_PROGRESS_VERSION,
            "generation_id": target["generation_id"],
            "status": "running",
            "total_rows": len(target["rows"]),
            "rows_fingerprint": target["rows_fingerprint"],
            "identity": target["identity"],
            "chunks": [],
        }
        try:
            self._write_progress(staging_dir, progress)
        except OSError as error:
            self._set_last_error("cannot write the staging progress: %s"
                                 % error)
            return
        with self._condition:
            self._blocked = None
            self._blocked_epoch = None
            self._ready_verified = False
            self._last_error = None

    def _resume_build(self, staging_dir, progress, pinned):
        """Resume from the last verified chunk, or finalize a completed
        build (SCN-64-2: 瞬时中断从最后已验证块续跑).

        The resume gate runs first (AC64-3) and yields the pinned target
        (the recorded H0 and event list); then the recorded chunks are
        re-verified against the vectors file; the file is truncated to the
        last verified chunk and embedding continues from there.  One chunk
        is embedded per cycle, so every intermediate state is a
        crashable resting state; a completed chunk is never re-embedded.
        A gate or verification failure discards the staging; the fresh
        build starts on the next cycle.
        """
        vectors_path = os.path.join(staging_dir, "vectors.fp32")
        dimension = pinned["identity"]["vector_dimension"]
        total_rows = progress.get("total_rows")
        try:
            events, pinned = self._resume_gate(progress)
        except _ResumeGateError as error:
            self._discard(staging_dir, error.reason, own=True)
            return
        except BuildError as error:
            self._set_last_error("resume gate read failed: %s" % error)
            return
        try:
            next_row, prefix_sha = _verify_progress_chunks(
                progress, vectors_path, dimension)
        except BuildProgressError as error:
            self._discard(staging_dir, error.reason, own=True)
            return
        if next_row < total_rows:
            try:
                with self._lease():
                    _build_chunks(staging_dir, vectors_path, events,
                                  self._provider, dimension,
                                  self._chunk_rows,
                                  progress["generation_id"], progress,
                                  start_row=next_row,
                                  prefix_digest=prefix_sha, chunk_limit=1)
            except BuildBlockedError as error:
                self._enter_blocked(error, staging_dir, progress)
            return  # one chunk per cycle; the next cycle continues
        if not os.path.isfile(vectors_path):
            # An empty build never embeds; materialize the empty vectors
            # file so the final manifest and the reopen verification see
            # the canonical container.
            try:
                fd = os.open(vectors_path,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            except OSError as error:
                self._set_last_error("cannot create the empty vectors file:"
                                     " %s" % error)
                return
        self._finalize_build(staging_dir, progress, pinned, events,
                             prefix_sha.copy().hexdigest())

    def _finalize_build(self, staging_dir, progress, pinned, events,
                        vectors_sha256):
        """metadata + fixed exact-oracle probes + final manifest, then the
        full reopen self-verification (spec clause 6) and the ready mark.

        Idempotent across crashes: already-written immutable files are
        reused and re-verified, never rewritten.
        """
        vectors_path = os.path.join(staging_dir, "vectors.fp32")
        metadata_path = os.path.join(staging_dir, "metadata.json")
        manifest_path = os.path.join(staging_dir, "manifest.json")
        dimension = pinned["identity"]["vector_dimension"]
        try:
            if not os.path.isfile(metadata_path):
                _write_metadata(metadata_path, pinned["rows"])
            if not os.path.isfile(manifest_path):
                try:
                    probes = _compute_probes(
                        self._facts_root, self._provider, events,
                        pinned["rows"], vectors_path, dimension,
                        self._probe_params,
                        (pinned["identity"]["source_hlc"][0],
                         pinned["identity"]["source_hlc"][1]))
                except BuildBlockedError as error:
                    self._enter_blocked(error, staging_dir, progress)
                    return
                manifest_bytes = _compose_manifest(
                    pinned["identity"], pinned["generation_id"],
                    pinned["rows_fingerprint"], len(pinned["rows"]),
                    progress["chunks"], probes, metadata_path, vectors_path,
                    vectors_sha256)
                _write_file(manifest_path, manifest_bytes)
                self._fsync_directory(staging_dir)
        except BuildBlockedError as error:
            self._enter_blocked(error, staging_dir, progress)
            return
        except OSError as error:
            self._set_last_error("staging finalize failed: %s" % error)
            return
        try:
            self._verify_container_dance(staging_dir)
        except GenerationRejected as error:
            self._discard(staging_dir, "reopen verification failed: %s"
                          % error.reason, own=True)
            return
        progress["status"] = "ready"
        try:
            self._write_progress(staging_dir, progress)
        except OSError as error:
            self._set_last_error("cannot mark the staging ready: %s"
                                 % error)
            return
        with self._condition:
            self._ready_generation_id = pinned["generation_id"]
            self._ready_staging_dir = staging_dir
            self._last_error = None
            self._condition.notify_all()

    def _reverify_ready(self, staging_dir, progress):
        """Reopen-verify a ready staging once after a restart.

        The ready staging is immutable since its verification, so the
        full re-check runs at most once per machine start; a staging that
        fails it is discarded and rebuilt (never served, never published).
        """
        if self._ready_verified:
            return
        try:
            self._resume_gate(progress)
        except _ResumeGateError as error:
            self._discard(staging_dir, error.reason, own=True)
            return
        except BuildError as error:
            self._set_last_error("ready gate read failed: %s" % error)
            return
        try:
            self._verify_container_dance(staging_dir)
        except GenerationRejected as error:
            self._discard(staging_dir, "ready staging failed re-"
                          "verification: %s" % error.reason, own=True)
            return
        with self._condition:
            self._ready_verified = True
            # A machine that found an already-ready record (e.g. after a
            # restart) surfaces the same ready state as one that built it,
            # so the #65 publisher can pick it up.
            self._ready_generation_id = progress["generation_id"]
            self._ready_staging_dir = staging_dir

    def _verify_container_dance(self, staging_dir):
        """Run the full reopen verification with progress.json moved aside.

        ``open_generation`` requires exactly the three immutable files, so
        the transient progress file is renamed out of the container (into
        the staging root) for the verification and back after it.  Raises
        ``GenerationRejected`` on the first failing check; the caller
        discards the staging.  A crash inside the dance leaves the staging
        without progress, which the next start treats as a leftover and
        rebuilds from scratch.
        """
        progress_path = os.path.join(staging_dir, PROGRESS_FILENAME)
        tmp_path = os.path.join(os.path.dirname(staging_dir),
                                ".verify-%s.tmp"
                                % os.path.basename(staging_dir))
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        os.rename(progress_path, tmp_path)
        try:
            opened = open_generation(staging_dir)
            opened.close()
        finally:
            try:
                os.rename(tmp_path, progress_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Blocked semantics
    # ------------------------------------------------------------------

    def _enter_blocked(self, error, staging_dir, progress):
        """Persist the block (status blocked + the named events), then
        publish it.  A deterministic block parks the worker until
        ``retry()`` or a target/epoch change (SCN-64-5; spec: blocked
        staging 不自动重试, 不静默跳过).
        """
        if progress is not None and staging_dir is not None:
            record = dict(progress)
            record["status"] = "blocked"
            record["blocked_events"] = list(error.blocked_events)
            record["reason"] = error.message
            record["phase"] = error.phase
            try:
                self._write_progress(staging_dir, record)
            except OSError:
                pass  # best effort; the block re-derives on restart
        identity = read_facts_identity(self._facts_root)
        with self._condition:
            self._blocked = error
            self._blocked_epoch = identity[0] if identity is not None \
                else None
            self._condition.notify_all()

    def retry(self):
        """Clear a deterministic block; the worker resumes from the last
        verified chunk (spec: 维护者显式重试).
        """
        with self._condition:
            if self._closed:
                return
            self._blocked = None
            self._blocked_epoch = None
            self._ready_verified = False
        staging_dir = self._current_dir
        progress = self._current_progress
        if (staging_dir is not None and progress is not None
                and progress.get("status") == "blocked"):
            record = dict(progress)
            record["status"] = "running"
            try:
                self._write_progress(staging_dir, record)
            except OSError:
                pass
        with self._condition:
            self._condition.notify_all()
            self._wake_event.set()

    # ------------------------------------------------------------------
    # Discard and cleanup
    # ------------------------------------------------------------------

    def _discard(self, staging_dir, reason, own=False):
        """Mark a staging record discarded; never delete it.

        A discarded staging is never resumed or partially reused
        (SCN-64-4).  The record keeps the diagnosis (status, reason,
        identity, chunks); physical deletion belongs to clear and the #66
        retention work.  ``own=True`` also resets the machine's in-memory
        build state (only for the machine's own current staging).
        """
        if os.path.isdir(staging_dir):
            progress = self._load_progress(staging_dir)
            if progress is not None and progress.get("status") != "discarded":
                progress["status"] = "discarded"
                progress["reason"] = reason
                try:
                    self._write_progress(staging_dir, progress)
                except OSError:
                    pass
        with self._condition:
            self._last_discard_reason = reason
            if own:
                self._ready_verified = False
                self._blocked = None
                self._blocked_epoch = None
                self._last_error = None
                self._ready_generation_id = None
                self._ready_staging_dir = None

    # ------------------------------------------------------------------
    # Publish seams (#65): the publisher calls these under the publish
    # lock, so none of them can race a worker cycle.
    # ------------------------------------------------------------------

    def provider(self):
        """The current desired provider (the publisher's embed seam)."""
        with self._condition:
            return self._provider

    def verify_publishable(self, staging_dir):
        """The #65 publish preconditions over one ready staging.

        Re-loads the record (it must be the machine's own ``ready``
        staging), re-runs the resume gate (epoch / H0 / fingerprints /
        builder version, recomputed from the facts at the recorded H0) and
        the full reopen verification -- file checksums, chunk records,
        row/event bijection, vector finiteness + unit norm, and the fixed
        exact-oracle probes (spec clause 6; AC65-1) -- with the progress
        record parked outside the container.  Returns ``(progress, pinned)``
        on success; raises ``StagingError`` naming the first failing check
        on any failure.
        """
        progress = self._load_progress(staging_dir)
        if progress is None:
            raise StagingError("staging record missing or unusable")
        if progress.get("status") != "ready":
            raise StagingError("staging status is %r, need ready"
                               % progress.get("status"))
        try:
            events, pinned = self._resume_gate(progress)
        except _ResumeGateError as error:
            raise StagingError("staging resume gate failed: %s"
                               % error.reason)
        except BuildError as error:
            raise StagingError("staging resume gate read failed: %s"
                               % error)
        try:
            self._verify_container_dance(staging_dir)
        except GenerationRejected as error:
            raise StagingError("staging reopen verification failed: %s"
                               % error.reason)
        return progress, pinned

    def publish_reject(self, staging_dir, reason):
        """#65: a ready staging that fails the publish preconditions is
        marked discarded -- never published, rebuilt on the next cycle."""
        self._discard(staging_dir, reason, own=True)

    def publish_block(self, reason, blocked_events, phase="delta"):
        """#65: record a deterministic publish-time block on the ready
        staging (spec: 确定性失败保持 blocked; the fault names the events).

        The publisher owns the publish lock while calling this, so it never
        races the worker; the worker re-derives the block from the record
        on its next cycle (``retry()`` clears it).
        """
        staging_dir = self._ready_staging_dir
        progress = (self._load_progress(staging_dir)
                    if staging_dir is not None else None)
        if progress is None or progress.get("status") != "ready":
            return
        record = dict(progress)
        record["status"] = "blocked"
        record["blocked_events"] = list(blocked_events)
        record["reason"] = reason
        record["phase"] = phase
        try:
            self._write_progress(staging_dir, record)
        except OSError:
            pass  # best effort; the block re-derives on restart
        with self._condition:
            self._ready_verified = False
            self._ready_generation_id = None
            self._ready_staging_dir = None

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _write_progress(self, staging_dir, progress):
        _write_atomic(os.path.join(staging_dir, PROGRESS_FILENAME),
                      _canonical_json(progress).encode("utf-8"))

    def _load_progress(self, staging_dir):
        """The staging's progress record, or None if unusable.

        A missing, unreadable, version-unknown or identity-mismatched
        record returns None: the cycle then discards the directory as a
        leftover and builds fresh (a record that cannot be gated must not
        be resumed).
        """
        path = os.path.join(staging_dir, PROGRESS_FILENAME)
        if not os.path.isfile(path):
            return None
        try:
            value = _read_json_file(path, "progress")
        except GenerationRejected:
            return None
        if (value.get("progress_version") != STAGING_PROGRESS_VERSION
                or value.get("generation_id") != os.path.basename(staging_dir)
                or value.get("status") not in ("running", "blocked", "ready",
                                               "discarded")):
            return None
        for key in ("total_rows", "rows_fingerprint", "identity", "chunks"):
            if key not in value:
                return None
        if not isinstance(value["identity"], dict) or not isinstance(
                value["chunks"], list):
            return None
        return value

    def _fsync_directory(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _lease(self):
        if self._builder_lock is None:
            yield
            return
        with self._builder_lock:
            yield

    def _staging_dir(self, generation_id):
        return os.path.join(self._derived_root, "staging", generation_id)

    def _published_dir(self, generation_id):
        return os.path.join(self._derived_root, "generations", generation_id)

    def _set_last_error(self, message):
        with self._condition:
            self._last_error = message
            self._condition.notify_all()

    def _sync_state(self, target, progress):
        with self._condition:
            self._current_dir = (self._staging_dir(target["generation_id"])
                                 if target is not None else None)
            self._target_generation_id = (target["generation_id"]
                                          if target is not None else None)
            self._current_progress = (dict(progress)
                                      if progress is not None else None)

    # ------------------------------------------------------------------
    # Builder seams (maintenance quiesce; not registered with the
    # coordinator -- see docs/staging-resumable-build.md)
    # ------------------------------------------------------------------

    def retarget(self, provider):
        """Swap the desired provider (spec: 新 desired fingerprint 可以
        取消尚未发布的旧 staging).

        The next cycle detects the representation change and discards the
        old staging in full.  The active configuration is never touched --
        desired never reinterprets the active generation.
        """
        if not isinstance(provider, RepresentationProvider):
            raise StagingError("provider must be a RepresentationProvider")
        representation_id_value = provider.representation_id()
        if not representation_id_value or not isinstance(
                representation_id_value, str):
            raise StagingError("provider representation_id must be a "
                               "non-empty string")
        dimension = provider.vector_dimension()
        if not isinstance(dimension, int) or dimension < 1:
            raise StagingError("provider vector_dimension must be a "
                               "positive integer")
        with self._condition:
            self._provider = provider
            self._ready_verified = False
            self._condition.notify_all()
            self._wake_event.set()

    def request_stop(self):
        self._stop_event.set()
        self._wake_event.set()

    def start(self):
        self._stop_event.clear()
        self._wake_event.set()

    def wait_idle(self, timeout=30.0):
        return self._idle_event.wait(timeout)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def status(self):
        """A copy of the machine's observable state (tests + status)."""
        with self._condition:
            progress = self._current_progress
            blocked = (self._blocked is not None
                       or (progress is not None
                           and progress.get("status") == "blocked"))
            blocked_events = []
            if self._blocked is not None:
                blocked_events = list(self._blocked.blocked_events)
            elif progress is not None and progress.get("status") == "blocked":
                blocked_events = list(progress.get("blocked_events") or [])
            return {
                "desired_representation_id":
                    self._provider.representation_id(),
                "active_representation_id": self._active_representation_id,
                "active_generation_id": self._active_generation_id,
                "target_generation_id": self._target_generation_id,
                "staging_dir": self._current_dir,
                "progress": (dict(progress)
                             if progress is not None else None),
                "blocked": blocked,
                "blocked_events": blocked_events,
                "ready_generation_id": self._ready_generation_id,
                "ready_staging_dir": self._ready_staging_dir,
                "last_error": self._last_error,
                "last_discard_reason": self._last_discard_reason,
            }

    def health(self):
        with self._condition:
            progress = self._current_progress
            return {
                "staging_target_generation_id": self._target_generation_id,
                "staging_status": (progress.get("status")
                                   if progress is not None else "idle"),
                "staging_total_rows": (progress.get("total_rows")
                                       if progress is not None else None),
                "staging_chunks": (len(progress.get("chunks") or [])
                                   if progress is not None else 0),
                "staging_blocked": self._blocked is not None,
                "staging_ready_generation_id": self._ready_generation_id,
                "staging_last_error": self._last_error,
                "staging_last_discard_reason": self._last_discard_reason,
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
            self._current_dir = None
            self._current_progress = None


# ---------------------------------------------------------------------------
# Config wiring (server.py builds the machine when the config declares it)
# ---------------------------------------------------------------------------

def build_staging_machine_from_config(facts_root, config, builder_lock=None,
                                      active_generation_id=None,
                                      active_representation_id=None,
                                      publish_lock=None):
    """Construct the staging machine from the evidence config dict.

    The config distinguishes desired from active (spec "配置区分 desired 与
    active"; the desired configuration never reinterprets the active
    generation):

        derived_root: <path>             where staging/ + generations/ live
        generation_id: <id>              the ACTIVE base generation to serve
        desired_representation_id: <id>  the desired target representation
                                         (default: the configured
                                         ``representation_id`` == the active
                                         one, i.e. "nothing to build")

    Returns None when neither ``derived_root`` nor ``generation_id`` is
    declared (mirrors the delta machine's gate); declaring only one is a
    configuration fault.  ``active_generation_id`` /
    ``active_representation_id`` (#65) override the config's declared
    active with the durable active manifest, exactly like the delta
    machine's seam, so the machine gates against what is actually active.
    ``publish_lock`` (#65) serializes every state-machine cycle with the
    publish transaction (see the constructor).
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
        active_representation_id_value = config["representation_id"]
        if (not active_representation_id_value or not isinstance(
                active_representation_id_value, str)):
            raise ValueError("representation_id must be a non-empty string")
        if active_representation_id is not None:
            if not isinstance(active_representation_id, str) \
                    or not active_representation_id:
                raise ValueError("active_representation_id must be a "
                                 "non-empty string")
            active_representation_id_value = active_representation_id
        desired_representation_id = config.get(
            "desired_representation_id", active_representation_id_value)
        if (not desired_representation_id or not isinstance(
                desired_representation_id, str)):
            raise ValueError("desired_representation_id must be a non-empty "
                             "string")
        poll = float(config.get("staging_poll_interval_ms", 2000)) / 1000.0
        if poll <= 0:
            raise ValueError("staging_poll_interval_ms must be positive")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed staging config: %s" % error)
    provider = _build_desired_provider(config, desired_representation_id)
    return StagingBuildMachine(
        facts_root, derived_root, provider, active_representation_id_value,
        generation_id, poll_interval=poll, builder_lock=builder_lock,
        publish_lock=publish_lock)


def _build_desired_provider(config, desired_representation_id):
    """The fixture representation seam behind the desired target (mirrors
    delta.py's provider construction; the real hidden-state provider plugs
    at the same seam in the integration harness)."""
    from evidence import FixtureRepresentationProvider
    try:
        query_vectors = config.get("query_vectors") or {}
        event_vectors = config.get("event_vectors") or {}
        default_query = config.get("default_query")
        default_event = config.get("default_event")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed evidence config: %s" % error)
    return FixtureRepresentationProvider(
        desired_representation_id,
        query_vectors,
        event_vectors,
        default_query=(default_query if default_query is not None
                       else (1.0, 0.0, 0.0, 0.0)),
        default_event=(default_event if default_event is not None
                       else (0.0, 1.0, 0.0, 0.0)))
