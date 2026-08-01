#!/usr/bin/env python3
"""Context window unit test (ADR-0002).

Asserts the context fed to scoring is truncated to its last N characters.
Pure function test: no model, no tokenizer needed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from server import window_context


def main():
    failures = []

    long_ctx = "abcdefghijklmnopqrstuvwxyz"  # 26 chars
    got = window_context(long_ctx, 8)
    if got != "stuvwxyz":
        failures.append(f"N=8 on 26 chars: expected 'stuvwxyz', got {got!r}")

    if window_context(long_ctx, 64) != long_ctx:
        failures.append("N larger than context should be the identity")

    if window_context("", 64) != "":
        failures.append("empty context should stay empty")

    if window_context("abc", 64) != "abc":
        failures.append("short context should be unchanged")

    cjk = "很长的上文内容包含很多汉字用来测试前缀缓存的正确性"
    if window_context(cjk, 4) != cjk[-4:]:
        failures.append("CJK window should be the last 4 chars")
    if window_context(cjk, 64) != cjk:
        failures.append("CJK context shorter than N should be unchanged")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  " + f)
        return 1

    print("PASS: window_context truncates to the last N characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
