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
  backup create     consistent online fact snapshot published as a versioned
                    two-member .squirrel-memory-backup ZIP with a no-
                    overwrite atomic publication; refuses destination media
                    that cannot guarantee owner-only permissions unless the
                    operator explicitly confirms (--allow-insecure-
                    destination + exact string) and permanently marks the
                    container.
  backup verify     fully offline validation of a backup container: strict
                    member/name/attribute/compression/size checks, CRC,
                    extracted-database integrity and re-computed manifest
                    cross-checks; never reads live state, never connects to
                    or starts the daemon, never loads the model.
  restore           atomically replace the whole fact store with a verified
                    backup (container + manifest + checksum + integrity +
                    version + space preflight), preserving the backup's
                    history/HLC but minting a NEW store_epoch through the
                    C++ seam; requires an explicit --backup-current or
                    --discard-current and an exact confirmation (interactive
                    RESTORE <backup_id> OVER <epoch> or non-interactive
                    --yes + --expect-store-epoch CAS); --backup-current runs
                    after quiesce and before the replace and a failure
                    leaves the live store unchanged. An unreadable current
                    store is restored only with the flag pair
                    --accept-unreadable-current +
                    --expect-current-fingerprint <hash>, which quarantines
                    the as-is DB/WAL/SHM (verified + fsynced) before the
                    replace; a truly missing store uses --expect-no-store
                    (never satisfied by an unreadable file).
  quarantine list|purge
                    list quarantined stores (identity only: operation id,
                    fingerprint, size, timestamp — never any private text)
                    and purge one store only with the exact operation id +
                    content fingerprint. The daemon never scans, repairs,
                    merges or auto-restores quarantine.
  rebuild           explicitly trigger a manual rebuild of the derived
                    state (spec #43 手动重建, #68): auto (compatibility
                    matrix minimum scope; healthy matching active ->
                    already_current), --full (rebuild FP32/projection/
                    delta/index from facts even when the fingerprint is
                    unchanged; only --full mints a new generation for the
                    same fingerprint), --index-only (only with a healthy
                    compatible base AND a real ANN sidecar; otherwise an
                    explicit refusal, never a silent upgrade to full),
                    --retry <build_id> (continue a blocked/incomplete
                    staging; blocked never auto-retries), --restart
                    (discard the staging, then rebuild), --wait (observe
                    only; Ctrl-C detaches, never cancels).  Rebuild never
                    modifies facts, history_id, store_epoch or the three
                    schema switches, never quiesces the plugin, and never
                    starts a second builder (#68).

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
    OperationBlocked,
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
from rebuild_operation import (  # noqa: E402
    MODE_AUTO,
    MODE_FULL,
    MODE_INDEX_ONLY,
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
    """The production operation registry (`clear`, `backup.create`,
    `migrate`, `restore`, `rebuild`)."""
    from clear_operation import production_registry as clear_registry
    from backup_operation import production_registry as backup_registry
    from migrate_operation import production_registry as migrate_registry
    from restore_operation import production_registry as restore_registry
    paths = paths or default_paths()
    registry = clear_registry(
        paths["semantic_memory_root"],
        control_socket=paths["control_socket"],
        scoring_socket=paths["daemon_socket"])
    for spec in backup_registry(paths["semantic_memory_root"])._specs.values():
        registry.register(spec)
    for spec in migrate_registry(
            paths["semantic_memory_root"],
            control_socket=paths["control_socket"])._specs.values():
        registry.register(spec)
    for spec in restore_registry(
            paths["semantic_memory_root"],
            control_socket=paths["control_socket"],
            scoring_socket=paths["daemon_socket"])._specs.values():
        registry.register(spec)
    rebuild_spec = _rebuild_spec(paths).build()
    registry.register(rebuild_spec)
    return registry


def _rebuild_derived_root(paths):
    """The rebuild operation's derived root.

    The daemon owns the live derived root (its ``evidence_config`` is a
    daemon-private JSON); a manual rebuild must target the SAME derived
    root, so the CLI resolves it from ``SQUIRREL_SEMANTIC_MEMORY_DERIVED_ROOT``
    when set, else the conventional sibling ``derived`` next to the facts
    store.  The single-builder constraint is the caller's contract: a
    rebuild must not run against a derived root a daemon staging worker is
    concurrently building (throwaway roots in this ticket's envelope).
    """
    explicit = os.environ.get("SQUIRREL_SEMANTIC_MEMORY_DERIVED_ROOT")
    if explicit:
        return os.path.abspath(explicit)
    return os.path.join(paths["semantic_memory_root"], "derived")


def _rebuild_spec(paths):
    """The production RebuildSpec for one semantic root.

    The preview (CLI resolves build_id / already_current before creating
    the operation) and the executor steps (registry) must share ONE spec
    instance so their seams (provider / machine builder / publish) can
    never disagree.  The production seams default to the throwaway
    envelope (deterministic fixture provider, standard staging machine,
    no publish); a host that wires real seams passes its own registry.
    """
    from rebuild_operation import RebuildSpec
    return RebuildSpec(paths["semantic_memory_root"],
                       derived_root=_rebuild_derived_root(paths))


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

    backup = sub.add_parser("backup", help="create or verify an online fact "
                                           "snapshot")
    backup_sub = backup.add_subparsers(dest="backup_command")

    backup_create = backup_sub.add_parser(
        "create", help="create a consistent online fact snapshot backup")
    backup_create.add_argument("--output", metavar="PATH", required=True)
    backup_create.add_argument(
        "--allow-insecure-destination", action="store_true",
        help="accept a destination medium that cannot guarantee owner-only "
             "file permissions; requires typing the exact confirmation "
             "string")
    backup_create.add_argument("--json", action="store_true")
    backup_create.set_defaults(handler=_cmd_backup_create)

    backup_verify = backup_sub.add_parser(
        "verify", help="verify a backup fully offline")
    backup_verify.add_argument("backup")
    backup_verify.add_argument("--json", action="store_true")
    backup_verify.set_defaults(handler=_cmd_backup_verify)

    restore = sub.add_parser(
        "restore",
        help="atomically replace the whole fact store with a verified "
             "backup, minting a new store epoch")
    restore.add_argument("--from", dest="from_path", metavar="BACKUP",
                         required=True)
    retain = restore.add_mutually_exclusive_group(required=True)
    retain.add_argument("--backup-current", metavar="PATH",
                        help="before replacing, snapshot the current store "
                             "to this new path (must not exist)")
    retain.add_argument("--discard-current", action="store_true",
                        help="replace without keeping the current store; "
                             "restore never secretly saves it")
    restore.add_argument("--yes", action="store_true",
                         help="non-interactive confirmation; for a healthy "
                              "store requires --expect-store-epoch; for the "
                              "unreadable/no-store paths it substitutes the "
                              "flag pair as the confirmation")
    restore.add_argument("--expect-store-epoch", metavar="UUID",
                         help="expected current store epoch (epoch CAS)")
    # #57: unreadable-current handling, quarantine and --expect-no-store.
    # --accept-unreadable-current requires --expect-current-fingerprint
    # (atomic pair); both are exclusive with --expect-no-store.
    restore.add_argument("--accept-unreadable-current", action="store_true",
                         help="accept a present-but-unreadable current store "
                              "and quarantine it as-is before the replace "
                              "(requires --expect-current-fingerprint)")
    restore.add_argument("--expect-current-fingerprint", metavar="HASH",
                         help="expected sha256 fingerprint over the as-is "
                              "current DB+WAL+SHM bytes (the unreadable-path "
                              "CAS)")
    restore.add_argument("--expect-no-store", action="store_true",
                         help="restore over a truly missing store (no "
                              "quarantine, no epoch CAS)")
    restore.add_argument("--json", action="store_true")
    restore.set_defaults(handler=_cmd_restore)

    clear = sub.add_parser("clear", help="physically clear the semantic "
                                         "memory and start a new history")
    clear.add_argument("--yes", action="store_true",
                       help="non-interactive confirmation; requires "
                            "--expect-store-epoch")
    clear.add_argument("--expect-store-epoch", metavar="UUID",
                       help="expected current store epoch (epoch CAS)")
    clear.add_argument("--json", action="store_true")
    clear.set_defaults(handler=_cmd_clear)

    migrate = sub.add_parser(
        "migrate", help="upgrade a supported-old fact store to the current "
                        "schema (safety snapshot + staging + atomic replace)")
    migrate.add_argument("--json", action="store_true")
    migrate.set_defaults(handler=_cmd_migrate)

    rebuild = sub.add_parser("rebuild", help="explicitly trigger a manual "
                                             "rebuild of the derived state")
    rebuild.add_argument("--full", action="store_true",
                         help="rebuild FP32 / projection / delta / index "
                              "from facts even when the fingerprint is "
                              "unchanged; only --full mints a new "
                              "generation for the same fingerprint")
    rebuild.add_argument("--index-only", action="store_true",
                         help="rebuild only the ANN index from a healthy "
                              "compatible base; refuses when no healthy "
                              "base or ANN sidecar exists (never upgrades "
                              "to full)")
    rebuild.add_argument("--retry", metavar="BUILD_ID",
                         help="continue an existing blocked/incomplete "
                              "staging build")
    rebuild.add_argument("--restart", action="store_true",
                         help="discard the current staging, then rebuild "
                              "from scratch (distinct from --retry)")
    rebuild.add_argument("--wait", action="store_true",
                         help="observe the rebuild until terminal; "
                              "interrupting only detaches, never cancels")
    rebuild.add_argument("--json", action="store_true")
    rebuild.set_defaults(handler=_cmd_rebuild)

    quarantine = sub.add_parser("quarantine",
                                help="list or purge quarantined stores")
    q_sub = quarantine.add_subparsers(dest="quarantine_command")

    q_list = q_sub.add_parser("list", help="list quarantined stores "
                                           "(identity only)")
    q_list.add_argument("--json", action="store_true")
    q_list.set_defaults(handler=_cmd_quarantine_list)

    q_purge = q_sub.add_parser("purge", help="purge one quarantined store "
                                             "with exact id + fingerprint")
    q_purge.add_argument("operation_id")
    q_purge.add_argument("content_fingerprint")
    q_purge.add_argument("--json", action="store_true")
    q_purge.set_defaults(handler=_cmd_quarantine_purge)

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
# backup create / verify
# ---------------------------------------------------------------------------

def _watch_detached_operation(store, operation_id, emit, mode, noun,
                              extra_argv=()):
    """Spawn the detached executor and observe the persistent record until
    it reaches a terminal state or `blocked`. Ctrl-C only detaches (exit
    130); the executor keeps running. Returns (record, None) on a terminal
    observation or (None, exit_code) on early failure or detach.

    ``extra_argv`` appends executor arguments before the operation id
    (e.g. ``("--retry",)`` for an explicit retry of a blocked rebuild).
    """
    import time as time_module
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "squirrel-semantic-memory")
    last_seq = 0
    alive_grace = None
    executor = None
    try:
        executor = subprocess.Popen(
            [sys.executable, entry, "operation", "run"]
            + list(extra_argv) + [operation_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        while True:
            current = store.load(operation_id)
            for entry in current["log"][last_seq:]:
                emit(entry)
                last_seq = len(current["log"])
            if current["state"] in ("succeeded", "failed", "blocked",
                                    "cancelled"):
                return current, None
            if executor.poll() is not None:
                if alive_grace is None:
                    alive_grace = time_module.monotonic()
                elif time_module.monotonic() - alive_grace > 3.0:
                    resume_args = " ".join(
                        ["operation", "run"] + list(extra_argv)
                        + [operation_id])
                    error = make_error(
                        "executor_exited", phase="runner", retryable=True,
                        remediation="the executor process exited without a "
                                    "terminal record; run `%s` to resume"
                                    % resume_args,
                        cause={"state": current["state"],
                               "phase": current["phase"]})
                    _render_error(error, mode)
                    return None, 1
            else:
                alive_grace = None
            time_module.sleep(0.25)
    except KeyboardInterrupt:
        current = store.load(operation_id)
        print("interrupted: detached from operation %s (state %s, phase %s); "
              "the %s continues in the background, this is not a cancel"
              % (operation_id, current["state"], current["phase"], noun),
              file=sys.stderr)
        return None, 130
    except OperationError as error:
        _store_operation_error(error, mode)
        return None, 2
    except OSError as error:
        _store_operation_error(
            OperationError("executor_start_failed", phase="cli",
                           retryable=True, cause={"error": error.strerror}),
            mode)
        return None, 1


def _confirm_insecure_destination(output, mode):
    """Exact-string second confirmation for --allow-insecure-destination
    (spec #55 SCN-55-6): any deviation, EOF or extra character cancels.
    Returns True only after the exact phrase was typed. Everything is
    rendered on stderr so `--json` stdout stays exactly one document."""
    from backup_operation import CONFIRMATION_PREFIX
    confirmation = CONFIRMATION_PREFIX + output
    print("warning: the destination medium could not prove owner-only file "
          "permissions for this backup", file=sys.stderr)
    print("the backup contains plaintext private input history; on an "
          "insecure destination other accounts or processes of this device "
          "may be able to read it", file=sys.stderr)
    print("type the exact string below to confirm:", file=sys.stderr)
    print(confirmation, file=sys.stderr, flush=True)
    try:
        entered = sys.stdin.readline()
    except (EOFError, OSError):
        entered = ""
    return entered.rstrip("\r\n") == confirmation


def _print_backup_result(record, args):
    if args.json:
        print(_json_dump(public_record(record)), flush=True)
        return
    result = record.get("result") or {}
    print("backup %s" % result.get("backup_id", "created"))
    print("  destination: %s" % result.get("destination", "unknown"))
    print("  history: %s (epoch %s)"
          % (result.get("history_id") or "unknown",
             result.get("store_epoch") or "unknown"))
    print("  fact schema: %s; event format: %s..%s"
          % (result.get("fact_schema_version"),
             result.get("event_format_version_min"),
             result.get("event_format_version_max")))
    print("  facts: %s events, %s commits, %s candidates, %s retractions"
          % (result.get("event_count"), result.get("commit_count"),
             result.get("candidate_count"), result.get("retraction_count")))
    print("  created: %s" % result.get("created_at"))
    print("  sha256: %s (%s bytes)"
          % (result.get("database_sha256"), result.get("database_size")))
    if result.get("insecure_destination"):
        print("  warning: insecure destination confirmed; this backup is "
              "not owner-only protected")
    print("  %s" % result.get(
        "sensitive_declaration",
        "this backup contains plaintext private input history"))


def _cmd_backup_create(args, paths):
    store = _operation_store(paths)
    mode = "json" if args.json else "human"
    try:
        store.open(create=False)
    except OperationError as error:
        return _store_operation_error(error, mode)

    output = os.path.abspath(args.output)
    if args.allow_insecure_destination:
        if not _confirm_insecure_destination(output, mode):
            error = make_error(
                "confirmation_failed", phase="cli", retryable=True,
                remediation="re-run backup create and type the exact "
                            "confirmation string",
                cause=None)
            _render_error(error, mode)
            return 1
    elif not args.json:
        print("creating online fact snapshot at %s" % output)

    try:
        record = create_operation(
            store, args.registry, "backup.create",
            {"output": output,
             "allow_insecure": args.allow_insecure_destination})
    except OperationError as error:
        return _store_operation_error(error, mode)
    except ValueError as error:
        return _store_operation_error(
            OperationError("invalid_parameters", phase="cli",
                           retryable=False, cause={
                               "error": str(error)}), mode)

    operation_id = record["operation_id"]
    if args.json:
        # The operation id must be observable before any snapshot work, but
        # stdout must stay exactly one versioned terminal document so a
        # single json.loads(stdout) parses the whole run. The compact
        # started envelope therefore goes to stderr, a separate channel
        # that never pollutes the JSON stdout contract.
        print(_json_line({
            "operation_version": OPERATION_VERSION,
            "operation_id": operation_id,
            "type": "backup.create",
            "state": "running",
            "output": output,
        }), flush=True, file=sys.stderr)
    else:
        print("backup create started: operation %s" % operation_id)

    def emit(entry):
        if not args.json:
            print(_human_event_line(entry), flush=True)

    current, failure_code = _watch_detached_operation(
        store, operation_id, emit, mode, "backup create")
    if failure_code is not None:
        return failure_code

    if current["state"] in ("succeeded", "cancelled"):
        _print_backup_result(current, args)
        return 0
    if args.json:
        print(_json_dump(public_record(current)), flush=True)
    else:
        print("backup create did not complete: state %s (phase %s)"
              % (current["state"], current["phase"]))
        if current.get("error") is not None:
            print("  error: %s" % current["error"]["code"])
            print("  remediation: %s"
                  % current["error"].get("remediation", ""))
    return 1


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------

def _print_migrate_result(record, args):
    if args.json:
        print(_json_dump(public_record(record)), flush=True)
        return
    result = record.get("result") or {}
    print("migrate %s" % result.get("outcome", "completed"))
    print("  schema: %s; event format: %s"
          % (result.get("fact_schema_version", "unknown"),
             result.get("event_format_version", "unknown")))
    print("  history: %s (epoch %s)"
          % (result.get("history_id") or "unknown",
             result.get("store_epoch") or "unknown"))


def _cmd_migrate(args, paths):
    store = _operation_store(paths)
    mode = "json" if args.json else "human"
    try:
        store.open(create=False)
    except OperationError as error:
        return _store_operation_error(error, mode)

    try:
        record = create_operation(store, args.registry, "migrate", None)
    except OperationError as error:
        return _store_operation_error(error, mode)
    except ValueError as error:
        return _store_operation_error(
            OperationError("invalid_parameters", phase="cli",
                           retryable=False, cause={
                               "error": str(error)}), mode)

    operation_id = record["operation_id"]
    if args.json:
        print(_json_line({
            "operation_version": OPERATION_VERSION,
            "operation_id": operation_id,
            "type": "migrate",
            "state": "running",
        }), flush=True, file=sys.stderr)
    else:
        print("migrate started: operation %s" % operation_id)

    def emit(entry):
        if not args.json:
            print(_human_event_line(entry), flush=True)

    current, failure_code = _watch_detached_operation(
        store, operation_id, emit, mode, "migrate")
    if failure_code is not None:
        return failure_code

    if current["state"] in ("succeeded", "cancelled"):
        _print_migrate_result(current, args)
        return 0
    if args.json:
        print(_json_dump(public_record(current)), flush=True)
    else:
        print("migrate did not complete: state %s (phase %s)"
              % (current["state"], current["phase"]))
        if current.get("error") is not None:
            print("  error: %s" % current["error"]["code"])
            print("  remediation: %s"
                  % current["error"].get("remediation", ""))
    return 1


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

def _read_restore_plan(paths, from_path, *, accept_unreadable=False,
                       expect_no_store=False):
    """Read-only plan for the restore confirmation: the live current
    identity/stats and the backup manifest. Raises OperationError on a
    fail-closed condition.

    The #57 modes change what "current" means:
    - healthy: the live identity and stats (existing #56 behavior).
    - unreadable: the live store is present but the identity seam cannot
      read it; there is no identity/stats to display, only the expected
      fingerprint.
    - no-store: no facts database exists at all; nothing to display.
    """
    from backup_operation import BackupError, read_backup_manifest
    from clear_operation import FactStoreHelper, live_identity
    from quarantine import classify_current_store
    from restore_operation import _verify_restore_backup
    helper = FactStoreHelper()
    facts_path = os.path.join(paths["semantic_memory_root"], "facts.sqlite3")
    if expect_no_store:
        if os.path.lexists(facts_path):
            raise OperationError(
                "store_present", phase="cli",
                remediation="a facts database exists; --expect-no-store "
                            "requires the store to be absent",
                cause=None)
        identity = None
        live_stats = None
    elif accept_unreadable:
        disposition, _detail = classify_current_store(
            paths["semantic_memory_root"], helper, os.geteuid())
        if disposition == "missing":
            raise OperationError(
                "store_missing", phase="cli",
                remediation="no facts database exists; the unreadable-"
                            "current path requires a present store. Use "
                            "--expect-no-store for a truly missing store",
                cause=None)
        if disposition == "readable":
            raise OperationError(
                "store_readable", phase="cli",
                remediation="the current store is readable through the "
                            "fact-store seam; the unreadable-current path "
                            "requires an unreadable store",
                cause={"disposition": _detail})
        identity = None
        live_stats = None
    else:
        identity_empty = live_identity(
            helper, paths["semantic_memory_root"])
        if identity_empty is None:
            raise OperationError(
                "store_missing", phase="cli",
                remediation="no facts database exists; there is nothing to "
                            "restore over (restore never creates a store)",
                cause=None)
        identity, _empty = identity_empty
        try:
            live_stats = helper.stats(paths["semantic_memory_root"])
        except Exception as error:
            fault = getattr(error, "code", None) or getattr(error, "status",
                                                            None)
            raise OperationError(
                "fact_store_unverifiable", phase="cli",
                remediation="the live fact store failed closed validation; "
                            "inspect and fix it before restoring",
                cause={"fault_code": fault})
    try:
        # Full offline validation of the backup (container, manifest,
        # checksum, integrity, version). This re-uses the restore preflight
        # verify so the CLI never trusts an unvalidated container.
        manifest, _stats, _disposition = _verify_restore_backup(
            from_path, helper, phase="cli")
    except BackupError as error:
        raise OperationError(
            error.code, phase="cli",
            remediation="the backup failed offline validation; inspect it "
                        "and re-create it if needed",
            cause=error.cause)
    return identity, live_stats, manifest


def _print_restore_result(record, args):
    if args.json:
        print(_json_dump(public_record(record)), flush=True)
        return
    result = record.get("result") or {}
    print("restore %s" % result.get("outcome", "completed"))
    print("  fact_operation_succeeded: %s"
          % ("yes" if result.get("fact_operation_succeeded") else "no"))
    print("  serving_ready: %s"
          % ("yes" if result.get("serving_ready") is True
             else ("no" if result.get("serving_ready") is False
                   else "unknown")))
    if result.get("rebuild_queued") is not None:
        print("  rebuild_queued: %s" % ("yes" if result.get("rebuild_queued")
                                        else "no"))
    old = result.get("old") or {}
    new = result.get("new") or {}
    print("  old history: %s (epoch %s)"
          % (old.get("history_id") or "unknown",
             old.get("store_epoch") or "unknown"))
    print("  new history: %s (epoch %s)"
          % (new.get("history_id") or "unknown",
             new.get("store_epoch") or "unknown"))
    if result.get("backup_id"):
        print("  backup: %s" % result["backup_id"])
        print("  backup history: %s (epoch %s)"
              % (result.get("backup_history_id") or "unknown",
                 result.get("backup_store_epoch") or "unknown"))
    if result.get("backup_current_destination"):
        print("  current store backed up to: %s"
              % result["backup_current_destination"])
    elif result.get("discarded_current"):
        print("  current store discarded (explicit choice)")
    if result.get("quarantine_operation_id"):
        print("  quarantined current store: %s (fingerprint %s)"
              % (result["quarantine_operation_id"],
                 result.get("quarantine_fingerprint") or "unknown"))
    if result.get("no_store"):
        print("  no-store: yes (no current store existed)")
    if result.get("backup_event_count") is not None:
        print("  backup facts: %s events" % result["backup_event_count"])
    print("  %s" % result.get(
        "plaintext_sensitive_declaration",
        "this operation touches plaintext private input history"))


def _cmd_restore(args, paths):
    store = _operation_store(paths)
    mode = "json" if args.json else "human"
    try:
        store.open(create=False)
    except OperationError as error:
        return _store_operation_error(error, mode)

    accept_unreadable = bool(args.accept_unreadable_current)
    fingerprint = (args.expect_current_fingerprint or "").strip().lower()
    expect_no_store = bool(args.expect_no_store)
    if bool(accept_unreadable) != bool(fingerprint):
        # The #57 flag pair is atomic (spec #57 seam 2): either flag alone
        # is a usage error.
        error = make_error(
            "unreadable_flags_required", phase="cli",
            remediation="provide both --accept-unreadable-current and "
                        "--expect-current-fingerprint <sha256 hex>, or "
                        "neither",
            cause=None)
        _render_error(error, mode)
        return 2
    if expect_no_store and (accept_unreadable or fingerprint):
        error = make_error(
            "conflicting_store_flags", phase="cli",
            remediation="--expect-no-store is exclusive with the "
                        "unreadable-current flags",
            cause=None)
        _render_error(error, mode)
        return 2
    if (accept_unreadable or expect_no_store) and args.backup_current:
        error = make_error(
            "retention_conflict", phase="cli",
            remediation="--backup-current needs a readable current store; "
                        "use --discard-current for an unreadable or missing "
                        "store",
            cause=None)
        _render_error(error, mode)
        return 2
    if (accept_unreadable or expect_no_store) \
            and args.expect_store_epoch is not None:
        error = make_error(
            "epoch_cas_unavailable", phase="cli",
            remediation="no current store epoch is readable for the "
                        "unreadable/no-store restore; the fingerprint (or "
                        "absence) is the expectation, not an epoch",
            cause=None)
        _render_error(error, mode)
        return 2
    if not (accept_unreadable or expect_no_store):
        if args.yes != (args.expect_store_epoch is not None):
            # Non-interactive restore requires both confirmation and epoch
            # CAS; there is deliberately no --force (spec #43).
            error = make_error(
                "confirmation_required", phase="cli",
                remediation="provide both --yes and --expect-store-epoch, or "
                            "run interactively and type the exact "
                            "confirmation string",
                cause=None)
            _render_error(error, mode)
            return 2
    # For the #57 paths, --yes is OPTIONAL: without it the exact-string
    # interactive confirmation is required (the flag pair alone is never a
    # silent bypass); with it the non-interactive confirmation applies.

    from_path = os.path.abspath(args.from_path)
    try:
        identity, live_stats, manifest = _read_restore_plan(
            paths, from_path, accept_unreadable=accept_unreadable,
            expect_no_store=expect_no_store)
    except OperationError as error:
        return _store_operation_error(error, mode)

    if expect_no_store:
        expected_epoch = ""
        confirmation = "RESTORE %s OVER NO-STORE" % manifest["backup_id"]
    elif accept_unreadable:
        expected_epoch = ""
        confirmation = "RESTORE %s OVER UNREADABLE %s" % (
            manifest["backup_id"], fingerprint)
    else:
        expected_epoch = identity["store_epoch"]
        confirmation = "RESTORE %s OVER %s" % (manifest["backup_id"],
                                               expected_epoch)
    backup_watermark = manifest["hlc_high_water"]
    description = (
        "this replaces the whole local semantic memory with the backup, "
        "keeping the backup's history and HLC but minting a new store epoch")
    if args.yes:
        if not (accept_unreadable or expect_no_store) \
                and args.expect_store_epoch != expected_epoch:
            error = make_error(
                "store_epoch_mismatch", phase="cli",
                remediation="re-run restore with --expect-store-epoch %s"
                            % expected_epoch,
                cause={"expected": args.expect_store_epoch,
                       "actual": expected_epoch})
            _render_error(error, mode)
            return 2
    else:
        if accept_unreadable:
            print("current:")
            print("  state: unreadable (present but cannot be read)")
            print("  expected fingerprint: %s" % fingerprint)
            print("  note: the current DB/WAL/SHM will be quarantined "
                  "as-is before the replace")
        elif expect_no_store:
            print("current: none (no facts database exists)")
        else:
            print("current:")
            print("  history: %s" % identity["history_id"])
            print("  epoch: %s" % identity["store_epoch"])
            print("  events: %s"
                  % (live_stats.get("event_count") if live_stats
                     else "unknown"))
        print("backup:")
        print("  id: %s" % manifest["backup_id"])
        print("  history: %s" % manifest["history_id"])
        print("  epoch: %s" % manifest["store_epoch"])
        print("  events: %s" % manifest["event_count"])
        print("  high-water: %s.%s"
              % (backup_watermark["physical_ms"],
                 backup_watermark["logical"]))
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
                remediation="re-run restore and type the exact confirmation "
                            "string",
                cause=None)
            _render_error(error, mode)
            return 1

    parameters = {
        "from_path": from_path,
        "backup_current": os.path.abspath(args.backup_current)
        if args.backup_current else None,
        "discard_current": args.discard_current,
        "expect_store_epoch": expected_epoch,
        "accept_unreadable_current": accept_unreadable,
        "expect_current_fingerprint": fingerprint,
        "expect_no_store": expect_no_store,
    }
    try:
        record = create_operation(store, args.registry, "restore", parameters)
    except OperationError as error:
        return _store_operation_error(error, mode)
    except ValueError as error:
        return _store_operation_error(
            OperationError("invalid_parameters", phase="cli",
                           retryable=False, cause={
                               "error": str(error)}), mode)

    operation_id = record["operation_id"]
    if args.json:
        print(_json_line({
            "operation_version": OPERATION_VERSION,
            "operation_id": operation_id,
            "type": "restore",
            "state": "running",
            "from_path": from_path,
            "backup_id": manifest["backup_id"],
        }), flush=True, file=sys.stderr)
    else:
        print("restore started: operation %s" % operation_id)

    def emit(entry):
        if not args.json:
            print(_human_event_line(entry), flush=True)

    current, failure_code = _watch_detached_operation(
        store, operation_id, emit, mode, "restore")
    if failure_code is not None:
        return failure_code

    if current["state"] in ("succeeded", "cancelled"):
        _print_restore_result(current, args)
        return 0
    if args.json:
        print(_json_dump(public_record(current)), flush=True)
    else:
        print("restore did not complete: state %s (phase %s)"
              % (current["state"], current["phase"]))
        if current.get("error") is not None:
            print("  error: %s" % current["error"]["code"])
            print("  remediation: %s"
                  % current["error"].get("remediation", ""))
    return 1


def _print_verify_result(result, args):
    if args.json:
        print(_json_dump(result), flush=True)
        return
    if result["valid"]:
        print("backup: valid")
    else:
        print("backup: invalid")
    print("  backup id: %s" % result.get("backup_id"))
    print("  history: %s (epoch %s)"
          % (result.get("history_id") or "unknown",
             result.get("store_epoch") or "unknown"))
    print("  fact schema: %s; event format: %s..%s"
          % (result.get("fact_schema_version"),
             result.get("event_format_version_min"),
             result.get("event_format_version_max")))
    print("  facts: %s events, %s commits, %s candidates, %s retractions"
          % (result.get("event_count"), result.get("commit_count"),
             result.get("candidate_count"), result.get("retraction_count")))
    print("  created: %s" % result.get("created_at"))
    print("  sha256: %s (%s bytes)"
          % (result.get("database_sha256"), result.get("database_size")))
    if result.get("insecure_destination"):
        print("  warning: this backup was created on an explicitly "
              "confirmed insecure destination; it is not owner-only "
              "protected")


def _cmd_backup_verify(args, paths):
    from backup_operation import VERIFY_VERSION, BackupError, verify_backup
    mode = "json" if args.json else "human"
    try:
        result = verify_backup(args.backup)
    except BackupError as error:
        payload = {
            "verify_version": VERIFY_VERSION,
            "valid": False,
            "error": make_error(
                error.code, phase="cli",
                remediation="verify the container's integrity, or re-create "
                            "the backup with a current build",
                cause=error.cause),
        }
        if mode == "json":
            print(_json_dump(payload), flush=True)
        else:
            print("backup: invalid (%s)" % error.code, file=sys.stderr)
            print("remediation: %s" % payload["error"]["remediation"],
                  file=sys.stderr)
        return 1
    _print_verify_result(result, args)
    return 0


# ---------------------------------------------------------------------------
# reserved maintenance commands
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# quarantine list / purge
# ---------------------------------------------------------------------------

def _cmd_quarantine_list(args, paths):
    from quarantine import (
        QUARANTINE_VERSION,
        list_quarantine,
    )
    mode = "json" if args.json else "human"
    try:
        entries = list_quarantine(paths["semantic_memory_root"],
                                  os.geteuid())
    except OperationError as error:
        return _store_operation_error(error, mode)
    payload = {
        "quarantine_version": QUARANTINE_VERSION,
        "count": len(entries),
        "entries": entries,
    }
    if args.json:
        print(_json_dump(payload), flush=True)
        return 0
    if not entries:
        print("quarantine: none")
        return 0
    for entry in entries:
        fingerprint = entry.get("fingerprint")
        created = entry.get("created_at_utc")
        total = entry.get("total_bytes")
        if not entry.get("valid"):
            print("quarantine %s (metadata unreadable)"
                  % entry["operation_id"])
            continue
        print("quarantine %s" % entry["operation_id"])
        print("  fingerprint: %s" % (fingerprint or "unknown"))
        print("  created: %s" % (created or "unknown"))
        if total is not None:
            print("  bytes: %s" % total)
        else:
            print("  bytes: unknown")
    return 0


def _cmd_quarantine_purge(args, paths):
    from quarantine import (
        QUARANTINE_VERSION,
        purge_quarantine,
    )
    mode = "json" if args.json else "human"
    try:
        removed = purge_quarantine(paths["semantic_memory_root"],
                                   args.operation_id,
                                   args.content_fingerprint, os.geteuid())
    except OperationError as error:
        # Usage-level (invalid id) exits 2; a refused purge (not found /
        # fingerprint mismatch) is a non-success outcome, exit 1.
        if error.code == "invalid_operation_id":
            return _store_operation_error(error, mode)
        _render_error(error.to_error_object(), mode)
        return 1
    payload = {
        "quarantine_version": QUARANTINE_VERSION,
        "purged": args.operation_id,
        "removed_bytes": removed,
    }
    if args.json:
        print(_json_dump(payload), flush=True)
    else:
        print("purged quarantine %s (%s bytes removed)"
              % (args.operation_id, removed))
    return 0


def _cmd_reserved(args, paths):
    command = _reserved_command_name(args)
    error = _not_implemented_error(command)
    _render_error(error, "json" if getattr(args, "json", False) else "human")
    return 2


def _reserved_command_name(args):
    return args.command


# ---------------------------------------------------------------------------
# rebuild
# ---------------------------------------------------------------------------

def _rebuild_parameters(args, paths):
    """Normalize the CLI rebuild flags into the operation parameters.

    ``--full`` and ``--index-only`` are mutually exclusive (usage error);
    ``--retry`` and ``--restart`` are mutually exclusive (a retry continues
    the staging, a restart discards it).  The derived root and the build
    target are resolved by the rebuild operation preview.
    """
    if args.full and args.index_only:
        error = make_error(
            "rebuild_mode_conflict", phase="cli",
            remediation="choose exactly one of --full or --index-only (or "
                        "neither for auto); they cannot be combined",
            cause=None)
        _render_error(error, "json" if args.json else "human")
        return None, 2
    if args.retry and args.restart:
        error = make_error(
            "rebuild_retry_restart_conflict", phase="cli",
            remediation="--retry continues an existing staging; --restart "
                        "discards it. Choose one",
            cause=None)
        _render_error(error, "json" if args.json else "human")
        return None, 2
    mode = MODE_FULL if args.full else (
        MODE_INDEX_ONLY if args.index_only else MODE_AUTO)
    if mode == MODE_FULL:
        # `--full` mints a NEW generation even when the fingerprint is
        # unchanged (spec #43).  The generation id is content-addressed, so
        # the mint needs a fresh rebuild tag -- one per explicit request.
        # The tag is part of the operation parameters (fixed before
        # creation), so a retry of the same operation reuses the identical
        # build target (idempotency key unchanged).
        import uuid as uuid_module
        rebuild_tag = "rebuild-full-%s" % uuid_module.uuid4().hex[:16]
    else:
        rebuild_tag = None
    return {
        "mode": mode,
        "derived_root": _rebuild_derived_root(paths),
        "retry_build_id": args.retry,
        "restart": bool(args.restart),
        "rebuild_tag": rebuild_tag,
    }, None

def _print_rebuild_result(record, args):
    if args.json:
        print(_json_dump(public_record(record)), flush=True)
        return
    result = record.get("result") or {}
    print("rebuild %s" % result.get("outcome", "completed"))
    print("  build: %s" % (result.get("build_id") or "unknown"))
    if result.get("generation_id"):
        print("  generation: %s" % result["generation_id"])
    print("  published: %s" % ("yes" if result.get("published") else "no"))
    if result.get("outcome") == "already_current":
        print("  the active generation already matches the desired "
              "identity; nothing was rebuilt")


def _find_rebuild_operation(store, build_id):
    """The operation id of a rebuild operation persisted with `build_id`,
    or None.  Scans only the operation records (never derives state)."""
    try:
        operation_ids = store.list_ids()
    except OperationError:
        return None
    for operation_id in operation_ids:
        try:
            record = store.load(operation_id)
        except OperationError:
            continue
        if record.get("type") != "rebuild":
            continue
        if record["parameters"].get("build_id") == build_id:
            return operation_id
    return None


def _resume_operation(store, args, mode, operation_id):
    """Resume an existing rebuild operation in explicit retry mode.

    ``--wait`` observes the persistent record until terminal (Ctrl-C only
    detaches, exit 130, never cancels); without it the retry executor is
    spawned and the CLI returns once the build job is durable (spec #43:
    默认在 build job 持久化后返回).
    """
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "squirrel-semantic-memory")
    if not args.wait:
        try:
            subprocess.Popen(
                [sys.executable, entry, "operation", "run", "--retry",
                 operation_id],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            return _store_operation_error(
                OperationError("executor_start_failed", phase="cli",
                               retryable=True,
                               cause={"error": error.strerror}), mode)
        if args.json:
            print(_json_dump({
                "operation_version": OPERATION_VERSION,
                "operation_id": operation_id,
                "type": "rebuild",
                "state": "running",
                "retry": True,
                "observed": False,
            }), flush=True)
        return 0

    def emit(entry):
        if not args.json:
            print(_human_event_line(entry), flush=True)

    # Explicit retry: `operation run --retry` clears the block (blocked
    # never auto-retries).
    current, failure_code = _watch_detached_operation(
        store, operation_id, emit, mode, "rebuild",
        extra_argv=("--retry",))
    if failure_code is not None:
        return failure_code

    if current["state"] in ("succeeded", "cancelled"):
        _print_rebuild_result(current, args)
        return 0
    if args.json:
        print(_json_dump(public_record(current)), flush=True)
    else:
        print("rebuild did not complete: state %s (phase %s)"
              % (current["state"], current["phase"]))
        if current.get("error") is not None:
            print("  error: %s" % current["error"]["code"])
            print("  remediation: %s"
                  % current["error"].get("remediation", ""))
    return 1


def _cmd_rebuild(args, paths):
    """Explicit manual rebuild (Habit130/squirrel#68).

    Creates (or idempotently returns) a `rebuild` operation whose
    ``build_id`` is fixed before creation, spawns the detached executor and
    returns once the build job is durable (spec #43: 默认在 build job 持久
    化后返回).  ``--wait`` observes the persistent record until terminal;
    Ctrl-C only detaches (exit 130), never cancels -- the durable build
    continues (AC68-6).
    """
    store = _operation_store(paths)
    mode = "json" if args.json else "human"
    try:
        store.open(create=False)
    except OperationError as error:
        return _store_operation_error(error, mode)

    parameters, failure = _rebuild_parameters(args, paths)
    if failure is not None:
        return failure

    if args.retry:
        # `--retry <build_id>` continues an EXISTING rebuild operation for
        # that build: locate the operation whose persisted build_id matches
        # and resume it (the operation record is the durable build job;
        # blocked never auto-retries -- the executor must run in explicit
        # retry mode, `operation run --retry`).  A retry never creates a
        # new operation and never changes the idempotency key.
        operation_id = _find_rebuild_operation(store, args.retry)
        if operation_id is None:
            error = make_error(
                "rebuild_not_found", phase="cli",
                remediation="the build_id does not match any persisted "
                            "rebuild operation; run rebuild first",
                cause={"build_id": args.retry})
            _render_error(error, mode)
            return 1
        current = store.load(operation_id)
        if current["state"] in ("succeeded", "cancelled", "failed"):
            # A terminal rebuild has nothing to retry: --retry continues a
            # blocked/incomplete staging, never a finished one (AC68-5).
            error = make_error(
                "rebuild_already_terminal", phase="cli",
                remediation="start a new rebuild for a fresh build; "
                            "--retry only continues a blocked or "
                            "incomplete staging",
                cause={"build_id": args.retry,
                       "state": current["state"]})
            _render_error(error, mode)
            return 1
        operation_id = _resume_operation(store, args, mode, operation_id)
        return operation_id

    # The build_id is resolved (read-only) before the operation exists so
    # the same target returns the same build_id and an auto already-current
    # request never creates an operation at all.  The same gates re-run in
    # the operation's preflight step.  The preview spec is the RebuildSpec
    # the registry's steps were built from (its seams and the executor
    # steps' seams can never disagree).
    from rebuild_operation import RebuildSpec
    registered = args.registry.get("rebuild")
    preview_spec = getattr(registered, "rebuild_spec", None)
    if not isinstance(preview_spec, RebuildSpec):
        # A host registry registered the bare OperationTypeSpec (no seam
        # wiring): fall back to the production RebuildSpec so the CLI
        # still resolves the build_id deterministically.
        preview_spec = _rebuild_spec(paths)
    preview = preview_spec.preview(parameters)
    if preview["refuse"] is not None:
        error = make_error(
            preview["refuse"]["code"], phase="cli", retryable=False,
            remediation=preview["refuse"]["remediation"],
            cause=preview["refuse"].get("cause"))
        _render_error(error, mode)
        return 1

    parameters["build_id"] = preview["build_id"]
    if preview["already_current"]:
        # auto + healthy matching active: succeeded immediately with
        # already_current; no operation record, no staging, no generation,
        # no rollback rotation (AC68-1).  The CLI reports the outcome
        # directly (nothing durable to wait on).
        if args.json:
            print(_json_dump({
                "rebuild_version": 1,
                "outcome": "already_current",
                "build_id": preview["build_id"],
                "active_generation_id": preview["active_generation_id"],
                "refuse": None,
            }), flush=True)
        else:
            print("rebuild already_current")
            print("  build: %s" % preview["build_id"])
            print("  the active generation already matches the desired "
                  "identity; nothing was rebuilt")
        return 0

    try:
        record = create_operation(store, args.registry, "rebuild",
                                  parameters)
    except OperationError as error:
        return _store_operation_error(error, mode)
    except ValueError as error:
        return _store_operation_error(
            OperationError("invalid_parameters", phase="cli",
                           retryable=False, cause={
                               "error": str(error)}), mode)

    operation_id = record["operation_id"]
    if args.json:
        # The operation id + build id must be observable before any build
        # work, but stdout must stay exactly one versioned terminal
        # document so a single json.loads(stdout) parses the whole run.
        # The compact started envelope therefore goes to stderr, a
        # separate channel that never pollutes the JSON stdout contract.
        print(_json_line({
            "operation_version": OPERATION_VERSION,
            "operation_id": operation_id,
            "type": "rebuild",
            "state": "running",
            "build_id": parameters["build_id"],
            "mode": parameters["mode"],
        }), flush=True, file=sys.stderr)
    else:
        print("rebuild started: operation %s (build %s)"
              % (operation_id, parameters["build_id"]))

    # Spec #43: 默认在 build job 持久化后返回 -- spawn the detached
    # executor and return immediately; only `--wait` observes the progress
    # (interrupting the wait detaches, never cancels -- the durable build
    # continues).
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "squirrel-semantic-memory")
    try:
        subprocess.Popen(
            [sys.executable, entry, "operation", "run", operation_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as error:
        return _store_operation_error(
            OperationError("executor_start_failed", phase="cli",
                           retryable=True, cause={"error": error.strerror}),
            mode)
    if not args.wait:
        if args.json:
            print(_json_dump({
                "operation_version": OPERATION_VERSION,
                "operation_id": operation_id,
                "type": "rebuild",
                "state": "running",
                "build_id": parameters["build_id"],
                "mode": parameters["mode"],
                "observed": False,
            }), flush=True)
        return 0

    def emit(entry):
        if not args.json:
            print(_human_event_line(entry), flush=True)

    current, failure_code = _watch_detached_operation(
        store, operation_id, emit, mode, "rebuild")
    if failure_code is not None:
        return failure_code

    if current["state"] in ("succeeded", "cancelled"):
        _print_rebuild_result(current, args)
        return 0
    if args.json:
        print(_json_dump(public_record(current)), flush=True)
    else:
        print("rebuild did not complete: state %s (phase %s)"
              % (current["state"], current["phase"]))
        if current.get("error") is not None:
            print("  error: %s" % current["error"]["code"])
            print("  remediation: %s"
                  % current["error"].get("remediation", ""))
    return 1


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def main(argv=None, registry=None):
    """Run the CLI. `registry` is the operation-type registry used by the
    internal `operation run` executor; production code passes None, which
    loads the production registry (`clear`, `backup.create`, `migrate`,
    `restore`, `rebuild`). Returns the process exit code.
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
