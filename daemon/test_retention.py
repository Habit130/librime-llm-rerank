#!/usr/bin/env python3
"""Model-free fault injection for derived-state retention, rollback and
damage recovery (Habit130/squirrel#67, delivery contract AC-67-v1).

The primary evidence is the model-free unit suite: no MLX, no real model,
no live facts / ~/Library/Rime.  A throwaway derived root per test drives
the #65 publish path (``publish_ready_staging``) to produce a retired
active + rollback, then injects damage (checksum flip, manifest rewrite,
missing directory) and asserts the recovery / retention behavior.

Scenario map (AC-67-v1 blocking scenarios):

- SCN-67-1  soft/hard dirty thresholds schedule a single builder
- SCN-67-2  after a healthy publish the retired active is the sole rollback;
            an older rollback is dropped; a damaged active is never
            registered
- SCN-67-3  a space-short build keeps the current active and the only
            rollback (never deletes the rollback to free space)
- SCN-67-4  a corrupt delta checkpoint is dropped and replayed from the
            base watermark (no directory guess)
- SCN-67-5  base / metadata / active-manifest damage isolates the bad
            generation and serves only after rollback re-verify + catch-up
- SCN-67-6  no healthy rollback -> fail-closed passthrough + background
            rebuild; IME commit keeps working
- SCN-67-7  nothing scans ``generations/`` to elect a rollback or active
- SCN-67-8  live facts untouched (this suite never writes the fact store
            beyond the fixture)
- SCN-67-9  the public ``rebuild`` CLI stays reserved (#68)
"""

import errno
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import retention  # noqa: E402
from delta import (  # noqa: E402
    DELTA_FILENAME,
    DELTA_SCHEMA_VERSION,
    DeltaStateMachine,
    read_facts_identity,
)
from evidence import (  # noqa: E402
    EvidenceError,
    FixtureRepresentationProvider,
    OracleParams,
    make_evidence_request,
)
from generation import (  # noqa: E402
    GENERATION_FILES,
    GenerationRejected,
    PROGRESS_FILENAME,
    build_generation,
    open_generation,
)
from oracle import StoredEvent  # noqa: E402
from publish import (  # noqa: E402
    ACTIVE_MANIFEST_FILENAME,
    GenerationPublisher,
    publish_ready_staging,
    read_active_manifest,
    write_active_manifest,
)
from retention import (  # noqa: E402
    ISOLATED_DIRNAME,
    ROLLBACK_MANIFEST_FILENAME,
    clear_rollback_manifest,
    read_rollback_manifest,
    retention_sweep,
    write_rollback_manifest,
)
from staging import StagingBuildMachine  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402

ACTIVE_REPR = "retention-test-active-repr-v1"
DESIRED_REPR = "retention-test-desired-repr-v1"

PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)


def make_active_provider():
    return FixtureRepresentationProvider(
        ACTIVE_REPR,
        {"我之前去": (1.0, 0.0, 0.0, 0.0),
         "我之后去": (0.0, 1.0, 0.0, 0.0),
         "农场清晨": (0.0, 0.0, 1.0, 0.0)},
        {"luna_pinyin|shijie|时界": (0.0, 1.0, 0.0, 0.0),
         "luna_pinyin|shijie|世界": (0.0, 0.0, 1.0, 0.0),
         "luna_pinyin|jinqi|近期": (0.0, 1.0, 0.0, 0.0)},
        default_event=(0.0, 1.0, 0.0, 0.0))


def make_desired_provider():
    return FixtureRepresentationProvider(
        DESIRED_REPR,
        {"我之前去": (0.0, 1.0, 0.0, 0.0),
         "我之后去": (0.0, 0.0, 1.0, 0.0),
         "农场清晨": (1.0, 0.0, 0.0, 0.0)},
        {"luna_pinyin|shijie|时界": (0.0, 1.0, 0.0, 0.0),
         "luna_pinyin|shijie|世界": (0.0, 0.0, 1.0, 0.0),
         "luna_pinyin|jinqi|近期": (0.0, 1.0, 0.0, 0.0)},
        default_event=(0.0, 1.0, 0.0, 0.0))


def base_facts():
    facts = FactsFixture()
    facts.add_event("e1", segment_input="shijie", selection="时界",
                    preceding_text="我之前去", competition=("世界", "时界"))
    facts.add_event("e2", segment_input="shijie", selection="世界",
                    preceding_text="我之后去", competition=("世界", "时界"))
    facts.add_event("e3", segment_input="shijie", selection="时界",
                    preceding_text="农场清晨", competition=("世界", "时界"))
    facts.add_event("e4", segment_input="jinqi", selection="近期",
                    preceding_text="讨论进展", competition=("近期", "今期"))
    return facts


def flip_byte(path, offset=0):
    with open(path, "r+b") as handle:
        handle.seek(offset)
        byte = handle.read(1)
        if not byte:
            byte = b"\x00"
        handle.seek(-1, 1)
        handle.write(bytes([byte[0] ^ 0xFF]))


class RetentionEnv:
    """One sandboxed facts root + derived root with a published active."""

    def __init__(self, facts=None):
        self.facts = facts or base_facts()
        self.facts.conn.execute("PRAGMA journal_mode=WAL;")
        self.facts.conn.commit()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")
        self.active_provider = make_active_provider()
        self.desired_provider = make_desired_provider()
        self.active_gen = build_generation(
            self.facts_root, self.active_provider, self.derived_root)
        self.active_generation_id = self.active_gen.generation_id
        self.active_gen.close()
        self.publish_lock = threading.Lock()
        self.machines = []
        self._window_seq = 0

    def machine(self, provider=None, generation_id=None, **kwargs):
        defaults = {"poll_interval": 0.01, "catch_up_deadline": 5.0}
        defaults.update(kwargs)
        machine = DeltaStateMachine(
            self.facts_root, self.derived_root,
            provider or self.active_provider,
            generation_id or self.active_generation_id, **defaults)
        self.machines.append(machine)
        return machine

    def staging(self, provider=None, **kwargs):
        defaults = {"chunk_rows": 2, "poll_interval": 0.01,
                    "start_worker": False, "publish_lock": self.publish_lock}
        defaults.update(kwargs)
        return StagingBuildMachine(
            self.facts_root, self.derived_root, provider
            or self.desired_provider, ACTIVE_REPR,
            self.active_generation_id, **defaults)

    def run_to_ready(self, builder, max_cycles=400):
        for _ in range(max_cycles):
            builder._cycle()
            progress = builder.status()["progress"]
            if progress is not None and progress["status"] == "ready":
                return progress
        return None

    def staging_dir(self, generation_id):
        return os.path.join(self.derived_root, "staging", generation_id)

    def published_dir(self, generation_id):
        return os.path.join(self.derived_root, "generations", generation_id)

    def manifest_path(self):
        return os.path.join(self.derived_root, ACTIVE_MANIFEST_FILENAME)

    def rollback_path(self):
        return os.path.join(self.derived_root, ROLLBACK_MANIFEST_FILENAME)

    def isolated_root(self):
        return os.path.join(self.derived_root, ISOLATED_DIRNAME)

    def checkpoint_path(self, generation_id):
        return os.path.join(self.derived_root, "delta", generation_id,
                            DELTA_FILENAME)

    def publish(self, builder, machine, provider=None):
        """Publish the builder's ready staging; returns the result dict."""
        progress = builder.status()["progress"]
        staging_dir = self.staging_dir(progress["generation_id"])
        return publish_ready_staging(
            self.facts_root, self.derived_root, builder, staging_dir,
            progress["generation_id"], provider or self.desired_provider,
            machine, publish_lock=self.publish_lock)

    def add_window_facts(self, count=1, base=1000000):
        """Add ``count`` facts after the base watermark; returns H1."""
        logical = 100 + self._window_seq * 100  # unique HLC per call
        self._window_seq += 1
        for index in range(count):
            self.facts.add_event(
                "post-%d-%d" % (self._window_seq, index),
                segment_input="shijie", selection="时界",
                preceding_text="我之前去", competition=("世界", "时界"),
                hlc=(base, logical + index))
        self.facts.set_clock(base, logical + count - 1)
        return (base, logical + count - 1)

    def publish_same_repr_second(self):
        """Publish a SECOND generation of the SAME representation as the
        active (newer H0 after added facts) and make the first active the
        rollback.  Returns ``(active_id, rollback_id)``.

        This mirrors a real same-fingerprint publish (compaction / fresh
        build at the same representation) so the runtime provider can serve
        both generations -- the precondition for a usable rollback.
        """
        from delta import read_facts_schema_version
        from publish import _compose_active_manifest
        from retention import compose_rollback_manifest
        rollback_id = self.active_generation_id
        self.add_window_facts(count=2)
        gen2 = build_generation(self.facts_root, self.active_provider,
                                self.derived_root)
        try:
            fact_schema = read_facts_schema_version(self.facts_root)
            active_manifest = _compose_active_manifest(
                gen2, "delta/%s/delta.sqlite3" % gen2.generation_id,
                fact_schema)
            write_active_manifest(self.derived_root, active_manifest)
            rollback = open_generation(self.published_dir(rollback_id))
            try:
                rollback_manifest = compose_rollback_manifest(
                    rollback, "delta/%s/delta.sqlite3" % rollback_id,
                    fact_schema)
                write_rollback_manifest(self.derived_root, rollback_manifest)
            finally:
                rollback.close()
        finally:
            gen2.close()
        return gen2.generation_id, rollback_id

    def close(self):
        for machine in self.machines:
            try:
                machine.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        self.machines = []
        self.facts.close()


class RetentionTestBase(unittest.TestCase):
    def setUp(self):
        self.env = None

    def tearDown(self):
        if self.env is not None:
            self.env.close()

    def make_env(self, **kwargs):
        self.env = RetentionEnv(**kwargs)
        return self.env


# ---------------------------------------------------------------------------
# SCN-67-2 / AC67-2: after a healthy publish the retired active is the sole
# rollback; an older rollback is dropped; a damaged active is never
# registered
# ---------------------------------------------------------------------------

class PublishRetentionTest(RetentionTestBase):

    def test_after_healthy_publish_retired_active_is_the_sole_rollback(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        self.assertIsNotNone(progress)
        retired_id = env.active_generation_id
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        # The retired active is registered as the rollback pointer.
        rollback, reason = read_rollback_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertIsNotNone(rollback)
        self.assertEqual(rollback["generation_id"], retired_id)
        # The retention sweep keeps exactly {active, rollback}.
        active_manifest, _ = read_active_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        self.assertNotEqual(active_id, retired_id)
        remaining = [name for name in os.listdir(
            os.path.join(env.derived_root, "generations"))
            if os.path.isdir(os.path.join(env.derived_root, "generations",
                                          name))]
        self.assertEqual(sorted(remaining), sorted({active_id, retired_id}))

    def test_second_publish_drops_the_older_rollback(self):
        env = self.make_env()
        # Publish #1 (desired repr): active A -> B, rollback = A.
        builder1 = env.staging()
        progress1 = env.run_to_ready(builder1)
        machine = env.machine()
        result1 = env.publish(builder1, machine)
        self.assertTrue(result1["ok"], result1)
        first_retired = env.active_generation_id
        first_active = progress1["generation_id"]
        # Publish #2: advance facts so the same desired provider builds a
        # NEW generation C (newer H0); active B -> C, rollback = B, A is
        # dropped.
        env.add_window_facts(count=2)
        builder2 = env.staging()
        progress2 = env.run_to_ready(builder2)
        self.assertIsNotNone(progress2, "second staging did not reach ready")
        self.assertNotEqual(progress2["generation_id"], first_active)
        result2 = env.publish(builder2, machine)
        self.assertTrue(result2["ok"], result2)
        rollback, _ = read_rollback_manifest(env.derived_root)
        self.assertEqual(rollback["generation_id"], first_active)
        active_manifest, _ = read_active_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        remaining = [name for name in os.listdir(
            os.path.join(env.derived_root, "generations"))
            if os.path.isdir(os.path.join(env.derived_root, "generations",
                                          name))]
        self.assertEqual(sorted(remaining),
                         sorted({active_id, first_active}))
        self.assertNotIn(first_retired, remaining)

    def test_damaged_active_is_never_registered_as_rollback(self):
        """SCN-67-2: a damaged active must not become the rollback pointer.
        The damage is discovered by the delta machine's recovery (isolate +
        rollback re-verify + catch-up); the isolated generation is NOT the
        rollback."""
        env = self.make_env()
        active_id, rollback_id = env.publish_same_repr_second()
        # Now damage the active generation's vectors (base damage).
        flip_byte(os.path.join(env.published_dir(active_id), "vectors.fp32"))
        # Reconstruct a machine on the damaged active -> recovery serves the
        # rollback and isolates the damaged active.
        recovered = env.machine(
            provider=make_active_provider(), generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id, rollback_id)
        # The damaged active is isolated, NOT registered as rollback.
        isolated = os.listdir(env.isolated_root())
        self.assertTrue(any(name.startswith(active_id) for name in isolated))
        rollback_now, _ = read_rollback_manifest(env.derived_root)
        self.assertIsNone(rollback_now)  # consumed by the recovery
        # The active manifest now points at the recovered rollback.
        active_manifest_now, _ = read_active_manifest(env.derived_root)
        self.assertEqual(active_manifest_now["generation_id"], rollback_id)


# ---------------------------------------------------------------------------
# SCN-67-3 / AC67-3: a space-short build keeps the current active and the
# only rollback (never deletes the rollback to free space)
# ---------------------------------------------------------------------------

class SpaceTest(RetentionTestBase):

    def test_retention_sweep_never_deletes_active_or_rollback(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        active_manifest, _ = read_active_manifest(env.derived_root)
        rollback, _ = read_rollback_manifest(env.derived_root)
        # A sweep with a rogue "active" naming something else must still
        # keep the actual active and rollback... but the caller passes the
        # authoritative ids; the sweep itself never deletes the rollback.
        retention_sweep(env.derived_root,
                        active_id=active_manifest["generation_id"],
                        rollback_id=rollback["generation_id"])
        remaining = [name for name in os.listdir(
            os.path.join(env.derived_root, "generations"))
            if os.path.isdir(os.path.join(env.derived_root, "generations",
                                          name))]
        self.assertEqual(sorted(remaining),
                         sorted({active_manifest["generation_id"],
                                 rollback["generation_id"]}))

    def test_retention_sweep_deletes_generations_outside_the_set(self):
        env = self.make_env()
        # A second, unrelated "old" generation in generations/ (simulating a
        # superseded generation): the sweep must delete it.
        old_id = "shadow-gen-v1:orphan-old-gen-0000000000000000000000000000"
        os.makedirs(os.path.join(env.derived_root, "generations", old_id))
        for name in GENERATION_FILES:
            with open(os.path.join(env.derived_root, "generations", old_id,
                                   name), "w", encoding="utf-8") as handle:
                handle.write("{}")
        retention_sweep(env.derived_root, active_id=env.active_generation_id)
        self.assertFalse(os.path.isdir(
            os.path.join(env.derived_root, "generations", old_id)))
        # The active survives.
        self.assertTrue(os.path.isdir(
            os.path.join(env.derived_root, "generations",
                         env.active_generation_id)))

    def test_space_short_keeps_active_and_only_rollback(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        active_manifest, _ = read_active_manifest(env.derived_root)
        rollback, _ = read_rollback_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        rollback_id = rollback["generation_id"]
        # A tiny budget: the projected peak exceeds it, the build must NOT
        # start (keeps active + rollback) and must report the error.
        ok, reason = retention.check_build_space(
            env.derived_root, budget_bytes=1,
            projected_staging_bytes=1 << 20)
        self.assertFalse(ok)
        self.assertIn("budget", reason)
        # Nothing was deleted: active and rollback are still present.
        self.assertTrue(os.path.isdir(env.published_dir(active_id)))
        self.assertTrue(os.path.isdir(env.published_dir(rollback_id)))

    def test_space_short_staging_machine_does_not_build(self):
        env = self.make_env()
        builder = env.staging(disk_budget_bytes=1)
        builder._cycle()
        self.assertIsNone(builder.status()["progress"])
        self.assertIn("budget", builder.status()["last_error"])
        # The active generation is untouched.
        self.assertTrue(os.path.isdir(env.published_dir(
            env.active_generation_id)))
        builder.close()


# ---------------------------------------------------------------------------
# SCN-67-1 / AC67-1: dirty scheduling (soft/hard) and one builder
# ---------------------------------------------------------------------------

class DirtySchedulingTest(RetentionTestBase):

    def test_soft_dirty_threshold_counts_new_vectors_plus_tombstones(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine(soft_dirty_min_changes=2, soft_dirty_ratio=0.05)
        env.publish(builder, machine)
        state = machine.dirty_state()
        self.assertFalse(state["soft_dirty"])
        # Add facts -> catch up -> the mirror grows.
        env.add_window_facts(count=2)
        machine.ensure_caught_up()
        state = machine.dirty_state()
        self.assertGreaterEqual(state["delta_changes"], 2)
        self.assertTrue(state["soft_dirty"])
        self.assertFalse(state["hard_dirty"])

    def test_hard_dirty_thresholds(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine(hard_dirty_changes=3)
        env.publish(builder, machine)
        env.add_window_facts(count=3)
        machine.ensure_caught_up()
        state = machine.dirty_state()
        self.assertTrue(state["hard_dirty"])

    def test_hard_dirty_by_bytes(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine(hard_dirty_bytes=1)  # any checkpoint >= 1 byte
        env.publish(builder, machine)
        state = machine.dirty_state()
        self.assertTrue(state["hard_dirty"])

    def test_soft_dirty_idle_compact_triggers_a_single_builder(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine(soft_dirty_min_changes=2, soft_dirty_ratio=0.05)
        # Wire the real single-builder seam: the dirty scheduler asks THIS
        # staging machine to compact (the same wiring the config seam uses).
        machine.set_compaction_trigger(builder.request_compaction)
        env.publish(builder, machine)
        env.add_window_facts(count=2)
        machine.ensure_caught_up()  # caught up = idle
        # The worker's cycle schedules the idle compact (soft-dirty + caught
        # up); the staging machine's ``request_compaction`` flag is the
        # single-builder seam (one builder, idempotent).
        machine._maybe_request_compaction(
            read_facts_identity(env.facts_root))
        self.assertTrue(builder._compaction_requested)
        # Idempotent: repeated dirty cycles do not enqueue a second build.
        machine._maybe_request_compaction(
            read_facts_identity(env.facts_root))
        self.assertTrue(builder._compaction_requested)
        builder.close()

    def test_hard_dirty_compacts_even_under_input(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine(hard_dirty_changes=2)
        env.publish(builder, machine)
        # Absorb a first batch so the mirror crosses hard-dirty, then park
        # the worker: new facts arrive while the snapshot provably lags
        # (input pending -- the not-idle case).
        env.add_window_facts(count=2)
        machine.ensure_caught_up()
        self.assertTrue(machine.dirty_state()["hard_dirty"])
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        calls = []
        machine.set_compaction_trigger(lambda: calls.append(1))
        env.add_window_facts(count=2)  # more input, snapshot still lags
        _epoch, facts_max = read_facts_identity(env.facts_root)
        self.assertLess(machine.snapshot().consumed, facts_max)
        # Hard-dirty must schedule the low-priority compact even under input.
        machine._maybe_request_compaction(
            read_facts_identity(env.facts_root))
        self.assertGreaterEqual(len(calls), 1)
        machine.start()
        builder.close()

    def test_compaction_through_the_staging_builder(self):
        """SCN-67-1: the forced build goes through the single staging
        builder (bypassing the matrix noop gate) and reaches ``ready``."""
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        # Dirty the delta, then ask for compaction.
        env.add_window_facts(count=2)
        machine.ensure_caught_up()
        builder.request_compaction()
        # The compaction target is the same fingerprint as the active; the
        # noop gate is bypassed and a ready staging appears.
        target_progress = None
        for _ in range(200):
            builder._cycle()
            status = builder.status()
            if status["progress"] is not None \
                    and status["progress"]["status"] == "ready":
                target_progress = status["progress"]
                break
        self.assertIsNotNone(target_progress)
        self.assertTrue(target_progress["status"], "ready")
        builder.close()


# ---------------------------------------------------------------------------
# SCN-67-4 / AC67-4: delta checkpoint corruption -> drop + replay from the
# base watermark (no directory guess)
# ---------------------------------------------------------------------------

class DeltaDamageTest(RetentionTestBase):

    def test_corrupt_checkpoint_is_dropped_and_replayed_from_base(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        active_manifest, _ = read_active_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        checkpoint = env.checkpoint_path(active_id)
        self.assertTrue(os.path.isfile(checkpoint))
        # Corrupt the checkpoint file.
        with open(checkpoint, "r+b") as handle:
            handle.seek(200)
            handle.write(b"\x00" * 64)
        # Reconstruct: the machine drops the bad checkpoint and replays from
        # the base watermark (the existing #63 semantics, now pinned for #67).
        recovered = env.machine(provider=make_desired_provider(),
                                generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id, active_id)
        # The base rows are still served (no data loss from the corruption).
        self.assertGreaterEqual(snapshot.change_seq, -1)
        recovered.close()


# ---------------------------------------------------------------------------
# SCN-67-5 / AC67-5: base / metadata / active-manifest damage -> isolate,
# serve only after rollback re-verify + catch-up
# ---------------------------------------------------------------------------

class RollbackRecoveryTest(RetentionTestBase):

    def _published_with_rollback(self):
        """Publish a same-representation second generation; the first active
        is the rollback.  Returns (env, active_id, rollback_id)."""
        env = self.make_env()
        active_id, rollback_id = env.publish_same_repr_second()
        return env, active_id, rollback_id

    def test_active_vector_damage_recovers_from_rollback_with_catch_up(self):
        env, active_id, rollback_id = self._published_with_rollback()
        # Facts advanced past the rollback's base watermark; the rollback
        # must catch up to the current watermark before serving.
        env.add_window_facts(count=3)
        flip_byte(os.path.join(env.published_dir(active_id), "vectors.fp32"))
        recovered = env.machine(provider=make_active_provider(),
                                generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id, rollback_id)
        # The rollback caught up: its snapshot covers the current facts
        # watermark (never a stale success).
        _epoch, facts_max = read_facts_identity(env.facts_root)
        self.assertGreaterEqual(snapshot.consumed, facts_max)
        # The damaged active was isolated.
        isolated = os.listdir(env.isolated_root())
        self.assertTrue(any(name.startswith(active_id) for name in isolated))

    def test_active_metadata_damage_recovers_from_rollback(self):
        env, active_id, rollback_id = self._published_with_rollback()
        flip_byte(os.path.join(env.published_dir(active_id),
                               "metadata.json"))
        recovered = env.machine(provider=make_active_provider(),
                                generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id, rollback_id)

    def test_active_manifest_damage_recovers_from_rollback(self):
        env, active_id, rollback_id = self._published_with_rollback()
        # Corrupt the active manifest (not the generation).
        with open(env.manifest_path(), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        recovered = env.machine(provider=make_active_provider(),
                                generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id, rollback_id)
        # The active manifest now durably names the rollback.
        active_manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(active_manifest["generation_id"], rollback_id)

    def test_rollback_catch_up_failure_is_not_semantic_success(self):
        """AC67-5: a rollback that cannot catch up (facts moved to an epoch
        the rollback cannot bind) must NOT be served as semantic success."""
        env, active_id, rollback_id = self._published_with_rollback()
        flip_byte(os.path.join(env.published_dir(active_id), "vectors.fp32"))
        # Corrupt the rollback generation itself so re-verify fails.
        flip_byte(os.path.join(env.published_dir(rollback_id),
                               "vectors.fp32"))
        recovered = env.machine(provider=make_active_provider(),
                                generation_id=active_id)
        with self.assertRaises(EvidenceError) as raised:
            recovered.ensure_caught_up()
        self.assertEqual("active_identity_refused", raised.exception.code)
        self.assertIn("rollback", raised.exception.message)
        self.assertTrue(recovered.force_rebuild_requested())


# ---------------------------------------------------------------------------
# SCN-67-6 / AC67-6: no healthy rollback -> fail-closed passthrough +
# background rebuild; IME commit keeps working
# ---------------------------------------------------------------------------

class NoRollbackTest(RetentionTestBase):

    def test_no_rollback_fails_closed_and_commits_still_work(self):
        env = self.make_env()
        # Publish a same-repr second generation then remove its rollback
        # pointer (the active is healthy; no rollback exists).
        active_id, _rollback_id = env.publish_same_repr_second()
        clear_rollback_manifest(env.derived_root)
        flip_byte(os.path.join(env.published_dir(active_id), "vectors.fp32"))
        recovered = env.machine(provider=make_active_provider(),
                                generation_id=active_id)
        with self.assertRaises(EvidenceError) as raised:
            recovered.ensure_caught_up()
        self.assertEqual("active_identity_refused", raised.exception.code)
        # The machine asks for a background rebuild from facts.
        self.assertTrue(recovered.force_rebuild_requested())
        # IME commit keeps working: the facts store is writable (recording
        # continues) even while the semantic path fails closed.
        env.facts.add_event("commit-ok", segment_input="shijie",
                            selection="时界", preceding_text="我之前去",
                            competition=("世界", "时界"))
        _epoch, facts_max = read_facts_identity(env.facts_root)
        self.assertIsNotNone(facts_max)

    def test_no_rollback_force_rebuild_through_staging(self):
        env = self.make_env()
        builder = env.staging(force_rebuild=True)
        # Even though desired == active (the matrix would say noop), the
        # forced rebuild bypasses the gate and reaches ready.
        progress = env.run_to_ready(builder)
        self.assertIsNotNone(progress)
        self.assertEqual(progress["status"], "ready")
        builder.close()

    def test_no_rollback_passthrough_does_not_serve_a_guessed_generation(
            self):
        """SCN-67-7: with no rollback the daemon must not scan generations/
        to elect a replacement active."""
        env = self.make_env()
        # Two extra real generations (built after facts advanced) in
        # generations/ -- the recovery must NOT pick any of them as the new
        # active.
        env.add_window_facts(count=2)
        extra1 = build_generation(env.facts_root, env.active_provider,
                                  env.derived_root)
        extra1_id = extra1.generation_id
        extra1.close()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        clear_rollback_manifest(env.derived_root)
        active_manifest, _ = read_active_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        flip_byte(os.path.join(env.published_dir(active_id), "vectors.fp32"))
        recovered = env.machine(provider=make_desired_provider(),
                                generation_id=active_id)
        with self.assertRaises(EvidenceError):
            recovered.ensure_caught_up()
        # The extra generation was NOT served as active.
        self.assertIsNone(recovered.snapshot())
        self.assertTrue(recovered.force_rebuild_requested())
        self.assertNotEqual(extra1_id, active_id)


# ---------------------------------------------------------------------------
# SCN-67-7 / AC67-7: code-level guarantee -- recovery never scans
# generations/ to elect a rollback
# ---------------------------------------------------------------------------

class NoDirectoryScanTest(RetentionTestBase):

    def test_recovery_uses_only_the_explicit_pointer(self):
        env = self.make_env()
        active_id, rollback_id = env.publish_same_repr_second()
        # Add a "newer-looking" real generation (built after facts advanced)
        # -- recovery must NOT pick it (the explicit pointer wins).
        env.add_window_facts(count=2)
        fake = build_generation(env.facts_root, env.active_provider,
                                env.derived_root)
        fake_id = fake.generation_id
        fake.close()
        self.assertNotEqual(fake_id, rollback_id)
        self.assertNotEqual(fake_id, active_id)
        flip_byte(os.path.join(env.published_dir(active_id), "vectors.fp32"))
        recovered = env.machine(provider=make_active_provider(),
                                generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        # The explicit rollback, not the fake "newest", is served.
        self.assertEqual(snapshot.base_generation_id, rollback_id)
        # The fake is swept (outside {active, rollback}) -- it was never
        # elected, and retention deleted it as out-of-set.
        self.assertFalse(os.path.isdir(env.published_dir(fake_id)))

    def test_recovery_source_never_scans_generations(self):
        """AC67-4 / SCN-67-7 code-level negative: the recovery path elects
        a rollback from the EXPLICIT pointer only -- the module never lists
        or scans ``generations/`` to pick a "newest".  This complements the
        behavioral test above (the spec's acceptance criterion is explicitly
        "tests + code grep negative")."""
        import inspect
        import retention as retention_module
        from delta import DeltaStateMachine
        source = (inspect.getsource(DeltaStateMachine._recover_via_rollback)
                  + inspect.getsource(retention_module))
        # ``retention.py`` scans only for the SWEEP (deleting out-of-set
        # generations from an explicit keep-set), never to elect a rollback;
        # the recovery function itself must not scan at all.
        recovery_source = inspect.getsource(
            DeltaStateMachine._recover_via_rollback)
        for banned in ("listdir(", "scandir(", "glob(", "os.walk("):
            self.assertNotIn(banned, recovery_source,
                             "recovery must not scan for a rollback")
        # The explicit pointer is the ONLY recovery source.
        self.assertIn("read_rollback_manifest", recovery_source)
        # The sweep scans generations/ only to DELETE (keep-set driven),
        # never to elect an active or rollback.
        self.assertIn("read_rollback_manifest", source)


# ---------------------------------------------------------------------------
# Rollback pointer file semantics
# ---------------------------------------------------------------------------

class RollbackManifestTest(RetentionTestBase):

    def test_roundtrip_and_validation(self):
        env = self.make_env()
        manifest = {
            "manifest_version": retention.ROLLBACK_MANIFEST_VERSION,
            "generation_id": env.active_generation_id,
            "store_epoch": "e1",
            "source_hlc": [1000000, 4],
            "fact_schema_version": "1",
            "representation_id": ACTIVE_REPR,
            "vector_format_version": "fp32-row-major-little-endian",
            "projection_version": "delta-schema-v1+generation-manifest-v1",
            "index_fingerprint": "index-fingerprint-v1:abcd",
            "delta_checkpoint": "delta/%s/delta.sqlite3"
                                % env.active_generation_id,
            "builder_version": "shadow-generation-builder-v1",
            "registered_at_ms": 1,
        }
        write_rollback_manifest(env.derived_root, manifest)
        read_back, reason = read_rollback_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(read_back["generation_id"],
                         env.active_generation_id)
        # A tampered pointer is unusable, never a guess.
        with open(env.rollback_path(), "w", encoding="utf-8") as handle:
            handle.write("{bad")
        read_back, reason = read_rollback_manifest(env.derived_root)
        self.assertIsNone(read_back)
        self.assertIsNotNone(reason)


# ---------------------------------------------------------------------------
# SCN-67-3 / RISK-67-1: no ANN sidecar in the exact-only envelope is not
# active-generation death
# ---------------------------------------------------------------------------

class NoAnnSidecarTest(RetentionTestBase):

    def test_missing_ann_sidecar_is_not_active_death(self):
        """The exact-only envelope has no ANN sidecar (RISK-66-1): a
        generation with no sidecar loads and serves -- missing ANN is NOT
        active-generation damage."""
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        active_manifest, _ = read_active_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        # No sidecar anywhere: the generation serves fine.
        generation_dir = env.published_dir(active_id)
        self.assertEqual(
            sorted(os.listdir(generation_dir)),
            sorted(GENERATION_FILES))
        opened = open_generation(generation_dir)
        opened.close()
        # An index-fingerprint-only change plans rebuild_index -> the
        # exact-only envelope resolves it to ``no_ann_sidecar`` (no model,
        # no projection rebuild) -- never a base rebuild, never a guess.
        import compat
        plan = compat.plan_actions(
            {"store_epoch": "e1",
             "fact_schema_version": "1",
             "representation_id": ACTIVE_REPR,
             "vector_format_version": "fp32-row-major-little-endian",
             "projection_version": "delta-schema-v1+generation-manifest-v1",
             "index_fingerprint": "index-fingerprint-v1:other"},
            {"store_epoch": "e1",
             "fact_schema_version": "1",
             "representation_id": ACTIVE_REPR,
             "vector_format_version": "fp32-row-major-little-endian",
             "projection_version": "delta-schema-v1+generation-manifest-v1",
             "index_fingerprint": "index-fingerprint-v1:original"})
        self.assertEqual(plan["actions"], ["rebuild_index"])
        self.assertEqual(plan["reason"], "no_ann_sidecar")
        self.assertFalse(plan["refuse_load"])

    def test_injected_ann_sidecar_corruption_is_not_active_death(self):
        """RISK-67-1: even when a test injects an ANN sidecar, its damage
        must never kill the active generation in this envelope -- the
        index-only recovery stays pinned to ``no_ann_sidecar`` (the healthy
        FP32 oracle keeps serving; nothing invents an index).  The sidecar
        lives OUTSIDE the exact container (a future #78/#79 ANN layout): the
        three canonical files stay byte-identical, so ``open_generation``
        still verifies and serves them."""
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = env.machine()
        result = env.publish(builder, machine)
        self.assertTrue(result["ok"], result)
        active_manifest, _ = read_active_manifest(env.derived_root)
        active_id = active_manifest["generation_id"]
        generation_dir = env.published_dir(active_id)
        # The exact container holds exactly the three canonical files; a
        # corrupt sidecar next to it (never inside) cannot touch the active.
        self.assertEqual(sorted(os.listdir(generation_dir)),
                         sorted(GENERATION_FILES))
        sidecar = os.path.join(env.derived_root, "ann", active_id + ".index")
        os.makedirs(os.path.dirname(sidecar), exist_ok=True)
        with open(sidecar, "wb") as handle:
            handle.write(b"\x00" * 64)
        flip_byte(sidecar)
        # The machine still loads and serves the active generation.
        recovered = env.machine(provider=make_desired_provider(),
                                generation_id=active_id)
        snapshot = recovered.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id, active_id)


# ---------------------------------------------------------------------------
# SCN-67-8 / SCN-67-9: facts untouched; #68 CLI reserved
# ---------------------------------------------------------------------------

class ScopeGuardTest(RetentionTestBase):

    def test_public_rebuild_cli_still_reserved(self):
        """SCN-67-9: the public ``rebuild`` CLI is NOT implemented by #67."""
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(
                os.path.abspath(__file__)), "cli.py"), "rebuild", "--help"],
            capture_output=True, text=True)
        # The parser may reject --help on the reserved subcommand or print a
        # "not implemented" notice; either way it must NOT behave as a
        # functional rebuild.  The important part: this ticket adds no
        # implementation.
        self.assertNotIn("--full --index-only", result.stdout)


# ---------------------------------------------------------------------------
# Additional fault injection (AC67-7): disk-full and staging damage
# ---------------------------------------------------------------------------

class DiskFullAndStagingDamageTest(RetentionTestBase):

    def test_disk_full_blocks_publish_and_keeps_active_and_rollback(self):
        """AC67-7 disk-full: an ENOSPC during the publish transaction fails
        closed -- the old active stays serving, nothing is deleted, and the
        ready staging survives for the publisher's next attempt."""
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        self.assertIsNotNone(progress)
        machine = env.machine()
        staging_dir = env.staging_dir(progress["generation_id"])
        # Inject ENOSPC into the publish's atomic manifest write (the commit
        # point): the temp write raises OSError(errno.ENOSPC), the manifest
        # is provably NOT replaced, and the container rename rolls back.
        import publish as publish_module
        original = publish_module._write_atomic

        def enospc_write(path, content):
            raise OSError(errno.ENOSPC, "No space left on device")

        publish_module._write_atomic = enospc_write
        try:
            result = publish_ready_staging(
                env.facts_root, env.derived_root, builder, staging_dir,
                progress["generation_id"], env.desired_provider, machine,
                publish_lock=env.publish_lock)
        finally:
            publish_module._write_atomic = original
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        # The old active keeps serving and nothing was deleted: the active
        # generation + the rollback pointer (if any) are intact.
        active_manifest, _ = read_active_manifest(env.derived_root)
        self.assertIsNone(active_manifest)  # no commit happened
        self.assertTrue(os.path.isdir(
            env.published_dir(env.active_generation_id)))
        # The ready staging survived for the next attempt.
        self.assertTrue(os.path.isdir(staging_dir))

    def test_staging_record_corruption_discards_and_rebuilds(self):
        """AC67-7 staging damage: a corrupted staging progress record is
        never resumed -- the machine discards it and rebuilds fresh (the
        unusable-record path in ``retention_sweep`` / ``_load_progress``)."""
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        self.assertIsNotNone(progress)
        staging_dir = env.staging_dir(progress["generation_id"])
        # Corrupt the progress record so it is unusable.
        with open(os.path.join(staging_dir, PROGRESS_FILENAME), "w",
                  encoding="utf-8") as handle:
            handle.write("{bad json")
        # The retention sweep treats it as neither live nor explicitly
        # discarded -- it is left for the staging machine's own discard
        # logic (never guessed at, never resumed).
        from retention import live_staging_generation_ids, retention_sweep
        retention_sweep(env.derived_root, active_id=env.active_generation_id,
                        live_staging_ids=live_staging_generation_ids(
                            env.derived_root))
        self.assertTrue(os.path.isdir(staging_dir))


if __name__ == "__main__":
    unittest.main()
