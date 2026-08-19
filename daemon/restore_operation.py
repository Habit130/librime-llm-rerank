#!/usr/bin/env python3
"""The `restore` production operation type (Habit130/squirrel#56, #57).

`squirrel-semantic-memory restore` atomically replaces the whole live fact
store with a verified backup, preserving the backup's logical history
(history_id, event/commit IDs, HLC state) while minting a NEW store_epoch,
under the #53/#54 maintenance seam. Restore never merges events by id.

Phase machine (canonical order, spec #43, clear-shaped):

    preflight -> waiting-for-quiesce -> staging -> publishing ->
    reopening -> cleanup

- `publishing` is the irreversible phase. The whole-store replacement, the
  durable `published.marker`, the bounded exclusive quiesce and (when
  requested) the `--backup-current` snapshot of the current store all happen
  inside one publishing step under the exclusive maintenance lease, so the
  persisted phase is an honest boundary: a cancel requested while the
  persisted phase is `publishing` is refused as uncancellable, and a cancel
  honored before it can never race a replacement.
- Staging (the only expensive fact work: extraction, migrate-on-file for
  supported-old backups, and the C++ prepare-restore that mints the new
  store_epoch) completes before any daemon prepare. The staged identity is
  durable (`identity.json`) and reused verbatim across retries, so no crash
  window can regenerate history or epoch identities.
- The backup's `history_id`, event IDs, commit IDs, candidates, retractions
  and HLC state are preserved by the C++ prepare-restore seam; Python never
  UPDATEs meta itself.

Retention is explicit: `--backup-current <path>` XOR `--discard-current`
must be chosen before any mutation. `--backup-current` runs AFTER quiesce
and BEFORE the replace, using the existing backup.create / snapshot path to
`<path>` (destination_exists and owner-only-medium checks still apply); if
that backup fails, the live store is unchanged.

Health contract (spec #43 / #57):

- A healthy current store is restored over with the epoch CAS
  (`--expect-store-epoch`) and `--backup-current` / `--discard-current`;
  an unreadable or missing store fails closed without the #57 flags.
- An unreadable (present-but-unreadable) current store is restored over
  ONLY with the flag pair `--accept-unreadable-current` +
  `--expect-current-fingerprint <hash>`. After quiesce the fingerprint is
  computed from the already-opened DB/WAL/SHM descriptors and the as-is
  bytes are copied into `quarantine/<operation_id>/`, verified and fsynced
  BEFORE the replace; any fingerprint mismatch or quarantine failure aborts
  with no replace and no successful-looking quarantine.
- A truly missing store is restored over ONLY with `--expect-no-store` (a
  distinct branch that never quarantines and never satisfies an unreadable
  file).

Fact semantics live in C++ (`fact_store_tool`): Python never creates,
verifies, migrates or epoch-mints a fact store itself; it only moves files
and reads the identity the C++ seam reports. No output, log or error ever
contains 上文, candidate text or embeddings.
"""

import os
import re
import stat

from backup_operation import (
    BackupError,
    FACTS_MEMBER,
    MANIFEST_MEMBER,
    SENSITIVE_DECLARATION,
    _backup_id,
    _cleanup_verify_dir,
    _extract_member,
    _now_iso,
    _open_verify_tempdir,
    _output_absolute,
    build_manifest,
    parse_zip_structure,
    read_backup_manifest,
    verify_backup,
)
from clear_operation import (
    FactStoreHelper,
    _HelperFailed,
    _open_root_fd,
    _probe_control_socket,
    _read_json,
    _remove_entry,
    _valid_identity_token,
    _write_json_atomic,
    live_identity,
)
from maintenance import (
    MaintenanceError,
    read_identity_under_exclusive,
    replace_fact_database,
    run_maintenance,
)
from operations import (
    OperationBlocked,
    OperationFailed,
    OperationTypeSpec,
)
from quarantine import (
    classify_current_store,
    current_store_bytes,
    open_current_files,
    probe_current_epoch,
    publish_quarantine,
)

RESTORE_DIRNAME = ".restore"
FACTS_DB = "facts.sqlite3"
IDENTITY_FILE = "identity.json"
STAGING_MANIFEST = "manifest.json"
PUBLISHED_MARKER = "published.marker"
STAGING_STORE_DIR = "store"
BACKUP_CURRENT_SNAPSHOT = "backup-current.sqlite3"

# Explicit, application-owned staging names; cleanup deletes only these.
RESTORE_DERIVED_NAMES = (RESTORE_DIRNAME,)

_PRISTINE_EPOCH = ""


def _staging_root(root, operation_id):
    return os.path.join(root, RESTORE_DIRNAME, operation_id)


def _restore_mode(parameters):
    """The normalized restore disposition mode: "healthy" (default),
    "unreadable" (`--accept-unreadable-current` + fingerprint), or
    "no-store" (`--expect-no-store`). The mode drives every phase gate."""
    if parameters.get("expect_no_store"):
        return "no-store"
    if parameters.get("accept_unreadable_current"):
        return "unreadable"
    return "healthy"


def _staging_store_dir(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), STAGING_STORE_DIR)


def _staging_db_path(root, operation_id):
    return os.path.join(_staging_store_dir(root, operation_id), FACTS_DB)


def _staging_manifest_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), STAGING_MANIFEST)


def _identity_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), IDENTITY_FILE)


def _published_marker_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), PUBLISHED_MARKER)


def _backup_current_snapshot_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id),
                        BACKUP_CURRENT_SNAPSHOT)


def _ensure_restore_dir(root, euid):
    """Create (or verify) the root-anchored .restore directory."""
    root_fd = _open_root_fd(root)
    try:
        try:
            st = os.lstat(RESTORE_DIRNAME, dir_fd=root_fd)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise OperationBlocked(
                    "staging_unsafe", phase="staging", retryable=False,
                    cause={"path": RESTORE_DIRNAME})
            if st.st_uid != euid or stat.S_IMODE(st.st_mode) != 0o700:
                raise OperationBlocked(
                    "staging_unsafe", phase="staging", retryable=False,
                    cause={"path": RESTORE_DIRNAME})
            return
        except FileNotFoundError:
            pass
        os.mkdir(RESTORE_DIRNAME, 0o700, dir_fd=root_fd)
    finally:
        os.close(root_fd)


def _remove_staging(root, operation_id, euid):
    """Idempotent, symlink-safe removal of this operation's staging root,
    anchored to the semantic root fd (a swapped symlink is unlinked, never
    followed)."""
    root_fd = None
    try:
        root_fd = _open_root_fd(root)
    except OperationFailed:
        # The root became unreadable; a later retry cleans it. The staging
        # directory must never be swept through an unverified root.
        return
    try:
        try:
            os.lstat(RESTORE_DIRNAME, dir_fd=root_fd)
        except FileNotFoundError:
            return
        except OSError:
            return
        try:
            dfd = os.open(RESTORE_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                          dir_fd=root_fd)
        except OSError:
            return
        try:
            try:
                os.lstat(operation_id, dir_fd=dfd)
            except FileNotFoundError:
                return
            _remove_entry(dfd, operation_id, euid)
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _backup_current_staging_id(operation_id):
    """The `.backup` staging id used by this restore's --backup-current
    snapshot (kept short so the nested backup staging never collides)."""
    return "restore-%s-bk" % operation_id[:24]


def _remove_backup_current_staging(root, operation_id, euid):
    """Idempotent, symlink-safe removal of the --backup-current snapshot
    staging under `.backup` (crash residue between the snapshot and the
    replace must never be left behind)."""
    from backup_operation import (
        _remove_staging as _remove_backup_staging,
    )
    _remove_backup_staging(root, _backup_current_staging_id(operation_id),
                           euid)


def _load_staged_identity(root, operation_id, euid):
    payload = _read_json(_identity_path(root, operation_id), euid)
    if not isinstance(payload, dict):
        return None
    if (not _valid_identity_token(payload.get("history_id"))
            or not _valid_identity_token(payload.get("store_epoch"))
            or type(payload.get("hlc_physical_ms")) is not int
            or type(payload.get("hlc_logical")) is not int):
        return None
    return payload


def _load_staged_manifest(root, operation_id, euid):
    payload = _read_json(_staging_manifest_path(root, operation_id), euid)
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("backup_manifest"), dict):
        return None
    if not isinstance(payload.get("prepared"), dict):
        return None
    return payload


def _verify_staging(helper, root, operation_id, staged_identity, euid):
    """Re-verify an existing staging artifact: the prepared store must exist
    and its C++ interpretation must match the durable staged identity."""
    try:
        identity, _empty = helper.verify(_staging_store_dir(root, operation_id))
    except Exception:
        return False
    return identity == staged_identity


def _staging_is_complete(helper, root, operation_id, euid):
    staged_identity = _load_staged_identity(root, operation_id, euid)
    if staged_identity is None:
        return False, None
    manifest = _load_staged_manifest(root, operation_id, euid)
    if manifest is None:
        return False, None
    if not _verify_staging(helper, root, operation_id, staged_identity, euid):
        return False, None
    return True, staged_identity


def _verify_restore_backup(from_path, helper, phase="preflight"):
    """Fully offline validation of the backup container for restore.

    Validates the container structure, exact member set, member names,
    attributes, compression, sizes, CRC, the manifest, the extracted
    database's SHA-256/size/integrity and its schema version. A supported-old
    backup (SCN-56-9) is classified through the migrate seam (the backup
    original is never modified; only the staging copy is migrated later); a
    too-new or missing-step backup is refused in preflight. Returns
    (manifest, stats, disposition) where stats are the C++ interpretation of
    the extracted database for a current backup, or the manifest's recorded
    stats for a supported-old one, and disposition is "current" or
    "supported-old".
    """
    parse_zip_structure(from_path)
    manifest = read_backup_manifest(from_path)

    directory = _open_verify_tempdir()
    extracted = {}
    digests = {}
    try:
        import zipfile
        try:
            archive = zipfile.ZipFile(from_path, "r")
        except (OSError, ValueError):
            raise BackupError("backup_unreadable")
        except zipfile.BadZipFile:
            raise BackupError("zip_malformed")
        try:
            members = archive.infolist()
            if len(members) != 2 \
                    or set(info.filename for info in members) \
                    != {FACTS_MEMBER, MANIFEST_MEMBER}:
                raise BackupError("zip_member_set_invalid")
            for info in members:
                if info.filename == FACTS_MEMBER:
                    import hashlib
                    sha = hashlib.sha256()
                    extracted[info.filename] = _extract_member(
                        archive, info, directory, info.filename, sha)
                    digests[info.filename] = sha.hexdigest()
                else:
                    extracted[info.filename] = _extract_member(
                        archive, info, directory, info.filename, None)
        except BackupError:
            raise
        except (ValueError, zipfile.BadZipFile, EOFError):
            raise BackupError("zip_malformed")
        finally:
            archive.close()

        db_path = os.path.join(directory, FACTS_MEMBER)
        db_size = extracted[FACTS_MEMBER]
        if db_size != manifest["database_size"]:
            raise BackupError("size_mismatch", cause={
                "field": "size",
                "expected": manifest["database_size"], "actual": db_size})
        if digests[FACTS_MEMBER] != manifest["database_sha256"]:
            raise BackupError("checksum_mismatch", cause={
                "field": "checksum",
                "expected": manifest["database_sha256"],
                "actual": digests[FACTS_MEMBER]})
        try:
            stats = helper.inspect(db_path, phase=phase)
        except _HelperFailed:
            # A supported-old backup is refused by the recorder-mode inspect.
            # Classify it through the migrate seam on THIS extracted copy:
            # migrated -> supported-old (allowed; the staging copy is
            # migrated later, the backup original never changes);
            # unsupported/missing-step -> refused in preflight.
            try:
                migrated = helper.migrate(db_path, phase=phase)
            except _HelperFailed as error:
                status = error.status
                if status in ("unsupported_version", "missing_step"):
                    raise BackupError(
                        "manifest_version_unsupported"
                        if status == "unsupported_version"
                        else "schema_missing_step",
                        cause={"fault_code": status})
                raise BackupError("fact_store_invalid",
                                  cause={"fault_code": status})
            if migrated.get("status") not in ("migrated", "no_migration"):
                raise BackupError("fact_store_invalid", cause={
                    "fault_code": migrated.get("status")})
            # The manifest's own recorded stats (validated at creation) are
            # the plan's source for a supported-old backup; the staged
            # migration is re-validated in the staging phase.
            stats = {
                "history_id": manifest["history_id"],
                "store_epoch": manifest["store_epoch"],
                "fact_schema_version": manifest["fact_schema_version"],
                "event_format_version_min": manifest[
                    "event_format_version_min"],
                "event_format_version_max": manifest[
                    "event_format_version_max"],
                "commit_count": manifest["commit_count"],
                "event_count": manifest["event_count"],
                "candidate_count": manifest["candidate_count"],
                "retraction_count": manifest["retraction_count"],
                "hlc_physical_ms": manifest["hlc_high_water"]["physical_ms"],
                "hlc_logical": manifest["hlc_high_water"]["logical"],
                "event_hlc_physical_ms": (
                    manifest["event_hlc_high_water"]["physical_ms"]
                    if manifest["event_hlc_high_water"] is not None else -1),
                "event_hlc_logical": (
                    manifest["event_hlc_high_water"]["logical"]
                    if manifest["event_hlc_high_water"] is not None else -1),
            }
            return manifest, stats, "supported-old"
        return manifest, stats, "current"
    finally:
        _cleanup_verify_dir(directory)


def _space_available(root):
    """Best-effort statvfs free space (RISK-56-4): None when unavailable."""
    try:
        st = os.statvfs(root)
    except OSError:
        return None
    return st.f_bavail * st.f_frsize


class RestoreSpec:
    """Factory for the `restore` OperationTypeSpec with injectable seams."""

    def __init__(self, root, *, helper=None, control_socket=None,
                 scoring_socket=None, timeout_s=5.0, now=None, sleep=None,
                 control_client_factory=None, euid=None, program_version="",
                 link=None, probe_medium=None, read_backup_manifest_fn=None):
        self.root = root
        self.euid = os.geteuid() if euid is None else euid
        self.helper = helper or FactStoreHelper()
        self.control_socket = control_socket
        self.scoring_socket = scoring_socket
        self.timeout_s = timeout_s
        self.now = now
        self.sleep = sleep
        self.control_client_factory = control_client_factory
        self.program_version = program_version
        self.link = link
        self.probe_medium = probe_medium
        self.read_backup_manifest_fn = read_backup_manifest_fn

    def _normalize(self, parameters):
        if not isinstance(parameters, dict):
            raise ValueError("restore parameters must be an object")
        from_path = parameters.get("from_path")
        if not isinstance(from_path, str) or not from_path:
            raise ValueError("from_path must be a path")
        if "\x00" in from_path:
            raise ValueError("from_path must not contain NUL")
        from_path = os.path.abspath(from_path)
        backup_current = parameters.get("backup_current")
        discard_current = parameters.get("discard_current")
        if backup_current is not None:
            backup_current = _output_absolute(backup_current)
        if bool(backup_current) == bool(discard_current):
            # --backup-current XOR --discard-current is mandatory (spec #43);
            # missing both or both set is a usage failure before any
            # mutation (SCN-56-4).
            raise ValueError("choose exactly one of backup-current or "
                             "discard-current")
        epoch = parameters.get("expect_store_epoch", _PRISTINE_EPOCH)
        if epoch != _PRISTINE_EPOCH and not _valid_identity_token(epoch):
            raise ValueError("expect_store_epoch must be a store epoch")
        # #57 unreadable-current / no-store flags (reserved in #56, now
        # implemented). The flag pair is atomic and mutually exclusive with
        # --expect-no-store; a present-but-unreadable current store is the
        # only scene the pair accepts, and an absent store is the only scene
        # --expect-no-store accepts.
        accept_unreadable = bool(parameters.get("accept_unreadable_current"))
        fingerprint = parameters.get("expect_current_fingerprint")
        if not isinstance(fingerprint, str):
            fingerprint = ""
        fingerprint = fingerprint.strip().lower()
        if fingerprint and not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("expect_current_fingerprint must be a sha256 "
                             "hex digest (64 hex characters)")
        expect_no_store = bool(parameters.get("expect_no_store"))
        if bool(accept_unreadable) != bool(fingerprint):
            raise ValueError("--accept-unreadable-current and "
                             "--expect-current-fingerprint must be provided "
                             "together")
        if expect_no_store and (accept_unreadable or fingerprint):
            raise ValueError("--expect-no-store is exclusive with the "
                             "unreadable-current flags")
        if expect_no_store and backup_current is not None:
            raise ValueError("--expect-no-store cannot be combined with "
                             "--backup-current (there is no current store to "
                             "back up)")
        if accept_unreadable and backup_current is not None:
            raise ValueError("--accept-unreadable-current cannot be combined "
                             "with --backup-current (an unreadable current "
                             "store cannot be snapshotted)")
        if (accept_unreadable or expect_no_store) and epoch != _PRISTINE_EPOCH:
            raise ValueError("no current store epoch is readable for an "
                             "unreadable or no-store restore; do not pass "
                             "expect_store_epoch")
        return {
            "from_path": from_path,
            "backup_current": backup_current,
            "discard_current": bool(discard_current),
            "expect_store_epoch": epoch,
            "accept_unreadable_current": accept_unreadable,
            "expect_current_fingerprint": fingerprint,
            "expect_no_store": expect_no_store,
        }

    # -- steps --------------------------------------------------------------

    def _current_disposition(self, record, phase):
        """Read the live store through the C++ seam and verify the CAS.

        Three modes (spec #43 / #57), selected by the normalized parameters:

        - healthy (default): requires a readable current store whose
          store_epoch == the expected one; unreadable -> fail closed,
          missing -> fail closed (#56 preserved).
        - unreadable: requires BOTH `--accept-unreadable-current` and
          `--expect-current-fingerprint`; the store must be PRESENT but the
          identity seam must fail to read it. A healthy readable store is
          refused (this path is not a bypass of the epoch CAS) and a missing
          store is refused (that is `--expect-no-store`).
        - no-store: requires `--expect-no-store`; the store must be ABSENT.
          An unreadable present file does not satisfy it, and a healthy
          present store does not either.

        Returns ("healthy", identity) | ("unreadable", None) |
        ("no-store", None). Every phase prelude uses this one gate so the
        disposition semantics stay identical across the machine.
        """
        parameters = record["parameters"]
        mode = _restore_mode(parameters)
        expected = parameters["expect_store_epoch"]
        if mode == "no-store":
            # The no-store gate is RAW presence: --expect-no-store requires
            # the facts path to be absent, never satisfied by an unreadable
            # file that happens to exist.
            if os.path.lexists(os.path.join(self.root, FACTS_DB)):
                raise OperationBlocked(
                    "store_present_unexpected", phase=phase,
                    remediation="a facts database exists (or an unreadable "
                                "file occupies the path); --expect-no-store "
                                "requires the store to be absent",
                    cause=None)
            return ("no-store", None)
        if mode == "unreadable":
            # The unreadable gate runs the C++ `schema` seam on a THROWAWAY
            # COPY of the current store (never the live file, so the as-is
            # bytes the operator's fingerprint covers stay untouched): a
            # store the seam cannot read (corrupt, clock-invalid, open or
            # permission failure) is the unreadable scene this path
            # quarantines; a store the seam reads (healthy, supported-old,
            # too-new) is refused — the path is not a bypass of the epoch
            # CAS and migrate stays the only upgrade path (RISK-57-2).
            disposition, _detail = classify_current_store(
                self.root, self.helper, self.euid)
            if disposition == "missing":
                raise OperationBlocked(
                    "store_missing", phase=phase,
                    remediation="no facts database exists; the unreadable-"
                                "current path requires a present (but "
                                "unreadable) store; use --expect-no-store "
                                "for a truly missing store",
                    cause=None)
            if disposition == "readable":
                raise OperationBlocked(
                    "store_present_unexpected", phase=phase,
                    remediation="the current store is readable through the "
                                "fact-store seam; the unreadable-current path "
                                "is for a store the identity seam cannot "
                                "read, not a bypass of the epoch CAS",
                    cause={"disposition": _detail})
            return ("unreadable", None)
        try:
            identity_empty = live_identity(self.helper, self.root)
        except OperationBlocked as error:
            if error.code != "fact_store_unverifiable":
                raise
            # The identity seam could not read a PRESENT store.
            raise OperationBlocked(
                "fact_store_unverifiable", phase=phase,
                remediation="the fact store failed closed validation; inspect "
                            "and fix it before restoring, or re-run restore "
                            "with --accept-unreadable-current and "
                            "--expect-current-fingerprint",
                cause={"fault_code": error.cause.get("fault_code")
                       if isinstance(error.cause, dict) else None})
        if identity_empty is None:
            raise OperationBlocked(
                "store_missing", phase=phase,
                remediation="no facts database exists; there is nothing to "
                            "restore over (restore never creates a store)",
                cause=None)
        identity, _empty = identity_empty
        if identity["store_epoch"] != expected:
            raise OperationBlocked(
                "store_epoch_mismatch", phase=phase,
                remediation="re-run restore with the current store epoch",
                cause={"expected": expected,
                       "actual": identity["store_epoch"]})
        return ("healthy", identity)

    def _step_preflight(self, record):
        disposition, _identity = self._current_disposition(record, "preflight")
        from_path = record["parameters"]["from_path"]
        try:
            manifest, stats, backup_disposition = _verify_restore_backup(
                from_path, self.helper, phase="preflight")
        except BackupError as error:
            raise OperationBlocked(
                error.code, phase="preflight",
                remediation="the backup failed offline validation; inspect "
                            "it and re-create it if needed",
                cause=error.cause)
        # Best-effort space check (spec #43 "版本和空间"; RISK-56-4): the
        # replace is atomic, but an obvious no-space condition must fail in
        # preflight with the current state untouched. The unreadable path
        # also needs space for the as-is quarantine copy of the current
        # store (spec #57: 空间不足时不发布恢复库).
        required = manifest.get("database_size")
        if disposition == "unreadable":
            current_bytes = current_store_bytes(self.root)
            if current_bytes is not None:
                required = (required or 0) + current_bytes
        available = _space_available(self.root)
        if (required is not None and available is not None
                and required > available):
            raise OperationBlocked(
                "insufficient_space", phase="preflight",
                remediation="free space in the facts root and retry",
                cause={"required_bytes": required,
                       "available_bytes": available})
        # Preflight is read-only: it never creates staging (a preflight
        # failure must leave the current state untouched). The durable plan
        # (backup manifest + stats) is (re)built idempotently in the staging
        # phase.
        return {"advance": True}

    def _step_waiting_for_quiesce(self, record):
        self._current_disposition(record, "waiting-for-quiesce")
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
        self._current_disposition(record, "staging")
        complete, staged_identity = _staging_is_complete(
            self.helper, self.root, operation_id, self.euid)
        if complete:
            return {"advance": True}
        _remove_staging(self.root, operation_id, self.euid)
        _ensure_restore_dir(self.root, self.euid)
        os.makedirs(_staging_root(self.root, operation_id), mode=0o700,
                    exist_ok=False)
        os.makedirs(_staging_store_dir(self.root, operation_id), mode=0o700,
                    exist_ok=False)
        from_path = record["parameters"]["from_path"]
        # The durable plan: backup manifest + C++ interpretation. It is
        # (re)built idempotently (the backup is immutable) so a crash before
        # it was durably written never strands the operation.
        staged_manifest = _load_staged_manifest(
            self.root, operation_id, self.euid)
        if staged_manifest is None:
            try:
                manifest, stats, disposition = _verify_restore_backup(
                    from_path, self.helper, phase="staging")
            except BackupError as error:
                raise OperationBlocked(
                    error.code, phase="staging",
                    remediation="the backup failed offline validation; "
                                "inspect it and re-create it if needed",
                    cause=error.cause)
            staged_manifest = {
                "backup_manifest": manifest,
                "prepared": None,
                "backup_stats": stats,
                "backup_disposition": disposition,
            }
            _write_json_atomic(
                _staging_manifest_path(self.root, operation_id),
                staged_manifest, self.euid)
        # 1. Extract the backup's facts member into the staging store
        #    (checksum re-verified against the manifest).
        db_path = _staging_db_path(self.root, operation_id)
        import hashlib
        import zipfile
        try:
            archive = zipfile.ZipFile(from_path, "r")
        except (OSError, ValueError):
            raise OperationBlocked(
                "backup_unreadable", phase="staging",
                remediation="the backup container cannot be read")
        except zipfile.BadZipFile:
            raise OperationBlocked(
                "zip_malformed", phase="staging",
                remediation="the backup container is not a well-formed ZIP")
        try:
            info = None
            for candidate in archive.infolist():
                if candidate.filename == FACTS_MEMBER:
                    info = candidate
                    break
            if info is None:
                raise OperationBlocked(
                    "zip_member_set_invalid", phase="staging",
                    remediation="the backup container is missing the facts "
                                "member")
            sha = hashlib.sha256()
            _extract_member(archive, info, _staging_store_dir(
                self.root, operation_id), FACTS_DB, sha)
        except BackupError as error:
            raise OperationBlocked(
                error.code, phase="staging",
                remediation="the backup member failed extraction")
        finally:
            archive.close()
        try:
            st = os.lstat(db_path)
            regular = stat.S_ISREG(st.st_mode) and st.st_uid == self.euid \
                and stat.S_IMODE(st.st_mode) == 0o600
        except OSError:
            regular = False
        if not regular:
            raise OperationBlocked(
                "staging_invalid", phase="staging",
                remediation="the extracted facts member is not a regular "
                            "owner-only file; re-run restore")
        if sha.hexdigest() != staged_manifest["backup_manifest"][
                "database_sha256"]:
            raise OperationBlocked(
                "checksum_mismatch", phase="staging",
                remediation="the extracted facts member failed its checksum; "
                            "re-run restore")
        # 2. Migrate a supported-old backup on the STAGING copy only (the
        #    backup original is never modified).
        disposition = staged_manifest["backup_disposition"]
        if disposition == "supported-old":
            try:
                migrated = self.helper.migrate(db_path, phase="staging")
            except _HelperFailed as error:
                raise OperationBlocked(
                    "migration_blocked", phase="staging",
                    remediation="the backup's facts could not be migrated; "
                                "the backup original is unchanged",
                    cause={"fault_code": error.status})
            if migrated.get("status") not in ("migrated", "no_migration"):
                raise OperationBlocked(
                    "migration_blocked", phase="staging",
                    remediation="the backup's facts could not be migrated; "
                                "the backup original is unchanged",
                    cause={"status": migrated.get("status")})
        # 3. Mint a NEW store_epoch through the C++ seam; history_id and all
        #    facts/HLC are preserved. Python never UPDATEs meta itself.
        try:
            prepared = self.helper.prepare_restore(db_path, phase="staging")
        except _HelperFailed as error:
            raise OperationBlocked(
                "restore_prepare_failed", phase="staging",
                remediation="the restore staging file could not be prepared; "
                            "the backup original is unchanged",
                cause={"fault_code": error.status})
        _live_disposition, _live_identity = self._current_disposition(
            record, "staging")
        old_epoch = record["parameters"]["expect_store_epoch"]
        backup_epoch = staged_manifest["backup_manifest"]["store_epoch"]
        if (prepared["store_epoch"] == backup_epoch
                or prepared["store_epoch"] == old_epoch
                or prepared["history_id"]
                != staged_manifest["backup_manifest"]["history_id"]):
            raise OperationBlocked(
                "staging_identity_collision", phase="staging",
                retryable=False,
                remediation="the staged restore identity is impossible; "
                            "inspect before retrying")
        staged_identity = {
            "history_id": prepared["history_id"],
            "store_epoch": prepared["store_epoch"],
            "hlc_physical_ms": prepared["hlc_physical_ms"],
            "hlc_logical": prepared["hlc_logical"],
        }
        _write_json_atomic(_identity_path(self.root, operation_id),
                           staged_identity, self.euid)
        staged_manifest["prepared"] = prepared
        _write_json_atomic(_staging_manifest_path(self.root, operation_id),
                           staged_manifest, self.euid)
        try:
            db_size = os.lstat(db_path).st_size
        except OSError:
            db_size = 0
        return {"progress": {"bytes": db_size, "chunks": 1},
                "advance": True}

    def _backup_current(self, operation_id, output):
        """Snapshot the CURRENT store to `<output>` under the exclusive
        lease, reusing the backup.create / snapshot path (owner-only
        destination, no-overwrite publication, self-verification). Raises
        before the replace on any failure: the live store stays unchanged.
        Returns the published backup's manifest."""
        from backup_operation import (
            BackupSpec,
            _ensure_backup_dir,
            _remove_staging as _remove_backup_staging,
            _snapshot_path,
            _staging_manifest_path as _backup_manifest_path,
        )
        backup_op_id = _backup_current_staging_id(operation_id)
        backup_spec = BackupSpec(
            self.root, helper=self.helper, euid=self.euid,
            program_version=self.program_version, now=self.now,
            link=self.link, probe_medium=self.probe_medium,
            read_backup_manifest_fn=self.read_backup_manifest_fn)
        _ensure_backup_dir(self.root, self.euid)
        os.makedirs(os.path.join(self.root, ".backup", backup_op_id),
                    mode=0o700, exist_ok=False)
        try:
            # The snapshot runs under the exclusive lease: the exclusive
            # variant skips the shared maintenance lock (which would
            # self-deadlock here).
            stats = self.helper.snapshot(
                self.root, _snapshot_path(self.root, backup_op_id),
                phase="publishing", exclusive=True)
        except Exception:
            _remove_backup_staging(self.root, backup_op_id, self.euid)
            raise
        secure = backup_spec._probe_medium(output, backup_op_id)
        if not secure:
            _remove_backup_staging(self.root, backup_op_id, self.euid)
            raise OperationBlocked(
                "insecure_destination", phase="publishing",
                remediation="--backup-current requires a destination that "
                            "proves owner-only file permissions; choose "
                            "another path or use --discard-current")
        snapshot_path = _snapshot_path(self.root, backup_op_id)
        try:
            st = os.lstat(snapshot_path)
        except OSError as error:
            _remove_backup_staging(self.root, backup_op_id, self.euid)
            raise OperationFailed(
                "staging_write_failed", phase="publishing", retryable=True,
                cause={"error": error.strerror})
        import hashlib
        sha = hashlib.sha256()
        with open(snapshot_path, "rb") as stream:
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                sha.update(chunk)
        manifest = build_manifest(
            stats, _backup_id(), _now_iso(self.now), st.st_size,
            sha.hexdigest(), insecure_destination=False,
            program_version=self.program_version)
        _write_json_atomic(
            _backup_manifest_path(self.root, backup_op_id), manifest,
            self.euid)
        temp = backup_spec._build_temp_zip(output, backup_op_id, manifest)
        backup_spec._publish(temp, output)
        backup_spec._self_check_final(output, manifest)
        _remove_backup_staging(self.root, backup_op_id, self.euid)
        # The published container is verified independently.
        verify_backup(output, helper=self.helper)
        return manifest

    def _step_publishing(self, record):
        operation_id = record["operation_id"]
        staged_identity = _load_staged_identity(
            self.root, operation_id, self.euid)
        staged_manifest = _load_staged_manifest(
            self.root, operation_id, self.euid)
        if staged_identity is None or staged_manifest is None:
            raise OperationBlocked(
                "staging_identity_missing", phase="publishing",
                remediation="restore or re-create the staging directory for "
                            "this operation, then retry")
        expected_epoch = record["parameters"]["expect_store_epoch"]
        backup_current = record["parameters"]["backup_current"]

        def replacement(lease):
            parameters = record["parameters"]
            mode = _restore_mode(parameters)
            if mode == "healthy":
                # -- healthy path (unchanged #56): the epoch CAS closes again
                # under the exclusive lease, before any fact mutation.
                self._healthy_replacement(
                    lease, record, staged_identity, expected_epoch,
                    backup_current)
            else:
                # -- #57 paths ---------------------------------------------------
                marker_exists = _read_json(
                    _published_marker_path(self.root, operation_id),
                    self.euid) is not None
                present = os.path.lexists(os.path.join(self.root, FACTS_DB))
                disk_epoch = None
                if present:
                    try:
                        disk_epoch = probe_current_epoch(self.root, self.euid)
                    except OperationBlocked:
                        # Still unreadable (corrupt / clock-invalid): the
                        # fingerprint gate below decides.
                        disk_epoch = None
                if disk_epoch == staged_identity["store_epoch"]:
                    # A previous attempt already published (crash between the
                    # atomic replace and the record write): re-persist the
                    # marker and continue; never regenerate identity.
                    pass
                elif marker_exists:
                    raise MaintenanceError("publish_state_inconsistent")
                elif disk_epoch is not None:
                    # A readable store with a different epoch appeared: the
                    # scene changed and this path's fingerprint/no-store
                    # expectation no longer holds.
                    raise MaintenanceError("epoch_mismatch")
                elif mode == "no-store":
                    if present:
                        # A store appeared (or an unreadable file now exists):
                        # --expect-no-store requires absence.
                        raise MaintenanceError("store_present_unexpected")
                    self._verify_staged_identity(operation_id, staged_identity)
                    replace_fact_database(self.root, _staging_db_path(
                        self.root, operation_id), lease)
                else:
                    # Unreadable path: the store must still be present and
                    # unreadable. Quarantine FIRST (fingerprint check + as-is
                    # copy + verify + fsync), then replace; any failure aborts
                    # with the current bytes untouched.
                    if not present:
                        raise MaintenanceError("store_missing")
                    self._verify_staged_identity(operation_id, staged_identity)
                    self._quarantine_and_replace(
                        lease, operation_id, staged_identity, parameters)
            _write_json_atomic(
                _published_marker_path(self.root, operation_id),
                {"store_epoch": staged_identity["store_epoch"],
                 "history_id": staged_identity["history_id"]}, self.euid)
            # Prime the published store under the lease: on this host a WAL
            # database without sidecars cannot be opened read-only, and the
            # daemon's reopen is exactly such an open.
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
                operation_id, **maintenance_kwargs,
                expect_unreadable=(_restore_mode(
                    record["parameters"]) == "unreadable"))
        except MaintenanceError as error:
            code = error.code
            if code == "epoch_mismatch":
                raise OperationBlocked(
                    "store_epoch_mismatch", phase="publishing",
                    remediation="re-run restore with the current store epoch",
                    cause={"expected": expected_epoch})
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
            if code == "store_present_unexpected":
                raise OperationBlocked(
                    "store_present_unexpected", phase="publishing",
                    remediation="a store now exists where none was expected; "
                                "inspect the current store before retrying",
                    cause=None)
            if code == "store_missing":
                raise OperationBlocked(
                    "store_missing", phase="publishing",
                    remediation="the current store is missing; the "
                                "unreadable-current path cannot quarantine "
                                "it. Use --expect-no-store for a missing "
                                "store",
                    cause=None)
            if code == "backup_current_failed":
                raise OperationBlocked(
                    "backup_current_failed", phase="publishing",
                    remediation="the --backup-current snapshot failed; the "
                                "live store is unchanged. Inspect the "
                                "destination and retry",
                    cause=None)
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
        # The daemon reopen is the authoritative "rebuild durably queued"
        # signal: `state` is "serving" (no rebuild needed) or "catching_up"
        # (rebuild queued, not waited on) and `serving_ready` reports the
        # serving availability separately. Persist it durably so the result
        # reports fact_operation_succeeded and serving_ready separately
        # (spec #43 "结果分别报告 fact_operation_succeeded 和 serving_ready";
        # #68/#84 own waiting for a finished generation).
        staged_manifest = _load_staged_manifest(
            self.root, operation_id, self.euid)
        if staged_manifest is not None:
            staged_manifest["reopen"] = {
                "store_epoch": recovery.get("store_epoch"),
                "state": recovery.get("state"),
                "serving_ready": recovery.get("serving_ready"),
            }
            _write_json_atomic(
                _staging_manifest_path(self.root, operation_id),
                staged_manifest, self.euid)
        return {"advance": True}

    def _healthy_replacement(self, lease, record, staged_identity,
                             expected_epoch, backup_current):
        """The unchanged #56 healthy-current replacement inside the lease:
        epoch CAS, staged identity check, --backup-current, atomic replace."""
        operation_id = record["operation_id"]
        if os.path.lexists(os.path.join(self.root, FACTS_DB)):
            live = read_identity_under_exclusive(self.root)
            disk_epoch = live["store_epoch"]
        else:
            disk_epoch = None
        marker_exists = _read_json(
            _published_marker_path(self.root, operation_id),
            self.euid) is not None
        if disk_epoch == staged_identity["store_epoch"]:
            # A previous attempt already published (crash between the atomic
            # replace and the record write): re-persist the marker and
            # continue; never regenerate identity.
            return
        if marker_exists:
            raise MaintenanceError("publish_state_inconsistent")
        if disk_epoch is None:
            raise MaintenanceError("epoch_mismatch")
        if disk_epoch != expected_epoch:
            raise MaintenanceError("epoch_mismatch")
        self._verify_staged_identity(operation_id, staged_identity)
        if backup_current is not None:
            # --backup-current runs AFTER quiesce and BEFORE the replace;
            # any failure aborts here with the live store unchanged.
            try:
                self._backup_current(operation_id, backup_current)
            except OperationBlocked:
                raise
            except OperationFailed:
                raise
            except BackupError as error:
                raise MaintenanceError("backup_current_failed") from error
        replace_fact_database(self.root, _staging_db_path(
            self.root, operation_id), lease)

    def _verify_staged_identity(self, operation_id, staged_identity):
        """The staged store must still be the prepared identity before the
        replace."""
        try:
            identity, _empty = self.helper.verify(
                _staging_store_dir(self.root, operation_id))
        except _HelperFailed:
            raise MaintenanceError("staging_invalid")
        if identity != staged_identity:
            raise MaintenanceError("staging_invalid")

    def _quarantine_and_replace(self, lease, operation_id, staged_identity,
                                parameters):
        """The #57 unreadable-current replacement inside the exclusive lease:
        open the as-is DB/WAL/SHM after quiesce, compute the fingerprint from
        THOSE opened descriptors, verify it against
        --expect-current-fingerprint, copy the bytes into
        quarantine/<operation_id>/ (verified + fsynced), and only then
        replace. Any fingerprint mismatch or quarantine failure raises before
        the replace; the current bytes stay untouched and no partial
        quarantine is left looking successful."""
        fds = None
        try:
            fds = open_current_files(self.root, self.euid)
            publish_quarantine(
                self.root, operation_id, fds,
                parameters["expect_current_fingerprint"], self.euid,
                now=self.now, disposition="unreadable")
        finally:
            if fds is not None:
                for fd in fds.values():
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        # Only after the quarantine is verified and durable: replace without
        # the old-store checkpoint. The as-is old bytes (including any WAL/
        # SHM) are preserved in quarantine; the old DB may be corrupt or have
        # an unreadable permission state, so the checkpoint must not run.
        replace_fact_database(self.root, _staging_db_path(
            self.root, operation_id), lease, checkpoint_old_store=False)

    def _step_reopening(self, record):
        operation_id = record["operation_id"]
        staged_identity = _load_staged_identity(
            self.root, operation_id, self.euid)
        if record["cancel_requested"]:
            # Pre-publish compensation (cancel_phase == reopening). The
            # irreversible replacement only ever runs in the publishing
            # phase, so the disk must still hold the complete old store.
            try:
                identity_empty = live_identity(self.helper, self.root)
            except OperationBlocked:
                # The current store is still unreadable (a #57 cancel before
                # publish): we cannot prove the old store is untouched, so the
                # cancel fails closed instead of pretending to reopen an
                # unverifiable state.
                raise OperationBlocked(
                    "cancel_unverifiable", phase="reopening",
                    remediation="the current store is unreadable; the cancel "
                                "cannot verify the old state. Re-run restore "
                                "to completion or purge the operation",
                    cause=None)
            if (identity_empty is not None and staged_identity is not None
                    and identity_empty[0]["store_epoch"]
                    == staged_identity["store_epoch"]):
                raise OperationBlocked(
                    "restore_published_during_cancel", phase="reopening",
                    remediation="the restore had already published when the "
                                "cancel was honored; inspect the store and "
                                "finish cleanup explicitly",
                    cause={"store_epoch": staged_identity["store_epoch"]})
            _remove_staging(self.root, operation_id, self.euid)
            _remove_backup_current_staging(self.root, operation_id, self.euid)
            return {"advance": True}
        if staged_identity is None:
            raise OperationBlocked(
                "staging_identity_missing", phase="reopening",
                remediation="restore or re-create the staging directory for "
                            "this operation, then retry")
        # Success path: the disk must now hold the staged identity.
        try:
            identity_empty = live_identity(self.helper, self.root)
        except OperationBlocked:
            # The freshly published store must be readable; an unreadable
            # post-publish store is a broken publication.
            raise OperationFailed(
                "reopen_unverifiable", phase="reopening", retryable=True,
                cause=None)
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
        staged_identity = _load_staged_identity(
            self.root, operation_id, self.euid)
        staged_manifest = _load_staged_manifest(
            self.root, operation_id, self.euid)
        backup_manifest = (staged_manifest or {}).get("backup_manifest")
        prepared = (staged_manifest or {}).get("prepared")
        backup_stats = (staged_manifest or {}).get("backup_stats") or {}
        removed_bytes = 0
        if record["cancel_requested"]:
            _remove_staging(self.root, operation_id, self.euid)
            _remove_backup_current_staging(self.root, operation_id, self.euid)
            return {"advance": True}
        # The outcome is derived from durable disk state AFTER the sweep, so
        # a crash at any point of cleanup retries into the identical result.
        try:
            identity_empty = live_identity(self.helper, self.root)
        except OperationBlocked:
            identity_empty = None
        if (identity_empty is not None
                and staged_identity is not None
                and identity_empty[0]["store_epoch"]
                == staged_identity["store_epoch"]):
            outcome = "restored"
            if _restore_mode(record["parameters"]) == "unreadable":
                # The old store was unreadable; its identity was never
                # readable, so the old identity is explicitly unknown.
                old_identity = {"store_epoch": None, "history_id": None,
                                "unreadable": True}
            elif _restore_mode(record["parameters"]) == "no-store":
                old_identity = None
            else:
                old_identity = {
                    "store_epoch": record["parameters"]["expect_store_epoch"],
                    "history_id": None,
                }
            new_identity = identity_empty[0]
        else:
            outcome = "not_restored"
            old_identity = identity_empty[0] if identity_empty else None
            new_identity = old_identity
        _remove_backup_current_staging(self.root, operation_id, self.euid)
        root_fd = _open_root_fd(self.root)
        try:
            for name in RESTORE_DERIVED_NAMES:
                removed_bytes += _remove_entry(root_fd, name, self.euid)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
        # serving_ready comes from the daemon reopen recorded in publishing
        # (the authoritative "rebuild durably queued" signal: state
        # catching_up with serving_ready False means queued, not done). The
        # scoring probe is only a fallback when the staged manifest was lost.
        reopen = (staged_manifest or {}).get("reopen") or {}
        if reopen.get("serving_ready") is not None:
            serving_ready = bool(reopen.get("serving_ready"))
            rebuild_queued = reopen.get("state") == "catching_up"
        else:
            serving_ready = None
            rebuild_queued = None
            if self.scoring_socket is not None:
                try:
                    from status_core import probe_daemon
                    serving = probe_daemon(self.scoring_socket)
                    serving_ready = serving.get("state") == "up"
                except Exception:
                    serving_ready = None
        if outcome == "restored":
            fact_operation_succeeded = True
        else:
            fact_operation_succeeded = False
        result = {
            "outcome": outcome,
            "fact_operation_succeeded": fact_operation_succeeded,
            "serving_ready": serving_ready,
            "rebuild_queued": rebuild_queued,
            "old": old_identity,
            "new": new_identity,
            "cleanup_complete": True,
        }
        if backup_manifest is not None:
            result["backup_id"] = backup_manifest["backup_id"]
            result["backup_history_id"] = backup_manifest["history_id"]
            result["backup_store_epoch"] = backup_manifest["store_epoch"]
        if backup_stats:
            result["backup_event_count"] = backup_stats.get("event_count")
            result["backup_hlc_high_water"] = {
                "physical_ms": backup_stats.get("hlc_physical_ms"),
                "logical": backup_stats.get("hlc_logical"),
            }
        if prepared is not None:
            result["previous_store_epoch"] = prepared.get(
                "previous_store_epoch")
        if record["parameters"]["backup_current"] is not None:
            result["backup_current_destination"] = record["parameters"][
                "backup_current"]
        if record["parameters"]["discard_current"]:
            result["discarded_current"] = True
        if _restore_mode(record["parameters"]) == "unreadable":
            # Identity-only quarantine evidence reference; never any content.
            result["quarantine_operation_id"] = operation_id
            result["quarantine_fingerprint"] = record["parameters"][
                "expect_current_fingerprint"]
        if _restore_mode(record["parameters"]) == "no-store":
            result["no_store"] = True
        result["plaintext_sensitive_declaration"] = SENSITIVE_DECLARATION
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
            "restore",
            phases=("preflight", "waiting-for-quiesce", "staging",
                    "publishing", "reopening", "cleanup"),
            irreversible_phase="publishing",
            normalize=self._normalize,
            steps=steps,
            cancel_phase="reopening",
        )


def build_restore_spec(root, **seams):
    """Build the production `restore` operation type for one semantic root."""
    return RestoreSpec(root, **seams).build()


def production_registry(root, **seams):
    """The production restore registry: `restore` only."""
    from operations import OperationRegistry
    registry = OperationRegistry()
    registry.register(build_restore_spec(root, **seams))
    return registry
