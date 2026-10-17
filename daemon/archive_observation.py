"""Passive daemon-side observation into the private input archive (#191).

The observer copies an owned snapshot on a real daemon edge (a scoring request
accepted for scoring, a scoring outcome, a model load, a model unload) and
attempts a bounded non-waiting admission through the shared producer. It never
serializes, connects, retries, or waits on the collector; transport and
storage happen on the producer's background sender. Admission is refused when
the observed policy is not fresh and enabled, and a refused snapshot is
dropped, never held for a later backfill.

Archive package imports are deferred to observer construction so this module
(and `daemon/server.py`) stays importable in a `daemon/`-only deployment where
the archive package is not present; an enabled archive socket then fails that
single construction and observation stays off.

Text content exists only inside the deliberately private payload of a request
observation and only while an admission attempt is in flight. Ordinary
records, local status, and this module's output are content-free. The daemon
scoring wire carries no secure-input signal, so the daemon does not claim any
sensitive-input detection: it records exactly the wire-carried window.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import threading
import time
import uuid

# The daemon is started as `python daemon/server.py`, so only the daemon
# directory is on sys.path by default. Add the checkout root so the shared
# archive package is importable when it exists; a `daemon/`-only deployment
# simply fails the lazy import inside DaemonArchiveObserver.__init__.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DAEMON_OBSERVATION_VERSION = 1
DAEMON_STAGES = ("request", "scoring", "load", "unload")
_UNKNOWN_SCHEMA = "unknown"
_MODEL_IDENTITY_BASIS = "daemon_model_path_basename_unverified_content"
_CONTEXT_WINDOW_RULE = "unicode_char_tail"
_ATTRIBUTION_RULE = "decode_prefix_reconstruction"
_DECOMPOSITION = "combined_tokenize_forward_scalar_extraction"
_RUNTIME_DISTRIBUTIONS = ("mlx", "mlx-lm", "numpy")

_PROCESS_ORIGIN = time.monotonic()


def monotonic_ms():
    """One process-relative monotonic clock domain for all stated edges."""
    return (time.monotonic() - _PROCESS_ORIGIN) * 1000.0


def wall_ms():
    """Absolute UTC wall milliseconds; the only cross-process clock."""
    return int(time.time() * 1000)


def _safe_token(value):
    from archive.safety import safe_token

    return safe_token(value)


def _hex_or_none(value):
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return None


def _token_or_none(value):
    return _safe_token(value) if isinstance(value, str) else None


def _trust_problem(socket_path):
    """Owner-only local trust gate for the archive socket.

    Returns None when the immediate parent directory (and the socket, when it
    already exists) is owner-only, or an error code otherwise. A socket that
    does not exist yet cannot be trusted into existence: it is treated as
    absent, and each admission re-checks before any content is held.
    """
    if not isinstance(socket_path, str) or not socket_path or socket_path[0] != os.sep:
        return "invalid_request"
    parent = os.path.dirname(socket_path)
    if not parent:
        return "unsafe_root"
    try:
        if os.path.islink(parent):
            return "unsafe_root"
        parent_info = os.lstat(parent)
    except OSError:
        return "unsafe_root"
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != os.geteuid()
        or stat.S_IMODE(parent_info.st_mode) & 0o077
    ):
        return "unsafe_root"
    try:
        socket_info = os.lstat(socket_path)
    except FileNotFoundError:
        return None
    except OSError:
        return "unsafe_root"
    if (
        not stat.S_ISSOCK(socket_info.st_mode)
        or socket_info.st_uid != os.geteuid()
        or stat.S_IMODE(socket_info.st_mode) & 0o077
    ):
        return "unsafe_root"
    return None


def _runtime_versions(record):
    versions = {}
    if isinstance(record, dict) and isinstance(record.get("versions"), dict):
        source = record["versions"]
    else:
        source = {}
        try:
            from personal_lora_live import runtime_versions

            source = runtime_versions()
        except Exception:  # noqa: BLE001 - identity is advisory, never fatal
            source = {}
    for name in _RUNTIME_DISTRIBUTIONS:
        value = source.get(name)
        versions[name] = value if _safe_token(value) else None
    return versions


class DaemonArchiveObserver(object):
    """One observer per daemon process; safe to call from any daemon thread.

    Construction resolves the archive package: in a `daemon/`-only deployment
    without the archive package, construction fails and the caller leaves
    observation off; every hook then stays a no-op.
    """

    def __init__(self, socket_path, source_instance_id=None, limits=None):
        from archive.interface import CONTENT_VERSION, ENVELOPE_VERSION
        from archive.producer import Producer

        self.socket_path = socket_path
        self.source_instance_id = source_instance_id or (
            "daemon-%s-%s" % (os.getpid(), uuid.uuid4().hex[:8])
        )
        self.disabled_reason = None
        if _trust_problem(socket_path) == "unsafe_root":
            # Refuse to hold content for a destination that is not owner-only
            # at daemon start; capture stays off for this process.
            self.disabled_reason = "unsafe_archive_socket"
        self._envelope_version = ENVELOPE_VERSION
        self._content_version = CONTENT_VERSION
        self._lock = threading.Lock()
        self._sequence = 0
        self._process_counter = 0
        self._refused_untrusted = 0
        self._producer = Producer(
            socket_path,
            source_instance_id=self.source_instance_id,
            limits=limits,
        )

    def close(self):
        self._producer.close()

    def next_process_id(self):
        with self._lock:
            self._process_counter += 1
            return "dsr-%s-%d" % (os.getpid(), self._process_counter)

    def local_status(self):
        status = self._producer.local_status()
        status["daemon_observation_version"] = DAEMON_OBSERVATION_VERSION
        status["disabled_reason"] = self.disabled_reason
        status["refused_untrusted"] = self._refused_untrusted
        return status

    def capture_effective(self):
        """Cheap local pre-check: fresh enabled policy and a trusted socket."""
        if self.disabled_reason is not None:
            return False
        if _trust_problem(self.socket_path) is not None:
            return False
        try:
            status = self._producer.local_status()
        except Exception:  # noqa: BLE001 - observation is never fatal
            return False
        return bool(
            status.get("fresh")
            and status.get("observed_desired") == "enabled"
            and not status.get("collector_unavailable")
        )

    def _next_sequence(self):
        with self._lock:
            self._sequence += 1
            return self._sequence

    def _admit(self, frame):
        """Bounded non-waiting admission. Never raises, never waits."""
        try:
            if _trust_problem(self.socket_path) is not None:
                with self._lock:
                    self._refused_untrusted += 1
                return None
            return self._producer.admit(frame)
        except Exception:  # noqa: BLE001 - an observation fault cannot fail scoring
            return None

    def _base_frame(self, stage, process_id):
        return {
            "envelope_version": self._envelope_version,
            "content_version": self._content_version,
            "schema_id": _UNKNOWN_SCHEMA,
            "source_instance_id": self.source_instance_id,
            "source_local_sequence": self._next_sequence(),
            "observation_kind": "daemon_observation",
            "daemon_observation_version": DAEMON_OBSERVATION_VERSION,
            "daemon_stage": stage,
            "stage": stage,
            "process_id": process_id,
            "observed_at_wall_ms": wall_ms(),
            "eligibility": "included",
            "host_persistence": "unknown",
        }

    def observe_request(self, request, state, process_id, effective_policy_id):
        """Observe one accepted scoring request; returns the taken edges.

        The edges dict is returned even when capture is not effective so the
        caller can time the outcome edge without holding content anywhere.
        """
        edges = {"request_accepted": monotonic_ms()}
        if not self.capture_effective():
            return edges
        try:
            context = request.get("context")
            candidates = request.get("candidates")
            if not isinstance(context, str) or not isinstance(candidates, list):
                return edges
            window = getattr(state, "context_window", 64)
            if not isinstance(window, int) or isinstance(window, bool) or window < 1:
                window = 64
            effective = context[-window:]
            clean_candidates = [
                candidate for candidate in candidates if isinstance(candidate, str)
            ]
            strategy = getattr(state, "scoring_strategy", "mean_token")
            if strategy not in ("mean_token", "legacy_sum"):
                strategy = "mean_token"
            declared = request.get("baseline_policy_id")
            digest = None
            exact = False
            if isinstance(declared, str) and declared:
                digest = hashlib.sha256(declared.encode("utf-8")).hexdigest()
                exact = declared == effective_policy_id
            model_path = getattr(state, "model_path", "") or ""
            model_identity = os.path.basename(os.path.normpath(model_path)) if model_path else ""
            frame = self._base_frame("request", process_id)
            frame.update(
                {
                    "request_id": _token_or_none(request.get("request_id")),
                    "plan_identity": _token_or_none(request.get("plan_identity")),
                    "effective_policy_id": _token_or_none(effective_policy_id)
                    or "unknown",
                    "declared_policy_digest": digest,
                    "declared_policy_exact": exact,
                    "scoring_strategy": strategy,
                    "context_window_rule": _CONTEXT_WINDOW_RULE,
                    "attribution_rule": _ATTRIBUTION_RULE,
                    "context_window_chars": window,
                    "requested_context_chars": len(context),
                    "effective_context_chars": len(effective),
                    "context_truncated": len(effective) < len(context),
                    "candidate_count": len(clean_candidates),
                    "candidate_chars": sum(len(candidate) for candidate in clean_candidates),
                    "model_identity": _token_or_none(model_identity),
                    "model_identity_basis": _MODEL_IDENTITY_BASIS,
                    "adapter_present": bool(getattr(state, "adapter_path", "")),
                    "adapter_digest": _hex_or_none(getattr(state, "adapter_digest", None)),
                    "edges": dict(edges),
                    "payload": {
                        "requested_context": context,
                        "effective_context": effective,
                        "candidates": list(clean_candidates),
                    },
                }
            )
            self._admit(frame)
        except Exception:  # noqa: BLE001 - observation is never fatal
            pass
        return edges

    def observe_scoring_outcome(self, meta):
        """Observe the decided scoring outcome for an accepted request."""
        if not self.capture_effective():
            return
        try:
            frame = self._base_frame("scoring", meta["process_id"])
            frame.update(
                {
                    "request_id": _token_or_none(meta.get("request_id")),
                    "outcome_code": meta["outcome_code"],
                    "error_phase": meta.get("error_phase"),
                    "scoring_started": bool(meta.get("scoring_started")),
                    "load_included": bool(meta.get("load_included")),
                    "scoring_ms": meta.get("scoring_ms"),
                    "load_ms": meta.get("load_ms"),
                    "scores_returned": meta.get("scores_returned"),
                    "decomposition": _DECOMPOSITION,
                    "edges": dict(meta["edges"]),
                }
            )
            self._admit(frame)
        except Exception:  # noqa: BLE001
            pass

    def note_load_started(self):
        if not self.capture_effective():
            return None
        try:
            return monotonic_ms()
        except Exception:  # noqa: BLE001
            return None

    def note_load_finished(self, started_ms, ok, state):
        if started_ms is None:
            return
        if not self.capture_effective():
            return
        try:
            finished = monotonic_ms()
            record = getattr(state, "identity_record", None)
            model_weights = None
            model_identity = None
            if isinstance(record, dict):
                model = record.get("model")
                if isinstance(model, dict):
                    model_identity = model.get("basename")
                    files = model.get("files")
                    if isinstance(files, dict):
                        weights = files.get("model.safetensors")
                        if isinstance(weights, dict):
                            model_weights = weights.get("sha256")
            if model_identity is None:
                model_path = getattr(state, "model_path", "") or ""
                model_identity = (
                    os.path.basename(os.path.normpath(model_path))
                    if model_path
                    else ""
                )
            frame = self._base_frame("load", "dload-%s" % self.source_instance_id)
            frame.update(
                {
                    "load_outcome": "completed" if ok else "failed",
                    "load_ms": max(0.0, finished - started_ms),
                    "model_identity": _token_or_none(model_identity),
                    "tokenizer_identity": None,
                    "adapter_present": bool(getattr(state, "adapter_path", "")),
                    "adapter_digest": _hex_or_none(getattr(state, "adapter_digest", None)),
                    "model_weights_sha256": _hex_or_none(model_weights),
                    "runtime_versions": _runtime_versions(record),
                    "edges": {
                        "load_started": float(started_ms),
                        "load_completed": float(finished),
                    },
                }
            )
            self._admit(frame)
        except Exception:  # noqa: BLE001
            pass

    def note_unload(self, reason, state):
        try:
            started = monotonic_ms()
        except Exception:  # noqa: BLE001
            return
        if not self.capture_effective():
            return
        try:
            if reason not in ("idle", "identity_change", "identity_invalid", "unspecified"):
                reason = "unspecified"
            finished = monotonic_ms()
            frame = self._base_frame("unload", "dunload-%s" % self.source_instance_id)
            frame.update(
                {
                    "unload_reason": reason,
                    "unload_ms": max(0.0, finished - started),
                    "edges": {
                        "unload_started": float(started),
                        "unload_completed": float(finished),
                    },
                }
            )
            self._admit(frame)
        except Exception:  # noqa: BLE001
            pass
