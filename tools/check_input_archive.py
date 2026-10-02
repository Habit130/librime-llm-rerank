#!/usr/bin/env python3
"""Contract driver for the input-archive Interface.

This is not a second storage implementation. It starts the delivered collector,
calls the public Interface, and drives the CLI/TUI Adapters.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pty
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from archive import Client, Producer  # noqa: E402
from archive.collector import Collector  # noqa: E402
from archive.interface import (  # noqa: E402
    INTERFACE_VERSION,
    canonical_bytes,
    parse_readiness,
    strip_content,
)
from archive.limits import DEFAULTS  # noqa: E402
from archive.producer import _budget_bytes  # noqa: E402
from archive.synthetic import INVENTED_TEXT, scale_observation, supported_processes  # noqa: E402

CANARY = "CANARY188BODY"
EXCL = "CANARY188EXCL"
CONF = "CANARY188CONF"
ESC_MARK = "CANARY188ESC"
REQUIRED = ["ARCH188-%s" % i for i in range(1, 9)]
PAGE = 20


class CheckFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def quarantine_tail_inconsistent(file_bytes, watermark):
    return file_bytes > watermark


def publication_matches_watermark(status_seq, query_seq, rows, persisted_seq, checkpoint_seq):
    return status_seq == query_seq == persisted_seq == checkpoint_seq and rows == 0


def start_outcome_is_exclusive(exits):
    """Exactly one supported CLI start may claim ownership of one root."""
    return sorted(exits) == [0, 1]


def start_reported_ownership(stdout, pid):
    """A claimed success must name this attempt's own ready owner."""
    lines = [line.strip() for line in (stdout or "").splitlines()]
    return (
        "collector_started=true" in lines
        and ("pid=%s" % pid) in lines
        and ("owner_pid=%s" % pid) in lines
    )


def readiness_is_this_attempt(line, token, pid, kind="ready"):
    """A readiness line counts only for the spawned token and child pid."""
    parsed = parse_readiness(line, token, pid)
    return parsed is not None and parsed[0] == kind


def survivors_are_zero(count):
    """A documented normal stop leaves no identified fixture collector."""
    return count == 0


def lock_identity_is_stable(before, after):
    """Contention or restart must not unlink or replace the owner's lock path."""
    return before is not None and before == after


def ordinary_output_is_content_free(text):
    return not any(marker in (text or "") for marker in (CANARY, EXCL, CONF, ESC_MARK))


def _fixture_collectors(root):
    """Bounded exact-fixture inventory of live collectors for one owned root.

    Identity comes from the command line (`-m archive.collector` and this exact
    `--root`), so a rejected child that never printed a PID is still counted.
    This is process identity, not transient file handles: `lsof` absence never
    proves exclusion. Returns None when the inventory itself is unavailable.
    """
    try:
        listing = subprocess.check_output(["ps", "-Ao", "pid=,command="], text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    found = []
    for line in listing.splitlines():
        if " -m archive.collector " not in line:
            continue
        if ("--root %s" % root) not in line and ("--root=%s" % root) not in line:
            continue
        try:
            found.append(int(line.split()[0]))
        except (IndexError, ValueError):
            continue
    return sorted(found)


def _read_int(path):
    try:
        return int(open(path, "r").read().strip())
    except (OSError, ValueError):
        return None


OVERSIZE_CJK = "你好世界输入法候选择词测试样本"
# 10845 invented CJK units: producer raw budget fits max_event_bytes while the
# canonical semantic size does not. This is the supported boundary that attempt 2
# reported, reproduced here as synthetic data with no real input.
OVERSIZE_UNITS = 10845


def _oversize_observation(source, units=OVERSIZE_UNITS, sequence=1):
    """A supported luna_pinyin observation whose exact refusal boundary matters."""
    text = (OVERSIZE_CJK * (units // len(OVERSIZE_CJK) + 1))[:units]
    return {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": source,
        "source_local_sequence": sequence,
        "observation_kind": "commit_attempt",
        "process_id": "proc-oversize",
        "update_id": "oversize-u",
        "commit_id": "oversize-c",
        "stage": "unknown",
        "host_persistence": "unknown",
        "clocks": {"event_time": None, "observation_time": None, "clock_domain": "unknown"},
        "payload": {"text": text},
    }


def _policy_observation_is_acknowledged(declared_revision, desired_revision):
    """A revision is acknowledged only when an observation declares it.

    A response that merely delivers `desired_revision` never acknowledges it.
    """
    return declared_revision is not None and declared_revision == desired_revision


def _oversize_boundary_trial():
    """In-process trial of the exact oversize refusal boundary.

    Measures the producer raw budget with the producer's own function and the
    canonical semantic size with the collector's own prepare path, then drives
    the real `_accept_one` refusal branch twice: once on the exact boundary
    fixture, and once on a fixture shrunk well inside the limit as a control.
    Never starts a collector and never writes storage.
    """
    trial = object.__new__(Collector)
    trial.limits = dict(DEFAULTS)
    trial._lock = threading.Lock()
    trial._cv = threading.Condition(trial._lock)
    trial._policy = {"revision": 1, "desired": "enabled"}
    trial._queue = []
    trial._queue_bytes = 0
    trial._identities = {}

    def run(units):
        trial._state = Collector._fresh_state(trial, "none", [])
        trial._queue = []
        trial._queue_bytes = 0
        trial._identities = {}
        observation = _oversize_observation("self-test-oversize", units=units)
        budget = [0]
        _budget_bytes(observation, 10 ** 9, budget)
        prepared = Collector._prepare(trial, observation)
        canonical = len(canonical_bytes(prepared["semantic"]))
        code = trial._accept_one(observation)
        with trial._lock:
            refused_units = trial._state["admission_refused_units"]
        return budget[0], canonical, code, refused_units

    raw, canonical, code, refused_units = run(OVERSIZE_UNITS)
    accounted = code == "event_too_large" and refused_units == 1
    # Control: a fixture well inside the limit must not be refused at all, so the
    # boundary trial above cannot pass by refusing everything.
    _raw_small, _canon_small, small_code, small_refused = run(64)
    unrefused_inside_limit = small_code != "event_too_large" and small_refused == 0
    return raw, canonical, accounted, unrefused_inside_limit


def contains_marker(text, marker):
    if text is None:
        return False
    if isinstance(text, bytes):
        return marker.encode("utf-8") in text
    return marker in text


def validate_report(report):
    problems = []
    try:
        blob = json.dumps(report, ensure_ascii=True)
    except TypeError:
        return ["report_not_serializable"]
    for marker in (CANARY, EXCL, CONF, ESC_MARK):
        if marker in blob:
            problems.append("canary_in_report")
            break
    if "\u001b" in blob or "\\u001b" in blob and "private" in blob:
        pass
    if "\x1b" in blob:
        problems.append("control_byte_in_report")
    coverage = report.get("coverage") or {}
    executed = coverage.get("executed") or []
    skipped = coverage.get("skipped") or []
    criteria = report.get("criteria") or {}
    if coverage.get("required") != REQUIRED:
        problems.append("required_coverage_mismatch")
    if skipped:
        problems.append("skipped_required")
    if not executed:
        problems.append("empty_coverage")
    for criterion in REQUIRED:
        if criterion not in executed:
            problems.append("missing_" + criterion)
        item = criteria.get(criterion) or {}
        if item.get("result") != "pass":
            problems.append("criterion_not_pass_" + criterion)
        if item.get("failed"):
            problems.append("criterion_failed_" + criterion)
    if report.get("result") != "pass":
        problems.append("result_not_pass")
    if report.get("canary_in_report") is not False:
        problems.append("canary_flag")
    return problems


def run_self_test():
    failures = []
    if not contains_marker("prefix" + CANARY + "suffix", CANARY):
        failures.append("positive_detector")
    if contains_marker("ordinary status", CANARY):
        failures.append("negative_detector")
    good = {
        "result": "pass",
        "canary_in_report": False,
        "coverage": {"required": list(REQUIRED), "executed": list(REQUIRED), "skipped": []},
        "criteria": {item: {"result": "pass", "failed": []} for item in REQUIRED},
    }
    if validate_report(good):
        failures.append("positive_report")
    missing = json.loads(json.dumps(good))
    missing["coverage"]["executed"] = ["ARCH188-1"]
    missing["coverage"]["skipped"] = ["ARCH188-2"]
    if not validate_report(missing):
        failures.append("negative_skipped")
    leaked = json.loads(json.dumps(good))
    leaked["note"] = CANARY
    if "canary_in_report" not in validate_report(leaked):
        failures.append("negative_canary")
    empty = {"result": "pass", "canary_in_report": False, "coverage": {"required": list(REQUIRED), "executed": [], "skipped": []}, "criteria": {}}
    if not validate_report(empty):
        failures.append("negative_empty")
    if not quarantine_tail_inconsistent(128, 0):
        failures.append("negative_quarantine_tail")
    if quarantine_tail_inconsistent(0, 0):
        failures.append("positive_quarantine_watermark")
    if not publication_matches_watermark(1, 1, 0, 1, 1):
        failures.append("positive_watermark_prefix")
    for name, values in (
        ("negative_watermark_status", (2, 1, 0, 1, 1)),
        ("negative_watermark_query", (1, 2, 1, 1, 1)),
        ("negative_watermark_rows", (1, 1, 1, 1, 1)),
        ("negative_watermark_checkpoint", (1, 1, 0, 1, 2)),
    ):
        if publication_matches_watermark(*values):
            failures.append(name)
    # An oversize refusal is only honest if it is observable. These controls fail
    # if the boundary fixture stops being an exact boundary, if the refusal stops
    # moving the owning counter, or if the fixture is refused for another reason.
    raw, canonical, accounted, unrefused_inside_limit = _oversize_boundary_trial()
    if not (raw <= DEFAULTS["max_event_bytes"] < canonical):
        failures.append("negative_oversize_boundary")
    if not accounted:
        failures.append("negative_oversize_unaccounted")
    if not unrefused_inside_limit:
        failures.append("positive_oversize_inside_limit")
    # A delivered revision is not an acknowledgement; only a declared one is.
    if not _policy_observation_is_acknowledged(1, 1):
        failures.append("positive_policy_acknowledgement")
    if _policy_observation_is_acknowledged(0, 1):
        failures.append("negative_policy_stale_declaration")
    if _policy_observation_is_acknowledged(None, 1):
        failures.append("negative_policy_absent_declaration")
    # Ownership/readiness/survivor predicates: each positive control must hold
    # and each deliberately failing control (including the confirmed defect
    # shape, two successful starts) must be rejected.
    if not start_outcome_is_exclusive([0, 1]) or not start_outcome_is_exclusive([1, 0]):
        failures.append("positive_start_exclusion")
    if start_outcome_is_exclusive([0, 0]) or start_outcome_is_exclusive([1, 1]):
        failures.append("negative_start_exclusion")
    if not start_reported_ownership("collector_started=true\npid=7\nowner_pid=7\n", 7):
        failures.append("positive_owned_success")
    if start_reported_ownership("collector_started=true\npid=7\nowner_pid=8\n", 7):
        failures.append("negative_borrowed_owner_pid")
    if start_reported_ownership("collector_started=true\npid=7\n", 7):
        failures.append("negative_unverified_owner_pid")
    if not readiness_is_this_attempt("ready 4242 tok", "tok", 4242):
        failures.append("positive_readiness")
    for line in (
        "ready 4242 other",
        "ready 4243 tok",
        "ready 4242",
        "",
        "refused 4242 tok collector_already_running",
    ):
        if readiness_is_this_attempt(line, "tok", 4242):
            failures.append("negative_readiness")
    if parse_readiness("refused 4242 tok collector_already_running", "tok", 4242) != (
        "refused",
        "collector_already_running",
    ):
        failures.append("positive_refusal")
    if parse_readiness("refused 4242 tok not_a_code", "tok", 4242) != ("refused", "collector_unavailable"):
        failures.append("negative_refusal_fail_closed")
    if not survivors_are_zero(0) or survivors_are_zero(1):
        failures.append("survivor_predicate")
    if not lock_identity_is_stable(7, 7):
        failures.append("positive_lock_identity")
    if lock_identity_is_stable(7, 8) or lock_identity_is_stable(None, None):
        failures.append("negative_lock_identity")
    if not ordinary_output_is_content_free("code=collector_already_running"):
        failures.append("positive_ownership_output")
    if ordinary_output_is_content_free(CANARY):
        failures.append("negative_ownership_output")
    if failures:
        sys.stdout.write("self-test fail %s\n" % ",".join(failures))
        return 1
    sys.stdout.write("self-test pass\n")
    return 0


class Suite(object):
    def __init__(self, workspace):
        self.workspace = os.path.abspath(workspace)
        self.pids = set()
        self.results = {item: [] for item in REQUIRED}
        self.executed = []
        self.counts = {}
        self.walkthrough_sha = ""
        self.limits = dict(DEFAULTS)

    def run(self):
        checks = [
            ("ARCH188-1", "provenance", self.check_provenance),
            ("ARCH188-2", "admission", self.check_admission),
            ("ARCH188-3", "durability", self.check_durability),
            ("ARCH188-4", "policy", self.check_policy),
            ("ARCH188-5", "privacy", self.check_privacy),
            ("ARCH188-6", "capacity", self.check_capacity),
            ("ARCH188-7", "walkthrough", self.check_walkthrough),
            ("ARCH188-8", "usability", self.check_usability),
        ]
        for criterion, name, fn in checks:
            self.executed.append(criterion)
            try:
                fn()
            except CheckFailure as exc:
                self.results[criterion].append(name + ":" + exc.code)
            except Exception:
                self.results[criterion].append(name + ":unexpected")
            finally:
                self.stop_owned()
        self.check_ownership_lifecycle()
        return self.report()

    def report(self):
        criteria = {}
        failed = False
        for item in REQUIRED:
            problems = self.results[item]
            if problems or item not in self.executed:
                failed = True
            criteria[item] = {
                "result": "fail" if problems else "pass",
                "checks": 1,
                "failed": problems,
            }
        return {
            "report_version": 1,
            "interface_version": INTERFACE_VERSION,
            "result": "fail" if failed else "pass",
            "criteria": criteria,
            "coverage": {
                "required": list(REQUIRED),
                "executed": list(self.executed),
                "skipped": [],
            },
            "counts": self.counts,
            "identities": {
                "python": "%s.%s.%s" % sys.version_info[:3],
                "interface_version": INTERFACE_VERSION,
                "envelope_version": 1,
                "content_version": 1,
            },
            "limits": self.limits,
            "walkthrough_sha256": self.walkthrough_sha,
            "canary_in_report": False,
            "dependencies": [],
            "inference_dependency": False,
        }

    def root(self, name):
        path = os.path.join(self.workspace, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def start(self, name, **flags):
        root = self.root(name)
        sock = os.path.join(root, "collector.sock")
        cmd = [
            sys.executable, "-m", "archive.cli",
            "--root", root, "--socket", sock, "--timeout", "8",
            "collector", "start",
        ]
        cmd.extend(self._flags(flags))
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=20)
        self._ordinary(proc.stdout, proc.stderr)
        if proc.returncode != 0:
            raise CheckFailure("start_failed")
        pid = _pid_from_text(proc.stdout)
        if pid:
            self.pids.add(pid)
        return root, sock, pid

    def start_rejected(self, root):
        sock = os.path.join(self.workspace, "rejected.sock")
        cmd = [
            sys.executable, "-m", "archive.cli",
            "--root", root, "--socket", sock, "--timeout", "5",
            "collector", "start",
        ]
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=15)
        self._ordinary(proc.stdout, proc.stderr)
        if proc.returncode == 0 or "code=unsafe_root" not in proc.stderr:
            raise CheckFailure("unsafe_root_not_rejected")
        return proc

    def stop_root(self, root, sock):
        cmd = [
            sys.executable, "-m", "archive.cli",
            "--root", root, "--socket", sock, "--timeout", "8",
            "collector", "stop",
        ]
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=20)
        self._ordinary(proc.stdout, proc.stderr)
        return proc

    def cli(self, *args, timeout=15):
        cmd = [sys.executable, "-m", "archive.cli", *args]
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        if "--private-detail" not in args:
            self._ordinary(proc.stdout, proc.stderr)
        return proc

    def stop_owned(self):
        for pid in list(self.pids):
            if _alive(pid) and _is_collector(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        deadline = time.time() + 2
        while time.time() < deadline and any(_alive(pid) for pid in self.pids):
            time.sleep(0.05)
        for pid in list(self.pids):
            if _alive(pid) and _is_collector(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        self.pids.clear()

    def start_async(self, root, sock, timeout=8):
        """A supported CLI start that is not waited for yet (concurrent race)."""
        command = [
            sys.executable, "-m", "archive.cli",
            "--root", root, "--socket", sock, "--timeout", str(timeout),
            "collector", "start",
        ]
        return subprocess.Popen(
            command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

    def start_pair(self, root, sock, timeout=8):
        """Two concurrent supported CLI starts on one root, both waited out."""
        procs = [self.start_async(root, sock, timeout), self.start_async(root, sock, timeout)]
        results = []
        for proc in procs:
            try:
                stdout, stderr = proc.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise CheckFailure("start_timeout")
            self._ordinary(stdout, stderr)
            results.append((proc.returncode, stdout, stderr))
        return results

    def direct_entry(self, root, sock, timeout=15):
        """The supported direct collector entry, not the CLI adapter."""
        return subprocess.run(
            [sys.executable, "-m", "archive.collector", "--root", root, "--socket", sock],
            cwd=REPO, capture_output=True, text=True, timeout=timeout,
        )

    def fixture_collectors(self, root):
        found = _fixture_collectors(root)
        if found is None:
            raise CheckFailure("inventory_unavailable")
        for pid in found:
            self.pids.add(pid)
        return found

    def wait_no_fixture_collectors(self, root, timeout=5):
        return _wait(lambda: _fixture_collectors(root) == [], timeout=timeout)

    def fresh_private_root(self, name):
        root = self.root(name)
        if os.path.isdir(root):
            shutil.rmtree(root)
        os.makedirs(root, 0o700)
        os.chmod(root, 0o700)
        return root

    def _race(self, root, sock):
        """Race two supported starts and return the winner/loser evidence."""
        results = self.start_pair(root, sock)
        exits = sorted(item[0] for item in results)
        if not start_outcome_is_exclusive(exits):
            raise CheckFailure(
                "race_not_exclusive:%s" % ",".join(str(value) for value in exits)
            )
        success = [item for item in results if item[0] == 0][0]
        loser = [item for item in results if item[0] != 0][0]
        if not ordinary_output_is_content_free(success[1] + success[2] + loser[1] + loser[2]):
            raise CheckFailure("race_content_leak")
        if "collector_started=true" in loser[1]:
            raise CheckFailure("race_loser_claimed_success")
        if "code=collector_already_running" not in loser[2]:
            raise CheckFailure("race_loser_code")
        pid = _pid_from_text(success[1])
        if pid is None or not start_reported_ownership(success[1], pid):
            raise CheckFailure("race_success_identity")
        live = self.fixture_collectors(root)
        if live != [pid]:
            raise CheckFailure("race_live_set")
        if _read_int(os.path.join(root, "collector.pid")) != pid:
            raise CheckFailure("race_pid_metadata")
        client = Client(sock, timeout=5)
        status = client.status()
        self._require(status)
        if status["body"].get("owner_pid") != pid:
            raise CheckFailure("race_endpoint_owner")
        if client.query("timeline", page_size=PAGE)["body"]["as_of_durable_seq"] != status["body"]["durable_seq"]:
            raise CheckFailure("race_query")
        return pid, success, loser, results

    def check_provenance(self):
        root, sock, _pid = self.start("provenance", freshness_window_ms=5000, heartbeat_interval_ms=50)
        client = Client(sock, timeout=5)
        status = client.status()
        self._require(status)
        if status["body"]["desired_policy"] != "off":
            raise CheckFailure("initial_not_off")
        enabled = self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        if enabled.returncode != 0:
            raise CheckFailure("enable_failed")
        source = "prov-source"
        observations = supported_processes(source)
        observations.append({
            "envelope_version": 99,
            "content_version": 1,
            "schema_id": "luna_pinyin",
            "source_instance_id": source,
            "source_local_sequence": 90,
            "observation_kind": "start",
            "process_id": "proc-bad-version",
            "payload": {"text": CANARY},
        })
        observations.append({
            "envelope_version": 1,
            "content_version": 1,
            "schema_id": "not_luna",
            "source_instance_id": source,
            "source_local_sequence": 91,
            "observation_kind": "start",
            "process_id": "proc-bad-schema",
            "payload": {"text": CANARY},
        })
        first = client.call("admit_batch", {"observations": observations})
        self._require(first)
        codes = first["body"]["codes"]
        if "unsupported_version" not in codes or "unsupported_schema" not in codes:
            raise CheckFailure("version_not_refused")
        if CANARY in json.dumps(strip_content(first)):
            raise CheckFailure("canary_leak:admit")
        again = client.call("admit_batch", {"observations": [observations[0]]})
        self._require(again)
        if "duplicate" not in again["body"]["codes"]:
            raise CheckFailure("duplicate")
        conflict = dict(observations[0])
        conflict["payload"] = {"text": CONF}
        conflicted = client.call("admit_batch", {"observations": [conflict]})
        self._require(conflicted)
        if "identity_conflict" not in conflicted["body"]["codes"]:
            raise CheckFailure("conflict")
        if CONF in json.dumps(strip_content(conflicted)):
            raise CheckFailure("canary_leak:conflict")
        late = {
            "envelope_version": 1,
            "content_version": 1,
            "schema_id": "luna_pinyin",
            "source_instance_id": source,
            "source_local_sequence": 7,
            "observation_kind": "input_change",
            "process_id": "proc-ooo",
            "update_id": "ooo-2",
            "parent_update_id": "ooo-1",
            "clocks": {"event_time": 100, "observation_time": None, "clock_domain": "unknown"},
            "payload": {"text": INVENTED_TEXT},
        }
        early = dict(late)
        early["source_local_sequence"] = 6
        early["update_id"] = "ooo-1"
        early["parent_update_id"] = None
        client.call("admit_batch", {"observations": [late]})
        client.checkpoint()
        client.call("admit_batch", {"observations": [early]})
        client.checkpoint()
        self._wait_durable(client, 1)
        for process_id in (
            "proc-commit",
            "proc-cancel",
            "proc-raw",
            "proc-unavailable",
            "proc-unknown",
            "proc-commit-only",
        ):
            found = client.query("process", process_id=process_id, page_size=PAGE)
            self._require(found)
            rows = found["body"]["observations"]
            if not rows:
                raise CheckFailure("missing_process")
            if any(row.get("host_persistence") != "unknown" or row.get("host_persistence_proof") for row in rows):
                raise CheckFailure("host_persistence_claimed")
            if any(row.get("content_included") for row in rows):
                raise CheckFailure("ordinary_content")
        commit_only = client.query("process", process_id="proc-commit-only", page_size=PAGE)
        incompleteness = commit_only["body"]["observations"][0]["incompleteness"]
        if "missing_intermediate" not in incompleteness or "missing_parent_update" not in incompleteness:
            raise CheckFailure("missing_not_disclosed")
        if commit_only["body"]["observations"][0]["semantic_interpretation"] != "commit_attempt_observed":
            raise CheckFailure("commit_reinterpreted")
        ooo = client.query("process", process_id="proc-ooo", page_size=PAGE)
        seqs = [row["source_local_sequence"] for row in ooo["body"]["observations"]]
        if seqs != [7, 6]:
            raise CheckFailure("reordered_by_time")
        private = client.query("process", process_id="proc-commit", private_detail=True, page_size=PAGE)
        original = json.dumps(private)
        if CONF in original:
            raise CheckFailure("conflict_replaced_original")
        if INVENTED_TEXT not in original:
            raise CheckFailure("original_missing")
        quarantine = open(os.path.join(root, "quarantine.jsonl"), "r").read()
        observations_text = open(os.path.join(root, "observations.jsonl"), "r").read()
        if CONF not in quarantine or CONF in observations_text:
            raise CheckFailure("quarantine")
        if CANARY in observations_text or CANARY in quarantine:
            raise CheckFailure("unsupported_stored")
        self._check_invalid_admission(sock)
        self.counts["provenance_records"] = client.status()["body"]["durable_seq"]

    def check_admission(self):
        self._review_admission_path()
        missing = os.path.join(self.workspace, "missing", "collector.sock")
        os.makedirs(os.path.dirname(missing), exist_ok=True)
        producer = Producer(missing, source_instance_id="absent-source", limits={"heartbeat_interval_ms": 50})
        try:
            blocked = _BlockedWork()
            result, waited = _watch(lambda: producer.admit(_sample("absent-source")))
            if waited or blocked.finished():
                raise CheckFailure("admission_waited_absent")
            if result.admitted:
                raise CheckFailure("admitted_without_collector")
        finally:
            producer.close()
        root, sock, pid = self.start("exited", freshness_window_ms=5000)
        os.kill(pid, signal.SIGKILL)
        self._wait_dead(pid)
        producer = Producer(sock, source_instance_id="exited-source", limits={"heartbeat_interval_ms": 50})
        try:
            result, waited = _watch(lambda: producer.admit(_sample("exited-source")))
            if waited or result.admitted or _alive(pid):
                raise CheckFailure("admission_waited_exited")
        finally:
            producer.close()
        hold = self.root("hold") + ".fifo"
        fd = _open_fifo(hold)
        try:
            root, sock, pid = self.start(
                "hold",
                publication_hold=hold,
                collector_queue_count=1,
                freshness_window_ms=5000,
                heartbeat_interval_ms=50,
            )
            client = Client(sock, timeout=5)
            self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
            if not _wait(lambda: client.status().get("body", {}).get("publication_hold") is True):
                raise CheckFailure("hold_not_entered")
            producer = Producer(
                sock,
                source_instance_id="hold-source",
                limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000, "producer_queue_count": 32},
            )
            try:
                self._wait_enabled(producer)
                blocked = _BlockedWork()
                results = []
                for index in range(6):
                    item = _sample("hold-source", sequence=index, kind="input_change")
                    result, waited = _watch(lambda item=item: producer.admit(item))
                    results.append(result)
                    if waited:
                        raise CheckFailure("admission_waited_hold")
                if blocked.finished():
                    raise CheckFailure("blocked_work_released")
                status = client.status()["body"]
                if not status["publication_hold"]:
                    raise CheckFailure("hold_released")
                if not _wait(lambda: _pressured(client), timeout=5):
                    status = client.status()["body"]
                    raise CheckFailure("saturation_not_observed")
                self.counts["held_known_dropped"] = status["known_dropped_units"]
            finally:
                producer.close()
        finally:
            os.write(fd, b"x")
            os.close(fd)
        control = self.root("control") + ".fifo"
        fd = _open_fifo(control)
        thread = None
        try:
            _root, sock, _pid = self.start("control", control_hold=control, freshness_window_ms=5000)
            client = Client(sock, timeout=8)
            thread = None
            def _control():
                client.set_policy("enabled", 0)
            thread = threading.Thread(target=_control, daemon=True)
            thread.start()
            if not _wait(lambda: client.status().get("body", {}).get("control_hold") is True, timeout=5):
                raise CheckFailure("control_not_blocked")
            producer = Producer(sock, source_instance_id="control-source", limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000})
            try:
                result, waited = _watch(lambda: producer.admit(_sample("control-source")))
                if waited or not thread.is_alive():
                    raise CheckFailure("admission_waited_control")
                if result is None:
                    raise CheckFailure("admission_missing")
            finally:
                producer.close()
        finally:
            os.write(fd, b"x")
            os.close(fd)
            if thread is not None:
                thread.join(timeout=3)
        self._check_storage_failure()
        self._check_oversize_refusal()

    def _check_oversize_refusal(self):
        """ARCH188-1: the exact oversize boundary must be observable, not silent.

        The fixture sits at the reported boundary: the producer raw budget fits
        `max_event_bytes` while the canonical semantic size does not. Acceptance
        and genuine counter movement are asserted separately from queue drain and
        query absence, so a silent disappearance cannot pass.
        """
        root, sock, _pid = self.start("oversize", freshness_window_ms=5000, heartbeat_interval_ms=50)
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        observation = _oversize_observation("oversize-source")
        budget = [0]
        _budget_bytes(observation, 10 ** 9, budget)
        raw = budget[0]
        self.counts["oversize_raw_budget"] = raw
        if raw > DEFAULTS["max_event_bytes"]:
            raise CheckFailure("oversize_fixture_not_on_boundary")

        # Direct public admission: the refusal code must be accompanied by an
        # observable refusal counter instead of arriving with no accounting.
        before = client.status()["body"]["admission_refused_units"]
        direct = client.call("admit_batch", {"observations": [observation]})
        codes = (direct.get("body") or {}).get("codes")
        if codes != ["event_too_large"]:
            raise CheckFailure("oversize_direct_code")
        after = client.status()["body"]["admission_refused_units"]
        if after != before + 1:
            raise CheckFailure("oversize_direct_unaccounted")
        self.counts["oversize_collector_refused_units"] = after - before

        # The producer admits the boundary item locally, then the drain refuses it.
        # Acceptance, queue drain, query absence and counter movement are checked
        # as separate facts.
        producer = Producer(
            sock,
            source_instance_id="oversize-source",
            limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000},
        )
        try:
            self._wait_enabled(producer)
            pre = client.status()["body"]["admission_refused_units"]
            result = producer.admit(observation)
            if not result.admitted:
                raise CheckFailure("oversize_local_not_admitted")
            if not _wait(lambda: producer.local_status().get("queued") == 0, timeout=8):
                raise CheckFailure("oversize_queue_not_drained")
            if not _wait(lambda: client.status()["body"]["admission_refused_units"] > pre, timeout=8):
                raise CheckFailure("oversize_drained_unaccounted")
            after_drain = client.status()["body"]["admission_refused_units"]
            self.counts["oversize_drained_refused_units"] = after_drain - pre
            query = client.query("process", process_id="proc-oversize", page_size=PAGE)["body"]
            if query.get("observations"):
                raise CheckFailure("oversize_appeared_in_query")
            if query.get("returned"):
                raise CheckFailure("oversize_query_returned")
        finally:
            producer.close()

        # Producer-local refusal is observable too, and is not double-counted by
        # the collector when it is refused before the sender ever ships it.
        big = Producer(
            sock,
            source_instance_id="oversize-local",
            limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000},
        )
        try:
            self._wait_enabled(big)
            collector_before = client.status()["body"]["admission_refused_units"]
            refused_before = big.local_status()["known_refused"]
            local_result = big.admit(_oversize_observation("oversize-local", units=40000))
            if local_result.admitted or local_result.code != "event_too_large":
                raise CheckFailure("oversize_local_not_refused")
            refused_after = big.local_status()["known_refused"]
            if refused_after != refused_before + 1:
                raise CheckFailure("oversize_local_unaccounted")
            time.sleep(0.3)
            if client.status()["body"]["admission_refused_units"] != collector_before:
                raise CheckFailure("oversize_local_double_counted")
            self.counts["oversize_local_known_refused"] = refused_after - refused_before
        finally:
            big.close()
        self.stop_owned()

    def _check_storage_failure(self):
        root, sock, _pid = self.start("storage-fail", freshness_window_ms=5000, heartbeat_interval_ms=50)
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        client.call("admit_batch", {"observations": [_sample("fail-source", sequence=1, process_id="kept")]})
        client.checkpoint()
        path = os.path.join(root, "observations.jsonl")
        before = open(path, "rb").read()
        os.chmod(path, 0o444)
        try:
            producer = Producer(
                sock,
                source_instance_id="fail-source",
                limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000},
            )
            try:
                self._wait_enabled(producer)
                blocked = _BlockedWork()
                result, waited = _watch(lambda: producer.admit(_sample("fail-source", sequence=2, process_id="lost")))
                if waited or blocked.finished():
                    raise CheckFailure("admission_waited_storage_failure")
                if result is None:
                    raise CheckFailure("admission_missing")
                if not _wait(lambda: client.checkpoint().get("body", {}).get("storage_failure") is True, timeout=8):
                    raise CheckFailure("storage_failure_not_disclosed")
            finally:
                producer.close()
            status = client.status()["body"]
            if not status["storage_failure"]:
                raise CheckFailure("storage_failure_not_disclosed")
            if open(path, "rb").read() != before:
                raise CheckFailure("storage_failure_rewrote")
            if not client.query("process", process_id="kept", page_size=PAGE)["body"]["observations"]:
                raise CheckFailure("storage_failure_lost_history")
            if client.query("process", process_id="lost", page_size=PAGE)["body"]["observations"]:
                raise CheckFailure("storage_failure_published")
        finally:
            os.chmod(path, 0o600)

    def check_durability(self):
        root, sock, pid = self.start("flush", freshness_window_ms=5000)
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        client.call("admit_batch", {"observations": [_sample("flush-source", text=INVENTED_TEXT)]})
        client.checkpoint()
        if client.status()["body"]["durable_seq"] < 1:
            raise CheckFailure("not_durable")
        epoch = client.status()["body"]["continuity_epoch"]
        self.stop_root(root, sock)
        self._wait_dead(pid)
        root, sock, pid = self.start("flush", freshness_window_ms=5000)
        client = Client(sock, timeout=5)
        status = client.status()["body"]
        if status["crash_tail"] != "none" or status["durable_seq"] < 1:
            raise CheckFailure("reopen")
        if status["continuity_epoch"] == epoch:
            raise CheckFailure("restart_kept_continuity")
        if status["desired_policy"] != "enabled":
            raise CheckFailure("policy_lost")
        phase = self.root("crash") + ".fifo"
        fd = _open_fifo(phase)
        try:
            os.write(fd, b"x")
            root, sock, pid = self.start(
                "crash",
                no_auto_checkpoint=True,
                publication_phase_hold=phase,
                freshness_window_ms=5000,
            )
            client = Client(sock, timeout=5)
            self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
            client.call("admit_batch", {"observations": [_sample("crash-source", sequence=1, process_id="proc-a")]})
            client.checkpoint()
            if not _wait(lambda: client.status().get("body", {}).get("durable_seq", 0) >= 1):
                raise CheckFailure("crash_baseline")
            known = client.status()["body"]["known_dropped_units"]
            client.call("admit_batch", {"observations": [_sample("crash-source", sequence=2, process_id="proc-b")]})
            thread = threading.Thread(target=client.checkpoint)
            thread.daemon = True
            thread.start()
            if not _wait(lambda: client.status().get("body", {}).get("publication_phase_hold") is True):
                raise CheckFailure("phase_hold")
            os.kill(pid, signal.SIGKILL)
            self._wait_dead(pid)
        finally:
            os.close(fd)
        root, sock, _pid = self.start("crash", freshness_window_ms=5000)
        client = Client(sock, timeout=5)
        status = client.status()["body"]
        if status["crash_tail"] != "unknown":
            raise CheckFailure("crash_tail_claimed_known")
        if status["known_dropped_units"] != known:
            raise CheckFailure("crash_counted_as_known_loss")
        present = client.query("process", process_id="proc-a", page_size=PAGE)
        absent = client.query("process", process_id="proc-b", page_size=PAGE)
        if not present["body"]["observations"] or absent["body"]["observations"]:
            raise CheckFailure("unpublished_tail_treated_durable")
        state = json.loads(open(os.path.join(root, "state.json"), "r").read())
        if state.get("crash_tail") != "unknown":
            raise CheckFailure("watermark_not_unknown")
        self.counts["discarded_unpublished_bytes"] = status["discarded_unpublished_bytes"]
        if status["discarded_unpublished_bytes"] <= 0:
            raise CheckFailure("no_unpublished_bytes")
        self._check_quarantine_tail()
        self._check_watermark_publication()

    def _check_watermark_publication(self):
        # A real file fault, not an injected append error: existing JSONL bytes
        # can be appended/fsynced while the watermark cannot be replaced.
        root, sock, pid = self.start("watermark-fail", management_timeout_ms=500)
        client = Client(sock, timeout=3)
        self._require(client.set_policy("enabled", 0))
        self._require(client.call("admit_batch", {"observations": [
            _sample("watermark-source", sequence=1, process_id="kept")]}))
        self._require(client.checkpoint())
        state_path = os.path.join(root, "state.json")
        obs_path = os.path.join(root, "observations.jsonl")
        with open(state_path) as handle:
            before = json.load(handle)
        with open(obs_path, "rb") as handle:
            prefix = handle.read()
        producer = Producer(sock, source_instance_id="watermark-source",
                            limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000})
        immutable = sys.platform == "darwin"
        try:
            self._wait_enabled(producer)
            if immutable:
                subprocess.run(["chflags", "uchg", state_path], check=True, capture_output=True)
            else:
                os.chmod(root, 0o500)
            result, waited = _watch(lambda: producer.admit(
                _sample("watermark-source", sequence=2, process_id="unpublished")))
            if waited or not result or not result.admitted:
                raise CheckFailure("watermark_admission_waited")
            if not _wait(lambda: client.status()["body"]["storage_failure"]):
                raise CheckFailure("watermark_failure_not_disclosed")
            status = client.status()["body"]
            query = client.query("process", process_id="unpublished")["body"]
            checkpoint = client.checkpoint()
            with open(state_path) as handle:
                persisted = json.load(handle)
            with open(obs_path, "rb") as handle:
                appended = handle.read()
            self.counts.update({
                "watermark_before_seq": before["durable_seq"],
                "watermark_failed_status_seq": status["durable_seq"],
                "watermark_failed_query_rows": query["returned"],
                "watermark_persisted_seq": persisted["durable_seq"],
                "watermark_appended_bytes": len(appended) - len(prefix),
                "watermark_checkpoint_seq": checkpoint.get("body", {}).get("durable_seq"),
            })
            os.kill(pid, signal.SIGKILL)
            self._wait_dead(pid)
        finally:
            producer.close()
            if immutable:
                subprocess.run(["chflags", "nouchg", state_path], check=True, capture_output=True)
            os.chmod(root, 0o700)
            os.chmod(state_path, 0o600)
        root, sock, pid = self.start("watermark-fail")
        reopened = Client(sock, timeout=3)
        restart = reopened.status()["body"]
        self.counts["watermark_reopened_seq"] = restart["durable_seq"]
        self.counts["watermark_reopened_discarded_bytes"] = restart["discarded_unpublished_bytes"]
        if len(appended) <= len(prefix) or not appended.startswith(prefix):
            raise CheckFailure("watermark_append_did_not_succeed")
        if persisted["durable_seq"] != before["durable_seq"] or persisted["durable_offset"] != before["durable_offset"]:
            raise CheckFailure("watermark_fault_did_not_hold")
        if not publication_matches_watermark(status["durable_seq"], query["as_of_durable_seq"], query["returned"], persisted["durable_seq"], status["durable_seq"]):
            raise CheckFailure("watermark_unpersisted_publication")
        if checkpoint.get("ok") and (checkpoint["body"]["durable_seq"] != persisted["durable_seq"] or not checkpoint["body"]["storage_failure"]):
            raise CheckFailure("watermark_false_checkpoint")
        if restart["durable_seq"] != before["durable_seq"] or restart["crash_tail"] != "unknown" or restart["known_dropped_units"] != before["known_dropped_units"]:
            raise CheckFailure("watermark_restart_invented_durability_or_loss")
        if restart["discarded_unpublished_bytes"] != len(appended) - len(prefix):
            raise CheckFailure("watermark_restart_tail")
        if reopened.query("process", process_id="kept")["body"]["returned"] != 1 or reopened.query("process", process_id="unpublished")["body"]["returned"]:
            raise CheckFailure("watermark_restart_prefix")

        # Hold the actual append/fsync-to-watermark interval. Concurrent public
        # reads must remain at the committed prefix; producer admission stays free.
        phase = self.root("watermark-held") + ".fifo"
        fd = _open_fifo(phase)
        try:
            os.write(fd, b"x")
            root, sock, pid = self.start("watermark-held", publication_phase_hold=phase,
                                         management_timeout_ms=500)
            client = Client(sock, timeout=3)
            self._require(client.set_policy("enabled", 0))
            self._require(client.call("admit_batch", {"observations": [
                _sample("held-source", sequence=1, process_id="kept")]}))
            self._require(client.checkpoint())
            producer = Producer(sock, source_instance_id="held-source",
                                limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000})
            try:
                self._wait_enabled(producer)
                result, waited = _watch(lambda: producer.admit(
                    _sample("held-source", sequence=2, process_id="pending")))
                if waited or not result.admitted:
                    raise CheckFailure("held_watermark_admission_waited")
                if not _wait(lambda: client.status()["body"]["publication_phase_hold"]):
                    raise CheckFailure("watermark_hold_not_active")
                checkpoints = []
                thread = threading.Thread(target=lambda: checkpoints.append(client.checkpoint()))
                thread.start()
                result, waited = _watch(lambda: producer.admit(
                    _sample("held-source", sequence=3, process_id="pending-next")))
                if waited or not result.admitted:
                    raise CheckFailure("held_watermark_concurrent_admission_waited")
                for _ in range(8):
                    status = client.status()["body"]
                    query = client.query("process", process_id="pending")["body"]
                    with open(os.path.join(root, "state.json")) as handle:
                        disk = json.load(handle)
                    if status["durable_seq"] != 1 or disk["durable_seq"] != 1 or query["returned"] or query["as_of_durable_seq"] != 1:
                        raise CheckFailure("held_watermark_visible")
                self.counts["watermark_held_public_reads"] = 8
                thread.join(timeout=3)
                if thread.is_alive() or not checkpoints or checkpoints[0].get("body", {}).get("durable_seq") != 1:
                    raise CheckFailure("held_watermark_false_checkpoint")
                os.write(fd, b"xx")
                self._wait_durable(client, 3)
                self._require(client.checkpoint())
            finally:
                producer.close()
            self.stop_root(root, sock)
            self._wait_dead(pid)
            root, sock, pid = self.start("watermark-held")
            client = Client(sock, timeout=3)
            if client.status()["body"]["durable_seq"] != 3 or client.query("process", process_id="pending")["body"]["returned"] != 1:
                raise CheckFailure("watermark_healthy_restart")
        finally:
            os.close(fd)

    def check_policy(self):
        root, sock, pid = self.start("policy", freshness_window_ms=400, heartbeat_interval_ms=50)
        initial = self.cli("--json", "--socket", sock, "status")
        if initial.returncode != 0:
            raise CheckFailure("status_cli")
        body = json.loads(initial.stdout)
        if body["body"]["desired_policy"] != "off" or body["body"]["globally_effective"]:
            raise CheckFailure("initial_effective")
        if "separately_configured_may_continue" not in initial.stdout:
            raise CheckFailure("legacy_disclosure")
        if body["body"]["legacy_switch_changed"] is not False:
            raise CheckFailure("legacy_switch")
        enabled = self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        if enabled.returncode != 0:
            raise CheckFailure("enable")
        producer = Producer(
            sock,
            source_instance_id="stale-source",
            limits={"heartbeat_interval_ms": 60000, "freshness_window_ms": 400},
        )
        try:
            if not _wait(lambda: _producer_seen(Client(sock, timeout=2))):
                raise CheckFailure("producer_not_seen")
            time.sleep(0.6)
            status = Client(sock, timeout=2).status()["body"]
            if status["globally_effective"]:
                raise CheckFailure("stale_reported_effective")
            observations = status["producer_observations"]
            if not observations or observations[0]["freshness"] != "stale":
                raise CheckFailure("stale_not_labeled")
            if status["desired_policy"] != "enabled":
                raise CheckFailure("stale_while_disabled")
        finally:
            producer.close()
        # ARCH188-4: a request that declares an older observed revision must be
        # recorded as declaring it. The revision delivered by the response is not
        # an acknowledgement, so status must not call that caller effective.
        client = Client(sock, timeout=3)
        desired_revision = client.status()["body"]["desired_revision"]
        stale_revision = desired_revision - 1
        if stale_revision < 0:
            raise CheckFailure("stale_observation_unavailable")
        stale_response = client.call(
            "policy_observe",
            {"source_instance_id": "declared-stale", "observed_revision": stale_revision},
        )
        if not stale_response.get("ok"):
            raise CheckFailure("stale_observation_refused")
        stale_entry = _producer_entry(client, "declared-stale")
        if stale_entry is None:
            raise CheckFailure("stale_declaration_not_recorded")
        if stale_entry["observed_revision"] != stale_revision:
            raise CheckFailure("stale_declaration_overwritten")
        if stale_entry["matches_desired_revision"] or stale_entry["effective"]:
            raise CheckFailure("stale_declaration_effective")
        if client.status()["body"]["globally_effective"]:
            raise CheckFailure("stale_call_globally_effective")
        self.counts["policy_declared_stale_revision"] = stale_entry["observed_revision"]

        # A later observation that reports the delivered revision is what
        # acknowledges it, and only then is that producer effective.
        match_response = client.call(
            "policy_observe",
            {"source_instance_id": "declared-stale", "observed_revision": desired_revision},
        )
        if not match_response.get("ok"):
            raise CheckFailure("matching_observation_refused")
        match_entry = _producer_entry(client, "declared-stale")
        if match_entry is None or match_entry["observed_revision"] != desired_revision:
            raise CheckFailure("matching_declaration_not_recorded")
        if not match_entry["matches_desired_revision"] or not match_entry["effective"]:
            raise CheckFailure("matching_declaration_not_effective")
        # Other producers seen earlier may still be inside their freshness window,
        # so assert this producer's entry rather than blanket global effectiveness.
        self.counts["policy_matching_revision"] = match_entry["observed_revision"]

        # The producer's own polling edge: it reports the revision delivered in the
        # response, and the collector records that only as a declaration until the
        # next observation reports it.
        polled = Producer(
            sock,
            source_instance_id="polled-source",
            limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 2000},
        )
        try:
            if not _wait(lambda: _producer_acknowledged(client, "polled-source", desired_revision),
                         timeout=8):
                raise CheckFailure("producer_poll_not_acknowledged")
            local = polled.local_status()
            if local["observed_revision"] != desired_revision or not local["fresh"]:
                raise CheckFailure("producer_poll_local_status")
            self.counts["policy_polled_revision"] = local["observed_revision"]
        finally:
            polled.close()
        stale = self.cli("--socket", sock, "policy", "pause", "--expect-revision", "0")
        if stale.returncode == 0 or "stale_revision" not in stale.stdout + stale.stderr:
            raise CheckFailure("stale_revision")
        paused = self.cli("--socket", sock, "policy", "pause", "--expect-revision", "1")
        if paused.returncode != 0:
            raise CheckFailure("pause")
        self.stop_root(root, sock)
        self._wait_dead(pid)
        root, sock, pid = self.start("policy", freshness_window_ms=5000)
        status = self.cli("--socket", sock, "status")
        if "desired_policy=paused" not in status.stdout:
            raise CheckFailure("pause_not_durable")
        refused = Client(sock, timeout=3).call("admit_batch", {"observations": [_sample("policy-source", sequence=3)]})
        if "capture_disabled" not in refused.get("body", {}).get("codes", []):
            raise CheckFailure("paused_interval_collected")
        before = Client(sock, timeout=3).status()["body"]["durable_seq"]
        resumed = self.cli("--socket", sock, "policy", "resume", "--expect-revision", "2")
        if resumed.returncode != 0:
            raise CheckFailure("resume")
        after = Client(sock, timeout=3).query("timeline", page_size=PAGE)
        if after["body"]["as_of_durable_seq"] != before:
            raise CheckFailure("resume_backfill")
        self._drive_tui_pause(sock)
        self.counts["policy_revision"] = Client(sock, timeout=3).status()["body"]["desired_revision"]

    def check_privacy(self):
        self._review_imports()
        real = self.root("symlink-target")
        os.mkdir(real)
        link = self.root("symlink-root")
        os.symlink(real, link)
        self.start_rejected(link)
        if os.path.exists(os.path.join(real, "policy.json")) or os.path.exists(os.path.join(real, "observations.jsonl")):
            raise CheckFailure("symlink_written")
        self.start_rejected("/bin")
        cloud = os.path.join(self.workspace, "Dropbox", "archive")
        self.start_rejected(cloud)
        if os.path.exists(cloud):
            raise CheckFailure("cloud_written")
        root, sock, pid = self.start("privacy", freshness_window_ms=5000, heartbeat_interval_ms=50)
        self._assert_modes(root)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        client = Client(sock, timeout=5)
        client.call("admit_batch", {"observations": [_sample("priv-source", sequence=1, process_id="proc-body", text=CANARY)]})
        client.call("admit_batch", {"observations": [{
            "envelope_version": 1,
            "content_version": 1,
            "schema_id": "luna_pinyin",
            "source_instance_id": "priv-source",
            "source_local_sequence": 2,
            "observation_kind": "input_change",
            "process_id": "proc-excluded",
            "eligibility": "excluded",
            "payload": {"text": EXCL},
        }]})
        client.call("admit_batch", {"observations": [_sample("priv-source", sequence=3, process_id="proc-esc", text="\x1b[2J" + ESC_MARK)]})
        client.checkpoint()
        ordinary = []
        for args in (
            ("--socket", sock, "status"),
            ("--socket", sock, "query", "overview"),
            ("--socket", sock, "query", "timeline", "--page-size", "20"),
            ("--socket", sock, "query", "process", "--process-id", "proc-body"),
        ):
            proc = self.cli(*args)
            ordinary.append(proc.stdout + proc.stderr)
        bad = client.call("status", {"payload": {"text": CANARY}}, envelope_version=99)
        ordinary.append(json.dumps(bad))
        joined = "\n".join(ordinary)
        for marker in (CANARY, EXCL, ESC_MARK):
            if marker in joined:
                raise CheckFailure("canary_leak:ordinary")
        if "\x1b" in joined:
            raise CheckFailure("escape_in_ordinary")
        private = self.cli("--socket", sock, "query", "process", "--process-id", "proc-body", "--private-detail")
        if CANARY not in private.stdout:
            raise CheckFailure("private_detail_missing")
        if EXCL in private.stdout:
            raise CheckFailure("excluded_in_detail")
        files = _scan_tree(root)
        if EXCL in files["blob"]:
            raise CheckFailure("excluded_stored")
        if CANARY not in open(os.path.join(root, "observations.jsonl"), "r").read():
            raise CheckFailure("body_not_in_artifact")
        for name in ("state.json", "policy.json", "collector.err", "collector.out"):
            if CANARY in open(os.path.join(root, name), "r", errors="ignore").read():
                raise CheckFailure("canary_leak:" + name)
        escaped = _tui_capture(sock, ["expand proc-esc", "quit"], repo=REPO)
        if b"\x1b" in escaped:
            raise CheckFailure("terminal_escape")
        if ESC_MARK.encode() not in escaped:
            raise CheckFailure("escaped_detail_missing")
        self._assert_no_tcp(pid)
        self._check_aliases()
        self.counts["privacy_files"] = len(files["names"])

    def check_capacity(self):
        self._assert_docs_limits()
        for count, name in ((100, "scale100"), (10000, "scale10000")):
            root, sock, pid = self.start(name, freshness_window_ms=5000, heartbeat_interval_ms=50)
            client = Client(sock, timeout=8)
            self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
            producer = Producer(
                sock,
                source_instance_id="scale-" + name,
                limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000, "producer_queue_count": 256},
            )
            try:
                self._wait_enabled(producer)
                pending = [scale_observation(index, "scale-" + name) for index in range(1, count + 1)]
                deadline = time.time() + (30 if count < 1000 else 90)
                while pending and time.time() < deadline:
                    result = producer.admit(pending[0])
                    if result.admitted:
                        pending.pop(0)
                    elif result.code == "queue_saturated":
                        time.sleep(0.01)
                    else:
                        raise CheckFailure("scale_refused")
                if pending:
                    raise CheckFailure("scale_timeout")
                if not _wait(lambda: producer.local_status().get("queued") == 0, timeout=60):
                    raise CheckFailure("scale_not_shipped")
                if not _wait(lambda: client.checkpoint().get("body", {}).get("durable_seq", 0) >= count, timeout=90):
                    raise CheckFailure("scale_not_durable")
            finally:
                producer.close()
            page = client.query("timeline", page_size=PAGE)
            self._require(page)
            if page["body"]["returned"] != PAGE:
                raise CheckFailure("page_bound_not_applied")
            encoded = json.dumps(strip_content(page))
            if len(encoded) > 65536 or CANARY in encoded:
                raise CheckFailure("page_unbounded")
            over = client.query("timeline", page_size=DEFAULTS["page_size_max"] + 1)
            if (over.get("error") or {}).get("code") != "page_bound":
                raise CheckFailure("page_bound_refusal")
            rss = _rss_kb(pid)
            self.counts[name + "_page"] = page["body"]["returned"]
            self.counts[name + "_response_bytes"] = len(encoded)
            self.counts[name + "_rss_kb"] = rss
            self.counts[name + "_processes"] = count
            self.stop_owned()
        root, sock, _pid = self.start(
            "capacity",
            archive_capacity_bytes=12000,
            warning_ratio=0.5,
            freshness_window_ms=5000,
        )
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        warned = False
        stopped = False
        first_id = "cap-1"
        for index in range(1, 80):
            client.call("admit_batch", {"observations": [_sample("cap-source", sequence=index, process_id="cap-%s" % index, text="x")]})
            client.checkpoint()
            status = client.status()["body"]
            if status["warning"]:
                warned = True
            if status["capacity_stop"]:
                stopped = True
                break
        if not warned or not stopped:
            raise CheckFailure("capacity_warning")
        digest = _file_sha(os.path.join(root, "observations.jsonl"))
        before = client.status()["body"]["durable_seq"]
        client.call("admit_batch", {"observations": [_sample("cap-source", sequence=90, process_id="cap-overflow", text="y")]})
        client.checkpoint()
        if _file_sha(os.path.join(root, "observations.jsonl")) != digest:
            raise CheckFailure("capacity_overwrite")
        if client.status()["body"]["durable_seq"] != before:
            raise CheckFailure("capacity_advanced")
        if not client.query("process", process_id=first_id, page_size=PAGE)["body"]["observations"]:
            raise CheckFailure("capacity_lost_history")
        self.counts["capacity_durable_seq"] = before

    def check_walkthrough(self):
        root, sock, pid = self.start("walk", freshness_window_ms=5000, heartbeat_interval_ms=50)
        transcript = []
        started = self.cli("--socket", sock, "status")
        transcript.append(started.stdout)
        enabled = self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        transcript.append(enabled.stdout)
        fixture = os.path.join(root, "fixture.json")
        observations = supported_processes("walk-source")
        fd = os.open(fixture, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.write(fd, json.dumps({"observations": observations}).encode("utf-8"))
        os.close(fd)
        admitted = self.cli(
            "--socket", sock, "--timeout", "8", "admit",
            "--fixture", fixture, "--source-instance-id", "walk-source",
        )
        transcript.append(admitted.stdout)
        Client(sock, timeout=5).checkpoint()
        if not _wait(lambda: Client(sock, timeout=2).status().get("body", {}).get("durable_seq", 0) >= 1):
            raise CheckFailure("walk_not_durable")
        first = _tui_session(sock, ["timeline", "expand proc-commit", "pause", "quit"])
        transcript.append(first.decode("utf-8", "replace"))
        if b"SCREEN overview" not in first or b"SCREEN timeline" not in first or b"SCREEN private-detail" not in first:
            raise CheckFailure("walk_screens")
        if INVENTED_TEXT.encode() in first.split(b"SCREEN private-detail")[0]:
            raise CheckFailure("walk_overview_leaked")
        if INVENTED_TEXT.encode() not in first.split(b"SCREEN private-detail")[1]:
            raise CheckFailure("walk_detail_missing")
        if not _alive(pid):
            raise CheckFailure("tui_stopped_collector")
        status = Client(sock, timeout=3).status()["body"]
        if status["desired_policy"] != "paused":
            raise CheckFailure("tui_pause")
        second = _tui_session(sock, ["quit"])
        transcript.append(second.decode("utf-8", "replace"))
        if b"desired_policy=paused" not in second:
            raise CheckFailure("tui_reopen")
        if not _alive(pid):
            raise CheckFailure("tui_reopen_stopped_collector")
        self.stop_root(root, sock)
        self._wait_dead(pid)
        root, sock, pid = self.start("walk", freshness_window_ms=5000)
        restarted = self.cli("--socket", sock, "status")
        transcript.append(restarted.stdout)
        if "desired_policy=paused" not in restarted.stdout:
            raise CheckFailure("walk_restart_pause")
        if not Client(sock, timeout=3).query("process", process_id="proc-commit", page_size=PAGE)["body"]["observations"]:
            raise CheckFailure("walk_record_lost")
        path = os.path.join(root, "walkthrough.txt")
        blob = "\n".join(transcript).encode("utf-8")
        out = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.write(out, blob)
        os.close(out)
        self.walkthrough_sha = hashlib.sha256(blob).hexdigest()
        self.counts["walkthrough_bytes"] = len(blob)

    def check_usability(self):
        self._assert_docs_contract()
        fresh = os.path.join(self.workspace, "fresh")
        archive_src = os.path.join(REPO, "archive")
        shutil.copytree(archive_src, os.path.join(fresh, "archive"))
        root = os.path.join(fresh, "demo")
        os.makedirs(os.path.dirname(root), exist_ok=True)
        sock = os.path.join(root, "collector.sock")
        start = subprocess.run(
            [sys.executable, "-m", "archive.cli", "--root", root, "--socket", sock, "collector", "start"],
            cwd=fresh, capture_output=True, text=True, timeout=20,
        )
        self._ordinary(start.stdout, start.stderr)
        if start.returncode != 0 or "capture_enabled=false" not in start.stdout:
            raise CheckFailure("fresh_start")
        status = subprocess.run(
            [sys.executable, "-m", "archive.cli", "--socket", sock, "status"],
            cwd=fresh, capture_output=True, text=True, timeout=10,
        )
        if status.returncode != 0 or "desired_policy=off" not in status.stdout:
            raise CheckFailure("fresh_status")
        stop = subprocess.run(
            [sys.executable, "-m", "archive.cli", "--root", root, "--socket", sock, "collector", "stop"],
            cwd=fresh, capture_output=True, text=True, timeout=15,
        )
        if stop.returncode != 0:
            raise CheckFailure("fresh_stop")
        example = Client(sock, timeout=1).status()
        if example.get("ok"):
            raise CheckFailure("fresh_still_running")
        self.counts["documented_defaults"] = len(DEFAULTS)

    def check_ownership_lifecycle(self):
        """SCN5: the repaired ownership/readiness/cleanup seam, over real
        subprocesses and the public Interface."""
        scenarios = [
            ("SCN5-1", ("ARCH188-7",), self.scenario_reproduced_race),
            ("SCN5-2", ("ARCH188-4", "ARCH188-3"), self.scenario_seeded_race),
            ("SCN5-3", ("ARCH188-7",), self.scenario_incumbent_and_entrypoint),
            ("SCN5-4", ("ARCH188-3",), self.scenario_killed_owner),
            ("SCN5-5", ("ARCH188-7",), self.scenario_failed_startup),
            ("SCN5-6", ("ARCH188-5",), self.scenario_artifact_safety),
            ("SCN5-7", ("ARCH188-7",), self.scenario_root_locality),
        ]
        for name, criteria, fn in scenarios:
            prefix = name.lower().replace("-", "")
            try:
                observation = fn() or {}
                self.counts[prefix + "_executed"] = 1
                for key, value in observation.items():
                    self.counts[prefix + "_" + key] = value
            except CheckFailure as exc:
                for criterion in criteria:
                    self.results[criterion].append("%s:%s" % (prefix, exc.code))
            except Exception:
                for criterion in criteria:
                    self.results[criterion].append("%s:unexpected" % prefix)
            finally:
                self.stop_owned()
        self.counts["ownership_scenarios_required"] = len(scenarios)

    def scenario_reproduced_race(self):
        """SCN5-1: five fresh roots, two concurrent supported starts each."""
        rounds = 0
        refusals = 0
        survivors = 0
        for index in range(5):
            name = "ownership/race-%d" % index
            root = self.fresh_private_root(name)
            sock = os.path.join(root, "collector.sock")
            pid, _success, _loser, _results = self._race(root, sock)
            stopped = self.stop_root(root, sock)
            if stopped.returncode != 0:
                raise CheckFailure("race_stop")
            if not self.wait_no_fixture_collectors(root):
                survivors = max(survivors, len(self.fixture_collectors(root)))
                raise CheckFailure("race_survivor_after_stop")
            restarted = self.start(name, freshness_window_ms=5000)
            if self.fixture_collectors(root) != [restarted[2]]:
                raise CheckFailure("race_restart_owners")
            self.stop_root(root, sock)
            if not self.wait_no_fixture_collectors(root):
                survivors = max(survivors, len(self.fixture_collectors(root)))
                raise CheckFailure("race_restart_survivor")
            rounds += 1
            refusals += 1
        if not survivors_are_zero(survivors):
            raise CheckFailure("race_survivors")
        return {
            "rounds": rounds,
            "refusals": refusals,
            "survivors_after_stop": survivors,
            "restarts": rounds,
        }

    def scenario_seeded_race(self):
        """SCN5-2: a real durable commit and paused policy survive a raced start."""
        name = "ownership/seeded"
        root = self.fresh_private_root(name)
        sock = os.path.join(root, "collector.sock")
        _root, _sock, pid = self.start(name, freshness_window_ms=5000, heartbeat_interval_ms=50)
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        client.call(
            "admit_batch",
            {"observations": [_sample("seeded-source", sequence=1, process_id="proc-seeded", text=INVENTED_TEXT)]},
        )
        self._wait_durable(client, 1)
        self.cli("--socket", sock, "policy", "pause", "--expect-revision", "1")
        before = client.status()["body"]
        rows_before = client.query("process", process_id="proc-seeded", page_size=PAGE)["body"]["observations"]
        if not rows_before:
            raise CheckFailure("seeded_prefix_missing")
        self.stop_root(root, sock)
        self._wait_dead(pid)
        winner, _success, _loser, _results = self._race(root, sock)
        after_client = Client(sock, timeout=5)
        status = after_client.status()["body"]
        if status["durable_seq"] != before["durable_seq"] or status["durable_bytes"] != before["durable_bytes"]:
            raise CheckFailure("seeded_prefix_mutated")
        if status["desired_policy"] != "paused" or status["desired_revision"] != before["desired_revision"]:
            raise CheckFailure("seeded_policy_mutated")
        if status["discarded_unpublished_bytes"] or status["discarded_quarantine_bytes"]:
            raise CheckFailure("loser_reconciliation")
        if status["storage_failure"] or status["crash_tail"] != "none":
            raise CheckFailure("seeded_state_unhealthy")
        rows_after = after_client.query("process", process_id="proc-seeded", page_size=PAGE)["body"]["observations"]
        if len(rows_after) != len(rows_before) or rows_after[0]["durable_seq"] != rows_before[0]["durable_seq"]:
            raise CheckFailure("seeded_record_lost")
        refused = after_client.call(
            "admit_batch",
            {"observations": [_sample("seeded-source", sequence=2, process_id="proc-seeded-later")]},
        )
        if refused.get("body", {}).get("codes") != ["capture_disabled"]:
            raise CheckFailure("seeded_pause_not_effective")
        self.stop_root(root, sock)
        self._wait_dead(winner)
        again = self.start(name, freshness_window_ms=5000)
        final = Client(sock, timeout=5).status()["body"]
        if final["durable_seq"] != before["durable_seq"] or final["desired_policy"] != "paused":
            raise CheckFailure("seeded_restart_lost")
        if len(Client(sock, timeout=5).query("process", process_id="proc-seeded", page_size=PAGE)["body"]["observations"]) != len(rows_before):
            raise CheckFailure("seeded_restart_record_lost")
        return {
            "durable_seq": before["durable_seq"],
            "durable_bytes": before["durable_bytes"],
            "policy_revision": before["desired_revision"],
            "epoch_changed": int(final["collector_epoch"] != before["collector_epoch"]),
            "loser_reconciliation": 0,
            "restart_owner": again[2],
        }

    def scenario_incumbent_and_entrypoint(self):
        """SCN5-3: incumbent plus duplicate CLI start and the direct entry."""
        name = "ownership/incumbent"
        root = self.fresh_private_root(name)
        sock = os.path.join(root, "collector.sock")
        _root, _sock, pid = self.start(name, freshness_window_ms=5000, heartbeat_interval_ms=50)
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        client.call(
            "admit_batch",
            {"observations": [_sample("incumbent-source", sequence=1, process_id="proc-incumbent", text=INVENTED_TEXT)]},
        )
        self._wait_durable(client, 1)
        before = client.status()["body"]
        inode_before = os.lstat(sock).st_ino
        duplicate = self.start_async(root, sock)
        try:
            stdout, stderr = duplicate.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            duplicate.kill()
            raise CheckFailure("duplicate_start_hung")
        self._ordinary(stdout, stderr)
        if duplicate.returncode == 0:
            raise CheckFailure("duplicate_claimed_success")
        if "collector_started=true" in stdout or _pid_from_text(stdout) is not None:
            raise CheckFailure("duplicate_claimed_owner")
        if "code=collector_already_running" not in stderr:
            raise CheckFailure("duplicate_code")
        direct = self.direct_entry(root, sock)
        self._ordinary(direct.stdout, direct.stderr)
        if direct.returncode == 0:
            raise CheckFailure("direct_entry_accepted")
        if "code=collector_already_running" not in direct.stderr:
            raise CheckFailure("direct_entry_code")
        if self.fixture_collectors(root) != [pid]:
            raise CheckFailure("incumbent_not_alone")
        if os.lstat(sock).st_ino != inode_before:
            raise CheckFailure("incumbent_socket_replaced")
        status = client.status()
        self._require(status)
        if status["body"].get("owner_pid") != pid:
            raise CheckFailure("incumbent_owner_changed")
        after = status["body"]
        if after["durable_seq"] != before["durable_seq"] or after["desired_revision"] != before["desired_revision"]:
            raise CheckFailure("incumbent_state_changed")
        rows = client.query("process", process_id="proc-incumbent", page_size=PAGE)["body"]["observations"]
        if len(rows) != 1:
            raise CheckFailure("incumbent_prefix_lost")
        self.stop_root(root, sock)
        if not self.wait_no_fixture_collectors(root):
            raise CheckFailure("incumbent_survivor")
        return {
            "duplicate_exit": duplicate.returncode,
            "direct_entry_exit": direct.returncode,
            "incumbent_socket_replaced": 0,
            "survivors": 0,
        }

    def scenario_killed_owner(self):
        """SCN5-4: SIGKILL the owner, leave stale metadata, restart normally."""
        name = "ownership/killed"
        root = self.fresh_private_root(name)
        sock = os.path.join(root, "collector.sock")
        _root, _sock, pid = self.start(name, freshness_window_ms=5000, heartbeat_interval_ms=50)
        client = Client(sock, timeout=5)
        self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
        client.call(
            "admit_batch",
            {"observations": [_sample("killed-source", sequence=1, process_id="proc-killed", text=INVENTED_TEXT)]},
        )
        self._wait_durable(client, 1)
        before = client.status()["body"]
        os.kill(pid, signal.SIGKILL)
        self._wait_dead(pid)
        # The product leaves its stale PID, socket, and lock artifacts in place.
        for artifact in ("collector.pid", "collector.sock", "collector.lock"):
            if not os.path.lexists(os.path.join(root, artifact)):
                raise CheckFailure("stale_metadata_missing:" + artifact)
        _root, _sock, new_pid = self.start(name, freshness_window_ms=5000)
        if self.fixture_collectors(root) != [new_pid]:
            raise CheckFailure("killed_reclaim_owners")
        reopened = Client(sock, timeout=5)
        status = reopened.status()
        self._require(status)
        body = status["body"]
        if body["durable_seq"] != before["durable_seq"] or body["durable_bytes"] != before["durable_bytes"]:
            raise CheckFailure("killed_prefix_mutated")
        if body["crash_tail"] != "unknown" or not body["unclean_shutdown_observed"]:
            raise CheckFailure("killed_tail_dishonest")
        if body["desired_revision"] != before["desired_revision"] or body["storage_failure"]:
            raise CheckFailure("killed_policy_lost")
        rows = reopened.query("process", process_id="proc-killed", page_size=PAGE)["body"]["observations"]
        if len(rows) != 1:
            raise CheckFailure("killed_record_lost")
        self.stop_root(root, sock)
        if not self.wait_no_fixture_collectors(root):
            raise CheckFailure("killed_restart_survivor")
        return {
            "durable_seq": before["durable_seq"],
            "manual_unlock": 0,
            "archive_edits": 0,
            "crash_tail": body["crash_tail"],
        }

    def scenario_failed_startup(self):
        """SCN5-5: one bounded real prepare/bind failure after ownership."""
        name = "ownership/bind-fault"
        root = self.fresh_private_root(name)
        sock = os.path.join(root, "collector.sock")
        os.mkdir(sock, 0o700)
        direct = self.direct_entry(root, sock)
        self._ordinary(direct.stdout, direct.stderr)
        if direct.returncode == 0 or "code=unsafe_root" not in direct.stderr:
            raise CheckFailure("bind_fault_accepted")
        if not os.path.isdir(sock) or os.path.islink(sock):
            raise CheckFailure("bind_fault_artifact_removed")
        if self.fixture_collectors(root):
            raise CheckFailure("bind_fault_orphan")
        cli_attempt = self.start_async(root, sock)
        try:
            stdout, stderr = cli_attempt.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            cli_attempt.kill()
            raise CheckFailure("bind_fault_start_hung")
        self._ordinary(stdout, stderr)
        if cli_attempt.returncode == 0 or "collector_started=true" in stdout:
            raise CheckFailure("bind_fault_claimed_success")
        if "code=unsafe_root" not in stderr:
            raise CheckFailure("bind_fault_code")
        if not os.path.isdir(sock):
            raise CheckFailure("bind_fault_artifact_removed_cli")
        if self.fixture_collectors(root):
            raise CheckFailure("bind_fault_orphan_cli")
        # Correct only the owned fault: exclusion was not leaked to a dead owner.
        os.rmdir(sock)
        recovered = self.start(name, freshness_window_ms=5000)
        self.stop_root(root, sock)
        if not self.wait_no_fixture_collectors(root):
            raise CheckFailure("bind_fault_reclaim_survivor")
        # An incumbent survives a contender whose own socket target is blocked.
        incumbent_name = "ownership/incumbent-fault"
        incumbent_root = self.fresh_private_root(incumbent_name)
        incumbent_sock = os.path.join(incumbent_root, "collector.sock")
        _root, _sock, incumbent = self.start(incumbent_name, freshness_window_ms=5000)
        blocked = os.path.join(incumbent_root, "blocked.sock")
        os.mkdir(blocked, 0o700)
        contender = self.start_async(incumbent_root, blocked)
        try:
            contender_out, contender_err = contender.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            contender.kill()
            raise CheckFailure("incumbent_contender_hung")
        self._ordinary(contender_out, contender_err)
        if contender.returncode == 0:
            raise CheckFailure("incumbent_contender_accepted")
        if "code=collector_already_running" not in contender_err:
            raise CheckFailure("incumbent_contender_code")
        if self.fixture_collectors(incumbent_root) != [incumbent]:
            raise CheckFailure("incumbent_contender_survivor")
        if not os.path.isdir(blocked):
            raise CheckFailure("incumbent_contender_removed_path")
        self._require(Client(incumbent_sock, timeout=5).status())
        self.stop_root(incumbent_root, incumbent_sock)
        if not self.wait_no_fixture_collectors(incumbent_root):
            raise CheckFailure("incumbent_fault_survivor")
        return {
            "phase": "socket_bind",
            "child_exit": direct.returncode,
            "cli_exit": cli_attempt.returncode,
            "orphans": 0,
            "reclaim_after_fix": recovered[2],
        }

    def scenario_artifact_safety(self):
        """SCN5-6: the ownership artifact is private, regular, and non-aliased."""
        parent = self.fresh_private_root("ownership/artifact")
        target = os.path.join(parent, "alias-target")
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
        os.write(fd, b"SEED")
        os.close(fd)
        os.chmod(target, 0o644)
        alias_root = self.fresh_private_root("ownership/artifact/alias-root")
        lock = os.path.join(alias_root, "collector.lock")
        os.symlink(target, lock)
        attempt = self.start_async(alias_root, os.path.join(alias_root, "collector.sock"))
        try:
            stdout, stderr = attempt.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            attempt.kill()
            raise CheckFailure("lock_alias_start_hung")
        self._ordinary(stdout, stderr)
        if attempt.returncode == 0:
            raise CheckFailure("lock_alias_accepted")
        if "code=unsafe_root" not in stderr:
            raise CheckFailure("lock_alias_code")
        if not os.path.islink(lock):
            raise CheckFailure("lock_alias_replaced")
        if open(target, "rb").read() != b"SEED" or stat.S_IMODE(os.lstat(target).st_mode) != 0o644:
            raise CheckFailure("lock_alias_target_mutated")
        if self.fixture_collectors(alias_root):
            raise CheckFailure("lock_alias_orphan")
        fifo_root = self.fresh_private_root("ownership/artifact/fifo-root")
        fifo_lock = os.path.join(fifo_root, "collector.lock")
        os.mkfifo(fifo_lock, 0o600)
        fifo = self.direct_entry(fifo_root, os.path.join(fifo_root, "collector.sock"))
        self._ordinary(fifo.stdout, fifo.stderr)
        if fifo.returncode == 0 or "code=unsafe_root" not in fifo.stderr:
            raise CheckFailure("lock_fifo_accepted")
        if not stat.S_ISFIFO(os.lstat(fifo_lock).st_mode):
            raise CheckFailure("lock_fifo_replaced")
        dir_root = self.fresh_private_root("ownership/artifact/dir-root")
        dir_lock = os.path.join(dir_root, "collector.lock")
        os.mkdir(dir_lock, 0o700)
        as_dir = self.direct_entry(dir_root, os.path.join(dir_root, "collector.sock"))
        self._ordinary(as_dir.stdout, as_dir.stderr)
        if as_dir.returncode == 0 or "code=unsafe_root" not in as_dir.stderr:
            raise CheckFailure("lock_directory_accepted")
        if not os.path.isdir(dir_lock) or os.path.islink(dir_lock):
            raise CheckFailure("lock_directory_replaced")
        name = "ownership/artifact/stable"
        stable_root = self.fresh_private_root(name)
        stable_sock = os.path.join(stable_root, "collector.sock")
        _root, _sock, pid = self.start(name, freshness_window_ms=5000)
        stable_lock = os.path.join(stable_root, "collector.lock")
        inode_before = os.lstat(stable_lock).st_ino
        contender = self.start_async(stable_root, stable_sock)
        try:
            contender.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            contender.kill()
            raise CheckFailure("lock_contender_hung")
        if not lock_identity_is_stable(inode_before, os.lstat(stable_lock).st_ino):
            raise CheckFailure("lock_inode_moved_on_contention")
        self.stop_root(stable_root, stable_sock)
        self._wait_dead(pid)
        self.start(name, freshness_window_ms=5000)
        if not lock_identity_is_stable(inode_before, os.lstat(stable_lock).st_ino):
            raise CheckFailure("lock_inode_moved_on_restart")
        info = os.lstat(stable_lock)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
            raise CheckFailure("lock_artifact_mode")
        self._assert_modes(stable_root)
        self.stop_root(stable_root, stable_sock)
        if not self.wait_no_fixture_collectors(stable_root):
            raise CheckFailure("lock_restart_survivor")
        return {
            "alias_refused": 1,
            "non_regular_refused": 1,
            "directory_refused": 1,
            "inode_stable": 1,
            "mode": "0600",
        }

    def scenario_root_locality(self):
        """SCN5-7: distinct roots are independent, and the healthy flow holds."""
        name_a = "ownership/locality-a"
        name_b = "ownership/locality-b"
        root_a = self.fresh_private_root(name_a)
        sock_a = os.path.join(root_a, "collector.sock")
        root_b = self.fresh_private_root(name_b)
        sock_b = os.path.join(root_b, "collector.sock")
        _root, _sock, pid_a = self.start(name_a, freshness_window_ms=5000, heartbeat_interval_ms=50)
        _root, _sock, pid_b = self.start(name_b, freshness_window_ms=5000, heartbeat_interval_ms=50)
        if pid_a == pid_b:
            raise CheckFailure("locality_shared_owner")
        if self.fixture_collectors(root_a) != [pid_a] or self.fixture_collectors(root_b) != [pid_b]:
            raise CheckFailure("locality_owners")
        client_a = Client(sock_a, timeout=5)
        client_b = Client(sock_b, timeout=5)
        self.cli("--socket", sock_a, "policy", "enable", "--expect-revision", "0")
        client_a.call(
            "admit_batch",
            {"observations": [_sample("locality-a", sequence=1, process_id="proc-a", text=INVENTED_TEXT)]},
        )
        self._wait_durable(client_a, 1)
        other = client_b.status()["body"]
        if other["durable_seq"] != 0 or other["desired_revision"] != 0 or other["desired_policy"] != "off":
            raise CheckFailure("locality_leaked")
        # A stale PID naming a live collector of another root proves nothing
        # about this unowned root: it must not block a legitimate start.
        stale_name = "ownership/locality-stale"
        stale_root = self.fresh_private_root(stale_name)
        stale_sock = os.path.join(stale_root, "collector.sock")
        fd = os.open(os.path.join(stale_root, "collector.pid"), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.write(fd, ("%s\n" % pid_a).encode("ascii"))
        os.close(fd)
        _root, _sock, stale_pid = self.start(stale_name, freshness_window_ms=5000)
        if self.fixture_collectors(stale_root) != [stale_pid]:
            raise CheckFailure("stale_pid_start_owners")
        self.stop_root(stale_root, stale_sock)
        if not self.wait_no_fixture_collectors(stale_root):
            raise CheckFailure("stale_pid_survivor")
        self.stop_root(root_a, sock_a)
        self._wait_dead(pid_a)
        if not _alive(pid_b) or self.fixture_collectors(root_b) != [pid_b]:
            raise CheckFailure("locality_stop_crossed")
        self._require(client_b.status())
        self.cli("--socket", sock_b, "policy", "enable", "--expect-revision", "0")
        client_b.call(
            "admit_batch",
            {"observations": [_sample("locality-b", sequence=1, process_id="proc-b", text=INVENTED_TEXT)]},
        )
        checkpoint = client_b.checkpoint()
        self._require(checkpoint)
        if checkpoint["body"]["durable_seq"] < 1:
            raise CheckFailure("locality_checkpoint")
        self.cli("--socket", sock_b, "policy", "pause", "--expect-revision", "1")
        adapter = self.cli("--socket", sock_b, "status")
        if adapter.returncode != 0:
            raise CheckFailure("locality_adapter")
        _tui_session(sock_b, ["quit"])
        if not _alive(pid_b):
            raise CheckFailure("adapter_close_stopped_collector")
        if Client(sock_b, timeout=3).status()["body"]["desired_policy"] != "paused":
            raise CheckFailure("adapter_changed_policy")
        self.stop_root(root_b, sock_b)
        self._wait_dead(pid_b)
        if not self.wait_no_fixture_collectors(root_a) or not self.wait_no_fixture_collectors(root_b):
            raise CheckFailure("locality_survivors")
        _root, _sock, _pid = self.start(name_b, freshness_window_ms=5000)
        reopened = Client(sock_b, timeout=5)
        status = reopened.status()["body"]
        if status["durable_seq"] < 1 or status["desired_policy"] != "paused":
            raise CheckFailure("locality_restart_lost")
        if len(reopened.query("process", process_id="proc-b", page_size=PAGE)["body"]["observations"]) != 1:
            raise CheckFailure("locality_restart_record_lost")
        self.stop_root(root_b, sock_b)
        if not self.wait_no_fixture_collectors(root_b):
            raise CheckFailure("locality_restart_survivor")
        return {
            "roots": 2,
            "cross_root_effect": 0,
            "stale_foreign_pid_start": 1,
            "stopped_roots": 2,
            "restart_retained": 1,
        }

    def _check_invalid_admission(self, sock):
        producer = Producer(
            sock,
            source_instance_id="invalid-source",
            limits={"heartbeat_interval_ms": 50, "freshness_window_ms": 5000},
        )
        try:
            self._wait_enabled(producer)
            missing = _sample("invalid-source", sequence=1, process_id="proc-missing")
            del missing["source_local_sequence"]
            unsafe = _sample("invalid-source", sequence=2, process_id="bad id")
            missing_result = producer.admit(missing)
            unsafe_result = producer.admit(unsafe)
            if missing_result.admitted or missing_result.durable or missing_result.code != "invalid_request":
                raise CheckFailure("missing_sequence_admitted")
            if unsafe_result.admitted or unsafe_result.code != "invalid_request":
                raise CheckFailure("unsafe_identity_admitted")
            if producer.local_status()["known_refused"] < 2:
                raise CheckFailure("invalid_not_refused")
        finally:
            producer.close()
        client = Client(sock, timeout=5)
        before = client.status()["body"].get("admission_refused_units", 0)
        direct = client.call("admit_batch", {"observations": [missing, unsafe]})
        codes = (direct.get("body") or {}).get("codes") or []
        if codes.count("invalid_request") < 2:
            raise CheckFailure("direct_invalid_not_refused")
        if not _wait(lambda: client.status().get("body", {}).get("admission_refused_units", 0) >= before + 2):
            raise CheckFailure("invalid_not_accounted")
        conflict_before = client.status()["body"]["identity_conflicts"]
        original = _sample("invalid-source", sequence=8, process_id="proc-conflict-once")
        client.call("admit_batch", {"observations": [original]})
        client.checkpoint()
        conflict = dict(original)
        conflict["payload"] = {"text": "INV-CONFLICT-ONCE"}
        conflicted = client.call("admit_batch", {"observations": [conflict]})
        if "identity_conflict" not in (conflicted.get("body") or {}).get("codes", []):
            raise CheckFailure("conflict_not_accounted")
        if client.status()["body"]["identity_conflicts"] != conflict_before + 1:
            raise CheckFailure("conflict_double_counted")
        if producer.local_status()["known_refused"] != 2:
            raise CheckFailure("conflict_counted_as_refusal")

    def _check_quarantine_tail(self):
        phase = self.root("qcrash") + ".fifo"
        fd = _open_fifo(phase)
        try:
            os.write(fd, b"x")
            root, sock, pid = self.start(
                "qcrash",
                no_auto_checkpoint=True,
                publication_phase_hold=phase,
                freshness_window_ms=5000,
                archive_capacity_bytes=2500,
            )
            client = Client(sock, timeout=5)
            self.cli("--socket", sock, "policy", "enable", "--expect-revision", "0")
            original = _sample("qcrash-source", sequence=1, process_id="proc-q")
            client.call("admit_batch", {"observations": [original]})
            client.checkpoint()
            if not _wait(lambda: client.status().get("body", {}).get("durable_seq", 0) >= 1):
                raise CheckFailure("quarantine_baseline")
            known = client.status()["body"]["known_dropped_units"]
            conflict = dict(original)
            conflict["payload"] = {"text": "INV-QUARANTINE-TAIL"}
            client.call("admit_batch", {"observations": [conflict]})
            thread = threading.Thread(target=client.checkpoint, daemon=True)
            thread.start()
            if not _wait(lambda: client.status().get("body", {}).get("publication_phase_hold") is True):
                raise CheckFailure("quarantine_phase_hold")
            os.kill(pid, signal.SIGKILL)
            self._wait_dead(pid)
        finally:
            os.close(fd)
        root, sock, _pid = self.start("qcrash", freshness_window_ms=5000, archive_capacity_bytes=2500)
        client = Client(sock, timeout=5)
        status = client.status()["body"]
        qpath = os.path.join(root, "quarantine.jsonl")
        qsize = os.lstat(qpath).st_size if os.path.lexists(qpath) and not stat.S_ISLNK(os.lstat(qpath).st_mode) else -1
        if status["crash_tail"] != "unknown":
            raise CheckFailure("quarantine_tail_not_unknown")
        if status["known_dropped_units"] != known:
            raise CheckFailure("quarantine_tail_counted_known")
        if qsize != status["quarantine_bytes"]:
            raise CheckFailure("quarantine_watermark_disagrees")
        if status.get("discarded_quarantine_bytes", 0) <= 0:
            raise CheckFailure("quarantine_tail_not_discarded")
        if quarantine_tail_inconsistent(qsize, status["quarantine_bytes"]):
            raise CheckFailure("quarantine_tail_still_unaccounted")
        self.counts["discarded_quarantine_bytes"] = status["discarded_quarantine_bytes"]

    def _check_aliases(self):
        parent = os.path.join(self.workspace, "alias-probes")
        os.makedirs(parent, 0o700)
        os.chmod(parent, 0o700)
        self._assert_alias_rejected(parent, "observations.jsonl", "obs-existing", dangling=False)
        self._assert_alias_rejected(parent, "observations.jsonl", "obs-dangling", dangling=True)
        self._assert_alias_rejected(parent, "quarantine.jsonl", "quar-existing", dangling=False)
        self._assert_alias_rejected(parent, "quarantine.jsonl", "quar-dangling", dangling=True)
        self._assert_log_alias(parent)

    def _assert_alias_rejected(self, parent, name, label, dangling):
        target = os.path.join(parent, label + "-target")
        before = b"SEED"
        if not dangling:
            fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
            os.write(fd, before)
            os.close(fd)
            os.chmod(target, 0o644)
        root = os.path.join(parent, label + "-root")
        os.mkdir(root, 0o700)
        link = os.path.join(root, name)
        os.symlink(target, link)
        sock = os.path.join(root, "collector.sock")
        proc = subprocess.run(
            [sys.executable, "-m", "archive.cli", "--root", root, "--socket", sock, "--timeout", "5", "collector", "start"],
            cwd=REPO, capture_output=True, text=True, timeout=15,
        )
        self._ordinary(proc.stdout, proc.stderr)
        if proc.returncode == 0:
            raise CheckFailure("alias_start_accepted")
        if os.path.islink(link) is False:
            raise CheckFailure("alias_replaced")
        if dangling:
            if os.path.lexists(target):
                raise CheckFailure("dangling_target_created")
            return
        info = os.lstat(target)
        if os.lstat(target).st_size != len(before) or open(target, "rb").read() != before:
            raise CheckFailure("alias_target_rewritten")
        if stat.S_IMODE(info.st_mode) != 0o644:
            raise CheckFailure("alias_target_chmod")

    def _assert_log_alias(self, parent):
        target = os.path.join(parent, "log-target")
        before = b"LOGSEED"
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
        os.write(fd, before)
        os.close(fd)
        os.chmod(target, 0o644)
        root = os.path.join(parent, "log-root")
        os.mkdir(root, 0o700)
        os.symlink(target, os.path.join(root, "collector.out"))
        sock = os.path.join(root, "collector.sock")
        proc = subprocess.run(
            [sys.executable, "-m", "archive.cli", "--root", root, "--socket", sock, "--timeout", "5", "collector", "start"],
            cwd=REPO, capture_output=True, text=True, timeout=15,
        )
        self._ordinary(proc.stdout, proc.stderr)
        if proc.returncode == 0 or "code=unsafe_root" not in proc.stderr:
            raise CheckFailure("log_alias_accepted")
        info = os.lstat(target)
        if open(target, "rb").read() != before or stat.S_IMODE(info.st_mode) != 0o644:
            raise CheckFailure("log_alias_truncated")

    def _review_admission_path(self):
        tree = ast.parse(open(os.path.join(REPO, "archive", "producer.py"), "r").read())
        wanted = {"admit", "_enqueue"}
        forbidden = {"sleep", "dumps", "dump", "connect", "send", "sendall", "recv", "open", "urlopen", "Popen", "fsync"}
        found = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in wanted:
                        found.add(item.name)
                        for child in ast.walk(item):
                            name = ""
                            if isinstance(child, ast.Call):
                                func = child.func
                                if isinstance(func, ast.Name):
                                    name = func.id
                                elif isinstance(func, ast.Attribute):
                                    name = func.attr
                            if name in forbidden:
                                raise CheckFailure("admission_path_io")
        if found != wanted:
            raise CheckFailure("admission_path_missing")

    def _review_imports(self):
        forbidden = {"mlx", "urllib", "requests", "http"}
        for name in os.listdir(os.path.join(REPO, "archive")):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(REPO, "archive", name), "r").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module.split(".")[0]]
                else:
                    continue
                if any(item in forbidden for item in modules):
                    raise CheckFailure("inference_import")
        for name in ("cli.py", "tui.py"):
            text = open(os.path.join(REPO, "archive", name), "r").read()
            if "archive.collector" in text and "import" in text:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "archive.collector":
                        raise CheckFailure("adapter_imports_storage")

    def _assert_no_tcp(self, pid):
        proc = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-i"], capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            raise CheckFailure("tcp_connection")
        if "Library/Rime" in open(os.path.join(REPO, "archive", "collector.py"), "r").read():
            raise CheckFailure("legacy_root_reference")

    def _assert_modes(self, root):
        for current, dirs, files in os.walk(root):
            if stat.S_IMODE(os.lstat(current).st_mode) & 0o077:
                raise CheckFailure("directory_mode")
            for name in dirs + files:
                info = os.lstat(os.path.join(current, name))
                if stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                    raise CheckFailure("private_mode")

    def _assert_docs_limits(self):
        text = open(os.path.join(REPO, "docs", "input-archive.md"), "r").read()
        for key, value in DEFAULTS.items():
            line = "DEFAULT %s=%s" % (key, value)
            if isinstance(value, float) and line not in text and "DEFAULT %s=%s" % (key, int(value) if value == int(value) else value) not in text:
                if line not in text:
                    raise CheckFailure("limits_not_documented")
            elif not isinstance(value, float) and line not in text:
                raise CheckFailure("limits_not_documented")

    def _assert_docs_contract(self):
        text = open(os.path.join(REPO, "docs", "input-archive.md"), "r").read()
        for token in (
            "input-archive-v1",
            "Producer.admit",
            "unsupported_version",
            "stale_revision",
            "unsafe_root",
            "page_bound",
            "identity_conflict",
            "crash_tail",
            "separately_configured_may_continue",
            "collector start",
            "collector stop",
            "not host",
        ):
            if token not in text:
                raise CheckFailure("docs_missing")
        self._assert_docs_limits()

    def _drive_tui_pause(self, sock):
        client = Client(sock, timeout=3)
        client.set_policy("enabled", client.status()["body"]["desired_revision"])
        captured = _tui_session(sock, ["pause", "quit"])
        if b"desired_policy=paused" not in captured:
            raise CheckFailure("tui_control_mismatch")
        if client.status()["body"]["desired_policy"] != "paused":
            raise CheckFailure("tui_not_interface")

    def _wait_enabled(self, producer):
        if not _wait(lambda: _enabled(producer)):
            raise CheckFailure("producer_not_enabled")

    def _wait_durable(self, client, minimum):
        if not _wait(lambda: client.checkpoint().get("body", {}).get("durable_seq", 0) >= minimum):
            raise CheckFailure("not_durable")

    def _wait_dead(self, pid):
        if not _wait(lambda: not _alive(pid), timeout=3):
            raise CheckFailure("pid_still_alive")

    def _require(self, response):
        if not response.get("ok"):
            raise CheckFailure((response.get("error") or {}).get("code", "not_ok"))

    def _ordinary(self, stdout, stderr):
        for marker in (CANARY, EXCL, CONF, ESC_MARK):
            if marker in (stdout or "") or marker in (stderr or ""):
                raise CheckFailure("canary_leak:cli")

    def _flags(self, flags):
        forwarded = []
        for key, value in flags.items():
            flag = "--" + key.replace("_", "-")
            if value is True:
                forwarded.append(flag)
            elif value not in (None, False, ""):
                forwarded.extend([flag, str(value)])
        return forwarded


def _sample(source, sequence=1, process_id="proc-sample", kind="start", text=INVENTED_TEXT):
    return {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "luna_pinyin",
        "source_instance_id": source,
        "source_local_sequence": sequence,
        "observation_kind": kind,
        "process_id": process_id,
        "payload": {"text": text},
    }


def _watch(fn, bound=0.5):
    done = threading.Event()
    box = {}

    def run():
        box["result"] = fn()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    finished = done.wait(bound)
    if not finished:
        return None, True
    return box.get("result"), False


class _BlockedWork(object):
    def __init__(self):
        self.fd_read, self.fd_write = os.pipe()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._block, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def _block(self):
        os.read(self.fd_read, 1)
        self.done.set()

    def finished(self):
        return self.done.is_set()

    def release(self):
        try:
            os.write(self.fd_write, b"x")
        except OSError:
            pass
        self.thread.join(timeout=1)


def _wait(fn, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if fn():
                return True
        except (OSError, KeyError, TypeError):
            pass
        time.sleep(0.05)
    return False


def _enabled(producer):
    local = producer.local_status()
    return local.get("fresh") and local.get("observed_desired") == "enabled"


def _pressured(client):
    body = client.status().get("body") or {}
    return body.get("publication_hold") is True and (
        body.get("known_dropped_units", 0) >= 1 or body.get("received_unpublished", 0) >= 1
    )


def _producer_seen(client):
    body = client.status().get("body") or {}
    return bool(body.get("producer_observations"))


def _producer_entry(client, source_instance_id):
    body = client.status().get("body") or {}
    for entry in body.get("producer_observations") or []:
        if entry.get("source_instance_id") == source_instance_id:
            return entry
    return None


def _producer_acknowledged(client, source_instance_id, revision):
    entry = _producer_entry(client, source_instance_id)
    return bool(
        entry
        and entry.get("observed_revision") == revision
        and entry.get("matches_desired_revision")
        and entry.get("freshness") == "fresh"
    )


def _pid_from_text(text):
    for line in text.splitlines():
        if line.startswith("pid="):
            return int(line.split("=", 1)[1])
    return None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_collector(pid):
    try:
        command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return "archive.collector" in command


def _wait_dead(pid):
    return _wait(lambda: not _alive(pid), timeout=3)


def _open_fifo(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        os.mkfifo(path, 0o600)
    fd = os.open(path, os.O_RDWR)
    os.chmod(path, 0o600)
    return fd


def _rss_kb(pid):
    try:
        text = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True)
        return int(text.strip() or "0")
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0


def _file_sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _scan_tree(root):
    names = []
    blob = []
    for current, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(current, name)
            info = os.lstat(path)
            if stat.S_ISSOCK(info.st_mode) or stat.S_ISFIFO(info.st_mode):
                continue
            names.append(name)
            try:
                blob.append(open(path, "rb").read().decode("utf-8", "ignore"))
            except OSError:
                continue
    return {"names": names, "blob": "\n".join(blob)}


def _tui_capture(sock, commands, repo):
    master, slave = pty.openpty()
    try:
        import termios
        attr = termios.tcgetattr(slave)
        attr[3] = attr[3] & ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attr)
    except Exception:
        pass
    proc = subprocess.Popen(
        [sys.executable, "-m", "archive.cli", "--socket", sock, "tui"],
        cwd=repo,
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)
    buf = _read_until(master, b"SCREEN overview", 5)
    for command in commands:
        os.write(master, (command + "\n").encode("utf-8"))
        token = b"SCREEN closed" if command == "quit" else b"SCREEN"
        buf += _read_until(master, token, 5)
    proc.wait(timeout=5)
    os.close(master)
    return buf


def _tui_session(sock, commands):
    return _tui_capture(sock, commands, REPO)


def _read_until(fd, token, timeout):
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            if token in buf:
                return buf
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        buf += chunk
        if token in buf and (token != b"SCREEN" or buf.count(b"SCREEN") >= 1):
            if token == b"SCREEN closed" or token != b"SCREEN":
                return buf
    return buf


def _prepare_workspace(path):
    real = os.path.realpath(path)
    allowed = os.path.realpath(os.path.join(REPO, ".local-work"))
    if real != allowed and not real.startswith(allowed + os.sep):
        sys.stderr.write("code=unsafe_root\n")
        return None
    if os.path.isdir(real):
        shutil.rmtree(real)
    os.makedirs(real, 0o700)
    return real


def main(argv):
    if "--self-test" in argv:
        return run_self_test()
    if "--suite" not in argv or "contract" not in argv:
        sys.stderr.write("code=invalid_request\n")
        return 2
    root = None
    report = None
    args = argv[1:]
    index = 0
    while index < len(args):
        if args[index] == "--root" and index + 1 < len(args):
            root = args[index + 1]
            index += 2
            continue
        if args[index] == "--report" and index + 1 < len(args):
            report = args[index + 1]
            index += 2
            continue
        index += 1
    if not root or not report:
        sys.stderr.write("code=invalid_request\n")
        return 2
    workspace = _prepare_workspace(root)
    if workspace is None:
        return 2
    report_path = os.path.abspath(report)
    if not report_path.startswith(os.path.realpath(os.path.join(REPO, ".local-work")) + os.sep):
        sys.stderr.write("code=unsafe_root\n")
        return 2
    suite = Suite(workspace)
    try:
        payload = suite.run()
    finally:
        suite.stop_owned()
    problems = validate_report(payload) if payload.get("result") == "pass" else ["result_not_pass"]
    if any(item == "canary_in_report" for item in problems):
        payload = {"report_version": 1, "result": "fail", "canary_in_report": True, "criteria": {}}
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    blob = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    fd = os.open(report_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.write(fd, blob)
    os.close(fd)
    os.chmod(report_path, 0o600)
    sys.stdout.write("result=%s\n" % payload.get("result"))
    for item in REQUIRED:
        failed = (payload.get("criteria") or {}).get(item, {}).get("failed") or []
        sys.stdout.write("%s %s\n" % (item, "fail" if failed else payload.get("criteria", {}).get(item, {}).get("result", "fail")))
        for code in failed:
            sys.stdout.write("fail %s %s\n" % (item, code))
    if payload.get("result") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
