#!/usr/bin/env python3
"""Token attribution seam tests (Habit130/squirrel#46, docs/token-attribution.md).

Deterministic tests against the real Qwen tokenizer — no model weights, no
MLX. They assert the attribution rules directly:
  - context-tail tokens never enter candidate token counts
  - BPE seams are stable and attributable (with an empty tail, the candidate
    gets exactly its own tokens)
  - a BPE token straddling the tail/candidate boundary fails closed
  - Qwen byte-level BPE fallback pairs (rare characters) stay whole on
    either side of the boundary
  - single- and multi-token candidates
  - empty candidates and lossy tokenization fail closed

Runs under `python -m unittest discover -s daemon -p 'test_*.py'` and
standalone: `daemon/.venv/bin/python daemon/test_attribution.py`.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from server import (
    MODEL_PATH,
    TokenAttributionError,
    candidate_scoring_plan,
)

TAIL_CHARS = 4


def load_tokenizer():
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(MODEL_PATH)


class CandidateScoringPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokenizer = load_tokenizer()

    def test_tail_tokens_excluded_from_candidate_count(self):
        tail = "今天天气"
        candidate = "攻击"
        ids, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, tail, candidate)
        tail_ids = self.tokenizer.encode(tail, add_special_tokens=False)
        candidate_ids = self.tokenizer.encode(candidate, add_special_tokens=False)
        self.assertEqual(len(tail_ids), target_start)
        self.assertEqual(len(candidate_ids), target_count)
        self.assertEqual(tail_ids + candidate_ids, ids)

    def test_single_token_candidate(self):
        _, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, "", "攻击")
        self.assertEqual(0, target_start)
        self.assertEqual(1, target_count)

    def test_multi_token_candidate(self):
        ids, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, "", "数字123混合")
        self.assertEqual(0, target_start)
        self.assertEqual(len(ids), target_count)
        self.assertGreater(target_count, 1)

    def test_empty_candidate_fails_closed(self):
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(self.tokenizer, "发起", "")

    def test_seam_boundary_is_stable_without_straddle(self):
        # "今天" + "天气" tokenizes as two 2-char tokens; the boundary must
        # fall exactly between them (BPE seam stable/attributable).
        ids, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, "今天", "天气")
        self.assertEqual(1, target_start)
        self.assertEqual(1, target_count)
        self.assertEqual(2, len(ids))

    def test_bpe_token_straddling_boundary_fails_closed(self):
        # "今" + "天" merges into one BPE token spanning the boundary.
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(self.tokenizer, "今", "天")

    def test_straddle_across_compound_token_fails_closed(self):
        # tail "攻" + candidate "击" merge into the single token 攻击.
        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(self.tokenizer, "攻", "击")

    def test_byte_fallback_pair_stays_whole_on_candidate_side(self):
        # 匑 is a rare char tokenized as a byte-level fallback pair
        # [13465, 239] with unreliable offset mappings; the whole pair must
        # be attributed to the candidate.
        ids, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, "", "匑")
        self.assertEqual(0, target_start)
        self.assertEqual(2, target_count)
        self.assertEqual(2, len(ids))

    def test_byte_fallback_pair_stays_whole_on_tail_side(self):
        # The pair must stay on the tail side when it belongs to the tail.
        ids, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, "匑", "击")
        self.assertEqual(2, target_start)
        self.assertEqual(1, target_count)
        self.assertEqual("击", self.tokenizer.decode(ids[target_start:]))

    def test_four_char_tail_split_never_leaks_into_candidate(self):
        # context longer than TAIL_CHARS: tail = last 4 chars.
        context = "今天天气很好"
        tail = context[-TAIL_CHARS:]
        self.assertEqual("天气很好", tail)
        _, target_start, target_count = candidate_scoring_plan(
            self.tokenizer, tail, "攻击")
        tail_ids = self.tokenizer.encode(tail, add_special_tokens=False)
        self.assertEqual(len(tail_ids), target_start)
        self.assertEqual(1, target_count)

    def test_lossy_tokenization_fails_closed(self):
        class LossyTokenizer:
            def encode(self, text, add_special_tokens=False):
                return [1, 2]

            def decode(self, ids):
                return "unrelated text"

        with self.assertRaises(TokenAttributionError):
            candidate_scoring_plan(LossyTokenizer(), "今天", "天气")


class AttributionInvariantSmokeTest(unittest.TestCase):
    """Real-tokenizer seam cases mirroring test_tokenizer.py's corpus."""

    @classmethod
    def setUpClass(cls):
        cls.tokenizer = load_tokenizer()

    def test_no_candidate_loses_all_its_tokens(self):
        cases = [
            ("发起", "攻击"),
            ("发起", "公鸡"),
            ("今天天气很好", "攻击"),
            ("我们今天去公园散步", "你好"),
            ("短", "攻击"),
            ("ab", "攻击"),
            ("发起。", "攻击"),
            ("你好，世界！", "攻击"),
            ("数字123混合", "测试"),
            ("很长的上文内容包含很多汉字用来测试前缀缓存的正确性", "候选"),
            ("标点，符号。测试！", "结果"),
            ("", "攻击"),
            ("abc", "攻击"),
            ("一二三四五六七八九十", "甲"),
            ("匑", "击"),
            ("公", "匑"),
        ]
        for context, candidate in cases:
            with self.subTest(context=context, candidate=candidate):
                tail = context[-TAIL_CHARS:]
                try:
                    ids, target_start, target_count = candidate_scoring_plan(
                        self.tokenizer, tail, candidate)
                except TokenAttributionError:
                    # Fail-closed is legitimate only when the seam is
                    # genuinely non-compositional (a BPE merge across the
                    # boundary). If tokenization respects the boundary but
                    # attribution still failed, that is a bug.
                    full = tail + candidate
                    tail_ids = self.tokenizer.encode(tail, add_special_tokens=False)
                    full_ids = self.tokenizer.encode(full, add_special_tokens=False)
                    self.assertNotEqual(tail_ids, full_ids[: len(tail_ids)])
                    continue
                self.assertGreater(target_count, 0)
                self.assertGreaterEqual(len(ids), target_start + target_count)
                # reconstructed boundary must be exact
                self.assertEqual(
                    tail, self.tokenizer.decode(ids[:target_start]))


if __name__ == "__main__":
    unittest.main()
