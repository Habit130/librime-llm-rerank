#!/usr/bin/env python3
"""Exact retrieval-evidence oracle (Habit130/squirrel#59).

The single ground truth for all downstream semantic-memory evaluation: given
the immutable selection facts in a facts.sqlite3 store (written by the C++
plugin) and deterministic per-event vectors supplied by the caller, it
computes the bounded retrieval evidence s_c for every candidate of one
current rerank group, exactly as pinned by the parent spec (#43):

  choice_problem_key = schema_id + category + canonical_segment_input
  r_i = clamp((cos_i - tau) / (1 - tau), 0, 1)
  u_i = count of same-key active events with order > order(i)
  d_i = 2 ** (-u_i / H)
  a_i = r_i * d_i
  kept = the at most K_evidence events above the threshold with the
         largest a_i                              # after computing ALL
  m_c = sum(a_i for kept events whose simplified-NFC selection == candidate c)
  M   = sum(m_c)
  s_c = (m_c / M) * m_c / (m_c + k)  if M > 0 else 0

Deliberate semantics (all are pinned by spec #43 and must not drift):

- Only events with the same choice-problem key provide evidence, and only the
  history's final selection provides positive evidence; unselected candidates
  never become negative evidence.
- All same-key active events are fully evaluated (cosine, threshold
  relevance, usage age, final weight) BEFORE the top-K cut.  Taking a cosine
  top-K first and aging afterwards is a different (non-equivalent) order and
  is rejected here.
- Usage age counts only same-key *active* events that are later in HLC order.
  Calendar time never decays an event; retracted events leave both the
  evidence set and the age clock at their retraction HLC.
- Retraction and commit visibility are as-of semantics exactly mirroring the
  C++ FactStore::QueryActiveEventsAsOf: an event is visible at query point
  (P, L) iff committed at-or-before it and no retraction of its commit took
  effect at-or-before it.  Future retractions never backfill an earlier
  replay.
- Zero evidence (empty store, no same-key events, nothing above tau, nothing
  matching the current group) is a successful result, never an error.  A
  missing or malformed store, missing vectors or non-finite values are true
  faults and raise OracleError.

Candidate and segment-input text is matched after NFC normalization plus a
traditional-to-simplified conversion.  The conversion is OpenCC's t2s preset
(TSCharacters + TSPhrases) using the exact dictionary files vendored under
opencc_data/, copied from the OpenCC revision librime pins
(ver.1.1.2-148-g556ed224, Apache-2.0) - the same data librime's zh_hans
simplifier uses.  The algorithm is longest phrase match first, single
character fallback, first alternative on ambiguity; this matches the
conversion librime applies to candidates before they are seen or recorded.
The oracle is model-free and stdlib-only (no numpy, no MLX).

The oracle never outputs raw text, embeddings or candidate text: results
carry event ids, numeric decompositions and candidate indexes only.
"""

import math
import os
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import (Callable, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence, Tuple)

_OPENCC_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "opencc_data")


class OracleError(Exception):
    """A true fault in the oracle's inputs or the fact store.

    Distinct from zero evidence: callers must treat OracleError as a failure
    (pass-through), never as an empty result.
    """


# ---------------------------------------------------------------------------
# Simplified-Chinese conversion (OpenCC t2s data, vendored)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _T2SDictionaries:
    """Longest-match phrase table and single-character table.

    phrase_by_first maps the first character of each phrase to a list of
    (phrase, conversion) pairs sorted by phrase length descending, so the
    longest match at a position is found by scanning that short list.
    """

    phrase_by_first: Mapping[str, Sequence[Tuple[str, str]]]
    char_map: Mapping[str, str]


_T2S = None  # module-level singleton; built lazily


def _load_t2s() -> _T2SDictionaries:
    global _T2S
    if _T2S is not None:
        return _T2S
    phrase_by_first: Dict[str, List[Tuple[str, str]]] = {}
    char_map: Dict[str, str] = {}
    for filename, is_char_table in (("TSPhrases.txt", False),
                                    ("TSCharacters.txt", True)):
        with open(os.path.join(_OPENCC_DATA_DIR, filename),
                  encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                key, sep, values = line.partition("\t")
                if not sep or not key or not values:
                    raise OracleError(
                        "malformed dictionary line in %s: %r"
                        % (filename, line[:40]))
                first = values.split(" ")[0]
                if is_char_table:
                    if len(key) != 1:
                        raise OracleError(
                            "single-char dictionary key is not one char: %r"
                            % key)
                    char_map[key] = first
                else:
                    if len(key) < 2:
                        raise OracleError(
                            "phrase dictionary key is not multi-char: %r"
                            % key)
                    phrase_by_first.setdefault(key[0], []).append(
                        (key, first))
    # Longest phrase first for every first character.
    for bucket in phrase_by_first.values():
        bucket.sort(key=lambda item: len(item[0]), reverse=True)
    _T2S = _T2SDictionaries(phrase_by_first=dict(phrase_by_first),
                            char_map=dict(char_map))
    return _T2S


def simplify(text):
    """OpenCC t2s conversion: longest phrase match, char fallback.

    Deterministic pure function; unknown characters pass through unchanged.
    """
    if not text:
        return text
    t2s = _load_t2s()
    out = []
    position = 0
    while position < len(text):
        candidates = t2s.phrase_by_first.get(text[position])
        matched = False
        if candidates is not None:
            for phrase, converted in candidates:
                if text.startswith(phrase, position):
                    out.append(converted)
                    position += len(phrase)
                    matched = True
                    break
        if matched:
            continue
        converted = t2s.char_map.get(text[position])
        out.append(converted if converted is not None else text[position])
        position += 1
    return "".join(out)


def canonicalize_segment_input(text):
    """Conservative segment-input normalization (spec #43).

    Only NFC plus ASCII lowercase; apostrophes, spaces, abbreviated pinyin,
    fuzzy-pinyin and correction differences are preserved: "xi'an" must never
    merge with "xian".
    """
    if not text:
        return text
    lowered = "".join(chr(ord(character) + 32)
                      if "A" <= character <= "Z" else character
                      for character in text)
    return unicodedata.normalize("NFC", lowered)


def match_text(text):
    """Candidate-text normalization: simplified conversion after NFC.

    Matching uses the exact simplified-NFC text; no case folding, no variant
    merging, no edit distance.
    """
    return simplify(unicodedata.normalize("NFC", text))


def choice_problem_key(schema_id, category, canonical_segment_input):
    """The spec-fixed choice-problem key tuple.

    Both the query side and the stored-event side must derive their key with
    the same function.
    """
    return (schema_id, category,
            canonicalize_segment_input(canonical_segment_input))


# ---------------------------------------------------------------------------
# Oracle parameters and query
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OracleParams:
    """Evidence aggregation parameters (spec #43 "检索证据公式")."""

    tau: float                  # relevance threshold; r_i is 0 when cos <= tau
    k_evidence: int             # K_evidence: max kept events by final weight
    half_life: float            # H: usage-age half life, > 0 or float("inf")
    saturation_k: float         # k: per-candidate saturation, > 0

    def __post_init__(self):
        if not (0.0 <= self.tau < 1.0):
            raise OracleError("tau must satisfy 0 <= tau < 1")
        if not (isinstance(self.k_evidence, int) and self.k_evidence >= 1):
            raise OracleError("k_evidence must be a positive integer")
        if not (math.isinf(self.half_life)
                or (isinstance(self.half_life, (int, float))
                    and self.half_life > 0.0)):
            raise OracleError("half_life must be > 0 or infinity")
        if math.isinf(self.half_life) and self.half_life < 0:
            raise OracleError("half_life must be positive or +infinity")
        if not (isinstance(self.saturation_k, (int, float))
                and math.isfinite(self.saturation_k)
                and self.saturation_k > 0.0):
            raise OracleError("saturation_k must be a finite positive number")


@dataclass(frozen=True)
class OracleQuery:
    """One retrieval query for a current rerank group.

    candidates are the current group's word candidates in original merge
    order; the group's segment input is the caller-provided canonical segment
    input (the oracle re-derives the key with the same conservative
    normalization).  as_of is the HLC query point; None means the store's
    current clock (all committed facts, all retractions applied).
    exclude_event_ids is for walk-forward replay of a target event that must
    not be visible to its own scoring ("score first, then add to memory").
    """

    schema_id: str
    canonical_segment_input: str
    candidates: Sequence[str]
    query_vector: Sequence[float]
    category: str = "word"
    as_of: Optional[Tuple[int, int]] = None
    exclude_event_ids: FrozenSet[str] = frozenset()

    def __post_init__(self):
        if not self.schema_id:
            raise OracleError("schema_id must not be empty")
        if not self.category:
            raise OracleError("category must not be empty")
        if not self.candidates:
            raise OracleError("query needs at least one candidate")
        if not self.query_vector:
            raise OracleError("query_vector must not be empty")
        if self.as_of is not None:
            if (len(self.as_of) != 2 or self.as_of[0] < 0
                    or self.as_of[1] < 0):
                raise OracleError(
                    "as_of must be (physical_ms >= 0, logical >= 0)")
        for value in self.query_vector:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise OracleError(
                    "query_vector must contain only finite numbers")

    @property
    def key(self):
        return choice_problem_key(self.schema_id, self.category,
                                  self.canonical_segment_input)


# ---------------------------------------------------------------------------
# Read-only fact access mirroring the C++ store semantics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    commit_id: str
    schema_id: str
    canonical_segment_input: str
    category: str
    final_selection_text: str
    hlc: Tuple[int, int]

    @property
    def key(self):
        return choice_problem_key(self.schema_id, self.category,
                                  self.canonical_segment_input)


class FactReader:
    """Read-only view over one facts.sqlite3 store.

    Mirrors FactStore::QueryActiveEventsAsOf exactly: same SQL shape, same
    at-or-before HLC comparison for commits and retractions, same
    (physical, logical, event_id) ordering.
    """

    def __init__(self, db_path):
        if not os.path.isfile(db_path):
            raise OracleError("fact store not found: %s" % db_path)
        try:
            self._conn = sqlite3.connect("file:%s?mode=ro" % db_path,
                                         uri=True, timeout=0)
        except sqlite3.Error as error:
            raise OracleError("cannot open fact store: %s" % error)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def default_as_of(self):
        """The store's current HLC clock; the natural 'now' query point."""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'hlc_physical_ms';").fetchone()
        row_logical = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'hlc_logical';").fetchone()
        if row is None or row_logical is None:
            raise OracleError("fact store meta clock is missing")
        try:
            physical = int(row["value"])
            logical = int(row_logical["value"])
        except (TypeError, ValueError) as error:
            raise OracleError("fact store meta clock is malformed") from error
        if physical < 0 or logical < 0:
            raise OracleError("fact store meta clock is malformed")
        return (physical, logical)

    def read_fact_identity(self):
        """Durable identity + max change HLC from the meta table.

        Mirrors FactHandle.read_identity: store_epoch and the store's current
        clock (the max change HLC).  A missing or malformed identity is a
        true fault, never a zero-evidence result.
        """
        try:
            rows = dict(self._conn.execute("SELECT key, value FROM meta"))
        except sqlite3.Error as error:
            raise OracleError("fact store meta read failed: %s" % error)
        store_epoch = rows.get("store_epoch")
        try:
            physical = int(rows.get("hlc_physical_ms", "-1"))
            logical = int(rows.get("hlc_logical", "-1"))
        except (TypeError, ValueError) as error:
            raise OracleError("fact store meta clock is malformed") from error
        if not store_epoch or physical < 0 or logical < 0:
            raise OracleError("fact store identity is incomplete")
        return (store_epoch, physical, logical)

    def read_active_events(self, as_of):
        """All events active at the query point, in HLC order.

        SQL mirrors FactStore::QueryActiveEventsAsOf, including the
        at-or-before comparison for both the commit and the retraction side.
        """
        physical, logical = as_of
        try:
            rows = self._conn.execute(
                "SELECT e.event_id, e.commit_id, e.schema_id,"
                " e.canonical_segment_input, e.category,"
                " e.final_selection_text, e.hlc_physical_ms, e.hlc_logical"
                " FROM selection_events e"
                " WHERE (e.hlc_physical_ms < ?1 OR (e.hlc_physical_ms = ?1"
                "        AND e.hlc_logical <= ?2))"
                " AND NOT EXISTS(SELECT 1 FROM retractions r"
                "                WHERE r.commit_id = e.commit_id"
                "                  AND (r.hlc_physical_ms < ?1"
                "                       OR (r.hlc_physical_ms = ?1"
                "                           AND r.hlc_logical <= ?2)))"
                " ORDER BY e.hlc_physical_ms, e.hlc_logical, e.event_id;",
                (physical, logical)).fetchall()
        except sqlite3.Error as error:
            raise OracleError("fact store query failed: %s" % error)
        events = []
        for row in rows:
            events.append(StoredEvent(
                event_id=row["event_id"],
                commit_id=row["commit_id"],
                schema_id=row["schema_id"],
                canonical_segment_input=row["canonical_segment_input"],
                category=row["category"],
                final_selection_text=row["final_selection_text"],
                hlc=(row["hlc_physical_ms"], row["hlc_logical"])))
        return events


# ---------------------------------------------------------------------------
# Evidence computation
# ---------------------------------------------------------------------------

def _as_float_vector(values, label):
    vector = tuple(float(value) for value in values)
    for value in vector:
        if not math.isfinite(value):
            raise OracleError("%s contains a non-finite value" % label)
    if not vector:
        raise OracleError("%s is empty" % label)
    return vector


def _cosine(query_vector, event_vector):
    dot = 0.0
    query_norm = 0.0
    event_norm = 0.0
    for query_value, event_value in zip(query_vector, event_vector):
        dot += query_value * event_value
        query_norm += query_value * query_value
        event_norm += event_value * event_value
    if query_norm == 0.0 or event_norm == 0.0:
        raise OracleError("cosine requires non-zero vectors")
    return dot / math.sqrt(query_norm * event_norm)


def _age_factor(usage_age, half_life):
    if math.isinf(half_life):
        return 1.0
    return 2.0 ** (-usage_age / half_life)


def compute_evidence(reader, params, query, vector_for):
    """Exact retrieval evidence for one query (the canonical oracle).

    vector_for is a callable mapping event_id to the event's deterministic
    vector (a sequence of floats); a missing vector, a dimension mismatch or
    a non-finite value is a true fault (OracleError), never silent evidence.

    Order of operations (spec #43 "精确 oracle"):
      1. same choice-problem key, active as of the query point
      2. exact cosine, r_i, current d_i and a_i for EVERY same-key active
         event
      3. top K_evidence by a_i
      4. per-candidate aggregation m_c / M / s_c
    """
    if not isinstance(params, OracleParams):
        raise OracleError("params must be an OracleParams")
    if not isinstance(query, OracleQuery):
        raise OracleError("query must be an OracleQuery")
    as_of = query.as_of if query.as_of is not None else reader.default_as_of()
    query_vector = _as_float_vector(query.query_vector, "query_vector")
    candidates = tuple(match_text(candidate) for candidate in query.candidates)

    same_key = []
    for event in reader.read_active_events(as_of):
        if event.event_id in query.exclude_event_ids:
            continue
        if event.key == query.key:
            same_key.append(event)
    same_key.sort(key=lambda event: (event.hlc, event.event_id))

    contributions = []
    for index, event in enumerate(same_key):
        try:
            vector = vector_for(event.event_id)
        except Exception as error:
            raise OracleError(
                "vector lookup failed for event %s" % event.event_id
            ) from error
        vector = _as_float_vector(
            vector, "vector for event %s" % event.event_id)
        if len(vector) != len(query_vector):
            raise OracleError(
                "vector dimension mismatch for event %s: %d vs query %d"
                % (event.event_id, len(vector), len(query_vector)))
        cosine = _cosine(query_vector, vector)
        relevance = min(max((cosine - params.tau) / (1.0 - params.tau), 0.0),
                        1.0)
        usage_age = len(same_key) - 1 - index
        age_factor = _age_factor(usage_age, params.half_life)
        weight = relevance * age_factor
        normalized_selection = match_text(event.final_selection_text)
        matched = -1
        for candidate_index, candidate in enumerate(candidates):
            if normalized_selection == candidate:
                matched = candidate_index
                break
        contributions.append((event, cosine, relevance, usage_age,
                              age_factor, weight, matched))

    # Threshold filter (r_i > 0, i.e. a_i > 0), then at most K_evidence by
    # final event weight a_i; deterministic tie-break by HLC order.
    passed = [entry for entry in contributions if entry[5] > 0.0]
    kept = sorted(passed, key=lambda entry:
                  (-entry[5], entry[0].hlc, entry[0].event_id))
    kept = kept[:params.k_evidence]

    m = [0.0] * len(candidates)
    for entry in kept:
        if entry[6] >= 0:
            m[entry[6]] += entry[5]
    total_mass = sum(m)

    candidate_evidence = []
    for candidate_index, candidate_mass in enumerate(m):
        if total_mass > 0.0:
            share = candidate_mass / total_mass
            saturation = candidate_mass / (
                candidate_mass + params.saturation_k)
            s = share * saturation
        else:
            s = 0.0
        candidate_evidence.append((candidate_index, candidate_mass, s))

    return OracleResult(
        query_point=as_of,
        same_key_active=len(same_key),
        kept=tuple(EventContribution(
            event_id=entry[0].event_id,
            commit_id=entry[0].commit_id,
            hlc=entry[0].hlc,
            cosine=entry[1],
            relevance=entry[2],
            usage_age=entry[3],
            age_factor=entry[4],
            weight=entry[5],
            matched_candidate=entry[6]) for entry in kept),
        candidates=tuple(CandidateEvidence(
            index=index, m=mass, s=s)
            for index, mass, s in candidate_evidence),
        total_mass=total_mass,
        derived_key=query.key)


@dataclass(frozen=True)
class EventContribution:
    """One kept event's full numeric decomposition (no raw text)."""

    event_id: str
    commit_id: str
    hlc: Tuple[int, int]
    cosine: float
    relevance: float   # r_i
    usage_age: int     # u_i
    age_factor: float  # d_i
    weight: float      # a_i
    matched_candidate: int  # index into the query's candidates; -1 when none


@dataclass(frozen=True)
class CandidateEvidence:
    """Per-candidate aggregation; s is the bounded retrieval evidence."""

    index: int
    m: float  # m_c
    s: float  # s_c in [0, 1)


@dataclass(frozen=True)
class OracleResult:
    """The oracle's answer: zero evidence is a valid, successful answer."""

    query_point: Tuple[int, int]
    same_key_active: int
    kept: Tuple[EventContribution, ...]
    candidates: Tuple[CandidateEvidence, ...]
    total_mass: float  # M
    derived_key: Tuple[str, str, str]

    def s_for(self, candidate_index):
        for candidate in self.candidates:
            if candidate.index == candidate_index:
                return candidate.s
        return None
