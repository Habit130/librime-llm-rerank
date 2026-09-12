#!/usr/bin/env python3
"""AC-80-v1 production configuration lock runner (Habit130/squirrel#80).

Writes the freeze before any lock decision. Uses bound artifacts only.
Does not re-run walk-forward, ANN, 100k, or models. Does not enable live
gamma or start #81.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_REPO = _ROOT.parent
_DAEMON = _REPO / "daemon"
for path in (str(_DAEMON), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from production_config_lock import (  # noqa: E402
    Lock80Error, assert_freeze_closed, build_freeze, build_report,
    committed_artifact_dir, decide_lock, load_bound_bundle, render_markdown,
    verify_privacy)
from public_layer_slicer import canonical_json  # noqa: E402

MAIN_REPO = Path("/Users/habit/Developer/librime-llm-rerank")
DEFAULT_ARTIFACTS = MAIN_REPO / ".local-work" / "ac80-production-lock" / (
    "artifacts")
FREEZE_NAME = "production_config_lock_freeze.json"
REPORT_NAME = "production_config_lock_report.json"
MANIFEST_NAME = "production_config_lock_manifest.json"
MARKDOWN_NAME = "PRODUCTION_CONFIG_LOCK_REPORT.md"


def git_sha(repo=_REPO):
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def run_bound(artifact_dir, committed_dir=None, code_sha=None):
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle = load_bound_bundle()
    code_sha = code_sha or git_sha()
    freeze = build_freeze(code_sha, bundle)
    verify_privacy(freeze)
    freeze_path = artifact_dir / FREEZE_NAME
    _write_json(freeze_path, freeze)
    written = json.loads(freeze_path.read_text(encoding="utf-8"))
    assert_freeze_closed(
        written, written["snapshot_sha256"], written["ac164_report_sha256"],
        code_sha)
    if "terminal" in written:
        raise Lock80Error("freeze pre-assigned a terminal")
    decision = decide_lock(written, bundle)
    report = build_report(written, decision, code_sha)
    _write_json(artifact_dir / REPORT_NAME, report)
    _write_json(artifact_dir / MANIFEST_NAME, report["manifest"])
    (artifact_dir / MARKDOWN_NAME).write_text(
        render_markdown(report), encoding="utf-8")
    if committed_dir is not None:
        committed_dir = Path(committed_dir)
        committed_dir.mkdir(parents=True, exist_ok=True)
        for name in (FREEZE_NAME, REPORT_NAME, MANIFEST_NAME, MARKDOWN_NAME):
            shutil.copy2(artifact_dir / name, committed_dir / name)
    return {
        "terminal": report["terminal"],
        "survivor_count": report["survivor_count"],
        "freeze_sha256": written["freeze_sha256"],
        "report_sha256": report["report_sha256"],
        "prospective_start_hlc": report["prospective_start_hlc"],
        "live_gamma": report["live_gamma"],
        "issue_81_started": report["issue_81_started"],
        "next_milestone_wait": report["next_milestone_wait"],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--committed-artifact-dir", type=Path,
                        default=committed_artifact_dir())
    parser.add_argument("--code-sha", default=None)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = run_bound(
        args.artifact_dir, args.committed_artifact_dir,
        code_sha=args.code_sha)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
