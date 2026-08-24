#!/usr/bin/env python3
"""One-shot public-layer A forward (Squirrel #154 / AC-154-v2)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_layer_a import (
    CONTRACT_ID,
    DEFAULT_ARTIFACT_DIR,
    PINNED_SLICE_DIGEST,
    PublicLayerAError,
    ROUTE_IDS,
    apply_scores,
    build_freeze,
    count_eligible_a,
    eligible_a_slices,
    load_freeze,
    pair_hit,
    reconstruct_preceding,
    verify_committed_digest,
    write_freeze,
)
from public_layer_slicer import (
    ESSAY_REPO,
    ESSAY_SHA,
    LUNA_PINYIN_REPO,
    LUNA_PINYIN_SHA,
    SOURCES,
    Lexicon,
    fetch_github_sha,
    fetch_raw_file,
    read_slice_table,
)


DEFAULT_QWEN_BASE = os.environ.get(
    "LLM_RERANK_MODEL", "/Users/habit/Models/Qwen/Qwen3-0.6B-Base")
DEFAULT_QWEN3_EMB = os.environ.get(
    "AC154_QWEN3_EMBEDDING",
    "/Users/habit/Developer/librime-llm-rerank/.local-work/models/"
    "Qwen3-Embedding-0.6B")
DEFAULT_BGE = os.environ.get(
    "AC154_BGE_M3",
    "/Users/habit/Developer/librime-llm-rerank/.local-work/models/BGE-M3")
DEFAULT_EMB_PY = os.environ.get(
    "AC154_EMBEDDING_PYTHON",
    "/Users/habit/Developer/librime-llm-rerank/.local-work/venv-embeddings/"
    "bin/python")
DEFAULT_QWEN_PY = os.environ.get(
    "AC154_QWEN_PYTHON",
    "/Users/habit/Developer/librime-llm-rerank/daemon/.venv/bin/python")
_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))


class EnvironmentBlocker(PublicLayerAError):
    """A required local model or runtime is missing."""


def _cache_dir(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def load_lexicon(cache: Path) -> Lexicon:
    dict_path = fetch_raw_file(
        LUNA_PINYIN_REPO, LUNA_PINYIN_SHA, "luna_pinyin.dict.yaml",
        cache / "lexicon" / "luna_pinyin.dict.yaml")
    essay_path = fetch_raw_file(
        ESSAY_REPO, ESSAY_SHA, "essay.txt",
        cache / "lexicon" / "essay.txt")
    return Lexicon.from_files(dict_path, essay_path)


class ASourceStore:
    def __init__(self, cache: Path):
        self.roots = {}
        for source in SOURCES:
            if source.split != "A":
                continue
            self.roots[source.repo] = fetch_github_sha(
                source.repo, source.sha,
                cache / "sources" / source.repo.replace("/", "_"))
        self._texts = {}

    def preceding(self, record) -> str:
        key = (record["repo"], record["path"])
        if key not in self._texts:
            path = self.roots[record["repo"]] / record["path"]
            self._texts[key] = path.read_text(encoding="utf-8")
        return reconstruct_preceding(self._texts[key], record["start"])


_IGNORABLE_DIRTY_PREFIXES = (
    "?? eval/.cache/",
    "?? eval/public_layer/a_",
    " M eval/public_layer/a_",
    "?? eval/public_layer/A_REPORT.md",
    " M eval/public_layer/A_REPORT.md",
)


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
        raise PublicLayerAError("real A run requires a clean code worktree")
    return sha


def require_model_dir(path: str, label: str) -> str:
    if not path or not os.path.isdir(path):
        raise EnvironmentBlocker("missing_%s" % label)
    if not os.path.isfile(os.path.join(path, "config.json")):
        raise EnvironmentBlocker("missing_%s_config" % label)
    return path


def embedding_fingerprints(qwen_emb: str, bge: str) -> dict:
    from embeddings import (
        BGE_M3_EMBEDDING_ROUTE,
        QWEN3_EMBEDDING_ROUTE,
        build_embedding_identity,
        embedding_representation_id,
    )

    qwen_emb = require_model_dir(qwen_emb, "qwen3_embedding_model")
    bge = require_model_dir(bge, "bge_m3_model")
    try:
        qwen_id = build_embedding_identity(qwen_emb, QWEN3_EMBEDDING_ROUTE)
        bge_id = build_embedding_identity(bge, BGE_M3_EMBEDDING_ROUTE)
    except Exception as error:  # noqa: BLE001
        raise EnvironmentBlocker("fingerprint_unavailable: %s" % error) from error
    return {
        "dedicated_qwen3_embedding_0_6b":
            embedding_representation_id(QWEN3_EMBEDDING_ROUTE, qwen_id),
        "dedicated_bge_m3":
            embedding_representation_id(BGE_M3_EMBEDDING_ROUTE, bge_id),
    }


def l28_fingerprint(qwen_base: str) -> dict:
    from representations import (
        CandidateRepresentationSpec,
        build_model_token_identity,
        candidate_representation_id,
    )

    qwen_base = require_model_dir(qwen_base, "qwen_base_model")
    try:
        identity = build_model_token_identity(qwen_base)
    except Exception as error:  # noqa: BLE001
        raise EnvironmentBlocker("fingerprint_unavailable: %s" % error) from error
    if identity.mlxlm_version in {"", "unknown"}:
        raise EnvironmentBlocker("mlx_lm_unavailable")
    spec = CandidateRepresentationSpec(layer=28, pooling="candidate_span_mean")
    return {
        "qwen_l28_candidate_span_mean":
            candidate_representation_id(spec, identity),
    }


def collect_fingerprints(embedding_python: str, qwen_python: str,
                         qwen_base: str, qwen_emb: str, bge: str) -> dict:
    script = str(Path(__file__).resolve())
    if not os.path.isfile(embedding_python):
        raise EnvironmentBlocker("missing_embedding_runtime")
    if not os.path.isfile(qwen_python):
        raise EnvironmentBlocker("missing_qwen_runtime")
    embedding = json.loads(subprocess.check_output(
        [embedding_python, script, "--emit-fingerprint", "embedding",
         "--qwen3-embedding", qwen_emb, "--bge-m3", bge],
        text=True))
    l28 = json.loads(subprocess.check_output(
        [qwen_python, script, "--emit-fingerprint", "l28",
         "--qwen-base", qwen_base],
        text=True))
    fingerprints = {}
    fingerprints.update(embedding)
    fingerprints.update(l28)
    if set(fingerprints) != set(ROUTE_IDS):
        raise EnvironmentBlocker("fingerprint_route_set_drifted")
    return fingerprints


def _hits_dir(cache: Path) -> Path:
    path = cache / "ac154"
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


def _load_ckpt(cache: Path, route_id: str, freeze_digest: str) -> dict:
    path = _ckpt_path(cache, route_id)
    if not path.exists():
        return {"a_slice_index": 0, "hits": 0, "pairs_seen": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("freeze_digest") != freeze_digest:
        raise PublicLayerAError("checkpoint freeze digest drifted")
    if data.get("route_id") != route_id:
        raise PublicLayerAError("checkpoint route drifted")
    return data


def _save_ckpt(cache: Path, route_id: str, freeze_digest: str, state: dict) -> None:
    _write_json(_ckpt_path(cache, route_id), {
        "freeze_digest": freeze_digest,
        "route_id": route_id,
        "a_slice_index": state["a_slice_index"],
        "hits": state["hits"],
        "pairs_seen": state["pairs_seen"],
    })


def _finish_hits(cache: Path, route_id: str, freeze_digest: str,
                 hits: int, pairs: int) -> None:
    _write_json(_hits_path(cache, route_id), {
        "freeze_digest": freeze_digest,
        "route_id": route_id,
        "hits": hits,
        "pairs": pairs,
        "complete": True,
    })


def load_complete_hits(cache: Path, freeze_digest: str) -> dict:
    hits = {}
    for route_id in ROUTE_IDS:
        path = _hits_path(cache, route_id)
        if not path.exists():
            raise PublicLayerAError("hits missing for %s" % route_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("freeze_digest") != freeze_digest
                or data.get("route_id") != route_id
                or not data.get("complete")):
            raise PublicLayerAError("hits identity drifted for %s" % route_id)
        hits[route_id] = int(data["hits"])
        if int(data["pairs"]) < 1:
            raise PublicLayerAError("hits pair count missing for %s" % route_id)
    return hits


def _iter_a_records(slices, start_index=0):
    index = 0
    for record in eligible_a_slices(slices):
        if index >= start_index:
            yield index, record
        index += 1


def score_embedding_route(route_id, model_path, slices, lexicon, store,
                          cache, freeze_digest, pair_count, batch_size=32):
    import numpy as np
    import torch
    from embeddings import BGEM3EmbeddingAdapter, Qwen3EmbeddingAdapter
    from representations import candidate_conditioned_payload

    adapters = {
        "dedicated_qwen3_embedding_0_6b": Qwen3EmbeddingAdapter,
        "dedicated_bge_m3": BGEM3EmbeddingAdapter,
    }
    adapter = adapters[route_id](model_path=model_path)
    adapter.load()
    model = adapter._model
    tokenizer = adapter._tokenizer
    pooling = adapter.route.pooling
    device = torch.device(
        "mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)
    model.eval()

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

    state = _load_ckpt(cache, route_id, freeze_digest)
    started = time.time()
    last_log = started
    for index, record in _iter_a_records(slices, state["a_slice_index"]):
        competitors = lexicon.competitors(
            record["target"], record["canonical_input"])
        if not competitors:
            state["a_slice_index"] = index + 1
            continue
        preceding = store.preceding(record)
        words = [record["target"], *competitors]
        texts = []
        ok = []
        for word in words:
            try:
                texts.append(candidate_conditioned_payload(preceding, word))
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
            vecs.append(encoded[cursor])
            cursor += 1
        target_vec = vecs[0]
        if target_vec is not None:
            target = np.asarray(target_vec, dtype=np.float64)
            self_dot = float(target @ target)
            for competitor_vec in vecs[1:]:
                if competitor_vec is None:
                    continue
                other = np.asarray(competitor_vec, dtype=np.float64)
                if self_dot > float(target @ other):
                    state["hits"] += 1
        state["pairs_seen"] += len(competitors)
        state["a_slice_index"] = index + 1
        now = time.time()
        if (index + 1) % 200 == 0 or now - last_log >= 30:
            rate = state["pairs_seen"] / max(now - started, 1e-6)
            print(
                f"{route_id} slice={index + 1} pairs={state['pairs_seen']}/"
                f"{pair_count} hits={state['hits']} rate={rate:.1f}/s",
                flush=True)
            _save_ckpt(cache, route_id, freeze_digest, state)
            last_log = now
    if state["pairs_seen"] != pair_count:
        raise PublicLayerAError(
            "%s pair count drifted: %s != %s"
            % (route_id, state["pairs_seen"], pair_count))
    _save_ckpt(cache, route_id, freeze_digest, state)
    _finish_hits(cache, route_id, freeze_digest, state["hits"], pair_count)
    print(f"{route_id} done hits={state['hits']} pairs={pair_count}", flush=True)


def _clone_prefix_cache(prefix_cache, valid):
    from mlx_lm.models.cache import KVCache

    clones = []
    for item in prefix_cache:
        clone = KVCache()
        clone.keys = item.keys[..., :valid, :]
        clone.values = item.values[..., :valid, :]
        clone.offset = valid
        clones.append(clone)
    return clones


def _l28_from_tail(extractor, tail_ids, cache):
    import numpy as np
    from hidden_state import _lazy_mlx, pool_candidate_hidden_states

    mx, create_attention_mask, _unused = _lazy_mlx()
    del _unused
    _model, inner = extractor._require_model()
    del _model
    token_ids = mx.array([list(tail_ids)])
    hidden = inner.embed_tokens(token_ids)
    mask = create_attention_mask(hidden, cache[0])
    for index, layer in enumerate(inner.layers):
        hidden = layer(hidden, mask, cache[index])
        if index + 1 != 28:
            continue
        normalized = inner.norm(hidden).astype(mx.float32)
        span = np.asarray(normalized[0]).reshape(len(tail_ids), -1)
        return pool_candidate_hidden_states(
            span.tolist(), 0, len(tail_ids), "candidate_span_mean")
    raise PublicLayerAError("L28 was not reached")


def score_l28_route(model_path, slices, lexicon, store, cache, freeze_digest,
                    pair_count):
    from hidden_state import HiddenStateExtractor
    from representations import (
        CandidateRepresentationSpec,
        RepresentationError,
        candidate_tokenization_for,
    )

    class _State:
        def __init__(self, path):
            self.model_path = path
            self.model = None
            self.tokenizer = None

        def load(self):
            if self.model is not None:
                return
            import mlx.core as mx
            from mlx_lm.utils import load

            self.model, self.tokenizer = load(self.model_path)
            mx.eval(self.model.parameters())

        @property
        def loaded(self):
            return self.model is not None

    spec = CandidateRepresentationSpec(layer=28, pooling="candidate_span_mean")
    extractor = HiddenStateExtractor(_State(model_path))
    extractor._require_model()
    tokenizer = extractor._tokenizer()
    state = _load_ckpt(cache, "qwen_l28_candidate_span_mean", freeze_digest)
    started = time.time()
    last_log = started
    route_id = "qwen_l28_candidate_span_mean"
    for index, record in _iter_a_records(slices, state["a_slice_index"]):
        competitors = lexicon.competitors(
            record["target"], record["canonical_input"])
        if not competitors:
            state["a_slice_index"] = index + 1
            continue
        preceding = store.preceding(record)
        try:
            _payload, target_ids, start, count = candidate_tokenization_for(
                tokenizer, preceding, record["target"], spec=spec)
            del _payload
            prefix_ids = target_ids[:start]
            target_tail = target_ids[start:start + count]
            prefix_cache = extractor._forward_prefix(prefix_ids)
            target_vec = _l28_from_tail(
                extractor, target_tail,
                _clone_prefix_cache(prefix_cache, len(prefix_ids)))
        except (RepresentationError, PublicLayerAError, ValueError, TypeError):
            target_vec = None
            prefix_ids = None
            prefix_cache = None
        if target_vec is not None:
            for competitor in competitors:
                try:
                    _payload, ids, start, count = candidate_tokenization_for(
                        tokenizer, preceding, competitor, spec=spec)
                    del _payload
                    if prefix_ids is not None and ids[:start] == prefix_ids:
                        other = _l28_from_tail(
                            extractor, ids[start:start + count],
                            _clone_prefix_cache(prefix_cache, len(prefix_ids)))
                    else:
                        other = extractor.candidate(
                            spec, preceding, competitor)
                except (RepresentationError, PublicLayerAError, ValueError,
                        TypeError):
                    continue
                if pair_hit(target_vec, other):
                    state["hits"] += 1
        state["pairs_seen"] += len(competitors)
        state["a_slice_index"] = index + 1
        now = time.time()
        if (index + 1) % 50 == 0 or now - last_log >= 30:
            rate = state["pairs_seen"] / max(now - started, 1e-6)
            print(
                f"{route_id} slice={index + 1} pairs={state['pairs_seen']}/"
                f"{pair_count} hits={state['hits']} rate={rate:.1f}/s",
                flush=True)
            _save_ckpt(cache, route_id, freeze_digest, state)
            last_log = now
    if state["pairs_seen"] != pair_count:
        raise PublicLayerAError(
            "l28 pair count drifted: %s != %s"
            % (state["pairs_seen"], pair_count))
    _save_ckpt(cache, route_id, freeze_digest, state)
    _finish_hits(cache, route_id, freeze_digest, state["hits"], pair_count)
    print(f"{route_id} done hits={state['hits']} pairs={pair_count}", flush=True)


def _spawn(python_path, extra_args):
    script = str(Path(__file__).resolve())
    completed = subprocess.run(
        [python_path, script, *extra_args], check=False)
    if completed.returncode != 0:
        raise PublicLayerAError(
            "route worker failed: %s" % " ".join(extra_args))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path,
                        default=Path(__file__).resolve().parent / ".cache" /
                        "public_layer")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--qwen-base", default=DEFAULT_QWEN_BASE)
    parser.add_argument("--qwen3-embedding", default=DEFAULT_QWEN3_EMB)
    parser.add_argument("--bge-m3", default=DEFAULT_BGE)
    parser.add_argument("--embedding-python", default=DEFAULT_EMB_PY)
    parser.add_argument("--qwen-python", default=DEFAULT_QWEN_PY)
    parser.add_argument("--score-route", choices=ROUTE_IDS)
    parser.add_argument("--emit-fingerprint", choices=("embedding", "l28"))
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--freeze-only", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.emit_fingerprint == "embedding":
        print(json.dumps(embedding_fingerprints(
            args.qwen3_embedding, args.bge_m3), ensure_ascii=False))
        return 0
    if args.emit_fingerprint == "l28":
        print(json.dumps(l28_fingerprint(args.qwen_base), ensure_ascii=False))
        return 0
    cache = _cache_dir(args.cache)
    output = args.output
    verify_committed_digest(output)
    print("loading lexicon", flush=True)
    lexicon = load_lexicon(cache)
    slices = read_slice_table(output / "slices.tsv")
    eligible_slice_count, pair_count = count_eligible_a(slices, lexicon)
    print(f"A eligible slices={eligible_slice_count} pairs={pair_count}",
          flush=True)
    if pair_count < 1:
        raise PublicLayerAError("A pair set is empty")

    if args.score_route:
        freeze = load_freeze(output)
        if freeze["pair_count"] != pair_count:
            raise PublicLayerAError("frozen pair count drifted")
        store = ASourceStore(cache)
        if args.score_route == "qwen_l28_candidate_span_mean":
            score_l28_route(
                args.qwen_base, slices, lexicon, store, cache,
                freeze["freeze_digest"], pair_count)
        elif args.score_route == "dedicated_qwen3_embedding_0_6b":
            score_embedding_route(
                args.score_route, args.qwen3_embedding, slices, lexicon,
                store, cache, freeze["freeze_digest"], pair_count)
        else:
            score_embedding_route(
                args.score_route, args.bge_m3, slices, lexicon, store,
                cache, freeze["freeze_digest"], pair_count)
        return 0

    if args.report_only:
        freeze = load_freeze(output)
        hits = load_complete_hits(cache, freeze["freeze_digest"])
        report = apply_scores(output, freeze, hits)
        print("winner", report["winner"])
        return 0

    creating = not (output / "a_freeze.json").exists()
    fingerprints = collect_fingerprints(
        args.embedding_python, args.qwen_python,
        args.qwen_base, args.qwen3_embedding, args.bge_m3)
    freeze = build_freeze(
        slice_digest=PINNED_SLICE_DIGEST,
        code_sha=current_code_sha(require_clean=creating),
        fingerprints=fingerprints,
        pair_count=pair_count,
        eligible_slice_count=eligible_slice_count,
    )
    if creating:
        write_freeze(output, freeze)
        print("froze", freeze["freeze_digest"], flush=True)
    else:
        existing = load_freeze(output)
        if existing != freeze:
            raise PublicLayerAError("existing freeze does not match identity")
        print("reusing freeze", freeze["freeze_digest"], flush=True)
    if args.freeze_only:
        return 0

    if not os.path.isfile(args.embedding_python):
        raise EnvironmentBlocker("missing_embedding_runtime")
    if not os.path.isfile(args.qwen_python):
        raise EnvironmentBlocker("missing_qwen_runtime")

    common = [
        "--cache", str(cache),
        "--output", str(output),
        "--qwen-base", args.qwen_base,
        "--qwen3-embedding", args.qwen3_embedding,
        "--bge-m3", args.bge_m3,
    ]
    for route_id, python_path in (
            ("dedicated_qwen3_embedding_0_6b", args.embedding_python),
            ("dedicated_bge_m3", args.embedding_python),
            ("qwen_l28_candidate_span_mean", args.qwen_python),
    ):
        if _hits_path(cache, route_id).exists():
            print("reuse complete hits", route_id, flush=True)
            continue
        print("scoring", route_id, flush=True)
        _spawn(python_path, common + ["--score-route", route_id])
    hits = load_complete_hits(cache, freeze["freeze_digest"])
    report = apply_scores(output, freeze, hits)
    print("winner", report["winner"])
    for route_id in ROUTE_IDS:
        row = report["routes"][route_id]
        print(f"  {route_id} hits={row['hits']} acc={row['accuracy']:.10f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EnvironmentBlocker as error:
        print("environment blocker:", error, file=sys.stderr)
        sys.exit(3)
    except PublicLayerAError as error:
        print("ac154 error:", error, file=sys.stderr)
        sys.exit(2)
