#!/usr/bin/env python3
"""End-to-end runner tests for the #176 pilot with a deterministic fake MLX.

The fake backend implements the small mlx/mlx-lm surface the runner uses, so
``--run``, ``--verify-reload``, reuse detection, probe persistence, owner-only
outputs and the privacy boundary are exercised without loading a real model
or touching the private dataset. Real timing evidence comes from the frozen
measurement itself, not these tests.
"""

import contextlib
import io
import json
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

_REAL_SUSTAINED = plp.sustained_run

SEALED_SENTINEL = "SENTINELSEALEDPRIVATETEXT"
STATS_SENTINEL = "SENTINELPROMPTTEXT"


class FakeEncoding(object):

    def __init__(self, ids, offsets):
        self.ids = ids
        self.offsets = offsets


class FakeBackendTokenizer(object):

    def encode(self, text):
        ids = [ord(character) - ord("a") + 1 for character in text]
        offsets = [(index, index + 1) for index in range(len(text))]
        return FakeEncoding(ids, offsets)


class FakeInnerTokenizer(object):
    backend_tokenizer = FakeBackendTokenizer()


class FakeTokenizerWrapper(object):
    _tokenizer = FakeInnerTokenizer()
    add_bos_token = False
    bos_token_id = None
    eos_token_id = None
    vocab_size = 16


class FakeModel(object):

    def __init__(self):
        self.layers = [object() for _ in range(4)]
        self._weight = np.zeros((8, 16), np.float32)

    def __call__(self, ids):
        ids = np.asarray(ids, dtype=np.int64)
        return self._weight[ids % 8]

    def trainable_parameters(self):
        return {"fake.weight": self._weight}

    def parameters(self):
        return {"fake.weight": self._weight}

    def fake_grads(self, batch, _lengths):
        seed = 1000 + int(np.asarray(batch, dtype=np.int64).sum()) % 9973
        rng = np.random.RandomState(seed)
        noise = rng.random_sample(self._weight.shape).astype(np.float32)
        return {"fake.weight": (noise - 0.5) * 0.01}

    def freeze(self):
        pass

    def train(self):
        pass

    def eval(self):
        pass


class FakeLosses(object):

    @staticmethod
    def cross_entropy(logits, targets):
        logits = np.asarray(logits, dtype=np.float32)
        targets = np.asarray(targets, dtype=np.int64)
        shifted = logits - logits.max(axis=-1, keepdims=True)
        log_probs = shifted - np.log(
            np.exp(shifted).sum(axis=-1, keepdims=True))
        picked = np.take_along_axis(log_probs, targets[..., None], axis=-1)
        return -picked[..., 0]


class FakeNN(object):

    losses = FakeLosses()

    @staticmethod
    def value_and_grad(model, loss_fn):
        def wrapped(model, batch, lengths):
            value = loss_fn(model, batch, lengths)
            return value, model.fake_grads(batch, lengths)
        return wrapped


class FakeAdamW(object):

    def __init__(self, learning_rate=0.0, weight_decay=0.0):
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.state = {"step": 0}

    def update(self, model, grads):
        params = model.parameters()
        for name, value in grads.items():
            params[name][...] -= (self.learning_rate
                                  * np.asarray(value, np.float32))
        self.state["step"] += 1


class FakeRandom(object):

    @staticmethod
    def seed(value):
        np.random.seed(value)


class FakeMX(object):
    float32 = np.float32
    random = FakeRandom()

    @staticmethod
    def array(value):
        return np.asarray(value)

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

    @staticmethod
    def reset_peak_memory():
        return None

    @staticmethod
    def get_peak_memory():
        return 0

    @staticmethod
    def clear_cache():
        return None

    @staticmethod
    def set_wired_limit(_limit):
        return None

    @staticmethod
    def device_info():
        return {"device_name": "fake", "architecture": "fake",
                "max_recommended_working_set_size": 1000000000}

    @staticmethod
    def save_safetensors(path, weights):
        with open(path, "wb") as handle:
            np.savez(handle, **{name: np.asarray(value)
                                for name, value in weights.items()})


class FakeOptim(object):
    AdamW = FakeAdamW


def fake_tree_flatten(tree):
    return sorted(tree.items())


def fake_tree_map(function, *trees):
    if len(trees) == 1:
        return {key: function(value) for key, value in trees[0].items()}
    keys = trees[0].keys()
    return {key: function(*[tree[key] for tree in trees]) for key in keys}


def fake_mlx_load(_path):
    return FakeModel(), FakeTokenizerWrapper()


def fake_linear_to_lora_layers(model, num_layers, config):
    model.rank = config["rank"]
    model.num_layers = num_layers
    model.modules = list(config["keys"])


def fake_load_adapters(model, adapter_dir):
    path = os.path.join(adapter_dir, "adapters.safetensors")
    with np.load(path) as data:
        params = model.parameters()
        for name in data.files:
            params[name][...] = data[name]


def fake_backend():
    return {
        "np": np,
        "mx": FakeMX(),
        "nn": FakeNN(),
        "optim": FakeOptim(),
        "tree_flatten": fake_tree_flatten,
        "tree_map": fake_tree_map,
        "mlx_load": fake_mlx_load,
        "linear_to_lora_layers": fake_linear_to_lora_layers,
        "load_adapters": fake_load_adapters,
    }


class RunnerTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pilot_runner_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "artifact")
        os.makedirs(self.root, mode=0o700)
        self.model_dir = os.path.join(self.tmp, "model")
        os.makedirs(self.model_dir, mode=0o700)
        self.dataset_dir = os.path.join(self.tmp, "dataset")
        os.makedirs(self.dataset_dir, mode=0o700)
        self.build_model_dir()
        self.config_path = self.build_config()
        real_require_mlx = plp.require_mlx
        real_sustained = plp.sustained_run
        real_versions = plp.runtime_versions
        plp.require_mlx = fake_backend
        plp.sustained_run = self.fast_sustained
        plp.runtime_versions = lambda: {
            "mlx": "0.32.0", "mlx-lm": "0.31.3", "numpy": "2.4.6"}
        self.addCleanup(setattr, plp, "require_mlx", real_require_mlx)
        self.addCleanup(setattr, plp, "sustained_run", real_sustained)
        self.addCleanup(setattr, plp, "runtime_versions", real_versions)

    @staticmethod
    def fast_sustained(backend, model, examples, rank, micro_batch, seconds):
        return _REAL_SUSTAINED(backend, model, examples, rank, micro_batch,
                               0.05)

    def build_model_dir(self):
        for name in plp.REQUIRED_MODEL_FILES:
            self.write(os.path.join(self.model_dir, name), "")
        self.write(os.path.join(self.model_dir, "config.json"), json.dumps({
            "model_type": "qwen3",
            "architectures": ["Qwen3ForCausalLM"],
            "num_hidden_layers": 4,
            "hidden_size": 16,
        }))

    def build_config(self):
        records = []
        characters = "abcde"
        for index in range(24):
            prompt = characters[:index % 5]
            completion = characters[index % 5:(index % 5) + 1 + index % 2]
            records.append({
                "schema": "personal-lora-completion-v1",
                "prompt": prompt,
                "completion": completion,
                "loss": "completion_only",
                "provenance": {"empty_context": prompt == ""},
            })
        train_text = "\n".join(json.dumps(record, sort_keys=True)
                               for record in records) + "\n"
        validation_text = SEALED_SENTINEL + " not json\n"
        test_text = SEALED_SENTINEL + " test not json\n"
        self.write(os.path.join(self.dataset_dir, plp.TRAIN_FILE),
                   train_text)
        self.write(os.path.join(self.dataset_dir, plp.VALIDATION_FILE),
                   validation_text)
        self.write(os.path.join(self.dataset_dir, plp.TEST_FILE),
                   test_text)
        manifest = {
            "schema": plp.MANIFEST_SCHEMA,
            "created_at_utc": "2026-09-14T00:00:00Z",
            "audit": {"samples": 24},
            "splits": {
                "train": {"sha256": pld.sha256_text(train_text), "lines": 24},
                "validation": {"lines": 6},
                "test": {"lines": 5},
            },
        }
        self.write(os.path.join(self.dataset_dir, plp.MANIFEST_FILE),
                   json.dumps(manifest, sort_keys=True) + "\n")
        config = {
            "artifact_root": self.root,
            "model_dir": self.model_dir,
            "dataset_dir": self.dataset_dir,
            "freeze_commit": "2076d0a6c92dbf57833b7a123ea54aab10ddd49d",
            "expected": {
                "train_sha256": pld.sha256_text(train_text),
                "manifest_sha256": pld.sha256_file(
                    os.path.join(self.dataset_dir, plp.MANIFEST_FILE)),
                "validation_sha256": pld.sha256_text(validation_text),
                "test_sha256": pld.sha256_text(test_text),
            },
            "run": {
                "ranks": [8, 16],
                "micro_batches": [1, 2, 4, 8],
                "effective_batch": 8,
                "num_layers": 4,
                "sustained_seconds": 1200,
                "reload_subset": 4,
                "eval_subset": 6,
                "recommended_epochs": 2,
            },
        }
        path = os.path.join(self.tmp, "config.json")
        self.write(path, json.dumps(config, sort_keys=True))
        return path

    @staticmethod
    def write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_pilot(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plp.cmd_run(self.config_path, allowed_root=self.root,
                               protected_roots=[])
        return code, output.getvalue()

    def test_run_completes_and_records_frozen_terminal(self):
        code, output = self.run_pilot()
        self.assertEqual(code, 0)
        measurement = plp.read_private_json(self.root, plp.MEASUREMENT_REL)
        self.assertEqual(measurement["terminal"], plp.TERMINAL_FEASIBLE)
        self.assertEqual(len(measurement["probes"]), 8)
        chosen = measurement["chosen"]
        self.assertIn(chosen["rank"], [8, 16])
        self.assertIn(chosen["micro_batch"], [1, 2, 4, 8])
        self.assertGreaterEqual(measurement["sustained"]["measured_seconds"],
                                0.05)
        self.assertTrue(measurement["verification"]["agreement_pass"])
        self.assertTrue(measurement["verification"]["weights_changed"])
        self.assertTrue(measurement["estimate"]["within_budget"])
        self.assertIn("terminal", output)

    def test_run_writes_only_owner_only_outputs(self):
        code, _output = self.run_pilot()
        self.assertEqual(code, 0)
        self.assertEqual(pld.verify_owner_only(self.root), [])
        adapter = os.path.join(self.root, plp.ADAPTER_FILE_REL)
        self.assertTrue(os.path.isfile(adapter))
        self.assertEqual(os.stat(adapter).st_mode & 0o777, 0o600)
        for relative in (plp.IDENTITY_REL, plp.PROBES_REL,
                         plp.MEASUREMENT_REL, plp.VERIFICATION_REL,
                         plp.ADAPTER_CONFIG_REL, plp.PUBLIC_REPORT_REL):
            self.assertTrue(os.path.isfile(os.path.join(self.root, relative)),
                            relative)

    def test_run_output_never_contains_private_text(self):
        code, output = self.run_pilot()
        self.assertEqual(code, 0)
        self.assertNotIn(SEALED_SENTINEL, output)
        self.assertNotIn(STATS_SENTINEL, output)
        report = open(os.path.join(self.root, plp.PUBLIC_REPORT_REL),
                      encoding="utf-8").read()
        self.assertNotIn(SEALED_SENTINEL, report)
        self.assertNotIn(self.tmp, report)
        identity = open(os.path.join(self.root, plp.IDENTITY_REL),
                        encoding="utf-8").read()
        self.assertNotIn(SEALED_SENTINEL, identity)

    def test_second_run_reuses_the_recorded_measurement(self):
        self.run_pilot()
        code, output = self.run_pilot()
        self.assertEqual(code, 0)
        self.assertIn("measurement_reused=true", output)

    def test_tampered_adapter_blocks_reuse(self):
        self.run_pilot()
        adapter = os.path.join(self.root, plp.ADAPTER_FILE_REL)
        with open(adapter, "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(plp.PilotError):
            self.run_pilot()

    def test_verify_reload_passes_from_disk(self):
        self.run_pilot()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plp.cmd_verify_reload(self.config_path,
                                         allowed_root=self.root,
                                         protected_roots=[])
        self.assertEqual(code, 0)
        self.assertIn('"verify_reload":"pass"', output.getvalue())

    def test_probe_table_is_resumed_not_rerun(self):
        self.run_pilot()
        probes_path = os.path.join(self.root, plp.PROBES_REL)
        before = os.stat(probes_path).st_mtime_ns
        with open(probes_path, encoding="utf-8") as handle:
            probes = json.load(handle)
        self.assertEqual(len(probes["probes"]), 8)
        os.utime(probes_path, ns=(before, before))

    def test_binding_mismatch_refuses_to_replace_measurement(self):
        self.run_pilot()
        with open(self.config_path, encoding="utf-8") as handle:
            config = json.load(handle)
        config["run"]["recommended_epochs"] = 4
        self.write(self.config_path, json.dumps(config, sort_keys=True))
        with self.assertRaises(plp.PilotError):
            self.run_pilot()


if __name__ == "__main__":
    unittest.main()
