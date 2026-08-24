#!/usr/bin/env python3
"""Model-free tests for public-layer A pairwise selection (Squirrel #154)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from public_layer_a import (  # noqa: E402
    CONTRACT_ID,
    PAIR_SET_RULE,
    PINNED_SLICE_DIGEST,
    ROUTE_IDS,
    TIE_TERMINAL,
    PublicLayerAError,
    apply_scores,
    build_freeze,
    build_report,
    expand_a_pairs,
    pair_hit,
    score_pairs,
    select_winner,
    verify_committed_digest,
    write_freeze,
)
from public_layer_slicer import (  # noqa: E402
    Lexicon,
    scan_privacy,
    slice_document,
)


FIXTURE_DICT = """---
name: luna_pinyin
...
形	xing
式	shi
刑	xing
事	shi
的	de
地	de
得	de
"""

FIXTURE_ESSAY = """形式	100
刑事	100
行事	10
"""


def fixture_lexicon():
    return Lexicon.from_texts(FIXTURE_DICT, FIXTURE_ESSAY)


def fixture_a_slices():
    lex = fixture_lexicon()
    text = "前文提到形式和内容。"
    return slice_document(
        text, lex, repo="rust-lang-cn/book-cn", path="a.md",
        source_sha="cde74c448e301ce8ac7960a0d3dc879efd83635d",
        spdx="Apache-2.0 / MIT", split="A")


def fixture_b_slices():
    lex = fixture_lexicon()
    text = "后文还有形式存在。"
    return slice_document(
        text, lex, repo="vuejs-translations/docs-zh-cn", path="b.md",
        source_sha="cfb9e9c56f112964021f9f5246bd1e65a6b15088",
        spdx="CC-BY-4.0", split="B")


def fixture_fingerprints():
    return {route_id: "fixture-fp-%s" % route_id for route_id in ROUTE_IDS}


class RouteSetTest(unittest.TestCase):
    def test_exactly_three_frozen_route_ids(self):
        self.assertEqual(
            (
                "dedicated_qwen3_embedding_0_6b",
                "dedicated_bge_m3",
                "qwen_l28_candidate_span_mean",
            ),
            ROUTE_IDS,
        )
        self.assertEqual(3, len(set(ROUTE_IDS)))
        self.assertNotIn("qwen_l14_candidate_span_mean", ROUTE_IDS)
        self.assertNotIn("qwen_global_l14_l21_l28_projection_3072_to_256",
                         ROUTE_IDS)


class PairSetTest(unittest.TestCase):
    def test_expands_every_a_slice_and_drops_b(self):
        a_slices = fixture_a_slices()
        mixed = a_slices + fixture_b_slices()
        pairs = expand_a_pairs(mixed, fixture_lexicon())
        self.assertTrue(pairs)
        self.assertTrue(all(pair.split == "A" for pair in pairs))
        self.assertTrue(all(pair.competitor != pair.target for pair in pairs))
        self.assertEqual(
            {(s["repo"], s["path"], s["start"], s["end"], s["target"],
              s["canonical_input"]) for s in a_slices},
            {(p.repo, p.path, p.start, p.end, p.target, p.canonical_input)
             for p in pairs},
        )
        self.assertFalse(any(p.repo.startswith("vuejs") for p in pairs))
        self.assertTrue(all(len(pair.target) >= 2 for pair in pairs))

    def test_pair_sets_are_identical_across_routes(self):
        pairs = expand_a_pairs(fixture_a_slices(), fixture_lexicon())
        keys = tuple(pair.key() for pair in pairs)
        self.assertEqual(len(keys), len(set(keys)))
        per_route = {route_id: keys for route_id in ROUTE_IDS}
        self.assertEqual(1, len(set(per_route.values())))

    def test_does_not_subsample_supplied_a_slices(self):
        lex = fixture_lexicon()
        first = fixture_a_slices()
        extra = slice_document(
            "另文也有形式出现。", lex, repo="Go-zh/go", path="c.md",
            source_sha="d4e8cec7338bde4c8396df6b642f991199d92186",
            spdx="BSD-3-Clause", split="A")
        pairs = expand_a_pairs(first + extra, lex)
        repos = {pair.repo for pair in pairs}
        self.assertEqual(
            {"rust-lang-cn/book-cn", "Go-zh/go"}, repos)

    def test_excludes_single_char_targets_and_keeps_multichar(self):
        lex = fixture_lexicon()
        text = "前文提到的形式可以。"
        mixed = slice_document(
            text, lex, repo="rust-lang-cn/book-cn", path="a.md",
            source_sha="cde74c448e301ce8ac7960a0d3dc879efd83635d",
            spdx="Apache-2.0 / MIT", split="A")
        targets = {record["target"] for record in mixed}
        self.assertTrue({"的", "形式"} <= targets)
        pairs = expand_a_pairs(mixed, lex)
        self.assertTrue(pairs)
        self.assertTrue(all(len(pair.target) >= 2 for pair in pairs))
        self.assertNotIn("的", {pair.target for pair in pairs})
        self.assertIn("形式", {pair.target for pair in pairs})


class PairwiseRuleTest(unittest.TestCase):
    def test_hit_is_strict_self_cosine_greater_than_cross(self):
        target = (1.0, 0.0, 0.0)
        other = (0.0, 1.0, 0.0)
        self.assertTrue(pair_hit(target, other))
        self.assertFalse(pair_hit(target, target))
        self.assertFalse(pair_hit(target, (1.0, 0.0, 0.0)))

    def test_missing_or_nonfinite_vectors_are_misses(self):
        target = (1.0, 0.0)
        self.assertFalse(pair_hit(None, target))
        self.assertFalse(pair_hit(target, None))
        self.assertFalse(pair_hit((float("nan"), 0.0), target))

    def test_score_pairs_uses_gold_as_query(self):
        pairs = expand_a_pairs(fixture_a_slices(), fixture_lexicon())
        preceding = {pair.key(): "前文提到" for pair in pairs}

        def encode(text, candidate):
            del text
            if candidate == "形式":
                return (1.0, 0.0, 0.0)
            return (0.0, 1.0, 0.0)

        hits = score_pairs(pairs, preceding.__getitem__, encode)
        self.assertEqual(len(pairs), hits)

        def collide(text, candidate):
            del text, candidate
            return (1.0, 0.0, 0.0)

        self.assertEqual(0, score_pairs(pairs, preceding.__getitem__, collide))


class WinnerRuleTest(unittest.TestCase):
    def test_unique_max_hit_count_wins(self):
        self.assertEqual(
            "dedicated_bge_m3",
            select_winner({
                "dedicated_qwen3_embedding_0_6b": 3,
                "dedicated_bge_m3": 5,
                "qwen_l28_candidate_span_mean": 4,
            }),
        )

    def test_tie_is_no_unique_winner_and_name_does_not_break_it(self):
        tied = {
            "dedicated_bge_m3": 9,
            "dedicated_qwen3_embedding_0_6b": 9,
            "qwen_l28_candidate_span_mean": 8,
        }
        self.assertEqual(TIE_TERMINAL, select_winner(tied))
        self.assertEqual("无唯一 A 赢家", TIE_TERMINAL)
        self.assertNotEqual(
            sorted(tied)[0],
            select_winner(tied),
        )


class FreezeAndReportTest(unittest.TestCase):
    def test_freeze_must_precede_scores_and_is_one_shot(self):
        freeze = build_freeze(
            slice_digest=PINNED_SLICE_DIGEST,
            code_sha="abc123",
            fingerprints=fixture_fingerprints(),
            pair_count=4,
            eligible_slice_count=2,
        )
        self.assertEqual(CONTRACT_ID, freeze["contract"])
        self.assertEqual("AC-154-v2", CONTRACT_ID)
        self.assertEqual(PAIR_SET_RULE, freeze["pair_set_rule"])
        self.assertEqual(PINNED_SLICE_DIGEST, freeze["slice_digest"])
        self.assertEqual(0, freeze["b_pairs"])
        self.assertEqual(0, freeze["len1_pairs_scored"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            freeze_path = write_freeze(root, freeze)
            scores = {route_id: 4 for route_id in ROUTE_IDS}
            report = apply_scores(root, freeze, scores)
            self.assertEqual(TIE_TERMINAL, report["winner"])
            with self.assertRaises(PublicLayerAError):
                apply_scores(root, freeze, scores)
            with self.assertRaises(PublicLayerAError):
                write_freeze(root, freeze)
            self.assertTrue(freeze_path.exists())

    def test_apply_scores_without_freeze_fails(self):
        freeze = build_freeze(
            slice_digest=PINNED_SLICE_DIGEST,
            code_sha="abc123",
            fingerprints=fixture_fingerprints(),
            pair_count=1,
            eligible_slice_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PublicLayerAError):
                apply_scores(Path(tmp), freeze, {ROUTE_IDS[0]: 1})

    def test_report_fields_and_privacy(self):
        freeze = build_freeze(
            slice_digest=PINNED_SLICE_DIGEST,
            code_sha="def456",
            fingerprints=fixture_fingerprints(),
            pair_count=10,
            eligible_slice_count=3,
        )
        report = build_report(freeze, {
            "dedicated_qwen3_embedding_0_6b": 10,
            "dedicated_bge_m3": 9,
            "qwen_l28_candidate_span_mean": 8,
        })
        self.assertEqual("dedicated_qwen3_embedding_0_6b", report["winner"])
        self.assertFalse(report["b_used_to_pick"])
        self.assertEqual(0, report["b_pairs_scored"])
        self.assertEqual(10, report["pair_count"])
        self.assertEqual(3, report["eligible_slice_count"])
        self.assertEqual(0, report["len1_pairs_scored"])
        self.assertEqual(PAIR_SET_RULE, report["pair_set_rule"])
        for route_id in ROUTE_IDS:
            row = report["routes"][route_id]
            self.assertEqual(10, row["pairs"])
            self.assertIn("hits", row)
            self.assertIn("accuracy", row)
            self.assertIn("fingerprint", row)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("前文", serialized)
        self.assertNotIn("形式", serialized)
        self.assertEqual([], scan_privacy(report))
        self.assertNotIn("alpha", serialized)
        self.assertNotIn("gamma", serialized)

    def test_committed_digest_pin(self):
        digest = verify_committed_digest()
        self.assertEqual(PINNED_SLICE_DIGEST, digest)

    def test_eval_readme_says_a_selects_and_b_owns_70(self):
        text = (Path(__file__).resolve().parent / "README.md").read_text(
            encoding="utf-8")
        self.assertIn("A only selects", text)
        self.assertIn("len≥2", text)
        self.assertIn("#156", text)
        self.assertIn("70%", text)
        self.assertIn("demoted", text)
        self.assertIn("same length rule", text)


if __name__ == "__main__":
    unittest.main()
