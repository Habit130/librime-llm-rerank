#!/usr/bin/env python3
"""Objective, batching, planning and estimate tests for the #176 pilot.

Fixtures are synthetic; the real tokenizer and the real dataset are never
needed here. These tests pin the frozen serialization semantics: one raw
``prompt + completion`` tokenizer call, completion-only loss, no chat or
synthetic EOS material, and a boundary-spanning token charged to the prompt
side with an explicit count.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_pilot as plp  # noqa: E402


def greedy_tokenizer(vocabulary, bos_id=None):
    calls = []

    def tokenize(text):
        calls.append(text)
        ids = []
        offsets = []
        if bos_id is not None:
            ids.append(bos_id)
            offsets.append(None)
        position = 0
        while position < len(text):
            match = None
            for width in range(min(8, len(text) - position), 0, -1):
                candidate = text[position:position + width]
                if candidate in vocabulary:
                    match = (vocabulary[candidate], width)
                    break
            if match is None:
                raise AssertionError("no fixture token at %d" % position)
            ids.append(match[0])
            offsets.append((position, position + match[1]))
            position += match[1]
        return ids, offsets

    return tokenize, calls


class ObjectiveTest(unittest.TestCase):

    def test_raw_concat_calls_tokenizer_once_on_prompt_plus_completion(self):
        tokenize, calls = greedy_tokenizer({"a": 1, "b": 2, "c": 3, "d": 4})
        example = plp.build_completion_example(tokenize, "ab", "cd")
        self.assertEqual(calls, ["abcd"])
        self.assertEqual(example.input_ids, [1, 2, 3, 4])
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.target_count(), 2)
        self.assertEqual(example.spanning_tokens, 0)

    def test_no_chat_wrapper_or_synthetic_eos_is_ever_added(self):
        tokenize, calls = greedy_tokenizer({"a": 1, "b": 2})
        example = plp.build_completion_example(tokenize, "a", "b")
        self.assertEqual(calls, ["ab"])
        self.assertEqual(example.total_tokens, 2)
        self.assertNotIn(151645, example.input_ids)
        self.assertNotIn(151643, example.input_ids)

    def test_completion_only_targets_exclude_every_prompt_token(self):
        tokenize, _ = greedy_tokenizer({"a": 1, "b": 2, "c": 3, "d": 4})
        example = plp.build_completion_example(tokenize, "ab", "cd")
        rows, lengths, _width = plp.batch_rows([example], [0])
        targets = plp.target_positions(lengths)[0]
        self.assertEqual(targets, [2, 3])

    def test_boundary_spanning_token_is_charged_to_prompt_side(self):
        tokenize, _ = greedy_tokenizer(
            {"a": 1, "b": 2, "c": 3, "d": 4, "bcd": 7})
        example = plp.build_completion_example(tokenize, "ab", "cd")
        self.assertEqual(example.input_ids, [1, 7])
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.spanning_tokens, 1)
        self.assertEqual(example.target_count(), 0)
        self.assertFalse(example.trainable())

    def test_boundary_spanning_token_is_never_charged_to_loss(self):
        tokenize, _ = greedy_tokenizer(
            {"a": 1, "b": 2, "c": 3, "d": 4, "bcd": 7})
        example = plp.build_completion_example(tokenize, "ab", "cd")
        _rows, lengths, _width = plp.batch_rows([example], [0])
        self.assertEqual(plp.target_positions(lengths)[0], [])

    def test_partial_spanning_leaves_later_completion_tokens_trainable(self):
        tokenize, _ = greedy_tokenizer(
            {"a": 1, "b": 2, "c": 3, "d": 4, "bc": 5})
        example = plp.build_completion_example(tokenize, "ab", "cd")
        self.assertEqual(example.input_ids, [1, 5, 4])
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.spanning_tokens, 1)
        self.assertEqual(example.target_count(), 1)

    def test_bos_is_input_only_and_charged_to_prompt_side(self):
        tokenize, _ = greedy_tokenizer({"a": 1, "b": 2}, bos_id=99)
        example = plp.build_completion_example(tokenize, "a", "b")
        self.assertEqual(example.input_ids, [99, 1, 2])
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.target_count(), 1)
        _rows, lengths, _width = plp.batch_rows([example], [0])
        self.assertEqual(plp.target_positions(lengths)[0], [2])

    def test_empty_prompt_first_token_is_never_a_target(self):
        tokenize, _ = greedy_tokenizer({"a": 1, "b": 2})
        example = plp.build_completion_example(tokenize, "", "ab")
        self.assertEqual(example.prompt_side, 0)
        self.assertEqual(example.target_count(), 1)
        _rows, lengths, _width = plp.batch_rows([example], [0])
        self.assertEqual(plp.target_positions(lengths)[0], [1])

    def test_single_token_example_is_untrainable(self):
        tokenize, _ = greedy_tokenizer({"a": 1})
        example = plp.build_completion_example(tokenize, "", "a")
        self.assertEqual(example.total_tokens, 1)
        self.assertFalse(example.trainable())

    def test_padding_is_batch_max_and_zero_filled(self):
        tokenize_a, _ = greedy_tokenizer({"a": 1})
        tokenize_b, _ = greedy_tokenizer(
            {"a": 1, "b": 2, "c": 3, "d": 4})
        short = plp.build_completion_example(tokenize_a, "a", "a")
        long = plp.build_completion_example(tokenize_b, "ab", "cd")
        rows, lengths, width = plp.batch_rows([short, long], [0, 1])
        self.assertEqual(width, 4)
        self.assertEqual(rows[0], [1, 1, 0, 0])
        self.assertEqual(rows[1], [1, 2, 3, 4])
        self.assertEqual(lengths, [(1, 2), (2, 4)])

    def test_tokenizer_offset_mismatch_fails_closed(self):
        def bad_tokenize(_text):
            return [1, 2], [(0, 1)]
        with self.assertRaises(plp.PilotError):
            plp.build_completion_example(bad_tokenize, "a", "b")


class AggregateTest(unittest.TestCase):

    def test_aggregate_counts_empty_context_and_untrainable(self):
        tokenize, _ = greedy_tokenizer({"a": 1, "b": 2, "c": 3})
        examples = [
            plp.build_completion_example(tokenize, "a", "b", False),
            plp.build_completion_example(tokenize, "", "bc", True),
            plp.build_completion_example(tokenize, "a", "b", False),
        ]
        flags = [False, True, False]
        summary = plp.aggregate_examples(examples, flags)
        self.assertEqual(summary["examples"], 3)
        self.assertEqual(summary["trainable"], 3)
        self.assertEqual(summary["empty_context"]["examples"], 1)
        self.assertEqual(summary["empty_context"]["trainable"], 1)
        self.assertEqual(summary["prompt_tokens"]["count"], 3)
        self.assertEqual(summary["completion_side_tokens"]["max"], 2)


class StreamTest(unittest.TestCase):

    def test_stream_epoch_is_a_deterministic_permutation(self):
        stream = plp.ShuffledStream(8, 176)
        first = [stream.next_index() for _ in range(8)]
        second = [stream.next_index() for _ in range(8)]
        self.assertEqual(sorted(first), list(range(8)))
        self.assertEqual(sorted(second), list(range(8)))
        repeat = plp.ShuffledStream(8, 176)
        self.assertEqual(first, [repeat.next_index() for _ in range(8)])

    def test_selective_indices_is_deterministic_and_sorted(self):
        first = plp.selective_indices(100, 10, 176)
        second = plp.selective_indices(100, 10, 176)
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))
        self.assertEqual(len(set(first)), 10)
        self.assertEqual(plp.selective_indices(5, 10, 176),
                         list(range(5)))


class EnvelopeTest(unittest.TestCase):

    def test_rejected_probes_are_never_chosen(self):
        probes = [
            {"rank": 16, "micro_batch": 8, "status": "rejected",
             "reject_reason": "swap_growth", "examples_per_second": 100.0},
            {"rank": 8, "micro_batch": 1, "status": "pass",
             "examples_per_second": 1.0},
        ]
        chosen = plp.choose_envelope(probes)
        self.assertEqual(chosen["rank"], 8)

    def test_higher_examples_per_second_wins_outside_tolerance(self):
        probes = [
            {"rank": 16, "micro_batch": 4, "status": "pass",
             "examples_per_second": 10.0},
            {"rank": 8, "micro_batch": 8, "status": "pass",
             "examples_per_second": 20.0},
        ]
        self.assertEqual(plp.choose_envelope(probes)["rank"], 8)

    def test_rank_16_wins_a_near_tie(self):
        probes = [
            {"rank": 8, "micro_batch": 4, "status": "pass",
             "examples_per_second": 10.0},
            {"rank": 16, "micro_batch": 4, "status": "pass",
             "examples_per_second": 10.1},
        ]
        self.assertEqual(plp.choose_envelope(probes)["rank"], 16)

    def test_no_passing_probe_has_no_choice(self):
        self.assertIsNone(plp.choose_envelope(
            [{"rank": 8, "micro_batch": 1, "status": "rejected",
              "examples_per_second": 0.0}]))


class EstimateTest(unittest.TestCase):

    def test_estimate_is_data_dependent_and_within_budget(self):
        estimate = plp.estimate_full_run(
            trainable_examples=12675, group_seconds=0.3,
            per_example_eval_seconds=0.001, save_seconds=0.2,
            validation_examples=1657, epochs=3)
        self.assertEqual(estimate["optimizer_steps_per_epoch"], 1585)
        self.assertAlmostEqual(estimate["epoch_seconds"], 475.5)
        self.assertTrue(estimate["within_budget"])
        self.assertAlmostEqual(estimate["total_hours"],
                               3 * (475.5 + 1.657 + 0.2) / 3600.0, places=6)

    def test_estimate_above_budget_is_reported_honestly(self):
        estimate = plp.estimate_full_run(
            trainable_examples=12675, group_seconds=10.0,
            per_example_eval_seconds=1.0, save_seconds=5.0,
            validation_examples=1657, epochs=3)
        self.assertFalse(estimate["within_budget"])
        self.assertGreater(estimate["total_hours"], 12.0)


class ConfigTest(unittest.TestCase):

    def base_run(self, **overrides):
        run = {
            "ranks": [8, 16],
            "micro_batches": [1, 2, 4, 8],
            "effective_batch": 8,
            "modules": list(plp.LORA_MODULES),
            "sustained_seconds": 1200,
            "reload_subset": 32,
            "eval_subset": 192,
            "recommended_epochs": 3,
        }
        run.update(overrides)
        return plp.validate_run_section(run)

    def test_default_envelope_is_accepted(self):
        values = self.base_run()
        self.assertEqual(values["ranks"], [8, 16])
        self.assertEqual(values["sustained_seconds"], 1200.0)

    def test_rank_outside_envelope_is_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(ranks=[4])

    def test_micro_batch_outside_envelope_is_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(micro_batches=[16])

    def test_non_divisor_micro_batch_is_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(micro_batches=[3])

    def test_changed_modules_are_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(modules=["self_attn.q_proj"])

    def test_short_sustained_run_is_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(sustained_seconds=60)

    def test_changed_effective_batch_is_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(effective_batch=16)

    def test_boolean_values_are_refused(self):
        with self.assertRaises(plp.PilotError):
            self.base_run(reload_subset=True)


class ModelIdentityTest(unittest.TestCase):

    def test_causal_qwen3_is_accepted(self):
        plp.assert_causal_qwen3({
            "model_type": "qwen3",
            "architectures": ["Qwen3ForCausalLM"],
            "num_hidden_layers": 28,
        })

    def test_embedding_architecture_is_refused(self):
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.assert_causal_qwen3({
                "model_type": "qwen3",
                "architectures": ["Qwen3ForCausalLM", "Qwen3Embedding"],
                "num_hidden_layers": 28,
            })

    def test_non_qwen3_model_type_is_refused(self):
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.assert_causal_qwen3({
                "model_type": "bert",
                "architectures": ["BertForMaskedLM"],
                "num_hidden_layers": 12,
            })

    def test_encoder_decoder_is_refused(self):
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.assert_causal_qwen3({
                "model_type": "qwen3",
                "architectures": ["Qwen3ForCausalLM"],
                "num_hidden_layers": 28,
                "is_encoder_decoder": True,
            })


class SwapParseTest(unittest.TestCase):

    def test_swap_usage_parses_megabytes(self):
        parsed = plp.parse_swap_usage(
            "total = 4096.00M  used = 1536.50M  free = 2559.50M")
        self.assertEqual(parsed["total_mb"], 4096.0)
        self.assertEqual(parsed["used_mb"], 1536.5)

    def test_swap_usage_parses_gigabytes(self):
        parsed = plp.parse_swap_usage(
            "total = 2.00G  used = 1.25G  free = 0.75G")
        self.assertEqual(parsed["used_mb"], 1280.0)

    def test_unrecognized_swap_output_raises(self):
        with self.assertRaises(ValueError):
            plp.parse_swap_usage("nothing here")


if __name__ == "__main__":
    unittest.main()
