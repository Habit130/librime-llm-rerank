#!/usr/bin/env python3
"""Re-verify the committed canonical 120/402 fixture (Habit130/squirrel#46).

A fresh checkout can re-verify the fixture end to end:

  eval/.venv/bin/python eval/verify_fixture.py \
      --dict <fixture librime build>/bin/luna_pinyin.dict.yaml

Checks:
  - corpus SHA-256 matches a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae
  - re-derived sentence/word cases match the committed fixture.json exactly
  - word case count == 402 and the word manifest checksum matches
  - the committed fixture.json itself is internally consistent

Exit 0 on verification, nonzero otherwise.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from derive_cases import (  # noqa: E402
    CORPUS_SHA256,
    load_corpus,
    parse_dict,
    sha256_file,
    word_manifest_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "eval" / "corpus" / "sentences.txt"
DEFAULT_FIXTURE = REPO_ROOT / "eval" / "fixture.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--dict", type=Path, required=True,
                    help="fixture librime build's luna_pinyin.dict.yaml")
    args = ap.parse_args()

    failures = []

    corpus_sha = sha256_file(args.corpus)
    if corpus_sha != CORPUS_SHA256:
        failures.append(
            f"corpus checksum mismatch: expected {CORPUS_SHA256}, got {corpus_sha}"
        )

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    committed_sentence_cases = fixture["sentence_cases"]
    committed_word_cases = fixture["word_cases"]

    dict_keys, char_readings = parse_dict(args.dict)
    sentence_cases, _skipped = load_corpus(args.corpus, char_readings)

    derived_sentences = [
        {"index": i, "sentence": sentence, "pinyin": "".join(syllables)}
        for i, (sentence, syllables) in enumerate(sentence_cases, 1)
    ]
    if derived_sentences != committed_sentence_cases:
        failures.append(
            f"sentence cases differ: derived {len(derived_sentences)} vs "
            f"committed {len(committed_sentence_cases)}"
        )

    from derive_cases import derive_word_cases  # noqa: E402

    word_cases = derive_word_cases(sentence_cases, dict_keys)
    derived_words = []
    for index, (word, syllables) in enumerate(word_cases, 1):
        source_sentence = None
        source_start = None
        for i, (sentence, _) in enumerate(sentence_cases, 1):
            position = sentence.find(word)
            if position >= 0:
                source_sentence = i
                source_start = position
                break
        derived_words.append({
            "index": index,
            "word": word,
            "pinyin": "".join(syllables),
            "source_sentence": source_sentence,
            "source_start": source_start,
        })
    if derived_words != committed_word_cases:
        failures.append(
            f"word cases differ: derived {len(derived_words)} vs "
            f"committed {len(committed_word_cases)}"
        )

    manifest_sha = hashlib.sha256(
        "\n".join(word_manifest_lines(word_cases)).encode("utf-8")
    ).hexdigest()
    if manifest_sha != fixture["word_manifest_sha256"]:
        failures.append(
            f"word manifest checksum mismatch: expected "
            f"{fixture['word_manifest_sha256']}, re-derived {manifest_sha}"
        )

    if fixture["counts"]["words"] != 402:
        failures.append(
            f"fixture word count is {fixture['counts']['words']}, expected 402"
        )
    if len(committed_word_cases) != 402:
        failures.append(
            f"committed word cases count is {len(committed_word_cases)}, "
            "expected 402"
        )

    if failures:
        print("FAIL: fixture verification failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"PASS: fixture verified")
    print(f"  corpus sha256:      {corpus_sha}")
    print(f"  sentence cases:     {len(committed_sentence_cases)}")
    print(f"  word cases:         {len(committed_word_cases)}")
    print(f"  word manifest sha256: {manifest_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
