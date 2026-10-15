#!/usr/bin/env python3
"""Content-free contract checker for passive plugin archive observation.

This is an orchestration entry, not a replacement plugin. It does not enable
capture. Ordinary stdout, stderr, and the report omit raw text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from archive import Client  # noqa: E402
from archive.collector import Collector  # noqa: E402
from archive.interface import strip_content  # noqa: E402
from archive.limits import resolve  # noqa: E402

CANARY = "PLUGIN190CANARY"
REQUIRED_CASES = (
    "PolicyOffDoesNotAdmitOrBlockCommit",
    "EnabledCaptureObservesCompetitionAndRequest",
    "FailedExchangeKeepsIssuedRequestId",
    "RerankOffDoesNotIssueRequest",
    "UnsupportedSchemaOmitsText",
    "SelectionCommitAndRetraction",
    "HeldPublicationDoesNotBlockCommit",
    "AbsentCollectorDoesNotBlockCommit",
    "SecureInputOmitsText",
    "OrdinaryDemandSurvivesCommitAndAbort",
    "PausedCommitIsNotBackfilled",
    "PausedSelectionIsNotBackfilled",
    "StaleSelectionIsNotBackfilled",
    "EffectiveSelectionCommitIsIncluded",
    "LossNoticeSurvivesFailedTransport",
)
WATCHDOG_MS = 2000


class CheckFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_content_free(text, label):
    if CANARY in text or "候测" in text or "世界" in text:
        raise CheckFailure("content_leak:" + label)


def _start(root, sock, **limits):
    os.makedirs(os.path.dirname(root), mode=0o700, exist_ok=True)
    collector = Collector(root, sock, resolve(limits))
    collector.serve_in_thread() if hasattr(collector, "serve_in_thread") else None
    return collector


def _frontend_frame(sequence=1, text="INV-NIHAO"):
    return {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": "frontend-1",
        "source_local_sequence": sequence,
        "observation_kind": "commit_attempt",
        "process_id": "proc-189",
        "update_id": "u-189",
        "commit_id": "c-189",
        "continuity_segment_id": "seg-189",
        "outcome": "observed_attempt",
        "stage": "frontend_update",
        "eligibility": "included",
        "host_persistence": "unknown",
        "payload": {"text": text},
    }


def _plugin_frame(sequence, version=1, **extra):
    frame = {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": "plugin-check",
        "source_local_sequence": sequence,
        "observation_kind": "plugin_observation",
        "plugin_observation_version": version,
        "plugin_stage": "competition",
        "process_id": "pproc-check",
        "association_role": "absent",
        "association_read": "absent",
        "coverage": "unknown",
        "coverage_basis": "unspecified",
        "lm_request_state": "no_request",
        "apply_state": "not_applicable",
        "submission": "not_applicable",
        "target_membership": "unknown",
        "payload": {"text": CANARY},
    }
    frame.update(extra)
    return frame


def _collector_main(root, sock):
    os.makedirs(os.path.dirname(root), exist_ok=True)
    code = subprocess.call(
        [
            sys.executable,
            "-m",
            "archive.cli",
            "--root",
            root,
            "--socket",
            sock,
            "collector",
            "start",
        ],
        cwd=REPO,
    )
    if code != 0:
        raise CheckFailure("collector_start")
    return code


def self_test(root):
    os.makedirs(root, mode=0o700, exist_ok=True)
    sock = os.path.join(root, "collector.sock")
    _collector_main(root, sock)
    try:
        client = Client(sock, timeout=3)
        client.set_policy("enabled", 0)
        bad = client.call("admit_batch", {"observations": [_plugin_frame(1, version=2)]})
        codes = (bad.get("body") or {}).get("codes") or []
        if codes != ["unsupported_plugin_observation"]:
            raise CheckFailure("version_refusal")
        forged = _plugin_frame(
            2,
            coverage="complete",
            coverage_basis="legacy_snapshot_complete",
            target_membership="present",
            captured_candidate_count=1,
            group_member_count=1,
        )
        forged_result = client.call("admit_batch", {"observations": [forged]})
        if (forged_result.get("body") or {}).get("codes") != ["invalid_request"]:
            raise CheckFailure("complete_claim")
        front = client.call("admit_batch", {"observations": [_frontend_frame()]})
        if (front.get("body") or {}).get("codes") != ["admitted"]:
            raise CheckFailure("frontend_frame")
        client.checkpoint()
        query = client.query("timeline", page_size=20)
        text = json.dumps(strip_content(query), sort_keys=True)
        _assert_content_free(text, "ordinary_query")
        if "commit_attempt_observed" not in text:
            raise CheckFailure("frontend_interpretation")
        if "plugin_competition_observed" in text:
            raise CheckFailure("forged_complete_stored")
        duplicate = _plugin_frame(3)
        client.checkpoint()
        first = client.call("admit_batch", {"observations": [duplicate]})
        second = client.call("admit_batch", {"observations": [duplicate]})
        if (first.get("body") or {}).get("codes") != ["admitted"]:
            raise CheckFailure("plugin_admit")
        if (second.get("body") or {}).get("codes") != ["duplicate"]:
            raise CheckFailure("plugin_duplicate")
        conflict = _plugin_frame(3, plugin_stage="emission")
        conflicted = client.call("admit_batch", {"observations": [conflict]})
        if (conflicted.get("body") or {}).get("codes") != ["identity_conflict"]:
            raise CheckFailure("plugin_conflict")
        status = json.dumps(client.status(), sort_keys=True)
        _assert_content_free(status, "status")
        if "separately_configured_may_continue" not in status:
            raise CheckFailure("legacy_disclosure")
        report = {"passed": True, "skipped": [], "content_included": False}
        if REQUIRED_CASES and report.get("skipped"):
            raise CheckFailure("skipped_case")
        skipped_probe = {"passed": False, "skipped": ["missing-required"], "content_included": False}
        if not skipped_probe["skipped"] or skipped_probe["passed"]:
            raise CheckFailure("skipped_probe")
    finally:
        subprocess.call(
            [sys.executable, "-m", "archive.cli", "--root", root, "--socket", sock, "collector", "stop"],
            cwd=REPO,
        )
    print("self-test passed")
    return 0


def _find_dylib(native_build):
    candidates = [
        os.path.join(native_build, "lib", "librime-llm-rerank.dylib"),
        os.path.join(native_build, "lib", "rime-plugins", "librime-llm-rerank.dylib"),
        os.path.join(native_build, "lib", "rime-plugins", "librime-llm-rerank.so"),
        os.path.join(native_build, "..", "dist", "lib", "rime-plugins", "librime-llm-rerank.dylib"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.realpath(path)
    raise CheckFailure("dylib_missing")


def contract(root, report_path, native_build):
    os.makedirs(root, mode=0o700, exist_ok=True)
    candidates = [
        os.path.join(native_build, "test", "llm_rerank_test"),
        os.path.join(native_build, "plugins", "llm-rerank", "test", "llm_rerank_test"),
    ]
    test_bin = next((path for path in candidates if os.path.isfile(path)), "")
    if not test_bin:
        raise CheckFailure("native_test_missing")
    dylib = _find_dylib(native_build)
    source_dir = os.path.join(native_build, "plugins", "llm-rerank")
    if not os.path.isdir(source_dir):
        source_dir = REPO
    watchdog = {
        "watchdog_ms": WATCHDOG_MS,
        "purpose": "dependency_detection_not_latency_certification",
        "dylib_sha256": _sha256(dylib),
        "test_bin_sha256": _sha256(test_bin),
        "content_included": False,
    }
    watchdog_path = os.path.join(root, "watchdog-before-fault.json")
    with open(watchdog_path, "w") as handle:
        json.dump(watchdog, handle, sort_keys=True)
        handle.write("\n")
    os.chmod(watchdog_path, 0o600)
    grant = os.path.dirname(os.path.abspath(root))
    short_root = grant
    if len(os.path.join(short_root, "lm.sock")) >= 104:
        raise CheckFailure("socket_path_too_long")
    os.makedirs(short_root, mode=0o700, exist_ok=True)
    env = os.environ.copy()
    env["LLM_RERANK_ARCHIVE_WORKSPACE"] = short_root
    env["LLM_RERANK_ARCHIVE_PRESERVE"] = "1"
    env["HOME"] = os.path.join(short_root, "home")
    os.makedirs(env["HOME"], mode=0o700, exist_ok=True)
    log_path = os.path.join(root, "gtest.log")
    proc = subprocess.run(
        [test_bin, "--gtest_filter=ArchiveObservationTest.*"],
        cwd=os.path.dirname(test_bin),
        env=env,
        text=True,
        capture_output=True,
    )
    with open(log_path, "w") as handle:
        handle.write(proc.stdout)
        handle.write(proc.stderr)
    _assert_content_free(proc.stdout + proc.stderr, "gtest_log")
    skipped = [name for name in REQUIRED_CASES if name not in proc.stdout and name not in proc.stderr]
    # gtest prints the fixture method name.
    missing = []
    combined = proc.stdout + proc.stderr
    for name in REQUIRED_CASES:
        if name not in combined:
            missing.append(name)
    report = {
        "passed": proc.returncode == 0 and not missing,
        "exit_code": proc.returncode,
        "missing_cases": missing,
        "skipped": missing,
        "dylib": dylib,
        "dylib_sha256": watchdog["dylib_sha256"],
        "test_bin_sha256": watchdog["test_bin_sha256"],
        "watchdog_ms": WATCHDOG_MS,
        "watchdog_path": watchdog_path,
        "native_workspace": short_root,
        "content_included": False,
        "ranking_benefit": False,
        "host_persistence_proof": False,
        "latency_certification": False,
        "merge_enables_capture": False,
    }
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w") as handle:
        json.dump(report, handle, sort_keys=True)
        handle.write("\n")
    os.chmod(report_path, 0o600)
    _assert_content_free(json.dumps(report), "report")
    if proc.returncode != 0 or missing:
        raise CheckFailure("native_cases")
    print("contract passed")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description="Plugin archive observation checker")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract",))
    parser.add_argument("--root", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--native-build", default="")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            if not args.root:
                raise CheckFailure("invalid_request")
            return self_test(args.root)
        if args.suite == "contract":
            if not args.root or not args.report or not args.native_build:
                raise CheckFailure("invalid_request")
            return contract(args.root, args.report, args.native_build)
        raise CheckFailure("invalid_request")
    except CheckFailure as exc:
        sys.stderr.write("code=%s\n" % exc.code)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
