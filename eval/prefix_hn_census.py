#!/usr/bin/env python3
"""Facts-only hard-negative query census (Habit130/squirrel#158, AC-158-v1).

On the pinned #157 claim-time snapshot, extend the development prefix to
the snapshot's **max unretracted HLC (inclusive)** and count, with the
frozen candidate-conditioned hard-negative definition, how many prefix
queries WILL have a hard negative — before any model forward:

- **New cutoff** = max HLC among unretracted events in the pinned snapshot,
  inclusive (owner decision 2026-08-26: "新截止点 = #157 快照末端").
  Every unretracted event in the snapshot is in the new prefix; the
  in-snapshot suffix count is 0 by definition of the snapshot-max cutoff,
  never 数据不足.
- **Primary count** = the frozen `prefix_hard_negative_query_count`
  (``calibration_cc.py``) applied to those prefix targets: same
  choice-problem key, HLC earlier, unretracted, differing final selection,
  and that selection landing in the target's current competition set.
  Threshold stays 200 (issue #158 body; do not change the definition or
  the threshold).
- **Terminals (exactly one)**: 可标定 when the primary count >= 200,
  仍不可标定 below.  可标定 only unlocks a later walk-forward freeze
  contract; it does not start walk-forward here.
- **Optional appendix**: a #77-wide count (same-key, earlier, unretracted,
  differing selection **without** the current-competition filter) on the
  same snapshot, diagnostic only and never the terminal.

This census runs purely on the snapshot: no model, no grid, no live `α`/`γ`
change, no `~/Library/Rime` deploy.  The report carries only hashes, the
numeric HLC pair, counts and the terminal — no 上文, no candidate text, no
machine paths.
"""

import hashlib
import json
import os
import platform
import sys

if os.path.basename(os.path.dirname(__file__)) == "eval":
    _REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _path in (os.path.dirname(os.path.abspath(__file__)),
                  os.path.join(_REPO, "daemon")):
        if _path not in sys.path:
            sys.path.insert(0, _path)

from walkforward_cc import FrozenFacts  # noqa: E402
from calibration_cc import prefix_hard_negative_query_count  # noqa: E402
from grid_cc import facts_only_data_count  # noqa: E402
from public_layer_slicer import scan_privacy  # noqa: E402
from oracle import match_text  # noqa: E402

# Engine identity (AC-158-v1 contract).
CONTRACT_ID = "AC-158-v1"
ENGINE_VERSION = "prefix-hn-census-v1"
MIN_HARD_NEGATIVE_QUERIES = 200
TERMINAL_CALIBRATABLE = "可标定"
TERMINAL_NOT_CALIBRATABLE = "仍不可标定"

# Pinned snapshot identity (issue #158 body; RISK-158-1).  The driver
# fails closed unless the file bytes reproduce this hash and identity.
PINNED_SNAPSHOT_SHA256 = "aa39556a984ebf6b18c416b348882a1aa2c243f4d8853541d3177f1a0b2fb394"
PINNED_HISTORY_ID = "dc3ffbf1a21957e0bb4ceed535c9df56"
PINNED_STORE_EPOCH = "8407bd6b456ba5c5a526b4b95951bac3"


class CensusError(Exception):
    """A true fault in the facts-only census inputs."""


class PrivacyViolation(CensusError):
    """The report contains private/raw content and cannot be delivered."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_max_unretracted_hlc(events):
    """The new cutoff: max HLC among unretracted events (inclusive).

    AC-158-2: the new prefix upper bound is this pair, written numerically
    into the report.  It supersedes the #77 prefix upper bound
    `[1787065441087, 0]` for this snapshot.
    """
    unretracted = [event for event in events if not event.retracted]
    if not unretracted:
        raise CensusError("snapshot has no unretracted events")
    return max(event.hlc for event in unretracted)


def wide_hard_negative_query_count(facts, prefix_targets):
    """#77-wide diagnostic appendix (no current-competition filter).

    Same selection-problem key, HLC earlier, unretracted, differing final
    selection — without the requirement that the differing selection lands
    in the target's current competition set.  Diagnostic only (issue #158
    body: "只作诊断，不得决定终态").
    """
    retracted = facts.all_retractions()
    events = facts.events()
    by_key = {}
    for event in events:
        by_key.setdefault(event.key, []).append(event)
    count = 0
    for target in prefix_targets:
        target_selection = match_text(target.final_selection_text)
        for history in by_key.get(target.key, ()):
            if history.commit_id == target.commit_id:
                continue
            if history.hlc > target.hlc:
                continue
            retraction = retracted.get(history.commit_id)
            if retraction is not None and retraction <= target.hlc:
                continue
            if match_text(history.final_selection_text) == target_selection:
                continue
            count += 1
            break
    return count


def terminal(primary_count):
    """Exactly one legal terminal from the primary count (AC-158-3)."""
    if primary_count >= MIN_HARD_NEGATIVE_QUERIES:
        return {
            "outcome": TERMINAL_CALIBRATABLE,
            "threshold": MIN_HARD_NEGATIVE_QUERIES,
            "reason": ("primary hard-negative query count %d >= %d; "
                       "walk-forward is NOT started by this census"
                       % (primary_count, MIN_HARD_NEGATIVE_QUERIES)),
        }
    return {
        "outcome": TERMINAL_NOT_CALIBRATABLE,
        "threshold": MIN_HARD_NEGATIVE_QUERIES,
        "reason": ("primary hard-negative query count %d < %d"
                   % (primary_count, MIN_HARD_NEGATIVE_QUERIES)),
    }


def census_counts(facts, prefix_targets, wide_targets=None):
    """The full facts-only census over the new prefix.

    Returns the primary count (frozen definition), the #77-wide diagnostic
    appendix count and the data-state block (unretracted / group-complete /
    keys; AC-158-3 + AC-158-4).  Actionability is an AC-157 replay concept
    and is not invented here.
    """
    primary = prefix_hard_negative_query_count(facts, prefix_targets)
    wide = wide_hard_negative_query_count(
        facts, wide_targets if wide_targets is not None else prefix_targets)
    state = facts_only_data_count(prefix_targets)
    data = {key: state[key]
            for key in ("replayable", "group_complete", "keys",
                        "explicit_indexed", "rank_gt1", "coverage")}
    return {
        "primary_count": primary,
        "threshold": MIN_HARD_NEGATIVE_QUERIES,
        "wide_77_diagnostic": wide,
        "data": data,
    }


def build_report(*, code_sha, snapshot_sha256, identity, cutoff_hlc,
                 counts, terminal_record, prefix_event_ids=(),
                 notes=None, decisions=None):
    """Assemble the desensitized census report dict (AC-158-v1).

    ``identity`` is the snapshot meta (history_id / store_epoch) and
    ``prefix_event_ids`` the new-prefix event-id set used only for the
    split hash.  The report carries hashes, the numeric cutoff HLC pair,
    counts and the terminal only.
    """
    split = _split_hashes(prefix_event_ids, cutoff_hlc)
    report = {
        "contract": CONTRACT_ID,
        "engine": {
            "version": ENGINE_VERSION,
            "program": "eval/prefix_hn_census.py + "
                       "eval/run_prefix_hn_census.py",
        },
        "code_sha": code_sha,
        "snapshot": {
            "sha256": snapshot_sha256,
            "history_id": identity.get("history_id"),
            "store_epoch": identity.get("store_epoch"),
        },
        "cutoff": {
            "hlc": [cutoff_hlc[0], cutoff_hlc[1]],
            "inclusive": True,
            "definition": ("max HLC among unretracted events in the "
                           "pinned snapshot (issue #158 body); every "
                           "unretracted event is in the new prefix"),
        },
        "split": split,
        "hard_negative": {
            "primary_count": counts["primary_count"],
            "threshold": counts["threshold"],
            "primary_definition": ("prefix_hard_negative_query_count "
                                   "(calibration_cc): same choice-problem "
                                   "key, HLC earlier, unretracted, "
                                   "differing final selection, and that "
                                   "selection in the current competition "
                                   "set"),
            "wide_77_diagnostic": counts["wide_77_diagnostic"],
            "appendix_note": ("#77-wide count (no current-competition "
                              "filter) is diagnostic only and never "
                              "chooses the terminal"),
        },
        "data": counts["data"],
        "terminal": terminal_record,
        "claim_support": {
            "live_gamma": 0.0,
            "walkforward_started": False,
            "no_model_forward": True,
            "no_grid_scan": True,
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "notes": notes or [],
    }
    if decisions:
        report["decisions"] = decisions
    digest = hashlib.sha256(
        _canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def _split_hashes(prefix_event_ids, cutoff_hlc):
    """Deterministic SHA-256 of the new-prefix event-id set.

    The prefix is every unretracted event (cutoff = snapshot max, so the
    in-snapshot suffix count is 0 by definition — not 数据不足).  The hash
    covers event ids only (desensitized), so a reviewer can verify the
    exact partition.
    """
    ids = sorted(prefix_event_ids)
    digest = hashlib.sha256()
    digest.update(b"ac158-prefix-v1\n")
    for event_id in ids:
        digest.update(event_id.encode("utf-8"))
        digest.update(b"\0")
    return {
        "cutoff_hlc": [cutoff_hlc[0], cutoff_hlc[1]],
        "prefix_event_count": len(ids),
        "suffix_event_count": 0,
        "suffix_note": ("in-snapshot suffix count is 0 by definition of "
                        "the snapshot-max cutoff, not 数据不足"),
        "prefix_sha256": digest.hexdigest(),
    }


def verify_privacy(report):
    """Scan the serialized report for private/raw markers (AC-158-5)."""
    findings = scan_privacy(report)
    if findings:
        raise PrivacyViolation("; ".join(findings))
    return True


def render_markdown(report):
    """A human-readable desensitized summary (no raw text)."""
    lines = [
        "# Prefix Hard-Negative Query Census (AC-158-v1)",
        "",
        "- Engine: %s" % report["engine"]["version"],
        "- Contract: %s" % report["contract"],
        "- Code SHA: `%s`" % report["code_sha"],
        "- Snapshot SHA-256: `%s`" % report["snapshot"]["sha256"],
        "- Snapshot identity: history `%s` / epoch `%s`" % (
            report["snapshot"]["history_id"],
            report["snapshot"]["store_epoch"]),
        "- Cutoff (max unretracted HLC, inclusive): `[%d,%d]`" % tuple(
            report["cutoff"]["hlc"]),
        "- Prefix events: %d (sha256 `%s`)" % (
            report["split"]["prefix_event_count"],
            report["split"]["prefix_sha256"]),
        "- In-snapshot suffix events: 0 (definition)",
        "- Primary hard-negative queries: **%d** (threshold %d)" % (
            report["hard_negative"]["primary_count"],
            report["hard_negative"]["threshold"]),
        "- #77-wide diagnostic: %d" % (
            report["hard_negative"]["wide_77_diagnostic"]),
        "- Terminal: **%s**" % report["terminal"]["outcome"],
        "",
        "## Data state (new prefix)",
        "",
        "```json",
        json.dumps(report["data"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Hard-negative definition",
        "",
        "- %s" % report["hard_negative"]["primary_definition"],
        "- %s" % report["hard_negative"]["appendix_note"],
        "",
        "## Terminal",
        "",
        "```json",
        json.dumps(report["terminal"], ensure_ascii=False, indent=2),
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


def run_census(snapshot_path, *, code_sha, verbose=True):
    """Verify the pinned snapshot, run the census, return (report, facts).

    ``report["data"]`` carries the desensitized counts; the private
    event-id list is kept in ``report["_prefix_event_ids"]`` temporarily
    for the split hash and stripped before return via ``_public_report``.
    """
    if not _file_sha256(snapshot_path) == PINNED_SNAPSHOT_SHA256:
        raise CensusError(
            "snapshot bytes do not reproduce the pinned SHA-256 "
            "(RISK-158-1); refusing to substitute any other copy")
    facts = FrozenFacts(snapshot_path)
    try:
        identity = facts.identity()
        if identity.get("history_id") != PINNED_HISTORY_ID:
            raise CensusError("snapshot history_id mismatch: %r"
                              % identity.get("history_id"))
        if identity.get("store_epoch") != PINNED_STORE_EPOCH:
            raise CensusError("snapshot store_epoch mismatch: %r"
                              % identity.get("store_epoch"))
        events = facts.events()
        targets = [event for event in events if not event.retracted]
        cutoff = snapshot_max_unretracted_hlc(events)
        counts = census_counts(facts, targets)
        record = terminal(counts["primary_count"])
        if verbose:
            print("snapshot sha256: %s" % PINNED_SNAPSHOT_SHA256)
            print("cutoff hlc: [%s,%s]" % (cutoff[0], cutoff[1]))
            print("unretracted events: %d" % len(targets))
            print("primary hard-negative queries: %d"
                  % counts["primary_count"])
            print("wide-77 diagnostic: %d" % counts["wide_77_diagnostic"])
            print("terminal: %s" % record["outcome"])
        report = build_report(
            code_sha=code_sha,
            snapshot_sha256=PINNED_SNAPSHOT_SHA256,
            identity={"history_id": PINNED_HISTORY_ID,
                      "store_epoch": PINNED_STORE_EPOCH},
            cutoff_hlc=cutoff,
            counts=counts,
            prefix_event_ids=[event.event_id for event in targets],
            terminal_record=record,
            notes=[
                "walk-forward is NOT started by this census; 可标定 only "
                "unlocks a later freeze contract",
                "no model forward, no grid scan, no live α/γ change "
                "(AC-158-6)",
                "the #77 prefix upper bound [1787065441087,0] is not used "
                "as the new prefix upper bound (issue #158 body)",
            ],
            decisions=[
                "d1 cutoff: new prefix upper bound = max unretracted HLC "
                "in the pinned snapshot, inclusive (AC-158-2); every "
                "unretracted event is in the new prefix, in-snapshot "
                "suffix count is 0 by definition",
                "d2 primary count: frozen prefix_hard_negative_query_count "
                "on those prefix targets; threshold 200 unchanged "
                "(AC-158-3)",
                "d3 terminal: 可标定 (primary >= 200) | 仍不可标定 "
                "(primary < 200); the #77-wide appendix never chooses the "
                "terminal",
            ],
        )
        verify_privacy(report)
        return report
    finally:
        facts.close()


def public_report(report):
    """Return the report as persisted (all keys are already deployable).

    Kept for parity with the runner seam; the report never carries private
    event-id lists.
    """
    return dict(report)