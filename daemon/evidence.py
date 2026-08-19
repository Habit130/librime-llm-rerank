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

import math
import os
import sqlite3
from dataclasses import dataclass
from typing import (Dict, List, Mapping, Optional, Sequence, Tuple)

from oracle import (FactReader, OracleError, OracleParams, OracleQuery,
                    compute_evidence)

# #72: the exact retrieval backend the daemon serves evidence with.  Both
# backends compute the same exact evidence over the same facts/vectors; the
# Accelerate backend uses Apple vecLib for the per-event cosine while the
# oracle backend uses Python scalar math.  The configured backend is bound
# into the index fingerprint (see compat.compose_backend_fingerprint); the
# config seam never silently switches backends.
BACKEND_ORACLE = "exact"
BACKEND_ACCELERATE = "accelerate-cblas-sgemv"

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


def format_identity_double(value):
    """Canonical double formatting shared with the C++ plugin.

    Both sides must produce byte-identical config identities, so the format
    is fixed: ``%g``-style with six significant digits, ``inf`` for infinity
    (the C++ side uses defaultfloat + setprecision(6)).
    """
    if math.isinf(value):
        return "inf"
    if not math.isfinite(value):
        raise EvidenceError("config_identity", "non-finite config value")
    return format(value, ".6g")


def compose_config_identity(representation_id, params, gamma):
    """Canonical evidence config identity (AC61-1 "配置身份").

    Covers the representation seam id and every oracle/gamma parameter that
    changes the served evidence semantics; a change in any component yields a
    different identity, and the daemon serves exactly the identity it was
    configured with.
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

    JSON configs use the flat "schema|canonical_input|selection" form; the
    internal lookup uses the tuple form so text containing '|' can never
    collide.
    """
    result = {}
    for key, vector in mapping.items():
        if isinstance(key, tuple):
            result[key] = vector
            continue
        if not isinstance(key, str):
            raise EvidenceError("representation_fault",
                                "event vector key must be a string or tuple")
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
                 retrieval_backend=BACKEND_ORACLE):
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
        if retrieval_backend not in (BACKEND_ORACLE, BACKEND_ACCELERATE):
            raise EvidenceError(
                "evidence_unavailable",
                "unsupported retrieval_backend %r" % (retrieval_backend,))
        self._facts_root = facts_root
        self._params = params
        self._provider = provider
        self._gamma = gamma
        self._machine = machine
        self._retrieval_backend = retrieval_backend
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
        ``compute_evidence``).  The Accelerate backend builds the vecLib
        engine over the snapshot's matrix; any Accelerate fault raises
        EvidenceError (fail closed -- never a silent Python fallback
        presented as Accelerate, SCN-72-5).

        The configured backend must AGREE with the snapshot's generation
        backend: a generation built for ``accelerate-cblas-sgemv`` must never
        be silently served with the oracle Python path (and vice versa),
        because the served backend is bound into ``index_fingerprint``
        (SCN-72-4).  A mismatch is a true fault, never a silent switch.
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
        return None

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
        schema_id = request["schema_id"]
        category = request["category"]
        canonical_input = request["canonical_segment_input"]
        preceding_text = request["preceding_text"]
        candidates = request["candidates"]
        request_watermark = request["fact_high_water"]

        snapshot = self._machine.ensure_caught_up()
        self._check_watermark(request_watermark, snapshot.store_epoch,
                              snapshot.consumed[0], snapshot.consumed[1])

        try:
            query_vector = snapshot.query_vector(preceding_text)
        except EvidenceError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise EvidenceError(
                "representation_fault", "query vector failed: %s" % error
            ) from error

        query = OracleQuery(
            schema_id=schema_id,
            canonical_segment_input=canonical_input,
            candidates=list(candidates),
            query_vector=list(query_vector),
            category=category,
        )
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
        raises EvidenceError for every true fault.
        """
        if self._machine is not None and os.path.isfile(self._db_path()):
            return self._serve_via_snapshot(request)
        schema_id = request["schema_id"]
        category = request["category"]
        canonical_input = request["canonical_segment_input"]
        preceding_text = request["preceding_text"]
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
            query_vector = self._provider.query_vector(preceding_text)
        except EvidenceError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise EvidenceError(
                "representation_fault", "query vector failed: %s" % error
            ) from error

        query = OracleQuery(
            schema_id=schema_id,
            canonical_segment_input=canonical_input,
            candidates=list(candidates),
            query_vector=list(query_vector),
            category=category,
        )

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

            result = compute_evidence(reader, self._params, query,
                                      vector_for)
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


def build_evidence_service_from_config(facts_root, config, machine=None):
    """Construct an EvidenceService from a JSON config dict.

    The config binds the oracle params, the plugin-side gamma and the
    injected deterministic representation seam:

        representation_id, tau, k_evidence, half_life, saturation_k, gamma,
        query_vectors (exact preceding text -> vector),
        event_vectors (schema_id|canonical_segment_input|final_selection -> vector),
        default_query, default_event,
        retrieval_backend ("exact" or "accelerate-cblas-sgemv"; default
        "exact" -- the #71 oracle path)

    ``machine`` (#63) is an optional prebuilt delta state machine; when
    present, every served request is gated through its published query
    snapshot instead of the live facts.  This is the #61 seam: e2e and
    daemon tests inject a deterministic fixture; #62 plugs the real
    hidden-state provider behind the same config shape (query/event vectors
    produced by the generation instead).
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
                           retrieval_backend=retrieval_backend)


def _provider_from_config(config, representation_id):
    """Construct the representation provider behind the config seam.

    Two provider kinds are supported:

    - ``provider_kind: "fixture"`` (default): the existing
      FixtureRepresentationProvider with explicit query/event vector maps
      (tests and small e2e fixtures).
    - ``provider_kind: "seed_vectors"``: the #71 capacity-fixture provider,
      deterministic fixed-seed vectors for the 100k-event fixtures (see
      seed_vectors.py).  The seed and dimension come from the config.
    """
    kind = config.get("provider_kind", "fixture")
    if kind == "seed_vectors":
        from seed_vectors import build_seed_provider_from_config
        return build_seed_provider_from_config(config)
    if kind != "fixture":
        raise EvidenceError(
            "evidence_unavailable",
            "unknown provider_kind %r (expected fixture or seed_vectors)"
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
