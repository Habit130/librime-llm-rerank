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
  - `clear --json` writes exactly one versioned terminal record to stdout
    (a single json.loads(stdout) parses the whole run); the compact started
    envelope that exposes the operation id before destructive work goes to
    stderr.
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
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import status_core  # noqa: E402
from operations import (  # noqa: E402
    ERROR_VERSION,
    EVENT_VERSION,
    OPERATION_VERSION,
    OperationError,
    OperationStore,
    cancel_operation,
    create_operation,
    make_error,
    make_runner_claim,
    operation_outcome_exit_code,
    public_record,
    try_run_pending_steps,
    wait_for_terminal,
)

PROGRAM_NAME = "squirrel-semantic-memory"
PROGRAM_VERSION = "0.1.0"

DEFAULT_ROOT = os.path.expanduser(
    "~/Library/Application Support/Squirrel/SemanticMemory")
DEFAULT_RIME_DIR = os.path.expanduser("~/Library/Rime")
DEFAULT_DAEMON_SOCKET = os.path.expanduser(
    "~/Library/Application Support/Squirrel/llm-rerank.sock")
DEFAULT_CONTROL_SOCKET = os.path.expanduser(
    "~/Library/Application Support/Squirrel/SemanticMemory/"
    "llm-rerank-control.sock")


def default_paths():
    return {
        "semantic_memory_root": os.environ.get(
            "SQUIRREL_SEMANTIC_MEMORY_ROOT") or DEFAULT_ROOT,
        "rime_dir": os.environ.get("SQUIRREL_RIME_DIR") or DEFAULT_RIME_DIR,
        "daemon_socket": os.environ.get("SQUIRREL_DAEMON_SOCKET")
        or DEFAULT_DAEMON_SOCKET,
        "control_socket": os.environ.get("SQUIRREL_DAEMON_CONTROL_SOCKET")
        or DEFAULT_CONTROL_SOCKET,
    }


def default_registry(paths=None):
    """The production operation registry (`clear`; later tickets add the
    remaining maintenance types)."""
    from clear_operation import production_registry
    paths = paths or default_paths()
    return production_registry(
        paths["semantic_memory_root"],
        control_socket=paths["control_socket"],
        scoring_socket=paths["daemon_socket"])


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
    wait_mode = wait.add_mutually_exclusive_group()
    wait_mode.add_argument("--json", action="store_true")
    wait_mode.add_argument("--json-lines", action="store_true",
                           help="stream operation events as versioned JSON "
                                "lines")
    wait.set_defaults(handler=_cmd_operation_wait)

    cancel = op_sub.add_parser("cancel", help="request cancellation in "
                                              "pre-publish phases")
    cancel.add_argument("operation_id")
    cancel.add_argument("--json", action="store_true")
    cancel.set_defaults(handler=_cmd_operation_cancel)

    # Internal executor entry point: deliberately hidden from the public
    # help surface (documented as not a public interface).
    run = op_sub.add_parser(
        "run", help=argparse.SUPPRESS,
        description="INTERNAL: execute pending steps for an operation "
                    "(not a public interface).")
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

    clear = sub.add_parser("clear", help="physically clear the semantic "
                                         "memory and start a new history")
    clear.add_argument("--yes", action="store_true",
                       help="non-interactive confirmation; requires "
                            "--expect-store-epoch")
    clear.add_argument("--expect-store-epoch", metavar="UUID",
                       help="expected current store epoch (epoch CAS)")
    clear.add_argument("--json", action="store_true")
    clear.set_defaults(handler=_cmd_clear)

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


def _render_error(error, mode):
    """mode is "human", "json" or "json-lines". JSON Lines errors are a
    single compact JSON document on one line, so a stream consumer never
    sees multi-line pretty output or mixed formats."""
    if mode == "json":
        print(_json_dump(error), flush=True)
    elif mode == "json-lines":
        print(_json_line(error), flush=True)
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


def _store_operation_error(error, mode):
    _render_error(error.to_error_object(), mode)
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
    # never creates the root and never writes (a pristine machine has no
    # operations yet).
    store = _operation_store(paths)
    operation_section = {"state": "unknown"}
    operation_fault = None
    try:
        store.open(create=False)
    except OperationError as error:
        operation_fault = error
    else:
        operation_section, operation_fault = _latest_operation(store)
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
        store.open(create=False)
        record = store.load(args.operation_id)
    except OperationError as error:
        return _store_operation_error(
            error, "json" if args.json else "human")
    if args.json:
        print(_json_dump(public_record(record)), flush=True)
    else:
        _print_operation_human(record)
    return 0


def _emit_wait_entry(entry, args):
    if args.json_lines:
        print(_json_line(entry), flush=True)
    elif not args.json:
        print(_human_event_line(entry), flush=True)


def _cmd_operation_wait(args, paths):
    store = _operation_store(paths)
    mode = "json-lines" if args.json_lines else (
        "json" if args.json else "human")
    try:
        store.open(create=False)
        record = store.load(args.operation_id)
    except OperationError as error:
        return _store_operation_error(error, mode)
    if record["state"] not in ("queued", "running", "blocked"):
        # Already terminal: stream every event once, then report.
        for entry in record["log"]:
            _emit_wait_entry(entry, args)
        if args.json:
            print(_json_dump(public_record(record)), flush=True)
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
        print(_json_dump(public_record(final)), flush=True)
    return operation_outcome_exit_code(outcome)


def _cmd_operation_cancel(args, paths):
    store = _operation_store(paths)
    try:
        record, disposition = cancel_operation(store, args.operation_id)
    except OperationError as error:
        return _store_operation_error(
            error, "json" if args.json else "human")
    payload = {
        "operation_version": OPERATION_VERSION,
        "operation_id": record["operation_id"],
        "cancel": disposition,
        "state": record["state"],
        "phase": record["phase"],
    }
    if args.json:
        print(_json_dump(payload), flush=True)
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
        claim = make_runner_claim()
        while True:
            record, acquired = try_run_pending_steps(
                store, args.registry, args.operation_id, claim=claim,
                max_steps=1 if args.once else None,
                retry_blocked=args.retry)
            if not acquired:
                current_claim = record.get("runner_claim") or {}
                print("operation %s is being executed by another executor "
                      "(pid %s); this invocation did not execute steps"
                      % (args.operation_id, current_claim.get("pid")),
                      file=sys.stderr)
                return 0
            for entry in record["log"][last_seq:]:
                print(_json_line(entry), flush=True)
                last_seq = len(record["log"])
            if record["state"] in ("succeeded", "failed", "blocked",
                                   "cancelled"):
                break
            if args.once:
                break
    except OperationError as error:
        return _store_operation_error(error, "human")
    if record["state"] in ("succeeded", "cancelled"):
        return 0
    if record["state"] in ("failed", "blocked"):
        return 1
    # running with --once: work was done, more remains; nothing is wrong.
    return 0


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------

def _read_clear_identity(paths):
    """Read-only current identity for the confirmation display."""
    from clear_operation import FactStoreHelper, live_identity
    return live_identity(FactStoreHelper(), paths["semantic_memory_root"])


def _emit_clear_event(entry, args):
    if not args.json:
        print(_human_event_line(entry), flush=True)


def _print_clear_result(record, args):
    if args.json:
        print(_json_dump(public_record(record)), flush=True)
        return
    result = record.get("result") or {}
    print("clear %s" % result.get("outcome", "completed"))
    print("  cleanup_complete: %s" % bool(result.get("cleanup_complete")))
    old = result.get("old") or {}
    new = result.get("new") or {}
    if result.get("outcome") == "cleared":
        print("  old history: %s (epoch %s)"
              % (old.get("history_id") or "unknown",
                 old.get("store_epoch") or "unknown"))
        print("  new history: %s (epoch %s)"
              % (new.get("history_id") or "unknown",
                 new.get("store_epoch") or "unknown"))
    else:
        identity = new or old
        if identity:
            print("  existing empty history: %s (epoch %s)"
                  % (identity.get("history_id"), identity.get("store_epoch")))
        else:
            print("  no semantic memory data existed")
    serving = result.get("serving_ready")
    print("  serving_ready: %s"
          % ("yes" if serving is True else ("no" if serving is False
                                            else "unknown")))
    print("  %s" % result.get("media_residue_disclaimer", ""))


def _cmd_clear(args, paths):
    store = _operation_store(paths)
    mode = "json" if args.json else "human"
    try:
        store.open(create=False)
    except OperationError as error:
        return _store_operation_error(error, mode)

    if args.yes != (args.expect_store_epoch is not None):
        # Non-interactive clear requires both confirmation and epoch CAS;
        # there is deliberately no --force (spec #43).
        error = make_error(
            "confirmation_required", phase="cli",
            remediation="provide both --yes and --expect-store-epoch, or run "
                        "interactively and type the exact confirmation string",
            cause=None)
        _render_error(error, mode)
        return 2

    try:
        identity_empty = _read_clear_identity(paths)
    except OperationError as error:
        return _store_operation_error(error, mode)

    if identity_empty is None:
        confirmation = "CLEAR PRISTINE"
        expected_epoch = ""
        description = ("no facts database exists; this clears any remaining "
                       "application-controlled semantic memory data")
    else:
        identity, _empty = identity_empty
        confirmation = "CLEAR %s AT %s" % (identity["history_id"],
                                           identity["store_epoch"])
        expected_epoch = identity["store_epoch"]
        description = ("this deletes the local semantic memory and starts a "
                       "new history")

    if args.yes:
        if args.expect_store_epoch != expected_epoch:
            # The interactive path above already re-derived the current
            # epoch; this gate makes a stale non-interactive expectation a
            # zero-side-effect usage outcome before any operation exists.
            error = make_error(
                "store_epoch_mismatch", phase="cli",
                remediation="re-run with --expect-store-epoch %s"
                            % (expected_epoch or "<no store>"),
                cause={"expected": args.expect_store_epoch,
                       "actual": expected_epoch or None})
            _render_error(error, mode)
            return 2
    else:
        print(description)
        print("type the exact string below to confirm:")
        print(confirmation, flush=True)
        try:
            entered = sys.stdin.readline()
        except (EOFError, OSError):
            entered = ""
        if entered.rstrip("\r\n") != confirmation:
            error = make_error(
                "confirmation_failed", phase="cli", retryable=True,
                remediation="re-run clear and type the exact confirmation "
                            "string",
                cause=None)
            _render_error(error, mode)
            return 1

    try:
        record = create_operation(
            store, args.registry, "clear",
            {"expect_store_epoch": expected_epoch})
    except OperationError as error:
        return _store_operation_error(error, mode)
    except ValueError as error:
        return _store_operation_error(
            OperationError("invalid_parameters", phase="cli",
                           retryable=False, cause={
                               "error": str(error)}), mode)

    operation_id = record["operation_id"]
    if args.json:
        # The operation id must be observable before any destructive work,
        # but stdout must stay exactly one versioned terminal document so a
        # single json.loads(stdout) parses the whole run. The compact
        # started envelope therefore goes to stderr, a separate channel
        # that never pollutes the JSON stdout contract.
        print(_json_line({
            "operation_version": OPERATION_VERSION,
            "operation_id": operation_id,
            "type": "clear",
            "state": "running",
            "expect_store_epoch_present": expected_epoch != "",
        }), flush=True, file=sys.stderr)
    else:
        print("clear started: operation %s" % operation_id)

    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "squirrel-semantic-memory")
    # Observe the persistent record; Ctrl-C only detaches (exit 130) while
    # the detached executor keeps running. If the executor died without
    # reaching a terminal state, report it instead of waiting forever. The
    # try encloses the executor spawn itself so a SIGINT can never kill
    # this process before the observation loop takes over.
    import time as time_module
    last_seq = 0
    alive_grace = None
    executor = None
    try:
        executor = subprocess.Popen(
            [sys.executable, entry, "operation", "run", operation_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        while True:
            current = store.load(operation_id)
            for entry in current["log"][last_seq:]:
                _emit_clear_event(entry, args)
                last_seq = len(current["log"])
            if current["state"] in ("succeeded", "failed", "blocked",
                                    "cancelled"):
                break
            if executor.poll() is not None:
                if alive_grace is None:
                    alive_grace = time_module.monotonic()
                elif time_module.monotonic() - alive_grace > 3.0:
                    error = make_error(
                        "executor_exited", phase="runner", retryable=True,
                        remediation="the executor process exited without a "
                                    "terminal record; run `operation run %s` "
                                    "to resume" % operation_id,
                        cause={"state": current["state"],
                               "phase": current["phase"]})
                    _render_error(error, mode)
                    return 1
            else:
                alive_grace = None
            time_module.sleep(0.25)
    except KeyboardInterrupt:
        current = store.load(operation_id)
        print("interrupted: detached from operation %s (state %s, phase %s); "
              "the clear continues in the background, this is not a cancel"
              % (operation_id, current["state"], current["phase"]),
              file=sys.stderr)
        return 130
    except OperationError as error:
        return _store_operation_error(error, mode)
    except OSError as error:
        return _store_operation_error(
            OperationError("executor_start_failed", phase="cli",
                           retryable=True, cause={"error": error.strerror}),
            mode)

    if current["state"] == "succeeded":
        _print_clear_result(current, args)
        return 0
    if current["state"] == "cancelled":
        _print_clear_result(current, args)
        return 0
    if args.json:
        print(_json_dump(public_record(current)), flush=True)
    else:
        print("clear did not complete: state %s (phase %s)"
              % (current["state"], current["phase"]))
        if current.get("error") is not None:
            print("  error: %s" % current["error"]["code"])
            print("  remediation: %s"
                  % current["error"].get("remediation", ""))
    return 1


# ---------------------------------------------------------------------------
# reserved maintenance commands
# ---------------------------------------------------------------------------

def _cmd_reserved(args, paths):
    command = _reserved_command_name(args)
    error = _not_implemented_error(command)
    _render_error(error, "json" if getattr(args, "json", False) else "human")
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
    internal `operation run` executor; production code passes None, which
    loads the production registry (`clear`; backup/restore/rebuild/
    quarantine arrive with their own tickets). Returns the process exit
    code.
    """
    if os.geteuid() == 0:
        error = make_error(
            "unsupported_privilege", phase="cli",
            remediation="run this command as the semantic memory owner, "
                        "not as root")
        _render_error(error, "human")
        return 2
    args = build_parser().parse_args(argv)
    paths = default_paths()
    if getattr(args, "registry", None) is None:
        args.registry = registry if registry is not None else \
            default_registry(paths)
    if not hasattr(args, "handler"):
        print("error: missing command (try --help)", file=sys.stderr)
        return 2
    return args.handler(args, paths)


if __name__ == "__main__":
    sys.exit(main())
