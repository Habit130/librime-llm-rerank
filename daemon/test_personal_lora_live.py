#!/usr/bin/env python3
"""Personal LoRA live identity and adapter load (Habit130/squirrel#184)."""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import personal_lora_live as pll
from personal_lora_live import IdentityError
from server import (
    MEAN_TOKEN_POLICY_ID,
    PROTOCOL_VERSION,
    REQUEST_FIELDS,
    ModelState,
    handle_health,
    handle_request,
)


def write_bytes(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def write_text(path, text):
    write_bytes(path, text.encode("utf-8"))


def causal_config():
    return {
        "model_type": "qwen3",
        "architectures": ["Qwen3ForCausalLM"],
        "num_hidden_layers": 2,
        "hidden_size": 8,
    }


def write_model_dir(root, config=None, extra=None):
    os.makedirs(root, exist_ok=True)
    payload = extra or {}
    for name in pll.REQUIRED_MODEL_FILES:
        if name == "config.json":
            write_text(
                os.path.join(root, name),
                json.dumps(config or causal_config()),
            )
        elif name in payload:
            write_bytes(os.path.join(root, name), payload[name])
        else:
            write_bytes(os.path.join(root, name), b"model-file:%s" % name.encode())
    return root


def write_adapter_dir(root, adapter_bytes=b"adapter-bytes", config=None):
    os.makedirs(root, exist_ok=True)
    write_bytes(os.path.join(root, pll.ADAPTER_FILE), adapter_bytes)
    write_text(
        os.path.join(root, pll.ADAPTER_CONFIG_FILE),
        json.dumps(config or {"fine_tune_type": "lora"}),
    )
    return root


def pins_from(model_identity, adapter_identity, versions=None):
    return {
        "model_composite_sha256": model_identity["composite_sha256"],
        "model_safetensors_sha256": model_identity["files"]["model.safetensors"][
            "sha256"
        ],
        "adapter_sha256": adapter_identity["sha256"],
        "adapter_config_sha256": adapter_identity["config_sha256"],
        "versions": versions or dict(pll.PINNED_VERSIONS),
    }


class EstablishedPinTest(unittest.TestCase):
    def test_established_pins_match_the_frozen_contract(self):
        pins = pll.live_pins()
        self.assertEqual(
            "f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa",
            pins["model_composite_sha256"],
        )
        self.assertEqual(
            "cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba",
            pins["model_safetensors_sha256"],
        )
        self.assertEqual(
            "7622f26d71efa34f5b9b1e92ebef2c064bd06363c3eac4c88fb0adb44b1462d9",
            pins["adapter_sha256"],
        )
        self.assertEqual(
            "656e2ea61b91f270bbca559b0d6377cac01ede1de7ea11710893a5a7ad4671b8",
            pins["adapter_config_sha256"],
        )
        self.assertEqual(
            {"mlx": "0.32.0", "mlx-lm": "0.31.3", "numpy": "2.4.6"},
            pins["versions"],
        )


class IdentityPinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lora-live-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.model_dir = os.path.join(self.tmp, "model")
        self.adapter_dir = os.path.join(self.tmp, "adapter")
        write_model_dir(self.model_dir)
        write_adapter_dir(self.adapter_dir)
        self.model_identity = pll.identify_model_dir(self.model_dir)
        self.adapter_identity = pll.identify_adapter(self.adapter_dir)
        self.pins = pins_from(self.model_identity, self.adapter_identity)

    def test_preflight_accepts_matching_fixture_pins(self):
        record = pll.pin_live_identities(
            self.model_dir,
            self.adapter_dir,
            expected=self.pins,
            versions=self.pins["versions"],
        )
        public = pll.public_identity_record(record)
        self.assertEqual(
            self.model_identity["composite_sha256"],
            public["model_composite_sha256"],
        )
        self.assertEqual(
            self.adapter_identity["sha256"], public["adapter_sha256"]
        )
        self.assertEqual("qwen3", public["causal"]["model_type"])
        self.assertIn("Qwen3ForCausalLM", public["causal"]["architectures"])

    def test_wrong_adapter_with_right_base_is_refused(self):
        other = os.path.join(self.tmp, "wrong-adapter")
        write_adapter_dir(other, adapter_bytes=b"not-the-selected-adapter")
        with self.assertRaisesRegex(IdentityError, "adapter identity mismatch"):
            pll.pin_live_identities(
                self.model_dir,
                other,
                expected=self.pins,
                versions=self.pins["versions"],
            )

    def test_wrong_adapter_config_is_refused(self):
        other = os.path.join(self.tmp, "wrong-config")
        with open(os.path.join(self.adapter_dir, pll.ADAPTER_FILE), "rb") as handle:
            adapter_bytes = handle.read()
        write_adapter_dir(
            other,
            adapter_bytes=adapter_bytes,
            config={"fine_tune_type": "lora", "note": "tampered"},
        )
        with self.assertRaisesRegex(
            IdentityError, "adapter_config identity mismatch"
        ):
            pll.pin_live_identities(
                self.model_dir,
                other,
                expected=self.pins,
                versions=self.pins["versions"],
            )

    def test_embedding_architecture_is_refused(self):
        bge = os.path.join(self.tmp, "bge")
        write_model_dir(
            bge,
            config={
                "model_type": "xlm-roberta",
                "architectures": ["XLMRobertaModel", "BGEEmbedding"],
                "num_hidden_layers": 12,
            },
        )
        with self.assertRaisesRegex(IdentityError, "causal qwen3"):
            pll.pin_live_identities(
                bge,
                self.adapter_dir,
                expected=self.pins,
                versions=self.pins["versions"],
            )

    def test_runtime_pin_mismatch_is_refused(self):
        with self.assertRaisesRegex(IdentityError, "pinned runtime mismatch"):
            pll.pin_live_identities(
                self.model_dir,
                self.adapter_dir,
                expected=self.pins,
                versions={"mlx": "0.0.0", "mlx-lm": "0.31.3", "numpy": "2.4.6"},
            )

    def test_skip_identity_env_does_not_waive_pins(self):
        os.environ["LLM_RERANK_SKIP_IDENTITY"] = "1"
        self.addCleanup(os.environ.pop, "LLM_RERANK_SKIP_IDENTITY", None)
        with self.assertRaises(IdentityError):
            pll.pin_live_identities(self.model_dir, self.adapter_dir)

    def test_copy_is_owner_only_and_refuses_train_paths(self):
        dest = os.path.join(self.tmp, "live-copy")
        copied = pll.copy_adapter(
            self.adapter_dir, dest, expected=self.pins
        )
        self.assertEqual(self.adapter_identity["sha256"], copied["sha256"])
        self.assertEqual(0o700, stat.S_IMODE(os.stat(dest).st_mode))
        for name in (pll.ADAPTER_FILE, pll.ADAPTER_CONFIG_FILE):
            self.assertEqual(
                0o600,
                stat.S_IMODE(os.stat(os.path.join(dest, name)).st_mode),
            )
        forbidden = os.path.join(
            self.tmp, "personal-lora-train-183", "selected"
        )
        with self.assertRaisesRegex(IdentityError, "refusing to write"):
            pll.copy_adapter(
                self.adapter_dir, forbidden, expected=self.pins
            )


class LoadAndProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lora-load-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.model_dir = os.path.join(self.tmp, "model")
        self.adapter_dir = os.path.join(self.tmp, "adapter")
        write_model_dir(self.model_dir)
        write_adapter_dir(self.adapter_dir)
        self.model_identity = pll.identify_model_dir(self.model_dir)
        self.adapter_identity = pll.identify_adapter(self.adapter_dir)
        self.pins = pins_from(self.model_identity, self.adapter_identity)

    def _pin(self, model_path, adapter_path, **_kwargs):
        return pll.pin_live_identities(
            model_path,
            adapter_path,
            expected=self.pins,
            versions=self.pins["versions"],
        )

    def test_load_calls_adapter_loader_after_pin(self):
        calls = []

        class Tokenizer:
            pad_token_id = 0
            eos_token_id = 1

        def fake_load(model_path, adapter_path):
            calls.append((model_path, adapter_path))
            return object(), Tokenizer()

        state = ModelState(self.model_dir, adapter_path=self.adapter_dir)
        with mock.patch("server.pin_live_identities", side_effect=self._pin), \
                mock.patch("server.load_adapted_model", side_effect=fake_load):
            state.load()
        self.assertTrue(state.loaded)
        self.assertEqual([(self.model_dir, self.adapter_dir)], calls)
        self.assertEqual(self.adapter_identity["sha256"], state.adapter_digest)

    def test_reuse_revalidates_when_adapter_bytes_change(self):
        class Tokenizer:
            pad_token_id = 0
            eos_token_id = 1

        state = ModelState(self.model_dir, adapter_path=self.adapter_dir)
        fake = mock.Mock(return_value=(object(), Tokenizer()))
        with mock.patch("server.pin_live_identities", side_effect=self._pin), \
                mock.patch("server.load_adapted_model", fake):
            state.load()
            fake.reset_mock()
            state.load()
            fake.assert_not_called()
            write_bytes(
                os.path.join(self.adapter_dir, pll.ADAPTER_FILE),
                b"tampered-adapter",
            )
            with self.assertRaises(IdentityError):
                state.load()
            self.assertFalse(state.loaded)

    def test_health_reports_adapter_digest_without_loading(self):
        state = ModelState(self.model_dir, adapter_path=self.adapter_dir)
        response = handle_health(
            state,
            {
                "version": PROTOCOL_VERSION,
                "request_id": "health-live",
                "kind": "health",
            },
        )
        self.assertFalse(response["health"]["model_loaded"])
        self.assertEqual(
            self.adapter_identity["sha256"],
            response["health"]["adapter_digest"],
        )
        self.assertFalse(state.loaded)

    def test_identity_fault_is_bound_and_does_not_echo_private_text(self):
        class FaultState:
            scoring_strategy = "mean_token"
            loaded = False

            def score(self, context, candidates):
                raise IdentityError("adapter identity mismatch")

        payload = json.dumps({
            "version": PROTOCOL_VERSION,
            "request_id": "req-live",
            "plan_identity": "plan-live",
            "baseline_policy_id": MEAN_TOKEN_POLICY_ID,
            "context": "private context fixture",
            "candidates": ["candidate-a", "candidate-b"],
        })
        response = handle_request(FaultState(), payload)
        self.assertEqual("identity_mismatch", response["error"]["code"])
        self.assertEqual("req-live", response["request_id"])
        self.assertEqual("plan-live", response["plan_identity"])
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))

    def test_scoring_protocol_fields_are_unchanged(self):
        self.assertEqual(
            {
                "version",
                "request_id",
                "plan_identity",
                "baseline_policy_id",
                "context",
                "candidates",
            },
            REQUEST_FIELDS,
        )
        payload = json.dumps({
            "version": PROTOCOL_VERSION,
            "request_id": "req-extra",
            "plan_identity": "plan-extra",
            "baseline_policy_id": MEAN_TOKEN_POLICY_ID,
            "context": "ctx",
            "candidates": ["他们", "它们"],
            "adapter": self.adapter_identity["sha256"],
        })
        response = handle_request(ModelState(self.model_dir), payload)
        self.assertEqual("invalid_request", response["error"]["code"])


if __name__ == "__main__":
    unittest.main()
