#!/usr/bin/env python3
"""Contract checker for the shared input-archive query Interface (Squirrel#192).

This is an orchestration entry, not a second archive or a second frontend. It
drives the versioned query Interface over a genuine collector with invented
fixtures, and its contract suite compiles the read-only accepted Squirrel
frontend against the source-built librime and the final plugin source export,
runs the production controller/plugin chain and a model-free fixture daemon
request handler, then inspects the NEW shared Interface outcomes and persisted
frontend timing rows.

Model-free substituted compute note: the fixture daemon answers with a
deterministic in-process scorer, so the suite proves association and handler
transport, never actual MLX phases or model performance. Ordinary stdout,
stderr and the report are content-free; private text appears only in a
deliberate private-detail query.

`--self-test` is supplementary. The contract suite covers the finite fixtures
and the 256/4096 scales; a skipped required case fails.

This checker does not enable capture, does not implement a second join
algorithm, and does not touch the old frontend timing checker's pin or result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from archive import Client  # noqa: E402
from archive.querying import (  # noqa: E402
    QUERY_VERSION,
    decode_cursor,
    percentiles,
)

REQUIRED_CASES = (
    "IdentityRelationsFixtures",
    "ChoiceProjectionStages",
    "TimingNumericFixtures",
    "OverviewHonestCounts",
    "Scale256And4096",
    "HighFanoutProcessBounds",
    "ConcurrentAppendAndRestartPrefix",
    "QueryNeverProbesOrLoads",
    "FrontendTimingRealChain",
    "PrivacyCanaryAndAdapters",
    "SourceBindingsAndReport",
)
WATCHDOG_MS = 2000
SCALE_SMALL = 256
SCALE_LARGE = 4096
CANARY = "Q192CANARY"
CANARY_TEXT = "你好" + CANARY
ACCEPTED_FRONTEND_TREE = "9bb76cf4d7c7dcd375ce1c6009d4416aa83baa42"
HARNESS_NAME = "check_input_archive_query_frontend.swift"
DAEMON_DIR = os.path.join(REPO, "daemon")


class CheckFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_rev(repo, *args):
    try:
        return subprocess.check_output(
            ["git", "-C", repo, *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def content_free(text, label):
    for needle in (CANARY, "你好", "甲正", "甲敏", "甲斥", "jiazheng", "jiamin", "jiachi", "INV-"):
        if needle in text:
            raise CheckFailure("content_leak:" + label)


def http_free(value, private=False):
    """Recursively verify no payload-bearing value is present."""
    forbidden = {
        "payload",
        "text",
        "committed_text",
        "candidate_text",
        "preceding_text",
        "composition",
        "preedit",
        "comment",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if not private and key in forbidden and item is not None:
                raise CheckFailure("content_key:" + key)
            http_free(item, private)
    elif isinstance(value, list):
        for item in value:
            http_free(item, private)


def frame(stage, sequence, source="ps-q192", process="p-q192", kind="commit_attempt", **extra):
    payload = {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": source,
        "source_local_sequence": sequence,
        "observation_kind": kind,
        "process_id": process,
        "clocks": {"observation_time": 1770000000000, "event_time": None},
        "outcome": "observed_attempt",
        "stage": stage,
    }
    payload.update(extra)
    return payload


def plugin_frame(sequence, source="plug-q192", process="p-q192", stage="competition", **extra):
    payload = {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": source,
        "source_local_sequence": sequence,
        "observation_kind": "plugin_observation",
        "plugin_observation_version": 1,
        "plugin_stage": stage,
        "process_id": process,
        "association_role": "absent",
        "association_read": "absent",
        "coverage": "unknown",
        "coverage_basis": "unspecified",
        "lm_request_state": "no_request",
        "apply_state": "not_applicable",
        "submission": "not_applicable",
        "target_membership": "unknown",
        "payload": {"text": CANARY_TEXT},
    }
    payload.update(extra)
    return payload


def frontend_timing_object(
    sequence,
    action_id,
    operation="key_update",
    entry=100000,
    endpoint_ticks=900000,
    numer=125,
    denom=3,
    endpoint="panel_update",
    duration=None,
    validity="valid",
    update_calls=None,
    **extra,
):
    if duration is None:
        duration = (endpoint_ticks - entry) * numer // denom
    if update_calls is None:
        update_calls = [{"endpoint": endpoint, "ticks": endpoint_ticks}] if endpoint != "unavailable" else []
    timing = {
        "version": 1,
        "action_id": action_id,
        "action": "key_handler",
        "operation": operation,
        "clock": {
            "domain": "mach_absolute_time",
            "unit": "nanoseconds",
            "timebase_numer": numer,
            "timebase_denom": denom,
        },
        "event_queue_wait": "unknown",
        "nested_actions": 0,
        "continuity_cut": False,
        "association": {"source_instance_id": "ps-q192", "process_id": "p-q192"},
        "update_calls": update_calls,
        "endpoint": endpoint,
        "entry_ticks": entry,
        "endpoint_ticks": endpoint_ticks,
        "duration_ns": duration,
        "validity": validity,
    }
    timing.update(extra)
    return {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": "ps-q192",
        "source_local_sequence": sequence,
        "observation_kind": "provenance",
        "process_id": "p-q192",
        "stage": "frontend_timing",
        "outcome": "unknown",
        "payload": {"frontend_timing": timing},
    }


def daemon_request(sequence, request_id, plan, **extra):
    payload = {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "unknown",
        "source_instance_id": "daemon-q192",
        "source_local_sequence": sequence,
        "observation_kind": "daemon_observation",
        "daemon_observation_version": 1,
        "daemon_stage": "request",
        "process_id": "p-q192",
        "observed_at_wall_ms": 1770000100000,
        "edges": {"request_accepted": 0.5},
        "request_id": request_id,
        "plan_identity": plan,
        "effective_policy_id": "policy-q192",
        "declared_policy_digest": "a" * 64,
        "declared_policy_exact": True,
        "scoring_strategy": "mean_token",
        "context_window_rule": "unicode_char_tail",
        "attribution_rule": "decode_prefix_reconstruction",
        "context_window_chars": 64,
        "requested_context_chars": 8,
        "effective_context_chars": 8,
        "context_truncated": False,
        "candidate_count": 4,
        "candidate_chars": 12,
        "model_identity": "fixture",
        "adapter_present": False,
        "adapter_digest": None,
    }
    payload.update(extra)
    return payload


def collector_command(root, sock, *extra):
    return [sys.executable, "-m", "archive.cli", "--root", root, "--socket", sock, *extra]


def start_collector(root, sock, **limits):
    os.makedirs(os.path.dirname(root), mode=0o700, exist_ok=True)
    command = collector_command(root, sock, "collector", "start")
    for key, value in limits.items():
        command.extend(["--" + key.replace("_", "-"), str(value)])
    code = subprocess.call(command, cwd=REPO)
    if code != 0:
        raise CheckFailure("collector_start")


def stop_collector(root, sock):
    subprocess.call(collector_command(root, sock, "collector", "stop"), cwd=REPO)


def rss_kb(pid):
    try:
        output = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True)
        return int(output.strip() or 0)
    except Exception:
        return 0


def _pid_of(root):
    try:
        with open(os.path.join(root, "collector.pid")) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return 0


def _admit(client, observations, allow_transient=True):
    """Admit observations in bounded batches.

    A documented transient refusal (queue_saturated) is retried while the
    publication catches up; any other refusal code is returned for the case to
    judge. This keeps CPU contention from masquerading as a defect without
    hiding a real refusal.
    """
    codes = []
    pending = list(observations)
    deadline = time.time() + 60.0
    while pending:
        batch = pending[:32]
        response = client.call("admit_batch", {"observations": batch})
        if not response.get("ok"):
            raise CheckFailure("admit_transport")
        batch_codes = (response.get("body") or {}).get("codes") or []
        if len(batch_codes) != len(batch):
            raise CheckFailure("admit_shape")
        retry = []
        for item, code in zip(batch, batch_codes):
            if code == "queue_saturated" and allow_transient and time.time() < deadline:
                retry.append(item)
                continue
            codes.append(code)
        pending = retry + pending[32:]
        if retry:
            client.checkpoint()
            time.sleep(0.05)
    return codes


def _durable(client):
    return ((client.status().get("body") or {}).get("durable_seq")) or 0


def await_durable(client, count, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _durable(client) >= count:
            return True
        client.checkpoint()
        time.sleep(0.02)
    return False


def _body(response):
    if not response.get("ok"):
        code = (response.get("error") or {}).get("code")
        raise CheckFailure(code or "query_failed")
    return response.get("body") or {}


def expect_error(client, code, view, **kwargs):
    """Assert a query is refused with the exact stable code."""
    try:
        _body(client.query(view, **kwargs))
    except CheckFailure as exc:
        if exc.code != code:
            raise
        return
    raise CheckFailure("expected_error_missing:" + code)


def row_by(client, view="timeline", **kwargs):
    body = _body(client.query(view, **kwargs))
    return body


def relation_status(rows, durable_seq, relation):
    for row in rows:
        if row.get("durable_seq") == durable_seq:
            block = (row.get("relations") or {}).get(relation) or {}
            return block.get("status")
    return None


def _count_rows(client, page_size=50, **filters):
    """Count every row a filtered timeline view returns, page by page."""
    total = 0
    cursor = None
    for _ in range(200):
        body = _body(client.query("timeline", page_size=page_size, cursor=cursor, **filters))
        rows = body["observations"]
        if not rows:
            break
        total += len(rows)
        cursor = body.get("next_cursor")
        if cursor is None:
            break
    return total


class ContractSuite(object):
    def __init__(self, root, frontend, native_build, evidence):
        self.root = root
        self.frontend = frontend
        self.native_build = native_build
        self.evidence = evidence
        self.cases = {}
        self.notes = {}
        self.order = list(REQUIRED_CASES)
        self.collectors = []
        self.processes = []
        self.logs = []
        self.report_extra = {}

    # -- fixtures -----------------------------------------------------------
    def collector(self, name, sock_dir=None, root_dir=None, **limits):
        root = root_dir if root_dir is not None else os.path.join(self.root, name)
        if sock_dir is None:
            sock = os.path.join(root, "collector.sock")
        else:
            # macOS sun_path is short; a fixture whose client cannot chdir to
            # the socket directory needs a short socket path even when the
            # archive root is long.
            sock = os.path.join(sock_dir, name + ".sock")
        os.makedirs(root, mode=0o700, exist_ok=True)
        start_collector(root, sock, **limits)
        client = Client(sock, timeout=10)
        client.set_policy("enabled", 0)
        self.collectors.append((root, sock))
        return client, root, sock

    def cleanup(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        for root, sock in self.collectors:
            stop_collector(root, sock)
        for sockdir in getattr(self, "socket_dirs", []):
            try:
                os.unlink(os.path.join(sockdir, "lm.sock"))
            except OSError:
                pass
            chain_sock = os.path.join(sockdir, "chain", "collector.sock")
            try:
                os.unlink(chain_sock)
            except OSError:
                pass

    def run(self):
        try:
            self._run_cases()
        finally:
            self.cleanup()

    def case(self, name, fn):
        if name in self.cases:
            return
        try:
            detail = fn() or {}
        except CheckFailure as exc:
            self.cases[name] = "fail"
            self.notes[name] = exc.code
        except Exception as exc:  # noqa: BLE001
            self.cases[name] = "fail"
            self.notes[name] = "internal_error:%s" % type(exc).__name__
        else:
            self.cases[name] = "pass"
            self.notes[name] = detail.get("note", "")

    def _run_cases(self):
        self.case("IdentityRelationsFixtures", self.c_identity_relations)
        self.case("ChoiceProjectionStages", self.c_choice_projection)
        self.case("TimingNumericFixtures", self.c_timing_numeric)
        self.case("OverviewHonestCounts", self.c_overview_honest)
        self.case("Scale256And4096", self.c_scale)
        self.case("HighFanoutProcessBounds", self.c_high_fanout)
        self.case("ConcurrentAppendAndRestartPrefix", self.c_concurrent_and_restart)
        self.case("QueryNeverProbesOrLoads", self.c_no_probe)
        self.case("FrontendTimingRealChain", self.c_frontend_chain)
        self.case("PrivacyCanaryAndAdapters", self.c_privacy_adapters)
        self.case("SourceBindingsAndReport", self.c_bindings)

    # -- C1 identity relations ---------------------------------------------
    def c_identity_relations(self):
        client, root, _sock = self.collector("identity")
        observations = [
            frame("start", 1, kind="start", update_id="u-id-1", commit_id="c-id-1"),
            frame(
                "frontend_update",
                2,
                update_id="u-id-2",
                parent_update_id="u-id-late",
                commit_id="c-id-1",
            ),
            frame(
                "frontend_update",
                3,
                source="ps-other",
                process="p-other",
                kind="commit_attempt",
                update_id="u-id-1",
                commit_id="c-id-1",
            ),
            frame("start", 4, source="ps-other", process="p-q192", kind="start", update_id="u-id-owner"),
            plugin_frame(
                5,
                association_role="engine_entry_context",
                association_read="claimed_valid",
                referenced_source_id="ps-q192",
                referenced_process_id="p-q192",
                referenced_update_id="u-id-2",
            ),
            plugin_frame(
                6,
                association_role="engine_entry_context",
                association_read="claimed_valid",
                referenced_source_id="ps-q192",
                referenced_process_id="p-q192",
                referenced_update_id="u-id-nowhere",
            ),
            plugin_frame(
                7,
                association_role="engine_entry_context",
                association_read="claimed_valid",
                referenced_source_id="ps-different",
                referenced_process_id="p-q192",
                referenced_update_id="u-id-1",
            ),
            plugin_frame(8, association_role="invalid", association_read="invalid"),
            plugin_frame(
                9,
                association_role="engine_entry_context",
                association_read="claimed_valid",
                referenced_source_id="ps-q192",
                referenced_process_id="p-q192",
            ),
            plugin_frame(
                10,
                association_role="engine_entry_context",
                association_read="claimed_valid",
                referenced_source_id="ps-q192",
                referenced_process_id="p-q192",
                referenced_update_id="u-id-2",
                plan_identity="plan-shared",
                lm_request_state="issued_succeeded",
                lm_request_id="req-shared",
            ),
            plugin_frame(
                11,
                association_role="engine_entry_context",
                association_read="claimed_valid",
                referenced_source_id="ps-q192",
                referenced_process_id="p-q192",
                referenced_update_id="u-id-2",
                plan_identity="plan-shared",
                lm_request_state="issued_succeeded",
                lm_request_id="req-second",
            ),
            daemon_request(12, "req-shared", "plan-shared"),
            daemon_request(13, "req-second", "plan-shared"),
            daemon_request(14, "req-disagree", "plan-a"),
            daemon_request(15, "req-disagree", "plan-b"),
        ]
        codes = _admit(client, observations)
        if any(code not in ("admitted", "duplicate") for code in codes):
            raise CheckFailure("admission:" + ",".join(codes))
        # A retry of the same capture identity is idempotent, not a second
        # observation and not a conflict.
        retry = _admit(client, [dict(observations[0])])
        if retry != ["duplicate"]:
            raise CheckFailure("idempotent_retry")
        conflict = _admit(
            client, [frame("start", 1, kind="start", payload={"text": "different-content"})]
        )
        if conflict != ["identity_conflict"]:
            raise CheckFailure("identity_conflict_admission")
        if not await_durable(client, 15):
            raise CheckFailure("durable_prefix")
        small = row_by(client, "timeline", page_size=50)
        rows = small["observations"]
        # Competing owners of one token are never merged into a valid identity;
        # equal text and different sources never link by text or time.
        if relation_status(rows, 1, "update_identity") != "conflicting":
            raise CheckFailure("competing_update_identity")
        if relation_status(rows, 2, "update_identity") != "valid":
            raise CheckFailure("own_update_identity")
        if relation_status(rows, 4, "process_identity") != "conflicting":
            raise CheckFailure("competing_process_identity")
        late_row = next(row for row in rows if row.get("durable_seq") == 2)
        if (late_row.get("relations") or {}).get("parent_reference", {}).get("status") != "unmatched":
            raise CheckFailure("late_parent_unresolved_at_snapshot")
        if (late_row.get("relations") or {}).get("parent_reference", {}).get("basis") != (
            "no_durable_record_with_this_token_at_prefix"
        ):
            raise CheckFailure("late_parent_basis")
        # Out-of-order: a later record resolves the missing relation at a
        # later prefix; the earlier snapshot is not rewritten.
        _admit(client, [frame("start", 16, kind="start", update_id="u-id-late")])
        if not await_durable(client, 16):
            raise CheckFailure("late_durable")
        later = row_by(client, "timeline", page_size=50)
        late_row_later = next(row for row in later["observations"] if row.get("durable_seq") == 2)
        if (late_row_later.get("relations") or {}).get("parent_reference", {}).get("status") != "valid":
            raise CheckFailure("late_parent_resolved_later")
        again = row_by(client, "timeline", page_size=50)
        for row in again["observations"]:
            if row.get("durable_seq") == 2:
                if (row.get("relations") or {}).get("parent_reference", {}).get("status") != "valid":
                    raise CheckFailure("snapshot_rewritten")
        # Association: valid, unmatched, stale, invalid, absent.
        checks = {
            5: "valid",
            6: "unmatched",
            7: "stale",
            8: "invalid",
            9: "unmatched",
        }
        for seq, expected in checks.items():
            status = relation_status(later["observations"], seq, "association")
            if status != expected:
                raise CheckFailure("association_%s:%s" % (seq, status))
        row5 = next(row for row in later["observations"] if row.get("durable_seq") == 5)
        evidence = (row5["relations"]["association"] or {}).get("evidence") or {}
        if evidence.get("proves_current_frontend_result") is not False:
            raise CheckFailure("entry_context_not_current_result")
        if evidence.get("witness_durable_seq") != 2:
            raise CheckFailure("witness_seq")
        # Request and plan collisions stay explicit; a unique native request id
        # with its own plan links.
        if relation_status(later["observations"], 10, "plan_identity") != "conflicting":
            raise CheckFailure("plan_conflict")
        if relation_status(later["observations"], 11, "plan_identity") != "conflicting":
            raise CheckFailure("plan_conflict_second")
        if relation_status(later["observations"], 10, "request_identity") != "linked":
            raise CheckFailure("request_link")
        if relation_status(later["observations"], 14, "request_identity") != "conflicting":
            raise CheckFailure("daemon_request_plan_conflict")
        if relation_status(later["observations"], 12, "request_identity") != "valid":
            raise CheckFailure("daemon_request_single_plan")
        if relation_status(later["observations"], 3, "update_identity") != "conflicting":
            raise CheckFailure("competing_update_second")
        # Records are unchanged: a re-read of the same prefix is identical.
        if json.dumps(later, sort_keys=True) != json.dumps(again, sort_keys=True):
            raise CheckFailure("records_changed")
        content_free(json.dumps(later), "identity_timeline")
        return {"note": "relations=13"}

    # -- C2 choice projection ----------------------------------------------
    def c_choice_projection(self):
        client, root, _sock = self.collector("choice")
        observations = [
            frame("frontend_update", 1, update_id="u-choice"),
            plugin_frame(
                2,
                window_id="win-a",
                group_id="grp-a",
                plugin_stage="competition",
                coverage="complete",
                coverage_basis="captured_group_members_and_target",
                target_membership="present",
                captured_candidate_count=4,
                group_member_count=4,
                apply_state="applied",
                submission="explicit",
                lm_request_state="issued_succeeded",
                lm_request_id="req-choice",
            ),
            plugin_frame(
                3,
                window_id="win-a",
                group_id="grp-a",
                plugin_stage="emission",
                emission_matches_upstream=False,
                apply_state="applied",
                order_changed=True,
            ),
            plugin_frame(
                4,
                window_id="win-b",
                group_id="grp-b",
                plugin_stage="competition",
                coverage="incomplete",
                coverage_basis="legacy_snapshot_complete",
                target_membership="present",
                captured_candidate_count=2,
                group_member_count=3,
            ),
            plugin_frame(
                5,
                window_id="win-b",
                group_id="grp-b",
                plugin_stage="emission",
                apply_state="unchanged",
            ),
            plugin_frame(
                6,
                window_id="win-c",
                group_id="grp-c",
                plugin_stage="competition",
                coverage="incomplete",
                target_membership="unknown",
                captured_candidate_count=2,
                group_member_count=2,
            ),
            plugin_frame(
                7,
                window_id="win-c",
                group_id="grp-c",
                plugin_stage="retraction",
                submission="unknown",
            ),
            plugin_frame(
                8,
                window_id="win-d",
                group_id="grp-d",
                plugin_stage="cancellation",
                submission="unknown",
                apply_state="fallback",
            ),
            plugin_frame(
                9,
                window_id="win-e",
                group_id="grp-e",
                plugin_stage="commit",
                submission="default",
                coverage="complete",
                coverage_basis="captured_group_members_and_target",
                target_membership="absent",
                captured_candidate_count=3,
                group_member_count=3,
            ),
        ]
        codes = _admit(client, observations)
        if any(code != "admitted" for code in codes):
            raise CheckFailure("admission")
        if not await_durable(client, 9):
            raise CheckFailure("durable")
        body = row_by(client, "choice", process_id="p-q192")
        groups = {group["group_id"]: group for group in body["groups"]}
        if set(groups) != {"grp-a", "grp-b", "grp-c", "grp-d", "grp-e"}:
            raise CheckFailure("group_set")
        a = groups["grp-a"]
        if not a["evidence_permitted"] or a["submission"] != "explicit":
            raise CheckFailure("group_a_evidence")
        if a["apply_state"] != "applied":
            raise CheckFailure("group_a_apply")
        if a["human_correctness_proof"] or a["ranking_benefit"]:
            raise CheckFailure("no_correctness_claim")
        b = groups["grp-b"]
        if b["coverage_claim_accepted"] or b["evidence_permitted"]:
            raise CheckFailure("legacy_complete_rejected")
        if b["coverage"] != "incomplete" or b["coverage_basis"] != "legacy_snapshot_complete":
            raise CheckFailure("submitted_coverage_kept")
        c = groups["grp-c"]
        if c["evidence_permitted"] or not c["retracted"]:
            raise CheckFailure("retraction_not_label")
        d = groups["grp-d"]
        if d["apply_state"] != "fallback" or d["evidence_permitted"]:
            raise CheckFailure("fallback_group")
        e = groups["grp-e"]
        if not e["evidence_permitted"] or e["submission"] != "default":
            raise CheckFailure("default_submission_weak")
        if "unselected" in json.dumps(body) and "not_negative" not in json.dumps(body):
            raise CheckFailure("unselected_label_rule")
        # A truncated-window marker cannot claim group-complete competition.
        forged = plugin_frame(
            10,
            window_id="win-f",
            group_id="grp-f",
            plugin_stage="competition",
            coverage="complete",
            coverage_basis="captured_group_members_and_target",
            target_membership="present",
            captured_candidate_count=2,
            group_member_count=2,
            truncated=True,
        )
        codes = _admit(client, [forged])
        if codes != ["invalid_request"]:
            raise CheckFailure("truncated_flag_refused")
        # A legacy complete claim is refused, never accepted as competition.
        legacy = plugin_frame(
            11,
            window_id="win-g",
            group_id="grp-g",
            plugin_stage="competition",
            coverage="complete",
            coverage_basis="legacy_snapshot_complete",
            target_membership="present",
            captured_candidate_count=2,
            group_member_count=2,
        )
        codes = _admit(client, [legacy])
        if codes != ["invalid_request"]:
            raise CheckFailure("legacy_complete_accepted")
        # Mixed span/category, target controls; a whole-window flag or a
        # candidate-count shortcut cannot claim completeness.
        codes = _admit(
            client,
            [
                plugin_frame(
                    12,
                    window_id="win-h",
                    group_id="grp-h",
                    plugin_stage="competition",
                    coverage="complete",
                    coverage_basis="whole_window_flag",
                    target_membership="present",
                    captured_candidate_count=4,
                    group_member_count=4,
                )
            ],
        )
        if codes != ["invalid_request"]:
            raise CheckFailure("whole_window_refused")
        content_free(json.dumps(body), "choice")
        return {"note": "groups=5"}

    # -- C3 timing ----------------------------------------------------------
    def c_timing_numeric(self):
        client, root, _sock = self.collector("timing")
        values = [10_000_000, 20_000_000, 30_000_000, 40_000_000]
        observations = [frame("frontend_update", 1, update_id="u-time")]
        sequence = 2
        for index, value in enumerate(values):
            entry = 1000
            endpoint = entry + value  # numer 1, denom 1 keeps hand math exact
            observations.append(
                frontend_timing_object(
                    sequence,
                    "act-%d" % index,
                    operation="key_update",
                    entry=entry,
                    endpoint_ticks=endpoint,
                    numer=1,
                    denom=1,
                )
            )
            sequence += 1
        observations.append(
            frontend_timing_object(
                sequence,
                "act-commit",
                operation="commit",
                entry=1000,
                endpoint_ticks=2000,
                numer=1,
                denom=1,
                endpoint="marked_text",
                commit_call={
                    "endpoint": "insert_text",
                    "start_ticks": 10,
                    "end_ticks": 30,
                    "duration_ns": 20,
                    "validity": "valid",
                },
            )
        )
        sequence += 1
        invalid_cases = []
        invalid_cases.append(("nonmonotone", frontend_timing_object(sequence, "bad-1", entry=500, endpoint_ticks=400, numer=1, denom=1, duration=1)))
        sequence += 1
        invalid_cases.append(("mismatch", frontend_timing_object(sequence, "bad-2", numer=1, denom=1, duration=1)))
        sequence += 1
        invalid_cases.append(("overflow", frontend_timing_object(sequence, "bad-3", entry=1, endpoint_ticks=(1 << 62), numer=(1 << 40), denom=1)))
        sequence += 1
        invalid_cases.append(("unavailable", frontend_timing_object(sequence, "bad-4", endpoint="unavailable", duration=5, entry=1, endpoint_ticks=2, numer=1, denom=1)))
        sequence += 1
        for _name, case in invalid_cases:
            observations.append(case)
        codes = _admit(client, observations)
        if any(code != "admitted" for code in codes):
            raise CheckFailure("admission:" + ",".join(codes))
        # Ill-typed structures are refused, not stored as zero.
        refused = []
        bool_case = frontend_timing_object(20, "bad-bool")
        bool_case["payload"]["frontend_timing"]["entry_ticks"] = True
        refused.append(("bool_entry", bool_case))
        negative = frontend_timing_object(21, "bad-negative")
        negative["payload"]["frontend_timing"]["duration_ns"] = -5
        refused.append(("negative_duration", negative))
        version_case = frontend_timing_object(22, "bad-version")
        version_case["payload"]["frontend_timing"]["version"] = 2
        refused.append(("version", version_case))
        nonfinite = frontend_timing_object(23, "bad-nonfinite")
        nonfinite["payload"]["frontend_timing"]["clock"]["timebase_numer"] = float("inf")
        refused.append(("nonfinite", nonfinite))
        unknown_field = frontend_timing_object(24, "bad-field")
        unknown_field["payload"]["frontend_timing"]["timebase_numer"] = 125
        refused.append(("unknown_field", unknown_field))
        for name, case in refused:
            codes = _admit(client, [case])
            if codes != ["invalid_request"]:
                raise CheckFailure("refusal_%s:%s" % (name, codes))
        # A valid standalone frontend interval with no backend phases is kept.
        if not await_durable(client, 6):
            raise CheckFailure("durable")
        timeline = row_by(client, "timeline", page_size=50)
        timing_rows = [
            row for row in timeline["observations"] if row.get("observation_kind") == "provenance"
        ]
        valid = [row for row in timing_rows if (row.get("frontend_timing") or {}).get("validity") == "valid"]
        if len(valid) != 5:
            raise CheckFailure("valid_samples:%d" % len(valid))
        key_valid = [row for row in valid if (row["frontend_timing"] or {}).get("operation") == "key_update"]
        if len(key_valid) != 4:
            raise CheckFailure("operation_split")
        timing = row_by(client, "timing")["operations"]
        key = next(bucket for bucket in timing if bucket["operation"] == "key_update")
        block = key["distributions"]["valid"]
        if block["count"] != 4:
            raise CheckFailure("count")
        if block["percentiles"] != {"p50": 20_000_000, "p95": 40_000_000, "p99": 40_000_000}:
            raise CheckFailure("percentiles:%s" % block["percentiles"])
        if not block["small_n"] or block["small_n_disclosure"] is None:
            raise CheckFailure("small_n")
        commit = next(bucket for bucket in timing if bucket["operation"] == "commit")
        commit_row = [row for row in valid if (row["frontend_timing"] or {}).get("operation") == "commit"][0]
        if commit_row["frontend_timing"]["commit_call_validity"] != "valid":
            raise CheckFailure("commit_call_separate")
        if commit["distributions"]["valid"]["count"] != 1:
            raise CheckFailure("commit_count")
        # Invalid and unknown samples keep explicit reasons and never become 0.
        invalid_rows = [row for row in timing_rows if (row.get("frontend_timing") or {}).get("validity") == "invalid"]
        reasons = {(row["frontend_timing"] or {}).get("unknown_reason") for row in invalid_rows}
        if not {"nonmonotone_endpoint", "declared_duration_mismatch", "unrepresentable_endpoint"}.issubset(reasons):
            raise CheckFailure("invalid_reasons:%s" % sorted(reasons))
        for row in invalid_rows:
            if (row["frontend_timing"] or {}).get("duration_ns") is not None:
                raise CheckFailure("invalid_has_duration")
        # Absent backend phases do not remove the frontend total.
        if any(row.get("daemon_stage") for row in timing_rows):
            raise CheckFailure("backend_mixed")
        content_free(json.dumps(timing_rows), "timing_rows")
        return {"note": "valid=5"}

    # -- C4 overview --------------------------------------------------------
    def c_overview_honest(self):
        client, root, sock = self.collector("overview")
        population = []
        for index in range(10):
            population.append(frame("frontend_update", index + 1, update_id="u-ov-%d" % index))
        population.append(frame("frontend_update", 1, update_id="u-ov-0"))
        population.append(frame("frontend_update", 11, source="ps-unknown-owner", process="p-unknown", payload={"text": CANARY_TEXT}))
        population.append(frame("frontend_update", 12))
        population.append(
            frame(
                "frontend_update",
                13,
                kind="commit_attempt",
                outcome="unavailable_client",
            )
        )
        population.append(
            {
                "envelope_version": 1,
                "content_version": 1,
                "observation_kind": "loss_notice",
                "source_instance_id": "ps-loss",
                "source_local_sequence": 1,
                "process_id": "p-loss",
                "schema_id": "unknown",
                "reason": "queue_saturated",
            }
        )
        population.append(
            {
                "envelope_version": 1,
                "content_version": 1,
                "observation_kind": "commit_attempt",
                "source_instance_id": "ps-q192",
                "source_local_sequence": 14,
                "process_id": "p-q192",
                "schema_id": "luna_pinyin",
                "eligibility": "excluded",
            }
        )
        codes = _admit(client, population)
        if any(code not in ("admitted", "duplicate") for code in codes):
            raise CheckFailure("admission:" + ",".join(codes))
        if codes.count("duplicate") != 1:
            raise CheckFailure("duplicate_retry_not_idempotent")
        if not await_durable(client, 15):
            raise CheckFailure("durable")
        first = _body(client.query("overview"))
        if first["population"]["observations"] != 15:
            raise CheckFailure("population:%s" % first["population"]["observations"])
        # The duplicate retry never became a durable row, so the eligible
        # population holds one unit per capture identity; the retry evidence
        # is the admission result, not a second row.
        if first["population"]["same_identity_retries_or_duplicates_collapsed"] != 0:
            raise CheckFailure("retry_double_counted")
        if first["population"]["unit"] != "source_instance_observation":
            raise CheckFailure("population_unit")
        kinds = {bucket["observation_kind"]: bucket for bucket in first["outcomes"]["kinds"]}
        if kinds.get("loss_notice", {}).get("observations") != 1:
            raise CheckFailure("loss_notice_count")
        if kinds.get("exclusion_notice", {}).get("observations") != 1:
            raise CheckFailure("exclusion_count")
        totals = first["stages"]["totals"]
        if totals["commit_attempts_unavailable_client"] != 1:
            raise CheckFailure("unavailable_client_outcome")
        if totals["commit_host_persistence_known"] != 0:
            raise CheckFailure("host_persistence_unknown")
        if first["stages"]["unknowns_retained"] is not True:
            raise CheckFailure("unknowns_retained")
        rates = first["stages"]["denominator_notes"]
        if "applied_unchanged is an applied plan" not in rates:
            raise CheckFailure("denominator_note")
        # One storage sample cannot fabricate a rate.
        if first["storage"]["growth"] is not None:
            raise CheckFailure("single_sample_rate")
        if first["storage"]["growth_unavailable_reason"] != "fewer_than_two_comparable_samples":
            raise CheckFailure("growth_reason")
        if first["storage"]["derived"]["index_rows"] < first["population"]["observations"]:
            raise CheckFailure("derived_index_under")
        if first["storage"]["managed"]["durable_bytes"] <= 0:
            raise CheckFailure("managed_bytes")
        if first["freshness"]["received_unpublished"] != 0:
            raise CheckFailure("pending_unpublished")
        if first["freshness"]["publication_state"] != "idle":
            raise CheckFailure("publication_state")
        if first["freshness"]["basis"] != "producer_poll_and_published_prefix":
            raise CheckFailure("freshness_basis")
        if first["slices"]["status"] != "not_observed":
            raise CheckFailure("slices_not_observed")
        if "application" not in first["slices"]["unknown_buckets"]:
            raise CheckFailure("slice_buckets")
        if first["quality"]["crash_tail"] != "none":
            raise CheckFailure("crash_tail_clean")
        # Pause state is reported as desired/effective separately.
        status = client.status()
        revision = (status.get("body") or {}).get("desired_revision")
        client.set_policy("paused", revision)
        paused = _body(client.query("overview"))
        if paused["quality"]["policy"]["desired"] != "paused":
            raise CheckFailure("pause_state")
        if paused["quality"]["policy"]["collector_effective"] != "paused":
            raise CheckFailure("pause_effective")
        if paused["quality"]["policy"]["globally_effective"] is not False:
            raise CheckFailure("globally_effective")
        client.set_policy("enabled", revision + 1)
        # Capacity stop is its own bucket in a dedicated small-capacity root,
        # and existing history there is untouched.
        small, small_root, small_sock = self.collector("overview-capacity", archive_capacity_bytes=4096)
        seeded = [frame("frontend_update", index + 1, process="p-cap", update_id="u-cap-%d" % index) for index in range(3)]
        codes = _admit(small, seeded)
        if any(code != "admitted" for code in codes):
            raise CheckFailure("capacity_seed")
        if not await_durable(small, 3):
            raise CheckFailure("capacity_seed_durable")
        before_bytes = _body(small.query("overview"))["storage"]["managed"]["durable_bytes"]
        fat = dict(frame("commit_attempt", 200, process="p-cap", update_id="u-fat"))
        fat["payload"] = {"text": "x" * 800}
        for index in range(20):
            item = dict(fat)
            item["source_local_sequence"] = 200 + index
            _admit(small, [item])
            small.checkpoint()
        capacity = _body(small.query("overview"))
        if not capacity["quality"]["capacity"]["capacity_stop"]:
            raise CheckFailure("capacity_stop_not_reported")
        after_bytes = capacity["storage"]["managed"]["durable_bytes"]
        if after_bytes < before_bytes or after_bytes <= 0:
            raise CheckFailure("capacity_lost_history")
        if capacity["quality"]["capacity"]["storage_failure"]:
            raise CheckFailure("false_storage_failure")
        if capacity["quality"]["capacity_refused_units"] < 1:
            raise CheckFailure("capacity_refusal_count")
        content_free(json.dumps(capacity), "overview")
        self.report_extra["overview_counts"] = {
            "observations": first["population"]["observations"],
            "loss_notice": kinds.get("loss_notice", {}).get("observations"),
            "exclusion": kinds.get("exclusion_notice", {}).get("observations"),
        }
        return {"note": "population=%d" % first["population"]["observations"]}

    # -- C5 scale -----------------------------------------------------------
    def _mixed_observations(self, count, high_fanout_updates=None, plugin_process=None):
        observations = []
        sequence = 0
        for index in range(count):
            sequence += 1
            kind = index % 5
            process = "p-scale" if kind != 1 else "p-fanout"
            update = "u-scale-%d" % (
                index if high_fanout_updates is None else (index % high_fanout_updates)
            )
            if kind == 0:
                observations.append(
                    frame(
                        "frontend_update",
                        sequence,
                        process=process,
                        update_id=update,
                        kind="commit_attempt",
                        payload={"text": CANARY_TEXT},
                    )
                )
            elif kind == 1:
                observations.append(
                    frame(
                        "frontend_update",
                        sequence,
                        source="ps-scale",
                        process="p-fanout",
                        update_id="u-fanout-%d" % (index % (high_fanout_updates or 1)),
                        kind="input_change",
                    )
                )
            elif kind == 2:
                observations.append(
                    plugin_frame(
                        sequence,
                        source="plug-scale",
                        process=plugin_process or process,
                        plugin_stage="competition",
                        window_id="win-scale-%d" % index,
                        group_id="grp-scale-%d" % index,
                        coverage="complete",
                        coverage_basis="captured_group_members_and_target",
                        target_membership="present",
                        captured_candidate_count=2,
                        group_member_count=2,
                    )
                )
            elif kind == 3:
                observations.append(
                    daemon_request(sequence, "req-scale-%d" % index, "plan-scale-%d" % index)
                )
            else:
                observations.append(
                    {
                        "envelope_version": 1,
                        "content_version": 1,
                        "observation_kind": "loss_notice",
                        "source_instance_id": "ps-loss",
                        "source_local_sequence": sequence,
                        "process_id": "p-loss",
                        "schema_id": "unknown",
                        "reason": "queue_saturated",
                    }
                )
        return observations

    def c_scale(self):
        results = {}
        for label, count in (("256", SCALE_SMALL), ("4096", SCALE_LARGE)):
            client, root, _sock = self.collector("scale-" + label)
            pid = _pid_of(root)
            before = rss_kb(pid)
            observations = self._mixed_observations(count)
            started = time.monotonic()
            codes = _admit(client, observations)
            if any(code not in ("admitted", "identity_conflict", "duplicate") for code in codes):
                raise CheckFailure("admission:" + label)
            if not await_durable(client, count, timeout=60):
                raise CheckFailure("durable:" + label)
            ingest_ms = int((time.monotonic() - started) * 1000)
            after = rss_kb(pid)
            query_started = time.monotonic()
            page_sizes = []
            cursor = ""
            total = 0
            seen = []
            for _ in range(400):
                body = _body(
                    client.query(
                        "timeline",
                        page_size=50,
                        cursor=cursor,
                    )
                )
                rows = body["observations"]
                if not rows:
                    break
                total += len(rows)
                page_sizes.append(len(rows))
                for row in rows:
                    seen.append(row["durable_seq"])
                cursor = body.get("next_cursor")
                if cursor is None:
                    break
                if len(rows) > 50:
                    raise CheckFailure("page_bound:" + label)
            query_ms = int((time.monotonic() - query_started) * 1000)
            if total != count or seen != sorted(seen) or len(set(seen)) != count:
                raise CheckFailure("iteration:%s:%s" % (label, total))
            if cursor is not None:
                raise CheckFailure("iteration_cursor")
            last_page = _body(client.query("timeline", page_size=5))
            if last_page["returned"] > 5:
                raise CheckFailure("page_max")
            expect_error(client, "page_bound", "timeline", page_size=51)
            results[label] = {
                "observations": count,
                "ingest_ms": ingest_ms,
                "query_all_ms": query_ms,
                "rss_kb_before": before,
                "rss_kb_after": after,
                "rss_delta_kb": after - before,
                "pages": len(page_sizes),
                "returned_total": total,
            }
        if results["4096"]["returned_total"] != SCALE_LARGE:
            raise CheckFailure("large_iteration")
        self.report_extra["scale"] = results
        return {"note": "256+4096 complete iteration"}

    # -- C6 high fanout -----------------------------------------------------
    def c_high_fanout(self):
        client, root, _sock = self.collector("fanout", query_choice_groups_max=16)
        observations = self._mixed_observations(
            1024, high_fanout_updates=512, plugin_process="p-fanout"
        )
        codes = _admit(client, observations)
        if any(code not in ("admitted", "identity_conflict", "duplicate") for code in codes):
            raise CheckFailure("admission")
        if not await_durable(client, 1024, timeout=45):
            raise CheckFailure("durable")
        page = _body(client.query("process", process_id="p-fanout", page_size=25))
        if page["returned"] > 25 or not page["has_more"]:
            raise CheckFailure("fanout_page_bound")
        row = page["observations"][0]
        if "payload" in row:
            raise CheckFailure("ordinary_payload")
        choice = _body(client.query("choice", process_id="p-fanout"))
        if not choice["groups_truncated"] or choice["groups_limit"] != 16:
            raise CheckFailure("choice_bound")
        if choice["groups_truncation_reason"] != "choice_group_bound":
            raise CheckFailure("truncation_reason")
        # A requested group is returned even beyond the truncation limit.
        only = _body(
            client.query("choice", process_id="p-fanout", group_id="grp-scale-937")
        )
        if only["group_id_filter"] != "grp-scale-937":
            raise CheckFailure("choice_group_filter")
        if only["groups_total"] != 1:
            raise CheckFailure("choice_group_scope")
        if only["groups"][0]["group_id"] != "grp-scale-937":
            raise CheckFailure("choice_group_identity")
        expect_error(
            client, "invalid_request", "choice", process_id="p-fanout", group_id="bad group"
        )
        expect_error(client, "invalid_request", "choice", process_id="bad group")
        # Cursor cannot silently cross filters, views or an unknown version.
        timeline = _body(client.query("timeline", page_size=10))
        token = timeline["cursor_token"]
        if timeline["returned"] != 10:
            raise CheckFailure("timeline_page")
        expect_error(
            client, "invalid_request", "timeline",
            page_size=10, process_id="p-fanout", cursor_token=token,
        )
        expect_error(client, "invalid_request", "overview", cursor_token=token)
        decoded = decode_cursor(token)
        if isinstance(decoded, str) or decoded.get("v") != QUERY_VERSION:
            raise CheckFailure("cursor_payload")
        expect_error(
            client, "unsupported_query_version", "timeline",
            cursor_token="q1.eyJ2Ijoid2VpcmQifQ",
        )
        continuation = _body(
            client.query("timeline", page_size=10, cursor=timeline["next_cursor"])
        )
        if continuation["observations"][0]["durable_seq"] <= timeline["observations"][-1]["durable_seq"]:
            raise CheckFailure("continuation_order")
        # A cursor token pins its snapshot: after new publications, continuing
        # the old token must not reveal records outside the named prefix.
        snapshot = _body(client.query("timeline", page_size=10))
        snapshot_seq = snapshot["as_of_durable_seq"]
        token = snapshot["cursor_token"]
        _admit(
            client,
            [
                frame("frontend_update", 9000 + index, process="p-late", update_id="u-late-%d" % index)
                for index in range(5)
            ],
        )
        if not await_durable(client, snapshot_seq + 5):
            raise CheckFailure("late_append")
        pinned = _body(
            client.query("timeline", page_size=50, cursor_token=token, cursor=None)
        )
        if pinned["as_of_durable_seq"] != snapshot_seq:
            raise CheckFailure("snapshot_watermark_drift")
        if any(row["durable_seq"] > snapshot_seq for row in pinned["observations"]):
            raise CheckFailure("snapshot_leak")
        for _ in range(20):
            page = _body(
                client.query(
                    "timeline",
                    page_size=10,
                    cursor_token=pinned["cursor_token"],
                    cursor=pinned["next_cursor"] or pinned["cursor"],
                )
            )
            if any(row["durable_seq"] > snapshot_seq for row in page["observations"]):
                raise CheckFailure("snapshot_leak_page")
            pinned = page
            if page.get("next_cursor") is None:
                break
        # Filtered aggregates count only the filtered rows.
        filtered_rows = _count_rows(client, source_instance_id="ps-scale")
        overview_filtered = _body(client.query("overview", source_instance_id="ps-scale"))
        if overview_filtered["population"]["observations"] != filtered_rows:
            raise CheckFailure("overview_filter_scope")
        if overview_filtered["population"]["observations"] >= _body(
            client.query("overview")
        )["population"]["observations"]:
            raise CheckFailure("overview_filter_noop")
        loss_rows = _count_rows(client, observation_kind="loss_notice")
        if loss_rows != _body(client.query("overview", observation_kind="loss_notice"))[
            "population"
        ]["observations"]:
            raise CheckFailure("overview_kind_filter")
        state_rows = _count_rows(client, state="unknown")
        if state_rows != _body(client.query("overview", state="unknown"))["population"][
            "observations"
        ]:
            raise CheckFailure("overview_state_filter")
        state_filtered = _body(client.query("timeline", page_size=10, state="unknown"))
        for row in state_filtered["observations"]:
            if (row.get("outcome") or "unknown") != "unknown":
                raise CheckFailure("state_filter")
        # A filter naming a field this archive never observes is refused.
        expect_error(client, "invalid_request", "timeline", application="com.example.app")
        expect_error(client, "invalid_request", "overview", application="com.example.app")
        expect_error(client, "invalid_request", "timeline", since_ms="not-a-number")
        early = _body(client.query("timeline", page_size=10, until_ms=1))
        if early["returned"] != 0:
            raise CheckFailure("time_filter_early")
        if "until_ms" not in early["filters_applied"]:
            raise CheckFailure("time_filter_echo")
        return {"note": "page_bound=25; snapshot pinned; filters scoped"}

    # -- C7 concurrent append and restart -----------------------------------
    def c_concurrent_and_restart(self):
        client, root, sock = self.collector("concurrent")
        codes = _admit(client, [frame("frontend_update", 1, update_id="u-c-1")])
        if codes != ["admitted"]:
            raise CheckFailure("seed")
        if not await_durable(client, 1):
            raise CheckFailure("seed_durable")
        snapshot = _body(client.query("timeline", page_size=50))
        snapshot_seq = snapshot["as_of_durable_seq"]
        # Concurrent append while a snapshot is being paged: the snapshot stays
        # at its prefix and the new record appears only in a later read.
        codes = _admit(client, [frame("frontend_update", 2, update_id="u-c-2")])
        if codes != ["admitted"]:
            raise CheckFailure("append")
        client.checkpoint()
        if await_durable(client, 2):
            pass
        again = _body(client.query("timeline", page_size=50))
        if again["observations"][0]["durable_seq"] != 1:
            raise CheckFailure("prefix_regression")
        # Held publication: the published prefix is unchanged during the hold
        # and a cursor naming the pending position is refused.
        hold_root = os.path.join(self.root, "concurrent-hold")
        hold_sock = os.path.join(hold_root, "collector.sock")
        fifo = os.path.join(self.root, "publication-hold.fifo")
        os.mkfifo(fifo, 0o600)
        os.makedirs(hold_root, mode=0o700)
        start_collector(hold_root, hold_sock, publication_hold=fifo)
        self.collectors.append((hold_root, hold_sock))
        hold_client = Client(hold_sock, timeout=10)
        hold_client.set_policy("enabled", 0)
        codes = _admit(hold_client, [frame("frontend_update", 1, process="p-hold")])
        if codes != ["admitted"]:
            raise CheckFailure("hold_admit")
        time.sleep(0.2)
        held = _body(hold_client.query("timeline", page_size=10))
        if held["returned"] != 0 or held["as_of_durable_seq"] != 0:
            raise CheckFailure("held_leaked")
        if held["cursor_token"] is None:
            raise CheckFailure("held_cursor")
        decoded = decode_cursor(held["cursor_token"])
        if decoded.get("as_of") != 0:
            raise CheckFailure("held_snapshot")
        # Post-admission known loss: while publication is held, a burst beyond
        # the collector queue is refused as queue_saturated and counted as a
        # known drop; a reference whose record was never published stays
        # unresolved rather than being reconstructed or silently linked. The
        # reference row is queued before the burst so it is published on
        # release while its target never is.
        reference = plugin_frame(
            1,
            source="plug-hold",
            process="p-hold",
            plugin_stage="commit",
            association_role="engine_entry_context",
            association_read="claimed_valid",
            referenced_source_id="ps-q192",
            referenced_process_id="p-hold",
            referenced_update_id="u-never-published",
        )
        codes = _admit(hold_client, [reference])
        if codes != ["admitted"]:
            raise CheckFailure("reference_admission")
        burst = [
            frame("frontend_update", 100 + index, process="p-hold", update_id="u-burst-%d" % index)
            for index in range(400)
        ]
        codes = _admit(hold_client, burst, allow_transient=False)
        dropped = sum(1 for code in codes if code == "queue_saturated")
        if dropped < 1:
            raise CheckFailure("known_loss_not_reported")
        overflow = _body(hold_client.query("overview"))
        if overflow["quality"]["known_dropped_units"] < 1:
            raise CheckFailure("known_drop_not_counted")
        if overflow["quality"]["loss_notice_relation"] is None:
            raise CheckFailure("loss_relation_statement")
        if overflow["quality"]["loss_notice_observations"] != 0:
            # A known drop is not automatically a loss-notice row.
            raise CheckFailure("loss_notice_conflated")
        hold_client.checkpoint()
        released = None
        with open(fifo, "w") as handle:
            handle.write("release\n")
        if not await_durable(hold_client, 2):
            raise CheckFailure("release_prefix")
        released = _body(hold_client.query("timeline", page_size=10))
        if released["returned"] < 2:
            raise CheckFailure("released_row")
        # Restart semantics: the published prefix survives, and a cursor from
        # the previous epoch is refused instead of silently crossing it.
        old_token = released["cursor_token"]
        stop_collector(hold_root, hold_sock)
        self.collectors = [item for item in self.collectors if item != (hold_root, hold_sock)]
        start_collector(hold_root, hold_sock)
        self.collectors.append((hold_root, hold_sock))
        restarted = Client(hold_sock, timeout=10)
        status = restarted.status().get("body") or {}
        durable_after = status.get("durable_seq")
        if not isinstance(durable_after, int) or durable_after < 2:
            raise CheckFailure("restart_prefix")
        if status.get("crash_tail") != "none":
            raise CheckFailure("clean_restart_tail:%s" % status.get("crash_tail"))
        expect_error(
            restarted, "cursor_snapshot_unknown", "timeline", cursor_token=old_token
        )
        reference_row = None
        cursor = ""
        for _ in range(20):
            page = _body(restarted.query("timeline", page_size=10, cursor=cursor or None))
            for row in page["observations"]:
                if row.get("observation_kind") == "plugin_observation":
                    reference_row = row
            cursor = page.get("next_cursor")
            if cursor is None:
                break
        if reference_row is None:
            raise CheckFailure("reference_row_missing")
        if (reference_row.get("relations") or {}).get("association", {}).get("status") != "unmatched":
            raise CheckFailure("post_admission_reference")
        content_free(json.dumps(released), "restart")
        return {"note": "held+restart prefix preserved; known loss counted"}

    # -- C8 no probe --------------------------------------------------------
    def c_no_probe(self):
        client, root, sock = self.collector("noprobe")
        codes = _admit(client, [frame("frontend_update", 1, update_id="u-np")])
        if codes != ["admitted"]:
            raise CheckFailure("seed")
        if not await_durable(client, 1):
            raise CheckFailure("durable")
        # Tripwire: any attempt to reach a scoring/health endpoint or load a
        # model would fail loudly here because the paths do not exist.
        probe_root = os.path.join(self.root, "probe-tripwire")
        os.makedirs(probe_root, mode=0o700)
        tripwire = os.path.join(probe_root, "scoring.sock")
        os.environ["LLM_RERANK_DAEMON_SOCKET"] = tripwire
        watchdog = time.monotonic() + WATCHDOG_MS / 1000.0
        for _ in range(5):
            _body(client.query("overview"))
            if os.path.lexists(tripwire):
                raise CheckFailure("query_probed")
            if time.monotonic() > watchdog:
                raise CheckFailure("query_watchdog")
        body = _body(client.query("daemon"))
        if body.get("live_probe") is not False or body.get("inference_dependency") is not False:
            raise CheckFailure("daemon_view_probe")
        if body["state"] not in ("unknown",):
            raise CheckFailure("daemon_state_guess")
        if body["freshness"] != "unavailable":
            raise CheckFailure("daemon_freshness")
        if body.get("unknown_reason") != "no_daemon_observations":
            raise CheckFailure("daemon_reason")
        self.processes = [proc for proc in self.processes if proc.poll() is None]
        del os.environ["LLM_RERANK_DAEMON_SOCKET"]
        return {"note": "no probe in %dms" % WATCHDOG_MS}

    # -- C9 real frontend chain --------------------------------------------
    def c_frontend_chain(self):
        if not self.frontend or not os.path.isdir(self.frontend):
            raise CheckFailure("frontend_missing")
        if not self.native_build or not os.path.isdir(self.native_build):
            raise CheckFailure("native_build_missing")
        work = os.path.join(self.root, "frontend")
        os.makedirs(work, mode=0o700)
        export = os.path.join(work, "frontend-export")
        head, tree = export_frontend(self.frontend, export)
        if tree != ACCEPTED_FRONTEND_TREE:
            raise CheckFailure("frontend_tree:%s" % tree)
        include_dir = os.path.join(work, "include")
        stage_librime_headers(self.frontend, include_dir)
        library_dir = os.path.join(self.native_build, "lib")
        if not os.path.isfile(os.path.join(library_dir, "librime.1.dylib")):
            raise CheckFailure("librime_dylib_missing")
        plugin_dylib = find_plugin_dylib(self.native_build)
        probes = os.path.join(work, "probes")
        binary = compile_frontend_harness(
            export,
            os.path.join(REPO, "tools", HARNESS_NAME),
            probes,
            library_dir,
            include_dir,
        )
        # The accepted frontend connects with the full path and refuses a
        # longer-than-sun_path socket instead of working around it, and the
        # collector requires its socket inside its own root. A root whose
        # fixture sockets would exceed the bound is refused explicitly here
        # rather than producing a confusing start failure.
        collector_sock = os.path.join(self.root, "frontend-chain", "collector.sock")
        daemon_sock = os.path.join(self.root, "frontend-chain", "daemon", "lm.sock")
        for candidate in (collector_sock, daemon_sock):
            if len(candidate.encode("utf-8")) >= 104:
                raise CheckFailure("socket_path_too_long_for_frontend")
        client, root, sock = self.collector("frontend-chain")
        shared = os.path.join(work, "shared")
        user = os.path.join(work, "user")
        log = os.path.join(work, "log")
        daemon_root = os.path.join(work, "daemon")
        facts = os.path.join(daemon_root, "facts")
        for path in (shared, user, log, daemon_root, facts):
            os.makedirs(path, mode=0o700)
        schema_socket = os.path.join(root, "daemon", "lm.sock")
        daemon = FixtureDaemon(work, schema_socket, archive_socket=sock, facts_root=facts)
        self.processes.append(daemon)
        daemon.wait_ready()
        write_frontend_schema(shared, user, sock, schema_socket)
        scenario_reports = {}
        report_dir = os.path.join(root, "reports")
        os.makedirs(report_dir, mode=0o700)
        scenarios = (
            "parity",
            "commit",
            "cancellation",
            "raw-finalization",
            "fallback",
            "success",
            "unavailable-client",
        )
        for scenario in scenarios:
            report_path = os.path.join(report_dir, "frontend-%s.json" % scenario)
            proc = subprocess.run(
                [
                    binary,
                    "--shared", shared,
                    "--user", user,
                    "--log", log,
                    "--socket", sock,
                    "--daemon-socket", schema_socket,
                    "--plugin-dylib", plugin_dylib,
                    "--scenario", scenario,
                    "--report", report_path,
                ],
                cwd=export,
                capture_output=True,
                text=True,
                timeout=600,
            )
            harness_log = proc.stdout + proc.stderr
            with open(os.path.join(work, "harness-%s.log" % scenario), "w") as handle:
                handle.write(harness_log)
            content_free(harness_log, "harness_log_" + scenario)
            report = {}
            if os.path.isfile(report_path):
                with open(report_path) as handle:
                    report = json.load(handle)
            if report.get("scenario", {}).get("scenario") != scenario:
                raise CheckFailure("harness_report_missing_%s" % scenario)
            if proc.returncode != 0:
                raise CheckFailure("harness_exit_%s:%s" % (scenario, proc.returncode))
            failures = report.get("failures") or []
            if failures:
                raise CheckFailure("harness_case_%s:%s" % (scenario, str(failures[0])[:30]))
            if report.get("substituted_compute") is not True:
                raise CheckFailure("substituted_disclosure")
            if report.get("cwd_unchanged") is not True:
                raise CheckFailure("harness_cwd")
            gate = report.get("secure_gate") or {}
            if gate.get("hook") != "forced_not_secure":
                raise CheckFailure("secure_gate_hook_%s" % gate.get("hook", "missing"))
            scenario_reports[scenario] = report
        parity = (scenario_reports.get("parity") or {}).get("parity") or {}
        if parity.get("inserts_equal") is not True or parity.get("marked_equal") is not True:
            raise CheckFailure("capture_parity")
        # The archive must eventually show the real chain: plugin emissions,
        # real frontend numeric timing rows and at least one linked request.
        deadline = time.time() + 20.0
        summary = None
        while time.time() < deadline:
            client.checkpoint()
            summary = self._chain_summary(client)
            if (
                summary["plugin_rows"] >= 1
                and summary["timing_rows"] >= 1
                and summary["linked"] >= 1
                and summary["issued_failed"] >= 1
            ):
                break
            time.sleep(0.25)
        if summary is None:
            raise CheckFailure("chain_summary")
        if summary["plugin_rows"] < 1:
            raise CheckFailure("plugin_rows:%d" % summary["plugin_rows"])
        if summary["plugin_stages"].get("emission", 0) < 1:
            # Candidate emission rows are the captured-candidate evidence of
            # the real chain, not a harness flag.
            raise CheckFailure("no_emission_rows")
        if summary["plugin_stages"].get("competition", 0) < 1:
            raise CheckFailure("no_competition_rows")
        if summary["timing_rows"] < 1:
            raise CheckFailure("timing_rows:%d" % summary["timing_rows"])
        if summary["linked"] < 1:
            raise CheckFailure("no_linked_request")
        if summary["issued_succeeded"] < 1 or summary["issued_failed"] < 1:
            raise CheckFailure(
                "exchange_controls:%d/%d" % (summary["issued_succeeded"], summary["issued_failed"])
            )
        if summary["daemon_requests"] < 1:
            raise CheckFailure("daemon_request_rows")
        self.report_extra["frontend"] = {
            "frontend_head": head,
            "frontend_tree": tree,
            "librime_dylib": os.path.join(library_dir, "librime.1.dylib"),
            "librime_sha256": sha256_file(os.path.join(library_dir, "librime.1.dylib")),
            "plugin_dylib": plugin_dylib,
            "plugin_sha256": sha256_file(plugin_dylib),
            "harness_sha256": sha256_file(binary),
            "linked_requests": summary["linked"],
            "timing_rows": summary["timing_rows"],
            "plugin_rows": summary["plugin_rows"],
            "plugin_stages": summary["plugin_stages"],
            "daemon_request_rows": summary["daemon_requests"],
            "exchange_success": summary["issued_succeeded"],
            "exchange_fallback": summary["issued_failed"],
            "scenario_reports": sorted(scenario_reports),
            "secure_gate": (scenario_reports.get("parity") or {}).get("secure_gate"),
            "runtime_fixture_note": (
                "the fixture chain root is a fresh owned runtime root under the"
                " checker root; the actionable evidence is this report and the"
                " harness logs"
            ),
            "substituted_compute": True,
        }
        return {
            "note": "linked=%d timing=%d plugin=%d"
            % (summary["linked"], summary["timing_rows"], summary["plugin_rows"])
        }

    def _chain_summary(self, client):
        summary = {
            "plugin_rows": 0,
            "timing_rows": 0,
            "linked": 0,
            "issued_succeeded": 0,
            "issued_failed": 0,
            "daemon_requests": 0,
            "plugin_stages": {},
        }
        cursor = ""
        for _ in range(200):
            body = _body(client.query("timeline", page_size=50, cursor=cursor or None))
            rows = body["observations"]
            if not rows:
                break
            for row in rows:
                relations = row.get("relations") or {}
                if row.get("observation_kind") == "plugin_observation":
                    summary["plugin_rows"] += 1
                    stage = row.get("plugin_stage")
                    if isinstance(stage, str):
                        summary["plugin_stages"][stage] = (
                            summary["plugin_stages"].get(stage, 0) + 1
                        )
                    state = row.get("lm_request_state")
                    if state == "issued_succeeded":
                        summary["issued_succeeded"] += 1
                    elif state == "issued_failed":
                        summary["issued_failed"] += 1
                    if (relations.get("request_identity") or {}).get("status") == "linked":
                        summary["linked"] += 1
                elif row.get("observation_kind") == "provenance":
                    timing = row.get("frontend_timing") or {}
                    if timing.get("validity") == "valid":
                        summary["timing_rows"] += 1
                elif row.get("observation_kind") == "daemon_observation":
                    if row.get("daemon_stage") == "request":
                        summary["daemon_requests"] += 1
            cursor = body.get("next_cursor")
            if cursor is None:
                break
        return summary

    # -- C10 privacy and adapters ------------------------------------------
    def c_privacy_adapters(self):
        client, root, sock = self.collector("privacy")
        codes = _admit(
            client,
            [
                frame("frontend_update", 1, update_id="u-priv", payload={"text": CANARY_TEXT}),
                frame(
                    "frontend_update",
                    2,
                    update_id="u-priv-2",
                    kind="unknown_outcome",
                    payload={"text": "ESC\x1b[31m\x1b[2J" + CANARY_TEXT},
                ),
                {
                    "envelope_version": 1,
                    "content_version": 1,
                    "observation_kind": "loss_notice",
                    "source_instance_id": "ps-priv",
                    "source_local_sequence": 3,
                    "process_id": "p-priv",
                    "schema_id": "unknown",
                    "reason": "queue_saturated",
                },
            ],
        )
        if any(code != "admitted" for code in codes):
            raise CheckFailure("admission:" + ",".join(codes))
        if not await_durable(client, 3):
            raise CheckFailure("durable")
        # Ordinary paths are content-free; the private detail is an opt-in and
        # its only content view.
        cli = run_cli(sock, "query", "timeline", "--page-size", "20")
        content_free(cli, "cli_timeline")
        cli_json = run_cli(sock, "--json", "query", "overview")
        content_free(cli_json, "cli_overview_json")
        errors = run_cli(sock, "query", "timeline", "--page-size", "999")
        if "page_bound" not in errors:
            raise CheckFailure("cli_error_code")
        content_free(errors, "cli_error")
        private = run_cli(
            sock, "query", "process", "--process-id", "p-q192", "--private-detail"
        )
        if CANARY not in private:
            raise CheckFailure("private_detail_absent")
        if "\x1b" in private.replace("\\u001b", ""):
            raise CheckFailure("raw_escape_emitted")
        if "\\u001b" not in private:
            raise CheckFailure("escape_not_rendered_as_data")
        # TUI parity: same shared Interface, same snapshot/filter semantics.
        tui_out = run_tui(sock, ["overview", "timeline", "timing", "quit"])
        content_free(tui_out, "tui")
        if "SCREEN overview" not in tui_out or "SCREEN timing" not in tui_out:
            raise CheckFailure("tui_views")
        if "frontend_timing_version=1" not in tui_out:
            raise CheckFailure("tui_timing")
        if "interface_version=input-archive-v1" not in tui_out:
            raise CheckFailure("tui_interface")
        # CLI and TUI agree on the same snapshot for the same query.
        cli_snapshot = run_cli_json(sock, "--json", "query", "timeline")
        parsed = json.loads(cli_snapshot)
        if parsed.get("body", {}).get("as_of_durable_seq") != 3:
            raise CheckFailure("cli_snapshot")
        return {"note": "ordinary content-free; private opt-in"}

    # -- C11 bindings and report -------------------------------------------
    def c_bindings(self):
        source = source_identity()
        runtime = runtime_identity()
        if not source.get("head") or not source.get("tree"):
            raise CheckFailure("source_identity")
        if not runtime.get("python"):
            raise CheckFailure("runtime_identity")
        bindings = {
            "query_version": QUERY_VERSION,
            "repo": REPO,
            "source": source,
            "runtime": runtime,
            "frontend": self.report_extra.get("frontend") or {
                "status": "frontend_case_did_not_pass",
            },
            "commands": COMMANDS_RUN,
        }
        self.report_extra["bindings"] = bindings
        return {"note": "bindings recorded"}

    def report(self, passed):
        skipped = [name for name in self.order if name not in self.cases]
        return {
            "checker": "check_input_archive_query",
            "contract": "AC-192-v1",
            "passed": bool(passed) and not skipped,
            "required_cases": list(self.order),
            "cases": self.cases,
            "notes": self.notes,
            "skipped": skipped,
            "watchdog_ms": WATCHDOG_MS,
            "substituted_compute": True,
            "substituted_compute_disclosure": (
                "the fixture daemon answers with a deterministic in-process"
                " scorer; this proves association/handler transport, not MLX"
                " phases or model performance"
            ),
            "latency_certification": False,
            "ranking_benefit": False,
            "host_persistence_proof": False,
            "five_view_complete": False,
            "merge_enables_capture": False,
            "content_included": False,
            **self.report_extra,
        }


# ---------------------------------------------------------------------------
# Frontend harness support


def export_frontend(frontend_root, destination):
    """Tracked export of the accepted read-only frontend at its exact tree."""
    head = git_rev(frontend_root, "rev-parse", "HEAD")
    os.makedirs(destination, mode=0o700)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", head],
        cwd=frontend_root,
        stdout=subprocess.PIPE,
        check=False,
    )
    if archive.returncode != 0:
        raise CheckFailure("frontend_export")
    extract = subprocess.run(
        ["tar", "-x", "-C", destination],
        input=archive.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if extract.returncode != 0:
        raise CheckFailure("frontend_extract")
    tree = git_rev(frontend_root, "rev-parse", head + "^{tree}")
    return head, tree


def stage_librime_headers(frontend_root, destination):
    headers = {
        "rime_api_stdbool.h": ("librime/dist/include/rime_api_stdbool.h", "librime/src/rime_api_stdbool.h"),
        "rime_api.h": ("librime/dist/include/rime_api.h", "librime/src/rime_api.h"),
        "rime/key_table.h": ("librime/dist/include/rime/key_table.h", "librime/src/rime/key_table.h"),
        "X11/keysymdef.h": ("librime/include/X11/keysymdef.h",),
        "X11/keysym.h": ("librime/include/X11/keysym.h",),
    }
    os.makedirs(destination, mode=0o700, exist_ok=True)
    for relative, candidates in headers.items():
        original = None
        for candidate in candidates:
            path = os.path.join(frontend_root, candidate)
            if os.path.isfile(path):
                original = path
                break
        if original is None:
            raise CheckFailure("librime_header_missing:" + relative)
        target = os.path.join(destination, relative)
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        shutil.copyfile(original, target)
        os.chmod(target, 0o600)


def find_plugin_dylib(native_build):
    candidates = [
        os.path.join(native_build, "lib", "rime-plugins", "librime-llm-rerank.dylib"),
        os.path.join(native_build, "lib", "librime-llm-rerank.dylib"),
        os.path.join(os.path.dirname(native_build), "release", "lib", "rime-plugins", "librime-llm-rerank.dylib"),
        os.path.join(os.path.dirname(native_build), "dist", "lib", "rime-plugins", "librime-llm-rerank.dylib"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.realpath(path)
    raise CheckFailure("plugin_dylib_missing")


def compile_frontend_harness(source_root, harness_path, probes_dir, library_dir, include_dir):
    os.makedirs(probes_dir, mode=0o700)
    app = os.path.join(probes_dir, "Harness.app", "Contents", "MacOS")
    os.makedirs(app, mode=0o700)
    plist = os.path.join(probes_dir, "Harness.app", "Contents", "Info.plist")
    with open(plist, "w") as handle:
        handle.write(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.ac192.harness</string>
<key>CFBundleExecutable</key><string>harness</string>
<key>CFBundleVersion</key><string>192</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
</dict></plist>
"""
        )
    os.chmod(plist, 0o600)
    # The harness source is a delivery artifact and is compiled together with
    # the read-only accepted frontend sources; it is copied into the export so
    # the swiftc invocation sees one self-contained tree.
    staged_harness = os.path.join(source_root, "probes")
    os.makedirs(staged_harness, mode=0o700, exist_ok=True)
    harness_target = os.path.join(staged_harness, HARNESS_NAME)
    shutil.copyfile(harness_path, harness_target)
    os.chmod(harness_target, 0o600)
    sources = sorted(
        os.path.join("sources", name)
        for name in os.listdir(os.path.join(source_root, "sources"))
        if name.endswith(".swift") and name != "Main.swift"
    )
    binary = os.path.abspath(os.path.join(app, "harness"))
    command = [
        "xcrun", "swiftc", "-parse-as-library", "-swift-version", "5",
        "-enable-bare-slash-regex", "-O",
        "-import-objc-header", "sources/Squirrel-Bridging-Header.h",
        "-I", os.path.abspath(include_dir), "-L", os.path.abspath(library_dir), "-lrime.1",
        "-Xlinker", "-rpath", "-Xlinker", os.path.abspath(library_dir),
        "-framework", "AppKit", "-framework", "InputMethodKit",
        "-framework", "Carbon", "-framework", "UserNotifications",
        "-framework", "CoreGraphics",
    ] + sources + [os.path.relpath(harness_target, source_root), "-o", binary]
    proc = subprocess.run(command, cwd=source_root, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise CheckFailure("harness_compile")
    os.chmod(binary, 0o700)
    return binary


def write_frontend_schema(shared, user, archive_socket, daemon_socket):
    default = """config_version: "0.1"
schema_list:
  - schema: luna_pinyin
switcher:
  fix_schema_list_order: true
menu:
  page_size: 5
"""
    schema = """schema:
  schema_id: luna_pinyin
  name: invented
  version: "1.0"
engine:
  processors:
    - ascii_composer
    - llm_rerank_recorder
    - speller
    - selector
    - express_editor
  segmentors:
    - ascii_segmentor
    - abc_segmentor
    - fallback_segmentor
  translators:
    - script_translator
  filters:
    - uniquifier
    - llm_rerank
speller:
  alphabet: zyxwvutsrqponmlkjihgfedcba
  delimiter: " '"
translator:
  dictionary: luna_pinyin
  enable_user_dict: false
menu:
  page_size: 5
llm_rerank:
  reranking_enabled: true
  recording_enabled: true
  evidence_enabled: false
  alpha: 1.0
  deadline_ms: 2000
  window: 32
  socket_path: %s
  input_archive:
    socket: %s
""" % (daemon_socket, archive_socket)
    dictionary = """---
name: luna_pinyin
version: "1.0"
sort: by_weight
...
你\tni\t100
泥\tni\t90
呢\tni\t80
拟\tni\t70
逆\tni\t60
腻\tni\t50
尼\tni\t40
倪\tni\t30
好\thao\t100
号\thao\t90
豪\thao\t80
你好\tnihao\t80
拟好\tnihao\t70
甲正\tjiazheng\t100
甲斥\tjiachi\t90
甲敏\tjiamin\t80
refusex\tre\t100
refusey\tre\t90
"""
    with open(os.path.join(shared, "default.yaml"), "w") as handle:
        handle.write(default)
    with open(os.path.join(shared, "luna_pinyin.schema.yaml"), "w") as handle:
        handle.write(schema)
    with open(os.path.join(shared, "luna_pinyin.dict.yaml"), "w") as handle:
        handle.write(dictionary)
    with open(os.path.join(user, "squirrel.yaml"), "w") as handle:
        handle.write(
            "config_version: \"1\"\ninput_archive:\n  socket: \"%s\"\nstyle:\n  inline_preedit: true\n"
            % archive_socket
        )
    for path in (
        os.path.join(shared, "default.yaml"),
        os.path.join(shared, "luna_pinyin.schema.yaml"),
        os.path.join(shared, "luna_pinyin.dict.yaml"),
        os.path.join(user, "squirrel.yaml"),
    ):
        os.chmod(path, 0o600)


FIXTURE_TRIGGERS = {
    # The fixture daemon fails the exchange whose first candidate is 好, so the
    # plugin keeps a failed issuance and falls back; the 你/你好 inputs answer
    # with substituted scores.
    "好": "raise",
    "fixture-mismatch": "mismatch",
}


def _fixture_daemon_main(argv):
    sys.path.insert(0, DAEMON_DIR)
    import server
    from server import ModelState

    class FixtureState(ModelState):
        def __init__(self):
            super().__init__("fixture-model", adapter_path="")

        def _load_base_model(self):
            class _Tokenizer:
                pad_token_id = 1
                eos_token_id = 1

            self.model = object()
            self.tokenizer = _Tokenizer()
            self.pad_id = 1

        def score(self, context, candidates):
            self.load()
            trigger = candidates[0] if candidates else ""
            behavior = FIXTURE_TRIGGERS.get(trigger)
            if behavior == "raise":
                raise RuntimeError("fixture scoring failure")
            if behavior == "mismatch":
                return []
            return [-(index + 1) * 0.25 for index in range(len(candidates))]

    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-daemon", action="store_true")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--archive-socket", default="")
    parser.add_argument("--facts-root", required=True)
    args = parser.parse_args(argv)
    server.IDLE_TIMEOUT = 300.0
    state = FixtureState()
    server.run_server(
        args.socket,
        "fixture-model",
        cache_limit_mb=0,
        test_mode=False,
        facts_root=args.facts_root,
        archive_socket=args.archive_socket,
        state=state,
    )
    return 0


class FixtureDaemon(object):
    def __init__(self, work, sock, archive_socket="", facts_root=""):
        self.sock = sock
        self.log_path = os.path.join(work, "fixture-daemon.log")
        self.log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                os.path.abspath(__file__),
                "--fixture-daemon",
                "--socket", sock,
                "--archive-socket", archive_socket,
                "--facts-root", facts_root,
            ],
            cwd=REPO,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise CheckFailure("fixture_daemon_exit")
            if os.path.lexists(self.sock):
                return True
            time.sleep(0.05)
        raise CheckFailure("fixture_daemon_not_ready")

    def poll(self):
        return self.proc.poll()

    def terminate(self):
        if self.proc.poll() is None:
            self.proc.terminate()

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()

    def wait(self, timeout=None):
        return self.proc.wait(timeout)


def run_cli(sock, *args):
    proc = subprocess.run(
        collector_command("", sock, *args),
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.stdout + proc.stderr


def run_cli_json(sock, *args):
    """Stdout only: the JSON surface must not be mixed with diagnostics."""
    proc = subprocess.run(
        collector_command("", sock, *args),
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.stdout


def run_tui(sock, commands):
    proc = subprocess.Popen(
        collector_command("", sock, "tui"),
        cwd=REPO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    out, _ = proc.communicate("\n".join(commands) + "\n", timeout=120)
    return out


def source_identity():
    payload = {
        "head": git_rev(REPO, "rev-parse", "HEAD"),
        "tree": git_rev(REPO, "rev-parse", "HEAD^{tree}"),
        "dirty": git_rev(REPO, "status", "--porcelain", "--untracked-files=no"),
    }
    return payload


def runtime_identity():
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "sqlite3": _sqlite_version(),
        "swiftc": _command_version(["xcrun", "swiftc", "--version"]),
    }


def _sqlite_version():
    try:
        import sqlite3

        return sqlite3.sqlite_version
    except Exception:
        return "unavailable"


def _command_version(command):
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
        return output.strip().splitlines()[0]
    except Exception:
        return "unavailable"


COMMANDS_RUN = [
    "python3 tools/check_input_archive_query.py --self-test --root <fresh>",
    "python3 tools/check_input_archive_query.py --suite contract --frontend <HOST>"
    " --native-build <HOST>/librime/build --root <fresh> --report <evidence>/query.json",
]


def self_test(root):
    os.makedirs(root, mode=0o700)
    # Percentile arithmetic is hand-computable at the frozen method.
    block = percentiles([10, 20, 30, 40])
    if block["percentiles"] != {"p50": 20, "p95": 40, "p99": 40}:
        raise CheckFailure("SelfTestPercentiles")
    if block["count"] != 4 or not block["small_n"]:
        raise CheckFailure("SelfTestPercentiles")
    from archive.querying import canonical_frontend_timing, conversion_ns, interval_ns

    timing, reason = canonical_frontend_timing(
        {
            "version": 1,
            "action_id": "act-1",
            "action": "key_handler",
            "operation": "key_update",
            "clock": {
                "domain": "mach_absolute_time",
                "unit": "nanoseconds",
                "timebase_numer": 125,
                "timebase_denom": 3,
            },
            "event_queue_wait": "unknown",
            "nested_actions": 0,
            "continuity_cut": False,
            "association": {"source_instance_id": "ps-1", "process_id": "p-1"},
            "update_calls": [{"endpoint": "marked_text", "ticks": 3000}],
            "endpoint": "marked_text",
            "entry_ticks": 1000,
            "endpoint_ticks": 3000,
            "duration_ns": 83333,
            "validity": "valid",
        }
    )
    if reason is not None or timing["validity"] != "valid":
        raise CheckFailure("SelfTestTimingCanonical")
    if interval_ns(1000, 3000, 125, 3) != 83333:
        raise CheckFailure("SelfTestTimingCanonical")
    if conversion_ns((1 << 62), (1 << 40), 1) is not None:
        raise CheckFailure("SelfTestTimingCanonical overflow")
    # A declared duration that disagrees with the ticks is stored as invalid,
    # never as a successful sample.
    forged, forged_reason = canonical_frontend_timing(
        {
            "version": 1,
            "action_id": "act-1",
            "action": "key_handler",
            "clock": {
                "domain": "mach_absolute_time",
                "unit": "nanoseconds",
                "timebase_numer": 1,
                "timebase_denom": 1,
            },
            "endpoint": "marked_text",
            "entry_ticks": 10,
            "endpoint_ticks": 20,
            "duration_ns": 1,
        }
    )
    if forged_reason is not None or forged["validity"] != "invalid":
        raise CheckFailure("SelfTestTimingForgedDuration")
    if forged["unknown_reason"] != "declared_duration_mismatch":
        raise CheckFailure("SelfTestTimingForgedDuration")
    if not _cursor_token_probe():
        raise CheckFailure("SelfTestCursor")
    print("self-test passed")
    return 0


def _cursor_token_probe():
    from archive.querying import encode_cursor, decode_cursor as decode

    token = encode_cursor("timeline", {"process_id": None}, 5, "epoch-1")
    decoded = decode(token)
    if isinstance(decoded, str) or decoded.get("as_of") != 5:
        return ""
    if decode("q1.%%%") != "invalid_request":
        return ""
    return token


def main(argv):
    parser = argparse.ArgumentParser(description="Input-archive query Interface checker")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract",))
    parser.add_argument("--frontend", default="")
    parser.add_argument("--native-build", default="")
    parser.add_argument("--root", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            if not args.root:
                raise CheckFailure("invalid_request")
            if os.path.lexists(args.root):
                # A self-test root must be fresh; an existing root is refused
                # with a stable code instead of a traceback.
                raise CheckFailure("root_not_fresh")
            return self_test(args.root)
        if args.suite == "contract":
            if not args.root or not args.report:
                raise CheckFailure("invalid_request")
            if os.path.lexists(args.root):
                raise CheckFailure("root_not_fresh")
            os.makedirs(os.path.dirname(os.path.abspath(args.report)), mode=0o700, exist_ok=True)
            evidence = os.path.dirname(os.path.abspath(args.report))
            os.makedirs(args.root, mode=0o700)
            suite = ContractSuite(args.root, args.frontend, args.native_build, evidence)
            suite.run()
            passed = all(state == "pass" for state in suite.cases.values()) and set(
                suite.cases
            ) == set(suite.order)
            report = suite.report(passed)
            with open(args.report, "w") as handle:
                json.dump(report, handle, sort_keys=True, indent=2)
                handle.write("\n")
            os.chmod(args.report, 0o600)
            content_free(json.dumps(report), "report")
            if not passed:
                sys.stderr.write(
                    json.dumps({name: suite.cases.get(name) for name in suite.order}) + "\n"
                )
                return 1
            print("contract passed")
            return 0
        raise CheckFailure("invalid_request")
    except CheckFailure as exc:
        sys.stderr.write("code=%s\n" % exc.code)
        return 1


if __name__ == "__main__":
    if "--fixture-daemon" in sys.argv:
        sys.exit(_fixture_daemon_main(sys.argv[1:]))
    sys.exit(main(sys.argv[1:]))
