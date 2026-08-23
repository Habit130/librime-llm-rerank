#!/usr/bin/env python3
"""The AC-111 candidate-conditioned global linear projection seam.

The projection is deliberately small and boring: one global matrix maps the
concatenation of the three AC-109 span-mean vectors to 256 dimensions.  This
module owns loading, identity validation, L2-normalized application, and the
model-free provider adapter.  Training lives in ``eval/train_linear_projection.py``.

Projection files are local artifacts.  A committed identity contains hashes
and declared configuration only; it never contains the matrix itself.
"""

import hashlib
import json
import math
import os

try:
    import numpy as np
except ImportError:  # pragma: no cover - the real adapter needs numpy
    np = None

from evidence import EvidenceError, RepresentationProvider


PROJECTION_ID_VERSION = "candidate-conditioned-linear-v1"
INPUT_DIMENSION = 3072
OUTPUT_DIMENSION = 256
VECTOR_FORMAT = "fp32-l2"
METRIC = "cosine"

REQUIRED_METADATA_FIELDS = (
    "source_representation_ids",
    "training_code_digest",
    "snapshot_sha256",
    "history_id",
    "store_epoch",
    "hlc_cutoff",
    "hyperparameters",
    "seed",
    "split",
    "sampling",
    "loss",
    "regularization",
    "stop",
    "weight_digest",
    "input_dim",
    "output_dim",
    "vector_format",
    "metric",
)


class ProjectionError(Exception):
    """A projection identity, shape, or numerical fault."""


def _require_numpy():
    if np is None:
        raise ProjectionError("numpy is required for the linear projection")
    return np


def canonical_json(value):
    """Return the canonical JSON form used by projection fingerprints."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _json_value(value):
    """Convert tuple-like metadata to JSON values without accepting arrays."""
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ProjectionError("projection metadata contains unsupported value")


def _metadata_without_fingerprint(metadata):
    value = dict(metadata)
    value.pop("fingerprint", None)
    return _json_value(value)


def projection_fingerprint(metadata):
    """Hash every declared projection identity field, including weight hash."""
    missing = [field for field in REQUIRED_METADATA_FIELDS
               if field not in metadata]
    if missing:
        raise ProjectionError(
            "projection metadata missing fields: %s" % ", ".join(missing))
    payload = canonical_json(_metadata_without_fingerprint(metadata)).encode(
        "utf-8")
    return "%s:%s" % (PROJECTION_ID_VERSION,
                       hashlib.sha256(payload).hexdigest())


def _weight_digest(weights):
    array = _require_numpy().asarray(weights, dtype="<f4", order="C")
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _l2_normalize(values):
    array = _require_numpy().asarray(values, dtype="<f4").reshape(-1)
    if array.size != OUTPUT_DIMENSION:
        raise ProjectionError("projection output dimension mismatch")
    if not bool(_require_numpy().isfinite(array).all()):
        raise ProjectionError("projection output contains non-finite values")
    norm = math.sqrt(float(_require_numpy().dot(
        array.astype("<f8"), array.astype("<f8"))))
    if not math.isfinite(norm) or norm == 0.0:
        raise ProjectionError("projection output has zero norm")
    normalized = (array.astype("<f8") / norm).astype("<f4")
    if not bool(_require_numpy().isfinite(normalized).all()):
        raise ProjectionError("normalized projection is non-finite")
    return tuple(float(value) for value in normalized)


class LinearProjection:
    """One validated FP32 global matrix and its frozen identity."""

    def __init__(self, weights, metadata):
        array = _require_numpy().asarray(weights, dtype="<f4", order="C")
        if array.shape != (OUTPUT_DIMENSION, INPUT_DIMENSION):
            raise ProjectionError(
                "expected one matrix with shape (%d, %d), got %r" % (
                    OUTPUT_DIMENSION, INPUT_DIMENSION, array.shape))
        if not bool(_require_numpy().isfinite(array).all()):
            raise ProjectionError("projection weights contain non-finite values")
        if not isinstance(metadata, dict):
            raise ProjectionError("projection metadata must be a dict")
        metadata = dict(metadata)
        if metadata.get("input_dim") != INPUT_DIMENSION or \
                metadata.get("output_dim") != OUTPUT_DIMENSION:
            raise ProjectionError("projection dimensions are not frozen")
        if metadata.get("vector_format") != VECTOR_FORMAT or \
                metadata.get("metric") != METRIC:
            raise ProjectionError("projection vector format is not frozen")
        digest = _weight_digest(array)
        if metadata.get("weight_digest") != digest:
            raise ProjectionError("projection weight digest mismatch")
        fingerprint = projection_fingerprint(metadata)
        declared = metadata.get("fingerprint")
        if declared is not None and declared != fingerprint:
            raise ProjectionError("projection fingerprint mismatch")
        metadata["fingerprint"] = fingerprint
        self._weights = array.copy()
        self._metadata = metadata

    @property
    def metadata(self):
        return dict(self._metadata)

    @property
    def fingerprint(self):
        return self._metadata["fingerprint"]

    @property
    def weight_digest(self):
        return self._metadata["weight_digest"]

    @property
    def weights(self):
        """Return a copy for local training/tests; callers cannot mutate state."""
        return self._weights.copy()

    def apply(self, vector):
        """Map one 3072-d vector to a finite FP32 L2-normalized 256-d vector."""
        values = _require_numpy().asarray(vector, dtype="<f4").reshape(-1)
        if values.size != INPUT_DIMENSION:
            raise ProjectionError(
                "projection input must have dimension %d" % INPUT_DIMENSION)
        if not bool(_require_numpy().isfinite(values).all()):
            raise ProjectionError("projection input contains non-finite values")
        result = self._weights.dot(values)
        return _l2_normalize(result)

    def save(self, path):
        """Write a local NPZ artifact containing weights and identity metadata."""
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        _require_numpy().savez(
            path,
            weights=self._weights,
            metadata_json=_require_numpy().array(
                canonical_json(self._metadata)),
        )

    @classmethod
    def load(cls, path):
        """Load and verify one local projection artifact."""
        if not os.path.isfile(path):
            raise ProjectionError("projection file not found: %s" % path)
        try:
            with _require_numpy().load(path, allow_pickle=False) as archive:
                if "weights" not in archive or "metadata_json" not in archive:
                    raise ProjectionError("projection artifact is incomplete")
                weights = archive["weights"]
                raw_metadata = archive["metadata_json"]
                if getattr(raw_metadata, "shape", ()) != ():
                    raise ProjectionError("projection metadata is not scalar")
                metadata = json.loads(str(raw_metadata.item()))
        except ProjectionError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ProjectionError("projection artifact is invalid: %s" % error)
        return cls(weights, metadata)


class ProjectedCandidateRepresentationProvider(RepresentationProvider):
    """Apply one trained projection after the three AC-109 source routes."""

    @classmethod
    def from_extractor(cls, extractor, projection):
        """Build the real AC-109 source chain without changing live config."""
        from hidden_state import HiddenStateCandidateRepresentationProvider
        from representations import candidate_conditioned_specs

        specs = tuple(spec for spec in candidate_conditioned_specs()
                      if spec.pooling == "candidate_span_mean")
        if tuple(spec.layer for spec in specs) != (14, 21, 28):
            raise ProjectionError("AC-109 span-mean source set changed")
        providers = tuple(
            HiddenStateCandidateRepresentationProvider(extractor, spec)
            for spec in specs)
        return cls(providers, projection)

    def __init__(self, source_providers, projection):
        if not isinstance(projection, LinearProjection):
            raise ProjectionError("projection must be a LinearProjection")
        providers = tuple(source_providers)
        if len(providers) != 3:
            raise ProjectionError("projection requires exactly three sources")
        dimensions = []
        for provider in providers:
            if not isinstance(provider, RepresentationProvider):
                raise ProjectionError("source is not a representation provider")
            if not provider.is_candidate_conditioned():
                raise ProjectionError("projection source must be candidate-conditioned")
            dimensions.append(provider.vector_dimension())
        if tuple(dimensions) != (1024, 1024, 1024):
            raise ProjectionError(
                "AC-109 source dimensions must be (1024, 1024, 1024), got %r"
                % (tuple(dimensions),))
        expected = tuple(projection.metadata["source_representation_ids"])
        actual = tuple(provider.representation_id() for provider in providers)
        if expected != actual:
            raise ProjectionError("projection source representation mismatch")
        self._providers = providers
        self._projection = projection

    def representation_id(self):
        return self._projection.fingerprint

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        del preceding_text
        raise EvidenceError(
            "representation_fault",
            "projected candidate-conditioned query requires a candidate")

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._apply(
            provider.query_vector_for_candidate(preceding_text, candidate)
            for provider in self._providers)

    def event_vector(self, event):
        return self.event_vector_for_candidate(event, event.final_selection_text)

    def event_vector_for_candidate(self, event, candidate):
        return self._apply(
            provider.event_vector_for_candidate(event, candidate)
            for provider in self._providers)

    def vector_dimension(self):
        return OUTPUT_DIMENSION

    def _apply(self, vectors):
        concatenated = []
        for vector in vectors:
            values = tuple(float(value) for value in vector)
            if len(values) != 1024:
                raise EvidenceError(
                    "representation_fault",
                    "AC-109 source vector dimension mismatch")
            concatenated.extend(values)
        try:
            return self._projection.apply(concatenated)
        except ProjectionError as error:
            raise EvidenceError("representation_fault", str(error)) from error


def projection_metadata_with_fingerprint(metadata):
    """Return a validated metadata copy with its deterministic fingerprint."""
    value = dict(metadata)
    value["fingerprint"] = projection_fingerprint(value)
    return value
