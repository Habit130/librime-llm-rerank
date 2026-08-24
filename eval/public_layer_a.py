#!/usr/bin/env python3
"""Public-layer A pairwise selection (Squirrel #154 / AC-154-v1)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_layer_slicer import (
    PRECEDING_LIMIT,
    canonical_json,
    digest_manifest,
    read_slice_table,
    scan_privacy,
    sha256_bytes,
)
from representations import NonFiniteRepresentationError, cosine


CONTRACT_ID = "AC-154-v1"
PINNED_SLICE_DIGEST = (
    "8818cc8033834db953c69c470453b98ecc418d45469d730d078d7c004d63d667"
)
ROUTE_IDS = (
    "dedicated_qwen3_embedding_0_6b",
    "dedicated_bge_m3",
    "qwen_l28_candidate_span_mean",
)
TIE_TERMINAL = "无唯一 A 赢家"
FREEZE_NAME = "a_freeze.json"
REPORT_JSON_NAME = "a_report.json"
REPORT_MD_NAME = "A_REPORT.md"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "public_layer"


class PublicLayerAError(Exception):
    """A contract fault in A pairwise selection."""


@dataclass(frozen=True)
class APair:
    repo: str
    path: str
    start: int
    end: int
    target: str
    canonical_input: str
    competitor: str
    split: str = "A"

    def key(self) -> str:
        return "\t".join((
            self.repo, self.path, str(self.start), str(self.end),
            self.target, self.canonical_input, self.competitor,
        ))


def a_only(slices):
    return [record for record in slices if record.get("split") == "A"]


def iter_a_pairs(slices, lexicon):
    for record in a_only(slices):
        competitors = lexicon.competitors(
            record["target"], record["canonical_input"])
        for competitor in competitors:
            yield APair(
                repo=record["repo"],
                path=record["path"],
                start=int(record["start"]),
                end=int(record["end"]),
                target=record["target"],
                canonical_input=record["canonical_input"],
                competitor=competitor,
                split="A",
            )


def expand_a_pairs(slices, lexicon) -> tuple[APair, ...]:
    return tuple(iter_a_pairs(slices, lexicon))


def count_a_pairs(slices, lexicon) -> int:
    total = 0
    for record in a_only(slices):
        total += len(lexicon.competitors(
            record["target"], record["canonical_input"]))
    return total


def reconstruct_preceding(text: str, start: int) -> str:
    return text[max(0, start - PRECEDING_LIMIT):start]


def pair_hit(target_vec, competitor_vec) -> bool:
    if target_vec is None or competitor_vec is None:
        return False
    try:
        return cosine(target_vec, target_vec) > cosine(
            target_vec, competitor_vec)
    except (NonFiniteRepresentationError, TypeError, ValueError):
        return False


def score_pairs(pairs, preceding_for_key, encode_fn) -> int:
    hits = 0
    for pair in pairs:
        preceding = preceding_for_key(pair.key())
        target_vec = encode_fn(preceding, pair.target)
        competitor_vec = encode_fn(preceding, pair.competitor)
        if pair_hit(target_vec, competitor_vec):
            hits += 1
    return hits


def select_winner(hits_by_route) -> str:
    if set(hits_by_route) != set(ROUTE_IDS):
        raise PublicLayerAError("winner input route set drifted")
    counts = [hits_by_route[route_id] for route_id in ROUTE_IDS]
    best = max(counts)
    winners = [route_id for route_id in ROUTE_IDS
               if hits_by_route[route_id] == best]
    if len(winners) != 1:
        return TIE_TERMINAL
    return winners[0]


def build_freeze(*, slice_digest, code_sha, fingerprints, pair_count) -> dict:
    if slice_digest != PINNED_SLICE_DIGEST:
        raise PublicLayerAError("slice digest is not the accepted #153 pin")
    if set(fingerprints) != set(ROUTE_IDS):
        raise PublicLayerAError("freeze route set drifted")
    if not isinstance(code_sha, str) or not code_sha:
        raise PublicLayerAError("code SHA is missing")
    if not isinstance(pair_count, int) or pair_count < 1:
        raise PublicLayerAError("pair count must be a positive integer")
    routes = {}
    for route_id in ROUTE_IDS:
        fingerprint = fingerprints[route_id]
        if not isinstance(fingerprint, str) or not fingerprint:
            raise PublicLayerAError("fingerprint missing for %s" % route_id)
        routes[route_id] = {"fingerprint": fingerprint}
    freeze = {
        "contract": CONTRACT_ID,
        "slice_digest": slice_digest,
        "code_sha": code_sha,
        "pair_count": pair_count,
        "b_pairs": 0,
        "routes": routes,
    }
    freeze["freeze_digest"] = sha256_bytes(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_digest"}).encode("utf-8"))
    return freeze


def freeze_path(artifact_dir: Path) -> Path:
    return Path(artifact_dir) / FREEZE_NAME


def report_json_path(artifact_dir: Path) -> Path:
    return Path(artifact_dir) / REPORT_JSON_NAME


def write_exclusive(path: Path, content: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as error:
        raise PublicLayerAError("artifact already exists: %s" % path) from error


def write_freeze(artifact_dir: Path, freeze: dict) -> Path:
    path = freeze_path(artifact_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if report_json_path(artifact_dir).exists():
        raise PublicLayerAError("cannot rewrite freeze after scores exist")
    write_exclusive(path, json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")
    privacy = scan_privacy(freeze)
    if privacy:
        raise PublicLayerAError("freeze privacy: " + "; ".join(privacy))
    return path


def load_freeze(artifact_dir: Path) -> dict:
    path = freeze_path(artifact_dir)
    if not path.exists():
        raise PublicLayerAError("freeze file is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def build_report(freeze: dict, hits_by_route: dict) -> dict:
    pair_count = freeze["pair_count"]
    routes = {}
    for route_id in ROUTE_IDS:
        hits = hits_by_route[route_id]
        if not isinstance(hits, int) or hits < 0 or hits > pair_count:
            raise PublicLayerAError("hit count out of range for %s" % route_id)
        routes[route_id] = {
            "fingerprint": freeze["routes"][route_id]["fingerprint"],
            "pairs": pair_count,
            "hits": hits,
            "accuracy": hits / pair_count,
        }
    report = {
        "contract": CONTRACT_ID,
        "slice_digest": freeze["slice_digest"],
        "code_sha": freeze["code_sha"],
        "freeze_digest": freeze["freeze_digest"],
        "pair_count": pair_count,
        "b_pairs_scored": 0,
        "b_used_to_pick": False,
        "routes": routes,
        "winner": select_winner(hits_by_route),
    }
    privacy = scan_privacy(report)
    if privacy:
        raise PublicLayerAError("report privacy: " + "; ".join(privacy))
    return report


def render_report_markdown(report: dict) -> str:
    lines = [
        "# Public-layer A winner (AC-154-v1)",
        "",
        f"- contract: `{report['contract']}`",
        f"- slice digest: `{report['slice_digest']}`",
        f"- code SHA: `{report['code_sha']}`",
        f"- freeze digest: `{report['freeze_digest']}`",
        f"- A pairs: {report['pair_count']}",
        f"- B pairs scored: {report['b_pairs_scored']}",
        f"- B used to pick: {str(report['b_used_to_pick']).lower()}",
        f"- winner: `{report['winner']}`",
        "",
        "| Route | Pairs | Hits | Accuracy |",
        "| --- | ---: | ---: | ---: |",
    ]
    for route_id in ROUTE_IDS:
        row = report["routes"][route_id]
        lines.append(
            f"| `{route_id}` | {row['pairs']} | {row['hits']} | "
            f"{row['accuracy']:.10f} |"
        )
    lines.extend([
        "",
        "Fingerprints:",
        "",
    ])
    for route_id in ROUTE_IDS:
        lines.append(
            f"- `{route_id}`: `{report['routes'][route_id]['fingerprint']}`"
        )
    lines.extend([
        "",
        "A only selects a representation. The public 70% pairwise gate is",
        "#156 on split B. The retired v1/v2 95% gates stay demoted.",
        "B was not scored. Live `α`/`γ` are unchanged.",
        "",
    ])
    return "\n".join(lines)


def apply_scores(artifact_dir: Path, freeze: dict, hits_by_route: dict) -> dict:
    artifact_dir = Path(artifact_dir)
    written = load_freeze(artifact_dir)
    if canonical_json(written) != canonical_json(freeze):
        raise PublicLayerAError("in-memory freeze drifted from disk")
    if report_json_path(artifact_dir).exists():
        raise PublicLayerAError("scores already exist for this identity")
    report = build_report(freeze, hits_by_route)
    write_exclusive(
        report_json_path(artifact_dir),
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_exclusive(
        artifact_dir / REPORT_MD_NAME,
        render_report_markdown(report))
    return report


def verify_committed_digest(artifact_dir: Path = DEFAULT_ARTIFACT_DIR) -> str:
    manifest = json.loads(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    slices = read_slice_table(artifact_dir / "slices.tsv")
    payload = dict(manifest)
    payload["slices"] = slices
    digest = digest_manifest(payload)
    if digest != PINNED_SLICE_DIGEST or manifest.get("digest") != digest:
        raise PublicLayerAError("committed #153 digest drifted")
    return digest
