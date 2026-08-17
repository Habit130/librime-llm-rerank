#!/usr/bin/env python3
"""Desensitized diagnostic report for the #70 walk-forward evaluation.

Spec #43 "可复验报告与隐私": every milestone and final acceptance run
produces a versioned local report package containing:

- code commit(s) (plugin + squirrel),
- model and tokenizer summaries and all representation fingerprints,
- the fact-snapshot SHA-256, history_id, store_epoch and the HLC range,
- the random seed and hardware/dependency versions,
- sample inclusion/exclusion counts,
- complete-competition coverage,
- all stratified metrics and confidence intervals,
- milestone state (diagnostic vs selectable),
- the reference to the #69 fixed-benchmark gate state (quoted, not
  re-adjudicated),
- and the evaluation-program decision record.

The report never copies raw preceding text, candidate text or full traces:
only event ids, numbers and counts.  GitHub receives only the desensitized
summary and the report-package hash; the local package itself is
gitignored.
"""

import hashlib
import json
import platform
import sys

from walkforward import ENGINE_VERSION, margin_base_unavailable


class ReportError(Exception):
    """A true fault in report generation."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def environment_summary():
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def model_summary(identity):
    """Model/tokenizer digests from the #60 ModelTokenIdentity."""
    return {
        "model_digest": identity.model_digest[:16],
        "tokenizer_digest": identity.tokenizer_digest[:16],
        "mlxlm_version": identity.mlxlm_version,
        "hidden_dim": identity.hidden_dim,
    }


def build_report(engine_version, snapshot, replay_summary, tau_status,
                 grid_results, milestone, benchmark69, decisions,
                 seed, extra=None):
    """Assemble the desensitized report dict.

    ``snapshot`` is the ``take_snapshot`` record; ``grid_results`` the
    ``run_representation`` records; ``benchmark69`` a summary of the #69
    gate state (quoted from the #69 record, not re-adjudicated).
    """
    if not snapshot or not snapshot.get("sha256"):
        raise ReportError("snapshot record is required")
    identity = snapshot.get("identity") or {}
    max_hlc = None
    try:
        max_hlc = [int(identity.get("hlc_physical_ms", "-1")),
                   int(identity.get("hlc_logical", "-1"))]
    except (TypeError, ValueError):
        max_hlc = None
    representation_ids = []
    for grid_result in grid_results or []:
        representation_ids.append(grid_result.get("representation"))
    report = {
        "contract": "AC-70-v1",
        "engine": {
            "version": engine_version,
            "program": "eval/walkforward.py + metrics/bootstrap/calibration/"
                       "grid/snapshot/report",
        },
        "snapshot": {
            "sha256": snapshot["sha256"],
            "history_id": identity.get("history_id"),
            "store_epoch": identity.get("store_epoch"),
            "max_hlc": max_hlc,
            "status": snapshot.get("status"),
        },
        "representations": representation_ids,
        "seed": seed,
        "environment": environment_summary(),
        "replay": replay_summary,
        "tau_calibration": tau_status,
        "grid": grid_results,
        "milestone": milestone,
        "benchmark_69": benchmark69,
        "margin_base": margin_base_unavailable(),
        "decisions": decisions,
        "selection": "not_run",
    }
    if extra:
        report.update(extra)
    digest = hashlib.sha256(
        _canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def render_markdown(report):
    """A human-readable desensitized summary (no raw text)."""
    lines = [
        "# Walk-Forward Evaluation Report (AC-70-v1)",
        "",
        "- Engine: %s" % report["engine"]["version"],
        "- Snapshot SHA-256: `%s`" % report["snapshot"]["sha256"],
        "- history_id: %s" % report["snapshot"]["history_id"],
        "- store_epoch: %s" % report["snapshot"]["store_epoch"],
        "- Seed: %s" % report["seed"],
        "- Milestone: **%s** (%s)" % (report["milestone"]["state"],
                                      report["milestone"]["reason"]),
        "- Selection: %s" % report["selection"],
        "- Representations: %s" % ", ".join(
            report.get("representations") or []),
        "",
    ]
    if report.get("model"):
        lines.append("## Model / tokenizer summary")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(report["model"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    lines.extend([
        "## Replay summary",
        "",
        "```json",
        json.dumps(report["replay"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## τ calibration",
        "",
        "```json",
        json.dumps(report["tau_calibration"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Grid",
        "",
        "```json",
        json.dumps(report["grid"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## #69 fixed-benchmark gate (quoted)",
        "",
        "```json",
        json.dumps(report["benchmark_69"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Decision record",
        "",
    ])
    for decision in report["decisions"]:
        lines.append("- %s" % decision)
    lines.append("")
    lines.append("Report SHA-256: `%s`" % report["report_sha256"])
    return "\n".join(lines)
