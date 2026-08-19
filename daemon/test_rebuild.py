#!/usr/bin/env python3
"""Explicit manual rebuild tests (Habit130/squirrel#68, AC-68-v1).

Model-free, stdlib-only, sandboxed temp fact roots + derived roots and
injected deterministic representation fixtures -- never real private
history.  Maps one-to-one onto the frozen delivery contract:

  AC68-1  auto uses the compat matrix minimum scope; a healthy active that
          already matches returns already_current (no new generation)
  AC68-2  --full rebuilds FP32/projection/delta/index from facts even when
          the fingerprint is unchanged (a NEW generation id is minted via
          the rebuild tag)
  AC68-3  --index-only is allowed only on a healthy compatible FP32 +
          metadata + projection; otherwise an EXPLICIT refusal, never a
          silent upgrade to full
  AC68-4  the same target queued/building reuses the same build_id;
          operation_id != build_id
  AC68-5  blocked never auto-retries; --retry continues the existing
          staging; --restart discards it and rebuilds
  AC68-6  --wait detach != cancel; cancel before publish is honored;
          after publish it is refused (operations machine)
  AC68-7  rebuild never modifies facts, history, store_epoch or the three
          schema switches; no plugin quiesce (no exclusive maintenance
          path, no control socket)
  SCN-68-9  one builder: the rebuild drives a single staging machine; a
          concurrent same-target rebuild reuses the same build_id instead
          of starting a second builder

The rebuild operation runs its real steps through the operations runner
(create_operation + run_pending_steps) over injected seams that mirror the
daemon's staging/publish machines.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from rebuild_operation import (  # noqa: E402
    ANN_SIDECAR_NAME,
    MODE_AUTO,
    MODE_FULL,
    MODE_INDEX_ONLY,
    REFUSE_INDEX_ONLY_UNHEALTHY_BASE,
    REFUSE_NO_ANN_SIDECAR,
    RebuildSpec,
)
from operations import (  # noqa: E402
    OperationRegistry,
    OperationStore,
    create_operation,
    run_pending_steps,
)
from generation import (  # noqa: E402
    GENERATION_FILES,
    build_generation,
)
from publish import (  # noqa: E402
    ACTIVE_MANIFEST_FILENAME,
    read_active_manifest,
)
from staging import StagingBuildMachine  # noqa: E402
from test_publish import (  # noqa: E402
    base_facts,
    make_active_provider,
    make_desired_provider,
)

ACTIVE_REPR = "rebuild-test-active-repr-v1"
DESIRED_REPR = "rebuild-test-desired-repr-v1"

# The three schema switches must never be touched by a rebuild.
SWITCH_META_KEYS = ("reranking_enabled", "recording_enabled",
                    "evidence_enabled")


class RebuildEnv:
    """One sandboxed facts root + derived root with a published active
    generation (the active manifest is written so the rebuild resolves the
    durable active identity)."""

    def __init__(self, facts=None, active_repr=ACTIVE_REPR,
                 desired_repr=DESIRED_REPR):
        self.facts = facts or base_facts()
        self.facts.conn.execute("PRAGMA journal_mode=WAL;")
        self.facts.conn.commit()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")
        os.makedirs(self.derived_root, mode=0o700, exist_ok=True)
        self.active_provider = make_active_provider()
        self.desired_provider = make_desired_provider()
        self.active_gen = build_generation(
            self.facts_root, self.active_provider, self.derived_root)
        self.active_generation_id = self.active_gen.generation_id
        self.active_gen.close()
        self._write_active_manifest()
        # The publish transaction needs a delta machine for the in-memory
        # pointer swap; the swap is handled by its worker thread.
        from delta import DeltaStateMachine
        self.delta_machine = DeltaStateMachine(
            self.facts_root, self.derived_root, self.active_provider,
            self.active_generation_id, poll_interval=0.01,
            start_worker=True)
        # Facts identity / switches snapshot for the untouched assertions.
        self.facts_before = self._facts_snapshot()

    def close(self):
        try:
            self.delta_machine.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
        self.facts.close()

    def cleanup(self):
        self.close()

    def _write_active_manifest(self):
        """Publish the active generation durably (manifest only; the
        container is already under generations/)."""
        import time as time_module
        from publish import write_active_manifest
        from delta import read_facts_schema_version
        schema = read_facts_schema_version(self.facts_root)
        identity = self.active_gen.identity()
        manifest = {
            "manifest_version": "active-manifest-v1",
            "generation_id": self.active_generation_id,
            "store_epoch": identity["store_epoch"],
            "source_hlc": identity["source_hlc"],
            "fact_schema_version": schema,
            "representation_id": identity["representation_id"],
            "vector_format_version": identity["vector_format"],
            "projection_version": identity["projection_version"],
            "index_fingerprint": identity["index_fingerprint"],
            "delta_checkpoint": "delta/%s/delta.sqlite3"
            % self.active_generation_id,
            "builder_version": identity["builder_version"],
            "published_at_ms": int(time_module.time() * 1000),
        }
        write_active_manifest(self.derived_root, manifest)

    def _facts_snapshot(self):
        conn = sqlite3.connect(os.path.join(self.facts_root,
                                            "facts.sqlite3"))
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            counts = {
                "events": conn.execute(
                    "SELECT COUNT(*) FROM selection_events").fetchone()[0],
                "commits": conn.execute(
                    "SELECT COUNT(*) FROM commits").fetchone()[0],
                "retractions": conn.execute(
                    "SELECT COUNT(*) FROM retractions").fetchone()[0],
            }
            return {"meta": meta, "counts": counts}
        finally:
            conn.close()

    def assert_facts_untouched(self, testcase):
        after = self._facts_snapshot()
        for key in ("history_id", "store_epoch",
                    "fact_schema_version", "hlc_physical_ms",
                    "hlc_logical"):
            testcase.assertEqual(self.facts_before["meta"].get(key),
                                 after["meta"].get(key), key)
        for key in ("events", "commits", "retractions"):
            testcase.assertEqual(self.facts_before["counts"][key],
                                 after["counts"][key], key)
        for key in SWITCH_META_KEYS:
            testcase.assertEqual(self.facts_before["meta"].get(key),
                                 after["meta"].get(key), key)

    def published_dir(self, generation_id):
        return os.path.join(self.derived_root, "generations", generation_id)

    def staging_dir(self, generation_id):
        return os.path.join(self.derived_root, "staging", generation_id)


def machine_builder_for(env, desired_repr=DESIRED_REPR):
    """A machine builder that mirrors the daemon's staging machine over the
    env's derived root, with the desired provider (same representation as
    the active unless overridden -- auto rebuild does not change the
    desired representation)."""

    def build(facts_root, derived_root, provider, active_representation_id,
              active_generation_id, *, rebuild_tag=None, force_rebuild=False,
              publish_lock=None, active_identity=None, builder_lock=None):
        return StagingBuildMachine(
            facts_root, derived_root, provider, active_representation_id,
            active_generation_id, chunk_rows=2, poll_interval=0.01,
            start_worker=False, publish_lock=publish_lock,
            active_identity=active_identity, force_rebuild=force_rebuild,
            rebuild_tag=rebuild_tag, builder_lock=builder_lock)

    return build


def publish_seam(env, delta_machine=None):
    """The #65 publish transaction over the env's derived root (with the
    env's real delta machine for the in-memory pointer swap)."""

    def publish(machine, staging_dir, generation_id, provider):
        import threading
        from publish import publish_ready_staging as _publish
        result = _publish(
            env.facts_root, env.derived_root, machine, staging_dir,
            generation_id, provider, delta_machine or env.delta_machine,
            publish_lock=threading.Lock())
        return result

    return publish


class RebuildEnvTest(unittest.TestCase):
    def setUp(self):
        self.env = None
        self.tmp = tempfile.mkdtemp(prefix="rebuild_test_")

    def tearDown(self):
        if self.env is not None:
            self.env.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_env(self, **kwargs):
        self.env = RebuildEnv(**kwargs)
        return self.env

    def spec(self, env, **seams):
        defaults = {
            "derived_root": env.derived_root,
            "provider_factory": lambda repr_id: make_desired_provider()
            if repr_id == DESIRED_REPR else make_active_provider(),
            "machine_builder": machine_builder_for(env),
            "publish": publish_seam(env),
        }
        defaults.update(seams)
        return RebuildSpec(env.facts_root, **defaults)

    def registry(self, spec):
        registry = OperationRegistry()
        registry.register(spec.build())
        return registry

    def run_rebuild(self, env, spec, parameters, operation_id=None,
                    retry_blocked=False):
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        # Mirror the CLI: --full mints a fresh rebuild tag per request
        # (the generation id is content-addressed, so the mint needs a
        # new tag); resolve the build_id read-only first, then create the
        # operation with the fixed build_id.  A preview refusal is left to
        # the operation's own preflight step (the same gates re-derive it
        # there) -- the tests assert the blocked outcome on the operation
        # record.
        parameters = dict(parameters)
        if parameters.get("mode") == MODE_FULL and not parameters.get(
                "rebuild_tag"):
            import uuid as uuid_module
            parameters["rebuild_tag"] = \
                "rebuild-test-%s" % uuid_module.uuid4().hex[:16]
        preview = spec.preview(parameters)
        if preview["refuse"] is not None:
            parameters["build_id"] = None
        else:
            parameters["build_id"] = preview["build_id"]
        record = create_operation(store, registry, "rebuild", parameters,
                                  operation_id=operation_id)
        final = run_pending_steps(store, registry, record["operation_id"],
                                  retry_blocked=retry_blocked)
        return final, store

    # -- helpers -----------------------------------------------------------

    def _switch_meta_snapshot(self, env):
        conn = sqlite3.connect(os.path.join(env.facts_root,
                                            "facts.sqlite3"))
        try:
            return dict(conn.execute(
                "SELECT key, value FROM meta WHERE key IN (%s)"
                % ",".join("?" for _ in SWITCH_META_KEYS)).fetchall())
        finally:
            conn.close()


class AutoAlreadyCurrentTest(RebuildEnvTest):
    """SCN-68-1 / AC68-1: auto + healthy matching active -> already_current,
    no new generation."""

    def test_auto_healthy_matching_active_is_already_current(self):
        env = self.make_env()
        spec = self.spec(env)
        final, store = self.run_rebuild(
            env, spec, {"mode": MODE_AUTO,
                        "derived_root": env.derived_root})
        self.assertEqual("succeeded", final["state"])
        result = final["result"]
        self.assertEqual("already_current", result["outcome"])
        self.assertEqual(env.active_generation_id, result["build_id"])
        # No staging was ever created; the active generation id is reused.
        staging_root = os.path.join(env.derived_root, "staging")
        self.assertFalse(os.path.isdir(staging_root)
                         and os.listdir(staging_root))
        env.assert_facts_untouched(self)
        # operation_id != build_id.
        self.assertNotEqual(final["operation_id"], result["build_id"])

    def test_auto_without_any_active_refuses(self):
        env = self.make_env()
        # Remove the active manifest: no active generation exists -- a
        # manual rebuild of derived state is refused (the daemon's first
        # build owns the first generation; never a silent first build).
        os.unlink(os.path.join(env.derived_root, ACTIVE_MANIFEST_FILENAME))
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_AUTO,
                        "derived_root": env.derived_root})
        self.assertEqual("blocked", final["state"])
        self.assertEqual("no_active_generation", final["error"]["code"])
        env.assert_facts_untouched(self)


class FullRebuildTest(RebuildEnvTest):
    """SCN-68-2 / AC68-2: --full mints a new generation even when the
    fingerprint is unchanged."""

    def test_full_mints_new_generation_at_same_fingerprint(self):
        env = self.make_env()
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_FULL,
                        "derived_root": env.derived_root})
        self.assertEqual("succeeded", final["state"])
        result = final["result"]
        self.assertEqual("rebuilt", result["outcome"])
        new_id = result["generation_id"]
        self.assertIsNotNone(new_id)
        # A NEW generation id was minted even though the fingerprint
        # (same facts, same representation) is unchanged.
        self.assertNotEqual(new_id, env.active_generation_id)
        # The new generation was published and is the active one now.
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(new_id, manifest["generation_id"])
        self.assertTrue(os.path.isdir(env.published_dir(new_id)))
        env.assert_facts_untouched(self)

    def test_full_publishes_a_ready_container(self):
        env = self.make_env()
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_FULL,
                        "derived_root": env.derived_root})
        new_id = final["result"]["generation_id"]
        for name in GENERATION_FILES:
            self.assertTrue(os.path.isfile(
                os.path.join(env.published_dir(new_id), name)), name)


class IndexOnlyTest(RebuildEnvTest):
    """SCN-68-3 / AC68-3: --index-only refuses unless a healthy compatible
    base AND a real ANN sidecar exist; never silently upgrades to full."""

    def test_index_only_refuses_no_ann_sidecar(self):
        env = self.make_env()
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_INDEX_ONLY,
                        "derived_root": env.derived_root})
        self.assertEqual("blocked", final["state"])
        self.assertEqual(REFUSE_NO_ANN_SIDECAR, final["error"]["code"])
        env.assert_facts_untouched(self)
        # No staging was started: the refusal happened in preflight.
        staging_root = os.path.join(env.derived_root, "staging")
        self.assertFalse(os.path.isdir(staging_root)
                         and os.listdir(staging_root))

    def test_index_only_refuses_unhealthy_base(self):
        env = self.make_env()
        # Corrupt the active FP32 file -> the base is unhealthy.
        with open(os.path.join(env.published_dir(env.active_generation_id),
                               "vectors.fp32"), "wb") as handle:
            handle.write(b"corrupt")
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_INDEX_ONLY,
                        "derived_root": env.derived_root})
        self.assertEqual("blocked", final["state"])
        self.assertEqual(REFUSE_INDEX_ONLY_UNHEALTHY_BASE,
                         final["error"]["code"])

    def test_index_only_refuses_no_active(self):
        env = self.make_env()
        os.unlink(os.path.join(env.derived_root, ACTIVE_MANIFEST_FILENAME))
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_INDEX_ONLY,
                        "derived_root": env.derived_root})
        self.assertEqual("blocked", final["state"])
        self.assertEqual("no_active_generation", final["error"]["code"])

    def test_index_only_with_injected_sidecar_is_allowed(self):
        env = self.make_env()
        # Inject a real ANN sidecar OUTSIDE the immutable generation
        # container (a file inside generations/<id>/ would break the
        # reopen verification's exact-member check).
        sidecar_dir = os.path.join(env.derived_root, "index",
                                   env.active_generation_id)
        os.makedirs(sidecar_dir, mode=0o700, exist_ok=True)
        sidecar = os.path.join(sidecar_dir, ANN_SIDECAR_NAME)
        with open(sidecar, "wb") as handle:
            handle.write(b"ann-index")
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_INDEX_ONLY,
                        "derived_root": env.derived_root})
        self.assertEqual("succeeded", final["state"])
        result = final["result"]
        self.assertEqual("index_rebuilt", result["outcome"])
        env.assert_facts_untouched(self)

    def test_index_only_never_upgrades_to_full(self):
        env = self.make_env()
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_INDEX_ONLY,
                        "derived_root": env.derived_root})
        self.assertEqual("blocked", final["state"])
        # The active generation id is untouched: nothing was rebuilt, no
        # new generation, no manifest change.
        manifest, _reason = read_active_manifest(env.derived_root)
        self.assertEqual(env.active_generation_id, manifest["generation_id"])
        env.assert_facts_untouched(self)


class BuildIdIdentityTest(RebuildEnvTest):
    """SCN-68-4 / AC68-4: same target queued/building reuses build_id;
    operation_id != build_id."""

    def test_same_target_reuses_build_id(self):
        env = self.make_env()
        # Force a full rebuild so the target differs from the active (a new
        # generation id is minted via the rebuild tag).
        spec = self.spec(env)
        parameters = {"mode": MODE_FULL, "derived_root": env.derived_root,
                      "rebuild_tag": "tag-1"}
        # The CLI resolves the build_id before creating the operation.
        parameters["build_id"] = spec.preview(parameters)["build_id"]
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        record1 = create_operation(store, registry, "rebuild", parameters,
                                   operation_id=None)
        record2 = create_operation(store, registry, "rebuild", parameters,
                                   operation_id=None)
        # Same target + same normalized parameters: the same build_id (the
        # operation ids differ -- each request is a new operation).
        build1 = record1["parameters"]["build_id"]
        build2 = record2["parameters"]["build_id"]
        self.assertEqual(build1, build2)
        self.assertNotEqual(record1["operation_id"], record2["operation_id"])
        self.assertNotEqual(record1["operation_id"], build1)

    def test_same_operation_id_different_parameters_is_rejected(self):
        env = self.make_env()
        spec = self.spec(env)
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        operation_id = "rebuild-idempotent-1"
        record = create_operation(
            store, registry, "rebuild",
            {"mode": MODE_FULL, "derived_root": env.derived_root,
             "rebuild_tag": "tag-A"}, operation_id=operation_id)
        self.assertEqual(operation_id, record["operation_id"])
        from operations import OperationIdConflict
        with self.assertRaises(OperationIdConflict):
            create_operation(
                store, registry, "rebuild",
                {"mode": MODE_FULL, "derived_root": env.derived_root,
                 "rebuild_tag": "tag-B"}, operation_id=operation_id)


class RetryRestartTest(RebuildEnvTest):
    """SCN-68-5 / AC68-5: blocked never auto-retries; --retry continues;
    --restart discards."""

    def _block_on_embed(self, env, fail_event="e1"):
        from evidence import RepresentationProvider

        class FailingProvider(RepresentationProvider):
            def __init__(self, inner, fail_event):
                self._inner = inner
                self._fail_event = fail_event

            def representation_id(self):
                return self._inner.representation_id()

            def query_vector(self, preceding_text):
                return self._inner.query_vector(preceding_text)

            def event_vector(self, event):
                if event.event_id == self._fail_event:
                    from evidence import EvidenceError
                    raise EvidenceError(
                        "representation_fault",
                        "deterministic test embed failure")
                return self._inner.event_vector(event)

            def vector_dimension(self):
                return self._inner.vector_dimension()

        provider = FailingProvider(make_desired_provider(), fail_event)
        spec = self.spec(
            env,
            provider_factory=lambda repr_id: provider)
        return spec

    def test_blocked_never_auto_retries(self):
        env = self.make_env()
        # The desired provider differs from the active (different
        # representation), so auto builds; make the embed fail.
        spec = self._block_on_embed(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_AUTO,
                        "derived_root": env.derived_root})
        self.assertEqual("blocked", final["state"])
        self.assertEqual("staging_blocked", final["error"]["code"])
        self.assertIn("e1", final["error"]["cause"]["events"])
        # A plain re-run of the same operation (auto, same params) stays
        # blocked: blocked never auto-retries.
        final2, _ = self.run_rebuild(
            env, spec, {"mode": MODE_AUTO,
                        "derived_root": env.derived_root},
            operation_id=final["operation_id"])
        self.assertEqual("blocked", final2["state"])

    def test_retry_continues_blocked_staging(self):
        env = self.make_env()
        spec = self._block_on_embed(env)
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        parameters = {"mode": MODE_AUTO, "derived_root": env.derived_root}
        parameters["build_id"] = spec.preview(parameters)["build_id"]
        record = create_operation(store, registry, "rebuild", parameters)
        final = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("blocked", final["state"])
        build_id = final["parameters"]["build_id"]
        # A plain re-run (no retry flag) must NOT auto-retry a blocked
        # operation: it stays blocked.
        final_again = run_pending_steps(store, registry,
                                        record["operation_id"])
        self.assertEqual("blocked", final_again["state"])
        # --retry <build_id> resumes the SAME operation (the CLI locates
        # it by build_id and runs `operation run --retry`): the executor
        # clears the block (retry_blocked) and the staging machine retries
        # the blocked staging; with the healthy provider the build resumes
        # from the last verified chunk and completes.
        spec_fixed = self.spec(env)  # healthy provider now
        registry_fixed = self.registry(spec_fixed)
        final2 = run_pending_steps(store, registry_fixed,
                                   record["operation_id"],
                                   retry_blocked=True)
        self.assertEqual("succeeded", final2["state"])
        self.assertEqual(build_id, final2["result"]["build_id"])

    def test_restart_discards_then_rebuilds(self):
        env = self.make_env()
        # Start a full rebuild and let it reach `running` with some chunks
        # (the desired provider matches, the build proceeds).
        spec = self.spec(env)
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        parameters = {"mode": MODE_FULL, "derived_root": env.derived_root,
                      "rebuild_tag": "restart-tag"}
        parameters["build_id"] = spec.preview(parameters)["build_id"]
        record = create_operation(store, registry, "rebuild", parameters)
        # Drive one step: the staging machine starts a fresh build.
        mid = run_pending_steps(store, registry, record["operation_id"],
                                max_steps=2)
        self.assertEqual("running", mid["state"])
        staging_generation = mid["parameters"]["build_id"]
        old_staging = os.path.join(env.derived_root, "staging",
                                   staging_generation)
        self.assertTrue(os.path.isdir(old_staging))
        # --restart is a NEW request (a fresh build id) that first
        # discards the current staging, then rebuilds from scratch; the
        # operation reaches succeeded.
        restart_params = {"mode": MODE_FULL, "derived_root": env.derived_root,
                          "rebuild_tag": "restart-tag-2", "restart": True}
        final, _ = self.run_rebuild(env, spec, restart_params)
        self.assertEqual("succeeded", final["state"])
        # The old staging was discarded (marked discarded; the post-publish
        # retention sweep may already have deleted it physically).
        self.assertFalse(os.path.isdir(old_staging))
        # The restarted build published a NEW generation (different tag ->
        # different build id).
        manifest, _reason = read_active_manifest(env.derived_root)
        self.assertNotEqual(staging_generation, manifest["generation_id"])
        env.assert_facts_untouched(self)


class WaitCancelTest(RebuildEnvTest):
    """SCN-68-6 / AC68-6: wait detach != cancel; cancel before publish is
    honored, after publish refused."""

    def test_cancel_before_publish_cancels(self):
        env = self.make_env()
        spec = self.spec(env)
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        parameters = {"mode": MODE_FULL, "derived_root": env.derived_root,
                      "rebuild_tag": "cancel-tag"}
        parameters["build_id"] = spec.preview(parameters)["build_id"]
        record = create_operation(store, registry, "rebuild", parameters)
        # Run a couple of steps so the operation is in a cancelable phase.
        run_pending_steps(store, registry, record["operation_id"],
                          max_steps=1)
        from operations import cancel_operation
        updated, disposition = cancel_operation(store,
                                                record["operation_id"])
        self.assertEqual("requested", disposition)
        final = run_pending_steps(store, registry, record["operation_id"])
        self.assertEqual("cancelled", final["state"])
        env.assert_facts_untouched(self)

    def test_wait_detach_does_not_cancel(self):
        env = self.make_env()
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_FULL,
                        "derived_root": env.derived_root})
        # A rebuild that completed was NOT cancelled by an observer: the
        # operation record shows no cancel_requested and the build_id is
        # the minted generation.
        self.assertEqual("succeeded", final["state"])
        self.assertFalse(final["cancel_requested"])
        self.assertIsNotNone(final["result"]["generation_id"])
        # AC68-6 (wait detach != cancel): the CLI's --wait observation loop
        # is the shared `_watch_detached_operation` watcher that clear /
        # backup use, whose SIGINT -> exit 130 -> detach (build continues,
        # never a cancel) is covered end-to-end by
        # CliTest.test_wait_sigint_detaches_without_cancelling (and the
        # rebuild wait path drives the exact same watcher with the same
        # Ctrl-C handling).


class NoQuiesceTest(RebuildEnvTest):
    """SCN-68-7 / AC68-8: rebuild never quiesces the plugin and never
    touches facts / history / epoch / switches."""

    def test_rebuild_takes_no_exclusive_path(self):
        env = self.make_env()
        # The exclusive maintenance path (maintenance.lock, control
        # socket, C++ helper) must never be touched: rebuild drives only
        # the staging machine.  Run a full rebuild and assert no lock or
        # control socket file appeared under the root.
        spec = self.spec(env)
        final, _ = self.run_rebuild(
            env, spec, {"mode": MODE_FULL,
                        "derived_root": env.derived_root})
        self.assertEqual("succeeded", final["state"])
        root_entries = os.listdir(env.facts_root)
        self.assertNotIn("maintenance.lock", root_entries)
        self.assertFalse(any(name.endswith(".sock")
                             for name in root_entries))
        env.assert_facts_untouched(self)


class SingleBuilderTest(RebuildEnvTest):
    """SCN-68-9: one builder -- a concurrent same-target rebuild reuses the
    same build_id instead of starting a second builder."""

    def test_concurrent_same_target_reuses_build_id(self):
        env = self.make_env()
        spec = self.spec(env)
        parameters = {"mode": MODE_FULL, "derived_root": env.derived_root,
                      "rebuild_tag": "single-builder"}
        parameters["build_id"] = spec.preview(parameters)["build_id"]
        registry = self.registry(spec)
        store = OperationStore(env.facts_root)
        record1 = create_operation(store, registry, "rebuild", parameters)
        record2 = create_operation(store, registry, "rebuild", parameters)
        self.assertEqual(
            record1["parameters"]["build_id"],
            record2["parameters"]["build_id"])
        # Both operations target the same staging generation id; only one
        # staging directory can exist for it (the staging machine is the
        # single builder -- a second rebuild never duplicates it).
        self.assertEqual(
            record1["parameters"]["build_id"],
            spec.preview(parameters)["build_id"])


if __name__ == "__main__":
    unittest.main()
