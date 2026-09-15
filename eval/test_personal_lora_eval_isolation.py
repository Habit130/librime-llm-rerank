#!/usr/bin/env python3
"""Sealing, privacy and identity tests for the #178 evaluation runner.

These tests pin the contract's isolation rules: the sealed test partition is
parsed only after a matching policy lock exists, artifact roots stay inside
the ticket-owned location with owner-only permissions, private text never
reaches the public report or the default console, the identity manifest and
the policy lock are immutable, and an adapter or snapshot identity drift
fails closed.
"""

import builtins
import contextlib
import io
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
import personal_lora_eval as ple  # noqa: E402
from test_personal_lora_eval_runner import (  # noqa: E402
    EvalFixture, PRIVATE_SENTINEL, command_patches, fake_backend)


class IsolationTestCase(unittest.TestCase):

    def setUp(self):
        self.fixture = EvalFixture()

    def tearDown(self):
        self.fixture.cleanup()

    def rewrite_config(self, update):
        with open(self.fixture.config_path, encoding="utf-8") as handle:
            config = json.load(handle)
        config.update(update)
        with open(self.fixture.config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        os.chmod(self.fixture.config_path, 0o600)


class SealedPartitionTest(IsolationTestCase):

    def test_test_partition_guard(self):
        test_path = os.path.join(self.fixture.dataset_dir, "test.jsonl")
        with self.assertRaises(ple.LockError):
            ple.parse_split_rows(test_path, "test.jsonl")
        rows = ple.parse_split_rows(test_path, "test.jsonl",
                                    allow_sealed=True)
        self.assertEqual(len(rows), len(self.fixture.test_rows))

    def test_eval_test_fails_closed_before_touching_test_text(self):
        opened = []
        original_open = builtins.open

        def tracking_open(path, mode="r", *args, **kwargs):
            if os.path.abspath(str(path)).endswith("test.jsonl"):
                opened.append(mode)
            return original_open(path, mode, *args, **kwargs)

        with command_patches(self.fixture):
            with mock.patch.object(builtins, "open", tracking_open):
                with self.assertRaises(ple.LockError):
                    ple.cmd_eval_test(
                        self.fixture.config_path,
                        allowed_root=self.fixture.artifact_root,
                        backend=fake_backend())
        self.assertTrue(all(mode == "rb" for mode in opened),
                        "test.jsonl was opened in a text mode: %r" % opened)

    def test_invalid_test_json_cannot_block_the_policy_lock(self):
        fixture = EvalFixture(test_text="not json at all\n")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                status = fixture.select()
            self.assertEqual(status, 0)
            lock = fixture.read_artifact("policy_lock.json")
            self.assertEqual(lock["test_sha256"],
                             fixture.expected["test_sha256"])
        finally:
            fixture.cleanup()


class ArtifactBoundaryTest(IsolationTestCase):

    def test_live_location_alias_is_refused(self):
        live = os.path.join(self.fixture.root, "live", "Squirrel")
        os.makedirs(live, mode=0o700, exist_ok=True)
        alias = os.path.join(self.fixture.root, "alias")
        os.symlink(live, alias)
        self.rewrite_config({"artifact_root": alias})
        with command_patches(self.fixture):
            with self.assertRaises(pld.IsolationError):
                ple.cmd_select_policy(
                    self.fixture.config_path,
                    allowed_root=self.fixture.artifact_root,
                    protected_roots=[os.path.join(self.fixture.root, "live")],
                    backend=fake_backend())

    def test_artifact_root_outside_the_ticket_root_is_refused(self):
        outside = tempfile.mkdtemp(prefix="outside_")
        try:
            self.rewrite_config({"artifact_root": outside})
            with command_patches(self.fixture):
                with self.assertRaises(pld.IsolationError):
                    ple.cmd_select_policy(
                        self.fixture.config_path,
                        allowed_root=self.fixture.artifact_root,
                        backend=fake_backend())
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_owner_only_violation_is_refused(self):
        stray = os.path.join(self.fixture.artifact_root, "stray")
        os.makedirs(stray, mode=0o755, exist_ok=True)
        os.chmod(stray, 0o755)
        with command_patches(self.fixture):
            with self.assertRaises(ple.EvalError):
                ple.cmd_select_policy(
                    self.fixture.config_path,
                    allowed_root=self.fixture.artifact_root,
                    backend=fake_backend())

    def test_unknown_config_keys_fail_closed(self):
        self.rewrite_config({"extra_key": True})
        with self.assertRaises(ple.EvalError):
            ple.load_config(self.fixture.config_path)

    def test_private_outputs_are_owner_only(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.fixture.select()
            self.fixture.eval_test()
            self.fixture.latency()
        self.assertEqual(pld.verify_owner_only(self.fixture.artifact_root),
                         [])


class IdentityImmutabilityTest(IsolationTestCase):

    def test_changed_epoch_checkpoint_is_an_environment_blocker(self):
        with open(self.fixture.checkpoint_path, "wb") as handle:
            handle.write(b"a-different-checkpoint")
        os.chmod(self.fixture.checkpoint_path, 0o600)
        with command_patches(self.fixture):
            with self.assertRaises(ple.EnvironmentBlocker):
                ple.cmd_select_policy(
                    self.fixture.config_path,
                    allowed_root=self.fixture.artifact_root,
                    backend=fake_backend())

    def test_changed_adapter_is_an_environment_blocker(self):
        adapter_path = os.path.join(self.fixture.adapter_dir,
                                    "adapters.safetensors")
        with open(adapter_path, "wb") as handle:
            handle.write(b"another-adapter")
        os.chmod(adapter_path, 0o600)
        with command_patches(self.fixture):
            with self.assertRaises(ple.EnvironmentBlocker):
                ple.cmd_select_policy(
                    self.fixture.config_path,
                    allowed_root=self.fixture.artifact_root,
                    backend=fake_backend())

    def test_identity_manifest_is_written_once(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.fixture.select()
        identity_path = os.path.join(self.fixture.artifact_root,
                                     "identity.json")
        before = pld.sha256_file(identity_path)
        with contextlib.redirect_stdout(io.StringIO()):
            self.fixture.select()
        self.assertEqual(pld.sha256_file(identity_path), before)

    def test_identity_rebinding_is_refused(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.fixture.select()
        identity_path = os.path.join(self.fixture.artifact_root,
                                     "identity.json")
        with open(identity_path, encoding="utf-8") as handle:
            identity = json.load(handle)
        identity["binding"]["adapter_sha256"] = "0" * 64
        with open(identity_path, "w", encoding="utf-8") as handle:
            json.dump(identity, handle)
        os.chmod(identity_path, 0o600)
        with command_patches(self.fixture):
            with self.assertRaises(ple.EvalError):
                ple.cmd_select_policy(
                    self.fixture.config_path,
                    allowed_root=self.fixture.artifact_root,
                    backend=fake_backend())


class ReportBoundaryTest(IsolationTestCase):

    def test_report_has_no_absolute_private_paths_or_event_ids(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.fixture.select()
            self.fixture.eval_test()
        report = self.fixture.report_text()
        self.assertNotIn(self.fixture.root, report)
        self.assertNotIn("v0", report)
        self.assertNotIn("t0", report)
        self.assertNotIn(PRIVATE_SENTINEL, report)
        self.assertIn("Verdict", report)

    def test_sentinel_candidates_never_reach_the_report(self):
        fixture = EvalFixture(sentinel_candidates=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fixture.select()
                fixture.eval_test()
            self.assertNotIn(PRIVATE_SENTINEL, fixture.report_text())
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
