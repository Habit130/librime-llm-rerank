"""Collector-owned streaming snapshots, durable jobs and explicit atomic restoration.

The non-rollback authority is the only serving pointer. Immutable backup bytes,
mutable restored generations and replaced content have separate registered owners.
Adapters pass plans; they never resolve paths or implement transaction semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import threading

from archive import annotations, datasets
from archive.interface import CONTENT_VERSION, ERROR_MESSAGES, InterfaceError, canonical_bytes
from archive.management_authority import Authority, VERSION
from archive import management_io as io
from archive.querying import QUERY_VERSION
from archive.safety import UnsafeRoot, safe_token

CORE = ("observations.jsonl", "quarantine.jsonl", "state.json", "annotation-identity.json",
        "annotation-state.json", "annotations.jsonl")
MAX_OBSERVATIONS = 65536
MAX_ANNOTATIONS = 65536
LINE = 131072
EXCLUDED = {
    "unpublished_queue_and_crash_tail": "not_published_not_reconstructable",
    "runtime_sockets_pids_locks_logs": "runtime_not_archive_content",
    "rebuildable_caches": "derived_not_source",
    "legacy_facts_semantic_traces_old_datasets": "separate_domain",
    "models_tokenizers_unrelated_files": "outside_new_archive_scope",
    "other_backup_and_retained_payloads": "no_recursive_backup",
    "source_registration_and_fence_authority": "current_nonrollback_authority_not_restored",
    "capture_policy": "current_desired_policy_preserved_not_restored",
}


def code_identity():
    return io.digest({name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                      for name in ("management.py", "management_authority.py", "management_io.py",
                                   "collector.py", "annotations.py", "datasets.py", "querying.py", "interface.py")})


class Management:
    def __init__(self, collector):
        self.c = collector
        self.authority = Authority(collector)
        self.lock = threading.RLock()
        self.active = None
        self.thread = None
        self.cancel = threading.Event()
        self.uncertain = set()
        # In-process finite test seam. Never set by ordinary requests/Adapters.
        self.hook = lambda phase: None

    @property
    def root(self):
        return self.authority.managed / "jobs"

    def prepare(self):
        self.authority.seed_history()
        for name in self.ids():
            job = self.load(name)
            if name in self.authority.value["committed"]:
                # The irreversible marker wins over a lost final status reply.
                job.update(state="succeeded", phase="committed", reason=None)
                for entry in job["registry"]:
                    if entry["role"] == "staging":
                        entry["state"] = "active_initial_snapshot_checksum"
                    elif entry["role"] == "retained_current":
                        entry["state"] = "retained"
                self.save(job)
                self.cleanup(job)
            elif job["state"] in ("pending", "running"):
                job.update(state="unknown", reason="interrupted_before_commit")
                self.audit(job)
                self.save(job)

    def ids(self):
        io.directory(self.root)
        result = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                if len(result) == io.MAX_JOBS:
                    raise InterfaceError("management_bound")
                io.identifier(entry.name)
                io.directory(self.root / entry.name)
                result.append(entry.name)
        return sorted(result)

    def path(self, job_id):
        io.identifier(job_id)
        io.directory(self.root)
        path = self.root / job_id
        if not os.path.lexists(path):
            raise InterfaceError("not_found")
        return io.directory(path)

    def load(self, job_id):
        path = self.path(job_id) / "job.json"
        if not os.path.lexists(path):
            # Reservation preceded copying. No plaintext is written before this
            # descriptor, so an interrupted mkdir is an owned empty reservation.
            with os.scandir(path.parent) as entries:
                if any(entry.name != "job.json.pending" for entry in entries):
                    raise InterfaceError("management_incomplete")
            return {"version": VERSION, "job_id": job_id, "request": None,
                    "request_digest": None, "state": "unknown", "phase": "reserved",
                    "reason": "interrupted_before_ack", "progress_bytes": 0,
                    "progress_files": 0, "registry": [], "cleanup": "not_started"}
        job = io.read_json(path)
        if job.get("version") != VERSION:
            raise InterfaceError("management_unsupported")
        if job.get("job_id") != job_id or job.get("state") not in ("pending", "running", "succeeded", "failed", "cancelled", "unknown"):
            raise InterfaceError("management_corrupt")
        if job.get("phase") not in ("reserved", "copying", "ready_to_switch", "committed") or job.get("reason") not in (None, "interrupted_before_ack", "interrupted_before_commit", *ERROR_MESSAGES):
            raise InterfaceError("management_corrupt")
        request = job.get("request")
        if request is not None and (not isinstance(request, dict) or not isinstance(request.get("plan"), dict)):
            raise InterfaceError("management_corrupt")
        if request is not None and io.digest(request) != job.get("request_digest"):
            raise InterfaceError("management_corrupt")
        if request is not None and request.get("kind") not in ("backup", "restore"):
            raise InterfaceError("management_corrupt")
        registry = job.get("registry")
        if not isinstance(registry, list) or len(registry) > io.MAX_FILES * 2 + 2:
            raise InterfaceError("management_bound")
        if any(not isinstance(item, dict) for item in registry):
            raise InterfaceError("management_corrupt")
        if any(type(job.get(name)) is not int or not 0 <= job[name] <= io.MAX_BYTES for name in ("progress_bytes", "progress_files")):
            raise InterfaceError("management_corrupt")
        if job.get("cleanup") not in ("not_started", "pending", "retained_current_registered", "confirmed_core_discarded_datasets_retained", "incomplete_registered_residuals"):
            raise InterfaceError("management_corrupt")
        expected = {}
        if request is not None:
            content = request["plan"] if request["kind"] == "backup" else request["plan"]["backup_plan"]
            prefix = "backup" if request["kind"] == "backup" else "restored"
            for item in content["files"]:
                expected[prefix + "/" + item["path"]] = ("backup" if prefix == "backup" else "staging", content["frontier"])
            expected[prefix + "/manifest.json"] = (prefix + "_manifest", content["frontier"])
            if prefix == "restored":
                if request.get("retention") not in ("retain-current", "discard-replaced-current"):
                    raise InterfaceError("management_corrupt")
                for item in request["plan"]["current_plan"]["retention_files"]:
                    expected["replaced/" + item["path"]] = ("retained_current" if request["retention"] == "retain-current" else "replaced_pending_discard", request["plan"]["current_plan"]["frontier"])
        if len({item.get("path") for item in registry}) != len(registry) or {item.get("path") for item in registry} != set(expected):
            raise InterfaceError("management_corrupt")
        for item in registry:
            if not isinstance(item, dict) or set(item) != {"owner", "path", "role", "state", "size", "sha256", "dependencies"} or item["owner"] != job_id:
                raise InterfaceError("management_corrupt")
            io.relative(item["path"])
            if (item["role"], item["dependencies"]) != expected[item["path"]] or item["state"] not in ("reserved", "published", "incomplete", "not_created", "active_initial_snapshot_checksum", "retained", "replaced_pending_discard", "discarded", "retained_source_unavailable"):
                raise InterfaceError("management_corrupt")
            if item["size"] is not None and (type(item["size"]) is not int or not 0 <= item["size"] <= io.MAX_BYTES):
                raise InterfaceError("management_corrupt")
            if item["sha256"] is not None:
                io.identifier(item["sha256"])
        return job

    def save(self, job):
        io.publish(self.path(job["job_id"]) / "job.json", job)

    def _frontier(self):
        c = self.c
        with c._annotations.lock:
            c._annotations._healthy()
            with c._lock:
                if c._transition or c._queue or c._publishing_units or c._state["storage_failure"]:
                    raise InterfaceError("management_busy")
                state = dict(c._state)
                policy_revision = c._policy["revision"]
            annotation = c._annotations._manifest()
        with c._datasets.lock:
            if c._datasets.active is not None:
                raise InterfaceError("management_busy")
            jobs = [(name, {**c._datasets.load(name), "state": "unknown"} if name in c._datasets.uncertain else c._datasets.load(name)) for name in c._datasets.ids()]
        return state, annotation, policy_revision, jobs

    def preview(self, ignore_job=None):
        c = self.c
        if self.active is not None and self.active != ignore_job:
            raise InterfaceError("management_busy")
        managed = []
        for job_id in self.ids():
            if job_id != ignore_job:
                job = self.load(job_id)
                managed.append({"job_id": job_id, "state": job["state"], "request_digest": job["request_digest"],
                                "registered_copies": len(job["registry"]), "cleanup": job["cleanup"]})
        # Snapshot the tiny authority/frontiers; scans run without admission locks.
        with c._content_gate:
            state, annotation, revision, jobs = self._frontier()
            generation = self.authority.value["generation"]
            content_root = Path(c.content_root)
        if state["durable_seq"] > MAX_OBSERVATIONS or annotation["revision"] > MAX_ANNOTATIONS:
            raise InterfaceError("management_bound")
        state.pop("management_namespace", None)
        generated = {
            "state.json": {**state, "clean_stop": True},
            "annotation-state.json": annotation,
            "annotation-identity.json": {"version": annotations.ANNOTATION_VERSION, "archive_id": annotation["archive_id"]},
        }
        files = []
        retention_files = []
        for name in CORE:
            physical = io.measure(content_root / name)
            retention_files.append({"path": name, **physical})
            if name in generated:
                raw = canonical_bytes(generated[name])
                entry = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            else:
                length = state["durable_offset"] if name == "observations.jsonl" else state["quarantine_bytes"] if name == "quarantine.jsonl" else annotation["offset"]
                entry = io.measure(content_root / name, length)
                if physical["size"] != length:
                    raise InterfaceError("management_busy")
            files.append({"path": name, **entry})
        excluded_datasets = []
        for name, job in jobs:
            if job["state"] != "succeeded":
                # Every registered incomplete content copy is explicitly excluded.
                copies = []
                for item in job["registry"]:
                    path = c._datasets.path(name) / item["path"]
                    copies.append({"path": item["path"], "lifecycle": item["state"],
                                   **(io.measure(path) if os.path.lexists(path) else {"size": 0, "sha256": None})})
                excluded_datasets.append({"job_id": name, "state": job["state"], "copies": copies})
                continue
            pair = job["request"]["snapshot"]
            if pair["archive_id"] != annotation["archive_id"] or pair["as_of_durable_seq"] > state["durable_seq"] or pair["annotation_revision"] > annotation["revision"]:
                raise InterfaceError("management_unavailable")
            c._datasets.manifest(job)
            for filename in ("job.json", "manifest.json", *datasets.FILES):
                files.append({"path": "datasets/" + name + "/" + filename,
                              **io.measure(c._datasets.path(name) / filename)})
                retention_files.append(dict(files[-1]))
        if len(files) > io.MAX_FILES or sum(f["size"] for f in files) > io.MAX_BYTES:
            raise InterfaceError("management_bound")
        frontier = {"archive_id": annotation["archive_id"], "durable_seq": state["durable_seq"],
                    "durable_offset": state["durable_offset"], "annotation_revision": annotation["revision"],
                    "annotation_chain": annotation["chain"], "serving_generation": generation,
                    "collector_epoch": state["collector_epoch"], "policy_revision": revision,
                    "dataset_frontier": io.digest([(name, job["request_digest"], job["state"]) for name, job in jobs]),
                    "managed_registry_frontier": io.digest(managed)}
        plan = {"version": VERSION, "content_version": CONTENT_VERSION, "query_version": QUERY_VERSION,
                "annotation_version": annotations.ANNOTATION_VERSION, "dataset_version": datasets.VERSION,
                "code_identity": code_identity(), "frontier": frontier, "files": files,
                "generated": generated, "retention_files": retention_files,
                "exclusions": EXCLUDED, "excluded_dataset_copies": excluded_datasets,
                "excluded_managed_copies": managed,
                "counts": {"observations": state["durable_seq"], "annotation_revisions": annotation["revision"],
                           "datasets": sum(j["state"] == "succeeded" for _, j in jobs), "files": len(files),
                           "bytes": sum(f["size"] for f in files), "quarantine_bytes": state["quarantine_bytes"]}}
        # Recheck after disk scans. No mixed frontier is accepted as a preview.
        with c._content_gate:
            current, current_annotation, current_revision, current_jobs = self._frontier()
            if (current["durable_seq"], current_annotation, current_revision, self.authority.value["generation"],
                [(n, j["request_digest"], j["state"]) for n, j in current_jobs]) != (
                    state["durable_seq"], annotation, revision, generation,
                    [(n, j["request_digest"], j["state"]) for n, j in jobs]):
                raise InterfaceError("management_stale")
        return {"plan": plan, "plan_identity": io.digest(plan), "scope": "published_new_archive_including_quarantine_and_successful_datasets",
                "bounds": self.bounds(), "content_included": False}

    def bounds(self):
        return {"chunk_bytes": io.CHUNK, "document_bytes": io.DOCUMENT, "files": io.MAX_FILES,
                "copy_bytes": io.MAX_BYTES, "jobs": io.MAX_JOBS, "page": io.PAGE,
                "observations": MAX_OBSERVATIONS, "annotation_revisions": MAX_ANNOTATIONS,
                **self.authority.summary()}

    def _entry(self, job_id, path, role, dependency, expected=None):
        expected = expected or {"size": None, "sha256": None}
        return {"owner": job_id, "path": path, "role": role, "state": "reserved",
                "size": expected["size"], "sha256": expected["sha256"], "dependencies": dependency}

    def _request_job(self, body, kind):
        if self.c._stop:
            raise InterfaceError("shutdown")
        operation = body.get("operation_id")
        if safe_token(operation) is None or not isinstance(body.get("plan"), dict):
            raise InterfaceError("invalid_request")
        request = {"kind": kind, "plan": body["plan"]}
        if kind == "restore":
            choice = body.get("retention")
            if choice not in ("retain-current", "discard-replaced-current") or body.get("confirm") is not True:
                raise InterfaceError("invalid_request")
            request["retention"] = choice
        job_id = io.digest({"namespace": self.authority.value["namespace"], "operation_id": operation})
        with self.lock:
            if job_id in self.ids():
                job = self.load(job_id)
                if job["request"] is None:
                    return {**self.summary(job), "replayed": True}
                if job["request_digest"] != io.digest(request):
                    raise InterfaceError("management_operation_conflict")
                return {**self.summary(job), "replayed": True}
            if self.active is not None or self.c._datasets.active is not None:
                raise InterfaceError("management_busy")
            if len(self.ids()) >= io.MAX_JOBS:
                raise InterfaceError("management_bound")
            # Supplied plans never become filesystem authority. Recompute before
            # allocating/copying and compare the whole collector-generated plan.
            expected = self.preview()["plan"] if kind == "backup" else self.restore_preview(body["plan"].get("backup_id"))["plan"]
            if body["plan"] != expected:
                raise InterfaceError("management_stale")
            required = expected["counts"]["bytes"] if kind == "backup" else expected["backup_counts"]["bytes"]
            if shutil.disk_usage(self.root).free < required + io.DOCUMENT:
                raise InterfaceError("management_capacity")
            path = io.mkdir(self.root / job_id)
            prefix = "backup" if kind == "backup" else "restored"
            plan = expected if kind == "backup" else expected["backup_plan"]
            registry = [self._entry(job_id, prefix + "/" + item["path"], "backup" if kind == "backup" else "staging", plan["frontier"], item) for item in plan["files"]]
            registry.append(self._entry(job_id, prefix + "/manifest.json", prefix + "_manifest", plan["frontier"]))
            job = {"version": VERSION, "job_id": job_id, "request": request, "request_digest": io.digest(request),
                   "state": "pending", "phase": "reserved", "reason": None, "progress_bytes": 0,
                   "progress_files": 0, "registry": registry, "cleanup": "not_started"}
            if kind == "restore":
                for item in expected["current_plan"]["retention_files"]:
                    # Retention transfers ownership of existing bytes; no hidden
                    # rollback copy or data amplification is created.
                    registry.append(self._entry(job_id, "replaced/" + item["path"], "retained_current" if request["retention"] == "retain-current" else "replaced_pending_discard", expected["current_plan"]["frontier"], item))
            self.save(job)  # durable acknowledgement + full copy reservation
            io.mkdir(path / prefix)
            self.active = job_id
            self.cancel.clear()
            self.thread = threading.Thread(target=self.run, args=(job_id,), name="archive-management", daemon=True)
            self.thread.start()
            return {**self.summary(job), "replayed": False, "acknowledgement": "durable_request_not_completion"}

    def summary(self, job):
        return {"management_version": VERSION, "job_id": job["job_id"], "kind": (job.get("request") or {}).get("kind"),
                "state": "unknown" if job["job_id"] in self.uncertain else job["state"],
                "phase": job["phase"], "reason": job["reason"], "request_digest": job["request_digest"],
                "progress_bytes": job["progress_bytes"], "progress_files": job["progress_files"],
                "cleanup": job["cleanup"], "registry_count": len(job["registry"]),
                "irreversible": job["state"] == "succeeded" or job["job_id"] in self.authority.value["committed"],
                "producer_availability": self.authority.summary(), "content_included": False}

    def _paths(self, path, name):
        parts = io.relative(name)
        for part in parts[:-1]:
            child = path / part
            if not os.path.lexists(child):
                io.mkdir(child)
            path = io.directory(child)
        return path / parts[-1]

    def _progress(self, job, count):
        if self.cancel.is_set() or self.c._stop:
            raise InterfaceError("management_cancelled")
        job["progress_bytes"] += count
        with self.lock:
            self.save(job)
        self.hook("copy_chunk")

    def run(self, job_id):
        try:
            with self.lock:
                job = self.load(job_id)
                job.update(state="running", phase="copying")
                self.save(job)
            self.hook("before_copy")
            kind = job["request"]["kind"]
            plan = job["request"]["plan"]
            if kind == "backup":
                source = Path(self.c.content_root)
                content = plan
                target = self.path(job_id) / "backup"
            else:
                source = self.path(plan["backup_id"]) / "backup"
                content = plan["backup_plan"]
                target = self.path(job_id) / "restored"
            for item in content["files"]:
                if self.cancel.is_set():
                    raise InterfaceError("management_cancelled")
                destination = self._paths(target, item["path"])
                if kind == "backup" and item["path"] in content["generated"]:
                    io.write_new(destination, canonical_bytes(content["generated"][item["path"]]))
                    self._progress(job, item["size"])
                else:
                    io.copy(io.resolve(source, item["path"]), destination, item, lambda count: self._progress(job, count))
                job["progress_files"] += 1
                with self.lock:
                    self.save(job)
            manifest = {"version": VERSION, "plan": content, "content_identity": io.digest(content)}
            io.write_new(target / "manifest.json", canonical_bytes(manifest))
            self.hook("after_files")
            self._verify_content(target, content)
            if kind == "restore":
                self._restore_switch(job)
            else:
                with self.lock:
                    if self.cancel.is_set() or self.c._stop:
                        raise InterfaceError("management_cancelled")
                    self.hook("before_backup_commit")
                    self.audit(job)
                    for entry in job["registry"]:
                        entry["state"] = "published"
                    job.update(state="succeeded", phase="committed")
                    self.save(job)  # backup publication + registry commit
                    self.hook("after_backup_commit")
        except BaseException as exc:
            try:
                with self.lock:
                    job = self.load(job_id)
                    committed = job["state"] == "succeeded" or job_id in self.authority.value["committed"]
                    if committed or self.authority.failed:
                        self.uncertain.add(job_id)
                    else:
                        job.update(state="cancelled" if isinstance(exc, InterfaceError) and exc.code == "management_cancelled" else "failed",
                                   reason=exc.code if isinstance(exc, InterfaceError) else "unsafe_root" if isinstance(exc, UnsafeRoot) else "storage_failure")
                        self.audit(job)
                        self.save(job)
            except (OSError, ValueError, KeyError, TypeError, InterfaceError, UnsafeRoot):
                self.uncertain.add(job_id)
        finally:
            with self.lock:
                self.active = None

    def audit(self, job):
        base = self.path(job["job_id"])
        for entry in job["registry"]:
            if entry["path"].startswith("replaced/"):
                continue
            path = io.optional(base, entry["path"])
            if path is not None and os.path.lexists(path):
                entry.update(io.measure(path))
                entry["state"] = "incomplete" if job["state"] != "succeeded" else "published"
            else:
                entry.update(state="not_created", size=0, sha256=None)

    def verify(self, job_id):
        job = self.load(job_id)
        if (job.get("request") or {}).get("kind") != "backup" or job["state"] != "succeeded" or job_id in self.uncertain:
            raise InterfaceError("management_incomplete")
        target = self.path(job_id) / "backup"
        plan = job["request"]["plan"]
        manifest = io.read_json(target / "manifest.json")
        if manifest.get("version") != VERSION:
            raise InterfaceError("management_unsupported")
        if manifest != {"version": VERSION, "plan": plan, "content_identity": io.digest(plan)}:
            raise InterfaceError("management_corrupt")
        for entry in job["registry"]:
            if entry["state"] != "published" or io.measure(io.resolve(self.path(job_id), entry["path"])) != {"size": entry["size"], "sha256": entry["sha256"]}:
                raise InterfaceError("management_tampered")
        self._verify_content(target, plan)
        return {"verified": True, "backup_id": job_id, "content_identity": io.digest(plan),
                "verification": "self_contained_source_annotation_dataset_semantics_and_registered_bytes",
                "counts": plan["counts"], "content_included": False}

    def _verify_content(self, target, plan):
        if plan.get("version") != VERSION or plan.get("content_version") != CONTENT_VERSION or plan.get("query_version") != QUERY_VERSION or plan.get("annotation_version") != annotations.ANNOTATION_VERSION or plan.get("dataset_version") != datasets.VERSION or plan.get("code_identity") != code_identity():
            raise InterfaceError("management_unsupported")
        files = plan.get("files")
        if not isinstance(files, list) or len(files) > io.MAX_FILES or len({f["path"] for f in files}) != len(files):
            raise InterfaceError("management_bound")
        if sum(f["size"] for f in files) > io.MAX_BYTES:
            raise InterfaceError("management_bound")
        expected_names = set(CORE)
        job_ids = set()
        for item in files:
            parts = io.relative(item["path"])
            if len(parts) == 3 and parts[0] == "datasets" and parts[2] in ("job.json", "manifest.json", *datasets.FILES):
                job_ids.add(io.identifier(parts[1]))
            elif item["path"] not in CORE:
                raise InterfaceError("management_corrupt")
            if io.measure(io.resolve(target, item["path"])) != {"size": item["size"], "sha256": item["sha256"]}:
                raise InterfaceError("management_tampered")
        expected_names |= {"datasets/" + name + "/" + filename for name in job_ids for filename in ("job.json", "manifest.json", *datasets.FILES)}
        if {f["path"] for f in files} != expected_names:
            raise InterfaceError("management_incomplete")
        # Build a read-only semantic source. No Collector.prepare, truncation,
        # reconciliation, policy, source registration or observation repair.
        from archive.collector import Collector
        proxy = Collector(str(target), str(target / "unused.sock"), self.c.limits, auto_checkpoint=False)
        proxy._state = io.read_json(target / "state.json")
        store = proxy._annotations
        identity = io.read_json(target / "annotation-identity.json")
        manifest = io.read_json(target / "annotation-state.json")
        if identity != {"version": annotations.ANNOTATION_VERSION, "archive_id": plan["frontier"]["archive_id"]}:
            raise InterfaceError("management_corrupt")
        store.archive_id = identity["archive_id"]
        count, identities = 0, set()
        with io.open_read(target / "observations.jsonl") as stream:
            while True:
                offset = stream.tell()
                raw = stream.readline(LINE + 1)
                if not raw:
                    break
                count += 1
                if len(raw) > LINE or not raw.endswith(b"\n") or count > MAX_OBSERVATIONS:
                    raise InterfaceError("management_bound")
                row = json.loads(raw)
                if row.get("record_version") != 1 or type(row["record_version"]) is not int:
                    raise InterfaceError("management_unsupported")
                if row.get("durable_seq") != count or safe_token(row.get("source_instance_id")) is None or not annotations.integer(row.get("source_local_sequence")):
                    raise InterfaceError("management_corrupt")
                key = (row["source_instance_id"], row["source_local_sequence"])
                if key in identities and row["observation_kind"] != "loss_notice":
                    raise InterfaceError("management_corrupt")
                if row["observation_kind"] != "loss_notice":
                    identities.add(key)
                # Source bytes/digests are immutable; no host persistence upgrade.
                if row.get("host_persistence_proof") is not False:
                    raise InterfaceError("management_corrupt")
                proxy._remember(row, offset, len(raw))
            offset = stream.tell()
        if count != plan["frontier"]["durable_seq"] or offset != proxy._state["durable_offset"] or offset != proxy._state["durable_bytes"] or count != proxy._state["durable_seq"]:
            raise InterfaceError("management_corrupt")
        with io.open_read(target / "annotations.jsonl") as stream:
            while True:
                offset = stream.tell()
                raw = stream.readline(annotations.LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > annotations.LINE_BYTES or not raw.endswith(b"\n") or store.revision >= MAX_ANNOTATIONS:
                    raise InterfaceError("management_bound")
                row = json.loads(raw)
                store._validate_row(row)
                proxy._annotation_source(row["semantic"]["source_reference"], count, include_choice=False)
                store._remember(row, offset, len(raw))
            store.offset = stream.tell()
        if store._manifest() != manifest or store.revision != plan["frontier"]["annotation_revision"] or store.chain != plan["frontier"]["annotation_chain"]:
            raise InterfaceError("management_corrupt")
        if io.regular(target / "quarantine.jsonl").st_size != proxy._state["quarantine_bytes"]:
            raise InterfaceError("management_corrupt")
        for name in sorted(job_ids):
            proxy._datasets.verify(name)

    def restore_preview(self, backup_id):
        verified = self.verify(backup_id)
        backup = self.load(backup_id)["request"]["plan"]
        current = self.preview()["plan"]
        plan = {"version": VERSION, "backup_id": backup_id, "backup_identity": verified["content_identity"],
                "backup_plan": backup, "backup_counts": backup["counts"], "current_plan": current,
                "serving_generation": self.authority.value["generation"],
                "retention_choices": ["retain-current", "discard-replaced-current"],
                "replaced_content": "confirmed_new_archive_core_only",
                "retained_datasets": "independent_existing_dataset_copies_remain_registered_source_may_be_unavailable",
                "producer_recovery": "producer_recreation_new_source_identity_required",
                "restored_dataset_default_training_candidate": False}
        return {"plan": plan, "plan_identity": io.digest(plan), "content_included": False}

    def _restore_switch(self, job):
        c = self.c
        # All content readers/writers use this gate. Producer admission does not
        # acquire it: it sees a bounded refusal under the short state lock.
        if not c._content_gate.acquire(False):
            raise InterfaceError("management_busy")
        policy_locked = publication_locked = False
        try:
            if not c._policy_lock.acquire(False):
                raise InterfaceError("management_busy")
            policy_locked = True
            if not c._publication_mutex.acquire(False):
                raise InterfaceError("management_busy")
            publication_locked = True
            with c._datasets.lock:
                if c._datasets.active is not None:
                    raise InterfaceError("management_busy")
            # Reject intervening input/edits/policy/inventory before the switch.
            if self.preview(ignore_job=job["job_id"])["plan"] != job["request"]["plan"]["current_plan"]:
                raise InterfaceError("management_stale")
            with self.authority.lock:
                with c._lock:
                    if c._queue or c._publishing_units or c._transition:
                        raise InterfaceError("management_busy")
                    c._transition = True
                if self.cancel.is_set() or c._stop:
                    raise InterfaceError("management_cancelled")
                self.hook("before_restore_commit")
                old_root = Path(c.content_root)
                job["old_content"] = str(old_root.relative_to(Path(c.root)))
                self.audit(job)
                job.update(phase="ready_to_switch", cleanup="pending")
                self.save(job)
                self.authority.switch(job["job_id"])
                self.hook("after_restore_commit")
                c._load_state()
                c._state["management_namespace"] = self.authority.value["namespace"]
                c._break_continuity_locked("historical_restore_producer_recreation_required")
                c._rebuild_index()
                c._annotations.prepare()
                c._datasets.prepare()
                c._persist_state()
                for entry in job["registry"]:
                    entry["state"] = "active_initial_snapshot_checksum" if entry["role"] == "staging" else "retained" if entry["role"] == "retained_current" else "replaced_pending_discard" if entry["role"] == "replaced_pending_discard" else "published"
                job.update(state="succeeded", phase="committed")
                self.save(job)
            self.cleanup(job)
        except BaseException:
            if self.authority.failed or job["job_id"] in self.authority.value["committed"]:
                # No unrequested rollback or mixed successful serving after an
                # uncertain/failed post-switch load. Restart consults authority.
                c._maintenance_unavailable = True
            raise
        finally:
            with c._lock:
                c._transition = False
            if publication_locked:
                c._publication_mutex.release()
            if policy_locked:
                c._policy_lock.release()
            c._content_gate.release()

    def cleanup(self, job):
        if (job.get("request") or {}).get("kind") != "restore" or job["job_id"] not in self.authority.value["committed"]:
            return
        if job["request"]["retention"] == "retain-current":
            job["cleanup"] = "retained_current_registered"
            self.save(job)
            return
        # Only the exact confirmed six core files are discard-authorized.
        # Dataset bytes, backups, roots and all unrelated files remain untouched.
        old = Path(self.c.root)
        relative = job.get("old_content")
        if relative != ".":
            parts = io.relative(relative)
            if len(parts) != 4 or parts[0:2] != ["management", "jobs"] or parts[3] != "restored":
                raise InterfaceError("management_corrupt")
            io.identifier(parts[2])
            old = io.directory(old / relative)
        if old == Path(self.c.content_root):
            raise InterfaceError("management_corrupt")
        try:
            self.hook("before_cleanup")
            for name in CORE:
                path = old / name
                if os.path.lexists(path):
                    io.regular(path)
                    os.unlink(path)
                    io.sync(old)
                for entry in job["registry"]:
                    if entry["path"] == "replaced/" + name:
                        entry["state"] = "discarded"
            # Independently retained dataset copies are never implicitly erased.
            for entry in job["registry"]:
                if entry["path"].startswith("replaced/datasets/"):
                    entry["state"] = "retained_source_unavailable"
            job["cleanup"] = "confirmed_core_discarded_datasets_retained"
        except (OSError, UnsafeRoot):
            job["cleanup"] = "incomplete_registered_residuals"
        self.save(job)

    def call(self, body):
        if self.authority.failed or self.c._maintenance_unavailable:
            raise InterfaceError("management_authority_unavailable")
        allowed = {"management_version", "action", "job_id", "operation_id", "plan", "retention", "confirm", "after", "page_size"}
        if set(body) - allowed or body.get("management_version") != VERSION:
            raise InterfaceError("management_unsupported" if body.get("management_version") != VERSION else "invalid_request")
        action = body.get("action")
        if action == "preview":
            return self.preview()
        if action == "create":
            return self._request_job(body, "backup")
        if action == "restore_preview":
            return self.restore_preview(body.get("job_id"))
        if action == "restore_confirm":
            return self._request_job(body, "restore")
        if action == "availability":
            return self.authority.summary()
        if action in ("list", "registry"):
            after, size = body.get("after", 0), body.get("page_size", 20)
            if type(after) is not int or after < 0 or type(size) is not int or not 1 <= size <= io.PAGE:
                raise InterfaceError("management_bound")
            if action == "list":
                ids = self.ids()
                return {"jobs": [self.summary(self.load(name)) for name in ids[after:after + size]],
                        "next_after": after + size if after + size < len(ids) else None}
            job = self.load(body.get("job_id"))
            rows = job["registry"]
            return {"registry": rows[after:after + size], "next_after": after + size if after + size < len(rows) else None,
                    "old_content": job.get("old_content"), "cleanup": job["cleanup"]}
        job_id = body.get("job_id")
        if action == "verify":
            return self.verify(job_id)
        if action == "status":
            with self.lock:
                return self.summary(self.load(job_id))
        if action == "cancel":
            with self.lock:
                job = self.load(job_id)
                if job["state"] == "succeeded" or job_id in self.authority.value["committed"]:
                    raise InterfaceError("management_committed")
                if self.active == job_id:
                    self.cancel.set()
                elif job["state"] in ("pending", "unknown"):
                    job.update(state="cancelled", reason="management_cancelled")
                    self.save(job)
                return self.summary(job)
        raise InterfaceError("invalid_request")
