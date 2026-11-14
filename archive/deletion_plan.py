"""Read-only exact-reference selection and bounded registered impact planning."""

from __future__ import annotations

import json
from pathlib import Path

from archive import management_io as io
from archive.deletion_authority import VERSION, capture_key
from archive.deletion_inventory import Inventory, MAX_DEPTH
from archive.deletion_lineage import Lineage, joined
from archive.interface import InterfaceError, canonical_bytes
from archive.management import CORE, LINE

MAX_SELECTED = 8192
MAX_OBSERVATIONS = 65536
EXCLUDED = {"legacy_facts_semantic_memory_traces_old_datasets": "separate_domain",
            "models_and_tokenizers": "outside_archive_authority",
            "unmanaged_and_external_copies": "not_scanned_not_erased",
            "system_backups_APFS_SSD_and_process_memory": "no_erasure_guarantee",
            "current_capture_policy": "preserved",
            "source_registration_and_restore_fences": "preserved",
            "nonrollback_removal_authority": "preserved_content_free",
            "unpublished_or_never_observed_input": "not_reconstructed"}


def records(path, length=None):
    with io.open_read(path) as stream:
        count = 0
        while True:
            if length is not None and stream.tell() == length:
                return
            raw = stream.readline(LINE + 1)
            if not raw:
                if length is not None and stream.tell() != length:
                    raise InterfaceError("deletion_stale")
                return
            count += 1
            if count > MAX_OBSERVATIONS or len(raw) > LINE or not raw.endswith(b"\n"):
                raise InterfaceError("deletion_bound")
            if length is not None and stream.tell() > length:
                raise InterfaceError("deletion_stale")
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise InterfaceError("deletion_unknown_lineage")
            yield row, raw


class Planner:
    def __init__(self, deletion):
        self.deletion = deletion
        self.c = deletion.c

    def frontier(self):
        c = self.c
        with c._annotations.lock:
            c._annotations._healthy()
            annotation = c._annotations._manifest()
            with c._lock:
                if c._queue or c._publishing_units or c._state["storage_failure"]:
                    raise InterfaceError("management_busy")
                if c._state["durable_seq"] > MAX_OBSERVATIONS or len(c._index) > MAX_OBSERVATIONS:
                    raise InterfaceError("deletion_bound")
                value = {"archive_id": c._annotations.archive_id,
                         "durable_seq": c._state["durable_seq"], "durable_offset": c._state["durable_offset"],
                         "collector_epoch": c._state["collector_epoch"],
                         "serving_generation": c._management.authority.value["generation"],
                         "policy_revision": c._policy["revision"], "annotation": annotation,
                          "removal_revision": self.deletion.authority.value["revision"]}
                value["source_content_identity"] = Lineage.reference_hash(c._dataset_reference(row) for row in c._index)
        return value

    def selection(self, selection):
        c = self.c
        if not isinstance(selection, dict) or len(selection) != 2 or type(selection.get("serving_generation")) is not int:
            raise InterfaceError("invalid_request")
        if selection["serving_generation"] != c._management.authority.value["generation"]:
            raise InterfaceError("deletion_stale")
        if "references" in selection:
            refs = selection["references"]
            if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_SELECTED:
                raise InterfaceError("deletion_bound")
        elif "range" in selection:
            span = selection["range"]
            if not isinstance(span, dict) or set(span) != {"first", "last"}:
                raise InterfaceError("invalid_request")
            for endpoint in span.values():
                self.reference(endpoint)
            first, last = span["first"]["durable_seq"], span["last"]["durable_seq"]
            if first > last:
                raise InterfaceError("invalid_request")
            refs = [c._dataset_reference(entry) for entry in c._index if first <= entry["durable_seq"] <= last]
            if not 1 <= len(refs) <= MAX_SELECTED:
                raise InterfaceError("deletion_bound")
        else:
            raise InterfaceError("invalid_request")
        seen, result = set(), []
        for ref in refs:
            self.reference(ref)
            key = capture_key(ref["source_instance_id"], ref["source_local_sequence"])
            if key in seen:
                raise InterfaceError("deletion_operation_conflict")
            seen.add(key)
            result.append(dict(ref))
        return sorted(result, key=lambda ref: ref["durable_seq"])

    def reference(self, ref):
        # The legacy observation reader calls open_nofollow(), which normalizes
        # file modes even on read. Deletion preview must neither repair input nor
        # change ctime and then invalidate its own exact path binding.
        c = self.c
        c._annotations._reference_shape(ref)
        matches = c._annotation_sources.get((ref["source_instance_id"], ref["source_local_sequence"]), ())
        if not matches:
            raise InterfaceError("not_found")
        if len(matches) != 1 or c._dataset_reference(matches[0]) != ref:
            raise InterfaceError("annotation_source_mismatch")
        entry = matches[0]
        if entry["length"] > LINE:
            raise InterfaceError("deletion_bound")
        with io.open_read(Path(c.observations_path)) as stream:
            stream.seek(entry["offset"])
            raw = stream.read(entry["length"])
        from archive.annotations import digest
        row = json.loads(raw)
        semantic = {key: value for key, value in row.items() if key not in {"record_version", "durable_seq", "content_hash", "identity", "host_persistence", "host_persistence_proof"}}
        if row.get("record_version") != 1 or row.get("identity") != [ref["source_instance_id"], ref["source_local_sequence"]] or digest(semantic) != row.get("content_hash") or digest(row) != ref["record_digest"]:
            raise InterfaceError("annotation_source_mismatch")

    def closure(self, selected):
        """Only explicit source-owned relation identities, never equal text."""
        c = self.c
        selected_keys = {capture_key(ref["source_instance_id"], ref["source_local_sequence"]) for ref in selected}
        included = {row["durable_seq"] for row in c._index
                    if capture_key(row["source_instance_id"], row["source_local_sequence"]) in selected_keys}
        edges = {}
        for row in c._index:
            owner = (row["source_instance_id"], row["process_id"])
            keys = [("update", row.get("update_id")), ("update", row.get("parent_update_id")),
                    ("commit", row.get("commit_id")), ("window", (row.get("plugin") or {}).get("window_id"))]
            for kind, value in keys:
                if value is not None:
                    edges.setdefault((owner, kind, value), set()).add(row["durable_seq"])
        # Relation metadata is bounded by the existing durable index. The number
        # of rounds is independently bounded; overflow is refusal, not truncation.
        groups = list(edges.values())
        updates = {}
        for row in c._index:
            if row.get('update_id'):
                updates.setdefault((row['source_instance_id'], row['update_id']), []).append(row)
        for row in c._index:
            plugin = row.get('plugin') or {}
            parent = (row['source_instance_id'], row.get('parent_update_id'))
            referenced = (plugin.get('referenced_source_id'), plugin.get('referenced_update_id'))
            for key in (parent, referenced):
                witnesses = updates.get(key, ())
                if len(witnesses) == 1:
                    groups.append({row['durable_seq'], witnesses[0]['durable_seq']})
        for depth in range(MAX_DEPTH + 1):
            enlarged = set(included)
            for group in groups:
                if included.intersection(group):
                    enlarged.update(group)
            if enlarged == included:
                break
            if depth == MAX_DEPTH:
                raise InterfaceError("deletion_bound")
            included = enlarged
        if len(included) > MAX_SELECTED:
            raise InterfaceError("deletion_bound")
        result = [c._dataset_reference(row) for row in c._index if row["durable_seq"] in included]
        return result, len(groups)

    def preview(self, selection):
        c = self.c
        with c._content_gate:
            before = self.frontier()
            selected = self.selection(selection)
            removed, groups = self.closure(selected)
            inventory = Inventory(c).collect()
            # Unknown quarantine cannot be attributed by a content hash alone.
            # No whole-file collateral is silently invented to hide this gap.
            for source in inventory["sources"]:
                quarantine = self.deletion.resolve(source["path"]) / "quarantine.jsonl"
                if quarantine.exists() and io.regular(quarantine).st_size:
                    raise InterfaceError("deletion_unknown_lineage")
            capture_keys = {capture_key(ref["source_instance_id"], ref["source_local_sequence"]) for ref in removed}
            current = str(Path(c.content_root).relative_to(Path(c.root)))
            current = "" if current == "." else current + "/"
            lineage = Lineage(self.deletion, inventory, removed)
            affected = lineage.resolve()
            current_root = current.rstrip("/") or "."
            affected_sources = {source["path"] for source in inventory["sources"]
                                if source["path"] in affected and source["path"] != current_root
                                and not source["path"].endswith("/backup")
                                and source['lifecycle'] not in ('reserved', 'incomplete', 'not_created')}
            affected_owners = affected - affected_sources - {current_root}
            actions = []
            for file in inventory["files"]:
                name = file["path"]
                edges = [edge for edge in inventory["edges"] if edge["path"] == name]
                if name in {current + part for part in ("observations.jsonl", "annotations.jsonl", "annotation-state.json", "state.json")}:
                    action, reason = "survivor_rewrite", "exact_capture_and_associated_annotation_removal"
                elif any(name.startswith(owner + "/") for owner in affected_owners):
                    action, reason = "unlink", "confirmed_whole_immutable_or_incomplete_artifact"
                elif any(name == joined(source, part) for source in affected_sources for part in CORE):
                    action, reason = "unlink", "confirmed_whole_retired_source_core"
                else:
                    continue
                actions.append({**file, "action": action, "reason": reason,
                                "owners": sorted({edge["owner"] for edge in edges})})
            annotation_revisions = []
            # Stream payload-bearing history without collecting annotation bodies.
            for row, _ in records(Path(c.content_root) / "annotations.jsonl"):
                ref = row["semantic"]["source_reference"]
                if capture_key(ref["source_instance_id"], ref["source_local_sequence"]) in capture_keys:
                    annotation_revisions.append(row["revision"])
            # A payload with unbound captured context cannot be proved unrelated
            # merely because its text differs. Surface this finite supported
            # unknown instead of inventing lineage or a producer lifecycle change.
            for row, _ in records(Path(c.content_root) / "observations.jsonl"):
                payload = row.get("payload")
                if isinstance(payload, dict) and payload.get("preceding_text") and capture_key(row['source_instance_id'], row['source_local_sequence']) not in capture_keys:
                    raise InterfaceError("deletion_unknown_lineage")
            if self.frontier() != before:
                raise InterfaceError("deletion_stale")
            primary = {ref["durable_seq"] for ref in selected}
            losses = []
            for action in actions:
                if action["action"] != "unlink":
                    continue
                units, tail = 0, False
                path = self.deletion.resolve(action["path"])
                if path.suffix == ".jsonl":
                    with io.open_read(path) as stream:
                        for chunk in iter(lambda: stream.read(io.CHUNK), b""):
                            units += chunk.count(b"\n")
                            tail = not chunk.endswith(b"\n")
                    unit = "complete_line_units_and_optional_partial_unit_not_semantic_compatibility"
                else:
                    units, unit = 1, "whole_file"
                losses.append({"path": action["path"], "owners": action["owners"],
                               "bytes": action["binding"]["size"], "unit": unit,
                               "units": units, "partial_trailing_unit": tail,
                               "scope": "entire_artifact_including_unselected_content"})
            plan = {"version": VERSION, "selection": selection, "selected": selected,
                    "removed_references": removed,
                    "collateral_references": [ref for ref in removed if ref["durable_seq"] not in primary],
                    "annotation_revisions": annotation_revisions, "frontier": before,
                    "inventory_identity": io.digest(inventory), "inventory": inventory,
                    "actions": actions, "whole_artifact_owners": sorted(affected_owners),
                    "whole_retired_sources": sorted(affected_sources), "excluded_domains": EXCLUDED,
                    "whole_artifact_losses": losses,
                    "counts": {"selected": len(selected), "collateral_observations": len(removed) - len(selected),
                               "annotation_revisions": len(annotation_revisions), "files": len(actions),
                               "confirmed_input_bytes": sum(item["binding"]["size"] for item in actions),
                               "whole_artifacts": len(affected_owners), "whole_retired_sources": len(affected_sources)},
                     "work": {"relation_groups": groups, "source_record_buffer_bytes": LINE,
                              "lineage_records_scanned": lineage.scanned,
                              "lineage_metadata_entries": lineage.metadata,
                              "selected_reference_bound": MAX_SELECTED}}
            if len(canonical_bytes(plan)) > min(io.DOCUMENT, c.limits["max_frame_bytes"] - 4096):
                raise InterfaceError("deletion_bound")
            return {"plan": plan, "plan_identity": io.digest(plan), "available": True, "content_included": False}
