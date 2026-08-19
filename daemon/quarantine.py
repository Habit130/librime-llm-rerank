#!/usr/bin/env python3
"""Quarantine management (Habit130/squirrel#57).

Layout: `quarantine/<operation_id>/` under the app-controlled semantic-memory
root, owner-only (directory 0700, files 0600 — the same rules as facts). It
holds the as-is DB/WAL/SHM bytes of a current store that was unreadable at
restore time, plus an identity-only `metadata.json`. The daemon never scans,
repairs, merges or auto-restores quarantine; `clear` deletes the whole
app-controlled quarantine directory; `quarantine purge <operation_id>
<content_fingerprint>` deletes exactly one operation's copy and only when
BOTH identifiers match exactly.

Fingerprint definition (documented exactly; tests and manual probes compute
the same value):

    fingerprint = sha256_hex(
        u64be(len(db))  || db  ||
        u64be(len(wal)) || wal ||
        u64be(len(shm)) || shm)

where each member contributes its as-is bytes in the fixed order DB, WAL,
SHM and an absent sidecar contributes a zero length (so its absence is still
covered by the fingerprint). The hash is computed from the SAME opened file
descriptors that are copied, never from a re-stat of a path the user might
have replaced between fingerprinting and copying (spec #57 seam 3).

Restore publishes a quarantine only inside the exclusive maintenance lease,
after quiesce, and only after the fingerprint check passes. Any copy/verify/
fsync failure removes the partial operation directory (a partial quarantine
must never look successful) and aborts before the replace. No output or
metadata ever contains 上文, candidate text or embeddings.
"""

import hashlib
import os
import stat

from backup_operation import _now_iso
from clear_operation import (
    _HelperFailed,
    _open_root_fd,
    _read_json,
    _remove_entry,
    _valid_identity_token,
    _write_json_atomic,
)
from operations import OperationBlocked, OperationFailed

QUARANTINE_DIRNAME = "quarantine"
FACTS_DB = "facts.sqlite3"
QUARANTINE_MEMBERS = ("facts.sqlite3", "facts.sqlite3-wal",
                      "facts.sqlite3-shm")
FINGERPRINT_ALGORITHM = "sha256"
QUARANTINE_VERSION = 1
METADATA_FILE = "metadata.json"
_COPY_CHUNK = 1 << 20


def quarantine_root(root):
    return os.path.join(root, QUARANTINE_DIRNAME)


def _operation_dir(root, operation_id):
    return os.path.join(quarantine_root(root), operation_id)


def _metadata_path(root, operation_id):
    return os.path.join(_operation_dir(root, operation_id), METADATA_FILE)


def fingerprint_bytes(member_bytes):
    """The documented content fingerprint over the as-is DB+WAL+SHM bytes.

    `member_bytes` maps member name -> bytes (absent sidecars omitted). The
    canonical concatenation is length-prefixed so different size boundaries
    can never collide.
    """
    digest = hashlib.sha256()
    for member in QUARANTINE_MEMBERS:
        payload = member_bytes.get(member, b"")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _source_hashes(fds):
    """Per-member (size, sha256) plus the combined fingerprint, read from
    the opened fds (which are consumed to EOF; callers lseek back before
    copying). Absent sidecars are recorded as absent with an empty hash. The
    combined fingerprint is exactly `fingerprint_bytes` (length-prefixed
    concatenation of the as-is bytes)."""
    per_member = {}
    digest = hashlib.sha256()
    for member in QUARANTINE_MEMBERS:
        fd = fds.get(member)
        if fd is None:
            digest.update((0).to_bytes(8, "big"))
            per_member[member] = {"present": False, "size": 0, "sha256": ""}
            continue
        st = os.fstat(fd)
        digest.update(st.st_size.to_bytes(8, "big"))
        member_digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, _COPY_CHUNK)
            if not chunk:
                break
            member_digest.update(chunk)
            digest.update(chunk)
        per_member[member] = {"present": True, "size": st.st_size,
                              "sha256": member_digest.hexdigest()}
    return {"fingerprint": digest.hexdigest(), "members": per_member}


def open_current_files(root, euid):
    """Open the current DB/WAL/SHM with O_NOFOLLOW (under the exclusive
    lease, after quiesce). Returns {member: fd}; an absent sidecar is not in
    the dict. Any present member must be a regular file owned by euid — a
    symlink or foreign-owned file cannot be preserved safely and fails
    closed. A missing facts.sqlite3 raises store_missing (that is the
    --expect-no-store territory, never an unreadable quarantine)."""
    root_fd = _open_root_fd(root)
    fds = {}
    try:
        for member in QUARANTINE_MEMBERS:
            try:
                fd = os.open(member, os.O_RDONLY | os.O_NOFOLLOW,
                             dir_fd=root_fd)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise OperationBlocked(
                    "quarantine_open_failed", phase="publishing",
                    remediation="the current store files could not be opened "
                                "for quarantine; retry when the files are "
                                "accessible",
                    cause={"member": member, "error": error.strerror})
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid != euid:
                    raise OperationBlocked(
                        "quarantine_open_refused", phase="publishing",
                        remediation="the current store file is not an "
                                    "owner-owned regular file; it cannot be "
                                    "quarantined safely",
                        cause={"member": member})
            except OperationBlocked:
                os.close(fd)
                raise
            fds[member] = fd
    finally:
        os.close(root_fd)
    if "facts.sqlite3" not in fds:
        raise OperationBlocked(
            "store_missing", phase="publishing",
            remediation="no facts database exists; the unreadable-current "
                        "restore cannot quarantine a missing store "
                        "(--expect-no-store is the missing-store path)",
            cause=None)
    return fds


def _verify_quarantine_dir(root_fd, euid, phase):
    """Verify the `quarantine` directory under the root is a real,
    owner-only 0700 directory (never a symlink, never foreign-owned)."""
    st = os.lstat(QUARANTINE_DIRNAME, dir_fd=root_fd)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise OperationBlocked(
            "quarantine_unsafe", phase=phase,
            remediation="the quarantine directory is not a real directory; "
                        "inspect before using quarantine",
            cause={"path": QUARANTINE_DIRNAME})
    if st.st_uid != euid or stat.S_IMODE(st.st_mode) != 0o700:
        raise OperationBlocked(
            "quarantine_unsafe", phase=phase,
            remediation="the quarantine directory is not owner-only 0700; "
                        "inspect before using quarantine",
            cause={"path": QUARANTINE_DIRNAME})


def _ensure_quarantine_dir(root_fd, euid):
    """Create (or verify) the owner-only `quarantine` directory under the
    root. A symlink or foreign-owned entry is refused."""
    try:
        _verify_quarantine_dir(root_fd, euid, phase="publishing")
        return
    except FileNotFoundError:
        pass
    os.mkdir(QUARANTINE_DIRNAME, 0o700, dir_fd=root_fd)
    os.fsync(root_fd)


def publish_quarantine(root, operation_id, fds, expected_fingerprint, euid,
                       now=None, disposition="unreadable"):
    """Copy the as-is current files into `quarantine/<operation_id>/`,
    verify byte-identity against the opened fds, fsync files and
    directories, and write the identity-only metadata.

    The fingerprint is re-verified from the SAME opened fds before anything
    is written; a mismatch raises `fingerprint_mismatch` with no quarantine
    and no replace. Any copy/verify/fsync failure removes the partial
    operation directory (never a successful-looking quarantine) and raises
    `quarantine_failed`. Returns the durable metadata dict.
    """
    if not _valid_identity_token(operation_id):
        raise OperationBlocked(
            "invalid_operation_id", phase="publishing",
            remediation="the operation id must be a safe identifier",
            cause=None)
    source = _source_hashes(fds)
    if source["fingerprint"] != expected_fingerprint:
        raise OperationBlocked(
            "fingerprint_mismatch", phase="publishing",
            remediation="the current store bytes do not match "
                        "--expect-current-fingerprint; re-run restore with "
                        "the current fingerprint",
            cause={"expected": expected_fingerprint,
                   "actual": source["fingerprint"]})
    root_fd = _open_root_fd(root)
    try:
        _ensure_quarantine_dir(root_fd, euid)
        try:
            qfd = os.open(QUARANTINE_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                          dir_fd=root_fd)
        except OSError as error:
            raise OperationBlocked(
                "quarantine_open_failed", phase="publishing",
                remediation="the quarantine directory could not be opened",
                cause={"error": error.strerror})
        try:
            # A retry of the same operation re-publishes under the exclusive
            # lease; the previous attempt for THIS operation is rewritten
            # only after the fingerprint check above passed, so an old
            # complete copy of the same bytes is equivalent.
            try:
                os.lstat(operation_id, dir_fd=qfd)
                _remove_entry(qfd, operation_id, euid)
            except FileNotFoundError:
                pass
            os.mkdir(operation_id, 0o700, dir_fd=qfd)
            os.fsync(qfd)
            op_fd = os.open(operation_id, os.O_RDONLY | os.O_NOFOLLOW,
                            dir_fd=qfd)
            try:
                for member in QUARANTINE_MEMBERS:
                    fd = fds.get(member)
                    if fd is None:
                        continue
                    os.lseek(fd, 0, os.SEEK_SET)
                    target = os.open(member, os.O_WRONLY | os.O_CREAT
                                     | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                                     dir_fd=op_fd)
                    try:
                        os.fchmod(target, 0o600)
                        while True:
                            chunk = os.read(fd, _COPY_CHUNK)
                            if not chunk:
                                break
                            view = memoryview(chunk)
                            while view:
                                written = os.write(target, view)
                                if written <= 0:
                                    raise OSError("short write")
                                view = view[written:]
                        os.fsync(target)
                    finally:
                        os.close(target)
                # Byte-identity verification of the copies: size + sha256
                # against the source hashes read from the opened fds.
                for member, record in source["members"].items():
                    if not record["present"]:
                        continue
                    target = os.open(member, os.O_RDONLY | os.O_NOFOLLOW,
                                     dir_fd=op_fd)
                    try:
                        st = os.fstat(target)
                        member_digest = hashlib.sha256()
                        while True:
                            chunk = os.read(target, _COPY_CHUNK)
                            if not chunk:
                                break
                            member_digest.update(chunk)
                        if (st.st_size != record["size"]
                                or member_digest.hexdigest()
                                != record["sha256"]):
                            raise OperationBlocked(
                                "quarantine_failed", phase="publishing",
                                remediation="the quarantine copy failed "
                                            "byte-identity verification; the "
                                            "restore did not replace the "
                                            "store",
                                cause={"member": member})
                    finally:
                        os.close(target)
                metadata = {
                    "quarantine_version": QUARANTINE_VERSION,
                    "operation_id": operation_id,
                    "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
                    "fingerprint": source["fingerprint"],
                    "disposition": disposition,
                    "created_at_utc": _now_iso(now),
                    "members": {
                        member: {"present": record["present"],
                                 "size": record["size"],
                                 "sha256": record["sha256"]}
                        for member, record in source["members"].items()},
                }
                _write_json_atomic(
                    os.path.join(_operation_dir(root, operation_id),
                                 METADATA_FILE),
                    metadata, euid)
                os.fsync(op_fd)
                return metadata
            finally:
                os.close(op_fd)
        finally:
            os.close(qfd)
        os.fsync(root_fd)
    except OperationBlocked:
        # A failed publish must never leave a partial quarantine that looks
        # successful. Removal is best-effort and owner-anchored.
        _remove_partial_quarantine(root_fd, operation_id, euid)
        raise
    except (OSError, OperationFailed) as error:
        _remove_partial_quarantine(root_fd, operation_id, euid)
        raise OperationBlocked(
            "quarantine_failed", phase="publishing",
            remediation="the quarantine copy failed; the restore did not "
                        "replace the store",
            cause={"error": getattr(error, "strerror", None)
                   or getattr(error, "code", None) or type(error).__name__})
    finally:
        os.close(root_fd)


def _remove_partial_quarantine(root_fd, operation_id, euid):
    """Best-effort, owner-anchored removal of one operation's quarantine
    directory after a failed publish."""
    try:
        dfd = os.open(QUARANTINE_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                      dir_fd=root_fd)
        try:
            _remove_entry(dfd, operation_id, euid)
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def list_quarantine(root, euid):
    """Identity-only listing of quarantined stores. Returns a list of dicts
    with operation_id, fingerprint, created_at_utc, disposition and member
    sizes — never any file content. A missing root or a missing quarantine
    directory is an empty list. An unsafe (foreign-owned, symlinked,
    non-directory) quarantine entry fails closed."""
    try:
        root_fd = _open_root_fd(root)
    except OperationBlocked:
        raise
    except OperationFailed as error:
        if error.code == "root_unavailable":
            # A machine with no semantic root has no quarantine.
            return []
        raise OperationBlocked(
            "quarantine_unavailable", phase="cli",
            remediation="the semantic memory root is unavailable",
            cause={"error": error.code})
    except OSError as error:
        raise OperationBlocked(
            "quarantine_unavailable", phase="cli",
            remediation="the semantic memory root is unavailable",
            cause={"error": error.strerror})
    try:
        try:
            _verify_quarantine_dir(root_fd, euid, phase="cli")
        except FileNotFoundError:
            return []
        qfd = os.open(QUARANTINE_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                      dir_fd=root_fd)
        entries = []
        try:
            for entry in os.scandir(qfd):
                entry_stat = entry.stat(follow_symlinks=False)
                if entry_stat.st_uid != euid:
                    raise OperationBlocked(
                        "quarantine_unsafe", phase="cli",
                        remediation="a quarantine entry is not owned by the "
                                    "semantic memory owner; inspect before "
                                    "using quarantine",
                        cause={"path": entry.name})
                if entry.is_symlink() or not entry.is_dir(
                        follow_symlinks=False):
                    raise OperationBlocked(
                        "quarantine_unsafe", phase="cli",
                        remediation="a quarantine entry is not a real "
                                    "directory; inspect before using "
                                    "quarantine",
                        cause={"path": entry.name})
                metadata = _read_json(
                    os.path.join(_operation_dir(root, entry.name),
                                 METADATA_FILE), euid)
                if not isinstance(metadata, dict):
                    entries.append({
                        "operation_id": entry.name,
                        "valid": False,
                        "fingerprint": None,
                        "created_at_utc": None,
                        "disposition": None,
                        "members": {},
                        "total_bytes": None,
                    })
                    continue
                members = metadata.get("members") or {}
                total = None
                sizes = {}
                if isinstance(members, dict):
                    total = 0
                    for member, record in members.items():
                        if isinstance(record, dict) and isinstance(
                                record.get("size"), int):
                            sizes[member] = record["size"]
                            total += record["size"]
                entries.append({
                    "operation_id": entry.name,
                    "valid": True,
                    "fingerprint": metadata.get("fingerprint"),
                    "created_at_utc": metadata.get("created_at_utc"),
                    "disposition": metadata.get("disposition"),
                    "members": sizes,
                    "total_bytes": total,
                })
        finally:
            os.close(qfd)
        entries.sort(key=lambda item: item["operation_id"])
        return entries
    finally:
        os.close(root_fd)


def purge_quarantine(root, operation_id, content_fingerprint, euid):
    """Delete `quarantine/<operation_id>/` only when the recorded content
    fingerprint exactly equals `content_fingerprint`. A missing operation
    raises quarantine_not_found; any fingerprint mismatch refuses the delete
    with fingerprint_mismatch and leaves the copy untouched. Returns the
    number of bytes removed."""
    if not _valid_identity_token(operation_id):
        raise OperationBlocked(
            "invalid_operation_id", phase="cli",
            remediation="the operation id must be a safe identifier",
            cause=None)
    root_fd = _open_root_fd(root)
    try:
        try:
            _verify_quarantine_dir(root_fd, euid, phase="cli")
        except FileNotFoundError:
            raise OperationBlocked(
                "quarantine_not_found", phase="cli",
                remediation="no quarantined store exists under this "
                            "operation id",
                cause={"operation_id": operation_id})
        qfd = os.open(QUARANTINE_DIRNAME, os.O_RDONLY | os.O_NOFOLLOW,
                      dir_fd=root_fd)
        try:
            try:
                os.lstat(operation_id, dir_fd=qfd)
            except FileNotFoundError:
                raise OperationBlocked(
                    "quarantine_not_found", phase="cli",
                    remediation="no quarantined store exists under this "
                                "operation id",
                    cause={"operation_id": operation_id})
            metadata = _read_json(
                os.path.join(_operation_dir(root, operation_id),
                             METADATA_FILE), euid)
            if (not isinstance(metadata, dict)
                    or metadata.get("fingerprint") != content_fingerprint):
                raise OperationBlocked(
                    "fingerprint_mismatch", phase="cli",
                    remediation="the content fingerprint does not match the "
                                "quarantined store; nothing was deleted. "
                                "Use `quarantine list` to read the exact "
                                "fingerprint",
                    cause={"operation_id": operation_id})
            removed = _remove_entry(qfd, operation_id, euid)
            os.fsync(qfd)
            return removed
        finally:
            os.close(qfd)
    finally:
        os.close(root_fd)


def probe_current_epoch(root, euid):
    """Non-mutating read of the current store's store_epoch meta value.

    Used ONLY inside the #57 publishing closure (under the exclusive lease,
    after quiesce) to detect an already-published restore: it returns the
    epoch when the store is readable, None when missing, and raises
    `store_unreadable` when the store cannot be read. This is a minimal
    single-meta-key read for crash recovery — NOT a classification and NOT a
    second fact-semantics stack; the C++ seam (`classify_current_store`)
    remains the authority for what "unreadable" means.

    The read uses sqlite's `immutable=1` read-only URI, which never creates,
    truncates or mutates the WAL/SHM sidecars; any other open of an
    unreadable WAL store would rewrite those sidecars and change the as-is
    bytes the operator's fingerprint covers. Under the exclusive lease no
    concurrent writer exists, so the immutable assumption holds.
    """
    facts_path = os.path.join(root, FACTS_DB)
    if not os.path.lexists(facts_path):
        return None
    import sqlite3
    try:
        connection = sqlite3.connect(
            "file:%s?immutable=1" % facts_path, uri=True, timeout=0)
        try:
            row = connection.execute(
                "SELECT value FROM meta WHERE key='store_epoch';").fetchone()
            return row[0] if row and row[0] else None
        finally:
            connection.close()
    except sqlite3.Error:
        raise OperationBlocked(
            "store_unreadable", phase="publishing",
            remediation="the current store cannot be read as SQLite; it is "
                        "the unreadable-current scene this path quarantines",
            cause=None)


def classify_current_store(root, helper, euid):
    """Classify the current store for the #57 restore paths.

    Returns ("missing", None) when the facts path is absent, ("readable",
    disposition) when the store is readable through the C++ seam (healthy,
    supported-old needs-migration, or too-new — all openable), and
    ("unreadable", fault_code) when the store is present but the C++ seam
    cannot read it (corrupt header, clock-invalid meta, open/permission
    failure).

    The classification runs the C++ `schema` seam on a THROWAWAY COPY of the
    main database file: the C++ seam is the single fact-semantics authority
    (never a second Python SQLite stack), and opening an unreadable WAL
    store with sqlite would rewrite its WAL/SHM sidecars and change the
    as-is bytes the operator's fingerprint covers. A copy is never the live
    store, so the fingerprint stays stable.
    """
    facts_path = os.path.join(root, FACTS_DB)
    if not os.path.lexists(facts_path):
        return ("missing", None)
    root_fd = None
    db_fd = None
    try:
        try:
            root_fd = _open_root_fd(root)
            db_fd = os.open(FACTS_DB, os.O_RDONLY | os.O_NOFOLLOW,
                            dir_fd=root_fd)
        except (OSError, OperationFailed) as error:
            return ("unreadable", getattr(error, "code", None)
                    or type(error).__name__)
        import shutil
        import tempfile
        copy_root = tempfile.mkdtemp(prefix="squirrel-classify-")
        try:
            copy_path = os.path.join(copy_root, FACTS_DB)
            with os.fdopen(db_fd, "rb") as source:
                with open(copy_path, "wb") as target:
                    shutil.copyfileobj(source, target, _COPY_CHUNK)
            db_fd = None  # ownership moved to the fdopen context
            os.chmod(copy_path, 0o600)
            try:
                disposition = helper.schema(copy_root, phase="preflight")
            except _HelperFailed as error:
                # The C++ seam cannot read the copy: corrupt / clock-invalid
                # / open or permission failure — the unreadable scene.
                return ("unreadable", error.status)
            return ("readable", disposition.get("disposition"))
        finally:
            shutil.rmtree(copy_root, ignore_errors=True)
    finally:
        if db_fd is not None:
            try:
                os.close(db_fd)
            except OSError:
                pass
        if root_fd is not None:
            os.close(root_fd)


def current_store_bytes(root):
    """Total as-is bytes of the current DB/WAL/SHM (best-effort, read-only
    size probe used for the quarantine space preflight). Returns None when
    the root or the database is unavailable."""
    try:
        root_fd = _open_root_fd(root)
    except Exception:
        return None
    try:
        total = 0
        for member in QUARANTINE_MEMBERS:
            try:
                st = os.lstat(member, dir_fd=root_fd)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
        return total
    except OSError:
        return None
    finally:
        os.close(root_fd)
