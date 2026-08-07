#!/usr/bin/env python3
"""Generate the canonical 120/402 eval fixture (Habit130/squirrel#46).

The derivation logic is copied verbatim from Squirrel PR #24 head commit
b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b (scripts/eval/run_eval.py), so a
fresh checkout regenerates byte-identical cases:

  - corpus: eval/corpus/sentences.txt (120 sentences, SHA-256
    a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae)
  - pinyin: pypinyin==0.55.0, sentence-level context-aware polyphone
    disambiguation, validated against the fixture dict's per-character
    readings
  - word cases: every dict-word substring (lengths 1..4) of each sentence,
    deduplicated by word text across the corpus, first occurrence wins,
    sorted by word text -> 402 cases

The fixture librime is pinned at 33e78140250125871856cdc5b42ddc6a5fcd3cd4
(1.17.0); the dict argument must come from that build's fixture files
(librime/build/bin/luna_pinyin.dict.yaml).

Context semantics: standalone word protocol, preceding text empty.

Output: eval/fixture.json (committed) with per-case pinyin and provenance
(source sentence index + char offset) plus checksums.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    sys.exit(
        "error: pypinyin not importable. Create the eval venv first: "
        "python3 -m venv eval/.venv && eval/.venv/bin/pip install -r eval/requirements.txt"
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "eval" / "corpus" / "sentences.txt"
DEFAULT_FIXTURE = REPO_ROOT / "eval" / "fixture.json"
MAX_PINYIN_LEN = 90
HAN_RE = re.compile(r"^[㐀-䶿一-鿿]+$")
CORPUS_SHA256 = "a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae"
SOURCE_COMMIT = "b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b"
FIXTURE_LIBRIME_COMMIT = "33e78140250125871856cdc5b42ddc6a5fcd3cd4"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dict(dict_path):
    """Return (set of every dict word key, char -> set of its dict readings)."""
    dict_keys = set()
    char_readings = {}
    started = False
    with dict_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not started:
                if line == "...":
                    started = True
                continue
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            word, pinyin = parts[0], parts[1]
            dict_keys.add(word)
            if len(word) == 1 and " " not in pinyin:
                char_readings.setdefault(word, set()).add(pinyin)
    return dict_keys, char_readings


def load_corpus(corpus_path, char_readings):
    """Return ([(sentence, syllables), ...], skipped) -- syllables is a
    per-character list, kept (rather than joined) so derive_word_cases can
    slice out sub-words with their in-context reading."""
    cases = []
    skipped = []
    with corpus_path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not HAN_RE.match(line):
                skipped.append((lineno, line, "non-Han content"))
                continue
            oov = [c for c in line if c not in char_readings]
            if oov:
                skipped.append(
                    (lineno, line,
                     f"OOV char(s): {''.join(sorted(set(oov)))}")
                )
                continue
            syllables = lazy_pinyin(line, style=Style.NORMAL)
            bad = [
                f"{c}({s})"
                for c, s in zip(line, syllables)
                if s not in char_readings.get(c, ())
            ]
            if bad:
                skipped.append(
                    (lineno, line, f"reading not in dict: {', '.join(bad)}")
                )
                continue
            if len("".join(syllables)) > MAX_PINYIN_LEN:
                skipped.append(
                    (lineno, line,
                     f"pinyin too long ({len(''.join(syllables))} chars)")
                )
                continue
            cases.append((line, syllables))
    return cases, skipped


def derive_word_cases(sentence_cases, dict_keys, lengths=(1, 2, 3, 4)):
    """Pull out every dict-word substring of each sentence as its own
    standalone test case, deduped by word text across the whole corpus
    (first occurrence wins), sorted by word text."""
    words = {}
    for sentence, syllables in sentence_cases:
        n = len(sentence)
        for length in lengths:
            for i in range(0, n - length + 1):
                word = sentence[i:i + length]
                if word in dict_keys and word not in words:
                    words[word] = syllables[i:i + length]
    return sorted(words.items())


def word_manifest_lines(word_cases):
    return [f"{word}\t{''.join(syllables)}" for word, syllables in word_cases]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--dict", type=Path, required=True,
                    help="fixture librime build's luna_pinyin.dict.yaml")
    ap.add_argument("--output", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--expect-words", type=int, default=402)
    args = ap.parse_args()

    if not args.corpus.exists():
        sys.exit(f"error: corpus not found: {args.corpus}")
    if not args.dict.exists():
        sys.exit(f"error: dict not found: {args.dict}")

    corpus_sha = sha256_file(args.corpus)
    if corpus_sha != CORPUS_SHA256:
        sys.exit(
            f"error: corpus checksum mismatch: expected {CORPUS_SHA256}, "
            f"got {corpus_sha}. Use the canonical corpus from Squirrel PR #24."
        )

    dict_keys, char_readings = parse_dict(args.dict)
    sentence_cases, skipped = load_corpus(args.corpus, char_readings)
    if not sentence_cases:
        sys.exit("error: no usable sentence cases after filtering the corpus.")
    word_cases = derive_word_cases(sentence_cases, dict_keys)

    sentences = [
        {"index": i, "sentence": sentence,
         "pinyin": "".join(syllables)}
        for i, (sentence, syllables) in enumerate(sentence_cases, 1)
    ]
    words = []
    for index, (word, syllables) in enumerate(word_cases, 1):
        source_sentence = None
        source_start = None
        for i, (sentence, _) in enumerate(sentence_cases, 1):
            position = sentence.find(word)
            if position >= 0:
                source_sentence = i
                source_start = position
                break
        words.append({
            "index": index,
            "word": word,
            "pinyin": "".join(syllables),
            "source_sentence": source_sentence,
            "source_start": source_start,
        })

    manifest = word_manifest_lines(word_cases)
    manifest_sha = hashlib.sha256(
        "\n".join(manifest).encode("utf-8")
    ).hexdigest()

    fixture = {
        "source_commit": SOURCE_COMMIT,
        "source_paths": ["scripts/eval/corpus/sentences.txt",
                         "scripts/eval/run_eval.py (derive_word_cases)"],
        "corpus_sha256": corpus_sha,
        "pinyin_dependency": "pypinyin==0.55.0",
        "fixture_librime_commit": FIXTURE_LIBRIME_COMMIT,
        "context_protocol": "standalone word, preceding text empty",
        "counts": {
            "sentences": len(sentences),
            "words": len(words),
        },
        "word_manifest_sha256": manifest_sha,
        "sentence_cases": sentences,
        "word_cases": words,
    }

    if len(words) != args.expect_words:
        sys.exit(
            f"error: expected {args.expect_words} word cases, derived "
            f"{len(words)}. This dict/corpus pair is not the canonical "
            "fixture."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"corpus:      {args.corpus} ({corpus_sha})")
    print(f"dict:        {args.dict}")
    print(f"skipped:     {len(skipped)}")
    for lineno, line, reason in skipped:
        print(f"  line {lineno}: {line!r} - {reason}")
    print(f"sentence cases: {len(sentences)}")
    print(f"word cases:     {len(words)}")
    print(f"word manifest sha256: {manifest_sha}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
