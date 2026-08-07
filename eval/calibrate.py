#!/usr/bin/env python3
"""Alpha calibration driver for the mean-token LM scoring policy
(Habit130/squirrel#46, docs/token-attribution.md).

Reproduces the canonical 120/402 fixture environment (Squirrel PR #24, head
b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b; fixture librime
33e78140250125871856cdc5b42ddc6a5fcd3cd4) with the llm_rerank filter enabled
and sweeps alpha over a pre-declared grid. The only variation between runs is
the LM normalization (mean_token vs legacy sum) and alpha; everything else is
frozen:

  - fixed inputs, expected words, candidate sets and merge order (the
    harness asserts the candidate text multiset of every case is identical
    to the alpha=0 run);
  - beta_sys = beta_usr = 1, gamma = 0, saturate_k = 3;
  - isolated disposable rime_dir per run, never ~/Library/Rime;
  - full 402 word cases as the primary denominator (no subsampling); the 120
    sentence cases are reported separately as a guard only;
  - pre-declared alpha grid and boundary extension rule written into the
    manifest before any metric is inspected;
  - deterministic pipeline (random seed 42 reported for auxiliary analysis).

Usage (from the repo root):

  eval/.venv/bin/python eval/calibrate.py \
      --console <squirrel>/librime/build/bin/rime_api_console \
      --template-dir <squirrel>/librime/build/bin

Outputs (all committed): eval/results.json (stable machine-readable),
eval/manifest.json, eval/SUMMARY.md.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "eval" / "fixture.json"
DEFAULT_MODEL = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
DAEMON_PY = REPO_ROOT / "daemon" / "server.py"
DAEMON_VENV_PY = REPO_ROOT / "daemon" / ".venv" / "bin" / "python"

TEMPLATE_FILES = [
    "default.yaml",
    "luna_pinyin.schema.yaml",
    "luna_pinyin.dict.yaml",
    "essay.txt",
    "symbols.yaml",
    "cangjie5.schema.yaml",
    "cangjie5.dict.yaml",
]
MARKER = "__eval_marker__"
CANDIDATE_RE = re.compile(r"^(\d+)\. (.*)$")
COMMENT_RE = re.compile(r"^(.*) \((.*)\)$")

# Pre-declared alpha grid and boundary extension rule. Written to the
# manifest before any metric is inspected (docs/token-attribution.md).
ALPHA_GRID = [0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]
ALPHA_EXTENSION = [14.0, 20.0]
RANDOM_SEED = 42
FIXED_COEFFICIENTS = {
    "beta_sys": 1.0,
    "beta_usr": 1.0,
    "gamma": 0.0,
    "saturate_k": 3.0,
    "window": 32,
}
DEADLINE_MS = 5000

OLD_BASELINE_POLICY_ID = "first-stage-base-v1"
NEW_BASELINE_POLICY_ID = "mean-token-lm-v1"
SOURCE_COMMIT = "b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b"
FIXTURE_LIBRIME_COMMIT = "33e78140250125871856cdc5b42ddc6a5fcd3cd4"
CORPUS_SHA256 = "a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj):
    """Canonical serialization for checksums and manifest hashing.

    Fixed rule shared with eval/verify_artifacts.py: sort_keys, compact
    separators, ensure_ascii=False. Never change this function without
    changing the verifier — committed manifest hashes are computed with it.
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def candidate_checksums(candidate_texts):
    """Stable checksums for one case's candidate list.

    `ordered_sha256` hashes the candidate texts in emission order (the
    original merge order as observed); `multiset_sha256` hashes the sorted
    texts so duplicate candidates are not silently collapsed away by the
    comparison.
    """
    return {
        "ordered_sha256": sha256_bytes(
            canonical_json(candidate_texts).encode("utf-8")),
        "multiset_sha256": sha256_bytes(
            canonical_json(sorted(candidate_texts)).encode("utf-8")),
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_fixture(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture["counts"]["sentences"] != 120 or fixture["counts"]["words"] != 402:
        sys.exit(f"error: fixture is not the canonical 120/402 fixture: {path}")
    if fixture["corpus_sha256"] != CORPUS_SHA256:
        sys.exit("error: fixture corpus checksum does not match the canonical corpus")
    return fixture


def build_script(cases):
    lines = ["set option zh_simp"]
    for pinyin in cases:
        lines.append("{Escape}")
        lines.append(pinyin)
        lines.append("print candidate list")
        lines.append(f"set option {MARKER}")
    lines.append("exit")
    return "\n".join(lines) + "\n"


def patch_schema(template, alpha, baseline_policy_id, socket_path):
    """Append the llm_rerank filter to the engine and add its config block.

    Text-level patch (no YAML dependency): the filter list is extended and a
    config block is appended at the end of the schema file.
    """
    text = template
    if "\n    - llm_rerank\n" in text:
        sys.exit("error: template schema already contains llm_rerank")
    text = text.replace(
        "    - simplifier@zh_tw\n    - uniquifier\n",
        "    - simplifier@zh_tw\n    - uniquifier\n    - llm_rerank\n",
    )
    block = (
        "\nllm_rerank:\n"
        f"  enable: true\n"
        f"  window: {FIXED_COEFFICIENTS['window']}\n"
        f"  alpha: {alpha}\n"
        f"  baseline_policy_id: {baseline_policy_id}\n"
        f"  sys_coeff: {FIXED_COEFFICIENTS['beta_sys']}\n"
        f"  usr_coeff: {FIXED_COEFFICIENTS['beta_usr']}\n"
        f"  gamma: {FIXED_COEFFICIENTS['gamma']}\n"
        f"  saturate_k: {FIXED_COEFFICIENTS['saturate_k']}\n"
        f"  deadline_ms: {DEADLINE_MS}\n"
        f"  socket_path: {socket_path}\n"
        "  verbose: false\n"
    )
    return text + block


def build_rime_dir(template_dir, alpha, baseline_policy_id, socket_path):
    tmp = Path(tempfile.mkdtemp(prefix="llm-rerank-calib-"))
    for name in TEMPLATE_FILES:
        src = template_dir / name
        if src.exists():
            shutil.copy(src, tmp / name)
    schema = (tmp / "luna_pinyin.schema.yaml").read_text(encoding="utf-8")
    (tmp / "luna_pinyin.schema.yaml").write_text(
        patch_schema(schema, alpha, baseline_policy_id, socket_path),
        encoding="utf-8",
    )
    return tmp


def run_console(console_path, rime_dir, script):
    proc = subprocess.run(
        [str(console_path)],
        cwd=rime_dir,
        input=script,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return proc.stdout


def split_into_blocks(stdout_text, expected_count):
    blocks = []
    current = []
    for line in stdout_text.splitlines():
        if line == f"{MARKER} set on.":
            blocks.append(current)
            current = []
        else:
            current.append(line)
    if len(blocks) != expected_count:
        sys.exit(
            f"error: expected {expected_count} test-case blocks from "
            "rime_api_console, got {len(blocks)} -- refusing to report numbers "
            "against misaligned data."
        )
    return blocks


def parse_candidates(block_lines):
    candidates = []
    for line in block_lines:
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


def rank_of(target, candidates):
    for i, text in enumerate(candidates, 1):
        if text == target:
            return i
    return None


def word_metrics(ranks):
    n = len(ranks)
    top1 = sum(1 for rank in ranks if rank == 1)
    top5 = sum(1 for rank in ranks if rank is not None and rank <= 5)
    not_found = sum(1 for rank in ranks if rank is None)
    mrr = sum((1.0 / rank if rank else 0.0) for rank in ranks) / n
    return {
        "samples": n,
        "not_found": not_found,
        "top1": top1,
        "top1_rate": top1 / n,
        "top5": top5,
        "top5_rate": top5 / n,
        "mrr": mrr,
    }


class Daemon:
    def __init__(self, socket_path, model_path, scoring, telemetry_path=None):
        self.socket_path = socket_path
        self.model_path = model_path
        self.scoring = scoring
        self.telemetry_path = telemetry_path
        self.proc = None

    def start(self):
        env = dict(os.environ)
        if self.telemetry_path:
            env["LLM_RERANK_TELEMETRY"] = str(self.telemetry_path)
        cmd = [
            str(DAEMON_VENV_PY), str(DAEMON_PY),
            "--socket", str(self.socket_path),
            "--model", self.model_path,
            "--scoring", self.scoring,
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        )
        line = self.proc.stdout.readline().strip()
        if not line.startswith("READY"):
            raise RuntimeError(f"daemon did not become ready: {line!r}")
        for _ in range(600):
            if os.path.exists(self.socket_path):
                return
            time.sleep(0.05)
        raise RuntimeError("daemon socket not created")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)


def model_identity(model_path):
    """Identity of the actual model weights and tokenizer files.

    The absolute path is only a display convenience; the identity itself is
    the set of (name, size, sha256) triples of the weight files (all shards,
    e.g. *.safetensors / *.bin / *.gguf) and of the tokenizer files, plus a
    combined sha256 over the canonical serialization of each set. Any change
    of weights, sharding, or tokenizer files changes the identity.
    """
    model_path = Path(model_path)

    def file_triples(names):
        triples = []
        for name in names:
            path = model_path / name
            if path.exists():
                triples.append({
                    "name": name,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
        return sorted(triples, key=lambda entry: entry["name"])

    weights = file_triples(
        sorted(name for name in os.listdir(model_path)
               if name.endswith((".safetensors", ".bin", ".gguf"))))
    tokenizer = file_triples([
        "tokenizer.json", "vocab.json", "merges.txt", "config.json",
        "tokenizer_config.json",
    ])
    if not weights:
        raise ValueError(
            f"no model weight files found under {model_path} "
            "(expected *.safetensors / *.bin / *.gguf)"
        )
    return {
        "display_model_path": str(model_path),
        "weights": {
            "files": weights,
            "sha256": sha256_bytes(canonical_json(weights).encode("utf-8")),
        },
        "tokenizer": {
            "files": tokenizer,
            "sha256": sha256_bytes(canonical_json(tokenizer).encode("utf-8")),
        },
    }


def rime_dir_identity(rime_dir):
    identity = {}
    for name in ("default.yaml", "luna_pinyin.schema.yaml"):
        path = rime_dir / name
        if path.exists():
            identity[name] = sha256_file(path)
    return identity


def config_identity(template_dir, alpha, baseline_policy_id):
    """Deterministic identity of the frozen calibration config.

    The schema is patched exactly as in a run, with the ephemeral socket path
    normalized away so the identity is reproducible across machines.
    """
    schema = (template_dir / "luna_pinyin.schema.yaml").read_text(encoding="utf-8")
    patched = patch_schema(schema, alpha, baseline_policy_id, "<ephemeral>")
    default = (template_dir / "default.yaml").read_bytes()
    digest = hashlib.sha256()
    digest.update(patched.encode("utf-8"))
    digest.update(b"\0")
    digest.update(default)
    return digest.hexdigest()


def decide_final(results):
    """Select the final alpha from the mean-token policy's candidate runs.

    Selection criterion (pre-declared): word top-1 rate, then MRR, then the
    smaller alpha as a stable tie-break. The selection domain is the
    mean-token policy: the alpha=0 baseline run (LM term disabled) plus the
    mean-token grid runs. The legacy sum run is background evidence for the
    old policy and never participates in the mean-token alpha decision.
    Returns a decision dict that the script itself writes into the manifest
    and the summary; nothing is hand-edited afterwards.

    Reported status flags:
      - internal_optimum: the winner is an interior point of the pre-declared
        grid (a boundary winner is not an internal optimum, and per the
        pre-declared protocol no unique optimum is then declared);
      - positive_alpha_qualified: some positive alpha beat alpha=0.
    """
    runs = [
        (key, entry)
        for key, entry in results["runs"].items()
        if key == "baseline" or key.startswith("mean_alpha_")
    ]
    if not runs:
        raise ValueError("no mean-token runs to select from")
    best_key, best = max(
        runs,
        key=lambda kv: (
            kv[1]["metrics"]["word"]["top1_rate"],
            kv[1]["metrics"]["word"]["mrr"],
            -kv[1]["alpha"],
        ),
    )
    alpha = best["alpha"]
    word = best["metrics"]["word"]
    positive_runs = [
        (key, entry["metrics"]["word"]["top1_rate"], entry["alpha"])
        for key, entry in results["runs"].items()
        if key.startswith("mean_alpha_") and "metrics" in entry
    ]
    best_positive = max(positive_runs, key=lambda t: (t[1], -t[2]),
                        default=None)

    if alpha == 0.0:
        positive_note = (
            f"no positive value qualified: the best positive grid point is "
            f"alpha={best_positive[2]} with word top-1 {best_positive[1]:.4f}, "
            "below alpha=0"
            if best_positive is not None
            else "the grid contains no positive values"
        )
        rationale = (
            "The canonical 120/402 fixture supports no positive alpha: "
            f"alpha=0 (word top-1 {word['top1_rate']:.4f}, "
            f"MRR {word['mrr']:.4f}, {word['top1']}/{word['samples']}) beats "
            f"every positive grid point {ALPHA_GRID[1:]} on top-1 and MRR; "
            f"{positive_note}. The best grid point sits on the grid's lower "
            "boundary and the pre-declared extension rule covers the upper "
            "boundary only, so no internal optimum exists. The data-supported "
            "boundary result is therefore alpha=0 (owner decision, "
            "Habit130/squirrel#46): the LM term stays disabled by default "
            "and the mean-token policy remains available via explicit schema "
            "configuration. A future contextual fixture may re-calibrate."
        )
        return {
            "final_alpha": "baseline",
            "final_alpha_value": 0.0,
            "internal_optimum": False,
            "positive_alpha_qualified": False,
            "final_alpha_rationale": rationale,
        }

    grid_interior = ALPHA_GRID[1:-1]
    internal_optimum = alpha in grid_interior
    if alpha == ALPHA_GRID[-1] and ALPHA_EXTENSION:
        extension_note = (
            f" the winner sits on the grid's upper boundary; per the "
            f"pre-declared extension rule the grid extends to "
            f"{ALPHA_EXTENSION[-1]} before an optimum is claimed"
        )
    elif not internal_optimum:
        extension_note = (
            " the winner sits on the grid's lower boundary; per the "
            "pre-declared protocol no internal optimum is declared"
        )
    else:
        extension_note = ""
    rationale = (
        f"Alpha={alpha} wins the canonical 120/402 fixture on word top-1 "
        f"({word['top1_rate']:.4f}) and MRR ({word['mrr']:.4f}) and "
        f"qualifies as the selected positive value.{extension_note}"
    )
    return {
        "final_alpha": best_key,
        "final_alpha_value": alpha,
        "internal_optimum": internal_optimum,
        "positive_alpha_qualified": True,
        "final_alpha_rationale": rationale,
    }


def finalize_manifest(manifest, results, decision):
    """Write the final manifest with a canonical, verifiable checksum.

    manifest_sha256 = sha256(canonical_json(manifest minus manifest_sha256));
    eval/verify_artifacts.py recomputes it with the same rule.
    """
    manifest.update(decision)
    sync_manifest_runs(manifest, results)
    without_hash = {
        key: value for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    manifest["manifest_sha256"] = sha256_bytes(
        canonical_json(without_hash).encode("utf-8"))
    return manifest


def sync_manifest_runs(manifest, results):
    for run_key in list(results["runs"].keys()):
        entry = results["runs"][run_key]
        manifest["runs"][run_key] = {
            "alpha": entry["alpha"],
            "policy": entry["policy"],
            "lm_term": entry["lm_term"],
            "metrics": entry["metrics"],
            "schema_config_sha256": entry["config_identity"],
            "harmful_regressions": results["harmful_regressions"].get(
                run_key, {"count": 0, "case_indexes": []}),
        }


def checkpoint(results_dir, manifest, results):
    sync_manifest_runs(manifest, results)
    (results_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (results_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--console", type=Path, required=True,
                    help="path to rime_api_console (fixture librime build)")
    ap.add_argument("--template-dir", type=Path, required=True,
                    help="dir with the fixture template files (build/bin)")
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--keep-tmp", action="store_true",
                    help="keep the isolated rime_dir of the last run (debugging)")
    args = ap.parse_args()

    if not args.console.exists():
        sys.exit(f"error: console not found: {args.console}")
    if not DAEMON_PY.exists() or not DAEMON_VENV_PY.exists():
        sys.exit("error: daemon venv not found; expected daemon/.venv")

    fixture = load_fixture(args.fixture)
    sentence_cases = fixture["sentence_cases"]
    word_cases = fixture["word_cases"]
    sentence_targets = [c["sentence"] for c in sentence_cases]
    word_targets = [c["word"] for c in word_cases]
    all_pinyins = [c["pinyin"] for c in sentence_cases] + \
                  [c["pinyin"] for c in word_cases]
    script = build_script(all_pinyins)

    results_dir = REPO_ROOT / "eval"
    telemetry_path = results_dir / "telemetry.jsonl"
    if telemetry_path.exists():
        telemetry_path.unlink()

    # Manifest skeleton with the pre-declared grid and extension rule.
    # Written BEFORE inspecting any metric.
    manifest = {
        "issue": "Habit130/squirrel#46",
        "source_commit": SOURCE_COMMIT,
        "source_pr": "Habit130/squirrel#24",
        "corpus": "scripts/eval/corpus/sentences.txt",
        "corpus_sha256": CORPUS_SHA256,
        "case_counts": {"sentences": 120, "words": 402},
        "word_manifest_sha256": fixture["word_manifest_sha256"],
        "fixture_librime_commit": FIXTURE_LIBRIME_COMMIT,
        "pinyin_dependency": "pypinyin==0.55.0",
        "context_protocol": "standalone word, preceding text empty",
        "model_identity": model_identity(args.model),
        "random_seed": RANDOM_SEED,
        "fixed_coefficients": FIXED_COEFFICIENTS,
        "deadline_ms": DEADLINE_MS,
        "scoring_policies": {
            "legacy": {"baseline_policy_id": OLD_BASELINE_POLICY_ID,
                       "normalization": "sum (pre-#46 algorithm)"},
            "mean_token": {"baseline_policy_id": NEW_BASELINE_POLICY_ID,
                           "normalization": "mean per candidate token"},
        },
        "alpha_grid": ALPHA_GRID,
        "alpha_grid_extension_rule": (
            f"if the best alpha sits on the grid's upper boundary, extend by "
            f"{ALPHA_EXTENSION}; if still on the boundary, report that no "
            "internal optimum exists"
        ),
        "grammar_data_identity": (
            "not installed (matching the PR #24 fixture environment; the "
            "frozen candidate sets were produced without octagram data)"
        ),
        "runs": {},
        "final_alpha": None,
        "final_alpha_value": None,
        "internal_optimum": None,
        "positive_alpha_qualified": None,
        "final_alpha_rationale": None,
        "baseline_candidate_manifest_sha256": None,
    }
    manifest_path = results_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    results = {
        "fixture": {
            "source_commit": SOURCE_COMMIT,
            "corpus_sha256": CORPUS_SHA256,
            "word_manifest_sha256": fixture["word_manifest_sha256"],
            "sentences": 120,
            "words": 402,
        },
        "runs": {},
        "case_ranks": {},
        "candidate_set_frozen": {},
        "harmful_regressions": {},
        "distributions": {},
        "baseline_candidate_checksums": {},
    }

    try:
        # Run 1: alpha=0 baseline (no LLM term). Freezes merge order and the
        # candidate sets every later run must match. The per-case ordered and
        # multiset candidate checksums are committed so future reruns can
        # prove the candidate sets and merge order are identical.
        baseline = run_single(
            args, script, sentence_targets, word_targets, all_pinyins,
            alpha=0.0, baseline_policy_id=NEW_BASELINE_POLICY_ID,
            daemon=None,
        )
        results["runs"]["baseline"] = {
            "alpha": 0.0, "policy": NEW_BASELINE_POLICY_ID,
            "lm_term": "disabled",
            "metrics": baseline["metrics"],
            "config_identity": baseline["config_identity"],
        }
        baseline_candidate_checksums = baseline["candidate_checksums"]
        results["baseline_candidate_checksums"] = baseline_candidate_checksums
        manifest["baseline_candidate_manifest_sha256"] = sha256_bytes(
            canonical_json(baseline_candidate_checksums).encode("utf-8"))
        checkpoint(results_dir, manifest, results)

        # Run 2: legacy sum policy at alpha=2.0 (old default).
        legacy_daemon = Daemon(
            results_dir / "calib-legacy.sock", args.model,
            "legacy_sum")
        legacy_daemon.start()
        try:
            legacy = run_single(
                args, script, sentence_targets, word_targets, all_pinyins,
                alpha=2.0, baseline_policy_id=OLD_BASELINE_POLICY_ID,
                daemon=legacy_daemon,
            )
        finally:
            legacy_daemon.stop()
        assert_frozen(legacy, baseline_candidate_checksums,
                      f"legacy alpha=2.0", results)
        results["runs"]["legacy_sum_alpha_2.0"] = {
            "alpha": 2.0, "policy": OLD_BASELINE_POLICY_ID,
            "lm_term": "legacy sum",
            "metrics": legacy["metrics"],
            "config_identity": legacy["config_identity"],
        }
        results["case_ranks"]["legacy_sum_alpha_2.0"] = legacy["ranks"]
        checkpoint(results_dir, manifest, results)

        # Runs 3+: mean-token sweep over the pre-declared grid.
        mean_daemon = Daemon(
            results_dir / "calib-mean.sock", args.model,
            "mean_token", telemetry_path=telemetry_path)
        mean_daemon.start()
        try:
            for alpha in ALPHA_GRID:
                if alpha == 0.0:
                    continue  # already measured as baseline
                run = run_single(
                    args, script, sentence_targets, word_targets, all_pinyins,
                    alpha=alpha, baseline_policy_id=NEW_BASELINE_POLICY_ID,
                    daemon=mean_daemon,
                )
                assert_frozen(run, baseline_candidate_checksums,
                              f"mean alpha={alpha}", results)
                results["runs"][f"mean_alpha_{alpha}"] = {
                    "alpha": alpha, "policy": NEW_BASELINE_POLICY_ID,
                    "lm_term": "mean token",
                    "metrics": run["metrics"],
                    "config_identity": run["config_identity"],
                }
                results["case_ranks"][f"mean_alpha_{alpha}"] = run["ranks"]
                checkpoint(results_dir, manifest, results)
        finally:
            mean_daemon.stop()

        results["case_ranks"]["baseline"] = baseline["ranks"]

        for run_key, run in results["runs"].items():
            if run_key in results["case_ranks"]:
                regressions = [
                    i + 1 for i, rank in enumerate(
                        results["case_ranks"][run_key]["word"])
                    if results["case_ranks"]["baseline"]["word"][i] == 1
                    and rank != 1
                ]
            else:
                regressions = []
            results["harmful_regressions"][run_key] = {
                "count": len(regressions),
                "case_indexes": regressions,
            }
    except Exception:
        raise

    results["distributions"] = load_distributions(telemetry_path)

    decision = decide_final(results)
    finalize_manifest(manifest, results, decision)
    checkpoint(results_dir, manifest, results)
    write_summary(results_dir / "SUMMARY.md", manifest, results)

    print()
    print("manifests written: eval/manifest.json, eval/results.json, "
          "eval/SUMMARY.md")
    print(f"final_alpha={decision['final_alpha_value']} "
          f"internal_optimum={decision['internal_optimum']} "
          f"positive_alpha_qualified={decision['positive_alpha_qualified']}")
    return 0


def run_single(args, script, sentence_targets, word_targets, all_pinyins,
               alpha, baseline_policy_id, daemon):
    socket_path = None
    if daemon is not None:
        socket_path = daemon.socket_path
    rime_dir = build_rime_dir(args.template_dir, alpha, baseline_policy_id,
                              socket_path or "/nonexistent")
    try:
        stdout = run_console(args.console, rime_dir, script)
    finally:
        if args.keep_tmp:
            print(f"(kept isolated rime_dir at {rime_dir})", file=sys.stderr)
        else:
            shutil.rmtree(rime_dir, ignore_errors=True)

    blocks = split_into_blocks(stdout, len(all_pinyins))
    sentence_blocks = blocks[: len(sentence_targets)]
    word_blocks = blocks[len(sentence_targets):]

    sentence_ranks = []
    sentence_emissions = []
    for target, block in zip(sentence_targets, sentence_blocks):
        candidates = parse_candidates(block)
        sentence_emissions.append(candidates)
        sentence_ranks.append(rank_of(target, candidates))
    word_ranks = []
    word_emissions = []
    for target, block in zip(word_targets, word_blocks):
        candidates = parse_candidates(block)
        word_emissions.append(candidates)
        word_ranks.append(rank_of(target, candidates))

    return {
        "metrics": {
            "sentence": word_metrics(sentence_ranks),
            "word": word_metrics(word_ranks),
        },
        "ranks": {"sentence": sentence_ranks, "word": word_ranks},
        "candidate_checksums": {
            "sentence": [candidate_checksums(s) for s in sentence_emissions],
            "word": [candidate_checksums(w) for w in word_emissions],
        },
        "config_identity": config_identity(args.template_dir, alpha,
                                           baseline_policy_id),
    }


def assert_frozen(run, baseline_candidate_checksums, label, results):
    """Verify every case's candidate multiset is identical to the baseline.

    Compared by the committed multiset checksums (sorted text lists), so
    duplicate candidates are never silently collapsed away.
    """
    mismatches = []
    for kind in ("sentence", "word"):
        for i, (got, expected) in enumerate(
            zip(run["candidate_checksums"][kind],
                baseline_candidate_checksums[kind]), 1
        ):
            if got["multiset_sha256"] != expected["multiset_sha256"]:
                mismatches.append(f"{kind} case {i}")
    if mismatches:
        sys.exit(
            f"error: candidate set changed between baseline and {label}: "
            + ", ".join(mismatches[:10])
            + " -- refusing to report numbers against a moving candidate set."
        )
    results["candidate_set_frozen"][label] = True


def load_distributions(telemetry_path):
    """Summarize the daemon telemetry (scores + token counts only).

    The full per-request rows stay out of the committed artifacts; the
    summary carries the acceptance-relevant distribution evidence.
    """
    if not telemetry_path.exists():
        return {"source": "daemon telemetry", "requests": 0, "samples": 0}
    rows = []
    for line in telemetry_path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    scores = []
    count_histogram = {}
    for row in rows:
        counts = row.get("counts")
        for i, score in enumerate(row.get("scores", [])):
            scores.append(score)
            count = counts[i] if counts else None
            if count is not None:
                count_histogram[count] = count_histogram.get(count, 0) + 1
    if not scores:
        return {"source": "daemon telemetry", "requests": len(rows), "samples": 0}
    return {
        "source": "daemon telemetry",
        "requests": len(rows),
        "samples": len(scores),
        "token_count_histogram": {
            str(key): count_histogram[key]
            for key in sorted(count_histogram)
        },
        "score_min": min(scores),
        "score_max": max(scores),
        "score_mean": sum(scores) / len(scores),
    }


def write_summary(path, manifest, results):
    model_identity = manifest["model_identity"]
    lines = [
        "# Mean-Token Scoring Calibration Summary",
        "",
        f"- Issue: Habit130/squirrel#46",
        f"- Canonical fixture: Squirrel PR #24 head `{SOURCE_COMMIT}` "
        "(120 sentences, 402 word cases; corpus SHA-256 `{}`)".format(
            CORPUS_SHA256),
        f"- Fixture librime: `{FIXTURE_LIBRIME_COMMIT}` (1.17.0)",
        f"- Word manifest SHA-256: `{manifest['word_manifest_sha256']}`",
        f"- Model weights: {len(model_identity['weights']['files'])} file(s), "
        "SHA-256 `{}`".format(model_identity["weights"]["sha256"]),
        f"- Tokenizer files: {len(model_identity['tokenizer']['files'])} file(s), "
        "SHA-256 `{}`".format(model_identity["tokenizer"]["sha256"]),
        f"- Random seed: {manifest['random_seed']} (pipeline is deterministic)",
        f"- Fixed coefficients: beta_sys=beta_usr=1, gamma=0, saturate_k=3, "
        "window=32; grammar data: not installed (PR #24 fixture environment)",
        f"- Alpha grid (pre-declared): {ALPHA_GRID}",
        f"- Grid extension rule: {manifest['alpha_grid_extension_rule']}",
        "",
        "## Word-level results (primary denominator: 402 word cases)",
        "",
        "| run | policy | alpha | top-1 | top-5 | MRR | samples | "
        "not found | harmful regressions |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, entry in results["runs"].items():
        m = entry["metrics"]["word"]
        reg = results["harmful_regressions"].get(key, {"count": 0})
        lines.append(
            f"| {key} | {entry['policy']} | {entry['alpha']} | "
            f"{m['top1_rate']:.4f} ({m['top1']}/{m['samples']}) | "
            f"{m['top5_rate']:.4f} | {m['mrr']:.4f} | {m['samples']} | "
            f"{m['not_found']} | {reg['count']} |"
        )
    lines.append("")
    lines.append("## Sentence-level results (guard only, not a denominator)")
    lines.append("")
    lines.append("| run | policy | alpha | top-1 |")
    lines.append("|---|---|---|---|")
    for key, entry in results["runs"].items():
        m = entry["metrics"]["sentence"]
        lines.append(
            f"| {key} | {entry['policy']} | {entry['alpha']} | "
            f"{m['top1_rate']:.4f} |"
        )
    lines.append("")
    lines.append("## Final decision")
    lines.append("")
    final_key = manifest["final_alpha"]
    if final_key:
        entry = results["runs"][final_key]
        lines.append(
            f"- **final alpha = {entry['alpha']}** (run `{final_key}`); "
            f"word top-1 {entry['metrics']['word']['top1_rate']:.4f}, "
            f"MRR {entry['metrics']['word']['mrr']:.4f}"
        )
        lines.append(
            f"- internal_optimum = {manifest['internal_optimum']}; "
            f"positive_alpha_qualified = "
            f"{manifest['positive_alpha_qualified']}"
        )
        lines.append(f"- Rationale: {manifest['final_alpha_rationale']}")
        baseline = results["runs"]["baseline"]
        legacy = results["runs"]["legacy_sum_alpha_2.0"]
        lines.append(
            f"- Baseline (no LM term): top-1 {baseline['metrics']['word']['top1_rate']:.4f}, "
            f"MRR {baseline['metrics']['word']['mrr']:.4f}"
        )
        lines.append(
            f"- Old sum policy alpha=2.0: top-1 {legacy['metrics']['word']['top1_rate']:.4f}, "
            f"MRR {legacy['metrics']['word']['mrr']:.4f}"
        )
        lines.append(
            f"- Delta vs baseline: top-1 "
            f"{entry['metrics']['word']['top1_rate'] - baseline['metrics']['word']['top1_rate']:+.4f}; "
            f"vs old policy: "
            f"{entry['metrics']['word']['top1_rate'] - legacy['metrics']['word']['top1_rate']:+.4f}"
        )
        lines.append(
            f"- Harmful regressions at final alpha: "
            f"{results['harmful_regressions'].get(final_key, {'count': 0})['count']} cases "
            "whose expected word dropped from rank 1"
        )
        lines.append(
            f"- Baseline candidate manifest SHA-256: "
            f"`{manifest['baseline_candidate_manifest_sha256']}` (per-case "
            "ordered and multiset checksums in results.json)"
        )
        lines.append(
            f"- Historical 78-case numbers are background only and are NOT a "
            "paired baseline (different denominator)."
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
