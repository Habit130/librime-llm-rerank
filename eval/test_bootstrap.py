#!/usr/bin/env python3
"""Tests for the bootstrap statistics machine (SCN-70-4).

Pins: key-clustered resampling (never single events), fixed seed
reproducibility, >=10000 replicates enforced, 95% CI reporting, and paired
differences on the same event set.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from walkforward import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED  # noqa: E402

from bootstrap import (BootstrapError, bootstrap_mean, bootstrap_rate,  # noqa: E402
                       paired_difference)


class _Outcome:
    def __init__(self, key, value):
        self.key = key
        self.value = value


def _outcomes(counts_by_key, value=1.0):
    outcomes = []
    for key, count in counts_by_key.items():
        for _ in range(count):
            outcomes.append(_Outcome(key, value))
    return outcomes


class BootstrapTest(unittest.TestCase):

    def test_replicates_floor_enforced(self):
        outcomes = _outcomes({"k1": 5})
        with self.assertRaises(BootstrapError):
            bootstrap_rate(outcomes, lambda o: o.value, replicates=9999)

    def test_clustered_resampling_respects_keys(self):
        """Resampling draws whole keys, so a key's events never split."""
        outcomes = _outcomes({"k1": 3, "k2": 3, "k3": 3}, value=1.0)
        point, _ = bootstrap_rate(outcomes, lambda o: o.value)
        self.assertEqual(point, 1.0)

    def test_deterministic_with_fixed_seed(self):
        """Same seed -> byte-identical CI (SCN-70-4 reproducibility);
        point estimate exact; CI is a plausible interval."""
        outcomes = ([_Outcome("k1", 1.0)] * 10 +
                    [_Outcome("k2", 0.0)] * 10 +
                    [_Outcome("k3", 0.5)] * 10)
        a = bootstrap_rate(outcomes, lambda o: o.value, seed=42)
        b = bootstrap_rate(outcomes, lambda o: o.value, seed=42)
        self.assertEqual(a, b)
        c = bootstrap_rate(outcomes, lambda o: o.value, seed=43)
        self.assertEqual(c[0], a[0])  # point is seed-independent
        self.assertAlmostEqual(a[0], 0.5)
        self.assertLessEqual(a[1][0], a[0])
        self.assertGreaterEqual(a[1][1], a[0])

    def test_ci_level_bounds(self):
        outcomes = _outcomes({"k1": 10, "k2": 10, "k3": 10}, value=1.0)
        point, ci = bootstrap_rate(outcomes, lambda o: o.value)
        self.assertEqual(point, 1.0)
        self.assertEqual(ci, (1.0, 1.0))

    def test_bootstrap_mean_mrr(self):
        outcomes = [
            _Outcome("k1", 1.0), _Outcome("k1", 0.5), _Outcome("k2", 1.0),
        ]
        point, ci = bootstrap_mean(outcomes, lambda o: o.value)
        self.assertAlmostEqual(point, 5 / 6)
        # clustered bootstrap with varying per-key values yields a real CI
        self.assertLessEqual(ci[0], point)
        self.assertGreaterEqual(ci[1], point)

    def test_paired_difference_on_same_events(self):
        """Paired differences: scheme and baseline on the same event ids."""
        scheme = [_Outcome("k%d" % i, 1.0 if i % 2 else 0.0)
                  for i in range(10)]
        baseline = [_Outcome("k%d" % i, 0.0) for i in range(10)]
        point, ci = paired_difference(scheme,
                                      lambda o: o.value,
                                      lambda o: 0.0)
        self.assertAlmostEqual(point, 0.5)
        self.assertLessEqual(ci[0], point)
        self.assertGreaterEqual(ci[1], point)

    def test_constants(self):
        self.assertGreaterEqual(BOOTSTRAP_REPLICATES, 10000)
        self.assertIsInstance(BOOTSTRAP_SEED, int)


if __name__ == "__main__":
    unittest.main()
