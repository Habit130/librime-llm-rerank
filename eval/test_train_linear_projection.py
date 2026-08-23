#!/usr/bin/env python3
"""Model-free tests for AC-111 prefix, pair, and deterministic fit seams."""

import hashlib
import os
import sys
import unittest
from types import SimpleNamespace

import numpy as np

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import train_linear_projection as trainer  # noqa: E402


def event(event_id, selection, hlc, key="same"):
    return SimpleNamespace(
        event_id=event_id,
        commit_id="commit-" + event_id,
        schema_id="luna_pinyin",
        category="word",
        canonical_segment_input=key,
        final_selection_text=selection,
        preceding_text="context-" + event_id,
        hlc=hlc,
        competition=("a", "b", "c"),
        retracted=False,
        key=("luna_pinyin", "word", key),
    )


class TrainingContractTest(unittest.TestCase):

    def test_pairs_have_only_frozen_labels(self):
        events = (event("a1", "a", (1, 0)), event("a2", "a", (2, 0)),
                  event("b1", "b", (3, 0)), event("b2", "b", (4, 0)))
        positives, negatives = trainer._all_pairs(events)
        self.assertEqual(2, len(positives))
        self.assertEqual(4, len(negatives))
        self.assertTrue(all(pair.label == 1 for pair in positives))
        self.assertTrue(all(pair.label == -1 for pair in negatives))
        self.assertTrue(all(pair.left_event_id != pair.right_event_id
                            for pair in positives + negatives))

    def test_empty_preceding_is_not_excluded_for_candidate_routes(self):
        candidate_event = event("empty", "a", (1, 0))
        candidate_event.preceding_text = ""
        self.assertTrue(trainer._event_is_replayable(candidate_event))

    def test_feature_concat_requires_three_unit_sources(self):
        source = np.zeros(1024, dtype=np.float32)
        source[0] = 1.0
        result = trainer.concatenate_source_vectors((source, source, source))
        self.assertEqual((3072,), result.shape)
        with self.assertRaises(trainer.TrainingError):
            trainer.concatenate_source_vectors((source, source))

    def test_fit_is_replayable_with_same_seed(self):
        events = tuple(event("e%d" % index, "a" if index % 2 else "b",
                             (index + 1, 0)) for index in range(8))
        construction = trainer.build_pairs(events, split_fraction=0.75,
                                           max_pairs_per_class=16)
        rng = np.random.default_rng(3)
        features = {
            item.event_id: rng.standard_normal(3072).astype(np.float32)
            for item in events
        }
        first, first_fit = trainer.fit_weights(
            features, construction.train_pairs, construction.validation_pairs,
            seed=trainer.SEED, max_epochs=3, patience=2)
        second, second_fit = trainer.fit_weights(
            features, construction.train_pairs, construction.validation_pairs,
            seed=trainer.SEED, max_epochs=3, patience=2)
        self.assertEqual(hashlib.sha256(first.tobytes()).hexdigest(),
                         hashlib.sha256(second.tobytes()).hexdigest())
        self.assertEqual(first_fit, second_fit)

    def test_training_code_does_not_reference_v2_driver(self):
        source_path = __file__.replace("test_train_linear_projection.py",
                                       "train_linear_projection.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("semantic_benchmark_v2", source)


if __name__ == "__main__":
    unittest.main()
