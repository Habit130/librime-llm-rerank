#!/usr/bin/env python3
"""Real-BGE isolated activation (Habit130/squirrel#170, AC-170-v1).

Not collected by ``scripts/run-model-free-gates.sh`` (integration_* name).
Missing matching local BGE weights is an environment blocker, not a skip.

Isolated disposable rime_dir and facts only. Live evidence is not enabled.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from embeddings import (  # noqa: E402
    QUERY_CACHE_LIMIT,
    BGEM3RepresentationProvider,
    build_bge_m3_provider_from_config,
    model_identity_digest,
    tokenizer_identity_digest,
)
from evidence import (  # noqa: E402
    EvidenceError,
    EvidenceService,
    build_evidence_service_from_config,
    compose_config_identity,
    make_evidence_request,
)
from generation import BuildTargetExistsError, build_generation  # noqa: E402
from oracle import OracleParams  # noqa: E402
from server import handle_evidence_request  # noqa: E402
from status_core import collect_status  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402
from tracing import (  # noqa: E402
    APPLY_STATE_APPLIED,
    APPLY_STATE_FALLBACK,
    APPLY_STATE_UNKNOWN,
    CLIENT_APPLY_FILENAME,
    TraceStore,
)

FROZEN_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
HIST_PRE = "周末想去那座"
CUR_PRE = "计划搬去那座"
SELECTED = "城市"
COMPETITOR = "成事"
SEGMENT = "chengshi"
PROFILE_PARAMS = OracleParams(
    tau=0.5, k_evidence=8, half_life=128.0, saturation_k=3.0)
PROFILE_GAMMA = 1.0
RESULTS = {}


def plugin_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def work_root():
    return os.path.join(plugin_root(), ".local-work", "ac170-activate")


def resolve_bge_model():
    env_path = os.environ.get("AC170_BGE_MODEL") or os.environ.get(
        "AC168_BGE_MODEL")
    candidates = []
    if env_path:
        candidates.append(env_path)
    candidates.extend((
        os.path.join(plugin_root(), ".local-work", "models", "BGE-M3"),
        "/Users/habit/Developer/librime-llm-rerank/.local-work/models/BGE-M3",
    ))
    seen = set()
    for path in candidates:
        path = os.path.abspath(path)
        if path in seen:
            continue
        seen.add(path)
        config_path = os.path.join(path, "config.json")
        metadata = os.path.join(
            path, ".cache", "huggingface", "download", "config.json.metadata")
        if os.path.isdir(path) and os.path.isfile(config_path):
            return path, metadata
    return None, None


def require_bge_model():
    path, metadata = resolve_bge_model()
    if path is None:
        raise SystemExit(
            "environment blocker: missing local BGE weights matching "
            "revision %s" % FROZEN_REVISION)
    with open(os.path.join(path, "config.json"), encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("model_type") != "xlm-roberta" \
            or config.get("hidden_size") != 1024:
        raise SystemExit(
            "environment blocker: BGE weights do not match frozen "
            "xlm-roberta hidden_size=1024 architecture")
    if metadata and os.path.isfile(metadata):
        with open(metadata, encoding="utf-8") as handle:
            revision = handle.readline().strip()
        if revision != FROZEN_REVISION:
            raise SystemExit(
                "environment blocker: BGE metadata revision %s != %s"
                % (revision, FROZEN_REVISION))
        RESULTS["upstream_revision"] = revision
    return path


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right))


def emit_order(candidates, base_scores, s_values, gamma):
    keyed = [
        (-(base_scores[index] + gamma * s_values[index]), index,
         candidates[index])
        for index in range(len(candidates))
    ]
    keyed.sort()
    return [item[2] for item in keyed]


def meta_map(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()


class RealBGEActivationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_path = require_bge_model()
        os.makedirs(work_root(), exist_ok=True)
        cls._tmpdir = tempfile.mkdtemp(
            prefix="isolated-rime-", dir=work_root())
        cls._old_tmpdir = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = cls._tmpdir
        cls.provider = BGEM3RepresentationProvider(model_path=cls.model_path)
        cls.representation_id = cls.provider.representation_id()
        cls.config_identity = compose_config_identity(
            cls.representation_id, PROFILE_PARAMS, PROFILE_GAMMA)
        RESULTS["representation_id"] = cls.representation_id
        RESULTS["config_identity"] = cls.config_identity
        RESULTS["model_path"] = cls.model_path
        RESULTS["model_digest"] = model_identity_digest(cls.model_path)
        RESULTS["tokenizer_digest"] = tokenizer_identity_digest(cls.model_path)
        RESULTS["baseline_policy_id"] = "mean-token-lm-v1"
        RESULTS["qwen_loaded"] = False

    @classmethod
    def tearDownClass(cls):
        if cls._old_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = cls._old_tmpdir

    def setUp(self):
        self.facts = FactsFixture()
        self.facts.conn.execute("PRAGMA journal_mode=WAL;")
        self.facts.conn.execute(
            "UPDATE meta SET value = value WHERE key = 'store_epoch';")
        self.facts.conn.commit()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")
        os.chmod(self.facts_root, 0o700)

    def tearDown(self):
        self.facts.close()

    def profile_config(self):
        return {
            "provider_kind": "bge_m3",
            "bge_model_path": self.model_path,
            "representation_id": self.representation_id,
            "desired_representation_id": self.representation_id,
            "tau": 0.5,
            "k_evidence": 8,
            "half_life": 128.0,
            "saturation_k": 3.0,
            "gamma": 1.0,
            "retrieval_backend": "exact",
        }

    def write_rime_dir(self, evidence_enabled):
        rime_dir = os.path.join(self.facts_root, "rime")
        build = os.path.join(rime_dir, "build")
        os.makedirs(build, exist_ok=True)
        with open(os.path.join(rime_dir, "default.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write("schema_list:\n  - schema: luna_pinyin\n")
        payload = {
            "schema": {"schema_id": "luna_pinyin"},
            "llm_rerank": {
                "reranking_enabled": True,
                "recording_enabled": True,
                "evidence_enabled": evidence_enabled,
                "alpha": 0.0,
                "gamma": 1.0,
                "tau": 0.5,
                "k_evidence": 8,
                "half_life": 128.0,
                "saturate_k": 3.0,
                "window": 32,
                "deadline_ms": 200,
                "baseline_policy_id": "mean-token-lm-v1",
                "representation_id": self.representation_id,
            },
        }
        with open(os.path.join(build, "luna_pinyin.schema.yaml"), "w",
                  encoding="utf-8") as handle:
            json.dump(payload, handle)
        return rime_dir

    def test_exp_activate_identities_and_loop(self):
        self.assertNotIn("mlx", sys.modules)
        self.assertTrue(self.representation_id.startswith(
            "dedicated-embedding-repr-v1:route=bge-m3-dense-1024:"))
        self.assertIn("adapter=bge-m3", self.representation_id)
        self.assertIn("instruction=none", self.representation_id)
        self.assertIn("pool=dense-mean", self.representation_id)
        self.assertIn("deps=torch@2.7.1,transformers@4.52.4,"
                      "tokenizers@0.21.1,safetensors@0.5.3",
                      self.representation_id)
        evidence = build_evidence_service_from_config(
            self.facts_root, self.profile_config())
        self.assertEqual(self.config_identity, evidence.config_identity())

        status_facts = os.path.join(self.facts_root, "status-facts")
        os.makedirs(status_facts)
        os.chmod(status_facts, 0o700)
        rime_dir = self.write_rime_dir(True)
        report = collect_status(
            rime_dir, status_facts, os.path.join(self.facts_root, "no.sock"))
        self.assertTrue(report["snapshot_ok"])
        duties = report["schemas"][0]["config"]["runtime_effective"]
        self.assertEqual("on", duties["evidence"]["state"])
        self.assertEqual("on", duties["recording"]["state"])
        RESULTS["disposable_rime_dir"] = rime_dir

        before = meta_map(self.facts.db_path)
        generation = build_generation(
            self.facts_root, self.provider, self.derived_root)
        generation_id = generation.generation_id
        generation.close()
        after_build = meta_map(self.facts.db_path)
        self.assertEqual(before["store_epoch"], after_build["store_epoch"])
        self.assertEqual(before["history_id"], after_build["history_id"])
        RESULTS["generation_id"] = generation_id

        service = EvidenceService(
            self.facts_root, PROFILE_PARAMS, self.provider, PROFILE_GAMMA)
        empty = service.serve({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": SEGMENT,
            "preceding_text": CUR_PRE,
            "candidates": [COMPETITOR, SELECTED],
            "fact_high_water": None,
        })
        self.assertEqual("ok", empty["status"])
        self.assertTrue(empty["zero_evidence"])

        hist = self.provider.query_vector_for_candidate(HIST_PRE, SELECTED)
        cur = self.provider.query_vector_for_candidate(CUR_PRE, SELECTED)
        pair_cosine = cosine(hist, cur)
        RESULTS["demo_cosine"] = pair_cosine
        if pair_cosine <= 0.5:
            raise SystemExit(
                "specification blocker: demo pair cosine %s <= tau 0.5; "
                "do not retune" % pair_cosine)
        self.assertGreater(pair_cosine, 0.5)
        self.assertNotEqual(HIST_PRE, CUR_PRE)

        self.facts.add_event(
            "commit-1", schema_id="luna_pinyin", segment_input=SEGMENT,
            category="word", selection=SELECTED, preceding_text=HIST_PRE,
            competition=(COMPETITOR, SELECTED))
        after_event = meta_map(self.facts.db_path)
        self.assertEqual(before["history_id"], after_event["history_id"])
        self.assertEqual(before["store_epoch"], after_event["store_epoch"])

        samples = []
        result = None
        for _ in range(8):
            started = time.perf_counter()
            result = service.serve({
                "schema_id": "luna_pinyin",
                "category": "word",
                "canonical_segment_input": SEGMENT,
                "preceding_text": CUR_PRE,
                "candidates": [COMPETITOR, SELECTED],
                "fact_high_water": None,
            })
            samples.append((time.perf_counter() - started) * 1000.0)
        self.assertEqual("ok", result["status"])
        self.assertFalse(result["zero_evidence"])
        s_values = [row["s"] for row in result["evidence"]]
        RESULTS["demo_s"] = s_values
        self.assertEqual(0.0, s_values[0])
        self.assertGreater(s_values[1], 0.0)
        gap = min(0.12, s_values[1] / 2.0)
        bases = [0.10 + gap, 0.10]
        self.assertEqual(
            [COMPETITOR, SELECTED],
            emit_order([COMPETITOR, SELECTED], bases, [0.0, 0.0],
                       PROFILE_GAMMA))
        self.assertEqual(
            [SELECTED, COMPETITOR],
            emit_order([COMPETITOR, SELECTED], bases, s_values,
                       PROFILE_GAMMA))
        samples.sort()
        RESULTS["latency_ms_samples"] = samples
        RESULTS["latency_p95_ms"] = samples[int(0.95 * (len(samples) - 1))]
        RESULTS["latency_p99_ms"] = samples[-1]
        RESULTS["deadline_ms"] = 200
        RESULTS["window"] = 32

        mismatched = make_evidence_request(
            "luna_pinyin", "word", SEGMENT, CUR_PRE,
            [COMPETITOR, SELECTED], "wrong-identity", None)
        response = handle_evidence_request(
            type("State", (), {"evidence_service": service})(),
            json.dumps(mismatched))
        self.assertEqual(
            "config_identity_mismatch", response["error"]["code"])

        store = TraceStore(self.facts_root)
        store.record_request({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": SEGMENT,
            "request_id": "llm-evidence-v1:1:0",
            "plan_identity": "plan-v2:test",
            "config_identity": self.config_identity,
            "fact_high_water": {"store_epoch": after_event["store_epoch"],
                                "hlc_physical_ms": 1000000,
                                "hlc_logical": 0},
            "complete_comparable": True,
            "candidate_count": 2,
        }, "ok")
        self.assertEqual(APPLY_STATE_UNKNOWN,
                         store.apply_state_for("llm-evidence-v1:1:0"))
        traces = os.path.join(self.facts_root, "traces")
        os.makedirs(traces, exist_ok=True)
        with open(os.path.join(traces, CLIENT_APPLY_FILENAME), "a",
                  encoding="utf-8") as handle:
            handle.write(json.dumps({
                "apply_state": APPLY_STATE_APPLIED,
                "request_ids": ["llm-evidence-v1:1:0"],
                "plan_identity": "plan-v2:test",
                "config_identity": self.config_identity,
            }, ensure_ascii=False) + "\n")
        self.assertEqual(APPLY_STATE_APPLIED,
                         store.apply_state_for("llm-evidence-v1:1:0"))
        store.record_request({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": SEGMENT,
            "request_id": "llm-evidence-v1:1:1",
            "plan_identity": "plan-v2:test",
            "config_identity": self.config_identity,
            "complete_comparable": True,
            "candidate_count": 2,
        }, "ok")
        store.record_apply_ack(["llm-evidence-v1:1:1"], APPLY_STATE_FALLBACK)
        self.assertEqual(APPLY_STATE_FALLBACK,
                         store.apply_state_for("llm-evidence-v1:1:1"))

        with open(self.facts.db_path, "rb") as handle:
            facts_bytes = handle.read()
        try:
            build_generation(
                self.facts_root, self.provider, self.derived_root)
        except BuildTargetExistsError:
            pass
        with open(self.facts.db_path, "rb") as handle:
            self.assertEqual(facts_bytes, handle.read())
        rebuilt = meta_map(self.facts.db_path)
        self.assertEqual(after_event["store_epoch"], rebuilt["store_epoch"])
        self.assertEqual(after_event["history_id"], rebuilt["history_id"])

        self.write_rime_dir(False)
        stopped = collect_status(
            rime_dir, status_facts, os.path.join(self.facts_root, "no.sock"))
        stopped_duties = stopped["schemas"][0]["config"]["runtime_effective"]
        self.assertEqual("off", stopped_duties["evidence"]["state"])
        self.assertEqual("on", stopped_duties["recording"]["state"])
        with open(self.facts.db_path, "rb") as handle:
            self.assertEqual(facts_bytes, handle.read())

        self.assertLessEqual(len(self.provider._query_cache), QUERY_CACHE_LIMIT)
        RESULTS["qwen_loaded"] = any(
            name == "mlx" or name.startswith("mlx.") for name in sys.modules)
        self.assertFalse(RESULTS["qwen_loaded"])

    def test_unavailable_model_is_not_zero_evidence(self):
        with self.assertRaises(EvidenceError) as raised:
            build_bge_m3_provider_from_config(
                {"bge_model_path": os.path.join(self._tmpdir, "missing-bge")})
        self.assertEqual("evidence_unavailable", raised.exception.code)


def main():
    require_bge_model()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence_path = os.path.join(work_root(), "activation-identities.json")
    os.makedirs(work_root(), exist_ok=True)
    with open(evidence_path, "w", encoding="utf-8") as handle:
        json.dump(RESULTS, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("wrote", evidence_path)
    print("results", json.dumps(RESULTS, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
