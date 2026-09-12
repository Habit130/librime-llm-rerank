#!/usr/bin/env python3
"""Model-free BGE online-loop wiring tests (Habit130/squirrel#168, AC-168-v1).

Stdlib-only. Tiny on-disk identity fixtures, never live Rime, never owner
facts, never real BGE weights. Dedicated real-model evidence lives in
``daemon/integration_bge_online_memory.py``.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from embeddings import build_bge_m3_provider_from_config  # noqa: E402
from evidence import (  # noqa: E402
    CandidateFixtureRepresentationProvider,
    EvidenceError,
    EvidenceService,
    build_evidence_service_from_config,
    compose_config_identity,
    make_evidence_request,
)
from oracle import OracleParams  # noqa: E402
from server import handle_evidence_request  # noqa: E402
from staging import StagingBuildMachine, _build_desired_provider  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402

PROFILE_PARAMS = OracleParams(
    tau=0.5, k_evidence=8, half_life=128.0, saturation_k=3.0)
PROFILE_GAMMA = 1.0
HIST_PRE = "周末想去那座"
CUR_PRE = "计划搬去那座"
SELECTED = "城市"
COMPETITOR = "成事"
SEGMENT = "chengshi"


def emit_order(candidates, base_scores, s_values, gamma):
    keyed = [
        (-(base_scores[index] + gamma * s_values[index]), index,
         candidates[index])
        for index in range(len(candidates))
    ]
    keyed.sort()
    return [item[2] for item in keyed]


def tiny_bge_dir():
    root = tempfile.mkdtemp(prefix="ac168-tiny-bge-")
    with open(os.path.join(root, "config.json"), "w", encoding="utf-8") as handle:
        json.dump({"hidden_size": 1024, "model_type": "xlm-roberta"}, handle)
    with open(os.path.join(root, "tokenizer.json"), "w", encoding="utf-8") as handle:
        handle.write("fixture-tokenizer")
    return root


class StagingBgeProviderTest(unittest.TestCase):
    def setUp(self):
        self.root = tiny_bge_dir()
        self.facts = FactsFixture()

    def tearDown(self):
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_desired_provider_accepts_bge_m3(self):
        provider = _build_desired_provider(
            {"provider_kind": "bge_m3", "bge_model_path": self.root},
            None)
        self.assertTrue(provider.representation_id().startswith(
            "dedicated-embedding-repr-v1:route=bge-m3-dense-1024:"))
        self.assertTrue(provider.is_candidate_conditioned())

    def test_desired_identity_mismatch_fails_closed(self):
        with self.assertRaises(EvidenceError) as raised:
            _build_desired_provider(
                {"provider_kind": "bge_m3", "bge_model_path": self.root},
                "not-a-bge-identity")
        self.assertEqual("representation_fault", raised.exception.code)

    def test_missing_model_path_is_unavailable(self):
        with self.assertRaises(EvidenceError) as raised:
            _build_desired_provider({"provider_kind": "bge_m3"}, None)
        self.assertEqual("evidence_unavailable", raised.exception.code)

    def test_missing_directory_is_unavailable(self):
        with self.assertRaises(EvidenceError) as raised:
            build_bge_m3_provider_from_config(
                {"bge_model_path": os.path.join(self.root, "missing")})
        self.assertEqual("evidence_unavailable", raised.exception.code)

    def test_builders_agree_on_representation_identity(self):
        from delta import _build_provider_from_config

        provider = build_bge_m3_provider_from_config(
            {"bge_model_path": self.root})
        representation_id = provider.representation_id()
        config = {
            "provider_kind": "bge_m3",
            "bge_model_path": self.root,
            "representation_id": representation_id,
            "desired_representation_id": representation_id,
            "tau": 0.5,
            "k_evidence": 8,
            "half_life": 128.0,
            "saturation_k": 3.0,
            "gamma": 1.0,
        }
        evidence = build_evidence_service_from_config(
            self.facts_root_dir(), config)
        desired = _build_desired_provider(config, representation_id)
        delta_provider = _build_provider_from_config(
            config, representation_id=representation_id)
        self.assertEqual(representation_id, desired.representation_id())
        self.assertEqual(representation_id, delta_provider.representation_id())
        self.assertEqual(
            compose_config_identity(
                representation_id, PROFILE_PARAMS, PROFILE_GAMMA),
            evidence.config_identity())

    def facts_root_dir(self):
        return os.path.dirname(self.facts.db_path)

    def test_mismatch_does_not_mutate_facts(self):
        with open(self.facts.db_path, "rb") as handle:
            before = handle.read()
        with self.assertRaises(EvidenceError):
            build_bge_m3_provider_from_config(
                {"bge_model_path": self.root},
                expected_representation_id="wrong-id")
        with open(self.facts.db_path, "rb") as handle:
            after = handle.read()
        self.assertEqual(before, after)

    def test_staging_machine_accepts_bge_provider(self):
        provider = build_bge_m3_provider_from_config(
            {"bge_model_path": self.root})
        representation_id = provider.representation_id()
        derived = os.path.join(self.facts_root_dir(), "derived")
        machine = StagingBuildMachine(
            self.facts_root_dir(), derived, provider, representation_id,
            "shadow-gen-v1:" + "0" * 32, start_worker=False)
        self.addCleanup(machine.close)
        self.assertEqual(representation_id, machine._provider.representation_id())
        self.assertEqual(1024, machine._provider.vector_dimension())


class FaultClassTest(unittest.TestCase):
    def setUp(self):
        self.facts = FactsFixture()
        self.facts_root = os.path.dirname(self.facts.db_path)

    def tearDown(self):
        self.facts.close()

    def test_empty_store_is_successful_zero_evidence(self):
        query = (1.0, 0.0, 0.0, 0.0)
        provider = CandidateFixtureRepresentationProvider(
            "ac168-zero-repr",
            {(CUR_PRE, SELECTED): query, (CUR_PRE, COMPETITOR): query},
            {},
        )
        service = EvidenceService(
            self.facts_root, PROFILE_PARAMS, provider, PROFILE_GAMMA)
        result = service.serve({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": SEGMENT,
            "preceding_text": CUR_PRE,
            "candidates": [COMPETITOR, SELECTED],
            "fact_high_water": None,
        })
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["zero_evidence"])
        self.assertEqual([0.0, 0.0], [row["s"] for row in result["evidence"]])

    def test_config_identity_mismatch_is_protocol_fault(self):
        provider = CandidateFixtureRepresentationProvider(
            "ac168-mismatch-repr", {}, {})
        service = EvidenceService(
            self.facts_root, PROFILE_PARAMS, provider, PROFILE_GAMMA)
        state = type("State", (), {"evidence_service": service})()
        request = make_evidence_request(
            "luna_pinyin", "word", SEGMENT, CUR_PRE,
            [COMPETITOR, SELECTED], "wrong-config-identity", None)
        response = handle_evidence_request(state, json.dumps(request))
        self.assertEqual(
            "config_identity_mismatch", response["error"]["code"])

    def test_unavailable_model_is_not_zero_evidence(self):
        with self.assertRaises(EvidenceError) as raised:
            build_evidence_service_from_config(
                self.facts_root,
                {
                    "provider_kind": "bge_m3",
                    "gamma": 1.0,
                    "tau": 0.5,
                    "k_evidence": 8,
                    "half_life": 128.0,
                    "saturation_k": 3.0,
                })
        self.assertEqual("evidence_unavailable", raised.exception.code)


class RankingFormulaTest(unittest.TestCase):
    def setUp(self):
        self.facts = FactsFixture()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.facts.add_event(
            "e1", schema_id="luna_pinyin", segment_input=SEGMENT,
            category="word", selection=SELECTED, preceding_text=HIST_PRE,
            competition=(COMPETITOR, SELECTED))

    def tearDown(self):
        self.facts.close()

    def test_alpha_zero_positive_evidence_changes_group_order(self):
        query = (1.0, 0.0, 0.0, 0.0)
        hit = (1.0, 0.0, 0.0, 0.0)
        provider = CandidateFixtureRepresentationProvider(
            "ac168-rank-repr",
            {(CUR_PRE, SELECTED): query,
             (CUR_PRE, COMPETITOR): (0.0, 1.0, 0.0, 0.0)},
            {("luna_pinyin", SEGMENT, SELECTED): hit},
            default_event=(0.0, 1.0, 0.0, 0.0),
        )
        service = EvidenceService(
            self.facts_root, PROFILE_PARAMS, provider, PROFILE_GAMMA)
        result = service.serve({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": SEGMENT,
            "preceding_text": CUR_PRE,
            "candidates": [COMPETITOR, SELECTED],
            "fact_high_water": None,
        })
        self.assertFalse(result["zero_evidence"])
        s_values = [row["s"] for row in result["evidence"]]
        self.assertEqual(0.0, s_values[0])
        self.assertAlmostEqual(0.25, s_values[1])
        self.assertNotEqual(HIST_PRE, CUR_PRE)
        bases = [0.20, 0.10]
        self.assertEqual(
            [SELECTED, COMPETITOR],
            emit_order([COMPETITOR, SELECTED], bases, s_values, PROFILE_GAMMA))


class UnchangedCppEvidenceTest(unittest.TestCase):
    def test_filter_emission_and_passthrough_tests_remain(self):
        root = os.path.join(os.path.dirname(__file__), "..", "test")
        with open(os.path.join(root, "llm_rerank_filter_test.cc"),
                  encoding="utf-8") as handle:
            filter_src = handle.read()
        with open(os.path.join(root, "llm_scorer_protocol_test.cc"),
                  encoding="utf-8") as handle:
            protocol_src = handle.read()
        self.assertIn("HitChangesWithinGroupOrder", protocol_src)
        self.assertIn("ZeroEvidenceKeepsBaseOrder", protocol_src)
        self.assertIn("TimeoutPassesThroughWholeWindow", protocol_src)
        self.assertIn("ConfigIdentityMismatchPassesThroughWholeWindow",
                      protocol_src)
        self.assertIn("HitPromotesCandidateWithinGroup", filter_src)
        self.assertIn("EvidenceFailurePassesThroughWholeWindow", filter_src)
        self.assertIn("ExhaustedWindowDeadlineSkipsLaterGroup", filter_src)
        self.assertIn("EvidenceOnlyChangesWithinGroup", filter_src)


if __name__ == "__main__":
    unittest.main()
