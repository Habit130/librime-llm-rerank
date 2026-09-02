#!/usr/bin/env python3
"""Model-free gate for the AC-162-v1 actionable milestone census.

Pins without loading any model, venv or GPU:

- CENSUS3000-1: the freeze binds snapshot SHA-256, history_id, store_epoch,
  code SHA, route/model/tokenizer identity, cutoff and reference parameters
  and is written before any score; identity inputs are fail-closed.
- CENSUS3000-2: the census replays through the AC-159 seam under the exact
  reference parameters and reproduces the AC-159 count semantics; the count
  values bit-match ``grid_cc.data_counts`` and the accepted AC-159 report.
- CENSUS3000-3: prefix/suffix/total blocks carry the four frozen counts and
  no other route/grid/quality paths exist in the surface.
- CENSUS3000-4: exactly one legal terminal; reached_3000 at 3000,
  pending_3000 below with the exact remaining count.
- CENSUS3000-5: the split stays at the frozen [1787667799562,0] cutoff, is
  never the snapshot maximum, and the split hashes are deterministic.
- CENSUS3000-6: freeze/report pass the privacy scan and carry hashes,
  identities, counts and the terminal only.
- CENSUS3000-7: the driver surface never reads a live configuration; the
  fixture end-to-end run leaves no live-store touch.

The census itself is exercised through the deterministic AC-159 fixture
provider; no model, no venv, no GPU.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from oracle import OracleParams  # noqa: E402

from fixture_facts import SyntheticFacts  # noqa: E402
from evidence import CandidateFixtureRepresentationProvider  # noqa: E402

from walkforward_cc import (  # noqa: E402
    PREFIX_HLC_MAX_INCLUSIVE, ROUTE_IDS, GROUP_COMPLETE_N,
    CandidateVectorTable, FrozenFacts, WalkForwardReplay,
    prefix_suffix_split)
from grid_cc import data_counts  # noqa: E402
from actionable_milestone_census import (  # noqa: E402
    AC159_REFERENCE, CENSUS_COUNT_KEYS, CONTRACT_ID, ENGINE_VERSION,
    MILESTONE_THRESHOLD, ROUTE_ID, TERMINAL_PENDING, TERMINAL_REACHED,
    CensusError, PrivacyViolation, build_freeze, build_report,
    census_counts, census_outcomes, legal_terminal, reference_params,
    render_markdown, split_census_counts, split_hashes, verify_privacy,
    AC159_CONTRACT_ID)
import run_actionable_milestone_census as census_runner  # noqa: E402


def _unit(cosine, dimension=4):
    import math
    r = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return tuple([cosine, r] + [0.0] * (dimension - 2))


def _fixture_provider(query_vectors, event_vectors):
    return CandidateFixtureRepresentationProvider(
        "fixture:ac162",
        query_vectors,
        event_vectors,
        default_query=(1.0, 0.0, 0.0, 0.0),
        default_event=(0.0, 1.0, 0.0, 0.0))


def _synthetic_with_split():
    """A synthetic snapshot with events straddling the frozen cutoff.

    Prefix events hold hlc <= [1787667799562, 0]; suffix events are strictly
    later (including several past the snapshot's own minimum, proving the
    split is the frozen cutoff, never the snapshot maximum).
    """
    facts = SyntheticFacts()
    cutoff = PREFIX_HLC_MAX_INCLUSIVE
    try:
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
        facts.add_event("s3", "wo", "后6", "我", ("我", "握"),
                        (cutoff[0] + 3000, cutoff[1]),
                        display_rank=1, display_page=1)
        facts.add_event("s4", "wo", "后7", "握", ("我", "握"),
                        (cutoff[0] + 4000, cutoff[1]),
                        display_rank=2, display_page=1)
        return facts
    except Exception:
        facts.close()
        raise


def _actionable_provider():
    """Query vectors close to the matching history event vectors: every
    same-key event is actionable (s > 0 at tau=0)."""
    queries = {}
    for preceding in ("前1", "前2", "前3", "后4", "后5", "后6", "后7"):
        queries[(preceding, "我")] = _unit(0.9)
        queries[(preceding, "握")] = _unit(0.1)
    events = {
        ("luna_pinyin", "wo", "我"): _unit(1.0),
        ("luna_pinyin", "wo", "握"): _unit(0.0),
    }
    return _fixture_provider(queries, events)


class ContractConstantsTest(unittest.TestCase):
    """CENSUS3000-2: the census is pinned to the AC-159 first route."""

    def test_contract_identity(self):
        self.assertEqual(CONTRACT_ID, "AC-162-v1")
        self.assertEqual(AC159_CONTRACT_ID, "AC-159-v1")
        self.assertEqual(ENGINE_VERSION, "actionable-milestone-census-v1")

    def test_single_frozen_route(self):
        self.assertEqual(ROUTE_ID, ROUTE_IDS[0])
        self.assertEqual(ROUTE_ID, "dedicated_qwen3_embedding_0_6b")

    def test_frozen_cutoff_is_the_ac159_cutoff(self):
        self.assertEqual(PREFIX_HLC_MAX_INCLUSIVE, (1787667799562, 0))

    def test_reference_parameters_exact(self):
        params = reference_params()
        self.assertEqual(params.tau, 0.0)
        self.assertEqual(params.k_evidence, 8)
        self.assertEqual(params.half_life, float("inf"))
        self.assertEqual(params.saturation_k, 1.0)
        record = __import__("actionable_milestone_census",
                            fromlist=["reference_parameters_record"])
        block = record.reference_parameters_record()
        self.assertEqual(block["gamma"], 0.0)
        self.assertEqual(block["actionable"], "any(s > 0)")
        self.assertEqual(block["group_complete_n"], GROUP_COMPLETE_N)
        self.assertEqual(block["group_complete_n"], 32)
        self.assertEqual(block["payload_rule"], "last64(preceding)+candidate")
        self.assertEqual(
            block["query_instruction"],
            "Represent the candidate-conditioned query for semantic "
            "retrieval.")

    def test_legal_terminal_constants(self):
        self.assertEqual(MILESTONE_THRESHOLD, 3000)
        self.assertEqual(TERMINAL_REACHED, "reached_3000")
        self.assertEqual(TERMINAL_PENDING, "pending_3000")


class Ac159SeamEquivalenceTest(unittest.TestCase):
    """CENSUS3000-2: census counts are bit-identical to the AC-159 seam."""

    def test_census_counts_equal_data_counts(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        provider = _actionable_provider()
        outcomes = census_outcomes(db, provider)
        ac159 = data_counts(outcomes)
        self.assertEqual(
            census_counts(outcomes),
            {key: ac159[key] for key in CENSUS_COUNT_KEYS})

    def test_census_replay_is_the_direct_seam_replay(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        provider = _actionable_provider()
        census = census_outcomes(db, provider)
        vectors = CandidateVectorTable(events, provider)
        direct = WalkForwardReplay(db, vectors).replay(
            reference_params(), 0.0)
        self.assertEqual(
            [(o.event_id, o.actionable, o.group_complete, o.in_prefix)
             for o in census],
            [(o.event_id, o.actionable, o.group_complete, o.in_prefix)
             for o in direct])

    def test_actionable_is_any_s_greater_than_zero(self):
        """Actionability must follow the seam: any(s > 0), not a tau gate."""
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = _actionable_provider()
        outcomes = census_outcomes(db, provider)
        by_id = {o.event_id: o for o in outcomes}
        # tau=0: any event with same-key history evidence is actionable;
        # p3 has no earlier same-key history so it carries no evidence.
        self.assertTrue(by_id["p1"].actionable)
        self.assertTrue(by_id["p2"].actionable)
        self.assertFalse(by_id["p3"].actionable)
        self.assertTrue(all(by_id[e].actionable
                            for e in ("s1", "s2", "s3", "s4")))
        # Actionability is exactly the seam's any(s > 0): no tau threshold
        # and no separate gate — positive evidence mass means actionable.
        for outcome in outcomes:
            self.assertEqual(outcome.actionable, outcome.total_mass > 0.0)

    def test_group_complete_is_saved_size_under_32(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = _actionable_provider()
        outcomes = census_outcomes(db, provider)
        self.assertTrue(all(o.group_complete for o in outcomes))
        # A size-32 competition is NOT group-complete even with the
        # persisted bit true (diagnostic-only bit, #76/#77 rewrite).
        big = SyntheticFacts()
        self.addCleanup(big.close)
        competition = tuple("c%d" % i for i in range(32))
        big.add_event("big1", "wo", "ctx", "c0", competition,
                      (PREFIX_HLC_MAX_INCLUSIVE[0] - 5000, 0),
                      competition_complete=True, display_rank=1,
                      display_page=1)
        bdb = FrozenFacts(big.db_path)
        self.addCleanup(bdb.close)
        big_events = bdb.events()
        self.assertFalse(big_events[0].group_complete)
        self.assertTrue(big_events[0].competition_complete)

    def test_accepted_ac159_counts_reproduced_from_committed_artifact(self):
        """The census reference block byte-matches the accepted AC-159
        report (read-only, quoted, never re-verified or forced)."""
        report_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "suffix_walkforward_ac159", "suffix_walkforward_report.json")
        with open(report_path, encoding="utf-8") as handle:
            accepted = json.load(handle)
        data = accepted["data"]
        self.assertEqual(
            AC159_REFERENCE["prefix_actionable_group_complete"],
            data["prefix"]["actionable_group_complete"])
        self.assertEqual(
            AC159_REFERENCE["suffix_actionable_group_complete"],
            data["suffix"]["actionable_group_complete"])
        self.assertEqual(
            AC159_REFERENCE["total_actionable_group_complete"],
            data["prefix"]["actionable_group_complete"]
            + data["suffix"]["actionable_group_complete"])
        self.assertEqual(
            AC159_REFERENCE["snapshot_sha256"],
            accepted["snapshot"]["sha256"])


class CutoffRegressionTest(unittest.TestCase):
    """CENSUS3000-5: the split is the frozen cutoff, never the snapshot max."""

    def test_split_uses_frozen_cutoff_not_snapshot_max(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        snapshot_max = max(event.hlc for event in events)
        self.assertGreater(snapshot_max, PREFIX_HLC_MAX_INCLUSIVE)
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        self.assertEqual({e.event_id for e in prefix},
                         {"p1", "p2", "p3"})
        self.assertEqual({e.event_id for e in suffix},
                         {"s1", "s2", "s3", "s4"})
        # s3/s4 are past the preserved cutoff, not the snapshot max.
        self.assertTrue(all(e.hlc > PREFIX_HLC_MAX_INCLUSIVE
                            for e in suffix))
        self.assertTrue(any(e.hlc < snapshot_max for e in suffix))

    def test_cutoff_event_is_in_prefix(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        prefix, _suffix = prefix_suffix_split(
            [e for e in events if not e.retracted])
        at_cutoff = [e for e in events
                     if e.hlc == PREFIX_HLC_MAX_INCLUSIVE]
        self.assertEqual(len(at_cutoff), 1)
        self.assertIn(at_cutoff[0].event_id,
                      {e.event_id for e in prefix})

    def test_split_hashes_deterministic_and_partitioned(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        first = split_hashes(facts.db_path, prefix, suffix)
        second = split_hashes(facts.db_path, prefix, suffix)
        self.assertEqual(first, second)
        self.assertEqual(first["cutoff_hlc"], [1787667799562, 0])
        self.assertEqual(first["prefix_event_count"], 3)
        self.assertEqual(first["suffix_event_count"], 4)
        self.assertNotEqual(first["prefix_sha256"], first["suffix_sha256"])
        self.assertEqual(first["snapshot_sha256"],
                         _file_sha256(facts.db_path))

    def test_split_hashes_fail_closed_on_crossing_events(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        suffix_one = suffix[0]
        prefix_one = prefix[0]
        # A prefix containing a strictly-later event fails the partition.
        with self.assertRaises(CensusError):
            split_hashes(facts.db_path,
                         prefix + [suffix_one],
                         [e for e in suffix if e.event_id
                          != suffix_one.event_id])
        # A suffix containing an at-or-before-cutoff event fails it too.
        with self.assertRaises(CensusError):
            split_hashes(facts.db_path,
                         [e for e in prefix if e.event_id
                          != prefix_one.event_id],
                         suffix + [prefix_one])


class TerminalTest(unittest.TestCase):
    """CENSUS3000-4: exactly one legal terminal at 2999/3000."""

    def test_2999_is_pending_with_remaining_one(self):
        record = legal_terminal(2999)
        self.assertEqual(record["outcome"], TERMINAL_PENDING)
        self.assertEqual(record["remaining"], 1)
        self.assertEqual(record["threshold"], 3000)

    def test_3000_is_reached(self):
        record = legal_terminal(3000)
        self.assertEqual(record["outcome"], TERMINAL_REACHED)
        self.assertEqual(record["remaining"], 0)

    def test_2550_is_pending_with_remaining_450(self):
        record = legal_terminal(2550)
        self.assertEqual(record["outcome"], TERMINAL_PENDING)
        self.assertEqual(record["remaining"], 450)

    def test_markedly_above_is_reached_without_remaining(self):
        record = legal_terminal(17420)
        self.assertEqual(record["outcome"], TERMINAL_REACHED)
        self.assertEqual(record["remaining"], 0)

    def test_zero_is_pending_full_remaining(self):
        record = legal_terminal(0)
        self.assertEqual(record["outcome"], TERMINAL_PENDING)
        self.assertEqual(record["remaining"], 3000)

    def test_negative_is_a_fault_not_a_terminal(self):
        with self.assertRaises(CensusError):
            legal_terminal(-1)

    def test_exactly_one_outcome_present(self):
        reached_keys = {k for k in legal_terminal(3000) if k == "outcome"}
        pending = legal_terminal(2999)
        self.assertEqual(reached_keys, {"outcome"})
        self.assertIn(pending["outcome"], (TERMINAL_PENDING,
                                           TERMINAL_REACHED))


class SplitCountsTest(unittest.TestCase):
    """CENSUS3000-3: prefix/suffix/total blocks with the four counts."""

    def test_split_counts_blocks(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = _actionable_provider()
        outcomes = census_outcomes(db, provider)
        counts = split_census_counts(outcomes)
        self.assertEqual(set(counts), {"prefix", "suffix", "total"})
        for block in counts.values():
            self.assertEqual(set(block), set(CENSUS_COUNT_KEYS))
        # All fixture events are group-complete; p3 is the earliest same-key
        # event so it has no history evidence and is not actionable.
        self.assertEqual(counts["prefix"]["replayable"], 3)
        self.assertEqual(counts["prefix"]["group_complete"], 3)
        self.assertEqual(counts["prefix"]["actionable_group_complete"], 2)
        self.assertEqual(counts["suffix"]["replayable"], 4)
        self.assertEqual(counts["suffix"]["group_complete"], 4)
        self.assertEqual(counts["suffix"]["actionable_group_complete"], 4)
        self.assertEqual(counts["total"]["replayable"], 7)
        self.assertEqual(counts["total"]["group_complete"], 7)
        self.assertEqual(counts["total"]["actionable_group_complete"], 6)
        # Total == prefix + suffix (the partition is exhaustive).
        self.assertEqual(
            counts["total"]["actionable_group_complete"],
            counts["prefix"]["actionable_group_complete"]
            + counts["suffix"]["actionable_group_complete"])

    def test_split_counts_use_key_cardinality(self):
        """actionable_keys counts distinct choice-problem keys, not events."""
        facts = SyntheticFacts()
        self.addCleanup(facts.close)
        cutoff = PREFIX_HLC_MAX_INCLUSIVE
        # Three events on one key; the earliest anchors the history chain.
        facts.add_event("a0", "wo", "ctx0", "我", ("我", "握"),
                        (cutoff[0] - 300, 0), display_rank=1,
                        display_page=1)
        facts.add_event("a1", "wo", "ctx1", "我", ("我", "握"),
                        (cutoff[0] - 100, 0), display_rank=1,
                        display_page=1)
        facts.add_event("a2", "wo", "ctx2", "握", ("我", "握"),
                        (cutoff[0] - 200, 0), display_rank=2,
                        display_page=1)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = _fixture_provider(
            {("ctx0", "我"): _unit(0.9),
             ("ctx1", "我"): _unit(0.9), ("ctx1", "握"): _unit(0.9),
             ("ctx2", "我"): _unit(0.9)},
            {("luna_pinyin", "wo", "我"): _unit(1.0),
             ("luna_pinyin", "wo", "握"): _unit(1.0)})
        counts = split_census_counts(census_outcomes(db, provider))
        # a0 is the earliest same-key event (no history evidence); a1 and a2
        # are actionable -> 2 actionable events, but only 1 distinct key.
        self.assertEqual(counts["prefix"]["actionable_group_complete"], 2)
        self.assertEqual(counts["prefix"]["actionable_keys"], 1)


class FreezeIdentityTest(unittest.TestCase):
    """CENSUS3000-1: the freeze binds every identity and fails closed."""

    def _snapshot_record(self, path, history_id="h1", store_epoch="e1"):
        return {
            "path": path,
            "sha256": _file_sha256(path),
            "identity": {"history_id": history_id,
                         "store_epoch": store_epoch},
            "status": {"status_check": "ok"},
            "source": "claim_time_online_backup",
        }

    def _route_identity(self, route_id=ROUTE_ID):
        return {
            "route_id": route_id,
            "adapter": "qwen3",
            "instruction": "Represent the candidate-conditioned query for "
                           "semantic retrieval.",
            "pooling": "last-token",
            "model_digest": "0" * 64,
            "tokenizer_digest": "1" * 64,
            "dimension": 1024,
            "vector_dimension": 1024,
        }

    def test_freeze_binds_snapshot_code_route_cutoff_params(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        snapshot = self._snapshot_record(facts.db_path)
        freeze = build_freeze(
            code_sha="a" * 40, snapshot=snapshot,
            route_identity=self._route_identity(),
            prefix_events=prefix, suffix_events=suffix)
        self.assertEqual(freeze["contract"], "AC-162-v1")
        self.assertEqual(freeze["code_sha"], "a" * 40)
        self.assertEqual(freeze["snapshot_sha256"], snapshot["sha256"])
        self.assertEqual(freeze["history_id"], "h1")
        self.assertEqual(freeze["store_epoch"], "e1")
        self.assertEqual(freeze["route"]["route_id"], ROUTE_ID)
        self.assertEqual(freeze["cutoff_hlc"], [1787667799562, 0])
        self.assertEqual(freeze["reference_parameters"]["tau"], 0.0)
        self.assertEqual(freeze["reference_parameters"]["gamma"], 0.0)
        self.assertIn("split", freeze)
        self.assertEqual(freeze["split"]["prefix_event_count"], 3)
        self.assertEqual(freeze["split"]["suffix_event_count"], 4)

    def test_freeze_fails_closed_without_snapshot_sha(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        snapshot = self._snapshot_record(facts.db_path)
        snapshot["sha256"] = None
        with self.assertRaises(CensusError):
            build_freeze(code_sha="a" * 40, snapshot=snapshot,
                         route_identity=self._route_identity(),
                         prefix_events=prefix, suffix_events=suffix)

    def test_freeze_fails_closed_without_store_identity(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        snapshot = self._snapshot_record(facts.db_path)
        snapshot["identity"] = {"history_id": "h1"}  # no store_epoch
        with self.assertRaises(CensusError):
            build_freeze(code_sha="a" * 40, snapshot=snapshot,
                         route_identity=self._route_identity(),
                         prefix_events=prefix, suffix_events=suffix)

    def test_freeze_fails_closed_on_wrong_route(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        snapshot = self._snapshot_record(facts.db_path)
        with self.assertRaises(CensusError):
            build_freeze(code_sha="a" * 40, snapshot=snapshot,
                         route_identity=self._route_identity(
                             route_id="dedicated_bge_m3"),
                         prefix_events=prefix, suffix_events=suffix)

    def test_freeze_fails_closed_without_code_sha(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        snapshot = self._snapshot_record(facts.db_path)
        with self.assertRaises(CensusError):
            build_freeze(code_sha="", snapshot=snapshot,
                         route_identity=self._route_identity(),
                         prefix_events=prefix, suffix_events=suffix)

    def test_freeze_passes_privacy_scan(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        freeze = build_freeze(
            code_sha="a" * 40,
            snapshot=self._snapshot_record(facts.db_path),
            route_identity=self._route_identity(),
            prefix_events=prefix, suffix_events=suffix)
        self.assertTrue(verify_privacy(freeze))
        serialized = repr(freeze)
        self.assertNotIn("前1", serialized)
        self.assertNotIn("我", serialized)
        self.assertNotIn("/Users/", serialized)


class ReportTest(unittest.TestCase):
    """CENSUS3000-3/6: the report carries counts, terminal, identities only."""

    def _report(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        events = db.events()
        targets = [e for e in events if not e.retracted]
        prefix, suffix = prefix_suffix_split(targets)
        counts = split_census_counts(census_outcomes(db, _actionable_provider()))
        return build_report(
            code_sha="a" * 40,
            snapshot={
                "path": facts.db_path,
                "sha256": _file_sha256(facts.db_path),
                "identity": {"history_id": "h1", "store_epoch": "e1"},
                "status": {"status_check": "ok"},
                "source": "claim_time_online_backup",
            },
            route_identity={
                "route_id": ROUTE_ID,
                "adapter": "qwen3",
                "model_digest": "0" * 64,
                "tokenizer_digest": "1" * 64,
            },
            counts=counts,
            terminal=legal_terminal(
                counts["total"]["actionable_group_complete"]),
            prefix_events=prefix, suffix_events=suffix)

    def test_report_blocks_and_identities(self):
        report = self._report()
        self.assertEqual(report["contract"], "AC-162-v1")
        self.assertEqual(set(report["counts"]),
                         {"prefix", "suffix", "total"})
        self.assertEqual(report["counts"]["total"]["replayable"], 7)
        self.assertIn(report["terminal"]["outcome"],
                      (TERMINAL_REACHED, TERMINAL_PENDING))
        self.assertEqual(report["cutoff"]["hlc"], [1787667799562, 0])
        self.assertEqual(report["route"]["route_id"], ROUTE_ID)
        self.assertEqual(report["snapshot"]["history_id"], "h1")
        self.assertIn("report_sha256", report)

    def test_report_has_no_other_route_or_grid_surface(self):
        report = self._report()
        serialized = repr(report)
        # No other route, grid, bootstrap or quality-gate blocks appear in
        # the report surface (the claim_support no_* flags name them but
        # never carry results).
        for forbidden in ("qwen_l28_candidate_span_mean",
                          "dedicated_bge_m3",
                          "replicates", "cells", "per_route",
                          "quantiles", "grid_manifest", "ci"):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(report["claim_support"]["no_other_route"])
        self.assertTrue(report["claim_support"]["no_tau_calibration"])
        self.assertTrue(report["claim_support"]["no_parameter_grid"])
        self.assertTrue(report["claim_support"]["no_quality_gate"])
        self.assertTrue(report["claim_support"]["no_bootstrap"])
        self.assertTrue(report["claim_support"]["no_shortlist"])
        self.assertTrue(report["claim_support"]["no_ann"])
        self.assertFalse(report["claim_support"]["walkforward_started"])
        self.assertEqual(report["claim_support"]["live_gamma"], 0.0)

    def test_report_privacy_and_no_raw_text(self):
        report = self._report()
        self.assertTrue(verify_privacy(report))
        serialized = repr(report)
        for raw in ("前1", "后4", "我", "握", "/Users/", "facts.sqlite"):
            self.assertNotIn(raw, serialized)
        markdown = render_markdown(report)
        self.assertIn("Actionable Milestone Census", markdown)
        self.assertIn("Report SHA-256", markdown)
        self.assertIn("Terminal", markdown)

    def test_verify_privacy_rejects_private_content(self):
        with self.assertRaises(PrivacyViolation):
            verify_privacy({"leak": "/Users/habit/secret.txt"})
        with self.assertRaises(PrivacyViolation):
            verify_privacy({"leak": "~/Library/Rime/user.yaml"})


class DriverFixtureEndToEndTest(unittest.TestCase):
    """The runner wiring end-to-end, model-free (--fixture).

    Runs the real driver path (snapshot -> identity freeze -> fixture
    vectors -> replay -> counts -> terminal -> freeze/report/mirror) on a
    synthetic snapshot with the git-clean check stubbed so the test itself
    can run from a dirty worktree.
    """

    def _run_driver(self, snapshot_path):
        temp = tempfile.mkdtemp(prefix="ac162_test_")
        self.addCleanup(lambda: shutil.rmtree(temp, ignore_errors=True))
        work = os.path.join(temp, "work")
        artifact = os.path.join(temp, "artifacts")
        committed = os.path.join(temp, "committed")
        argv = ["--fixture", "--snapshot", snapshot_path,
                "--work-dir", work, "--artifact-dir", artifact,
                "--committed-artifact-dir", committed]
        with mock.patch.object(census_runner, "current_code_sha",
                               return_value="b" * 40):
            status = census_runner.main(argv)
        self.assertEqual(status, 0)
        return artifact, committed

    def test_fixture_driver_writes_freeze_then_report(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        artifact, committed = self._run_driver(facts.db_path)

        freeze_path = os.path.join(
            artifact, "actionable_milestone_census_freeze.json")
        report_path = os.path.join(
            artifact, "actionable_milestone_census_report.json")
        md_path = os.path.join(
            artifact, "ACTIONABLE_MILESTONE_CENSUS_REPORT.md")
        self.assertTrue(os.path.isfile(freeze_path))
        self.assertTrue(os.path.isfile(report_path))
        self.assertTrue(os.path.isfile(md_path))
        freeze = json.load(open(freeze_path, encoding="utf-8"))
        report = json.load(open(report_path, encoding="utf-8"))

        # Frozen identities.
        self.assertEqual(freeze["contract"], "AC-162-v1")
        self.assertEqual(freeze["code_sha"], "b" * 40)
        self.assertEqual(freeze["history_id"], "synthetic-history")
        self.assertEqual(freeze["store_epoch"], "synthetic-epoch")
        self.assertEqual(freeze["route"]["route_id"], ROUTE_ID)
        self.assertEqual(freeze["cutoff_hlc"], [1787667799562, 0])
        self.assertEqual(freeze["split"]["prefix_event_count"], 3)
        self.assertEqual(freeze["split"]["suffix_event_count"], 4)

        # Counts must equal the direct seam replay on the same snapshot.
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = census_runner._fixture_provider(db.events(), ROUTE_ID)
        expected = split_census_counts(census_outcomes(db, provider))
        self.assertEqual(report["counts"], expected)
        self.assertEqual(report["terminal"],
                         legal_terminal(
                             expected["total"]["actionable_group_complete"]))

        # Mirrored desensitized artifacts.
        for name in ("actionable_milestone_census_freeze.json",
                     "actionable_milestone_census_report.json",
                     "ACTIONABLE_MILESTONE_CENSUS_REPORT.md"):
            source = os.path.join(artifact, name)
            mirror = os.path.join(committed, name)
            self.assertTrue(os.path.isfile(mirror))
            with open(source, "rb") as a, open(mirror, "rb") as b:
                self.assertEqual(a.read(), b.read())

        # Privacy checks on persisted artifacts.
        self.assertTrue(verify_privacy(freeze))
        self.assertTrue(verify_privacy(report))

    def test_fixture_driver_reports_pending_terminal(self):
        facts = _synthetic_with_split()
        self.addCleanup(facts.close)
        artifact, _committed = self._run_driver(facts.db_path)
        report = json.load(open(os.path.join(
            artifact, "actionable_milestone_census_report.json"),
            encoding="utf-8"))
        self.assertEqual(report["terminal"]["outcome"], "pending_3000")
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        provider = census_runner._fixture_provider(db.events(), ROUTE_ID)
        total = split_census_counts(
            census_outcomes(db, provider))["total"][
                "actionable_group_complete"]
        self.assertEqual(report["terminal"]["remaining"], 3000 - total)

    def test_driver_missing_snapshot_fails_closed(self):
        with mock.patch.object(census_runner, "current_code_sha",
                               return_value="b" * 40):
            status = census_runner.main([
                "--fixture", "--snapshot", "/nonexistent/snapshot.sqlite3",
                "--work-dir", tempfile.mkdtemp(prefix="ac162_missing_")])
        self.assertEqual(status, 3)


def _file_sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()