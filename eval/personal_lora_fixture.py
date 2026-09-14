#!/usr/bin/env python3
"""Synthetic fact-store builder for the personal LoRA dataset tests.

The schema mirrors the live fact store (fact_schema_version 1) exactly, with
the same tables, columns, indexes-by-PK and retraction semantics.  Tests use
it to pin eligibility, duplicate, retraction, split and sealing behavior
without touching any real fact data.
"""

import json
import os
import shutil
import sqlite3
import tempfile

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

NO_PK_DDL = FACT_DDL.replace(
    "event_id TEXT PRIMARY KEY NOT NULL",
    "event_id TEXT NOT NULL").replace(
    "  text TEXT NOT NULL,\n  PRIMARY KEY (event_id, merge_order));",
    "  text TEXT NOT NULL);")

DEFAULT_META = {
    "fact_schema_version": "1",
    "event_format_version": "1",
    "history_id": "synthetic-history",
    "store_epoch": "synthetic-epoch",
    "hlc_physical_ms": "1000",
    "hlc_logical": "0",
    "created_at_ms": "1000",
}


class SyntheticSource:
    """One disposable facts store with controlled events and commits."""

    def __init__(self, root=None, primary_key=True, meta=None):
        self.root = root or tempfile.mkdtemp(prefix="personal_lora_fixture_")
        os.makedirs(self.root, exist_ok=True)
        self.db_path = os.path.join(self.root, "facts.sqlite3")
        self.connection = sqlite3.connect(self.db_path)
        self.connection.executescript(FACT_DDL if primary_key
                                      else NO_PK_DDL)
        values = dict(DEFAULT_META)
        if meta:
            values.update(meta)
        self.connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)", sorted(values.items()))
        self._commit_seq = 0
        self._event_seq = 0
        self._hlc_seq = 1000
        self._session_seq = {}
        self.connection.commit()

    def _next_hlc(self, step=10):
        self._hlc_seq += step
        return (self._hlc_seq, 0)

    def add_commit(self, commit_id=None, utc=None):
        if commit_id is None:
            self._commit_seq += 1
            commit_id = "commit-%d" % self._commit_seq
        self.connection.execute(
            "INSERT OR IGNORE INTO commits(commit_id, utc_committed_at_ms)"
            " VALUES(?, ?)", (commit_id, utc if utc is not None
                              else self._hlc_seq))
        return commit_id

    def add_event(self, event_id=None, commit_id=None, session_id="s1",
                  session_seq=None, hlc=None, preceding_text="",
                  final_selection_text="字", competition=("字", "词"),
                  schema_id="luna_pinyin", category="word",
                  confirmation_source="explicit_current", span_start=0,
                  span_end=1, competition_complete=False, display_rank=1,
                  display_page=1, canonical_segment_input=None):
        self._event_seq += 1
        if event_id is None:
            event_id = "event-%d" % self._event_seq
        if commit_id is None:
            commit_id = self.add_commit()
        else:
            self.add_commit(commit_id)
        if hlc is None:
            hlc = self._next_hlc()
        else:
            self._hlc_seq = max(self._hlc_seq, hlc[0])
        if session_seq is None:
            session_seq = self._session_seq.get(session_id, 0) + 1
            self._session_seq[session_id] = session_seq
        physical, logical = hlc
        self.connection.execute(
            "INSERT INTO selection_events(event_id, commit_id,"
            " event_format_version, schema_id, canonical_segment_input,"
            " span_start, span_end, category, preceding_text,"
            " competition_complete, final_selection_text,"
            " confirmation_source, trigger_keycode, display_rank,"
            " display_page, session_id, session_seq, hlc_physical_ms,"
            " hlc_logical, utc_confirmed_at_ms, utc_committed_at_ms)"
            " VALUES(?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?,"
            " ?, ?, ?, ?)",
            (event_id, commit_id, schema_id,
             canonical_segment_input or ("seg-%s" % event_id),
             span_start, span_end, category, preceding_text,
             int(bool(competition_complete)), final_selection_text,
             confirmation_source, display_rank, display_page, session_id,
             session_seq, physical, logical, physical, physical))
        for merge_order, text in enumerate(competition):
            self.connection.execute(
                "INSERT INTO selection_candidates(event_id, merge_order,"
                " text) VALUES(?, ?, ?)", (event_id, merge_order, text))
        self.connection.commit()
        return event_id

    def retract(self, commit_id, hlc=None):
        if hlc is None:
            hlc = self._next_hlc()
        physical, logical = hlc
        self.connection.execute(
            "INSERT INTO retractions(retraction_id, commit_id,"
            " hlc_physical_ms, hlc_logical, utc_retracted_at_ms)"
            " VALUES(?, ?, ?, ?, ?)",
            ("retraction-%s" % commit_id, commit_id, physical, logical,
             physical))
        self.connection.commit()

    def close(self, remove=True):
        self.connection.close()
        if remove:
            shutil.rmtree(self.root, ignore_errors=True)


def write_config(path, source_db, artifact_root, **extra):
    payload = {"source_db": source_db, "artifact_root": artifact_root}
    payload.update(extra)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    os.chmod(path, 0o600)
    return path


def read_partition(root, name):
    path = os.path.join(root, "dataset", "%s.jsonl" % name)
    records = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records
