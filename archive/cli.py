"""CLI adapter over the shared input-archive Interface.

The CLI does not open observation storage. Collector start only spawns
`archive.collector`.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import select
import signal
import subprocess
import sys
import time

from archive.interface import (
    INTERFACE_VERSION,
    Client,
    InterfaceError,
    parse_readiness,
    strip_content,
)
from archive.producer import Producer
from archive.safety import UnsafeRoot, escape_terminal_data, open_nofollow, validate_root

_COLLECTOR_FLAGS = (
    "no_auto_checkpoint",
    "publication_hold",
    "publication_phase_hold",
    "control_hold",
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
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Input-archive CLI adapter")
    parser.add_argument("--socket", default="")
    parser.add_argument("--root", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    sub = parser.add_subparsers(dest="command")

    collector = sub.add_parser("collector")
    collector_sub = collector.add_subparsers(dest="collector_command")
    start = collector_sub.add_parser("start")
    _add_collector_flags(start)
    collector_sub.add_parser("stop")

    policy = sub.add_parser("policy")
    policy.add_argument("action", choices=("enable", "pause", "resume", "off", "status"))
    policy.add_argument("--expect-revision", type=int)

    query = sub.add_parser("query")
    query.add_argument("view", choices=("overview", "timeline", "process", "losses", "status"))
    query.add_argument("--process-id", default="")
    query.add_argument("--private-detail", action="store_true")
    query.add_argument("--page-size", type=int)
    query.add_argument("--cursor", default="")

    admit = sub.add_parser("admit")
    admit.add_argument("--fixture", required=True)
    admit.add_argument("--source-instance-id", default="synthetic-producer")
    admit.add_argument("--heartbeat-interval-ms", type=int, default=50)
    admit.add_argument("--freshness-window-ms", type=int, default=2000)

    sub.add_parser("checkpoint")
    sub.add_parser("status")
    sub.add_parser("tui")
    args = parser.parse_args(argv)
    if args.command == "collector" and args.collector_command == "start":
        return _start(args)
    if args.command == "collector" and args.collector_command == "stop":
        return _stop(args)
    if args.command == "status" or (args.command == "policy" and args.action == "status"):
        return _print(args, _client(args).status())
    if args.command == "policy":
        return _policy(args)
    if args.command == "query":
        return _query(args)
    if args.command == "checkpoint":
        return _print(args, _client(args).checkpoint())
    if args.command == "admit":
        return _admit(args)
    if args.command == "tui":
        return _tui(args)
    parser.print_help(sys.stderr)
    return 2


def _add_collector_flags(parser):
    parser.add_argument("--no-auto-checkpoint", action="store_true")
    parser.add_argument("--publication-hold", default="")
    parser.add_argument("--publication-phase-hold", default="")
    parser.add_argument("--control-hold", default="")
    for name in (
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
        parser.add_argument("--" + name.replace("_", "-"), dest=name, type=int)
    parser.add_argument("--warning-ratio", dest="warning_ratio", type=float)


def _start(args):
    if not args.root or not args.socket:
        sys.stderr.write("code=invalid_request\n")
        return 2
    try:
        validate_root(args.root)
    except UnsafeRoot:
        sys.stderr.write("code=unsafe_root\n")
        return 2
    if not os.path.isdir(args.root):
        os.mkdir(args.root, 0o700)
    os.chmod(args.root, 0o700)
    stdout_path = os.path.join(args.root, "collector.out")
    stderr_path = os.path.join(args.root, "collector.err")
    out_fd = None
    try:
        # Append, never truncate: a refused start must not erase the live
        # owner's own diagnostics before it discovers it is not the owner.
        out_fd = open_nofollow(stdout_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
        err_fd = open_nofollow(stderr_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    except UnsafeRoot:
        if out_fd is not None:
            os.close(out_fd)
        sys.stderr.write("code=unsafe_root\n")
        return 2
    try:
        read_fd, write_fd = _readiness_pipe()
    except OSError:
        os.close(out_fd)
        os.close(err_fd)
        sys.stderr.write("code=collector_unavailable\n")
        return 1
    token = secrets.token_hex(16)
    command = [sys.executable, "-m", "archive.collector", "--root", args.root, "--socket", args.socket]
    command.extend(_forward_flags(args))
    command.extend(["--ready-fd", str(write_fd), "--ready-token", token])
    try:
        proc = subprocess.Popen(
            command,
            stdout=out_fd,
            stderr=err_fd,
            start_new_session=True,
            pass_fds=(write_fd,),
        )
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        os.close(out_fd)
        os.close(err_fd)
        sys.stderr.write("code=collector_unavailable\n")
        return 1
    os.close(out_fd)
    os.close(err_fd)
    os.close(write_fd)
    try:
        outcome, code = _await_readiness(proc, read_fd, token, args.timeout)
    finally:
        os.close(read_fd)
    if outcome == "ready" and _confirm_owner(args, proc, args.timeout):
        sys.stdout.write("interface_version=%s\n" % INTERFACE_VERSION)
        sys.stdout.write("collector_started=true\n")
        sys.stdout.write("capture_enabled=false\n")
        sys.stdout.write("pid=%s\n" % proc.pid)
        sys.stdout.write("owner_pid=%s\n" % proc.pid)
        sys.stdout.write("content_included=false\n")
        return 0
    if outcome == "ready":
        # The child reported readiness but the endpoint or PID metadata does
        # not describe it. Never claim success for an unverified owner.
        code = "collector_unavailable"
    _reap(proc, args.timeout)
    sys.stderr.write("code=%s\n" % code)
    return 1


def _readiness_pipe():
    """A pipe whose read end stays with this CLI and write end goes to the child."""
    read_fd, write_fd = os.pipe()
    return _high_fd(read_fd), _high_fd(write_fd)


def _high_fd(fd):
    """Move a descriptor above the stdio range, or fail with OSError.

    F_DUPFD asks the kernel for the lowest descriptor at or above 3 in one
    step, so this cannot loop or hand a stdio slot to the child.
    """
    if fd >= 3:
        return fd
    spare = fcntl.fcntl(fd, fcntl.F_DUPFD, 3)
    os.close(fd)
    return spare


def _await_readiness(proc, read_fd, token, timeout):
    """Bounded wait for this attempt's own readiness or refusal line."""
    deadline = time.time() + max(0.5, timeout)
    buffer = b""
    while time.time() < deadline:
        remaining = max(0.0, deadline - time.time())
        readable, _, _ = select.select([read_fd], [], [], min(0.05, remaining))
        if readable:
            chunk = os.read(read_fd, 256)
            if not chunk:
                break
            buffer += chunk
            if b"\n" in buffer:
                break
            continue
        if proc.poll() is not None:
            break
    line = buffer.split(b"\n", 1)[0].decode("ascii", "replace") if buffer else ""
    parsed = parse_readiness(line, token, proc.pid)
    if parsed is None:
        return "failed", "collector_unavailable"
    return parsed


def _confirm_owner(args, proc, timeout):
    """Confirm the answering endpoint, root metadata and this child agree.

    A single probe can miss a child that has only just started serving under
    load, and killing a healthy owner is worse than retrying briefly, so this
    re-probes inside a bounded window before a start is called unverified.
    """
    deadline = time.time() + max(0.5, min(2.0, timeout))
    while True:
        try:
            response = Client(args.socket, timeout=0.2).status()
            body = response.get("body") or {}
            if response.get("ok") and body.get("owner_pid") == proc.pid and _read_pid(args.root) == proc.pid:
                return True
        except (OSError, InterfaceError):
            pass
        if proc.poll() is not None or time.time() >= deadline:
            return False
        time.sleep(0.05)


def _reap(proc, timeout):
    """Reap only the child this CLI spawned; never the root's incumbent."""
    bound = min(2.0, max(0.5, timeout))
    try:
        proc.wait(timeout=bound)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=bound)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=bound)
    except subprocess.TimeoutExpired:
        pass


def _forward_flags(args):
    forwarded = []
    if getattr(args, "no_auto_checkpoint", False):
        forwarded.append("--no-auto-checkpoint")
    for name, flag in (
        ("publication_hold", "--publication-hold"),
        ("publication_phase_hold", "--publication-phase-hold"),
        ("control_hold", "--control-hold"),
    ):
        value = getattr(args, name, "")
        if value:
            forwarded.extend([flag, value])
    for name in _COLLECTOR_FLAGS:
        if name in {"no_auto_checkpoint", "publication_hold", "publication_phase_hold", "control_hold"}:
            continue
        value = getattr(args, name, None)
        if value is not None:
            forwarded.extend(["--" + name.replace("_", "-"), str(value)])
    return forwarded


def _stop(args):
    if not args.socket or not args.root:
        sys.stderr.write("code=invalid_request\n")
        return 2
    pid = _read_pid(args.root)
    response = Client(args.socket, timeout=args.timeout).shutdown()
    if pid and _command_is_collector(pid):
        deadline = time.time() + args.timeout
        while time.time() < deadline and _alive(pid):
            time.sleep(0.05)
        if _alive(pid) and _command_is_collector(pid):
            os.kill(pid, signal.SIGTERM)
    sys.stdout.write("collector_stop_requested=true\n")
    sys.stdout.write("content_included=false\n")
    if response.get("ok") or response.get("error", {}).get("code") == "collector_unavailable":
        return 0
    return 1


def _policy(args):
    if not args.socket:
        sys.stderr.write("code=invalid_request\n")
        return 2
    client = _client(args)
    desired = {"enable": "enabled", "resume": "enabled", "pause": "paused", "off": "off"}[args.action]
    expected = args.expect_revision
    if expected is None:
        status = client.status()
        if not status.get("ok"):
            return _print(args, status)
        expected = status["body"]["desired_revision"]
    return _print(args, client.set_policy(desired, expected))


def _query(args):
    kwargs = {}
    if args.page_size is not None:
        kwargs["page_size"] = args.page_size
    if args.cursor:
        kwargs["cursor"] = int(args.cursor) if args.cursor.isdigit() else args.cursor
    if args.process_id:
        kwargs["process_id"] = args.process_id
    if args.private_detail:
        kwargs["private_detail"] = True
    response = _client(args).query(args.view, **kwargs)
    return _print(args, response, private=args.private_detail and args.view == "process")


def _admit(args):
    try:
        fixture = json.loads(open(args.fixture, "r").read())
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("code=invalid_request\n")
        return 2
    observations = fixture.get("observations") if isinstance(fixture, dict) else fixture
    if not isinstance(observations, list):
        sys.stderr.write("code=invalid_request\n")
        return 2
    producer = Producer(
        args.socket,
        source_instance_id=args.source_instance_id,
        limits={
            "heartbeat_interval_ms": args.heartbeat_interval_ms,
            "freshness_window_ms": args.freshness_window_ms,
        },
    )
    try:
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            local = producer.local_status()
            if local.get("fresh"):
                break
            time.sleep(0.02)
        codes = []
        for item in observations:
            item = dict(item)
            item["source_instance_id"] = args.source_instance_id
            codes.append(producer.admit(item).code)
        time.sleep(0.05)
    finally:
        producer.close()
    counts = {}
    for code in codes:
        counts[code] = counts.get(code, 0) + 1
    response = {
        "ok": True,
        "body": {"codes": counts, "count": len(codes), "content_included": False},
        "content_included": False,
    }
    return _print(args, response)


def _tui(args):
    from archive.tui import run

    run(_client(args), sys.stdin, sys.stdout)
    return 0


def _client(args):
    if not args.socket:
        sys.stderr.write("code=invalid_request\n")
        raise SystemExit(2)
    return Client(args.socket, timeout=args.timeout)


def _print(args, response, private=False):
    if private and not args.json:
        _print_private_human(response)
    elif args.json:
        payload = response if private else strip_content(response)
        sys.stdout.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")
    else:
        _print_human(strip_content(response))
    return 0 if response.get("ok") else 1


def _print_human(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"payload", "text", "composition", "candidates", "committed_text"}:
                continue
            _print_human(item, prefix + key + ".")
        return
    if isinstance(value, list):
        sys.stdout.write("%scount=%s\n" % (prefix, len(value)))
        for index, item in enumerate(value):
            _print_human(item, "%s%s." % (prefix, index))
        return
    sys.stdout.write("%s=%s\n" % (prefix[:-1], _scalar(value)))


def _print_private_human(response):
    body = response.get("body") or {}
    sys.stdout.write("SCREEN private-detail\ncontent_included=true\n")
    for row in body.get("observations") or []:
        payload = row.get("payload")
        text = payload.get("text") if isinstance(payload, dict) else payload
        sys.stdout.write(
            "process=%s kind=%s text=%s\n"
            % (row.get("process_id"), row.get("observation_kind"), escape_terminal_data("" if text is None else str(text)))
        )


def _scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return escape_terminal_data(str(value))


def _read_pid(root):
    path = os.path.join(root, "collector.pid")
    try:
        return int(open(path, "r").read().strip())
    except (OSError, ValueError):
        return None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _command_is_collector(pid):
    try:
        command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return "archive.collector" in command


if __name__ == "__main__":
    sys.exit(main())
