#!/usr/bin/env python3
"""USearch ANN path tests (Habit130/squirrel#78, AC-78-v1).

Model-free: BruteForceIndex stands in for USearch so the oracle/merge,
identity, freeze-closed and passthrough contracts run without the library.
"""

import math
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from ann import (  # noqa: E402
    ANN_SEED,
    BUILD_PRESETS,
    OVERFETCH_FLOOR,
    OVERFETCH_MULTIPLIERS,
    QUERY_SEARCH_VALUES,
    USEARCH_BACKEND,
    USEARCH_DTYPE,
    USEARCH_LIBRARY_VERSION,
    USEARCH_METRIC,
    USEARCH_SERIALIZATION_ABI,
    AnnError,
    BruteForceIndex,
    compose_usearch_build_params,
    compute_ann_evidence,
    load_ann_sidecar,
    overfetch_count,
    publish_ann_sidecar,
)
from compat import (  # noqa: E402
    ACTION_NOOP,
    ACTION_REBUILD_INDEX,
    compose_backend_fingerprint,
    compose_index_fingerprint,
    plan_actions,
)
from evidence import (  # noqa: E402
    EvidenceError,
    compose_config_identity,
)
from oracle import (  # noqa: E402
    FactReader,
    OracleParams,
    OracleQuery,
    compute_evidence,
)
from test_oracle import (  # noqa: E402
    BASIS,
    FactsFixture,
    unit_vector,
)


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


class OverfetchAndIdentityTest(unittest.TestCase):

    def test_overfetch_floor_and_multipliers(self):
        self.assertEqual((2, 4, 8), OVERFETCH_MULTIPLIERS)
        self.assertEqual(32, OVERFETCH_FLOOR)
        self.assertEqual(32, overfetch_count(8, 2))
        self.assertEqual(32, overfetch_count(8, 4))
        self.assertEqual(64, overfetch_count(8, 8))
        self.assertEqual(128, overfetch_count(16, 8))
        self.assertEqual(512, overfetch_count(64, 8))

    def test_overfetch_rejects_unknown_multiplier(self):
        with self.assertRaises(AnnError) as ctx:
            overfetch_count(8, 3)
        self.assertEqual("ann_config", ctx.exception.code)

    def test_query_identity_includes_overfetch_and_query_search(self):
        params = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                              saturation_k=1.0)
        base = compose_config_identity("repr", params, 2.0)
        ann = compose_config_identity("repr", params, 2.0,
                                      overfetch=32, query_search=64)
        self.assertNotEqual(base, ann)
        self.assertIn(":overfetch=32:qs=64", ann)
        other = compose_config_identity("repr", params, 2.0,
                                        overfetch=64, query_search=64)
        self.assertNotEqual(ann, other)

    def test_exact_identity_unchanged_without_ann_fields(self):
        params = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                              saturation_k=1.0)
        self.assertEqual(
            "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=2",
            compose_config_identity("r", params, 2.0))

    def test_build_params_enter_index_fingerprint_not_query(self):
        exact = compose_index_fingerprint()
        usearch = compose_backend_fingerprint(
            USEARCH_BACKEND,
            params=compose_usearch_build_params(BUILD_PRESETS[1]))
        self.assertNotEqual(exact, usearch)
        other = compose_backend_fingerprint(
            USEARCH_BACKEND,
            params=compose_usearch_build_params(BUILD_PRESETS[0]))
        self.assertNotEqual(usearch, other)
        query_a = compose_config_identity(
            "r", DEFAULT_PARAMS, 2.0, overfetch=32, query_search=16)
        query_b = compose_config_identity(
            "r", DEFAULT_PARAMS, 2.0, overfetch=32, query_search=128)
        self.assertNotEqual(query_a, query_b)
        self.assertEqual(4, len(BUILD_PRESETS))
        self.assertEqual((16, 32, 64, 128), QUERY_SEARCH_VALUES)
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
            USEARCH_BACKEND, params={"connectivity": 16, "expansion_add": 128})
        right = compose_backend_fingerprint(
            USEARCH_BACKEND, params={"connectivity": 32, "expansion_add": 128})
        plan = plan_actions(identity(left), identity(right))
        self.assertEqual([ACTION_REBUILD_INDEX], plan["actions"])

    def test_unknown_fingerprint_refuses(self):
        with self.assertRaises(AnnError) as ctx:
            load_ann_sidecar("/no/such/dir")
        self.assertEqual("ann_index", ctx.exception.code)

    def test_usearch_constants(self):
        self.assertEqual("usearch-hnsw", USEARCH_BACKEND)
        self.assertEqual("cos", USEARCH_METRIC)
        self.assertEqual("f32", USEARCH_DTYPE)
        self.assertTrue(USEARCH_LIBRARY_VERSION.startswith("usearch-hnsw"))
        self.assertEqual("usearch-index-v1-arm64", USEARCH_SERIALIZATION_ABI)


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
        self.assertEqual([item.s for item in exact.candidates],
                         [item.s for item in ann.candidates])

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
        self.assertTrue(all(item.s == 0.0 for item in result.candidates))

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
        self.assertAlmostEqual(0.25, result.kept[0].age_factor)

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

    def test_delta_only_event_is_visible(self):
        self.fx.add_event("base", selection="你好", hlc=(1, 0))
        self.fx.add_event("delta", selection="你好", hlc=(2, 0))
        vectors = {
            "base": unit_vector(0.6),
            "delta": unit_vector(0.99),
        }
        index = BruteForceIndex(["base"], [vectors["base"]])
        query = self._query()
        params = OracleParams(tau=0.5, k_evidence=2, half_life=float("inf"),
                              saturation_k=1.0)
        result = run_ann(self.fx, params, query, vectors, index,
                         overfetch=8, delta_ids=("delta",))
        self.assertEqual(("delta", "base"),
                         tuple(item.event_id for item in result.kept))

    def test_restricted_overfetch_can_miss_oracle_k(self):
        self.fx.add_event("hot", selection="你好", hlc=(1, 0))
        self.fx.add_event("young", selection="你好", hlc=(2, 0))
        vectors = {
            "hot": unit_vector(0.99),
            "young": unit_vector(0.60),
        }
        index = BruteForceIndex(["hot"], [vectors["hot"]])
        params = OracleParams(tau=0.5, k_evidence=2, half_life=1.0,
                              saturation_k=1.0)
        query = self._query()
        exact = run_exact(self.fx, params, query, vectors)
        ann = run_ann(self.fx, params, query, vectors, index, overfetch=1)
        self.assertIn("young", [item.event_id for item in exact.kept])
        self.assertNotIn("young", [item.event_id for item in ann.kept])

    def test_cosine_top_k_is_not_ground_truth(self):
        self.fx.add_event("old_hot", selection="你好", hlc=(1, 0))
        self.fx.add_event("young_cool", selection="你好", hlc=(2, 0))
        vectors = {
            "old_hot": unit_vector(0.99),
            "young_cool": unit_vector(0.70),
        }
        index = BruteForceIndex(
            ["old_hot", "young_cool"],
            [vectors["old_hot"], vectors["young_cool"]])
        params = OracleParams(tau=0.5, k_evidence=1, half_life=1.0,
                              saturation_k=1.0)
        query = self._query()
        exact = run_exact(self.fx, params, query, vectors)
        ann = run_ann(self.fx, params, query, vectors, index, overfetch=8)
        self.assertEqual(exact.kept[0].event_id, ann.kept[0].event_id)


class AnnLifecycleTest(unittest.TestCase):

    def test_publish_restart_and_mixed_generation_refuse(self):
        ids = ["e1", "e2"]
        vectors = [unit_vector(0.9), unit_vector(0.8)]
        index = BruteForceIndex(ids, vectors)
        tmp = tempfile.mkdtemp(prefix="ann-life-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        derived = os.path.join(tmp, "derived")
        meta = {
            "backend": "brute-force",
            "metric": USEARCH_METRIC,
            "dtype": USEARCH_DTYPE,
            "dimension": 4,
            "library_version": "brute-v1",
            "serialization_abi": "brute",
            "build_params": {},
            "index_fingerprint": compose_index_fingerprint(
                backend="brute-force"),
            "generation_id": "gen-a",
            "event_count": 2,
        }
        publish_ann_sidecar(index, derived, "gen-a", meta)
        loaded, loaded_meta = load_ann_sidecar(
            os.path.join(derived, "index", "gen-a"),
            expected_fingerprint=meta["index_fingerprint"],
            expected_generation_id="gen-a")
        self.assertEqual(("e1", "e2"), loaded.event_ids())
        self.assertEqual("gen-a", loaded_meta["generation_id"])
        with self.assertRaises(AnnError) as ctx:
            load_ann_sidecar(
                os.path.join(derived, "index", "gen-a"),
                expected_generation_id="gen-b")
        self.assertEqual("ann_identity", ctx.exception.code)

    def test_corrupt_sidecar_refuses_unknown_identity(self):
        tmp = tempfile.mkdtemp(prefix="ann-corrupt-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        directory = os.path.join(tmp, "index", "g")
        os.makedirs(directory)
        with open(os.path.join(directory, "index.meta.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"backend":"mystery"}\n')
        with self.assertRaises(AnnError) as ctx:
            load_ann_sidecar(directory)
        self.assertEqual("ann_identity", ctx.exception.code)


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


if __name__ == "__main__":
    unittest.main()
