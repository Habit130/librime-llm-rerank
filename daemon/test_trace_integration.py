#!/usr/bin/env python3
"""Evidence-service + trace-store integration (Habit130/squirrel#74, AC-74-v1).

End-to-end within the daemon: an EvidenceService with a configured
TraceStore records order-change traces, fault traces and aggregates-only for
unchanged successes, all identity-only, with the wire response unchanged
(no ``_oracle_result`` / ``_trace`` keys escape).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from evidence import (  # noqa: E402
    EvidenceService,
    FixtureRepresentationProvider,
    compose_config_identity,
    make_evidence_request,
)
from oracle import OracleParams  # noqa: E402
from server import handle_evidence_request  # noqa: E402
from tracing import TraceStore  # noqa: E402
from test_evidence import (  # noqa: E402
    GAMMA,
    PARAMS,
    REPR_ID,
    encode,
    make_provider,
)
from test_oracle import FactsFixture  # noqa: E402


def trial(complete_comparable=True, base_scores=None):
    # Wire key "actionable" is historical (#152); old fixtures keep parsing.
    return {
        "actionable": complete_comparable,
        "base_scores": base_scores if base_scores is not None
        else [1.0, 2.0],
    }


class TraceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_trace_int_")
        self.facts_root = os.path.join(self._tmp, "facts")
        os.makedirs(self.facts_root)
        self.fixture = FactsFixture()
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        shutil.copy(self.fixture.db_path,
                    os.path.join(self.facts_root, "facts.sqlite3"))
        self.trace_root = os.path.join(self._tmp, "sm")
        self.store = TraceStore(self.trace_root)
        self.service = EvidenceService(
            self.facts_root, PARAMS, make_provider("时界"), GAMMA,
            trace_store=self.store)
        self.state = type("State", (), {"evidence_service": self.service,
                                        "trace_store": self.store})()

    def tearDown(self):
        self.fixture.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def call(self, **overrides):
        request = make_evidence_request(
            schema_id="luna_pinyin",
            category="word",
            canonical_segment_input="shijie",
            preceding_text="我",
            candidates=["世界", "时界"],
            config_identity=compose_config_identity(REPR_ID, PARAMS, GAMMA),
            fact_high_water={"store_epoch": "e1", "hlc_physical_ms": 1000000,
                             "hlc_logical": 0},
            request_id=overrides.pop("request_id", "evidence-int-1"),
        )
        request.update(overrides)
        return handle_evidence_request(self.state, encode(request))

    def trace_files(self):
        directory = self.store.directory()
        if not os.path.isdir(directory):
            return []
        return sorted(os.listdir(directory))

    def test_unchanged_success_aggregates_only(self):
        # base_scores [1.0, 2.0]: 时界 (index 1) already leads on base and
        # keeps leading with evidence -> no order change.
        response = self.call(trial=trial(base_scores=[1.0, 2.0]))
        self.assertEqual("ok", response["status"])
        # No trace body; aggregates recorded; response is wire-clean.
        self.assertEqual([], [f for f in self.trace_files()
                              if f.startswith("trace-")])
        self.assertEqual(1, self.store.aggregates()["semantic_requests"])
        self.assertNotIn("_oracle_result", response)
        self.assertNotIn("_trace", response)

    def test_order_change_writes_full_trace(self):
        # base_scores [1.0, 0.1]: 世界 (index 0) leads on base, but the
        # evidence hit promotes 时界 (index 1) -> final order flips.
        response = self.call(request_id="evidence-int-2",
                             trial=trial(base_scores=[1.0, 0.1]))
        self.assertEqual("ok", response["status"])
        traces = [f for f in self.trace_files()
                  if f.startswith("trace-tr-evidence-int-2-")]
        self.assertEqual(1, len(traces))
        with open(os.path.join(self.store.directory(), traces[0]),
                  encoding="utf-8") as f:
            trace = json.load(f)
        self.assertEqual("order_change", trace["kind"])
        self.assertEqual("evidence-int-2", trace["request_id"])
        # Shadow order [0,1] (世界 first on base); final [1,0] (时界 first).
        self.assertEqual([0, 1], trace["shadow_order"])
        self.assertEqual([1, 0], trace["final_order"])
        self.assertEqual([0, 1], trace["base_ranks"])
        self.assertEqual([1, 0], trace["final_ranks"])
        # Neighbor event ids come from the real oracle result.
        self.assertEqual(1, len(trace["neighbors"]))
        self.assertIn("event_id", trace["neighbors"][0])
        self.assertEqual(1, self.store.aggregates()["order_changes"])
        # Wire response unchanged.
        self.assertNotIn("_oracle_result", response)

    def test_fault_records_stable_error_identity(self):
        # Watermark mismatch -> true fault -> fault trace with passthrough.
        response = self.call(
            request_id="evidence-int-3",
            fact_high_water={"store_epoch": "wrong",
                             "hlc_physical_ms": 1, "hlc_logical": 0})
        self.assertEqual("fact_identity_mismatch",
                         response["error"]["code"])
        traces = [f for f in self.trace_files()
                  if f.startswith("trace-tr-evidence-int-3-")]
        self.assertEqual(1, len(traces))
        with open(os.path.join(self.store.directory(), traces[0]),
                  encoding="utf-8") as f:
            trace = json.load(f)
        self.assertEqual("fault", trace["kind"])
        self.assertEqual("fact_identity_mismatch", trace["error_code"])
        self.assertTrue(trace["passthrough"])
        agg = self.store.aggregates()
        self.assertEqual(1, agg["faults"])
        self.assertEqual(1, agg["passthroughs"])

    def test_validation_faults_are_recorded(self):
        # Input-correctness / fail-closed violations that never reach the
        # service still count as true faults (spec: they raise an alarm).
        response = self.call(request_id="evidence-int-4",
                             trial={"actionable": True,
                                    "base_scores": [1.0]})  # length mismatch
        self.assertEqual("invalid_request", response["error"]["code"])
        traces = [f for f in self.trace_files()
                  if f.startswith("trace-tr-evidence-int-4-")]
        self.assertEqual(1, len(traces))
        with open(os.path.join(self.store.directory(), traces[0]),
                  encoding="utf-8") as f:
            trace = json.load(f)
        self.assertEqual("fault", trace["kind"])
        self.assertEqual("invalid_request", trace["error_code"])
        self.assertTrue(trace["passthrough"])
        agg = self.store.aggregates()
        self.assertEqual(1, agg["faults"])
        self.assertEqual(1, agg["passthroughs"])

    def test_no_trace_store_keeps_wire_identical(self):
        service = EvidenceService(self.facts_root, PARAMS,
                                  make_provider("时界"), GAMMA)
        state = type("State", (), {"evidence_service": service})()
        request = make_evidence_request(
            schema_id="luna_pinyin", category="word",
            canonical_segment_input="shijie", preceding_text="我",
            candidates=["世界", "时界"],
            config_identity=compose_config_identity(REPR_ID, PARAMS, GAMMA),
            fact_high_water={"store_epoch": "e1", "hlc_physical_ms": 1000000,
                             "hlc_logical": 0})
        request["trial"] = trial(base_scores=[1.0, 0.1])
        response = handle_evidence_request(state, encode(request))
        self.assertEqual("ok", response["status"])
        self.assertEqual(set(response),
                         {"version", "kind", "request_id", "plan_identity",
                          "config_identity", "fact_high_water", "status",
                          "zero_evidence", "evidence", "query_point"})


if __name__ == "__main__":
    unittest.main()
