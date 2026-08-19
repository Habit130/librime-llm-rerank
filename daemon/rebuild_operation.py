#!/usr/bin/env python3
"""The `rebuild` production operation type (Habit130/squirrel#68).

``squirrel-semantic-memory rebuild`` explicitly triggers a manual rebuild of
the derived state (FP32 vectors, projection, delta and index) from facts,
through the EXISTING #64/#65/#66/#67 staging machine -- never a second
builder.  Rebuild never modifies facts, ``history_id``, ``store_epoch`` or
the three schema switches, and never quiesces the plugin (spec #43 手动重建;
SCN-68-7/8).

Command surface (spec #43):

    rebuild            auto: the compatibility matrix chooses the minimum
                       safe scope; a healthy active that already matches the
                       desired identity returns ``already_current`` with no
                       new generation (AC68-1)
    rebuild --full     rebuild FP32 / projection / delta / index from facts
                       even when the fingerprint is unchanged; ONLY an
                       explicit ``--full`` mints a new generation for the
                       same fingerprint (AC68-2)
    rebuild --index-only
                       allowed only when a healthy compatible FP32 +
                       metadata + projection exist; otherwise an EXPLICIT
                       refusal, never a silent upgrade to full (AC68-3;
                       RISK-68-1)
    rebuild --retry <build_id>
                       continue an existing blocked/incomplete staging;
                       blocked builds never auto-retry (AC68-5)
    rebuild --restart  discard the staging, then rebuild from scratch
                       (distinct from retry; AC68-5)
    rebuild --wait     observe only; Ctrl-C detaches, never cancels (AC68-6)

Identity and idempotency (#52 / spec): the operation record carries a
persistent operation id AND a ``build_id`` (the staging generation id --
content-addressed), which are deliberately different.  The same target
already queued/building returns the same ``build_id``; the same operation id
with the same normalized parameters is idempotent, and the same operation id
with different parameters is rejected (SCN-68-4).

Phase machine (canonical subset; no quiesce -- spec: rebuild 不 quiesce 插件):

    preflight -> staging -> publishing -> cleanup

- ``publishing`` is the irreversible phase.  The ready staging is verified
  (checksum / event-set / vector / oracle probes -- the #65 publish gates)
  and published here; a cancel requested before it is honored, at/after it
  the cancel is refused as uncancellable (spec: backup 和 rebuild 在发布前
  可以取消; SCN-68-6).
- The staging step drives the injected #64 staging machine one cycle per
  runner step, so progress units are real (events / bytes / chunks / phase),
  never fake percentages (spec #43), and every intermediate state is a
  crashable resting state (the runner re-runs the step from the machine's
  durable progress record after a crash).
- ``already_current`` (auto + healthy matching active) skips staging and
  publishing entirely: no staging, no new generation, no rollback rotation
  (SCN-68-1 / AC68-1).

Injection seams (mirror clear/restore): the CLI/test host supplies the
representation provider factory (model-free fixture in tests; the real
hidden-state provider plugs at the same seam), the staging machine builder,
and an optional publish seam.  The live daemon is NOT required -- rebuild
drives the machine in the executor process, so it must never run against a
derived root that a daemon staging worker is simultaneously building (the
single-builder constraint is preserved by the caller: throwaway roots in
this ticket's envelope; RISK-68-2).

Output/log/error contract: only ids, hashes, phases, progress units, states
and error codes -- never 上文, candidate text or embeddings (spec #43).
"""

import os
import stat

import compat  # noqa: E402
from compat import (  # noqa: E402
    ACTION_NOOP,
    ACTION_REBUILD_INDEX,
    LAYER_REPRESENTATION,
    plan_actions,
    refuse_load_reason,
)
from delta import read_facts_identity, read_facts_schema_version  # noqa: E402
from generation import (  # noqa: E402
    PROJECTION_VERSION,
    VECTOR_FORMAT,
    _prepare_target,
    _read_snapshot,
    open_generation,
)
from operations import (  # noqa: E402
    OperationBlocked,
    OperationTypeSpec,
)

REBUILD_TYPE = "rebuild"
REBUILD_PHASES = ("preflight", "staging", "publishing", "cleanup")
REBUILD_IRREVERSIBLE_PHASE = "publishing"

MODE_AUTO = "auto"
MODE_FULL = "full"
MODE_INDEX_ONLY = "index_only"
MODES = (MODE_AUTO, MODE_FULL, MODE_INDEX_ONLY)

# Refusal codes for --index-only / precondition failures (deterministic ->
# blocked on the operations machine).
REFUSE_NO_ANN_SIDECAR = "no_ann_sidecar"
REFUSE_INDEX_ONLY_NO_BASE = "index_only_no_base"
REFUSE_INDEX_ONLY_UNHEALTHY_BASE = "index_only_unhealthy_base"
REFUSE_DERIVED_ROOT_UNCONFIGURED = "derived_root_unconfigured"
REFUSE_ACTIVE_UNKNOWN = "refuse_load"

# The active generation's ANN sidecar marker.  In the exact-only envelope
# there is no ANN sidecar to rebuild (RISK-66-1 / RISK-68-1): the default
# probe returns False and --index-only refuses with a stable reason unless a
# test injects a real sidecar.
ANN_SIDECAR_NAME = "index.ann"

# Cycles cap is defensive: the runner re-invokes the staging step (one
# machine cycle per step), and a bounded step guards against an unbounded
# single step if a machine ever spins without advancing.
MAX_STAGING_CYCLES_PER_STEP = 1


def _default_derived_root(root):
    """The default derived root lives next to the facts store."""
    return os.path.join(root, "derived")


class _DerivedBuilderLock:
    """Cross-process single-builder lease over one derived root.

    The rebuild executor is a separate process from the daemon; the #64
    staging machine's in-process ``builder_lock`` only serializes threads
    of one daemon.  The spec's one-builder rule (SCN-68-9) must hold ACROSS
    processes, so the rebuild machine is given a flock-based lease rooted
    at ``<derived_root>/.rebuild-builder.lock``: every machine cycle takes
    the lease, so a second rebuild (or a daemon staging worker wired to
    the same lock) yields instead of building -- never two builders over
    the same derived root.  flock is kernel-released on process death, so
    a crashed executor never wedges the lease.
    """

    LOCK_NAME = ".rebuild-builder.lock"

    def __init__(self, derived_root):
        self._path = os.path.join(derived_root, self.LOCK_NAME)
        self._fd = None

    def acquire(self):
        import fcntl
        fd = os.open(self._path,
                     os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            os.close(fd)
            raise
        self._fd = fd

    def release(self):
        fd = self._fd
        self._fd = None
        if fd is not None:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def _valid_build_id(value):
    return (isinstance(value, str) and 1 <= len(value) <= 128
            and all(character in (
                "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:")
                for character in value))


def _exact_mode(path, mode):
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == mode
    except OSError:
        return False


def _probe_ann_sidecar(derived_root, generation_id):
    """True when a real ANN sidecar exists for the active generation.

    The exact-only envelope has no ANN library; the sidecar lives OUTSIDE
    the immutable generation container (a file inside ``generations/<id>/``
    would break the reopen verification's exact-member check) under
    ``<derived_root>/index/<generation_id>/index.ann`` -- the seam a future
    #78/#79 backend publishes (and a test can inject).  ``--index-only``
    requires a REAL sidecar to rebuild -- never a fabricated ANN
    (RISK-68-1).
    """
    path = os.path.join(derived_root, "index", generation_id,
                        ANN_SIDECAR_NAME)
    try:
        return os.path.isfile(path) and not os.path.islink(path)
    except OSError:
        return False


def _compose_index_fingerprint():
    from compat import compose_index_fingerprint
    return compose_index_fingerprint()


class RebuildSpec:
    """Factory for the `rebuild` OperationTypeSpec with injectable seams.

    Seams (all optional; defaults target the throwaway/test envelope):
      provider_factory(representation_id) -> RepresentationProvider
          the desired representation seam behind the build target.  The
          default is a deterministic fixture provider (model-free); the real
          hidden-state provider plugs at the same seam.
      machine_builder(facts_root, derived_root, provider, active_repr,
                      active_gen_id, *, rebuild_tag, force_rebuild,
                      publish_lock) -> StagingBuildMachine
          constructs the single staging machine this operation drives
          (defaults to the standard #64 machine, start_worker=False).
      has_ann_sidecar(derived_root, generation_id) -> bool
          the index-only gate probe (default: exact-only, no sidecar).
      publish(machine, staging_dir, generation_id, provider) -> dict | None
          optional publish seam for the ready staging (the #65 publish
          transaction needs a delta machine; the CLI host wires it only
          when it has one).  None leaves the ready staging in place for a
          daemon publisher -- the operation still reports success at
          ``ready`` (the durable build job is persisted; spec: 默认在 build
          job 持久化后返回).
    """

    def __init__(self, root, *, derived_root=None, provider_factory=None,
                 machine_builder=None, has_ann_sidecar=None, publish=None,
                 euid=None):
        self.root = root
        self.euid = os.geteuid() if euid is None else euid
        self.derived_root = derived_root or _default_derived_root(root)
        if provider_factory is None:
            provider_factory = self._default_provider_factory
        self.provider_factory = provider_factory
        self.machine_builder = machine_builder or self._default_machine_builder
        self.has_ann_sidecar = has_ann_sidecar or _probe_ann_sidecar
        self.publish = publish
        # Executor-process state, keyed by operation id (a registry is
        # shared by many operations; per-operation machines and decisions
        # must NEVER leak across operations -- one builder at a time).
        self._machines = {}
        # Cross-process single-builder leases, keyed by derived root.
        self._builder_locks = {}

    # ------------------------------------------------------------------
    # Defaults (throwaway envelope)
    # ------------------------------------------------------------------

    def _default_provider_factory(self, representation_id):
        from evidence import FixtureRepresentationProvider
        return FixtureRepresentationProvider(
            representation_id, {}, {},
            default_query=(1.0, 0.0, 0.0, 0.0),
            default_event=(0.0, 1.0, 0.0, 0.0))

    def _default_machine_builder(self, facts_root, derived_root, provider,
                                 active_representation_id, active_generation_id,
                                 *, rebuild_tag=None, force_rebuild=False,
                                 publish_lock=None, active_identity=None,
                                 builder_lock=None):
        from staging import StagingBuildMachine
        return StagingBuildMachine(
            facts_root, derived_root, provider, active_representation_id,
            active_generation_id, chunk_rows=64, poll_interval=0.01,
            start_worker=False, publish_lock=publish_lock,
            active_identity=active_identity, force_rebuild=force_rebuild,
            rebuild_tag=rebuild_tag, builder_lock=builder_lock)

    # ------------------------------------------------------------------
    # Normalization (idempotency credential)
    # ------------------------------------------------------------------

    def _normalize(self, parameters):
        if not isinstance(parameters, dict):
            raise ValueError("rebuild parameters must be an object")
        mode = parameters.get("mode", MODE_AUTO)
        if mode not in MODES:
            raise ValueError("rebuild mode must be one of %s"
                             % ", ".join(MODES))
        derived_root = parameters.get("derived_root") or self.derived_root
        if not isinstance(derived_root, str) or not derived_root:
            raise ValueError("derived_root must be a non-empty path")
        derived_root = os.path.abspath(derived_root)
        if "\x00" in derived_root:
            raise ValueError("derived_root must not contain NUL")
        retry_build_id = parameters.get("retry_build_id")
        if retry_build_id is not None and not _valid_build_id(retry_build_id):
            raise ValueError("retry_build_id must be a valid build id")
        build_id = parameters.get("build_id")
        if build_id is not None and not _valid_build_id(build_id):
            raise ValueError("build_id must be a valid build id")
        rebuild_tag = parameters.get("rebuild_tag")
        if rebuild_tag is not None and (
                not isinstance(rebuild_tag, str) or not rebuild_tag):
            raise ValueError("rebuild_tag must be a non-empty string or None")
        if not isinstance(parameters.get("restart", False), bool):
            raise ValueError("restart must be a boolean")
        # The explicit retry marker is carried on the record but NOT part
        # of the idempotency credential: `--retry <build_id>` resumes the
        # SAME operation (same normalized parameters) -- never a new
        # idempotency key, so a retry of a blocked build reuses the
        # operation instead of rejecting it as a parameter change (#52).
        return {
            "mode": mode,
            "derived_root": derived_root,
            "build_id": build_id,
            "rebuild_tag": rebuild_tag,
            "restart": bool(parameters.get("restart", False)),
        }

    # ------------------------------------------------------------------
    # Read-only preview (the CLI resolves build_id before creating the
    # operation so the same target returns the same build id)
    # ------------------------------------------------------------------

    def _active_identity(self, facts_root, fact_schema_version,
                         derived_root):
        """(active_identity, active_generation_id, refuse_reason).

        Resolves the durable active identity from the active manifest (the
        manifest, not the config, is the source of truth after a publish).
        A present-but-invalid / unknown manifest refuses (no config-active
        fallback, #66); no manifest means nothing active yet.
        """
        from publish import read_active_manifest
        manifest, reason = read_active_manifest(derived_root)
        if manifest is None and reason is not None:
            return None, None, reason
        if manifest is None:
            return None, None, None
        from publish import active_identity_from_manifest
        identity = active_identity_from_manifest(manifest)
        refuse = refuse_load_reason(
            identity, facts_schema_version=fact_schema_version)
        if refuse is not None:
            return None, None, refuse
        return identity, manifest["generation_id"], None

    def _desired_provider(self, active_identity):
        """The desired representation for the rebuild target.

        A manual rebuild does not change the desired representation (the
        rebuild is of the current derived state); the desired provider
        therefore carries the ACTIVE representation id, so the matrix sees
        the layers as identical and auto returns already_current while
        --full still mints a new generation via the rebuild tag.
        """
        if active_identity is not None:
            representation_id = active_identity.get(LAYER_REPRESENTATION)
        else:
            representation_id = "fixture-rebuild-repr-v1"
        return self.provider_factory(representation_id)

    def _target(self, facts_root, provider, rebuild_tag=None):
        """The deterministic rebuild target (read-only; never writes)."""
        store_epoch, source_hlc, events = _read_snapshot(facts_root)
        return _prepare_target(events, provider, store_epoch, source_hlc,
                               rebuild_tag=rebuild_tag)

    def _desired_identity(self, facts_epoch, fact_schema_version, provider):
        """The desired layered identity for the rebuild target.

        Mirrors the staging machine's desired identity composition: the
        store epoch and fact schema come from the facts, the generation-bound
        layers come from the desired provider and the current projection /
        index constants.  The rebuild does not change any of them, so the
        matrix compares them against the active layer by layer.
        """
        return {
            compat.LAYER_STORE_EPOCH: facts_epoch,
            compat.LAYER_FACT_SCHEMA: fact_schema_version,
            compat.LAYER_REPRESENTATION: provider.representation_id(),
            compat.LAYER_VECTOR_FORMAT: VECTOR_FORMAT,
            compat.LAYER_PROJECTION: PROJECTION_VERSION,
            compat.LAYER_INDEX: _compose_index_fingerprint(),
        }

    def _refuse(self, code, message, remediation, cause=None):
        return {
            "build_id": None,
            "refuse": {
                "code": code, "message": message,
                "remediation": remediation, "cause": cause,
            },
            "already_current": False,
            "active_generation_id": None,
            "mismatches": [],
            "plan": None,
        }

    def _active_generation_healthy(self, derived_root, generation_id):
        """Reopen-verify the active generation (checksums / identity /
        probes).  A failed reopen is an unhealthy base."""
        path = os.path.join(derived_root, "generations", generation_id)
        if not os.path.isdir(path):
            return False
        try:
            generation = open_generation(path)
            generation.close()
            return True
        except Exception:  # noqa: BLE001 - unhealthy is a refuse
            return False

    def _index_only_refusal(self, derived_root, active_identity,
                            active_generation_id, plan):
        """The explicit --index-only gate (AC68-3).

        Returns a refusal tuple ``(code, message, remediation)`` or None
        when index-only is legal.  Never silently upgrades to full.
        """
        if active_identity is None or active_generation_id is None:
            return (REFUSE_INDEX_ONLY_NO_BASE,
                    "no active generation exists; there is no healthy base "
                    "to rebuild an index from",
                    "build the base generation first, then re-run "
                    "--index-only")
        if not self._active_generation_healthy(derived_root,
                                               active_generation_id):
            return (REFUSE_INDEX_ONLY_UNHEALTHY_BASE,
                    "the active FP32 / metadata / projection are not "
                    "healthy-compatible",
                    "fix or rebuild the base derived state first; "
                    "--index-only never silently upgrades to full")
        if not self.has_ann_sidecar(derived_root, active_generation_id):
            return (REFUSE_NO_ANN_SIDECAR,
                    "the exact-only envelope has no ANN sidecar to rebuild",
                    "there is no ANN index in this envelope; --index-only "
                    "refuses instead of fabricating one (revisit with "
                    "#78/#79)")
        return None

    def _matrix_plan(self, facts_epoch, fact_schema_version, active_identity,
                     provider):
        desired_identity = self._desired_identity(
            facts_epoch, fact_schema_version, provider)
        return plan_actions(desired_identity, active_identity,
                            facts_schema_version=fact_schema_version)

    def _is_already_current(self, mode, plan, active_identity,
                            active_generation_id, derived_root):
        """auto + healthy matching active (AC68-1 / SCN-68-1).

        Only the AUTO mode may return already_current: --full must always
        mint a new generation, and --index-only is gated separately.

        ``[ACTION_REBUILD_INDEX]`` is accepted as already-current ONLY
        because the exact-only envelope resolves an index-fingerprint-only
        change to a planned no-op with reason ``no_ann_sidecar`` (RISK-66-1:
        no ANN sidecar to rebuild, never a silent re-embed).  A future
        real-ANN envelope (#78/#79) must route that gap to --index-only
        instead; the refusal lives on the index-only gate.
        """
        return (mode == MODE_AUTO
                and active_identity is not None
                and active_generation_id is not None
                and plan["actions"] in ([ACTION_NOOP], [ACTION_REBUILD_INDEX])
                and not plan.get("refuse_load")
                and self._active_generation_healthy(derived_root,
                                                    active_generation_id))

    def preview(self, parameters):
        """Read-only preflight used by the CLI BEFORE creating the operation.

        Resolves the active identity, runs the compatibility matrix and
        returns:

            {"build_id": str | None,
             "refuse": {code, message, remediation, cause} | None,
             "already_current": bool,
             "active_generation_id": str | None,
             "mismatches": [...]}

        Never writes anything.  A refusal here is the explicit --index-only
        (or precondition) refusal; the same gates re-run inside the
        operation's preflight step so a persisted operation is never
        bypassed by a CLI change.
        """
        normalized = self._normalize(parameters)
        facts_root = self.root
        derived_root = normalized["derived_root"]
        if not os.path.isdir(derived_root) or not _exact_mode(
                derived_root, 0o700):
            if normalized["mode"] == MODE_INDEX_ONLY:
                return self._refuse(
                    REFUSE_INDEX_ONLY_NO_BASE,
                    "no healthy derived state exists to rebuild",
                    "the derived root is missing or not owner-only; a "
                    "manual rebuild needs existing derived state")
            return self._refuse(
                REFUSE_DERIVED_ROOT_UNCONFIGURED,
                "the derived root is missing or not owner-only",
                "ensure the derived root exists with owner-only "
                "permissions before rebuilding")
        try:
            facts_identity = read_facts_identity(facts_root)
        except Exception as error:  # noqa: BLE001 - fail closed
            return self._refuse(
                "fact_store_unreadable",
                "the fact store cannot be read",
                "inspect the fact store before rebuilding",
                cause={"fault": type(error).__name__})
        if facts_identity is None:
            return self._refuse(
                "fact_store_missing",
                "no fact store exists; there is nothing to rebuild",
                "create facts first (recording) before rebuilding")
        facts_epoch, _max = facts_identity
        try:
            fact_schema_version = read_facts_schema_version(facts_root)
        except Exception:  # noqa: BLE001 - fail closed
            fact_schema_version = None
        active_identity, active_generation_id, refuse = self._active_identity(
            facts_root, fact_schema_version, derived_root)
        if refuse is not None:
            return self._refuse(
                REFUSE_ACTIVE_UNKNOWN,
                "the active identity cannot be loaded (%s)" % refuse,
                "inspect the active manifest and the derived state before "
                "rebuilding",
                cause={"refuse_reason": refuse})
        provider = self._desired_provider(active_identity)
        plan = self._matrix_plan(facts_epoch, fact_schema_version,
                                 active_identity, provider)

        if active_identity is None:
            # A manual rebuild rebuilds EXISTING derived state; with no
            # active generation there is nothing to compare or replace.
            # An explicit request is refused -- never a silent first build.
            return self._refuse(
                "no_active_generation",
                "no active generation exists to rebuild",
                "let the daemon build the first generation, then re-run "
                "rebuild")

        if normalized["mode"] == MODE_INDEX_ONLY:
            refusal = self._index_only_refusal(
                derived_root, active_identity, active_generation_id, plan)
            if refusal is not None:
                return self._refuse(*refusal)
            target = self._target(facts_root, provider)
            return {
                "build_id": target["generation_id"],
                "refuse": None,
                "already_current": False,
                "active_generation_id": active_generation_id,
                "mismatches": plan["mismatches"],
                "plan": plan,
            }

        already_current = self._is_already_current(
            normalized["mode"], plan, active_identity,
            active_generation_id, derived_root)
        target = self._target(facts_root, provider,
                              rebuild_tag=normalized["rebuild_tag"])
        return {
            "build_id": (active_generation_id if already_current
                         else target["generation_id"]),
            "refuse": None,
            "already_current": bool(already_current),
            "active_generation_id": active_generation_id,
            "mismatches": plan["mismatches"],
            "plan": plan,
        }

    # ------------------------------------------------------------------
    # Shared phase prelude
    # ------------------------------------------------------------------

    def _staging_representation(self, derived_root, build_id):
        """The representation a live staging record of `build_id` was built
        with, or None when no live record exists.

        A retry continues the EXISTING build: the desired representation
        must stay the one the staging was pinned to (never re-derived from
        the current active identity, which would discard the staging as a
        "desired representation changed" -- SCN-64-4).
        """
        if not build_id:
            return None
        from staging import STAGING_PROGRESS_VERSION
        import json as json_module
        path = os.path.join(derived_root, "staging", build_id,
                            "progress.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                value = json_module.load(handle)
        except (OSError, ValueError):
            return None
        if value.get("progress_version") != STAGING_PROGRESS_VERSION:
            return None
        if value.get("generation_id") != build_id:
            return None
        identity = value.get("identity") or {}
        representation = identity.get("representation_id")
        if not isinstance(representation, str) or not representation:
            return None
        return representation

    def _facts_and_active(self, record, phase):
        """Read-only (facts identity, schema, active identity, derived
        root) with the fail-closed gates; raises OperationBlocked on a
        deterministic precondition failure."""
        normalized = record["parameters"]
        facts_root = self.root
        derived_root = normalized["derived_root"]
        facts_identity = read_facts_identity(facts_root)
        if facts_identity is None:
            raise OperationBlocked(
                "fact_store_missing", phase=phase,
                remediation="create facts first (recording) before "
                            "rebuilding")
        facts_epoch, _max = facts_identity
        try:
            fact_schema_version = read_facts_schema_version(facts_root)
        except Exception:  # noqa: BLE001 - fail closed
            fact_schema_version = None
        active_identity, active_generation_id, refuse = self._active_identity(
            facts_root, fact_schema_version, derived_root)
        if refuse is not None:
            raise OperationBlocked(
                REFUSE_ACTIVE_UNKNOWN, phase=phase,
                remediation="inspect the active manifest and the derived "
                            "state before rebuilding",
                cause={"refuse_reason": refuse})
        return (facts_epoch, fact_schema_version, active_identity,
                active_generation_id, derived_root)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _step_preflight(self, record):
        normalized = record["parameters"]
        facts_root = self.root
        facts_epoch, fact_schema_version, active_identity, \
            active_generation_id, derived_root = self._facts_and_active(
                record, "preflight")
        provider = self._desired_provider(active_identity)
        plan = self._matrix_plan(facts_epoch, fact_schema_version,
                                 active_identity, provider)

        if active_identity is None:
            # A manual rebuild rebuilds EXISTING derived state; with no
            # active generation there is nothing to compare or replace.
            # An explicit request is refused -- never a silent first build.
            raise OperationBlocked(
                "no_active_generation", phase="preflight",
                remediation="let the daemon build the first generation, "
                            "then re-run rebuild")

        if normalized["mode"] == MODE_INDEX_ONLY:
            refusal = self._index_only_refusal(
                derived_root, active_identity, active_generation_id, plan)
            if refusal is not None:
                code, message, remediation = refusal
                raise OperationBlocked(
                    code, phase="preflight", remediation=remediation,
                    cause={"message": message})

        # The build target (build_id) is fixed by the CLI preview; the
        # persisted operation carries it so the same target reuses it and a
        # crash/restart re-derives the identical job.  Defensive: recompute
        # and cross-check; a disagreement means the facts or the active
        # identity changed between preview and execution -- fail
        # deterministically, never silently rebuild the wrong target.
        already_current = self._is_already_current(
            normalized["mode"], plan, active_identity,
            active_generation_id, derived_root)
        target = self._target(facts_root, provider,
                              rebuild_tag=normalized["rebuild_tag"])
        expected_build_id = (active_generation_id if already_current
                             else target["generation_id"])
        if (normalized["build_id"] is not None
                and normalized["build_id"] != expected_build_id):
            raise OperationBlocked(
                "build_target_changed", phase="preflight",
                remediation="re-run rebuild; the target changed since the "
                            "request was created",
                cause={"recorded": normalized["build_id"],
                       "current": expected_build_id})
        return {"advance": True}

    def _machine_for(self, record):
        """The single staging machine for this operation, cached per
        operation id (a registry is shared by many operations; a machine
        must NEVER leak across operations -- one builder at a time)."""
        operation_id = record["operation_id"]
        machines = getattr(self, "_machines", None)
        if machines is None:
            machines = self._machines = {}
        machine = machines.get(operation_id)
        if machine is not None:
            # A cached machine was built for THIS operation in this
            # executor invocation; it stays open until the cleanup step
            # pops it (cleanup is the final phase, so a cached machine is
            # never stale).
            return machine
        normalized = record["parameters"]
        facts_root = self.root
        derived_root = normalized["derived_root"]
        _facts_epoch, _schema, active_identity, active_generation_id, _ = \
            self._facts_and_active(record, "staging")
        # The desired representation for the rebuild target.  A manual
        # rebuild does not change the desired representation: the matrix
        # and the target use the ACTIVE representation, so auto returns
        # already_current when the active is healthy-matching and --full
        # mints a new generation of the SAME representation via the tag.
        # An EXISTING staging record of this build_id (a retry) pins the
        # representation it was built with -- retry must continue that
        # build, never reinterpret it with the current active identity
        # (SCN-64-4: a changed desired representation discards the
        # staging).
        staging_repr = self._staging_representation(
            derived_root, normalized["build_id"])
        if staging_repr is not None:
            provider = self.provider_factory(staging_repr)
        else:
            provider = self._desired_provider(active_identity)
        active_repr = (active_identity.get(LAYER_REPRESENTATION)
                       if active_identity is not None else
                       provider.representation_id())
        # With no active generation yet, the machine is told a placeholder
        # active identity (it builds the desired generation in full on the
        # first cycle; the declared active id is never matched by any
        # target).  The active_identity seam is left None so the machine
        # composes the active from the config-declared active + current
        # facts, which for a placeholder that matches the desired
        # representation yields the normal first-build path.
        active_id = active_generation_id or \
            "shadow-gen-v1:no-active-yet-0000000000000000000000000000"
        machine = self.machine_builder(
            facts_root, derived_root, provider, active_repr, active_id,
            rebuild_tag=normalized["rebuild_tag"],
            force_rebuild=(normalized["mode"] == MODE_FULL),
            publish_lock=self._publish_lock(),
            builder_lock=self._builder_lock_for(derived_root))
        machines[operation_id] = machine
        return machine

    def _builder_lock_for(self, derived_root):
        """The cross-process single-builder lease for one derived root,
        cached per executor invocation (SCN-68-9: one builder at a time)."""
        locks = getattr(self, "_builder_locks", None)
        if locks is None:
            locks = self._builder_locks = {}
        lock = locks.get(derived_root)
        if lock is None:
            lock = locks[derived_root] = _DerivedBuilderLock(derived_root)
        return lock

    def _index_only_sidecar_ready(self, record):
        """The --index-only allow branch requires a REAL, non-empty ANN
        sidecar for the active generation (never a fabricated index)."""
        try:
            from publish import read_active_manifest
            manifest, _reason = read_active_manifest(
                record["parameters"]["derived_root"])
            if manifest is None or _reason is not None:
                return False
            if not self.has_ann_sidecar(
                    record["parameters"]["derived_root"],
                    manifest["generation_id"]):
                return False
            # The sidecar must be a real, non-empty file.
            path = os.path.join(
                record["parameters"]["derived_root"], "index",
                manifest["generation_id"], ANN_SIDECAR_NAME)
            return (os.path.isfile(path) and not os.path.islink(path)
                    and os.path.getsize(path) > 0)
        except Exception:  # noqa: BLE001 - fail closed
            return False

    def _is_auto_already_current(self, record):
        """Recompute the already_current decision from the persisted record
        (never from executor-instance state, which is shared across
        operations)."""
        normalized = record["parameters"]
        if normalized["mode"] != MODE_AUTO:
            return False
        facts_epoch, fact_schema_version, active_identity, \
            active_generation_id, derived_root = self._facts_and_active(
                record, "preflight")
        provider = self._desired_provider(active_identity)
        plan = self._matrix_plan(facts_epoch, fact_schema_version,
                                 active_identity, provider)
        return self._is_already_current(
            MODE_AUTO, plan, active_identity, active_generation_id,
            derived_root)

    def _step_staging(self, record):
        normalized = record["parameters"]
        if self._is_auto_already_current(record):
            # auto + healthy matching active: no staging, no new generation,
            # no rollback rotation (AC68-1 / SCN-68-1).
            return {"advance": True}
        if normalized["mode"] == MODE_INDEX_ONLY:
            # --index-only rebuilds ONLY the ANN sidecar (a future #78/#79
            # backend); the FP32 / metadata / projection generation
            # container is untouched -- there is nothing to stage or
            # publish.  The preflight already verified the healthy base and
            # the real sidecar; this step re-verifies the sidecar is a
            # REAL, non-empty file (never a fabricated ANN, RISK-68-1) and
            # the outcome records the index rebuild condition.
            if not self._index_only_sidecar_ready(record):
                raise OperationBlocked(
                    "index_only_sidecar_missing", phase="staging",
                    remediation="the ANN sidecar is not a readable, "
                                "non-empty file; there is no index to "
                                "rebuild",
                    cause=None)
            return {"advance": True}
        derived_root = normalized["derived_root"]
        machine = self._machine_for(record)

        if normalized["restart"]:
            # --restart discards the CURRENT staging (any live staging of
            # the derived root except THIS build's own target), then
            # rebuilds from scratch -- distinct from retry: retry
            # continues the existing staging, restart throws it away
            # (AC68-5 / spec: 丢弃 staging 后重建).  The machine's own
            # `_discard` is the authoritative discard (it marks the record
            # AND resets the machine's in-memory build state); the rebuild
            # never hand-writes another machine's progress.json, which
            # would race a live builder.
            if not getattr(self, "_restart_done", False):
                self._restart_done = True
                staging_root = os.path.join(derived_root, "staging")
                try:
                    entries = os.listdir(staging_root)
                except OSError:
                    entries = []
                for entry in entries:
                    staging_dir = os.path.join(staging_root, entry)
                    if not os.path.isdir(staging_dir) or entry.endswith(
                            ".tmp"):
                        continue
                    if entry == normalized["build_id"]:
                        # This build's own target is handled by the normal
                        # fresh-build cycle (a leftover of the same build
                        # is cleared by _start_build).
                        continue
                    # A live staging of another build (same representation,
                    # different rebuild tag, or an older target): the
                    # explicit restart discards it so the fresh build
                    # starts clean.
                    try:
                        from staging import STAGING_PROGRESS_VERSION
                        import json as json_module
                        progress_path = os.path.join(staging_dir,
                                                     "progress.json")
                        if not os.path.isfile(progress_path):
                            continue
                        with open(progress_path, encoding="utf-8") as handle:
                            value = json_module.load(handle)
                        if value.get("progress_version") == \
                                STAGING_PROGRESS_VERSION and value.get(
                                "status") not in ("discarded",):
                            machine._discard(
                                staging_dir,
                                "explicit rebuild --restart", own=False)
                    except Exception:  # noqa: BLE001 - best effort
                        pass
        status = machine.status()
        progress = status.get("progress")
        if progress is not None and progress.get("status") == "blocked" \
                and progress.get("generation_id") == normalized["build_id"]:
            machine.retry()

        # Drive the single staging machine ONE cycle per runner step.  The
        # runner re-invokes this step (advance=False) until the machine
        # reaches a durable resting state, so each cycle's real progress
        # delta is persisted and every intermediate state is crashable.
        # Driving `_cycle()` directly (instead of a daemon worker thread)
        # is the same cycle-by-cycle seam the staging integration harness
        # uses (daemon/integration_staging.py): the rebuild executor IS
        # the driver, one state-machine cycle per runner step, and the
        # machine's durable progress record makes the step idempotent
        # across executor restarts.
        for _ in range(MAX_STAGING_CYCLES_PER_STEP):
            machine._cycle()
            progress = machine.status().get("progress")
            if progress is None:
                raise OperationBlocked(
                    "rebuild_refused", phase="staging",
                    remediation="inspect the staging machine status and "
                                "re-run rebuild",
                    cause={"last_error":
                           machine.status().get("last_error")})
            status = progress.get("status")
            if status == "blocked":
                blocked_events = progress.get("blocked_events") or []
                reason = progress.get("reason") or "staging blocked"
                raise OperationBlocked(
                    "staging_blocked", phase="staging",
                    remediation="fix the cause and re-run rebuild --retry "
                                "<build_id>",
                    cause={"events": blocked_events[:8], "reason": reason})
            if status == "ready":
                delta = self._progress_delta(record, progress)
                return {"advance": True, "progress": delta}
            if status == "discarded":
                # The machine discarded its own staging (target/epoch
                # change); the next cycle starts a fresh build.
                continue
            # running: report the real progress so far, stay in this phase.
            delta = self._progress_delta(record, progress)
            if delta:
                return {"progress": delta}
        return {"advance": False}

    def _step_publishing(self, record):
        if self._is_auto_already_current(record):
            return {"advance": True}
        if record["parameters"]["mode"] == MODE_INDEX_ONLY:
            # --index-only rebuilds only the ANN sidecar; the generation
            # container is untouched, so there is no publish transaction.
            return {"advance": True}
        normalized = record["parameters"]
        machine = self._machine_for(record)
        status = machine.status()
        progress = status.get("progress")
        generation_id = (progress.get("generation_id")
                         if progress is not None else None)
        staging_dir = status.get("ready_staging_dir") or (
            os.path.join(normalized["derived_root"], "staging", generation_id)
            if generation_id else None)
        if not generation_id or not staging_dir or not os.path.isdir(
                staging_dir):
            raise OperationBlocked(
                "ready_staging_missing", phase="publishing",
                remediation="re-run rebuild --retry <build_id>",
                cause={"generation_id": generation_id})
        # The #65 publish gates stay in force: the ready container is
        # re-verified (checksum / event-set / vector / oracle probes) by the
        # staging machine's verify_publishable before anything is renamed.
        try:
            machine.verify_publishable(staging_dir)
        except Exception as error:  # noqa: BLE001 - fail closed
            reason = getattr(error, "reason", None) or str(error)
            raise OperationBlocked(
                "publish_precondition_failed", phase="publishing",
                remediation="inspect and re-run rebuild --retry <build_id>",
                cause={"reason": reason})
        published = False
        if self.publish is not None:
            result = self.publish(machine, staging_dir, generation_id,
                                  machine.provider())
            published = bool(result and result.get("ok"))
            if not published:
                raise OperationBlocked(
                    "publish_failed", phase="publishing",
                    remediation="the publish transaction failed; the ready "
                                "staging is preserved for a retry",
                    cause={"error": (result or {}).get("error")})
        # The published generation id must survive into the cleanup result
        # even across executor restarts: it is derived from the durable
        # ready staging (the active manifest now points at it).
        self._published_generation_id = generation_id
        return {"advance": True}

    def _step_cleanup(self, record):
        machines = getattr(self, "_machines", None)
        if machines:
            operation_id = record["operation_id"]
            machine = machines.pop(operation_id, None)
            if machine is not None:
                try:
                    machine.close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
        if self._is_auto_already_current(record):
            result = {
                "outcome": "already_current",
                "build_id": record["parameters"]["build_id"],
                "published": False,
            }
        elif record["parameters"]["mode"] == MODE_INDEX_ONLY:
            result = {
                "outcome": "index_rebuilt",
                "build_id": record["parameters"]["build_id"],
                "published": False,
            }
        else:
            # Re-derive the published generation: after a REAL publish the
            # active manifest points at the new generation (the staging
            # container was renamed away); without a publish seam the
            # durable READY staging of this build is the completed build
            # job (spec: 默认在 build job 持久化后返回, a daemon publisher
            # picks it up).
            generation_id = None
            published = False
            try:
                from publish import read_active_manifest
                manifest, _reason = read_active_manifest(
                    record["parameters"]["derived_root"])
                if manifest is not None and _reason is None:
                    # The active manifest is the durable commit point: when
                    # it points at THIS build's generation id the rebuild
                    # published (a real publish transaction renamed the
                    # ready staging into generations/ and replaced the
                    # manifest).
                    if manifest["generation_id"] == \
                            record["parameters"]["build_id"]:
                        generation_id = manifest["generation_id"]
                        published = True
            except Exception:  # noqa: BLE001 - best effort
                pass
            if generation_id is None:
                try:
                    from staging import STAGING_PROGRESS_VERSION
                    import json as json_module
                    staging_root = os.path.join(
                        record["parameters"]["derived_root"], "staging")
                    if os.path.isdir(staging_root):
                        progress_path = os.path.join(
                            staging_root, record["parameters"]["build_id"],
                            "progress.json")
                        if os.path.isfile(progress_path):
                            with open(progress_path,
                                      encoding="utf-8") as handle:
                                value = json_module.load(handle)
                            if value.get("progress_version") == \
                                    STAGING_PROGRESS_VERSION and value.get(
                                    "status") == "ready":
                                generation_id = value.get("generation_id")
                except Exception:  # noqa: BLE001 - best effort
                    pass
            result = {
                "outcome": "rebuilt",
                "build_id": record["parameters"]["build_id"],
                "generation_id": generation_id,
                "published": published,
            }
        return {"progress": {"chunks": 1}, "advance": True,
                "result": result}

    # ------------------------------------------------------------------
    # Progress helpers (real units only)
    # ------------------------------------------------------------------

    def _publish_lock(self):
        import threading
        return threading.Lock()

    def _progress_delta(self, record, progress):
        """Real progress delta since the last PERSISTED progress (events /
        bytes / chunks).  A percentage is never fabricated when the total is
        unknown (spec #43)."""
        current = {
            "events": progress.get("total_rows") or 0,
            "bytes": sum(chunk.get("bytes", 0)
                         for chunk in (progress.get("chunks") or [])),
            "chunks": len(progress.get("chunks") or []),
        }
        delta = {}
        for unit in ("events", "bytes", "chunks"):
            value = current[unit] - record["progress"][unit]
            if value > 0:
                delta[unit] = value
        return delta

    def build(self):
        steps = {
            "preflight": self._step_preflight,
            "staging": self._step_staging,
            "publishing": self._step_publishing,
            "cleanup": self._step_cleanup,
        }
        spec = OperationTypeSpec(
            REBUILD_TYPE,
            phases=REBUILD_PHASES,
            irreversible_phase=REBUILD_IRREVERSIBLE_PHASE,
            normalize=self._normalize,
            steps=steps,
        )
        # The CLI preview must use the SAME seams as the executor steps;
        # the spec carries its originating RebuildSpec so the CLI can
        # resolve build_id / already_current identically.
        spec.rebuild_spec = self
        return spec


def build_rebuild_spec(root, **seams):
    """Build the production `rebuild` operation type for one semantic root."""
    return RebuildSpec(root, **seams).build()


def production_registry(root, **seams):
    """The production rebuild registry: `rebuild` only."""
    from operations import OperationRegistry
    registry = OperationRegistry()
    registry.register(build_rebuild_spec(root, **seams))
    return registry
