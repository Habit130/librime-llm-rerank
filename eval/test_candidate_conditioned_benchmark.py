#!/usr/bin/env python3
"""Model-free AC-109 adapter tests without the deferred v2 benchmark."""

import os
import hashlib
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from candidate_conditioned_benchmark import (  # noqa: E402
    V1_DIGEST,
    payload,
    projected_provider_from_extractor,
    projected_provider_from_local_weights,
    route_ids,
    run_fixture_adapter,
)
from semantic_benchmark import benchmark_manifest  # noqa: E402
from linear_projection import (  # noqa: E402
    INPUT_DIMENSION,
    METRIC,
    OUTPUT_DIMENSION,
    VECTOR_FORMAT,
    LinearProjection,
    projection_metadata_with_fingerprint,
)


class CandidateConditionedAdapterTest(unittest.TestCase):
    def test_payload_is_last_64_chars_plus_candidate(self):
        self.assertEqual("前" * 64 + "候选", payload("前" * 70, "候选"))
        self.assertEqual("候选", payload("", "候选"))

    def test_v1_digest_is_unchanged(self):
        self.assertEqual(V1_DIGEST, benchmark_manifest()["benchmark_digest"])

    def test_exactly_four_routes_and_positive_path(self):
        self.assertEqual(
            (
                "candidate_l14_candidate_span_mean",
                "candidate_l21_candidate_span_mean",
                "candidate_l28_candidate_span_mean",
                "candidate_l28_last_candidate_token",
            ),
            route_ids(),
        )
        report = run_fixture_adapter()
        for route, cases in report["routes"].items():
            self.assertEqual(2, len(cases), route)
            self.assertTrue(all(item["passed"] for item in cases), route)
        self.assertEqual("not_read_or_run", report["v2"])

    def test_projection_adapter_is_optional_without_local_weights(self):
        self.assertIsNone(projected_provider_from_local_weights(None, ()))
        self.assertIsNone(projected_provider_from_extractor(None, object()))

    def test_projection_adapter_applies_a_local_matrix_to_v1_fixtures(self):
        weights = np.zeros((OUTPUT_DIMENSION, INPUT_DIMENSION), dtype="<f4")
        weights[:OUTPUT_DIMENSION, :OUTPUT_DIMENSION] = np.eye(
            OUTPUT_DIMENSION, dtype="<f4")
        metadata = {
            "source_representation_ids": ["fixture-l14", "fixture-l21",
                                           "fixture-l28"],
            "training_code_digest": "fixture-code",
            "snapshot_sha256": "fixture-snapshot",
            "history_id": "fixture-history",
            "store_epoch": "fixture-epoch",
            "hlc_cutoff": [1, 0],
            "hyperparameters": {"fixture": True},
            "seed": 1,
            "split": {"policy": "fixture"},
            "sampling": {"policy": "fixture"},
            "loss": {"name": "fixture"},
            "regularization": {"name": "fixture"},
            "stop": {"policy": "fixture"},
            "weight_digest": hashlib.sha256(
                weights.tobytes(order="C")).hexdigest(),
            "input_dim": INPUT_DIMENSION,
            "output_dim": OUTPUT_DIMENSION,
            "vector_format": VECTOR_FORMAT,
            "metric": METRIC,
        }
        root = tempfile.mkdtemp(prefix="ac111-v1-adapter-")
        try:
            path = os.path.join(root, "projection.npz")
            LinearProjection(
                weights, projection_metadata_with_fingerprint(metadata)).save(path)
            report = run_fixture_adapter(path)
            self.assertEqual(2, len(report["linear_projection"]))
            self.assertTrue(all(
                item["status"] == "ok"
                and item["vector_dimension"] == OUTPUT_DIMENSION
                and item["finite_evidence"]
                for item in report["linear_projection"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
