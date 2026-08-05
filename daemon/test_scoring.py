#!/usr/bin/env python3
"""Mean-token reduction tests (Habit130/squirrel#46, docs/token-attribution.md).

Pure-function and fake-logit tests: no model, no MLX, no tokenizer — CI
runnable. They assert the scoring semantics directly:
  - identical per-token log probs with different token counts give identical
    mean scores
  - single- and multi-token candidates use the same formula
  - batch padding length never enters the numerator or denominator
  - the prefix conditions the first target token; no prefix at position 0
    fails closed
  - non-finite per-token or mean values fail the whole batch
  - any candidate failure fails the whole batch (atomicity)
  - the legacy sum policy is reproduced faithfully
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from server import (
    NonFiniteTokenScoreError,
    TokenAttributionError,
    legacy_sum_scores,
    mean_token_scores,
)


class DictLp:
    """Fake lp accessor: dict[(batch, position, token_id)] -> log prob."""

    def __init__(self, values, default=-1.0):
        self.values = dict(values)
        self.default = default

    def __call__(self, batch, position, token_id):
        return self.values.get((batch, position, token_id), self.default)


class MeanTokenScoresTest(unittest.TestCase):
    def test_equal_per_token_probs_give_equal_means(self):
        # Single-token candidate: P(token 10 | prefix) = -2.5
        # Two-token candidate: same -2.5 per token.
        plans = [
            ([10], 0, 1),
            ([11, 12], 0, 2),
        ]
        prefix = {10: -2.5, 11: -2.5}
        lp = DictLp({(1, 0, 12): -2.5})
        scores, counts = mean_token_scores(
            lambda token_id: prefix[token_id], lp, plans)
        self.assertEqual([1, 2], counts)
        self.assertAlmostEqual(-2.5, scores[0])
        self.assertAlmostEqual(-2.5, scores[1])

    def test_different_lengths_same_per_token_score_same_mean(self):
        # token ids [20] vs [21, 22, 23], every log prob -1.0.
        plans = [([20], 0, 1), ([21, 22, 23], 0, 3)]
        lp = DictLp({(1, 0, 22): -1.0, (1, 1, 23): -1.0})
        scores, counts = mean_token_scores(
            lambda token_id: -1.0, lp, plans)
        self.assertEqual([1, 3], counts)
        self.assertAlmostEqual(-1.0, scores[0])
        self.assertAlmostEqual(-1.0, scores[1])

    def test_batch_padding_length_never_enters_denominator(self):
        # Candidate 2 is shorter than candidate 1; its count must be its own
        # real target count (1), not the padded batch length (3).
        plans = [([100, 101, 102], 0, 3), ([103], 0, 1)]
        lp = DictLp({(0, 0, 101): -3.0, (0, 1, 102): -3.0, (1, 0, 103): -9.0})
        prefix = {100: -3.0, 103: -9.0}
        scores, counts = mean_token_scores(
            lambda token_id: prefix[token_id], lp, plans)
        self.assertEqual([3, 1], counts)
        self.assertAlmostEqual(-3.0, scores[0])
        self.assertAlmostEqual(-9.0, scores[1])

    def test_padding_positions_are_never_read(self):
        # The fake lp has no values for padding positions; reading one would
        # produce the default -1.0 and corrupt the score.
        plans = [([1, 2], 0, 2), ([3], 0, 1)]
        lp = DictLp({(0, 0, 2): -4.0}, default=float("nan"))
        scores, counts = mean_token_scores(lambda token_id: -4.0, lp, plans)
        self.assertEqual([2, 1], counts)
        self.assertAlmostEqual(-4.0, scores[0])
        self.assertAlmostEqual(-4.0, scores[1])

    def test_first_target_token_conditioned_on_prefix(self):
        plans = [([7], 0, 1)]
        scores, _ = mean_token_scores(lambda token_id: -1.25, DictLp({}), plans)
        self.assertAlmostEqual(-1.25, scores[0])

    def test_no_prefix_at_position_zero_fails_closed(self):
        plans = [([7], 0, 1)]
        with self.assertRaises(TokenAttributionError):
            mean_token_scores(None, DictLp({}), plans)

    def test_tail_precedes_target_tokens(self):
        # target starts at position 1 (one tail token before it).
        plans = [([1, 2, 3], 1, 2)]
        lp = DictLp({(0, 0, 2): -2.0, (0, 1, 3): -2.0})
        scores, counts = mean_token_scores(None, lp, plans)
        self.assertEqual([2], counts)
        self.assertAlmostEqual(-2.0, scores[0])

    def test_non_finite_per_token_fails_whole_batch(self):
        plans = [([1, 2], 0, 2), ([3], 0, 1)]
        lp = DictLp({(0, 0, 2): float("nan")})
        with self.assertRaises(NonFiniteTokenScoreError):
            mean_token_scores(lambda token_id: -1.0, lp, plans)

    def test_non_finite_mean_fails_whole_batch(self):
        plans = [([1], 0, 1)]
        with self.assertRaises(NonFiniteTokenScoreError):
            mean_token_scores(lambda token_id: float("inf"), DictLp({}), plans)

    def test_any_candidate_failure_fails_the_whole_batch(self):
        # Candidate 2 has zero target tokens: the whole batch must fail.
        plans = [([1, 2], 0, 2), ([3], 0, 0)]
        with self.assertRaises(TokenAttributionError):
            mean_token_scores(lambda token_id: -1.0, DictLp({}), plans)

    def test_target_position_out_of_range_fails_closed(self):
        plans = [([1, 2], 1, 2)]
        with self.assertRaises(TokenAttributionError):
            mean_token_scores(None, DictLp({}), plans)


class LegacySumScoresTest(unittest.TestCase):
    def test_sum_over_all_suffix_tokens_with_prefix(self):
        ids_list = [[1, 2, 3]]
        prefix = {1: -1.0}
        lp = DictLp({(0, 0, 2): -2.0, (0, 1, 3): -3.0})
        scores = legacy_sum_scores(lambda token_id: prefix[token_id], lp, ids_list)
        self.assertAlmostEqual(-6.0, scores[0])

    def test_first_token_skipped_without_prefix(self):
        ids_list = [[1, 2, 3]]
        lp = DictLp({(0, 0, 2): -2.0, (0, 1, 3): -3.0})
        scores = legacy_sum_scores(None, lp, ids_list)
        self.assertAlmostEqual(-5.0, scores[0])

    def test_non_finite_fails_whole_batch(self):
        ids_list = [[1, 2], [3, 4]]
        lp = DictLp({(0, 0, 2): float("-inf")})
        with self.assertRaises(NonFiniteTokenScoreError):
            legacy_sum_scores(None, lp, ids_list)


if __name__ == "__main__":
    unittest.main()
