#!/usr/bin/env python3
"""Persistent exact delta state machine tests (Habit130/squirrel#63, AC-63-v1).

Model-free, stdlib-only, sandboxed temp fact roots + derived roots and
injected deterministic representation fixtures -- never real private history.
The suite is adversarial by design and maps one-to-one onto the frozen
delivery contract:

  AC63-1  the query gate re-reads store_epoch + max change HLC and wakes the
          worker; notifications are only a wake optimization
  AC63-2  the unique worker processes additions and whole-commit retractions
          in fact-transaction order (SCN-63-8)
  AC63-3  vectors, tombstones, active set, age sequence and consumed HLC
          advance in one durable delta transaction
  AC63-4  a new read-only snapshot is published only after the transaction
          commits (incl. the crash point between commit and publish)
  AC63-5  a new event is visible to the next successful query; a retraction
          exits both evidence and the age clock in the same snapshot
  AC63-6  a catch-up that cannot finish in time fails explicitly
          (not_caught_up), never a stale-watermark success (SCN-63-3/7)
  AC63-7  restart, lost notifications and checkpoint corruption replay to
          evidence-identical results (SCN-63-4/5/6)

Equivalence is evidence-level (AC63-7): the served per-candidate ``s`` array
and query point equal the canonical oracle computed on the same facts at the
same watermark with the same (fp32-quantized) vectors.  File-level identity
is never promised for the checkpoint.
"""

import json
import os
import sqlite3
import struct
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import delta as delta_module  # noqa: E402
from delta import (  # noqa: E402
    DELTA_FILENAME,
    DELTA_SCHEMA_VERSION,
    DeltaError,
    DeltaRejected,
    DeltaStateMachine,
    build_delta_machine_from_config,
    open_delta_checkpoint,
    read_facts_identity,
)
from evidence import (  # noqa: E402
    EvidenceError,
    EvidenceService,
    FixtureRepresentationProvider,
    RepresentationProvider,
    build_evidence_service_from_config,
)
from generation import build_generation  # noqa: E402
from oracle import (  # noqa: E402
    FactReader,
    OracleParams,
    OracleQuery,
    compute_evidence,
)
from test_oracle import FactsFixture  # noqa: E402

REPR_ID = "delta-test-repr-v1"
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)

PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)

SECRET_PRECEDING = "机密上文内容绝对不许进 delta"


def make_provider(representation_id=REPR_ID):
    return FixtureRepresentationProvider(
        representation_id,
        {"我之前去": QUERY_VECTOR,
         "我之后去": (0.8, 0.6, 0.0, 0.0),
         "农场清晨": (0.2, 0.979796, 0.0, 0.0)},
        {"luna_pinyin|shijie|时界": (0.9, 0.43589, 0.0, 0.0),
         "luna_pinyin|shijie|世界": (0.3, 0.953939, 0.0, 0.0),
         "luna_pinyin|gongji|攻击": (0.2, 0.979796, 0.0, 0.0),
         "luna_pinyin|gongji|公鸡": (0.6, 0.8, 0.0, 0.0),
         "luna_pinyin|jinqi|近期": (0.7, 0.714143, 0.0, 0.0)},
        default_event=(0.0, 1.0, 0.0, 0.0))


def fp32(vector):
    """Quantize to the delta's FP32 row semantics (exact round trip)."""
    return tuple(struct.unpack("<f", struct.pack("<f", float(value)))[0]
                 for value in vector)


def base_facts():
    """A base fact store with three same-key events and one other-key event."""
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
    """The canonical oracle on the facts at ``as_of`` with fp32 vectors.

    Quantizes every event vector exactly like the delta BLOB does, so the
    snapshot-served evidence is bit-identical (the equivalence standard of
    AC63-7).  ``query`` must carry the base fields; as_of is pinned here.
    """
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


def snapshot_evidence(snapshot, provider, params, query):
    """The canonical oracle over one published snapshot (fp32 vectors)."""
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


class _CountingProvider(RepresentationProvider):
    """Wraps a fixture and records event_vector calls.

    Guards every call with a lock and tracks the maximum concurrent depth, so
    tests can prove the worker embeds strictly sequentially (SCN-63-8).
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls = []
        self._depth = 0
        self._max_depth = 0
        self._lock = threading.Lock()

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        with self._lock:
            self._depth += 1
            self._max_depth = max(self._max_depth, self._depth)
        try:
            vector = self._inner.event_vector(event)
        finally:
            with self._lock:
                self._depth -= 1
        with self._lock:
            self.calls.append(event.event_id)
        return vector

    def vector_dimension(self):
        return self._inner.vector_dimension()

    @property
    def count(self):
        with self._lock:
            return len(self.calls)

    @property
    def max_depth(self):
        with self._lock:
            return self._max_depth


class _FailingCommit:
    """One-shot sqlite3.Connection wrapper that fails the next COMMIT."""

    def __init__(self, conn):
        self._conn = conn
        self._armed = True
        self.row_factory = conn.row_factory

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._conn.executescript(*args, **kwargs)

    def commit(self):
        if self._armed:
            self._armed = False
            raise sqlite3.Error("injected commit failure")
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()


class DeltaEnv:
    """One sandboxed facts + derived root with a built base generation."""

    def __init__(self, provider=None, facts=None):
        self.facts = facts or base_facts()
        # The production C++ store runs facts.sqlite3 in WAL mode; the delta
        # tests mirror that so the machine's read-only views never collide
        # with the fixture's own writes (rollback-journal stores can make a
        # concurrent reader/writer pair fail with disk I/O errors).  The
        # trivial write materializes the -wal/-shm sidecars, which a
        # read-only WAL reader requires.
        self.facts.conn.execute("PRAGMA journal_mode=WAL;")
        self.facts.conn.execute(
            "UPDATE meta SET value = value WHERE key = 'store_epoch';")
        self.facts.conn.commit()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")
        self.provider = provider or make_provider()
        self.gen = build_generation(self.facts_root, self.provider,
                                    self.derived_root)
        self.generation_id = self.gen.generation_id
        self.gen.close()

    @property
    def db_path(self):
        return os.path.join(self.facts_root, "facts.sqlite3")

    @property
    def delta_path(self):
        # #65: the checkpoint is per-generation
        # (delta/<generation_id>/delta.sqlite3).
        return os.path.join(self.derived_root, "delta", self.generation_id,
                            DELTA_FILENAME)

    def machine(self, provider=None, **kwargs):
        defaults = {"poll_interval": 0.01, "catch_up_deadline": 5.0}
        defaults.update(kwargs)
        return DeltaStateMachine(self.facts_root, self.derived_root,
                                 provider or self.provider,
                                 self.generation_id, **defaults)

    def add_event(self, *args, **kwargs):
        return self.facts.add_event(*args, **kwargs)

    def add_retraction(self, *args, **kwargs):
        return self.facts.add_retraction(*args, **kwargs)

    def cleanup(self):
        try:
            self.facts.close()  # removes the temp facts root (incl. derived)
        finally:
            pass


def env(**kwargs):
    return DeltaEnv(**kwargs)


class EnvTest(unittest.TestCase):
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
        self.env = env(**kwargs)
        return self.env

    def machine(self, *args, **kwargs):
        machine = self.env.machine(*args, **kwargs)
        self.machines.append(machine)
        return machine


class DeltaFileTest(unittest.TestCase):
    """The checkpoint file: schema, pragmas, permissions, privacy."""

    def setUp(self):
        self.env = DeltaEnv()

    def tearDown(self):
        self.env.cleanup()

    def read_rows(self, path):
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute(
                "SELECT event_id, commit_id, schema_id,"
                " canonical_segment_input, category, final_selection_text,"
                " hlc_physical_ms, hlc_logical, vector, change_seq"
                " FROM delta_events ORDER BY change_seq;").fetchall()
            tombstones = conn.execute(
                "SELECT commit_id, hlc_physical_ms, hlc_logical, change_seq"
                " FROM retractions ORDER BY change_seq;").fetchall()
            meta = dict(conn.execute(
                "SELECT key, value FROM meta").fetchall())
            return rows, tombstones, meta
        finally:
            conn.close()

    def test_delta_uses_wal_and_synchronous_full(self):
        machine = self.env.machine()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界", preceding_text="我之前去")
            machine.ensure_caught_up()
        finally:
            machine.close()
        # journal_mode is durable in the file header; synchronous=FULL is
        # connection-local and must be applied on every checkpoint
        # connection (the machine's own connect applies it).
        conn = delta_module._connect_delta(self.env.delta_path)
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode;").fetchone()[0],
                             "wal")
            self.assertEqual(int(conn.execute(
                "PRAGMA synchronous;").fetchone()[0]), 2)
        finally:
            conn.close()
        plain = sqlite3.connect(self.env.delta_path)
        try:
            self.assertEqual(plain.execute(
                "PRAGMA journal_mode;").fetchone()[0], "wal")
        finally:
            plain.close()

    def test_delta_file_is_owner_only(self):
        machine = self.env.machine()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界", preceding_text="我之前去")
            machine.ensure_caught_up()
        finally:
            machine.close()
        mode = os.stat(self.env.delta_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_delta_never_stores_raw_preceding_text(self):
        machine = self.env.machine()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界",
                               preceding_text=SECRET_PRECEDING)
            machine.ensure_caught_up()
        finally:
            machine.close()
        with open(self.env.delta_path, "rb") as handle:
            blob = handle.read()
        self.assertNotIn(SECRET_PRECEDING.encode("utf-8"), blob)
        rows, _tombstones, _meta = self.read_rows(self.env.delta_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "luna_pinyin")
        self.assertEqual(rows[0][3], "shijie")
        self.assertEqual(rows[0][4], "word")
        self.assertEqual(rows[0][5], "世界")

    def test_delta_vectors_are_fp32_blobs(self):
        machine = self.env.machine()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界", preceding_text="我之前去")
            machine.ensure_caught_up()
        finally:
            machine.close()
        rows, _tombstones, _meta = self.read_rows(self.env.delta_path)
        vector = rows[0][8]
        event = self.env.facts.conn.execute(
            "SELECT * FROM selection_events WHERE event_id = 'n1'"
        ).fetchone()
        stored = type("E", (), {
            "event_id": "n1", "commit_id": event["commit_id"],
            "schema_id": event["schema_id"],
            "canonical_segment_input": event["canonical_segment_input"],
            "category": event["category"],
            "final_selection_text": event["final_selection_text"],
            "hlc": (event["hlc_physical_ms"], event["hlc_logical"]),
        })()
        expected = struct.pack("<4f", *[float(v) for v in
                                        fp32(self.env.provider.event_vector(
                                            stored))])
        self.assertEqual(vector, expected)

    def test_delta_records_compatible_identity(self):
        machine = self.env.machine()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界", preceding_text="我之前去")
            machine.ensure_caught_up()
        finally:
            machine.close()
        _rows, _tombstones, meta = self.read_rows(self.env.delta_path)
        self.assertEqual(meta["delta_schema_version"], DELTA_SCHEMA_VERSION)
        self.assertEqual(meta["base_generation_id"], self.env.generation_id)
        self.assertEqual(meta["store_epoch"], "e1")
        self.assertEqual(meta["representation_id"], REPR_ID)
        self.assertEqual(meta["vector_dimension"], "4")
        self.assertEqual(int(meta["base_hlc_physical_ms"]),
                         self.env.gen.source_hlc[0])
        consumed = (int(meta["consumed_hlc_physical_ms"]),
                    int(meta["consumed_hlc_logical"]))
        self.assertGreater(consumed, self.env.gen.source_hlc)


class CatchUpTest(EnvTest):
    """Immediate visibility, the query gate, and the deadline semantics."""

    def test_new_event_is_visible_to_the_next_successful_query(self):
        self.make_env()
        machine = self.machine()
        self.env.add_event("n1", segment_input="shijie", selection="时界",
                           preceding_text="我之前去",
                           competition=("世界", "时界"))
        snapshot = machine.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)
        self.assertIn("n1", [contribution.event_id
                             for contribution in served.kept])

    def test_snapshot_reaches_the_facts_watermark(self):
        self.make_env()
        machine = self.machine()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        snapshot = machine.ensure_caught_up()
        facts_epoch, facts_max = read_facts_identity(self.env.facts_root)
        self.assertEqual(snapshot.store_epoch, facts_epoch)
        self.assertEqual(snapshot.consumed, facts_max)

    def test_lost_notification_still_catches_up(self):
        # The worker polls on a small interval and the gate re-reads the
        # facts identity itself; no notification is ever required.
        self.make_env()
        machine = self.machine(poll_interval=0.01)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        snapshot = machine.ensure_caught_up()
        self.assertIn("n1", snapshot.event_ids())

    def test_behind_watermark_fails_and_never_returns_stale_success(self):
        self.make_env()
        machine = self.machine(poll_interval=0.01, catch_up_deadline=0.3)
        machine.ensure_caught_up()
        machine.request_stop()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界", preceding_text="我之前去")
            with self.assertRaises(EvidenceError) as raised:
                machine.ensure_caught_up()
            self.assertEqual(raised.exception.code, "not_caught_up")
        finally:
            machine.start()
        snapshot = machine.ensure_caught_up()
        self.assertIn("n1", snapshot.event_ids())

    def test_request_deadline_timeout_fails_explicitly(self):
        self.make_env()

        class _Slow(RepresentationProvider):
            """Deterministic slow embedding: every event vector sleeps."""

            def __init__(self, inner):
                self._inner = inner

            def representation_id(self):
                return REPR_ID

            def query_vector(self, preceding_text):
                return QUERY_VECTOR

            def event_vector(self, event):
                time.sleep(0.2)
                return self._inner.event_vector(event)

            def vector_dimension(self):
                return 4

        slow = _CountingProvider(_Slow(self.env.provider))
        machine = self.machine(provider=slow, poll_interval=0.01,
                               catch_up_deadline=0.05)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        with self.assertRaises(EvidenceError) as raised:
            machine.ensure_caught_up()
        self.assertEqual(raised.exception.code, "not_caught_up")
        # The worker keeps working; a later request with room to wait
        # succeeds on the same snapshot.
        snapshot = machine.ensure_caught_up(deadline=time.monotonic() + 5.0)
        self.assertIn("n1", snapshot.event_ids())

    def test_plugin_declared_watermark_is_checked_against_the_snapshot(self):
        self.make_env()
        provider = self.env.provider
        service = EvidenceService(self.env.facts_root, PARAMS, provider, 1.0,
                                  machine=self.machine())
        request = {
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": "shijie",
            "preceding_text": "我之前去",
            "candidates": ["世界", "时界"],
            "fact_high_water": None,
        }
        result = service.serve(request)
        self.assertEqual(result["status"], "ok")
        facts_epoch, facts_max = read_facts_identity(self.env.facts_root)
        request["fact_high_water"] = {
            "store_epoch": facts_epoch,
            "hlc_physical_ms": facts_max[0],
            "hlc_logical": facts_max[1],
        }
        self.assertEqual(service.serve(request)["status"], "ok")
        request["fact_high_water"] = {
            "store_epoch": "wrong-epoch",
            "hlc_physical_ms": facts_max[0],
            "hlc_logical": facts_max[1],
        }
        with self.assertRaises(EvidenceError) as raised:
            service.serve(request)
        self.assertEqual(raised.exception.code, "fact_identity_mismatch")

    def test_evidence_service_never_succeeds_behind_the_watermark(self):
        self.make_env()
        machine = self.machine(poll_interval=0.01, catch_up_deadline=0.3)
        service = EvidenceService(self.env.facts_root, PARAMS,
                                  self.env.provider, 1.0, machine=machine)
        machine.ensure_caught_up()
        machine.request_stop()
        try:
            self.env.add_event("n1", segment_input="shijie",
                               selection="世界", preceding_text="我之前去")
            request = {
                "schema_id": "luna_pinyin",
                "category": "word",
                "canonical_segment_input": "shijie",
                "preceding_text": "我之前去",
                "candidates": ["世界", "时界"],
                "fact_high_water": None,
            }
            with self.assertRaises(EvidenceError) as raised:
                service.serve(request)
            self.assertEqual(raised.exception.code, "not_caught_up")
        finally:
            machine.start()
        self.assertEqual(service.serve(request)["status"], "ok")


class RetractionTest(EnvTest):
    """Whole-commit retractions: evidence and age exit in one snapshot."""

    def test_retraction_exits_evidence_and_age_in_the_same_snapshot(self):
        self.make_env()
        machine = self.machine()
        commit = "commit-n"
        self.env.add_event("n1", commit_id=commit, segment_input="shijie",
                           selection="世界", preceding_text="我之前去",
                           competition=("世界", "时界"))
        self.env.add_event("n2", commit_id=commit, segment_input="shijie",
                           selection="时界", preceding_text="我之后去",
                           competition=("世界", "时界"))
        self.env.add_retraction("r1", commit, (1000000, 99))
        snapshot = machine.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)
        self.assertNotIn("n1", [c.event_id for c in served.kept])
        self.assertNotIn("n2", [c.event_id for c in served.kept])
        # The older same-key events age as if the retracted events never
        # existed (the oracle at the retraction watermark is that answer).
        self.assertEqual(
            {c.event_id: c.usage_age for c in served.kept},
            {c.event_id: c.usage_age for c in expected.kept})

    def test_retraction_of_a_base_commit_exits_evidence_and_age(self):
        self.make_env()
        machine = self.machine()
        base_commit = self.env.facts.conn.execute(
            "SELECT commit_id FROM selection_events WHERE event_id = 'e3'"
        ).fetchone()[0]
        self.env.add_retraction("r1", base_commit, (1000000, 99))
        snapshot = machine.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)
        self.assertNotIn("e3", [c.event_id for c in served.kept])

    def test_commit_and_retraction_in_the_same_batch_never_enter_evidence(self):
        self.make_env()
        machine = self.machine()
        machine.ensure_caught_up()
        commit = "commit-x"
        self.env.add_event("n1", commit_id=commit, segment_input="shijie",
                           selection="世界", preceding_text="我之前去",
                           competition=("世界", "时界"))
        self.env.add_retraction("r1", commit, (1000000, 99))
        snapshot = machine.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)
        self.assertNotIn("n1", [c.event_id for c in served.kept])
        self.assertEqual(
            {c.event_id for c in served.kept},
            {c.event_id for c in expected.kept})


class OrderingTest(EnvTest):
    """AC63-2 / SCN-63-8: one worker, fact-transaction order, no interleave."""

    def test_changes_are_absorbed_in_fact_order(self):
        self.make_env()
        machine = self.machine()
        machine.ensure_caught_up()
        # Quiesce the worker so the whole interleaved sequence lands in one
        # deterministic batch.
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        commit = "commit-o"
        self.env.add_event("o1", commit_id=commit, segment_input="shijie",
                           selection="世界", preceding_text="我之前去")
        self.env.add_event("o2", commit_id=commit, segment_input="jinqi",
                           selection="近期", preceding_text="讨论进展")
        self.env.add_retraction("r1", commit, (1000000, 99))
        self.env.add_event("o3", segment_input="shijie", selection="时界",
                           preceding_text="我之前去")
        machine.start()
        snapshot = machine.ensure_caught_up()
        # o1/o2 were retracted inside the same batch (never embedded), o3
        # survived and the whole commit's tombstone was recorded.
        self.assertEqual(snapshot.change_seq, 1)
        self.assertNotIn("o1", snapshot.event_ids())
        self.assertNotIn("o2", snapshot.event_ids())
        self.assertIn("o3", snapshot.event_ids())
        conn = sqlite3.connect(self.env.delta_path)
        try:
            events = conn.execute(
                "SELECT event_id, change_seq FROM delta_events"
                " ORDER BY change_seq;").fetchall()
            tombstones = conn.execute(
                "SELECT commit_id, change_seq FROM retractions"
                " ORDER BY change_seq;").fetchall()
        finally:
            conn.close()
        # The change sequence preserves the fact store's total order across
        # both tables: o3 (hlc 7) before the tombstone (hlc 99).
        self.assertEqual([row[0] for row in events], ["o3"])
        self.assertEqual(events[0][1], 0)
        self.assertEqual(tombstones, [("commit-o", 1)])

    def test_single_worker_embeds_strictly_sequentially(self):
        self.make_env()
        counting = _CountingProvider(self.env.provider)
        machine = self.machine(provider=counting, poll_interval=0.01)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        self.env.add_event("n2", segment_input="jinqi", selection="近期",
                           preceding_text="讨论进展")
        self.env.add_event("n3", segment_input="shijie", selection="时界",
                           preceding_text="农场清晨")
        machine.ensure_caught_up()
        self.assertEqual(counting.max_depth, 1)
        self.assertEqual(counting.calls, ["n1", "n2", "n3"])

    def test_commits_arriving_during_catch_up_are_picked_up_next(self):
        self.make_env()
        machine = self.machine(poll_interval=0.01)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine.ensure_caught_up()
        first = machine.snapshot()
        self.env.add_event("n2", segment_input="jinqi", selection="近期",
                           preceding_text="讨论进展")
        second = machine.ensure_caught_up()
        self.assertGreater(second.consumed, first.consumed)
        self.assertIn("n2", second.event_ids())
        self.assertNotIn("n2", first.event_ids())


class PublishTimingTest(EnvTest):
    """AC63-4: publish only after commit; old snapshots stay frozen."""

    def test_failed_transaction_publishes_nothing(self):
        self.make_env()
        machine = self.machine(poll_interval=0.01, catch_up_deadline=0.3)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        original = delta_module._connect_delta

        def failing(path):
            return _FailingCommit(original(path))

        with mock.patch.object(delta_module, "_connect_delta", failing):
            with self.assertRaises(EvidenceError) as raised:
                machine.ensure_caught_up()
            self.assertEqual(raised.exception.code, "not_caught_up")
        snapshot = machine.snapshot()
        self.assertNotIn("n1", snapshot.event_ids())
        self.assertEqual(machine.health()["delta_change_seq"], -1)
        if os.path.isfile(self.env.delta_path):
            conn = sqlite3.connect(self.env.delta_path)
            try:
                rows = conn.execute(
                    "SELECT COUNT(*) FROM delta_events").fetchone()[0]
                meta = dict(conn.execute(
                    "SELECT key, value FROM meta").fetchall())
            finally:
                conn.close()
            self.assertEqual(rows, 0)
            self.assertNotIn("change_seq", meta)  # the batch never committed
        # The retry (a fresh connection) advances rows + watermark together.
        snapshot = machine.ensure_caught_up()
        self.assertIn("n1", snapshot.event_ids())

    def test_publish_failure_after_commit_replays_nothing_and_republishes(self):
        self.make_env()
        machine = self.machine(poll_interval=0.01, catch_up_deadline=0.5)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        real_publish = machine._publish_snapshot_locked
        failures = {"on": True}

        def failing_publish():
            if failures["on"]:
                raise DeltaRejected("injected publish failure")
            real_publish()

        with mock.patch.object(machine, "_publish_snapshot_locked",
                               failing_publish):
            # The delta transaction commits but no snapshot may be published;
            # requests keep failing explicitly until a publish succeeds.
            with self.assertRaises(EvidenceError) as raised:
                machine.ensure_caught_up()
            self.assertEqual(raised.exception.code, "not_caught_up")
            snapshot = machine.snapshot()
            self.assertNotIn("n1", snapshot.event_ids())
            conn = sqlite3.connect(self.env.delta_path)
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM delta_events").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)
            failures["on"] = False
        # The committed transaction is never re-embedded: the next cycle
        # re-publishes from the committed state.
        snapshot = machine.ensure_caught_up()
        self.assertIn("n1", snapshot.event_ids())
        conn = sqlite3.connect(self.env.delta_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM delta_events").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_old_snapshot_stays_frozen_while_a_new_one_is_published(self):
        self.make_env()
        machine = self.machine()
        old = machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        new = machine.ensure_caught_up()
        self.assertNotIn("n1", old.event_ids())
        self.assertIn("n1", new.event_ids())
        self.assertEqual(old.consumed, self.env.gen.source_hlc)
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        old_evidence = snapshot_evidence(old, self.env.provider, PARAMS,
                                         query)
        expected_old = oracle_on_facts(
            self.env.facts_root, self.env.provider, PARAMS, query,
            as_of=self.env.gen.source_hlc)
        assert_same_evidence(self, old_evidence, expected_old)


class RecoveryTest(EnvTest):
    """AC63-7 / SCN-63-4/5/6: restart, lost notification, corruption, epoch."""

    def test_restart_loads_the_checkpoint_without_reembedding(self):
        self.make_env()
        counting = _CountingProvider(self.env.provider)
        machine = self.machine(provider=counting)
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        self.env.add_event("n2", segment_input="jinqi", selection="近期",
                           preceding_text="讨论进展")
        machine.ensure_caught_up()
        before = counting.count
        self.assertGreater(before, 0)
        machine.close()
        self.machines.clear()
        machine2 = self.machine(provider=counting)
        machine2.ensure_caught_up()
        self.assertEqual(counting.count, before)
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(machine2.snapshot(), self.env.provider,
                                   PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)

    def test_restart_after_facts_advanced_replays_to_the_same_evidence(self):
        self.make_env()
        machine = self.machine()
        machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        # Facts advanced while the machine was down (lost notifications do
        # not matter: the gate re-reads the facts identity).
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine2 = self.machine()
        snapshot = machine2.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)

    def test_deleted_checkpoint_replays_from_the_base_watermark(self):
        self.make_env()
        counting = _CountingProvider(self.env.provider)
        machine = self.machine(provider=counting)
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine.ensure_caught_up()
        consumed_before = machine.snapshot().consumed
        machine.close()
        self.machines.clear()
        os.unlink(self.env.delta_path)
        machine2 = self.machine(provider=counting)
        snapshot = machine2.ensure_caught_up()
        self.assertEqual(snapshot.consumed, consumed_before)
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)
        # The replay re-embedded exactly the post-H0 event once more.
        self.assertEqual(counting.count, 2)

    def test_truncated_checkpoint_is_dropped_and_replayed(self):
        self.make_env()
        machine = self.machine()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        with open(self.env.delta_path, "r+b") as handle:
            handle.truncate(os.path.getsize(self.env.delta_path) // 2)
        machine2 = self.machine()
        machine2.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(machine2.snapshot(), self.env.provider,
                                   PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)

    def test_bitflipped_checkpoint_is_dropped_and_replayed(self):
        self.make_env()
        machine = self.machine()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        path = self.env.delta_path
        # Corrupt the file header's declared page size: opening the
        # checkpoint then fails deterministically.
        with open(path, "r+b") as handle:
            handle.seek(16)
            byte = handle.read(1)
            handle.seek(-1, 1)
            handle.write(bytes([byte[0] ^ 0xFF]))
        machine2 = self.machine()
        machine2.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(machine2.snapshot(), self.env.provider,
                                   PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)

    def test_identity_mismatched_checkpoint_is_dropped_and_replayed(self):
        self.make_env()
        machine = self.machine()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        conn = sqlite3.connect(self.env.delta_path)
        try:
            conn.execute(
                "UPDATE meta SET value = 'wrong-repr'"
                " WHERE key = 'representation_id';")
            conn.commit()
        finally:
            conn.close()
        machine2 = self.machine()
        snapshot = machine2.ensure_caught_up()
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)

    def test_epoch_change_discards_everything_and_rebuilds(self):
        self.make_env()
        machine = self.machine(poll_interval=0.01)
        machine.ensure_caught_up()
        old_delta = self.env.delta_path
        # The checkpoint is created lazily on the first change batch; with no
        # changes after the base there is no file yet.
        self.assertFalse(os.path.isfile(old_delta))
        # A restore/clear replaced the facts with a new store epoch.
        self.env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        self.env.facts.conn.execute(
            "UPDATE meta SET value = '2000000'"
            " WHERE key = 'hlc_physical_ms';")
        self.env.facts.conn.execute(
            "UPDATE meta SET value = '0' WHERE key = 'hlc_logical';")
        self.env.facts.conn.commit()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.store_epoch, "e2")
        self.assertNotEqual(snapshot.base_generation_id, self.env.generation_id)
        self.assertIn("n1", snapshot.event_ids())
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        assert_same_evidence(self, served, expected)
        # A change after the rebuild writes a fresh checkpoint bound to the
        # new generation and epoch (the stale one was discarded).
        self.env.add_event("n2", hlc=(2000000, 1), segment_input="shijie",
                           selection="世界", preceding_text="我之前去")
        snapshot = machine.ensure_caught_up()
        self.assertIn("n2", snapshot.event_ids())
        conn = sqlite3.connect(machine.delta_checkpoint_path())
        try:
            meta = dict(conn.execute(
                "SELECT key, value FROM meta").fetchall())
            self.assertEqual(meta["store_epoch"], "e2")
            self.assertEqual(meta["base_generation_id"],
                             snapshot.base_generation_id)
        finally:
            conn.close()

    def test_restart_after_epoch_change_self_heals(self):
        self.make_env()
        machine = self.machine()
        machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        self.env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        self.env.facts.conn.commit()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        # The declared generation id is stale; the machine rebuilds from the
        # facts instead of serving derived state across epochs.
        machine2 = self.machine()
        snapshot = machine2.ensure_caught_up()
        self.assertEqual(snapshot.store_epoch, "e2")
        self.assertIn("n1", snapshot.event_ids())


class BlockedTest(EnvTest):
    """Deterministic faults block catch-up with the event named."""

    def _blocking_provider(self, bad_event="n1"):
        inner = self.env.provider

        class Blocking(RepresentationProvider):
            def representation_id(self):
                return inner.representation_id()

            def query_vector(self, preceding_text):
                return inner.query_vector(preceding_text)

            def event_vector(self, event):
                if event.event_id == bad_event:
                    raise EvidenceError(
                        "representation_fault",
                        "cannot represent %s" % event.event_id)
                return inner.event_vector(event)

            def vector_dimension(self):
                return inner.vector_dimension()

        return Blocking()

    def test_deterministic_error_blocks_and_names_the_event(self):
        self.make_env()
        provider = self._blocking_provider()
        machine = self.machine(provider=provider, poll_interval=0.01,
                               catch_up_deadline=0.3)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        with self.assertRaises(EvidenceError) as raised:
            machine.ensure_caught_up()
        self.assertEqual(raised.exception.code, "representation_fault")
        self.assertTrue(machine.health()["delta_blocked"])
        # The blocked diagnosis record lands asynchronously in the checkpoint
        # (the worker persists it after unblocking the waiting request).
        deadline = time.monotonic() + 5.0
        while True:
            if os.path.isfile(self.env.delta_path):
                try:
                    conn = sqlite3.connect(self.env.delta_path, timeout=0)
                    try:
                        meta = dict(conn.execute(
                            "SELECT key, value FROM meta").fetchall())
                    finally:
                        conn.close()
                    if meta.get("blocked") == "1":
                        break
                except sqlite3.Error:
                    pass
            if time.monotonic() > deadline:
                self.fail("blocked record never landed in the checkpoint")
            time.sleep(0.01)
        self.assertEqual(meta["blocked"], "1")
        self.assertIn("n1", json.loads(meta["blocked_events"]))

    def test_blocked_survives_restart_without_reembedding(self):
        self.make_env()
        provider = self._blocking_provider()
        counting = _CountingProvider(provider)
        machine = self.machine(provider=counting, poll_interval=0.01,
                               catch_up_deadline=0.3)
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        with self.assertRaises(EvidenceError):
            machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        machine2 = self.machine(provider=counting, poll_interval=0.01,
                                catch_up_deadline=0.3)
        with self.assertRaises(EvidenceError) as raised:
            machine2.ensure_caught_up()
        self.assertEqual(raised.exception.code, "representation_fault")

    def test_retry_reattempts_after_a_block(self):
        self.make_env()
        inner = self.env.provider
        calls = {"count": 0}
        failures = {"on": True}

        class Flaky(RepresentationProvider):
            def representation_id(self):
                return inner.representation_id()

            def query_vector(self, preceding_text):
                return inner.query_vector(preceding_text)

            def event_vector(self, event):
                calls["count"] += 1
                if failures["on"] and event.event_id == "n1":
                    raise EvidenceError(
                        "representation_fault",
                        "cannot represent %s" % event.event_id)
                return inner.event_vector(event)

            def vector_dimension(self):
                return inner.vector_dimension()

        machine = self.machine(provider=Flaky(), poll_interval=0.01,
                               catch_up_deadline=0.3)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        with self.assertRaises(EvidenceError):
            machine.ensure_caught_up()
        failures["on"] = False
        machine.retry()
        snapshot = machine.ensure_caught_up()
        self.assertIn("n1", snapshot.event_ids())
        # The diagnosis record is cleared by a successful retry.
        conn = sqlite3.connect(self.env.delta_path)
        try:
            meta = dict(conn.execute(
                "SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
        self.assertNotIn("blocked", meta)

    def test_retry_waits_for_the_delta_write_lock(self):
        """Maintenance retry() never fails fast on a concurrent write lock.

        Pins the AC-63-v1 repair: a checkpoint connection must not re-set
        the persistent journal_mode pragma (which would take the write
        lock), and the maintenance path must wait for a briefly held lock
        instead of surfacing a spurious failure.
        """
        self.make_env()
        inner = self.env.provider
        failures = {"on": True}

        class Flaky(RepresentationProvider):
            def representation_id(self):
                return inner.representation_id()

            def query_vector(self, preceding_text):
                return inner.query_vector(preceding_text)

            def event_vector(self, event):
                if failures["on"] and event.event_id == "n1":
                    raise EvidenceError(
                        "representation_fault",
                        "cannot represent %s" % event.event_id)
                return inner.event_vector(event)

            def vector_dimension(self):
                return inner.vector_dimension()

        machine = self.machine(provider=Flaky(), poll_interval=0.01,
                               catch_up_deadline=0.3)
        machine.ensure_caught_up()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        with self.assertRaises(EvidenceError):
            machine.ensure_caught_up()
        failures["on"] = False
        # A second connection holds the delta write lock for 0.3 s (created
        # in its own thread: sqlite connections are thread-bound).
        locked = threading.Event()

        def holder():
            conn = sqlite3.connect(self.env.delta_path, timeout=0)
            conn.execute("BEGIN IMMEDIATE;")
            locked.set()
            time.sleep(0.3)
            conn.rollback()
            conn.close()

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(locked.wait(5.0))
        start = time.monotonic()
        try:
            machine.retry()
            waited = time.monotonic() - start
        finally:
            thread.join(10.0)
        # retry() waited for the lock and completed -- it did not fail
        # fast with a spurious lock error (the repaired defect).
        self.assertGreaterEqual(waited, 0.25)
        self.assertLess(waited, 4.0)
        snapshot = machine.ensure_caught_up()
        self.assertIn("n1", snapshot.event_ids())

    def test_retry_under_worker_write_concurrency(self):
        """Many block -> retry -> catch-up cycles stay deterministic.

        Each round commits a batch of events, blocks on the first, then
        retries while the worker absorbs the whole batch.  The retry path
        must never surface a spurious lock failure and every round must
        end fully caught up (regression pin for the AC-63-v1 repair).
        """
        self.make_env()
        inner = self.env.provider
        failures = {"on": True}
        rounds = 8

        class Flaky(RepresentationProvider):
            def representation_id(self):
                return inner.representation_id()

            def query_vector(self, preceding_text):
                return inner.query_vector(preceding_text)

            def event_vector(self, event):
                if failures["on"] and event.event_id.endswith("blocking"):
                    raise EvidenceError(
                        "representation_fault",
                        "cannot represent %s" % event.event_id)
                return inner.event_vector(event)

            def vector_dimension(self):
                return inner.vector_dimension()

        machine = self.machine(provider=Flaky(), poll_interval=0.005,
                               catch_up_deadline=5.0)
        machine.ensure_caught_up()
        for round_index in range(rounds):
            prefix = "r%d-" % round_index
            self.env.add_event(
                prefix + "blocking", segment_input="shijie",
                selection="世界", preceding_text="我之前去")
            for index in range(30):
                self.env.add_event(
                    prefix + "e%02d" % index, segment_input="shijie",
                    selection="时界" if index % 2 else "世界",
                    preceding_text="我之前去")
            with self.assertRaises(EvidenceError) as raised:
                machine.ensure_caught_up()
            self.assertEqual(raised.exception.code, "representation_fault")
            failures["on"] = False
            machine.retry()
            snapshot = machine.ensure_caught_up()
            self.assertIn(prefix + "blocking", snapshot.event_ids())
            self.assertIn(prefix + "e29", snapshot.event_ids())
            failures["on"] = True
        machine.close()
        self.machines.clear()
        # A restart after all rounds loads a clean checkpoint (no leftover
        # blocked record from any round).
        machine2 = self.machine(provider=Flaky(), poll_interval=0.005,
                                catch_up_deadline=5.0)
        snapshot = machine2.ensure_caught_up()
        self.assertIn("r7-e29", snapshot.event_ids())


class ServiceWiringTest(EnvTest):
    """The EvidenceService + config wiring (the #61/#62/#63 seam)."""

    def test_service_serves_evidence_from_the_machine_snapshot(self):
        self.make_env()
        machine = self.machine()
        service = EvidenceService(self.env.facts_root, PARAMS,
                                  self.env.provider, 1.0, machine=machine)
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        request = {
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": "shijie",
            "preceding_text": "我之前去",
            "candidates": ["世界", "时界"],
            "fact_high_water": None,
        }
        result = service.serve(request)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["zero_evidence"])
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        expected = oracle_on_facts(self.env.facts_root, self.env.provider,
                                   PARAMS, query)
        served_s = {entry["index"]: entry["s"] for entry in result["evidence"]}
        self.assertEqual(
            served_s,
            {c.index: c.s for c in expected.candidates})

    def test_machine_with_missing_facts_keeps_missing_store_semantics(self):
        self.make_env()
        machine = self.machine()
        machine.ensure_caught_up()
        machine.close()
        self.machines.clear()
        os.unlink(self.env.db_path)
        service = EvidenceService(self.env.facts_root, PARAMS,
                                  self.env.provider, 1.0, machine=machine)
        request = {
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": "shijie",
            "preceding_text": "我之前去",
            "candidates": ["世界", "时界"],
            "fact_high_water": None,
        }
        result = service.serve(request)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["zero_evidence"])
        request["fact_high_water"] = {
            "store_epoch": "e1",
            "hlc_physical_ms": 1000000,
            "hlc_logical": 0,
        }
        with self.assertRaises(EvidenceError) as raised:
            service.serve(request)
        self.assertEqual(raised.exception.code, "fact_store_fault")

    def test_config_builder_builds_the_machine(self):
        self.make_env()
        config = {
            "representation_id": REPR_ID,
            "tau": 0.5,
            "k_evidence": 8,
            "half_life": 32.0,
            "saturation_k": 1.0,
            "gamma": 1.0,
            "query_vectors": {"我之前去": list(QUERY_VECTOR)},
            "event_vectors": {},
            "derived_root": self.env.derived_root,
            "generation_id": self.env.generation_id,
            "poll_interval_ms": 10,
            "catch_up_deadline_ms": 5000,
        }
        machine = build_delta_machine_from_config(self.env.facts_root,
                                                  config)
        self.machines.append(machine)
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        service = build_evidence_service_from_config(self.env.facts_root,
                                                     config, machine=machine)
        request = {
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": "shijie",
            "preceding_text": "我之前去",
            "candidates": ["世界", "时界"],
            "fact_high_water": None,
        }
        result = service.serve(request)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["zero_evidence"])

    def test_config_builder_requires_both_delta_keys(self):
        self.make_env()
        config = {"derived_root": self.env.derived_root,
                  "representation_id": REPR_ID}
        with self.assertRaises(EvidenceError):
            build_delta_machine_from_config(self.env.facts_root, config)
        config = {"generation_id": self.env.generation_id,
                  "representation_id": REPR_ID}
        with self.assertRaises(EvidenceError):
            build_delta_machine_from_config(self.env.facts_root, config)

    def test_config_without_delta_keys_stays_legacy(self):
        self.make_env()
        config = {"representation_id": REPR_ID, "gamma": 1.0}
        self.assertIsNone(build_delta_machine_from_config(
            self.env.facts_root, config))

    def test_machine_rejects_provider_identity_mismatch(self):
        self.make_env()
        other = make_provider(representation_id="delta-test-repr-v2")
        with self.assertRaises(DeltaError):
            DeltaStateMachine(self.env.facts_root, self.env.derived_root,
                              other, self.env.generation_id)


class EmptyAndEdgeTest(EnvTest):
    """Empty stores, no changes, and the machine lifecycle."""

    def test_empty_fact_store_builds_and_serves_zero_evidence(self):
        self.env = DeltaEnv(facts=FactsFixture())
        machine = self.machine()
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.event_ids(), [])
        query = OracleQuery(schema_id="luna_pinyin",
                            canonical_segment_input="shijie",
                            candidates=["世界", "时界"],
                            query_vector=QUERY_VECTOR)
        served = snapshot_evidence(snapshot, self.env.provider, PARAMS, query)
        self.assertEqual([c.s for c in served.candidates], [0.0, 0.0])

    def test_no_changes_after_base_is_a_fast_noop(self):
        self.make_env()
        machine = self.machine()
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.consumed, self.env.gen.source_hlc)
        self.assertEqual(machine.health()["delta_change_seq"], -1)

    def test_delta_checkpoint_open_rejects_garbage(self):
        self.make_env()
        path = self.env.delta_path
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"not a sqlite database at all")
        with self.assertRaises(DeltaRejected):
            open_delta_checkpoint(path, self.env.gen, self.env.provider,
                                  self.env.facts_root)


class CoordinatorSeamTest(EnvTest):
    """The maintenance-coordinator recovery and builder seams."""

    def test_invalidate_discards_derived_state(self):
        self.make_env()
        machine = self.machine()
        self.env.add_event("n1", segment_input="shijie", selection="世界",
                           preceding_text="我之前去")
        machine.ensure_caught_up()
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        machine.invalidate("e1", "e1")
        self.assertIsNone(machine.snapshot())
        self.assertFalse(os.path.isfile(self.env.delta_path))
        machine.rebuild("e1")
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.store_epoch, "e1")

    def test_rebuild_callback_fires_after_the_new_base_snapshot(self):
        self.make_env()
        machine = self.machine()
        machine.ensure_caught_up()
        machine.request_stop()
        self.assertTrue(machine.wait_idle(5.0))
        fired = {"count": 0}

        def complete(target_epoch):
            fired["count"] += 1
            fired["epoch"] = target_epoch
            self.assertIsNotNone(machine.snapshot())

        machine.rebuild("e1", complete)
        snapshot = machine.ensure_caught_up()
        self.assertEqual(snapshot.store_epoch, "e1")
        self.assertEqual(fired["count"], 1)
        self.assertEqual(fired["epoch"], "e1")


if __name__ == "__main__":
    unittest.main()
