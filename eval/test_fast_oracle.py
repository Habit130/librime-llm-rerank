#!/usr/bin/env python3
"""Bit-faithfulness test: FastEvidence vs the canonical oracle.

The engine's vectorized evidence path must reproduce the canonical #59
oracle's per-candidate s (and total mass) to floating-point precision over
a grid of tau / H / K / k and diverse same-key history layouts.  If the
fast path ever drifts, this gate fails and the walk-forward metrics cannot
be trusted.
"""

import os
import random
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from oracle import (OracleParams, OracleQuery, compute_evidence)  # noqa: E402

from walkforward import FastEvidence  # noqa: E402


def _unit(cosine, dimension=4):
    import math
    r = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return tuple([cosine, r] + [0.0] * (dimension - 2))


class _Reader:
    """Minimal FactReader stand-in feeding events to the canonical oracle."""

    def __init__(self, events):
        self._events = tuple(events)

    def read_active_events(self, as_of=None):
        return list(self._events)

    def default_as_of(self):
        return (999999, 0)


class _Event:
    def __init__(self, event_id, key, selection, cosine, hlc):
        self.event_id = event_id
        self.commit_id = "c-" + event_id
        self.schema_id = "s"
        self.category = "word"
        self.canonical_segment_input = key
        self.final_selection_text = selection
        self.preceding_text = ""
        self.hlc = hlc
        self.key = ("s", "word", key)
        self._cosine = cosine

    def vector(self):
        return _unit(self._cosine)


class FastOracleEquivalenceTest(unittest.TestCase):

    def _run_case(self, events, query_cosine, candidates, params):
        # canonical oracle path
        reader = _Reader(events)
        query = OracleQuery(
            schema_id="s", category="word",
            canonical_segment_input=events[0].canonical_segment_input,
            candidates=list(candidates),
            query_vector=_unit(query_cosine))
        canonical = compute_evidence(
            reader, params, query,
            lambda event_id: next(e.vector() for e in events
                                  if e.event_id == event_id))
        s_canonical = canonical.s_for

        # fast path
        fast = FastEvidence(params.tau, params.k_evidence,
                            params.half_life, params.saturation_k)
        history = sorted(events, key=lambda e: e.hlc)
        usage_ages = list(range(len(history) - 1, -1, -1))
        selection_texts = [e.final_selection_text for e in history]
        event_vectors = [e.vector() for e in history]
        s_fast = fast.run(_unit(query_cosine), event_vectors, usage_ages,
                          list(candidates), selection_texts)
        for index in range(len(candidates)):
            want = s_canonical(index)
            have = s_fast[index]
            if want is None:
                self.assertEqual(have, 0.0)
            else:
                self.assertAlmostEqual(have, want, places=12)

    def test_equivalence_across_params(self):
        rng = random.Random(7)
        selections = ["a", "b", "c"]
        for iteration in range(12):
            key = "k%d" % (iteration % 3)
            count = rng.randint(1, 8)
            events = []
            for index in range(count):
                events.append(_Event(
                    "e%d-%d" % (iteration, index), key,
                    selections[rng.randrange(len(selections))],
                    rng.uniform(0.0, 1.0), (index, 0)))
            tau = rng.choice([0.0, 0.3, 0.6, 0.8])
            k_evidence = rng.choice([2, 4, 8])
            half_life = rng.choice([8, 32, float("inf")])
            saturation_k = rng.choice([1, 3, 7])
            params = OracleParams(tau=tau, k_evidence=k_evidence,
                                  half_life=half_life,
                                  saturation_k=saturation_k)
            self._run_case(events, rng.uniform(0.0, 1.0),
                           list(selections), params)

    def test_equivalence_all_same_selection(self):
        """When every history event chooses the same candidate, both paths
        give that candidate the full mass and the others zero."""
        events = [_Event("a0", "k", "x", 0.9, (0, 0)),
                  _Event("a1", "k", "x", 0.95, (1, 0)),
                  _Event("a2", "k", "x", 0.98, (2, 0))]
        params = OracleParams(tau=0.0, k_evidence=2, half_life=float("inf"),
                              saturation_k=1.0)
        self._run_case(events, 0.9, ["x", "y"], params)

    def test_equivalence_threshold_kills_low_cosine(self):
        events = [_Event("a0", "k", "x", 0.2, (0, 0)),
                  _Event("a1", "k", "x", 0.3, (1, 0))]
        params = OracleParams(tau=0.9, k_evidence=8, half_life=float("inf"),
                              saturation_k=1.0)
        self._run_case(events, 0.4, ["x", "y"], params)
        self.assertEqual(params.tau, 0.9)


if __name__ == "__main__":
    unittest.main()
