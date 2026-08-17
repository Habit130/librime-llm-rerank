#!/usr/bin/env python3
"""Tests for the τ calibration protocol (SCN-70-5).

Pins: τ only from the dev prefix; the query-level hard-negative cosine
distribution; the >=200-query gate with the spec-consistent
"not_calibratable" state (no invented τ); and the fixed quantile set
Q95/Q97.5/Q99/Q99.5.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from oracle import OracleParams  # noqa: E402

from fixture_facts import (SyntheticFacts, axis_query_vectors,  # noqa: E402
                           fixture_provider, selection_vectors)
from walkforward import (DEV_PREFIX_RATIO, FrozenFacts,  # noqa: E402
                         MIN_HARD_NEGATIVE_QUERIES, TAU_QUANTILES,
                         VectorTable, WalkForwardReplay)
from calibration import (calibrate_tau, dev_prefix,  # noqa: E402
                         nearest_rank_quantile)


def _make_replay(event_count, key_count, same_selection_share=0.5,
                 cosine=0.95):
    """Many events across several keys; alternate selections per key."""
    facts = SyntheticFacts()
    query_vectors = {}
    event_vectors = {}
    for key_index in range(key_count):
        canonical = "key%d" % key_index
        query_vectors["ctx-%d" % key_index] = (1.0, 0.0, 0.0, 0.0)
        event_vectors[("luna_pinyin", canonical, "选%d" % key_index)] = \
            (cosine, (1 - cosine * cosine) ** 0.5, 0.0, 0.0)
        event_vectors[("luna_pinyin", canonical, "另%d" % key_index)] = \
            (0.0, 1.0, 0.0, 0.0)
    for index in range(event_count):
        key_index = index % key_count
        canonical = "key%d" % key_index
        selection = ("选%d" % key_index
                     if (index // key_count) % 2 == 0
                     else "另%d" % key_index)
        facts.add_event("e%d" % index, canonical,
                        "ctx-%d" % key_index, selection,
                        ("选%d" % key_index, "另%d" % key_index),
                        (1000 + index, 0))
    provider = fixture_provider(query_vectors, event_vectors)
    frozen = FrozenFacts(facts.db_path)
    vectors = VectorTable(frozen.events(), provider)
    replay = WalkForwardReplay(frozen, vectors)
    return facts, frozen, replay


class TauCalibrationTest(unittest.TestCase):

    def test_dev_prefix_ratio(self):
        targets = list(range(100))
        prefix = dev_prefix(targets)
        self.assertEqual(len(prefix), 70)
        self.assertEqual(prefix, list(range(70)))

    def test_quantile_function(self):
        values = sorted(float(i) for i in range(100))
        self.assertEqual(nearest_rank_quantile(values, 0.95), 94.0)
        self.assertEqual(nearest_rank_quantile(values, 0.975), 97.0)
        self.assertEqual(nearest_rank_quantile(values, 0.99), 98.0)
        self.assertEqual(nearest_rank_quantile(values, 0.995), 99.0)

    def test_not_calibratable_below_200(self):
        """Fewer than 200 hard-negative queries -> no τ invented."""
        facts, frozen, replay = _make_replay(
            event_count=30, key_count=3)
        try:
            status = calibrate_tau(replay)
            self.assertEqual(status["state"], "not_calibratable")
            self.assertLess(status["queries"], MIN_HARD_NEGATIVE_QUERIES)
            self.assertNotIn("quantiles", status)
        finally:
            frozen.close()
            facts.close()

    def test_calibratable_above_200(self):
        """>=200 queries -> τ candidates are exactly the four quantiles."""
        facts, frozen, replay = _make_replay(
            event_count=400, key_count=8)
        try:
            status = calibrate_tau(replay)
            self.assertEqual(status["state"], "calibratable")
            self.assertGreaterEqual(status["queries"],
                                    MIN_HARD_NEGATIVE_QUERIES)
            self.assertEqual(
                set(status["quantiles"]), {str(q) for q in TAU_QUANTILES})
            # the hard-negative distribution: each query's max cosine to a
            # different-selection history is the configured cosine
            for quantile in status["quantiles"].values():
                self.assertAlmostEqual(quantile, 0.95)
        finally:
            frozen.close()
            facts.close()

    def test_hard_negative_only_different_selection(self):
        """Queries without a different-selection history contribute nothing
        to the distribution (they are not counted as hard-negative
        queries)."""
        facts = SyntheticFacts()
        try:
            # single key, all events select the same candidate: no
            # hard-negative history ever.
            for index in range(250):
                facts.add_event("e%d" % index, "wo", "ctx", "我",
                                ("我", "握"), (1000 + index, 0))
            provider = fixture_provider(axis_query_vectors(), {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            frozen = FrozenFacts(facts.db_path)
            try:
                vectors = VectorTable(frozen.events(), provider)
                replay = WalkForwardReplay(frozen, vectors)
                status = calibrate_tau(replay)
                self.assertEqual(status["state"], "not_calibratable")
                self.assertEqual(status["queries"], 0)
            finally:
                frozen.close()
        finally:
            facts.close()


if __name__ == "__main__":
    unittest.main()
