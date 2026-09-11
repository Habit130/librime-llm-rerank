#!/usr/bin/env python3
"""AC-79-v1 hnswlib ANN qualification identities, metrics and report."""

import json
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from ann import (  # noqa: E402
    ANN_SEED,
    HNSWLIB_BACKEND,
    HNSWLIB_BUILD_PRESETS,
    HNSWLIB_DTYPE,
    HNSWLIB_LIBRARY_VERSION,
    HNSWLIB_METRIC,
    HNSWLIB_QUERY_SEARCH_VALUES,
    HNSWLIB_SERIALIZATION_ABI,
    OVERFETCH_FLOOR,
    OVERFETCH_MULTIPLIERS,
)
from public_layer_slicer import canonical_json, sha256_bytes  # noqa: E402
from suffix_walkforward_ac164 import (  # noqa: E402
    PINNED_HISTORY_ID,
    PINNED_SNAPSHOT_SHA256,
    PINNED_STORE_EPOCH,
)
from usearch_ann import (  # noqa: E402
    AC164_CODE_SHA,
    AC164_REPORT_SHA256,
    COMPLETE_P95_MS,
    COMPLETE_P99_MS,
    DERIVED_DISK_GIB,
    EMISSION_MIN,
    FIXTURE_VERSION,
    GENERATION_DISK_GIB,
    INCREMENTAL_P95_MS,
    INCREMENTAL_P99_MS,
    REBUILD_CONCURRENT_P95_MS,
    REBUILD_PEAK_INCREMENTAL_GIB,
    RECALL_MACRO_MIN,
    RECALL_P5_MIN,
    REPLAY_TIMEOUT_MS,
    ROUTE_ID,
    RSS_INCREMENTAL_MIB,
    TOP1_MIN,
    bge_identity_from_ac164,
    cell_identity,
    derived_state_bytes,
    directory_bytes,
    file_sha256,
    is_finite_h,
    load_shortlist_cells,
    published_generation_bytes,
    qualify_preset,
    query_recall,
    scheme_order,
    summarize_cell_queries,
    verify_privacy as _verify_privacy_78,
)
from walkforward_cc import PREFIX_HLC_MAX_INCLUSIVE  # noqa: E402

CONTRACT_ID = "AC-79-v1"
LEGAL_TERMINALS = ("hnswlib_qualified", "hnswlib_disqualified")
AC78_FREEZE_SHA256 = (
    "dd888a45c07d3f656effca15cf4ab04fa17c79fa81ddccbaff580921e31032dc")
AC78_REPORT_SHA256 = (
    "08afd526795885e218271ab7ecc55829701ac6ca28252243ebe32e91bf4c14ab")
AC78_CODE_SHA = "7c338e87880c168a01e2e0daf655823553929ee3"


class Ann79Error(Exception):
    """A frozen AC-79 identity or measurement fault."""


def verify_privacy(payload):
    try:
        return _verify_privacy_78(payload)
    except Exception as error:
        raise Ann79Error(str(error)) from error


def build_freeze(code_sha, snapshot_sha256, history_id, store_epoch,
                 report_sha256, finite_cells, control_cells, bge_identity,
                 scoring_code_sha=AC164_CODE_SHA):
    if snapshot_sha256 != PINNED_SNAPSHOT_SHA256:
        raise Ann79Error("snapshot SHA-256 mismatch")
    if history_id != PINNED_HISTORY_ID:
        raise Ann79Error("history_id mismatch")
    if store_epoch != PINNED_STORE_EPOCH:
        raise Ann79Error("store_epoch mismatch")
    if report_sha256 != AC164_REPORT_SHA256:
        raise Ann79Error("AC-164 report SHA-256 mismatch")
    if len(finite_cells) != 144 or len(control_cells) != 36:
        raise Ann79Error("shortlist cell counts drifted")
    freeze = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "scoring_code_sha": scoring_code_sha,
        "snapshot_sha256": snapshot_sha256,
        "history_id": history_id,
        "store_epoch": store_epoch,
        "ac164_report_sha256": report_sha256,
        "ac78_freeze_sha256": AC78_FREEZE_SHA256,
        "ac78_report_sha256": AC78_REPORT_SHA256,
        "ac78_code_sha": AC78_CODE_SHA,
        "cutoff_hlc": list(PREFIX_HLC_MAX_INCLUSIVE),
        "route_id": ROUTE_ID,
        "bge": bge_identity,
        "shortlist_cells": 180,
        "qualification_cells": [cell_identity(cell) for cell in finite_cells],
        "control_cells": [cell_identity(cell) for cell in control_cells],
        "ann_backend": HNSWLIB_BACKEND,
        "ann_metric": HNSWLIB_METRIC,
        "ann_dtype": HNSWLIB_DTYPE,
        "ann_library_version": HNSWLIB_LIBRARY_VERSION,
        "ann_serialization_abi": HNSWLIB_SERIALIZATION_ABI,
        "ann_build_presets": [dict(preset) for preset in HNSWLIB_BUILD_PRESETS],
        "overfetch_multipliers": list(OVERFETCH_MULTIPLIERS),
        "overfetch_floor": OVERFETCH_FLOOR,
        "query_search_values": list(HNSWLIB_QUERY_SEARCH_VALUES),
        "seed": ANN_SEED,
        "fixture_version": FIXTURE_VERSION,
        "fixture_kinds": ["freq", "hotkey"],
        "legal_terminals": list(LEGAL_TERMINALS),
        "gates": {
            "recall_macro_min": RECALL_MACRO_MIN,
            "recall_p5_min": RECALL_P5_MIN,
            "top1_min": TOP1_MIN,
            "emission_min": EMISSION_MIN,
        },
        "declared_before_build": True,
        "usearch_preset_not_copied": True,
    }
    freeze["freeze_sha256"] = sha256_bytes(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_sha256"}).encode("utf-8"))
    return freeze


def assert_freeze_closed(freeze, snapshot_sha256, report_sha256, code_sha):
    if freeze.get("snapshot_sha256") != snapshot_sha256:
        raise Ann79Error("freeze snapshot hash drifted")
    if freeze.get("ac164_report_sha256") != report_sha256:
        raise Ann79Error("freeze report hash drifted")
    if freeze.get("code_sha") != code_sha:
        raise Ann79Error("freeze code SHA drifted")
    if freeze.get("ac78_freeze_sha256") != AC78_FREEZE_SHA256:
        raise Ann79Error("AC-78 freeze hash drifted")
    if freeze.get("ac78_report_sha256") != AC78_REPORT_SHA256:
        raise Ann79Error("AC-78 report hash drifted")
    if freeze.get("ann_backend") != HNSWLIB_BACKEND:
        raise Ann79Error("freeze backend is not hnswlib-hnsw")
    if not freeze.get("declared_before_build"):
        raise Ann79Error("freeze was not declared before build")
    if len(freeze.get("ann_build_presets") or []) > 4:
        raise Ann79Error("more than 4 ANN build presets")
    if list(freeze.get("overfetch_multipliers") or []) != list(
            OVERFETCH_MULTIPLIERS):
        raise Ann79Error("overfetch multipliers drifted")
    if list(freeze.get("query_search_values") or []) != list(
            HNSWLIB_QUERY_SEARCH_VALUES):
        raise Ann79Error("query-search values drifted")
    if len(freeze.get("query_search_values") or []) > 4:
        raise Ann79Error("more than 4 query-search values")
    if freeze.get("seed") != ANN_SEED:
        raise Ann79Error("ANN seed drifted")


def select_preset(prefix_results, latency_p95=None, generation_size=None):
    """Select on prefix among presets that meet ANN79-5.

    Tie-break: hotkey ordinary-query p95, then smaller generation size.
    """
    eligible = [row for row in prefix_results if row.get("meets_ann79_5")]
    pool = eligible if eligible else list(prefix_results)
    if not pool:
        raise Ann79Error("no ANN presets measured")

    def key(row):
        p95 = row.get("hotkey_p95_ms")
        if p95 is None:
            p95 = latency_p95 if latency_p95 is not None else float("inf")
        size = row.get("generation_size")
        if size is None:
            size = generation_size if generation_size is not None else 0
        passing = -int(row.get("passing_cells") or 0)
        return (passing, p95, size, row.get("preset_id"),
                row.get("overfetch_multiplier"), row.get("query_search"))

    chosen = sorted(pool, key=key)[0]
    chosen = dict(chosen)
    chosen["selected_on_prefix"] = True
    chosen["eligible_on_prefix"] = bool(eligible)
    return chosen


def decide_terminal(suffix_cells, capacity_pass, memory_pass, measured):
    if not measured:
        raise Ann79Error("unmeasured gates never pass")
    passing = [cell for cell in suffix_cells
               if cell.get("finite_h") and cell.get("pass")
               and capacity_pass and memory_pass]
    if passing:
        return "hnswlib_qualified", passing
    return "hnswlib_disqualified", []


def build_report(freeze, selection, suffix_cells, capacity, memory,
                 lifecycle, privacy_ok, terminal, code_sha):
    report = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "freeze_sha256": freeze.get("freeze_sha256"),
        "snapshot_sha256": freeze.get("snapshot_sha256"),
        "ac164_report_sha256": freeze.get("ac164_report_sha256"),
        "ac78_freeze_sha256": freeze.get("ac78_freeze_sha256"),
        "ac78_report_sha256": freeze.get("ac78_report_sha256"),
        "ac78_terminal_context": "usearch_disqualified",
        "route_id": ROUTE_ID,
        "selected_ann_preset": {
            "preset_id": selection.get("preset_id"),
            "M": selection.get("M"),
            "ef_construction": selection.get("ef_construction"),
            "overfetch_multiplier": selection.get("overfetch_multiplier"),
            "query_search": selection.get("query_search"),
            "eligible_on_prefix": selection.get("eligible_on_prefix"),
        },
        "qualification_cells": suffix_cells,
        "capacity": capacity,
        "memory": memory,
        "lifecycle": lifecycle,
        "privacy_ok": bool(privacy_ok),
        "live_alpha": 0.0,
        "live_gamma": 0.0,
        "live_evidence": False,
        "usearch_numbers_substituted": False,
        "terminal": terminal,
        "legal_terminals": list(LEGAL_TERMINALS),
    }
    if terminal not in LEGAL_TERMINALS:
        raise Ann79Error("illegal terminal %r" % terminal)
    verify_privacy(report)
    report["report_sha256"] = sha256_bytes(
        canonical_json({key: value for key, value in report.items()
                        if key != "report_sha256"}).encode("utf-8"))
    verify_privacy(report)
    return report


def render_markdown(report):
    lines = [
        "# hnswlib ANN qualification (AC-79-v1)",
        "",
        "- Terminal: **%s**" % report["terminal"],
        "- Freeze SHA-256: `%s`" % report["freeze_sha256"],
        "- Snapshot SHA-256: `%s`" % report["snapshot_sha256"],
        "- AC-164 report SHA-256: `%s`" % report["ac164_report_sha256"],
        "- AC-78 context (not evidence): `%s` freeze `%s`" % (
            report.get("ac78_terminal_context"),
            report.get("ac78_freeze_sha256")),
        "- Selected preset: `%s`" % (
            report["selected_ann_preset"].get("preset_id")),
        "- M / ef_construction: %s / %s" % (
            report["selected_ann_preset"].get("M"),
            report["selected_ann_preset"].get("ef_construction")),
        "- Overfetch multiplier: %s" % (
            report["selected_ann_preset"].get("overfetch_multiplier")),
        "- Query-search (ef): %s" % (
            report["selected_ann_preset"].get("query_search")),
        "- Privacy: %s" % ("clean" if report["privacy_ok"] else "FAIL"),
        "- Live alpha/gamma/evidence: 0 / 0 / false",
        "- USearch numbers substituted: %s" % (
            report.get("usearch_numbers_substituted")),
        "",
        "## Finite-H cells",
        "",
    ]
    passing = 0
    for cell in report.get("qualification_cells") or []:
        marker = "pass" if cell.get("pass") else cell.get("reason", "fail")
        if cell.get("pass"):
            passing += 1
        ident = cell.get("cell") or {}
        lines.append(
            "- H=%s K=%s γ=%s k=%s τq=%s → %s (recall=%.4f p5=%.4f top1=%.4f "
            "emission=%.4f n=%s)" % (
                ident.get("half_life"), ident.get("k_evidence"),
                ident.get("gamma"), ident.get("saturation_k"),
                ident.get("tau_quantile"), marker,
                cell.get("recall_macro") or 0.0,
                cell.get("recall_p5") or 0.0,
                cell.get("top1") or 0.0,
                cell.get("emission") or 0.0,
                cell.get("n") or 0))
    lines.extend([
        "",
        "Passing finite-H cells: %d" % passing,
        "",
        "## Capacity / memory",
        "",
        canonical_json(report.get("capacity") or {}),
        "",
        canonical_json(report.get("memory") or {}),
        "",
        "## Lifecycle",
        "",
        canonical_json(report.get("lifecycle") or {}),
        "",
        "- Report SHA-256: `%s`" % report["report_sha256"],
    ])
    return "\n".join(lines) + "\n"


def committed_artifact_dir():
    return Path(_ROOT) / "hnswlib_ann_qualification"


def assert_ac78_identities():
    freeze_path = Path(_ROOT) / "usearch_ann_qualification" / (
        "usearch_ann_freeze.json")
    report_path = Path(_ROOT) / "usearch_ann_qualification" / (
        "usearch_ann_report.json")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if freeze.get("freeze_sha256") != AC78_FREEZE_SHA256:
        raise Ann79Error("committed AC-78 freeze SHA-256 drifted")
    if report.get("report_sha256") != AC78_REPORT_SHA256:
        raise Ann79Error("committed AC-78 report SHA-256 drifted")
    if report.get("terminal") != "usearch_disqualified":
        raise Ann79Error("AC-78 terminal context drifted")
