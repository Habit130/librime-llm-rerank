#!/usr/bin/env python3
"""Desensitized, versioned report for the #106 α recalibration.

The report is reproducible offline: it carries the code/model/tokenizer
identities, snapshot SHA-256, HLC range, freeze watermark, inclusion/
exclusion counts, per-α metrics (top-1, MRR, M1, M2), the 无法重放 count,
the α=0 fidelity diagnostic, the control table, the decision record, and a
report SHA-256.  It never contains raw 上文, candidate text, input codes or
embeddings (SCN-106-9).
"""

import hashlib
import json
import platform
import sys
from typing import Dict

from recalibrate import ALPHA_GRID


class ReportError(Exception):
    """A true fault in report generation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment_summary() -> Dict:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def build_report(contract: str,
                 snapshot_record: Dict,
                 freeze_watermark: tuple,
                 code_identity: Dict,
                 model_identity: Dict,
                 inclusion_counts: Dict,
                 per_alpha: Dict,
                 unreplayable: Dict,
                 fidelity: Dict,
                 control: Dict,
                 decision: Dict,
                 decisions_record: list,
                 grid: list = None,
                 validation: Dict = None) -> Dict:
    """Assemble the desensitized report dict.

    ``per_alpha``: {alpha: AlphaMetrics-like dict}; ``control``: the
    separate control table; ``decision``: the decide_final record;
    ``validation``: the D-A106-1 weight-map validation record.
    """
    report = {
        "contract": contract,
        "code_identity": code_identity,
        "model_identity": model_identity,
        "snapshot": {
            "sha256": snapshot_record.get("sha256"),
            "history_id": (snapshot_record.get("identity") or {}).get(
                "history_id"),
            "store_epoch": (snapshot_record.get("identity") or {}).get(
                "store_epoch"),
            "max_hlc": _hlc_of(snapshot_record),
            "status": snapshot_record.get("status"),
        },
        "freeze_watermark": list(freeze_watermark),
        "predeclared_grid": grid or ALPHA_GRID,
        "inclusion": inclusion_counts,
        "unreplayable": unreplayable,
        "per_alpha": {str(alpha): _metrics_dict(metrics)
                      for alpha, metrics in sorted(per_alpha.items())},
        "fidelity_alpha0": fidelity,
        "control": control,
        "decision": decision,
        "decisions_record": decisions_record,
        "validation": validation or {"samples": 0, "matched": 0},
        "environment": environment_summary(),
    }
    digest = hashlib.sha256(
        _canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def _hlc_of(snapshot_record: Dict):
    identity = snapshot_record.get("identity") or {}
    try:
        return [int(identity.get("hlc_physical_ms", "-1")),
                int(identity.get("hlc_logical", "-1"))]
    except (TypeError, ValueError):
        return None


def _metrics_dict(metrics) -> Dict:
    return {
        "samples": metrics.samples,
        "top1": metrics.top1,
        "top1_rate": metrics.top1_rate,
        "mrr": metrics.mrr,
        "m1_denominator": metrics.m1_denominator,
        "m1_numerator": metrics.m1_numerator,
        "m2_denominator": metrics.m2_denominator,
        "m2_numerator": metrics.m2_numerator,
        "empty_preceding": metrics.empty_preceding,
    }


def render_markdown(report: Dict) -> str:
    lines = [
        "# α Recalibration Report (%s)" % report["contract"],
        "",
        "- Report SHA-256: `%s`" % report["report_sha256"],
        "- Snapshot SHA-256: `%s`" % report["snapshot"]["sha256"],
        "- history_id: %s" % report["snapshot"]["history_id"],
        "- store_epoch: %s" % report["snapshot"]["store_epoch"],
        "- Freeze watermark: %s" % report["freeze_watermark"],
        "- Pre-declared grid: %s" % report["predeclared_grid"],
        "",
        "## Decision",
        "",
        "- state: **%s**" % report["decision"]["state"],
        "- reason: %s" % report["decision"]["reason"],
        "- final_alpha_value: %s" % report["decision"]["final_alpha_value"],
        "- internal_optimum: %s" % report["decision"]["internal_optimum"],
        "- positive_alpha_qualified: %s"
        % report["decision"]["positive_alpha_qualified"],
        "",
        "## Inclusion / exclusion",
        "",
        "```json",
        json.dumps(report["inclusion"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 无法重放",
        "",
        "```json",
        json.dumps(report["unreplayable"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Per-α (primary denominator)",
        "",
        "| α | samples | top-1 | top-1 rate | MRR | M1 | M2 |",
        "|---|---|---|---|---|---|---|",
    ]
    for alpha, metrics in report["per_alpha"].items():
        lines.append(
            "| %s | %s | %s | %.4f | %.4f | %s/%s | %s/%s |"
            % (alpha, metrics["samples"], metrics["top1"],
               metrics["top1_rate"], metrics["mrr"],
               metrics["m1_numerator"], metrics["m1_denominator"],
               metrics["m2_numerator"], metrics["m2_denominator"]))
    lines += [
        "",
        "## α=0 fidelity diagnostic",
        "",
        "```json",
        json.dumps(report["fidelity_alpha0"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Control denominator (separate table, never decision input)",
        "",
        "```json",
        json.dumps(report["control"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Decision record",
        "",
    ]
    for decision in report["decisions_record"]:
        lines.append("- %s" % decision)
    lines.append("")
    lines.append("Report SHA-256: `%s`" % report["report_sha256"])
    return "\n".join(lines)
