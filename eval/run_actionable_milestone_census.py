#!/usr/bin/env python3
"""Actionable milestone census runner (Habit130/squirrel#162, AC-162-v1).

One-shot driver: takes a **fresh** read-only Online Backup of the live
semantic-memory facts at claim (the live store is never written), binds all
measurement identities BEFORE any score (snapshot SHA-256, history_id,
store_epoch, code SHA, route/model/tokenizer identity, frozen cutoff,
reference parameters), scores exactly one route
(``dedicated_qwen3_embedding_0_6b``) with the AC-159 first-route worker,
replays the whole snapshot through the AC-159 seam under the frozen
reference parameters, and writes the desensitized freeze/report plus exactly
one legal terminal (``reached_3000`` / ``pending_3000``).

The Qwen3-Embedding runtime/GPU is exclusive to this run.  No L28/BGE model,
no τ calibration, no grid, no bootstrap, no quality gate, no shortlist, no
ANN, no deployment, no live α/γ/evidence change, no librime build tree, no
`~/Library/Rime` deploy, no latency claim.

Usage:

    python3 eval/run_actionable_milestone_census.py \
        --work-dir <main-repo>/.local-work/ac162-actionable-census/work \
        --artifact-dir <main-repo>/.local-work/ac162-actionable-census/artifacts

    (the desensitized mirror is committed to eval/actionable_milestone_census/;
     rerun an existing snapshot with --snapshot; model-free wiring smoke with
     --fixture.)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(Path(__file__).resolve().parents[1] / "daemon") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from actionable_milestone_census import (  # noqa: E402
    CONTRACT_ID, ENGINE_VERSION, ROUTE_ID, CensusError, PrivacyViolation,
    build_freeze, build_report, census_outcomes, legal_terminal,
    public_report, render_markdown, split_census_counts, verify_privacy)
from public_layer_slicer import canonical_json  # noqa: E402
from snapshot import SnapshotError, take_snapshot  # noqa: E402
from walkforward_cc import (  # noqa: E402
    FrozenFacts, PREFIX_HLC_MAX_INCLUSIVE, SuffixWalkforwardError,
    needed_query_pairs, prefix_suffix_split)
from run_suffix_walkforward import (  # noqa: E402  (AC-159 worker seam)
    EnvironmentBlocker, MAIN_REPO, _FixtureProvider, _fixture_provider,
    _identity_path, _load_route_vectors, _spawn)

FREEZE_NAME = "actionable_milestone_census_freeze.json"
REPORT_JSON_NAME = "actionable_milestone_census_report.json"
REPORT_MD_NAME = "ACTIONABLE_MILESTONE_CENSUS_REPORT.md"
DEFAULT_ARTIFACT_DIR = (MAIN_REPO / ".local-work" / "ac162-actionable-census"
                        / "artifacts")
DEFAULT_WORK_DIR = (MAIN_REPO / ".local-work" / "ac162-actionable-census"
                    / "work")
# Git-committed mirror of the desensitized AC-162 freeze/report.  A NEW
# path: it never touches eval/suffix_walkforward/ (AC-157) or
# eval/suffix_walkforward_ac159/ (AC-159).
COMMITTED_ARTIFACT_DIR = (Path(__file__).resolve().parent
                          / "actionable_milestone_census")
# Historical artifact dirs that must stay untouched.
HISTORICAL_DIRS = (
    (Path(__file__).resolve().parent / "suffix_walkforward").resolve(),
    (Path(__file__).resolve().parent / "suffix_walkforward_ac159").resolve(),
)

RUN_SUFFIX_WALKFORWARD = str(Path(__file__).resolve().parent
                             / "run_suffix_walkforward.py")


class ContractFailure(Exception):
    """A frozen AC-162 invariant failed during the run."""


def current_code_sha(*, require_clean):
    repo = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                  cwd=str(repo), text=True).strip()
    if not require_clean:
        return sha
    dirty = subprocess.check_output(["git", "status", "--porcelain"],
                                    cwd=str(repo), text=True)
    ignored = (".cache/", "actionable_milestone_census/", ".local-work/",
               "__pycache__", ".venv")
    leftover = [line for line in dirty.splitlines()
                if not any(marker in line for marker in ignored)]
    if leftover:
        raise EnvironmentBlocker(
            "real run requires a clean code worktree: %s"
            % "; ".join(leftover))
    return sha


def _ensure_not_historical(path, label):
    resolved = Path(path).resolve()
    for historical in HISTORICAL_DIRS:
        if resolved == historical or historical in resolved.parents:
            raise EnvironmentBlocker(
                "%s directory is historical and read-only: %s"
                % (label, path))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--artifact-dir", type=Path,
                        default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--committed-artifact-dir", type=Path,
                        default=COMMITTED_ARTIFACT_DIR)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None,
                        help="worker alias for --artifact-dir (unused here)")
    parser.add_argument("--live-db", default=os.path.expanduser(
        "~/Library/Application Support/Squirrel/SemanticMemory/"
        "facts.sqlite3"))
    parser.add_argument("--status-cli", default=os.path.expanduser(
        "~/Developer/librime-llm-rerank/daemon/squirrel-semantic-memory"))
    parser.add_argument("--qwen3-embedding-model", default=str(
        MAIN_REPO / ".local-work" / "models" / "Qwen3-Embedding-0.6B"))
    parser.add_argument("--embedding-python", default=str(
        MAIN_REPO / ".local-work" / "venv-embeddings" / "bin" / "python"))
    parser.add_argument("--snapshot", default=None,
                        help="reuse an existing frozen snapshot (path)")
    parser.add_argument("--fixture", action="store_true",
                        help="model-free smoke run: deterministic synthetic "
                             "vectors, no model workers (driver wiring only; "
                             "the committed test suite is the real gate)")
    return parser.parse_args(argv)


def _fixture_identity():
    return {
        "route_id": ROUTE_ID,
        "adapter": "fixture",
        "instruction": "none",
        "pooling": "fixture",
        "representation_id": "fixture:%s" % ROUTE_ID,
        "vector_dimension": _FixtureProvider.DIMENSION,
    }


def _main_driver(args):
    work_dir = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    cache = args.cache if args.cache is not None else (work_dir / "cache")
    cache.mkdir(parents=True, exist_ok=True)
    output = args.artifact_dir
    _ensure_not_historical(output, "artifact")
    committed = args.committed_artifact_dir
    _ensure_not_historical(committed, "committed artifact")
    output.mkdir(parents=True, exist_ok=True)

    code_sha = current_code_sha(require_clean=True)

    # -- frozen snapshot (fresh read-only Online Backup at claim) --------
    if args.snapshot:
        snapshot_path = Path(args.snapshot)
        if not snapshot_path.is_file():
            raise EnvironmentBlocker(
                "snapshot not found: %s" % snapshot_path)
        snapshot = {
            "path": os.path.abspath(args.snapshot),
            "sha256": _file_sha256(str(snapshot_path)),
            "identity": _open_meta(str(snapshot_path)),
            "status": {"status_check": "skipped"},
            "source": "provided_frozen_snapshot",
        }
    else:
        if not os.path.isfile(args.live_db):
            raise EnvironmentBlocker(
                "missing live facts store; a claim-time snapshot is "
                "required (CENSUS3000-1): %s" % args.live_db)
        snapshot = take_snapshot(args.live_db, str(work_dir),
                                 status_cli=args.status_cli
                                 if os.path.isfile(args.status_cli) else None)
        snapshot["source"] = "claim_time_online_backup"
        snapshot_path = Path(snapshot["path"])
    print("snapshot sha256: %s" % snapshot["sha256"], flush=True)

    facts = FrozenFacts(str(snapshot_path))
    try:
        events = facts.events()
        targets = [event for event in events if not event.retracted]
        if not targets:
            raise EnvironmentBlocker(
                "snapshot has no unretracted events; not a consistent "
                "Online Backup (CENSUS3000-1)")
        prefix_targets, suffix_targets = prefix_suffix_split(targets)
        print("prefix targets: %d; suffix targets: %d"
              % (len(prefix_targets), len(suffix_targets)), flush=True)

        # -- route identity (frozen BEFORE any score) ---------------------
        if args.fixture:
            identities = {ROUTE_ID: _fixture_identity()}
        else:
            if not os.path.isfile(args.embedding_python):
                raise EnvironmentBlocker(
                    "missing embedding runtime: %s" % args.embedding_python)
            if not os.path.isdir(args.qwen3_embedding_model):
                raise EnvironmentBlocker(
                    "missing Qwen3-Embedding model: %s"
                    % args.qwen3_embedding_model)
            # The identity worker runs in the embedding venv (dependency
            # versions come from that interpreter, exactly as AC-159); the
            # requested model path is forwarded so the fingerprint always
            # matches the model the census validates and scores.
            _spawn(args.embedding_python,
                   ["--identity", ROUTE_ID,
                    "--qwen3-embedding-model", str(args.qwen3_embedding_model)],
                   cache=cache, output=output)
            identities = {ROUTE_ID: json.loads(
                _identity_path(cache, ROUTE_ID).read_text(
                    encoding="utf-8"))}
        if identities[ROUTE_ID]["route_id"] != ROUTE_ID:
            raise EnvironmentBlocker("identity drifted for %s" % ROUTE_ID)
        print("route identity frozen: %s (model %s)" % (
            ROUTE_ID,
            identities[ROUTE_ID].get("model_digest", "fixture")), flush=True)

        # -- freeze BEFORE any score (CENSUS3000-1) ------------------------
        freeze = build_freeze(
            code_sha=code_sha, snapshot=snapshot,
            route_identity=identities[ROUTE_ID],
            prefix_events=prefix_targets, suffix_events=suffix_targets)
        verify_privacy(freeze)
        frozen_path = output / FREEZE_NAME
        if frozen_path.exists():
            existing = json.loads(frozen_path.read_text(encoding="utf-8"))
            if existing.get("code_sha") != code_sha:
                frozen_path.unlink()  # stale code -> rebuild
            elif existing != freeze:
                raise EnvironmentBlocker(
                    "existing freeze does not match the reconstituted "
                    "identity (code/snapshot/route drift)")
        tmp_path = frozen_path.with_suffix(frozen_path.suffix + ".tmp")
        tmp_path.write_text(canonical_json(freeze) + "\n", encoding="utf-8")
        tmp_path.replace(frozen_path)
        print("freeze written: %s" % (output / FREEZE_NAME), flush=True)

        # -- single-route vectors (AC-159 worker seam, one shot) ----------
        pairs = needed_query_pairs(facts, targets)
        if args.fixture:
            provider = _fixture_provider(events, ROUTE_ID)
        else:
            _spawn(args.embedding_python,
                   ["--score-route", ROUTE_ID,
                    "--qwen3-embedding-model", str(args.qwen3_embedding_model)],
                   cache=cache, output=output, snapshot=str(snapshot_path))
            provider = _load_route_vectors(
                cache, ROUTE_ID, identities[ROUTE_ID], events, pairs)
        print("route vectors ready: %d query pairs" % len(pairs), flush=True)

        # -- replay + counts + terminal ------------------------------------
        outcomes = census_outcomes(facts, provider)
        counts = split_census_counts(outcomes)
        total = counts["total"]["actionable_group_complete"]
        terminal = legal_terminal(total)
        print("prefix actionable group-complete: %d"
              % counts["prefix"]["actionable_group_complete"], flush=True)
        print("suffix actionable group-complete: %d"
              % counts["suffix"]["actionable_group_complete"], flush=True)
        print("total actionable group-complete: %d" % total, flush=True)

        report = build_report(
            code_sha=code_sha, snapshot=snapshot,
            route_identity=identities[ROUTE_ID], counts=counts,
            terminal=terminal, prefix_events=prefix_targets,
            suffix_events=suffix_targets,
            notes=[
                "the census reports the fresh claim-time counts; drift vs "
                "the accepted AC-159 2537/13/2550 is expected and reported, "
                "never forced (RISK-CENSUS3000-1)",
                "L28 and BGE routes are intentionally outside this gate: "
                "AC-159's canonical top-level data count used the first "
                "Qwen3-Embedding route (RISK-CENSUS3000-2)",
                "no grid, quality gate, shortlist, ANN, deployment or live "
                "alpha/gamma/evidence change occurred (CENSUS3000-7)",
            ],
            decisions=[
                "d1 snapshot: one fresh read-only Online Backup at claim "
                "(CENSUS3000-1); the live store is never written; status "
                "continuity is checked when the status CLI is available",
                "d2 route: exactly dedicated_qwen3_embedding_0_6b; payload "
                "last64(preceding)+candidate; frozen English query "
                "instruction on the query side only, no event-side "
                "instruction (AC-159 first-route semantics)",
                "d3 parameters: tau=0, K_evidence=8, H=inf, saturation_k=1, "
                "gamma=0; actionable = any(s > 0) — gamma zero preserves the "
                "shadow order but does not redefine actionability",
                "d4 group-complete: saved same-group competition size < 32; "
                "the persisted competition_complete bit is never the gate "
                "(#76/#77 rewrite)",
                "d5 split: prefix = hlc <= [1787667799562,0] inclusive, "
                "suffix = strictly later; the cutoff is never moved to the "
                "new snapshot maximum (CENSUS3000-5)",
                "d6 terminal: reached_3000 iff total actionable "
                "group-complete >= 3000, else pending_3000 with the exact "
                "remaining count; the walk-forward is not started by this "
                "census (CENSUS3000-4)",
            ],
        )
        verify_privacy(report)
        public = public_report(report)
        verify_privacy(public)
        (output / REPORT_JSON_NAME).write_text(
            canonical_json(public) + "\n", encoding="utf-8")
        (output / REPORT_MD_NAME).write_text(
            render_markdown(public), encoding="utf-8")
        print("report written: %s/%s" % (output, REPORT_JSON_NAME),
              flush=True)
        print("report sha256: %s" % public["report_sha256"], flush=True)
        committed.mkdir(parents=True, exist_ok=True)
        for name in (FREEZE_NAME, REPORT_JSON_NAME, REPORT_MD_NAME):
            source = output / name
            if source.is_file():
                shutil.copyfile(source, committed / name)
        print("committed report mirror: %s" % committed, flush=True)
        print("terminal outcome: %s" % terminal["outcome"], flush=True)
        return 0
    finally:
        facts.close()


def _open_meta(path):
    import sqlite3
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()


def _file_sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return _main_driver(args)
    except ContractFailure as error:
        print("contract failure:", error, file=sys.stderr)
        return 4
    except EnvironmentBlocker as error:
        print("environment blocker:", error, file=sys.stderr)
        return 3
    except (SnapshotError, CensusError, PrivacyViolation,
            SuffixWalkforwardError) as error:
        # RISK-CENSUS3000-3: an inconsistent Online Backup, a privacy
        # violation or any census/engine input fault is an execution-
        # environment blocker on the documented channel (exit 3), never a
        # raw traceback; nothing is delivered either way (fail closed).
        print("environment blocker:", error, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())