#!/usr/bin/env python3
"""Personal-layer 2x2 forward (Squirrel #155 / AC-155-v1).

One-shot driver: verifies the read-only pinned #77 prefix snapshot, extracts
the complete 2x2 keys, scores exactly the two frozen routes, and writes the
desensitized freeze/report into `eval/personal_layer/`. Private event text
never leaves the cache, the live daemon is never touched, and no public-layer
or `gamma` value enters the verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(Path(__file__).resolve().parents[1] / "daemon") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from personal_layer_2x2 import (  # noqa: E402
    CONTRACT_ID,
    DEFAULT_ARTIFACT_DIR,
    FALLBACK_PIN_SHA256,
    FALLBACK_PIN_NAME,
    HLC_MAX_INCLUSIVE,
    HLC_MIN,
    MIN_COMPLETE_KEYS,
    PRIMARY_PIN_SHA256,
    ROUTE_IDS,
    Personal2x2Error,
    apply_preflight,
    apply_scores,
    build_freeze,
    canonical_json,
    classify_keys,
    group_keys,
    key_sha256,
    load_freeze,
    load_prefix_snapshot,
    sha256_bytes,
    write_freeze,
    write_report,
)

DEFAULT_SNAPSHOT = (
    "/Users/habit/Developer/librime-llm-rerank/.local-work/ac111-prefix/"
    + FALLBACK_PIN_NAME)
DEFAULT_EMBEDDING_MODEL = (
    "/Users/habit/Developer/librime-llm-rerank/.local-work/models/"
    "Qwen3-Embedding-0.6B")
DEFAULT_EMBEDDING_PYTHON = (
    "/Users/habit/Developer/librime-llm-rerank/.local-work/"
    "venv-embeddings/bin/python")
DEFAULT_DAEMON_PYTHON = (
    "/Users/habit/Developer/librime-llm-rerank/daemon/.venv/bin/python")
DEFAULT_MLX_MODEL = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
KEYS_NAME = "keys.jsonl"


class EnvironmentBlocker(Personal2x2Error):
    """A required local model, runtime or snapshot is missing."""


def _cache_dir(cache):
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _keys_path(cache):
    return cache / KEYS_NAME


def _route_ds_path(cache, route_id):
    return cache / ("route-%s.ds.jsonl" % route_id)


def _acquire_snapshot_copy(source, cache, expected_sha):
    """Read-only worktree copy of the pinned snapshot, byte-verified.

    The pinned store is a WAL database, so the `-shm`/`-wal` sidecars are
    copied next to the main file or a read-only open cannot reach the shared
    index on the first query.
    """
    dest = cache / "prefix-snapshot.sqlite3"
    if dest.exists() and sha256_bytes(dest.read_bytes()) == expected_sha \
            and _sidecar_copy_ok(cache):
        return dest
    digest = sha256_bytes(Path(source).read_bytes())
    if digest != expected_sha:
        raise EnvironmentBlocker(
            "snapshot has %s; accepted pins: primary %s, fallback %s"
            % (digest, PRIMARY_PIN_SHA256, FALLBACK_PIN_SHA256))
    shutil.copy2(source, dest)
    _copy_sidecars(source, cache)
    os.chmod(dest, 0o400)
    if sha256_bytes(dest.read_bytes()) != expected_sha:
        raise EnvironmentBlocker("snapshot copy failed verification")
    return dest


def _copy_sidecars(source, cache):
    """Copy `-shm`/`-wal` sidecars next to the snapshot copy."""
    for suffix in ("-shm", "-wal"):
        src = Path(source).with_name(Path(source).name + suffix)
        if not src.exists():
            continue
        dest = cache / ("prefix-snapshot.sqlite3" + suffix)
        shutil.copy2(src, dest)
        os.chmod(dest, 0o400)


def _sidecar_copy_ok(cache):
    for suffix in ("-shm", "-wal"):
        src = Path(DEFAULT_SNAPSHOT).with_name(FALLBACK_PIN_NAME + suffix)
        dest = cache / ("prefix-snapshot.sqlite3" + suffix)
        if src.exists() and not dest.exists():
            return False
    return True


def _dereference_snapshot(source, cache):
    """Choose and pin the snapshot file: explicit source first, then the
    fallback pin on this machine (the primary #77 byte hash is accepted when
    a matching file is supplied)."""
    if source is not None:
        digest = sha256_bytes(Path(source).read_bytes())
        if digest in (PRIMARY_PIN_SHA256, FALLBACK_PIN_SHA256):
            return source, digest
        raise EnvironmentBlocker("supplied snapshot is not a #77 pin")
    fallback = Path(DEFAULT_SNAPSHOT)
    if not fallback.is_file():
        raise EnvironmentBlocker("missing pinned snapshot (both pins absent)")
    digest = sha256_bytes(fallback.read_bytes())
    if digest not in (PRIMARY_PIN_SHA256, FALLBACK_PIN_SHA256):
        raise EnvironmentBlocker("pinned snapshot hash drifted")
    return fallback, digest


def _write_keys(cache, rows):
    """Private key table: base/partner windows and candidates by key hash."""
    path = _keys_path(cache)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    tmp.replace(path)
    return rows


def _rows_from_complete(complete):
    rows = []
    for key, (base, partner) in sorted(complete.items()):
        rows.append({
            "key_sha256": key_sha256(key),
            "ctx1": base.window(),
            "selected": base.selected,
            "ctx2": partner.window(),
            "unselected": list(base.unselected()),
        })
    return rows


def _read_keys(cache):
    rows = []
    with _keys_path(cache).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def _load_ds(cache, route_id):
    rows = {}
    path = _route_ds_path(cache, route_id)
    if not path.exists():
        raise Personal2x2Error("route scores missing for %s" % route_id)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["key_sha256"]] = (row["d_cand"], row["d_ctx"])
    return rows


def _score_keys(keys, encode, cache):
    """Per complete key the frozen 2x2: key_d_cand = median 1-cos over the
    base's unselected real candidates, key_d_ctx = 1-cos between the same
    selected candidate in the two literally different windows.

    encode is a cached callable taking (ctx, candidate) and returning the
    L2-normalized FP32 vector of ``last64(ctx)+candidate``.
    """
    from representations import cosine

    results = []
    for row in keys:
        ctx1 = row["ctx1"]
        ctx2 = row["ctx2"]
        selected = row["selected"]
        selected_vec = encode(ctx1, selected)
        ctx_vec = encode(ctx2, selected)
        d_ctx = 1.0 - cosine(selected_vec, ctx_vec)
        distances = [
            1.0 - cosine(selected_vec, encode(ctx1, candidate))
            for candidate in row["unselected"]
        ]
        results.append((row["key_sha256"],
                        _median(distances), d_ctx))
    return results


def _median(values):
    import statistics
    return statistics.median(values)


def _score_embedding_route(keys, model_path, batch_size=32):
    """dedicated_qwen3_embedding_0_6b: last-token pooled, L2-normalized;
    document-side per AC-155 (the query instruction is never applied)."""
    import numpy as np
    import torch
    from embeddings import Qwen3EmbeddingAdapter

    adapter = Qwen3EmbeddingAdapter(model_path=model_path)
    adapter.load()
    model = adapter._model
    tokenizer = adapter._tokenizer
    device = torch.device(
        "mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)
    model.eval()
    del adapter

    cache = {}

    def encode(ctx, candidate):
        key = (ctx, candidate)
        vec = cache.get(key)
        if vec is not None:
            return vec
        from representations import candidate_conditioned_payload
        payload_text = candidate_conditioned_payload(ctx, candidate)
        with torch.no_grad():
            encoded = tokenizer([payload_text], return_tensors="pt",
                                padding=True, add_special_tokens=False)
            encoded = {key: value.to(device)
                       for key, value in encoded.items()}
            hidden = model(**encoded)
            hidden = hidden.last_hidden_state.float()
            mask = encoded["attention_mask"]
            last = mask.sum(dim=1) - 1
            last = torch.clamp(last, min=0)
            rows = hidden[torch.arange(hidden.size(0),
                                       device=hidden.device), last]
            rows = torch.nn.functional.normalize(rows, p=2, dim=1)
            vector = rows.cpu().numpy()[0]
        if not np.all(np.isfinite(vector)):
            raise EnvironmentBlocker("non-finite embedding produced")
        cache[key] = vector
        return vector

    return _score_keys(keys, encode, cache)


def _score_mlx_route(keys, model_path):
    """qwen_l28_candidate_span_mean: MLX forward through Qwen3-0.6B-Base,
    candidate-span mean-pool at layer 28 after the final RMSNorm."""
    import numpy as np
    from hidden_state import _lazy_mlx, pool_candidate_hidden_states
    from representations import (CandidateRepresentationSpec,
                                 RepresentationError,
                                 candidate_tokenization_for)

    mx, create_attention_mask, _unused = _lazy_mlx()
    del _unused

    class _State:
        def __init__(self, path):
            self.model_path = path
            self.model = None
            self.tokenizer = None

        def load(self):
            if self.model is not None:
                return
            from mlx_lm.utils import load
            self.model, self.tokenizer = load(self.model_path)
            mx.eval(self.model.parameters())

    state = _State(model_path)
    state.load()
    tokenizer = state.tokenizer
    inner = (state.model.model if hasattr(state.model, "model")
             else state.model)
    embed = getattr(inner, "embed_tokens", None)
    layers = getattr(inner, "layers", None)
    norm = getattr(inner, "norm", None)
    if embed is None or layers is None or norm is None:
        raise EnvironmentBlocker("model is not the expected Qwen3 shape")
    del state, inner
    spec = CandidateRepresentationSpec(
        layer=28, pooling="candidate_span_mean")

    def l28_payload(ctx, candidate):
        _payload, ids, start, count = candidate_tokenization_for(
            tokenizer, ctx, candidate, spec=spec)
        del _payload
        ids = list(ids)
        hidden = embed(mx.array([ids]))
        mask = create_attention_mask(hidden, None)
        states = [None] * len(layers)
        for index, layer in enumerate(layers):
            hidden = layer(hidden, mask, states[index])
            if index + 1 == 28:
                normalized = norm(hidden).astype(mx.float32)
                span = np.asarray(normalized[0]).reshape(len(ids), -1)
                return pool_candidate_hidden_states(
                    span.tolist(), 0, len(ids), "candidate_span_mean")
        raise EnvironmentBlocker("L28 was not reached")

    cache = {}

    def encode(ctx, candidate):
        vec = cache.get((ctx, candidate))
        if vec is not None:
            return vec
        try:
            vec = l28_payload(ctx, candidate)
        except (RepresentationError, ValueError, TypeError) as error:
            raise EnvironmentBlocker("L28 payload fault: %s" % error)
        if vec is None or len(vec) != 1024:
            raise EnvironmentBlocker("L28 produced no 1024-d vector")
        cache[(ctx, candidate)] = vec
        return vec

    return _score_keys(keys, encode, cache)


def _render_md(freeze, report):
    lines = [
        "# Personal-layer 2x2 candidate contribution (%s)" % CONTRACT_ID,
        "",
        "- contract: `%s`" % CONTRACT_ID,
        "- code SHA: `%s`" % freeze["code_sha"],
        "- prefix pin hash: `%s`" % PRIMARY_PIN_SHA256,
        "- snapshot SHA-256: `%s`" % freeze["snapshot_sha256"],
        "- HLC window: `[%s,%s] .. [%s,%s]`" % (
            HLC_MIN[0], HLC_MIN[1], HLC_MAX_INCLUSIVE[0],
            HLC_MAX_INCLUSIVE[1]),
        "- payload: `%s` (all four 2x2 cells; %s)" % (
            freeze["payload_rule"], freeze["embedding_instruction"]),
        "- routes: `%s`" % ", ".join(freeze["routes"]),
        "- complete keys: %d (threshold %d)" % (
            freeze["complete_key_count"], MIN_COMPLETE_KEYS),
        "- incomplete: %s" % "; ".join(
            "%s=%d" % (reason, count)
            for reason, count in freeze["incomplete_reasons"].items()),
        "- terminal: `%s`" % report["terminal"],
        "",
        "| route | median(key_d_cand) | median(key_d_ctx) | r | knife |",
        "| --- | --- | --- | --- | --- |",
    ]
    for route_id, summary in report["routes"].items():
        r = ("%.6f" % summary["r"]) if summary["r"] is not None else "-"
        d_cand = ("%.6f" % summary["median_key_d_cand"]) \
            if summary["median_key_d_cand"] is not None else "-"
        d_ctx = ("%.6f" % summary["median_key_d_ctx"]) \
            if summary["median_key_d_ctx"] is not None else "-"
        lines.append(
            "| `%s` | %s | %s | %s | %s |"
            % (route_id, d_cand, d_ctx, r, summary["label"]))
    lines.extend([
        "",
        "cross-route: **%s**" % report["cross_route"],
        "",
        "The personal 2x2 answers candidate contribution only: it does not "
        "calibrate the public gate, does not approve `gamma`, does not "
        "start #113, and public-layer B accuracy did not enter `r`.",
        "",
    ])
    return "\n".join(lines)


def _spawn(python_path, extra_args, *, cache, output):
    script = str(Path(__file__).resolve())
    completed = subprocess.run(
        [python_path, script, *extra_args,
         "--cache", str(cache), "--output", str(output)],
        check=False)
    if completed.returncode != 0:
        raise Personal2x2Error(
            "route worker failed: %s" % " ".join(extra_args))


REJECTED_REASON = "no_replayable_payload"


def _rejected_keys_path(cache):
    return cache / "rejected-keys.jsonl"


def _preflight_l28(rows, model_path):
    """Deterministic tokenization-fault preflight over every 2x2 cell.

    Runs under the daemon venv with the frozen Qwen3-0.6B-Base tokenizer:
    a cell whose payload token straddles the context/candidate boundary is
    an AC-108 representation fault that rejects the whole key (one
    unreplayable cell makes the key unreplayable; no vector is invented).
    """
    from representations import (CandidateRepresentationSpec,
                                 RepresentationError,
                                 candidate_tokenization_for)

    spec = CandidateRepresentationSpec(
        layer=28, pooling="candidate_span_mean")
    tokenizer = _load_preflight_tokenizer(model_path)
    rejected = []
    for row in rows:
        cells = [(row["ctx1"], row["selected"]),
                 (row["ctx2"], row["selected"])]
        cells.extend((row["ctx1"], candidate)
                     for candidate in row["unselected"])
        unusable = False
        for ctx, candidate in cells:
            try:
                candidate_tokenization_for(
                    tokenizer, ctx, candidate, spec=spec)
            except (RepresentationError, ValueError, TypeError):
                unusable = True
                break
        if unusable:
            rejected.append(row["key_sha256"])
    return rejected


def _load_preflight_tokenizer(model_path):
    import mlx.core as mx
    from mlx_lm.utils import load

    _model, tokenizer = load(model_path)
    mx.eval(_model.parameters())
    return tokenizer


def _read_rejected(cache):
    path = _rejected_keys_path(cache)
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(
        encoding="utf-8").splitlines() if line.strip()]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path(__file__).resolve()
                        .parent / ".cache" / "personal_layer_2x2")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--model", default=DEFAULT_MLX_MODEL)
    parser.add_argument("--embedding-model",
                        default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--embedding-python", default=DEFAULT_EMBEDDING_PYTHON)
    parser.add_argument("--daemon-python", default=DEFAULT_DAEMON_PYTHON)
    parser.add_argument("--score-route", choices=ROUTE_IDS, default=None)
    parser.add_argument("--preflight-l28", action="store_true")
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    cache = _cache_dir(args.cache)
    output = args.output

    if args.preflight_l28:
        keys = _read_keys(cache)
        if not keys:
            raise Personal2x2Error("key table is empty in %s" % cache)
        rejected = _preflight_l28(keys, args.model)
        path = _rejected_keys_path(cache)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(rejected) + ("\n" if rejected else ""),
                       encoding="utf-8")
        tmp.replace(path)
        print("l28 preflight rejected %d/%d keys"
              % (len(rejected), len(keys)), flush=True)
        return 0

    if args.score_route:
        route_id = args.score_route
        keys = _read_keys(cache)
        if not keys:
            raise Personal2x2Error("key table is empty in %s" % cache)
        print("scoring %s with %d keys" % (route_id, len(keys)), flush=True)
        started = time.time()
        if route_id == ROUTE_IDS[0]:
            results = _score_embedding_route(keys, args.embedding_model)
        elif route_id == ROUTE_IDS[1]:
            results = _score_mlx_route(keys, args.model)
        else:
            raise Personal2x2Error("unknown route: %s" % route_id)
        path = _route_ds_path(cache, route_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for key_hash, d_cand, d_ctx in results:
                handle.write(canonical_json({
                    "key_sha256": key_hash,
                    "d_cand": d_cand,
                    "d_ctx": d_ctx,
                }) + "\n")
        tmp.replace(path)
        print("route %s done in %.1fs (%d keys)" % (
            route_id, time.time() - started, len(results)), flush=True)
        return 0

    source, snapshot_sha = _dereference_snapshot(args.snapshot, cache)
    snapshot = _acquire_snapshot_copy(source, cache, snapshot_sha)
    print("snapshot pin %s" % snapshot_sha, flush=True)

    events = load_prefix_snapshot(snapshot)
    groups = group_keys(events)
    complete, reasons = classify_keys(groups)
    rows = _rows_from_complete(complete)
    creating = not (output / "prefix_2x2_freeze.json").exists()
    if creating and rows:
        if not os.path.isfile(args.daemon_python):
            raise EnvironmentBlocker("missing_mlx_runtime")
        if not os.path.isdir(args.model):
            raise EnvironmentBlocker("missing_mlx_model")
        print("l28 preflight over %d complete keys" % len(rows), flush=True)
        _spawn(args.daemon_python, ["--preflight-l28"],
               cache=cache, output=output)
        rows, rejected = apply_preflight(rows, _read_rejected(cache))
        if rejected:
            reasons = dict(reasons)
            reasons[REJECTED_REASON] = reasons.get(REJECTED_REASON, 0) \
                + rejected
            print("preflight dropped %d keys" % rejected, flush=True)
    _write_keys(cache, rows)
    code_sha = current_code_sha(require_clean=True)
    freeze = build_freeze(
        snapshot_sha256=snapshot_sha,
        code_sha=code_sha,
        complete_keys=[row["key_sha256"] for row in rows],
        complete_key_count=len(rows),
        incomplete_reasons=reasons,
    )
    if creating:
        write_freeze(output, freeze)
        print("froze %s complete=%d incomplete=%s" % (
            freeze["freeze_digest"], len(rows), reasons), flush=True)
    else:
        existing = load_freeze(output)
        if existing != freeze:
            raise Personal2x2Error(
                "existing freeze does not match the reconstituted identity")
        print("reusing freeze %s" % existing["freeze_digest"], flush=True)
    if args.freeze_only:
        return 0

    if freeze["complete_key_count"] < MIN_COMPLETE_KEYS:
        print("terminal 无结论: complete keys %d < %d" % (
            freeze["complete_key_count"], MIN_COMPLETE_KEYS), flush=True)
        per_route = {route_id: [] for route_id in ROUTE_IDS}
    else:
        per_route = {}
        for route_id in ROUTE_IDS:
            ds_path = _route_ds_path(cache, route_id)
            if not ds_path.exists():
                if args.report_only:
                    raise Personal2x2Error(
                        "route %s scores missing for report-only" % route_id)
                if route_id == ROUTE_IDS[0]:
                    if not os.path.isfile(args.embedding_python):
                        raise EnvironmentBlocker("missing_embedding_runtime")
                    if not os.path.isdir(args.embedding_model):
                        raise EnvironmentBlocker("missing_embedding_model")
                    _spawn(args.embedding_python, ["--score-route", route_id],
                           cache=cache, output=output)
                else:
                    if not os.path.isfile(args.daemon_python):
                        raise EnvironmentBlocker("missing_mlx_runtime")
                    if not os.path.isdir(args.model):
                        raise EnvironmentBlocker("missing_mlx_model")
                    _spawn(args.daemon_python, ["--score-route", route_id],
                           cache=cache, output=output)
            loaded = _load_ds(cache, route_id)
            expected = set(freeze["complete_keys"])
            if set(loaded) != expected:
                raise Personal2x2Error(
                    "route %s key set drifted: %d vs %d"
                    % (route_id, len(loaded), len(expected)))
            per_route[route_id] = [loaded[key]
                                   for key in freeze["complete_keys"]]
        print("scoring done (both routes)", flush=True)

    report = apply_scores(output, freeze, per_route)
    md_text = _render_md(freeze, report)
    write_report(output, freeze, report, md_text)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print("terminal", report["terminal"], "cross", report["cross_route"])
    return 0


def current_code_sha(*, require_clean):
    from personal_layer_2x2 import current_code_sha as _code_sha
    return _code_sha(require_clean=require_clean)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EnvironmentBlocker as error:
        print("environment blocker:", error, file=sys.stderr)
        sys.exit(3)
    except Personal2x2Error as error:
        print("ac155 error:", error, file=sys.stderr)
        sys.exit(2)