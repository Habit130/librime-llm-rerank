"""Collector-owned exact-plan deletion jobs and content-free recovery journal.

No Adapter chooses paths. Preparation writes survivors only, never a rollback
copy. The removal-authority commit is irreversible; interrupted committed jobs
must finish exact-bound replacements/removals before the collector can serve.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import threading
import uuid

from archive import management_io as io
from archive.annotations import AnnotationStore, digest
from archive.deletion_authority import RemovalAuthority, VERSION, MAX_JOBS, capture_key
from archive.deletion_inventory import binding
from archive.deletion_plan import Planner, records
from archive.interface import ERROR_MESSAGES, InterfaceError, canonical_bytes
from archive.safety import UnsafeRoot, safe_token


class Deletion:
    def __init__(self, collector):
        self.c = collector
        self.authority = RemovalAuthority(collector)
        self.lock = threading.RLock()
        self.active = None
        self.thread = None
        self.cancel = threading.Event()
        self.hook = lambda phase: None
        self.uncertain = set()

    @property
    def root(self):
        return self.authority.directory / "jobs"

    def resolve(self, relative):
        path = io.directory(Path(self.c.root))
        if relative == ".":
            return path
        if not isinstance(relative, str) or len(relative) > 768:
            raise InterfaceError("deletion_unknown_lineage")
        parts = relative.split("/")
        if not 1 <= len(parts) <= 8 or any(not part or part in (".", "..") for part in parts):
            raise InterfaceError("deletion_unknown_lineage")
        for part in parts:
            io.relative(part)
        for part in parts[:-1]:
            path = io.directory(path / part)
        return path / parts[-1]

    def ids(self):
        io.directory(self.root)
        result = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                if len(result) >= MAX_JOBS:
                    raise InterfaceError("deletion_bound")
                io.identifier(entry.name)
                io.directory(self.root / entry.name)
                result.append(entry.name)
        return sorted(result)

    def path(self, job_id):
        io.identifier(job_id)
        return io.directory(self.root / job_id)

    def load(self, job_id):
        with self.lock:
            return self._load(job_id)

    def _load(self, job_id):
        job = io.read_json(self.path(job_id) / "job.json")
        if job.get("version") != VERSION:
            raise InterfaceError("deletion_unsupported")
        if job.get("job_id") != job_id or job.get("state") not in ("pending", "running", "succeeded", "failed", "cancelled", "unknown"):
            raise InterfaceError("deletion_authority_unavailable")
        if job.get("plan_identity") != io.digest(job.get("plan")) or job.get("request_digest") != io.digest({"plan_identity": job["plan_identity"], "accept_collateral": True}):
            raise InterfaceError("deletion_authority_unavailable")
        if not isinstance(job.get("registry"), list) or len(job["registry"]) > 4:
            raise InterfaceError("deletion_bound")
        expected = {item["path"]: item for item in job["plan"]["actions"] if item["action"] == "survivor_rewrite"}
        for entry in job["registry"]:
            if set(entry) != {"path", "target", "scope", "state", "size", "sha256"} or entry["target"] not in expected or entry["path"] != io.digest({"target": entry["target"]}) + ".survivor":
                raise InterfaceError("deletion_authority_unavailable")
            if entry["scope"] != job["plan"]["frontier"] or entry["state"] not in ("reserved", "staged", "incomplete", "transferred", "discarded"):
                raise InterfaceError("deletion_authority_unavailable")
        if len({entry["path"] for entry in job["registry"]}) != len(job["registry"]):
            raise InterfaceError("deletion_authority_unavailable")
        if job.get("phase") not in ("acknowledged", "preparing_survivors", "prepared", "removal_authority_committed", "removing", "publication", "cleanup", "completed"):
            raise InterfaceError("deletion_authority_unavailable")
        if job.get("reason") not in (None, *ERROR_MESSAGES):
            raise InterfaceError("deletion_authority_unavailable")
        paths = {item["path"] for item in job["plan"]["actions"]}
        for field in ("removed", "pending", "unknown"):
            values = job.get(field)
            if not isinstance(values, list) or len(values) != len(set(values)) or not set(values) <= paths:
                raise InterfaceError("deletion_authority_unavailable")
        if set(job["removed"]) & set(job["pending"]) or set(job["removed"]) | set(job["pending"]) != paths or job.get("inflight") not in (None, *paths):
            raise InterfaceError("deletion_authority_unavailable")
        if any(type(job.get(field)) is not int or job[field] < 0 for field in ("progress_bytes", "progress_records", "progress_files")):
            raise InterfaceError("deletion_authority_unavailable")
        return job

    def save(self, job):
        # Status/cancel reads hold this same short metadata lock. An atomic
        # descriptor replacement must not race their no-alias open validation.
        with self.lock:
            io.publish(self.path(job["job_id"]) / "job.json", job)

    def prepare(self):
        self.authority.prepare()
        # This runs before legacy startup reconciliation. A committed removal
        # journal cannot expose an old/mixed view or be truncated back to it.
        for name in self.ids():
            job = self.load(name)
            if name in self.authority.value["committed"] and job["state"] != "succeeded":
                self.finish(job, recovering=True)
            elif job["state"] in ("pending", "running"):
                job.update(state="unknown", reason="deletion_interrupted")
                self.audit_staging(job)
                self.save(job)
        self.c._annotations.pruning_authority = self.authority.value["bridges"]
        self.validate_serving_scope()

    def validate_serving_scope(self):
        if not self.authority.value["captures"]:
            return
        c = self.c
        state = io.read_json(Path(c.state_path))
        gaps = state.get("deletion_gaps", {})
        if not isinstance(gaps, dict):
            raise InterfaceError("deletion_authority_unavailable")
        for seq, key in gaps.items():
            entry = self.authority.value["captures"].get(key)
            if not isinstance(seq, str) or not seq.isascii() or not seq.isdecimal() or str(int(seq)) != seq or entry is None or entry["durable_seq"] != int(seq):
                raise InterfaceError("deletion_authority_unavailable")
        # Ignore unpublished crash tails exactly as the existing collector does;
        # only the published prefix may be interpreted as current content.
        count = previous = 0
        with io.open_read(Path(c.observations_path)) as stream:
            while stream.tell() < state["durable_offset"]:
                raw = stream.readline(131073)
                if not raw or len(raw) > 131072 or not raw.endswith(b"\n") or stream.tell() > state["durable_offset"]:
                    raise InterfaceError("deletion_authority_unavailable")
                row = json.loads(raw)
                seq = row.get('durable_seq')
                if type(seq) is not int or not previous < seq <= state['durable_seq'] or str(seq) in gaps:
                    raise InterfaceError('deletion_authority_unavailable')
                count += 1
                previous = seq
                if self.authority.removed(row["source_instance_id"], row["source_local_sequence"]):
                    raise InterfaceError("deletion_removed")
        if count + len(gaps) != state['durable_seq']:
            raise InterfaceError('deletion_authority_unavailable')

    def preview(self, selection, ignore_job=None):
        if self.active is not None and self.active != ignore_job:
            raise InterfaceError("management_busy")
        if self.authority.failed:
            raise InterfaceError("deletion_authority_unavailable")
        self.authority.check()
        return Planner(self).preview(selection)

    def confirm(self, body):
        if safe_token(body.get("operation_id")) is None or body.get("confirm") is not True or body.get("accept_collateral") is not True:
            raise InterfaceError("invalid_request")
        plan = body.get("plan")
        if not isinstance(plan, dict) or body.get("plan_identity") != io.digest(plan):
            raise InterfaceError("deletion_stale")
        request_digest = io.digest({"plan_identity": body["plan_identity"], "accept_collateral": True})
        job_id = io.digest({"namespace": self.authority.value["namespace"], "operation_id": body["operation_id"]})
        with self.c._operation_lock, self.lock:
            if job_id in self.ids():
                job = self.load(job_id)
                if job["request_digest"] != request_digest:
                    raise InterfaceError("deletion_operation_conflict")
                return {**self.summary(job), "replayed": True}
            if self.c._stop or self.active is not None or self.c._management.active is not None or self.c._datasets.active is not None:
                raise InterfaceError("management_busy")
            if len(self.ids()) >= MAX_JOBS:
                raise InterfaceError("deletion_bound")
            if self.preview(plan.get("selection"))["plan"] != plan:
                raise InterfaceError("deletion_stale")
            # Authority exhaustion refuses before even survivor preparation.
            self.authority.proposed(job_id, plan["removed_references"], [])
            io.mkdir(self.root / job_id)
            job = {"version": VERSION, "job_id": job_id, "plan": plan, "plan_identity": io.digest(plan),
                   "request_digest": request_digest, "state": "pending", "phase": "acknowledged", "reason": None,
                   "progress_bytes": 0, "progress_records": 0, "progress_files": 0, "registry": [],
                   "removed": [], "pending": [item["path"] for item in plan["actions"]],
                   "unknown": [], "inflight": None, "bridges": []}
            self.save(job)
            self.active = job_id
            self.cancel.clear()
            self.thread = threading.Thread(target=self.run, args=(job_id,), name="archive-deletion", daemon=True)
            self.thread.start()
            return {**self.summary(job), "replayed": False, "acknowledgement": "durable_request_not_completion"}

    def summary(self, job):
        return {"deletion_version": VERSION, "job_id": job["job_id"],
                "state": "unknown" if job["job_id"] in self.uncertain else job["state"],
                "phase": job["phase"], "reason": job["reason"], "plan_identity": job["plan_identity"],
                "request_digest": job["request_digest"], "progress_bytes": job["progress_bytes"],
                "progress_records": job["progress_records"], "progress_files": job["progress_files"],
                "irreversible": None if self.authority.failed else job["job_id"] in self.authority.value["committed"],
                "authority_commit": "unknown" if self.authority.failed else "committed" if job["job_id"] in self.authority.value["committed"] else "not_committed",
                "removed": job["removed"], "pending": job["pending"], "unknown": job["unknown"],
                "residual_staging": [entry["path"] for entry in job["registry"] if entry["state"] not in ("transferred", "discarded")],
                "scope": job["plan"]["counts"], "excluded_domains": job["plan"]["excluded_domains"], "content_included": False}

    def checkpoint(self, job, count=0, records_count=0):
        if self.cancel.is_set() or self.c._stop:
            raise InterfaceError("deletion_cancelled")
        job["progress_bytes"] += count
        job["progress_records"] += records_count
        self.save(job)
        self.hook("prepare_progress")

    def reserve(self, job, target):
        entry = {"path": io.digest({"target": target}) + ".survivor", "target": target,
                 "scope": job["plan"]["frontier"], "state": "reserved", "size": None, "sha256": None}
        job["registry"].append(entry)
        self.save(job)
        return entry, self.path(job["job_id"]) / entry["path"]

    def stage(self, job):
        c = self.c
        plan = job["plan"]
        keys = {capture_key(ref["source_instance_id"], ref["source_local_sequence"]) for ref in plan["removed_references"]}
        current = Path(c.content_root)
        base = str(current.relative_to(Path(c.root)))
        prefix = "" if base == "." else base + "/"
        index = {row["durable_seq"]: row["record_digest"] for row in c._index}
        sizes = {}
        for filename in ("observations.jsonl", "annotations.jsonl"):
            action = next(a for a in plan['actions'] if a['path'] == prefix + filename)
            if binding(current / filename) != action['binding']:
                raise InterfaceError('deletion_stale')
            entry, path = self.reserve(job, prefix + filename)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                processed_bytes = processed_records = 0
                for row, raw in records(current / filename, action['binding']['size']):
                    if filename == "observations.jsonl":
                        if index.get(row["durable_seq"]) != digest(row):
                            raise InterfaceError("deletion_stale")
                        remove = capture_key(row["source_instance_id"], row["source_local_sequence"]) in keys
                    else:
                        ref = row["semantic"]["source_reference"]
                        remove = capture_key(ref["source_instance_id"], ref["source_local_sequence"]) in keys
                        if remove:
                            job["bridges"].append({"archive_id": row["archive_id"], "revision": row["revision"],
                                                   "previous": row["previous"], "chain": row["chain"],
                                                   "operation_digest": digest({"operation_id": row["operation_id"]}),
                                                   "semantic_hash": row["semantic_hash"]})
                    if not remove:
                        io.write_all(fd, raw)
                    processed_bytes += len(raw)
                    processed_records += 1
                    if processed_records == 64:
                        self.checkpoint(job, processed_bytes, processed_records)
                        processed_bytes = processed_records = 0
                if processed_records:
                    self.checkpoint(job, processed_bytes, processed_records)
                os.fsync(fd)
            finally:
                os.close(fd)
            io.sync(path.parent)
            entry.update(io.measure(path), state="staged")
            sizes[filename] = entry["size"]
            self.save(job)
        authority = self.authority.proposed(job["job_id"], plan["removed_references"], job["bridges"])
        gaps = dict(c._state.get("deletion_gaps", {}))
        for ref in plan["removed_references"]:
            gaps[str(ref["durable_seq"])] = capture_key(ref["source_instance_id"], ref["source_local_sequence"])
        state = {**c._state, "durable_offset": sizes["observations.jsonl"], "durable_bytes": sizes["observations.jsonl"],
                 "deletion_gaps": gaps, "deletion_namespace": authority["namespace"],
                 "collector_epoch": uuid.uuid4().hex, "continuity_epoch": uuid.uuid4().hex,
                 "continuity_break_reasons": ["confirmed_input_deletion"], "clean_stop": True}
        manifest = copy.deepcopy(c._annotations._manifest())
        pruned = dict(c._annotations.pruned)
        pruned.update({bridge["revision"]: bridge for bridge in job["bridges"]})
        manifest.update(offset=sizes["annotations.jsonl"])
        if pruned:
            manifest["pruned"] = [digest({field: bridge[field] for field in ("archive_id", "revision", "chain")}) for _, bridge in sorted(pruned.items())]
        for filename, value in (("state.json", state), ("annotation-state.json", manifest)):
            entry, path = self.reserve(job, prefix + filename)
            io.write_new(path, canonical_bytes(value))
            entry.update(io.measure(path), state="staged")
            self.checkpoint(job, entry["size"])
        job["phase"] = "prepared"
        self.save(job)

    def run(self, job_id):
        c = self.c
        try:
            job = self.load(job_id)
            job.update(state="running", phase="preparing_survivors")
            self.save(job)
            self.hook("before_prepare")
            self.stage(job)
            self.hook("after_prepare")
            if not c._content_gate.begin_transition():
                raise InterfaceError("management_busy")
            policy_locked = publication_locked = False
            try:
                if not c._policy_lock.acquire(False):
                    raise InterfaceError("management_busy")
                policy_locked = True
                if not c._publication_mutex.acquire(False):
                    raise InterfaceError("management_busy")
                publication_locked = True
                if self.preview(job["plan"]["selection"], ignore_job=job_id)["plan"] != job["plan"]:
                    raise InterfaceError("deletion_stale")
                with c._lock:
                    if c._queue or c._publishing_units:
                        raise InterfaceError("management_busy")
                    c._transition = True
                if self.cancel.is_set() or c._stop:
                    raise InterfaceError("deletion_cancelled")
                self.hook("before_authority_commit")
                with self.lock:
                    if self.cancel.is_set() or c._stop:
                        raise InterfaceError("deletion_cancelled")
                    self.authority.commit(job_id, job["plan"]["removed_references"], job["bridges"], job["plan"]["frontier"]["removal_revision"])
                job["phase"] = "removal_authority_committed"
                self.save(job)
                self.hook("after_authority_commit")
                self.finish(job)
                c._annotations = AnnotationStore(c.content_root)
                c._annotations.pruning_authority = self.authority.value["bridges"]
                c._load_state()
                c._rebuild_index()
                c._annotations.prepare()
                c._datasets.prepare()
                c._persist_state()
            except BaseException:
                if job_id in self.authority.value["committed"] or self.authority.failed:
                    c._maintenance_unavailable = True
                raise
            finally:
                with c._lock:
                    c._transition = False
                if publication_locked:
                    c._publication_mutex.release()
                if policy_locked:
                    c._policy_lock.release()
                c._content_gate.end_transition()
        except BaseException as error:
            try:
                job = self.load(job_id)
                irreversible = job_id in self.authority.value["committed"] or self.authority.failed
                job.update(state="unknown" if irreversible else "cancelled" if isinstance(error, InterfaceError) and error.code == "deletion_cancelled" else "failed",
                           reason=error.code if isinstance(error, InterfaceError) else "unsafe_root" if isinstance(error, UnsafeRoot) else "storage_failure")
                if job.get("inflight") is not None and job["inflight"] not in job["unknown"]:
                    job["unknown"].append(job["inflight"])
                self.audit_staging(job)
                self.save(job)
            except BaseException:
                self.uncertain.add(job_id)
        finally:
            with self.lock:
                self.active = None

    def audit_staging(self, job):
        for entry in job["registry"]:
            path = self.path(job["job_id"]) / entry["path"]
            if os.path.lexists(path):
                entry.update(io.measure(path), state="incomplete")

    def finish(self, job, recovering=False):
        """Resume exact-bound paths. Never replay removed text or old backups."""
        if job["job_id"] not in self.authority.value["committed"]:
            raise InterfaceError("deletion_authority_unavailable")
        job.update(state="running", phase="removing")
        self.save(job)
        stage = {entry["target"]: entry for entry in job["registry"]}
        for action in job["plan"]["actions"]:
            name = action["path"]
            target = self.resolve(name)
            if name in job["removed"]:
                # A transferred survivor may legitimately advance only after a
                # completed job. An incomplete job has never resumed collection.
                if action["action"] == "unlink" and os.path.lexists(target):
                    raise InterfaceError("deletion_stale")
                continue
            job["pending"] = [item["path"] for item in job["plan"]["actions"] if item["path"] not in job["removed"]]
            job["inflight"] = name
            self.save(job)
            self.hook("before_path_mutation")
            if action["action"] == "survivor_rewrite":
                entry = stage[name]
                source = self.path(job["job_id"]) / entry["path"]
                expected = {key: entry[key] for key in ("size", "sha256")}
                if os.path.lexists(source):
                    if binding(target) != action["binding"] or io.measure(source) != expected:
                        raise InterfaceError("deletion_stale")
                    os.replace(source, target)
                    io.sync(target.parent)
                elif not os.path.lexists(target) or io.measure(target) != expected:
                    raise InterfaceError("deletion_stale")
                entry["state"] = "transferred"
            else:
                if os.path.lexists(target):
                    if binding(target) != action["binding"]:
                        raise InterfaceError("deletion_stale")
                    os.unlink(target)
                    io.sync(target.parent)
                elif not recovering:
                    raise InterfaceError("deletion_stale")
                else:
                    # A crash may follow unlink before the progress save. The
                    # journal is the explicit transaction binding for this leaf.
                    io.sync(target.parent)
            job["removed"].append(name)
            job["inflight"] = None
            job["unknown"] = [path for path in job["unknown"] if path != name]
            job["pending"] = [path for path in job["pending"] if path != name]
            job["progress_files"] += 1
            self.save(job)
            self.hook("after_path_mutation")
        job["phase"] = "publication"
        self.save(job)
        self.publish_lifecycle(job)
        self.hook("after_registry_publication")
        job["phase"] = "cleanup"
        self.save(job)
        for entry in job["registry"]:
            if os.path.lexists(self.path(job["job_id"]) / entry["path"]):
                raise InterfaceError("deletion_residual")
        for action in job["plan"]["actions"]:
            target = self.resolve(action["path"])
            if action["action"] == "unlink":
                if os.path.lexists(target):
                    raise InterfaceError("deletion_residual")
            else:
                expected = {key: stage[action["path"]][key] for key in ("size", "sha256")}
                if io.measure(target) != expected:
                    raise InterfaceError("deletion_residual")
        if job["pending"] or job["unknown"]:
            raise InterfaceError("deletion_residual")
        self.hook("before_completion")
        job.update(state="succeeded", phase="completed", reason=None)
        self.save(job)

    def publish_lifecycle(self, job):
        # Descriptors are content-free lifecycle authority, not usable immutable
        # payloads. Never regenerate or rebind a removed artifact as successful.
        removed = {item["path"] for item in job["plan"]["actions"] if item["action"] == "unlink"}
        for name in self.c._management.ids():
            descriptor = self.c._management.load(name)
            changed = False
            for entry in descriptor["registry"]:
                parts = io.relative(entry["path"])
                if parts[0] == "replaced":
                    old = descriptor.get("old_content")
                    prefix = "" if old == "." else old + "/" if isinstance(old, str) else "unknown/"
                    relative = prefix + "/".join(parts[1:])
                else:
                    relative = "management/jobs/" + name + "/" + entry["path"]
                if relative in removed:
                    entry["state"] = "discarded"
                    changed = True
            if changed:
                descriptor["removal_job"] = job["job_id"]
                if (descriptor.get("request") or {}).get("kind") == "backup":
                    descriptor.update(state="failed", reason="deletion_removed")
                self.c._management.save(descriptor)
        from archive.datasets import DatasetStore
        for record in job['plan']['inventory']['jobs']:
            if record['kind'] != 'dataset':
                continue
            base = record['owner']
            path = self.resolve(base)
            # Whole backup removal includes its nested immutable descriptors.
            if not os.path.lexists(path / 'job.json'):
                continue
            store = DatasetStore(self.c)
            store.root = path.parent
            name = path.name
            descriptor = store.load(name)
            if any(base + "/" + entry["path"] in removed for entry in descriptor["registry"]):
                descriptor.update(state="failed", reason="deletion_removed", removal_job=job["job_id"])
                for entry in descriptor["registry"]:
                    if base + "/" + entry["path"] in removed:
                        entry.update(state="not_created", size=None, sha256=None)
                store.save(descriptor)
        for name in self.ids():
            if name == job["job_id"]:
                continue
            descriptor = self.load(name)
            changed = False
            for entry in descriptor["registry"]:
                relative = str((self.path(name) / entry["path"]).relative_to(Path(self.c.root)))
                if relative in removed:
                    entry["state"] = "discarded"
                    changed = True
            if changed:
                descriptor["removal_job"] = job["job_id"]
                self.save(descriptor)

    def call(self, body):
        if body.get("deletion_version") != VERSION:
            raise InterfaceError("deletion_unsupported")
        if set(body) - {"deletion_version", "action", "selection", "plan", "plan_identity", "operation_id", "confirm", "accept_collateral", "job_id", "after", "page_size"}:
            raise InterfaceError("invalid_request")
        action = body.get("action")
        if (self.c._maintenance_unavailable or self.authority.failed) and action not in ("status", "progress", "result", "list", "registry", "availability", "cancel"):
            raise InterfaceError("deletion_authority_unavailable")
        if action == "preview":
            return self.preview(body.get("selection"))
        if action == "confirm":
            return self.confirm(body)
        if action == "availability":
            return self.authority.summary()
        if action == "list":
            after, size = body.get("after", 0), body.get("page_size", 20)
            if type(after) is not int or after < 0 or type(size) is not int or not 1 <= size <= io.PAGE:
                raise InterfaceError("deletion_bound")
            ids = self.ids()
            return {"jobs": [self.summary(self.load(name)) for name in ids[after:after + size]],
                    "next_after": after + size if after + size < len(ids) else None}
        with self.lock:
            job = self.load(body.get("job_id"))
            if action in ("status", "result", "progress"):
                return self.summary(job)
            if action == "cancel":
                if self.authority.failed:
                    raise InterfaceError("deletion_authority_unavailable")
                if job["job_id"] in self.authority.value["committed"]:
                    raise InterfaceError("deletion_committed")
                if self.active == job["job_id"]:
                    self.cancel.set()
                elif job["state"] in ("pending", "unknown"):
                    job.update(state="cancelled", reason="deletion_cancelled")
                    self.save(job)
                return self.summary(job)
            if action == "registry":
                after, size = body.get("after", 0), body.get("page_size", 20)
                if type(after) is not int or after < 0 or type(size) is not int or not 1 <= size <= io.PAGE:
                    raise InterfaceError("deletion_bound")
                rows = job["registry"]
                return {"registry": rows[after:after + size], "next_after": after + size if after + size < len(rows) else None}
        raise InterfaceError("invalid_request")
