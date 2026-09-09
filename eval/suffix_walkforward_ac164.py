#!/usr/bin/env python3
"""AC-164-v1 identity pin for the 3000-milestone exact suffix walk-forward.

The scoring, grid, gates and terminals stay on the accepted AC-159 seam.
This module binds the immutable AC-162 snapshot, split and Qwen3
reference-route entry census, and refuses a later live backup.
"""

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

from actionable_milestone_census import (
    CensusError, split_hashes as census_split_hashes)
from public_layer_slicer import canonical_json
from shortlist_cc import (
    TERMINAL_EXACT, TERMINAL_INSUFFICIENT, TERMINAL_NARROWED,
    TERMINAL_NO_QUALIFIED)
from walkforward_cc import (
    BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, CONTRACT_ID as ENGINE_CONTRACT,
    ENGINE_VERSION as ENGINE_SEAM_VERSION, PREFIX_HLC_MAX_INCLUSIVE,
    ROUTE_IDS)


CONTRACT_ID = "AC-164-v1"
ENGINE_VERSION = ENGINE_SEAM_VERSION
PINNED_SNAPSHOT_SHA256 = (
    "111517b4548ad97cb73c801a3099076d70f90afc36bf94eb13f3fd1121cd94f5")
PINNED_HISTORY_ID = "dc3ffbf1a21957e0bb4ceed535c9df56"
PINNED_STORE_EPOCH = "8407bd6b456ba5c5a526b4b95951bac3"
PINNED_PREFIX_EVENT_COUNT = 4844
PINNED_SUFFIX_EVENT_COUNT = 3901
PINNED_PREFIX_SHA256 = (
    "e50349a8630a9505c667569bde93c5bbfc9b1206d28c51d0ec5c80d96bb201a1")
PINNED_SUFFIX_SHA256 = (
    "9a7dd8b9444a397431a6c0212cfa2379dcfdac5f5a1cefc7150a1324cf3bb7a2")
ENTRY_CENSUS = {
    "prefix_actionable_group_complete": 2537,
    "suffix_actionable_group_complete": 2370,
    "total_actionable_group_complete": 4907,
    "prefix_actionable_keys": 421,
    "suffix_actionable_keys": 479,
    "total_actionable_keys": 611,
}
LEGAL_TERMINALS = (
    TERMINAL_EXACT, TERMINAL_NARROWED, TERMINAL_NO_QUALIFIED,
    TERMINAL_INSUFFICIENT)
HISTORICAL_RELATIVE_DIRS = (
    "suffix_walkforward",
    "suffix_walkforward_ac159",
    "actionable_milestone_census",
)
SNAPSHOT_COPY_NAME = "facts-snapshot-ac162.sqlite3"
QWEN3_ROUTE_ID = ROUTE_IDS[0]


class Ac164Error(Exception):
    """A frozen AC-164 identity or census invariant failed."""


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_meta(path):
    conn = sqlite3.connect(path, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only = 1")
        return dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()


def isolate_readonly_snapshot(source, dest_dir):
    """Copy only the sqlite bytes into an empty dir (no WAL/SHM)."""
    source = Path(source)
    if not source.is_file():
        raise Ac164Error("preserved AC-162 snapshot not found")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / SNAPSHOT_COPY_NAME

    def _unlink_sidecars(path):
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                os.chmod(sidecar, 0o644)
                sidecar.unlink()

    if source.resolve() == dest.resolve():
        _unlink_sidecars(dest)
        return dest
    if dest.exists():
        os.chmod(dest, 0o644)
        dest.unlink()
    _unlink_sidecars(dest)
    shutil.copyfile(str(source), str(dest))
    return dest


def bind_preserved_snapshot(path, *, fixture=False):
    """Fail-closed snapshot identity. Real runs refuse any other bytes."""
    path = Path(path)
    if not path.is_file():
        raise Ac164Error("preserved AC-162 snapshot not found")
    try:
        sha = file_sha256(path)
        identity = open_meta(str(path))
    except sqlite3.DatabaseError as error:
        raise Ac164Error("snapshot is not a readable facts store") from error
    history_id = identity.get("history_id")
    store_epoch = identity.get("store_epoch")
    if not history_id or not store_epoch:
        raise Ac164Error("snapshot meta missing history_id/store_epoch")
    if not fixture:
        if sha != PINNED_SNAPSHOT_SHA256:
            raise Ac164Error(
                "snapshot SHA-256 mismatch; refuse a later live backup")
        if history_id != PINNED_HISTORY_ID:
            raise Ac164Error("snapshot history_id mismatch")
        if store_epoch != PINNED_STORE_EPOCH:
            raise Ac164Error("snapshot store_epoch mismatch")
    return {
        "path": str(path),
        "sha256": sha,
        "identity": identity,
        "status": {"status_check": "skipped"},
        "source": ("fixture_snapshot" if fixture
                   else "preserved_ac162_snapshot"),
    }


def assert_split(split, *, fixture=False):
    if list(split.get("cutoff_hlc") or []) != list(PREFIX_HLC_MAX_INCLUSIVE):
        raise Ac164Error("split cutoff moved off [1787667799562,0]")
    if fixture:
        return split
    if split.get("prefix_event_count") != PINNED_PREFIX_EVENT_COUNT:
        raise Ac164Error("prefix split count mismatch")
    if split.get("suffix_event_count") != PINNED_SUFFIX_EVENT_COUNT:
        raise Ac164Error("suffix split count mismatch")
    if split.get("prefix_sha256") != PINNED_PREFIX_SHA256:
        raise Ac164Error("prefix split SHA-256 mismatch")
    if split.get("suffix_sha256") != PINNED_SUFFIX_SHA256:
        raise Ac164Error("suffix split SHA-256 mismatch")
    if split.get("snapshot_sha256") != PINNED_SNAPSHOT_SHA256:
        raise Ac164Error("split snapshot SHA-256 mismatch")
    return split


def entry_census_from_counts(prefix, suffix, total):
    return {
        "prefix_actionable_group_complete":
            prefix["actionable_group_complete"],
        "suffix_actionable_group_complete":
            suffix["actionable_group_complete"],
        "total_actionable_group_complete":
            total["actionable_group_complete"],
        "prefix_actionable_keys": prefix["actionable_keys"],
        "suffix_actionable_keys": suffix["actionable_keys"],
        "total_actionable_keys": total["actionable_keys"],
    }


def assert_entry_census(prefix, suffix, total):
    actual = entry_census_from_counts(prefix, suffix, total)
    if actual != ENTRY_CENSUS:
        raise Ac164Error(
            "Qwen3 reference-route entry census mismatch: "
            "got %s expected %s" % (actual, ENTRY_CENSUS))
    return actual


def historical_artifact_dirs(eval_dir):
    eval_dir = Path(eval_dir)
    return tuple((eval_dir / name).resolve()
                 for name in HISTORICAL_RELATIVE_DIRS)


def ensure_not_historical(path, eval_dir, label):
    resolved = Path(path).resolve()
    for historical in historical_artifact_dirs(eval_dir):
        if resolved == historical or historical in resolved.parents:
            raise Ac164Error(
                "%s directory is historical and read-only: %s"
                % (label, path))
    return resolved


def annotate_freeze(freeze, snapshot, prefix_events, suffix_events,
                    *, fixture=False):
    freeze = dict(freeze)
    identity = snapshot.get("identity") or {}
    history_id = identity.get("history_id")
    store_epoch = identity.get("store_epoch")
    if not freeze.get("code_sha") or len(str(freeze.get("code_sha"))) != 40:
        raise Ac164Error("code SHA is required for the freeze")
    if not freeze.get("snapshot_sha256"):
        raise Ac164Error("snapshot SHA-256 is required for the freeze")
    if not history_id or not store_epoch:
        raise Ac164Error("snapshot meta missing history_id/store_epoch")
    routes = freeze.get("routes") or {}
    if set(routes) != set(ROUTE_IDS):
        raise Ac164Error("freeze must bind exactly the three frozen routes")
    freeze["contract"] = CONTRACT_ID
    freeze["engine_contract"] = ENGINE_CONTRACT
    freeze["engine_version"] = ENGINE_VERSION
    freeze["history_id"] = history_id
    freeze["store_epoch"] = store_epoch
    freeze["snapshot_source"] = snapshot.get("source")
    freeze["cutoff_hlc"] = list(PREFIX_HLC_MAX_INCLUSIVE)
    freeze["bootstrap_seed"] = freeze.get("seed", BOOTSTRAP_SEED)
    freeze["bootstrap_replicates"] = (
        (freeze.get("grid_manifest") or {}).get(
            "replicates", BOOTSTRAP_REPLICATES))
    freeze["entry_census_expected"] = dict(ENTRY_CENSUS)
    try:
        freeze["split"] = census_split_hashes(
            snapshot["path"], prefix_events, suffix_events)
    except CensusError as error:
        raise Ac164Error(str(error)) from error
    if not fixture:
        if freeze["snapshot_sha256"] != PINNED_SNAPSHOT_SHA256:
            raise Ac164Error(
                "snapshot SHA-256 mismatch; refuse a later live backup")
        if history_id != PINNED_HISTORY_ID:
            raise Ac164Error("snapshot history_id mismatch")
        if store_epoch != PINNED_STORE_EPOCH:
            raise Ac164Error("snapshot store_epoch mismatch")
        assert_split(freeze["split"], fixture=False)
    return freeze


def annotate_report(report, freeze, actual_census, *, fixture=False):
    report = dict(report)
    report.pop("report_sha256", None)
    report["contract"] = CONTRACT_ID
    report["engine_contract"] = ENGINE_CONTRACT
    report["history_id"] = freeze["history_id"]
    report["store_epoch"] = freeze["store_epoch"]
    report["split"] = freeze["split"]
    matched = actual_census == ENTRY_CENSUS
    if not fixture and not matched:
        raise Ac164Error(
            "Qwen3 reference-route entry census mismatch: "
            "got %s expected %s" % (actual_census, ENTRY_CENSUS))
    report["entry_census"] = {
        "expected": dict(ENTRY_CENSUS),
        "actual": dict(actual_census),
        "matched": matched,
    }
    notes = list(report.get("notes") or [])
    notes.extend([
        "AC-164 uses the preserved AC-162 snapshot only; a later live "
        "backup is refused (WF3000-1)",
        "Qwen3 reference-route entry census must reproduce 2537/2370/4907 "
        "and keys 421/479/611 (WF3000-3)",
        "public-B accuracy and the personal 2x2 r were never read into "
        "selection, tie-breaking or interpretation (WF3000-5)",
        "live alpha/gamma/evidence, facts, ANN and deployment are unchanged "
        "(WF3000-8)",
    ])
    report["notes"] = notes
    digest = hashlib.sha256(
        canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def assert_legal_terminal(decision):
    outcome = decision.get("outcome")
    if outcome not in LEGAL_TERMINALS:
        raise Ac164Error("illegal terminal: %s" % outcome)
    if outcome in (TERMINAL_EXACT, TERMINAL_NARROWED):
        eligible = []
        for route in decision.get("per_route") or []:
            eligible.extend(route.get("eligible") or [])
        if not eligible:
            raise Ac164Error("shortlist terminal has no eligible cell")
        for cell in eligible:
            hard = cell.get("hard_gates") or {}
            if not hard.get("evaluated") or not hard.get("pass"):
                raise Ac164Error(
                    "shortlist contains a cell with an unmeasured or "
                    "failed required gate")
            if hard.get("unevaluated"):
                raise Ac164Error(
                    "shortlist contains a cell with unevaluated gates")
    return outcome
