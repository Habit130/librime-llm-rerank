#!/usr/bin/env python3
"""Walk-forward evaluation driver (Habit130/squirrel#70).

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
  representations over the pre-declared grid, and writes the desensitized
  diagnostic report (JSON + Markdown) into ``--work-dir``.

The report never contains raw preceding text, candidate text or traces:
only ids, hashes, numbers and counts.  Nothing here writes the live store,
restarts the daemon, or touches ``~/Library/Rime``.
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
from grid import run_representation  # noqa: E402


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

# Engine decision record (delivery contract AC-70-v1).
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
    "Finite-H gates compare paired differences on the common actionable "
    "union with key-clustered bootstrap (fixed seed, >=10000 replicates, "
    "95% CI).",
    "D7 selection milestones: at the current sample size the report is a "
    "diagnostic only ('诊断报告,不选方案'); the earliest selection needs "
    ">=1000 actionable complete-competition events, >=100 keys, >=200 "
    "explicit_indexed and >=200 confirmation-rank >1 events.",
    "D8 snapshot: SQLite Online Backup API copy (SCN-70-7); live status "
    "watermark captured before and after, gap state must be 'none' and the "
    "high-water monotonic; the copy is integrity-checked and SHA-256 "
    "fingerprinted; the live store, daemon, ~/Library/Rime and the librime "
    "build tree are untouched.",
]


def real_providers(model_path):
    """The four first-round representations behind #60 hidden-state vectors."""
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
    return providers


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
    args = parser.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)

    # -- frozen snapshot (SCN-70-7) -----------------------------------------
    snapshot = take_snapshot(args.live_db, args.work_dir,
                             status_cli=args.status_cli)

    # -- representation providers -------------------------------------------
    if args.fixture:
        from evidence import FixtureRepresentationProvider
        providers = {
            "fixture": FixtureRepresentationProvider(
                "fixture:driver-smoke",
                {}, {}),
        }
    else:
        providers = real_providers(args.model)

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

    # -- milestone (overall diagnostic state) --------------------------------
    milestone = grid_results[0]["milestone"] if grid_results else {
        "state": "diagnostic", "reason": "no representations"}

    # -- report ---------------------------------------------------------------
    tau_status = {r["representation"]: r["tau"] for r in grid_results}
    report = build_report(
        ENGINE_VERSION, snapshot, replay_summary, tau_status, grid_results,
        milestone, BENCHMARK_69_REFERENCE, DECISION_RECORD,
        seed=args.seed)
    report_path = os.path.join(args.work_dir, "diagnostic-report.json")
    markdown_path = os.path.join(args.work_dir, "diagnostic-report.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    print("report written: %s" % report_path)
    print("report sha256: %s" % report["report_sha256"])
    print("milestone: %s (%s)" % (milestone["state"], milestone["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
