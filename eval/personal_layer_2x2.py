#!/usr/bin/env python3
"""Personal-layer 2x2 candidate-contribution cells (Squirrel #155 / AC-155-v1).

Runs the complete-key 2x2 over one frozen #77 HLC prefix snapshot with
exactly two frozen routes (`dedicated_qwen3_embedding_0_6b` and
`qwen_l28_candidate_span_mean`). The 2x2 answers only whether the candidate
contribution of a representation is distinguishable from its context effect
on this machine's own prefix events; it never calibrates a public gate, never
enables `gamma`, and never mixes with public-layer accuracy.

- Selection key = `(schema_id, category, canonical_segment_input)`.
- Every complete key contributes `key_d_cand = median(1-cos over unselected
  real candidates)` and `key_d_ctx = 1-cos(ctx1,sel vs ctx2,sel)`.
- Route `r = median(key_d_cand) / median(key_d_ctx)` with the frozen knife
  (<0.5 context-dominant, >=1 candidate signal, otherwise grey, median==0
  no conclusion).
- Committed artifacts carry key hashes, counts, r, knife and verdict only;
  never preceding text, candidate text, machine paths or live facts.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_layer_slicer import (canonical_json, scan_privacy, sha256_bytes)  # noqa: E402
from representations import (candidate_conditioned_payload, cosine,  # noqa: E402
                             window_text)


CONTRACT_ID = "AC-155-v1"
PRIMARY_PIN_SHA256 = (
    "b1bfde41a9399a67409691f0de22dda7690a69ceb87edebcd3fe44059c87ba76")
FALLBACK_PIN_SHA256 = (
    "ce69b7292a92cf6a64c24c512d843250cfdd2a3c837c3772b277bae686709be7")
FALLBACK_PIN_NAME = "facts-prefix-hlc-1787065441087.sqlite3"
HLC_MIN = (1786806466751, 0)
HLC_MAX_INCLUSIVE = (1787065441087, 0)
MIN_COMPLETE_KEYS = 30
PAYLOAD_RULE = "last64(preceding)+candidate"
SELECTION_KEY = ("schema_id", "category", "canonical_segment_input")
ROUTE_IDS = (
    "dedicated_qwen3_embedding_0_6b",
    "qwen_l28_candidate_span_mean",
)
KEY_PAYLOADS = "all four 2x2 cells use last64(preceding)+candidate"
EMBED_INSTRUCTION = "none (Qwen3-emb query instruction not applied)"
FREEZE_NAME = "prefix_2x2_freeze.json"
REPORT_JSON_NAME = "prefix_2x2_report.json"
REPORT_MD_NAME = "PX2X_REPORT.md"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "personal_layer"
NO_CONCLUSION = "无结论"

KNIFE_DOMINANT = "上文主导"
KNIFE_SIGNAL = "候选信号不低于上文"
KNIFE_GREY = "灰色"
KNIFE_NO_CONCLUSION = NO_CONCLUSION
CROSS_DUAL_DOMINANT = "双主导"
CROSS_DUAL_SIGNAL = "双有信号"
CROSS_SPLIT = "分裂"
CROSS_ANY_GREY = "任一灰色"


class Personal2x2Error(Exception):
    """A contract fault in the personal-layer 2x2."""


@dataclass(frozen=True)
class PrefixEvent:
    """One active selection event inside the frozen prefix window."""

    event_id: str
    schema_id: str
    category: str
    canonical_input: str
    hlc: tuple
    preceding: str
    selected: str
    candidates: tuple

    def replayable(self) -> bool:
        return self.selected in self.candidates

    def window(self) -> str:
        return window_text(self.preceding)

    def unselected(self) -> tuple:
        return tuple(candidate for candidate in self.candidates
                     if candidate != self.selected)

    def key(self) -> tuple:
        return (self.schema_id, self.category, self.canonical_input)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hlc_range(rows):
    if not rows:
        return None
    physical = [row["hlc_physical_ms"] for row in rows]
    logical = [row["hlc_logical"] for row in rows]
    return ((min(physical), min(logical)), (max(physical), max(logical)))


def load_prefix_snapshot(path, *, hlc_min=HLC_MIN,
                         hlc_max_inclusive=HLC_MAX_INCLUSIVE):
    """Read the active events of a pinned prefix snapshot, read-only.

    The whole recorded event range must lie inside the frozen prefix window;
    events outside the window would mean the file is not the pinned prefix.
    """
    if not isinstance(path, (str, Path)) or not Path(path).is_file():
        raise Personal2x2Error("snapshot file not found")
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        selected = conn.execute(
            "SELECT event_id, schema_id, category, canonical_segment_input,"
            " hlc_physical_ms, hlc_logical, preceding_text,"
            " final_selection_text FROM selection_events").fetchall()
    finally:
        conn.close()
    if not selected:
        raise Personal2x2Error("snapshot has no events")
    try:
        prepared = [
            (row["event_id"], row["schema_id"], row["category"],
             row["canonical_segment_input"],
             (row["hlc_physical_ms"], row["hlc_logical"]),
             row["preceding_text"], row["final_selection_text"])
            for row in selected
        ]
        events = {row[0]: row for row in prepared}
    except (KeyError, TypeError) as error:
        raise Personal2x2Error("snapshot schema is not the fact store") from error

    full_range = _hlc_range(selected)
    if full_range[0] < hlc_min or full_range[1] > hlc_max_inclusive:
        raise Personal2x2Error(
            "snapshot HLC range %s..%s exceeds the frozen prefix" % full_range)

    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        candidate_rows = conn.execute(
            "SELECT event_id, text FROM selection_candidates"
            " ORDER BY event_id, merge_order").fetchall()
        active_ids = {
            row["event_id"] for row in conn.execute(
                "SELECT event_id FROM active_events").fetchall()
        }
    finally:
        conn.close()

    candidates = {}
    for row in candidate_rows:
        candidates.setdefault(row["event_id"], []).append(row["text"])
    prefix_events = []
    for item in prepared:
        event_id = item[0]
        if event_id not in active_ids:
            continue
        if event_id not in candidates:
            raise Personal2x2Error("event without competition set: %s"
                                   % event_id)
        prefix_events.append(PrefixEvent(
            event_id=event_id,
            schema_id=item[1],
            category=item[2],
            canonical_input=item[3],
            hlc=item[4],
            preceding=item[5],
            selected=item[6],
            candidates=tuple(candidates[event_id]),
        ))
    return prefix_events


def verify_snapshot_sha256(path, expected_sha256, *, file_text):
    """Byte-hash the pinned snapshot and compare with the contract pin."""
    digest = sha256_bytes(Path(path).read_bytes())
    if digest != expected_sha256:
        raise Personal2x2Error(
            "%s mismatch: has %s, pin expects %s"
            % (file_text, digest, expected_sha256))
    return digest


def group_keys(events):
    """Events by selection key, each group sorted by (HLC, event_id)."""
    groups = {}
    for event in events:
        groups.setdefault(event.key(), []).append(event)
    for key in groups:
        groups[key].sort(key=lambda event: (event.hlc, event.event_id))
    return groups


def base_and_partner(group):
    """The frozen complete-key pair inside one key group.

    base = the HLC-earliest replayable event with at least one unselected
    real candidate.  partner = the HLC-earliest other event whose last-64
    window is literally different from base's (no further requirement).
    Returns None when either is missing.
    """
    base = None
    for event in group:
        if event.replayable() and event.unselected():
            base = event
            break
    if base is None:
        return None
    partner = None
    for event in group:
        if event.event_id == base.event_id:
            continue
        if event.window() != base.window():
            partner = event
            break
    if partner is None:
        return None
    return base, partner


def classify_keys(groups):
    """(complete, reasons): every complete key and per-reason counts.

    complete maps each selection key to its (base, partner) pair; reasons
    counts keys that failed the base condition (no replayable event with an
    unselected real candidate) or the partner condition (no event with a
    literally different last-64 window).
    """
    complete = {}
    reasons = {"no_replayable_base": 0, "no_partner_window": 0}
    for key, group in groups.items():
        pair = base_and_partner(group)
        if pair is not None:
            complete[key] = pair
            continue
        if any(event.replayable() and event.unselected()
               for event in group):
            reasons["no_partner_window"] += 1
        else:
            reasons["no_replayable_base"] += 1
    return complete, reasons


def key_sha256(key):
    payload = {
        "schema_id": key[0],
        "category": key[1],
        "canonical_segment_input": key[2],
    }
    return sha256_text(canonical_json(payload))


def key_statistics(base, partner, encode):
    """Median contribution over the base's unselected candidates and d_ctx.

    encode takes (ctx, candidate) and returns the L2-normalized FP32 vector
    of ``last64(ctx)+candidate`` (the frozen payload for all four cells).
    """
    ctx1 = base.window()
    ctx2 = partner.window()
    selected = base.selected
    selected_vec = encode(ctx1, selected)
    ctx_vec = encode(ctx2, selected)
    candidate_distances = [
        1.0 - cosine(selected_vec, encode(ctx1, candidate))
        for candidate in base.unselected()
    ]
    if not candidate_distances:
        raise Personal2x2Error("complete key with no unselected candidate")
    return (statistics.median(candidate_distances),
            1.0 - cosine(selected_vec, ctx_vec))


def knife_for(r):
    if r < 0.5:
        return KNIFE_DOMINANT
    if r >= 1.0:
        return KNIFE_SIGNAL
    return KNIFE_GREY


def route_summary(key_ds):
    """Route-level median r with the frozen knife.

    key_ds = sequence of (key_d_cand, key_d_ctx) per complete key.
    """
    if not key_ds:
        return {"label": KNIFE_NO_CONCLUSION, "r": None,
                "median_key_d_cand": None, "median_key_d_ctx": None}
    d_cand = statistics.median(ds[0] for ds in key_ds)
    d_ctx = statistics.median(ds[1] for ds in key_ds)
    if d_ctx == 0.0:
        return {"label": KNIFE_NO_CONCLUSION, "r": None,
                "median_key_d_cand": d_cand, "median_key_d_ctx": d_ctx}
    r = d_cand / d_ctx
    return {"median_key_d_cand": d_cand, "median_key_d_ctx": d_ctx,
            "r": r, "label": knife_for(r)}


def cross_route_summary(labels):
    if set(labels) != set(ROUTE_IDS):
        raise Personal2x2Error("cross-route synthesis needs both routes")
    if any(label in (KNIFE_GREY, KNIFE_NO_CONCLUSION)
           for label in labels.values()):
        return CROSS_ANY_GREY
    distinct = set(labels.values())
    if distinct == {KNIFE_DOMINANT}:
        return CROSS_DUAL_DOMINANT
    if distinct == {KNIFE_SIGNAL}:
        return CROSS_DUAL_SIGNAL
    if distinct == {KNIFE_DOMINANT, KNIFE_SIGNAL}:
        return CROSS_SPLIT
    raise Personal2x2Error("unexpected knife label set: %r" % distinct)


def build_freeze(*, snapshot_sha256, code_sha, complete_keys,
                 complete_key_count, incomplete_reasons):
    if snapshot_sha256 != FALLBACK_PIN_SHA256 and \
            snapshot_sha256 != PRIMARY_PIN_SHA256:
        raise Personal2x2Error("snapshot SHA is not an accepted #77 pin")
    if not isinstance(code_sha, str) or not code_sha:
        raise Personal2x2Error("code SHA is missing")
    if len(complete_keys) != complete_key_count:
        raise Personal2x2Error("complete key list/count drifted")
    key_hashes = sorted(complete_keys)
    freeze = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "snapshot_sha256": snapshot_sha256,
        "hlc_min": list(HLC_MIN),
        "hlc_max_inclusive": list(HLC_MAX_INCLUSIVE),
        "payload_rule": PAYLOAD_RULE,
        "selection_key": list(SELECTION_KEY),
        "min_complete_keys": MIN_COMPLETE_KEYS,
        "routes": list(ROUTE_IDS),
        "embedding_instruction": EMBED_INSTRUCTION,
        "complete_key_count": complete_key_count,
        "incomplete_key_count": sum(incomplete_reasons.values()),
        "incomplete_reasons": {
            key: count for key, count in sorted(incomplete_reasons.items())},
        "complete_keys": key_hashes,
    }
    freeze["freeze_digest"] = sha256_text(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_digest"}))
    return freeze


def freeze_path(artifact_dir):
    return Path(artifact_dir) / FREEZE_NAME


def report_json_path(artifact_dir):
    return Path(artifact_dir) / REPORT_JSON_NAME


def report_md_path(artifact_dir):
    return Path(artifact_dir) / REPORT_MD_NAME


def write_freeze(artifact_dir, freeze):
    path = freeze_path(artifact_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(canonical_json(freeze) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_freeze(artifact_dir):
    path = freeze_path(artifact_dir)
    if not path.is_file():
        raise Personal2x2Error("freeze is missing from the artifact dir")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("contract") != CONTRACT_ID:
        raise Personal2x2Error("freeze contract drifted")
    expected_digest = sha256_text(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_digest"}))
    if freeze.get("freeze_digest") != expected_digest:
        raise Personal2x2Error("freeze digest verification failed")
    return freeze


def apply_scores(artifact_dir, freeze, per_route_ds):
    expected = freeze["complete_key_count"]
    for route_id, key_ds in per_route_ds.items():
        if route_id not in ROUTE_IDS:
            raise Personal2x2Error("route outside the frozen set: %s"
                                   % route_id)
        if len(key_ds) != expected:
            raise Personal2x2Error(
                "route %s key count drifted: %s != %s"
                % (route_id, len(key_ds), expected))
    if expected < MIN_COMPLETE_KEYS:
        empty = {"label": KNIFE_NO_CONCLUSION, "r": None,
                 "median_key_d_cand": None, "median_key_d_ctx": None}
        return {
            "contract": CONTRACT_ID,
            "freeze_digest": freeze["freeze_digest"],
            "snapshot_sha256": freeze["snapshot_sha256"],
            "complete_key_count": expected,
            "min_complete_keys": MIN_COMPLETE_KEYS,
            "terminal": NO_CONCLUSION,
            "routes": {route_id: dict(empty) for route_id in ROUTE_IDS},
            "cross_route": CROSS_ANY_GREY,
        }
    summaries = {
        route_id: route_summary(key_ds)
        for route_id, key_ds in per_route_ds.items()
    }
    if len(summaries) != len(ROUTE_IDS):
        raise Personal2x2Error("route summaries do not cover both routes")
    labels = {route_id: summary["label"]
              for route_id, summary in summaries.items()}
    return {
        "contract": CONTRACT_ID,
        "freeze_digest": freeze["freeze_digest"],
        "snapshot_sha256": freeze["snapshot_sha256"],
        "complete_key_count": expected,
        "min_complete_keys": MIN_COMPLETE_KEYS,
        "terminal": "判定",
        "routes": summaries,
        "cross_route": cross_route_summary(labels),
    }


def _privacy_findings(value):
    return scan_privacy(value)


def write_report(artifact_dir, freeze, report, md_text):
    findings = _privacy_findings(report)
    findings.extend(_privacy_findings(md_text))
    if findings:
        raise Personal2x2Error("privacy scan failed: %s"
                               % "; ".join(findings))
    (Path(artifact_dir) / REPORT_JSON_NAME).write_text(
        canonical_json(report) + "\n", encoding="utf-8")
    (Path(artifact_dir) / REPORT_MD_NAME).write_text(
        md_text, encoding="utf-8")


def current_code_sha(*, require_clean):
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                  cwd=str(_ROOT), text=True).strip()
    if not require_clean:
        return sha
    dirty = subprocess.check_output(["git", "status", "--porcelain"],
                                    cwd=str(_ROOT), text=True)
    ignored = (".cache/", "personal_layer/", "prefix_2x2_", ".local-work/",
               "PX2X_REPORT.md", "__pycache__")
    leftover = [
        line for line in dirty.splitlines()
        if not any(marker in line for marker in ignored)
    ]
    if leftover:
        raise Personal2x2Error("real run requires a clean code worktree: %s"
                               % "; ".join(leftover))
    return sha