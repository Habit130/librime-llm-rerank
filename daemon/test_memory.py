#!/usr/bin/env python3
"""Memory-flat regression test for the daemon (ADR-0002, issue #29).

Sends a sequence of GROWING-context requests to the live daemon and samples
`phys_footprint_peak`. With the windowed, stateless fix the peak must stay
FLAT (the windowed context never exceeds CONTEXT_WINDOW chars, so the Metal
pool high-water mark is the single-request peak, reached early). Before the
fix the peak climbed monotonically to many GB.

Needs a running daemon + loaded model. Run against the live socket:
  daemon/.venv/bin/python daemon/test_memory.py
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

from server import SOCKET_PATH

CANDIDATES = [
    "攻击", "公鸡", "工具", "工作", "公共", "公司", "功能", "恭喜",
    "宫殿", "供给", "巩固", "贡献", "共同", "沟通", "构成", "购买",
    "足够", "足球", "组织", "最初", "尊重", "遵守", "作品", "作用",
    "今天", "明天", "昨天", "今年", "月份", "日期", "时间", "时候",
]

# Chunk appended each iteration so the raw context grows far past the window.
GROW_CHUNK = "今天我们继续输入更多的上文内容用来验证内存是否保持平稳不随会话长度增长"


def find_daemon_pid():
    out = subprocess.run(
        ["pgrep", "-f", "server.py --serve"],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    return int(out[0]) if out else None


def peak_mb(pid):
    out = subprocess.run(
        ["footprint", "-p", str(pid)], capture_output=True, text=True
    ).stdout
    m = re.search(r"phys_footprint_peak:\s+([\d.]+)\s*(\w+)", out)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2).upper()
    factor = {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}.get(unit, 1.0)
    return val * factor


def send(sock_path, req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    s.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default=SOCKET_PATH)
    ap.add_argument("--iterations", type=int, default=60)
    ap.add_argument("--candidates", type=int, default=32)
    ap.add_argument("--tolerance-mb", type=float, default=500.0)
    ap.add_argument("--ceiling-mb", type=float, default=3072.0)
    args = ap.parse_args()

    pid = find_daemon_pid()
    if pid is None:
        print("FAIL: no running daemon found (pgrep 'server.py --serve')")
        return 1

    cands = CANDIDATES[: args.candidates]
    sample_at = {5, 15, 30, 45, args.iterations}
    samples = []
    context = "发起"

    print(f"daemon pid={pid} socket={args.socket}")
    print(f"iterations={args.iterations} candidates/batch={len(cands)}")
    print()

    for i in range(1, args.iterations + 1):
        context = context + GROW_CHUNK  # raw context grows unboundedly
        resp = send(args.socket, {"context": context, "candidates": cands})
        if "scores" not in resp or len(resp["scores"]) != len(cands):
            print(f"FAIL: bad response at iter {i}: {resp}")
            return 1
        if i in sample_at:
            peak = peak_mb(pid)
            samples.append((i, len(context), peak))
            print(f"  iter {i:>3}  raw_context={len(context):>4} chars  "
                  f"phys_footprint_peak={peak:.0f} MB")

    early = samples[0][2]
    late = samples[-1][2]
    growth = late - early

    print()
    print(f"peak early (iter {samples[0][0]}): {early:.0f} MB")
    print(f"peak late  (iter {samples[-1][0]}): {late:.0f} MB")
    print(f"growth: {growth:.0f} MB  (tolerance {args.tolerance_mb:.0f} MB, "
          f"ceiling {args.ceiling_mb:.0f} MB)")
    print()

    if growth > args.tolerance_mb:
        print(f"FAIL: footprint grew {growth:.0f} MB across the session "
              f"(> {args.tolerance_mb:.0f} MB tolerance) — not flat")
        return 1
    if late > args.ceiling_mb:
        print(f"FAIL: late peak {late:.0f} MB exceeds ceiling "
              f"{args.ceiling_mb:.0f} MB")
        return 1

    print("PASS: phys_footprint_peak stayed flat across growing context")
    return 0


if __name__ == "__main__":
    sys.exit(main())
