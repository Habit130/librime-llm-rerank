#!/usr/bin/env python3
"""Template dictionary weights for the #106 α recalibration.

The facts store persists the saved competition candidate *texts* but not
their librime weights or LM scores.  This module recovers the librime
runtime weight of a saved candidate from the template (system) dictionary's
compiled table, exactly as the plugin's ``WeightScorer`` reads it from
``Phrase::weight()``:

    phrase_weight = log(raw_weight) - kS + credibility

where ``kS = log(1e8)`` and ``credibility`` is 0 for the flat template
environment (no prism path penalty, no user data).  ``raw_weight`` is the
dictionary entry's compiled weight (``log`` of the raw dict/essay weight in
``dict_compiler``), so the decompiled table's stored weight is already
``log(raw_weight)``; the runtime value is that minus ``kS``.

The decompiled table is produced from the librime build tree's compiled
``luna_pinyin.table.bin`` by ``rime_table_decompiler`` (a read-only tool
copied out of the librime build tree; we never run librime's build here).
The decompiler writes the entry's *raw* weight (``exp`` of the stored log
weight); entries whose raw weight is 0 compile to ``log(DBL_EPSILON)`` and
the decompiler omits the weight column for them, so this module applies the
``log(DBL_EPSILON) - kS`` value explicitly.

Candidate text matching uses the oracle's simplified-NFC normalization
(``daemon/oracle.py::match_text``) because the compiled table stores
traditional text while the facts store simplified candidates; the mapping is
keyed by ``(simplified_text, code_without_spaces)``.

A candidate whose ``(text, code)`` is absent from the template table cannot
receive a finite weight: that is the RISK-106-1 user-dict case and makes the
whole event 无法重放 (SCN-106-5).  This module never touches the user
dictionary, ``~/Library/Rime``, or the live facts store.
"""

import math
import os
from typing import Dict, Optional, Tuple

from oracle import match_text  # simplified-NFC normalization

# librime constants (src/rime/dict/dictionary.cc kS; dict_compiler DBL_EPSILON).
K_S = 18.420680743952367  # log(1e8)
DBL_EPSILON = 2.220446049250313e-16


class TemplateWeightError(Exception):
    """A true fault in the template weight computation."""


def runtime_weight(raw_weight: float) -> float:
    """The librime runtime phrase weight for one compiled-table entry.

    ``raw_weight`` is the decompiled table's third column — the *raw*
    dictionary/essay weight (the decompiler applies ``exp(stored)``), or 0.0
    for entries whose raw weight is 0 (the decompiler omits the column for
    those; librime compiled them to ``log(DBL_EPSILON)``).  The runtime
    phrase weight is ``log(raw) - kS``; the raw-0 sentinel maps to
    ``log(DBL_EPSILON) - kS``.
    """
    if raw_weight > 0.0:
        return math.log(raw_weight) - K_S
    if raw_weight == 0.0:
        return math.log(DBL_EPSILON) - K_S
    raise TemplateWeightError("invalid stored weight %r" % raw_weight)


def parse_decompiled_table(
        path: str) -> Dict[Tuple[str, str], Tuple[str, float]]:
    """Parse a ``rime_table_decompiler`` dump into the weight map.

    Returns ``{(simplified_text, code_no_spaces): (traditional_text,
    raw_weight)}``.  ``raw_weight`` is the stored table weight: ``log(raw)``
    for entries with a weight column, or 0.0 (the raw-0 sentinel) for
    entries whose weight column was omitted.  ``code_no_spaces`` removes the
    spaces librime's decompiler inserts between syllables
    (``xian zai`` -> ``xianzai``), matching the facts store's
    ``canonical_segment_input``.
    """
    if not os.path.isfile(path):
        raise TemplateWeightError("decompiled table not found: %s" % path)
    result = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("---") \
                    or line.startswith("name:"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            text, code = parts[0], parts[1]
            raw_weight = 0.0
            if len(parts) > 2 and parts[2]:
                try:
                    raw_weight = float(parts[2])
                except ValueError as error:
                    raise TemplateWeightError(
                        "invalid weight in decompiled table line %r"
                        % line) from error
            result[(match_text(text), code.replace(" ", ""))] = (text,
                                                                  raw_weight)
    if not result:
        raise TemplateWeightError("decompiled table is empty: %s" % path)
    return result


def weight_for(weight_map: Dict[Tuple[str, str], Tuple[str, float]],
               text: str,
               code: str) -> Optional[float]:
    """The librime runtime weight of one saved candidate, or None.

    ``None`` means the candidate is absent from the template table (the
    user-dict case, RISK-106-1): the event cannot be replayed under
    template weights.
    """
    entry = weight_map.get((match_text(text), code.replace(" ", "")))
    if entry is None:
        return None
    return runtime_weight(entry[1])
