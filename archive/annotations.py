"""Collector-owned versioned human evidence, never an observation writer.

The fsynced manifest publishes a prefix of an append-only journal. Indexes hold
offsets, hashes and revision numbers, not private values. Queries seek at most
one revision per kind/source; no cursor owns a copy of the history.
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import os
import stat
import threading
import tempfile
import uuid

from archive.interface import InterfaceError, canonical_bytes
from archive.safety import UnsafeRoot, atomic_write, open_nofollow, safe_token

ANNOTATION_VERSION = "input-archive-annotations-v1"
KINDS = ("confirm", "correct", "exclude", "experience")
TEXT_BYTES = 8192
NOTE_BYTES = 2048
LINE_BYTES = 131072
PAGE_BYTES = 1048576
MAX_REVISION = (1 << 63) - 1
EXPERIENCES = ("input_difficulty", "candidate_issue", "unexpected_behavior", "other")
VALUES = ("minor", "major", "blocking")
REASONS = ("private", "sensitive", "unrepresentative", "other")
ZERO = "0" * 64


def integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_REVISION


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def bounded_text(value, bound, empty=False):
    if not isinstance(value, str) or (not value and not empty):
        raise InterfaceError("invalid_request")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError:
        raise InterfaceError("invalid_request")
    if length > bound:
        raise InterfaceError("annotation_input_bound")
    return value


def normalize_edit(body):
    if set(body) - {"annotation_version", "source_reference", "expected_revision", "operation_id", "kind", "value"}:
        raise InterfaceError("invalid_request")
    kind = body.get("kind")
    value = body.get("value", {})
    if kind not in KINDS or not isinstance(value, dict):
        raise InterfaceError("invalid_request")
    if not integer(body.get("expected_revision")) or safe_token(body.get("operation_id")) is None:
        raise InterfaceError("invalid_request")
    if kind == "confirm":
        if value:
            raise InterfaceError("invalid_request")
        value = {}
    elif kind == "correct":
        if set(value) != {"text"}:
            raise InterfaceError("invalid_request")
        value = {"text": bounded_text(value["text"], TEXT_BYTES)}
    elif kind == "exclude":
        if set(value) != {"reason"} or value.get("reason") not in REASONS:
            raise InterfaceError("invalid_request")
        value = {"reason": value["reason"], "excluded": True}
    else:
        if set(value) - {"kind", "value", "note"} or value.get("kind") not in EXPERIENCES or value.get("value") not in VALUES:
            raise InterfaceError("invalid_request")
        value = {"kind": value["kind"], "value": value["value"], "note": bounded_text(value.get("note", ""), NOTE_BYTES, True)}
    return kind, value


class AnnotationStore:
    """One instance beneath the collector's lifetime OwnerLock.

    No operation here holds the collector admission lock. Startup streams the
    published journal once, then stores O(revisions) metadata and idempotency
    hashes; payload history lives on disk. A failed uncertain write poisons this
    instance until restart, never rolls a possibly published decision backward.
    """

    def __init__(self, root):
        self.root = root
        self.identity_path = os.path.join(root, "annotation-identity.json")
        self.manifest_path = os.path.join(root, "annotation-state.json")
        self.journal_path = os.path.join(root, "annotations.jsonl")
        self.lock = threading.Lock()
        self.failed = False
        self.history = {}
        self.operations = {}
        self.revision = 0
        self.offset = 0
        self.chain = ZERO
        self.archive_id = None

    def _check_path(self, path):
        if not os.path.lexists(path):
            return
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
            raise UnsafeRoot("annotation_artifact")

    def _read_json(self, path, bound=4096):
        self._check_path(path)
        fd = open_nofollow(path, os.O_RDONLY)
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(bound + 1)
        if len(raw) > bound:
            raise ValueError()
        return json.loads(raw)

    def prepare(self):
        for path in (self.identity_path, self.manifest_path, self.journal_path):
            self._check_path(path)
        try:
            exists = tuple(os.path.exists(p) for p in (self.identity_path, self.manifest_path, self.journal_path))
            if not any(exists):
                self.archive_id = uuid.uuid4().hex
                # Publish the empty journal and manifest first, identity last.
                # Interrupted initialization is refused, never treated as empty.
                fd = open_nofollow(self.journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.fsync(fd)
                os.close(fd)
                atomic_write(self.manifest_path, canonical_bytes(self._manifest()))
                atomic_write(self.identity_path, canonical_bytes({"version": ANNOTATION_VERSION, "archive_id": self.archive_id}))
            elif not all(exists):
                raise ValueError()
            identity = self._read_json(self.identity_path)
            if set(identity) != {"version", "archive_id"} or identity["version"] != ANNOTATION_VERSION:
                raise ValueError()
            archive_id = identity["archive_id"]
            if not isinstance(archive_id, str) or len(archive_id) != 32 or any(ch not in "0123456789abcdef" for ch in archive_id):
                raise ValueError()
            self.archive_id = archive_id
            state = self._read_json(self.manifest_path)
            if set(state) != {"version", "archive_id", "revision", "offset", "chain"} or state["version"] != ANNOTATION_VERSION or state["archive_id"] != self.archive_id:
                raise ValueError()
            if not integer(state["revision"]) or not integer(state["offset"]):
                raise ValueError()
            fd = open_nofollow(self.journal_path, os.O_RDWR)
            with os.fdopen(fd, "r+b") as handle:
                while handle.tell() < state["offset"]:
                    offset = handle.tell()
                    raw = handle.readline(LINE_BYTES + 1)
                    if len(raw) > LINE_BYTES or not raw.endswith(b"\n") or handle.tell() > state["offset"]:
                        raise ValueError()
                    row = json.loads(raw)
                    self._validate_row(row)
                    self._remember(row, offset, len(raw))
                if self.revision != state["revision"] or self.chain != state["chain"] or handle.tell() != state["offset"]:
                    raise ValueError()
                if os.fstat(handle.fileno()).st_size < state["offset"]:
                    raise ValueError()
                handle.truncate(state["offset"])
                handle.flush()
                os.fsync(handle.fileno())
                self.offset = state["offset"]
        except (OSError, ValueError, TypeError, KeyError, InterfaceError, UnicodeError):
            self.failed = True
            raise InterfaceError("annotation_state_invalid")

    def _manifest(self):
        return {"version": ANNOTATION_VERSION, "archive_id": self.archive_id, "revision": self.revision, "offset": self.offset, "chain": self.chain}

    def _validate_row(self, row):
        if not isinstance(row, dict) or set(row) != {"version", "archive_id", "revision", "operation_id", "semantic", "semantic_hash", "previous", "chain"}:
            raise ValueError()
        if row["version"] != ANNOTATION_VERSION or row["archive_id"] != self.archive_id or not integer(row["revision"], 1) or row["revision"] != self.revision + 1 or row["previous"] != self.chain:
            raise ValueError()
        if safe_token(row["operation_id"]) is None or row["operation_id"] in self.operations or digest(row["semantic"]) != row["semantic_hash"]:
            raise ValueError()
        check = dict(row)
        chain = check.pop("chain")
        if digest(check) != chain:
            raise ValueError()
        semantic = row["semantic"]
        if not isinstance(semantic, dict) or set(semantic) != {"source_reference", "kind", "value", "provenance", "expected_revision"} or semantic.get("kind") not in KINDS or semantic.get("provenance") != "human" or type(semantic.get("expected_revision")) is not int or semantic["expected_revision"] != self.revision:
            raise ValueError()
        value = semantic["value"]
        if semantic["kind"] == "exclude":
            if not isinstance(value, dict) or value.get("excluded") is not True or set(value) != {"excluded", "reason"}:
                raise ValueError()
            value = {"reason": value["reason"]}
        kind, normalized = normalize_edit({"kind": semantic["kind"], "value": value, "expected_revision": semantic["expected_revision"], "operation_id": row["operation_id"]})
        if normalized != semantic["value"]:
            raise ValueError()
        self._reference_shape(semantic["source_reference"])

    def _remember(self, row, offset, length):
        semantic = row["semantic"]
        ref = semantic["source_reference"]
        key = (ref["source_instance_id"], ref["source_local_sequence"], semantic["kind"])
        self.history.setdefault(key, []).append((row["revision"], offset, length, digest(row)))
        self.operations[row["operation_id"]] = (row["semantic_hash"], row["revision"])
        self.revision = row["revision"]
        self.chain = row["chain"]

    def _reference_shape(self, ref):
        if not isinstance(ref, dict) or set(ref) != {"archive_id", "source_instance_id", "source_local_sequence", "durable_seq", "record_digest"}:
            raise InterfaceError("invalid_request")
        if ref["archive_id"] != self.archive_id:
            raise InterfaceError("annotation_foreign_archive")
        if safe_token(ref["source_instance_id"]) is None or not integer(ref["source_local_sequence"]) or not integer(ref["durable_seq"], 1):
            raise InterfaceError("invalid_request")
        d = ref["record_digest"]
        if not isinstance(d, str) or len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
            raise InterfaceError("invalid_request")

    def _healthy(self):
        if self.failed:
            raise InterfaceError("annotation_state_invalid")
        for path in (self.identity_path, self.manifest_path, self.journal_path):
            if not os.path.lexists(path):
                raise InterfaceError("annotation_state_invalid")
            self._check_path(path)

    def mutate(self, body, resolve_source):
        with self.lock:
            self._healthy()
            if body.get("annotation_version") != ANNOTATION_VERSION:
                raise InterfaceError("unsupported_annotation_version")
            kind, value = normalize_edit(body)
            ref = body.get("source_reference")
            self._reference_shape(ref)
            source = resolve_source(ref)
            if kind == "confirm" and source["observed_target"] is None:
                raise InterfaceError("annotation_target_unavailable")
            semantic = {"source_reference": ref, "kind": kind, "value": value, "provenance": "human", "expected_revision": body["expected_revision"]}
            semantic_hash = digest(semantic)
            prior = self.operations.get(body["operation_id"])
            if prior is not None:
                if prior[0] != semantic_hash:
                    raise InterfaceError("annotation_operation_conflict")
                return self._ack(prior[1], True)
            if body["expected_revision"] != self.revision:
                raise InterfaceError("annotation_stale_revision")
            if self.revision == MAX_REVISION:
                raise InterfaceError("annotation_input_bound")
            row = {"version": ANNOTATION_VERSION, "archive_id": self.archive_id, "revision": self.revision + 1, "operation_id": body["operation_id"], "semantic": semantic, "semantic_hash": semantic_hash, "previous": self.chain}
            row["chain"] = digest(row)
            raw = canonical_bytes(row) + b"\n"
            try:
                self._append(raw)
                state = {"version": ANNOTATION_VERSION, "archive_id": self.archive_id, "revision": row["revision"], "offset": self.offset + len(raw), "chain": row["chain"]}
                self._publish(state)
            except (OSError, UnsafeRoot):
                self.failed = True
                raise InterfaceError("storage_failure")
            self._remember(row, self.offset, len(raw))
            self.offset += len(raw)
            return self._ack(self.revision, False)

    def _append(self, raw):
        fd = open_nofollow(self.journal_path, os.O_WRONLY)
        try:
            os.lseek(fd, self.offset, os.SEEK_SET)
            remaining = memoryview(raw)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError()
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    def _publish(self, state):
        # Unlike a single os.write, this cannot mistake a short write for a
        # published manifest. A failure after replace is uncertain: poison
        # this instance and let restart validate the complete old/new prefix.
        self._check_path(self.manifest_path)
        fd, temporary = tempfile.mkstemp(prefix=".annotation-", dir=self.root)
        try:
            remaining = memoryview(canonical_bytes(state))
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError()
                remaining = remaining[written:]
            os.fchmod(fd, 0o600)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, self.manifest_path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _ack(self, revision, replayed):
        return {"annotation_version": ANNOTATION_VERSION, "archive_id": self.archive_id, "annotation_revision": revision, "current_annotation_revision": self.revision, "durable": True, "replayed": replayed}

    def effective(self, ref, revision):
        """Caller holds store lock; <=4 single-row reads, O(log H) per kind."""
        found = {}
        for kind in KINDS:
            history = self.history.get((ref["source_instance_id"], ref["source_local_sequence"], kind), [])
            position = bisect.bisect_right(history, (revision, MAX_REVISION, MAX_REVISION, "z")) - 1
            if position < 0:
                continue
            rev, offset, length, row_hash = history[position]
            fd = open_nofollow(self.journal_path, os.O_RDONLY)
            with os.fdopen(fd, "rb") as handle:
                handle.seek(offset)
                raw = handle.read(length)
            try:
                row = json.loads(raw)
                if digest(row) != row_hash or row["semantic"]["source_reference"] != ref:
                    raise ValueError()
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise InterfaceError("annotation_state_invalid")
            found[kind] = {"revision": rev, **row["semantic"]}
        return found


def observed_target(record):
    """Only concrete submitted targets; never composition/host/unselected text."""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = record.get("observation_kind")
    if kind == "commit_attempt":
        text = payload.get("text")
    elif kind == "plugin_observation" and (record.get("plugin") or {}).get("plugin_stage") == "commit":
        text = payload.get("text")
    else:
        return None
    if not isinstance(text, str) or not text:
        return None
    try:
        bounded_text(text, TEXT_BYTES)
    except InterfaceError:
        return None
    return text


def evidence(source, edits, private):
    record = source["record"]
    plugin = record.get("plugin") or {}
    observed = source["observed_target"]
    human = max((edits[k] for k in ("confirm", "correct") if k in edits), key=lambda item: item["revision"], default=None)
    provenance = "unavailable"
    target = None
    if human:
        provenance = "human_reviewed" if human["kind"] == "confirm" else "human_corrected"
        target = observed if human["kind"] == "confirm" else human["value"]["text"]
    elif observed is not None:
        target = observed
        provenance = "observed_explicit_preference" if plugin.get("submission") == "explicit" else "observed_default_weak" if plugin.get("submission") == "default" else "observed_submission_unknown"
    exclusion = edits.get("exclude")
    experience = edits.get("experience")
    # A human correction is language material evidence, not automatic corpus
    # admission, observed membership or a reconstructed choice competition.
    choice = source.get("choice")
    eligible = bool(choice and choice.get("evidence_permitted") and not choice.get("retracted") and choice.get("request_outcome") == "engine_commit_observed" and target is not None and target == observed and choice.get("target_membership") == "present" and not exclusion)
    result = {
        "source_reference": source["reference"],
        "observed_kind": record.get("observation_kind"),
        "observed_outcome": record.get("outcome"),
        "observed_submission": plugin.get("submission", "unknown"),
        "target_available": target is not None,
        "target_provenance": provenance,
        "human_revision": human["revision"] if human else None,
        "excluded": exclusion is not None,
        "exclusion_reason": exclusion["value"]["reason"] if exclusion else None,
        "exclusion_revision": exclusion["revision"] if exclusion else None,
        "experience": {"kind": experience["value"]["kind"], "value": experience["value"]["value"], "revision": experience["revision"]} if experience else None,
        "kind_revisions": {kind: item["revision"] for kind, item in edits.items()},
        "language_material": {"evidence_available": target is not None, "excluded": exclusion is not None, "admission": "not_decided"},
        "ranking_evaluation": {"evidence_eligible": eligible, "reason": None if eligible else "complete_scoped_observed_target_required_and_no_retraction_or_exclusion", "observed_choice": choice},
        "corrected_target_membership": "not_asserted" if human and human["kind"] == "correct" else "not_applicable",
        "objective_correctness_proof": False, "host_persistence_proof": False, "ranking_benefit": False,
    }
    if private:
        result["private_values"] = {"effective_target": target, "observed_target": observed, "experience_note": experience["value"]["note"] if experience else None}
    return result


def encode_cursor(value):
    return "a1." + base64.urlsafe_b64encode(canonical_bytes(value)).decode("ascii")


def decode_cursor(value):
    if not isinstance(value, str) or not value.startswith("a1.") or len(value) > 2048:
        raise InterfaceError("invalid_request")
    try:
        return json.loads(base64.b64decode(value[3:], altchars=b"-_", validate=True))
    except (ValueError, UnicodeError):
        raise InterfaceError("invalid_request")
