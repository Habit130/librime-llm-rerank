#!/usr/bin/env python3
"""#71 capacity-benchmark report builder (Habit130/squirrel#71, SCN-71-6).

Assembles the versioned local report package from the measurement records.
Spec #43 "可复验报告与隐私" requires, per milestone and final acceptance:

- code commit (plugin + squirrel)
- model and tokenizer summaries and all fingerprints/parameters
- history_id, store_epoch and the HLC range
- fact-snapshot SHA-256
- random seed
- hardware and dependency versions
- sample inclusion/exclusion counts and complete-competition coverage
- all stratified metrics and confidence intervals
- performance distributions
- difference-event IDs

The report never copies raw 上文, candidate text or full traces: only
event ids, numbers, counts and hashes.  GitHub receives only the
desensitized summary, the report-package hash and the local path.
"""

import hashlib
import json
import os
import platform
import sys


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def environment_summary():
    import datetime
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_report(contract, fixture_summary, records, write_results,
                 memory_results, disk_results, code_commits,
                 model_summary, seed, extra=None):
    """Assemble the desensitized report dict.

    ``records`` maps scenario name -> record dict (freq_s1s3, freq_s2,
    hotkey_s1s3, freq_s4).  ``write_results`` is the fact-write benchmark
    record (single/multi).  ``memory_results`` the RSS measurements.
    ``disk_results`` the generation/facts sizes.  ``code_commits`` maps
    repo -> commit sha.  ``model_summary`` the model/tokenizer digest.
    """
    if not records:
        raise ValueError("records are required")
    if not contract:
        raise ValueError("contract id is required")
    report = {
        "contract": contract,
        "generated_utc": environment_summary(),
        "code_commits": code_commits,
        "model": model_summary,
        "seed": seed,
        "fixtures": fixture_summary,
        "records": records,
        "fact_write_bench": write_results,
        "memory": memory_results,
        "disk": disk_results,
    }
    if extra:
        report["extra"] = extra
    digest = hashlib.sha256(
        _canonical_json(report).encode("utf-8")).hexdigest()
    report["report_sha256"] = digest
    return report


def render_markdown(report):
    """A human-readable desensitized summary (no raw text)."""
    lines = [
        "# 100k Eligibility Baseline Report (%s)" % report["contract"],
        "",
        "- Contract: %s" % report["contract"],
        "- Report SHA-256: `%s`" % report["report_sha256"],
        "- Seed: %s" % report["seed"],
    ]
    commits = report.get("code_commits") or {}
    for repo, sha in commits.items():
        lines.append("- %s commit: `%s`" % (repo, sha))
    model = report.get("model") or {}
    if model:
        lines.append("- Model: %s" % json.dumps(model, sort_keys=True))
    fixtures = report.get("fixtures") or {}
    for kind, summary in (fixtures.get("fixtures") or {}).items():
        lines.append("- Fixture %s: %d events, %d keys, facts sha256 %s"
                     % (kind, summary.get("event_count", 0),
                        summary.get("distinct_keys", 0),
                        summary.get("facts_sha256", "")))
    lines.append("")
    lines.append("## Latency records (ms)")
    for name, record in (report.get("records") or {}).items():
        lines.append("### %s" % name)
        for scenario in ("s1_ordinary_query", "s2_first_after_commit",
                         "s3_replay"):
            if scenario in record:
                pcts = record[scenario].get("percentiles") or {}
                lines.append("- %s: n=%s p50=%.1f p95=%.1f p99=%.1f "
                             "max=%.1f timeouts=%s" % (
                                 scenario, pcts.get("n", 0),
                                 pcts.get("p50", 0), pcts.get("p95", 0),
                                 pcts.get("p99", 0), pcts.get("max", 0),
                                 record[scenario].get("timeouts", 0)))
    lines.append("")
    lines.append("## Fact-write benchmark")
    write = report.get("fact_write_bench") or {}
    single = write.get("single") or {}
    multi = write.get("multi") or {}
    if single:
        lines.append("- single: n=%s p50=%.3f p95=%.3f p99=%.3f "
                     "journal=%s synchronous=%s" % (
                         single.get("batches", 0),
                         (single.get("latency_ms") or {}).get("p50", 0),
                         (single.get("latency_ms") or {}).get("p95", 0),
                         (single.get("latency_ms") or {}).get("p99", 0),
                         single.get("journal_mode", ""),
                         single.get("synchronous", "")))
    if multi:
        lines.append("- multi: writers=%s n/writer=%s p50=%.3f p95=%.3f "
                     "p99=%.3f journal=%s synchronous=%s" % (
                         multi.get("writers", 0),
                         multi.get("batches_per_writer", 0),
                         (multi.get("parent_latency_ms") or {}).get("p50", 0),
                         (multi.get("parent_latency_ms") or {}).get("p95", 0),
                         (multi.get("parent_latency_ms") or {}).get("p99", 0),
                         multi.get("journal_mode", ""),
                         multi.get("synchronous", "")))
    lines.append("")
    lines.append("## Memory / disk")
    memory = report.get("memory") or {}
    if memory:
        lines.append("- memory: %s" % json.dumps(memory, sort_keys=True))
    disk = report.get("disk") or {}
    if disk:
        lines.append("- disk: %s" % json.dumps(disk, sort_keys=True))
    lines.append("")
    lines.append("Report SHA-256: `%s`" % report["report_sha256"])
    return "\n".join(lines)


def write_report_package(report, output_dir):
    """Write the versioned local report package (JSON + Markdown) and
    return (json_path, markdown_path)."""
    os.makedirs(output_dir, mode=0o700, exist_ok=True)
    json_path = os.path.join(output_dir, "100k-baseline-report.json")
    md_path = os.path.join(output_dir, "100k-baseline-report.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    return json_path, md_path
