#!/usr/bin/env python3
"""Model-free tests for the public-layer B gate (Squirrel #156 / AC-156-v1)."""

import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from public_layer_a import (  # noqa: E402
    MAX_SCORER_RSS_BYTES,
    PINNED_SLICE_DIGEST,
    guard_scorer_rss,
    iter_compact_table,
    pair_hit,
    query_text,
    verify_committed_digest,
    write_compact_table,
)
from public_layer_b import (  # noqa: E402
    A_CONTRACT_ID,
    A_WINNER_ROUTE,
    CACHE_CONTRACT_DIR,
    COMPACT_TABLE_NAME,
    CONTRACT_ID,
    FAIL_TERMINAL,
    GATE_ACCURACY,
    MIN_TARGET_LEN,
    PAIR_SET_RULE,
    PASS_TERMINAL,
    PINNED_A_FREEZE_DIGEST,
    QUERY_RULE,
    REPORT_MD_NAME,
    SOURCE_COMPACT_TABLE_NAME,
    PublicLayerBError,
    apply_scores,
    b_pair_keys,
    build_b_compact_slices,
    build_freeze,
    build_report,
    compact_table_path,
    count_eligible_b,
    current_code_sha,
    eligible_b_slices,
    iter_b_compact_table,
    iter_b_source_compact_table,
    load_a_winner_identity,
    load_b_compact_header,
    load_freeze,
    render_report_markdown,
    report_json_path,
    score_b_pairs,
    select_verdict,
    source_compact_table_path,
    validate_freeze,
    write_b_compact_table,
    write_b_source_compact_table,
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


def fixture_rows():
    lex = fixture_lexicon()
    return build_b_compact_slices(
        fixture_b_slices(), lex, lambda record: "前文提到")


def fixture_freeze(**overrides):
    payload = dict(
        slice_digest=PINNED_SLICE_DIGEST,
        code_sha="abc123",
        a_freezer_digest=PINNED_A_FREEZE_DIGEST,
        a_winner_fingerprint="fixture-bge-fp",
        b_source_table_digest="source-digest",
        b_source_slice_count=100,
        b_source_pair_count=500,
        compact_table_digest="table-digest",
        eligible_slice_count=13,
        pair_count=63,
    )
    payload.update(overrides)
    return build_freeze(**payload)


class BContractTest(unittest.TestCase):
    def test_b_contract_is_ac156_v1(self):
        self.assertEqual("AC-156-v1", CONTRACT_ID)
        self.assertEqual("AC-154-v4", A_CONTRACT_ID)
        self.assertNotEqual(CONTRACT_ID, A_CONTRACT_ID)

    def test_pair_set_rule_marks_split_b(self):
        self.assertEqual(
            "target_len>=2;stride=8;index_mod=0;split=B", PAIR_SET_RULE)
        self.assertIn("split=B", PAIR_SET_RULE)
        self.assertEqual("ctx-as-query:last64", QUERY_RULE)

    def test_gate_is_public_70_not_tau_or_personal(self):
        self.assertEqual(0.70, GATE_ACCURACY)
        self.assertNotEqual(0.95, GATE_ACCURACY)
        self.assertEqual("dedicated_bge_m3", A_WINNER_ROUTE)


class BPairSetTest(unittest.TestCase):
    def test_pairs_cover_b_slices_and_exclude_a(self):
        lex = fixture_lexicon()
        mixed = fixture_a_slices() + fixture_b_slices()
        keys = b_pair_keys(mixed, lex)
        self.assertTrue(keys)
        self.assertTrue(all(key[0] == "vuejs-translations/docs-zh-cn"
                            for key in keys))
        self.assertTrue(all(len(key[4]) >= MIN_TARGET_LEN for key in keys))
        expected = {
            (s["repo"], s["path"], s["start"], s["end"], s["target"],
             s["canonical_input"])
            for s in eligible_b_slices(mixed)
        }
        self.assertEqual(
            expected,
            {(key[0], key[1], key[2], key[3], key[4], key[5])
             for key in keys})
        self.assertFalse(any(key[0].startswith("rust-lang") for key in keys))
        self.assertFalse(any(key[0].startswith("Go-zh") for key in keys))

    def test_zero_len1_targets_in_b_pairs(self):
        lex = fixture_lexicon()
        text = "后文的的得形式。"
        extra = slice_document(
            text, lex, repo="vuejs-translations/docs-zh-cn", path="b2.md",
            source_sha="cfb9e9c56f112964021f9f5246bd1e65a6b15088",
            spdx="CC-BY-4.0", split="B")
        keys = b_pair_keys(extra, lex)
        self.assertTrue(keys)
        self.assertTrue(all(len(key[4]) >= 2 for key in keys))

    def test_counts_match_pair_keys(self):
        lex = fixture_lexicon()
        slices = fixture_b_slices()
        slice_count, pair_count = count_eligible_b(slices, lex)
        self.assertEqual(len(eligible_b_slices(slices)), slice_count)
        self.assertEqual(len(b_pair_keys(slices, lex)), pair_count)
        self.assertGreaterEqual(slice_count, 1)
        self.assertGreaterEqual(pair_count, slice_count)

    def test_b_compact_rows_carry_sorted_competitors_only(self):
        lex = fixture_lexicon()
        rows = build_b_compact_slices(
            fixture_b_slices(), lex, lambda record: "前文提到")
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual("vuejs-translations/docs-zh-cn", row.repo)
            self.assertNotIn(row.target, row.competitors)
            self.assertEqual(tuple(sorted(row.competitors)), row.competitors)
            self.assertGreaterEqual(len(row.target), 2)

    def test_b_table_names_and_cache_dir_do_not_reuse_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".cache" / "public_layer"
            self.assertEqual("ac156", CACHE_CONTRACT_DIR)
            self.assertEqual("b_pairs_stride8.jsonl", COMPACT_TABLE_NAME)
            self.assertEqual("b_pairs.jsonl", SOURCE_COMPACT_TABLE_NAME)
            self.assertNotEqual(COMPACT_TABLE_NAME, "a_pairs_stride8.jsonl")
            self.assertEqual("ac156", compact_table_path(cache).parent.name)
            self.assertEqual(
                cache / "ac156" / "b_pairs_stride8.jsonl",
                compact_table_path(cache))
            self.assertEqual(
                cache / "ac156" / "b_pairs.jsonl",
                source_compact_table_path(cache))

    def test_b_table_round_trip_and_header(self):
        rows = fixture_rows()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".cache" / "public_layer"
            path = compact_table_path(cache)
            digest = write_b_compact_table(
                path, rows, slice_digest=PINNED_SLICE_DIGEST)
            self.assertEqual(64, len(digest))
            self.assertEqual(rows, tuple(iter_b_compact_table(path)))
            header = load_b_compact_header(path)
            self.assertEqual(CONTRACT_ID, header["contract"])
            self.assertEqual(PAIR_SET_RULE, header["pair_set_rule"])
            self.assertEqual(QUERY_RULE, header["query_rule"])
            self.assertEqual(len(rows), header["eligible_slice_count"])
            self.assertEqual(
                sum(len(row.competitors) for row in rows),
                header["pair_count"])

    def test_b_source_table_round_trip(self):
        rows = fixture_rows()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / ".cache" / "public_layer"
            path = source_compact_table_path(cache)
            digest = write_b_source_compact_table(
                path, rows, slice_digest=PINNED_SLICE_DIGEST)
            self.assertEqual(64, len(digest))
            self.assertEqual(rows, tuple(iter_b_source_compact_table(path)))

    def test_a_stride_table_is_rejected_as_b_input(self):
        from public_layer_a import build_compact_slices as build_a_rows

        lex = fixture_lexicon()
        a_rows = build_a_rows(fixture_a_slices(), lex, lambda record: "前")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a_pairs_stride8.jsonl"
            write_compact_table(path, a_rows, slice_digest=PINNED_SLICE_DIGEST)
            with self.assertRaises(PublicLayerBError):
                tuple(iter_b_compact_table(path))
            with self.assertRaises(PublicLayerBError):
                load_b_compact_header(path)

    def test_b_stride_keeps_every_eighth_b_slice(self):
        lex = fixture_lexicon()
        extra = slice_document(
            "后文还有刑事和行事。", lex,
            repo="typst-doc-cn/tutorial", path="t.md",
            source_sha="b2e19b6c9ddcec580c9f5b2741bd3b323b2eaf8c",
            spdx="Apache-2.0", split="B")
        all_slices = extra + fixture_b_slices()
        rows = build_b_compact_slices(all_slices, lex, lambda record: "前")
        from public_layer_a import stride_rows

        picked = stride_rows(rows)
        self.assertEqual((len(rows) + 7) // 8, len(picked))
        self.assertLess(len(picked), len(rows))
        self.assertNotEqual(0, len(picked))
        ids = [row.identity() for row in picked]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(tuple(sorted(picked)), tuple(picked))
        self.assertTrue(all(
            row.competitors == original.competitors
            for row, original in zip(picked, rows[::8])))
        self.assertTrue(all(
            row.repo in {"vuejs-translations/docs-zh-cn",
                         "typst-doc-cn/tutorial"}
            for row in picked))


class BQueryAndHitTest(unittest.TestCase):
    def test_query_is_last64_window(self):
        preceding = "后" * 70
        self.assertEqual("后" * 64, query_text(preceding))

    def test_pair_hit_is_strict_and_rejects_cos_v_v(self):
        query = (0.0, 1.0, 0.0)
        target = (1.0, 0.0, 0.0)
        self.assertFalse(pair_hit(query, target, (0.0, 1.0, 0.0)))
        self.assertFalse(pair_hit(target, target, target))
        self.assertTrue(pair_hit((1.0, 0.0, 0.0), target, (0.0, 1.0, 0.0)))

    def test_score_b_pairs_uses_ctx_as_query_not_gold_self(self):
        rows = fixture_rows()
        pairs = sum(len(row.competitors) for row in rows)
        seen_queries = []

        def encode_query(text):
            seen_queries.append(text)
            return (1.0, 0.0, 0.0)

        def encode_candidate(preceding, word):
            del preceding
            if word == "形式":
                return (1.0, 0.0, 0.0)
            return (0.0, 1.0, 0.0)

        hits = score_b_pairs(rows, encode_query, encode_candidate)
        self.assertEqual(pairs, hits)
        self.assertTrue(seen_queries)
        self.assertEqual("前文提到", seen_queries[0])

        def collide(preceding, word):
            del preceding, word
            return (0.0, 1.0, 0.0)

        self.assertEqual(0, score_b_pairs(rows, encode_query, collide))


class BGateVerdictTest(unittest.TestCase):
    def test_accuracy_at_or_above_gate_passes(self):
        winner, passed = select_verdict(7 / 10)
        self.assertTrue(passed)
        self.assertEqual(PASS_TERMINAL, winner)
        self.assertEqual("dedicated_bge_m3", winner)

    def test_accuracy_below_gate_is_no_public_winner(self):
        winner, passed = select_verdict(69 / 100)
        self.assertFalse(passed)
        self.assertEqual(FAIL_TERMINAL, winner)
        self.assertEqual("无公开赢家", winner)

    def test_boundary_is_inclusive_only(self):
        self.assertTrue(select_verdict(8 / 10)[1])
        self.assertTrue(select_verdict(7 / 10)[1])
        self.assertFalse(select_verdict(69 / 100)[1])

    def test_verdict_rejects_out_of_range_accuracy(self):
        with self.assertRaises(PublicLayerBError):
            select_verdict(1.1)
        with self.assertRaises(PublicLayerBError):
            select_verdict(-0.1)


class BFreezeAndReportTest(unittest.TestCase):
    def test_freeze_fields_and_digest(self):
        freeze = fixture_freeze()
        self.assertEqual(CONTRACT_ID, freeze["contract"])
        self.assertEqual(PINNED_SLICE_DIGEST, freeze["slice_digest"])
        self.assertEqual("abc123", freeze["code_sha"])
        self.assertEqual(A_WINNER_ROUTE, freeze["a_winner"])
        self.assertEqual(PINNED_A_FREEZE_DIGEST, freeze["a_freezer_digest"])
        self.assertEqual("fixture-bge-fp", freeze["a_winner_fingerprint"])
        self.assertEqual(PAIR_SET_RULE, freeze["pair_set_rule"])
        self.assertEqual(QUERY_RULE, freeze["query_rule"])
        self.assertEqual(100, freeze["b_source_slice_count"])
        self.assertEqual(500, freeze["b_source_pair_count"])
        self.assertEqual("source-digest", freeze["b_source_table_digest"])
        self.assertEqual(13, freeze["eligible_slice_count"])
        self.assertEqual(63, freeze["pair_count"])
        self.assertEqual("table-digest", freeze["compact_table_digest"])
        self.assertEqual(0.70, freeze["gate_accuracy"])
        self.assertEqual(64, len(freeze["freeze_digest"]))

    def test_freeze_rejects_drifted_pins(self):
        with self.assertRaises(PublicLayerBError):
            fixture_freeze(slice_digest="x" * 64)
        with self.assertRaises(PublicLayerBError):
            fixture_freeze(a_freezer_digest="y" * 64)
        with self.assertRaises(PublicLayerBError):
            fixture_freeze(code_sha="")
        with self.assertRaises(PublicLayerBError):
            fixture_freeze(pair_count=0)
        with self.assertRaises(PublicLayerBError):
            fixture_freeze(b_source_slice_count=0)

    def test_validate_rejects_a_contract_freeze(self):
        a_freeze = {
            "contract": "AC-154-v4",
            "slice_digest": PINNED_SLICE_DIGEST,
            "pair_set_rule": "target_len>=2;stride=8;index_mod=0",
            "query_rule": QUERY_RULE,
            "a_winner": A_WINNER_ROUTE,
            "a_freezer_digest": PINNED_A_FREEZE_DIGEST,
        }
        with self.assertRaises(PublicLayerBError) as raised:
            validate_freeze(a_freeze)
        self.assertIn("contract", str(raised.exception))

    def test_freeze_precedes_scores_and_is_one_shot(self):
        freeze = fixture_freeze()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            written = write_freeze(root, freeze)
            self.assertEqual(freeze, load_freeze(root))
            self.assertTrue(written.exists())
            with self.assertRaises(PublicLayerBError):
                write_freeze(root, freeze)
            apply_scores(root, freeze, 40)
            self.assertTrue(report_json_path(root).exists())
            with self.assertRaises(PublicLayerBError):
                write_freeze(root, fixture_freeze())
            with self.assertRaises(PublicLayerBError):
                apply_scores(root, freeze, 41)

    def test_apply_scores_requires_freeze_on_disk(self):
        freeze = fixture_freeze()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PublicLayerBError):
                apply_scores(Path(tmp), freeze, 40)

    def test_report_verdict_and_privacy(self):
        freeze = fixture_freeze(pair_count=10, eligible_slice_count=2)
        report = build_report(freeze, 7)
        self.assertEqual(0.7, report["accuracy"])
        self.assertTrue(report["gate_passed"])
        self.assertEqual(PASS_TERMINAL, report["winner"])
        report_fail = build_report(freeze, 6)
        self.assertEqual(FAIL_TERMINAL, report_fail["winner"])
        self.assertFalse(report_fail["gate_passed"])
        self.assertEqual(10, report["pair_count"])
        self.assertEqual(2, report["eligible_slice_count"])
        self.assertEqual(100, report["b_source_slice_count"])
        self.assertEqual(500, report["b_source_pair_count"])
        self.assertEqual("dedicated_bge_m3", report["a_winner"])
        self.assertEqual(PINNED_A_FREEZE_DIGEST, report["a_freezer_digest"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("形式", serialized)
        self.assertNotIn("前文", serialized)
        self.assertNotIn("alpha", serialized)
        self.assertNotIn("gamma", serialized)
        self.assertEqual([], scan_privacy(report))

    def test_report_hits_out_of_range_rejected(self):
        freeze = fixture_freeze(pair_count=10, eligible_slice_count=2)
        with self.assertRaises(PublicLayerBError):
            build_report(freeze, 11)
        with self.assertRaises(PublicLayerBError):
            build_report(freeze, -1)

    def test_markdown_renders_verdict_and_terminals(self):
        freeze = fixture_freeze(pair_count=10, eligible_slice_count=2)
        md = render_report_markdown(build_report(freeze, 7))
        self.assertIn("AC-156-v1", md)
        self.assertIn("0.70", md)
        self.assertIn("`PASSED`", md)
        self.assertIn("`dedicated_bge_m3`", md)
        self.assertIn("γ", md)
        self.assertIn("#113", md)
        self.assertIn("95%", md)
        self.assertIn("#155", md)
        md_fail = render_report_markdown(build_report(freeze, 6))
        self.assertIn("`FAILED`", md_fail)
        self.assertIn("无公开赢家", md_fail)

    def test_committed_a_winner_identity_is_read(self):
        identity = load_a_winner_identity()
        self.assertEqual(A_WINNER_ROUTE, identity.winner)
        self.assertEqual(PINNED_A_FREEZE_DIGEST, identity.freeze_digest)
        self.assertTrue(identity.fingerprint.startswith("dedicated-embedding"))
        committed = json.loads(
            (Path(__file__).resolve().parent / "public_layer" /
             "a_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(
            committed["routes"]["dedicated_bge_m3"]["fingerprint"],
            identity.fingerprint)

    def test_load_a_winner_identity_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drifted = {
                "contract": "AC-154-v4",
                "freeze_digest": "0" * 64,
                "routes": {"dedicated_bge_m3": {"fingerprint": "f"}},
            }
            (root / "a_freeze.json").write_text(
                json.dumps(drifted), encoding="utf-8")
            with self.assertRaises(PublicLayerBError):
                load_a_winner_identity(root)
            no_fp = {
                "contract": "AC-154-v4",
                "freeze_digest": PINNED_A_FREEZE_DIGEST,
                "routes": {"dedicated_qwen3_embedding_0_6b": {}},
            }
            (root / "a_freeze.json").write_text(
                json.dumps(no_fp), encoding="utf-8")
            with self.assertRaises(PublicLayerBError):
                load_a_winner_identity(root)

    def test_committed_digest_pin(self):
        self.assertEqual(PINNED_SLICE_DIGEST, verify_committed_digest())

    def test_current_code_sha_is_plausible(self):
        sha = current_code_sha(require_clean=False)
        self.assertEqual(40, len(sha))

    def test_readme_documents_b_gate_and_limits(self):
        text = (Path(__file__).resolve().parent / "README.md").read_text(
            encoding="utf-8")
        self.assertIn("Public-layer B gate", text)
        self.assertIn("#156", text)
        self.assertIn("70%", text)
        self.assertIn("无公开赢家", text)
        self.assertIn("γ", text)
        self.assertIn("#113", text)
        self.assertIn("95%", text)
        self.assertIn("#155", text)


class BMetricGateTest(unittest.TestCase):
    def test_report_full_hits_pass_and_zero_hits_fail(self):
        freeze = fixture_freeze(pair_count=10, eligible_slice_count=2)
        self.assertTrue(build_report(freeze, 10)["gate_passed"])
        self.assertFalse(build_report(freeze, 0)["gate_passed"])


class BMemorySplitTest(unittest.TestCase):
    def test_guard_stops_above_eight_gigabytes(self):
        with self.assertRaises(Exception):
            guard_scorer_rss(MAX_SCORER_RSS_BYTES + 1)
        self.assertEqual(100, guard_scorer_rss(100))

    def test_score_route_worker_does_not_load_lexicon(self):
        import run_public_layer_b as runner

        worker_src = "\n".join((
            inspect.getsource(runner.score_bge_route),
            inspect.getsource(runner._track_rss),
        ))
        self.assertNotIn("Lexicon", worker_src)
        self.assertNotIn("load_lexicon", worker_src)
        self.assertNotIn("pinyin_to_words", worker_src)
        self.assertNotIn("essay", worker_src.lower())
        self.assertIn("iter_b_compact_table", worker_src)
        self.assertIn("guard_scorer_rss", worker_src)


if __name__ == "__main__":
    unittest.main()