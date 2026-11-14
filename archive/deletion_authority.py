"""Bounded, content-free removal authority outside historical restore payloads.

This module never removes a file, rewrites source rows, or fences a producer.
The collector's transaction owns those actions. Capture tombstones are permanent
within the owner namespace: there is no eviction, reset, or text-based selection.
"""

from __future__ import annotations

import os
from pathlib import Path
import threading
import uuid

from archive import management_io as io
from archive.interface import InterfaceError, canonical_bytes
from archive.safety import safe_token

VERSION = "input-archive-deletion-v1"
MAX_CAPTURES = 65536
MAX_BRIDGES = 65536
MAX_BYTES = 8 * 1048576
MAX_JOBS = 128


def capture_key(source, sequence):
    if safe_token(source) is None or type(sequence) is not int or not 0 <= sequence < 1 << 63:
        raise InterfaceError("invalid_request")
    return io.digest({"source_instance_id": source, "source_local_sequence": sequence})


class RemovalAuthority:
    def __init__(self, collector):
        self.c = collector
        self.root = Path(collector.root)
        self.directory = self.root / "deletion"
        self.marker = self.root / "deletion-namespace.json"
        self.control = self.directory / "control.json"
        self.lock = threading.RLock()
        self.value = None
        self.failed = False

    def prepare(self):
        try:
            self._prepare()
        except (OSError, ValueError, KeyError, TypeError):
            self.failed = True
            raise InterfaceError("deletion_authority_unavailable") from None

    def _prepare(self):
        present = os.path.lexists(self.directory)
        marked = os.path.lexists(self.marker)
        anchor = self.c._policy.get("deletion_namespace")
        if present != marked:
            raise InterfaceError("deletion_authority_unavailable")
        if not present:
            state = Path(self.c.state_path)
            if anchor is not None or os.path.lexists(state) and io.read_json(state).get("deletion_namespace"):
                raise InterfaceError("deletion_authority_unavailable")
            namespace = uuid.uuid4().hex
            io.publish(self.marker, {"version": VERSION, "namespace": namespace})
            io.mkdir(self.directory)
            io.mkdir(self.directory / "jobs")
            self._write({"version": VERSION, "namespace": namespace,
                         "management_namespace": self.c._management.authority.value["namespace"],
                         "revision": 0, "captures": {}, "bridges": {}, "committed": {}})
        io.directory(self.directory)
        marker = io.read_json(self.marker)
        value = io.read_json(self.control)
        if marker.get("version") != VERSION or value.get("version") != VERSION:
            raise InterfaceError("deletion_unsupported")
        if set(marker) != {"version", "namespace"}:
            raise InterfaceError("deletion_authority_unavailable")
        io.identifier(marker["namespace"], 32)
        self.validate(value)
        if value["namespace"] != marker["namespace"] or anchor not in (None, value["namespace"]):
            raise InterfaceError("deletion_authority_unavailable")
        self.value = value
        if anchor is None:
            self.c._policy["deletion_namespace"] = value["namespace"]
            self.c._write_policy()

    def validate(self, value):
        if not isinstance(value, dict) or set(value) != {"version", "namespace", "management_namespace", "revision", "captures", "bridges", "committed"}:
            raise InterfaceError("deletion_authority_unavailable")
        if value["version"] != VERSION:
            raise InterfaceError("deletion_unsupported")
        io.identifier(value["namespace"], 32)
        if value["management_namespace"] != self.c._management.authority.value["namespace"]:
            raise InterfaceError("deletion_authority_unavailable")
        if type(value["revision"]) is not int or not 0 <= value["revision"] <= MAX_JOBS:
            raise InterfaceError("deletion_authority_unavailable")
        for field, bound in (("captures", MAX_CAPTURES), ("bridges", MAX_BRIDGES), ("committed", MAX_JOBS)):
            if not isinstance(value[field], dict) or len(value[field]) > bound:
                raise InterfaceError("deletion_bound")
        for key, entry in value["captures"].items():
            io.identifier(key)
            if not isinstance(entry, dict) or set(entry) != {"archive_id", "durable_seq", "record_digest"}:
                raise InterfaceError("deletion_authority_unavailable")
            io.identifier(entry["archive_id"], 32)
            io.identifier(entry["record_digest"])
            if type(entry["durable_seq"]) is not int or not 1 <= entry["durable_seq"] < 1 << 63:
                raise InterfaceError("deletion_authority_unavailable")
        for key, entry in value["bridges"].items():
            io.identifier(key)
            if not isinstance(entry, dict) or set(entry) != {"archive_id", "revision", "previous", "chain", "operation_digest", "semantic_hash"}:
                raise InterfaceError("deletion_authority_unavailable")
            io.identifier(entry["archive_id"], 32)
            if type(entry["revision"]) is not int or not 1 <= entry["revision"] < 1 << 63:
                raise InterfaceError("deletion_authority_unavailable")
            for field in ("previous", "chain", "operation_digest", "semantic_hash"):
                io.identifier(entry[field])
            if key != io.digest({field: entry[field] for field in ("archive_id", "revision", "chain")}):
                raise InterfaceError("deletion_authority_unavailable")
        if len(value["committed"]) != value["revision"]:
            raise InterfaceError("deletion_authority_unavailable")
        for job, revision in value["committed"].items():
            io.identifier(job)
            if type(revision) is not int or not 1 <= revision <= value["revision"]:
                raise InterfaceError("deletion_authority_unavailable")
        if set(value["committed"].values()) != set(range(1, value["revision"] + 1)):
            raise InterfaceError("deletion_authority_unavailable")
        if len(canonical_bytes(value)) > MAX_BYTES:
            raise InterfaceError("deletion_bound")

    def _write(self, value):
        self.validate(value)
        try:
            if self.value is not None:
                self.check()
            io.publish(self.control, value)
        except BaseException:
            self.failed = True
            raise
        self.value = value

    def check(self):
        """Management-path verification only; admission never performs I/O."""
        if self.failed or self.value is None:
            raise InterfaceError("deletion_authority_unavailable")
        try:
            marker = io.read_json(self.marker)
            value = io.read_json(self.control)
            self.validate(value)
            if marker != {"version": VERSION, "namespace": self.value["namespace"]} or value != self.value:
                raise InterfaceError("deletion_authority_unavailable")
        except BaseException:
            self.failed = True
            raise

    def removed(self, source, sequence):
        if self.failed or self.value is None:
            raise InterfaceError("deletion_authority_unavailable")
        return capture_key(source, sequence) in self.value["captures"]

    def proposed(self, job_id, references, bridges):
        """Validate every bound and conflict before any removal is authorized."""
        io.identifier(job_id)
        if self.failed or self.value is None:
            raise InterfaceError("deletion_authority_unavailable")
        value = self.value
        if job_id in value["committed"]:
            raise InterfaceError("deletion_operation_conflict")
        captures = dict(value["captures"])
        for ref in references:
            key = capture_key(ref["source_instance_id"], ref["source_local_sequence"])
            entry = {field: ref[field] for field in ("archive_id", "durable_seq", "record_digest")}
            if key in captures and captures[key] != entry:
                raise InterfaceError("deletion_operation_conflict")
            captures[key] = entry
        pruned = dict(value["bridges"])
        for bridge in bridges:
            key = io.digest({field: bridge[field] for field in ("archive_id", "revision", "chain")})
            if key in pruned and pruned[key] != bridge:
                raise InterfaceError("deletion_operation_conflict")
            pruned[key] = dict(bridge)
        result = {**value, "revision": value["revision"] + 1, "captures": captures,
                  "bridges": pruned, "committed": {**value["committed"], job_id: value["revision"] + 1}}
        self.validate(result)
        return result

    def commit(self, job_id, references, bridges, expected_revision):
        with self.lock:
            if self.value["revision"] != expected_revision:
                raise InterfaceError("deletion_stale")
            value = self.proposed(job_id, references, bridges)
            self._write(value)

    def summary(self):
        return {"deletion_version": VERSION, "authority_available": not self.failed,
                "revision": self.value["revision"], "removed_captures": len(self.value["captures"]),
                "pruned_annotation_revisions": len(self.value["bridges"]),
                "capture_bound": MAX_CAPTURES, "annotation_bridge_bound": MAX_BRIDGES,
                "authority_bytes_bound": MAX_BYTES, "job_bound": MAX_JOBS}
