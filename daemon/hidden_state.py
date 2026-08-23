#!/usr/bin/env python3
"""MLX-bound extraction of versioned hidden-state 上文 representations (#60).

``HiddenStateExtractor`` wraps the daemon's already-loaded ``ModelState`` and
reuses its ``model`` and ``tokenizer``; it never loads a second model
(ADR-0001 / SCN-60-3). It implements a version-constrained Qwen3 forward —
layer-by-layer so intermediate snapshots can be captured after Qwen's final
RMSNorm, exactly preserving the manual prototype's seam
(``feat/prototype-semantic-neighbors``) — and the representation_id of every
produced vector is bound to ``representations.ModelTokenIdentity``
(mlx-lm version, model/tokenizer digests, hidden dim).

The model graph functions (``create_attention_mask``, layer ``__call__``,
``make_prompt_cache``) are taken from the pinned ``mlx-lm`` and the Qwen3
structure is asserted before any forward, so a different or renamed model
architecture fails closed instead of producing a vector from the wrong graph.

All MLX/numpy imports are lazy so the model-free daemon gate can import this
module without MLX installed.
"""

from evidence import EvidenceError, RepresentationProvider
from representations import (
    CandidateRepresentationSpec,
    EXACT_LAYERS,
    SPLIT_REUSE_LAYER,
    EmptyContextRepresentationError,
    InvalidRepresentationSpec,
    ModelForwardRepresentationError,
    ModelTokenIdentity,
    RepresentationError,
    RepresentationSpec,
    build_model_token_identity,
    candidate_tokenization_for,
    candidate_conditioned_specs,
    exact_tokenization_for,
    l2_normalize,
    representation_id,
    split_tokenization_for,
)


def _lazy_mlx():
    import mlx.core as mx
    from mlx_lm.models.base import create_attention_mask
    from mlx_lm.models.cache import make_prompt_cache
    return mx, create_attention_mask, make_prompt_cache


def pool_candidate_hidden_states(hidden_states, candidate_start,
                                 candidate_count, pooling):
    """Pool an already RMSNormed sequence over the candidate span only."""
    end = candidate_start + candidate_count
    if candidate_start < 0 or candidate_count < 1 \
            or end > len(hidden_states):
        raise InvalidRepresentationSpec("candidate token span is invalid")
    span = hidden_states[candidate_start:end]
    if pooling == "candidate_span_mean":
        dimension = len(span[0])
        draft = [sum(row[index] for row in span) / len(span)
                 for index in range(dimension)]
    elif pooling == "last_candidate_token":
        draft = span[-1]
    else:
        raise InvalidRepresentationSpec(
            "unsupported candidate pooling %r" % pooling)
    return l2_normalize(draft)


class HiddenStateExtractor:
    """Generate pre-declared hidden-state representations from a loaded state.

    ``state`` must expose the ``ModelState`` surface: ``model_path``,
    ``load()``, ``loaded`` and, once loaded, ``model`` and ``tokenizer``.
    The extractor is stateless apart from the cached model/tokenizer identity
    digest (hashing the weight file once per process, lazily on first
    representation request -- it is never in the scoring hot path).
    """

    def __init__(self, state):
        self._state = state
        self._identity = None

    # -- identity ----------------------------------------------------------

    @property
    def identity(self):
        if self._identity is None:
            self._identity = build_model_token_identity(self._state.model_path)
        return self._identity

    def representation_id(self, spec):
        return representation_id(spec, self.identity)

    # -- model access ------------------------------------------------------

    def _require_model(self):
        self._state.load()
        model = self._state.model
        if model is None:
            raise RepresentationError("model is not loaded")
        if getattr(model, "model_type", None) != "qwen3":
            raise InvalidRepresentationSpec(
                "representations require mlx-lm qwen3 architecture, got %r"
                % getattr(model, "model_type", None))
        inner = getattr(model, "model", None)
        for attribute in ("embed_tokens", "layers", "norm"):
            if getattr(inner, attribute, None) is None:
                raise InvalidRepresentationSpec(
                    "qwen3 model missing attribute %r" % attribute)
        if len(inner.layers) < max(EXACT_LAYERS + (SPLIT_REUSE_LAYER,)):
            raise InvalidRepresentationSpec(
                "qwen3 model has %d layers, need at least %d"
                % (len(inner.layers), max(EXACT_LAYERS + (SPLIT_REUSE_LAYER,))))
        return model, inner

    def _tokenizer(self):
        if self._state.tokenizer is None:
            raise RepresentationError("tokenizer is not loaded")
        return self._state.tokenizer

    # -- forward -----------------------------------------------------------

    def _run(self, ids, cache, snapshot_layers):
        """Version-constrained Qwen3 forward with layer snapshots.

        ``ids`` is a non-empty token-id tuple. ``cache`` is a prompt-cache
        list whose offset already consumes previously processed tokens (for
        the split-reuse seam) or None for a standalone forward. For every
        1-indexed ``layer_number`` in ``snapshot_layers`` the post-layer
        hidden state is passed through Qwen's final RMSNorm, cast to FP32,
        its last token is L2-normalized and validated; snapshots are returned
        keyed by ``layer_number``.
        """
        mx, create_attention_mask, _ = _lazy_mlx()
        if not ids:
            raise EmptyContextRepresentationError("no tokens to forward")
        model, inner = self._require_model()
        token_ids = mx.array([list(ids)])
        h = inner.embed_tokens(token_ids)
        layer_cache = cache if cache is not None else [None] * len(inner.layers)
        mask = create_attention_mask(h, layer_cache[0])
        snapshots = {}
        try:
            import numpy as np
            for index, (layer, current_cache) in enumerate(
                zip(inner.layers, layer_cache)
            ):
                h = layer(h, mask, current_cache)
                layer_number = index + 1
                if layer_number in snapshot_layers:
                    normalized = inner.norm(h).astype(mx.float32)
                    last = np.asarray(normalized[0, -1]).ravel()
                    snapshots[layer_number] = l2_normalize(last)
            if not snapshots:
                mx.eval(h)
        except RepresentationError:
            raise
        except Exception as error:  # noqa: BLE001 - any model fault fails closed
            raise ModelForwardRepresentationError(
                "hidden-state forward failed: %s" % error) from error
        return snapshots, layer_cache

    def _forward_prefix(self, prefix_ids, cache=None):
        """Build a prompt cache over ``prefix_ids`` (scoring-seam prefix
        forward). Returns the cache list with its KV materialized."""
        mx, create_attention_mask, make_prompt_cache = _lazy_mlx()
        model, inner = self._require_model()
        if cache is None:
            cache = make_prompt_cache(model)
        if not prefix_ids:
            return cache
        token_ids = mx.array([list(prefix_ids)])
        h = inner.embed_tokens(token_ids)
        mask = create_attention_mask(h, cache[0])
        try:
            for layer, current_cache in zip(inner.layers, cache):
                h = layer(h, mask, current_cache)
            mx.eval(h, *[array for item in cache
                         for array in (item.keys, item.values)])
        except Exception as error:  # noqa: BLE001
            raise ModelForwardRepresentationError(
                "prefix forward failed: %s" % error) from error
        return cache

    def _guarded(self, fn):
        """Run ``fn`` but fail closed on any non-Representation error.

        An underlying model/tokenizer fault must surface as the explicit
        ``ModelForwardRepresentationError`` fault class, never as a dirty
        result (SCN-60-2 "模型错误").
        """
        try:
            return fn()
        except RepresentationError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed on any fault
            raise ModelForwardRepresentationError(
                "representation generation failed: %s" % error) from error

    def _final_validate(self, vector):
        """Boundary check before a vector may leave the extractor.

        The real forward already L2-normalizes and rejects non-finite values;
        this idempotent pass makes the "no silent dirty vector" guarantee
        airtight even if a hypothetical forward bug bypassed the inner check
        (SCN-60-2). Re-normalizing an already-unit vector is a no-op for
        exact equality (dividing by a value whose square-sum is exactly 1.0).
        """
        return l2_normalize(vector)

    # -- generation paths --------------------------------------------------

    def exact(self, spec, context):
        """One standalone exact representation (AC60-1).

        A single deterministic forward over ``encode(last N chars)``;
        invalid specs, empty windows, model faults and non-finite vectors all
        fail closed through ``RepresentationError`` subclasses.
        """
        if not isinstance(spec, RepresentationSpec):
            raise InvalidRepresentationSpec("exact requires a RepresentationSpec")
        if spec.kind != "exact":
            raise InvalidRepresentationSpec(
                "exact() requires an exact spec, got %r" % spec.kind)
        self._require_model()
        tokenizer = self._tokenizer()
        _, ids = exact_tokenization_for(
            tokenizer, context, spec.window_chars, spec=spec)
        snapshots, _ = self._guarded(
            lambda: self._run(ids, None, {spec.layer}))
        return self._final_validate(snapshots[spec.layer])

    def exact_all(self, context):
        """All pre-declared exact layers from one forward.

        Returns ``{layer_number: vector}`` for the exact L14/L21/L28
        candidates; any fault fails the whole call.
        """
        self._require_model()
        tokenizer = self._tokenizer()
        _, ids = exact_tokenization_for(tokenizer, context)
        snapshots, _ = self._guarded(
            lambda: self._run(ids, None, set(EXACT_LAYERS)))
        return {layer: self._final_validate(snapshot)
                for layer, snapshot in snapshots.items()}

    def split_reuse(self, context, prefix_cache=None):
        """The pre-declared split-reuse representation (AC60-2).

        Reuses the scoring seam: tokenized prefix + tokenized tail, with the
        prefix KV cache reused. ``prefix_cache`` may be supplied by the caller
        (the batched-reuse path builds it once in the scoring batch, then the
        representation only pays the tail forward); when omitted a fresh
        prefix cache is built here. Returns ``(vector, cache)`` where
        ``cache`` is the prompt-cache list used. The tail forward advances the
        supplied cache past the tail tokens, so a caller that wants to reuse a
        prefix cache across rounds must provide a fresh clone at the prefix
        offset per round (see ``integration_hidden_state.py``).
        """
        self._require_model()
        tokenizer = self._tokenizer()
        _, prefix_ids, _, tail_ids = split_tokenization_for(
            tokenizer, context)
        if prefix_cache is None:
            prefix_cache = self._guarded(
                lambda: self._forward_prefix(prefix_ids))
        snapshots, cache = self._guarded(
            lambda: self._run(tail_ids, prefix_cache, {SPLIT_REUSE_LAYER}))
        return self._final_validate(snapshots[SPLIT_REUSE_LAYER]), cache

    def _run_candidate_layers(self, ids, candidate_start, candidate_count,
                               layer_numbers, pooling):
        """Forward one candidate payload and pool the requested layers."""
        mx, create_attention_mask, _ = _lazy_mlx()
        if not ids:
            raise EmptyContextRepresentationError("no candidate payload tokens")
        if candidate_count < 1 or candidate_start < 0 \
                or candidate_start + candidate_count > len(ids):
            raise InvalidRepresentationSpec("candidate token span is invalid")
        model, inner = self._require_model()
        del model
        token_ids = mx.array([list(ids)])
        h = inner.embed_tokens(token_ids)
        layer_cache = [None] * len(inner.layers)
        mask = create_attention_mask(h, layer_cache[0])
        wanted = set(layer_numbers)
        if not wanted:
            raise InvalidRepresentationSpec("candidate layer set is empty")
        snapshots = {}
        try:
            for index, layer in enumerate(inner.layers):
                h = layer(h, mask, layer_cache[index])
                layer_number = index + 1
                if layer_number not in wanted:
                    continue
                normalized = inner.norm(h).astype(mx.float32)
                import numpy as np
                span = np.asarray(
                    normalized[0, candidate_start:
                               candidate_start + candidate_count]).reshape(
                                   candidate_count, -1)
                snapshots[layer_number] = pool_candidate_hidden_states(
                    span.tolist(), 0, candidate_count, pooling)
            if len(snapshots) != len(wanted):
                raise InvalidRepresentationSpec(
                    "candidate layers were not all reached")
            return snapshots
        except RepresentationError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise ModelForwardRepresentationError(
                "candidate-conditioned forward failed: %s" % error) from error

    def candidate(self, spec, preceding_text, candidate):
        """Generate one frozen candidate-conditioned route vector."""
        if not isinstance(spec, CandidateRepresentationSpec):
            raise InvalidRepresentationSpec(
                "candidate requires a CandidateRepresentationSpec")
        self._require_model()
        tokenizer = self._tokenizer()
        _, ids, start, count = candidate_tokenization_for(
            tokenizer, preceding_text, candidate,
            spec.window_chars, spec=spec)
        return self._guarded(lambda: self._run_candidate_layers(
            ids, start, count, (spec.layer,), spec.pooling)[spec.layer])

    def candidate_span_mean_all(self, preceding_text, candidate):
        """Generate the three AC-109 span-mean vectors in one forward."""
        specs = tuple(spec for spec in candidate_conditioned_specs()
                      if spec.pooling == "candidate_span_mean")
        if tuple(spec.layer for spec in specs) != (14, 21, 28):
            raise InvalidRepresentationSpec(
                "AC-109 span-mean source set changed")
        self._require_model()
        tokenizer = self._tokenizer()
        _, ids, start, count = candidate_tokenization_for(
            tokenizer, preceding_text, candidate, spec=specs[0])
        return self._guarded(lambda: self._run_candidate_layers(
            ids, start, count, tuple(spec.layer for spec in specs),
            "candidate_span_mean"))


class HiddenStateRepresentationProvider(RepresentationProvider):
    """One pre-declared representation behind the #61 provider seam (#62).

    The generation path's real provider: ``event_vector`` recomputes the
    event representation from the event's raw ``preceding_text`` (facts are
    the only source of raw text; the generation stores vectors only),
    ``query_vector`` computes the same representation for request text, and
    ``representation_id`` is the extractor's deterministic id for the bound
    spec.  Any representation fault (empty window, model forward failure,
    non-finite vector) surfaces as ``EvidenceError(representation_fault)``
    so the #62 builder blocks the build naming the event (SCN-62-7).
    """

    def __init__(self, extractor, spec):
        if not isinstance(spec, RepresentationSpec):
            raise InvalidRepresentationSpec(
                "spec must be a RepresentationSpec")
        self._extractor = extractor
        self._spec = spec

    def representation_id(self):
        return self._extractor.representation_id(self._spec)

    def query_vector(self, preceding_text):
        return self._forward(preceding_text)

    def event_vector(self, event):
        return self._forward(event.preceding_text)

    def vector_dimension(self):
        return self._extractor.identity.hidden_dim

    def _forward(self, context):
        try:
            if self._spec.kind == "exact":
                return self._extractor.exact(self._spec, context)
            return self._extractor.split_reuse(context)[0]
        except EvidenceError:
            raise
        except RepresentationError as error:
            raise EvidenceError(
                "representation_fault", "representation failed: %s" % error
            ) from error


class HiddenStateCandidateRepresentationProvider(RepresentationProvider):
    """Candidate-conditioned provider for one frozen Qwen route."""

    def __init__(self, extractor, spec):
        if not isinstance(spec, CandidateRepresentationSpec):
            raise InvalidRepresentationSpec(
                "spec must be a CandidateRepresentationSpec")
        self._extractor = extractor
        self._spec = spec

    def representation_id(self):
        return self._extractor.representation_id(self._spec)

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        raise EvidenceError(
            "representation_fault",
            "candidate-conditioned query requires a candidate")

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._forward(preceding_text, candidate)

    def event_vector(self, event):
        return self.event_vector_for_candidate(
            event, event.final_selection_text)

    def event_vector_for_candidate(self, event, candidate):
        if candidate != event.final_selection_text:
            raise EvidenceError(
                "representation_fault",
                "event vector candidate does not match selection")
        return self._forward(event.preceding_text, candidate)

    def vector_dimension(self):
        return self._extractor.identity.hidden_dim

    def _forward(self, preceding_text, candidate):
        try:
            return self._extractor.candidate(
                self._spec, preceding_text, candidate)
        except EvidenceError:
            raise
        except RepresentationError as error:
            raise EvidenceError(
                "representation_fault", "representation failed: %s" % error
            ) from error
