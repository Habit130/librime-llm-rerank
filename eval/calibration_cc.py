#!/usr/bin/env python3
"""τ calibration for the candidate-conditioned suffix walk-forward
(Habit130/squirrel#157, AC-157-v1).

Spec #43 τ clauses applied to the #157 frozen split:

- τ is produced **only from the development prefix** (events with
  ``hlc <= [1787065441087, 0]``, inclusive) — never from the suffix claim
  set, which is reserved for the quality/safety gates (folding the suffix
  into development is a contract failure).
- There is no fractional dev-prefix ratio here: the frozen HLC cutoff IS
  the dev prefix of every route (issue #157 body).
- For each query (prefix target event), a **query-level hard negative** is
  the maximum cosine, over the same-key active history events whose final
  selection differs from the query's final selection, of the retrieval
  pair that could actually support a wrong candidate: the cosine between
  the query side of the history event's own selected candidate
  (``query_vector_for_candidate``) and the history event's document-side
  vector.  A history event whose selection matches no current-group
  candidate cannot contribute evidence and is not a hard negative.
- Only after >= 200 such queries are accumulated may τ be calibrated.
  Below that the state is **not_calibratable** and NO τ value is invented:
  the route leaves the shortlist (AC-157-3; RISK-157-3).  All three
  not_calibratable -> 无合格方案 (legal terminal).
- τ is only scanned over the pre-declared quantiles Q95 / Q97.5 / Q99 /
  Q99.5 (nearest-rank, deterministic).

No raw text is produced: the calibration only records cosines and counts.
"""

import math

import numpy as np

from oracle import match_text

from walkforward_cc import MIN_HARD_NEGATIVE_QUERIES, TAU_QUANTILES


class TauCalibrationError(Exception):
    """A true fault in τ calibration inputs."""


def query_hard_negative_cosines(replay, prefix_targets):
    """query_id -> max hard-negative cosine for every prefix target.

    For each prefix target, only history events that (a) share the choice-
    problem key, (b) are active at the target's HLC (score-first memory,
    whole commit excluded), (c) have a representable document vector, and
    (d) whose final selection differs from the target's final selection AND
    matches one of the target's current-group candidates are considered.
    The cosine is the retrieval pair ``(query side of the event's own
    selected candidate, event document vector)`` — the pair that could
    actually give the wrong candidate non-zero evidence; the largest cosine
    over them becomes the query's hard-negative value.  Queries without any
    such event contribute nothing.
    """
    result = {}
    for target in prefix_targets:
        history = replay._same_key_active(target)
        if not history:
            continue
        candidates = [match_text(c) for c in target.competition]
        target_selection = match_text(target.final_selection_text)
        values = []
        for h in history:
            selected = match_text(h.final_selection_text)
            if selected == target_selection:
                continue
            slot = next((index for index, candidate in enumerate(candidates)
                         if candidate == selected), -1)
            if slot < 0:
                continue  # this event cannot support any current candidate
            query_vector = replay._vectors.query_vector_for_candidate(
                target.preceding_text, target.competition[slot])
            event_vector = replay._vectors.event_vector(h.event_id)
            cosine = float(np.asarray(query_vector, dtype=np.float64) @
                           np.asarray(event_vector, dtype=np.float64))
            values.append(cosine)
        if not values:
            continue
        result[target.event_id] = float(max(values))
    return result


def nearest_rank_quantile(sorted_values, q):
    """Nearest-rank quantile of a sorted ascending sample."""
    if not sorted_values:
        return None
    index = int(math.ceil(q * len(sorted_values))) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[index]


def calibrate_tau(replay, prefix_targets):
    """The full τ calibration for one representation over the prefix.

    Returns a dict:

        {"state": "calibratable" | "not_calibratable",
         "queries": <count of queries with a hard-negative history>,
         "min_queries": 200,
         "quantiles": {q: value, ...}   # present only when calibratable
         "prefix_count": <prefix target count>}

    ``state`` is "not_calibratable" when fewer than 200 queries carry a
    hard-negative history; no τ value is then invented (the caller must not
    substitute a default; AC-157-3).
    """
    cosines = query_hard_negative_cosines(replay, prefix_targets)
    base = {
        "queries": len(cosines),
        "min_queries": MIN_HARD_NEGATIVE_QUERIES,
        "prefix_count": len(prefix_targets),
    }
    if len(cosines) < MIN_HARD_NEGATIVE_QUERIES:
        return dict(base, state="not_calibratable")
    sorted_values = sorted(cosines.values())
    return dict(
        base,
        state="calibratable",
        quantiles={str(q): nearest_rank_quantile(sorted_values, q)
                   for q in TAU_QUANTILES},
    )