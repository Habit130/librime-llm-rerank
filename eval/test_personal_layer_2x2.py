#!/usr/bin/env python3
"""Model-free tests for the personal-layer 2x2 (Squirrel #155 / AC-155-v1).

Proves the complete-key 2x2 extraction, the two frozen routes, the r knife
and the four-state cross-route synthesis from synthetic snapshots with
injected vectors — no model, no transformers, no MLX.
"""

import json
import math
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from personal_layer_2x2 import (  # noqa: E402
    CONTRACT_ID,
    CROSS_ANY_GREY,
    CROSS_DUAL_DOMINANT,
    CROSS_DUAL_SIGNAL,
    CROSS_SPLIT,
    FALLBACK_PIN_SHA256,
    HLC_MAX_INCLUSIVE,
    HLC_MIN,
    KNIFE_DOMINANT,
    KNIFE_GREY,
    KNIFE_NO_CONCLUSION,
    KNIFE_SIGNAL,
    MIN_COMPLETE_KEYS,
    NO_CONCLUSION,
    PRIMARY_PIN_SHA256,
    ROUTE_IDS,
    Personal2x2Error,
    apply_preflight,
    apply_scores,
    base_and_partner,
    build_freeze,
    classify_keys,
    cross_route_summary,
    freeze_path,
    group_keys,
    key_sha256,
    key_statistics,
    knife_for,
    load_freeze,
    load_prefix_snapshot,
    route_summary,
    write_freeze,
    write_report,
    verify_snapshot_sha256,
)

SCHEMA = "luna_pinyin"
CATEGORY = "word"
MINI_HLC = ((1000, 0), (2000, 0))


def make_event(event_id, key_input, preceding, selected, hlc=None,
               candidates=None, category=CATEGORY, schema_id=SCHEMA):
    return {
        "event_id": event_id,
        "schema_id": schema_id,
        "category": category,
        "canonical_segment_input": key_input,
        "hlc": hlc if hlc is not None else (1500, 0),
        "preceding": preceding,
        "final_selection_text": selected,
        "candidates": candidates if candidates is not None
        else [selected],
    }


def build_snapshot(events, retracted=(), path=None):
    """Synthetic fact store with the subset of columns the loader reads."""
    target = path if path is not None \
        else tempfile.mkstemp(suffix=".sqlite3")[1]
    conn = sqlite3.connect(target)
    try:
        conn.executescript("""
            CREATE TABLE commits (
                commit_id TEXT PRIMARY KEY, utc_committed_at_ms INTEGER);
            CREATE TABLE selection_events (
                event_id TEXT PRIMARY KEY, commit_id TEXT,
                event_format_version INTEGER, schema_id TEXT,
                canonical_segment_input TEXT, span_start INTEGER,
                span_end INTEGER, category TEXT, preceding_text TEXT,
                competition_complete INTEGER, final_selection_text TEXT,
                confirmation_source TEXT, trigger_keycode INTEGER,
                display_rank INTEGER, display_page INTEGER,
                session_id TEXT, session_seq INTEGER,
                hlc_physical_ms INTEGER, hlc_logical INTEGER,
                utc_confirmed_at_ms INTEGER, utc_committed_at_ms INTEGER);
            CREATE TABLE selection_candidates (
                event_id TEXT NOT NULL, merge_order INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (event_id, merge_order));
            CREATE TABLE retractions (
                retraction_id TEXT PRIMARY KEY, commit_id TEXT,
                hlc_physical_ms INTEGER, hlc_logical INTEGER,
                utc_retracted_at_ms INTEGER);
            CREATE VIEW active_events AS
                SELECT e.event_id FROM selection_events e
                WHERE NOT EXISTS (
                    SELECT 1 FROM retractions r
                    WHERE r.commit_id = e.commit_id);
        """)
        for index, event in enumerate(events):
            physical, logical = event["hlc"]
            conn.execute(
                "INSERT INTO commits (commit_id, utc_committed_at_ms)"
                " VALUES (?, ?)", ("commit-%d" % index, physical))
            conn.execute(
                "INSERT INTO selection_events (event_id, commit_id,"
                " event_format_version, schema_id, canonical_segment_input,"
                " span_start, span_end, category, preceding_text,"
                " competition_complete, final_selection_text,"
                " confirmation_source, trigger_keycode, display_rank,"
                " display_page, session_id, session_seq,"
                " hlc_physical_ms, hlc_logical, utc_confirmed_at_ms,"
                " utc_committed_at_ms) VALUES (?, ?, 1, ?, ?, 0, 1, ?, ?, 0,"
                " ?, 'typed', NULL, 0, 0, 'sess', 0, ?, ?, ?, ?)",
                (event["event_id"], "commit-%d" % index,
                 event["schema_id"], event["canonical_segment_input"],
                 event["category"], event["preceding"],
                 event["final_selection_text"],
                 physical, logical, physical, physical))
            for order, text in enumerate(event["candidates"]):
                conn.execute(
                    "INSERT INTO selection_candidates"
                    " (event_id, merge_order, text) VALUES (?, ?, ?)",
                    (event["event_id"], order, text))
        for index, event in enumerate(events):
            if event["event_id"] not in retracted:
                continue
            conn.execute(
                "INSERT INTO retractions (retraction_id, commit_id,"
                " hlc_physical_ms, hlc_logical, utc_retracted_at_ms)"
                " VALUES (?, ?, ?, 0, ?)",
                ("retr-%s" % event["event_id"],
                 "commit-%d" % index, event["hlc"][0], event["hlc"][0]))
        conn.commit()
    finally:
        conn.close()
    return target


KEY = ("luna_pinyin", "word")


def loaded_events(events, hlc_min=(1000, 0), hlc_max=(10000, 0)):
    """Loader-produced PrefixEvents (sorted per key) from synthetic events."""
    with tempfile.TemporaryDirectory() as tmp:
        path = build_snapshot(events, path=Path(tmp) / "facts.sqlite3")
        loaded = load_prefix_snapshot(path, hlc_min=hlc_min,
                                      hlc_max_inclusive=hlc_max)
    groups = group_keys(loaded)
    return {key: groups[key] for key in groups}


def key_group(events, canonical_input, hlc_min=(1000, 0),
              hlc_max=(10000, 0)):
    groups = loaded_events(events, hlc_min, hlc_max)
    return groups[(KEY[0], KEY[1], canonical_input)]


class ContractTest(unittest.TestCase):
    def test_contract_is_ac155_v1(self):
        self.assertEqual(CONTRACT_ID, "AC-155-v1")

    def test_exactly_two_routes(self):
        self.assertEqual(ROUTE_IDS, (
            "dedicated_qwen3_embedding_0_6b",
            "qwen_l28_candidate_span_mean",
        ))

    def test_pins_match_a_77_prefix(self):
        self.assertEqual(len(PRIMARY_PIN_SHA256), 64)
        self.assertEqual(len(FALLBACK_PIN_SHA256), 64)
        self.assertEqual(HLC_MIN, (1786806466751, 0))
        self.assertEqual(HLC_MAX_INCLUSIVE, (1787065441087, 0))

    def test_complete_key_threshold_30(self):
        self.assertEqual(MIN_COMPLETE_KEYS, 30)


class SnapshotLoadTest(unittest.TestCase):
    def test_loads_only_active_events(self):
        events = [
            make_event("e1", "a", "上文一", "词一", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "上文二", "词一", (1200, 0),
                       ["词一"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_snapshot(events, retracted=("e1",), path=Path(tmp)
                                  / "facts.sqlite3")
            loaded = load_prefix_snapshot(path, hlc_min=(1000, 0),
                                          hlc_max_inclusive=(2000, 0))
        self.assertEqual([event.event_id for event in loaded], ["e2"])

    def test_snapshot_accepted_pins(self):
        events = [make_event("e1", "a", "上文", "词", (1500, 0),
                             ["词", "词二"])]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_snapshot(events, path=Path(tmp) / "facts.sqlite3")
            with self.assertRaises(Personal2x2Error):
                verify_snapshot_sha256(
                    path, "0" * 64, file_text="snapshot")

    def test_events_outside_prefix_window_fail(self):
        events = [make_event("e1", "a", "上文", "词", (3000, 0),
                             ["词", "词二"])]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_snapshot(events, path=Path(tmp) / "facts.sqlite3")
            with self.assertRaises(Personal2x2Error):
                load_prefix_snapshot(path, hlc_min=(1000, 0),
                                     hlc_max_inclusive=(2000, 0))

    def test_missing_snapshot_fails(self):
        with self.assertRaises(Personal2x2Error):
            load_prefix_snapshot("/no/such/snapshot.sqlite3")

    def test_event_without_competition_set_fails(self):
        events = [make_event("e1", "a", "上文", "词", (1500, 0),
                             ["词", "词二"])]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_snapshot(events, path=Path(tmp) / "facts.sqlite3")
            conn = sqlite3.connect(path)
            conn.execute("DELETE FROM selection_candidates")
            conn.commit()
            conn.close()
            with self.assertRaises(Personal2x2Error):
                load_prefix_snapshot(path, hlc_min=(1000, 0),
                                     hlc_max_inclusive=(2000, 0))


class CompleteKeyTest(unittest.TestCase):
    def test_base_is_earliest_with_unselected_candidate(self):
        events = [
            make_event("early", "a", "上文一", "词一", (1100, 0), ["词一"]),
            make_event("mid", "a", "上文二", "词一", (1200, 0),
                       ["词一", "词二"]),
            make_event("late", "a", "上文三", "词一", (1300, 0),
                       ["词一", "词三"]),
        ]
        pair = base_and_partner(key_group(events, "a"))
        self.assertIsNotNone(pair)
        base, partner = pair
        self.assertEqual(base.event_id, "mid")
        self.assertEqual(partner.event_id, "early")

    def test_partner_requires_literally_different_window(self):
        events = [
            make_event("e1", "a", "同一上文", "词一", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "同一上文", "词二", (1200, 0),
                       ["词二", "词三"]),
        ]
        self.assertIsNone(base_and_partner(key_group(events, "a")))

    def test_partner_excludes_base_itself(self):
        events = [
            make_event("e1", "a", "上文一", "词一", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "上文一", "词一", (1200, 0),
                       ["词一"]),
        ]
        self.assertIsNone(base_and_partner(key_group(events, "a")))

    def test_unreplayable_event_cannot_be_base(self):
        events = [
            make_event("e1", "a", "上文一", "未在竞争集", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "上文二", "词一", (1200, 0),
                       ["词一", "词三"]),
        ]
        pair = base_and_partner(key_group(events, "a"))
        self.assertIsNotNone(pair)
        base, _partner = pair
        self.assertEqual(base.event_id, "e2")

    def test_classify_counts_complete_and_incomplete(self):
        events = [
            make_event("e1", "a", "上文一", "词一", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "上文二", "词一", (1200, 0),
                       ["词一", "词三"]),
            make_event("e3", "b", "上文一", "词一", (1100, 0), ["词一"]),
            make_event("e4", "b", "上文二", "词一", (1200, 0), ["词一"]),
            make_event("e5", "c", "上文一", "词一", (1100, 0), ["词一"]),
        ]
        groups = loaded_events(events)
        complete, reasons = classify_keys(groups)
        self.assertEqual(list(complete), [("luna_pinyin", "word", "a")])
        self.assertEqual(reasons, {"no_replayable_base": 2,
                                   "no_partner_window": 0})

    def test_retracted_event_is_excluded(self):
        events = [
            make_event("e1", "a", "上文一", "词一", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "上文二", "词一", (1200, 0),
                       ["词一", "词三"]),
            make_event("e3", "a", "上文三", "词一", (1300, 0),
                       ["词一", "词四"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_snapshot(events, retracted=("e2",),
                                  path=Path(tmp) / "facts.sqlite3")
            loaded = load_prefix_snapshot(path, hlc_min=(1000, 0),
                                          hlc_max_inclusive=(10000, 0))
        groups = group_keys(loaded)
        pair = base_and_partner(groups[("luna_pinyin", "word", "a")])
        base, partner = pair
        self.assertEqual(base.event_id, "e1")
        self.assertNotEqual(partner.event_id, "e2")

    def test_window_is_last64(self):
        events = [
            make_event("e1", "a", "前" * 100 + "尾甲", "词一", (1100, 0),
                       ["词一", "词二"]),
            make_event("e2", "a", "前" * 100 + "尾乙", "词一", (1200, 0),
                       ["词一", "词三"]),
        ]
        pair = base_and_partner(key_group(events, "a"))
        base, partner = pair
        self.assertEqual(len(base.window()), 64)
        self.assertEqual(len(partner.window()), 64)
        self.assertTrue(base.window().endswith("尾甲"))
        self.assertTrue(partner.window().endswith("尾乙"))

    def test_key_hash_is_stable_and_binds_the_key(self):
        key = ("luna_pinyin", "word", "xianzai")
        first = key_sha256(key)
        second = key_sha256(key)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(key_sha256(("luna_pinyin", "word", "nipeng")),
                            first)

    def test_preflight_drops_only_rejected_keys(self):
        rows = [
            {"key_sha256": "a" * 64, "ctx1": "x", "selected": "s",
             "ctx2": "y", "unselected": ["u"]},
            {"key_sha256": "b" * 64, "ctx1": "x", "selected": "s",
             "ctx2": "z", "unselected": ["w"]},
        ]
        kept, rejected = apply_preflight(rows, ["a" * 64])
        self.assertEqual(len(kept), 1)
        self.assertEqual(rejected, 1)
        self.assertEqual(kept[0]["key_sha256"], "b" * 64)
        kept, rejected = apply_preflight(rows, [])
        self.assertEqual(len(kept), 2)
        self.assertEqual(rejected, 0)

    def test_l28_pool_is_candidate_span_not_full_sequence(self):
        """Numerical proof that candidate-span mean differs from the
        full-sequence mean the AC-155-v1 repair prohibited."""
        from run_personal_layer_2x2 import _pool_candidate_bounds
        span = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        candidate = _pool_candidate_bounds(span, 1, 1)
        full = _pool_candidate_bounds(span, 0, len(span))
        self.assertEqual(candidate, (0.0, 1.0))
        self.assertNotEqual(candidate, full)

    def test_l28_worker_passes_attribution_bounds_to_pooler(self):
        """Source-structure guard: the L28 worker must hand the pooler the
        `start, count` from candidate_tokenization_for; discarding them
        (pooling the whole sequence) fails this test."""
        import inspect
        import run_personal_layer_2x2 as runner
        src = inspect.getsource(runner._score_mlx_route)
        self.assertIn("candidate_tokenization_for(", src)
        pool_call = [
            line.strip() for line in src.splitlines()
            if "_pool_candidate_bounds(" in line
        ]
        self.assertEqual(len(pool_call), 1)
        self.assertIn("start", pool_call[0])
        self.assertIn("count", pool_call[0])
        self.assertNotIn("len(", pool_call[0])


class PoolBoundsTest(unittest.TestCase):
    def test_bounds_pool_over_the_candidate_span_only(self):
        from run_personal_layer_2x2 import _pool_candidate_bounds
        span = [[1.0, 0.0], [0.3, 0.0], [0.0, 1.0], [0.0, 0.3]]
        pooled = _pool_candidate_bounds(span, 1, 2)
        mean = (0.15, 0.5)
        norm = (0.15 ** 2 + 0.5 ** 2) ** 0.5
        self.assertAlmostEqual(pooled[0], mean[0] / norm, places=9)
        self.assertAlmostEqual(pooled[1], mean[1] / norm, places=9)

    def test_bounds_pool_drops_outside_candidate_tokens(self):
        from run_personal_layer_2x2 import _pool_candidate_bounds
        span = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        self.assertEqual(_pool_candidate_bounds(span, 1, 1),
                         (0.0, 1.0))
        self.assertNotEqual(_pool_candidate_bounds(span, 1, 1),
                            _pool_candidate_bounds(span, 0, 3))


class KeyCellsTest(unittest.TestCase):
    def _encode(self, vectors):
        cache = {}

        def encode(ctx, selected):
            key = ctx + "|" + selected
            vec = cache.get(key)
            if vec is None:
                vec = vectors[key]
                cache[key] = vec
            return vec
        return encode

    def _pair(self, base_event, partner_event):
        events = [base_event, partner_event]
        return base_and_partner(key_group(events, base_event[
            "canonical_segment_input"]))

    def test_cells_follow_the_frozen_payload(self):
        pair = self._pair(
            make_event("base", "a", "上文甲", "选中", (1100, 0),
                       ["选中", "陪跑一", "陪跑二"]),
            make_event("partner", "a", "上文乙", "选中", (1200, 0),
                       ["选中", "其他"]))
        base, partner = pair
        enc = self._encode({
            "上文甲|选中": (1.0, 0.0, 0.0),
            "上文乙|选中": (0.6, 0.8, 0.0),
            "上文甲|陪跑一": (0.0, 1.0, 0.0),
            "上文甲|陪跑二": (0.0, 0.0, 1.0),
        })
        d_cand, d_ctx = key_statistics(base, partner, enc)
        self.assertAlmostEqual(d_ctx, 1.0 - 0.6, places=12)
        self.assertAlmostEqual(d_cand, 1.0, places=12)

    def test_d_cand_is_median_over_unselected(self):
        pair = self._pair(
            make_event("base", "a", "上文甲", "选中", (1100, 0),
                       ["选中", "近", "中", "远"]),
            make_event("partner", "a", "上文乙", "选中", (1200, 0),
                       ["选中", "其他"]))
        base, partner = pair
        enc = self._encode({
            "上文甲|选中": (1.0, 0.0),
            "上文乙|选中": (0.8, 0.6),
            "上文甲|近": (0.94, math.sqrt(1 - 0.94 ** 2)),
            "上文甲|中": (0.5, math.sqrt(1 - 0.5 ** 2)),
            "上文甲|远": (0.1, math.sqrt(1 - 0.1 ** 2)),
        })
        d_cand, _d_ctx = key_statistics(base, partner, enc)
        self.assertAlmostEqual(d_cand, 0.5, places=6)

    def test_selected_missing_from_partner_window_is_still_anchored(self):
        pair = self._pair(
            make_event("base", "a", "上文甲", "选中", (1100, 0),
                       ["选中", "陪跑"]),
            make_event("partner", "a", "上文乙", "异词", (1200, 0),
                       ["异词", "另一"]))
        base, partner = pair
        enc = self._encode({
            "上文甲|选中": (1.0, 0.0),
            "上文乙|选中": (0.0, 1.0),
            "上文甲|陪跑": (0.9, math.sqrt(1 - 0.81)),
        })
        d_cand, d_ctx = key_statistics(base, partner, enc)
        self.assertAlmostEqual(d_ctx, 1.0, places=12)
        self.assertAlmostEqual(d_cand, 1.0 - 0.9, places=6)

    def test_cell_d_ctx_between_different_selected_values_is_not_assumed(self):
        events = [
            make_event("base", "a", "上文甲", "选中", (1100, 0),
                       ["选中", "陪跑一"]),
            make_event("partner", "a", "上文乙", "选中", (1200, 0),
                       ["选中", "陪跑二"]),
        ]
        enc = self._encode({
            "上文甲|选中": (1.0, 0.0),
            "上文乙|选中": (0.0, 1.0),
            "上文甲|陪跑一": (0.5, math.sqrt(1 - 0.25)),
        })
        base, partner = base_and_partner(key_group(events, "a"))
        _d_cand, d_ctx = key_statistics(base, partner, enc)
        self.assertAlmostEqual(d_ctx, 1.0, places=12)


class KnifeAndSynthesisTest(unittest.TestCase):
    def test_knife_boundaries(self):
        self.assertEqual(knife_for(0.0), KNIFE_DOMINANT)
        self.assertEqual(knife_for(0.499), KNIFE_DOMINANT)
        self.assertEqual(knife_for(0.5), KNIFE_GREY)
        self.assertEqual(knife_for(0.75), KNIFE_GREY)
        self.assertEqual(knife_for(1.0), KNIFE_SIGNAL)
        self.assertEqual(knife_for(2.0), KNIFE_SIGNAL)

    def test_route_summary_medians_and_r(self):
        key_ds = [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]
        summary = route_summary(key_ds)
        self.assertAlmostEqual(summary["median_key_d_cand"], 0.3, places=12)
        self.assertAlmostEqual(summary["median_key_d_ctx"], 0.4, places=12)
        self.assertAlmostEqual(summary["r"], 0.75, places=12)
        self.assertEqual(summary["label"], KNIFE_GREY)

    def test_zero_context_median_is_no_conclusion(self):
        summary = route_summary([(0.3, 0.0), (0.5, 0.0)])
        self.assertEqual(summary["label"], KNIFE_NO_CONCLUSION)
        self.assertIsNone(summary["r"])

    def test_empty_keys_are_no_conclusion(self):
        summary = route_summary([])
        self.assertEqual(summary["label"], KNIFE_NO_CONCLUSION)

    def test_cross_route_dual_dominant(self):
        summary = cross_route_summary({ROUTE_IDS[0]: KNIFE_DOMINANT,
                                       ROUTE_IDS[1]: KNIFE_DOMINANT})
        self.assertEqual(summary, CROSS_DUAL_DOMINANT)

    def test_cross_route_dual_signal(self):
        summary = cross_route_summary({ROUTE_IDS[0]: KNIFE_SIGNAL,
                                       ROUTE_IDS[1]: KNIFE_SIGNAL})
        self.assertEqual(summary, CROSS_DUAL_SIGNAL)

    def test_cross_route_split(self):
        summary = cross_route_summary({ROUTE_IDS[0]: KNIFE_DOMINANT,
                                       ROUTE_IDS[1]: KNIFE_SIGNAL})
        self.assertEqual(summary, CROSS_SPLIT)

    def test_cross_route_any_grey(self):
        for label in (KNIFE_GREY, KNIFE_NO_CONCLUSION):
            summary = cross_route_summary({ROUTE_IDS[0]: label,
                                           ROUTE_IDS[1]: KNIFE_SIGNAL})
            self.assertEqual(summary, CROSS_ANY_GREY)

    def test_cross_route_rejects_wrong_route_set(self):
        with self.assertRaises(Personal2x2Error):
            cross_route_summary({ROUTE_IDS[0]: KNIFE_SIGNAL,
                                 "intruder": KNIFE_SIGNAL})


class FreezeReportTest(unittest.TestCase):
    def _fixture_events(self, count=MIN_COMPLETE_KEYS + 2):
        events = []
        for index in range(count):
            events.append(make_event(
                "b%02d" % index, "k%02d" % index, "上文甲%d" % index,
                "选中", (1100 + index * 2, 0),
                ["选中", "陪跑"]))
            events.append(make_event(
                "p%02d" % index, "k%02d" % index, "上文乙%d" % index,
                "选中", (1200 + index * 2, 0),
                ["选中", "另一"]))
        return events

    def _freeze(self, events, tmp):
        path = build_snapshot(events, path=Path(tmp) / "facts.sqlite3")
        loaded = load_prefix_snapshot(path, hlc_min=(1000, 0),
                                      hlc_max_inclusive=(10000, 0))
        groups = group_keys(loaded)
        complete, reasons = classify_keys(groups)
        freeze = build_freeze(
            snapshot_sha256=FALLBACK_PIN_SHA256,
            code_sha="a" * 40,
            complete_keys=sorted(key_sha256(key) for key in complete),
            complete_key_count=len(complete),
            incomplete_reasons=reasons,
        )
        return freeze, complete

    def _report(self, freeze, d_ctx_values=(0.2, 0.4)):
        """Per-route key_ds sized to the frozen complete-key count."""
        if freeze["complete_key_count"] == 0:
            per_route = {route_id: [] for route_id in ROUTE_IDS}
        else:
            per_route = {}
            for route_id in ROUTE_IDS:
                per_route[route_id] = []
                for index in range(freeze["complete_key_count"]):
                    d_ctx = d_ctx_values[index % len(d_ctx_values)]
                    per_route[route_id].append(
                        (0.1 + 0.2 * (index % 3), d_ctx))
        return apply_scores(freeze, freeze, per_route)

    def test_freeze_rejects_non_pin_snapshot(self):
        with self.assertRaises(Personal2x2Error):
            build_freeze(
                snapshot_sha256="f" * 64,
                code_sha="a" * 40,
                complete_keys=[],
                complete_key_count=0,
                incomplete_reasons={"no_replayable_base": 1},
            )

    def test_freeze_round_trip_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze, _complete = self._freeze(self._fixture_events(), tmp)
            artifact = Path(tmp) / "out"
            write_freeze(artifact, freeze)
            loaded = load_freeze(artifact)
            self.assertEqual(loaded, freeze)
            self.assertEqual(
                loaded["complete_key_count"], MIN_COMPLETE_KEYS + 2)
            self.assertEqual(len(loaded["complete_keys"]),
                             MIN_COMPLETE_KEYS + 2)

    def test_freeze_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze, _complete = self._freeze(self._fixture_events(), tmp)
            artifact = Path(tmp) / "out"
            write_freeze(artifact, freeze)
            path = freeze_path(artifact)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["complete_key_count"] = 0
            path.write_text(json.dumps(data, ensure_ascii=False),
                            encoding="utf-8")
            with self.assertRaises(Personal2x2Error):
                load_freeze(artifact)

    def test_under_30_keys_is_no_conclusion_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = self._fixture_events(count=3)
            freeze, _complete = self._freeze(events, tmp)
            freeze["freeze_digest"] = ""
            # apply_scores only reads complete_key_count/snapshot_sha256
            report = self._report(freeze)
            self.assertEqual(report["terminal"], NO_CONCLUSION)
            for route_id in ROUTE_IDS:
                self.assertIn(route_id, report["routes"])
                self.assertEqual(report["routes"][route_id]["label"],
                                 KNIFE_NO_CONCLUSION)
            self.assertEqual(report["cross_route"], CROSS_ANY_GREY)

    def test_zero_complete_keys_is_no_conclusion_terminal(self):
        freeze = build_freeze(
            snapshot_sha256=FALLBACK_PIN_SHA256,
            code_sha="a" * 40,
            complete_keys=[],
            complete_key_count=0,
            incomplete_reasons={"no_replayable_base": 5},
        )
        report = self._report(freeze)
        self.assertEqual(report["terminal"], NO_CONCLUSION)
        self.assertEqual(report["cross_route"], CROSS_ANY_GREY)

    def test_report_privacy_and_both_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze, _complete = self._freeze(self._fixture_events(), tmp)
            report = self._report(freeze)
            self.assertEqual(report["terminal"], "判定")
            for route_id in ROUTE_IDS:
                self.assertIn(route_id, report["routes"])
                self.assertIn("label", report["routes"][route_id])
            blob = json.dumps(report, ensure_ascii=False)
            for forbidden in ("上文甲", "选中", "陪跑", "另一", "k0"):
                self.assertNotIn(forbidden, blob)

    def test_report_rejects_drifted_key_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            freeze, _complete = self._freeze(self._fixture_events(), tmp)
            per_route = {route_id: [(0.1, 0.2)]
                         for route_id in ROUTE_IDS}
            with self.assertRaises(Personal2x2Error):
                apply_scores(freeze, freeze, per_route)

    def test_report_markdown_renders_terminal_and_verdict(self):
        from run_personal_layer_2x2 import _render_md
        with tempfile.TemporaryDirectory() as tmp:
            freeze, _complete = self._freeze(self._fixture_events(), tmp)
            report = self._report(freeze)
            md = _render_md(freeze, report)
            self.assertIn("cross-route", md)
            self.assertIn(str(report["cross_route"]), md)
            self.assertIn("gamma", md)
            for route_id in ROUTE_IDS:
                self.assertIn(route_id, md)

    def test_write_report_scans_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = self._fixture_events(count=1)
            path = Path(tmp) / "facts.sqlite3"
            build_snapshot(events, path=path)
            loaded = load_prefix_snapshot(path, hlc_min=(1000, 0),
                                          hlc_max_inclusive=(10000, 0))
            groups = group_keys(loaded)
            complete, reasons = classify_keys(groups)
            freeze = build_freeze(
                snapshot_sha256=FALLBACK_PIN_SHA256,
                code_sha="a" * 40,
                complete_keys=sorted(key_sha256(key) for key in complete),
                complete_key_count=len(complete),
                incomplete_reasons=reasons,
            )
            artifact = Path(tmp) / "out"
            write_freeze(artifact, freeze)
            report = self._report(freeze)
            from run_personal_layer_2x2 import _render_md
            md = _render_md(freeze, report)
            write_report(artifact, freeze, report, md)
            self.assertTrue((artifact / "prefix_2x2_report.json").is_file())
            self.assertTrue((artifact / "PX2X_REPORT.md").is_file())


if __name__ == "__main__":
    unittest.main()