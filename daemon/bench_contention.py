#!/usr/bin/env python3
"""#73 contention and RSS measurement driver (SCN-73-5, RISK-73-4).

The MLX exact retrieval backend runs in the SAME daemon process as the
mean-token LM candidate scorer (one model, one process -- SCN-73-5, no
second resident model).  This driver measures what that sharing costs:

  R  retrieval-only   : evidence requests for the 100k hot key, MLX warm
  S  scoring-only     : mean-token LM scoring requests (the existing
                        candidate-scoring path), model hot
  C  concurrent       : the SAME two request streams interleaved
                        (exact retrieval overlapping candidate scoring)
  M  memory           : steady + peak RSS of the shared daemon, and the
                        LM-only daemon as the reference baseline

Windows are exclusive and quiet (UTC + loadavg recorded per window).  The
daemon is the REAL production server (daemon/server.py) with an evidence
config -- not the bench evidence daemon -- so the model, the scorer and the
MLX engine genuinely share one process.  Nothing touches live facts or
~/Library/Rime.
"""

import argparse
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAEMON = os.path.join(_REPO, "daemon")
_PYTHON = os.environ.get(
    "LLM_RERANK_PYTHON",
    "/Users/habit/Developer/librime-llm-rerank/daemon/.venv/bin/python")
SERVER = os.path.join(_DAEMON, "server.py")
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


def rss_kib(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip())
    except Exception:  # noqa: BLE001 - best effort
        return None


def send_json(sock_path, payload, timeout_s=120.0):
    """One framed request/response round trip; returns (ms, response)."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    t0 = time.perf_counter()
    try:
        s.connect(sock_path)
        s.sendall((json.dumps(payload, ensure_ascii=False) + "\n")
                  .encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return (time.perf_counter() - t0) * 1000.0, json.loads(buf)
    except socket.timeout:
        return timeout_s * 1000.0, {"error": {"code": "transport_timeout"}}
    finally:
        s.close()


def percentiles(values):
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "p50": ordered[int(n * 0.50)],
        "p95": ordered[int(n * 0.95)],
        "p99": ordered[int(n * 0.99)],
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
    }


def evidence_payload(request_id, config_identity, fact_high_water):
    from evidence import make_evidence_request
    return make_evidence_request(
        schema_id="luna_pinyin", category="word",
        canonical_segment_input="hotkey",
        preceding_text="a" * 64, candidates=["w0", "w1", "w2"],
        config_identity=config_identity,
        fact_high_water=fact_high_water, request_id=request_id)


# The scoring path must tokenize cleanly (token attribution fails on
# synthetic ASCII suffixes); use realistic Chinese 上文 + candidates exactly
# like the production IMK path (self_test.py uses 发起/攻击/公鸡).
_SCORING_CONTEXT = "今天天气不错，我们一起去公园散步吧，然后"
_SCORING_CANDIDATES = ("攻击", "公鸡", "工程")


def scoring_payload(request_id):
    from server import make_request
    return make_request(request_id, "contention-plan-v1",
                        _SCORING_CONTEXT, list(_SCORING_CANDIDATES))


def wait_ready(sock_path, proc, timeout_s=180):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if os.path.exists(sock_path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect(sock_path)
                s.close()
                return True
            except OSError:
                pass
        if proc.poll() is not None:
            return False
        time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--events-per-window", type=int, default=60)
    parser.add_argument("--concurrent-rounds", type=int, default=40)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    work = args.work_root
    os.makedirs(work, mode=0o700, exist_ok=True)
    records = os.path.join(work, "records")
    os.makedirs(records, mode=0o700, exist_ok=True)

    # -- 1. fixture ------------------------------------------------------
    fixtures = os.path.join(work, "fixtures")
    if not args.skip_build or not os.path.exists(
            os.path.join(fixtures, "hotkey", "facts.sqlite3")):
        rc = subprocess.run([_PYTHON, FIXTURES, "--output", fixtures,
                             "--seed", str(SEED)],
                            cwd=os.path.dirname(FIXTURES)).returncode
        if rc != 0:
            print("FAIL: fixture build", file=sys.stderr)
            return 1
    hotkey_facts = os.path.join(fixtures, "hotkey")

    # -- 2. build the hotkey MLX generation -------------------------------
    derived = os.path.join(work, "derived-hotkey")
    build_script = os.path.join(work, "build_gen.py")
    if not args.skip_build or not os.path.exists(
            os.path.join(derived, "generations")):
        with open(build_script, "w") as handle:
            handle.write(
                "import sys; sys.path.insert(0, 'daemon')\n"
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
                    derived, REPR_ID, SEED, DIM, hotkey_facts, derived,
                    "mlx-exact-matmul", hotkey_facts, derived))
        rc = subprocess.run([_PYTHON, build_script], cwd=_REPO).returncode
        if rc != 0:
            print("FAIL: generation build", file=sys.stderr)
            return 1

    # -- 3. read identity + config identity --------------------------------
    import sqlite3
    from evidence import (compose_config_identity, EVIDENCE_PROTOCOL_VERSION)
    from oracle import OracleParams
    conn = sqlite3.connect(os.path.join(hotkey_facts, "facts.sqlite3"))
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()
    fact_high_water = {
        "store_epoch": meta["store_epoch"],
        "hlc_physical_ms": int(meta["hlc_physical_ms"]),
        "hlc_logical": int(meta["hlc_logical"]),
    }
    params = OracleParams(tau=0.4, k_evidence=8, half_life=32.0,
                          saturation_k=2.0)
    config_identity = compose_config_identity(REPR_ID, params, 2.0)

    evidence_config = {
        "provider_kind": "seed_vectors",
        "representation_id": REPR_ID,
        "seed": SEED,
        "vector_dimension": DIM,
        "derived_root": derived,
        "generation_id": None,
        "retrieval_backend": "mlx-exact-matmul",
        "tau": 0.4,
        "k_evidence": 8,
        "half_life": 32.0,
        "saturation_k": 2.0,
        "gamma": 2.0,
        "catch_up_deadline_ms": 5000,
        "poll_interval_ms": 500,
    }
    from publish import read_active_manifest
    manifest, _reason = read_active_manifest(derived)
    evidence_config["generation_id"] = manifest["generation_id"]
    evidence_config["representation_id"] = manifest["representation_id"]

    cfg_path = os.path.join(work, "evidence-config.json")
    with open(cfg_path, "w") as handle:
        json.dump(evidence_config, handle)

    sock_dir = os.path.join(work, "sock")
    os.makedirs(sock_dir, mode=0o700, exist_ok=True)
    scoring_sock = os.path.join(sock_dir, "scoring.sock")
    control_sock = os.path.join(sock_dir, "control.sock")
    for path in (scoring_sock, control_sock):
        if os.path.exists(path):
            os.unlink(path)

    # -- 4. start the REAL daemon (model + MLX evidence, one process) ------
    log_path = os.path.join(records, "server.log")
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [_PYTHON, SERVER, "--socket", scoring_sock, "--model", MODEL,
         "--facts-root", hotkey_facts, "--control-socket", control_sock,
         "--evidence-config", cfg_path],
        cwd=_REPO, env=dict(os.environ, PYTHONPATH=_DAEMON),
        stdout=log, stderr=subprocess.STDOUT)
    if not wait_ready(scoring_sock, proc):
        print("FAIL: daemon not ready: %s"
              % open(log_path).read()[-3000:], file=sys.stderr)
        return 1

    # Warm the model + MLX engine before any window (model-warm discipline):
    # one scoring request (loads Qwen) and one evidence request (builds the
    # MLX matrix + norms).
    try:
        resp = send_json(scoring_sock, scoring_payload("warm-lm"))[1]
        if "scores" not in resp:
            print("FAIL: scoring warm-up: %s" % resp, file=sys.stderr)
            return 1
        resp = send_json(scoring_sock,
                         evidence_payload("warm-ev", config_identity,
                                          fact_high_water))[1]
        if resp.get("status") != "ok":
            print("FAIL: evidence warm-up: %s" % resp, file=sys.stderr)
            return 1
    except Exception as error:  # noqa: BLE001
        print("FAIL: warm-up: %s" % error, file=sys.stderr)
        return 1

    def run_window(kind, count):
        """One exclusive latency window; returns (latencies, faults)."""
        latencies = []
        faults = 0
        for i in range(count):
            if kind == "evidence":
                payload = evidence_payload("c-%d" % i, config_identity,
                                           fact_high_water)
            else:
                payload = scoring_payload("s-%d" % i)
            dt, resp = send_json(scoring_sock, payload)
            if "error" in resp or (kind == "evidence"
                                   and resp.get("status") != "ok"):
                faults += 1
            latencies.append(dt)
        return latencies, faults

    record = {
        "contract": "AC-73-v1",
        "scenario": "contention",
        "backend": "mlx-exact-matmul",
        "model": os.path.basename(os.path.normpath(MODEL)),
        "events_per_window": args.events_per_window,
        "concurrent_rounds": args.concurrent_rounds,
        "windows": {},
    }

    # R: retrieval-only (MLX exact, hot key).
    print("[R] retrieval-only %s" % env_snapshot(), flush=True)
    r_lat, r_faults = run_window("evidence", args.events_per_window)
    record["windows"]["retrieval_only"] = {
        "start": env_snapshot(), "latencies_ms": r_lat,
        "percentiles": percentiles(r_lat), "faults": r_faults}

    # S: scoring-only (mean-token LM).
    print("[S] scoring-only %s" % env_snapshot(), flush=True)
    s_lat, s_faults = run_window("scoring", args.events_per_window)
    record["windows"]["scoring_only"] = {
        "start": env_snapshot(), "latencies_ms": s_lat,
        "percentiles": percentiles(s_lat), "faults": s_faults}

    # C: concurrent (interleaved evidence + scoring).
    print("[C] concurrent %s" % env_snapshot(), flush=True)
    c_ev = []
    c_sc = []
    c_faults = 0
    for i in range(args.concurrent_rounds):
        dt, resp = send_json(scoring_sock,
                             evidence_payload("cc-ev-%d" % i,
                                              config_identity,
                                              fact_high_water))
        if "error" in resp or resp.get("status") != "ok":
            c_faults += 1
        c_ev.append(dt)
        dt, resp = send_json(scoring_sock, scoring_payload("cc-sc-%d" % i))
        if "error" in resp:
            c_faults += 1
        c_sc.append(dt)
    record["windows"]["concurrent"] = {
        "start": env_snapshot(),
        "evidence_latencies_ms": c_ev,
        "evidence_percentiles": percentiles(c_ev),
        "scoring_latencies_ms": c_sc,
        "scoring_percentiles": percentiles(c_sc),
        "faults": c_faults,
    }

    # M: memory (steady + peak RSS of the shared daemon).
    peak = 0
    samples = []
    for _ in range(20):
        value = rss_kib(proc.pid)
        if value is not None:
            samples.append(value)
            peak = max(peak, value)
        time.sleep(0.5)
    record["windows"]["memory"] = {
        "start": env_snapshot(),
        "shared_daemon_steady_rss_kib": (samples[-1] if samples else None),
        "shared_daemon_peak_rss_kib": peak,
        "note": ("the shared daemon holds the LM model weights AND the MLX "
                 "matrix copy in one process; the LM-only reference is the "
                 "scoring-only window's process footprint (same daemon, "
                 "model hot, no engine)"),
    }
    # Reference: LM-only RSS (model hot, engine never built) -- start a
    # second daemon with the SAME model but an evidence config that never
    # constructs the MLX engine (backend "exact").
    lm_only_cfg = dict(evidence_config)
    lm_only_cfg["retrieval_backend"] = "exact"
    lm_only_cfg_path = os.path.join(work, "evidence-config-lm-only.json")
    with open(lm_only_cfg_path, "w") as handle:
        json.dump(lm_only_cfg, handle)
    lm_sock = os.path.join(sock_dir, "lm-only.sock")
    lm_ctl = os.path.join(sock_dir, "lm-only-control.sock")
    if os.path.exists(lm_sock):
        os.unlink(lm_sock)
    lm_log = open(os.path.join(records, "lm-only-server.log"), "w",
                  encoding="utf-8")
    lm_proc = subprocess.Popen(
        [_PYTHON, SERVER, "--socket", lm_sock, "--model", MODEL,
         "--facts-root", hotkey_facts, "--control-socket", lm_ctl,
         "--evidence-config", lm_only_cfg_path],
        cwd=_REPO, env=dict(os.environ, PYTHONPATH=_DAEMON),
        stdout=lm_log, stderr=subprocess.STDOUT)
    if wait_ready(lm_sock, lm_proc):
        send_json(lm_sock, scoring_payload("lm-warm"))
        lm_peak = 0
        for _ in range(20):
            value = rss_kib(lm_proc.pid)
            if value is not None:
                lm_peak = max(lm_peak, value)
            time.sleep(0.5)
        record["windows"]["memory"]["lm_only_peak_rss_kib"] = lm_peak
        record["windows"]["memory"]["incremental_peak_rss_kib"] = (
            peak - lm_peak if lm_peak else None)
    else:
        print("WARN: LM-only reference daemon not ready", file=sys.stderr)
    lm_proc.terminate()
    try:
        lm_proc.wait(10)
    except subprocess.TimeoutExpired:
        lm_proc.kill()
    lm_log.close()

    # -- 5. stop the shared daemon and write the record --------------------
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()
    record["finished"] = env_snapshot()
    out_path = os.path.join(records, "contention.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    print("contention record: %s" % out_path)
    print("R  evidence p50/p95/p99: %s" % json.dumps(
        record["windows"]["retrieval_only"]["percentiles"]))
    print("S  scoring  p50/p95/p99: %s" % json.dumps(
        record["windows"]["scoring_only"]["percentiles"]))
    print("C  evidence p50/p95/p99: %s" % json.dumps(
        record["windows"]["concurrent"]["evidence_percentiles"]))
    print("C  scoring  p50/p95/p99: %s" % json.dumps(
        record["windows"]["concurrent"]["scoring_percentiles"]))
    print("M  shared peak RSS: %s KiB; LM-only peak: %s KiB; incremental: %s"
          % (peak,
             record["windows"]["memory"].get("lm_only_peak_rss_kib"),
             record["windows"]["memory"].get("incremental_peak_rss_kib")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
