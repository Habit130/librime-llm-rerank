#!/usr/bin/env python3
"""CLI tests for `squirrel-semantic-memory` (Habit130/squirrel#52).

Subprocess tests run the real entry script with temporary roots; in-process
tests call cli.main() with the fixture operation type registered for the
internal `operation run` executor. All filesystem fixtures are isolated
temporary directories; the live Rime dir and the live facts root are never
touched.
"""

import contextlib
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import cli  # noqa: E402
from fixture_operations import fixture_spec  # noqa: E402
from operations import (  # noqa: E402
    OperationBlocked,
    OperationRegistry,
    OperationStore,
    create_operation,
    run_pending_steps,
)
from tracing import TraceStore  # noqa: E402

DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(DAEMON_DIR, "squirrel-semantic-memory")
MARKER = "PRIVATE_MARKER_上文_候选_embedding_%s" % "cli_secret"

SCHEMA = {
    "schema": {"schema_id": "alpha"},
    "engine": {"filters": ["uniquifier", "llm_rerank"],
               "processors": ["llm_rerank_recorder"]},
    "llm_rerank": {"reranking_enabled": True, "recording_enabled": True,
                   "evidence_enabled": False},
}


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_cli_")
        self.root = os.path.join(self._tmp, "sm")
        self.rime_dir = os.path.join(self._tmp, "rime")
        os.makedirs(os.path.join(self.rime_dir, "build"))
        self._old_env = dict(os.environ)
        os.environ["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = self.root
        os.environ["SQUIRREL_RIME_DIR"] = self.rime_dir
        os.environ["SQUIRREL_DAEMON_SOCKET"] = os.path.join(
            self._tmp, "missing.sock")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------

    def run_cli(self, *args, timeout=30):
        proc = subprocess.run(
            [sys.executable, ENTRY] + list(args),
            capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr

    def write_schema(self):
        with open(os.path.join(self.rime_dir, "default.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("config_version: \"0.1\"\n")
            f.write("schema_list:\n  - schema: alpha\n")
        with open(os.path.join(self.rime_dir, "build",
                               "alpha.schema.yaml"), "w",
                  encoding="utf-8") as f:
            json.dump(SCHEMA, f, ensure_ascii=False)

    def registry(self):
        registry = OperationRegistry()
        registry.register(fixture_spec())
        return registry

    def create_op(self, operation_id=None, **overrides):
        values = {"work_dir": os.path.join(self._tmp, "work"),
                  "private_label": MARKER, "sleep_s": 0}
        values.update(overrides)
        os.makedirs(values["work_dir"], exist_ok=True)
        return create_operation(OperationStore(self.root), self.registry(),
                                "fixture.maintenance", values,
                                operation_id=operation_id)

    def run_op(self, operation_id, **kwargs):
        return run_pending_steps(OperationStore(self.root), self.registry(),
                                 operation_id, **kwargs)

    # -- version ------------------------------------------------------------

    def test_version_human_and_json(self):
        rc, out, _ = self.run_cli("version")
        self.assertEqual(0, rc)
        self.assertIn("squirrel-semantic-memory 0.1.0", out)
        self.assertIn("status_version 2", out)
        self.assertIn("operation_version 1", out)
        rc, out, _ = self.run_cli("version", "--json")
        self.assertEqual(0, rc)
        payload = json.loads(out)
        self.assertEqual("squirrel-semantic-memory", payload["command"])
        self.assertEqual("0.1.0", payload["program_version"])
        self.assertEqual(2, payload["status_version"])
        self.assertEqual(1, payload["operation_version"])
        self.assertEqual(1, payload["event_version"])
        self.assertEqual(1, payload["error_version"])

    # -- status wiring ------------------------------------------------------

    def test_status_healthy_exit_zero(self):
        self.write_schema()
        rc, out, _ = self.run_cli("status")
        self.assertEqual(0, rc)
        self.assertIn("Semantic memory status", out)
        self.assertIn("alpha", out)
        rc, out, _ = self.run_cli("status", "--json")
        self.assertEqual(0, rc)
        report = json.loads(out)
        self.assertEqual(2, report["status_version"])
        self.assertTrue(report["snapshot_ok"])
        self.assertEqual("not_created", report["facts"]["health"])
        self.assertEqual("offline", report["serving"]["state"])
        self.assertIn("operation", report)
        self.assertIsNone(report["operation"])
        self.assertEqual(0, report["exit_code"])

    def test_status_schema_filter(self):
        self.write_schema()
        rc, out, _ = self.run_cli("status", "--schema", "alpha")
        self.assertEqual(0, rc)
        rc, out, _ = self.run_cli("status", "--schema", "nope", "--json")
        self.assertEqual(2, rc)
        report = json.loads(out)
        self.assertFalse(report["snapshot_ok"])
        self.assertEqual("unknown_schema", report["error"]["code"])

    def test_status_blocked_facts_is_exit_one(self):
        self.write_schema()
        os.makedirs(self.root)
        os.chmod(self.root, 0o755)
        rc, _, _ = self.run_cli("status")
        self.assertEqual(1, rc)

    def test_status_unreadable_rime_is_exit_two(self):
        rc, out, _ = self.run_cli("status", "--json")
        self.assertEqual(2, rc)
        report = json.loads(out)
        self.assertEqual("rime_dir_unavailable", report["error"]["code"])

    def test_status_operation_dimension_and_contributions(self):
        self.write_schema()
        op = self.create_op()
        # A queued operation is reported without hurting the exit code.
        rc, out, _ = self.run_cli("status", "--json")
        self.assertEqual(0, rc)
        report = json.loads(out)
        self.assertEqual(op["operation_id"],
                         report["operation"]["operation_id"])
        self.assertEqual("queued", report["operation"]["state"])
        self.assertEqual(0, report["exit_code"])
        # A cancelled (intentional) operation still exits 0.
        self.run_op(op["operation_id"], max_steps=1)
        self.run_cli("operation", "cancel", op["operation_id"])
        self.run_op(op["operation_id"])
        rc, out, _ = self.run_cli("status", "--json")
        report = json.loads(out)
        self.assertEqual("cancelled", report["operation"]["state"])
        self.assertEqual(0, report["exit_code"])
        # A blocked/failed latest operation pushes the exit code to 1.
        op2 = self.create_op(operation_id="op2")
        self.run_op(op2["operation_id"], fault_hook=self._block_hook())
        rc, out, _ = self.run_cli("status", "--json")
        report = json.loads(out)
        self.assertEqual("blocked", report["operation"]["state"])
        self.assertEqual(1, report["exit_code"])

    def test_status_unreadable_operation_store_is_exit_one(self):
        self.write_schema()
        op = self.create_op()
        record_path = os.path.join(self.root, "operations", "%s.json"
                                   % op["operation_id"])
        os.chmod(record_path, 0o644)
        rc, out, _ = self.run_cli("status", "--json")
        self.assertEqual(1, rc)
        report = json.loads(out)
        self.assertEqual("unknown", report["operation"]["state"])
        self.assertEqual("operation_permission",
                         report["operation"]["error"]["cause"]["fault_code"])

    def _cancel(self, operation_id):
        rc, out, err = self.run_cli("operation", "cancel", operation_id,
                                    "--json")
        return rc, json.loads(out), err

    # -- operation show / wait / cancel -------------------------------------

    def test_show_json_and_human(self):
        op = self.create_op(operation_id="show-1")
        rc, out, _ = self.run_cli("operation", "show", "show-1", "--json")
        self.assertEqual(0, rc)
        record = json.loads(out)
        self.assertEqual(1, record["operation_version"])
        self.assertEqual("queued", record["state"])
        self.assertEqual("preflight", record["phase"])
        self.assertEqual(op["operation_id"], record["operation_id"])
        rc, out, _ = self.run_cli("operation", "show", "show-1")
        self.assertEqual(0, rc)
        self.assertIn("operation show-1", out)
        self.assertIn("state: queued", out)
        self.assertIn("irreversible at: publishing", out)

    def test_show_missing_operation_is_exit_two(self):
        rc, out, _ = self.run_cli("operation", "show", "nope", "--json")
        self.assertEqual(2, rc)
        error = json.loads(out)
        self.assertEqual("operation_not_found", error["code"])
        self.assertEqual(1, error["error_version"])
        self.assertIn("occurred_at", error)
        self.assertIn("retryable", error)
        self.assertIn("remediation", error)

    def test_show_enforces_store_security(self):
        # A loose-permission root must block every data command, including
        # show (the acceptance reproduction).
        op = self.create_op(operation_id="loose-root")
        os.chmod(self.root, 0o755)
        rc, out, _ = self.run_cli("operation", "show", "loose-root", "--json")
        self.assertEqual(2, rc)
        error = json.loads(out)
        self.assertEqual("store_blocked", error["code"])
        self.assertEqual("root_permission",
                         error["cause"]["fault_code"])

    def test_show_path_escape_is_not_found(self):
        rc, out, _ = self.run_cli("operation", "show", "../evil", "--json")
        self.assertEqual(2, rc)
        self.assertEqual("operation_not_found", json.loads(out)["code"])
        self.assertFalse(os.path.exists(os.path.join(self._tmp, "evil.json")))

    def test_wait_blocked_operation_exits_one(self):
        # `blocked` is a waitable outcome: wait must return with exit 1 so
        # the operator can fix the cause and explicitly retry, never poll
        # forever.
        op = self.create_op(operation_id="blocked-wait")
        self.run_op(op["operation_id"], fault_hook=self._block_hook())
        rc, out, _ = self.run_cli("operation", "wait",
                                  op["operation_id"])
        self.assertEqual(1, rc)
        self.assertIn("terminal: blocked", out)

    def test_wait_json_lines_error_is_single_line(self):
        # Errors on a JSON Lines stream are exactly one compact JSON
        # document on one line, never pretty-printed across many lines.
        rc, out, _ = self.run_cli("operation", "wait", "nope",
                                  "--json-lines")
        self.assertEqual(2, rc)
        lines = out.splitlines()
        self.assertEqual(1, len(lines))
        error = json.loads(lines[0])
        self.assertEqual("operation_not_found", error["code"])
        self.assertEqual(1, error["error_version"])

    def test_wait_json_and_json_lines_are_mutually_exclusive(self):
        rc, _, _ = self.run_cli("operation", "wait", "x", "--json",
                                "--json-lines")
        self.assertEqual(2, rc)

    def test_operation_run_is_not_in_public_help(self):
        rc, out, _ = self.run_cli("operation", "--help")
        self.assertEqual(0, rc)
        self.assertNotIn("execute pending steps", out)
        self.assertNotIn("operation run", out)

    def test_wait_on_succeeded_operation_exit_zero(self):
        op = self.create_op()
        self.run_op(op["operation_id"])
        rc, out, _ = self.run_cli("operation", "wait", op["operation_id"])
        self.assertEqual(0, rc)
        self.assertIn("terminal: succeeded", out)
        rc, out, _ = self.run_cli("operation", "wait", op["operation_id"],
                                  "--json")
        self.assertEqual(0, rc)
        record = json.loads(out)
        self.assertEqual("succeeded", record["state"])
        self.assertTrue(record["result"]["completed"])

    def test_wait_on_failed_operation_exit_one(self):
        op = self.create_op()
        self.run_op(op["operation_id"],
                    fault_hook=self._fail_hook())
        rc, out, _ = self.run_cli("operation", "wait", op["operation_id"])
        self.assertEqual(1, rc)

    def test_wait_json_lines_increasing_seq(self):
        op = self.create_op()
        self.run_op(op["operation_id"])
        rc, out, _ = self.run_cli("operation", "wait",
                                  op["operation_id"], "--json-lines")
        self.assertEqual(0, rc)
        lines = [json.loads(line) for line in out.splitlines() if line]
        self.assertTrue(lines)
        seqs = [line["seq"] for line in lines]
        self.assertEqual(sorted(seqs), seqs)
        self.assertTrue(all(line["event_version"] == 1 for line in lines))
        self.assertEqual("terminal", lines[-1]["kind"])
        self.assertEqual("succeeded", lines[-1]["outcome"])

    def test_wait_missing_operation_is_exit_two(self):
        rc, _, _ = self.run_cli("operation", "wait", "nope")
        self.assertEqual(2, rc)

    def test_cancel_pre_publish_requested_exit_zero(self):
        op = self.create_op(operation_id="cancel-1")
        self.run_op(op["operation_id"], max_steps=1)
        rc, payload, _ = self._cancel(op["operation_id"])
        self.assertEqual(0, rc)
        self.assertEqual("requested", payload["cancel"])
        self.assertTrue(self.run_op(op["operation_id"])["state"]
                        == "cancelled")
        rc, out, _ = self.run_cli("operation", "wait", op["operation_id"])
        self.assertEqual(0, rc)
        self.assertIn("terminal: cancelled", out)

    def test_cancel_after_irreversible_uncancellable_exit_one(self):
        op = self.create_op(operation_id="cancel-2")
        self.run_op(op["operation_id"], max_steps=4)
        rc, payload, _ = self._cancel(op["operation_id"])
        self.assertEqual(1, rc)
        self.assertEqual("uncancellable", payload["cancel"])
        # The operation finishes its cleanup anyway.
        final = self.run_op(op["operation_id"])
        self.assertEqual("succeeded", final["state"])

    def test_cancel_missing_operation_is_exit_two(self):
        rc, _, _ = self.run_cli("operation", "cancel", "nope")
        self.assertEqual(2, rc)

    def test_operation_run_without_executor_fails(self):
        # The production registry registers `clear` (#54); a planted record
        # for a type that no registry registers fails deterministically.
        from operations import new_operation
        store = OperationStore(self.root)
        store.open()
        record = new_operation("backup", {}, ("preflight", "publishing"),
                               "publishing", operation_id="ghost-cli")
        store.create(record)
        rc, out, _ = self.run_cli("operation", "run", "ghost-cli")
        self.assertEqual(1, rc)
        shown = self.run_cli("operation", "show", "ghost-cli", "--json")
        self.assertEqual("failed", json.loads(shown[1])["state"])
        self.assertEqual("unsupported_operation_type",
                         json.loads(shown[1])["error"]["code"])

    # -- internal `operation run` (in-process with fixture registry) --------

    def test_operation_run_in_process_completes(self):
        op = self.create_op()
        rc = cli.main(["operation", "run", op["operation_id"]],
                      registry=self.registry())
        self.assertEqual(0, rc)
        record = OperationStore(self.root).load(op["operation_id"])
        self.assertEqual("succeeded", record["state"])

    def test_operation_run_once_steps_one_at_a_time(self):
        op = self.create_op()
        rc = cli.main(["operation", "run", "--once", op["operation_id"]],
                      registry=self.registry())
        self.assertEqual(0, rc)
        record = OperationStore(self.root).load(op["operation_id"])
        self.assertEqual("staging", record["phase"])

    def test_operation_run_yields_when_executor_lock_is_held(self):
        op = self.create_op(operation_id="run-yield")
        entered = threading.Event()
        release = threading.Event()

        def pause(phase, step_index, point):
            if point == "before_step":
                entered.set()
                release.wait(timeout=10)

        holder = threading.Thread(target=run_pending_steps, args=(
            OperationStore(self.root), self.registry(), op["operation_id"]),
            kwargs={"fault_hook": pause})
        holder.start()
        entered.wait(timeout=10)

        output = io.StringIO()
        error = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(
                error):
            rc = cli.main(["operation", "run", op["operation_id"]],
                          registry=self.registry())
        elapsed = time.monotonic() - started
        self.assertEqual(0, rc)
        self.assertLess(elapsed, 1.0)
        self.assertIn("another executor", error.getvalue())
        self.assertFalse(os.path.exists(os.path.join(
            self._tmp, "work", "preflight.count")))

        release.set()
        holder.join(timeout=10)
        self.assertFalse(holder.is_alive())

    def test_operation_run_does_not_auto_retry_blocked(self):
        op = self.create_op(operation_id="run-blocked")
        self.run_op(op["operation_id"], fault_hook=self._block_hook())
        # A plain run must NOT retry a deterministic blocked operation.
        rc = cli.main(["operation", "run", op["operation_id"]],
                      registry=self.registry())
        self.assertEqual(1, rc)
        record = OperationStore(self.root).load(op["operation_id"])
        self.assertEqual("blocked", record["state"])
        # The explicit --retry is the operator's retry after the fix.
        rc = cli.main(["operation", "run", "--retry", op["operation_id"]],
                      registry=self.registry())
        self.assertEqual(0, rc)
        record = OperationStore(self.root).load(op["operation_id"])
        self.assertEqual("succeeded", record["state"])

    # -- Ctrl-C detach ------------------------------------------------------

    def test_wait_sigint_detaches_without_cancelling(self):
        op = self.create_op(operation_id="detach-1", sleep_s=0.2)
        env = dict(os.environ)
        runner = (
            "import sys; sys.path.insert(0, %r);"
            "from fixture_operations import fixture_spec;"
            "from operations import (OperationRegistry, OperationStore,"
            " run_pending_steps);"
            "r = OperationRegistry(); r.register(fixture_spec());"
            "run_pending_steps(OperationStore(%r), r, %r)"
            % (DAEMON_DIR, self.root, op["operation_id"])
        )
        executor = subprocess.Popen(
            [sys.executable, "-c", runner], env=env)
        # Give the executor a moment to leave `queued`, then observe it.
        time.sleep(0.35)
        waiter = subprocess.Popen(
            [sys.executable, ENTRY, "operation", "wait",
             op["operation_id"]], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env)
        time.sleep(0.4)
        waiter.send_signal(signal.SIGINT)
        stdout, stderr = waiter.communicate(timeout=10)
        self.assertEqual(130, waiter.returncode)
        self.assertIn("detached from operation", stderr)
        self.assertNotIn("cancel", stdout.lower())
        executor.wait(timeout=20)
        record = OperationStore(self.root).load(op["operation_id"])
        self.assertEqual("succeeded", record["state"])
        self.assertFalse(record["cancel_requested"])

    # -- reserved maintenance commands --------------------------------------

    def test_reserved_commands_return_not_implemented(self):
        # backup create/verify, migrate, restore, quarantine and rebuild
        # are implemented since #55/#58/#56/#57/#68; no reserved command
        # surface remains.
        rc, out, err = self.run_cli("rebuild", "--json")
        # A rebuild without any configured derived state refuses with a
        # stable precondition error -- never a fake success and never a
        # not_implemented.
        self.assertEqual(1, rc)
        self.assertIn("derived_root_unconfigured", out + err)

    # -- rebuild CLI surface (Habit130/squirrel#68) --------------------------

    def test_rebuild_full_and_index_only_conflict_is_usage_error(self):
        rc, out, err = self.run_cli("rebuild", "--full", "--index-only",
                                    "--json")
        self.assertEqual(2, rc)
        self.assertIn("rebuild_mode_conflict", out + err)

    def test_rebuild_retry_and_restart_conflict_is_usage_error(self):
        rc, out, err = self.run_cli("rebuild", "--retry",
                                    "shadow-gen-v1:x-0000000000000000000000000000",
                                    "--restart", "--json")
        self.assertEqual(2, rc)
        self.assertIn("rebuild_retry_restart_conflict", out + err)

    def test_rebuild_retry_unknown_build_refuses(self):
        rc, out, err = self.run_cli(
            "rebuild", "--retry",
            "shadow-gen-v1:missing-0000000000000000000000000000", "--json")
        self.assertEqual(1, rc)
        self.assertIn("rebuild_not_found", out + err)

    def test_restore_57_flags_single_usage_error(self):
        # Either #57 restore flag alone is a usage error (spec #57 seam 2).
        cases = [
            ("restore", "--from", "x.squirrel-memory-backup",
             "--discard-current", "--accept-unreadable-current"),
            ("restore", "--from", "x.squirrel-memory-backup",
             "--discard-current", "--expect-current-fingerprint", "deadbeef"),
        ]
        for args in cases:
            with self.subTest(command=args):
                rc, out, err = self.run_cli(*args)
                self.assertEqual(2, rc, args)
                self.assertIn("unreadable_flags_required", out + err)

    def test_restore_expect_no_store_conflicts_with_unreadable_flags(self):
        rc, out, err = self.run_cli(
            "restore", "--from", "x.squirrel-memory-backup",
            "--discard-current", "--expect-no-store",
            "--accept-unreadable-current",
            "--expect-current-fingerprint", "d" * 64)
        self.assertEqual(2, rc)
        self.assertIn("conflicting_store_flags", out + err)

    def test_restore_unreadable_without_yes_goes_interactive(self):
        # The flag pair alone is not a silent bypass: without --yes the
        # exact-string interactive confirmation is required. (With no store
        # present the plan itself fails closed first.)
        rc, out, err = self.run_cli(
            "restore", "--from", "x.squirrel-memory-backup",
            "--discard-current", "--accept-unreadable-current",
            "--expect-current-fingerprint", "d" * 64)
        self.assertEqual(2, rc)
        self.assertIn("store_missing", out + err)

    def test_restore_unreadable_rejects_epoch_cas_and_backup_current(self):
        rc, out, err = self.run_cli(
            "restore", "--from", "x.squirrel-memory-backup",
            "--discard-current", "--yes",
            "--accept-unreadable-current",
            "--expect-current-fingerprint", "d" * 64,
            "--expect-store-epoch", "a" * 32)
        self.assertEqual(2, rc)
        self.assertIn("epoch_cas_unavailable", out + err)
        rc, out, err = self.run_cli(
            "restore", "--from", "x.squirrel-memory-backup",
            "--backup-current", "/tmp/out-backup",
            "--yes", "--accept-unreadable-current",
            "--expect-current-fingerprint", "d" * 64)
        self.assertEqual(2, rc)
        self.assertIn("retention_conflict", out + err)

    # -- quarantine ----------------------------------------------------------

    def _write_quarantine(self, operation_id, fingerprint="d" * 64,
                          marker="quarantined-bytes"):
        """Create a quarantined store fixture (identity-only metadata + as-is
        bytes) and return its fingerprint."""
        from quarantine import (
            METADATA_FILE,
            QUARANTINE_DIRNAME,
        )
        if not os.path.isdir(self.root):
            os.makedirs(self.root, mode=0o700)
        os.chmod(self.root, 0o700)
        qparent = os.path.join(self.root, QUARANTINE_DIRNAME)
        if not os.path.isdir(qparent):
            os.makedirs(qparent, mode=0o700)
        os.chmod(qparent, 0o700)
        qdir = os.path.join(qparent, operation_id)
        os.makedirs(qdir, mode=0o700)
        with open(os.path.join(qdir, "facts.sqlite3"), "wb") as stream:
            stream.write(marker.encode("utf-8"))
        os.chmod(os.path.join(qdir, "facts.sqlite3"), 0o600)
        import json as json_module
        with open(os.path.join(qdir, METADATA_FILE), "w",
                  encoding="utf-8") as stream:
            json_module.dump({
                "quarantine_version": 1,
                "operation_id": operation_id,
                "fingerprint_algorithm": "sha256",
                "fingerprint": fingerprint,
                "disposition": "unreadable",
                "created_at_utc": "2026-08-19T00:00:00+00:00",
                "members": {"facts.sqlite3": {"present": True, "size": 18,
                                              "sha256": ""}},
            }, stream)
        os.chmod(os.path.join(qdir, METADATA_FILE), 0o600)
        return fingerprint

    def test_quarantine_list_identity_only(self):
        fingerprint = self._write_quarantine("op-q1")
        rc, out, err = self.run_cli("quarantine", "list", "--json")
        self.assertEqual(0, rc, err)
        payload = json.loads(out)
        self.assertEqual(1, payload["count"])
        entry = payload["entries"][0]
        self.assertEqual("op-q1", entry["operation_id"])
        self.assertEqual(fingerprint, entry["fingerprint"])
        self.assertTrue(entry["valid"])
        # Identity only: no private content ever appears.
        self.assertNotIn("quarantined-bytes", out)
        rc, out, err = self.run_cli("quarantine", "list")
        self.assertEqual(0, rc, err)
        self.assertIn("op-q1", out)
        self.assertIn(fingerprint, out)
        self.assertNotIn("quarantined-bytes", out)

    def test_quarantine_purge_requires_exact_fingerprint(self):
        self._write_quarantine("op-q2", fingerprint="d" * 64)
        # Wrong fingerprint refuses the delete (exit 1) and leaves the copy.
        rc, out, err = self.run_cli(
            "quarantine", "purge", "op-q2", "e" * 64, "--json")
        self.assertEqual(1, rc)
        self.assertIn("fingerprint_mismatch", out + err)
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "quarantine", "op-q2")))
        # Exact fingerprint deletes it.
        rc, out, err = self.run_cli(
            "quarantine", "purge", "op-q2", "d" * 64, "--json")
        self.assertEqual(0, rc, err)
        payload = json.loads(out)
        self.assertEqual("op-q2", payload["purged"])
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "quarantine", "op-q2")))
        # A second purge of a missing operation refuses.
        rc, out, err = self.run_cli(
            "quarantine", "purge", "op-q2", "d" * 64, "--json")
        self.assertEqual(1, rc)
        self.assertIn("quarantine_not_found", out + err)

    def test_quarantine_purge_invalid_operation_id_is_usage_error(self):
        rc, out, err = self.run_cli(
            "quarantine", "purge", "../escape", "d" * 64)
        self.assertEqual(2, rc)
        self.assertIn("invalid_operation_id", out + err)

    def test_backup_create_without_store_fails_closed(self):
        output_path = os.path.join(self._tmp, "backup.squirrel-memory-backup")
        rc, out, err = self.run_cli("backup", "create", "--output",
                                    output_path)
        # No live store exists in this sandbox: the operation fails closed
        # with the stable fact-store fault; no fake success, no target.
        self.assertIn("fact_store_unverifiable", out + err)
        self.assertNotEqual(0, rc)
        self.assertFalse(os.path.exists(output_path))

    def test_unknown_command_is_exit_two(self):
        rc, _, _ = self.run_cli("frobnicate")
        self.assertEqual(2, rc)

    def test_missing_subcommand_is_exit_two(self):
        rc, _, _ = self.run_cli("operation")
        self.assertEqual(2, rc)

    # -- privacy ------------------------------------------------------------

    def test_cli_outputs_never_echo_private_input(self):
        op = self.create_op(operation_id="priv-1")
        self.run_op(op["operation_id"])
        for args in (("operation", "show", "priv-1"),
                     ("operation", "show", "priv-1", "--json"),
                     ("operation", "wait", "priv-1"),
                     ("operation", "wait", "priv-1", "--json-lines"),
                     ("operation", "cancel", "priv-1", "--json"),
                     ("status", "--json")):
            with self.subTest(args=args):
                rc, out, err = self.run_cli(*args)
                self.assertNotIn(MARKER, out, args)
                self.assertNotIn(MARKER, err, args)
                self.assertNotIn("上文", out, args)
                self.assertNotIn("候选", out, args)
        # The sanitized JSON snapshot never carries the parameters (the
        # idempotency credential stays inside the owner-only store); only
        # the fingerprint is reportable.
        rc, out, _ = self.run_cli("operation", "show", "priv-1", "--json")
        record = json.loads(out)
        self.assertNotIn("parameters", record)
        self.assertIn("parameters_fingerprint", record)
        # The persisted record's log/result/error stay clean too.
        persisted = OperationStore(self.root).load("priv-1")
        self.assertNotIn(MARKER, json.dumps(persisted["log"],
                                            ensure_ascii=False))
        self.assertNotIn(MARKER, json.dumps(persisted["result"],
                                            ensure_ascii=False))

    # -- security -----------------------------------------------------------

    def test_operations_dir_and_records_owner_only(self):
        self.create_op()
        operations_dir = os.path.join(self.root, "operations")
        self.assertEqual(0o700, stat.S_IMODE(os.lstat(operations_dir).st_mode))
        for name in os.listdir(operations_dir):
            path = os.path.join(operations_dir, name)
            if name.endswith(".json"):
                self.assertEqual(0o600,
                                 stat.S_IMODE(os.lstat(path).st_mode))

    def _block_hook(self):
        def hook(phase, step_index, point):
            raise OperationBlocked(code="fixture_preflight_failed",
                                   phase=phase)
        return hook

    def _fail_hook(self):
        from operations import OperationFailed

        def hook(phase, step_index, point):
            raise OperationFailed(code="transient_step_failure", phase=phase)
        return hook


class TrialCliTest(unittest.TestCase):
    """`annotate` / `alarm` / `status` trial dimension (Habit130/squirrel#74).

    Uses throwaway trace stores under the temp semantic root; never touches
    live facts or Rime.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_trial_cli_")
        self.root = os.path.join(self._tmp, "sm")
        self.rime_dir = os.path.join(self._tmp, "rime")
        os.makedirs(os.path.join(self.rime_dir, "build"))
        self._old_env = dict(os.environ)
        os.environ["SQUIRREL_SEMANTIC_MEMORY_ROOT"] = self.root
        os.environ["SQUIRREL_RIME_DIR"] = self.rime_dir
        os.environ["SQUIRREL_DAEMON_SOCKET"] = os.path.join(
            self._tmp, "missing.sock")
        self.store = TraceStore(self.root)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def run_cli(self, *args, timeout=30):
        proc = subprocess.run(
            [sys.executable, ENTRY] + list(args),
            capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr

    def write_schema(self):
        with open(os.path.join(self.rime_dir, "default.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("config_version: \"0.1\"\n")
            f.write("schema_list:\n  - schema: alpha\n")
        with open(os.path.join(self.rime_dir, "build",
                               "alpha.schema.yaml"), "w",
                  encoding="utf-8") as f:
            json.dump(SCHEMA, f, ensure_ascii=False)

    def seed_trace(self, request_id, kind="order_change"):
        if kind == "order_change":
            self.store.record_request(
                {"schema_id": "luna_pinyin", "category": "word",
                 "canonical_segment_input": "shijie",
                 "request_id": request_id, "plan_identity": "p",
                 "config_identity": "c",
                 "fact_high_water": {"store_epoch": "e1"},
                 "actionable": True, "candidate_count": 2},
                "ok",
                trace_payload={"kind": "order_change",
                               "request_id": request_id,
                               "schema_id": "luna_pinyin",
                               "category": "word",
                               "canonical_segment_input": "shijie",
                               "plan_identity": "p",
                               "config_identity": "c",
                               "retrieval_backend": "exact",
                               "base_scores": [1.0, 2.0],
                               "shadow_order": [0, 1],
                               "final_order": [1, 0],
                               "base_ranks": [0, 1],
                               "final_ranks": [1, 0],
                               "candidate_count": 2})
        else:
            self.store.record_request(
                {"schema_id": "luna_pinyin", "category": "word",
                 "canonical_segment_input": "shijie",
                 "request_id": request_id, "plan_identity": "p",
                 "config_identity": "c",
                 "fact_high_water": {"store_epoch": "e1"},
                 "actionable": True, "candidate_count": 2},
                "oracle_fault",
                trace_payload={"kind": "fault",
                               "error_code": "oracle_fault",
                               "passthrough": True})

    def test_annotate_mispromotion_human_and_json(self):
        self.seed_trace("req-cli-1")
        rc, out, err = self.run_cli(
            "annotate", "mispromotion", "--request-id", "req-cli-1",
            "--event-id", "evt-9")
        self.assertEqual(0, rc, err)
        self.assertIn("annotated mispromotion", out)
        self.assertIn("req-cli-1", out)
        rc, out, err = self.run_cli(
            "annotate", "mispromotion", "--request-id", "req-cli-1", "--json")
        self.assertEqual(0, rc, err)
        payload = json.loads(out)
        self.assertEqual("req-cli-1", payload["annotation"]["request_id"])
        self.assertEqual("mispromotion", payload["annotation"]["kind"])
        self.assertEqual([], payload["alarms_fired"])
        # Never echoes private text.
        self.assertNotIn(MARKER, out)
        self.assertNotIn(MARKER, err)

    def test_annotate_unknown_request_refuses(self):
        rc, out, err = self.run_cli(
            "annotate", "mispromotion", "--request-id", "req-unknown")
        self.assertEqual(1, rc)
        self.assertIn("unknown_request_id", err)
        rc, out, err = self.run_cli(
            "annotate", "mispromotion", "--request-id", "req-unknown",
            "--json")
        self.assertEqual(1, rc)
        payload = json.loads(out)
        self.assertEqual("unknown_request_id", payload["code"])

    def test_annotate_refuses_raw_text_ids(self):
        self.seed_trace("req-cli-2")
        rc, out, err = self.run_cli(
            "annotate", "mispromotion", "--request-id", "req-cli-2",
            "--event-id", MARKER)
        self.assertEqual(1, rc)
        self.assertIn("unknown_request_id", err)

    def test_alarm_list_and_dismiss(self):
        self.seed_trace("req-cli-3")
        self.store.record_annotation("req-cli-3")
        # Force an alarm through the store directly (window logic is
        # unit-tested in test_tracing.py); the CLI surface is what we test.
        self.store._fire_alarm(
            "mispromotion_rate",
            {"window": 100, "confirmed": 3},
            "2026-01-01T00:00:00+00:00",
            "3 user-confirmed mispromotions in the last 100 actionable "
            "events; suggest rollback to gamma=0")
        rc, out, err = self.run_cli("alarm", "list")
        self.assertEqual(0, rc, err)
        self.assertIn("mispromotion_rate", out)
        self.assertIn("rollback to gamma=0", out)
        rc, out, err = self.run_cli("alarm", "list", "--json")
        self.assertEqual(0, rc, err)
        payload = json.loads(out)
        self.assertEqual(1, payload["active_count"])
        alarm_id = payload["alarms"][0]["alarm_id"]
        rc, out, err = self.run_cli("alarm", "dismiss", alarm_id,
                                    "--reason", "主观否决")
        self.assertEqual(0, rc, err)
        self.assertIn("dismissed alarm", out)
        rc, out, err = self.run_cli("alarm", "list")
        self.assertEqual(0, rc, err)
        self.assertIn("no alarms", out)
        # Traces remain after dismissal (SCN-74-7).
        self.assertEqual(1, len(self.store.list_traces()))

    def test_alarm_dismiss_unknown_refuses(self):
        rc, out, err = self.run_cli("alarm", "dismiss", "alarm-nope")
        self.assertEqual(1, rc)
        self.assertIn("unknown_alarm_id", err)

    def test_status_reports_trial_dimension(self):
        self.write_schema()
        self.seed_trace("req-cli-4")
        rc, out, err = self.run_cli("status", "--json")
        self.assertEqual(0, rc, err)
        payload = json.loads(out)
        self.assertIn("trial", payload)
        self.assertEqual(1, payload["trial"]["trace_count"])
        self.assertEqual(1, payload["trial"]["aggregates"]["semantic_requests"])
        self.assertIn("trial", out)
        # No raw text anywhere in status.
        self.assertNotIn(MARKER, out)
        self.assertNotIn(MARKER, err)

    def test_status_trial_alarm_raises_exit_code(self):
        self.write_schema()
        self.seed_trace("req-cli-5")
        self.store.record_annotation("req-cli-5")
        self.store._fire_alarm(
            "fault_rate",
            {"window": 300, "faults": 4, "rate": 0.0133},
            "2026-01-01T00:00:00+00:00",
            "true-fault rate exceeds 1%; suggest rollback to gamma=0")
        rc, out, err = self.run_cli("status", "--json")
        self.assertEqual(1, rc, err)
        payload = json.loads(out)
        self.assertEqual(1, payload["exit_code"])
        self.assertEqual(1, len(payload["trial"]["alarms"]))


if __name__ == "__main__":
    unittest.main()
