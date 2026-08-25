#!/usr/bin/env python3
"""Candidate-conditioned suffix walk-forward engine (Habit130/squirrel#157, AC-157-v1).

The exact walk-forward (wiring onto the #77 seam; AC-157-v1 "wiring" is not
frozen, this module is that wiring) drives the three frozen routes
(``dedicated_qwen3_embedding_0_6b``, ``qwen_l28_candidate_span_mean``,
``dedicated_bge_m3``) over a claim-time read-only Online-Backup snapshot
split at the frozen HLC cutoff ``[1787065441087, 0]``:

- **Payload** (all routes): ``last64(preceding) + candidate``, no separator
  (ADR-0003 / #109 / #110).  L28 pools the candidate token span
  ``[start, start+count)`` via ``candidate_span_mean``; whole-payload
  pooling is a contract failure (the provider seam owns this; the report
  fingerprints it).
- **Query side**: Qwen3-emb uses the frozen English instruction
  ``Represent the candidate-conditioned query for semantic retrieval.`` +
  newline + payload; BGE none; L28 none.  **Document/history side**: no
  instruction (the provider seam owns this too).
- **Split**: events with ``hlc <= [1787065441087, 0]`` = development prefix
  (τ calibration + grid selection only); strictly later events = the suffix
  claim set (quality/safety gates only).  Folding the suffix into
  development is a contract failure.
- **Snapshot**: a fresh read-only Online Backup / facts copy is taken at
  claim (SN-157-1; the #77/#155 prefix files cannot be the only store).
  Missing snapshot -> environment blocker.  No suffix events past the
  cutoff -> **数据不足** (legal terminal, not an implementation failure;
  RISK-157-2).
- **τ**: per route only from prefix query-level hard negatives (>= 200
  queries, Q95/Q97.5/Q99/Q99.5); below that ``not_calibratable`` and the
  route leaves the shortlist; no τ is invented (AC-157-3; RISK-157-3).
- **Grid**: H in {8,32,128,512,inf}; K_evidence in {8,16,32,64}; gamma in
  {0.5,1,2,4}; k in {1,3,7}; alpha = 0 (AC-106-v2).  No extra cells, no
  continuous optimizer.
- **Rank denominator**: saved same-group competition size < 32
  (group-complete); the persisted ``competition_complete`` bit is a
  diagnostic only.  Shadow baseline: same events/set, alpha=0, gamma=0.
- **Cross-route**: comparisons use the common actionable union; an event
  without evidence for a route's scheme scores as that route's shadow
  baseline.
- **Public-B accuracy (11953/14725) and the personal 2x2 r never enter
  decide_final, tie-breaking or suffix-rank interpretation** (AC-157-5).

Strict-HLC walk-forward semantics are preserved from the #77 seam: score
first, then add to memory; the target's own whole commit is excluded;
retractions apply as-of and never backfill.

No raw text is produced: per-event records carry event ids, HLCs, choice-
problem key hashes, numeric decompositions and candidate indexes only.
"""

import math
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from oracle import OracleParams, match_text

# Engine identity (AC-157-v1 contract).
CONTRACT_ID = "AC-157-v1"
ENGINE_VERSION = "suffix-walkforward-v1"
# Frozen HLC split (issue #157 body): prefix inclusive; suffix = strictly
# later.  Events are ordered by (hlc, event_id).
PREFIX_HLC_MAX_INCLUSIVE = (1787065441087, 0)
# The three frozen routes (issue #157 body).
ROUTE_IDS = (
    "dedicated_qwen3_embedding_0_6b",
    "qwen_l28_candidate_span_mean",
    "dedicated_bge_m3",
)
L28_ROUTE_ID = "qwen_l28_candidate_span_mean"
# Payload / instruction contract (AC-157-1; the adapter seam mirrors these,
# they are recorded in the freeze/report as the frozen identities).
PAYLOAD_RULE = "last64(preceding)+candidate"
QWEN3_EMB_QUERY_INSTRUCTION = (
    "Represent the candidate-conditioned query for semantic retrieval.")
L28_POOLING_RULE = "candidate_span_mean"
# Payload / instruction contract descriptions (fingerprinted in the report).
PAYLOAD_RULE = "last64(preceding)+candidate"
QWEN3_EMB_QUERY_INSTRUCTION = (
    "Represent the candidate-conditioned query for semantic retrieval.")
L28_POOLING_RULE = "candidate_span_mean"
# τ calibration (per route, prefix only).
MIN_HARD_NEGATIVE_QUERIES = 200
TAU_QUANTILES = (0.95, 0.975, 0.99, 0.995)
# Group-complete gate (#43 / #76 / #77): saved competition size < N.
GROUP_COMPLETE_N = 32
# Δ₁ category cap; the P10(margin_base) term is computed from the prefix
# where the shadow baseline already ranked the selection first.
DELTA_ONE_CAP = 0.5
# Bootstrap contract (AC-157-v1): key-clustered, fixed seed, >= 10000.
BOOTSTRAP_SEED = 20260817
BOOTSTRAP_REPLICATES = 10000
CI_LEVEL = 0.95


class SuffixWalkforwardError(Exception):
    """A true fault in the suffix walk-forward inputs."""


@dataclass(frozen=True)
class SelectionEvent:
    """One stored selection event (target or history), read-only mirror."""

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
    def key(self) -> Tuple[str, str, str]:
        return (self.schema_id, self.category, self.canonical_segment_input)

    @property
    def key_hash(self) -> str:
        import hashlib
        payload = "%s\0%s\0%s" % self.key
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def group_complete(self) -> bool:
        return len(self.competition) < GROUP_COMPLETE_N

    @property
    def in_prefix(self) -> bool:
        return self.hlc <= PREFIX_HLC_MAX_INCLUSIVE


class FrozenFacts:
    """Read-only wrapper over one consistent facts.sqlite3 copy.

    Mirrors the walkforward.FrozenFacts surface: events in strict
    (hlc, event_id) order, retraction map, competition sets, identity.
    Every access is a plain read; the file is a private copy.
    """

    def __init__(self, snapshot_path):
        self._path = os.path.abspath(snapshot_path)
        if not os.path.isfile(self._path):
            raise SuffixWalkforwardError(
                "snapshot not found: %s" % self._path)
        try:
            self._conn = sqlite3.connect(self._path, timeout=2.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA query_only=ON;")
        except sqlite3.Error as error:
            raise SuffixWalkforwardError(
                "cannot open snapshot: %s" % error)

    def close(self):
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def path(self):
        return self._path

    def identity(self):
        try:
            rows = dict(self._conn.execute("SELECT key, value FROM meta"))
        except sqlite3.Error as error:
            raise SuffixWalkforwardError(
                "snapshot meta read failed: %s" % error)
        return {
            "store_epoch": rows.get("store_epoch"),
            "history_id": rows.get("history_id"),
            "fact_schema_version": rows.get("fact_schema_version"),
            "max_hlc": (int(rows.get("hlc_physical_ms", "-1")),
                        int(rows.get("hlc_logical", "-1"))),
        }

    def all_retractions(self):
        try:
            rows = self._conn.execute(
                "SELECT commit_id, hlc_physical_ms, hlc_logical"
                " FROM retractions").fetchall()
        except sqlite3.Error as error:
            raise SuffixWalkforwardError(
                "snapshot retractions read failed: %s" % error)
        return {row["commit_id"]: (row["hlc_physical_ms"], row["hlc_logical"])
                for row in rows}

    def competition(self, event_id):
        try:
            rows = self._conn.execute(
                "SELECT text FROM selection_candidates"
                " WHERE event_id = ? ORDER BY merge_order", (event_id,),
            ).fetchall()
        except sqlite3.Error as error:
            raise SuffixWalkforwardError(
                "snapshot candidates read failed: %s" % error)
        return tuple(row["text"] for row in rows)

    def events(self):
        retracted = set(self.all_retractions())
        events = []
        try:
            rows = self._conn.execute(
                "SELECT * FROM selection_events").fetchall()
        except sqlite3.Error as error:
            raise SuffixWalkforwardError(
                "snapshot events read failed: %s" % error)
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


class CandidateVectorTable:
    """Cached candidate-conditioned vectors (query side per candidate).

    The query side of a candidate-conditioned representation depends on the
    candidate (payload ``last64(preceding)+candidate`` and, for the Qwen3-emb
    route, the frozen query instruction).  The provider seam is the frozen
    ``RepresentationProvider`` surface (``event_vector`` /
    ``query_vector_for_candidate``); the table caches event vectors by event
    id and query vectors by ``(preceding_text, candidate)``.  Empty-上文
    events are still representable through the candidate-conditioned payload
    (the payload does not depend on a non-empty window); they provide and
    receive evidence exactly like any other representable event.
    """

    def __init__(self, events, provider):
        self._by_id = {event.event_id: event for event in events}
        self._provider = provider
        self._dimension = int(provider.vector_dimension())
        self._events: Dict[str, Tuple[float, ...]] = {}
        self._queries: Dict[Tuple[str, str], Tuple[float, ...]] = {}

    def event_vector(self, event_id):
        if event_id not in self._events:
            event = self._by_id.get(event_id)
            if event is None:
                raise SuffixWalkforwardError(
                    "no vector source for event %s" % event_id)
            self._events[event_id] = self._finite(
                self._provider.event_vector(event), "event %s" % event_id)
        return self._events[event_id]

    def query_vector_for_candidate(self, preceding_text, candidate):
        key = (preceding_text, candidate)
        if key not in self._queries:
            self._queries[key] = self._finite(
                self._provider.query_vector_for_candidate(
                    preceding_text, candidate),
                "query %r" % (key,))
        return self._queries[key]

    def _finite(self, vector, label):
        vector = tuple(float(value) for value in vector)
        if not vector or len(vector) != self._dimension:
            raise SuffixWalkforwardError(
                "vector dimension mismatch for %s" % label)
        for value in vector:
            if not math.isfinite(value):
                raise SuffixWalkforwardError(
                    "vector not finite for %s" % label)
        return vector

    def dimension(self):
        return self._dimension


class CandidateFastEvidence:
    """Vectorized candidate-conditioned evidence (oracle-branch faithful).

    Mirrors ``oracle.compute_evidence`` exactly as the #70 ``FastEvidence``
    mirrors the context-only branch: same-key active history in HLC order,
    per-candidate query vectors, matched events only, exact cosine,
    relevance, usage-age weight, top-K by weight with an (hlc, event_id)
    tie-break, per-candidate m_c / M / s_c.  A history event only supports
    the candidate its (simplified-NFC) selection matches; events matching no
    candidate still consume a usage-age slot but contribute no evidence
    (ADR-0003; oracle compute_evidence candidate branch).
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

    def run(self, candidate_indexes, query_vectors, event_vectors,
            usage_ages, candidates, selection_texts):
        """Per-candidate evidence s for one query (candidate-conditioned).

        ``candidate_indexes``: candidate order positions that have their
        query vector in ``query_vectors`` (only candidates capable of
        matching some same-key history are computed; the rest score 0 in s).
        ``query_vectors``: L2-normalized query vector per listed candidate;
        ``event_vectors``: same-key active event vectors in HLC order;
        ``candidates``: the group's raw texts; ``selection_texts``:
        simplified-NFC final selections of the history events.  Returns
        ``(s_by_index, kept_positions, kept_weights, kept_matches,
        total_mass)`` with ``s_by_index`` in full candidate order (0.0 for
        candidates without a relevant history); ``kept_positions`` index
        into the event-vector lists.  Every kept event matched a candidate.
        """
        candidates = [match_text(c) for c in candidates]
        if not event_vectors or not candidate_indexes:
            return ([0.0] * len(candidates), (), (), (), 0.0)
        query_matrix = np.asarray(query_vectors, dtype=np.float64)
        event_matrix = np.asarray(event_vectors, dtype=np.float64)
        # Per (candidate, event) cosine matrix, then row-select the matched
        # candidate per event; an event matching no candidate gets no slot.
        cosine_matrix = query_matrix @ event_matrix.T
        # Map each history event to its representative candidate slot:
        # the FIRST normalized-equal candidate wins, mirroring the oracle's
        # per-candidate pairing (compute_evidence events_by_candidate).
        slot_of_candidate = {}
        for slot, candidate_index in enumerate(candidate_indexes):
            slot_of_candidate[candidate_index] = slot
        matched_slot = []
        for selected in selection_texts:
            idx = next((slot for slot, candidate_index
                        in enumerate(candidate_indexes)
                        if candidates[candidate_index] == selected), -1)
            matched_slot.append(idx)
        matched_slot = np.asarray(matched_slot, dtype=int)
        with_match = matched_slot >= 0
        cosine = np.zeros(len(event_vectors), dtype=np.float64)
        if with_match.any():
            idx = np.where(with_match)[0]
            cosine[idx] = cosine_matrix[matched_slot[idx], idx]
        relevance = self._relevance(cosine)
        weight = relevance * self._age(usage_ages)
        passed = weight > 0.0
        if not passed.any():
            return ([0.0] * len(candidates), (), (), (), 0.0)
        order = np.argsort(-weight, kind="stable")
        kept = order[:self._k]
        positions = []
        weights = []
        matches = []
        m = [0.0] * len(candidates)
        for position in kept:
            if not passed[position]:
                continue
            positions.append(int(position))
            weights.append(float(weight[position]))
            candidate_index = candidate_indexes[matched_slot[position]]
            matches.append(int(candidate_index))
            m[int(candidate_index)] += float(weight[position])
        total_mass = float(sum(m))
        s = []
        if total_mass <= 0.0:
            return ([0.0] * len(candidates), (), (), (), 0.0)
        for candidate_mass in m:
            share = candidate_mass / total_mass
            saturation = candidate_mass / (candidate_mass + self._sat)
            s.append(share * saturation)
        return s, tuple(positions), tuple(weights), tuple(matches), total_mass


@dataclass(frozen=True)
class EventOutcome:
    """Per-event replay outcome (ids and numbers only, no raw text).

    Field names mirror the #70 ``walkforward.EventOutcome`` so the shared
    ``metrics.py`` / ``bootstrap.py`` aggregation layers apply unchanged.
    ``key`` is the private choice-problem key tuple used only by the
    key-clustered bootstrap; reports always use ``key_hash``.
    """

    event_id: str
    hlc: Tuple[int, int]
    key: Tuple[str, str, str]
    key_hash: str
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
    in_prefix: bool


class WalkForwardReplay:
    """Strict-HLC candidate-conditioned replay over one frozen snapshot.

    Score first, then add to memory; the target's own whole commit is never
    visible to its own query; committed-at-or-before, non-retracted,
    same-key events form the as-of history; retractions apply as-of and
    never backfill.  The split is applied to the *target set* (targets are
    tagged prefix/suffix by HLC); memory accumulates over the whole
    snapshot, so suffix targets see prefix history — the exact walk-forward
    (issue #157 body: "只按 HLC 因果回放验收").
    """

    def __init__(self, facts, vectors):
        if not isinstance(facts, FrozenFacts):
            raise SuffixWalkforwardError("facts must be a FrozenFacts")
        if not isinstance(vectors, CandidateVectorTable):
            raise SuffixWalkforwardError(
                "vectors must be a CandidateVectorTable")
        self._facts = facts
        self._vectors = vectors
        self._events = facts.events()
        self._by_id = {event.event_id: event for event in self._events}
        self._retractions = facts.all_retractions()
        # Same-key index: one replay covers the whole grid per route, so
        # the same-key scan must be O(same-key history), not O(all events).
        self._same_key_index = {}
        for event in self._events:
            self._same_key_index.setdefault(event.key, []).append(event)

    def events(self):
        return self._events

    def targets(self):
        return [event for event in self._events if not event.retracted]

    def _same_key_active(self, target):
        physical, logical = target.hlc
        result = []
        for event in self._same_key_index.get(target.key, ()):
            if event.commit_id == target.commit_id:
                continue
            if event.hlc > target.hlc:
                continue
            retracted = self._retractions.get(event.commit_id)
            if retracted is not None and retracted <= target.hlc:
                continue
            result.append(event)
        result.sort(key=lambda e: (e.hlc, e.event_id))
        return result

    def replay(self, params, gamma):
        """Run the full HLC replay under one parameter configuration.

        Returns the per-target EventOutcome list in HLC order.  Pure and
        deterministic; each call re-walks the snapshot, so cells are
        independent and reproducible.
        """
        if not isinstance(params, OracleParams):
            raise SuffixWalkforwardError("params must be an OracleParams")
        if not (isinstance(gamma, (int, float)) and gamma >= 0.0):
            raise SuffixWalkforwardError("gamma must be non-negative")

        fast = CandidateFastEvidence(
            params.tau, params.k_evidence, params.half_life,
            params.saturation_k)
        outcomes = []
        for target in self.targets():
            history = self._same_key_active(target)
            event_vectors = []
            for h in history:
                event_vectors.append(self._vectors.event_vector(h.event_id))
            usage_ages = list(range(len(history) - 1, -1, -1))
            selection_texts = [match_text(h.final_selection_text)
                               for h in history]
            # Only candidates that can match some same-key history event
            # need a query vector (others score 0 evidence; no invented
            # cosine).  The runner precomputes exactly this pair set.
            templates = [match_text(c) for c in target.competition]
            candidate_indexes = []
            query_vectors = []
            seen_templates = set()
            for index, candidate in enumerate(target.competition):
                template = templates[index]
                if template in seen_templates:
                    continue
                seen_templates.add(template)
                if any(selected == template for selected in selection_texts):
                    candidate_indexes.append(index)
                    query_vectors.append(
                        self._vectors.query_vector_for_candidate(
                            target.preceding_text, candidate))
            s, kept_positions, kept_weights, kept_matches, total_mass = \
                fast.run(candidate_indexes, query_vectors, event_vectors,
                         usage_ages, list(target.competition),
                         selection_texts)
            baseline_rank = (1 if (target.display_page == 1
                                   and target.display_rank == 1) else 2)
            scheme_rank = self._scheme_rank(target, s, gamma)
            selection_index = self._selection_index(target)
            actionable = any(value > 0.0 for value in s)
            outcomes.append(EventOutcome(
                event_id=target.event_id,
                hlc=target.hlc,
                key=target.key,
                key_hash=target.key_hash,
                confirmation_source=target.confirmation_source,
                competition_complete=target.competition_complete,
                group_complete=target.group_complete,
                baseline_rank=baseline_rank,
                scheme_rank=scheme_rank,
                actionable=actionable,
                total_mass=total_mass,
                candidate_count=len(target.competition),
                selection_index=selection_index,
                kept_ids=tuple(history[position].event_id
                               for position in kept_positions),
                kept_weights=tuple(float(v) for v in kept_weights),
                kept_matches=tuple(int(m) for m in kept_matches),
                in_prefix=target.in_prefix))
        return outcomes

    @staticmethod
    def _base_reconstruction(target):
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
            raise SuffixWalkforwardError(
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
        """Scheme rank under base_proxy + gamma*s (γ=0 reproduces baseline)."""
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

    @staticmethod
    def _selection_index(target):
        """First simplified-NFC-equal candidate index of the selection."""
        selection = match_text(target.final_selection_text)
        for index, text in enumerate(target.competition):
            if match_text(text) == selection:
                return index
        return None


def prefix_suffix_split(targets):
    """(prefix, suffix) targets at the frozen HLC cutoff (prefix incl.)."""
    prefix = [t for t in targets if t.in_prefix]
    suffix = [t for t in targets if not t.in_prefix]
    return prefix, suffix


class _StubProvider:
    """A provider that never produces vectors; used only for pair
    enumeration where only the same-key history logic runs."""

    def vector_dimension(self):
        return 1

    def event_vector(self, event):
        raise SuffixWalkforwardError("stub provider has no vectors")

    def query_vector_for_candidate(self, preceding_text, candidate):
        raise SuffixWalkforwardError("stub provider has no vectors")


def needed_query_pairs(facts, targets=None):
    """The exact (preceding_text, candidate) query pairs the replay needs.

    Candidate-conditioned evidence only compares a candidate's query vector
    against history events whose normalized selection matches that
    candidate.  This enumerates, for every target and every normalized-c
    candidate with at least one same-key active history event matching it,
    the query pair the vector cache must hold.  Used by the runner to bound
    the model forwards (one pass per route) and by tests to assert the
    cache identity.  The pair set is route-independent: it follows from the
    facts and the frozen grouping rules only.
    """
    stub = WalkForwardReplay(facts, CandidateVectorTable(
        facts.events(), _StubProvider()))
    if targets is None:
        targets = stub.targets()
    pairs = set()
    for target in targets:
        history = stub._same_key_active(target)
        selections = {match_text(h.final_selection_text)
                      for h in history}
        seen_templates = set()
        for candidate in target.competition:
            template = match_text(candidate)
            if template in seen_templates:
                continue
            seen_templates.add(template)
            if template in selections:
                pairs.add((target.preceding_text, candidate))
    return pairs


def margin_base_prefix(prefix_outcomes):
    """P10(margin_base) over the prefix (AC-157-v1).

    margin_base events = prefix events where the shadow baseline already
    ranked the final selection first; the base margin is the positive
    base-score gap of the final selection vs the runner-up.  Real snapshots
    do not persist per-candidate base scores, so the engine uses the
    recorded confirmation rank as the base position (mirroring the #77 D3
    reconstruction) and reports the margin as the rank gap, then enforces
    ``Δ₁ <= min(0.5, P10(margin_base))``.  Returns (p10 | None, count).
    """
    margins = []
    for outcome in prefix_outcomes:
        # baseline_rank==1 already encodes display_page==1 and
        # display_rank==1 (the constructors define it so).
        if outcome.baseline_rank != 1:
            continue
        if outcome.selection_index is None:
            continue
        margins.append(1.0)  # unbounded below? no: rank-1 vs runner-up proxy gap
    if not margins:
        return None, 0
    margins.sort()
    index = int(math.ceil(0.10 * len(margins))) - 1
    return margins[max(0, min(index, len(margins) - 1))], len(margins)


def delta_one(gamma, k):
    """Δ₁ = γ/(1+k): the maximum single-event evidence increment."""
    return gamma / (1.0 + k)