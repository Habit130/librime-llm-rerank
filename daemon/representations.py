#!/usr/bin/env python3
"""Versioned hidden-state 上文 representations (Habit130/squirrel#60).

This module is the pure, model-free core of the representation seam: it owns
the pre-declared first-round candidate set, the deterministic
``representation_id`` composition, the tokenization seams (exact vs split
reuse), the L2 normalization that makes cosine similarity a pure dot product,
and the fail-closed boundary rules. It deliberately imports no MLX and no
transformers, so the model-free daemon gate (``python3 -m unittest discover
-s daemon -p 'test_*.py'``) can exercise every acceptance criterion that does
not require a real forward.

The MLX-bound extraction (the version-constrained Qwen3 forward) lives in
``hidden_state.py``; it imports ``representations``, never the other way.

The seam semantics are pinned by the manual prototype preserved on
``feat/prototype-semantic-neighbors`` (Habit130/squirrel#33 / #41):

- first-round candidates = exact L14/L21/L28 last-token + split-reuse L28;
- intermediate snapshots apply Qwen's **final** RMSNorm exactly like the last
  layer, so all layers are compared on one scale;
- every representation is FP32 and L2-normalized, so distance is cosine;
- the pre-declared split-reuse representation reuses the scoring seam
  (tokenized prefix + tail instead of one exact ``encode(last64)``); the
  seam changes tokens on BPE boundaries, so its representation_id always
  differs from the exact 64-char representation even when the vectors happen
  to agree on a smooth seam.

Every generated vector is bound to its ``representation_id`` (AC60-3 / spec
#43 "任何表示变化都会触发正确重建"); recomputing under a changed identity
must treat the old vector as incompatible (SCN-60-1).
"""

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

REPRESENTATION_ID_VERSION = "hidden-state-repr-v1"
CANDIDATE_REPRESENTATION_ID_VERSION = "candidate-conditioned-repr-v1"
GRAPH_VERSION = "1"

# ADR-0002 / spec #43: the model is conditioned on the last 64 chars of 上文.
WINDOW_CHARS = 64
# The scoring seam (docs/token-attribution.md) re-tokenizes the last 4 chars
# per candidate; the split-reuse representation is defined on that seam.
TAIL_CHARS = 4

# First-round exact layers (project notation, 1-indexed; layer `n` maps to
# the 0-indexed `model.model.layers[n-1]`).
EXACT_LAYERS = (14, 21, 28)
# The single pre-declared split-reuse representation (Habit130/squirrel#33).
SPLIT_REUSE_LAYER = 28

POOLING = "last"
NORM_TAG = "rmsnorm+l2"
OUTPUT_DTYPE = "fp32"
METRIC = "cosine"
CANDIDATE_PAYLOAD_SCHEMA = "candidate-conditioned-concat-v1"
CANDIDATE_SERIALIZATION = "last64-preceding-plus-candidate:no-separator:no-special"
CANDIDATE_SPAN_RULE = "candidate-token-span-v1"

# Files that make up the model identity digest and the tokenizer identity
# digest, in this fixed order so the digest is canonical across environments.
MODEL_IDENTITY_FILES = ("config.json", "generation_config.json",
                        "model.safetensors")
TOKENIZER_IDENTITY_FILES = ("tokenizer_config.json", "tokenizer.json",
                            "vocab.json", "merges.txt")


class RepresentationError(Exception):
    """A true fault in representation generation.

    Distinct from producing a vector: callers must treat subclasses as
    failures (pass-through / rebuild), never as an empty or zero result.
    """


class EmptyContextRepresentationError(RepresentationError):
    """The context window is empty or tokenizes to no tokens.

    A last-token representation is undefined on an empty window. There is no
    phantom EOS-anchored vector here (the scoring seam anchors EOS only
    because it must condition candidate tokens on something; a representation
    of void text would be a dirty vector that could later contribute bogus
    evidence), so an empty 上文 is an explicit fault (SCN-60-2).
    """


class NonFiniteRepresentationError(RepresentationError):
    """The draft vector is not finite or cannot be L2-normalized.

    Non-finite values and zero-norm vectors are both rejected here, so a
    dirty vector can never leave the generation path (SCN-60-2).
    """


class ModelForwardRepresentationError(RepresentationError):
    """The underlying model forward failed (SCN-60-2 "模型错误")."""


class InvalidRepresentationSpec(RepresentationError):
    """A representation specification is outside the supported envelope."""


@dataclass(frozen=True)
class RepresentationSpec:
    """One pre-declared representation candidate.

    ``kind`` is ``exact`` (one deterministic ``encode(last N chars)`` forward)
    or ``split_reuse`` (the scoring seam: tokenized prefix + tail, prefix
    KV-cached). ``layer`` uses the project's 1-indexed notation (14/21/28).
    The fixed engineering choices -- pooling = last-token, normalization =
    final RMSNorm + L2, output dtype = fp32, metric = cosine -- are part of
    the identity and are not configurable by a caller.
    """

    kind: str
    layer: int
    window_chars: int = WINDOW_CHARS
    pooling: str = POOLING
    norm: str = NORM_TAG
    dtype: str = OUTPUT_DTYPE
    metric: str = METRIC
    id_version: str = field(default=REPRESENTATION_ID_VERSION)

    def __post_init__(self):
        if self.kind not in ("exact", "split_reuse"):
            raise InvalidRepresentationSpec("kind must be exact or split_reuse")
        if not isinstance(self.layer, int) or self.layer < 1:
            raise InvalidRepresentationSpec("layer must be a positive integer")
        if self.kind == "exact" and self.layer not in EXACT_LAYERS:
            raise InvalidRepresentationSpec(
                "exact layer %d is not in the pre-declared set %r"
                % (self.layer, EXACT_LAYERS))
        if self.kind == "split_reuse" and self.layer != SPLIT_REUSE_LAYER:
            raise InvalidRepresentationSpec(
                "split_reuse layer must be %d" % SPLIT_REUSE_LAYER)
        if not isinstance(self.window_chars, int) or self.window_chars < 1:
            raise InvalidRepresentationSpec("window_chars must be positive")
        if self.pooling != POOLING:
            raise InvalidRepresentationSpec("only last-token pooling is declared")
        if self.norm != NORM_TAG:
            raise InvalidRepresentationSpec("only rmsnorm+l2 normalization is declared")
        if self.dtype != OUTPUT_DTYPE:
            raise InvalidRepresentationSpec("only fp32 output is declared")
        if self.metric != METRIC:
            raise InvalidRepresentationSpec("only cosine metric is declared")

    @property
    def seam(self):
        return self.kind

    @property
    def layer_index(self):
        """0-indexed layer index into ``model.model.layers``."""
        return self.layer - 1

    @property
    def short_name(self):
        if self.kind == "exact":
            return "exact_l%d_%s" % (self.layer, self.pooling)
        return "split_l%d_%s" % (self.layer, self.pooling)

    def __str__(self):
        return self.short_name


@dataclass(frozen=True)
class CandidateRepresentationSpec:
    """One of the four frozen candidate-conditioned Qwen routes.

    This remains separate from ``RepresentationSpec`` so the accepted
    context-only #60/#69 regression artifact is not changed.
    """

    layer: int
    pooling: str
    window_chars: int = WINDOW_CHARS
    payload_schema: str = CANDIDATE_PAYLOAD_SCHEMA
    serialization: str = CANDIDATE_SERIALIZATION
    span_rule: str = CANDIDATE_SPAN_RULE
    norm: str = NORM_TAG
    dtype: str = OUTPUT_DTYPE
    metric: str = METRIC
    id_version: str = field(default=CANDIDATE_REPRESENTATION_ID_VERSION)

    def __post_init__(self):
        if self.layer not in EXACT_LAYERS:
            raise InvalidRepresentationSpec(
                "candidate layer %d is not in the pre-declared set %r"
                % (self.layer, EXACT_LAYERS))
        if self.pooling not in ("candidate_span_mean", "last_candidate_token"):
            raise InvalidRepresentationSpec(
                "candidate pooling is not pre-declared: %r" % self.pooling)
        if self.pooling == "last_candidate_token" and self.layer != 28:
            raise InvalidRepresentationSpec(
                "last_candidate_token control must use layer 28")
        if self.window_chars != WINDOW_CHARS:
            raise InvalidRepresentationSpec(
                "candidate window_chars must be exactly %d" % WINDOW_CHARS)
        if self.payload_schema != CANDIDATE_PAYLOAD_SCHEMA:
            raise InvalidRepresentationSpec("unsupported candidate payload")
        if self.serialization != CANDIDATE_SERIALIZATION:
            raise InvalidRepresentationSpec("unsupported candidate serialization")
        if self.span_rule != CANDIDATE_SPAN_RULE:
            raise InvalidRepresentationSpec("unsupported candidate span rule")
        if self.norm != NORM_TAG:
            raise InvalidRepresentationSpec("only rmsnorm+l2 normalization is declared")
        if self.dtype != OUTPUT_DTYPE:
            raise InvalidRepresentationSpec("only fp32 output is declared")
        if self.metric != METRIC:
            raise InvalidRepresentationSpec("only cosine metric is declared")

    @property
    def short_name(self):
        return "candidate_l%d_%s" % (self.layer, self.pooling)

    def __str__(self):
        return self.short_name


@dataclass(frozen=True)
class ModelTokenIdentity:
    """The model/tokenizer summary the representation_id is bound to.

    ``model_digest`` hashes the model's config and weight file contents,
    ``tokenizer_digest`` hashes the tokenizer files, ``mlxlm_version`` pins
    the MLX-LM implementation the forward wrapper is constrained to, and
    ``hidden_dim`` is the representation dimension from the model config.
    """

    model_digest: str
    tokenizer_digest: str
    mlxlm_version: str
    hidden_dim: int

    def __post_init__(self):
        if not self.model_digest or not self.tokenizer_digest:
            raise RepresentationError("identity digests must not be empty")
        if not self.mlxlm_version:
            raise RepresentationError("mlx-lm version must not be empty")
        if not isinstance(self.hidden_dim, int) or self.hidden_dim < 1:
            raise RepresentationError("hidden_dim must be a positive integer")


# ---------------------------------------------------------------------------
# Model / tokenizer identity digest
# ---------------------------------------------------------------------------

def _sha256_hex(content):
    return hashlib.sha256(content).hexdigest()


def _file_bytes_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_digest(directory, files):
    """Deterministic digest over a canonical, ordered file set.

    Each present file contributes ``name:size:sha256(content)``; a file that
    is expected but missing is recorded as ``name:missing`` so a changed file
    set changes the digest.
    """
    digest = hashlib.sha256()
    digest.update(b"identity-file-set-v1\n")
    for name in files:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            digest.update(("%s:missing\0" % name).encode("utf-8"))
            continue
        digest.update(("%s:%d:%s\0" % (
            name, os.path.getsize(path),
            _file_bytes_sha256(path))).encode("utf-8"))
    return digest.hexdigest()


def model_identity_digest(model_path):
    try:
        return _identity_digest(model_path, MODEL_IDENTITY_FILES)
    except OSError as error:
        raise RepresentationError(
            "cannot hash model identity at %s: %s" % (model_path, error)
        )


def tokenizer_identity_digest(model_path):
    try:
        return _identity_digest(model_path, TOKENIZER_IDENTITY_FILES)
    except OSError as error:
        raise RepresentationError(
            "cannot hash tokenizer identity at %s: %s" % (model_path, error)
        )


def _config_hidden_dim(model_path):
    config_path = os.path.join(model_path, "config.json")
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise RepresentationError(
            "cannot read model config at %s: %s" % (config_path, error))
    hidden_dim = config.get("hidden_size")
    if not isinstance(hidden_dim, int) or hidden_dim < 1:
        raise RepresentationError(
            "config hidden_size missing or invalid at %s" % config_path)
    return hidden_dim


def build_model_token_identity(model_path):
    """Lazily build the identity; hashing reads the weight file once per
    process (cached by the extractor)."""
    return ModelTokenIdentity(
        model_digest=model_identity_digest(model_path),
        tokenizer_digest=tokenizer_identity_digest(model_path),
        mlxlm_version=_mlx_lm_version(),
        hidden_dim=_config_hidden_dim(model_path),
    )


def _mlx_lm_version():
    try:
        from importlib import metadata
        return metadata.version("mlx-lm")
    except Exception:  # noqa: BLE001 - any resolution problem means unknown
        return "unknown"


# ---------------------------------------------------------------------------
# representation_id composition (AC60-3)
# ---------------------------------------------------------------------------

def representation_id(spec, identity):
    """Deterministic identity of one representation candidate.

    Covers every component the acceptance contract names: model/tokenizer
    summaries, mlx-lm implementation version, layer, pooling, truncation
    (window chars), seam, normalization, dimension, dtype and distance
    metric. Any change to any component yields a different id, which is the
    versioning contract: vectors computed under one id are incompatible with
    vectors under another (SCN-60-1).
    """
    if isinstance(spec, CandidateRepresentationSpec):
        return candidate_representation_id(spec, identity)
    if not isinstance(spec, RepresentationSpec):
        raise InvalidRepresentationSpec("spec must be a RepresentationSpec")
    if not isinstance(identity, ModelTokenIdentity):
        raise InvalidRepresentationSpec("identity must be a ModelTokenIdentity")
    return "%s:model=%s:tokenizer=%s:mlxlm=%s:graph=%s:layer=%d:pool=%s:window=%d:seam=%s:norm=%s:dim=%d:dtype=%s:metric=%s" % (
        spec.id_version,
        identity.model_digest[:16],
        identity.tokenizer_digest[:16],
        identity.mlxlm_version,
        GRAPH_VERSION,
        spec.layer,
        spec.pooling,
        spec.window_chars,
        spec.seam,
        spec.norm,
        identity.hidden_dim,
        spec.dtype,
        spec.metric,
    )


def candidate_representation_id(spec, identity):
    """Bind the frozen candidate payload and pooling contract to an id."""
    if not isinstance(spec, CandidateRepresentationSpec):
        raise InvalidRepresentationSpec(
            "spec must be a CandidateRepresentationSpec")
    if not isinstance(identity, ModelTokenIdentity):
        raise InvalidRepresentationSpec("identity must be a ModelTokenIdentity")
    return (
        "%s:payload=%s:serialization=%s:model=%s:tokenizer=%s:mlxlm=%s:"
        "graph=%s:layer=%d:pool=%s:window=%d:span=%s:norm=%s:dim=%d:"
        "dtype=%s:metric=%s"
        % (
            spec.id_version,
            spec.payload_schema,
            spec.serialization,
            identity.model_digest[:16],
            identity.tokenizer_digest[:16],
            identity.mlxlm_version,
            GRAPH_VERSION,
            spec.layer,
            spec.pooling,
            spec.window_chars,
            spec.span_rule,
            spec.norm,
            identity.hidden_dim,
            spec.dtype,
            spec.metric,
        )
    )


# ---------------------------------------------------------------------------
# Seams: which string is tokenized, and its fail-closed routing
# ---------------------------------------------------------------------------

def window_text(context, window_chars=WINDOW_CHARS):
    """Truncate to the last ``window_chars`` characters (ADR-0002)."""
    if not context:
        return ""
    if window_chars >= len(context):
        return context
    return context[-window_chars:]


def split_context(context, window_chars=WINDOW_CHARS, tail_chars=TAIL_CHARS):
    """The scoring seam's split of the windowed context.

    Mirrors ``ModelState.score``: a window longer than ``tail_chars`` splits
    into ``prefix`` (all but the last ``tail_chars``) and ``tail`` (the last
    ``tail_chars``); a window at most ``tail_chars`` long has an empty prefix
    and the whole window as tail. The split-reuse representation is defined
    on the *tokenization of this split*, which is what makes its
    representation_id different from exact even when the tokens coincide.
    """
    windowed = window_text(context, window_chars)
    if len(windowed) > tail_chars:
        return windowed[:-tail_chars], windowed[-tail_chars:]
    return "", windowed


def exact_tokenization_for(tokenizer, context, window_chars=WINDOW_CHARS,
                           spec=None):
    """The exact seam: one deterministic ``encode(last N chars)``.

    Returns ``(windowed_text, token_ids)`` where ``token_ids`` is a tuple.
    An empty window, or a window that tokenizes to zero tokens, is an
    explicit ``EmptyContextRepresentationError`` (successful zero values are
    not defined for a last-token representation).
    """
    if spec is not None and spec.kind != "exact":
        raise InvalidRepresentationSpec("exact_tokenization_for requires an exact spec")
    windowed = window_text(context, window_chars)
    if not windowed:
        raise EmptyContextRepresentationError("empty context window")
    ids = tokenizer.encode(windowed, add_special_tokens=False)
    if not ids:
        raise EmptyContextRepresentationError(
            "context window tokenizes to no tokens")
    return windowed, tuple(ids)


def split_tokenization_for(tokenizer, context, window_chars=WINDOW_CHARS,
                           tail_chars=TAIL_CHARS, spec=None):
    """The split-reuse seam: tokenized prefix + tokenized tail separately.

    Returns ``(prefix_text, prefix_ids, tail_text, tail_ids)``. The prefix
    and tail are tokenized independently (never re-concatenated), which is
    the point of the seam: ``encode(prefix) + encode(tail)`` can differ from
    ``encode(prefix + tail)`` on BPE seams (SCN-60-2 / #41).
    """
    if spec is not None and spec.kind != "split_reuse":
        raise InvalidRepresentationSpec(
            "split_tokenization_for requires a split_reuse spec")
    windowed = window_text(context, window_chars)
    if not windowed:
        raise EmptyContextRepresentationError("empty context window")
    prefix_text, tail_text = split_context(
        windowed, window_chars, tail_chars)
    prefix_ids = (
        tuple(tokenizer.encode(prefix_text, add_special_tokens=False))
        if prefix_text else ()
    )
    tail_ids = tuple(tokenizer.encode(tail_text, add_special_tokens=False))
    if not tail_ids:
        raise EmptyContextRepresentationError(
            "tail tokenizes to no tokens")
    return prefix_text, prefix_ids, tail_text, tail_ids


class CandidateSpanRepresentationError(RepresentationError):
    """The tokenizer cannot establish a lossless candidate token span."""


class EmptyCandidateRepresentationError(CandidateSpanRepresentationError):
    """An empty candidate has no token span and cannot be represented."""


def candidate_conditioned_payload(preceding_text, candidate,
                                  window_chars=WINDOW_CHARS):
    """The frozen payload: ``last_64(preceding_text) + candidate``."""
    if window_chars != WINDOW_CHARS:
        raise InvalidRepresentationSpec(
            "candidate window_chars must be exactly %d" % WINDOW_CHARS)
    if not isinstance(candidate, str) or not candidate:
        raise EmptyCandidateRepresentationError("empty candidate")
    if not isinstance(preceding_text, str):
        raise RepresentationError("preceding_text must be a string")
    return window_text(preceding_text, window_chars) + candidate


def candidate_tokenization_for(tokenizer, preceding_text, candidate,
                               window_chars=WINDOW_CHARS, spec=None):
    """Return payload token ids and the deterministic candidate token span.

    Attribution uses the same decode/reconstruction rule as
    ``candidate_scoring_plan``. A token crossing the context/candidate
    boundary is not attributable and therefore fails closed.
    """
    if spec is not None and not isinstance(spec, CandidateRepresentationSpec):
        raise InvalidRepresentationSpec(
            "candidate_tokenization_for requires a candidate spec")
    payload = candidate_conditioned_payload(
        preceding_text, candidate, window_chars)
    ids = tokenizer.encode(payload, add_special_tokens=False)
    if not ids:
        raise CandidateSpanRepresentationError(
            "payload tokenizes to no tokens")
    if tokenizer.decode(ids) != payload:
        raise CandidateSpanRepresentationError(
            "lossy candidate-conditioned tokenization")
    context = window_text(preceding_text, window_chars)
    if not context:
        if tokenizer.decode(ids) != candidate:
            raise RepresentationError("candidate suffix mismatch")
        return payload, tuple(ids), 0, len(ids)
    for boundary in range(1, len(ids) + 1):
        if tokenizer.decode(ids[:boundary]) != context:
            continue
        if boundary == len(ids):
            raise EmptyCandidateRepresentationError(
                "candidate token span is empty")
        if tokenizer.decode(ids[boundary:]) != candidate:
            raise CandidateSpanRepresentationError("candidate suffix mismatch")
        return payload, tuple(ids), boundary, len(ids) - boundary
    raise CandidateSpanRepresentationError(
        "token straddles context/candidate boundary")


def seam_changed(prefix_text, prefix_ids, tail_text, tail_ids,
                 exact_ids):
    """Whether the split seam produced a different token stream than exact.

    ``exact_ids`` must be the tokenization of ``prefix_text + tail_text``.
    True when a BPE token spans the prefix/tail character boundary (#41).
    """
    return tuple(exact_ids) != tuple(prefix_ids) + tuple(tail_ids)


# ---------------------------------------------------------------------------
# Vector normalization (AC60-1: L2 normalization; cosine is the metric)
# ---------------------------------------------------------------------------

def l2_normalize(values):
    """Unit-normalize a finite vector; fail closed otherwise.

    Raises ``NonFiniteRepresentationError`` for any non-finite value (NaN,
    +/-inf) or a zero-norm vector. A zero-norm or non-finite vector is a
    dirty vector and must never leave the generation path, so it is an
    explicit fault (SCN-60-2).
    """
    vector = tuple(float(value) for value in values)
    if not vector:
        raise NonFiniteRepresentationError("empty vector")
    squared = 0.0
    for value in vector:
        if not math.isfinite(value):
            raise NonFiniteRepresentationError(
                "non-finite vector value %r" % (value,))
        squared += value * value
    norm = math.sqrt(squared)
    if not math.isfinite(norm) or norm == 0.0:
        raise NonFiniteRepresentationError("zero-norm vector")
    return tuple(value / norm for value in vector)


def cosine(left, right):
    """Cosine of two unit vectors (the declared metric).

    Operates on already L2-normalized representations; kept as a small pure
    helper for tests. Raises ``NonFiniteRepresentationError`` when either
    side is not finite or a zero vector.
    """
    left = tuple(float(value) for value in left)
    right = tuple(float(value) for value in right)
    if len(left) != len(right):
        raise NonFiniteRepresentationError("cosine dimension mismatch")
    for value in left + right:
        if not math.isfinite(value):
            raise NonFiniteRepresentationError("non-finite cosine input")
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for lvalue, rvalue in zip(left, right):
        dot += lvalue * rvalue
        left_norm += lvalue * lvalue
        right_norm += rvalue * rvalue
    if left_norm == 0.0 or right_norm == 0.0:
        raise NonFiniteRepresentationError("cosine requires non-zero vectors")
    return dot / math.sqrt(left_norm * right_norm)


# ---------------------------------------------------------------------------
# First-round candidate set (AC60-1 / AC60-2)
# ---------------------------------------------------------------------------

def first_round_specs():
    """The pre-declared first-round representation candidate set.

    Kept exactly to the manual prototype's survivors (Habit130/squirrel#33):
    exact L14/L21/L28 last-token, and the split-reuse L28 representation.
    EOS last-token, unnormalized dot, prefix-only (drop-last-4-chars) and
    candidate-conditioned pair representations were rejected by the manual
    prototype and are not first-round candidates.
    """
    return (
        RepresentationSpec(kind="exact", layer=14),
        RepresentationSpec(kind="exact", layer=21),
        RepresentationSpec(kind="exact", layer=28),
        RepresentationSpec(kind="split_reuse", layer=SPLIT_REUSE_LAYER),
    )


def candidate_conditioned_specs():
    """Exactly the four frozen Qwen3 candidate-conditioned routes."""
    return (
        CandidateRepresentationSpec(layer=14, pooling="candidate_span_mean"),
        CandidateRepresentationSpec(layer=21, pooling="candidate_span_mean"),
        CandidateRepresentationSpec(layer=28, pooling="candidate_span_mean"),
        CandidateRepresentationSpec(layer=28, pooling="last_candidate_token"),
    )
