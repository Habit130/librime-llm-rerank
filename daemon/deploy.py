#!/usr/bin/env python3
"""Portable phase-one daemon install/start/health/stop (Squirrel #131).

Project-local venv, pinned inference deps, and parameterized paths. Isolated
verification uses a health-only stand-in when a real model directory is not
configured. This tool never writes ~/Library/Rime or the live Squirrel
semantic-memory root unless those paths are passed explicitly.
"""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHECKOUT = os.path.dirname(HERE)
REQUIREMENTS_NAME = "requirements-daemon.txt"
PLIST_NAME = "com.squirrel.llm-rerank.plist"
SERVER_NAME = "server.py"
RUNTIME_NAME = ".local-run"
PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")
MIN_PYTHON = (3, 10)
HEALTH_REQUEST = {
    "version": 2,
    "request_id": "deploy-health",
    "kind": "health",
}
STANDIN_MODEL_NAME = "stand-in-model"


class DeployError(Exception):
    pass


def _die(message, code=2):
    print("error: %s" % message, file=sys.stderr)
    return code


def checkout_root(path):
    root = os.path.abspath(path)
    daemon = os.path.join(root, "daemon")
    if not os.path.isfile(os.path.join(daemon, SERVER_NAME)):
        raise DeployError("checkout is missing daemon/%s" % SERVER_NAME)
    if not os.path.isfile(os.path.join(daemon, REQUIREMENTS_NAME)):
        raise DeployError("checkout is missing daemon/%s" % REQUIREMENTS_NAME)
    if not os.path.isfile(os.path.join(daemon, PLIST_NAME)):
        raise DeployError("checkout is missing daemon/%s" % PLIST_NAME)
    return root


def default_runtime(checkout):
    return os.path.join(checkout, "daemon", RUNTIME_NAME)


def default_venv(checkout):
    return os.path.join(checkout, "daemon", ".venv")


def default_interpreter(checkout):
    return os.path.join(default_venv(checkout), "bin", "python")


def default_server(checkout):
    return os.path.join(checkout, "daemon", SERVER_NAME)


def default_requirements(checkout):
    return os.path.join(checkout, "daemon", REQUIREMENTS_NAME)


def default_plist_template(checkout):
    return os.path.join(checkout, "daemon", PLIST_NAME)


def resolve_model(explicit):
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get("LLM_RERANK_MODEL")
    if env:
        return os.path.abspath(env)
    return ""


def find_python(explicit=None):
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("LLM_RERANK_PYTHON")
    if env:
        candidates.append(env)
    for name in ("python3.12", "python3.11", "python3.10", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    seen = set()
    for candidate in candidates:
        if candidate in seen or not candidate:
            continue
        seen.add(candidate)
        if not os.path.isfile(candidate) and shutil.which(candidate) is None:
            continue
        try:
            out = subprocess.check_output(
                [candidate, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                text=True,
            ).strip()
            major, minor = (int(part) for part in out.split("."))
        except (OSError, subprocess.CalledProcessError, ValueError):
            continue
        if (major, minor) >= MIN_PYTHON:
            return candidate
    raise DeployError(
        "need Python >= %d.%d for daemon/.venv (set LLM_RERANK_PYTHON)"
        % MIN_PYTHON
    )


def ensure_owner_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise DeployError("runtime path is not a directory: %s" % path)
    if info.st_uid != os.getuid():
        raise DeployError("runtime path is not owner-owned: %s" % path)
    os.chmod(path, 0o700)


def read_pid(pid_path):
    if not os.path.isfile(pid_path):
        return None
    try:
        with open(pid_path, encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _reap(pid):
    if not pid:
        return False
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    except OSError:
        return False
    return waited == pid


def pid_alive(pid):
    if not pid:
        return False
    if _reap(pid):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write_pid(pid_path, pid):
    tmp = pid_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("%d\n" % pid)
    os.replace(tmp, pid_path)


def paths_from_args(args):
    checkout = checkout_root(args.checkout)
    runtime = os.path.abspath(args.runtime_dir or default_runtime(checkout))
    interpreter = os.path.abspath(
        args.interpreter or default_interpreter(checkout)
    )
    server = os.path.abspath(args.server or default_server(checkout))
    socket_path = os.path.abspath(
        args.socket or os.path.join(runtime, "llm-rerank.sock")
    )
    log_path = os.path.abspath(
        args.log or os.path.join(runtime, "llm-rerank.log")
    )
    log_err = os.path.abspath(
        getattr(args, "log_err", None)
        or os.path.join(runtime, "llm-rerank.err")
    )
    facts_root = os.path.abspath(
        args.facts_root or os.path.join(runtime, "facts")
    )
    model = resolve_model(getattr(args, "model", None))
    pid_path = os.path.abspath(
        getattr(args, "pid_file", None) or os.path.join(runtime, "daemon.pid")
    )
    return {
        "checkout": checkout,
        "runtime": runtime,
        "interpreter": interpreter,
        "server": server,
        "socket": socket_path,
        "log": log_path,
        "log_err": log_err,
        "facts_root": facts_root,
        "model": model,
        "pid_file": pid_path,
        "venv": default_venv(checkout),
        "requirements": default_requirements(checkout),
        "plist_template": default_plist_template(checkout),
    }


def render_plist(template_path, values):
    with open(template_path, encoding="utf-8") as handle:
        text = handle.read()
    mapping = {
        "__CHECKOUT__": values["checkout"],
        "__INTERPRETER__": values["interpreter"],
        "__SERVER__": values["server"],
        "__MODEL__": values["model"],
        "__SOCKET__": values["socket"],
        "__LOG__": values["log"],
        "__LOG_ERR__": values["log_err"],
        "__FACTS_ROOT__": values["facts_root"],
    }
    rendered = text
    for token, value in mapping.items():
        if token not in rendered:
            raise DeployError("plist template missing %s" % token)
        rendered = rendered.replace(token, value)
    leftover = PLACEHOLDER.findall(rendered)
    if leftover:
        raise DeployError("unresolved plist placeholders: %s" % leftover)
    if "/Users/habit" in rendered:
        raise DeployError("rendered plist still contains /Users/habit")
    return rendered


def cmd_render_plist(args):
    paths = paths_from_args(args)
    if not paths["model"]:
        raise DeployError(
            "model path is required to render the launchd template "
            "(--model or LLM_RERANK_MODEL)"
        )
    text = render_plist(paths["plist_template"], paths)
    output = args.output
    if output:
        parent = os.path.dirname(os.path.abspath(output))
        if parent:
            ensure_owner_dir(parent)
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


def cmd_install(args):
    checkout = checkout_root(args.checkout)
    python = find_python(args.python)
    venv = os.path.abspath(args.venv or default_venv(checkout))
    requirements = os.path.abspath(
        args.requirements or default_requirements(checkout)
    )
    if not os.path.isfile(requirements):
        raise DeployError("missing requirements file: %s" % requirements)
    parent = os.path.dirname(venv)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not os.path.isfile(os.path.join(venv, "bin", "python")):
        subprocess.check_call([python, "-m", "venv", venv])
    interpreter = os.path.join(venv, "bin", "python")
    subprocess.check_call(
        [interpreter, "-m", "pip", "install", "--upgrade", "pip"]
    )
    install_cmd = [
        interpreter, "-m", "pip", "install",
        "--disable-pip-version-check",
        "-r", requirements,
    ]
    subprocess.check_call(install_cmd)
    print("installed %s into %s" % (requirements, venv))
    return 0


def _prepare_runtime(paths, health_only):
    ensure_owner_dir(paths["runtime"])
    ensure_owner_dir(os.path.dirname(paths["socket"]))
    ensure_owner_dir(os.path.dirname(paths["log"]))
    ensure_owner_dir(paths["facts_root"])
    model = paths["model"]
    if health_only and not model:
        model = os.path.join(paths["runtime"], STANDIN_MODEL_NAME)
        os.makedirs(model, exist_ok=True)
        marker = os.path.join(model, "README")
        if not os.path.isfile(marker):
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(
                    "Health-only stand-in. Not a real mlx-lm model.\n"
                    "Set --model or LLM_RERANK_MODEL to a local model "
                    "directory for scoring. Weights are not shipped.\n"
                )
        paths["model"] = model
    elif not model:
        raise DeployError(
            "scoring start needs --model or LLM_RERANK_MODEL; "
            "pass --health-only for the model-free handshake"
        )
    return paths


def cmd_start(args):
    paths = _prepare_runtime(paths_from_args(args), args.health_only)
    if not os.path.isfile(paths["interpreter"]):
        raise DeployError(
            "interpreter not found: %s (run install or pass --interpreter)"
            % paths["interpreter"]
        )
    if not os.path.isfile(paths["server"]):
        raise DeployError("missing server: %s" % paths["server"])
    existing = read_pid(paths["pid_file"])
    if pid_alive(existing):
        raise DeployError("daemon already running as pid %d" % existing)
    command = [
        paths["interpreter"],
        paths["server"],
        "--serve",
        "--socket", paths["socket"],
        "--model", paths["model"],
        "--facts-root", paths["facts_root"],
    ]
    if args.health_only:
        command.append("--health-only")
    pid = _spawn_daemon(command, paths["checkout"], paths["log"], paths["log_err"])
    write_pid(paths["pid_file"], pid)
    deadline = time.time() + args.timeout
    last_error = "timeout waiting for READY"
    while time.time() < deadline:
        if not pid_alive(pid):
            raise DeployError("daemon exited; see %s" % paths["log_err"])
        try:
            with open(paths["log"], "rb") as handle:
                if b"READY " in handle.read():
                    print("started pid %d socket %s" % (pid, paths["socket"]))
                    return 0
        except OSError as error:
            last_error = str(error)
        time.sleep(0.05)
    _stop_pid(pid, timeout=2)
    raise DeployError(last_error)


def _spawn_daemon(command, cwd, stdout_path, stderr_path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    log_out = os.open(stdout_path, flags, 0o600)
    log_err = os.open(stderr_path, flags, 0o600)
    try:
        pid = os.fork()
    except OSError:
        os.close(log_out)
        os.close(log_err)
        raise
    if pid == 0:
        try:
            os.setsid()
            os.dup2(log_out, 1)
            os.dup2(log_err, 2)
            os.close(log_out)
            if log_err != log_out:
                os.close(log_err)
            os.chdir(cwd)
            os.execv(command[0], command)
        except Exception:
            os._exit(127)
    os.close(log_out)
    os.close(log_err)
    return pid


def _stop_pid(pid, timeout):
    if not pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        _reap(pid)
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        _reap(pid)
        return
    deadline = time.time() + 2
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.05)
    raise DeployError("pid %d did not exit" % pid)


def send_health(socket_path, timeout=2.0):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(socket_path)
        conn.sendall(
            (json.dumps(HEALTH_REQUEST, ensure_ascii=False) + "\n").encode("utf-8")
        )
        conn.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            piece = conn.recv(65536)
            if not piece:
                break
            chunks.append(piece)
    finally:
        conn.close()
    if not chunks:
        raise DeployError("empty health response")
    return json.loads(b"".join(chunks).decode("utf-8"))


def cmd_health(args):
    paths = paths_from_args(args)
    response = send_health(paths["socket"], timeout=args.timeout)
    json.dump(response, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if response.get("kind") != "health" or "health" not in response:
        raise DeployError("response is not a health handshake")
    return 0


def cmd_stop(args):
    paths = paths_from_args(args)
    pid = read_pid(paths["pid_file"])
    _stop_pid(pid, timeout=args.timeout)
    if os.path.lexists(paths["socket"]):
        try:
            os.unlink(paths["socket"])
        except OSError:
            pass
    if os.path.isfile(paths["pid_file"]):
        os.unlink(paths["pid_file"])
    print("stopped")
    return 0


def _copy_checkout(source, dest):
    daemon_src = os.path.join(source, "daemon")
    daemon_dst = os.path.join(dest, "daemon")

    def ignore(_directory, names):
        skipped = set()
        for name in names:
            if name in (".venv", RUNTIME_NAME, "__pycache__", ".git"):
                skipped.add(name)
            elif name.endswith(".pyc"):
                skipped.add(name)
        return skipped

    shutil.copytree(daemon_src, daemon_dst, ignore=ignore)


def isolated_verify(source_checkout, work_dir=None, install_pins=True,
                    python=None, timeout=15.0):
    source = checkout_root(source_checkout)
    owns_dir = work_dir is None
    root = work_dir or tempfile.mkdtemp(prefix="llm131-")
    try:
        ensure_owner_dir(root)
        checkout = os.path.join(root, "checkout")
        if os.path.exists(checkout):
            shutil.rmtree(checkout)
        os.mkdir(checkout)
        _copy_checkout(source, checkout)
        runtime = os.path.join(root, "run")
        ensure_owner_dir(runtime)
        ns = argparse.Namespace(
            checkout=checkout,
            runtime_dir=runtime,
            interpreter=None,
            server=None,
            socket=os.path.join(runtime, "llm-rerank.sock"),
            log=os.path.join(runtime, "llm-rerank.log"),
            log_err=os.path.join(runtime, "llm-rerank.err"),
            facts_root=os.path.join(runtime, "facts"),
            model=None,
            pid_file=os.path.join(runtime, "daemon.pid"),
            python=python,
            venv=os.path.join(checkout, "daemon", ".venv"),
            requirements=os.path.join(checkout, "daemon", REQUIREMENTS_NAME),
            health_only=True,
            timeout=timeout,
            output=os.path.join(runtime, PLIST_NAME),
        )
        if install_pins:
            cmd_install(ns)
            ns.interpreter = os.path.join(ns.venv, "bin", "python")
        else:
            ns.interpreter = sys.executable
            ns.venv = None
        cmd_start(ns)
        try:
            health = send_health(ns.socket, timeout=timeout)
            if health.get("kind") != "health":
                raise DeployError("isolated health failed: %r" % health)
            if health.get("health", {}).get("model_loaded"):
                raise DeployError("health-only start loaded a model")
            ns.model = os.path.join(runtime, STANDIN_MODEL_NAME)
            cmd_render_plist(ns)
            with open(ns.output, encoding="utf-8") as handle:
                rendered = handle.read()
            if "/Users/habit" in rendered:
                raise DeployError("rendered plist contains /Users/habit")
            for token in (
                ns.checkout, ns.interpreter, ns.model, ns.log, ns.socket
            ):
                if token not in rendered:
                    raise DeployError("rendered plist missing path %s" % token)
        finally:
            cmd_stop(ns)
        return {
            "checkout": checkout,
            "runtime": runtime,
            "socket": ns.socket,
            "interpreter": ns.interpreter,
            "model": ns.model,
            "plist": ns.output,
            "installed_pins": bool(install_pins),
            "health_kind": health["kind"],
            "model_loaded": health["health"]["model_loaded"],
        }
    finally:
        if owns_dir:
            shutil.rmtree(root, ignore_errors=True)


def cmd_verify(args):
    record = isolated_verify(
        args.checkout,
        work_dir=args.work_dir,
        install_pins=not args.skip_install,
        python=args.python,
        timeout=args.timeout,
    )
    json.dump(record, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkout",
        default=DEFAULT_CHECKOUT,
        help="plugin checkout root (directory that contains daemon/)",
    )
    parser.add_argument("--runtime-dir", help="owner-only runtime directory")
    parser.add_argument("--interpreter")
    parser.add_argument("--server")
    parser.add_argument("--socket")
    parser.add_argument("--model")
    parser.add_argument("--log")
    parser.add_argument("--log-err")
    parser.add_argument("--facts-root")
    parser.add_argument("--pid-file")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="create daemon/.venv from pins")
    install.add_argument("--python", help="base interpreter for the venv")
    install.add_argument("--venv")
    install.add_argument("--requirements")
    install.set_defaults(func=cmd_install)

    start = sub.add_parser("start", help="start the daemon")
    start.add_argument(
        "--health-only",
        action="store_true",
        help="do not import MLX or load a model",
    )
    start.add_argument("--timeout", type=float, default=15.0)
    start.set_defaults(func=cmd_start)

    health = sub.add_parser("health", help="query the health handshake")
    health.add_argument("--timeout", type=float, default=2.0)
    health.set_defaults(func=cmd_health)

    stop = sub.add_parser("stop", help="stop the daemon started by this tool")
    stop.add_argument("--timeout", type=float, default=5.0)
    stop.set_defaults(func=cmd_stop)

    render = sub.add_parser(
        "render-plist",
        help="render the launchd template with explicit paths",
    )
    render.add_argument("--output")
    render.set_defaults(func=cmd_render_plist)

    verify = sub.add_parser(
        "verify",
        help="isolated temp checkout: install/start/health/stop",
    )
    verify.add_argument("--work-dir")
    verify.add_argument("--python")
    verify.add_argument("--timeout", type=float, default=30.0)
    verify.add_argument(
        "--skip-install",
        action="store_true",
        help="use this interpreter for a health-only start (no pin install)",
    )
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DeployError as error:
        return _die(str(error))


if __name__ == "__main__":
    sys.exit(main())
