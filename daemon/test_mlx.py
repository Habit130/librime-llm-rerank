#!/usr/bin/env python3
"""MLX exact-backend equivalence suite (Habit130/squirrel#73, AC-73-v1).

Model-free, deterministic, sandboxed: the MLX backend
(``daemon/mlx_engine.py``, ``mx.matmul`` over the canonical FP32 matrix) is
compared against the canonical stdlib oracle (``daemon/oracle.py``) on the
SAME query / facts / vectors.  Maps one-to-one onto the blocking scenarios:

  SCN-73-1  every same-key active event is scored on the MLX path; no cosine
            shortlist substitutes for the oracle's full evaluation
  SCN-73-2  per-query neighbors / event weights / candidate evidence s_c /
            final emit order match the stdlib oracle within the pinned
            tolerance (1e-6 absolute cosine; any kept-set or emit-order flip
            is an equivalence fail, never "almost")
  SCN-73-4  the MLX backend enters ``index_fingerprint`` and differs from
            the oracle and Accelerate backend fingerprints (SCN-73-4)
  SCN-73-6  MLX missing at runtime fails closed (no silent Accelerate/Python
            fallback presented as MLX)

The suite skips (not fails) when MLX is unavailable on the host, so it stays
green on non-MLX CI; on this machine MLX is required.

Never touches live facts, ~/Library/Rime, or the live daemon.
"""

import math
import os
import shutil
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
    import mlx.core  # noqa: F401
    from mlx_engine import (  # noqa: E402
        MlxCosineEngine,
        MlxError,
        build_cosine_engine,
    )
    MLX_AVAILABLE = True
except Exception:  # noqa: BLE001 - env without MLX skips the suite
    MLX_AVAILABLE = False

from test_accelerate import build_facts  # noqa: E402  (shared fixture helper)

DIM = 1024
SEED = 20260817
# Pinned equivalence tolerance (SCN-73-2): absolute cosine difference vs the
# oracle.  Measured MLX-matmul deviation at 100k x 1024 is ~3e-8, two orders
# of magnitude inside this bound.
COSINE_TOLERANCE = 1e-6


class _FixtureMatrix:
    """A deterministic FP32 matrix backing the engine, from seed vectors."""

    def __init__(self, events, dimension=DIM, seed=SEED):
        self.events = events
        self.dimension = dimension
        self.row_index = {"ev-%d" % i: i for i in range(events)}
        tmpdir = tempfile.mkdtemp(prefix="mlx-matrix-")
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


@unittest.skipUnless(MLX_AVAILABLE,
                     "MLX not available; skipping MLX equivalence suite")
class MlxEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mlx-equiv-")
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
                  engine_cls=MlxCosineEngine):
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
        self.assertEqual(oracle.same_key_active, engine.same_key_active,
                         "same-key active count must match")
        oracle_kept = [(c.event_id, c.cosine, c.weight, c.matched_candidate)
                       for c in oracle.kept]
        engine_kept = [(c.event_id, c.cosine, c.weight, c.matched_candidate)
                       for c in engine.kept]
        # SCN-73-2: identical kept-set (same events, same order) and weights.
        self.assertEqual(
            [item[0] for item in oracle_kept],
            [item[0] for item in engine_kept],
            "kept event set / order must match the oracle")
        for o_entry, e_entry in zip(oracle_kept, engine_kept):
            self.assertLessEqual(
                abs(o_entry[1] - e_entry[1]), COSINE_TOLERANCE,
                "cosine deviation exceeds the pinned tolerance")
            self.assertLessEqual(
                abs(o_entry[2] - e_entry[2]), COSINE_TOLERANCE,
                "weight deviation exceeds the pinned tolerance")
            self.assertEqual(o_entry[3], e_entry[3],
                             "matched candidate must match")
        # s_c per candidate + final emit order (by descending s, then index).
        oracle_sc = {c.index: c.s for c in oracle.candidates}
        engine_sc = {c.index: c.s for c in engine.candidates}
        for index in oracle_sc:
            self.assertLessEqual(
                abs(oracle_sc[index] - engine_sc[index]), COSINE_TOLERANCE,
                "candidate evidence s_c deviation exceeds tolerance")
        oracle_order = sorted(range(len(oracle_sc)),
                              key=lambda i: (-oracle_sc[i], i))
        engine_order = sorted(range(len(engine_sc)),
                              key=lambda i: (-engine_sc[i], i))
        self.assertEqual(oracle_order, engine_order,
                         "final emit order must match the oracle")

    # -- SCN-73-1/73-2: large same-key sets use the matmul batched path ------

    def test_large_same_key_matches_oracle(self):
        """SCN-73-1/73-2: 5000 same-key events through the matmul path."""
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

        SCN-73-1: every same-key event is still scored; the fallback is the
        oracle's own float64 cosine, so the result is exact.
        """
        events = 300
        matrix = _FixtureMatrix(events)
        extra = 3
        matrix2 = _FixtureMatrix(events + extra)
        try:
            engine = MlxCosineEngine(
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
        """SCN-73-1: a same-key event the engine cannot serve is a fault."""
        events = 400
        matrix = _FixtureMatrix(events)
        try:
            db = build_facts(os.path.join(self.root, "facts"), events)
            # An engine whose matrix covers only the first 200 events: the
            # remaining same-key events must still be scored (via vector_for)
            # or fault -- never silently dropped from the scored set.
            partial_rows = {k: v for k, v in matrix.row_index.items()
                            if v < 200}
            engine = MlxCosineEngine(
                matrix.buffer, events, matrix.dimension, partial_rows)
            reader = FactReader(db)
            query = self._query("z" * 64)

            def vector_for(event_id):
                # No fallback vector available: the engine must fault rather
                # than serve a truncated same-key set (SCN-73-1).
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

    # -- SCN-73-6: fail closed ----------------------------------------------

    def test_missing_mlx_fails_closed(self):
        """MLX unavailable at runtime raises MlxError, never a silent
        Accelerate/Python fallback."""
        import mlx_engine as _mle
        from unittest import mock
        with mock.patch.object(
                _mle, "MlxError",
                side_effect=lambda msg: MlxError(msg)) as _fake, \
                mock.patch.dict(sys.modules, {"mlx.core": None}):
            # Force the engine's lazy import path to fail by making
            # ``import mlx.core`` raise; build_cosine_engine must surface
            # MlxError, not a fallback.
            with self.assertRaises(MlxError):
                build_cosine_engine(b"", 0, 1024, {})

    # -- SCN-73-4: backend enters the fingerprint ---------------------------

    def test_fingerprint_distinguishes_backends(self):
        from compat import (ACCELERATE_BACKEND, EXACT_BACKEND, MLX_BACKEND,
                            compose_backend_fingerprint)
        exact_fp = compose_backend_fingerprint(EXACT_BACKEND)
        accelerate_fp = compose_backend_fingerprint(ACCELERATE_BACKEND)
        mlx_fp = compose_backend_fingerprint(MLX_BACKEND)
        # SCN-73-4: the MLX backend must NEVER reuse the oracle or the
        # Accelerate fingerprint; the content digest differs because the
        # backend and library/ABI version enter the payload.
        self.assertNotEqual(exact_fp, mlx_fp,
                            "MLX must not reuse the oracle fingerprint")
        self.assertNotEqual(accelerate_fp, mlx_fp,
                            "MLX must not reuse the Accelerate fingerprint")
        # And the MLX backend must not silently bind another backend's
        # library version either (that would be a fingerprint forgery).
        from compat import (ACCELERATE_LIBRARY_VERSION,
                            EXACT_LIBRARY_VERSION, compose_index_fingerprint)
        forged_oracle = compose_index_fingerprint(
            backend=MLX_BACKEND, library_version=EXACT_LIBRARY_VERSION)
        forged_accel = compose_index_fingerprint(
            backend=MLX_BACKEND, library_version=ACCELERATE_LIBRARY_VERSION)
        self.assertNotEqual(mlx_fp, forged_oracle)
        self.assertNotEqual(mlx_fp, forged_accel)

    def test_generation_build_binds_backend(self):
        """An MLX generation gets a different id and fingerprint than the
        oracle build of the same facts (SCN-73-4)."""
        from generation import build_generation
        from seed_vectors import SeedVectorProvider
        from compat import EXACT_BACKEND, MLX_BACKEND
        events = 120
        db_root = os.path.join(self.root, "facts")
        build_facts(db_root, events)
        out_exact = os.path.join(self.root, "out-exact")
        out_mlx = os.path.join(self.root, "out-mlx")
        provider = SeedVectorProvider("seed-fixture-v1:1024", SEED, DIM)
        g_exact = build_generation(db_root, provider, out_exact,
                                   retrieval_backend=EXACT_BACKEND)
        g_mlx = build_generation(db_root, provider, out_mlx,
                                 retrieval_backend=MLX_BACKEND)
        try:
            self.assertNotEqual(g_exact.generation_id, g_mlx.generation_id)
            self.assertEqual(g_exact.retrieval_backend, EXACT_BACKEND)
            self.assertEqual(g_mlx.retrieval_backend, MLX_BACKEND)
            self.assertNotEqual(g_exact.index_fingerprint,
                                g_mlx.index_fingerprint)
            # The FP32 vector file itself is identical (same facts/vectors).
            with open(os.path.join(g_exact.generation_dir,
                                   "vectors.fp32"), "rb") as a, \
                 open(os.path.join(g_mlx.generation_dir,
                                   "vectors.fp32"), "rb") as b:
                self.assertEqual(a.read(), b.read(),
                                 "FP32 vectors must be identical across "
                                 "backends")
        finally:
            g_exact.close()
            g_mlx.close()

    def test_generation_reopen_accepts_mlx_backend(self):
        """An MLX generation reopens through open_generation."""
        from generation import build_generation, open_generation
        from seed_vectors import SeedVectorProvider
        from compat import MLX_BACKEND
        events = 90
        db_root = os.path.join(self.root, "facts")
        build_facts(db_root, events)
        out = os.path.join(self.root, "out")
        provider = SeedVectorProvider("seed-fixture-v1:1024", SEED, DIM)
        g = build_generation(db_root, provider, out,
                             retrieval_backend=MLX_BACKEND)
        gen_id = g.generation_id
        g.close()
        reopened = open_generation(os.path.join(out, "generations", gen_id))
        try:
            self.assertEqual(reopened.retrieval_backend, MLX_BACKEND)
        finally:
            reopened.close()

    # -- engine direct checks ------------------------------------------------

    def test_engine_cosine_matches_oracle_single(self):
        """One event: engine cosine == oracle cosine within tolerance."""
        events = 1
        matrix = _FixtureMatrix(events)
        try:
            engine = MlxCosineEngine(
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

    # -- SCN-73-6: no silent backend switch ----------------------------------

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
        by a service configured for another (SCN-73-6: the served backend is
        bound into index_fingerprint, so a silent switch would serve under a
        forged identity)."""
        from evidence import (BACKEND_ACCELERATE, BACKEND_MLX, BACKEND_ORACLE,
                              EvidenceError)

        class FakeSnapshot:
            def retrieval_backend(self):
                return BACKEND_ORACLE  # generation built for the oracle

            def mlx_engine(self):
                raise AssertionError("must not build an engine for a "
                                     "mismatched generation")

        # Config says MLX, snapshot generation is oracle -> fault.
        service = self._make_service(BACKEND_MLX)
        with self.assertRaises(EvidenceError) as ctx:
            service._cosine_engine(FakeSnapshot())
        self.assertEqual(ctx.exception.code, "backend_mismatch")

        # Config says oracle, snapshot is MLX -> fault (never silently serve
        # the python path for an MLX fingerprint).
        class FakeSnapshotMlx:
            def retrieval_backend(self):
                return BACKEND_MLX

        service_oracle = self._make_service(BACKEND_ORACLE)
        with self.assertRaises(EvidenceError) as ctx:
            service_oracle._cosine_engine(FakeSnapshotMlx())
        self.assertEqual(ctx.exception.code, "backend_mismatch")

        # Accelerate config against an MLX generation -> fault too.
        class FakeSnapshotMlx2:
            def retrieval_backend(self):
                return BACKEND_MLX

        service_accel = self._make_service(BACKEND_ACCELERATE)
        with self.assertRaises(EvidenceError) as ctx:
            service_accel._cosine_engine(FakeSnapshotMlx2())
        self.assertEqual(ctx.exception.code, "backend_mismatch")

    def test_backend_match_serves_mlx(self):
        """Matching MLX backend builds the engine through the snapshot seam."""
        from evidence import BACKEND_MLX

        class FakeSnapshot:
            def retrieval_backend(self):
                return BACKEND_MLX

            def mlx_engine(self):
                return object()  # the engine seam resolves here

        service = self._make_service(BACKEND_MLX)
        self.assertIsNotNone(service._cosine_engine(FakeSnapshot()))


if __name__ == "__main__":
    unittest.main()
