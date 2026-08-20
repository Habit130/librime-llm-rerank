#!/usr/bin/env python3
"""#71 capacity-benchmark driver: orchestrates the full measurement battery.

Runs each scenario against a fresh server instance + fixture copy so the
delta checkpoint and the facts store are pristine per scenario (SCN-71-2
quiet-window discipline: every latency window is exclusive; the window
start/end timestamps and loadavg are recorded per scenario).

Scenarios:
  S1+S3  ordinary-query latency + replay on the freq-distribution fixture
  H1+H3  ordinary-query latency + bounded replay on the single-hot-key
         fixture (10k replay is infeasible at ~7.5 s/query; the driver
         measures a bounded sample and records the extrapolation)
  S2     first query after a fresh commit (catch-up gate) on a separate
         fixture copy (the appends must not leak into S1/S3)
  S4     replay while a background staging rebuild runs concurrently

Each scenario writes its own JSON record; the driver aggregates them into
one report section.  Nothing here writes the live facts root, touches
~/Library/Rime, or restarts the live daemon.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAEMON = os.path.join(_REPO, "daemon")
_PYTHON = os.environ.get(
    "LLM_RERANK_PYTHON",
    "/Users/habit/Developer/librime-llm-rerank/daemon/.venv/bin/python")
BENCH_DAEMON = os.path.join(_DAEMON, "bench_evidence_daemon.py")
CLIENT = os.path.join(_DAEMON, "bench_evidence_client.py")
FIXTURES = os.path.join(_DAEMON, "..", "eval", "100k_fixtures.py")
MODEL = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
REPR_ID = "seed-fixture-v1:1024"
SEED = 20260817
DIM = 1024


def env_snapshot():
    return {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
    }


def run(cmd, cwd=None, timeout=1800, env=None):
    """Run a command, returning (returncode, stdout+stderr)."""
    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = _DAEMON
    if env:
        full_env.update(env)
    proc = subprocess.run(cmd, cwd=cwd, env=full_env,
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def start_server(sock_dir, facts_root, derived_root, seed, repr_id,
                 log_path, staging_config=None, timeout_s=90, backend="exact"):
    os.makedirs(sock_dir, mode=0o700, exist_ok=True)
    for name in ("evidence.sock",):
        path = os.path.join(sock_dir, name)
        if os.path.exists(path):
            os.unlink(path)
    cmd = [_PYTHON, BENCH_DAEMON,
           "--facts-root", facts_root,
           "--derived-root", derived_root,
           "--socket", os.path.join(sock_dir, "evidence.sock"),
           "--representation-id", repr_id,
           "--seed", str(seed),
           "--dimension", str(DIM),
           "--backend", backend]
    if staging_config:
        cmd += ["--staging-config", staging_config]
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd, cwd=_REPO, env=dict(os.environ, PYTHONPATH=_DAEMON),
        stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + timeout_s
    ready = False
    while time.time() < deadline:
        if os.path.exists(os.path.join(sock_dir, "evidence.sock")):
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    if not ready:
        raise RuntimeError("bench daemon did not become ready: %s"
                           % open(log_path).read()[-2000:])
    # Wait for the delta machine's startup catch-up to finish: probe with
    # one evidence request until it returns (the machine is caught up when
    # the first request succeeds; a busy startup may take seconds at 100k
    # events).
    probe_ready = False
    probe_deadline = time.time() + timeout_s
    while time.time() < probe_deadline:
        try:
            import socket as _socket
            probe = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            probe.settimeout(5)
            probe.connect(os.path.join(sock_dir, "evidence.sock"))
            probe.sendall((json.dumps({
                "version": 2, "kind": "evidence",
                "request_id": "probe-ready", "plan_identity": "probe",
                "schema_id": "luna_pinyin", "category": "word",
                "canonical_segment_input": "probe-key",
                "preceding_text": "a" * 64,
                "candidates": ["w0", "w1", "w2"],
                "config_identity": "probe", "fact_high_water": None,
            }) + "\n").encode("utf-8"))
            probe.shutdown(_socket.SHUT_WR)
            buf = b""
            while True:
                chunk = probe.recv(65536)
                if not chunk:
                    break
                buf += chunk
            probe.close()
            if b'"status": "ok"' in buf or b'"error"' in buf:
                probe_ready = True
                break
        except Exception:
            pass
        if proc.poll() is not None:
            break
        time.sleep(1)
    if not probe_ready:
        raise RuntimeError("bench daemon never served: %s"
                           % open(log_path).read()[-2000:])
    return proc, log


def stop_server(proc, log):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    log.close()


def sample_peak_rss_kb(proc, tracker):
    """Sample the daemon's current RSS and fold it into a peak tracker."""
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(proc.pid)],
                             capture_output=True, text=True, timeout=10)
        rss_kb = int(out.stdout.strip())
    except Exception:  # noqa: BLE001 - best effort; never fail the window
        return tracker
    return max(tracker, rss_kb)


def record_peak_rss(record_path, rss_kb):
    """Attach the window's peak RSS to an existing measurement record."""
    try:
        with open(record_path, encoding="utf-8") as handle:
            record = json.load(handle)
    except Exception:  # noqa: BLE001 - best effort
        return
    record["peak_rss_kib"] = rss_kb
    with open(record_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)


def _active_generation_id(derived_root):
    sys.path.insert(0, _DAEMON)
    from publish import read_active_manifest
    manifest, _ = read_active_manifest(derived_root)
    return manifest["generation_id"]


def _build_generation_script(derived_root, facts_root, repr_id, seed,
                             backend="exact"):
    return ("import sys; sys.path.insert(0, 'daemon')\n"
            "from seed_vectors import SeedVectorProvider\n"
            "from generation import build_generation\n"
            "from publish import write_active_manifest, "
            "_compose_active_manifest, _read_fact_schema_version, "
            "DELTA_FILENAME\n"
            "import shutil\n"
            "shutil.rmtree(%r, ignore_errors=True)\n"
            "p = SeedVectorProvider(%r, %d, %d)\n"
            "g = build_generation(%r, p, %r, retrieval_backend=%r)\n"
            "m = _compose_active_manifest(g, 'delta/%%s/%%s' %% "
            "(g.generation_id, DELTA_FILENAME), "
            "_read_fact_schema_version(%r))\n"
            "write_active_manifest(%r, m)\n"
            "g.close()\n" % (
                derived_root, repr_id, seed, DIM, facts_root, derived_root,
                backend, facts_root, derived_root))


def _run_client(sock_dir, kind, facts_root, replay_count,
                client_deadline_ms, record_path, cwd, backend="exact"):
    full_env = dict(os.environ)
    full_env["LLM_RERANK_BENCH_BACKEND"] = backend
    return run([
        _PYTHON, CLIENT, "--socket",
        os.path.join(sock_dir, "evidence.sock"),
        "--kind", kind, "--seed", str(SEED), "--dimension", str(DIM),
        "--representation-id", REPR_ID,
        "--replay-count", str(replay_count),
        "--client-deadline-ms", str(client_deadline_ms),
        "--output", record_path,
        "--facts-root", facts_root,
    ], cwd=cwd, env=full_env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--backend", default="exact",
                        choices=("exact", "accelerate-cblas-sgemv",
                                 "mlx-exact-matmul"),
                        help="exact retrieval backend (default: the #71 "
                             "python oracle; #72 vecLib; #73 MLX)")
    parser.add_argument("--replay-count", type=int, default=10000)
    parser.add_argument("--hotkey-replay-count", type=int, default=30)
    parser.add_argument("--client-deadline-ms", type=float, default=200.0)
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse existing fixtures/derived roots")
    args = parser.parse_args()
    backend = args.backend

    work = args.work_root
    os.makedirs(work, mode=0o700, exist_ok=True)
    records = os.path.join(work, "records")
    os.makedirs(records, mode=0o700, exist_ok=True)

    # -- 1. build the fixtures once (deterministic) ----------------------
    fixtures = os.path.join(work, "fixtures")
    if not args.skip_build or not os.path.exists(
            os.path.join(fixtures, "freq", "facts.sqlite3")):
        rc, out = run([_PYTHON, FIXTURES, "--output", fixtures,
                       "--seed", str(SEED)], cwd=os.path.dirname(FIXTURES))
        if rc != 0:
            print(out[-2000:])
            return 1
    with open(os.path.join(fixtures, "100k-fixtures-summary.json"),
              encoding="utf-8") as handle:
        fixture_summary = json.load(handle)

    # -- 2. build pristine freq generation -------------------------------
    derived_freq = os.path.join(work, "derived-freq")
    if not args.skip_build or not os.path.exists(
            os.path.join(derived_freq, "generations")):
        with open(os.path.join(work, "build_gen.py"), "w") as handle:
            handle.write(_build_generation_script(
                derived_freq, os.path.join(fixtures, "freq"),
                REPR_ID, SEED, backend))
        rc, out = run([_PYTHON, os.path.join(work, "build_gen.py")],
                      cwd=_REPO, timeout=1200)
        if rc != 0:
            print(out[-2000:])
            return 1

    # -- 3. S1+S3 freq ----------------------------------------------------
    print("[S1+S3] freq window %s" % env_snapshot(), flush=True)
    sock_dir = os.path.join(work, "sock-freq")
    proc, log = start_server(
        sock_dir, os.path.join(fixtures, "freq"), derived_freq,
        SEED, REPR_ID, os.path.join(records, "freq-server.log"),
        backend=backend)
    time.sleep(5)
    record_s13 = os.path.join(records, "freq-s1s3.json")
    rc, out = _run_client(
        sock_dir, "freq", os.path.join(fixtures, "freq"),
        args.replay_count, args.client_deadline_ms, record_s13, _REPO,
        backend=backend)
    peak = sample_peak_rss_kb(proc, 0)
    record_peak_rss(record_s13, peak)
    stop_server(proc, log)
    if rc != 0:
        print(out[-3000:])
        return 1
    for line in out.strip().splitlines()[-4:]:
        print(line)

    # -- 4. S2 (first query after a commit) on a separate copy -----------
    print("[S2] commit window %s" % env_snapshot(), flush=True)
    s2_facts = os.path.join(work, "fixtures-s2")
    shutil.rmtree(s2_facts, ignore_errors=True)
    shutil.copytree(os.path.join(fixtures, "freq"), s2_facts)
    derived_s2 = os.path.join(work, "derived-s2")
    shutil.rmtree(derived_s2, ignore_errors=True)
    shutil.copytree(derived_freq, derived_s2)
    sock_dir = os.path.join(work, "sock-s2")
    proc, log = start_server(
        sock_dir, s2_facts, derived_s2, SEED, REPR_ID,
        os.path.join(records, "s2-server.log"), backend=backend)
    time.sleep(5)
    record_s2 = os.path.join(records, "freq-s2.json")
    rc, out = _run_client(
        sock_dir, "freq", s2_facts, 50, args.client_deadline_ms,
        record_s2, _REPO, backend=backend)
    peak = sample_peak_rss_kb(proc, 0)
    record_peak_rss(record_s2, peak)
    stop_server(proc, log)
    if rc != 0:
        print(out[-3000:])
        return 1
    for line in out.strip().splitlines()[-4:]:
        print(line)

    # -- 5. hotkey generation + S1/S3 (bounded replay) -------------------
    print("[H1+H3] hotkey window %s" % env_snapshot(), flush=True)
    derived_hotkey = os.path.join(work, "derived-hotkey")
    if not args.skip_build or not os.path.exists(
            os.path.join(derived_hotkey, "generations")):
        with open(os.path.join(work, "build_gen_hotkey.py"), "w") as handle:
            handle.write(_build_generation_script(
                derived_hotkey, os.path.join(fixtures, "hotkey"),
                REPR_ID, SEED, backend))
        rc, out = run([_PYTHON, os.path.join(work, "build_gen_hotkey.py")],
                      cwd=_REPO, timeout=1200)
        if rc != 0:
            print(out[-2000:])
            return 1
    sock_dir = os.path.join(work, "sock-hotkey")
    proc, log = start_server(
        sock_dir, os.path.join(fixtures, "hotkey"), derived_hotkey,
        SEED, REPR_ID, os.path.join(records, "hotkey-server.log"),
        backend=backend)
    time.sleep(5)
    record_h = os.path.join(records, "hotkey-s1s3.json")
    rc, out = _run_client(
        sock_dir, "hotkey", os.path.join(fixtures, "hotkey"),
        args.hotkey_replay_count, args.client_deadline_ms, record_h, _REPO,
        backend=backend)
    peak = sample_peak_rss_kb(proc, 0)
    record_peak_rss(record_h, peak)
    stop_server(proc, log)
    if rc != 0:
        print(out[-3000:])
        return 1
    for line in out.strip().splitlines()[-4:]:
        print(line)

    # -- 6. S4 background-rebuild concurrency ----------------------------
    print("[S4] rebuild concurrency window %s" % env_snapshot(), flush=True)
    s4_facts = os.path.join(work, "fixtures-s4")
    shutil.rmtree(s4_facts, ignore_errors=True)
    shutil.copytree(os.path.join(fixtures, "freq"), s4_facts)
    derived_s4 = os.path.join(work, "derived-s4")
    shutil.rmtree(derived_s4, ignore_errors=True)
    shutil.copytree(derived_freq, derived_s4)
    staging_config = os.path.join(work, "s4-staging-config.json")
    with open(staging_config, "w", encoding="utf-8") as handle:
        json.dump({
            "provider_kind": "seed_vectors",
            "representation_id": REPR_ID,
            "seed": SEED,
            "vector_dimension": DIM,
            "desired_representation_id": "seed-fixture-v2:1024",
            "desired_seed": 20260818,
            "staging_poll_interval_ms": 500,
        }, handle, indent=2)
    sock_dir = os.path.join(work, "sock-s4")
    proc, log = start_server(
        sock_dir, s4_facts, derived_s4, SEED, REPR_ID,
        os.path.join(records, "s4-server.log"),
        staging_config=staging_config, timeout_s=90, backend=backend)
    time.sleep(5)
    staging_dir = os.path.join(derived_s4, "staging")
    for _ in range(120):
        if os.path.isdir(staging_dir) and os.listdir(staging_dir):
            break
        time.sleep(1)
    record_s4 = os.path.join(records, "freq-s4.json")
    rc, out = _run_client(
        sock_dir, "freq", s4_facts, args.replay_count,
        args.client_deadline_ms, record_s4, _REPO, backend=backend)
    peak = sample_peak_rss_kb(proc, 0)
    record_peak_rss(record_s4, peak)
    stop_server(proc, log)
    if rc != 0:
        print(out[-3000:])
        return 1
    for line in out.strip().splitlines()[-4:]:
        print(line)

    # -- aggregate --------------------------------------------------------
    contract = "AC-72-v1" if backend == "accelerate-cblas-sgemv" else (
        "AC-73-v1" if backend == "mlx-exact-matmul" else "AC-71-v1")
    aggregate = {
        "contract": contract,
        "retrieval_backend": backend,
        "fixtures": fixture_summary,
        "records": {
            "freq_s1s3": record_s13,
            "freq_s2": record_s2,
            "hotkey_s1s3": record_h,
            "freq_s4": record_s4,
        },
        "done": env_snapshot(),
    }
    agg_path = os.path.join(records, "aggregate.json")
    with open(agg_path, "w", encoding="utf-8") as handle:
        json.dump(aggregate, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    print("aggregate: %s" % agg_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
