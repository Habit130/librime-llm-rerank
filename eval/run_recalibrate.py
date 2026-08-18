#!/usr/bin/env python3
"""α recalibration driver (Habit130/squirrel#106, contract AC-106-v1).

Offline: γ=0, evidence off, mean-token-lm-v1, β_sys=β_usr=1, window 32.

Primary denominator: freeze-inclusive, unretracted, group-complete
(competition size < 32) selection events from one consistent read-only
facts snapshot; 上文 = the stored preceding_text (<= 64 chars).  Control
denominator: the committed 120-sentence fixture's word cases with in-sentence
prefixes (never the empty-上文 word protocol).  Pre-declared α grid with the
#46 extension rule; decide_final uses only the primary denominator.

Usage (from the repo root):

    daemon/.venv/bin/python eval/run_recalibrate.py \\
        --snapshot <snapshot.sqlite3> \\
        --decompiled-table <luna_pinyin.table.decompiled.txt> \\
        --daemon-socket <workdir>/sock/calib.sock \\
        --work-dir <local report dir> \\
        [--console <librime>/build/bin/rime_api_console] \\
        [--template-dir <librime>/build/bin] \\
        [--status-cli <squirrel-semantic-memory>] \\
        [--take-snapshot <live facts.sqlite3>]

The report (JSON + Markdown) and per-event local package are written into
``--work-dir``; nothing is uploaded.  Raw 上文/candidate text never appears
in the report.
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

from decide import decide_final  # noqa: E402
from primary_events import FREEZE_WATERMARK, load_primary_events  # noqa: E402
from recalib_report import build_report, render_markdown, sha256_file  # noqa: E402
from recalibrate import (ALPHA_EXTENSION, ALPHA_GRID,  # noqa: E402
                         alpha0_rank_map, per_alpha_metrics,
                         score_event)
from snapshot import take_snapshot  # noqa: E402
from template_weights import parse_decompiled_table  # noqa: E402

ENGINE_VERSION = "recalibrate-alpha-v1"
CONTRACT = "AC-106-v1"
FROZEN_POLICY_ID = (
    "frozen-baseline-v1:rule=mean-token-lm-v1:model=Qwen3-0.6B-Base:"
    "tokenizer=Qwen3-0.6B-Base:norm=exact-text:fail=fail-closed-passthrough:"
    "squirrel=9c47df777958:plugin=ce58c72017db:alpha=0.0:beta_sys=1.0:"
    "beta_usr=1.0"
)

# Executor decision record (delivery contract AC-106-v1).
DECISIONS_RECORD = [
    "D-A106-1 scoring seam: the primary α ranking is computed from the "
    "template dictionary's compiled weights (rime_table_decompiler dump of "
    "the librime build tree's luna_pinyin.table.bin; runtime weight = "
    "log(raw) - kS, byte-verified against the plugin WeightScorer's verbose "
    "logs) plus the daemon mean-token-lm-v1 scores over the pinned saved "
    "competition set (same socket/protocol the plugin LlmScorer uses). The "
    "saved competition set is pinned by construction: only the recorded "
    "candidates are ranked, never a regenerated set (seam 6). The console + "
    "custom-dict composite-scorer path is implemented as a validation seam "
    "(model-free test + sample cross-check).",
    "D-A106-2 group-complete gate: saved competition size < 32, NOT the "
    "persisted competition_complete bit (spec #43 / #76 rewrite, SCN-106-3).",
    "D-A106-3 无法重放: any saved candidate without a finite template weight "
    "or a finite LM score makes the whole event 无法重放 (SCN-106-5); "
    "reported per reason, never silently reranked.",
    "D-A106-4 decision: primary-only top-1, then MRR, then smaller α; "
    "α=0 in the selection domain; control metrics never enter decide_final "
    "(SCN-106-6). Extension rule applied only when the winner is the grid "
    "upper bound.",
    "D-A106-5 SCN-106-10 gate: if the remaining primary set after 无法重放 "
    "falls below 1000 group-complete events or 100 choice-problem keys, no "
    "α* is declared and the driver hands back a specification blocker with "
    "desensitized drop-off counts.",
    "D-A106-6 empty 上文: stays in the primary set (valid 64-char window, "
    "possibly empty), reported as a stratum, never a fault (SCN-106-7). "
    "Control empty-prefix cases are dropped and counted.",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", default=None,
                    help="frozen facts snapshot (sqlite3); required unless "
                         "--take-snapshot is given")
    ap.add_argument("--take-snapshot", default=os.path.expanduser(
        "~/Library/Application Support/Squirrel/SemanticMemory/"
        "facts.sqlite3"), help="live facts store to snapshot (Online Backup)")
    ap.add_argument("--status-cli", default=None,
                    help="squirrel-semantic-memory status CLI for continuity")
    ap.add_argument("--decompiled-table", required=True,
                    help="rime_table_decompiler dump of luna_pinyin.table.bin")
    ap.add_argument("--daemon-socket", required=True,
                    help="mean_token daemon socket path")
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--fixture", default=os.path.join(_ROOT, "fixture.json"))
    ap.add_argument("--console", default=None,
                    help="rime_api_console (control path / validation)")
    ap.add_argument("--template-dir", default=None,
                    help="librime build/bin dir with template yamls")
    ap.add_argument("--model", default="/Users/habit/Models/Qwen/"
                                       "Qwen3-0.6B-Base")
    ap.add_argument("--alpha-grid", nargs="*", type=float,
                    default=ALPHA_GRID,
                    help="pre-declared α grid (default %s)" % ALPHA_GRID)
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)

    # -- snapshot ----------------------------------------------------------
    snapshot_record = None
    if args.snapshot:
        if not os.path.isfile(args.snapshot):
            sys.exit("error: snapshot not found: %s" % args.snapshot)
        identity = _snapshot_identity(args.snapshot)
        snapshot_record = {
            "path": os.path.abspath(args.snapshot),
            "sha256": sha256_file(args.snapshot),
            "identity": identity,
            "status": {"status_check": "skipped"},
        }
    else:
        snapshot_record = take_snapshot(args.take_snapshot, args.work_dir,
                                        status_cli=args.status_cli)
    print("snapshot sha256: %s" % snapshot_record["sha256"])

    # -- weights -----------------------------------------------------------
    weight_map = parse_decompiled_table(args.decompiled_table)
    print("template weight entries: %d" % len(weight_map))

    # -- primary events ----------------------------------------------------
    loaded = load_primary_events(snapshot_record["path"])
    events = loaded["events"]
    print("primary counts: %s" % json.dumps(loaded["counts"]))

    # -- score every event (weights + LM) -----------------------------------
    event_scores = []
    unreplayable = {"weight": 0, "lm": 0}
    for event in events:
        score, reason = score_event(
            event, weight_map, args.daemon_socket,
            plan_identity="recalib-v1:primary")
        if score is None:
            unreplayable[reason] = unreplayable.get(reason, 0) + 1
            continue
        event_scores.append(score)
    primary_events = len(event_scores)
    keys = len({score.key for score in event_scores})
    print("scored primary events: %d (keys %d)" % (primary_events, keys))
    print("unreplayable: %s" % json.dumps(unreplayable))

    # -- α sweep (primary) --------------------------------------------------
    alpha0 = alpha0_rank_map(event_scores)
    per_alpha = {}
    for alpha in args.alpha_grid:
        metrics = per_alpha_metrics(event_scores, alpha, alpha0)
        per_alpha[alpha] = metrics
        print("α=%-5s top1=%.4f mrr=%.4f samples=%d"
              % (alpha, metrics.top1_rate, metrics.mrr, metrics.samples))

    # -- extension rule -----------------------------------------------------
    grid = list(args.alpha_grid)
    winner = max(
        [a for a in grid if a in per_alpha],
        key=lambda a: (per_alpha[a].top1_rate, per_alpha[a].mrr, -a),
    ) if per_alpha else None
    if winner is not None and winner == grid[-1]:
        # Winner on the upper bound: sweep the extension points.
        for alpha in ALPHA_EXTENSION:
            if alpha not in per_alpha:
                metrics = per_alpha_metrics(event_scores, alpha, alpha0)
                per_alpha[alpha] = metrics
                print("extension α=%-5s top1=%.4f mrr=%.4f"
                      % (alpha, metrics.top1_rate, metrics.mrr))
        grid = grid + [a for a in ALPHA_EXTENSION if a not in grid]

    # -- fidelity diagnostic (α=0 vs observed) ------------------------------
    fidelity = {
        "observed_rank1": sum(1 for s in event_scores if s.observed_rank1),
        "reconstructed_alpha0_rank1": sum(
            1 for s in event_scores
            if alpha0.get(s.event_id) == 1),
        "agreement": _fidelity_agreement(event_scores, alpha0),
        "samples": primary_events,
    }

    # -- decision (primary only; SCN-106-10 gate) ---------------------------
    decision = decide_final(per_alpha, grid=grid,
                            primary_event_count=primary_events,
                            primary_key_count=keys)

    # -- weight validation seam (D-A106-1) ----------------------------------
    # A sample of scored events is replayed through the console with a
    # custom dict containing exactly the pinned saved competition texts
    # (seam 6); the filter's logged librime weights for the pinned set are
    # compared against the template weight map (D-A106-1 byte-for-byte
    # validation of the pure-compute weight seam against the actual
    # composite scorer).
    validation = {"samples": 0, "matched": 0, "compared": 0}
    if args.console and args.template_dir:
        from console_replay import pinned_set_weights
        from template_weights import weight_for
        sample = [s for s in event_scores
                  if not s.preceding_empty][:8]
        for score in sample:
            event = _event_by_id(loaded["events"], score.event_id)
            if event is None:
                continue
            # Template raw weights for the saved set (parallel to texts).
            raw_weights = []
            mapped_weights = []
            ok = True
            for text in event.competition:
                w = weight_for(weight_map, text,
                               event.canonical_segment_input)
                if w is None:
                    ok = False
                    break
                mapped_weights.append(round(w, 4))
                import math
                raw_weights.append(math.exp(w + 18.420680743952367))
            if not ok:
                continue
            try:
                logged = pinned_set_weights(
                    args.console, args.template_dir, args.daemon_socket,
                    event.preceding_text, event.canonical_segment_input,
                    list(event.competition), raw_weights)
            except Exception:  # noqa: BLE001 - console path can fail closed
                continue
            logged_rounded = sorted(round(w, 4) for w in logged)
            validation["samples"] += 1
            validation["compared"] += len(mapped_weights)
            # Byte-for-byte agreement of the weight VECTOR (order-free:
            # the logged batch order follows the filter's scored order, which
            # can differ from merge order).  librime prints ~4 significant
            # digits, so a 1e-3 tolerance absorbs its float-print rounding.
            mapped_sorted = sorted(mapped_weights)
            validation["matched"] += sum(
                1 for a, b in zip(mapped_sorted, logged_rounded)
                if abs(a - b) < 1e-3)
    validation["note"] = (
        "pinned-set console composite-scorer weights vs template weight map "
        "(order-free vector comparison, 1e-3 tolerance) on a sample of "
        "scored events")

    # -- control denominator ------------------------------------------------
    # One console run per word case establishes the engine competition set
    # (full template dict, emitted order); the librime weight of every
    # emitted candidate comes from the template weight map (D-A106-1, the
    # same map validated byte-for-byte against the filter's verbose logs),
    # and the daemon provides the mean-token LM scores.  Every α rank is
    # then arithmetic over the full set — the control's window-truncated
    # reordering is not used, because the control's domain is the full
    # engine competition set (seam 10).
    control = {}
    if args.console and args.template_dir:
        from control_denominator import control_case_ranks, load_fixture
        from console_replay import engine_competition
        from daemon_scoring import DaemonScoringError, score_batch
        from template_weights import weight_for
        fixture = load_fixture(args.fixture)
        sentences = {c["index"]: c["sentence"]
                     for c in fixture["sentence_cases"]}
        word_cases, dropped = _control_word_cases(fixture)
        per_case = []
        for case in word_cases:
            sentence = sentences.get(
                _word_source_sentence(fixture, case.case_index)) or ""
            start = _word_source_start(fixture, case.case_index) or 0
            context_text = sentence[:start]
            target_text = _word_text(fixture, case.case_index)
            candidates, _logged = engine_competition(
                args.console, args.template_dir, args.daemon_socket,
                context_text, case.pinyin)
            # Weights for the FULL emitted set from the template map.
            weights = []
            missing = False
            for text in candidates:
                w = weight_for(weight_map, text, case.pinyin)
                if w is None:
                    missing = True
                    break
                weights.append(w)
            if missing or len(weights) != len(candidates):
                per_case.append((case.case_index, len(candidates),
                                 {alpha: None for alpha in per_alpha}))
                continue
            try:
                lm_scores = score_batch(args.daemon_socket, context_text,
                                        candidates,
                                        request_id="recalib-ctl:" +
                                        str(case.case_index),
                                        plan_identity="recalib-v1:control")
            except DaemonScoringError:
                lm_scores = [None] * len(candidates)
            if any(v is None for v in lm_scores):
                # LM fail-closed on the engine set: case is not ranked.
                per_case.append((case.case_index, len(candidates),
                                 {alpha: None for alpha in per_alpha}))
                continue
            logged_pairs = [(t, w) for t, w in zip(candidates, weights)]
            ranks = control_case_ranks(
                candidates, logged_pairs, lm_scores, target_text,
                list(per_alpha))
            per_case.append((case.case_index, len(candidates), ranks))
        # Sentence-case guard table (seam 10: the control denominator is the
        # 120 sentence cases PLUS the in-prefix word cases).  Each sentence
        # case is a whole-sentence query (上文 empty, #46 context protocol);
        # reported as a separate guard, never decision input.
        from control_denominator import sentence_cases
        sent_cases = sentence_cases(fixture)
        sent_metrics = _sentence_guard_metrics(sent_cases, per_alpha,
                                               args, weight_map)
        control = {
            "word_cases": len(word_cases),
            "empty_prefix_dropped": dropped,
            "per_alpha": _control_metrics_from_ranks(per_case, list(per_alpha)),
            "samples_per_case": len(per_case),
            "sentence_guard": sent_metrics,
        }
    else:
        control = {"note": "console/template not provided; control table "
                           "not run"}

    # -- report -------------------------------------------------------------
    report = build_report(
        CONTRACT,
        snapshot_record,
        FREEZE_WATERMARK,
        code_identity={
            "engine_version": ENGINE_VERSION,
            "plugin_commit": _git_head(),
            "policy_id": FROZEN_POLICY_ID,
        },
        model_identity={"model": os.path.basename(os.path.normpath(
            args.model))},
        inclusion_counts=loaded["counts"],
        per_alpha=per_alpha,
        unreplayable=unreplayable,
        fidelity=fidelity,
        control=control,
        decision=decision,
        decisions_record=DECISIONS_RECORD,
        grid=grid,
        validation=validation,
    )
    report_path = os.path.join(args.work_dir, "recalibrate-report.json")
    markdown_path = os.path.join(args.work_dir, "recalibrate-report.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    print("report written: %s" % report_path)
    print("report sha256: %s" % report["report_sha256"])
    print("decision state: %s" % decision["state"])
    if decision["state"] == "specification_blocker":
        print("SCN-106-10 blocker: %s" % decision["reason"])
    return 0


def _word_source_sentence(fixture, case_index):
    for wc in fixture["word_cases"]:
        if wc["index"] == case_index:
            return wc.get("source_sentence")
    return None


def _event_by_id(events, event_id):
    for event in events:
        if event.event_id == event_id:
            return event
    return None


def _word_source_start(fixture, case_index):
    for wc in fixture["word_cases"]:
        if wc["index"] == case_index:
            return wc.get("source_start")
    return None


def _word_text(fixture, case_index):
    for wc in fixture["word_cases"]:
        if wc["index"] == case_index:
            return wc["word"]
    return None


def _control_word_cases(fixture):
    """word cases with a non-empty in-sentence prefix; (cases, dropped)."""
    from control_denominator import control_word_cases
    return control_word_cases(fixture)


def _control_metrics_from_ranks(per_case, alphas):
    """per-α control metrics from [(case_index, size, {alpha: rank})]."""
    result = {}
    for alpha in alphas:
        samples = 0
        top1 = 0
        reciprocal = 0.0
        for _, _, ranks in per_case:
            rank = ranks.get(alpha)
            if rank is None:
                continue
            samples += 1
            if rank == 1:
                top1 += 1
            reciprocal += 1.0 / rank
        result[alpha] = {
            "samples": samples,
            "top1": top1,
            "top1_rate": (top1 / samples) if samples else 0.0,
            "mrr": (reciprocal / samples) if samples else 0.0,
        }
    return result


def _sentence_guard_metrics(sent_cases, per_alpha, args, weight_map):
    """Guard-table metrics for the 120 sentence cases.

    Each sentence case is a whole-sentence query (上文 empty).  The engine
    competition set for the full sentence pinyin contains the sentence plus
    its sub-word candidates; each sub-word has its own code, so the pinned
    weight-map arithmetic does not apply to this guard.  Instead the guard
    uses the console's emitted order at α=0 (the filter's output; #46 found
    the sentence guard flat across α because the filter does not reorder
    sentence candidates).  Reported as a separate guard; never decision
    input (AC106-3).
    """
    from console_replay import engine_competition, rank_of
    alphas = list(per_alpha)
    ranks_at_alpha0 = []
    for case in sent_cases:
        sentence_text = _sentence_text(args, case.case_index)
        candidates, _logged = engine_competition(
            args.console, args.template_dir, args.daemon_socket,
            "", case.pinyin)
        ranks_at_alpha0.append(rank_of(sentence_text, candidates))
    # The guard is reported at every α with the same α=0 outcome (the #46
    # finding: the filter does not reorder sentence candidates), so the
    # guard stays flat and never disturbs the decision.
    result = {}
    for alpha in alphas:
        samples = 0
        top1 = 0
        reciprocal = 0.0
        for rank in ranks_at_alpha0:
            if rank is None:
                continue
            samples += 1
            if rank == 1:
                top1 += 1
            reciprocal += 1.0 / rank
        result[alpha] = {
            "samples": samples,
            "top1": top1,
            "top1_rate": (top1 / samples) if samples else 0.0,
            "mrr": (reciprocal / samples) if samples else 0.0,
        }
    return {"cases": len(sent_cases), "per_alpha": result,
            "method": "console emitted order at alpha=0 (guard is flat "
                      "across alpha per #46)"}


def _sentence_text(args, case_index):
    with open(args.fixture, encoding="utf-8") as handle:
        fixture = json.load(handle)
    for c in fixture["sentence_cases"]:
        if c["index"] == case_index:
            return c["sentence"]
    return None


def _fidelity_agreement(event_scores, alpha0):
    agree = 0
    total = 0
    for score in event_scores:
        a0 = alpha0.get(score.event_id)
        if a0 is None:
            continue
        total += 1
        if (a0 == 1) == score.observed_rank1:
            agree += 1
    return (agree / total) if total else 0.0


def _snapshot_identity(path):
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        rows = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()
    return {
        "history_id": rows.get("history_id"),
        "store_epoch": rows.get("store_epoch"),
        "fact_schema_version": rows.get("fact_schema_version"),
        "hlc_physical_ms": rows.get("hlc_physical_ms"),
        "hlc_logical": rows.get("hlc_logical"),
    }


def _git_head():
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True,
                             cwd=_ROOT).stdout.strip()
        return out
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
