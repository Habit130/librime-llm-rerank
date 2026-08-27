#!/usr/bin/env python3
"""Prefix hard-negative query census driver (Habit130/squirrel#158, AC-158-v1).

Facts-only: verifies the pinned #157 claim-time snapshot (bytes + identity,
RISK-158-1), computes the new prefix cutoff = max unretracted HLC
(inclusive), counts the primary hard-negative queries with the frozen
``prefix_hard_negative_query_count`` definition (threshold 200) and writes
the desensitized census report (hashes + HLC pair + counts + terminal) into
the artifact dir.  No model, no grid, no live store access, no
`~/Library/Rime`.

Usage:

    python3 eval/run_prefix_hn_census.py \
        --snapshot <pinned snapshot copy> \
        --artifact-dir eval/prefix_hn_census
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from prefix_hn_census import (  # noqa: E402
    ENGINE_VERSION, PrivacyViolation, public_report, render_markdown,
    run_census, verify_privacy, PINNED_SNAPSHOT_SHA256)

FREEZE_NAME = "prefix_hn_census_freeze.json"
REPORT_JSON_NAME = "prefix_hn_census_report.json"
REPORT_MD_NAME = "PREFIX_HN_CENSUS_REPORT.md"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "prefix_hn_census"


class EnvironmentBlocker(Exception):
    """A required local snapshot is missing or does not byte-match."""


def current_code_sha(*, require_clean):
    repo = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                  cwd=str(repo), text=True).strip()
    if not require_clean:
        return sha
    dirty = subprocess.check_output(["git", "status", "--porcelain"],
                                    cwd=str(repo), text=True)
    ignored = (".cache/", "prefix_hn_census/", ".local-work/",
               "__pycache__", ".venv")
    leftover = [line for line in dirty.splitlines()
                if not any(marker in line for marker in ignored)]
    if leftover:
        raise EnvironmentBlocker(
            "real run requires a clean code worktree: %s"
            % "; ".join(leftover))
    return sha


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True,
                        help="pinned #157 snapshot copy (byte-verified)")
    parser.add_argument("--artifact-dir", type=Path,
                        default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--skip-sha-check", action="store_true",
                        help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _main(args):
    snapshot_path = Path(args.snapshot)
    if not snapshot_path.is_file():
        raise EnvironmentBlocker(
            "snapshot not found (RISK-158-1): %s" % snapshot_path)
    if not args.skip_sha_check:
        from prefix_hn_census import _file_sha256
        if _file_sha256(str(snapshot_path)) != PINNED_SNAPSHOT_SHA256:
            raise EnvironmentBlocker(
                "snapshot bytes do not reproduce the pinned SHA-256 "
                "(RISK-158-1); refuse to substitute a live backup: %s"
                % snapshot_path)
    code_sha = current_code_sha(require_clean=True)
    output = args.artifact_dir
    output.mkdir(parents=True, exist_ok=True)

    try:
        report = run_census(str(snapshot_path), code_sha=code_sha)
    except PrivacyViolation as error:
        raise EnvironmentBlocker("privacy scan failed: %s" % error)
    public = public_report(report)
    verify_privacy(public)

    # Freeze BEFORE the report: identities only (snapshot pin + cutoff is
    # a property of the snapshot, not of a live state).
    freeze = {
        "contract": "AC-158-v1",
        "code_sha": code_sha,
        "snapshot_sha256": PINNED_SNAPSHOT_SHA256,
        "cutoff_hlc": public["cutoff"]["hlc"],
        "threshold": public["hard_negative"]["threshold"],
    }
    freeze_path = output / FREEZE_NAME
    if freeze_path.exists():
        existing = json.loads(freeze_path.read_text(encoding="utf-8"))
        if existing.get("code_sha") != code_sha:
            freeze_path.unlink()  # stale code -> rebuild
        elif existing != freeze:
            raise EnvironmentBlocker(
                "existing freeze does not match the reconstituted "
                "identity (code/snapshot drift)")
    tmp_path = freeze_path.with_suffix(freeze_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(freeze, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")) + "\n", encoding="utf-8")
    tmp_path.replace(freeze_path)

    (output / REPORT_JSON_NAME).write_text(
        json.dumps(public, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")) + "\n", encoding="utf-8")
    (output / REPORT_MD_NAME).write_text(
        render_markdown(public), encoding="utf-8")
    print("report written: %s/%s" % (output, REPORT_JSON_NAME))
    print("report sha256: %s" % public["report_sha256"])
    print("terminal: %s" % public["terminal"]["outcome"])
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return _main(args)
    except EnvironmentBlocker as error:
        print("environment blocker:", error, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())