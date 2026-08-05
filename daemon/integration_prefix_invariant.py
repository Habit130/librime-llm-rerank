#!/usr/bin/env python3
"""Tokenize seam invariant test (#12 decision, #20 second test seam).

Asserts: for any context + candidate, the first len(prefix_tokens) tokens of
tokenize(context + candidate) are identical to the shared prefix tokens, where
prefix = context[:-TAIL_CHARS].

Pure function test: only needs the tokenizer, no model weights.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from server import CONTEXT_WINDOW, window_context

MODEL_PATH = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
TAIL_CHARS = 4

CASES = [
    ("发起", "攻击"),
    ("发起", "公鸡"),
    ("今天天气很好", "攻击"),
    ("今天天气很好", "公鸡"),
    ("我们今天去公园散步", "你好"),
    ("短", "攻击"),
    ("ab", "攻击"),
    ("发起。", "攻击"),
    ("你好，世界！", "攻击"),
    ("数字123混合", "测试"),
    ("很长的上文内容包含很多汉字用来测试前缀缓存的正确性", "候选"),
    ("标点，符号。测试！", "结果"),
    ("", "攻击"),
    ("abc", "攻击"),
    ("一二三四五六七八九十", "甲"),
]

# Long raw contexts that exceed CONTEXT_WINDOW; each is windowed to the last
# CONTEXT_WINDOW chars before the seam invariant is checked (ADR-0002).
WINDOW_CASES = [
    ("这是一段非常非常长的上文内容用来验证窗口化之后分词接缝不变量仍然成立包括标点符号和数字123等等", "候选"),
    ("恰好六十四字" * 20, "甲"),
    ("发起" * 40, "攻击"),
    (
        "今天天气很好我们一起去公园散步看到了很多花花草草还有小鸟在唱歌非常开心"
        "今天天气很好我们一起去公园散步看到了很多花花草草还有小鸟在唱歌非常开心",
        "测试",
    ),
    ("短", "攻击"),
]


def _check_prefix_invariant(tokenizer, context, candidate):
    """Return an error string if the seam invariant is violated, else None."""
    if len(context) > TAIL_CHARS:
        prefix_text = context[:-TAIL_CHARS]
    else:
        prefix_text = ""

    prefix_tokens = (
        tokenizer.encode(prefix_text, add_special_tokens=False) if prefix_text else []
    )

    full_tokens = tokenizer.encode(context + candidate, add_special_tokens=False)
    actual_prefix = full_tokens[: len(prefix_tokens)]
    if actual_prefix != prefix_tokens:
        return (
            f"  context={context!r} candidate={candidate!r}\n"
            f"    prefix_text={prefix_text!r}\n"
            f"    prefix_tokens={prefix_tokens}\n"
            f"    full_tokens[:len]={actual_prefix}\n"
            f"    full_tokens={full_tokens}"
        )
    return None


def test_prefix_invariant(tokenizer):
    failures = []
    for context, candidate in CASES:
        err = _check_prefix_invariant(tokenizer, context, candidate)
        if err:
            failures.append(err)
    return failures


def test_windowed_invariant(tokenizer, context_window):
    failures = []
    for raw_context, candidate in WINDOW_CASES:
        context = window_context(raw_context, context_window)
        err = _check_prefix_invariant(tokenizer, context, candidate)
        if err:
            failures.append(
                f"  (windowed {len(raw_context)} -> {len(context)} chars)\n" + err
            )
    return failures


def main():
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

    print(f"Tokenizer: {MODEL_PATH}")
    print(f"TAIL_CHARS: {TAIL_CHARS}")
    print(f"CONTEXT_WINDOW: {CONTEXT_WINDOW}")
    print(f"Cases: {len(CASES)} + {len(WINDOW_CASES)} windowed")
    print()

    failures = test_prefix_invariant(tokenizer)
    if failures:
        print(f"FAIL: {len(failures)} case(s) violated the prefix invariant:")
        for f in failures:
            print(f)
        return 1
    print(f"PASS: all {len(CASES)} cases satisfy the prefix invariant")

    windowed_failures = test_windowed_invariant(tokenizer, CONTEXT_WINDOW)
    if windowed_failures:
        print(
            f"FAIL: {len(windowed_failures)} windowed case(s) violated the invariant:"
        )
        for f in windowed_failures:
            print(f)
        return 1
    print(
        f"PASS: all {len(WINDOW_CASES)} windowed cases satisfy the prefix invariant"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
