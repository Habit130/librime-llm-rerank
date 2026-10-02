"""Independent input-archive collector.

Durable publication is the fsynced watermark in state.json, written only after
the observation bytes are appended and fsynced. Anything short of that watermark
is not durable. An unclean restart reports an unknown crash tail and does not
parse unpublished bytes into observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import signal
import socket
import stat
import sys
import threading
import time
import uuid

from archive.interface import (
    CONTENT_VERSION,
    ENVELOPE_VERSION,
    INTERFACE_VERSION,
    ORDERING,
    SUPPORTED_SCHEMA,
    bind_unix_socket,
    canonical_bytes,
    encode_frame,
    error_body,
    failure,
    read_frame,
)
from archive.limits import resolve
from archive.safety import (
    UnsafeRoot,
    atomic_write,
    ensure_private_dir,
    open_nofollow,
    ordinary_token,
    reject_alias,
    safe_token,
    validate_root,
)

_KINDS = {
    "start",
    "input_change",
    "replacement",
    "temporary_selection",
    "commit_attempt",
    "cancellation",
    "raw_finalization",
    "unavailable_client",
    "unknown_outcome",
    "loss_notice",
    "exclusion_notice",
    "provenance",
}
_INTERMEDIATE = {"input_change", "replacement", "temporary_selection", "start"}
_REASONS = {
    "deliberate_exclusion",
    "queue_saturated",
    "displaced_for_priority",
    "storage_failure",
    "capacity_stop",
    "requeue_saturated",
    "collector_queue_saturated",
}
_OUTCOMES = {
    "observed_attempt",
    "cancelled",
    "raw_finalized",
    "unavailable_client",
    "unknown",
    "temporary_selection",
    "replacement",
    "input_change",
}
_HIGH = {
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
_CONTENT_FREE_KINDS = {"loss_notice", "exclusion_notice"}


def _hash(semantic):
    return hashlib.sha256(canonical_bytes(semantic)).hexdigest()


def _block_fifo(path, stop_flag):
    """Block until one byte is written or stop_flag is set.

    The caller should open the FIFO O_RDWR first so this open does not deadlock.
    """
    read_fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        os.set_blocking(read_fd, False)
        while not stop_flag():
            ready, _, _ = select.select([read_fd], [], [], 0.05)
            if not ready:
                continue
            chunk = os.read(read_fd, 1)
            if chunk:
                return
    finally:
        os.close(read_fd)


class Collector(object):
    def __init__(self, root, socket_path, limits, auto_checkpoint=True,
                 publication_hold="", phase_hold="", control_hold=""):
        self.root = root
        self.socket_path = socket_path
        self.limits = limits
        self.auto_checkpoint = auto_checkpoint
        self.publication_hold = publication_hold
        self.phase_hold = phase_hold
        self.control_hold = control_hold
        self.observations_path = os.path.join(root, "observations.jsonl")
        self.quarantine_path = os.path.join(root, "quarantine.jsonl")
        self.state_path = os.path.join(root, "state.json")
        self.policy_path = os.path.join(root, "policy.json")
        self.pid_path = os.path.join(root, "collector.pid")
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._queue = []
        self._queue_bytes = 0
        self._stop = False
        self._checkpoint_requested = False
        self._waiters = []
        self._index = []
        self._identities = {}
        self._update_ids = set()
        self._process_kinds = {}
        self._producers = {}
        self._publication_hold_active = False
        self._phase_hold_active = False
        self._control_hold_active = False
        self._policy_lock = threading.Lock()
        self._loaded_existing_state = False
        self._state = {}
        self._policy = {}
        self._sock = None
        self._publication = None

    def prepare(self):
        ensure_private_dir(self.root)
        self._validate_socket()
        self._refuse_managed_aliases()
        self._reject_foreign_collector()
        self._load_policy()
        self._load_state()
        self._prepare_files()
        self._rebuild_index()
        self._persist_state()

    def _refuse_managed_aliases(self):
        for path in (
            self.observations_path,
            self.quarantine_path,
            self.state_path,
            self.policy_path,
            self.pid_path,
            self.socket_path,
            os.path.join(self.root, "collector.out"),
            os.path.join(self.root, "collector.err"),
        ):
            reject_alias(path)

    def _validate_socket(self):
        if os.path.dirname(self.socket_path) != self.root:
            raise UnsafeRoot("socket_outside_root")
        if os.path.lexists(self.socket_path) and stat.S_ISLNK(os.lstat(self.socket_path).st_mode):
            raise UnsafeRoot("symlink_socket")

    def _reject_foreign_collector(self):
        reject_alias(self.pid_path)
        if not os.path.lexists(self.pid_path):
            return
        try:
            raw = self._read_nofollow(self.pid_path).strip()
            pid = int(raw)
        except (OSError, ValueError):
            return
        if pid == os.getpid() or not _pid_alive(pid):
            return
        command = _pid_command(pid)
        if "archive.collector" in command:
            raise UnsafeRoot("collector_already_running")

    def _load_policy(self):
        reject_alias(self.policy_path)
        if os.path.lexists(self.policy_path):
            self._policy = json.loads(self._read_nofollow(self.policy_path))
            if self._policy.get("desired") not in {"off", "enabled", "paused"}:
                self._policy["desired"] = "off"
        else:
            self._policy = {
                "policy_version": 1,
                "revision": 0,
                "desired": "off",
                "scope": "input_archive_only",
                "legacy_selection_recording": "separately_configured_may_continue",
                "legacy_switch_changed": False,
            }
            self._write_policy()

    def _load_state(self):
        reject_alias(self.state_path)
        if not os.path.lexists(self.state_path):
            self._state = self._fresh_state("none", ["collector_start"])
            self._loaded_existing_state = False
            return
        self._loaded_existing_state = True
        previous = json.loads(self._read_nofollow(self.state_path))
        reasons = ["collector_start"]
        crash_tail = "none"
        discarded = 0
        quarantine_discarded = 0
        short = False
        if not previous.get("clean_stop"):
            crash_tail = "unknown"
            reasons.append("unclean_shutdown")
        obs_extra, obs_short = self._reconcile_file(
            self.observations_path, int(previous.get("durable_offset", 0))
        )
        quar_extra, quar_short = self._reconcile_file(
            self.quarantine_path, int(previous.get("quarantine_bytes", 0))
        )
        discarded = obs_extra
        quarantine_discarded = quar_extra
        short = obs_short or quar_short
        if obs_extra or quar_extra or short:
            crash_tail = "unknown"
            if "unpublished_tail" not in reasons:
                reasons.append("unpublished_tail")
        self._state = self._fresh_state(crash_tail, reasons)
        for key in (
            "durable_seq",
            "durable_offset",
            "durable_bytes",
            "known_dropped_units",
            "storage_failed_units",
            "capacity_refused_units",
            "identity_conflicts",
            "capacity_stop",
            "storage_failure",
            "quarantine_bytes",
            "admission_refused_units",
        ):
            if key in previous:
                self._state[key] = previous[key]
        self._state["discarded_unpublished_bytes"] = discarded
        self._state["discarded_quarantine_bytes"] = quarantine_discarded
        if short:
            self._state["storage_failure"] = True
        if crash_tail == "unknown":
            self._state["crash_tail"] = "unknown"

    def _fresh_state(self, crash_tail, reasons):
        return {
            "state_version": 1,
            "durable_seq": 0,
            "durable_offset": 0,
            "durable_bytes": 0,
            "known_dropped_units": 0,
            "storage_failed_units": 0,
            "capacity_refused_units": 0,
            "identity_conflicts": 0,
            "capacity_stop": False,
            "storage_failure": False,
            "crash_tail": crash_tail,
            "discarded_unpublished_bytes": 0,
            "collector_epoch": uuid.uuid4().hex,
            "continuity_epoch": uuid.uuid4().hex,
            "continuity_break_reasons": reasons,
            "clean_stop": False,
            "quarantine_bytes": 0,
            "admission_refused_units": 0,
            "discarded_quarantine_bytes": 0,
        }

    def _reconcile_file(self, path, watermark):
        """Return (extra_bytes_truncated, short_of_watermark). Never follow a symlink."""
        reject_alias(path)
        if not os.path.lexists(path):
            if watermark:
                return 0, True
            return 0, False
        size = os.lstat(path).st_size
        if size > watermark:
            self._truncate_file(path, watermark)
            return size - watermark, False
        if size < watermark:
            return 0, True
        return 0, False

    def _read_nofollow(self, path):
        fd = open_nofollow(path, os.O_RDONLY)
        try:
            chunks = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8")
        finally:
            os.close(fd)

    def _prepare_files(self):
        for path in (self.observations_path, self.quarantine_path):
            reject_alias(path)
            if not os.path.lexists(path):
                fd = open_nofollow(path, os.O_CREAT | os.O_WRONLY)
                os.close(fd)
            else:
                fd = open_nofollow(path, os.O_RDWR)
                os.close(fd)
        atomic_write(self.pid_path, ("%s\n" % os.getpid()).encode("ascii"))

    def _rebuild_index(self):
        self._index = []
        self._identities = {}
        self._update_ids = set()
        self._process_kinds = {}
        if not os.path.exists(self.observations_path):
            return
        offset_limit = int(self._state.get("durable_offset", 0))
        with open(self.observations_path, "rb") as handle:
            while handle.tell() < offset_limit:
                start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if handle.tell() > offset_limit:
                    self._state["storage_failure"] = True
                    break
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    self._state["storage_failure"] = True
                    break
                if not isinstance(record, dict):
                    self._state["storage_failure"] = True
                    break
                self._remember(record, start, len(line))

    def _remember(self, record, offset, length):
        seq = int(record.get("durable_seq") or 0)
        process_id = record.get("process_id")
        kind = record.get("observation_kind")
        update_id = record.get("update_id")
        self._index.append(
            {
                "durable_seq": seq,
                "offset": offset,
                "length": length,
                "process_id": process_id,
                "observation_kind": kind,
                "update_id": update_id,
                "parent_update_id": record.get("parent_update_id"),
                "commit_id": record.get("commit_id"),
                "source_instance_id": record.get("source_instance_id"),
                "source_local_sequence": record.get("source_local_sequence"),
                "schema_id": record.get("schema_id"),
                "stage": record.get("stage"),
                "outcome": record.get("outcome"),
                "reason": record.get("reason"),
                "client_supplied_host_claim": record.get("client_supplied_host_claim"),
                "clocks": record.get("clocks"),
                "continuity_segment_id": record.get("continuity_segment_id"),
            }
        )
        identity = record.get("identity")
        content_hash = record.get("content_hash")
        if isinstance(identity, list) and len(identity) == 2 and content_hash and kind not in {"loss_notice"}:
            self._identities[(identity[0], identity[1])] = content_hash
        if isinstance(update_id, str):
            self._update_ids.add(update_id)
        if isinstance(process_id, str) and isinstance(kind, str):
            self._process_kinds.setdefault(process_id, set()).add(kind)

    def serve(self):
        self._sock = bind_unix_socket(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        self._sock.listen(128)
        self._sock.settimeout(0.1)
        self._publication = threading.Thread(target=self._publication_loop, name="archive-publication", daemon=True)
        self._publication.start()
        sys.stdout.write("ready\n")
        sys.stdout.flush()
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        self._final_checkpoint()
        self._mark_clean()
        try:
            self._sock.close()
        except OSError:
            pass
        if os.path.lexists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    def _handle(self, conn):
        try:
            conn.settimeout(self.limits["management_timeout_ms"] / 1000.0)
            try:
                request = read_frame(conn, self.limits["max_frame_bytes"])
                if request is None:
                    return
                response = self._dispatch(request)
            except Exception:
                sys.stderr.write("code=malformed_frame\n")
                response = failure("unknown", "", "malformed_frame")
            self._send(conn, response)
        finally:
            conn.close()

    def _send(self, conn, response):
        try:
            conn.sendall(encode_frame(response, self.limits["max_frame_bytes"]))
        except Exception:
            sys.stderr.write("code=malformed_frame\n")

    def _dispatch(self, request):
        op = request.get("op") if isinstance(request.get("op"), str) else "unknown"
        request_id = request.get("request_id") if isinstance(request.get("request_id"), str) else ""
        if request.get("interface_version") != INTERFACE_VERSION:
            return failure(op, request_id, "unsupported_version")
        if request.get("envelope_version") != ENVELOPE_VERSION:
            return failure(op, request_id, "unsupported_version")
        content = request.get("content_version", CONTENT_VERSION)
        if content != CONTENT_VERSION and op in {"admit_batch", "query", "set_policy"}:
            return failure(op, request_id, "unsupported_version")
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        if op == "status" or op == "overview":
            return self._ok(op, request_id, self.snapshot())
        if op == "policy_observe":
            return self._ok(op, request_id, self._observe_producer(body))
        if op == "query":
            return self._query(op, request_id, body)
        if op == "set_policy":
            return self._set_policy(op, request_id, body)
        if op == "checkpoint":
            return self._ok(op, request_id, self._checkpoint_and_snapshot())
        if op == "admit_batch":
            return self._admit_batch(op, request_id, body)
        if op == "shutdown":
            self._stop = True
            try:
                self._sock.settimeout(0.01)
            except OSError:
                pass
            return self._ok(op, request_id, {"shutting_down": True, "content_included": False})
        return failure(op, request_id, "invalid_request")

    def _ok(self, op, request_id, body):
        body = dict(body)
        body["content_included"] = False
        return {
            "interface_version": INTERFACE_VERSION,
            "envelope_version": ENVELOPE_VERSION,
            "op": op,
            "request_id": request_id,
            "ok": True,
            "body": body,
            "content_included": False,
        }

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            producers = []
            fresh_match = 0
            stale = 0
            for source_id, observed in self._producers.items():
                age_ms = int((now - observed["seen"]) * 1000)
                is_fresh = age_ms <= self.limits["freshness_window_ms"]
                matches = observed["revision"] is not None and observed["revision"] == self._policy["revision"]
                if not is_fresh or not matches:
                    stale += 1
                elif is_fresh and matches:
                    fresh_match += 1
                producers.append(
                    {
                        "source_instance_id": ordinary_token(source_id),
                        "observed_revision": observed["revision"],
                        "freshness": "fresh" if is_fresh else "stale",
                        "matches_desired_revision": matches,
                        "effective": bool(is_fresh and matches and self._policy["desired"] == "enabled"),
                    }
                )
            desired = self._policy["desired"]
            if self._state["storage_failure"]:
                collector_effective = "storage_failure"
            elif self._state["capacity_stop"]:
                collector_effective = "capacity_stop"
            else:
                collector_effective = desired
            globally = (
                desired == "enabled"
                and collector_effective == "enabled"
                and fresh_match >= 1
                and stale == 0
            )
            used = self._state["durable_bytes"] + self._state["quarantine_bytes"]
            warning = used >= int(self.limits["archive_capacity_bytes"] * self.limits["warning_ratio"])
            return {
                "interface_version": INTERFACE_VERSION,
                "desired_policy": desired,
                "desired_revision": self._policy["revision"],
                "desired_durable": True,
                "collector_effective": collector_effective,
                "collector_epoch": self._state["collector_epoch"],
                "continuity_epoch": self._state["continuity_epoch"],
                "continuity_broken": True,
                "continuity_break_reasons": list(self._state["continuity_break_reasons"]),
                "globally_effective": globally,
                "scope": "input_archive_only",
                "legacy_selection_recording": "separately_configured_may_continue",
                "legacy_switch_changed": False,
                "acknowledgement_scope": "collector_durable_desired_policy",
                "durable_seq": self._state["durable_seq"],
                "received_unpublished": len(self._queue),
                "known_dropped_units": self._state["known_dropped_units"],
                "storage_failed_units": self._state["storage_failed_units"],
                "capacity_refused_units": self._state["capacity_refused_units"],
                "crash_tail": self._state["crash_tail"],
                "unclean_shutdown_observed": "unclean_shutdown" in self._state["continuity_break_reasons"],
                "discarded_unpublished_bytes": self._state["discarded_unpublished_bytes"],
                "discarded_quarantine_bytes": self._state.get("discarded_quarantine_bytes", 0),
                "admission_refused_units": self._state.get("admission_refused_units", 0),
                "storage_failure": self._state["storage_failure"],
                "capacity_stop": self._state["capacity_stop"],
                "warning": warning and not self._state["capacity_stop"],
                "durable_bytes": self._state["durable_bytes"],
                "quarantine_bytes": self._state["quarantine_bytes"],
                "capacity_bytes": self.limits["archive_capacity_bytes"],
                "identity_conflicts": self._state["identity_conflicts"],
                "producer_observations": producers,
                "limits": dict(self.limits),
                "ordering": ORDERING,
                "host_persistence_proof": False,
                "inference_dependency": False,
                "inference_availability": "not_observed",
                "ranking_benefit": False,
                "five_view_complete": False,
                "publication_hold": self._publication_hold_active,
                "publication_phase_hold": self._phase_hold_active,
                "control_hold": self._control_hold_active,
                "content_included": False,
            }

    def _observe_producer(self, body):
        source_id = body.get("source_instance_id")
        if safe_token(source_id) is None:
            return self.snapshot()
        with self._lock:
            declared = body.get("observed_revision")
            if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
                declared = None
            self._producers[source_id] = {
                "revision": declared,
                "seen": time.monotonic(),
            }
        return {
            "desired_policy": self._policy["desired"],
            "desired_revision": self._policy["revision"],
            "collector_effective": self.snapshot()["collector_effective"],
            "freshness_window_ms": self.limits["freshness_window_ms"],
            "content_included": False,
        }

    def _set_policy(self, op, request_id, body):
        if self.control_hold:
            with self._lock:
                self._control_hold_active = True
            _block_fifo(self.control_hold, lambda: self._stop)
            with self._lock:
                self._control_hold_active = False
            if self._stop:
                return failure(op, request_id, "shutdown")
        desired = body.get("desired")
        expected = body.get("expected_revision")
        if desired not in {"off", "enabled", "paused"} or isinstance(expected, bool) or not isinstance(expected, int):
            return failure(op, request_id, "invalid_request")
        with self._policy_lock:
            with self._lock:
                if expected != self._policy["revision"]:
                    return failure(op, request_id, "stale_revision")
                revision = expected + 1
                policy = {
                    "policy_version": 1,
                    "revision": revision,
                    "desired": desired,
                    "scope": "input_archive_only",
                    "legacy_selection_recording": "separately_configured_may_continue",
                    "legacy_switch_changed": False,
                }
            try:
                atomic_write(self.policy_path, canonical_bytes(policy) + b"\n")
            except OSError:
                with self._lock:
                    self._state["storage_failure"] = True
                return failure(op, request_id, "storage_failure")
            with self._lock:
                self._policy = policy
                self._break_continuity_locked("policy_transition")
        body = self.snapshot()
        body["scope"] = "collector_durable_desired_policy"
        body["revision"] = revision
        body["desired"] = desired
        body["durable"] = True
        body["producer_effective"] = False
        return self._ok(op, request_id, body)

    def _break_continuity_locked(self, reason):
        self._state["continuity_epoch"] = uuid.uuid4().hex
        if reason not in self._state["continuity_break_reasons"]:
            self._state["continuity_break_reasons"].append(reason)

    def _write_policy(self):
        atomic_write(self.policy_path, canonical_bytes(self._policy) + b"\n")

    def _admit_batch(self, op, request_id, body):
        observations = body.get("observations")
        if not isinstance(observations, list) or len(observations) > self.limits["batch_size"]:
            return failure(op, request_id, "invalid_request")
        codes = [self._accept_one(item) for item in observations]
        counts = {}
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
        return self._ok(op, request_id, {"codes": codes, "counts": counts, "durable": False})

    def _accept_one(self, observation):
        if not isinstance(observation, dict):
            with self._lock:
                self._state["admission_refused_units"] = self._state.get("admission_refused_units", 0) + 1
            return "invalid_request"
        if observation.get("envelope_version", ENVELOPE_VERSION) != ENVELOPE_VERSION:
            return "unsupported_version"
        if observation.get("content_version", CONTENT_VERSION) != CONTENT_VERSION:
            return "unsupported_version"
        prepared = self._prepare(observation)
        if isinstance(prepared, str):
            if prepared == "invalid_request":
                with self._lock:
                    self._state["admission_refused_units"] = self._state.get("admission_refused_units", 0) + 1
            return prepared
        size = len(canonical_bytes(prepared["semantic"]))
        if size > self.limits["max_event_bytes"]:
            with self._lock:
                self._state["admission_refused_units"] = self._state.get("admission_refused_units", 0) + 1
            return "event_too_large"
        with self._lock:
            if self._state["storage_failure"]:
                return "storage_failure"
            if self._state["capacity_stop"]:
                self._state["capacity_refused_units"] += 1
                return "capacity_stop"
            if prepared["kind"] not in _CONTENT_FREE_KINDS and self._policy["desired"] != "enabled":
                return "capture_disabled"
            identity = prepared["identity"]
            if identity is not None:
                previous = self._identities.get(identity)
                if previous == prepared["content_hash"]:
                    return "duplicate"
                if previous is not None:
                    self._state["identity_conflicts"] += 1
                    self._break_continuity_locked("identity_conflict")
                    queued = self._queue_locked(prepared, size, quarantine=True)
                    return "identity_conflict" if queued else "queue_saturated"
            if not self._queue_locked(prepared, size, quarantine=False):
                self._state["known_dropped_units"] += 1
                self._break_continuity_locked("known_loss")
                return "queue_saturated"
            if identity is not None:
                self._identities[identity] = prepared["content_hash"]
            return "admitted"

    def _prepare(self, observation):
        excluded = observation.get("eligibility") == "excluded" or observation.get("excluded") is True
        kind = observation.get("observation_kind")
        if not isinstance(kind, str):
            return "invalid_request"
        if excluded:
            kind = "exclusion_notice"
        elif kind not in _KINDS:
            kind = "unknown_outcome"
        source_id = observation.get("source_instance_id")
        sequence = observation.get("source_local_sequence")
        process_id = observation.get("process_id")
        if safe_token(source_id) is None or safe_token(process_id) is None:
            return "invalid_request"
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            return "invalid_request"
        schema = observation.get("schema_id", "unknown")
        if kind not in _CONTENT_FREE_KINDS:
            if schema == SUPPORTED_SCHEMA:
                schema_interpretation = "supported"
            elif schema == "unknown":
                schema_interpretation = "unknown"
            else:
                return "unsupported_schema"
        else:
            schema = "unknown"
            schema_interpretation = "unknown"
        payload = None if excluded or kind in _CONTENT_FREE_KINDS else observation.get("payload")
        if payload is not None and not isinstance(payload, (dict, list, str, int, float, bool)):
            payload = None
        semantic = {
            "source_instance_id": source_id,
            "source_local_sequence": sequence,
            "observation_kind": kind,
            "process_id": process_id,
            "update_id": _optional_token(observation.get("update_id")),
            "commit_id": _optional_token(observation.get("commit_id")),
            "parent_update_id": _optional_token(observation.get("parent_update_id")),
            "continuity_segment_id": _optional_token(observation.get("continuity_segment_id")),
            "schema_id": schema,
            "schema_interpretation": schema_interpretation,
            "clocks": _clocks(observation.get("clocks")),
            "stage": _token_or_unknown(observation.get("stage")),
            "outcome": _outcome(observation.get("outcome"), kind),
            "reason": _reason(observation.get("reason"), kind),
            "eligibility": "excluded" if excluded else "included",
            "payload": payload,
            "client_supplied_host_claim": _host_claim(observation.get("host_persistence")),
        }
        return {
            "semantic": semantic,
            "kind": kind,
            "identity": (source_id, sequence),
            "content_hash": _hash(semantic),
            "priority": "high" if kind in _HIGH else "low",
        }

    def _queue_locked(self, prepared, size, quarantine):
        if self._fits_locked(size):
            self._queue.append({"prepared": prepared, "size": size, "quarantine": quarantine})
            self._queue_bytes += size
            self._cv.notify()
            return True
        if prepared["priority"] == "high":
            for index, item in enumerate(self._queue):
                if item["prepared"]["priority"] == "low" and not item["quarantine"]:
                    self._displace_locked(index)
                    self._queue.append({"prepared": prepared, "size": size, "quarantine": quarantine})
                    self._queue_bytes += size
                    self._cv.notify()
                    return True
        return False

    def _fits_locked(self, size):
        return (
            len(self._queue) + 1 <= self.limits["collector_queue_count"]
            and self._queue_bytes + size <= self.limits["collector_queue_bytes"]
        )

    def _displace_locked(self, index):
        item = self._queue.pop(index)
        self._queue_bytes -= item["size"]
        identity = item["prepared"]["identity"]
        if identity in self._identities and not item["quarantine"]:
            self._identities.pop(identity, None)
        self._state["known_dropped_units"] += 1
        self._break_continuity_locked("known_loss")

    def _publication_loop(self):
        try:
            self._publication_loop_inner()
        except Exception:
            sys.stderr.write("code=storage_failure\n")
            with self._lock:
                self._state["storage_failure"] = True

    def _publication_loop_inner(self):
        if self.publication_hold:
            with self._lock:
                self._publication_hold_active = True
            _block_fifo(self.publication_hold, lambda: self._stop)
            with self._lock:
                self._publication_hold_active = False
        while not self._stop or self._queue:
            batch, waiters = self._take_batch()
            if batch:
                self._publish(batch)
            elif waiters:
                self._persist_state()
            for waiter in waiters:
                waiter.set()
            if self._stop and not self._queue:
                break

    def _take_batch(self):
        interval = self.limits["checkpoint_interval_ms"] / 1000.0 if self.auto_checkpoint else None
        with self._cv:
            if not self._queue and not self._checkpoint_requested and not self._stop:
                self._cv.wait(timeout=interval if interval else 0.2)
            count = len(self._queue) if (self._checkpoint_requested or self.auto_checkpoint or self._stop) else 0
            if count == 0 and not self._checkpoint_requested:
                return [], []
            take = min(len(self._queue), self.limits["batch_size"])
            if take == 0:
                waiters = self._waiters
                self._waiters = []
                self._checkpoint_requested = False
                return [], waiters
            batch = self._queue[:take]
            del self._queue[:take]
            self._queue_bytes -= sum(item["size"] for item in batch)
            waiters = []
            if not self._queue:
                waiters = self._waiters
                self._waiters = []
                self._checkpoint_requested = False
            return batch, waiters

    def _publish(self, batch):
        observation_lines = []
        quarantine_lines = []
        metas = []
        with self._lock:
            capacity = self.limits["archive_capacity_bytes"]
            used = self._state["durable_bytes"] + self._state["quarantine_bytes"]
            next_seq = self._state["durable_seq"]
        for item in batch:
            prepared = item["prepared"]
            semantic = dict(prepared["semantic"])
            target_quarantine = item["quarantine"]
            if target_quarantine:
                line = canonical_bytes({"content_hash": prepared["content_hash"], "payload": semantic.get("payload")}) + b"\n"
                if used + len(line) > capacity:
                    with self._lock:
                        self._state["capacity_stop"] = True
                        self._state["capacity_refused_units"] += 1
                    continue
                quarantine_lines.append(line)
                used += len(line)
                continue
            next_seq += 1
            record = dict(semantic)
            record["record_version"] = 1
            record["durable_seq"] = next_seq
            record["content_hash"] = prepared["content_hash"]
            record["identity"] = list(prepared["identity"]) if prepared["identity"] else None
            record["host_persistence"] = "unknown"
            record["host_persistence_proof"] = False
            line = canonical_bytes(record) + b"\n"
            if used + len(line) > capacity:
                next_seq -= 1
                with self._lock:
                    self._state["capacity_stop"] = True
                    self._state["capacity_refused_units"] += 1
                    identity = prepared["identity"]
                    if identity in self._identities:
                        self._identities.pop(identity, None)
                continue
            observation_lines.append(line)
            metas.append(record)
            used += len(line)
        before_offset = self._regular_size(self.observations_path)
        before_quarantine = self._regular_size(self.quarantine_path)
        try:
            if quarantine_lines:
                self._append(self.quarantine_path, b"".join(quarantine_lines))
            if observation_lines:
                self._append(self.observations_path, b"".join(observation_lines))
        except (OSError, UnsafeRoot):
            with self._lock:
                self._state["storage_failure"] = True
                self._state["storage_failed_units"] += len(observation_lines) + len(quarantine_lines)
                for record in metas:
                    identity = tuple(record["identity"]) if record.get("identity") else None
                    if identity in self._identities:
                        self._identities.pop(identity, None)
            self._persist_state()
            return
        if self.phase_hold and (observation_lines or quarantine_lines):
            with self._lock:
                self._phase_hold_active = True
            _block_fifo(self.phase_hold, lambda: self._stop)
            with self._lock:
                self._phase_hold_active = False
            if self._stop:
                self._truncate_file(self.observations_path, before_offset)
                self._truncate_file(self.quarantine_path, before_quarantine)
                return
        with self._lock:
            offset = self._state["durable_offset"]
            for record, line in zip(metas, observation_lines):
                self._remember(record, offset, len(line))
                offset += len(line)
                self._state["durable_seq"] = record["durable_seq"]
                self._state["durable_bytes"] += len(line)
            self._state["durable_offset"] = offset
            self._state["quarantine_bytes"] += sum(len(line) for line in quarantine_lines)
            used_now = self._state["durable_bytes"] + self._state["quarantine_bytes"]
            if used_now >= self.limits["archive_capacity_bytes"]:
                self._state["capacity_stop"] = True
        self._persist_state()

    def _append(self, path, data):
        fd = open_nofollow(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _regular_size(self, path):
        reject_alias(path)
        if not os.path.lexists(path):
            return 0
        return os.lstat(path).st_size

    def _persist_state(self):
        with self._lock:
            payload = canonical_bytes(self._state) + b"\n"
        atomic_write(self.state_path, payload)

    def _checkpoint_and_snapshot(self):
        waiter = threading.Event()
        with self._cv:
            self._checkpoint_requested = True
            self._waiters.append(waiter)
            self._cv.notify()
        waiter.wait(timeout=self.limits["management_timeout_ms"] / 1000.0)
        return self.snapshot()

    def _final_checkpoint(self):
        if self._publication is None:
            return
        with self._cv:
            self._checkpoint_requested = True
            self._cv.notify()
        self._publication.join(timeout=2.0)

    def _mark_clean(self):
        size = os.path.getsize(self.observations_path) if os.path.exists(self.observations_path) else 0
        with self._lock:
            self._state["clean_stop"] = size == self._state["durable_offset"]
        self._persist_state()

    def _truncate_file(self, path, offset):
        reject_alias(path)
        if not os.path.lexists(path):
            return
        fd = open_nofollow(path, os.O_RDWR)
        try:
            os.ftruncate(fd, offset)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _state_storage_failed(self):
        with self._lock:
            return bool(self._state["storage_failure"])

    def _query(self, op, request_id, body):
        view = body.get("view")
        if view in {"overview", "status"}:
            return self._ok(op, request_id, self.snapshot())
        if view not in {"timeline", "process", "losses"}:
            return failure(op, request_id, "invalid_request")
        page_size = body.get("page_size", self.limits["page_size_default"])
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
            return failure(op, request_id, "invalid_request")
        if page_size > self.limits["page_size_max"]:
            return failure(op, request_id, "page_bound")
        cursor = body.get("cursor")
        start_seq = 0
        if cursor not in (None, ""):
            if isinstance(cursor, bool) or not isinstance(cursor, int):
                if isinstance(cursor, str) and cursor.isdigit():
                    start_seq = int(cursor)
                else:
                    return failure(op, request_id, "invalid_request")
            else:
                start_seq = cursor
        private = body.get("private_detail") is True and view == "process"
        with self._lock:
            watermark = self._state["durable_seq"]
            epoch = self._state["collector_epoch"]
            index = list(self._index)
            update_ids = set(self._update_ids)
            process_kinds = {key: set(value) for key, value in self._process_kinds.items()}
        selected = []
        for entry in index:
            if entry["durable_seq"] <= start_seq or entry["durable_seq"] > watermark:
                continue
            if view == "losses" and entry["observation_kind"] != "loss_notice":
                continue
            if view == "process" and entry["process_id"] != body.get("process_id"):
                continue
            if view == "timeline" and entry["observation_kind"] == "loss_notice":
                pass
            selected.append(entry)
            if len(selected) >= page_size:
                break
        rows = [self._summary(entry, update_ids, process_kinds, private) for entry in selected]
        next_cursor = selected[-1]["durable_seq"] if len(selected) >= page_size else None
        response = {
            "view": view,
            "ordering": ORDERING,
            "page_size": page_size,
            "cursor": start_seq,
            "next_cursor": next_cursor,
            "as_of_durable_seq": watermark,
            "collector_epoch": epoch,
            "observations": rows,
            "returned": len(rows),
            "content_included": private,
            "private_detail": private,
        }
        if private:
            return {
                "interface_version": INTERFACE_VERSION,
                "envelope_version": ENVELOPE_VERSION,
                "op": op,
                "request_id": request_id,
                "ok": True,
                "body": response,
                "content_included": True,
            }
        return self._ok(op, request_id, response)

    def _summary(self, entry, update_ids, process_kinds, private):
        parent = entry.get("parent_update_id")
        if parent is None:
            parent_status = "absent"
        elif parent in update_ids:
            parent_status = "present"
        else:
            parent_status = "missing"
        kinds = process_kinds.get(entry.get("process_id"), set())
        incompleteness = []
        if entry.get("observation_kind") == "commit_attempt" and not (_INTERMEDIATE & kinds):
            incompleteness.append("missing_intermediate")
        if parent_status == "missing":
            incompleteness.append("missing_parent_update")
        summary = {
            "durable_seq": entry["durable_seq"],
            "observation_kind": entry["observation_kind"],
            "process_id": ordinary_token(entry.get("process_id")),
            "update_id": ordinary_token(entry.get("update_id")) if entry.get("update_id") else None,
            "parent_update_id": ordinary_token(parent) if parent else None,
            "parent_status": parent_status,
            "commit_id": ordinary_token(entry.get("commit_id")) if entry.get("commit_id") else None,
            "source_instance_id": ordinary_token(entry.get("source_instance_id")),
            "source_local_sequence": entry.get("source_local_sequence"),
            "schema_id": entry.get("schema_id"),
            "stage": entry.get("stage") or "unknown",
            "outcome": entry.get("outcome") or "unknown",
            "reason": entry.get("reason"),
            "host_persistence": "unknown",
            "host_persistence_proof": False,
            "client_supplied_host_claim": entry.get("client_supplied_host_claim"),
            "clocks": entry.get("clocks") or _clocks(None),
            "continuity_segment_id": ordinary_token(entry.get("continuity_segment_id")) if entry.get("continuity_segment_id") else None,
            "incompleteness": incompleteness,
            "semantic_interpretation": _interpretation(entry.get("observation_kind")),
            "content_included": False,
        }
        if private:
            payload = self._read_payload(entry)
            summary["payload"] = payload
            summary["content_included"] = True
        return summary

    def _read_payload(self, entry):
        with open(self.observations_path, "rb") as handle:
            handle.seek(entry["offset"])
            line = handle.read(entry["length"])
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        return record.get("payload")


def _optional_token(value):
    if value is None:
        return None
    return safe_token(value)


def _token_or_unknown(value):
    token = safe_token(value)
    return token or "unknown"


def _clocks(value):
    event_time = None
    observation_time = None
    if isinstance(value, dict):
        if isinstance(value.get("event_time"), (int, float)) and not isinstance(value.get("event_time"), bool):
            event_time = value.get("event_time")
        if isinstance(value.get("observation_time"), (int, float)) and not isinstance(value.get("observation_time"), bool):
            observation_time = value.get("observation_time")
    return {
        "event_time": event_time,
        "observation_time": observation_time,
        "clock_domain": "unknown",
    }


def _outcome(value, kind):
    if value in _OUTCOMES:
        return value
    defaults = {
        "commit_attempt": "observed_attempt",
        "cancellation": "cancelled",
        "raw_finalization": "raw_finalized",
        "unavailable_client": "unavailable_client",
        "temporary_selection": "temporary_selection",
        "replacement": "replacement",
        "input_change": "input_change",
    }
    return defaults.get(kind, "unknown")


def _reason(value, kind):
    if value in _REASONS:
        return value
    if kind == "exclusion_notice":
        return "deliberate_exclusion"
    return None


def _host_claim(value):
    if value in {"persisted", "unknown", "unavailable"}:
        return value
    if value is None:
        return None
    return "unrecognized"


def _interpretation(kind):
    return {
        "start": "process_started",
        "input_change": "input_change_observed",
        "replacement": "replacement_observed",
        "temporary_selection": "temporary_selection_observed",
        "commit_attempt": "commit_attempt_observed",
        "cancellation": "cancelled",
        "raw_finalization": "raw_finalization_observed",
        "unavailable_client": "unavailable_client",
        "unknown_outcome": "unknown",
        "loss_notice": "known_loss",
        "exclusion_notice": "deliberate_exclusion",
        "provenance": "provenance_observed",
    }.get(kind, "unknown")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_command(pid):
    try:
        import subprocess
        return subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    except Exception:
        return ""


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Input-archive collector")
    parser.add_argument("--root", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--no-auto-checkpoint", action="store_true")
    parser.add_argument("--publication-hold", default="")
    parser.add_argument("--publication-phase-hold", default="")
    parser.add_argument("--control-hold", default="")
    for key in (
        "producer_queue_count",
        "producer_queue_bytes",
        "collector_queue_count",
        "collector_queue_bytes",
        "max_event_bytes",
        "archive_capacity_bytes",
        "page_size_default",
        "page_size_max",
        "checkpoint_interval_ms",
        "freshness_window_ms",
        "heartbeat_interval_ms",
        "max_frame_bytes",
        "batch_size",
        "connect_timeout_ms",
        "management_timeout_ms",
    ):
        parser.add_argument("--" + key.replace("_", "-"), dest=key, type=int)
    parser.add_argument("--warning-ratio", dest="warning_ratio", type=float)
    return parser.parse_args(argv)


def limits_from_args(args):
    overrides = {}
    for key in (
        "producer_queue_count",
        "producer_queue_bytes",
        "collector_queue_count",
        "collector_queue_bytes",
        "max_event_bytes",
        "archive_capacity_bytes",
        "warning_ratio",
        "page_size_default",
        "page_size_max",
        "checkpoint_interval_ms",
        "freshness_window_ms",
        "heartbeat_interval_ms",
        "max_frame_bytes",
        "batch_size",
        "connect_timeout_ms",
        "management_timeout_ms",
    ):
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = value
    return resolve(overrides)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        root = validate_root(args.root)
        limits = limits_from_args(args)
        collector = Collector(
            root,
            args.socket,
            limits,
            auto_checkpoint=not args.no_auto_checkpoint,
            publication_hold=args.publication_hold,
            phase_hold=args.publication_phase_hold,
            control_hold=args.control_hold,
        )
        collector.prepare()
    except UnsafeRoot as exc:
        sys.stderr.write("code=%s\n" % exc.code)
        return 2
    except (KeyError, ValueError):
        sys.stderr.write("code=invalid_request\n")
        return 2
    def _term(_signum, _frame):
        collector._stop = True
    signal.signal(signal.SIGTERM, _term)
    try:
        collector.serve()
    except UnsafeRoot as exc:
        sys.stderr.write("code=%s\n" % exc.code)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
