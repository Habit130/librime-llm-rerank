#!/usr/bin/env python3
"""Two deterministic 100k-event capacity fixtures (Habit130/squirrel#71).

Spec #43 "十万事件性能夹具":

  - 一套模拟真实选择问题键频率 (realistic choice-problem-key frequency
    distribution).
  - 一套把十万事件全部放在同一热键 (single-hot-key worst case).

Both fixtures are fully deterministic (fixed seed), use only synthetic
selection text (never private history), and record their generation rules
and summary so the report package can prove reproducibility.  The vectors
are NOT stored in the fact store (facts save only raw 上文 per spec); the
#71 seed-vector provider (daemon/seed_vectors.py) regenerates them
deterministically from the event id, so the fixtures double as the input
for the #72/#73 Accelerate/MLX exact-path challenges and the #78/#79 ANN
eligibility work without re-deriving vectors from the fact text.

Design decisions (recorded, SCN-71-1):

  D1 Key-frequency fixture: 100,000 events over a Zipf-like distribution
     with exponent s=1.2 across 2,000 distinct keys.  This mirrors the
     observed real-world shape (few hot keys, long tail) without claiming
     to be the live machine's distribution; the parameter set is the
     documented rule.  Each key is a synthetic canonical segment input
     ``key-<n>`` (ASCII, no real pinyin), because the fixture's purpose is
     capacity/latency, not quality (quality uses real selection events per
     spec).
  D2 Single-hot-key fixture: all 100,000 events on one key ``hotkey``.
  D3 Each event: one commit, competition set of 3 word candidates
     (synthetic text ``w0``/``w1``/``w2``), final selection cycling through
     the candidates, ``competition_complete=true``, ``confirmation_source``
     cycling ``explicit_current``/``explicit_indexed``, deterministic HLC
     (physical = base + index, logical 0), 64-char synthetic preceding text
     built from a fixed alphabet so the query-side 64-char window contract
     is exercised (len <= 64).
  D4 The fixture store is created with the production fact schema (the
     exact DDL used by the C++ store; the daemon reads it read-only).  The
     store is a disposable temp root; nothing touches the live facts root.
  D5 Determinism: the whole build is a pure function of the seed.  The
     report records the seed and the SHA-256 of the resulting facts store.

The module also exposes the deterministic query/event vector rule summary
(see daemon/seed_vectors.py) so the report can cross-reference both.
"""

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from test_oracle import FACT_DDL  # noqa: E402  (production fact schema)

FIXTURE_VERSION = "100k-fixtures-v1"
DEFAULT_SEED = 20260817
DEFAULT_EVENTS = 100000
DISTINCT_KEYS = 2000
ZIPF_EXPONENT = 1.2
COMPETITION = ("w0", "w1", "w2")
CONFIRMATION_SOURCES = ("explicit_current", "explicit_indexed")
BASE_PHYSICAL_MS = 1700000000000

# A fixed 64-char synthetic preceding-text alphabet (no real 上文, no
# private text; exercises the 64-char window contract).
WINDOW_ALPHABET = ("abcdefghijklmnopqrstuvwxyz0123456789"
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _window_text(index):
    """Deterministic 64-char synthetic window from a fixed alphabet."""
    out = []
    for position in range(64):
        out.append(WINDOW_ALPHABET[(index + position * 7) % len(WINDOW_ALPHABET)])
    return "".join(out)


def _zipf_weights(count, exponent):
    """Unnormalized Zipf weights 1/k^exponent for k in 1..count."""
    return [1.0 / (float(k) ** exponent) for k in range(1, count + 1)]


def _draw_key(rng, keys, cumulative, total):
    """One deterministic key draw from the precomputed Zipf CDF."""
    target = rng.random() * total
    # linear scan is fine (2000 keys); keep it simple and deterministic
    for index, cum in enumerate(cumulative):
        if target <= cum:
            return keys[index]
    return keys[-1]


def build_fixture_facts(root, kind, seed=DEFAULT_SEED, event_count=DEFAULT_EVENTS):
    """Create one 100k-event facts store under ``root``.

    ``kind`` is ``"freq"`` (realistic key-frequency) or ``"hotkey"``
    (single hot key).  Returns a summary dict (no raw text) suitable for
    the report package.
    """
    import random
    rng = random.Random(seed)
    os.makedirs(root, exist_ok=True)
    os.chmod(root, 0o700)
    db_path = os.path.join(root, "facts.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript(FACT_DDL)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    if kind == "freq":
        weights = _zipf_weights(DISTINCT_KEYS, ZIPF_EXPONENT)
        total = sum(weights)
        keys = ["key-%05d" % index for index in range(DISTINCT_KEYS)]
        cumulative = []
        acc = 0.0
        for weight in weights:
            acc += weight / total
            cumulative.append(acc)
    elif kind == "hotkey":
        keys = ["hotkey"]
        cumulative = [1.0]
        total = 1.0
    else:
        raise ValueError("unknown fixture kind %r" % kind)

    meta = [
        ("fact_schema_version", "1"),
        ("event_format_version", "1"),
        ("history_id", "fixture-history-%s" % seed),
        ("store_epoch", "fixture-epoch-%s-%s" % (kind, seed)),
        ("hlc_physical_ms", str(BASE_PHYSICAL_MS)),
        ("hlc_logical", "0"),
        ("created_at_ms", str(BASE_PHYSICAL_MS)),
    ]
    conn.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", meta)

    commit_ids = []
    events = []
    candidates = []
    key_counts = {}
    for index in range(event_count):
        key = _draw_key(rng, keys, cumulative, total) if kind == "freq" else "hotkey"
        key_counts[key] = key_counts.get(key, 0) + 1
        event_id = "ev-%s-%07d" % (kind, index)
        commit_id = "commit-%s-%07d" % (kind, index)
        commit_ids.append((commit_id, BASE_PHYSICAL_MS + index))
        selection = COMPETITION[index % len(COMPETITION)]
        source = CONFIRMATION_SOURCES[index % len(CONFIRMATION_SOURCES)]
        display_rank = 1 if index % 3 == 0 else 2
        events.append(
            (event_id, commit_id, 1, "luna_pinyin", key, 0, 4, "word",
             _window_text(index), 1, selection, source, None, display_rank,
             1, "synthetic-session", index, BASE_PHYSICAL_MS + index, 0,
             BASE_PHYSICAL_MS + index, BASE_PHYSICAL_MS + index))
        for merge_order, text in enumerate(COMPETITION):
            candidates.append((event_id, merge_order, text))
    conn.executemany(
        "INSERT INTO commits(commit_id, utc_committed_at_ms) VALUES(?, ?)",
        commit_ids)
    conn.executemany(
        "INSERT INTO selection_events(event_id, commit_id,"
        " event_format_version, schema_id, canonical_segment_input,"
        " span_start, span_end, category, preceding_text,"
        " competition_complete, final_selection_text, confirmation_source,"
        " trigger_keycode, display_rank, display_page, session_id,"
        " session_seq, hlc_physical_ms, hlc_logical, utc_confirmed_at_ms,"
        " utc_committed_at_ms)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        events)
    conn.executemany(
        "INSERT INTO selection_candidates(event_id, merge_order, text)"
        " VALUES(?, ?, ?)", candidates)
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'hlc_physical_ms';",
        (str(BASE_PHYSICAL_MS + event_count),))
    conn.commit()
    conn.close()
    # Owner-only perms per the privacy contract: the fact root is 0700 and
    # the database file 0600 (mirrors the live store; the daemon's fact
    # handle fails closed otherwise).  The maintenance.lock advisory lease
    # file is created by the C++ recorder in production; the fixture creates
    # it so the daemon's read-only fact handle can acquire its shared lease.
    os.chmod(db_path, 0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = db_path + suffix
        if os.path.exists(sidecar):
            os.chmod(sidecar, 0o600)
    lock_path = os.path.join(root, "maintenance.lock")
    with open(lock_path, "w", encoding="utf-8") as handle:
        handle.write("")
    os.chmod(lock_path, 0o600)

    sha256 = _sha256_file(db_path)
    summary = {
        "fixture_version": FIXTURE_VERSION,
        "kind": kind,
        "seed": seed,
        "event_count": event_count,
        "distinct_keys": len(key_counts),
        "max_key_count": max(key_counts.values()),
        "min_key_count": min(key_counts.values()) if kind == "freq" else None,
        "zipf_exponent": ZIPF_EXPONENT if kind == "freq" else None,
        "distinct_keys_target": DISTINCT_KEYS if kind == "freq" else 1,
        "facts_sha256": sha256,
        "facts_path": db_path,
        "hlc_physical_ms": BASE_PHYSICAL_MS + event_count,
        "hlc_logical": 0,
        "vector_rule": "seed-vectors-v1:splitmix64:l2",
        "window_chars": 64,
    }
    return summary


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True,
                        help="parent dir; creates <output>/freq and "
                             "<output>/hotkey facts roots")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENTS)
    parser.add_argument("--summary", default=None,
                        help="JSON file to write the summary (default: "
                             "<output>/100k-fixtures-summary.json)")
    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    summaries = {}
    for kind in ("freq", "hotkey"):
        root = os.path.join(args.output, kind)
        summaries[kind] = build_fixture_facts(
            root, kind, seed=args.seed, event_count=args.events)
        print("%s: %d events, %d keys, facts sha256 %s" % (
            kind, args.events, summaries[kind]["distinct_keys"],
            summaries[kind]["facts_sha256"]))
    summary_path = args.summary or os.path.join(
        args.output, "100k-fixtures-summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump({"version": FIXTURE_VERSION, "fixtures": summaries},
                  handle, ensure_ascii=False, sort_keys=True, indent=2)
    print("summary written: %s" % summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
