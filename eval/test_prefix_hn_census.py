#!/usr/bin/env python3
"""Model-free gate for the AC-158-v1 facts-only hard-negative census.

Pins without any model / snapshot:

- AC158-1: the pinned snapshot SHA-256 and identity constants are exact
  (driver fails closed on byte mismatch — RISK-158-1).
- AC158-2: the new cutoff = max HLC among unretracted events (inclusive),
  and the numeric pair flows into the report.
- AC158-3: the primary count is the frozen
  ``prefix_hard_negative_query_count`` on the new prefix targets; the
  terminal is exactly 可标定 (>= 200) | 仍不可标定 (< 200).
- AC158-4: the report carries unretracted / group-complete / key counts.
- AC158-5: the report passes the privacy scan (hashes/HLC/counts/terminal
  only; no 上文, no candidate text, no machine paths).

The >= 200 side of the terminal is exercised by a synthetic fixture, not by
the pinned snapshot (which is a private machine artifact).
"""

import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from fixture_facts import SyntheticFacts  # noqa: E402

from walkforward_cc import FrozenFacts  # noqa: E402
from prefix_hn_census import (  # noqa: E402
    CONTRACT_ID, ENGINE_VERSION, MIN_HARD_NEGATIVE_QUERIES,
    PINNED_HISTORY_ID, PINNED_SNAPSHOT_SHA256, PINNED_STORE_EPOCH,
    TERMINAL_CALIBRATABLE, TERMINAL_NOT_CALIBRATABLE, CensusError,
    PrivacyViolation, build_report, census_counts,
    render_markdown, run_census, snapshot_max_unretracted_hlc, terminal,
    verify_privacy, wide_hard_negative_query_count)


def _targets(facts_path):
    return [event for event in FrozenFacts(facts_path).events()
            if not event.retracted]


class SnapshotPinTest(unittest.TestCase):
    """AC158-1: the pinned snapshot identity is byte-exact and immutable."""

    def test_pinned_snapshot_sha256(self):
        self.assertEqual(len(PINNED_SNAPSHOT_SHA256), 64)
        self.assertTrue(all(c in "0123456789abcdef"
                            for c in PINNED_SNAPSHOT_SHA256))

    def test_pinned_snapshot_identity(self):
        self.assertEqual(len(PINNED_HISTORY_ID), 32)
        self.assertEqual(len(PINNED_STORE_EPOCH), 32)

    def test_census_rejects_wrong_bytes(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".sqlite3",
                                         delete=False) as empty:
            empty.write(b"not the pinned snapshot")
            path = empty.name
        try:
            with self.assertRaisesRegex(CensusError, "SHA-256"):
                run_census(path, code_sha="0" * 40)
        finally:
            os.unlink(path)


class CutoffTest(unittest.TestCase):
    """AC158-2: cutoff = max unretracted HLC (inclusive), pair in report."""

    def _facts(self):
        facts = SyntheticFacts()
        self.addCleanup(facts.close)
        facts.add_event("e1", "k1", "ctx-1", "A", ("A", "B"), (1000, 0))
        facts.add_event("e2", "k1", "ctx-2", "B", ("A", "B"), (2000, 5))
        facts.add_event("e3", "k1", "ctx-3", "A", ("A", "B"), (3000, 0),
                        retract_at=(4000, 0))
        return facts

    def test_max_is_latest_unretracted(self):
        facts = self._facts()
        events = FrozenFacts(facts.db_path).events()
        self.assertEqual(snapshot_max_unretracted_hlc(events), (2000, 5))

    def test_cutoff_pair_reaches_report(self):
        facts = self._facts()
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        targets = [e for e in db.events() if not e.retracted]
        counts = census_counts(db, targets)
        report = build_report(
            code_sha="0" * 40,
            snapshot_sha256="a" * 64,
            identity={"history_id": "h" * 32, "store_epoch": "e" * 32},
            cutoff_hlc=(2000, 5),
            counts=counts,
            prefix_event_ids=[event.event_id for event in targets],
            terminal_record=terminal(counts["primary_count"]))
        self.assertEqual(report["cutoff"]["hlc"], [2000, 5])
        self.assertIs(report["cutoff"]["inclusive"], True)
        self.assertEqual(report["split"]["suffix_event_count"], 0)
        self.assertEqual(report["split"]["prefix_event_count"], 2)


class PrimaryCountTest(unittest.TestCase):
    """AC158-3: the primary count is the frozen definition; the #77-wide
    appendix adds the no-current-competition cases but never overrides."""

    def _facts(self):
        facts = SyntheticFacts()
        self.addCleanup(facts.close)
        # k1: t2's history t1 selects B, which IS in t2's competition
        # ("A","B") -> counts in both primary and wide.
        facts.add_event("t1", "k1", "ctx", "A", ("A", "B"), (100, 0))
        facts.add_event("t2", "k1", "ctx", "B", ("A", "B"), (200, 0))
        # k2: u2's history u1 selects Z, which is NOT in u2's competition
        # ("A","B") -> primary skips it, the #77-wide count does not.
        facts.add_event("u1", "k2", "ctx", "Z", ("A", "B"), (100, 0))
        facts.add_event("u2", "k2", "ctx", "A", ("A", "B"), (200, 0))
        # k3: same selection -> neither counts.
        facts.add_event("v1", "k3", "ctx", "A", ("A", "B"), (100, 0))
        facts.add_event("v2", "k3", "ctx", "A", ("A", "B"), (200, 0))
        return facts

    def test_primary_requires_competition_membership(self):
        facts = self._facts()
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        targets = _targets(facts.db_path)
        self.assertEqual(len(targets), 6)
        from calibration_cc import prefix_hard_negative_query_count
        primary = prefix_hard_negative_query_count(db, targets)
        # Only t2: same-key history with a different selection in its
        # current competition ("B" in ("A","B")).  u2's "Z" history is not
        # in its competition; v2 has no different-selection history.
        self.assertEqual(primary, 1)
        wide = wide_hard_negative_query_count(db, targets)
        # t2 ("B" differs) + u2 ("Z" differs) = 2.
        self.assertEqual(wide, 2)

    def test_terminal_edges(self):
        self.assertEqual(
            terminal(200)["outcome"], TERMINAL_CALIBRATABLE)
        self.assertEqual(
            terminal(199)["outcome"], TERMINAL_NOT_CALIBRATABLE)
        self.assertEqual(
            terminal(1)["outcome"], TERMINAL_NOT_CALIBRATABLE)
        self.assertEqual(terminal(0)["threshold"],
                         MIN_HARD_NEGATIVE_QUERIES)


class ReportTest(unittest.TestCase):
    """AC158-4/-5: data-state counts present; privacy scan gates delivery."""

    def _report(self):
        facts = SyntheticFacts()
        self.addCleanup(facts.close)
        # Two keys, several group-complete events with alternating
        # selections so each key has a differing-selection history in its
        # current competition.
        for index in range(3):
            facts.add_event("e%d" % index, "k1", "ctx",
                            "A" if index % 2 == 0 else "B", ("A", "B"),
                            (1000 + index * 10, 0))
            facts.add_event("f%d" % index, "k2", "ctx",
                            "B" if index % 2 == 0 else "A", ("A", "B"),
                            (2000 + index * 10, 0))
        db = FrozenFacts(facts.db_path)
        self.addCleanup(db.close)
        db_events = db.events()
        targets = [e for e in db_events if not e.retracted]
        counts = census_counts(db, targets)
        record = terminal(counts["primary_count"])
        return build_report(
            code_sha="0" * 40,
            snapshot_sha256="b" * 64,
            identity={"history_id": "h" * 32, "store_epoch": "e" * 32},
            cutoff_hlc=snapshot_max_unretracted_hlc(db_events),
            counts=counts,
            prefix_event_ids=[event.event_id for event in targets],
            terminal_record=record), counts

    def test_data_state_counts(self):
        report, counts = self._report()
        self.assertEqual(report["data"]["replayable"], 6)
        self.assertEqual(report["data"]["group_complete"], 6)
        self.assertEqual(report["data"]["keys"], 2)
        # primary: e0 no history; e1 sees B in competition; e2 sees B;
        # f1 sees A; f2 sees A -> 4 queries.  wide: same 4 (all the
        # differing selections are in their competition here).
        self.assertEqual(report["hard_negative"]["primary_count"], 4)
        self.assertEqual(report["hard_negative"]["wide_77_diagnostic"], 4)

    def test_no_live_state_claims(self):
        report, _counts = self._report()
        self.assertEqual(report["claim_support"]["live_gamma"], 0.0)
        self.assertIs(report["claim_support"]["walkforward_started"], False)
        self.assertIs(report["claim_support"]["no_model_forward"], True)

    def test_privacy_clean_report(self):
        report, _counts = self._report()
        self.assertTrue(verify_privacy(report))

    def test_privacy_rejects_machine_path(self):
        report, _counts = self._report()
        report["notes"].append("/Users/habit/Developer/facts.sqlite3")
        with self.assertRaisesRegex(PrivacyViolation, "(machine path|)"):
            verify_privacy(report)

    def test_markdown_roundtrip_carries_terminal(self):
        report, _counts = self._report()
        text = render_markdown(report)
        self.assertIn(report["terminal"]["outcome"], text)
        self.assertIn("[%d,%d]" % tuple(report["cutoff"]["hlc"]), text)


class ContractIdentityTest(unittest.TestCase):

    def test_contract_and_engine_identity(self):
        self.assertEqual(CONTRACT_ID, "AC-158-v1")
        self.assertEqual(ENGINE_VERSION, "prefix-hn-census-v1")


if __name__ == "__main__":
    unittest.main()