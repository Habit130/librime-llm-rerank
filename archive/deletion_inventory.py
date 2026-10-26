"""Finite registered-copy inventory, without semantic compatibility promotion.

Only registry edges and the current canonical core are traversed. In particular,
this is not filesystem discovery, a dataset migration, or deletion authority.
"""

from __future__ import annotations

import os
from pathlib import Path

from archive import management_io as io
from archive.interface import InterfaceError
from archive.management import CORE

MAX_FILES = 8192
MAX_BYTES = 2 * 1024 * 1048576
MAX_EDGES = 32768
MAX_DEPTH = 8


def binding(path):
    before = io.regular(path)
    checksum = io.measure(path)
    after = io.regular(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise InterfaceError("deletion_stale")
    return {**checksum, "device": after.st_dev, "inode": after.st_ino,
            "mtime_ns": after.st_mtime_ns, "ctime_ns": after.st_ctime_ns}


class Inventory:
    def __init__(self, collector):
        self.c = collector
        self.root = io.directory(Path(collector.root))
        self.files = {}
        self.edges = []
        self.sources = {}
        self.jobs = []
        self.dataset_roots = set()
        self.bytes = 0

    def relative(self, path):
        # Every caller constructs a path from a validated registered owner.
        # Plans report that identity; no request may resolve an arbitrary path.
        try:
            return str(Path(path).relative_to(self.root))
        except ValueError:
            raise InterfaceError("deletion_unknown_lineage") from None

    def add(self, path, owner, role, dependency, state, expected=None, immutable=False):
        name = self.relative(path)
        if len(self.edges) >= MAX_EDGES:
            raise InterfaceError("deletion_bound")
        edge = {"path": name, "owner": owner, "role": role, "lifecycle": state,
                 "dependency": dependency, "immutable": immutable}
        if dependency is None:
            edge["unknown"] = "missing_registered_dependency"
        present = os.path.lexists(path)
        if present:
            bound = binding(path)
            # Mutable serving and transferred source files have their own exact
            # current binding, not a claim that their initial checksum is current.
            pinned = state in ("published", "retained", "replaced_pending_discard", "retained_source_unavailable", "staged")
            if expected is not None and pinned and bound["size"] != expected.get("size"):
                raise InterfaceError("deletion_unknown_lineage")
            if expected is not None and pinned and bound["sha256"] != expected.get("sha256"):
                raise InterfaceError("deletion_unknown_lineage")
            if name in self.files and self.files[name]["binding"] != bound:
                raise InterfaceError("deletion_stale")
            if name not in self.files:
                self.bytes += bound["size"]
            self.files[name] = {"path": name, "binding": bound}
        else:
            # Reserved/never-created and explicitly discarded copies are honest
            # absences, not an error or permission to delete a later replacement.
            if state not in ("reserved", "not_created", "discarded"):
                raise InterfaceError("deletion_unknown_lineage")
            edge["absent"] = True
        self.edges.append(edge)
        if len(self.files) > MAX_FILES or self.bytes > MAX_BYTES:
            raise InterfaceError("deletion_bound")

    def source(self, path, frontier, owner, lifecycle):
        name = self.relative(path)
        if not isinstance(frontier, dict) or not isinstance(frontier.get("archive_id"), str):
            raise InterfaceError("deletion_unknown_lineage")
        io.identifier(frontier["archive_id"], 32)
        item = {"path": name, "frontier": frontier, "owner": owner, "lifecycle": lifecycle}
        prior = self.sources.get(name)
        if prior is not None and prior["frontier"]["archive_id"] != frontier["archive_id"]:
            raise InterfaceError("deletion_unknown_lineage")
        if prior is None or lifecycle == "current" or prior["lifecycle"] != "current" and frontier.get("durable_seq", 0) > prior["frontier"].get("durable_seq", 0):
            self.sources[name] = item

    def old_root(self, job):
        relative = job.get("old_content")
        if relative == ".":
            return self.root
        if not isinstance(relative, str):
            raise InterfaceError("deletion_unknown_lineage")
        parts = io.relative(relative)
        if len(parts) != 4 or parts[:2] != ["management", "jobs"] or parts[3] != "restored":
            raise InterfaceError("deletion_unknown_lineage")
        io.identifier(parts[2])
        path = self.root
        for part in parts:
            path = io.directory(path / part)
        return path

    def collect(self):
        c = self.c
        with c._lock:
            if c._queue or c._publishing_units or c._transition or c._state["storage_failure"]:
                raise InterfaceError("management_busy")
            frontier = {"archive_id": c._annotations.archive_id, "durable_seq": c._state["durable_seq"],
                        "annotation_revision": c._annotations.revision,
                        "serving_generation": c._management.authority.value["generation"]}
        self.source(Path(c.content_root), frontier, "current", "current")
        for name in CORE:
            self.add(Path(c.content_root) / name, "current", "canonical", frontier, "current")
        # A dataset descriptor's structural loader deliberately does not require
        # its old tool code identity to equal today's code. No manifest semantic
        # verifier, mutation, compatibility weakening or regeneration is invoked.
        if c._datasets.active is not None or c._management.active is not None:
            raise InterfaceError("management_busy")
        self.datasets(Path(c.content_root) / "datasets")
        for name in c._management.ids():
            job = c._management.load(name)
            self.jobs.append({"owner": name, "kind": "management", "state": job["state"],
                              "request_digest": job["request_digest"]})
            base = c._management.path(name)
            request = job["request"]
            if job.get("old_content") is not None:
                self.datasets(self.old_root(job) / "datasets")
            for entry in job["registry"]:
                parts = io.relative(entry["path"])
                if parts[0] == "replaced":
                    if job.get('old_content') is None:
                        # Before the restore switch this is an ownership-transfer
                        # reservation, not a second physical copy. The existing
                        # source is inventoried through its actual serving owner.
                        if entry['state'] != 'reserved' or os.path.lexists(base / 'replaced'):
                            raise InterfaceError('deletion_unknown_lineage')
                        if len(self.edges) >= MAX_EDGES:
                            raise InterfaceError('deletion_bound')
                        self.edges.append({'path': self.relative(base / entry['path']), 'owner': name,
                                           'role': entry['role'], 'lifecycle': 'reserved_no_transfer',
                                           'dependency': entry['dependencies'], 'absent': True, 'immutable': False})
                        continue
                    path = self.old_root(job)
                    relative = "/".join(parts[1:])
                else:
                    path = base
                    relative = entry["path"]
                leaf = io.optional(path, relative)
                if leaf is None:
                    # An absent reserved nested directory has no payload; never
                    # create it during a read-only inventory.
                    if entry["state"] not in ("reserved", "not_created", "discarded"):
                        raise InterfaceError("deletion_unknown_lineage")
                    self.edges.append({"path": self.relative(path / relative), "owner": name,
                                       "role": entry["role"], "lifecycle": entry["state"],
                                       "dependency": entry["dependencies"], "absent": True,
                                       "immutable": job["state"] == "succeeded" and parts[0] == "backup"})
                    if len(self.edges) > MAX_EDGES:
                        raise InterfaceError("deletion_bound")
                    continue
                self.add(leaf, name, entry["role"], entry["dependencies"], entry["state"], entry,
                         immutable=job["state"] == "succeeded" and parts[0] == "backup")
                if leaf.name == "observations.jsonl" and os.path.lexists(leaf):
                    self.source(leaf.parent, entry["dependencies"], name, entry["state"])
                if parts[0] in ("backup", "restored"):
                    self.datasets(base / parts[0] / "datasets")
            if request is None and job["registry"]:
                raise InterfaceError("deletion_unknown_lineage")
        if hasattr(c, "_deletion") and c._deletion.authority.value is not None:
            for name in c._deletion.ids():
                if name == c._deletion.active:
                    # This operation's declared survivors are not an escape
                    # copy, and must not make its own final cutoff stale.
                    continue
                job = c._deletion.load(name)
                self.jobs.append({"owner": name, "kind": "deletion", "state": job["state"],
                                  "request_digest": job["request_digest"]})
                for entry in job["registry"]:
                    path = c._deletion.path(name) / entry["path"]
                    lifecycle = "discarded" if entry["state"] in ("transferred", "discarded") else entry["state"]
                    self.add(path, name, "deletion_survivors", entry["scope"], lifecycle, entry)
        return {"files": sorted(self.files.values(), key=lambda row: row["path"]),
                "edges": self.edges, "sources": sorted(self.sources.values(), key=lambda row: row["path"]),
                "jobs": self.jobs,
                "counts": {"files": len(self.files), "edges": len(self.edges), "sources": len(self.sources),
                           "bytes": self.bytes},
                 "bounds": {"files": MAX_FILES, "bytes": MAX_BYTES, "edges": MAX_EDGES, "lineage_depth": MAX_DEPTH}}

    def datasets(self, root):
        """Visit only the dataset registry of an already registered source owner.

        Retired source directories can contain failed jobs that were excluded
        from a backup. Their own registry remains authoritative after restore.
        A disposable structural reader never prepares/repairs the old store.
        """
        if root in self.dataset_roots or not os.path.lexists(root):
            return
        self.dataset_roots.add(root)
        if len(self.dataset_roots) > MAX_EDGES:
            raise InterfaceError("deletion_bound")
        from archive.datasets import DatasetStore
        store = DatasetStore(self.c)
        store.root = io.directory(root)
        for name in store.ids():
            job = store.load(name)
            base = store.path(name)
            owner = self.relative(base)
            self.jobs.append({"owner": owner, "kind": "dataset", "state": job["state"],
                              "request_digest": job["request_digest"]})
            for entry in job["registry"]:
                path = io.optional(base, entry["path"])
                if path is None:
                    raise InterfaceError("deletion_unknown_lineage")
                self.add(path, owner, "dataset", entry["dependencies"], entry["state"], entry,
                         immutable=job["state"] == "succeeded")
