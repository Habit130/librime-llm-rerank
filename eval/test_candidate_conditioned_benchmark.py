#!/usr/bin/env python3
"""Model-free AC-109 adapter tests without the deferred v2 benchmark."""

import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
