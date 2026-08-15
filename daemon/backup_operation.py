#!/usr/bin/env python3
"""The `backup.create` operation and the offline `backup verify`
(Habit130/squirrel#55).

`backup create` makes a consistent snapshot of the live fact store with the
SQLite Online Backup API (through the C++ `fact_store_tool snapshot` seam)
while concurrent fact writers keep running, then publishes a versioned
`.squirrel-memory-backup` ZIP that contains exactly two members:
`facts.sqlite3` and `manifest.json`. The destination must not exist; the ZIP
is staged in the destination parent as an exclusive owner-only temp file,
fsynced, re-opened and self-verified, and published with a hard-link rename
that can never overwrite a racing destination. A destination medium that
cannot prove owner-only 0600 semantics is refused unless the operator passed
`--allow-insecure-destination` AND typed the exact confirmation string; the
container is then permanently marked `insecure_destination: true`.

`backup verify` is completely offline: it never reads the live facts root,
never creates or touches the operation store, never connects to or starts
the daemon, never loads a model and never modifies application state. It
strictly parses the container (member set, names, attributes, encryption,
compression, sizes, ratios, CRC), extracts both members into an owner-only
temporary directory, re-computes the manifest checksums against the database
and cross-checks every manifest identity/count/HLC field against the C++
fact-store interpretation of the extracted database.

Fact semantics stay in C++ (`fact_store_tool inspect`): Python never
queries fact tables itself. No output, log, manifest or error ever contains
上文, candidate text or embeddings.
"""

import errno
import hashlib
import json
import os
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from clear_operation import (
    FactStoreHelper,
    _valid_identity_token,
)
from operations import (
    OperationBlocked,
    OperationFailed,
    OperationTypeSpec,
)

BACKUP_EXTENSION = ".squirrel-memory-backup"
BACKUP_FORMAT_VERSION = 1
MANIFEST_VERSION = 1
VERIFY_VERSION = 1
BACKUP_DIRNAME = ".backup"
FACTS_MEMBER = "facts.sqlite3"
MANIFEST_MEMBER = "manifest.json"
ZIP_MEMBERS = (FACTS_MEMBER, MANIFEST_MEMBER)
SNAPSHOT_FILE = "snapshot.sqlite3"
STAGING_MANIFEST = "manifest.json"
PUBLISHED_MARKER = "published.marker"

# Conservative, fixed, documented and tested resource bounds for any
# container accepted by verify (spec #55: "异常压缩尺寸的保守上限").
MAX_MEMBER_UNCOMPRESSED = 2 * 1024 ** 3
MAX_TOTAL_UNCOMPRESSED = 4 * 1024 ** 3
MAX_MANIFEST_SIZE = 64 * 1024
MAX_COMPRESSION_RATIO = 1000
ALLOWED_COMPRESSION = frozenset((zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED))
MAX_TEMP_SIZE = MAX_TOTAL_UNCOMPRESSED

# The exact confirmation string for an insecure destination (spec #55
# SCN-55-6): any deviation, EOF or extra character cancels.
CONFIRMATION_PREFIX = "ALLOW INSECURE BACKUP AT "

SENSITIVE_DECLARATION = (
    "This backup contains the plaintext private input history of the "
    "semantic memory. It is not encrypted; protect it as you protect the "
    "live fact store. User copies made outside the application are outside "
    "application control.")

HELPER_ENV = "SQUIRREL_FACT_STORE_HELPER"

_STABLE_MESSAGES = {
    "backup_not_found": "the backup path does not exist",
    "backup_not_regular": "the backup path is not a regular file",
    "backup_symlink": "the backup path is a symlink",
    "backup_unreadable": "the backup container cannot be read",
    "zip_malformed": "the backup container is not a well-formed ZIP",
    "zip_member_set_invalid": "the container does not contain exactly "
                              "facts.sqlite3 and manifest.json",
    "zip_member_name_invalid": "the container contains an unsafe member "
                               "name",
    "zip_member_duplicate": "the container contains duplicate members",
    "zip_member_type_invalid": "the container contains a directory, "
                               "symlink or device member",
    "zip_member_encrypted": "the container contains an encrypted member",
    "zip_compression_unsupported": "the container uses an unsupported "
                                   "compression method",
    "zip_size_limit": "the container exceeds the documented uncompressed "
                      "size limit",
    "zip_ratio_limit": "the container exceeds the documented compression "
                       "ratio limit",
    "manifest_malformed": "manifest.json is not valid JSON",
    "manifest_invalid": "manifest.json is missing or malformed fields",
    "manifest_version_unsupported": "the backup format version is not "
                                    "supported",
    "fact_store_invalid": "the facts database inside the container failed "
                          "offline validation",
    "backup_mismatch": "the facts database contradicts the manifest",
    "checksum_mismatch": "the facts database checksum does not match the "
                         "manifest",
    "size_mismatch": "the facts database size does not match the manifest",
    "insecure_destination": "the destination medium cannot guarantee "
                            "owner-only file permissions and no override "
                            "was confirmed",
    "destination_exists": "the destination already exists and would never "
                          "be overwritten",
    "destination_parent_unsafe": "the destination parent directory is "
                                 "missing, not a directory, a symlink or "
                                 "not writable",
    "fact_store_unverifiable": "the live fact store failed closed "
                               "validation and cannot be snapshotted",
    "staging_identity_missing": "the staged backup identity is missing; "
                                "restore or re-create the staging "
                                "directory, then retry",
    "staging_invalid": "the staged snapshot or manifest is invalid",
    "confirmation_required": "an insecure destination requires the exact "
                             "confirmation string",
    "unsupported_privilege": "the CLI refuses to run with elevated "
                             "privileges",
}

_BACKUP_RESULT_FIELDS = (
    "backup_version", "backup_id", "history_id", "store_epoch",
    "fact_schema_version", "event_format_version_min",
    "event_format_version_max", "commit_count", "event_count",
    "candidate_count", "retraction_count", "hlc_high_water",
    "event_hlc_high_water", "created_at", "producer", "database_size",
    "database_sha256", "insecure_destination", "plaintext_sensitive",
    "destination",
)

_MANIFEST_INT_FIELDS = (
    "fact_schema_version", "event_format_version_min",
    "event_format_version_max", "commit_count", "event_count",
    "candidate_count", "retraction_count", "database_size",
)


def _now_iso(now=None):
    if now is not None:
        return now
    return datetime.now(timezone.utc).isoformat()


def _reject_duplicate_json_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


class BackupError(Exception):
    """A stable offline backup/verify error (code + optional cause)."""

    def __init__(self, code, cause=None):
        super().__init__(code)
        self.code = code
        self.cause = cause


def _error_object(code, phase, cause=None):
    from operations import make_error
    return make_error(code, phase=phase, retryable=False,
                      remediation=_STABLE_MESSAGES.get(code, code),
                      cause=cause)


def _backup_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Manifest (write-side construction and strict read-side validation)
# ---------------------------------------------------------------------------

def _hlc_high_water(stats):
    return {"physical_ms": stats["hlc_physical_ms"],
            "logical": stats["hlc_logical"]}


def _event_hlc_high_water(stats):
    physical = stats["event_hlc_physical_ms"]
    logical = stats["event_hlc_logical"]
    if physical is None or logical is None or physical < 0 or logical < 0:
        return None
    return {"physical_ms": physical, "logical": logical}


def build_manifest(stats, backup_id, created_at, database_size,
                   database_sha256, insecure_destination, program_version):
    """Construct the versioned manifest. Every field is validated before it
    is written into the container (spec #55 SCN-55-4); the C++ snapshot
    stats are the single source of the identity/count/HLC facts."""
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "backup_id": backup_id,
        "history_id": stats["history_id"],
        "store_epoch": stats["store_epoch"],
        "fact_schema_version": stats["fact_schema_version"],
        "event_format_version_min": stats["event_format_version_min"],
        "event_format_version_max": stats["event_format_version_max"],
        "commit_count": stats["commit_count"],
        "event_count": stats["event_count"],
        "candidate_count": stats["candidate_count"],
        "retraction_count": stats["retraction_count"],
        "hlc_high_water": _hlc_high_water(stats),
        "event_hlc_high_water": _event_hlc_high_water(stats),
        "created_at": created_at,
        "producer": {
            "program": "squirrel-semantic-memory",
            "program_version": program_version,
            "fact_store_helper": "fact_store_tool",
        },
        "database_size": database_size,
        "database_sha256": database_sha256,
        "insecure_destination": bool(insecure_destination),
        "plaintext_sensitive": True,
        "sensitive_declaration": SENSITIVE_DECLARATION,
        "member_names": list(ZIP_MEMBERS),
    }
    error = validate_manifest(manifest)
    if error is not None:
        raise ValueError("constructed manifest is invalid: %s" % error)
    return manifest


def validate_manifest(payload):
    """Strict structural validation of a manifest object.

    Total: returns a stable error code string or None; never raises. The
    same validator gates the manifest before it is written into the ZIP and
    the manifest read back during offline verify (verify then re-computes
    and cross-checks everything rather than trusting the manifest).
    """
    if not isinstance(payload, dict):
        return "manifest_invalid"
    if set(payload) != set((
            "manifest_version", "backup_format_version", "backup_id",
            "history_id", "store_epoch", "fact_schema_version",
            "event_format_version_min", "event_format_version_max",
            "commit_count", "event_count", "candidate_count",
            "retraction_count", "hlc_high_water", "event_hlc_high_water",
            "created_at", "producer", "database_size", "database_sha256",
            "insecure_destination", "plaintext_sensitive",
            "sensitive_declaration", "member_names")):
        return "manifest_invalid"
    if payload["manifest_version"] != MANIFEST_VERSION:
        return "manifest_version_unsupported"
    if payload["backup_format_version"] != BACKUP_FORMAT_VERSION:
        return "manifest_version_unsupported"
    if not isinstance(payload["backup_id"], str) or not payload["backup_id"]:
        return "manifest_invalid"
    if not _valid_identity_token(payload.get("history_id") or ""):
        return "manifest_invalid"
    if not _valid_identity_token(payload.get("store_epoch") or ""):
        return "manifest_invalid"
    for key in _MANIFEST_INT_FIELDS:
        value = payload[key]
        if type(value) is not int or isinstance(value, bool):
            return "manifest_invalid"
        if key in ("commit_count", "event_count", "candidate_count",
                   "retraction_count", "database_size") and value < 0:
            return "manifest_invalid"
    if (payload["fact_schema_version"] != 1
            or not (1 <= payload["event_format_version_min"] <= 1
                    if payload["event_format_version_min"] >= 0
                    else payload["event_format_version_min"] == -1)
            or not (1 <= payload["event_format_version_max"] <= 1
                    if payload["event_format_version_max"] >= 0
                    else payload["event_format_version_max"] == -1)):
        return "manifest_version_unsupported"
    if (payload["event_format_version_min"] != -1
            and payload["event_format_version_max"] <
            payload["event_format_version_min"]):
        return "manifest_invalid"
    watermark = payload["hlc_high_water"]
    if (not isinstance(watermark, dict)
            or set(watermark) != {"physical_ms", "logical"}
            or type(watermark["physical_ms"]) is not int
            or type(watermark["logical"]) is not int
            or watermark["physical_ms"] < 0 or watermark["logical"] < 0):
        return "manifest_invalid"
    event_watermark = payload["event_hlc_high_water"]
    if event_watermark is not None:
        if (not isinstance(event_watermark, dict)
                or set(event_watermark) != {"physical_ms", "logical"}
                or type(event_watermark["physical_ms"]) is not int
                or type(event_watermark["logical"]) is not int
                or event_watermark["physical_ms"] < 0
                or event_watermark["logical"] < 0):
            return "manifest_invalid"
    if not isinstance(payload["created_at"], str) or not payload["created_at"]:
        return "manifest_invalid"
    producer = payload["producer"]
    if (not isinstance(producer, dict)
            or not isinstance(producer.get("program"), str)
            or not producer["program"]
            or not isinstance(producer.get("program_version"), str)
            or not isinstance(producer.get("fact_store_helper"), str)):
        return "manifest_invalid"
    sha = payload["database_sha256"]
    if (not isinstance(sha, str) or len(sha) != 64
            or any(ch not in "0123456789abcdef" for ch in sha)):
        return "manifest_invalid"
    if payload["database_size"] < 0:
        return "manifest_invalid"
    if type(payload["insecure_destination"]) is not bool:
        return "manifest_invalid"
    if payload["plaintext_sensitive"] is not True:
        return "manifest_invalid"
    if not isinstance(payload["sensitive_declaration"], str):
        return "manifest_invalid"
    members = payload["member_names"]
    if members != list(ZIP_MEMBERS):
        return "manifest_invalid"
    return None


# ---------------------------------------------------------------------------
# Strict ZIP parsing (shared by verify and the publish self-check)
# ---------------------------------------------------------------------------

def _unix_type(info):
    return (info.external_attr >> 16) & 0xF000


def _info_is_directory(info):
    return ((_unix_type(info) == 0x4000)
            or info.is_dir()
            or (info.filename.endswith("/")))


def _info_is_symlink(info):
    return _unix_type(info) == 0xA000


def _info_is_device(info):
    return _unix_type(info) in (0x2000, 0x6000)


def _valid_member_name(name):
    if name in ZIP_MEMBERS:
        return True
    # Any other name — including absolute, traversal, backslash or Unicode
    # lookalikes — is rejected outright.
    return False


def parse_zip_structure(path):
    """Strictly parse a `.squirrel-memory-backup` container.

    Returns the ordered list of member names and the per-member
    (uncompressed size, compress size) tuples. Raises BackupError with a
    stable code. Nothing is extracted here; this stage runs before any
    member content is opened.
    """
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, ValueError):
        raise BackupError("backup_unreadable")
    except zipfile.BadZipFile:
        raise BackupError("zip_malformed")
    try:
        infos = archive.infolist()
    except (ValueError, zipfile.BadZipFile):
        raise BackupError("zip_malformed")
    finally:
        archive.close()
    names = [info.filename for info in infos]
    # Member-level checks first: a dangerous type (directory/symlink/
    # device), name, encryption flag or compression method is rejected
    # regardless of the overall member set.
    for info in infos:
        if _info_is_directory(info):
            raise BackupError("zip_member_type_invalid")
        if _info_is_symlink(info):
            raise BackupError("zip_member_type_invalid")
        if _info_is_device(info):
            raise BackupError("zip_member_type_invalid")
        if not _valid_member_name(info.filename):
            raise BackupError("zip_member_name_invalid")
        if info.flag_bits & 0x1 or info.flag_bits & 0x40:
            raise BackupError("zip_member_encrypted")
        if info.compress_type not in ALLOWED_COMPRESSION:
            raise BackupError("zip_compression_unsupported")
    if len(names) != len(ZIP_MEMBERS):
        raise BackupError("zip_member_set_invalid")
    if set(names) != set(ZIP_MEMBERS):
        raise BackupError("zip_member_set_invalid")
    if len(set(names)) != len(names):
        raise BackupError("zip_member_duplicate")
    result = []
    total = 0
    for info in infos:
        if info.file_size > MAX_MEMBER_UNCOMPRESSED:
            raise BackupError("zip_size_limit")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise BackupError("zip_size_limit")
        if info.compress_size > 0 and info.file_size // info.compress_size \
                > MAX_COMPRESSION_RATIO:
            raise BackupError("zip_ratio_limit")
        if info.filename == MANIFEST_MEMBER \
                and info.file_size > MAX_MANIFEST_SIZE:
            raise BackupError("zip_size_limit")
        result.append((info.filename, info.file_size, info.compress_size))
    return result


def read_backup_manifest(path):
    """Read and strictly validate manifest.json from a container.

    Runs the same structural validation as the write side, then returns the
    manifest dict. Raises BackupError. Never modifies anything.
    """
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, ValueError):
        raise BackupError("backup_unreadable")
    except zipfile.BadZipFile:
        raise BackupError("zip_malformed")
    try:
        members = archive.infolist()
        if len(members) != len(ZIP_MEMBERS) \
                or set(info.filename for info in members) != set(ZIP_MEMBERS):
            raise BackupError("zip_member_set_invalid")
        info = next(info for info in members
                    if info.filename == MANIFEST_MEMBER)
        if info.file_size > MAX_MANIFEST_SIZE:
            raise BackupError("zip_size_limit")
        with archive.open(info) as stream:
            payload = stream.read()
    except BackupError:
        raise
    except (ValueError, zipfile.BadZipFile, EOFError):
        raise BackupError("zip_malformed")
    finally:
        archive.close()
    try:
        manifest = json.loads(payload.decode("utf-8"),
                              object_pairs_hook=_reject_duplicate_json_fields)
    except (ValueError, UnicodeDecodeError):
        raise BackupError("manifest_malformed")
    error = validate_manifest(manifest)
    if error is not None:
        raise BackupError(error)
    return manifest


# ---------------------------------------------------------------------------
# Offline verify (spec #55 SCN-55-9 / SCN-55-10)
# ---------------------------------------------------------------------------

def _open_verify_tempdir():
    directory = tempfile.mkdtemp(prefix="squirrel-backup-verify-")
    try:
        st = os.lstat(directory)
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o700):
            raise BackupError("backup_unreadable")
    except BackupError:
        os.rmdir(directory)
        raise
    return directory


def _extract_member(archive, info, directory, file_name, sha):
    """Stream one member into an owner-only file created exclusively via the
    directory fd; the member name has already been validated to be one of
    the two fixed names, so nothing can escape the directory. CRC is
    verified by zipfile while reading. Returns the byte count."""
    dfd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fd = os.open(file_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
    except OSError as error:
        if error.errno == errno.EEXIST:
            raise BackupError("zip_member_duplicate")
        raise BackupError("backup_unreadable")
    except BackupError:
        raise
    try:
        os.fchmod(fd, 0o600)
        try:
            with archive.open(info) as source:
                while True:
                    chunk = source.read(1 << 20)
                    if not chunk:
                        break
                    view = memoryview(chunk)
                    while view:
                        written = os.write(fd, view)
                        if written <= 0:
                            raise BackupError("backup_unreadable")
                        view = view[written:]
                    if sha is not None:
                        sha.update(chunk)
        except BackupError:
            raise
        except (ValueError, zipfile.BadZipFile, EOFError, OSError):
            raise BackupError("zip_malformed")
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        st = os.lstat(os.path.join(directory, file_name))
    except OSError:
        raise BackupError("backup_unreadable")
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
        raise BackupError("backup_unreadable")
    return st.st_size


def _cleanup_verify_dir(directory):
    if not directory:
        return
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return
    try:
        for name in os.listdir(dfd):
            try:
                os.unlink(name, dir_fd=dfd)
            except OSError:
                pass
    finally:
        os.close(dfd)
    try:
        os.rmdir(directory)
    except OSError:
        pass


def verify_backup(path, helper=None, euid=None, now=None):
    """Fully offline verification of one backup container.

    Returns a versioned result dict with `valid` True/False and, on failure,
    a stable error object. Touches only `path` and an owner-only temporary
    directory. Never connects to the daemon, never reads the live facts
    root, never writes application state.
    """
    euid = os.geteuid() if euid is None else euid
    helper = helper or FactStoreHelper()
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise BackupError("backup_not_found")
    except OSError:
        raise BackupError("backup_unreadable")
    if stat.S_ISLNK(st.st_mode):
        raise BackupError("backup_symlink")
    if not stat.S_ISREG(st.st_mode):
        raise BackupError("backup_not_regular")

    parse_zip_structure(path)
    manifest = read_backup_manifest(path)

    directory = _open_verify_tempdir()
    extracted = {}
    digests = {}
    try:
        try:
            archive = zipfile.ZipFile(path, "r")
        except (OSError, ValueError):
            raise BackupError("backup_unreadable")
        except zipfile.BadZipFile:
            raise BackupError("zip_malformed")
        try:
            members = archive.infolist()
            if len(members) != len(ZIP_MEMBERS) \
                    or set(info.filename for info in members) \
                    != set(ZIP_MEMBERS):
                raise BackupError("zip_member_set_invalid")
            for info in members:
                if info.filename == FACTS_MEMBER:
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
        # Fast, deterministic container-level checks first: the database
        # byte size and SHA-256 must match the manifest before the database
        # is even interpreted.
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
            stats = helper.inspect(db_path, phase="cli")
        except Exception as error:
            fault = getattr(error, "status", None)
            raise BackupError("fact_store_invalid",
                              cause={"fault_code": fault,
                                     "error": getattr(error, "code", None)})

        mismatch = None
        if stats["history_id"] != manifest["history_id"]:
            mismatch = ("history_id", manifest["history_id"],
                        stats["history_id"])
        elif stats["store_epoch"] != manifest["store_epoch"]:
            mismatch = ("store_epoch", manifest["store_epoch"],
                        stats["store_epoch"])
        elif stats["fact_schema_version"] != manifest["fact_schema_version"]:
            mismatch = ("fact_schema_version",
                        manifest["fact_schema_version"],
                        stats["fact_schema_version"])
        elif stats["event_format_version_min"] != \
                manifest["event_format_version_min"] or \
                stats["event_format_version_max"] != \
                manifest["event_format_version_max"]:
            mismatch = ("event_format_range",
                        (manifest["event_format_version_min"],
                         manifest["event_format_version_max"]),
                        (stats["event_format_version_min"],
                         stats["event_format_version_max"]))
        elif stats["commit_count"] != manifest["commit_count"]:
            mismatch = ("commit_count", manifest["commit_count"],
                        stats["commit_count"])
        elif stats["event_count"] != manifest["event_count"]:
            mismatch = ("event_count", manifest["event_count"],
                        stats["event_count"])
        elif stats["candidate_count"] != manifest["candidate_count"]:
            mismatch = ("candidate_count", manifest["candidate_count"],
                        stats["candidate_count"])
        elif stats["retraction_count"] != manifest["retraction_count"]:
            mismatch = ("retraction_count", manifest["retraction_count"],
                        stats["retraction_count"])
        elif stats["hlc_physical_ms"] != \
                manifest["hlc_high_water"]["physical_ms"] or \
                stats["hlc_logical"] != \
                manifest["hlc_high_water"]["logical"]:
            mismatch = ("hlc_high_water",
                        (manifest["hlc_high_water"]["physical_ms"],
                         manifest["hlc_high_water"]["logical"]),
                        (stats["hlc_physical_ms"], stats["hlc_logical"]))
        elif manifest["event_hlc_high_water"] is not None:
            if (stats["event_hlc_physical_ms"] !=
                    manifest["event_hlc_high_water"]["physical_ms"]
                    or stats["event_hlc_logical"] !=
                    manifest["event_hlc_high_water"]["logical"]):
                mismatch = (
                    "event_hlc_high_water",
                    (manifest["event_hlc_high_water"]["physical_ms"],
                     manifest["event_hlc_high_water"]["logical"]),
                    (stats["event_hlc_physical_ms"],
                     stats["event_hlc_logical"]))
        elif stats["event_hlc_physical_ms"] != -1 or \
                stats["event_hlc_logical"] != -1:
            mismatch = ("event_hlc_high_water", None,
                        (stats["event_hlc_physical_ms"],
                         stats["event_hlc_logical"]))
        if mismatch is not None:
            field, expected, actual = mismatch
            raise BackupError("backup_mismatch",
                              cause={"field": field, "expected": expected,
                                     "actual": actual})

        result = {
            "verify_version": VERIFY_VERSION,
            "valid": True,
            "backup_id": manifest["backup_id"],
            "history_id": manifest["history_id"],
            "store_epoch": manifest["store_epoch"],
            "fact_schema_version": manifest["fact_schema_version"],
            "event_format_version_min": manifest["event_format_version_min"],
            "event_format_version_max": manifest["event_format_version_max"],
            "commit_count": manifest["commit_count"],
            "event_count": manifest["event_count"],
            "candidate_count": manifest["candidate_count"],
            "retraction_count": manifest["retraction_count"],
            "hlc_high_water": manifest["hlc_high_water"],
            "event_hlc_high_water": manifest["event_hlc_high_water"],
            "created_at": manifest["created_at"],
            "producer": manifest["producer"],
            "database_size": manifest["database_size"],
            "database_sha256": manifest["database_sha256"],
            "insecure_destination": manifest["insecure_destination"],
            "plaintext_sensitive": manifest["plaintext_sensitive"],
        }
        return result
    finally:
        _cleanup_verify_dir(directory)


# ---------------------------------------------------------------------------
# backup.create operation machine
# ---------------------------------------------------------------------------

def _output_absolute(output):
    if not isinstance(output, str) or not output:
        raise ValueError("output must be a path")
    if "\x00" in output:
        raise ValueError("output must not contain NUL")
    return os.path.abspath(output)


def _temp_artifact_path(output, operation_id, kind):
    base = os.path.basename(output)
    parent = os.path.dirname(output)
    return os.path.join(parent, ".%s.%s.%s" % (base, operation_id, kind))


def _staging_root(root, operation_id):
    return os.path.join(root, BACKUP_DIRNAME, operation_id)


def _snapshot_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), SNAPSHOT_FILE)


def _staging_manifest_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), STAGING_MANIFEST)


def _published_marker_path(root, operation_id):
    return os.path.join(_staging_root(root, operation_id), PUBLISHED_MARKER)


def _write_json_atomic(path, payload, euid):
    """Owner-only temp file -> fsync -> rename -> parent fsync."""
    directory = os.path.dirname(path)
    dfd = None
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
        tmp_name = ".%s.tmp-%d" % (os.path.basename(path), os.getpid())
        fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        try:
            os.fchmod(fd, 0o600)
            data = json.dumps(payload, ensure_ascii=False,
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


def _read_json_strict(path, euid):
    import json as json_module
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != euid
                or stat.S_IMODE(st.st_mode) != 0o600):
            raise OSError("unsafe")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            return json_module.load(
                stream, object_pairs_hook=_reject_duplicate_json_fields)
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _remove_entry(root_fd, name, euid):
    """Symlink-safe, owner-verified recursive delete anchored to a directory
    fd (same policy as the clear cleanup)."""
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
        os.unlink(name, dir_fd=root_fd)
        return 0
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
                    "cleanup_owner_refused", phase="cleanup",
                    retryable=False,
                    cause={"path": os.path.join(name, entry.name)})
            if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                os.unlink(entry.name, dir_fd=dfd)
            elif entry.is_dir(follow_symlinks=False):
                _remove_entry(dfd, entry.name, euid)
            else:
                raise OperationFailed(
                    "cleanup_not_regular", phase="cleanup", retryable=False,
                    cause={"path": os.path.join(name, entry.name)})
    finally:
        os.close(dfd)
    os.rmdir(name, dir_fd=root_fd)
    return 0


def _remove_staging(root, operation_id, euid):
    """Idempotent, symlink-safe removal of this operation's staging root
    (and of the empty `.backup` directory once no other operation uses
    it)."""
    root_fd = None
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
        st = os.fstat(root_fd)
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != euid
                or stat.S_IMODE(st.st_mode) != 0o700):
            return
    except OSError:
        return
    try:
        try:
            backup_fd = os.open(BACKUP_DIRNAME,
                                os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError:
            return
        try:
            try:
                os.lstat(operation_id, dir_fd=backup_fd)
            except FileNotFoundError:
                return
            _remove_entry(backup_fd, operation_id, euid)
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)
        try:
            os.rmdir(BACKUP_DIRNAME, dir_fd=root_fd)
        except OSError:
            pass
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def _ensure_backup_dir(root, euid):
    root_fd = None
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_NOFOLLOW)
        st = os.fstat(root_fd)
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != euid
                or stat.S_IMODE(st.st_mode) != 0o700):
            raise OperationFailed(
                "root_unsafe", phase="staging", retryable=False)
    except OSError as error:
        raise OperationFailed(
            "root_unavailable", phase="staging", retryable=True,
            cause={"error": error.strerror})
    try:
        try:
            st = os.lstat(BACKUP_DIRNAME, dir_fd=root_fd)
            if (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)
                    or st.st_uid != euid
                    or stat.S_IMODE(st.st_mode) != 0o700):
                raise OperationFailed(
                    "staging_unsafe", phase="staging", retryable=False,
                    cause={"path": BACKUP_DIRNAME})
            return
        except FileNotFoundError:
            pass
        os.mkdir(BACKUP_DIRNAME, 0o700, dir_fd=root_fd)
    finally:
        os.close(root_fd)


class BackupSpec:
    """Factory for the `backup.create` OperationTypeSpec with injectable
    seams (helper, clocks, file-system primitives for fault injection).

    Phase machine (canonical order):

        preflight -> staging -> publishing -> cleanup

    - `publishing` is the irreversible phase: the container is written,
      fsynced, self-verified and published with a no-overwrite hard-link
      rename; a cancel requested at/after it is refused as uncancellable and
      the operation only finishes self-check and cleanup.
    - `cleanup` doubles as the cancel compensation phase (cancel_phase): a
      cancel honored in preflight/staging moves the machine there, removes
      the staged snapshot/manifest and this operation's temp artifacts, and
      goes terminal `cancelled` — a cancelled backup never leaves a final
      target.
    - The staged backup_id and manifest are durable and reused verbatim
      across retries (no identity regeneration, no second snapshot, no
      re-snapshot after a crash mid-publish: the published container's own
      backup_id/checksum identify a previous successful publication).
    """

    def __init__(self, root, *, helper=None, euid=None, program_version="",
                 now=None, link=None, fsync_dir=None, write_zip=None,
                 probe_medium=None, read_backup_manifest_fn=None):
        self.root = root
        self.euid = os.geteuid() if euid is None else euid
        self.helper = helper or FactStoreHelper()
        self.program_version = program_version
        self.now = now
        self.link = link
        self.fsync_dir = fsync_dir
        self.write_zip = write_zip
        self.probe_medium = probe_medium
        self.read_backup_manifest_fn = read_backup_manifest_fn

    # -- helpers ------------------------------------------------------------

    def _normalize(self, parameters):
        if not isinstance(parameters, dict):
            raise ValueError("backup.create parameters must be an object")
        output = _output_absolute(parameters.get("output"))
        allow_insecure = parameters.get("allow_insecure", False)
        if type(allow_insecure) is not bool:
            raise ValueError("allow_insecure must be a boolean")
        return {"output": output, "allow_insecure": allow_insecure}

    def _live_store_state(self, phase):
        """Read-only current store state through the C++ seam; raises
        OperationBlocked when the store cannot be proven snapshot-able."""
        try:
            identity, _empty = self.helper.verify(self.root)
        except Exception as error:
            fault = getattr(error, "status", None)
            raise OperationBlocked(
                "fact_store_unverifiable", phase=phase,
                remediation="inspect and fix the fact store before "
                            "backing it up",
                cause={"fault_code": fault})
        return identity

    def _load_staging_manifest(self, operation_id):
        payload = _read_json_strict(
            _staging_manifest_path(self.root, operation_id), self.euid)
        if payload is None:
            return None
        error = validate_manifest(payload)
        if error is not None:
            return None
        return payload

    def _verify_staging(self, operation_id, manifest):
        """Re-verify an existing staging artifact: the snapshot must exist
        and its C++ interpretation must match the staged manifest field by
        field. A stale or tampered staging is removed by the caller."""
        snapshot_path = _snapshot_path(self.root, operation_id)
        try:
            st = os.lstat(snapshot_path)
        except OSError:
            return False
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != self.euid
                or stat.S_IMODE(st.st_mode) != 0o600):
            return False
        try:
            stats = self.helper.inspect(snapshot_path, phase="staging")
        except Exception:
            return False
        return _stats_match_manifest(stats, manifest)

    def _destination_state(self, output, manifest):
        """Classify the final destination against this operation's staged
        manifest: 'absent', 'own_published' (a previous attempt of this
        operation already published the identical container) or an
        OperationBlocked for any other existing path (never overwritten)."""
        try:
            st = os.lstat(output)
        except FileNotFoundError:
            return "absent"
        except OSError as error:
            raise OperationBlocked(
                "destination_exists", phase="preflight",
                remediation="choose a destination that does not exist",
                cause={"error": error.strerror})
        if not stat.S_ISREG(st.st_mode) or st.st_uid != self.euid:
            raise OperationBlocked(
                "destination_exists", phase="preflight",
                remediation="choose a destination that does not exist",
                cause={"kind": "existing"})
        if manifest is None:
            raise OperationBlocked(
                "destination_exists", phase="preflight",
                remediation="choose a destination that does not exist",
                cause={"kind": "existing"})
        try:
            final_manifest = self._read_final_manifest(output)
        except BackupError:
            raise OperationBlocked(
                "destination_exists", phase="preflight",
                remediation="choose a destination that does not exist",
                cause={"kind": "existing_unreadable"})
        if final_manifest["backup_id"] != manifest["backup_id"]:
            raise OperationBlocked(
                "destination_exists", phase="preflight",
                remediation="choose a destination that does not exist",
                cause={"kind": "other_backup"})
        return "own_published"

    def _read_final_manifest(self, output):
        if self.read_backup_manifest_fn is not None:
            return self.read_backup_manifest_fn(output)
        return read_backup_manifest(output)

    def _verify_parent(self, output, phase):
        parent = os.path.dirname(output)
        try:
            st = os.lstat(parent)
        except FileNotFoundError:
            raise OperationBlocked(
                "destination_parent_unsafe", phase=phase,
                remediation="create the destination directory first")
        except OSError:
            raise OperationBlocked(
                "destination_parent_unsafe", phase=phase,
                remediation="the destination directory is not accessible")
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise OperationBlocked(
                "destination_parent_unsafe", phase=phase,
                remediation="the destination directory must be a real "
                            "directory, not a symlink")
        try:
            parent_fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            raise OperationBlocked(
                "destination_parent_unsafe", phase=phase,
                remediation="the destination directory is not accessible")
        try:
            pst = os.fstat(parent_fd)
            if not stat.S_ISDIR(pst.st_mode):
                raise OperationBlocked(
                    "destination_parent_unsafe", phase=phase,
                    remediation="the destination directory must be a "
                                "directory")
            if not os.access(parent, os.W_OK):
                raise OperationBlocked(
                    "destination_parent_unsafe", phase=phase,
                    remediation="the destination directory is not writable")
        finally:
            os.close(parent_fd)
        return parent

    def _probe_medium(self, output, operation_id):
        """Prove (or fail to prove) that the destination medium honors
        owner-only regular files: create an exclusive 0600 probe in the
        destination parent, fchmod it, and read back the real mode/owner.
        Returns True when secure, False when insecure. The probe is always
        removed."""
        if self.probe_medium is not None:
            return self.probe_medium(output, operation_id)
        probe = _temp_artifact_path(output, operation_id, "probe")
        parent = os.path.dirname(output)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            try:
                fd = os.open(os.path.basename(probe),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            except OSError as error:
                if error.errno != errno.EEXIST:
                    raise OperationFailed(
                        "staging_write_failed", phase="staging",
                        retryable=True, cause={"error": error.strerror})
                st = os.lstat(os.path.basename(probe), dir_fd=parent_fd)
                if (not stat.S_ISREG(st.st_mode) or st.st_uid != self.euid):
                    raise OperationBlocked(
                        "destination_parent_unsafe", phase="staging",
                        remediation="the destination directory contains a "
                                    "foreign probe file; inspect it")
                os.unlink(os.path.basename(probe), dir_fd=parent_fd)
                fd = os.open(os.path.basename(probe),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            try:
                os.fchmod(fd, 0o600)
                st = os.fstat(fd)
                secure = (stat.S_ISREG(st.st_mode)
                          and st.st_uid == self.euid
                          and stat.S_IMODE(st.st_mode) == 0o600)
            finally:
                os.close(fd)
            os.unlink(os.path.basename(probe), dir_fd=parent_fd)
            os.fsync(parent_fd)
            return secure
        finally:
            os.close(parent_fd)

    def _remove_own_artifacts(self, output, operation_id):
        """Remove this operation's temp/probe artifacts in the destination
        parent (never the final target). Idempotent; owner-verified."""
        parent = os.path.dirname(output)
        base = os.path.basename(output)
        prefix = ".%s.%s." % (base, operation_id)
        parent_fd = None
        try:
            parent_fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return
        try:
            try:
                names = os.listdir(parent_fd)
            except OSError:
                return
            for name in names:
                if not name.startswith(prefix):
                    continue
                try:
                    st = os.lstat(name, dir_fd=parent_fd)
                    if st.st_uid != self.euid:
                        continue
                    if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                        os.unlink(name, dir_fd=parent_fd)
                    elif stat.S_ISDIR(st.st_mode):
                        _remove_entry(parent_fd, name, self.euid)
                except OSError:
                    continue
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    # -- steps --------------------------------------------------------------

    def _step_preflight(self, record):
        output = record["parameters"]["output"]
        self._live_store_state("preflight")
        self._verify_parent(output, "preflight")
        manifest = self._load_staging_manifest(record["operation_id"])
        self._destination_state(output, manifest)
        return {"advance": True}

    def _step_staging(self, record):
        operation_id = record["operation_id"]
        output = record["parameters"]["output"]
        allow_insecure = record["parameters"]["allow_insecure"]
        manifest = self._load_staging_manifest(operation_id)
        if manifest is not None and self._verify_staging(operation_id,
                                                         manifest):
            return {"advance": True}
        if manifest is not None:
            _remove_staging(self.root, operation_id, self.euid)
        _ensure_backup_dir(self.root, self.euid)
        os.makedirs(_staging_root(self.root, operation_id), mode=0o700,
                    exist_ok=False)
        snapshot_path = _snapshot_path(self.root, operation_id)
        try:
            stats = self.helper.snapshot(self.root, snapshot_path,
                                         phase="staging")
        except Exception:
            _remove_staging(self.root, operation_id, self.euid)
            raise
        secure = self._probe_medium(output, operation_id)
        if not secure and not allow_insecure:
            _remove_staging(self.root, operation_id, self.euid)
            raise OperationBlocked(
                "insecure_destination", phase="staging",
                remediation="run with --allow-insecure-destination and "
                            "confirm the exact string, or choose a "
                            "destination on a medium that honors "
                            "owner-only permissions")
        try:
            st = os.lstat(snapshot_path)
        except OSError as error:
            _remove_staging(self.root, operation_id, self.euid)
            raise OperationFailed(
                "staging_write_failed", phase="staging", retryable=True,
                cause={"error": error.strerror})
        if not stat.S_ISREG(st.st_mode) or st.st_uid != self.euid \
                or stat.S_IMODE(st.st_mode) != 0o600:
            _remove_staging(self.root, operation_id, self.euid)
            raise OperationBlocked(
                "staging_invalid", phase="staging",
                remediation="restore or re-create the staging directory "
                            "for this operation, then retry")
        backup_id = _backup_id()
        created_at = _now_iso(self.now)
        sha = hashlib.sha256()
        with open(snapshot_path, "rb") as stream:
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                sha.update(chunk)
        database_sha256 = sha.hexdigest()
        database_size = st.st_size
        manifest = build_manifest(
            stats, backup_id, created_at, database_size, database_sha256,
            insecure_destination=not secure,
            program_version=self.program_version)
        _write_json_atomic(_staging_manifest_path(self.root, operation_id),
                           manifest, self.euid)
        return {"progress": {"bytes": database_size, "chunks": 1},
                "advance": True}

    def _build_temp_zip(self, output, operation_id, manifest):
        """Write the final container as an exclusive owner-only temp file in
        the destination parent; fsync it; then re-open and strictly
        self-verify it before publication. Returns the temp path."""
        temp = _temp_artifact_path(output, operation_id, "tmp")
        self._remove_own_artifacts(output, operation_id)
        snapshot_path = _snapshot_path(self.root, operation_id)
        parent = os.path.dirname(output)
        if self.write_zip is not None:
            self.write_zip(temp, snapshot_path, manifest, parent)
        else:
            parent_fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                fd = os.open(os.path.basename(temp),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            except OSError as error:
                if error.errno != errno.EEXIST:
                    raise OperationFailed(
                        "staging_write_failed", phase="publishing",
                        retryable=True, cause={"error": error.strerror})
                raise OperationBlocked(
                    "staging_invalid", phase="publishing",
                    remediation="a temp file for this operation already "
                                "exists and could not be replaced; inspect "
                                "it")
            try:
                os.fchmod(fd, 0o600)
                st = os.fstat(fd)
                if (not stat.S_ISREG(st.st_mode) or st.st_uid != self.euid
                        or stat.S_IMODE(st.st_mode) != 0o600):
                    raise OperationBlocked(
                        "insecure_destination", phase="publishing",
                        remediation="the destination medium cannot "
                                    "guarantee owner-only permissions")
                raw = os.fdopen(fd, "wb")
                fd = None
                try:
                    with zipfile.ZipFile(raw, "w",
                                         compression=zipfile.ZIP_DEFLATED,
                                         allowZip64=False) as archive:
                        for name in ZIP_MEMBERS:
                            info = zipfile.ZipInfo(name)
                            info.create_system = 3
                            info.external_attr = (0o600 | 0x8000) << 16
                            info.date_time = _zip_date_time(self.now)
                            if name == FACTS_MEMBER:
                                with open(snapshot_path, "rb") as source:
                                    archive.writestr(info, source.read())
                            else:
                                archive.writestr(
                                    info, json.dumps(
                                        manifest, ensure_ascii=False,
                                        indent=2).encode("utf-8"))
                    raw.flush()
                    os.fsync(raw.fileno())
                finally:
                    raw.close()
            finally:
                if fd is not None:
                    os.close(fd)
            os.fsync(parent_fd)
            os.close(parent_fd)
        # Re-open and self-verify the staged container exactly like verify
        # does, before anything is published.
        try:
            structure = parse_zip_structure(temp)
            final_manifest = self._read_final_manifest(temp)
        except BackupError as error:
            raise OperationBlocked(
                "staging_invalid", phase="publishing",
                remediation="the staged container failed self-verification; "
                            "retry to rebuild it",
                cause={"fault_code": error.code})
        if (final_manifest["backup_id"] != manifest["backup_id"]
                or [name for name, _size, _c in structure] !=
                list(ZIP_MEMBERS)):
            raise OperationBlocked(
                "staging_invalid", phase="publishing",
                remediation="the staged container failed self-verification; "
                            "retry to rebuild it")
        return temp

    def _publish(self, temp, output):
        """No-overwrite atomic publication: a hard-link rename into the
        destination succeeds only when the destination does not exist, so a
        concurrently created destination is never overwritten; the temp is
        then unlinked and the parent directory fsynced."""
        if self.link is not None:
            try:
                return self.link(temp, output)
            except OSError as error:
                if error.errno == errno.EEXIST:
                    raise OperationBlocked(
                        "destination_exists", phase="publishing",
                        remediation="a destination appeared during "
                                    "publication; it is never overwritten")
                raise OperationFailed(
                    "publish_failed", phase="publishing", retryable=True,
                    cause={"error": error.strerror})
        try:
            os.link(temp, output)
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise OperationFailed(
                    "publish_failed", phase="publishing", retryable=True,
                    cause={"error": error.strerror})
            raise OperationBlocked(
                "destination_exists", phase="publishing",
                remediation="a destination appeared during publication; "
                            "it is never overwritten")
        os.unlink(temp)
        parent = os.path.dirname(output)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def _self_check_final(self, output, manifest):
        """Verify the published final: it must be a regular owner-owned file
        whose container reads back with this operation's backup_id."""
        try:
            st = os.lstat(output)
        except OSError as error:
            raise OperationFailed(
                "publish_failed", phase="publishing", retryable=True,
                cause={"error": error.strerror})
        if not stat.S_ISREG(st.st_mode):
            raise OperationBlocked(
                "staging_invalid", phase="publishing",
                remediation="the published destination is not a regular "
                            "file; inspect it")
        try:
            final_manifest = self._read_final_manifest(output)
        except BackupError as error:
            raise OperationBlocked(
                "staging_invalid", phase="publishing",
                remediation="the published container does not verify; "
                            "inspect it",
                cause={"fault_code": error.code})
        if final_manifest["backup_id"] != manifest["backup_id"]:
            raise OperationBlocked(
                "staging_invalid", phase="publishing",
                remediation="the published container belongs to a different "
                            "backup; inspect it")

    def _step_publishing(self, record):
        operation_id = record["operation_id"]
        output = record["parameters"]["output"]
        manifest = self._load_staging_manifest(operation_id)
        if manifest is None:
            raise OperationBlocked(
                "staging_identity_missing", phase="publishing",
                remediation="restore or re-create the staging directory for "
                            "this operation, then retry")
        if not self._verify_staging(operation_id, manifest):
            raise OperationBlocked(
                "staging_invalid", phase="publishing",
                remediation="the staged snapshot or manifest is invalid; "
                            "retry to rebuild it")
        temp = _temp_artifact_path(output, operation_id, "tmp")
        try:
            published_before = self._destination_state(output, manifest) \
                == "own_published"
            if not published_before:
                temp = self._build_temp_zip(output, operation_id, manifest)
                self._publish(temp, output)
            self._self_check_final(output, manifest)
            _write_json_atomic(
                _published_marker_path(self.root, operation_id),
                {"backup_id": manifest["backup_id"],
                 "destination": output,
                 "database_sha256": manifest["database_sha256"],
                 "published_at": _now_iso(self.now)}, self.euid)
        except OperationBlocked:
            self._remove_own_artifacts(output, operation_id)
            raise
        except OperationFailed:
            try:
                st = os.lstat(output)
                own_published = stat.S_ISREG(st.st_mode) \
                    and st.st_uid == self.euid
            except OSError:
                own_published = False
            if not own_published:
                self._remove_own_artifacts(output, operation_id)
            raise
        return {"progress": {"bytes": manifest["database_size"],
                             "chunks": 1},
                "advance": True}

    def _step_cleanup(self, record):
        operation_id = record["operation_id"]
        output = record["parameters"]["output"]
        removed = 0
        if record["cancel_requested"]:
            # Compensation for a pre-publish cancel: the final target never
            # exists (cancel is only honored before the irreversible
            # publishing phase); remove this operation's temp/probe
            # artifacts and its staged snapshot/manifest.
            self._remove_own_artifacts(output, operation_id)
            _remove_staging(self.root, operation_id, self.euid)
            return {"advance": True}
        manifest = self._load_staging_manifest(operation_id)
        _remove_staging(self.root, operation_id, self.euid)
        self._remove_own_artifacts(output, operation_id)
        if manifest is None:
            return {"advance": True}
        try:
            st = os.lstat(output)
            regular = stat.S_ISREG(st.st_mode) and st.st_uid == self.euid
        except OSError:
            regular = False
        if not regular:
            raise OperationBlocked(
                "staging_invalid", phase="cleanup",
                remediation="the published destination is missing after a "
                            "successful publication; inspect it")
        result = {
            "backup_version": BACKUP_FORMAT_VERSION,
            "backup_id": manifest["backup_id"],
            "history_id": manifest["history_id"],
            "store_epoch": manifest["store_epoch"],
            "fact_schema_version": manifest["fact_schema_version"],
            "event_format_version_min": manifest["event_format_version_min"],
            "event_format_version_max": manifest["event_format_version_max"],
            "commit_count": manifest["commit_count"],
            "event_count": manifest["event_count"],
            "candidate_count": manifest["candidate_count"],
            "retraction_count": manifest["retraction_count"],
            "hlc_high_water": manifest["hlc_high_water"],
            "event_hlc_high_water": manifest["event_hlc_high_water"],
            "created_at": manifest["created_at"],
            "producer": manifest["producer"],
            "database_size": manifest["database_size"],
            "database_sha256": manifest["database_sha256"],
            "insecure_destination": manifest["insecure_destination"],
            "plaintext_sensitive": manifest["plaintext_sensitive"],
            "destination": output,
        }
        return {"progress": {"bytes": removed, "chunks": 1},
                "advance": True, "result": result}

    def build(self):
        steps = {
            "preflight": self._step_preflight,
            "staging": self._step_staging,
            "publishing": self._step_publishing,
            "cleanup": self._step_cleanup,
        }
        return OperationTypeSpec(
            "backup.create",
            phases=("preflight", "staging", "publishing", "cleanup"),
            irreversible_phase="publishing",
            normalize=self._normalize,
            steps=steps,
            cancel_phase="cleanup",
        )


def _stats_match_manifest(stats, manifest):
    """True when the C++ snapshot stats match the manifest field by field
    (the manifest must never contradict the snapshot)."""
    if (stats["history_id"] != manifest["history_id"]
            or stats["store_epoch"] != manifest["store_epoch"]
            or stats["fact_schema_version"] != manifest["fact_schema_version"]
            or stats["event_format_version_min"] !=
            manifest["event_format_version_min"]
            or stats["event_format_version_max"] !=
            manifest["event_format_version_max"]
            or stats["commit_count"] != manifest["commit_count"]
            or stats["event_count"] != manifest["event_count"]
            or stats["candidate_count"] != manifest["candidate_count"]
            or stats["retraction_count"] != manifest["retraction_count"]
            or stats["hlc_physical_ms"] !=
            manifest["hlc_high_water"]["physical_ms"]
            or stats["hlc_logical"] != manifest["hlc_high_water"]["logical"]):
        return False
    event_watermark = manifest["event_hlc_high_water"]
    if event_watermark is None:
        return (stats["event_hlc_physical_ms"] == -1
                and stats["event_hlc_logical"] == -1)
    return (stats["event_hlc_physical_ms"] == event_watermark["physical_ms"]
            and stats["event_hlc_logical"] == event_watermark["logical"])


def _zip_date_time(now):
    if callable(now):
        moment = now()
    else:
        moment = datetime.now(timezone.utc)
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute,
            max(0, moment.second))


def build_backup_spec(root, **seams):
    """Build the production `backup.create` operation type for one semantic
    root."""
    return BackupSpec(root, **seams).build()


def production_registry(root, **seams):
    """The production backup registry: `backup.create` only."""
    from operations import OperationRegistry
    registry = OperationRegistry()
    registry.register(build_backup_spec(root, **seams))
    return registry
