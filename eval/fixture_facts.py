#!/usr/bin/env python3
"""Synthetic fact-store builder for the #70 walk-forward tests.

The fixture is fully model-free and deterministic: controlled unit vectors
drive the oracle, so every causality and statistics property can be pinned
exactly.  The schema mirrors the live facts store (fact_schema_version 1),
including retractions and the competition candidate table.
"""

import os
import sqlite3
import tempfile

from oracle import match_text


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
"""


class SyntheticFacts:
    """One disposable facts store over a fixed schema."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="walkforward_fixture_")
        self.db_path = os.path.join(self.root, "facts.sqlite3")
        self.connection = sqlite3.connect(self.db_path)
        self.connection.executescript(FACT_DDL)
        self.connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            (("fact_schema_version", "1"),
             ("event_format_version", "1"),
             ("history_id", "synthetic-history"),
             ("store_epoch", "synthetic-epoch"),
             ("hlc_physical_ms", "1000000"),
             ("hlc_logical", "0"),
             ("created_at_ms", "1000000")))
        self._seq = 0

    def add_event(self, event_id, canonical_segment_input, preceding_text,
                  final_selection_text, competition, hlc,
                  confirmation_source="explicit_current",
                  competition_complete=True, display_rank=1,
                  display_page=1, commit_id=None, retract_at=None,
                  schema_id="luna_pinyin", category="word"):
        """Insert one selection event (optionally retracted later).

        ``hlc`` is the commit HLC; ``retract_at`` (HLC) inserts a retraction
        of the commit, so the event is visible as history before that point
        but not as a target.
        """
        self._seq += 1
        if commit_id is None:
            commit_id = "commit-%d" % self._seq
        physical, logical = hlc
        self.connection.execute(
            "INSERT INTO commits(commit_id, utc_committed_at_ms)"
            " VALUES(?, ?)", (commit_id, physical))
        self.connection.execute(
            "INSERT INTO selection_events(event_id, commit_id,"
            " event_format_version, schema_id, canonical_segment_input,"
            " span_start, span_end, category, preceding_text,"
            " competition_complete, final_selection_text, confirmation_source,"
            " trigger_keycode, display_rank, display_page, session_id,"
            " session_seq, hlc_physical_ms, hlc_logical,"
            " utc_confirmed_at_ms, utc_committed_at_ms)"
            " VALUES(?, ?, 1, ?, ?, 0, 1, ?, ?, ?, ?, ?, NULL, ?, ?,"
            " 'synthetic', 0, ?, ?, ?, ?)",
            (event_id, commit_id, schema_id, canonical_segment_input,
             category, preceding_text,
             int(bool(competition_complete)), final_selection_text,
             confirmation_source, display_rank, display_page, physical,
             logical, physical, physical))
        for merge_order, text in enumerate(competition):
            self.connection.execute(
                "INSERT INTO selection_candidates(event_id, merge_order, text)"
                " VALUES(?, ?, ?)", (event_id, merge_order, text))
        if retract_at is not None:
            retraction_id = "retraction-%d" % self._seq
            r_physical, r_logical = retract_at
            self.connection.execute(
                "INSERT INTO retractions(retraction_id, commit_id,"
                " hlc_physical_ms, hlc_logical, utc_retracted_at_ms)"
                " VALUES(?, ?, ?, ?, ?)",
                (retraction_id, commit_id, r_physical, r_logical,
                 r_physical))
        self.connection.commit()
        return event_id

    def close(self):
        self.connection.close()
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


def unit_vector(cosine, dimension=4):
    """A unit vector whose dot with the canonical query axis is ``cosine``."""
    if not -1.0 <= cosine <= 1.0:
        raise ValueError("cosine out of range")
    remainder = (1.0 - cosine * cosine) ** 0.5
    return (cosine, remainder) + (0.0,) * (dimension - 2)


def fixture_provider(query_vectors, event_vectors, dimension=4,
                     representation_id="fixture:walkforward",
                     default_query=None, default_event=None):
    """A deterministic fixture provider over explicit text->vector maps.

    ``query_vectors`` maps the exact preceding text to a unit vector;
    ``event_vectors`` maps ``(schema_id, canonical_segment_input,
    final_selection_text)`` to a unit vector.  Tests build the maps so the
    cosine between a query and a history event is exactly the configured
    value, making every oracle step fully deterministic.
    """
    from evidence import FixtureRepresentationProvider
    return FixtureRepresentationProvider(
        representation_id,
        query_vectors,
        event_vectors,
        default_query=default_query if default_query is not None
        else (1.0, 0.0, 0.0, 0.0),
        default_event=default_event if default_event is not None
        else (0.0, 1.0, 0.0, 0.0),
    )


def axis_query_vectors():
    """Query text 'ctx' maps to the (1,0,0,0) axis."""
    return {"ctx": unit_vector(1.0)}


def selection_vectors(key_to_cosine, schema_id="luna_pinyin"):
    """event_vectors for (schema, canonical_input, selection) -> cosine."""
    return {("luna_pinyin", canonical, selection): unit_vector(cosine)
            for (canonical, selection), cosine in key_to_cosine.items()}
