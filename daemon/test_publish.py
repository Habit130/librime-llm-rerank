#!/usr/bin/env python3
"""Atomic blue-green publish tests (Habit130/squirrel#65, AC-65-v1).

Model-free, stdlib-only, sandboxed temp fact roots + derived roots and
injected deterministic representation fixtures -- never real private
history.  Maps one-to-one onto the frozen delivery contract:

  AC65-1  publish reopens the ready staging in full (checksums / event
          set / row mapping / vectors / exact-oracle probes); a corrupted
          or drifted container is never published
  AC65-2  the publish reads H1 under the short publish lock and absorbs
          (H0,H1] additions AND whole-commit retractions into the staging
          generation's own delta checkpoint
  AC65-3/4  generation + delta + active manifest are all durable before the
          atomic manifest replace; manifest + parent fsync precede the
          in-memory pointer swap (fsync-order instrumentation + the
          crash-point matrix: SCN-65-2/3)
  AC65-5  post-H1 facts during the publish are caught up by the new active
          before the next successful query -- no stale-watermark success
  AC65-6  pre-switch crashes keep the old active serving; post-switch
          crashes load the complete new generation on restart
  AC65-7  one query never mixes old/new representation / projection /
          index identity, including under concurrent queries (SCN-65-5)
  SCN-65-6  fact writes are never blocked by the publish
  SCN-65-7  a store epoch change mid-publish aborts with the old active
          intact

The delta machine runs its real worker; the staging machine is driven
cycle-by-cycle except in the publisher end-to-end tests.
"""

import json
import os
import struct
import sys
import threading
import time
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.dirname(__file__))

import publish  # noqa: E402
from delta import DeltaStateMachine  # noqa: E402
from evidence import (  # noqa: E402
    EvidenceError,
    EvidenceService,
    FixtureRepresentationProvider,
    RepresentationProvider,
    make_evidence_request,
)
from generation import (  # noqa: E402
    PROGRESS_FILENAME,
    build_generation,
)
from oracle import (  # noqa: E402
    FactReader,
    OracleError,
    OracleParams,
    OracleQuery,
    compute_evidence,
)
from publish import (  # noqa: E402
    ACTIVE_MANIFEST_FILENAME,
    GenerationPublisher,
    read_active_manifest,
)
from staging import StagingBuildMachine  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402

ACTIVE_REPR = "publish-test-active-repr-v1"
DESIRED_REPR = "publish-test-desired-repr-v1"

PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)


def make_active_provider():
    """OLD representation: query 我之前去 vs event 时界 orthogonal
    (zero evidence) so old-identity answers are zeros."""
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
    """NEW representation: query 我之前去 == event 时界 (cosine 1, strong
    evidence); new-identity answers differ visibly from old ones, so any
    identity mixing is caught."""
    return FixtureRepresentationProvider(
        DESIRED_REPR,
        {"我之前去": (0.0, 1.0, 0.0, 0.0),
         "我之后去": (0.0, 0.0, 1.0, 0.0),
         "农场清晨": (1.0, 0.0, 0.0, 0.0)},
        {"luna_pinyin|shijie|时界": (0.0, 1.0, 0.0, 0.0),
         "luna_pinyin|shijie|世界": (0.0, 0.0, 1.0, 0.0),
         "luna_pinyin|jinqi|近期": (0.0, 1.0, 0.0, 0.0)},
        default_event=(0.0, 1.0, 0.0, 0.0))


def fp32(vector):
    return tuple(struct.unpack("<f", struct.pack("<f", float(value)))[0]
                 for value in vector)


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


def oracle_on_facts(facts_root, provider, params, query, as_of=None):
    """The canonical oracle on the facts at ``as_of`` with fp32 vectors."""
    reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
    try:
        point = as_of if as_of is not None else reader.default_as_of()
        events_by_id = {
            event.event_id: event
            for event in reader.read_active_events(point)
        }

        def vector_for(event_id):
            event = events_by_id.get(event_id)
            if event is None:
                raise OracleError("no stored event %s" % event_id)
            return fp32(provider.event_vector(event))

        pinned = OracleQuery(
            schema_id=query.schema_id,
            canonical_segment_input=query.canonical_segment_input,
            candidates=list(query.candidates),
            query_vector=list(query.query_vector),
            category=query.category,
            as_of=point,
        )
        return compute_evidence(reader, params, pinned, vector_for)
    finally:
        reader.close()


def snapshot_evidence(snapshot, params, query):
    reader = snapshot.reader()
    try:
        return compute_evidence(reader, params, query, snapshot.vector_for)
    finally:
        reader.close()


def assert_same_evidence(test, left, right):
    test.assertEqual(
        [(c.index, c.s) for c in left.candidates],
        [(c.index, c.s) for c in right.candidates])
    test.assertEqual(left.query_point, right.query_point)
    test.assertEqual([k.event_id for k in left.kept],
                     [k.event_id for k in right.kept])


def probe_query():
    return OracleQuery(
        schema_id="luna_pinyin",
        canonical_segment_input="shijie",
        candidates=["世界", "时界"],
        query_vector=list(QUERY_VECTOR),
    )


def service_request(preceding_text="我之前去"):
    return make_evidence_request(
        "luna_pinyin", "word", "shijie", preceding_text, ["世界", "时界"],
        config_identity="unused-by-serve", fact_high_water=None)


class _BlockingProvider(RepresentationProvider):
    """Wraps a fixture; event_vector for listed ids waits on a gate."""

    def __init__(self, inner, gate, block_events=()):
        self._inner = inner
        self._gate = gate
        self._block_events = set(block_events)
        self.entered = threading.Event()

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        if event.event_id in self._block_events:
            self.entered.set()
            self._gate.wait(15.0)
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


class _TwoGateProvider(RepresentationProvider):
    """Wraps a fixture; per-event gates (id -> Event to wait on)."""

    def __init__(self, inner, gate_by_event):
        self._inner = inner
        self._gate_by_event = dict(gate_by_event)
        self.entered = threading.Event()

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        gate = self._gate_by_event.get(event.event_id)
        if gate is not None:
            self.entered.set()
            gate.wait(15.0)
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


class _FailingProvider(RepresentationProvider):
    """Wraps a fixture; event_vector for one id raises on demand."""

    def __init__(self, inner, fail_event=None, fail_exc=None):
        self._inner = inner
        self._fail_event = fail_event
        self._fail_exc = fail_exc or EvidenceError(
            "representation_fault", "injected failure")

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        if event.event_id == self._fail_event:
            raise self._fail_exc
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


def _flip_byte(path, offset=0):
    with open(path, "r+b") as handle:
        handle.seek(offset)
        byte = handle.read(1)
        if not byte:
            byte = b"\x00"
        handle.seek(-1, 1)
        handle.write(bytes([byte[0] ^ 0xFF]))


class PublishEnv:
    """One sandboxed facts root + derived root with an active generation."""

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

    def machine(self, provider=None, generation_id=None, **kwargs):
        defaults = {"poll_interval": 0.01, "catch_up_deadline": 5.0}
        defaults.update(kwargs)
        return DeltaStateMachine(
            self.facts_root, self.derived_root,
            provider or self.active_provider,
            generation_id or self.active_generation_id,
            **defaults)

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

    def checkpoint_path(self, generation_id):
        return os.path.join(self.derived_root, "delta", generation_id,
                            "delta.sqlite3")

    def add_publish_window_facts(self):
        """(H0,H1] additions: two in-window events, one whole-commit
        retraction of them, one surviving event, one base-commit
        retraction.  Returns the final facts watermark H1."""
        self.facts.add_event("w1", commit_id="commit-window",
                             segment_input="shijie", selection="时界",
                             preceding_text="我之前去",
                             competition=("世界", "时界"))
        self.facts.add_event("w2", commit_id="commit-window",
                             segment_input="shijie", selection="世界",
                             preceding_text="我之前去",
                             competition=("世界", "时界"))
        self.facts.add_retraction("retract-window", "commit-window",
                                  (1000000, 7))
        self.facts.add_event("w3", segment_input="shijie", selection="时界",
                             preceding_text="我之前去",
                             competition=("世界", "时界"))
        self.facts.add_retraction("retract-e2", "commit-e2", (1000000, 9))
        return (1000000, 9)

    def cleanup(self):
        self.facts.close()


class PublishBase(unittest.TestCase):
    def setUp(self):
        self.env = None
        self.machines = []

    def tearDown(self):
        for machine in self.machines:
            try:
                machine.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        if self.env is not None:
            self.env.cleanup()

    def make_env(self, **kwargs):
        self.env = PublishEnv(**kwargs)
        return self.env

    def machine(self, *args, **kwargs):
        machine = self.env.machine(*args, **kwargs)
        self.machines.append(machine)
        return machine


# ---------------------------------------------------------------------------
# AC65-1: publish-time reopen verification
# ---------------------------------------------------------------------------

class PublishPreconditionTest(PublishBase):
    """A ready staging that fails the publish reopen is never published."""

    def test_corrupted_vectors_are_never_published(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        self.assertIsNotNone(progress, "staging did not reach ready")
        staging_dir = env.staging_dir(progress["generation_id"])
        _flip_byte(os.path.join(staging_dir, "vectors.fp32"))
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder, staging_dir,
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertIn("reopen verification failed", result["error"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        # The staging is marked discarded (never published, rebuilt) and
        # the old generation keeps serving.
        with open(os.path.join(staging_dir, PROGRESS_FILENAME),
                  encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(record["status"], "discarded")
        self.assertIn("reopen verification failed", record["reason"])
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         env.active_generation_id)

    def test_corrupted_manifest_is_never_published(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        staging_dir = env.staging_dir(progress["generation_id"])
        _flip_byte(os.path.join(staging_dir, "manifest.json"), offset=20)
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder, staging_dir,
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        with open(os.path.join(staging_dir, PROGRESS_FILENAME),
                  encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(record["status"], "discarded")

    def test_tampered_progress_record_fails_the_resume_gate(self):
        from generation import _canonical_json, _write_atomic
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        staging_dir = env.staging_dir(progress["generation_id"])
        record = dict(progress)
        record["rows_fingerprint"] = "f" * 64
        _write_atomic(os.path.join(staging_dir, PROGRESS_FILENAME),
                      _canonical_json(record).encode("utf-8"))
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder, staging_dir,
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertIn("resume gate", result["error"])
        self.assertFalse(os.path.isfile(env.manifest_path()))

    def test_wrong_generation_id_is_never_published(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            "shadow-gen-v1:not-the-record", env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertFalse(os.path.isfile(env.manifest_path()))


# ---------------------------------------------------------------------------
# AC65-2: H1 under the publish lock; (H0,H1] replay into the staging's own
# delta checkpoint
# ---------------------------------------------------------------------------

class PublishDeltaTest(PublishBase):

    def test_window_additions_and_whole_commit_retractions_are_replayed(
            self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        self.assertIsNotNone(progress)
        h0 = tuple(progress["identity"]["source_hlc"])
        h1 = env.add_publish_window_facts()
        self.assertEqual(h0, (1000000, 4))
        self.assertEqual(h1, (1000000, 9))
        machine = self.machine()
        staging_dir = env.staging_dir(progress["generation_id"])
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder, staging_dir,
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        # The staging generation's own delta checkpoint: rows + tombstones
        # + consumed watermark, bound to the staging generation.
        checkpoint_path = env.checkpoint_path(progress["generation_id"])
        self.assertTrue(os.path.isfile(checkpoint_path))
        import sqlite3
        conn = sqlite3.connect(checkpoint_path)
        try:
            meta = dict(conn.execute(
                "SELECT key, value FROM meta").fetchall())
            rows = conn.execute("SELECT event_id, commit_id FROM"
                                " delta_events").fetchall()
            tombstones = conn.execute("SELECT commit_id FROM"
                                      " retractions").fetchall()
        finally:
            conn.close()
        self.assertEqual(meta["base_generation_id"],
                         progress["generation_id"])
        self.assertEqual(meta["store_epoch"],
                         progress["identity"]["store_epoch"])
        self.assertEqual(
            (int(meta["consumed_hlc_physical_ms"]),
             int(meta["consumed_hlc_logical"])), h1)
        # w1/w2 were retracted inside the window (never embedded); w3
        # survived; the e2 base-commit retraction is a tombstone.
        self.assertEqual([row[0] for row in rows], ["w3"])
        self.assertEqual(sorted(row[0] for row in tombstones),
                         ["commit-e2", "commit-window"])
        # The active manifest was atomically replaced.
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(manifest["generation_id"],
                         progress["generation_id"])
        self.assertEqual(manifest["delta_checkpoint"],
                         "delta/%s/delta.sqlite3"
                         % progress["generation_id"])
        self.assertEqual(manifest["representation_id"], DESIRED_REPR)
        self.assertEqual(manifest["store_epoch"],
                         progress["identity"]["store_epoch"])
        self.assertEqual(manifest["source_hlc"],
                         progress["identity"]["source_hlc"])
        # The in-memory pointer was swapped: the served snapshot is the new
        # identity at H1.
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])
        self.assertEqual(snapshot.consumed, h1)
        self.assertEqual(snapshot.representation_id, DESIRED_REPR)
        ids = set(snapshot.event_ids())
        self.assertIn("w3", ids)
        self.assertNotIn("w1", ids)
        self.assertNotIn("w2", ids)
        self.assertNotIn("e2", ids)
        self.assertIn("e1", ids)
        # Evidence is served from the new identity: 我之前去 now matches
        # 时界 (cosine 1), so s > 0 for the 时界 candidate.
        query = replace(probe_query(), query_vector=list(
            make_desired_provider().query_vector("我之前去")))
        served = snapshot_evidence(snapshot, PARAMS, query)
        expected = oracle_on_facts(
            env.facts_root, make_desired_provider(), PARAMS, query,
            as_of=h1)
        assert_same_evidence(self, served, expected)
        s_by_index = {c.index: c.s for c in served.candidates}
        self.assertGreater(s_by_index[1], 0.0)

    def test_empty_window_publish_serves_the_new_identity_immediately(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])
        self.assertEqual(snapshot.consumed,
                         tuple(progress["identity"]["source_hlc"]))


# ---------------------------------------------------------------------------
# AC65-3/4: fsync order, atomic manifest replace, crash-point matrix
# ---------------------------------------------------------------------------

class FsyncOrderTest(PublishBase):

    def test_durability_order_generation_delta_manifest_then_switch(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        env.add_publish_window_facts()
        machine = self.machine()
        trace = []
        original_fsync = publish._fsync_directory
        original_write_atomic = publish._write_atomic

        def tracing_fsync(path):
            trace.append(("fsync", path))
            original_fsync(path)

        def tracing_write_atomic(path, content):
            # At the atomic manifest replace both the container and the
            # staging delta must already be durable.
            trace.append(("write_atomic", path))
            assert os.path.isdir(env.published_dir(progress["generation_id"]))
            assert os.path.isfile(
                env.checkpoint_path(progress["generation_id"]))
            original_write_atomic(path, content)

        original_switch = machine.publish_switch

        def tracing_switch(*args, **kwargs):
            trace.append(("switch", args[0]))
            return original_switch(*args, **kwargs)

        publish._fsync_directory = tracing_fsync
        publish._write_atomic = tracing_write_atomic
        machine.publish_switch = tracing_switch
        try:
            result = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder,
                env.staging_dir(progress["generation_id"]),
                progress["generation_id"], env.desired_provider, machine,
                publish_lock=env.publish_lock)
        finally:
            publish._fsync_directory = original_fsync
            publish._write_atomic = original_write_atomic
            del machine.publish_switch
        self.assertTrue(result["ok"], result)
        kinds = [item[0] for item in trace]
        manifest_index = kinds.index("write_atomic")
        switch_index = kinds.index("switch")
        self.assertGreater(manifest_index, 0)
        self.assertGreater(switch_index, manifest_index)
        # The generation container rename fsyncs happened before the
        # manifest replace.
        fsync_paths = [item[1] for item in trace[:manifest_index]
                       if item[0] == "fsync"]
        self.assertTrue(any("generations" in path for path in fsync_paths))
        self.assertTrue(any("staging" in path for path in fsync_paths))
        # The active manifest is a single valid JSON document, atomically
        # replaced (no temp leftovers).
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(manifest["generation_id"],
                         progress["generation_id"])
        leftovers = [name for name in os.listdir(env.derived_root)
                     if name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])


class CrashPointTest(PublishBase):
    """The crash matrix: pre-switch crashes keep the old active, post-
    switch crashes load the complete new generation on restart.

    Crash points are simulated by raising at the exact seam inside the
    publish transaction; the durable state assertions are identical to what
    a real process crash at that point leaves on disk.
    """

    def _ready_env(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        env.add_publish_window_facts()
        return env, builder, progress

    def test_crash_before_the_delta_build_keeps_the_old_active(self):
        env, builder, progress = self._ready_env()
        machine = self.machine()
        original = publish._build_staging_delta

        def crash(*args, **kwargs):
            raise publish.PublishError("injected crash before delta build")

        publish._build_staging_delta = crash
        try:
            result = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder,
                env.staging_dir(progress["generation_id"]),
                progress["generation_id"], env.desired_provider, machine,
                publish_lock=env.publish_lock)
        finally:
            publish._build_staging_delta = original
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         env.active_generation_id)
        # The staging is untouched and still ready.
        self.assertTrue(os.path.isdir(
            env.staging_dir(progress["generation_id"])))
        with open(os.path.join(env.staging_dir(progress["generation_id"]),
                               PROGRESS_FILENAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["status"], "ready")

    def test_deterministic_delta_fault_blocks_and_names_the_event(self):
        env, builder, progress = self._ready_env()
        machine = self.machine()
        failing = _FailingProvider(env.desired_provider, fail_event="w3")
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], failing, machine,
            publish_lock=env.publish_lock)
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertIn("w3", result["error"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        with open(os.path.join(env.staging_dir(progress["generation_id"]),
                               PROGRESS_FILENAME), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["blocked_events"], ["w3"])
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         env.active_generation_id)

    def test_crash_after_the_delta_build_before_the_rename(self):
        env, builder, progress = self._ready_env()
        machine = self.machine()
        original = publish._park_progress

        def crash(*args, **kwargs):
            raise OSError("injected crash before the container rename")

        publish._park_progress = crash
        try:
            result = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder,
                env.staging_dir(progress["generation_id"]),
                progress["generation_id"], env.desired_provider, machine,
                publish_lock=env.publish_lock)
        finally:
            publish._park_progress = original
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        # The staging container stayed put; the orphaned staging delta is
        # harmless derived state that a later publish of the same id
        # supersedes.
        self.assertTrue(os.path.isdir(
            env.staging_dir(progress["generation_id"])))
        self.assertTrue(os.path.isfile(
            env.checkpoint_path(progress["generation_id"])))
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         env.active_generation_id)

    def test_crash_after_the_rename_before_the_manifest_is_rolled_back(
            self):
        env, builder, progress = self._ready_env()
        machine = self.machine()
        original = publish.write_active_manifest

        def crash(*args, **kwargs):
            raise OSError("injected crash before the manifest replace")

        publish.write_active_manifest = crash
        try:
            result = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder,
                env.staging_dir(progress["generation_id"]),
                progress["generation_id"], env.desired_provider, machine,
                publish_lock=env.publish_lock)
        finally:
            publish.write_active_manifest = original
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        # The container rename was rolled back: the ready staging survives
        # intact for the publisher's next attempt.
        self.assertTrue(os.path.isdir(
            env.staging_dir(progress["generation_id"])))
        self.assertFalse(os.path.isdir(
            env.published_dir(progress["generation_id"])))
        with open(os.path.join(env.staging_dir(progress["generation_id"]),
                               PROGRESS_FILENAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["status"], "ready")
        # A retry (no crash) publishes fully.
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])

    def test_crash_after_the_manifest_before_the_switch_loads_new_on_restart(
            self):
        env, builder, progress = self._ready_env()
        machine = self.machine()

        def crash_switch(*args, **kwargs):
            raise RuntimeError("injected crash before the pointer swap")

        machine.publish_switch = crash_switch
        try:
            result = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder,
                env.staging_dir(progress["generation_id"]),
                progress["generation_id"], env.desired_provider, machine,
                publish_lock=env.publish_lock)
        finally:
            del machine.publish_switch
        self.assertFalse(result["ok"])
        self.assertTrue(result["committed"])
        # The manifest was durably replaced (the commit point).
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(manifest["generation_id"],
                         progress["generation_id"])
        # The live process still serves the old snapshot (the swap never
        # happened); a restart loads the complete new generation.
        self.assertEqual(machine.snapshot().base_generation_id,
                         env.active_generation_id)
        self.assertFalse(os.path.isdir(
            env.staging_dir(progress["generation_id"])))
        self.assertTrue(os.path.isdir(
            env.published_dir(progress["generation_id"])))
        for name in ("manifest.json", "metadata.json", "vectors.fp32"):
            self.assertTrue(os.path.isfile(os.path.join(
                env.published_dir(progress["generation_id"]), name)))
        machine.close()
        self.machines.clear()
        restarted = self.machine(
            provider=env.desired_provider,
            generation_id=manifest["generation_id"])
        snapshot = restarted.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])
        self.assertEqual(snapshot.representation_id, DESIRED_REPR)
        self.assertEqual(snapshot.consumed, (1000000, 9))

    def test_old_generation_and_its_checkpoint_are_retained(self):
        """#66 owns retention: publish never deletes the retired active."""
        env, builder, progress = self._ready_env()
        machine = self.machine()
        machine.ensure_caught_up()
        old_checkpoint = machine.delta_checkpoint_path()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        self.assertTrue(os.path.isdir(env.published_dir(
            env.active_generation_id)))
        self.assertTrue(os.path.isfile(old_checkpoint))


# ---------------------------------------------------------------------------
# AC65-5 / SCN-65-4/6: facts written during the publish window
# ---------------------------------------------------------------------------

class PublishWindowTest(PublishBase):

    def test_post_h1_facts_are_caught_up_before_the_next_success(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        env.add_publish_window_facts()  # facts watermark (1000000, 9)
        publish_gate = threading.Event()
        catchup_gate = threading.Event()
        blocked = _TwoGateProvider(
            env.desired_provider,
            {"w3": publish_gate, "w4": catchup_gate})
        machine = self.machine()
        staging_dir = env.staging_dir(progress["generation_id"])
        result_holder = {}

        def run_publish():
            result_holder["result"] = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder, staging_dir,
                progress["generation_id"], blocked, machine,
                publish_lock=env.publish_lock)

        thread = threading.Thread(target=run_publish)
        thread.start()
        self.assertTrue(blocked.entered.wait(10.0),
                        "publish never reached the delta embed")
        # The publish is inside its delta embed (w3 blocked).  Fact writes
        # are never blocked by the publish (SCN-65-6): commit post-H1
        # facts right now (explicit hlc beyond H1=(1000000,9) -- the
        # fixture's auto-advance would reuse an in-window hlc).
        env.facts.add_event("w4", hlc=(1000000, 10),
                            segment_input="shijie", selection="时界",
                            preceding_text="我之前去",
                            competition=("世界", "时界"))
        publish_gate.set()
        thread.join(15.0)
        self.assertFalse(thread.is_alive(), "publish did not finish")
        result = result_holder["result"]
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["committed"], True)
        # The publish committed at H1 = (1000000, 9); w4 is post-H1.  The
        # new active serves the snapshot at H1 and the worker is now busy
        # catching up w4 -- a query in this window must fail with
        # not_caught_up, never succeed on a stale watermark (SCN-65-4).
        self.assertEqual(machine.snapshot().consumed, (1000000, 9))
        self.assertNotIn("w4", set(machine.snapshot().event_ids()))
        with self.assertRaises(EvidenceError) as caught:
            machine.ensure_caught_up(deadline=time.monotonic() + 0.05)
        self.assertEqual(caught.exception.code, "not_caught_up")
        catchup_gate.set()
        snapshot = machine.ensure_caught_up()
        self.assertIn("w4", set(snapshot.event_ids()))
        self.assertEqual(snapshot.consumed, (1000000, 10))
        # The served evidence includes the caught-up event.
        query = replace(probe_query(), query_vector=list(
            make_desired_provider().query_vector("我之前去")))
        expected = oracle_on_facts(env.facts_root, make_desired_provider(),
                                   PARAMS, query)
        served = snapshot_evidence(snapshot, PARAMS, query)
        assert_same_evidence(self, served, expected)

    def test_publish_holds_the_lock_while_facts_keep_writing(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        env.add_publish_window_facts()
        gate = threading.Event()
        blocked = _BlockingProvider(env.desired_provider, gate,
                                    block_events=("w3",))
        machine = self.machine()
        staging_dir = env.staging_dir(progress["generation_id"])
        lock_seen = []

        def run_publish():
            result = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder, staging_dir,
                progress["generation_id"], blocked, machine,
                publish_lock=env.publish_lock)
            lock_seen.append(result)

        thread = threading.Thread(target=run_publish)
        thread.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not lock_seen:
            # While the publish is inside its transaction the publish lock
            # is held (the staging worker serializes on it).
            if env.publish_lock.locked():
                lock_seen.append("held")
                break
            time.sleep(0.005)
        self.assertEqual(lock_seen[-1], "held")
        gate.set()
        thread.join(15.0)
        self.assertFalse(thread.is_alive(), "publish did not finish")
        self.assertTrue(lock_seen[-1]["ok"], lock_seen)


# ---------------------------------------------------------------------------
# AC65-7 / SCN-65-5: single-query identity atomicity
# ---------------------------------------------------------------------------

class IdentityAtomicityTest(PublishBase):

    def _evidence_of(self, service, request):
        response = service.serve(request)
        return [(entry["index"], entry["s"]) for entry in response["evidence"]]

    def test_one_query_never_mixes_identities_across_the_switch(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = self.machine(catch_up_deadline=0.5)
        service = EvidenceService(env.facts_root, PARAMS,
                                  env.active_provider, 1.0, machine=machine)
        self.assertEqual(service.config_identity().split(":repr=")[1]
                         .split(":")[0], ACTIVE_REPR)
        request = service_request()
        # Phase 1 (old identity): the delta worker is parked so the old
        # snapshot is frozen and every query deterministically serves the
        # old representation.
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        expected_old = self._evidence_of(service, request)
        self.assertEqual(expected_old, [(0, 0.0), (1, 0.0)])
        responses = []
        stop = threading.Event()

        def query_loop():
            while not stop.is_set():
                try:
                    responses.append(self._evidence_of(service, request))
                except Exception:  # noqa: BLE001 - transient gate faults
                    pass  # transient gate faults are fine during the window
                time.sleep(0.001)

        loop = threading.Thread(target=query_loop, daemon=True)
        loop.start()
        time.sleep(0.05)
        # Publish with a bounded switch deadline: the worker is parked, so
        # the handshake times out -- the manifest is committed and the
        # committed-but-unswitched state is retried later.
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock, switch_deadline=0.1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["committed"])
        manifest, _reason = read_active_manifest(env.derived_root)
        self.assertEqual(manifest["generation_id"],
                         progress["generation_id"])
        # The live process still serves the old identity (committed but not
        # switched): every concurrent response equals the old identity.
        time.sleep(0.05)
        still_old = set(map(tuple, responses))
        self.assertEqual(still_old, {tuple(expected_old)})
        # The service's config identity still matches what it serves.
        self.assertEqual(service.config_identity().split(":repr=")[1]
                         .split(":")[0], ACTIVE_REPR)
        # The expected post-switch identity: the new-representation oracle
        # at the staging's H0 (no post-H0 facts in this scenario).
        query = replace(probe_query(), query_vector=list(
            make_desired_provider().query_vector("我之前去")))
        expected_new = oracle_on_facts(
            env.facts_root, make_desired_provider(), PARAMS, query,
            as_of=tuple(progress["identity"]["source_hlc"]))
        expected_new_tuple = tuple(
            (c.index, c.s) for c in expected_new.candidates)
        self.assertNotEqual(expected_new_tuple, tuple(expected_old))
        # Resume the worker: the queued switch completes and the queries
        # flip to the new identity -- each response is exactly the new
        # identity, never a mix.
        responses.clear()
        machine.start()
        deadline = time.monotonic() + 15.0
        try:
            while time.monotonic() < deadline:
                if expected_new_tuple in set(map(tuple, responses)):
                    break
                time.sleep(0.01)
        finally:
            stop.set()
            loop.join(5.0)
        all_responses = set(map(tuple, responses))
        self.assertIn(expected_new_tuple, all_responses)
        # Every recorded response is exactly one complete identity.
        self.assertLessEqual(all_responses,
                             {tuple(expected_old), expected_new_tuple})
        self.assertEqual(service.config_identity().split(":repr=")[1]
                         .split(":")[0], DESIRED_REPR)
        final = self._evidence_of(service, request)
        self.assertEqual(tuple(final), expected_new_tuple)
        # The final identity equals the new-representation oracle exactly.
        self.assertEqual(
            tuple(final),
            tuple((c.index, c.s) for c in expected_new.candidates))

    def test_publish_switch_clears_a_stale_catch_up_block(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        env.add_publish_window_facts()
        # The OLD identity's catch-up is deterministically blocked on w3
        # (w1/w2 are retracted inside the same batch and never embedded).
        failing = _FailingProvider(env.active_provider, fail_event="w3")
        machine = self.machine(provider=failing, catch_up_deadline=0.5)
        with self.assertRaises(EvidenceError) as caught:
            machine.ensure_caught_up()
        self.assertEqual(caught.exception.code, "representation_fault")
        # The publish (a config change) switches the identity and clears
        # the block; the new active serves immediately at H1.
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])
        self.assertEqual(snapshot.consumed, (1000000, 9))

    def test_switch_aborts_when_the_epoch_changed(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = self.machine()
        machine.ensure_caught_up()
        old_snapshot = machine.snapshot()
        # Park the worker so the epoch change cannot trigger a rebuild
        # before the switch is queued.
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        env.facts.conn.commit()
        result_holder = {}

        def run_switch():
            result_holder["result"] = machine.publish_switch(
                progress["generation_id"],
                env.checkpoint_path(progress["generation_id"]),
                env.desired_provider, "e1",
                deadline=time.monotonic() + 10.0)

        thread = threading.Thread(target=run_switch)
        thread.start()
        time.sleep(0.1)  # the switch is queued (the worker is parked)
        machine.start()  # the worker processes it and aborts on the epoch
        thread.join(10.0)
        self.assertFalse(thread.is_alive(), "switch handshake did not end")
        ok, error = result_holder["result"]
        self.assertFalse(ok)
        self.assertIn("epoch changed", error)
        self.assertIs(machine.snapshot(), old_snapshot)
        self.assertEqual(machine.snapshot().base_generation_id,
                         env.active_generation_id)


# ---------------------------------------------------------------------------
# SCN-65-7: epoch change mid-publish
# ---------------------------------------------------------------------------

class EpochAbortTest(PublishBase):

    def test_epoch_change_mid_publish_aborts_with_the_old_active_intact(
            self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        env.add_publish_window_facts()
        gate = threading.Event()
        blocked = _BlockingProvider(env.desired_provider, gate,
                                    block_events=("w3",))
        machine = self.machine()
        staging_dir = env.staging_dir(progress["generation_id"])
        result_holder = {}

        def run_publish():
            result_holder["result"] = publish.publish_ready_staging(
                env.facts_root, env.derived_root, builder, staging_dir,
                progress["generation_id"], blocked, machine,
                publish_lock=env.publish_lock)

        thread = threading.Thread(target=run_publish)
        thread.start()
        # The publish is inside its delta embed (w3's vector embedding is
        # in flight): the store is replaced with a new epoch (restore/clear
        # semantics).
        self.assertTrue(blocked.entered.wait(10.0),
                        "publish never reached the delta embed")
        env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        env.facts.conn.execute(
            "UPDATE meta SET value = '2000000'"
            " WHERE key = 'hlc_physical_ms';")
        env.facts.conn.execute(
            "UPDATE meta SET value = '0' WHERE key = 'hlc_logical';")
        env.facts.conn.commit()
        gate.set()
        thread.join(15.0)
        self.assertFalse(thread.is_alive(), "publish did not finish")
        result = result_holder["result"]
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertIn("epoch changed", result["error"])
        # The old active is untouched: no manifest, no published container,
        # the staging container intact in staging/.
        self.assertFalse(os.path.isfile(env.manifest_path()))
        self.assertFalse(os.path.isdir(
            env.published_dir(progress["generation_id"])))
        self.assertTrue(os.path.isdir(staging_dir))
        # The old generation files remain on disk.
        self.assertTrue(os.path.isdir(env.published_dir(
            env.active_generation_id)))

    def test_publish_preconditions_reject_a_stale_epoch_staging(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = self.machine()
        env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        env.facts.conn.commit()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertFalse(result["ok"])
        self.assertFalse(result["committed"])
        self.assertFalse(os.path.isfile(env.manifest_path()))
        # The staging is discarded: an epoch-mismatched build must never be
        # published; the machine's next cycle would rebuild for e2.
        with open(os.path.join(env.staging_dir(progress["generation_id"]),
                               PROGRESS_FILENAME), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["status"], "discarded")


# ---------------------------------------------------------------------------
# Restart semantics and the active-manifest config seam
# ---------------------------------------------------------------------------

class RestartTest(PublishBase):

    def test_restart_loads_the_complete_new_generation_from_the_manifest(
            self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        h1 = env.add_publish_window_facts()
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        machine.close()
        self.machines.clear()
        # A fresh machine resolves the active identity from the manifest.
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        self.assertEqual(manifest["generation_id"],
                         progress["generation_id"])
        restarted = self.machine(
            provider=env.desired_provider,
            generation_id=manifest["generation_id"])
        snapshot = restarted.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])
        self.assertEqual(snapshot.representation_id, DESIRED_REPR)
        self.assertEqual(snapshot.consumed, h1)
        self.assertEqual(restarted.delta_checkpoint_path(),
                         env.checkpoint_path(progress["generation_id"]))
        # Post-restart catch-up works on the new checkpoint (explicit hlc
        # beyond H1; the fixture's auto-advance would reuse an in-window
        # one).
        env.facts.add_event("r1", hlc=(1000000, 10),
                            segment_input="shijie", selection="时界",
                            preceding_text="我之前去",
                            competition=("世界", "时界"))
        snapshot = restarted.ensure_caught_up()
        self.assertIn("r1", set(snapshot.event_ids()))

    def test_config_seam_resolves_the_manifest_when_present(self):
        from delta import build_delta_machine_from_config
        from staging import build_staging_machine_from_config
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        machine = self.machine()
        result = publish.publish_ready_staging(
            env.facts_root, env.derived_root, builder,
            env.staging_dir(progress["generation_id"]),
            progress["generation_id"], env.desired_provider, machine,
            publish_lock=env.publish_lock)
        self.assertTrue(result["ok"], result)
        machine.close()
        self.machines.clear()
        config = {
            "derived_root": env.derived_root,
            "generation_id": env.active_generation_id,
            "representation_id": ACTIVE_REPR,
            "desired_representation_id": DESIRED_REPR,
        }
        # The server wiring resolves the active identity from the manifest
        # (not the stale config) before building the machines; mirror it.
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(reason)
        machine2 = build_delta_machine_from_config(
            env.facts_root, config,
            active_generation_id=manifest["generation_id"],
            active_representation_id=manifest["representation_id"])
        self.machines.append(machine2)
        snapshot = machine2.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         progress["generation_id"])
        self.assertEqual(snapshot.representation_id, DESIRED_REPR)
        staging2 = build_staging_machine_from_config(
            env.facts_root, config,
            active_generation_id=manifest["generation_id"],
            active_representation_id=manifest["representation_id"])
        status = staging2.status()
        self.assertEqual(status["active_generation_id"],
                         progress["generation_id"])
        self.assertEqual(status["active_representation_id"], DESIRED_REPR)
        staging2.close()

    def test_config_seam_without_a_manifest_uses_the_config_active(self):
        from delta import build_delta_machine_from_config
        env = self.make_env()
        config = {
            "derived_root": env.derived_root,
            "generation_id": env.active_generation_id,
            "representation_id": ACTIVE_REPR,
        }
        machine = build_delta_machine_from_config(env.facts_root, config)
        self.machines.append(machine)
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         env.active_generation_id)
        self.assertEqual(snapshot.representation_id, ACTIVE_REPR)

    def test_invalid_manifest_falls_back_to_the_config_active(self):
        from delta import build_delta_machine_from_config
        env = self.make_env()
        with open(env.manifest_path(), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        manifest, reason = read_active_manifest(env.derived_root)
        self.assertIsNone(manifest)
        self.assertIn("unreadable", reason)
        config = {
            "derived_root": env.derived_root,
            "generation_id": env.active_generation_id,
            "representation_id": ACTIVE_REPR,
        }
        machine = build_delta_machine_from_config(env.facts_root, config)
        self.machines.append(machine)
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.base_generation_id,
                         env.active_generation_id)


# ---------------------------------------------------------------------------
# GenerationPublisher worker
# ---------------------------------------------------------------------------

class PublisherTest(PublishBase):

    def _ready_staging_env(self):
        env = self.make_env()
        builder = env.staging()
        progress = env.run_to_ready(builder)
        builder.close()
        env.add_publish_window_facts()
        return env, progress

    def test_publisher_publishes_a_ready_staging_end_to_end(self):
        env, progress = self._ready_staging_env()
        builder = env.staging(start_worker=True, poll_interval=0.02)
        machine = self.machine()
        publisher = GenerationPublisher(
            env.facts_root, env.derived_root, builder, machine,
            publish_lock=env.publish_lock, poll_interval=0.02)
        try:
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                if publisher.status()["switched_generation_id"] \
                        == progress["generation_id"]:
                    break
                time.sleep(0.02)
            status = publisher.status()
            self.assertEqual(status["switched_generation_id"],
                             progress["generation_id"], status)
            self.assertIsNone(status["last_error"])
            snapshot = machine.ensure_caught_up()
            self.assertEqual(snapshot.base_generation_id,
                             progress["generation_id"])
            # The staging record is gone: nothing to re-publish.
            self.assertFalse(os.path.isdir(env.staging_dir(
                progress["generation_id"])))
        finally:
            publisher.close()
            builder.close()

    def test_publisher_retries_a_committed_but_unswitched_publish(self):
        env, progress = self._ready_staging_env()
        # A fresh staging machine with a real worker picks the ready record
        # up; the publisher drives the rest.
        builder = env.staging(start_worker=True, poll_interval=0.02)
        machine = self.machine()
        # Park the delta worker: the publisher's publish commits the
        # manifest but its switch handshake times out.
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        publisher = GenerationPublisher(
            env.facts_root, env.derived_root, builder, machine,
            publish_lock=env.publish_lock, poll_interval=0.02,
            switch_deadline=0.1)
        try:
            # The publisher publishes and commits; the switch stays pending
            # while the worker is parked.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                status = publisher.status()
                if status["committed_generation_id"] \
                        == progress["generation_id"]:
                    break
                time.sleep(0.02)
            status = publisher.status()
            self.assertEqual(status["committed_generation_id"],
                             progress["generation_id"], status)
            self.assertIsNone(status["switched_generation_id"])
            self.assertIn("switch", status["last_error"] or "")
            # Once the worker resumes, the publisher retries the handshake
            # on its next poll and the switch completes.
            machine.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if publisher.status()["switched_generation_id"] \
                        == progress["generation_id"]:
                    break
                time.sleep(0.02)
            status = publisher.status()
            self.assertEqual(status["switched_generation_id"],
                             progress["generation_id"], status)
            snapshot = machine.ensure_caught_up()
            self.assertEqual(snapshot.base_generation_id,
                             progress["generation_id"])
        finally:
            publisher.close()
            builder.close()

    def test_publisher_idles_without_a_ready_staging(self):
        # desired == active: the staging machine never builds, so the
        # publisher has nothing to publish.
        env = self.make_env()
        builder = env.staging(provider=env.active_provider,
                              start_worker=True, poll_interval=0.02)
        machine = self.machine()
        publisher = GenerationPublisher(
            env.facts_root, env.derived_root, builder, machine,
            publish_lock=env.publish_lock, poll_interval=0.02)
        try:
            time.sleep(0.2)
            status = publisher.status()
            self.assertIsNone(status["committed_generation_id"])
            self.assertIsNone(status["switched_generation_id"])
            self.assertFalse(os.path.isfile(env.manifest_path()))
        finally:
            publisher.close()
            builder.close()


if __name__ == "__main__":
    unittest.main()
