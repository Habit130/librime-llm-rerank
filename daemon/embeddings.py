#!/usr/bin/env python3
"""Dedicated candidate-conditioned embedding adapters (Squirrel #110).

The module keeps the model-free representation contract separate from the
optional transformers runtime.  Qwen3-Embedding and BGE-M3 are deliberately
two adapter identities, even though they share one dense hidden-state runner:
the model, tokenizer, adapter/instruction, output format and dependency
versions are all part of the representation identity.

No model-loading package is imported at module import time.  This makes the
daemon and eval fixture gates usable without a model or the embedding venv.
"""

import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass
from importlib import metadata

from evidence import (CandidateFixtureRepresentationProvider,
                      EvidenceError, RepresentationProvider)
from representations import (CANDIDATE_PAYLOAD_SCHEMA,
                              CANDIDATE_SERIALIZATION,
                              WINDOW_CHARS, candidate_conditioned_payload,
                              l2_normalize)


EMBEDDING_REPRESENTATION_ID_VERSION = "dedicated-embedding-repr-v1"
EMBEDDING_OUTPUT_DIMENSION = 1024
EMBEDDING_VECTOR_FORMAT = "fp32-l2"
EMBEDDING_METRIC = "cosine"
QWEN3_QUERY_INSTRUCTION = (
    "Represent the candidate-conditioned query for semantic retrieval."
)


class EmbeddingError(Exception):
    """Base fault for loading, identity or inference."""


class EmbeddingLoadError(EmbeddingError):
    """A model or tokenizer could not be loaded."""


class EmbeddingIdentityError(EmbeddingError):
    """The model identity is missing, changed or incompatible."""


class EmbeddingInferenceError(EmbeddingError):
    """A forward pass did not produce a valid embedding."""


class ModelProcessConflictError(EmbeddingLoadError):
    """A second heavyweight model was requested in this process."""


@dataclass(frozen=True)
class EmbeddingRoute:
    """Frozen adapter semantics for one dedicated embedding route."""

    route_id: str
    adapter: str
    instruction: str
    pooling: str
    model_name: str

    def __post_init__(self):
        expected = {
            "qwen3-embedding-0.6b": (
                "qwen3", QWEN3_QUERY_INSTRUCTION, "last-token",
                "Qwen3-Embedding-0.6B"),
            "bge-m3-dense-1024": (
                "bge-m3", "none", "dense-mean", "BGE-M3"),
        }.get(self.route_id)
        if expected is None or (
                self.adapter, self.instruction, self.pooling, self.model_name
        ) != expected:
            raise EmbeddingIdentityError("embedding route semantics are not frozen")


QWEN3_EMBEDDING_ROUTE = EmbeddingRoute(
    route_id="qwen3-embedding-0.6b",
    adapter="qwen3",
    instruction=QWEN3_QUERY_INSTRUCTION,
    pooling="last-token",
    model_name="Qwen3-Embedding-0.6B",
)
BGE_M3_EMBEDDING_ROUTE = EmbeddingRoute(
    route_id="bge-m3-dense-1024",
    adapter="bge-m3",
    instruction="none",
    pooling="dense-mean",
    model_name="BGE-M3",
)


def embedding_routes():
    """Return exactly the two frozen dedicated routes."""
    return (QWEN3_EMBEDDING_ROUTE, BGE_M3_EMBEDDING_ROUTE)


@dataclass(frozen=True)
class EmbeddingIdentity:
    """All identity inputs that can change a dedicated vector."""

    route_id: str
    model_digest: str
    tokenizer_digest: str
    adapter: str
    instruction: str
    output_dimension: int
    vector_format: str
    metric: str
    dependency_versions: tuple

    def __post_init__(self):
        if not self.route_id or not self.model_digest:
            raise EmbeddingIdentityError("route and model digest are required")
        if not self.tokenizer_digest:
            raise EmbeddingIdentityError("tokenizer digest is required")
        if self.output_dimension != EMBEDDING_OUTPUT_DIMENSION:
            raise EmbeddingIdentityError("embedding output dimension must be 1024")
        if self.vector_format != EMBEDDING_VECTOR_FORMAT:
            raise EmbeddingIdentityError("unsupported embedding vector format")
        if self.metric != EMBEDDING_METRIC:
            raise EmbeddingIdentityError("unsupported embedding metric")
        if not isinstance(self.dependency_versions, tuple):
            raise EmbeddingIdentityError("dependency versions must be a tuple")
        for item in self.dependency_versions:
            if (not isinstance(item, tuple) or len(item) != 2
                    or not all(isinstance(value, str) and value for value in item)):
                raise EmbeddingIdentityError("dependency versions are malformed")


def _file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_files(directory, predicate):
    if not os.path.isdir(directory):
        raise EmbeddingIdentityError("model directory is missing")
    paths = []
    for root, _dirs, names in os.walk(directory):
        for name in names:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, directory)
            if os.path.isfile(path) and predicate(relative):
                paths.append(relative)
    digest = hashlib.sha256()
    digest.update(b"embedding-identity-file-set-v1\n")
    for relative in sorted(paths):
        path = os.path.join(directory, relative)
        digest.update(("%s:%d:%s\0" % (
            relative, os.path.getsize(path), _file_digest(path))).encode("utf-8"))
    return digest.hexdigest()


def _model_file(relative):
    basename = os.path.basename(relative)
    return (basename == "config.json" or basename == "generation_config.json"
            or basename.endswith(".safetensors")
            or basename.endswith(".safetensors.index.json")
            or basename.endswith(".bin")
            or basename.endswith(".bin.index.json"))


def _tokenizer_file(relative):
    return os.path.basename(relative) in {
        "tokenizer_config.json", "tokenizer.json", "special_tokens_map.json",
        "vocab.json", "merges.txt", "spiece.model", "sentencepiece.bpe.model",
    }


def model_identity_digest(model_path):
    """Hash model configuration and all supported weight shards."""
    return _digest_files(model_path, _model_file)


def tokenizer_identity_digest(model_path):
    """Hash the tokenizer files used by an adapter."""
    return _digest_files(model_path, _tokenizer_file)


def _config_dimension(model_path):
    config_path = os.path.join(model_path, "config.json")
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as error:
        raise EmbeddingIdentityError(
            "cannot read embedding model config: %s" % error) from error
    for key in ("hidden_size", "d_model", "dim", "embedding_dim"):
        value = config.get(key)
        if isinstance(value, int) and value > 0:
            return value
    raise EmbeddingIdentityError("embedding model config has no dimension")


def _dependency_version(package):
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unavailable"


def embedding_dependency_versions():
    """Return the versions that define the isolated embedding runtime."""
    return tuple((package, _dependency_version(package)) for package in (
        "torch", "transformers", "tokenizers", "safetensors"))


def build_embedding_identity(model_path, route,
                             dependency_versions=None):
    """Build a real model identity without loading heavyweight weights."""
    if not isinstance(route, EmbeddingRoute):
        raise EmbeddingIdentityError("route must be an EmbeddingRoute")
    dimension = _config_dimension(model_path)
    if dimension != EMBEDDING_OUTPUT_DIMENSION:
        raise EmbeddingIdentityError(
            "route %s has dimension %s, expected 1024"
            % (route.route_id, dimension))
    return EmbeddingIdentity(
        route_id=route.route_id,
        model_digest=model_identity_digest(model_path),
        tokenizer_digest=tokenizer_identity_digest(model_path),
        adapter=route.adapter,
        instruction=route.instruction,
        output_dimension=dimension,
        vector_format=EMBEDDING_VECTOR_FORMAT,
        metric=EMBEDDING_METRIC,
        dependency_versions=tuple(dependency_versions or
                                  embedding_dependency_versions()),
    )


def fixture_embedding_identity(route, model_digest=None,
                               tokenizer_digest=None,
                               dependency_versions=None):
    """Make an explicit identity for model-free 1024-d fixtures."""
    if not isinstance(route, EmbeddingRoute):
        raise EmbeddingIdentityError("route must be an EmbeddingRoute")
    return EmbeddingIdentity(
        route_id=route.route_id,
        model_digest=model_digest or "fixture-model-%s" % route.route_id,
        tokenizer_digest=tokenizer_digest or
        "fixture-tokenizer-%s" % route.route_id,
        adapter=route.adapter,
        instruction=route.instruction,
        output_dimension=EMBEDDING_OUTPUT_DIMENSION,
        vector_format=EMBEDDING_VECTOR_FORMAT,
        metric=EMBEDDING_METRIC,
        dependency_versions=tuple(dependency_versions or (
            ("torch", "fixture"), ("transformers", "fixture"),
            ("tokenizers", "fixture"), ("safetensors", "fixture"),
        )),
    )


def embedding_representation_id(route, identity):
    """Compose the complete identity for one dedicated route."""
    if not isinstance(route, EmbeddingRoute):
        raise EmbeddingIdentityError("route must be an EmbeddingRoute")
    if not isinstance(identity, EmbeddingIdentity):
        raise EmbeddingIdentityError("identity must be an EmbeddingIdentity")
    if identity.route_id != route.route_id:
        raise EmbeddingIdentityError("identity route does not match adapter")
    if identity.adapter != route.adapter or identity.instruction != route.instruction:
        raise EmbeddingIdentityError("identity adapter semantics do not match route")
    dependencies = ",".join("%s@%s" % item
                             for item in identity.dependency_versions)
    return (
        "%s:route=%s:payload=%s:serialization=%s:model=%s:tokenizer=%s:"
        "adapter=%s:instruction=%s:pool=%s:dim=%d:format=%s:metric=%s:deps=%s"
        % (
            EMBEDDING_REPRESENTATION_ID_VERSION,
            route.route_id,
            CANDIDATE_PAYLOAD_SCHEMA,
            CANDIDATE_SERIALIZATION,
            identity.model_digest,
            identity.tokenizer_digest,
            identity.adapter,
            identity.instruction,
            route.pooling,
            identity.output_dimension,
            identity.vector_format,
            identity.metric,
            dependencies,
        )
    )


_MODEL_REGISTRY_LOCK = threading.RLock()
_MODEL_REGISTRY = None


def _reset_model_registry_for_tests():
    """Clear the process model registry for isolated model-free tests."""
    global _MODEL_REGISTRY
    with _MODEL_REGISTRY_LOCK:
        _MODEL_REGISTRY = None


def _load_or_reuse_model(model_key, loader, validator=None):
    """Load at most one heavyweight model in this Python process."""
    global _MODEL_REGISTRY
    with _MODEL_REGISTRY_LOCK:
        if _MODEL_REGISTRY is not None:
            loaded_key, model, tokenizer = _MODEL_REGISTRY
            if loaded_key != model_key:
                raise ModelProcessConflictError(
                    "one heavyweight embedding model is already loaded")
            return model, tokenizer
        try:
            model, tokenizer = loader()
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - load must fail closed
            raise EmbeddingLoadError("embedding model load failed: %s" % error) \
                from error
        if model is None or tokenizer is None:
            raise EmbeddingLoadError("embedding loader returned an empty model")
        try:
            model.eval()
        except AttributeError:
            pass
        if validator is not None:
            validator(model)
        _MODEL_REGISTRY = (model_key, model, tokenizer)
        return model, tokenizer


class DedicatedEmbeddingAdapter:
    """Shared load, identity, forward and validation seam."""

    def __init__(self, route, model_path=None, identity=None, loader=None):
        if not isinstance(route, EmbeddingRoute):
            raise EmbeddingIdentityError("route must be an EmbeddingRoute")
        if model_path is None and identity is None:
            raise EmbeddingIdentityError("model_path or identity is required")
        self.route = route
        self.model_path = (os.path.abspath(model_path)
                           if model_path is not None else None)
        self._expected_identity = identity
        self._identity = identity
        self._loader = loader
        self._model = None
        self._tokenizer = None
        self._loaded_identity = None

    @property
    def identity(self):
        if self._identity is None:
            self._identity = build_embedding_identity(
                self.model_path, self.route)
        return self._identity

    @property
    def representation_id(self):
        return embedding_representation_id(self.route, self.identity)

    @property
    def output_dimension(self):
        return self.identity.output_dimension

    def _current_identity(self):
        if self.model_path is None:
            return self.identity
        return build_embedding_identity(self.model_path, self.route)

    def _validate_identity(self):
        current = self._current_identity()
        if current != self.identity:
            raise EmbeddingIdentityError(
                "embedding model identity changed before inference")

    def _default_loader(self):
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise EmbeddingLoadError(
                "transformers is required in .venv-embeddings") from error
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                self.model_path, local_files_only=True)
            model = AutoModel.from_pretrained(
                self.model_path, local_files_only=True)
        except Exception as error:  # noqa: BLE001 - fail closed
            raise EmbeddingLoadError(
                "cannot load local embedding model: %s" % error) from error
        return model, tokenizer

    def load(self):
        """Load or reuse the one process-owned model after identity checks."""
        if self._model is not None:
            self._validate_identity()
            return
        self._validate_identity()
        model_key = (
            "injected" if self.model_path is None
            else os.path.realpath(self.model_path),
            self.representation_id,
        )
        loader = self._loader or self._default_loader
        model, tokenizer = _load_or_reuse_model(
            model_key, loader, validator=self._validate_model_shape)
        self._model = model
        self._tokenizer = tokenizer
        self._loaded_identity = self.identity

    def _validate_model_shape(self, model):
        config = getattr(model, "config", None)
        dimension = getattr(config, "hidden_size", None)
        if dimension is not None and dimension != EMBEDDING_OUTPUT_DIMENSION:
            raise EmbeddingIdentityError(
                "loaded model dimension is not 1024")
        model_type = getattr(config, "model_type", None)
        expected_type = "qwen3" if self.route.adapter == "qwen3" \
            else "xlm-roberta"
        if model_type != expected_type:
            raise EmbeddingIdentityError(
                "loaded model architecture %r does not match %s route"
                % (model_type, self.route.route_id))

    def _input_text(self, preceding_text, candidate, is_query):
        payload = candidate_conditioned_payload(preceding_text, candidate)
        if is_query and self.route.adapter == "qwen3":
            return self.route.instruction + "\n" + payload
        return payload

    @staticmethod
    def _to_rows(value):
        try:
            value = value.detach().float().cpu().tolist()
        except AttributeError:
            if hasattr(value, "tolist"):
                value = value.tolist()
        if not isinstance(value, list) or not value:
            raise EmbeddingInferenceError("model returned no hidden states")
        if isinstance(value[0], list) and value[0] \
                and isinstance(value[0][0], list):
            value = value[0]
        if not isinstance(value[0], list):
            raise EmbeddingInferenceError("hidden states have no sequence axis")
        return value

    @staticmethod
    def _to_mask(value, row_count):
        if value is None:
            return [1] * row_count
        try:
            value = value.detach().cpu().tolist()
        except AttributeError:
            if hasattr(value, "tolist"):
                value = value.tolist()
        if isinstance(value, list) and value and isinstance(value[0], list):
            value = value[0]
        if not isinstance(value, list) or len(value) != row_count:
            raise EmbeddingInferenceError("attention mask shape mismatch")
        return [int(item) for item in value]

    def _forward(self, text):
        self.load()
        self._validate_identity()
        try:
            encoded = self._tokenizer(
                text, return_tensors="pt", add_special_tokens=False)
            input_ids = encoded.get("input_ids")
            if input_ids is None:
                raise EmbeddingInferenceError("tokenizer returned no input ids")
            hidden = self._model(**encoded)
            hidden = (hidden.get("last_hidden_state")
                      if isinstance(hidden, dict)
                      else getattr(hidden, "last_hidden_state", None))
            if hidden is None:
                raise EmbeddingInferenceError(
                    "model returned no last_hidden_state")
            rows = self._to_rows(hidden)
            mask = self._to_mask(encoded.get("attention_mask"), len(rows))
            active = [row for row, enabled in zip(rows, mask) if enabled]
            if not active:
                raise EmbeddingInferenceError("tokenizer produced no active tokens")
            if self.route.pooling == "last-token":
                vector = active[-1]
            else:
                dimension = len(active[0])
                if dimension == 0 or any(len(row) != dimension for row in active):
                    raise EmbeddingInferenceError("hidden dimension is inconsistent")
                vector = [sum(row[index] for row in active) / len(active)
                          for index in range(dimension)]
            if len(vector) != EMBEDDING_OUTPUT_DIMENSION:
                raise EmbeddingInferenceError(
                    "embedding dimension is not 1024")
            return l2_normalize(vector)
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - inference fails closed
            raise EmbeddingInferenceError(
                "embedding inference failed: %s" % error) from error

    def query(self, preceding_text, candidate):
        return self._forward(self._input_text(preceding_text, candidate, True))

    def document(self, preceding_text, candidate):
        return self._forward(self._input_text(preceding_text, candidate, False))


class Qwen3EmbeddingAdapter(DedicatedEmbeddingAdapter):
    """Qwen3-Embedding-0.6B query/document adapter."""

    def __init__(self, model_path=None, identity=None, loader=None):
        super().__init__(QWEN3_EMBEDDING_ROUTE, model_path, identity, loader)


class BGEM3EmbeddingAdapter(DedicatedEmbeddingAdapter):
    """BGE-M3 dense-only adapter; sparse and ColBERT outputs are unavailable."""

    def __init__(self, model_path=None, identity=None, loader=None):
        super().__init__(BGE_M3_EMBEDDING_ROUTE, model_path, identity, loader)


class DedicatedEmbeddingRepresentationProvider(RepresentationProvider):
    """Candidate-conditioned provider for one dedicated embedding adapter."""

    def __init__(self, adapter):
        if not isinstance(adapter, DedicatedEmbeddingAdapter):
            raise EmbeddingIdentityError("provider requires an embedding adapter")
        self._adapter = adapter

    def representation_id(self):
        return self._adapter.representation_id

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        raise EvidenceError(
            "representation_fault",
            "candidate-conditioned embedding requires a candidate")

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._forward(self._adapter.query, preceding_text, candidate)

    def event_vector(self, event):
        return self.event_vector_for_candidate(event, event.final_selection_text)

    def event_vector_for_candidate(self, event, candidate):
        if candidate != event.final_selection_text:
            raise EvidenceError(
                "representation_fault",
                "event vector candidate does not match selection")
        return self._forward(self._adapter.document, event.preceding_text,
                             candidate)

    def vector_dimension(self):
        return self._adapter.output_dimension

    @staticmethod
    def _forward(fn, preceding_text, candidate):
        try:
            return fn(preceding_text, candidate)
        except EvidenceError:
            raise
        except EmbeddingError as error:
            raise EvidenceError("representation_fault", str(error)) from error
        except Exception as error:  # noqa: BLE001 - provider fails closed
            raise EvidenceError(
                "representation_fault", "embedding failed: %s" % error
            ) from error


class Qwen3EmbeddingRepresentationProvider(
        DedicatedEmbeddingRepresentationProvider):
    """RepresentationProvider for the frozen Qwen route."""

    def __init__(self, model_path=None, identity=None, loader=None):
        super().__init__(Qwen3EmbeddingAdapter(model_path, identity, loader))


class BGEM3RepresentationProvider(DedicatedEmbeddingRepresentationProvider):
    """RepresentationProvider for the frozen BGE dense route."""

    def __init__(self, model_path=None, identity=None, loader=None):
        super().__init__(BGEM3EmbeddingAdapter(model_path, identity, loader))


def embedding_fixture_vector(axis):
    """Return a deterministic unit vector for model-free route fixtures."""
    if not isinstance(axis, int) or not 0 <= axis < EMBEDDING_OUTPUT_DIMENSION:
        raise EmbeddingError("fixture axis is outside the embedding dimension")
    result = [0.0] * EMBEDDING_OUTPUT_DIMENSION
    result[axis] = 1.0
    return tuple(result)


class EmbeddingFixtureRepresentationProvider(
        CandidateFixtureRepresentationProvider):
    """1024-dimensional candidate fixture bound to a dedicated route id."""

    def __init__(self, route, identity, query_vectors, event_vectors,
                 default_query=None, default_event=None):
        vectors = list(query_vectors.values()) + list(event_vectors.values())
        for vector in vectors:
            if len(vector) != EMBEDDING_OUTPUT_DIMENSION:
                raise EmbeddingError("embedding fixture vectors must be 1024-dimensional")
        representation_id = embedding_representation_id(route, identity)
        super().__init__(
            representation_id,
            query_vectors,
            event_vectors,
            default_query=(default_query if default_query is not None
                           else embedding_fixture_vector(0)),
            default_event=(default_event if default_event is not None
                           else embedding_fixture_vector(1)),
        )
        if self.vector_dimension() != EMBEDDING_OUTPUT_DIMENSION:
            raise EmbeddingError("embedding fixture must be 1024-dimensional")
