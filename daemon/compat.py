#!/usr/bin/env python3
"""Layered compatibility-matrix planner (Habit130/squirrel#66).

The single reuse/load authority for derived state.  Given the desired and the
active layered identities, it returns the exact action union the build path
must execute -- and refuses to load when an identity is unknown, a compat
declaration is missing, or a checksum cannot be verified.  No builder,
staging, delta, publish or open path infers compatibility from file
appearance (spec: 所有复用都必须由显式矩阵允许, builder 不得自行猜测).

Layers (spec #43 "分层兼容身份"): ``fact_schema_version`` (fact tables, event
format and HLC decodability), ``representation_id`` (model/tokenizer digest,
layer, pooling, truncation, normalization, dimension), ``vector_format_version``
(canonical FP32 file + row encoding), ``projection_version`` (active projection,
retraction, choice-problem keys, HLC metadata interpretation) and
``index_fingerprint`` (content digest of retrieval backend + metric + build
params + library version + serialization ABI).  The query-config identity
(H / gamma / k / tau / K_evidence / overfetch / ef_search) stays on the
evidence config seam (``compose_config_identity``, #61): a query-parameter-only
change is an explicit matrix no-op, never a base rebuild (AC66-6).

The matrix (spec "版本兼容矩阵"):

- ``store_epoch`` changed -> discard ALL derived state, full rebuild from
  current facts (``invalidate_all``).
- ``representation_id`` changed -> re-embed every active event into a new
  generation (``reembed``); no vector reuse.
- only ``vector_format_version`` changed -> reuse FP32 only through a
  registered converter with a deterministic byte-level / per-value
  equivalence test (``convert_vectors``); otherwise re-embed, never byte-cast.
- only ``projection_version`` changed -> rebuild the projection / choice-
  problem keys / HLC metadata from facts (``rebuild_projection``); vectors may
  be reused by event_id only when the representation is identical and the old
  vector checksum verifies (``reuse_vectors``).
- only ``index_fingerprint`` changed -> no model, no projection rebuild
  (``rebuild_index``).  In the exact-only envelope there is no ANN sidecar to
  rebuild, so the planned index-only action resolves to a no-op with reason
  ``no_ann_sidecar`` (RISK-66-1); never a silent re-embed.
- only query parameters changed -> explicit no-op for the base (``noop``).
- multi-layer change -> the action union (subsumption-collapsed: reembed
  implies fresh projection and fresh index, invalidate_all implies everything).

Unknown identity, missing compat declaration or a checksum failure refuses the
load of that derived state as a successful active generation
(``refuse_load_reason`` / SCN-66-10/12); there is no config-active fallback
for a broken/unknown active manifest.
"""

import hashlib
import json

# ---------------------------------------------------------------------------
# Identity layers
# ---------------------------------------------------------------------------

LAYER_FACT_SCHEMA = "fact_schema_version"
LAYER_REPRESENTATION = "representation_id"
LAYER_VECTOR_FORMAT = "vector_format_version"
LAYER_PROJECTION = "projection_version"
LAYER_INDEX = "index_fingerprint"
LAYER_STORE_EPOCH = "store_epoch"

# The orthogonal layers the matrix compares, in declaration order.
IDENTITY_LAYERS = (LAYER_STORE_EPOCH, LAYER_FACT_SCHEMA, LAYER_REPRESENTATION,
                   LAYER_VECTOR_FORMAT, LAYER_PROJECTION, LAYER_INDEX)

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

ACTION_INVALIDATE_ALL = "invalidate_all"
ACTION_REEMBED = "reembed"
ACTION_REBUILD_PROJECTION = "rebuild_projection"
ACTION_REUSE_VECTORS = "reuse_vectors"
ACTION_CONVERT_VECTORS = "convert_vectors"
ACTION_REBUILD_INDEX = "rebuild_index"
ACTION_NOOP = "noop"

_ACTION_LABELS = {
    ACTION_INVALIDATE_ALL:
        "store epoch changed: discard all derived state, full rebuild",
    ACTION_REEMBED:
        "representation changed: re-embed all active events",
    ACTION_REBUILD_PROJECTION:
        "projection changed: rebuild projection / keys / HLC metadata",
    ACTION_REUSE_VECTORS:
        "reuse vectors by event_id (representation identical, checksums "
        "verified)",
    ACTION_CONVERT_VECTORS:
        "reuse vectors through a registered tested-equivalent converter",
    ACTION_REBUILD_INDEX:
        "index fingerprint changed: no model, no projection rebuild",
    ACTION_NOOP:
        "query parameters changed: no base rebuild",
}

# Subsumption: an action implies (covers) the others in its frozenset.  A
# re-embedded generation carries a fresh projection and a fresh index;
# invalidate_all (full rebuild from current facts) covers every other action.
_IMPLIES = {
    ACTION_INVALIDATE_ALL: frozenset({
        ACTION_REEMBED, ACTION_REBUILD_PROJECTION, ACTION_REUSE_VECTORS,
        ACTION_CONVERT_VECTORS, ACTION_REBUILD_INDEX,
    }),
    ACTION_REEMBED: frozenset({
        ACTION_REBUILD_PROJECTION, ACTION_REUSE_VECTORS,
        ACTION_CONVERT_VECTORS, ACTION_REBUILD_INDEX,
    }),
    ACTION_CONVERT_VECTORS: frozenset({ACTION_REUSE_VECTORS}),
}

# ---------------------------------------------------------------------------
# Refuse-load reasons (SCN-66-10 / SCN-66-12)
# ---------------------------------------------------------------------------

REFUSE_MISSING_DECLARATION = "missing_compat_declaration"
REFUSE_FACT_SCHEMA_CHANGED = "fact_schema_changed"
REFUSE_UNSUPPORTED_FORMAT = "unsupported_vector_format"
REFUSE_UNSUPPORTED_BACKEND = "unsupported_retrieval_backend"
REFUSE_CHECKSUM_FAILURE = "checksum_failure"
REFUSE_UNKNOWN_IDENTITY = "unknown_identity"

# Exact-only envelope constants (the only supported backend / format / metric).
EXACT_BACKEND = "exact"
EXACT_METRIC = "cosine"
# The exact-only envelope has no ANN library; the "library version" is the
# version of the in-tree exact retrieval implementation that interprets the
# FP32 file.  A second production backend / format would change this constant
# (and thus every fingerprint) -- the seam ANN lands on in #78/#79.
EXACT_LIBRARY_VERSION = "oracle-exact-v1"
# The serialization ABI of the canonical vector file: row-major little-endian
# FP32, no header (dimension/rows live in the manifest).
FP32_ROW_MAJOR_LE = "fp32-row-major-little-endian"
INDEX_FINGERPRINT_PREFIX = "index-fingerprint-v1"

# ---------------------------------------------------------------------------
# Index fingerprint composition (content digest, never a bare string)
# ---------------------------------------------------------------------------


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _sha256_hex(content):
    return hashlib.sha256(content).hexdigest()


def compose_index_fingerprint(backend=EXACT_BACKEND, metric=EXACT_METRIC,
                              params=None, library_version=EXACT_LIBRARY_VERSION,
                              serialization_abi=FP32_ROW_MAJOR_LE):
    """Content digest of the retrieval index identity (spec: index_fingerprint
    = 检索后端 + 距离度量 + 构建参数 + 库版本 + 序列化 ABI; 不是裸的 "exact").

    ANN build parameters (ef_search, M, overfetch, ...) belong HERE, not in the
    generation identity's query layer: changing any component -- including an
    ANN build param, when one is configured -- yields a different fingerprint,
    which the matrix then treats as an index-only change (no model re-run in
    this envelope; AC66-6).
    """
    payload = _canonical_json({
        "backend": backend,
        "metric": metric,
        "build_params": params or {},
        "library_version": library_version,
        "serialization_abi": serialization_abi,
    })
    return "%s:%s" % (INDEX_FINGERPRINT_PREFIX,
                      _sha256_hex(payload.encode("utf-8"))[:32])


# ---------------------------------------------------------------------------
# Vector format converters (SCN-66-5 / SCN-66-6)
# ---------------------------------------------------------------------------


class VectorFormatConverter:
    """A registered converter between two vector formats.

    The matrix allows vector reuse through a converter ONLY when it carries a
    deterministic byte-level / per-value equivalence test
    (``verify_equivalent``) that provably preserves values -- a converter
    without a proven equivalence never permits reuse (spec: 只有逐值等价且经过
    校验的转换器可以复用旧向量).
    """

    def __init__(self, name, source_format, target_format, convert,
                 verify_equivalent):
        if not name or not isinstance(name, str):
            raise ValueError("converter name must be a non-empty string")
        if not source_format or not target_format:
            raise ValueError("converter formats must be non-empty strings")
        if not callable(convert) or not callable(verify_equivalent):
            raise ValueError("converter must provide convert and "
                             "verify_equivalent callables")
        self.name = name
        self.source_format = source_format
        self.target_format = target_format
        self.convert = convert
        self.verify_equivalent = verify_equivalent

    def key(self):
        return (self.source_format, self.target_format)


CONVERTER_REGISTRY = {}


def register_converter(converter):
    """Register one vector-format converter (idempotent for the same key)."""
    if not isinstance(converter, VectorFormatConverter):
        raise TypeError("converter must be a VectorFormatConverter")
    CONVERTER_REGISTRY[converter.key()] = converter


def find_converter(source_format, target_format, registry=None):
    """The registered converter (source -> target), or None.

    A same-format pair resolves to the identity converter, which is registered
    for the current fp32 format so the matrix has an explicit, tested
    conversion seam even in the exact-only envelope.
    """
    registry = CONVERTER_REGISTRY if registry is None else registry
    return registry.get((source_format, target_format))


# The identity converter for the current canonical format: byte-identical
# conversion with a byte-level equivalence test.  Registered so the matrix's
# converter path is exercised and pinned even before a second format exists.
register_converter(VectorFormatConverter(
    name="identity-%s" % FP32_ROW_MAJOR_LE,
    source_format=FP32_ROW_MAJOR_LE,
    target_format=FP32_ROW_MAJOR_LE,
    convert=lambda data: data,
    verify_equivalent=lambda left, right: left == right,
))


# ---------------------------------------------------------------------------
# Mismatch and refuse classification
# ---------------------------------------------------------------------------


def mismatch_reasons(desired, active):
    """Per-layer mismatch reasons between two identity dicts (privacy-clean:
    only layer names and identity values -- never raw text or embeddings)."""
    reasons = []
    for layer in IDENTITY_LAYERS:
        if desired.get(layer) != active.get(layer):
            reasons.append({
                "layer": layer,
                "desired": desired.get(layer),
                "active": active.get(layer),
                "reason": _ACTION_LABELS.get(
                    _layer_action(layer), "identity layer differs"),
            })
    return reasons


def _layer_action(layer):
    return {
        LAYER_STORE_EPOCH: ACTION_INVALIDATE_ALL,
        LAYER_REPRESENTATION: ACTION_REEMBED,
        LAYER_VECTOR_FORMAT: ACTION_CONVERT_VECTORS,
        LAYER_PROJECTION: ACTION_REBUILD_PROJECTION,
        LAYER_INDEX: ACTION_REBUILD_INDEX,
    }.get(layer)


def refuse_load_reason(active, facts_schema_version=None,
                       supported_formats=None):
    """Why the active identity cannot be loaded as a successful active
    generation, or None when it can.

    Covers the SCN-66-10 / SCN-66-12 cases that are decidable from the
    identity alone: a missing explicit compat declaration, a fact schema the
    daemon cannot decode (migration is #58, out of scope), and an unsupported
    vector format on disk.  A legacy bare-string index fingerprint (e.g.
    "exact") is an unknown identity -- it never carries the
    backend/metric/params/ABI digest this daemon compares.  A checksum
    failure is decided by the reopen verification (``open_generation`` ->
    ``GenerationRejected``) and is mapped by the caller to
    ``REFUSE_CHECKSUM_FAILURE`` -- this function stays the identity-level
    classifier and returns None for a present, well-formed identity.
    """
    if active is None:
        return REFUSE_UNKNOWN_IDENTITY
    if not isinstance(active, dict):
        return REFUSE_UNKNOWN_IDENTITY
    for layer in IDENTITY_LAYERS:
        value = active.get(layer)
        if value is None or (isinstance(value, str) and not value):
            return REFUSE_MISSING_DECLARATION
    if facts_schema_version is not None \
            and active.get(LAYER_FACT_SCHEMA) != facts_schema_version:
        return REFUSE_FACT_SCHEMA_CHANGED
    supported_formats = supported_formats or {FP32_ROW_MAJOR_LE}
    if active.get(LAYER_VECTOR_FORMAT) not in supported_formats:
        return REFUSE_UNSUPPORTED_FORMAT
    fingerprint = active.get(LAYER_INDEX, "")
    if isinstance(fingerprint, str) and not fingerprint.startswith(
            INDEX_FINGERPRINT_PREFIX + ":"):
        return REFUSE_UNKNOWN_IDENTITY
    return None


# ---------------------------------------------------------------------------
# The matrix: desired vs active -> action union
# ---------------------------------------------------------------------------


def _collapse_union(actions):
    """Subsumption-collapse a raw action set to the minimal covering union.

    ``invalidate_all`` covers everything; ``reembed`` covers fresh projection
    and fresh index; ``convert_vectors`` covers vector reuse.  The result is
    the union the builder must execute -- never a guessed smaller action
    (SCN-66-9).
    """
    working = set(actions)
    changed = True
    while changed:
        changed = False
        for action in list(working):
            for covers in list(working):
                if covers == action:
                    continue
                if action in _IMPLIES.get(covers, ()):
                    working.discard(action)
                    changed = True
                    break
    return working


def plan_actions(desired, active, converters=None,
                 facts_schema_version=None, query_identity=None):
    """The matrix decision for reaching ``desired`` from ``active``.

    ``desired`` / ``active`` are identity dicts keyed by ``IDENTITY_LAYERS``
    (missing keys are treated as an unknown identity -> refuse).  ``active``
    may be None (nothing active yet): the desired generation is built in full.

    ``query_identity`` is the evidence config identity (the #61
    ``compose_config_identity`` output on the evidence seam).  When the base
    layers are identical, a *query-parameter-only* difference is an explicit
    matrix no-op (AC66-6 / SCN-66-8) -- it never rebuilds the base, and the
    query path still fail-closes on a request naming a different identity
    (the existing ``config_identity_mismatch`` on the evidence seam).

    Returns a dict:

        actions         sorted union of action names (subsumption-collapsed)
        mismatches      per-layer mismatch reasons (privacy-clean)
        vector_reuse    "event_id" | "convert" | "none"
        refuse_load     bool
        refuse_reason   str | None
        reason          str | None (e.g. "no_ann_sidecar" for index-only)
    """
    if desired is None or not isinstance(desired, dict):
        raise ValueError("desired identity must be a dict")
    for layer in IDENTITY_LAYERS:
        if layer not in desired:
            raise ValueError("desired identity missing layer %s" % layer)

    refuse = refuse_load_reason(active, facts_schema_version=facts_schema_version)
    if refuse is not None:
        return {
            "actions": [],
            "mismatches": [{"layer": None, "reason": refuse}],
            "vector_reuse": "none",
            "refuse_load": True,
            "refuse_reason": refuse,
            "reason": None,
        }
    if active is None:
        # Nothing active yet: build the desired generation in full.
        return {
            "actions": [ACTION_REEMBED],
            "mismatches": [],
            "vector_reuse": "none",
            "refuse_load": False,
            "refuse_reason": None,
            "reason": None,
        }

    raw = set()
    vector_reuse = "none"
    reason = None
    for layer in IDENTITY_LAYERS:
        if desired[layer] == active.get(layer):
            continue
        action = _layer_action(layer)
        if action == ACTION_INVALIDATE_ALL:
            raw.add(ACTION_INVALIDATE_ALL)
        elif action == ACTION_REEMBED:
            raw.add(ACTION_REEMBED)
        elif action == ACTION_CONVERT_VECTORS:
            source = active.get(LAYER_VECTOR_FORMAT)
            target = desired[LAYER_VECTOR_FORMAT]
            registry = CONVERTER_REGISTRY if converters is None else converters
            converter = find_converter(source, target, registry)
            if converter is not None and converter.verify_equivalent:
                raw.add(ACTION_CONVERT_VECTORS)
                vector_reuse = "convert"
            else:
                # No tested equivalent converter: re-embed, never byte-cast
                # (SCN-66-5).
                raw.add(ACTION_REEMBED)
        elif action == ACTION_REBUILD_PROJECTION:
            raw.add(ACTION_REBUILD_PROJECTION)
            # Vector reuse by event_id is permitted only when the
            # representation is identical (checked here) and the old vector
            # checksum verifies (checked by the caller via reopen).
            if desired[LAYER_REPRESENTATION] == active.get(LAYER_REPRESENTATION):
                raw.add(ACTION_REUSE_VECTORS)
                vector_reuse = "event_id"
        elif action == ACTION_REBUILD_INDEX:
            raw.add(ACTION_REBUILD_INDEX)
            # Exact-only envelope: no ANN sidecar to rebuild (RISK-66-1).
            reason = "no_ann_sidecar"

    if not raw:
        # Base layers identical: the only possible difference is the query
        # config identity (kept on the evidence seam), which never rebuilds
        # the base -- an explicit matrix no-op (AC66-6 / SCN-66-8).
        raw.add(ACTION_NOOP)

    actions = sorted(_collapse_union(raw))
    return {
        "actions": actions,
        "mismatches": mismatch_reasons(desired, active),
        "vector_reuse": vector_reuse,
        "refuse_load": False,
        "refuse_reason": None,
        "reason": reason,
    }
