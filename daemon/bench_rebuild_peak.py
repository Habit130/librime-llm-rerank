#!/usr/bin/env python3
"""Sample peak RSS during a 100k generation rebuild (#71 SCN-71-3)."""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "daemon"))

from seed_vectors import SeedVectorProvider  # noqa: E402
from generation import build_generation  # noqa: E402
import shutil  # noqa: E402

DERIVED = sys.argv[1] if len(sys.argv) > 1 else "/tmp/100k-bench/rebuild-peak"
FACTS = sys.argv[2] if len(sys.argv) > 2 else "/tmp/100k-bench/fixtures/freq"

shutil.rmtree(DERIVED, ignore_errors=True)
provider = SeedVectorProvider("seed-fixture-v1:1024", 20260817, 1024)

pid = os.getpid()
samples = []

def sample_rss():
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out)  # KB
    except ValueError:
        return 0

t0 = time.perf_counter()
peak = 0
while not os.path.exists(os.path.join(DERIVED, "generations")):
    # wait for staging to appear
    if time.perf_counter() - t0 > 60:
        break
    time.sleep(0.5)

def watch():
    global peak
    while True:
        rss_kb = sample_rss()
        peak = max(peak, rss_kb)
        samples.append((time.perf_counter() - t0, rss_kb))
        time.sleep(0.5)
        # stop when the published generation dir appears and stabilizes
        if os.path.isdir(os.path.join(DERIVED, "generations")) and \
                os.listdir(os.path.join(DERIVED, "generations")):
            # keep sampling a bit more for the post-build tail
            if time.perf_counter() - start_tail > 3:
                break

start_tail = time.perf_counter()
gen = build_generation(FACTS, provider, DERIVED)
build_s = time.perf_counter() - t0
# final samples after build
for _ in range(6):
    time.sleep(0.5)
    rss_kb = sample_rss()
    peak = max(peak, rss_kb)
    samples.append((time.perf_counter() - t0, rss_kb))
print(json.dumps({
    "ok": True,
    "build_seconds": round(build_s, 1),
    "peak_rss_kb": peak,
    "peak_rss_mb": round(peak / 1024, 1),
    "samples": len(samples),
}))
gen.close()
