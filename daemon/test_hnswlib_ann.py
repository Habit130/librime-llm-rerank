#!/usr/bin/env python3
"""hnswlib ANN path tests (Habit130/squirrel#79, AC-79-v1)."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from ann import (  # noqa: E402
    ANN_SEED,
    HNSWLIB_BACKEND,
    HNSWLIB_BUILD_PRESETS,
    HNSWLIB_DTYPE,
    HNSWLIB_LIBRARY_VERSION,
    HNSWLIB_METRIC,
    HNSWLIB_QUERY_SEARCH_VALUES,
    HNSWLIB_SERIALIZATION_ABI,
    OVERFETCH_FLOOR,
    OVERFETCH_MULTIPLIERS,
    AnnError,
    BruteForceIndex,
    compose_hnswlib_build_params,
    compute_ann_evidence,
    load_ann_sidecar,
    overfetch_count,
)
from compat import (  # noqa: E402
    ACTION_NOOP,
    ACTION_REBUILD_INDEX,
    compose_backend_fingerprint,
    compose_index_fingerprint,
    plan_actions,
)
from oracle import (  # noqa: E402
    FactReader,
    OracleParams,
    OracleQuery,
    compute_evidence,
)
from test_oracle import BASIS, FactsFixture, unit_vector  # noqa: E402


DEFAULT_PARAMS = OracleParams(tau=0.5, k_evidence=2, half_life=32.0,
                              saturation_k=1.0)


def run_ann(fixture, params, query, vectors, index, overfetch=32,
            delta_ids=None, query_search=None):
    reader = FactReader(fixture.db_path)
    try:
        return compute_ann_evidence(
            reader, params, query, lambda event_id: vectors[event_id],
            index, overfetch, query_search=query_search, delta_ids=delta_ids)
    finally:
        reader.close()


def run_exact(fixture, params, query, vectors):
    reader = FactReader(fixture.db_path)
    try:
        return compute_evidence(
            reader, params, query, lambda event_id: vectors[event_id])
    finally:
        reader.close()


class HnswlibIdentityTest(unittest.TestCase):

    def test_overfetch_floor_and_multipliers(self):
        self.assertEqual((2, 4, 8), OVERFETCH_MULTIPLIERS)
        self.assertEqual(32, OVERFETCH_FLOOR)
        self.assertEqual(32, overfetch_count(8, 2))
        self.assertEqual(64, overfetch_count(8, 8))

    def test_query_identity_includes_overfetch_and_query_search(self):
        from evidence import compose_config_identity as compose
        params = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                              saturation_k=1.0)
        base = compose("repr", params, 2.0)
        ann = compose("repr", params, 2.0, overfetch=32, query_search=64)
        self.assertNotEqual(base, ann)
        self.assertIn(":overfetch=32:qs=64", ann)

    def test_build_params_enter_index_fingerprint_not_query(self):
        exact = compose_index_fingerprint()
        hnsw = compose_backend_fingerprint(
            HNSWLIB_BACKEND,
            params=compose_hnswlib_build_params(HNSWLIB_BUILD_PRESETS[1]))
        self.assertNotEqual(exact, hnsw)
        other = compose_backend_fingerprint(
            HNSWLIB_BACKEND,
            params=compose_hnswlib_build_params(HNSWLIB_BUILD_PRESETS[0]))
        self.assertNotEqual(hnsw, other)
        from evidence import compose_config_identity as compose
        query_a = compose("r", DEFAULT_PARAMS, 2.0, overfetch=32,
                          query_search=32)
        query_b = compose("r", DEFAULT_PARAMS, 2.0, overfetch=32,
                          query_search=256)
        self.assertNotEqual(query_a, query_b)
        self.assertEqual(4, len(HNSWLIB_BUILD_PRESETS))
        self.assertEqual((32, 64, 128, 256), HNSWLIB_QUERY_SEARCH_VALUES)
        self.assertEqual(20260817, ANN_SEED)

    def test_query_param_change_is_matrix_noop(self):
        from compat import LAYER_INDEX

        def identity(fp=None):
            return {
                "store_epoch": "e",
                "fact_schema_version": "1",
                "representation_id": "r",
                "vector_format_version": "fp32-row-major-little-endian",
                "projection_version": "p",
                LAYER_INDEX: fp or compose_index_fingerprint(),
            }

        plan = plan_actions(identity(), identity())
        self.assertEqual([ACTION_NOOP], plan["actions"])

    def test_build_param_change_is_rebuild_index(self):
        from compat import LAYER_INDEX

        def identity(fp):
            return {
                "store_epoch": "e",
                "fact_schema_version": "1",
                "representation_id": "r",
                "vector_format_version": "fp32-row-major-little-endian",
                "projection_version": "p",
                LAYER_INDEX: fp,
            }

        left = compose_backend_fingerprint(
            HNSWLIB_BACKEND, params={"M": 16, "ef_construction": 200})
        right = compose_backend_fingerprint(
            HNSWLIB_BACKEND, params={"M": 32, "ef_construction": 200})
        plan = plan_actions(identity(left), identity(right))
        self.assertEqual([ACTION_REBUILD_INDEX], plan["actions"])

    def test_unknown_fingerprint_refuses(self):
        with self.assertRaises(AnnError) as ctx:
            load_ann_sidecar("/no/such/dir")
        self.assertEqual("ann_index", ctx.exception.code)

    def test_hnswlib_constants(self):
        self.assertEqual("hnswlib-hnsw", HNSWLIB_BACKEND)
        self.assertEqual("cosine", HNSWLIB_METRIC)
        self.assertEqual("f32", HNSWLIB_DTYPE)
        self.assertTrue(HNSWLIB_LIBRARY_VERSION.startswith("hnswlib-hnsw"))
        self.assertEqual("hnswlib-index-v1-arm64", HNSWLIB_SERIALIZATION_ABI)

    def test_usearch_sidecar_is_not_hnswlib(self):
        tmp = tempfile.mkdtemp(prefix="ann-usearch-meta-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        directory = os.path.join(tmp, "index", "g")
        os.makedirs(directory)
        with open(os.path.join(directory, "index.meta.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"backend":"usearch-hnsw"}\n')
        with self.assertRaises(AnnError) as ctx:
            load_ann_sidecar(directory)
        self.assertEqual("ann_identity", ctx.exception.code)


class AnnOracleSemanticsTest(unittest.TestCase):

    def setUp(self):
        self.fx = FactsFixture()
        self.addCleanup(self.fx.close)

    def _query(self, candidates=("你好", "呢耗"), vector=BASIS, **kwargs):
        return OracleQuery(
            schema_id="luna_pinyin",
            canonical_segment_input="nihao",
            candidates=candidates,
            query_vector=vector,
            **kwargs)

    def test_full_overfetch_matches_exact_oracle(self):
        self.fx.add_event("e1", selection="你好", hlc=(1, 0))
        self.fx.add_event("e2", selection="你好", hlc=(2, 0))
        self.fx.add_event("e3", selection="呢耗", hlc=(3, 0))
        vectors = {
            "e1": unit_vector(0.95),
            "e2": unit_vector(0.90),
            "e3": unit_vector(0.80),
        }
        index = BruteForceIndex(list(vectors), list(vectors.values()))
        query = self._query()
        exact = run_exact(self.fx, DEFAULT_PARAMS, query, vectors)
        ann = run_ann(self.fx, DEFAULT_PARAMS, query, vectors, index,
                      overfetch=32)
        self.assertEqual([item.event_id for item in exact.kept],
                         [item.event_id for item in ann.kept])

    def test_cross_key_hits_are_dropped(self):
        self.fx.add_event("same", selection="你好", segment_input="nihao",
                          hlc=(1, 0))
        self.fx.add_event("other", selection="你好", segment_input="world",
                          hlc=(2, 0))
        vectors = {
            "same": unit_vector(0.7),
            "other": unit_vector(0.99),
        }
        index = BruteForceIndex(["other", "same"],
                                [vectors["other"], vectors["same"]])
        query = self._query()
        result = run_ann(self.fx, DEFAULT_PARAMS, query, vectors, index,
                         overfetch=8)
        self.assertEqual(("same",), tuple(item.event_id for item in result.kept))

    def test_candidate_mismatch_does_not_contribute(self):
        self.fx.add_event("e1", selection="其他", hlc=(1, 0))
        vectors = {"e1": unit_vector(0.99)}
        index = BruteForceIndex(["e1"], [vectors["e1"]])
        query = OracleQuery(
            schema_id="luna_pinyin",
            canonical_segment_input="nihao",
            candidates=("你好", "呢耗"),
            query_vector=BASIS,
            candidate_query_vectors=(BASIS, BASIS),
        )
        result = run_ann(self.fx, DEFAULT_PARAMS, query, vectors, index,
                         overfetch=8)
        self.assertEqual((), tuple(item.event_id for item in result.kept))

    def test_zero_evidence_is_success(self):
        query = self._query()
        index = BruteForceIndex([], [])
        result = run_ann(self.fx, DEFAULT_PARAMS, query, {}, index,
                         overfetch=8)
        self.assertEqual(0, result.same_key_active)
        self.assertEqual((), result.kept)

    def test_retraction_leaves_evidence_and_age_clock(self):
        self.fx.add_event("e1", selection="你好", commit_id="c1", hlc=(1, 0))
        self.fx.add_event("e2", selection="你好", commit_id="c2", hlc=(2, 0))
        self.fx.add_retraction("r1", "c1", (3, 0))
        vectors = {"e1": unit_vector(0.99), "e2": unit_vector(0.90)}
        index = BruteForceIndex(["e1", "e2"], [vectors["e1"], vectors["e2"]])
        query = self._query()
        exact = run_exact(self.fx, DEFAULT_PARAMS, query, vectors)
        ann = run_ann(self.fx, DEFAULT_PARAMS, query, vectors, index,
                      overfetch=8)
        self.assertEqual([item.event_id for item in exact.kept],
                         [item.event_id for item in ann.kept])
        self.assertNotIn("e1", [item.event_id for item in ann.kept])

    def test_decay_uses_full_same_key_age_clock(self):
        self.fx.add_event("old", selection="你好", hlc=(1, 0))
        self.fx.add_event("mid", selection="你好", hlc=(2, 0))
        self.fx.add_event("new", selection="你好", hlc=(3, 0))
        vectors = {
            "old": unit_vector(0.99),
            "mid": unit_vector(0.51),
            "new": unit_vector(0.51),
        }
        index = BruteForceIndex(["old"], [vectors["old"]])
        query = self._query()
        params = OracleParams(tau=0.5, k_evidence=8, half_life=1.0,
                              saturation_k=1.0)
        result = run_ann(self.fx, params, query, vectors, index, overfetch=8)
        self.assertEqual(1, len(result.kept))
        self.assertEqual("old", result.kept[0].event_id)
        self.assertEqual(2, result.kept[0].usage_age)

    def test_same_score_tie_follows_exact_hlc_rule(self):
        self.fx.add_event("a", selection="你好", hlc=(1, 0))
        self.fx.add_event("b", selection="你好", hlc=(2, 0))
        vec = unit_vector(0.9)
        vectors = {"a": vec, "b": vec}
        index = BruteForceIndex(["b", "a"], [vec, vec])
        params = OracleParams(tau=0.5, k_evidence=1, half_life=float("inf"),
                              saturation_k=1.0)
        query = self._query()
        exact = run_exact(self.fx, params, query, vectors)
        ann = run_ann(self.fx, params, query, vectors, index, overfetch=8)
        self.assertEqual(exact.kept[0].event_id, ann.kept[0].event_id)

    def test_duplicate_base_delta_prefers_delta(self):
        self.fx.add_event("e1", selection="你好", hlc=(1, 0))
        base_vec = unit_vector(0.6)
        delta_vec = unit_vector(0.95)
        vectors = {"e1": delta_vec}
        index = BruteForceIndex(["e1"], [base_vec])
        query = self._query()
        result = run_ann(self.fx, DEFAULT_PARAMS, query, vectors, index,
                         overfetch=8, delta_ids=("e1",))
        self.assertEqual(("e1",), tuple(item.event_id for item in result.kept))
        self.assertGreater(result.kept[0].cosine, 0.9)


class AnnPassthroughTest(unittest.TestCase):

    def test_missing_index_is_fault_not_exact_fallback(self):
        fx = FactsFixture()
        self.addCleanup(fx.close)
        fx.add_event("e1", selection="你好", hlc=(1, 0))
        query = OracleQuery(
            schema_id="luna_pinyin",
            canonical_segment_input="nihao",
            candidates=("你好",),
            query_vector=BASIS)
        with self.assertRaises(AnnError) as ctx:
            run_ann(fx, DEFAULT_PARAMS, query, {"e1": unit_vector(0.9)},
                    None, overfetch=8)
        self.assertEqual("ann_index", ctx.exception.code)

    def test_search_fault_does_not_return_exact_kept(self):
        class Boom(BruteForceIndex):
            def search(self, query_vector, count, query_search=None):
                raise RuntimeError("index exploded")

        fx = FactsFixture()
        self.addCleanup(fx.close)
        fx.add_event("e1", selection="你好", hlc=(1, 0))
        vectors = {"e1": unit_vector(0.9)}
        query = OracleQuery(
            schema_id="luna_pinyin",
            canonical_segment_input="nihao",
            candidates=("你好",),
            query_vector=BASIS)
        with self.assertRaises(AnnError) as ctx:
            run_ann(fx, DEFAULT_PARAMS, query, vectors,
                    Boom(["e1"], [vectors["e1"]]), overfetch=8)
        self.assertEqual("ann_index", ctx.exception.code)


class HnswlibLifecycleStubTest(unittest.TestCase):

    def test_mystery_backend_refuses(self):
        tmp = tempfile.mkdtemp(prefix="ann-hnsw-corrupt-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        directory = os.path.join(tmp, "index", "g")
        os.makedirs(directory)
        with open(os.path.join(directory, "index.meta.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"backend":"mystery"}\n')
        with self.assertRaises(AnnError) as ctx:
            load_ann_sidecar(directory)
        self.assertEqual("ann_identity", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
