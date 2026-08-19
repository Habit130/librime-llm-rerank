#!/usr/bin/env python3
"""Derived-state retention, rollback and damage isolation (Habit130/squirrel#67).

On top of the #65 atomic publish (the durable active manifest + pointer swap)
and the #66 compatibility matrix (the single reuse/load authority), this
module owns the *lifecycle* of derived generations under one derived root:

- **One active, one healthy rollback, one staging** (spec "压代、保留与回退"):
  after a successful publish the just-retired **healthy** active becomes the
  rollback; a damaged active is isolated and never registered.  Generations
  that fall outside {active, rollback, current staging} are deleted by the
  retention sweep.  The sweep never deletes the only rollback (or the active
  or a live staging) -- a space-short build keeps the current active and
  reports the error instead.
- **Explicit rollback pointer**: ``<derived_root>/rollback_manifest.json``
  next to ``active_manifest.json`` (``clear`` already allowlists that name).
  The pointer is the ONLY recovery source -- recovery never scans
  ``generations/`` to "pick the newest" (spec: 不扫描目录猜测"最新"generation).
- **Isolation** (spec "损坏处理"): a bad active/rollback generation is moved
  under ``<derived_root>/isolated/<id>-<ts>/`` -- app-controlled derived
  state (not the #57 facts quarantine), never served, deleted by ``clear``
  (the ``isolated`` directory is allowlisted there).
- **Space** (spec "构建前预估三份派生状态的峰值空间"): before a build the
  peak of active + rollback + staging (+ their delta checkpoints) is
  estimated against a budget; when short the current active is kept and the
  build reports the error -- the only rollback is never deleted to free
  space.

The delta machine's recovery path (``_recover_via_rollback``) consumes this
module: it isolates a damaged active, re-verifies the rollback generation
(``open_generation`` -- identity + checksums + probes) and catches its delta
checkpoint up to the current facts watermark **before** it may serve
(AC67-5); a catch-up failure is not a semantic success (fail closed).  When
no healthy rollback exists the semantic path fails closed and a background
rebuild from facts is queued (AC67-6) -- fact recording / IME commit keep
working (this module never touches facts).
"""

import json
import os
import time

from generation import GENERATION_FILES, _canonical_json, _read_json_file, \
    _write_atomic

ROLLBACK_MANIFEST_FILENAME = "rollback_manifest.json"
ROLLBACK_MANIFEST_VERSION = "rollback-manifest-v1"

ISOLATED_DIRNAME = "isolated"

# Spec #43 disk gate (memory/disk 门槛): active + rollback + staging + delta
# <= 3 GiB.  The daemon's space estimate uses this as the default budget;
# operators may raise it via ``derived_disk_budget_bytes``.
DEFAULT_DERIVED_DISK_BUDGET_BYTES = 3 * 1024 * 1024 * 1024

_ROLLBACK_KEYS = (
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
    "registered_at_ms",
)


class RetentionError(Exception):
    """A true fault of the retention / rollback path."""


def _validate_rollback_manifest(manifest):
    """A diagnosis string for an unusable rollback manifest, else None."""
    if not isinstance(manifest, dict):
        return "rollback manifest must be a JSON object"
    if manifest.get("manifest_version") != ROLLBACK_MANIFEST_VERSION:
        return "rollback manifest version %r unsupported" % (
            manifest.get("manifest_version"))
    for key in _ROLLBACK_KEYS:
        if key not in manifest:
            return "rollback manifest key %s missing" % key
    if not isinstance(manifest["generation_id"], str) \
            or not manifest["generation_id"]:
        return "rollback manifest generation_id missing"
    if not isinstance(manifest["store_epoch"], str) \
            or not manifest["store_epoch"]:
        return "rollback manifest store_epoch missing"
    source_hlc = manifest["source_hlc"]
    if (not isinstance(source_hlc, list) or len(source_hlc) != 2
            or not all(isinstance(value, int) and value >= 0
                       for value in source_hlc)):
        return "rollback manifest source_hlc malformed"
    for key in ("fact_schema_version", "representation_id",
                "vector_format_version", "projection_version",
                "index_fingerprint", "delta_checkpoint", "builder_version"):
        if not isinstance(manifest[key], str) or not manifest[key]:
            return "rollback manifest %s missing" % key
    if not isinstance(manifest["registered_at_ms"], int):
        return "rollback manifest registered_at_ms must be an integer"
    return None


def read_rollback_manifest(derived_root):
    """``(manifest, reason)``: the explicit rollback pointer, or None.

    ``reason`` is None when the file is absent (no rollback) and a diagnosis
    string when it is present but unusable (the caller must treat an
    unusable pointer exactly like no rollback -- never guess a replacement).
    """
    path = os.path.join(derived_root, ROLLBACK_MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as error:
        return None, "rollback manifest unreadable: %s" % error
    problem = _validate_rollback_manifest(value)
    if problem is not None:
        return None, problem
    return value, None


def write_rollback_manifest(derived_root, manifest):
    """Atomically replace the rollback pointer (temp + fsync + rename)."""
    _write_atomic(
        os.path.join(derived_root, ROLLBACK_MANIFEST_FILENAME),
        _canonical_json(manifest).encode("utf-8"))


def clear_rollback_manifest(derived_root):
    """Remove the rollback pointer (best effort; a stale pointer is treated
    as no rollback by every reader)."""
    try:
        os.unlink(os.path.join(derived_root, ROLLBACK_MANIFEST_FILENAME))
    except OSError:
        pass


def compose_rollback_manifest(generation, delta_checkpoint, fact_schema_version):
    """The rollback pointer over one verified, healthy generation.

    Mirrors the active manifest's identity layers so a rollback can be
    re-verified field by field against the current facts / runtime before it
    is served (AC67-5).
    """
    identity = generation.identity()
    return {
        "manifest_version": ROLLBACK_MANIFEST_VERSION,
        "generation_id": generation.generation_id,
        "store_epoch": identity["store_epoch"],
        "source_hlc": identity["source_hlc"],
        "fact_schema_version": fact_schema_version,
        "representation_id": identity["representation_id"],
        "vector_format_version": identity["vector_format"],
        "projection_version": identity["projection_version"],
        "index_fingerprint": identity["index_fingerprint"],
        "delta_checkpoint": delta_checkpoint,
        "builder_version": identity["builder_version"],
        "registered_at_ms": int(time.time() * 1000),
    }


def register_healthy_rollback(derived_root, generation, delta_checkpoint,
                              fact_schema_version):
    """Register one verified generation as the rollback pointer.

    The caller has already run ``open_generation`` (identity + checksums +
    probes); only a healthy generation may be registered (a damaged active
    is isolated, never registered -- SCN-67-2).  Replaces any previous
    rollback (the older one is dropped by the retention sweep).
    """
    write_rollback_manifest(
        derived_root,
        compose_rollback_manifest(generation, delta_checkpoint,
                                  fact_schema_version))


# ---------------------------------------------------------------------------
# Isolation (spec "损坏处理" seam 6)
# ---------------------------------------------------------------------------

def isolate_generation(derived_root, generation_id, reason):
    """Move a damaged generation out of ``generations/`` into isolation.

    The app-controlled ``isolated/<id>-<ts>/`` directory is never served
    (nothing scans it) and is deleted by ``clear`` (the ``isolated`` name is
    allowlisted there).  ``clear``'s derived allowlist already covers it --
    this is derived-state isolation, deliberately NOT the #57 facts
    quarantine.  Best effort: the caller treats an isolation failure as a
    refusal to serve that generation, never as a reason to serve it.
    """
    source = os.path.join(derived_root, "generations", generation_id)
    if not os.path.isdir(source):
        return  # nothing to isolate (already gone / never published)
    isolated_root = os.path.join(derived_root, ISOLATED_DIRNAME)
    try:
        os.makedirs(isolated_root, mode=0o700, exist_ok=True)
        target = os.path.join(isolated_root,
                              "%s-%d" % (generation_id, int(time.time() * 1000)))
        os.rename(source, target)
        try:
            metadata = _canonical_json({
                "generation_id": generation_id,
                "isolated_at_ms": int(time.time() * 1000),
                "reason": reason,
            })
            fd = os.open(os.path.join(target, "metadata.json"),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600)
            try:
                os.write(fd, metadata.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass  # best effort metadata; the isolation itself is durable
    except OSError:
        # Isolation failed: the bad generation stays put, but the caller
        # must still refuse to serve it.
        return


# ---------------------------------------------------------------------------
# Space estimation (spec "构建前预估三份派生状态的峰值空间")
# ---------------------------------------------------------------------------

def _dir_bytes(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def estimate_derived_bytes(derived_root):
    """Current on-disk bytes of active + rollback + staging + delta.

    Walks only the app-controlled derived namespaces under ``derived_root``
    (generations/, staging/, delta/, isolated/) plus the two manifests; it
    never touches facts or anything outside the derived root.
    """
    total = 0
    for name in ("generations", "staging", "delta", ISOLATED_DIRNAME):
        total += _dir_bytes(os.path.join(derived_root, name))
    for name in ("active_manifest.json", ROLLBACK_MANIFEST_FILENAME):
        path = os.path.join(derived_root, name)
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


def projected_peak_bytes(derived_root, projected_staging_bytes=0):
    """The peak of the three derived copies + deltas during a build.

    ``projected_staging_bytes`` is the caller's estimate of the in-flight
    build (rows x dimension x 4 for the vector file, plus a small constant);
    the peak is the current footprint plus that projected container.
    """
    current = estimate_derived_bytes(derived_root)
    return current + int(projected_staging_bytes)


def check_build_space(derived_root, budget_bytes,
                      projected_staging_bytes=0):
    """``(ok, reason)``: is a build within the derived disk budget?

    Space-short never deletes anything -- the current active (and the only
    rollback) are kept and the build reports the error (SCN-67-3).
    """
    if budget_bytes is None:
        return True, None
    peak = projected_peak_bytes(derived_root, projected_staging_bytes)
    if peak > budget_bytes:
        return False, ("derived disk budget exceeded: estimated peak %d "
                       "bytes > budget %d bytes; keeping the current active, "
                       "not deleting any rollback" % (peak, budget_bytes))
    return True, None


# ---------------------------------------------------------------------------
# Retention sweep (seam 1): <=1 active, <=1 rollback, <=1 staging
# ---------------------------------------------------------------------------

def _staging_progress(derived_root, staging_dir):
    """Read one staging progress record (or None if unusable)."""
    try:
        from staging import STAGING_PROGRESS_VERSION
        path = os.path.join(staging_dir, "progress.json")
        if not os.path.isfile(path):
            return None
        value = _read_json_file(path, "progress")
        if value.get("progress_version") != STAGING_PROGRESS_VERSION:
            return None
        if value.get("generation_id") != os.path.basename(staging_dir):
            return None
        if value.get("status") not in ("running", "blocked", "ready",
                                       "discarded"):
            return None
        return value
    except Exception:  # noqa: BLE001 - best effort
        return None


def retention_sweep(derived_root, active_id, rollback_id=None,
                    live_staging_ids=()):
    """Delete derived state that falls outside {active, rollback, staging}.

    - ``generations/<id>`` is deleted unless ``id`` is the active or the
      rollback (never the only rollback, never the active).
    - ``delta/<id>`` checkpoints are deleted for deleted generations and for
      checkpoints that are neither active/rollback nor a live staging build's.
    - ``staging/<id>`` directories whose progress record is ``discarded``
      (or unusable) are deleted -- physical cleanup of records this machine
      already marked obsolete.  A live (running/blocked/ready) staging is
      kept (the current staging).
    - ``isolated/`` is never swept here (``clear`` owns it; a damaged
      generation must remain inspectable until the operator clears).

    The sweep never runs mid-publish: the publisher calls it only after a
    successful publish (or the server once at startup) -- never inside the
    manifest swap (SCN-67-2/3).
    """
    keep = set()
    if active_id:
        keep.add(active_id)
    if rollback_id:
        keep.add(rollback_id)
    live_staging = set(live_staging_ids or ())

    generations_root = os.path.join(derived_root, "generations")
    try:
        entries = os.listdir(generations_root)
    except OSError:
        entries = []
    for entry in entries:
        if entry in keep:
            continue
        path = os.path.join(generations_root, entry)
        if os.path.isdir(path):
            try:
                import shutil
                shutil.rmtree(path)
            except OSError:
                pass

    delta_root = os.path.join(derived_root, "delta")
    try:
        entries = os.listdir(delta_root)
    except OSError:
        entries = []
    for entry in entries:
        if entry in keep or entry in live_staging:
            continue
        path = os.path.join(delta_root, entry)
        if os.path.isdir(path):
            try:
                import shutil
                shutil.rmtree(path)
            except OSError:
                pass

    staging_root = os.path.join(derived_root, "staging")
    try:
        entries = os.listdir(staging_root)
    except OSError:
        entries = []
    for entry in entries:
        if entry in live_staging:
            continue
        path = os.path.join(staging_root, entry)
        if not os.path.isdir(path):
            continue
        if entry.endswith(".tmp"):
            # Transient parked progress records (verify dance): safe to drop.
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        # Only a staging the machine EXPLICITLY marked discarded is deleted
        # here.  A running/blocked/ready record is the current staging (kept
        # regardless of the live-staging list -- that list is a best-effort
        # read and a momentarily parked progress (verify dance) must never
        # look deletable).  A dir with no readable record is left for the
        # staging machine's own discard logic, never guessed at here.
        try:
            progress = _staging_progress(derived_root, path)
        except Exception:  # noqa: BLE001 - best effort
            progress = None
        if progress is not None and progress.get("status") == "discarded":
            try:
                import shutil
                shutil.rmtree(path)
            except OSError:
                pass


def live_staging_generation_ids(derived_root):
    """The generation ids of running/blocked/ready staging records."""
    ids = []
    staging_root = os.path.join(derived_root, "staging")
    try:
        entries = os.listdir(staging_root)
    except OSError:
        return ids
    for entry in entries:
        path = os.path.join(staging_root, entry)
        if not os.path.isdir(path) or entry.endswith(".tmp"):
            continue
        try:
            progress = _staging_progress(derived_root, path)
        except Exception:  # noqa: BLE001 - best effort
            continue
        if progress is not None and progress.get("status") in (
                "running", "blocked", "ready"):
            ids.append(progress.get("generation_id"))
    return ids


def sweep_from_manifests(derived_root, active_id=None, rollback_id=None):
    """One retention pass resolved from the durable pointers.

    Reads the active + rollback manifests (if not given) and sweeps
    generations outside {active, rollback, live staging} -- the single
    shared implementation of the post-publish sweep (publish.py) and the
    startup sweep (server.py).  Best effort: a sweep fault never blocks the
    caller (a publish or a daemon start).
    """
    if active_id is None or rollback_id is None:
        from publish import read_active_manifest
        if active_id is None:
            manifest, _reason = read_active_manifest(derived_root)
            active_id = (manifest.get("generation_id")
                         if manifest is not None else None)
        if rollback_id is None:
            manifest, _reason = read_rollback_manifest(derived_root)
            rollback_id = (manifest.get("generation_id")
                           if manifest is not None else None)
    retention_sweep(derived_root, active_id=active_id,
                    rollback_id=rollback_id,
                    live_staging_ids=live_staging_generation_ids(
                        derived_root))
