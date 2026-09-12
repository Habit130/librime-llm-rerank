#!/usr/bin/env python3
"""Real-BGE online memory loop (Habit130/squirrel#168, AC-168-v1).

Not collected by ``scripts/run-model-free-gates.sh`` (integration_* name).
Missing matching local BGE weights is an environment blocker, not a skip.

Run with the allocated embeddings interpreter:

  .local-work/ac168-bge-runtime/venv/bin/python \\
      daemon/integration_bge_online_memory.py

Isolated synthetic facts only. Live evidence is not enabled.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delta import DeltaStateMachine  # noqa: E402
from embeddings import (  # noqa: E402
    QUERY_CACHE_LIMIT,
    BGEM3RepresentationProvider,
    build_bge_m3_provider_from_config,
)
from evidence import (  # noqa: E402
    EvidenceError,
    EvidenceService,
    RepresentationProvider,
    build_evidence_service_from_config,
    compose_config_identity,
    make_evidence_request,
)
from generation import build_generation  # noqa: E402
from oracle import OracleParams  # noqa: E402
from server import handle_evidence_request  # noqa: E402
from staging import _build_desired_provider  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402

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
    return os.path.join(plugin_root(), ".local-work", "ac168-bge-runtime")


def resolve_bge_model():
    env_path = os.environ.get("AC168_BGE_MODEL")
    candidates = []
    if env_path:
        candidates.append(env_path)
    candidates.extend((
        os.path.join(plugin_root(), ".local-work", "models", "BGE-M3"),
        os.path.join(
            os.path.dirname(plugin_root()), "librime-llm-rerank",
            ".local-work", "models", "BGE-M3"),
        "/Users/habit/Developer/librime-llm-rerank/.local-work/models/BGE-M3",
    ))
    seen = set()
    for path in candidates:
        path = os.path.abspath(path)
        if path in seen:
            continue
        seen.add(path)
        config_path = os.path.join(path, "config.json")
        if os.path.isdir(path) and os.path.isfile(config_path):
            return path
    return None


def require_bge_model():
    path = resolve_bge_model()
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


class CountingProvider(RepresentationProvider):
    def __init__(self, inner):
        self._inner = inner
        self.event_calls = []

    def representation_id(self):
        return self._inner.representation_id()

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._inner.query_vector_for_candidate(preceding_text, candidate)

    def event_vector(self, event):
        return self.event_vector_for_candidate(
            event, event.final_selection_text)

    def event_vector_for_candidate(self, event, candidate):
        self.event_calls.append(event.event_id)
        return self._inner.event_vector_for_candidate(event, candidate)

    def vector_dimension(self):
        return self._inner.vector_dimension()


class RealBGEOnlineMemoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_path = require_bge_model()
        os.makedirs(work_root(), exist_ok=True)
        cls._tmpdir = tempfile.mkdtemp(
            prefix="isolated-facts-", dir=work_root())
        cls._old_tmpdir = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = cls._tmpdir
        cls.provider = BGEM3RepresentationProvider(model_path=cls.model_path)
        cls.representation_id = cls.provider.representation_id()
        RESULTS["representation_id"] = cls.representation_id
        RESULTS["model_path"] = cls.model_path

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
        self.machines = []

    def tearDown(self):
        for machine in self.machines:
            try:
                machine.close()
            except Exception:
                pass
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

    def test_exp_runtime_1_identity_agreement_and_fail_closed(self):
        config = self.profile_config()
        evidence = build_evidence_service_from_config(self.facts_root, config)
        desired = _build_desired_provider(config, self.representation_id)
        from delta import _build_provider_from_config
        delta_provider = _build_provider_from_config(
            config, representation_id=self.representation_id)
        self.assertEqual(self.representation_id, desired.representation_id())
        self.assertEqual(
            self.representation_id, delta_provider.representation_id())
        self.assertEqual(
            compose_config_identity(
                self.representation_id, PROFILE_PARAMS, PROFILE_GAMMA),
            evidence.config_identity())
        with open(self.facts.db_path, "rb") as handle:
            before = handle.read()
        with self.assertRaises(EvidenceError) as raised:
            build_bge_m3_provider_from_config(
                config, expected_representation_id="incompatible-identity")
        self.assertEqual("representation_fault", raised.exception.code)
        with open(self.facts.db_path, "rb") as handle:
            after = handle.read()
        self.assertEqual(before, after)

    def test_exp_runtime_2_3_4_5_loop(self):
        self.assertNotIn("mlx", sys.modules)
        self.assertNotIn("mlx.core", sys.modules)
        counter = CountingProvider(self.provider)
        generation = build_generation(
            self.facts_root, counter, self.derived_root)
        generation_id = generation.generation_id
        generation.close()
        self.assertEqual([], counter.event_calls)

        machine = DeltaStateMachine(
            self.facts_root, self.derived_root, counter, generation_id,
            poll_interval=0.01, catch_up_deadline=120.0)
        self.machines.append(machine)
        service = EvidenceService(
            self.facts_root, PROFILE_PARAMS, self.provider, PROFILE_GAMMA,
            machine=machine)
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
        before_catch = len(counter.event_calls)
        machine.ensure_caught_up()
        self.assertEqual(before_catch + 1, len(counter.event_calls))

        result = service.serve({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": SEGMENT,
            "preceding_text": CUR_PRE,
            "candidates": [COMPETITOR, SELECTED],
            "fact_high_water": None,
        })
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

        identity = compose_config_identity(
            self.representation_id, PROFILE_PARAMS, PROFILE_GAMMA)
        state = type("State", (), {"evidence_service": service})()
        mismatched = make_evidence_request(
            "luna_pinyin", "word", SEGMENT, CUR_PRE,
            [COMPETITOR, SELECTED], "wrong-identity", None)
        response = handle_evidence_request(state, json.dumps(mismatched))
        self.assertEqual(
            "config_identity_mismatch", response["error"]["code"])

        machine.close()
        self.machines.remove(machine)
        restart_counter = CountingProvider(self.provider)
        restarted = DeltaStateMachine(
            self.facts_root, self.derived_root, restart_counter,
            generation_id, poll_interval=0.01, catch_up_deadline=120.0)
        self.machines.append(restarted)
        restarted.ensure_caught_up()
        self.assertEqual([], restart_counter.event_calls)
        restarted_service = EvidenceService(
            self.facts_root, PROFILE_PARAMS, self.provider, PROFILE_GAMMA,
            machine=restarted)
        matched = make_evidence_request(
            "luna_pinyin", "word", SEGMENT, CUR_PRE,
            [COMPETITOR, SELECTED], identity, None)
        ok = handle_evidence_request(
            type("State", (), {"evidence_service": restarted_service})(),
            json.dumps(matched))
        self.assertEqual("ok", ok["status"])
        self.assertFalse(ok["zero_evidence"])

        self.assertLessEqual(
            len(self.provider._query_cache), QUERY_CACHE_LIMIT)
        RESULTS["qwen_loaded"] = any(
            name == "mlx" or name.startswith("mlx.") for name in sys.modules)
        self.assertFalse(RESULTS["qwen_loaded"])

    def test_unavailable_model_is_evidence_unavailable(self):
        with self.assertRaises(EvidenceError) as raised:
            build_bge_m3_provider_from_config(
                {"bge_model_path": os.path.join(self._tmpdir, "missing-bge")})
        self.assertEqual("evidence_unavailable", raised.exception.code)


def main():
    require_bge_model()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence_path = os.path.join(work_root(), "ac168-runtime-evidence.json")
    with open(evidence_path, "w", encoding="utf-8") as handle:
        json.dump(RESULTS, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("wrote", evidence_path)
    print("results", json.dumps(RESULTS, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
