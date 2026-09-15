#!/usr/bin/env python3
"""Objective, mask, batching, selection and config tests for #177.

Fixtures are synthetic; the real tokenizer, the real dataset and MLX are
never needed. These tests pin that the training runner uses the frozen #176
serialization and completion-only mask (raw ``prompt + completion``, no chat
wrapper, boundary-spanning tokens prompt-side, untrainable examples skipped)
and that the predeclared selection and frozen configuration behave exactly as
the contract states.
"""

import json
import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_data as pld  # noqa: E402
import personal_lora_pilot as plp  # noqa: E402
import personal_lora_train as plt  # noqa: E402


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


class FakeMX(object):
    float32 = np.float32

    @staticmethod
    def array(value):
        return np.asarray(value, dtype=np.int32)

    @staticmethod
    def arange(start, stop):
        return np.arange(start, stop)

    @staticmethod
    def logical_and(left, right):
        return np.logical_and(left, right)

    @staticmethod
    def logsumexp(value, axis, keepdims):
        maximum = value.max(axis=axis, keepdims=True)
        return maximum + np.log(
            np.exp(value - maximum).sum(axis=axis, keepdims=True))

    @staticmethod
    def take_along_axis(value, indices, axis):
        return np.take_along_axis(value, indices, axis=axis)

    @staticmethod
    def eval(*_values):
        return None


class UniformModel(object):
    """Zero logits: every completion token costs exactly log(vocab_size)."""

    def __init__(self, vocab=16):
        self._weight = np.zeros((8, vocab), np.float32)

    def __call__(self, ids):
        return self._weight[np.asarray(ids) % 8]

    def eval(self):
        pass

    def train(self):
        pass


def fake_backend():
    return {"np": np, "mx": FakeMX()}


UNIFORM_LOSS = math.log(16)


class ObjectiveSeamTest(unittest.TestCase):

    def test_objective_matches_the_pilot_exactly(self):
        self.assertEqual(plt.OBJECTIVE, plp.OBJECTIVE)
        self.assertEqual(tuple(plt.LORA_MODULES), tuple(plp.LORA_MODULES))
        self.assertEqual(plt.SEED, plp.SEED)
        self.assertEqual(plt.LEARNING_RATE, plp.LEARNING_RATE)
        self.assertEqual(plt.WEIGHT_DECAY, plp.WEIGHT_DECAY)
        self.assertEqual(plt.LORA_DROPOUT, plp.LORA_DROPOUT)
        self.assertEqual(plt.RELOAD_TOLERANCE, plp.RELOAD_TOLERANCE)
        self.assertEqual(plt.RELOAD_SUBSET_SIZE, plp.RELOAD_SUBSET_SIZE)

    def example(self, vocabulary, prompt, completion, bos_id=None):
        tokenize, _calls = greedy_tokenizer(vocabulary, bos_id)
        return plp.build_completion_example(
            tokenize, prompt, completion)

    def test_completion_nll_charges_only_completion_tokens(self):
        backend = fake_backend()
        example = self.example({"a": 1, "b": 2, "c": 3, "d": 4}, "ab", "cd")
        nll, tokens = plt.completion_nll(backend, UniformModel(), example)
        self.assertEqual(tokens, 2)
        self.assertAlmostEqual(nll, 2 * UNIFORM_LOSS, places=6)

    def test_boundary_spanning_token_is_never_charged_to_the_loss(self):
        backend = fake_backend()
        example = self.example(
            {"a": 1, "b": 2, "c": 3, "d": 4, "bcd": 7}, "ab", "cd")
        self.assertEqual(example.prompt_side, 2)
        self.assertEqual(example.spanning_tokens, 1)
        self.assertFalse(example.trainable())
        nll, tokens = plt.completion_nll(backend, UniformModel(), example)
        self.assertEqual(tokens, 0)
        self.assertEqual(nll, 0.0)

    def test_partial_spanning_leaves_later_completion_tokens_trainable(self):
        backend = fake_backend()
        example = self.example(
            {"a": 1, "b": 2, "c": 3, "d": 4, "bc": 5}, "ab", "cd")
        self.assertEqual(example.spanning_tokens, 1)
        self.assertTrue(example.trainable())
        nll, tokens = plt.completion_nll(backend, UniformModel(), example)
        self.assertEqual(tokens, 1)
        self.assertAlmostEqual(nll, UNIFORM_LOSS, places=6)

    def test_empty_prompt_first_token_is_never_a_target(self):
        backend = fake_backend()
        example = self.example({"a": 1, "b": 2}, "", "ab")
        self.assertEqual(example.prompt_side, 0)
        nll, tokens = plt.completion_nll(backend, UniformModel(), example)
        self.assertEqual(tokens, 1)
        self.assertAlmostEqual(nll, UNIFORM_LOSS, places=6)

    def test_bos_is_input_only_and_prompt_side(self):
        backend = fake_backend()
        example = self.example({"a": 1, "b": 2}, "a", "b", bos_id=99)
        self.assertEqual(example.input_ids, [99, 1, 2])
        nll, tokens = plt.completion_nll(backend, UniformModel(), example)
        self.assertEqual(tokens, 1)
        self.assertAlmostEqual(nll, UNIFORM_LOSS, places=6)

    def test_single_token_example_fails_closed(self):
        backend = fake_backend()
        example = self.example({"a": 1}, "", "a")
        self.assertFalse(example.trainable())
        with self.assertRaises(plt.TrainError):
            plt.completion_nll(backend, UniformModel(), example)

    def test_untrainable_examples_are_skipped_not_repaired(self):
        tokenize, calls = greedy_tokenizer(
            {"a": 1, "b": 2, "c": 3, "d": 4, "bcd": 7})
        examples = [
            plp.build_completion_example(tokenize, "ab", "cd"),
            plp.build_completion_example(tokenize, "ab", "cd"),
        ]
        self.assertEqual(calls, ["abcd", "abcd"])
        self.assertEqual(plt.trainable_indices(examples), [])
        backend = fake_backend()
        with self.assertRaises(plt.TrainError):
            plt.partition_completion_loss(backend, UniformModel(), examples,
                                          [])

    def test_partition_loss_is_token_weighted_over_the_frozen_mask(self):
        backend = fake_backend()
        tokenize, _calls = greedy_tokenizer({"a": 1, "b": 2, "c": 3, "d": 4})
        examples = [
            plp.build_completion_example(tokenize, "ab", "cd"),
            plp.build_completion_example(tokenize, "", "ab"),
        ]
        result = plt.partition_completion_loss(backend, UniformModel(),
                                               examples, [0, 1])
        self.assertEqual(result["examples"], 2)
        self.assertEqual(result["completion_tokens"], 3)
        self.assertAlmostEqual(result["mean_loss"], UNIFORM_LOSS, places=6)

    def test_load_examples_matches_the_pilot_parser(self):
        root = tempfile.mkdtemp(prefix="train_objective_")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "validation.jsonl")
        records = [
            {"schema": plp.DATASET_SCHEMA, "prompt": "ab", "completion": "c",
             "loss": "completion_only",
             "provenance": {"empty_context": False}},
            {"schema": plp.DATASET_SCHEMA, "prompt": "", "completion": "d",
             "loss": "completion_only",
             "provenance": {"empty_context": True}},
        ]
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        self.assertEqual(plt.load_examples(path, "validation.jsonl"),
                         plp.load_train_examples(path))

    def test_load_examples_refuses_invalid_records(self):
        root = tempfile.mkdtemp(prefix="train_objective_")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "validation.jsonl")
        bad = [
            "not json\n",
            json.dumps({"schema": "other", "prompt": "a",
                        "completion": "b"}) + "\n",
            json.dumps({"schema": plp.DATASET_SCHEMA, "prompt": "a",
                        "completion": "b", "loss": "something"}) + "\n",
            json.dumps({"schema": plp.DATASET_SCHEMA, "prompt": "a",
                        "completion": "", "loss": "completion_only"}) + "\n",
            json.dumps({"schema": plp.DATASET_SCHEMA, "prompt": 5,
                        "completion": "b",
                        "loss": "completion_only"}) + "\n",
        ]
        for text in bad:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            with self.assertRaises(plt.TrainError):
                plt.load_examples(path, "validation.jsonl")


class MarkerModel(object):
    """Logits whose only channel is the 0-based input position."""

    def __call__(self, ids):
        ids = np.asarray(ids)
        positions = np.arange(ids.shape[1], dtype=np.float32)
        return positions[None, :, None].repeat(ids.shape[0], axis=0)

    def eval(self):
        pass

    def train(self):
        pass


class MarkerLosses(object):

    @staticmethod
    def cross_entropy(logits, _targets):
        return np.asarray(logits)[..., 0]


class MarkerNN(object):
    losses = MarkerLosses()


class PaddedLossMaskTest(unittest.TestCase):
    """The completion-only loss never charges a padding target."""

    def loss(self, rows, lengths):
        backend = {"np": np, "mx": FakeMX(), "nn": MarkerNN()}
        return float(plp.make_loss_fn(backend)(
            MarkerModel(), np.asarray(rows, dtype=np.int32),
            np.asarray(lengths, dtype=np.int32)))

    def test_first_padding_target_is_excluded(self):
        loss = self.loss([[1, 2, 3, 0, 0], [4, 5, 6, 7, 8]],
                         [(2, 3), (2, 5)])
        self.assertAlmostEqual(loss, 7.0 / 4.0, places=6)

    def test_equal_length_rows_keep_every_completion_position(self):
        loss = self.loss([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]],
                         [(2, 5), (2, 5)])
        self.assertAlmostEqual(loss, 12.0 / 6.0, places=6)


class FrozenIdentityConstantTest(unittest.TestCase):
    """The runner pins the #176/#175 identities independently of config."""

    def test_model_composite_is_the_frozen_identity(self):
        self.assertEqual(
            plt.FROZEN_MODEL_COMPOSITE_SHA256,
            "f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320"
            "fafa")

    def test_dataset_digests_are_the_frozen_identities(self):
        self.assertEqual(plt.FROZEN_DATASET_DIGESTS, {
            "train_sha256":
                "c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c8"
                "0d8dd2",
            "validation_sha256":
                "80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8b"
                "deaa880",
            "manifest_sha256":
                "5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704"
                "774bae",
            "test_sha256":
                "12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a"
                "9f2d2b",
        })
        self.assertEqual(plt.FROZEN_FREEZE_COMMIT,
                         "2076d0a6c92dbf57833b7a123ea54aab10ddd49d")


class EpochPlanTest(unittest.TestCase):

    def test_every_index_is_used_exactly_once_per_epoch(self):
        batches = plt.epoch_batches(11259, 1)
        self.assertEqual(len(batches), 1408)
        flattened = [index for batch in batches for index in batch]
        self.assertEqual(sorted(flattened), list(range(11259)))
        self.assertEqual(len(batches[-1]), 11259 - 1407 * 8)

    def test_batches_are_deterministic_and_epoch_scoped(self):
        self.assertEqual(plt.epoch_batches(64, 2), plt.epoch_batches(64, 2))
        self.assertNotEqual(plt.epoch_batches(64, 2),
                            plt.epoch_batches(64, 3))

    def test_negative_count_fails_closed(self):
        with self.assertRaises(plt.TrainError):
            plt.epoch_batches(-1, 1)


class EpochDeadlineTest(unittest.TestCase):
    """The remaining budget starts at the current clock, not process start."""

    def test_deadline_is_anchored_to_now(self):
        self.assertEqual(
            plt.next_epoch_deadline(1000.0, 3000.0, 3600.0), 1600.0)

    def test_exhausted_budget_has_no_deadline(self):
        self.assertIsNone(
            plt.next_epoch_deadline(1000.0, 3600.0, 3600.0))
        self.assertIsNone(
            plt.next_epoch_deadline(1000.0, 4000.0, 3600.0))


class SelectionTest(unittest.TestCase):

    def test_lowest_validation_loss_wins(self):
        rows = [
            {"epoch": 1, "validation_loss": 2.0},
            {"epoch": 2, "validation_loss": 1.5},
            {"epoch": 3, "validation_loss": 1.7},
        ]
        self.assertEqual(plt.select_epoch(rows)["epoch"], 2)

    def test_exact_tie_goes_to_the_later_epoch(self):
        rows = [
            {"epoch": 1, "validation_loss": 1.5},
            {"epoch": 2, "validation_loss": 1.5},
            {"epoch": 3, "validation_loss": 1.5},
        ]
        self.assertEqual(plt.select_epoch(rows)["epoch"], 3)

    def test_selection_never_uses_train_loss_or_a_metric(self):
        rows = [
            {"epoch": 1, "validation_loss": 2.0, "train": {"loss_mean": 0.1}},
            {"epoch": 2, "validation_loss": 1.0, "train": {"loss_mean": 5.0}},
        ]
        self.assertEqual(plt.select_epoch(rows)["epoch"], 2)

    def test_non_finite_loss_fails_closed(self):
        for loss in (float("nan"), float("inf")):
            with self.assertRaises(plt.TrainError):
                plt.select_epoch([{"epoch": 1, "validation_loss": loss}])

    def test_empty_rows_fail_closed(self):
        with self.assertRaises(plt.TrainError):
            plt.select_epoch([])


class FrozenConfigTest(unittest.TestCase):

    def test_default_run_is_the_frozen_shape(self):
        frozen = plt.validate_run_section({})
        self.assertEqual(frozen["epochs"], 3)
        self.assertEqual(frozen["rank"], 16)
        self.assertEqual(frozen["alpha"], 16)
        self.assertEqual(frozen["dropout"], 0.0)
        self.assertEqual(frozen["modules"], list(plt.LORA_MODULES))
        self.assertEqual(frozen["micro_batch"], 8)
        self.assertEqual(frozen["gradient_accumulation"], 1)
        self.assertEqual(frozen["effective_batch"], 8)
        self.assertEqual(frozen["learning_rate"], 1e-4)
        self.assertEqual(frozen["weight_decay"], 0.0)
        self.assertEqual(frozen["seed"], 176)
        self.assertIsNone(frozen["num_layers"])

    def test_explicit_frozen_values_are_accepted(self):
        frozen = plt.validate_run_section({
            "epochs": 3, "rank": 16, "alpha": 16, "dropout": 0.0,
            "modules": list(plt.LORA_MODULES), "micro_batch": 8,
            "gradient_accumulation": 1, "effective_batch": 8,
            "learning_rate": 1e-4, "weight_decay": 0.0, "seed": 176,
            "num_layers": 28,
        })
        self.assertEqual(frozen["num_layers"], 28)

    def test_every_deviation_is_refused(self):
        deviations = {
            "epochs": 4, "rank": 8, "alpha": 8, "dropout": 0.1,
            "modules": ["self_attn.q_proj"], "micro_batch": 4,
            "gradient_accumulation": 2, "effective_batch": 16,
            "learning_rate": 2e-4, "weight_decay": 0.01, "seed": 177,
            "num_layers": 0,
        }
        for key, value in deviations.items():
            with self.assertRaises(plt.TrainError):
                plt.validate_run_section({key: value})

    def test_boolean_values_are_refused(self):
        with self.assertRaises(plt.TrainError):
            plt.validate_run_section({"learning_rate": True})
        with self.assertRaises(plt.TrainError):
            plt.validate_run_section({"num_layers": True})

    def test_config_hash_tracks_the_run_section(self):
        frozen = plt.validate_run_section({})
        self.assertEqual(plt.config_sha256(frozen),
                         plt.config_sha256(plt.validate_run_section({})))
        changed = dict(frozen)
        changed["learning_rate"] = 2e-4
        self.assertNotEqual(plt.config_sha256(frozen),
                            plt.config_sha256(changed))

    def test_config_hash_binds_the_objective(self):
        frozen = plt.validate_run_section({})
        digest = plt.config_sha256(frozen)
        self.assertEqual(digest, pld.sha256_text(pld.canonical_json(
            {"objective": plt.OBJECTIVE, "run": frozen})))


class CliTest(unittest.TestCase):

    def test_self_test_cli_passes(self):
        self.assertEqual(plt.main(["--self-test"]), 0)

    def test_run_without_config_fails_closed(self):
        self.assertEqual(plt.main(["--run"]), 1)

    def test_missing_config_file_fails_closed(self):
        self.assertEqual(plt.main(["--run", "--config",
                                   "/nonexistent/config.json"]), 1)

    def test_self_test_covers_the_frozen_decisions(self):
        checks = plt.self_test()
        self.assertIn("frozen_epochs", checks)
        self.assertIn("cache_threshold_is_two_gb", checks)
        self.assertIn("selection_prefers_later_epoch_on_a_tie", checks)
        self.assertIn("epoch_batches_cover_every_index_once", checks)


if __name__ == "__main__":
    unittest.main()
