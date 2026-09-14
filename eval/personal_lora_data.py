#!/usr/bin/env python3
"""Personal LoRA completion-dataset freeze (Habit130/squirrel#175).

Turns one consistent, read-only SQLite Online Backup of the canonical fact
store into a private completion-training dataset:

- prompt = the stored raw causal 上文 (``preceding_text``, at most 64 Unicode
  characters as stored, empty is a valid stratum);
- completion = the finally committed ``final_selection_text``;
- loss boundary intent = completion-only, with no tokenizer-dependent mask
  claimed before a tokenizer is pinned.

The module never concatenates unrelated events, never uses a later choice as
preceding text and never prints raw text.  All private artifacts stay under
the ticket-owned artifact root with owner-only permissions:

    <root>/config.json                      (operator supplied)
    <root>/acquisition/state.json           attempt history + frozen identity
    <root>/snapshot/facts-snapshot.sqlite3  the one successful Online Backup
    <root>/dataset/train.jsonl
    <root>/dataset/validation.jsonl
    <root>/dataset/test.jsonl
    <root>/dataset/manifest.json            aggregate-only frozen manifest
    <root>/dataset/public-report.md         desensitized qualification report

CLI (the delivery interface):

    python3 eval/personal_lora_data.py --config <root>/config.json
    python3 eval/personal_lora_data.py --verify-only --manifest \
        <root>/dataset/manifest.json

Exit status:

- 0  dataset_frozen (run) or verification PASS (verify-only)
- 2  needs_owner_decision: an honest report over a legal but unusable dataset
- 1  error/blocker: source corruption or access failure, isolation violation,
     schema fault, tampered or unreproducible freeze

Config keys: ``source_db`` and ``artifact_root`` (required); ``status_cli``,
``status_timeout_seconds`` and ``expected_fact_schema_version`` (optional).
Relative paths resolve against the repository root.  The status CLI is
observational only: a timeout or missing binary is reported as health
``unknown``, never as snapshot corruption or success.
"""

import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_DAEMON_DIR = os.path.join(_REPO_ROOT, "daemon")
if _DAEMON_DIR not in sys.path:
    sys.path.insert(0, _DAEMON_DIR)

import oracle  # noqa: E402  (plugin oracle; stdlib-only simplified-NFC match)
from oracle import canonicalize_segment_input, match_text  # noqa: E402

TOOL_NAME = "personal_lora_data"
TOOL_VERSION = 1
DATASET_SCHEMA = "personal-lora-completion-v1"
MANIFEST_SCHEMA = "personal-lora-data-manifest-v1"

# Established conventions (AC-175-v1 Established / existing #76/#77 seams).
GROUP_COMPLETE_N = 32
PRECEDING_WINDOW = 64
EXPLICIT_CONFIRMATION_SOURCES = ("explicit_current", "explicit_indexed")
WORD_CATEGORIES = ("word",)
SUPPORTED_SCHEMAS = ("luna_pinyin",)
LOSS_BOUNDARY_INTENT = "completion_only"

# Deterministic temporal freeze constants, recorded in every manifest.
TRAIN_FRACTION = 0.8
VALIDATION_FRACTION = 0.1
SESSION_SNAP_TOLERANCE_FRACTION = 0.01
RATIO_DEVIATION_LIMIT = 0.05

DEFAULT_ALLOWED_ROOT = os.path.join(_REPO_ROOT, ".local-work",
                                    "personal-lora-data")
SNAPSHOT_REL = "snapshot/facts-snapshot.sqlite3"
MANIFEST_REL = "dataset/manifest.json"
PUBLIC_REPORT_REL = "dataset/public-report.md"
STATE_REL = "acquisition/state.json"
CONFIG_KEYS = frozenset((
    "source_db", "artifact_root", "status_cli", "status_timeout_seconds",
    "expected_fact_schema_version",
))

REQUIRED_TABLES = {
    "meta": ("key", "value"),
    "commits": ("commit_id", "utc_committed_at_ms"),
    "selection_events": (
        "event_id", "commit_id", "event_format_version", "schema_id",
        "canonical_segment_input", "span_start", "span_end", "category",
        "preceding_text", "competition_complete", "final_selection_text",
        "confirmation_source", "trigger_keycode", "display_rank",
        "display_page", "session_id", "session_seq", "hlc_physical_ms",
        "hlc_logical", "utc_confirmed_at_ms", "utc_committed_at_ms"),
    "selection_candidates": ("event_id", "merge_order", "text"),
    "retractions": ("retraction_id", "commit_id", "hlc_physical_ms",
                    "hlc_logical", "utc_retracted_at_ms"),
}
REQUIRED_META_KEYS = ("fact_schema_version", "history_id", "store_epoch",
                      "hlc_physical_ms", "hlc_logical")

REQUIRED_TEXT_FIELDS = ("event_id", "commit_id", "schema_id",
                        "canonical_segment_input", "category", "session_id",
                        "confirmation_source")
REQUIRED_INT_FIELDS = ("span_start", "span_end", "display_rank",
                       "display_page", "session_seq", "hlc_physical_ms",
                       "hlc_logical")
CONTENT_SIGNATURE_FIELDS = (
    "commit_id", "schema_id", "canonical_segment_input", "span_start",
    "span_end", "category", "preceding_text", "competition_complete",
    "final_selection_text", "confirmation_source", "trigger_keycode",
    "display_rank", "display_page", "session_id", "session_seq",
    "hlc_physical_ms", "hlc_logical")

FAULT_REASONS = frozenset((
    "missing_required_field", "conflicting_duplicate_event_id",
    "conflicting_duplicate_capture", "orphan_commit", "overlong_context",
    "invalid_span"))

RANKING_INELIGIBLE_REASONS = frozenset((
    "group_at_or_above_window", "target_not_in_competition",
    "invalid_candidate_data"))

PARTITIONS = ("train", "validation", "test")
PROMPT_LENGTH_KEYS = ("min", "max", "mean", "p50", "p90", "p99")


class PersonalLoraDataError(Exception):
    """A true fault in acquisition, qualification, export or verification."""


class IsolationError(PersonalLoraDataError):
    """A writable path resolves outside the ticket-owned artifact root."""


class AcquisitionError(PersonalLoraDataError):
    """The one consistent snapshot could not be acquired or validated."""


class SourceSchemaError(PersonalLoraDataError):
    """The source or snapshot schema does not match the bound fact schema."""


class DataFaultError(PersonalLoraDataError):
    """The eligible event stream cannot be frozen without violating a rule."""


# ---------------------------------------------------------------------------
# Deterministic JSON / hashing helpers
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _resolve(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


# ---------------------------------------------------------------------------
# Path sealing (DATA-4)
# ---------------------------------------------------------------------------

DEFAULT_PROTECTED_ROOTS = (
    os.path.join("~", "Library", "Application Support", "Squirrel"),
    os.path.join("~", "Library", "Rime"),
)


def default_protected_roots() -> Tuple[str, ...]:
    return tuple(os.path.expanduser(root) for root in DEFAULT_PROTECTED_ROOTS)


def _is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def assert_artifact_root(artifact_root: str,
                         allowed_root: Optional[str] = None,
                         protected_roots: Optional[Sequence[str]] = None
                         ) -> str:
    """Fail closed unless the artifact root is ticket-owned and safe.

    The resolved root must not be a live fact/Rime/app location (including
    via symlink aliases) and must stay inside the allowed ticket root.
    """
    resolved = _resolve(artifact_root)
    allowed = _resolve(allowed_root if allowed_root is not None
                       else DEFAULT_ALLOWED_ROOT)
    roots = (tuple(protected_roots) if protected_roots is not None
             else default_protected_roots())
    for root in roots:
        protected = _resolve(root)
        if _is_within(resolved, protected):
            raise IsolationError(
                "artifact root resolves into a protected live location")
    if not _is_within(resolved, allowed):
        raise IsolationError(
            "artifact root resolves outside the ticket-owned artifact root")
    return resolved


def safe_target(root: str, relative: str) -> str:
    """Resolve one artifact-relative output path, refusing escapes.

    Absolute paths, ``..`` components, symlinked targets and paths whose
    resolved parent escapes the artifact root (symlink aliases) are refused.
    """
    if not relative or os.path.isabs(relative):
        raise IsolationError("artifact path must be relative and non-empty")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise IsolationError("artifact path contains an unsafe component")
    base = _resolve(root)
    current = base
    for part in parts[:-1]:
        current = os.path.join(current, part)
        if os.path.exists(current) and not _is_within(_resolve(current), base):
            raise IsolationError("artifact path escapes the artifact root")
    target = os.path.join(base, *parts)
    if os.path.islink(target):
        raise IsolationError("artifact path is a symlink")
    parent = os.path.dirname(target)
    if os.path.exists(parent) and not _is_within(_resolve(parent), base):
        raise IsolationError("artifact parent escapes the artifact root")
    return target


def verify_owner_only(root: str) -> List[str]:
    """Return violations of the owner-only permission rule under ``root``."""
    violations = []
    base = _resolve(root)
    for directory, dirnames, filenames in os.walk(base):
        entries = [directory] + [os.path.join(directory, name)
                                 for name in dirnames + filenames]
        for entry in entries:
            stat = os.lstat(entry)
            if stat.st_mode & 0o077:
                violations.append(os.path.relpath(entry, base))
    return sorted(violations)


def prepare_artifact_root(root: str,
                          allowed_root: Optional[str] = None,
                          protected_roots: Optional[Sequence[str]] = None
                          ) -> str:
    resolved = assert_artifact_root(root, allowed_root, protected_roots)
    os.makedirs(resolved, mode=0o700, exist_ok=True)
    os.chmod(resolved, 0o700)
    return resolved


def ensure_private_dir(root: str, relative: str) -> str:
    target = safe_target(root, relative)
    base = _resolve(root)
    current = base
    for part in relative.split("/"):
        current = os.path.join(current, part)
        if os.path.exists(current):
            if not os.path.isdir(current) or os.path.islink(current):
                raise IsolationError("artifact directory component is unsafe")
        else:
            os.mkdir(current, 0o700)
        os.chmod(current, 0o700)
    return target


def private_write_bytes(root: str, relative: str, data: bytes) -> str:
    """Atomically write one owner-only file inside the artifact root."""
    target = safe_target(root, relative)
    parent = os.path.dirname(relative)
    if parent:
        ensure_private_dir(root, parent)
    temporary = "%s.tmp-%d" % (target, os.getpid())
    descriptor = os.open(temporary,
                         os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                         0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    os.chmod(target, 0o600)
    return target


def path_identity(path: str) -> Dict[str, str]:
    resolved = _resolve(path)
    return {
        "db_basename": os.path.basename(resolved),
        "path_sha256": sha256_text(resolved),
    }


# ---------------------------------------------------------------------------
# Read-only source access (DATA-1)
# ---------------------------------------------------------------------------

def _readonly_uri(path: str, immutable: bool) -> str:
    resolved = _resolve(path)
    quoted = resolved.replace("?", "%3f").replace("#", "%23")
    suffix = "&immutable=1" if immutable else ""
    return "file:%s?mode=ro%s" % (quoted, suffix)


def open_sqlite_readonly(path: str, immutable: bool = False
                         ) -> sqlite3.Connection:
    """Open one database read-only; frozen snapshots use ``immutable=1``.

    A WAL-mode copy has no ``-shm`` file, and a plain read-only connection
    cannot create one, so frozen-snapshot reads must declare the file
    immutable (true by construction: the artifact is never written again).
    """
    if not os.path.isfile(path):
        raise AcquisitionError("sqlite source not found")
    try:
        connection = sqlite3.connect(_readonly_uri(path, immutable), uri=True,
                                     timeout=5.0)
        connection.execute("PRAGMA query_only=ON;")
    except sqlite3.Error as error:
        raise AcquisitionError("cannot open sqlite source read-only: %s"
                               % error.__class__.__name__) from error
    return connection


def inspect_schema(connection: sqlite3.Connection) -> Dict:
    try:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master"
            " WHERE type IN ('table', 'view') ORDER BY type, name").fetchall()
    except sqlite3.Error as error:
        raise SourceSchemaError("cannot read sqlite schema") from error
    tables = {}
    for kind, name, _sql in rows:
        if kind == "table":
            quoted = '"%s"' % name.replace('"', '""')
            columns = [row[1] for row in connection.execute(
                "PRAGMA table_info(%s)" % quoted)]
            tables[name] = columns
    fingerprint = sha256_text(canonical_json([[k, n, s] for k, n, s in rows]))
    return {"fingerprint_sha256": fingerprint, "tables": tables}


def validate_required_schema(schema: Dict) -> None:
    tables = schema.get("tables") or {}
    for table, columns in REQUIRED_TABLES.items():
        present = tables.get(table)
        if present is None:
            raise SourceSchemaError("required fact table is missing")
        missing = [column for column in columns if column not in present]
        if missing:
            raise SourceSchemaError(
                "required fact column is missing in %s: %s"
                % (table, ",".join(missing)))


def read_meta(connection: sqlite3.Connection) -> Dict[str, str]:
    try:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error as error:
        raise SourceSchemaError("cannot read fact meta") from error
    meta = {row[0]: row[1] for row in rows}
    missing = [key for key in REQUIRED_META_KEYS if key not in meta]
    if missing:
        raise SourceSchemaError("required meta keys are missing")
    return meta


def read_source_observation(connection: sqlite3.Connection,
                            path: str) -> Dict:
    """Read-only pre/post metadata: identity, schema and high-water."""
    schema = inspect_schema(connection)
    validate_required_schema(schema)
    meta = read_meta(connection)
    try:
        physical = int(meta["hlc_physical_ms"])
        logical = int(meta["hlc_logical"])
    except (TypeError, ValueError) as error:
        raise SourceSchemaError("fact high-water is not an integer") from error
    observation = path_identity(path)
    observation.update({
        "schema_fingerprint_sha256": schema["fingerprint_sha256"],
        "store_epoch": meta["store_epoch"],
        "history_id": meta["history_id"],
        "fact_schema_version": meta.get("fact_schema_version"),
        "event_format_version": meta.get("event_format_version"),
        "high_water": [physical, logical],
    })
    return observation


def compare_observations(before: Dict, after: Dict) -> Dict:
    """Source continuity, distinct from daemon/service health."""
    continuity = {
        "store_epoch_stable": before.get("store_epoch") == after.get(
            "store_epoch"),
        "history_id_stable": before.get("history_id") == after.get(
            "history_id"),
        "schema_fingerprint_stable": before.get(
            "schema_fingerprint_sha256") == after.get(
            "schema_fingerprint_sha256"),
        "source_path_stable": before.get("path_sha256") == after.get(
            "path_sha256"),
    }
    before_hw = tuple(before.get("high_water") or ())
    after_hw = tuple(after.get("high_water") or ())
    continuity["high_water_monotonic"] = (
        len(before_hw) == 2 and len(after_hw) == 2 and after_hw >= before_hw)
    return continuity


def observe_health(config: Dict) -> Dict:
    """Observational daemon/service health; timeout is ``unknown``."""
    status_cli = config.get("status_cli")
    if not status_cli:
        return {"state": "unknown", "reason": "status_cli_not_configured"}
    if not os.path.isfile(status_cli):
        return {"state": "unknown", "reason": "status_cli_missing"}
    timeout = config.get("status_timeout_seconds", 10)
    try:
        completed = subprocess.run(
            [status_cli, "status", "--json"], capture_output=True, text=True,
            timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"state": "unknown", "reason": "status_cli_timeout"}
    except OSError:
        return {"state": "unknown", "reason": "status_cli_error"}
    if completed.returncode != 0:
        return {"state": "unknown", "reason": "status_cli_failed"}
    try:
        parsed = json.loads(completed.stdout)
    except ValueError:
        return {"state": "unknown", "reason": "status_cli_unparseable"}
    facts = parsed.get("facts") or {}
    high_water = facts.get("fact_high_water") or {}
    observation = {
        "state": "ok" if facts.get("snapshot_ok") else "unhealthy",
        "snapshot_ok": facts.get("snapshot_ok"),
        "gap_state": (facts.get("recording_gaps") or {}).get("state"),
        "store_epoch": facts.get("store_epoch"),
        "history_id": facts.get("history_id"),
        "total_events": facts.get("total_events"),
        "active_events": facts.get("active_events"),
        "fact_high_water": [high_water.get("hlc_physical_ms"),
                            high_water.get("hlc_logical")],
    }
    return observation


def perform_backup(source_path: str, target_path: str) -> None:
    """One SQLite Online Backup; the source stays read-only/query-only."""
    descriptor = os.open(target_path,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600)
    os.close(descriptor)
    source = open_sqlite_readonly(source_path)
    try:
        target = sqlite3.connect(target_path)
        try:
            source.backup(target)
        finally:
            target.close()
    except sqlite3.Error as error:
        raise AcquisitionError("online backup failed: %s"
                               % error.__class__.__name__) from error
    finally:
        source.close()
    os.chmod(target_path, 0o600)


def validate_snapshot(snapshot_path: str) -> Dict:
    """Integrity, identity and high-water binding for one frozen copy."""
    connection = open_sqlite_readonly(snapshot_path, immutable=True)
    try:
        try:
            integrity = connection.execute(
                "PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as error:
            raise AcquisitionError("snapshot integrity check failed") from error
        if integrity != "ok":
            raise AcquisitionError("snapshot integrity is not ok")
        try:
            foreign_keys = connection.execute(
                "PRAGMA foreign_key_check").fetchall()
        except sqlite3.Error as error:
            raise AcquisitionError("snapshot foreign key check failed") from error
        if foreign_keys:
            raise AcquisitionError("snapshot has foreign key violations")
        schema = inspect_schema(connection)
        validate_required_schema(schema)
        meta = read_meta(connection)
        try:
            high_water = [int(meta["hlc_physical_ms"]), int(meta["hlc_logical"])]
            max_row = connection.execute(
                "SELECT hlc_physical_ms, hlc_logical FROM selection_events"
                " ORDER BY hlc_physical_ms DESC, hlc_logical DESC LIMIT 1"
            ).fetchone()
        except (TypeError, ValueError, sqlite3.Error) as error:
            raise AcquisitionError("snapshot identity is malformed") from error
        identity = {
            "store_epoch": meta["store_epoch"],
            "history_id": meta["history_id"],
            "fact_schema_version": meta.get("fact_schema_version"),
            "event_format_version": meta.get("event_format_version"),
            "high_water": high_water,
            "max_event_hlc": list(max_row) if max_row else None,
        }
        counts = {}
        for table in ("selection_events", "selection_candidates",
                      "commits", "retractions"):
            counts[table] = connection.execute(
                "SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        return {
            "sha256": sha256_file(snapshot_path),
            "size_bytes": os.path.getsize(snapshot_path),
            "integrity": "ok",
            "schema_fingerprint_sha256": schema["fingerprint_sha256"],
            "identity": identity,
            "counts": counts,
        }
    finally:
        connection.close()


def load_state(root: str) -> Dict:
    state_path = safe_target(root, STATE_REL)
    if not os.path.exists(state_path):
        return {"attempts": [], "success": None}
    if os.path.islink(state_path) or not os.path.isfile(state_path):
        raise IsolationError("acquisition state path is unsafe")
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except ValueError as error:
        raise AcquisitionError("acquisition state is corrupt") from error
    if not isinstance(state.get("attempts"), list):
        raise AcquisitionError("acquisition state is malformed")
    return state


def save_state(root: str, state: Dict) -> str:
    return private_write_bytes(root, STATE_REL,
                               canonical_json(state).encode("utf-8"))


def verify_frozen_snapshot(root: str, record: Dict) -> Dict:
    snapshot_path = safe_target(root, record["path"])
    if os.path.islink(snapshot_path) or not os.path.isfile(snapshot_path):
        raise AcquisitionError(
            "frozen snapshot is missing or replaced; refusing a silent "
            "reacquisition")
    validated = validate_snapshot(snapshot_path)
    if validated["sha256"] != record["sha256"]:
        raise AcquisitionError(
            "frozen snapshot checksum mismatch; refusing a silent "
            "reacquisition")
    return validated


def acquire_snapshot(config: Dict) -> Dict:
    """Exactly one successful Online Backup, with explicit failed attempts.

    A recorded successful freeze is verified and reused, never replaced.  A
    failed attempt is recorded as failed and never becomes the frozen
    identity.
    """
    root = config["artifact_root"]
    source = config["source_db"]
    if not os.path.isfile(source):
        raise AcquisitionError("source fact store not found")
    state = load_state(root)
    if state.get("success"):
        record = dict(state["success"])
        validated = verify_frozen_snapshot(root, record)
        record.update({
            "integrity": validated["integrity"],
            "schema_fingerprint_sha256":
                validated["schema_fingerprint_sha256"],
            "identity": validated["identity"],
            "counts": validated["counts"],
        })
        return {
            "snapshot": record,
            "acquisition": {
                "attempts": state["attempts"],
                "successful_attempt": record["attempt"],
                "reused_frozen_snapshot": True,
            },
            "source_observations": record.get("source_observations"),
        }

    ensure_private_dir(root, "acquisition")
    ensure_private_dir(root, "snapshot")
    attempt_number = len(state["attempts"]) + 1
    entry = {"attempt": attempt_number, "started_at_utc": utc_now_iso(),
             "status": "in_progress"}
    temporary_path = safe_target(
        root, "acquisition/attempt-%d.sqlite3" % attempt_number)
    if os.path.exists(temporary_path):
        os.unlink(temporary_path)
    try:
        expected_version = config.get("expected_fact_schema_version")
        connection = open_sqlite_readonly(source)
        try:
            before = read_source_observation(connection, source)
            if expected_version is not None and \
                    str(before["fact_schema_version"]) != str(expected_version):
                raise SourceSchemaError(
                    "fact schema version does not match the configured "
                    "expectation")
            health_before = observe_health(config)
            perform_backup(source, temporary_path)
            snapshot = validate_snapshot(temporary_path)
            after = read_source_observation(connection, source)
            health_after = observe_health(config)
        finally:
            connection.close()
        continuity = compare_observations(before, after)
        failed = [name for name, ok in continuity.items() if not ok]
        if failed:
            raise AcquisitionError(
                "source continuity violated across acquisition: %s"
                % ",".join(sorted(failed)))
        if snapshot["identity"]["store_epoch"] != before["store_epoch"] or \
                snapshot["identity"]["history_id"] != before["history_id"] or \
                snapshot["schema_fingerprint_sha256"] != \
                before["schema_fingerprint_sha256"]:
            raise AcquisitionError(
                "snapshot identity does not bind the observed source "
                "identity")
        snapshot_low = tuple(snapshot["identity"]["high_water"])
        if not (tuple(before["high_water"]) <= snapshot_low
                <= tuple(after["high_water"])):
            raise AcquisitionError(
                "snapshot high-water is outside the observed source window")

        frozen_path = safe_target(root, SNAPSHOT_REL)
        if os.path.exists(frozen_path) or os.path.islink(frozen_path):
            raise IsolationError(
                "a frozen snapshot already exists; refusing to replace it")
        os.replace(temporary_path, frozen_path)
        os.chmod(frozen_path, 0o600)
        frozen = validate_snapshot(frozen_path)
        record = {
            "attempt": attempt_number,
            "path": SNAPSHOT_REL,
            "sha256": frozen["sha256"],
            "size_bytes": frozen["size_bytes"],
            "integrity": frozen["integrity"],
            "schema_fingerprint_sha256": frozen["schema_fingerprint_sha256"],
            "identity": frozen["identity"],
            "counts": frozen["counts"],
            "source_observations": {
                "before": before,
                "after": after,
                "continuity": continuity,
                "health": {"before": health_before, "after": health_after},
            },
        }
        entry.update({
            "status": "succeeded",
            "finished_at_utc": utc_now_iso(),
            "snapshot_sha256": frozen["sha256"],
            "snapshot_bytes": frozen["size_bytes"],
            "path": SNAPSHOT_REL,
        })
        state["attempts"].append(entry)
        state["success"] = record
        save_state(root, state)
        return {
            "snapshot": record,
            "acquisition": {
                "attempts": state["attempts"],
                "successful_attempt": attempt_number,
                "reused_frozen_snapshot": False,
            },
            "source_observations": record["source_observations"],
        }
    except PersonalLoraDataError as error:
        entry.update({"status": "failed", "finished_at_utc": utc_now_iso(),
                      "reason": error.__class__.__name__})
        state["attempts"].append(entry)
        save_state(root, state)
        if os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise
    except (OSError, sqlite3.Error) as error:
        entry.update({"status": "failed", "finished_at_utc": utc_now_iso(),
                      "reason": error.__class__.__name__})
        state["attempts"].append(entry)
        save_state(root, state)
        if os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise AcquisitionError("acquisition failed: %s"
                               % error.__class__.__name__) from error


# ---------------------------------------------------------------------------
# Faithful eligibility and labels (DATA-2)
# ---------------------------------------------------------------------------

class EventRecord:
    """One training-eligible stored selection event."""

    __slots__ = ("event_id", "commit_id", "session_id", "session_seq",
                 "schema_id", "category", "canonical_segment_input",
                 "preceding_text", "final_selection_text", "hlc",
                 "span_start", "span_end", "confirmation_source",
                 "competition_complete", "display_rank", "display_page",
                 "competition", "ranking_eligible")

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields[name])

    @property
    def empty_context(self) -> bool:
        return not self.preceding_text

    @property
    def choice_key(self) -> Tuple[str, str, str]:
        return (self.schema_id, self.category,
                canonicalize_segment_input(self.canonical_segment_input))

    @property
    def order_key(self) -> Tuple:
        return (self.hlc, self.event_id)


class AuditResult:
    """Aggregate eligibility audit over one frozen snapshot."""

    def __init__(self, events, rows_total, duplicates_collapsed,
                 excluded_by_reason, data_faults_by_reason,
                 missing_field_counts, ranking_ineligible_by_reason):
        self.events = events
        self.rows_total = rows_total
        self.duplicates_collapsed = duplicates_collapsed
        self.excluded_by_reason = excluded_by_reason
        self.data_faults_by_reason = data_faults_by_reason
        self.missing_field_counts = missing_field_counts
        self.ranking_ineligible_by_reason = ranking_ineligible_by_reason

    @property
    def samples(self) -> int:
        return len(self.events)

    @property
    def empty_context_samples(self) -> int:
        return sum(1 for event in self.events if event.empty_context)

    @property
    def ranking_eligible(self) -> int:
        return sum(1 for event in self.events if event.ranking_eligible)

    def to_json(self) -> Dict:
        return {
            "rows_total": self.rows_total,
            "samples": self.samples,
            "duplicates_collapsed": self.duplicates_collapsed,
            "excluded_by_reason": dict(sorted(
                self.excluded_by_reason.items())),
            "data_faults_by_reason": dict(sorted(
                self.data_faults_by_reason.items())),
            "missing_field_counts": dict(sorted(
                self.missing_field_counts.items())),
            "empty_context_samples": self.empty_context_samples,
            "ranking_eligible": self.ranking_eligible,
            "ranking_ineligible_by_reason": dict(sorted(
                self.ranking_ineligible_by_reason.items())),
            "rules": {
                "training_admission": (
                    "explicit_committed_unretracted_word_event_with_valid_"
                    "required_fields"),
                "ranking_eligibility": (
                    "group_size_lt_%d_and_target_membership_and_valid_"
                    "candidate_data" % GROUP_COMPLETE_N),
                "group_complete_convention": (
                    "saved_same_group_competition_size_lt_%d (persisted "
                    "competition_complete bit ignored)" % GROUP_COMPLETE_N),
                "preceding_window_characters": PRECEDING_WINDOW,
                "empty_context": "valid_and_counted",
                "loss_boundary_intent": LOSS_BOUNDARY_INTENT,
                "ordering": "(hlc_physical_ms, hlc_logical, event_id)",
                "explicit_confirmation_sources": list(
                    EXPLICIT_CONFIRMATION_SOURCES),
                "word_categories": list(WORD_CATEGORIES),
            },
        }


def _missing(value) -> bool:
    return value is None or value == ""


def _content_signature(row: Dict) -> str:
    return canonical_json([row.get(name) for name in CONTENT_SIGNATURE_FIELDS])


def _capture_signature(row: Dict, retracted_commits, candidates) -> str:
    return canonical_json([
        row.get("schema_id"), row.get("category"),
        row.get("canonical_segment_input"), row.get("preceding_text"),
        row.get("final_selection_text"), row.get("span_start"),
        row.get("span_end"), row.get("confirmation_source"),
        row.get("display_rank"), row.get("display_page"),
        row.get("competition_complete"),
        list(candidates.get(row.get("event_id"), [])),
        row.get("commit_id") in retracted_commits])


def _span_is_valid(row: Dict) -> bool:
    start = row.get("span_start")
    end = row.get("span_end")
    return (isinstance(start, int) and isinstance(end, int)
            and 0 <= start < end)


def _candidate_data_faults(competition: List[Tuple[int, str]]) -> bool:
    if not competition:
        return True
    orders = [order for order, _text in competition]
    if len(set(orders)) != len(orders) or orders != sorted(orders):
        return True
    return any(not isinstance(text, str) or text == ""
               for _order, text in competition)


def build_event(row: Dict, competition: List[Tuple[int, str]]) -> EventRecord:
    return EventRecord(
        event_id=row["event_id"], commit_id=row["commit_id"],
        session_id=row["session_id"], session_seq=row["session_seq"],
        schema_id=row["schema_id"], category=row["category"],
        canonical_segment_input=row["canonical_segment_input"],
        preceding_text=row["preceding_text"],
        final_selection_text=row["final_selection_text"],
        hlc=(int(row["hlc_physical_ms"]), int(row["hlc_logical"])),
        span_start=int(row["span_start"]), span_end=int(row["span_end"]),
        confirmation_source=row["confirmation_source"],
        competition_complete=bool(row["competition_complete"]),
        display_rank=int(row["display_rank"]),
        display_page=int(row["display_page"]),
        competition=tuple(text for _order, text in competition),
        ranking_eligible=False)


def audit_events(connection: sqlite3.Connection) -> AuditResult:
    """Apply the Established eligibility, retraction and duplicate rules."""
    connection.row_factory = sqlite3.Row
    schema = inspect_schema(connection)
    validate_required_schema(schema)
    retracted_commits = {row[0] for row in connection.execute(
        "SELECT commit_id FROM retractions")}
    commit_ids = {row[0] for row in connection.execute(
        "SELECT commit_id FROM commits")}
    candidates: Dict[str, List[Tuple[int, str]]] = {}
    for event_id, merge_order, text in connection.execute(
            "SELECT event_id, merge_order, text FROM selection_candidates"
            " ORDER BY event_id, merge_order"):
        candidates.setdefault(event_id, []).append((merge_order, text))
    rows = [dict(row) for row in connection.execute(
        "SELECT * FROM selection_events")]

    def sort_key(row):
        physical = row.get("hlc_physical_ms")
        logical = row.get("hlc_logical")
        return (-1 if physical is None else physical,
                -1 if logical is None else logical,
                str(row.get("event_id")))

    rows.sort(key=sort_key)
    excluded: Dict[str, int] = {}
    faults: Dict[str, int] = {}
    missing_fields: Dict[str, int] = {}
    ranking_ineligible: Dict[str, int] = {}

    def exclude(reason, count=1):
        excluded[reason] = excluded.get(reason, 0) + count
        if reason in FAULT_REASONS:
            faults[reason] = faults.get(reason, 0) + count

    valid_rows = []
    for row in rows:
        missing = [name for name in REQUIRED_TEXT_FIELDS if _missing(row.get(name))]
        missing.extend(name for name in REQUIRED_INT_FIELDS
                       if row.get(name) is None)
        if row.get("preceding_text") is None:
            missing.append("preceding_text")
        if missing:
            for name in missing:
                missing_fields[name] = missing_fields.get(name, 0) + 1
            exclude("missing_required_field")
            continue
        valid_rows.append(row)

    by_event_id: Dict[str, List[Dict]] = {}
    for row in valid_rows:
        by_event_id.setdefault(row["event_id"], []).append(row)
    deduplicated = []
    duplicates_collapsed = 0
    for event_id, group in by_event_id.items():
        if len(group) == 1:
            deduplicated.append(group[0])
            continue
        if len({_content_signature(row) for row in group}) == 1:
            duplicates_collapsed += len(group) - 1
            deduplicated.append(group[0])
        else:
            exclude("conflicting_duplicate_event_id", len(group))

    by_capture: Dict[Tuple[str, object], List[Dict]] = {}
    for row in deduplicated:
        by_capture.setdefault((row["session_id"], row["session_seq"]),
                              []).append(row)
    captured = []
    for group in by_capture.values():
        if len(group) == 1:
            captured.append(group[0])
            continue
        if len({_capture_signature(row, retracted_commits, candidates)
                for row in group}) == 1:
            duplicates_collapsed += len(group) - 1
            captured.append(group[0])
        else:
            exclude("conflicting_duplicate_capture", len(group))

    samples = []
    for row in captured:
        if row["commit_id"] not in commit_ids:
            exclude("orphan_commit")
            continue
        if row["commit_id"] in retracted_commits:
            exclude("retracted")
            continue
        if row["confirmation_source"] not in EXPLICIT_CONFIRMATION_SOURCES:
            exclude("not_explicit_confirmation")
            continue
        if row["schema_id"] not in SUPPORTED_SCHEMAS:
            exclude("not_supported_schema")
            continue
        if row["category"] not in WORD_CATEGORIES:
            exclude("not_word_category")
            continue
        if not str(row["final_selection_text"]):
            exclude("missing_target")
            continue
        if len(row["preceding_text"]) > PRECEDING_WINDOW:
            exclude("overlong_context")
            continue
        if not _span_is_valid(row):
            exclude("invalid_span")
            continue
        competition = candidates.get(row["event_id"], [])
        event = build_event(row, competition)
        if competition:
            target = match_text(event.final_selection_text)
            if target not in [match_text(text) for _order, text in competition]:
                ranking_ineligible["target_not_in_competition"] = \
                    ranking_ineligible.get("target_not_in_competition", 0) + 1
            else:
                event.ranking_eligible = True
        if _candidate_data_faults(competition):
            ranking_ineligible["invalid_candidate_data"] = \
                ranking_ineligible.get("invalid_candidate_data", 0) + 1
            event.ranking_eligible = False
        if len(competition) >= GROUP_COMPLETE_N:
            ranking_ineligible["group_at_or_above_window"] = \
                ranking_ineligible.get("group_at_or_above_window", 0) + 1
            event.ranking_eligible = False
        samples.append(event)

    samples.sort(key=lambda event: event.order_key)
    return AuditResult(
        events=samples, rows_total=len(rows),
        duplicates_collapsed=duplicates_collapsed,
        excluded_by_reason=excluded, data_faults_by_reason=faults,
        missing_field_counts=missing_fields,
        ranking_ineligible_by_reason=ranking_ineligible)


def load_event_audit(snapshot_path: str) -> AuditResult:
    connection = open_sqlite_readonly(snapshot_path, immutable=True)
    try:
        return audit_events(connection)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Deterministic temporal freeze (DATA-3)
# ---------------------------------------------------------------------------

class SplitPlan:
    """Ordered, whole-commit, session-preferred temporal boundaries."""

    def __init__(self, boundaries, boundary_kinds, chosen, targets,
                 tolerance_events, unit_count):
        self.boundaries = boundaries
        self.boundary_kinds = boundary_kinds
        self.chosen = chosen
        self.targets = targets
        self.tolerance_events = tolerance_events
        self.unit_count = unit_count

    def partitions(self, events) -> Dict[str, List[EventRecord]]:
        first, second = self.boundaries
        return {"train": list(events[:first]),
                "validation": list(events[first:second]),
                "test": list(events[second:])}

    def to_json(self) -> Dict:
        return {
            "kind": "deterministic_ordered_commit_unit_boundaries",
            "train_fraction": TRAIN_FRACTION,
            "validation_fraction": VALIDATION_FRACTION,
            "session_preference": (
                "cut_at_session_last_occurrence_within_tolerance"),
            "session_snap_tolerance_fraction":
                SESSION_SNAP_TOLERANCE_FRACTION,
            "session_snap_tolerance_events": self.tolerance_events,
            "tie_break": "smallest_absolute_deviation_then_earlier_position",
            "whole_commit_preserved": True,
            "fallback": "nearest_commit_unit_boundary",
            "targets": list(self.targets),
            "chosen": list(self.chosen),
            "chosen_kinds": list(self.boundary_kinds),
            "commit_units": self.unit_count,
        }


def commit_units(events: Sequence[EventRecord]) -> List[Tuple[int, int]]:
    """Half-open event-index units, one per contiguous commit run."""
    units = []
    start = 0
    for index in range(1, len(events) + 1):
        if index == len(events) or \
                events[index].commit_id != events[start].commit_id:
            units.append((start, index))
            start = index
    seen = set()
    for start, end in units:
        commit_id = events[start].commit_id
        if commit_id in seen:
            raise DataFaultError(
                "a commit identity is not contiguous in HLC order; a "
                "whole-commit partition is impossible")
        seen.add(commit_id)
    return units


def plan_splits(events: Sequence[EventRecord]) -> SplitPlan:
    total = len(events)
    units = commit_units(events)
    unit_ends = [end for _start, end in units]
    valid_bounds = [end for end in unit_ends if 0 < end < total]
    last_position: Dict[str, int] = {}
    for index, event in enumerate(events):
        last_position[event.session_id] = index
    session_boundaries = sorted({
        unit_ends[index] for index in range(len(units) - 1)
        if last_position[events[unit_ends[index] - 1].session_id]
        == unit_ends[index] - 1})
    tolerance = max(1, int(total * SESSION_SNAP_TOLERANCE_FRACTION))

    def choose(target_index, lower):
        within = [position for position in session_boundaries
                  if lower < position < total
                  and abs(position - target_index) <= tolerance]
        if within:
            position = min(within,
                           key=lambda item: (abs(item - target_index), item))
            return position, "session_end"
        candidates = [position for position in valid_bounds
                      if position > lower]
        if not candidates:
            return None, "none"
        position = min(candidates,
                       key=lambda item: (abs(item - target_index), item))
        return position, "commit_unit_end"

    if total == 0:
        return SplitPlan((0, 0), ("none", "none"), (0, 0), (0, 0), tolerance,
                         len(units))
    target_train = min(total - 1, max(1, int(round(total * TRAIN_FRACTION))))
    target_validation = min(total - 1, max(1, int(round(
        total * (TRAIN_FRACTION + VALIDATION_FRACTION)))))
    first, first_kind = choose(target_train, 0)
    if first is None:
        first, first_kind = total, "none"
    second, second_kind = choose(target_validation, first)
    if second is None or second <= first:
        second, second_kind = total, "none"
    return SplitPlan((first, second), (first_kind, second_kind),
                     (first, second), (target_train, target_validation),
                     tolerance, len(units))


def _percentile(ordered: List[int], fraction: float) -> Optional[int]:
    if not ordered:
        return None
    index = int(round((len(ordered) - 1) * fraction))
    return ordered[max(0, min(len(ordered) - 1, index))]


def length_summary(values: Sequence[int]) -> Dict:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None,
                "p50": None, "p90": None, "p99": None, "histogram": {}}
    ordered = sorted(values)
    histogram: Dict[str, int] = {}
    for value in ordered:
        histogram[str(value)] = histogram.get(str(value), 0) + 1
    ordered_histogram = {key: histogram[key] for key in
                         sorted(histogram, key=int)}
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "p99": _percentile(ordered, 0.99),
        "histogram": ordered_histogram,
    }


def _seen_in_train(part: Sequence[EventRecord],
                   train_pairs, train_keys) -> Dict[str, int]:
    return {
        "exact_context_target": sum(
            1 for event in part if (event.preceding_text,
                                    event.final_selection_text)
            in train_pairs),
        "exact_context_target_total": len(part),
        "choice_key": sum(1 for event in part
                          if event.choice_key in train_keys),
        "choice_key_total": len(part),
    }


def _part_stats(part: Sequence[EventRecord], total: int,
                target_fraction: float) -> Dict:
    return {
        "events": len(part),
        "commits": len({event.commit_id for event in part}),
        "sessions": len({event.session_id for event in part}),
        "keys": len({event.choice_key for event in part}),
        "empty_context": sum(1 for event in part if event.empty_context),
        "ranking_eligible": sum(1 for event in part
                                if event.ranking_eligible),
        "proportion": (round(len(part) / total, 6) if total else None),
        "target_proportion": target_fraction,
        "first_hlc": list(part[0].hlc) if part else None,
        "last_hlc": list(part[-1].hlc) if part else None,
        "prompt_lengths": length_summary(
            [len(event.preceding_text) for event in part]),
        "completion_lengths": length_summary(
            [len(event.final_selection_text) for event in part]),
    }


def decide_terminal(audit: AuditResult,
                    parts: Dict[str, List[EventRecord]]) -> Tuple[str, List[str]]:
    reasons = []
    total = len(audit.events)
    if audit.data_faults_by_reason:
        reasons.append("data_faults_present")
    if total == 0:
        reasons.append("no_eligible_samples")
    for name in PARTITIONS:
        if not parts[name]:
            reasons.append("empty_%s_partition" % name)
            continue
        if name in ("validation", "test") and not any(
                event.ranking_eligible for event in parts[name]):
            reasons.append("no_ranking_eligible_%s" % name)
    for name, target in (("train", TRAIN_FRACTION),
                         ("validation", VALIDATION_FRACTION),
                         ("test", 1.0 - TRAIN_FRACTION
                          - VALIDATION_FRACTION)):
        if total and abs(len(parts[name]) / total - target) > \
                RATIO_DEVIATION_LIMIT:
            reasons.append("proportion_deviation_%s" % name)
    if reasons:
        return "needs_owner_decision", reasons
    return "dataset_frozen", []


# ---------------------------------------------------------------------------
# Sealed export, manifest and verification (DATA-4, DATA-5)
# ---------------------------------------------------------------------------

def _example_record(event: EventRecord, partition: str) -> Dict:
    return {
        "schema": DATASET_SCHEMA,
        "prompt": event.preceding_text,
        "completion": event.final_selection_text,
        "loss": LOSS_BOUNDARY_INTENT,
        "provenance": {
            "event_id": event.event_id,
            "commit_id": event.commit_id,
            "session_id": event.session_id,
            "session_seq": event.session_seq,
            "schema_id": event.schema_id,
            "category": event.category,
            "canonical_segment_input": event.canonical_segment_input,
            "choice_key_sha256": sha256_text(
                canonical_json(list(event.choice_key))),
            "hlc": list(event.hlc),
            "span": [event.span_start, event.span_end],
            "competition_size": len(event.competition),
            "competition_complete_bit": event.competition_complete,
            "ranking_eligible": event.ranking_eligible,
            "empty_context": event.empty_context,
            "context_characters": len(event.preceding_text),
            "completion_characters": len(event.final_selection_text),
            "partition": partition,
        },
    }


def encode_partition(part: Sequence[EventRecord], partition: str) -> bytes:
    lines = []
    for event in part:
        lines.append(canonical_json(_example_record(event, partition)))
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _boundary_binding(part: Sequence[EventRecord]) -> Optional[Dict]:
    if not part:
        return None
    return {"first_hlc": list(part[0].hlc), "last_hlc": list(part[-1].hlc)}


def _sessions_spanning(parts: Dict[str, List[EventRecord]]) -> int:
    session_parts: Dict[str, set] = {}
    for name in PARTITIONS:
        for event in parts[name]:
            session_parts.setdefault(event.session_id, set()).add(name)
    return sum(1 for names in session_parts.values() if len(names) > 1)


def build_splits_section(audit: AuditResult, plan: SplitPlan,
                         parts: Dict[str, List[EventRecord]]) -> Dict:
    """Deterministic split evidence shared by export and verification."""
    train_pairs = {(event.preceding_text, event.final_selection_text)
                   for event in parts["train"]}
    train_keys = {event.choice_key for event in parts["train"]}
    target_fractions = {"train": TRAIN_FRACTION,
                        "validation": VALIDATION_FRACTION,
                        "test": 1.0 - TRAIN_FRACTION - VALIDATION_FRACTION}
    split_manifest = {}
    for name in PARTITIONS:
        data = encode_partition(parts[name], name)
        stats = _part_stats(parts[name], len(audit.events),
                            target_fractions[name])
        stats.update({
            "file": "dataset/%s.jsonl" % name,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "lines": len(parts[name]),
        })
        stats["seen_in_train"] = (
            None if name == "train"
            else _seen_in_train(parts[name], train_pairs, train_keys))
        split_manifest[name] = stats
    return {
        "rule": plan.to_json(),
        "parts": split_manifest,
        "sessions_spanning_partitions": _sessions_spanning(parts),
        "boundaries": {name: _boundary_binding(parts[name])
                       for name in PARTITIONS},
        "total": {
            "events": len(audit.events),
            "commits": len({event.commit_id for event in audit.events}),
            "sessions": len({event.session_id for event in audit.events}),
            "keys": len({event.choice_key for event in audit.events}),
        },
    }


def export_dataset(root: str, audit: AuditResult, plan: SplitPlan,
                   snapshot: Dict, acquisition: Dict,
                   source_observations: Dict) -> Dict:
    manifest_path = safe_target(root, MANIFEST_REL)
    if os.path.exists(manifest_path) or os.path.islink(manifest_path):
        raise IsolationError(
            "a successful dataset freeze already exists at %s; refusing to "
            "replace or rebind it" % MANIFEST_REL)
    parts = plan.partitions(audit.events)
    terminal, terminal_reasons = decide_terminal(audit, parts)

    ensure_private_dir(root, "dataset")
    splits = build_splits_section(audit, plan, parts)
    for name in PARTITIONS:
        data = encode_partition(parts[name], name)
        private_write_bytes(root, "dataset/%s.jsonl" % name, data)

    trial = {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION,
                 "script_sha256": sha256_file(os.path.abspath(__file__)),
                 "oracle_sha256": sha256_file(oracle.__file__)},
        "created_at_utc": utc_now_iso(),
        "terminal": terminal,
        "terminal_reasons": terminal_reasons,
        "source": source_observations,
        "snapshot": {
            "path": snapshot["path"],
            "sha256": snapshot["sha256"],
            "size_bytes": snapshot["size_bytes"],
            "integrity": snapshot["integrity"],
            "schema_fingerprint_sha256":
                snapshot["schema_fingerprint_sha256"],
            "identity": snapshot["identity"],
            "counts": snapshot["counts"],
        },
        "acquisition": acquisition,
        "audit": audit.to_json(),
        "splits": splits,
    }
    manifest = {"schema": MANIFEST_SCHEMA}
    manifest.update(trial)
    private_write_bytes(root, MANIFEST_REL,
                        (canonical_json(manifest) + "\n").encode("utf-8"))
    report = render_public_report(manifest)
    private_write_bytes(root, PUBLIC_REPORT_REL, report.encode("utf-8"))
    manifest["_artifacts"] = {
        "manifest": MANIFEST_REL,
        "public_report": PUBLIC_REPORT_REL,
    }
    return manifest


def _split_proportion(part_stats: Dict) -> str:
    proportion = part_stats.get("proportion")
    return "n/a" if proportion is None else "%.2f%%" % (proportion * 100.0)


def _length_cell(stats: Dict) -> str:
    if not stats.get("count"):
        return "n/a/n/a/n/a/n/a/n/a"
    return "%s/%s/%s/%s/%s" % (stats["min"], stats["p50"], stats["p90"],
                               stats["p99"], stats["max"])


def render_public_report(manifest: Dict) -> str:
    """Desensitized Markdown report: aggregates and identities only."""
    audit = manifest["audit"]
    splits = manifest["splits"]
    parts = splits["parts"]
    snapshot = manifest["snapshot"]
    lines = [
        "# Personal LoRA dataset freeze — public report",
        "",
        "Aggregate-only qualification report for the private completion "
        "dataset freeze (Habit130/squirrel#175, AC-175-v1). No raw strings, "
        "token sequences, per-example fingerprints or absolute private paths.",
        "",
        "## Terminal",
        "",
        "- terminal: `%s`" % manifest["terminal"],
        "- terminal reasons: %s" % (", ".join(manifest["terminal_reasons"])
                                    or "none"),
        "- created: %s" % manifest["created_at_utc"],
        "",
        "## Snapshot identity",
        "",
        "- snapshot artifact: `%s`" % snapshot["path"],
        "- snapshot sha256: `%s`" % snapshot["sha256"],
        "- snapshot bytes: %d" % snapshot["size_bytes"],
        "- integrity: `%s`" % snapshot["integrity"],
        "- schema fingerprint sha256: `%s`"
        % snapshot["schema_fingerprint_sha256"],
        "- store_epoch: `%s`" % snapshot["identity"]["store_epoch"],
        "- history_id: `%s`" % snapshot["identity"]["history_id"],
        "- fact_schema_version: `%s`"
        % snapshot["identity"]["fact_schema_version"],
        "- high_water: %s" % snapshot["identity"]["high_water"],
        "- max_event_hlc: %s" % snapshot["identity"]["max_event_hlc"],
        "- acquisition attempts: %d (successful attempt %s, reused=%s)"
        % (len(manifest["acquisition"]["attempts"]),
           manifest["acquisition"]["successful_attempt"],
           manifest["acquisition"]["reused_frozen_snapshot"]),
        "",
        "## Event audit",
        "",
        "| metric | count |",
        "| --- | --- |",
        "| stored rows | %d |" % audit["rows_total"],
        "| training samples | %d |" % audit["samples"],
        "| duplicate rows collapsed | %d |" % audit["duplicates_collapsed"],
        "| empty-context samples | %d |" % audit["empty_context_samples"],
        "| ranking-eligible samples | %d |" % audit["ranking_eligible"],
        "",
        "Exclusions by reason:",
        "",
    ]
    for reason, count in sorted(audit["excluded_by_reason"].items()):
        lines.append("- `%s`: %d" % (reason, count))
    lines.extend(["", "Data faults by reason:", ""])
    if audit["data_faults_by_reason"]:
        for reason, count in sorted(audit["data_faults_by_reason"].items()):
            lines.append("- `%s`: %d" % (reason, count))
    else:
        lines.append("- none")
    lines.extend(["", "Ranking ineligibility by reason:", ""])
    if audit["ranking_ineligible_by_reason"]:
        for reason, count in sorted(
                audit["ranking_ineligible_by_reason"].items()):
            lines.append("- `%s`: %d" % (reason, count))
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Temporal splits",
        "",
        "| split | events | proportion | commits | sessions | keys | "
        "empty context | ranking eligible | sha256 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for name in PARTITIONS:
        stats = parts[name]
        lines.append(
            "| %s | %d | %s | %d | %d | %d | %d | %d | `%s` |"
            % (name, stats["events"], _split_proportion(stats),
               stats["commits"], stats["sessions"], stats["keys"],
               stats["empty_context"], stats["ranking_eligible"],
               stats["sha256"]))
    lines.extend([
        "",
        "- sessions spanning partitions: %d"
        % splits["sessions_spanning_partitions"],
        "- boundary rule: `%s`" % splits["rule"]["kind"],
        "- chosen boundaries (event positions): %s"
        % splits["rule"]["chosen"],
        "- chosen boundary kinds: %s" % splits["rule"]["chosen_kinds"],
        "- targets (event positions): %s" % splits["rule"]["targets"],
        "- session tolerance (events): %d"
        % splits["rule"]["session_snap_tolerance_events"],
        "",
        "## Overlap with training",
        "",
        "| split | exact context+target | choice key | denominator |",
        "| --- | --- | --- | --- |",
    ])
    for name in ("validation", "test"):
        seen = parts[name]["seen_in_train"]
        lines.append("| %s | %d | %d | %d |"
                     % (name, seen["exact_context_target"],
                        seen["choice_key"], seen["exact_context_target_total"]))
    lines.extend([
        "",
        "## Length distributions (Unicode characters, tokenizer deferred)",
        "",
        "| split | prompt min/p50/p90/p99/max | completion "
        "min/p50/p90/p99/max |",
        "| --- | --- | --- |",
    ])
    for name in PARTITIONS:
        prompt = parts[name]["prompt_lengths"]
        completion = parts[name]["completion_lengths"]
        lines.append("| %s | %s | %s |"
                     % (name, _length_cell(prompt), _length_cell(completion)))
    lines.extend([
        "",
        "## Limitations",
        "",
        "- Static historical split: retractions are resolved as of this "
        "snapshot; later retractions require a new dataset/adapter version.",
        "- Earlier project experiments may have seen this historical period; "
        "this is not claimed as an untouched project-wide prospective test.",
        "- New post-freeze events belong to later prospective confirmation, "
        "not to this snapshot.",
        "- Token lengths and any tokenizer-dependent loss mask are deferred "
        "until a tokenizer is pinned in the pilot.",
        "- The 4907 historical retrieval-actionable count is not a training "
        "admission threshold for this dataset.",
        "",
    ])
    return "\n".join(lines)


def _hash_lines(path: str) -> Tuple[int, str]:
    digest = hashlib.sha256()
    lines = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            lines += chunk.count(b"\n")
    return lines, digest.hexdigest()


def verify_freeze(manifest_path: str,
                  protected_roots: Optional[Sequence[str]] = None) -> Dict:
    """Read-only checksum, provenance and reproducibility verification."""
    failures: List[str] = []
    manifest_path = _resolve(manifest_path)
    root = os.path.dirname(os.path.dirname(manifest_path))
    if not os.path.isfile(manifest_path):
        return {"failures": ["manifest not found"], "summary": {}}
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except ValueError:
        return {"failures": ["manifest is not valid JSON"], "summary": {}}
    if manifest.get("schema") != MANIFEST_SCHEMA:
        failures.append("manifest schema mismatch")
    tool = manifest.get("tool") or {}
    if tool.get("version") != TOOL_VERSION:
        failures.append("manifest was produced by a different tool version")

    snapshot_record = manifest.get("snapshot") or {}
    snapshot_path = os.path.join(root, snapshot_record.get("path", ""))
    if not os.path.isfile(snapshot_path) or os.path.islink(snapshot_path):
        failures.append("snapshot artifact missing or unsafe")
    else:
        if sha256_file(snapshot_path) != snapshot_record.get("sha256"):
            failures.append("snapshot sha256 mismatch")
        try:
            validated = validate_snapshot(snapshot_path)
        except PersonalLoraDataError as error:
            failures.append("snapshot validation failed: %s"
                            % error.__class__.__name__)
        else:
            if validated["identity"] != snapshot_record.get("identity"):
                failures.append("snapshot identity mismatch")

    parts = (manifest.get("splits") or {}).get("parts") or {}
    for name in PARTITIONS:
        stats = parts.get(name) or {}
        relative = stats.get("file")
        if not relative:
            failures.append("missing part %s" % name)
            continue
        path = os.path.join(root, relative)
        if not os.path.isfile(path) or os.path.islink(path):
            failures.append("part file missing or unsafe: %s" % name)
            continue
        lines, digest = _hash_lines(path)
        if digest != stats.get("sha256"):
            failures.append("part sha256 mismatch: %s" % name)
        if lines != stats.get("lines"):
            failures.append("part line count mismatch: %s" % name)

    if failures:
        return {"failures": failures, "summary": {}}

    try:
        audit = load_event_audit(snapshot_path)
        plan = plan_splits(audit.events)
        rederived = plan.partitions(audit.events)
    except PersonalLoraDataError as error:
        failures.append("snapshot reprocessing failed: %s"
                        % error.__class__.__name__)
        rederived = None
    if rederived is not None:
        if audit.to_json() != manifest.get("audit"):
            failures.append("audit aggregates do not reproduce")
        for name in PARTITIONS:
            expected = encode_partition(rederived[name], name)
            stats = parts.get(name) or {}
            if sha256_bytes(expected) != stats.get("sha256"):
                failures.append("part is not reproducible from the "
                                "snapshot: %s" % name)
        rule = (manifest.get("splits") or {}).get("rule") or {}
        if plan.to_json() != rule:
            failures.append("split rule does not reproduce")
        if build_splits_section(audit, plan, rederived) != \
                manifest.get("splits"):
            failures.append("split metadata does not reproduce")
        rederived_terminal, rederived_reasons = decide_terminal(audit,
                                                                rederived)
        if rederived_terminal != manifest.get("terminal"):
            failures.append("terminal does not reproduce from the frozen "
                            "snapshot")
        if list(rederived_reasons) != list(manifest.get("terminal_reasons")
                                           or []):
            failures.append("terminal reasons do not reproduce")

    permission_violations = verify_owner_only(root)
    if permission_violations:
        failures.append("owner-only permissions violated: %d path(s)"
                        % len(permission_violations))

    summary = {
        "terminal": manifest.get("terminal"),
        "snapshot_sha256": snapshot_record.get("sha256"),
        "events": (manifest.get("audit") or {}).get("samples"),
        "parts": {name: (parts.get(name) or {}).get("events")
                  for name in PARTITIONS},
        "ranking_eligible": (manifest.get("audit") or {}).get(
            "ranking_eligible"),
        "manifest_sha256": sha256_file(manifest_path),
    }
    return {"failures": failures, "summary": summary}


# ---------------------------------------------------------------------------
# Config and CLI
# ---------------------------------------------------------------------------

def _resolve_config_path(value: str) -> str:
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(_REPO_ROOT, expanded)


def load_config(path: str) -> Dict:
    resolved = _resolve(_resolve_config_path(path))
    if not os.path.isfile(resolved):
        raise PersonalLoraDataError("config file not found")
    try:
        with open(resolved, encoding="utf-8") as handle:
            raw = json.load(handle)
    except ValueError as error:
        raise PersonalLoraDataError("config is not valid JSON") from error
    if not isinstance(raw, dict):
        raise PersonalLoraDataError("config must be a JSON object")
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise PersonalLoraDataError("config has unknown keys: %s"
                                    % ",".join(unknown))
    for key in ("source_db", "artifact_root"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise PersonalLoraDataError("config key %s is required" % key)
    config = {
        "source_db": _resolve(_resolve_config_path(raw["source_db"])),
        "artifact_root": _resolve(_resolve_config_path(
            raw["artifact_root"])),
        "status_timeout_seconds": raw.get("status_timeout_seconds", 10),
    }
    timeout = config["status_timeout_seconds"]
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise PersonalLoraDataError(
            "status_timeout_seconds must be a positive number")
    if raw.get("status_cli") is not None and \
            not isinstance(raw.get("status_cli"), str):
        raise PersonalLoraDataError("status_cli must be a string path")
    if raw.get("status_cli"):
        config["status_cli"] = _resolve(_resolve_config_path(
            raw["status_cli"]))
    if raw.get("expected_fact_schema_version") is not None:
        config["expected_fact_schema_version"] = \
            raw["expected_fact_schema_version"]
    return config


def run_freeze(config_path: str,
               allowed_root: Optional[str] = None,
               protected_roots: Optional[Sequence[str]] = None) -> Dict:
    config = load_config(config_path)
    root = prepare_artifact_root(config["artifact_root"], allowed_root,
                                 protected_roots)
    if os.path.exists(os.path.join(root, MANIFEST_REL)):
        raise IsolationError(
            "a successful dataset freeze already exists; refusing to "
            "replace or rebind it; use --verify-only")
    acquisition = acquire_snapshot(config)
    snapshot = acquisition["snapshot"]
    audit = load_event_audit(os.path.join(root, snapshot["path"]))
    plan = plan_splits(audit.events)
    manifest = export_dataset(root, audit, plan, snapshot,
                              acquisition["acquisition"],
                              acquisition["source_observations"])
    manifest["_root"] = root
    return manifest


def _print_run_summary(manifest: Dict) -> None:
    parts = manifest["splits"]["parts"]
    print("terminal: %s" % manifest["terminal"])
    if manifest["terminal_reasons"]:
        print("terminal reasons: %s" % ",".join(manifest["terminal_reasons"]))
    print("snapshot sha256: %s" % manifest["snapshot"]["sha256"])
    print("samples: %d (train=%d validation=%d test=%d)"
          % (manifest["audit"]["samples"], parts["train"]["events"],
             parts["validation"]["events"], parts["test"]["events"]))
    print("ranking eligible: total=%d train=%d validation=%d test=%d"
          % (manifest["audit"]["ranking_eligible"],
             parts["train"]["ranking_eligible"],
             parts["validation"]["ranking_eligible"],
             parts["test"]["ranking_eligible"]))
    for name in PARTITIONS:
        print("%s: %s sha256=%s" % (name, parts[name]["file"],
                                    parts[name]["sha256"]))
    print("manifest: %s" % MANIFEST_REL)
    print("public report: %s" % PUBLIC_REPORT_REL)


def main(argv: Optional[Sequence[str]] = None,
         allowed_root: Optional[str] = None,
         protected_roots: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the personal LoRA completion dataset "
                    "(AC-175-v1).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", help="private freeze config JSON")
    group.add_argument("--verify-only", action="store_true",
                       help="verify the sealed freeze without changing it")
    parser.add_argument("--manifest",
                        help="frozen manifest path for --verify-only")
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            if not args.manifest:
                parser.error("--verify-only requires --manifest")
            result = verify_freeze(args.manifest,
                                   protected_roots=protected_roots)
            if result["failures"]:
                print("FAIL: dataset freeze verification failed")
                for failure in result["failures"]:
                    print("  - %s" % failure)
                return 1
            summary = result["summary"]
            print("PASS: dataset freeze verified")
            print("  terminal: %s" % summary["terminal"])
            print("  snapshot sha256: %s" % summary["snapshot_sha256"])
            print("  events: %s (train=%s validation=%s test=%s)"
                  % (summary["events"], summary["parts"]["train"],
                     summary["parts"]["validation"],
                     summary["parts"]["test"]))
            print("  ranking eligible: %s" % summary["ranking_eligible"])
            print("  manifest sha256: %s" % summary["manifest_sha256"])
            return 0
        if args.manifest:
            parser.error("--manifest requires --verify-only")
        manifest = run_freeze(args.config, allowed_root=allowed_root,
                              protected_roots=protected_roots)
        _print_run_summary(manifest)
        return 0 if manifest["terminal"] == "dataset_frozen" else 2
    except PersonalLoraDataError as error:
        print("ERROR: %s" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
