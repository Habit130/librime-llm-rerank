#!/usr/bin/env python3
"""Public-layer B gate on the frozen A winner (Squirrel #156 / AC-156-v1)."""

from __future__ import annotations

import json
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

from public_layer_a import (  # noqa: E402
    CompactSlice,
    compact_counts,
    pair_hit,
    query_text,
    sha256_bytes,
)
from public_layer_slicer import (  # noqa: E402
    canonical_json,
    scan_privacy,
)


CONTRACT_ID = "AC-156-v1"
A_CONTRACT_ID = "AC-154-v4"
PINNED_SLICE_DIGEST = (
    "8818cc8033834db953c69c470453b98ecc418d45469d730d078d7c004d63d667"
)
PINNED_A_FREEZE_DIGEST = (
    "091af6f9b84925b920dced2dfb218a8079052351b8c1a2735eb9f37081250ed1"
)
A_WINNER_ROUTE = "dedicated_bge_m3"
PAIR_SET_RULE = "target_len>=2;stride=8;index_mod=0;split=B"
QUERY_RULE = "ctx-as-query:last64"
MIN_TARGET_LEN = 2
STRIDE = 8
INDEX_MOD = 0
GATE_ACCURACY = 0.70
PASS_TERMINAL = "dedicated_bge_m3"
FAIL_TERMINAL = "无公开赢家"
FREEZE_NAME = "b_freeze.json"
REPORT_JSON_NAME = "b_report.json"
REPORT_MD_NAME = "B_REPORT.md"
COMPACT_TABLE_NAME = "b_pairs_stride8.jsonl"
SOURCE_COMPACT_TABLE_NAME = "b_pairs.jsonl"
CACHE_CONTRACT_DIR = "ac156"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "public_layer"
_IGNORABLE_DIRTY_PREFIXES = (
    "?? eval/.cache/",
    "?? eval/public_layer/b_",
    " M eval/public_layer/b_",
    "?? eval/public_layer/B_REPORT.md",
    " M eval/public_layer/B_REPORT.md",
)


class PublicLayerBError(Exception):
    """A B contract fault in the public-layer gate."""


@dataclass(frozen=True)
class BFrozenIdentity:
    """A-winner identity taken from the committed #154 freeze."""

    winner: str
    freeze_digest: str
    fingerprint: str


def eligible_b_slices(slices):
    return [record for record in slices if record.get("split") == "B"
            and len(record.get("target") or "") >= MIN_TARGET_LEN]


def iter_b_pairs(slices, lexicon):
    for record in eligible_b_slices(slices):
        for competitor in lexicon.competitors(
                record["target"], record["canonical_input"]):
            yield (
                record["repo"], record["path"], int(record["start"]),
                int(record["end"]), record["target"],
                record["canonical_input"], competitor,
            )


def b_pair_keys(slices, lexicon) -> tuple:
    return tuple(iter_b_pairs(slices, lexicon))


def count_eligible_b(slices, lexicon) -> tuple[int, int]:
    records = eligible_b_slices(slices)
    pairs = 0
    for record in records:
        pairs += len(lexicon.competitors(
            record["target"], record["canonical_input"]))
    return len(records), pairs


def build_b_compact_slices(slices, lexicon, preceding_for_record) -> tuple:
    rows = []
    for record in eligible_b_slices(slices):
        competitors = tuple(lexicon.competitors(
            record["target"], record["canonical_input"]))
        rows.append(CompactSlice(
            repo=record["repo"],
            path=record["path"],
            start=int(record["start"]),
            end=int(record["end"]),
            target=record["target"],
            canonical_input=record["canonical_input"],
            preceding=preceding_for_record(record),
            competitors=competitors,
        ))
    return tuple(rows)


def score_b_pairs(rows, encode_query, encode_candidate) -> int:
    hits = 0
    for row in rows:
        query_vec = encode_query(query_text(row.preceding))
        target_vec = encode_candidate(row.preceding, row.target)
        for competitor in row.competitors:
            competitor_vec = encode_candidate(row.preceding, competitor)
            if pair_hit(query_vec, target_vec, competitor_vec):
                hits += 1
    return hits


def b_table_header(*, slice_digest, eligible_slice_count, pair_count) -> dict:
    return {
        "record": "header",
        "contract": CONTRACT_ID,
        "slice_digest": slice_digest,
        "query_rule": QUERY_RULE,
        "pair_set_rule": PAIR_SET_RULE,
        "eligible_slice_count": eligible_slice_count,
        "pair_count": pair_count,
    }


def write_b_compact_table(path: Path, rows, *, slice_digest) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    slice_count, pair_count = compact_counts(rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(
            b_table_header(
                slice_digest=slice_digest,
                eligible_slice_count=slice_count,
                pair_count=pair_count,
            ),
            ensure_ascii=False, sort_keys=True) + "\n")
        for row in rows:
            handle.write(json.dumps(
                row.to_record(), ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)
    return sha256_bytes(path.read_bytes())


def write_b_source_compact_table(path: Path, rows, *, slice_digest) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    slice_count, pair_count = compact_counts(rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(
            b_table_header(
                slice_digest=slice_digest,
                eligible_slice_count=slice_count,
                pair_count=pair_count,
            ),
            ensure_ascii=False, sort_keys=True) + "\n")
        for row in rows:
            handle.write(json.dumps(
                row.to_record(), ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)
    return sha256_bytes(path.read_bytes())


def _iter_b_table(path: Path, expected_name: str):
    header = None
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            kind = record.get("record")
            if kind == "header":
                if header is not None:
                    raise PublicLayerBError(
                        "%s has a second header" % expected_name)
                if record.get("contract") != CONTRACT_ID:
                    raise PublicLayerBError(
                        "%s contract is not v1" % expected_name)
                if record.get("query_rule") != QUERY_RULE:
                    raise PublicLayerBError(
                        "%s query rule drifted" % expected_name)
                if record.get("pair_set_rule") != PAIR_SET_RULE:
                    raise PublicLayerBError(
                        "%s pair rule drifted" % expected_name)
                if record.get("slice_digest") != PINNED_SLICE_DIGEST:
                    raise PublicLayerBError(
                        "%s slice digest drifted" % expected_name)
                header = record
                continue
            if kind != "slice":
                raise PublicLayerBError(
                    "%s record kind drifted" % expected_name)
            yield CompactSlice.from_record(record)
    if header is None:
        raise PublicLayerBError("%s header is missing" % expected_name)


def iter_b_compact_table(path: Path):
    yield from _iter_b_table(path, "compact table")


def iter_b_source_compact_table(path: Path):
    yield from _iter_b_table(path, "source table")


def load_b_compact_header(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        first = handle.readline()
    if not first.strip():
        raise PublicLayerBError("compact table is empty")
    header = json.loads(first)
    if header.get("record") != "header":
        raise PublicLayerBError("compact table header is missing")
    if header.get("contract") != CONTRACT_ID:
        raise PublicLayerBError("compact table contract is not v1")
    return header


def compact_table_path(cache: Path) -> Path:
    return Path(cache) / CACHE_CONTRACT_DIR / COMPACT_TABLE_NAME


def source_compact_table_path(cache: Path) -> Path:
    return Path(cache) / CACHE_CONTRACT_DIR / SOURCE_COMPACT_TABLE_NAME


def load_a_winner_identity(artifact_dir=DEFAULT_ARTIFACT_DIR) -> BFrozenIdentity:
    path = Path(artifact_dir) / "a_freeze.json"
    try:
        freeze = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicLayerBError("A freeze is unreadable") from error
    if (freeze.get("contract") != A_CONTRACT_ID
            or freeze.get("freeze_digest") != PINNED_A_FREEZE_DIGEST):
        raise PublicLayerBError("A freeze identity drifted")
    routes = freeze.get("routes") or {}
    winner_row = routes.get(A_WINNER_ROUTE)
    fingerprint = winner_row.get("fingerprint") if winner_row else None
    if not isinstance(fingerprint, str) or not fingerprint:
        raise PublicLayerBError("A winner fingerprint is missing")
    return BFrozenIdentity(
        winner=A_WINNER_ROUTE,
        freeze_digest=freeze["freeze_digest"],
        fingerprint=fingerprint,
    )


def build_freeze(*, slice_digest, code_sha, a_freezer_digest,
                 a_winner_fingerprint, b_source_table_digest,
                 b_source_slice_count, b_source_pair_count,
                 compact_table_digest, eligible_slice_count,
                 pair_count) -> dict:
    if slice_digest != PINNED_SLICE_DIGEST:
        raise PublicLayerBError("slice digest is not the accepted #153 pin")
    if a_freezer_digest != PINNED_A_FREEZE_DIGEST:
        raise PublicLayerBError("A freeze digest is not the #154 pin")
    if not isinstance(code_sha, str) or not code_sha:
        raise PublicLayerBError("code SHA is missing")
    if not isinstance(a_winner_fingerprint, str) or not a_winner_fingerprint:
        raise PublicLayerBError("A winner fingerprint is missing")
    if not isinstance(pair_count, int) or pair_count < 1:
        raise PublicLayerBError("pair count must be a positive integer")
    if not isinstance(eligible_slice_count, int) or eligible_slice_count < 1:
        raise PublicLayerBError(
            "eligible slice count must be a positive integer")
    if not isinstance(b_source_pair_count, int) or b_source_pair_count < 1:
        raise PublicLayerBError(
            "B source pair count must be a positive integer")
    if not isinstance(b_source_slice_count, int) or b_source_slice_count < 1:
        raise PublicLayerBError(
            "B source slice count must be a positive integer")
    if not isinstance(b_source_table_digest, str) or not b_source_table_digest:
        raise PublicLayerBError("B source table digest is missing")
    if not isinstance(compact_table_digest, str) or not compact_table_digest:
        raise PublicLayerBError("compact table digest is missing")
    freeze = {
        "contract": CONTRACT_ID,
        "slice_digest": slice_digest,
        "code_sha": code_sha,
        "a_winner": A_WINNER_ROUTE,
        "a_freezer_digest": a_freezer_digest,
        "a_winner_fingerprint": a_winner_fingerprint,
        "pair_set_rule": PAIR_SET_RULE,
        "query_rule": QUERY_RULE,
        "b_source_table_digest": b_source_table_digest,
        "b_source_slice_count": b_source_slice_count,
        "b_source_pair_count": b_source_pair_count,
        "eligible_slice_count": eligible_slice_count,
        "pair_count": pair_count,
        "compact_table_digest": compact_table_digest,
        "gate_accuracy": GATE_ACCURACY,
    }
    freeze["freeze_digest"] = sha256_bytes(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_digest"}).encode("utf-8"))
    return freeze


def freeze_path(artifact_dir: Path) -> Path:
    return Path(artifact_dir) / FREEZE_NAME


def report_json_path(artifact_dir: Path) -> Path:
    return Path(artifact_dir) / REPORT_JSON_NAME


def validate_freeze(freeze: dict) -> dict:
    if freeze.get("contract") != CONTRACT_ID:
        raise PublicLayerBError("freeze contract drifted")
    if freeze.get("query_rule") != QUERY_RULE:
        raise PublicLayerBError("freeze query rule drifted")
    if freeze.get("pair_set_rule") != PAIR_SET_RULE:
        raise PublicLayerBError("freeze pair rule drifted")
    if freeze.get("slice_digest") != PINNED_SLICE_DIGEST:
        raise PublicLayerBError("freeze slice digest drifted")
    if freeze.get("a_winner") != A_WINNER_ROUTE:
        raise PublicLayerBError("freeze A winner drifted")
    if freeze.get("a_freezer_digest") != PINNED_A_FREEZE_DIGEST:
        raise PublicLayerBError("freeze A freezer digest drifted")
    return freeze


def load_freeze(artifact_dir: Path) -> dict:
    path = freeze_path(artifact_dir)
    if not path.exists():
        raise PublicLayerBError("freeze file is missing")
    return validate_freeze(json.loads(path.read_text(encoding="utf-8")))


def write_exclusive(path: Path, content: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as error:
        raise PublicLayerBError("artifact already exists: %s" % path) from error


def write_freeze(artifact_dir: Path, freeze: dict) -> Path:
    path = freeze_path(artifact_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if report_json_path(artifact_dir).exists():
        raise PublicLayerBError("cannot rewrite freeze after scores exist")
    validate_freeze(freeze)
    write_exclusive(path, json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")
    privacy = scan_privacy(freeze)
    if privacy:
        raise PublicLayerBError("freeze privacy: " + "; ".join(privacy))
    return path


def select_verdict(accuracy) -> tuple[str, bool]:
    if not isinstance(accuracy, float) or not 0.0 <= accuracy <= 1.0:
        raise PublicLayerBError("accuracy out of range")
    if accuracy >= GATE_ACCURACY:
        return PASS_TERMINAL, True
    return FAIL_TERMINAL, False


def build_report(freeze: dict, hits: int) -> dict:
    validate_freeze(freeze)
    pair_count = freeze["pair_count"]
    if not isinstance(hits, int) or hits < 0 or hits > pair_count:
        raise PublicLayerBError("hit count out of range")
    accuracy = hits / pair_count
    winner, gate_passed = select_verdict(accuracy)
    report = {
        "contract": CONTRACT_ID,
        "slice_digest": freeze["slice_digest"],
        "code_sha": freeze["code_sha"],
        "freeze_digest": freeze["freeze_digest"],
        "a_winner": freeze["a_winner"],
        "a_freezer_digest": freeze["a_freezer_digest"],
        "a_winner_fingerprint": freeze["a_winner_fingerprint"],
        "pair_set_rule": freeze["pair_set_rule"],
        "query_rule": freeze["query_rule"],
        "b_source_table_digest": freeze["b_source_table_digest"],
        "b_source_slice_count": freeze["b_source_slice_count"],
        "b_source_pair_count": freeze["b_source_pair_count"],
        "eligible_slice_count": freeze["eligible_slice_count"],
        "pair_count": pair_count,
        "compact_table_digest": freeze["compact_table_digest"],
        "gate_accuracy": freeze["gate_accuracy"],
        "hits": hits,
        "accuracy": accuracy,
        "gate_passed": gate_passed,
        "winner": winner,
    }
    privacy = scan_privacy(report)
    if privacy:
        raise PublicLayerBError("report privacy: " + "; ".join(privacy))
    return report


def render_report_markdown(report: dict) -> str:
    verdict = "PASSED" if report["gate_passed"] else "FAILED"
    lines = [
        "# Public-layer B gate (AC-156-v1)",
        "",
        f"- contract: `{report['contract']}`",
        f"- slice digest: `{report['slice_digest']}`",
        f"- code SHA: `{report['code_sha']}`",
        f"- freeze digest: `{report['freeze_digest']}`",
        f"- A winner (frozen by #154): `{report['a_winner']}`",
        f"- A freeze digest: `{report['a_freezer_digest']}`",
        f"- pair-set rule: `{report['pair_set_rule']}`",
        f"- query rule: `{report['query_rule']}`",
        f"- B source slices (len>=2): {report['b_source_slice_count']}",
        f"- B source pairs (len>=2): {report['b_source_pair_count']}",
        f"- B source table digest: `{report['b_source_table_digest']}`",
        f"- B stride slices: {report['eligible_slice_count']}",
        f"- B stride pairs: {report['pair_count']}",
        f"- compact table digest: `{report['compact_table_digest']}`",
        f"- gate: `accuracy >= {report['gate_accuracy']}`",
        f"- hits: {report['hits']} / {report['pair_count']}",
        f"- accuracy: {report['accuracy']:.10f}",
        f"- gate: `{verdict}`",
        f"- winner: `{report['winner']}`",
        "",
        "B only scores the frozen A winner",
        "`dedicated_bge_m3` on the stride-8 subset of #153 B slices whose",
        "target length is >= 2, with the same `ctx-as-query:last64` rule",
        "as A. A verdict of `dedicated_bge_m3` is a public-layer",
        "representation result only: it does not enable `γ` or #113, the",
        "retired 95% τ keeps no official status, and #155 is not started.",
        "",
    ]
    return "\n".join(lines)


def apply_scores(artifact_dir: Path, freeze: dict, hits: int) -> dict:
    artifact_dir = Path(artifact_dir)
    written = load_freeze(artifact_dir)
    if canonical_json(written) != canonical_json(freeze):
        raise PublicLayerBError("in-memory freeze drifted from disk")
    if report_json_path(artifact_dir).exists():
        raise PublicLayerBError("scores already exist for this identity")
    report = build_report(freeze, hits)
    write_exclusive(
        report_json_path(artifact_dir),
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_exclusive(
        artifact_dir / REPORT_MD_NAME,
        render_report_markdown(report))
    return report


def current_code_sha(*, require_clean: bool) -> str:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(_ROOT), text=True).strip()
    if not require_clean:
        return sha
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=str(_ROOT), text=True)
    leftover = [
        line for line in dirty.splitlines()
        if line.strip() and not any(
            line.startswith(prefix) for prefix in _IGNORABLE_DIRTY_PREFIXES)
    ]
    if leftover:
        raise PublicLayerBError("real B run requires a clean code worktree")
    return sha