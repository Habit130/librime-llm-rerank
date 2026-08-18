#!/usr/bin/env python3
"""The `migrate` production operation type (Habit130/squirrel#58).

`squirrel-semantic-memory migrate` upgrades a supported-old fact store to the
current schema head, under the #53/#54 maintenance seam: a verified safety
snapshot is created BEFORE any migration work (SQLite Online Backup API +
full C++ validation through `fact_store_tool snapshot`), the migration runs
on a staging copy of that snapshot (`fact_store_tool migrate`, one SQLite
transaction per ordered step chain with pre-commit validation), and only a
successfully migrated staging file is published with the atomic
`replace_fact_database` path under the exclusive maintenance lease.

Phase machine (canonical order, spec #43):

    preflight -> waiting-for-quiesce -> staging -> publishing -> reopening

- `publishing` is the irreversible phase: the atomic fact replacement and
  the bounded exclusive quiesce happen inside one publishing step, so the
  persisted phase is an honest boundary (a cancel honored before it can
  never race a replacement; the compensation in `reopening` observes only
  the complete old store).
- Staging (the only expensive fact work) completes before any daemon
  prepare. The staged snapshot is durable and reused across retries, so a
  crash never re-runs the safety snapshot or re-migrates from a torn file.
- An already-current store is a no-op (`already_migrated`): repeated
  migrates never churn identities and never touch the live store.
- A too-new store (`unsupported`), a missing migration step (`missing_step`)
  or an unverifiable store fails closed in preflight with a distinct,
  explicit report; recording stays stopped.
- The live schema disposition is read through the C++ seam
  (`fact_store_tool schema`); Python never re-derives fact semantics.

Fact semantics live in C++ (`fact_store_tool`): Python only moves files and
reads the identity/disposition the C++ seam reports. No output, log or error
ever contains 上文, candidate text or embeddings.
"""

import os

from maintenance import (
    MaintenanceError,
    read_identity_under_exclusive,
    replace_fact_database,
    run_maintenance,
)
from clear_operation import (
    FactStoreHelper,
    _HelperFailed,
    _probe_control_socket,
    _valid_identity_token,
    _write_json_atomic,
)
from operations import (
    OperationBlocked,
    OperationFailed,
    OperationTypeSpec,
)

MIGRATE_DIRNAME = ".migrate"
FACTS_DB = "facts.sqlite3"
SNAPSHOT_FILE = "snapshot.sqlite3"
MIGRATED_FILE = "migrated.sqlite3"
STAGING_MANIFEST = "manifest.json"
PUBLISHED_MARKER = "published.marker"


def _staging_root(root, operation_id):
    return os.path.join(root, MIGRATE_DIRNAME, operation_id)


def _staging_store_dir(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), "store")


def _staging_db_path(root, operation_id):
    return os.path.join(_staging_store_dir(root, operation_id), FACTS_DB)


def _staging_snapshot_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), SNAPSHOT_FILE)


def _staging_migrated_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), MIGRATED_FILE)


class MigrateSpec:
    """Factory for the `migrate` OperationTypeSpec with injectable seams."""

    def __init__(self, root, *, helper=None, control_socket=None,
                 timeout_s=5.0, now=None, sleep=None,
                 control_client_factory=None, euid=None):
        self.root = root
        self.euid = os.geteuid() if euid is None else euid
        self.helper = helper or FactStoreHelper()
        self.control_socket = control_socket
        self.timeout_s = timeout_s
        self.now = now
        self.sleep = sleep
        self.control_client_factory = control_client_factory

    def _normalize(self, parameters):
        if parameters is None:
            return {}
        if not isinstance(parameters, dict):
            raise ValueError("migrate parameters must be an object")
        return {}

    # -- steps --------------------------------------------------------------

    def _live_disposition(self, phase):
        """Read the live store schema disposition through the C++ seam.

        Returns (disposition, schema) where schema carries the durable
        identity. A missing store is `not_created`; a too-new or gap store
        returns its explicit disposition; any other unreadable store fails
        closed (the migrate operation never fabricates a disposition).
        """
        try:
            schema = self.helper.schema(self.root, phase=phase)
        except _HelperFailed as error:
            if error.status == "no_store":
                return "not_created", None
            if error.status == "db_unsupported_version":
                # The C++ seam failed closed on a too-new or gap store; the
                # disposition is derived there, so surface it explicitly
                # instead of a generic unverifiable fault.
                return "unsupported", None
            raise OperationBlocked(
                "fact_store_unverifiable", phase=phase,
                remediation="the fact store failed closed validation; "
                            "inspect and fix it before migrating",
                cause={"fault_code": error.status})
        return schema["disposition"], schema

    def _step_preflight(self, record):
        disposition, schema = self._live_disposition("preflight")
        if disposition in ("unsupported", "missing_step"):
            raise OperationBlocked(
                "schema_unsupported" if disposition == "unsupported"
                else "schema_missing_step",
                phase="preflight",
                remediation=(
                    "this build cannot migrate the store: the schema is "
                    "newer than the program supports (recording stays "
                    "stopped)" if disposition == "unsupported" else
                    "no migration step covers the store's schema version; "
                    "upgrade the build to a version that can migrate it "
                    "(recording stays stopped)"),
                cause={"schema_version": schema["fact_schema_version"] if
                       schema else None})
        if disposition == "not_created":
            raise OperationBlocked(
                "store_missing", phase="preflight",
                remediation="no facts database exists; there is nothing to "
                            "migrate (create one with normal use or a clear "
                            "operation)",
                cause=None)
        if disposition == "current":
            # Already at the head: a no-op success, never a churn of
            # identities and never a write.
            return {"advance": True}
        # needs_migration: record the epoch CAS for the publish re-check.
        return {"advance": True}

    def _step_waiting_for_quiesce(self, record):
        disposition, _schema = self._live_disposition("waiting-for-quiesce")
        if disposition == "current":
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
        disposition, _schema = self._live_disposition("staging")
        if disposition == "current":
            return {"advance": True}
        staging_root = _staging_root(self.root, operation_id)
        if os.path.lexists(staging_root):
            # A previous attempt left a durable staging artifact: reuse it
            # only when it is complete. `migrate` is idempotent and returns
            # no_migration for a file already at the current head (the same
            # C++ step table the operation runs against), so it doubles as
            # the re-validation. Anything else is torn and is rebuilt.
            migrated = _staging_migrated_path(self.root, operation_id)
            if os.path.isfile(migrated):
                try:
                    result = self.helper.migrate(migrated, phase="staging")
                    if result.get("status") == "no_migration":
                        return {"advance": True}
                except (_HelperFailed, OperationFailed):
                    pass
            self._remove_staging(operation_id)
        import shutil
        os.makedirs(staging_root, mode=0o700, exist_ok=False)
        # 1. Safety snapshot BEFORE any migration work (SCN-58-1): a
        #    verified consistent snapshot of the live store. Snapshot
        #    failure -> no migration, live DB unchanged.
        snapshot = _staging_snapshot_path(self.root, operation_id)
        try:
            stats = self.helper.snapshot(self.root, snapshot,
                                         phase="staging")
        except _HelperFailed as error:
            self._remove_staging(operation_id)
            raise OperationBlocked(
                "safety_snapshot_failed", phase="staging",
                remediation="the safety snapshot could not be created and "
                            "verified; the live store is unchanged. Fix the "
                            "cause and retry migrate",
                cause={"fault_code": error.status})
        except OperationFailed:
            self._remove_staging(operation_id)
            raise
        # 2. Migrate the STAGING copy (never the live root): one SQLite
        #    transaction per ordered step chain with pre-commit validation.
        #    Any failure leaves the staging file unchanged; the live DB is
        #    never touched.
        migrated = _staging_migrated_path(self.root, operation_id)
        os.replace(snapshot, migrated)
        try:
            result = self.helper.migrate(migrated, phase="staging")
        except (_HelperFailed, OperationFailed):
            self._remove_staging(operation_id)
            raise
        manifest = {
            "snapshot_stats": stats,
            "migrate_result": result,
        }
        _write_json_atomic(os.path.join(staging_root, STAGING_MANIFEST),
                           manifest, self.euid)
        import stat
        st = os.lstat(migrated)
        return {"progress": {"bytes": st.st_size, "chunks": 1},
                "advance": True}

    def _step_publishing(self, record):
        operation_id = record["operation_id"]
        staged = _staging_migrated_path(self.root, operation_id)
        if not os.path.isfile(staged):
            disposition, _schema = self._live_disposition("publishing")
            if disposition == "current":
                return {"advance": True}
            raise OperationBlocked(
                "staging_artifact_missing", phase="publishing",
                remediation="the staged migration artifact was lost; "
                            "re-run migrate to rebuild it",
                cause=None)
        # A store that became current between phases (another migrate won,
        # or the store was never old) is a no-op: nothing to publish, no
        # exclusive lease needed. The phase machine still runs to completion
        # so the outcome is recorded uniformly.
        disposition, _schema = self._live_disposition("publishing")
        if disposition == "current":
            return {"advance": True}

        def replacement(lease):
            # Re-verify the live disposition under the exclusive lease,
            # before any fact mutation. The epoch/version gate closes again
            # here: a store that moved to current is a no-op, a store that
            # changed identity fails closed.
            live = read_identity_under_exclusive(self.root)
            marker_exists = os.path.exists(os.path.join(
                _staging_root(self.root, operation_id), PUBLISHED_MARKER))
            try:
                disposition, _schema = self._live_disposition("publishing")
            except OperationBlocked:
                raise MaintenanceError("epoch_unverifiable")
            if disposition == "current" and marker_exists:
                # A previous attempt already published; the store is at the
                # head. Re-persist the marker and continue.
                pass
            elif disposition == "current":
                raise MaintenanceError("epoch_mismatch")
            elif disposition != "needs_migration":
                raise MaintenanceError("epoch_mismatch")
            else:
                # The staged file must still be the migrated head store and
                # carry the same epoch/history the preflight saw; verify via
                # the C++ seam (Python never interprets fact rows). `migrate`
                # is idempotent: a file already at the head returns
                # no_migration, and the reported identity is the durable one.
                try:
                    result = self.helper.migrate(staged, phase="publishing")
                except (_HelperFailed, OperationFailed):
                    raise MaintenanceError("staging_invalid")
                if result.get("status") not in ("migrated", "no_migration"):
                    raise MaintenanceError("staging_invalid")
                if result.get("store_epoch") != live["store_epoch"]:
                    raise MaintenanceError("epoch_mismatch")
                replace_fact_database(self.root, staged, lease)
            # Prime the published store under the lease: on this host a WAL
            # database without sidecars cannot be opened read-only, and the
            # daemon's reopen is exactly such an open. A short read-write
            # checkpoint materializes the sidecars before the lease is
            # released (mirrors the clear operation's publish priming).
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
                raise MaintenanceError("publish_prime_failed") from error
            _write_json_atomic(os.path.join(
                _staging_root(self.root, operation_id), PUBLISHED_MARKER),
                {"store_epoch": live["store_epoch"]}, self.euid)

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
                    remediation="the live store changed during the "
                                "operation; re-run migrate",
                    cause=None)
            if code == "staging_invalid":
                raise OperationBlocked(
                    "staging_invalid", phase="publishing",
                    remediation="the staged migration artifact no longer "
                                "validates; re-run migrate to rebuild it",
                    cause=None)
            if code == "epoch_unverifiable":
                raise OperationBlocked(
                    "fact_store_unverifiable", phase="publishing",
                    remediation="the fact store failed closed validation; "
                                "inspect and fix it before migrating",
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
        return {"advance": True}

    def _step_reopening(self, record):
        operation_id = record["operation_id"]
        if record["cancel_requested"]:
            # Pre-publish compensation: the irreversible replacement only
            # runs in publishing, so the disk still holds the complete old
            # store. Nothing to restore; remove the staging artifact.
            self._remove_staging(operation_id)
            return {"advance": True}
        disposition, schema = self._live_disposition("reopening")
        if disposition != "current":
            raise OperationBlocked(
                "migrate_incomplete", phase="reopening",
                remediation="the store did not reach the current schema; "
                            "re-run migrate",
                cause={"disposition": disposition})
        result = {
            "outcome": "migrated",
            "fact_schema_version": schema["fact_schema_version"],
            "event_format_version": schema["event_format_version"],
            "history_id": schema["history_id"],
            "store_epoch": schema["store_epoch"],
        }
        return {"advance": True, "result": result}

    def _remove_staging(self, operation_id):
        """Idempotent, symlink-safe removal of this operation's staging
        root, anchored to the semantic root fd (a swapped symlink is
        unlinked, never followed)."""
        from clear_operation import _remove_entry, _open_root_fd
        root_fd = None
        try:
            root_fd = _open_root_fd(self.root)
        except OperationFailed:
            # The root became unreadable; a later retry cleans it. The
            # staging directory must never be swept through an unverified
            # root.
            return
        try:
            try:
                os.lstat(MIGRATE_DIRNAME, dir_fd=root_fd)
            except FileNotFoundError:
                return
            except OSError:
                return
            try:
                dfd = os.open(MIGRATE_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                              dir_fd=root_fd)
            except OSError:
                return
            try:
                try:
                    os.lstat(operation_id, dir_fd=dfd)
                except FileNotFoundError:
                    return
                _remove_entry(dfd, operation_id, self.euid)
            finally:
                os.close(dfd)
        finally:
            if root_fd is not None:
                os.close(root_fd)

    def build(self):
        steps = {
            "preflight": self._step_preflight,
            "waiting-for-quiesce": self._step_waiting_for_quiesce,
            "staging": self._step_staging,
            "publishing": self._step_publishing,
            "reopening": self._step_reopening,
        }
        return OperationTypeSpec(
            "migrate",
            phases=("preflight", "waiting-for-quiesce", "staging",
                    "publishing", "reopening"),
            irreversible_phase="publishing",
            normalize=self._normalize,
            steps=steps,
            cancel_phase="reopening",
        )


def build_migrate_spec(root, **seams):
    """Build the production `migrate` operation type for one semantic root."""
    return MigrateSpec(root, **seams).build()


def production_registry(root, **seams):
    """The production migrate registry: `migrate` only."""
    from operations import OperationRegistry
    registry = OperationRegistry()
    registry.register(build_migrate_spec(root, **seams))
    return registry
