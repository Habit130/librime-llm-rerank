#!/usr/bin/env python3
"""Read-only acquisition tests for the #175 dataset freeze (DATA-1).

Pins the one-successful-Online-Backup state machine, explicit failed
attempts, frozen-identity immutability, source metadata continuity,
service-health unknowns, and the fail-closed config/schema guards.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import personal_lora_data as pld  # noqa: E402
from personal_lora_fixture import SyntheticSource, write_config  # noqa: E402


class PersonalLoraAcquisitionTest(unittest.TestCase):

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

    def config(self, source, **extra):
        root = tempfile.mkdtemp(prefix="personal_lora_root_")
        self.roots.append(root)
        path = os.path.join(root, "config.json")
        write_config(path, source.db_path, root, **extra)
        return root, pld.load_config(path)

    def records(self, source, count=5):
        for index in range(count):
            source.add_event("e%d" % index, session_seq=index + 1,
                             preceding_text="ctx%d" % index,
                             final_selection_text="w%d" % index,
                             hlc=(2000 + index * 10, 0))

    def test_backup_is_read_only_and_binds_identity(self):
        source = self.source()
        self.records(source)
        before_bytes = pld.sha256_file(source.db_path)
        before_mtime = os.stat(source.db_path).st_mtime_ns
        root, config = self.config(source)
        result = pld.acquire_snapshot(config)
        snapshot = result["snapshot"]
        self.assertEqual(pld.sha256_file(source.db_path), before_bytes)
        self.assertEqual(os.stat(source.db_path).st_mtime_ns, before_mtime)
        self.assertEqual(snapshot["integrity"], "ok")
        self.assertEqual(snapshot["identity"]["history_id"],
                         "synthetic-history")
        self.assertEqual(snapshot["identity"]["store_epoch"],
                         "synthetic-epoch")
        self.assertEqual(snapshot["counts"]["selection_events"], 5)
        validated = pld.validate_snapshot(
            os.path.join(root, pld.SNAPSHOT_REL))
        self.assertEqual(validated["sha256"], snapshot["sha256"])
        state = pld.load_state(root)
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["attempts"][0]["status"], "succeeded")
        self.assertEqual(state["success"]["sha256"], snapshot["sha256"])
        continuity = snapshot["source_observations"]["continuity"]
        self.assertTrue(all(continuity.values()))

    def test_failed_attempt_is_explicit_and_retry_succeeds(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)
        real_backup = pld.perform_backup
        calls = {"count": 0}

        def flaky(source_path, target_path):
            calls["count"] += 1
            if calls["count"] == 1:
                raise pld.AcquisitionError("injected")
            return real_backup(source_path, target_path)

        with mock.patch.object(pld, "perform_backup", side_effect=flaky):
            with self.assertRaises(pld.AcquisitionError):
                pld.acquire_snapshot(config)
        state = pld.load_state(root)
        self.assertEqual([attempt["status"] for attempt in state["attempts"]],
                         ["failed"])
        self.assertIsNone(state["success"])
        self.assertFalse(os.path.exists(
            os.path.join(root, pld.SNAPSHOT_REL)))
        result = pld.acquire_snapshot(config)
        self.assertFalse(result["acquisition"]["reused_frozen_snapshot"])
        self.assertEqual(result["acquisition"]["successful_attempt"], 2)
        state = pld.load_state(root)
        self.assertEqual([attempt["status"] for attempt in state["attempts"]],
                         ["failed", "succeeded"])

    def test_frozen_snapshot_is_reused_never_replaced(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)
        first = pld.acquire_snapshot(config)
        mtime = os.stat(os.path.join(root, pld.SNAPSHOT_REL)).st_mtime_ns
        second = pld.acquire_snapshot(config)
        self.assertTrue(second["acquisition"]["reused_frozen_snapshot"])
        self.assertEqual(second["snapshot"]["sha256"], first["snapshot"]["sha256"])
        self.assertEqual(os.stat(os.path.join(
            root, pld.SNAPSHOT_REL)).st_mtime_ns, mtime)
        self.assertEqual(len(pld.load_state(root)["attempts"]), 1)

    def test_missing_frozen_snapshot_refuses_silent_reacquisition(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)
        pld.acquire_snapshot(config)
        os.unlink(os.path.join(root, pld.SNAPSHOT_REL))
        with self.assertRaises(pld.AcquisitionError):
            pld.acquire_snapshot(config)

    def test_source_epoch_change_fails_continuity(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)
        real = pld.read_source_observation
        calls = {"count": 0}

        def wrapped(connection, path):
            observation = real(connection, path)
            calls["count"] += 1
            if calls["count"] == 2:
                observation = dict(observation, store_epoch="other-epoch")
            return observation

        with mock.patch.object(pld, "read_source_observation",
                               side_effect=wrapped):
            with self.assertRaises(pld.AcquisitionError):
                pld.acquire_snapshot(config)
        state = pld.load_state(root)
        self.assertEqual(state["attempts"][0]["status"], "failed")
        self.assertIsNone(state["success"])

    def test_high_water_regression_fails_continuity(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)
        real = pld.read_source_observation
        calls = {"count": 0}

        def wrapped(connection, path):
            observation = real(connection, path)
            calls["count"] += 1
            if calls["count"] == 2:
                observation = dict(observation, high_water=[1, 0])
            return observation

        with mock.patch.object(pld, "read_source_observation",
                               side_effect=wrapped):
            with self.assertRaises(pld.AcquisitionError):
                pld.acquire_snapshot(config)
        self.assertIsNone(pld.load_state(root)["success"])

    def test_health_timeout_is_unknown_not_a_failure(self):
        source = self.source()
        self.records(source)
        root = tempfile.mkdtemp(prefix="personal_lora_root_")
        self.roots.append(root)
        script = os.path.join(root, "health.sh")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nsleep 5\n")
        os.chmod(script, 0o700)
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root, status_cli=script,
                     status_timeout_seconds=0.2)
        result = pld.acquire_snapshot(pld.load_config(config_path))
        health = result["source_observations"]["health"]
        self.assertEqual(health["before"]["state"], "unknown")
        self.assertEqual(health["before"]["reason"], "status_cli_timeout")
        self.assertEqual(health["after"]["state"], "unknown")
        self.assertEqual(result["snapshot"]["integrity"], "ok")

    def test_unhealthy_status_is_recorded_but_not_corruption(self):
        source = self.source()
        self.records(source)
        root = tempfile.mkdtemp(prefix="personal_lora_root_")
        self.roots.append(root)
        script = os.path.join(root, "health.sh")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nprintf '%s' '{\"facts\":"
                         "{\"snapshot_ok\":false,\"recording_gaps\":"
                         "{\"state\":\"gap\"},\"total_events\":5}}'\n")
        os.chmod(script, 0o700)
        config_path = os.path.join(root, "config.json")
        write_config(config_path, source.db_path, root, status_cli=script)
        result = pld.acquire_snapshot(pld.load_config(config_path))
        health = result["source_observations"]["health"]["before"]
        self.assertEqual(health["state"], "unhealthy")
        self.assertEqual(health["gap_state"], "gap")
        self.assertEqual(result["snapshot"]["integrity"], "ok")

    def test_corrupt_backup_fails_validation_and_records_attempt(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)

        def corrupt(source_path, target_path):
            with open(target_path, "wb") as handle:
                handle.write(b"not a sqlite database")

        with mock.patch.object(pld, "perform_backup", side_effect=corrupt):
            with self.assertRaises(pld.AcquisitionError):
                pld.acquire_snapshot(config)
        state = pld.load_state(root)
        self.assertEqual(state["attempts"][0]["status"], "failed")
        self.assertIsNone(state["success"])
        self.assertFalse(os.path.exists(
            os.path.join(root, pld.SNAPSHOT_REL)))

    def test_foreign_key_violation_blocks_the_snapshot(self):
        source = self.source()
        self.records(source)
        source.connection.execute("DELETE FROM commits")
        source.connection.commit()
        root, config = self.config(source)
        with self.assertRaises(pld.AcquisitionError):
            pld.acquire_snapshot(config)
        self.assertIsNone(pld.load_state(root)["success"])

    def test_expected_schema_version_mismatch_fails_before_backup(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source, expected_fact_schema_version=99)
        with self.assertRaises(pld.SourceSchemaError):
            pld.acquire_snapshot(config)
        state = pld.load_state(root)
        self.assertEqual(state["attempts"][0]["status"], "failed")
        self.assertEqual(state["attempts"][0]["reason"], "SourceSchemaError")

    def test_wal_mode_source_snapshot_validates(self):
        source = self.source()
        self.records(source)
        source.connection.execute("PRAGMA journal_mode=WAL;")
        source.connection.execute(
            "INSERT INTO meta(key, value) VALUES('wal-probe', '1')")
        source.connection.commit()
        self.assertEqual(
            source.connection.execute("PRAGMA journal_mode").fetchone()[0],
            "wal")
        root, config = self.config(source)
        result = pld.acquire_snapshot(config)
        self.assertEqual(result["snapshot"]["integrity"], "ok")
        self.assertEqual(result["snapshot"]["counts"]["selection_events"], 5)
        audit = pld.load_event_audit(os.path.join(
            root, pld.SNAPSHOT_REL))
        self.assertEqual(audit.samples, 5)

    def test_corrupt_state_fails_closed(self):
        source = self.source()
        self.records(source)
        root, config = self.config(source)
        os.makedirs(os.path.join(root, "acquisition"), mode=0o700)
        with open(os.path.join(root, pld.STATE_REL), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(pld.AcquisitionError):
            pld.acquire_snapshot(config)

    def test_config_rejects_unknown_keys_and_bad_values(self):
        source = self.source()
        root = tempfile.mkdtemp(prefix="personal_lora_root_")
        self.roots.append(root)
        path = write_config(os.path.join(root, "config.json"),
                            source.db_path, root, surprise=True)
        with self.assertRaises(pld.PersonalLoraDataError):
            pld.load_config(path)
        path = write_config(os.path.join(root, "config.json"),
                            source.db_path, root,
                            status_timeout_seconds="slow")
        with self.assertRaises(pld.PersonalLoraDataError):
            pld.load_config(path)
        with open(os.path.join(root, "config.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"artifact_root": root}, handle)
        with self.assertRaises(pld.PersonalLoraDataError):
            pld.load_config(os.path.join(root, "config.json"))


if __name__ == "__main__":
    unittest.main()
