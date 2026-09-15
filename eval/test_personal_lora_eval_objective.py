#!/usr/bin/env python3
"""Frozen objective, policy and verdict tests for #178.

These tests pin the completion-only scoring math against an independent
numpy reference, the saved-competition ranking and tie-break rules, the
frozen S1–S4 policy arithmetic, the validation-only selection order and the
``benefit``/``no_benefit``/``inconclusive`` verdict boundaries. They use the
pinned MLX runtime for the batch scorer but no model and no private data.
"""

import os
import sys
import unittest

import numpy as np

try:
    import mlx.core as mx
except Exception:  # pragma: no cover - model-free gates have no mlx
    mx = None

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_eval as ple  # noqa: E402
import personal_lora_pilot as plp  # noqa: E402

VOCAB = 32


class TinyEncoding(object):

    def __init__(self, ids, offsets):
        self.ids = ids
        self.offsets = offsets


class TinyBackendTokenizer(object):

    def encode(self, text):
        ids = [(ord(character) - ord("a")) % (VOCAB - 1) + 1
               for character in text]
        offsets = [(index, index + 1) for index in range(len(text))]
        return TinyEncoding(ids, offsets)


class TinyInnerTokenizer(object):
    backend_tokenizer = TinyBackendTokenizer()


class TinyTokenizerWrapper(object):
    _tokenizer = TinyInnerTokenizer()
    add_bos_token = False
    bos_token_id = None
    vocab_size = VOCAB


class BoundaryBackendTokenizer(object):
    """Maps ``prompt + completion`` to a boundary-spanning token layout."""

    layout = {}

    def encode(self, text):
        ids, offsets = self.layout[text]
        return TinyEncoding(list(ids), list(offsets))


class BoundaryInnerTokenizer(object):
    backend_tokenizer = BoundaryBackendTokenizer()


class BoundaryTokenizerWrapper(object):
    _tokenizer = BoundaryInnerTokenizer()
    add_bos_token = False
    bos_token_id = None


def tiny_tokenize(text):
    return plp.make_offsets_tokenizer(TinyTokenizerWrapper())(text)


def numpy_logits(ids):
    base = np.arange(1, VOCAB + 1, dtype=np.float64).reshape(1, 1, VOCAB)
    return ids[..., None].astype(np.float64) * 0.25 + base * 0.1


def mlx_logits(ids):
    base = mx.arange(1, VOCAB + 1, dtype=mx.float32).reshape(1, 1, VOCAB)
    return ids[..., None].astype(mx.float32) * 0.25 + base * 0.1


def reference_logsum(ids, prompt_side):
    ids = np.asarray(ids, dtype=np.int64)
    logits = numpy_logits(ids[None, :-1])
    shifted = logits - logits.max(axis=-1, keepdims=True)
    log_probs = shifted - np.log(np.exp(shifted).sum(axis=-1, keepdims=True))
    targets = ids[1:]
    picked = np.take_along_axis(log_probs[0], targets[:, None],
                                axis=-1)[:, 0]
    positions = np.arange(1, len(ids))
    mask = positions >= max(1, prompt_side)
    return float((picked * mask).sum()), int(mask.sum())


@unittest.skipIf(mx is None, "the mlx runtime is not installed here")
class BatchScoringTest(unittest.TestCase):

    def score(self, examples):
        return ple.mlx_score_batch({"mx": mx}, mlx_logits, examples)

    def test_matches_the_numpy_reference_and_padding(self):
        prompt_a = "abc"
        prompt_b = "abcdefgh"
        examples = [
            plp.build_completion_example(tiny_tokenize, prompt_a, "de"),
            plp.build_completion_example(tiny_tokenize, prompt_b, "x"),
        ]
        values = self.score(examples)
        self.assertEqual(len(values), 2)
        for example, (logsum, tokens, spanning) in zip(examples, values):
            expected, expected_tokens = reference_logsum(
                example.input_ids, example.prompt_side)
            self.assertAlmostEqual(logsum, expected, places=4)
            self.assertEqual(tokens, expected_tokens)
            self.assertEqual(spanning, 0)
        self.assertNotEqual(examples[0].total_tokens,
                            examples[1].total_tokens)

    def test_boundary_spanning_token_stays_prompt_side(self):
        BoundaryBackendTokenizer.layout = {
            "abc": ([1, 2, 3], [(0, 2), (1, 3), (3, 4)]),
        }
        wrapper = BoundaryTokenizerWrapper()
        tokenize = plp.make_offsets_tokenizer(wrapper)
        example = plp.build_completion_example(tokenize, "ab", "c")
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.spanning_tokens, 1)
        self.assertEqual(example.target_count(), 1)
        values = self.score([example])
        expected, expected_tokens = reference_logsum(example.input_ids,
                                                     example.prompt_side)
        self.assertAlmostEqual(values[0][0], expected, places=4)
        self.assertEqual(values[0][1], expected_tokens)
        self.assertEqual(values[0][2], 1)

    def test_consumed_completion_has_no_completion_tokens(self):
        BoundaryBackendTokenizer.layout = {
            "abc": ([1, 2], [(0, 1), (1, 3)]),
        }
        wrapper = BoundaryTokenizerWrapper()
        tokenize = plp.make_offsets_tokenizer(wrapper)
        example = plp.build_completion_example(tokenize, "ab", "c")
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.spanning_tokens, 1)
        self.assertEqual(example.target_count(), 0)
        values = self.score([example])
        self.assertEqual(values[0], (0.0, 0, 1))

    def test_single_token_examples_are_unscored(self):
        example = plp.build_completion_example(tiny_tokenize, "", "a")
        self.assertEqual(example.total_tokens, 1)
        values = self.score([example])
        self.assertEqual(values[0][1], 0)
        empty = self.score([])
        self.assertEqual(empty, [])


class RankingTest(unittest.TestCase):

    def test_tie_break_keeps_the_saved_order(self):
        groups = [ple._fake_group(0, target_pos=0)]
        scores = [[(-1.0, 1, 0), (-1.0, 1, 0), (-2.0, 1, 0)]]
        system = ple.build_system_eval(groups, scores, "S1")
        self.assertEqual(system["per_group"][0]["rank"], 1)
        self.assertEqual(system["per_group"][0]["top1"], 1)
        groups = [ple._fake_group(0, target_pos=1)]
        system = ple.build_system_eval(groups, scores, "S1")
        self.assertEqual(system["per_group"][0]["rank"], 2)

    def test_s2_prefers_the_longer_normalized_completion(self):
        groups = [ple._fake_group(0, target_pos=1)]
        scores = [[(-3.0, 1, 0), (-4.0, 2, 0)]]
        s1 = ple.build_system_eval(groups, scores, "S1")
        s2 = ple.build_system_eval(groups, scores, "S2")
        self.assertEqual(s1["per_group"][0]["rank"], 1)
        self.assertEqual(s2["per_group"][0]["rank"], 2)

    def test_mispromotion_and_target_logloss(self):
        groups = [ple._fake_group(0, target_pos=0, display_rank=1),
                  ple._fake_group(1, target_pos=1, display_rank=2)]
        rime = ple.build_rime_eval(groups)
        scores = [
            [(-1.0, 1, 0), (-2.0, 1, 0)],
            [(-2.0, 2, 0), (-2.0, 1, 0)],
        ]
        system = ple.build_system_eval(groups, scores, "S1")
        aggregate = ple.aggregate(system, groups, rime)
        self.assertEqual(aggregate["ranked_rows"], 2)
        self.assertEqual(aggregate["top1"], 1)
        self.assertEqual(aggregate["mispromotion"], 0)
        self.assertAlmostEqual(aggregate["target_logloss"], 1.5)
        mispromoting = [
            [(-2.0, 1, 0), (-1.0, 1, 0)],
            [(-2.0, 2, 0), (-2.0, 1, 0)],
        ]
        system = ple.build_system_eval(groups, mispromoting, "S1")
        aggregate = ple.aggregate(system, groups, rime)
        self.assertEqual(aggregate["mispromotion"], 1)
        self.assertAlmostEqual(aggregate["mrr"], 0.5)

    def test_rime_reference_uses_the_recorded_display_position(self):
        groups = [ple._fake_group(0, display_rank=1, display_page=1),
                  ple._fake_group(1, display_rank=5, display_page=1),
                  ple._fake_group(2, display_rank=1, display_page=2)]
        rime = ple.build_rime_eval(groups)
        self.assertEqual(rime["per_group"][0]["top1"], 1)
        self.assertEqual(rime["per_group"][1]["top1"], 0)
        self.assertEqual(rime["per_group"][2]["top1"], 0)
        self.assertAlmostEqual(rime["per_group"][1]["mrr"], 0.2)
        self.assertAlmostEqual(rime["per_group"][2]["mrr"], 0.0)


class PolicyTest(unittest.TestCase):

    def test_s1_and_s2_arithmetic_and_unscored_candidates(self):
        self.assertAlmostEqual(ple.apply_policy("S1", -3.0, 2), -1.5)
        self.assertAlmostEqual(ple.apply_policy("S2", -3.0, 2), -3.0)
        self.assertIsNone(ple.apply_policy("S1", -3.0, 0))
        self.assertIsNone(ple.apply_policy("S2", -3.0, 0))
        with self.assertRaises(ple.EvalError):
            ple.apply_policy("S3", -3.0, 2)

    def test_weight_precondition(self):
        unavailable = ple.weight_precondition(
            {"candidate_columns": ["event_id", "merge_order", "text"]}, 7)
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["policies"], {"S3": "n/a", "S4": "n/a"})
        self.assertEqual(ple.available_policies(unavailable), ["S1", "S2"])
        available = ple.weight_precondition(
            {"candidate_columns": ["event_id", "merge_order", "weight"]}, 7)
        self.assertTrue(available["available"])
        self.assertEqual(ple.available_policies(available),
                         ["S1", "S2", "S3", "S4"])

    def test_selection_prefers_top1_then_mrr_then_order(self):
        stats = {
            "S1": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
            "S2": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
            "S3": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
            "S4": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
        }
        self.assertEqual(ple.select_policy(stats, ple.POLICIES), "S1")
        stats["S2"]["mrr"] = 0.6
        self.assertEqual(ple.select_policy(stats, ple.POLICIES), "S2")
        stats["S4"]["top1"] = 6
        self.assertEqual(ple.select_policy(stats, ple.POLICIES), "S4")
        stats["S3"]["top1"] = 6
        stats["S3"]["mrr"] = 0.7
        self.assertEqual(ple.select_policy(stats, ple.POLICIES), "S3")

    def test_lock_refusals(self):
        binding = {"tool_sha256": "t", "model_composite_sha256": "m"}
        stats = {
            "S1": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
            "S2": {"top1": 4, "mrr": 0.4, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
            "S3": "n/a",
            "S4": "n/a",
        }
        good = {
            "schema": ple.LOCK_SCHEMA, "tool": ple.TOOL_NAME,
            "tool_version": ple.TOOL_VERSION, "tool_sha256": "t",
            "binding": binding, "selected_policy": "S1",
            "available_policies": ["S1", "S2"], "test_sha256": "c",
            "policy_stats": stats,
        }
        ple.assert_lock(good, binding, "c")
        with self.assertRaises(ple.LockError):
            ple.assert_lock(dict(good, selected_policy="S2"), binding, "c")
        with self.assertRaises(ple.LockError):
            ple.assert_lock({"schema": ple.LOCK_SCHEMA}, binding, "c")
        for mutation in (
            {"schema": "other"},
            {"tool_sha256": "x"},
            {"binding": {"tool_sha256": "t"}},
            {"selected_policy": "S9"},
            {"available_policies": ["S2"]},
            {"policy_stats": {}},
        ):
            broken = dict(good)
            broken.update(mutation)
            with self.assertRaises(ple.LockError):
                ple.assert_lock(broken, binding, "c")
        with self.assertRaises(ple.LockError):
            ple.assert_lock(good, binding, "d")

    def test_selection_conflict_detection(self):
        locked = {
            "selected_policy": "S1",
            "policy_stats": {
                "S1": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                       "omitted_rows": 0, "omission_rate": 0.0},
                "S3": "n/a",
            },
        }
        same = {
            "selected_policy": "S1",
            "policy_stats": {
                "S1": {"top1": 5, "mrr": 0.5, "ranked_rows": 10,
                       "omitted_rows": 0, "omission_rate": 0.0},
                "S3": "n/a",
            },
        }
        self.assertIsNone(ple.selection_matches(locked, same))
        changed = dict(same, selected_policy="S2")
        self.assertIsNotNone(ple.selection_matches(locked, changed))
        metric = {"selected_policy": "S1", "policy_stats": {
            "S1": {"top1": 6, "mrr": 0.5, "ranked_rows": 10,
                   "omitted_rows": 0, "omission_rate": 0.0},
            "S3": "n/a"}}
        self.assertIsNotNone(ple.selection_matches(locked, metric))


class VerdictTest(unittest.TestCase):

    def test_inconclusive_boundaries_via_the_frozen_constants(self):
        self.assertIsNotNone(ple.VERDICT_MIN_DENOMINATOR)
        self.assertEqual(ple.verdict_for(240, 199, 1, 1, 2)[0],
                         "inconclusive")
        self.assertEqual(ple.verdict_for(240, 200, 1, 1, 2)[0], "benefit")
        self.assertEqual(ple.verdict_for(1000, 801, 1, 1, 2)[0], "benefit")
        self.assertEqual(ple.verdict_for(1000, 799, 1, 1, 2)[0],
                         "inconclusive")

    def test_benefit_requires_strict_improvement_over_both_baselines(self):
        self.assertEqual(ple.verdict_for(500, 400, 10, 20, 21)[0], "benefit")
        self.assertEqual(ple.verdict_for(500, 400, 10, 21, 21)[0],
                         "no_benefit")
        self.assertEqual(ple.verdict_for(500, 400, 21, 10, 21)[0],
                         "no_benefit")
        self.assertEqual(ple.verdict_for(500, 400, 20, 20, 20)[0],
                         "no_benefit")

    def test_evidence_records_the_denominator_and_omissions(self):
        verdict, evidence = ple.verdict_for(500, 450, 10, 20, 21)
        self.assertEqual(verdict, "benefit")
        self.assertEqual(evidence["ranking_eligible"], 500)
        self.assertEqual(evidence["scored_denominator"], 450)
        self.assertEqual(evidence["omitted_rows"], 50)
        self.assertAlmostEqual(evidence["omission_rate"], 0.1)


if __name__ == "__main__":
    unittest.main()
