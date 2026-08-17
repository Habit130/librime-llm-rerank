#!/usr/bin/env python3
"""Deterministic fixed-seed vector provider (Habit130/squirrel#71).

The #61 representation seam injects the daemon's evidence representation.
The existing ``FixtureRepresentationProvider`` requires an explicit
query/event vector dictionary, which cannot scale to the #71 100k-event
capacity fixtures (a 100k x 1024-dict would be hundreds of MB of JSON).
This module adds the ``provider_kind: "seed_vectors"`` branch to the same
seam: vectors are generated from a fixed seed with a documented rule, so
both 100k fixtures (realistic key-frequency distribution and single-hot-key
worst case) can be served by the real daemon over the full IPC path.

Vector generation rule (documented, deterministic, reproducible):

  - seed: a fixed integer, recorded in the report package.
  - event vector: ``normalize(prng(seed, "event", event_id))``
  - query vector: ``normalize(prng(seed, "query", preceding_text))``
  - ``prng`` is a splitmix64 counter-based PRNG (pure Python, platform
    independent) expanded to ``vector_dimension`` float32 values in
    [-1, 1) and L2-normalized to unit norm.
  - The cosine structure is intentionally pseudo-random (mean ~0), so the
    fixture exercises the full oracle loop (every same-key active event is
    evaluated: cosine, threshold, age, weight) with the same cost profile
    as real vectors.  Zero-evidence queries remain successful results;
    latency is independent of the cosine values.

The provider is model-free and stdlib-only.  It exists only to serve the
capacity fixtures; the production representation stays the #60 hidden-state
seam.
"""

import hashlib
import math
import os
import struct

from evidence import EvidenceError, RepresentationProvider

PROVIDER_KIND = "seed_vectors"
VECTOR_RULE = "seed-vectors-v1:splitmix64:l2"
DEFAULT_DIMENSION = 1024  # Qwen3-0.6B hidden size; the real exact path cost


class SeedVectorProvider(RepresentationProvider):
    """Deterministic fixed-seed representation for capacity fixtures.

    ``event_vector`` is a pure function of ``(seed, kind, key)``; the
    generation build calls it once per stored event and the built FP32
    container serves query-time reads from mmap exactly like production.
    """

    def __init__(self, representation_id, seed, vector_dimension=None):
        if not representation_id or not isinstance(representation_id, str):
            raise EvidenceError("representation_fault",
                                "seed provider needs a representation_id")
        try:
            seed = int(seed)
            vector_dimension = (DEFAULT_DIMENSION if vector_dimension is None
                                else int(vector_dimension))
        except (TypeError, ValueError) as error:
            raise EvidenceError("representation_fault",
                                "seed/dimension must be integers: %s"
                                % error) from error
        if vector_dimension < 1:
            raise EvidenceError("representation_fault",
                                "vector_dimension must be >= 1")
        self._representation_id = representation_id
        self._seed = seed
        self._dimension = vector_dimension

    def representation_id(self):
        return self._representation_id

    def vector_dimension(self):
        return self._dimension

    def query_vector(self, preceding_text):
        return _vector(self._seed, "query", preceding_text, self._dimension)

    def event_vector(self, event):
        # The event id is the deterministic identity of a stored fact; the
        # raw preceding text is not part of the rule (the fixture vector is
        # a property of the fact, reproducible from the stored row alone).
        return _vector(self._seed, "event", event.event_id, self._dimension)

    def config_summary(self):
        return {
            "provider_kind": PROVIDER_KIND,
            "vector_rule": VECTOR_RULE,
            "seed": self._seed,
            "vector_dimension": self._dimension,
        }


def _mix64(value):
    """splitmix64 finalizer: deterministic, platform independent."""
    value = (value + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return value ^ (value >> 31)


def _vector(seed, kind, key, dimension):
    """One L2-normalized deterministic vector from (seed, kind, key)."""
    material = "%d:%s:%s" % (seed, kind, key)
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    state = int.from_bytes(digest[:8], "little")
    values = []
    for _ in range(dimension):
        state = _mix64(state)
        # float32 in [-1, 1): use the low 24 bits as a 24-bit fraction.
        fraction = (state & 0xFFFFFF) / float(0x1000000)
        values.append(2.0 * fraction - 1.0)
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0 or not math.isfinite(norm):
        raise EvidenceError("representation_fault",
                            "seed vector produced a non-normalizable vector")
    return tuple(value / norm for value in values)


def build_seed_provider_from_config(config, representation_id=None,
                                    seed=None):
    """Construct a SeedVectorProvider from the evidence config dict.

    Recognized keys: ``representation_id`` (required unless overridden),
    ``seed`` (required unless overridden), ``vector_dimension`` (default
    1024).  Raises EvidenceError on malformed input (fail closed, never a
    silently different representation).  The optional overrides let the
    desired (staging) seam construct a different representation than the
    active one from the same config shape.
    """
    try:
        representation_id = representation_id or config["representation_id"]
        seed = seed if seed is not None else config["seed"]
    except (KeyError, TypeError) as error:
        raise EvidenceError(
            "evidence_unavailable",
            "seed_vectors provider needs representation_id and seed: %s"
            % error) from error
    dimension = config.get("vector_dimension", DEFAULT_DIMENSION)
    return SeedVectorProvider(representation_id, seed, dimension)
