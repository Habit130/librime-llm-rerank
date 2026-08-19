#!/usr/bin/env python3
"""Walk-forward evaluation driver (Habit130/squirrel#70/#77).

Usage:

    python3 eval/run_walkforward.py \
        --live-db <live facts.sqlite3> \
        --status-cli <squirrel-semantic-memory> \
        --work-dir <local dir for the snapshot copy + report> \
        --model <Qwen model dir> \
        [--fixture] [--seed 20260817] [--replicates 10000]

Modes:

- ``--fixture``: model-free gate over synthetic facts with the fixture
  provider (the committed ``test_*`` suite covers the full gate; this flag
  is for a quick smoke run of the driver itself).
- real mode (default): loads the Qwen3-0.6B-Base model via the daemon's
  #60 extractor, takes a frozen snapshot with the Online Backup API (live
  recorder undisturbed, SCN-70-7), replays all four first-round
  representations over the pre-declared grid at α=0 (AC-106-v2), applies
  the AC-77-v1 hard gates on the group-complete denominator, and writes
  the desensitized diagnostic report (JSON + Markdown) into ``--work-dir``.

The report never contains raw preceding text, candidate text or traces:
only ids, hashes, numbers and counts.  Nothing here writes the live store,
restarts the daemon, or touches ``~/Library/Rime``.  The terminal outcome
is one of: exact quality shortlist / 收窄声称 shortlist / 仅安全、涨幅未测准 /
无合格方案 (AC-77-v1 seam 11).  Live ``γ`` stays 0.
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from walkforward import (  # noqa: E402
    BOOTSTRAP_SEED, ENGINE_VERSION, FrozenFacts, VectorTable,
    WalkForwardReplay)
from snapshot import take_snapshot  # noqa: E402
from report import build_report, render_markdown  # noqa: E402
from grid import data_counts, run_representation, start_gate_passed  # noqa: E402
from shortlist import assemble_shortlist  # noqa: E402


# #69 fixed-benchmark gate state, quoted from the #69 acceptance record
# (Habit130/squirrel#69, AC-69-v1, finding F1).  Quoted verbatim, not
# re-adjudicated: all four first-round representations fail both 95% gates
# at the benchmark parameters (tau=0.90, K=8; benchmark-only values).
BENCHMARK_69_REFERENCE = {
    "source": "Habit130/squirrel#69 AC-69-v1 acceptance record, finding F1",
    "benchmark_params": {"tau": 0.90, "k_evidence": 8, "half_life": "inf",
                         "saturation_k": 1.0},
    "gates": {"positive": ">=95%", "hard_negative": ">=95%"},
    "real_model_measurements": {
        "exact_l14": {"positive": "24/100 (24%)",
                      "hard_negative_no_evidence": "39/100 (39%)"},
        "exact_l21": {"positive": "22/100 (22%)",
                      "hard_negative_no_evidence": "42/100 (42%)"},
        "exact_l28": {"positive": "48/100 (48%)",
                      "hard_negative_no_evidence": "30/100 (30%)"},
        "split_l28": {"positive": "46/100 (46%)",
                      "hard_negative_no_evidence": "30/100 (30%)"},
    },
    "gate_state": "all four first-round representations fail both 95% gates "
                  "(best positive 48% exact_l28/split_l28; best negative "
                  "no-evidence 42% exact_l21)",
    "decision": "owner decided to proceed with #70 as planned; this report "
                "quotes the state and does not re-adjudicate it",
}

# Engine decision record (delivery contracts AC-70-v1 / AC-77-v1).
DECISION_RECORD = [
    "D1 walk-forward order: targets replay in strict HLC total order; each "
    "query's as_of is the event's commit HLC and the whole commit is "
    "excluded, so scoring always happens before the target enters memory "
    "(score first, then add to memory). Retractions apply as-of: an event "
    "is visible until its commit's retraction HLC; future retractions never "
    "backfill an earlier replay (SCN-70-1).",
    "D2 baseline outcome: the live system recorded events under the frozen "
    "γ=0 baseline (evidence explicitly disabled), so the shadow-baseline "
    "outcome for the user's final selection is observed ground truth = the "
    "recorded confirmation position; rank 1 iff display_page==1 and "
    "display_rank==1. No base scores are reconstructed (facts do not "
    "persist per-candidate base scores).",
    "D3 scheme outcome: the scheme re-ranks the recorded competition set "
    "under base_proxy + gamma*s_c, where base_proxy is a deterministic "
    "reconstruction of the (unavailable) per-candidate base scores from "
    "the facts: the recorded confirmation position of the user's final "
    "selection (display_page/display_rank) is the frozen baseline's rank "
    "of that selection, so the reconstruction pins the selection there and "
    "keeps the remaining candidates in recorded (merge) order around it. "
    "At γ=0 the scheme ranking is exactly the recorded confirmation "
    "position for every event (fixture-tested identity, including rank>1 "
    "events), so γ=0 reproduces the shadow baseline; the report carries "
    "the recorded-order-vs-confirmation-rank agreement as a diagnostic of "
    "the reconstruction's fidelity. Events on page > 1 (absolute rank "
    "depends on the page size the facts do not record) are excluded from "
    "scheme ranking and reported in the fidelity diagnostic.",
    "D4 Δ₁ margin_base: P10(margin_base) needs per-candidate base scores "
    "which the fact schema does not store; the engine reports "
    "'margin_base unavailable' (mirroring the τ not-calibratable handling) "
    "and enforces the Δ₁ <= 0.5 hard cap. Synthetic fixtures inject base "
    "scores and pin the full Δ₁ boundary in the test suite.",
    "D5 τ: per representation_id, only from the development prefix "
    "(earliest 70% of replayable targets); a query's hard-negative value is "
    "the max cosine to same-key history with a different final selection; "
    ">=200 queries are required before calibration; candidates are "
    "Q95/Q97.5/Q99/Q99.5 nearest-rank quantiles. Below 200 the state is "
    "'not_calibratable' and no τ is invented.",
    "D6 no continuous optimizer: the scan is a flat pre-declared product "
    "grid (representations x H x K x gamma x k, τ per representation). "
    "α is frozen at 0 (AC-106-v2); grid cells do not vary α. "
    "Finite-H gates compare paired differences on the common actionable "
    "union with key-clustered bootstrap (fixed seed, >=10000 replicates, "
    "95% CI).",
    "D7 (superseded by AC-77-v1): the #70 selection-milestone gates "
    "(1000 actionable-complete / 100 keys / 200 explicit_indexed / 200 "
    "rank>1) are no longer a start gate.  The #76 start gate is "
    "group-complete replayable >= 1000 and >= 100 choice-problem keys; the "
    "milestone counts are claim/stratum rules only.",
    "D8 snapshot: SQLite Online Backup API copy (SCN-70-7); live status "
    "watermark captured before and after, gap state must be 'none' and the "
    "high-water monotonic; the copy is integrity-checked and SHA-256 "
    "fingerprinted; the live store, daemon, ~/Library/Rime and the librime "
    "build tree are untouched.",
    "D9 group-complete gate (AC-77-v1 seam 3): an event enters the top-1 / "
    "MRR / mispromotion / safety / pollution / event-count gates iff its "
    "saved same-group competition size < N (N=32).  The persisted "
    "competition_complete bit is NOT the gate — it is reported as a "
    "diagnostic only.  A size-32 event with bit=true is out; a size-10 "
    "event with bit=false is in.",
    "D10 terminal outcome (AC-77-v1 seam 11): exactly one of "
    "exact quality shortlist / 收窄声称 shortlist / 仅安全、涨幅未测准 / "
    "无合格方案 is emitted by shortlist.py.  No ANN, no production winner, "
    "no live γ enable; #43 「唯一方案选择」 is deferred to #80.",
    "D11 #69 fixed-benchmark elimination (quoted F1): all four first-round "
    "representations fail both 95% gates at the benchmark parameters "
    "(tau=0.90, K=8).  A representation that failed the fixed benchmark "
    "cannot enter the exact quality shortlist; its walk-forward still runs "
    "and is reported as a diagnostic.  This report quotes the state and "
    "does not re-adjudicate it.",
]


def real_providers(model_path):
    """The four first-round representations behind #60 hidden-state vectors.

    Returns (providers, identity) where identity is the #60
    ModelTokenIdentity (model/tokenizer digests, mlx-lm version, hidden
    dim) the report fingerprints.
    """
    from representations import first_round_specs
    from hidden_state import HiddenStateExtractor, \
        HiddenStateRepresentationProvider
    from server import ModelState

    state = ModelState(model_path)
    extractor = HiddenStateExtractor(state)
    providers = {}
    for spec in first_round_specs():
        providers[spec.short_name] = HiddenStateRepresentationProvider(
            extractor, spec)
    return providers, extractor.identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-db", default=os.path.expanduser(
        "~/Library/Application Support/Squirrel/SemanticMemory/"
        "facts.sqlite3"))
    parser.add_argument("--status-cli", default=os.path.expanduser(
        "~/Developer/librime-llm-rerank/daemon/squirrel-semantic-memory"))
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--model", default="/Users/habit/Models/Qwen/"
                        "Qwen3-0.6B-Base")
    parser.add_argument("--fixture", action="store_true",
                        help="model-free smoke run with the fixture provider")
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--replicates", type=int, default=10000)
    parser.add_argument("--max-cells", type=int, default=None,
                        help="limit grid cells (driver smoke only)")
    parser.add_argument("--snapshot", default=None,
                        help="reuse an existing frozen snapshot (path); "
                             "defaults to taking a fresh one")
    args = parser.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)

    # -- frozen snapshot (SCN-70-7) -----------------------------------------
    if args.snapshot:
        if not os.path.isfile(args.snapshot):
            sys.exit("error: snapshot not found: %s" % args.snapshot)
        from snapshot import sha256_file
        import sqlite3
        conn = sqlite3.connect(args.snapshot)
        try:
            identity = dict(conn.execute("SELECT key, value FROM meta"))
        finally:
            conn.close()
        snapshot = {
            "path": os.path.abspath(args.snapshot),
            "sha256": sha256_file(args.snapshot),
            "identity": identity,
            "status": {"status_check": "skipped"},
        }
    else:
        snapshot = take_snapshot(args.live_db, args.work_dir,
                                 status_cli=args.status_cli)
    print("snapshot sha256: %s" % snapshot["sha256"])

    # -- representation providers -------------------------------------------
    if args.fixture:
        from evidence import FixtureRepresentationProvider
        providers = {
            "fixture": FixtureRepresentationProvider(
                "fixture:driver-smoke",
                {}, {}),
        }
        model_identity = None
    else:
        providers, model_identity = real_providers(args.model)

    # -- replay + grid -------------------------------------------------------
    facts = FrozenFacts(snapshot["path"])
    try:
        grid_results = []
        replay_summary = None
        for name, provider in providers.items():
            vectors = VectorTable(facts.events(), provider)
            replay = WalkForwardReplay(facts, vectors)
            if replay_summary is None:
                from walkforward import OracleParams
                _, replay_summary = replay.replay(
                    OracleParams(tau=0.0, k_evidence=8,
                                 half_life=float("inf"), saturation_k=1.0),
                    gamma=0.0)
            result = run_representation(replay, name, args.seed,
                                        replicates=args.replicates)
            if args.max_cells is not None:
                result["cells"] = result["cells"][:args.max_cells]
            # Strip the internal per-cell outcome lists (bulky; the report
            # carries ids and numbers only, never raw text, but per-event
            # outcome lists belong in the local package, not the digest).
            for cell_record in result["cells"]:
                cell_record.pop("outcomes", None)
            grid_results.append(result)
    finally:
        facts.close()

    # -- data state + terminal decision (AC-77-v1) ---------------------------
    data = grid_results[0]["data"] if grid_results else {}
    start_ok = start_gate_passed(data)
    # The #69 fixed-benchmark record (quoted F1) uses the short names
    # (exact_l14 / exact_l21 / exact_l28 / split_l28); the engine's
    # representation ids carry the "_last" pooling suffix
    # (exact_l14_last / ... / split_l28_last).  All four first-round
    # representations fail the fixed benchmark (quoted F1, not
    # re-adjudicated): positive 24/22/48/46% (need >=95%), hard-negative
    # no-evidence 39/42/30/30% (need >=95%).  Map the short names onto the
    # scanned ids so the elimination is exact; any representation not in
    # the #69 record is NOT marked failed.
    benchmark_69_short = set(BENCHMARK_69_REFERENCE["real_model_measurements"])
    benchmark_fail = set()
    for grid_result in grid_results:
        name = grid_result["representation"]
        if name in benchmark_69_short or name.rsplit("_", 1)[0] in \
                benchmark_69_short:
            benchmark_fail.add(name)
    decision = assemble_shortlist(grid_results, data, benchmark_fail)
    if not start_ok:
        # The #76 start gate did not pass on this snapshot: the milestone
        # run cannot form a shortlist.  Emit 无合格方案 with the rerun
        # milestones (live γ stays 0).
        decision["outcome"] = "无合格方案"
        decision["start_gate_passed"] = False
        decision["start_gate_reason"] = (
            "group-complete replayable %d (need >=1000) and/or keys %d "
            "(need >=100)" % (data.get("group_complete", 0),
                              data.get("keys", 0)))
    else:
        decision["start_gate_passed"] = True

    # -- report ---------------------------------------------------------------
    tau_status = {r["representation"]: r["tau"] for r in grid_results}
    extra = {}
    if model_identity is not None:
        from report import model_summary
        extra["model"] = model_summary(model_identity)
    # Pre-declared grid manifest (AC-77 seam 5): the frozen candidate space
    # written before metrics — no extra cells, no continuous optimizer.
    from grid import (GAMMAS, HALF_LIVES, K_EVIDENCE, SATURATION_KS,
                      predeclared_cells)
    extra["grid_manifest"] = {
        "declared_before_metrics": True,
        "alpha": 0.0,  # AC-106-v2: frozen offline baseline; no α grid
        "half_lives": [("inf" if h == float("inf") else h)
                       for h in HALF_LIVES],
        "k_evidence": list(K_EVIDENCE),
        "gamma": list(GAMMAS),
        "saturation_k": list(SATURATION_KS),
        "tau_quantiles": ["Q95", "Q97.5", "Q99", "Q99.5"],
        "cells_per_representation": len(predeclared_cells("x")),
    }
    report = build_report(
        ENGINE_VERSION, snapshot, replay_summary, tau_status, grid_results,
        decision, BENCHMARK_69_REFERENCE, DECISION_RECORD,
        seed=args.seed, extra=extra)
    report_path = os.path.join(args.work_dir, "diagnostic-report.json")
    markdown_path = os.path.join(args.work_dir, "diagnostic-report.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    print("report written: %s" % report_path)
    print("report sha256: %s" % report["report_sha256"])
    print("terminal outcome: %s" % decision["outcome"])
    print("group-complete: %d / keys: %d / actionable gc: %d"
          % (data.get("group_complete", 0), data.get("keys", 0),
             data.get("actionable_group_complete", 0)))
    print("tau state: %s" % {k: v["state"] for k, v in tau_status.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
