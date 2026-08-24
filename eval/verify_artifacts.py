#!/usr/bin/env python3
"""Read-only verifier for the committed calibration artifacts
(Habit130/squirrel#46, PR #12 round 2).

Checks, all from committed files (no model, no console run):

1. **Fixture**: re-derives the 120/402 fixture from corpus + dict and
   compares with fixture.json (corpus checksum, case sets, word-manifest
   checksum).
2. **Manifest checksum**: recomputes `manifest_sha256` as
   `sha256(canonical_json(manifest minus manifest_sha256))` with the same
   canonical rule calibrate.py uses, and compares with the committed value.
3. **Results <-> manifest consistency**: every run's alpha/policy/lm_term/
   metrics/schema-config identity match.
4. **Rank-derived summaries**: word/sentence metrics and harmful-regression
   counts are recomputed from committed `case_ranks` with the same
   functions `calibrate.py` uses. Derived values must match both
   `results.json` and `manifest.json`. Decision fields are recomputed from
   those derived metrics, not from the copied summaries.
5. **Baseline candidate manifest**: `baseline_candidate_manifest_sha256`
   equals the canonical checksum of results.json's per-case ordered +
   multiset candidate checksums (522 cases), and at least one case's
   ordered checksum differs from its multiset checksum (proof the ordered
   hash captures emission order, not a re-sorted multiset).
6. **Summary**: regenerates SUMMARY.md with the same `write_summary` the
   script uses and compares byte-for-byte with the committed file.
7. **Distributions**: results.json carries the summarized score/token-count
   distribution evidence.

Exit 0 on verification, nonzero otherwise.

Usage:
  eval/.venv/bin/python eval/verify_artifacts.py \
      --dict <fixture librime>/bin/luna_pinyin.dict.yaml
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "eval"


def canonical_json(obj):
    from calibrate import canonical_json as _canonical

    return _canonical(obj)


DECISION_FIELDS = (
    "final_alpha", "final_alpha_value", "internal_optimum",
    "positive_alpha_qualified", "final_alpha_rationale",
)


def verify_rank_derived_summaries(results, manifest):
    """Recompute metrics, harmful regressions, and the decision from ranks.

    Returns a list of failure strings (empty when ranks, both copied
    summaries, and the recorded decision agree).
    """
    from calibrate import (
        decide_final,
        harmful_regressions_for_run,
        metrics_from_ranks,
    )

    failures = []
    case_ranks = results.get("case_ranks")
    if not isinstance(case_ranks, dict):
        return ["results.json missing case_ranks"]

    baseline_ranks = case_ranks.get("baseline")
    if not isinstance(baseline_ranks, dict) or "word" not in baseline_ranks:
        return ["case_ranks missing baseline word ranks"]
    baseline_word = baseline_ranks["word"]

    derived_runs = {}
    for key, entry in results.get("runs", {}).items():
        ranks = case_ranks.get(key)
        if not isinstance(ranks, dict) or "sentence" not in ranks \
                or "word" not in ranks:
            failures.append(f"run {key}: missing case_ranks")
            continue

        derived_metrics = metrics_from_ranks(ranks)
        if entry.get("metrics") != derived_metrics:
            failures.append(
                f"run {key}: results metrics disagree with case_ranks")
        run_manifest = manifest.get("runs", {}).get(key)
        if run_manifest is None:
            failures.append(f"manifest missing run {key}")
        elif run_manifest.get("metrics") != derived_metrics:
            failures.append(
                f"run {key}: manifest metrics disagree with case_ranks")

        if len(ranks["word"]) != len(baseline_word):
            failures.append(
                f"run {key}: word rank count {len(ranks['word'])} "
                f"!= baseline {len(baseline_word)}")
            continue
        derived_hr = harmful_regressions_for_run(baseline_word, ranks["word"])
        stored_hr = results.get("harmful_regressions", {}).get(key)
        if stored_hr != derived_hr:
            failures.append(
                f"run {key}: results harmful_regressions disagree with "
                "case_ranks")
        if run_manifest is not None and \
                run_manifest.get("harmful_regressions") != derived_hr:
            failures.append(
                f"run {key}: manifest harmful_regressions disagree with "
                "case_ranks")

        derived_entry = dict(entry)
        derived_entry["metrics"] = derived_metrics
        derived_runs[key] = derived_entry

    if len(derived_runs) != len(results.get("runs", {})):
        return failures

    derived_results = dict(results)
    derived_results["runs"] = derived_runs
    decision = decide_final(derived_results)
    for field in DECISION_FIELDS:
        if manifest.get(field) != decision[field]:
            failures.append(
                f"decision field {field}: manifest "
                f"{manifest.get(field)!r} != recomputed {decision[field]!r}")
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dict", type=Path, required=True,
                    help="fixture librime build's luna_pinyin.dict.yaml")
    args = ap.parse_args()

    sys.path.insert(0, str(EVAL_DIR))
    from calibrate import sha256_bytes, write_summary
    from verify_fixture import verify_fixture

    failures = []

    corpus = EVAL_DIR / "corpus" / "sentences.txt"
    fixture_path = EVAL_DIR / "fixture.json"
    manifest_path = EVAL_DIR / "manifest.json"
    results_path = EVAL_DIR / "results.json"
    summary_path = EVAL_DIR / "SUMMARY.md"

    if not all(p.exists() for p in
               (corpus, fixture_path, manifest_path, results_path,
                summary_path)):
        failures.append("one or more committed artifacts are missing")

    if failures:
        print("FAIL:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))

    # 1. Fixture.
    for failure in verify_fixture(corpus, fixture_path, args.dict):
        failures.append(f"fixture: {failure}")

    # 2. Manifest checksum (canonical rule, self-hash field excluded).
    committed_hash = manifest.get("manifest_sha256")
    without_hash = {
        key: value for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    recomputed_hash = sha256_bytes(
        canonical_json(without_hash).encode("utf-8"))
    if committed_hash != recomputed_hash:
        failures.append(
            f"manifest checksum mismatch: committed {committed_hash}, "
            f"recomputed {recomputed_hash}")

    # 3. Results <-> manifest consistency.
    manifest_runs = manifest.get("runs", {})
    for key, entry in results["runs"].items():
        run_manifest = manifest_runs.get(key)
        if run_manifest is None:
            failures.append(f"manifest missing run {key}")
            continue
        for field in ("alpha", "policy", "lm_term"):
            if run_manifest.get(field) != entry.get(field):
                failures.append(
                    f"run {key}: manifest {field}={run_manifest.get(field)} "
                    f"!= results {field}={entry.get(field)}")
        if run_manifest.get("metrics") != entry.get("metrics"):
            failures.append(f"run {key}: metrics differ between artifacts")
        if run_manifest.get("schema_config_sha256") != entry.get(
                "config_identity"):
            failures.append(
                f"run {key}: schema config identity differs between artifacts")
    for key in manifest_runs:
        if key not in results["runs"]:
            failures.append(f"manifest has unknown run {key}")

    # 4. Rank-derived metrics, harmful regressions, and decision.
    failures.extend(verify_rank_derived_summaries(results, manifest))

    # 5. Baseline candidate manifest.
    baseline_checksums = results.get("baseline_candidate_checksums")
    if not baseline_checksums:
        failures.append("results.json missing baseline_candidate_checksums")
    else:
        expected_counts = {"sentence": 120, "word": 402}
        for kind, count in expected_counts.items():
            cases = baseline_checksums.get(kind)
            if not isinstance(cases, list) or len(cases) != count:
                failures.append(
                    f"baseline_candidate_checksums[{kind}]: expected "
                    f"{count} entries, got "
                    f"{len(cases) if isinstance(cases, list) else 'missing'}")
                continue
            for i, entry in enumerate(cases, 1):
                if not isinstance(entry, dict) or \
                        "ordered_sha256" not in entry or \
                        "multiset_sha256" not in entry:
                    failures.append(
                        f"baseline_candidate_checksums[{kind}] case {i}: "
                        "missing ordered/multiset checksum")
        distinct_order_cases = sum(
            1
            for kind in expected_counts
            for entry in baseline_checksums.get(kind, [])
            if isinstance(entry, dict)
            and entry.get("ordered_sha256") != entry.get("multiset_sha256")
        )
        if distinct_order_cases == 0:
            failures.append(
                "every case has ordered_sha256 == multiset_sha256: the "
                "ordered checksums do not capture emission/merge order "
                "(candidate lists were sorted before hashing)")
        expected_manifest_sha = sha256_bytes(
            canonical_json(baseline_checksums).encode("utf-8"))
        if manifest.get("baseline_candidate_manifest_sha256") != \
                expected_manifest_sha:
            failures.append(
                f"baseline candidate manifest checksum mismatch: committed "
                f"{manifest.get('baseline_candidate_manifest_sha256')}, "
                f"recomputed {expected_manifest_sha}")

    # 6. Summary regenerates byte-for-byte.
    try:
        regenerated = summary_path.with_name(
            "SUMMARY.regenerated.md")
        write_summary(regenerated, manifest, results)
        if regenerated.read_text(encoding="utf-8") != \
                summary_path.read_text(encoding="utf-8"):
            failures.append(
                "SUMMARY.md differs from what write_summary regenerates")
        regenerated.unlink()
    except Exception as error:  # noqa: BLE001
        failures.append(f"summary regeneration failed: {error}")

    # 7. Distribution evidence.
    distributions = results.get("distributions", {})
    for field in ("requests", "samples", "token_count_histogram",
                  "score_min", "score_max", "score_mean"):
        if field not in distributions:
            failures.append(f"distributions missing {field}")

    if failures:
        print("FAIL: artifact verification failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("PASS: committed calibration artifacts are consistent and "
          "regenerable")
    print(f"  manifest sha256:        {manifest['manifest_sha256']}")
    print(f"  final alpha:            {manifest['final_alpha_value']} "
          f"(internal_optimum={manifest['internal_optimum']}, "
          f"positive_alpha_qualified="
          f"{manifest['positive_alpha_qualified']})")
    print(f"  baseline candidate      "
          f"{manifest['baseline_candidate_manifest_sha256']}")
    print(f"  runs verified:          {len(results['runs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
