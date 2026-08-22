#!/usr/bin/env python3
"""Model-free candidate-conditioned adapter for the accepted #69 v1 set.

This is a development/regression adapter only. It deliberately imports the
accepted v1 benchmark, never the deferred v2 module, and uses controlled
vectors to exercise the four candidate-conditioned route identities and the
positive-only evidence path.
"""

import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAEMON = os.path.join(_ROOT, "daemon")
if _DAEMON not in sys.path:
    sys.path.insert(0, _DAEMON)

from evidence import (  # noqa: E402
    CandidateFixtureRepresentationProvider,
    EvidenceService,
    compose_config_identity,
)
from oracle import OracleParams  # noqa: E402
from representations import (  # noqa: E402
    candidate_conditioned_payload,
    candidate_conditioned_specs,
)
from semantic_benchmark import (  # noqa: E402
    BENCHMARK_K_EVIDENCE,
    BENCHMARK_SATURATION_K,
    BENCHMARK_TAU,
    BENCHMARK_HALF_LIFE,
    CATEGORY,
    FIXTURE_DISTRACTOR_PRECEDING_TEXTS,
    SCHEMA_ID,
    SyntheticFacts,
    benchmark_cases,
    benchmark_manifest,
)


CONTRACT_ID = "AC-109-v1"
PAYLOAD_SCHEMA = "candidate-conditioned-concat-v1"
V1_DIGEST = "69205442228a14b6942e2a4de999587e893125f24f3d91e3e218a0140e2df1ec"
QUERY_AXIS = (1.0, 0.0, 0.0, 0.0)
ORTHOGONAL_AXIS = (0.0, 1.0, 0.0, 0.0)
DEFAULT_EVENT_AXIS = (0.0, 0.0, 1.0, 0.0)


def route_ids():
    """Stable route names for the four frozen pooling candidates."""
    return tuple(spec.short_name for spec in candidate_conditioned_specs())


def payload(preceding_text, candidate):
    """Expose the frozen payload for adapter tests and reports."""
    return candidate_conditioned_payload(preceding_text, candidate)


def _near_axis(cosine):
    return (cosine, math.sqrt(1.0 - cosine * cosine), 0.0, 0.0)


def _case_result(case, representation_id):
    fixture = SyntheticFacts(case, FIXTURE_DISTRACTOR_PRECEDING_TEXTS)
    try:
        expected = case.expected_candidate
        query_vectors = {
            (payload(case.query_preceding_text, candidate), candidate): (
                QUERY_AXIS if candidate == expected else ORTHOGONAL_AXIS)
            for candidate in case.candidates
        }
        target_cosine = 0.97 if case.relation == "positive" else 0.10
        event_vectors = {
            (payload(case.recorded_preceding_text, case.history_selection),
             SCHEMA_ID, case.choice_problem, case.history_selection):
            _near_axis(target_cosine)
        }
        params = OracleParams(
            tau=BENCHMARK_TAU,
            k_evidence=BENCHMARK_K_EVIDENCE,
            half_life=BENCHMARK_HALF_LIFE,
            saturation_k=BENCHMARK_SATURATION_K,
        )
        provider = CandidateFixtureRepresentationProvider(
            representation_id, query_vectors, event_vectors,
            default_query=ORTHOGONAL_AXIS,
            default_event=DEFAULT_EVENT_AXIS,
        )
        service = EvidenceService(
            os.path.dirname(fixture.db_path), params, provider, gamma=0.0)
        response = service.serve({
            "schema_id": SCHEMA_ID,
            "category": CATEGORY,
            "canonical_segment_input": case.choice_problem,
            "preceding_text": case.query_preceding_text,
            "candidates": list(case.candidates),
            "fact_high_water": None,
        })
        expected_index = case.candidates.index(expected)
        expected_evidence = response["evidence"][expected_index]["s"]
        passed = (expected_evidence > 0.0
                  if case.relation == "positive"
                  else expected_evidence == 0.0)
        return passed, response
    finally:
        fixture.close()


def run_fixture_adapter():
    """Run the four routes over a bounded, controlled subset of #69 v1."""
    manifest = benchmark_manifest()
    if manifest["benchmark_digest"] != V1_DIGEST:
        raise RuntimeError("accepted #69 v1 digest changed")
    cases = (benchmark_cases()[0], benchmark_cases()[2])
    results = {}
    for spec in candidate_conditioned_specs():
        route = spec.short_name
        passed = []
        for case in cases:
            ok, response = _case_result(case, "fixture:%s" % route)
            passed.append({
                "relation": case.relation,
                "passed": ok,
                "zero_evidence": response["zero_evidence"],
                "evidence_indexes": [
                    entry["index"] for entry in response["evidence"]
                    if entry["s"] > 0.0
                ],
            })
        results[route] = passed
    return {
        "contract": CONTRACT_ID,
        "payload_schema": PAYLOAD_SCHEMA,
        "v1_benchmark_digest": manifest["benchmark_digest"],
        "routes": results,
        "v2": "not_read_or_run",
    }


if __name__ == "__main__":
    report = run_fixture_adapter()
    print("candidate-conditioned v1 adapter: PASS")
    print("routes: %s" % ", ".join(report["routes"]))
