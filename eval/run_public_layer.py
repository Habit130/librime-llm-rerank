#!/usr/bin/env python3
"""Build the frozen public-layer slice corpus (Squirrel #153)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_layer_slicer import (
    ESSAY_REPO,
    ESSAY_SHA,
    LUNA_PINYIN_REPO,
    LUNA_PINYIN_SHA,
    MIN_SPLIT_COUNT,
    SOURCES,
    Lexicon,
    build_manifest,
    count_gate_errors,
    digest_manifest,
    fetch_github_sha,
    fetch_raw_file,
    scan_privacy,
    sha256_file,
    slice_tree,
    write_slice_table,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(__file__).resolve().parent / ".cache" / "public_layer",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "public_layer",
    )
    args = parser.parse_args(argv)

    cache = args.cache
    output = args.output
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    dict_path = fetch_raw_file(
        LUNA_PINYIN_REPO, LUNA_PINYIN_SHA, "luna_pinyin.dict.yaml",
        cache / "lexicon" / "luna_pinyin.dict.yaml")
    essay_path = fetch_raw_file(
        ESSAY_REPO, ESSAY_SHA, "essay.txt",
        cache / "lexicon" / "essay.txt")
    lexicon_files = [
        {
            "name": "luna_pinyin.dict.yaml",
            "repo": LUNA_PINYIN_REPO,
            "sha": LUNA_PINYIN_SHA,
            "sha256": sha256_file(dict_path),
        },
        {
            "name": "essay.txt",
            "repo": ESSAY_REPO,
            "sha": ESSAY_SHA,
            "sha256": sha256_file(essay_path),
        },
    ]
    print("loading lexicon", flush=True)
    lexicon = Lexicon.from_files(dict_path, essay_path)
    print(f"lexicon words={len(lexicon.words)}", flush=True)

    slices = []
    for source in SOURCES:
        print(f"fetching {source.repo}@{source.sha}", flush=True)
        root = fetch_github_sha(
            source.repo, source.sha,
            cache / "sources" / source.repo.replace("/", "_"))
        print(f"slicing {source.repo}", flush=True)
        found = slice_tree(
            root, lexicon, repo=source.repo, source_sha=source.sha,
            spdx=source.spdx, split=source.split)
        print(f"  {source.repo}: {len(found)}", flush=True)
        slices.extend(found)

    slices.sort(key=lambda rec: (
        rec["repo"], rec["path"], rec["start"], rec["end"],
        rec["canonical_input"], rec["target"]))
    manifest = build_manifest(slices, lexicon_files)
    manifest["digest"] = digest_manifest(manifest)
    errors = count_gate_errors(manifest)
    written = {key: value for key, value in manifest.items()
               if key != "slices"}
    (output / "manifest.json").write_text(
        json.dumps(written, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    write_slice_table(output / "slices.tsv", slices)
    report = [
        "# Public-layer source slices (AC-153-v1)",
        "",
        f"- rule: `{manifest['rule_id']}`",
        f"- digest: `{manifest['digest']}`",
        f"- A: {manifest['counts']['A']}",
        f"- B: {manifest['counts']['B']}",
        "",
        "| Repo | Split | Count |",
        "| --- | --- | ---: |",
    ]
    for source in SOURCES:
        report.append(
            f"| `{source.repo}` | {source.split} | "
            f"{manifest['counts_per_source'].get(source.repo, 0)} |"
        )
    report.extend([
        "",
        "`slices.tsv` stores source index, path, offsets, target, and complete",
        "pinyin. Competitors are reconstructed from the pinned system lexicon;",
        "上文 is reconstructed from the pinned source files and offsets. Neither",
        "private 上文 nor machine paths are stored.",
        "",
        "This corpus is public-layer raw material only. It does not load a",
        "model, emit pairwise scores, or choose a winner. The retired v1/v2",
        "95% representation gates from #69/#150 are demoted and are not",
        "applied here.",
        "",
    ])
    if errors:
        report.append("Count gate failed:")
        report.extend(f"- {item}" for item in errors)
        report.append("")
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")

    privacy = scan_privacy(written)
    if privacy:
        print("privacy findings:", file=sys.stderr)
        for item in privacy:
            print(f"  {item}", file=sys.stderr)
        return 2
    if errors:
        print("count gate failed:", file=sys.stderr)
        for item in errors:
            print(f"  {item}", file=sys.stderr)
        return 1
    print(f"digest {manifest['digest']}")
    print(f"A={manifest['counts']['A']} B={manifest['counts']['B']} "
          f"(min {MIN_SPLIT_COUNT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
