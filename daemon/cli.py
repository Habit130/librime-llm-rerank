#!/usr/bin/env python3
"""The `squirrel-semantic-memory` maintenance CLI (Habit130/squirrel#52).

The single supported public entry point for semantic-memory maintenance
(spec #43 "公开维护 CLI"). This ticket delivers:

  status            wired to the existing `status_core.py` (collect_status /
                    render_human / compute_exit_code); adds the additive
                    `operation` dimension (latest maintenance operation).
  version           program and protocol versions.
  operation show/wait/cancel
                    observe and cancel persistent long operations.
  operation run     INTERNAL executor loop (not a public interface): runs
                    pending steps for an operation; future tickets spawn it
                    detached so the foreground CLI can exit and only
                    detach, never cancel.
  backup create|verify, restore, clear, rebuild, quarantine list|purge
                    RESERVED command surface (approved by spec #43): fully
                    parsed but dispatch to a stable `not_implemented` error;
                    they never fake success and never execute destructive
                    behavior (#54/#55/#57/#68 implement them).

Output contracts (deterministic):
  - human text and --json carry stable version fields inside the document
    (status_version / operation_version / event_version / error_version).
  - `operation wait --json-lines` streams the operation log events in seq
    order; seq is strictly increasing.
  - error objects follow the spec error protocol: code, message,
    occurred_at, retryable, phase, remediation, cause.
  - Exit codes: 0 success; 1 non-success outcome (failed/blocked, or a
    cancel refused past the irreversible point); 2 usage error / unreadable
    store; 130 = `wait` detached by Ctrl-C (observation only, never a
    cancel). `status` keeps the status_core 0/1/2 rule.
  - Output, logs and errors never contain 上文, candidate text or
    embeddings.

Privilege and ownership (spec "权限与安全"): the operation store is
owner-only (0700/0600), symlink-rejecting, and the CLI refuses to run with
euid 0.

Paths are overridable for tests and headless use:
  SQUIRREL_SEMANTIC_MEMORY_ROOT (default ~/Library/Application Support/
  Squirrel/SemanticMemory), SQUIRREL_RIME_DIR (default ~/Library/Rime),
  SQUIRREL_DAEMON_SOCKET (default .../llm-rerank.sock).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import status_core  # noqa: E402
from operations import (  # noqa: E402
    ERROR_VERSION,
    EVENT_VERSION,
    OPERATION_VERSION,
    OperationError,
    OperationRegistry,
    OperationStore,
    cancel_operation,
    make_error,
    operation_outcome_exit_code,
    run_pending_steps,
    wait_for_terminal,
)

PROGRAM_NAME = "squirrel-semantic-memory"
PROGRAM_VERSION = "0.1.0"

DEFAULT_ROOT = os.path.expanduser(
    "~/Library/Application Support/Squirrel/SemanticMemory")
DEFAULT_RIME_DIR = os.path.expanduser("~/Library/Rime")
DEFAULT_DAEMON_SOCKET = os.path.expanduser(
    "~/Library/Application Support/Squirrel/llm-rerank.sock")


def default_paths():
    return {
        "semantic_memory_root": os.environ.get(
            "SQUIRREL_SEMANTIC_MEMORY_ROOT") or DEFAULT_ROOT,
        "rime_dir": os.environ.get("SQUIRREL_RIME_DIR") or DEFAULT_RIME_DIR,
        "daemon_socket": os.environ.get("SQUIRREL_DAEMON_SOCKET")
        or DEFAULT_DAEMON_SOCKET,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Semantic memory maintenance CLI (owner-only).")
    sub = parser.add_subparsers(dest="command")

    status = sub.add_parser("status", help="report the semantic memory "
                                           "status snapshot")
    status.add_argument("--json", action="store_true")
    status.add_argument("--schema", metavar="ID")
    status.set_defaults(handler=_cmd_status)

    version = sub.add_parser("version", help="print program and protocol "
                                             "versions")
    version.add_argument("--json", action="store_true")
    version.set_defaults(handler=_cmd_version)

    operation = sub.add_parser("operation", help="inspect and control long "
                                                 "operations")
    op_sub = operation.add_subparsers(dest="operation_command")

    show = op_sub.add_parser("show", help="show an operation snapshot")
    show.add_argument("operation_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(handler=_cmd_operation_show)

    wait = op_sub.add_parser("wait", help="observe an operation until "
                                          "terminal; Ctrl-C only detaches")
    wait.add_argument("operation_id")
    wait.add_argument("--json", action="store_true")
    wait.add_argument("--json-lines", action="store_true",
                      help="stream operation events as versioned JSON lines")
    wait.set_defaults(handler=_cmd_operation_wait)

    cancel = op_sub.add_parser("cancel", help="request cancellation in "
                                              "pre-publish phases")
    cancel.add_argument("operation_id")
    cancel.add_argument("--json", action="store_true")
    cancel.set_defaults(handler=_cmd_operation_cancel)

    run = op_sub.add_parser(
        "run", help="INTERNAL: execute pending steps for an operation "
                    "(not a public interface)")
    run.add_argument("operation_id")
    run.add_argument("--once", action="store_true",
                     help="execute at most one step")
    run.add_argument("--retry", action="store_true",
                     help="explicitly retry a blocked operation")
    run.set_defaults(handler=_cmd_operation_run)

    # -- reserved maintenance commands (spec #43 contract surface) --------

    backup = sub.add_parser("backup", help="reserved: backup commands")
    backup_sub = backup.add_subparsers(dest="backup_command")

    backup_create = backup_sub.add_parser(
        "create", help="reserved: create an online fact snapshot")
    backup_create.add_argument("--output", metavar="PATH", required=True)
    backup_create.add_argument("--json", action="store_true")
    backup_create.set_defaults(handler=_cmd_reserved)

    backup_verify = backup_sub.add_parser(
        "verify", help="reserved: verify a backup offline")
    backup_verify.add_argument("backup")
    backup_verify.add_argument("--json", action="store_true")
    backup_verify.set_defaults(handler=_cmd_reserved)

    restore = sub.add_parser("restore", help="reserved: restore a backup")
    restore.add_argument("--from", dest="from_path", metavar="BACKUP")
    restore.add_argument("--backup-current", metavar="PATH")
    restore.add_argument("--discard-current", action="store_true")
    restore.add_argument("--yes", action="store_true")
    restore.add_argument("--expect-store-epoch", metavar="UUID")
    restore.add_argument("--accept-unreadable-current", action="store_true")
    restore.add_argument("--expect-current-fingerprint", metavar="HASH")
    restore.add_argument("--expect-no-store", action="store_true")
    restore.add_argument("--json", action="store_true")
    restore.set_defaults(handler=_cmd_reserved)

    clear = sub.add_parser("clear", help="reserved: physically clear the "
                                         "semantic memory")
    clear.add_argument("--yes", action="store_true")
    clear.add_argument("--expect-store-epoch", metavar="UUID")
    clear.add_argument("--json", action="store_true")
    clear.set_defaults(handler=_cmd_reserved)

    rebuild = sub.add_parser("rebuild", help="reserved: rebuild derived "
                                             "state")
    rebuild.add_argument("--full", action="store_true")
    rebuild.add_argument("--index-only", action="store_true")
    rebuild.add_argument("--retry", metavar="BUILD_ID")
    rebuild.add_argument("--restart", action="store_true")
    rebuild.add_argument("--wait", action="store_true")
    rebuild.add_argument("--json", action="store_true")
    rebuild.set_defaults(handler=_cmd_reserved)

    quarantine = sub.add_parser("quarantine",
                                help="reserved: quarantine management")
    q_sub = quarantine.add_subparsers(dest="quarantine_command")

    q_list = q_sub.add_parser("list", help="reserved: list quarantined "
                                           "stores")
    q_list.add_argument("--json", action="store_true")
    q_list.set_defaults(handler=_cmd_reserved)

    q_purge = q_sub.add_parser("purge", help="reserved: purge a "
                                             "quarantined store")
    q_purge.add_argument("operation_id")
    q_purge.add_argument("content_fingerprint")
    q_purge.add_argument("--json", action="store_true")
    q_purge.set_defaults(handler=_cmd_reserved)

    return parser


def _json_dump(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _json_line(payload):
    return json.dumps(payload, ensure_ascii=False)


def _not_implemented_error(command):
    return make_error(
        "not_implemented", phase="cli",
        remediation="this command is reserved by the spec and not "
                    "implemented in this build",
        cause={"command": command})


def _render_error(error, json_mode):
    if json_mode:
        print(_json_dump(error))
    else:
        cause = error.get("cause")
        cause_text = "" if not cause else " (cause: %s)" % json.dumps(
            cause, ensure_ascii=False)
        print("error: %s: %s%s" % (error.get("code"),
                                   error.get("message"), cause_text),
              file=sys.stderr)
        print("remediation: %s" % error.get("remediation"), file=sys.stderr)


def _operation_store(paths):
    return OperationStore(paths["semantic_memory_root"])


def _store_operation_error(error, json_mode):
    _render_error(error.to_error_object(), json_mode)
    return 2


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def _latest_operation(store):
    """Latest operation by creation time plus the first load fault, so a
    corrupt/symlinked/loose-permission record is reported instead of being
    silently skipped."""
    operation_ids = store.list_ids()
    latest = None
    fault = None
    for operation_id in operation_ids:
        try:
            record = store.load(operation_id)
        except OperationError as error:
            if fault is None:
                fault = error
            continue
        if latest is None or record["created_at"] > latest["created_at"]:
            latest = record
    if latest is None:
        return None, fault
    return {
        "operation_id": latest["operation_id"],
        "type": latest["type"],
        "state": latest["state"],
        "phase": latest["phase"],
        "created_at": latest["created_at"],
        "updated_at": latest["updated_at"],
    }, fault


def _cmd_status(args, paths):
    report = status_core.collect_status(paths["rime_dir"],
                                        paths["semantic_memory_root"],
                                        paths["daemon_socket"])
    if args.schema:
        if report.get("snapshot_ok"):
            report["schemas"] = [entry for entry in report["schemas"]
                                 if entry["schema_id"] == args.schema]
            if not report["schemas"]:
                report = {
                    "status_version": status_core.STATUS_VERSION,
                    "generated_at": report["generated_at"],
                    "snapshot_ok": False,
                    "error": make_error("unknown_schema", phase="cli",
                                        cause={"schema": args.schema}),
                    "schemas": [],
                    "facts": report["facts"],
                    "serving": report["serving"],
                    "exit_code": 2,
                }
    # Additive operation dimension (spec status contract): the latest
    # maintenance operation. Additive only; status_version stays 1. Status
    # never creates the root (a pristine machine has no operations yet).
    store = _operation_store(paths)
    operation_section = {"state": "unknown"}
    operation_fault = None
    if os.path.isdir(paths["semantic_memory_root"]):
        try:
            store.open()
        except OperationError as error:
            operation_fault = error
        else:
            operation_section, operation_fault = _latest_operation(store)
    else:
        operation_section = None
    if operation_fault is not None:
        operation_section = {"state": "unknown",
                             "error": operation_fault.to_error_object()}
    report["operation"] = operation_section
    exit_code = status_core.compute_exit_code(report)
    if (isinstance(operation_section, dict)
            and (operation_section.get("state") in ("failed", "blocked")
                 or "error" in operation_section)):
        exit_code = max(exit_code, 1)
    report["exit_code"] = exit_code
    if args.json:
        print(_json_dump(report))
    else:
        print(status_core.render_human(report))
        if operation_section is None:
            print("operation: none")
        elif isinstance(operation_section, dict):
            if "error" in operation_section:
                print("operation: unavailable (%s)"
                      % operation_section["error"]["code"])
            else:
                print("operation: %s (%s, state %s, phase %s)"
                      % (operation_section["operation_id"],
                         operation_section["type"],
                         operation_section["state"],
                         operation_section["phase"]))
    return exit_code


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

def _cmd_version(args, paths):
    payload = {
        "command": PROGRAM_NAME,
        "program_version": PROGRAM_VERSION,
        "status_version": status_core.STATUS_VERSION,
        "operation_version": OPERATION_VERSION,
        "event_version": EVENT_VERSION,
        "error_version": ERROR_VERSION,
        "python_version": sys.version.split()[0],
    }
    if args.json:
        print(_json_dump(payload))
    else:
        print("%s %s (status_version %s; operation_version %s; "
              "event_version %s; error_version %s; python %s)"
              % (PROGRAM_NAME, payload["program_version"],
                 payload["status_version"], payload["operation_version"],
                 payload["event_version"], payload["error_version"],
                 payload["python_version"]))
    return 0


# ---------------------------------------------------------------------------
# operation show / wait / cancel / run
# ---------------------------------------------------------------------------

def _human_event_line(entry):
    kind = entry.get("kind")
    phase = entry.get("phase") or ""
    if kind == "progress":
        units = ", ".join("%s +%s" % (unit, value)
                          for unit, value in sorted(entry["progress"].items()))
        return "seq %s progress (phase %s): %s" % (entry["seq"], phase, units)
    if kind == "transition":
        return "seq %s transition: state %s (phase %s)" % (
            entry["seq"], entry.get("state"), phase)
    if kind == "cancel_requested":
        return "seq %s cancel requested (phase %s)" % (entry["seq"], phase)
    if kind == "terminal":
        outcome = entry.get("outcome")
        error_code = entry.get("error_code")
        suffix = "" if error_code is None else " (%s)" % error_code
        return "seq %s terminal: %s%s (phase %s)" % (
            entry["seq"], outcome, suffix, phase)
    return "seq %s %s (phase %s)" % (entry["seq"], kind, phase)


def _print_operation_human(record):
    print("operation %s" % record["operation_id"])
    print("  type: %s" % record["type"])
    print("  state: %s" % record["state"])
    print("  phase: %s" % record["phase"])
    print("  irreversible at: %s" % record["irreversible_phase"])
    print("  progress: events %s; bytes %s; chunks %s"
          % (record["progress"]["events"], record["progress"]["bytes"],
             record["progress"]["chunks"]))
    print("  created: %s" % record["created_at"])
    print("  updated: %s" % record["updated_at"])
    if record["cancel_requested"]:
        print("  cancel requested: yes")
    if record["error"] is not None:
        print("  error: %s" % record["error"]["code"])
    if record["result"] is not None:
        print("  result: %s"
              % json.dumps(record["result"], ensure_ascii=False))


def _cmd_operation_show(args, paths):
    store = _operation_store(paths)
    try:
        record = store.load(args.operation_id)
    except OperationError as error:
        return _store_operation_error(error, args.json)
    if args.json:
        print(_json_dump(record))
    else:
        _print_operation_human(record)
    return 0


def _emit_wait_entry(entry, args):
    if args.json_lines:
        print(_json_line(entry))
    elif not args.json:
        print(_human_event_line(entry))


def _cmd_operation_wait(args, paths):
    store = _operation_store(paths)
    try:
        store.open()
        record = store.load(args.operation_id)
    except OperationError as error:
        return _store_operation_error(error, args.json or args.json_lines)
    if record["state"] not in ("queued", "running", "blocked"):
        # Already terminal: stream every event once, then report.
        for entry in record["log"]:
            _emit_wait_entry(entry, args)
        if args.json:
            print(_json_dump(record))
        return operation_outcome_exit_code(record["state"])
    try:
        final, outcome = wait_for_terminal(
            store, args.operation_id, emit=lambda entry: _emit_wait_entry(
                entry, args))
    except KeyboardInterrupt:
        current = store.load(args.operation_id)
        print("interrupted: detached from operation %s (state %s, phase %s); "
              "the operation continues, this is not a cancel"
              % (args.operation_id, current["state"], current["phase"]),
              file=sys.stderr)
        return 130
    if args.json:
        print(_json_dump(final))
    return operation_outcome_exit_code(outcome)


def _cmd_operation_cancel(args, paths):
    store = _operation_store(paths)
    try:
        record, disposition = cancel_operation(store, args.operation_id)
    except OperationError as error:
        return _store_operation_error(error, args.json)
    payload = {
        "operation_version": OPERATION_VERSION,
        "operation_id": record["operation_id"],
        "cancel": disposition,
        "state": record["state"],
        "phase": record["phase"],
    }
    if args.json:
        print(_json_dump(payload))
    elif disposition == "requested":
        print("cancel requested for operation %s (state %s, phase %s)"
              % (record["operation_id"], record["state"], record["phase"]))
    elif disposition == "already_cancelled":
        print("operation %s already cancelled" % record["operation_id"])
    elif disposition == "uncancellable":
        print("operation %s cannot be cancelled (state %s, phase %s); it "
              "is past its irreversible point and will finish its cleanup"
              % (record["operation_id"], record["state"], record["phase"]))
    else:
        print("operation %s already %s; cancel refused"
              % (record["operation_id"], record["state"]))
    if disposition in ("requested", "already_cancelled"):
        return 0
    return 1


def _cmd_operation_run(args, paths):
    store = _operation_store(paths)
    try:
        store.open()
        record = store.load(args.operation_id)
        last_seq = len(record["log"])
        while True:
            record = run_pending_steps(
                store, args.registry, args.operation_id,
                max_steps=1 if args.once else None,
                retry_blocked=args.retry)
            for entry in record["log"][last_seq:]:
                print(_json_line(entry))
                last_seq = len(record["log"])
            if record["state"] in ("succeeded", "failed", "blocked",
                                   "cancelled"):
                break
            if args.once:
                break
    except OperationError as error:
        return _store_operation_error(error, False)
    if record["state"] in ("succeeded", "cancelled"):
        return 0
    if record["state"] in ("failed", "blocked"):
        return 1
    # running with --once: work was done, more remains; nothing is wrong.
    return 0


# ---------------------------------------------------------------------------
# reserved maintenance commands
# ---------------------------------------------------------------------------

def _cmd_reserved(args, paths):
    command = _reserved_command_name(args)
    error = _not_implemented_error(command)
    _render_error(error, getattr(args, "json", False))
    return 2


def _reserved_command_name(args):
    if args.command == "backup":
        return "backup %s" % args.backup_command
    if args.command == "quarantine":
        return "quarantine %s" % args.quarantine_command
    return args.command


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def main(argv=None, registry=None):
    """Run the CLI. `registry` is the operation-type registry used by the
    internal `operation run` executor; production code passes None (no
    maintenance type is registered in #52). Returns the process exit code.
    """
    args = build_parser().parse_args(argv)
    paths = default_paths()
    if getattr(args, "registry", None) is None:
        args.registry = registry if registry is not None else OperationRegistry()
    if not hasattr(args, "handler"):
        print("error: missing command (try --help)", file=sys.stderr)
        return 2
    return args.handler(args, paths)


if __name__ == "__main__":
    sys.exit(main())
