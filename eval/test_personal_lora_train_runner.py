#!/usr/bin/env python3
"""End-to-end runner tests for #183 with a deterministic fake MLX.

The fake backend implements the small mlx/mlx-lm surface the runner uses, so
``--run``, ``--verify-reload``, checkpoint selection, reuse/immutability,
resume after a blocker, cache clearing and the privacy boundary are exercised
without loading a real model or touching the private dataset. Real training
evidence comes from the frozen run itself, not these tests.
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
import personal_lora_train as plt  # noqa: E402

SEALED_SENTINEL = "SENTINELSEALEDPRIVATETEXT"
TEXT_SENTINEL = "zzsentinelprivatetextzz"


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
    vocab_size = 32


class FakeModel(object):

    def __init__(self):
        self.layers = [object() for _ in range(4)]
        self._weight = np.zeros((8, 32), np.float32)

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
    cache_memory = 0
    clear_calls = 0

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
    def get_active_memory():
        return 0

    @classmethod
    def get_cache_memory(cls):
        return cls.cache_memory

    @classmethod
    def clear_cache(cls):
        cls.clear_calls += 1
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


LOAD_ADAPTER_CALLS = []
LOAD_WEIGHT_CALLS = []


def fake_mlx_load(_path):
    return FakeModel(), FakeTokenizerWrapper()


def fake_linear_to_lora_layers(model, num_layers, config):
    model.rank = config["rank"]
    model.num_layers = num_layers
    model.modules = list(config["keys"])


def fake_load_adapters(model, adapter_dir):
    LOAD_ADAPTER_CALLS.append(os.path.basename(adapter_dir))
    path = os.path.join(adapter_dir, "adapters.safetensors")
    with np.load(path) as data:
        params = model.parameters()
        for name in data.files:
            params[name][...] = data[name]


def fake_load_weights(model, path):
    LOAD_WEIGHT_CALLS.append(os.path.basename(os.path.dirname(path)))
    with np.load(path) as data:
        params = model.parameters()
        for name in data.files:
            params[name][...] = data[name]


def fake_backend():
    return {
        "np": np,
        "mx": FakeMX,
        "nn": FakeNN(),
        "optim": FakeOptim(),
        "tree_flatten": fake_tree_flatten,
        "tree_map": fake_tree_map,
        "mlx_load": fake_mlx_load,
        "linear_to_lora_layers": fake_linear_to_lora_layers,
        "load_adapters": fake_load_adapters,
        "load_weights": fake_load_weights,
    }


class RunnerTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="train_runner_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "artifact")
        os.makedirs(self.root, mode=0o700)
        self.model_dir = os.path.join(self.tmp, "model")
        os.makedirs(self.model_dir, mode=0o700)
        self.dataset_dir = os.path.join(self.tmp, "dataset")
        os.makedirs(self.dataset_dir, mode=0o700)
        self.build_model_dir()
        self.config_path = self.build_config()
        FakeMX.cache_memory = 0
        FakeMX.clear_calls = 0
        LOAD_ADAPTER_CALLS[:] = []
        LOAD_WEIGHT_CALLS[:] = []
        real_require_mlx = plt.require_mlx
        real_versions = plp.runtime_versions
        plt.require_mlx = fake_backend
        plp.runtime_versions = lambda: {
            "mlx": "0.32.0", "mlx-lm": "0.31.3", "numpy": "2.4.6"}
        self.addCleanup(setattr, plt, "require_mlx", real_require_mlx)
        self.addCleanup(setattr, plp, "runtime_versions", real_versions)
        config = json.loads(open(self.config_path, encoding="utf-8").read())
        frozen_values = {
            "FROZEN_MODEL_COMPOSITE_SHA256":
                config["expected"]["model_composite_sha256"],
            "FROZEN_DATASET_DIGESTS": {
                key: config["expected"][key]
                for key in ("train_sha256", "validation_sha256",
                            "manifest_sha256", "test_sha256")},
            "FROZEN_FREEZE_COMMIT": config["freeze_commit"],
        }
        for name, value in frozen_values.items():
            self.addCleanup(setattr, plt, name, getattr(plt, name))
            setattr(plt, name, value)

    def build_model_dir(self):
        for name in plp.REQUIRED_MODEL_FILES:
            self.write(os.path.join(self.model_dir, name), "")
        self.write(os.path.join(self.model_dir, "config.json"), json.dumps({
            "model_type": "qwen3",
            "architectures": ["Qwen3ForCausalLM"],
            "num_hidden_layers": 4,
            "hidden_size": 16,
        }))

    def train_text(self):
        records = []
        characters = "abcde"
        for index in range(24):
            prompt = characters[:index % 5]
            completion = characters[index % 5:(index % 5) + 1 + index % 2]
            records.append({
                "schema": plp.DATASET_SCHEMA,
                "prompt": prompt,
                "completion": completion,
                "loss": "completion_only",
                "provenance": {"empty_context": prompt == ""},
            })
        return "\n".join(json.dumps(record, sort_keys=True)
                         for record in records) + "\n"

    def validation_text(self):
        records = []
        characters = "abcde"
        for index in range(8):
            prompt = characters[:index % 4]
            if index == 0:
                prompt = TEXT_SENTINEL + prompt
            completion = characters[index % 4:(index % 4) + 1]
            records.append({
                "schema": plp.DATASET_SCHEMA,
                "prompt": prompt,
                "completion": completion,
                "loss": "completion_only",
                "provenance": {"empty_context": prompt == ""},
            })
        return "\n".join(json.dumps(record, sort_keys=True)
                         for record in records) + "\n"

    def build_config(self):
        train_text = self.train_text()
        validation_text = self.validation_text()
        test_text = SEALED_SENTINEL + " not json\n"
        self.write(os.path.join(self.dataset_dir, plp.TRAIN_FILE),
                   train_text)
        self.write(os.path.join(self.dataset_dir, plp.VALIDATION_FILE),
                   validation_text)
        self.write(os.path.join(self.dataset_dir, plp.TEST_FILE), test_text)
        manifest = {
            "schema": plp.MANIFEST_SCHEMA,
            "created_at_utc": "2026-09-14T00:00:00Z",
            "audit": {"samples": 24},
            "splits": {
                "parts": {
                    "train": {"sha256": pld.sha256_text(train_text),
                              "lines": 24},
                    "validation": {"lines": 8},
                    "test": {"lines": 1},
                },
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
                "model_composite_sha256":
                    plp.identify_model_dir(self.model_dir)["composite_sha256"],
            },
            "run": {
                "epochs": 3,
                "rank": 16,
                "micro_batch": 8,
                "learning_rate": 1e-4,
                "seed": 176,
            },
        }
        path = os.path.join(self.tmp, "config.json")
        self.write(path, json.dumps(config, sort_keys=True))
        return path

    @staticmethod
    def write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_train(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plt.cmd_run(self.config_path, allowed_root=self.root,
                               protected_roots=[])
        return code, output.getvalue()

    def run_verify(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plt.cmd_verify_reload(self.config_path,
                                         allowed_root=self.root,
                                         protected_roots=[])
        return code, output.getvalue()

    def read_json(self, relative):
        return plt.read_private_json(self.root, relative)

    def test_run_trains_three_epochs_and_selects_the_predeclared_checkpoint(self):
        code, output = self.run_train()
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_TRAINED)
        measurement = self.read_json(plt.MEASUREMENT_REL)
        rows = measurement["epochs"]
        self.assertEqual([row["epoch"] for row in rows], [1, 2, 3])
        self.assertEqual(state["selected_epoch"],
                         plt.select_epoch(rows)["epoch"])
        self.assertGreater(state["wall_clock_seconds"], 0.0)
        self.assertTrue(measurement["within_budget"])
        self.assertLessEqual(measurement["training_seconds"],
                             measurement["wall_clock_seconds"])
        verification = measurement["verification"]
        self.assertTrue(verification["agreement_pass"])
        self.assertTrue(verification["weights_changed"])
        self.assertEqual(verification["selected_epoch"],
                         state["selected_epoch"])
        self.assertLessEqual(verification["max_abs_diff"],
                             plt.RELOAD_TOLERANCE)
        for epoch in (1, 2, 3):
            directory = os.path.join(self.root, "epochs", "epoch-%d" % epoch)
            self.assertTrue(os.path.isfile(
                os.path.join(directory, "adapters.safetensors")))
            self.assertTrue(os.path.isfile(
                os.path.join(directory, "adapter_config.json")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.root, plt.SELECTED_DIR_REL, "adapters.safetensors")))
        self.assertEqual(LOAD_ADAPTER_CALLS, ["selected"])
        self.assertEqual(measurement["trainable_examples"], 21)
        self.assertEqual(measurement["untrainable_examples"], 3)
        self.assertIn("terminal", output)

    def test_epochs_use_the_frozen_batch_plan(self):
        self.run_train()
        measurement = self.read_json(plt.MEASUREMENT_REL)
        for row in measurement["epochs"]:
            expected = plt.epoch_batches(measurement["trainable_examples"],
                                         row["epoch"])
            self.assertEqual(row["steps"], len(expected))

    def test_cache_guard_clears_above_the_threshold_and_once_per_epoch(self):
        FakeMX.cache_memory = plt.CACHE_CLEAR_THRESHOLD_BYTES + 1
        code, _output = self.run_train()
        self.assertEqual(code, 0)
        measurement = self.read_json(plt.MEASUREMENT_REL)
        self.assertGreater(measurement["cache_clears"]["threshold"], 0)
        self.assertEqual(measurement["cache_clears"]["epoch_floor"], 3)
        for row in measurement["epochs"]:
            self.assertGreaterEqual(row["cache_clears"]["threshold"], 1)
            self.assertEqual(row["cache_clears"]["epoch_floor"], 1)

    def test_run_writes_only_owner_only_outputs(self):
        code, _output = self.run_train()
        self.assertEqual(code, 0)
        self.assertEqual(pld.verify_owner_only(self.root), [])
        adapter = os.path.join(self.root, plt.SELECTED_DIR_REL,
                               "adapters.safetensors")
        self.assertEqual(os.stat(adapter).st_mode & 0o777, 0o600)
        for relative in (plt.IDENTITY_REL, plt.STATE_REL, plt.EPOCHS_REL,
                         plt.MEASUREMENT_REL, plt.VERIFICATION_REL,
                         plt.PUBLIC_REPORT_REL,
                         plt.SELECTED_DIR_REL + "/adapter_config.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.root, relative)),
                            relative)

    def test_run_output_never_contains_private_text(self):
        code, output = self.run_train()
        self.assertEqual(code, 0)
        self.assertNotIn(TEXT_SENTINEL, output)
        self.assertNotIn(SEALED_SENTINEL, output)
        for relative in (plt.PUBLIC_REPORT_REL, plt.IDENTITY_REL,
                         plt.MEASUREMENT_REL, plt.STATE_REL,
                         plt.EPOCHS_REL):
            with open(os.path.join(self.root, relative),
                      encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn(TEXT_SENTINEL, text, relative)
            self.assertNotIn(SEALED_SENTINEL, text, relative)
            self.assertNotIn(self.tmp, text, relative)

    def test_report_carries_the_contract_evidence(self):
        self.run_train()
        report = os.path.join(self.root, plt.PUBLIC_REPORT_REL)
        with open(report, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("trained", text)
        self.assertIn(plt.SELECTION_RULE, text)
        self.assertIn("lowest validation", text)
        self.assertIn("agreement", text)
        self.assertIn("model.safetensors", text)
        self.assertIn("selected epoch", text)

    def test_second_run_reuses_and_never_rewrites_recorded_identity(self):
        self.run_train()
        recorded = {}
        for relative in (plt.IDENTITY_REL, plt.STATE_REL, plt.MEASUREMENT_REL,
                         plt.PUBLIC_REPORT_REL):
            with open(os.path.join(self.root, relative), "rb") as handle:
                recorded[relative] = handle.read()
        code, output = self.run_train()
        self.assertEqual(code, 0)
        self.assertIn("run_reused=true", output)
        for relative, expected in recorded.items():
            with open(os.path.join(self.root, relative), "rb") as handle:
                self.assertEqual(handle.read(), expected, relative)

    def test_tampered_selected_adapter_blocks_reuse(self):
        self.run_train()
        adapter = os.path.join(self.root, plt.SELECTED_DIR_REL,
                               "adapters.safetensors")
        with open(adapter, "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(plt.TrainError):
            self.run_train()

    def test_binding_mismatch_refuses_to_replace_the_run(self):
        self.run_train()
        state_path = os.path.join(self.root, plt.STATE_REL)
        state = json.loads(open(state_path, encoding="utf-8").read())
        state["binding"]["tool_sha256"] = "0" * 64
        self.write(state_path, json.dumps(state, sort_keys=True))
        with self.assertRaises(plt.TrainError):
            self.run_train()

    def test_identity_without_state_fails_closed(self):
        self.write(os.path.join(self.root, plt.IDENTITY_REL), "{}\n")
        with self.assertRaises(plt.TrainError):
            self.run_train()

    def test_verify_reload_passes_from_disk(self):
        self.run_train()
        code, output = self.run_verify()
        self.assertEqual(code, 0)
        self.assertIn('"verify_reload":"pass"', output)

    def test_verify_reload_fails_on_a_tampered_adapter(self):
        self.run_train()
        adapter = os.path.join(self.root, plt.SELECTED_DIR_REL,
                               "adapters.safetensors")
        with open(adapter, "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(plt.TrainError):
            self.run_verify()

    def test_capacity_blocker_leaves_a_resumable_artifact(self):
        FakeMX.cache_memory = plt.CACHE_CLEAR_THRESHOLD_BYTES + 1
        real_train_epoch = plt.train_epoch
        raised = {"done": False}

        def flaky(backend, model, optimizer, loss_and_grad, examples, epoch,
                  stats, counters, deadline=None):
            if epoch == 2 and not raised["done"]:
                raised["done"] = True
                raise plt.CapacityBlocker("simulated out of memory")
            return real_train_epoch(backend, model, optimizer, loss_and_grad,
                                    examples, epoch, stats, counters, deadline)

        plt.train_epoch = flaky
        try:
            code, _output = self.run_train()
        finally:
            plt.train_epoch = real_train_epoch
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_CAPACITY)
        self.assertEqual(state["next_epoch"], 2)
        rows = self.read_json(plt.EPOCHS_REL)["rows"]
        self.assertEqual([row["epoch"] for row in rows], [1])
        first_loss = rows[0]["validation_loss"]
        self.assertTrue(os.path.isfile(os.path.join(
            self.root, "epochs", "epoch-1", "adapters.safetensors")))
        code, _output = self.run_train()
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_TRAINED)
        self.assertEqual(state["resumed_from_epoch"], 2)
        measurement = self.read_json(plt.MEASUREMENT_REL)
        self.assertEqual(measurement["resumed_from_epoch"], 2)
        rows = measurement["epochs"]
        self.assertEqual([row["epoch"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0]["validation_loss"], first_loss)
        self.assertEqual(measurement["cache_clears"]["threshold"],
                         sum(row["cache_clears"]["threshold"]
                             for row in rows))
        self.assertEqual(measurement["cache_clears"]["epoch_floor"],
                         sum(row["cache_clears"]["epoch_floor"]
                             for row in rows))
        self.assertEqual(LOAD_WEIGHT_CALLS, ["epoch-1"])

    def test_runtime_budget_blocker_then_resume(self):
        real_budget = plt.BUDGET_SECONDS
        plt.BUDGET_SECONDS = -1.0
        try:
            code, _output = self.run_train()
        finally:
            plt.BUDGET_SECONDS = real_budget
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_RUNTIME)
        self.assertEqual(state["next_epoch"], 1)
        measurement = self.read_json(plt.MEASUREMENT_REL)
        self.assertFalse(measurement["within_budget"])
        self.assertEqual(measurement["epochs"], [])
        code, _output = self.run_train()
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_TRAINED)
        self.assertEqual(state["resumed_from_epoch"], 1)
        self.assertEqual(len(self.read_json(plt.MEASUREMENT_REL)["epochs"]),
                         3)

    def test_every_config_deviation_fails_before_any_write(self):
        for key, value in (("learning_rate", 2e-4), ("rank", 8),
                           ("epochs", 4), ("micro_batch", 4)):
            config = json.loads(open(self.config_path,
                                     encoding="utf-8").read())
            config["run"][key] = value
            self.write(self.config_path, json.dumps(config, sort_keys=True))
            with self.assertRaises(plt.TrainError):
                self.run_train()
            self.assertFalse(os.path.exists(
                os.path.join(self.root, plt.STATE_REL)))
        self.build_config()

    def test_model_identity_mismatch_is_an_environment_blocker(self):
        config = json.loads(open(self.config_path,
                                 encoding="utf-8").read())
        config["expected"]["model_composite_sha256"] = "0" * 64
        self.write(self.config_path, json.dumps(config, sort_keys=True))
        with self.assertRaises(plt.EnvironmentBlocker):
            self.run_train()

    def test_self_consistent_config_cannot_override_the_frozen_identity(self):
        train_path = os.path.join(self.dataset_dir, plp.TRAIN_FILE)
        with open(train_path, encoding="utf-8") as handle:
            train_text = handle.read()
        extra = json.dumps({
            "schema": plp.DATASET_SCHEMA, "prompt": "a", "completion": "b",
            "loss": "completion_only",
            "provenance": {"empty_context": False},
        }) + "\n"
        self.write(train_path, train_text + extra)
        manifest_path = os.path.join(self.dataset_dir, plp.MANIFEST_FILE)
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["splits"]["parts"]["train"] = {
            "sha256": pld.sha256_text(train_text + extra), "lines": 25}
        self.write(manifest_path, json.dumps(manifest, sort_keys=True)
                   + "\n")
        config = json.loads(open(self.config_path, encoding="utf-8").read())
        config["expected"]["train_sha256"] = pld.sha256_text(train_text
                                                             + extra)
        config["expected"]["manifest_sha256"] = pld.sha256_file(manifest_path)
        self.write(self.config_path, json.dumps(config, sort_keys=True))
        with self.assertRaises(plt.EnvironmentBlocker):
            self.run_train()

    def test_num_layers_must_cover_all_decoder_layers(self):
        config = json.loads(open(self.config_path, encoding="utf-8").read())
        config["run"]["num_layers"] = 1
        self.write(self.config_path, json.dumps(config, sort_keys=True))
        with self.assertRaises(plt.TrainError):
            self.run_train()
        self.assertFalse(os.path.exists(
            os.path.join(self.root, plt.STATE_REL)))

    def test_selection_only_resume_after_a_crash_following_epoch_three(self):
        real_select = plt.select_epoch
        raised = {"done": False}

        def flaky(rows):
            if not raised["done"]:
                raised["done"] = True
                raise RuntimeError("simulated crash before selection")
            return real_select(rows)

        plt.select_epoch = flaky
        try:
            with self.assertRaises(RuntimeError):
                self.run_train()
        finally:
            plt.select_epoch = real_select
        state = self.read_json(plt.STATE_REL)
        self.assertIsNone(state["terminal"])
        self.assertEqual(state["next_epoch"], 4)
        before = [row["checkpoint"]["adapter_sha256"] for row in
                  self.read_json(plt.EPOCHS_REL)["rows"]]
        self.assertEqual(len(before), 3)
        LOAD_WEIGHT_CALLS[:] = []
        code, _output = self.run_train()
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_TRAINED)
        self.assertEqual(state["resumed_from_epoch"], 4)
        after = [row["checkpoint"]["adapter_sha256"] for row in
                 self.read_json(plt.EPOCHS_REL)["rows"]]
        self.assertEqual(after, before)
        self.assertEqual(LOAD_WEIGHT_CALLS, ["epoch-3"])

    def test_overrun_after_the_epochs_finalizes_then_reports_runtime_blocker(self):
        real_select = plt.select_epoch
        real_budget = plt.BUDGET_SECONDS

        def select_and_tighten(rows):
            plt.BUDGET_SECONDS = -1.0
            return real_select(rows)

        plt.select_epoch = select_and_tighten
        try:
            code, _output = self.run_train()
        finally:
            plt.select_epoch = real_select
            plt.BUDGET_SECONDS = real_budget
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_RUNTIME)
        self.assertEqual(state["next_epoch"], 4)
        self.assertFalse(self.read_json(plt.MEASUREMENT_REL)["within_budget"])
        self.assertTrue(os.path.isfile(os.path.join(
            self.root, plt.SELECTED_DIR_REL, "adapters.safetensors")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.root, plt.VERIFICATION_REL)))
        code, _output = self.run_train()
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_TRAINED)
        self.assertEqual(state["resumed_from_epoch"], 4)

    def test_training_budget_overrun_is_explicitly_non_resumable(self):
        real_epoch = plt.run_one_epoch
        calls = {"count": 0}

        def slow_epoch(*args, **kwargs):
            row = real_epoch(*args, **kwargs)
            calls["count"] += 1
            if calls["count"] == 1:
                row = dict(row)
                row["seconds"] = row["seconds"] + plt.BUDGET_SECONDS
            return row

        plt.run_one_epoch = slow_epoch
        try:
            code, _output = self.run_train()
        finally:
            plt.run_one_epoch = real_epoch
        self.assertEqual(code, 0)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_RUNTIME)
        self.assertEqual(state["next_epoch"], 2)
        rows = self.read_json(plt.EPOCHS_REL)["rows"]
        self.assertEqual([row["epoch"] for row in rows], [1])
        code, output = self.run_train()
        self.assertEqual(code, 0)
        self.assertIn("does not grant fresh training time", output)
        state = self.read_json(plt.STATE_REL)
        self.assertEqual(state["terminal"], plt.TERMINAL_RUNTIME)
        self.assertEqual([row["epoch"] for row in
                          self.read_json(plt.EPOCHS_REL)["rows"]], [1])

    def test_tampered_epoch_checkpoint_blocks_resume(self):
        real_epoch = plt.train_epoch
        raised = {"done": False}

        def flaky(backend, model, optimizer, loss_and_grad, examples, epoch,
                  stats, counters, deadline=None):
            if epoch == 2 and not raised["done"]:
                raised["done"] = True
                raise plt.CapacityBlocker("simulated out of memory")
            return real_epoch(backend, model, optimizer, loss_and_grad,
                              examples, epoch, stats, counters, deadline)

        plt.train_epoch = flaky
        try:
            code, _output = self.run_train()
        finally:
            plt.train_epoch = real_epoch
        self.assertEqual(code, 0)
        checkpoint = os.path.join(self.root, "epochs", "epoch-1",
                                  "adapters.safetensors")
        with open(checkpoint, "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(plt.TrainError):
            self.run_train()

    def test_non_owner_only_file_refuses_the_run(self):
        note = os.path.join(self.root, "operator-note.txt")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write("x")
        os.chmod(note, 0o644)
        with self.assertRaises(plt.TrainError):
            self.run_train()
        self.assertFalse(os.path.exists(
            os.path.join(self.root, plt.STATE_REL)))

    def test_permission_violation_blocks_reuse(self):
        self.run_train()
        note = os.path.join(self.root, "operator-note.txt")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write("x")
        os.chmod(note, 0o644)
        with self.assertRaises(plt.TrainError):
            self.run_train()

    def test_verify_reload_rejects_changed_inputs(self):
        self.run_train()
        vocab = os.path.join(self.model_dir, "vocab.json")
        with open(vocab, "a", encoding="utf-8") as handle:
            handle.write("x")
        with self.assertRaises(plt.EnvironmentBlocker):
            self.run_verify()

    def test_verify_reload_rejects_a_changed_runtime_pin(self):
        self.run_train()
        plp.runtime_versions = lambda: {
            "mlx": "0.0.0", "mlx-lm": "0.0.0", "numpy": "0.0.0"}
        with self.assertRaises(plp.EnvironmentBlocker):
            self.run_verify()

    def test_environment_blockers_from_the_shared_seam_exit_three(self):
        real_root = plt.DEFAULT_ALLOWED_ROOT
        plt.DEFAULT_ALLOWED_ROOT = self.root
        try:
            plp.runtime_versions = lambda: {
                "mlx": "0.0.0", "mlx-lm": "0.0.0", "numpy": "0.0.0"}
            self.assertEqual(
                plt.main(["--run", "--config", self.config_path]), 3)
            plp.runtime_versions = lambda: {
                "mlx": "0.32.0", "mlx-lm": "0.31.3", "numpy": "2.4.6"}
            config = json.loads(open(self.config_path,
                                     encoding="utf-8").read())
            config["expected"]["train_sha256"] = "0" * 64
            self.write(self.config_path, json.dumps(config, sort_keys=True))
            self.assertEqual(
                plt.main(["--run", "--config", self.config_path]), 3)
        finally:
            plt.DEFAULT_ALLOWED_ROOT = real_root
            self.build_config()


if __name__ == "__main__":
    unittest.main()
