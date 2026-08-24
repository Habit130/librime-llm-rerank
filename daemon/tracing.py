#!/usr/bin/env python3
"""Desensitized trial traces and advisory exit alarms (Habit130/squirrel#74).

The daemon-side trial instrumentation of the semantic evidence path.  A
local, app-controlled ``traces/`` directory under the semantic-memory root
holds:

- one identity-only structured trace per request whose semantic emit order
  differs from the γ=0 shadow baseline, or per true fault (SCN-74-1/2);
- a rolling aggregates record for unchanged successful requests: counts plus
  a segmented latency histogram only (SCN-74-3);
- user-confirmed mispromotion annotations keyed by request ID / event ID
  (SCN-74-5), never private facts;
- advisory exit alarms (SCN-74-6/7): persisted for `status` / `--json`,
  suggesting rollback to ``γ=0`` only, never writing any config or switch.

Privacy contract (AC74-4, spec "结构化 trace 只引用事件 ID"): every file in
this module — traces, aggregates, annotations, alarms, status sections and
logs — may contain schema ids, stable codes, request IDs, event IDs,
fingerprints, watermarks, ranks, score decompositions and latencies only.
Raw 上文, candidate text and embeddings never appear; the tests probe for
them.

File layout (all owner-only, 0700 dir / 0600 files):

    <root>/traces/
        trace-<trace_id>.json      one order-change or fault trace
        aggregates.json            rolling aggregates + sliding windows
        annotations.json           user-confirmed mispromotion annotations
        alarms.json                fired + dismissed alarm state
        index.json                 request_id -> trace_id + kind + timestamp

Windows (seam 5, pinned): sliding windows.  Complete-comparable windows
count requests whose group was complete and comparable (the plugin
declares the live trial bit; wire key ``trial.actionable`` is historical,
Squirrel#152).  That bit is not CONTEXT.md Actionable Event (eval
denominator: non-zero pre-existing retrieval evidence).  Fault-rate and
latency windows count all semantic (evidence) requests.  Denominators are
never mixed.
"""

import json
import math
import os
import stat
import threading
import time
from datetime import datetime, timezone

TRACES_DIRNAME = "traces"
TRACE_VERSION = 1
AGGREGATES_VERSION = 1
ANNOTATIONS_VERSION = 1
ALARMS_VERSION = 1
INDEX_VERSION = 1

FILE_MODE = 0o600
DIR_MODE = 0o700

# Sliding-window alarm thresholds (spec #43 真实试用退出规则; pinned here so
# tests and status share one definition).
MISPROMOTION_WINDOW = 100          # consecutive complete-comparable requests
MISPROMOTION_LIMIT = 3             # user-confirmed mispromotions in window
FAULT_WINDOW = 300                 # consecutive semantic requests
FAULT_RATE_LIMIT = 0.01            # true-fault rate > 1% in window
LATENCY_WINDOW = 300               # semantic requests per latency window
LATENCY_P95_MS = 50.0              # full-request gate, spec #43
LATENCY_P99_MS = 75.0              # full-request gate, spec #43

# Segmented latency histogram buckets (ms, upper edge).  The full-request
# bucket is the last entry; p95/p99 gates apply to it.
LATENCY_BUCKETS_MS = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 75.0, 100.0, 200.0,
                      float("inf"))


class TracingError(Exception):
    """A tracing-path fault.  Never raised into the evidence serve path:
    tracing must never fail closed the evidence itself (it is advisory)."""


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


_SAFE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:+=")


def _safe_name(value, max_len=200):
    """Event/request ids are identity tokens; refuse anything hostile.

    ASCII-only by construction: any non-ASCII character (CJK 上文, candidate
    text, embeddings) fails, so a leaked raw-text string can never be
    persisted under an identity field (AC74-4).
    """
    if not isinstance(value, str) or not value:
        return None
    if len(value) > max_len:
        return None
    if not all(char in _SAFE_CHARS for char in value):
        return None
    return value



def _read_float(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) \
        else None


def _ensure_owner_dir(path):
    """Create/verify an owner-only directory (0700, not a symlink).

    Creates missing parent directories up to ``path`` (the semantic-memory
    root itself may not exist yet on a pristine machine).
    """
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        _ensure_owner_dir(parent)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        try:
            os.mkdir(path, DIR_MODE)
        except FileExistsError:
            pass
        except OSError as error:
            raise TracingError("traces_root_create_failed: %s" % error)
        st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise TracingError("traces_root_unsafe")
    if st.st_uid != os.getuid():
        raise TracingError("traces_root_owner")
    if stat.S_IMODE(st.st_mode) != DIR_MODE:
        try:
            os.chmod(path, DIR_MODE)
        except OSError as error:
            raise TracingError("traces_root_chmod_failed: %s" % error)
    return path


def _write_owner_file(path, payload):
    """Atomically write a 0600 JSON file (temp + rename, owner-only)."""
    _ensure_owner_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), FILE_MODE)
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as error:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise TracingError("trace_write_failed: %s" % error)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else default
    except (OSError, ValueError, TypeError):
        return default


def _percentile(ordered, q):
    if not ordered:
        return None
    index = int(math.ceil(q * len(ordered))) - 1
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


class TraceStore:
    """App-controlled trace/aggregate/annotation/alarm store under a root.

    Thread-safe: all durable mutations take a per-store lock.  Never writes
    outside ``<root>/traces`` and never touches facts, derived state, the
    three switches or ``γ`` (SCN-74-8).
    """

    def __init__(self, root, now=None):
        self._root = root
        self._dir = os.path.join(root, TRACES_DIRNAME)
        self._lock = threading.Lock()
        self._now = now or time.time

    def directory(self):
        return self._dir

    # ------------------------------------------------------------------
    # Public write entry points
    # ------------------------------------------------------------------

    def record_request(self, request_meta, outcome, trace_payload=None,
                       latency_segments=None):
        """Record one semantic (evidence) request.

        ``request_meta`` is the identity-only request envelope (schema_id,
        category, canonical_segment_input, request_id, plan_identity,
        config_identity, fact_high_water, complete_comparable,
        candidate_count).
        ``outcome`` is "ok" or a stable fault code; ``trace_payload`` is the
        full identity-only trace for order changes and faults (None for
        unchanged successes); ``latency_segments`` is the segmented latency
        dict for the histogram and the p95/p99 windows.

        Always updates the rolling aggregates; writes a full trace only for
        order changes and faults; evaluates alarms after each write.
        Returns the fired alarms list (possibly empty).
        """
        with self._lock:
            now_iso = _now_iso()
            trace_id = None
            if trace_payload is not None:
                trace_id = trace_payload.get("trace_id")
                if trace_id is None:
                    trace_id = self._new_trace_id(request_meta)
                trace_payload["trace_id"] = trace_id
                trace_payload["trace_version"] = TRACE_VERSION
                trace_payload.setdefault("recorded_at", now_iso)
                self._validate_trace_payload(trace_payload)
                self._write_trace(trace_id, trace_payload)
                self._index_trace(trace_id, request_meta, outcome, now_iso)
            self._update_aggregates(request_meta, outcome, latency_segments,
                                    trace_id is not None, now_iso)
            return self._evaluate_alarms(request_meta, now_iso)

    @staticmethod
    def _validate_trace_payload(payload):
        """AC74-4 gate: a trace may contain identity tokens and numbers only.

        The serialized payload must be pure ASCII; any 上文 / candidate text /
        embedding byte (non-ASCII or control) refuses the whole trace, and
        every identity field must pass ``_safe_name``.
        """
        if not isinstance(payload, dict):
            raise TracingError("trace_payload_invalid")
        for key in ("schema_id", "category", "canonical_segment_input",
                    "plan_identity", "config_identity", "request_id",
                    "trace_id", "error_code", "retrieval_backend"):
            if payload.get(key) is not None and _safe_name(
                    payload[key]) is None:
                raise TracingError("trace_identity_unsafe")
        for neighbor in payload.get("neighbors") or []:
            if not isinstance(neighbor, dict):
                raise TracingError("trace_payload_invalid")
            for key in ("event_id", "commit_id"):
                if neighbor.get(key) is not None and _safe_name(
                        neighbor[key]) is None:
                    raise TracingError("trace_identity_unsafe")
        serialized = json.dumps(payload, ensure_ascii=False)
        try:
            serialized.encode("ascii")
        except UnicodeEncodeError as error:
            raise TracingError(
                "trace_contains_non_ascii: %s" % error) from error

    def record_annotation(self, request_id, event_id=None, annotator=None):
        """Record a user-confirmed mispromotion by identity only.

        Refuses (returns None) when the request id is not known to the trace
        index; never copies private facts (SCN-74-5).  The event id, when
        given, must be a valid identity token; it is stored as-is without
        lookup (event ids live inside the trace body).
        """
        if _safe_name(request_id) is None:
            return None
        if event_id is not None and _safe_name(event_id) is None:
            return None
        with self._lock:
            index = self._read_index()
            entry = index.get(request_id)
            if entry is None or not isinstance(entry, dict):
                return None
            # A mispromotion can only be confirmed on an order-change trace
            # (the semantic emit order actually moved a candidate); fault
            # traces have no emission to judge.
            if entry.get("kind") != "order_change":
                return None
            annotations = self._read_annotations()
            for a in annotations.get("annotations", []):
                if a.get("request_id") == request_id:
                    # Already confirmed; return the existing record with the
                    # current alarm state (idempotent confirmation).
                    return a, self._evaluate_alarms(
                        {"complete_comparable": True,
                         "request_id": request_id},
                        _now_iso())
            record = {
                "annotation_id": "ann-%s" % (len(annotations.get(
                    "annotations", [])) + 1),
                "annotated_at": _now_iso(),
                "request_id": request_id,
                "trace_id": entry.get("trace_id"),
                "kind": "mispromotion",
                "event_id": event_id,
                "annotator": annotator,
            }
            annotations.setdefault("annotations", []).append(record)
            annotations["version"] = ANNOTATIONS_VERSION
            annotations["updated_at"] = _now_iso()
            self._write_annotations(annotations)
            # A confirmation can push a window over the threshold.
            alarms = self._evaluate_alarms(
                {"complete_comparable": True, "request_id": request_id},
                _now_iso())
            return record, alarms

    def dismiss_alarm(self, alarm_id, reason=None):
        """User may subjectively veto / dismiss an alarm (SCN-74-7).

        Dismissal never erases traces or annotations; the alarm record keeps
        its fired state and gains a dismissed marker.  The reason is the
        user's own veto note (deliberately free text -- the user typed it,
        not the system), bounded to 200 chars so the alarm record stays
        small; it is never 上文/candidate/embedding data.
        """
        if reason is not None:
            reason = str(reason)[:200]
        with self._lock:
            alarms = self._read_alarms()
            for alarm in alarms.get("alarms", []):
                if alarm.get("alarm_id") == alarm_id:
                    if alarm.get("dismissed_at"):
                        return alarm
                    alarm["dismissed_at"] = _now_iso()
                    alarm["dismiss_reason"] = reason
                    alarm["dismissed"] = True
                    alarms["updated_at"] = _now_iso()
                    self._write_alarms(alarms)
                    return alarm
            return None

    def list_alarms(self, include_dismissed=False):
        alarms = self._read_alarms().get("alarms", [])
        if not include_dismissed:
            alarms = [a for a in alarms if not a.get("dismissed")]
        return alarms

    def list_traces(self):
        """Identity-only trace summaries for `status` (never trace bodies)."""
        index = self._read_index()
        result = []
        for request_id, entry in sorted(index.items()):
            if request_id in ("version", "updated_at") or not isinstance(
                    entry, dict) or not entry.get("trace_id"):
                continue
            summary = {
                "request_id": request_id,
                "trace_id": entry.get("trace_id"),
                "kind": entry.get("kind"),
                "recorded_at": entry.get("recorded_at"),
            }
            for key in ("schema_id", "category"):
                if entry.get(key):
                    summary[key] = entry[key]
            result.append(summary)
        return result

    def aggregates(self):
        return self._read_aggregates()

    def annotations(self):
        return self._read_annotations().get("annotations", [])

    def clear(self):
        """Delete every app-controlled trace artifact (seam 2, SCN-74-9).

        Only the ``traces`` directory is removed; external copies the user
        made are out of scope (the caller's disclaimer covers that).
        """
        with self._lock:
            try:
                st = os.lstat(self._dir)
            except FileNotFoundError:
                return
            if (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)
                    or st.st_uid != os.getuid()):
                raise TracingError("traces_root_unsafe")
            for name in os.listdir(self._dir):
                path = os.path.join(self._dir, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
                    raise TracingError("traces_root_unsafe")
                os.unlink(path)
            os.rmdir(self._dir)

    # ------------------------------------------------------------------
    # Internal readers/writers
    # ------------------------------------------------------------------

    def _new_trace_id(self, request_meta):
        request_id = _safe_name(request_meta.get("request_id"))
        suffix = request_id or "anon"
        return "tr-%s-%s" % (suffix, int(self._now() * 1000))

    def _write_trace(self, trace_id, payload):
        if _safe_name(trace_id) is None:
            raise TracingError("trace_id_unsafe")
        _write_owner_file(self._trace_path(trace_id), payload)

    def _trace_path(self, trace_id):
        return os.path.join(self._dir, "trace-%s.json" % trace_id)

    def _read_index(self):
        return _read_json(os.path.join(self._dir, "index.json"), {})

    def _index_trace(self, trace_id, request_meta, outcome, now_iso):
        index = self._read_index()
        entry = {
            "trace_id": trace_id,
            "kind": outcome if outcome != "ok" else "order_change",
            "recorded_at": now_iso,
        }
        for key in ("schema_id", "category", "canonical_segment_input"):
            if request_meta.get(key):
                if _safe_name(request_meta[key]) is None:
                    raise TracingError("trace_identity_unsafe")
                entry[key] = request_meta[key]
        self._write_index_entry(index, request_meta, entry)

    def _index_complete_comparable(self, request_meta, outcome, seq, now_iso):
        """Index one complete-comparable request (trace or not) with its
        global sequence, so a later mispromotion confirmation can locate
        the event's position in the complete-comparable stream.

        Persisted index key ``actionable_seq`` is historical; do not
        migrate existing files.
        """
        index = self._read_index()
        existing = index.get(request_meta["request_id"])
        entry = {
            "recorded_at": now_iso,
            "actionable_seq": seq,
            "kind": existing.get("kind") if isinstance(existing, dict)
            else ("ok" if outcome == "ok" else outcome),
        }
        for key in ("schema_id", "category", "canonical_segment_input",
                    "trace_id"):
            if existing and isinstance(existing, dict) and existing.get(key):
                entry[key] = existing[key]
            elif request_meta.get(key):
                entry[key] = request_meta[key]
        self._write_index_entry(index, request_meta, entry)

    def _write_index_entry(self, index, request_meta, entry):
        index[request_meta["request_id"]] = entry
        index["version"] = INDEX_VERSION
        index["updated_at"] = _now_iso()
        _write_owner_file(os.path.join(self._dir, "index.json"), index)

    def _read_aggregates(self):
        value = _read_json(os.path.join(self._dir, "aggregates.json"), {})
        if not value:
            value = {
                "version": AGGREGATES_VERSION,
                "created_at": _now_iso(),
                "updated_at": None,
                "semantic_requests": 0,
                # Historical persist keys for the complete-comparable stream
                # (#152).  Do not rename; existing aggregates.json must load.
                "actionable_events": 0,
                "actionable_seq": 0,
                "order_changes": 0,
                "faults": 0,
                "passthroughs": 0,
                "latency_histogram": {
                    str(bucket): 0 for bucket in LATENCY_BUCKETS_MS
                },
                "latency_segments": {},
                # Sliding windows (capped FIFOs, identity only).
                "recent_actionable": [],
                "recent_outcomes": [],
                "recent_full_latencies": [],
            }
        return value

    def _update_aggregates(self, request_meta, outcome, latency_segments,
                           wrote_trace, now_iso):
        aggregates = self._read_aggregates()
        aggregates["semantic_requests"] += 1
        if request_meta.get("complete_comparable"):
            aggregates["actionable_events"] += 1
            aggregates["actionable_seq"] += 1
            seq = aggregates["actionable_seq"]
            ring = aggregates["recent_actionable"]
            ring.append(request_meta["request_id"])
            del ring[:-MISPROMOTION_WINDOW]
            # Index every complete-comparable request with its global
            # sequence so a mispromotion confirmed much later still knows
            # where the event sat in that stream (SCN-74-6 "任意连续 100 条").
            self._index_complete_comparable(
                request_meta, outcome, seq, now_iso)
        if outcome != "ok":
            aggregates["faults"] += 1
            # A true fault makes the plugin pass the window through (protocol
            # contract AC61-2); the daemon records that pass-through result.
            aggregates["passthroughs"] += 1
        elif wrote_trace:
            aggregates["order_changes"] += 1
        ring = aggregates["recent_outcomes"]
        ring.append(outcome)
        del ring[:-FAULT_WINDOW]
        segments = latency_segments or {}
        full = _read_float(segments.get("full_request_ms"))
        if full is not None:
            self._bump_histogram(aggregates["latency_histogram"], full)
            ring = aggregates["recent_full_latencies"]
            ring.append(full)
            # Two consecutive 300-request windows need up to 600 entries.
            del ring[:-(2 * LATENCY_WINDOW)]
        for key, value in segments.items():
            if key == "full_request_ms":
                continue
            value = _read_float(value)
            if value is None:
                continue
            segment = aggregates["latency_segments"].setdefault(key, {})
            segment["count"] = segment.get("count", 0) + 1
            segment["sum_ms"] = segment.get("sum_ms", 0.0) + value
            segment["max_ms"] = max(segment.get("max_ms", 0.0), value)
        aggregates["updated_at"] = now_iso
        _write_owner_file(os.path.join(self._dir, "aggregates.json"),
                          aggregates)

    @staticmethod
    def _bump_histogram(histogram, value_ms):
        for bucket in LATENCY_BUCKETS_MS:
            if value_ms <= bucket:
                histogram[str(bucket)] += 1
                return
        histogram[str(LATENCY_BUCKETS_MS[-1])] += 1

    def _read_annotations(self):
        value = _read_json(os.path.join(self._dir, "annotations.json"), {})
        if not value:
            value = {"version": ANNOTATIONS_VERSION, "annotations": []}
        return value

    def _write_annotations(self, annotations):
        _write_owner_file(os.path.join(self._dir, "annotations.json"),
                          annotations)

    def _read_alarms(self):
        value = _read_json(os.path.join(self._dir, "alarms.json"), {})
        if not value:
            value = {"version": ALARMS_VERSION, "alarms": []}
        return value

    def _write_alarms(self, alarms):
        _write_owner_file(os.path.join(self._dir, "alarms.json"), alarms)

    # ------------------------------------------------------------------
    # Alarm evaluation (sliding windows, pinned)
    # ------------------------------------------------------------------

    def _evaluate_alarms(self, request_meta, now_iso):
        """Evaluate every exit window after one recorded request.

        Fires at most one alarm per kind per evaluation; an already-fired
        (or dismissed) alarm with the same kind is not re-fired.  Returns
        the list of newly fired alarms.
        """
        fired = []
        for kind, evaluator in (
                ("mispromotion_rate", self._mispromotion_alarm),
                ("fault_rate", self._fault_rate_alarm),
                ("latency_gate", self._latency_alarm)):
            alarm = evaluator(now_iso)
            if alarm:
                fired.append(alarm)
        return fired

    def _mispromotion_alarm(self, now_iso):
        """3 user-confirmed mispromotions in any consecutive 100
        complete-comparable requests.

        Sliding-window semantics over the complete-comparable stream (not
        CONTEXT.md Actionable Event): each complete-comparable request
        carries a global ``actionable_seq`` in the index (historical persist
        key), so a confirmation that arrives long after the event still
        knows the event's position.  Three confirmed events fall inside
        some 100-event window iff their sequence span (max - min + 1) is at
        most 100.
        """
        index = self._read_index()
        confirmed = [
            index[a.get("request_id")].get("actionable_seq")
            for a in self._read_annotations().get("annotations", [])
            if a.get("kind") == "mispromotion"
            and a.get("request_id") is not None
            and isinstance(index.get(a.get("request_id")), dict)
        ]
        confirmed = [seq for seq in confirmed
                     if isinstance(seq, int) and seq > 0]
        if len(confirmed) < MISPROMOTION_LIMIT:
            return None
        window = MISPROMOTION_WINDOW
        # The 3 (or more) confirmed events span at most 100
        # complete-comparable requests: sort their sequences and check every
        # consecutive triple.
        ordered = sorted(confirmed)
        for i in range(len(ordered) - MISPROMOTION_LIMIT + 1):
            span = ordered[i + MISPROMOTION_LIMIT - 1] - ordered[i] + 1
            if span <= window:
                return self._fire_alarm(
                    "mispromotion_rate",
                    {"window": window, "confirmed": MISPROMOTION_LIMIT,
                     "span_events": span},
                    now_iso,
                    "%d user-confirmed mispromotions within %d consecutive "
                    "complete-comparable requests; suggest rollback to "
                    "gamma=0" % (MISPROMOTION_LIMIT, window))
        return None

    def _fault_rate_alarm(self, now_iso):
        """True-fault rate > 1% in any consecutive 300 semantic requests."""
        ring = self._read_aggregates().get("recent_outcomes", [])
        window = FAULT_WINDOW
        if len(ring) < window:
            return None
        for start in range(0, len(ring) - window + 1):
            chunk = ring[start:start + window]
            faults = sum(1 for outcome in chunk if outcome != "ok")
            rate = faults / float(window)
            if rate > FAULT_RATE_LIMIT:
                return self._fire_alarm(
                    "fault_rate",
                    {"window": window, "faults": faults, "rate": rate},
                    now_iso,
                    "true-fault rate %.2f%% exceeds 1%% in the last %d "
                    "semantic requests; suggest rollback to gamma=0"
                    % (rate * 100.0, window))
        return None

    def _latency_alarm(self, now_iso):
        """Two consecutive 300-request windows miss the p95/p99 gates."""
        ring = self._read_aggregates().get("recent_full_latencies", [])
        window = LATENCY_WINDOW
        if len(ring) < window + 1:
            return None
        windows = []
        for start in range(0, len(ring) - window + 1):
            chunk = sorted(ring[start:start + window])
            p95 = _percentile(chunk, 0.95)
            p99 = _percentile(chunk, 0.99)
            if p95 is None or p99 is None:
                continue
            windows.append({
                "start_index": start,
                "p95_ms": p95,
                "p99_ms": p99,
                "gate_p95_ms": LATENCY_P95_MS,
                "gate_p99_ms": LATENCY_P99_MS,
                "miss": p95 > LATENCY_P95_MS or p99 > LATENCY_P99_MS,
            })
        misses = [w for w in windows if w["miss"]]
        for first, second in zip(misses, misses[1:]):
            if second["start_index"] == first["start_index"] + 1:
                return self._fire_alarm(
                    "latency_gate",
                    {"window": window, "first": first, "second": second},
                    now_iso,
                    "two consecutive %d-request windows miss the p95/p99 "
                    "latency gates; suggest rollback to gamma=0" % window)
        return None

    def _fire_alarm(self, kind, detail, now_iso, message):
        """Persist one alarm (advisory; never writes config)."""
        alarms = self._read_alarms()
        for alarm in alarms.get("alarms", []):
            if alarm.get("kind") == kind and not alarm.get("dismissed"):
                return alarm  # already fired and not dismissed
        alarm = {
            "alarm_id": "alarm-%s-%s" % (kind, int(self._now() * 1000)),
            "kind": kind,
            "fired_at": now_iso,
            "message": message,
            "detail": detail,
            "dismissed": False,
            "suggestion": "rollback to gamma=0",
        }
        alarms.setdefault("alarms", []).append(alarm)
        alarms["updated_at"] = now_iso
        self._write_alarms(alarms)
        return alarm

