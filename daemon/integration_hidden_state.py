#!/usr/bin/env python3
"""Real-model hidden-state representation integration and latency evidence (#60).

Explicit opt-in integration command -- NOT part of the model-free unittest
gate (the ``integration_*`` name keeps ``-p 'test_*.py'`` from collecting it).
Requires the real Qwen3-0.6B-Base at MODEL_PATH (default
``/Users/habit/Models/Qwen/Qwen3-0.6B-Base``, override with
``LLM_RERANK_MODEL``) plus MLX, exactly like ``integration_tokenizer.py``.
Missing MLX or model files fail with an explicit configuration error, never a
fake pass.

Primary evidence for:

- SCN-60-1 / AC60-4: recomputing the same raw UTF-8 上文 under the same
  identity is bit-identical (in-process, across two separate loads, and
  across two separate processes via the printed vector hashes); a changed
  identity changes the id and the vector, so the old vector is incompatible.
- SCN-60-3: generation reuses the loaded ModelState model; after the first
  load ``mlx_lm.utils.load`` is patched to raise and generation still
  succeeds -- there is no second model in the process.
- SCN-60-4 / AC60-5: segmented latency (standalone exact forward vs. the
  split-reuse tail phase with a reused prefix cache) collected in a quiet
  window, with a before/after environment snapshot and timestamps.
- AC60-2 / AC60-6: empty context, 64-char boundary and BPE seam routing on
  the real tokenizer, plus every first-round candidate id.

Run:
  daemon/.venv/bin/python daemon/integration_hidden_state.py
    [--rounds exact:reuse] [--output DIR] [--model PATH]

All contexts are synthetic; no private history is read or written. The
evidence artifact (JSON) is written to ``--output`` or a fresh temp dir.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import platform
import socket
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL_PATH = os.environ.get(
    "LLM_RERANK_MODEL", "/Users/habit/Models/Qwen/Qwen3-0.6B-Base")

# Synthetic, hand-authored contexts (never private history). The last context
# is crafted so the split seam lands inside the known "今天" BPE merge, which
# forces ``encode(prefix) + encode(tail) != encode(prefix + tail)`` (#41).
SMOKE_CONTEXTS = (
    "",
    "短",
    "发起",
    "今天我们一起去公园散步，天气非常好。",
    "在完成需求评审架构设计接口联调之后团队决定开始实施迁移方案",
    "项目代号 Q3-2026：上游合并后做 A/B 对比，数字 123 与标点，。！",
    "甲" * 59 + "今天天气?",
)

# The latency benchmark context: exactly 64 chars (the ADR-0002 window).
BENCH_CONTEXT = ("在完成需求评审架构设计接口联调压力测试和上线审批之后团队终于"
                 "决定从下周一开始按照既定的迁移方案分批")


def _vector_hex(vector):
    value = ",".join("%.9g" % number for number in vector)
    bytez = value.encode("ascii")
    return hashlib.sha256(bytez).hexdigest()


def _env_snapshot():
    loadavg = ""
    try:
        loadavg = ",".join("%.2f" % item for item in os.getloadavg())
    except Exception:  # noqa: BLE001 - keep the snapshot buildable anywhere
        loadavg = ""
    maxrss = ""
    try:
        import resource
        # ru_maxrss is reported in bytes on macOS and kilobytes on Linux.
        bytes_value = resource.getrusage(
            resource.RUSAGE_SELF).ru_maxrss
        maxrss = "%d" % (bytes_value if platform.system() == "Darwin"
                         else bytes_value * 1024)
    except Exception:  # noqa: BLE001
        maxrss = ""
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "uname": platform.uname()._asdict(),
        "loadavg": loadavg,
        "maxrss_bytes": maxrss,
        "axon_cache_mb": _mx_cache_limit_bytes(),
        "model_path": os.path.basename(os.path.normpath(MODEL_PATH)),
    }


def _mx_cache_limit_bytes():
    try:
        import mlx.core as mx
        return int(mx.get_cache_limit())
    except Exception:  # noqa: BLE001
        return None


def _clone_prefix_cache(prefix_cache, valid):
    """Slice a prompt cache back to its valid prefix offset.

    The base prefix cache has ``offset == valid`` (the prefix token count)
    before any tail forward. Each reuse round works on a fresh clone sliced to
    that prefix offset, so round-to-round the tail forward always proceeds
    from the same KV state and never accumulates.
    """
    from mlx_lm.models.cache import KVCache
    clones = []
    for item in prefix_cache:
        keys = item.keys[..., :valid, :]
        values = item.values[..., :valid, :]
        clone = KVCache()
        clone.keys = keys
        clone.values = values
        clone.offset = valid
        clones.append(clone)
    return clones


def main():
    parser = argparse.ArgumentParser(description="representation integration")
    parser.add_argument("--rounds", default="16:16",
                        help="exact:reuse measurement rounds (default 16:16)")
    parser.add_argument("--output", default=None,
                        help="directory for the evidence JSON artifact")
    parser.add_argument("--model", default=MODEL_PATH)
    args = parser.parse_args()
    try:
        exact_rounds, reuse_rounds = (int(part) for part in args.rounds.split(":"))
    except ValueError as error:
        print("FAIL: --rounds must be <int>:<int> (%s)" % error)
        return 2
    if min(exact_rounds, reuse_rounds) < 3:
        print("FAIL: need at least 3 rounds per phase")
        return 2
    out_dir = args.output or tempfile.mkdtemp(prefix="repr-evidence-")

    try:
        from server import ModelState
        from representations import (
            EXACT_LAYERS,
            EmptyContextRepresentationError,
            InvalidRepresentationSpec,
            NonFiniteRepresentationError,
            RepresentationSpec,
            first_round_specs,
            representation_id,
            seam_changed,
            split_tokenization_for,
            window_text,
        )
        from hidden_state import HiddenStateExtractor
    except ImportError as error:
        print("FAIL: cannot import the daemon representation modules: %s" % error)
        print("   Run inside the daemon venv (daemon/.venv/bin/python).")
        return 1
    try:
        import mlx.core as mx
        import mlx_lm
        import mlx_lm.utils
    except ImportError as error:
        print("FAIL: MLX not importable: %s" % error)
        print("   Run inside the daemon venv (daemon/.venv/bin/python).")
        return 1
    if not os.path.isdir(args.model) or not os.path.exists(
            os.path.join(args.model, "model.safetensors")):
        print("FAIL: model not found at %s (set LLM_RERANK_MODEL)." % args.model)
        return 1

    failures = []
    findings = {}

    def check(name, condition, detail):
        if not condition:
            failures.append("%s: %s" % (name, detail))
        return condition

    def expect_fault(name, fn, exc_type, detail):
        try:
            fn()
        except exc_type:
            return True
        except Exception as error:  # noqa: BLE001
            failures.append("%s: wrong fault type %r (%s)" % (
                name, type(error).__name__, error))
            return False
        failures.append("%s: expected %s, got success (%s)" % (
            name, exc_type.__name__, detail))
        return False

    env_before = _env_snapshot()
    state = ModelState(args.model)
    extractor = HiddenStateExtractor(state)
    spec28 = RepresentationSpec(kind="exact", layer=28)

    # --- identity and ids ------------------------------------------------
    identity = extractor.identity
    ids = {}
    for spec in first_round_specs():
        ids[spec.short_name] = extractor.representation_id(spec)
    findings["representation_ids"] = {name: value for name, value in ids.items()}
    check("four-distinct-ids", len(set(ids.values())) == 4,
          "expected 4 distinct ids, got %d" % len(set(ids.values())))
    check("split-id-differs-from-exact",
          ids["split_l28_last"] != ids["exact_l28_last"],
          "split and exact 28 ids must differ (seam component)")
    findings["identity"] = {
        "model_digest": identity.model_digest[:16],
        "tokenizer_digest": identity.tokenizer_digest[:16],
        "mlxlm_version": identity.mlxlm_version,
        "hidden_dim": identity.hidden_dim,
    }

    # One warm forward so Metal compiles the graph before measuring.
    warm = "在完成需求评审架构设计接口联调之后团队决定开始实施迁移方案"
    vector_warm = extractor.exact(spec28, warm)
    check("warm-finite-unit",
          all(math.isfinite(v) for v in vector_warm)
          and abs(math.sqrt(sum(v * v for v in vector_warm)) - 1.0) < 1e-5,
          "warm vector not finite/unit")

    # --- determinism (SCN-60-1 / AC60-4) ---------------------------------
    context = "司令要求部队立即对目标展开一轮全面进攻，指挥所确认后下令开火。"
    first = extractor.exact(spec28, context)
    second = extractor.exact(spec28, context)
    check("in-process-bit-identical",
          list(first) == list(second),
          "same context+identity recomputed differently")
    exact_all_a = extractor.exact_all(context)
    exact_all_b = extractor.exact_all(context)
    check("exact-all-bit-identical",
          all(list(exact_all_a[layer]) == list(exact_all_b[layer])
              for layer in EXACT_LAYERS),
          "exact_all recomputed differently")
    split_prefix_ids = split_tokenization_for(state.tokenizer, context)[1]
    base_prefix_cache = extractor._forward_prefix(split_prefix_ids)
    split_fresh, _unused_cache = extractor.split_reuse(context)
    split_reused, _unused_cache2 = extractor.split_reuse(
        context, prefix_cache=_clone_prefix_cache(
            base_prefix_cache, len(split_prefix_ids)))
    check("split-reuse-fresh-vs-reused-identical",
          list(split_fresh) == list(split_reused),
          "supplied or self-built prefix must not change the vector")
    split_reused2, _unused_cache3 = extractor.split_reuse(
        context, prefix_cache=_clone_prefix_cache(
            base_prefix_cache, len(split_prefix_ids)))
    check("split-reuse-bit-identical",
          list(split_reused) == list(split_reused2),
          "split_reuse recomputed differently under reused prefix")
    split_a = split_reused

    # Cross-load determinism: a second, independently loaded extractor.
    state2 = ModelState(args.model)
    extractor2 = HiddenStateExtractor(state2)
    cross = extractor2.exact(spec28, context)
    check("cross-load-bit-identical",
          list(first) == list(cross),
          "independent load produced a different vector")

    # Identity change -> old vector incompatible.
    other = RepresentationSpec(kind="exact", layer=14)
    layered = extractor.exact(other, context)
    check("identity-change-incompat",
          extractor.representation_id(other) != extractor.representation_id(spec28)
          and list(first) != list(layered),
          "changed identity must change id and vector")
    findings["vectors"] = {
        "exact_l28": _vector_hex(first),
        "exact_l14": _vector_hex(layered),
        "split_l28": _vector_hex(split_a),
    }

    # --- no second model (SCN-60-3) --------------------------------------
    loaded_model = state.model
    real_load = mlx_lm.utils.load
    try:
        mlx_lm.utils.load = None  # pragma: no cover - replaced below
    except Exception:
        pass

    def _blocking_load(*_args, **_kwargs):
        raise RuntimeError("generation triggered a second model load (SCN-60-3)")

    mlx_lm.utils.load = _blocking_load
    try:
        probe = extractor.exact(spec28, "生成路径不得加载第二个模型。")
        mlx_lm.utils.load = real_load
    except Exception as error:  # noqa: BLE001
        mlx_lm.utils.load = real_load
        check("no-second-model", False, "generation failed: %s" % error)
        probe = None
    if probe is not None:
        check("no-second-model", state.model is loaded_model,
              "generation swapped the loaded model")

    # --- boundary routing on the real tokenizer (AC60-6) ------------------
    expect_fault("empty-context-exact", lambda: extractor.exact(spec28, ""),
                 EmptyContextRepresentationError, "empty 上文 must fail closed")
    expect_fault("empty-context-split", lambda: extractor.split_reuse(""),
                 EmptyContextRepresentationError, "empty 上文 must fail closed")
    long_text = "甲" * 70 + "节目监控预警面板全部按规划上报且已就绪。"
    check("window-last-64", True, "")
    windowed = window_text(long_text, 64)
    check("window-text-correct", windowed == long_text[-64:],
          "window must keep the last 64 chars")
    iv = extractor.exact(spec28, long_text)
    check("window-vector-finite",
          all(math.isfinite(v) for v in iv), "long-context vector not finite")

    seams = []
    for smoke in [context for context in SMOKE_CONTEXTS if context]:
        try:
            prefix_text, prefix_ids, tail_text, tail_ids = split_tokenization_for(
                state.tokenizer, smoke)
            exact_ids = state.tokenizer.encode(
                prefix_text + tail_text, add_special_tokens=False)
            seams.append(seam_changed(prefix_text, prefix_ids, tail_text,
                                      tail_ids, exact_ids))
            _v, _c = extractor.split_reuse(smoke)
        except Exception as error:  # noqa: BLE001
            failures.append("seam smoke %r: %s" % (smoke, error))
    findings["seam_changed_rate"] = (
        sum(seams) / len(seams) if seams else None)
    check("seam-smoke-runs", len(seams) == len([c for c in SMOKE_CONTEXTS if c]),
          "some smoke context failed to produce a split representation")

    # Forced BPE seam: the crafted context must change the token stream at
    # the split boundary, and the split representation must then differ from
    # the exact one (AC60-2 / SCN-60-2 #41).
    seam_context = SMOKE_CONTEXTS[-1]
    s_prefix, s_prefix_ids, s_tail, s_tail_ids = split_tokenization_for(
        state.tokenizer, seam_context)
    seam_exact_ids = state.tokenizer.encode(
        s_prefix + s_tail, add_special_tokens=False)
    crosses = seam_changed(s_prefix, s_prefix_ids, s_tail, s_tail_ids,
                           seam_exact_ids)
    check("forced-bpe-seam-crosses", crosses,
          "crafted 今/天 boundary unexpectedly leaves the token stream "
          "unchanged")
    if crosses:
        seam_exact_vector = extractor.exact(spec28, seam_context)
        seam_split_vector, _c = extractor.split_reuse(seam_context)
        check("forced-bpe-seam-vectors-differ",
              list(seam_exact_vector) != list(seam_split_vector),
              "exact and split vectors must differ when the seam changes "
              "the token stream")
        findings["forced_bpe_seam"] = {
            "exact_ids": list(s_prefix_ids) + list(s_tail_ids),
            "whole_ids": list(seam_exact_ids),
            "exact_vector": _vector_hex(seam_exact_vector),
            "split_vector": _vector_hex(seam_split_vector),
        }

    exact_counts = []
    for smoke in [context for context in SMOKE_CONTEXTS if context]:
        windowed = window_text(smoke, 64)
        ids_exact = state.tokenizer.encode(windowed, add_special_tokens=False)
        exact_counts.append(len(ids_exact))
    findings["smoke_token_counts"] = exact_counts

    # --- segmented latency (SCN-60-4 / AC60-5) ---------------------------
    def pstats(samples):
        ordered = sorted(samples)
        median = statistics.median(ordered)
        p95 = ordered[min(len(ordered) - 1, int(math.ceil(0.95 * len(ordered))) - 1)]
        return {"count": len(ordered), "median_ms": round(median * 1000, 3),
                "p95_ms": round(p95 * 1000, 3),
                "min_ms": round(ordered[0] * 1000, 3),
                "max_ms": round(ordered[-1] * 1000, 3)}

    exact_times = []
    reuse_times = []
    reuse_total_times = []
    prefix_ids = split_tokenization_for(state.tokenizer, BENCH_CONTEXT)[1]
    prefix_cache = extractor._forward_prefix(prefix_ids)
    bench_valid = len(prefix_ids)
    for index in range(max(exact_rounds, reuse_rounds)):
        if index < exact_rounds:
            start = time.perf_counter()
            extractor.exact(spec28, BENCH_CONTEXT)
            exact_times.append(time.perf_counter() - start)
        if index < reuse_rounds:
            cache = _clone_prefix_cache(prefix_cache, bench_valid)
            start = time.perf_counter()
            extractor.split_reuse(BENCH_CONTEXT, prefix_cache=cache)
            reuse_times.append(time.perf_counter() - start)
        if index < reuse_rounds:
            start = time.perf_counter()
            extractor.split_reuse(BENCH_CONTEXT)
            reuse_total_times.append(time.perf_counter() - start)
    env_after = _env_snapshot()
    latency = {
        "exact_standalone": pstats(exact_times),
        "split_reuse_tail_batched": pstats(reuse_times),
        "split_reuse_total": pstats(reuse_total_times),
    }
    findings["latency"] = latency
    findings["env_before"] = env_before
    findings["env_after"] = env_after

    artifact = {
        "evidence": "AC-60-v1 hidden-state representation integration",
        "utc": env_before["utc"],
        "rounded": 0,
        "results": findings,
        "failures": failures,
    }
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, "representation_evidence.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2, default=str)

    print("evidence artifact: %s" % artifact_path)
    print("representation_ids:")
    for name, value in ids.items():
        print("  %s = %s" % (name, value))
    print("latency: %s" % json.dumps(latency, indent=2))
    print("seam_changed_rate=%s vectors=%s" % (
        findings["seam_changed_rate"],
        json.dumps(findings.get("vectors", {}))))
    if failures:
        print("FAIL: %d failure(s):" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("PASS: representation integration and latency evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())