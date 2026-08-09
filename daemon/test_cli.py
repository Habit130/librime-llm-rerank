#!/usr/bin/env python3
"""CLI tests for `squirrel-semantic-memory` (Habit130/squirrel#52).

Subprocess tests run the real entry script with temporary roots; in-process
tests call cli.main() with the fixture operation type registered for the
internal `operation run` executor. All filesystem fixtures are isolated
temporary directories; the live Rime dir and the live facts root are never
touched.
"""

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
        self.assertIn("status_version 1", out)
        self.assertIn("operation_version 1", out)
        rc, out, _ = self.run_cli("version", "--json")
        self.assertEqual(0, rc)
        payload = json.loads(out)
        self.assertEqual("squirrel-semantic-memory", payload["command"])
        self.assertEqual("0.1.0", payload["program_version"])
        self.assertEqual(1, payload["status_version"])
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
        self.assertEqual(1, report["status_version"])
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
        # The production registry registers no type; a planted record for an
        # unregistered type fails deterministically.
        from operations import new_operation
        store = OperationStore(self.root)
        store.open()
        record = new_operation("clear", {}, ("preflight", "publishing"),
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
        output_path = os.path.join(self._tmp, "backup.squirrel-memory-backup")
        cases = [
            ("backup", "create", "--output", output_path),
            ("backup", "verify", output_path),
            ("restore",),
            ("clear",),
            ("rebuild",),
            ("quarantine", "list"),
            ("quarantine", "purge", "op-1", "deadbeef"),
        ]
        for args in cases:
            with self.subTest(command=args):
                rc, out, err = self.run_cli(*args)
                self.assertEqual(2, rc, args)
                self.assertIn("not_implemented", out + err)
        # No fake success: the target file was never created.
        self.assertFalse(os.path.exists(output_path))

    def test_reserved_commands_json_error(self):
        rc, out, _ = self.run_cli("clear", "--yes",
                                  "--expect-store-epoch", "u-1", "--json")
        self.assertEqual(2, rc)
        error = json.loads(out)
        self.assertEqual("not_implemented", error["code"])
        self.assertEqual("clear", error["cause"]["command"])
        self.assertEqual(1, error["error_version"])

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


if __name__ == "__main__":
    unittest.main()
