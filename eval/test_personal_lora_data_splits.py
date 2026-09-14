#!/usr/bin/env python3
"""Deterministic temporal freeze tests for the #175 dataset (DATA-3).

Pins whole-commit preservation, session-boundary preference, ordered
nonoverlapping boundaries, deterministic repeated export, overlap reporting
and the ``needs_owner_decision`` legal outcome on synthetic facts.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_data as pld  # noqa: E402
from personal_lora_fixture import (SyntheticSource, read_partition,  # noqa: E402
                                   write_config)


class PersonalLoraSplitTest(unittest.TestCase):

    def setUp(self):
        self.sources = []
        self.roots = []

    def tearDown(self):
        for source in self.sources:
            source.close()
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def source(self, **kwargs):
        created = SyntheticSource(**kwargs)
        self.sources.append(created)
        return created

    def root(self):
        created = tempfile.mkdtemp(prefix="personal_lora_root_")
        self.roots.append(created)
        return created

    def export(self, source, root=None):
        root = root or self.root()
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root)
        manifest = pld.run_freeze(config_path, allowed_root=root,
                                  protected_roots=[])
        return root, manifest

    def add_sequential(self, source, count, session_size=None,
                       competition_for=None):
        for index in range(count):
            if session_size:
                session_id = "s%d" % (index // session_size)
                session_seq = (index % session_size) + 1
            else:
                session_id = "s1"
                session_seq = index + 1
            competition = (competition_for(index) if competition_for
                           else ("w%d" % index, "x"))
            source.add_event("e%03d" % index, session_id=session_id,
                             session_seq=session_seq,
                             preceding_text="ctx%d" % index,
                             final_selection_text="w%d" % index,
                             competition=competition,
                             hlc=(1000 + index * 10, 0))

    def test_deterministic_repeated_export_equality(self):
        source = self.source()
        self.add_sequential(source, 100)
        first_root, first = self.export(source)
        second_root, second = self.export(source)
        self.assertEqual(first["splits"]["rule"], second["splits"]["rule"])
        for name in pld.PARTITIONS:
            self.assertEqual(first["splits"]["parts"][name]["sha256"],
                             second["splits"]["parts"][name]["sha256"])
            with open(os.path.join(first_root, "dataset", "%s.jsonl" % name),
                      "rb") as handle:
                first_bytes = handle.read()
            with open(os.path.join(second_root, "dataset", "%s.jsonl" % name),
                      "rb") as handle:
                second_bytes = handle.read()
            self.assertEqual(first_bytes, second_bytes)

    def test_whole_commit_never_splits(self):
        source = self.source()
        index = 0
        while index < 60:
            commit_id = "commit-%d" % (index // 3)
            for offset in range(3):
                if index + offset >= 60:
                    break
                position = index + offset
                source.add_event("e%03d" % position, commit_id=commit_id,
                                 session_id="s%d" % (position // 10),
                                 session_seq=(position % 10) + 1,
                                 preceding_text="ctx%d" % position,
                                 final_selection_text="w%d" % position,
                                 hlc=(1000 + position * 10, 0))
            index += 3
        root, manifest = self.export(source)
        seen = {}
        for name in pld.PARTITIONS:
            for record in read_partition(root, name):
                commit_id = record["provenance"]["commit_id"]
                if commit_id in seen:
                    self.assertEqual(seen[commit_id], name,
                                     "commit %s spans partitions" % commit_id)
                seen[commit_id] = name
        self.assertEqual(manifest["splits"]["parts"]["train"]["events"], 48)
        self.assertGreaterEqual(manifest["splits"]["parts"]["validation"]["events"], 1)

    def test_session_boundary_preferred_when_nearby(self):
        source = self.source()
        self.add_sequential(source, 100, session_size=10)
        _, manifest = self.export(source)
        rule = manifest["splits"]["rule"]
        self.assertNotIn(False, [kind == "session_end"
                                 for kind in rule["chosen_kinds"]])
        self.assertEqual(rule["chosen"], [80, 90])
        self.assertEqual(rule["chosen_kinds"],
                         ["session_end", "session_end"])

    def test_commit_boundary_fallback_without_session_boundaries(self):
        source = self.source()
        self.add_sequential(source, 100)
        _, manifest = self.export(source)
        rule = manifest["splits"]["rule"]
        self.assertEqual(rule["chosen"], [80, 90])
        self.assertEqual(rule["chosen_kinds"],
                         ["commit_unit_end", "commit_unit_end"])

    def test_boundaries_are_ordered_and_disjoint(self):
        source = self.source()
        self.add_sequential(source, 100, session_size=10)
        root, manifest = self.export(source)
        boundaries = manifest["splits"]["boundaries"]
        self.assertLess(tuple(boundaries["train"]["last_hlc"]),
                        tuple(boundaries["validation"]["first_hlc"]))
        self.assertLess(tuple(boundaries["validation"]["last_hlc"]),
                        tuple(boundaries["test"]["first_hlc"]))
        identities = {}
        for name in pld.PARTITIONS:
            identities[name] = {record["provenance"]["event_id"]
                                for record in read_partition(root, name)}
        self.assertEqual(identities["train"] & identities["validation"],
                         set())
        self.assertEqual(identities["train"] & identities["test"], set())
        self.assertEqual(identities["validation"] & identities["test"],
                         set())
        self.assertEqual(sum(len(ids) for ids in identities.values()), 100)

    def test_train_overlap_counts_are_reported_separately(self):
        source = self.source()
        self.add_sequential(source, 100, session_size=10,
                            competition_for=lambda index: ("w%d" % index, "x"))
        source.connection.execute(
            "UPDATE selection_events SET preceding_text = 'ctx0',"
            " final_selection_text = 'w0' WHERE event_id = 'e080'")
        source.connection.execute(
            "UPDATE selection_events SET canonical_segment_input ="
            " (SELECT canonical_segment_input FROM selection_events"
            " WHERE event_id = 'e000') WHERE event_id = 'e080'")
        source.connection.commit()
        _, manifest = self.export(source)
        seen = manifest["splits"]["parts"]["validation"]["seen_in_train"]
        self.assertGreaterEqual(seen["exact_context_target"], 1)
        self.assertGreaterEqual(seen["choice_key"], 1)
        self.assertEqual(seen["exact_context_target_total"], 10)

    def test_sessions_spanning_partitions_reported(self):
        source = self.source()
        self.add_sequential(source, 100, session_size=10)
        _, manifest = self.export(source)
        self.assertEqual(manifest["splits"]["sessions_spanning_partitions"], 0)
        source2 = self.source()
        self.add_sequential(source2, 100)
        _, manifest2 = self.export(source2)
        self.assertEqual(manifest2["splits"]["sessions_spanning_partitions"], 1)

    def test_empty_dataset_is_an_honest_decision_not_an_error(self):
        source = self.source()
        root, manifest = self.export(source)
        self.assertEqual(manifest["terminal"], "needs_owner_decision")
        self.assertIn("no_eligible_samples", manifest["terminal_reasons"])
        self.assertEqual(manifest["audit"]["samples"], 0)
        for name in pld.PARTITIONS:
            self.assertTrue(os.path.isfile(
                os.path.join(root, "dataset", "%s.jsonl" % name)))
        result = pld.verify_freeze(os.path.join(root, pld.MANIFEST_REL))
        self.assertEqual(result["failures"], [])

    def test_empty_partition_returns_needs_owner_decision(self):
        source = self.source()
        self.add_sequential(source, 4)
        root = self.root()
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = pld.main(["--config", config_path], allowed_root=root,
                            protected_roots=[])
        self.assertEqual(code, 2)
        self.assertIn("needs_owner_decision", stdout.getvalue())
        with open(os.path.join(root, pld.MANIFEST_REL),
                  encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("empty_test_partition", manifest["terminal_reasons"])

    def test_unevaluable_validation_returns_needs_owner_decision(self):
        source = self.source()
        window = tuple("候%d" % index for index in range(32))
        for index in range(10):
            source.add_event("e%d" % index, session_id="s1",
                             session_seq=index + 1,
                             preceding_text="ctx%d" % index,
                             final_selection_text="候0",
                             competition=window, hlc=(1000 + index * 10, 0))
        _, manifest = self.export(source)
        self.assertEqual(manifest["terminal"], "needs_owner_decision")
        self.assertIn("no_ranking_eligible_validation",
                      manifest["terminal_reasons"])
        self.assertIn("no_ranking_eligible_test",
                      manifest["terminal_reasons"])

    def test_noncontiguous_commit_is_a_data_fault(self):
        source = self.source()
        source.add_event("e1", commit_id="c1", session_seq=1, hlc=(1000, 0))
        source.add_event("e2", commit_id="c2", session_seq=2, hlc=(1010, 0))
        source.add_event("e3", commit_id="c1", session_seq=3, hlc=(1020, 0))
        audit = pld.load_event_audit(source.db_path)
        with self.assertRaises(pld.DataFaultError):
            pld.plan_splits(audit.events)

    def test_data_faults_block_a_successful_terminal(self):
        source = self.source()
        self.add_sequential(source, 10)
        source.add_event("fault", preceding_text="上" * 65, session_id="s1",
                         session_seq=11, hlc=(2000, 0))
        root, manifest = self.export(source)
        self.assertEqual(manifest["terminal"], "needs_owner_decision")
        self.assertIn("data_faults_present", manifest["terminal_reasons"])
        result = pld.verify_freeze(os.path.join(root, pld.MANIFEST_REL))
        self.assertEqual(result["failures"], [])

    def test_split_rule_and_proportions_recorded(self):
        source = self.source()
        self.add_sequential(source, 100, session_size=10)
        _, manifest = self.export(source)
        parts = manifest["splits"]["parts"]
        self.assertEqual(parts["train"]["proportion"], 0.8)
        self.assertEqual(parts["validation"]["proportion"], 0.1)
        self.assertEqual(parts["test"]["proportion"], 0.1)
        rule = manifest["splits"]["rule"]
        self.assertEqual(rule["train_fraction"], 0.8)
        self.assertEqual(rule["validation_fraction"], 0.1)
        self.assertTrue(rule["whole_commit_preserved"])
        self.assertEqual(rule["tie_break"],
                         "smallest_absolute_deviation_then_earlier_position")


if __name__ == "__main__":
    unittest.main()
