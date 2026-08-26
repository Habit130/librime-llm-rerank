#!/usr/bin/env python3
"""Model-free gate for the AC-159-v1 candidate-conditioned suffix walk-forward.

Pins without loading any model:

- AC159-1: exactly the three frozen routes; candidate-conditioned query
  pairing (per-candidate query vectors, matched-event pairing) is
  bit-faithful to the canonical oracle's candidate branch; L28 span
  pooling contract stays with the frozen seam.
- AC159-2: the frozen HLC split is respected: prefix includes
  [1787667799562, 0], suffix is strictly later; selection uses prefix
  outcomes only, claims use suffix outcomes only; memory still accumulates
  over the whole snapshot (suffix targets see prefix history).
- AC159-4: the grid manifest is the frozen pre-declared space; τ uses only
  prefix query-level hard negatives (nearest-rank Q95/Q97.5/Q99/Q99.5);
  below 200 queries the route is ``not_calibratable`` and no τ is invented.
- AC159-5: the legal terminals (exact shortlist / 收窄声称 shortlist /
  无合格方案 / 数据不足) are emitted with the documented gates; the +3pp
  claim is refused when the suffix actionable group-complete sample cannot
  support it.
- AC159-6: public-B accuracy and the personal 2x2 r never enter
  decide_final (no such input exists in the decision surface).
- AC159-7: reports pass the privacy scan and carry hashes, counts, cell
  identities and the terminal only.

The replay itself is exercised through a deterministic candidate-conditioned
fixture provider; no model, no venv, no GPU.
"""

import os
import random
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from oracle import OracleParams, OracleQuery, compute_evidence, match_text  # noqa: E402

from fixture_facts import SyntheticFacts  # noqa: E402
from evidence import CandidateFixtureRepresentationProvider  # noqa: E402

from walkforward_cc import (  # noqa: E402
    CONTRACT_ID, ENGINE_VERSION, PREFIX_HLC_MAX_INCLUSIVE, ROUTE_IDS,
    L28_ROUTE_ID, QWEN3_EMB_QUERY_INSTRUCTION, PAYLOAD_RULE,
    L28_POOLING_RULE, CandidateFastEvidence, CandidateVectorTable,
    FrozenFacts, WalkForwardReplay, margin_base_prefix, needed_query_pairs,
    prefix_suffix_split, delta_one)
from calibration_cc import calibrate_tau, nearest_rank_quantile  # noqa: E402
from shortlist_cc import assemble_shortlist  # noqa: E402
from grid_cc import (data_counts, grid_manifest, data_insufficient,
                     finite_h_gate, run_route,
                     select_prefix_cells)  # noqa: E402
from suffix_report import build_report, render_markdown, verify_privacy  # noqa: E402


QUE = lambda code: {"evidence": code}  # noqa: E731 - private-record helper


def _unit(cosine, dimension=4):
    import math
    r = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return tuple([cosine, r] + [0.0] * (dimension - 2))


class _Event:
    """One same-key event for the canonical oracle (candidate branch).

    ``events`` tuples are (selection, cosine, event_id).
    """

    def __init__(self, selection, cosine, event_id):
        self.event_id = event_id
        self.commit_id = "c-" + event_id
        self.schema_id = "s"
        self.category = "word"
        self.canonical_segment_input = "key"
        self.final_selection_text = selection
        self.preceding_text = ""
        self.hlc = (int(event_id[1:]), 0)
        self.key = ("s", "word", "key")
        self._cosine = cosine

    def vector(self):
        return _unit(self._cosine)


class _Reader:
    """Minimal FactReader stand-in feeding events to the canonical oracle."""

    def __init__(self, events):
        self._events = tuple(events)

    def read_active_events(self, as_of=None):
        return list(self._events)

    def default_as_of(self):
        return (999999, 0)


class FastOracleEquivalenceTest(unittest.TestCase):
    """CandidateFastEvidence vs the canonical oracle's candidate branch.

    The engine's vectorized path must reproduce oracle.compute_evidence
    with per-candidate query vectors to floating-point precision over a
    grid of tau / H / K / k and diverse match layouts (the AC-159-1
    AC-honored mirror of test_fast_oracle).
    """

    def _run_case(self, events, candidates, params, queries_by_candidate):
        """events: list of (selection, cosine, event_id); returns
        (fast_s, oracle_s) per candidate.  Events must be HLC-ordered for
        the fast path (the oracle sorts same-key events itself), so both
        paths receive the identical (event_id-sorted) order."""
        events = sorted(events, key=lambda item: (int(item[2][1:]), item[2]))
        reader = _Reader([_Event(*event) for event in events])

        def vector_for(event_id):
            for selection, cosine, event in events:
                if event == event_id:
                    return _unit(cosine)
            raise KeyError(event_id)

        oracle_query = OracleQuery(
            schema_id="s",
            canonical_segment_input="key",
            candidates=candidates,
            query_vector=(),
            candidate_query_vectors=[
                queries_by_candidate.get(index, (1.0, 0.0, 0.0, 0.0))
                for index in range(len(candidates))],
        )
        oracle = compute_evidence(reader, params, oracle_query, vector_for)
        oracle_s = [candidate.s for candidate in oracle.candidates]

        selection_texts = [match_text(sel) for sel, _cos, _id in events]
        event_vectors = [vector_for(event_id) for _sel, _cos, event_id
                         in events]
        query_vectors = [queries_by_candidate.get(i, (1.0, 0.0, 0.0, 0.0))
                         for i in range(len(candidates))]
        usage_ages = list(range(len(events) - 1, -1, -1))
        fast = CandidateFastEvidence(
            params.tau, params.k_evidence, params.half_life,
            params.saturation_k)
        candidate_indexes = list(range(len(candidates)))
        s_fast, _pos, _w, _m, _mass = fast.run(
            candidate_indexes, query_vectors, event_vectors, usage_ages,
            candidates, selection_texts)
        return s_fast, oracle_s

    def test_equivalence_across_params(self):
        from oracle import match_text
        rng = random.Random(7)
        for _trial in range(12):
            n_events = rng.randint(2, 8)
            events = []
            for index in range(n_events):
                selection = rng.choice(["A", "B", "C"])
                cosine = rng.choice([0.2, 0.55, 0.7, 0.9, 0.95])
                events.append((selection, cosine, "e%d" % index))
            candidates = rng.sample(["A", "B", "C"],
                                    k=rng.randint(1, 3))
            params = OracleParams(
                tau=rng.choice([0.3, 0.6, 0.9]),
                k_evidence=rng.choice([1, 2, 4]),
                half_life=rng.choice([8, float("inf")]),
                saturation_k=rng.choice([1, 3, 7]))
            queries = {idx: _unit(rng.choice([0.1, 0.5, 0.8]))
                       for idx in range(len(candidates))}
            fast_s, oracle_s = self._run_case(
                events, candidates, params, queries)
            self.assertEqual(len(fast_s), len(oracle_s))
            for fast, oracle in zip(fast_s, oracle_s):
                self.assertAlmostEqual(fast, oracle, places=10,
                                       msg="trial %d params %r" % (_trial,
                                                                   params))

    def test_equivalence_duplicate_selections(self):
        from oracle import match_text
        events = [("A", 0.9, "e1"), ("A", 0.7, "e2"), ("B", 0.5, "e3")]
        params = OracleParams(tau=0.3, k_evidence=2,
                              half_life=float("inf"), saturation_k=1.0)
        queries = {0: _unit(0.8), 1: _unit(0.6)}
        fast_s, oracle_s = self._run_case(events, ["A", "B"], params, queries)
        for fast, oracle in zip(fast_s, oracle_s):
            self.assertAlmostEqual(fast, oracle, places=10)

    def test_equivalence_all_same_selection(self):
        from oracle import match_text
        events = [("A", 0.8, "e1"), ("A", 0.85, "e2")]
        params = OracleParams(tau=0.4, k_evidence=2,
                              half_life=float("inf"), saturation_k=3.0)
        queries = {0: _unit(0.9)}
        fast_s, oracle_s = self._run_case(events, ["A"], params, queries)
        self.assertEqual(fast_s, oracle_s)


class RouteAndPayloadContractTest(unittest.TestCase):

    def test_exactly_three_frozen_routes(self):
        self.assertEqual(ROUTE_IDS, (
            "dedicated_qwen3_embedding_0_6b",
            "qwen_l28_candidate_span_mean",
            "dedicated_bge_m3",
        ))

    def test_payload_and_instruction_constants(self):
        # AC159-1: no separator; query instruction only for Qwen3-emb.
        self.assertEqual(PAYLOAD_RULE, "last64(preceding)+candidate")
        self.assertEqual(
            QWEN3_EMB_QUERY_INSTRUCTION,
            "Represent the candidate-conditioned query for semantic "
            "retrieval.")
        self.assertEqual(L28_ROUTE_ID, "qwen_l28_candidate_span_mean")
        self.assertEqual(L28_POOLING_RULE, "candidate_span_mean")

    def test_frozen_split_hlc(self):
        self.assertEqual(PREFIX_HLC_MAX_INCLUSIVE, (1787667799562, 0))


def _fixture_provider(query_vectors, event_vectors):
    """A candidate-conditioned fixture provider (the #155-style seam)."""
    from evidence import CandidateFixtureRepresentationProvider
    return CandidateFixtureRepresentationProvider(
        "fixture:ac159",
        query_vectors,
        event_vectors,
        default_query=(1.0, 0.0, 0.0, 0.0),
        default_event=(0.0, 1.0, 0.0, 0.0))


def _synthetic_with_split():
    """A synthetic snapshot with events on both sides of the cutoff.

    Prefix events hold hlc <= [1787667799562, 0]; suffix events are strictly
    later.  Vectors are chosen so same-key, different-selection history
    yields defined hard-negative cosines.
    """
    facts = SyntheticFacts()
    cutoff = PREFIX_HLC_MAX_INCLUSIVE
    try:
        # Prefix: one key with a history chain (A then B) so a target has a
        # hard-negative history, plus suffix events on the same key.
        facts.add_event("p1", "wo", "前1", "我", ("我", "握"),
                        cutoff, display_rank=1, display_page=1)
        facts.add_event("p2", "wo", "前2", "握", ("我", "握"),
                        (cutoff[0] - 1000, cutoff[1]),
                        display_rank=2, display_page=1)
        facts.add_event("p3", "wo", "前3", "我", ("我", "握"),
                        (cutoff[0] - 2000, cutoff[1]),
                        display_rank=1, display_page=1)
        facts.add_event("s1", "wo", "后4", "握", ("我", "握"),
                        (cutoff[0] + 1000, cutoff[1]),
                        display_rank=2, display_page=1)
        facts.add_event("s2", "wo", "后5", "我", ("我", "握"),
                        (cutoff[0] + 2000, cutoff[1]),
                        display_rank=1, display_page=1)
        return facts
    except Exception:
        facts.close()
        raise


class SplitSeamTest(unittest.TestCase):

    def _events_with_vectors(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        events = FrozenFacts(facts.db_path).events()
        return events

    def test_prefix_suffix_split_frozen_cutoff(self):
        events = self._events_with_vectors()
        prefix, suffix = prefix_suffix_split(events)
        by_id = {event.event_id: event for event in events}
        self.assertEqual({event.event_id for event in prefix},
                         {"p1", "p2", "p3"})
        self.assertEqual({event.event_id for event in suffix},
                         {"s1", "s2"})
        for event in prefix:
            self.assertTrue(by_id[event.event_id].in_prefix)
        for event in suffix:
            self.assertFalse(by_id[event.event_id].in_prefix)

    def test_prefix_includes_cutoff_event(self):
        events = self._events_with_vectors()
        cutoff = [e for e in events
                  if e.hlc == PREFIX_HLC_MAX_INCLUSIVE]
        self.assertEqual(len(cutoff), 1)
        self.assertTrue(cutoff[0].in_prefix)

    def test_replay_memory_crosses_the_boundary(self):
        """Suffix targets must see prefix history (exact walk-forward)."""
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        events = FrozenFacts(facts.db_path).events()
        provider = _fixture_provider(
            {
                # Query for 我 with the suffix context is close to history
                # that selected 我 (a prefix event).
                ("后4", "我"): (0.85, 0.53, 0.0, 0.0),
                ("后4", "握"): (0.2, 0.98, 0.0, 0.0),
            },
            {
                ("luna_pinyin", "wo", "我"): (1.0, 0.0, 0.0, 0.0),
                ("luna_pinyin", "wo", "握"): (0.0, 1.0, 0.0, 0.0),
            })
        vectors = CandidateVectorTable(events, provider)
        replay = WalkForwardReplay(FrozenFacts(facts.db_path), vectors)
        outcomes = replay.replay(OracleParams(
            tau=0.3, k_evidence=8, half_life=float("inf"),
            saturation_k=1.0), gamma=2.0)
        by_id = {outcome.event_id: outcome for outcome in outcomes}
        # s1 (suffix) has same-key prefix history -> it CAN be actionable,
        # proving memory crosses the split (never restarted at the cutoff).
        self.assertIn("s1", by_id)
        history = replay._same_key_active(
            FrozenFacts(facts.db_path).events()[-1])
        self.assertTrue(any(event.event_id == "p1" for event in history)
                        or any(event.event_id == "p2" for event in history))


class TauCalibrationTest(unittest.TestCase):

    def test_nearest_rank_quantiles(self):
        values = sorted([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        self.assertEqual(nearest_rank_quantile(values, 0.95), 0.6)
        self.assertEqual(nearest_rank_quantile(values, 0.99), 0.6)

    def test_not_calibratable_below_200_queries(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        provider = _fixture_provider({}, {})
        vectors = CandidateVectorTable(events, provider)
        replay = WalkForwardReplay(db, vectors)
        status = calibrate_tau(replay, [e for e in events
                                        if not e.retracted and e.in_prefix])
        self.assertEqual(status["state"], "not_calibratable")
        self.assertLess(status["queries"], 200)
        self.assertNotIn("quantiles", status)


class CalibrationQuantileTest(unittest.TestCase):
    """With >= 200 hard-negative queries the quantiles must come from the
    prefix only and be exactly the four frozen quantiles."""

    def _build_calibratable_facts(self):
        facts = SyntheticFacts()
        self.addCleanup(facts.close)
        # >= 200 prefix queries with a same-key hard-negative history: use
        # several keys, each alternating A/B selections on the same key, so
        # every query except a key's first event sees a different-selection
        # event in its own key history.  All hlc <= the frozen cutoff.
        keys = ["k1", "k2", "k3", "k4"]
        count_per_key = 60
        for key in keys:
            for index in range(count_per_key):
                selection = "A" if index % 2 == 0 else "B"
                facts.add_event(
                    "%s-q%d" % (key, index), key, "ctx-%s-%d" % (key, index),
                    selection, ("A", "B"),
                    (1787065000000 + index * 100 + keys.index(key) * 7, 0),
                    display_rank=2, display_page=1)
        return facts

    def test_calibratable_quantiles_exact_set(self):
        facts = self._build_calibratable_facts()
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        provider = _fixture_provider(
            {(event.preceding_text, candidate): _unit(0.9)
             for event in events
             for candidate in ("A", "B")},
            {("luna_pinyin", key, selection): _unit(0.7)
             for key in ("k1", "k2") for selection in ("A", "B")})
        vectors = CandidateVectorTable(events, provider)
        replay = WalkForwardReplay(db, vectors)
        prefix = [e for e in events if not e.retracted and e.in_prefix]
        status = calibrate_tau(replay, prefix)
        self.assertEqual(status["state"], "calibratable")
        self.assertEqual(set(status["quantiles"]),
                         {"0.95", "0.975", "0.99", "0.995"})
        self.assertGreaterEqual(status["queries"], 200)


class GridAndTerminalTest(unittest.TestCase):

    def test_predeclared_grid_manifest(self):
        manifest = grid_manifest(replicates=10000)
        self.assertEqual(manifest["contract"], "AC-159-v1")
        self.assertEqual(manifest["cutoff_hlc"], [1787667799562, 0])
        self.assertEqual(manifest["routes"], list(ROUTE_IDS))
        self.assertEqual(manifest["declared_before_metrics"], True)
        self.assertEqual(manifest["alpha"], 0.0)
        self.assertEqual(
            manifest["half_lives"], [8, 32, 128, 512, "inf"])
        self.assertEqual(manifest["k_evidence"], [8, 16, 32, 64])
        self.assertEqual(manifest["gamma"], [0.5, 1.0, 2.0, 4.0])
        self.assertEqual(manifest["saturation_k"], [1, 3, 7])
        self.assertEqual(
            manifest["tau_quantiles"], ["Q95", "Q97.5", "Q99", "Q99.5"])

    def test_delta_one_hard_cap(self):
        self.assertEqual(delta_one(1.0, 1), 0.5)
        self.assertEqual(delta_one(4.0, 1), 2.0)
        self.assertEqual(delta_one(0.5, 3), 0.125)

    def test_margin_base_prefix(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = _fixture_provider({}, {})
        vectors = CandidateVectorTable(db.events(), provider)
        replay = WalkForwardReplay(db, vectors)
        outcomes = replay.replay(OracleParams(
            tau=0.0, k_evidence=8, half_life=float("inf"),
            saturation_k=1.0), 0.0)
        prefix = [o for o in outcomes if o.in_prefix]
        p10, count = margin_base_prefix(prefix)
        # p1 and p3 are baseline-correct (display 1/1): margin proxy = 1.0.
        self.assertEqual(p10, 1.0)
        self.assertEqual(count, 2)

    def test_data_insufficient_when_no_suffix_complete(self):
        counts = {"replayable": 50, "group_complete": 0,
                  "keys": 0, "explicit_indexed": 0, "rank_gt1": 0,
                  "actionable_group_complete": 0, "actionable_keys": 0,
                  "coverage": 0.0}
        self.assertTrue(data_insufficient(counts))

    def test_assemble_terminal_insufficient_by_construction(self):
        """The decision surface has no public-B or personal-2x2 input."""
        import inspect
        signature = inspect.signature(assemble_shortlist)
        parameter_names = list(signature.parameters)
        self.assertEqual(parameter_names,
                         ["route_results", "data", "seed", "replicates"])
        self.assertNotIn("public_b", parameter_names)
        self.assertNotIn("personal_r", parameter_names)

    def test_prefix_selection_ignores_suffix_gate_fields(self):
        """Grid-family selection cannot read suffix claim observations."""
        def cell(half_life, top1, suffix_pass, k_evidence=8):
            return {
                "cell": {
                    "route_id": ROUTE_IDS[0], "half_life": half_life,
                    "k_evidence": k_evidence, "gamma": 0.5,
                    "saturation_k": 1,
                    "tau_quantile": "0.95", "tau": 0.5,
                },
                "prefix_metrics": {
                    "top1": top1, "mrr": 0.8,
                    "actionable_group_complete": 100,
                },
                "hard_gates": {"pass": suffix_pass},
            }

        cells = [cell(8, 0.9, False), cell(float("inf"), 0.9, True),
                 cell(8, 0.8, True, k_evidence=16)]
        selection = select_prefix_cells(cells)
        self.assertEqual(selection["reason"],
                         "max_prefix_top1_mrr_actionable")
        self.assertEqual([record["selected"] for record in cells],
                         [True, True, False])

    def test_route_runs_suffix_gates_after_prefix_selection(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = _fixture_provider(
            {("后4", "我"): _unit(0.85), ("后4", "握"): _unit(0.2)},
            {("luna_pinyin", "wo", "我"): _unit(1.0),
             ("luna_pinyin", "wo", "握"): _unit(0.0)})
        replay = WalkForwardReplay(
            db, CandidateVectorTable(db.events(), provider))
        result = run_route(
            replay, ROUTE_IDS[0], {
                "state": "calibratable",
                "queries": 200,
                "quantiles": {"0.95": 0.3, "0.975": 0.3,
                              "0.99": 0.3, "0.995": 0.3},
            }, {"prefix": {}, "suffix": {}}, seed=7, replicates=10000,
            max_cells=5, margin_p10=1.0)
        self.assertEqual(result["selection"]["mode"], "prefix_only")
        selected = [cell for cell in result["cells"]
                    if cell.get("selected")]
        unselected = [cell for cell in result["cells"]
                      if "eliminated" not in cell and not cell.get("selected")]
        self.assertTrue(selected)
        self.assertTrue(all("metrics" in cell for cell in selected))
        self.assertTrue(all("metrics" not in cell for cell in unselected))

    def test_finite_h_gate_uses_suffix_only(self):
        from walkforward_cc import EventOutcome

        def outcome(event_id, in_prefix, scheme_rank):
            return EventOutcome(
                event_id=event_id, hlc=(1, 0), key=("s", "c", "k"),
                key_hash="k", confirmation_source="explicit_current",
                competition_complete=True, group_complete=True,
                baseline_rank=1, scheme_rank=scheme_rank, actionable=True,
                total_mass=1.0, candidate_count=2, selection_index=0,
                kept_ids=("h",), kept_weights=(1.0,), kept_matches=(0,),
                in_prefix=in_prefix)

        gate = finite_h_gate(
            {"_outcomes": [outcome("prefix", True, 1),
                           outcome("suffix", False, 1)]},
            {"_outcomes": [outcome("prefix", True, 2),
                           outcome("suffix", False, 1)]})
        self.assertEqual(gate["union_events"], 1)
        self.assertEqual(gate["top1_diff"][0], 0.0)


class TerminalAssemblyTest(unittest.TestCase):
    """AC159-5: the terminal is one of the four legal states and follows
    the #159-quoted gate assembly rules (decide_final inputs only)."""

    def _data(self, suffix_gc=1200, suffix_actionable=1100):
        return {
            "prefix": {"group_complete": 2200, "actionable_group_complete": 900},
            "suffix": {"group_complete": suffix_gc,
                       "actionable_group_complete": suffix_actionable},
        }

    def _passing_cell(self, route_id, lift_claimable=True):
        return {
            "cell": {
                "route_id": route_id,
                "half_life": 8.0,
                "k_evidence": 8,
                "gamma": 0.5,
                "saturation_k": 1,
                "tau_quantile": "0.95",
                "tau": 0.5,
            },
            "delta_one_ok": True,
            "hard_gates": {
                "pass": True,
                "safety_top1_ok": True, "safety_mrr_ok": True,
                "mispromotion_point_ok": True, "mispromotion_ci_ok": True,
                "pollution_point_ok": True, "pollution_ci_ok": True,
            },
            "finite_h_gate": {"pass": True},
            "metrics": {"top1": 0.73, "mrr": 0.81},
            "ci": {"top1_vs_baseline": (0.03, (0.01, 0.05))},
            "lift": {
                "claimable": lift_claimable,
                "pass": lift_claimable,
                "reason": None,
            },
        }

    def test_insufficient_suffix_is_legal_terminal(self):
        decision = assemble_shortlist([{
            "route_id": ROUTE_IDS[0],
            "tau": {"state": "calibratable"},
            "cells": [self._passing_cell(ROUTE_IDS[0])],
        }], self._data(suffix_gc=0, suffix_actionable=0))
        self.assertEqual(decision["outcome"], "数据不足")
        self.assertEqual(decision["live_gamma"], 0.0)

    def test_all_not_calibratable_is_no_qualified(self):
        decision = assemble_shortlist([
            {"route_id": route,
             "tau": {"state": "not_calibratable", "queries": 12},
             "cells": []}
            for route in ROUTE_IDS], self._data())
        self.assertEqual(decision["outcome"], "无合格方案")

    def test_exact_shortlist_when_lift_claimable(self):
        decision = assemble_shortlist([{
            "route_id": ROUTE_IDS[0],
            "tau": {"state": "calibratable"},
            "cells": [self._passing_cell(ROUTE_IDS[0], True)],
        }], self._data())
        self.assertEqual(decision["outcome"], "exact_shortlist")
        self.assertEqual(decision["per_route"][0]["eligible_cells"], 1)

    def test_narrowed_claim_when_lift_unclaimable(self):
        decision = assemble_shortlist([{
            "route_id": ROUTE_IDS[0],
            "tau": {"state": "calibratable"},
            "cells": [self._passing_cell(ROUTE_IDS[0], False)],
        }], self._data(suffix_actionable=150))
        self.assertEqual(decision["outcome"], "收窄声称_shortlist")
        self.assertEqual(decision["per_route"][0]["eligible_cells"], 1)

    def test_suffix_claims_only_use_prefix_selected_cells(self):
        finite = self._passing_cell(ROUTE_IDS[0], True)
        finite["selected"] = True
        infinite = self._passing_cell(ROUTE_IDS[0], True)
        infinite["cell"]["half_life"] = float("inf")
        infinite["selected"] = True
        unselected = self._passing_cell(ROUTE_IDS[0], True)
        unselected["cell"]["k_evidence"] = 16
        unselected["selected"] = False
        decision = assemble_shortlist([{
            "route_id": ROUTE_IDS[0],
            "tau": {"state": "calibratable"},
            "selection": {"mode": "prefix_only"},
            "cells": [finite, infinite, unselected],
        }], self._data())
        self.assertEqual(decision["outcome"], "exact_shortlist")
        self.assertEqual(decision["per_route"][0]["selected_cells"], 2)
        self.assertEqual(decision["per_route"][0]["eligible_cells"], 2)
        self.assertEqual(
            decision["per_route"][0]["eliminated_by_reason"],
            {"prefix_not_selected": 1})


class ReportPrivacyTest(unittest.TestCase):

    def _build_minimal_report(self):
        from snapshot import take_snapshot
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        snapshot = {
            "path": facts.db_path,
            "sha256": "0" * 64,
            "identity": {"history_id": "h", "store_epoch": "e",
                         "fact_schema_version": "1", "max_hlc": [0, 0]},
            "status": {"status_check": "skipped"},
        }
        events = db.events()
        decision = {
            "outcome": "无合格方案",
            "reason": "test decision",
            "data": {"prefix": {}, "suffix": {}},
            "per_route": [],
            "total_eligible_cells": 0,
            "live_gamma": 0.0,
        }
        report = build_report(
            engine_version=ENGINE_VERSION,
            code_sha="0" * 40,
            snapshot=snapshot,
            prefix_events=[e for e in events if e.in_prefix],
            suffix_events=[e for e in events if not e.in_prefix],
            route_results=[{
                "route_id": ROUTE_IDS[0],
                "tau": {"state": "not_calibratable"},
                "cells": [],
                "data": {},
            }],
            decision=decision,
            data={},
            tau_status=[],
            margin_base="prefix proxy",
            grid_manifest=grid_manifest(10000),
            seed=20260817,
            replicates=10000,
            public_b_unused=True,
            personal_r_unused=True,
            live_gamma=0.0,
            report_notes=["ac159 test"],
        )
        self.assertEqual(report["contract"], "AC-159-v1")
        self.assertEqual(report["split"]["cutoff_hlc"],
                         [1787667799562, 0])
        return report

    def test_report_privacy_scan_passes(self):
        report = self._build_minimal_report()
        self.assertTrue(verify_privacy(report))
        markdown = render_markdown(report)
        self.assertIn("Report SHA-256", markdown)

    def test_report_has_no_raw_text(self):
        report = self._build_minimal_report()
        serialized = repr(report)
        self.assertNotIn("前1", serialized)
        self.assertNotIn("我", serialized)
        self.assertNotIn("/Users/", serialized)


class ContractIdentityTest(unittest.TestCase):

    def test_contract_id(self):
        self.assertEqual(CONTRACT_ID, "AC-159-v1")
        self.assertEqual(ENGINE_VERSION, "suffix-walkforward-v2")


if __name__ == "__main__":
    unittest.main()
