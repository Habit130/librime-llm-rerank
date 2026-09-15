#!/usr/bin/env python3
"""Personal LoRA candidate-ranking evaluation and Mac scoring latency (#178).

This runner is the Squirrel#178 execution (contract AC-178-v1, parent spec
#174). It evaluates three systems on the frozen #175 temporal partitions:

- **Rime reference** — the saved historical candidate display, using the
  recorded ``display_page``/``display_rank`` of the finally committed target;
  disclosed as observed UI order, not an as-of Rime weight replay;
- **unadapted Qwen** — the pinned causal ``Qwen3-0.6B-Base``;
- **LoRA adapter** — the selected #177 epoch-2 adapter.

The scoring policy is selected on the validation ranking-eligible groups
only, among the frozen finite candidates S1–S4, and written to
``policy_lock.json``. The sealed test partition is parsed only after a lock
that matches the current identities exists; after the lock the test is
scored exactly once. The verdict is ``benefit``/``no_benefit``/
``inconclusive`` under the frozen rule. A separate command measures
candidate-scoring wall-clock latency on the validation ranking-eligible
groups with the exact adapter.

Candidate generation is never performed here: candidates come only from the
frozen snapshot's saved same-group competition. Private text stays in the
owner-only artifact root; the default console and the public report carry
aggregate-only values.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import personal_lora_data as pld  # noqa: E402
import personal_lora_pilot as plp  # noqa: E402
import oracle  # noqa: E402  (plugin oracle; path inserted by personal_lora_data)

match_text = oracle.match_text

TOOL_NAME = "personal_lora_eval"
TOOL_VERSION = 1
IDENTITY_SCHEMA = "personal-lora-eval-identity-v1"
LOCK_SCHEMA = "personal-lora-eval-policy-lock-v1"
SELECTION_SCHEMA = "personal-lora-eval-policy-selection-v1"
TEST_SCHEMA = "personal-lora-eval-test-results-v1"
LATENCY_SCHEMA = "personal-lora-eval-latency-v1"
OBJECTIVE = plp.OBJECTIVE

TERMINAL_POLICY_LOCKED = "policy_locked"
TERMINAL_TEST_EVALUATED = "test_evaluated"
TERMINAL_LATENCY = "latency_measured"

DEFAULT_ALLOWED_ROOT = os.path.join(_REPO_ROOT, ".local-work",
                                    "personal-lora-eval")
IDENTITY_REL = "identity.json"
LOCK_REL = "policy_lock.json"
SELECTION_REL = "validation/selection.json"
TEST_RESULTS_REL = "test/results.json"
TEST_GROUPS_REL = "test/per-group.json"
LATENCY_REL = "latency/measurement.json"
LATENCY_GROUPS_REL = "latency/per-group.json"
PUBLIC_REPORT_REL = "public-report.md"

PINNED_VERSIONS = plp.PINNED_VERSIONS
CACHE_CLEAR_THRESHOLD_BYTES = 2_000_000_000
ADAPTER_FILE = "adapters.safetensors"
ADAPTER_CONFIG_FILE = "adapter_config.json"

FROZEN_FREEZE_COMMIT = "2076d0a6c92dbf57833b7a123ea54aab10ddd49d"
FROZEN_MODEL_COMPOSITE = \
    "f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa"
FROZEN_ADAPTER_SHA256 = \
    "7622f26d71efa34f5b9b1e92ebef2c064bd06363c3eac4c88fb0adb44b1462d9"
FROZEN_ADAPTER_EPOCH = 2
FROZEN_SNAPSHOT_SHA256 = \
    "be2b09256dd2c24485ed618501fc06408b4441e1d14a8d86d2645797e82ae6de"
FROZEN_DATASET_DIGESTS = {
    "train_sha256":
        "c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2",
    "validation_sha256":
        "80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8bdeaa880",
    "test_sha256":
        "12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a9f2d2b",
    "manifest_sha256":
        "5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704774bae",
}

POLICIES = ("S1", "S2", "S3", "S4")
WEIGHTED_POLICIES = ("S3", "S4")
POLICY_WEIGHT_FACTOR = {"S3": 1.0, "S4": 0.5}
CANDIDATE_TIE_BREAK = "saved_merge_order_ascending"
SELECTION_RULE = ("highest LoRA top-1 on validation ranking-eligible groups; "
                  "tie-break higher LoRA MRR; then S1 > S2 > S3 > S4")
VERDICT_RULE = ("benefit iff LoRA top-1 is strictly greater than both the "
                "Rime reference and unadapted Qwen; no_benefit iff LoRA top-1 "
                "is <= either baseline; inconclusive iff the ranking-eligible "
                "scored denominator is < 200 or unscored/omitted "
                "ranking-eligible rows exceed 20%")
VERDICT_MIN_DENOMINATOR = 200
VERDICT_MAX_OMISSION_RATE = 0.20

WEIGHT_COLUMN_NAMES = ("weight", "dict_weight", "quality", "score")
SYSTEM_NAMES = ("rime_reference", "unadapted_qwen", "lora_epoch2")

CONFIG_KEYS = frozenset((
    "artifact_root", "model_dir", "dataset_dir", "snapshot_path",
    "adapter_dir", "epoch_checkpoint_path", "freeze_commit", "expected",
))
EXPECTED_KEYS = frozenset((
    "model_composite_sha256", "snapshot_sha256", "adapter_sha256",
    "train_sha256", "validation_sha256", "test_sha256", "manifest_sha256",
))


class EvalError(Exception):
    """A blocking config, schema, isolation or internal error."""


class EnvironmentBlocker(EvalError):
    """A pinned identity or runtime requirement cannot be satisfied."""


class LockError(EvalError):
    """The policy lock is missing, stale or inconsistent."""


def resolve_path(path: str) -> str:
    return pld._resolve(path)


def config_path_from_repo(value: str) -> str:
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(_REPO_ROOT, expanded)


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


def assert_owner_only(root: str) -> None:
    violations = pld.verify_owner_only(root)
    if violations:
        raise EvalError("owner-only permission violation under the artifact "
                        "root: %s" % ",".join(violations))


def load_config(path: str) -> Dict[str, Any]:
    resolved = resolve_path(config_path_from_repo(path))
    if not os.path.isfile(resolved):
        raise EvalError("config file not found: %s" % path)
    try:
        raw = load_json_file(resolved)
    except ValueError as error:
        raise EvalError("config is not valid JSON") from error
    if not isinstance(raw, dict):
        raise EvalError("config must be a JSON object")
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise EvalError("config has unknown keys: %s" % ",".join(unknown))
    required = ("artifact_root", "model_dir", "dataset_dir", "snapshot_path",
                "adapter_dir", "epoch_checkpoint_path")
    for key in required:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise EvalError("config key %s is required" % key)
    expected = raw.get("expected")
    if not isinstance(expected, dict):
        raise EvalError("config key expected is required")
    unexpected = sorted(set(expected) - EXPECTED_KEYS)
    if unexpected:
        raise EvalError("expected has unknown keys: %s" % ",".join(unexpected))
    for key in sorted(EXPECTED_KEYS):
        value = expected.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise EvalError("expected.%s must be a sha256 hex digest" % key)
        int(value, 16)
    return {
        "artifact_root": resolve_path(config_path_from_repo(
            raw["artifact_root"])),
        "model_dir": resolve_path(config_path_from_repo(raw["model_dir"])),
        "dataset_dir": resolve_path(config_path_from_repo(
            raw["dataset_dir"])),
        "snapshot_path": resolve_path(config_path_from_repo(
            raw["snapshot_path"])),
        "adapter_dir": resolve_path(config_path_from_repo(
            raw["adapter_dir"])),
        "epoch_checkpoint_path": resolve_path(config_path_from_repo(
            raw["epoch_checkpoint_path"])),
        "freeze_commit": raw.get("freeze_commit"),
        "expected": {key: expected[key] for key in sorted(EXPECTED_KEYS)},
    }


# ---------------------------------------------------------------------------
# Identity (EVAL-1)
# ---------------------------------------------------------------------------

def require_mlx() -> Dict[str, Any]:
    backend = plp.require_mlx()
    backend["score_batch"] = mlx_score_batch
    return backend


def identify_adapter(config: Dict[str, Any]) -> Dict[str, Any]:
    adapter_dir = config["adapter_dir"]
    if not os.path.isdir(adapter_dir):
        raise EnvironmentBlocker("adapter directory not found")
    files = {}
    for name in (ADAPTER_FILE, ADAPTER_CONFIG_FILE):
        path = os.path.join(adapter_dir, name)
        if not os.path.isfile(path) or os.path.islink(path):
            raise EnvironmentBlocker("adapter file missing: %s" % name)
        files[name] = {"sha256": pld.sha256_file(path),
                       "bytes": os.path.getsize(path)}
    try:
        adapter_config = load_json_file(
            os.path.join(adapter_dir, ADAPTER_CONFIG_FILE))
    except ValueError as error:
        raise EnvironmentBlocker("adapter_config.json is not valid JSON") \
            from error
    if not isinstance(adapter_config, dict):
        raise EnvironmentBlocker("adapter_config.json is not an object")
    if adapter_config.get("epoch") != FROZEN_ADAPTER_EPOCH:
        raise EnvironmentBlocker(
            "the selected adapter does not record the frozen epoch %d"
            % FROZEN_ADAPTER_EPOCH)
    if adapter_config.get("base_model_composite_sha256") != \
            FROZEN_MODEL_COMPOSITE:
        raise EnvironmentBlocker(
            "the selected adapter does not bind the frozen base model")
    checkpoint_path = config["epoch_checkpoint_path"]
    if not os.path.isfile(checkpoint_path) or os.path.islink(checkpoint_path):
        raise EnvironmentBlocker("the frozen epoch-2 checkpoint is missing")
    checkpoint_sha = pld.sha256_file(checkpoint_path)
    summary = {
        key: adapter_config.get(key)
        for key in ("fine_tune_type", "num_layers", "rank", "alpha",
                    "mlx_scale", "dropout", "objective", "seed", "epoch",
                    "base_model_composite_sha256", "dataset_train_sha256",
                    "config_sha256", "freeze_commit")
    }
    summary["lora_parameters"] = adapter_config.get("lora_parameters")
    return {
        "dir_basename": os.path.basename(adapter_dir),
        "files": files,
        "sha256": files[ADAPTER_FILE]["sha256"],
        "bytes": files[ADAPTER_FILE]["bytes"],
        "config": summary,
        "epoch_checkpoint": {
            "sha256": checkpoint_sha,
            "bytes": os.path.getsize(checkpoint_path),
            "matches_selected": checkpoint_sha ==
                                files[ADAPTER_FILE]["sha256"],
        },
    }


def identify_snapshot(snapshot_path: str) -> Dict[str, Any]:
    if not os.path.isfile(snapshot_path):
        raise EnvironmentBlocker("snapshot file not found")
    connection = pld.open_sqlite_readonly(snapshot_path, immutable=True)
    try:
        schema = pld.inspect_schema(connection)
        pld.validate_required_schema(schema)
        meta = pld.read_meta(connection)
        columns = list(schema["tables"].get("selection_candidates") or [])
    finally:
        connection.close()
    return {
        "sha256": pld.sha256_file(snapshot_path),
        "bytes": os.path.getsize(snapshot_path),
        "schema_fingerprint_sha256": schema["fingerprint_sha256"],
        "meta": {key: meta.get(key) for key in pld.REQUIRED_META_KEYS},
        "candidate_columns": columns,
    }


def assert_frozen_identities(model_identity: Dict[str, Any],
                             dataset_identity: Dict[str, Any],
                             adapter_identity: Dict[str, Any],
                             snapshot_identity: Dict[str, Any],
                             expected: Dict[str, str]) -> None:
    """Pin the #175/#176/#177 identities independently of the config."""
    problems = []
    composite = model_identity.get("composite_sha256")
    if composite != expected.get("model_composite_sha256"):
        problems.append("the model directory does not match the config "
                        "expected composite")
    if composite != FROZEN_MODEL_COMPOSITE:
        problems.append("the model composite is not the frozen #176 identity")
    digests = dataset_identity.get("digests") or {}
    mismatches = [key for key in sorted(FROZEN_DATASET_DIGESTS)
                  if digests.get(key) != FROZEN_DATASET_DIGESTS[key]]
    if mismatches:
        problems.append("dataset files are not the frozen #175 freeze: %s"
                        % ",".join(mismatches))
    if dataset_identity.get("freeze_commit") != FROZEN_FREEZE_COMMIT:
        problems.append("the dataset freeze commit is not the #175 freeze")
    adapter_sha = adapter_identity.get("sha256")
    if adapter_sha != expected.get("adapter_sha256"):
        problems.append("the adapter does not match the config expected "
                        "sha256")
    if adapter_sha != FROZEN_ADAPTER_SHA256:
        problems.append("the adapter is not the selected #177 epoch-2 "
                        "adapter")
    if not (adapter_identity.get("epoch_checkpoint") or {}).get(
            "matches_selected"):
        problems.append("the selected adapter bytes differ from the frozen "
                        "epoch-2 checkpoint")
    snapshot_sha = snapshot_identity.get("sha256")
    if snapshot_sha != expected.get("snapshot_sha256"):
        problems.append("the snapshot does not match the config expected "
                        "sha256")
    if snapshot_sha != FROZEN_SNAPSHOT_SHA256:
        problems.append("the snapshot is not the frozen #175 snapshot")
    if problems:
        raise EnvironmentBlocker("; ".join(problems))


def module_digests() -> Dict[str, str]:
    return {
        "personal_lora_data": pld.sha256_file(os.path.abspath(pld.__file__)),
        "personal_lora_pilot": pld.sha256_file(os.path.abspath(plp.__file__)),
        "oracle": pld.sha256_file(os.path.abspath(oracle.__file__)),
    }


def build_binding(config: Dict[str, Any], model_identity: Dict[str, Any],
                  dataset_identity: Dict[str, Any],
                  adapter_identity: Dict[str, Any],
                  snapshot_identity: Dict[str, Any],
                  versions: Dict[str, Optional[str]],
                  tool_sha: str) -> Dict[str, Any]:
    return {
        "tool_sha256": tool_sha,
        "modules": module_digests(),
        "model_composite_sha256": model_identity["composite_sha256"],
        "adapter_sha256": adapter_identity["sha256"],
        "adapter_config_sha256":
            adapter_identity["files"][ADAPTER_CONFIG_FILE]["sha256"],
        "adapter_epoch": FROZEN_ADAPTER_EPOCH,
        "epoch_checkpoint_sha256":
            adapter_identity["epoch_checkpoint"]["sha256"],
        "dataset": dataset_identity["digests"],
        "snapshot_sha256": snapshot_identity["sha256"],
        "freeze_commit": dataset_identity.get("freeze_commit"),
        "runtime": versions,
        "objective": OBJECTIVE,
    }


def binding_sha256(binding: Dict[str, Any]) -> str:
    return pld.sha256_text(pld.canonical_json(binding))


def gather_identity(config: Dict[str, Any], versions: Dict[str, Any],
                    tool_sha: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    dataset_identity = plp.identify_dataset(config)
    model_identity = plp.identify_model_dir(config["model_dir"])
    adapter_identity = identify_adapter(config)
    snapshot_identity = identify_snapshot(config["snapshot_path"])
    assert_frozen_identities(model_identity, dataset_identity,
                             adapter_identity, snapshot_identity,
                             config["expected"])
    binding = build_binding(config, model_identity, dataset_identity,
                            adapter_identity, snapshot_identity, versions,
                            tool_sha)
    identity = {
        "schema": IDENTITY_SCHEMA,
        "created_at_utc": pld.utc_now_iso(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION,
                 "sha256": tool_sha},
        "binding": binding,
        "model": model_identity,
        "adapter": adapter_identity,
        "dataset": dataset_identity,
        "snapshot": snapshot_identity,
        "runtime": versions,
    }
    return identity, binding


def load_or_write_identity(root: str, identity: Dict[str, Any],
                           binding: Dict[str, Any]) -> bool:
    """Write the identity manifest once; reuse only on an exact binding."""
    if private_path_exists(root, IDENTITY_REL):
        recorded = read_private_json(root, IDENTITY_REL)
        if recorded.get("schema") != IDENTITY_SCHEMA:
            raise EvalError("identity.json has an unexpected schema")
        recorded_binding = recorded.get("binding")
        if recorded_binding != binding:
            raise EvalError("identity.json binding does not match the "
                            "current model/adapter/dataset/runtime "
                            "identities; refusing to rebind")
        return False
    write_private_json(root, IDENTITY_REL, identity)
    return True


# ---------------------------------------------------------------------------
# Frozen partitions and saved competition (no invented candidates)
# ---------------------------------------------------------------------------

class Group(object):
    """One ranking-eligible saved selection event and its candidates."""

    __slots__ = ("ordinal", "event_id", "prompt", "target", "empty_context",
                 "choice_key_sha256", "candidates", "target_pos",
                 "display_rank", "display_page", "seen_exact_pair",
                 "seen_choice_key")

    def __init__(self, ordinal: int, event_id: str, prompt: str, target: str,
                 empty_context: bool, choice_key_sha256: str,
                 candidates: Sequence[str], target_pos: int,
                 display_rank: int, display_page: int):
        self.ordinal = ordinal
        self.event_id = event_id
        self.prompt = prompt
        self.target = target
        self.empty_context = empty_context
        self.choice_key_sha256 = choice_key_sha256
        self.candidates = tuple(candidates)
        self.target_pos = target_pos
        self.display_rank = display_rank
        self.display_page = display_page
        self.seen_exact_pair = False
        self.seen_choice_key = False


def parse_split_rows(path: str, label: str,
                     allow_sealed: bool = False) -> List[Dict[str, Any]]:
    """Parse one completion partition.

    The sealed ``test.jsonl`` may not be parsed as text before the policy
    lock exists; only a binary checksum is allowed before then.
    """
    if os.path.basename(path) == plp.TEST_FILE and not allow_sealed:
        raise LockError("refusing to parse the sealed test partition "
                        "before the frozen policy lock")
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise EvalError("%s line %d is blank" % (label, line_number))
            try:
                record = json.loads(line)
            except ValueError as error:
                raise EvalError("%s line %d is not JSON"
                                % (label, line_number)) from error
            if not isinstance(record, dict):
                raise EvalError("%s line %d is not an object"
                                % (label, line_number))
            if record.get("schema") != pld.DATASET_SCHEMA:
                raise EvalError("%s line %d has unexpected schema"
                                % (label, line_number))
            if record.get("loss") != pld.LOSS_BOUNDARY_INTENT:
                raise EvalError("%s line %d has unexpected loss intent"
                                % (label, line_number))
            prompt = record.get("prompt")
            completion = record.get("completion")
            if not isinstance(prompt, str) or not isinstance(completion, str):
                raise EvalError("%s line %d has non-text fields"
                                % (label, line_number))
            if not completion:
                raise EvalError("%s line %d has an empty completion"
                                % (label, line_number))
            provenance = record.get("provenance")
            if not isinstance(provenance, dict):
                raise EvalError("%s line %d has no provenance"
                                % (label, line_number))
            if not isinstance(provenance.get("event_id"), str):
                raise EvalError("%s line %d has no event identity"
                                % (label, line_number))
            rows.append({"prompt": prompt, "completion": completion,
                         "provenance": provenance})
    return rows


def _chunked(values: Sequence[str],
             size: int = 500) -> List[Sequence[str]]:
    return [values[start:start + size]
            for start in range(0, len(values), size)]


def fetch_events(connection: sqlite3.Connection,
                 event_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    events: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(event_ids):
        placeholders = ",".join("?" * len(chunk))
        query = ("SELECT event_id, display_rank, display_page,"
                 " preceding_text, final_selection_text"
                 " FROM selection_events WHERE event_id IN (%s)"
                 % placeholders)
        for row in connection.execute(query, list(chunk)):
            events[row[0]] = {
                "display_rank": int(row[1]),
                "display_page": int(row[2]),
                "preceding_text": row[3],
                "final_selection_text": row[4],
            }
    return events


def fetch_candidates(connection: sqlite3.Connection,
                     event_ids: Sequence[str]
                     ) -> Dict[str, List[str]]:
    candidates: Dict[str, List[str]] = {event_id: []
                                        for event_id in event_ids}
    orders: Dict[str, List[int]] = {event_id: [] for event_id in event_ids}
    for chunk in _chunked(event_ids):
        placeholders = ",".join("?" * len(chunk))
        query = ("SELECT event_id, merge_order, text FROM selection_candidates"
                 " WHERE event_id IN (%s) ORDER BY event_id, merge_order"
                 % placeholders)
        for row in connection.execute(query, list(chunk)):
            candidates[row[0]].append(row[2])
            orders[row[0]].append(int(row[1]))
    for event_id, texts in candidates.items():
        if not texts:
            raise EvalError("a ranking-eligible event has no saved "
                            "candidates")
        if any(text is None or not str(text) for text in texts):
            raise EvalError("a saved candidate has empty text")
        observed = orders[event_id]
        if len(set(observed)) != len(observed) or \
                observed != sorted(observed):
            raise EvalError("saved candidate merge order is not strictly "
                            "increasing")
    return candidates


def build_groups(rows: Sequence[Dict[str, Any]],
                 connection: sqlite3.Connection,
                 label: str) -> Tuple[List[Group], Dict[str, Any]]:
    eligible = [row for row in rows
                if bool(row["provenance"].get("ranking_eligible"))]
    event_ids = [row["provenance"]["event_id"] for row in eligible]
    if len(set(event_ids)) != len(event_ids):
        raise EvalError("%s has a duplicate event identity" % label)
    events = fetch_events(connection, event_ids)
    candidates = fetch_candidates(connection, event_ids)
    groups: List[Group] = []
    page_one = 0
    position_agrees = 0
    for row in eligible:
        provenance = row["provenance"]
        event_id = provenance["event_id"]
        event = events.get(event_id)
        if event is None:
            raise EvalError("%s references an event missing from the frozen "
                            "snapshot" % label)
        if event["preceding_text"] != row["prompt"]:
            raise EvalError("%s prompt does not match the frozen snapshot"
                            % label)
        if event["final_selection_text"] != row["completion"]:
            raise EvalError("%s target does not match the frozen snapshot"
                            % label)
        saved = candidates[event_id]
        target = match_text(row["completion"])
        positions = [index for index, text in enumerate(saved)
                     if match_text(text) == target]
        if not positions:
            raise EvalError("%s target is not in the saved competition"
                            % label)
        target_pos = positions[0]
        if event["display_page"] == 1 and \
                event["display_rank"] == target_pos + 1:
            position_agrees += 1
        if event["display_page"] == 1:
            page_one += 1
        group = Group(
            ordinal=len(groups), event_id=event_id, prompt=row["prompt"],
            target=row["completion"],
            empty_context=bool(provenance.get("empty_context")),
            choice_key_sha256=str(provenance.get("choice_key_sha256") or ""),
            candidates=saved, target_pos=target_pos,
            display_rank=event["display_rank"],
            display_page=event["display_page"])
        groups.append(group)
    if not groups:
        raise EvalError("%s has no ranking-eligible groups" % label)
    summary = {
        "rows": len(rows),
        "ranking_eligible": len(groups),
        "ranking_ineligible": len(rows) - len(groups),
        "empty_context": sum(1 for group in groups if group.empty_context),
        "first_page": page_one,
        "deeper_than_first_page": len(groups) - page_one,
        "saved_position_matches_recorded_display_rank": position_agrees,
        "candidate_total": sum(len(group.candidates) for group in groups),
        "group_size_min": min(len(group.candidates) for group in groups),
        "group_size_max": max(len(group.candidates) for group in groups),
    }
    return groups, summary


def load_train_membership(config: Dict[str, Any]
                          ) -> Tuple[set, set, int]:
    """Exact (prompt, completion) pairs and choice keys seen in training."""
    path = pld.safe_target(config["dataset_dir"], plp.TRAIN_FILE)
    rows = parse_split_rows(path, plp.TRAIN_FILE)
    pairs = set()
    keys = set()
    for row in rows:
        pairs.add((row["prompt"], row["completion"]))
        key = row["provenance"].get("choice_key_sha256")
        if isinstance(key, str) and key:
            keys.add(key)
    return pairs, keys, len(rows)


def apply_train_membership(groups: Sequence[Group], pairs: set,
                           keys: set) -> Dict[str, int]:
    seen_exact = 0
    seen_key = 0
    for group in groups:
        group.seen_exact_pair = (group.prompt, group.target) in pairs
        group.seen_choice_key = bool(group.choice_key_sha256) and \
            group.choice_key_sha256 in keys
        seen_exact += 1 if group.seen_exact_pair else 0
        seen_key += 1 if group.seen_choice_key else 0
    return {"exact_pair_seen_in_train": seen_exact,
            "choice_key_seen_in_train": seen_key}


# ---------------------------------------------------------------------------
# Frozen scoring policies (EVAL-2)
# ---------------------------------------------------------------------------

def weight_precondition(snapshot_identity: Dict[str, Any],
                        candidate_total: int) -> Dict[str, Any]:
    """S3/S4 need a finite saved numeric weight for every scored candidate."""
    columns = list(snapshot_identity.get("candidate_columns") or [])
    present = [name for name in WEIGHT_COLUMN_NAMES if name in columns]
    if present:
        return {
            "available": True,
            "weight_column": present[0],
            "candidates_examined": candidate_total,
        }
    return {
        "available": False,
        "reason": "the frozen snapshot's selection_candidates table saves "
                  "no numeric candidate weight",
        "candidate_columns": columns,
        "candidates_examined": candidate_total,
        "policies": {"S3": "n/a", "S4": "n/a"},
    }


def available_policies(precondition: Dict[str, Any]) -> List[str]:
    if precondition.get("available"):
        return list(POLICIES)
    return ["S1", "S2"]


def apply_policy(policy: str, logsum: float, tokens: int) -> Optional[float]:
    if tokens <= 0:
        return None
    if policy == "S1":
        return logsum / float(tokens)
    if policy == "S2":
        return logsum
    raise EvalError("policy %s requires a saved numeric candidate weight"
                    % policy)


def mlx_score_batch(backend: Dict[str, Any], model,
                    examples: Sequence[plp.CompletionExample]
                    ) -> List[Tuple[float, int, int]]:
    """Completion-only log-sums for one padded batch (raw-concat seam).

    Reuses the frozen #176/#177 serialization: each example was tokenized
    once on ``prompt + completion`` with boundary-spanning tokens charged to
    the prompt side. Position ``t`` contributes when
    ``t >= max(1, prompt_side)`` and ``t < total_tokens``. Candidates with no
    completion-side target return zero tokens and are unscored omissions.
    """
    mx = backend["mx"]
    if not examples:
        return []
    width = max(example.total_tokens for example in examples)
    if width < 2:
        return [(0.0, 0, example.spanning_tokens) for example in examples]
    rows = [list(example.input_ids) + [0] * (width - example.total_tokens)
            for example in examples]
    ids = mx.array(rows)
    logits = model(ids[:, :-1]).astype(mx.float32)
    log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
    targets = ids[:, 1:]
    picked = mx.take_along_axis(log_probs, targets[..., None], axis=-1)
    picked = picked[..., 0]
    positions = mx.arange(1, width)
    lengths = mx.array([[example.total_tokens] for example in examples])
    prompts = mx.array([[max(1, example.prompt_side)]
                        for example in examples])
    mask = ((positions >= prompts) & (positions < lengths)).astype(mx.float32)
    sums = (picked * mask).sum(axis=-1)
    mx.eval(sums)
    values = sums.tolist()
    results = []
    for example, value in zip(examples, values):
        results.append((float(value), example.target_count(),
                        example.spanning_tokens))
    return results


def score_group(backend: Dict[str, Any], model, tokenize: Callable,
                group: Group) -> List[Tuple[float, int, int]]:
    examples = [plp.build_completion_example(tokenize, group.prompt, text)
                for text in group.candidates]
    values = backend["score_batch"](backend, model, examples)
    if len(values) != len(examples):
        raise EvalError("the scoring backend returned %d values for %d "
                        "candidates" % (len(values), len(examples)))
    for value in values:
        if not isinstance(value, tuple) or len(value) != 3:
            raise EvalError("the scoring backend returned a malformed score")
    return values


def guard_cache(backend: Dict[str, Any], counters: Dict[str, int]) -> None:
    if backend["mx"].get_cache_memory() > CACHE_CLEAR_THRESHOLD_BYTES:
        backend["mx"].clear_cache()
        counters["threshold"] += 1


def score_groups(backend: Dict[str, Any], model, tokenize: Callable,
                 groups: Sequence[Group]
                 ) -> List[List[Tuple[float, int, int]]]:
    counters = {"threshold": 0}
    scored = []
    for group in groups:
        scored.append(score_group(backend, model, tokenize, group))
        guard_cache(backend, counters)
    return scored


def build_system_eval(groups: Sequence[Group],
                      scored: Sequence[Sequence[Tuple[float, int, int]]],
                      policy: str) -> Dict[str, Any]:
    per_group = []
    for group, entries in zip(groups, scored):
        values: List[Optional[float]] = []
        omitted = 0
        spanning = 0
        for logsum, tokens, spanning_tokens in entries:
            spanning += 1 if spanning_tokens else 0
            value = apply_policy(policy, logsum, tokens)
            if value is None:
                omitted += 1
            values.append(value)
        ranked = sorted((index for index, value in enumerate(values)
                         if value is not None),
                        key=lambda index: (-values[index], index))
        if group.target_pos in ranked:
            rank = ranked.index(group.target_pos) + 1
            target = entries[group.target_pos]
            per_group.append({
                "rank": rank,
                "top1": 1 if rank == 1 else 0,
                "mrr": 1.0 / rank,
                "target_logsum": target[0],
                "target_tokens": target[1],
                "scored_candidates": len(ranked),
                "omitted_candidates": omitted,
                "spanning_candidates": spanning,
            })
        else:
            per_group.append({
                "rank": None, "top1": 0, "mrr": 0.0,
                "target_logsum": None, "target_tokens": None,
                "scored_candidates": len(ranked),
                "omitted_candidates": omitted,
                "spanning_candidates": spanning,
            })
    return {"per_group": per_group}


def build_rime_eval(groups: Sequence[Group]) -> Dict[str, Any]:
    """Observed historical display order, from the recorded target position."""
    per_group = []
    for group in groups:
        first = group.display_page == 1 and group.display_rank == 1
        mrr = 1.0 / group.display_rank if group.display_page == 1 else 0.0
        per_group.append({"rank": group.display_rank,
                          "top1": 1 if first else 0,
                          "mrr": mrr,
                          "on_first_page": group.display_page == 1})
    return {"per_group": per_group}


def aggregate(system: Dict[str, Any], groups: Sequence[Group],
              rime: Dict[str, Any],
              indices: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    domain = list(range(len(groups))) if indices is None else list(indices)
    per_group = system["per_group"]
    rime_per_group = rime["per_group"]
    ranked = [index for index in domain
              if per_group[index]["rank"] is not None]
    rows = len(ranked)
    top1 = sum(per_group[index]["top1"] for index in ranked)
    mrr = sum(per_group[index]["mrr"] for index in ranked)
    mispromotion = sum(
        1 for index in ranked
        if rime_per_group[index]["top1"] == 1 and
        per_group[index]["rank"] != 1)
    logsums = []
    tokens = 0
    for index in ranked:
        entry = per_group[index]
        count = entry.get("target_tokens") or 0
        if entry.get("target_logsum") is not None and count:
            logsums.append(entry["target_logsum"])
            tokens += count
    logloss = None
    if tokens:
        logloss = -sum(logsums) / float(tokens)
    return {
        "domain_rows": len(domain),
        "ranked_rows": rows,
        "omitted_rows": len(domain) - rows,
        "top1": top1,
        "top1_rate": (top1 / float(rows)) if rows else 0.0,
        "mrr": (mrr / float(rows)) if rows else 0.0,
        "mispromotion": mispromotion,
        "target_logloss": logloss,
        "target_completion_tokens": tokens,
        "omitted_candidates": sum(per_group[index].get("omitted_candidates", 0)
                                  for index in domain),
        "spanning_candidates": sum(
            per_group[index].get("spanning_candidates", 0)
            for index in domain),
    }


def select_policy(policy_stats: Dict[str, Dict[str, Any]],
                  policies: Sequence[str]) -> str:
    best = None
    best_key = None
    for policy in policies:
        stats = policy_stats[policy]
        key = (stats["top1"], round(stats["mrr"], 12))
        if best is None or key > best_key:
            best = policy
            best_key = key
    if best is None:
        raise EvalError("no scoring policy is available for selection")
    return best


def verdict_for(ranking_eligible: int, denominator: int, rime_top1: int,
                base_top1: int, lora_top1: int) -> Tuple[str, Dict[str, Any]]:
    omission_rate = ((ranking_eligible - denominator) /
                     float(ranking_eligible)) if ranking_eligible else 1.0
    evidence = {
        "ranking_eligible": ranking_eligible,
        "scored_denominator": denominator,
        "omitted_rows": ranking_eligible - denominator,
        "omission_rate": omission_rate,
        "rime_top1": rime_top1,
        "unadapted_qwen_top1": base_top1,
        "lora_top1": lora_top1,
    }
    if denominator < VERDICT_MIN_DENOMINATOR:
        return "inconclusive", dict(
            evidence,
            reason="the ranking-eligible scored denominator %d is below %d"
                   % (denominator, VERDICT_MIN_DENOMINATOR))
    if omission_rate > VERDICT_MAX_OMISSION_RATE:
        return "inconclusive", dict(
            evidence,
            reason="unscored/omitted ranking-eligible rows exceed 20%% "
                   "(%.6f)" % omission_rate)
    if lora_top1 > rime_top1 and lora_top1 > base_top1:
        return "benefit", dict(
            evidence, reason="LoRA top-1 is strictly greater than both the "
                             "Rime reference and unadapted Qwen")
    return "no_benefit", dict(
        evidence, reason="LoRA top-1 is not strictly greater than both "
                         "baselines")


# ---------------------------------------------------------------------------
# Policy lock (EVAL-2)
# ---------------------------------------------------------------------------

def assert_lock(lock: Dict[str, Any], binding: Dict[str, Any],
                test_sha256: Optional[str] = None) -> None:
    if not isinstance(lock, dict) or lock.get("schema") != LOCK_SCHEMA:
        raise LockError("policy_lock.json is missing or has an unexpected "
                        "schema")
    if lock.get("tool") != TOOL_NAME or \
            lock.get("tool_version") != TOOL_VERSION:
        raise LockError("policy_lock.json was written by another tool "
                        "version")
    if lock.get("tool_sha256") != binding.get("tool_sha256"):
        raise LockError("policy_lock.json was written by a different tool "
                        "build")
    if lock.get("binding") != binding:
        raise LockError("policy_lock.json does not match the current "
                        "identities")
    selected = lock.get("selected_policy")
    if selected not in POLICIES:
        raise LockError("policy_lock.json has an invalid selected policy")
    if selected not in (lock.get("available_policies") or []):
        raise LockError("policy_lock.json selected an unavailable policy")
    if test_sha256 is not None and lock.get("test_sha256") != test_sha256:
        raise LockError("policy_lock.json does not bind the sealed test "
                        "partition checksum")


def read_lock(root: str, binding: Dict[str, Any],
              test_sha256: Optional[str] = None) -> Dict[str, Any]:
    if not private_path_exists(root, LOCK_REL):
        raise LockError("policy_lock.json does not exist; the validation-only "
                        "selection must complete first")
    lock = read_private_json(root, LOCK_REL)
    assert_lock(lock, binding, test_sha256)
    return lock


def selection_matches(lock: Dict[str, Any],
                      selection: Dict[str, Any],
                      tolerance: float = 1e-9) -> Optional[str]:
    if lock.get("selected_policy") != selection.get("selected_policy"):
        return "the recomputed selection picks %s, not the locked %s" % (
            selection.get("selected_policy"), lock.get("selected_policy"))
    locked = {policy: stats
              for policy, stats in (lock.get("policy_stats") or {}).items()
              if isinstance(stats, dict)}
    current = {policy: stats
               for policy, stats in
               (selection.get("policy_stats") or {}).items()
               if isinstance(stats, dict)}
    if sorted(locked) != sorted(current):
        return "the recomputed policy set differs from the locked policy set"
    for policy in sorted(current):
        left = locked[policy]
        right = current[policy]
        for key in ("top1", "ranked_rows", "omitted_rows"):
            if left.get(key) != right.get(key):
                return "policy %s %s changed from %r to %r" % (
                    policy, key, left.get(key), right.get(key))
        for key in ("mrr", "omission_rate"):
            if left.get(key) is None or right.get(key) is None:
                continue
            if abs(float(left[key]) - float(right[key])) > tolerance:
                return "policy %s %s changed beyond %g" % (
                    policy, key, tolerance)
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def prepare_environment(config_path: str, allowed_root: Optional[str] = None,
                        protected_roots: Optional[Sequence[str]] = None
                        ) -> Tuple[Dict[str, Any], str, Dict[str, Any],
                                   Dict[str, Any]]:
    config = load_config(config_path)
    root = pld.prepare_artifact_root(
        config["artifact_root"],
        allowed_root if allowed_root is not None else DEFAULT_ALLOWED_ROOT,
        protected_roots)
    assert_owner_only(root)
    versions = plp.runtime_versions()
    plp.assert_pinned_versions(versions)
    tool_sha = pld.sha256_file(os.path.abspath(__file__))
    identity, binding = gather_identity(config, versions, tool_sha)
    load_or_write_identity(root, identity, binding)
    assert_owner_only(root)
    return config, root, identity, binding


def cmd_select_policy(config_path: str, allowed_root: Optional[str] = None,
                      protected_roots: Optional[Sequence[str]] = None,
                      backend: Optional[Dict[str, Any]] = None) -> int:
    started = time.perf_counter()
    config, root, identity, binding = prepare_environment(
        config_path, allowed_root, protected_roots)
    test_path = pld.safe_target(config["dataset_dir"], plp.TEST_FILE)
    test_sha256 = pld.sha256_file(test_path)
    validation_path = pld.safe_target(config["dataset_dir"],
                                      plp.VALIDATION_FILE)
    if test_sha256 != config["expected"]["test_sha256"]:
        raise EnvironmentBlocker("the sealed test checksum does not match "
                                 "the frozen #175 identity")

    backend = backend if backend is not None else require_mlx()
    connection = pld.open_sqlite_readonly(config["snapshot_path"],
                                          immutable=True)
    try:
        rows = parse_split_rows(validation_path, plp.VALIDATION_FILE)
        groups, summary = build_groups(rows, connection, plp.VALIDATION_FILE)
    finally:
        connection.close()
    train_pairs, train_keys, _train_rows = load_train_membership(config)
    membership = apply_train_membership(groups, train_pairs, train_keys)

    model, tokenizer = plp.load_base_model(backend, config["model_dir"])
    backend["load_adapters"](model, config["adapter_dir"])
    model.eval()
    tokenize = plp.make_offsets_tokenizer(tokenizer)
    scored = score_groups(backend, model, tokenize, groups)

    precondition = weight_precondition(
        identity["snapshot"], summary["candidate_total"])
    policies = available_policies(precondition)
    policy_stats = {}
    rime = build_rime_eval(groups)
    for policy in policies:
        system = build_system_eval(groups, scored, policy)
        policy_stats[policy] = aggregate(system, groups, rime)
    for policy in WEIGHTED_POLICIES:
        if policy not in policy_stats:
            policy_stats[policy] = "n/a"
    selected = select_policy(
        {policy: policy_stats[policy] for policy in policies}, policies)
    selection = {
        "schema": SELECTION_SCHEMA,
        "created_at_utc": pld.utc_now_iso(),
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "tool_sha256": binding["tool_sha256"],
        "binding": binding,
        "partition": plp.VALIDATION_FILE,
        "summary": summary,
        "membership": membership,
        "weight_precondition": precondition,
        "candidate_tie_break": CANDIDATE_TIE_BREAK,
        "selection_rule": SELECTION_RULE,
        "policy_stats": policy_stats,
        "available_policies": policies,
        "selected_policy": selected,
        "validation_sha256": identity["dataset"]["digests"][
            "validation_sha256"],
        "test_sha256": test_sha256,
        "test_parsed": False,
    }
    if private_path_exists(root, LOCK_REL):
        lock = read_lock(root, binding, test_sha256)
        problem = selection_matches(lock, {
            "selected_policy": selected, "policy_stats": policy_stats})
        if problem:
            raise LockError("the frozen policy lock conflicts with the "
                            "recomputed validation selection: %s" % problem)
        lock_action = "lock_reused"
    else:
        lock = {
            "schema": LOCK_SCHEMA,
            "created_at_utc": pld.utc_now_iso(),
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "tool_sha256": binding["tool_sha256"],
            "binding": binding,
            "validation_sha256": selection["validation_sha256"],
            "test_sha256": test_sha256,
            "weight_precondition": precondition,
            "candidate_tie_break": CANDIDATE_TIE_BREAK,
            "selection_rule": SELECTION_RULE,
            "policy_stats": policy_stats,
            "available_policies": policies,
            "selected_policy": selected,
        }
        write_private_json(root, LOCK_REL, lock)
        lock_action = "lock_written"
    write_private_json(root, SELECTION_REL, selection)
    render_public_report(root)
    elapsed = time.perf_counter() - started
    print("terminal=%s" % TERMINAL_POLICY_LOCKED)
    print("selected_policy=%s" % selected)
    print("validation_ranking_eligible=%d" % summary["ranking_eligible"])
    print("validation_candidates=%d" % summary["candidate_total"])
    print("lock_action=%s" % lock_action)
    print("wall_clock_seconds=%.2f" % elapsed)
    print(pld.canonical_json({
        "selected_policy": selected,
        "policy_stats": {policy: policy_stats[policy] for policy in policies},
        "weight_precondition_available": precondition["available"],
        "wall_clock_seconds": round(elapsed, 2),
    }))
    return 0


def cmd_eval_test(config_path: str, allowed_root: Optional[str] = None,
                  protected_roots: Optional[Sequence[str]] = None,
                  backend: Optional[Dict[str, Any]] = None) -> int:
    started = time.perf_counter()
    config, root, identity, binding = prepare_environment(
        config_path, allowed_root, protected_roots)
    test_path = pld.safe_target(config["dataset_dir"], plp.TEST_FILE)
    test_sha256 = pld.sha256_file(test_path)
    if test_sha256 != config["expected"]["test_sha256"]:
        raise EnvironmentBlocker("the sealed test checksum does not match "
                                 "the frozen #175 identity")
    lock = read_lock(root, binding, test_sha256)

    if private_path_exists(root, TEST_RESULTS_REL):
        results = read_private_json(root, TEST_RESULTS_REL)
        recorded_binding = results.get("binding")
        if recorded_binding != binding:
            raise EvalError("test/results.json was written under different "
                            "identities; refusing to replace the single "
                            "locked test pass")
        if results.get("lock_sha256") != pld.sha256_file(
                pld.safe_target(root, LOCK_REL)):
            raise EvalError("test/results.json does not match the current "
                            "policy lock")
        assert_owner_only(root)
        print("terminal=%s" % TERMINAL_TEST_EVALUATED)
        print("results_reused=true")
        print("verdict=%s" % results.get("verdict"))
        print("scored_denominator=%s"
              % (results.get("verdict_evidence") or {}).get(
                  "scored_denominator"))
        return 0

    backend = backend if backend is not None else require_mlx()
    connection = pld.open_sqlite_readonly(config["snapshot_path"],
                                          immutable=True)
    try:
        rows = parse_split_rows(test_path, plp.TEST_FILE, allow_sealed=True)
        groups, summary = build_groups(rows, connection, plp.TEST_FILE)
    finally:
        connection.close()
    train_pairs, train_keys, train_rows = load_train_membership(config)
    membership = apply_train_membership(groups, train_pairs, train_keys)

    policy = lock["selected_policy"]
    base_model, tokenizer = plp.load_base_model(backend, config["model_dir"])
    base_model.eval()
    tokenize = plp.make_offsets_tokenizer(tokenizer)
    base_scored = score_groups(backend, base_model, tokenize, groups)
    del base_model
    backend["mx"].clear_cache()
    lora_model, lora_tokenizer = plp.load_base_model(backend,
                                                     config["model_dir"])
    backend["load_adapters"](lora_model, config["adapter_dir"])
    lora_model.eval()
    lora_tokenize = plp.make_offsets_tokenizer(lora_tokenizer)
    lora_scored = score_groups(backend, lora_model, lora_tokenize, groups)

    rime = build_rime_eval(groups)
    base_system = build_system_eval(groups, base_scored, policy)
    lora_system = build_system_eval(groups, lora_scored, policy)
    denominator_indices = [
        index for index in range(len(groups))
        if base_system["per_group"][index]["rank"] is not None and
        lora_system["per_group"][index]["rank"] is not None]
    denominator = len(denominator_indices)
    rime_aggregate = aggregate(rime, groups, rime)
    base_aggregate = aggregate(base_system, groups, rime)
    lora_aggregate = aggregate(lora_system, groups, rime)
    common = {
        "rime_reference": aggregate(rime, groups, rime,
                                    denominator_indices),
        "unadapted_qwen": aggregate(base_system, groups, rime,
                                    denominator_indices),
        "lora_epoch2": aggregate(lora_system, groups, rime,
                                 denominator_indices),
    }
    verdict, verdict_evidence = verdict_for(
        summary["ranking_eligible"], denominator,
        common["rime_reference"]["top1"], common["unadapted_qwen"]["top1"],
        common["lora_epoch2"]["top1"])
    strata = build_strata(groups, base_system, lora_system, rime,
                          denominator_indices)
    results = {
        "schema": TEST_SCHEMA,
        "created_at_utc": pld.utc_now_iso(),
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "tool_sha256": binding["tool_sha256"],
        "binding": binding,
        "binding_sha256": binding_sha256(binding),
        "lock_sha256": pld.sha256_file(pld.safe_target(root, LOCK_REL)),
        "policy": policy,
        "summary": summary,
        "membership": membership,
        "denominator_rows": denominator,
        "systems": {
            "rime_reference": rime_aggregate,
            "unadapted_qwen": base_aggregate,
            "lora_epoch2": lora_aggregate,
        },
        "comparison": common,
        "strata": strata,
        "verdict": verdict,
        "verdict_evidence": verdict_evidence,
        "verdict_rule": VERDICT_RULE,
        "second_pass": False,
        "wall_clock_seconds": round(time.perf_counter() - started, 2),
    }
    per_group = {
        "schema": "personal-lora-eval-test-per-group-v1",
        "policy": policy,
        "groups": [
            {
                "ordinal": group.ordinal,
                "candidates": len(group.candidates),
                "empty_context": group.empty_context,
                "seen_exact_pair": group.seen_exact_pair,
                "seen_choice_key": group.seen_choice_key,
                "target_pos": group.target_pos,
                "rime_rank": group.display_rank,
                "rime_page": group.display_page,
                "unadapted_rank":
                    base_system["per_group"][group.ordinal]["rank"],
                "lora_rank": lora_system["per_group"][group.ordinal]["rank"],
                "unadapted_target_logsum":
                    base_system["per_group"][group.ordinal]["target_logsum"],
                "lora_target_logsum":
                    lora_system["per_group"][group.ordinal]["target_logsum"],
                "target_tokens":
                    lora_system["per_group"][group.ordinal]["target_tokens"],
            }
            for group in groups
        ],
    }
    write_private_json(root, TEST_RESULTS_REL, results)
    write_private_json(root, TEST_GROUPS_REL, per_group)
    render_public_report(root)
    print("terminal=%s" % TERMINAL_TEST_EVALUATED)
    print("policy=%s" % policy)
    print("test_ranking_eligible=%d" % summary["ranking_eligible"])
    print("scored_denominator=%d" % denominator)
    print("verdict=%s" % verdict)
    print("wall_clock_seconds=%.2f" % results["wall_clock_seconds"])
    print(pld.canonical_json({
        "policy": policy,
        "comparison": {
            name: {
                "ranked_rows": common[name]["ranked_rows"],
                "top1": common[name]["top1"],
                "top1_rate": round(common[name]["top1_rate"], 6),
                "mrr": round(common[name]["mrr"], 6),
                "mispromotion": common[name]["mispromotion"],
                "target_logloss": (
                    round(common[name]["target_logloss"], 6)
                    if common[name]["target_logloss"] is not None else None),
            }
            for name in SYSTEM_NAMES
        },
        "verdict": verdict,
        "verdict_reason": verdict_evidence["reason"],
    }))
    return 0


def build_strata(groups: Sequence[Group], base_system: Dict[str, Any],
                 lora_system: Dict[str, Any], rime: Dict[str, Any],
                 indices: Sequence[int]) -> Dict[str, Any]:
    dimensions = {
        "context": ("empty", "nonempty"),
        "exact_pair": ("train_seen", "train_unseen"),
        "choice_key": ("train_seen", "train_unseen"),
    }
    strata = {}
    for dimension, values in dimensions.items():
        blocks = {}
        for value in values:
            members = [index for index in indices
                       if stratum_value(groups[index], dimension) == value]
            blocks[value] = {
                "rows": len(members),
                "rime_reference": aggregate(rime, groups, rime, members),
                "unadapted_qwen": aggregate(base_system, groups, rime,
                                            members),
                "lora_epoch2": aggregate(lora_system, groups, rime, members),
            }
        strata[dimension] = blocks
    return strata


def stratum_value(group: Group, dimension: str) -> str:
    if dimension == "context":
        return "empty" if group.empty_context else "nonempty"
    if dimension == "exact_pair":
        return "train_seen" if group.seen_exact_pair else "train_unseen"
    if dimension == "choice_key":
        return "train_seen" if group.seen_choice_key else "train_unseen"
    raise EvalError("unknown stratum dimension %s" % dimension)


def cmd_measure_latency(config_path: str, allowed_root: Optional[str] = None,
                        protected_roots: Optional[Sequence[str]] = None,
                        backend: Optional[Dict[str, Any]] = None) -> int:
    started = time.perf_counter()
    config, root, identity, binding = prepare_environment(
        config_path, allowed_root, protected_roots)
    lock = read_lock(root, binding)
    policy = lock["selected_policy"]
    if private_path_exists(root, LATENCY_REL):
        measurement = read_private_json(root, LATENCY_REL)
        if measurement.get("binding") != binding:
            raise EvalError("latency/measurement.json was written under "
                            "different identities; refusing to replace the "
                            "recorded measurement")
        assert_owner_only(root)
        print("terminal=%s" % TERMINAL_LATENCY)
        print("latency_reused=true")
        return 0

    validation_path = pld.safe_target(config["dataset_dir"],
                                      plp.VALIDATION_FILE)
    backend = backend if backend is not None else require_mlx()
    connection = pld.open_sqlite_readonly(config["snapshot_path"],
                                          immutable=True)
    try:
        rows = parse_split_rows(validation_path, plp.VALIDATION_FILE)
        groups, summary = build_groups(rows, connection, plp.VALIDATION_FILE)
    finally:
        connection.close()

    system_before = plp.sample_system_state(sample_processes=True)
    backend["mx"].reset_peak_memory()
    load_start = time.perf_counter()
    model, tokenizer = plp.load_base_model(backend, config["model_dir"])
    backend["load_adapters"](model, config["adapter_dir"])
    model.eval()
    tokenize = plp.make_offsets_tokenizer(tokenizer)
    load_seconds = time.perf_counter() - load_start

    per_group = []
    counters = {"threshold": 0}
    scoring_start = time.perf_counter()
    for index, group in enumerate(groups):
        start = time.perf_counter()
        scores = score_group(backend, model, tokenize, group)
        system = build_system_eval([group], [scores], policy)
        target_rank = system["per_group"][0]["rank"]
        elapsed = time.perf_counter() - start
        guard_cache(backend, counters)
        per_group.append({
            "ordinal": index,
            "candidates": len(group.candidates),
            "seconds": elapsed,
            "per_candidate_seconds": elapsed / float(len(group.candidates)),
            "target_rank": target_rank,
            "cold": index == 0,
        })
    scoring_seconds = time.perf_counter() - scoring_start
    total_seconds = time.perf_counter() - started
    system_after = plp.sample_system_state(sample_processes=True)
    mx = backend["mx"]
    cold = [row for row in per_group if row["cold"]]
    warm = [row for row in per_group if not row["cold"]]
    measurement = {
        "schema": LATENCY_SCHEMA,
        "created_at_utc": pld.utc_now_iso(),
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "tool_sha256": binding["tool_sha256"],
        "binding": binding,
        "binding_sha256": binding_sha256(binding),
        "machine": plp.machine_facts(),
        "protocol": {
            "partition": plp.VALIDATION_FILE,
            "ranking_eligible_groups": summary["ranking_eligible"],
            "adapter": "selected epoch-2 LoRA",
            "policy": policy,
            "timed_region": "candidate tokenization + padded model forward + "
                            "completion-only log-sum + locked-policy ranking",
            "cold": "the first group after the model load",
            "warm": "every remaining group",
            "per_candidate": "group wall clock / saved candidates in the "
                             "group",
            "scope": "offline candidate scoring only; not IMK/panel "
                     "presentation and not a live-wait repair claim",
        },
        "summary": summary,
        "load_seconds": load_seconds,
        "scoring_seconds": scoring_seconds,
        "groups": len(groups),
        "candidates": sum(len(group.candidates) for group in groups),
        "cold": {
            "groups": len(cold),
            "group_seconds": plp.summarize_lengths(
                [row["seconds"] for row in cold]),
            "per_candidate_seconds": plp.summarize_lengths(
                [row["per_candidate_seconds"] for row in cold]),
        },
        "warm": {
            "groups": len(warm),
            "group_seconds": plp.summarize_lengths(
                [row["seconds"] for row in warm]),
            "per_candidate_seconds": plp.summarize_lengths(
                [row["per_candidate_seconds"] for row in warm]),
        },
        "all_groups": {
            "group_seconds": plp.summarize_lengths(
                [row["seconds"] for row in per_group]),
            "per_candidate_seconds": plp.summarize_lengths(
                [row["per_candidate_seconds"] for row in per_group]),
        },
        "memory": {
            "mlx_peak_bytes": int(mx.get_peak_memory()),
            "mlx_active_bytes": int(mx.get_active_memory()),
            "mlx_cache_bytes": int(mx.get_cache_memory()),
            "process_max_rss_mb": plp.process_max_rss_mb(),
            "cache_clears": counters,
        },
        "system_before": system_before,
        "system_after": system_after,
        "total_seconds": total_seconds,
    }
    write_private_json(root, LATENCY_REL, measurement)
    write_private_json(root, LATENCY_GROUPS_REL, {
        "schema": "personal-lora-eval-latency-per-group-v1",
        "groups": per_group,
    })
    render_public_report(root)
    print("terminal=%s" % TERMINAL_LATENCY)
    print("groups=%d" % len(groups))
    print("candidates=%d" % measurement["candidates"])
    print("policy=%s" % policy)
    print("load_seconds=%.4f" % load_seconds)
    print("warm_group_p50_seconds=%.6f"
          % measurement["warm"]["group_seconds"].get("p50", 0.0))
    print("warm_group_p90_seconds=%.6f"
          % measurement["warm"]["group_seconds"].get("p90", 0.0))
    print("warm_group_p99_seconds=%.6f"
          % measurement["warm"]["group_seconds"].get("p99", 0.0))
    print("mlx_peak_gb=%.4f" % (measurement["memory"]["mlx_peak_bytes"]
                                / float(1024 ** 3)))
    return 0


# ---------------------------------------------------------------------------
# Public report
# ---------------------------------------------------------------------------

def load_optional_json(root: str, relative: str) -> Optional[Dict[str, Any]]:
    if not private_path_exists(root, relative):
        return None
    return read_private_json(root, relative)


def render_public_report(root: str) -> str:
    identity = load_optional_json(root, IDENTITY_REL)
    selection = load_optional_json(root, SELECTION_REL)
    lock = load_optional_json(root, LOCK_REL)
    results = load_optional_json(root, TEST_RESULTS_REL)
    latency = load_optional_json(root, LATENCY_REL)
    lines = ["# Personal LoRA candidate-ranking evaluation "
             "(`personal-lora-eval`)", ""]
    lines.append("This report is desensitized: it contains identities, "
                 "aggregate counts, policy statistics, comparisons, the "
                 "verdict and timings. It contains no prompt, completion or "
                 "candidate text, no event identifiers and no absolute "
                 "private paths.")
    lines.append("")
    if identity:
        binding = identity["binding"]
        lines.append("## Identities")
        lines.append("")
        lines.append("| Item | Value |")
        lines.append("| --- | --- |")
        lines.append("| model composite sha256 | `%s` |"
                     % binding["model_composite_sha256"])
        lines.append("| selected adapter sha256 (epoch %s) | `%s` |"
                     % (binding["adapter_epoch"], binding["adapter_sha256"]))
        lines.append("| adapter config sha256 | `%s` |"
                     % binding["adapter_config_sha256"])
        lines.append("| epoch-2 checkpoint equals selected | %s |"
                     % identity["adapter"]["epoch_checkpoint"][
                         "matches_selected"])
        lines.append("| dataset train/validation/test sha256 | `%s` / `%s` / "
                     "`%s` |"
                     % (binding["dataset"]["train_sha256"],
                        binding["dataset"]["validation_sha256"],
                        binding["dataset"]["test_sha256"]))
        lines.append("| dataset manifest sha256 | `%s` |"
                     % binding["dataset"]["manifest_sha256"])
        lines.append("| snapshot sha256 | `%s` |"
                     % binding["snapshot_sha256"])
        lines.append("| freeze commit | `%s` |" % binding["freeze_commit"])
        runtime = binding["runtime"]
        lines.append("| runtime | mlx %s / mlx-lm %s / numpy %s |"
                     % (runtime.get("mlx"), runtime.get("mlx-lm"),
                        runtime.get("numpy")))
        lines.append("| tool sha256 | `%s` |" % binding["tool_sha256"])
        lines.append("")
    if lock:
        lines.append("## Policy lock (validation only, before test parse)")
        lines.append("")
        lines.append("Selection rule: %s. Candidate tie-break: `%s`."
                     % (lock["selection_rule"], lock["candidate_tie_break"]))
        lines.append("")
        lines.append("| Policy | Validation top-1 | Validation MRR | "
                     "Ranked rows |")
        lines.append("| --- | --- | --- | --- |")
        for policy in POLICIES:
            stats = (lock.get("policy_stats") or {}).get(policy)
            if isinstance(stats, dict):
                lines.append("| %s | %d (%.6f) | %.6f | %d |"
                             % (policy, stats["top1"], stats["top1_rate"],
                                stats["mrr"], stats["ranked_rows"]))
            else:
                lines.append("| %s | n/a | n/a | n/a |" % policy)
        lines.append("")
        lines.append("Selected policy: **%s**. Weight precondition: %s."
                     % (lock["selected_policy"],
                        "available" if (lock.get("weight_precondition") or {})
                        .get("available") else
                        "not available (S3/S4 n/a, recorded not failed)"))
        lines.append("")
    if selection:
        summary = selection["summary"]
        lines.append("## Validation groups")
        lines.append("")
        lines.append("| Item | Value |")
        lines.append("| --- | --- |")
        lines.append("| ranking-eligible / ineligible | %d / %d |"
                     % (summary["ranking_eligible"],
                        summary["ranking_ineligible"]))
        lines.append("| saved candidates | %d |"
                     % summary["candidate_total"])
        lines.append("| empty-context groups | %d |"
                     % summary["empty_context"])
        lines.append("| deeper than the first page | %d |"
                     % summary["deeper_than_first_page"])
        lines.append("| recorded display rank equals saved position | %d / "
                     "%d |"
                     % (summary[
                         "saved_position_matches_recorded_display_rank"],
                        summary["ranking_eligible"]))
        lines.append("")
    if results:
        comparison = results["comparison"]
        lines.append("## Locked test ranking (`%s`, one pass)"
                     % results["policy"])
        lines.append("")
        lines.append("| System | Ranked rows | Top-1 | Top-1 rate | MRR | "
                     "Mispromotion | Target log-loss |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for name in SYSTEM_NAMES:
            block = comparison[name]
            logloss = block["target_logloss"]
            lines.append("| %s | %d | %d | %.6f | %.6f | %d | %s |"
                         % (name, block["ranked_rows"], block["top1"],
                            block["top1_rate"], block["mrr"],
                            block["mispromotion"],
                            "%.6f" % logloss if logloss is not None
                            else "n/a"))
        lines.append("")
        evidence = results["verdict_evidence"]
        lines.append("Verdict: **%s** — %s." % (results["verdict"],
                                                evidence["reason"]))
        lines.append("")
        lines.append("| Verdict evidence | Value |")
        lines.append("| --- | --- |")
        lines.append("| ranking-eligible test groups | %d |"
                     % evidence["ranking_eligible"])
        lines.append("| scored denominator | %d |"
                     % evidence["scored_denominator"])
        lines.append("| omitted rows (rate) | %d (%.6f) |"
                     % (evidence["omitted_rows"], evidence["omission_rate"]))
        lines.append("")
        lines.append("### Strata (common denominator)")
        lines.append("")
        for dimension in sorted(results["strata"]):
            lines.append("| %s | rows | rime top-1 | qwen top-1 | lora top-1 "
                         "| lora MRR |" % dimension)
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for value in sorted(results["strata"][dimension]):
                block = results["strata"][dimension][value]
                lines.append("| %s | %d | %d | %d | %d | %.6f |"
                             % (value, block["rows"],
                                block["rime_reference"]["top1"],
                                block["unadapted_qwen"]["top1"],
                                block["lora_epoch2"]["top1"],
                                block["lora_epoch2"]["mrr"]))
            lines.append("")
    if latency:
        warm = latency["warm"]
        cold = latency["cold"]
        lines.append("## Mac candidate-scoring latency (validation, exact "
                     "adapter)")
        lines.append("")
        lines.append("Protocol: %s." % latency["protocol"]["scope"])
        lines.append("")
        lines.append("The timed region is `%s` under the locked policy "
                     "`%s`."
                     % (latency["protocol"].get("timed_region", "n/a"),
                        latency["protocol"].get("policy", "n/a")))
        lines.append("")
        lines.append("| Metric | cold (1 group) | warm (%d groups) | all "
                     "(%d groups) |"
                     % (warm["groups"], latency["groups"]))
        lines.append("| --- | --- | --- | --- |")
        lines.append("| group seconds p50/p90/p99 | %.6f/%.6f/%.6f | "
                     "%.6f/%.6f/%.6f | %.6f/%.6f/%.6f |"
                     % (cold["group_seconds"].get("p50", 0.0),
                        cold["group_seconds"].get("p90", 0.0),
                        cold["group_seconds"].get("p99", 0.0),
                        warm["group_seconds"].get("p50", 0.0),
                        warm["group_seconds"].get("p90", 0.0),
                        warm["group_seconds"].get("p99", 0.0),
                        latency["all_groups"]["group_seconds"].get("p50", 0.0),
                        latency["all_groups"]["group_seconds"].get("p90", 0.0),
                        latency["all_groups"]["group_seconds"].get("p99", 0.0)))
        lines.append("| per-candidate seconds p50/p90/p99 | "
                     "%.6f/%.6f/%.6f | %.6f/%.6f/%.6f | %.6f/%.6f/%.6f |"
                     % (cold["per_candidate_seconds"].get("p50", 0.0),
                        cold["per_candidate_seconds"].get("p90", 0.0),
                        cold["per_candidate_seconds"].get("p99", 0.0),
                        warm["per_candidate_seconds"].get("p50", 0.0),
                        warm["per_candidate_seconds"].get("p90", 0.0),
                        warm["per_candidate_seconds"].get("p99", 0.0),
                        latency["all_groups"]["per_candidate_seconds"].get(
                            "p50", 0.0),
                        latency["all_groups"]["per_candidate_seconds"].get(
                            "p90", 0.0),
                        latency["all_groups"]["per_candidate_seconds"].get(
                            "p99", 0.0)))
        lines.append("")
        lines.append("Model load %.4f s; scoring %.4f s; %d groups, %d "
                     "candidates; MLX peak %.4f GB, active %.4f GB, cache "
                     "%.4f GB; process max RSS %s MB; swap before/after "
                     "%s/%s MB."
                     % (latency["load_seconds"],
                        latency.get("scoring_seconds", 0.0),
                        latency["groups"], latency["candidates"],
                        latency["memory"]["mlx_peak_bytes"] / float(1024 ** 3),
                        latency["memory"]["mlx_active_bytes"] / float(1024 ** 3),
                        latency["memory"]["mlx_cache_bytes"] / float(1024 ** 3),
                        latency["memory"]["process_max_rss_mb"],
                        latency["system_before"].get("swap_used_mb"),
                        latency["system_after"].get("swap_used_mb")))
        lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append("- The Rime reference uses the recorded historical "
                 "`display_page`/`display_rank` of the committed target: an "
                 "observed UI order, not an as-of Rime weight replay. Where "
                 "the recorded rank and the saved candidate position differ "
                 "(reported above), the recorded rank is used.")
    lines.append("- Models rank only saved candidates of the same "
                 "same-group competition; no candidate is generated, added or "
                 "reordered from outside the saved list.")
    lines.append("- Completion-side tokens follow the frozen #176/#177 "
                 "raw-concat seam; boundary-spanning tokens stay prompt-side. "
                 "Candidates with no completion-side target are unscored "
                 "omissions, counted and excluded from the argmax, never "
                 "silently ranked last.")
    lines.append("- Improved training or validation loss is not ranking "
                 "benefit; the verdict uses only the locked test ranking on "
                 "the common denominator.")
    lines.append("- Latency is offline candidate scoring on a shared "
                 "personal Mac with the live input method running; it is not "
                 "IMK/panel presentation, not training-step time and not a "
                 "live `get_context` wait repair claim.")
    lines.append("- The test partition is a sealed historical split, not a "
                 "project-wide untouched prospective test; later retractions "
                 "would require a new dataset/adapter version.")
    lines.append("")
    text = "\n".join(lines)
    pld.private_write_bytes(root, PUBLIC_REPORT_REL, text.encode("utf-8"))
    return text


# ---------------------------------------------------------------------------
# Self test
# ---------------------------------------------------------------------------

class _FakeGroup(object):
    __slots__ = ("ordinal", "empty_context", "seen_exact_pair",
                 "seen_choice_key", "target_pos", "display_rank",
                 "display_page")


def _fake_group(ordinal: int, target_pos: int = 0, display_rank: int = 1,
                display_page: int = 1, empty: bool = False,
                seen_exact: bool = False, seen_key: bool = False):
    group = _FakeGroup()
    group.ordinal = ordinal
    group.empty_context = empty
    group.seen_exact_pair = seen_exact
    group.seen_choice_key = seen_key
    group.target_pos = target_pos
    group.display_rank = display_rank
    group.display_page = display_page
    return group


def self_test() -> List[str]:
    checks = []
    groups = [_fake_group(0), _fake_group(1, target_pos=1, display_rank=2),
              _fake_group(2, target_pos=2, display_page=2, display_rank=1)]
    rime = build_rime_eval(groups)
    scores = [
        [(0.0, 1, 0), (-1.0, 1, 0)],
        [(-2.0, 1, 0), (-1.0, 1, 0)],
        [(-1.0, 2, 0), (-2.0, 1, 0), (-3.0, 1, 1)],
    ]
    system = build_system_eval(groups, scores, "S1")
    aggregate_value = aggregate(system, groups, rime)
    if (aggregate_value["top1"], aggregate_value["ranked_rows"]) != (2, 3):
        raise EvalError("self-test: S1 top-1 aggregation is wrong")
    checks.append("s1_aggregation")
    if rime["per_group"][2]["on_first_page"]:
        raise EvalError("self-test: a deeper page counted as the first page")
    checks.append("rime_page_boundary")

    omitted = [
        [(0.0, 1, 0), (-9.0, 0, 1), (-1.0, 1, 0)],
        [(-2.0, 1, 0), (-1.0, 1, 0)],
        [(-1.0, 2, 0), (-2.0, 1, 0), (-3.0, 1, 1)],
    ]
    omitted_system = build_system_eval(groups, omitted, "S1")
    if omitted_system["per_group"][0]["rank"] != 1:
        raise EvalError("self-test: an unscored candidate must not be "
                        "ranked last")
    if omitted_system["per_group"][0]["omitted_candidates"] != 1:
        raise EvalError("self-test: the unscored omission was not counted")
    target_omitted = [
        [(0.0, 0, 1), (-1.0, 1, 0)],
        [(-2.0, 1, 0), (-1.0, 1, 0)],
        [(-1.0, 2, 0), (-2.0, 1, 0), (-3.0, 1, 1)],
    ]
    if build_system_eval(groups, target_omitted,
                         "S1")["per_group"][0]["rank"] is not None:
        raise EvalError("self-test: an unscored target must be an omitted "
                        "row")
    checks.append("unscored_omission")

    stats = {
        "S1": {"top1": 10, "mrr": 0.5, "ranked_rows": 20, "omitted_rows": 0,
               "omission_rate": 0.0},
        "S2": {"top1": 10, "mrr": 0.5, "ranked_rows": 20, "omitted_rows": 0,
               "omission_rate": 0.0},
        "S3": {"top1": 9, "mrr": 0.9, "ranked_rows": 20, "omitted_rows": 0,
               "omission_rate": 0.0},
        "S4": {"top1": 9, "mrr": 0.9, "ranked_rows": 20, "omitted_rows": 0,
               "omission_rate": 0.0},
    }
    if select_policy(stats, ["S1", "S2", "S3", "S4"]) != "S1":
        raise EvalError("self-test: the policy tie-break order is wrong")
    stats["S2"]["mrr"] = 0.6
    if select_policy(stats, ["S1", "S2", "S3", "S4"]) != "S2":
        raise EvalError("self-test: the MRR tie-break is wrong")
    stats["S3"]["top1"] = 11
    if select_policy(stats, ["S1", "S2", "S3", "S4"]) != "S3":
        raise EvalError("self-test: the top-1 policy rule is wrong")
    checks.append("policy_selection")

    verdict, evidence = verdict_for(500, 450, 380, 350, 390)
    if verdict != "benefit":
        raise EvalError("self-test: benefit was not detected")
    if verdict_for(500, 450, 380, 390, 390)[0] != "no_benefit":
        raise EvalError("self-test: a tie must not be benefit")
    if verdict_for(500, 450, 380, 350, 380)[0] != "no_benefit":
        raise EvalError("self-test: an equal baseline must not be benefit")
    if verdict_for(500, 199, 100, 100, 150)[0] != "inconclusive":
        raise EvalError("self-test: the denominator floor is wrong")
    if verdict_for(500, 399, 100, 100, 150)[0] != "inconclusive":
        raise EvalError("self-test: the omission cap is wrong")
    if verdict_for(500, 400, 100, 100, 150)[0] != "benefit":
        raise EvalError("self-test: the omission cap boundary is wrong")
    if evidence["scored_denominator"] != 450:
        raise EvalError("self-test: verdict evidence is wrong")
    checks.append("verdict")

    precondition = weight_precondition(
        {"candidate_columns": ["event_id", "merge_order", "text"]}, 5)
    if precondition["available"] or available_policies(precondition) != \
            ["S1", "S2"]:
        raise EvalError("self-test: the weight precondition is wrong")
    checks.append("weight_precondition")

    if apply_policy("S1", -4.0, 2) != -2.0 or apply_policy("S2", -4.0, 2) \
            != -4.0 or apply_policy("S1", -4.0, 0) is not None:
        raise EvalError("self-test: policy arithmetic is wrong")
    checks.append("policy_arithmetic")

    lock = {"selected_policy": "S1",
            "policy_stats": {"S1": {"top1": 1, "ranked_rows": 2,
                                    "omitted_rows": 0, "mrr": 0.5,
                                    "omission_rate": 0.0}}}
    if selection_matches(lock, {"selected_policy": "S1", "policy_stats":
                                {"S1": {"top1": 1, "ranked_rows": 2,
                                        "omitted_rows": 0, "mrr": 0.5,
                                        "omission_rate": 0.0}}}) is not None:
        raise EvalError("self-test: an identical selection did not match")
    if selection_matches(lock, {"selected_policy": "S2", "policy_stats":
                                lock["policy_stats"]}) is None:
        raise EvalError("self-test: a changed policy was not detected")
    checks.append("lock_consistency")

    boundary_example = plp.build_completion_example(
        _boundary_tokenizer, "ab", "c")
    if boundary_example.prompt_side != 2:
        raise EvalError("self-test: the boundary token was not charged to "
                        "the prompt side")
    checks.append("boundary_side")
    return checks


class _BoundaryEncoding(object):

    def __init__(self, ids, offsets):
        self.ids = ids
        self.offsets = offsets


class _BoundaryBackend(object):

    def encode(self, text):
        return _BoundaryEncoding([1, 2, 3], [(0, 2), (1, 3), (3, 4)])


def _boundary_tokenizer(text):
    encoding = _BoundaryBackend().encode(text)
    return list(encoding.ids), list(encoding.offsets)


def cmd_self_test() -> int:
    checks = self_test()
    print("self_test_checks=%d" % len(checks))
    for name in checks:
        print("  ok %s" % name)
    print("self_test=PASS")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Personal LoRA candidate-ranking evaluation (#178)")
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--self-test", action="store_true")
    commands.add_argument("--select-policy", action="store_true")
    commands.add_argument("--eval-test", action="store_true")
    commands.add_argument("--measure-latency", action="store_true")
    parser.add_argument("--config")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            return cmd_self_test()
        if not args.config:
            parser.error("--config is required for this command")
        if args.select_policy:
            return cmd_select_policy(args.config)
        if args.eval_test:
            return cmd_eval_test(args.config)
        return cmd_measure_latency(args.config)
    except (EnvironmentBlocker, plp.EnvironmentBlocker) as error:
        print("environment_blocker: %s" % error, file=sys.stderr)
        return 3
    except (EvalError, plp.PilotError, pld.PersonalLoraDataError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
