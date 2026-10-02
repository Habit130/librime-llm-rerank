"""Configurable input-archive limits.

These defaults are engineering choices, not a latency or zero-loss
certification. Accounting uses exact published JSONL byte lengths.
"""

from __future__ import annotations

DEFAULTS = {
    "producer_queue_count": 256,
    "producer_queue_bytes": 1048576,
    "collector_queue_count": 256,
    "collector_queue_bytes": 1048576,
    "max_event_bytes": 65536,
    "archive_capacity_bytes": 67108864,
    "warning_ratio": 0.8,
    "page_size_default": 20,
    "page_size_max": 50,
    "checkpoint_interval_ms": 250,
    "freshness_window_ms": 2000,
    "heartbeat_interval_ms": 500,
    "max_frame_bytes": 4194304,
    "batch_size": 64,
    "connect_timeout_ms": 1000,
    "management_timeout_ms": 5000,
}


def resolve(overrides=None):
    """Return a complete limit map. Unknown keys are refused by callers."""
    resolved = dict(DEFAULTS)
    for key, value in (overrides or {}).items():
        if key not in DEFAULTS:
            raise KeyError(key)
        resolved[key] = value
    _validate(resolved)
    return resolved


def _validate(limits):
    positive_ints = (
        "producer_queue_count",
        "producer_queue_bytes",
        "collector_queue_count",
        "collector_queue_bytes",
        "max_event_bytes",
        "archive_capacity_bytes",
        "page_size_default",
        "page_size_max",
        "freshness_window_ms",
        "heartbeat_interval_ms",
        "max_frame_bytes",
        "batch_size",
        "connect_timeout_ms",
        "management_timeout_ms",
    )
    for key in positive_ints:
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(key)
    if limits["page_size_default"] > limits["page_size_max"]:
        raise ValueError("page_size_default")
    if limits["page_size_max"] > 100:
        raise ValueError("page_size_max")
    ratio = limits["warning_ratio"]
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        raise ValueError("warning_ratio")
    if ratio <= 0 or ratio >= 1:
        raise ValueError("warning_ratio")
    interval = limits["checkpoint_interval_ms"]
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 0:
        raise ValueError("checkpoint_interval_ms")
