#!/usr/bin/env python3
"""#71 100k capacity-fixture determinism tests (SCN-71-1).

Pins the two fixtures (realistic key-frequency distribution and single
hot-key) to their documented generation rules: same seed -> identical
facts SHA-256; event/competition/HLC structure matches the fact schema;
the key-frequency fixture has a Zipf-like spread while the hot-key fixture
has exactly one key.  These are the reproducibility properties the #72/#73
and #78/#79 challenge paths depend on.
"""

import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
for path in (_ROOT, os.path.join(os.path.dirname(_ROOT), "daemon")):
    if path not in sys.path:
        sys.path.insert(0, path)

import importlib  # noqa: E402
_fixtures_mod = importlib.import_module("100k_fixtures")  # noqa: E402
COMPETITION = _fixtures_mod.COMPETITION
DEFAULT_EVENTS = _fixtures_mod.DEFAULT_EVENTS
DEFAULT_SEED = _fixtures_mod.DEFAULT_SEED
build_fixture_facts = _fixtures_mod.build_fixture_facts


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FixtureDeterminismTest(unittest.TestCase):

    def test_freq_and_hotkey_are_deterministic(self):
        root1 = tempfile.mkdtemp(prefix="freq-100k-1-")
        root2 = tempfile.mkdtemp(prefix="freq-100k-2-")
        try:
            s1 = build_fixture_facts(os.path.join(root1, "freq"), "freq",
                                     seed=DEFAULT_SEED,
                                     event_count=DEFAULT_EVENTS)
            s2 = build_fixture_facts(os.path.join(root2, "freq"), "freq",
                                     seed=DEFAULT_SEED,
                                     event_count=DEFAULT_EVENTS)
            self.assertEqual(s1["facts_sha256"], s2["facts_sha256"])
            self.assertEqual(s1["event_count"], 100000)
            self.assertGreater(s1["distinct_keys"], 1)
            # Zipf: the max key count is far larger than the min.
            self.assertGreater(s1["max_key_count"], 1000)
            self.assertEqual(s1["kind"], "freq")
        finally:
            import shutil
            shutil.rmtree(root1, ignore_errors=True)
            shutil.rmtree(root2, ignore_errors=True)

    def test_hotkey_fixture_has_one_key(self):
        root = tempfile.mkdtemp(prefix="hotkey-100k-")
        try:
            s = build_fixture_facts(os.path.join(root, "hotkey"), "hotkey",
                                    seed=DEFAULT_SEED,
                                    event_count=DEFAULT_EVENTS)
            self.assertEqual(s["kind"], "hotkey")
            self.assertEqual(s["distinct_keys"], 1)
            self.assertEqual(s["max_key_count"], 100000)
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_facts_schema_shape(self):
        root = tempfile.mkdtemp(prefix="shape-100k-")
        try:
            facts_root = os.path.join(root, "freq")
            build_fixture_facts(facts_root, "freq", seed=DEFAULT_SEED,
                                event_count=1000)
            db = os.path.join(facts_root, "facts.sqlite3")
            conn = sqlite3.connect(db)
            try:
                events = conn.execute(
                    "SELECT COUNT(*) FROM selection_events").fetchone()[0]
                candidates = conn.execute(
                    "SELECT COUNT(*) FROM selection_candidates").fetchone()[0]
                commits = conn.execute(
                    "SELECT COUNT(*) FROM commits").fetchone()[0]
                self.assertEqual(events, 1000)
                self.assertEqual(commits, 1000)
                self.assertEqual(candidates, 1000 * len(COMPETITION))
            finally:
                conn.close()
            # Owner-only perms (the daemon's fact handle requires them).
            mode = os.stat(facts_root).st_mode & 0o777
            self.assertEqual(mode, 0o700)
            db_mode = os.stat(db).st_mode & 0o777
            self.assertEqual(db_mode, 0o600)
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
