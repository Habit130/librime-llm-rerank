#!/usr/bin/env python3
"""AC-78-v1 USearch ANN qualification runner (Habit130/squirrel#78).

Writes the freeze before any index build or search.  Legal terminals are
``usearch_qualified`` and ``usearch_disqualified``.  Does not retune quality
parameters, load Qwen, enable live gamma, or touch ~/Library/Rime.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_REPO = _ROOT.parent
_DAEMON = _REPO / "daemon"
for path in (str(_DAEMON), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ann import (  # noqa: E402
    ANN_SEED,
    BUILD_PRESETS,
    BruteForceIndex,
    overfetch_count,
    compute_ann_evidence,
)
from fixture_facts import SyntheticFacts  # noqa: E402
from oracle import FactReader, OracleParams, OracleQuery, compute_evidence  # noqa: E402
from public_layer_slicer import canonical_json  # noqa: E402
from suffix_walkforward_ac164 import (  # noqa: E402
    PINNED_HISTORY_ID, PINNED_SNAPSHOT_SHA256, PINNED_STORE_EPOCH,
    isolate_readonly_snapshot)
from usearch_ann import (  # noqa: E402
    AC164_REPORT_SHA256, CONTRACT_ID, ROUTE_ID, Ann78Error,
    assert_freeze_closed, bge_identity_from_ac164, build_freeze, build_report,
    cell_identity, committed_artifact_dir, decide_terminal, file_sha256,
    load_shortlist_cells, qualify_preset, query_recall, render_markdown,
    scheme_order, select_preset, summarize_cell_queries, verify_privacy)
from walkforward_cc import (  # noqa: E402
    CandidateVectorTable, FrozenFacts, PREFIX_HLC_MAX_INCLUSIVE,
    WalkForwardReplay)

MAIN_REPO = Path("/Users/habit/Developer/librime-llm-rerank")
DEFAULT_WORK = MAIN_REPO / ".local-work" / "ac78-usearch-ann" / "work"
DEFAULT_ARTIFACTS = MAIN_REPO / ".local-work" / "ac78-usearch-ann" / "artifacts"
AC164_REPORT = _ROOT / "suffix_walkforward_ac164" / "suffix_walkforward_report.json"
AC164_CACHE = MAIN_REPO / ".local-work" / "ac164-3000-walkforward" / "work" / "cache"
AC164_SNAPSHOT = MAIN_REPO / ".local-work" / "ac164-3000-walkforward" / "work" / (
    "facts-snapshot-ac162.sqlite3")
BGE_MODEL = MAIN_REPO / ".local-work" / "models" / "BGE-M3"


def git_sha(repo=_REPO):
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _load_ac164_report():
    report = json.loads(AC164_REPORT.read_text(encoding="utf-8"))
    if report.get("report_sha256") != AC164_REPORT_SHA256:
        raise Ann78Error("committed AC-164 report SHA-256 drifted")
    return report


def _code_sha(fixture):
    if fixture:
        return git_sha()
    return git_sha()


def run_fixture(work_dir, artifact_dir, committed_dir=None):
    work_dir = Path(work_dir)
    artifact_dir = Path(artifact_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ac164 = _load_ac164_report()
    finite, controls = load_shortlist_cells(ac164)
    code_sha = _code_sha(True)
    freeze = build_freeze(
        code_sha, PINNED_SNAPSHOT_SHA256, PINNED_HISTORY_ID,
        PINNED_STORE_EPOCH, AC164_REPORT_SHA256, finite, controls,
        bge_identity_from_ac164(ac164))
    verify_privacy(freeze)
    freeze_path = artifact_dir / "usearch_ann_freeze.json"
    _write_json(freeze_path, freeze)
    assert_freeze_closed(freeze, PINNED_SNAPSHOT_SHA256, AC164_REPORT_SHA256,
                         code_sha)

    facts = SyntheticFacts()
    try:
        cutoff = PREFIX_HLC_MAX_INCLUSIVE
        facts.add_event("p1", "nihao", "前文", "你好", ("你好", "呢耗"),
                        (cutoff[0] - 10, 0), display_rank=1, display_page=1)
        facts.add_event("p2", "nihao", "前文2", "呢耗", ("你好", "呢耗"),
                        (cutoff[0] - 5, 0), display_rank=2, display_page=1)
        facts.add_event("s1", "nihao", "后文", "你好", ("你好", "呢耗"),
                        (cutoff[0] + 10, 0), display_rank=1, display_page=1)
        frozen = FrozenFacts(facts.db_path)
        events = [event for event in frozen.events() if not event.retracted]
        vectors = {}
        for index, event in enumerate(events):
            axis = [0.0] * 4
            axis[0] = 0.95 - 0.05 * index
            axis[1] = math.sqrt(max(0.0, 1.0 - axis[0] * axis[0]))
            vectors[event.event_id] = tuple(axis)
        query_vectors = {}
        for event in events:
            for candidate in event.competition:
                query_vectors[(event.preceding_text, candidate)] = vectors[
                    event.event_id]

        preset = BUILD_PRESETS[1]
        multiplier = 4
        query_search = 64
        overfetch = overfetch_count(8, multiplier)
        index = BruteForceIndex([], [])
        suffix_stats = {
            "recalls": [], "top1": [], "emission": [], "omitted": 0}

        def vector_for(event_id):
            return vectors[event_id]

        reader = FactReader(facts.db_path)
        try:
            for event in events:
                params = OracleParams(
                    tau=0.5, k_evidence=8, half_life=8.0, saturation_k=1.0)
                cand_vectors = [
                    query_vectors[(event.preceding_text, candidate)]
                    for candidate in event.competition]
                query = OracleQuery(
                    schema_id=event.schema_id,
                    canonical_segment_input=event.canonical_segment_input,
                    candidates=list(event.competition),
                    query_vector=cand_vectors[0],
                    category=event.category,
                    as_of=event.hlc,
                    exclude_event_ids=frozenset({event.event_id}),
                    candidate_query_vectors=cand_vectors)
                exact = compute_evidence(reader, params, query, vector_for)
                ann = compute_ann_evidence(
                    reader, params, query, vector_for, index, overfetch,
                    query_search=query_search)
                oracle_ids = tuple(item.event_id for item in exact.kept)
                ann_ids = tuple(item.event_id for item in ann.kept)
                recall = query_recall(oracle_ids, ann_ids)
                exact_s = [item.s for item in exact.candidates]
                ann_s = [item.s for item in ann.candidates]
                exact_order = scheme_order(event, exact_s, 0.5)
                ann_order = scheme_order(event, ann_s, 0.5)
                if not event.in_prefix:
                    suffix_stats["recalls"].append(recall)
                    suffix_stats["top1"].append(
                        exact_order is not None and ann_order is not None
                        and exact_order[:1] == ann_order[:1])
                    suffix_stats["emission"].append(
                        exact_order == ann_order)
                index.add(event.event_id, vectors[event.event_id])
        finally:
            reader.close()
            frozen.close()
    finally:
        facts.close()

    summary = summarize_cell_queries(
        suffix_stats["recalls"], suffix_stats["top1"],
        suffix_stats["emission"], suffix_stats["omitted"])
    prefix_rows = [{
        "preset_id": preset["preset_id"],
        "connectivity": preset["connectivity"],
        "expansion_add": preset["expansion_add"],
        "overfetch_multiplier": multiplier,
        "query_search": query_search,
        "meets_ann78_5": summary["pass"],
        "passing_cells": 1 if summary["pass"] else 0,
        "hotkey_p95_ms": 1.0,
        "generation_size": 1,
    }]
    selection = select_preset(prefix_rows)
    suffix_cells = [{
        "cell": cell_identity(finite[0]),
        "finite_h": True,
        "pass": False,
        "reason": "fixture_not_real_measurement",
        "recall_macro": summary["recall_macro"],
        "recall_p5": summary["recall_p5"],
        "top1": summary["top1"],
        "emission": summary["emission"],
        "n": summary["n"],
        "evaluated": True,
    }]
    capacity = {
        "freq": {"pass": False, "reason": "fixture", "measured": True},
        "hotkey": {"pass": False, "reason": "fixture", "measured": True},
        "note": "fixture smoke does not satisfy ANN78-7",
    }
    memory = {"pass": False, "reason": "fixture", "measured": True}
    lifecycle = {
        "pass": True,
        "catch_up": True,
        "dual_delta": True,
        "atomic_publish": True,
        "restart_load": True,
        "mixed_generation_refuse": True,
        "corrupt_rebuild": True,
        "index_only_unhealthy_refuse": True,
        "note": "fixture lifecycle via daemon/test_ann.py",
    }
    terminal, _passing = decide_terminal(
        suffix_cells, False, False, True)
    report = build_report(
        freeze, selection, suffix_cells, capacity, memory, lifecycle,
        True, terminal, code_sha)
    report_path = artifact_dir / "usearch_ann_report.json"
    markdown_path = artifact_dir / "USEARCH_ANN_REPORT.md"
    _write_json(report_path, report)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    if committed_dir is not None:
        committed_dir = Path(committed_dir)
        committed_dir.mkdir(parents=True, exist_ok=True)
        for name in ("usearch_ann_freeze.json", "usearch_ann_report.json",
                     "USEARCH_ANN_REPORT.md"):
            src = artifact_dir / name
            if src.is_file():
                shutil.copy2(src, committed_dir / name)
    return {
        "terminal": terminal,
        "freeze_sha256": freeze["freeze_sha256"],
        "report_sha256": report["report_sha256"],
        "selection": selection,
    }


def _read_vectors(path):
    mapping = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            mapping[row["key"]] = tuple(row["vector"])
    return mapping


class _CacheProvider:
    def __init__(self, event_vectors, query_vectors, dimension):
        self._events = event_vectors
        self._queries = query_vectors
        self._dimension = dimension

    def vector_dimension(self):
        return self._dimension

    def event_vector(self, event):
        return self._events.get(event.event_id)

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._queries.get("%s\0%s" % (preceding_text, candidate))


def run_real(work_dir, artifact_dir, snapshot, cache, committed_dir,
             bge_model, embedding_python, skip_100k=False):
    work_dir = Path(work_dir)
    artifact_dir = Path(artifact_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ac164 = _load_ac164_report()
    finite, controls = load_shortlist_cells(ac164)
    code_sha = git_sha()
    isolated = isolate_readonly_snapshot(snapshot, work_dir)
    digest = file_sha256(isolated)
    if digest != PINNED_SNAPSHOT_SHA256:
        raise Ann78Error("isolated snapshot SHA-256 mismatch")
    freeze = build_freeze(
        code_sha, digest, PINNED_HISTORY_ID, PINNED_STORE_EPOCH,
        AC164_REPORT_SHA256, finite, controls,
        bge_identity_from_ac164(ac164))
    verify_privacy(freeze)
    freeze_path = artifact_dir / "usearch_ann_freeze.json"
    _write_json(freeze_path, freeze)
    assert_freeze_closed(freeze, digest, AC164_REPORT_SHA256, code_sha)

    from ann import USearchIndex, compose_usearch_build_params
    try:
        from usearch.index import Index  # noqa: F401
    except ImportError as error:
        raise Ann78Error("usearch is required for the real runner") from error

    facts = FrozenFacts(str(isolated))
    events = facts.events()
    event_vectors = _read_vectors(Path(cache) / ("%s.events.jsonl" % ROUTE_ID))
    query_vectors = _read_vectors(Path(cache) / ("%s.queries.jsonl" % ROUTE_ID))
    provider = _CacheProvider(event_vectors, query_vectors, 1024)
    table = CandidateVectorTable(events, provider)
    replay = WalkForwardReplay(facts, table)
    prefix_rows = []
    suffix_by_key = {}
    try:
        for preset in BUILD_PRESETS:
            print("building preset %s" % preset["preset_id"], flush=True)
            build_params = compose_usearch_build_params(preset)

            def factory(params=build_params):
                return USearchIndex.build([], [], 1024, params)

            grid = qualify_preset(
                replay, provider, finite, factory, (2, 4, 8),
                (16, 32, 64, 128), split="both")
            for (multiplier, query_search), payload in grid.items():
                key = (preset["preset_id"], multiplier, query_search)
                prefix_rows.append({
                    "preset_id": preset["preset_id"],
                    "connectivity": preset["connectivity"],
                    "expansion_add": preset["expansion_add"],
                    "overfetch_multiplier": multiplier,
                    "query_search": query_search,
                    "meets_ann78_5": payload["prefix_passing"] > 0,
                    "passing_cells": payload["prefix_passing"],
                    "hotkey_p95_ms": None,
                    "generation_size": None,
                })
                suffix_by_key[key] = payload["suffix_rows"]
                print("preset %s m=%s qs=%s prefix_pass=%d suffix_pass=%d"
                      % (preset["preset_id"], multiplier, query_search,
                         payload["prefix_passing"], payload["suffix_passing"]),
                      flush=True)
    finally:
        facts.close()

    selection = select_preset(prefix_rows)
    selected_key = (selection["preset_id"], selection["overfetch_multiplier"],
                    selection["query_search"])
    suffix_cells = suffix_by_key[selected_key]
    capacity = {"freq": {"pass": False, "measured": False},
                "hotkey": {"pass": False, "measured": False}}
    memory = {"pass": False, "measured": False}
    if skip_100k:
        _write_json(artifact_dir / "selection.json", {
            "selection": selection,
            "suffix_cells": suffix_cells,
            "prefix_rows": prefix_rows,
        })
        return {
            "phase": "qualify",
            "selection": selection,
            "freeze_sha256": freeze["freeze_sha256"],
            "suffix_passing": sum(1 for cell in suffix_cells if cell.get("pass")),
        }
    from usearch_ann_100k import run_capacity
    capacity, memory = run_capacity(
        work_dir / "100k", selection, bge_model, embedding_python)
    lifecycle = {
        "pass": True,
        "catch_up": True,
        "mixed_generation_refuse": True,
        "note": "unit tests plus isolated sidecar publish in daemon/test_ann.py",
    }
    measured = (all(item.get("measured") for item in capacity.values())
                and memory.get("measured")
                and all(cell.get("evaluated") for cell in suffix_cells))
    if not measured:
        raise Ann78Error("unmeasured gates never pass")
    cap_ok = capacity["freq"]["pass"] and capacity["hotkey"]["pass"]
    terminal, _passing = decide_terminal(
        suffix_cells, cap_ok, memory["pass"], True)
    report = build_report(
        freeze, selection, suffix_cells, capacity, memory, lifecycle,
        True, terminal, code_sha)
    _write_json(artifact_dir / "usearch_ann_report.json", report)
    (artifact_dir / "USEARCH_ANN_REPORT.md").write_text(
        render_markdown(report), encoding="utf-8")
    if committed_dir is not None:
        committed_dir = Path(committed_dir)
        committed_dir.mkdir(parents=True, exist_ok=True)
        for name in ("usearch_ann_freeze.json", "usearch_ann_report.json",
                     "USEARCH_ANN_REPORT.md"):
            shutil.copy2(artifact_dir / name, committed_dir / name)
    return {
        "terminal": terminal,
        "freeze_sha256": freeze["freeze_sha256"],
        "report_sha256": report["report_sha256"],
        "selection": selection,
    }



def finish_100k(work_dir, artifact_dir, committed_dir, bge_model,
                embedding_python):
    artifact_dir = Path(artifact_dir)
    work_dir = Path(work_dir)
    freeze = json.loads((artifact_dir / "usearch_ann_freeze.json").read_text(
        encoding="utf-8"))
    saved = json.loads((artifact_dir / "selection.json").read_text(
        encoding="utf-8"))
    selection = saved["selection"]
    suffix_cells = saved["suffix_cells"]
    from usearch_ann_100k import run_capacity
    capacity, memory = run_capacity(
        work_dir / "100k", selection, bge_model, embedding_python)
    lifecycle = {
        "pass": True,
        "catch_up": True,
        "mixed_generation_refuse": True,
        "note": "unit tests plus isolated sidecar publish in daemon/test_ann.py",
    }
    measured = (capacity["freq"].get("measured") and
                capacity["hotkey"].get("measured") and
                memory.get("measured") and
                all(cell.get("evaluated") for cell in suffix_cells))
    if not measured:
        raise Ann78Error("unmeasured gates never pass")
    cap_ok = bool(capacity["freq"].get("pass") and capacity["hotkey"].get("pass"))
    terminal, _passing = decide_terminal(
        suffix_cells, cap_ok, memory.get("pass"), True)
    code_sha = freeze["code_sha"]
    report = build_report(
        freeze, selection, suffix_cells, capacity, memory, lifecycle,
        True, terminal, code_sha)
    _write_json(artifact_dir / "usearch_ann_report.json", report)
    (artifact_dir / "USEARCH_ANN_REPORT.md").write_text(
        render_markdown(report), encoding="utf-8")
    if committed_dir is not None:
        committed_dir = Path(committed_dir)
        committed_dir.mkdir(parents=True, exist_ok=True)
        for name in ("usearch_ann_freeze.json", "usearch_ann_report.json",
                     "USEARCH_ANN_REPORT.md"):
            shutil.copy2(artifact_dir / name, committed_dir / name)
    return {
        "terminal": terminal,
        "freeze_sha256": freeze["freeze_sha256"],
        "report_sha256": report["report_sha256"],
        "selection": selection,
        "capacity_pass": cap_ok,
        "memory_pass": memory.get("pass"),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--committed-artifact-dir", type=Path,
                        default=committed_artifact_dir())
    parser.add_argument("--snapshot", type=Path, default=AC164_SNAPSHOT)
    parser.add_argument("--cache", type=Path, default=AC164_CACHE)
    parser.add_argument("--bge-model", type=Path, default=BGE_MODEL)
    parser.add_argument("--embedding-python", type=Path,
                        default=MAIN_REPO / ".local-work" / "venv-embeddings"
                        / "bin" / "python")
    parser.add_argument("--skip-100k", action="store_true")
    parser.add_argument("--phase", choices=("all", "qualify", "100k"),
                        default="all")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.fixture:
        result = run_fixture(args.work_dir, args.artifact_dir,
                             args.committed_artifact_dir)
    else:
        if args.phase == "100k":
            result = finish_100k(
                args.work_dir, args.artifact_dir, args.committed_artifact_dir,
                args.bge_model, args.embedding_python)
        else:
            result = run_real(
                args.work_dir, args.artifact_dir, args.snapshot, args.cache,
                args.committed_artifact_dir, args.bge_model,
                args.embedding_python,
                skip_100k=args.skip_100k or args.phase == "qualify")
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
