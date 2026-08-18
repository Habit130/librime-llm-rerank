#!/usr/bin/env python3
"""α-sweep ranking engine for the #106 recalibration (primary denominator).

For every grid α the ranking of a saved competition set is computed with the
frozen comparison formula (spec #43, invariant):

    score(c) = α · mean_token_lm_score(c | 上文) + β_src · weight(c)
    γ = 0

- ``weight(c)`` is the librime runtime log-space dictionary weight
  (template_weights.runtime_weight), identical across every α on that event
  (SCN-106-4);
- ``mean_token_lm_score`` is the daemon ``mean-token-lm-v1`` score
  (daemon_scoring), candidate tokens only, fail-closed;
- the same candidate set (the pinned saved competition texts in merge
  order) is ranked at every α; ties keep the saved merge order.

无法重放 (SCN-106-5): if any saved candidate cannot receive a finite weight
or a finite LM score, the whole event is 无法重放 and is excluded from every
α (counted; the rest of the set is never silently reranked).

Observed ground truth: the frozen γ=0 baseline's outcome for the user's
final selection is the recorded confirmation position — rank 1 iff
``display_page == 1 and display_rank == 1`` (matches #70's baseline_rank).

Mispromotion (mandatory report, not a veto; seam 9):

- M1 (live policy): events whose observed confirmation was already rank 1,
  then reconstructed ``α > 0`` pushes the selection down;
- M2 (grid-consistent): events whose reconstructed ``α = 0`` was rank 1,
  then ``α > 0`` pushes it down.

``decide_final`` never reads these as the primary sort key.

No raw text leaves this module: per-event records carry event ids, HLCs,
alpha values, and ranks only.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from daemon_scoring import DaemonScoringError, score_batch
from primary_events import SelectionEvent
from template_weights import weight_for

# Pre-declared α grid and boundary extension rule (#46, frozen).
ALPHA_GRID = [0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]
ALPHA_EXTENSION = [14.0, 20.0]
BETA_SYS = 1.0
BETA_USR = 1.0


class RecalibrationError(Exception):
    """A true fault in the ranking engine inputs."""


@dataclass(frozen=True)
class EventScore:
    """One event's per-candidate scores (no raw text)."""

    event_id: str
    hlc: Tuple[int, int]
    key: Tuple[str, str, str]
    selection_index: int              # index of the selection in competition
    weights: Tuple[float, ...]   # librime runtime weights, merge order
    lm_scores: Tuple[float, ...] # mean-token LM scores, merge order
    observed_rank1: bool         # display_page==1 and display_rank==1
    competition_size: int
    preceding_empty: bool
    confirmation_source: str


def _selection_index(event: SelectionEvent) -> Optional[int]:
    """Index of the final selection in the saved competition (first
    simplified-NFC-equal candidate, mirroring the oracle's attribution)."""
    from oracle import match_text
    selection = match_text(event.final_selection_text)
    for index, text in enumerate(event.competition):
        if match_text(text) == selection:
            return index
    return None


def score_event(event: SelectionEvent,
                weight_map: Dict,
                daemon_socket: str,
                plan_identity: str) -> Tuple[Optional[EventScore], str]:
    """Score one event's pinned saved competition set.

    Returns ``(EventScore, None)`` on success, or ``(None, reason)`` when
    the event is 无法重放.  ``reason`` is one of ``"weight"`` (a saved
    candidate has no template weight) or ``"lm"`` (the daemon failed the
    batch).  SCN-106-5: the whole event fails, never a partial rerank.
    """
    texts = list(event.competition)
    code = event.canonical_segment_input
    weights = []
    for text in texts:
        weight = weight_for(weight_map, text, code)
        if weight is None:
            return None, "weight"
        if not math.isfinite(weight):
            return None, "weight"
        weights.append(weight)
    try:
        lm = score_batch(daemon_socket, event.preceding_text, texts,
                         request_id="recalib:" + event.event_id,
                         plan_identity=plan_identity)
    except DaemonScoringError:
        return None, "lm"
    if len(lm) != len(texts):
        return None, "lm"
    for value in lm:
        if not math.isfinite(value):
            return None, "lm"
    selection_index = _selection_index(event)
    if selection_index is None:
        # The user's final selection is absent from the recorded competition:
        # the selection is a saved candidate that cannot receive a weight or
        # a rank, so the event is 无法重放 under the weight family
        # (SCN-106-5; the contract's 无法重放 triggers are weight/LM).
        return None, "weight"
    observed_rank1 = event.display_page == 1 and event.display_rank == 1
    return EventScore(
        event_id=event.event_id,
        hlc=event.hlc,
        key=event.key,
        selection_index=selection_index,
        weights=tuple(weights),
        lm_scores=tuple(lm),
        observed_rank1=observed_rank1,
        competition_size=len(texts),
        preceding_empty=not event.preceding_text,
        confirmation_source=event.confirmation_source,
    ), None


def selection_rank(event_score: EventScore, alpha: float) -> Optional[int]:
    """Rank (1-based) of the final selection under one α.

    Ties keep the saved merge order (stable).  Returns None only when the
    selection index is out of range (defensive; should not happen).
    """
    selection_index = event_score.selection_index
    if not (0 <= selection_index < len(event_score.weights)):
        return None
    scores = [
        alpha * lm + weight
        for lm, weight in zip(event_score.lm_scores, event_score.weights)
    ]
    order = sorted(range(len(scores)),
                   key=lambda i: (-scores[i], i))
    for rank, index in enumerate(order, start=1):
        if index == selection_index:
            return rank
    return None


def alpha0_rank(event_score: EventScore) -> Optional[int]:
    """The reconstructed α=0 (weight-only) rank of the selection."""
    return selection_rank(event_score, 0.0)


@dataclass(frozen=True)
class AlphaMetrics:
    """Per-α metrics over the scored primary set."""

    alpha: float
    samples: int                 # scored events with a selection rank
    top1: int
    top1_rate: float
    mrr: float
    m1_denominator: int
    m1_numerator: int
    m2_denominator: int
    m2_numerator: int
    empty_preceding: int


def per_alpha_metrics(event_scores: Sequence[EventScore],
                      alpha: float,
                      alpha0_ranks: Optional[Dict[str, int]] = None
                      ) -> AlphaMetrics:
    """Aggregate one α over the scored primary events.

    ``alpha0_ranks`` maps event_id -> α=0 rank (needed for M2).  Metrics
    use every scored event whose selection rank is known.
    """
    samples = 0
    top1 = 0
    reciprocal_sum = 0.0
    m1_den = 0
    m1_num = 0
    m2_den = 0
    m2_num = 0
    empty = 0
    for score in event_scores:
        rank = selection_rank(score, alpha)
        if rank is None:
            continue
        samples += 1
        if rank == 1:
            top1 += 1
        reciprocal_sum += 1.0 / rank
        if score.preceding_empty:
            empty += 1
        # M1: observed (live policy) was rank 1, α>0 pushes down.
        if score.observed_rank1 and alpha > 0.0 and rank != 1:
            m1_den += 1
            m1_num += 1
        elif score.observed_rank1 and alpha > 0.0:
            m1_den += 1
        # M2: reconstructed α=0 was rank 1, α>0 pushes down.
        if alpha > 0.0:
            a0 = (alpha0_ranks or {}).get(score.event_id)
            if a0 is not None and a0 == 1:
                m2_den += 1
                if rank != 1:
                    m2_num += 1
    return AlphaMetrics(
        alpha=alpha,
        samples=samples,
        top1=top1,
        top1_rate=(top1 / samples) if samples else 0.0,
        mrr=(reciprocal_sum / samples) if samples else 0.0,
        m1_denominator=m1_den,
        m1_numerator=m1_num,
        m2_denominator=m2_den,
        m2_numerator=m2_num,
        empty_preceding=empty,
    )


def alpha0_rank_map(event_scores: Sequence[EventScore]) -> Dict[str, int]:
    """event_id -> reconstructed α=0 selection rank."""
    return {score.event_id: rank for score in event_scores
            if (rank := alpha0_rank(score)) is not None}
