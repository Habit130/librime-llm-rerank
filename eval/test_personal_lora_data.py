#!/usr/bin/env python3
"""Eligibility, audit, export and privacy tests for the #175 dataset freeze.

Pins AC-175-v1 DATA-2 (event, retraction, duplicate and causal-text rules;
training vs ranking eligibility) and the private/public output boundary of
DATA-4/DATA-5 on synthetic facts only.
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

SENTINEL = "PRIVATE_SENTINEL_测试词"


class PersonalLoraEligibilityTest(unittest.TestCase):

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

    def audit(self, source):
        return pld.load_event_audit(source.db_path)

    def export(self, source, **config_extra):
        root = self.root()
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root, **config_extra)
        manifest = pld.run_freeze(config_path, allowed_root=root,
                                  protected_roots=[])
        return root, manifest

    def test_incomplete_competition_trains_but_only_small_groups_rank(self):
        source = self.source()
        source.add_event("small", competition=("甲", "乙"), final_selection_text="甲")
        source.add_event("window", competition=tuple("候%d" % index
                                                     for index in range(31))
                         + ("甲",), final_selection_text="甲")
        audit = self.audit(source)
        self.assertEqual(audit.samples, 2)
        eligible = {event.event_id: event.ranking_eligible
                    for event in audit.events}
        self.assertTrue(eligible["small"])
        self.assertFalse(eligible["window"])
        self.assertEqual(audit.ranking_ineligible_by_reason,
                         {"group_at_or_above_window": 1})

    def test_retraction_excludes_event_including_immediate_retraction(self):
        source = self.source()
        source.add_event("retracted", commit_id="c1", hlc=(2000, 0))
        source.retract("c1", hlc=(2000, 0))
        source.add_event("active", commit_id="c2", hlc=(3000, 0))
        audit = self.audit(source)
        self.assertEqual([event.event_id for event in audit.events], ["active"])
        self.assertEqual(audit.excluded_by_reason, {"retracted": 1})

    def test_empty_context_is_a_valid_counted_stratum(self):
        source = self.source()
        source.add_event("empty", preceding_text="", final_selection_text="我",
                         competition=("我", "你"))
        audit = self.audit(source)
        self.assertEqual(audit.samples, 1)
        self.assertEqual(audit.empty_context_samples, 1)
        self.assertTrue(audit.events[0].ranking_eligible)
        self.assertEqual(audit.excluded_by_reason, {})

    def test_missing_target_is_excluded(self):
        source = self.source()
        source.add_event("no-target", final_selection_text="")
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.excluded_by_reason, {"missing_target": 1})

    def test_overlong_stored_context_is_a_data_fault(self):
        source = self.source()
        source.add_event("long", preceding_text="上" * 65)
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.excluded_by_reason, {"overlong_context": 1})
        self.assertEqual(audit.data_faults_by_reason, {"overlong_context": 1})
        self.assertEqual(audit.missing_field_counts, {})

    def test_conflicting_duplicate_event_id_is_a_fault(self):
        source = self.source(primary_key=False)
        source.add_event("dup", session_seq=1, final_selection_text="甲")
        source.add_event("dup", session_seq=2, final_selection_text="乙",
                         hlc=(1010, 0))
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.excluded_by_reason,
                         {"conflicting_duplicate_event_id": 2})
        self.assertEqual(audit.data_faults_by_reason,
                         {"conflicting_duplicate_event_id": 2})

    def test_identical_duplicate_event_id_collapses_to_one_sample(self):
        source = self.source(primary_key=False)
        source.add_event("dup", commit_id="c1", session_seq=1,
                         final_selection_text="甲", competition=("甲", "乙"),
                         hlc=(1010, 0))
        source.add_event("dup", commit_id="c1", session_seq=1,
                         final_selection_text="甲", competition=("甲", "乙"),
                         hlc=(1010, 0))
        audit = self.audit(source)
        self.assertEqual(audit.samples, 1)
        self.assertEqual(audit.duplicates_collapsed, 1)
        self.assertEqual(audit.excluded_by_reason, {})

    def test_capture_duplicate_vs_repeated_choice(self):
        source = self.source()
        source.add_event("capture-a", session_id="s1", session_seq=1,
                         final_selection_text="甲", preceding_text="上文",
                         canonical_segment_input="wo")
        source.add_event("capture-b", session_id="s1", session_seq=1,
                         final_selection_text="甲", preceding_text="上文",
                         canonical_segment_input="wo", hlc=(1010, 0))
        source.add_event("repeat", session_id="s2", session_seq=1,
                         final_selection_text="甲", preceding_text="上文",
                         hlc=(1020, 0))
        audit = self.audit(source)
        self.assertEqual(audit.samples, 2)
        self.assertEqual(audit.duplicates_collapsed, 1)
        self.assertEqual({event.event_id for event in audit.events},
                         {"capture-a", "repeat"})

    def test_capture_conflict_on_confirmation_source_is_a_fault(self):
        source = self.source()
        source.add_event("dup-a", session_id="s1", session_seq=1,
                         final_selection_text="甲", preceding_text="上文",
                         canonical_segment_input="wo")
        source.add_event("dup-b", session_id="s1", session_seq=1,
                         final_selection_text="甲", preceding_text="上文",
                         canonical_segment_input="wo",
                         confirmation_source="auto_commit", hlc=(1010, 0))
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.data_faults_by_reason,
                         {"conflicting_duplicate_capture": 2})

    def test_target_membership_is_independent_of_training_admission(self):
        source = self.source()
        source.add_event("absent", competition=("甲", "乙"),
                         final_selection_text="丙")
        audit = self.audit(source)
        self.assertEqual(audit.samples, 1)
        self.assertFalse(audit.events[0].ranking_eligible)
        self.assertEqual(audit.ranking_ineligible_by_reason,
                         {"target_not_in_competition": 1})

    def test_group_complete_convention_ignores_persisted_bit(self):
        source = self.source()
        source.add_event("marked", competition=tuple("候%d" % index
                                                     for index in range(10)),
                         final_selection_text="候0",
                         competition_complete=True)
        source.add_event("unmarked", competition=tuple("候%d" % index
                                                       for index in range(32)),
                         final_selection_text="候0",
                         competition_complete=False)
        audit = self.audit(source)
        eligible = {event.event_id: event.ranking_eligible
                    for event in audit.events}
        self.assertTrue(eligible["marked"])
        self.assertFalse(eligible["unmarked"])

    def test_non_explicit_and_non_word_events_are_excluded(self):
        source = self.source()
        source.add_event("auto", confirmation_source="auto_commit")
        source.add_event("sentence", category="sentence")
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.excluded_by_reason,
                         {"not_explicit_confirmation": 1,
                          "not_word_category": 1})

    def test_non_luna_pinyin_schema_is_excluded(self):
        source = self.source()
        source.add_event("other-schema", schema_id="cangjie")
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.excluded_by_reason,
                         {"not_supported_schema": 1})

    def test_orphan_commit_is_a_fault(self):
        source = self.source()
        source.add_event("orphan", commit_id="ghost")
        source.connection.execute("DELETE FROM commits")
        source.connection.commit()
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.data_faults_by_reason, {"orphan_commit": 1})

    def test_invalid_span_is_a_fault(self):
        source = self.source()
        source.add_event("span", span_start=2, span_end=2)
        audit = self.audit(source)
        self.assertEqual(audit.samples, 0)
        self.assertEqual(audit.data_faults_by_reason, {"invalid_span": 1})

    def test_empty_candidate_list_trains_but_cannot_rank(self):
        source = self.source()
        source.add_event("no-group", competition=(), final_selection_text="甲")
        audit = self.audit(source)
        self.assertEqual(audit.samples, 1)
        self.assertFalse(audit.events[0].ranking_eligible)
        self.assertEqual(audit.ranking_ineligible_by_reason,
                         {"invalid_candidate_data": 1})


class PersonalLoraExportTest(PersonalLoraEligibilityTest):

    def test_export_writes_partitions_and_manifest(self):
        source = self.source()
        for index in range(10):
            source.add_event("e%d" % index, preceding_text="上%d" % index,
                             final_selection_text="词%d" % index,
                             competition=("词%d" % index, "别"),
                             session_id="s1", session_seq=index + 1,
                             hlc=(2000 + index * 10, 0))
        root, manifest = self.export(source)
        self.assertEqual(manifest["terminal"], "dataset_frozen")
        total = sum(part["events"] for part in
                    manifest["splits"]["parts"].values())
        self.assertEqual(total, 10)
        for name in pld.PARTITIONS:
            records = read_partition(root, name)
            self.assertEqual(len(records), manifest["splits"]["parts"][name]["events"])
            for record in records:
                self.assertEqual(record["schema"], pld.DATASET_SCHEMA)
                self.assertEqual(record["loss"], pld.LOSS_BOUNDARY_INTENT)
                self.assertEqual(record["provenance"]["partition"], name)
                self.assertRegex(record["prompt"], r"^上\d$")
        manifest_path = os.path.join(root, "dataset", "manifest.json")
        with open(manifest_path, encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored["terminal"], "dataset_frozen")
        self.assertIn("rules", stored["audit"])

    def test_raw_text_never_reaches_console_report_or_manifest(self):
        source = self.source()
        for index in range(10):
            source.add_event("e%d" % index,
                             preceding_text=SENTINEL,
                             final_selection_text=SENTINEL,
                             competition=(SENTINEL, "别"))
        root = self.root()
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = pld.main(["--config", config_path], allowed_root=root,
                            protected_roots=[])
        self.assertEqual(code, 0)
        self.assertNotIn(SENTINEL, stdout.getvalue())
        self.assertNotIn(SENTINEL, stderr.getvalue())
        self.assertNotIn(root, stdout.getvalue())
        for name in pld.PARTITIONS:
            records = read_partition(root, name)
            for record in records:
                self.assertEqual(record["prompt"], SENTINEL)
                self.assertEqual(record["completion"], SENTINEL)
        with open(os.path.join(root, pld.PUBLIC_REPORT_REL),
                  encoding="utf-8") as handle:
            report = handle.read()
        self.assertNotIn(SENTINEL, report)
        self.assertNotIn(root, report)
        self.assertNotIn("event-", report)
        with open(os.path.join(root, pld.MANIFEST_REL),
                  encoding="utf-8") as handle:
            manifest_text = handle.read()
        self.assertNotIn(SENTINEL, manifest_text)
        for index in range(10):
            self.assertNotIn('"e%d"' % index, manifest_text)

    def test_error_messages_do_not_echo_raw_text(self):
        source = self.source()
        source.add_event("fault", preceding_text=SENTINEL * 40)
        root = self.root()
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            pld.main(["--config", config_path], allowed_root=root,
                     protected_roots=[])
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(SENTINEL, combined)


if __name__ == "__main__":
    unittest.main()
