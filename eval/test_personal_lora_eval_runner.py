#!/usr/bin/env python3
"""End-to-end runner tests for #178 with a deterministic fake backend.

The fake backend implements the small scoring surface the runner uses, so
``--select-policy``, ``--eval-test`` and ``--measure-latency`` are exercised
on a synthetic dataset and snapshot without loading a real model or touching
the private #175 partition. Real ranking evidence comes from the frozen run
itself, not these tests.

The fixture also pins the evaluation order: ``test.jsonl`` is checksummed but
never parsed before a matching policy lock exists, the lock binds the sealed
test checksum, completed test results are reused instead of a second pass,
and the public report and console carry no private text.
"""

import builtins
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_data as pld  # noqa: E402
import personal_lora_eval as ple  # noqa: E402
import personal_lora_pilot as plp  # noqa: E402

SEALED_SENTINEL = "SENTINELSENTINELSEALEDTEXT"
PRIVATE_SENTINEL = "zqsentinelprivatetextzq"

REQUIRED_MODEL_CONTENTS = {
    "config.json": json.dumps({
        "model_type": "qwen3",
        "architectures": ["Qwen3ForCausalLM"],
        "num_hidden_layers": 4,
        "hidden_size": 8,
        "vocab_size": 32,
        "is_encoder_decoder": False,
    }),
    "generation_config.json": "{}",
    "merges.txt": "",
    "model.safetensors": "fake-weights",
    "tokenizer.json": "{}",
    "tokenizer_config.json": "{}",
    "vocab.json": "{}",
}


class FakeEncoding(object):

    def __init__(self, ids, offsets):
        self.ids = ids
        self.offsets = offsets


class FakeBackendTokenizer(object):

    def encode(self, text):
        ids = [(ord(character) - ord("a")) % 26 + 1 for character in text]
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
        self.prefer_prompt = False
        self.eval_calls = 0

    def eval(self):
        self.eval_calls += 1

    def train(self):
        pass


class FakeMX(object):
    cache_memory = 0
    clear_calls = 0
    peak_memory = 0
    cleared_between_loads = 0

    @staticmethod
    def set_wired_limit(_limit):
        return None

    @staticmethod
    def device_info():
        return {"max_recommended_working_set_size": 1000000000}

    @staticmethod
    def reset_peak_memory():
        FakeMX.peak_memory = 0

    @staticmethod
    def get_peak_memory():
        return FakeMX.peak_memory

    @staticmethod
    def get_active_memory():
        return 0

    @staticmethod
    def get_cache_memory():
        return FakeMX.cache_memory

    @staticmethod
    def clear_cache():
        FakeMX.clear_calls += 1


def fake_score_batch(_backend, model, examples):
    """Deterministic completion score from the fake tokenization.

    The base model prefers ``a``; an adapted model prefers the first prompt
    character (the fixture encodes the target there), so the expected top-1
    counts are derivable by construction.
    """
    values = []
    for example in examples:
        tokens = example.target_count()
        if tokens <= 0:
            values.append((0.0, 0, example.spanning_tokens))
            continue
        last = example.input_ids[-1]
        if model.prefer_prompt and example.prompt_side >= 1:
            preferred = example.input_ids[0]
        else:
            preferred = 1
        value = -1.0 if last == preferred else -5.0
        values.append((value * tokens, tokens, example.spanning_tokens))
    return values


def fake_mlx_load(_model_dir):
    return FakeModel(), FakeTokenizerWrapper()


def fake_load_adapters(model, _adapter_dir):
    model.prefer_prompt = True
    FakeMX.cache_memory = 0


def fake_backend():
    return {
        "mx": FakeMX,
        "mlx_load": fake_mlx_load,
        "load_adapters": fake_load_adapters,
        "score_batch": fake_score_batch,
    }


@contextlib.contextmanager
def command_patches(fixture, **extra):
    """Frozen-identity patches plus a stubbed pinned-runtime probe.

    The model-free release gate installs only NumPy/pypinyin and no
    MLX runtime, so these fake-backend tests stub the runtime probe while
    still exercising the evaluation logic; every real run checks the pinned
    runtime itself.
    """
    patches = fixture.frozen_patches()
    patches.update(extra)
    with mock.patch.multiple(ple, **patches), \
            mock.patch.object(ple.plp, "runtime_versions",
                              lambda: dict(ple.PINNED_VERSIONS)):
        yield


def write_file(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, mode)


def make_row(event_id, prompt, completion, choice_key, ranking_eligible=True):
    return {
        "schema": "personal-lora-completion-v1",
        "prompt": prompt,
        "completion": completion,
        "loss": "completion_only",
        "provenance": {
            "event_id": event_id,
            "ranking_eligible": ranking_eligible,
            "empty_context": prompt == "",
            "choice_key_sha256": choice_key,
            "partition": "synthetic",
        },
    }


def fixture_rows(count, prefix, empty_every=10):
    rows = []
    for index in range(count):
        target = "abc"[index % 3]
        prompt = "" if index % empty_every == 0 else target
        rows.append(make_row("%s%d" % (prefix, index), prompt, target,
                             "key-" + target))
    return rows


class EvalFixture(object):
    """A synthetic but complete ticket-owned fixture."""

    def __init__(self, count=240, empty_every=10, test_text=None,
                 sentinel_candidates=False):
        self.root = tempfile.mkdtemp(prefix="personal_lora_eval_")
        self.artifact_root = os.path.join(self.root, "artifacts")
        self.model_dir = os.path.join(self.root, "model")
        self.dataset_dir = os.path.join(self.root, "dataset")
        self.snapshot_path = os.path.join(self.root, "facts.sqlite3")
        self.adapter_dir = os.path.join(self.root, "selected")
        self.checkpoint_path = os.path.join(self.root, "epoch-2.safetensors")
        for directory in (self.artifact_root, self.model_dir,
                          self.dataset_dir, self.adapter_dir):
            os.makedirs(directory, mode=0o700, exist_ok=True)
        self.train_rows = [make_row("train0", "a", "a", "key-a",
                                    ranking_eligible=False)]
        self.validation_rows = fixture_rows(count, "v", empty_every)
        self.test_rows = fixture_rows(count, "t", empty_every)
        self.test_text = test_text
        self.sentinel_candidates = sentinel_candidates
        self._build()

    def _build(self):
        for name, text in REQUIRED_MODEL_CONTENTS.items():
            write_file(os.path.join(self.model_dir, name), text)
        model_identity = plp.identify_model_dir(self.model_dir)
        adapter_bytes = b"fake-adapter-bytes"
        write_file(os.path.join(self.adapter_dir, "adapter_config.json"),
                   json.dumps({
                       "epoch": 2,
                       "rank": 16,
                       "alpha": 16,
                       "loss": "completion_only",
                       "base_model_composite_sha256":
                           model_identity["composite_sha256"],
                   }))
        with open(os.path.join(self.adapter_dir, "adapters.safetensors"),
                  "wb") as handle:
            handle.write(adapter_bytes)
        os.chmod(os.path.join(self.adapter_dir, "adapters.safetensors"),
                 0o600)
        with open(self.checkpoint_path, "wb") as handle:
            handle.write(adapter_bytes)
        os.chmod(self.checkpoint_path, 0o600)
        self._write_dataset()
        self._write_snapshot()
        self._write_config()

    def _write_dataset(self):
        train_text = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                             for row in self.train_rows)
        validation_text = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                                  for row in self.validation_rows)
        if self.test_text is None:
            test_text = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                                for row in self.test_rows)
        else:
            test_text = self.test_text
        write_file(os.path.join(self.dataset_dir, "train.jsonl"), train_text)
        write_file(os.path.join(self.dataset_dir, "validation.jsonl"),
                   validation_text)
        write_file(os.path.join(self.dataset_dir, "test.jsonl"), test_text)
        manifest = {
            "schema": plp.MANIFEST_SCHEMA,
            "created_at_utc": "2026-09-15T00:00:00Z",
            "audit": {"samples": len(self.train_rows)},
            "splits": {"parts": {
                "train": {"sha256": pld.sha256_text(train_text),
                          "lines": len(self.train_rows)},
                "validation": {"sha256": pld.sha256_text(validation_text),
                               "lines": len(self.validation_rows)},
                "test": {"sha256": pld.sha256_text(test_text),
                         "lines": test_text.count("\n")},
            }},
        }
        write_file(os.path.join(self.dataset_dir, "manifest.json"),
                   json.dumps(manifest, sort_keys=True) + "\n")
        self.digests = {
            "train_sha256": pld.sha256_text(train_text),
            "validation_sha256": pld.sha256_text(validation_text),
            "test_sha256": pld.sha256_text(test_text),
            "manifest_sha256": pld.sha256_file(
                os.path.join(self.dataset_dir, "manifest.json")),
        }

    def _write_snapshot(self):
        connection = sqlite3.connect(self.snapshot_path)
        try:
            connection.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL,
                                   value TEXT NOT NULL);
                CREATE TABLE commits (commit_id TEXT PRIMARY KEY NOT NULL,
                                      utc_committed_at_ms INTEGER NOT NULL);
                CREATE TABLE retractions (retraction_id TEXT PRIMARY KEY
                                          NOT NULL, commit_id TEXT NOT NULL,
                                          hlc_physical_ms INTEGER NOT NULL,
                                          hlc_logical INTEGER NOT NULL,
                                          utc_retracted_at_ms INTEGER NOT
                                          NULL);
                CREATE TABLE selection_events (event_id TEXT PRIMARY KEY NOT
                                               NULL, commit_id TEXT NOT NULL,
                                               event_format_version INTEGER
                                               NOT NULL, schema_id TEXT NOT
                                               NULL, canonical_segment_input
                                               TEXT NOT NULL, span_start
                                               INTEGER NOT NULL, span_end
                                               INTEGER NOT NULL, category
                                               TEXT NOT NULL, preceding_text
                                               TEXT NOT NULL,
                                               competition_complete INTEGER
                                               NOT NULL,
                                               final_selection_text TEXT NOT
                                               NULL, confirmation_source TEXT
                                               NOT NULL, trigger_keycode
                                               INTEGER, display_rank INTEGER
                                               NOT NULL, display_page INTEGER
                                               NOT NULL, session_id TEXT NOT
                                               NULL, session_seq INTEGER NOT
                                               NULL, hlc_physical_ms INTEGER
                                               NOT NULL, hlc_logical INTEGER
                                               NOT NULL, utc_confirmed_at_ms
                                               INTEGER NOT NULL,
                                               utc_committed_at_ms INTEGER
                                               NOT NULL);
                CREATE TABLE selection_candidates (event_id TEXT NOT NULL,
                                                   merge_order INTEGER NOT
                                                   NULL, text TEXT NOT NULL,
                                                   PRIMARY KEY (event_id,
                                                   merge_order));
            """)
            for key, value in (("fact_schema_version", "1"),
                               ("history_id", "synthetic"),
                               ("store_epoch", "synthetic"),
                               ("hlc_physical_ms", "1789348852036"),
                               ("hlc_logical", "0")):
                connection.execute("INSERT INTO meta VALUES (?, ?)",
                                   (key, value))
            connection.execute(
                "INSERT INTO commits VALUES ('commit', 1)")
            for row in self.validation_rows + self.test_rows + \
                    self.train_rows:
                provenance = row["provenance"]
                event_id = provenance["event_id"]
                target = row["completion"]
                prompt = row["prompt"]
                display_rank = 2
                connection.execute(
                    "INSERT INTO selection_events VALUES (?, 'commit', 1,"
                    " 'luna_pinyin', 'seg', 0, 1, 'word', ?, 1, ?,"
                    " 'explicit_current', NULL, ?, 1, 'session', 1, 1, 0,"
                    " 1, 1)",
                    (event_id, prompt, target, display_rank))
                candidates = ["a", "b", "c"]
                if self.sentinel_candidates:
                    candidates = ["a", PRIVATE_SENTINEL, "c"]
                    if target not in candidates:
                        candidates[-1] = target
                for order, text in enumerate(candidates):
                    connection.execute(
                        "INSERT INTO selection_candidates VALUES (?, ?, ?)",
                        (event_id, order, text))
            connection.commit()
        finally:
            connection.close()

    def _write_config(self):
        model_identity = plp.identify_model_dir(self.model_dir)
        adapter_sha = pld.sha256_file(
            os.path.join(self.adapter_dir, "adapters.safetensors"))
        snapshot_sha = pld.sha256_file(self.snapshot_path)
        self.expected = dict(self.digests)
        self.expected.update({
            "model_composite_sha256": model_identity["composite_sha256"],
            "adapter_sha256": adapter_sha,
            "snapshot_sha256": snapshot_sha,
        })
        self.config_path = os.path.join(self.root, "config.json")
        write_file(self.config_path, json.dumps({
            "artifact_root": self.artifact_root,
            "model_dir": self.model_dir,
            "dataset_dir": self.dataset_dir,
            "snapshot_path": self.snapshot_path,
            "adapter_dir": self.adapter_dir,
            "epoch_checkpoint_path": self.checkpoint_path,
            "freeze_commit": "synthetic-freeze",
            "expected": self.expected,
        }, sort_keys=True) + "\n")

    def frozen_patches(self):
        return {
            "FROZEN_MODEL_COMPOSITE":
                self.expected["model_composite_sha256"],
            "FROZEN_ADAPTER_SHA256": self.expected["adapter_sha256"],
            "FROZEN_SNAPSHOT_SHA256": self.expected["snapshot_sha256"],
            "FROZEN_FREEZE_COMMIT": "synthetic-freeze",
            "FROZEN_DATASET_DIGESTS": dict(self.digests),
        }

    def select(self, backend=None, emit=False):
        with command_patches(self):
            if emit:
                return ple.cmd_select_policy(
                    self.config_path, allowed_root=self.artifact_root,
                    backend=backend or fake_backend())
            with contextlib.redirect_stdout(io.StringIO()):
                return ple.cmd_select_policy(
                    self.config_path, allowed_root=self.artifact_root,
                    backend=backend or fake_backend())

    def eval_test(self, backend=None, emit=False):
        with command_patches(self):
            if emit:
                return ple.cmd_eval_test(
                    self.config_path, allowed_root=self.artifact_root,
                    backend=backend or fake_backend())
            with contextlib.redirect_stdout(io.StringIO()):
                return ple.cmd_eval_test(
                    self.config_path, allowed_root=self.artifact_root,
                    backend=backend or fake_backend())

    def eval_test_error(self, error, backend=None):
        with command_patches(self):
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    ple.cmd_eval_test(
                        self.config_path, allowed_root=self.artifact_root,
                        backend=backend or fake_backend())
                except error:
                    return None
        raise AssertionError("expected %s from cmd_eval_test" % error)

    def latency(self, backend=None, emit=False):
        with command_patches(self):
            if emit:
                return ple.cmd_measure_latency(
                    self.config_path, allowed_root=self.artifact_root,
                    backend=backend or fake_backend())
            with contextlib.redirect_stdout(io.StringIO()):
                return ple.cmd_measure_latency(
                    self.config_path, allowed_root=self.artifact_root,
                    backend=backend or fake_backend())

    def read_artifact(self, relative):
        with open(os.path.join(self.artifact_root, relative),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def report_text(self):
        with open(os.path.join(self.artifact_root, "public-report.md"),
                  encoding="utf-8") as handle:
            return handle.read()

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class PolicyLockTest(unittest.TestCase):

    def setUp(self):
        self.fixture = EvalFixture()

    def tearDown(self):
        self.fixture.cleanup()

    def test_select_policy_locks_without_parsing_test(self):
        opened = []
        original_open = builtins.open

        def tracking_open(path, mode="r", *args, **kwargs):
            if os.path.abspath(str(path)).endswith("test.jsonl"):
                opened.append(mode)
            return original_open(path, mode, *args, **kwargs)

        with mock.patch.object(builtins, "open", tracking_open):
            status = self.fixture.select()
        self.assertEqual(status, 0)
        self.assertTrue(opened)
        self.assertTrue(all(mode == "rb" for mode in opened),
                        "test.jsonl was opened in a text mode: %r" % opened)
        lock = self.fixture.read_artifact("policy_lock.json")
        self.assertEqual(lock["schema"], ple.LOCK_SCHEMA)
        self.assertEqual(lock["selected_policy"], "S1")
        self.assertEqual(lock["test_sha256"],
                         self.fixture.expected["test_sha256"])
        self.assertFalse(lock["weight_precondition"]["available"])
        self.assertEqual(lock["available_policies"], ["S1", "S2"])
        self.assertIn("S1", lock["policy_stats"])
        self.assertEqual(lock["policy_stats"]["S3"], "n/a")
        identity = self.fixture.read_artifact("identity.json")
        self.assertEqual(
            identity["adapter"]["sha256"],
            self.fixture.expected["adapter_sha256"])
        self.assertTrue(identity["adapter"]["epoch_checkpoint"][
            "matches_selected"])

    def test_select_policy_reuses_and_verifies_the_lock(self):
        self.fixture.select()
        lock_path = os.path.join(self.fixture.artifact_root,
                                 "policy_lock.json")
        before = pld.sha256_file(lock_path)
        status = self.fixture.select()
        self.assertEqual(status, 0)
        self.assertEqual(pld.sha256_file(lock_path), before)

    def test_select_policy_refuses_a_stale_lock(self):
        self.fixture.select()
        lock_path = os.path.join(self.fixture.artifact_root,
                                 "policy_lock.json")
        with open(lock_path, encoding="utf-8") as handle:
            lock = json.load(handle)
        lock["selected_policy"] = "S2"
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(lock))
        with command_patches(self.fixture):
            with self.assertRaises(ple.LockError):
                ple.cmd_select_policy(self.fixture.config_path,
                                      allowed_root=self.fixture.artifact_root,
                                      backend=fake_backend())

    def test_eval_test_refuses_without_a_lock(self):
        with command_patches(self.fixture):
            with self.assertRaises(ple.LockError):
                ple.cmd_eval_test(self.fixture.config_path,
                                  allowed_root=self.fixture.artifact_root,
                                  backend=fake_backend())
        self.assertFalse(os.path.exists(os.path.join(
            self.fixture.artifact_root, "test")))

    def test_eval_test_refuses_a_lock_bound_to_another_test(self):
        self.fixture.select()
        lock_path = os.path.join(self.fixture.artifact_root,
                                 "policy_lock.json")
        with open(lock_path, encoding="utf-8") as handle:
            lock = json.load(handle)
        lock["test_sha256"] = "0" * 64
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(lock))
        with command_patches(self.fixture):
            with self.assertRaises(ple.LockError):
                ple.cmd_eval_test(self.fixture.config_path,
                                  allowed_root=self.fixture.artifact_root,
                                  backend=fake_backend())


class LockedTestRankingTest(unittest.TestCase):

    def setUp(self):
        self.fixture = EvalFixture()
        self.fixture.select()

    def tearDown(self):
        self.fixture.cleanup()

    def test_locked_test_pass_and_verdict(self):
        status = self.fixture.eval_test()
        self.assertEqual(status, 0)
        results = self.fixture.read_artifact("test/results.json")
        self.assertEqual(results["policy"], "S1")
        self.assertFalse(results["second_pass"])
        self.assertEqual(results["summary"]["ranking_eligible"], 240)
        comparison = results["comparison"]
        self.assertEqual(comparison["rime_reference"]["top1"], 0)
        self.assertEqual(comparison["unadapted_qwen"]["top1"], 72)
        self.assertEqual(comparison["lora_epoch2"]["top1"], 216)
        self.assertEqual(results["denominator_rows"], 216)
        self.assertEqual(results["verdict"], "benefit")
        self.assertAlmostEqual(
            comparison["lora_epoch2"]["target_logloss"], 1.0)
        self.assertEqual(
            results["strata"]["context"]["empty"]["rows"], 0)
        self.assertEqual(
            results["strata"]["exact_pair"]["train_seen"]["rows"], 72)
        self.assertEqual(
            results["strata"]["exact_pair"]["train_unseen"]["rows"], 144)
        self.assertEqual(
            results["strata"]["choice_key"]["train_seen"]["rows"], 72)

    def test_no_benefit_when_the_adapter_ranks_like_the_base(self):
        def no_preference_adapters(model, _adapter_dir):
            model.prefer_prompt = False

        backend = fake_backend()
        backend["load_adapters"] = no_preference_adapters
        self.fixture.eval_test(backend=backend)
        results = self.fixture.read_artifact("test/results.json")
        comparison = results["comparison"]
        self.assertEqual(comparison["lora_epoch2"]["top1"], 72)
        self.assertEqual(comparison["unadapted_qwen"]["top1"], 72)
        self.assertEqual(results["verdict"], "no_benefit")

    def test_completed_results_are_reused_not_rescored(self):
        self.fixture.eval_test()
        results_path = os.path.join(self.fixture.artifact_root,
                                    "test/results.json")
        before = pld.sha256_file(results_path)
        calls = []

        def counting_score_batch(backend, model, examples):
            calls.append(len(examples))
            return fake_score_batch(backend, model, examples)

        backend = fake_backend()
        backend["score_batch"] = counting_score_batch
        status = self.fixture.eval_test(backend=backend)
        self.assertEqual(status, 0)
        self.assertEqual(calls, [])
        self.assertEqual(pld.sha256_file(results_path), before)

    def test_eval_test_refuses_when_identities_change(self):
        self.fixture.eval_test()
        adapter_path = os.path.join(self.fixture.adapter_dir,
                                    "adapters.safetensors")
        with open(adapter_path, "wb") as handle:
            handle.write(b"another-adapter")
        with command_patches(self.fixture,
                             FROZEN_ADAPTER_SHA256=pld.sha256_file(
                                 adapter_path)):
            with self.assertRaises(ple.EvalError):
                ple.cmd_eval_test(self.fixture.config_path,
                                  allowed_root=self.fixture.artifact_root,
                                  backend=fake_backend())

    def test_latency_cold_warm_measurement(self):
        status = self.fixture.latency()
        self.assertEqual(status, 0)
        measurement = self.fixture.read_artifact(
            "latency/measurement.json")
        self.assertEqual(measurement["groups"], 240)
        self.assertEqual(measurement["candidates"], 720)
        self.assertEqual(measurement["cold"]["groups"], 1)
        self.assertEqual(measurement["warm"]["groups"], 239)
        self.assertEqual(measurement["protocol"]["partition"],
                         "validation.jsonl")
        self.assertEqual(measurement["protocol"]["policy"], "S1")
        self.assertIn("ranking", measurement["protocol"]["timed_region"])
        self.assertIn("p50", measurement["warm"]["group_seconds"])
        self.assertIn("p90", measurement["warm"]["per_candidate_seconds"])
        self.assertIn("p99", measurement["all_groups"]["group_seconds"])
        per_group = self.fixture.read_artifact("latency/per-group.json")
        self.assertIn("target_rank", per_group["groups"][0])
        self.assertTrue(os.path.exists(os.path.join(
            self.fixture.artifact_root, "latency/per-group.json")))
        measurement_path = os.path.join(self.fixture.artifact_root,
                                        "latency/measurement.json")
        before = pld.sha256_file(measurement_path)
        self.assertEqual(self.fixture.latency(), 0)
        self.assertEqual(pld.sha256_file(measurement_path), before)

    def test_latency_requires_the_policy_lock(self):
        fixture = EvalFixture()
        try:
            with self.assertRaises(ple.LockError):
                fixture.latency()
        finally:
            fixture.cleanup()

    def test_changed_adapter_config_is_refused_after_the_lock(self):
        config_path = os.path.join(self.fixture.adapter_dir,
                                   "adapter_config.json")
        with open(config_path, encoding="utf-8") as handle:
            adapter_config = json.load(handle)
        adapter_config["rank"] = 8
        adapter_config.setdefault("lora_parameters", {})["rank"] = 8
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(adapter_config, handle)
        os.chmod(config_path, 0o600)
        self.fixture.eval_test_error(ple.EvalError)
        self.assertFalse(os.path.exists(os.path.join(
            self.fixture.artifact_root, "test/results.json")))


class InconclusiveTest(unittest.TestCase):

    def test_omission_dominated_fixture_is_inconclusive(self):
        fixture = EvalFixture(count=240, empty_every=4)
        try:
            fixture.select()
            fixture.eval_test()
            results = fixture.read_artifact("test/results.json")
            self.assertEqual(results["summary"]["ranking_eligible"], 240)
            self.assertEqual(results["denominator_rows"], 180)
            self.assertGreater(results["verdict_evidence"]["omission_rate"],
                               0.20)
            self.assertEqual(results["verdict"], "inconclusive")
        finally:
            fixture.cleanup()


class PrivacyAndReportTest(unittest.TestCase):

    def test_report_and_console_exclude_private_sentinels(self):
        fixture = EvalFixture(sentinel_candidates=True)
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                fixture.select(emit=True)
                fixture.eval_test(emit=True)
                fixture.latency(emit=True)
            report = fixture.report_text()
            self.assertNotIn(PRIVATE_SENTINEL, report)
            self.assertNotIn(PRIVATE_SENTINEL, output.getvalue())
            per_group = fixture.read_artifact("test/per-group.json")
            self.assertNotIn(PRIVATE_SENTINEL,
                             json.dumps(per_group, ensure_ascii=False))
            self.assertNotIn("event_id", json.dumps(per_group))
        finally:
            fixture.cleanup()

    def test_sealed_test_checksum_does_not_need_valid_json(self):
        fixture = EvalFixture(test_text=SEALED_SENTINEL + " not json\n")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fixture.select(), 0)
            lock = fixture.read_artifact("policy_lock.json")
            self.assertEqual(lock["test_sha256"], fixture.expected[
                "test_sha256"])
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
