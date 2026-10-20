"""Shared versioned query semantics for the input archive.

This module is the single home for join/aggregate/detail semantics used by the
collector query surface and by the CLI and TUI Adapters. It never opens
observation storage. It computes identity relations, honest outcome
denominators, frontend timing distributions and group-level choice projections
from durable index rows at a published prefix.

Bound semantics (input-archive-query-v1), additive to input-archive-v1:

- Ordering of durable rows is ``durable_seq_ascending``; every view reports the
  ``as_of_durable_seq`` snapshot it read.
- A cursor is an opaque token naming a filter set and the snapshot it continued.
  It cannot silently cross a different filter set, an unknown snapshot or an
  unpublished position; those are explicit errors.
- Page size is bounded by ``page_size_max`` and the encoded response of a
  successful non-private page of a bounded view by ``query_page_bytes_max``;
  management/control responses and the status/daemon state reads are not
  pages.
- Private text is only ever returned for view ``process`` with
  ``private_detail`` true.
- A new out-of-order record can resolve a relation at a later prefix; a
  snapshot is immutable and is never rewritten.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math

from archive.interface import canonical_bytes

QUERY_VERSION = "input-archive-query-v1"
_SUPPORTED_QUERY_VERSIONS = (QUERY_VERSION,)
_CURSOR_PREFIX = "q1."
FRONTEND_TIMING_VERSION = 1
# Version 1 frontend timing is a payload inside provenance observations. Only a
# declared payload object drives this projection; the row's own stage token is
# evidence of intent, not of a numeric sample.
CHOICE_PROJECTION_VERSION = 1
CHOICE_COMPLETE_BASIS = "captured_group_members_and_target"
CHOICE_IDENTITY_BASIS = "source_instance_window_group"
PERCENTILE_METHOD = "nearest_rank_ceil_p_n_first_observed_value"
PERCENTILE_FIELD = "percentiles.nearest_rank_ceil_p_n_first_observed_value"

_VALIDITY_VALUES = {"valid", "invalid", "unknown"}
_ENDPOINT_VALUES = ("unavailable", "marked_text", "panel_update")
_TIMEBASE_MAX = (1 << 64) - 1
_MAX_NESTED_ACTIONS = 255


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _rate(numerator, denominator):
    """Exact count ratio, or None with no fabricated value."""
    if not denominator:
        return None
    return numerator / denominator


def percentiles(values):
    """Documented percentile method over observed sample values.

    Method ``nearest_rank_ceil_p_n_first_observed_value``: the p-th percentile
    is the smallest observed sample whose rank is at least ``ceil(p * n)``;
    small-N disclosure is reported, not hidden. Values are reported as given
    (frontend timing is integer nanoseconds) so every figure is hand
    computable. No SLA, statistical-adequacy or performance certification is
    attached to this distribution.
    """
    samples = sorted(value for value in values)
    count = len(samples)
    block = {
        "count": count,
        "method": PERCENTILE_METHOD,
        "field": PERCENTILE_FIELD,
        "small_n": count < 20,
        "small_n_disclosure": (
            "fewer_than_20_samples_percentiles_are_descriptive_only"
            if count < 20
            else None
        ),
    }
    if not samples:
        block["percentiles"] = None
        block["min"] = None
        block["max"] = None
        block["mean"] = None
        return block
    ranks = {}
    for label, p in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
        index = max(1, math.ceil(p * count))
        ranks[label] = samples[index - 1]
    block["percentiles"] = ranks
    block["min"] = samples[0]
    block["max"] = samples[-1]
    block["mean"] = sum(samples) / count
    return block


def conversion_ns(ticks, numer, denom):
    """Overflow-safe mach tick conversion; None when it cannot be represented.

    The product is computed in unbounded Python integers and is refused when it
    exceeds a 64-bit unsigned value, so a wrapped or truncated figure is never
    returned as a successful conversion.
    """
    if not _is_int(ticks) or not _is_int(numer) or not _is_int(denom):
        return None
    if ticks < 0 or numer <= 0 or denom <= 0:
        return None
    total = ticks * numer
    if total > _TIMEBASE_MAX * denom:
        return None
    return total // denom


def interval_ns(start, end, numer, denom):
    """A primary interval needs a real start and a strictly later end."""
    if not _is_int(start) or not _is_int(end) or not _is_int(numer) or not _is_int(denom):
        return None
    if start <= 0 or end <= start:
        return None
    return conversion_ns(end - start, numer, denom)


def _canonical_call(value, numer, denom):
    if not isinstance(value, dict):
        return "commit_call_not_object"
    if set(value) - _TIMING_COMMIT_CALL_KEYS:
        return "commit_call_unknown_field"
    endpoint = value.get("endpoint")
    if endpoint not in ("insert_text",):
        return "commit_call_endpoint"
    if value.get("validity") is not None and value.get("validity") not in _VALIDITY_VALUES:
        return "commit_call_validity"
    if value.get("unknown_reason") is not None and not isinstance(value.get("unknown_reason"), str):
        return "commit_call_unknown_reason"
    start = value.get("start_ticks")
    end = value.get("end_ticks")
    if start is not None and (not _is_int(start) or start < 0):
        return "commit_call_start_ticks"
    if end is not None and (not _is_int(end) or end <= 0):
        return "commit_call_end_ticks"
    declared_duration = value.get("duration_ns")
    if declared_duration is not None and (
        not _is_int(declared_duration) or declared_duration <= 0
    ):
        return "commit_call_duration_ns"
    call = {
        "endpoint": "insert_text",
        "start_ticks": start,
        "end_ticks": end,
        "duration_ns": declared_duration,
        "validity": "unknown",
        "unknown_reason": None,
        "derived_from": "entry_exit_ticks_over_own_timebase",
    }
    if start is None or end is None:
        call["unknown_reason"] = "commit_call_missing_endpoint_or_duration"
        return call
    if start <= 0 or end <= start:
        call["validity"] = "invalid"
        call["unknown_reason"] = "nonmonotone_commit_call"
        return call
    computed = conversion_ns(end - start, numer, denom)
    if computed is None:
        call["validity"] = "invalid"
        call["unknown_reason"] = "unrepresentable_commit_call"
        return call
    if declared_duration is None:
        call["validity"] = "invalid"
        call["unknown_reason"] = "declared_duration_absent"
        call["computed_ns"] = computed
        return call
    if declared_duration != computed:
        call["validity"] = "invalid"
        call["unknown_reason"] = "declared_duration_mismatch"
        call["computed_ns"] = computed
        return call
    call["validity"] = "valid"
    return call


_TIMING_OBJECT_KEYS = {
    "version",
    "action_id",
    "action",
    "operation",
    "clock",
    "event_queue_wait",
    "nested_actions",
    "continuity_cut",
    "association",
    "update_calls",
    "endpoint",
    "entry_ticks",
    "endpoint_ticks",
    "duration_ns",
    "validity",
    "unknown_reason",
    "commit_call",
}
_TIMING_CLOCK_KEYS = {"domain", "unit", "timebase_numer", "timebase_denom"}
_TIMING_ASSOCIATION_KEYS = {
    "source_instance_id",
    "process_id",
    "continuity_segment_id",
    "update_id",
    "terminal_update_id",
    "commit_id",
}
_TIMING_UPDATE_CALL_KEYS = {"endpoint", "ticks"}
_TIMING_COMMIT_CALL_KEYS = {
    "endpoint",
    "start_ticks",
    "end_ticks",
    "duration_ns",
    "validity",
    "unknown_reason",
}


def canonical_frontend_timing(value):
    """Canonicalize one frontend timing object.

    Returns ``(None, reason_code)`` for a structure that must be refused, or
    ``(timing, None)`` for a canonical self-identifying object. The object is
    parsed with its actual declared schema: an unknown key, a wrong type or an
    out-of-range value is refused, while a well-typed but semantically invalid
    pair is stored and classified with an explicit reason. Numeric validity is
    re-derived from ticks and the object's own timebase; a declared
    ``duration_ns`` is compared rather than trusted.
    """
    if value is None:
        return None, "timing_absent"
    if not isinstance(value, dict):
        return None, "timing_not_object"
    if set(value) - _TIMING_OBJECT_KEYS:
        return None, "timing_unknown_field"
    version = value.get("version")
    if not _is_int(version) or version != FRONTEND_TIMING_VERSION:
        return None, "unsupported_frontend_timing_version"
    action_id = value.get("action_id")
    if not isinstance(action_id, str) or not action_id:
        return None, "timing_action_identity"
    for name in ("action", "operation"):
        if name in value and not isinstance(value[name], str):
            return None, "timing_" + name + "_type"
    clock = value.get("clock")
    if not isinstance(clock, dict):
        return None, "timing_clock"
    if set(clock) - _TIMING_CLOCK_KEYS:
        return None, "timing_clock"
    if clock.get("domain") != "mach_absolute_time":
        return None, "timing_clock_domain"
    if clock.get("unit") != "nanoseconds":
        return None, "timing_clock_unit"
    numer = clock.get("timebase_numer")
    denom = clock.get("timebase_denom")
    if not _is_int(numer) or not _is_int(denom) or numer <= 0 or denom <= 0:
        return None, "timing_timebase"
    entry = value.get("entry_ticks")
    if entry is not None and (not _is_int(entry) or entry <= 0):
        return None, "timing_entry_ticks"
    endpoint = value.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return None, "timing_endpoint_missing"
    if endpoint not in _ENDPOINT_VALUES:
        # The primary endpoint is part of the declared v1 schema; a nonempty
        # endpoint outside its domain cannot be a successful semantic result.
        return None, "unsupported_frontend_endpoint"
    endpoint_ticks = value.get("endpoint_ticks")
    if endpoint_ticks is not None and (
        not _is_int(endpoint_ticks) or endpoint_ticks <= 0
    ):
        return None, "timing_endpoint_ticks"
    declared_duration = value.get("duration_ns")
    if declared_duration is not None and (
        not _is_int(declared_duration) or declared_duration <= 0
    ):
        return None, "timing_duration_ns"
    validity = value.get("validity")
    if validity is not None and validity not in _VALIDITY_VALUES:
        return None, "timing_validity"
    nested = value.get("nested_actions", 0)
    if not _is_int(nested) or nested < 0:
        return None, "timing_nested_actions"
    # An action plus its nested entries is folded into one declared sample
    # frame; a declared count beyond the bounded fold is not a supported
    # observation.
    if nested > _MAX_NESTED_ACTIONS:
        return None, "timing_nested_actions_bound"
    continuity_cut = value.get("continuity_cut")
    if continuity_cut is not None and not isinstance(continuity_cut, bool):
        return None, "timing_continuity_cut"
    event_queue_wait = value.get("event_queue_wait")
    if isinstance(event_queue_wait, (int, float)) and not isinstance(
        event_queue_wait, bool
    ):
        if not math.isfinite(event_queue_wait) or event_queue_wait < 0:
            return None, "timing_event_queue_wait"
    elif event_queue_wait is not None and event_queue_wait != "unknown":
        return None, "timing_event_queue_wait"

    update_calls = value.get("update_calls", [])
    if update_calls is None:
        update_calls = []
    if not isinstance(update_calls, list):
        return None, "timing_update_calls"
    calls = []
    for call in update_calls:
        if not isinstance(call, dict) or set(call) - _TIMING_UPDATE_CALL_KEYS:
            return None, "timing_update_call"
        call_endpoint = call.get("endpoint")
        if call_endpoint not in ("marked_text", "panel_update"):
            return None, "timing_update_call_endpoint"
        ticks = call.get("ticks")
        if not _is_int(ticks) or ticks <= 0:
            return None, "timing_update_call_ticks"
        calls.append({"endpoint": call_endpoint, "ticks": ticks})

    association = value.get("association")
    if association is not None and not isinstance(association, dict):
        return None, "timing_association"
    association_fields = {}
    if isinstance(association, dict):
        if set(association) - _TIMING_ASSOCIATION_KEYS:
            return None, "timing_association"
        for name in ("source_instance_id", "process_id", "continuity_segment_id",
                     "update_id", "terminal_update_id", "commit_id"):
            field = association.get(name)
            if field is not None and (not isinstance(field, str) or not field):
                return None, "timing_association_" + name
            association_fields[name] = field

    timing = {
        "version": FRONTEND_TIMING_VERSION,
        "action_id": action_id,
        "action": value.get("action") if isinstance(value.get("action"), str) else None,
        "operation": value.get("operation") if isinstance(value.get("operation"), str) else None,
        "clock_domain": "mach_absolute_time",
        "clock_unit": "nanoseconds",
        "timebase_numer": numer,
        "timebase_denom": denom,
        "event_queue_wait": "unknown",
        "nested_actions": nested,
        "continuity_cut": bool(continuity_cut) if isinstance(continuity_cut, bool) else False,
        "update_calls": calls,
        "endpoint": endpoint,
        "entry_ticks": entry if isinstance(entry, int) and not isinstance(entry, bool) else None,
        "endpoint_ticks": endpoint_ticks if isinstance(endpoint_ticks, int) and not isinstance(endpoint_ticks, bool) else None,
        "declared_duration_ns": declared_duration if isinstance(declared_duration, int) and not isinstance(declared_duration, bool) else None,
        "validity": "unknown",
        "unknown_reason": None,
        "commit_call": None,
        "association": association_fields,
    }
    reason = None
    # The primary interval is the operation's own last completed marked_text/
    # panel_update call completion. A declared endpoint with no matching
    # completed call, a tick value that is not that call's completion, or a
    # later completed call than the declared one is not a valid primary
    # sample; the sample stays visible as invalid with an explicit reason.
    call_ticks = {call["endpoint"]: call["ticks"] for call in calls}
    primary_mismatch = None
    if endpoint == "unavailable":
        if calls:
            primary_mismatch = "endpoint_unavailable_with_completed_calls"
    elif endpoint == "marked_text":
        if "marked_text" not in call_ticks:
            primary_mismatch = "missing_primary_completion_call"
        elif timing["endpoint_ticks"] != call_ticks["marked_text"]:
            primary_mismatch = "primary_endpoint_not_completed_call"
        elif call_ticks.get("panel_update", 0) >= call_ticks["marked_text"]:
            primary_mismatch = "primary_endpoint_not_last_completed_call"
    elif endpoint == "panel_update":
        if "panel_update" not in call_ticks:
            primary_mismatch = "missing_primary_completion_call"
        elif timing["endpoint_ticks"] != call_ticks["panel_update"]:
            primary_mismatch = "primary_endpoint_not_completed_call"
        elif call_ticks.get("marked_text", 0) > call_ticks["panel_update"]:
            primary_mismatch = "primary_endpoint_not_last_completed_call"
    if primary_mismatch is not None:
        timing["validity"] = "invalid"
        reason = primary_mismatch
    elif endpoint == "unavailable":
        timing["validity"] = "unknown"
        reason = "no_update_call"
    elif not timing["entry_ticks"]:
        timing["validity"] = "invalid"
        reason = "missing_entry"
    elif not timing["endpoint_ticks"]:
        timing["validity"] = "invalid"
        reason = "missing_endpoint"
    elif timing["endpoint_ticks"] <= timing["entry_ticks"]:
        timing["validity"] = "invalid"
        reason = "nonmonotone_endpoint"
    else:
        computed = conversion_ns(
            timing["endpoint_ticks"] - timing["entry_ticks"], numer, denom
        )
        if computed is None:
            timing["validity"] = "invalid"
            reason = "unrepresentable_endpoint"
        elif timing["declared_duration_ns"] is None:
            timing["validity"] = "invalid"
            reason = "declared_duration_absent"
            timing["computed_duration_ns"] = computed
        elif timing["declared_duration_ns"] != computed:
            timing["validity"] = "invalid"
            reason = "declared_duration_mismatch"
            timing["computed_duration_ns"] = computed
        else:
            timing["validity"] = "valid"
            timing["computed_duration_ns"] = computed
    declared_reason = value.get("unknown_reason")
    declared_reason = declared_reason if isinstance(declared_reason, str) else None
    if timing["validity"] == "valid":
        timing["unknown_reason"] = None
    else:
        timing["unknown_reason"] = reason or declared_reason or "declared_unknown"
    if "commit_call" in value and value.get("commit_call") is not None:
        call = value.get("commit_call")
        canonical_call = _canonical_call(call, numer, denom)
        if isinstance(canonical_call, str):
            return None, canonical_call
        timing["commit_call"] = canonical_call
    return timing, None


def canonicalize_timing_payload(payload):
    """Canonicalize the ``frontend_timing`` object inside a payload.

    Returns ``(timing, None)`` when the payload carries a canonical timing
    object, ``(None, None)`` when it declares none, or ``(None, reason)`` for a
    structure that must be refused at admission.
    """
    if not isinstance(payload, dict) or "frontend_timing" not in payload:
        return None, None
    timing, reason = canonical_frontend_timing(payload.get("frontend_timing"))
    if timing is None:
        return None, reason or "timing_not_object"
    return timing, None


def encode_cursor(view, filters, as_of_durable_seq, epoch, query_version=QUERY_VERSION):
    payload = {
        "v": query_version,
        "view": view,
        "filters": _filter_fingerprint(filters),
        "as_of": as_of_durable_seq,
        "epoch": epoch,
    }
    data = canonical_bytes(payload)
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_cursor(token):
    """Return the cursor payload dict, or a stable error code."""
    if not isinstance(token, str) or not token.startswith(_CURSOR_PREFIX):
        return "invalid_request"
    body = token[len(_CURSOR_PREFIX):]
    padding = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + padding)
    except (binascii.Error, ValueError):
        return "invalid_request"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return "invalid_request"
    if not isinstance(payload, dict):
        return "invalid_request"
    if payload.get("v") not in _SUPPORTED_QUERY_VERSIONS:
        return "unsupported_query_version"
    if not isinstance(payload.get("view"), str):
        return "invalid_request"
    if not isinstance(payload.get("filters"), str):
        return "invalid_request"
    if not _is_int(payload.get("as_of")) or payload["as_of"] < 0:
        return "invalid_request"
    if not isinstance(payload.get("epoch"), str) or not payload["epoch"]:
        return "invalid_request"
    return payload


def _filter_fingerprint(filters):
    return hashlib.sha256(canonical_bytes(_canonical_filters(filters))).hexdigest()


def _canonical_filters(filters):
    if not isinstance(filters, dict):
        return {}
    return {str(key): value for key, value in sorted(filters.items()) if value is not None}


def filter_fingerprint(filters):
    return _filter_fingerprint(filters)


# ---------------------------------------------------------------------------
# Identity relation resolution


class RelationContext(object):
    """Reverse indexes over the durable rows at one published prefix.

    Rows are the already-published index rows; unpublished work never reaches
    this object. When the collector supplies its incremental join state, the
    maps are copied rather than rebuilt from the row list, so a query reads a
    bounded index instead of re-deriving the joins over the whole history.
    """

    def __init__(self, rows, join_state=None, owner_evidence_max=None):
        self.rows = list(rows)
        self.by_seq = {row.get("durable_seq"): row for row in self.rows}
        self.owner_evidence_max = owner_evidence_max
        if join_state is not None:
            self.updates = dict(join_state["updates"])
            self.update_witnesses = dict(join_state["update_witnesses"])
            self.update_owners = {
                key: set(value) for key, value in join_state["update_owners"].items()
            }
            self.process_sources = {
                key: set(value) for key, value in join_state["process_sources"].items()
            }
            self.commit_owners = {
                key: set(value) for key, value in join_state["commit_owners"].items()
            }
            self.segment_owners = {
                key: set(value) for key, value in join_state["segment_owners"].items()
            }
            self.request_rows = {
                key: list(value) for key, value in join_state["request_rows"].items()
            }
            self.plan_owners = {
                key: set(value) for key, value in join_state["plan_owners"].items()
            }
            self.request_plans = {
                key: set(value) for key, value in join_state["request_plans"].items()
            }
            return
        self.updates = {}
        self.update_witnesses = {}
        self.update_owners = {}
        self.process_sources = {}
        self.commit_owners = {}
        self.segment_owners = {}
        self.request_rows = {}
        self.plan_owners = {}
        self.request_plans = {}
        for row in self.rows:
            seq = row.get("durable_seq")
            # Identity relations are declared by the capture rows themselves:
            # plugin and daemon rows are observers that reference a frontend
            # token, so they never create a second owner for it.
            observer = row.get("observation_kind") in ("plugin_observation", "daemon_observation")
            if not observer:
                update = row.get("update_id")
                if isinstance(update, str):
                    self.updates[update] = min(self.updates.get(update, seq), seq)
                    owner = (row.get("source_instance_id"), row.get("process_id"))
                    self.update_witnesses.setdefault((update, owner), seq)
                    self.update_owners.setdefault(update, set()).add(
                        (row.get("source_instance_id"), row.get("process_id"))
                    )
                process = row.get("process_id")
                if isinstance(process, str):
                    self.process_sources.setdefault(process, set()).add(
                        row.get("source_instance_id")
                    )
                commit = row.get("commit_id")
                if isinstance(commit, str):
                    self.commit_owners.setdefault(commit, set()).add(
                        (row.get("source_instance_id"), row.get("process_id"))
                    )
                segment = row.get("continuity_segment_id")
                if isinstance(segment, str):
                    self.segment_owners.setdefault(segment, set()).add(
                        (row.get("source_instance_id"), row.get("process_id"))
                    )
            daemon = row.get("daemon")
            if isinstance(daemon, dict) and daemon.get("daemon_stage") == "request":
                request_id = daemon.get("request_id")
                if isinstance(request_id, str):
                    self.request_rows.setdefault(request_id, []).append(seq)
                    plan = daemon.get("plan_identity")
                    if isinstance(plan, str):
                        self.plan_owners.setdefault(plan, set()).add(request_id)
                        self.request_plans.setdefault(request_id, set()).add(plan)

    def relation(self, name, status, basis, evidence=None):
        block = {"relation": name, "status": status, "basis": basis}
        if evidence is not None:
            block["evidence"] = evidence
        return block

    def owners_evidence(self, owners):
        """Render an owner list under the configured high-fanout bound.

        Owners may be (source, process) pairs (token relations) or plain source
        identifiers (process ownership); both render as content-free labels. A
        reused token under very many owners keeps its total count and an
        explicit truncation reason instead of an unbounded list.
        """
        rendered = []
        for owner in owners:
            if isinstance(owner, tuple) and len(owner) == 2:
                source, process = owner
                rendered.append(
                    "%s/%s" % (source or "unknown", process or "unknown")
                )
            else:
                rendered.append(str(owner) if owner else "unknown")
        rendered.sort()
        limit = self.owner_evidence_max
        if limit is not None and len(rendered) > limit:
            return {
                "owners": rendered[:limit],
                "owners_total": len(rendered),
                "owners_truncated": True,
                "owners_truncation_reason": "query_high_fanout_updates_max",
            }
        return {
            "owners": rendered,
            "owners_total": len(rendered),
            "owners_truncated": False,
        }

    def update_relation(self, row, field, value):
        if value is None:
            return self.relation(field, "absent", "no_declared_" + field)
        if field == "parent_update_id":
            return self.update_relation_for(row, field, value)
        if value in self.updates:
            return self.relation(
                field, "valid", "exact_token_match_durable_record", self.updates[value]
            )
        return self.relation(field, "unmatched", "no_durable_record_with_this_token")

    def update_relation_for(self, row, field, value):
        """Parent resolve status at this prefix, spelled exactly as the public
        summary uses it: present, missing, absent, or unknown."""
        if value is None:
            return self.relation(field, "absent", "no_parent_declared")
        if value in self.updates:
            return self.relation(
                field, "valid", "exact_token_match_durable_record", self.updates[value]
            )
        return self.relation(
            field, "unmatched", "no_durable_record_with_this_token_at_prefix"
        )

    def token_relation(self, name, value, owners=None):
        if value is None:
            return self.relation(name, "absent", "no_declared_" + name)
        if owners is None:
            owners = {(None, None)}
        if len(owners) > 1:
            return self.relation(
                name,
                "conflicting",
                "multiple_recorded_owners_for_this_token",
                self.owners_evidence(owners),
            )
        if (None, None) in owners:
            return self.relation(name, "unmatched", "no_durable_record_with_this_token")
        return self.relation(name, "valid", "exact_token_match_durable_record")

    def process_relation(self, row, value):
        if value is None:
            return self.relation("process_identity", "absent", "no_process_declared")
        owners = {owner for owner in self.process_sources.get(value, set()) if owner}
        if not owners:
            return self.relation(
                "process_identity", "not_observed", "no_durable_process_record"
            )
        observer = row.get("observation_kind") in ("plugin_observation", "daemon_observation")
        if len(owners) == 1:
            owner = next(iter(owners))
            if observer or row.get("source_instance_id") == owner:
                return self.relation(
                    "process_identity", "valid", "exact_source_and_process_match"
                )
            return self.relation(
                "process_identity", "unmatched", "process_owner_is_a_different_source"
            )
        block = self.relation(
            "process_identity",
            "conflicting",
            "process_token_recorded_under_multiple_source_incarnations",
            self.owners_evidence(owners),
        )
        return block

    def association(self, row, plugin):
        """The plugin's declared engine-entry context against durable records.

        ``engine_entry_context`` is a snapshot of the frontend entry context,
        not proof of the current operation's resulting frontend update.
        """
        evidence = {
            "declared_role": plugin.get("association_role"),
            "association_read": plugin.get("association_read"),
            "proves_current_frontend_result": False,
            "frontend_terminal": "unknown",
        }
        role = plugin.get("association_role")
        read = plugin.get("association_read")
        if role in (None, "absent"):
            return self.relation("association", "absent", "no_association_declared", evidence)
        if role == "invalid" or read == "invalid":
            return self.relation("association", "invalid", "association_marked_invalid", evidence)
        if read == "malformed":
            return self.relation("association", "malformed", "association_read_malformed", evidence)
        if role == "unknown" or read == "unknown":
            return self.relation("association", "unknown", "association_not_read", evidence)
        reference = {
            "source_instance_id": plugin.get("referenced_source_id"),
            "process_id": plugin.get("referenced_process_id"),
            "update_id": plugin.get("referenced_update_id"),
        }
        evidence["reference"] = reference
        if all(reference.get(name) is None for name in reference):
            return self.relation("association", "absent", "no_reference_tokens", evidence)
        if set(reference) - {"source_instance_id", "process_id", "update_id"}:
            return self.relation("association", "malformed", "unknown_reference_field", evidence)
        for name, value in reference.items():
            if value is not None and not isinstance(value, str):
                return self.relation(
                    "association", "malformed", "reference_token_not_text", evidence
                )
        update = reference.get("update_id")
        if update is None:
            # A valid reference is asserted only by the exact owned update
            # token; a partial reference stays unresolved rather than guessed.
            return self.relation(
                "association",
                "unmatched",
                "no_owned_update_token_to_resolve",
                evidence,
            )
        declared_source = reference.get("source_instance_id")
        declared_process = reference.get("process_id")
        # A full recorded owner disambiguates token reuse. The first witness
        # of the unscoped token is not evidence against a later exact owner.
        witness = self.update_witnesses.get(
            (update, (declared_source, declared_process))
        )
        if witness is None:
            witness = self.updates.get(update)
        if witness is None:
            return self.relation(
                "association",
                "unmatched",
                "no_durable_record_with_referenced_update_token",
                evidence,
            )
        witness_row = self.by_seq.get(witness)
        witness_source = witness_row.get("source_instance_id") if witness_row else None
        witness_process = witness_row.get("process_id") if witness_row else None
        evidence["witness_durable_seq"] = witness
        if declared_source is not None and declared_source != witness_source:
            return self.relation(
                "association",
                "stale",
                "referenced_update_belongs_to_a_different_source",
                evidence,
            )
        if declared_process is not None and declared_process != witness_process:
            return self.relation(
                "association",
                "stale",
                "referenced_update_belongs_to_a_different_process",
                evidence,
            )
        if declared_source is None or declared_process is None:
            return self.relation(
                "association",
                "unknown_owner",
                "reference_omits_source_or_process_token",
                evidence,
            )
        return self.relation(
            "association",
            "valid",
            "exact_source_process_update_match",
            evidence,
        )

    def request_link(self, row, plugin):
        """Association of an issued plugin exchange with daemon records.

        The native request id is the only join key; a plan digest alone, a
        timestamp, text equality, a pid or arrival order never resolves it.
        """
        state = plugin.get("lm_request_state")
        request_id = plugin.get("lm_request_id")
        plan_identity = plugin.get("plan_identity")
        evidence = {
            "lm_request_state": state,
            "request_id_basis": "native_scorer_request_id_from_attempted_exchange",
            "proves_scoring_benefit": False,
            "application_proof": False,
        }
        if plan_identity is None:
            plan_relation = self.relation("plan_identity", "absent", "no_plan_declared", evidence)
        elif len(self.plan_owners.get(plan_identity, set())) > 1:
            plan_relation = self.relation(
                "plan_identity",
                "conflicting",
                "plan_digest_claimed_by_multiple_requests",
                sorted(self.plan_owners[plan_identity]),
            )
        elif plan_identity in self.plan_owners:
            plan_relation = self.relation(
                "plan_identity", "valid", "exact_digest_match_with_daemon_request"
            )
        else:
            plan_relation = self.relation(
                "plan_identity", "unmatched", "no_daemon_request_with_this_digest"
            )
        if state == "no_request":
            if request_id:
                request_relation = self.relation(
                    "request", "invalid", "request_id_present_without_a_request"
                )
            else:
                request_relation = self.relation(
                    "request", "not_issued", "no_lm_request_was_issued"
                )
            return request_relation, plan_relation, evidence
        request_relation = self.relation(
            "request_identity", "unknown", "issued_request_without_a_request_token"
        )
        if not isinstance(request_id, str) or not request_id:
            return request_relation, plan_relation, evidence
        records = self.request_rows.get(request_id, [])
        if not records:
            request_relation = self.relation(
                "request",
                "unmatched",
                "no_durable_daemon_request_with_this_token",
            )
            return request_relation, plan_relation, evidence
        plans = self.request_plans.get(request_id, set())
        evidence["daemon_request_rows"] = len(records)
        if len(plans) > 1:
            request_relation = self.relation(
                "request",
                "conflicting",
                "daemon_requests_with_this_token_disagree_on_plan_identity",
                sorted(plans),
            )
            return request_relation, plan_relation, evidence
        if plan_identity is not None and plans and plan_identity not in plans:
            request_relation = self.relation(
                "request",
                "conflicting",
                "plugin_plan_identity_differs_from_daemon_request_plan",
            )
            return request_relation, plan_relation, evidence
        if len(records) > 1:
            request_relation = self.relation(
                "request",
                "ambiguous",
                "multiple_daemon_requests_with_this_token",
                list(records),
            )
            return request_relation, plan_relation, evidence
        request_relation = self.relation(
            "request",
            "linked",
            "native_request_id_matches_one_durable_daemon_request",
            records[0],
        )
        return request_relation, plan_relation, evidence

    def row_relations(self, row):
        relations = {}
        update = row.get("update_id")
        if isinstance(update, str):
            relations["update_identity"] = self.token_relation(
                "update_identity", update, self.update_owners.get(update)
            )
        else:
            relations["update_identity"] = self.relation(
                "update_identity", "absent", "no_update_declared"
            )
        relations["process_identity"] = self.process_relation(row, row.get("process_id"))
        relations["parent_reference"] = self.update_relation(
            row, "parent_update_id", row.get("parent_update_id")
        )
        commit = row.get("commit_id")
        relations["commit_identity"] = self.token_relation(
            "commit_identity", commit, self.commit_owners.get(commit) if isinstance(commit, str) else None
        )
        segment = row.get("continuity_segment_id")
        relations["segment_identity"] = self.token_relation(
            "segment_identity",
            segment,
            self.segment_owners.get(segment) if isinstance(segment, str) else None,
        )
        plugin = row.get("plugin")
        daemon = row.get("daemon")
        if isinstance(plugin, dict):
            relations["association"] = self.association(row, plugin)
            request, plan, _evidence = self.request_link(row, plugin)
            relations["request_identity"] = request
            relations["plan_identity"] = plan
        elif isinstance(daemon, dict) and daemon.get("daemon_stage") == "request":
            request_id = daemon.get("request_id")
            plan = daemon.get("plan_identity")
            if isinstance(request_id, str):
                plans = self.request_plans.get(request_id, set())
                if len(plans) > 1:
                    relations["request_identity"] = self.relation(
                        "request_identity",
                        "conflicting",
                        "daemon_requests_with_this_token_disagree_on_plan_identity",
                        sorted(plans),
                    )
                else:
                    relations["request_identity"] = self.relation(
                        "request_identity", "valid", "durable_daemon_request"
                    )
            else:
                relations["request_identity"] = self.relation(
                    "request_identity", "absent", "daemon_request_without_a_request_token"
                )
            if plan is None:
                relations["plan_identity"] = self.relation(
                    "plan_identity", "absent", "no_plan_declared"
                )
            elif len(self.plan_owners.get(plan, set())) > 1:
                relations["plan_identity"] = self.relation(
                    "plan_identity",
                    "conflicting",
                    "plan_digest_claimed_by_multiple_requests",
                    sorted(self.plan_owners[plan]),
                )
            else:
                relations["plan_identity"] = self.relation(
                    "plan_identity", "valid", "durable_daemon_request_plan"
                )
        return relations


def relation_summary(relations):
    counts = {}
    for block in relations.values():
        status = block.get("status")
        counts[status] = counts.get(status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Denominators and aggregate views

def identity_key(row):
    """The capture identity of one observation: source instance plus the
    source-local sequence. A retry of the same capture carries the same key;
    the collector's admission result decides admitted/duplicate/conflict."""
    return (row.get("source_instance_id"), row.get("source_local_sequence"))


def eligible_population(rows):
    """Deduplicated eligible observation population.

    One logical observation per capture identity; a same-identity retry that
    was admitted or recognized as an exact duplicate is not a second
    observation. Every other unit stays in its own honest bucket and no
    unknown is discarded to make a rate look better.
    """
    seen = {}
    duplicates = 0
    conflicting = 0
    for row in rows:
        key = identity_key(row)
        if key in seen:
            duplicates += 1
            continue
        seen[key] = row
    return {
        "unit": "source_instance_observation",
        "identity": "source_instance_id_and_source_local_sequence",
        "observations": len(seen),
        "same_identity_retries_or_duplicates_collapsed": duplicates,
        "identity_conflicting_units": conflicting,
    }


def stage_denominators(rows):
    """Counted stage outcomes with explicit numerators and denominators.

    Successful daemon scoring alone proves no plugin application, no frontend
    presentation, no host persistence and no ranking benefit. Applied+unchanged
    is an applied plan, never a benefit. Unknown sources stay in the eligible
    population instead of disappearing from it.
    """
    totals = {
        "computed_scoring_outcomes": 0,
        "computed_scoring_ok": 0,
        "computed_scoring_failed": 0,
        "plugin_issuances": 0,
        "plugin_issued_succeeded": 0,
        "plugin_issued_failed": 0,
        "plugin_applied": 0,
        "plugin_applied_changed": 0,
        "plugin_applied_unchanged": 0,
        "plugin_fallback": 0,
        "plugin_no_request": 0,
        "frontend_timing_actions": 0,
        "frontend_timing_valid": 0,
        "frontend_timing_invalid": 0,
        "frontend_timing_unknown": 0,
        "frontend_timing_unavailable": 0,
        "commit_attempts": 0,
        "commit_attempts_unavailable_client": 0,
        "commit_host_persistence_known": 0,
    }
    units = []
    for row in rows:
        kind = row.get("observation_kind")
        daemon = row.get("daemon")
        plugin = row.get("plugin")
        if isinstance(daemon, dict) and daemon.get("daemon_stage") == "scoring":
            totals["computed_scoring_outcomes"] += 1
            if daemon.get("outcome_code") == "ok":
                totals["computed_scoring_ok"] += 1
            else:
                totals["computed_scoring_failed"] += 1
        if isinstance(plugin, dict):
            state = plugin.get("lm_request_state")
            if state in ("issued_succeeded", "issued_failed"):
                totals["plugin_issuances"] += 1
                totals["plugin_issued_%s" % state.split("_", 1)[1]] += 1
            elif state == "no_request":
                totals["plugin_no_request"] += 1
            apply_state = plugin.get("apply_state")
            if apply_state == "applied":
                totals["plugin_applied"] += 1
                if plugin.get("emission_matches_upstream") is False:
                    totals["plugin_applied_changed"] += 1
                else:
                    totals["plugin_applied_unchanged"] += 1
            elif apply_state == "fallback":
                totals["plugin_fallback"] += 1
        if kind == "provenance" and row.get("stage") == "frontend_timing":
            # Every declared timing action keeps its own bucket: a valid
            # numerator agrees with the timing view's canonical valid samples
            # for the same scope, and invalid/unknown/unavailable samples stay
            # visible instead of disappearing or counting as valid.
            totals["frontend_timing_actions"] += 1
            timing = row.get("frontend_timing")
            validity = timing.get("validity") if isinstance(timing, dict) else None
            if validity == "valid":
                totals["frontend_timing_valid"] += 1
            elif validity == "invalid":
                totals["frontend_timing_invalid"] += 1
            elif validity == "unknown":
                totals["frontend_timing_unknown"] += 1
            else:
                totals["frontend_timing_unavailable"] += 1
        if kind == "commit_attempt":
            totals["commit_attempts"] += 1
            if (row.get("outcome") or "unknown") == "unavailable_client":
                totals["commit_attempts_unavailable_client"] += 1
            if row.get("host_persistence") == "persisted":
                totals["commit_host_persistence_known"] += 1
        if isinstance(plugin, dict):
            units.append(
                {
                    "durable_seq": row.get("durable_seq"),
                    "source_instance_id": row.get("source_instance_id"),
                    "lm_request_state": plugin.get("lm_request_state"),
                    "apply_state": plugin.get("apply_state"),
                    "submission": plugin.get("submission"),
                    "coverage": plugin.get("coverage"),
                    "evidence_permitted": bool(
                        plugin.get("coverage") == "complete"
                        and isinstance(plugin.get("captured_candidate_count"), int)
                        and plugin.get("captured_candidate_count")
                        == plugin.get("group_member_count")
                    ),
                }
            )
    return {
        "totals": totals,
        "plugin_units": units,
        "unknowns_retained": True,
        "denominator_notes": (
            "unknown sources are not discarded to improve any rate;"
            " applied_unchanged is an applied plan, not ranking benefit;"
            " scoring success alone proves no application or persistence"
        ),
    }


def outcome_denominators(rows):
    """Per-kind outcome counts with the exact denominator each one uses."""
    kinds = {}
    for row in rows:
        kind = row.get("observation_kind") or "unknown"
        bucket = kinds.setdefault(
            kind,
            {
                "unit": "source_instance_observation",
                "observation_kind": kind,
                "observations": 0,
                "outcomes": {},
                "eligibility": {},
            },
        )
        bucket["observations"] += 1
        outcome = row.get("outcome") or "unknown"
        bucket["outcomes"][outcome] = bucket["outcomes"].get(outcome, 0) + 1
        eligibility = "excluded" if kind == "exclusion_notice" else "included"
        bucket["eligibility"][eligibility] = bucket["eligibility"].get(eligibility, 0) + 1
    return {
        "kinds": [kinds[name] for name in sorted(kinds)],
        "unit": "source_instance_observation",
        "retry_handling": "same_identity_retries_collapsed_in_identity_population_only",
    }


def quality_denominators(rows, state):
    """Known loss, refusal, policy and capacity state, each in its own bucket.

    Collector post-admission displacement yields a known-dropped unit and a
    continuity break; it is not necessarily a loss-notice row and does not
    claim an exact cause for every missing reference.
    """
    return {
        "known_dropped_units": state.get("known_dropped_units", 0),
        "known_dropped_units_basis": "collector_counter",
        "admission_refused_units": state.get("admission_refused_units", 0),
        "storage_failed_units": state.get("storage_failed_units", 0),
        "capacity_refused_units": state.get("capacity_refused_units", 0),
        "identity_conflicts": state.get("identity_conflicts", 0),
        "loss_notice_observations": sum(
            1 for row in rows if row.get("observation_kind") == "loss_notice"
        ),
        "exclusion_notice_observations": sum(
            1 for row in rows if row.get("observation_kind") == "exclusion_notice"
        ),
        "loss_notice_relation": (
            "a continuity break or known_dropped_units does not by itself prove"
            " a loss-notice row; the two are counted separately"
        ),
        "continuity_broken": bool(state.get("continuity_break_reasons")),
        "continuity_break_reasons": list(state.get("continuity_break_reasons") or []),
        "policy": {
            "desired": state.get("desired_policy"),
            "desired_revision": state.get("desired_revision"),
            "collector_effective": state.get("collector_effective"),
            "globally_effective": state.get("globally_effective"),
            "scope": "collector_durable_desired_policy",
        },
        "capacity": {
            "capacity_stop": bool(state.get("capacity_stop")),
            "storage_failure": bool(state.get("storage_failure")),
            "capacity_bytes": state.get("capacity_bytes"),
        },
        "crash_tail": state.get("crash_tail", "unknown"),
        "crash_tail_basis": "last_restart_reconciliation",
        "unclean_shutdown_observed": bool(state.get("unclean_shutdown_observed")),
        "discarded_unpublished_bytes": state.get("discarded_unpublished_bytes", 0),
        "discarded_quarantine_bytes": state.get("discarded_quarantine_bytes", 0),
    }


def storage_denominators(state, index_rows):
    """Managed archive bytes and derived index bytes are separate figures."""
    durable_bytes = state.get("durable_bytes", 0)
    quarantine_bytes = state.get("quarantine_bytes", 0)
    capacity_bytes = state.get("capacity_bytes", 0)
    return {
        "managed": {
            "durable_bytes": durable_bytes,
            "quarantine_bytes": quarantine_bytes,
            "total_bytes": durable_bytes + quarantine_bytes,
            "capacity_bytes": capacity_bytes,
            "used_ratio": (
                (durable_bytes + quarantine_bytes) / capacity_bytes
                if capacity_bytes
                else None
            ),
            "basis": "exact_published_jsonl_plus_quarantine_bytes",
        },
        "derived": {
            "index_rows": len(index_rows),
            "index_bytes_estimate": len(index_rows) * _INDEX_ROW_ESTIMATE_BYTES,
            "basis": "declared_in_memory_offset_index_width_times_rows",
            "note": "derived diagnostic state, never counted as managed archive bytes",
        },
        "growth": None,
        "growth_unavailable_reason": "fewer_than_two_comparable_samples",
        "retention": "not_managed_here",
    }


def storage_growth(first, second, elapsed_ms):
    """Growth only from two declared, comparable managed-byte samples."""
    if first is None or second is None:
        return None
    if elapsed_ms is None or elapsed_ms <= 0:
        return None
    delta = second - first
    return {
        "first_bytes": first,
        "second_bytes": second,
        "delta_bytes": delta,
        "elapsed_ms": elapsed_ms,
        "bytes_per_second": delta / (elapsed_ms / 1000.0),
        "basis": "two_declared_comparable_samples",
    }


def producer_freshness(state, index_rows, now_wall_ms, freshness_window_ms):
    """Producer and publication freshness, without any daemon probe."""
    producers = []
    for producer in state.get("producer_observations") or []:
        producers.append(dict(producer))
    last_observation = index_rows[-1] if index_rows else None
    publication_age_ms = None
    publication_age_basis = "no_durable_observation_at_prefix"
    if last_observation is not None:
        observed = (last_observation.get("clocks") or {}).get("observation_time")
        if (isinstance(observed, (int, float)) and not isinstance(observed, bool)
                and not (isinstance(observed, float) and not math.isfinite(observed))):
            publication_age_ms = max(0, int(now_wall_ms - observed))
            publication_age_basis = "client_supplied_observation_time"
        elif isinstance(observed, float) and not math.isfinite(observed):
            publication_age_basis = "durable_observation_has_nonfinite_client_observation_time"
        else:
            publication_age_basis = "durable_observation_has_no_client_observation_time"
    pending = state.get("received_unpublished", 0)
    publication = "idle"
    if pending:
        publication = "pending_admission"
    return {
        "producers": producers,
        "desired_revision": state.get("desired_revision"),
        "published_durable_seq": state.get("durable_seq"),
        "received_unpublished": pending,
        "publication_state": publication,
        "last_observation_age_ms": publication_age_ms,
        "publication_age_basis": publication_age_basis,
        "last_observation_freshness": (
            None
            if publication_age_ms is None
            else ("fresh" if publication_age_ms <= freshness_window_ms else "stale")
        ),
        "freshness_window_ms": freshness_window_ms,
        "basis": "producer_poll_and_published_prefix",
        "live_probe": False,
    }


def overview_body(rows, state, limits, timing, now_wall_ms):
    """Honest overview counts. Every figure names its unit and denominator."""
    population = eligible_population(rows)
    stages = stage_denominators(rows)
    inclusion = {
        "included": sum(
            1 for row in rows if row.get("observation_kind") != "exclusion_notice"
        ),
        "excluded": sum(
            1 for row in rows if row.get("observation_kind") == "exclusion_notice"
        ),
        "unit": "source_instance_observation",
    }
    return {
        "view": "overview",
        "query_version": QUERY_VERSION,
        "ordering": "durable_seq_ascending",
        "as_of_durable_seq": state.get("durable_seq"),
        "collector_epoch": state.get("collector_epoch"),
        "population": population,
        "inclusion": inclusion,
        "stages": stages,
        "timing": timing,
        "slices": {
            "status": "not_observed",
            "available": [],
            "unknown_buckets": [
                "cold",
                "hot",
                "idle_resumption",
                "application",
                "input_size",
            ],
            "basis": "no_explicit_slice_evidence_in_this_archive",
            "note": (
                "no slice is inferred from timing, PID, text or arrival order;"
                " missing slice metadata stays an explicit unknown bucket"
            ),
        },
        "outcomes": outcome_denominators(rows),
        "quality": quality_denominators(rows, state),
        "storage": storage_denominators(state, rows),
        "freshness": producer_freshness(
            state, rows, now_wall_ms, limits["freshness_window_ms"]
        ),
        "host_persistence_proof": False,
        "application_proof": False,
        "ranking_benefit": False,
        "inference_availability": "not_observed",
        "inference_dependency": False,
        "live_probe": False,
        "five_view_complete": False,
        "content_included": False,
    }


# ---------------------------------------------------------------------------
# Frontend timing projection


class TimingSummary(object):
    """Operation-separated frontend timing distributions.

    The primary figure is the real controller action entry to the last
    ``marked_text``/``panel_update`` call completion, in the frontend's own
    mach_absolute_time nanoseconds. A valid standalone frontend interval is
    kept even when backend phases or optional association rows are absent;
    association quality is disclosed separately. Missing, unsupported,
    malformed, unknown and invalid data keep explicit reasons and are never a
    zero latency. Old flat timing, #189 measurement scopes and backend times
    are never mixed into this total.
    """

    def __init__(self, limits):
        self.limits = limits
        self.rows = []
        self.by_operation = {}
        self.unavailable = {}
        self.lane_conflicts = 0

    def add(self, row, timing, reason):
        if timing is None:
            if reason:
                self.unavailable[reason] = self.unavailable.get(reason, 0) + 1
            return
        entry = {
            "durable_seq": row.get("durable_seq"),
            "observation_kind": row.get("observation_kind"),
            "stage": row.get("stage"),
            "source_instance_id": row.get("source_instance_id"),
            "process_id": row.get("process_id"),
            "update_id": row.get("update_id"),
            "operation": timing.get("operation") or "unknown",
            "validity": timing.get("validity"),
            "duration_ns": (
                timing.get("declared_duration_ns")
                if timing.get("validity") == "valid"
                else None
            ),
            "declared_duration_ns": timing.get("declared_duration_ns"),
            "computed_duration_ns": timing.get("computed_duration_ns"),
            "endpoint": timing.get("endpoint"),
            "unknown_reason": timing.get("unknown_reason"),
            "clock_domain": timing.get("clock_domain"),
            "commit_call_validity": (
                timing.get("commit_call") or {}
            ).get("validity") if timing.get("commit_call") else None,
            "commit_call_duration_ns": (
                timing.get("commit_call") or {}
            ).get("duration_ns") if timing.get("commit_call") else None,
        }
        operation = entry["operation"]
        bucket = self.by_operation.setdefault(
            operation,
            {
                "operation": operation,
                "unit": "frontend_action_interval_nanoseconds",
                "primary_definition": (
                    "controller_action_entry_to_last_marked_text_or_panel_update_call"
                    "_completion"
                ),
                "valid_samples": 0,
                "invalid_samples": 0,
                "unknown_samples": 0,
                "valid_values_ns": [],
            },
        )
        validity = timing.get("validity")
        if validity == "valid" and isinstance(entry["duration_ns"], int):
            bucket["valid_samples"] += 1
            bucket["valid_values_ns"].append(entry["duration_ns"])
        elif validity == "invalid":
            bucket["invalid_samples"] += 1
        else:
            bucket["unknown_samples"] += 1
        if len(self.rows) < self.limits["query_timing_rows_max"]:
            self.rows.append(entry)
        else:
            self.rows.append(None)
            self.lane_conflicts += 1

    def body(self, state):
        operations = []
        for name in sorted(self.by_operation):
            bucket = self.by_operation[name]
            values = bucket.pop("valid_values_ns")
            summary = percentiles(values)
            bucket["distributions"] = {
                "valid": summary,
                "invalid": {
                    "count": bucket["invalid_samples"],
                    "reason": "explicit_reasons_per_sample",
                },
                "unknown": {
                    "count": bucket["unknown_samples"],
                    "reason": "explicit_reasons_per_sample",
                },
                "reasons": self.unavailable,
                "method_basis": "frontend_numeric_v1_only",
            }
            bucket["zero_latency_substitution"] = False
            bucket["sla_claim"] = False
            bucket["statistical_adequacy_claim"] = False
            operations.append(bucket)
        return {
            "view": "timing",
            "query_version": QUERY_VERSION,
            "frontend_timing_version": FRONTEND_TIMING_VERSION,
            "as_of_durable_seq": state.get("durable_seq"),
            "collector_epoch": state.get("collector_epoch"),
            "operations": operations,
            "rows": [row for row in self.rows if row is not None],
            "rows_truncated": self.lane_conflicts > 0,
            "rows_limit": self.limits["query_timing_rows_max"],
            "unavailable": self.unavailable,
            "unavailable_total": sum(self.unavailable.values()),
            "never_mixes": [
                "old_flat_timing",
                "measurement_scope_189",
                "backend_daemon_times",
            ],
            "association_quality_disclosure": (
                "a valid frontend interval is retained when backend phases or"
                " association rows are absent; association quality is reported"
                " separately on each row"
            ),
            "content_included": False,
        }


def collect_timing(rows, limits):
    """Build the timing summary from durable rows.

    Rows carry the canonical ``frontend_timing`` field parsed at admission, so
    no query re-reads payloads for timing and a row that declares the timing
    stage without a usable payload keeps an explicit reason.
    """
    summary = TimingSummary(limits)
    for row in rows:
        if row.get("observation_kind") != "provenance":
            continue
        if row.get("stage") != "frontend_timing":
            continue
        timing = row.get("frontend_timing")
        if timing is None:
            summary.add(row, None, "timing_payload_absent")
            continue
        summary.add(row, timing, None)
    return summary


# ---------------------------------------------------------------------------
# Group-level choice projection


def _coverage_accepted(plugin):
    if plugin.get("coverage") != "complete":
        return False
    if plugin.get("coverage_basis") != CHOICE_COMPLETE_BASIS:
        return False
    if plugin.get("truncated") is True:
        return False
    captured = plugin.get("captured_candidate_count")
    members = plugin.get("group_member_count")
    if not _is_int(captured) or not _is_int(members) or captured < 1:
        return False
    return captured == members


def _choice_entry(row, window_id, group_id, missing):
    if not missing:
        identity = {"status": "scoped", "basis": CHOICE_IDENTITY_BASIS, "missing": []}
        scope = "captured_rerank_group_span_and_category"
    else:
        identity = {
            "status": "missing" if window_id is None and group_id is None else "partial",
            "basis": None,
            "missing": missing,
        }
        scope = "single_observation_without_scoped_group_identity"
    return {
        "source_instance_id": row.get("source_instance_id"),
        "process_id": row.get("process_id"),
        "window_id": window_id,
        "group_id": group_id,
        "group_identity": identity,
        "stages": {},
        "observations": 0,
        "plan_identity": None,
        "lm_request_state": "unknown",
        "lm_request_ids": [],
        "apply_state": "unknown",
        "submission": "unknown",
        "target_membership": "unknown",
        "coverage": "unknown",
        "coverage_basis": None,
        "coverage_claim_accepted": False,
        "captured_candidate_count": None,
        "group_member_count": None,
        "member_durable_seqs": [],
        "member_evidence_truncated": False,
        "retracted": False,
        "request_outcome": "unknown",
        "association_status": None,
        "completeness": {
            "complete": False,
            "basis": None,
            "why": "no_captured_group_members_and_target_evidence",
        },
        "scope": scope,
        "content_included": False,
    }


def _accumulate_choice(rollup, row, plugin, limits):
    identified = not rollup["group_identity"]["missing"]
    rollup["observations"] += 1
    stage = plugin.get("plugin_stage")
    rollup["stages"][stage] = rollup["stages"].get(stage, 0) + 1
    if plugin.get("plan_identity") is not None:
        rollup["plan_identity"] = plugin.get("plan_identity")
    state = plugin.get("lm_request_state")
    if state in ("issued_succeeded", "issued_failed"):
        rollup["lm_request_state"] = state
    elif state is not None and rollup["lm_request_state"] == "unknown":
        rollup["lm_request_state"] = state
    if plugin.get("lm_request_id") and plugin.get("lm_request_id") not in rollup["lm_request_ids"]:
        rollup["lm_request_ids"].append(plugin.get("lm_request_id"))
    if plugin.get("apply_state") not in (None, "not_applicable", "unknown"):
        rollup["apply_state"] = plugin.get("apply_state")
    if plugin.get("submission") not in (None, "not_applicable", "unknown"):
        rollup["submission"] = plugin.get("submission")
    if plugin.get("target_membership") not in (None, "unknown"):
        rollup["target_membership"] = plugin.get("target_membership")
    if plugin.get("coverage") not in (None, "unknown"):
        rollup["coverage"] = plugin.get("coverage")
        rollup["coverage_basis"] = plugin.get("coverage_basis")
        # Only an identified group can accept a coverage claim: without a
        # scoped group identity there is no captured group to be complete.
        if identified and _coverage_accepted(plugin):
            rollup["coverage_claim_accepted"] = True
            rollup["captured_candidate_count"] = plugin.get("captured_candidate_count")
            rollup["group_member_count"] = plugin.get("group_member_count")
            if len(rollup["member_durable_seqs"]) < limits["query_group_members_max"]:
                rollup["member_durable_seqs"].append(row.get("durable_seq"))
            else:
                rollup["member_evidence_truncated"] = True
        elif plugin.get("coverage") == "complete" and plugin.get("truncated") is True:
            rollup["completeness"]["why"] = "truncated_window_not_group_complete"
    if stage == "commit":
        rollup["request_outcome"] = "engine_commit_observed"
    elif stage == "cancellation":
        rollup["request_outcome"] = "cancelled"
    elif stage == "retraction":
        rollup["retracted"] = True
    if plugin.get("association_role") not in (None, "absent"):
        rollup["association_status"] = plugin.get("association_role")


def _finish_choice(rollup):
    identified = not rollup["group_identity"]["missing"]
    accepted = identified and rollup["coverage_claim_accepted"]
    if not identified:
        why = "scoped_group_identity_unavailable"
    elif accepted:
        why = "captured_group_members_and_target_with_consistent_counts"
    else:
        why = rollup["completeness"]["why"]
    rollup["completeness"] = {
        "complete": accepted,
        "basis": CHOICE_COMPLETE_BASIS if accepted else None,
        "why": why,
    }
    evidence_permitted = accepted and rollup["target_membership"] in ("present", "absent")
    rollup["evidence_permitted"] = evidence_permitted
    if evidence_permitted:
        reason = None
    elif not identified:
        reason = "scoped_group_identity_required"
    else:
        reason = "complete_captured_group_members_and_target_evidence_required"
    rollup["evidence_not_permitted_reason"] = reason
    rollup["human_correctness_proof"] = False
    rollup["application_proof"] = False
    rollup["ranking_benefit"] = False
    return rollup


def choice_group_rollup(rows, process_id, limits, group_id=None):
    """Per captured rerank group projection for one process.

    A group is (span AND category, source/window/group identity). Only an
    observation with the complete scoped identity (source instance, window and
    group) joins a group; an observation missing any of them is never merged
    by its absent keys. It stays visible as its own per-observation entry with
    explicit missing/partial identity, no accepted coverage and no
    `evidence_permitted`. Stage evidence stays per stage; completeness is only
    accepted with captured group members and target evidence with consistent
    counts. An explicit committed preference is not human correctness; a
    default submission is weak; cancelled, retracted, raw, unavailable and
    unknown outcomes never become default positive ranking labels; unselected
    is not negative.
    """
    bound = limits["query_choice_groups_max"]
    groups = {}
    order = []
    truncated = False
    truncation_reason = None
    unidentified = []
    unidentified_total = 0
    for row in rows:
        plugin = row.get("plugin")
        if not isinstance(plugin, dict):
            continue
        if process_id is not None and row.get("process_id") != process_id:
            continue
        if group_id is not None and plugin.get("group_id") != group_id:
            continue
        window_id = plugin.get("window_id")
        row_group_id = plugin.get("group_id")
        missing = [
            name
            for name, value in (
                ("source_instance_id", row.get("source_instance_id")),
                ("window_id", window_id),
                ("group_id", row_group_id),
            )
            if value is None
        ]
        if missing:
            unidentified_total += 1
            if len(unidentified) >= bound:
                continue
            entry = _choice_entry(row, window_id, row_group_id, missing)
            entry["durable_seq"] = row.get("durable_seq")
            _accumulate_choice(entry, row, plugin, limits)
            unidentified.append(_finish_choice(entry))
            continue
        key = (row.get("source_instance_id"), window_id, row_group_id)
        rollup = groups.get(key)
        if rollup is None:
            if len(groups) >= bound:
                truncated = True
                truncation_reason = "choice_group_bound"
                continue
            rollup = _choice_entry(row, window_id, row_group_id, missing)
            groups[key] = rollup
            order.append(key)
        _accumulate_choice(rollup, row, plugin, limits)
    rollups = [_finish_choice(groups[key]) for key in order]
    unidentified_truncated = unidentified_total > len(unidentified)
    return {
        "projection_version": CHOICE_PROJECTION_VERSION,
        "scope": "captured_rerank_group_span_and_category",
        "identity_rule": "scoped_source_window_group_required",
        "group_id_filter": group_id,
        "groups": rollups,
        "groups_total": len(rollups),
        "groups_truncated": truncated,
        "groups_truncation_reason": truncation_reason,
        "groups_limit": bound,
        "unidentified_observations": unidentified,
        "unidentified_observations_total": unidentified_total,
        "unidentified_observations_truncated": unidentified_truncated,
        "unidentified_observations_truncation_reason": (
            "choice_group_bound" if unidentified_truncated else None
        ),
        "no_whole_window_flag": True,
        "candidate_count_shortcut": False,
        "label_rules": {
            "explicit_committed_preference": "not_human_correctness",
            "default_submission": "weak_evidence",
            "cancelled_retracted_raw_unavailable_unknown": "never_default_positive_label",
            "unselected": "not_negative",
        },
        "content_included": False,
    }


_INDEX_ROW_ESTIMATE_BYTES = 320
