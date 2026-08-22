#!/usr/bin/env python3
"""Tests for the model-free dedicated embedding v1 adapter."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from dedicated_embedding_benchmark import (  # noqa: E402
    V1_DIGEST,
    payload,
    run_fixture_adapter,
)
from semantic_benchmark import benchmark_manifest  # noqa: E402


class DedicatedEmbeddingBenchmarkTest(unittest.TestCase):
    def test_payload_and_digest_are_frozen(self):
        self.assertEqual("前" * 64 + "候选", payload("前" * 70, "候选"))
        self.assertEqual(V1_DIGEST, benchmark_manifest()["benchmark_digest"])

    def test_both_routes_pass_bounded_v1_cases(self):
        report = run_fixture_adapter()
        self.assertEqual(
            {"qwen3-embedding-0.6b", "bge-m3-dense-1024"},
            set(report["routes"]),
        )
        for cases in report["routes"].values():
            self.assertEqual(2, len(cases))
            self.assertTrue(all(item["passed"] for item in cases))
        self.assertEqual("not_read_or_run", report["v2"])
        self.assertEqual(2, len(report["representation_ids"]))


if __name__ == "__main__":
    unittest.main()
