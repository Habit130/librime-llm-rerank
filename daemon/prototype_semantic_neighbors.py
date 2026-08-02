#!/usr/bin/env python3
"""Interactive throwaway prototype for semantic-neighbor quality (squirrel#33).

Run from the plugin repository root:

  .venv/bin/python daemon/prototype_semantic_neighbors.py

Use --report for a non-interactive summary. Nothing is persisted.
"""

import argparse
import shutil
import sys
import termios
import tty
import unicodedata

from semantic_neighbors_prototype import (
    GROUPS,
    MODEL_PATH,
    QUERIES,
    REPRESENTATIONS,
    HiddenStateExtractor,
    PrototypeResults,
)


BOLD = "\x1b[1m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
RESET = "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"
ENTER_ALT_SCREEN = "\x1b[?1049h"
EXIT_ALT_SCREEN = "\x1b[?1049l"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"


def display_width(text):
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def format_context(text, width):
    if display_width(text) <= width:
        return text
    kept = []
    remaining = width - 1
    for char in reversed(text):
        char_width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if char_width > remaining:
            break
        kept.append(char)
        remaining -= char_width
    return "…" + "".join(reversed(kept))


def pad_display(text, width):
    return text + " " * max(0, width - display_width(text))


def viewport_width():
    return min(max(shutil.get_terminal_size((88, 24)).columns, 72), 110)


def print_report(results):
    print("\nRepresentation summary (within-rerank-group retrieval)")
    print(f"{'representation':30} {'top1':>7} {'MRR':>7} {'margin':>10} {'ms':>8}")
    print("-" * 68)
    for representation in REPRESENTATIONS:
        metrics = results.metrics(representation)
        print(
            f"{representation.name:30} "
            f"{metrics.top1:7.1%} {metrics.mrr:7.3f} "
            f"{metrics.mean_margin:10.4f} {metrics.median_ms:8.2f}"
        )

    fidelity = results.split_fidelity()
    print("\nExact vs split-reuse fidelity")
    print(f"median cosine:       {fidelity['median_cosine']:.6f}")
    print(f"p05 cosine:          {fidelity['p05_cosine']:.6f}")
    print(f"BPE seam changed:    {fidelity['seam_changed_rate']:.1%}")
    print(f"split total median:  {fidelity['median_total_ms']:.2f} ms")
    print(f"reused tail median:  {fidelity['median_tail_ms']:.2f} ms")
    print("\nIntegrated N=32 scoring hot path")
    print(f"baseline median:     {results.hot_path['baseline_ms']:.2f} ms")
    print(
        f"final-layer row:     {results.hot_path['final_ms']:.2f} ms "
        f"({results.hot_path['final_delta_ms']:+.2f} ms)"
    )
    print(
        f"layer-21 row:        {results.hot_path['l21_ms']:.2f} ms "
        f"({results.hot_path['l21_delta_ms']:+.2f} ms)"
    )
    print("\nThe pair representation evaluates every candidate separately; its latency is per candidate.")


def render_detail(results, query_index, representation_index):
    query = QUERIES[query_index]
    representation = REPRESENTATIONS[representation_index]
    metrics = results.metrics(representation)
    width = viewport_width()
    rule = "─" * width
    context_width = max(20, width - 46)
    lines = [CLEAR]
    lines.append(f"{BOLD}语义近邻表示原型{RESET}  {DIM}Squirrel #33{RESET}")
    lines.append(
        f"{DIM}场景 {query_index + 1}/{len(QUERIES)}"
        f"  ·  表示 {representation_index + 1}/{len(REPRESENTATIONS)}{RESET}"
    )
    lines.append(f"{DIM}{rule}{RESET}")
    lines.append(f"{BOLD}上文{RESET}      {format_context(query.context, width - 10)}")
    lines.append(
        f"{BOLD}重排组{RESET}    {' / '.join(GROUPS[query.group])}"
        f"    {BOLD}期望{RESET}  {GREEN}{query.expected}{RESET}"
        f"    {DIM}{query.intent}{RESET}"
    )
    lines.append(f"{BOLD}当前表示{RESET}  {CYAN}{representation.name}{RESET}")
    lines.append(f"{DIM}          {representation.description}{RESET}")
    lines.append(f"{DIM}{rule}{RESET}")
    lines.append(
        f"{BOLD}质量概览{RESET}  top-1 {metrics.top1:.1%}"
        f"  ·  MRR {metrics.mrr:.3f}"
        f"  ·  margin {metrics.mean_margin:.4f}"
        f"  ·  {metrics.median_ms:.2f} ms"
    )
    if representation.pair_conditioned:
        lines.append(
            f"{DIM}候选条件化表示：近邻区使用期望候选；汇总会分别查询组内每个候选。{RESET}"
        )

    lines.append("")
    lines.append(f"{BOLD}同组近邻{RESET}  {DIM}✓ 同选择  × 竞争选择{RESET}")
    for rank, (event, score) in enumerate(
        results.neighbors(query, representation, group_only=True)[:6], 1
    ):
        matched = event.selected == query.expected
        marker = f"{GREEN}✓{RESET}" if matched else f"{RED}×{RESET}"
        context = pad_display(format_context(event.context, context_width), context_width)
        lines.append(
            f" {marker}  {rank:>2}  {score: .5f}  "
            f"{context}"
            f"  → {event.selected}  {DIM}{event.intent}{RESET}"
        )

    lines.append("")
    lines.append(f"{BOLD}全局近邻{RESET}")
    for rank, (event, score) in enumerate(
        results.neighbors(query, representation)[:3], 1
    ):
        marker = f"{GREEN}✓{RESET}" if event.intent == query.intent else f"{DIM}·{RESET}"
        context = pad_display(format_context(event.context, context_width), context_width)
        lines.append(
            f" {marker}  {rank:>2}  {score: .5f}  "
            f"{context}"
            f"  → {event.selected}  {DIM}{event.intent}{RESET}"
        )

    lines.append("")
    lines.append(f"{DIM}{rule}{RESET}")
    lines.append(
        f"{BOLD}j / k{RESET} 切换场景    {BOLD}h / l{RESET} 切换表示    "
        f"{BOLD}s{RESET} 汇总    {BOLD}q{RESET} 退出"
    )
    return "\n".join(lines)


def render_summary(results):
    width = viewport_width()
    rule = "─" * width
    lines = [
        CLEAR,
        f"{BOLD}表示汇总{RESET}  {DIM}同一重排组内检索{RESET}",
        f"{DIM}{rule}{RESET}",
        "",
    ]
    lines.append(f"{'representation':30} {'top1':>7} {'MRR':>7} {'margin':>10} {'ms':>8}")
    lines.append("-" * 68)
    for representation in REPRESENTATIONS:
        metrics = results.metrics(representation)
        lines.append(
            f"{representation.name:30} "
            f"{metrics.top1:7.1%} {metrics.mrr:7.3f} "
            f"{metrics.mean_margin:10.4f} {metrics.median_ms:8.2f}"
        )
    fidelity = results.split_fidelity()
    lines.extend(
        [
            "",
            f"{BOLD}Exact vs split{RESET}: median={fidelity['median_cosine']:.6f}  "
            f"p05={fidelity['p05_cosine']:.6f}  seam changed={fidelity['seam_changed_rate']:.1%}",
            f"split total={fidelity['median_total_ms']:.2f}ms  reused tail={fidelity['median_tail_ms']:.2f}ms",
            f"N=32 hot path: base {results.hot_path['baseline_ms']:.2f}ms; "
            f"final row {results.hot_path['final_ms']:.2f}ms "
            f"({results.hot_path['final_delta_ms']:+.2f}); "
            f"L21 row {results.hot_path['l21_ms']:.2f}ms "
            f"({results.hot_path['l21_delta_ms']:+.2f})",
            "",
            f"{DIM}{rule}{RESET}",
            f"{BOLD}s{RESET} 返回详情    {BOLD}q{RESET} 退出",
        ]
    )
    return "\n".join(lines)


def run_tui(results):
    query_index = 0
    representation_index = 0
    summary = False
    file_descriptor = sys.stdin.fileno()
    old_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setcbreak(file_descriptor)
        sys.stdout.write(ENTER_ALT_SCREEN + HIDE_CURSOR)
        while True:
            frame = render_summary(results) if summary else render_detail(
                results, query_index, representation_index
            )
            sys.stdout.write(frame)
            sys.stdout.flush()
            key = sys.stdin.read(1)
            if key == "q":
                break
            if key == "s":
                summary = not summary
            elif not summary and key == "j":
                query_index = (query_index + 1) % len(QUERIES)
            elif not summary and key == "k":
                query_index = (query_index - 1) % len(QUERIES)
            elif not summary and key == "l":
                representation_index = (representation_index + 1) % len(REPRESENTATIONS)
            elif not summary and key == "h":
                representation_index = (representation_index - 1) % len(REPRESENTATIONS)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)
        sys.stdout.write(SHOW_CURSOR + EXIT_ALT_SCREEN)
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Compare semantic-neighbor representations")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    print(f"Loading {args.model}")
    extractor = HiddenStateExtractor(args.model)
    results = PrototypeResults(extractor)

    last_shown = -1

    def progress(completed, total):
        nonlocal last_shown
        percent = int(completed * 100 / total)
        if percent // 10 != last_shown:
            last_shown = percent // 10
            print(f"Embedding cases: {completed}/{total}", flush=True)

    results.build(progress=progress)
    if args.report or not sys.stdin.isatty():
        print_report(results)
    else:
        run_tui(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
