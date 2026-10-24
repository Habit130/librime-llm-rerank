#!/usr/bin/env python3
"""Finite AC-193-v1 model-free checks over real collector/Interface/Adapters.

All fixtures are invented and retained in owner-only roots. Reports contain
identities/counts, not source, target or note text. Fault injection is confined
to an owned subprocess launcher, never a production producer input path.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import sqlite3
import subprocess
import sys
import time
import tracemalloc

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from archive.annotations import (ANNOTATION_VERSION, LINE_BYTES, NOTE_BYTES, TEXT_BYTES, normalize_edit)
from archive.interface import InterfaceError, strip_content
from archive_fixture_client import RegisteredFixtureClient as Client
from archive.safety import assert_private_tree, atomic_write
from archive.tui import TuiSession
from check_input_archive_query import frame, plugin_frame, _admit


def plugin(sequence, stage, **extra):
    return plugin_frame(sequence, stage=stage, **extra)

REQUIRED_CASES = (
    "ExactReferencesAndImmutableSources", "FourKindsAndLabelProvenance",
    "ConcurrentCASAndIdempotency", "PinnedReadsAndConsumer",
    "DurabilityFaultsAndRestart", "MalformedIncompatibleState",
    "Scale256And4096", "HighRevisionAndSourceIncarnations",
    "BoundsVersionsAndCursors", "ConcurrentCapture",
    "CLIAndTUIPrivacyAndErrors", "AliasesPermissionsAndNoProbe",
)
CANARY = "ANN193CANARY"
TEXT = "安" + CANARY + "\x1b[31m\n\x85"
REPLACEMENT = "改" + CANARY

LAUNCHER = r'''
import importlib.abc, os, socket, sys
class NoModel(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mlx', 'mlx_lm') or 'health_probe' in fullname:
            os.write(2, b'forbidden_probe=true\n')
            raise RuntimeError('forbidden_probe')
sys.meta_path.insert(0, NoModel())
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
def guard(self, address, original):
    if self.family != socket.AF_UNIX:
        os.write(2, b'forbidden_probe=true\n')
        raise RuntimeError('forbidden_probe')
    return original(self, address)
socket.socket.connect = lambda self, address: guard(self, address, original_connect)
socket.socket.connect_ex = lambda self, address: guard(self, address, original_connect_ex)
from archive.annotations import AnnotationStore
from archive.collector import Collector, main
fault = os.environ.get('ANN193_FAULT', '')
if fault in ('before', 'crash_before', 'crash_after'):
    original = AnnotationStore._publish
    def publish(self, state):
        if fault == 'crash_before': os._exit(71)
        if fault == 'crash_after':
            original(self, state)
            os._exit(72)
        raise OSError('injected')
    AnnotationStore._publish = publish
if fault == 'disk':
    def append(self, raw): raise OSError('injected')
    AnnotationStore._append = append
if fault == 'lost_reply':
    original_send = Collector._send
    def send(self, conn, response, page_bounded=False):
        if response.get('op') == 'annotation_edit' and response.get('ok') and not response['body'].get('replayed'):
            return
        return original_send(self, conn, response, page_bounded)
    Collector._send = send
sys.exit(main())
'''


class CheckFailure(Exception):
    pass


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


def body(response):
    require(response.get("ok") is True, (response.get("error") or {}).get("code", "response_failed"))
    return response["body"]


def error(response, code):
    require(not response.get("ok") and response.get("error", {}).get("code") == code, "wrong_error:" + code)


def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for raw in iter(lambda: handle.read(1048576), b""):
            h.update(raw)
    return h.hexdigest()


def no_private(raw):
    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False)
    require(CANARY not in raw and "\\u5b89" not in raw and "\\u6539" not in raw, "private_output")
    require("\x1b" not in raw and "\x85" not in raw, "terminal_escape")


class Fixture:
    def __init__(self, root, fault="", limits=()):
        self.root = Path(root)
        self.socket = str(self.root / "s")
        self.client = Client(self.socket, timeout=5)
        self.proc = None
        self.run = 0
        self.start(fault, limits)

    def start(self, fault="", limits=()):
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.run += 1
        self.out = open(self.root / ("launch-%s.out" % self.run), "xb")
        self.err = open(self.root / ("launch-%s.err" % self.run), "xb")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ANN193_FAULT=fault)
        self.argv = [sys.executable, "-c", LAUNCHER, "--root", str(self.root), "--socket", self.socket, "--no-auto-checkpoint", *limits]
        self.proc = subprocess.Popen(self.argv, cwd=REPO, env=env, stdout=self.out, stderr=self.err, start_new_session=True, restore_signals=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.proc.poll() is None:
            if self.client.status().get("ok"):
                return
            time.sleep(.02)
        raise CheckFailure("collector_start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.client.shutdown()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(10)
        if self.proc:
            self.out.close()
            self.err.close()
        self.proc = None

    def restart(self, fault=""):
        self.stop()
        self.start(fault)

    def seed(self, observations):
        current = body(self.client.status())
        body(self.client.set_policy("enabled", current["desired_revision"]))
        codes = _admit(self.client, observations)
        require(all(code in ("admitted", "duplicate") for code in codes), "fixture_admission")
        body(self.client.checkpoint())
        current = body(self.client.status())
        body(self.client.set_policy("off", current["desired_revision"]))

    def refs(self):
        result = []
        response = body(self.client.annotations(page_size=50))
        snapshot = (response["as_of_durable_seq"], response["annotation_revision"])
        while True:
            result.extend(row["source_reference"] for row in response["observations"])
            if not response["next_cursor"]:
                return result, snapshot
            response = body(self.client.annotations(cursor_token=response["next_cursor"], page_size=50))
            require(snapshot == (response["as_of_durable_seq"], response["annotation_revision"]), "cursor_snapshot")

    def edit(self, ref, kind, value, revision, operation):
        return self.client.annotate(ref, kind, value, revision, operation)

    def row(self, ref, **kwargs):
        return body(self.client.annotations(source_reference=ref, **kwargs))["observations"][0]


def observations():
    return [frame("commit", 1, source="ann-a", process="same-process", payload={"text": TEXT}), frame("commit", 1, source="ann-b", process="same-process", payload={"text": TEXT})]


def exact(f):
    f.seed(observations())
    refs, pair = f.refs()
    require(len(refs) == 2 and refs[0] != refs[1], "source_incarnation")
    raw_hash = hash_file(f.root / "observations.jsonl")
    body(f.edit(refs[0], "correct", {"text": REPLACEMENT}, 0, "exact-1"))
    require(f.row(refs[1])["target_provenance"] == "observed_submission_unknown", "same_text_retarget")
    for replacement, expected in (({"archive_id": "a" * 32}, "annotation_foreign_archive"), ({"source_instance_id": "missing"}, "not_found"), ({"source_local_sequence": 9999}, "not_found"), ({"record_digest": "a" * 64}, "annotation_source_mismatch"), ({"durable_seq": 2}, "annotation_source_mismatch")):
        error(f.edit({**refs[0], **replacement}, "confirm", {}, 1, "bad-ref"), expected)
    status = body(f.client.status())
    body(f.client.set_policy("enabled", status["desired_revision"]))
    require(_admit(f.client, [frame("commit", 100, source="pending")]) == ["admitted"], "pending_admit")
    error(f.edit({**refs[0], "source_instance_id": "pending", "source_local_sequence": 100}, "confirm", {}, 1, "unpublished"), "not_found")
    # Stop will publish pending source work, so compare the old complete prefix
    # before and after annotation only, then independently hash around restart.
    require(raw_hash == hash_file(f.root / "observations.jsonl"), "annotation_changed_source")
    body(f.client.checkpoint())
    raw_hash = hash_file(f.root / "observations.jsonl")
    f.restart()
    require(raw_hash == hash_file(f.root / "observations.jsonl"), "restart_changed_source")
    require(f.row(refs[0], private_detail=True)["private_values"]["observed_target"] == TEXT, "original_target_changed")
    return {"distinct_sources": 2, "reference_refusals": 6, "unchanged_source_sha256": raw_hash}


def kinds(f):
    frames = [plugin(1, "commit", source_instance_id="explicit", process_id="p-explicit", window_id="w", group_id="g", submission="explicit", target_membership="present", coverage="complete", coverage_basis="captured_group_members_and_target", captured_candidate_count=1, group_member_count=1, payload={"text": TEXT}), plugin(1, "commit", source_instance_id="default", process_id="p-default", window_id="w", group_id="g", submission="default", payload={"text": TEXT})]
    for index, kind in enumerate(("cancellation", "replacement", "raw_finalization", "unavailable_client", "unknown_outcome", "temporary_selection"), 10):
        frames.append(frame("stage", index, kind=kind, payload={"text": TEXT}))
    frames.append(plugin(2, "retraction", source_instance_id="explicit", process_id="p-explicit", window_id="w", group_id="g"))
    f.seed(frames)
    refs, pair = f.refs()
    active = f.row(refs[0], as_of_durable_seq=2)
    require(active["ranking_evaluation"]["evidence_eligible"], "complete_observed_choice_ineligible")
    require(not f.row(refs[0])["ranking_evaluation"]["evidence_eligible"], "retraction_positive")
    require(f.row(refs[0])["target_provenance"] == "observed_explicit_preference", "explicit_provenance")
    require(f.row(refs[1])["target_provenance"] == "observed_default_weak", "default_provenance")
    for ref in refs[2:]:
        error(f.edit(ref, "confirm", {}, 0, "confirm-unavailable"), "annotation_target_unavailable")
        row = f.row(ref)
        require(not row["target_available"] and not row["ranking_evaluation"]["evidence_eligible"], "implicit_label")
    revision = 0
    for op, kind, value in (("confirm", "confirm", {}), ("correct1", "correct", {"text": REPLACEMENT}), ("correct2", "correct", {"text": REPLACEMENT + "2"}), ("exclude", "exclude", {"reason": "private"}), ("experience", "experience", {"kind": "candidate_issue", "value": "major", "note": TEXT})):
        revision += 1
        ack = body(f.edit(refs[0], kind, value, revision - 1, op))
        require(ack["durable"] and ack["annotation_revision"] == revision, "kind_ack")
    row = f.row(refs[0], private_detail=True)
    require(row["private_values"]["effective_target"] == REPLACEMENT + "2" and row["private_values"]["observed_target"] == TEXT, "correction_history")
    require(row["excluded"] and row["experience"]["value"] == "major", "independent_experience")
    require(not row["ranking_evaluation"]["evidence_eligible"] and row["corrected_target_membership"] == "not_asserted" and row["language_material"]["admission"] == "not_decided", "admission_shortcut")
    require(f.row(refs[0], annotation_revision=1)["target_provenance"] == "human_reviewed", "confirm_history")
    corrected = f.row(refs[0], annotation_revision=2, as_of_durable_seq=2)
    require(not corrected["ranking_evaluation"]["evidence_eligible"] and corrected["ranking_evaluation"]["observed_choice"]["completeness"]["complete"], "correction_fabricated_choice")
    no_private(f.row(refs[0]))
    return {"operations": 5, "non_target_controls": 7, "final_revision": revision}


def concurrent(f):
    f.seed(observations())
    ref = f.refs()[0][0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda op: f.edit(ref, "correct", {"text": REPLACEMENT}, 0, op), ("client-a", "client-b")))
    require(sum(response.get("ok", False) for response in results) == 1, "cas_winners")
    loser = next(r for r in results if not r.get("ok"))
    error(loser, "annotation_stale_revision")
    winner = "client-a" if results[0].get("ok") else "client-b"
    ack = body(f.edit(ref, "correct", {"text": REPLACEMENT}, 0, winner))
    require(ack["replayed"] and ack["annotation_revision"] == 1, "idempotency")
    error(f.edit(ref, "correct", {"text": TEXT}, 0, winner), "annotation_operation_conflict")
    body(f.edit(ref, "correct", {"text": TEXT}, 1, "deliberate"))
    require(f.row(ref, annotation_revision=1, private_detail=True)["private_values"]["effective_target"] == REPLACEMENT, "old_revision_lost")
    return {"winners": 1, "stale_losers": 1, "replayed_revision": 1}


def pinned(f):
    f.seed(observations())
    ref = f.refs()[0][0]
    body(f.edit(ref, "correct", {"text": REPLACEMENT}, 0, "pin-1"))
    before = body(f.client.annotations(source_reference=ref, annotation_revision=1, as_of_durable_seq=2, private_detail=True))
    old = body(f.client.query("timeline", page_size=1))
    body(f.edit(ref, "exclude", {"reason": "sensitive"}, 1, "pin-2"))
    old_again = body(f.client.query("timeline", page_size=1))
    require(old == old_again, "unannotated_query_changed")
    f.restart()
    after = body(f.client.annotations(source_reference=ref, annotation_revision=1, as_of_durable_seq=2, private_detail=True))
    require(before == after, "pinned_pair_changed")
    # A downstream mock consumes only this Interface response: no file reads,
    # target joins or reconstructed completeness in the consumer.
    row = after["observations"][0]
    consumer = (row["private_values"]["effective_target"], row["target_provenance"], row["excluded"], row["language_material"]["admission"], row["ranking_evaluation"]["evidence_eligible"])
    require(consumer == (REPLACEMENT, "human_corrected", False, "not_decided", False), "consumer_projection")
    require(f.row(ref)["excluded"], "latest_exclusion_missing")
    return {"pinned_pair": [2, 1], "same_after_restart": True, "consumer_joins": 0}


def fault_cases(root):
    results = []
    for fault in ("before", "disk", "lost_reply", "crash_before", "crash_after"):
        f = Fixture(root / fault)
        try:
            f.seed(observations())
            ref = f.refs()[0][0]
            policy_before = body(f.client.status())["desired_revision"]
            source_hash = hash_file(f.root / "observations.jsonl")
            f.restart(fault)
            response = f.edit(ref, "correct", {"text": REPLACEMENT}, 0, "fault-op")
            require(not response.get("ok"), "false_durable_success")
            if fault in ("before", "disk"):
                error(f.client.annotations(), "annotation_state_invalid")
            elif fault == "lost_reply":
                require(body(f.client.annotations())["annotation_revision"] == 1, "published_reply_loss_visibility")
            f.restart()
            published = fault in ("lost_reply", "crash_after")
            require(body(f.client.annotations())["annotation_revision"] == int(published), "fault_revision")
            row = f.row(ref, private_detail=True)
            require(row["private_values"]["effective_target"] == (REPLACEMENT if published else TEXT), "mixed_fault_state")
            ack = body(f.edit(ref, "correct", {"text": REPLACEMENT}, 0, "fault-op"))
            require(ack["annotation_revision"] == 1 and ack["replayed"] == published, "fault_retry")
            status = body(f.client.status())
            require(status["desired_revision"] == policy_before and status["desired_policy"] == "off", "annotation_enabled_capture")
            body(f.client.set_policy("paused", policy_before))
            body(f.edit(ref, "experience", {"kind": "other", "value": "minor"}, 1, "paused-edit"))
            require(body(f.client.status())["desired_policy"] == "paused", "annotation_unpaused_capture")
            require(source_hash == hash_file(f.root / "observations.jsonl"), "fault_changed_source")
            results.append({"fault": fault, "published_before_retry": published, "recovered_revision": 1})
        finally:
            f.stop()
    return {"faults": results}


def invalid_state(root):
    count = 0
    for field in ("manifest_json", "manifest_version", "journal", "missing_identity"):
        f = Fixture(root / field)
        f.seed(observations())
        ref = f.refs()[0][0]
        body(f.edit(ref, "confirm", {}, 0, "state-1"))
        f.stop()
        if field == "missing_identity":
            # Preserve original bytes in an additive artifact, never remove
            # historical output. Renaming is confined to this own fault case.
            (f.root / "annotation-identity.json").rename(f.root / "saved-identity.json")
        elif field == "journal":
            atomic_write(str(f.root / "annotations.jsonl"), b"{}\n")
        elif field == "manifest_json":
            atomic_write(str(f.root / "annotation-state.json"), b"{")
        else:
            path = f.root / "annotation-state.json"
            state = json.loads(path.read_text())
            state["version"] = "future"
            atomic_write(str(path), json.dumps(state).encode())
        response = subprocess.run([sys.executable, "-m", "archive.collector", "--root", str(f.root), "--socket", f.socket], cwd=REPO, capture_output=True, text=True, timeout=10)
        no_private(response.stdout + response.stderr)
        require(response.returncode != 0 and "code=annotation_state_invalid" in response.stderr, "malformed_reset")
        count += 1
    return {"refused_states": count}


def scales(f):
    f.seed([frame("commit", n, source="scale-" + str(n % 3), payload={"text": TEXT}) for n in range(1, 4097)])
    refs, pair = f.refs()
    require(len(refs) == 4096, "scale_sources")
    samples = []
    start = time.monotonic()
    for n, ref in enumerate(refs, 1):
        body(f.edit(ref, "experience", {"kind": "input_difficulty", "value": "minor"}, n - 1, "scale-%s" % n))
        if n in (256, 4096):
            before = time.monotonic()
            page = body(f.client.annotations(annotation_revision=n, page_size=50))
            count = 0
            edited = 0
            max_bytes = 0
            while True:
                max_bytes = max(max_bytes, len(json.dumps(page).encode()))
                for row in page["observations"]:
                    count += 1
                    edited += row["experience"] is not None
                if not page["next_cursor"]:
                    break
                page = body(f.client.annotations(cursor_token=page["next_cursor"], page_size=50))
            require(count == 4096 and edited == n, "scale_iteration")
            rss = subprocess.check_output(["ps", "-o", "rss=", "-p", str(f.proc.pid)], text=True).strip()
            samples.append({"operations": n, "iterated_sources": count, "edited_sources": edited, "max_page_bytes": max_bytes, "iteration_seconds": time.monotonic() - before, "collector_rss_kib_sample": int(rss), "journal_bytes": (f.root / "annotations.jsonl").stat().st_size})
    f.restart()
    row = f.row(refs[-1], annotation_revision=256)
    require(row["experience"] is None, "scale_restart_pin")
    return {"samples": samples, "elapsed_seconds": time.monotonic() - start, "rss_is_not_total_ram_claim": True}


def high_revision(f):
    f.seed(observations())
    refs, pair = f.refs()
    for n in range(1, 257):
        body(f.edit(refs[0], "correct", {"text": REPLACEMENT + str(n)}, n - 1, "high-%s" % n))
    f.restart()
    for revision in (1, 128, 256):
        row = f.row(refs[0], annotation_revision=revision, private_detail=True)
        require(row["private_values"]["effective_target"] == REPLACEMENT + str(revision), "high_revision_read")
    require(f.row(refs[1])["human_revision"] is None, "incarnation_collision")
    return {"one_source_revisions": 256, "pinned_revisions_checked": [1, 128, 256], "incarnations": 2}


def bounds(f):
    f.seed(observations())
    ref = f.refs()[0][0]
    error(f.edit(ref, "correct", {"text": "x" * (TEXT_BYTES + 1)}, 0, "long-text"), "annotation_input_bound")
    error(f.edit(ref, "experience", {"kind": "other", "value": "major", "note": "x" * (NOTE_BYTES + 1)}, 0, "long-note"), "annotation_input_bound")
    body(f.edit(ref, "correct", {"text": "x" * TEXT_BYTES}, 0, "max-text"))
    body(f.edit(ref, "experience", {"kind": "other", "value": "major", "note": "x" * NOTE_BYTES}, 1, "max-note"))
    for kwargs, code in (({"annotation_version": "future"}, "unsupported_annotation_version"), ({"annotation_revision": 3}, "annotation_revision_unknown"), ({"annotation_revision": -1}, "annotation_revision_unknown"), ({"annotation_revision": True}, "annotation_revision_unknown"), ({"as_of_durable_seq": 999}, "annotation_revision_unknown"), ({"page_size": 51}, "page_bound"), ({"page_size": 0}, "invalid_request"), ({"cursor_token": "bad"}, "invalid_request"), ({"archive_id": "foreign"}, "annotation_foreign_archive")):
        error(f.client.annotations(**kwargs), code)
    first = body(f.client.annotations(page_size=1))
    error(f.client.annotations(cursor_token=first["next_cursor"], annotation_revision=0), "annotation_revision_unknown")
    error(f.client.annotations(cursor_token=first["next_cursor"], private_detail=True), "invalid_request")
    other = Fixture(f.root.parent / "foreign-cursor")
    try:
        error(other.client.annotations(cursor_token=first["next_cursor"]), "annotation_foreign_archive")
    finally:
        other.stop()
    small = Fixture(f.root.parent / "byte-bound", limits=("--query-page-bytes-max", "512"))
    try:
        small.seed(observations())
        # Responses are rejected whole; private reads do not bypass the bound.
        error(small.client.annotations(), "page_bytes_bound")
        error(small.client.annotations(private_detail=True), "page_bytes_bound")
    finally:
        small.stop()
    return {"text_bytes": TEXT_BYTES, "note_bytes": NOTE_BYTES, "query_refusals": 11}


def concurrent_capture(f):
    f.seed(observations())
    ref = f.refs()[0][0]
    status = body(f.client.status())
    body(f.client.set_policy("enabled", status["desired_revision"]))
    def capture():
        return _admit(f.client, [frame("commit", n, source="concurrent-capture") for n in range(1, 257)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(capture)
        for n in range(1, 129):
            body(f.edit(ref, "experience", {"kind": "other", "value": "minor"}, n - 1, "concurrent-%s" % n))
        codes = future.result()
    body(f.client.checkpoint())
    require(all(code == "admitted" for code in codes), "concurrent_refusal")
    status = body(f.client.status())
    require(status["durable_seq"] == 258 and status["known_dropped_units"] == 0, "concurrent_honesty")
    return {"admitted": len(codes), "durable_prefix": 258, "annotation_revision": 128, "fixture_known_dropped_units": 0}


def adapters(f):
    f.seed(observations())
    ref = f.refs()[0][0]
    def cli(args, payload=None):
        command = [sys.executable, "-m", "archive.cli", "--socket", f.socket, "annotations", *args]
        result = subprocess.run(command, cwd=REPO, input=None if payload is None else json.dumps(payload) + "\n", capture_output=True, text=True, timeout=10)
        if "--private-detail" not in args:
            no_private(result.stdout + result.stderr)
        require("Traceback" not in result.stderr, "adapter_traceback")
        return result
    revision = 0
    for kind, value in (("confirm", {}), ("correct", {"text": REPLACEMENT}), ("exclude", {"reason": "private"}), ("experience", {"kind": "other", "value": "major", "note": TEXT})):
        result = cli([kind, "--expect-revision", str(revision), "--operation-id", "cli-" + kind], {"source_reference": ref, "value": value})
        require(result.returncode == 0 and body(json.loads(result.stdout))["durable"], "cli_edit")
        revision += 1
    result = cli(["correct", "--expect-revision", "0", "--operation-id", "cli-stale"], {"source_reference": ref, "value": {"text": TEXT}})
    error(json.loads(result.stdout), "annotation_stale_revision")
    private = cli(["show", "--private-detail", "--revision", "4", "--prefix", "2"], {"source_reference": ref})
    require(CANARY in private.stdout and "\x1b" not in private.stdout, "cli_private")
    private_file = f.root / "reference-input.json"
    private_file.write_text(json.dumps({"source_reference": ref}))
    require(cli(["show", "--input-file", str(private_file)]).returncode == 0, "cli_private_file")
    for args, payload in ((["bad-" + CANARY], None), (["correct", "--expect-revision", CANARY], None), (["correct"], {}), (["show"], {"bad": TEXT}), (["show"], None)):
        if args == ["show"] and payload is None:
            payload = {"source_reference": {}}
        result = cli(args, payload)
        require(result.returncode != 0, "cli_bad_success")
    malformed = subprocess.run([sys.executable, "-m", "archive.cli", "--socket", f.socket, "annotations", "show"], cwd=REPO, input="{" + TEXT + "\n", capture_output=True, text=True, timeout=10)
    no_private(malformed.stdout + malformed.stderr)
    require(malformed.returncode != 0, "malformed_input_success")
    commands = "annotations 2 4\nannotation-select 1\nannotation-edit confirm tui-confirm 4\nannotation-edit correct tui-correct 5\n" + json.dumps({"text": TEXT}) + "\nannotation-edit exclude tui-exclude 6\n" + json.dumps({"reason": "other"}) + "\nannotation-edit experience tui-experience 7\n" + json.dumps({"kind": "unexpected_behavior", "value": "blocking", "note": TEXT}) + "\nannotation-edit confirm tui-stale 4\nannotation-private\nannotation-select 999\nannotation-edit correct bad bad\nquit\n"
    result = subprocess.run([sys.executable, "-m", "archive.cli", "--socket", f.socket, "tui"], cwd=REPO, input=commands, capture_output=True, text=True, timeout=15)
    # Deliberate private screen at old pinned revision, not silently latest.
    require(result.returncode == 0 and CANARY in result.stdout and "annotation_stale_revision" in result.stdout and "SCREEN closed" in result.stdout and "\x1b" not in result.stdout, "tui_interaction")
    # Ordinary stream (no opt-in screen) must remain private-content free.
    out = io.StringIO()
    TuiSession(f.client, io.StringIO("annotations\nannotation-select 1\nannotation-edit confirm stale 0\nquit\n"), out).run()
    no_private(out.getvalue())
    require(body(f.client.status())["desired_policy"] == "off", "page_close_policy")
    require(body(f.client.annotations())["annotation_revision"] == 8, "tui_mutations")
    f.stop()
    result = cli(["list"])
    error(json.loads(result.stdout), "collector_unavailable")
    out = io.StringIO()
    TuiSession(f.client, io.StringIO("annotations\nannotation-private\nquit\n"), out).run()
    require("collector_unavailable" in out.getvalue(), "tui_disconnected_empty")
    no_private(out.getvalue())
    return {"cli_operations": 4, "tui_operations": 4, "durable_revision": 8, "stale_not_retried": True, "private_controls_escaped": True}


def safety(root):
    f = Fixture(root / "base")
    try:
        f.seed(observations())
        ref = f.refs()[0][0]
        # Private file input rejects broad mode, symlink and hardlink aliases.
        path = root / "input.json"
        path.write_text(json.dumps({"source_reference": ref}))
        os.chmod(path, 0o644)
        alias = root / "alias.json"
        alias.symlink_to(path)
        hard = root / "hard.json"
        os.link(path, hard)
        for leaf in (path, alias, hard):
            result = subprocess.run([sys.executable, "-m", "archive.cli", "--socket", f.socket, "annotations", "show", "--input-file", str(leaf)], cwd=REPO, capture_output=True, text=True, timeout=10)
            no_private(result.stdout + result.stderr)
            require(result.returncode != 0, "unsafe_private_file")
        # Only own fault artifacts: preserve original as saved copy, then
        # ensure new managed symlink cannot write through its target.
        f.stop()
        original = f.root / "annotation-state.json"
        original.rename(f.root / "saved-state.json")
        original.symlink_to(f.root / "saved-state.json")
        before = hash_file(f.root / "saved-state.json")
        result = subprocess.run([sys.executable, "-m", "archive.collector", "--root", str(f.root), "--socket", f.socket], cwd=REPO, capture_output=True, text=True, timeout=10)
        require(result.returncode != 0 and "unsafe_root" in result.stderr and before == hash_file(f.root / "saved-state.json"), "managed_alias")
        os.chmod(path, 0o600)
        logs = [p.read_text() for p in root.rglob("launch-*.err")]
        require(not any("forbidden_probe" in log for log in logs), "probe_tripwire")
        return {"private_input_refusals": 3, "managed_alias_refused": True, "no_model_or_network_probe": True}
    finally:
        f.stop()


def self_test():
    normalize_edit({"kind": "correct", "value": {"text": "x"}, "expected_revision": 0, "operation_id": "self"})
    try:
        normalize_edit({"kind": "correct", "value": {"text": "x" * (TEXT_BYTES + 1)}, "expected_revision": 0, "operation_id": "self"})
    except InterfaceError as exc:
        require(exc.code == "annotation_input_bound", "self_bound")
    else:
        raise CheckFailure("self_bound_missing")
    require("private_values" not in strip_content({"private_values": {"effective_target": TEXT}}), "self_redaction")
    print("self_test=pass content_included=false")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract",))
    parser.add_argument("--root")
    parser.add_argument("--report")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    require(args.suite == "contract" and args.root and args.report, "arguments")
    os.umask(0o077)
    root = Path(args.root).absolute()
    require(not root.exists(), "fresh_root_required")
    root.mkdir(parents=True, mode=0o700)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    results = []
    functions = (exact, kinds, concurrent, pinned, fault_cases, invalid_state, scales, high_revision, bounds, concurrent_capture, adapters, safety)
    tracemalloc.start()
    for name, function in zip(REQUIRED_CASES, functions):
        case_root = root / name
        fixture = None
        start = time.monotonic()
        try:
            if function in (fault_cases, invalid_state, safety):
                case_root.mkdir(mode=0o700)
                details = function(case_root)
            else:
                fixture = Fixture(case_root)
                details = function(fixture)
            results.append({"case": name, "pass": True, "details": details, "seconds": time.monotonic() - start})
            print("case=%s result=pass content_included=false" % name, flush=True)
        except Exception as exc:
            # Do not reflect arbitrary exception/argv/value payloads.
            code = str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__
            no_private(code)
            results.append({"case": name, "pass": False, "error": code, "seconds": time.monotonic() - start})
            print("case=%s result=fail code=%s content_included=false" % (name, code), flush=True)
        finally:
            if fixture:
                fixture.stop()
    current, peak = tracemalloc.get_traced_memory()
    report = {"contract": "AC-193-v1", "annotation_version": ANNOTATION_VERSION, "content_included": False, "required_cases": list(REQUIRED_CASES), "cases": results, "skips": [], "pass": all(item["pass"] for item in results) and len(results) == len(REQUIRED_CASES), "runtime": {"python": sys.version, "executable": sys.executable, "sqlite": sqlite3.sqlite_version}, "root": str(root), "cwd": str(REPO), "argv": sys.argv, "source": {str(p.relative_to(REPO)): hash_file(p) for p in [REPO / "archive/annotations.py", REPO / "archive/collector.py", REPO / "archive/interface.py", REPO / "archive/annotation_adapter.py", REPO / "archive/cli.py", REPO / "archive/tui.py", Path(__file__)]}, "launcher_sha256": hashlib.sha256(LAUNCHER.encode()).hexdigest(), "checker_tracemalloc_peak_bytes": peak, "not_a_total_ram_claim": True, "limits": {"text_bytes": TEXT_BYTES, "note_bytes": NOTE_BYTES, "private_input_bytes": LINE_BYTES}, "live_capture": False, "models_loaded": False}
    target = Path(args.report)
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    atomic_write(str(target), json.dumps(report, indent=2, sort_keys=True).encode())
    print("required_cases=%s passed=%s skipped=0 content_included=false" % (len(results), sum(item["pass"] for item in results)))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
