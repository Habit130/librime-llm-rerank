#!/usr/bin/env python3
"""Strict-HLC walk-forward evaluation engine (Habit130/squirrel#70).

Given one frozen, read-only facts snapshot (a consistent copy taken with the
SQLite Online Backup API; never the live store) and one deterministic
representation provider (the #60 seam), this module replays every target
selection event in strict HLC total order under the exact oracle (#59):

- Score first, then add to memory: the target event's own commit is never
  visible to its own query (``as_of`` = the event's commit HLC, the whole
  commit excluded).  Only facts committed at-or-before that point and active
  at it (retraction as-of semantics) are visible.  No random split, no future
  leakage, no backfill from later retractions.
- Target labels always exclude retracted events; retracted events remain
  visible as history to queries before their retraction HLC.
- ``explicit_current`` and ``explicit_indexed`` are both primary targets.
- **Group-complete** (Habit130/squirrel#76/#77 rewrite, AC-77-v1 seam 3):
  an event enters the top-1 / MRR / mispromotion / safety / pollution /
  event-count gates iff its saved same-group competition size is ``< N``
  (``N = 32``).  The persisted ``competition_complete`` bit is NOT that
  gate: it is reported as a diagnostic only (a window may be marked
  complete yet hold a full size-32 group, and an unmarked window may still
  be a complete size-10 group).  Events that are not group-complete still
  provide positive historical evidence.
- Actionability, the cross-scheme actionable union, complete-competition
  coverage and the confirmation-source x confirmation-rank strata are all
  computed here; metric aggregation and bootstrap live in ``metrics.py`` /
  ``bootstrap.py``.

Engine decisions (recorded in the delivery decision record):

- The shadow baseline is the frozen live policy that produced the snapshot
  (γ=0, evidence disabled).  Its per-event outcome for the user's final
  selection is therefore **observed ground truth**, recorded as the
  confirmation position (``display_page``/``display_rank``): confirmation
  rank 1 means the baseline ranked the selection first.  No base scores are
  reconstructed.
- The *scheme* outcome is computed by re-ranking the recorded competition
  set under ``base_proxy + gamma*s_c``, where ``base_proxy`` is a
  deterministic reconstruction of the (unavailable) per-candidate base
  scores from the facts: the recorded confirmation position of the user's
  final selection (``display_page``/``display_rank``) is the frozen
  baseline's rank of that selection, so the reconstruction pins the
  selection at its recorded position and keeps the remaining candidates in
  recorded (merge) order around it.  At γ=0 the scheme ranking is then
  exactly the recorded confirmation position for every event (fixture-tested
  identity, including rank>1 events), so ``γ=0`` reproduces the shadow
  baseline; the report carries the recorded-order-vs-confirmation-rank
  agreement as a diagnostic of the reconstruction's fidelity.
- Empty-上文 events are a defined non-condition, not a fault: the #60
  seam declares no representation for an empty window (no phantom vector),
  so an event whose ``preceding_text`` is empty is unrepresentable — it
  never provides or receives evidence, is excluded from replayable targets
  (counted), and does not crash the run.  A non-empty context whose
  representation fails is a true fault and fails the engine loudly.
- Δ₁'s P10(margin_base) term needs per-candidate base scores, which the fact
  schema does not store; the engine reports that term as unavailable on real
  snapshots and enforces the ``Δ₁ <= 0.5`` hard cap, exactly like the
  "τ not calibratable" handling.  Synthetic fixtures inject base scores and
  pin the full Δ₁ semantics.

This module never writes raw text, candidate text or preceding text into
results: per-event records carry event ids, HLCs, numeric decompositions and
candidate indexes only.
"""

import math
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is required for the grid
    np = None

from oracle import (OracleError, OracleParams, match_text)

# Engine constants (pre-declared, versioned).
ENGINE_VERSION = "hlc-walkforward-eval-v2"
DEV_PREFIX_RATIO = 0.7   # tau calibration uses the earliest 70% of targets
MIN_HARD_NEGATIVE_QUERIES = 200
TAU_QUANTILES = (0.95, 0.975, 0.99, 0.995)
BOOTSTRAP_REPLICATES = 10000
BOOTSTRAP_SEED = 20260817
CI_LEVEL = 0.95
DELTA_ONE_CAP = 0.5
# Group-complete gate (spec #43 / #76 / #77): saved same-group competition
# size < GROUP_COMPLETE_N.  NOT the persisted competition_complete bit.
GROUP_COMPLETE_N = 32


class EngineError(Exception):
    """A true fault in the walk-forward engine inputs or invariants."""


# ---------------------------------------------------------------------------
# Snapshot loading (read-only; the caller passes a consistent copy path)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelectionEvent:
    """One stored selection event (target or history)."""

    event_id: str
    commit_id: str
    schema_id: str
    category: str
    canonical_segment_input: str
    final_selection_text: str
    preceding_text: str
    hlc: Tuple[int, int]
    confirmation_source: str
    competition_complete: bool
    display_rank: int
    display_page: int
    competition: Tuple[str, ...]
    retracted: bool

    @property
    def key(self):
        return (self.schema_id, self.category, self.canonical_segment_input)

    @property
    def group_complete(self):
        """Group-complete = saved same-group competition size < N (N=32).

        The #76/#77 rank-gate denominator.  The persisted
        ``competition_complete`` bit is a separate, diagnostic-only flag:
        it is not the group-complete gate (a full size-32 window may be
        marked complete; an unmarked window may still hold a complete
        size-10 group).
        """
        return len(self.competition) < GROUP_COMPLETE_N


class FrozenFacts:
    """Read-only wrapper over one consistent facts.sqlite3 copy.

    Mirrors the oracle's FactReader semantics for the replay queries and
    additionally exposes the competition candidate lists, confirmation
    fields and the retraction map needed by the engine.  Every access is a
    plain read; the file is a private copy, so nothing here can touch the
    live store.
    """

    def __init__(self, snapshot_path):
        self._path = os.path.abspath(snapshot_path)
        if not os.path.isfile(self._path):
            raise EngineError("snapshot not found: %s" % self._path)
        try:
            self._conn = sqlite3.connect(self._path, timeout=2.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA query_only=ON;")
        except sqlite3.Error as error:
            raise EngineError("cannot open snapshot: %s" % error)

    def close(self):
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def path(self):
        return self._path

    # -- identity -----------------------------------------------------------

    def identity(self):
        """(store_epoch, history_id, fact_schema_version, max HLC)."""
        try:
            rows = dict(self._conn.execute("SELECT key, value FROM meta"))
        except sqlite3.Error as error:
            raise EngineError("snapshot meta read failed: %s" % error)
        return {
            "store_epoch": rows.get("store_epoch"),
            "history_id": rows.get("history_id"),
            "fact_schema_version": rows.get("fact_schema_version"),
            "max_hlc": (int(rows.get("hlc_physical_ms", "-1")),
                        int(rows.get("hlc_logical", "-1"))),
        }

    # -- raw rows -----------------------------------------------------------

    def all_retractions(self):
        """commit_id -> retraction HLC for every recorded retraction."""
        try:
            rows = self._conn.execute(
                "SELECT commit_id, hlc_physical_ms, hlc_logical"
                " FROM retractions").fetchall()
        except sqlite3.Error as error:
            raise EngineError("snapshot retractions read failed: %s" % error)
        return {row["commit_id"]: (row["hlc_physical_ms"], row["hlc_logical"])
                for row in rows}

    def competition(self, event_id):
        """Recorded competition texts in recorded (merge) order.

        The oracle matches candidates by simplified-NFC text and, on a tie,
        attributes history evidence to the first normalized-equal
        candidate (oracle.compute_evidence enumerates candidates in order
        and breaks at the first match).  The engine mirrors that: texts
        that normalize equal are tolerated (e.g. 於/于 both simplify to 于),
        and every duplicate-aware lookup (selection index, base
        reconstruction) resolves to the first normalized-equal candidate,
        exactly like the oracle — never silently to a later one.
        """
        try:
            rows = self._conn.execute(
                "SELECT text FROM selection_candidates"
                " WHERE event_id = ? ORDER BY merge_order", (event_id,),
            ).fetchall()
        except sqlite3.Error as error:
            raise EngineError("snapshot candidates read failed: %s" % error)
        return tuple(row["text"] for row in rows)

    def events(self):
        """All stored events (active and retracted) as SelectionEvent.

        Ordering is by (hlc, event_id); retracted events carry
        ``retracted=True`` and remain visible as history to queries at or
        before their retraction HLC.
        """
        retracted = set(self.all_retractions())
        events = []
        try:
            rows = self._conn.execute(
                "SELECT * FROM selection_events").fetchall()
        except sqlite3.Error as error:
            raise EngineError("snapshot events read failed: %s" % error)
        for row in rows:
            events.append(SelectionEvent(
                event_id=row["event_id"],
                commit_id=row["commit_id"],
                schema_id=row["schema_id"],
                category=row["category"],
                canonical_segment_input=row["canonical_segment_input"],
                final_selection_text=row["final_selection_text"],
                preceding_text=row["preceding_text"] or "",
                hlc=(row["hlc_physical_ms"], row["hlc_logical"]),
                confirmation_source=row["confirmation_source"],
                competition_complete=bool(row["competition_complete"]),
                display_rank=int(row["display_rank"]),
                display_page=int(row["display_page"]),
                competition=self.competition(row["event_id"]),
                retracted=row["commit_id"] in retracted))
        events.sort(key=lambda e: (e.hlc, e.event_id))
        return events

    def target_events(self):
        """Targets = active (non-retracted) events in HLC order."""
        return [e for e in self.events() if not e.retracted]

    def commit_events(self, events):
        """commit_id -> event ids of that commit (whole-commit exclusion)."""
        by_commit = {}
        for event in events:
            by_commit.setdefault(event.commit_id, set()).add(event.event_id)
        return by_commit


# ---------------------------------------------------------------------------
# Vector table (one deterministic representation over the frozen snapshot)
# ---------------------------------------------------------------------------

class VectorTable:
    """event_id -> vector for every stored event, built once per provider.

    Vectors are produced by the #60/#61 provider seam (fixture provider in
    tests, hidden-state extractor on real snapshots).  Query vectors for an
    event's own preceding text are the same deterministic function of the
    raw text, so the table serves both the history side and the query side.

    Empty-上文 events are **unrepresentable**: the seam declares no
    representation for an empty window (no phantom EOS vector), so such an
    event maps to no vector (``vector(event_id)`` returns None) and is
    excluded from replay targets and from evidence.  Any other vector
    fault (non-finite, dimension mismatch, model error on a non-empty
    context) is a true engine fault and fails the whole table.
    """

    def __init__(self, events, provider):
        self._events = events
        self._provider = provider
        self._vectors = {}
        self._queries = {}
        self._dimension = provider.vector_dimension()
        for event in events:
            self._vectors[event.event_id] = self._forward(
                "event", event)

    def _forward(self, kind, event):
        if kind == "query" and not event.preceding_text:
            return None
        if kind == "event" and not event.preceding_text:
            return None
        try:
            if kind == "event":
                vector = self._provider.event_vector(event)
            else:
                vector = self._provider.query_vector(event.preceding_text)
        except Exception as error:  # noqa: BLE001 - fail closed
            raise EngineError("%s vector failed for %s: %s"
                              % (kind, event.event_id, error)) from error
        vector = tuple(float(value) for value in vector)
        if not vector or len(vector) != self._dimension:
            raise EngineError("%s vector dimension mismatch for %s"
                              % (kind, event.event_id))
        for value in vector:
            if not math.isfinite(value):
                raise EngineError("%s vector not finite for %s"
                                  % (kind, event.event_id))
        return vector

    def event_vector(self, event_id):
        """The event's representation, or None when unrepresentable (empty
        window); a missing entry for a representable event is a fault."""
        if event_id not in self._vectors:
            raise EngineError("no vector for event %s" % event_id)
        return self._vectors[event_id]

    def query_vector(self, event_id):
        vector = self._queries.get(event_id)
        if vector is not None or event_id in self._queries:
            return vector
        target = None
        for event in self._events:
            if event.event_id == event_id:
                target = event
                break
        if target is None:
            raise EngineError("no query vector for event %s" % event_id)
        vector = self._forward("query", target)
        self._queries[event_id] = vector
        return vector

    def dimension(self):
        return self._dimension


# ---------------------------------------------------------------------------
# Fast exact oracle (numpy-vectorized; bit-faithful to oracle.compute_evidence)
# ---------------------------------------------------------------------------

def _fast_cosine_matrix(query_vectors, event_vectors):
    """Cosine matrix (queries x events); vectors are L2-normalized."""
    return np.asarray(query_vectors, dtype=np.float64) @ np.asarray(
        event_vectors, dtype=np.float64).T


class FastEvidence:
    """Vectorized re-computation of the canonical oracle's evidence.

    Implements the exact spec #43 semantics with the same order of
    operations as ``oracle.compute_evidence`` (same-key active events,
    exact cosine, threshold relevance, usage age, final weight, top-K by
    weight, per-candidate m_c / M / s_c).  Bit-faithfulness to the oracle is
    pinned by ``test_fast_oracle_equivalence`` over synthetic fixtures with
    varied tau / H / K / k and retraction layouts.
    """

    def __init__(self, tau, k_evidence, half_life, saturation_k):
        self._tau = tau
        self._k = k_evidence
        self._h = half_life
        self._sat = saturation_k

    def _relevance(self, cosine):
        return np.maximum(np.minimum(
            (cosine - self._tau) / (1.0 - self._tau), 1.0), 0.0)

    def _age(self, usage_ages):
        if math.isinf(self._h):
            return np.ones(len(usage_ages), dtype=np.float64)
        return np.power(2.0, -np.asarray(usage_ages, dtype=np.float64)
                        / self._h)

    def run(self, query_vector, event_vectors, usage_ages, candidates,
            selection_texts):
        """Per-candidate evidence s for one query.

        ``event_vectors`` are the same-key active event vectors in HLC
        order, ``usage_ages`` their usage ages, ``candidates`` the current
        group's texts (raw) and ``selection_texts`` the simplified-NFC final
        selections of the history events (matching order).  Candidates are
        normalized exactly like the oracle, so a history selection
        contributes to a candidate iff the simplified-NFC texts match.
        Returns the per-candidate s list in candidate order.
        """
        if not event_vectors:
            return [0.0] * len(candidates)
        candidates = [match_text(c) for c in candidates]
        cosine = _fast_cosine_matrix([query_vector], event_vectors)[0]
        relevance = self._relevance(cosine)
        weight = relevance * self._age(usage_ages)
        passed = weight > 0.0
        if not passed.any():
            return [0.0] * len(candidates)
        order = np.argsort(-weight, kind="stable")
        kept = order[:self._k]
        mass = np.zeros(len(candidates), dtype=np.float64)
        for position in kept:
            if not passed[position]:
                continue
            text = selection_texts[position]
            for index, candidate in enumerate(candidates):
                if text == candidate:
                    mass[index] += float(weight[position])
                    break
        total = float(mass.sum())
        if total <= 0.0:
            return [0.0] * len(candidates)
        result = []
        for candidate_mass in mass:
            share = candidate_mass / total
            saturation = candidate_mass / (candidate_mass + self._sat)
            result.append(float(share * saturation))
        return result


# ---------------------------------------------------------------------------
# Walk-forward replay
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventOutcome:
    """Per-event replay outcome (event ids and numbers only, no raw text).

    - ``baseline_rank``: 1 or 2 — the recorded confirmation rank of the
      user's final selection under the frozen shadow baseline (1 = the
      baseline displayed the selection first).
    - ``scheme_rank``: the scheme's rank of the final selection under
      base_proxy + gamma*s_c; None when the selection is absent from the
      recorded competition set.
    - ``actionable``: the scheme held non-zero evidence for at least one
      candidate of the group at replay time (score-first memory) — the
      spec's per-candidate actionable definition; kept history matching no
      candidate contributes mass but no candidate evidence.
    - ``kept_ids`` / ``kept_weights`` / ``kept_matches``: kept contribution
      event ids, a_i and the matched candidate index (-1 when the history
      selection matched no candidate), needed for pollution decomposition.
    - ``key``: the choice-problem key tuple, for key-clustered bootstrap
      and frequency-band stratification.
    """

    event_id: str
    hlc: Tuple[int, int]
    key: Tuple[str, str, str]
    confirmation_source: str
    competition_complete: bool
    group_complete: bool
    baseline_rank: int
    scheme_rank: Optional[int]
    actionable: bool
    total_mass: float
    candidate_count: int
    selection_index: Optional[int]
    kept_ids: Tuple[str, ...]
    kept_weights: Tuple[float, ...]
    kept_matches: Tuple[int, ...]


class WalkForwardReplay:
    """Replay all targets in HLC order, scoring before adding to memory."""

    def __init__(self, facts, vectors):
        if not isinstance(facts, FrozenFacts):
            raise EngineError("facts must be a FrozenFacts")
        if not isinstance(vectors, VectorTable):
            raise EngineError("vectors must be a VectorTable")
        self._facts = facts
        self._vectors = vectors
        self._events = facts.events()
        self._commit_events = facts.commit_events(self._events)
        self._retractions = facts.all_retractions()

    def events(self):
        return self._events

    def targets(self):
        """Replayable targets = active (non-retracted) events with a
        representable 上文 (empty-上文 events are unrepresentable and are
        excluded and counted, per the engine's non-condition rule)."""
        return [e for e in self._events
                if not e.retracted and e.preceding_text]

    def unrepresentable_targets(self):
        """Active events excluded from replay because their 上文 is empty."""
        return [e for e in self._events
                if not e.retracted and not e.preceding_text]

    def _same_key_active(self, target):
        """Same-key events active at the target's HLC, whole commit excluded.

        Mirrors the canonical oracle's as-of read: committed at-or-before
        the query point, no retraction at-or-before it; the target's whole
        commit is excluded (score first, then add to memory).  Events with
        an empty 上文 are unrepresentable and cannot provide evidence, so
        they are dropped.  Returns events in HLC order.
        """
        physical, logical = target.hlc
        result = []
        for event in self._events:
            if event.commit_id == target.commit_id:
                continue
            if not event.preceding_text:
                continue
            if event.hlc > target.hlc:
                continue
            retracted = self._retractions.get(event.commit_id)
            if retracted is not None and retracted <= target.hlc:
                continue
            if event.key == target.key:
                result.append(event)
        result.sort(key=lambda e: (e.hlc, e.event_id))
        return result

    def replay(self, params, gamma):
        """Run the full HLC replay under one parameter configuration.

        Returns ``(outcomes, summary)``: per-event outcomes in HLC order and
        replay-level counts (coverage, actionable, strata sizes, excluded
        unrepresentable targets).
        """
        if not isinstance(params, OracleParams):
            raise EngineError("params must be an OracleParams")
        if not (isinstance(gamma, (int, float)) and gamma >= 0.0):
            raise EngineError("gamma must be a non-negative number")

        fast = FastEvidence(params.tau, params.k_evidence,
                            params.half_life, params.saturation_k)
        outcomes = []
        for target in self.targets():
            history = self._same_key_active(target)
            query_vector = self._vectors.query_vector(target.event_id)
            if query_vector is None:
                raise EngineError("representable target has no query vector "
                                  "for %s" % target.event_id)
            event_vectors = []
            for h in history:
                vector = self._vectors.event_vector(h.event_id)
                if vector is None:
                    raise EngineError("representable history event has no "
                                      "vector for %s" % h.event_id)
                event_vectors.append(vector)
            usage_ages = list(range(len(history) - 1, -1, -1))
            selection_texts = [match_text(h.final_selection_text)
                               for h in history]
            s = fast.run(query_vector, event_vectors, usage_ages,
                         list(target.competition), selection_texts)
            total_mass, kept_ids, kept_weights, kept_matches = \
                self._kept_decomposition(
                    fast, query_vector, event_vectors, usage_ages,
                    selection_texts, history, target)
            baseline_rank = (1 if (target.display_page == 1
                                   and target.display_rank == 1) else 2)
            scheme_rank = self._scheme_rank(target, s, gamma)
            selection_index = self._selection_index(target)
            # Actionable = the scheme's memory held non-zero evidence for
            # AT LEAST ONE candidate of the current group (spec #43: "足以
            # 对当前至少一个候选形成非零检索证据的历史").  Kept history
            # whose selection matches no candidate contributes mass but no
            # candidate evidence, so it is not actionable.
            actionable = any(value > 0.0 for value in s)
            outcomes.append(EventOutcome(
                event_id=target.event_id,
                hlc=target.hlc,
                key=target.key,
                confirmation_source=target.confirmation_source,
                competition_complete=target.competition_complete,
                group_complete=target.group_complete,
                baseline_rank=baseline_rank,
                scheme_rank=scheme_rank,
                actionable=actionable,
                total_mass=total_mass,
                candidate_count=len(target.competition),
                selection_index=selection_index,
                kept_ids=kept_ids,
                kept_weights=kept_weights,
                kept_matches=kept_matches))

        summary = self._summarize(outcomes, gamma)
        return outcomes, summary

    def _kept_decomposition(self, fast, query_vector, event_vectors,
                            usage_ages, selection_texts, history, target):
        """(M, kept_ids, kept_weights, kept_matches) for the query.

        M is the total evidence mass of kept events (spec's M = sum m_c);
        kept_ids / kept_weights / kept_matches mirror the oracle's kept
        contributions in order, with the matched candidate index (or -1).
        """
        if not event_vectors:
            return 0.0, (), (), ()
        candidates = [match_text(c) for c in target.competition]
        cosine = _fast_cosine_matrix([query_vector], event_vectors)[0]
        relevance = fast._relevance(cosine)
        weight = relevance * fast._age(usage_ages)
        passed = weight > 0.0
        if not passed.any():
            return 0.0, (), (), ()
        order = np.argsort(-weight, kind="stable")
        kept = order[:fast._k]
        ids = []
        weights = []
        matches = []
        mass = 0.0
        for position in kept:
            if not passed[position]:
                continue
            text = selection_texts[position]
            matched = -1
            for index, candidate in enumerate(candidates):
                if text == candidate:
                    matched = index
                    break
            ids.append(history[position].event_id)
            weights.append(float(weight[position]))
            matches.append(matched)
            mass += float(weight[position])
        return mass, tuple(ids), tuple(weights), tuple(matches)

    @staticmethod
    def _selection_index(target):
        """Candidate index (0-based) of the final selection in the group.

        Resolves to the FIRST candidate whose simplified-NFC text equals
        the selection's simplified-NFC text, mirroring the oracle's
        match-text attribution (duplicates like 於/于 both simplify to
        于 resolve to the first, exactly like compute_evidence).
        """
        selection = match_text(target.final_selection_text)
        for index, text in enumerate(target.competition):
            if match_text(text) == selection:
                return index
        return None

    @staticmethod
    def _base_reconstruction(target):
        """Deterministic base-score reconstruction from the facts (D3).

        The facts persist only the recorded competition order (merge order)
        and the recorded confirmation position of the final selection
        (``display_rank``/``display_page``).  The frozen γ=0 baseline
        displayed the selection at that position, so the reconstruction
        pins the selection at ``display_rank`` on page 1 and keeps the
        remaining candidates in recorded order around it; the selection's
        own relative order against other candidates is therefore exactly
        the recorded confirmation position, and γ=0 reproduces the shadow
        baseline.

        The selection's candidate index is the first simplified-NFC-equal
        candidate (same rule as the oracle's match attribution), so
        normalized duplicates (於/于) resolve deterministically and
        consistently with evidence attribution.

        Returns a list of ``(index, base_rank)`` in pinned order where
        ``base_rank`` is 1-based, or None when the confirmation position is
        not reconstructable from the facts (selection absent from the
        recorded competition, or ``display_page`` > 1 — the absolute rank
        on later pages depends on the page size, which the facts do not
        record; those events are excluded from scheme ranking and reported
        in the reconstruction-fidelity diagnostic).
        """
        selection = match_text(target.final_selection_text)
        selection_index = None
        for index, text in enumerate(target.competition):
            if match_text(text) == selection:
                selection_index = index
                break
        if selection_index is None:
            return None
        if target.display_page != 1:
            return None
        confirmation_rank = target.display_rank
        if not 1 <= confirmation_rank <= len(target.competition):
            raise EngineError(
                "confirmation position %d outside competition of %d for %s"
                % (confirmation_rank, len(target.competition),
                   target.event_id))
        ordered = [index for index in range(len(target.competition))
                   if index != selection_index]
        ordered.insert(confirmation_rank - 1, selection_index)
        # Renumber 1..n in pinned order.
        return [(index, rank)
                for rank, index in enumerate(ordered, start=1)]

    @classmethod
    def _scheme_rank(cls, target, s_by_index, gamma):
        """Scheme rank of the final selection under base_proxy + gamma*s.

        base_proxy is the deterministic base reconstruction pinned to the
        recorded confirmation position (see ``_base_reconstruction``), so
        at γ=0 the scheme ranking is exactly the recorded confirmation
        position (fixture-tested identity for rank 1 and rank >1 events).
        ``s_by_index`` maps candidate index -> bounded evidence; ties keep
        the reconstructed base order.  Returns None when the base position
        is not reconstructable (page > 1 or selection absent).
        """
        reconstruction = cls._base_reconstruction(target)
        if reconstruction is None:
            return None
        selection_candidate_index = cls._selection_index(target)
        if selection_candidate_index is None:
            return None
        selection_rank = None
        base_score = {}
        scores = []
        for index, rank in reconstruction:
            # Base score proxy: rank 1 is the largest base score.
            base_score[index] = -float(rank)
        for index, rank in reconstruction:
            s = s_by_index[index] if index < len(s_by_index) else 0.0
            score = base_score[index] + gamma * s
            scores.append((score, index, rank))
            if index == selection_candidate_index:
                selection_score = score
                selection_rank = rank
        if selection_rank is None:
            return None
        rank = 1
        for score, index, base_rank in scores:
            if score > selection_score:
                rank += 1
            elif score == selection_score and base_rank < selection_rank:
                rank += 1
        return rank

    def _summarize(self, outcomes, gamma):
        replayable = len(outcomes)
        group_complete = [o for o in outcomes if o.group_complete]
        bit_complete = [o for o in outcomes if o.competition_complete]
        actionable = [o for o in outcomes if o.actionable]
        coverage = (len(group_complete) / replayable) if replayable else 0.0
        strata = {}
        for o in outcomes:
            if not o.actionable:
                continue
            key = "%s/%s" % (o.confirmation_source,
                             "1" if o.baseline_rank == 1 else ">1")
            strata[key] = strata.get(key, 0) + 1
        hlc_range = None
        if outcomes:
            hlc_range = {
                "min": [outcomes[0].hlc[0], outcomes[0].hlc[1]],
                "max": [outcomes[-1].hlc[0], outcomes[-1].hlc[1]],
            }
        # Reconstruction fidelity: the recorded confirmation rank vs the
        # rank the scheme would give the selection at γ=0 (pinned to the
        # recorded position by construction — always equal for page-1
        # events).  The diagnostic reports how many events were excluded
        # from scheme ranking because the base position is not
        # reconstructable (page > 1, or selection absent from the recorded
        # competition).
        reconstructable = sum(1 for o in outcomes
                              if o.scheme_rank is not None)
        return {
            "replayable_targets": replayable,
            "unrepresentable_targets": len(self.unrepresentable_targets()),
            "group_complete": len(group_complete),
            "competition_complete_bit": len(bit_complete),
            "group_complete_n": GROUP_COMPLETE_N,
            "actionable": len(actionable),
            "coverage": coverage,
            "strata": strata,
            "hlc_range": hlc_range,
            "scheme_rank_reconstructable": reconstructable,
            "gamma": gamma,
        }


# ---------------------------------------------------------------------------
# Gate helpers shared by the grid scan
# ---------------------------------------------------------------------------

def delta_one(gamma, k):
    """Δ₁ = γ/(1+k): the maximum single-event evidence increment."""
    return gamma / (1.0 + k)


def margin_base_unavailable():
    """Real snapshots do not persist per-candidate base scores.

    The spec's P10(margin_base) term cannot be computed from facts; the
    engine reports this state explicitly (mirroring the τ not-calibratable
    handling) instead of inventing a margin.  Synthetic fixtures inject base
    scores and pin the full Δ₁ semantics.
    """
    return {"available": False,
            "reason": "facts do not persist per-candidate base scores"}
