#!/usr/bin/env python3
"""Actionable group-complete milestone census (Habit130/squirrel#162, AC-162-v1).

A lightweight, read-only census that answers whether the AC-159 fixed split
has reached the predeclared milestone of 3000 actionable group-complete
events, using the SAME reference-route semantics that produced the accepted
AC-159 ``2537 + 13 = 2550`` count:

- **Snapshot**: one fresh read-only SQLite Online Backup at run time; the
  live semantic-memory store stays untouched.
- **Cutoff**: frozen at ``[1787667799562, 0]`` (the AC-159 split); prefix is
  inclusive, suffix strictly later.  Never moved to the new snapshot
  maximum, never folded into prefix.
- **Route**: exactly ``dedicated_qwen3_embedding_0_6b``: payload
  ``last64(preceding)+candidate``, frozen English query instruction on the
  query side only, no event-side instruction, same candidate normalization,
  strict-HLC history, same-commit exclusion and as-of retraction semantics
  as AC-159 (the census replays through the AC-159 seam directly).
- **Reference parameters**: ``tau=0``, ``K_evidence=8``, ``H=inf``,
  ``saturation_k=1``, ``gamma=0``.  ``actionable`` stays ``any(s > 0)`` —
  gamma zero preserves the shadow order but does not redefine
  actionability.
- **Group-complete**: saved same-group competition size ``< 32`` (the
  persisted ``competition_complete`` bit is diagnostic only, exactly as in
  the #76/#77 rewrite).
- **Counts**: prefix, suffix and total replayable, group-complete,
  actionable group-complete and actionable-key counts.
- **Terminal (exactly one)**: ``reached_3000`` iff the total actionable
  group-complete count is at least 3000; otherwise ``pending_3000`` with the
  exact remaining count ``3000 - total``.  Neither terminal starts the full
  walk-forward or changes live behavior.

No L28/BGE model, no τ calibration, no parameter grid, no bootstrap, no
quality/safety gate, no shortlist, no ANN, no deployment and no live
alpha/gamma/evidence change.  Private data (snapshot, vector cache, working
freeze/report copies) stays under the ignored ``.local-work/ac162-actionable-census/``
directory; only the desensitized freeze/report reach the tracked artifact
path ``eval/actionable_milestone_census/``, which is a new path and never
touches ``eval/suffix_walkforward/`` or ``eval/suffix_walkforward_ac159/``.

The report carries only hashes, identities, HLC pairs, counts and the
terminal — no preceding text, candidate text, facts, vectors or machine
paths.
"""

import hashlib
import json
import os
import platform
import sys

from public_layer_slicer import canonical_json, scan_privacy, sha256_bytes
from walkforward_cc import (  # noqa: E402
    CONTRACT_ID as AC159_CONTRACT_ID,
    ENGINE_VERSION as AC159_ENGINE_VERSION,
    PREFIX_HLC_MAX_INCLUSIVE, ROUTE_IDS, GROUP_COMPLETE_N,
    CandidateVectorTable, FrozenFacts, WalkForwardReplay,
    prefix_suffix_split)
from grid_cc import data_counts  # noqa: E402

# Engine identity (AC-162-v1 contract).
CONTRACT_ID = "AC-162-v1"
ENGINE_VERSION = "actionable-milestone-census-v1"
# The milestone gate (issue #162 body): total actionable group-complete
# events >= 3000 -> reached_3000.
MILESTONE_THRESHOLD = 3000
TERMINAL_REACHED = "reached_3000"
TERMINAL_PENDING = "pending_3000"
SPLIT_HASH_VERSION = "ac162-split-v1"
# The single frozen route (AC-159 first route; issue #162 body).
ROUTE_ID = ROUTE_IDS[0]
# Reference parameters (issue #162 body / handoff Established): exactly the
# AC-159 reference cell, replayed at gamma=0.
REFERENCE_TAU = 0.0
REFERENCE_K_EVIDENCE = 8
REFERENCE_HALF_LIFE = float("inf")
REFERENCE_SATURATION_K = 1.0
REFERENCE_GAMMA = 0.0
# Count keys carried per split (issue #162 body).
CENSUS_COUNT_KEYS = ("replayable", "group_complete",
                     "actionable_group_complete", "actionable_keys")

# The canonical count values accepted at AC-159 (quoted for the record;
# historical comparison, never forced onto a newer snapshot).
AC159_REFERENCE = {
    "snapshot_sha256":
        "4aebca791976c520d749525e177e2c6769a999290e5d49a58001f5a99f4359e9",
    "prefix_actionable_group_complete": 2537,
    "suffix_actionable_group_complete": 13,
    "total_actionable_group_complete": 2550,
}


class CensusError(Exception):
    """A true fault in the actionable-milestone census inputs."""


class PrivacyViolation(CensusError):
    """The report/freeze contains private/raw content and cannot be delivered."""


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reference_params():
    """The frozen reference OracleParams (tau=0, K=8, H=inf, k=1)."""
    from oracle import OracleParams
    return OracleParams(
        tau=REFERENCE_TAU,
        k_evidence=REFERENCE_K_EVIDENCE,
        half_life=REFERENCE_HALF_LIFE,
        saturation_k=REFERENCE_SATURATION_K,
    )


def reference_parameters_record():
    """JSON-safe reference parameter identity block (frozen)."""
    return {
        "tau": REFERENCE_TAU,
        "k_evidence": REFERENCE_K_EVIDENCE,
        "half_life": "inf",
        "saturation_k": REFERENCE_SATURATION_K,
        "gamma": REFERENCE_GAMMA,
        "actionable": "any(s > 0)",
        "group_complete_n": GROUP_COMPLETE_N,
        "payload_rule": "last64(preceding)+candidate",
        "query_instruction": ("Represent the candidate-conditioned query "
                              "for semantic retrieval."),
        "event_side_instruction": "none",
        "ac159_seam": "%s/%s" % (AC159_CONTRACT_ID, AC159_ENGINE_VERSION),
    }


def census_outcomes(facts, provider):
    """Replay the whole snapshot through the AC-159 seam (reference params).

    Returns the per-target ``EventOutcome`` list in HLC order produced by
    ``walkforward_cc.WalkForwardReplay`` under the frozen reference
    parameters — the exact first-route semantics of AC-159 (strict-HLC
    replay, same-commit exclusion, as-of retractions, candidate-conditioned
    evidence with ``actionable = any(s > 0)``).
    """
    events = facts.events()
    vectors = CandidateVectorTable(events, provider)
    replay = WalkForwardReplay(facts, vectors)
    return replay.replay(reference_params(), REFERENCE_GAMMA)


def census_counts(outcomes):
    """Per-split census block over replay outcomes (AC-159 count semantics).

    The four counts come from ``grid_cc.data_counts`` — the same aggregation
    that produced the accepted AC-159 ``data[route][prefix/suffix]`` block —
    so the census totals are bit-identical to the AC-159 reference seam.
    """
    state = data_counts(outcomes)
    return {key: state[key] for key in CENSUS_COUNT_KEYS}


def split_census_counts(outcomes):
    """prefix / suffix / total census blocks at the frozen cutoff."""
    prefix, suffix = prefix_suffix_split(outcomes)
    return {
        "prefix": census_counts(prefix),
        "suffix": census_counts(suffix),
        "total": census_counts(outcomes),
    }


def legal_terminal(total_actionable_group_complete):
    """Exactly one legal terminal (CENSUS3000-4).

    ``reached_3000`` iff total >= 3000, else ``pending_3000`` with the exact
    remaining count ``3000 - total``.
    """
    if not isinstance(total_actionable_group_complete, int):
        raise CensusError("total actionable group-complete must be an int")
    if total_actionable_group_complete < 0:
        raise CensusError("total actionable group-complete cannot be negative")
    if total_actionable_group_complete >= MILESTONE_THRESHOLD:
        return {
            "outcome": TERMINAL_REACHED,
            "threshold": MILESTONE_THRESHOLD,
            "remaining": 0,
            "reason": ("total actionable group-complete events %d >= %d; "
                       "the predeclared AC-162 milestone is reached; the "
                       "walk-forward is NOT started by this census"
                       % (total_actionable_group_complete,
                          MILESTONE_THRESHOLD)),
        }
    remaining = MILESTONE_THRESHOLD - total_actionable_group_complete
    return {
        "outcome": TERMINAL_PENDING,
        "threshold": MILESTONE_THRESHOLD,
        "remaining": remaining,
        "reason": ("total actionable group-complete events %d < %d; "
                   "remaining count to the milestone: %d"
                   % (total_actionable_group_complete,
                      MILESTONE_THRESHOLD, remaining)),
    }


def split_hashes(snapshot_path, prefix_events, suffix_events):
    """Deterministic SHA-256s of the prefix/suffix event-id splits.

    The split is the frozen AC-159 cutoff (prefix inclusive).  The hashes
    cover event ids only (desensitized) so a reviewer can verify the exact
    partition; the partition itself fails closed if any event crosses the
    cutoff boundary.
    """
    prefix_ids = {event.event_id for event in prefix_events}
    suffix_ids = {event.event_id for event in suffix_events}
    if prefix_ids & suffix_ids:
        raise CensusError("prefix/suffix split overlaps event ids")
    if any(event.hlc > PREFIX_HLC_MAX_INCLUSIVE for event in prefix_events):
        raise CensusError("prefix contains an event after the frozen cutoff")
    if any(event.hlc <= PREFIX_HLC_MAX_INCLUSIVE for event in suffix_events):
        raise CensusError("suffix contains an event at or before the cutoff")

    def _hash(events):
        digest = hashlib.sha256()
        digest.update((SPLIT_HASH_VERSION + "\n").encode("ascii"))
        for event_id in sorted(event.event_id for event in events):
            digest.update(event_id.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    return {
        "cutoff_hlc": list(PREFIX_HLC_MAX_INCLUSIVE),
        "prefix_event_count": len(prefix_events),
        "suffix_event_count": len(suffix_events),
        "prefix_sha256": _hash(prefix_events),
        "suffix_sha256": _hash(suffix_events),
        "snapshot_sha256": _file_sha256(snapshot_path),
    }


def build_freeze(*, code_sha, snapshot, route_identity, prefix_events,
                 suffix_events):
    """The identity freeze, written BEFORE any model score (CENSUS3000-1).

    Binds the snapshot SHA-256, ``history_id``, ``store_epoch``, code SHA,
    route/model/tokenizer identity, the frozen cutoff and the reference
    parameters.  Fails closed on any missing identity input.
    """
    if not code_sha or len(code_sha) != 40:
        raise CensusError("code SHA is required for the freeze")
    if not snapshot or not snapshot.get("sha256"):
        raise CensusError("snapshot record (with sha256) is required")
    if not route_identity or route_identity.get("route_id") != ROUTE_ID:
        raise CensusError("route identity is required and must be %s"
                          % ROUTE_ID)
    identity = snapshot.get("identity") or {}
    for key in ("history_id", "store_epoch"):
        if not identity.get(key):
            raise CensusError("snapshot %s is required for the freeze" % key)
    return {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "snapshot_sha256": snapshot["sha256"],
        "snapshot_source": snapshot.get("source",
                                        "claim_time_online_backup"),
        "history_id": identity.get("history_id"),
        "store_epoch": identity.get("store_epoch"),
        "route": route_identity,
        "cutoff_hlc": list(PREFIX_HLC_MAX_INCLUSIVE),
        "reference_parameters": reference_parameters_record(),
        "split": split_hashes(snapshot["path"], prefix_events,
                              suffix_events),
    }


def environment_summary():
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def build_report(*, code_sha, snapshot, route_identity, counts, terminal,
                 prefix_events, suffix_events, notes=None, decisions=None):
    """Assemble the desensitized census report dict (AC-162-v1).

    Counts, hashes, identities and the terminal only — never raw 上文,
    candidate text, facts, vectors or machine paths.
    """
    if not snapshot or not snapshot.get("sha256"):
        raise CensusError("snapshot record is required")
    identity = snapshot.get("identity") or {}
    report = {
        "contract": CONTRACT_ID,
        "engine": {
            "version": ENGINE_VERSION,
            "program": "eval/actionable_milestone_census.py + "
                       "eval/run_actionable_milestone_census.py",
        },
        "code_sha": code_sha,
        "snapshot": {
            "sha256": snapshot["sha256"],
            "source": snapshot.get("source", "claim_time_online_backup"),
            "history_id": identity.get("history_id"),
            "store_epoch": identity.get("store_epoch"),
            "status": {
                "status_check": (snapshot.get("status") or {}).get(
                    "status_check", "skipped"),
            },
        },
        "cutoff": {
            "hlc": list(PREFIX_HLC_MAX_INCLUSIVE),
            "inclusive": True,
            "definition": ("frozen AC-159 cutoff; prefix = hlc <= "
                           "[1787667799562,0] (inclusive), suffix = strictly "
                           "later; never moved to the new snapshot maximum "
                           "and never folded into prefix selection"),
        },
        "route": route_identity,
        "reference_parameters": reference_parameters_record(),
        "split": split_hashes(snapshot["path"], prefix_events,
                              suffix_events),
        "counts": counts,
        "terminal": terminal,
        "ac159_reference": dict(AC159_REFERENCE),
        "claim_support": {
            "no_other_route": True,
            "no_tau_calibration": True,
            "no_parameter_grid": True,
            "no_quality_gate": True,
            "no_bootstrap": True,
            "no_shortlist": True,
            "no_ann": True,
            "live_gamma": 0.0,
            "walkforward_started": False,
        },
        "environment": environment_summary(),
        "notes": notes or [],
    }
    if decisions:
        report["decisions"] = decisions
    digest = hashlib.sha256(
        canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def verify_privacy(payload):
    """Scan serialized report/freeze for private/raw markers (CENSUS3000-6)."""
    findings = scan_privacy(payload)
    if findings:
        raise PrivacyViolation("; ".join(findings))
    return True


def render_markdown(report):
    """A human-readable desensitized summary (no raw text)."""
    terminal = report["terminal"]
    lines = [
        "# Actionable Milestone Census (AC-162-v1)",
        "",
        "- Engine: %s" % report["engine"]["version"],
        "- Contract: %s" % report["contract"],
        "- Code SHA: `%s`" % report["code_sha"],
        "- Snapshot SHA-256: `%s`" % report["snapshot"]["sha256"],
        "- Snapshot identity: history `%s` / epoch `%s`" % (
            report["snapshot"]["history_id"],
            report["snapshot"]["store_epoch"]),
        "- Route: `%s`" % report["route"]["route_id"],
        "- Cutoff HLC: `[%s,%s]` (prefix inclusive)" % tuple(
            report["cutoff"]["hlc"]),
        "- Prefix events: %d (sha256 `%s`)" % (
            report["split"]["prefix_event_count"],
            report["split"]["prefix_sha256"]),
        "- Suffix events: %d (sha256 `%s`)" % (
            report["split"]["suffix_event_count"],
            report["split"]["suffix_sha256"]),
        "",
        "## Counts",
        "",
        "```json",
        json.dumps(report["counts"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Terminal",
        "",
        "```json",
        json.dumps(terminal, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Reference semantics",
        "",
        "```json",
        json.dumps(report["reference_parameters"], ensure_ascii=False,
                   indent=2),
        "```",
        "",
        "## AC-159 reference (quoted, not re-verified)",
        "",
        "```json",
        json.dumps(report["ac159_reference"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
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


def public_report(report):
    """The report as persisted (already fully desensitized)."""
    return dict(report)