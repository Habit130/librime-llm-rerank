#!/usr/bin/env python3
"""One frozen local MLX LoRA training run (Habit130/squirrel#177, AC-177-v1).

Trains one versioned personal LoRA adapter on the pinned causal
``Qwen3-0.6B-Base`` with the frozen completion-only objective, validates the
frozen ``validation.jsonl`` partition after every one of exactly three
epochs, and selects a checkpoint solely by the predeclared rule (lowest mean
completion-only validation loss; a later epoch wins an exact tie). The sealed
``test.jsonl`` is opened for checksumming only and is never parsed.

The objective and serialization seam is exactly the #176 one
(``personal_lora_pilot``): raw ``prompt + completion`` concatenation, one
tokenizer call, completion-only loss, a boundary-spanning token charged to
the prompt side and counted, and untrainable examples skipped and reported.
This runner imports that seam instead of reimplementing it.

Hyperparameters are frozen: LoRA rank 16, alpha 16, dropout 0, q/k/v/o on all
decoder layers; bf16 base weights with fp32 LoRA/optimizer; micro-batch 8,
accumulation 1 (effective batch 8), batch-max padding; AdamW lr 1e-4, weight
decay 0, seed 176; 3 epochs. There is no search, no extra grid and no early
stop; a config that deviates is refused before any run starts.

CLI (``python3`` is the ticket-local venv interpreter):

    python3 eval/personal_lora_train.py --self-test
    python3 eval/personal_lora_train.py --run --config <root>/config.json
    python3 eval/personal_lora_train.py --verify-reload --config <root>/config.json

Exit status:

- 0  ``--run`` recorded its terminal (``trained`` or a precise
     ``runtime_blocker`` / ``capacity_blocker``), or ``--verify-reload``
     PASS;
- 1  config/isolation/schema/internal error, or ``--verify-reload`` FAIL;
- 3  ``environment_blocker``: pinned runtime, model identity or dataset
     identity cannot be bound.

All private artifacts (identity, state, per-epoch checkpoints, selected
adapter, verification and the public report) stay under the ticket root with
owner-only permissions. The public report is aggregate-only: identities,
losses, wall clock, memory, cache-clear counts and trainable/untrainable
counts, never prompt/completion text, event identifiers or absolute private
paths.
"""

import argparse
import json
import math
import os
import random
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import personal_lora_data as pld  # noqa: E402
import personal_lora_pilot as plp  # noqa: E402

TOOL_NAME = "personal_lora_train"
TOOL_VERSION = 1
IDENTITY_SCHEMA = "personal-lora-train-identity-v1"
STATE_SCHEMA = "personal-lora-train-state-v1"
EPOCHS_SCHEMA = "personal-lora-train-epochs-v1"
MEASUREMENT_SCHEMA = "personal-lora-train-measurement-v1"
VERIFICATION_SCHEMA = "personal-lora-train-verification-v1"
OBJECTIVE = plp.OBJECTIVE

TERMINAL_TRAINED = "trained"
TERMINAL_RUNTIME = "runtime_blocker"
TERMINAL_CAPACITY = "capacity_blocker"
TERMINAL_ENVIRONMENT = "environment_blocker"

DEFAULT_ALLOWED_ROOT = os.path.join(_REPO_ROOT, ".local-work",
                                    "personal-lora-train")
IDENTITY_REL = "identity.json"
STATE_REL = "state.json"
EPOCHS_REL = "run/epochs.json"
MEASUREMENT_REL = "run/measurement.json"
VERIFICATION_REL = "run/verification.json"
PUBLIC_REPORT_REL = "public-report.md"
EPOCH_DIR_TEMPLATE = "epochs/epoch-%d"
SELECTED_DIR_REL = "selected"
ADAPTER_FILE = "adapters.safetensors"
ADAPTER_CONFIG_FILE = "adapter_config.json"

EPOCHS = 3
RANK = 16
ALPHA = 16
LORA_DROPOUT = 0.0
LORA_MODULES = tuple(plp.LORA_MODULES)
MICRO_BATCH = 8
GRADIENT_ACCUMULATION = 1
EFFECTIVE_BATCH = MICRO_BATCH * GRADIENT_ACCUMULATION
LEARNING_RATE = 1e-4
WEIGHT_DECAY = 0.0
SEED = 176
CACHE_CLEAR_THRESHOLD_BYTES = 2_000_000_000
RELOAD_TOLERANCE = 1e-4
RELOAD_SUBSET_SIZE = 32
BUDGET_SECONDS = 12 * 3600.0
SELECTION_RULE = "min_validation_completion_loss_later_epoch_tie_break"

FROZEN_FREEZE_COMMIT = "2076d0a6c92dbf57833b7a123ea54aab10ddd49d"
FROZEN_MODEL_COMPOSITE_SHA256 = (
    "f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa")
FROZEN_DATASET_DIGESTS = {
    "train_sha256":
        "c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2",
    "validation_sha256":
        "80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8bdeaa880",
    "manifest_sha256":
        "5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704774bae",
    "test_sha256":
        "12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a9f2d2b",
}

CONFIG_KEYS = frozenset(("artifact_root", "model_dir", "dataset_dir",
                         "freeze_commit", "expected", "run"))
EXPECTED_KEYS = frozenset(("train_sha256", "manifest_sha256",
                           "validation_sha256", "test_sha256",
                           "model_composite_sha256"))
RUN_KEYS = frozenset((
    "epochs", "rank", "alpha", "dropout", "modules", "micro_batch",
    "gradient_accumulation", "effective_batch", "learning_rate",
    "weight_decay", "seed", "num_layers",
))
SET_COUNTER_KEYS = ("threshold", "epoch_floor")


class TrainError(Exception):
    """A blocking config, isolation, schema or internal error."""


class EnvironmentBlocker(TrainError):
    """A pinned identity or runtime requirement cannot be satisfied."""


class CapacityBlocker(TrainError):
    """The frozen training run cannot complete on this machine."""


class RuntimeBudgetExceeded(TrainError):
    """The 12-hour wall-clock budget was exhausted."""


def require_mlx() -> Dict[str, Any]:
    backend = plp.require_mlx()
    backend["load_weights"] = (
        lambda model, path: model.load_weights(path, strict=False))
    return backend


def load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def private_path_exists(root: str, relative: str) -> bool:
    return plp.private_path_exists(root, relative)


def read_private_json(root: str, relative: str) -> Any:
    return plp.read_private_json(root, relative)


def write_private_json(root: str, relative: str, value: Any) -> str:
    return plp.write_private_json(root, relative, value)


def config_path_from_repo(value: str) -> str:
    return plp.config_path_from_repo(value)


def load_config(path: str) -> Dict[str, Any]:
    resolved = plp.resolve_path(config_path_from_repo(path))
    if not os.path.isfile(resolved):
        raise TrainError("config file not found: %s" % path)
    try:
        raw = load_json_file(resolved)
    except ValueError as error:
        raise TrainError("config is not valid JSON") from error
    if not isinstance(raw, dict):
        raise TrainError("config must be a JSON object")
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise TrainError("config has unknown keys: %s" % ",".join(unknown))
    for key in ("artifact_root", "model_dir", "dataset_dir"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise TrainError("config key %s is required" % key)
    expected = raw.get("expected")
    if not isinstance(expected, dict):
        raise TrainError("config key expected is required")
    unexpected = sorted(set(expected) - EXPECTED_KEYS)
    if unexpected:
        raise TrainError("expected has unknown keys: %s"
                         % ",".join(unexpected))
    for key in sorted(EXPECTED_KEYS):
        value = expected.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise TrainError("expected.%s must be a sha256 hex digest" % key)
    run = raw.get("run")
    if run is None:
        run = {}
    if not isinstance(run, dict):
        raise TrainError("config key run must be an object")
    unknown_run = sorted(set(run) - RUN_KEYS)
    if unknown_run:
        raise TrainError("run has unknown keys: %s" % ",".join(unknown_run))
    return {
        "artifact_root": plp.resolve_path(config_path_from_repo(
            raw["artifact_root"])),
        "model_dir": plp.resolve_path(config_path_from_repo(raw["model_dir"])),
        "dataset_dir": plp.resolve_path(config_path_from_repo(
            raw["dataset_dir"])),
        "freeze_commit": raw.get("freeze_commit"),
        "expected": {key: expected[key] for key in sorted(EXPECTED_KEYS)},
        "run": validate_run_section(run),
    }


def validate_run_section(run: Dict[str, Any]) -> Dict[str, Any]:
    """Return the frozen hyperparameters, refusing every deviation."""
    frozen = {
        "epochs": EPOCHS,
        "rank": RANK,
        "alpha": ALPHA,
        "dropout": LORA_DROPOUT,
        "modules": list(LORA_MODULES),
        "micro_batch": MICRO_BATCH,
        "gradient_accumulation": GRADIENT_ACCUMULATION,
        "effective_batch": EFFECTIVE_BATCH,
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "seed": SEED,
    }
    for key, expected in frozen.items():
        if key not in run:
            continue
        supplied = run[key]
        if key == "modules":
            if list(supplied or []) != list(LORA_MODULES):
                raise TrainError("run.modules is frozen at %s"
                                 % (list(LORA_MODULES),))
            continue
        if isinstance(supplied, bool) or supplied != expected:
            raise TrainError("run.%s is frozen at %r (supplied %r); the "
                             "contract allows no hyperparameter search"
                             % (key, expected, supplied))
    num_layers = run.get("num_layers")
    if num_layers is not None:
        if isinstance(num_layers, bool) or not isinstance(num_layers, int) \
                or num_layers < 1:
            raise TrainError("run.num_layers must be a positive integer or "
                             "null for all decoder layers")
    frozen["num_layers"] = num_layers
    return frozen


def config_sha256(run: Dict[str, Any]) -> str:
    return pld.sha256_text(pld.canonical_json(
        {"objective": OBJECTIVE, "run": run}))


def build_binding(tool_sha: str, model_identity: Dict[str, Any],
                  dataset_identity: Dict[str, Any], run: Dict[str, Any],
                  config_hash: str) -> Dict[str, Any]:
    return {
        "tool_sha256": tool_sha,
        "model_composite_sha256": model_identity["composite_sha256"],
        "dataset": dataset_identity["digests"],
        "freeze_commit": dataset_identity.get("freeze_commit"),
        "objective": OBJECTIVE,
        "config_sha256": config_hash,
        "run": run,
    }


def assert_frozen_identities(model_identity: Dict[str, Any],
                             dataset_identity: Dict[str, Any],
                             expected: Dict[str, str]) -> None:
    """Pin the #176/#175 identities independently of the mutable config."""
    problems = []
    if model_identity.get("composite_sha256") != expected.get(
            "model_composite_sha256"):
        problems.append("the model directory does not match the config "
                        "expected composite")
    if model_identity.get("composite_sha256") != FROZEN_MODEL_COMPOSITE_SHA256:
        problems.append("the model composite is not the frozen #176 identity")
    digests = dataset_identity.get("digests") or {}
    mismatches = [key for key in sorted(FROZEN_DATASET_DIGESTS)
                  if digests.get(key) != FROZEN_DATASET_DIGESTS[key]]
    if mismatches:
        problems.append("dataset files are not the frozen #175 freeze: %s"
                        % ",".join(mismatches))
    if dataset_identity.get("freeze_commit") != FROZEN_FREEZE_COMMIT:
        problems.append("the dataset freeze commit is not the #175 freeze")
    if problems:
        raise EnvironmentBlocker("; ".join(problems))


def load_examples(path: str, label: str) -> List[Dict[str, Any]]:
    """Parse one unsealed completion partition (train or validation)."""
    examples = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise TrainError("%s line %d is blank" % (label, line_number))
            try:
                record = json.loads(line)
            except ValueError as error:
                raise TrainError("%s line %d is not JSON"
                                 % (label, line_number)) from error
            if not isinstance(record, dict):
                raise TrainError("%s line %d is not an object"
                                 % (label, line_number))
            if record.get("schema") != plp.DATASET_SCHEMA:
                raise TrainError("%s line %d has unexpected schema"
                                 % (label, line_number))
            if record.get("loss") != "completion_only":
                raise TrainError("%s line %d has unexpected loss intent"
                                 % (label, line_number))
            prompt = record.get("prompt")
            completion = record.get("completion")
            if not isinstance(prompt, str) or not isinstance(completion, str):
                raise TrainError("%s line %d has non-text fields"
                                 % (label, line_number))
            if not completion:
                raise TrainError("%s line %d has an empty completion"
                                 % (label, line_number))
            provenance = record.get("provenance") or {}
            examples.append({
                "prompt": prompt,
                "completion": completion,
                "empty_context": bool(provenance.get("empty_context")),
            })
    return examples


def tokenize_examples(tokenize: Callable, examples: Sequence[Dict[str, Any]]
                      ) -> List[plp.CompletionExample]:
    return [plp.build_completion_example(
        tokenize, record["prompt"], record["completion"],
        record["empty_context"]) for record in examples]


def epoch_batches(count: int, epoch: int,
                  seed: int = SEED) -> List[List[int]]:
    """One deterministic shuffled pass: every index exactly once per epoch.

    Batches are ``MICRO_BATCH * GRADIENT_ACCUMULATION`` examples; the final
    batch is smaller when the count is not divisible.
    """
    if count < 0:
        raise TrainError("example count must not be negative")
    order = list(range(count))
    random.Random(seed + epoch).shuffle(order)
    size = MICRO_BATCH * GRADIENT_ACCUMULATION
    return [order[start:start + size] for start in range(0, count, size)]


def new_cache_counters() -> Dict[str, int]:
    return {key: 0 for key in SET_COUNTER_KEYS}


def guard_cache(backend: Dict[str, Any], counters: Dict[str, int]) -> None:
    """Clear the MLX allocator cache whenever it exceeds the frozen 2 GB."""
    if backend["mx"].get_cache_memory() > CACHE_CLEAR_THRESHOLD_BYTES:
        backend["mx"].clear_cache()
        counters["threshold"] += 1


def micro_batch_tensors(backend: Dict[str, Any], examples, indices):
    rows, lengths, _width = plp.batch_rows(examples, indices)
    return plp.to_batch_tensors(backend, rows, lengths)


def train_epoch(backend: Dict[str, Any], model, optimizer,
                loss_and_grad: Callable, examples, epoch: int,
                stats: Dict[str, Any], counters: Dict[str, int],
                deadline: Optional[float] = None) -> None:
    """One full shuffled epoch with a cache guard after every update."""
    model.train()
    for indices in epoch_batches(len(examples), epoch):
        if deadline is not None and time.perf_counter() >= deadline:
            raise RuntimeBudgetExceeded(
                "the %.0f h training budget was exhausted inside epoch %d"
                % (BUDGET_SECONDS / 3600.0, epoch))
        batches = [micro_batch_tensors(backend, examples, indices)]
        losses, grads = plp.accumulate_gradients(
            backend, model, loss_and_grad, batches, stats)
        plp.apply_optimizer_step(backend, model, optimizer, grads,
                                 GRADIENT_ACCUMULATION, stats)
        stats["losses"].extend(losses)
        guard_cache(backend, counters)


def completion_nll(backend: Dict[str, Any], model,
                   example: plp.CompletionExample) -> Tuple[float, int]:
    """Completion-side cross-entropy sum and target count for one example.

    The mask is the frozen #176 one: position ``t`` contributes only when
    ``t >= max(1, prompt_side)``, so no prompt-side token and no boundary
    spanning token is ever charged to the loss.
    """
    mx = backend["mx"]
    if example.total_tokens < 2:
        raise TrainError("completion loss needs at least two tokens")
    ids = mx.array([example.input_ids])
    logits = model(ids[:, :-1]).astype(mx.float32)
    log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
    targets = ids[0, 1:]
    picked = mx.take_along_axis(log_probs[0], targets[:, None], axis=-1)[:, 0]
    positions = mx.arange(1, example.total_tokens)
    mask = (positions >= max(1, example.prompt_side)).astype(mx.float32)
    total = mask.sum()
    nll = (-picked * mask).sum()
    mx.eval(nll, total)
    return float(nll.item()), int(total.item())


def partition_completion_loss(backend: Dict[str, Any], model,
                              examples: Sequence[plp.CompletionExample],
                              indices: Sequence[int],
                              cache_guard: Optional[Callable[[], None]] = None
                              ) -> Dict[str, Any]:
    """Token-weighted mean completion-only loss over the frozen mask."""
    model.eval()
    if not indices:
        raise TrainError("the validation partition has no trainable examples")
    nll_total = 0.0
    token_total = 0
    for index in indices:
        nll, tokens = completion_nll(backend, model, examples[index])
        nll_total += nll
        token_total += tokens
        if cache_guard is not None:
            cache_guard()
    if token_total <= 0:
        raise TrainError("the validation partition has no completion targets")
    mean_loss = nll_total / float(token_total)
    if not math.isfinite(mean_loss):
        raise TrainError("the validation loss is not finite")
    return {
        "mean_loss": mean_loss,
        "examples": len(indices),
        "completion_tokens": token_total,
    }


def select_epoch(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Lowest validation loss; an exact tie goes to the later epoch."""
    if not rows:
        raise TrainError("there are no epoch rows to select from")
    chosen = None
    for row in rows:
        loss = row.get("validation_loss")
        if isinstance(loss, bool) or not isinstance(loss, (int, float)) \
                or not math.isfinite(loss):
            raise TrainError("epoch %s has a non-finite validation loss"
                             % (row.get("epoch"),))
        if chosen is None or loss < chosen["validation_loss"] or (
                loss == chosen["validation_loss"]
                and row["epoch"] > chosen["epoch"]):
            chosen = row
    return chosen


def adapter_config(num_layers: int, metadata: Dict[str, Any]
                   ) -> Dict[str, Any]:
    config = {
        "fine_tune_type": "lora",
        "num_layers": num_layers,
        "lora_parameters": {
            "rank": RANK,
            "scale": plp.lora_scale(RANK),
            "dropout": LORA_DROPOUT,
            "keys": list(LORA_MODULES),
        },
        "rank": RANK,
        "alpha": ALPHA,
        "mlx_scale": plp.lora_scale(RANK),
        "objective": OBJECTIVE,
        "seed": SEED,
    }
    config.update(metadata)
    return config


def save_adapter_dir(backend: Dict[str, Any], model, root: str,
                     relative_dir: str, num_layers: int,
                     metadata: Dict[str, Any]) -> Dict[str, Any]:
    mx = backend["mx"]
    weights = dict(backend["tree_flatten"](model.trainable_parameters()))
    mx.eval(list(weights.values()))
    pld.ensure_private_dir(root, relative_dir)
    adapter_file = pld.safe_target(root, relative_dir + "/" + ADAPTER_FILE)
    start = time.perf_counter()
    mx.save_safetensors(adapter_file, weights)
    elapsed = time.perf_counter() - start
    os.chmod(adapter_file, 0o600)
    write_private_json(root, relative_dir + "/" + ADAPTER_CONFIG_FILE,
                       adapter_config(num_layers, metadata))
    return {
        "adapter_sha256": pld.sha256_file(adapter_file),
        "adapter_bytes": os.path.getsize(adapter_file),
        "save_seconds": round(elapsed, 4),
    }


def copy_private_file(root: str, source_rel: str, target_rel: str) -> str:
    with open(pld.safe_target(root, source_rel), "rb") as handle:
        data = handle.read()
    return pld.private_write_bytes(root, target_rel, data)


def reload_adapter_model(backend: Dict[str, Any], model_dir: str, root: str,
                         relative_dir: str):
    model, tokenizer = plp.load_base_model(backend, model_dir)
    backend["load_adapters"](model, pld.safe_target(root, relative_dir))
    model.eval()
    return model, tokenizer


def trainable_indices(examples: Sequence[plp.CompletionExample]
                      ) -> List[int]:
    return [index for index, example in enumerate(examples)
            if example.trainable()]


def checkpoint_metadata(identity: Dict[str, Any], config_hash: str,
                        epoch: int) -> Dict[str, Any]:
    return {
        "epoch": epoch,
        "base_model_composite_sha256":
            identity["model"]["composite_sha256"],
        "dataset_train_sha256":
            identity["dataset"]["digests"]["train_sha256"],
        "freeze_commit": identity["dataset"].get("freeze_commit"),
        "config_sha256": config_hash,
    }


def build_identity(config: Dict[str, Any], dataset_identity: Dict[str, Any],
                   model_identity: Dict[str, Any],
                   versions: Dict[str, Optional[str]], tool_sha: str,
                   run: Dict[str, Any], config_hash: str,
                   binding: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": IDENTITY_SCHEMA,
        "created_at_utc": pld.utc_now_iso(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION,
                 "sha256": tool_sha},
        "versions": versions,
        "pinned_versions": {name: pin for name, pin in plp.PINNED_VERSIONS},
        "machine": plp.machine_facts(),
        "model": model_identity,
        "dataset": dataset_identity,
        "objective": OBJECTIVE,
        "selection_rule": SELECTION_RULE,
        "budget_seconds": BUDGET_SECONDS,
        "reload_tolerance": RELOAD_TOLERANCE,
        "reload_subset_size": RELOAD_SUBSET_SIZE,
        "cache_clear_threshold_bytes": CACHE_CLEAR_THRESHOLD_BYTES,
        "config_sha256": config_hash,
        "run": run,
        "binding": binding,
    }


def assert_state(state: Dict[str, Any], binding: Dict[str, Any]) -> None:
    if state.get("schema") != STATE_SCHEMA:
        raise TrainError("state.json has an unexpected schema")
    if state.get("binding") != binding:
        raise TrainError(
            "a recorded run exists but is bound to a different tool, model, "
            "dataset or config; refusing to replace it")


def assert_identity(identity: Dict[str, Any], binding: Dict[str, Any]) -> None:
    if identity.get("schema") != IDENTITY_SCHEMA:
        raise TrainError("identity.json has an unexpected schema")
    if identity.get("binding") != binding:
        raise TrainError(
            "identity.json is bound to a different tool, model, dataset or "
            "config; refusing to replace it")


def read_epoch_rows(root: str, binding: Dict[str, Any]
                    ) -> List[Dict[str, Any]]:
    if not private_path_exists(root, EPOCHS_REL):
        return []
    recorded = read_private_json(root, EPOCHS_REL)
    if recorded.get("schema") != EPOCHS_SCHEMA:
        raise TrainError("run/epochs.json has an unexpected schema")
    if recorded.get("binding") != binding:
        raise TrainError(
            "run/epochs.json is bound to a different tool, model, dataset or "
            "config; refusing to reuse it")
    rows = recorded.get("rows")
    if not isinstance(rows, list):
        raise TrainError("run/epochs.json has no rows list")
    return rows


def write_epoch_rows(root: str, binding: Dict[str, Any],
                     rows: Sequence[Dict[str, Any]]) -> None:
    write_private_json(root, EPOCHS_REL, {
        "schema": EPOCHS_SCHEMA,
        "binding": binding,
        "rows": list(rows),
    })


def checkpoint_relative_dir(epoch: int) -> str:
    return EPOCH_DIR_TEMPLATE % epoch


def resume_requirements(root: str, rows: Sequence[Dict[str, Any]],
                        next_epoch: int) -> List[str]:
    problems = []
    expected = list(range(1, next_epoch))
    if [row.get("epoch") for row in rows] != expected:
        problems.append("completed epoch rows are not exactly %s" % expected)
        return problems
    for row in rows:
        for name in (ADAPTER_FILE, ADAPTER_CONFIG_FILE):
            relative = checkpoint_relative_dir(row["epoch"]) + "/" + name
            if not os.path.isfile(pld.safe_target(root, relative)):
                problems.append("%s is missing" % relative)
    return problems


def verify_completed_artifacts(root: str, rows: Sequence[Dict[str, Any]],
                               state: Dict[str, Any]) -> List[str]:
    problems = []
    required = [SELECTED_DIR_REL + "/" + ADAPTER_FILE,
                SELECTED_DIR_REL + "/" + ADAPTER_CONFIG_FILE,
                EPOCHS_REL, VERIFICATION_REL, MEASUREMENT_REL,
                PUBLIC_REPORT_REL]
    for relative in required:
        if not os.path.isfile(pld.safe_target(root, relative)):
            problems.append("%s is missing" % relative)
    if [row.get("epoch") for row in rows] != list(range(1, EPOCHS + 1)):
        problems.append("the recorded epoch rows are not all of 1..%d"
                        % EPOCHS)
    if not problems:
        verification = read_private_json(root, VERIFICATION_REL)
        actual = pld.sha256_file(pld.safe_target(
            root, SELECTED_DIR_REL + "/" + ADAPTER_FILE))
        if verification.get("selected_adapter_sha256") != actual:
            problems.append("the selected adapter sha256 does not match the "
                            "recorded verification")
        if not verification.get("agreement_pass"):
            problems.append("the recorded verification did not pass")
        if state.get("selected_epoch") != verification.get(
                "selected_epoch"):
            problems.append("the selected epoch does not match the recorded "
                            "verification")
    for row in rows:
        relative = checkpoint_relative_dir(row["epoch"]) + "/" + ADAPTER_FILE
        if not os.path.isfile(pld.safe_target(root, relative)):
            problems.append("%s is missing" % relative)
    return problems


def finish_terminal(root: str, state: Dict[str, Any], rows: Sequence[Dict],
                    identity: Dict[str, Any], binding: Dict[str, Any],
                    terminal: str, reasons: Sequence[str],
                    wall_clock_seconds: float, training_seconds: float,
                    peak_memory: Dict[str, Any],
                    cache_counters: Dict[str, int],
                    resumed_from_epoch: Optional[int],
                    verification: Optional[Dict[str, Any]],
                    selected: Optional[Dict[str, Any]],
                    trainable_count: int, untrainable_count: int,
                    validation_trainable: int) -> int:
    measurement = {
        "schema": MEASUREMENT_SCHEMA,
        "terminal": terminal,
        "terminal_reasons": list(reasons),
        "binding": binding,
        "config_sha256": binding["config_sha256"],
        "selection_rule": SELECTION_RULE,
        "selected_epoch": (selected or {}).get("epoch"),
        "epochs": list(rows),
        "training_seconds": round(training_seconds, 4),
        "wall_clock_seconds": round(wall_clock_seconds, 4),
        "budget_seconds": BUDGET_SECONDS,
        "within_budget": training_seconds <= BUDGET_SECONDS,
        "within_total_wall_clock": wall_clock_seconds <= BUDGET_SECONDS,
        "peak_memory": peak_memory,
        "process_max_rss_mb": plp.process_max_rss_mb(),
        "cache_clears": dict(cache_counters),
        "trainable_examples": trainable_count,
        "untrainable_examples": untrainable_count,
        "validation_trainable_examples": validation_trainable,
        "resumed_from_epoch": resumed_from_epoch,
        "verification": verification,
        "finished_at_utc": pld.utc_now_iso(),
    }
    write_private_json(root, MEASUREMENT_REL, measurement)
    state = dict(state)
    state["terminal"] = terminal
    state["terminal_reasons"] = list(reasons)
    state["selected_epoch"] = (selected or {}).get("epoch")
    state["training_seconds"] = round(training_seconds, 4)
    state["wall_clock_seconds"] = round(wall_clock_seconds, 4)
    state["updated_at_utc"] = pld.utc_now_iso()
    write_private_json(root, STATE_REL, state)
    pld.private_write_bytes(
        root, PUBLIC_REPORT_REL,
        render_public_report(identity, measurement).encode("utf-8"))
    violations = pld.verify_owner_only(root)
    if violations:
        raise TrainError("owner-only permission violation under the artifact "
                         "root: %s" % ",".join(violations))
    print("terminal=%s" % terminal)
    print(pld.canonical_json({
        "terminal": terminal,
        "terminal_reasons": list(reasons),
        "selected_epoch": (selected or {}).get("epoch"),
        "wall_clock_seconds": round(wall_clock_seconds, 4),
        "cache_clears": dict(cache_counters),
        "peak_memory_gb": peak_memory.get("peak_gb"),
    }))
    return 0


def render_public_report(identity: Dict[str, Any],
                         measurement: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Frozen personal LoRA training run — desensitized report")
    lines.append("")
    lines.append("Contract AC-177-v1 (Habit130/squirrel#177). Aggregate "
                 "evidence only: no prompt/completion text, no event "
                 "identifiers, no absolute private paths.")
    lines.append("")
    lines.append("## Terminal")
    lines.append("")
    lines.append("- terminal: `%s`" % measurement.get("terminal"))
    reasons = measurement.get("terminal_reasons") or []
    for reason in reasons:
        lines.append("- reason: %s" % reason)
    lines.append("- objective: `%s`" % OBJECTIVE)
    lines.append("- selection rule: `%s`" % SELECTION_RULE)
    lines.append("- config sha256: `%s`"
                 % measurement.get("config_sha256"))
    lines.append("- training budget %.1f h covers the 3-epoch pass with "
                 "per-epoch validation/save; measured %.4f h (within budget: "
                 "%s)"
                 % (BUDGET_SECONDS / 3600.0,
                    measurement.get("training_seconds", 0.0) / 3600.0,
                    measurement.get("within_budget")))
    lines.append("- total wall clock including identity, tokenization and the "
                 "selected-adapter save/reload verification: %.4f s (%.4f h; "
                 "within the %.1f h envelope: %s)"
                 % (measurement.get("wall_clock_seconds", 0.0),
                    measurement.get("wall_clock_seconds", 0.0) / 3600.0,
                    BUDGET_SECONDS / 3600.0,
                    measurement.get("within_total_wall_clock")))
    lines.append("- resumed from a blocker: %s"
                 % ("yes (epoch %s)" % measurement.get("resumed_from_epoch")
                    if measurement.get("resumed_from_epoch")
                    else "no"))
    lines.append("")
    lines.append("## Identities")
    lines.append("")
    lines.append("- model: `%s` (causal Qwen3ForCausalLM), composite sha256 "
                 "`%s`"
                 % (identity["model"].get("basename"),
                    identity["model"].get("composite_sha256")))
    weights = (identity["model"].get("files") or {}).get("model.safetensors")
    if weights:
        lines.append("- base weight file: `model.safetensors` sha256 `%s` "
                     "(%s bytes)"
                     % (weights.get("sha256"), weights.get("bytes")))
    lines.append("- model config: `%s`"
                 % pld.canonical_json(identity["model"].get("config", {})))
    lines.append("- runtime pins: `%s`"
                 % pld.canonical_json(identity.get("pinned_versions", {})))
    lines.append("- dataset: freeze commit `%s`, train sha256 `%s`, "
                 "validation sha256 `%s`, manifest sha256 `%s`"
                 % (identity["dataset"].get("freeze_commit"),
                    identity["dataset"]["digests"]["train_sha256"],
                    identity["dataset"]["digests"]["validation_sha256"],
                    identity["dataset"]["digests"]["manifest_sha256"]))
    lines.append("- sealed test file (checksum only, never parsed): `%s`"
                 % identity["dataset"]["digests"]["test_sha256"])
    lines.append("- machine: `%s`"
                 % pld.canonical_json(identity.get("machine", {})))
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
    fresh = identity.get("fresh_lora") or {}
    lines.append("- fresh LoRA: warm start `%s`, initialization `%s`, source "
                 "adapter `%s`, trainable parameters %s"
                 % (fresh.get("warm_start"), fresh.get("initialization"),
                    fresh.get("source_adapter"),
                    fresh.get("trainable_parameters")))
    lines.append("")
    lines.append("## Frozen hyperparameters")
    lines.append("")
    lines.append("- config sha256 `%s`"
                 % measurement.get("config_sha256"))
    lines.append("- run `%s`" % pld.canonical_json(identity.get("run", {})))
    lines.append("- bf16 base weights with fp32 LoRA/optimizer; batch-max "
                 "padding; MLX cache cleared when it exceeds %s bytes and at "
                 "least once per epoch; no hyperparameter search, no early "
                 "stop"
                 % identity.get("cache_clear_threshold_bytes"))
    lines.append("")
    lines.append("## Token aggregates")
    lines.append("")
    for label in ("train", "validation"):
        tokens = identity.get("token_aggregate_%s" % label) or {}
        if not tokens:
            continue
        lines.append("- %s: examples %s; trainable %s; untrainable %s; "
                     "empty-context examples %s (trainable %s); "
                     "boundary-spanning %s tokens over %s examples (charged to "
                     "the prompt side); prompt-side tokens `%s`; "
                     "completion-side tokens `%s`"
                     % (label, tokens.get("examples"),
                        tokens.get("trainable"), tokens.get("untrainable"),
                        tokens["empty_context"]["examples"],
                        tokens["empty_context"]["trainable"],
                        tokens["boundary_spanning"]["tokens"],
                        tokens["boundary_spanning"]["examples"],
                        pld.canonical_json(tokens["prompt_tokens"]),
                        pld.canonical_json(
                            tokens["completion_side_tokens"])))
    lines.append("")
    lines.append("## Epochs")
    lines.append("")
    lines.append("| epoch | steps | train loss first/last/mean | "
                 "validation loss | seconds | cache clears | peak GB | "
                 "selected |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    selected_epoch = measurement.get("selected_epoch")
    for row in measurement.get("epochs") or []:
        train = row.get("train") or {}
        clears = row.get("cache_clears") or {}
        lines.append("| %s | %s | %s/%s/%s | %.6f | %.4f | %s | %s | %s |"
                     % (row.get("epoch"), row.get("steps"),
                        train.get("loss_first"), train.get("loss_last"),
                        train.get("loss_mean"), row.get("validation_loss"),
                        row.get("seconds"),
                        (clears.get("threshold", 0)
                         + clears.get("epoch_floor", 0)),
                        row.get("peak_memory_gb"),
                        "yes" if row.get("epoch") == selected_epoch else ""))
    lines.append("- trainable train examples %s; untrainable %s; trainable "
                 "validation examples %s"
                 % (measurement.get("trainable_examples"),
                    measurement.get("untrainable_examples"),
                    measurement.get("validation_trainable_examples")))
    lines.append("")
    lines.append("## Selection and reload")
    lines.append("")
    lines.append("- selected epoch: `%s` (rule: lowest validation "
                 "completion-only loss; a later epoch wins an exact tie)"
                 % selected_epoch)
    verification = measurement.get("verification") or {}
    if verification:
        lines.append("- selected adapter sha256 `%s` (%s bytes)"
                     % (verification.get("selected_adapter_sha256"),
                        verification.get("selected_adapter_bytes")))
        lines.append("- save/reload completion log-sum agreement on the "
                     "frozen %s-example train subset (`%s`): max abs diff `%s` "
                     "(tolerance `%s`), pass %s"
                     % (verification.get("subset_size"),
                        verification.get("subset_rule"),
                        verification.get("max_abs_diff"), RELOAD_TOLERANCE,
                        verification.get("agreement_pass")))
        lines.append("- trainable digest before/after training: `%s` -> `%s` "
                     "(changed: %s)"
                     % (verification.get("init_digest"),
                        verification.get("final_trainable_digest"),
                        verification.get("weights_changed")))
    lines.append("- wall clock: see the Terminal section; peak MLX memory "
                 "`%s`; process max RSS MB %s; cache clears `%s`"
                 % (pld.canonical_json(measurement.get("peak_memory")),
                    measurement.get("process_max_rss_mb"),
                    pld.canonical_json(measurement.get("cache_clears"))))
    lines.append("")
    return "\n".join(lines)


def run_one_epoch(backend: Dict[str, Any], model, optimizer,
                  loss_and_grad: Callable, train_examples,
                  validation_examples, validation_indices, subset_indices,
                  full_train_examples, epoch: int, root: str, num_layers: int,
                  identity: Dict[str, Any], config_hash: str,
                  global_counters: Dict[str, int],
                  deadline: Optional[float]) -> Dict[str, Any]:
    mx = backend["mx"]
    epoch_started = time.perf_counter()
    stats = plp.new_stats()
    counters = new_cache_counters()
    train_epoch(backend, model, optimizer, loss_and_grad, train_examples,
                epoch, stats, counters, deadline)
    mx.clear_cache()
    counters["epoch_floor"] += 1
    validation = partition_completion_loss(
        backend, model, validation_examples, validation_indices,
        lambda: guard_cache(backend, counters))
    model.eval()
    subset_scores = plp.completion_logsums(
        backend, model, full_train_examples, subset_indices)
    checkpoint = save_adapter_dir(
        backend, model, root, checkpoint_relative_dir(epoch), num_layers,
        checkpoint_metadata(identity, config_hash, epoch))
    for key in SET_COUNTER_KEYS:
        global_counters[key] += counters[key]
    return {
        "epoch": epoch,
        "steps": stats["updates"],
        "examples": len(train_examples),
        "train": plp.phase_stats(stats),
        "validation_loss": validation["mean_loss"],
        "validation_examples": validation["examples"],
        "validation_completion_tokens": validation["completion_tokens"],
        "seconds": round(time.perf_counter() - epoch_started, 4),
        "cache_clears": dict(counters),
        "peak_memory_gb": round(mx.get_peak_memory() / 1e9, 4),
        "checkpoint": checkpoint,
        "subset_indices": list(subset_indices),
        "subset_logsums": subset_scores,
    }


def cmd_run(config_path: str, allowed_root: Optional[str] = None,
            protected_roots: Optional[Sequence[str]] = None) -> int:
    started = time.perf_counter()
    config = load_config(config_path)
    root = pld.prepare_artifact_root(
        config["artifact_root"],
        allowed_root if allowed_root is not None else DEFAULT_ALLOWED_ROOT,
        protected_roots)
    run_section = config["run"]
    config_hash = config_sha256(run_section)
    dataset_identity = plp.identify_dataset(config)
    model_identity = plp.identify_model_dir(config["model_dir"])
    assert_frozen_identities(model_identity, dataset_identity,
                             config["expected"])
    versions = plp.runtime_versions()
    plp.assert_pinned_versions(versions)
    tool_sha = pld.sha256_file(os.path.abspath(__file__))
    binding = build_binding(tool_sha, model_identity, dataset_identity,
                            run_section, config_hash)

    state: Optional[Dict[str, Any]] = None
    resumed_from_epoch: Optional[int] = None
    rows: List[Dict[str, Any]] = []
    elapsed_before = 0.0
    training_seconds_before = 0.0
    if private_path_exists(root, STATE_REL):
        state = read_private_json(root, STATE_REL)
        assert_state(state, binding)
        if not private_path_exists(root, IDENTITY_REL):
            raise TrainError("state.json exists without identity.json")
        identity = read_private_json(root, IDENTITY_REL)
        assert_identity(identity, binding)
        terminal = state.get("terminal")
        if terminal == TERMINAL_TRAINED:
            rows = read_epoch_rows(root, binding)
            problems = verify_completed_artifacts(root, rows, state)
            if problems:
                raise TrainError("the completed run is incomplete: %s"
                                 % "; ".join(problems))
            print("run_reused=true")
            print(pld.canonical_json({
                "terminal": terminal,
                "selected_epoch": state.get("selected_epoch"),
            }))
            return 0
        if terminal not in (None, TERMINAL_RUNTIME, TERMINAL_CAPACITY):
            raise TrainError("state.json records an unexpected terminal %r"
                             % terminal)
        rows = read_epoch_rows(root, binding)
        next_epoch = state.get("next_epoch")
        if isinstance(next_epoch, bool) or not isinstance(next_epoch, int) \
                or not 1 <= next_epoch <= EPOCHS + 1:
            raise TrainError("state.json records an invalid next_epoch")
        rows = [row for row in rows if row.get("epoch") < next_epoch]
        problems = resume_requirements(root, rows, next_epoch)
        if problems:
            raise TrainError("resume checkpoints are incomplete: %s"
                             % "; ".join(problems))
        resumed_from_epoch = next_epoch
        elapsed_before = float(state.get("wall_clock_seconds") or 0.0)
        training_seconds_before = float(state.get("training_seconds") or 0.0)
        state["resumed_from_epoch"] = resumed_from_epoch
        state["updated_at_utc"] = pld.utc_now_iso()
        write_private_json(root, STATE_REL, state)
        print("resume_from_epoch=%d" % next_epoch)
    else:
        for relative in (IDENTITY_REL, EPOCHS_REL):
            if private_path_exists(root, relative):
                raise TrainError("%s exists without state.json; refusing to "
                                 "replace an incomplete artifact set"
                                 % relative)

    backend = require_mlx()
    model, tokenizer = plp.load_base_model(backend, config["model_dir"])
    tokenize = plp.make_offsets_tokenizer(tokenizer)
    train_records = load_examples(
        pld.safe_target(config["dataset_dir"], plp.TRAIN_FILE),
        plp.TRAIN_FILE)
    validation_records = load_examples(
        pld.safe_target(config["dataset_dir"], plp.VALIDATION_FILE),
        plp.VALIDATION_FILE)
    tokenized_train = tokenize_examples(tokenize, train_records)
    tokenized_validation = tokenize_examples(tokenize, validation_records)
    trainable_train = trainable_indices(tokenized_train)
    trainable_validation = trainable_indices(tokenized_validation)
    if not trainable_train:
        raise CapacityBlocker("no trainable train examples")
    if not trainable_validation:
        raise CapacityBlocker("no trainable validation examples")
    train_examples = [tokenized_train[index] for index in trainable_train]
    subset_indices = trainable_train[:RELOAD_SUBSET_SIZE]

    num_layers = run_section["num_layers"]
    if num_layers is None:
        num_layers = len(model.layers)
    elif num_layers != len(model.layers):
        raise TrainError("run.num_layers must cover all %d decoder layers; "
                         "the frozen LoRA shape is every decoder layer"
                         % len(model.layers))

    if state is None:
        plp.apply_lora(backend, model, RANK, num_layers, SEED)
        digest_before, trainable_parameters = plp.trainable_digest(
            backend, model)
        identity = build_identity(
            config, dataset_identity, model_identity, versions, tool_sha,
            run_section, config_hash, binding)
        identity["tokenizer"] = {
            "class": type(tokenizer).__name__,
            "backend": type(getattr(tokenizer, "_tokenizer", None)).__name__,
            "vocab_size": getattr(tokenizer, "vocab_size", None),
            "bos_token_id": getattr(tokenizer, "bos_token_id", None),
            "eos_token_id": getattr(tokenizer, "eos_token_id", None),
            "add_bos_token": bool(getattr(tokenizer, "add_bos_token", False)),
            "add_eos_token": bool(getattr(tokenizer, "add_eos_token", False)),
        }
        identity["model"]["class"] = type(model).__name__
        identity["runtime_device"] = {
            "device": backend["mx"].device_info().get("device_name"),
            "architecture": backend["mx"].device_info().get("architecture"),
            "max_recommended_working_set_gb": round(
                backend["mx"].device_info()["max_recommended_working_set_size"]
                / 1e9, 3),
        }
        identity["token_aggregate_train"] = plp.aggregate_examples(
            tokenized_train, [record["empty_context"]
                              for record in train_records])
        identity["token_aggregate_validation"] = plp.aggregate_examples(
            tokenized_validation, [record["empty_context"]
                                   for record in validation_records])
        identity["fresh_lora"] = {
            "warm_start": False,
            "initialization": "mlx_random_seed_%d" % SEED,
            "source_adapter": None,
            "trainable_parameters": trainable_parameters,
            "init_digest": digest_before,
        }
        write_private_json(root, IDENTITY_REL, identity)
        state = {
            "schema": STATE_SCHEMA,
            "binding": binding,
            "terminal": None,
            "terminal_reasons": [],
            "next_epoch": 1,
            "epochs_completed": 0,
            "selected_epoch": None,
            "resumed_from_epoch": None,
            "init_digest": digest_before,
            "wall_clock_seconds": 0.0,
            "training_seconds": 0.0,
            "started_at_utc": pld.utc_now_iso(),
            "updated_at_utc": pld.utc_now_iso(),
        }
        write_private_json(root, STATE_REL, state)
        write_epoch_rows(root, binding, [])
        start_epoch = 1
    else:
        identity = read_private_json(root, IDENTITY_REL)
        start_epoch = resumed_from_epoch
        plp.apply_lora(backend, model, RANK, num_layers, SEED)
        if start_epoch > 1:
            backend["load_weights"](
                model,
                pld.safe_target(
                    root, checkpoint_relative_dir(start_epoch - 1)
                    + "/" + ADAPTER_FILE))

    optimizer = backend["optim"].AdamW(learning_rate=LEARNING_RATE,
                                       weight_decay=WEIGHT_DECAY)
    loss_and_grad = backend["nn"].value_and_grad(model, plp.make_loss_fn(
        backend))
    backend["mx"].reset_peak_memory()
    global_counters = new_cache_counters()
    training_used = training_seconds_before
    terminal = None
    reasons: List[str] = []
    for epoch in range(start_epoch, EPOCHS + 1):
        remaining = BUDGET_SECONDS - training_used
        if remaining <= 0 or time.perf_counter() >= started + remaining:
            terminal = TERMINAL_RUNTIME
            reasons = ["the %.0f h training budget is exhausted; AC-177-v1 "
                       "does not grant fresh training time (the per-epoch "
                       "checkpoints are retained)"
                       % (BUDGET_SECONDS / 3600.0)]
            break
        try:
            row = run_one_epoch(
                backend, model, optimizer, loss_and_grad, train_examples,
                tokenized_validation, trainable_validation, subset_indices,
                tokenized_train, epoch, root, num_layers, identity,
                config_hash, global_counters, started + remaining)
        except RuntimeBudgetExceeded as error:
            terminal = TERMINAL_RUNTIME
            reasons = [str(error)]
            break
        except CapacityBlocker as error:
            terminal = TERMINAL_CAPACITY
            reasons = [str(error)]
            break
        except Exception as error:
            if not plp._looks_like_memory_error(error):
                raise
            backend["mx"].clear_cache()
            terminal = TERMINAL_CAPACITY
            reasons = ["training ran out of memory in epoch %d: %s"
                       % (epoch, error)]
            break
        rows.append(row)
        training_used += row["seconds"]
        elapsed = elapsed_before + (time.perf_counter() - started)
        state["next_epoch"] = epoch + 1
        state["epochs_completed"] = len(rows)
        state["wall_clock_seconds"] = round(elapsed, 4)
        state["training_seconds"] = round(training_used, 4)
        state["updated_at_utc"] = pld.utc_now_iso()
        write_epoch_rows(root, binding, rows)
        write_private_json(root, STATE_REL, state)
        train = row["train"]
        print(pld.canonical_json({
            "epoch": epoch,
            "train_loss_mean": train.get("loss_mean"),
            "validation_loss": round(row["validation_loss"], 6),
            "seconds": row["seconds"],
            "cache_clears": (row["cache_clears"]["threshold"]
                             + row["cache_clears"]["epoch_floor"]),
        }))
        if training_used > BUDGET_SECONDS:
            terminal = TERMINAL_RUNTIME
            reasons = ["the training wall clock %.4f h exceeds the %.0f h "
                       "budget after epoch %d"
                       % (training_used / 3600.0, BUDGET_SECONDS / 3600.0,
                          epoch)]
            break

    wall_clock = elapsed_before + (time.perf_counter() - started)
    peak_memory = {
        "peak_gb": round(backend["mx"].get_peak_memory() / 1e9, 4),
        "active_gb": round(backend["mx"].get_active_memory() / 1e9, 4),
        "cache_gb": round(backend["mx"].get_cache_memory() / 1e9, 4),
    }
    if terminal is not None:
        return finish_terminal(
            root, state, rows, identity, binding, terminal, reasons,
            wall_clock, training_used, peak_memory, global_counters,
            resumed_from_epoch, None, None, len(train_examples),
            identity["token_aggregate_train"]["untrainable"],
            len(trainable_validation))

    selected = select_epoch(rows)
    digest_after, _final_trainable = plp.trainable_digest(backend, model)
    copy_private_file(
        root, checkpoint_relative_dir(selected["epoch"]) + "/" + ADAPTER_FILE,
        SELECTED_DIR_REL + "/" + ADAPTER_FILE)
    copy_private_file(
        root, checkpoint_relative_dir(selected["epoch"]) + "/"
        + ADAPTER_CONFIG_FILE, SELECTED_DIR_REL + "/" + ADAPTER_CONFIG_FILE)
    selected_sha = pld.sha256_file(pld.safe_target(
        root, SELECTED_DIR_REL + "/" + ADAPTER_FILE))
    del model
    backend["mx"].clear_cache()
    reloaded, _tokenizer = reload_adapter_model(
        backend, config["model_dir"], root, SELECTED_DIR_REL)
    scores_after = plp.completion_logsums(
        backend, reloaded, tokenized_train, subset_indices)
    recorded = selected.get("subset_logsums") or []
    if len(recorded) != len(scores_after):
        raise TrainError("the recorded subset scores do not match the frozen "
                         "subset")
    max_diff = max((abs(left - right)
                    for left, right in zip(recorded, scores_after)),
                   default=0.0)
    agreement = max_diff <= RELOAD_TOLERANCE
    init_digest = state.get("init_digest")
    verification = {
        "schema": VERIFICATION_SCHEMA,
        "selected_epoch": selected["epoch"],
        "selected_adapter_sha256": selected_sha,
        "selected_adapter_bytes": os.path.getsize(pld.safe_target(
            root, SELECTED_DIR_REL + "/" + ADAPTER_FILE)),
        "subset_size": len(scores_after),
        "subset_rule": "first_%d_trainable_examples_in_file_order"
                       % RELOAD_SUBSET_SIZE,
        "scores_before_save": recorded,
        "scores_after_reload": scores_after,
        "max_abs_diff": max_diff,
        "tolerance": RELOAD_TOLERANCE,
        "agreement_pass": agreement,
        "reload_loader": "mlx_lm.tuner.utils.load_adapters",
        "init_digest": init_digest,
        "final_trainable_digest": digest_after,
        "weights_changed": bool(
            init_digest is not None and digest_after != init_digest),
    }
    write_private_json(root, VERIFICATION_REL, verification)
    if not agreement:
        raise TrainError(
            "save/reload completion log-sum agreement failed: max abs diff "
            "%.8f > %.1e" % (max_diff, RELOAD_TOLERANCE))
    wall_clock = elapsed_before + (time.perf_counter() - started)
    if training_used > BUDGET_SECONDS:
        return finish_terminal(
            root, state, rows, identity, binding, TERMINAL_RUNTIME,
            ["the training wall clock %.4f h exceeds the %.0f h budget; the "
             "selected checkpoint and its verification are retained"
             % (training_used / 3600.0, BUDGET_SECONDS / 3600.0)],
            wall_clock, training_used, peak_memory, global_counters,
            resumed_from_epoch, verification, selected, len(train_examples),
            identity["token_aggregate_train"]["untrainable"],
            len(trainable_validation))
    return finish_terminal(
        root, state, rows, identity, binding, TERMINAL_TRAINED, [], wall_clock,
        training_used, peak_memory, global_counters, resumed_from_epoch,
        verification, selected, len(train_examples),
        identity["token_aggregate_train"]["untrainable"],
        len(trainable_validation))


def cmd_verify_reload(config_path: str, allowed_root: Optional[str] = None,
                      protected_roots: Optional[Sequence[str]] = None) -> int:
    config = load_config(config_path)
    root = pld.prepare_artifact_root(
        config["artifact_root"],
        allowed_root if allowed_root is not None else DEFAULT_ALLOWED_ROOT,
        protected_roots)
    if not private_path_exists(root, STATE_REL):
        raise TrainError("no recorded run to verify")
    state = read_private_json(root, STATE_REL)
    identity = read_private_json(root, IDENTITY_REL)
    assert_frozen_identities(identity["model"], identity["dataset"],
                             config["expected"])
    binding = build_binding(
        pld.sha256_file(os.path.abspath(__file__)),
        identity["model"], identity["dataset"], config["run"],
        config_sha256(config["run"]))
    assert_state(state, binding)
    assert_identity(identity, binding)
    if state.get("terminal") != TERMINAL_TRAINED:
        raise TrainError("the recorded run did not reach trained")
    verification = read_private_json(root, VERIFICATION_REL)
    if not verification.get("agreement_pass"):
        raise TrainError("the recorded run did not pass save/reload "
                         "agreement")
    adapter_file = pld.safe_target(
        root, SELECTED_DIR_REL + "/" + ADAPTER_FILE)
    if pld.sha256_file(adapter_file) != verification.get(
            "selected_adapter_sha256"):
        raise TrainError("the selected adapter sha256 does not match the "
                         "recorded verification")
    train_records = load_examples(
        pld.safe_target(config["dataset_dir"], plp.TRAIN_FILE),
        plp.TRAIN_FILE)
    backend = require_mlx()
    tokenize = plp.make_offsets_tokenizer(
        plp.load_base_model(backend, config["model_dir"])[1])
    tokenized = tokenize_examples(tokenize, train_records)
    indices = trainable_indices(tokenized)
    subset_size = int(verification.get("subset_size", RELOAD_SUBSET_SIZE))
    subset = indices[:subset_size]
    model, _tokenizer = reload_adapter_model(
        backend, config["model_dir"], root, SELECTED_DIR_REL)
    scores = plp.completion_logsums(backend, model, tokenized, subset)
    recorded = verification.get("scores_before_save") or []
    if len(recorded) != len(scores):
        raise TrainError("the recorded score count does not match the frozen "
                         "subset")
    max_diff = max((abs(left - right)
                    for left, right in zip(recorded, scores)), default=0.0)
    passed = max_diff <= RELOAD_TOLERANCE
    print(pld.canonical_json({
        "verify_reload": "pass" if passed else "fail",
        "selected_epoch": verification.get("selected_epoch"),
        "subset_size": len(scores),
        "max_abs_diff": max_diff,
        "tolerance": RELOAD_TOLERANCE,
        "selected_adapter_sha256": verification.get(
            "selected_adapter_sha256"),
    }))
    return 0 if passed else 1


def self_test() -> List[str]:
    checks: List[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise TrainError("self-test failed: %s" % name)
        checks.append(name)

    check("frozen_epochs", EPOCHS == 3)
    check("frozen_lora", RANK == ALPHA == 16 and LORA_DROPOUT == 0.0)
    check("frozen_objective_matches_pilot",
          OBJECTIVE == plp.OBJECTIVE == "completion_only_raw_concat")
    check("frozen_modules",
          tuple(LORA_MODULES) == tuple(plp.LORA_MODULES))
    check("frozen_batch",
          MICRO_BATCH == 8 and GRADIENT_ACCUMULATION == 1
          and EFFECTIVE_BATCH == 8)
    check("frozen_optimizer",
          LEARNING_RATE == 1e-4 and WEIGHT_DECAY == 0.0 and SEED == 176)
    check("cache_threshold_is_two_gb",
          CACHE_CLEAR_THRESHOLD_BYTES == 2_000_000_000)

    first = epoch_batches(11, 1)
    check("epoch_batches_cover_every_index_once",
          sorted(index for batch in first for index in batch)
          == list(range(11)))
    check("epoch_batches_final_batch_is_smaller",
          [len(batch) for batch in first] == [8, 3])
    check("epoch_batches_are_deterministic",
          first == epoch_batches(11, 1))
    check("epoch_batches_change_with_the_epoch",
          sorted(sum(epoch_batches(64, 1), []))
          == sorted(sum(epoch_batches(64, 2), []))
          and epoch_batches(64, 1) != epoch_batches(64, 2))

    frozen = validate_run_section({})
    check("default_run_is_the_frozen_shape",
          frozen["epochs"] == 3 and frozen["rank"] == 16
          and frozen["learning_rate"] == 1e-4 and frozen["num_layers"] is None)
    check("config_hash_is_stable", config_sha256(frozen)
          == config_sha256(validate_run_section({})))
    changed = dict(frozen)
    changed["learning_rate"] = 2e-4
    check("config_hash_tracks_learning_rate",
          config_sha256(frozen) != config_sha256(changed))

    rows = [
        {"epoch": 1, "validation_loss": 2.0},
        {"epoch": 2, "validation_loss": 1.5},
        {"epoch": 3, "validation_loss": 1.5},
    ]
    check("selection_prefers_later_epoch_on_a_tie",
          select_epoch(rows)["epoch"] == 3)
    rows[2] = {"epoch": 3, "validation_loss": 2.1}
    check("selection_prefers_the_lowest_loss",
          select_epoch(rows)["epoch"] == 2)
    check("adapter_config_carries_the_frozen_lora",
          adapter_config(28, {})["num_layers"] == 28
          and adapter_config(28, {})["lora_parameters"]["rank"] == 16)
    return checks


def cmd_self_test() -> int:
    checks = self_test()
    for name in checks:
        print("self-test ok: %s" % name)
    print("self-test: PASS (%d checks)" % len(checks))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="One frozen local MLX LoRA training run (AC-177-v1)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true",
                       help="run frozen-config and selection self-checks")
    group.add_argument("--run", action="store_true",
                       help="run the one frozen 3-epoch training run")
    group.add_argument("--verify-reload", action="store_true",
                       help="verify the selected adapter from disk")
    parser.add_argument("--config", help="path to the private config JSON")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            return cmd_self_test()
        if not args.config:
            raise TrainError("--config is required with --run/--verify-reload")
        if args.run:
            return cmd_run(args.config)
        return cmd_verify_reload(args.config)
    except EnvironmentBlocker as error:
        print("terminal=%s" % TERMINAL_ENVIRONMENT)
        print("blocker=%s" % error)
        return 3
    except (TrainError, pld.PersonalLoraDataError) as error:
        print("error=%s" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
