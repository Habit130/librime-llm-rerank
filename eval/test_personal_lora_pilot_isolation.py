#!/usr/bin/env python3
"""Sealing, privacy and identity tests for the #176 pilot runner.

These tests pin the contract's isolation rules: the sealed validation/test
files are opened only in binary mode for checksumming and are never parsed,
private outputs stay under the ticket root with owner-only permissions, the
desensitized report and default console contain no prompt/completion text or
absolute private paths, and model identity fails closed on the wrong model.
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
import personal_lora_pilot as plp  # noqa: E402

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
        self.root = tempfile.mkdtemp(prefix="pilot_isolation_")
        self.dataset = os.path.join(self.root, "dataset")
        os.makedirs(self.dataset, mode=0o700)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def build_dataset(self, expected=True):
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
        write_text(os.path.join(self.dataset, plp.TRAIN_FILE), train_text)
        write_text(os.path.join(self.dataset, plp.VALIDATION_FILE),
                   SEALED_SENTINEL + " not json\n")
        write_text(os.path.join(self.dataset, plp.TEST_FILE),
                   SEALED_SENTINEL + " not json either\n")
        manifest = {
            "schema": plp.MANIFEST_SCHEMA,
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
        write_text(os.path.join(self.dataset, plp.MANIFEST_FILE),
                   json.dumps(manifest, sort_keys=True) + "\n")
        expected_digests = {
            "train_sha256": sha256_text(train_text),
            "manifest_sha256": pld.sha256_file(
                os.path.join(self.dataset, plp.MANIFEST_FILE)),
            "validation_sha256": pld.sha256_file(
                os.path.join(self.dataset, plp.VALIDATION_FILE)),
            "test_sha256": pld.sha256_file(
                os.path.join(self.dataset, plp.TEST_FILE)),
        }
        if not expected:
            expected_digests["train_sha256"] = "0" * 64
        return {
            "artifact_root": self.root,
            "model_dir": self.root,
            "dataset_dir": self.dataset,
            "freeze_commit": "2076d0a6c92dbf57833b7a123ea54aab10ddd49d",
            "expected": expected_digests,
            "run": plp.validate_run_section({}),
        }

    def build_model_dir(self, model_type="qwen3",
                        architectures=("Qwen3ForCausalLM",)):
        model_dir = os.path.join(self.root, "model")
        os.makedirs(model_dir, mode=0o700)
        for name in plp.REQUIRED_MODEL_FILES:
            write_text(os.path.join(model_dir, name), "")
        write_text(os.path.join(model_dir, "config.json"), json.dumps({
            "model_type": model_type,
            "architectures": list(architectures),
            "num_hidden_layers": 4,
            "hidden_size": 16,
        }))
        return model_dir


class SealedFileTest(IsolationTestCase):

    def test_sealed_files_are_checksummed_but_never_parsed(self):
        config = self.build_dataset()
        opened = []
        original_open = builtins.open

        def tracking_open(path, mode="r", *args, **kwargs):
            normalized = os.path.abspath(str(path))
            if normalized.endswith((plp.VALIDATION_FILE, plp.TEST_FILE)):
                opened.append((os.path.basename(normalized), mode))
            return original_open(path, mode, *args, **kwargs)

        builtins.open = tracking_open
        try:
            identity = plp.identify_dataset(config)
        finally:
            builtins.open = original_open
        self.assertEqual(identity["train_lines"], 1)
        self.assertEqual(sorted(mode for _name, mode in opened), ["rb", "rb"])
        self.assertEqual(len(opened), 2)

    def test_invalid_json_in_sealed_files_does_not_block_identity(self):
        config = self.build_dataset()
        identity = plp.identify_dataset(config)
        self.assertEqual(identity["digests"]["test_sha256"],
                         config["expected"]["test_sha256"])

    def test_expected_digest_mismatch_is_an_environment_blocker(self):
        config = self.build_dataset(expected=False)
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.identify_dataset(config)

    def test_manifest_train_binding_is_checked(self):
        config = self.build_dataset()
        manifest_path = os.path.join(self.dataset, plp.MANIFEST_FILE)
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["splits"]["parts"]["train"]["lines"] = 99
        write_text(manifest_path, json.dumps(manifest, sort_keys=True))
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.identify_dataset(config)


class PrivateOutputTest(IsolationTestCase):

    def test_private_json_is_owner_only_and_round_trips(self):
        root = os.path.join(self.root, "artifact")
        os.makedirs(root, mode=0o700)
        pld.private_write_bytes(root, "run/probes.json", b"{}\n")
        pld.private_write_bytes(root, "public-report.md", b"report\n")
        self.assertEqual(pld.verify_owner_only(root), [])
        self.assertEqual(plp.read_private_json(root, "run/probes.json"), {})

    def test_artifact_root_outside_allowed_root_is_refused(self):
        allowed = tempfile.mkdtemp(prefix="pilot_allowed_")
        outside = tempfile.mkdtemp(prefix="pilot_outside_")
        self.addCleanup(shutil.rmtree, allowed, True)
        self.addCleanup(shutil.rmtree, outside, True)
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(outside, allowed_root=allowed,
                                     protected_roots=[])

    def test_protected_location_is_refused(self):
        protected = tempfile.mkdtemp(prefix="pilot_protected_")
        self.addCleanup(shutil.rmtree, protected, True)
        nested = os.path.join(protected, "root")
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(nested, allowed_root=protected,
                                     protected_roots=[protected])


class ReportPrivacyTest(IsolationTestCase):

    def identity(self):
        return {
            "model": {
                "basename": "Qwen3-0.6B-Base",
                "composite_sha256": "a" * 64,
                "config": {"model_type": "qwen3"},
            },
            "versions": {"mlx": "0.32.0"},
            "pinned_versions": {"mlx": "0.32.0"},
            "machine": {"model": "Mac17,3"},
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
            "token_aggregate": {
                "examples": 3,
                "trainable": 3,
                "untrainable": 0,
                "empty_context": {"examples": 0, "trainable": 0},
                "prompt_tokens": {"count": 3, "min": 0, "p50": 1, "p90": 2,
                                  "p99": 2, "max": 2, "mean": 1.0},
                "completion_side_tokens": {"count": 3, "min": 1, "p50": 1,
                                           "p90": 2, "p99": 2, "max": 2,
                                           "mean": 1.3},
                "boundary_spanning": {"examples": 0, "tokens": 0},
            },
        }

    def measurement(self):
        return {
            "terminal": "local_feasible",
            "terminal_reasons": [],
            "probes": [{
                "rank": 8, "micro_batch": 4, "accumulate": 2,
                "status": "pass", "reject_reason": None,
                "examples_per_second": 1.0, "peak_memory_gb": 2.0,
                "swap_before_mb": 100.0, "swap_after_mb": 100.0,
            }],
            "chosen": {"rank": 8, "micro_batch": 4},
            "sustained": {
                "rank": 8, "micro_batch": 4, "accumulate": 2,
                "target_seconds": 1200.0, "warmup_seconds": 2.0,
                "measured_seconds": 1200.0,
                "measured": {
                    "micro_batches": 10, "optimizer_updates": 5,
                    "micro_batch_seconds": {"min": 0.1, "max": 0.2,
                                            "mean": 0.15},
                    "update_seconds": {"mean": 0.01},
                    "padded_widths": {"min": 4, "max": 8, "mean": 6},
                    "padded_tokens_total": 60,
                    "loss_first": 9.0, "loss_last": 8.0, "loss_mean": 8.5,
                },
                "samples": [{"thermal": "unavailable"}],
                "peak_memory_gb": 2.0, "swap_start_mb": 100.0,
                "swap_end_mb": 100.0, "swap_growth_mb": 0.0,
            },
            "verification": {
                "digest_before": "1" * 64, "digest_after": "2" * 64,
                "weights_changed": True, "trainable_parameters": 100,
                "adapter_sha256": "f" * 64, "adapter_bytes": 128,
                "save_seconds": 0.05,
                "reload_loader": "mlx_lm.tuner.utils.load_adapters",
                "subset_size": 32, "subset_rule": "first_32_trainable",
                "max_abs_diff": 0.0, "agreement_pass": True,
            },
            "estimate": {
                "effective_batch": 8, "optimizer_steps_per_epoch": 100,
                "epoch_seconds": 10.0, "validation_seconds_per_epoch": 1.0,
                "checkpoint_seconds_per_epoch": 0.05, "epochs": 3,
                "total_seconds": 33.15, "total_hours": 0.009,
                "budget_hours": 12.0, "within_budget": True,
            },
            "trainable_examples": 800,
            "recommended_shape": {"objective": plp.OBJECTIVE},
        }

    def test_report_contains_no_prompt_text_or_absolute_paths(self):
        identity = self.identity()
        report = plp.render_public_report(identity, self.measurement())
        self.assertNotIn(SEALED_SENTINEL, report)
        self.assertNotIn(self.root, report)
        self.assertNotIn("/Users/", report)

    def test_report_carries_the_aggregate_evidence(self):
        report = plp.render_public_report(self.identity(), self.measurement())
        self.assertIn("local_feasible", report)
        self.assertIn("completion_only_raw_concat", report)
        self.assertIn("agreement", report)
        self.assertIn("1200.0", report)


class IdentityFailClosedTest(IsolationTestCase):

    def test_missing_weight_file_is_an_environment_blocker(self):
        model_dir = self.build_model_dir()
        os.remove(os.path.join(model_dir, "model.safetensors"))
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.identify_model_dir(model_dir)

    def test_embedding_model_directory_is_refused(self):
        model_dir = self.build_model_dir(
            model_type="qwen3",
            architectures=("Qwen3Model", "Qwen3Embedding"))
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.identify_model_dir(model_dir)

    def test_non_causal_directory_is_refused(self):
        model_dir = self.build_model_dir(
            model_type="bert", architectures=("BertForMaskedLM",))
        with self.assertRaises(plp.EnvironmentBlocker):
            plp.identify_model_dir(model_dir)


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
        with self.assertRaises(plp.PilotError):
            plp.load_config(self.write_config(config))

    def test_missing_expected_digest_fails_closed(self):
        config = self.valid_config()
        del config["expected"]["train_sha256"]
        with self.assertRaises(plp.PilotError):
            plp.load_config(self.write_config(config))

    def test_short_digest_fails_closed(self):
        config = self.valid_config()
        config["expected"]["train_sha256"] = "abc"
        with self.assertRaises(plp.PilotError):
            plp.load_config(self.write_config(config))

    def test_run_envelope_is_validated_from_file(self):
        config = self.valid_config()
        config["run"] = {"ranks": [4]}
        with self.assertRaises(plp.PilotError):
            plp.load_config(self.write_config(config))

    def test_valid_config_round_trips(self):
        config = self.valid_config()
        loaded = plp.load_config(self.write_config(config))
        self.assertEqual(loaded["freeze_commit"], config["freeze_commit"])
        self.assertEqual(loaded["run"]["ranks"], [8, 16])


class CliTest(unittest.TestCase):

    def test_self_test_cli_passes(self):
        self.assertEqual(plp.main(["--self-test"]), 0)

    def test_run_without_config_fails_closed(self):
        self.assertEqual(plp.main(["--run"]), 1)

    def test_missing_config_file_fails_closed(self):
        self.assertEqual(plp.main(["--run", "--config",
                                   "/nonexistent/config.json"]), 1)

    def test_self_test_reports_every_check(self):
        checks = plp.self_test()
        self.assertIn("boundary_spanning_token_is_prompt_side", checks)
        self.assertIn("targets_exclude_prompt_side", checks)


if __name__ == "__main__":
    unittest.main()
