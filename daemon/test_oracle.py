#!/usr/bin/env python3
"""Exact retrieval-evidence oracle tests (Habit130/squirrel#59, AC-59-v1).

Model-free, stdlib-only, sandboxed temp fact stores with synthetic fixed
vectors - never real private history.  The suite is adversarial by design:

  AC59-1  choice-problem key derivation preserves apostrophe / space /
          abbreviated-pinyin / fuzzy-pinyin / correction differences and
          unifies only NFC and ASCII case
  AC59-2  simplified-NFC exact matching; only the history's final selection
          gives positive evidence; no negative evidence, no variant merging
  AC59-3  all same-key active events are fully evaluated (cosine, threshold,
          usage age, final weight) BEFORE the top-K cut
  AC59-4  usage age advances only by same-key later active events; calendar
          time and unrelated input never decay
  AC59-5  retraction semantics follow HLC: exit evidence set and age clock at
          the retraction HLC; future retractions never backfill
  AC59-6  aggregation strictly bounded; zero evidence is a success
  AC59-7  fixed counterexample: cosine-top-K-then-age != oracle

  SCN-59-1 .. SCN-59-4 from the delivery contract are exercised inside the
  corresponding criterion groups.
"""

import math
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from oracle import (  # noqa: E402
    OracleError,
    OracleParams,
    OracleQuery,
    FactReader,
    canonicalize_segment_input,
    choice_problem_key,
    compute_evidence,
    match_text,
    simplify,
)

FACT_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE commits (
  commit_id TEXT PRIMARY KEY NOT NULL,
  utc_committed_at_ms INTEGER NOT NULL);
CREATE TABLE selection_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL REFERENCES commits(commit_id),
  event_format_version INTEGER NOT NULL,
  schema_id TEXT NOT NULL,
  canonical_segment_input TEXT NOT NULL,
  span_start INTEGER NOT NULL,
  span_end INTEGER NOT NULL,
  category TEXT NOT NULL,
  preceding_text TEXT NOT NULL,
  competition_complete INTEGER NOT NULL,
  final_selection_text TEXT NOT NULL,
  confirmation_source TEXT NOT NULL,
  trigger_keycode INTEGER,
  display_rank INTEGER NOT NULL,
  display_page INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  session_seq INTEGER NOT NULL,
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  utc_confirmed_at_ms INTEGER NOT NULL,
  utc_committed_at_ms INTEGER NOT NULL);
CREATE INDEX idx_selection_events_commit_id
  ON selection_events(commit_id);
CREATE TABLE selection_candidates (
  event_id TEXT NOT NULL REFERENCES selection_events(event_id),
  merge_order INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (event_id, merge_order));
CREATE TABLE retractions (
  retraction_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL REFERENCES commits(commit_id),
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  utc_retracted_at_ms INTEGER NOT NULL);
CREATE UNIQUE INDEX idx_retractions_commit_id ON retractions(commit_id);
"""


def unit_vector(component, dimension=4):
    """Unit vector whose cosine with the basis vector equals `component`."""
    if component > 1.0 or component < -1.0:
        raise ValueError("not a cosine")
    values = [component]
    values += [0.0] * (dimension - 1)
    values[1] = math.sqrt(max(0.0, 1.0 - component * component))
    return tuple(values)


# The query vector for most tests: cosine(query, unit_vector(x)) == x.
BASIS = (1.0, 0.0, 0.0, 0.0)


class FactsFixture:
    """One temp facts.sqlite3 store with deterministic content."""

    def __init__(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_oracle_")
        self.db_path = os.path.join(self._tmp, "facts.sqlite3")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(FACT_DDL)
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('fact_schema_version', '1');")
        self.conn.execute(
            "INSERT INTO meta(key, value)"
            " VALUES('event_format_version', '1');")
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('history_id', 'h1');")
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('store_epoch', 'e1');")
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('hlc_physical_ms',"
            " '1000000');")
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('hlc_logical', '0');")
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('created_at_ms', '1000000');")
        self.conn.commit()
        self._next_logical = 1

    def close(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def set_clock(self, physical_ms, logical):
        self.conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'hlc_physical_ms';",
            (physical_ms,))
        self.conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'hlc_logical';", (logical,))
        self.conn.commit()

    def add_event(self, event_id, *,
                  commit_id=None, schema_id="luna_pinyin",
                  segment_input="nihao", category="word",
                  selection="你好", hlc=None, utc_committed=None,
                  utc_confirmed=None, preceding_text="前文",
                  competition=()):
        """One immutable selection event; HLC auto-advances when not given.

        The meta clock advances with every write, mirroring the C++ store.
        ``preceding_text`` is the raw recent-64-char 上文 the event was
        recorded with; ``competition`` extends the materialized competition
        set (merge order 1+; the selection itself is always merge order 0).
        """
        commit_id = commit_id or "commit-" + event_id
        if hlc is None:
            hlc = (1000000, self._next_logical)
            self._next_logical += 1
        physical, logical = hlc
        self.conn.execute(
            "INSERT OR IGNORE INTO commits(commit_id, utc_committed_at_ms)"
            " VALUES(?, ?);", (commit_id, utc_committed or physical))
        self.conn.execute(
            "INSERT INTO selection_events(event_id, commit_id,"
            " event_format_version, schema_id, canonical_segment_input,"
            " span_start, span_end, category, preceding_text,"
            " competition_complete, final_selection_text,"
            " confirmation_source, trigger_keycode, display_rank,"
            " display_page, session_id, session_seq, hlc_physical_ms,"
            " hlc_logical, utc_confirmed_at_ms, utc_committed_at_ms)"
            " VALUES(?,?,?,?,?,0,4,?,?,1,?,?,NULL,1,1,'s1',0,?,?,?,?);",
            (event_id, commit_id, 1, schema_id, segment_input, category,
             preceding_text, selection, "explicit_current", physical, logical,
             utc_confirmed or physical, utc_committed or physical))
        self.conn.execute(
            "INSERT INTO selection_candidates(event_id, merge_order, text)"
            " VALUES(?, 0, ?);", (event_id, selection))
        for order, text in enumerate(competition, start=1):
            self.conn.execute(
                "INSERT INTO selection_candidates(event_id, merge_order, text)"
                " VALUES(?, ?, ?);", (event_id, order, text))
        self._advance_clock(physical, logical)
        self.conn.commit()
        return event_id

    def _advance_clock(self, physical, logical):
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'hlc_physical_ms';").fetchone()
        row_logical = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'hlc_logical';").fetchone()
        clock = (int(row["value"]), int(row_logical["value"]))
        if (physical, logical) > clock:
            self.conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'hlc_physical_ms';",
                (physical,))
            self.conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'hlc_logical';",
                (logical,))

    def add_retraction(self, retraction_id, commit_id, hlc):
        physical, logical = hlc
        self.conn.execute(
            "INSERT INTO retractions(retraction_id, commit_id,"
            " hlc_physical_ms, hlc_logical, utc_retracted_at_ms)"
            " VALUES(?,?,?,?,?);",
            (retraction_id, commit_id, physical, logical, physical))
        self._advance_clock(physical, logical)
        self.conn.commit()


def run_oracle(fixture, params, query, vectors):
    reader = FactReader(fixture.db_path)
    try:
        return compute_evidence(reader, params, query,
                                lambda event_id: vectors[event_id])
    finally:
        reader.close()


DEFAULT_PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                              saturation_k=1.0)

COMMON_VECTORS = {
    "e1": unit_vector(0.95),
    "e2": unit_vector(0.90),
    "e3": unit_vector(0.80),
    "e4": unit_vector(0.70),
}


class CanonicalizeSegmentInputTest(unittest.TestCase):
    """AC59-1: key derivation is conservative; only NFC + ASCII case."""

    def key(self, text):
        return choice_problem_key("luna_pinyin", "word", text)

    def test_apostrophe_preserved(self):
        self.assertNotEqual(self.key("xi'an"), self.key("xian"))

    def test_space_preserved(self):
        self.assertNotEqual(self.key("ni hao"), self.key("nihao"))

    def test_abbreviated_pinyin_preserved(self):
        # 简拼 "cs" must not merge with the full spelling "chushi".
        self.assertNotEqual(self.key("cs"), self.key("chushi"))

    def test_fuzzy_pinyin_preserved(self):
        # 模糊音 l/n: "lan" must not merge with "nan".
        self.assertNotEqual(self.key("lan"), self.key("nan"))

    def test_correction_preserved(self):
        # 纠错差异: full "gui" vs corrected spelling "guei".
        self.assertNotEqual(self.key("gui"), self.key("guei"))

    def test_nfc_forms_merge(self):
        composed = "x\u00ed'an"
        decomposed = "xi\u0301'an"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(canonicalize_segment_input(composed),
                         canonicalize_segment_input(decomposed))

    def test_ascii_case_merges(self):
        self.assertEqual(canonicalize_segment_input("NIHAO"),
                         canonicalize_segment_input("nihao"))

    def test_schema_and_category_partition(self):
        key = choice_problem_key("luna_pinyin", "word", "nihao")
        self.assertEqual(key, choice_problem_key("luna_pinyin", "word",
                                                 "NIHao"))
        self.assertNotEqual(key, choice_problem_key("double_pinyin", "word",
                                                    "nihao"))
        self.assertNotEqual(key, choice_problem_key("luna_pinyin", "sentence",
                                                    "nihao"))

    def test_key_is_spec_tuple(self):
        self.assertEqual(("luna_pinyin", "word", "nihao"),
                         choice_problem_key("luna_pinyin", "word", "NIHAO"))


class SimplifyTest(unittest.TestCase):
    """AC59-2: simplified conversion + NFC produce the matching text."""

    def test_common_simplifications(self):
        self.assertEqual(simplify("後台"), "后台")
        self.assertEqual(simplify("繁體"), "繁体")
        self.assertEqual(simplify("電腦"), "电脑")
        self.assertEqual(simplify("時間"), "时间")

    def test_first_alternative_policy(self):
        # 乾 -> "干" is the first (default) alternative.
        self.assertEqual(simplify("乾坤"), "乾坤")  # phrase table keeps it
        self.assertEqual(simplify("乾"), "干")      # char fallback

    def test_unknown_passes_through(self):
        self.assertEqual(simplify("abc 123"), "abc 123")
        self.assertEqual(simplify("汉字"), "汉字")

    def test_no_variant_merging(self):
        # 著 is not in the t2s tables; 著 and 着 must stay distinct (spec:
        # no 字形变体 merging).
        self.assertEqual(match_text("著作"), "著作")
        self.assertNotEqual(match_text("著"), match_text("着"))

    def test_nfc_applied_to_match_text(self):
        composed = "\u00e9"
        decomposed = "e\u0301"
        self.assertEqual(match_text(composed), match_text(decomposed))

    def test_traditional_history_matches_simplified_candidate(self):
        self.assertEqual(match_text("後台"), match_text("后台"))
        self.assertEqual(match_text("后台"), match_text("後台"))


class MatchEvidenceTest(unittest.TestCase):
    """AC59-2: only exact simplified-NFC matches give positive evidence."""

    def setUp(self):
        self.fixture = FactsFixture()
        self.fixture.add_event("e1", segment_input="houtai",
                               selection="後台")
        self.fixture.add_event("e2", segment_input="qiantai",
                               selection="前台")
        self.vectors = {"e1": unit_vector(0.95), "e2": unit_vector(0.95)}

    def tearDown(self):
        self.fixture.close()

    def test_traditional_selection_matches_simplified_candidate(self):
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "houtai", ["后台", "前台"],
                        BASIS),
            self.vectors)
        self.assertEqual(1, result.same_key_active)
        kept = {contribution.event_id: contribution
                for contribution in result.kept}
        self.assertIn("e1", kept)
        # e1 selected 後台, which matches the simplified candidate 后台.
        self.assertEqual(0, kept["e1"].matched_candidate)
        self.assertGreater(result.candidates[0].m, 0.0)
        self.assertEqual(0.0, result.candidates[1].m)

    def test_only_final_selection_gets_positive_evidence(self):
        # e2 selected 前台; the unselected candidate 后台 gets zero (not
        # negative) evidence.
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "qiantai", ["前台", "后台"],
                        BASIS),
            self.vectors)
        kept = {contribution.event_id: contribution
                for contribution in result.kept}
        self.assertEqual(0, kept["e2"].matched_candidate)
        self.assertEqual(0.0, result.candidates[1].m)

    def test_selection_not_in_group_is_zero_evidence_success(self):
        # A history whose selected candidate is absent from the current
        # group contributes nothing; this is still a success, not a fault.
        fixture = FactsFixture()
        fixture.add_event("e1", segment_input="houtai", selection="侧台")
        try:
            result = run_oracle(
                fixture, DEFAULT_PARAMS,
                OracleQuery("luna_pinyin", "houtai", ["后台", "前台"],
                            BASIS),
                {"e1": unit_vector(0.99)})
            self.assertEqual(1, result.same_key_active)
            self.assertEqual(0.0, result.total_mass)
            for candidate in result.candidates:
                self.assertEqual(0.0, candidate.s)
        finally:
            fixture.close()

    def test_nfc_candidate_matching(self):
        self.fixture.add_event("e4", segment_input="cafe",
                               selection="caf\u00e9")
        self.vectors["e4"] = unit_vector(0.95)
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "cafe", ["caf\u00e9"], BASIS),
            self.vectors)
        kept = {contribution.event_id: contribution
                for contribution in result.kept}
        self.assertEqual(0, kept["e4"].matched_candidate)
        self.assertGreater(result.total_mass, 0.0)


class OrderOfEvaluationTest(unittest.TestCase):
    """AC59-3 / SCN-59-1: compute everything first, then take K."""

    def setUp(self):
        self.fixture = FactsFixture()

    def tearDown(self):
        self.fixture.close()

    def test_old_high_cosine_loses_to_young_event_after_ageing(self):
        # e1 is old (u=10) with a very high cosine; e2 is new (u=0) with a
        # lower cosine but a higher final weight a_i = r_i * d_i.
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 11))
        # e1 has 9 later same-key active events -> u=9... build them.
        for i in range(8):
            self.fixture.add_event("x%d" % i, selection="丙",
                                   hlc=(1000000, 2 + i))
        vectors = {"e1": unit_vector(0.99), "e2": unit_vector(0.95)}
        for i in range(8):
            vectors["x%d" % i] = unit_vector(0.50)
        params = OracleParams(tau=0.5, k_evidence=1, half_life=8.0,
                              saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙", "丙"],
                        BASIS),
            vectors)
        # cosine order: e1 first; a_i order: e2 first.
        self.assertEqual(["e2"], [c.event_id for c in result.kept])
        contributions = {c.event_id: c for c in result.kept}
        e1 = contributions["e2"]
        self.assertEqual(0.95, e1.cosine)
        self.assertEqual(0, e1.usage_age)
        self.assertEqual(1.0, e1.age_factor)

    def test_k_caps_kept_set_and_keeps_highest_weights(self):
        for i in range(4):
            self.fixture.add_event("e%d" % i, hlc=(1000000, 1 + i))
        vectors = {"e0": unit_vector(0.95), "e1": unit_vector(0.90),
                   "e2": unit_vector(0.80), "e3": unit_vector(0.70)}
        params = OracleParams(tau=0.5, k_evidence=2, half_life=32.0,
                              saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            vectors)
        self.assertEqual(2, len(result.kept))
        self.assertEqual(["e0", "e1"],
                         [c.event_id for c in result.kept])

    def test_tie_break_is_hlc_then_event_id(self):
        # Identical final weights (no ageing, same cosine): the older event
        # wins the single kept slot deterministically.
        self.fixture.add_event("e1", hlc=(1000000, 1))
        self.fixture.add_event("e2", hlc=(1000000, 2))
        vectors = {"e1": unit_vector(0.90), "e2": unit_vector(0.90)}
        params = OracleParams(tau=0.5, k_evidence=1, half_life=float("inf"),
                              saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            vectors)
        self.assertEqual(["e1"], [c.event_id for c in result.kept])

    def test_below_threshold_events_never_enter_kept(self):
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 2))
        vectors = {"e1": unit_vector(0.95), "e2": unit_vector(0.45)}
        params = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                              saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"],
                        BASIS),
            vectors)
        self.assertEqual(["e1"], [c.event_id for c in result.kept])
        self.assertEqual(0.0, result.candidates[1].m)


class UsageAgeTest(unittest.TestCase):
    """AC59-4: age advances only by same-key later ACTIVE events."""

    def setUp(self):
        self.fixture = FactsFixture()

    def tearDown(self):
        self.fixture.close()

    def test_age_formula_values(self):
        self.fixture.add_event("e1", hlc=(1000000, 1))
        self.fixture.add_event("e2", hlc=(1000000, 2))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        contributions = {c.event_id: c for c in result.kept}
        self.assertEqual(1, contributions["e1"].usage_age)
        self.assertEqual(2.0 ** (-1.0 / 32.0), contributions["e1"].age_factor)
        self.assertEqual(0, contributions["e2"].usage_age)
        self.assertEqual(1.0, contributions["e2"].age_factor)

    def test_infinite_half_life_never_decays(self):
        self.fixture.add_event("e1", hlc=(1000000, 1))
        self.fixture.add_event("e2", hlc=(1000000, 2))
        params = OracleParams(tau=0.5, k_evidence=8,
                              half_life=float("inf"), saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        contributions = {c.event_id: c for c in result.kept}
        self.assertEqual(1.0, contributions["e1"].age_factor)
        self.assertEqual(1.0, contributions["e2"].age_factor)

    def test_calendar_time_never_decays(self):
        fixture_a = FactsFixture()
        fixture_a.add_event("e1", selection="甲", hlc=(1000000, 1),
                            utc_confirmed=1000, utc_committed=1000)
        fixture_a.add_event("e2", selection="甲", hlc=(1000000, 2),
                            utc_confirmed=2000, utc_committed=2000)
        fixture_b = FactsFixture()
        fixture_b.add_event("e1", selection="甲", hlc=(1000000, 1),
                            utc_confirmed=9999999999000,
                            utc_committed=9999999999000)
        fixture_b.add_event("e2", selection="甲", hlc=(1000000, 2),
                            utc_confirmed=9999999999000,
                            utc_committed=9999999999000)
        try:
            query = OracleQuery("luna_pinyin", "nihao", ["甲"],
                                BASIS)
            result_a = run_oracle(fixture_a, DEFAULT_PARAMS, query,
                                  {"e1": unit_vector(0.95),
                                   "e2": unit_vector(0.95)})
            result_b = run_oracle(fixture_b, DEFAULT_PARAMS, query,
                                  {"e1": unit_vector(0.95),
                                   "e2": unit_vector(0.95)})
            self.assertEqual(result_a.kept, result_b.kept)
            self.assertEqual(result_a.candidates, result_b.candidates)
        finally:
            fixture_a.close()
            fixture_b.close()

    def test_unrelated_key_never_advances_age(self):
        self.fixture.add_event("e1", segment_input="nihao", hlc=(1000000, 1))
        self.fixture.add_event("e2", segment_input="haode", hlc=(1000000, 2))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        contributions = {c.event_id: c for c in result.kept}
        self.assertEqual(["e1"], list(contributions))
        self.assertEqual(0, contributions["e1"].usage_age)
        self.assertEqual(1.0, contributions["e1"].age_factor)

    def test_repeated_selection_same_candidate(self):
        # SCN-59-4: old events age normally; the new event joins at d=1.
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="甲", hlc=(1000000, 2))
        params = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                              saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["甲"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        contributions = {c.event_id: c for c in result.kept}
        self.assertEqual(1, contributions["e1"].usage_age)
        self.assertLess(contributions["e1"].age_factor, 1.0)
        self.assertEqual(0, contributions["e2"].usage_age)
        self.assertEqual(1.0, contributions["e2"].age_factor)
        expected_mass = (0.9 * 2.0 ** (-1.0 / 32.0)) + 0.9
        self.assertAlmostEqual(expected_mass, result.total_mass)


class RetractionSemanticsTest(unittest.TestCase):
    """AC59-5 / SCN-59-2: HLC-based exit from evidence set and age clock."""

    def setUp(self):
        self.fixture = FactsFixture()

    def tearDown(self):
        self.fixture.close()

    def test_retraction_exits_evidence_and_age_clock(self):
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 2))
        self.fixture.add_retraction("r1", "commit-e2", hlc=(1000000, 3))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        self.assertEqual(["e1"], [c.event_id for c in result.kept])
        contributions = {c.event_id: c for c in result.kept}
        # e2 no longer advances e1's age clock.
        self.assertEqual(0, contributions["e1"].usage_age)
        self.assertEqual(1.0, contributions["e1"].age_factor)
        self.assertEqual(0.0, result.candidates[1].m)

    def test_retraction_covers_whole_commit(self):
        self.fixture.add_event("e1", commit_id="commit-1", selection="甲",
                               hlc=(1000000, 1))
        self.fixture.add_event("e2", commit_id="commit-1", selection="乙",
                               hlc=(1000000, 2))
        self.fixture.add_retraction("r1", "commit-1", hlc=(1000000, 3))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        self.assertEqual([], list(result.kept))
        self.assertEqual(0.0, result.total_mass)

    def test_future_retraction_never_backfills(self):
        # SCN-59-2: querying before the retraction HLC still sees e2 active.
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 2))
        self.fixture.add_retraction("r1", "commit-e2", hlc=(1000000, 5))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"], BASIS,
                        as_of=(1000000, 4)),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        self.assertEqual({"e1", "e2"},
                         {c.event_id for c in result.kept})
        contributions = {c.event_id: c for c in result.kept}
        self.assertEqual(1, contributions["e1"].usage_age)
        self.assertGreater(result.candidates[1].m, 0.0)

    def test_event_after_query_point_is_not_visible(self):
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 3))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"], BASIS,
                        as_of=(1000000, 2)),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        self.assertEqual(["e1"], [c.event_id for c in result.kept])
        self.assertEqual(0, result.candidates[1].m)

    def test_default_query_point_applies_all_retractions(self):
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 2))
        self.fixture.add_retraction("r1", "commit-e2", hlc=(1000000, 3))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"], BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        self.assertEqual(["e1"], [c.event_id for c in result.kept])

    def test_excluded_event_neither_evidences_nor_ages(self):
        # Walk-forward replay of a target event: it must not see itself.
        self.fixture.add_event("target", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e1", selection="乙", hlc=(1000000, 2))
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"], BASIS,
                        exclude_event_ids=frozenset({"target"})),
            {"target": unit_vector(0.95), "e1": unit_vector(0.95)})
        self.assertEqual(["e1"], [c.event_id for c in result.kept])
        contributions = {c.event_id: c for c in result.kept}
        self.assertEqual(0, contributions["e1"].usage_age)


class BoundednessAndZeroEvidenceTest(unittest.TestCase):
    """AC59-6: strict bounds; zero evidence is success, not a fault."""

    def setUp(self):
        self.fixture = FactsFixture()

    def tearDown(self):
        self.fixture.close()

    def test_empty_store_is_zero_evidence_success(self):
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            {})
        self.assertEqual(0, result.same_key_active)
        self.assertEqual([], list(result.kept))
        self.assertEqual(0.0, result.candidates[0].s)

    def test_no_same_key_events_is_zero_evidence_success(self):
        self.fixture.add_event("e1", segment_input="qita", selection="其他")
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS),
            {"e1": unit_vector(0.95)})
        self.assertEqual(0, result.same_key_active)
        self.assertEqual(0.0, result.candidates[0].s)

    def test_nothing_above_tau_is_zero_evidence_success(self):
        self.fixture.add_event("e1", selection="甲")
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲"], BASIS),
            {"e1": unit_vector(0.30)})
        self.assertEqual(1, result.same_key_active)
        self.assertEqual([], list(result.kept))
        self.assertEqual(0.0, result.candidates[0].s)

    def test_cosine_equal_tau_is_strictly_zero(self):
        # r_i must be exactly zero at cos == tau.  The event vector
        # (0.5, 0.5, 0.5, 0.5) has unit norm and exact cosine 0.5 with BASIS,
        # so the threshold comparison is exact rather than float-noise.
        self.fixture.add_event("e1", selection="甲")
        result = run_oracle(
            self.fixture, DEFAULT_PARAMS,
            OracleQuery("luna_pinyin", "nihao", ["甲"], BASIS),
            {"e1": (0.5, 0.5, 0.5, 0.5)})
        self.assertEqual([], list(result.kept))
        self.assertEqual(0.0, result.total_mass)

    def test_single_event_delta_one_bound(self):
        for saturation_k, expected in ((1.0, 1.0 / 2.0), (3.0, 1.0 / 4.0)):
            fixture = FactsFixture()
            fixture.add_event("e1", selection="甲")
            params = OracleParams(tau=0.0, k_evidence=8,
                                  half_life=float("inf"),
                                  saturation_k=saturation_k)
            result = run_oracle(
                fixture, params,
                OracleQuery("luna_pinyin", "nihao", ["甲"],
                            BASIS),
                {"e1": unit_vector(1.0)})
            # s_c == 1/(1+k), i.e. gamma*s_c <= gamma/(1+k) == Delta_1.
            self.assertAlmostEqual(expected, result.candidates[0].s)
            fixture.close()

    def test_s_is_always_below_one(self):
        for i in range(10):
            self.fixture.add_event("e%d" % i, selection="甲",
                                   hlc=(1000000, 1 + i))
        vectors = {"e%d" % i: unit_vector(1.0) for i in range(10)}
        params = OracleParams(tau=0.0, k_evidence=8,
                              half_life=float("inf"), saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["甲"], BASIS),
            vectors)
        self.assertEqual(8, len(result.kept))
        self.assertGreater(result.candidates[0].m, 0.0)
        self.assertLess(result.candidates[0].s, 1.0)
        self.assertGreaterEqual(result.candidates[0].s, 0.0)

    def test_share_and_saturation_decompose(self):
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 2))
        params = OracleParams(tau=0.5, k_evidence=8,
                              half_life=float("inf"), saturation_k=1.0)
        result = run_oracle(
            self.fixture, params,
            OracleQuery("luna_pinyin", "nihao", ["甲", "乙"],
                        BASIS),
            {"e1": unit_vector(0.95), "e2": unit_vector(0.95)})
        # Both m == 0.9: share 0.5, saturation 0.9/1.9 -> s = 0.5 * 0.9/1.9.
        expected = 0.5 * (0.9 / 1.9)
        self.assertAlmostEqual(expected, result.candidates[0].s)
        self.assertAlmostEqual(expected, result.candidates[1].s)


class TopKCosineThenAgeCounterexampleTest(unittest.TestCase):
    """AC59-7: the fixed counterexample proving the order matters."""

    def setUp(self):
        self.fixture = FactsFixture()

    def tearDown(self):
        self.fixture.close()

    def test_cosine_top_k_then_age_differs_from_oracle(self):
        # Fixed scenario.  e1 is old with the highest cosine (0.99); e2 is
        # new with a lower cosine (0.95) but a higher final weight
        # a_i = r_i * d_i.  K=1, H=4.
        self.fixture.add_event("e1", selection="甲", hlc=(1000000, 1))
        self.fixture.add_event("e2", selection="乙", hlc=(1000000, 2))
        params = OracleParams(tau=0.5, k_evidence=1, half_life=4.0,
                              saturation_k=1.0)
        query = OracleQuery("luna_pinyin", "nihao", ["甲", "乙"],
                            BASIS)
        vectors = {"e1": unit_vector(0.99), "e2": unit_vector(0.95)}
        result = run_oracle(self.fixture, params, query, vectors)

        # The oracle keeps the young event e2 and supports 乙.
        self.assertEqual(["e2"], [c.event_id for c in result.kept])
        oracle_s_b = result.candidates[1].s
        self.assertGreater(oracle_s_b, 0.0)
        self.assertEqual(0.0, result.candidates[0].s)
        self.assertAlmostEqual(0.9 / 1.9, oracle_s_b)

        # The naive alternative (cosine top-K first, then age) keeps e1 and
        # produces different evidence on the same facts and vectors:
        #   r_e1 = (0.99 - 0.5) / 0.5 = 0.98,  d_e1 = 2 ** (-1 / 4)
        expected_a_e1 = 0.98 * 2.0 ** (-1.0 / 4.0)
        naive_s_a = (expected_a_e1 / expected_a_e1) * (
            expected_a_e1 / (expected_a_e1 + params.saturation_k))
        self.assertGreater(naive_s_a, 0.0)
        self.assertNotAlmostEqual(naive_s_a, oracle_s_b)
        # Cosine-top-K supports 甲 while the oracle supports 乙: not just a
        # different magnitude, a different candidate entirely.
        self.assertEqual(0.0, result.candidates[0].s)


class FaultSemanticsTest(unittest.TestCase):
    """True faults raise OracleError; never silently become zero evidence."""

    def setUp(self):
        self.fixture = FactsFixture()

    def tearDown(self):
        self.fixture.close()

    def test_missing_store_raises(self):
        with self.assertRaises(OracleError):
            FactReader("/nonexistent/facts.sqlite3")

    def test_missing_meta_clock_raises(self):
        self.fixture.conn.execute(
            "DELETE FROM meta WHERE key = 'hlc_physical_ms';")
        self.fixture.conn.commit()
        with self.assertRaises(OracleError):
            run_oracle(self.fixture, DEFAULT_PARAMS,
                       OracleQuery("luna_pinyin", "nihao", ["你好"],
                                   BASIS), {})

    def test_missing_vector_raises(self):
        self.fixture.add_event("e1", selection="甲")
        with self.assertRaises(OracleError):
            run_oracle(self.fixture, DEFAULT_PARAMS,
                       OracleQuery("luna_pinyin", "nihao", ["甲"],
                                   BASIS), {})

    def test_dimension_mismatch_raises(self):
        self.fixture.add_event("e1", selection="甲")
        with self.assertRaises(OracleError):
            run_oracle(self.fixture, DEFAULT_PARAMS,
                       OracleQuery("luna_pinyin", "nihao", ["甲"],
                                   BASIS),
                       {"e1": unit_vector(0.95, dimension=6)})

    def test_non_finite_vector_raises(self):
        self.fixture.add_event("e1", selection="甲")
        with self.assertRaises(OracleError):
            run_oracle(self.fixture, DEFAULT_PARAMS,
                       OracleQuery("luna_pinyin", "nihao", ["甲"],
                                   BASIS),
                       {"e1": (0.5, float("nan"), 0.0, 0.0)})

    def test_zero_vector_raises(self):
        self.fixture.add_event("e1", selection="甲")
        with self.assertRaises(OracleError):
            run_oracle(self.fixture, DEFAULT_PARAMS,
                       OracleQuery("luna_pinyin", "nihao", ["甲"],
                                   BASIS),
                       {"e1": (0.0, 0.0, 0.0, 0.0)})

    def test_invalid_params_raise(self):
        base = dict(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)
        for overrides in ({"tau": -0.1}, {"tau": 1.0}, {"k_evidence": 0},
                          {"k_evidence": 1.5}, {"half_life": 0.0},
                          {"half_life": -8.0}, {"saturation_k": 0.0},
                          {"saturation_k": -1.0}):
            kwargs = dict(base)
            kwargs.update(overrides)
            with self.assertRaises(OracleError):
                OracleParams(**kwargs)

    def test_invalid_query_raises(self):
        with self.assertRaises(OracleError):
            OracleQuery("", "nihao", ["你好"], BASIS)
        with self.assertRaises(OracleError):
            OracleQuery("luna_pinyin", "nihao", [], BASIS)
        with self.assertRaises(OracleError):
            OracleQuery("luna_pinyin", "nihao", ["你好"], [])
        with self.assertRaises(OracleError):
            OracleQuery("luna_pinyin", "nihao", ["你好"], BASIS,
                        as_of=(-1, 0))


class DeterminismTest(unittest.TestCase):
    def test_identical_inputs_identical_results(self):
        fixture = FactsFixture()
        try:
            for i in range(4):
                fixture.add_event("e%d" % i, selection="甲",
                                  hlc=(1000000, 1 + i))
            query = OracleQuery("luna_pinyin", "nihao", ["甲"],
                                BASIS)
            vectors = {"e0": unit_vector(0.95), "e1": unit_vector(0.90),
                       "e2": unit_vector(0.85), "e3": unit_vector(0.80)}
            first = run_oracle(fixture, DEFAULT_PARAMS, query, vectors)
            for _ in range(3):
                again = run_oracle(fixture, DEFAULT_PARAMS, query, vectors)
                self.assertEqual(first, again)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
