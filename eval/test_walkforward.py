#!/usr/bin/env python3
"""Causality and semantics tests for the #70 walk-forward engine.

Pins SCN-70-1 (strict HLC walk-forward: score first, then add to memory;
as-of visibility; no future leakage; retractions never backfill), SCN-70-2
(incomplete competition: positive historical evidence only, never rank
gates) and SCN-70-3 (actionable / union / coverage / stratification) on
synthetic facts with controlled vectors.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from oracle import OracleParams  # noqa: E402

from fixture_facts import (SyntheticFacts, axis_query_vectors,  # noqa: E402
                           fixture_provider, selection_vectors)
from walkforward import (FrozenFacts, VectorTable,  # noqa: E402
                         WalkForwardReplay)


def replay_for(facts, query_vectors, event_vectors, params=None,
               gamma=2.0):
    provider = fixture_provider(query_vectors, event_vectors)
    frozen = FrozenFacts(facts.db_path)
    try:
        vectors = VectorTable(frozen.events(), provider)
        replay = WalkForwardReplay(frozen, vectors)
        if params is None:
            params = OracleParams(tau=0.0, k_evidence=8,
                                  half_life=float("inf"), saturation_k=1.0)
        return replay, replay.replay(params, gamma)
    finally:
        frozen.close()


class WalkForwardCausalityTest(unittest.TestCase):

    def test_score_first_then_add_memory(self):
        """An event must never see itself or its own commit (SCN-70-1).

        The first event of a key has no history, so it is not actionable;
        the second event sees only the first commit, not itself.
        """
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "ctx1", "我",
                            ("我", "握"), (100, 0),
                            display_rank=1, display_page=1)
            facts.add_event("e2", "wo", "ctx2", "握",
                            ("我", "握"), (200, 0),
                            display_rank=2, display_page=1)
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (0.9, 0.436, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            # e1 has no history -> not actionable, baseline first (display
            # rank 1), scheme rank 1 (recorded order, no evidence).
            self.assertFalse(by_id["e1"].actionable)
            self.assertEqual(by_id["e1"].baseline_rank, 1)
            self.assertEqual(by_id["e1"].scheme_rank, 1)
            # e2 sees only e1 -> actionable; e1 supports 我 (cosine 1.0),
            # e2 selected 握 (baseline rank 2) -> scheme pushes 我 up, the
            # selection drops out of first -> scheme rank 2 (仍第二:两个
            # 候选).
            self.assertTrue(by_id["e2"].actionable)
            self.assertEqual(by_id["e2"].baseline_rank, 2)
            self.assertEqual(by_id["e2"].scheme_rank, 2)
        finally:
            facts.close()

    def test_no_future_leakage(self):
        """A query at HLC t must never see events committed after t."""
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "ctx1", "我", ("我", "握"), (100, 0))
            facts.add_event("e2", "wo", "ctx2", "我", ("我", "握"), (300, 0))
            facts.add_event("e3", "wo", "ctx3", "握", ("我", "握"), (200, 0))
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (1.0, 0.0, 0.0, 0.0),
                "ctx3": (0.9, 0.436, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            # e3 committed at (200,0) must not see e2 (300,0).
            self.assertEqual(len(by_id["e3"].kept_ids), 1)
            self.assertEqual(by_id["e3"].kept_ids, ("e1",))
        finally:
            facts.close()

    def test_retraction_as_of_no_backfill(self):
        """A retracted event stays visible before its retraction HLC and a
        later retraction never changes an earlier query (SCN-70-1)."""
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "ctx1", "我", ("我", "握"), (100, 0),
                            retract_at=(250, 0))
            facts.add_event("e2", "wo", "ctx2", "握", ("我", "握"), (200, 0))
            facts.add_event("e3", "wo", "ctx3", "我", ("我", "握"), (300, 0))
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (0.9, 0.436, 0.0, 0.0),
                "ctx3": (0.0, 1.0, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            # e2 at (200,0) sees e1 (retracted at 250 > 200): visible.
            self.assertIn("e1", by_id["e2"].kept_ids)
            # e3 at (300,0) must NOT see e1 (retracted at 250 <= 300).
            self.assertNotIn("e1", by_id["e3"].kept_ids)
            # e1 is retracted -> not a target.
            self.assertNotIn("e1", by_id)
        finally:
            facts.close()

    def test_gamma_zero_equals_recorded_baseline(self):
        """γ=0 must reproduce the recorded order exactly (D3 identity).

        With γ=0 the scheme ranking equals the recorded competition order,
        so every event's scheme_rank equals its recorded position.
        """
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "ctx1", "握", ("我", "握"), (100, 0),
                            display_rank=2, display_page=1)
            facts.add_event("e2", "wo", "ctx2", "我", ("我", "握"), (200, 0),
                            display_rank=1, display_page=1)
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (1.0, 0.0, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            }, gamma=0.0)
            for outcome in outcomes:
                self.assertEqual(outcome.scheme_rank, outcome.baseline_rank)
        finally:
            facts.close()

    def test_gamma_zero_identity_when_merge_order_differs(self):
        """The reconstruction pins the selection at its recorded
        confirmation position, so γ=0 reproduces the shadow baseline even
        when the recorded merge order differs from the confirmation rank
        (the case the base-score reconstruction exists for)."""
        facts = SyntheticFacts()
        try:
            # Selection 我 is 3rd in merge order but was confirmed at rank 1.
            facts.add_event("e1", "wo", "ctx1", "我",
                            ("得", "的", "我", "握"), (100, 0),
                            display_rank=1, display_page=1)
            facts.add_event("e2", "wo", "ctx2", "握",
                            ("我", "握", "的", "得"), (200, 0),
                            display_rank=2, display_page=1)
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (1.0, 0.0, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "的"): (0.0, 0.0, 1.0, 0.0),
                ("luna_pinyin", "wo", "得"): (0.0, 0.0, 0.0, 1.0),
            }, gamma=0.0)
            by_id = {o.event_id: o for o in outcomes}
            # e1: merge order puts 我 3rd, but confirmation rank is 1; the
            # reconstruction pins it at 1, so scheme_rank == 1.
            self.assertEqual(by_id["e1"].baseline_rank, 1)
            self.assertEqual(by_id["e1"].scheme_rank, 1)
            # e2: merge order puts 握 2nd and confirmation rank is 2.
            self.assertEqual(by_id["e2"].baseline_rank, 2)
            self.assertEqual(by_id["e2"].scheme_rank, 2)
        finally:
            facts.close()

    def test_empty_context_events_excluded(self):
        """Empty-上文 events are unrepresentable: excluded from replayable
        targets (counted), never provide or receive evidence (SCN-70-1's
        no-phantom-vector rule), and never crash the run."""
        facts = SyntheticFacts()
        try:
            facts.add_event("e0", "wo", "", "我", ("我", "握"), (50, 0),
                            display_rank=1, display_page=1)
            facts.add_event("e1", "wo", "ctx1", "我", ("我", "握"), (100, 0),
                            display_rank=1, display_page=1)
            facts.add_event("e2", "wo", "ctx2", "握", ("我", "握"), (200, 0),
                            display_rank=2, display_page=1)
            replay, (outcomes, summary) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (0.9, 0.436, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            self.assertEqual(summary["unrepresentable_targets"], 1)
            self.assertEqual(summary["replayable_targets"], 2)
            by_id = {o.event_id: o for o in outcomes}
            self.assertNotIn("e0", by_id)
            # e1 (after e0) sees only nothing before it: e0 is dropped, so
            # e1 has no history and is not actionable.
            self.assertFalse(by_id["e1"].actionable)
            self.assertEqual(by_id["e1"].kept_ids, ())
        finally:
            facts.close()

    def test_actionable_requires_candidate_evidence(self):
        """Actionable = non-zero evidence for at least one candidate of the
        current group (spec #43).  History whose selection matches no
        candidate contributes mass but no candidate evidence, so it is NOT
        actionable (review finding A4)."""
        facts = SyntheticFacts()
        try:
            # e1 selects 丙, which is absent from e2's competition.
            facts.add_event("e1", "wo", "ctx1", "丙", ("丙",), (100, 0))
            facts.add_event("e2", "wo", "ctx2", "我", ("我", "握"), (200, 0),
                            display_rank=1, display_page=1)
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (0.9, 0.436, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "丙"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            # e2 sees e1 (kept) with total mass > 0, but 丙 matches no
            # candidate of (我, 握) -> s_c = 0 for both -> not actionable.
            self.assertIn("e1", by_id["e2"].kept_ids)
            self.assertGreater(by_id["e2"].total_mass, 0.0)
            self.assertFalse(by_id["e2"].actionable)
        finally:
            facts.close()

    def test_duplicate_normalized_candidates_first_match(self):
        """Candidates that normalize equal (於/于 -> 于) are tolerated and
        resolve to the FIRST normalized-equal candidate, exactly like the
        oracle's match attribution (review finding B3)."""
        facts = SyntheticFacts()
        try:
            # e1 selects 於 (simplifies to 于); e2's competition contains
            # both 于 and 於.  The oracle attributes 於's evidence to the
            # first normalized-equal candidate (于 at index 0).
            facts.add_event("e1", "yu", "ctx1", "於", ("於",), (100, 0))
            facts.add_event("e2", "yu", "ctx2", "於", ("于", "於"), (200, 0),
                            display_rank=2, display_page=1)
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (0.9, 0.436, 0.0, 0.0),
            }, {
                ("luna_pinyin", "yu", "於"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "yu", "于"): (1.0, 0.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            # e1's selection 於 matches e2's candidate 于 (first
            # normalized-equal) -> evidence lands on index 0.
            self.assertTrue(by_id["e2"].actionable)
            self.assertEqual(by_id["e2"].selection_index, 0)
            # selection_index resolves to the first normalized-equal too.
            self.assertEqual(by_id["e2"].kept_matches, (0,))
        finally:
            facts.close()

    def test_page2_confirmation_not_reconstructable(self):
        """display_page > 1: the absolute rank depends on the page size the
        facts do not record, so the base position is not reconstructable and
        the scheme rank is None (reported in the fidelity diagnostic)."""
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "ctx1", "我", ("我", "握"), (100, 0),
                            display_rank=2, display_page=2)
            facts.add_event("e2", "wo", "ctx2", "握", ("我", "握"), (200, 0),
                            display_rank=1, display_page=1)
            replay, (outcomes, summary) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (1.0, 0.0, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            self.assertIsNone(by_id["e1"].scheme_rank)
            self.assertEqual(by_id["e2"].scheme_rank, 1)
        finally:
            facts.close()

    def test_incomplete_competition_positive_evidence_only(self):
        """competition_complete=false: positive historical evidence yes,
        top-1/MRR/mispromotion gates no (SCN-70-2)."""
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "ctx1", "我", ("我", "握"), (100, 0),
                            competition_complete=False)
            facts.add_event("e2", "wo", "ctx2", "握", ("我", "握"), (200, 0),
                            competition_complete=False)
            replay, (outcomes, _) = replay_for(facts, {
                "ctx1": (1.0, 0.0, 0.0, 0.0),
                "ctx2": (0.9, 0.436, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
            by_id = {o.event_id: o for o in outcomes}
            # e1 (incomplete) provides positive evidence to e2.
            self.assertIn("e1", by_id["e2"].kept_ids)
            # e2 itself is actionable but incomplete -> not in rank gates:
            # scheme_rank is still computed for diagnosis, but the gate
            # eligibility lives in metrics (complete_only), pinned below.
            from metrics import (mispromotion_events, top1)
            eligible = [o for o in outcomes if o.competition_complete]
            self.assertEqual(eligible, [])
            self.assertIsNone(top1(outcomes, complete_only=True))
            self.assertEqual(mispromotion_events(outcomes), ([], []))
        finally:
            facts.close()

    def test_actionable_union_and_coverage(self):
        """SCN-70-3: actionable, coverage and strata computed correctly."""
        facts = SyntheticFacts()
        try:
            for i in range(10):
                facts.add_event("a%d" % i, "wo", "ctxa", "我",
                                ("我", "握"), (100 + i, 0),
                                competition_complete=False)
            facts.add_event("b0", "de", "ctxb", "的", ("的", "得"),
                            (200, 0), competition_complete=True)
            facts.add_event("b1", "de", "ctxb", "得", ("的", "得"),
                            (300, 0), competition_complete=True)
            replay, (outcomes, summary) = replay_for(facts, {
                "ctxa": (1.0, 0.0, 0.0, 0.0),
                "ctxb": (1.0, 0.0, 0.0, 0.0),
            }, {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
                ("luna_pinyin", "de", "的"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "de", "得"): (0.0, 1.0, 0.0, 0.0),
            })
            self.assertEqual(summary["replayable_targets"], 12)
            self.assertEqual(summary["complete_competition"], 2)
            self.assertAlmostEqual(summary["coverage"], 2 / 12)
            # actionable: all events with prior same-key history.
            actionable = {o.event_id for o in outcomes if o.actionable}
            self.assertIn("a1", actionable)
            self.assertNotIn("a0", actionable)
            self.assertIn("b1", actionable)
            self.assertNotIn("b0", actionable)
        finally:
            facts.close()


if __name__ == "__main__":
    unittest.main()
