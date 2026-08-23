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
from fixture_facts import SyntheticFacts  # noqa: E402


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

    def test_pair_labels_do_not_normalize_distinct_recorded_selections(self):
        events = (event("traditional", "於", (1, 0)),
                  event("simplified", "于", (2, 0)))
        positives, negatives = trainer._all_pairs(events)
        self.assertEqual([], positives)
        self.assertEqual(1, len(negatives))

    def test_split_has_no_cross_split_pairs(self):
        events = tuple(event("e%d" % index, "a", (index + 1, 0))
                       for index in range(8))
        construction = trainer.build_pairs(events, split_fraction=0.5,
                                           max_pairs_per_class=16)
        train_ids = {item.event_id for item in construction.train_events}
        validation_ids = {item.event_id
                          for item in construction.validation_events}
        for pair in construction.train_pairs:
            self.assertIn(pair.left_event_id, train_ids)
            self.assertIn(pair.right_event_id, train_ids)
        for pair in construction.validation_pairs:
            self.assertIn(pair.left_event_id, validation_ids)
            self.assertIn(pair.right_event_id, validation_ids)

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

    def test_prefix_digest_mismatch_is_rejected_before_read(self):
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "a", "a", "a", ("a",), (1000000, 0))
            with self.assertRaises(trainer.TrainingError):
                trainer.load_prefix_dataset(
                    facts.db_path, expected_snapshot_sha256="0" * 64,
                    expected_history_id=None, expected_store_epoch=None,
                    cutoff=(1000000, 0))
        finally:
            facts.close()

    def test_suffix_event_and_retraction_are_rejected(self):
        for retract in (False, True):
            facts = SyntheticFacts()
            try:
                facts.add_event(
                    "e1", "a", "a", "a", ("a",), (1000001, 0),
                    retract_at=(1000001, 1) if retract else None)
                expected = trainer.sha256_file(facts.db_path)
                with self.assertRaises(trainer.TrainingError):
                    trainer.load_prefix_dataset(
                        facts.db_path, expected_snapshot_sha256=expected,
                        expected_history_id=None, expected_store_epoch=None,
                        cutoff=(1000000, 0))
            finally:
                facts.close()

    def test_committed_summary_withholds_owner_paths(self):
        summary_path = os.path.join(_ROOT, "SUMMARY-linear-projection-AC111.md")
        with open(summary_path, encoding="utf-8") as handle:
            summary = handle.read()
        self.assertNotIn("facts-prefix-hlc-1787065441087.sqlite3", summary)
        self.assertNotIn("candidate-conditioned-linear.npz", summary)

    def test_training_code_does_not_reference_v2_driver(self):
        source_path = __file__.replace("test_train_linear_projection.py",
                                       "train_linear_projection.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("semantic_benchmark_v2", source)


if __name__ == "__main__":
    unittest.main()
