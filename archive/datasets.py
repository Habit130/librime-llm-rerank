"""Collector-owned immutable datasets. No Adapter reads or joins storage.

Only payload-free bounded metadata is retained across the two streaming passes.
Publication is the fsynced job descriptor: it atomically registers the complete
artifact set and its dependencies. Unpublished copies remain owned, never valid.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

from archive import annotations
from archive.interface import CONTENT_VERSION, ERROR_MESSAGES, InterfaceError, canonical_bytes
from archive.querying import QUERY_VERSION, CHOICE_PROJECTION_VERSION, RelationContext
from archive.safety import UnsafeRoot, safe_token, validate_root

VERSION = "input-archive-datasets-v1"
RULE = "whole-segment-durable-interval-v1"
MAX_SOURCES = 65536
MAX_JOBS = 1024
PAGE = 64
LINE = 8 * 1048576
SOURCE_LINE = 131072
FILES = ("partition.jsonl", "corpus.jsonl", "choice.jsonl")
PARTS = ("train", "validation", "test")
TERMINALS = {"commit_attempt", "cancellation", "raw_finalization", "unavailable_client", "unknown_outcome"}


def sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def known_text(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= SOURCE_LINE
    except UnicodeError:
        return False


def check_dir(path):
    validate_root(str(path))
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise UnsafeRoot("dataset_directory")


def check_file(path):
    check_dir(Path(path).parent)
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600:
        raise UnsafeRoot("dataset_artifact")


def read_json(path, bound=LINE):
    check_file(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        raw = f.read(bound + 1)
    if len(raw) > bound:
        raise InterfaceError("dataset_bound")
    return json.loads(raw)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_all(fd, raw):
    while raw:
        n = os.write(fd, raw)
        if n <= 0:
            raise OSError()
        raw = raw[n:]


def publish_json(path, value):
    """Fixed private descriptor, short-write safe; unknown fsync failure is not success."""
    parent = Path(path).parent
    check_dir(parent)
    if os.path.lexists(path):
        check_file(path)
    temporary = parent / (Path(path).name + ".pending")
    if os.path.lexists(temporary):
        check_file(temporary)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        write_all(fd, canonical_bytes(value))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    sync_dir(parent)


def code_identity():
    root = Path(__file__).parent
    return sha({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ("datasets.py", "collector.py", "annotations.py", "querying.py", "interface.py")})


class Cancelled(Exception):
    pass


class DatasetStore:
    def __init__(self, collector):
        self.collector = collector
        self.root = Path(collector.root) / "datasets"
        self.lock = threading.RLock()
        self.active = None
        self.cancelled = threading.Event()
        self.thread = None
        self.uncertain = set()
        self.error = None

    def prepare(self):
        try:
            self._recover()
        except InterfaceError as exc:
            self.error = exc.code
        except UnsafeRoot:
            self.error = "unsafe_root"
        except (OSError, ValueError, KeyError, TypeError):
            self.error = "dataset_corrupt"

    def _recover(self):
        # Lazy: existing archive starts do not create any dataset bytes.
        if not os.path.lexists(self.root):
            return
        check_dir(self.root)
        for job_id in self.ids():
            job = self.load(job_id)
            if job["state"] in ("pending", "running"):
                job["state"] = "unknown"
                job["reason"] = "interrupted_before_publication"
                for artifact in job["registry"]:
                    path = self.path(job_id) / artifact["path"]
                    if os.path.lexists(path):
                        size, digest = self.file_digest(path)
                        artifact.update(state="incomplete", size=size, sha256=digest)
                    else:
                        artifact["state"] = "not_created"
                self.save(job)

    def ids(self):
        if not os.path.lexists(self.root):
            return []
        check_dir(self.root)
        names = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                if len(names) == MAX_JOBS:
                    raise InterfaceError("dataset_bound")
                if len(entry.name) != 64 or any(c not in "0123456789abcdef" for c in entry.name):
                    raise InterfaceError("dataset_corrupt")
                check_dir(self.root / entry.name)
                names.append(entry.name)
        return sorted(names)

    def path(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 64 or any(c not in "0123456789abcdef" for c in job_id):
            raise InterfaceError("invalid_request")
        check_dir(self.root)
        path = self.root / job_id
        if not os.path.lexists(path):
            raise InterfaceError("not_found")
        check_dir(path)
        return path

    def load(self, job_id):
        try:
            job = read_json(self.path(job_id) / "job.json")
        except FileNotFoundError:
            return self.unacknowledged(job_id)
        if job.get("request") is None and job.get("state") in ("unknown", "cancelled"):
            return {**self.unacknowledged(job_id), "state": job["state"]}
        if job.get("version") != VERSION:
            raise InterfaceError("dataset_incompatible")
        if job.get("job_id") != job_id or job.get("state") not in ("pending", "running", "succeeded", "failed", "cancelled", "unknown"):
            raise InterfaceError("dataset_corrupt")
        if sha(job.get("request")) != job.get("request_digest"):
            raise InterfaceError("dataset_corrupt")
        request = job["request"]
        if set(request) != {"snapshot", "version", "rule", "code_identity"} or request["version"] != VERSION or request["rule"] != RULE:
            raise InterfaceError("dataset_incompatible")
        pair = request["snapshot"]
        if not isinstance(pair, dict) or set(pair) != {"archive_id", "as_of_durable_seq", "annotation_revision", "first_durable_seq", "content_version", "query_version", "annotation_version", "source_content_identity"}:
            raise InterfaceError("dataset_corrupt")
        archive_id = pair["archive_id"]
        if not isinstance(archive_id, str) or len(archive_id) != 32 or any(c not in "0123456789abcdef" for c in archive_id):
            raise InterfaceError("dataset_corrupt")
        for value in (pair["source_content_identity"], request["code_identity"]):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise InterfaceError("dataset_corrupt")
        if any(not annotations.integer(pair[k], 1 if k == "first_durable_seq" else 0) for k in ("as_of_durable_seq", "annotation_revision", "first_durable_seq")):
            raise InterfaceError("dataset_corrupt")
        if pair["content_version"] != CONTENT_VERSION or pair["query_version"] != QUERY_VERSION or pair["annotation_version"] != annotations.ANNOTATION_VERSION:
            raise InterfaceError("dataset_incompatible")
        registry = job.get("registry")
        if not isinstance(registry, list) or len(registry) != 4 or {x.get("path") for x in registry} != {*FILES, "manifest.json"}:
            raise InterfaceError("dataset_corrupt")
        for item in registry:
            if set(item) != {"owner", "path", "state", "sha256", "size", "dependencies"} or item["owner"] != job_id or item["dependencies"] != job["request"]["snapshot"] or item["state"] not in ("reserved", "published", "incomplete", "not_created"):
                raise InterfaceError("dataset_corrupt")
            if item["sha256"] is not None and (not isinstance(item["sha256"], str) or len(item["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in item["sha256"])):
                raise InterfaceError("dataset_corrupt")
            if item["size"] is not None and not annotations.integer(item["size"]):
                raise InterfaceError("dataset_corrupt")
        if type(job.get("cancel_requested")) is not bool or not annotations.integer(job.get("progress_sources")):
            raise InterfaceError("dataset_corrupt")
        if job.get("reason") not in (None, "interrupted_before_publication", "cancelled_before_publication", "dataset_write_failed", *ERROR_MESSAGES):
            raise InterfaceError("dataset_corrupt")
        return job

    def unacknowledged(self, job_id):
        registry = []
        for name in (*FILES, "manifest.json"):
            path = self.path(job_id) / name
            size, digest = self.file_digest(path) if os.path.lexists(path) else (None, None)
            registry.append({"owner": job_id, "path": name, "state": "incomplete" if size is not None else "not_created",
                             "sha256": digest, "size": size, "dependencies": None})
        return {"version": VERSION, "job_id": job_id, "request": None, "request_digest": None,
                "state": "unknown", "progress_sources": 0, "reason": "interrupted_before_request_acknowledgement",
                "cancel_requested": False, "registry": registry}

    def save(self, job):
        publish_json(self.path(job["job_id"]) / "job.json", job)

    def snapshot(self, body):
        c = self.collector
        store = c._annotations
        with store.lock:
            store._healthy()
            with c._lock:
                prefix = c._state["durable_seq"]
            pair = {"archive_id": store.archive_id, "as_of_durable_seq": prefix,
                    "annotation_revision": store.revision, "first_durable_seq": 1,
                    "content_version": CONTENT_VERSION, "query_version": QUERY_VERSION,
                    "annotation_version": annotations.ANNOTATION_VERSION}
            if not isinstance(body, dict) or set(body) - (set(pair) | {"source_content_identity"}):
                raise InterfaceError("invalid_request")
            for name in pair:
                if name in body:
                    pair[name] = body[name]
            if pair["archive_id"] != store.archive_id:
                raise InterfaceError("annotation_foreign_archive")
            for name, maximum, minimum in (("as_of_durable_seq", prefix, 0), ("annotation_revision", store.revision, 0), ("first_durable_seq", prefix + 1, 1)):
                if not annotations.integer(pair[name], minimum) or pair[name] > maximum:
                    raise InterfaceError("annotation_revision_unknown")
            if pair["first_durable_seq"] > pair["as_of_durable_seq"] + 1:
                raise InterfaceError("invalid_request")
            for name, expected in (("content_version", CONTENT_VERSION), ("query_version", QUERY_VERSION), ("annotation_version", annotations.ANNOTATION_VERSION)):
                if pair[name] != expected or type(pair[name]) is not type(expected):
                    raise InterfaceError("dataset_incompatible")
            if pair["as_of_durable_seq"] - pair["first_durable_seq"] + 1 > MAX_SOURCES:
                raise InterfaceError("dataset_bound")
        content = hashlib.sha256()
        after = pair["first_durable_seq"] - 1
        while after < pair["as_of_durable_seq"]:
            refs = c._dataset_refs(after, pair["as_of_durable_seq"], PAGE)
            if not refs:
                raise InterfaceError("dataset_source_unavailable")
            for ref in refs:
                if ref["durable_seq"] != after + 1:
                    raise InterfaceError("dataset_corrupt")
                content.update(canonical_bytes({"reference": ref}) + b"\n")
                after = ref["durable_seq"]
        identity = content.hexdigest()
        if "source_content_identity" in body and body["source_content_identity"] != identity:
            raise InterfaceError("annotation_source_mismatch")
        pair["source_content_identity"] = identity
        return pair

    def sources(self, pair, choices=True):
        """At most PAGE reference metadata, one record, bounded shared group projection."""
        c = self.collector
        try:
            check_file(c.observations_path)
        except FileNotFoundError:
            raise InterfaceError("dataset_source_unavailable")
        after = pair["first_durable_seq"] - 1
        while after < pair["as_of_durable_seq"]:
            refs = c._dataset_refs(after, pair["as_of_durable_seq"], PAGE)
            if not refs:
                raise InterfaceError("dataset_source_unavailable")
            for ref in refs:
                if ref["durable_seq"] != after + 1:
                    raise InterfaceError("dataset_corrupt")
                source = c._dataset_source(ref, pair["as_of_durable_seq"], SOURCE_LINE, include_choice=choices)
                if type(source["record"].get("record_version")) is not int or source["record"]["record_version"] != 1:
                    raise InterfaceError("dataset_incompatible")
                with c._annotations.lock:
                    c._annotations._healthy()
                    edits = c._annotations.effective(ref, pair["annotation_revision"])
                yield source, annotations.evidence(source, edits, True)
                after = ref["durable_seq"]

    def inspect(self, pair, emit=None, progress=None):
        """One shared source map, before either view's admission filter.

        Ordering is durable order, not wall-clock causality. Closed intervals
        of every scoped segment AND process forbid cuts. Overlap merges intervals.
        A segment is closed only with a later distinct owned segment witness,
        complete observed processes and no missing local-sequence/loss evidence.
        """
        pair = self.snapshot(pair)
        with self.collector._annotations.lock:
            retained_exclusions = any(key[2] == "exclude" and history[0][0] <= pair["annotation_revision"]
                                      for key, history in self.collector._annotations.history.items())
        metadata, segments, processes, last_source, source_hash = [], {}, {}, {}, hashlib.sha256()
        exclusions, group_exclusions, outside_groups, checked_groups = set(), set(), set(), set()
        window_exclusions, bounded_groups = set(), set()
        for source, evidence in self.sources(pair, choices=False):
            record, ref = source["record"], source["reference"]
            seq = ref["durable_seq"]
            source_hash.update(canonical_bytes({"reference": ref}) + b"\n")
            owner = record["source_instance_id"]
            segment = (owner, record.get("continuity_segment_id"))
            process = (owner, record.get("process_id"))
            plugin = record.get("plugin") or {}
            group = (owner, record.get("process_id"), plugin.get("window_id"), plugin.get("group_id"))
            if plugin.get("window_id") and plugin.get("group_id") and group not in checked_groups:
                checked_groups.add(group)
                refs = self.collector._dataset_window_refs(record, pair["as_of_durable_seq"])
                if refs is None:
                    bounded_groups.add(group)
                if refs and any(r["durable_seq"] < pair["first_durable_seq"] for r in refs):
                    outside_groups.add(group)
            row = {"reference": ref, "segment": segment, "process": process, "group": group,
                   "kind": record.get("observation_kind"), "excluded": evidence["excluded"],
                   "update_id": record.get("update_id"), "plugin": plugin, "daemon": record.get("daemon")}
            metadata.append(row)
            state = segments.setdefault(segment, {"first": seq, "last": seq, "closed": False, "bad": segment[1] is None, "processes": set()})
            state["last"] = seq
            state["processes"].add(process)
            old = last_source.get(owner)
            if old and old[0] != segment:
                segments[old[0]]["closed"] = True
                if state["first"] != seq:
                    state["bad"] = True  # reappearing closed segment
            local = record["source_local_sequence"]
            if old and local != old[1] + 1:
                state["bad"] = True
                segments[old[0]]["bad"] = True
            last_source[owner] = (segment, local)
            proc = processes.setdefault(process, {"first": seq, "last": seq, "start": False, "terminal": False, "segments": set()})
            proc["last"] = seq
            proc["segments"].add(segment)
            proc["start"] |= row["kind"] == "start" or plugin.get("plugin_stage") == "competition"
            proc["terminal"] |= row["kind"] in TERMINALS or plugin.get("plugin_stage") in ("commit", "cancellation")
            state["bad"] |= row["kind"] in ("loss_notice", "exclusion_notice", "unknown_outcome")
            if evidence["excluded"]:
                exclusions.add(seq)
                if plugin.get("window_id") and plugin.get("group_id"):
                    group_exclusions.add(group)
                if plugin.get("window_id"):
                    window_exclusions.add(group[:3])
            if progress and len(metadata) % PAGE == 0:
                progress(len(metadata))
        intervals = [(v["first"], v["last"]) for v in segments.values()]
        intervals += [(v["first"], v["last"]) for v in processes.values()]
        # Recorded cross-source dependency edges also forbid a split. A token
        # without one exact owned update witness remains unknown, never a join.
        updates = {}
        owned_update_counts = Counter()
        for row in metadata:
            if row["update_id"]:
                owned_update_counts[(row["process"][0], row["update_id"])] += 1
                key = (row["process"][0], row["process"][1], row["update_id"])
                updates.setdefault(key, []).append(row["reference"]["durable_seq"])
        dependency_bad = set()
        by_seq = {r["reference"]["durable_seq"]: r for r in metadata}
        relation_rows = [{"durable_seq": r["reference"]["durable_seq"], "source_instance_id": r["process"][0],
                          "process_id": r["process"][1], "update_id": r["update_id"], "observation_kind": r["kind"],
                          "plugin": r["plugin"], "daemon": r["daemon"]} for r in metadata]
        relations = RelationContext(relation_rows)
        for row in metadata:
            plugin = row["plugin"]
            key = (plugin.get("referenced_source_id"), plugin.get("referenced_process_id"), plugin.get("referenced_update_id"))
            witnesses = updates.get(key, ())
            if len(witnesses) == 1:
                seq = row["reference"]["durable_seq"]
                intervals.append((min(seq, witnesses[0]), max(seq, witnesses[0])))
                if witnesses[0] in exclusions:
                    dependency_bad.add(seq)
            if plugin:
                request, plan, evidence = relations.request_link(row, plugin)
                row["request_relation"] = request
                row["plan_relation"] = plan
                if request["status"] == "linked":
                    other = request["evidence"]
                    seq = row["reference"]["durable_seq"]
                    intervals.append((min(seq, other), max(seq, other)))
                    row["scoring_source"] = by_seq[other]
                    if other in exclusions:
                        dependency_bad.add(seq)
        # No interval can be cut. Candidate cuts are O(N), prefix counts O(1).
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        uncertain_first = min((s["first"] for s in segments.values()
                               if not s["closed"] or s["bad"] or any(not processes[p]["start"] or not processes[p]["terminal"] or len(processes[p]["segments"]) != 1 for p in s["processes"])), default=pair["as_of_durable_seq"] + 1)
        cuts = [end for _, end in merged[:-1] if end < uncertain_first]
        n, first = len(metadata), pair["first_durable_seq"]
        # Minimize L1 deviation of cumulative .8/.9 targets with strict cuts;
        # ties resolve to the earliest durable pair. Linear suffix minimum.
        best, boundary = None, None
        suffix = []
        for cut in reversed(cuts):
            candidate = (abs(10 * (cut - first + 1) - 9 * n), cut)
            suffix.append(min(candidate, suffix[-1]) if suffix else candidate)
        suffix.reverse()
        for i, a in enumerate(cuts[:-1]):
            cost, b = suffix[i + 1]
            candidate = (abs(10 * (a - first + 1) - 8 * n) + cost, a, b)
            if best is None or candidate < best:
                best, boundary = candidate, (a, b)
        membership = {}
        counts = {name: Counter({p: 0 for p in PARTS}) for name in ("source", "corpus", "choice")}
        reasons, provenance, populations = Counter(), Counter(), Counter()
        eligible_counts = Counter({p: 0 for p in PARTS})
        for row in metadata:
            seq = row["reference"]["durable_seq"]
            part = "unassigned" if boundary is None else "train" if seq <= boundary[0] else "validation" if seq <= boundary[1] else "test"
            membership[seq] = part
            counts["source"][part] += 1
        # Context stores only source refs; target material is not cached here.
        # Context is one directly recorded parent commit, never inferred adjacency.
        update_commits, text_parts = {}, {"corpus": {}, "choice": {}}
        source_by_seq = {row["reference"]["durable_seq"]: row for row in metadata}
        for source, evidence in self.sources(pair):
            record, ref = source["record"], source["reference"]
            seq = ref["durable_seq"]
            row = source_by_seq[seq]
            part, state = membership[seq], segments[row["segment"]]
            proc = processes[row["process"]]
            issues = []
            if record.get("schema_id") != "luna_pinyin" or record.get("schema_interpretation") != "supported":
                issues.append("unsupported_or_unknown_schema")
            if part == "unassigned": issues.append("no_two_legal_whole_segment_cuts")
            if not state["closed"]: issues.append("open_segment")
            if state["bad"]: issues.append("unknown_or_incomplete_continuity")
            if any(not processes[p]["start"] or not processes[p]["terminal"] or len(processes[p]["segments"]) != 1 for p in state["processes"]):
                issues.append("incomplete_owned_process")
            if evidence["excluded"]: issues.append("excluded_source")
            if seq in dependency_bad: issues.append("excluded_recorded_source_dependency")
            if row["group"] in outside_groups:
                issues.append("group_dependency_outside_selected_source_range")
            if row["group"] in bounded_groups:
                issues.append("competition_dependency_bound")
            plugin = record.get("plugin") or {}
            choice = source.get("choice")
            if choice and choice.get("retracted"): issues.append("retracted")
            if choice and choice.get("request_outcome") != "engine_commit_observed":
                issues.append("group_outcome_not_normal")
            # Whole scoped group dependency, including excluded competition rows.
            if row["group"] in group_exclusions: issues.append("excluded_competition_dependency")
            if row["group"][:3] in window_exclusions:
                issues.append("excluded_captured_window_dependency")
            corpus_issues = list(issues)
            normal = record.get("observation_kind") == "commit_attempt" and record.get("outcome") == "observed_attempt" or plugin.get("plugin_stage") == "commit"
            if not normal: corpus_issues.append("not_normal_observed_commit")
            if evidence["private_values"]["effective_target"] is None: corpus_issues.append("target_unavailable")
            parent = (record["source_instance_id"], record.get("parent_update_id"))
            context = update_commits.get(parent) if owned_update_counts[parent] == 1 else None
            context_refs = []
            if context:
                parent_seq, parent_segment, parent_ref, admitted = context
                if parent_segment == row["segment"] and parent_seq < seq and membership[parent_seq] == part:
                    if not admitted:
                        corpus_issues.append("excluded_or_inadmissible_context_dependency")
                    else:
                        context_refs.append(parent_ref)
            corpus_ok = not corpus_issues
            private = evidence["private_values"]
            common = {"source_reference": ref, "partition": part,
                      "annotation_revision": pair["annotation_revision"],
                      "target_provenance": evidence["target_provenance"],
                      "human_revision": evidence["human_revision"],
                      "observed_target": private["observed_target"], "effective_target": private["effective_target"],
                      "host_persistence_proof": False, "objective_correctness_proof": False}
            if normal:
                populations["normal_commit_observations"] += 1
                populations["corpus_admitted"] += corpus_ok
                populations["corpus_not_admitted"] += not corpus_ok
                provenance[evidence["target_provenance"]] += 1
                for reason in corpus_issues: reasons["corpus:" + reason] += 1
            if corpus_ok:
                corpus = {**common, "context_source_references": context_refs,
                          "context_basis": "recorded_parent_update_to_earlier_same_segment_commit" if context_refs else "unavailable_no_supported_prior_commit_relation",
                          "submit_order": record["source_local_sequence"], "continuity_segment": list(row["segment"]),
                          "observation_scope": "engine_commit" if plugin else "frontend_commit_call",
                          "incompleteness": ["host_document_unknown", "host_persistence_unknown"]}
                self._emit(emit, "corpus.jsonl", corpus)
                counts["corpus"][part] += 1
                self._overlap(text_parts["corpus"], private["effective_target"], part)
            if normal and not plugin and record.get("update_id"):
                update_commits[(record["source_instance_id"], record["update_id"])] = (seq, row["segment"], ref, corpus_ok)
            choice_issues = list(issues)
            if plugin.get("plugin_stage") == "commit":
                structured, structured_issues = self.structured_choice(source, pair, retained_exclusions)
                structured["request_relation"] = row.get("request_relation")
                structured["plan_relation"] = row.get("plan_relation")
                scoring = row.get("scoring_source")
                structured["scoring_observation"] = {"source_reference": scoring["reference"], "daemon": scoring["daemon"]} if scoring else None
                choice_issues += structured_issues
                if not evidence["ranking_evaluation"]["evidence_eligible"]:
                    choice_issues.append("shared_annotation_ranking_evidence_ineligible")
                if evidence["target_provenance"] not in ("human_reviewed", "human_corrected", "observed_explicit_preference"):
                    choice_issues.append("unsupported_or_weak_label")
                # The shared annotation restriction is retained: outside/changed
                # human targets are not silently requalified for ranking.
                for reason in choice_issues: reasons["choice:" + reason] += 1
                populations["choice_commit_observations"] += 1
                populations["choice_eligible"] += not choice_issues
                populations["choice_not_eligible"] += bool(choice_issues)
                if not choice_issues: eligible_counts[part] += 1
                choice_row = {**common, "eligible": not choice_issues, "reasons": sorted(set(choice_issues)),
                              "shared_projection": choice, "captured": structured,
                              "unselected_candidate_labels": "not_asserted"}
                # Excluded dependencies are never exported as training content.
                if not any("excluded" in reason or "outside_selected_source_range" in reason for reason in choice_issues):
                    self._emit(emit, "choice.jsonl", choice_row)
                    counts["choice"][part] += 1
                    self._overlap(text_parts["choice"], private["effective_target"], part)
            partition = {"source_reference": ref, "partition": part, "segment": list(row["segment"]),
                         "process": list(row["process"]), "source_reasons": sorted(set(issues)),
                         "corpus_admitted": corpus_ok,
                         "choice_eligible": plugin.get("plugin_stage") == "commit" and not choice_issues}
            self._emit(emit, "partition.jsonl", partition)
        source_id = source_hash.hexdigest()
        if source_id != pair["source_content_identity"]:
            raise InterfaceError("annotation_source_mismatch")
        overlaps = {}
        for view, texts in text_parts.items():
            overlaps[view] = {"distinct_equal_target_hashes_cross_partition": sum(len(parts) > 1 for parts in texts.values()),
                              "rule": "sha256_of_exact_utf8_effective_target_distinct_partition_sets; genuine_repeats_retained"}
        output = {"version": VERSION, "rule": RULE, "code_identity": code_identity(),
                  "source": pair, "source_content_identity": source_id,
                  "choice_projection_version": CHOICE_PROJECTION_VERSION,
                  "boundary": list(boundary) if boundary else None,
                  "ordering": "durable_seq; overlapping_scoped_segment_and_process_intervals_indivisible; earliest_L1_cumulative_80_90_cut_tie",
                  "outcome": "bounded_unusable" if reasons["choice:group_expansion_bound_or_missing_identity"] else "usable" if boundary and all(counts["corpus"][p] for p in PARTS) else "unusable",
                  "counts": {name: {"unit": "durable_source_observation" if name == "source" else "exported_row", "total": sum(values.values()), "by_partition": dict(values), "proportions": {p: values[p] / sum(values.values()) if sum(values.values()) else None for p in PARTS}} for name, values in counts.items()},
                  "reasons": dict(sorted(reasons.items())), "label_counts": dict(sorted(provenance.items())),
                  "populations": {"unit": "source_commit_observation", "counts": dict(populations),
                                  "choice_eligible_by_partition": dict(eligible_counts),
                                  "reason_count_unit": "source_commit_reason_incidence; reasons_may_overlap",
                                  "exclusion_source_observations": len(exclusions)},
                  "equal_text_overlap": overlaps, "distinct_source_identity_cross_partition_overlap": 0,
                  "bounds": {"source_metadata_max": MAX_SOURCES, "reference_page_max": PAGE, "payload_rows_buffered": 1,
                             "source_record_bytes_max": SOURCE_LINE,
                             "group_payload_rows_max": self.collector.limits["query_group_members_max"], "output_line_bytes_max": LINE},
                  "work": {"source_pass_rows": 2 * len(metadata), "source_metadata_entries": len(metadata),
                           "scoped_segments": len(segments), "scoped_processes": len(processes), "legal_boundary_count": len(cuts)},
                  "non_claims": ["statistical_adequacy", "prospective_untouched_confirmation", "host_document", "model_benefit", "total_RAM_independence"]}
        return output

    @staticmethod
    def _overlap(index, text, part):
        if text is not None:
            index.setdefault(hashlib.sha256(text.encode()).hexdigest(), set()).add(part)

    @staticmethod
    def _emit(emit, name, value):
        try:
            raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        except (ValueError, UnicodeError):
            raise InterfaceError("dataset_corrupt")
        if len(raw) > LINE:
            raise InterfaceError("dataset_bound")
        if emit:
            emit(name, raw)

    def structured_choice(self, source, pair, retained_exclusions):
        """Copy actual structured evidence; no text join or reconstructed members."""
        c, record = self.collector, source["record"]
        plugin = record.get("plugin") or {}
        refs = c._dataset_window_refs(record, pair["as_of_durable_seq"])
        if refs is None:
            return {"observations": [], "scoring_input": None}, ["group_expansion_bound_or_missing_identity"]
        if any(ref["durable_seq"] < pair["first_durable_seq"] for ref in refs):
            return {"observations": [], "scoring_input": None}, ["group_dependency_outside_selected_source_range"]
        observed, reasons = [], []
        for ref in refs:
            other = c._dataset_source(ref, pair["as_of_durable_seq"], SOURCE_LINE, include_choice=False)
            with c._annotations.lock:
                edits = c._annotations.effective(ref, pair["annotation_revision"])
            if "exclude" in edits:
                return {"observations": [], "scoring_input": None}, ["excluded_competition_dependency"]
            payload = other["record"].get("payload")
            # Captured preceding text has no complete source-reference vector.
            # Once ANY retained exclusion exists, absence of an exact context
            # dependency is not permission to copy that private context. Omit
            # this dependent example (not a text-matching reconstruction).
            if retained_exclusions and isinstance(payload, dict) and payload.get("preceding_text"):
                return {"observations": [], "scoring_input": None}, ["excluded_or_unknown_captured_context_dependency"]
            observed.append({"source_reference": ref, "stage": (other["record"].get("plugin") or {}).get("plugin_stage"), "payload": payload})
        complete = []
        for item in observed:
            payload = item["payload"]
            if not isinstance(payload, dict): continue
            candidates, groups = payload.get("candidates"), payload.get("groups")
            if not isinstance(candidates, list) or not isinstance(groups, list): continue
            if not known_text(payload.get("input")): continue
            for group in groups:
                if not isinstance(group, dict) or group.get("identity") != plugin.get("group_id"): continue
                if (type(group.get("start")) is not int or type(group.get("end")) is not int
                        or not 0 <= group["start"] <= group["end"] or not known_text(group.get("category"))
                        or group.get("plan_complete") is not True): continue
                indexes = group.get("member_indexes")
                if not isinstance(indexes, list) or not indexes or any(type(i) is not int or i < 0 or i >= len(candidates) for i in indexes) or len(set(indexes)) != len(indexes): continue
                members = [candidates[i] for i in indexes]
                if any(not isinstance(m, dict) or (m.get("start"), m.get("end"), m.get("category")) != (group.get("start"), group.get("end"), group.get("category")) for m in members): continue
                if any(type(m.get("start")) is not int or type(m.get("end")) is not int
                       or not known_text(m.get("text")) or type(m.get("merge_order")) is not int
                       or m["merge_order"] < 0 for m in members): continue
                if len(indexes) != plugin.get("group_member_count"): continue
                if private_target(source) not in [m.get("text") for m in members]: continue
                if not all(isinstance(payload.get(name), list) and all(type(i) is int for i in payload[name]) and sorted(payload[name]) == list(range(len(candidates))) for name in ("upstream_order", "emission_order")): continue
                complete.append(sha({"members": [{k: m.get(k) for k in ("text", "start", "end", "category", "merge_order")} for m in members], "span": [group.get("start"), group.get("end")], "category": group.get("category")}))
        if not complete: reasons.append("structured_members_orders_target_unavailable")
        if len(set(complete)) > 1: reasons.append("conflicting_structured_members")
        return {"observations": observed, "scoring_input": None,
                "scoring_input_basis": "not_reconstructed_from_preceding_text_or_plan",
                "request_identity": plugin.get("lm_request_id"), "plan_identity": plugin.get("plan_identity"),
                "model_identity": None, "policy_identity": None}, reasons

    def current(self, manifest, job_id=None):
        pair = manifest["source"]
        restored_historical = job_id in getattr(self.collector, "_historical_dataset_ids", set())
        try:
            if manifest.get("code_identity") != code_identity():
                return {"current_policy_consistent": None, "default_training_candidate": False, "tool_compatibility": "incompatible"}
            self.snapshot(pair)
            with self.collector._annotations.lock:
                revision = self.collector._annotations.revision
                conflicts = sum(key[2] == "exclude" and pair["annotation_revision"] < history[0][0] <= revision
                                for key, history in self.collector._annotations.history.items())
            content = hashlib.sha256()
            for source, evidence in self.sources({**pair, "annotation_revision": revision}, choices=False):
                content.update(canonical_bytes({"reference": source["reference"]}) + b"\n")
            if content.hexdigest() != manifest["source_content_identity"]:
                return {"current_policy_consistent": None, "default_training_candidate": False, "source_compatibility": "changed"}
            with self.collector._annotations.lock:
                if self.collector._annotations.revision != revision:
                    return {"current_annotation_revision": revision, "current_policy_consistent": None,
                            "default_training_candidate": False, "reason": "annotation_changed_during_check"}
            return {"current_annotation_revision": revision, "exclusion_conflicts": conflicts,
                    "exclusion_conflict_rule": "conservative_any_new_archive_exclusion_including_unknown_context_dependencies",
                    "current_policy_consistent": conflicts == 0,
                    "default_training_candidate": not restored_historical and conflicts == 0 and manifest["outcome"] == "usable",
                    **({"historical_restored_freeze": True, "default_candidacy_reason": "historical_restore_is_not_a_new_training_freeze"} if restored_historical else {})}
        except (InterfaceError, OSError, UnsafeRoot):
            return {"current_policy_consistent": None, "default_training_candidate": False, "source_compatibility": "unavailable"}

    def call(self, body):
        if self.error:
            raise InterfaceError(self.error)
        allowed = {"dataset_version", "action", "job_id", "operation_id", "snapshot", "after", "page_size", "artifact", "private_detail", "include_test"}
        if set(body) - allowed or body.get("dataset_version") != VERSION:
            raise InterfaceError("dataset_incompatible" if body.get("dataset_version") != VERSION else "invalid_request")
        action = body.get("action")
        if action == "snapshot":
            return {"snapshot": self.snapshot(body.get("snapshot") or {}), "dataset_version": VERSION}
        if action == "preview":
            result = self.inspect(body.get("snapshot") or {})
            return {**result, "current": self.current(result)}
        if action == "create":
            return self.create(body)
        if action == "list":
            after, size = body.get("after", 0), body.get("page_size", 20)
            if type(after) is not int or after < 0 or type(size) is not int or not 1 <= size <= PAGE:
                raise InterfaceError("invalid_request")
            with self.lock:
                ids = self.ids()
                page = [self.status(job_id) for job_id in ids[after:after + size]]
            return {"jobs": page, "next_after": after + size if after + size < len(ids) else None}
        job_id = body.get("job_id")
        if action == "status":
            return self.status(job_id)
        if action == "cancel":
            with self.lock:
                job = self.load(job_id)
                if job["state"] == "succeeded":
                    raise InterfaceError("dataset_already_published")
                if job_id == self.active:
                    self.cancelled.set()
                    job["cancel_requested"] = True
                    self.save(job)
                elif job["state"] in ("pending", "unknown"):
                    job["state"], job["reason"] = "cancelled", "cancelled_before_publication"
                    self.save(job)
                return self.summary(job)
        if action == "verify":
            return self.verify(job_id)
        if action == "private":
            return self.private(body)
        raise InterfaceError("invalid_request")

    def create(self, body):
        if safe_token(body.get("operation_id")) is None or not isinstance(body.get("snapshot"), dict):
            raise InterfaceError("invalid_request")
        pair = self.snapshot(body["snapshot"])
        # Explicit pair required: a retry never substitutes current state.
        if set(body["snapshot"]) != set(pair):
            raise InterfaceError("invalid_request")
        request = {"snapshot": pair, "version": VERSION, "rule": RULE, "code_identity": code_identity()}
        request_digest = sha(request)
        job_id = sha({"archive_id": pair["archive_id"], "operation_id": body["operation_id"]})
        with self.lock:
            if not os.path.lexists(self.root):
                os.mkdir(self.root, 0o700)
                sync_dir(self.root.parent)
            check_dir(self.root)
            if job_id in self.ids():
                job = self.load(job_id)
                if job["request_digest"] != request_digest:
                    raise InterfaceError("dataset_operation_conflict")
                return {**self.status(job_id), "replayed": True}
            if self.active is not None:
                raise InterfaceError("dataset_busy")
            if len(self.ids()) >= MAX_JOBS:
                raise InterfaceError("dataset_bound")
            path = self.root / job_id
            os.mkdir(path, 0o700)
            sync_dir(self.root)
            job = {"version": VERSION, "job_id": job_id, "request": request, "request_digest": request_digest,
                   "state": "pending", "progress_sources": 0, "reason": None, "cancel_requested": False,
                   "registry": [{"owner": job_id, "path": name, "state": "reserved", "sha256": None, "size": None,
                                 "dependencies": pair} for name in (*FILES, "manifest.json")]}
            self.save(job)  # durable request acknowledgement; not successful data
            self.active = job_id
            self.cancelled.clear()
            self.thread = threading.Thread(target=self.run, args=(job_id,), daemon=True)
            self.thread.start()
            return {**self.summary(job), "replayed": False, "acknowledgement": "durable_request_not_completed_freeze"}

    def summary(self, job):
        return {"dataset_version": VERSION, "job_id": job["job_id"], "state": job["state"],
                "progress_sources": job["progress_sources"], "reason": job["reason"],
                "request_digest": job["request_digest"], "cancel_requested": job["cancel_requested"],
                "registry": job["registry"], "content_included": False}

    def status(self, job_id):
        with self.lock:
            job = self.load(job_id)
            result = self.summary(job)
            if job_id in self.uncertain:
                return {**result, "state": "unknown", "reason": "publication_durability_unknown_until_restart"}
            if job["state"] == "succeeded":
                manifest = self.manifest(job)
                for item in job["registry"]:
                    if self.file_digest(self.path(job_id) / item["path"]) != (item["size"], item["sha256"]):
                        raise InterfaceError("dataset_corrupt")
                result.update({"outcome": manifest["outcome"], "counts": manifest["counts"],
                                "current": self.current(manifest, job_id), "manifest_identity": sha(manifest)})
            return result

    def run(self, job_id):
        handles = {}
        try:
            with self.lock:
                job = self.load(job_id)
                job["state"] = "running"
                self.save(job)
            path = self.path(job_id)
            hashes = {name: hashlib.sha256() for name in FILES}
            sizes = Counter()
            for name in FILES:
                handles[name] = os.open(path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)

            def progress(seq):
                if self.cancelled.is_set():
                    raise Cancelled()
                with self.lock:
                    if self.cancelled.is_set():
                        raise Cancelled()
                    job["progress_sources"] = seq
                    self.save(job)

            def emit(name, raw):
                if self.cancelled.is_set():
                    raise Cancelled()
                write_all(handles[name], raw)
                hashes[name].update(raw)
                sizes[name] += len(raw)

            manifest = self.inspect(job["request"]["snapshot"], emit, progress)
            for fd in handles.values():
                os.fsync(fd)
            for fd in handles.values():
                os.close(fd)
            handles = {}
            manifest["artifacts"] = {name: {"sha256": hashes[name].hexdigest(), "size": sizes[name]} for name in FILES}
            manifest["freeze_identity"] = job["request_digest"]
            fd = os.open(path / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                write_all(fd, canonical_bytes(manifest))
                os.fsync(fd)
            finally:
                os.close(fd)
            sync_dir(path)
            with self.lock:
                if self.cancelled.is_set():
                    raise Cancelled()
                for artifact in job["registry"]:
                    size, digest = self.file_digest(path / artifact["path"])
                    artifact.update(state="published", size=size, sha256=digest)
                job["state"] = "succeeded"
                job["progress_sources"] = manifest["counts"]["source"]["total"]
                self._publish_success(job)
        except BaseException as exc:
            for fd in handles.values():
                os.close(fd)
            try:
                with self.lock:
                    # A late failure after the publication marker cannot undo it.
                    durable = self.load(job_id)
                    if durable["state"] != "succeeded":
                        durable["state"] = "cancelled" if isinstance(exc, Cancelled) else "failed"
                        durable["reason"] = "cancelled_before_publication" if isinstance(exc, Cancelled) else exc.code if isinstance(exc, InterfaceError) else "dataset_write_failed"
                        for artifact in durable["registry"]:
                            p = self.path(job_id) / artifact["path"]
                            if os.path.lexists(p):
                                size, digest = self.file_digest(p)
                                artifact.update(state="incomplete", size=size, sha256=digest)
                            else:
                                artifact["state"] = "not_created"
                        self.save(durable)
                    else:
                        self.uncertain.add(job_id)
            except (OSError, InterfaceError, UnsafeRoot, ValueError, TypeError):
                pass  # durable running -> unknown on restart; never fabricated success
        finally:
            with self.lock:
                self.active = None

    def _publish_success(self, job):
        self.save(job)

    @staticmethod
    def file_digest(path):
        check_file(path)
        h, size = hashlib.sha256(), 0
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            for raw in iter(lambda: f.read(65536), b""):
                size += len(raw)
                h.update(raw)
        return size, h.hexdigest()

    def manifest(self, job):
        if job["state"] != "succeeded":
            raise InterfaceError("dataset_not_published")
        path = self.path(job["job_id"]) / "manifest.json"
        entry = next(x for x in job["registry"] if x["path"] == "manifest.json")
        if self.file_digest(path) != (entry["size"], entry["sha256"]):
            raise InterfaceError("dataset_corrupt")
        manifest = read_json(path)
        if manifest.get("version") != VERSION or manifest.get("rule") != RULE:
            raise InterfaceError("dataset_incompatible")
        if manifest.get("freeze_identity") != job["request_digest"] or manifest.get("source") != job["request"]["snapshot"] or set(manifest.get("artifacts", {})) != set(FILES):
            raise InterfaceError("dataset_corrupt")
        registry = job["registry"]
        if not isinstance(registry, list) or len(registry) != 4 or {x.get("path") for x in registry} != {*FILES, "manifest.json"}:
            raise InterfaceError("dataset_corrupt")
        for item in registry:
            if item.get("owner") != job["job_id"] or item.get("dependencies") != manifest["source"] or item.get("state") != "published":
                raise InterfaceError("dataset_corrupt")
        return manifest

    def verify(self, job_id):
        if job_id in self.uncertain:
            raise InterfaceError("dataset_not_published")
        job = self.load(job_id)
        manifest = self.manifest(job)
        if manifest.get("code_identity") != code_identity():
            raise InterfaceError("dataset_incompatible")
        for item in job["registry"]:
            size, digest = self.file_digest(self.path(job_id) / item["path"])
            if size != item["size"] or digest != item["sha256"]:
                raise InterfaceError("dataset_corrupt")
        # Semantic verification recomputes streams into hashes only. No writes,
        # normalization, repair, copied source history or artifact-only success.
        hashes = {name: hashlib.sha256() for name in FILES}
        sizes = Counter()
        def emit(name, raw):
            hashes[name].update(raw)
            sizes[name] += len(raw)
        expected = self.inspect(manifest["source"], emit)
        expected["artifacts"] = {name: {"sha256": hashes[name].hexdigest(), "size": sizes[name]} for name in FILES}
        expected["freeze_identity"] = job["request_digest"]
        if manifest != expected:
            raise InterfaceError("dataset_corrupt")
        return {"verification": "semantic_source_annotation_partition_admission_and_artifacts", "verified": True,
                "outcome": manifest["outcome"], "manifest_identity": sha(manifest), "current": self.current(manifest, job_id)}

    def private(self, body):
        if body.get("private_detail") is not True or type(body.get("include_test", False)) is not bool or body.get("artifact") not in FILES:
            raise InterfaceError("invalid_request")
        job = self.load(body.get("job_id"))
        self.manifest(job)
        after, size = body.get("after", 0), body.get("page_size", 1)
        if type(after) is not int or after < 0 or type(size) is not int or not 1 <= size <= 4:
            raise InterfaceError("invalid_request")
        path = self.path(job["job_id"]) / body["artifact"]
        check_file(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        result, position, total = [], after, 0
        with os.fdopen(fd, "rb") as f:
            i = -1
            while True:
                raw = f.readline(LINE + 1)
                if not raw: break
                i += 1
                if len(raw) > LINE: raise InterfaceError("dataset_bound")
                if i < after: continue
                row = json.loads(raw)
                position = i + 1
                if row.get("partition") == "test" and not body.get("include_test", False): continue
                total += len(raw)
                if total > 1048576: raise InterfaceError("page_bytes_bound")
                result.append(row)
                if len(result) == size: break
        return {"rows": result, "next_after": position if result else None, "test_hidden": not body.get("include_test", False), "content_included": True}


def private_target(source):
    return source.get("observed_target")
