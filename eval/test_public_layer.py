#!/usr/bin/env python3
"""Model-free tests for the public-layer source slicer (Squirrel #153)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from public_layer_slicer import (  # noqa: E402
    FORBIDDEN_DELIVERY_MARKERS,
    RULE_ID,
    SOURCES,
    Lexicon,
    build_manifest,
    compact_slice,
    digest_manifest,
    ineligible_mask,
    normalize_pinyin,
    read_slice_table,
    scan_privacy,
    slice_document,
    slice_tree,
    write_slice_table,
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
行	hang
行	xing
航	hang
"""

FIXTURE_ESSAY = """形式	100
刑事	100
行事	10
航行	50
"""


def fixture_lexicon():
    return Lexicon.from_texts(FIXTURE_DICT, FIXTURE_ESSAY)


class PinsTest(unittest.TestCase):
    def test_five_sources_match_issue_153_table(self):
        expected = [
            ("A", "rust-lang-cn/book-cn",
             "cde74c448e301ce8ac7960a0d3dc879efd83635d",
             "Apache-2.0 / MIT"),
            ("A", "SwiftGGTeam/the-swift-programming-language-in-chinese",
             "cfc700e942e8e45e56e834172c6df55412f864d2",
             "Apache-2.0"),
            ("A", "Go-zh/go",
             "d4e8cec7338bde4c8396df6b642f991199d92186",
             "BSD-3-Clause"),
            ("B", "vuejs-translations/docs-zh-cn",
             "cfb9e9c56f112964021f9f5246bd1e65a6b15088",
             "CC-BY-4.0"),
            ("B", "typst-doc-cn/tutorial",
             "b2e19b6c9ddcec580c9f5b2741bd3b323b2eaf8c",
             "Apache-2.0"),
        ]
        self.assertEqual(5, len(SOURCES))
        got = [(s.split, s.repo, s.sha, s.spdx) for s in SOURCES]
        self.assertEqual(expected, got)

    def test_ab_membership_is_whole_repo(self):
        by_repo = {s.repo: s.split for s in SOURCES}
        self.assertEqual("A", by_repo["Go-zh/go"])
        self.assertEqual("B", by_repo["vuejs-translations/docs-zh-cn"])
        self.assertEqual({"A", "B"}, {s.split for s in SOURCES})


class LexiconTest(unittest.TestCase):
    def test_normalize_keeps_syllable_boundaries(self):
        self.assertEqual("xing shi", normalize_pinyin("Xing Shi"))
        self.assertEqual("shuan", normalize_pinyin("shuan"))
        self.assertEqual("shu an", normalize_pinyin("shu an"))
        self.assertNotEqual(normalize_pinyin("shu an"),
                            normalize_pinyin("shuan"))

    def test_essay_encoding_adds_system_words(self):
        lex = fixture_lexicon()
        self.assertIn("形式", lex.words)
        self.assertIn("xing shi", lex.word_to_pinyins["形式"])
        self.assertIn("刑事", lex.pinyin_to_words["xing shi"])

    def test_homophones_are_same_complete_pinyin_different_word(self):
        lex = fixture_lexicon()
        comps = lex.competitors("形式", "xing shi")
        self.assertEqual(["刑事", "行事"], comps)
        self.assertNotIn("形式", comps)
        self.assertNotIn("航行", comps)

    def test_polyphone_sets_stay_separate(self):
        lex = fixture_lexicon()
        self.assertEqual(["航"], lex.competitors("行", "hang"))
        self.assertIn("形", lex.competitors("行", "xing"))
        self.assertNotIn("航", lex.competitors("行", "xing"))


class MaskTest(unittest.TestCase):
    def test_fenced_and_inline_code_are_ineligible(self):
        text = "前文形式\n```\n刑事\n```\n后文`行事`结束"
        mask = ineligible_mask(text)
        self.assertFalse(mask[text.index("形")])
        self.assertTrue(mask[text.index("刑")])
        self.assertTrue(mask[text.index("行")])
        self.assertFalse(mask[text.index("结")])

    def test_ascii_only_and_image_only_lines_are_ineligible(self):
        text = "hello world\n![图](a.png)\n形式可以\n"
        mask = ineligible_mask(text)
        self.assertTrue(all(mask[i] for i, ch in enumerate(text)
                            if ch in "hello world"))
        self.assertTrue(mask[text.index("!")])
        self.assertFalse(mask[text.index("形")])

    def test_html_pre_masks_go_object_name_comment(self):
        text = (
            "<p>假如有以下声明：</p>\n"
            "<pre>\n"
            "type T struct {\n"
            "    name string // 对象名\n"
            "    value int // 对象值\n"
            "}\n"
            "</pre>\n"
            "<p>后文形式。</p>\n"
        )
        mask = ineligible_mask(text)
        for token in ("对象名", "对象值"):
            start = text.index(token)
            self.assertTrue(all(mask[start:start + len(token)]), token)
        self.assertFalse(mask[text.index("形")])

    def test_html_code_masks_inline_han(self):
        text = "可见<code>f(g(<i>g 的形参</i>))</code>以及形式。"
        mask = ineligible_mask(text)
        start = text.index("的形参")
        self.assertTrue(all(mask[start:start + 3]))
        prose = text.index("形式")
        self.assertFalse(mask[prose])

    def test_html_script_masks_footer_comments(self):
        text = (
            "<p>前文形式</p>\n"
            "<script type=\"text/javascript\">\n"
            "    // 根据保存的偏好设置配色方案。\n"
            "    const appearanceKey = 'developer.setting.preferredColorScheme'\n"
            "</script>\n"
        )
        mask = ineligible_mask(text)
        start = text.index("根据保存")
        self.assertTrue(all(mask[start:start + 4]))
        self.assertFalse(mask[text.index("形")])

    def test_markdown_script_setup_mention_is_not_an_html_region(self):
        text = "详见 [`<script setup>`](/api)。后文形式。"
        mask = ineligible_mask(text)
        self.assertFalse(mask[text.index("形式")])


class SliceRuleTest(unittest.TestCase):
    def test_target_is_exact_original_substring_at_offsets(self):
        lex = fixture_lexicon()
        text = "前文提到形式和内容。"
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.md",
            source_sha="abc", spdx="MIT", split="A")
        hit = [s for s in slices if s["target"] == "形式"]
        self.assertEqual(1, len(hit))
        rec = hit[0]
        self.assertEqual(text[rec["start"]:rec["end"]], rec["target"])
        self.assertEqual("形式", text[rec["start"]:rec["end"]])
        self.assertEqual(["刑事", "行事"], rec["competitors"])
        self.assertEqual("xing shi", rec["canonical_input"])

    def test_longest_match_is_greedy_left_to_right(self):
        lex = fixture_lexicon()
        text = "甲形式乙"
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.md",
            source_sha="abc", spdx="MIT", split="A")
        targets = [s["target"] for s in slices]
        self.assertIn("形式", targets)
        self.assertNotIn("形", targets)
        self.assertNotIn("式", targets)

    def test_no_fake_words(self):
        lex = fixture_lexicon()
        text = "形式的行。"
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.md",
            source_sha="abc", spdx="MIT", split="A")
        for rec in slices:
            self.assertIn(rec["target"], lex.words)
            for word in rec["competitors"]:
                self.assertIn(word, lex.words)
                self.assertIn(rec["canonical_input"],
                              lex.word_to_pinyins[word])
            self.assertNotIn(rec["target"], rec["competitors"])

    def test_code_fence_does_not_leak_targets(self):
        lex = fixture_lexicon()
        text = "前文这里\n```text\n形式\n```\n"
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.md",
            source_sha="abc", spdx="MIT", split="A")
        self.assertEqual([], [s for s in slices if s["target"] == "形式"])

    def test_html_pre_code_script_do_not_leak_targets(self):
        lex = fixture_lexicon()
        text = (
            "<p>前文这里</p>\n"
            "<pre>name string // 形式</pre>\n"
            "<p>中间<code>刑事</code>还有</p>\n"
            "<script type=\"text/javascript\">// 行事</script>\n"
        )
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.html",
            source_sha="abc", spdx="MIT", split="A")
        self.assertEqual([], [s["target"] for s in slices])

    def test_preceding_text_is_at_most_64_and_requires_han(self):
        lex = fixture_lexicon()
        text = "形" + "式"
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.md",
            source_sha="abc", spdx="MIT", split="A")
        self.assertEqual([], slices)
        prefix = "甲" * 80
        text = prefix + "形式"
        slices = slice_document(
            text, lex, repo="ex/repo", path="a.md",
            source_sha="abc", spdx="MIT", split="A")
        hit = [s for s in slices if s["target"] == "形式"][0]
        self.assertEqual(64, len(hit["preceding_text"]))
        self.assertEqual("甲" * 64, hit["preceding_text"])

    def test_license_and_non_document_files_are_skipped(self):
        lex = fixture_lexicon()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "LICENSE").write_text("形式刑事\n", encoding="utf-8")
            (root / "pic.png").write_bytes(b"\x89PNG")
            (root / "main.go").write_text("// 形式\n", encoding="utf-8")
            (root / "doc.md").write_text("前文形式。\n", encoding="utf-8")
            slices = slice_tree(
                root, lex, repo="ex/repo", source_sha="abc",
                spdx="MIT", split="A")
            self.assertEqual(["doc.md"], sorted({s["path"] for s in slices}))
            self.assertTrue(all(s["target"] == "形式" for s in slices))


class DigestTest(unittest.TestCase):
    def _payload(self):
        lex = fixture_lexicon()
        slices = slice_document(
            "前文形式。", lex, repo="rust-lang-cn/book-cn", path="a.md",
            source_sha=SOURCES[0].sha, spdx=SOURCES[0].spdx, split="A")
        return build_manifest(
            slices,
            lexicon_files=[
                {"name": "luna_pinyin.dict.yaml", "sha256": "d" * 64},
                {"name": "essay.txt", "sha256": "e" * 64},
            ],
        )

    def test_digest_is_identical_twice(self):
        payload = self._payload()
        first = digest_manifest(payload)
        second = digest_manifest(payload)
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))

    def test_slice_table_roundtrip_preserves_digest_fields(self):
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slices.tsv"
            write_slice_table(path, payload["slices"])
            loaded = read_slice_table(path)
        self.assertEqual(
            [compact_slice(row) for row in payload["slices"]], loaded)

    def test_mutating_sha_lexicon_rule_or_split_changes_digest(self):
        base = digest_manifest(self._payload())
        sha_mut = self._payload()
        sha_mut["sources"][0]["sha"] = "0" * 40
        lex_mut = self._payload()
        lex_mut["lexicon_files"][0]["sha256"] = "f" * 64
        rule_mut = self._payload()
        rule_mut["rule_id"] = RULE_ID + "-mutated"
        split_mut = self._payload()
        split_mut["slices"][0]["split"] = "B"
        self.assertNotEqual(base, digest_manifest(sha_mut))
        self.assertNotEqual(base, digest_manifest(lex_mut))
        self.assertNotEqual(base, digest_manifest(rule_mut))
        self.assertNotEqual(base, digest_manifest(split_mut))


class PrivacyTest(unittest.TestCase):
    def test_scan_rejects_home_paths_and_live_facts(self):
        findings = scan_privacy({
            "repo": "ex/repo",
            "path": "/Users/habit/secret.md",
            "note": "~/Library/Rime/user.yaml",
        })
        self.assertTrue(findings)
        clean = scan_privacy({
            "repo": "ex/repo",
            "path": "src/ch01.md",
            "target": "形式",
        })
        self.assertEqual([], clean)
        self.assertIn("/Users/", FORBIDDEN_DELIVERY_MARKERS)


class CommittedArtifactTest(unittest.TestCase):
    ARTIFACT_DIR = Path(__file__).resolve().parent / "public_layer"

    def test_committed_manifest_pins_and_counts_if_present(self):
        manifest_path = self.ARTIFACT_DIR / "manifest.json"
        slices_path = self.ARTIFACT_DIR / "slices.tsv"
        if not manifest_path.exists():
            self.skipTest("full-run artifacts not committed yet")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        slices = read_slice_table(slices_path)
        self.assertEqual(RULE_ID, manifest["rule_id"])
        self.assertEqual(
            [(s.split, s.repo, s.sha) for s in SOURCES],
            [(row["split"], row["repo"], row["sha"])
             for row in manifest["sources"]])
        self.assertGreaterEqual(manifest["counts"]["A"], 200)
        self.assertGreaterEqual(manifest["counts"]["B"], 200)
        payload = dict(manifest)
        payload["slices"] = slices
        self.assertEqual(manifest["digest"], digest_manifest(payload))
        self.assertEqual(manifest["counts"]["A"] + manifest["counts"]["B"],
                         len(slices))
        self.assertTrue(all("/" not in row["path"][:1] and
                            not row["path"].startswith("/Users/")
                            for row in slices))
        findings = scan_privacy(manifest)
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
