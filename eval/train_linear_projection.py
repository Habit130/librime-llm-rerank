#!/usr/bin/env python3
"""Deterministic AC-111-v2 prefix-only linear projection training.

This driver is intentionally separate from the walk-forward and benchmark-v2
drivers.  It accepts one already-frozen facts copy, verifies its digest before
opening it, and never takes a snapshot or opens the live facts store.

The training contract is declared by constants below before any feature or
quality value is computed:

* the eligible events are split by HLC order at 80/20 inside the prefix;
* pairs are same-key/same-selection positives and same-key/different-selection
  hard negatives, with no cross-split pairs;
* all valid pairs are enumerated, then each class is deterministically capped
  by evenly spaced HLC/key order (the cap is a sampling decision);
* full-batch cosine pair loss, no bias, a negative margin, and L2 weight
  regularization are optimized with a fixed seed;
* validation loss with fixed patience selects the stop epoch, never a suffix
  event or a v2 quality metric.

The raw preceding text, candidate text, features, and matrix are process-local
or written below an ignored ``.local-work`` directory.  Only the summary is
intended for version control.
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
_LOCAL_OUTPUT_ROOT = (_ROOT / ".local-work").resolve()
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))

from linear_projection import (  # noqa: E402
    INPUT_DIMENSION,
    METRIC,
    OUTPUT_DIMENSION,
    VECTOR_FORMAT,
    LinearProjection,
    ProjectionError,
    projection_metadata_with_fingerprint,
)
from oracle import match_text  # noqa: E402
from snapshot import sha256_file  # noqa: E402
from walkforward import FrozenFacts  # noqa: E402


CONTRACT_ID = "AC-111-v2"
CONFIRMED_SNAPSHOT_PATH = (
    "/Users/habit/Developer/librime-llm-rerank/.local-work/ac111-prefix/"
    "facts-prefix-hlc-1787065441087.sqlite3"
)
PREFIX_SHA256 = (
    "ce69b7292a92cf6a64c24c512d843250cfdd2a3c837c3772b277bae686709be7"
)
PREFIX_HISTORY_ID = "dc3ffbf1a21957e0bb4ceed535c9df56"
PREFIX_STORE_EPOCH = "8407bd6b456ba5c5a526b4b95951bac3"
HLC_CUTOFF = (1787065441087, 0)

# Frozen training declarations.  Do not edit these after looking at a metric.
SPLIT_FRACTION = 0.80
PAIR_SAMPLING = "all-valid-pairs-then-evenly-spaced-class-cap"
MAX_PAIRS_PER_CLASS = 1024
LOSS_NAME = "class-balanced-cosine-positive-and-negative-margin-hinge"
NEGATIVE_MARGIN = 0.20
LEARNING_RATE = 0.05
L2_LAMBDA = 1.0e-4
SEED = 20260822
MAX_EPOCHS = 120
EARLY_STOP_PATIENCE = 20
EARLY_STOP_MIN_DELTA = 1.0e-8
BATCHING = "full-batch"
BIAS = "none"

SOURCE_POOLING = "candidate_span_mean"
SOURCE_LAYERS = (14, 21, 28)


class TrainingError(Exception):
    """A true prefix, pair, feature, or training fault."""


@dataclass(frozen=True)
class PrefixDataset:
    """Eligible active events and privacy-safe prefix counts."""

    events: tuple
    identity: dict
    snapshot_sha256: str
    counts: dict


@dataclass(frozen=True)
class Pair:
    """One unordered pair; label is +1 for positive and -1 for hard negative."""

    left_event_id: str
    right_event_id: str
    label: int


@dataclass(frozen=True)
class PairConstruction:
    """Raw and sampled train/validation pair sets."""

    train_events: tuple
    validation_events: tuple
    train_pairs: tuple
    validation_pairs: tuple
    counts: dict


def _is_after(left, right):
    return tuple(left) > tuple(right)


def _event_sort_key(event):
    return (tuple(event.hlc), event.event_id)


def _selection_label(event):
    """Use the recorded final-selection field for pair labels."""
    if not isinstance(event.final_selection_text, str) \
            or not event.final_selection_text:
        raise TrainingError("selection identity is malformed")
    return event.final_selection_text


def _identity_complete(event):
    required = (
        event.event_id,
        event.commit_id,
        event.schema_id,
        event.category,
        event.canonical_segment_input,
        event.final_selection_text,
    )
    if not all(isinstance(value, str) and value for value in required):
        return False
    if not isinstance(event.preceding_text, str):
        return False
    if not isinstance(event.hlc, tuple) or len(event.hlc) != 2:
        return False
    if not all(isinstance(value, int) and value >= 0 for value in event.hlc):
        return False
    return True


def _event_is_replayable(event):
    """Validate the AC-109 event inputs without requiring a model forward.

    Unlike the context-only routes, an empty preceding text is valid here:
    candidate-conditioned tokenization represents the candidate-only payload.
    """
    if not event.competition or not all(
            isinstance(candidate, str) and candidate
            for candidate in event.competition):
        return False
    try:
        selected = match_text(event.final_selection_text)
    except Exception as error:  # noqa: BLE001 - malformed facts are excluded
        raise TrainingError("selection identity is malformed") from error
    return any(match_text(candidate) == selected
               for candidate in event.competition)


def load_prefix_dataset(
        snapshot_path=CONFIRMED_SNAPSHOT_PATH,
        expected_snapshot_sha256=PREFIX_SHA256,
        expected_history_id=PREFIX_HISTORY_ID,
        expected_store_epoch=PREFIX_STORE_EPOCH,
        cutoff=HLC_CUTOFF):
    """Load only the verified prefix using ``FrozenFacts`` read-only access."""
    actual_sha256 = sha256_file(snapshot_path)
    if expected_snapshot_sha256 is not None \
            and actual_sha256 != expected_snapshot_sha256:
        raise TrainingError(
            "prefix snapshot SHA-256 mismatch: expected %s, got %s" % (
                expected_snapshot_sha256, actual_sha256))

    facts = FrozenFacts(os.path.abspath(snapshot_path))
    try:
        identity = facts.identity()
        if expected_history_id is not None \
                and identity.get("history_id") != expected_history_id:
            raise TrainingError("prefix history_id mismatch")
        if expected_store_epoch is not None \
                and identity.get("store_epoch") != expected_store_epoch:
            raise TrainingError("prefix store_epoch mismatch")
        if tuple(identity.get("max_hlc", ())) != tuple(cutoff):
            raise TrainingError("prefix max HLC does not equal the cutoff")

        retractions = facts.all_retractions()
        suffix_retractions = sum(
            1 for hlc in retractions.values() if _is_after(hlc, cutoff))
        if suffix_retractions:
            raise TrainingError("prefix contains post-cutoff retractions")

        all_events = facts.events()
        suffix_events = [event for event in all_events
                         if _is_after(event.hlc, cutoff)]
        if suffix_events:
            raise TrainingError("prefix contains post-cutoff events")

        counts = {
            "snapshot_events": len(all_events),
            "snapshot_retractions": len(retractions),
            "suffix_events": 0,
            "suffix_retractions": 0,
            "retracted_events": 0,
            "incomplete_identity": 0,
            "unreplayable_events": 0,
            "empty_preceding": 0,
        }
        eligible = []
        for event in all_events:
            if event.retracted:
                counts["retracted_events"] += 1
                continue
            if not _identity_complete(event):
                counts["incomplete_identity"] += 1
                continue
            if not _event_is_replayable(event):
                counts["unreplayable_events"] += 1
                continue
            if not event.preceding_text:
                counts["empty_preceding"] += 1
            eligible.append(event)
        eligible.sort(key=_event_sort_key)
        counts["active_events"] = len(all_events) - counts["retracted_events"]
        counts["eligible_events"] = len(eligible)
        counts["excluded_events"] = (
            counts["retracted_events"] + counts["incomplete_identity"]
            + counts["unreplayable_events"])
        return PrefixDataset(tuple(eligible), identity, actual_sha256, counts)
    finally:
        facts.close()


def _pair_sort_key(pair, event_by_id):
    left = event_by_id[pair.left_event_id]
    right = event_by_id[pair.right_event_id]
    return (_event_sort_key(left), _event_sort_key(right), pair.label)


def _all_pairs(events):
    """Enumerate only the frozen same-key pair semantics."""
    by_key = {}
    event_by_id = {event.event_id: event for event in events}
    for event in events:
        by_key.setdefault(event.key, {}).setdefault(
            _selection_label(event), []).append(event)

    positives = []
    negatives = []
    for key in sorted(by_key, key=lambda value: tuple(str(part)
                                                       for part in value)):
        selection_groups = by_key[key]
        ordered_groups = []
        for selection in sorted(selection_groups):
            group = sorted(selection_groups[selection], key=_event_sort_key)
            ordered_groups.append(group)
            positives.extend(
                Pair(left.event_id, right.event_id, 1)
                for left, right in itertools.combinations(group, 2))
        for left_group, right_group in itertools.combinations(ordered_groups, 2):
            negatives.extend(
                Pair(left.event_id, right.event_id, -1)
                for left in left_group for right in right_group)

    positives.sort(key=lambda pair: _pair_sort_key(pair, event_by_id))
    negatives.sort(key=lambda pair: _pair_sort_key(pair, event_by_id))
    return positives, negatives


def _evenly_spaced_cap(pairs, limit):
    if len(pairs) <= limit:
        return tuple(pairs)
    if limit < 1:
        return ()
    if limit == 1:
        return (pairs[0],)
    indexes = [int(round(index * (len(pairs) - 1) / (limit - 1)))
               for index in range(limit)]
    return tuple(pairs[index] for index in indexes)


def _sample_pairs(events, limit=MAX_PAIRS_PER_CLASS):
    positives, negatives = _all_pairs(events)
    sampled = tuple(
        _evenly_spaced_cap(positives, limit)
        + _evenly_spaced_cap(negatives, limit))
    return sampled, {
        "raw_positive": len(positives),
        "raw_hard_negative": len(negatives),
        "sampled_positive": sum(pair.label == 1 for pair in sampled),
        "sampled_hard_negative": sum(pair.label == -1 for pair in sampled),
    }


def build_pairs(events, split_fraction=SPLIT_FRACTION,
                max_pairs_per_class=MAX_PAIRS_PER_CLASS):
    """Split by HLC first, then build and deterministically sample pairs."""
    ordered = tuple(sorted(events, key=_event_sort_key))
    if not 0.0 < split_fraction < 1.0:
        raise TrainingError("split fraction must be between zero and one")
    split_index = int(math.floor(len(ordered) * split_fraction))
    if len(ordered) >= 2:
        split_index = min(max(split_index, 1), len(ordered) - 1)
    train_events = ordered[:split_index]
    validation_events = ordered[split_index:]
    train_pairs, train_counts = _sample_pairs(
        train_events, max_pairs_per_class)
    validation_pairs, validation_counts = _sample_pairs(
        validation_events, max_pairs_per_class)
    counts = {
        "split_fraction": split_fraction,
        "split_index": split_index,
        "train_events": len(train_events),
        "validation_events": len(validation_events),
        "max_pairs_per_class": max_pairs_per_class,
        "train": train_counts,
        "validation": validation_counts,
    }
    return PairConstruction(train_events, validation_events, train_pairs,
                            validation_pairs, counts)


def concatenate_source_vectors(vectors):
    """Validate and concatenate L2-normalized 1024-d AC-109 source vectors."""
    vectors = tuple(np.asarray(vector, dtype=np.float32).reshape(-1)
                    for vector in vectors)
    if len(vectors) != 3 or any(vector.size != 1024 for vector in vectors):
        raise TrainingError("AC-109 feature must contain three 1024-d vectors")
    for vector in vectors:
        if not bool(np.isfinite(vector).all()):
            raise TrainingError("AC-109 source vector is non-finite")
        norm = float(np.linalg.norm(vector.astype(np.float64)))
        if not math.isfinite(norm) or abs(norm - 1.0) > 1.0e-3:
            raise TrainingError("AC-109 source vector is not L2-normalized")
    result = np.concatenate(vectors).astype(np.float32)
    if result.shape != (INPUT_DIMENSION,):
        raise TrainingError("AC-111 concatenated feature dimension mismatch")
    return result


def feature_from_extractor(extractor, event):
    """Materialize one event feature through the existing AC-109 seam."""
    snapshots = extractor.candidate_span_mean_all(
        event.preceding_text, event.final_selection_text)
    if tuple(sorted(snapshots)) != SOURCE_LAYERS:
        raise TrainingError("AC-109 span-mean layer set changed")
    return concatenate_source_vectors(tuple(snapshots[layer]
                                            for layer in SOURCE_LAYERS))


def materialize_features(events, feature_function):
    """Build an in-memory event-id -> feature map; no feature is persisted."""
    result = {}
    for event in events:
        feature = np.asarray(feature_function(event), dtype=np.float32)
        if feature.shape != (INPUT_DIMENSION,):
            raise TrainingError("feature dimension mismatch for event")
        if not bool(np.isfinite(feature).all()):
            raise TrainingError("feature contains a non-finite value")
        result[event.event_id] = feature
    return result


def materialize_candidate_features(dataset, extractor):
    """Materialize representable AC-109 events and exclude seam faults.

    A candidate payload whose tokenizer cannot identify a clean candidate span
    is unreplayable under the existing AC-109 seam and is counted, not turned
    into a synthetic vector.  A model load/forward fault remains a hard error.
    """
    from representations import ModelForwardRepresentationError
    from representations import RepresentationError

    representable = []
    features = {}
    skipped = 0
    for event in dataset.events:
        try:
            feature = feature_from_extractor(extractor, event)
        except ModelForwardRepresentationError:
            raise
        except RepresentationError:
            skipped += 1
            continue
        features[event.event_id] = np.asarray(feature, dtype=np.float32)
        representable.append(event)
    if not representable:
        raise TrainingError("no AC-109-replayable events remain")
    counts = dict(dataset.counts)
    counts["representation_unreplayable"] = skipped
    counts["unreplayable_events"] += skipped
    counts["eligible_events"] = len(representable)
    counts["excluded_events"] += skipped
    return PrefixDataset(tuple(representable), dataset.identity,
                         dataset.snapshot_sha256, counts), features


def _project_rows(features, weights):
    projected = features.dot(weights.T)
    norms = np.sqrt(np.sum(projected.astype(np.float64) ** 2, axis=1))
    if not bool(np.isfinite(norms).all()) or bool((norms <= 0.0).any()):
        raise TrainingError("projection produced a zero or non-finite norm")
    return projected / norms[:, None], norms


def _pair_arrays(pairs, features):
    if not pairs:
        return None
    left = np.stack([features[pair.left_event_id] for pair in pairs])
    right = np.stack([features[pair.right_event_id] for pair in pairs])
    labels = np.asarray([pair.label for pair in pairs], dtype=np.float64)
    return left, right, labels


def _pair_loss_gradient(weights, arrays):
    left, right, labels = arrays
    left_projected, left_norms = _project_rows(left, weights)
    right_projected, right_norms = _project_rows(right, weights)
    similarities = np.sum(left_projected * right_projected, axis=1)
    positive = labels > 0
    losses = np.zeros(len(labels), dtype=np.float64)
    d_similarity = np.zeros(len(labels), dtype=np.float64)
    losses[positive] = 1.0 - similarities[positive]
    d_similarity[positive] = -1.0
    negative_active = (~positive) & (similarities > NEGATIVE_MARGIN)
    negative_error = similarities[negative_active] - NEGATIVE_MARGIN
    losses[negative_active] = negative_error ** 2
    d_similarity[negative_active] = 2.0 * negative_error

    weights_by_class = np.zeros(len(labels), dtype=np.float64)
    positive_count = int(positive.sum())
    negative_count = int((~positive).sum())
    if positive_count:
        weights_by_class[positive] = 0.5 / positive_count \
            if negative_count else 1.0 / positive_count
    if negative_count:
        weights_by_class[~positive] = 0.5 / negative_count \
            if positive_count else 1.0 / negative_count

    left_scale = (d_similarity * weights_by_class)[:, None]
    right_scale = left_scale
    left_gradient = (right_projected - similarities[:, None] * left_projected) \
        / left_norms[:, None]
    right_gradient = (left_projected - similarities[:, None] * right_projected) \
        / right_norms[:, None]
    left_gradient *= left_scale
    right_gradient *= right_scale
    gradient = left_gradient.T.dot(left) + right_gradient.T.dot(right)
    regularization_loss = L2_LAMBDA * float(np.mean(weights.astype(np.float64) ** 2))
    gradient = gradient \
        + (2.0 * L2_LAMBDA / weights.size) * weights
    loss = float(np.sum(weights_by_class * losses) + regularization_loss)
    if not math.isfinite(loss) or not bool(np.isfinite(gradient).all()):
        raise TrainingError("training loss or gradient is non-finite")
    return loss, gradient.astype(np.float32)


def fit_weights(features, pairs, validation_pairs, seed=SEED,
                max_epochs=MAX_EPOCHS, patience=EARLY_STOP_PATIENCE):
    """Fit one deterministic matrix and return it with numeric stop evidence."""
    train_arrays = _pair_arrays(pairs, features)
    if train_arrays is None:
        raise TrainingError("no training pairs remain after the frozen filters")
    validation_arrays = _pair_arrays(validation_pairs, features)
    rng = np.random.default_rng(seed)
    weights = (rng.standard_normal(
        (OUTPUT_DIMENSION, INPUT_DIMENSION)).astype(np.float32)
               / math.sqrt(INPUT_DIMENSION))
    best_weights = weights.copy()
    best_validation = float("inf")
    best_epoch = 0
    stale = 0
    last_train_loss = None
    last_validation_loss = None
    stop_reason = "max_epochs"
    for epoch in range(1, max_epochs + 1):
        train_loss, gradient = _pair_loss_gradient(weights, train_arrays)
        weights -= LEARNING_RATE * gradient
        last_train_loss, _unused = _pair_loss_gradient(weights, train_arrays)
        if validation_arrays is not None:
            last_validation_loss, _unused = _pair_loss_gradient(
                weights, validation_arrays)
            if last_validation_loss < best_validation - EARLY_STOP_MIN_DELTA:
                best_validation = last_validation_loss
                best_weights = weights.copy()
                best_epoch = epoch
                stale = 0
            else:
                stale += 1
                if stale >= patience:
                    stop_reason = "validation_patience"
                    break
        else:
            best_weights = weights.copy()
            best_epoch = epoch
    if validation_arrays is None:
        best_validation = None
    return best_weights, {
        "epochs_run": epoch,
        "best_epoch": best_epoch,
        "stop_reason": stop_reason,
        "train_loss": last_train_loss,
        "validation_loss": last_validation_loss,
        "best_validation_loss": best_validation,
    }


def training_code_digest(root=_ROOT):
    """Digest the code that defines feature materialization and projection."""
    paths = (
        ("eval/train_linear_projection.py", root / "eval/train_linear_projection.py"),
        ("daemon/linear_projection.py", root / "daemon/linear_projection.py"),
        ("daemon/hidden_state.py", root / "daemon/hidden_state.py"),
        ("daemon/representations.py", root / "daemon/representations.py"),
        ("daemon/oracle.py", root / "daemon/oracle.py"),
        ("daemon/server.py", root / "daemon/server.py"),
        ("daemon/opencc_data/TSCharacters.txt",
         root / "daemon/opencc_data/TSCharacters.txt"),
        ("daemon/opencc_data/TSPhrases.txt",
         root / "daemon/opencc_data/TSPhrases.txt"),
        ("eval/walkforward.py", root / "eval/walkforward.py"),
        ("eval/snapshot.py", root / "eval/snapshot.py"),
    )
    digest = hashlib.sha256(b"ac111-training-code-v1\n")
    for name, path in paths:
        try:
            content = path.read_bytes()
        except OSError as error:
            raise TrainingError("training code is unreadable: %s" % name) from error
        digest.update(('%s:%d:' % (name, len(content))).encode("ascii"))
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def _projection_metadata(dataset, source_ids, training_evidence, seed):
    metadata = {
        "contract": CONTRACT_ID,
        "source_representation_ids": list(source_ids),
        "training_code_digest": training_code_digest(),
        "snapshot_sha256": dataset.snapshot_sha256,
        "history_id": dataset.identity["history_id"],
        "store_epoch": dataset.identity["store_epoch"],
        "hlc_cutoff": list(HLC_CUTOFF),
        "hyperparameters": {
            "input_dim": INPUT_DIMENSION,
            "output_dim": OUTPUT_DIMENSION,
            "source_pooling": SOURCE_POOLING,
            "source_layers": list(SOURCE_LAYERS),
            "learning_rate": LEARNING_RATE,
            "negative_margin": NEGATIVE_MARGIN,
            "batching": BATCHING,
            "bias": BIAS,
        },
        "seed": seed,
        "split": {
            "policy": "time-based-HLC-event-order",
            "fraction": SPLIT_FRACTION,
            "train_events": training_evidence["pairs"]["train_events"],
            "validation_events": training_evidence["pairs"]["validation_events"],
        },
        "sampling": {
            "policy": PAIR_SAMPLING,
            "max_pairs_per_class": MAX_PAIRS_PER_CLASS,
            "with_replacement": False,
        },
        "loss": {
            "name": LOSS_NAME,
            "positive_target": 1.0,
            "negative_margin": NEGATIVE_MARGIN,
            "class_balance": "equal-class-mean",
        },
        "regularization": {
            "name": "L2-mean-weight-square",
            "lambda": L2_LAMBDA,
        },
        "stop": {
            "policy": "validation-loss-patience",
            "max_epochs": MAX_EPOCHS,
            "patience": EARLY_STOP_PATIENCE,
            "min_delta": EARLY_STOP_MIN_DELTA,
            "selected_epoch": training_evidence["fit"]["best_epoch"],
            "reason": training_evidence["fit"]["stop_reason"],
        },
        "weight_digest": training_evidence["weight_digest"],
        "input_dim": INPUT_DIMENSION,
        "output_dim": OUTPUT_DIMENSION,
        "vector_format": VECTOR_FORMAT,
        "metric": METRIC,
    }
    return projection_metadata_with_fingerprint(metadata)


def render_summary(dataset, pair_construction, fit_evidence, metadata,
                   _weight_path):
    """Render only hashes, counts, and declared numeric configuration."""
    evidence = {
        "contract": CONTRACT_ID,
        "snapshot": {
            "path": "owner-local confirmed-prefix snapshot (path withheld)",
            "sha256": dataset.snapshot_sha256,
            "history_id": dataset.identity["history_id"],
            "store_epoch": dataset.identity["store_epoch"],
            "hlc_cutoff": list(HLC_CUTOFF),
        },
        "counts": dataset.counts,
        "pairs": pair_construction.counts,
        "declarations": {
            "split": "HLC event order, 80/20, no cross-split pairs",
            "sampling": PAIR_SAMPLING,
            "loss": LOSS_NAME,
            "regularization": "L2 mean weight square",
            "seed": SEED,
            "stop": "validation loss patience 20, max 120 epochs",
            "bias": BIAS,
        },
        "fit": fit_evidence,
        "projection": {
            "fingerprint": metadata["fingerprint"],
            "weight_digest": metadata["weight_digest"],
            "source_representation_ids": metadata["source_representation_ids"],
            "training_code_digest": metadata["training_code_digest"],
            "input_dim": metadata["input_dim"],
            "output_dim": metadata["output_dim"],
            "vector_format": metadata["vector_format"],
            "metric": metadata["metric"],
        },
        "privacy": {
            "raw_preceding_text": "not committed",
            "candidate_text": "not committed",
            "vectors": "not committed",
            "projection_weights": "owner-local ignored artifact (path withheld)",
        },
        "isolation": {
            "suffix_events_read": 0,
            "v2_imported_or_run": False,
            "live_facts_opened_or_written": False,
            "new_snapshot_taken": False,
            "alpha": 0,
            "gamma": 0,
        },
    }
    return "# AC-111-v2 Linear Projection Summary\n\n```json\n%s\n```\n" % \
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)


def run_training(snapshot_path, model_path, output_dir,
                 summary_path=None, seed=SEED):
    """Materialize prefix features, fit, save local weights, and write summary."""
    if seed != SEED:
        raise TrainingError("AC-111-v2 seed is frozen at %d" % SEED)
    output_dir = str(Path(output_dir).expanduser().resolve())
    local_root = str(_LOCAL_OUTPUT_ROOT)
    if output_dir != local_root \
            and not output_dir.startswith(local_root + os.sep):
        raise TrainingError("projection weights must stay under .local-work")
    # The digest check and all prefix-boundary checks happen before model load.
    dataset = load_prefix_dataset(snapshot_path)

    from hidden_state import HiddenStateExtractor  # noqa: E402
    from server import ModelState  # noqa: E402

    state = ModelState(model_path)
    extractor = HiddenStateExtractor(state)
    from representations import candidate_conditioned_specs  # noqa: E402
    source_specs = tuple(spec for spec in candidate_conditioned_specs()
                         if spec.pooling == SOURCE_POOLING)
    if tuple(spec.layer for spec in source_specs) != SOURCE_LAYERS:
        raise TrainingError("AC-109 source route set changed")
    source_ids = tuple(extractor.representation_id(spec)
                       for spec in source_specs)

    print("prefix verified: %s" % dataset.snapshot_sha256)
    dataset, features = materialize_candidate_features(dataset, extractor)
    pair_construction = build_pairs(dataset.events)
    print("eligible events: %d; train pairs: %d; validation pairs: %d" % (
        len(dataset.events), len(pair_construction.train_pairs),
        len(pair_construction.validation_pairs)))
    weights, fit_evidence = fit_weights(
        features, pair_construction.train_pairs,
        pair_construction.validation_pairs, seed=seed)
    weight_digest = hashlib.sha256(
        np.asarray(weights, dtype="<f4", order="C").tobytes(order="C")
    ).hexdigest()
    training_evidence = {
        "pairs": {
            "train_events": pair_construction.counts["train_events"],
            "validation_events": pair_construction.counts["validation_events"],
            "train_pairs": len(pair_construction.train_pairs),
            "validation_pairs": len(pair_construction.validation_pairs),
        },
        "fit": fit_evidence,
        "weight_digest": weight_digest,
    }
    metadata = _projection_metadata(dataset, source_ids, training_evidence, seed)
    projection = LinearProjection(weights, metadata)
    os.makedirs(output_dir, exist_ok=True)
    weight_path = os.path.join(output_dir, "candidate-conditioned-linear.npz")
    projection.save(weight_path)
    if summary_path is not None:
        summary_path = os.path.abspath(summary_path)
        summary_directory = os.path.dirname(summary_path)
        if summary_directory:
            os.makedirs(summary_directory, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as handle:
            handle.write(render_summary(
                dataset, pair_construction, training_evidence, metadata,
                weight_path))
    return projection, dataset, pair_construction, fit_evidence, weight_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=CONFIRMED_SNAPSHOT_PATH)
    parser.add_argument("--model", default="/Users/habit/Models/Qwen/Qwen3-0.6B-Base")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    if args.seed != SEED:
        parser.error("AC-111-v2 seed is frozen at %d" % SEED)
    try:
        projection, _dataset, _pairs, fit, weight_path = run_training(
            args.snapshot, args.model, args.output_dir, args.summary,
            seed=args.seed)
    except (TrainingError, ProjectionError, OSError, ValueError) as error:
        print("FAIL: %s" % error)
        return 1
    print("projection fingerprint: %s" % projection.fingerprint)
    print("weight digest: %s" % projection.weight_digest)
    print("selected epoch: %s" % fit["best_epoch"])
    print("local weights: %s" % os.path.abspath(weight_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
