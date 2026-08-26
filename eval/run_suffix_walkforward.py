#!/usr/bin/env python3
"""Suffix walk-forward runner (Habit130/squirrel#159, AC-159-v1).

One-shot driver: takes a **new** read-only Online Backup / facts copy at
claim (the #77/#155 prefix files are not a sufficient store), splits it at
the frozen HLC cutoff `[1787667799562, 0]` (prefix inclusive), scores the
three frozen routes (`dedicated_qwen3_embedding_0_6b`,
`qwen_l28_candidate_span_mean`, `dedicated_bge_m3`) into a private vector
cache (one process per route in its own runtime: the embedding venv for the
torch routes, the daemon venv for the MLX L28 route), runs the pre-declared
grid on the prefix (τ + cells), applies the #159-quoted gates on the suffix
claim set, and writes the desensitized freeze/report into the artifact dir.

The freeze (identity: code SHA, snapshot/split hashes, route fingerprints,
grid manifest, seed, replicates) is written BEFORE any score; a second claim
or a freeze mismatch fails closed.  No live-store write, no daemon restart,
no `~/Library/Rime` deploy; GPU/MLX is exclusive to this run
(shared-state allocation of the issue).

Terminals (issue #159 body, frozen): exact shortlist | 收窄声称 shortlist |
无合格方案 | 数据不足.  No ANN, no production winner, no live α/γ change;
public-B accuracy and the personal 2x2 r never enter the decision.

Usage:

    python3 eval/run_suffix_walkforward.py \
        --work-dir <local snapshot+report dir> \
        --artifact-dir .local-work/ac159-suffix-wf/artifacts \
        --embedding-python <repo>/.local-work/venv-embeddings/bin/python \
        --daemon-python <repo>/daemon/.venv/bin/python \
        --qwen3-embedding-model <repo>/.local-work/models/Qwen3-Embedding-0.6B \
        --bge-model <repo>/.local-work/models/BGE-M3 \
        --qwen-base /Users/habit/Models/Qwen/Qwen3-0.6B-Base

    (worker modes are spawned by the driver; see --identity / --score-route)
"""

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(Path(__file__).resolve().parents[1] / "daemon") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from public_layer_slicer import canonical_json, sha256_bytes  # noqa: E402
from snapshot import take_snapshot  # noqa: E402
from walkforward_cc import (  # noqa: E402
    CONTRACT_ID, ENGINE_VERSION, FrozenFacts, PREFIX_HLC_MAX_INCLUSIVE,
    ROUTE_IDS, L28_ROUTE_ID, BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES,
    MIN_HARD_NEGATIVE_QUERIES,
    CandidateVectorTable, WalkForwardReplay, needed_query_pairs,
    margin_base_prefix, prefix_suffix_split)
from calibration_cc import calibrate_tau, prefix_hard_negative_query_count  # noqa: E402
from grid_cc import data_counts, facts_only_data_count, grid_manifest, run_route  # noqa: E402
from shortlist_cc import assemble_shortlist  # noqa: E402
from suffix_report import (build_report, verify_privacy,  # noqa: E402
                           render_markdown)


# Machine-bound defaults follow the AC-155 precedent: runtimes, models and
# the claim-time work area live in the main librime-llm-rerank checkout
# (`.local-work/` is gitignored there; the worktree carries only code).
MAIN_REPO = Path(os.path.abspath(__file__)).resolve().parents[1]
if not (MAIN_REPO / ".local-work" / "models").is_dir():
    MAIN_REPO = Path("/Users/habit/Developer/librime-llm-rerank")


def _main_path(*parts):
    return str(MAIN_REPO.joinpath(*parts))


FREEZE_NAME = "suffix_walkforward_freeze.json"
REPORT_JSON_NAME = "suffix_walkforward_report.json"
REPORT_MD_NAME = "SUFFIX_WALKFORWARD_REPORT.md"
DEFAULT_ARTIFACT_DIR = (Path(__file__).resolve().parents[1] / ".local-work"
                        / "ac159-suffix-wf" / "artifacts")


class EnvironmentBlocker(Exception):
    """A required local model, runtime or snapshot is missing."""


class ContractFailure(Exception):
    """A frozen AC-159 invariant failed during the run."""


def _cache_dir(cache):
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _event_vectors_path(cache, route_id):
    return cache / ("%s.events.jsonl" % route_id)


def _query_vectors_path(cache, route_id):
    return cache / ("%s.queries.jsonl" % route_id)


def _identity_path(cache, route_id):
    return cache / ("%s.identity.json" % route_id)


def current_code_sha(*, require_clean):
    repo = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                  cwd=str(repo), text=True).strip()
    if not require_clean:
        return sha
    dirty = subprocess.check_output(["git", "status", "--porcelain"],
                                    cwd=str(repo), text=True)
    ignored = (".cache/", "suffix_walkforward/", ".local-work/",
               "__pycache__", ".venv")
    leftover = [line for line in dirty.splitlines()
                if not any(marker in line for marker in ignored)]
    if leftover:
        raise EnvironmentBlocker(
            "real run requires a clean code worktree: %s"
            % "; ".join(leftover))
    return sha


def _spawn(python_path, extra_args, *, cache, output, snapshot=None):
    script = str(Path(__file__).resolve())
    command = [python_path, script, *extra_args,
               "--cache", str(cache), "--output", str(output)]
    if snapshot is not None:
        command += ["--snapshot", str(snapshot)]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise EnvironmentBlocker(
            "route worker failed: %s" % " ".join(extra_args))


def _write_vectors(path, vectors):
    """vectors: iterable of (key, vector); write canonical JSONL."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for key, vector in vectors:
            handle.write(canonical_json({
                "key": key, "vector": [float(v) for v in vector]}) + "\n")
    tmp.replace(path)
    return path


def _read_vectors(path):
    result = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            result[row["key"]] = tuple(row["vector"])
    return result


def _route_identity(route_id, args, cache):
    """Route fingerprint (pure hashing; spawns in the route's runtime)."""
    if route_id == L28_ROUTE_ID:
        from representations import (CandidateRepresentationSpec,
                                     build_model_token_identity)
        identity = build_model_token_identity(args.qwen_base)
        spec = CandidateRepresentationSpec(
            layer=28, pooling="candidate_span_mean")
        from representations import candidate_representation_id
        representation_id = candidate_representation_id(spec, identity)
        return {
            "route_id": route_id,
            "adapter": "qwen3-hidden",
            "instruction": "none",
            "pooling": "candidate_span_mean",
            "model_digest": identity.model_digest[:16],
            "tokenizer_digest": identity.tokenizer_digest[:16],
            "mlxlm_version": identity.mlxlm_version,
            "hidden_dim": identity.hidden_dim,
            "representation_id": representation_id,
            "vector_dimension": identity.hidden_dim,
        }
    from embeddings import (BGEM3EmbeddingAdapter, Qwen3EmbeddingAdapter,
                            build_embedding_identity)
    if route_id == ROUTE_IDS[0]:
        adapter = Qwen3EmbeddingAdapter(model_path=args.qwen3_embedding_model)
    elif route_id == ROUTE_IDS[2]:
        adapter = BGEM3EmbeddingAdapter(model_path=args.bge_model)
    else:
        raise EnvironmentBlocker("unknown embedding route: %s" % route_id)
    identity = build_embedding_identity(adapter.model_path, adapter.route)
    return {
        "route_id": route_id,
        "adapter": adapter.route.adapter,
        "instruction": adapter.route.instruction or "none",
        "pooling": adapter.route.pooling,
        "model_digest": identity.model_digest,
        "tokenizer_digest": identity.tokenizer_digest,
        "dimension": identity.output_dimension,
        "format": identity.vector_format,
        "metric": identity.metric,
        "dependencies": list(identity.dependency_versions),
        "representation_id": adapter.representation_id,
        "vector_dimension": identity.output_dimension,
    }


class _CachedProvider:
    """Model-free provider over precomputed route vectors (driver side)."""

    def __init__(self, event_vectors, query_vectors, dimension):
        self._events = event_vectors
        self._queries = query_vectors
        self._dimension = dimension

    def vector_dimension(self):
        return self._dimension

    def event_vector(self, event):
        return self._events[event.event_id]

    def query_vector_for_candidate(self, preceding_text, candidate):
        key = "%s\0%s" % (preceding_text, candidate)
        return self._queries[key]


class _FixtureProvider:
    """Deterministic model-free provider for the --fixture smoke run.

    Vectors are a pure function of the route id and the payload hash so the
    smoke run is reproducible without any model; the committed test suite
    (not this path) is the real AC-159 gate.
    """

    DIMENSION = 16

    def __init__(self, route_id):
        self._route_id = route_id
        self._seed = int(sha256_bytes(route_id.encode("utf-8"))[:8], 16)

    def vector_dimension(self):
        return self.DIMENSION

    def _vector(self, key):
        import hashlib
        digest = hashlib.sha256(
            ("%s\0%s" % (self._route_id, key)).encode("utf-8")).digest()
        values = [digest[index % len(digest)] / 255.0
                  for index in range(self.DIMENSION)]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return tuple(v / norm for v in values)

    def event_vector(self, event):
        return self._vector("event:%s" % event.event_id)

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._vector("query:%s\0%s" % (preceding_text, candidate))


def _fixture_provider(events, route_id):
    del events
    return _FixtureProvider(route_id)


def _load_route_vectors(cache, route_id, identity):
    events = _read_vectors(_event_vectors_path(cache, route_id))
    queries = _read_vectors(_query_vectors_path(cache, route_id))
    dimension = identity["vector_dimension"]
    return _CachedProvider(events, queries, dimension)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--artifact-dir", type=Path,
                        default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None,
                        help="worker mode alias for --artifact-dir")
    parser.add_argument("--live-db", default=os.path.expanduser(
        "~/Library/Application Support/Squirrel/SemanticMemory/"
        "facts.sqlite3"))
    parser.add_argument("--status-cli", default=os.path.expanduser(
        "~/Developer/librime-llm-rerank/daemon/squirrel-semantic-memory"))
    parser.add_argument("--qwen-base", default="/Users/habit/Models/Qwen/"
                         "Qwen3-0.6B-Base")
    parser.add_argument("--qwen3-embedding-model", default=_main_path(
        ".local-work", "models", "Qwen3-Embedding-0.6B"))
    parser.add_argument("--bge-model", default=_main_path(
        ".local-work", "models", "BGE-M3"))
    parser.add_argument("--embedding-python", default=_main_path(
        ".local-work", "venv-embeddings", "bin", "python"))
    parser.add_argument("--daemon-python", default=_main_path(
        "daemon", ".venv", "bin", "python"))
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--replicates", type=int, default=BOOTSTRAP_REPLICATES)
    parser.add_argument("--snapshot", default=None,
                        help="reuse an existing frozen snapshot (path)")
    parser.add_argument("--max-cells", type=int, default=None)
    parser.add_argument("--fixture", action="store_true",
                        help="model-free smoke run: synthetic deterministic "
                             "vectors, no model workers (driver wiring only; "
                             "the committed test suite is the real gate)")
    # Worker modes (spawned by the driver).
    parser.add_argument("--identity", type=str, choices=ROUTE_IDS,
                        default=None)
    parser.add_argument("--score-route", type=str, choices=ROUTE_IDS,
                        default=None)
    return parser.parse_args(argv)


def _main_driver(args):
    work_dir = args.work_dir or (Path(__file__).resolve().parents[1]
                                 / ".local-work" / "suffix-wf")
    work_dir.mkdir(parents=True, exist_ok=True)
    cache = _cache_dir(args.cache if args.cache is not None
                       else (work_dir / "cache"))
    output = args.artifact_dir
    output.mkdir(parents=True, exist_ok=True)

    code_sha = current_code_sha(require_clean=True)

    # -- frozen snapshot (new Online Backup copy at claim) ----------------
    if args.snapshot:
        snapshot_path = Path(args.snapshot)
        if not snapshot_path.is_file():
            raise EnvironmentBlocker(
                "snapshot not found: %s" % snapshot_path)
        snapshot = {
            "path": os.path.abspath(args.snapshot),
            "sha256": sha256_bytes(snapshot_path.read_bytes()),
            "identity": _open_meta(snapshot_path),
            "status": {"status_check": "skipped"},
            "source": "provided_frozen_snapshot",
        }
        snapshot_path = snapshot["path"]
    else:
        if not os.path.isfile(args.live_db):
            raise EnvironmentBlocker(
                "missing live facts store; a claim-time snapshot is "
                "required (SN-159-1): %s" % args.live_db)
        snapshot = take_snapshot(args.live_db, str(work_dir),
                                 status_cli=args.status_cli
                                 if os.path.isfile(args.status_cli) else None)
        snapshot["source"] = "claim_time_online_backup"
        snapshot_path = snapshot["path"]
    print("snapshot sha256: %s" % snapshot["sha256"], flush=True)

    facts = FrozenFacts(snapshot_path)
    try:
        events = facts.events()
        targets = [e for e in events if not e.retracted]
        prefix_targets, suffix_targets = prefix_suffix_split(targets)
        if not suffix_targets:
            # 数据不足 (legal terminal): no suffix events past the cutoff.
            decision = {
                "outcome": "数据不足",
                "reason": ("snapshot has no events past the frozen cutoff "
                           "[%s,%s]: the suffix claim set is empty"
                           % PREFIX_HLC_MAX_INCLUSIVE),
                "data": {
                    "prefix": facts_only_data_count(prefix_targets),
                    "suffix": facts_only_data_count(suffix_targets),
                },
                "per_route": [],
                "total_eligible_cells": 0,
                "live_gamma": 0.0,
            }
            _write_report(snapshot, [], decision, {}, decision["data"],
                          prefix_targets,
                          suffix_targets, code_sha, args, cache, output)
            return 0

        # -- route identities (in-venv; frozen BEFORE any score) ----------
        if args.fixture:
            identities = {route_id: {
                "route_id": route_id,
                "adapter": "fixture",
                "instruction": "none",
                "pooling": "fixture",
                "representation_id": "fixture:%s" % route_id,
                "vector_dimension": _FixtureProvider.DIMENSION,
            } for route_id in ROUTE_IDS}
        else:
            for route_id in ROUTE_IDS:
                spawn_python = (args.embedding_python
                                if route_id != L28_ROUTE_ID
                                else args.daemon_python)
                if not os.path.isfile(spawn_python):
                    raise EnvironmentBlocker(
                        "missing runtime %s for route %s"
                        % (spawn_python, route_id))
                _spawn(spawn_python, ["--identity", route_id],
                       cache=cache, output=output)
            identities = {route_id: json.loads(
                _identity_path(cache, route_id).read_text(encoding="utf-8"))
                for route_id in ROUTE_IDS}
        for route_id in ROUTE_IDS:
            if identities[route_id]["route_id"] != route_id:
                raise EnvironmentBlocker("identity drifted for %s" % route_id)

        # -- facts-only calibration invariant (AC-159-4) ------------------
        # The hard-negative query count is a pure fact of the prefix.  #158
        # established that this new cutoff is calibratable; a lower count is
        # an implementation fault, not a legal AC-159 terminal.
        hn_count = prefix_hard_negative_query_count(facts, prefix_targets)
        if hn_count < MIN_HARD_NEGATIVE_QUERIES:
            raise ContractFailure(
                "prefix hard-negative recomputation returned %d < %d; "
                "AC-159 expects the #158-calibratable prefix"
                % (hn_count, MIN_HARD_NEGATIVE_QUERIES))

        # -- freeze BEFORE any score --------------------------------------
        freeze = _build_freeze(code_sha, snapshot, identities, args)
        frozen_path = output / FREEZE_NAME
        if frozen_path.exists():
            existing = json.loads(frozen_path.read_text(encoding="utf-8"))
            if existing.get("code_sha") != code_sha:
                frozen_path.unlink()  # stale code -> rebuild
            elif existing != freeze:
                raise EnvironmentBlocker(
                    "existing freeze does not match the reconstituted "
                    "identity (code/snapshot/grid drift)")
        tmp_path = frozen_path.with_suffix(frozen_path.suffix + ".tmp")
        tmp_path.write_text(canonical_json(freeze) + "\n", encoding="utf-8")
        tmp_path.replace(frozen_path)

        # -- per-route vector workers (exclusive GPU/MLX, one at a time) --
        providers = {}
        for route_id in ROUTE_IDS:
            if args.fixture:
                provider = _fixture_provider(events, route_id)
            else:
                spawn_python = (args.embedding_python
                                if route_id != L28_ROUTE_ID
                                else args.daemon_python)
                _spawn(spawn_python, ["--score-route", route_id],
                       cache=cache, output=output, snapshot=snapshot_path)
                provider = _load_route_vectors(
                    cache, route_id, identities[route_id])
            providers[route_id] = provider

        # -- replay + calibration + grid -----------------------------------
        matrix = []
        data_by_route = {}
        for route_id in ROUTE_IDS:
            provider = providers[route_id]
            vectors = CandidateVectorTable(events, provider)
            replay = WalkForwardReplay(facts, vectors)
            tau_status = calibrate_tau(replay, prefix_targets)
            if tau_status.get("state") != "calibratable":
                raise ContractFailure(
                    "route %s calibration returned %s despite facts-only "
                    "count %d >= %d"
                    % (route_id, tau_status.get("state"), hn_count,
                       MIN_HARD_NEGATIVE_QUERIES))
            reference = replay.replay(_reference_params(), 0.0)
            prefix_ref = [o for o in reference if o.in_prefix]
            suffix_ref = [o for o in reference if not o.in_prefix]
            data_by_route[route_id] = {
                "prefix": data_counts(prefix_ref),
                "suffix": data_counts(suffix_ref),
            }
            margin_p10, _n = margin_base_prefix(prefix_ref)
            route_result = run_route(
                replay, route_id, tau_status, data_by_route[route_id],
                seed=args.seed, replicates=args.replicates,
                max_cells=args.max_cells, margin_p10=margin_p10)
            matrix.append(route_result)
        data = {
            "prefix": data_by_route[ROUTE_IDS[0]]["prefix"],
            "suffix": data_by_route[ROUTE_IDS[0]]["suffix"],
        }
        decision = assemble_shortlist(matrix, data)
        if args.max_cells is not None:
            decision["partial_scan"] = True
        _write_report(snapshot, matrix, decision, data_by_route, data,
                      prefix_targets, suffix_targets, code_sha, args,
                      cache, output)
        print("terminal outcome: %s" % decision["outcome"], flush=True)
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


def _reference_params():
    from oracle import OracleParams
    return OracleParams(tau=0.0, k_evidence=8, half_life=float("inf"),
                        saturation_k=1.0)


def _build_freeze(code_sha, snapshot, identities, args):
    return {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "snapshot_sha256": snapshot["sha256"],
        "snapshot_source": snapshot.get("source", "claim_time_online_backup"),
        "grid_manifest": grid_manifest(args.replicates),
        "seed": args.seed,
        "routes": {route_id: identities[route_id]
                   for route_id in ROUTE_IDS},
    }


def _write_report(snapshot, matrix, decision, data_by_route, data,
                  prefix_targets, suffix_targets, code_sha, args,
                  cache, output):
    report = build_report(
        engine_version=ENGINE_VERSION,
        code_sha=code_sha,
        snapshot=snapshot,
        prefix_events=prefix_targets,
        suffix_events=suffix_targets,
        route_results=matrix,
        decision=decision,
        data=data,
        tau_status=[{"route_id": r["route_id"], "tau": r.get("tau")}
                    for r in matrix],
        margin_base={"note": "prefix events where the shadow baseline "
                             "already ranked the final selection first "
                             "(reconstructed base-proxy rank gap)"},
        grid_manifest=grid_manifest(args.replicates),
        seed=args.seed,
        replicates=args.replicates,
        public_b_unused=True,
        personal_r_unused=True,
        live_gamma=0.0,
        report_notes=[
            "public-B accuracy (11953/14725) was never read into the "
            "selection or the terminal decision (AC-159-6)",
            "the personal 2x2 r was never read into the selection, "
            "tie-breaking or suffix-rank interpretation (AC-159-6)",
            "live gamma is unchanged at 0 (AC-159-7)",
        ],
        decisions=[
            "d1 split: the snapshot is the claim-time Online Backup copy; "
            "prefix = hlc <= [1787667799562,0] (inclusive), suffix = the "
            "claim set; selection uses the prefix only, claims use the "
            "suffix only (AC-159-2)",
            "d2 payload: last64(preceding)+candidate, no separator; the "
            "query side uses the frozen Qwen3-emb instruction only for "
            "dedicated_qwen3_embedding_0_6b; document/history side never "
            "applies an instruction (AC-159-1)",
            "d3 L28 pools the candidate token span [start, start+count) "
            "via candidate_span_mean; whole-payload pooling would be a "
            "contract failure (AC-159-1)",
            "d4 rank denominator: saved same-group competition size < 32 "
            "(group-complete), never the persisted competition_complete "
            "bit (issue #159 body)",
            "d5 τ: per route only from prefix query-level hard negatives, "
            ">= 200 queries, Q95/Q97.5/Q99/Q99.5; below 200 the route is "
            "not_calibratable and leaves the shortlist (AC-159-4)",
            "d6 grid: H {8,32,128,512,inf} x K {8,16,32,64} x gamma "
            "{0.5,1,2,4} x k {1,3,7}, alpha=0; no extra cells, no "
            "continuous optimizer (AC-159-4)",
            "d7 bootstrap: key-clustered (choice-problem key), fixed seed, "
            ">= 10000 replicates, 95% CI; differences paired per event "
            "(issue #159 body)",
            "d8 cross-route metrics use the common actionable union; an "
            "event without evidence for a route scores as that route's "
            "shadow baseline (issue #159 body)",
            "d9 Δ₁ = gamma/(1+k) <= min(0.5, P10(margin_base)) with "
            "margin_base from the prefix: real snapshots do not persist "
            "base scores, the engine records the reconstructed rank gap "
            "and enforces the hard cap",
            "d10 prefix selection: per route, select the family with the "
            "best prefix top-1, then MRR, then actionable count; retain all "
            "H variants so suffix gates cannot influence selection",
            "d11 terminals: exact shortlist / 收窄声称 shortlist / "
            "无合格方案 / 数据不足; ties are reported, never broken by "
            "model name; no ANN, no production winner (issue #159 body)",
        ])
    verify_privacy(report)
    (output / REPORT_JSON_NAME).write_text(
        canonical_json(report) + "\n", encoding="utf-8")
    (output / REPORT_MD_NAME).write_text(
        render_markdown(report), encoding="utf-8")
    print("report written: %s/%s" % (output, REPORT_JSON_NAME), flush=True)
    print("report sha256: %s" % report["report_sha256"], flush=True)


def _score_embedding_route(route_id, args):
    from embeddings import (BGEM3EmbeddingAdapter, Qwen3EmbeddingAdapter,
                            QWEN3_QUERY_INSTRUCTION)
    import numpy as np
    import torch

    if route_id == ROUTE_IDS[0]:
        model_path = args.qwen3_embedding_model
        adapter_cls = Qwen3EmbeddingAdapter
        use_instruction = True
    else:
        model_path = args.bge_model
        adapter_cls = BGEM3EmbeddingAdapter
        use_instruction = False
    if not os.path.isdir(model_path):
        raise EnvironmentBlocker("missing embedding model: %s" % model_path)
    adapter = adapter_cls(model_path=model_path)
    adapter.load()
    model = adapter._model
    tokenizer = adapter._tokenizer
    pooling = adapter.route.pooling
    device = torch.device("mps" if torch.backends.mps.is_available()
                          else "cpu")
    model.to(device)
    model.eval()
    del adapter

    cache_dir = _cache_dir(args.cache if args.cache is not None
                           else Path(__file__).resolve().parent / ".cache" /
                           "suffix_walkforward")

    def encode_texts(texts, batch_size=32):
        vectors = []
        for offset in range(0, len(texts), batch_size):
            chunk = texts[offset:offset + batch_size]
            encoded = tokenizer(
                chunk, return_tensors="pt", padding=True,
                add_special_tokens=False)
            encoded = {key: value.to(device)
                       for key, value in encoded.items()}
            with torch.no_grad():
                hidden = model(**encoded)
                hidden = hidden.last_hidden_state.float()
                mask = encoded["attention_mask"]
                if pooling == "last-token":
                    last = mask.sum(dim=1) - 1
                    last = torch.clamp(last, min=0)
                    rows = hidden[torch.arange(hidden.size(0),
                                               device=hidden.device), last]
                else:
                    denom = mask.sum(dim=1).clamp(min=1).unsqueeze(-1)
                    rows = (hidden * mask.unsqueeze(-1)).sum(dim=1) / denom
                rows = torch.nn.functional.normalize(rows, p=2, dim=1)
            active = mask.sum(dim=1).cpu().tolist()
            cpu = rows.cpu().numpy()
            for index, count in enumerate(active):
                vector = cpu[index]
                if not np.all(np.isfinite(vector)):
                    raise EnvironmentBlocker("non-finite embedding produced")
                vectors.append(vector)
        return vectors

    from representations import candidate_conditioned_payload

    snapshot_path = _freeze_snapshot_path(args)
    facts = FrozenFacts(snapshot_path)
    try:
        events = facts.events()
        targets = [e for e in events if not e.retracted]
        pairs = needed_query_pairs(facts, targets)
        # Event (document) side: no instruction.
        event_texts = [candidate_conditioned_payload(
            e.preceding_text, e.final_selection_text) for e in events]
        event_vectors = encode_texts(event_texts)
        # Query side: instruction only for the Qwen3-emb route.
        pair_keys = []
        query_texts = []
        for preceding, candidate in pairs:
            payload = candidate_conditioned_payload(preceding, candidate)
            if use_instruction:
                query_texts.append(QWEN3_QUERY_INSTRUCTION + "\n" + payload)
            else:
                query_texts.append(payload)
            pair_keys.append("%s\0%s" % (preceding, candidate))
        query_vectors = encode_texts(query_texts) if query_texts else []
        _write_vectors(_event_vectors_path(cache_dir, route_id),
                       zip((e.event_id for e in events), event_vectors))
        _write_vectors(_query_vectors_path(cache_dir, route_id),
                       zip(pair_keys, query_vectors))
        print("route %s done: %d events, %d queries"
              % (route_id, len(events), len(pairs)), flush=True)
    finally:
        facts.close()
    return 0


def _score_l28_route(args):
    from hidden_state import _lazy_mlx, pool_candidate_hidden_states
    from representations import (CandidateRepresentationSpec,
                                 candidate_tokenization_for)
    import numpy as np

    if not os.path.isdir(args.qwen_base):
        raise EnvironmentBlocker("missing mlx model: %s" % args.qwen_base)
    mx, create_attention_mask, _unused = _lazy_mlx()
    del _unused

    class _State:
        def __init__(self, path):
            self.model_path = path
            self.model = None
            self.tokenizer = None

        def load(self):
            if self.model is not None:
                return
            from mlx_lm.utils import load
            self.model, self.tokenizer = load(self.model_path)
            mx.eval(self.model.parameters())

    state = _State(args.qwen_base)
    state.load()
    tokenizer = state.tokenizer
    inner = (state.model.model if hasattr(state.model, "model")
             else state.model)
    embed = getattr(inner, "embed_tokens", None)
    layers = getattr(inner, "layers", None)
    norm = getattr(inner, "norm", None)
    if embed is None or layers is None or norm is None:
        raise EnvironmentBlocker("model is not the expected Qwen3 shape")
    del state

    spec = CandidateRepresentationSpec(
        layer=28, pooling="candidate_span_mean")

    def l28_vector(preceding, candidate):
        """L28 candidate-span-mean vector (frozen span attribution)."""
        payload, ids, start, count = candidate_tokenization_for(
            tokenizer, preceding, candidate, spec=spec)
        del payload
        ids = list(ids)
        hidden = embed(mx.array([ids]))
        mask = create_attention_mask(hidden, None)
        for index, layer in enumerate(layers):
            hidden = layer(hidden, mask, None)
            if index + 1 == 28:
                normalized = norm(hidden).astype(mx.float32)
                span = np.asarray(
                    normalized[0, start:start + count]).reshape(count, -1)
                vector = pool_candidate_hidden_states(
                    span.tolist(), 0, count, "candidate_span_mean")
                return vector
        raise EnvironmentBlocker("L28 was not reached")

    cache_dir = _cache_dir(args.cache if args.cache is not None
                           else Path(__file__).resolve().parent / ".cache" /
                           "suffix_walkforward")

    snapshot_path = _freeze_snapshot_path(args)
    facts = FrozenFacts(snapshot_path)
    try:
        events = facts.events()
        targets = [e for e in events if not e.retracted]
        pairs = needed_query_pairs(facts, targets)
        event_vectors = []
        for event in events:
            event_vectors.append(l28_vector(
                event.preceding_text, event.final_selection_text))
        _write_vectors(_event_vectors_path(cache_dir, L28_ROUTE_ID),
                       zip((e.event_id for e in events), event_vectors))
        query_rows = []
        for preceding, candidate in pairs:
            query_rows.append(l28_vector(preceding, candidate))
        _write_vectors(_query_vectors_path(cache_dir, L28_ROUTE_ID),
                       zip(("%s\0%s" % pair for pair in pairs), query_rows))
        print("route %s done: %d events, %d queries"
              % (L28_ROUTE_ID, len(events), len(pairs)), flush=True)
    finally:
        facts.close()
    return 0


def _freeze_snapshot_path(args):
    if args.snapshot:
        return str(args.snapshot)
    # The claim-time snapshot lives under the work dir (take_snapshot
    # writes facts-snapshot-*.sqlite3 there) or the default local dir.
    candidates = [args.work_dir, DEFAULT_ARTIFACT_DIR,
                  Path(__file__).resolve().parents[1] / ".local-work" /
                  "suffix-wf"]
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        matches = sorted(path.glob("facts-snapshot-*.sqlite3"))
        if matches:
            return str(matches[-1])
    raise EnvironmentBlocker(
        "claim-time snapshot not found; run the driver (which takes the "
        "Online Backup copy) before spawning score workers")


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.identity:
        cache = _cache_dir(args.cache if args.cache is not None
                           else (Path(__file__).resolve().parents[1] /
                                 ".local-work" / "suffix-wf" / "cache"))
        identity = _route_identity(args.identity, args, cache)
        _identity_path(cache, args.identity).write_text(
            canonical_json(identity) + "\n", encoding="utf-8")
        print(canonical_json(identity), flush=True)
        return 0
    if args.score_route:
        if args.score_route == L28_ROUTE_ID:
            return _score_l28_route(args)
        return _score_embedding_route(args.score_route, args)
    return _main_driver(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ContractFailure as error:
        print("contract failure:", error, file=sys.stderr)
        sys.exit(4)
    except EnvironmentBlocker as error:
        print("environment blocker:", error, file=sys.stderr)
        sys.exit(3)
