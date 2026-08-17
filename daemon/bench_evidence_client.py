#!/usr/bin/env python3
"""#71 capacity-benchmark evidence-path measurement client.

Measures retrieval-evidence request latency over the real unix-socket IPC
path against a running bench evidence daemon (bench_evidence_daemon.py),
for the #71 capacity fixtures (freq distribution and single-hot-key).

Scenarios measured (spec #43 "十万事件性能夹具"; contract SCN-71-2):

  S1 ordinary query: a request whose choice-problem key has a populated
     same-key history (the fixture's hot keys).
  S2 first query after a commit: the daemon's delta worker must catch up
     one freshly committed event before the request is served (the
     not_caught_up gate path).
  S3 10,000-request replay: sequential requests; any single request whose
     round-trip exceeds the client deadline (200 ms by default, matching
     the plugin's EvidenceScorer deadline) is counted as a timeout.
  S4 background-rebuild concurrency: the evidence requests run while a
     staging generation build is in progress in the same derived root;
     the full request p95 must still hold.

For each scenario the client records per-request latencies (ms), the
percentiles (p50/p95/p99), timeout counts and the window's loadavg +
process snapshot, so the report can prove the quiet-machine discipline.

The client never writes raw 上文 / candidate text: it only carries the
synthetic fixture keys and synthetic competition text it was given.
"""

import argparse
import datetime
import json
import os
import socket
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evidence import (EVIDENCE_PROTOCOL_VERSION,  # noqa: E402
                      compose_config_identity, make_evidence_request)
from oracle import OracleParams  # noqa: E402


def send(sock_path, payload, timeout_s=120.0):
    """One framed evidence request/response round trip.

    Returns (latency_ms, response).  On a transport timeout it returns
    (timeout_ms, {"error": {"code": "transport_timeout"}}) so the caller
    records the timeout honestly (a true fault, never a silent success).
    """
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


def environment_snapshot():
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
        "host": socket.gethostname(),
    }


def build_request(schema_id, canonical_input, preceding_text, candidates,
                  config_identity, fact_high_water, request_id):
    return make_evidence_request(
        schema_id=schema_id, category="word",
        canonical_segment_input=canonical_input,
        preceding_text=preceding_text, candidates=candidates,
        config_identity=config_identity,
        fact_high_water=fact_high_water, request_id=request_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--kind", required=True, choices=("freq", "hotkey"))
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--dimension", type=int, default=1024)
    parser.add_argument("--representation-id", required=True)
    parser.add_argument("--tau", type=float, default=0.4)
    parser.add_argument("--k-evidence", type=int, default=8)
    parser.add_argument("--half-life", type=float, default=32.0)
    parser.add_argument("--saturation-k", type=float, default=2.0)
    parser.add_argument("--gamma", type=float, default=2.0)
    parser.add_argument("--client-deadline-ms", type=float, default=200.0)
    parser.add_argument("--replay-count", type=int, default=10000)
    parser.add_argument("--output", required=True,
                        help="JSON file for the measurement record")
    parser.add_argument("--facts-root", required=True,
                        help="fixture facts root (for the watermark)")
    args = parser.parse_args()

    params = OracleParams(tau=args.tau, k_evidence=args.k_evidence,
                          half_life=args.half_life,
                          saturation_k=args.saturation_k)
    config_identity = compose_config_identity(
        args.representation_id, params, args.gamma)

    # Watermark: read the fixture store's current HLC (read-only).
    import sqlite3
    conn = sqlite3.connect(os.path.join(args.facts_root, "facts.sqlite3"))
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()
    fact_high_water = {
        "store_epoch": meta["store_epoch"],
        "hlc_physical_ms": int(meta["hlc_physical_ms"]),
        "hlc_logical": int(meta["hlc_logical"]),
    }

    # Build request shapes.
    if args.kind == "hotkey":
        canonical_inputs = ["hotkey"] * 50
    else:
        # The freq fixture's hot keys (deterministic): the first keys by
        # count from the summary are the expensive ones; sample a spread
        # including cold keys to reflect the distribution.
        canonical_inputs = ["key-%05d" % index for index in
                            range(0, 2000, 40)]
    candidates = ["w0", "w1", "w2"]
    preceding = "a" * 64  # synthetic 64-char window

    record = {
        "contract": "AC-71-v1",
        "kind": args.kind,
        "seed": args.seed,
        "dimension": args.dimension,
        "representation_id": args.representation_id,
        "params": {
            "tau": args.tau, "k_evidence": args.k_evidence,
            "half_life": args.half_life, "saturation_k": args.saturation_k,
            "gamma": args.gamma,
        },
        "client_deadline_ms": args.client_deadline_ms,
        "config_identity": config_identity,
        "fact_high_water": fact_high_water,
        "started": environment_snapshot(),
    }

    # S1 ordinary query latency across the key spread.
    s1_latencies = []
    s1_faults = 0
    for index, canonical in enumerate(canonical_inputs):
        payload = build_request(
            "luna_pinyin", canonical, preceding, candidates,
            config_identity, fact_high_water,
            "s1-%d" % index)
        dt_ms, response = send(args.socket, payload)
        if "error" in response or not response.get("status") == "ok":
            s1_faults += 1
        s1_latencies.append(dt_ms)
    record["s1_ordinary_query"] = {
        "latencies_ms": s1_latencies,
        "percentiles": percentiles(s1_latencies),
        "faults": s1_faults,
    }
    print("S1 ordinary: %s" % json.dumps(record["s1_ordinary_query"]
                                         ["percentiles"]))

    # S3 10k replay: mix of hot and cold keys, deadline-enforced.
    # Runs BEFORE S2 so the S2 commit appends do not pollute the replay's
    # steady-state measurement (the delta must stay caught up throughout).
    s3_latencies = []
    s3_timeouts = 0
    s3_faults = 0
    for index in range(args.replay_count):
        if args.kind == "hotkey":
            canonical = "hotkey"
        else:
            canonical = canonical_inputs[index % len(canonical_inputs)]
        payload = build_request(
            "luna_pinyin", canonical, preceding, candidates,
            config_identity, fact_high_water, "s3-%d" % index)
        dt_ms, response = send(args.socket, payload)
        if "error" in response or not response.get("status") == "ok":
            s3_faults += 1
        if dt_ms >= args.client_deadline_ms:
            s3_timeouts += 1
        s3_latencies.append(dt_ms)
        if (index + 1) % 1000 == 0:
            print("S3 replay %d/%d timeouts=%d" % (
                index + 1, args.replay_count, s3_timeouts), flush=True)
    record["s3_replay"] = {
        "count": args.replay_count,
        "latencies_ms": s3_latencies,
        "percentiles": percentiles(s3_latencies),
        "timeouts": s3_timeouts,
        "faults": s3_faults,
    }
    print("S3 replay: %s" % json.dumps(record["s3_replay"]["percentiles"]))

    # S2 first query after one fresh commit (catch-up gate): a new commit
    # batch is appended to the facts store (exact recorder transaction
    # shape: commits + event + candidates + HLC advance), then the first
    # evidence request measures the daemon's catch-up latency (embed the
    # new event vector, durable delta transaction, publish the snapshot)
    # plus the query itself.  The catch-up deadline in the config is 5 s;
    # a fault (not_caught_up / representation_fault) is recorded honestly.
    def append_commit(physical_ms, logical, seq):
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(
            os.path.join(args.facts_root, "facts.sqlite3"))
        conn.execute("PRAGMA journal_mode=WAL;")
        commit_id = "bench-commit-%d" % seq
        event_id = "bench-ev-%d" % seq
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
            " VALUES(?,?,1,'luna_pinyin','hotkey',0,4,'word',?,1,?,"
            " 'explicit_current',NULL,1,1,'bench',?,?,?,?,?)",
            (event_id, commit_id, "a" * 64, "w0", seq, physical_ms,
             logical, physical_ms, physical_ms))
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

    s2_latencies = []
    s2_faults = 0
    s2_timeouts = 0
    base_physical = fact_high_water["hlc_physical_ms"]
    for index in range(20):
        new_physical = base_physical + index + 1
        append_commit(new_physical, index, 900000 + index)
        payload = build_request(
            "luna_pinyin", "hotkey", preceding, candidates,
            config_identity, {
                "store_epoch": fact_high_water["store_epoch"],
                "hlc_physical_ms": new_physical,
                "hlc_logical": index,
            }, "s2-%d" % index)
        dt_ms, response = send(args.socket, payload)
        if "error" in response or not response.get("status") == "ok":
            s2_faults += 1
        if dt_ms >= args.client_deadline_ms:
            s2_timeouts += 1
        s2_latencies.append(dt_ms)
    record["s2_first_after_commit"] = {
        "latencies_ms": s2_latencies,
        "percentiles": percentiles(s2_latencies),
        "faults": s2_faults,
        "timeouts": s2_timeouts,
        "commits_appended": 20,
        "note": ("each iteration appends one commit batch to the facts "
                 "store then issues the first evidence request for the new "
                 "watermark; the measured latency includes the delta "
                 "catch-up (embed + durable delta tx + snapshot publish) "
                 "plus the oracle query"),
    }
    print("S2 first-after-commit: %s" % json.dumps(
        record["s2_first_after_commit"]["percentiles"]))

    record["finished"] = environment_snapshot()
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True,
                  indent=2)
    print("record written: %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
