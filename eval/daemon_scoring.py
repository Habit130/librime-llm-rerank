#!/usr/bin/env python3
"""Mean-token LM scoring client for the #106 α recalibration.

Talks the existing daemon scoring protocol (``mean_token``,
``baseline_policy_id = mean-token-lm-v1``) over the Unix socket — the same
protocol the plugin's ``LlmScorer`` uses, so the LM scores are exactly what
the frozen policy would produce.  Fail-closed: any daemon error (token
attribution, non-finite score, policy mismatch, transport) raises
``DaemonScoringError``, and the caller marks the event 无法重放 (SCN-106-5).
"""

import json
import socket
from typing import List

# Daemon protocol (daemon/server.py).
PROTOCOL_VERSION = 2
MEAN_TOKEN_POLICY_ID = "mean-token-lm-v1"


class DaemonScoringError(Exception):
    """The daemon failed to score a batch (fail closed)."""


def score_batch(socket_path: str,
                context: str,
                candidates: List[str],
                request_id: str,
                plan_identity: str,
                timeout_s: float = 120.0) -> List[float]:
    """Score one candidate batch via the mean_token daemon protocol.

    ``context`` is the 上文 (last 64 characters, ADR-0002); ``candidates``
    the saved competition texts in merge order.  Returns the per-candidate
    mean-token LM scores (log-prob means).  Raises ``DaemonScoringError`` on
    any daemon or transport failure.
    """
    if not candidates:
        return []
    request = {
        "version": PROTOCOL_VERSION,
        "request_id": request_id,
        "plan_identity": plan_identity,
        "baseline_policy_id": MEAN_TOKEN_POLICY_ID,
        "context": context,
        "candidates": candidates,
    }
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect(socket_path)
        sock.sendall((json.dumps(request, ensure_ascii=False) + "\n")
                     .encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    except (OSError, socket.timeout, ConnectionError) as error:
        raise DaemonScoringError(
            "daemon transport failed: %s" % error) from error
    finally:
        sock.close()
    try:
        response = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DaemonScoringError(
            "daemon returned invalid JSON: %s" % error) from error
    if "error" in response:
        code = response["error"].get("code", "unknown")
        raise DaemonScoringError("daemon error: %s" % code)
    scores = response.get("scores")
    if not isinstance(scores, list) or len(scores) != len(candidates):
        raise DaemonScoringError(
            "daemon score count mismatch: got %r for %d candidates"
            % (scores and len(scores), len(candidates)))
    for value in scores:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DaemonScoringError("daemon returned non-numeric score")
    return [float(value) for value in scores]
