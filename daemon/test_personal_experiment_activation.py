#!/usr/bin/env python3
"""Model-free personal experiment activation tests (Habit130/squirrel#170).

Stdlib-only. Disposable rime_dir and synthetic facts. Never live Rime, never
owner facts, never real BGE weights. Real-model evidence lives in
``daemon/integration_personal_experiment_activation.py``.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from embeddings import build_bge_m3_provider_from_config  # noqa: E402
from evidence import (  # noqa: E402
    EvidenceError,
    compose_config_identity,
)
from oracle import OracleParams  # noqa: E402
from status_core import collect_status  # noqa: E402
from test_bge_online_memory import tiny_bge_dir  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402
from tracing import (  # noqa: E402
    APPLY_STATE_APPLIED,
    APPLY_STATE_FALLBACK,
    APPLY_STATE_UNKNOWN,
    CLIENT_APPLY_FILENAME,
    TraceStore,
)

PROFILE_PARAMS = OracleParams(
    tau=0.5, k_evidence=8, half_life=128.0, saturation_k=3.0)
PROFILE_GAMMA = 1.0
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNBOOK = os.path.join(PLUGIN_ROOT, "docs", "personal-experiment-activation.md")
FROZEN_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
BASELINE_POLICY = "mean-token-lm-v1"


def request_meta(request_id):
    return {
        "schema_id": "luna_pinyin",
        "category": "word",
        "canonical_segment_input": "chengshi",
        "request_id": request_id,
        "plan_identity": "plan-v2:test",
        "config_identity": "evidence-v1:repr=ac170-fixture:tau=0.5:"
                           "kev=8:H=128:sat=3:gamma=1",
        "fact_high_water": {"store_epoch": "e1", "hlc_physical_ms": 1000000,
                            "hlc_logical": 0},
        "complete_comparable": True,
        "candidate_count": 2,
    }


class ProfileIdentityTest(unittest.TestCase):
    def test_frozen_numeric_identity(self):
        identity = compose_config_identity(
            "ac170-fixture-repr", PROFILE_PARAMS, PROFILE_GAMMA)
        self.assertEqual(
            "evidence-v1:repr=ac170-fixture-repr:tau=0.5:kev=8:H=128:"
            "sat=3:gamma=1",
            identity)

    def test_empty_representation_id_fails_closed(self):
        with self.assertRaises(EvidenceError) as raised:
            compose_config_identity("", PROFILE_PARAMS, PROFILE_GAMMA)
        self.assertEqual("config_identity", raised.exception.code)

    def test_yaml_only_identity_mismatch_does_not_mutate_facts(self):
        root = tiny_bge_dir()
        facts = FactsFixture()
        try:
            with open(facts.db_path, "rb") as handle:
                before = handle.read()
            with self.assertRaises(EvidenceError) as raised:
                build_bge_m3_provider_from_config(
                    {"bge_model_path": root},
                    expected_representation_id="yaml-only-without-check")
            self.assertEqual("representation_fault", raised.exception.code)
            with open(facts.db_path, "rb") as handle:
                after = handle.read()
            self.assertEqual(before, after)
            conn = sqlite3.connect(facts.db_path)
            meta = dict(conn.execute("SELECT key, value FROM meta"))
            conn.close()
            self.assertEqual("e1", meta["store_epoch"])
            self.assertEqual("h1", meta["history_id"])
        finally:
            facts.close()
            shutil.rmtree(root, ignore_errors=True)


class DisposableRimeDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="ac170-rime-")
        self.rime_dir = os.path.join(self._tmp, "rime")
        self.facts_root = os.path.join(self._tmp, "facts")
        os.makedirs(os.path.join(self.rime_dir, "build"))
        os.makedirs(self.facts_root)
        os.chmod(self.facts_root, 0o700)
        self.sock = os.path.join(self._tmp, "missing.sock")
        with open(os.path.join(self.rime_dir, "default.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write("schema_list:\n  - schema: luna_pinyin\n")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_schema(self, evidence_enabled, representation_id=None):
        section = {
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
            "baseline_policy_id": BASELINE_POLICY,
        }
        if representation_id is not None:
            section["representation_id"] = representation_id
        payload = {
            "schema": {"schema_id": "luna_pinyin"},
            "llm_rerank": section,
        }
        with open(os.path.join(self.rime_dir, "build",
                               "luna_pinyin.schema.yaml"), "w",
                  encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_evidence_on_in_disposable_dir_keeps_recording(self):
        self.write_schema(True, "ac170-fixture-repr")
        report = collect_status(self.rime_dir, self.facts_root, self.sock)
        self.assertTrue(report["snapshot_ok"])
        entry = report["schemas"][0]
        duties = entry["config"]["runtime_effective"]
        self.assertEqual("on", duties["evidence"]["state"])
        self.assertEqual("on", duties["recording"]["state"])
        self.assertEqual(0.0, entry["config"]["alpha"])
        self.assertEqual(1.0, entry["config"]["gamma"])
        self.assertEqual(BASELINE_POLICY, entry["config"]["baseline_policy_id"])

    def test_stop_evidence_keeps_recording_and_facts(self):
        self.write_schema(True, "ac170-fixture-repr")
        marker = os.path.join(self.facts_root, "owner-facts-marker")
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("keep")
        with open(marker, "rb") as handle:
            before = handle.read()
        self.write_schema(False, "ac170-fixture-repr")
        report = collect_status(self.rime_dir, self.facts_root, self.sock)
        duties = report["schemas"][0]["config"]["runtime_effective"]
        self.assertEqual("off", duties["evidence"]["state"])
        self.assertEqual("on", duties["recording"]["state"])
        with open(marker, "rb") as handle:
            self.assertEqual(before, handle.read())


class ApplyUnknownTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="ac170-apply-")
        self.store = TraceStore(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_computed_without_ack_is_unknown(self):
        self.store.record_request(request_meta("req-computed"), "ok")
        self.assertEqual(APPLY_STATE_UNKNOWN,
                         self.store.apply_state_for("req-computed"))
        self.assertNotEqual(APPLY_STATE_APPLIED,
                            self.store.apply_state_for("req-computed"))

    def test_client_jsonl_ack_is_applied_not_computed(self):
        self.store.record_request(request_meta("req-applied"), "ok")
        traces = os.path.join(self._tmp, "traces")
        os.makedirs(traces, exist_ok=True)
        with open(os.path.join(traces, CLIENT_APPLY_FILENAME), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps({
                "apply_state": APPLY_STATE_APPLIED,
                "request_ids": ["req-applied"],
                "plan_identity": "plan-v2:test",
                "config_identity": request_meta("req-applied")["config_identity"],
            }, ensure_ascii=False) + "\n")
        self.assertEqual(APPLY_STATE_APPLIED,
                         self.store.apply_state_for("req-applied"))

    def test_fallback_ack_is_not_applied(self):
        self.store.record_request(request_meta("req-fb"), "ok")
        self.store.record_apply_ack(["req-fb"], APPLY_STATE_FALLBACK)
        self.assertEqual(APPLY_STATE_FALLBACK,
                         self.store.apply_state_for("req-fb"))


class RunbookTest(unittest.TestCase):
    def test_runbook_has_owner_enable_stop_and_non_claims(self):
        with open(RUNBOOK, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("evidence_enabled: true", text)
        self.assertIn("evidence_enabled: false", text)
        self.assertIn("<ACTIVATED_REPRESENTATION_ID>", text)
        self.assertIn("<ACTIVATED_CONFIG_IDENTITY>", text)
        self.assertIn("annotate mispromotion", text)
        self.assertIn("unique_lock", text)
        self.assertIn(FROZEN_REVISION, text)
        self.assertIn("Do not enable live evidence in this ticket", text)


class UnchangedCppActivationTest(unittest.TestCase):
    def test_filter_apply_and_timeout_tests_remain(self):
        root = os.path.join(PLUGIN_ROOT, "test")
        with open(os.path.join(root, "llm_rerank_filter_test.cc"),
                  encoding="utf-8") as handle:
            src = handle.read()
        self.assertIn("EmptyFactsRootFallsBackToDefaultRootDir", src)
        self.assertIn("MissingEvidenceScorerIsFallbackNotStranded", src)
        self.assertIn("TimeoutIsFallbackNotApplied", src)
        self.assertIn("ObservationWriteFailureDoesNotChangeEmission", src)


if __name__ == "__main__":
    unittest.main()
