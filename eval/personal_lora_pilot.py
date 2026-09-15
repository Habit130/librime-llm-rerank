#!/usr/bin/env python3
"""Local MLX LoRA feasibility pilot (Habit130/squirrel#176, AC-176-v1).

Demonstrates one genuine local MLX LoRA train/update/save/reload path for the
frozen completion-only objective on the M5/24 GB Mac and returns a measured
``local_feasible`` estimate for one full training run plus routine
validation/checkpointing within 12 hours, or a precise blocker.

Objective and serialization (frozen by the contract):

- text is the raw concatenation ``prompt + completion``;
- the tokenizer is called once on that concatenated string (no chat or
  instruction wrapper, no synthetic sentence-end training target);
- a target token contributes loss only when its first character lies at or
  after the prompt/completion character boundary, so the prompt is never
  charged to the loss;
- a token that spans the boundary is charged to the prompt side, is counted
  and is reported, and is never silently assigned to the loss side;
- a tokenizer-required BOS, when present, is an input-only token charged to
  the prompt side.

The module keeps all private artifacts (identity manifest, probe table,
measurement, adapter, verification scores and the public report) under the
ticket-owned root, owner-only. It never parses ``validation.jsonl`` or
``test.jsonl``: those are only opened in binary mode for checksumming. No
prompt/completion text is printed or written outside the private root.

CLI (the delivery interface):

    python3 eval/personal_lora_pilot.py --self-test
    python3 eval/personal_lora_pilot.py --run --config <root>/config.json
    python3 eval/personal_lora_pilot.py --verify-reload --config <root>/config.json

Exit status:

- 0  run completed with the recorded terminal (``local_feasible`` or
     ``capacity_blocker``), or verify-reload PASS;
- 1  config/isolation/schema/internal error, or verify-reload FAIL;
- 3  ``environment_blocker``: pinned runtime, model identity or dataset
     identity cannot be bound.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import resource
import re
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import personal_lora_data as pld  # noqa: E402

TOOL_NAME = "personal_lora_pilot"
TOOL_VERSION = 1
IDENTITY_SCHEMA = "personal-lora-pilot-identity-v1"
MEASUREMENT_SCHEMA = "personal-lora-pilot-measurement-v1"
PROBES_SCHEMA = "personal-lora-pilot-probes-v1"
OBJECTIVE = "completion_only_raw_concat"
TERMINAL_FEASIBLE = "local_feasible"
TERMINAL_CAPACITY = "capacity_blocker"
TERMINAL_ENVIRONMENT = "environment_blocker"

DEFAULT_ALLOWED_ROOT = os.path.join(_REPO_ROOT, ".local-work",
                                    "personal-lora-pilot")
CONFIG_REL = "config.json"
IDENTITY_REL = "identity.json"
PROBES_REL = "run/probes.json"
MEASUREMENT_REL = "run/measurement.json"
VERIFICATION_REL = "run/verification.json"
ADAPTER_DIR_REL = "adapter"
ADAPTER_FILE_REL = "adapter/adapters.safetensors"
ADAPTER_CONFIG_REL = "adapter/adapter_config.json"
PUBLIC_REPORT_REL = "public-report.md"

PINNED_VERSIONS = (("mlx", "0.32.0"), ("mlx-lm", "0.31.3"),
                   ("numpy", "2.4.6"))

RANKS = (8, 16)
MICRO_BATCHES = (1, 2, 4, 8)
EFFECTIVE_BATCH = 8
LEARNING_RATE = 1e-4
WEIGHT_DECAY = 0.0
LORA_DROPOUT = 0.0
SEED = 176
LORA_MODULES = ("self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj",
                "self_attn.o_proj")
LORA_ALPHA_EQUALS_RANK = True
RELOAD_TOLERANCE = 1e-4
RELOAD_SUBSET_SIZE = 32
EVAL_SUBSET_SIZE = 192
DEFAULT_SUSTAINED_SECONDS = 1200.0
BUDGET_SECONDS = 12 * 3600.0
DEFAULT_RECOMMENDED_EPOCHS = 3
PROBE_WARMUP_GROUPS = 1
PROBE_MEASURED_GROUPS = 3
SUSTAINED_WARMUP_GROUPS = 2
SWAP_GROWTH_LIMIT_MB = 256.0
SYSTEM_SAMPLE_SECONDS = 10.0
SYSTEM_SAMPLE_LIMIT = 300
PROBE_TIE_TOLERANCE = 0.02

DATASET_SCHEMA = "personal-lora-completion-v1"
MANIFEST_SCHEMA = "personal-lora-data-manifest-v1"
TRAIN_FILE = "train.jsonl"
VALIDATION_FILE = "validation.jsonl"
TEST_FILE = "test.jsonl"
MANIFEST_FILE = "manifest.json"
SEALED_FILES = (VALIDATION_FILE, TEST_FILE)
REQUIRED_MODEL_FILES = ("config.json", "generation_config.json", "merges.txt",
                        "model.safetensors", "tokenizer.json",
                        "tokenizer_config.json", "vocab.json")

CONFIG_KEYS = frozenset(("artifact_root", "model_dir", "dataset_dir",
                         "freeze_commit", "expected", "run"))
EXPECTED_KEYS = frozenset(("train_sha256", "manifest_sha256",
                           "validation_sha256", "test_sha256"))
RUN_KEYS = frozenset((
    "ranks", "micro_batches", "effective_batch", "num_layers", "modules",
    "probe_warmup_groups", "probe_measured_groups", "sustained_seconds",
    "reload_subset", "eval_subset", "recommended_epochs",
))


class PilotError(Exception):
    """A blocking config, isolation, schema or internal error."""


class EnvironmentBlocker(PilotError):
    """A pinned identity or runtime requirement cannot be satisfied."""


class CapacityBlocker(PilotError):
    """The frozen envelope cannot complete the measured run."""


def resolve_path(path: str) -> str:
    return pld._resolve(path)


def config_path_from_repo(value: str) -> str:
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(_REPO_ROOT, expanded)


def lora_scale(rank: int) -> float:
    """MLX ``scale`` for standard LoRA with ``alpha = rank``."""
    if LORA_ALPHA_EQUALS_RANK:
        return float(rank) / float(rank)
    return float(rank)


def parse_swap_usage(text: str) -> Dict[str, float]:
    match = re.search(
        r"total = ([0-9.]+)([MG]),?\s*used = ([0-9.]+)([MG])", text)
    if not match:
        raise ValueError("unrecognized vm.swapusage output")

    def to_mb(value: str, unit: str) -> float:
        amount = float(value)
        return amount * 1024.0 if unit == "G" else amount

    return {
        "total_mb": to_mb(match.group(1), match.group(2)),
        "used_mb": to_mb(match.group(3), match.group(4)),
    }


def sample_system_state(sample_processes: bool = False) -> Dict[str, Any]:
    state = {
        "utc": pld.utc_now_iso(),
        "swap_used_mb": None,
        "thermal": "unavailable",
        "thermal_note": None,
        "top_process_cpu_percent": None,
        "top_process_name": None,
    }
    try:
        output = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True,
            timeout=10, check=False).stdout
        state["swap_used_mb"] = parse_swap_usage(output)["used_mb"]
    except Exception as error:  # pragma: no cover - host dependent
        state["swap_error"] = str(error)
    try:
        output = subprocess.run(
            ["pmset", "-g", "therm"], capture_output=True, text=True,
            timeout=10, check=False).stdout
        limit = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", output)
        if limit:
            state["thermal"] = "CPU_Speed_Limit=%s" % limit.group(1)
        else:
            state["thermal_note"] = output.strip().splitlines()[0] \
                if output.strip() else "empty therm output"
    except Exception as error:  # pragma: no cover - host dependent
        state["thermal_note"] = str(error)
    if sample_processes:
        try:
            output = subprocess.run(
                ["ps", "-Ao", "pcpu=,comm="], capture_output=True, text=True,
                timeout=10, check=False).stdout
            rows = []
            for line in output.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) != 2:
                    continue
                try:
                    rows.append((float(parts[0]), parts[1]))
                except ValueError:
                    continue
            rows.sort(reverse=True)
            if rows:
                state["top_process_cpu_percent"] = rows[0][0]
                state["top_process_name"] = os.path.basename(rows[0][1])
        except Exception as error:  # pragma: no cover - host dependent
            state["process_error"] = str(error)
    return state


def process_max_rss_mb() -> Optional[float]:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024.0 * 1024.0 if platform.system() == "Darwin" else 1024.0
    return round(usage / divisor, 3)


def machine_facts() -> Dict[str, Any]:
    facts = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    for key, command in (("model", ["sysctl", "-n", "hw.model"]),
                         ("memory_bytes", ["sysctl", "-n", "hw.memsize"]),
                         ("cpu_count", ["sysctl", "-n", "hw.ncpu"])):
        try:
            output = subprocess.run(command, capture_output=True, text=True,
                                    timeout=10, check=False).stdout.strip()
            facts[key] = int(output) if key.endswith(("bytes", "count")) \
                else output
        except Exception:  # pragma: no cover - host dependent
            facts[key] = None
    return facts


def runtime_versions() -> Dict[str, Optional[str]]:
    versions = {}
    for distribution, _pin in PINNED_VERSIONS:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def assert_pinned_versions(versions: Dict[str, Optional[str]]) -> None:
    mismatches = []
    for distribution, pin in PINNED_VERSIONS:
        if versions.get(distribution) != pin:
            mismatches.append("%s=%s (expected %s)"
                              % (distribution, versions.get(distribution),
                                 pin))
    if mismatches:
        raise EnvironmentBlocker(
            "pinned runtime mismatch: %s" % "; ".join(mismatches))


def require_mlx() -> Dict[str, Any]:
    try:
        import numpy
        import mlx.core
        import mlx.nn
        import mlx.optimizers
        from mlx.utils import tree_flatten, tree_map
        from mlx_lm import load as mlx_load
        from mlx_lm.tuner.utils import linear_to_lora_layers, load_adapters
    except Exception as error:
        raise EnvironmentBlocker("mlx runtime unavailable: %s" % error)
    return {
        "np": numpy,
        "mx": mlx.core,
        "nn": mlx.nn,
        "optim": mlx.optimizers,
        "tree_flatten": tree_flatten,
        "tree_map": tree_map,
        "mlx_load": mlx_load,
        "linear_to_lora_layers": linear_to_lora_layers,
        "load_adapters": load_adapters,
    }


def load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_private_json(root: str, relative: str, value: Any) -> str:
    return pld.private_write_bytes(
        root, relative,
        (pld.canonical_json(value) + "\n").encode("utf-8"))


def read_private_json(root: str, relative: str) -> Any:
    return load_json_file(pld.safe_target(root, relative))


def private_path_exists(root: str, relative: str) -> bool:
    return os.path.exists(pld.safe_target(root, relative))


def load_config(path: str) -> Dict[str, Any]:
    resolved = resolve_path(config_path_from_repo(path))
    if not os.path.isfile(resolved):
        raise PilotError("config file not found: %s" % path)
    try:
        raw = load_json_file(resolved)
    except ValueError as error:
        raise PilotError("config is not valid JSON") from error
    if not isinstance(raw, dict):
        raise PilotError("config must be a JSON object")
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise PilotError("config has unknown keys: %s" % ",".join(unknown))
    for key in ("artifact_root", "model_dir", "dataset_dir"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise PilotError("config key %s is required" % key)
    expected = raw.get("expected")
    if not isinstance(expected, dict):
        raise PilotError("config key expected is required")
    unexpected = sorted(set(expected) - EXPECTED_KEYS)
    if unexpected:
        raise PilotError("expected has unknown keys: %s"
                         % ",".join(unexpected))
    for key in sorted(EXPECTED_KEYS):
        value = expected.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise PilotError("expected.%s must be a sha256 hex digest" % key)
    run = raw.get("run")
    if run is None:
        run = {}
    if not isinstance(run, dict):
        raise PilotError("config key run must be an object")
    unknown_run = sorted(set(run) - RUN_KEYS)
    if unknown_run:
        raise PilotError("run has unknown keys: %s" % ",".join(unknown_run))
    return {
        "artifact_root": resolve_path(config_path_from_repo(
            raw["artifact_root"])),
        "model_dir": resolve_path(config_path_from_repo(raw["model_dir"])),
        "dataset_dir": resolve_path(config_path_from_repo(
            raw["dataset_dir"])),
        "freeze_commit": raw.get("freeze_commit"),
        "expected": {key: expected[key] for key in sorted(EXPECTED_KEYS)},
        "run": validate_run_section(run),
    }


def _require_int(value: Any, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or \
            value < minimum:
        raise PilotError("%s must be an integer >= %d" % (name, minimum))
    return value


def validate_run_section(run: Dict[str, Any]) -> Dict[str, Any]:
    ranks = run.get("ranks", list(RANKS))
    micro_batches = run.get("micro_batches", list(MICRO_BATCHES))
    if not isinstance(ranks, list) or not ranks or \
            any(isinstance(rank, bool) or rank not in RANKS
                for rank in ranks):
        raise PilotError("run.ranks must be a non-empty subset of %s"
                         % (list(RANKS),))
    if len(set(ranks)) != len(ranks):
        raise PilotError("run.ranks must not repeat")
    if not isinstance(micro_batches, list) or not micro_batches or \
            any(isinstance(micro, bool) or micro not in MICRO_BATCHES
                for micro in micro_batches):
        raise PilotError("run.micro_batches must be a non-empty subset of %s"
                         % (list(MICRO_BATCHES),))
    if len(set(micro_batches)) != len(micro_batches):
        raise PilotError("run.micro_batches must not repeat")
    effective_batch = run.get("effective_batch", EFFECTIVE_BATCH)
    if effective_batch != EFFECTIVE_BATCH:
        raise PilotError("run.effective_batch is frozen at %d"
                         % EFFECTIVE_BATCH)
    if any(EFFECTIVE_BATCH % micro for micro in micro_batches):
        raise PilotError("every run.micro_batches entry must divide %d"
                         % EFFECTIVE_BATCH)
    modules = run.get("modules", list(LORA_MODULES))
    if tuple(modules) != tuple(LORA_MODULES):
        raise PilotError("run.modules is frozen at %s" % (list(LORA_MODULES),))
    num_layers = run.get("num_layers")
    if num_layers is not None:
        num_layers = _require_int(num_layers, "run.num_layers")
    values = {
        "ranks": list(ranks),
        "micro_batches": list(micro_batches),
        "effective_batch": EFFECTIVE_BATCH,
        "num_layers": num_layers,
        "modules": list(LORA_MODULES),
        "probe_warmup_groups": _require_int(
            run.get("probe_warmup_groups", PROBE_WARMUP_GROUPS),
            "run.probe_warmup_groups"),
        "probe_measured_groups": _require_int(
            run.get("probe_measured_groups", PROBE_MEASURED_GROUPS),
            "run.probe_measured_groups"),
        "sustained_seconds": run.get("sustained_seconds",
                                     DEFAULT_SUSTAINED_SECONDS),
        "reload_subset": _require_int(
            run.get("reload_subset", RELOAD_SUBSET_SIZE),
            "run.reload_subset", 2),
        "eval_subset": _require_int(
            run.get("eval_subset", EVAL_SUBSET_SIZE), "run.eval_subset"),
        "recommended_epochs": _require_int(
            run.get("recommended_epochs", DEFAULT_RECOMMENDED_EPOCHS),
            "run.recommended_epochs"),
    }
    sustained = values["sustained_seconds"]
    if isinstance(sustained, bool) or not isinstance(sustained, (int, float)) \
            or sustained < DEFAULT_SUSTAINED_SECONDS:
        raise PilotError("run.sustained_seconds must be >= %.0f"
                         % DEFAULT_SUSTAINED_SECONDS)
    values["sustained_seconds"] = float(sustained)
    return values


def assert_causal_qwen3(model_config: Dict[str, Any]) -> None:
    if not isinstance(model_config, dict):
        raise EnvironmentBlocker("model config is not a JSON object")
    model_type = model_config.get("model_type")
    if model_type != "qwen3":
        raise EnvironmentBlocker(
            "model_type %r is not the required causal qwen3" % model_type)
    architectures = model_config.get("architectures") or []
    if "Qwen3ForCausalLM" not in architectures:
        raise EnvironmentBlocker(
            "architectures %r do not declare Qwen3ForCausalLM"
            % (architectures,))
    if any("Embedding" in str(entry) for entry in architectures):
        raise EnvironmentBlocker("an embedding architecture is not a "
                                 "causal language model substitute")
    if model_config.get("is_encoder_decoder"):
        raise EnvironmentBlocker("encoder-decoder models are not causal")
    if not model_config.get("num_hidden_layers"):
        raise EnvironmentBlocker("model config has no num_hidden_layers")


MODEL_CONFIG_FIELDS = (
    "model_type", "architectures", "num_hidden_layers", "hidden_size",
    "intermediate_size", "num_attention_heads", "num_key_value_heads",
    "head_dim", "tie_word_embeddings", "torch_dtype", "vocab_size",
    "max_position_embeddings", "rms_norm_eps", "rope_theta",
)


def identify_model_dir(model_dir: str) -> Dict[str, Any]:
    resolved = resolve_path(model_dir)
    if not os.path.isdir(resolved):
        raise EnvironmentBlocker("model directory not found")
    files = {}
    for name in sorted(os.listdir(resolved)):
        path = os.path.join(resolved, name)
        if os.path.isfile(path) and not os.path.islink(path):
            files[name] = {"sha256": pld.sha256_file(path),
                           "bytes": os.path.getsize(path)}
    missing = [name for name in REQUIRED_MODEL_FILES if name not in files]
    if missing:
        raise EnvironmentBlocker("model directory is missing: %s"
                                 % ",".join(missing))
    model_config = load_json_file(os.path.join(resolved, "config.json"))
    assert_causal_qwen3(model_config)
    summary = {field: model_config.get(field)
               for field in MODEL_CONFIG_FIELDS
               if model_config.get(field) is not None}
    return {
        "basename": os.path.basename(resolved),
        "composite_sha256": pld.sha256_text(pld.canonical_json(files)),
        "files": files,
        "config": summary,
    }


def count_lines(path: str) -> int:
    total = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += chunk.count(b"\n")
    return total


def identify_dataset(config: Dict[str, Any]) -> Dict[str, Any]:
    dataset_dir = resolve_path(config["dataset_dir"])
    if not os.path.isdir(dataset_dir):
        raise EnvironmentBlocker("dataset directory not found")
    paths = {}
    for name in (TRAIN_FILE, VALIDATION_FILE, TEST_FILE, MANIFEST_FILE):
        path = os.path.join(dataset_dir, name)
        if not os.path.isfile(path):
            raise EnvironmentBlocker("dataset file missing: %s" % name)
        paths[name] = path
    digests = {
        "train_sha256": pld.sha256_file(paths[TRAIN_FILE]),
        "manifest_sha256": pld.sha256_file(paths[MANIFEST_FILE]),
    }
    for name, key in ((VALIDATION_FILE, "validation_sha256"),
                      (TEST_FILE, "test_sha256")):
        digests[key] = pld.sha256_file(paths[name])
    expected = config["expected"]
    mismatches = [key for key in sorted(EXPECTED_KEYS)
                  if digests[key] != expected[key]]
    if mismatches:
        raise EnvironmentBlocker(
            "dataset identity mismatch for %s" % ",".join(mismatches))
    manifest = load_json_file(paths[MANIFEST_FILE])
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise EnvironmentBlocker("dataset manifest schema is not %s"
                                 % MANIFEST_SCHEMA)
    parts = (manifest.get("splits") or {}).get("parts") or {}
    train_part = parts.get("train") or {}
    if train_part.get("sha256") != digests["train_sha256"]:
        raise EnvironmentBlocker(
            "manifest train sha256 does not match train.jsonl")
    observed_lines = count_lines(paths[TRAIN_FILE])
    if train_part.get("lines") != observed_lines:
        raise EnvironmentBlocker(
            "manifest train line count does not match train.jsonl")
    return {
        "digests": digests,
        "train_lines": observed_lines,
        "freeze_commit": config.get("freeze_commit"),
        "manifest_created_at_utc": manifest.get("created_at_utc"),
        "training_samples": (manifest.get("audit") or {}).get("samples"),
        "validation_lines": (parts.get("validation") or {}).get("lines"),
        "test_lines": (parts.get("test") or {}).get("lines"),
    }


def load_train_examples(path: str) -> List[Dict[str, Any]]:
    examples = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise PilotError("train.jsonl line %d is blank" % line_number)
            try:
                record = json.loads(line)
            except ValueError as error:
                raise PilotError("train.jsonl line %d is not JSON"
                                 % line_number) from error
            if not isinstance(record, dict):
                raise PilotError("train.jsonl line %d is not an object"
                                 % line_number)
            if record.get("schema") != DATASET_SCHEMA:
                raise PilotError("train.jsonl line %d has unexpected schema"
                                 % line_number)
            if record.get("loss") != "completion_only":
                raise PilotError("train.jsonl line %d has unexpected loss "
                                 "intent" % line_number)
            prompt = record.get("prompt")
            completion = record.get("completion")
            if not isinstance(prompt, str) or not isinstance(completion, str):
                raise PilotError("train.jsonl line %d has non-text fields"
                                 % line_number)
            if not completion:
                raise PilotError("train.jsonl line %d has an empty completion"
                                 % line_number)
            provenance = record.get("provenance") or {}
            examples.append({
                "prompt": prompt,
                "completion": completion,
                "empty_context": bool(provenance.get("empty_context")),
            })
    return examples


class CompletionExample(object):
    """One completion-only example after tokenization and side assignment."""

    __slots__ = ("input_ids", "prompt_side", "total_tokens",
                 "spanning_tokens", "empty_context")

    def __init__(self, input_ids: List[int], prompt_side: int,
                 spanning_tokens: int, empty_context: bool):
        self.input_ids = list(input_ids)
        self.prompt_side = prompt_side
        self.total_tokens = len(self.input_ids)
        self.spanning_tokens = spanning_tokens
        self.empty_context = empty_context

    def target_count(self) -> int:
        return max(0, self.total_tokens - max(1, self.prompt_side))

    def trainable(self) -> bool:
        return self.total_tokens >= 2 and self.target_count() >= 1


def build_completion_example(
        tokenize: Callable[
            [str], Tuple[List[int], List[Optional[Tuple[int, int]]]]],
        prompt: str, completion: str, empty_context: bool = False
) -> CompletionExample:
    """Tokenize ``prompt + completion`` once and assign token sides.

    ``tokenize`` returns token ids and per-token character offsets into the
    concatenated string. ``None`` marks an input-only token (a tokenizer BOS).
    A token whose offset starts before the boundary is prompt-side; a token
    that starts before and ends after the boundary is prompt-side, counted as
    spanning, and never charged to the loss.
    """
    text = prompt + completion
    ids, offsets = tokenize(text)
    if len(ids) != len(offsets):
        raise PilotError("tokenizer returned %d ids but %d offsets"
                         % (len(ids), len(offsets)))
    boundary = len(prompt)
    prompt_side = 0
    spanning = 0
    for offset in offsets:
        if offset is None:
            prompt_side += 1
            continue
        start, end = offset
        if start >= boundary:
            continue
        prompt_side += 1
        if end > boundary:
            spanning += 1
    return CompletionExample(ids, prompt_side, spanning, empty_context)


def make_offsets_tokenizer(tokenizer_wrapper) -> Callable:
    inner = getattr(tokenizer_wrapper, "_tokenizer", None)
    backend = getattr(inner, "backend_tokenizer", None)
    if backend is None:
        raise EnvironmentBlocker(
            "the pinned tokenizer exposes no backend tokenizer offsets")
    add_bos = bool(getattr(tokenizer_wrapper, "add_bos_token", False))
    bos_id = getattr(tokenizer_wrapper, "bos_token_id", None)
    if add_bos and bos_id is None:
        raise EnvironmentBlocker(
            "tokenizer requires a BOS but exposes no bos_token_id")

    def tokenize(text: str):
        encoding = backend.encode(text)
        offsets = [tuple(offset) for offset in encoding.offsets]
        ids = list(encoding.ids)
        if add_bos:
            ids = [bos_id] + ids
            offsets = [None] + offsets
        return ids, offsets

    return tokenize


def summarize_lengths(values: Sequence[float]) -> Dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}

    def pick(fraction: float) -> float:
        index = min(len(ordered) - 1,
                    max(0, int(round(fraction * (len(ordered) - 1)))))
        return ordered[index]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": pick(0.5),
        "p90": pick(0.9),
        "p99": pick(0.99),
        "max": ordered[-1],
        "mean": round(sum(ordered) / float(len(ordered)), 6),
    }


def aggregate_examples(examples: Sequence[CompletionExample],
                       empty_flags: Sequence[bool]) -> Dict[str, Any]:
    prompt_lengths = []
    completion_lengths = []
    spanning_examples = 0
    spanning_tokens = 0
    untrainable = 0
    empty_total = 0
    empty_trainable = 0
    for example, empty in zip(examples, empty_flags):
        prompt_lengths.append(example.prompt_side)
        completion_lengths.append(
            max(0, example.total_tokens - example.prompt_side))
        if example.spanning_tokens:
            spanning_examples += 1
            spanning_tokens += example.spanning_tokens
        if not example.trainable():
            untrainable += 1
        if empty:
            empty_total += 1
            if example.trainable():
                empty_trainable += 1
    return {
        "examples": len(examples),
        "trainable": len(examples) - untrainable,
        "untrainable": untrainable,
        "empty_context": {
            "examples": empty_total,
            "trainable": empty_trainable,
        },
        "prompt_tokens": summarize_lengths(prompt_lengths),
        "completion_side_tokens": summarize_lengths(completion_lengths),
        "boundary_spanning": {
            "examples": spanning_examples,
            "tokens": spanning_tokens,
        },
    }


class ShuffledStream(object):
    """Deterministic reshuffling example stream (one pass per epoch)."""

    def __init__(self, count: int, seed: int):
        self.count = count
        self.seed = seed
        self.epoch = 0
        self._order: List[int] = []
        self._position = 0

    def next_index(self) -> int:
        if self._position >= len(self._order):
            self.epoch += 1
            rng = random.Random(self.seed + self.epoch)
            order = list(range(self.count))
            rng.shuffle(order)
            self._order = order
            self._position = 0
        index = self._order[self._position]
        self._position += 1
        return index

    def next_batch(self, size: int) -> List[int]:
        return [self.next_index() for _ in range(size)]


def batch_rows(examples: Sequence[CompletionExample],
               indices: Sequence[int]) -> Tuple[List[List[int]],
                                                List[Tuple[int, int]], int]:
    rows = [examples[index].input_ids for index in indices]
    width = max(len(row) for row in rows)
    padded = [list(row) + [0] * (width - len(row)) for row in rows]
    lengths = [(examples[index].prompt_side, examples[index].total_tokens)
               for index in indices]
    return padded, lengths, width


def target_positions(lengths: Sequence[Tuple[int, int]]) -> List[List[int]]:
    return [[step for step in range(1, total) if step >= prompt_side]
            for prompt_side, total in lengths]


def selective_indices(count: int, subset: int, seed: int) -> List[int]:
    if subset >= count:
        return list(range(count))
    rng = random.Random(seed)
    return sorted(rng.sample(range(count), subset))


def choose_envelope(probes: Sequence[Dict[str, Any]]
                    ) -> Optional[Dict[str, Any]]:
    passed = [probe for probe in probes if probe.get("status") == "pass"]
    if not passed:
        return None
    best_rate = max(float(probe["examples_per_second"])
                    for probe in passed)
    near = [probe for probe in passed
            if float(probe["examples_per_second"])
            >= best_rate * (1.0 - PROBE_TIE_TOLERANCE)]
    near.sort(key=lambda probe: (-int(probe["rank"]),
                                 -int(probe["micro_batch"])))
    return near[0]


def estimate_full_run(trainable_examples: int, group_seconds: float,
                      per_example_eval_seconds: float, save_seconds: float,
                      validation_examples: int, epochs: int) -> Dict[str, Any]:
    steps_per_epoch = int(math.ceil(
        trainable_examples / float(EFFECTIVE_BATCH)))
    epoch_seconds = steps_per_epoch * group_seconds
    validation_seconds = validation_examples * per_example_eval_seconds
    checkpoint_seconds = save_seconds
    total_seconds = epochs * (epoch_seconds + validation_seconds
                              + checkpoint_seconds)
    return {
        "effective_batch": EFFECTIVE_BATCH,
        "optimizer_steps_per_epoch": steps_per_epoch,
        "epoch_seconds": epoch_seconds,
        "validation_seconds_per_epoch": validation_seconds,
        "checkpoint_seconds_per_epoch": checkpoint_seconds,
        "epochs": epochs,
        "total_seconds": total_seconds,
        "total_hours": total_seconds / 3600.0,
        "budget_hours": BUDGET_SECONDS / 3600.0,
        "within_budget": total_seconds <= BUDGET_SECONDS,
    }


def trainable_digest(backend: Dict[str, Any], model) -> Tuple[str, int]:
    mx = backend["mx"]
    weights = backend["tree_flatten"](model.trainable_parameters())
    digest = hashlib.sha256()
    arrays = []
    total = 0
    for name, value in weights:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(repr(tuple(value.shape)).encode("utf-8"))
        arrays.append(value.astype(mx.float32))
        total += int(value.size)
    mx.eval(arrays)
    for value in arrays:
        digest.update(backend["np"].asarray(value).tobytes())
    return digest.hexdigest(), total


def make_loss_fn(backend: Dict[str, Any]) -> Callable:
    """Completion-only loss; right-padding targets are never charged.

    Target position ``t`` (1-based over the row) contributes only when
    ``t >= prompt_side`` and ``t < total_tokens``, so the first padding token
    of a row shorter than the batch width is excluded, exactly like the
    larger row's impossible position ``t == total_tokens``.
    """
    mx = backend["mx"]
    nn = backend["nn"]

    def loss_fn(model, batch, lengths):
        inputs = batch[:, :-1]
        targets = batch[:, 1:]
        logits = model(inputs)
        steps = mx.arange(1, targets.shape[1] + 1)
        mask = mx.logical_and(steps >= lengths[:, 0:1],
                              steps < lengths[:, 1:])
        losses = nn.losses.cross_entropy(logits, targets) * mask
        return losses.astype(mx.float32).sum() / mask.sum()

    return loss_fn


def to_batch_tensors(backend: Dict[str, Any], rows: Sequence[Sequence[int]],
                     lengths: Sequence[Tuple[int, int]]):
    np = backend["np"]
    mx = backend["mx"]
    batch = mx.array(np.asarray(rows, dtype=np.int32))
    lengths_array = mx.array(np.asarray(lengths, dtype=np.int32))
    return batch, lengths_array


def micro_batches_for(backend: Dict[str, Any], examples, stream: ShuffledStream,
                      micro_batch: int, accumulate: int
                      ) -> List[Tuple[Any, Any]]:
    batches = []
    for _ in range(accumulate):
        indices = stream.next_batch(micro_batch)
        rows, lengths, _width = batch_rows(examples, indices)
        batches.append(to_batch_tensors(backend, rows, lengths))
    return batches


def accumulate_gradients(backend: Dict[str, Any], model,
                         loss_and_grad: Callable,
                         batches: Sequence[Tuple[Any, Any]],
                         stats: Optional[Dict[str, Any]] = None,
                         sample_hook: Optional[Callable[[], None]] = None
                         ) -> Tuple[List[float], Any]:
    mx = backend["mx"]
    tree_map = backend["tree_map"]
    total = None
    losses = []
    for batch, lengths in batches:
        if sample_hook is not None:
            sample_hook()
        start = time.perf_counter()
        value, grads = loss_and_grad(model, batch, lengths)
        mx.eval(value, grads)
        elapsed = time.perf_counter() - start
        losses.append(float(value.item()))
        if stats is not None:
            stats["micro_batch_seconds"].append(elapsed)
            stats["padded_widths"].append(int(batch.shape[1]))
            stats["micro_batches"] += 1
        total = grads if total is None else tree_map(
            lambda left, right: left + right, total, grads)
    return losses, total


def apply_optimizer_step(backend: Dict[str, Any], model, optimizer, grads,
                         count: int,
                         stats: Optional[Dict[str, Any]] = None) -> None:
    mx = backend["mx"]
    tree_map = backend["tree_map"]
    scaled = tree_map(lambda value: value / float(count), grads)
    start = time.perf_counter()
    optimizer.update(model, scaled)
    mx.eval(model.parameters(), optimizer.state)
    elapsed = time.perf_counter() - start
    if stats is not None:
        stats["update_seconds"].append(elapsed)
        stats["updates"] += 1


def new_stats() -> Dict[str, Any]:
    return {
        "micro_batch_seconds": [],
        "update_seconds": [],
        "padded_widths": [],
        "losses": [],
        "micro_batches": 0,
        "updates": 0,
    }


def phase_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    micro = stats["micro_batch_seconds"]
    updates = stats["update_seconds"]
    widths = stats["padded_widths"]
    losses = stats["losses"]
    return {
        "micro_batches": stats["micro_batches"],
        "optimizer_updates": stats["updates"],
        "micro_batch_seconds": summarize_lengths(micro) if micro else None,
        "update_seconds": summarize_lengths(updates) if updates else None,
        "padded_widths": summarize_lengths(widths) if widths else None,
        "padded_tokens_total": int(sum(widths)),
        "loss_mean": (round(sum(losses) / len(losses), 5) if losses
                      else None),
        "loss_first": (round(losses[0], 5) if losses else None),
        "loss_last": (round(losses[-1], 5) if losses else None),
    }


def run_groups(backend: Dict[str, Any], model, optimizer,
               loss_and_grad: Callable, examples, stream: ShuffledStream,
               micro_batch: int, accumulate: int, groups: int,
               stats: Dict[str, Any],
               sample_hook: Optional[Callable[[], None]] = None,
               deadline: Optional[float] = None) -> None:
    for _group in range(groups):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        batches = micro_batches_for(backend, examples, stream, micro_batch,
                                    accumulate)
        losses, grads = accumulate_gradients(
            backend, model, loss_and_grad, batches, stats, sample_hook)
        stats["losses"].extend(losses)
        apply_optimizer_step(backend, model, optimizer, grads, accumulate,
                             stats)


def system_sampler(limit: int = SYSTEM_SAMPLE_LIMIT):
    samples: List[Dict[str, Any]] = []
    last = {"time": 0.0}

    def hook():
        now = time.perf_counter()
        if samples and now - last["time"] < SYSTEM_SAMPLE_SECONDS:
            return
        if len(samples) >= limit:
            return
        last["time"] = now
        samples.append(sample_system_state())

    return samples, hook


def apply_lora(backend: Dict[str, Any], model, rank: int, num_layers: int,
               seed: int = SEED) -> None:
    mx = backend["mx"]
    mx.random.seed(seed)
    model.freeze()
    config = {
        "rank": rank,
        "scale": lora_scale(rank),
        "dropout": LORA_DROPOUT,
        "keys": list(LORA_MODULES),
    }
    backend["linear_to_lora_layers"](model, num_layers, config)


def load_base_model(backend: Dict[str, Any], model_dir: str):
    model, tokenizer = backend["mlx_load"](model_dir)
    backend["mx"].set_wired_limit(
        backend["mx"].device_info()["max_recommended_working_set_size"])
    return model, tokenizer


def probe_pair(backend: Dict[str, Any], model, examples, rank: int,
               micro_batch: int, warmup_groups: int, measured_groups: int,
               seed: int) -> Dict[str, Any]:
    mx = backend["mx"]
    optimizer = backend["optim"].AdamW(learning_rate=LEARNING_RATE,
                                       weight_decay=WEIGHT_DECAY)
    loss_and_grad = backend["nn"].value_and_grad(model, make_loss_fn(backend))
    model.train()
    accumulate = EFFECTIVE_BATCH // micro_batch
    stream = ShuffledStream(len(examples), seed)
    mx.reset_peak_memory()
    warmup_stats = new_stats()
    run_groups(backend, model, optimizer, loss_and_grad, examples, stream,
               micro_batch, accumulate, warmup_groups, warmup_stats)
    mx.clear_cache()
    swap_before = sample_system_state()["swap_used_mb"]
    measured = new_stats()
    run_groups(backend, model, optimizer, loss_and_grad, examples, stream,
               micro_batch, accumulate, measured_groups, measured)
    swap_after = sample_system_state()["swap_used_mb"]
    micro_total = sum(measured["micro_batch_seconds"])
    update_total = sum(measured["update_seconds"])
    group_total = micro_total + update_total
    examples_done = measured["micro_batches"] * micro_batch
    rate = examples_done / group_total if group_total > 0 else 0.0
    swap_growth = None
    if swap_before is not None and swap_after is not None:
        swap_growth = swap_after - swap_before
    status = "pass"
    reason = None
    if swap_growth is not None and swap_growth > SWAP_GROWTH_LIMIT_MB:
        status = "rejected"
        reason = "swap_growth"
    return {
        "rank": rank,
        "micro_batch": micro_batch,
        "accumulate": accumulate,
        "status": status,
        "reject_reason": reason,
        "examples_per_second": round(rate, 4),
        "warmup": phase_stats(warmup_stats),
        "measured": phase_stats(measured),
        "peak_memory_gb": round(mx.get_peak_memory() / 1e9, 4),
        "active_memory_gb": round(mx.get_active_memory() / 1e9, 4),
        "cache_memory_gb": round(mx.get_cache_memory() / 1e9, 4),
        "swap_before_mb": swap_before,
        "swap_after_mb": swap_after,
    }


def sustained_run(backend: Dict[str, Any], model, examples, rank: int,
                  micro_batch: int, seconds: float) -> Dict[str, Any]:
    mx = backend["mx"]
    optimizer = backend["optim"].AdamW(learning_rate=LEARNING_RATE,
                                       weight_decay=WEIGHT_DECAY)
    loss_and_grad = backend["nn"].value_and_grad(model, make_loss_fn(backend))
    model.train()
    accumulate = EFFECTIVE_BATCH // micro_batch
    stream = ShuffledStream(len(examples), SEED)
    samples, hook = system_sampler()
    samples.append(sample_system_state(sample_processes=True))
    mx.reset_peak_memory()
    warmup_stats = new_stats()
    warmup_start = time.perf_counter()
    run_groups(backend, model, optimizer, loss_and_grad, examples, stream,
               micro_batch, accumulate, SUSTAINED_WARMUP_GROUPS, warmup_stats,
               hook)
    warmup_seconds = time.perf_counter() - warmup_start
    mx.clear_cache()
    samples.append(sample_system_state())
    measured = new_stats()
    started = time.perf_counter()
    deadline = started + seconds
    while time.perf_counter() < deadline:
        run_groups(backend, model, optimizer, loss_and_grad, examples, stream,
                   micro_batch, accumulate, 1, measured, hook, deadline)
    measured_seconds = time.perf_counter() - started
    hook()
    mx.eval(model.parameters())
    if measured["micro_batches"] == 0:
        raise CapacityBlocker(
            "the sustained run recorded no post-warmup micro-batches")
    swap_values = [sample["swap_used_mb"] for sample in samples
                   if sample.get("swap_used_mb") is not None]
    swap_growth = None
    if swap_values:
        swap_growth = max(swap_values) - swap_values[0]
    summary = {
        "rank": rank,
        "micro_batch": micro_batch,
        "accumulate": accumulate,
        "target_seconds": seconds,
        "warmup_seconds": round(warmup_seconds, 4),
        "warmup": phase_stats(warmup_stats),
        "measured_seconds": round(measured_seconds, 4),
        "measured": phase_stats(measured),
        "samples": samples,
        "peak_memory_gb": round(mx.get_peak_memory() / 1e9, 4),
        "active_memory_gb": round(mx.get_active_memory() / 1e9, 4),
        "cache_memory_gb": round(mx.get_cache_memory() / 1e9, 4),
        "pilot_max_rss_mb": process_max_rss_mb(),
        "swap_start_mb": swap_values[0] if swap_values else None,
        "swap_end_mb": swap_values[-1] if swap_values else None,
        "swap_growth_mb": swap_growth,
        "oom": False,
        "swap_growth_exceeded": bool(
            swap_growth is not None and swap_growth > SWAP_GROWTH_LIMIT_MB),
        "finished_utc": pld.utc_now_iso(),
    }
    return summary


def completion_logsums(backend: Dict[str, Any], model, examples,
                       indices: Sequence[int]) -> List[float]:
    mx = backend["mx"]
    model.eval()
    results = []
    for index in indices:
        example = examples[index]
        if example.total_tokens < 2:
            raise PilotError("completion log-sum needs at least two tokens")
        ids = mx.array([example.input_ids])
        logits = model(ids[:, :-1]).astype(mx.float32)
        log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        targets = ids[0, 1:]
        picked = mx.take_along_axis(log_probs[0], targets[:, None],
                                    axis=-1)[:, 0]
        positions = mx.arange(1, example.total_tokens)
        mask = (positions >= max(1, example.prompt_side)).astype(mx.float32)
        value = (picked * mask).sum()
        mx.eval(value)
        results.append(float(value.item()))
    return results


def save_adapter(backend: Dict[str, Any], model, root: str, metadata: Dict,
                 rank: int, num_layers: int) -> Dict[str, Any]:
    mx = backend["mx"]
    weights = dict(backend["tree_flatten"](model.trainable_parameters()))
    mx.eval(list(weights.values()))
    adapter_dir = pld.ensure_private_dir(root, ADAPTER_DIR_REL)
    adapter_file = pld.safe_target(root, ADAPTER_FILE_REL)
    start = time.perf_counter()
    mx.save_safetensors(adapter_file, weights)
    elapsed = time.perf_counter() - start
    os.chmod(adapter_file, 0o600)
    adapter_config = {
        "fine_tune_type": "lora",
        "num_layers": num_layers,
        "lora_parameters": {
            "rank": rank,
            "scale": lora_scale(rank),
            "dropout": LORA_DROPOUT,
            "keys": list(LORA_MODULES),
        },
        "rank": rank,
        "alpha": rank,
        "mlx_scale": lora_scale(rank),
        "objective": OBJECTIVE,
        "seed": SEED,
    }
    adapter_config.update(metadata)
    write_private_json(root, ADAPTER_CONFIG_REL, adapter_config)
    return {
        "save_seconds": round(elapsed, 4),
        "adapter_sha256": pld.sha256_file(adapter_file),
        "adapter_bytes": os.path.getsize(adapter_file),
    }


def reload_adapter_model(backend: Dict[str, Any], model_dir: str, root: str):
    adapter_dir = pld.safe_target(root, ADAPTER_DIR_REL)
    model, tokenizer = load_base_model(backend, model_dir)
    backend["load_adapters"](model, adapter_dir)
    model.eval()
    return model, tokenizer


def eval_cost(backend: Dict[str, Any], model, examples,
              indices) -> Dict[str, Any]:
    if not indices:
        raise PilotError("eval subset is empty after trainability filter")
    start = time.perf_counter()
    completion_logsums(backend, model, examples, indices)
    elapsed = time.perf_counter() - start
    return {
        "examples": len(indices),
        "seconds": round(elapsed, 4),
        "per_example_seconds": elapsed / len(indices),
    }


def render_public_report(identity: Dict[str, Any],
                         measurement: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Local MLX LoRA pilot — desensitized report")
    lines.append("")
    lines.append("Contract AC-176-v1 (Habit130/squirrel#176). Aggregate "
                 "evidence only: no prompt/completion text, no event "
                 "identifiers, no absolute private paths.")
    lines.append("")
    lines.append("## Identities")
    lines.append("")
    lines.append("- terminal: `%s`" % measurement.get("terminal"))
    lines.append("- objective: `%s`" % OBJECTIVE)
    lines.append("- model: `%s` (causal Qwen3ForCausalLM), composite sha256 "
                 "`%s`"
                 % (identity["model"].get("basename"),
                    identity["model"].get("composite_sha256")))
    lines.append("- model config: `%s`"
                 % pld.canonical_json(identity["model"].get("config", {})))
    lines.append("- runtime pins: `%s`"
                 % pld.canonical_json(identity.get("versions", {})))
    lines.append("- dataset: freeze commit `%s`, train sha256 `%s`, "
                 "manifest sha256 `%s`"
                 % (identity["dataset"].get("freeze_commit"),
                    identity["dataset"]["digests"]["train_sha256"],
                    identity["dataset"]["digests"]["manifest_sha256"]))
    lines.append("- sealed files (checksum only, never parsed): "
                 "validation `%s`, test `%s`"
                 % (identity["dataset"]["digests"]["validation_sha256"],
                    identity["dataset"]["digests"]["test_sha256"]))
    lines.append("- machine: `%s`; pinned versions asserted: `%s`"
                 % (pld.canonical_json(identity.get("machine", {})),
                    pld.canonical_json(identity.get("pinned_versions", {}))))
    device = identity.get("runtime_device")
    if device:
        lines.append("- runtime device: `%s`" % pld.canonical_json(device))
    tokenizer = identity.get("tokenizer")
    if tokenizer:
        lines.append("- tokenizer: `%s` via `%s`, add_bos `%s`, add_eos `%s`, "
                     "vocab %s"
                     % (tokenizer.get("class"), tokenizer.get("backend"),
                        tokenizer.get("add_bos_token"),
                        tokenizer.get("add_eos_token"),
                        tokenizer.get("vocab_size")))
    tokens = identity.get("token_aggregate", {})
    if tokens:
        lines.append("")
        lines.append("## Real train-partition token lengths (aggregate)")
        lines.append("")
        lines.append("- examples %s; trainable %s; untrainable %s "
                     "(single token or no completion-side target)"
                     % (tokens.get("examples"), tokens.get("trainable"),
                        tokens.get("untrainable")))
        lines.append("- empty-context examples %s (trainable %s)"
                     % (tokens["empty_context"]["examples"],
                        tokens["empty_context"]["trainable"]))
        lines.append("- prompt-side tokens `%s`"
                     % pld.canonical_json(tokens["prompt_tokens"]))
        lines.append("- completion-side tokens `%s`"
                     % pld.canonical_json(tokens["completion_side_tokens"]))
        lines.append("- boundary-spanning tokens: %s over %s examples "
                     "(charged to the prompt side, never to the loss)"
                     % (tokens["boundary_spanning"]["tokens"],
                        tokens["boundary_spanning"]["examples"]))
    probes = measurement.get("probes") or []
    if probes:
        lines.append("")
        lines.append("## Envelope probes (one per declared pair)")
        lines.append("")
        lines.append("| rank | micro-batch | accumulate | status | "
                     "examples/s | peak/active/cache GB | swap growth MB |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for probe in probes:
            growth = None
            if probe.get("swap_before_mb") is not None and \
                    probe.get("swap_after_mb") is not None:
                growth = round(probe["swap_after_mb"]
                               - probe["swap_before_mb"], 2)
            lines.append("| %s | %s | %s | %s%s | %s | %s/%s/%s | %s |"
                         % (probe["rank"], probe["micro_batch"],
                            probe["accumulate"], probe["status"],
                            "" if not probe.get("reject_reason")
                            else " (%s)" % probe["reject_reason"],
                            probe["examples_per_second"],
                            probe["peak_memory_gb"],
                            probe.get("active_memory_gb"),
                            probe.get("cache_memory_gb"), growth))
        chosen = measurement.get("chosen") or {}
        if chosen:
            lines.append("")
            lines.append("Chosen pair: rank %s, micro-batch %s "
                         "(selection: no sustained swap growth, then "
                         "examples/s, then rank 16 over 8)."
                         % (chosen.get("rank"), chosen.get("micro_batch")))
    sustained = measurement.get("sustained")
    if sustained:
        lines.append("")
        lines.append("## Sustained measured run (post-warmup)")
        lines.append("")
        measured = sustained["measured"]
        lines.append("- rank %s, micro-batch %s, accumulate %s, "
                     "effective batch %s, seed %s"
                     % (sustained["rank"], sustained["micro_batch"],
                        sustained["accumulate"], EFFECTIVE_BATCH, SEED))
        lines.append("- optimizer: AdamW, lr `%s`, weight decay `%s`"
                     % (LEARNING_RATE, WEIGHT_DECAY))
        lines.append("- measured wall time %ss (target %ss); warmup "
                     "separate %ss"
                     % (sustained["measured_seconds"],
                        sustained["target_seconds"],
                        sustained["warmup_seconds"]))
        lines.append("- micro-batches %s; optimizer updates %s; micro-batch "
                     "seconds `%s`"
                     % (measured["micro_batches"],
                        measured["optimizer_updates"],
                        pld.canonical_json(
                            measured["micro_batch_seconds"])))
        lines.append("- optimizer update seconds `%s`"
                     % pld.canonical_json(measured["update_seconds"]))
        lines.append("- padded widths `%s`; padded tokens total %s"
                     % (pld.canonical_json(measured["padded_widths"]),
                        measured["padded_tokens_total"]))
        lines.append("- loss first/last/mean `%s/%s/%s`"
                     % (measured["loss_first"], measured["loss_last"],
                        measured["loss_mean"]))
        thermal = [sample.get("thermal")
                   for sample in (sustained.get("samples") or [])[:3]]
        lines.append("- MLX peak/active/cache GB "
                     "`%s/%s/%s`; pilot max RSS MB %s"
                     % (sustained["peak_memory_gb"],
                        sustained.get("active_memory_gb"),
                        sustained.get("cache_memory_gb"),
                        sustained.get("pilot_max_rss_mb")))
        lines.append("- system swap start/end/growth MB "
                     "`%s/%s/%s` (system-wide trend after the post-warmup "
                     "baseline; process memory is the MLX/RSS line above); "
                     "thermal `%s`"
                     % (sustained["swap_start_mb"], sustained["swap_end_mb"],
                        sustained["swap_growth_mb"],
                        pld.canonical_json(thermal)))
    verification = measurement.get("verification")
    if verification:
        lines.append("")
        lines.append("## Trainable update and save/reload")
        lines.append("")
        lines.append("- adapter digest before/after training: `%s` -> `%s` "
                     "(changed: %s); trainable parameters %s"
                     % (verification["digest_before"],
                        verification["digest_after"],
                        verification["weights_changed"],
                        verification["trainable_parameters"]))
        lines.append("- adapter file sha256 `%s` (%s bytes); save %ss; "
                     "reload loader `%s`"
                     % (verification["adapter_sha256"],
                        verification["adapter_bytes"],
                        verification["save_seconds"],
                        verification["reload_loader"]))
        lines.append("- completion log-sum agreement on the frozen %s-example "
                     "train subset (%s): max abs diff `%s` (tolerance `%s`), "
                     "pass %s"
                     % (verification["subset_size"],
                        verification["subset_rule"],
                        verification["max_abs_diff"], RELOAD_TOLERANCE,
                        verification["agreement_pass"]))
    estimate = measurement.get("estimate")
    if estimate:
        lines.append("")
        lines.append("## Full-run estimate")
        lines.append("")
        lines.append("- trainable examples %s; steps per epoch %s; "
                     "recommended epochs %s"
                     % (measurement.get("trainable_examples"),
                        estimate["optimizer_steps_per_epoch"],
                        estimate["epochs"]))
        lines.append("- per-epoch train %sh; validation %ss; checkpoint "
                     "%ss (train-side measurements)"
                     % (round(estimate["epoch_seconds"] / 3600.0, 4),
                        round(estimate["validation_seconds_per_epoch"], 2),
                        round(estimate["checkpoint_seconds_per_epoch"], 2)))
        lines.append("- estimated total %sh against a %sh budget "
                     "(within budget: %s)"
                     % (round(estimate["total_hours"], 3),
                        estimate["budget_hours"],
                        estimate["within_budget"]))
        shape = measurement.get("recommended_shape")
        if shape:
            lines.append("- recommended #177 shape: `%s`"
                         % pld.canonical_json(shape))
    reasons = measurement.get("terminal_reasons") or []
    if reasons:
        lines.append("")
        lines.append("## Terminal reasons")
        lines.append("")
        for reason in reasons:
            lines.append("- %s" % reason)
    lines.append("")
    return "\n".join(lines)


def build_recommended_shape(rank: int, micro_batch: int,
                            epochs: int) -> Dict[str, Any]:
    return {
        "base_model": "Qwen3-0.6B-Base (causal, identity pinned above)",
        "objective": OBJECTIVE,
        "precision": "base weights bfloat16, LoRA and optimizer float32",
        "lora": {
            "rank": rank,
            "alpha": rank,
            "mlx_scale": lora_scale(rank),
            "dropout": LORA_DROPOUT,
            "modules": list(LORA_MODULES),
            "layers": "all decoder layers",
        },
        "batch": {
            "micro_batch": micro_batch,
            "gradient_accumulation": EFFECTIVE_BATCH // micro_batch,
            "effective_batch": EFFECTIVE_BATCH,
            "padding": "batch max",
        },
        "optimizer": {
            "name": "AdamW",
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "seed": SEED,
        },
        "epochs": epochs,
        "validation": "frozen validation partition, per-epoch loss only",
        "checkpoint": "per-epoch adapter save; final adapter kept",
    }


def binding(identity: Dict[str, Any], tool_sha: str,
            config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool_sha256": tool_sha,
        "model_composite_sha256": identity["model"]["composite_sha256"],
        "dataset": identity["dataset"]["digests"],
        "freeze_commit": identity["dataset"].get("freeze_commit"),
        "run": config["run"],
    }


def measurement_binding_matches(measurement: Dict[str, Any],
                                identity: Dict[str, Any], tool_sha: str,
                                config: Dict[str, Any]) -> bool:
    return (measurement.get("binding") or {}) == binding(identity, tool_sha,
                                                         config)


def verify_recorded_artifacts(root: str,
                              measurement: Dict[str, Any]) -> List[str]:
    problems = []
    adapter_file = pld.safe_target(root, ADAPTER_FILE_REL)
    if not os.path.isfile(adapter_file):
        problems.append("adapter file is missing")
    else:
        recorded = (measurement.get("verification") or {}).get(
            "adapter_sha256")
        actual = pld.sha256_file(adapter_file)
        if recorded != actual:
            problems.append("adapter file sha256 does not match the "
                            "recorded measurement")
    for relative in (ADAPTER_CONFIG_REL, VERIFICATION_REL, PUBLIC_REPORT_REL):
        if not os.path.isfile(pld.safe_target(root, relative)):
            problems.append("%s is missing" % relative)
    return problems


def finish(terminal: Optional[str], reasons: Sequence[str]) -> int:
    if terminal is None:
        raise PilotError("measurement finished without a terminal")
    return 0


def cmd_run(config_path: str, allowed_root: Optional[str] = None,
            protected_roots: Optional[Sequence[str]] = None) -> int:
    started = time.perf_counter()
    config = load_config(config_path)
    root = pld.prepare_artifact_root(
        config["artifact_root"],
        allowed_root if allowed_root is not None else DEFAULT_ALLOWED_ROOT,
        protected_roots)
    dataset_identity = identify_dataset(config)
    model_identity = identify_model_dir(config["model_dir"])
    versions = runtime_versions()
    assert_pinned_versions(versions)
    tool_sha = pld.sha256_file(os.path.abspath(__file__))
    identity = {
        "schema": IDENTITY_SCHEMA,
        "created_at_utc": pld.utc_now_iso(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION,
                 "sha256": tool_sha},
        "versions": versions,
        "pinned_versions": {name: pin for name, pin in PINNED_VERSIONS},
        "machine": machine_facts(),
        "model": model_identity,
        "dataset": dataset_identity,
    }
    write_private_json(root, IDENTITY_REL, identity)
    identity_seconds = time.perf_counter() - started
    current_binding = binding(identity, tool_sha, config)

    if private_path_exists(root, MEASUREMENT_REL):
        measurement = read_private_json(root, MEASUREMENT_REL)
        if not measurement_binding_matches(measurement, identity, tool_sha,
                                           config):
            raise PilotError(
                "a completed measurement exists but is bound to a different "
                "tool, dataset or run config; refusing to replace it")
        problems = verify_recorded_artifacts(root, measurement)
        if problems:
            raise PilotError("recorded measurement is incomplete: %s"
                             % "; ".join(problems))
        print("measurement_reused=true")
        print("terminal=%s" % measurement.get("terminal"))
        return finish(measurement.get("terminal"),
                      measurement.get("terminal_reasons") or [])

    examples = load_train_examples(
        pld.safe_target(config["dataset_dir"], TRAIN_FILE))
    backend = require_mlx()
    tokenize_started = time.perf_counter()
    model, tokenizer = load_base_model(backend, config["model_dir"])
    tokenize = make_offsets_tokenizer(tokenizer)
    tokenized = [build_completion_example(
        tokenize, record["prompt"], record["completion"],
        record["empty_context"]) for record in examples]
    tokenize_seconds = time.perf_counter() - tokenize_started
    identity["tokenizer"] = {
        "class": type(tokenizer).__name__,
        "backend": type(getattr(tokenizer, "_tokenizer", None)).__name__,
        "vocab_size": getattr(tokenizer, "vocab_size", None),
        "bos_token_id": getattr(tokenizer, "bos_token_id", None),
        "eos_token_id": getattr(tokenizer, "eos_token_id", None),
        "add_bos_token": bool(getattr(tokenizer, "add_bos_token", False)),
        "add_eos_token": bool(getattr(tokenizer, "add_eos_token", False)),
    }
    token_aggregate = aggregate_examples(
        tokenized, [record["empty_context"] for record in examples])
    identity["token_aggregate"] = token_aggregate
    identity["model"]["class"] = type(model).__name__
    identity["runtime_device"] = {
        "device": backend["mx"].device_info().get("device_name"),
        "architecture": backend["mx"].device_info().get("architecture"),
        "max_recommended_working_set_gb": round(
            backend["mx"].device_info()["max_recommended_working_set_size"]
            / 1e9, 3),
    }
    write_private_json(root, IDENTITY_REL, identity)
    print(pld.canonical_json(token_aggregate))

    trainable_indices = [index for index, example in enumerate(tokenized)
                         if example.trainable()]
    if not trainable_indices:
        raise CapacityBlocker("no trainable completion examples in the "
                              "train partition")
    trainable_examples = [tokenized[index] for index in trainable_indices]
    num_layers = config["run"]["num_layers"]
    if num_layers is None:
        num_layers = len(model.layers)
    if num_layers > len(model.layers):
        raise PilotError("run.num_layers exceeds the model layer count")
    del model

    probes_started = time.perf_counter()
    if private_path_exists(root, PROBES_REL):
        try:
            existing_probes = read_private_json(root, PROBES_REL)
        except ValueError as error:
            raise PilotError("existing probe table is not valid JSON"
                             ) from error
        if existing_probes.get("binding") != current_binding:
            raise PilotError("existing probe table is bound to a different "
                             "tool, dataset or run config; refusing to reuse "
                             "or replace it")
        if existing_probes.get("schema") != PROBES_SCHEMA:
            raise PilotError("existing probe table has an unexpected schema")
        probes = existing_probes.get("probes", [])
    else:
        probes = []
    recorded_pairs = {(probe["rank"], probe["micro_batch"])
                      for probe in probes}
    for rank in config["run"]["ranks"]:
        current_model = None
        for micro_batch in config["run"]["micro_batches"]:
            if (rank, micro_batch) in recorded_pairs:
                continue
            try:
                if current_model is None:
                    current_model, _ = load_base_model(backend,
                                                       config["model_dir"])
                    apply_lora(backend, current_model, rank, num_layers)
                entry = probe_pair(
                    backend, current_model, trainable_examples, rank,
                    micro_batch, config["run"]["probe_warmup_groups"],
                    config["run"]["probe_measured_groups"], SEED)
            except Exception as error:
                if not _looks_like_memory_error(error):
                    raise
                backend["mx"].clear_cache()
                entry = {
                    "rank": rank, "micro_batch": micro_batch,
                    "accumulate": EFFECTIVE_BATCH // micro_batch,
                    "status": "rejected", "reject_reason": "oom",
                    "examples_per_second": 0.0,
                    "warmup": None, "measured": None,
                    "peak_memory_gb": None,
                    "swap_before_mb": None, "swap_after_mb": None,
                }
            probes.append(entry)
            recorded_pairs.add((rank, micro_batch))
            write_private_json(root, PROBES_REL,
                               {"schema": PROBES_SCHEMA,
                                "binding": current_binding,
                                "probes": probes})
            print(pld.canonical_json(entry))
            backend["mx"].clear_cache()
        current_model = None
    probe_seconds = time.perf_counter() - probes_started

    chosen = choose_envelope(probes)
    setup_seconds = time.perf_counter() - started
    timing = {
        "identity_seconds": round(identity_seconds, 4),
        "tokenize_seconds": round(tokenize_seconds, 4),
        "probe_seconds": round(probe_seconds, 4),
    }
    if chosen is None:
        return finish_with_capacity(
            root, identity, current_binding, probes, None, None, timing,
            ["every declared (rank, micro-batch) probe was rejected or out "
             "of memory"], setup_seconds=setup_seconds)

    rank = int(chosen["rank"])
    micro_batch = int(chosen["micro_batch"])
    model, tokenizer = load_base_model(backend, config["model_dir"])
    apply_lora(backend, model, rank, num_layers)
    digest_before, trainable_params = trainable_digest(backend, model)
    try:
        sustained = sustained_run(backend, model, trainable_examples, rank,
                                  micro_batch,
                                  config["run"]["sustained_seconds"])
    except CapacityBlocker as error:
        return finish_with_capacity(
            root, identity, current_binding, probes, chosen, None, timing,
            [str(error)], setup_seconds=setup_seconds)
    except Exception as error:
        if not _looks_like_memory_error(error):
            raise
        backend["mx"].clear_cache()
        return finish_with_capacity(
            root, identity, current_binding, probes, chosen, None, timing,
            ["sustained run out of memory at rank %d micro-batch %d"
             % (rank, micro_batch)], setup_seconds=setup_seconds)

    digest_after, _ = trainable_digest(backend, model)
    reload_indices = trainable_indices[:config["run"]["reload_subset"]]
    scores_before = completion_logsums(backend, model, tokenized,
                                       reload_indices)
    adapter_meta = {
        "base_model_composite_sha256":
            identity["model"]["composite_sha256"],
        "dataset_train_sha256":
            identity["dataset"]["digests"]["train_sha256"],
        "freeze_commit": identity["dataset"].get("freeze_commit"),
    }
    adapter_info = save_adapter(backend, model, root, adapter_meta, rank,
                                num_layers)
    reloaded, _ = reload_adapter_model(backend, config["model_dir"], root)
    scores_after = completion_logsums(backend, reloaded, tokenized,
                                      reload_indices)
    max_diff = max((abs(left - right)
                    for left, right in zip(scores_before, scores_after)),
                   default=0.0)
    agreement = max_diff <= RELOAD_TOLERANCE
    verification = {
        "subset_size": len(reload_indices),
        "subset_rule": "first_%d_trainable_examples_in_file_order"
                       % config["run"]["reload_subset"],
        "scores_before_save": scores_before,
        "scores_after_reload": scores_after,
        "max_abs_diff": max_diff,
        "tolerance": RELOAD_TOLERANCE,
        "agreement_pass": agreement,
        "digest_before": digest_before,
        "digest_after": digest_after,
        "trainable_parameters": trainable_params,
        "weights_changed": digest_before != digest_after,
        "adapter_sha256": adapter_info["adapter_sha256"],
        "adapter_bytes": adapter_info["adapter_bytes"],
        "save_seconds": adapter_info["save_seconds"],
        "reload_loader": "mlx_lm.tuner.utils.load_adapters",
    }
    write_private_json(root, VERIFICATION_REL, verification)

    eval_indices = [index for index in selective_indices(
        len(tokenized), config["run"]["eval_subset"], SEED)
        if tokenized[index].trainable()]
    eval_result = eval_cost(backend, reloaded, tokenized, eval_indices)
    validation_examples = identity["dataset"]["validation_lines"] or 0
    micro_mean = sustained["measured"]["micro_batch_seconds"]["mean"]
    update_mean = sustained["measured"]["update_seconds"]["mean"]
    group_seconds = (micro_mean * sustained["accumulate"] + update_mean)
    estimate = estimate_full_run(
        len(trainable_examples), group_seconds,
        eval_result["per_example_seconds"], adapter_info["save_seconds"],
        validation_examples, config["run"]["recommended_epochs"])
    if not agreement:
        raise PilotError(
            "save/reload completion log-sum agreement failed: max abs diff "
            "%.8f > %.1e" % (max_diff, RELOAD_TOLERANCE))
    if not verification["weights_changed"]:
        raise PilotError("optimizer steps did not change the adapter "
                         "weights")
    if not estimate["within_budget"]:
        terminal = TERMINAL_CAPACITY
        reasons = ["measured estimate %.3f h exceeds the %.0f h budget"
                   % (estimate["total_hours"], BUDGET_SECONDS / 3600.0)]
    else:
        terminal = TERMINAL_FEASIBLE
        reasons = []
    measurement = {
        "schema": MEASUREMENT_SCHEMA,
        "terminal": terminal,
        "terminal_reasons": reasons,
        "binding": current_binding,
        "probes": probes,
        "chosen": chosen,
        "sustained": sustained,
        "verification": verification,
        "eval_cost": eval_result,
        "estimate": estimate,
        "trainable_examples": len(trainable_examples),
        "identity": identity,
        "recommended_shape": build_recommended_shape(
            rank, micro_batch, config["run"]["recommended_epochs"]),
        "timing": timing,
        "setup_seconds": round(setup_seconds, 4),
        "finished_at_utc": pld.utc_now_iso(),
    }
    write_private_json(root, MEASUREMENT_REL, measurement)
    pld.private_write_bytes(
        root, PUBLIC_REPORT_REL,
        render_public_report(identity, measurement).encode("utf-8"))
    violations = pld.verify_owner_only(root)
    if violations:
        raise PilotError("owner-only permission violation under the "
                         "artifact root: %s" % ",".join(violations))
    print(pld.canonical_json({
        "terminal": terminal,
        "chosen": {"rank": rank, "micro_batch": micro_batch},
        "measured_seconds": sustained["measured_seconds"],
        "micro_batch_seconds_mean": micro_mean,
        "update_seconds_mean": update_mean,
        "estimate": estimate,
        "agreement_max_abs_diff": max_diff,
        "adapter_sha256": adapter_info["adapter_sha256"],
    }))
    return finish(terminal, reasons)


def finish_with_capacity(root: str, identity: Dict[str, Any],
                         current_binding: Dict[str, Any], probes, chosen,
                         sustained, timing: Dict[str, Any],
                         reasons: List[str],
                         setup_seconds: float) -> int:
    measurement: Dict[str, Any] = {
        "schema": MEASUREMENT_SCHEMA,
        "terminal": TERMINAL_CAPACITY,
        "terminal_reasons": reasons,
        "binding": current_binding,
        "probes": probes,
        "chosen": chosen,
        "identity": identity,
        "timing": timing,
        "setup_seconds": round(setup_seconds, 4),
        "finished_at_utc": pld.utc_now_iso(),
    }
    if sustained is not None:
        measurement["sustained"] = sustained
    write_private_json(root, MEASUREMENT_REL, measurement)
    write_private_json(root, VERIFICATION_REL, {})
    pld.private_write_bytes(
        root, PUBLIC_REPORT_REL,
        render_public_report(identity, measurement).encode("utf-8"))
    print("terminal=%s" % TERMINAL_CAPACITY)
    print(pld.canonical_json({"terminal_reasons": reasons}))
    return 0


def _looks_like_memory_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in
               ("out of memory", "oom", "allocation", "bad_alloc",
                "resource limit", "memory limit"))


def cmd_verify_reload(config_path: str, allowed_root: Optional[str] = None,
                      protected_roots: Optional[Sequence[str]] = None) -> int:
    config = load_config(config_path)
    root = pld.prepare_artifact_root(
        config["artifact_root"],
        allowed_root if allowed_root is not None else DEFAULT_ALLOWED_ROOT,
        protected_roots)
    if not private_path_exists(root, MEASUREMENT_REL):
        raise PilotError("no completed measurement to verify")
    verification = read_private_json(root, VERIFICATION_REL)
    if not verification.get("agreement_pass"):
        raise PilotError("the recorded measurement did not pass the "
                         "save/reload agreement")
    adapter_file = pld.safe_target(root, ADAPTER_FILE_REL)
    if pld.sha256_file(adapter_file) != verification.get("adapter_sha256"):
        raise PilotError("adapter file sha256 does not match the recorded "
                         "verification")
    examples = load_train_examples(
        pld.safe_target(config["dataset_dir"], TRAIN_FILE))
    backend = require_mlx()
    tokenize = make_offsets_tokenizer(
        backend["mlx_load"](config["model_dir"])[1])
    tokenized = [build_completion_example(
        tokenize, record["prompt"], record["completion"],
        record["empty_context"]) for record in examples]
    trainable_indices = [index for index, example in enumerate(tokenized)
                         if example.trainable()]
    indices = trainable_indices[:int(verification.get(
        "subset_size", RELOAD_SUBSET_SIZE))]
    model, _ = reload_adapter_model(backend, config["model_dir"], root)
    scores = completion_logsums(backend, model, tokenized, indices)
    recorded = verification.get("scores_before_save") or []
    if len(recorded) != len(scores):
        raise PilotError("recorded score count does not match the frozen "
                         "subset")
    max_diff = max((abs(left - right)
                    for left, right in zip(recorded, scores)), default=0.0)
    passed = max_diff <= RELOAD_TOLERANCE
    print(pld.canonical_json({
        "verify_reload": "pass" if passed else "fail",
        "subset_size": len(scores),
        "max_abs_diff": max_diff,
        "tolerance": RELOAD_TOLERANCE,
        "adapter_sha256": verification.get("adapter_sha256"),
    }))
    return 0 if passed else 1


def _selftest_tokenizer(vocabulary: Dict[str, int],
                        bos_id: Optional[int] = None):
    calls = []

    def tokenize(text: str):
        calls.append(text)
        ids: List[int] = []
        offsets: List[Optional[Tuple[int, int]]] = []
        if bos_id is not None:
            ids.append(bos_id)
            offsets.append(None)
        position = 0
        while position < len(text):
            match = None
            for width in range(min(8, len(text) - position), 0, -1):
                candidate = text[position:position + width]
                if candidate in vocabulary:
                    match = (vocabulary[candidate], width)
                    break
            if match is None:
                raise PilotError("selftest tokenizer has no token at %d"
                                 % position)
            ids.append(match[0])
            offsets.append((position, position + match[1]))
            position += match[1]
        return ids, offsets

    return tokenize, calls


def self_test() -> List[str]:
    checks: List[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise PilotError("self-test failed: %s" % name)
        checks.append(name)

    check("lora_scale_alpha_equals_rank",
          lora_scale(8) == 1.0 and lora_scale(16) == 1.0)

    tokenize, calls = _selftest_tokenizer(
        {"a": 1, "b": 2, "c": 3, "d": 4})
    example = build_completion_example(tokenize, "ab", "cd")
    check("raw_concat_single_call", calls == ["abcd"])
    check("completion_side_targets",
          example.prompt_side == 2 and example.target_count() == 2)
    check("no_synthetic_special_tokens",
          example.total_tokens == 4 and example.spanning_tokens == 0)

    tokenize_merge, _ = _selftest_tokenizer(
        {"a": 1, "b": 2, "c": 3, "d": 4, "bcd": 7})
    merged = build_completion_example(tokenize_merge, "ab", "cd")
    check("boundary_spanning_token_is_prompt_side",
          merged.spanning_tokens == 1 and merged.prompt_side == 2
          and merged.target_count() == 0 and not merged.trainable())

    tokenize_bos, _ = _selftest_tokenizer({"a": 1, "b": 2}, bos_id=99)
    bos = build_completion_example(tokenize_bos, "a", "b")
    check("bos_is_input_only_prompt_side",
          bos.input_ids[0] == 99 and bos.prompt_side == 2
          and bos.target_count() == 1)

    empty_prompt = build_completion_example(
        _selftest_tokenizer({"a": 1, "b": 2})[0], "", "ab")
    check("empty_prompt_targets_start_after_first_token",
          empty_prompt.prompt_side == 0 and empty_prompt.target_count() == 1)
    single = build_completion_example(
        _selftest_tokenizer({"a": 1})[0], "", "a")
    check("single_token_example_untrainable", not single.trainable())

    rows, lengths, width = batch_rows([example, merged], [0, 1])
    check("batch_pads_to_batch_max",
          width == max(len(example.input_ids), len(merged.input_ids))
          and all(len(row) == width for row in rows))
    positions = target_positions(lengths)
    check("targets_exclude_prompt_side",
          all(step >= prompt_side
              for (prompt_side, _total), steps in zip(lengths, positions)
              for step in steps))

    stream = ShuffledStream(5, SEED)
    first_epoch = [stream.next_index() for _ in range(5)]
    check("stream_is_a_permutation", sorted(first_epoch) == list(range(5)))

    probes = [
        {"rank": 8, "micro_batch": 4, "status": "pass",
         "examples_per_second": 10.0},
        {"rank": 16, "micro_batch": 4, "status": "pass",
         "examples_per_second": 10.1},
        {"rank": 16, "micro_batch": 8, "status": "rejected",
         "reject_reason": "oom", "examples_per_second": 99.0},
    ]
    chosen = choose_envelope(probes)
    check("rank_16_wins_near_tie",
          chosen is not None and chosen["rank"] == 16)
    estimate = estimate_full_run(1000, 0.5, 0.01, 2.0, 100, 3)
    check("estimate_arithmetic",
          estimate["optimizer_steps_per_epoch"] == 125
          and estimate["epoch_seconds"] == 62.5
          and estimate["within_budget"])

    swap = parse_swap_usage(
        "total = 4096.00M  used = 1536.50M  free = 2559.50M  (encrypted)")
    check("swap_parse", swap["used_mb"] == 1536.5)
    return checks


def cmd_self_test() -> int:
    checks = self_test()
    for name in checks:
        print("self-test ok: %s" % name)
    print("self-test: PASS (%d checks)" % len(checks))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local MLX LoRA feasibility pilot (AC-176-v1)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true",
                       help="run objective and planning self-checks")
    group.add_argument("--run", action="store_true",
                       help="run the authorized measurement")
    group.add_argument("--verify-reload", action="store_true",
                       help="verify save/reload agreement from disk")
    parser.add_argument("--config", help="path to the private config JSON")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            return cmd_self_test()
        if not args.config:
            raise PilotError("--config is required with --run/--verify-reload")
        if args.run:
            return cmd_run(args.config)
        return cmd_verify_reload(args.config)
    except EnvironmentBlocker as error:
        print("terminal=%s" % TERMINAL_ENVIRONMENT)
        print("blocker=%s" % error)
        return 3
    except (PilotError, pld.PersonalLoraDataError) as error:
        print("error=%s" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
