#!/usr/bin/env python3
"""One-shot public-layer B gate forward (Squirrel #156 / AC-156-v1)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_layer_a import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    candidate_text,
    compact_counts,
    guard_scorer_rss,
    pair_hit,
    query_text,
    verify_committed_digest,
)
from public_layer_b import (  # noqa: E402
    A_WINNER_ROUTE,
    CONTRACT_ID,
    PINNED_SLICE_DIGEST,
    QUERY_RULE,
    PublicLayerBError,
    apply_scores,
    build_b_compact_slices,
    build_freeze,
    compact_table_path,
    current_code_sha,
    iter_b_compact_table,
    iter_b_source_compact_table,
    load_a_winner_identity,
    load_b_compact_header,
    load_freeze,
    sha256_bytes,
    source_compact_table_path,
    write_b_compact_table,
    write_b_source_compact_table,
    write_freeze,
)
from public_layer_slicer import (  # noqa: E402
    ESSAY_REPO,
    ESSAY_SHA,
    LUNA_PINYIN_REPO,
    LUNA_PINYIN_SHA,
    SOURCES,
    fetch_github_sha,
    fetch_raw_file,
    read_slice_table,
)


DEFAULT_BGE = os.environ.get(
    "AC156_BGE_M3",
    "/Users/habit/Developer/librime-llm-rerank/.local-work/models/BGE-M3")
DEFAULT_EMB_PY = os.environ.get(
    "AC156_EMBEDDING_PYTHON",
    "/Users/habit/Developer/librime-llm-rerank/.local-work/venv-embeddings/"
    "bin/python")
PINNED_A_FREEZE_DIGEST = (
    "091af6f9b84925b920dced2dfb218a8079052351b8c1a2735eb9f37081250ed1"
)
_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))


class EnvironmentBlocker(PublicLayerBError):
    """A required local model or runtime is missing."""


def _cache_dir(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def load_lexicon(cache: Path):
    from public_layer_slicer import Lexicon

    dict_path = fetch_raw_file(
        LUNA_PINYIN_REPO, LUNA_PINYIN_SHA, "luna_pinyin.dict.yaml",
        cache / "lexicon" / "luna_pinyin.dict.yaml")
    essay_path = fetch_raw_file(
        ESSAY_REPO, ESSAY_SHA, "essay.txt",
        cache / "lexicon" / "essay.txt")
    return Lexicon.from_files(dict_path, essay_path)


class BSourceStore:
    """Preceding-text store over the two pinned B source repos."""

    def __init__(self, cache: Path):
        self.roots = {}
        for source in SOURCES:
            if source.split != "B":
                continue
            self.roots[source.repo] = fetch_github_sha(
                source.repo, source.sha,
                cache / "sources" / source.repo.replace("/", "_"))
        self._texts = {}

    def preceding(self, record) -> str:
        from public_layer_a import reconstruct_preceding

        key = (record["repo"], record["path"])
        if key not in self._texts:
            path = self.roots[record["repo"]] / record["path"]
            self._texts[key] = path.read_text(encoding="utf-8")
        return reconstruct_preceding(self._texts[key], record["start"])


def verify_a_identity_untouched(output: Path) -> None:
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=str(_ROOT), text=True)
    for line in dirty.splitlines():
        if not line.strip():
            continue
        if "/public_layer/a_" in line:
            raise PublicLayerBError("A artifacts changed: %s" % line.strip())
    a_freeze = json.loads(
        (Path(output) / "a_freeze.json").read_text(encoding="utf-8"))
    if a_freeze.get("freeze_digest") != PINNED_A_FREEZE_DIGEST:
        raise PublicLayerBError("A freeze digest drifted")
    a_report = json.loads(
        (Path(output) / "a_report.json").read_text(encoding="utf-8"))
    if a_report.get("b_used_to_pick") is not False:
        raise PublicLayerBError("A report claims B was used to pick")


def build_b_source_table(cache: Path, output: Path) -> tuple[str, dict]:
    lexicon = load_lexicon(cache)
    slices = read_slice_table(Path(output) / "slices.tsv")
    store = BSourceStore(cache)
    rows = build_b_compact_slices(slices, lexicon, store.preceding)
    slice_count, pair_count = compact_counts(rows)
    print(
        f"B source slices={slice_count} pairs={pair_count}", flush=True)
    path = source_compact_table_path(cache)
    digest = write_b_source_compact_table(
        path, rows, slice_digest=PINNED_SLICE_DIGEST)
    header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    del lexicon
    del store
    return digest, header


def build_b_stride_table(cache: Path, output: Path) -> tuple[str, dict, dict]:
    source = source_compact_table_path(cache)
    if not source.exists():
        source_digest, source_header = build_b_source_table(cache, output)
    else:
        source_digest = sha256_bytes(source.read_bytes())
        source_header = load_b_compact_header(source)
    kept = []
    for index, row in enumerate(iter_b_source_compact_table(source)):
        if index % 8 == 0:
            kept.append(row)
    stride_digest = write_b_compact_table(
        compact_table_path(cache), kept, slice_digest=PINNED_SLICE_DIGEST)
    stride_header = load_b_compact_header(compact_table_path(cache))
    del kept
    return stride_digest, source_header, stride_header, source_digest


def _hits_dir(cache: Path) -> Path:
    path = cache / "ac156"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ckpt_path(cache: Path, route_id: str) -> Path:
    return _hits_dir(cache) / ("%s.ckpt.json" % route_id)


def _hits_path(cache: Path, route_id: str) -> Path:
    return _hits_dir(cache) / ("%s.hits.json" % route_id)


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _load_ckpt(cache: Path, route_id: str, freeze: dict) -> dict:
    path = _ckpt_path(cache, route_id)
    empty = {
        "slice_index": 0, "hits": 0, "pairs_seen": 0, "peak_rss_bytes": 0,
    }
    if not path.exists():
        return empty
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("contract") != CONTRACT_ID
            or data.get("query_rule") != QUERY_RULE
            or data.get("freeze_digest") != freeze["freeze_digest"]
            or data.get("route_id") != route_id):
        raise PublicLayerBError("checkpoint identity drifted")
    return {
        "slice_index": int(data["slice_index"]),
        "hits": int(data["hits"]),
        "pairs_seen": int(data["pairs_seen"]),
        "peak_rss_bytes": int(data.get("peak_rss_bytes") or 0),
    }


def _save_ckpt(cache: Path, route_id: str, freeze: dict, state: dict) -> None:
    _write_json(_ckpt_path(cache, route_id), {
        "contract": CONTRACT_ID,
        "query_rule": QUERY_RULE,
        "freeze_digest": freeze["freeze_digest"],
        "route_id": route_id,
        "slice_index": state["slice_index"],
        "hits": state["hits"],
        "pairs_seen": state["pairs_seen"],
        "peak_rss_bytes": state["peak_rss_bytes"],
    })


def _finish_hits(cache: Path, route_id: str, freeze: dict,
                 hits: int, pairs: int, peak_rss_bytes: int) -> None:
    _write_json(_hits_path(cache, route_id), {
        "contract": CONTRACT_ID,
        "query_rule": QUERY_RULE,
        "freeze_digest": freeze["freeze_digest"],
        "route_id": route_id,
        "hits": hits,
        "pairs": pairs,
        "peak_rss_bytes": peak_rss_bytes,
        "complete": True,
    })


def load_b_complete_hits(cache: Path, freeze: dict) -> int:
    route_id = A_WINNER_ROUTE
    path = _hits_path(cache, route_id)
    if not path.exists():
        raise PublicLayerBError("hits missing for %s" % route_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("contract") != CONTRACT_ID
            or data.get("query_rule") != QUERY_RULE
            or data.get("freeze_digest") != freeze["freeze_digest"]
            or data.get("route_id") != route_id
            or not data.get("complete")):
        raise PublicLayerBError("hits identity drifted for %s" % route_id)
    if int(data["pairs"]) != freeze["pair_count"]:
        raise PublicLayerBError("hits pair count drifted for %s" % route_id)
    return int(data["hits"])


def require_b_compact_table(cache: Path, freeze: dict) -> Path:
    path = compact_table_path(cache)
    if not path.exists():
        raise PublicLayerBError("compact table is missing")
    digest = sha256_bytes(path.read_bytes())
    if digest != freeze["compact_table_digest"]:
        raise PublicLayerBError("compact table digest drifted")
    header = load_b_compact_header(path)
    if header["pair_count"] != freeze["pair_count"]:
        raise PublicLayerBError("compact table pair count drifted")
    if header["eligible_slice_count"] != freeze["eligible_slice_count"]:
        raise PublicLayerBError("compact table slice count drifted")
    return path


def _track_rss(state: dict) -> int:
    rss = guard_scorer_rss()
    if rss > state["peak_rss_bytes"]:
        state["peak_rss_bytes"] = rss
    return rss


def score_bge_route(model_path, table_path, cache, freeze, batch_size=32):
    import numpy as np
    import torch
    from embeddings import BGEM3EmbeddingAdapter

    adapter = BGEM3EmbeddingAdapter(model_path=model_path)
    adapter.load()
    model = adapter._model
    tokenizer = adapter._tokenizer
    pooling = adapter.route.pooling
    device = torch.device(
        "mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)
    model.eval()
    route_id = A_WINNER_ROUTE
    pair_count = freeze["pair_count"]

    def encode_texts(texts):
        vectors = [None] * len(texts)
        for offset in range(0, len(texts), batch_size):
            chunk = texts[offset:offset + batch_size]
            encoded = tokenizer(
                chunk, return_tensors="pt", padding=True,
                add_special_tokens=False)
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with torch.no_grad():
                hidden = model(**encoded)
                hidden = hidden.last_hidden_state.float()
                mask = encoded["attention_mask"]
                if pooling == "last-token":
                    last = mask.sum(dim=1) - 1
                    last = torch.clamp(last, min=0)
                    rows = hidden[torch.arange(hidden.size(0),
                                               device=hidden.device), last]
                else:
                    denom = mask.sum(dim=1).clamp(min=1).unsqueeze(-1)
                    rows = (hidden * mask.unsqueeze(-1)).sum(dim=1) / denom
                rows = torch.nn.functional.normalize(rows, p=2, dim=1)
            active = mask.sum(dim=1).cpu().tolist()
            cpu = rows.cpu().numpy()
            for index, count in enumerate(active):
                if count <= 0:
                    continue
                vectors[offset + index] = cpu[index]
        return vectors

    state = _load_ckpt(cache, route_id, freeze)
    started = time.time()
    last_log = started
    for index, row in enumerate(iter_b_compact_table(table_path)):
        if index < state["slice_index"]:
            continue
        _track_rss(state)
        competitors = row.competitors
        if not competitors:
            state["slice_index"] = index + 1
            continue
        ok = []
        texts = []
        query = query_text(row.preceding)
        try:
            texts.append(query)
            ok.append(bool(query))
        except Exception:  # noqa: BLE001
            texts.append("")
            ok.append(False)
        for word in (row.target, *competitors):
            try:
                texts.append(candidate_text(row.preceding, word))
                ok.append(True)
            except Exception:  # noqa: BLE001
                texts.append("")
                ok.append(False)
        live_texts = [text for text, flag in zip(texts, ok) if flag]
        encoded = encode_texts(live_texts) if live_texts else []
        cursor = 0
        vecs = []
        for flag in ok:
            if not flag:
                vecs.append(None)
                continue
            vec = encoded[cursor]
            cursor += 1
            if vec is not None and not np.all(np.isfinite(vec)):
                vec = None
            vecs.append(vec)
        query_vec = vecs[0]
        target_vec = vecs[1]
        for competitor_vec in vecs[2:]:
            if pair_hit(query_vec, target_vec, competitor_vec):
                state["hits"] += 1
        state["pairs_seen"] += len(competitors)
        state["slice_index"] = index + 1
        now = time.time()
        if (index + 1) % 200 == 0 or now - last_log >= 30:
            rate = state["pairs_seen"] / max(now - started, 1e-6)
            print(
                f"{route_id} slice={index + 1} pairs={state['pairs_seen']}/"
                f"{pair_count} hits={state['hits']} "
                f"rss={state['peak_rss_bytes']} rate={rate:.1f}/s",
                flush=True)
            _save_ckpt(cache, route_id, freeze, state)
            last_log = now
    if state["pairs_seen"] != pair_count:
        raise PublicLayerBError(
            "%s pair count drifted: %s != %s"
            % (route_id, state["pairs_seen"], pair_count))
    _track_rss(state)
    _save_ckpt(cache, route_id, freeze, state)
    _finish_hits(cache, route_id, freeze, state["hits"], pair_count,
                 state["peak_rss_bytes"])
    print(
        f"{route_id} done hits={state['hits']} pairs={pair_count} "
        f"peak_rss={state['peak_rss_bytes']}",
        flush=True)


def _spawn(python_path, extra_args):
    script = str(Path(__file__).resolve())
    completed = subprocess.run(
        [python_path, script, *extra_args], check=False)
    if completed.returncode != 0:
        raise PublicLayerBError(
            "route worker failed: %s" % " ".join(extra_args))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path,
                        default=Path(__file__).resolve().parent / ".cache" /
                        "public_layer")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--bge-m3", default=DEFAULT_BGE)
    parser.add_argument("--embedding-python", default=DEFAULT_EMB_PY)
    parser.add_argument("--score-bge", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--build-table", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    cache = _cache_dir(args.cache)
    output = args.output
    verify_committed_digest(output)
    verify_a_identity_untouched(output)

    if args.build_table:
        stride_digest, source_header, stride_header, source_digest = \
            build_b_stride_table(cache, output)
        print(
            f"B stride table slices={stride_header['eligible_slice_count']} "
            f"pairs={stride_header['pair_count']} "
            f"source_slices={source_header['eligible_slice_count']} "
            f"source_pairs={source_header['pair_count']} "
            f"stride_digest={stride_digest} "
            f"source_digest={source_digest}",
            flush=True)
        return 0

    table = compact_table_path(cache)
    if not table.exists():
        print("building B stride compact table", flush=True)
        _spawn(sys.executable, [
            "--cache", str(cache),
            "--output", str(output),
            "--build-table",
        ])

    if args.score_bge:
        freeze = load_freeze(output)
        table_path = require_b_compact_table(cache, freeze)
        guard_scorer_rss()
        score_bge_route(args.bge_m3, table_path, cache, freeze)
        return 0

    header = load_b_compact_header(table)
    source = source_compact_table_path(cache)
    source_digest = sha256_bytes(source.read_bytes())
    source_header = load_b_compact_header(source)
    identity = load_a_winner_identity(output)
    creating = not (Path(output) / "b_freeze.json").exists()
    freeze = build_freeze(
        slice_digest=PINNED_SLICE_DIGEST,
        code_sha=current_code_sha(require_clean=creating),
        a_freezer_digest=identity.freeze_digest,
        a_winner_fingerprint=identity.fingerprint,
        b_source_table_digest=source_digest,
        b_source_slice_count=source_header["eligible_slice_count"],
        b_source_pair_count=source_header["pair_count"],
        compact_table_digest=sha256_bytes(table.read_bytes()),
        eligible_slice_count=header["eligible_slice_count"],
        pair_count=header["pair_count"],
    )
    if creating:
        write_freeze(output, freeze)
        print("froze", freeze["freeze_digest"], flush=True)
    else:
        existing = load_freeze(output)
        if existing != freeze:
            raise PublicLayerBError("existing freeze does not match identity")
        print("reusing freeze", freeze["freeze_digest"], flush=True)
    if args.freeze_only:
        return 0

    if args.report_only:
        hits = load_b_complete_hits(cache, freeze)
        report = apply_scores(output, freeze, hits)
        print("verdict", report["winner"])
        print("gate", "PASSED" if report["gate_passed"] else "FAILED")
        return 0

    if not os.path.isfile(args.embedding_python):
        raise EnvironmentBlocker("missing_embedding_runtime")
    if not os.path.isdir(args.bge_m3):
        raise EnvironmentBlocker("missing_bge_m3_model")

    if not _hits_path(cache, A_WINNER_ROUTE).exists():
        print("scoring", A_WINNER_ROUTE, flush=True)
        _spawn(args.embedding_python, [
            "--cache", str(cache),
            "--output", str(output),
            "--bge-m3", args.bge_m3,
            "--score-bge",
        ])
    else:
        print("reuse complete hits", A_WINNER_ROUTE, flush=True)
    hits = load_b_complete_hits(cache, freeze)
    report = apply_scores(output, freeze, hits)
    print("verdict", report["winner"])
    peak = json.loads(
        _hits_path(cache, A_WINNER_ROUTE).read_text(encoding="utf-8")
    ).get("peak_rss_bytes")
    print(
        f"  {A_WINNER_ROUTE} hits={report['hits']} "
        f"acc={report['accuracy']:.10f} peak_rss={peak}")
    print("gate", "PASSED" if report["gate_passed"] else "FAILED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EnvironmentBlocker as error:
        print("environment blocker:", error, file=sys.stderr)
        sys.exit(3)
    except PublicLayerBError as error:
        print("ac156 error:", error, file=sys.stderr)
        sys.exit(2)