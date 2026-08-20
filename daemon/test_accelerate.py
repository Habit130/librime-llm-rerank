#!/usr/bin/env python3
"""Accelerate exact-backend equivalence suite (Habit130/squirrel#72, AC-72-v1).

Model-free, deterministic, sandboxed: the Accelerate backend
(``daemon/accelerate.py``, Apple vecLib ``cblas_sgemv``) is compared against
the canonical stdlib oracle (``daemon/oracle.py``) on the SAME query /
facts / vectors.  Maps one-to-one onto the blocking scenarios:

  SCN-72-1  every same-key active event is scored on the Accelerate path;
            no cosine shortlist substitutes for the oracle's full evaluation
  SCN-72-2  per-query neighbors / event weights / candidate evidence s_c /
            final emit order match the stdlib oracle within the pinned
            tolerance (1e-6 absolute cosine; any kept-set or emit-order flip
            is an equivalence fail, never "almost")
  SCN-72-4  the Accelerate backend enters ``index_fingerprint`` and differs
            from the oracle backend fingerprint (SCN-72-4)
  SCN-72-5  Accelerate missing at runtime fails closed (no silent Python
            fallback presented as Accelerate)

The suite skips (not fails) when Apple vecLib is unavailable on the host, so
it stays green on non-macOS CI; on this machine vecLib is required.

Never touches live facts, ~/Library/Rime, or the live daemon.
"""

import math
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from oracle import (  # noqa: E402
    OracleError,
    OracleParams,
    OracleQuery,
    FactReader,
    compute_evidence,
)
from seed_vectors import _vector  # noqa: E402  (deterministic fixture vectors)

try:
    from accelerate import (  # noqa: E402
        AccelerateCosineEngine,
        AccelerateError,
        _load_vecLib,
        build_cosine_engine,
    )
    _load_vecLib()
    VECLIB_AVAILABLE = True
except Exception:  # noqa: BLE001 - env without vecLib skips the suite
    VECLIB_AVAILABLE = False

from test_oracle import FACT_DDL  # noqa: E402  (production fact schema)

DIM = 1024
SEED = 20260817
# Pinned equivalence tolerance (SCN-72-2 / RISK-72-3): absolute cosine
# difference vs the oracle.  Measured sgemv deviation at 100k x 1024 is
# ~1e-8, two orders of magnitude inside this bound.
COSINE_TOLERANCE = 1e-6


def build_facts(root, events, seed=SEED):
    """A sandboxed fact store with ``events`` same-hot-key selection events.

    Deterministic: event ids ev-0..ev-N, final selection cycling w0/w1/w2,
    monotone HLC, 64-char synthetic preceding text.  Returns the store path.
    """
    os.makedirs(root, exist_ok=True)
    db_path = os.path.join(root, "facts.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript(FACT_DDL)
    base = 1700000000000
    conn.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", [
        ("fact_schema_version", "1"),
        ("event_format_version", "1"),
        ("history_id", "fixture-history-%d" % seed),
        ("store_epoch", "fixture-epoch-%d" % seed),
        ("hlc_physical_ms", str(base)),
        ("hlc_logical", "0"),
    ])
    conn.executemany(
        "INSERT INTO commits(commit_id, utc_committed_at_ms) VALUES(?, ?)",
        [("c-%d" % i, base + i) for i in range(events)])
    rows = []
    for i in range(events):
        rows.append((
            "ev-%d" % i, "c-%d" % i, 1, "luna_pinyin", "hotkey", 0, 4,
            "word", "w" * 64, 1, ("w0", "w1", "w2")[i % 3],
            "explicit_current", None, 1, 1, "synthetic-session", i,
            base + i, 0, base + i, base + i))
    conn.executemany(
        "INSERT INTO selection_events(event_id, commit_id,"
        " event_format_version, schema_id, canonical_segment_input,"
        " span_start, span_end, category, preceding_text,"
        " competition_complete, final_selection_text, confirmation_source,"
        " trigger_keycode, display_rank, display_page, session_id,"
        " session_seq, hlc_physical_ms, hlc_logical, utc_confirmed_at_ms,"
        " utc_committed_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'hlc_physical_ms'",
                 (str(base + events),))
    conn.commit()
    conn.close()
    return db_path


class _FixtureMatrix:
    """A deterministic FP32 matrix backing the engine, from seed vectors."""

    def __init__(self, events, dimension=DIM, seed=SEED):
        self.events = events
        self.dimension = dimension
        self.row_index = {"ev-%d" % i: i for i in range(events)}
        tmpdir = tempfile.mkdtemp(prefix="accel-matrix-")
        self.path = os.path.join(tmpdir, "vectors.fp32")
        with open(self.path, "wb") as handle:
            for i in range(events):
                vector = _vector(seed, "event", "ev-%d" % i, dimension)
                handle.write(struct.pack("<%df" % dimension, *vector))
        self._file = open(self.path, "rb")
        import mmap
        self._mm = mmap.mmap(self._file.fileno(), 0,
                             access=mmap.ACCESS_COPY)
        self.buffer = self._mm

    def event_vector(self, event_id):
        row = self.row_index[event_id]
        return struct.unpack_from("<%df" % self.dimension, self.buffer,
                                  row * self.dimension * 4)

    def close(self):
        try:
            self._mm.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
        try:
            self._file.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
        shutil.rmtree(os.path.dirname(self.path), ignore_errors=True)


def assert_equivalent(testcase, oracle, engine):
    """Query-by-query equivalence shared by the #72/#73 backend suites.

    Compares the oracle and a backend-engine result: same-key active count,
    kept set (same events, same order), per-event cosine/weight deviation
    within COSINE_TOLERANCE, per-candidate evidence ``s_c`` deviation and
    the final emit order.  ``testcase`` is the unittest.TestCase providing
    the assert methods.
    """
    testcase.assertEqual(oracle.same_key_active, engine.same_key_active,
                         "same-key active count must match")
    oracle_kept = [(c.event_id, c.cosine, c.weight, c.matched_candidate)
                   for c in oracle.kept]
    engine_kept = [(c.event_id, c.cosine, c.weight, c.matched_candidate)
                   for c in engine.kept]
    # SCN-72-2 / SCN-73-2: identical kept-set (same events, same order).
    testcase.assertEqual(
        [item[0] for item in oracle_kept],
        [item[0] for item in engine_kept],
        "kept event set / order must match the oracle")
    for o_entry, e_entry in zip(oracle_kept, engine_kept):
        testcase.assertLessEqual(
            abs(o_entry[1] - e_entry[1]), COSINE_TOLERANCE,
            "cosine deviation exceeds the pinned tolerance")
        testcase.assertLessEqual(
            abs(o_entry[2] - e_entry[2]), COSINE_TOLERANCE,
            "weight deviation exceeds the pinned tolerance")
        testcase.assertEqual(o_entry[3], e_entry[3],
                             "matched candidate must match")
    # s_c per candidate + final emit order (by descending s, then index).
    oracle_sc = {c.index: c.s for c in oracle.candidates}
    engine_sc = {c.index: c.s for c in engine.candidates}
    for index in oracle_sc:
        testcase.assertLessEqual(
            abs(oracle_sc[index] - engine_sc[index]), COSINE_TOLERANCE,
            "candidate evidence s_c deviation exceeds tolerance")
    oracle_order = sorted(range(len(oracle_sc)),
                          key=lambda i: (-oracle_sc[i], i))
    engine_order = sorted(range(len(engine_sc)),
                          key=lambda i: (-engine_sc[i], i))
    testcase.assertEqual(oracle_order, engine_order,
                         "final emit order must match the oracle")


@unittest.skipUnless(VECLIB_AVAILABLE,
                     "Apple vecLib not available; skipping Accelerate suite")
class AccelerateEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="accel-equiv-")
        self.params = OracleParams(tau=0.0, k_evidence=8, half_life=32.0,
                                   saturation_k=2.0)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _query(self, text="a" * 64):
        return OracleQuery(
            schema_id="luna_pinyin",
            canonical_segment_input="hotkey",
            candidates=["w0", "w1", "w2"],
            query_vector=_vector(SEED, "query", text, DIM))

    def _run_both(self, events, query_texts, matrix=None,
                  engine_cls=AccelerateCosineEngine):
        """Compute oracle and engine results for the same queries."""
        db = build_facts(os.path.join(self.root, "facts"), events)
        own_matrix = matrix is None
        if own_matrix:
            matrix = _FixtureMatrix(events)
        try:
            engine = engine_cls(matrix.buffer, events, matrix.dimension,
                                matrix.row_index)
            reader = FactReader(db)

            def vector_for(event_id):
                return matrix.event_vector(event_id)

            oracle_results = []
            engine_results = []
            for text in query_texts:
                query = self._query(text)
                o = compute_evidence(reader, self.params, query, vector_for)
                e = compute_evidence(reader, self.params, query, vector_for,
                                     cosine_engine=engine)
                oracle_results.append(o)
                engine_results.append(e)
            return oracle_results, engine_results
        finally:
            if own_matrix:
                matrix.close()

    def assert_equivalent(self, oracle, engine):
        """Query-by-query equivalence: kept set, weights, s_c, emit order."""
        assert_equivalent(self, oracle, engine)

    # -- SCN-72-1/72-2: large same-key sets use the sgemv batched path ------

    def test_large_same_key_matches_oracle(self):
        """SCN-72-1/72-2: 5000 same-key events through the sgemv path."""
        oracle_results, engine_results = self._run_both(
            5000, ["a" * 64, "b" * 64, "c" * 64])
        for oracle, engine in zip(oracle_results, engine_results):
            self.assertEqual(oracle.same_key_active, 5000)
            self.assert_equivalent(oracle, engine)

    def test_small_same_key_matches_oracle(self):
        """Small sets (<= threshold) use the byte-identical Python path."""
        oracle_results, engine_results = self._run_both(
            100, ["a" * 64, "d" * 64])
        for oracle, engine in zip(oracle_results, engine_results):
            self.assertEqual(oracle.same_key_active, 100)
            self.assert_equivalent(oracle, engine)

    def test_mixed_delta_fallback_matches_oracle(self):
        """Events missing from the matrix fall back to vector_for (delta).

        SCN-72-1: every same-key event is still scored; the fallback is the
        oracle's own float64 cosine, so the result is exact.
        """
        events = 300
        matrix = _FixtureMatrix(events)
        # A second matrix holding the "delta" event that is NOT in the first
        # matrix: the engine must still score it via vector_for.
        extra = 3
        matrix2 = _FixtureMatrix(events + extra)
        try:
            engine = AccelerateCosineEngine(
                matrix.buffer, events, matrix.dimension, matrix.row_index)
            db = build_facts(os.path.join(self.root, "facts"), events + extra)

            def vector_for(event_id):
                return matrix2.event_vector(event_id)

            reader = FactReader(db)
            for text in ("a" * 64, "e" * 64):
                query = self._query(text)
                oracle = compute_evidence(reader, self.params, query,
                                          vector_for)
                engine_result = compute_evidence(
                    reader, self.params, query, vector_for,
                    cosine_engine=engine)
                self.assertEqual(oracle.same_key_active, events + extra)
                self.assert_equivalent(oracle, engine_result)
        finally:
            matrix.close()
            matrix2.close()

    def test_every_same_key_event_is_scored(self):
        """SCN-72-1: a same-key event the engine cannot serve is a fault."""
        events = 400
        matrix = _FixtureMatrix(events)
        try:
            db = build_facts(os.path.join(self.root, "facts"), events)
            # An engine whose matrix covers only the first 200 events: the
            # remaining same-key events must still be scored (via vector_for)
            # or fault -- never silently dropped from the scored set.
            partial_rows = {k: v for k, v in matrix.row_index.items()
                            if v < 200}
            engine = AccelerateCosineEngine(
                matrix.buffer, events, matrix.dimension, partial_rows)
            reader = FactReader(db)
            query = self._query("z" * 64)

            def vector_for(event_id):
                # No fallback vector available: the engine must fault rather
                # than serve a truncated same-key set (SCN-72-1).
                raise OracleError("no vector for %s" % event_id)

            with self.assertRaises(OracleError):
                compute_evidence(reader, self.params, query, vector_for,
                                 cosine_engine=engine)

            # With a working fallback, the same engine serves every event:
            # the missing-from-matrix events are scored exactly like the
            # oracle (delta catch-up path).
            def vector_for_ok(event_id):
                return matrix.event_vector(event_id)

            oracle = compute_evidence(reader, self.params, query,
                                      vector_for_ok)
            engine_result = compute_evidence(
                reader, self.params, query, vector_for_ok,
                cosine_engine=engine)
            self.assertEqual(oracle.same_key_active, events)
            self.assert_equivalent(oracle, engine_result)
        finally:
            matrix.close()

    # -- SCN-72-5: fail closed ----------------------------------------------

    def test_missing_vecLib_fails_closed(self):
        """Accelerate missing at runtime raises AccelerateError, never a
        silent Python fallback."""
        import accelerate as _accel
        from unittest import mock
        with mock.patch.object(_accel, "_load_vecLib",
                               side_effect=AccelerateError("no vecLib")):
            with self.assertRaises(AccelerateError):
                build_cosine_engine(b"", 0, 1024, {})

    # -- SCN-72-4: backend enters the fingerprint ---------------------------

    def test_fingerprint_distinguishes_backends(self):
        from compat import (ACCELERATE_BACKEND, EXACT_BACKEND,
                            compose_backend_fingerprint)
        exact_fp = compose_backend_fingerprint(EXACT_BACKEND)
        accelerate_fp = compose_backend_fingerprint(ACCELERATE_BACKEND)
        # SCN-72-4: the Accelerate backend must NEVER reuse the oracle
        # fingerprint; the content digest differs because the backend and
        # library/ABI version enter the payload.
        self.assertNotEqual(exact_fp, accelerate_fp,
                            "Accelerate must not reuse the oracle fingerprint")
        # And the Accelerate backend must not silently bind the oracle's
        # library version either (that would be a fingerprint forgery).
        from compat import (ACCELERATE_LIBRARY_VERSION,
                            EXACT_LIBRARY_VERSION, compose_index_fingerprint)
        forged = compose_index_fingerprint(
            backend=ACCELERATE_BACKEND,
            library_version=EXACT_LIBRARY_VERSION)
        self.assertNotEqual(accelerate_fp, forged)

    def test_generation_build_binds_backend(self):
        """An Accelerate generation gets a different id and fingerprint than
        the oracle build of the same facts (SCN-72-4)."""
        from generation import build_generation
        from seed_vectors import SeedVectorProvider
        from compat import ACCELERATE_BACKEND, EXACT_BACKEND
        events = 120
        db_root = os.path.join(self.root, "facts")
        build_facts(db_root, events)
        out_exact = os.path.join(self.root, "out-exact")
        out_accel = os.path.join(self.root, "out-accel")
        provider = SeedVectorProvider("seed-fixture-v1:1024", SEED, DIM)
        g_exact = build_generation(db_root, provider, out_exact,
                                   retrieval_backend=EXACT_BACKEND)
        g_accel = build_generation(db_root, provider, out_accel,
                                   retrieval_backend=ACCELERATE_BACKEND)
        try:
            self.assertNotEqual(g_exact.generation_id, g_accel.generation_id)
            self.assertEqual(g_exact.retrieval_backend, EXACT_BACKEND)
            self.assertEqual(g_accel.retrieval_backend, ACCELERATE_BACKEND)
            self.assertNotEqual(g_exact.index_fingerprint,
                                g_accel.index_fingerprint)
            # The FP32 vector file itself is identical (same facts/vectors).
            with open(os.path.join(g_exact.generation_dir,
                                   "vectors.fp32"), "rb") as a, \
                 open(os.path.join(g_accel.generation_dir,
                                   "vectors.fp32"), "rb") as b:
                self.assertEqual(a.read(), b.read(),
                                 "FP32 vectors must be identical across "
                                 "backends")
        finally:
            g_exact.close()
            g_accel.close()

    def test_generation_reopen_accepts_accelerate_backend(self):
        """An Accelerate generation reopens through open_generation."""
        from generation import build_generation, open_generation
        from seed_vectors import SeedVectorProvider
        from compat import ACCELERATE_BACKEND
        events = 90
        db_root = os.path.join(self.root, "facts")
        build_facts(db_root, events)
        out = os.path.join(self.root, "out")
        provider = SeedVectorProvider("seed-fixture-v1:1024", SEED, DIM)
        g = build_generation(db_root, provider, out,
                             retrieval_backend=ACCELERATE_BACKEND)
        gen_id = g.generation_id
        g.close()
        reopened = open_generation(os.path.join(out, "generations", gen_id))
        try:
            self.assertEqual(reopened.retrieval_backend, ACCELERATE_BACKEND)
        finally:
            reopened.close()

    # -- engine direct checks ------------------------------------------------

    def test_engine_cosine_matches_oracle_single(self):
        """One event: engine cosine == oracle cosine within tolerance."""
        events = 1
        matrix = _FixtureMatrix(events)
        try:
            engine = AccelerateCosineEngine(
                matrix.buffer, events, matrix.dimension, matrix.row_index)
            query_vector = _vector(SEED, "query", "q" * 64, DIM)
            event_vector = matrix.event_vector("ev-0")
            dot = sum(a * b for a, b in zip(query_vector, event_vector))
            qn = sum(a * a for a in query_vector)
            en = sum(b * b for b in event_vector)
            oracle_cos = dot / math.sqrt(qn * en)
            batch = engine.batch_cosines(query_vector, ("ev-0",),
                                         matrix.event_vector)
            self.assertLessEqual(abs(oracle_cos - batch["ev-0"]),
                                 COSINE_TOLERANCE)
        finally:
            matrix.close()

    # -- SCN-72-5: no silent backend switch ----------------------------------

    @staticmethod
    def _make_service(backend):
        from evidence import (EvidenceService,
                              FixtureRepresentationProvider)
        provider = FixtureRepresentationProvider(
            "seed-fixture-v1:1024", {"q": [1.0, 0.0, 0.0, 0.0]},
            {"schema|candidate|selection": [0.0, 1.0, 0.0, 0.0]})
        return EvidenceService(
            "/tmp/nonexistent-facts", OracleParams(
                tau=0.0, k_evidence=8, half_life=float("inf"),
                saturation_k=1.0),
            provider, gamma=1.0, retrieval_backend=backend)

    def test_backend_mismatch_fails_closed(self):
        """A generation built for one backend must never be silently served
        by a service configured for another (SCN-72-5: the served backend is
        bound into index_fingerprint, so a silent switch would serve under a
        forged identity)."""
        from evidence import BACKEND_ACCELERATE, BACKEND_ORACLE, EvidenceError

        class FakeSnapshot:
            def retrieval_backend(self):
                return BACKEND_ORACLE  # generation built for the oracle

            def accelerate_engine(self):
                raise AssertionError("must not build an engine for a "
                                     "mismatched generation")

        # Config says Accelerate, snapshot generation is oracle -> fault.
        service = self._make_service(BACKEND_ACCELERATE)
        with self.assertRaises(EvidenceError) as ctx:
            service._cosine_engine(FakeSnapshot())
        self.assertEqual(ctx.exception.code, "backend_mismatch")

        # Config says oracle, snapshot is Accelerate -> fault (never silently
        # serve the python path for an Accelerate fingerprint).
        class FakeSnapshotAccel:
            def retrieval_backend(self):
                return BACKEND_ACCELERATE

        service_oracle = self._make_service(BACKEND_ORACLE)
        with self.assertRaises(EvidenceError) as ctx:
            service_oracle._cosine_engine(FakeSnapshotAccel())
        self.assertEqual(ctx.exception.code, "backend_mismatch")

    def test_backend_match_serves(self):
        """Matching backends serve (oracle config + oracle generation -> the
        None engine path, i.e. the canonical oracle)."""
        from evidence import BACKEND_ORACLE

        class FakeSnapshot:
            def retrieval_backend(self):
                return BACKEND_ORACLE

        service = self._make_service(BACKEND_ORACLE)
        self.assertIsNone(service._cosine_engine(FakeSnapshot()))


if __name__ == "__main__":
    unittest.main()
