#!/usr/bin/env python3
"""Control denominator for the #106 α recalibration (fixture in-prefix).

The control denominator (seam 10, frozen):

- from the committed ``eval/fixture.json`` (membership is never regenerated):
  120 ``sentence_cases`` plus the ``word_cases`` that cite
  ``source_sentence`` / ``source_start``;
- for each word case, ``上文 = sentence[:source_start]``, target = ``word``;
  the pinyin is the case's own pinyin;
- cases whose prefix is empty (``source_start == 0``) are dropped — those
  are the empty-上文 protocol — and the dropped count is reported
  (SCN-106-7);
- the engine competition set for that pinyin is ranked under the same
  formula and grid inside a disposable rime_dir (the console + full
  template dict path, following the #46 ``calibrate.py`` pattern);
- the control table is published SEPARATELY and never enters
  ``decide_final`` (AC106-3, SCN-106-6).

No raw text leaves this module: per-case records carry case indexes,
pinyin codes, prefix lengths and ranks only.
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class ControlError(Exception):
    """A true fault in the control denominator inputs."""


@dataclass(frozen=True)
class ControlCase:
    """One control case (index and numbers only)."""

    case_index: int        # fixture index (word case index)
    kind: str              # "word" | "sentence"
    target_index: str      # desensitized: the case index as the label key
    pinyin: str
    prefix_length: int
    competition_size: Optional[int]   # engine competition size at replay
    target_rank: Optional[int]        # rank of the target in the set


def load_fixture(fixture_path: str) -> Dict:
    """Load and validate the committed 120/402 fixture."""
    with open(fixture_path, encoding="utf-8") as handle:
        fixture = json.load(handle)
    counts = fixture.get("counts") or {}
    if counts.get("sentences") != 120 or counts.get("words") != 402:
        raise ControlError(
            "fixture is not the canonical 120/402 fixture: %s" % fixture_path)
    return fixture


def control_word_cases(fixture: Dict) -> Tuple[List[ControlCase], int]:
    """The in-prefix word cases (empty-prefix cases dropped, counted).

    Returns (cases, dropped_count).  ``上文 = sentence[:source_start]``; the
    target is the word; the label key is the case index (no raw text).
    """
    sentences = {c["index"]: c["sentence"] for c in fixture["sentence_cases"]}
    cases = []
    dropped = 0
    for word_case in fixture["word_cases"]:
        src = word_case.get("source_sentence")
        start = word_case.get("source_start")
        if src is None or start is None:
            dropped += 1
            continue
        sentence = sentences.get(src)
        if sentence is None:
            dropped += 1
            continue
        prefix = sentence[:start]
        if not prefix:
            dropped += 1
            continue
        cases.append(ControlCase(
            case_index=word_case["index"],
            kind="word",
            target_index=str(word_case["index"]),
            pinyin=word_case["pinyin"],
            prefix_length=len(prefix),
            competition_size=None,
            target_rank=None,
        ))
    return cases, dropped




def sentence_cases(fixture: Dict) -> List[ControlCase]:
    """The 120 sentence cases (guard table).

    Each sentence case is a whole-sentence query under the #46 context
    protocol (上文 empty): the pinyin is the full sentence pinyin and the
    target is the sentence text.  They are reported as a separate guard
    table and never enter ``decide_final`` (AC106-3).
    """
    return [
        ControlCase(
            case_index=c["index"],
            kind="sentence",
            target_index=str(c["index"]),
            pinyin=c["pinyin"],
            prefix_length=0,
            competition_size=None,
            target_rank=None,
        )
        for c in fixture["sentence_cases"]
    ]


def control_case_ranks(candidates: List[str],
                       logged_weights: List,
                       lm_scores: List[float],
                       target_text: str,
                       alphas: List[float]) -> Dict[float, Optional[int]]:
    """Per-α ranks of one control case from one engine competition set.

    ``candidates`` is the engine competition set in emitted order;
    ``logged_weights`` the per-candidate librime weights from the filter's
    verbose logs; ``lm_scores`` the per-candidate daemon mean-token scores;
    ``target_text`` the case's target (the word text, matched exactly as the
    emitted candidates).  Returns {alpha: rank-or-None} for the target under
    every α (ties keep the emitted order).
    """
    if len(candidates) != len(logged_weights) or \
            len(candidates) != len(lm_scores):
        raise ControlError(
            "control case rank inputs misaligned: %d candidates, %d weights, "
            "%d lm scores" % (len(candidates), len(logged_weights),
                              len(lm_scores)))
    weights = [w for _, w in logged_weights]
    result = {}
    for alpha in alphas:
        scores = [alpha * lm + weight
                  for lm, weight in zip(lm_scores, weights)]
        order = sorted(range(len(scores)),
                       key=lambda i: (-scores[i], i))
        rank = None
        for position, index in enumerate(order, start=1):
            if candidates[index] == target_text:
                rank = position
                break
        result[alpha] = rank
    return result
