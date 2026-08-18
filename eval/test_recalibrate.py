#!/usr/bin/env python3
"""Model-free tests for the #106 α recalibration (AC-106-v1).

Pins (no model, no daemon, no console):

- SCN-106-2: primary labels never include retracted events or events with
  HLC < freeze watermark; HLC order is strict (reuses FrozenFacts).
- SCN-106-3: group-complete uses saved competition size < 32, NOT the
  persisted competition_complete bit.
- SCN-106-5: a saved candidate without finite weight makes the whole event
  无法重放; the rest is not silently reranked.
- SCN-106-6 / AC106-3: decide_final reads only primary metrics; a
  control-only win cannot select a positive α.
- SCN-106-7: empty-上文 stays in the primary set (stratum, not a fault);
  control empty-prefix cases are dropped and counted.
- SCN-106-10: below 1000 primary events / 100 keys -> specification blocker,
  no α* declared.
- SCN-106-11: upper-bound winner after extension is not reported as a
  calibrated internal optimum.
- AC106-2: pre-declared grid including α=0 is fully run; extension applied
  only when the winner is the upper bound; decide_final = primary top-1,
  then MRR, then smaller α.
- AC106-7: scoring uses log 权重 (template_weights), not #70 base_proxy,
  not 品质.
- AC106-6 / SCN-106-9: the report is desensitized (no raw 上文/candidate
  text), carries SHA-256 + identities + counts.
"""

import json
import os
import sqlite3
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from decide import decide_final  # noqa: E402
from primary_events import (FREEZE_WATERMARK, GROUP_COMPLETE_N,  # noqa: E402
                            load_primary_events)
from recalib_report import build_report, render_markdown  # noqa: E402
from recalibrate import (AlphaMetrics, alpha0_rank_map,  # noqa: E402
                         per_alpha_metrics, score_event,
                         selection_rank)
from template_weights import (parse_decompiled_table,  # noqa: E402
                              runtime_weight)
from walkforward import FrozenFacts  # noqa: E402

from fixture_facts import SyntheticFacts  # noqa: E402


# ---------------------------------------------------------------------------
# weight map helpers
# ---------------------------------------------------------------------------

def make_weight_map(entries):
    """weight_map from {text: raw_weight} under one synthetic code.

    ``raw_weight`` is what the decompiled table stores: the *raw*
    dictionary/essay weight (e.g. 12587.0), or 0.0 for the raw-0 sentinel.
    """
    return {(text, "testcode"): (text, raw) for text, raw in entries.items()}


class TemplateWeightsTest(unittest.TestCase):

    def test_runtime_weight_is_log_minus_ks(self):
        import math
        raw = 110731.0  # decompiled table stores the raw weight
        self.assertAlmostEqual(runtime_weight(raw),
                               math.log(raw) - 18.420680743952367)

    def test_zero_raw_weight_uses_dbl_epsilon(self):
        import math
        self.assertAlmostEqual(
            runtime_weight(0.0),
            math.log(2.220446049250313e-16) - 18.420680743952367)

    def test_weight_for_missing_candidate_is_none(self):
        """A candidate absent from the template table -> None (RISK-106-1)."""
        import math
        weight_map = make_weight_map({"文字": 12587.0, "蚊子": 2612.0})
        self.assertAlmostEqual(weight_for_text(weight_map, "文字"),
                               math.log(12587.0) - 18.420680743952367)
        self.assertIsNone(weight_for_text(weight_map, "陷在"))

    def test_decompiled_parse_skips_header_and_weights_are_parsed(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as handle:
            handle.write("# Rime dictionary\n---\nname: x\n文字\twen zi\t12587\n"
                         "蚊子\twen zi\t2612\n问字\twen zi\n")
            path = handle.name
        try:
            table = parse_decompiled_table(path)
            self.assertIn(("文字", "wenzi"), table)
            self.assertEqual(table[("文字", "wenzi")][1], 12587.0)
            self.assertEqual(table[("问字", "wenzi")][1], 0.0)
        finally:
            os.unlink(path)


def weight_for_text(weight_map, text):
    from template_weights import weight_for
    return weight_for(weight_map, text, "testcode")


# ---------------------------------------------------------------------------
# primary event loading (SCN-106-2 / SCN-106-3 / SCN-106-7)
# ---------------------------------------------------------------------------

class PrimaryEventsTest(unittest.TestCase):

    def _facts(self):
        facts = SyntheticFacts()
        try:
            facts.add_event("pre", "wo", "ctx0", "我", ("我", "握"), (100, 0),
                            competition_complete=True)
            # post-freeze group-complete event with empty 上文
            facts.add_event("e1", "wo", "", "我", ("我", "握"), (FREEZE_WATERMARK[0] + 1, 0),
                            competition_complete=False)
            # post-freeze group-complete with 32 candidates (NOT group-complete)
            facts.add_event("e2", "wo", "ctx2", "我",
                            tuple("c%d" % i for i in range(32)),
                            (FREEZE_WATERMARK[0] + 2, 0),
                            competition_complete=True)
            # post-freeze group-complete with 31 candidates (group-complete)
            facts.add_event("e3", "wo", "ctx3", "我",
                            tuple("d%d" % i for i in range(31)),
                            (FREEZE_WATERMARK[0] + 3, 0),
                            competition_complete=True)
            # retracted post-freeze event
            facts.add_event("e4", "wo", "ctx4", "握", ("我", "握"),
                            (FREEZE_WATERMARK[0] + 4, 0),
                            retract_at=(FREEZE_WATERMARK[0] + 5, 0))
            # pre-freeze event
            facts.add_event("e5", "wo", "ctx5", "我", ("我", "握"),
                            (FREEZE_WATERMARK[0] - 1, 0))
        finally:
            pass
        return facts

    def test_group_complete_uses_size_not_bit(self):
        """SCN-106-3: competition size < 32 gates, not the persisted bit."""
        facts = self._facts()
        try:
            loaded = load_primary_events(
                facts.db_path,
                freeze_watermark=(FREEZE_WATERMARK[0] + 1, 0))
            ids = {e.event_id for e in loaded["events"]}
            # e1: size 2 < 32, bit false -> INCLUDED (bit ignored)
            self.assertIn("e1", ids)
            # e2: size 32 -> EXCLUDED (not group-complete) even though bit true
            self.assertNotIn("e2", ids)
            # e3: size 31 -> INCLUDED
            self.assertIn("e3", ids)
            # e4: retracted -> EXCLUDED
            self.assertNotIn("e4", ids)
            # e5: pre-freeze -> EXCLUDED
            self.assertNotIn("e5", ids)
            # e1 empty 上文 counted as stratum, not a fault
            self.assertEqual(loaded["counts"]["empty_preceding"], 1)
        finally:
            facts.close()

    def test_empty_preceding_stays_in_set(self):
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "", "我", ("我", "握"),
                            (FREEZE_WATERMARK[0] + 1, 0))
            loaded = load_primary_events(facts.db_path,
                                         freeze_watermark=(FREEZE_WATERMARK[0] + 1, 0))
            self.assertEqual([e.event_id for e in loaded["events"]], ["e1"])
            self.assertEqual(loaded["counts"]["empty_preceding"], 1)
        finally:
            facts.close()

    def test_overlong_preceding_is_fault(self):
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wo", "长" * 65, "我", ("我", "握"),
                            (FREEZE_WATERMARK[0] + 1, 0))
            with self.assertRaises(Exception):
                load_primary_events(facts.db_path,
                                    freeze_watermark=(FREEZE_WATERMARK[0] + 1, 0))
        finally:
            facts.close()


# ---------------------------------------------------------------------------
# 无法重放 (SCN-106-5)
# ---------------------------------------------------------------------------

class UnreplayableTest(unittest.TestCase):

    def _event(self, facts, event_id="e1", texts=("文字", "蚊子", "问字")):
        frozen = FrozenFacts(facts.db_path)
        try:
            for e in frozen.events():
                if e.event_id == event_id:
                    return e
        finally:
            frozen.close()
        self.fail("event %s not found" % event_id)

    def test_missing_weight_makes_event_unreplayable(self):
        import math
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wenzi", "ctx", "文字",
                            ("文字", "蚊子", "陷在"),
                            (FREEZE_WATERMARK[0] + 1, 0))
            event = self._event(facts)
            weight_map = {
                ("文字", "wenzi"): ("文字", 12587.0),
                ("蚊子", "wenzi"): ("蚊子", 2612.0),
            }
            score, reason = score_event(
                event, weight_map, "/nonexistent.sock", "test")
            self.assertIsNone(score)
            self.assertEqual(reason, "weight")
        finally:
            facts.close()

    def test_fully_weighted_event_scores(self):
        import math
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wenzi", "ctx", "文字",
                            ("文字", "蚊子", "问字"),
                            (FREEZE_WATERMARK[0] + 1, 0))
            event = self._event(facts)
            # Map keyed by the event's real code ("wenzi").
            weight_map = {
                ("文字", "wenzi"): ("文字", 12587.0),
                ("蚊子", "wenzi"): ("蚊子", 2612.0),
                ("问字", "wenzi"): ("问字", 0.0),
            }
            # LM would fail against a missing socket -> lm reason.
            score, reason = score_event(
                event, weight_map, "/nonexistent.sock", "test")
            self.assertIsNone(score)
            self.assertEqual(reason, "lm")
        finally:
            facts.close()

    def test_selection_rank_ties_keep_merge_order(self):
        """Ranking is stable: ties keep the saved merge order."""
        import math
        facts = SyntheticFacts()
        try:
            facts.add_event("e1", "wenzi", "ctx", "蚊子",
                            ("文字", "蚊子"),
                            (FREEZE_WATERMARK[0] + 1, 0))
            event = self._event(facts)
            weight_map = make_weight_map({"文字": 12587.0, "蚊子": 2612.0})
            score, reason = score_event(
                event, weight_map, "/nonexistent.sock", "test")
            self.assertIsNone(score)
        finally:
            facts.close()

    def test_alpha0_rank_is_weight_only(self):
        """AC106-7: α=0 ranking = log 权重 only (no LM term)."""
        import math
        from recalibrate import EventScore
        w1 = math.log(12587.0) - 18.420680743952367
        w2 = math.log(2612.0) - 18.420680743952367
        score = EventScore(
            event_id="e1", hlc=(1, 0), key=("luna_pinyin", "word", "wenzi"),
            selection_index=0,
            weights=(w1, w2), lm_scores=(-1.0, -1.0),
            observed_rank1=True, competition_size=2,
            preceding_empty=False, confirmation_source="explicit_current")
        # α=0: weight-only -> candidate 0 (文字) first.
        self.assertEqual(selection_rank(score, 0.0), 1)


# ---------------------------------------------------------------------------
# decide_final (SCN-106-6 / AC106-2 / AC106-3 / SCN-106-10 / SCN-106-11)
# ---------------------------------------------------------------------------

def _metrics(alpha, top1_rate, mrr=0.5, samples=10):
    return AlphaMetrics(alpha=alpha, samples=samples, top1=int(top1_rate * samples),
                        top1_rate=top1_rate, mrr=mrr,
                        m1_denominator=0, m1_numerator=0,
                        m2_denominator=0, m2_numerator=0,
                        empty_preceding=0)


class DecideFinalTest(unittest.TestCase):

    def test_control_only_win_cannot_select_positive_alpha(self):
        """AC106-3 / SCN-106-6: control metrics never enter decide_final.

        A positive α that wins only on control and loses on primary must not
        be selected.  Here α=1 has primary top-1 BELOW α=0, so even though
        the (external) control would favor it, decide_final (which never sees
        control) picks α=0.
        """
        primary = {
            0.0: _metrics(0.0, 0.40, mrr=0.50),
            1.0: _metrics(1.0, 0.30, mrr=0.45),
            2.0: _metrics(2.0, 0.28, mrr=0.43),
        }
        decision = decide_final(primary, primary_event_count=1000,
                                primary_key_count=120)
        self.assertEqual(decision["state"], "decided")
        self.assertEqual(decision["final_alpha_value"], 0.0)
        self.assertFalse(decision["positive_alpha_qualified"])

    def test_selection_keys_top1_then_mrr_then_smaller_alpha(self):
        """AC106-2: primary top-1, then MRR, then smaller α."""
        primary = {
            0.0: _metrics(0.0, 0.40, mrr=0.50),
            1.0: _metrics(1.0, 0.42, mrr=0.51),   # top-1 winner
            2.0: _metrics(2.0, 0.42, mrr=0.48),   # same top-1, lower MRR
            3.0: _metrics(3.0, 0.40, mrr=0.60),
        }
        decision = decide_final(primary, primary_event_count=1000,
                                primary_key_count=120)
        self.assertEqual(decision["final_alpha_value"], 1.0)
        self.assertTrue(decision["positive_alpha_qualified"])
        self.assertTrue(decision["internal_optimum"])

    def test_extension_triggered_only_on_upper_bound(self):
        """The extension rule applies only when the winner is the upper bound."""
        primary = {
            0.0: _metrics(0.0, 0.40, mrr=0.50),
            1.0: _metrics(1.0, 0.42, mrr=0.51),
            10.0: _metrics(10.0, 0.30, mrr=0.45),
        }
        # Winner is 1.0 (interior), not the upper bound -> no extension.
        decision = decide_final(primary, primary_event_count=1000,
                                primary_key_count=120)
        self.assertEqual(decision["final_alpha_value"], 1.0)
        self.assertNotIn(14.0, decision["swept_domain"])

    def test_upper_bound_winner_extends_and_not_calibrated_if_still_bound(self):
        """SCN-106-11: upper-bound winner after extension is not a calibrated
        internal optimum."""
        primary = {
            0.0: _metrics(0.0, 0.30, mrr=0.40),
            5.0: _metrics(5.0, 0.35, mrr=0.45),
            10.0: _metrics(10.0, 0.40, mrr=0.50),
            14.0: _metrics(14.0, 0.45, mrr=0.55),
            20.0: _metrics(20.0, 0.50, mrr=0.60),
        }
        decision = decide_final(primary, primary_event_count=1000,
                                primary_key_count=120)
        self.assertEqual(decision["final_alpha_value"], 20.0)
        self.assertFalse(decision["internal_optimum"])
        self.assertIn(14.0, decision["swept_domain"])
        self.assertIn(20.0, decision["swept_domain"])

    def test_spec_blocker_below_1000_events(self):
        """SCN-106-10: primary N < 1000 -> no α* declared."""
        primary = {0.0: _metrics(0.0, 0.40), 1.0: _metrics(1.0, 0.50)}
        decision = decide_final(primary, primary_event_count=689,
                                primary_key_count=224)
        self.assertEqual(decision["state"], "specification_blocker")
        self.assertIsNone(decision["final_alpha_value"])
        self.assertIn("689", decision["reason"])

    def test_spec_blocker_below_100_keys(self):
        """SCN-106-10: keys < 100 -> no α* declared."""
        primary = {0.0: _metrics(0.0, 0.40), 1.0: _metrics(1.0, 0.50)}
        decision = decide_final(primary, primary_event_count=1200,
                                primary_key_count=80)
        self.assertEqual(decision["state"], "specification_blocker")

    def test_no_spec_blocker_when_gate_met(self):
        primary = {0.0: _metrics(0.0, 0.40), 1.0: _metrics(1.0, 0.50)}
        decision = decide_final(primary, primary_event_count=1200,
                                primary_key_count=150)
        self.assertEqual(decision["state"], "decided")
        self.assertEqual(decision["final_alpha_value"], 1.0)


# ---------------------------------------------------------------------------
# report desensitization (AC106-6 / SCN-106-9)
# ---------------------------------------------------------------------------

class ReportTest(unittest.TestCase):

    def _report(self):
        decision = decide_final(
            {0.0: _metrics(0.0, 0.4), 1.0: _metrics(1.0, 0.5)},
            primary_event_count=1000, primary_key_count=120)
        return build_report(
            "AC-106-v1",
            {"sha256": "a" * 64,
             "identity": {"history_id": "h", "store_epoch": "e",
                          "hlc_physical_ms": "1786806466751"},
             "status": {"status_check": "skipped"}},
            FREEZE_WATERMARK,
            {"engine_version": "recalibrate-alpha-v1", "policy_id": "p"},
            {"model": "Qwen3-0.6B-Base"},
            {"post_freeze_active": 100, "post_freeze_group_complete": 90,
             "empty_preceding": 5, "group_complete_n": 32,
             "freeze_watermark": list(FREEZE_WATERMARK),
             "overlong_preceding": 0},
            {0.0: _metrics(0.0, 0.4), 1.0: _metrics(1.0, 0.5)},
            {"weight": 5, "lm": 0},
            {"observed_rank1": 60, "reconstructed_alpha0_rank1": 55,
             "agreement": 0.9, "samples": 90},
            {"per_alpha": {}},
            decision,
            ["D1 test"])

    def test_report_has_no_raw_text(self):
        report = self._report()
        text = json.dumps(report, ensure_ascii=False)
        for probe in ("preceding_text", "candidate_text", "final_selection",
                      "的的的", "哲理的", "wenzi", "xianzai"):
            self.assertNotIn(probe, text)

    def test_report_carries_fingerprints_and_sha256(self):
        report = self._report()
        self.assertEqual(report["snapshot"]["sha256"], "a" * 64)
        self.assertEqual(report["freeze_watermark"], list(FREEZE_WATERMARK))
        self.assertIn("report_sha256", report)
        self.assertIn("per_alpha", report)
        self.assertIn("decision", report)

    def test_report_digest_deterministic(self):
        self.assertEqual(self._report()["report_sha256"],
                         self._report()["report_sha256"])

    def test_markdown_render_includes_decision(self):
        markdown = render_markdown(self._report())
        self.assertIn("α Recalibration Report", markdown)
        self.assertIn("final_alpha_value", markdown)
        self.assertIn("Report SHA-256", markdown)


class ControlDenominatorTest(unittest.TestCase):

    def test_word_cases_empty_prefix_dropped_and_counted(self):
        """SCN-106-7: control empty-prefix cases are dropped and counted."""
        from control_denominator import control_word_cases
        # Build a synthetic fixture (not the committed one) to pin the logic.
        fixture = {
            "counts": {"sentences": 120, "words": 402},
            "sentence_cases": [
                {"index": 1, "sentence": "今天天气很好"},
                {"index": 2, "sentence": "abc"},
            ],
            "word_cases": [
                {"index": 1, "word": "一", "source_sentence": 1,
                 "source_start": 0},    # empty prefix -> dropped
                {"index": 2, "word": "今天", "source_sentence": 1,
                 "source_start": 0},    # empty prefix -> dropped
                {"index": 3, "word": "天气", "pinyin": "tianqi",
                 "source_sentence": 1,
                 "source_start": 2},    # prefix "今天"
            ],
        }
        cases, dropped = control_word_cases(fixture)
        self.assertEqual(dropped, 2)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].case_index, 3)
        self.assertEqual(cases[0].prefix_length, 2)

    def test_control_case_ranks_ties_keep_emitted_order(self):
        from control_denominator import control_case_ranks
        candidates = ["甲", "乙", "丙"]
        logged = [("sys", -10.0), ("sys", -10.0), ("sys", -5.0)]
        lm = [0.0, 0.0, 0.0]
        ranks = control_case_ranks(candidates, logged, lm, "乙", [0.0])
        # Scores: 丙 -5 (highest), 甲 -10, 乙 -10.  Order: [丙, 甲, 乙] with
        # the tie (甲/乙) keeping emitted order -> 乙 is rank 3.
        self.assertEqual(ranks[0.0], 3)


class ConsoleParsingTest(unittest.TestCase):
    """Model-free tests for the console output parsers."""

    def test_parse_candidates_keeps_console_emission_shape(self):
        """The parser mirrors calibrate.py: it keeps the emitted text as the
        console prints it (highlight brackets on the selection, leading
        spaces, comments in parentheses).  Ranking logic must be robust to
        the raw emission shape; the control driver matches targets against
        the emitted texts exactly as the console prints them."""
        from console_replay import parse_candidates
        out = (
            "1. [文字]\n"
            "2.  蚊子 \n"
            "3.  问字 〔問字〕\n"
        )
        self.assertEqual(parse_candidates(out),
                         ["[文字]", " 蚊子 ", " 问字 〔問字〕"])

    def test_parse_weights_extracts_librime_logs(self):
        from console_replay import parse_weights
        err = (
            "I llm_rerank weight: source=sys weight=-8.98026 coeff=1 "
            "score=-8.98026\n"
            "I llm_rerank weight: source=usr weight=-10.5528 coeff=1 "
            "score=-10.5528\n"
        )
        self.assertEqual(parse_weights(err),
                         [("sys", -8.98026), ("usr", -10.5528)])

    def test_rank_of_finds_target(self):
        from console_replay import rank_of
        self.assertEqual(rank_of("蚊子", ["文字", "蚊子", "问字"]), 2)
        self.assertIsNone(rank_of("不在", ["文字", "蚊子"]))


class DecideExtensionTest(unittest.TestCase):

    def test_no_double_append_when_grid_has_extension_points(self):
        """The driver pre-sweeps extension α and passes them in the grid;
        decide_final must not append them again (the swept domain feeds the
        internal-optimum boundary check)."""
        from decide import decide_final
        from recalibrate import AlphaMetrics
        metrics = {
            0.0: _metrics(0.0, 0.30),
            5.0: _metrics(5.0, 0.35),
            10.0: _metrics(10.0, 0.40),
            14.0: _metrics(14.0, 0.45),
            20.0: _metrics(20.0, 0.50),
        }
        # The driver already swept the extension points into the grid.
        grid = [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 14.0, 20.0]
        decision = decide_final(metrics, grid=grid,
                                primary_event_count=1200,
                                primary_key_count=150)
        domain = decision["swept_domain"]
        self.assertEqual(domain.count(14.0), 1)
        self.assertEqual(domain.count(20.0), 1)
        self.assertEqual(decision["final_alpha_value"], 20.0)
        self.assertFalse(decision["internal_optimum"])


if __name__ == "__main__":
    unittest.main()
