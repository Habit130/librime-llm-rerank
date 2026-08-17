#!/usr/bin/env python3
"""#71 final report-package assembly.

Collects the measurement records (latency, fact-write, memory, disk),
code/model/hardware identity, and writes the versioned report package
(JSON + Markdown) with its SHA-256, plus the desensitized GitHub summary
(spec #43 "可复验报告与隐私": GitHub only gets the desensitized summary,
the report-package hash and the local path).

Usage:
    python3 eval/assemble_100k_report.py \
        --work-root <bench root with records/> \
        --write-record <fact-write record.json> \
        --memory-record <memory-disk record.json> \
        --rebuild-peak-json <rebuild peak.json> \
        --plugin-commit <sha> --squirrel-commit <sha> \
        --output-dir <report package dir> \
        [--model-digest ...] [--tokenizer-digest ...]
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import importlib  # noqa: E402
_report_mod = importlib.import_module("100k_report")  # noqa: E402
build_report = _report_mod.build_report
render_markdown = _report_mod.render_markdown
write_report_package = _report_mod.write_report_package
sha256_file = _report_mod.sha256_file


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", required=True,
                        help="bench root (records/ contains the records)")
    parser.add_argument("--write-record", required=True)
    parser.add_argument("--memory-record", required=True)
    parser.add_argument("--plugin-commit", required=True)
    parser.add_argument("--squirrel-commit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-path", default="/Users/habit/Models/"
                        "Qwen/Qwen3-0.6B-Base")
    args = parser.parse_args()

    records_dir = os.path.join(args.work_root, "records")
    aggregate = load_json(os.path.join(records_dir, "aggregate.json"))
    records = {}
    for name, path in aggregate["records"].items():
        records[name] = load_json(path)
    fixture_summary = aggregate["fixtures"]
    write_results = load_json(args.write_record)
    memory_results = load_json(args.memory_record)

    # Model/tokenizer digest (Qwen3-0.6B-Base; hashes of the weights and
    # tokenizer files, matching the #60 identity rule).
    def dir_sha256(path, pattern=None):
        digest = hashlib.sha256()
        names = sorted(os.listdir(path)) if os.path.isdir(path) else []
        for name in names:
            full = os.path.join(path, name)
            if os.path.isfile(full):
                if pattern and not name.startswith(pattern):
                    continue
                digest.update(name.encode("utf-8"))
                digest.update(b"\0")
                with open(full, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return digest.hexdigest()

    model_summary = {
        "model_basename": os.path.basename(os.path.normpath(args.model_path)),
        "model_digest": dir_sha256(args.model_path, "model.safetensors")[:16],
        "tokenizer_digest": dir_sha256(args.model_path, "tokenizer")[:16],
        "hidden_dim": 1024,
    }

    report = build_report(
        contract="AC-71-v1",
        fixture_summary=fixture_summary,
        records=records,
        write_results=write_results,
        memory_results=memory_results,
        disk_results=memory_results.get("disk", {}),
        code_commits={
            "librime-llm-rerank": args.plugin_commit,
            "squirrel": args.squirrel_commit,
        },
        model_summary=model_summary,
        seed=20260817,
        extra={
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
    )

    json_path, md_path = write_report_package(report, args.output_dir)
    print("report JSON: %s" % json_path)
    print("report MD:   %s" % md_path)
    print("report SHA-256: %s" % report["report_sha256"])

    # The desensitized GitHub summary (no raw 上文, no candidate text).
    summary = {
        "contract": report["contract"],
        "report_sha256": report["report_sha256"],
        "report_path": os.path.abspath(args.output_dir),
        "fixtures": {
            kind: {
                "events": s.get("event_count"),
                "keys": s.get("distinct_keys"),
                "facts_sha256": s.get("facts_sha256"),
            }
            for kind, s in (fixture_summary.get("fixtures") or {}).items()
        },
        "latency_ms": {
            name: {
                scenario: (rec.get(scenario) or {}).get("percentiles")
                for scenario in ("s1_ordinary_query", "s2_first_after_commit",
                                 "s3_replay")
            }
            for name, rec in records.items()
        },
        "fact_write": {
            "single": (write_results.get("single") or {}).get("latency_ms"),
            "multi": (write_results.get("multi") or {})
                     .get("parent_latency_ms"),
            "durability_full": all(
                (write_results.get("%s_durability" % label) or {}).get("full")
                for label in ("single", "multi")),
        },
        "memory_mb": memory_results.get("memory"),
        "disk_mib": memory_results.get("disk"),
        "code_commits": report["code_commits"],
    }
    summary_path = os.path.join(args.output_dir, "github-summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    print("github summary: %s" % summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
