#!/usr/bin/env python3
"""AC-78 daemon IPC helpers (EvidenceService unix socket)."""

import json
import os
import shutil
import socket
import statistics
import subprocess
import tempfile
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_ROOT)
_DAEMON = os.path.join(_REPO, "daemon")
DAEMON_SCRIPT = os.path.join(_ROOT, "ac78_evidence_daemon.py")


def rss_mib(pid):
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip()) / 1024.0
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def percentiles(values):
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    n = len(ordered)

    def at(p):
        if n == 1:
            return float(ordered[0])
        rank = (n - 1) * (p / 100.0)
        low = int(rank)
        high = min(n - 1, low + 1)
        weight = rank - low
        return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)

    return {
        "n": n,
        "p50": at(50),
        "p95": at(95),
        "p99": at(99),
        "max": float(ordered[-1]),
        "mean": statistics.mean(ordered),
    }


def send(sock_path, payload, timeout_s=30.0):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    started = time.perf_counter()
    try:
        sock.connect(sock_path)
        sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n")
                     .encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        buf = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        return (time.perf_counter() - started) * 1000.0, json.loads(buf)
    except socket.timeout:
        return timeout_s * 1000.0, {"error": {"code": "transport_timeout"}}
    finally:
        sock.close()


def fact_high_water(facts_root):
    import sqlite3
    conn = sqlite3.connect(os.path.join(facts_root, "facts.sqlite3"))
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()
    return {
        "store_epoch": meta["store_epoch"],
        "hlc_physical_ms": int(meta["hlc_physical_ms"]),
        "hlc_logical": int(meta["hlc_logical"]),
    }


def append_commit(facts_root, canonical_input, physical_ms, logical, seq,
                  preceding="a" * 64, selection="w0"):
    import sqlite3
    conn = sqlite3.connect(os.path.join(facts_root, "facts.sqlite3"))
    conn.execute("PRAGMA journal_mode=WAL;")
    commit_id = "ac78-commit-%d" % seq
    event_id = "ac78-ev-%d" % seq
    conn.execute(
        "INSERT OR REPLACE INTO commits(commit_id, utc_committed_at_ms)"
        " VALUES(?, ?)", (commit_id, physical_ms))
    conn.execute(
        "INSERT OR REPLACE INTO selection_events(event_id, commit_id,"
        " event_format_version, schema_id, canonical_segment_input,"
        " span_start, span_end, category, preceding_text,"
        " competition_complete, final_selection_text,"
        " confirmation_source, trigger_keycode, display_rank,"
        " display_page, session_id, session_seq, hlc_physical_ms,"
        " hlc_logical, utc_confirmed_at_ms, utc_committed_at_ms)"
        " VALUES(?,?,1,'luna_pinyin',?,0,4,'word',?,1,?,"
        " 'explicit_current',NULL,1,1,'ac78',?,?,?,?,?)",
        (event_id, commit_id, canonical_input, preceding, selection, seq,
         physical_ms, logical, physical_ms, physical_ms))
    for merge_order, text in enumerate(("w0", "w1", "w2")):
        conn.execute(
            "INSERT OR REPLACE INTO selection_candidates"
            "(event_id, merge_order, text) VALUES(?,?,?)",
            (event_id, merge_order, text))
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'hlc_physical_ms';",
        (str(physical_ms),))
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'hlc_logical';",
        (str(logical),))
    conn.commit()
    conn.close()
    return event_id


def start_daemon(python, config_path, sock_dir, log_path, status_path,
                 rebuild_concurrent=False, timeout_s=180):
    del sock_dir
    short_dir = tempfile.mkdtemp(prefix="ac78s-", dir="/tmp")
    os.chmod(short_dir, 0o700)
    sock_path = os.path.join(short_dir, "e.sock")
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    cmd = [str(python), DAEMON_SCRIPT, "--config", str(config_path),
           "--socket", sock_path, "--status-file", str(status_path)]
    if rebuild_concurrent:
        cmd.append("--rebuild-concurrent")
    log = open(log_path, "w", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = _DAEMON + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        cmd, cwd=_REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    proc._ac78_sock_dir = short_dir
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if os.path.exists(sock_path) and os.path.isfile(status_path):
            try:
                with open(status_path, encoding="utf-8") as handle:
                    status = json.load(handle)
                if status.get("ann_backend") == "usearch-hnsw":
                    return proc, log, sock_path, status
            except (OSError, ValueError):
                pass
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    snippet = ""
    try:
        log.flush()
        snippet = open(log_path, encoding="utf-8").read()[-4000:]
    except OSError:
        pass
    stop_daemon(proc, log)
    raise RuntimeError("ac78 daemon did not become ready: %s" % snippet)


def start_rebuild_process(python, derived_root, generation_id, log_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = _DAEMON + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import os, sys\n"
        "sys.path.insert(0, %r)\n"
        "from generation import open_generation\n"
        "from ann import rebuild_ann_from_generation\n"
        "from publish import read_active_manifest\n"
        "derived = %r\n"
        "manifest, reason = read_active_manifest(derived)\n"
        "if manifest is None:\n"
        "    raise SystemExit('no active manifest: %%s' %% reason)\n"
        "gid = manifest['generation_id']\n"
        "generation = open_generation(os.path.join(derived, 'generations', gid))\n"
        "try:\n"
        "    from ann import load_ann_sidecar, sidecar_dir\n"
        "    _index, meta = load_ann_sidecar(sidecar_dir(derived, gid),\n"
        "        expected_generation_id=gid)\n"
        "    staging = os.path.join(derived, 'staging')\n"
        "    os.makedirs(staging, mode=0o700, exist_ok=True)\n"
        "    rebuild_ann_from_generation(\n"
        "        generation, staging, 'ann-rebuild-' + gid,\n"
        "        dict(meta.get('build_params') or {}),\n"
        "        meta.get('index_fingerprint'))\n"
        "    print('REBUILD_DONE', flush=True)\n"
        "finally:\n"
        "    generation.close()\n"
    ) % (_DAEMON, str(derived_root))
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(python), "-c", code], cwd=_REPO, env=env,
        stdout=log, stderr=subprocess.STDOUT)
    return proc, log


def stop_daemon(proc, log):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if log is not None:
        log.close()
    sock_dir = getattr(proc, "_ac78_sock_dir", None) if proc is not None else None
    if sock_dir:
        shutil.rmtree(sock_dir, ignore_errors=True)
