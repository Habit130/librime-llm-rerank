#!/usr/bin/env python3
"""Console replay for the #106 control denominator (and validation).

Runs ``rime_api_console`` inside a disposable rime_dir (the #46 template
pattern copied from ``calibrate.py``), with the llm_rerank filter enabled,
and ranks the engine competition set for one pinyin under the frozen
formula.

For the control denominator the engine competition set is the **full
template dict** group for that pinyin (never a pinned set — the control is
the fixture's in-prefix protocol).  The 上文 for a word case is the sentence
prefix ``sentence[:source_start]``; it is committed through a punctuator
mapping in the disposable ``default.yaml`` (a ``{commit: <text>}`` entry on
a reserved key), exactly the mechanism the plugin's recorder uses to build
``preceding_text`` from commit history.

The filter's ``verbose`` logs carry the per-candidate librime runtime
weights (``llm_rerank weight: ...``), which the driver uses to verify the
pure-compute weight map against librime's actual scorer (validation seam,
D-A106-1).  The emitted candidate order is read from the console stdout.

Raw 上文/candidate text flows only into the disposable rime_dir (local,
never uploaded); the report carries only counts, ranks and lengths.

Nothing here writes ``~/Library/Rime``, the live facts store, or the librime
build tree; the console binary and template yamls are copied out of the
build tree by the caller.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from control_denominator import ControlCase

TEMPLATE_FILES = [
    "default.yaml",
    "luna_pinyin.schema.yaml",
    "luna_pinyin.dict.yaml",
    "essay.txt",
    "symbols.yaml",
    "cangjie5.schema.yaml",
    "cangjie5.dict.yaml",
]
CANDIDATE_RE = re.compile(r"^(\d+)\. (.*)$")
COMMENT_RE = re.compile(r"^(.*) \((.*)\)$")
WEIGHT_RE = re.compile(r"llm_rerank weight: source=(\w+) weight=([-\d.eE+]+)")

# The reserved key that commits the 上文 in the disposable default.yaml.
CONTEXT_COMMIT_KEY = "]"
WINDOW = 32


class ConsoleReplayError(Exception):
    """A true fault in the console replay."""


def build_rime_dir(template_dir: str,
                   alpha: float,
                   socket_path: str,
                   context_text: str) -> Path:
    """One disposable rime_dir with the llm_rerank filter + context commit."""
    template_dir = Path(template_dir)
    tmp = Path(tempfile.mkdtemp(prefix="recalib-control-"))
    for name in TEMPLATE_FILES:
        src = template_dir / name
        if src.exists():
            shutil.copy(src, tmp / name)
    schema = (tmp / "luna_pinyin.schema.yaml").read_text(encoding="utf-8")
    if "\n    - llm_rerank\n" not in schema:
        schema = schema.replace(
            "    - simplifier@zh_tw\n    - uniquifier\n",
            "    - simplifier@zh_tw\n    - uniquifier\n    - llm_rerank\n")
    schema += (
        "\nllm_rerank:\n"
        "  enable: true\n"
        f"  window: {WINDOW}\n"
        f"  alpha: {alpha}\n"
        "  baseline_policy_id: mean-token-lm-v1\n"
        "  sys_coeff: 1.0\n"
        "  usr_coeff: 1.0\n"
        "  gamma: 0.0\n"
        "  saturate_k: 3.0\n"
        "  deadline_ms: 5000\n"
        f"  socket_path: {socket_path}\n"
        "  verbose: true\n"
    )
    (tmp / "luna_pinyin.schema.yaml").write_text(schema, encoding="utf-8")
    default = (tmp / "default.yaml").read_text(encoding="utf-8")
    escaped = _yaml_escape(context_text)
    default += (
        "\npunctuator:\n"
        "  full_shape:\n"
        f"    '{CONTEXT_COMMIT_KEY}' : {{ commit: '{escaped}' }}\n"
        "  half_shape:\n"
        f"    '{CONTEXT_COMMIT_KEY}' : {{ commit: '{escaped}' }}\n"
    )
    (tmp / "default.yaml").write_text(default, encoding="utf-8")
    return tmp


def _yaml_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "''")


def build_script(pinyin: str, context_text: str) -> str:
    lines = ["set option zh_simp"]
    if context_text:
        lines.append(CONTEXT_COMMIT_KEY)  # commit the 上文
    lines.append(pinyin)
    lines.append("print candidate list")
    lines.append("exit")
    return "\n".join(lines) + "\n"


def run_console(console_path: str, rime_dir: Path, script: str,
                timeout: int = 300) -> Tuple[str, str]:
    proc = subprocess.run(
        [str(console_path)],
        cwd=str(rime_dir),
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout, proc.stderr


def parse_candidates(stdout_text: str) -> List[str]:
    candidates = []
    for line in stdout_text.splitlines():
        m = CANDIDATE_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        rest = m.group(2)
        if idx == 1:
            candidates = []
        cm = COMMENT_RE.match(rest)
        text = cm.group(1) if cm else rest
        candidates.append(text)
    return candidates


def parse_weights(stderr_text: str) -> List[Tuple[str, float]]:
    """per-candidate librime runtime weights from the verbose logs."""
    return [(match.group(1), float(match.group(2)))
            for match in WEIGHT_RE.finditer(stderr_text)]


def rank_of(target: str, candidates: List[str]) -> Optional[int]:
    for i, text in enumerate(candidates, 1):
        if text == target:
            return i
    return None


def engine_competition(console_path: str,
                       template_dir: str,
                       socket_path: str,
                       context_text: str,
                       pinyin: str) -> Tuple[List[str], List[Tuple[str, float]]]:
    """One console run: the engine competition set + logged weights.

    Runs the full template dict (engine regeneration — the control's
    ranking domain) with the llm_rerank filter at α=0, commits the 上文 via
    the punctuator, types the pinyin, and returns:

        (emitted_candidates, logged_weights)

    ``emitted_candidates`` is the engine competition set in emitted order;
    ``logged_weights`` are the per-candidate librime runtime weights from
    the filter's verbose logs (order = scored batch order).  The caller
    then computes every α ranking from these weights + daemon LM scores
    (D-A106-1), so one console run serves the whole grid.
    """
    rime_dir = build_rime_dir(template_dir, 0.0, socket_path, context_text)
    try:
        stdout, stderr = run_console(console_path, rime_dir,
                                     build_script(pinyin, context_text))
    finally:
        shutil.rmtree(rime_dir, ignore_errors=True)
    return parse_candidates(stdout), parse_weights(stderr)


def pinned_set_weights(console_path: str,
                       template_dir: str,
                       socket_path: str,
                       context_text: str,
                       pinyin: str,
                       saved_texts,
                       raw_weights) -> List[float]:
    """Log librime's runtime weights for the PINNED saved set (seam 6).

    Builds a disposable rime_dir whose custom dict contains exactly the
    saved competition texts with their template raw weights, commits the
    上文 via the punctuator, types the pinyin, and returns the filter's
    logged ``llm_rerank weight:`` values in saved-set order.  This is the
    contract's composite-scorer validation path: librime's actual
    ``WeightScorer`` computes the weights, and the caller compares them
    against the pure-compute map (D-A106-1).

    ``saved_texts`` are the pinned competition texts; ``raw_weights`` the
    corresponding template raw weights (parallel lists).  The custom dict
    uses ``use_preset_vocabulary: false`` so librime compiles exactly the
    given weights.
    """
    from pathlib import Path
    import tempfile
    template_dir = Path(template_dir)
    tmp = Path(tempfile.mkdtemp(prefix="recalib-pinned-"))
    for name in TEMPLATE_FILES:
        src = template_dir / name
        if src.exists():
            shutil.copy(src, tmp / name)
    dict_lines = [
        "---", "name: luna_pinyin", 'version: "pinned"',
        "sort: by_weight", "use_preset_vocabulary: false", "...",
    ]
    for text, raw in zip(saved_texts, raw_weights):
        dict_lines.append("%s\t%s\t%s" % (text, pinyin, raw))
    (tmp / "luna_pinyin.dict.yaml").write_text(
        "\n".join(dict_lines) + "\n", encoding="utf-8")
    schema = (tmp / "luna_pinyin.schema.yaml").read_text(encoding="utf-8")
    if "\n    - llm_rerank\n" not in schema:
        schema = schema.replace(
            "    - simplifier@zh_tw\n    - uniquifier\n",
            "    - simplifier@zh_tw\n    - uniquifier\n    - llm_rerank\n")
    schema += (
        "\nllm_rerank:\n"
        "  enable: true\n"
        f"  window: {WINDOW}\n"
        "  alpha: 1.0\n"
        "  baseline_policy_id: mean-token-lm-v1\n"
        "  sys_coeff: 1.0\n"
        "  usr_coeff: 1.0\n"
        "  gamma: 0.0\n"
        "  saturate_k: 3.0\n"
        "  deadline_ms: 5000\n"
        f"  socket_path: {socket_path}\n"
        "  verbose: true\n"
    )
    (tmp / "luna_pinyin.schema.yaml").write_text(schema, encoding="utf-8")
    default = (tmp / "default.yaml").read_text(encoding="utf-8")
    escaped = _yaml_escape(context_text)
    default += (
        "\npunctuator:\n"
        "  full_shape:\n"
        f"    '{CONTEXT_COMMIT_KEY}' : {{ commit: '{escaped}' }}\n"
        "  half_shape:\n"
        f"    '{CONTEXT_COMMIT_KEY}' : {{ commit: '{escaped}' }}\n"
    )
    (tmp / "default.yaml").write_text(default, encoding="utf-8")
    try:
        stdout, stderr = run_console(console_path, tmp,
                                     build_script(pinyin, context_text))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    weights = parse_weights(stderr)
    # The filter scores the whole pinned group (size < 32 -> complete), so
    # the logged weights are in saved-set order.
    if len(weights) != len(saved_texts):
        raise ConsoleReplayError(
            "pinned-set weight count mismatch: logged %d for %d saved texts"
            % (len(weights), len(saved_texts)))
    return [w for _, w in weights]
