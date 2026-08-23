#!/usr/bin/env python3
"""Model-free tests for the AC-111 projection and provider adapter."""

import hashlib
import json
import math
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evidence import EvidenceError, RepresentationProvider
from linear_projection import (
    INPUT_DIMENSION,
    METRIC,
    OUTPUT_DIMENSION,
    VECTOR_FORMAT,
    LinearProjection,
    ProjectionError,
    ProjectedCandidateRepresentationProvider,
    projection_metadata_with_fingerprint,
)


def make_projection(seed=7):
    rng = np.random.default_rng(seed)
    weights = rng.standard_normal(
        (OUTPUT_DIMENSION, INPUT_DIMENSION)).astype("<f4")
    digest = hashlib.sha256(weights.tobytes(order="C")).hexdigest()
    metadata = {
        "source_representation_ids": ["source-l14", "source-l21", "source-l28"],
        "training_code_digest": "code-digest",
        "snapshot_sha256": "snapshot-digest",
        "history_id": "history",
        "store_epoch": "epoch",
        "hlc_cutoff": [10, 0],
        "hyperparameters": {"test": True},
        "seed": seed,
        "split": {"policy": "test"},
        "sampling": {"policy": "test"},
        "loss": {"name": "test"},
        "regularization": {"name": "test"},
        "stop": {"policy": "test"},
        "weight_digest": digest,
        "input_dim": INPUT_DIMENSION,
        "output_dim": OUTPUT_DIMENSION,
        "vector_format": VECTOR_FORMAT,
        "metric": METRIC,
    }
    return LinearProjection(
        weights, projection_metadata_with_fingerprint(metadata))


class FakeCandidateProvider(RepresentationProvider):

    def __init__(self, identifier, offset):
        self.identifier = identifier
        self.offset = offset

    def representation_id(self):
        return self.identifier

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        del preceding_text
        raise EvidenceError("representation_fault", "candidate required")

    def query_vector_for_candidate(self, preceding_text, candidate):
        del preceding_text, candidate
        return tuple(float(self.offset + index + 1) for index in range(1024))

    def event_vector(self, event):
        return self.event_vector_for_candidate(event, event.final_selection_text)

    def event_vector_for_candidate(self, event, candidate):
        del event, candidate
        return tuple(float(self.offset + index + 1) for index in range(1024))

    def vector_dimension(self):
        return 1024


class LinearProjectionTest(unittest.TestCase):

    def test_apply_is_fixed_dimension_and_l2_normalized(self):
        projection = make_projection()
        result = projection.apply(np.ones(INPUT_DIMENSION, dtype=np.float32))
        self.assertEqual(OUTPUT_DIMENSION, len(result))
        self.assertTrue(all(math.isfinite(value) for value in result))
        self.assertAlmostEqual(1.0, math.sqrt(sum(value * value
                                                   for value in result)),
                               places=5)

    def test_wrong_input_dimension_fails_closed(self):
        with self.assertRaises(ProjectionError):
            make_projection().apply((1.0,) * (INPUT_DIMENSION - 1))

    def test_save_and_load_revalidates_identity(self):
        projection = make_projection()
        root = tempfile.mkdtemp(prefix="ac111-projection-test-")
        try:
            path = os.path.join(root, "projection.npz")
            projection.save(path)
            loaded = LinearProjection.load(path)
            self.assertEqual(projection.fingerprint, loaded.fingerprint)
            self.assertEqual(projection.weight_digest, loaded.weight_digest)
            self.assertEqual(projection.apply((1.0,) * INPUT_DIMENSION),
                             loaded.apply((1.0,) * INPUT_DIMENSION))
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_tampered_fingerprint_is_rejected(self):
        projection = make_projection()
        metadata = projection.metadata
        metadata["seed"] += 1
        root = tempfile.mkdtemp(prefix="ac111-projection-tamper-")
        try:
            path = os.path.join(root, "projection.npz")
            np.savez(path, weights=projection.weights,
                     metadata_json=np.array(json.dumps(metadata,
                                                       sort_keys=True)))
            with self.assertRaises(ProjectionError):
                LinearProjection.load(path)
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_concatenates_sources_in_declared_order(self):
        projection = make_projection()
        providers = tuple(
            FakeCandidateProvider(identifier, offset)
            for identifier, offset in zip(
                projection.metadata["source_representation_ids"], (0, 1000, 2000)))
        adapter = ProjectedCandidateRepresentationProvider(providers, projection)
        vector = adapter.query_vector_for_candidate("unused", "candidate")
        expected = projection.apply(tuple(
            value for provider in providers
            for value in provider.query_vector_for_candidate(
                "unused", "candidate")))
        reverse = projection.apply(tuple(
            value for provider in reversed(providers)
            for value in provider.query_vector_for_candidate(
                "unused", "candidate")))
        self.assertEqual(expected, vector)
        self.assertNotEqual(reverse, vector)
        self.assertEqual(OUTPUT_DIMENSION, len(vector))
        self.assertAlmostEqual(1.0, math.sqrt(sum(value * value
                                                   for value in vector)),
                               places=5)
        self.assertEqual(OUTPUT_DIMENSION, adapter.vector_dimension())
        with self.assertRaises(EvidenceError):
            adapter.query_vector("unused")

    def test_provider_rejects_non_candidate_source(self):
        projection = make_projection()

        class LegacyProvider(FakeCandidateProvider):
            def is_candidate_conditioned(self):
                return False

        providers = (LegacyProvider("source-l14", 0),
                     FakeCandidateProvider("source-l21", 0),
                     FakeCandidateProvider("source-l28", 0))
        with self.assertRaises(ProjectionError):
            ProjectedCandidateRepresentationProvider(providers, projection)


if __name__ == "__main__":
    unittest.main()
