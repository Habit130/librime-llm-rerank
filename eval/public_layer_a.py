#!/usr/bin/env python3
"""Public-layer A pairwise selection (Squirrel #154 / AC-154-v3)."""

from __future__ import annotations

import json
import os
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

from public_layer_slicer import (
    canonical_json,
    digest_manifest,
    read_slice_table,
    scan_privacy,
    sha256_bytes,
)
from representations import (
    WINDOW_CHARS,
    candidate_conditioned_payload,
    cosine,
    window_text,
    NonFiniteRepresentationError,
)


CONTRACT_ID = "AC-154-v3"
PINNED_SLICE_DIGEST = (
    "8818cc8033834db953c69c470453b98ecc418d45469d730d078d7c004d63d667"
)
PAIR_SET_RULE = "target_len>=2"
QUERY_RULE = "ctx-as-query:last64"
MIN_TARGET_LEN = 2
ROUTE_IDS = (
    "dedicated_qwen3_embedding_0_6b",
    "dedicated_bge_m3",
    "qwen_l28_candidate_span_mean",
)
TIE_TERMINAL = "无唯一 A 赢家"
FREEZE_NAME = "a_freeze.json"
REPORT_JSON_NAME = "a_report.json"
REPORT_MD_NAME = "A_REPORT.md"
COMPACT_TABLE_NAME = "a_pairs.jsonl"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "public_layer"
MAX_SCORER_RSS_BYTES = 8 * 1024 * 1024 * 1024
VOID_CONTRACTS = frozenset({"AC-154-v1", "AC-154-v2"})


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


@dataclass(frozen=True)
class CompactSlice:
    repo: str
    path: str
    start: int
    end: int
    target: str
    canonical_input: str
    preceding: str
    competitors: tuple[str, ...]

    def identity(self) -> tuple:
        return (
            self.repo, self.path, self.start, self.end,
            self.target, self.canonical_input,
        )

    def pairs(self) -> tuple[APair, ...]:
        return tuple(
            APair(
                repo=self.repo,
                path=self.path,
                start=self.start,
                end=self.end,
                target=self.target,
                canonical_input=self.canonical_input,
                competitor=competitor,
                split="A",
            )
            for competitor in self.competitors
        )

    def to_record(self) -> dict:
        return {
            "record": "slice",
            "repo": self.repo,
            "path": self.path,
            "start": self.start,
            "end": self.end,
            "target": self.target,
            "canonical_input": self.canonical_input,
            "preceding": self.preceding,
            "competitors": list(self.competitors),
        }

    @classmethod
    def from_record(cls, record: dict) -> "CompactSlice":
        competitors = tuple(record["competitors"])
        if tuple(sorted(competitors)) != competitors:
            raise PublicLayerAError("compact competitors are not sorted")
        if record["target"] in competitors:
            raise PublicLayerAError("compact competitors include the target")
        return cls(
            repo=record["repo"],
            path=record["path"],
            start=int(record["start"]),
            end=int(record["end"]),
            target=record["target"],
            canonical_input=record["canonical_input"],
            preceding=record["preceding"],
            competitors=competitors,
        )


def a_only(slices):
    return [record for record in slices if record.get("split") == "A"]


def eligible_target(record) -> bool:
    return len(record.get("target") or "") >= MIN_TARGET_LEN


def eligible_a_slices(slices):
    return [record for record in a_only(slices) if eligible_target(record)]


def iter_a_pairs(slices, lexicon):
    for record in eligible_a_slices(slices):
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


def count_eligible_a(slices, lexicon) -> tuple[int, int]:
    records = eligible_a_slices(slices)
    pairs = 0
    for record in records:
        pairs += len(lexicon.competitors(
            record["target"], record["canonical_input"]))
    return len(records), pairs


def count_a_pairs(slices, lexicon) -> int:
    return count_eligible_a(slices, lexicon)[1]


def reconstruct_preceding(text: str, start: int) -> str:
    return text[max(0, start - WINDOW_CHARS):start]


def query_text(preceding: str) -> str:
    return window_text(preceding, WINDOW_CHARS)


def candidate_text(preceding: str, word: str) -> str:
    return candidate_conditioned_payload(preceding, word)


def pair_hit(query_vec, target_vec, competitor_vec) -> bool:
    if query_vec is None or target_vec is None or competitor_vec is None:
        return False
    try:
        return cosine(query_vec, target_vec) > cosine(
            query_vec, competitor_vec)
    except (NonFiniteRepresentationError, TypeError, ValueError):
        return False


def score_pairs(pairs, preceding_for_key, encode_query, encode_candidate) -> int:
    hits = 0
    for pair in pairs:
        preceding = preceding_for_key(pair.key())
        query_vec = encode_query(query_text(preceding))
        target_vec = encode_candidate(preceding, pair.target)
        competitor_vec = encode_candidate(preceding, pair.competitor)
        if pair_hit(query_vec, target_vec, competitor_vec):
            hits += 1
    return hits


def build_compact_slices(slices, lexicon, preceding_for_record):
    rows = []
    for record in eligible_a_slices(slices):
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


def compact_pair_set(rows) -> tuple[APair, ...]:
    pairs = []
    for row in rows:
        pairs.extend(row.pairs())
    return tuple(pairs)


def compact_counts(rows) -> tuple[int, int]:
    return len(tuple(rows)), sum(len(row.competitors) for row in rows)


def compact_table_path(cache: Path) -> Path:
    return Path(cache) / "ac154" / COMPACT_TABLE_NAME


def table_header(*, slice_digest, eligible_slice_count, pair_count) -> dict:
    return {
        "record": "header",
        "contract": CONTRACT_ID,
        "slice_digest": slice_digest,
        "query_rule": QUERY_RULE,
        "pair_set_rule": PAIR_SET_RULE,
        "eligible_slice_count": eligible_slice_count,
        "pair_count": pair_count,
    }


def write_compact_table(path: Path, rows, *, slice_digest) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    slice_count, pair_count = compact_counts(rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(
            table_header(
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


def iter_compact_table(path: Path):
    header = None
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            kind = record.get("record")
            if kind == "header":
                if header is not None:
                    raise PublicLayerAError("compact table has a second header")
                if record.get("contract") != CONTRACT_ID:
                    raise PublicLayerAError("compact table contract is not v3")
                if record.get("query_rule") != QUERY_RULE:
                    raise PublicLayerAError("compact table query rule drifted")
                if record.get("pair_set_rule") != PAIR_SET_RULE:
                    raise PublicLayerAError("compact table pair rule drifted")
                if record.get("slice_digest") != PINNED_SLICE_DIGEST:
                    raise PublicLayerAError("compact table slice digest drifted")
                header = record
                continue
            if kind != "slice":
                raise PublicLayerAError("compact table record kind drifted")
            yield CompactSlice.from_record(record)
    if header is None:
        raise PublicLayerAError("compact table header is missing")


def load_compact_header(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        first = handle.readline()
    if not first.strip():
        raise PublicLayerAError("compact table is empty")
    header = json.loads(first)
    if header.get("record") != "header":
        raise PublicLayerAError("compact table header is missing")
    if header.get("contract") != CONTRACT_ID:
        raise PublicLayerAError("compact table contract is not v3")
    return header


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


def build_freeze(*, slice_digest, code_sha, fingerprints, pair_count,
                 eligible_slice_count, compact_table_digest) -> dict:
    if slice_digest != PINNED_SLICE_DIGEST:
        raise PublicLayerAError("slice digest is not the accepted #153 pin")
    if set(fingerprints) != set(ROUTE_IDS):
        raise PublicLayerAError("freeze route set drifted")
    if not isinstance(code_sha, str) or not code_sha:
        raise PublicLayerAError("code SHA is missing")
    if not isinstance(pair_count, int) or pair_count < 1:
        raise PublicLayerAError("pair count must be a positive integer")
    if not isinstance(eligible_slice_count, int) or eligible_slice_count < 1:
        raise PublicLayerAError("eligible slice count must be a positive integer")
    if not isinstance(compact_table_digest, str) or not compact_table_digest:
        raise PublicLayerAError("compact table digest is missing")
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
        "pair_set_rule": PAIR_SET_RULE,
        "query_rule": QUERY_RULE,
        "eligible_slice_count": eligible_slice_count,
        "pair_count": pair_count,
        "compact_table_digest": compact_table_digest,
        "b_pairs": 0,
        "len1_pairs_scored": 0,
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
    validate_freeze(freeze)
    write_exclusive(path, json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")
    privacy = scan_privacy(freeze)
    if privacy:
        raise PublicLayerAError("freeze privacy: " + "; ".join(privacy))
    return path


def validate_freeze(freeze: dict) -> dict:
    contract = freeze.get("contract")
    if contract in VOID_CONTRACTS:
        raise PublicLayerAError("v2 freeze unused")
    if contract != CONTRACT_ID:
        raise PublicLayerAError("freeze contract drifted")
    if freeze.get("query_rule") != QUERY_RULE:
        raise PublicLayerAError("freeze query rule drifted")
    if freeze.get("pair_set_rule") != PAIR_SET_RULE:
        raise PublicLayerAError("freeze pair rule drifted")
    if freeze.get("slice_digest") != PINNED_SLICE_DIGEST:
        raise PublicLayerAError("freeze slice digest drifted")
    return freeze


def load_freeze(artifact_dir: Path) -> dict:
    path = freeze_path(artifact_dir)
    if not path.exists():
        raise PublicLayerAError("freeze file is missing")
    return validate_freeze(json.loads(path.read_text(encoding="utf-8")))


def void_v2_artifacts(artifact_dir: Path, cache: Path) -> list[str]:
    removed = []
    freeze = freeze_path(artifact_dir)
    if freeze.exists():
        try:
            payload = json.loads(freeze.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if payload.get("contract") != CONTRACT_ID \
                or payload.get("query_rule") != QUERY_RULE:
            freeze.unlink()
            removed.append(str(freeze))
    hits_dir = Path(cache) / "ac154"
    if hits_dir.is_dir():
        for path in sorted(hits_dir.glob("*.ckpt.json")) \
                + sorted(hits_dir.glob("*.hits.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if payload.get("contract") != CONTRACT_ID \
                    or payload.get("query_rule") != QUERY_RULE:
                path.unlink()
                removed.append(str(path))
    return removed


def build_report(freeze: dict, hits_by_route: dict) -> dict:
    validate_freeze(freeze)
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
        "pair_set_rule": freeze["pair_set_rule"],
        "query_rule": freeze["query_rule"],
        "eligible_slice_count": freeze["eligible_slice_count"],
        "pair_count": pair_count,
        "compact_table_digest": freeze["compact_table_digest"],
        "b_pairs_scored": 0,
        "len1_pairs_scored": 0,
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
        "# Public-layer A winner (AC-154-v3)",
        "",
        f"- contract: `{report['contract']}`",
        f"- slice digest: `{report['slice_digest']}`",
        f"- code SHA: `{report['code_sha']}`",
        f"- freeze digest: `{report['freeze_digest']}`",
        f"- pair-set rule: `{report['pair_set_rule']}`",
        f"- query rule: `{report['query_rule']}`",
        f"- eligible A slices: {report['eligible_slice_count']}",
        f"- A pairs: {report['pair_count']}",
        f"- compact table digest: `{report['compact_table_digest']}`",
        f"- B pairs scored: {report['b_pairs_scored']}",
        f"- len=1 pairs scored: {report['len1_pairs_scored']}",
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
        "A only selects a representation on `target_len>=2` pairs with",
        "query `ctx-as-query:last64`. The public 70% pairwise gate is #156",
        "on split B with the same query and length rules. The retired",
        "v1/v2 95% gates stay demoted. B and len=1 were not scored. Live",
        "`α`/`γ` are unchanged.",
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


def scorer_rss_bytes() -> int:
    output = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True)
    return int(output.strip()) * 1024


def guard_scorer_rss(rss_bytes=None, limit=MAX_SCORER_RSS_BYTES) -> int:
    rss = scorer_rss_bytes() if rss_bytes is None else rss_bytes
    if rss > limit:
        raise PublicLayerAError(
            "scorer physical footprint exceeded 8G: %s" % rss)
    return rss


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
