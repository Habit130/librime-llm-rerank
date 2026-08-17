#!/usr/bin/env python3
"""#71 capacity-fixture seed-vector provider tests.

Pins the deterministic rules of the #71 fixtures (SCN-71-1): the seed
provider is a pure function of (seed, kind, key); the same input yields the
same unit vector; different seeds yield different vectors; the dimension is
configurable; malformed config fails closed.  These rules are what make the
100k latency fixtures reproducible across machines and across the #72/#73
and #78/#79 challenge paths.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from seed_vectors import (  # noqa: E402
    DEFAULT_DIMENSION,
    PROVIDER_KIND,
    VECTOR_RULE,
    SeedVectorProvider,
    build_seed_provider_from_config,
)
from evidence import EvidenceError  # noqa: E402


def _norm2(vector):
    return math.sqrt(sum(value * value for value in vector))


class SeedVectorProviderTest(unittest.TestCase):

    def test_vectors_are_unit_norm_and_deterministic(self):
        provider = SeedVectorProvider("repr-v1", 20260817, 16)
        event = type("Event", (), {"event_id": "ev-1"})()
        v1 = provider.event_vector(event)
        v2 = provider.event_vector(event)
        self.assertEqual(v1, v2)
        self.assertAlmostEqual(_norm2(v1), 1.0, places=6)
        q1 = provider.query_vector("abc")
        q2 = provider.query_vector("abc")
        self.assertEqual(q1, q2)
        self.assertAlmostEqual(_norm2(q1), 1.0, places=6)
        self.assertEqual(len(v1), 16)
        self.assertEqual(len(q1), 16)

    def test_different_keys_and_kinds_differ(self):
        provider = SeedVectorProvider("repr-v1", 20260817, 16)
        event_a = type("Event", (), {"event_id": "ev-1"})()
        event_b = type("Event", (), {"event_id": "ev-2"})()
        self.assertNotEqual(provider.event_vector(event_a),
                            provider.event_vector(event_b))
        self.assertNotEqual(provider.query_vector("abc"),
                            provider.event_vector(event_a))

    def test_different_seeds_differ(self):
        p1 = SeedVectorProvider("repr-v1", 1, 16)
        p2 = SeedVectorProvider("repr-v1", 2, 16)
        event = type("Event", (), {"event_id": "ev-1"})()
        self.assertNotEqual(p1.event_vector(event),
                            p2.event_vector(event))

    def test_default_dimension_is_1024(self):
        provider = SeedVectorProvider("repr-v1", 20260817)
        self.assertEqual(provider.vector_dimension(), 1024)

    def test_identity_and_rule(self):
        provider = SeedVectorProvider("repr-v1", 20260817, 1024)
        self.assertEqual(provider.representation_id(), "repr-v1")
        summary = provider.config_summary()
        self.assertEqual(summary["provider_kind"], PROVIDER_KIND)
        self.assertEqual(summary["vector_rule"], VECTOR_RULE)
        self.assertEqual(summary["seed"], 20260817)
        self.assertEqual(summary["vector_dimension"], 1024)

    def test_build_from_config(self):
        provider = build_seed_provider_from_config({
            "representation_id": "repr-v1",
            "seed": 20260817,
            "vector_dimension": 32,
        })
        self.assertEqual(provider.vector_dimension(), 32)
        self.assertEqual(provider.representation_id(), "repr-v1")

    def test_build_from_config_overrides(self):
        provider = build_seed_provider_from_config(
            {"representation_id": "repr-v1", "seed": 20260817},
            representation_id="repr-v2", seed=42)
        self.assertEqual(provider.representation_id(), "repr-v2")
        self.assertEqual(provider._seed, 42)

    def test_build_from_config_missing_seed_fails_closed(self):
        with self.assertRaises(EvidenceError):
            build_seed_provider_from_config({"representation_id": "repr-v1"})

    def test_build_from_config_bad_dimension_fails_closed(self):
        with self.assertRaises(EvidenceError):
            build_seed_provider_from_config({
                "representation_id": "repr-v1",
                "seed": 20260817,
                "vector_dimension": 0,
            })


if __name__ == "__main__":
    unittest.main()
