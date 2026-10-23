"""Non-rollback serving pointer and permanent source-incarnation fencing."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import uuid

from archive.interface import InterfaceError
from archive.management_io import directory, digest, identifier, mkdir, publish, read_json, regular
from archive.safety import safe_token

VERSION = "input-archive-management-v1"
MAX_SOURCES = 8192
MAX_AUTHORITY_BYTES = 2 * 1048576


class Authority:
    def __init__(self, collector):
        self.collector = collector
        self.root = Path(collector.root)
        self.managed = self.root / "management"
        self.marker = self.root / "management-namespace.json"
        self.lock = threading.RLock()
        self.value = None
        self.failed = False

    def prepare(self):
        try:
            self._prepare()
        except (OSError, ValueError, TypeError, KeyError):
            raise InterfaceError("management_authority_unavailable") from None

    def _prepare(self):
        existing = os.path.lexists(self.managed)
        marked = os.path.lexists(self.marker)
        if existing != marked:
            raise InterfaceError("management_authority_unavailable")
        if not existing:
            # A surviving state marker detects removal of both authority files.
            state = self.root / "state.json"
            if self.collector._policy.get("management_namespace") or os.path.lexists(state) and read_json(state).get("management_namespace"):
                raise InterfaceError("management_authority_unavailable")
            namespace = uuid.uuid4().hex
            publish(self.marker, {"version": VERSION, "namespace": namespace})
            mkdir(self.managed)
            mkdir(self.managed / "jobs")
            publish(self.managed / "control.json", {"version": VERSION, "namespace": namespace,
                    "generation": 0, "serving_job": None, "sources": {}, "committed": {}})
        directory(self.managed)
        if regular(self.managed / "control.json").st_size > MAX_AUTHORITY_BYTES:
            raise InterfaceError("management_authority_unavailable")
        marker = read_json(self.marker)
        value = read_json(self.managed / "control.json")
        if marker.get("version") != VERSION or value.get("version") != VERSION:
            raise InterfaceError("management_unsupported")
        if set(marker) != {"version", "namespace"} or set(value) != {"version", "namespace", "generation", "serving_job", "sources", "committed"}:
            raise InterfaceError("management_authority_unavailable")
        identifier(marker["namespace"], 32)
        if value["namespace"] != marker["namespace"] or type(value["generation"]) is not int or value["generation"] < 0:
            raise InterfaceError("management_authority_unavailable")
        sources = value["sources"]
        if not isinstance(sources, dict) or len(sources) > MAX_SOURCES:
            raise InterfaceError("management_authority_unavailable")
        for source, generation in sources.items():
            identifier(source)
            if type(generation) is not int or not 0 <= generation <= value["generation"]:
                raise InterfaceError("management_authority_unavailable")
        if not isinstance(value["committed"], dict) or len(value["committed"]) > 128:
            raise InterfaceError("management_authority_unavailable")
        for job, generation in value["committed"].items():
            identifier(job)
            if type(generation) is not int or not 1 <= generation <= value["generation"]:
                raise InterfaceError("management_authority_unavailable")
        serving = value["serving_job"]
        if serving is not None and (identifier(serving) not in value["committed"]):
            raise InterfaceError("management_authority_unavailable")
        if (serving is None) != (value["generation"] == 0):
            raise InterfaceError("management_authority_unavailable")
        self.value = value
        policy_namespace = self.collector._policy.get("management_namespace")
        if policy_namespace is not None and policy_namespace != value["namespace"]:
            raise InterfaceError("management_authority_unavailable")
        self.install_paths()
        if policy_namespace is None:
            # The current policy is outside replaced content. Its namespace
            # anchor survives discard and prevents a missing authority becoming
            # a fresh empty namespace on the supported restart path.
            self.collector._policy["management_namespace"] = value["namespace"]
            self.collector._write_policy()

    def install_paths(self):
        c = self.collector
        serving = self.value["serving_job"]
        content = self.root if serving is None else directory(self.managed / "jobs" / serving / "restored")
        c.content_root = str(content)
        c.observations_path = str(content / "observations.jsonl")
        c.quarantine_path = str(content / "quarantine.jsonl")
        c.state_path = str(content / "state.json")
        from archive.annotations import AnnotationStore
        c._annotations = AnnotationStore(str(content))
        c._datasets.root = content / "datasets"
        c._historical_dataset_ids = set()
        if serving is not None:
            manifest = read_json(content / "manifest.json")
            if manifest.get("version") != VERSION:
                raise InterfaceError("management_unsupported")
            files = manifest["plan"]["files"]
            if not isinstance(files, list) or len(files) > 8192:
                raise InterfaceError("management_bound")
            # Only historical datasets actually included in this restoration;
            # later explicitly created freezes keep their separate semantics.
            for item in files:
                parts = item["path"].split("/")
                if len(parts) == 3 and parts[0] == "datasets" and parts[2] == "job.json":
                    identifier(parts[1])
                    c._historical_dataset_ids.add(parts[1])
        names = ("observations.jsonl", "quarantine.jsonl", "state.json", "annotation-identity.json",
                 "annotation-state.json", "annotations.jsonl")
        for name in names:
            path = content / name
            if os.path.lexists(path):
                regular(path)  # before legacy loaders can truncate/chmod/open
            elif serving is not None:
                raise InterfaceError("management_incomplete")
        observations = content / "observations.jsonl"
        if serving is None and os.path.lexists(observations) and observations.lstat().st_size:
            if any(not os.path.lexists(content / name) for name in ("state.json", "annotation-identity.json", "annotation-state.json", "annotations.jsonl")):
                raise InterfaceError("management_incomplete")

    def _write(self, value):
        from archive.interface import canonical_bytes
        if len(canonical_bytes(value)) > MAX_AUTHORITY_BYTES:
            raise InterfaceError("management_bound")
        try:
            publish(self.managed / "control.json", value)
        except BaseException:
            # replace/fsync ambiguity is never an enabled empty namespace.
            self.failed = True
            raise
        self.value = value

    @staticmethod
    def key(source):
        if safe_token(source) is None:
            raise InterfaceError("invalid_request")
        return digest({"source_instance_id": source})

    def seed_history(self):
        """One supported cutover: historical source IDs are known, never fresh."""
        with self.lock:
            keys = {self.key(row["source_instance_id"]) for row in self.collector._index}
            missing = keys - self.value["sources"].keys()
            if not missing:
                return
            if self.value["generation"] != 0:
                # Restored historical IDs are always fenced, not re-registered.
                generation = self.value["generation"] - 1
            else:
                generation = 0
            if len(missing) + len(self.value["sources"]) > MAX_SOURCES:
                raise InterfaceError("management_bound")
            value = {**self.value, "sources": {**self.value["sources"], **dict.fromkeys(missing, generation)}}
            self._write(value)

    def register(self, source):
        key = self.key(source)
        with self.lock:
            if self.failed:
                raise InterfaceError("management_authority_unavailable")
            if key in self.value["sources"]:
                return self.allowed(source)
            if len(self.value["sources"]) >= MAX_SOURCES:
                raise InterfaceError("management_bound")
            value = {**self.value, "sources": {**self.value["sources"], key: self.value["generation"]}}
            self._write(value)  # durable before any usable enabled policy reply
            return True

    def allowed(self, source):
        if self.failed or self.value is None:
            return False
        return self.value["sources"].get(self.key(source)) == self.value["generation"]

    def refusal(self, source):
        if self.failed:
            return "management_authority_unavailable"
        key = self.key(source)
        return "source_recreation_required" if key in self.value["sources"] else "source_unregistered"

    def summary(self):
        value = self.value
        fenced = sum(g < value["generation"] for g in value["sources"].values())
        return {"management_version": VERSION, "serving_generation": value["generation"],
                "authority_available": not self.failed, "registered_sources": len(value["sources"]),
                "fenced_sources": fenced, "source_bound": MAX_SOURCES,
                "authority_bytes_bound": MAX_AUTHORITY_BYTES,
                "producer_recreation_required": bool(fenced),
                "capture_recovery": "producer_recreation_new_source_identity_required" if fenced else "current_registration_required"}

    def switch(self, job_id):
        """Caller holds lock and collector transition gate. No source is evicted."""
        value = {**self.value, "generation": self.value["generation"] + 1, "serving_job": job_id,
                 "committed": {**self.value["committed"], job_id: self.value["generation"] + 1}}
        self._write(value)  # sole irreversible restore+fence commit point
        self.install_paths()
