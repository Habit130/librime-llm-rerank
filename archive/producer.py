"""Non-blocking producer admission.

`Producer.admit` captures an owned snapshot and attempts a bounded queue
insertion. It does not serialize, compress, connect, flush, or wait for the
collector, a full queue, or a query/control lock. A background sender performs
those steps.
"""

from __future__ import annotations

import threading
import time
import uuid

from archive.interface import (
    CONTENT_VERSION,
    ENVELOPE_VERSION,
    INTERFACE_VERSION,
    SUPPORTED_SCHEMA,
    Client,
)
from archive.limits import resolve

_HIGH_KINDS = {
    "start",
    "commit_attempt",
    "raw_finalization",
    "cancellation",
    "unavailable_client",
    "unknown_outcome",
    "loss_notice",
    "exclusion_notice",
    "provenance",
}


class AdmissionResult(object):
    def __init__(self, admitted, code, capture_seq=None, priority="low"):
        self.admitted = admitted
        self.code = code
        self.capture_seq = capture_seq
        self.durable = False
        self.priority = priority

    def as_dict(self):
        return {
            "admitted": self.admitted,
            "code": self.code,
            "capture_seq": self.capture_seq,
            "durable": False,
            "priority": self.priority,
            "interface_version": INTERFACE_VERSION,
            "content_included": False,
        }


class _Item(object):
    def __init__(self, capture_seq, kind, priority, snapshot, size):
        self.capture_seq = capture_seq
        self.kind = kind
        self.priority = priority
        self.snapshot = snapshot
        self.size = size


def _owned_snapshot(value, depth=0):
    if depth > 8:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_owned_snapshot(item, depth + 1) for item in value]
    if isinstance(value, dict):
        owned = {}
        for key, item in value.items():
            owned[str(key)] = _owned_snapshot(item, depth + 1)
        return owned
    return None


def _budget_bytes(value, limit, acc):
    if acc[0] > limit:
        return
    if isinstance(value, str):
        acc[0] += len(value.encode("utf-8"))
    elif isinstance(value, dict):
        for key, item in value.items():
            acc[0] += len(str(key).encode("utf-8"))
            _budget_bytes(item, limit, acc)
            if acc[0] > limit:
                return
    elif isinstance(value, list):
        for item in value:
            _budget_bytes(item, limit, acc)
            if acc[0] > limit:
                return
    else:
        acc[0] += 8


def _priority_for(kind):
    if kind in _HIGH_KINDS:
        return "high"
    return "low"


class Producer(object):
    def __init__(self, socket_path, source_instance_id=None, limits=None, sndbuf=None):
        self.socket_path = socket_path
        self.source_instance_id = source_instance_id or uuid.uuid4().hex
        self.limits = resolve(limits)
        self.sndbuf = sndbuf
        self._lock = threading.Lock()
        self._queue = []
        self._bytes = 0
        self._capture_seq = 0
        self._known_refused = 0
        self._known_dropped = 0
        self._local_losses = []
        self._observed_revision = None
        self._observed_desired = None
        self._observed_at = None
        self._collector_unavailable = True
        self._last_poll = None
        self._stop = False
        self._sender = threading.Thread(target=self._sender_loop, name="archive-sender", daemon=True)
        self._sender.start()

    def close(self):
        self._stop = True
        self._sender.join(timeout=1.0)

    def local_status(self):
        with self._lock:
            fresh = self._cache_fresh_locked(time.monotonic())
            return {
                "interface_version": INTERFACE_VERSION,
                "source_instance_id": self.source_instance_id,
                "observed_revision": self._observed_revision,
                "observed_desired": self._observed_desired,
                "fresh": fresh,
                "collector_unavailable": self._collector_unavailable,
                "queued": len(self._queue),
                "known_refused": self._known_refused,
                "known_dropped": self._known_dropped,
                "content_included": False,
            }

    def admit(self, observation):
        """Input-path admission. Must return without collector or storage waits."""
        if not isinstance(observation, dict):
            return AdmissionResult(False, "invalid_request")
        envelope = observation.get("envelope_version", ENVELOPE_VERSION)
        content = observation.get("content_version", CONTENT_VERSION)
        if envelope != ENVELOPE_VERSION or content != CONTENT_VERSION:
            return AdmissionResult(False, "unsupported_version")
        snapshot = _owned_snapshot(observation)
        if not isinstance(snapshot, dict):
            return AdmissionResult(False, "invalid_request")
        acc = [0]
        _budget_bytes(snapshot, self.limits["max_event_bytes"], acc)
        if acc[0] > self.limits["max_event_bytes"]:
            return AdmissionResult(False, "event_too_large")
        if snapshot.get("eligibility") == "excluded" or snapshot.get("excluded") is True:
            notice = self._exclusion_notice(snapshot)
            return self._enqueue(notice, "exclusion_notice", _budget_of(notice))
        schema = snapshot.get("schema_id", "unknown")
        kind = snapshot.get("observation_kind")
        if kind != "loss_notice" and schema not in (SUPPORTED_SCHEMA, "unknown"):
            return AdmissionResult(False, "unsupported_schema")
        now = time.monotonic()
        with self._lock:
            fresh = self._cache_fresh_locked(now)
            desired = self._observed_desired
        if not fresh or desired != "enabled":
            code = "capture_disabled" if fresh and desired in {"off", "paused"} else "policy_not_effective"
            return AdmissionResult(False, code)
        kind = snapshot.get("observation_kind") or "unknown_outcome"
        return self._enqueue(snapshot, kind, acc[0])

    def _exclusion_notice(self, snapshot):
        return {
            "envelope_version": ENVELOPE_VERSION,
            "content_version": CONTENT_VERSION,
            "source_instance_id": snapshot.get("source_instance_id") or self.source_instance_id,
            "source_local_sequence": snapshot.get("source_local_sequence"),
            "observation_kind": "exclusion_notice",
            "process_id": snapshot.get("process_id"),
            "schema_id": "unknown",
            "reason": "deliberate_exclusion",
            "eligibility": "excluded",
            "payload": None,
        }

    def _cache_fresh_locked(self, now):
        if self._observed_at is None or self._observed_revision is None:
            return False
        window = self.limits["freshness_window_ms"] / 1000.0
        return (now - self._observed_at) <= window

    def _enqueue(self, snapshot, kind, size):
        priority = _priority_for(kind)
        with self._lock:
            self._capture_seq += 1
            capture_seq = self._capture_seq
            item = _Item(capture_seq, kind, priority, snapshot, size)
            if self._fits_locked(size):
                self._queue.append(item)
                self._bytes += size
                return AdmissionResult(True, "admitted", capture_seq, priority)
            if priority == "high":
                for index, old in enumerate(self._queue):
                    if old.priority == "low":
                        self._drop_locked(index)
                        self._queue.append(item)
                        self._bytes += size
                        return AdmissionResult(True, "admitted", capture_seq, priority)
            self._known_refused += 1
            self._remember_loss_locked(item, "queue_saturated")
            return AdmissionResult(False, "queue_saturated", capture_seq, priority)

    def _fits_locked(self, size):
        return (
            len(self._queue) + 1 <= self.limits["producer_queue_count"]
            and self._bytes + size <= self.limits["producer_queue_bytes"]
        )

    def _drop_locked(self, index):
        old = self._queue.pop(index)
        self._bytes -= old.size
        self._known_dropped += 1
        self._remember_loss_locked(old, "displaced_for_priority")

    def _remember_loss_locked(self, item, reason):
        identity = item.snapshot if isinstance(item.snapshot, dict) else {}
        self._local_losses.append(
            {
                "observation_kind": "loss_notice",
                "source_instance_id": identity.get("source_instance_id") or self.source_instance_id,
                "source_local_sequence": identity.get("source_local_sequence"),
                "process_id": identity.get("process_id"),
                "dropped_kind": item.kind,
                "reason": reason,
                "payload": None,
                "schema_id": "unknown",
                "envelope_version": ENVELOPE_VERSION,
                "content_version": CONTENT_VERSION,
            }
        )
        if len(self._local_losses) > 64:
            self._local_losses = self._local_losses[-64:]

    def _drain(self, limit):
        with self._lock:
            batch = self._queue[:limit]
            del self._queue[:limit]
            self._bytes -= sum(item.size for item in batch)
            losses = self._local_losses
            self._local_losses = []
            return batch, losses

    def _requeue(self, items):
        with self._lock:
            for item in reversed(items):
                if self._fits_locked(item.size):
                    self._queue.insert(0, item)
                    self._bytes += item.size
                else:
                    self._known_dropped += 1
                    self._remember_loss_locked(item, "requeue_saturated")

    def _sender_loop(self):
        while not self._stop:
            self._poll_policy()
            batch, losses = self._drain(self.limits["batch_size"])
            if losses:
                self._send_losses(losses)
            if not batch:
                time.sleep(0.01)
                continue
            if not self._send_batch(batch):
                self._requeue(batch)

    def _client(self):
        timeout = self.limits["connect_timeout_ms"] / 1000.0
        return Client(self.socket_path, timeout=timeout, sndbuf=self.sndbuf)

    def _poll_policy(self):
        now = time.monotonic()
        interval = self.limits["heartbeat_interval_ms"] / 1000.0
        if self._last_poll is not None and (now - self._last_poll) < interval:
            return
        self._last_poll = now
        response = self._client().call(
            "policy_observe",
            {
                "source_instance_id": self.source_instance_id,
                "observed_revision": self._observed_revision,
            },
        )
        now = time.monotonic()
        with self._lock:
            if not response.get("ok"):
                self._collector_unavailable = True
                return
            body = response.get("body") or {}
            self._collector_unavailable = False
            self._observed_revision = body.get("desired_revision")
            self._observed_desired = body.get("desired_policy")
            self._observed_at = now

    def _send_batch(self, batch):
        observations = [item.snapshot for item in batch]
        response = self._client().call("admit_batch", {"observations": observations})
        if not response.get("ok") and (response.get("error") or {}).get("code") == "collector_unavailable":
            with self._lock:
                self._collector_unavailable = True
            return False
        return True

    def _send_losses(self, losses):
        self._client().call("admit_batch", {"observations": losses})


def _budget_of(snapshot):
    acc = [0]
    _budget_bytes(snapshot, 1000000, acc)
    return acc[0]
