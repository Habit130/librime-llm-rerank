#!/usr/bin/env python3
"""Real Qwen tokenizer integration tests
(Habit130/squirrel#46, docs/token-attribution.md).

Explicit opt-in integration command — NOT part of the default model-free
unittest gate (the file is named `integration_*`, so `-p 'test_*.py'` does
not collect it). Requires the real Qwen tokenizer at MODEL_PATH (default
`/Users/habit/Models/Qwen/Qwen3-0.6B-Base`, override with LLM_RERANK_MODEL).

When transformers or the model files are missing, the script fails with an
explicit configuration error — it never pretends to pass.

Run:
  daemon/.venv/bin/python daemon/integration_tokenizer.py
"""

import os
import sys

MODEL_PATH = os.environ.get(
    "LLM_RERANK_MODEL", "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
)
TAIL_CHARS = 4


def _require_tokenizer():
    try:
        from transformers import AutoTokenizer
    except ImportError as error:
        sys.exit(
            "FAIL: transformers is not importable. Run inside the daemon "
            f"venv (daemon/.venv/bin/python). ({error})"
        )
    if not os.path.isdir(MODEL_PATH) or not os.path.exists(
        os.path.join(MODEL_PATH, "tokenizer.json")
    ):
        sys.exit(
            f"FAIL: model/tokenizer not found at {MODEL_PATH}. Set "
            "LLM_RERANK_MODEL to the Qwen3-0.6B-Base directory."
        )
    try:
        return AutoTokenizer.from_pretrained(MODEL_PATH)
    except Exception as error:  # noqa: BLE001 - report and exit
        sys.exit(f"FAIL: could not load tokenizer from {MODEL_PATH}: {error}")


def main():
    sys.path.insert(0, os.path.dirname(__file__))
    from server import TokenAttributionError, candidate_scoring_plan

    tokenizer = _require_tokenizer()

    failures = []

    def check(name, condition, detail):
        if not condition:
            failures.append(f"{name}: {detail}")

    def expect_fail(name, tail, candidate, reason):
        try:
            candidate_scoring_plan(tokenizer, tail, candidate)
        except TokenAttributionError:
            return
        failures.append(f"{name}: expected fail-closed ({reason}), got a plan")

    # Tail tokens never enter candidate token counts.
    ids, target_start, target_count = candidate_scoring_plan(
        tokenizer, "今天天气", "攻击")
    tail_ids = tokenizer.encode("今天天气", add_special_tokens=False)
    check("tail exclusion", target_start == len(tail_ids)
          and target_count == 1,
          f"target_start={target_start} count={target_count}")

    # Single- and multi-token candidates.
    _, ts1, c1 = candidate_scoring_plan(tokenizer, "", "攻击")
    check("single token", ts1 == 0 and c1 == 1, f"{ts1}/{c1}")
    ids2, ts2, c2 = candidate_scoring_plan(tokenizer, "", "数字123混合")
    check("multi token", ts2 == 0 and c2 == len(ids2) and c2 > 1,
          f"{ts2}/{c2}/{len(ids2)}")

    # BPE seam stable and attributable.
    ids3, ts3, c3 = candidate_scoring_plan(tokenizer, "今天", "天气")
    check("stable seam", ts3 == 1 and c3 == 1 and len(ids3) == 2,
          f"{ts3}/{c3}/{len(ids3)}")

    # Real-Qwen straddle: 今 + 天 merge into one token.
    expect_fail("straddle 今/天", "今", "天", "BPE merge across boundary")
    expect_fail("straddle 攻/击", "攻", "击", "compound token spans boundary")

    # Byte-level BPE fallback pairs (rare chars) stay whole.
    ids4, ts4, c4 = candidate_scoring_plan(tokenizer, "", "匑")
    check("byte fallback candidate side",
          ts4 == 0 and c4 == 2 and len(ids4) == 2, f"{ts4}/{c4}/{len(ids4)}")
    ids5, ts5, c5 = candidate_scoring_plan(tokenizer, "匑", "击")
    check("byte fallback tail side",
          ts5 == 2 and c5 == 1
          and tokenizer.decode(ids5[ts5:]) == "击", f"{ts5}/{c5}")

    # Suffix reconstruction holds for the real tokenizer.
    for tail, candidate in [("今天", "天气"), ("", "攻击"), ("匑", "击")]:
        ids, ts, _c = candidate_scoring_plan(tokenizer, tail, candidate)
        check(f"suffix decode {tail!r}+{candidate!r}",
              tokenizer.decode(ids[ts:]) == candidate,
              f"got {tokenizer.decode(ids[ts:])!r}")

    # Corpus-style seam smoke: every case either attributes cleanly or
    # fails closed on a genuinely non-compositional seam.
    cases = [
        ("发起", "攻击"), ("发起", "公鸡"), ("今天天气很好", "攻击"),
        ("我们今天去公园散步", "你好"), ("短", "攻击"), ("ab", "攻击"),
        ("发起。", "攻击"), ("你好，世界！", "攻击"), ("数字123混合", "测试"),
        ("很长的上文内容包含很多汉字用来测试前缀缓存的正确性", "候选"),
        ("标点，符号。测试！", "结果"), ("", "攻击"), ("abc", "攻击"),
        ("一二三四五六七八九十", "甲"), ("匑", "击"), ("公", "匑"),
    ]
    for context, candidate in cases:
        tail = context[-TAIL_CHARS:]
        try:
            ids, target_start, target_count = candidate_scoring_plan(
                tokenizer, tail, candidate)
        except TokenAttributionError:
            full = tail + candidate
            tail_ids = tokenizer.encode(tail, add_special_tokens=False)
            full_ids = tokenizer.encode(full, add_special_tokens=False)
            check(
                f"smoke {context!r}+{candidate!r}",
                tail_ids != full_ids[: len(tail_ids)],
                "fail-closed on a compositional seam",
            )
            continue
        check(
            f"smoke {context!r}+{candidate!r}",
            target_count > 0 and tokenizer.decode(ids[:target_start]) == tail,
            "attribution mismatch",
        )

    if failures:
        print(f"FAIL: {len(failures)} integration failure(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"PASS: real Qwen tokenizer integration "
          f"({MODEL_PATH}), {len(cases)} smoke cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
