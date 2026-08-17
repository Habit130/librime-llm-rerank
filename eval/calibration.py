#!/usr/bin/env python3
"""τ calibration protocol for the #70 walk-forward evaluation.

Spec #43 τ clauses, implemented literally:

- Each ``representation_id`` calibrates its own τ, and τ is produced **only
  from the development prefix** (the earliest ``DEV_PREFIX_RATIO`` of
  replayable target events in HLC order) — never from the rest of the
  timeline.
- For each query (target event), take the **maximum cosine** among the
  same-choice-problem historical events whose final selection differs from
  the query's final selection: that is the query-level hard-negative
  distribution (one value per query).
- Only after at least 200 such queries are accumulated may τ be calibrated.
  Below that the state is **not calibratable** and NO τ value is invented:
  the grid scan then reports the representation as un-calibrated and skips
  the τ-dependent cells (spec-consistent "未可标定" handling).
- τ is only scanned over the pre-declared quantiles Q95 / Q97.5 / Q99 /
  Q99.5 of that distribution.

The development prefix is a versioned engine constant (``DEV_PREFIX_RATIO``
= 0.7).  The quantile function is deterministic (nearest-rank on the sorted
distribution) so a re-run reproduces identical τ candidates.

No raw text is produced: the calibration only records cosines and counts.
"""

import math
import statistics

from walkforward import (DEV_PREFIX_RATIO, MIN_HARD_NEGATIVE_QUERIES,
                         TAU_QUANTILES)

import numpy as np


class TauCalibrationError(Exception):
    """A true fault in τ calibration inputs."""


def dev_prefix(targets, ratio=DEV_PREFIX_RATIO):
    """The earliest ``ratio`` of replayable target events in HLC order."""
    if not 0.0 < ratio <= 1.0:
        raise TauCalibrationError("dev-prefix ratio must be in (0, 1]")
    count = int(math.floor(len(targets) * ratio))
    return targets[:count]


def query_hard_negative_cosines(replay, prefix_targets):
    """query_id -> max cosine among same-key, different-selection history.

    For every prefix query, only historical events that (a) share the
    choice-problem key, (b) are active at the query's HLC (score-first
    memory, whole commit excluded), (c) have a representable 上文 (empty-
    上文 events are unrepresentable and provide no evidence), and (d) whose
    final selection differs from the query's final selection are
    considered; the largest cosine over them becomes the query's
    hard-negative value.  Queries without any such event contribute
    nothing (they are not "queries with a hard-negative history").
    """
    result = {}
    for target in prefix_targets:
        history = replay._same_key_active(target)
        query_vector = replay._vectors.query_vector(target.event_id)
        event_vectors = []
        for h in history:
            if h.final_selection_text == target.final_selection_text:
                continue
            vector = replay._vectors.event_vector(h.event_id)
            if vector is None:
                continue
            event_vectors.append(vector)
        if not event_vectors:
            continue
        from walkforward import _fast_cosine_matrix
        cosines = _fast_cosine_matrix([query_vector], event_vectors)[0]
        result[target.event_id] = float(np.max(cosines))
    return result


def nearest_rank_quantile(sorted_values, q):
    """Nearest-rank quantile of a sorted ascending sample."""
    if not sorted_values:
        return None
    index = int(math.ceil(q * len(sorted_values))) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[index]


def calibrate_tau(replay):
    """The full τ calibration for one representation.

    Returns a dict:

        {"state": "calibratable" | "not_calibratable",
         "queries": <count of queries with a hard-negative history>,
         "min_queries": 200,
         "quantiles": {q: value, ...}   # present only when calibratable
         "prefix_count": <dev-prefix target count>,
         "prefix_ratio": 0.7}

    ``state`` is "not_calibratable" when fewer than 200 queries carry a
    hard-negative history; no τ value is then invented (the caller must not
    substitute a default).
    """
    targets = replay.targets()
    prefix = dev_prefix(targets)
    cosines = query_hard_negative_cosines(replay, prefix)
    if len(cosines) < MIN_HARD_NEGATIVE_QUERIES:
        return {
            "state": "not_calibratable",
            "queries": len(cosines),
            "min_queries": MIN_HARD_NEGATIVE_QUERIES,
            "prefix_count": len(prefix),
            "prefix_ratio": DEV_PREFIX_RATIO,
        }
    sorted_values = sorted(cosines.values())
    return {
        "state": "calibratable",
        "queries": len(cosines),
        "min_queries": MIN_HARD_NEGATIVE_QUERIES,
        "prefix_count": len(prefix),
        "prefix_ratio": DEV_PREFIX_RATIO,
        "quantiles": {str(q): nearest_rank_quantile(sorted_values, q)
                      for q in TAU_QUANTILES},
    }
