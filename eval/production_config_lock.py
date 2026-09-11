#!/usr/bin/env python3
"""AC-80-v1 production configuration lock identities, elimination and report."""

import json
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from grid_cc import rerun_milestones  # noqa: E402
from public_layer_slicer import canonical_json, scan_privacy, sha256_bytes  # noqa: E402
from suffix_walkforward_ac164 import (  # noqa: E402
    PINNED_HISTORY_ID, PINNED_SNAPSHOT_SHA256, PINNED_STORE_EPOCH)
from usearch_ann import (  # noqa: E402
    AC164_REPORT_SHA256, bge_identity_from_ac164, cell_identity,
    is_finite_h, load_shortlist_cells)
from walkforward_cc import PREFIX_HLC_MAX_INCLUSIVE  # noqa: E402

CONTRACT_ID = "AC-80-v1"
ROUTE_ID = "dedicated_bge_m3"
LEGAL_TERMINALS = ("unique_lock", "无合格配置")
GATES = (
    "quality_safety_pollution_finite_h",
    "claimable_plus3pp",
    "retrieval_equivalence",
    "latency_memory_disk",
)
BACKENDS = (
    "exact",
    "accelerate-cblas-sgemv",
    "mlx-exact-matmul",
    "sqlite-vec",
    "usearch-hnsw",
    "hnswlib-hnsw",
)
EXACT_BACKENDS = (
    "exact",
    "accelerate-cblas-sgemv",
    "mlx-exact-matmul",
    "sqlite-vec",
)
ANN_BACKENDS = ("usearch-hnsw", "hnswlib-hnsw")
AC78_FREEZE_SHA256 = (
    "dd888a45c07d3f656effca15cf4ab04fa17c79fa81ddccbaff580921e31032dc")
AC78_REPORT_SHA256 = (
    "08afd526795885e218271ab7ecc55829701ac6ca28252243ebe32e91bf4c14ab")
AC79_FREEZE_SHA256 = (
    "1c39fa4f533b7000f5e97173fbd0525030cc6ef322bc31dc4b0bd1fdaf0bd58c")
AC79_REPORT_SHA256 = (
    "13a99ee56379314098c0e378ff02fcc40c47982e3209bae1b57573ec4a09db71")
MANIFEST_FIELDS = (
    "baseline",
    "representation",
    "H",
    "tau",
    "K",
    "gamma",
    "k",
    "generation_format",
    "backend",
    "search_parameters",
)
CENSUS_ACTIONABLE_TOTAL = 4907
EXACT_ANN_P95_SLACK_MS = 5.0


class Lock80Error(Exception):
    """A frozen AC-80 identity, elimination, or lock-record fault."""


def committed_artifact_dir():
    return Path(_ROOT) / "production_config_lock"


def ac164_report_path():
    return Path(_ROOT) / "suffix_walkforward_ac164" / (
        "suffix_walkforward_report.json")


def _ann_paths(name):
    folder = Path(_ROOT) / ("%s_ann_qualification" % name)
    return folder / ("%s_ann_freeze.json" % name), folder / (
        "%s_ann_report.json" % name)


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_bound_bundle():
    ac164 = _load_json(ac164_report_path())
    if ac164.get("report_sha256") != AC164_REPORT_SHA256:
        raise Lock80Error("committed AC-164 report SHA-256 drifted")
    if ac164.get("decision", {}).get("outcome") != "收窄声称_shortlist":
        raise Lock80Error("AC-164 terminal drifted")
    usearch_freeze, usearch_report = (
        _load_json(path) for path in _ann_paths("usearch"))
    hnswlib_freeze, hnswlib_report = (
        _load_json(path) for path in _ann_paths("hnswlib"))
    if usearch_freeze.get("freeze_sha256") != AC78_FREEZE_SHA256:
        raise Lock80Error("committed AC-78 freeze SHA-256 drifted")
    if usearch_report.get("report_sha256") != AC78_REPORT_SHA256:
        raise Lock80Error("committed AC-78 report SHA-256 drifted")
    if usearch_report.get("terminal") != "usearch_disqualified":
        raise Lock80Error("AC-78 terminal drifted")
    if hnswlib_freeze.get("freeze_sha256") != AC79_FREEZE_SHA256:
        raise Lock80Error("committed AC-79 freeze SHA-256 drifted")
    if hnswlib_report.get("report_sha256") != AC79_REPORT_SHA256:
        raise Lock80Error("committed AC-79 report SHA-256 drifted")
    if hnswlib_report.get("terminal") != "hnswlib_disqualified":
        raise Lock80Error("AC-79 terminal drifted")
    finite, controls = load_shortlist_cells(ac164)
    records = _finite_selected_records(ac164)
    if len(records) != 144 or len(finite) != 144 or len(controls) != 36:
        raise Lock80Error("finite-H shortlist count drifted")
    return {
        "ac164": ac164,
        "usearch_freeze": usearch_freeze,
        "usearch_report": usearch_report,
        "hnswlib_freeze": hnswlib_freeze,
        "hnswlib_report": hnswlib_report,
        "finite_cells": finite,
        "control_cells": controls,
        "finite_records": records,
        "bge": bge_identity_from_ac164(ac164),
        "backend_states": bound_backend_states(usearch_report, hnswlib_report),
    }


def _finite_selected_records(report):
    bge = next((route for route in report.get("routes") or []
                if route.get("route_id") == ROUTE_ID), None)
    if bge is None:
        raise Lock80Error("AC-164 report has no dedicated_bge_m3 route")
    records = []
    for record in bge.get("cells") or []:
        if not record.get("selected"):
            continue
        cell = record.get("cell") or {}
        if is_finite_h(cell.get("half_life")):
            records.append(record)
    return records


def _identity_key(cell):
    ident = cell_identity(cell)
    return (
        ident["route_id"],
        ident["tau_quantile"],
        ident["tau"],
        ident["half_life"],
        ident["k_evidence"],
        ident["gamma"],
        ident["saturation_k"],
    )


def _ann_cell_map(report):
    mapping = {}
    for row in report.get("qualification_cells") or []:
        mapping[_identity_key(row.get("cell") or {})] = row
    return mapping


def bound_backend_states(usearch_report, hnswlib_report):
    usearch_cells = _ann_cell_map(usearch_report)
    hnswlib_cells = _ann_cell_map(hnswlib_report)
    usearch_resource = bool(
        ((usearch_report.get("capacity") or {}).get("freq") or {}).get("pass")
        and ((usearch_report.get("capacity") or {}).get("hotkey") or {}).get(
            "pass")
        and (usearch_report.get("memory") or {}).get("pass"))
    hnswlib_resource = bool(
        ((hnswlib_report.get("capacity") or {}).get("freq") or {}).get("pass")
        and ((hnswlib_report.get("capacity") or {}).get("hotkey") or {}).get(
            "pass")
        and (hnswlib_report.get("memory") or {}).get("pass"))
    return {
        "exact": {
            "retrieval_equivalence": {
                "evaluated": True,
                "pass": True,
                "reason": "oracle_identity",
            },
            "latency_memory_disk": {
                "evaluated": True,
                "pass": False,
                "reason": "ac71_not_production_hot_path",
            },
        },
        "accelerate-cblas-sgemv": {
            "retrieval_equivalence": {
                "evaluated": True,
                "pass": True,
                "reason": "ac72_equivalence",
            },
            "latency_memory_disk": {
                "evaluated": True,
                "pass": False,
                "reason": "accelerate_不合格",
            },
        },
        "mlx-exact-matmul": {
            "retrieval_equivalence": {
                "evaluated": True,
                "pass": True,
                "reason": "ac73_equivalence",
            },
            "latency_memory_disk": {
                "evaluated": True,
                "pass": False,
                "reason": "mlx_不合格",
            },
        },
        "sqlite-vec": {
            "retrieval_equivalence": {
                "evaluated": False,
                "pass": False,
                "reason": "unmeasured",
            },
            "latency_memory_disk": {
                "evaluated": False,
                "pass": False,
                "reason": "unmeasured",
            },
        },
        "usearch-hnsw": {
            "retrieval_cells": usearch_cells,
            "latency_memory_disk": {
                "evaluated": True,
                "pass": usearch_resource,
                "reason": "ok" if usearch_resource else "usearch_disqualified",
            },
        },
        "hnswlib-hnsw": {
            "retrieval_cells": hnswlib_cells,
            "latency_memory_disk": {
                "evaluated": True,
                "pass": hnswlib_resource,
                "reason": "ok" if hnswlib_resource else "hnswlib_disqualified",
            },
        },
    }


def build_freeze(code_sha, bundle):
    if not code_sha or len(str(code_sha)) != 40:
        raise Lock80Error("code SHA is required for the freeze")
    finite = bundle["finite_cells"]
    controls = bundle["control_cells"]
    if len(finite) != 144 or len(controls) != 36:
        raise Lock80Error("shortlist cell counts drifted")
    freeze = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "snapshot_sha256": PINNED_SNAPSHOT_SHA256,
        "history_id": PINNED_HISTORY_ID,
        "store_epoch": PINNED_STORE_EPOCH,
        "ac164_report_sha256": AC164_REPORT_SHA256,
        "ac78_freeze_sha256": AC78_FREEZE_SHA256,
        "ac78_report_sha256": AC78_REPORT_SHA256,
        "ac79_freeze_sha256": AC79_FREEZE_SHA256,
        "ac79_report_sha256": AC79_REPORT_SHA256,
        "cutoff_hlc": list(PREFIX_HLC_MAX_INCLUSIVE),
        "route_id": ROUTE_ID,
        "bge": bundle["bge"],
        "shortlist_cells": 180,
        "qualification_cells": [cell_identity(cell) for cell in finite],
        "control_cells": [cell_identity(cell) for cell in controls],
        "backends": list(BACKENDS),
        "elimination_gates": list(GATES),
        "bound_terminals": {
            "ac164": "收窄声称_shortlist",
            "ac71": "not_production_exact_hot_path",
            "ac72": "不合格",
            "ac73": "不合格",
            "ac78": "usearch_disqualified",
            "ac79": "hnswlib_disqualified",
        },
        "legal_terminals": list(LEGAL_TERMINALS),
        "unmeasured_never_survives": True,
        "unclaimable_plus3pp_never_survives": True,
        "declared_before_decision": True,
    }
    verify_privacy(freeze)
    freeze["freeze_sha256"] = sha256_bytes(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_sha256"}).encode("utf-8"))
    return freeze


def assert_freeze_closed(freeze, snapshot_sha256, report_sha256, code_sha):
    if freeze.get("snapshot_sha256") != snapshot_sha256:
        raise Lock80Error("freeze snapshot hash drifted")
    if freeze.get("ac164_report_sha256") != report_sha256:
        raise Lock80Error("freeze AC-164 report hash drifted")
    if freeze.get("code_sha") != code_sha:
        raise Lock80Error("freeze code SHA drifted")
    if freeze.get("ac78_freeze_sha256") != AC78_FREEZE_SHA256:
        raise Lock80Error("AC-78 freeze hash drifted")
    if freeze.get("ac78_report_sha256") != AC78_REPORT_SHA256:
        raise Lock80Error("AC-78 report hash drifted")
    if freeze.get("ac79_freeze_sha256") != AC79_FREEZE_SHA256:
        raise Lock80Error("AC-79 freeze hash drifted")
    if freeze.get("ac79_report_sha256") != AC79_REPORT_SHA256:
        raise Lock80Error("AC-79 report hash drifted")
    if freeze.get("cutoff_hlc") != list(PREFIX_HLC_MAX_INCLUSIVE):
        raise Lock80Error("cutoff HLC drifted")
    if not freeze.get("declared_before_decision"):
        raise Lock80Error("freeze was not declared before the decision")
    if "terminal" in freeze:
        raise Lock80Error("freeze must not pre-assign a terminal")
    if list(freeze.get("elimination_gates") or []) != list(GATES):
        raise Lock80Error("elimination gates drifted")
    if list(freeze.get("backends") or []) != list(BACKENDS):
        raise Lock80Error("backend list drifted")
    if len(freeze.get("qualification_cells") or []) != 144:
        raise Lock80Error("qualification cell count drifted")


def verify_privacy(payload):
    findings = scan_privacy(payload)
    text = canonical_json(payload) if not isinstance(payload, str) else payload
    if "/Users/" in text or "/Users/habit" in text:
        findings.append("canonical_json: machine path")
    for marker in ("~/Library/Rime", "Library/Rime", "facts.sqlite",
                   "userdb.txt"):
        if marker in text:
            findings.append("canonical_json: %s" % marker)
    if findings:
        raise Lock80Error("privacy scan failed: %s" % "; ".join(findings[:8]))
    return True


def _quality_gate(record):
    if not record.get("selected"):
        return {"evaluated": True, "pass": False, "reason": "not_selected"}
    if not record.get("delta_one_ok", False):
        return {"evaluated": True, "pass": False, "reason": "delta_one"}
    hard = record.get("hard_gates") or {}
    unevaluated = sorted(hard.get("unevaluated") or [])
    if not hard.get("evaluated", False) or unevaluated:
        return {"evaluated": False, "pass": False, "reason": "unmeasured"}
    if not hard.get("pass", False):
        return {"evaluated": True, "pass": False, "reason": "hard_gates"}
    gate = record.get("finite_h_gate") or {}
    if not gate.get("evaluated", False):
        return {"evaluated": False, "pass": False, "reason": "unmeasured"}
    if not gate.get("pass", False):
        return {"evaluated": True, "pass": False, "reason": "finite_h"}
    return {"evaluated": True, "pass": True, "reason": "ok"}


def _claimable_gate(record):
    lift = record.get("lift") or {}
    if "claimable" not in lift and "pass" not in lift:
        return {"evaluated": False, "pass": False, "reason": "unmeasured"}
    if lift.get("claimable") is True and lift.get("pass") is True:
        return {"evaluated": True, "pass": True, "reason": "ok"}
    return {
        "evaluated": True,
        "pass": False,
        "reason": lift.get("reason") or "unclaimable",
    }


def _backend_gate(record, backend, backend_states, gate_name):
    state = backend_states.get(backend)
    if state is None:
        return {"evaluated": False, "pass": False, "reason": "unmeasured"}
    if gate_name == "retrieval_equivalence" and "retrieval_cells" in state:
        row = state["retrieval_cells"].get(_identity_key(record.get("cell") or {}))
        if row is None:
            return {"evaluated": False, "pass": False, "reason": "unmeasured"}
        evaluated = bool(row.get("evaluated"))
        passed = bool(evaluated and row.get("pass"))
        reason = row.get("reason") or ("ok" if passed else "ann_recall")
        if not evaluated:
            reason = "unmeasured"
        return {"evaluated": evaluated, "pass": passed, "reason": reason}
    gate = state.get(gate_name)
    if not gate:
        return {"evaluated": False, "pass": False, "reason": "unmeasured"}
    return {
        "evaluated": bool(gate.get("evaluated")),
        "pass": bool(gate.get("evaluated") and gate.get("pass")),
        "reason": gate.get("reason") or (
            "ok" if gate.get("pass") else "unmeasured"),
    }


def _lift_ci_lower(record):
    ci = (record.get("ci") or {}).get("top1_vs_baseline")
    if not isinstance(ci, list) or len(ci) < 2:
        return None
    bounds = ci[1]
    if isinstance(bounds, list) and bounds:
        try:
            return float(bounds[0])
        except (TypeError, ValueError):
            return None
    try:
        return float(bounds)
    except (TypeError, ValueError):
        return None


def evaluate_row(record, backend, backend_states):
    if backend not in BACKENDS:
        raise Lock80Error("unknown backend %r" % backend)
    gates = {
        "quality_safety_pollution_finite_h": _quality_gate(record),
        "claimable_plus3pp": _claimable_gate(record),
        "retrieval_equivalence": _backend_gate(
            record, backend, backend_states, "retrieval_equivalence"),
        "latency_memory_disk": _backend_gate(
            record, backend, backend_states, "latency_memory_disk"),
    }
    failing = None
    for gate_id in GATES:
        gate = gates[gate_id]
        if not gate.get("evaluated") or not gate.get("pass"):
            failing = gate_id
            break
    ident = cell_identity(record.get("cell") or {})
    return {
        "cell": ident,
        "backend": backend,
        "survive": failing is None,
        "failing_gate_id": failing,
        "gates": gates,
        "lift_ci_lower": _lift_ci_lower(record),
    }


def decide_lock(freeze, bundle):
    assert_freeze_closed(
        freeze, freeze["snapshot_sha256"], freeze["ac164_report_sha256"],
        freeze["code_sha"])
    backend_states = bundle["backend_states"]
    matrix = []
    for record in bundle["finite_records"]:
        for backend in freeze["backends"]:
            matrix.append(evaluate_row(record, backend, backend_states))
    expected = len(freeze["qualification_cells"]) * len(BACKENDS)
    if len(matrix) != expected:
        raise Lock80Error("matrix size drifted")
    survivors = [row for row in matrix if row["survive"]]
    if not survivors:
        terminal = "无合格配置"
        winner = None
    else:
        winner = dict(tie_break(survivors))
        winner["bge"] = bundle.get("bge")
        terminal = "unique_lock"
    if terminal not in LEGAL_TERMINALS:
        raise Lock80Error("illegal terminal %r" % terminal)
    total = CENSUS_ACTIONABLE_TOTAL
    milestones = rerun_milestones(total)
    next_wait = next((item for item in milestones if item > total), None)
    return {
        "terminal": terminal,
        "survivor_count": len(survivors),
        "winner": winner,
        "matrix": matrix,
        "next_milestone_wait": next_wait,
        "rerun_milestones": milestones,
        "actionable_group_complete_total": total,
    }


def tie_break(survivors):
    if not survivors:
        return None
    ann_p95 = [row.get("resource_p95_ms") for row in survivors
               if row.get("backend") in ANN_BACKENDS
               and row.get("resource_p95_ms") is not None]
    fastest_ann = min(ann_p95) if ann_p95 else None

    def key(row):
        ident = row["cell"]
        lift_lo = row.get("lift_ci_lower")
        if lift_lo is None:
            lift_lo = float("-inf")
        p95 = row.get("resource_p95_ms")
        if p95 is None:
            p95 = float("inf")
        size = row.get("generation_bytes")
        if size is None:
            size = 0
        exact_rank = 1
        if (fastest_ann is not None
                and row.get("backend") in EXACT_BACKENDS
                and row.get("resource_p95_ms") is not None
                and row["resource_p95_ms"] <= fastest_ann + EXACT_ANN_P95_SLACK_MS):
            exact_rank = 0
        return (
            -float(lift_lo),
            ident["k_evidence"],
            ident["gamma"],
            -ident["saturation_k"],
            -float(ident["half_life"]),
            p95,
            size,
            exact_rank,
            ident["route_id"],
            row["backend"],
        )

    return sorted(survivors, key=key)[0]


def build_manifest(terminal, winner, prospective_hlc):
    if terminal not in LEGAL_TERMINALS:
        raise Lock80Error("illegal terminal %r" % terminal)
    if terminal == "无合格配置":
        if winner is not None:
            raise Lock80Error("无合格配置 cannot carry a winner")
        if prospective_hlc != "not_opened":
            raise Lock80Error("无合格配置 cannot open prospective confirmation")
        manifest = {field: None for field in MANIFEST_FIELDS}
        manifest["omitted_reason"] = "无合格配置"
        manifest["prospective_start_hlc"] = "not_opened"
        return manifest
    if winner is None:
        raise Lock80Error("unique_lock requires a surviving configuration")
    if prospective_hlc == "not_opened" or prospective_hlc is None:
        raise Lock80Error("unique_lock requires a real next-HLC")
    ident = winner["cell"]
    search = winner.get("search_parameters")
    if search is None and winner.get("backend") in EXACT_BACKENDS:
        search = None
    manifest = {
        "baseline": winner.get("baseline"),
        "representation": winner.get("bge") or winner.get("representation"),
        "H": ident["half_life"],
        "tau": ident["tau"],
        "K": ident["k_evidence"],
        "gamma": ident["gamma"],
        "k": ident["saturation_k"],
        "generation_format": (
            (winner.get("bge") or {}).get("format")
            or winner.get("generation_format") or "fp32-l2"),
        "backend": winner["backend"],
        "search_parameters": search,
        "omitted_reason": None,
        "prospective_start_hlc": list(prospective_hlc),
    }
    return manifest


def build_report(freeze, decision, code_sha, prospective_hlc=None):
    terminal = decision["terminal"]
    if terminal not in LEGAL_TERMINALS:
        raise Lock80Error("illegal terminal %r" % terminal)
    if terminal == "无合格配置":
        hlc = "not_opened"
    else:
        hlc = prospective_hlc
    manifest = build_manifest(terminal, decision.get("winner"), hlc)
    failing_counts = {}
    backend_counts = {}
    for row in decision["matrix"]:
        backend_counts[row["backend"]] = backend_counts.get(row["backend"], 0) + 1
        gate = row["failing_gate_id"] or "survive"
        failing_counts[gate] = failing_counts.get(gate, 0) + 1
    report = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "freeze_sha256": freeze.get("freeze_sha256"),
        "snapshot_sha256": freeze.get("snapshot_sha256"),
        "ac164_report_sha256": freeze.get("ac164_report_sha256"),
        "ac78_freeze_sha256": freeze.get("ac78_freeze_sha256"),
        "ac78_report_sha256": freeze.get("ac78_report_sha256"),
        "ac79_freeze_sha256": freeze.get("ac79_freeze_sha256"),
        "ac79_report_sha256": freeze.get("ac79_report_sha256"),
        "cutoff_hlc": list(freeze.get("cutoff_hlc") or []),
        "route_id": ROUTE_ID,
        "terminal": terminal,
        "legal_terminals": list(LEGAL_TERMINALS),
        "survivor_count": decision["survivor_count"],
        "matrix": decision["matrix"],
        "failing_gate_counts": failing_counts,
        "backend_row_counts": backend_counts,
        "manifest": manifest,
        "next_milestone_wait": decision.get("next_milestone_wait"),
        "rerun_milestones": decision.get("rerun_milestones"),
        "actionable_group_complete_total": decision.get(
            "actionable_group_complete_total"),
        "prospective_start_hlc": manifest["prospective_start_hlc"],
        "privacy_ok": True,
        "live_alpha": 0.0,
        "live_gamma": 0.0,
        "live_evidence": False,
        "issue_81_started": False,
    }
    verify_privacy(report)
    report["report_sha256"] = sha256_bytes(
        canonical_json({key: value for key, value in report.items()
                        if key != "report_sha256"}).encode("utf-8"))
    verify_privacy(report)
    return report


def render_markdown(report):
    lines = [
        "# Production configuration lock (AC-80-v1)",
        "",
        "- Terminal: **%s**" % report["terminal"],
        "- Freeze SHA-256: `%s`" % report["freeze_sha256"],
        "- Snapshot SHA-256: `%s`" % report["snapshot_sha256"],
        "- AC-164 report SHA-256: `%s`" % report["ac164_report_sha256"],
        "- AC-78 freeze/report: `%s` / `%s`" % (
            report.get("ac78_freeze_sha256"), report.get("ac78_report_sha256")),
        "- AC-79 freeze/report: `%s` / `%s`" % (
            report.get("ac79_freeze_sha256"), report.get("ac79_report_sha256")),
        "- Survivors: %s" % report["survivor_count"],
        "- Matrix rows: %s" % len(report.get("matrix") or []),
        "- Next milestone wait: %s" % report.get("next_milestone_wait"),
        "- Prospective start HLC: `%s`" % report["prospective_start_hlc"],
        "- Privacy: %s" % ("clean" if report["privacy_ok"] else "FAIL"),
        "- Live alpha/gamma/evidence: 0 / 0 / false",
        "- Issue #81 started: %s" % report.get("issue_81_started"),
        "",
        "## Failing gates",
        "",
        canonical_json(report.get("failing_gate_counts") or {}),
        "",
        "## Manifest",
        "",
        canonical_json(report.get("manifest") or {}),
        "",
        "- Report SHA-256: `%s`" % report["report_sha256"],
    ]
    return "\n".join(lines) + "\n"
