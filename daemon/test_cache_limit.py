#!/usr/bin/env python3
"""Cache-limit regression test for the MLX allocator cache (issue #31).

Integration test: requires the real model at MODEL_PATH. Run in-process:
  daemon/.venv/bin/python daemon/test_cache_limit.py

Drives score() with VARIED request shapes (random candidate counts and lengths)
for several dozen iterations. With mx.metal.set_cache_limit() set, asserts:
  - mx.get_cache_memory() stays bounded (near/under the limit, not growing)
  - mx.get_active_memory() stays roughly constant (model weights only)
  - average latency stays in budget (~50 ms)

A uniform-shape test will NOT reproduce the bug; sizes MUST vary.
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import mlx.core as mx
from server import MODEL_PATH, ModelState, CACHE_LIMIT_MB

SHORT_WORDS = [
    "攻击", "公鸡", "工具", "工作", "公共", "公司", "功能", "恭喜",
    "今天", "明天", "昨天", "今年", "月份", "日期", "时间", "时候",
]

LONG_PHRASES = [
    "我们今天一起去公园散步吧",
    "这个项目的进展非常顺利",
    "机器学习模型需要大量数据",
    "输入法候选词排序算法",
    "自然语言处理技术应用",
    "深度学习框架性能优化",
    "中文分词和词性标注",
    "语音识别准确率提升",
]

CONTEXTS = [
    "发起",
    "今天我们继续输入更多的上文内容用来验证内存是否保持平稳",
    "机器学习",
    "自然语言处理",
    "",
]

CANDIDATE_COUNTS = [3, 5, 8, 16, 32]


def make_varied_candidates(rng):
    n = rng.choice(CANDIDATE_COUNTS)
    cands = []
    for _ in range(n):
        if rng.random() < 0.5:
            cands.append(rng.choice(SHORT_WORDS))
        else:
            cands.append(rng.choice(LONG_PHRASES))
    return cands


def main():
    iterations = 40
    cache_limit_mb = CACHE_LIMIT_MB
    latency_budget_ms = 80.0

    print(f"model: {MODEL_PATH}")
    print(f"cache limit: {cache_limit_mb} MB")
    print(f"iterations: {iterations}")
    print()

    mx.set_cache_limit(cache_limit_mb * 10**6)

    state = ModelState(MODEL_PATH)
    state.load()

    rng = random.Random(42)

    latencies = []
    cache_samples = []
    active_samples = []

    for i in range(1, iterations + 1):
        context = rng.choice(CONTEXTS)
        candidates = make_varied_candidates(rng)

        t0 = time.perf_counter()
        scores = state.score(context, candidates)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

        assert len(scores) == len(candidates), (
            f"iter {i}: expected {len(candidates)} scores, got {len(scores)}"
        )

        cache_mb = mx.get_cache_memory() / 1e6
        active_mb = mx.get_active_memory() / 1e6
        cache_samples.append(cache_mb)
        active_samples.append(active_mb)

        if i % 10 == 0 or i == 1:
            print(f"  iter {i:>3}  n_cands={len(candidates):>2}  "
                  f"latency={elapsed_ms:.1f} ms  "
                  f"cache={cache_mb:.0f} MB  active={active_mb:.0f} MB")

    avg_latency = sum(latencies) / len(latencies)
    max_cache = max(cache_samples)
    early_active = sum(active_samples[:5]) / 5
    late_active = sum(active_samples[-5:]) / 5
    active_drift = abs(late_active - early_active)

    print()
    print(f"avg latency: {avg_latency:.1f} ms (budget {latency_budget_ms:.0f} ms)")
    print(f"max cache:   {max_cache:.0f} MB (limit {cache_limit_mb} MB)")
    print(f"active early: {early_active:.0f} MB, late: {late_active:.0f} MB, "
          f"drift: {active_drift:.0f} MB")
    print()

    ok = True

    if max_cache > cache_limit_mb * 1.2:
        print(f"FAIL: max cache {max_cache:.0f} MB exceeds limit "
              f"{cache_limit_mb} MB by >20%")
        ok = False

    if active_drift > 200:
        print(f"FAIL: active memory drifted {active_drift:.0f} MB "
              f"(expected roughly constant)")
        ok = False

    if avg_latency > latency_budget_ms:
        print(f"FAIL: avg latency {avg_latency:.1f} ms exceeds budget "
              f"{latency_budget_ms:.0f} ms")
        ok = False

    if ok:
        print("PASS: cache bounded, active constant, latency in budget")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
