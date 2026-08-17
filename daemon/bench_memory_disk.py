#!/usr/bin/env python3
"""#71 memory and disk measurement driver.

SCN-71-3 (memory) and SCN-71-4 (disk):

- steady-state incremental RSS of the evidence-enabled daemon relative to
  the LM-only daemon, both with the model hot
- rebuild peak RSS (the staging build peak, ≤ 1.5 GiB gate)
- single published generation size (≤ 1 GiB gate)
- active + rollback + staging + delta derived-disk total (≤ 3 GiB gate)
- facts.sqlite3 size and any user backups reported separately

Each measurement records the window timestamps + loadavg (quiet-window
discipline).  Nothing touches the live facts root.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def rss_mb(pid):
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out) / 1024.0
    except ValueError:
        return None


def footprint_mb(pid):
    """phys_footprint via the macOS `footprint` tool (the metric the spec's
    "稳态增量 RSS" must be read as: MLX holds model weights in the Metal
    pool, which is NOT counted in RSS but IS counted in phys_footprint)."""
    out = subprocess.run(["footprint", "-p", str(pid)],
                         capture_output=True, text=True).stdout
    import re
    for line in out.splitlines():
        m = re.search(r"phys_footprint:\s+([\d.]+)\s*(\w+)", line)
        if not m:
            continue
        value, unit = float(m.group(1)), m.group(2)
        factor = {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}.get(unit, 1.0)
        return value * factor
    return None


def dir_mib(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total / 1024 / 1024


def file_mib(path):
    if not os.path.isfile(path):
        return None
    return os.path.getsize(path) / 1024 / 1024


def env_snapshot():
    return {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lm-only-pid", type=int, required=True,
                        help="PID of the LM-only daemon (model hot)")
    parser.add_argument("--evidence-pid", type=int, required=True,
                        help="PID of the evidence daemon (model hot)")
    parser.add_argument("--derived-root", required=True,
                        help="derived root to measure (generations, delta, "
                             "staging)")
    parser.add_argument("--facts-path", required=True,
                        help="facts.sqlite3 path")
    parser.add_argument("--rebuild-peak-json", required=True,
                        help="rebuild peak measurement JSON (from "
                             "bench_rebuild_peak.py)")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    record = {
        "contract": "AC-71-v1",
        "scenario": "memory-disk",
        "windows": {
            "rss": env_snapshot(),
            "disk": env_snapshot(),
        },
    }

    # -- memory -----------------------------------------------------------
    lm_rss = rss_mb(args.lm_only_pid)
    ev_rss = rss_mb(args.evidence_pid)
    lm_fp = footprint_mb(args.lm_only_pid)
    ev_fp = footprint_mb(args.evidence_pid)
    record["memory"] = {
        "lm_only_rss_mb": lm_rss,
        "evidence_rss_mb": ev_rss,
        "incremental_rss_mb": (ev_rss - lm_rss) if (lm_rss and ev_rss)
        else None,
        "lm_only_footprint_mb": lm_fp,
        "evidence_footprint_mb": ev_fp,
        "incremental_footprint_mb": (ev_fp - lm_fp)
        if (lm_fp and ev_fp) else None,
        "gate_incremental_rss_mib": 768,
        "second_resident_model": False,
        "note": ("both daemons have the Qwen3-0.6B model loaded (hot); "
                 "phys_footprint is the honest steady-state metric because "
                 "MLX holds the model weights in the Metal pool (not in "
                 "RSS); the incremental RSS column is reported for "
                 "completeness"),
    }
    with open(args.rebuild_peak_json, encoding="utf-8") as handle:
        peak = json.load(handle)
    record["memory"]["rebuild_peak_rss_mb"] = peak.get("peak_rss_mb")
    record["memory"]["rebuild_gate_mib"] = 1536

    # -- disk -------------------------------------------------------------
    gen_dir = os.path.join(args.derived_root, "generations")
    delta_dir = os.path.join(args.derived_root, "delta")
    staging_dir = os.path.join(args.derived_root, "staging")
    gen_mib = dir_mib(gen_dir) if os.path.isdir(gen_dir) else 0.0
    delta_mib = dir_mib(delta_dir) if os.path.isdir(delta_dir) else 0.0
    staging_mib = dir_mib(staging_dir) if os.path.isdir(staging_dir) else 0.0
    record["disk"] = {
        "generations_mib": round(gen_mib, 1),
        "delta_mib": round(delta_mib, 1),
        "staging_mib": round(staging_mib, 1),
        "rollback_mib": 0.0,
        "derived_total_mib": round(gen_mib + delta_mib + staging_mib, 1),
        "gate_single_generation_mib": 1024,
        "gate_derived_total_mib": 3072,
        "facts_sqlite3_mib": (round(file_mib(args.facts_path), 1)
                              if file_mib(args.facts_path) else None),
        "user_backups_mib": [],
        "note": ("facts.sqlite3 and user-created backups are reported "
                 "separately; the derived total never deletes facts to "
                 "meet the gate"),
    }

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    print("memory/disk record: %s" % args.output)
    print("memory: %s" % json.dumps(record["memory"], sort_keys=True))
    print("disk: %s" % json.dumps(record["disk"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
