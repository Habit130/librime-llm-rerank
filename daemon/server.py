#!/usr/bin/env python3
"""LLM rerank daemon: MLX inference over a unix domain socket.

Protocol (JSON, newline-delimited):
  Request:  {"version": 1, "request_id": "...", "plan_identity": "...",
             "context": "<preceding text>", "candidates": ["c1", "c2", ...]}
  Response: {"version": 1, "request_id": "...", "plan_identity": "...",
             "scores": [s1, s2, ...]}
  Error:    {"version": 1, "error": {"code": "...", ...}}

Health request (issue #51, model-free; the status core uses it to observe
serving state without loading the model):
  Request:  {"version": 2, "request_id": "...", "kind": "health"}
  Response: {"version": 2, "request_id": "...", "kind": "health",
             "health": {"pid": ..., "model_loaded": bool, ...}}

Lifecycle:
  - Model is lazy-loaded on first request (0.33 s cold start).
  - 5 minutes of idle unloads the model (releases ~1.5 GB).
  - Socket path: ~/Library/Application Support/Squirrel/llm-rerank.sock
"""

import argparse
from datetime import datetime, timezone
import json
import math
import os
import socket
import sys
import threading
import time

from control import run_control_server, validate_control_path
from coordinator import MaintenanceCoordinator
from delta import build_delta_machine_from_config
import compat  # noqa: E402
from staging import build_staging_machine_from_config
from publish import (build_publisher_from_config, read_active_manifest)
from evidence import (EVIDENCE_KIND, EvidenceError, EvidenceService,
                      build_evidence_service_from_config)

SOCKET_PATH = os.path.expanduser(
    "~/Library/Application Support/Squirrel/llm-rerank.sock"
)
FACTS_ROOT = os.path.expanduser(
    "~/Library/Application Support/Squirrel/SemanticMemory"
)
MODEL_PATH = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
IDLE_TIMEOUT = 300  # seconds
TAIL_CHARS = 4  # chars of context tail re-tokenized per candidate
CONTEXT_WINDOW = 64  # chars of 上文 tail the model is conditioned on (ADR-0002)
CACHE_LIMIT_MB = 512  # MLX allocator cache cap; 0 = unlimited (default MLX behavior)
PROTOCOL_VERSION = 2
MAX_REQUEST_BYTES = 64 * 1024
REQUEST_READ_DEADLINE = 5.0
REQUEST_FIELDS = {
    "version",
    "request_id",
    "plan_identity",
    "baseline_policy_id",
    "context",
    "candidates",
}

# Evidence request kind (Squirrel#61, AC61-1): the plugin asks the daemon for
# the canonical oracle's candidate-level retrieval evidence for one rerank
# group.  The exact field set is part of the protocol; anything else is
# invalid_request.
EVIDENCE_FIELDS = {
    "version",
    "kind",
    "request_id",
    "plan_identity",
    "schema_id",
    "category",
    "canonical_segment_input",
    "preceding_text",
    "candidates",
    "config_identity",
    "fact_high_water",
}

# Scoring strategies (see docs/token-attribution.md). The production strategy
# is mean_token: the mean log probability of the tokens that provably belong
# to the candidate text. legacy_sum is a calibration-only faithful
# reproduction of the pre-#46 algorithm (sum over all suffix tokens, first
# token skipped when the prefix is empty); it exists so the old policy's
# numbers can be reported on the canonical 120/402 denominator without
# duplicating scoring logic in the calibration tooling.
SCORING_STRATEGY_MEAN_TOKEN = "mean_token"
SCORING_STRATEGY_LEGACY_SUM = "legacy_sum"

# Policy-id binding (Habit130/squirrel#46 acceptance, PR #12 round 2): each
# daemon scoring mode accepts exactly one declared baseline_policy_id, so a
# plan's declared normalization can never be silently served by a daemon
# running a different algorithm. legacy_sum exists solely for calibration
# and only accepts the old sum policy id.
MEAN_TOKEN_POLICY_ID = "mean-token-lm-v1"
LEGACY_SUM_POLICY_ID = "first-stage-base-v1"
POLICY_ID_BY_STRATEGY = {
    SCORING_STRATEGY_MEAN_TOKEN: MEAN_TOKEN_POLICY_ID,
    SCORING_STRATEGY_LEGACY_SUM: LEGACY_SUM_POLICY_ID,
}

# Frozen shadow baseline (Habit130/squirrel#75, AC-75-v1): the deployed
# baseline_policy_id is a composed identity carrying code SHAs, model and
# tokenizer identity, token averaging rule, alpha/beta values, candidate
# normalization and failure semantics (freeze record in Habit130/squirrel).
# The daemon cannot verify the deployment-scoped components (SHAs, alpha,
# beta), but it verifies the ones it owns: the token rule must equal the
# scoring mode's canonical id and the model/tokenizer identity must equal
# its own model directory basename. The canonical id stays accepted so
# unconfigured or calibration schemas keep the exact-match binding.
FROZEN_BASELINE_PREFIX = "frozen-baseline-v1:"
FROZEN_REQUIRED_KEYS = ("rule", "model", "tokenizer")
FROZEN_KNOWN_KEYS = ("rule", "model", "tokenizer", "norm", "fail",
                     "squirrel", "plugin", "alpha", "beta_sys", "beta_usr")


def daemon_model_identity(state):
    path = getattr(state, "model_path", None) or MODEL_PATH
    return os.path.basename(os.path.normpath(path))


def build_compat_report(evidence_config, facts_root, active_identity,
                        refuse_reason, staging_machine, machine):
    """The privacy-clean desired/active compatibility report for status.

    Composes the desired layered identity from the evidence config + current
    facts, the active identity from the active manifest (or the refusal), and
    runs the compatibility matrix to produce the mismatch reasons and the
    planned action union (spec: status 必须报告 desired 与 active 指纹和不匹配
    原因; SCN-66-11).  Only identity strings and digests -- never raw text,
    candidates or embeddings.
    """
    from delta import read_facts_identity, read_facts_schema_version
    from compat import (compose_index_fingerprint, plan_actions,
                        LAYER_STORE_EPOCH, LAYER_FACT_SCHEMA,
                        LAYER_REPRESENTATION, LAYER_VECTOR_FORMAT,
                        LAYER_PROJECTION, LAYER_INDEX, FP32_ROW_MAJOR_LE)
    from generation import PROJECTION_VERSION
    report = {"refuse_load": refuse_reason is not None,
              "refuse_reason": refuse_reason,
              "desired": None, "active": None, "mismatches": [],
              "actions": []}
    try:
        facts_identity = read_facts_identity(facts_root)
        facts_schema_version = read_facts_schema_version(facts_root)
    except Exception:  # noqa: BLE001 - a missing/unreadable store means
        facts_identity = None
        facts_schema_version = None
    if facts_identity is None:
        return report
    facts_epoch = facts_identity[0]
    try:
        desired_repr = evidence_config.get(
            "desired_representation_id",
            evidence_config.get("representation_id"))
        desired_projection = evidence_config.get(
            "desired_projection_version", PROJECTION_VERSION)
        desired_index = evidence_config.get("desired_index_fingerprint")
        if not desired_index:
            desired_index = compose_index_fingerprint()
        desired_format = evidence_config.get(
            "desired_vector_format_version", FP32_ROW_MAJOR_LE)
    except (KeyError, TypeError, ValueError):
        return report
    desired = {
        LAYER_STORE_EPOCH: facts_epoch,
        LAYER_FACT_SCHEMA: facts_schema_version,
        LAYER_REPRESENTATION: desired_repr,
        LAYER_VECTOR_FORMAT: desired_format,
        LAYER_PROJECTION: desired_projection,
        LAYER_INDEX: desired_index,
    }
    report["desired"] = desired
    report["active"] = active_identity
    if active_identity is None:
        return report
    try:
        plan = plan_actions(desired, active_identity,
                            facts_schema_version=facts_schema_version)
    except Exception:  # noqa: BLE001 - the report never takes the daemon down
        return report
    report["mismatches"] = plan.get("mismatches", [])
    report["actions"] = plan.get("actions", [])
    return report


def parse_frozen_baseline_id(declared_id):
    """Parse a frozen-baseline policy id into its components.

    Returns None for anything malformed: wrong prefix, empty payload,
    unknown key, empty value, duplicate key or a missing required key.
    """
    if not declared_id.startswith(FROZEN_BASELINE_PREFIX):
        return None
    payload = declared_id[len(FROZEN_BASELINE_PREFIX):]
    if not payload:
        return None
    components = {}
    for part in payload.split(":"):
        if "=" not in part:
            return None
        key, _, value = part.partition("=")
        if key not in FROZEN_KNOWN_KEYS or not value or key in components:
            return None
        components[key] = value
    for key in FROZEN_REQUIRED_KEYS:
        if key not in components:
            return None
    return components


def accepted_by_strategy(declared_id, strategy, state):
    """Whether the daemon may serve a plan declaring `declared_id`.

    Exact canonical match always passes; in the mean_token mode a well-formed
    frozen-baseline id passes only when its rule and model/tokenizer
    components match the daemon's own strategy and model identity. legacy_sum
    keeps the exact-match binding (calibration-only, never a deployment).
    """
    accepted_policy = POLICY_ID_BY_STRATEGY.get(strategy)
    if accepted_policy is None:
        return False
    if declared_id == accepted_policy:
        return True
    if strategy != SCORING_STRATEGY_MEAN_TOKEN:
        return False
    frozen = parse_frozen_baseline_id(declared_id)
    if frozen is None:
        return False
    model_identity = daemon_model_identity(state)
    return (frozen["rule"] == MEAN_TOKEN_POLICY_ID
            and frozen["model"] == model_identity
            and frozen["tokenizer"] == model_identity)


class TokenAttributionError(Exception):
    """The candidate token boundary cannot be proven safe to score."""


class NonFiniteTokenScoreError(Exception):
    """A per-token or reduced log probability is not finite."""


def reject_duplicate_object_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object field")
        value[key] = item
    return value


def window_context(context, context_window):
    """Truncate context to its last `context_window` characters (ADR-0002)."""
    return context[-context_window:]


def candidate_scoring_plan(tokenizer, tail_text, candidate):
    """Tokenize `tail_text + candidate` and attribute tokens to the candidate.

    Returns (suffix_ids, first_target_position, target_count) or raises
    TokenAttributionError.

    Attribution is by reconstruction (docs/token-attribution.md): the token
    boundary is located by decoding token-sequence prefixes and comparing
    them with the tail text. This is provably safe -- `decode(ids[:k]) ==
    tail_text` proves tokens [0, k) cover exactly the tail characters, the
    round-trip precondition `decode(ids) == full` proves the remaining
    tokens cover exactly the candidate characters, and the suffix
    precondition `decode(ids[k:]) == candidate` closes the loop without
    relying on decoder composability. It also handles Qwen's byte-level BPE
    fallback pairs (rare characters tokenize as two byte tokens whose
    offset mappings are unreliable): the pair stays whole on whichever side
    of the boundary it falls.

    Fail-closed conditions:
      - empty candidate;
      - lossy tokenization (decode of the full sequence != the input text);
      - a token spanning the tail/candidate boundary (no prefix k decodes
        to exactly the tail text);
      - the candidate suffix does not decode back to the candidate text;
      - zero candidate tokens.
    """
    if not candidate:
        raise TokenAttributionError("empty candidate")
    full = tail_text + candidate
    ids = tokenizer.encode(full, add_special_tokens=False)
    if not ids:
        raise TokenAttributionError("no tokens")
    if tokenizer.decode(ids) != full:
        raise TokenAttributionError("lossy tokenization")
    if not tail_text:
        if tokenizer.decode(ids) != candidate:
            raise TokenAttributionError("candidate suffix mismatch")
        return ids, 0, len(ids)
    for k in range(1, len(ids) + 1):
        if tokenizer.decode(ids[:k]) == tail_text:
            if k == len(ids):
                raise TokenAttributionError("no candidate tokens")
            if tokenizer.decode(ids[k:]) != candidate:
                raise TokenAttributionError("candidate suffix mismatch")
            return ids, k, len(ids) - k
    raise TokenAttributionError("token straddles text boundary")


def mean_token_scores(prefix_last_lp, lp_getter, plans):
    """Reduce per-token log probabilities to mean scores (mean_token policy).

    `plans` is a list of (suffix_ids, first_target_position, target_count).
    `prefix_last_lp` is a callable token_id -> log prob of the first suffix
    token given the prefix, or None (callers must guarantee it is not None
    when a target token sits at position 0). `lp_getter(batch, position,
    token_id)` returns the log prob of suffix token `position + 1` given the
    prefix and the tokens before it.

    Each candidate is scored by its own target token count (never the batch
    padding length); padding positions are never read. Any non-finite value
    fails the whole batch (NonFiniteTokenScoreError).
    """
    scores = []
    counts = []
    for batch, (ids, target_start, target_count) in enumerate(plans):
        if target_count <= 0:
            raise TokenAttributionError("zero candidate tokens")
        total = 0.0
        for offset in range(target_count):
            position = target_start + offset
            if position >= len(ids):
                raise TokenAttributionError("target position out of range")
            token_id = ids[position]
            if position == 0:
                if prefix_last_lp is None:
                    raise TokenAttributionError("no conditioning for first token")
                logp = prefix_last_lp(token_id)
            else:
                logp = lp_getter(batch, position - 1, token_id)
            if not math.isfinite(logp):
                raise NonFiniteTokenScoreError()
            total += logp
        mean = total / target_count
        if not math.isfinite(mean):
            raise NonFiniteTokenScoreError()
        scores.append(mean)
        counts.append(target_count)
    return scores, counts


def legacy_sum_scores(prefix_last_lp, lp_getter, ids_list):
    """Faithful reproduction of the pre-#46 sum policy (legacy_sum, calib-only).

    Sums the log probability of every suffix token; the first suffix token is
    accumulated only when a prefix exists, exactly as the old
    ModelState.score() did. Any non-finite value fails the whole batch.
    """
    scores = []
    for batch, ids in enumerate(ids_list):
        total = 0.0
        if prefix_last_lp is not None and ids:
            logp = prefix_last_lp(ids[0])
            if not math.isfinite(logp):
                raise NonFiniteTokenScoreError()
            total += logp
        for position in range(len(ids) - 1):
            logp = lp_getter(batch, position, ids[position + 1])
            if not math.isfinite(logp):
                raise NonFiniteTokenScoreError()
            total += logp
        if not math.isfinite(total):
            raise NonFiniteTokenScoreError()
        scores.append(total)
    return scores


class ModelState:
    """Holds the loaded model and tokenizer.

    Scoring is stateless (ADR-0002): the prefix KV cache is built fresh inside
    each score() call as local state, so nothing accumulates across requests.
    """

    def __init__(self, model_path, context_window=CONTEXT_WINDOW,
                 scoring_strategy=SCORING_STRATEGY_MEAN_TOKEN):
        self.model_path = model_path
        self.context_window = context_window
        self.scoring_strategy = scoring_strategy
        self.model = None
        self.tokenizer = None
        self.pad_id = None

    def load(self):
        if self.model is not None:
            return
        import mlx.core as mx
        from mlx_lm.utils import load

        self.model, self.tokenizer = load(self.model_path)
        mx.eval(self.model.parameters())
        self.pad_id = self.tokenizer.pad_token_id
        if self.pad_id is None:
            self.pad_id = self.tokenizer.eos_token_id

    def unload(self):
        import mlx.core as mx

        self.model = None
        self.tokenizer = None
        try:
            mx.clear_cache()
        except Exception:
            pass

    @property
    def loaded(self):
        return self.model is not None

    def _build_prefix_cache(self, prefix_ids):
        import mlx.core as mx
        import mlx.nn as nn
        from mlx_lm.models.cache import make_prompt_cache

        cache = make_prompt_cache(self.model)
        if prefix_ids:
            x = mx.array([prefix_ids])
            logits = self.model(x, cache)
            last_lp = nn.log_softmax(logits[0, -1, :], axis=-1)
            mx.eval(last_lp, *[c.keys for c in cache], *[c.values for c in cache])
        else:
            last_lp = None
        return cache, last_lp

    def score(self, context, candidates):
        """Score candidates via teacher-forced log-prob accumulation.

        Window (ADR-0002): condition on the last `context_window` chars only.
        Stateless: the prefix KV cache is built fresh per request as local
        state, shared across the candidate batch, and freed on return.

        Tokenize strategy (#12) + attribution (#46), applied to the windowed
        string:
          - prefix = context[:-TAIL_CHARS], tokenized once, KV cached
          - per candidate: tokenize context[-TAIL_CHARS:] + candidate as tail
          - batched forward
          - mean_token: sum the log probs of the tokens that provably belong
            to the candidate text, divided by that candidate's own token
            count (see docs/token-attribution.md)
          - legacy_sum: pre-#46 policy (calibration-only), sum over all
            suffix tokens with the first token skipped when the prefix is
            empty
        """
        import mlx.core as mx
        import mlx.nn as nn

        self.load()

        n = len(candidates)
        if n == 0:
            return []

        context = window_context(context, self.context_window)

        if len(context) > TAIL_CHARS:
            prefix_text = context[:-TAIL_CHARS]
            tail_text = context[-TAIL_CHARS:]
        else:
            prefix_text = ""
            tail_text = context

        prefix_ids = (
            self.tokenizer.encode(prefix_text, add_special_tokens=False)
            if prefix_text
            else []
        )
        if self.scoring_strategy == SCORING_STRATEGY_MEAN_TOKEN:
            # Defined model-input rule (docs/token-attribution.md): when the
            # windowed context is empty there is nothing to condition the
            # first candidate token on; anchor it on EOS so its conditional
            # probability is defined. Identical for every candidate in the
            # batch, so it cannot bias comparison. The legacy policy
            # reproduced no such anchor and is not given one here.
            anchor = self.tokenizer.eos_token_id
            if anchor is None:
                anchor = self.pad_id
            if anchor is None:
                raise TokenAttributionError("no anchor token")
            if not prefix_ids and not tail_text:
                prefix_ids = [anchor]
        prefix_cache, prefix_last_lp = self._build_prefix_cache(prefix_ids)

        if self.scoring_strategy == SCORING_STRATEGY_MEAN_TOKEN:
            plans = [
                candidate_scoring_plan(self.tokenizer, tail_text, c)
                for c in candidates
            ]
            ids_per_candidate = [plan[0] for plan in plans]
        else:
            ids_per_candidate = [
                self.tokenizer.encode(tail_text + c, add_special_tokens=False)
                for c in candidates
            ]

        max_tail = max(len(t) for t in ids_per_candidate)
        padded = [
            t + [self.pad_id] * (max_tail - len(t)) for t in ids_per_candidate
        ]
        suffix = mx.array(padded)

        has_prefix = prefix_last_lp is not None
        if has_prefix:
            score_cache = self._expand_cache(prefix_cache, n, max_tail)
        else:
            score_cache = None

        logits = self.model(suffix, score_cache)
        lp = nn.log_softmax(logits, axis=-1)

        def prefix_lp(token_id):
            return float(prefix_last_lp[token_id])

        def suffix_lp(batch, position, token_id):
            return float(lp[batch, position, token_id])

        if self.scoring_strategy == SCORING_STRATEGY_MEAN_TOKEN:
            scores, counts = mean_token_scores(
                prefix_lp if has_prefix else None, suffix_lp, plans
            )
        else:
            scores = legacy_sum_scores(
                prefix_lp if has_prefix else None, suffix_lp, ids_per_candidate
            )
            counts = None

        mx.eval(mx.array(scores))
        telemetry = os.environ.get("LLM_RERANK_TELEMETRY")
        if telemetry:
            # Calibration telemetry: scores and per-candidate token counts
            # only. Never contains context, candidate text, or token text.
            try:
                with open(telemetry, "a", encoding="utf-8") as f:
                    row = {"n": n, "scores": scores}
                    if counts is not None:
                        row["counts"] = counts
                    f.write(json.dumps(row) + "\n")
            except OSError:
                pass
        return scores

    def _expand_cache(self, ctx_cache, n, tail_len):
        import mlx.core as mx
        from mlx_lm.models.cache import KVCache

        result = []
        for c in ctx_cache:
            valid = c.offset
            ck = c.keys[..., :valid, :]
            cv = c.values[..., :valid, :]
            Hk, D = ck.shape[1], ck.shape[3]
            Vk, Dv = cv.shape[1], cv.shape[3]
            prefix_k = mx.broadcast_to(ck, (n, Hk, valid, D))
            prefix_v = mx.broadcast_to(cv, (n, Vk, valid, Dv))
            full_k = mx.concatenate(
                [prefix_k, mx.zeros((n, Hk, tail_len, D), dtype=ck.dtype)], axis=2
            )
            full_v = mx.concatenate(
                [prefix_v, mx.zeros((n, Vk, tail_len, Dv), dtype=cv.dtype)], axis=2
            )
            nc = KVCache()
            nc.keys = full_k
            nc.values = full_v
            nc.offset = valid
            result.append(nc)
        mx.eval([nc.keys for nc in result], [nc.values for nc in result])
        return result


def protocol_error(
    code,
    phase="validate",
    retryable=False,
    request_id=None,
    plan_identity=None,
):
    messages = {
        "invalid_json": "request is not valid JSON",
        "invalid_request": "request does not match the scoring protocol",
        "inference_failed": "scoring failed",
        "invalid_score_result": "scorer returned an invalid result",
        "score_count_mismatch": "score count does not match candidate count",
        "non_finite_score": "scorer returned a non-finite score",
        "token_attribution_failed": "candidate token attribution failed",
        "policy_mismatch": "plan policy does not match the daemon scoring mode",
        "server_error": "scoring transport failed",
        "maintenance_in_progress": "scoring is temporarily quiesced for maintenance",
        "evidence_unavailable": "evidence service is not configured",
        "config_identity_mismatch": "declared evidence config identity does not match the daemon",
        "active_identity_refused": "the active identity is unknown, broken or missing a compat declaration",
        "fact_identity_mismatch": "fact store epoch does not match the request",
        "not_caught_up": "daemon fact snapshot is behind the request watermark",
        "fact_store_fault": "fact store is missing or unreadable",
        "accelerate_fault": "Accelerate retrieval backend failed",
        "mlx_fault": "MLX retrieval backend failed",
        "representation_fault": "representation generation failed",
    }
    response = {
        "version": PROTOCOL_VERSION,
        "error": {
            "code": code,
            "message": messages[code],
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "retryable": retryable,
            "phase": phase,
            "remediation": (
                "retry the request" if retryable else "fix the request or scorer"
            ),
            "cause": None,
        },
    }
    if request_id is not None and plan_identity is not None:
        response["request_id"] = request_id
        response["plan_identity"] = plan_identity
    return response


def make_request(request_id, plan_identity, context, candidates,
                 baseline_policy_id=MEAN_TOKEN_POLICY_ID):
    return {
        "version": PROTOCOL_VERSION,
        "request_id": request_id,
        "plan_identity": plan_identity,
        "baseline_policy_id": baseline_policy_id,
        "context": context,
        "candidates": candidates,
    }


def read_request(conn, deadline_seconds=REQUEST_READ_DEADLINE, now=time.monotonic):
    chunks = []
    size = 0
    deadline = now() + deadline_seconds
    while True:
        remaining = deadline - now()
        if remaining <= 0:
            raise TimeoutError("request deadline exceeded")
        conn.settimeout(remaining)
        try:
            chunk = conn.recv(65536)
        except socket.timeout:
            # socket.timeout is only an alias of TimeoutError since
            # Python 3.10; normalize so callers see one exception type.
            raise TimeoutError("request deadline exceeded") from None
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds protocol size limit")
        chunks.append(chunk)
    framed = b"".join(chunks)
    if not framed:
        return None
    if framed.count(b"\n") != 1 or not framed.endswith(b"\n"):
        raise ValueError("request must be one JSON document followed by one LF")
    return framed[:-1].decode("utf-8")


def handle_health(state, request, coordinator=None):
    """Model-free serving observation (issue #51 status core).

    Never loads the model: `model_loaded` is the daemon's own current state,
    which is exactly what a status command may observe without triggering a
    load. Response carries no context, candidate text or embedding.
    """
    strategy = getattr(state, "scoring_strategy", SCORING_STRATEGY_MEAN_TOKEN)
    response = {
        "version": PROTOCOL_VERSION,
        "request_id": request["request_id"],
        "kind": "health",
        "health": {
            "pid": os.getpid(),
            "model_loaded": bool(getattr(state, "loaded", False)),
            "scoring_strategy": strategy,
            "policy_id": POLICY_ID_BY_STRATEGY.get(strategy),
            "model_identity": daemon_model_identity(state),
            "context_window": getattr(state, "context_window", CONTEXT_WINDOW),
            "cache_limit_mb": getattr(state, "cache_limit_mb", CACHE_LIMIT_MB),
            "telemetry": bool(os.environ.get("LLM_RERANK_TELEMETRY")),
            "started_at": getattr(state, "started_at", None),
        },
    }
    if coordinator is not None:
        response["health"].update(coordinator.health())
    compatibility = getattr(state, "compatibility_report", None)
    if compatibility is not None:
        response["health"]["compatibility"] = compatibility
    return response


def handle_evidence_request(state, data, coordinator=None,
                            completion_sink=None):
    """Serve one retrieval-evidence request (Squirrel#61, AC61-1/AC61-2).

    The evidence path is model-free: it reads the fact store read-only and
    computes the canonical oracle's candidate-level evidence with the
    configured injectable representation provider.  Success responses carry
    ``status: "ok"`` with an explicit ``zero_evidence`` flag; every true
    fault (store, watermark, identity, representation, oracle) is a bounded
    error object that must make the plugin pass the whole window through.
    """
    try:
        decoder = json.JSONDecoder(object_pairs_hook=reject_duplicate_object_fields)
        req, parsed_end = decoder.raw_decode(data)
        if parsed_end != len(data):
            raise ValueError("trailing request payload")
    except (json.JSONDecodeError, TypeError, ValueError):
        return protocol_error("invalid_json")

    if (
        not isinstance(req, dict)
        or set(req) != EVIDENCE_FIELDS
        or type(req["version"]) is not int
        or req["version"] != PROTOCOL_VERSION
        or req.get("kind") != EVIDENCE_KIND
        or not isinstance(req["request_id"], str)
        or not req["request_id"]
        or not isinstance(req["plan_identity"], str)
        or not req["plan_identity"]
        or not isinstance(req["schema_id"], str)
        or not req["schema_id"]
        or not isinstance(req["category"], str)
        or not req["category"]
        or not isinstance(req["canonical_segment_input"], str)
        or not isinstance(req["preceding_text"], str)
        # The request carries the recent-64-char 上文 window (ADR-0002 / the
        # plugin's plan truncation); a longer context is out of contract and
        # would silently change the query semantics.
        or len(req["preceding_text"]) > 64
        or not isinstance(req["candidates"], list)
        or not req["candidates"]
        or any(
            not isinstance(candidate, str) or not candidate
            for candidate in req["candidates"]
        )
        or not isinstance(req["config_identity"], str)
        or not req["config_identity"]
    ):
        return protocol_error("invalid_request")

    service = getattr(state, "evidence_service", None)
    if service is None:
        return protocol_error(
            "evidence_unavailable",
            phase="evidence",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )

    # Config-identity binding: the daemon serves exactly the identity it was
    # configured with; a request declaring anything else is a true fault
    # (plugin passes through), never a silently different evidence algorithm.
    if req["config_identity"] != service.config_identity():
        return protocol_error(
            "config_identity_mismatch",
            phase="evidence",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )

    lease = coordinator.begin_request() if coordinator is not None else None
    if coordinator is not None and lease is None:
        return protocol_error(
            "maintenance_in_progress", phase="maintenance", retryable=True,
            request_id=req["request_id"], plan_identity=req["plan_identity"])
    if lease is not None and completion_sink is None:
        lease.complete()
        return protocol_error(
            "server_error",
            phase="transport",
            retryable=True,
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )

    def finish(response):
        if lease is not None:
            try:
                completion_sink(lease)
            except Exception:
                lease.complete()
                raise
        return response

    try:
        result = service.serve(req)
    except EvidenceError as error:
        code = error.code if error.code in _EVIDENCE_FAULT_CODES else "oracle_fault"
        # A catch-up failure is transient: the worker is still absorbing the
        # facts, so a retry after a moment is the honest remediation.  All
        # other evidence faults keep the pass-through semantics of #61.
        retryable = code == "not_caught_up"
        return finish(protocol_error(
            code,
            phase="evidence",
            retryable=retryable,
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    except Exception:  # noqa: BLE001 - any fault fails closed
        return finish(protocol_error(
            "oracle_fault",
            phase="evidence",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))

    return finish({
        "version": PROTOCOL_VERSION,
        "kind": EVIDENCE_KIND,
        "request_id": req["request_id"],
        "plan_identity": req["plan_identity"],
        "config_identity": req["config_identity"],
        "fact_high_water": req["fact_high_water"],
        "status": "ok",
        "zero_evidence": result["zero_evidence"],
        "evidence": result["evidence"],
        "query_point": result["query_point"],
    })


_EVIDENCE_FAULT_CODES = frozenset((
    "evidence_unavailable",
    "config_identity_mismatch",
    "active_identity_refused",
    "fact_identity_mismatch",
    "not_caught_up",
    "fact_store_fault",
    "oracle_fault",
    "accelerate_fault",
    "mlx_fault",
    "representation_fault",
    "invalid_request",
))


def handle_request(state, data, coordinator=None, completion_sink=None):
    try:
        decoder = json.JSONDecoder(object_pairs_hook=reject_duplicate_object_fields)
        req, parsed_end = decoder.raw_decode(data)
        if parsed_end != len(data):
            raise ValueError("trailing request payload")
    except (json.JSONDecodeError, TypeError, ValueError):
        return protocol_error("invalid_json")

    # Health handshake (additive v2 request kind; scoring requests are
    # untouched and must not carry a "kind" field).
    if isinstance(req, dict) and req.get("kind") == "health":
        if (
            set(req) != {"version", "request_id", "kind"}
            or type(req["version"]) is not int
            or req["version"] != PROTOCOL_VERSION
            or not isinstance(req["request_id"], str)
            or not req["request_id"]
        ):
            return protocol_error("invalid_request")
        return handle_health(state, req, coordinator)

    # Retrieval-evidence request (Squirrel#61, AC61-1): the plugin asks for
    # the candidate-level oracle evidence of one rerank group.  Additive
    # request kind like health; scoring requests never carry "kind".
    if isinstance(req, dict) and req.get("kind") == EVIDENCE_KIND:
        return handle_evidence_request(state, data, coordinator,
                                       completion_sink)

    if (
        not isinstance(req, dict)
        or set(req) != REQUEST_FIELDS
        or type(req["version"]) is not int
        or req["version"] != PROTOCOL_VERSION
        or not isinstance(req["request_id"], str)
        or not req["request_id"]
        or not isinstance(req["plan_identity"], str)
        or not req["plan_identity"]
        or not isinstance(req["baseline_policy_id"], str)
        or not req["baseline_policy_id"]
        or not isinstance(req["context"], str)
        or not isinstance(req["candidates"], list)
        or any(
            not isinstance(candidate, str) or not candidate
            for candidate in req["candidates"]
        )
    ):
        return protocol_error("invalid_request")

    # Policy binding: the declared baseline_policy_id must be the exact id
    # of the daemon's scoring mode (or a frozen-baseline composition whose
    # rule and model identity match it), otherwise the plan's declared
    # normalization could be silently served by a different algorithm.
    strategy = getattr(state, "scoring_strategy", SCORING_STRATEGY_MEAN_TOKEN)
    if not accepted_by_strategy(req["baseline_policy_id"], strategy, state):
        return protocol_error(
            "policy_mismatch",
            phase="validate",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )

    lease = coordinator.begin_request() if coordinator is not None else None
    if coordinator is not None and lease is None:
        return protocol_error(
            "maintenance_in_progress", phase="maintenance", retryable=True,
            request_id=req["request_id"], plan_identity=req["plan_identity"])
    # A coordinated request must hand its lease to the transport owner. There
    # is no safe default completion point before that owner's sendall attempt.
    if lease is not None and completion_sink is None:
        lease.complete()
        return protocol_error(
            "server_error",
            phase="transport",
            retryable=True,
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )

    def finish(response):
        if lease is not None:
            try:
                completion_sink(lease)
            except Exception:
                lease.complete()
                raise
        return response

    try:
        scores = state.score(req["context"], req["candidates"])
    except TimeoutError:
        return finish(protocol_error(
            "inference_failed",
            phase="score",
            retryable=True,
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    except TokenAttributionError:
        return finish(protocol_error(
            "token_attribution_failed",
            phase="score",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    except NonFiniteTokenScoreError:
        return finish(protocol_error(
            "non_finite_score",
            phase="score",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    except Exception:
        return finish(protocol_error(
            "inference_failed",
            phase="score",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))

    if not isinstance(scores, list) or any(
        isinstance(score, bool) or not isinstance(score, (int, float))
        for score in scores
    ):
        return finish(protocol_error(
            "invalid_score_result",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    if len(scores) != len(req["candidates"]):
        return finish(protocol_error(
            "score_count_mismatch",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    try:
        has_non_finite_score = any(not math.isfinite(score) for score in scores)
    except OverflowError:
        has_non_finite_score = True
    if has_non_finite_score:
        return finish(protocol_error(
            "non_finite_score",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        ))
    return finish({
        "version": PROTOCOL_VERSION,
        "request_id": req["request_id"],
        "plan_identity": req["plan_identity"],
        "scores": scores,
    })


def serve_scoring_connection(state, conn, coordinator=None,
                             activity_sink=None):
    """Serve one scoring connection and complete its request only after send.

    A client acknowledgement is not needed for quiesce. The server-side
    `sendall()` attempt is the response-delivery linearization point; a broken
    pipe is terminal too and releases the request lease in the same finally
    block.
    """
    completions = []
    try:
        conn.settimeout(5.0)
        if activity_sink is not None:
            activity_sink()
        data = read_request(conn)
        if data is not None:
            response = handle_request(state, data, coordinator,
                                      completion_sink=completions.append)
            conn.sendall(
                (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
            )
            if activity_sink is not None:
                activity_sink()
    except (socket.timeout, TimeoutError):
        try:
            conn.sendall(
                (
                    json.dumps(protocol_error("server_error", phase="transport",
                                              retryable=True)) + "\n"
                ).encode("utf-8")
            )
        except Exception:
            pass
    except Exception:
        try:
            conn.sendall(
                (
                    json.dumps(protocol_error("server_error", phase="transport"))
                    + "\n"
                ).encode("utf-8")
            )
        except Exception:
            pass
    finally:
        for lease in completions:
            lease.complete()


def run_server(sock_path, model_path, context_window=CONTEXT_WINDOW,
               cache_limit_mb=CACHE_LIMIT_MB,
               scoring_strategy=SCORING_STRATEGY_MEAN_TOKEN, test_mode=False,
               control_socket=None, facts_root=None, evidence_config=None):
    import mlx.core as mx

    if cache_limit_mb > 0:
        mx.set_cache_limit(cache_limit_mb * 10**6)

    state = ModelState(model_path, context_window, scoring_strategy)
    state.cache_limit_mb = cache_limit_mb
    state.started_at = datetime.now(timezone.utc).isoformat()
    facts_root = (facts_root or os.environ.get("SQUIRREL_SEMANTIC_MEMORY_ROOT")
                  or FACTS_ROOT)
    control_socket = control_socket or os.path.join(facts_root,
                                                     "llm-rerank-control.sock")
    if evidence_config is not None:
        # #63/#64/#65/#66 wiring: when the config declares a derived root and
        # an active generation, the delta state machine becomes both the
        # evidence snapshot source and the coordinator's derived-state
        # recovery, and the staging machine (if the config declares a
        # desired identity different from the active one) resumably builds the
        # target generation in the background.  Both builders share the
        # single-builder lease (spec "一次只运行一个 builder").
        # #65: the active manifest -- not the config -- is the source of
        # truth for what is active after a runtime publish, so both machines
        # and the evidence service resolve the active generation id and
        # representation from it when present and valid; the publisher
        # performs the blue-green switch (its transaction and the staging
        # worker serialize on the shared publish lock).
        # #66: a present-but-invalid / unknown active manifest REFUSES the
        # load of derived state -- there is no config-active fallback
        # (SCN-66-10).  The machines are constructed in a refused state and
        # every evidence request fails closed (pass-through); status reports
        # the refusal reason.
        builder_lock = threading.Lock()
        publish_lock = threading.Lock()
        active_generation_id = None
        active_representation_id = None
        active_identity = None
        refuse_reason = None
        try:
            derived_root = evidence_config.get("derived_root")
        except (KeyError, TypeError, ValueError):
            derived_root = None
        if derived_root:
            from delta import read_facts_schema_version
            try:
                facts_schema_version = read_facts_schema_version(facts_root)
            except Exception:  # noqa: BLE001 - the manifest may predate facts
                facts_schema_version = None
            from publish import resolve_active_identity
            active_identity, refuse_reason = resolve_active_identity(
                derived_root, facts_schema_version=facts_schema_version)
            if active_identity is not None and refuse_reason is None:
                active_generation_id = (
                    read_active_manifest(derived_root)[0]["generation_id"])
                active_representation_id = active_identity[
                    compat.LAYER_REPRESENTATION]
        machine = build_delta_machine_from_config(
            facts_root, evidence_config, builder_lock=builder_lock,
            active_generation_id=active_generation_id,
            active_representation_id=active_representation_id,
            refuse_reason=refuse_reason)
        coordinator = MaintenanceCoordinator(
            facts_root, recovery=machine, auto_open_fact_handle=True)
        if machine is not None:
            coordinator.register_builder(machine)
        # #67: when the delta machine's recovery found no healthy rollback it
        # recorded ``force_rebuild_requested`` -- the staging machine must
        # rebuild from facts regardless of desired == active (AC67-6).  The
        # machine-level refusal is authoritative (the delta machine may have
        # recovered via rollback even when the manifest-level resolve refused,
        # in which case the recovered active manifest is valid and the
        # staging machine must NOT idle on the stale manifest-level refusal).
        force_rebuild = (machine is not None
                         and machine.force_rebuild_requested())
        machine_refuse = (machine.refuse_reason()
                          if machine is not None else None)
        staging_refuse_reason = (None
                                 if force_rebuild or machine_refuse is None
                                 else machine_refuse)
        # #67: the delta machine's rollback recovery rewrote the active
        # manifest -- the staging machine must gate against the RECOVERED
        # active (id + representation), never the pre-recovery one, and the
        # compatibility report must reflect the recovered active identity.
        staging_active_generation_id = active_generation_id
        staging_active_representation_id = active_representation_id
        report_active_identity = active_identity
        if derived_root and machine is not None and not force_rebuild:
            try:
                from publish import active_identity_from_manifest
                manifest, manifest_reason = read_active_manifest(derived_root)
                if manifest is not None and manifest_reason is None:
                    staging_active_generation_id = manifest["generation_id"]
                    staging_active_representation_id = manifest[
                        "representation_id"]
                    report_active_identity = active_identity_from_manifest(
                        manifest)
            except Exception:  # noqa: BLE001 - best effort; keep the config
                pass
        staging_machine = build_staging_machine_from_config(
            facts_root, evidence_config, builder_lock=builder_lock,
            active_generation_id=staging_active_generation_id,
            active_representation_id=staging_active_representation_id,
            publish_lock=publish_lock, active_identity=active_identity,
            refuse_reason=staging_refuse_reason,
            force_rebuild=force_rebuild)
        publisher = build_publisher_from_config(
            facts_root, evidence_config, staging_machine, machine,
            publish_lock)
        state.evidence_service = build_evidence_service_from_config(
            facts_root, evidence_config, machine=machine)
        # #67 wiring: the dirty scheduler asks the single staging builder to
        # compact; a successful publish clears the forced-build flags so the
        # compaction terminates (the delta absorbed, no second builder).
        if machine is not None and staging_machine is not None:
            machine.set_compaction_trigger(
                staging_machine.request_compaction)
            if publisher is not None:
                publisher.add_publish_success_hook(
                    staging_machine.notify_publish_success)
        state.compatibility_report = build_compat_report(
            evidence_config, facts_root, report_active_identity,
            machine_refuse if machine is not None else refuse_reason,
            staging_machine, machine)
        # #67 retention pass at startup (never mid-publish): sweep any
        # leftovers outside {active, rollback, live staging} left by a crash.
        if derived_root:
            try:
                from retention import sweep_from_manifests
                sweep_from_manifests(derived_root)
            except Exception:  # noqa: BLE001 - best effort; never block start
                pass
    else:
        machine = None
        staging_machine = None
        publisher = None
        coordinator = (
            MaintenanceCoordinator(facts_root, auto_open_fact_handle=True)
            if facts_root else None
        )
    if control_socket and coordinator is None:
        raise ValueError("--control-socket requires --facts-root")
    if control_socket and os.path.abspath(control_socket) == os.path.abspath(sock_path):
        raise ValueError("scoring and control sockets must differ")
    if control_socket:
        validate_control_path(control_socket)
    last_activity = time.time()
    lock = threading.Lock()

    def mark_activity():
        nonlocal last_activity
        with lock:
            last_activity = time.time()

    # Scoring and control endpoints are distinct, but both need the same
    # owner-only, symlink-safe parent guarantee.
    validate_control_path(sock_path)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o600)
    srv.listen(5)
    srv.settimeout(1.0)

    if test_mode:
        print(f"READY {sock_path}", flush=True)

    def idle_watchdog():
        nonlocal last_activity
        while True:
            time.sleep(10)
            with lock:
                if state.loaded and (time.time() - last_activity) > IDLE_TIMEOUT:
                    state.unload()
                    if test_mode:
                        print("UNLOADED (idle timeout)", flush=True)

    watchdog = threading.Thread(target=idle_watchdog, daemon=True)
    watchdog.start()
    control_stop = threading.Event()
    control_thread = None
    if control_socket:
        control_thread = threading.Thread(
            target=run_control_server,
            args=(control_socket, coordinator, None, control_stop),
            daemon=True,
        )
        control_thread.start()

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            try:
                with lock:
                    last_activity = time.time()
                serve_scoring_connection(
                    state, conn, coordinator,
                    activity_sink=mark_activity,
                )
                with lock:
                    last_activity = time.time()
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if control_thread is not None:
            control_stop.set()
            try:
                wake = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                wake.connect(control_socket)
                wake.close()
            except OSError:
                pass
            control_thread.join(2.0)
        if coordinator is not None:
            coordinator.close()
        if machine is not None:
            machine.close()
        if staging_machine is not None:
            staging_machine.close()
        if publisher is not None:
            publisher.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)


def self_test(sock_path, model_path):
    """Start server in background, send test requests, verify responses."""
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, __file__, "--socket", sock_path, "--model", model_path, "--serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    if not line.startswith("READY"):
        print(f"FAIL: server did not become ready: {line}", file=sys.stderr)
        proc.kill()
        return False

    time.sleep(0.1)
    ok = True

    def send(req):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data.decode("utf-8"))

    try:
        resp = send(
            make_request(
                "self-test-1", "self-test-plan-1", "发起", ["攻击", "公鸡"]
            )
        )
        if "scores" not in resp or len(resp["scores"]) != 2:
            print(f"FAIL: unexpected response: {resp}", file=sys.stderr)
            ok = False
        else:
            print(f"PASS: scores = {resp['scores']}")

        resp2 = send(
            make_request(
                "self-test-2", "self-test-plan-2", "今天", ["攻击", "公鸡"]
            )
        )
        if "scores" not in resp2 or len(resp2["scores"]) != 2:
            print(f"FAIL: unexpected response: {resp2}", file=sys.stderr)
            ok = False
        else:
            print(f"PASS: scores = {resp2['scores']}")
            if resp["scores"] != resp2["scores"]:
                print("PASS: different contexts produce different scores")
            else:
                print("WARN: same scores for different contexts")

        resp3 = send(make_request("self-test-3", "self-test-plan-3", "", []))
        if resp3.get("scores") != []:
            print(f"FAIL: empty candidates: {resp3}", file=sys.stderr)
            ok = False
        else:
            print("PASS: empty candidates returns empty scores")

        resp4 = send(make_request("self-test-4", "self-test-plan-4", "你好", ["世界"]))
        if "scores" not in resp4:
            print(f"FAIL: single candidate: {resp4}", file=sys.stderr)
            ok = False
        else:
            print(f"PASS: single candidate score = {resp4['scores']}")

    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        ok = False
    finally:
        proc.terminate()
        proc.wait()

    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM rerank daemon")
    parser.add_argument("--socket", default=SOCKET_PATH)
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--facts-root")
    parser.add_argument("--control-socket")
    parser.add_argument(
        "--evidence-config",
        help="JSON file configuring the retrieval-evidence service "
        "(representation seam + oracle params + gamma); absent = evidence "
        "requests fail with evidence_unavailable",
    )
    parser.add_argument(
        "--context-window",
        type=int,
        default=CONTEXT_WINDOW,
        help="chars of 上文 tail to condition on (ADR-0002)",
    )
    parser.add_argument(
        "--cache-limit-mb",
        type=int,
        default=CACHE_LIMIT_MB,
        help="MLX allocator cache cap in MB; 0 = unlimited",
    )
    parser.add_argument(
        "--scoring",
        choices=[SCORING_STRATEGY_MEAN_TOKEN, SCORING_STRATEGY_LEGACY_SUM],
        default=SCORING_STRATEGY_MEAN_TOKEN,
        help="scoring strategy; legacy_sum reproduces the pre-#46 sum policy "
        "for calibration comparison only",
    )
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.context_window < 1:
        parser.error("--context-window must be >= 1")

    if args.cache_limit_mb < 0:
        parser.error("--cache-limit-mb must be >= 0")

    if args.test:
        ok = self_test(args.socket, args.model)
        sys.exit(0 if ok else 1)
    else:
        evidence_config = None
        if args.evidence_config:
            import json as _json
            with open(args.evidence_config, encoding="utf-8") as handle:
                evidence_config = _json.load(handle)
        run_server(
            args.socket, args.model, args.context_window, args.cache_limit_mb,
            args.scoring, test_mode=True, control_socket=args.control_socket,
            facts_root=args.facts_root, evidence_config=evidence_config
        )
