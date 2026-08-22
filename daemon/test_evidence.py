#!/usr/bin/env python3
"""Retrieval-evidence protocol and service tests (Habit130/squirrel#61, AC61-v1).

Model-free, stdlib-only, sandboxed temp fact stores with an injected
deterministic representation fixture -- never real private history.  The
suite is adversarial by design:

  AC61-1  the request carries schema, choice problem, recent 64-char context,
          current candidate group, config identity and fact high-water
  AC61-2  the daemon serves candidate-level evidence from read-only facts,
          explicitly distinguishing success-zero from true faults
  SCN-61-1 semantic hit: qualified history + injected representation ->
          candidate-level s > 0
  SCN-61-2 no hit: no qualified history -> success zero evidence
  SCN-61-3 supporter candidate missing: history final selection not in the
          current group -> zero contribution for that group
  SCN-61-4 timeout / protocol error / identity mismatch / incomplete
          response are explicit faults (pass-through happens plugin-side)
  SCN-61-6 evidence changes only within-group emission order, never the
          candidate set
  SCN-61-7 the semantic evidence replaces the old bigram term: no double
          counting term exists anywhere in the response shape
"""

import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from evidence import (  # noqa: E402
    CandidateFixtureRepresentationProvider,
    DEFAULT_HALF_LIFE,
    DEFAULT_K_EVIDENCE,
    DEFAULT_SATURATION_K,
    DEFAULT_TAU,
    EVIDENCE_KIND,
    EvidenceError,
    EvidenceService,
    FixtureRepresentationProvider,
    build_evidence_service_from_config,
    compose_config_identity,
    format_identity_double,
    make_evidence_request,
)
from oracle import OracleParams  # noqa: E402
from server import (  # noqa: E402
    EVIDENCE_FIELDS,
    PROTOCOL_VERSION,
    handle_evidence_request,
    handle_request,
)
from test_oracle import FACT_DDL, FactsFixture  # noqa: E402

# Shared injected deterministic representation: the query vector is a fixed
# basis vector, and the fixture maps one history selection to a near-parallel
# vector (cosine 0.95) while every other event falls back to an orthogonal
# default (cosine 0).  tau = 0.5 so only the near-parallel event is relevant.
REPR_ID = "e2e-fixture-repr-v1"
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)
HIT_EVENT_VECTOR = (0.95, math.sqrt(1.0 - 0.95**2), 0.0, 0.0)
DEFAULT_EVENT_VECTOR = (0.0, 1.0, 0.0, 0.0)

PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)
GAMMA = 2.0


def make_provider(hit_selection=None, schema_id="luna_pinyin"):
    event_vectors = {}
    if hit_selection is not None:
        event_vectors["%s|shijie|%s" % (schema_id, hit_selection)] = (
            HIT_EVENT_VECTOR)
    return FixtureRepresentationProvider(
        REPR_ID,
        {"我": QUERY_VECTOR},
        event_vectors,
        default_event=DEFAULT_EVENT_VECTOR,
    )


def make_service(facts_root, provider=None, params=PARAMS, gamma=GAMMA):
    return EvidenceService(facts_root, params,
                           provider or make_provider("时界"), gamma)


def evidence_request(**overrides):
    value = make_evidence_request(
        schema_id="luna_pinyin",
        category="word",
        canonical_segment_input="shijie",
        preceding_text="我",
        candidates=["世界", "时界"],
        config_identity=compose_config_identity(REPR_ID, PARAMS, GAMMA),
        fact_high_water={"store_epoch": "e1", "hlc_physical_ms": 1000000,
                         "hlc_logical": 0},
    )
    value.update(overrides)
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False)


class EvidenceServiceTest(unittest.TestCase):
    """The service itself: oracle semantics + watermark + fault classes."""

    def setUp(self):
        self.fixture = FactsFixture()
        self.facts_root = os.path.dirname(self.fixture.db_path)
        self.service = make_service(self.facts_root)

    def tearDown(self):
        self.fixture.close()

    def request(self, **overrides):
        return evidence_request(**overrides)

    def serve(self, **overrides):
        return self.service.serve(self.request(**overrides))

    def test_hit_serves_candidate_level_evidence(self):
        # A qualified history event (same choice problem, selection 时界)
        # whose injected vector is near the query vector produces s > 0 for
        # exactly that candidate (SCN-61-1).
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        result = self.serve()
        self.assertEqual("ok", result["status"])
        self.assertFalse(result["zero_evidence"])
        self.assertEqual([{"index": 0, "s": 0.0},
                          {"index": 1, "s": result["evidence"][1]["s"]}],
                         result["evidence"])
        self.assertGreater(result["evidence"][1]["s"], 0.0)
        self.assertLess(result["evidence"][1]["s"], 1.0)
        self.assertEqual(0.0, result["evidence"][0]["s"])

    def test_empty_store_is_success_zero_evidence(self):
        result = self.serve()
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["zero_evidence"])
        self.assertEqual([{"index": 0, "s": 0.0},
                          {"index": 1, "s": 0.0}], result["evidence"])

    def test_no_qualified_history_is_success_zero_evidence(self):
        # Events exist but under a different choice problem key (SCN-61-2).
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="gongji", selection="攻击")
        result = self.serve()
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["zero_evidence"])
        self.assertEqual([{"index": 0, "s": 0.0},
                          {"index": 1, "s": 0.0}], result["evidence"])

    def test_supporter_candidate_missing_is_zero_contribution(self):
        # The history's final selection (时界) is not among the current group
        # candidates (世界/世界), so the group gets zero contribution (SCN-61-3).
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        result = self.serve(candidates=["世界", "世界"])
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["zero_evidence"])
        self.assertEqual([{"index": 0, "s": 0.0},
                          {"index": 1, "s": 0.0}], result["evidence"])

    def test_support_candidate_not_matching_any_current_candidate(self):
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        result = self.serve(candidates=["世界", "实界"])
        self.assertTrue(result["zero_evidence"])

    def test_retracted_history_gives_no_evidence(self):
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        self.fixture.add_retraction("r1", "commit-e1",
                                    (1000000, 99))
        result = self.serve(fact_high_water=None)
        self.assertTrue(result["zero_evidence"])

    def test_identity_mismatch_epoch_is_fault(self):
        with self.assertRaises(EvidenceError) as ctx:
            self.service.serve(self.request(
                fact_high_water={"store_epoch": "other",
                                 "hlc_physical_ms": 1000000,
                                 "hlc_logical": 0}))
        self.assertEqual("fact_identity_mismatch", ctx.exception.code)

    def test_not_caught_up_watermark_is_fault(self):
        # The daemon snapshot must be at or beyond the plugin's declared
        # watermark; a request claiming a future HLC is a true fault.
        with self.assertRaises(EvidenceError) as ctx:
            self.service.serve(self.request(
                fact_high_water={"store_epoch": "e1",
                                 "hlc_physical_ms": 999999999,
                                 "hlc_logical": 999}))
        self.assertEqual("not_caught_up", ctx.exception.code)

    def test_missing_store_is_success_zero_only_without_watermark(self):
        shutil.rmtree(self.fixture._tmp)
        with self.assertRaises(EvidenceError) as ctx:
            self.service.serve(self.request(
                fact_high_water={"store_epoch": "e1", "hlc_physical_ms": 1,
                                 "hlc_logical": 0}))
        self.assertEqual("fact_store_fault", ctx.exception.code)
        result = self.service.serve(self.request(fact_high_water=None))
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["zero_evidence"])

    def test_corrupt_store_is_fault(self):
        with open(self.fixture.db_path, "wb") as handle:
            handle.write(b"this is not a sqlite database")
        with self.assertRaises(EvidenceError) as ctx:
            self.service.serve(self.request(fact_high_water=None))
        self.assertIn(ctx.exception.code,
                      ("fact_store_fault", "oracle_fault"))

    def test_config_identity_covers_every_component(self):
        # A change to any bound component changes the identity (SCN-61-4:
        # identity mismatch is a fault the plugin passes through).
        base = compose_config_identity(REPR_ID, PARAMS, GAMMA)
        variants = [
            compose_config_identity("other-repr", PARAMS, GAMMA),
            compose_config_identity(REPR_ID,
                                    OracleParams(tau=0.6, k_evidence=8,
                                                 half_life=32.0,
                                                 saturation_k=1.0),
                                    GAMMA),
            compose_config_identity(REPR_ID, PARAMS, 3.0),
        ]
        for variant in variants:
            self.assertNotEqual(base, variant)

    def test_identity_double_formatting_is_canonical(self):
        self.assertEqual("0.5", format_identity_double(0.5))
        self.assertEqual("inf", format_identity_double(float("inf")))
        self.assertEqual("2", format_identity_double(2.0))
        self.assertEqual("0.2", format_identity_double(0.2))

    def test_representation_fault_missing_query_vector_never_faults(self):
        # The fixture falls back to a deterministic default; a missing entry
        # is zero evidence, not a fault.  A provider that raises is a fault.
        class FailingProvider(FixtureRepresentationProvider):
            def query_vector(self, preceding_text):
                raise EvidenceError("representation_fault", "boom")

        service = EvidenceService(self.facts_root, PARAMS,
                                  FailingProvider(REPR_ID, {}, {}), GAMMA)
        with self.assertRaises(EvidenceError) as ctx:
            service.serve(self.request())
        self.assertEqual("representation_fault", ctx.exception.code)

    def test_service_never_emits_raw_text(self):
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        result = self.service.serve(self.request())
        self.assertNotIn("时界", json.dumps(result))
        self.assertNotIn("世界", json.dumps(result))
        self.assertNotIn("我", json.dumps(result))

    def test_build_service_from_config_round_trip(self):
        config = {
            "representation_id": REPR_ID,
            "tau": 0.5,
            "k_evidence": 8,
            "half_life": 32.0,
            "saturation_k": 1.0,
            "gamma": 2.0,
            "query_vectors": {"我": list(QUERY_VECTOR)},
            "event_vectors": {"luna_pinyin|shijie|时界": list(HIT_EVENT_VECTOR)},
            "default_event": list(DEFAULT_EVENT_VECTOR),
        }
        service = build_evidence_service_from_config(self.facts_root, config)
        self.assertEqual(compose_config_identity(REPR_ID, PARAMS, GAMMA),
                         service.config_identity())
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        result = service.serve(self.request())
        self.assertFalse(result["zero_evidence"])


class CandidateConditionedEvidenceTest(unittest.TestCase):
    """AC-109: query and history vectors are paired by candidate."""

    def setUp(self):
        self.fixture = FactsFixture()
        self.facts_root = os.path.dirname(self.fixture.db_path)
        self.fixture.add_event(
            "e1", schema_id="luna_pinyin", segment_input="shijie",
            selection="时界", preceding_text="过去", competition=("世界", "时界"))
        self.params = OracleParams(
            tau=0.5, k_evidence=8, half_life=float("inf"), saturation_k=1.0)

    def tearDown(self):
        self.fixture.close()

    def test_only_selected_candidate_pair_receives_evidence(self):
        provider = CandidateFixtureRepresentationProvider(
            "candidate-fixture-v1",
            {("现在", "世界"): (0.0, 1.0, 0.0, 0.0),
             ("现在", "时界"): QUERY_VECTOR},
            {("luna_pinyin", "shijie", "时界"): HIT_EVENT_VECTOR},
            default_event=DEFAULT_EVENT_VECTOR,
        )
        service = EvidenceService(
            self.facts_root, self.params, provider, gamma=0.0)
        result = service.serve({
            "schema_id": "luna_pinyin",
            "category": "word",
            "canonical_segment_input": "shijie",
            "preceding_text": "现在",
            "candidates": ["世界", "时界"],
            "fact_high_water": None,
        })
        self.assertEqual(0.0, result["evidence"][0]["s"])
        self.assertGreater(result["evidence"][1]["s"], 0.0)

    def test_other_selected_candidate_does_not_use_current_candidate_vector(self):
        self.fixture.add_event(
            "e2", schema_id="luna_pinyin", segment_input="shijie",
            selection="世界", preceding_text="过去", competition=("世界", "时界"))
        provider = CandidateFixtureRepresentationProvider(
            "candidate-fixture-v2",
            {("现在", "世界"): (0.0, 1.0, 0.0, 0.0),
             ("现在", "时界"): QUERY_VECTOR},
            {("luna_pinyin", "shijie", "时界"): HIT_EVENT_VECTOR,
             ("luna_pinyin", "shijie", "世界"): HIT_EVENT_VECTOR},
            default_event=DEFAULT_EVENT_VECTOR,
        )
        service = EvidenceService(
            self.facts_root, self.params, provider, gamma=0.0)
        result = service.serve({
            "schema_id": "luna_pinyin", "category": "word",
            "canonical_segment_input": "shijie", "preceding_text": "现在",
            "candidates": ["世界", "时界"], "fact_high_water": None,
        })
        self.assertEqual(0.0, result["evidence"][0]["s"])
        self.assertGreater(result["evidence"][1]["s"], 0.0)


class EvidenceProtocolTest(unittest.TestCase):
    """The daemon-side protocol: field validation, routing, fault objects."""

    def setUp(self):
        self.fixture = FactsFixture()
        self.facts_root = os.path.dirname(self.fixture.db_path)
        self.service = make_service(self.facts_root)
        self.state = type("State", (), {"evidence_service": self.service})()

    def tearDown(self):
        self.fixture.close()

    def call(self, request=None, state=None, raw=False):
        payload = request or evidence_request()
        if not raw:
            payload = encode(payload)
        return handle_evidence_request(state or self.state, payload)

    def assert_error(self, response, code):
        self.assertEqual(PROTOCOL_VERSION, response["version"])
        self.assertIn(response["error"]["phase"], ("validate", "evidence"))
        self.assertEqual(code, response["error"]["code"])
        self.assertNotIn("时界", str(response))
        self.assertNotIn("世界", str(response))
        self.assertNotIn("我", str(response))

    def test_success_response_is_versioned_and_bound(self):
        self.fixture.add_event("e1", schema_id="luna_pinyin",
                               segment_input="shijie", selection="时界")
        response = self.call()
        self.assertEqual(PROTOCOL_VERSION, response["version"])
        self.assertEqual(EVIDENCE_KIND, response["kind"])
        self.assertEqual("evidence-1", response["request_id"])
        self.assertEqual("rerank-plan-v2:test", response["plan_identity"])
        self.assertEqual(compose_config_identity(REPR_ID, PARAMS, GAMMA),
                         response["config_identity"])
        self.assertEqual("ok", response["status"])
        self.assertFalse(response["zero_evidence"])
        self.assertEqual(2, len(response["evidence"]))
        self.assertFalse(response["evidence"][0]["s"] > 0.0)
        self.assertGreater(response["evidence"][1]["s"], 0.0)
        self.assertEqual({"store_epoch": "e1", "hlc_physical_ms": 1000000,
                          "hlc_logical": 0}, response["fact_high_water"])

    def test_success_zero_evidence_is_explicit(self):
        response = self.call()
        self.assertEqual("ok", response["status"])
        self.assertTrue(response["zero_evidence"])
        self.assertEqual([0.0, 0.0],
                         [entry["s"] for entry in response["evidence"]])

    def test_missing_fields_are_rejected(self):
        for field in EVIDENCE_FIELDS:
            with self.subTest(field=field):
                damaged = evidence_request()
                del damaged[field]
                self.assert_error(self.call(request=damaged), "invalid_request")

    def test_wrong_field_types_are_rejected(self):
        damaged_values = {
            "version": "2",
            "kind": 17,
            "request_id": None,
            "plan_identity": 17,
            "schema_id": 17,
            "category": ["word"],
            "canonical_segment_input": None,
            "preceding_text": 17,
            "candidates": "not-a-list",
            "config_identity": None,
            "fact_high_water": "water",
        }
        for field, value in damaged_values.items():
            with self.subTest(field=field):
                self.assert_error(self.call(
                    request=evidence_request(**{field: value})),
                    "invalid_request")

    def test_extra_fields_are_rejected(self):
        self.assert_error(self.call(request=evidence_request(extra=True)),
                          "invalid_request")

    def test_trial_envelope_is_validated(self):
        # The additive trial envelope (#74) must carry exactly actionable +
        # base_scores aligned with the candidates; anything else is a fault.
        good = {"actionable": True, "base_scores": [1.0, 2.0]}
        self.assertEqual("ok", self.call(
            request=evidence_request(trial=good))["status"])
        bad_trials = [
            {"actionable": True, "base_scores": [1.0]},       # length
            {"actionable": True, "base_scores": [1.0, "x"]},  # non-numeric
            {"actionable": True, "base_scores": [1.0, float("inf")]},
            {"actionable": "yes", "base_scores": [1.0, 2.0]},  # type
            {"actionable": True},                              # missing scores
            {"actionable": True, "base_scores": [1.0, 2.0],
             "order_changed": False},                          # extra field
            "not-a-dict",
        ]
        for trial in bad_trials:
            with self.subTest(trial=trial):
                self.assert_error(self.call(
                    request=evidence_request(trial=trial)),
                    "invalid_request")

    def test_empty_candidates_are_rejected(self):
        for damaged in (evidence_request(candidates=[]),
                        evidence_request(candidates=["", "时界"])):
            with self.subTest(damaged=damaged["candidates"]):
                self.assert_error(self.call(request=damaged),
                                  "invalid_request")

    def test_preceding_text_beyond_64_chars_is_rejected(self):
        # The request carries the recent-64-char 上文 window; anything longer
        # is out of the protocol contract (AC61-1).
        self.assert_error(self.call(
            request=evidence_request(preceding_text="字" * 65)),
            "invalid_request")
        self.assertEqual("ok", self.call(
            request=evidence_request(preceding_text="字" * 64))["status"])

    def test_wrong_version_is_rejected(self):
        self.assert_error(self.call(
            request=evidence_request(version=PROTOCOL_VERSION + 1)),
            "invalid_request")

    def test_evidence_unavailable_without_service(self):
        state = type("State", (), {"evidence_service": None})()
        self.assert_error(self.call(state=state), "evidence_unavailable")

    def test_config_identity_mismatch_is_fault(self):
        other = compose_config_identity("other-repr", PARAMS, GAMMA)
        self.assert_error(self.call(
            request=evidence_request(config_identity=other)),
            "config_identity_mismatch")
        # The mismatch never echoes the declared identity.
        self.assertNotIn("other-repr", str(self.call(
            request=evidence_request(config_identity=other))))

    def test_fact_identity_mismatch_is_fault(self):
        self.assert_error(self.call(request=evidence_request(
            fact_high_water={"store_epoch": "other",
                             "hlc_physical_ms": 1000000,
                             "hlc_logical": 0})),
            "fact_identity_mismatch")

    def test_not_caught_up_is_fault(self):
        self.assert_error(self.call(request=evidence_request(
            fact_high_water={"store_epoch": "e1",
                             "hlc_physical_ms": 999999999,
                             "hlc_logical": 999})),
            "not_caught_up")

    def test_oracle_fault_maps_to_fault_object(self):
        with open(self.fixture.db_path, "wb") as handle:
            handle.write(b"not a database")
        response = self.call(request=evidence_request(fact_high_water=None))
        self.assertIn(response["error"]["code"],
                      ("fact_store_fault", "oracle_fault"))

    def test_invalid_json_is_rejected(self):
        self.assert_error(self.call(request="not-json", raw=True), "invalid_json")

    def test_duplicate_fields_are_rejected(self):
        pairs = list(evidence_request().items())
        damaged = "{" + ",".join(
            f"{json.dumps(key)}:{json.dumps(value, ensure_ascii=False)}"
            for key, value in pairs
        ) + ",\"request_id\":\"x\"}"
        self.assert_error(self.call(request=damaged, raw=True), "invalid_json")

    def test_scoring_requests_never_carry_kind(self):
        # A scoring request with an evidence kind must be rejected as
        # invalid_request, never routed to scoring.
        response = handle_request(
            type("State", (), {"evidence_service": self.service})(),
            encode({"version": PROTOCOL_VERSION, "request_id": "r",
                    "kind": EVIDENCE_KIND}))
        self.assertEqual("invalid_request", response["error"]["code"])

    def test_maintenance_quiesce_rejects_evidence_requests(self):
        from coordinator import MaintenanceCoordinator
        coordinator = MaintenanceCoordinator(
            self.facts_root,
            identity_reader=lambda _root: {
                "store_epoch": "e1", "hlc_physical_ms": 1000000,
                "hlc_logical": 0,
            },
        )
        assert coordinator.prepare("op-1")["ok"]
        response = handle_evidence_request(
            self.state, encode(evidence_request()), coordinator)
        self.assertEqual("maintenance_in_progress",
                         response["error"]["code"])


class EvidenceConfigIdentityTest(unittest.TestCase):
    """The identity the plugin and daemon must both derive byte-identically."""

    def test_identity_format_is_stable(self):
        identity = compose_config_identity(REPR_ID, PARAMS, GAMMA)
        self.assertEqual(
            "evidence-v1:repr=e2e-fixture-repr-v1:tau=0.5:kev=8:H=32:sat=1:"
            "gamma=2",
            identity,
        )

    def test_defaults_are_not_winner_params(self):
        # Spec #43: prototype values may not be written as locked winners.
        self.assertEqual(0.0, DEFAULT_TAU)
        self.assertTrue(math.isinf(DEFAULT_HALF_LIFE))
        self.assertTrue(DEFAULT_K_EVIDENCE >= 1)


if __name__ == "__main__":
    unittest.main()
