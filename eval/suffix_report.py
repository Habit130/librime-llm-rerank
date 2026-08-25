#!/usr/bin/env python3
"""Desensitized suffix walk-forward report (Habit130/squirrel#157, AC-157-v1).

The report package carries only:

- code and engine identities (contract, engine version, code SHA),
- snapshot and split hashes (SHA-256 of the claim-time Online-Backup copy
  and of the prefix/suffix event-id split files) and HLC ranges,
- per-route fingerprints and τ calibration state (incl. not_calibratable),
- the pre-declared grid manifest (routes, H/K/γ/k sets, quantiles, α=0),
- per-cell identities and numeric evidence (point estimates, key-clustered
  bootstrap CIs, gate states),
- the terminal decision record and the claim-support statement,
- a privacy scan verdict.

It never copies raw preceding text, candidate text, live facts or machine
paths; only ids, hashes, numbers and counts (issue #157 body: "仓库只收脱敏
计数、单元格身份、指纹、快照/切分哈希、终态").  GitHub receives only the
desensitized summary and the report-package hash.
"""

import hashlib
import json
import platform
import sys

from public_layer_slicer import scan_privacy


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def environment_summary():
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def split_hashes(snapshot_path, prefix_events, suffix_events):
    """Deterministic SHA-256s of the prefix/suffix event-id splits.

    The split is defined by the frozen HLC cutoff (prefix inclusive).  The
    hashes cover only event ids (desensitized identifiers), never raw text;
    they let a reviewer verify the exact split partition.
    """
    def _hash(events):
        ids = sorted(event.event_id for event in events)
        digest = hashlib.sha256()
        digest.update(b"ac157-split-v1\n")
        for event_id in ids:
            digest.update(event_id.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    prefix_path = None
    suffix_path = None
    return {
        "cutoff_hlc": [1787065441087, 0],
        "prefix_event_count": len(prefix_events),
        "suffix_event_count": len(suffix_events),
        "prefix_sha256": _hash(prefix_events),
        "suffix_sha256": _hash(suffix_events),
        "snapshot_sha256": _file_sha256(snapshot_path),
    }


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ReportError(Exception):
    """A true fault in report generation."""


class PrivacyViolation(ReportError):
    """The report contains private/raw content and cannot be delivered."""


def build_report(*, engine_version, code_sha, snapshot, prefix_events,
                 suffix_events, route_results, decision, data, tau_status,
                 margin_base, grid_manifest, seed, replicates,
                 public_b_unused=True, personal_r_unused=True,
                 live_gamma=0.0, report_notes=None, decisions=None):
    """Assemble the desensitized report dict (AC-157-v1).

    ``snapshot`` is the ``take_snapshot`` record; ``route_results`` the
    ``run_route`` records; ``decision`` the ``assemble_shortlist`` terminal
    record.  The report carries counts, hashes and cell identities only.
    """
    if not snapshot or not snapshot.get("sha256"):
        raise ReportError("snapshot record is required")
    identity = snapshot.get("identity") or {}
    report = {
        "contract": "AC-157-v1",
        "engine": {
            "version": engine_version,
            "program": "eval/walkforward_cc.py + calibration_cc/grid_cc/"
                       "shortlist_cc/suffix_report",
        },
        "code_sha": code_sha,
        "snapshot": {
            "sha256": snapshot["sha256"],
            "history_id": identity.get("history_id"),
            "store_epoch": identity.get("store_epoch"),
            "status": {
                "status_check": (snapshot.get("status") or {}).get(
                    "status_check", "skipped"),
            },
        },
        "split": split_hashes(snapshot["path"], prefix_events,
                              suffix_events),
        "seed": seed,
        "replicates": replicates,
        "environment": environment_summary(),
        "grid_manifest": grid_manifest,
        "tau_calibration": [
            {"route_id": r["route_id"], "tau": r.get("tau")}
            for r in route_results],
        "routes": route_results,
        "data": data,
        "decision": decision,
        "margin_base": margin_base,
        "claim_support": {
            "public_b_unused": public_b_unused,
            "personal_2x2_r_unused": personal_r_unused,
            "live_gamma": live_gamma,
        },
        "notes": report_notes or [],
    }
    if decisions:
        report["decisions"] = decisions
    digest = hashlib.sha256(
        _canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def verify_privacy(report):
    """Scan the serialized report for private/raw markers.

    Refuse delivery on any finding: the report carries desensitized counts,
    cell identities, fingerprints, snapshot/split hashes and the terminal
    only (AC-157-6).
    """
    findings = scan_privacy(report)
    if findings:
        raise PrivacyViolation("; ".join(findings))
    return True


def render_markdown(report):
    """A human-readable desensitized summary (no raw text)."""
    lines = [
        "# Suffix Walk-Forward Report (AC-157-v1)",
        "",
        "- Engine: %s" % report["engine"]["version"],
        "- Code SHA: `%s`" % report["code_sha"],
        "- Snapshot SHA-256: `%s`" % report["snapshot"]["sha256"],
        "- Split cutoff HLC: `[%s,%s]`" % tuple(
            report["split"]["cutoff_hlc"]),
        "- Prefix events: %d (sha256 `%s`)" % (
            report["split"]["prefix_event_count"],
            report["split"]["prefix_sha256"]),
        "- Suffix events: %d (sha256 `%s`)" % (
            report["split"]["suffix_event_count"],
            report["split"]["suffix_sha256"]),
        "- Seed: %s / replicates: %s" % (report["seed"],
                                         report["replicates"]),
        "- Terminal outcome: **%s**" % report["decision"]["outcome"],
        "- Live γ: %s" % report["claim_support"]["live_gamma"],
        "",
        "## τ calibration (prefix only)",
        "",
        "```json",
        json.dumps(report["tau_calibration"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Data state",
        "",
        "```json",
        json.dumps(report["data"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Decision",
        "",
        "```json",
        json.dumps(report["decision"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Routes",
        "",
    ]
    for route in report["routes"]:
        lines.append("### %s" % route["route_id"])
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(route, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    if report.get("notes"):
        lines.append("## Notes")
        lines.append("")
        for note in report["notes"]:
            lines.append("- %s" % note)
        lines.append("")
    if report.get("decisions"):
        lines.append("## Decision record")
        lines.append("")
        for decision in report["decisions"]:
            lines.append("- %s" % decision)
        lines.append("")
    lines.append("Report SHA-256: `%s`" % report["report_sha256"])
    return "\n".join(lines)