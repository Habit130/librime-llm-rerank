#!/usr/bin/env python3
"""LLM rerank daemon: MLX inference over a unix domain socket.

Protocol (JSON, newline-delimited):
  Request:  {"version": 1, "request_id": "...", "plan_identity": "...",
             "context": "<preceding text>", "candidates": ["c1", "c2", ...]}
  Response: {"version": 1, "request_id": "...", "plan_identity": "...",
             "scores": [s1, s2, ...]}
  Error:    {"version": 1, "error": {"code": "...", ...}}

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

SOCKET_PATH = os.path.expanduser(
    "~/Library/Application Support/Squirrel/llm-rerank.sock"
)
MODEL_PATH = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
IDLE_TIMEOUT = 300  # seconds
TAIL_CHARS = 4  # chars of context tail re-tokenized per candidate
CONTEXT_WINDOW = 64  # chars of 上文 tail the model is conditioned on (ADR-0002)
CACHE_LIMIT_MB = 512  # MLX allocator cache cap; 0 = unlimited (default MLX behavior)
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
REQUEST_READ_DEADLINE = 5.0
REQUEST_FIELDS = {
    "version",
    "request_id",
    "plan_identity",
    "context",
    "candidates",
}


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


class ModelState:
    """Holds the loaded model and tokenizer.

    Scoring is stateless (ADR-0002): the prefix KV cache is built fresh inside
    each score() call as local state, so nothing accumulates across requests.
    """

    def __init__(self, model_path, context_window=CONTEXT_WINDOW):
        self.model_path = model_path
        self.context_window = context_window
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

        Tokenize strategy (#12), applied to the windowed string:
          - prefix = context[:-TAIL_CHARS], tokenized once, KV cached
          - per candidate: tokenize context[-TAIL_CHARS:] + candidate as tail
          - batched forward, sum log probs of candidate tokens
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
        prefix_cache, prefix_last_lp = self._build_prefix_cache(prefix_ids)

        tail_ids_per_cand = []
        for c in candidates:
            full_tail = tail_text + c
            ids = self.tokenizer.encode(full_tail, add_special_tokens=False)
            tail_ids_per_cand.append(ids)

        max_tail = max(len(t) for t in tail_ids_per_cand)
        padded = [t + [self.pad_id] * (max_tail - len(t)) for t in tail_ids_per_cand]
        suffix = mx.array(padded)

        has_prefix = prefix_last_lp is not None
        if has_prefix:
            score_cache = self._expand_cache(prefix_cache, n, max_tail)
        else:
            score_cache = None

        logits = self.model(suffix, score_cache)
        lp = nn.log_softmax(logits, axis=-1)

        scores = []
        for i in range(n):
            tail_ids = tail_ids_per_cand[i]
            total = 0.0
            if has_prefix and tail_ids:
                total += float(prefix_last_lp[tail_ids[0]])
            for t in range(len(tail_ids) - 1):
                total += float(lp[i, t, tail_ids[t + 1]])
            scores.append(total)

        mx.eval(mx.array(scores))
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
        "server_error": "scoring transport failed",
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


def make_request(request_id, plan_identity, context, candidates):
    return {
        "version": PROTOCOL_VERSION,
        "request_id": request_id,
        "plan_identity": plan_identity,
        "context": context,
        "candidates": candidates,
    }


def read_request(conn, deadline_seconds=REQUEST_READ_DEADLINE):
    chunks = []
    size = 0
    deadline = time.monotonic() + deadline_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline exceeded")
        conn.settimeout(remaining)
        chunk = conn.recv(65536)
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


def handle_request(state, data):
    try:
        decoder = json.JSONDecoder(object_pairs_hook=reject_duplicate_object_fields)
        req, parsed_end = decoder.raw_decode(data)
        if parsed_end != len(data):
            raise ValueError("trailing request payload")
    except (json.JSONDecodeError, TypeError, ValueError):
        return protocol_error("invalid_json")

    if (
        not isinstance(req, dict)
        or set(req) != REQUEST_FIELDS
        or type(req["version"]) is not int
        or req["version"] != PROTOCOL_VERSION
        or not isinstance(req["request_id"], str)
        or not req["request_id"]
        or not isinstance(req["plan_identity"], str)
        or not req["plan_identity"]
        or not isinstance(req["context"], str)
        or not isinstance(req["candidates"], list)
        or any(
            not isinstance(candidate, str) or not candidate
            for candidate in req["candidates"]
        )
    ):
        return protocol_error("invalid_request")

    try:
        scores = state.score(req["context"], req["candidates"])
    except TimeoutError:
        return protocol_error(
            "inference_failed",
            phase="score",
            retryable=True,
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )
    except Exception:
        return protocol_error(
            "inference_failed",
            phase="score",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )

    if not isinstance(scores, list) or any(
        isinstance(score, bool) or not isinstance(score, (int, float))
        for score in scores
    ):
        return protocol_error(
            "invalid_score_result",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )
    if len(scores) != len(req["candidates"]):
        return protocol_error(
            "score_count_mismatch",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )
    try:
        has_non_finite_score = any(not math.isfinite(score) for score in scores)
    except OverflowError:
        has_non_finite_score = True
    if has_non_finite_score:
        return protocol_error(
            "non_finite_score",
            request_id=req["request_id"],
            plan_identity=req["plan_identity"],
        )
    return {
        "version": PROTOCOL_VERSION,
        "request_id": req["request_id"],
        "plan_identity": req["plan_identity"],
        "scores": scores,
    }


def run_server(sock_path, model_path, context_window=CONTEXT_WINDOW, cache_limit_mb=CACHE_LIMIT_MB, test_mode=False):
    import mlx.core as mx

    if cache_limit_mb > 0:
        mx.set_cache_limit(cache_limit_mb * 10**6)

    state = ModelState(model_path, context_window)
    last_activity = time.time()
    lock = threading.Lock()

    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
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

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            try:
                conn.settimeout(5.0)
                data = read_request(conn)
                if data is not None:
                    with lock:
                        last_activity = time.time()
                    resp = handle_request(state, data)
                    with lock:
                        last_activity = time.time()
                    conn.sendall(
                        (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")
                    )
            except socket.timeout:
                try:
                    conn.sendall(
                        (
                            json.dumps(
                                protocol_error(
                                    "server_error",
                                    phase="transport",
                                    retryable=True,
                                )
                            )
                            + "\n"
                        ).encode("utf-8")
                    )
                except Exception:
                    pass
            except Exception:
                try:
                    conn.sendall(
                        (
                            json.dumps(
                                protocol_error(
                                    "server_error",
                                    phase="transport",
                                )
                            )
                            + "\n"
                        ).encode("utf-8")
                    )
                except Exception:
                    pass
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
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
        run_server(
            args.socket, args.model, args.context_window, args.cache_limit_mb, test_mode=True
        )
