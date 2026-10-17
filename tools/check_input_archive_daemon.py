#!/usr/bin/env python3
"""Content-free contract checker for passive daemon archive observation.

This drives the real production daemon handler over a real unix socket into a
genuine collector and reads the passive `daemon` query view. It is an
orchestration entry, not a replacement daemon. It does not enable capture on
any deployed root, and ordinary stdout/stderr and the report omit raw text.

Suites:
  --suite contract  model-free cases for DAEMON191-1..7 over a fixture state
  --suite model     the approved local Qwen + sealed adapter with real MLX
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON_DIR = os.path.join(REPO, "daemon")
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from archive import Client  # noqa: E402
from archive.interface import strip_content  # noqa: E402
from archive.safety import safe_token  # noqa: E402

CANARY = "DAEMON191CANARY"
TEXT_MARK = "\u5019\u6d4b"  # 候测: invented text marker for leak scans
WATCHDOG_MS = 2000
REQUEST_WATCHDOG_MS = 60000
IDLE_WATCHDOG_MS = 420000
SCORING_DAEMON_ENTRY = os.path.join(DAEMON_DIR, "server.py")

REQUIRED_CASES = (
    "DaemonViewUnavailableWithoutObservations",
    "DisabledCaptureScoresWithoutRecords",
    "EnabledCaptureBindsRequestAndOutcome",
    "WindowedContextDistinctions",
    "WarmRequestHasNoSecondLoad",
    "DeterministicErrorAndBarrierControls",
    "PolicyPauseRefusalAndResumeNoBackfill",
    "AbsentCollectorScoresWithinWatchdog",
    "HeldPublicationScoresThenPublishes",
    "CapacityStopScoresWithinWatchdog",
    "StorageFailureScoresWithinWatchdog",
    "MalformedPeerStaysUnknown",
    "PassiveStateNeverProbesOrActivates",
    "ProtocolControlsUnchanged",
    "VersionRefusalsAtCollector",
    "CanariesAbsentFromOrdinaryOutputs",
)


class CheckFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ordinary_content_free(text, label):
    if CANARY in text or TEXT_MARK in text:
        raise CheckFailure("content_leak:" + label)


def _git_rev():
    try:
        out = subprocess.check_output(
            ["git", "-C", REPO, "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return None


def _source_identity():
    files = (
        "archive/interface.py",
        "archive/producer.py",
        "archive/collector.py",
        "archive/cli.py",
        "daemon/server.py",
        "daemon/archive_observation.py",
        "daemon/personal_lora_live.py",
        "tools/check_input_archive_daemon.py",
    )
    identity = {"git_head": _git_rev(), "files": {}}
    for name in files:
        path = os.path.join(REPO, name)
        if os.path.isfile(path):
            identity["files"][name] = _sha256_file(path)
    return identity


def _runtime_identity():
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "bytecode_disabled": os.environ.get("PYTHONDONTWRITEBYTECODE") == "1",
    }


def _run(argv, **kwargs):
    kwargs.setdefault("cwd", REPO)
    return subprocess.run(argv, **kwargs)


def _collector_start(root, sock, timeout="8", **limits):
    os.makedirs(os.path.dirname(root), mode=0o700, exist_ok=True)
    argv = [
        sys.executable, "-m", "archive.cli",
        "--root", root, "--socket", sock, "--timeout", timeout,
        "collector", "start",
    ]
    for key, value in limits.items():
        argv.append("--%s" % key.replace("_", "-"))
        argv.append(str(value))
    proc = _run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CheckFailure("collector_start")
    return proc


def _collector_stop(root, sock):
    _run(
        [
            sys.executable, "-m", "archive.cli",
            "--root", root, "--socket", sock, "--timeout", "5",
            "collector", "stop",
        ],
        capture_output=True,
        text=True,
    )


def _wait_for_socket(path, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            try:
                conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                conn.settimeout(0.5)
                conn.connect(path)
                conn.close()
                return True
            except OSError:
                time.sleep(0.05)
                continue
        time.sleep(0.05)
    return False


def _exchange(path, payload, timeout=10.0, read_reply=True, half_close=True):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(path)
        conn.sendall(payload)
        if half_close:
            conn.shutdown(socket.SHUT_WR)
        if not read_reply:
            return None
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        if not data:
            return None
        return json.loads(data.decode("utf-8"))
    finally:
        conn.close()


def _scoring_request(request_id, plan_identity, context, candidates,
                     policy_id="mean-token-lm-v1"):
    return {
        "version": 2,
        "request_id": request_id,
        "plan_identity": plan_identity,
        "baseline_policy_id": policy_id,
        "context": context,
        "candidates": candidates,
    }


def _send_request_raw(path, obj, timeout=10.0):
    return _exchange(
        path, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"),
        timeout=timeout,
    )


def _await(predicate, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def _body(response):
    return (response or {}).get("body") or {}


def _daemon_view(client):
    return _body(client.call("query", {"view": "daemon"}))


def _timeline(client, page_size=50):
    rows = []
    cursor = None
    while True:
        body = {"view": "timeline", "page_size": page_size}
        if cursor is not None:
            body["cursor"] = cursor
        page = _body(client.call("query", body))
        chunk = page.get("observations") or []
        rows.extend(chunk)
        cursor = page.get("next_cursor")
        if not cursor:
            return rows


def _daemon_rows(client):
    return [row for row in _timeline(client) if row.get("observation_kind") == "daemon_observation"]


def _durable_now(client):
    _body(client.call("checkpoint"))
    status = _body(client.call("status"))
    return status


def _await_durable_rows(client, predicate, timeout=10.0):
    def probe():
        status = _body(client.call("checkpoint"))
        rows = _daemon_rows(client)
        if predicate(rows, status):
            return rows
        return None

    return _await(probe, timeout=timeout, interval=0.1)


def _enable_capture(client):
    status = _body(client.call("status"))
    response = client.set_policy("enabled", status["desired_revision"])
    if not response.get("ok"):
        raise CheckFailure("policy_enable")
    return response


def _set_policy(client, desired):
    status = _body(client.call("status"))
    response = client.set_policy(desired, status["desired_revision"])
    if not response.get("ok"):
        raise CheckFailure("policy_" + desired)
    return response


def _await_producer_effective(client, timeout=15.0):
    def probe():
        status = _body(client.call("status"))
        if status.get("globally_effective"):
            return status
        return None

    status = _await(probe, timeout=timeout, interval=0.1)
    if not status:
        raise CheckFailure("producer_not_effective")
    return status


def _scan_root_for(path_root, needles):
    """Return any file under path_root whose bytes contain a needle."""
    hits = []
    for current, dirs, files in os.walk(path_root, followlinks=False):
        for name in dirs + files:
            full = os.path.join(current, name)
            try:
                info = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                hits.append(("symlink", full))
                continue
            if stat.S_ISSOCK(info.st_mode) or stat.S_ISFIFO(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            try:
                with open(full, "rb") as handle:
                    data = handle.read()
            except OSError:
                continue
            for needle in needles:
                if needle.encode("utf-8") in data:
                    hits.append((name, full))
                    break
    return hits


# ---------------------------------------------------------------------------
# Fixture daemon (contract suite): the real run_server path with a
# deterministic in-process state; only the MLX load/score implementation is
# substituted. Lifecycle hooks fire through the production ModelState code.
# ---------------------------------------------------------------------------

FIXTURE_TRIGGERS = {
    "ERR-TRIGGER": "raise",
    "BARRIER-TRIGGER": "barrier",
    "NONFINITE-TRIGGER": "nonfinite",
    "MISMATCH-TRIGGER": "mismatch",
    "LOADFAIL-TRIGGER": "loadfail",
}


def _run_fixture_daemon(argv):
    sys.path.insert(0, DAEMON_DIR)
    import server
    from server import ModelState

    class FixtureState(ModelState):
        def __init__(self, barrier_file=""):
            super().__init__("fixture-model", adapter_path="")
            self.barrier_file = barrier_file
            self.fail_next_load = False

        def _load_base_model(self):
            if self.fail_next_load:
                self.fail_next_load = False
                raise RuntimeError("fixture load failure")

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
            if behavior == "barrier" and self.barrier_file:
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    if os.path.exists(self.barrier_file):
                        break
                    time.sleep(0.01)
            if behavior == "loadfail":
                self.fail_next_load = True
                self.unload(reason="unspecified")
                self.load()
            if behavior == "nonfinite":
                return [float("inf") for _ in candidates]
            if behavior == "mismatch":
                return []
            return [-(index + 1) * 0.25 for index in range(len(candidates))]

    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-daemon", action="store_true")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--archive-socket", default="")
    parser.add_argument("--facts-root", required=True)
    parser.add_argument("--idle-timeout", type=float, default=300.0)
    parser.add_argument("--barrier-file", default="")
    args = parser.parse_args(argv)
    # Controlled-clock fixture: the production watchdog reads the module
    # global, so the fast-clock check patches it in this process only. The
    # production default (IDLE_TIMEOUT = 300) and its source stay untouched.
    server.IDLE_TIMEOUT = args.idle_timeout
    state = FixtureState(barrier_file=args.barrier_file)
    server.run_server(
        args.socket, "fixture-model", cache_limit_mb=0, test_mode=False,
        facts_root=args.facts_root,
        archive_socket=args.archive_socket,
        state=state,
    )
    return 0


class FixtureDaemon(object):
    def __init__(self, root, sock, archive_socket="", facts_root="",
                 idle_timeout=300.0, barrier_file="", log_path=""):
        self.sock = sock
        self.log = open(log_path or os.devnull, "wb")
        self.proc = subprocess.Popen(
            [
                sys.executable, os.path.abspath(__file__),
                "--fixture-daemon",
                "--socket", sock,
                "--archive-socket", archive_socket,
                "--facts-root", facts_root,
                "--idle-timeout", str(idle_timeout),
                "--barrier-file", barrier_file,
            ],
            cwd=REPO,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self, timeout=15.0):
        if not _wait_for_socket(self.sock, timeout):
            raise CheckFailure("fixture_daemon_not_ready")
        return True

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        try:
            self.log.close()
        except OSError:
            pass


class MalformedPeer(object):
    """A badly-behaved local peer: it answers the interface with garbage or
    incomplete bodies, and records what it was asked. Nothing it does can be
    admission or durability."""

    def __init__(self, sock):
        self.sock = sock
        self.received = []
        self._stop = False
        self._conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._conn.bind(sock)
        os.chmod(sock, 0o600)
        self._conn.listen(8)
        self._conn.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _read_frame(self, conn):
        header = b""
        while len(header) < 4:
            chunk = conn.recv(4 - len(header))
            if not chunk:
                return None
            header += chunk
        (size,) = struct.unpack(">I", header)
        if size <= 0 or size > 4 * 1024 * 1024:
            return None
        payload = b""
        while len(payload) < size:
            chunk = conn.recv(size - len(payload))
            if not chunk:
                return None
            payload += chunk
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return None

    def _reply(self, conn, obj):
        data = json.dumps(obj).encode("utf-8")
        conn.sendall(struct.pack(">I", len(data)) + data)

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self._conn.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(2.0)
                request = self._read_frame(conn)
                if request is None:
                    # Malformed peer: reply with an unparseable frame.
                    conn.sendall(struct.pack(">I", 5) + b"junk!")
                    continue
                op = request.get("op")
                self.received.append(op)
                if op == "policy_observe":
                    self._reply(conn, {
                        "interface_version": "input-archive-v1",
                        "envelope_version": 1,
                        "op": op,
                        "ok": True,
                        "body": {},
                        "content_included": False,
                    })
                else:
                    # A transport success that certifies nothing.
                    self._reply(conn, {
                        "interface_version": "input-archive-v1",
                        "envelope_version": 1,
                        "op": op,
                        "ok": True,
                        "body": {},
                        "content_included": False,
                    })
            except Exception:
                pass
            finally:
                conn.close()

    def stop(self):
        self._stop = True
        try:
            self._conn.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)


class ContractSuite(object):
    def __init__(self, root):
        self.root = root
        self.cases = {}
        self.order = list(REQUIRED_CASES)
        self.notes = {}
        self.collectors = []
        self.daemons = []
        self.peers = []
        self.logs = []
        self.watchdogs = {
            "request_completion_ms": WATCHDOG_MS,
            "idle_unload_ms": IDLE_WATCHDOG_MS,
        }

    # -- fixture management ------------------------------------------------
    def collector(self, name, **limits):
        root = os.path.join(self.root, name)
        sock = os.path.join(root, "collector.sock")
        os.makedirs(root, mode=0o700, exist_ok=True)
        _collector_start(root, sock, **limits)
        self.collectors.append((root, sock))
        return Client(sock, timeout=5), root, sock

    def daemon(self, name, archive_socket="", **kwargs):
        daemon_root = os.path.join(self.root, name)
        os.makedirs(daemon_root, mode=0o700, exist_ok=True)
        os.chmod(daemon_root, 0o700)
        facts = os.path.join(daemon_root, "facts")
        os.makedirs(facts, mode=0o700, exist_ok=True)
        os.chmod(facts, 0o700)
        sock = os.path.join(daemon_root, "daemon.sock")
        log_path = os.path.join(self.root, name + ".daemon.log")
        daemon = FixtureDaemon(
            self.root, sock, archive_socket=archive_socket,
            facts_root=facts, log_path=log_path, **kwargs
        )
        self.daemons.append(daemon)
        self.logs.append(log_path)
        daemon.wait_ready()
        return daemon, sock

    def run(self):
        try:
            self._run_cases()
        finally:
            self._cleanup()

    def _cleanup(self):
        for daemon in self.daemons:
            daemon.stop()
        for peer in self.peers:
            peer.stop()
        for root, sock in self.collectors:
            _collector_stop(root, sock)

    # -- runner ------------------------------------------------------------
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
        self.case("DaemonViewUnavailableWithoutObservations",
                  self.c_view_unavailable)
        self.case("DisabledCaptureScoresWithoutRecords",
                  self.c_disabled_no_records)
        self.case("EnabledCaptureBindsRequestAndOutcome",
                  self.c_binds_request_outcome)
        self.case("WindowedContextDistinctions", self.c_window_controls)
        self.case("WarmRequestHasNoSecondLoad", self.c_warm_no_load)
        self.case("DeterministicErrorAndBarrierControls", self.c_error_barrier)
        self.case("PolicyPauseRefusalAndResumeNoBackfill", self.c_pause_resume)
        self.case("AbsentCollectorScoresWithinWatchdog", self.c_absent_collector)
        self.case("HeldPublicationScoresThenPublishes", self.c_held_publication)
        self.case("CapacityStopScoresWithinWatchdog", self.c_capacity_stop)
        self.case("StorageFailureScoresWithinWatchdog", self.c_storage_failure)
        self.case("MalformedPeerStaysUnknown", self.c_malformed_peer)
        self.case("PassiveStateNeverProbesOrActivates", self.c_passive_reads)
        self.case("ProtocolControlsUnchanged", self.c_protocol_controls)
        self.case("VersionRefusalsAtCollector", self.c_version_refusals)
        self.case("CanariesAbsentFromOrdinaryOutputs", self.c_canary_scan)

    # -- state shared between cases ---------------------------------------
    @property
    def main(self):
        if not hasattr(self, "_main"):
            client, root, sock = self.collector("c-main")
            daemon, daemon_sock = self.daemon(
                "main", archive_socket=sock,
            )
            self._main = {
                "client": client,
                "root": root,
                "sock": sock,
                "daemon": daemon,
                "daemon_sock": daemon_sock,
            }
        return self._main

    # -- cases -------------------------------------------------------------
    def c_view_unavailable(self):
        view = _daemon_view(self.main["client"])
        if view.get("state") != "unknown" or view.get("freshness") != "unavailable":
            raise CheckFailure("unexpected_state")
        if view.get("unknown_reason") != "no_daemon_observations":
            raise CheckFailure("unexpected_reason")
        if view.get("content_included") is not False:
            raise CheckFailure("content_flag")
        if view.get("live_probe") is not False or view.get("inference_dependency") is not False:
            raise CheckFailure("probe_claim")
        return {"note": "unavailable_semantics"}

    def c_disabled_no_records(self):
        main = self.main
        # A dedicated daemon so the shared one stays cold for the cold-load
        # case; capture is off because the collector was never enabled.
        _daemon, sock = self.daemon("off", archive_socket=main["sock"])
        response = _send_request_raw(
            sock,
            _scoring_request(
                "req-off-1", "plan-off-1",
                "%s 上文 window off" % CANARY,
                ["\u653b\u51fb", "\u516c\u9e21"],
            ),
            timeout=10.0,
        )
        if not response or response.get("scores") != [-0.25, -0.5]:
            raise CheckFailure("fixture_score")
        _durable_now(main["client"])
        rows = _daemon_rows(main["client"])
        if rows:
            raise CheckFailure("recorded_while_off")
        hits = _scan_root_for(main["root"], [CANARY])
        if hits:
            raise CheckFailure("canary_persisted_while_off")
        return {"note": "capture_off_no_record"}

    def c_binds_request_outcome(self):
        main = self.main
        _enable_capture(main["client"])
        _await_producer_effective(main["client"])
        context = "%s \u4e0a\u6587\u957f\u5ea6\u6d4b\u8bd5" % CANARY
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request(
                "req-on-1", "rerank-plan-v2:sha1:%s" % ("a1" * 20),
                context, ["\u653b\u51fb", "\u516c\u9e21", "\u4e0a\u8bcd"],
            ),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("fixture_score_on")
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "scoring"
                and row.get("request_id") == "req-on-1"
                for row in rows
            ),
            timeout=10.0,
        )
        if not rows:
            raise CheckFailure("outcome_not_durable")
        requests = [
            row for row in rows
            if row.get("daemon_stage") == "request"
            and row.get("request_id") == "req-on-1"
        ]
        scorings = [
            row for row in rows
            if row.get("daemon_stage") == "scoring"
            and row.get("request_id") == "req-on-1"
        ]
        if len(requests) != 1 or len(scorings) != 1:
            raise CheckFailure("record_count")
        request_row, scoring_row = requests[0], scorings[0]
        if request_row.get("plan_identity") != "rerank-plan-v2:sha1:%s" % ("a1" * 20):
            raise CheckFailure("plan_identity_binding")
        if request_row.get("process_id") != scoring_row.get("process_id"):
            raise CheckFailure("process_binding")
        if request_row.get("source_instance_id") != scoring_row.get("source_instance_id"):
            raise CheckFailure("source_binding")
        if not safe_token(request_row.get("source_instance_id") or ""):
            raise CheckFailure("source_token")
        if scoring_row.get("outcome_code") != "ok":
            raise CheckFailure("outcome_code")
        if scoring_row.get("load_included") is not True:
            raise CheckFailure("cold_load_flagged")
        if not (scoring_row.get("scoring_ms") or 0) > 0:
            raise CheckFailure("scoring_ms")
        if scoring_row.get("decomposition") != "combined_tokenize_forward_scalar_extraction":
            raise CheckFailure("decomposition")
        edges = scoring_row.get("edges") or {}
        if not edges.get("request_accepted") <= edges.get("scoring_started") <= edges.get("scoring_completed") <= edges.get("outcome_decided"):
            raise CheckFailure("edge_order")
        loads = [row for row in rows if row.get("daemon_stage") == "load"]
        if len(loads) != 1 or loads[0].get("load_outcome") != "completed":
            raise CheckFailure("load_observation")
        if loads[0].get("model_identity") != "fixture-model":
            raise CheckFailure("load_identity")
        if loads[0].get("runtime_versions") is None:
            raise CheckFailure("runtime_identity")
        # Private detail is deliberate; ordinary rows are content-free.
        private = _body(main["client"].call(
            "query", {"view": "process", "process_id": request_row.get("process_id"),
                      "private_detail": True}))
        payload_rows = [
            row for row in private.get("observations") or []
            if row.get("payload") is not None
        ]
        if not payload_rows:
            raise CheckFailure("private_detail_missing")
        payload = payload_rows[0]["payload"]
        if payload.get("requested_context") != context:
            raise CheckFailure("private_context")
        if payload.get("effective_context") != context:
            raise CheckFailure("private_effective")
        if payload.get("candidates") != ["\u653b\u51fb", "\u516c\u9e21", "\u4e0a\u8bcd"]:
            raise CheckFailure("private_candidates")
        ordinary = json.dumps(
            strip_content(_body(main["client"].call("query", {"view": "timeline"}))),
            sort_keys=True,
        )
        _ordinary_content_free(ordinary, "timeline")
        status = json.dumps(main["client"].status(), sort_keys=True)
        _ordinary_content_free(status, "status")
        return {"note": "request_outcome_load_bound"}

    def c_window_controls(self):
        main = self.main
        long_context = ("%s" % CANARY) + "\u5e8f" * 60 + "\u5c3e\u5b57\u7b26"
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request(
                "req-win-1", "plan-win-1", long_context,
                ["\u957f\u4e0a\u6587"],
            ),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("long_context_score")
        empty = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-win-2", "plan-win-2", "", ["\u7a7a\u4e0a\u6587"]),
            timeout=10.0,
        )
        if not empty or "scores" not in empty:
            raise CheckFailure("empty_context_score")
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("request_id") == "req-win-2"
                and row.get("daemon_stage") == "scoring"
                for row in rows
            ),
            timeout=10.0,
        )
        long_rows = [
            row for row in rows
            if row.get("daemon_stage") == "request" and row.get("request_id") == "req-win-1"
        ]
        if len(long_rows) != 1:
            raise CheckFailure("long_row")
        row = long_rows[0]
        if row.get("requested_context_chars") != len(long_context):
            raise CheckFailure("requested_chars")
        if row.get("effective_context_chars") != 64:
            raise CheckFailure("effective_chars")
        if row.get("context_window_chars") != 64:
            raise CheckFailure("window_chars")
        if row.get("context_truncated") is not True:
            raise CheckFailure("truncated_flag")
        empty_rows = [
            row for row in rows
            if row.get("daemon_stage") == "request" and row.get("request_id") == "req-win-2"
        ]
        if len(empty_rows) != 1:
            raise CheckFailure("empty_row")
        if empty_rows[0].get("effective_context_chars") != 0:
            raise CheckFailure("empty_effective")
        if empty_rows[0].get("context_truncated") is not False:
            raise CheckFailure("empty_truncated")
        # An identity outside the token alphabet loses its field, never the
        # whole observation.
        unsafe = _send_request_raw(
            main["daemon_sock"],
            _scoring_request(
                "req unsafe/unknown", "plan unknown", "\u672a\u77e5",
                ["\u672a\u77e5\u8eab\u4efd"],
            ),
            timeout=10.0,
        )
        if not unsafe or "scores" not in unsafe:
            raise CheckFailure("unsafe_id_score")
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "request"
                and row.get("request_id") is None
                for row in rows
            ),
            timeout=10.0,
        )
        unknown_rows = [
            row for row in (rows or [])
            if row.get("daemon_stage") == "request"
            and row.get("request_id") is None
        ]
        if not unknown_rows:
            raise CheckFailure("unknown_identity_absent")
        unique = {
            (row.get("request_id"), row.get("source_local_sequence"))
            for row in rows
            if row.get("daemon_stage") == "request"
        }
        if len(unique) != len([
            row for row in rows if row.get("daemon_stage") == "request"
        ]):
            raise CheckFailure("identity_reuse")
        return {"note": "requested_vs_effective"}

    def c_warm_no_load(self):
        main = self.main
        before = [row for row in _daemon_rows(main["client"]) if row.get("daemon_stage") == "load"]
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-warm-1", "plan-warm-1", "\u70ed\u72b6\u6001", ["\u70ed\u72b6\u6001"]),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("warm_score")
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "scoring" and row.get("request_id") == "req-warm-1"
                for row in rows
            ),
            timeout=10.0,
        )
        warm = [
            row for row in rows
            if row.get("daemon_stage") == "scoring" and row.get("request_id") == "req-warm-1"
        ]
        if len(warm) != 1:
            raise CheckFailure("warm_outcome")
        if warm[0].get("load_included") is not False:
            raise CheckFailure("warm_load_flag")
        if warm[0].get("load_ms") is not None:
            raise CheckFailure("fake_load_ms")
        after = [row for row in rows if row.get("daemon_stage") == "load"]
        if len(after) != len(before):
            raise CheckFailure("extra_load_observation")
        return {"note": "no_fake_load_duration"}

    def c_error_barrier(self):
        main = self.main
        # Deterministic failure
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-err-1", "plan-err-1", "\u9519\u8bef", ["ERR-TRIGGER"]),
            timeout=10.0,
        )
        if (response or {}).get("error", {}).get("code") != "inference_failed":
            raise CheckFailure("error_response")
        # Barrier: the outcome must not be decided before the barrier
        # releases; the accepted request is durable while scoring is blocked.
        barrier_file = os.path.join(self.root, "barrier.release")
        _barrier_daemon, barrier_sock = self.daemon(
            "barrier", archive_socket=self.main["sock"], barrier_file=barrier_file,
        )
        outcome = {}

        def send_barrier_request():
            try:
                outcome["response"] = _send_request_raw(
                    barrier_sock,
                    _scoring_request(
                        "req-bar-1", "plan-bar-1", "\u963b\u585e",
                        ["BARRIER-TRIGGER"],
                    ),
                    timeout=10.0,
                )
            except Exception as exc:  # noqa: BLE001
                outcome["error"] = type(exc).__name__

        thread = threading.Thread(target=send_barrier_request, daemon=True)
        barrier_started = time.monotonic()
        thread.start()
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "request"
                and row.get("request_id") == "req-bar-1"
                for row in rows
            ),
            timeout=5.0,
        )
        if not rows:
            raise CheckFailure("barrier_request_row")
        pre = [
            row for row in rows
            if row.get("daemon_stage") == "scoring"
            and row.get("request_id") == "req-bar-1"
        ]
        if pre:
            raise CheckFailure("barrier_outcome_early")
        time.sleep(0.5)
        with open(barrier_file, "w") as handle:
            handle.write("release\n")
        thread.join(timeout=10.0)
        if thread.is_alive() or "response" not in outcome:
            raise CheckFailure("barrier_response")
        if "scores" not in (outcome.get("response") or {}):
            raise CheckFailure("barrier_score")
        barrier_ms = (time.monotonic() - barrier_started) * 1000
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "scoring"
                and row.get("request_id") == "req-bar-1"
                for row in rows
            ),
            timeout=10.0,
        )
        scored = [
            row for row in (rows or [])
            if row.get("daemon_stage") == "scoring"
            and row.get("request_id") == "req-bar-1"
        ]
        if len(scored) != 1:
            raise CheckFailure("barrier_outcome")
        if (scored[0].get("scoring_ms") or 0) < 400:
            raise CheckFailure("barrier_ms")
        # Load failure observation
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-loadfail-1", "plan-loadfail-1", "\u5931\u8d25", ["LOADFAIL-TRIGGER"]),
            timeout=10.0,
        )
        if (response or {}).get("error", {}).get("code") != "inference_failed":
            raise CheckFailure("loadfail_response")
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "load" and row.get("load_outcome") == "failed"
                for row in rows
            ),
            timeout=10.0,
        )
        if not rows:
            raise CheckFailure("loadfail_observation")
        failed = [
            row for row in rows
            if row.get("daemon_stage") == "load" and row.get("load_outcome") == "failed"
        ]
        if len(failed) != 1 or (failed[0].get("load_ms") or 0) < 0:
            raise CheckFailure("loadfail_fields")
        # Non-finite and count mismatch controls stay truthful.
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-nf-1", "plan-nf-1", "\u975e\u6cd5", ["NONFINITE-TRIGGER"]),
            timeout=10.0,
        )
        if (response or {}).get("error", {}).get("code") != "non_finite_score":
            raise CheckFailure("nonfinite_response")
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-mm-1", "plan-mm-1", "\u4e0d\u5339\u914d", ["MISMATCH-TRIGGER"]),
            timeout=10.0,
        )
        if (response or {}).get("error", {}).get("code") != "score_count_mismatch":
            raise CheckFailure("mismatch_response")
        return {"note": "lazy_barrier_error_controls"}

    def c_pause_resume(self):
        main = self.main
        _set_policy(main["client"], "paused")
        # Race window: the producer may still hold a fresh 'enabled' snapshot
        # for up to the freshness window; the collector must refuse that
        # content with a genuine per-item reply.
        racy_context = "%s paused-race" % CANARY
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-pause-1", "plan-pause-1", racy_context, ["\u6682\u505c"]),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("pause_race_score")
        time.sleep(2.6)
        expired_context = "%s paused-expired" % CANARY
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-pause-2", "plan-pause-2", expired_context, ["\u6682\u505c"]),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("pause_expired_score")
        # The collector's refusal is a genuine per-item reply: the same frame
        # shape that is admissible while enabled is refused `capture_disabled`
        # while paused and must not persist content.
        refused_frame = _frame("request", 100)
        refused_frame["payload"] = {
            "requested_context": "genuine-refusal-191",
            "effective_context": "genuine-refusal-191",
            "candidates": ["\u771f\u5b9e\u62d2\u7edd"],
        }
        refused = main["client"].call(
            "admit_batch", {"observations": [refused_frame]})
        if _body(refused).get("codes") != ["capture_disabled"]:
            raise CheckFailure("genuine_refusal_code")
        _durable_now(main["client"])
        if _scan_root_for(main["root"], ["genuine-refusal-191"]):
            raise CheckFailure("refused_content_persisted")
        _enable_capture(main["client"])
        _await_producer_effective(main["client"])
        admitted_frame = _frame("request", 101)
        admitted_frame["payload"] = {
            "requested_context": "genuine-refusal-191",
            "effective_context": "genuine-refusal-191",
            "candidates": ["\u771f\u5b9e\u62d2\u7edd"],
        }
        admitted = main["client"].call(
            "admit_batch", {"observations": [admitted_frame]})
        if _body(admitted).get("codes") != ["admitted"]:
            raise CheckFailure("resumed_admit")
        _durable_now(main["client"])
        if not _scan_root_for(main["root"], ["genuine-refusal-191"]):
            raise CheckFailure("resumed_content_missing")
        resumed_context = "%s resumed-ok" % CANARY
        response = _send_request_raw(
            main["daemon_sock"],
            _scoring_request("req-resume-1", "plan-resume-1", resumed_context, ["\u6062\u590d"]),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("resume_score")
        rows = _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("request_id") == "req-resume-1" for row in rows
            ),
            timeout=10.0,
        )
        if not rows:
            raise CheckFailure("resume_row")
        paused_ids = {
            "req-pause-1", "req-pause-2",
        }
        for row in rows:
            if row.get("request_id") in paused_ids:
                raise CheckFailure("paused_row_present")
        hits = _scan_root_for(main["root"], ["paused-race", "paused-expired"])
        if hits:
            raise CheckFailure("paused_content_persisted")
        if not _scan_root_for(main["root"], ["resumed-ok"]):
            raise CheckFailure("resumed_content_missing")
        return {"note": "pause_refusal_resume_contrast"}

    def c_absent_collector(self):
        parent = os.path.join(self.root, "absent")
        os.makedirs(parent, mode=0o700, exist_ok=True)
        missing_socket = os.path.join(parent, "collector.sock")
        daemon, sock = self.daemon("absent", archive_socket=missing_socket)
        started = time.monotonic()
        response = _send_request_raw(
            sock,
            _scoring_request("req-absent-1", "plan-absent-1", "\u7f3a\u5e2d", ["\u7f3a\u5e2d"]),
            timeout=10.0,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        if not response or "scores" not in response:
            raise CheckFailure("absent_score")
        if elapsed_ms > WATCHDOG_MS:
            raise CheckFailure("absent_watchdog")
        if os.path.exists(missing_socket):
            raise CheckFailure("unexpected_collector")
        daemon.stop()
        return {"note": "completion_ms=%d" % int(elapsed_ms)}

    def c_held_publication(self):
        hold_root = os.path.join(self.root, "held")
        os.makedirs(hold_root, mode=0o700, exist_ok=True)
        hold_sock = os.path.join(hold_root, "collector.sock")
        fifo = os.path.join(hold_root, "publish.hold")
        os.mkfifo(fifo, 0o600)
        _collector_start(hold_root, hold_sock, publication_hold=fifo)
        self.collectors.append((hold_root, hold_sock))
        client = Client(hold_sock, timeout=5)
        _enable_capture(client)
        daemon, sock = self.daemon("held", archive_socket=hold_sock)
        started = time.monotonic()
        response = _send_request_raw(
            sock,
            _scoring_request("req-held-1", "plan-held-1", "\u6301\u4f4f", ["\u6301\u4f4f"]),
            timeout=10.0,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        if not response or "scores" not in response:
            raise CheckFailure("held_score")
        if elapsed_ms > WATCHDOG_MS:
            raise CheckFailure("held_watchdog")
        # Publication is held, so `checkpoint` cannot complete; the status op
        # does not wait on publication.
        status = _body(client.call("status"))
        if status.get("durable_seq"):
            raise CheckFailure("held_published_early")
        if not status.get("publication_hold"):
            raise CheckFailure("hold_not_active")
        with open(fifo, "w") as handle:
            handle.write("release\n")
        rows = _await_durable_rows(
            client,
            lambda rows, status: any(
                row.get("request_id") == "req-held-1" for row in rows
            ),
            timeout=10.0,
        )
        if not rows:
            raise CheckFailure("held_not_published_after_release")
        daemon.stop()
        return {"note": "completion_ms=%d" % int(elapsed_ms)}

    def c_capacity_stop(self):
        cap_root = os.path.join(self.root, "cap")
        os.makedirs(cap_root, mode=0o700, exist_ok=True)
        cap_sock = os.path.join(cap_root, "collector.sock")
        _collector_start(cap_root, cap_sock, archive_capacity_bytes=1000)
        self.collectors.append((cap_root, cap_sock))
        client = Client(cap_sock, timeout=5)
        _enable_capture(client)
        daemon, sock = self.daemon("cap", archive_socket=cap_sock)
        _await_producer_effective(client)
        started = time.monotonic()
        responses = []
        for index in range(4):
            responses.append(_send_request_raw(
                sock,
                _scoring_request(
                    "req-cap-%d" % index, "plan-cap-%d" % index,
                    "%s \u5bb9\u91cf" % CANARY, ["\u5bb9\u91cf\u5019\u9009%d" % index],
                ),
                timeout=10.0,
            ))
        elapsed_ms = (time.monotonic() - started) * 1000
        if any(not response or "scores" not in response for response in responses):
            raise CheckFailure("capacity_score")
        if elapsed_ms > WATCHDOG_MS * len(responses):
            raise CheckFailure("capacity_watchdog")
        status = _await(
            lambda: (
                lambda body: body if body.get("capacity_stop") else None
            )(_body(client.call("checkpoint"))),
            timeout=10.0,
            interval=0.2,
        )
        if not status:
            raise CheckFailure("capacity_not_reached")
        if not status.get("capacity_refused_units"):
            raise CheckFailure("capacity_not_accounted")
        daemon.stop()
        return {"note": "completion_ms=%d" % int(elapsed_ms)}

    def c_storage_failure(self):
        sf_root = os.path.join(self.root, "sf")
        os.makedirs(sf_root, mode=0o700, exist_ok=True)
        sf_sock = os.path.join(sf_root, "collector.sock")
        _collector_start(sf_root, sf_sock)
        self.collectors.append((sf_root, sf_sock))
        client = Client(sf_sock, timeout=5)
        _enable_capture(client)
        daemon, sock = self.daemon("sf", archive_socket=sf_sock)
        _await_producer_effective(client)
        response = _send_request_raw(
            sock,
            _scoring_request("req-sf-0", "plan-sf-0", "\u5b58\u50a8", ["\u5b58\u50a8"]),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("storage_base_score")
        observations = os.path.join(sf_root, "observations.jsonl")
        os.chmod(observations, 0o400)
        try:
            started = time.monotonic()
            response = _send_request_raw(
                sock,
                _scoring_request("req-sf-1", "plan-sf-1", "\u5b58\u50a8\u6545\u969c", ["\u5b58\u50a8\u6545\u969c"]),
                timeout=10.0,
            )
            elapsed_ms = (time.monotonic() - started) * 1000
            if not response or "scores" not in response:
                raise CheckFailure("storage_fault_score")
            if elapsed_ms > WATCHDOG_MS:
                raise CheckFailure("storage_fault_watchdog")
            status = _await(
                lambda: (
                    lambda body: body if body.get("storage_failure") else None
                )(_body(client.call("checkpoint"))),
                timeout=10.0,
                interval=0.2,
            )
            if not status:
                raise CheckFailure("storage_failure_not_reported")
            response = _send_request_raw(
                sock,
                _scoring_request("req-sf-2", "plan-sf-2", "\u5b58\u50a8\u4ecd\u6545\u969c", ["\u5b58\u50a8\u4ecd\u6545\u969c"]),
                timeout=10.0,
            )
            if not response or "scores" not in response:
                raise CheckFailure("storage_fault_persist_score")
        finally:
            os.chmod(observations, 0o600)
        daemon.stop()
        return {"note": "storage_failure_observed_ms=%d" % int(elapsed_ms)}

    def c_malformed_peer(self):
        peer_dir = os.path.join(self.root, "peer")
        os.makedirs(peer_dir, mode=0o700, exist_ok=True)
        peer_sock = os.path.join(peer_dir, "collector.sock")
        peer = MalformedPeer(peer_sock)
        self.peers.append(peer)
        daemon, sock = self.daemon("peer", archive_socket=peer_sock)
        started = time.monotonic()
        response = _send_request_raw(
            sock,
            _scoring_request("req-peer-1", "plan-peer-1", "\u6076\u610f\u540c\u4f34", ["\u6076\u610f\u540c\u4f34"]),
            timeout=10.0,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        if not response or "scores" not in response:
            raise CheckFailure("peer_score")
        if elapsed_ms > WATCHDOG_MS:
            raise CheckFailure("peer_watchdog")
        if not _await(lambda: peer.received, timeout=5.0):
            raise CheckFailure("peer_never_contacted")
        if not _await(lambda: "policy_observe" in peer.received, timeout=5.0):
            raise CheckFailure("peer_no_policy")
        # Nothing the malformed peer returned can be a durable observation.
        with open(os.path.join(self.root, "peer.received.json"), "w") as handle:
            json.dump(sorted(set(peer.received)), handle, sort_keys=True)
            handle.write("\n")
        os.chmod(os.path.join(self.root, "peer.received.json"), 0o600)
        daemon.stop()
        return {"note": "completion_ms=%d ops=%s" % (
            int(elapsed_ms), ",".join(sorted(set(peer.received))))}

    def c_passive_reads(self):
        main = self.main
        # A dedicated daemon with a controlled (short) idle clock: the real
        # production watchdog unloads it, while passive reads keep working.
        idle_daemon, idle_sock = self.daemon(
            "idle", archive_socket=main["sock"], idle_timeout=4.0,
        )
        response = _send_request_raw(
            idle_sock,
            _scoring_request("req-idle-1", "plan-idle-1", "\u7a7a\u95f2", ["\u7a7a\u95f2"]),
            timeout=10.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("idle_load_request")
        view = _await(
            lambda: (
                lambda v: v if v.get("state") == "loaded" else None
            )(_daemon_view(main["client"])),
            timeout=10.0,
        )
        if not view:
            raise CheckFailure("state_not_loaded")
        # The scoring outcome of the idle request must be durable before the
        # baseline so the loop's assertion attributes new rows correctly.
        _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "scoring"
                and row.get("request_id") == "req-idle-1"
                for row in rows
            ),
            timeout=10.0,
        )
        baseline_activity = len([
            row for row in _daemon_rows(main["client"])
            if row.get("daemon_stage") in {"request", "scoring"}
        ])
        deadline = time.monotonic() + 30.0
        staleness_seen = False
        while time.monotonic() < deadline:
            view = _daemon_view(main["client"])
            if view.get("state") == "loaded" and view.get("freshness") == "stale":
                staleness_seen = True
            if view.get("state") == "unloaded":
                break
            time.sleep(0.25)
        if not view or view.get("state") != "unloaded":
            raise CheckFailure("idle_unload_not_observed")
        if not staleness_seen:
            raise CheckFailure("freshness_stale_never_seen")
        rows = _daemon_rows(main["client"])
        unloads = [
            row for row in rows
            if row.get("daemon_stage") == "unload"
            and row.get("unload_reason") == "unspecified"
        ]
        if len(unloads) < 1:
            raise CheckFailure("idle_reason_missing")
        activity = [
            row for row in rows
            if row.get("daemon_stage") in {"request", "scoring"}
        ]
        if len(activity) != baseline_activity:
            raise CheckFailure("passive_reads_created_activity")
        # Trap the scoring endpoint: the daemon is gone, passive reads still
        # return the last-observed durable state.
        idle_daemon.stop()
        view = _daemon_view(main["client"])
        if view.get("state") != "unloaded":
            raise CheckFailure("state_after_process_exit")
        if view.get("freshness") not in {"fresh", "stale"}:
            raise CheckFailure("freshness_after_process_exit")
        return {"note": "idle_unload_without_health_or_scoring"}

    def c_protocol_controls(self):
        main = self.main
        with_archive = main["daemon_sock"]
        # A second daemon without archive observation.
        plain, plain_sock = self.daemon("plain")
        context = "%s protocol" % CANARY
        candidates = ["\u653b\u51fb", "\u516c\u9e21"]
        pairs = []
        for path in (with_archive, plain_sock):
            request = _scoring_request(
                "req-proto-ok", "plan-proto-ok", context, candidates,
            )
            pairs.append(_send_request_raw(path, request, timeout=10.0))
            pairs.append(_send_request_raw(
                path,
                _scoring_request(
                    "req-proto-err", "plan-proto-err",
                    context, candidates, policy_id="other-policy-v1",
                ),
                timeout=10.0,
            ))
            pairs.append(_exchange(path, b"notjson\n", timeout=10.0))
            pairs.append(_exchange(
                path,
                b'{"version":2,"version":2,"request_id":"x","plan_identity":"p",'
                b'"baseline_policy_id":"mean-token-lm-v1","context":"","candidates":["a"]}\n',
                timeout=10.0,
            ))
            pairs.append(_send_request_raw(
                path,
                {
                    "version": 1, "request_id": "req-v1", "plan_identity": "plan-v1",
                    "baseline_policy_id": "mean-token-lm-v1",
                    "context": "", "candidates": ["a"],
                },
                timeout=10.0,
            ))
            pairs.append(_send_request_raw(
                path,
                _scoring_request("req-empty-cand", "plan-empty-cand", "", [""]),
                timeout=10.0,
            ))
        def shape(response):
            if response is None:
                return None
            if "error" in response:
                error = dict(response["error"])
                error.pop("occurred_at", None)
                return {"error": error, "request_id": response.get("request_id")}
            return {"scores": response.get("scores")}

        first, second = shape(pairs[0]), shape(pairs[6])
        if first != second or not first or "scores" not in first:
            raise CheckFailure("score_divergence")
        for offset, expected in (
            (1, "policy_mismatch"),
            (2, "invalid_json"),
            (3, "invalid_json"),
            (4, "invalid_request"),
            (5, "invalid_request"),
        ):
            left = shape(pairs[offset])
            right = shape(pairs[6 + offset])
            if left != right or not left or left.get("error", {}).get("code") != expected:
                raise CheckFailure(
                    "proto_shape_%s:%s|%s" % (
                        expected,
                        json.dumps(left, sort_keys=True),
                        json.dumps(right, sort_keys=True),
                    )
                )
        # Health is additive v2 and must not create daemon observations. All
        # capture-on protocol exchanges must be durable before the baseline.
        _await_durable_rows(
            main["client"],
            lambda rows, status: any(
                row.get("daemon_stage") == "scoring"
                and row.get("request_id") == "req-proto-ok"
                for row in rows
            ),
            timeout=10.0,
        )
        _durable_now(main["client"])
        before = len(_daemon_rows(main["client"]))
        health = _send_request_raw(
            with_archive,
            {"version": 2, "request_id": "health-1", "kind": "health"},
            timeout=10.0,
        )
        if (health or {}).get("kind") != "health" or "health" not in health:
            raise CheckFailure("health_shape")
        _durable_now(main["client"])
        after = len(_daemon_rows(main["client"]))
        if after != before:
            raise CheckFailure("health_created_observation")
        # Timeout control: a half-open request gets the transport error shape.
        started = time.monotonic()
        response = _exchange(with_archive, b"", timeout=10.0, read_reply=False)
        # Send a partial frame then wait for the server's deadline response.
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(10.0)
        conn.connect(with_archive)
        conn.sendall(b'{"version":2,')
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        conn.close()
        timeout_response = json.loads(data.decode("utf-8"))
        if timeout_response.get("error", {}).get("code") != "server_error":
            raise CheckFailure("timeout_shape")
        if (time.monotonic() - started) < 4.5:
            raise CheckFailure("timeout_too_fast")
        plain.stop()
        return {"note": "paired_capture_on_off_shapes"}

    def c_version_refusals(self):
        main = self.main
        client = main["client"]
        before = _body(client.call("status")).get("admission_refused_units")
        frames = [
            _frame("request", 1, daemon_observation_version=2),
            _frame("request", 2, drop=("daemon_observation_version",)),
            _frame("request", 3, observed_at_wall_ms=-1),
            _frame("request", 4, edges={}),
            _frame("request", 5, effective_context_chars=100),
        ]
        expected = [
            "unsupported_daemon_observation",
            "unsupported_daemon_observation",
            "invalid_request",
            "invalid_request",
            "invalid_request",
        ]
        response = client.call("admit_batch", {"observations": frames})
        codes = _body(response).get("codes")
        if codes != expected:
            raise CheckFailure("refusal_codes")
        after = _body(client.call("status")).get("admission_refused_units")
        if not isinstance(after, int) or not isinstance(before, int):
            raise CheckFailure("refusal_counter_missing")
        if after - before != expected.count("invalid_request"):
            raise CheckFailure("refusal_counter")
        _durable_now(client)
        rows = _daemon_rows(client)
        for row in rows:
            if row.get("daemon_observation_version") not in (1,):
                raise CheckFailure("unsupported_stored")
        return {"note": "version_and_malformed_refused"}

    def c_canary_scan(self):
        main = self.main
        _durable_now(main["client"])
        report_text = json.dumps(self.report(), sort_keys=True)
        _ordinary_content_free(report_text, "report")
        for log_path in self.logs:
            if os.path.exists(log_path):
                with open(log_path, "rb") as handle:
                    data = handle.read()
                _ordinary_content_free(data.decode("utf-8", "replace"), "daemon_log")
        for root, _sock in self.collectors:
            for name in ("collector.out", "collector.err"):
                path = os.path.join(root, name)
                if os.path.exists(path):
                    with open(path, "rb") as handle:
                        data = handle.read()
                    _ordinary_content_free(data.decode("utf-8", "replace"), "collector_log")
        view = _daemon_view(main["client"])
        _ordinary_content_free(json.dumps(view, sort_keys=True), "daemon_view")
        # Deliberately private content exists for admitted requests at least
        # once (healthy contrast is asserted by the pause/resume case).
        return {"note": "ordinary_outputs_clean"}

    # -- reporting ---------------------------------------------------------
    def report(self):
        executed = {name: self.cases.get(name, "missing") for name in self.order}
        missing = [name for name in self.order if name not in self.cases]
        skipped = []
        unknown = []
        failed = [name for name, state in executed.items() if state == "fail"]
        return {
            "checker": "check_input_archive_daemon",
            "suite": "contract",
            "passed": not failed and not missing,
            "cases": executed,
            "failures": {name: self.notes.get(name, "") for name in failed},
            "missing": missing,
            "skipped": skipped,
            "unknown": unknown,
            "required_cases": list(self.order),
            "watchdogs_ms": self.watchdogs,
            "source_identity": _source_identity(),
            "runtime_identity": _runtime_identity(),
            "root": self.root,
            "content_included": False,
            "latency_certification": False,
            "host_persistence_proof": False,
            "merge_enables_capture": False,
        }


def _frame(stage, sequence, version=1, drop=(), **extra):
    frame = {
        "envelope_version": 1,
        "content_version": 1,
        "schema_id": "unknown",
        "source_instance_id": "daemon-check",
        "source_local_sequence": sequence,
        "observation_kind": "daemon_observation",
        "daemon_observation_version": version,
        "daemon_stage": stage,
        "stage": stage,
        "process_id": "proc-%d" % sequence,
        "observed_at_wall_ms": int(time.time() * 1000),
        "eligibility": "included",
        "host_persistence": "unknown",
    }
    if stage == "request":
        frame.update({
            "request_id": "req-%d" % sequence,
            "plan_identity": "plan-%d" % sequence,
            "effective_policy_id": "mean-token-lm-v1",
            "declared_policy_digest": "0" * 64,
            "declared_policy_exact": True,
            "scoring_strategy": "mean_token",
            "context_window_rule": "unicode_char_tail",
            "attribution_rule": "decode_prefix_reconstruction",
            "context_window_chars": 64,
            "requested_context_chars": 4,
            "effective_context_chars": 4,
            "context_truncated": False,
            "candidate_count": 1,
            "candidate_chars": 2,
            "model_identity": "fixture-model",
            "model_identity_basis": "daemon_model_path_basename_unverified_content",
            "adapter_present": False,
            "adapter_digest": None,
            "edges": {"request_accepted": 1.0},
            "payload": {"requested_context": CANARY, "effective_context": CANARY,
                        "candidates": [CANARY]},
        })
    for key in drop:
        frame.pop(key, None)
    frame.update(extra)
    return frame


def self_test():
    root = os.path.realpath(tempfile.mkdtemp(prefix="ac191-st-"))
    os.chmod(root, 0o700)
    sock = os.path.join(root, "collector.sock")
    _collector_start(root, sock)
    try:
        client = Client(sock, timeout=5)
        client.set_policy("enabled", 0)
        response = client.call("admit_batch", {
            "observations": [_frame("request", 1, daemon_observation_version=2)],
        })
        if _body(response).get("codes") != ["unsupported_daemon_observation"]:
            raise CheckFailure("version_refusal")
        response = client.call("admit_batch", {
            "observations": [_frame("request", 2, observed_at_wall_ms=0)],
        })
        if _body(response).get("codes") != ["invalid_request"]:
            raise CheckFailure("malformed_refusal")
        same = _frame("request", 3)
        response = client.call("admit_batch", {"observations": [same]})
        if _body(response).get("codes") != ["admitted"]:
            raise CheckFailure("request_admit")
        response = client.call("admit_batch", {"observations": [_frame("request", 4)]})
        if _body(response).get("codes") != ["admitted"]:
            raise CheckFailure("second_admit")
        response = client.call("admit_batch", {"observations": [same]})
        if _body(response).get("codes") != ["duplicate"]:
            raise CheckFailure("duplicate")
        conflict = _frame("request", 3, effective_policy_id="legacy_sum")
        response = client.call("admit_batch", {"observations": [conflict]})
        if _body(response).get("codes") != ["identity_conflict"]:
            raise CheckFailure("conflict")
        client.checkpoint()
        view = _daemon_view(client)
        text = json.dumps(view, sort_keys=True)
        _ordinary_content_free(text, "self_test_view")
        if view.get("state") != "unknown" or view.get("freshness") != "unknown":
            raise CheckFailure("self_test_state")
        if view.get("daemon_observations") != 2:
            raise CheckFailure("self_test_count")
        status = json.dumps(client.status(), sort_keys=True)
        _ordinary_content_free(status, "self_test_status")
        if "separately_configured_may_continue" not in status:
            raise CheckFailure("legacy_disclosure")
        skipped_probe = {"passed": False, "skipped": ["missing-required"]}
        if not skipped_probe["skipped"] or skipped_probe["passed"]:
            raise CheckFailure("skipped_probe")
    finally:
        _collector_stop(root, sock)
    print("self-test passed")
    return 0


# ---------------------------------------------------------------------------
# Model suite: real daemon process, real MLX cold load, natural idle unload.
# ---------------------------------------------------------------------------


def _model_identity(model_path, adapter_path):
    sys.path.insert(0, DAEMON_DIR)
    from personal_lora_live import pin_live_identities

    record = pin_live_identities(model_path, adapter_path)
    return {
        "model_basename": record["model"]["basename"],
        "model_composite_sha256": record["model"]["composite_sha256"],
        "model_weights_sha256": record["model"]["files"]["model.safetensors"]["sha256"],
        "adapter_sha256": record["adapter"]["sha256"],
        "runtime_versions": record["versions"],
    }


class ModelSuite(object):
    def __init__(self, root, model_path, adapter_path):
        self.root = root
        self.model_path = model_path
        self.adapter_path = adapter_path
        self.cases = {}
        self.order = (
            "ModelIdentityPinsVerified",
            "ColdLoadAndScoringObserved",
            "CaptureOffOnSameScores",
            "LongAndEmptyContextWindow",
            "NaturalIdleUnloadPassiveReads",
        )
        self.collector = None
        self.daemon = None
        self.daemon_log = None
        self.notes = {}
        self.durations = {}

    def case(self, name, fn):
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

    def run(self):
        try:
            self.case("ModelIdentityPinsVerified", self.c_identity)
            self.case("ColdLoadAndScoringObserved", self.c_cold)
            self.case("CaptureOffOnSameScores", self.c_contrast)
            self.case("LongAndEmptyContextWindow", self.c_windows)
            self.case("NaturalIdleUnloadPassiveReads", self.c_idle)
        finally:
            self._cleanup()

    def _cleanup(self):
        if self.daemon is not None and self.daemon.poll() is None:
            self.daemon.terminate()
            try:
                self.daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.daemon.kill()
                self.daemon.wait(timeout=5)
        if self.collector is not None:
            root, sock = self.collector
            _collector_stop(root, sock)

    def _start(self):
        if self.collector is not None:
            return
        root = self.root
        os.makedirs(root, mode=0o700, exist_ok=True)
        croot = os.path.join(root, "collector")
        csock = os.path.join(croot, "collector.sock")
        os.makedirs(croot, mode=0o700, exist_ok=True)
        _collector_start(croot, csock)
        self.collector = (croot, csock)
        client = Client(csock, timeout=5)
        self.client = client
        facts = os.path.join(root, "facts")
        os.makedirs(facts, mode=0o700, exist_ok=True)
        os.chmod(facts, 0o700)
        dsock = os.path.join(root, "daemon.sock")
        log_path = os.path.join(root, "daemon.log")
        self.daemon_log = open(log_path, "wb")
        self.daemon = subprocess.Popen(
            [
                sys.executable, SCORING_DAEMON_ENTRY, "--serve",
                "--socket", dsock,
                "--model", self.model_path,
                "--adapter", self.adapter_path,
                "--facts-root", facts,
                "--archive-socket", csock,
            ],
            cwd=REPO,
            stdout=self.daemon_log,
            stderr=subprocess.STDOUT,
        )
        if not _wait_for_socket(dsock, timeout=30.0):
            raise CheckFailure("daemon_not_ready")
        self.dsock = dsock

    def c_identity(self):
        identity = _model_identity(self.model_path, self.adapter_path)
        self.model_identity = identity
        return {"note": "pins_verified"}

    def c_cold(self):
        self._start()
        identity = getattr(self, "model_identity", None)
        if identity is None:
            identity = _model_identity(self.model_path, self.adapter_path)
            self.model_identity = identity
        _enable_capture(self.client)
        _await_producer_effective(self.client)
        context = "%s cold" % CANARY
        started = time.monotonic()
        response = _send_request_raw(
            self.dsock,
            _scoring_request(
                "model-req-cold", "model-plan-cold", context,
                ["\u653b\u51fb", "\u516c\u9e21"],
            ),
            timeout=REQUEST_WATCHDOG_MS / 1000.0,
        )
        cold_ms = (time.monotonic() - started) * 1000
        self.durations["cold_request_ms"] = cold_ms
        if not response or "scores" not in response:
            raise CheckFailure("cold_score")
        self.cold_scores = response["scores"]
        rows = _await_durable_rows(
            self.client,
            lambda rows, status: any(
                row.get("daemon_stage") == "scoring"
                and row.get("request_id") == "model-req-cold"
                for row in rows
            ),
            timeout=30.0,
        )
        if not rows:
            raise CheckFailure("cold_records")
        scoring = [
            row for row in rows
            if row.get("daemon_stage") == "scoring"
            and row.get("request_id") == "model-req-cold"
        ]
        loads = [row for row in rows if row.get("daemon_stage") == "load"]
        if len(scoring) != 1 or len(loads) != 1:
            raise CheckFailure("cold_record_count")
        if scoring[0].get("load_included") is not True:
            raise CheckFailure("cold_load_flag")
        load = loads[0]
        if load.get("load_outcome") != "completed":
            raise CheckFailure("cold_load_outcome")
        if load.get("model_identity") != identity["model_basename"]:
            raise CheckFailure("cold_model_identity")
        if load.get("model_weights_sha256") != identity["model_weights_sha256"]:
            raise CheckFailure("cold_weights_digest")
        if load.get("adapter_digest") != identity["adapter_sha256"]:
            raise CheckFailure("cold_adapter_digest")
        versions = load.get("runtime_versions") or {}
        if versions.get("mlx") != identity["runtime_versions"].get("mlx"):
            raise CheckFailure("cold_runtime_identity")
        return {"note": "cold_request_ms=%d" % int(cold_ms)}

    def c_contrast(self):
        context = "%s contrast" % CANARY
        # Capture-off request (policy was never enabled at that point is not
        # true here: capture is on). Instead compare the same input scored
        # with capture on to the capture-off baseline recorded before the
        # enable; the baseline is produced now with the policy paused.
        _set_policy(self.client, "paused")
        time.sleep(2.6)
        response_off = _send_request_raw(
            self.dsock,
            _scoring_request(
                "model-req-off", "model-plan-off", context,
                ["\u653b\u51fb", "\u516c\u9e21"],
            ),
            timeout=REQUEST_WATCHDOG_MS / 1000.0,
        )
        _enable_capture(self.client)
        _await_producer_effective(self.client)
        response_on = _send_request_raw(
            self.dsock,
            _scoring_request(
                "model-req-on", "model-plan-on", context,
                ["\u653b\u51fb", "\u516c\u9e21"],
            ),
            timeout=REQUEST_WATCHDOG_MS / 1000.0,
        )
        if not response_off or "scores" not in response_off:
            raise CheckFailure("contrast_off")
        if not response_on or "scores" not in response_on:
            raise CheckFailure("contrast_on")
        if response_off["scores"] != response_on["scores"]:
            raise CheckFailure("capture_changed_scores")
        if getattr(self, "cold_scores", None) is not None:
            # Same model, same contract: the cold scores used a different
            # context, so only record them; equality is asserted for the
            # paired on/off requests above.
            pass
        rows = _await_durable_rows(
            self.client,
            lambda rows, status: any(
                row.get("request_id") == "model-req-on" for row in rows
            ),
            timeout=30.0,
        )
        for row in rows or []:
            if row.get("request_id") == "model-req-off":
                raise CheckFailure("capture_off_recorded")
        return {"note": "paired_scores_equal"}

    def c_windows(self):
        long_context = CANARY + "\u5e8f" * 100
        response = _send_request_raw(
            self.dsock,
            _scoring_request(
                "model-req-long", "model-plan-long", long_context,
                ["\u957f\u4e0a\u6587"],
            ),
            timeout=REQUEST_WATCHDOG_MS / 1000.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("long_score")
        response = _send_request_raw(
            self.dsock,
            _scoring_request(
                "model-req-empty", "model-plan-empty", "", ["\u7a7a\u4e0a\u6587"],
            ),
            timeout=REQUEST_WATCHDOG_MS / 1000.0,
        )
        if not response or "scores" not in response:
            raise CheckFailure("empty_score")
        rows = _await_durable_rows(
            self.client,
            lambda rows, status: any(
                row.get("request_id") == "model-req-empty" and row.get("daemon_stage") == "request"
                for row in rows
            ),
            timeout=30.0,
        )
        long_rows = [
            row for row in rows
            if row.get("daemon_stage") == "request" and row.get("request_id") == "model-req-long"
        ]
        if len(long_rows) != 1 or long_rows[0].get("effective_context_chars") != 64:
            raise CheckFailure("long_window")
        empty_rows = [
            row for row in rows
            if row.get("daemon_stage") == "request" and row.get("request_id") == "model-req-empty"
        ]
        if len(empty_rows) != 1 or empty_rows[0].get("effective_context_chars") != 0:
            raise CheckFailure("empty_window")
        return {"note": "window_64_and_empty"}

    def c_idle(self):
        # Natural idle unload: production IDLE_TIMEOUT stays 300 s and the
        # passive loop must not reset activity. Reads every 20 s.
        started = time.monotonic()
        deadline = started + IDLE_WATCHDOG_MS / 1000.0
        self.durations["idle_wait_started_wall"] = int(time.time())
        saw_stale = False
        view = None
        while time.monotonic() < deadline:
            view = _daemon_view(self.client)
            if view.get("state") == "loaded" and view.get("freshness") == "stale":
                saw_stale = True
            if view.get("state") == "unloaded":
                break
            time.sleep(20.0)
        if not view or view.get("state") != "unloaded":
            raise CheckFailure("idle_unload_not_observed")
        idle_ms = (time.monotonic() - started) * 1000
        self.durations["idle_unload_ms"] = idle_ms
        if idle_ms > IDLE_WATCHDOG_MS:
            raise CheckFailure("idle_watchdog")
        if not saw_stale:
            raise CheckFailure("freshness_stale_never_seen")
        rows = _daemon_rows(self.client)
        unloads = [
            row for row in rows
            if row.get("daemon_stage") == "unload"
            and row.get("unload_reason") == "unspecified"
        ]
        if not unloads:
            raise CheckFailure("idle_unload_record")
        # Passive reads did not create scoring or request activity.
        requests = [
            row for row in rows
            if row.get("daemon_stage") in {"request", "scoring"}
            and row.get("request_id") not in {
                "model-req-cold", "model-req-off", "model-req-on",
                "model-req-long", "model-req-empty",
            }
        ]
        if requests:
            raise CheckFailure("unexpected_activity")
        # Capture-off request was never recorded (no backfill after resume).
        for row in rows:
            if row.get("request_id") == "model-req-off":
                raise CheckFailure("capture_off_recorded")
        return {"note": "idle_unload_ms=%d" % int(idle_ms)}

    def report(self):
        executed = {name: self.cases.get(name, "missing") for name in self.order}
        missing = [name for name in self.order if name not in self.cases]
        failed = [name for name, state in executed.items() if state == "fail"]
        return {
            "checker": "check_input_archive_daemon",
            "suite": "model",
            "passed": not failed and not missing,
            "cases": executed,
            "failures": {name: self.notes.get(name, "") for name in failed},
            "missing": missing,
            "skipped": [],
            "unknown": [],
            "required_cases": list(self.order),
            "watchdogs_ms": {
                "cold_request_ms": REQUEST_WATCHDOG_MS,
                "request_ms": REQUEST_WATCHDOG_MS,
                "idle_unload_ms": IDLE_WATCHDOG_MS,
            },
            "durations": self.durations,
            "model_requested": self.model_path,
            "adapter_requested": self.adapter_path,
            "model_identity": getattr(self, "model_identity", None),
            "source_identity": _source_identity(),
            "runtime_identity": _runtime_identity(),
            "root": self.root,
            "content_included": False,
            "latency_certification": False,
            "host_persistence_proof": False,
            "ranking_benefit": False,
            "merge_enables_capture": False,
        }


def _write_report(path, report):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = json.dumps(report, sort_keys=True, ensure_ascii=True)
    _ordinary_content_free(payload, "report")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload + "\n")
    os.chmod(path, 0o600)


def contract(root, report_path):
    os.makedirs(root, mode=0o700, exist_ok=True)
    suite = ContractSuite(root)
    suite.run()
    report = suite.report()
    _write_report(report_path, report)
    for name in suite.order:
        state = report["cases"].get(name)
        note = report["failures"].get(name) or suite.notes.get(name) or ""
        print("%s %s%s" % (state.upper(), name, (" (%s)" % note) if note else ""))
    if not report["passed"]:
        print("missing=%s" % ",".join(report["missing"]))
        return 1
    print("contract passed")
    return 0


def model(root, report_path, model_path, adapter_path):
    os.makedirs(root, mode=0o700, exist_ok=True)
    suite = ModelSuite(root, model_path, adapter_path)
    suite.run()
    report = suite.report()
    _write_report(report_path, report)
    for name in suite.order:
        state = report["cases"].get(name)
        note = report["failures"].get(name) or suite.notes.get(name) or ""
        print("%s %s%s" % (state.upper(), name, (" (%s)" % note) if note else ""))
    if not report["passed"]:
        return 1
    print("model suite passed")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description="Daemon archive observation checker")
    parser.add_argument("--fixture-daemon", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract", "model"))
    parser.add_argument("--root", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--adapter", default="")
    parser.add_argument("--socket", default="")
    parser.add_argument("--archive-socket", default="")
    parser.add_argument("--facts-root", default="")
    parser.add_argument("--idle-timeout", type=float, default=300.0)
    parser.add_argument("--idle-check-interval", type=float, default=10.0)
    parser.add_argument("--barrier-file", default="")
    args = parser.parse_args(argv)
    if args.fixture_daemon:
        return _run_fixture_daemon(argv)
    try:
        if args.self_test:
            return self_test()
        if args.suite == "contract":
            if not args.root or not args.report:
                raise CheckFailure("invalid_request")
            return contract(args.root, args.report)
        if args.suite == "model":
            if not args.root or not args.report or not args.model or not args.adapter:
                raise CheckFailure("invalid_request")
            return model(args.root, args.report, args.model, args.adapter)
        raise CheckFailure("invalid_request")
    except CheckFailure as exc:
        sys.stderr.write("code=%s\n" % exc.code)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
