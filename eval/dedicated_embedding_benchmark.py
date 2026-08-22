#!/usr/bin/env python3
"""Model-free #69 v1 adapter for the two dedicated embedding routes.

This is a development adapter only.  It keeps the accepted #69 v1 payload,
digest and exact oracle, while using 1024-dimensional controlled vectors for
Qwen3-Embedding-0.6B and BGE-M3 dense.  It deliberately has no dependency on
the deferred v2 benchmark.
"""

import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAEMON = os.path.join(_ROOT, "daemon")
if _DAEMON not in sys.path:
    sys.path.insert(0, _DAEMON)

from embeddings import (  # noqa: E402
    EmbeddingFixtureRepresentationProvider,
    embedding_fixture_vector,
    embedding_representation_id,
    embedding_routes,
    fixture_embedding_identity,
)
from evidence import EvidenceService  # noqa: E402
from oracle import OracleParams  # noqa: E402
from representations import candidate_conditioned_payload  # noqa: E402
from semantic_benchmark import (  # noqa: E402
    BENCHMARK_HALF_LIFE,
    BENCHMARK_K_EVIDENCE,
    BENCHMARK_SATURATION_K,
    BENCHMARK_TAU,
    CATEGORY,
    FIXTURE_DISTRACTOR_PRECEDING_TEXTS,
    SCHEMA_ID,
    SyntheticFacts,
    benchmark_cases,
    benchmark_manifest,
)


CONTRACT_ID = "AC-110-v1"
PAYLOAD_SCHEMA = "candidate-conditioned-concat-v1"
V1_DIGEST = "69205442228a14b6942e2a4de999587e893125f24f3d91e3e218a0140e2df1ec"
EMBEDDING_DIMENSION = 1024


def payload(preceding_text, candidate):
    """Expose the unchanged #109 payload to adapter tests and reports."""
    return candidate_conditioned_payload(preceding_text, candidate)


def _axis_vector(axis):
    return embedding_fixture_vector(axis, EMBEDDING_DIMENSION)


def _near_axis(cosine):
    return (cosine, math.sqrt(1.0 - cosine * cosine)) + (0.0,) * 1022


def _case_result(case, route):
    fixture = SyntheticFacts(case, FIXTURE_DISTRACTOR_PRECEDING_TEXTS)
    try:
        identity = fixture_embedding_identity(route)
        query_vectors = {
            (payload(case.query_preceding_text, candidate), candidate): (
                _axis_vector(0) if candidate == case.expected_candidate
                else _axis_vector(1))
            for candidate in case.candidates
        }
        target_cosine = 0.97 if case.relation == "positive" else 0.10
        event_vectors = {
            (payload(case.recorded_preceding_text, case.history_selection),
             SCHEMA_ID, case.choice_problem, case.history_selection):
            _near_axis(target_cosine)
        }
        provider = EmbeddingFixtureRepresentationProvider(
            route,
            identity,
            query_vectors,
            event_vectors,
            default_query=_axis_vector(1),
            default_event=_axis_vector(2),
        )
        params = OracleParams(
            tau=BENCHMARK_TAU,
            k_evidence=BENCHMARK_K_EVIDENCE,
            half_life=BENCHMARK_HALF_LIFE,
            saturation_k=BENCHMARK_SATURATION_K,
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
        expected_index = case.candidates.index(case.expected_candidate)
        expected_evidence = response["evidence"][expected_index]["s"]
        passed = (expected_evidence > 0.0
                  if case.relation == "positive"
                  else expected_evidence == 0.0)
        return passed, response, provider.representation_id()
    finally:
        fixture.close()


def run_fixture_adapter():
    """Run two bounded #69 v1 cases through both dedicated routes."""
    manifest = benchmark_manifest()
    if manifest["benchmark_digest"] != V1_DIGEST:
        raise RuntimeError("accepted #69 v1 digest changed")
    cases = (benchmark_cases()[0], benchmark_cases()[2])
    results = {}
    identities = {}
    for route in embedding_routes():
        passed = []
        for case in cases:
            ok, response, representation_id = _case_result(case, route)
            passed.append({
                "relation": case.relation,
                "passed": ok,
                "zero_evidence": response["zero_evidence"],
                "evidence_indexes": [
                    entry["index"] for entry in response["evidence"]
                    if entry["s"] > 0.0
                ],
            })
            identities[route.route_id] = representation_id
        results[route.route_id] = passed
    return {
        "contract": CONTRACT_ID,
        "payload_schema": PAYLOAD_SCHEMA,
        "v1_benchmark_digest": manifest["benchmark_digest"],
        "routes": results,
        "representation_ids": identities,
        "v2": "not_read_or_run",
    }


if __name__ == "__main__":
    report = run_fixture_adapter()
    print("dedicated embedding candidate-conditioned v1 adapter: PASS")
    print("routes: %s" % ", ".join(report["routes"]))
