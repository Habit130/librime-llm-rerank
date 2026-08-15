#!/usr/bin/env python3
"""Persistent long-operation engine for the semantic memory CLI
(Habit130/squirrel#52).

This module owns the operation model, the persistent operation store, the
centralized state/phase transition constraints, the cancel protocol and the
step executor ("runner"). It is NOT a CLI: argument parsing and process
plumbing live in `cli.py`; `status` semantics stay in `status_core.py`; the
real maintenance operation types (backup/restore/clear/rebuild/quarantine)
arrive with later tickets (#54/#55/#57/#68) and register here.

Design contract (spec #43 "长操作、进度与幂等", "错误协议", "权限与安全"):

- An operation has a stable `operation_id` generated before any work starts
  and an idempotency contract keyed on it: the same operation ID with the
  same normalized parameters (fingerprinted together with the operation
  type) returns the existing operation/result; the same ID with different
  parameters is rejected (`operation_id_conflict`).
- Operation IDs are validated as a single safe filename component before
  every store access; `..`/`/` can never escape the operations directory.
- State is one of `queued | running | blocked | succeeded | failed |
  cancelled`; phase advances only along the phase list the operation
  recorded at creation (so an upgraded binary can never reinterpret a
  running operation's machine), never backwards, and never after a terminal
  state. `blocked` is a waitable outcome: `wait` returns it with exit 1 so
  the operator can fix the cause and explicitly retry (`run --retry`);
  `blocked` never auto-retries and a successful retry clears the stale
  error.
- The irreversible point is recorded per operation (`irreversible_phase`).
  Cancel is only honored in phases before it; at/after it the cancel request
  is answered with an explicit uncancellable result and the runner
  continues.
- Record mutation is linearizable: every read-modify-write is a
  compare-and-swap on the record revision (`rev`), re-applying the mutation
  to the freshest record on conflict. Creation is exclusive (hard-link
  rename that never overwrites), so racing creates can neither overwrite nor
  lose the idempotency comparison.
- The runner is stateless and crash-recoverable: it reads, executes one
  step, persists atomically, and repeats. A crash at any point leaves the
  previous complete record on disk, so recovery re-runs exactly from the
  persisted phase/progress. Steps must be idempotent by construction; the
  irreversible-publish pattern is to check the persistent artifact the step
  itself created before re-creating it (this is the "已完成不可逆步骤不会因
  重启重复执行" guarantee).
- Executor ownership is exclusive and crash-recoverable: a run lock under
  the stable semantic-memory root is held across the entire side-effecting
  invocation, and every record access is pinned to the operations-directory
  identity observed when that lock was acquired. A second executor yields;
  process death releases ownership automatically.
- Progress reports only real units (`events`, `bytes`, `chunks`, `phase`);
  a percentage is never fabricated when the total is unknown.
- The operation log stores only IDs, hashes, phases, progress units, states
  and error codes. It never stores 上文, candidate text, embeddings or other
  private input (parameters are stored once for the idempotency comparison,
  never echoed into log entries, error objects or the CLI's public JSON).
- The operations directory and files are owner-only (0700 / 0600), access
  is anchored to the operations directory fd (no symlink or path swap can
  redirect it), symlinks, foreign owners, loose permissions and root/sudo
  execution are refused.
"""

import errno
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
import uuid
from datetime import datetime, timezone

OPERATION_VERSION = 1
EVENT_VERSION = 1
ERROR_VERSION = 1
OPERATIONS_DIRNAME = "operations"
TERMINAL_STATES = ("succeeded", "failed", "cancelled")
STATES = ("queued", "running", "blocked", "succeeded", "failed", "cancelled")

# Canonical phase set (spec #43); individual operations record the ordered
# subset that applies to their type.
CANONICAL_PHASES = (
    "preflight",
    "waiting-for-quiesce",
    "staging",
    "publishing",
    "reopening",
    "catching-up",
    "cleanup",
)

PROGRESS_UNITS = ("events", "bytes", "chunks")
LOG_KINDS = ("transition", "progress", "cancel_requested", "terminal")
OUTCOMES = ("succeeded", "failed", "cancelled", "blocked")

SAFE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
MAX_ID_LENGTH = 64

_STABLE_MESSAGES = {
    "operation_not_found": "no such operation",
    "operation_id_conflict": "operation id already used with different "
                             "parameters",
    "unsupported_operation_type": "no executor is registered for this "
                                  "operation type",
    "invalid_operation_record": "the operation record is invalid or from an "
                                "unsupported version",
    "store_blocked": "the operation store cannot be safely accessed",
    "unsupported_privilege": "the CLI refuses to run with elevated "
                             "privileges",
    "operation_uncancellable": "the operation is past its irreversible "
                               "point and cannot be cancelled",
    "operation_already_terminal": "the operation already reached a terminal "
                                  "state",
    "deterministic_step_failure": "the operation failed deterministically "
                                  "and needs an explicit retry",
    "transient_step_failure": "the operation failed on a transient "
                              "condition",
    "not_implemented": "this command is reserved by the spec and not "
                       "implemented in this build",
    "unknown_schema": "no deployed schema matches the filter",
    "operation_conflict": "the operation changed concurrently; retry",
    "fixture_preflight_failed": "fixture preflight failed (test-only)",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def make_error(code, phase, retryable=False, remediation=None, cause=None):
    """Build the versioned error object (spec #43 "错误协议").

    Only stable codes and generic messages; never raw input text.
    """
    return {
        "error_version": ERROR_VERSION,
        "code": code,
        "message": _STABLE_MESSAGES.get(code, code),
        "occurred_at": _now_iso(),
        "retryable": bool(retryable),
        "phase": phase,
        "remediation": remediation or _default_remediation(retryable),
        "cause": cause,
    }


def _default_remediation(retryable):
    if retryable:
        return "retry the operation"
    return "fix the condition and explicitly retry"


class OperationError(Exception):
    """A protocol-level operation error with a stable code."""

    def __init__(self, code, phase="cli", retryable=False, remediation=None,
                 cause=None):
        super().__init__(code)
        self.code = code
        self.phase = phase
        self.retryable = retryable
        self.remediation = remediation
        self.cause = cause

    def to_error_object(self):
        return make_error(self.code, self.phase, self.retryable,
                          self.remediation, self.cause)


class OperationNotFound(OperationError):
    def __init__(self, operation_id):
        super().__init__("operation_not_found")
        self.operation_id = operation_id


class OperationIdConflict(OperationError):
    def __init__(self, operation_id):
        super().__init__("operation_id_conflict")
        self.operation_id = operation_id


class OperationConflict(OperationError):
    """A compare-and-swap lost its race; the caller re-reads and retries."""

    def __init__(self, operation_id):
        super().__init__("operation_conflict", phase="runner", retryable=True)
        self.operation_id = operation_id


class UnsupportedOperationType(OperationError):
    def __init__(self, operation_type):
        super().__init__("unsupported_operation_type")
        self.operation_type = operation_type


class StoreBlocked(OperationError):
    """The operation store cannot be safely used (owner/permission/symlink).

    `fault_code` mirrors the status_core vocabulary (root_symlink,
    root_permission, op_dir_symlink, operation_symlink, ...).
    """

    def __init__(self, fault_code):
        super().__init__("store_blocked", phase="cli",
                         cause={"fault_code": fault_code})
        self.fault_code = fault_code


class UnsupportedPrivilege(OperationError):
    def __init__(self):
        super().__init__("unsupported_privilege")


class OperationBlocked(OperationError):
    """Deterministic step failure: the operation goes to `blocked`."""

    def __init__(self, code="deterministic_step_failure", phase=None,
                 remediation=None, cause=None):
        super().__init__(code, phase=phase or "preflight", retryable=False,
                         remediation=remediation, cause=cause)


class OperationFailed(OperationError):
    """Transient (or otherwise final) step failure: `failed`."""

    def __init__(self, code="transient_step_failure", phase=None,
                 retryable=True, remediation=None, cause=None):
        super().__init__(code, phase=phase or "preflight", retryable=retryable,
                         remediation=remediation, cause=cause)


class SimulatedCrash(Exception):
    """Test seam: abort the runner between persist boundaries without
    persisting anything, exactly like a process kill at that point."""


class InvalidTransition(Exception):
    """Internal invariant: a state/phase transition was rejected."""


def validate_operation_id(operation_id):
    """An operation ID must be a single safe filename component: non-empty,
    no separators or dots, bounded length. This is enforced before every
    store access so `../` can never escape the operations directory."""
    if (not isinstance(operation_id, str) or not operation_id
            or len(operation_id) > MAX_ID_LENGTH
            or any(ch not in SAFE_ID_CHARS for ch in operation_id)):
        raise ValueError("invalid operation id: %r" % (operation_id,))


# ---------------------------------------------------------------------------
# State machine (centralized)
# ---------------------------------------------------------------------------

_STATE_TRANSITIONS = {
    "queued": ("running", "cancelled"),
    "running": ("blocked", "failed", "succeeded", "cancelled"),
    "blocked": ("running", "cancelled"),
    "succeeded": (),
    "failed": (),
    "cancelled": (),
}


def validate_state_transition(current, new_state):
    if current not in STATES or new_state not in STATES:
        raise InvalidTransition("unknown state")
    if new_state not in _STATE_TRANSITIONS[current]:
        raise InvalidTransition("illegal state transition %s -> %s"
                                % (current, new_state))
    return True


def _phase_index(record, phase):
    try:
        return record["phases"].index(phase)
    except ValueError:
        raise InvalidTransition("phase %s not in recorded phases" % phase)


def validate_phase_transition(record, new_phase):
    """A phase may only advance to its recorded successor (or stay).

    Phase lists are recorded at creation, so an upgraded binary can never
    move a persisted operation to a phase the operation was not created
    with, and a restart can never regress a phase.
    """
    if record["phase"] == new_phase:
        return True
    if new_phase not in record["phases"]:
        raise InvalidTransition("phase %s not in recorded phases" % new_phase)
    if record["phase"] not in record["phases"]:
        raise InvalidTransition("current phase %s not in recorded phases"
                                % record["phase"])
    expected = _phase_index(record, record["phase"]) + 1
    if _phase_index(record, new_phase) != expected:
        raise InvalidTransition("illegal phase transition %s -> %s"
                                % (record["phase"], new_phase))
    return True


def is_cancelable(record):
    """Cancel is honored only before the irreversible phase (spec #43)."""
    if record["state"] in TERMINAL_STATES:
        return False
    if record["state"] == "queued":
        return True
    if record["phase"] not in record["phases"]:
        return False
    return _phase_index(record, record["phase"]) < _phase_index(
        record, record["irreversible_phase"])


# ---------------------------------------------------------------------------
# Operation record model
# ---------------------------------------------------------------------------

REQUIRED_RECORD_FIELDS = (
    "operation_version", "operation_id", "type", "state", "phase", "phases",
    "irreversible_phase", "cancel_phase", "parameters",
    "parameters_fingerprint", "created_at", "updated_at",
    "cancel_requested", "cancel_requested_at", "progress", "result", "error",
    "log", "rev", "runner_claim",
)


def parameters_fingerprint(operation_type, normalized_parameters):
    """Deterministic hash of (operation type, canonical parameters), so two
    different command semantics can never share an idempotency key."""
    canonical = json.dumps([operation_type, normalized_parameters],
                           sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def new_operation(operation_type, normalized_parameters, phases,
                  irreversible_phase, operation_id=None, cancel_phase=None):
    """Build the initial operation record. The ID is generated before any
    work starts so it can be printed immediately (spec #43).

    `cancel_phase` is the extension seam for cancelled operations that must
    run compensation before going terminal (spec #43: restore/clear
    cancelled before the fact replacement reopen the old state): when a
    cancel is honored, the operation moves into `cancel_phase`, its steps
    run, and advancing from it goes to terminal `cancelled` instead of the
    next phase.
    """
    operation_id = operation_id or str(uuid.uuid4())
    validate_operation_id(operation_id)
    if not phases or irreversible_phase not in phases:
        raise ValueError("invalid phase machine for operation")
    if len(set(phases)) != len(phases):
        raise ValueError("duplicate phase in operation machine")
    for phase in phases:
        if phase not in CANONICAL_PHASES:
            raise ValueError("phase %s not in the canonical phase set" % phase)
    if cancel_phase is not None and cancel_phase not in phases:
        raise ValueError("cancel phase %s not in the operation machine"
                         % cancel_phase)
    if (cancel_phase is not None
            and phases.index(cancel_phase) <= phases.index(
                irreversible_phase)):
        raise ValueError("cancel phase must follow the irreversible phase")
    now = _now_iso()
    return {
        "operation_version": OPERATION_VERSION,
        "operation_id": operation_id,
        "type": operation_type,
        "state": "queued",
        "phase": phases[0],
        "phases": list(phases),
        "irreversible_phase": irreversible_phase,
        "cancel_phase": cancel_phase,
        "parameters": normalized_parameters,
        "parameters_fingerprint": parameters_fingerprint(
            operation_type, normalized_parameters),
        "created_at": now,
        "updated_at": now,
        "cancel_requested": False,
        "cancel_requested_at": None,
        "progress": {"events": 0, "bytes": 0, "chunks": 0},
        "result": None,
        "error": None,
        "log": [],
        "rev": 1,
        "runner_claim": None,
    }


def _valid_claim(value):
    if value is None:
        return True
    return (isinstance(value, dict)
            and type(value.get("pid")) is int and value["pid"] > 0
            and isinstance(value.get("token"), str) and value["token"]
            and _valid_timestamp(value.get("claimed_at")))


def _valid_timestamp(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_error(value):
    if value is None:
        return True
    required = {
        "error_version", "code", "message", "occurred_at", "retryable",
        "phase", "remediation", "cause",
    }
    return (isinstance(value, dict) and set(value) == required
            and value.get("error_version") == ERROR_VERSION
            and isinstance(value.get("code"), str) and value["code"]
            and isinstance(value.get("message"), str) and value["message"]
            and _valid_timestamp(value.get("occurred_at"))
            and isinstance(value.get("retryable"), bool)
            and isinstance(value.get("phase"), str) and value["phase"]
            and isinstance(value.get("remediation"), str)
            and isinstance(value.get("cause"), (dict, type(None))))


def _reject_duplicate_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def validate_record(record):
    """Structural validation of a persisted record.

    Total: for any bytes read from disk this returns True/False and never
    raises (all membership tests are guarded by type checks first, so
    malformed records produce a stable `operation_invalid` error instead of
    a TypeError). Rejects unsupported versions, unknown states/phases,
    broken or duplicated phase machines, non-contiguous log sequences
    (which would corrupt the next appended event), missing per-event
    fields, malformed progress units and invalid claims.
    """
    if not isinstance(record, dict):
        return False
    if record.get("operation_version") != OPERATION_VERSION:
        return False
    if set(record) != set(REQUIRED_RECORD_FIELDS):
        return False
    operation_id = record.get("operation_id")
    try:
        validate_operation_id(operation_id)
    except ValueError:
        return False
    operation_type = record.get("type")
    if not isinstance(operation_type, str) or not operation_type:
        return False
    parameters = record.get("parameters")
    if not isinstance(parameters, dict):
        return False
    fingerprint = record.get("parameters_fingerprint")
    try:
        expected_fingerprint = parameters_fingerprint(operation_type,
                                                       parameters)
    except (TypeError, ValueError):
        return False
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in fingerprint)
            or fingerprint != expected_fingerprint):
        return False
    if (not _valid_timestamp(record.get("created_at"))
            or not _valid_timestamp(record.get("updated_at"))):
        return False
    if not isinstance(record.get("cancel_requested"), bool):
        return False
    cancel_requested_at = record.get("cancel_requested_at")
    if cancel_requested_at is not None and not _valid_timestamp(
            cancel_requested_at):
        return False
    if record["cancel_requested"] and cancel_requested_at is None:
        return False
    if not isinstance(record.get("result"), (dict, type(None))):
        return False
    if not _valid_error(record.get("error")):
        return False
    state = record["state"]
    if not isinstance(state, str) or state not in STATES:
        return False
    rev = record.get("rev")
    if type(rev) is not int or rev < 1:
        return False
    if not _valid_claim(record.get("runner_claim")):
        return False
    phases = record["phases"]
    if not isinstance(phases, list) or not phases:
        return False
    if any(not isinstance(phase, str) for phase in phases):
        return False
    if len(set(phases)) != len(phases):
        return False
    if any(phase not in CANONICAL_PHASES for phase in phases):
        return False
    canonical_indexes = [CANONICAL_PHASES.index(phase) for phase in phases]
    if canonical_indexes != sorted(canonical_indexes):
        return False
    irreversible = record.get("irreversible_phase")
    if not isinstance(irreversible, str) or irreversible not in phases:
        return False
    cancel_phase = record.get("cancel_phase")
    if cancel_phase is not None and (not isinstance(cancel_phase, str)
                                     or cancel_phase not in phases):
        return False
    if (cancel_phase is not None
            and phases.index(cancel_phase) <= phases.index(irreversible)):
        return False
    phase = record["phase"]
    if not isinstance(phase, str) or phase not in phases:
        return False
    progress = record["progress"]
    if (not isinstance(progress, dict)
            or set(progress) != set(PROGRESS_UNITS)):
        return False
    for unit in PROGRESS_UNITS:
        value = progress.get(unit)
        if type(value) is not int or value < 0:
            return False
    log = record["log"]
    if not isinstance(log, list):
        return False
    for index, entry in enumerate(log):
        if not isinstance(entry, dict):
            return False
        allowed_event_fields = {
            "event_version", "seq", "at", "kind", "state", "phase",
            "progress", "error_code", "outcome",
        }
        if any(key not in allowed_event_fields for key in entry):
            return False
        seq = entry.get("seq")
        if type(seq) is not int or seq != index + 1:
            return False
        if entry.get("event_version") != EVENT_VERSION:
            return False
        at = entry.get("at")
        if not isinstance(at, str) or not at:
            return False
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in LOG_KINDS:
            return False
        entry_state = entry.get("state")
        if not isinstance(entry_state, str) or entry_state not in STATES:
            return False
        entry_phase = entry.get("phase")
        if not isinstance(entry_phase, str) or entry_phase not in phases:
            return False
        if kind == "progress":
            delta = entry.get("progress")
            if not isinstance(delta, dict) or not delta:
                return False
            for unit, value in delta.items():
                if (unit not in PROGRESS_UNITS or not isinstance(value, int)
                        or isinstance(value, bool) or value < 0):
                    return False
        if kind == "terminal":
            outcome = entry.get("outcome")
            if not isinstance(outcome, str) or outcome not in OUTCOMES:
                return False
        error_code = entry.get("error_code")
        if error_code is not None and not isinstance(error_code, str):
            return False
    return True


def _append_event(record, kind, state=None, phase=None, progress=None,
                  error_code=None, outcome=None):
    """Append a log event. Events carry only IDs, hashes, phases, progress
    units, states and error codes — never parameters or input text. Seq is
    contiguous with the existing log (validate_record guarantees the base
    is contiguous)."""
    entry = {
        "event_version": EVENT_VERSION,
        "seq": len(record["log"]) + 1,
        "at": _now_iso(),
        "kind": kind,
        "state": state,
        "phase": phase,
    }
    if progress is not None:
        entry["progress"] = progress
    if error_code is not None:
        entry["error_code"] = error_code
    if outcome is not None:
        entry["outcome"] = outcome
    record["log"].append(entry)


# ---------------------------------------------------------------------------
# Operation store (atomic, owner-only, symlink-rejecting, CAS)
# ---------------------------------------------------------------------------

def _exact_mode(path, mode):
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == mode
    except OSError:
        return False


class OperationStore:
    """Directory-backed operation persistence.

    One JSON record per operation under `<root>/operations/`, written
    atomically (temp file -> fsync -> rename -> directory fsync). Record
    access is anchored to directory fds (the root is opened by fd, the
    operations directory is opened relative to it, and every record is
    opened relative to that), so no path-based lookup happens between a
    security check and an access — a path swap cannot redirect anything;
    the final component is additionally opened with O_NOFOLLOW. Owner and
    exact mode (0700 dir / 0600 file) are verified per access. Operation
    IDs are validated as single safe filename components before every
    access.

    Mutation is linearizable: every read-modify-write goes through
    `mutate()`, which re-reads the record, re-applies the mutation to the
    freshest state and writes with a compare-and-swap on `rev`; the
    revision check and the atomic rename happen under a per-operation
    advisory lock (`<id>.lock`), so no writer can slip between them.
    Creation is exclusive via a hard-link rename that never overwrites an
    existing record.

    Executor ownership is a separate per-operation advisory lock
    (`<id>.run`) held by the runner for its whole invocation: a second
    executor probes it non-blocking and yields instead of executing, and
    because flock is kernel-released on process death, a crashed executor's
    ownership is reclaimed automatically — no wall-clock lease exists, so a
    live executor can never be taken over mid-step and a recycled pid can
    never wedge an operation. The record's `runner_claim` (pid/token/
    claimed_at) is advisory diagnostics: it identifies the current
    executor and is refreshed on every runner write.

    The store holds no in-memory state: every call re-reads the record,
    which is what makes the runner crash-recoverable by construction.
    """

    def __init__(self, root_dir, euid=None):
        self.root_dir = root_dir
        self.euid = os.geteuid() if euid is None else euid
        self.operations_dir = os.path.join(root_dir, OPERATIONS_DIRNAME)
        self._pinned_operations_identity = None

    def _verify_root_entry(self, create):
        """Verify the semantic-memory root is an owner-only real directory,
        creating it (0700) when missing and `create` is True. Returns True
        when the root exists afterwards, False when it is missing and
        `create` is False. Called by `open()` and by every per-access
        `_open_operations_dir`, so no data command can read or write
        through a misconfigured root."""
        if self.euid == 0:
            raise UnsupportedPrivilege()
        if not os.path.lexists(self.root_dir):
            if not create:
                return False
            os.makedirs(self.root_dir, mode=0o700, exist_ok=True)
            return True
        try:
            st = os.lstat(self.root_dir)
        except OSError:
            raise StoreBlocked("root_unavailable")
        if stat.S_ISLNK(st.st_mode):
            raise StoreBlocked("root_symlink")
        if not stat.S_ISDIR(st.st_mode):
            raise StoreBlocked("root_not_directory")
        if st.st_uid != self.euid:
            raise StoreBlocked("root_owner")
        if not _exact_mode(self.root_dir, 0o700):
            raise StoreBlocked("root_permission")
        return True

    def _verify_operations_entry(self, create):
        """Verify the operations directory is an owner-only real directory,
        creating it (0700) when missing and `create` is True. Returns True
        when the directory exists afterwards, False when it is missing and
        `create` is False."""
        if not os.path.lexists(self.operations_dir):
            if not create:
                return False
            os.makedirs(self.operations_dir, mode=0o700, exist_ok=True)
            return True
        try:
            st = os.lstat(self.operations_dir)
        except OSError:
            raise StoreBlocked("op_dir_unavailable")
        if stat.S_ISLNK(st.st_mode):
            raise StoreBlocked("op_dir_symlink")
        if not stat.S_ISDIR(st.st_mode):
            raise StoreBlocked("op_dir_not_directory")
        if st.st_uid != self.euid:
            raise StoreBlocked("op_dir_owner")
        if not _exact_mode(self.operations_dir, 0o700):
            raise StoreBlocked("op_dir_permission")
        return True

    def open(self, create=True):
        """Verify (and by default create) the root and operations directory
        with owner-only permissions. With `create=False` a missing root is
        left untouched (read-only commands report no operations instead).
        Raises StoreBlocked / UnsupportedPrivilege. Every individual record
        access re-verifies these checks via `_open_operations_dir`, so a
        command that skips `open()` is still gated."""
        if self._verify_root_entry(create):
            self._verify_operations_entry(create)
        return self

    def _open_root_dir(self):
        if self.euid == 0:
            raise UnsupportedPrivilege()
        try:
            root_fd = os.open(self.root_dir, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StoreBlocked("root_symlink")
            raise StoreBlocked("root_unavailable")
        try:
            st = os.fstat(root_fd)
            if not stat.S_ISDIR(st.st_mode):
                raise StoreBlocked("root_not_directory")
            if st.st_uid != self.euid:
                raise StoreBlocked("root_owner")
            if not stat.S_IMODE(st.st_mode) == 0o700:
                raise StoreBlocked("root_permission")
        except StoreBlocked:
            os.close(root_fd)
            raise
        except OSError:
            os.close(root_fd)
            raise StoreBlocked("root_unavailable")
        return root_fd

    def _open_operations_from_root(self, root_fd):
        try:
            dfd = os.open(OPERATIONS_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                          dir_fd=root_fd)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StoreBlocked("op_dir_symlink")
            if error.errno == errno.ENOENT:
                # A store that has never held operations cannot hold this
                # operation either; callers map this to not-found.
                raise StoreBlocked("op_dir_unavailable")
            raise StoreBlocked("op_dir_unreadable")
        try:
            st = os.fstat(dfd)
            if not stat.S_ISDIR(st.st_mode):
                raise StoreBlocked("op_dir_not_directory")
            if st.st_uid != self.euid:
                raise StoreBlocked("op_dir_owner")
            if not stat.S_IMODE(st.st_mode) == 0o700:
                raise StoreBlocked("op_dir_permission")
            identity = (st.st_dev, st.st_ino)
            if (self._pinned_operations_identity is not None
                    and identity != self._pinned_operations_identity):
                raise StoreBlocked("op_dir_replaced")
        except StoreBlocked:
            os.close(dfd)
            raise
        except OSError:
            os.close(dfd)
            raise StoreBlocked("op_dir_unreadable")
        return dfd

    def _open_operations_dir(self):
        """Open root and `operations/` by fd, enforcing a runner's pinned
        directory identity when one is active on this store instance."""
        root_fd = self._open_root_dir()
        try:
            return self._open_operations_from_root(root_fd)
        finally:
            os.close(root_fd)

    def _open_lock_file(self, dfd, lock_name):
        """Open an advisory lock file (0600, O_NOFOLLOW) via the directory
        fd. O_EXCL create with a plain-open fallback: concurrent O_CREAT of
        the same name through two directory fds intermittently returns
        ENOENT on macOS (kernel lookup race) even though the file exists; a
        racing create here surfaces as EEXIST instead, which is handled by
        reopening the existing lock file."""
        try:
            try:
                fd = os.open(lock_name,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
                try:
                    os.fchmod(fd, 0o600)
                except OSError:
                    os.close(fd)
                    raise
                return fd
            except OSError as error:
                if error.errno != errno.EEXIST:
                    raise
                return os.open(lock_name, os.O_WRONLY | os.O_NOFOLLOW,
                               dir_fd=dfd)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StoreBlocked("operation_lock_symlink")
            raise StoreBlocked("operation_lock_unavailable")

    def _verify_lock_file(self, fd):
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise StoreBlocked("operation_lock_not_regular")
        if st.st_uid != self.euid:
            raise StoreBlocked("operation_lock_owner")
        if not stat.S_IMODE(st.st_mode) == 0o600:
            raise StoreBlocked("operation_lock_permission")

    def _acquire_record_lock(self, dfd, name):
        """Take the per-operation write lock (`<id>.lock`, flock EX). The
        lock serializes the CAS revision check with the atomic rename in
        `_write_record`, so no writer can slip between the check and the
        rename; it also serializes racing creators. Kernel-released on
        process death."""
        lock_fd = self._open_lock_file(
            dfd, "%s.lock" % name[: -len(".json")])
        try:
            self._verify_lock_file(lock_fd)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except StoreBlocked:
            os.close(lock_fd)
            raise
        except OSError:
            os.close(lock_fd)
            raise StoreBlocked("operation_lock_unavailable")
        return lock_fd

    def acquire_run_lock(self, operation_id):
        """Take the root-anchored per-operation executor lock.

        The lock lives outside the replaceable `operations/` directory. The
        directory identity observed here is pinned for every runner access,
        so swapping the directory cannot fork ownership across lock inodes.
        """
        try:
            validate_operation_id(operation_id)
        except ValueError:
            raise OperationNotFound(operation_id)
        root_fd = self._open_root_dir()
        dfd = None
        try:
            dfd = self._open_operations_from_root(root_fd)
            st = os.fstat(dfd)
            identity = (st.st_dev, st.st_ino)
            name = self._record_name(operation_id)
            lock_fd = self._open_lock_file(
                root_fd, ".operation-%s.run" % name[: -len(".json")])
        except StoreBlocked:
            if dfd is not None:
                os.close(dfd)
            os.close(root_fd)
            raise
        except OSError:
            if dfd is not None:
                os.close(dfd)
            os.close(root_fd)
            raise StoreBlocked("operation_lock_unavailable")
        try:
            self._verify_lock_file(lock_fd)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._pinned_operations_identity = identity
                return (root_fd, dfd, lock_fd)
            except BlockingIOError:
                os.close(lock_fd)
                os.close(dfd)
                os.close(root_fd)
                return None
        except StoreBlocked:
            os.close(lock_fd)
            os.close(dfd)
            os.close(root_fd)
            raise
        except OSError:
            os.close(lock_fd)
            os.close(dfd)
            os.close(root_fd)
            raise StoreBlocked("operation_lock_unavailable")

    def release_run_lock(self, lock):
        root_fd, dfd, lock_fd = lock
        self._pinned_operations_identity = None
        os.close(lock_fd)
        os.close(dfd)
        os.close(root_fd)

    def _record_name(self, operation_id):
        validate_operation_id(operation_id)
        return "%s.json" % operation_id

    def _read_via_dfd(self, dfd, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StoreBlocked("operation_symlink")
            raise OperationNotFound(name[: -len(".json")])
        try:
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                st = os.fstat(f.fileno())
                if not stat.S_ISREG(st.st_mode):
                    raise StoreBlocked("operation_not_regular")
                if st.st_uid != self.euid:
                    raise StoreBlocked("operation_owner")
                if not stat.S_IMODE(st.st_mode) == 0o600:
                    raise StoreBlocked("operation_permission")
                payload = f.read()
        except StoreBlocked:
            raise
        except (OSError, UnicodeError):
            raise StoreBlocked("operation_unreadable")
        try:
            record = json.loads(
                payload, object_pairs_hook=_reject_duplicate_object_pairs)
        except (ValueError, UnicodeDecodeError):
            raise StoreBlocked("operation_unreadable")
        try:
            valid = validate_record(record)
        except Exception:
            # Validation must be total; a validator bug must still surface
            # as the stable invalid-record error, never a traceback.
            valid = False
        if not valid:
            raise StoreBlocked("operation_invalid")
        if record["operation_id"] != name[: -len(".json")]:
            raise StoreBlocked("operation_invalid")
        return record

    def _read_record(self, operation_id):
        try:
            name = self._record_name(operation_id)
        except ValueError:
            raise OperationNotFound(operation_id)
        try:
            dfd = self._open_operations_dir()
        except StoreBlocked as error:
            if error.fault_code in ("op_dir_unavailable", "root_unavailable"):
                # A store that has never held operations cannot have this
                # operation either.
                raise OperationNotFound(operation_id)
            raise
        try:
            return self._read_via_dfd(dfd, name)
        finally:
            os.close(dfd)

    def _write_bytes(self, fd, payload):
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write stalled")
            view = view[written:]

    def _write_record(self, record, operation_id, expected_rev=None):
        """Atomic persist: temp file (0600, O_NOFOLLOW) -> fsync -> rename
        -> directory fsync, all relative to the operations directory fd and
        under the per-operation write lock. A crash at any point leaves the
        previous complete record (or no record for a fresh create) in
        place.

        With `expected_rev` the write is a compare-and-swap: the revision
        check and the rename happen under the per-operation flock, so a
        concurrent writer can neither slip between them nor overwrite the
        record; a lost CAS raises OperationConflict and changes nothing.
        The record is validated before it is published, so a malformed
        mutation can never reach disk.
        """
        if not validate_record(record):
            raise OperationError("invalid_operation_record", phase="runner")
        record["updated_at"] = _now_iso()
        dfd = self._open_operations_dir()
        lock_fd = None
        try:
            name = self._record_name(operation_id)
            lock_fd = self._acquire_record_lock(dfd, name)
            if expected_rev is not None:
                try:
                    current = self._read_via_dfd(dfd, name)
                except OperationNotFound:
                    raise OperationConflict(operation_id)
                if current["rev"] != expected_rev:
                    raise OperationConflict(operation_id)
            tmp = "%s.tmp-%d-%s" % (name, os.getpid(), uuid.uuid4().hex[:8])
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            try:
                os.fchmod(fd, 0o600)
                record["rev"] = (record["rev"] or 1) + 1
                payload = json.dumps(record, ensure_ascii=False,
                                     indent=2).encode("utf-8")
                self._write_bytes(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
            except OSError:
                try:
                    os.unlink(tmp, dir_fd=dfd)
                except OSError:
                    pass
                raise
            os.fsync(dfd)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(dfd)

    def create(self, record):
        """Exclusive create: the record is linked into place with a
        hard-link rename that never overwrites, under the per-operation
        advisory lock. A racing creator either loses (and idempotently
        returns the existing record, or is rejected with
        OperationIdConflict for different parameters) or wins."""
        if not validate_record(record):
            raise OperationError("invalid_operation_record", phase="runner")
        operation_id = record["operation_id"]
        validate_operation_id(operation_id)
        dfd = self._open_operations_dir()
        lock_fd = None
        try:
            name = self._record_name(operation_id)
            lock_fd = self._acquire_record_lock(dfd, name)
            tmp = "%s.tmp-%d-%s" % (name, os.getpid(), uuid.uuid4().hex[:8])
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            try:
                os.fchmod(fd, 0o600)
                payload = json.dumps(record, ensure_ascii=False,
                                     indent=2).encode("utf-8")
                self._write_bytes(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
            except OSError as error:
                if error.errno != errno.EEXIST:
                    try:
                        os.unlink(tmp, dir_fd=dfd)
                    except OSError:
                        pass
                    raise
                # Lost the creation race: return the winner under the
                # idempotency contract.
                try:
                    os.unlink(tmp, dir_fd=dfd)
                except OSError:
                    pass
                try:
                    existing = self._read_via_dfd(dfd, name)
                except OperationNotFound:
                    raise OperationConflict(operation_id)
                if existing["parameters_fingerprint"] != record[
                        "parameters_fingerprint"]:
                    raise OperationIdConflict(operation_id)
                return existing
            os.unlink(tmp, dir_fd=dfd)
            os.fsync(dfd)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(dfd)
        return self._read_record(operation_id)

    def load(self, operation_id):
        return self._read_record(operation_id)

    def list_ids(self):
        try:
            dfd = self._open_operations_dir()
        except StoreBlocked as error:
            if error.fault_code in ("op_dir_unavailable", "root_unavailable"):
                # A store that never held operations has no operations.
                return []
            raise
        try:
            names = os.listdir(dfd)
        except OSError:
            return []
        finally:
            os.close(dfd)
        result = []
        for name in names:
            if name.endswith(".json"):
                result.append(name[: -len(".json")])
        return sorted(result)

    def mutate(self, operation_id, fn, attempts=64):
        """Linearizable read-modify-write.

        Re-reads the record, re-applies `fn` to the freshest state (the
        mutation must be safe to re-apply), and CAS-writes it. `fn(record)`
        returns True when the record changed and must be written, False
        when no write is needed. Raises OperationConflict if the CAS keeps
        losing (persistent concurrent writers).
        """
        for _ in range(attempts):
            record = self.load(operation_id)
            changed = fn(record)
            if not changed:
                return record
            try:
                self._write_record(record, operation_id,
                                   expected_rev=record["rev"])
            except OperationConflict:
                continue
            return record
        raise OperationConflict(operation_id)


# ---------------------------------------------------------------------------
# Operation type registry and runner
# ---------------------------------------------------------------------------

class OperationTypeSpec:
    """One operation type's machine and step functions.

    Later tickets (#54/#55/#57/#68) register their types here; #52 ships no
    production type. `normalize` returns the canonical parameter dict that is
    persisted (and fingerprinted, together with the operation type) for the
    idempotency comparison; a step receives the current record and returns
    a dict with any of:

      progress: delta of real units {events|bytes|chunks: int}
      advance:  True to move to the recorded successor phase
      result:   final result payload (only meaningful with advance on the
                last phase -> state becomes succeeded)

    A step may raise OperationBlocked (deterministic -> blocked), Operation
    Failed (transient -> failed) or SimulatedCrash (test seam: abort without
    persisting anything). Steps must be idempotent by construction; the
    irreversible-publish pattern is to check the persistent artifact the
    step itself created before creating it. `cancel_phase` names the phase
    a cancelled operation moves into so its compensation steps run before
    terminal `cancelled` (restore/clear reopen their old state there).
    """

    def __init__(self, operation_type, phases, irreversible_phase,
                 normalize, steps, cancel_phase=None):
        self.operation_type = operation_type
        self.phases = tuple(phases)
        self.irreversible_phase = irreversible_phase
        self.cancel_phase = cancel_phase
        self.normalize = normalize
        self.steps = dict(steps)

    def new_record(self, parameters, operation_id=None):
        return new_operation(self.operation_type,
                             self.normalize(parameters),
                             self.phases, self.irreversible_phase,
                             operation_id=operation_id,
                             cancel_phase=self.cancel_phase)


class OperationRegistry:
    def __init__(self):
        self._specs = {}

    def register(self, spec):
        self._specs[spec.operation_type] = spec

    def get(self, operation_type):
        return self._specs.get(operation_type)


def create_operation(store, registry, operation_type, parameters,
                     operation_id=None):
    """Create or idempotently return an operation.

    Same operation ID + same normalized parameters -> existing operation;
    same ID + different parameters -> OperationIdConflict; the operation ID
    is generated before any work and returned immediately. Creation is
    exclusive: racing creators cannot overwrite each other.
    """
    spec = registry.get(operation_type)
    if spec is None:
        raise UnsupportedOperationType(operation_type)
    store.open()
    record = spec.new_record(parameters, operation_id=operation_id)
    return store.create(record)


def _classify_cancel(record):
    if record["state"] == "cancelled":
        return "already_cancelled"
    if record["state"] in ("succeeded", "failed"):
        return "terminal"
    if not is_cancelable(record):
        return "uncancellable"
    return "requested"


def cancel_operation(store, operation_id):
    """Request cancellation. Honored by the runner at its cancel checkpoint
    in cancelable (pre-irreversible) phases — moving into the operation's
    `cancel_phase` when one is recorded — or immediately for a `blocked`
    operation without a cancel phase (no executor is in flight, so the
    cancel takes effect without waiting for a retry); past the irreversible
    point an explicit uncancellable result is returned and the operation
    continues to finish. The request is written with the store's CAS, so a
    concurrently running executor can never overwrite it."""
    store.open(create=False)
    while True:
        record = store.load(operation_id)
        disposition = _classify_cancel(record)
        if disposition != "requested":
            return record, disposition
        if record["state"] == "blocked" and not record.get("cancel_phase"):
            def cancel_blocked(record):
                if record["state"] != "blocked" or not is_cancelable(record):
                    return False
                validate_state_transition(record["state"], "cancelled")
                _append_event(record, "terminal", state="cancelled",
                              phase=record["phase"], outcome="cancelled")
                record["state"] = "cancelled"
                return True
            updated = store.mutate(operation_id, cancel_blocked)
            if updated["state"] == "cancelled":
                return updated, "requested"
            continue

        def apply(record):
            if _classify_cancel(record) != "requested":
                return False
            if record["cancel_requested"]:
                return False
            record["cancel_requested"] = True
            record["cancel_requested_at"] = _now_iso()
            _append_event(record, "cancel_requested", state=record["state"],
                          phase=record["phase"])
            return True

        updated = store.mutate(operation_id, apply)
        if updated["cancel_requested"]:
            return updated, "requested"


def _step_index_in_phase(record, phase):
    return len([entry for entry in record["log"]
                if entry.get("kind") == "progress"
                and entry.get("phase") == phase])


def make_runner_claim():
    """A fresh executor identity (pid, token, claimed_at). Sequential
    runner invocations of one executor (the CLI `operation run` loop) pass
    the same claim; concurrent invocations use distinct ones. The claim is
    advisory — ownership is the per-operation run lock — but it identifies
    the current executor in the record for diagnostics."""
    return {"pid": os.getpid(), "token": str(uuid.uuid4()),
            "claimed_at": _now_iso()}


def _refresh_claim(record, claim):
    """Advisory executor identity, refreshed on every runner write so the
    record always shows the current owner's pid, token and time."""
    record["runner_claim"] = {"pid": claim["pid"], "token": claim["token"],
                              "claimed_at": _now_iso()}


def _claim_and_start_transform(record, claim, retry_blocked):
    if record["state"] == "queued":
        _refresh_claim(record, claim)
        record["state"] = "running"
        _append_event(record, "transition", state="running",
                      phase=record["phase"])
        return True
    if record["state"] == "blocked" and retry_blocked:
        # Explicit operator retry: clear the stale error.
        _refresh_claim(record, claim)
        record["state"] = "running"
        record["error"] = None
        _append_event(record, "transition", state="running",
                      phase=record["phase"])
        return True
    return False


def _cancel_checkpoint_transform(record):
    """Honor a pending cancel. With a `cancel_phase` the operation moves
    there so its compensation steps (reopen/cleanup) run before terminal
    `cancelled` (spec #43: restore/clear cancelled before the fact
    replacement reopen the old state); without one, the operation goes
    terminal immediately."""
    if not (record["cancel_requested"] and is_cancelable(record)):
        return False
    cancel_phase = record.get("cancel_phase")
    if cancel_phase and record["phase"] != cancel_phase:
        if record["state"] in ("queued", "blocked"):
            validate_state_transition(record["state"], "running")
            record["state"] = "running"
            record["error"] = None
        _append_event(record, "transition", state="running",
                      phase=cancel_phase)
        record["phase"] = cancel_phase
        return True
    if cancel_phase and record["phase"] == cancel_phase:
        # The compensation steps are running; terminal comes from their
        # advance.
        return False
    validate_state_transition(record["state"], "cancelled")
    _append_event(record, "terminal", state="cancelled",
                  phase=record["phase"], outcome="cancelled")
    record["state"] = "cancelled"
    return True


def _fail_unsupported_transform(record, claim):
    _refresh_claim(record, claim)
    record["error"] = make_error("unsupported_operation_type",
                                 phase=record["phase"])
    _append_event(record, "terminal", state="failed",
                  phase=record["phase"], outcome="failed",
                  error_code="unsupported_operation_type")
    record["state"] = "failed"
    return True


def _mark_step_error_transform(record, claim, phase, error, state):
    if record["phase"] != phase or record["state"] != "running":
        # A concurrent writer moved the operation; the loop re-evaluates
        # (re-application safety: never clobber a terminal state).
        return False
    _refresh_claim(record, claim)
    if record["cancel_requested"] and is_cancelable(record):
        return _cancel_checkpoint_transform(record)
    record["error"] = error.to_error_object()
    _append_event(record, "terminal", state=state, phase=phase,
                  outcome=state, error_code=error.code)
    record["state"] = state
    return True


def _apply_step_result_transform(record, claim, phase, result):
    if record["phase"] != phase:
        # A concurrent writer moved the phase; the loop re-evaluates.
        return False
    _refresh_claim(record, claim)
    progress = result.get("progress")
    if progress:
        for unit in PROGRESS_UNITS:
            if unit in progress:
                record["progress"][unit] += int(progress[unit])
        _append_event(record, "progress", state=record["state"],
                      phase=phase, progress=dict(progress))
    if result.get("advance"):
        if (record["cancel_requested"] and is_cancelable(record)
                and record["phase"] != record.get("cancel_phase")):
            # A cancel landed while this step executed; the advance into
            # the next phase is held so the runner's checkpoint can cancel
            # before the irreversible point (the progress made by the step
            # is still real and stays persisted).
            return True
        if phase == record.get("cancel_phase") and record["cancel_requested"]:
            # Advancing from the compensation phase finishes the cancel.
            # The guard matters: an operation whose cancel phase is also a
            # regular phase (restore/clear's reopening) must advance
            # normally when no cancel was ever requested.
            record["error"] = None
            _append_event(record, "terminal", state="cancelled",
                          phase=phase, outcome="cancelled")
            record["state"] = "cancelled"
        elif phase == record["phases"][-1]:
            record["result"] = result.get("result") or {"completed": True}
            record["error"] = None
            _append_event(record, "terminal", state="succeeded",
                          phase=phase, outcome="succeeded")
            record["state"] = "succeeded"
        else:
            new_phase = record["phases"][_phase_index(record, phase) + 1]
            validate_phase_transition(record, new_phase)
            _append_event(record, "transition", state="running",
                          phase=new_phase)
            record["phase"] = new_phase
    return True


def try_run_pending_steps(store, registry, operation_id, *, fault_hook=None,
                          max_steps=None, retry_blocked=False, claim=None):
    """Execute pending work for one operation.

    The runner first takes the per-operation executor lock (`<id>.run`,
    flock): while another live executor holds it the runner yields without
    executing anything, and because flock is kernel-released on process
    death, a crashed executor's ownership is reclaimed automatically and no
    wall-clock lease can ever let a live executor be taken over mid-step.
    `claim` is the executor identity recorded on the operation (advisory
    diagnostics); sequential continuation passes the same claim.

    Loop: read record -> cancel checkpoint -> (queued -> running; blocked ->
    running only on an explicit retry) -> execute one step -> CAS-persist ->
    repeat. A crash anywhere only loses the step that had not finished
    persisting, so restarting the runner resumes from the persisted phase
    and progress. Every write is CAS'd on the record revision under the
    per-operation write lock, so a concurrent cancel is never overwritten
    and the phase machine can never move backwards; a cancel that lands
    while a step runs holds that step's phase advance so the checkpoint can
    cancel before the irreversible point. `fault_hook(phase, step_index,
    point)` is the crash/fault injection seam used by tests (point is
    "before_step" or "after_step"); raising SimulatedCrash aborts without
    persisting, raising OperationBlocked/Failed injects those outcomes.
    `max_steps` bounds the number of step executions (transitions are not
    counted) for deterministic test stepping. `retry_blocked` marks this
    invocation as the explicit operator retry that a `blocked` operation
    requires (spec: blocked is deterministic and never auto-retries; `wait`
    and any other observer never retry).

    Returns `(record, acquired)`. `acquired` is False only when another
    executor owns the run lock; callers must yield rather than retry-loop.
    """
    store.open()
    claim = claim or make_runner_claim()
    lock = store.acquire_run_lock(operation_id)
    if lock is None:
        # Another live executor holds the operation; yield without
        # executing (exclusive ownership).
        return store.load(operation_id), False
    try:
        steps_executed = 0
        while True:
            record = store.load(operation_id)
            if record["state"] in TERMINAL_STATES:
                return record, True
            if record["cancel_requested"] and is_cancelable(record):
                record = store.mutate(operation_id,
                                      _cancel_checkpoint_transform)
                if record["state"] == "cancelled":
                    return record, True
                # A cancel_phase was entered: continue so the compensation
                # steps run before the terminal cancelled.
                continue
            if record["state"] == "blocked" and not retry_blocked:
                return record, True
            if record["state"] in ("queued", "blocked"):
                record = store.mutate(
                    operation_id, lambda r: _claim_and_start_transform(
                        r, claim, retry_blocked))
                continue
            if max_steps is not None and steps_executed >= max_steps:
                return record, True
            spec = registry.get(record["type"])
            if spec is None:
                record = store.mutate(
                    operation_id, lambda r: _fail_unsupported_transform(
                        r, claim))
                return record, True
            phase = record["phase"]
            step_index = _step_index_in_phase(record, phase)
            try:
                if fault_hook is not None:
                    fault_hook(phase, step_index, "before_step")
                result = spec.steps[phase](record)
                if fault_hook is not None:
                    fault_hook(phase, step_index, "after_step")
            except SimulatedCrash:
                raise
            except OperationBlocked as error:
                record = store.mutate(
                    operation_id, lambda r: _mark_step_error_transform(
                        r, claim, phase, error, "blocked"))
                if record["state"] == "running":
                    continue
                return record, True
            except OperationFailed as error:
                record = store.mutate(
                    operation_id, lambda r: _mark_step_error_transform(
                        r, claim, phase, error, "failed"))
                if record["state"] == "running":
                    continue
                return record, True
            steps_executed += 1
            record = store.mutate(
                operation_id, lambda r: _apply_step_result_transform(
                    r, claim, phase, result))
    finally:
        store.release_run_lock(lock)


def run_pending_steps(store, registry, operation_id, *, fault_hook=None,
                      max_steps=None, retry_blocked=False, claim=None):
    """Compatibility wrapper returning only the operation record."""
    record, _ = try_run_pending_steps(
        store, registry, operation_id, fault_hook=fault_hook,
        max_steps=max_steps, retry_blocked=retry_blocked, claim=claim)
    return record


def wait_for_terminal(store, operation_id, *, poll_interval=0.25,
                      timeout_s=None, emit=None):
    """Observe an operation until it reaches a terminal state or `blocked`
    (blocked needs a human fix and an explicit retry, so waiting stops with
    exit 1 instead of polling forever).

    Only observes: interruption by the caller (KeyboardInterrupt) never
    cancels the operation. `emit(entry)` receives each unseen log event in
    seq order; returns (record, outcome) where outcome is one of
    succeeded/failed/cancelled/blocked or None on timeout.
    """
    store.open(create=False)
    last_seq = 0
    deadline = None
    if timeout_s is not None:
        deadline = time.monotonic() + timeout_s
    while True:
        record = store.load(operation_id)
        for entry in record["log"]:
            if entry["seq"] > last_seq:
                if emit is not None:
                    emit(entry)
                last_seq = entry["seq"]
        if record["state"] in TERMINAL_STATES or record["state"] == "blocked":
            return record, record["state"]
        if deadline is not None and time.monotonic() >= deadline:
            return record, None
        time.sleep(poll_interval)


def operation_outcome_exit_code(outcome):
    """Deterministic exit code for wait: 0 for succeeded and cancelled
    (intentional outcomes), 1 for failed/blocked, 2 for a timeout."""
    if outcome in ("succeeded", "cancelled"):
        return 0
    if outcome in ("failed", "blocked"):
        return 1
    return 2


def _scrub_private(node):
    """Recursively drop `parameters` (the idempotency credential) from any
    output-bound structure, including error `cause` and `result` payloads,
    so a future step can never leak private input through CLI output."""
    if isinstance(node, dict):
        return {key: _scrub_private(value) for key, value in node.items()
                if key != "parameters"}
    if isinstance(node, list):
        return [_scrub_private(item) for item in node]
    return node


def public_record(record):
    """The sanitized snapshot for CLI output: everything except the
    parameters, which are the idempotency credential and must never leave
    the owner-only store (privacy contract). The fingerprint stays."""
    return _scrub_private(record)


if __name__ == "__main__":
    print("operations.py is a library module; use the "
          "squirrel-semantic-memory CLI.", file=sys.stderr)
    sys.exit(2)
