#!/usr/bin/env python3
"""Sealing, privacy and identity tests for the #177 training runner.

These tests pin the contract's isolation rules: ``test.jsonl`` is opened only
in binary mode for checksumming and is never parsed, private outputs stay
under the ticket root with owner-only permissions, the desensitized report
and default console contain no prompt/completion text or absolute private
paths, and the config fails closed on any deviation from the frozen
hyperparameters.
"""

import builtins
import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_data as pld  # noqa: E402
import personal_lora_train as plt  # noqa: E402

SEALED_SENTINEL = "SENTINELSEALEDPRIVATETEXT"


def sha256_text(text):
    return pld.sha256_text(text)


def write_text(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, mode)


class IsolationTestCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="train_isolation_")
        self.dataset = os.path.join(self.root, "dataset")
        os.makedirs(self.dataset, mode=0o700)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def build_dataset(self, expected=True, model_composite=None):
        train_lines = [
            json.dumps({
                "schema": "personal-lora-completion-v1",
                "prompt": "ab",
                "completion": "c",
                "loss": "completion_only",
                "provenance": {"empty_context": False},
            }, ensure_ascii=False),
        ]
        train_text = "\n".join(train_lines) + "\n"
        validation_text = json.dumps({
            "schema": "personal-lora-completion-v1",
            "prompt": "ab",
            "completion": "d",
            "loss": "completion_only",
            "provenance": {"empty_context": False},
        }) + "\n"
        test_text = SEALED_SENTINEL + " not json\n"
        write_text(os.path.join(self.dataset, plt.plp.TRAIN_FILE), train_text)
        write_text(os.path.join(self.dataset, plt.plp.VALIDATION_FILE),
                   validation_text)
        write_text(os.path.join(self.dataset, plt.plp.TEST_FILE), test_text)
        manifest = {
            "schema": plt.plp.MANIFEST_SCHEMA,
            "created_at_utc": "2026-09-14T00:00:00Z",
            "audit": {"samples": 1},
            "splits": {
                "parts": {
                    "train": {"sha256": sha256_text(train_text),
                              "lines": 1},
                    "validation": {"lines": 1},
                    "test": {"lines": 1},
                },
            },
        }
        write_text(os.path.join(self.dataset, plt.plp.MANIFEST_FILE),
                   json.dumps(manifest, sort_keys=True) + "\n")
        expected_digests = {
            "train_sha256": sha256_text(train_text),
            "manifest_sha256": pld.sha256_file(
                os.path.join(self.dataset, plt.plp.MANIFEST_FILE)),
            "validation_sha256": sha256_text(validation_text),
            "test_sha256": sha256_text(test_text),
            "model_composite_sha256": model_composite or ("a" * 64),
        }
        if not expected:
            expected_digests["train_sha256"] = "0" * 64
        return {
            "artifact_root": self.root,
            "model_dir": self.root,
            "dataset_dir": self.dataset,
            "freeze_commit": "2076d0a6c92dbf57833b7a123ea54aab10ddd49d",
            "expected": expected_digests,
            "run": plt.validate_run_section({}),
        }


class SealedFileTest(IsolationTestCase):

    def test_test_file_is_checksummed_but_never_parsed(self):
        config = self.build_dataset(
            model_composite=("a" * 64))
        opened = []
        original_open = builtins.open

        def tracking_open(path, mode="r", *args, **kwargs):
            normalized = os.path.abspath(str(path))
            if normalized.endswith(plt.plp.TEST_FILE):
                opened.append((os.path.basename(normalized), mode))
            return original_open(path, mode, *args, **kwargs)

        builtins.open = tracking_open
        try:
            identity = plt.plp.identify_dataset(config)
        finally:
            builtins.open = original_open
        self.assertEqual(identity["digests"]["test_sha256"],
                         config["expected"]["test_sha256"])
        self.assertEqual(opened, [(plt.plp.TEST_FILE, "rb")])

    def test_invalid_json_in_the_test_file_does_not_block_identity(self):
        config = self.build_dataset()
        identity = plt.plp.identify_dataset(config)
        self.assertEqual(identity["digests"]["test_sha256"],
                         config["expected"]["test_sha256"])

    def test_validation_is_parsed_only_by_the_explicit_loader(self):
        config = self.build_dataset()
        plt.plp.identify_dataset(config)
        records = plt.load_examples(
            os.path.join(self.dataset, plt.plp.VALIDATION_FILE),
            plt.plp.VALIDATION_FILE)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["completion"], "d")

    def test_expected_digest_mismatch_is_an_environment_blocker(self):
        config = self.build_dataset(expected=False)
        with self.assertRaises(plt.plp.EnvironmentBlocker):
            plt.plp.identify_dataset(config)

    def test_manifest_train_binding_is_checked(self):
        config = self.build_dataset()
        manifest_path = os.path.join(self.dataset, plt.plp.MANIFEST_FILE)
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["splits"]["parts"]["train"]["lines"] = 99
        write_text(manifest_path, json.dumps(manifest, sort_keys=True))
        with self.assertRaises(plt.plp.EnvironmentBlocker):
            plt.plp.identify_dataset(config)


class PrivateOutputTest(IsolationTestCase):

    def test_private_json_is_owner_only_and_round_trips(self):
        root = os.path.join(self.root, "artifact")
        os.makedirs(root, mode=0o700)
        plt.write_private_json(root, "run/epochs.json", {"rows": []})
        plt.write_private_json(root, "public-report.md", {})
        self.assertEqual(pld.verify_owner_only(root), [])
        self.assertEqual(plt.read_private_json(root, "run/epochs.json"),
                         {"rows": []})

    def test_artifact_root_outside_allowed_root_is_refused(self):
        allowed = tempfile.mkdtemp(prefix="train_allowed_")
        outside = tempfile.mkdtemp(prefix="train_outside_")
        self.addCleanup(shutil.rmtree, allowed, True)
        self.addCleanup(shutil.rmtree, outside, True)
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(outside, allowed_root=allowed,
                                     protected_roots=[])

    def test_protected_location_is_refused(self):
        protected = tempfile.mkdtemp(prefix="train_protected_")
        self.addCleanup(shutil.rmtree, protected, True)
        nested = os.path.join(protected, "root")
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(nested, allowed_root=protected,
                                     protected_roots=[protected])

    def test_epoch_checkpoint_paths_stay_inside_the_root(self):
        root = os.path.join(self.root, "artifact")
        os.makedirs(root, mode=0o700)
        relative = plt.checkpoint_relative_dir(2)
        self.assertEqual(relative, "epochs/epoch-2")
        pld.ensure_private_dir(root, relative)
        with self.assertRaises(pld.IsolationError):
            pld.safe_target(root, "../escape")


class ReportPrivacyTest(IsolationTestCase):

    def identity(self):
        return {
            "model": {
                "basename": "Qwen3-0.6B-Base",
                "composite_sha256": "a" * 64,
                "class": "Qwen3ForCausalLM",
                "config": {"model_type": "qwen3"},
                "files": {"model.safetensors": {"sha256": "9" * 64,
                                                "bytes": 1192135096}},
            },
            "versions": {"mlx": "0.32.0"},
            "pinned_versions": {"mlx": "0.32.0"},
            "machine": {"model": "Mac17,3"},
            "cache_clear_threshold_bytes": 2_000_000_000,
            "dataset": {
                "digests": {"train_sha256": "b" * 64,
                            "manifest_sha256": "c" * 64,
                            "validation_sha256": "d" * 64,
                            "test_sha256": "e" * 64},
                "freeze_commit": "2076d0a",
            },
            "tokenizer": {"class": "Qwen2Tokenizer",
                          "backend": "Tokenizer", "vocab_size": 151936,
                          "add_bos_token": False, "add_eos_token": False},
            "runtime_device": {"device": "Apple M5"},
            "run": {"epochs": 3, "rank": 16},
            "fresh_lora": {"warm_start": False,
                           "initialization": "mlx_random_seed_176",
                           "source_adapter": None,
                           "trainable_parameters": 4587520},
            "token_aggregate_train": {
                "examples": 3, "trainable": 3, "untrainable": 0,
                "empty_context": {"examples": 0, "trainable": 0},
                "prompt_tokens": {"count": 3, "min": 0, "p50": 1, "p90": 2,
                                  "p99": 2, "max": 2, "mean": 1.0},
                "completion_side_tokens": {"count": 3, "min": 1, "p50": 1,
                                           "p90": 2, "p99": 2, "max": 2,
                                           "mean": 1.3},
                "boundary_spanning": {"examples": 0, "tokens": 0},
            },
            "token_aggregate_validation": {
                "examples": 2, "trainable": 2, "untrainable": 0,
                "empty_context": {"examples": 0, "trainable": 0},
                "prompt_tokens": {"count": 2, "min": 0, "p50": 1, "p90": 1,
                                  "p99": 1, "max": 1, "mean": 1.0},
                "completion_side_tokens": {"count": 2, "min": 1, "p50": 1,
                                           "p90": 1, "p99": 1, "max": 1,
                                           "mean": 1.0},
                "boundary_spanning": {"examples": 0, "tokens": 0},
            },
        }

    def measurement(self):
        return {
            "terminal": "trained",
            "terminal_reasons": [],
            "config_sha256": "7" * 64,
            "wall_clock_seconds": 1080.0,
            "within_budget": True,
            "resumed_from_epoch": None,
            "selected_epoch": 2,
            "epochs": [{
                "epoch": 1, "steps": 1408, "train": {
                    "loss_first": 7.0, "loss_last": 2.0, "loss_mean": 2.5},
                "validation_loss": 2.4, "seconds": 300.0,
                "cache_clears": {"threshold": 100, "epoch_floor": 1},
                "peak_memory_gb": 2.8, "checkpoint": {"adapter_sha256": "f"},
            }, {
                "epoch": 2, "steps": 1408, "train": {
                    "loss_first": 2.3, "loss_last": 1.9, "loss_mean": 2.0},
                "validation_loss": 2.1, "seconds": 300.0,
                "cache_clears": {"threshold": 100, "epoch_floor": 1},
                "peak_memory_gb": 2.8, "checkpoint": {"adapter_sha256": "g"},
            }],
            "verification": {
                "selected_epoch": 2,
                "selected_adapter_sha256": "f" * 64,
                "selected_adapter_bytes": 18374616,
                "subset_size": 32,
                "subset_rule": "first_32_trainable_examples_in_file_order",
                "max_abs_diff": 0.0,
                "agreement_pass": True,
                "digest_before": "1" * 64,
                "digest_after": "2" * 64,
                "weights_changed": True,
            },
            "peak_memory": {"peak_gb": 2.8, "active_gb": 1.2,
                            "cache_gb": 0.1},
            "process_max_rss_mb": 1699.0,
            "cache_clears": {"threshold": 200, "epoch_floor": 2},
            "trainable_examples": 11259,
            "untrainable_examples": 1416,
            "validation_trainable_examples": 1553,
        }

    def test_report_contains_no_prompt_text_or_absolute_paths(self):
        report = plt.render_public_report(self.identity(), self.measurement())
        self.assertNotIn(SEALED_SENTINEL, report)
        self.assertNotIn(self.root, report)
        self.assertNotIn("/Users/", report)
        self.assertNotIn("data/", report)

    def test_report_carries_the_aggregate_evidence(self):
        report = plt.render_public_report(self.identity(), self.measurement())
        self.assertIn("trained", report)
        self.assertIn(plt.SELECTION_RULE, report)
        self.assertIn("lowest validation", report)
        self.assertIn("11259", report)
        self.assertIn("1416", report)
        self.assertIn("selected epoch: `2`", report)
        self.assertIn("agreement", report)


class ConfigFileTest(IsolationTestCase):

    def write_config(self, value):
        path = os.path.join(self.root, "config.json")
        write_text(path, json.dumps(value, sort_keys=True))
        return path

    def valid_config(self):
        return self.build_dataset()

    def test_unknown_keys_fail_closed(self):
        config = self.valid_config()
        config["extra"] = 1
        with self.assertRaises(plt.TrainError):
            plt.load_config(self.write_config(config))

    def test_missing_expected_digest_fails_closed(self):
        config = self.valid_config()
        del config["expected"]["model_composite_sha256"]
        with self.assertRaises(plt.TrainError):
            plt.load_config(self.write_config(config))

    def test_short_digest_fails_closed(self):
        config = self.valid_config()
        config["expected"]["test_sha256"] = "abc"
        with self.assertRaises(plt.TrainError):
            plt.load_config(self.write_config(config))

    def test_unknown_run_key_fails_closed(self):
        config = self.valid_config()
        config["run"]["epochs"] = 3
        config["run"]["extra"] = 1
        with self.assertRaises(plt.TrainError):
            plt.load_config(self.write_config(config))

    def test_valid_config_round_trips(self):
        config = self.valid_config()
        loaded = plt.load_config(self.write_config(config))
        self.assertEqual(loaded["freeze_commit"], config["freeze_commit"])
        self.assertEqual(loaded["run"]["epochs"], 3)
        self.assertIsNone(loaded["run"]["num_layers"])


class CliTest(unittest.TestCase):

    def test_self_test_cli_passes(self):
        self.assertEqual(plt.main(["--self-test"]), 0)

    def test_run_without_config_fails_closed(self):
        self.assertEqual(plt.main(["--run"]), 1)

    def test_missing_config_file_fails_closed(self):
        self.assertEqual(plt.main(["--run", "--config",
                                   "/nonexistent/config.json"]), 1)

    def test_verify_reload_without_a_run_fails_closed(self):
        root = tempfile.mkdtemp(prefix="train_cli_")
        self.addCleanup(shutil.rmtree, root, True)
        config = {
            "artifact_root": root,
            "model_dir": root,
            "dataset_dir": root,
            "freeze_commit": None,
            "expected": {key: "a" * 64 for key in plt.EXPECTED_KEYS},
            "run": {},
        }
        path = os.path.join(root, "config.json")
        write_text(path, json.dumps(config))
        self.assertEqual(plt.main(["--verify-reload", "--config", path]), 1)


if __name__ == "__main__":
    unittest.main()
