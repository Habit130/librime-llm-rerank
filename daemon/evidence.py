#!/usr/bin/env python3
"""Candidate-level retrieval evidence for the rerank filter (Habit130/squirrel#61).

The daemon side of the evidence protocol: given one rerank group's request,
serve the canonical oracle's bounded retrieval evidence ``s_c`` per candidate
from the read-only fact store, using an injectable deterministic
representation seam.  This is the bridge that replaces the first-stage bigram
term: the plugin applies ``gamma * s_c`` to the base score only on a complete
success response, and every true fault passes the whole window through in
original order.

Protocol contract (AC61-1 / AC61-2):

- Request fields (exact set, validated by server.py):
    version, kind="evidence", request_id, plan_identity, schema_id,
    category, canonical_segment_input, preceding_text, candidates,
    config_identity, fact_high_water

- ``config_identity`` binds the evidence semantics: representation id plus
  oracle params (tau, k_evidence, half_life, saturation_k) plus gamma.  The
  daemon composes the identity it is configured to serve and rejects any
  request that declares a different one (config_identity_mismatch -> fault).

- ``fact_high_water`` is the plugin's declared fact snapshot
  (``store_epoch`` + max change HLC).  The daemon must prove its own read-only
  snapshot is at or beyond that watermark before serving; an epoch mismatch or
  a snapshot behind the watermark is a true fault, never a stale success.

- Success responses carry ``status: "ok"`` and a per-candidate ``s`` array;
  zero evidence (empty store, no same-key events, nothing above the
  threshold, nothing matching the current group) is still ``status: "ok"``
  with ``zero_evidence: true``.  Missing/corrupt stores, missing vectors,
  non-finite values and representation faults are explicit ``error`` objects.

- The response never contains raw text: candidate indexes and numeric
  decompositions only.

The representation seam (#62 hook): ``RepresentationProvider`` supplies the
query vector for the request's preceding text and a deterministic vector for
every stored event.  ``FixtureRepresentationProvider`` is the injected,
model-free deterministic implementation used by the daemon tests and the
end-to-end gate; the #62 generation builder plugs a real hidden-state
provider behind the same interface.
"""

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import (Dict, List, Mapping, Optional, Sequence, Tuple)

from oracle import (FactReader, OracleError, OracleParams, OracleQuery,
                    compute_evidence)

# #72/#73: the exact retrieval backend the daemon serves evidence with.  All
# backends compute the same exact evidence over the same facts/vectors; the
# Accelerate backend uses Apple vecLib and the MLX backend uses mlx.core for
# the per-event cosine while the oracle backend uses Python scalar math.
# The configured backend is bound into the index fingerprint (see
# compat.compose_backend_fingerprint); the config seam never silently
# switches backends.
BACKEND_ORACLE = "exact"
BACKEND_ACCELERATE = "accelerate-cblas-sgemv"
BACKEND_MLX = "mlx-exact-matmul"

EVIDENCE_KIND = "evidence"
EVIDENCE_PROTOCOL_VERSION = 2
EVIDENCE_CONFIG_ID_VERSION = "evidence-v1"

# Oracle params defaults are deliberately NOT production winners (spec #43:
# no prototype grid value may be written as a locked winner).  A caller that
# wants a nonzero evidence path must configure every param explicitly; the
# daemon's configured identity is what it serves.
DEFAULT_TAU = 0.0
DEFAULT_K_EVIDENCE = 8
DEFAULT_HALF_LIFE = float("inf")
DEFAULT_SATURATION_K = 3.0


class EvidenceError(Exception):
    """A true fault in the evidence path.

    Distinct from zero evidence: callers must treat EvidenceError as a
    failure (plugin pass-through), never as an empty result.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def quantize_identity_double(value):
    """Ingest a double into the six-significant-digit config-identity domain.

    Six significant digits (``defaultfloat`` / ``%.6g``) are the canonical
    configuration domain (Habit130/squirrel#132 option 1 / #151), not merely
    a display format. Values that differ only beyond that precision are the
    same config. Already-canonical values keep today's bytes. Infinity is
    accepted; other non-finite values fail closed. AC-61 is not superseded.
    """
    if math.isinf(value):
        return float("inf")
    if not math.isfinite(value):
        raise EvidenceError("config_identity", "non-finite config value")
    return float(format(value, ".6g"))


def format_identity_double(value):
    """Canonical double formatting shared with the C++ plugin.

    Ingests via ``quantize_identity_double`` so colliding inputs share one
    identity string. Both sides must stay byte-identical: ``%g``-style with
    six significant digits, ``inf`` for infinity (C++ defaultfloat +
    setprecision(6)).
    """
    quantized = quantize_identity_double(value)
    if math.isinf(quantized):
        return "inf"
    return format(quantized, ".6g")


def compose_config_identity(representation_id, params, gamma):
    """Canonical evidence config identity (AC61-1 "配置身份").

    Covers the representation seam id and every oracle/gamma parameter that
    changes the served evidence semantics; a change in any component yields a
    different identity, and the daemon serves exactly the identity it was
    configured with. Every double is ingested into the six-significant-digit
    domain before the string is composed.
    """
    if not representation_id or not isinstance(representation_id, str):
        raise EvidenceError("config_identity",
                            "representation_id must be a non-empty string")
    if not isinstance(params, OracleParams):
        raise EvidenceError("config_identity", "params must be OracleParams")
    if not isinstance(gamma, (int, float)) or not math.isfinite(gamma):
        raise EvidenceError("config_identity", "gamma must be finite")
    return "%s:repr=%s:tau=%s:kev=%s:H=%s:sat=%s:gamma=%s" % (
        EVIDENCE_CONFIG_ID_VERSION,
        representation_id,
        format_identity_double(params.tau),
        params.k_evidence,
        format_identity_double(params.half_life),
        format_identity_double(params.saturation_k),
        format_identity_double(gamma),
    )


# ---------------------------------------------------------------------------
# The injectable representation seam (#62 hook)
# ---------------------------------------------------------------------------

class RepresentationProvider:
    """Deterministic vector seam for one representation identity.

    ``query_vector`` turns the request's preceding text into the query
    representation; ``event_vector`` turns one stored selection event into
    the representation that was (or will be) generated for it.  A missing or
    unusable event vector is a true fault (the oracle's ``vector_for`` raises
    OracleError), never silent zero evidence.  ``vector_dimension`` declares
    the fixed output dimension (the generation builder binds it into the
    container identity).  #62 plugs a real generation-backed provider behind
    this interface.
    """

    def representation_id(self):
        raise NotImplementedError

    def query_vector(self, preceding_text):
        raise NotImplementedError

    def event_vector(self, event):
        raise NotImplementedError

    def vector_dimension(self):
        raise NotImplementedError

    def is_candidate_conditioned(self):
        """Whether vectors require the current/selected candidate argument."""
        return False

    def query_vector_for_candidate(self, preceding_text, candidate):
        """Candidate-aware query seam; legacy providers use their old vector."""
        del candidate
        return self.query_vector(preceding_text)

    def event_vector_for_candidate(self, event, candidate):
        """Candidate-aware event seam; legacy providers use their old vector."""
        del candidate
        return self.event_vector(event)


def _normalize(vector):
    values = tuple(float(value) for value in vector)
    if not values:
        raise EvidenceError("representation_fault", "empty vector")
    for value in values:
        if not math.isfinite(value):
            raise EvidenceError("representation_fault",
                                "non-finite vector value")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise EvidenceError("representation_fault", "zero-norm vector")
    return tuple(value / norm for value in values)


def _event_vector_key(schema_id, canonical_segment_input,
                      final_selection_text):
    return (schema_id, canonical_segment_input, final_selection_text)


def _parse_event_vector_keys(mapping):
    """Normalize config keys to the internal tuple form.

    JSON configs use the flat "schema|canonical_input|selection" form or a
    canonical JSON array for candidate-conditioned history keys; the internal
    lookup uses the tuple form so text containing '|' can never collide.
    """
    result = {}
    for key, vector in mapping.items():
        if isinstance(key, tuple):
            result[key] = vector
            continue
        if not isinstance(key, str):
            raise EvidenceError("representation_fault",
                                "event vector key must be a string or tuple")
        try:
            decoded = json.loads(key)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, list) and len(decoded) in (3, 4) \
                and all(isinstance(part, str) for part in decoded):
            result[tuple(decoded)] = vector
            continue
        parts = key.split("|")
        if len(parts) != 3:
            raise EvidenceError(
                "representation_fault",
                "event vector key must be schema|canonical_input|selection")
        result[tuple(parts)] = vector
    return result


class FixtureRepresentationProvider(RepresentationProvider):
    """Injected deterministic representation for tests and the e2e gate.

    Model-free and stdlib-only: query vectors are looked up by the exact
    preceding text, event vectors by ``(schema_id, canonical_segment_input,
    final_selection_text)``; anything not in the fixture falls back to
    orthogonal default vectors (cosine 0 -> no evidence).  Vectors are
    L2-normalized at load, so every cosine relationship is fully controlled
    by the fixture the test writes -- this is the deterministic representation
    the e2e contract requires, and the seam where #62 plugs real generation.
    """

    def __init__(self, representation_id, query_vectors, event_vectors,
                 default_query=(1.0, 0.0, 0.0, 0.0),
                 default_event=(0.0, 1.0, 0.0, 0.0)):
        if not representation_id or not isinstance(representation_id, str):
            raise EvidenceError("representation_fault",
                                "fixture needs a representation_id")
        self._representation_id = representation_id
        self._query_vectors = {
            key: _normalize(vector)
            for key, vector in query_vectors.items()
        }
        self._event_vectors = {
            key: _normalize(vector)
            for key, vector in _parse_event_vector_keys(event_vectors).items()
        }
        self._default_query = _normalize(default_query)
        self._default_event = _normalize(default_event)

    def representation_id(self):
        return self._representation_id

    def query_vector(self, preceding_text):
        return self._query_vectors.get(preceding_text, self._default_query)

    def event_vector(self, event):
        key = _event_vector_key(event.schema_id,
                                 event.canonical_segment_input,
                                 event.final_selection_text)
        return self._event_vectors.get(key, self._default_event)

    def vector_dimension(self):
        return len(self._default_query)


class CandidateFixtureRepresentationProvider(RepresentationProvider):
    """Model-free candidate-conditioned fixture provider.

    Query keys are ``(preceding_text, candidate)``. Event vectors remain bound
    to the immutable event's selected candidate and choice-problem identity.
    """

    def __init__(self, representation_id, query_vectors, event_vectors,
                 default_query=(1.0, 0.0, 0.0, 0.0),
                 default_event=(0.0, 1.0, 0.0, 0.0)):
        if not representation_id or not isinstance(representation_id, str):
            raise EvidenceError("representation_fault",
                                "fixture needs a representation_id")
        self._representation_id = representation_id
        self._query_vectors = {
            self._query_key(key): _normalize(vector)
            for key, vector in query_vectors.items()
        }
        self._event_vectors = {
            key: _normalize(vector)
            for key, vector in _parse_event_vector_keys(event_vectors).items()
        }
        self._default_query = _normalize(default_query)
        self._default_event = _normalize(default_event)

    @staticmethod
    def _query_key(key):
        if isinstance(key, tuple) and len(key) == 2:
            return key
        if isinstance(key, str):
            try:
                decoded = json.loads(key)
            except (TypeError, ValueError):
                decoded = key.split("|", 1)
            if isinstance(decoded, list) and len(decoded) == 2:
                decoded = tuple(decoded)
            if isinstance(decoded, (list, tuple)) and len(decoded) == 2 \
                    and all(isinstance(part, str) for part in decoded):
                return tuple(decoded)
        raise EvidenceError(
            "representation_fault",
            "candidate query key must be (preceding_text, candidate)")

    def representation_id(self):
        return self._representation_id

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        raise EvidenceError(
            "representation_fault",
            "candidate-conditioned query requires a candidate")

    def query_vector_for_candidate(self, preceding_text, candidate):
        vector = self._query_vectors.get((preceding_text, candidate))
        if vector is None:
            from representations import candidate_conditioned_payload
            serialized = candidate_conditioned_payload(
                preceding_text, candidate)
            vector = self._query_vectors.get((serialized, candidate))
            if vector is None:
                vector = self._query_vectors.get(serialized)
        return vector if vector is not None else self._default_query

    def event_vector(self, event):
        return self.event_vector_for_candidate(
            event, event.final_selection_text)

    def event_vector_for_candidate(self, event, candidate):
        if candidate != event.final_selection_text:
            raise EvidenceError(
                "representation_fault",
                "event vector candidate does not match selection")
        key = _event_vector_key(event.schema_id,
                                event.canonical_segment_input,
                                candidate)
        vector = self._event_vectors.get(key)
        if vector is None:
            from representations import candidate_conditioned_payload
            history_key = (
                candidate_conditioned_payload(event.preceding_text, candidate),
                event.schema_id, event.canonical_segment_input, candidate)
            vector = self._event_vectors.get(history_key)
        return vector if vector is not None else self._default_event

    def vector_dimension(self):
        return len(self._default_query)


# ---------------------------------------------------------------------------
# The evidence service
# ---------------------------------------------------------------------------

def _hlc_tuple(physical, logical):
    return (physical, logical)


class EvidenceService:
    """Serve one evidence request from read-only facts via the oracle.

    ``facts_root`` is the semantic-memory fact root (never written here),
    ``params`` the oracle aggregation parameters, ``provider`` the injected
    deterministic representation seam and ``gamma`` the plugin-side evidence
    weight that participates in the config identity.

    ``machine`` (optional, #63) is the delta state machine whose published
    query snapshot gates every request: the request is served only from a
    snapshot that has caught up to the facts' current ``store_epoch`` +
    max change HLC, so a request never succeeds on a stale watermark.  When
    no machine is configured the service reads the facts directly (the
    offline/calibration path); when a machine is configured but the fact
    store is missing, the missing-store semantics below apply unchanged.
    """

    def __init__(self, facts_root, params, provider, gamma, machine=None,
                 retrieval_backend=BACKEND_ORACLE, trace_store=None):
        if not facts_root:
            raise EvidenceError("evidence_unavailable", "facts root missing")
        if not isinstance(params, OracleParams):
            raise EvidenceError("evidence_unavailable",
                                "params must be OracleParams")
        if not isinstance(provider, RepresentationProvider):
            raise EvidenceError("evidence_unavailable",
                                "provider must be a RepresentationProvider")
        if not isinstance(gamma, (int, float)) or not math.isfinite(gamma):
            raise EvidenceError("evidence_unavailable", "gamma must be finite")
        if retrieval_backend not in (BACKEND_ORACLE, BACKEND_ACCELERATE,
                                     BACKEND_MLX):
            raise EvidenceError(
                "evidence_unavailable",
                "unsupported retrieval_backend %r" % (retrieval_backend,))
        self._facts_root = facts_root
        self._params = params
        self._provider = provider
        self._gamma = gamma
        self._machine = machine
        self._retrieval_backend = retrieval_backend
        self._trace_store = trace_store
        self._config_identity = compose_config_identity(
            provider.representation_id(), params, gamma)

    def config_identity(self):
        """The identity the daemon currently serves.

        With a delta machine (#63/#65), the served identity follows the
        machine's published snapshot representation: a publish switch swaps
        the served representation exactly when the in-memory pointer swaps,
        so a request's config identity never mismatches what the snapshot
        would actually compute.  Without a machine it is the configured
        identity (the offline/calibration path).
        """
        if self._machine is not None:
            representation_id = self._machine.snapshot_representation_id()
            return compose_config_identity(representation_id, self._params,
                                           self._gamma)
        return self._config_identity

    def _db_path(self):
        return os.path.join(self._facts_root, "facts.sqlite3")

    def _cosine_engine(self, snapshot):
        """The CosineEngine for this request, per the configured backend.

        The oracle backend returns None (the canonical Python scalar path in
        ``compute_evidence``).  The Accelerate and MLX backends build their
        engine over the snapshot's matrix; any engine fault raises
        EvidenceError (fail closed -- never a silent Python fallback
        presented as the configured backend, SCN-72-5 / SCN-73-6).

        The configured backend must AGREE with the snapshot's generation
        backend: a generation built for ``accelerate-cblas-sgemv`` or
        ``mlx-exact-matmul`` must never be silently served with the oracle
        Python path (and vice versa), because the served backend is bound
        into ``index_fingerprint`` (SCN-72-4 / SCN-73-4).  A mismatch is a
        true fault, never a silent switch.
        """
        try:
            generation_backend = snapshot.retrieval_backend()
        except Exception:  # noqa: BLE001 - snapshot without a backend
            generation_backend = None
        if generation_backend != self._retrieval_backend:
            raise EvidenceError(
                "backend_mismatch",
                "configured retrieval backend %r does not match the "
                "served generation backend %r"
                % (self._retrieval_backend, generation_backend))
        if self._retrieval_backend == BACKEND_ACCELERATE:
            try:
                return snapshot.accelerate_engine()
            except EvidenceError:
                raise
            except Exception as error:  # noqa: BLE001 - fail closed
                raise EvidenceError(
                    "accelerate_fault",
                    "Accelerate backend unavailable: %s" % error) from error
        if self._retrieval_backend == BACKEND_MLX:
            try:
                return snapshot.mlx_engine()
            except EvidenceError:
                raise
            except Exception as error:  # noqa: BLE001 - fail closed
                raise EvidenceError(
                    "mlx_fault",
                    "MLX backend unavailable: %s" % error) from error
        return None

    @staticmethod
    def _oracle_query(source, request):
        """Build one-vector or per-candidate query semantics."""
        preceding_text = request["preceding_text"]
        candidates = list(request["candidates"])
        if source.is_candidate_conditioned():
            vectors = [source.query_vector_for_candidate(
                preceding_text, candidate) for candidate in candidates]
            if not vectors:
                raise EvidenceError("representation_fault",
                                    "candidate query has no vectors")
            return OracleQuery(
                schema_id=request["schema_id"],
                canonical_segment_input=request["canonical_segment_input"],
                candidates=candidates,
                query_vector=list(vectors[0]),
                category=request["category"],
                candidate_query_vectors=[list(vector) for vector in vectors],
            )
        return OracleQuery(
            schema_id=request["schema_id"],
            canonical_segment_input=request["canonical_segment_input"],
            candidates=candidates,
            query_vector=list(source.query_vector(preceding_text)),
            category=request["category"],
        )

    def _serve_via_snapshot(self, request):
        """Serve one request from the machine's caught-up query snapshot.

        The catch-up gate (AC63-1) re-reads the facts identity inside
        ``ensure_caught_up``; only a snapshot covering the facts' current
        watermark is returned, otherwise a true ``not_caught_up`` fault is
        raised -- never a stale-watermark success (AC63-6).  The query
        vector comes from the snapshot itself (#65): the snapshot binds its
        own representation at publish time, so a single query can never mix
        the old and the new representation/projection/index identity even
        while a publish switch is in flight (SCN-65-5).
        """
        candidates = request["candidates"]
        request_watermark = request["fact_high_water"]

        snapshot = self._machine.ensure_caught_up()
        self._check_watermark(request_watermark, snapshot.store_epoch,
                              snapshot.consumed[0], snapshot.consumed[1])

        try:
            query = self._oracle_query(snapshot, request)
        except EvidenceError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise EvidenceError(
                "representation_fault", "query vector failed: %s" % error
            ) from error
        reader = snapshot.reader()
        try:
            engine = self._cosine_engine(snapshot)
            result = compute_evidence(reader, self._params, query,
                                      snapshot.vector_for,
                                      cosine_engine=engine)
        except OracleError as error:
            raise EvidenceError("oracle_fault", str(error)) from error
        except EvidenceError:
            raise
        finally:
            reader.close()

        s_by_index = {
            candidate.index: candidate.s for candidate in result.candidates
        }
        evidence = [
            {"index": index, "s": s_by_index.get(index, 0.0)}
            for index in range(len(candidates))
        ]
        zero_evidence = all(abs(entry["s"]) == 0.0 for entry in evidence)
        return {
            "status": "ok",
            "zero_evidence": zero_evidence,
            "evidence": evidence,
            "query_point": {
                "hlc_physical_ms": result.query_point[0],
                "hlc_logical": result.query_point[1],
            },
            "_oracle_result": result,
        }

    def _read_identity(self, reader):
        """store_epoch + max change HLC from the meta table (read-only).

        Mirrors FactHandle.read_identity; a store without a provable identity
        is a fault, never a zero-evidence result.
        """
        try:
            return reader.read_fact_identity()
        except OracleError as error:
            raise EvidenceError("fact_store_fault", str(error)) from error

    def _check_watermark(self, request_watermark, store_epoch, physical,
                         logical):
        """Catch-up gate (AC61-2 / spec "追平失败则属真故障").

        The daemon must prove its own snapshot is at or beyond the plugin's
        declared fact high-water before serving; an epoch mismatch or a
        snapshot behind the watermark is a true fault, never a stale success.
        A request without a watermark (plugin could not read the store) skips
        the gate.
        """
        if request_watermark is None:
            return
        if not isinstance(request_watermark, dict):
            raise EvidenceError("invalid_request",
                                "fact_high_water must be an object")
        expected = request_watermark.get("store_epoch")
        physical_want = request_watermark.get("hlc_physical_ms")
        logical_want = request_watermark.get("hlc_logical")
        if (not isinstance(expected, str) or not expected
                or not isinstance(physical_want, int) or physical_want < 0
                or not isinstance(logical_want, int) or logical_want < 0):
            raise EvidenceError("invalid_request",
                                "fact_high_water is malformed")
        if expected != store_epoch:
            raise EvidenceError("fact_identity_mismatch",
                                "fact store epoch does not match the request")
        if (physical, logical) < (physical_want, logical_want):
            raise EvidenceError("not_caught_up",
                                "daemon fact snapshot is behind the request "
                                "watermark")
        return True

    def serve(self, request):
        """Compute candidate-level evidence for one group request.

        ``request`` is the already field-validated evidence request dict.
        Returns the success response dict (including ``zero_evidence``);
        raises EvidenceError for every true fault.  When a trace store is
        configured, order changes and faults are recorded identity-only and
        unchanged successes aggregate only, as side effects.
        """
        started = time.monotonic()
        trial = request.get("trial")
        try:
            if self._machine is not None and os.path.isfile(self._db_path()):
                response = self._serve_via_snapshot(request)
            else:
                response = self._serve_direct(request)
        except EvidenceError as error:
            self._record_fault(request, error, started)
            raise
        except Exception:  # noqa: BLE001 - any fault fails closed
            self._record_fault(request, None, started)
            raise
        # The private oracle-result envelope feeds tracing only; it never
        # reaches callers or the wire.
        result = response.pop("_oracle_result", None)
        if self._trace_store is not None:
            self._attach_trace(request, response, result, trial, started)
        return response

    def _record_fault(self, request, error, started):
        """Persist a stable fault trace (SCN-74-2) without raw text."""
        store = self._trace_store
        if store is None:
            return
        try:
            code = error.code if isinstance(error, EvidenceError) \
                else "oracle_fault"
            store.record_request(
                self._request_meta(request),
                code,
                trace_payload={
                    "kind": "fault",
                    "error_code": code,
                    "passthrough": True,  # AC61-2: every fault passes through
                    "config_identity": self.config_identity(),
                    "retrieval_backend": self._retrieval_backend,
                    "fact_high_water": request.get("fact_high_water"),
                    "derived_watermark": self._derived_watermark(),
                },
                latency_segments=self._segments(request, started, None),
            )
        except Exception:  # noqa: BLE001 - tracing is advisory, never fatal
            pass

    def _attach_trace(self, request, response, result, trial, started):
        """Write the identity-only order-change trace or aggregates.

        The shadow emit order is the group replayed with γ=0 (base scores
        only, stable sort descending -- exactly the plugin's
        ``ReplayRerankPlan`` with zero retrieval evidence); the final order
        adds ``gamma * s_c``.  Any permutation difference is an order
        change (SCN-74-1); unchanged successes aggregate only (SCN-74-3).
        """
        store = self._trace_store
        if store is None:
            return
        try:
            outcome = "ok"
            shadow, final = self._emit_orders(request, result, trial)
            if shadow is None or final == shadow:
                store.record_request(
                    self._request_meta(request), outcome,
                    latency_segments=self._segments(request, started, result))
                return
            payload = self._trace_payload(request, result, trial, shadow,
                                          final)
            store.record_request(
                self._request_meta(request), outcome,
                trace_payload=payload,
                latency_segments=self._segments(request, started, result))
        except Exception:  # noqa: BLE001 - tracing is advisory
            pass

    def _emit_orders(self, request, result, trial):
        """(shadow_order, final_order) as candidate-index permutations.

        Stable sort by comparison score descending, matching the plugin's
        group replay semantics: ties keep the original (merge) order.  The
        request's candidate list is the group in merge order.
        """
        if not trial or not isinstance(trial.get("base_scores"), list):
            return None, None
        base_scores = trial["base_scores"]
        if len(base_scores) != len(request.get("candidates") or []):
            return None, None
        if result is None:
            return None, None
        s_by_index = {
            candidate.index: candidate.s for candidate in result.candidates
        }
        gamma = self._gamma
        indexes = list(range(len(base_scores)))
        shadow = sorted(indexes,
                        key=lambda i: base_scores[i], reverse=True)
        final = sorted(
            indexes,
            key=lambda i: base_scores[i] + gamma * s_by_index.get(i, 0.0),
            reverse=True)
        # Python's sorted is stable: equal comparison scores keep merge
        # order, exactly like std::stable_sort in ReplayRerankPlan.
        return tuple(shadow), tuple(final)

    def _request_meta(self, request):
        return {
            "schema_id": request.get("schema_id"),
            "category": request.get("category"),
            "canonical_segment_input": request.get(
                "canonical_segment_input"),
            "request_id": request.get("request_id"),
            "plan_identity": request.get("plan_identity"),
            "config_identity": request.get("config_identity"),
            "fact_high_water": request.get("fact_high_water"),
            "actionable": bool((request.get("trial") or {}).get(
                "actionable")),
            "candidate_count": len(request.get("candidates") or []),
        }

    def _segments(self, request, started, result):
        """Segmented latency in ms (full_request + oracle stage timings)."""
        segments = {"full_request_ms": (time.monotonic() - started) * 1000.0}
        if result is not None and hasattr(result, "latency_ms"):
            for key, value in result.latency_ms.items():
                segments[key] = value
        return segments

    @staticmethod
    def _ranks(order):
        rank = {index: position for position, index in enumerate(order)}
        return [rank.get(i, len(order)) for i in range(len(order))]

    def _derived_watermark(self):
        """The served generation identity (base generation + representation).

        Privacy-clean: identity strings only, from the delta machine's
        published snapshot when one exists (spec: trace carries the
        generation fingerprint); None on the offline/calibration path.
        """
        machine = self._machine
        if machine is None:
            return None
        try:
            snapshot = machine.snapshot()
        except Exception:  # noqa: BLE001 - advisory; never fatal
            return None
        if snapshot is None:
            return None
        watermark = {"representation_id": None, "generation_id": None}
        try:
            watermark["representation_id"] = snapshot.representation_id()
        except Exception:  # noqa: BLE001
            pass
        try:
            watermark["generation_id"] = snapshot.base_generation_id()
        except Exception:  # noqa: BLE001
            pass
        return watermark

    def _trace_payload(self, request, result, trial, shadow, final):
        """Assemble the identity-only full trace (AC74-1 fields)."""
        payload = {
            "kind": "order_change",
            "schema_id": request.get("schema_id"),
            "category": request.get("category"),
            "canonical_segment_input": request.get(
                "canonical_segment_input"),
            "plan_identity": request.get("plan_identity"),
            "config_identity": self.config_identity(),
            "retrieval_backend": self._retrieval_backend,
            "fact_high_water": request.get("fact_high_water"),
            "request_id": request.get("request_id"),
            "base_scores": list(trial.get("base_scores") or []),
            "shadow_order": list(shadow),
            "final_order": list(final),
            "base_ranks": self._ranks(shadow),
            "final_ranks": self._ranks(final),
            "candidate_count": len(request.get("candidates") or []),
            "facts_watermark": None,
            "derived_watermark": self._derived_watermark(),
            "neighbors": [],
            "aggregate_s_c": None,
        }
        if result is not None:
            payload["facts_watermark"] = {
                "store_epoch": getattr(result, "store_epoch", None),
                "hlc_physical_ms": result.query_point[0],
                "hlc_logical": result.query_point[1],
            }
            payload["neighbors"] = [
                {
                    "event_id": contribution.event_id,
                    "commit_id": contribution.commit_id,
                    "cosine": contribution.cosine,
                    "r_i": contribution.relevance,
                    "d_i": contribution.age_factor,
                    "a_i": contribution.weight,
                    "usage_age": contribution.usage_age,
                    "matched_candidate": contribution.matched_candidate,
                }
                for contribution in result.kept
            ]
            payload["aggregate_s_c"] = [
                {"index": candidate.index, "s": candidate.s}
                for candidate in result.candidates
            ]
        return payload

    def _serve_direct(self, request):
        """The direct (non-snapshot) serve path, returning the response with
        the private ``_oracle_result`` envelope."""
        candidates = request["candidates"]
        request_watermark = request["fact_high_water"]

        if not os.path.isfile(self._db_path()):
            # A missing store means an empty event library: success zero
            # evidence, but only when the plugin also declares no watermark
            # (a declared watermark against a missing store is a fault).
            if request_watermark is not None:
                raise EvidenceError("fact_store_fault",
                                    "fact store is missing")
            return {
                "status": "ok",
                "zero_evidence": True,
                "evidence": [
                    {"index": index, "s": 0.0}
                    for index in range(len(candidates))
                ],
                "query_point": None,
            }

        reader = None
        try:
            reader = FactReader(self._db_path())
            store_epoch, physical, logical = self._read_identity(reader)
            self._check_watermark(request_watermark, store_epoch, physical,
                                  logical)
        except OracleError as error:
            raise EvidenceError("fact_store_fault", str(error)) from error
        except sqlite3.Error as error:
            raise EvidenceError("fact_store_fault", str(error)) from error

        try:
            query = self._oracle_query(self._provider, request)
        except EvidenceError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise EvidenceError(
                "representation_fault", "query vector failed: %s" % error
            ) from error

        # The oracle's vector_for is keyed by event id; resolve it through
        # the provider with the full event record (missing -> fault).
        try:
            events_by_id = {}
            as_of = reader.default_as_of()
            for event in reader.read_active_events(as_of):
                events_by_id[event.event_id] = event

            def vector_for(event_id):
                event = events_by_id.get(event_id)
                if event is None:
                    raise OracleError(
                        "no stored event for vector lookup %s" % event_id)
                try:
                    return self._provider.event_vector(event)
                except EvidenceError as error:
                    raise OracleError(
                        "event vector failed for %s: %s"
                        % (event_id, error.message)) from error
                except Exception as error:  # noqa: BLE001 - fail closed
                    raise OracleError(
                        "event vector failed for %s: %s"
                        % (event_id, error)) from error

            started = time.monotonic()
            result = compute_evidence(reader, self._params, query,
                                      vector_for)
            # The oracle already filled result.latency_ms with its stage
            # timings (#74 segmented latency); the wall-clock oracle_ms here
            # would clobber them, so it stays local.
            oracle_ms = (time.monotonic() - started) * 1000.0
            object.__setattr__(result, "latency_ms", dict(
                result.latency_ms, oracle_ms=oracle_ms))
        except OracleError as error:
            raise EvidenceError("oracle_fault", str(error)) from error
        finally:
            reader.close()

        s_by_index = {
            candidate.index: candidate.s for candidate in result.candidates
        }
        evidence = [
            {"index": index, "s": s_by_index.get(index, 0.0)}
            for index in range(len(candidates))
        ]
        zero_evidence = all(abs(entry["s"]) == 0.0 for entry in evidence)
        return {
            "status": "ok",
            "zero_evidence": zero_evidence,
            "evidence": evidence,
            "query_point": {
                "hlc_physical_ms": result.query_point[0],
                "hlc_logical": result.query_point[1],
            },
            "_oracle_result": result,
        }


def make_evidence_request(schema_id, category, canonical_segment_input,
                          preceding_text, candidates, config_identity,
                          fact_high_water, request_id="evidence-1",
                          plan_identity="rerank-plan-v2:test",
                          version=EVIDENCE_PROTOCOL_VERSION):
    """Build one evidence request dict (mirrors the C++ plugin's builder)."""
    return {
        "version": version,
        "kind": EVIDENCE_KIND,
        "request_id": request_id,
        "plan_identity": plan_identity,
        "schema_id": schema_id,
        "category": category,
        "canonical_segment_input": canonical_segment_input,
        "preceding_text": preceding_text,
        "candidates": list(candidates),
        "config_identity": config_identity,
        "fact_high_water": fact_high_water,
    }


def build_evidence_service_from_config(facts_root, config, machine=None,
                                       trace_store=None):
    """Construct an EvidenceService from a JSON config dict.

    The config binds the oracle params, the plugin-side gamma and the
    injected deterministic representation seam:

        representation_id, tau, k_evidence, half_life, saturation_k, gamma,
        query_vectors (exact preceding text -> vector),
        event_vectors (schema_id|canonical_segment_input|final_selection -> vector),
        default_query, default_event,
        retrieval_backend ("exact", "accelerate-cblas-sgemv" or
        "mlx-exact-matmul"; default "exact" -- the #71 oracle path)

    ``machine`` (#63) is an optional prebuilt delta state machine; when
    present, every served request is gated through its published query
    snapshot instead of the live facts.  This is the #61 seam: e2e and
    daemon tests inject a deterministic fixture; #62 plugs the real
    hidden-state provider behind the same config shape (query/event vectors
    produced by the generation instead).

    ``trace_store`` (#74) is the optional app-controlled trial trace store
    (daemon/tracing.py); when present, order changes and true faults are
    recorded identity-only, unchanged successes aggregate only.
    """
    try:
        representation_id = config["representation_id"]
        tau = float(config.get("tau", DEFAULT_TAU))
        k_evidence = int(config.get("k_evidence", DEFAULT_K_EVIDENCE))
        half_life = float(config.get("half_life", DEFAULT_HALF_LIFE))
        saturation_k = float(
            config.get("saturation_k", DEFAULT_SATURATION_K))
        gamma = float(config["gamma"])
        retrieval_backend = config.get("retrieval_backend", BACKEND_ORACLE)
        query_vectors = config.get("query_vectors") or {}
        event_vectors = config.get("event_vectors") or {}
        default_query = config.get("default_query")
        default_event = config.get("default_event")
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("evidence_unavailable",
                            "malformed evidence config: %s" % error)
    params = OracleParams(tau=tau, k_evidence=k_evidence,
                          half_life=half_life, saturation_k=saturation_k)
    provider = _provider_from_config(config, representation_id)
    return EvidenceService(facts_root, params, provider, gamma,
                           machine=machine,
                           retrieval_backend=retrieval_backend,
                           trace_store=trace_store)


def _provider_from_config(config, representation_id):
    """Construct the representation provider behind the config seam.

    Two provider kinds are supported:

    - ``provider_kind: "fixture"`` (default): the existing
      FixtureRepresentationProvider with explicit query/event vector maps
      (tests and small e2e fixtures).
    - ``provider_kind: "candidate_fixture"``: candidate-conditioned maps
      keyed by ``(preceding_text, candidate)`` plus the existing event key.
    - ``provider_kind: "seed_vectors"``: the #71 capacity-fixture provider,
      deterministic fixed-seed vectors for the 100k-event fixtures (see
      seed_vectors.py).  The seed and dimension come from the config.
    """
    kind = config.get("provider_kind", "fixture")
    if kind == "seed_vectors":
        from seed_vectors import build_seed_provider_from_config
        return build_seed_provider_from_config(config)
    if kind == "candidate_fixture":
        return CandidateFixtureRepresentationProvider(
            representation_id,
            config.get("candidate_query_vectors") or {},
            config.get("candidate_event_vectors") or {},
            default_query=config.get("default_query") or
            (1.0, 0.0, 0.0, 0.0),
            default_event=config.get("default_event") or
            (0.0, 1.0, 0.0, 0.0),
        )
    if kind != "fixture":
        raise EvidenceError(
            "evidence_unavailable",
            "unknown provider_kind %r (expected fixture, candidate_fixture "
            "or seed_vectors)"
            % kind)
    query_vectors = config.get("query_vectors") or {}
    event_vectors = config.get("event_vectors") or {}
    default_query = config.get("default_query")
    default_event = config.get("default_event")
    return FixtureRepresentationProvider(
        representation_id,
        query_vectors,
        event_vectors,
        default_query=(default_query if default_query is not None
                       else (1.0, 0.0, 0.0, 0.0)),
        default_event=(default_event if default_event is not None
                       else (0.0, 1.0, 0.0, 0.0)),
    )
