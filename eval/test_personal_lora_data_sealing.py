#!/usr/bin/env python3
"""Sealing, immutability and privacy tests for the #175 dataset (DATA-4).

Pins owner-only storage, artifact-root isolation (including symlink
aliases), refusal to overwrite or rebind a successful freeze, verify-only
tamper detection, read-only verification and the desensitized public report.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_data as pld  # noqa: E402
from personal_lora_fixture import SyntheticSource, write_config  # noqa: E402


class PersonalLoraSealingTest(unittest.TestCase):

    def setUp(self):
        self.sources = []
        self.roots = []

    def tearDown(self):
        for source in self.sources:
            source.close()
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def source(self):
        created = SyntheticSource()
        self.sources.append(created)
        for index in range(10):
            created.add_event("evtid-%d" % index, session_id="s1",
                              session_seq=index + 1,
                              preceding_text="ctx%d" % index,
                              final_selection_text="w%d" % index,
                              competition=("w%d" % index, "x"),
                              hlc=(2000 + index * 10, 0))
        return created

    def root(self):
        created = tempfile.mkdtemp(prefix="personal_lora_root_")
        self.roots.append(created)
        return created

    def export(self, source=None):
        source = source or self.source()
        root = self.root()
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root)
        manifest = pld.run_freeze(config_path, allowed_root=root,
                                  protected_roots=[])
        return root, manifest

    def entries(self, root):
        found = []
        for directory, dirnames, filenames in os.walk(root):
            for name in dirnames + filenames:
                found.append(os.path.join(directory, name))
        return found

    def test_artifact_root_outside_allowed_root_is_refused(self):
        allowed = self.root()
        outside = self.root()
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(outside, allowed_root=allowed,
                                     protected_roots=[])

    def test_artifact_root_in_protected_location_is_refused(self):
        protected = self.root()
        nested = os.path.join(protected, "dataset-root")
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(nested, allowed_root=self.root(),
                                     protected_roots=[protected])

    def test_symlink_alias_to_protected_location_is_refused(self):
        protected = self.root()
        allowed = self.root()
        alias = os.path.join(allowed, "alias")
        os.symlink(protected, alias)
        with self.assertRaises(pld.IsolationError):
            pld.assert_artifact_root(os.path.join(alias, "root"),
                                     allowed_root=allowed,
                                     protected_roots=[protected])

    def test_symlinked_artifact_subdirectory_is_refused(self):
        root = self.root()
        outside = self.root()
        os.symlink(outside, os.path.join(root, "dataset"))
        with self.assertRaises(pld.IsolationError):
            pld.private_write_bytes(root, "dataset/train.jsonl", b"data")

    def test_symlinked_target_file_is_refused(self):
        root = self.root()
        target = os.path.join(root, "manifest.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{}")
        link = os.path.join(root, "link.json")
        os.symlink(target, link)
        with self.assertRaises(pld.IsolationError):
            pld.private_write_bytes(root, "link.json", b"data")

    def test_safe_target_rejects_escaping_relative_paths(self):
        root = self.root()
        for relative in ("../escape.json", "/absolute.json", "a/../b.json",
                         "a/./b.json", "", "a//b.json"):
            with self.assertRaises(pld.IsolationError, msg=relative):
                pld.safe_target(root, relative)

    def test_existing_freeze_is_never_overwritten_or_rebound(self):
        source = self.source()
        root, manifest = self.export(source)
        manifest_path = os.path.join(root, pld.MANIFEST_REL)
        before = pld.sha256_file(manifest_path)
        config_path = os.path.join(root, "config.json")
        with self.assertRaises(pld.IsolationError):
            pld.run_freeze(config_path, allowed_root=root, protected_roots=[])
        self.assertEqual(pld.sha256_file(manifest_path), before)

    def test_verify_only_detects_tampered_split_file(self):
        root, _manifest = self.export()
        path = os.path.join(root, "dataset", "validation.jsonl")
        with open(path, "ab") as handle:
            handle.write(b"tampered\n")
        result = pld.verify_freeze(os.path.join(root, pld.MANIFEST_REL))
        self.assertTrue(any("sha256" in failure or "line count" in failure
                            for failure in result["failures"]))

    def test_verify_only_detects_tampered_snapshot(self):
        root, _manifest = self.export()
        snapshot_path = os.path.join(root, pld.SNAPSHOT_REL)
        with open(snapshot_path, "r+b") as handle:
            handle.seek(1024)
            original = handle.read(1)
            handle.seek(1024)
            handle.write(bytes([original[0] ^ 0xFF]))
        result = pld.verify_freeze(os.path.join(root, pld.MANIFEST_REL))
        self.assertTrue(any("snapshot" in failure
                            for failure in result["failures"]))

    def test_verify_only_is_read_only_and_passes(self):
        root, _manifest = self.export()
        before = {path: os.stat(path).st_mtime_ns
                  for path in self.entries(root)}
        result = pld.verify_freeze(os.path.join(root, pld.MANIFEST_REL))
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["summary"]["terminal"], "dataset_frozen")
        after = {path: os.stat(path).st_mtime_ns
                 for path in self.entries(root)}
        self.assertEqual(before, after)

    def test_owner_only_permissions_everywhere(self):
        root, _manifest = self.export()
        self.assertEqual(pld.verify_owner_only(root), [])

    def test_missing_manifest_fails_verification(self):
        root = self.root()
        result = pld.verify_freeze(os.path.join(root, "dataset",
                                                "manifest.json"))
        self.assertTrue(result["failures"])

    def test_public_report_is_desensitized(self):
        root, _manifest = self.export()
        with open(os.path.join(root, pld.PUBLIC_REPORT_REL),
                  encoding="utf-8") as handle:
            report = handle.read()
        self.assertIn("dataset_frozen", report)
        self.assertNotIn(root, report)
        self.assertNotIn("event_id", report)
        self.assertNotIn("choice_key_sha256", report)
        self.assertNotIn("path_sha256", report)
        self.assertNotIn("evtid-", report)
        self.assertIn("snapshot sha256", report)

    def test_verify_only_recomputes_split_metadata(self):
        root, _manifest = self.export()
        manifest_path = os.path.join(root, pld.MANIFEST_REL)
        with open(manifest_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["splits"]["parts"]["train"]["events"] = 999
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
        result = pld.verify_freeze(manifest_path)
        self.assertTrue(any("split metadata" in failure
                            for failure in result["failures"]))

    def test_verify_only_recomputes_terminal_decision(self):
        root, _manifest = self.export()
        manifest_path = os.path.join(root, pld.MANIFEST_REL)
        with open(manifest_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["terminal"] = "needs_owner_decision"
        payload["terminal_reasons"] = ["forged"]
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
        result = pld.verify_freeze(manifest_path)
        self.assertTrue(any("terminal" in failure
                            for failure in result["failures"]))


if __name__ == "__main__":
    unittest.main()
