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
  same normalized parameters returns the existing operation/result; the same
  ID with different parameters is rejected (`operation_id_conflict`).
- State is one of `queued | running | blocked | succeeded | failed |
  cancelled`; phase advances only along the phase list the operation recorded
  at creation (so an upgraded binary can never reinterpret a running
  operation's machine), never backwards, and never after a terminal state.
- The irreversible point is recorded per operation (`irreversible_phase`).
  Cancel is only honored in phases before it; at/after it the cancel request
  is answered with an explicit uncancellable result and the runner continues.
- The runner is stateless: it reads, executes one step, persists atomically,
  and repeats. A crash at any point leaves the previous complete record on
  disk, so recovery re-runs exactly from the persisted phase/progress. Steps
  must be idempotent by construction; the irreversible-publish pattern is to
  check the persistent artifact the step itself created before re-creating it
  (this is the "已完成不可逆步骤不会因重启重复执行" guarantee).
- Progress reports only real units (`events`, `bytes`, `chunks`, `phase`);
  a percentage is never fabricated when the total is unknown.
- The operation log stores only IDs, hashes, phases, progress units, states
  and error codes. It never stores 上文, candidate text, embeddings or other
  private input (parameters are stored once for the idempotency comparison,
  never echoed into log entries or error objects).
- The operations directory and files are owner-only (0700 / 0600); symlinks,
  foreign owners, loose permissions and root/sudo execution are refused.
"""

import hashlib
import json
import os
import stat
import sys
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
    "irreversible_phase", "parameters", "parameters_fingerprint",
    "created_at", "updated_at", "cancel_requested", "cancel_requested_at",
    "progress", "result", "error", "log",
)

FINGERPRINT_PARAMETERS = 1


def parameters_fingerprint(normalized_parameters):
    """Deterministic hash of the canonical parameter JSON."""
    canonical = json.dumps(normalized_parameters, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def new_operation(operation_type, normalized_parameters, phases,
                  irreversible_phase, operation_id=None):
    """Build the initial operation record. The ID is generated before any
    work starts so it can be printed immediately (spec #43)."""
    operation_id = operation_id or str(uuid.uuid4())
    if not phases or irreversible_phase not in phases:
        raise ValueError("invalid phase machine for operation")
    for phase in phases:
        if phase not in CANONICAL_PHASES:
            raise ValueError("phase %s not in the canonical phase set" % phase)
    now = _now_iso()
    return {
        "operation_version": OPERATION_VERSION,
        "operation_id": operation_id,
        "type": operation_type,
        "state": "queued",
        "phase": phases[0],
        "phases": list(phases),
        "irreversible_phase": irreversible_phase,
        "parameters": normalized_parameters,
        "parameters_fingerprint": parameters_fingerprint(
            normalized_parameters),
        "created_at": now,
        "updated_at": now,
        "cancel_requested": False,
        "cancel_requested_at": None,
        "progress": {"events": 0, "bytes": 0, "chunks": 0},
        "result": None,
        "error": None,
        "log": [],
    }


def validate_record(record):
    """Structural validation of a persisted record.

    Rejects unsupported versions, unknown states/phases, broken phase
    machines and non-monotonic log sequences so a corrupted or hostile
    record can never drive the state machine.
    """
    if not isinstance(record, dict):
        return False
    if record.get("operation_version") != OPERATION_VERSION:
        return False
    for field in REQUIRED_RECORD_FIELDS:
        if field not in record:
            return False
    if record["state"] not in STATES:
        return False
    phases = record["phases"]
    if not isinstance(phases, list) or not phases:
        return False
    if any(phase not in CANONICAL_PHASES for phase in phases):
        return False
    if record["irreversible_phase"] not in phases:
        return False
    if record["phase"] not in phases:
        return False
    if not isinstance(record["log"], list):
        return False
    last_seq = 0
    for entry in record["log"]:
        if not isinstance(entry, dict):
            return False
        if entry.get("event_version") != EVENT_VERSION:
            return False
        seq = entry.get("seq")
        if not isinstance(seq, int) or seq <= last_seq:
            return False
        last_seq = seq
    return True


def _append_event(record, kind, state=None, phase=None, progress=None,
                  error_code=None, outcome=None):
    """Append a log event. Events carry only IDs, hashes, phases, progress
    units, states and error codes — never parameters or input text."""
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
# Operation store (atomic, owner-only, symlink-rejecting)
# ---------------------------------------------------------------------------

def _exact_mode(path, mode):
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == mode
    except OSError:
        return False


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class OperationStore:
    """Directory-backed operation persistence.

    One JSON record per operation under `<root>/operations/`, written
    atomically (temp file in the same directory -> fsync -> rename ->
    directory fsync). Reads open with O_NOFOLLOW and verify owner and exact
    mode, so a symlink swap or a foreign-owner file is refused. The store
    holds no in-memory state: every call re-reads the record, which is what
    makes the runner crash-recoverable by construction.
    """

    def __init__(self, root_dir, euid=None):
        self.root_dir = root_dir
        self.euid = os.geteuid() if euid is None else euid
        self.operations_dir = os.path.join(root_dir, OPERATIONS_DIRNAME)
        self._opened = False

    def open(self):
        """Verify/create the root and operations directory with owner-only
        permissions. Raises StoreBlocked / UnsupportedPrivilege."""
        if self.euid == 0:
            raise UnsupportedPrivilege()
        root = self.root_dir
        if os.path.lexists(root):
            try:
                st = os.lstat(root)
            except OSError:
                raise StoreBlocked("root_unavailable")
            if stat.S_ISLNK(st.st_mode):
                raise StoreBlocked("root_symlink")
            if not stat.S_ISDIR(st.st_mode):
                raise StoreBlocked("root_not_directory")
            if st.st_uid != self.euid:
                raise StoreBlocked("root_owner")
            if not _exact_mode(root, 0o700):
                raise StoreBlocked("root_permission")
        else:
            os.makedirs(self.root_dir, mode=0o700)
        if os.path.lexists(self.operations_dir):
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
        else:
            os.makedirs(self.operations_dir, mode=0o700)
        self._opened = True
        return self

    def _record_path(self, operation_id):
        return os.path.join(self.operations_dir, "%s.json" % operation_id)

    def _read_record(self, operation_id):
        path = self._record_path(operation_id)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            if os.path.islink(path):
                raise StoreBlocked("operation_symlink")
            raise OperationNotFound(operation_id)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise StoreBlocked("operation_not_regular")
            if st.st_uid != self.euid:
                raise StoreBlocked("operation_owner")
            if not stat.S_IMODE(st.st_mode) == 0o600:
                raise StoreBlocked("operation_permission")
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                payload = f.read()
        except OSError:
            raise StoreBlocked("operation_unreadable")
        try:
            record = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            raise StoreBlocked("operation_unreadable")
        if not validate_record(record):
            raise StoreBlocked("operation_invalid")
        if record["operation_id"] != operation_id:
            raise StoreBlocked("operation_invalid")
        return record

    def _write_record(self, record, operation_id):
        """Atomic persist: temp file (0600, O_NOFOLLOW) -> fsync -> rename
        -> directory fsync. A crash at any point leaves the previous complete
        record (or no record for a fresh create) in place."""
        path = self._record_path(operation_id)
        tmp = "%s.tmp-%d-%s" % (path, os.getpid(), uuid.uuid4().hex[:8])
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            payload = json.dumps(record, ensure_ascii=False, indent=2)
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.rename(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        _fsync_dir(self.operations_dir)

    def exists(self, operation_id):
        return os.path.isfile(self._record_path(operation_id))

    def create(self, record):
        operation_id = record["operation_id"]
        if self.exists(operation_id):
            existing = self.load(operation_id)
            if existing["parameters_fingerprint"] == record[
                    "parameters_fingerprint"]:
                return existing
            raise OperationIdConflict(operation_id)
        self._write_record(record, operation_id)
        return self.load(operation_id)

    def load(self, operation_id):
        return self._read_record(operation_id)

    def list_ids(self):
        try:
            names = os.listdir(self.operations_dir)
        except OSError:
            return []
        result = []
        for name in names:
            if name.endswith(".json"):
                result.append(name[: -len(".json")])
        return sorted(result)

    def update(self, record):
        operation_id = record["operation_id"]
        record["updated_at"] = _now_iso()
        self._write_record(record, operation_id)
        return self.load(operation_id)


# ---------------------------------------------------------------------------
# Operation type registry and runner
# ---------------------------------------------------------------------------

class OperationTypeSpec:
    """One operation type's machine and step functions.

    Later tickets (#54/#55/#57/#68) register their types here; #52 ships no
    production type. `normalize` returns the canonical parameter dict that is
    persisted (and fingerprinted) for the idempotency comparison; a step
    returns a dict with any of:

      progress: delta of real units {events|bytes|chunks: int}
      advance:  True to move to the recorded successor phase
      result:   final result payload (only meaningful with advance on the
                last phase -> state becomes succeeded)

    A step may raise OperationBlocked (deterministic -> blocked), Operation
    Failed (transient -> failed) or SimulatedCrash (test seam: abort without
    persisting anything).
    """

    def __init__(self, operation_type, phases, irreversible_phase,
                 normalize, steps):
        self.operation_type = operation_type
        self.phases = tuple(phases)
        self.irreversible_phase = irreversible_phase
        self.normalize = normalize
        self.steps = dict(steps)

    def new_record(self, parameters, operation_id=None):
        return new_operation(self.operation_type,
                             self.normalize(parameters),
                             self.phases, self.irreversible_phase,
                             operation_id=operation_id)


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
    is generated before any work and returned immediately.
    """
    spec = registry.get(operation_type)
    if spec is None:
        raise UnsupportedOperationType(operation_type)
    store.open()
    record = spec.new_record(parameters, operation_id=operation_id)
    return store.create(record)


def cancel_operation(store, operation_id):
    """Request cancellation. Honored by the runner only in cancelable
    (pre-irreversible) phases; otherwise an explicit uncancellable result is
    returned and the operation continues to finish."""
    store.open()
    record = store.load(operation_id)
    if record["state"] == "cancelled":
        return record, "already_cancelled"
    if record["state"] in ("succeeded", "failed"):
        return record, "terminal"
    if not is_cancelable(record):
        return record, "uncancellable"
    if record["cancel_requested"]:
        return record, "requested"
    record["cancel_requested"] = True
    record["cancel_requested_at"] = _now_iso()
    _append_event(record, "cancel_requested", state=record["state"],
                  phase=record["phase"])
    return store.update(record), "requested"


def _step_index_in_phase(record, phase):
    return len([entry for entry in record["log"]
                if entry.get("kind") == "progress"
                and entry.get("phase") == phase])


def run_pending_steps(store, registry, operation_id, *, fault_hook=None,
                      max_steps=None, retry_blocked=False):
    """Execute pending work for one operation.

    Stateless loop: read record -> (queued -> running; blocked -> running
    only on an explicit retry) -> cancel checkpoint -> execute one step ->
    persist -> repeat. A crash anywhere only loses the step that had not
    finished persisting, so restarting the runner resumes from the persisted
    phase and progress. `fault_hook(phase, step_index, point)` is the
    crash/fault injection seam used by tests (point is "before_step" or
    "after_step"); raising SimulatedCrash aborts without persisting, raising
    OperationBlocked/Failed injects those outcomes. `max_steps` bounds the
    number of step executions (transitions are not counted) for
    deterministic test stepping. `retry_blocked` marks this invocation as
    the explicit operator retry that a `blocked` operation requires (spec:
    blocked is deterministic and never auto-retries; `wait` and any other
    observer never retry).

    Returns the final record when no more immediate work remains.
    """
    store.open()
    steps_executed = 0
    while True:
        record = store.load(operation_id)
        if record["state"] in TERMINAL_STATES:
            return record
        if record["state"] == "queued":
            validate_state_transition(record["state"], "running")
            _append_event(record, "transition", state="running",
                          phase=record["phase"])
            record["state"] = "running"
            record = store.update(record)
        elif record["state"] == "blocked":
            if not retry_blocked:
                return record
            validate_state_transition(record["state"], "running")
            _append_event(record, "transition", state="running",
                          phase=record["phase"])
            record["state"] = "running"
            record = store.update(record)
        if record["cancel_requested"] and is_cancelable(record):
            validate_state_transition(record["state"], "cancelled")
            _append_event(record, "terminal", state="cancelled",
                          phase=record["phase"], outcome="cancelled")
            record["state"] = "cancelled"
            return store.update(record)
        if max_steps is not None and steps_executed >= max_steps:
            return record
        spec = registry.get(record["type"])
        if spec is None:
            record["error"] = make_error("unsupported_operation_type",
                                         phase=record["phase"])
            _append_event(record, "terminal", state="failed",
                          phase=record["phase"], outcome="failed",
                          error_code="unsupported_operation_type")
            record["state"] = "failed"
            return store.update(record)
        phase = record["phase"]
        step_index = _step_index_in_phase(record, phase)
        try:
            if fault_hook is not None:
                fault_hook(phase, step_index, "before_step")
            result = spec.steps[phase](record, _StepContext(store))
            if fault_hook is not None:
                fault_hook(phase, step_index, "after_step")
        except SimulatedCrash:
            raise
        except OperationBlocked as error:
            record["error"] = error.to_error_object()
            _append_event(record, "terminal", state="blocked",
                          phase=phase, outcome="blocked",
                          error_code=error.code)
            record["state"] = "blocked"
            return store.update(record)
        except OperationFailed as error:
            record["error"] = error.to_error_object()
            _append_event(record, "terminal", state="failed",
                          phase=phase, outcome="failed",
                          error_code=error.code)
            record["state"] = "failed"
            return store.update(record)
        steps_executed += 1
        progress = result.get("progress")
        if progress:
            for unit in ("events", "bytes", "chunks"):
                if unit in progress:
                    record["progress"][unit] += int(progress[unit])
            _append_event(record, "progress", state=record["state"],
                          phase=phase, progress=dict(progress))
        if result.get("advance"):
            if phase == record["phases"][-1]:
                record["result"] = result.get("result") or {
                    "completed": True}
                _append_event(record, "terminal", state="succeeded",
                              phase=phase, outcome="succeeded")
                record["state"] = "succeeded"
                return store.update(record)
            new_phase = record["phases"][
                _phase_index(record, phase) + 1]
            validate_phase_transition(record, new_phase)
            _append_event(record, "transition", state="running",
                          phase=new_phase)
            record["phase"] = new_phase
            record = store.update(record)
            continue
        record = store.update(record)


class _StepContext:
    """Handed to step functions; carries the store for steps that need
    cross-operation state (future tickets: locks, quarantine, manifests)."""

    def __init__(self, store):
        self.store = store


def wait_for_terminal(store, operation_id, *, poll_interval=0.25,
                      timeout_s=None, emit=None):
    """Observe an operation until it reaches a terminal state.

    Only observes: interruption by the caller (KeyboardInterrupt) never
    cancels the operation. `emit(entry)` receives each unseen log event in
    seq order; returns (terminal_record, terminal_outcome).
    """
    store.open()
    last_seq = 0
    deadline = None
    if timeout_s is not None:
        import time
        deadline = time.monotonic() + timeout_s
    while True:
        record = store.load(operation_id)
        for entry in record["log"]:
            if entry["seq"] > last_seq:
                if emit is not None:
                    emit(entry)
                last_seq = entry["seq"]
        if record["state"] in TERMINAL_STATES:
            return record, record["state"]
        if deadline is not None:
            import time
            if time.monotonic() >= deadline:
                return record, None
        import time
        time.sleep(poll_interval)


def operation_outcome_exit_code(outcome):
    """Deterministic exit code for wait: 0 for succeeded and cancelled
    (intentional outcomes), 1 for failed/blocked, 2 for a timeout."""
    if outcome in ("succeeded", "cancelled"):
        return 0
    if outcome in ("failed", "blocked"):
        return 1
    return 2


if __name__ == "__main__":
    print("operations.py is a library module; use the "
          "squirrel-semantic-memory CLI.", file=sys.stderr)
    sys.exit(2)
