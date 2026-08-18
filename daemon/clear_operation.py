#!/usr/bin/env python3
"""The `clear` production operation type (Habit130/squirrel#54).

`clear` physically resets the semantic memory: it publishes a brand-new
empty fact store (fresh history_id, fresh store_epoch, reset HLC) through
the #53 maintenance seam, then deletes every application-controlled copy of
the old facts and derived state.

Phase machine (canonical order, spec #43):

    preflight -> waiting-for-quiesce -> staging -> publishing ->
    reopening -> cleanup

- `publishing` is the irreversible phase. The atomic fact replacement, the
  durable `published.marker` and the bounded exclusive quiesce all happen
  inside one publishing step, so the persisted phase is an honest boundary:
  a cancel requested while the persisted phase is `publishing` is refused as
  uncancellable, and a cancel honored before it can never race a
  replacement in flight (the compensation step only ever observes the
  complete old store).
- Staging (the only expensive fact work) completes before any daemon
  prepare. The staged identity is durable (`identity.json`) and is reused
  verbatim across retries, so no crash window can regenerate history or
  epoch identities.
- `already_clear` (pristine or an empty store with nothing pending cleanup)
  skips the replacement entirely: repeated clears of an empty system never
  churn identities. Old operation details are still removed idempotently in
  cleanup.

Fact semantics live in C++ (`fact_store_tool`): Python never creates,
verifies or empties a fact store itself; it only moves files and reads the
identity the C++ seam reports. Cleanup is an explicit application-owned
allowlist, symlink-safe and owner-verified, never a recursive sweep of
unknown paths.
"""

import json
import os
import stat

from maintenance import (
    MaintenanceError,
    ROOT_MODE,
    read_identity_under_exclusive,
    read_recording_gap,
    replace_fact_database,
    run_maintenance,
)
from operations import (
    OperationBlocked,
    OperationFailed,
    OperationTypeSpec,
)

CLEAR_DIRNAME = ".clear"
FACTS_DB = "facts.sqlite3"
IDENTITY_FILE = "identity.json"
PUBLISHED_MARKER = "published.marker"
STAGING_STORE_DIR = "store"

HELPER_ENV = "SQUIRREL_FACT_STORE_HELPER"

# Explicit, application-owned derived-state names. Cleanup (and the
# already_clear check) deletes only these, nothing else under the root.
DERIVED_DIR_NAMES = ("generations", "staging", "quarantine", CLEAR_DIRNAME)
DERIVED_FILE_NAMES = (
    "active_manifest.json", "rollback_manifest.json", "derived_manifest.json",
)
DERIVED_FILE_PREFIXES = ("delta", ".snapshot")
GAP_FILES = ("recording_gap.json", "recording_gap.lock")
GAP_INTENT_PREFIX = ".recording_gap_intent."
PROCESS_MARKER_PREFIX = ".recording_process."

SAFE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

MEDIA_RESIDUE_DISCLAIMER = (
    "application-level deletion only: every application-controlled copy of "
    "the old facts and derived state has been deleted. This does not erase "
    "APFS snapshots, SSD wear-leveling remnants, system backups or backups "
    "you copied elsewhere.")

_PRISTINE_EPOCH = ""


def default_fact_store_helper():
    """Resolve the C++ fact-store helper binary.

    Tests set SQUIRREL_FACT_STORE_HELPER; the development default is the
    plugin build tree next to the librime checkout that hosts this package.
    """
    env = os.environ.get(HELPER_ENV)
    if env:
        return env
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
        "build", "plugins", "llm-rerank", "bin", "fact_store_tool"))


def _valid_identity_token(value):
    return (isinstance(value, str) and 1 <= len(value) <= 64
            and all(character in SAFE_ID_CHARS for character in value))


def _staging_root(root, operation_id):
    return os.path.join(root, CLEAR_DIRNAME, operation_id)


def _staging_store_dir(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), STAGING_STORE_DIR)


def _staging_db_path(root, operation_id):
    return os.path.join(_staging_store_dir(root, operation_id), FACTS_DB)


class _HelperFailed(Exception):
    """The C++ fact-store helper reported a stable failure."""

    def __init__(self, status):
        super().__init__(status)
        self.status = status


class FactStoreHelper:
    """Thin process wrapper over the C++ fact-store tool.

    Fact interpretation (schema, quick_check, version, emptiness, fresh
    identity) stays in C++; Python only parses the stable JSON envelope.
    """

    def __init__(self, helper_path=None, run=None):
        self.helper_path = helper_path or default_fact_store_helper()
        self._run = run

    def _execute(self, command, root, phase="staging"):
        import subprocess
        runner = self._run or subprocess.run
        try:
            completed = runner(
                [self.helper_path, command, "--root", root],
                capture_output=True, text=True, timeout=120)
        except OSError as error:
            raise OperationFailed(
                "fact_store_helper_unavailable", phase=phase,
                retryable=False, cause={"error": error.strerror})
        except Exception as error:
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"error": type(error).__name__})
        if completed.returncode != 0 and completed.returncode != 1:
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"exit": completed.returncode})
        try:
            payload = json.loads((completed.stdout or "").strip() or "null")
        except ValueError:
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if not isinstance(payload, dict):
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if payload.get("ok"):
            return payload
        raise _HelperFailed(payload.get("status") or "helper_failed")

    def verify(self, root):
        """Verify an existing store; returns (identity, empty) or raises."""
        payload = self._execute("verify", root)
        identity = {
            "history_id": payload.get("history_id"),
            "store_epoch": payload.get("store_epoch"),
            "hlc_physical_ms": payload.get("hlc_physical_ms"),
            "hlc_logical": payload.get("hlc_logical"),
        }
        if (not _valid_identity_token(identity["history_id"])
                or not _valid_identity_token(identity["store_epoch"])
                or type(identity["hlc_physical_ms"]) is not int
                or type(identity["hlc_logical"]) is not int
                or not isinstance(payload.get("empty"), bool)):
            raise OperationFailed(
                "fact_store_helper_invalid", phase="staging", retryable=False)
        return identity, payload["empty"]

    def create_empty(self, root):
        """Create and validate a fresh empty store; returns its identity."""
        payload = self._execute("create-empty", root)
        identity = {
            "history_id": payload.get("history_id"),
            "store_epoch": payload.get("store_epoch"),
            "hlc_physical_ms": payload.get("hlc_physical_ms"),
            "hlc_logical": payload.get("hlc_logical"),
        }
        if (not _valid_identity_token(identity["history_id"])
                or not _valid_identity_token(identity["store_epoch"])
                or type(identity["hlc_physical_ms"]) is not int
                or type(identity["hlc_logical"]) is not int
                or identity["hlc_logical"] != 0
                or payload.get("empty") is not True):
            raise OperationFailed(
                "fact_store_helper_invalid", phase="staging", retryable=False)
        return identity

    def snapshot(self, root, output, phase="staging"):
        """Create a consistent Online Backup snapshot of the live store at
        `root` into the not-yet-existing `output` file; returns the C++
        snapshot stats (identity, versions, counts, HLC high-water marks).
        """
        import subprocess
        runner = self._run or subprocess.run
        try:
            completed = runner(
                [self.helper_path, "snapshot", "--root", root, "--output",
                 output], capture_output=True, text=True, timeout=120)
        except OSError as error:
            raise OperationFailed(
                "fact_store_helper_unavailable", phase=phase,
                retryable=False, cause={"error": error.strerror})
        except Exception as error:
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"error": type(error).__name__})
        if completed.returncode not in (0, 1):
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"exit": completed.returncode})
        try:
            payload = json.loads((completed.stdout or "").strip() or "null")
        except ValueError:
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if isinstance(payload, dict) and payload.get("ok"):
            return self._parse_snapshot_stats(payload)
        status = (payload or {}).get("status") if isinstance(
            payload, dict) else None
        raise _HelperFailed(status or "helper_failed")

    def inspect(self, db_path, phase="staging"):
        """Read-only validation and stats of one standalone fact store
        database file (a snapshot or an extracted backup member)."""
        import subprocess
        runner = self._run or subprocess.run
        try:
            completed = runner(
                [self.helper_path, "inspect", "--db", db_path],
                capture_output=True, text=True, timeout=120)
        except OSError as error:
            raise OperationFailed(
                "fact_store_helper_unavailable", phase=phase,
                retryable=False, cause={"error": error.strerror})
        except Exception as error:
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"error": type(error).__name__})
        if completed.returncode not in (0, 1):
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"exit": completed.returncode})
        try:
            payload = json.loads((completed.stdout or "").strip() or "null")
        except ValueError:
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if isinstance(payload, dict) and payload.get("ok"):
            return self._parse_snapshot_stats(payload)
        status = (payload or {}).get("status") if isinstance(
            payload, dict) else None
        raise _HelperFailed(status or "helper_failed")

    def schema(self, root, phase="preflight"):
        """Read the live store's durable schema disposition through the C++
        seam. Returns {"fact_schema_version", "event_format_version",
        "disposition", "history_id", "store_epoch"} or raises. Never writes,
        never migrates; the disposition is derived from the C++ step table.
        """
        import subprocess
        runner = self._run or subprocess.run
        try:
            completed = runner(
                [self.helper_path, "schema", "--root", root],
                capture_output=True, text=True, timeout=120)
        except OSError as error:
            raise OperationFailed(
                "fact_store_helper_unavailable", phase=phase,
                retryable=False, cause={"error": error.strerror})
        except Exception as error:
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"error": type(error).__name__})
        if completed.returncode not in (0, 1):
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"exit": completed.returncode})
        try:
            payload = json.loads((completed.stdout or "").strip() or "null")
        except ValueError:
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if not isinstance(payload, dict):
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if not payload.get("ok"):
            raise _HelperFailed(payload.get("status") or "helper_failed")
        disposition = payload.get("disposition")
        if disposition not in ("current", "needs_migration", "unsupported",
                               "missing_step"):
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False)
        for key in ("fact_schema_version", "event_format_version"):
            if type(payload.get(key)) is not int:
                raise OperationFailed(
                    "fact_store_helper_invalid", phase=phase, retryable=False)
        if (not _valid_identity_token(payload.get("history_id") or "")
                or not _valid_identity_token(payload.get("store_epoch") or "")):
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False)
        return payload

    def migrate(self, db_path, phase="staging"):
        """Migrate ONE standalone database file (a snapshot or an extracted
        backup member) in place to the current schema head through the C++
        seam. Returns the migrate result envelope. On failure the file's
        facts are unchanged (the whole chain runs in one SQLite transaction).
        """
        import subprocess
        runner = self._run or subprocess.run
        try:
            completed = runner(
                [self.helper_path, "migrate", "--db", db_path],
                capture_output=True, text=True, timeout=120)
        except OSError as error:
            raise OperationFailed(
                "fact_store_helper_unavailable", phase=phase,
                retryable=False, cause={"error": error.strerror})
        except Exception as error:
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"error": type(error).__name__})
        if completed.returncode not in (0, 1):
            raise OperationFailed(
                "fact_store_helper_failed", phase=phase, retryable=True,
                cause={"exit": completed.returncode})
        try:
            payload = json.loads((completed.stdout or "").strip() or "null")
        except ValueError:
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if not isinstance(payload, dict):
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False,
                cause=None)
        if not payload.get("ok"):
            raise _HelperFailed(payload.get("status") or "helper_failed")
        if (type(payload.get("from_version")) is not int
                or type(payload.get("to_version")) is not int
                or type(payload.get("events_projected")) is not int
                or type(payload.get("events_preserved")) is not int
                or type(payload.get("epoch_changed")) is not bool
                or not _valid_identity_token(payload.get("history_id") or "")
                or not _valid_identity_token(payload.get("store_epoch") or "")):
            raise OperationFailed(
                "fact_store_helper_invalid", phase=phase, retryable=False)
        return payload

    def _parse_snapshot_stats(self, payload):
        """Validate and normalize the C++ snapshot stats envelope."""
        stats = {
            "history_id": payload.get("history_id"),
            "store_epoch": payload.get("store_epoch"),
            "fact_schema_version": payload.get("fact_schema_version"),
            "event_format_version_min": payload.get(
                "event_format_version_min"),
            "event_format_version_max": payload.get(
                "event_format_version_max"),
            "commit_count": payload.get("commit_count"),
            "event_count": payload.get("event_count"),
            "candidate_count": payload.get("candidate_count"),
            "retraction_count": payload.get("retraction_count"),
            "hlc_physical_ms": payload.get("hlc_physical_ms"),
            "hlc_logical": payload.get("hlc_logical"),
            "event_hlc_physical_ms": payload.get("event_hlc_physical_ms"),
            "event_hlc_logical": payload.get("event_hlc_logical"),
        }
        if (not _valid_identity_token(stats["history_id"])
                or not _valid_identity_token(stats["store_epoch"])
                or type(stats["fact_schema_version"]) is not int
                or stats["fact_schema_version"] < 1
                or any(type(stats[key]) is not int
                       for key in ("commit_count", "event_count",
                                   "candidate_count", "retraction_count",
                                   "hlc_physical_ms", "hlc_logical"))):
            raise OperationFailed(
                "fact_store_helper_invalid", phase="staging", retryable=False)
        for key in ("event_format_version_min", "event_format_version_max",
                    "event_hlc_physical_ms", "event_hlc_logical"):
            value = stats[key]
            if value is not None and type(value) is not int:
                raise OperationFailed(
                    "fact_store_helper_invalid", phase="staging",
                    retryable=False)
        if (stats["event_count"] == 0
                and (stats["event_hlc_physical_ms"] != -1
                     or stats["event_hlc_logical"] != -1
                     or stats["event_format_version_min"] != -1
                     or stats["event_format_version_max"] != -1)):
            raise OperationFailed(
                "fact_store_helper_invalid", phase="staging", retryable=False)
        return stats


def live_identity(helper, root):
    """Read the live store identity through the C++ seam.

    Returns None for a provably missing store; any other helper failure is
    converted into the stable error of the caller's choice.
    """
    try:
        return helper.verify(root)
    except _HelperFailed as error:
        if error.status == "no_store":
            return None
        raise OperationBlocked(
            "fact_store_unverifiable", phase="preflight",
            remediation="the fact store failed closed validation; inspect "
                        "and fix it before clearing",
            cause={"fault_code": error.status})


def _safe_isdir_lstat(root, name):
    try:
        st = os.lstat(os.path.join(root, name))
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode)


def _remove_entry(root_fd, name, euid):
    """Symlink-safe, owner-verified recursive delete of one application-owned
    entry, anchored to the root directory fd.

    A symlink is unlinked itself and never followed; directories are walked
    one entry at a time; foreign-owned entries fail closed so a mislabeled
    path can never be recursively swept.
    """
    removed_bytes = 0
    try:
        st = os.lstat(name, dir_fd=root_fd)
    except FileNotFoundError:
        return 0
    except OSError as error:
        raise OperationFailed(
            "cleanup_unavailable", phase="cleanup", retryable=True,
            cause={"path": name, "error": error.strerror})
    if stat.S_ISLNK(st.st_mode):
        os.unlink(name, dir_fd=root_fd)
        return 0
    if st.st_uid != euid:
        raise OperationFailed(
            "cleanup_owner_refused", phase="cleanup", retryable=False,
            cause={"path": name})
    if stat.S_ISREG(st.st_mode):
        removed_bytes += st.st_size
        os.unlink(name, dir_fd=root_fd)
        return removed_bytes
    if not stat.S_ISDIR(st.st_mode):
        raise OperationFailed(
            "cleanup_not_regular", phase="cleanup", retryable=False,
            cause={"path": name})
    try:
        dfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError as error:
        raise OperationFailed(
            "cleanup_unavailable", phase="cleanup", retryable=True,
            cause={"path": name, "error": error.strerror})
    try:
        for entry in os.scandir(dfd):
            entry_stat = entry.stat(follow_symlinks=False)
            if entry_stat.st_uid != euid:
                raise OperationFailed(
                    "cleanup_owner_refused", phase="cleanup", retryable=False,
                    cause={"path": os.path.join(name, entry.name)})
            if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                if entry.is_file(follow_symlinks=False):
                    removed_bytes += entry_stat.st_size
                os.unlink(entry.name, dir_fd=dfd)
            elif entry.is_dir(follow_symlinks=False):
                removed_bytes += _remove_entry(dfd, entry.name, euid)
            else:
                raise OperationFailed(
                    "cleanup_not_regular", phase="cleanup", retryable=False,
                    cause={"path": os.path.join(name, entry.name)})
    finally:
        os.close(dfd)
    os.rmdir(name, dir_fd=root_fd)
    return removed_bytes


def _remove_file(root_fd, name, euid):
    """Unlink one regular application-owned file (or its symlink)."""
    try:
        st = os.lstat(name, dir_fd=root_fd)
    except FileNotFoundError:
        return 0
    except OSError as error:
        raise OperationFailed(
            "cleanup_unavailable", phase="cleanup", retryable=True,
            cause={"path": name, "error": error.strerror})
    if stat.S_ISLNK(st.st_mode):
        os.unlink(name, dir_fd=root_fd)
        return 0
    if not stat.S_ISREG(st.st_mode) or st.st_uid != euid:
        raise OperationFailed(
            "cleanup_refused", phase="cleanup", retryable=False,
            cause={"path": name})
    removed = st.st_size
    os.unlink(name, dir_fd=root_fd)
    return removed


def _recorder_is_live(root_fd):
    """True when any recorder process marker is held by a live process."""
    try:
        names = [entry.name for entry in os.scandir(root_fd)
                 if entry.name.startswith(PROCESS_MARKER_PREFIX)]
    except OSError:
        return True
    for name in names:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError:
            return True
        try:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            except OSError:
                return True
        finally:
            os.close(fd)
    return False


def _gap_belongs_to_old_history(gap, old_epoch):
    """A gap record may be deleted only when it provably belongs to the old
    history (or documents nothing at all). Unknown provenance is kept."""
    if not isinstance(gap, dict):
        return False
    state = gap.get("state")
    if state == "present":
        return bool(old_epoch) and gap.get("store_epoch") == old_epoch
    if state == "none":
        return True
    return False


def _clean_operations(root_fd, operations_dir_fd, keep_id, euid):
    """Delete old operation details (JSON, locks, temp files), keeping the
    current operation's idempotency record and its locks.

    Run-lock files are deleted only for terminal operations: unlink-while-
    locked races a live executor of a non-terminal operation, and a blocked
    operation still awaits an explicit operator retry.
    """
    removed = 0
    terminal_ids = set()
    for entry in list(os.scandir(operations_dir_fd)):
        name = entry.name
        entry_stat = entry.stat(follow_symlinks=False)
        if entry_stat.st_uid != euid:
            raise OperationFailed(
                "cleanup_owner_refused", phase="cleanup", retryable=False,
                cause={"path": "operations/" + name})
        if name == "%s.json" % keep_id:
            continue
        if name == "%s.lock" % keep_id:
            continue
        if entry.is_symlink() or entry.is_file(follow_symlinks=False):
            if name.endswith(".json"):
                if not _record_is_terminal(operations_dir_fd, name, euid):
                    # A blocked operation still awaits an explicit operator
                    # retry; its record is not "useless" yet.
                    continue
                terminal_ids.add(name[: -len(".json")])
            if entry.is_file(follow_symlinks=False):
                removed += entry_stat.st_size
            os.unlink(entry.name, dir_fd=operations_dir_fd)
        elif entry.is_dir(follow_symlinks=False):
            removed += _remove_entry(operations_dir_fd, entry.name, euid)
        else:
            raise OperationFailed(
                "cleanup_not_regular", phase="cleanup", retryable=False,
                cause={"path": "operations/" + name})
    # Root-anchored executor run locks of terminal operations.
    for entry in list(os.scandir(root_fd)):
        if not entry.name.startswith(".operation-") or not entry.name.endswith(
                ".run"):
            continue
        other_id = entry.name[len(".operation-"):-len(".run")]
        if other_id == keep_id or other_id not in terminal_ids:
            continue
        try:
            st = os.lstat(entry.name, dir_fd=root_fd)
        except FileNotFoundError:
            continue
        if st.st_uid != euid:
            raise OperationFailed(
                "cleanup_owner_refused", phase="cleanup", retryable=False,
                cause={"path": entry.name})
        if not stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            raise OperationFailed(
                "cleanup_refused", phase="cleanup", retryable=False,
                cause={"path": entry.name})
        removed += st.st_size
        os.unlink(entry.name, dir_fd=root_fd)
    return removed


def _record_is_terminal(operations_dir_fd, name, euid):
    """Reads one operation record just far enough to decide terminality.

    Non-terminal records (queued/running/blocked) are kept; anything that
    cannot be read safely is kept as well (fail closed, never delete what we
    cannot prove is useless).
    """
    import json as json_module
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=operations_dir_fd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != euid:
            return False
        payload = json_module.load(os.fdopen(fd, "r", encoding="utf-8"))
        return isinstance(payload, dict) and payload.get("state") in (
            "succeeded", "failed", "cancelled")
    except (OSError, ValueError, UnicodeError):
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _open_root_fd(root):
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise OperationFailed(
            "root_unavailable", phase="cleanup", retryable=True,
            cause={"error": error.strerror})
    try:
        st = os.fstat(root_fd)
        if (not stat.S_ISDIR(st.st_mode)
                or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != ROOT_MODE):
            os.close(root_fd)
            raise OperationFailed(
                "root_unsafe", phase="cleanup", retryable=False)
    except OperationFailed:
        raise
    except OSError:
        os.close(root_fd)
        raise OperationFailed("root_unavailable", phase="cleanup",
                              retryable=True)
    return root_fd


def _derived_leftovers(root, operation_id, euid):
    """Explicit allowlist scan for app-owned derived leftovers.

    Returns a list of entry names pending cleanup. Control-plane operation
    records are deliberately excluded: a repeated clear must not be forced
    to publish new identities merely because the previous clear left its
    own idempotency record behind (those are removed idempotently during
    cleanup instead).
    """
    leftovers = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return ["<unreadable>"]
    for entry in entries:
        name = entry.name
        if name == FACTS_DB or name.startswith(FACTS_DB + "-"):
            continue
        if name == "maintenance.lock" or name == "operations":
            continue
        if name.startswith(PROCESS_MARKER_PREFIX):
            continue
        if name.startswith(".operation-") and name.endswith(".run"):
            continue
        if (name in DERIVED_DIR_NAMES or name in DERIVED_FILE_NAMES
                or name.startswith(DERIVED_FILE_PREFIXES)
                or name.startswith(GAP_INTENT_PREFIX)
                or name in GAP_FILES):
            leftovers.append(name)
    gap = read_recording_gap(root)
    if gap.get("state") in ("present", "unknown") and \
            "recording_gap.json" not in leftovers:
        leftovers.append("recording_gap.json")
    return leftovers


def _already_clear(root, operation_id, identity, empty, euid):
    if identity is None:
        return not _derived_leftovers(root, operation_id, euid)
    if not empty:
        return False
    return not _derived_leftovers(root, operation_id, euid)


def _write_json_atomic(path, payload, euid):
    """Owner-only temp file -> fsync -> rename -> parent fsync."""
    import json as json_module
    directory = os.path.dirname(path)
    dfd = None
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
        tmp_name = ".%s.tmp-%d" % (os.path.basename(path), os.getpid())
        fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        try:
            os.fchmod(fd, 0o600)
            data = json_module.dumps(payload, ensure_ascii=False,
                                     indent=2).encode("utf-8")
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_name, os.path.basename(path), src_dir_fd=dfd,
                   dst_dir_fd=dfd)
        os.fsync(dfd)
    except OSError as error:
        raise OperationFailed(
            "staging_write_failed", phase="staging", retryable=True,
            cause={"path": path, "error": error.strerror})
    finally:
        if dfd is not None:
            os.close(dfd)


def _read_json(path, euid):
    import json as json_module
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != euid
                or stat.S_IMODE(st.st_mode) != 0o600):
            raise OSError("unsafe")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            return json_module.load(stream)
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _load_staged_identity(staging_root, euid):
    payload = _read_json(os.path.join(staging_root, IDENTITY_FILE), euid)
    if not isinstance(payload, dict):
        return None
    if (not _valid_identity_token(payload.get("history_id"))
            or not _valid_identity_token(payload.get("store_epoch"))
            or type(payload.get("hlc_physical_ms")) is not int
            or type(payload.get("hlc_logical")) is not int):
        return None
    return payload


def _remove_staging(root, operation_id, euid):
    """Idempotent, symlink-safe removal of this operation's staging root."""
    root_fd = _open_root_fd(root)
    try:
        clear_dir = CLEAR_DIRNAME
        if not _safe_isdir_lstat(root, clear_dir):
            return 0
        try:
            dfd = os.open(clear_dir, os.O_RDONLY | os.O_NOFOLLOW,
                          dir_fd=root_fd)
        except OSError:
            return 0
        try:
            try:
                os.lstat(operation_id, dir_fd=dfd)
            except FileNotFoundError:
                return 0
            return _remove_entry(dfd, operation_id, euid)
        finally:
            os.close(dfd)
    finally:
        os.close(root_fd)


def _ensure_clear_dir(root, euid):
    """Create (or verify) the root-anchored .clear directory."""
    root_fd = _open_root_fd(root)
    try:
        try:
            st = os.lstat(CLEAR_DIRNAME, dir_fd=root_fd)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise OperationFailed(
                    "staging_unsafe", phase="staging", retryable=False,
                    cause={"path": CLEAR_DIRNAME})
            if st.st_uid != euid or stat.S_IMODE(st.st_mode) != ROOT_MODE:
                raise OperationFailed(
                    "staging_unsafe", phase="staging", retryable=False,
                    cause={"path": CLEAR_DIRNAME})
            return
        except FileNotFoundError:
            pass
        os.mkdir(CLEAR_DIRNAME, ROOT_MODE, dir_fd=root_fd)
    finally:
        os.close(root_fd)


def _staging_is_valid(helper, root, operation_id, staged_identity, euid):
    """Re-verify an existing staging artifact against its durable identity."""
    identity, empty = helper.verify(_staging_store_dir(root, operation_id))
    return (empty and identity == staged_identity)


def _probe_control_socket(path, socket_module=None):
    import socket
    sock = socket_module or socket
    probe = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
    try:
        probe.settimeout(2.0)
        probe.connect(path)
    except (OSError, ValueError):
        return False
    finally:
        probe.close()
    return True


class ClearSpec:
    """Factory for the `clear` OperationTypeSpec with injectable seams."""

    def __init__(self, root, *, helper=None, control_socket=None,
                 scoring_socket=None, timeout_s=5.0, now=None, sleep=None,
                 control_client_factory=None, euid=None):
        self.root = root
        self.euid = os.geteuid() if euid is None else euid
        self.helper = helper or FactStoreHelper()
        self.control_socket = control_socket
        self.scoring_socket = scoring_socket
        self.timeout_s = timeout_s
        self.now = now
        self.sleep = sleep
        self.control_client_factory = control_client_factory

    def _normalize(self, parameters):
        if not isinstance(parameters, dict):
            raise ValueError("clear parameters must be an object")
        epoch = parameters.get("expect_store_epoch", _PRISTINE_EPOCH)
        if epoch != _PRISTINE_EPOCH and not _valid_identity_token(epoch):
            raise ValueError("expect_store_epoch must be a store epoch")
        return {"expect_store_epoch": epoch}

    # -- steps --------------------------------------------------------------

    def _current_disposition(self, record, phase):
        """Read the live store through the C++ seam and classify the clear.

        Returns ("already_clear", identity) when the system is provably
        empty with nothing pending cleanup, otherwise ("proceed", identity).
        Raises OperationBlocked on a stale expectation, a missing expected
        store or an unverifiable store. Every phase prelude uses this one
        gate so the CAS and already_clear semantics stay identical across
        the machine.
        """
        expected = record["parameters"]["expect_store_epoch"]
        identity_empty = live_identity(self.helper, self.root)
        if identity_empty is not None:
            identity, empty = identity_empty
            if _already_clear(self.root, record["operation_id"], identity,
                              empty, self.euid):
                return "already_clear", identity
            if identity["store_epoch"] != expected:
                raise OperationBlocked(
                    "store_epoch_mismatch", phase=phase,
                    remediation="re-run clear with the current store epoch",
                    cause={"expected": expected,
                           "actual": identity["store_epoch"]})
            return "proceed", identity
        if expected != _PRISTINE_EPOCH:
            raise OperationBlocked(
                "store_epoch_mismatch", phase=phase,
                remediation="re-run clear with the current store epoch",
                cause={"expected": expected, "actual": None})
        if _already_clear(self.root, record["operation_id"], None, True,
                          self.euid):
            return "already_clear", None
        return "proceed", None

    def _step_preflight(self, record):
        self._current_disposition(record, "preflight")
        return {"advance": True}

    def _step_waiting_for_quiesce(self, record):
        disposition, _identity = self._current_disposition(
            record, "waiting-for-quiesce")
        if disposition == "already_clear":
            return {"advance": True}
        if self.control_socket is None:
            raise OperationFailed(
                "daemon_unavailable", phase="waiting-for-quiesce",
                retryable=True,
                remediation="start the semantic memory daemon and retry")
        if not _probe_control_socket(self.control_socket):
            raise OperationFailed(
                "daemon_unavailable", phase="waiting-for-quiesce",
                retryable=True,
                remediation="start the semantic memory daemon and retry")
        return {"advance": True}

    def _step_staging(self, record):
        operation_id = record["operation_id"]
        disposition, old_identity = self._current_disposition(
            record, "staging")
        if disposition == "already_clear":
            return {"advance": True}
        staging_root = _staging_root(self.root, operation_id)
        if os.path.lexists(staging_root):
            staged_identity = _load_staged_identity(staging_root, self.euid)
            if staged_identity is not None and _staging_is_valid(
                    self.helper, self.root, operation_id, staged_identity,
                    self.euid):
                return {"advance": True}
            _remove_staging(self.root, operation_id, self.euid)
        _ensure_clear_dir(self.root, self.euid)
        os.makedirs(staging_root, mode=0o700, exist_ok=False)
        staged_identity = self.helper.create_empty(
            _staging_store_dir(self.root, operation_id))
        # The staged identity must differ from the old one (epoch and
        # history) and from the operation's own expectation; anything else
        # is an impossible random coincidence or a broken helper.
        expected = record["parameters"]["expect_store_epoch"]
        if staged_identity["store_epoch"] == expected or (
                old_identity is not None and (
                    staged_identity["history_id"]
                    == old_identity["history_id"]
                    or staged_identity["store_epoch"]
                    == old_identity["store_epoch"])):
            raise OperationFailed(
                "staging_identity_collision", phase="staging",
                retryable=False)
        _write_json_atomic(os.path.join(staging_root, IDENTITY_FILE),
                           staged_identity, self.euid)
        try:
            db_size = os.lstat(_staging_db_path(
                self.root, operation_id)).st_size
        except OSError:
            db_size = 0
        return {"progress": {"bytes": db_size, "chunks": 1},
                "advance": True}

    def _step_publishing(self, record):
        operation_id = record["operation_id"]
        old_epoch = record["parameters"]["expect_store_epoch"]
        staged_identity = _load_staged_identity(
            _staging_root(self.root, operation_id), self.euid)
        if staged_identity is None:
            # A live store may have become already-clear between phases, but
            # a missing staged identity in a non-already-clear system means
            # the staging artifact was lost: fail deterministically.
            disposition, _identity = self._current_disposition(
                record, "publishing")
            if disposition == "already_clear":
                return {"advance": True}
            raise OperationBlocked(
                "staging_identity_missing", phase="publishing",
                remediation="restore or re-create the staging directory for "
                            "this operation, then retry")

        def replacement(lease):
            # Re-verify the expected epoch under the exclusive lease, before
            # any fact mutation (SCN-54-1: the CAS gate closes again here).
            # A pristine system has no store at all; that is only valid when
            # the operation itself expected no store. A present-but-unreadable
            # store fails closed (the epoch cannot be proven).
            if os.path.lexists(os.path.join(self.root, FACTS_DB)):
                live = read_identity_under_exclusive(self.root)
                disk_epoch = live["store_epoch"]
            else:
                disk_epoch = None
            marker_exists = _read_json(os.path.join(
                _staging_root(self.root, operation_id), PUBLISHED_MARKER),
                self.euid) is not None
            if disk_epoch == staged_identity["store_epoch"]:
                # A previous attempt already published (crash between the
                # atomic replace and the record write): re-persist the
                # marker and continue; never regenerate identity, never
                # restore the old epoch.
                pass
            elif marker_exists:
                # Marker says published, disk says something else: an
                # impossible sequence without external interference. Fail
                # closed.
                raise MaintenanceError("publish_state_inconsistent")
            elif disk_epoch is None:
                # Pristine clear: the replacement creates the first store.
                if old_epoch != _PRISTINE_EPOCH:
                    raise MaintenanceError("epoch_mismatch")
                try:
                    identity, empty = self.helper.verify(
                        _staging_store_dir(self.root, operation_id))
                except _HelperFailed:
                    raise MaintenanceError("staging_invalid")
                if not empty or identity != staged_identity:
                    raise MaintenanceError("staging_invalid")
                replace_fact_database(self.root, _staging_db_path(
                    self.root, operation_id), lease)
            elif disk_epoch != old_epoch:
                raise MaintenanceError("epoch_mismatch")
            else:
                try:
                    identity, empty = self.helper.verify(
                        _staging_store_dir(self.root, operation_id))
                except _HelperFailed:
                    raise MaintenanceError("staging_invalid")
                if not empty or identity != staged_identity:
                    raise MaintenanceError("staging_invalid")
                replace_fact_database(self.root, _staging_db_path(
                    self.root, operation_id), lease)
            _write_json_atomic(os.path.join(
                _staging_root(self.root, operation_id), PUBLISHED_MARKER),
                staged_identity, self.euid)
            # Prime the published store under the lease: on this host a WAL
            # database without sidecars cannot be opened read-only, and the
            # daemon's reopen is exactly such an open. A short read-write
            # checkpoint materializes the sidecars before the lease is
            # released.
            import sqlite3
            try:
                connection = sqlite3.connect(
                    os.path.join(self.root, FACTS_DB), timeout=0)
                try:
                    connection.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
                finally:
                    connection.close()
            except sqlite3.Error as error:
                raise MaintenanceError(
                    "publish_prime_failed") from error

        maintenance_kwargs = {"timeout_s": self.timeout_s}
        if self.now is not None:
            maintenance_kwargs["now"] = self.now
        if self.sleep is not None:
            maintenance_kwargs["sleep"] = self.sleep
        if self.control_client_factory is not None:
            maintenance_kwargs["control_client_factory"] = \
                self.control_client_factory
        try:
            recovery = run_maintenance(
                lambda: None, self.root, replacement, self.control_socket,
                operation_id, **maintenance_kwargs)
        except MaintenanceError as error:
            code = error.code
            if code == "epoch_mismatch":
                raise OperationBlocked(
                    "store_epoch_mismatch", phase="publishing",
                    remediation="re-run clear with the current store epoch",
                    cause={"expected": old_epoch})
            if code == "staging_invalid":
                raise OperationBlocked(
                    "staging_invalid", phase="publishing",
                    remediation="restore or re-create the staging directory "
                                "for this operation, then retry")
            if code == "publish_state_inconsistent":
                raise OperationBlocked(
                    "publish_state_inconsistent", phase="publishing",
                    remediation="the staged publication marker disagrees "
                                "with the store on disk; inspect before "
                                "retrying")
            if code == "publish_prime_failed":
                raise OperationFailed(
                    "publish_failed", phase="publishing", retryable=True,
                    remediation="retry; the published store re-primes on "
                                "the next attempt",
                    cause={"fault_code": code})
            if code == "quiesce_timeout":
                raise OperationFailed(
                    "quiesce_timeout", phase="publishing", retryable=True,
                    remediation="retry when the daemon and recorders are "
                                "less busy")
            if code == "maintenance_in_progress":
                raise OperationFailed(
                    "maintenance_in_progress", phase="publishing",
                    retryable=True,
                    remediation="retry after the concurrent maintenance "
                                "operation finishes")
            raise OperationFailed(
                "publish_failed", phase="publishing", retryable=True,
                cause={"fault_code": code})
        if not recovery.get("ok"):
            code = recovery.get("code", "publish_failed")
            if code == "maintenance_in_progress":
                raise OperationFailed(
                    "maintenance_in_progress", phase="publishing",
                    retryable=True)
            raise OperationFailed(
                "publish_failed", phase="publishing", retryable=True,
                cause={"fault_code": code})
        if (recovery.get("store_epoch") is not None
                and recovery.get("store_epoch")
                != staged_identity["store_epoch"]):
            raise OperationBlocked(
                "reopen_epoch_mismatch", phase="publishing",
                remediation="the daemon reports a different store epoch "
                            "than the published store; inspect before "
                            "retrying",
                cause={"published": staged_identity["store_epoch"],
                       "reported": recovery.get("store_epoch")})
        return {"advance": True}

    def _step_reopening(self, record):
        operation_id = record["operation_id"]
        staged_identity = _load_staged_identity(
            _staging_root(self.root, operation_id), self.euid)
        if record["cancel_requested"]:
            # Pre-publish compensation (cancel_phase == reopening). The
            # irreversible replacement only ever runs in the publishing
            # phase, so the disk must still hold the complete old store.
            identity_empty = live_identity(self.helper, self.root)
            if (identity_empty is not None and staged_identity is not None
                    and identity_empty[0]["store_epoch"]
                    == staged_identity["store_epoch"]):
                raise OperationBlocked(
                    "clear_published_during_cancel", phase="reopening",
                    remediation="the clear had already published when the "
                                "cancel was honored; inspect the store and "
                                "finish cleanup explicitly",
                    cause={"store_epoch": staged_identity["store_epoch"]})
            _remove_staging(self.root, operation_id, self.euid)
            return {"advance": True}
        if staged_identity is None:
            # Nothing was published (already_clear): the system must still
            # be provably empty; nothing needs reopening.
            disposition, _identity = self._current_disposition(
                record, "reopening")
            if disposition == "already_clear":
                return {"advance": True}
            raise OperationFailed(
                "reopen_unverifiable", phase="reopening", retryable=True,
                cause=None)
        # Success path: the disk must now hold the staged identity.
        identity_empty = live_identity(self.helper, self.root)
        if identity_empty is None:
            raise OperationFailed(
                "reopen_unverifiable", phase="reopening", retryable=True,
                cause=None)
        identity, _empty = identity_empty
        if identity["store_epoch"] != staged_identity["store_epoch"]:
            raise OperationBlocked(
                "store_epoch_unexpected", phase="reopening",
                remediation="the published store epoch does not match the "
                            "staged identity; inspect before retrying",
                cause={"published": staged_identity["store_epoch"],
                       "disk": identity["store_epoch"]})
        return {"advance": True}

    def _step_cleanup(self, record):
        operation_id = record["operation_id"]
        old_epoch = record["parameters"]["expect_store_epoch"]
        root_fd = _open_root_fd(self.root)
        removed_bytes = 0
        try:
            for name in DERIVED_DIR_NAMES:
                removed_bytes += _remove_entry(root_fd, name, self.euid)
            for entry in list(os.scandir(root_fd)):
                name = entry.name
                if (name in DERIVED_FILE_NAMES
                        or name.startswith(DERIVED_FILE_PREFIXES)):
                    removed_bytes += _remove_entry(root_fd, name, self.euid)
            # Old-history gap state: only the provably-safe parts. Live
            # recorder evidence and unknown provenance are kept.
            gap = read_recording_gap(self.root)
            if _gap_belongs_to_old_history(gap, old_epoch) and not \
                    _recorder_is_live(root_fd):
                for name in GAP_FILES:
                    removed_bytes += _remove_file(root_fd, name, self.euid)
                for entry in list(os.scandir(root_fd)):
                    if entry.name.startswith(GAP_INTENT_PREFIX):
                        removed_bytes += _remove_file(root_fd, entry.name,
                                                      self.euid)
            # Old operation details (terminal records and their locks/temp
            # files); the current operation's record and locks are kept.
            try:
                operations_fd = os.open("operations", os.O_RDONLY
                                        | os.O_NOFOLLOW, dir_fd=root_fd)
            except FileNotFoundError:
                operations_fd = None
            if operations_fd is not None:
                try:
                    removed_bytes += _clean_operations(
                        root_fd, operations_fd, operation_id, self.euid)
                finally:
                    os.close(operations_fd)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)

        # The outcome is derived from durable disk state AFTER the sweep, so
        # a crash at any point of cleanup retries into the identical result
        # (the staging directory and its markers are gone by now): a store
        # whose epoch differs from the expected one — or any store created
        # by a pristine clear — proves the replacement happened; otherwise
        # the system was already clear.
        identity_empty = live_identity(self.helper, self.root)
        if identity_empty is not None and (
                old_epoch == _PRISTINE_EPOCH
                or identity_empty[0]["store_epoch"] != old_epoch):
            outcome = "cleared"
            old_identity = {"store_epoch": old_epoch,
                            "history_id": None} if old_epoch else None
            new_identity = identity_empty[0]
        else:
            outcome = "already_clear"
            old_identity = identity_empty[0] if identity_empty else None
            new_identity = old_identity
        serving_ready = None
        if self.scoring_socket is not None:
            try:
                from status_core import probe_daemon
                serving = probe_daemon(self.scoring_socket)
                serving_ready = serving.get("state") == "up"
            except Exception:
                serving_ready = None
        result = {
            "outcome": outcome,
            "cleanup_complete": True,
            "old": old_identity,
            "new": new_identity,
            "serving_ready": serving_ready,
            "application_level_deletion": True,
            "media_residue_disclaimer": MEDIA_RESIDUE_DISCLAIMER,
        }
        return {"progress": {"bytes": removed_bytes, "chunks": 1},
                "advance": True, "result": result}

    def build(self):
        steps = {
            "preflight": self._step_preflight,
            "waiting-for-quiesce": self._step_waiting_for_quiesce,
            "staging": self._step_staging,
            "publishing": self._step_publishing,
            "reopening": self._step_reopening,
            "cleanup": self._step_cleanup,
        }
        return OperationTypeSpec(
            "clear",
            phases=("preflight", "waiting-for-quiesce", "staging",
                    "publishing", "reopening", "cleanup"),
            irreversible_phase="publishing",
            normalize=self._normalize,
            steps=steps,
            cancel_phase="reopening",
        )


def build_clear_spec(root, **seams):
    """Build the production `clear` operation type for one semantic root."""
    return ClearSpec(root, **seams).build()


def production_registry(root, **seams):
    """The production operation registry: `clear` only (backup/restore/
    rebuild/quarantine arrive with their own tickets)."""
    from operations import OperationRegistry
    registry = OperationRegistry()
    registry.register(build_clear_spec(root, **seams))
    return registry
