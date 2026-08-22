#!/usr/bin/env python3
"""Model-free contract tests for the two dedicated embedding routes."""

import json
import os
import shutil
import tempfile
import types
import unittest

import sys

sys.path.insert(0, os.path.dirname(__file__))

from embeddings import (
    BGE_M3_EMBEDDING_ROUTE,
    EMBEDDING_OUTPUT_DIMENSION,
    EMBEDDING_VECTOR_FORMAT,
    EmbeddingError,
    EmbeddingFixtureRepresentationProvider,
    EmbeddingIdentityError,
    EmbeddingInferenceError,
    EmbeddingLoadError,
    ModelProcessConflictError,
    QWEN3_EMBEDDING_ROUTE,
    QWEN3_QUERY_INSTRUCTION,
    Qwen3EmbeddingAdapter,
    BGEM3EmbeddingAdapter,
    _reset_model_registry_for_tests,
    embedding_fixture_vector,
    embedding_representation_id,
    fixture_embedding_identity,
)
from representations import candidate_conditioned_payload


def rows(*vectors):
    return [list(vector) for vector in vectors]


class FakeTokenizer:
    def __init__(self, token_count=2):
        self.calls = []
        self.token_count = token_count

    def __call__(self, text, return_tensors, add_special_tokens):
        self.calls.append((text, return_tensors, add_special_tokens))
        return {
            "input_ids": [[1] * self.token_count],
            "attention_mask": [[1] * self.token_count],
        }


class FakeModel:
    def __init__(self, hidden_states):
        self.config = types.SimpleNamespace(hidden_size=EMBEDDING_OUTPUT_DIMENSION)
        self.hidden_states = hidden_states
        self.eval_count = 0

    def eval(self):
        self.eval_count += 1

    def __call__(self, **_encoded):
        return types.SimpleNamespace(last_hidden_state=self.hidden_states)


class EmbeddingRouteTest(unittest.TestCase):
    def test_only_two_routes_are_frozen(self):
        from embeddings import embedding_routes

        self.assertEqual(
            ("qwen3-embedding-0.6b", "bge-m3-dense-1024"),
            tuple(route.route_id for route in embedding_routes()),
        )
        self.assertEqual(QWEN3_QUERY_INSTRUCTION,
                         QWEN3_EMBEDDING_ROUTE.instruction)
        self.assertEqual("none", BGE_M3_EMBEDDING_ROUTE.instruction)
        self.assertEqual("dense-mean", BGE_M3_EMBEDDING_ROUTE.pooling)

    def test_mixed_route_semantics_are_rejected(self):
        from embeddings import EmbeddingRoute

        with self.assertRaises(EmbeddingIdentityError):
            EmbeddingRoute(
                route_id="qwen3-embedding-0.6b",
                adapter="bge-m3",
                instruction="none",
                pooling="dense-mean",
                model_name="BGE-M3",
            )

    def test_identity_binds_all_embedding_components(self):
        identity = fixture_embedding_identity(QWEN3_EMBEDDING_ROUTE)
        identifier = embedding_representation_id(QWEN3_EMBEDDING_ROUTE,
                                                  identity)
        for component in (
                "payload=candidate-conditioned-concat-v1",
                "serialization=last64-preceding-plus-candidate",
                "model=fixture-model-qwen3-embedding-0.6b",
                "tokenizer=fixture-tokenizer-qwen3-embedding-0.6b",
                "adapter=qwen3",
                "instruction=" + QWEN3_QUERY_INSTRUCTION,
                "dim=1024", "format=" + EMBEDDING_VECTOR_FORMAT,
                "metric=cosine", "torch@fixture", "transformers@fixture"):
            self.assertIn(component, identifier)

    def test_route_identity_changes_between_models(self):
        qwen = embedding_representation_id(
            QWEN3_EMBEDDING_ROUTE,
            fixture_embedding_identity(QWEN3_EMBEDDING_ROUTE),
        )
        bge = embedding_representation_id(
            BGE_M3_EMBEDDING_ROUTE,
            fixture_embedding_identity(BGE_M3_EMBEDDING_ROUTE),
        )
        self.assertNotEqual(qwen, bge)

    def test_fixture_requires_1024_dimensions(self):
        identity = fixture_embedding_identity(QWEN3_EMBEDDING_ROUTE)
        with self.assertRaises(EmbeddingError):
            EmbeddingFixtureRepresentationProvider(
                QWEN3_EMBEDDING_ROUTE, identity,
                {("上文", "候选"): (1.0, 0.0)},
                {},
            )


class AdapterTest(unittest.TestCase):
    def setUp(self):
        _reset_model_registry_for_tests()

    def tearDown(self):
        _reset_model_registry_for_tests()

    def make_model(self, values, token_count=2, model_type="qwen3"):
        tokenizer = FakeTokenizer(token_count)
        model = FakeModel(values)
        model.config.model_type = model_type
        return model, tokenizer, lambda: (model, tokenizer)

    def test_qwen_query_instruction_and_document_payload(self):
        axis = embedding_fixture_vector(0)
        model, tokenizer, loader = self.make_model(rows(axis, axis))
        adapter = Qwen3EmbeddingAdapter(
            identity=fixture_embedding_identity(QWEN3_EMBEDDING_ROUTE),
            loader=loader,
        )
        query = adapter.query("前" * 70, "候选")
        document = adapter.document("前" * 70, "候选")
        payload = candidate_conditioned_payload("前" * 70, "候选")
        self.assertEqual(EMBEDDING_OUTPUT_DIMENSION, len(query))
        self.assertEqual(EMBEDDING_OUTPUT_DIMENSION, len(document))
        self.assertEqual(QWEN3_QUERY_INSTRUCTION + "\n" + payload,
                         tokenizer.calls[0][0])
        self.assertEqual(payload, tokenizer.calls[1][0])
        self.assertFalse(tokenizer.calls[0][2])
        self.assertFalse(tokenizer.calls[1][2])
        self.assertEqual(1, model.eval_count if hasattr(model, "eval_count")
                         else 0)

    def test_bge_query_and_document_have_no_instruction_and_use_dense_mean(self):
        first = embedding_fixture_vector(0)
        second = embedding_fixture_vector(1)
        model, tokenizer, loader = self.make_model(
            rows(first, second), model_type="xlm-roberta")
        adapter = BGEM3EmbeddingAdapter(
            identity=fixture_embedding_identity(BGE_M3_EMBEDDING_ROUTE),
            loader=loader,
        )
        vector = adapter.query("上文", "候选")
        adapter.document("上文", "候选")
        payload = candidate_conditioned_payload("上文", "候选")
        self.assertEqual(payload, tokenizer.calls[0][0])
        self.assertEqual(payload, tokenizer.calls[1][0])
        self.assertAlmostEqual(2 ** -0.5, vector[0], places=6)
        self.assertAlmostEqual(2 ** -0.5, vector[1], places=6)
        self.assertEqual(EMBEDDING_OUTPUT_DIMENSION, len(vector))

    def test_second_different_heavyweight_model_is_rejected(self):
        axis = embedding_fixture_vector(0)
        _model, _tokenizer, loader = self.make_model(rows(axis, axis))
        first = Qwen3EmbeddingAdapter(
            identity=fixture_embedding_identity(QWEN3_EMBEDDING_ROUTE),
            loader=loader,
        )
        first.query("上文", "候选")
        other = BGEM3EmbeddingAdapter(
            identity=fixture_embedding_identity(BGE_M3_EMBEDDING_ROUTE),
            loader=loader,
        )
        with self.assertRaises(ModelProcessConflictError):
            other.query("上文", "候选")

    def test_loader_fault_never_returns_a_vector(self):
        for adapter_type, route in (
                (Qwen3EmbeddingAdapter, QWEN3_EMBEDDING_ROUTE),
                (BGEM3EmbeddingAdapter, BGE_M3_EMBEDDING_ROUTE)):
            with self.subTest(route=route.route_id):
                _reset_model_registry_for_tests()

                def fail():
                    raise RuntimeError("weights unavailable")

                adapter = adapter_type(
                    identity=fixture_embedding_identity(route), loader=fail)
                with self.assertRaises(EmbeddingLoadError):
                    adapter.query("上文", "候选")

    def test_dirty_forward_never_returns_a_vector(self):
        for adapter_type, route, model_type in (
                (Qwen3EmbeddingAdapter, QWEN3_EMBEDDING_ROUTE, "qwen3"),
                (BGEM3EmbeddingAdapter, BGE_M3_EMBEDDING_ROUTE,
                 "xlm-roberta")):
            with self.subTest(route=route.route_id):
                _reset_model_registry_for_tests()
                dirty = list(embedding_fixture_vector(0))
                dirty[0] = float("nan")
                _model, _tokenizer, loader = self.make_model(
                    rows(dirty, dirty), model_type=model_type)
                adapter = adapter_type(
                    identity=fixture_embedding_identity(route),
                    loader=loader,
                )
                with self.assertRaises(EmbeddingInferenceError):
                    adapter.query("上文", "候选")


class IdentityFaultTest(unittest.TestCase):
    def setUp(self):
        _reset_model_registry_for_tests()
        self.root = tempfile.mkdtemp(prefix="embedding-identity-")
        with open(os.path.join(self.root, "config.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"hidden_size": 1024}, handle)
        with open(os.path.join(self.root, "tokenizer.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("fixture")

    def tearDown(self):
        _reset_model_registry_for_tests()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_changed_model_files_fail_closed_before_forward(self):
        from embeddings import build_embedding_identity
        from embeddings import embedding_dependency_versions

        identity = build_embedding_identity(
            self.root, QWEN3_EMBEDDING_ROUTE,
            dependency_versions=embedding_dependency_versions(),
        )
        model = FakeModel(rows(embedding_fixture_vector(0),
                               embedding_fixture_vector(0)))
        model.config.model_type = "qwen3"
        tokenizer = FakeTokenizer()
        adapter = Qwen3EmbeddingAdapter(
            model_path=self.root,
            identity=identity,
            loader=lambda: (model, tokenizer),
        )
        with open(os.path.join(self.root, "config.json"), "a",
                  encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaises(EmbeddingIdentityError):
            adapter.query("上文", "候选")
        self.assertFalse(tokenizer.calls)


if __name__ == "__main__":
    unittest.main()
