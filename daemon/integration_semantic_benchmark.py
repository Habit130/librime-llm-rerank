#!/usr/bin/env python3
"""Real-model gate for the fixed semantic benchmark (#69).

This is explicit opt-in integration, not part of the model-free unittest
gate.  It loads the #60 Qwen3 extractor once, computes vectors for the fixed
synthetic benchmark 上文, and sends every case through the #59 exact
oracle over disposable temporary facts roots.  The report contains no raw
上文, candidate text, or private path; it retains benchmark/case digests, IDs,
numeric gate results and non-sensitive environment metadata.

Run from the plugin repository:

    daemon/.venv/bin/python daemon/integration_semantic_benchmark.py \
        [--model /Users/habit/Models/Qwen/Qwen3-0.6B-Base] [--output DIR]

The command fails explicitly when MLX or the model is unavailable.  A failing
representation is reported as failing the elimination gate; this command
never selects a representation and never changes production configuration.
"""

import argparse
import datetime
import json
import os
import platform
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVAL = _REPO_ROOT / "eval"
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

from semantic_benchmark import (  # noqa: E402
    CONTRACT_ID,
    run_real_model_gate,
)


MODEL_PATH = os.environ.get(
    "LLM_RERANK_MODEL", "/Users/habit/Models/Qwen/Qwen3-0.6B-Base")


def _environment(model_path):
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "model_basename": os.path.basename(os.path.normpath(model_path)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--output", default=None,
                        help="directory for the numeric evidence artifact")
    args = parser.parse_args()
    try:
        import mlx.core  # noqa: F401
        import mlx_lm  # noqa: F401
    except ImportError as error:
        print("FAIL: MLX is not importable: %s" % error)
        print("   Run inside daemon/.venv or install the project daemon deps.")
        return 1

    started = _environment(args.model)
    try:
        report = run_real_model_gate(args.model)
    except Exception as error:  # noqa: BLE001 - integration is fail-closed
        print("FAIL: semantic benchmark integration: %s" % error)
        return 1
    report = {
        "evidence": CONTRACT_ID + " semantic benchmark real-model gate",
        "started": started,
        "finished": _environment(args.model),
        "results": report,
    }
    output_dir = args.output or tempfile.mkdtemp(prefix="semantic-evidence-")
    os.makedirs(output_dir, exist_ok=True)
    artifact_path = os.path.join(output_dir, "semantic_benchmark_evidence.json")
    with open(artifact_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2,
                  sort_keys=True)

    print("evidence artifact: %s" % artifact_path)
    print("benchmark digest: %s" % report["results"]["benchmark"]
          ["benchmark_digest"])
    print("coverage: %s" % json.dumps(report["results"]["coverage"],
                                       sort_keys=True))
    for name, result in report["results"]["representations"].items():
        print("  %s positive=%.3f negative=%.3f gate=%s" % (
            name, result["positive"]["rate"],
            result["hard_negative"]["rate"], result["gate_pass"]))
    passed = all(result["gate_pass"] for result in
                 report["results"]["representations"].values())
    if not passed:
        print("FAIL: one or more representations did not meet AC-69-v1")
        print("selection=not_run production_enablement=not_run")
        return 1
    print("PASS: semantic benchmark gate; selection and production enablement "
          "remain not_run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
