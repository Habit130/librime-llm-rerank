#!/usr/bin/env python3
"""Model-free token attribution contract tests
(Habit130/squirrel#46, docs/token-attribution.md).

Pure-function tests with a fake tokenizer: no transformers, no MLX, no model
files — runnable in a clean Python environment. They pin the attribution
contract of `candidate_scoring_plan`:
  - context-tail tokens never enter candidate token counts
  - a BPE token straddling the tail/candidate boundary fails closed
  - byte-level BPE fallback pairs stay whole on either side of the boundary
  - single- and multi-token candidates
  - empty candidates and lossy tokenization fail closed
  - the candidate suffix must decode back to the candidate text (round-2
    acceptance: no implicit decoder-composability assumption)

Real-Qwen seam coverage (straddle / single-multi token / byte fallback
against the actual tokenizer) lives in `daemon/integration_tokenizer.py` and
is run explicitly.

Runs under the default model-free gate:
  `python -m unittest discover -s daemon -p 'test_*.py'`
and standalone: `python3 daemon/test_attribution.py`.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from server import (
    TokenAttributionError,
    candidate_scoring_plan,
)


class FakeTokenizer:
    """Deterministic fake tokenizer: encode text -> ids, decode ids -> text.

    `decode_map` keys are tuples of ids; any lookup outside the map raises,
    so a test fails loudly if the attribution code asks for something the
    scenario did not anticipate.
    """

    def __init__(self, encode_map, decode_map):
        self.encode_map = encode_map
        self.decode_map = decode_map

    def encode(self, text, add_special_tokens=False):
        if text not in self.encode_map:
            raise AssertionError(f"unexpected encode input {text!r}")
        return list(self.encode_map[text])

    def decode(self, ids):
        key = tuple(ids)
        if key not in self.decode_map:
            raise AssertionError(f"unexpected decode input {key!r}")
        return self.decode_map[key]


# Scenario: tail "今天天气" (ids 1,2) + candidate "攻击" (id 3). The
# reconstruction loop probes every prefix k, so every prefix id sequence must
# map to a text in decode_map.
CLEAN_SPLIT = FakeTokenizer(
    encode_map={"今天天气攻击": [1, 2, 3]},
    decode_map={
        (1, 2, 3): "今天天气攻击",
        (1, 2): "今天天气",
        (1,): "今",
        (3,): "攻击",
    },
)


class CandidateScoringPlanTest(unittest.TestCase):
    def test_tail_tokens_excluded_from_candidate_count(self):
        ids, target_start, target_count = candidate_scoring_plan(
            CLEAN_SPLIT, "今天天气", "攻击")
        self.assertEqual([1, 2, 3], ids)
        self.assertEqual(2, target_start)
        self.assertEqual(1, target_count)

    def test_multi_token_candidate_with_empty_tail(self):
        tok = FakeTokenizer(
            encode_map={"数字123混合": [1, 2, 3, 4]},
            decode_map={(1, 2, 3, 4): "数字123混合"},
        )
        ids, target_start, target_count = candidate_scoring_plan(
            tok, "", "数字123混合")
        self.assertEqual(0, target_start)
        self.assertEqual(4, target_count)

    def test_single_token_candidate_with_empty_tail(self):
        tok = FakeTokenizer(
            encode_map={"攻击": [7]},
            decode_map={(7,): "攻击"},
        )
        _, target_start, target_count = candidate_scoring_plan(tok, "", "攻击")
        self.assertEqual(0, target_start)
        self.assertEqual(1, target_count)

    def test_empty_candidate_fails_closed(self):
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(CLEAN_SPLIT, "今天天气", "")

    def test_bpe_token_straddling_boundary_fails_closed(self):
        # "今" + "天" merge into one token that spans the boundary; no
        # prefix of the ids decodes to exactly the tail.
        tok = FakeTokenizer(
            encode_map={"今天": [4]},
            decode_map={(4,): "今天"},
        )
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(tok, "今", "天")

    def test_byte_fallback_pair_stays_whole_on_candidate_side(self):
        # Rare char 匑 tokenizes as two ids (a byte-level fallback pair);
        # both must be attributed to the candidate with an empty tail.
        tok = FakeTokenizer(
            encode_map={"匑": [5, 6]},
            decode_map={(5, 6): "匑"},
        )
        ids, target_start, target_count = candidate_scoring_plan(tok, "", "匑")
        self.assertEqual(0, target_start)
        self.assertEqual(2, target_count)
        self.assertEqual([5, 6], ids)

    def test_byte_fallback_pair_stays_whole_on_tail_side(self):
        tok = FakeTokenizer(
            encode_map={"匑击": [5, 6, 7]},
            decode_map={
                (5, 6, 7): "匑击",
                (5, 6): "匑",
                (5,): "\ufffd",  # half of the fallback pair
                (7,): "击",
            },
        )
        ids, target_start, target_count = candidate_scoring_plan(tok, "匑", "击")
        self.assertEqual(2, target_start)
        self.assertEqual(1, target_count)
        self.assertEqual((7,), tuple(ids[target_start:]))

    def test_lossy_tokenization_fails_closed(self):
        tok = FakeTokenizer(
            encode_map={"今天天气攻击": [1, 2, 3]},
            decode_map={(1, 2, 3): "unrelated text"},
        )
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(tok, "今天天气", "攻击")

    def test_candidate_suffix_mismatch_fails_closed(self):
        # Round-2 acceptance: full decode and prefix decode are correct but
        # the suffix does not decode back to the candidate — the request
        # must fail closed instead of trusting decoder composability.
        tok = FakeTokenizer(
            encode_map={"今天天气攻击": [1, 2, 3]},
            decode_map={
                (1, 2, 3): "今天天气攻击",
                (1, 2): "今天天气",
                (1,): "今",
                (3,): "攻",  # != candidate "攻击"
            },
        )
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(tok, "今天天气", "攻击")

    def test_suffix_mismatch_with_empty_tail_fails_closed(self):
        tok = FakeTokenizer(
            encode_map={"攻击": [3]},
            decode_map={(3,): "攻"},
        )
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(tok, "", "攻击")

    def test_unexpected_tokenizer_lookup_fails_loudly(self):
        # A decode lookup outside the scenario map raises AssertionError
        # rather than silently succeeding — the attribution code may not
        # query beyond the boundaries it is expected to.
        tok = FakeTokenizer(
            encode_map={"今天天气攻击": [1, 2, 3]},
            decode_map={
                (1, 2, 3): "今天天气攻击",
                (1, 2): "今天天气",
                (1,): "今",
                # no (3,) entry — the suffix query must fail loudly
            },
        )
        with self.assertRaises(AssertionError):
            candidate_scoring_plan(tok, "今天天气", "攻击")


if __name__ == "__main__":
    unittest.main()
