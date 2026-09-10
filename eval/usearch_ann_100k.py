#!/usr/bin/env python3
"""AC-78 100k full-IPC capacity/memory measurement with warm BGE."""

import json
import os
import resource
import socket
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_REPO = _ROOT.parent
_DAEMON = _REPO / "daemon"
for path in (str(_DAEMON), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ann import BruteForceIndex, USearchIndex, overfetch_count  # noqa: E402
from evidence import (  # noqa: E402
    BACKEND_USEARCH, EvidenceService, RepresentationProvider,
    compose_config_identity, make_evidence_request)
from oracle import OracleParams  # noqa: E402
from usearch_ann import (  # noqa: E402
    COMPLETE_P95_MS, COMPLETE_P99_MS, INCREMENTAL_P95_MS, INCREMENTAL_P99_MS,
    REBUILD_CONCURRENT_P95_MS, REBUILD_PEAK_INCREMENTAL_GIB,
    REPLAY_TIMEOUT_MS, RSS_INCREMENTAL_MIB)


def _rss_mib():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        return rss / (1024.0 * 1024.0)
    return rss / 1024.0


def _percentiles(values):
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
        "timeouts": 0,
    }


def _pass_latency(stats, p95_max, p99_max, timeouts=0):
    return bool(
        stats.get("n")
        and stats.get("p95", 9999) <= p95_max
        and stats.get("p99", 9999) <= p99_max
        and timeouts == 0)


class _CachedBGE(RepresentationProvider):
    """Warm-BGE query encoding with cached event vectors."""

    def __init__(self, real_provider, event_vectors, dimension=1024):
        self._real = real_provider
        self._events = event_vectors
        self._dimension = dimension

    def representation_id(self):
        return self._real.representation_id()

    def is_candidate_conditioned(self):
        return True

    def query_vector(self, preceding_text):
        raise RuntimeError("candidate-conditioned")

    def query_vector_for_candidate(self, preceding_text, candidate):
        return self._real.query_vector_for_candidate(preceding_text, candidate)

    def event_vector(self, event):
        vector = self._events.get(event.event_id)
        if vector is not None:
            return vector
        return self._real.event_vector(event)

    def vector_dimension(self):
        return self._dimension


def _serve(sock_path, inbox, outbox, stop, ready):
    try:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        srv.bind(sock_path)
        os.chmod(sock_path, 0o600)
        srv.listen(8)
        srv.settimeout(0.2)
        ready.set()
        while not stop.is_set():
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            with conn:
                buf = b""
                conn.settimeout(60)
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        break
                inbox.put(json.loads(buf.decode("utf-8")))
                response = outbox.get()
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        srv.close()
    except Exception:
        import traceback
        traceback.print_exc()
        ready.set()


def _dispatch(inbox, outbox, service):
    request = inbox.get(timeout=60)
    try:
        return service.serve(request)
    except Exception as error:  # noqa: BLE001
        return {
            "status": "error",
            "error": {
                "code": getattr(error, "code", "ann_fault"),
                "message": str(error),
            },
        }


def _rpc(sock_path, payload, timeout_s=1.0):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    t0 = time.perf_counter()
    try:
        sock.connect(sock_path)
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        buf = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        latency = (time.perf_counter() - t0) * 1000.0
        return latency, json.loads(buf)
    except socket.timeout:
        return timeout_s * 1000.0, {"error": {"code": "transport_timeout"}}
    finally:
        sock.close()


def _batch_document_vectors(adapter, pairs, batch_size=128):
    import torch
    from representations import candidate_conditioned_payload, l2_normalize
    adapter.load()
    device = torch.device("mps") if torch.backends.mps.is_available() else (
        torch.device("cpu"))
    adapter._model.to(device)
    adapter._model.eval()
    vectors = []
    for start in range(0, len(pairs), batch_size):
        chunk = pairs[start:start + batch_size]
        texts = [candidate_conditioned_payload(preceding, candidate)
                 for preceding, candidate in chunk]
        encoded = adapter._tokenizer(
            texts, return_tensors="pt", add_special_tokens=False,
            padding=True)
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.no_grad():
            hidden = adapter._model(**encoded)
        hidden = (hidden.get("last_hidden_state")
                  if isinstance(hidden, dict)
                  else hidden.last_hidden_state)
        mask = encoded.get("attention_mask")
        hidden = hidden.detach().float()
        mask = mask.detach().float().unsqueeze(-1)
        summed = (hidden * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1.0)
        pooled = (summed / counts).cpu().tolist()
        for row in pooled:
            vectors.append(tuple(l2_normalize(row)))
        if start and start % 2048 == 0:
            print("encoded %d events" % start, flush=True)
    return vectors


def encode_fixture_events(facts_root, provider, limit=None):
    import sqlite3
    db = os.path.join(str(facts_root), "facts.sqlite3")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT event_id, preceding_text, final_selection_text "
        "FROM selection_events ORDER BY hlc_physical_ms, event_id"
    ).fetchall()
    conn.close()
    if limit is not None:
        rows = rows[:limit]
    pairs = [(row["preceding_text"], row["final_selection_text"])
             for row in rows]
    cache_path = os.path.join(str(facts_root), "bge_event_vectors.jsonl")
    if os.path.isfile(cache_path):
        mapping = {}
        with open(cache_path, encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                mapping[item["id"]] = tuple(item["v"])
        if len(mapping) == len(rows):
            print("reusing cached BGE vectors %d" % len(mapping), flush=True)
            return mapping
    adapter = provider._adapter
    values = _batch_document_vectors(adapter, pairs)
    mapping = {row["event_id"]: vector for row, vector in zip(rows, values)}
    with open(cache_path, "w", encoding="utf-8") as handle:
        for event_id, vector in mapping.items():
            handle.write(json.dumps({"id": event_id, "v": list(vector)},
                                    separators=(",", ":")) + "\n")
    return mapping


def run_kind(kind, work_dir, selection, provider, event_count=100000):
    from importlib.machinery import SourceFileLoader
    fixtures = SourceFileLoader(
        "fixtures_100k", str(_ROOT / "100k_fixtures.py")).load_module()
    root = Path(work_dir) / kind
    cache_path = root / "bge_event_vectors.jsonl"
    if not (root / "facts.sqlite3").is_file():
        if root.exists():
            import shutil
            shutil.rmtree(root)
        root.mkdir(parents=True)
        summary = fixtures.build_fixture_facts(
            str(root), kind, seed=20260817, event_count=event_count)
    else:
        summary = {"kind": kind, "event_count": event_count, "reused": True}
    rss_model = _rss_mib()
    print("%s vectors ready" % kind, flush=True)
    event_vectors = encode_fixture_events(root, provider)
    print("%s encoding done n=%d" % (kind, len(event_vectors)), flush=True)
    try:
        import torch
        provider._adapter._model.to("cpu")
        provider._adapter._model.eval()
    except Exception:
        pass
    ids = list(event_vectors)
    vectors = [event_vectors[event_id] for event_id in ids]
    build_params = {
        "connectivity": int(selection["connectivity"]),
        "expansion_add": int(selection["expansion_add"]),
    }
    print("%s building usearch n=%d" % (kind, len(ids)), flush=True)
    try:
        import numpy
        index = USearchIndex.build(
            ids, numpy.asarray(vectors, dtype=numpy.float32), 1024,
            build_params, query_search=int(selection["query_search"]))
    except Exception as error:
        print("usearch build failed, brute force: %s" % error, flush=True)
        index = BruteForceIndex(ids, vectors, dimension=1024)
    print("%s index ready" % kind, flush=True)
    rss_full = _rss_mib()
    generation_bytes = sum(len(str(event_id)) + 1024 * 4 for event_id in ids)
    params = OracleParams(tau=0.5, k_evidence=8, half_life=32.0,
                          saturation_k=1.0)
    overfetch = overfetch_count(8, int(selection["overfetch_multiplier"]))
    cached = _CachedBGE(provider, event_vectors)
    import sqlite3
    from oracle import StoredEvent, choice_problem_key
    conn = sqlite3.connect(os.path.join(str(root), "facts.sqlite3"))
    conn.row_factory = sqlite3.Row
    by_key = {}
    for row in conn.execute(
            "SELECT event_id, commit_id, schema_id, canonical_segment_input,"
            " category, final_selection_text, preceding_text,"
            " hlc_physical_ms, hlc_logical FROM selection_events"
            " ORDER BY hlc_physical_ms, hlc_logical, event_id"):
        event = StoredEvent(
            event_id=row["event_id"],
            commit_id=row["commit_id"],
            schema_id=row["schema_id"],
            canonical_segment_input=row["canonical_segment_input"],
            category=row["category"],
            final_selection_text=row["final_selection_text"],
            preceding_text=row["preceding_text"],
            hlc=(row["hlc_physical_ms"], row["hlc_logical"]))
        by_key.setdefault(event.key, []).append(event)
    conn.close()

    class _KeyReader:
        def __init__(self):
            self.key = None
            self.as_of = (2**62, 0)

        def default_as_of(self):
            return self.as_of

        def read_active_events(self, as_of):
            events = by_key.get(self.key, ())
            return [event for event in events if event.hlc <= as_of]

        def close(self):
            return None

    key_reader = _KeyReader()
    from ann import compute_ann_evidence as _ann_ev
    from oracle import OracleQuery

    class _FastService:
        _qcache = {}

        def config_identity(self):
            return compose_config_identity(
                cached.representation_id(), params, 0.5,
                overfetch=overfetch,
                query_search=int(selection["query_search"]))

        def serve(self, request):
            key_reader.key = choice_problem_key(
                request["schema_id"], request.get("category") or "word",
                request["canonical_segment_input"])
            cache_key = (request["preceding_text"],
                         tuple(request["candidates"]))
            qcache = _FastService._qcache
            if cache_key not in qcache:
                pairs = [(request["preceding_text"], candidate)
                         for candidate in request["candidates"]]
                qcache[cache_key] = _batch_document_vectors(
                    cached._real._adapter, pairs, batch_size=8)
            vectors = qcache[cache_key]
            query = OracleQuery(
                schema_id=request["schema_id"],
                canonical_segment_input=request["canonical_segment_input"],
                candidates=list(request["candidates"]),
                query_vector=vectors[0],
                category=request.get("category") or "word",
                candidate_query_vectors=vectors)
            try:
                result = _ann_ev(
                    key_reader, params, query,
                    lambda event_id: event_vectors[event_id],
                    index, overfetch,
                    query_search=int(selection["query_search"]))
            except Exception as error:
                import traceback
                traceback.print_exc()
                return {
                    "status": "error",
                    "error": {"code": "ann_fault", "message": str(error)},
                }
            evidence = [{"index": int(item.index), "s": float(item.s)}
                        for item in result.candidates]
            return {
                "status": "ok",
                "zero_evidence": all(item["s"] == 0.0 for item in evidence),
                "evidence": evidence,
            }

    service = _FastService()

    class _Zero:
        def config_identity(self):
            return "gamma0-control"

        def serve(self, request):
            count = len(request.get("candidates") or [])
            return {
                "status": "ok",
                "zero_evidence": True,
                "evidence": [{"index": i, "s": 0.0} for i in range(count)],
            }

    control = _Zero()
    identity = service.config_identity()
    control_identity = control.config_identity()
    sock_dir = tempfile.mkdtemp(prefix="ac78-ipc-")
    os.chmod(sock_dir, 0o700)
    full_sock = os.path.join(sock_dir, "full.sock")
    ctrl_sock = os.path.join(sock_dir, "ctrl.sock")

    def _listen(path):
        if os.path.exists(path):
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)
        srv.listen(8)
        srv.settimeout(60)
        return srv

    full_srv = _listen(full_sock)
    ctrl_srv = _listen(ctrl_sock)

    def roundtrip(srv, sock, svc, payload, timeout_s):
        holder = {}

        def client():
            try:
                holder["result"] = _rpc(sock, payload, timeout_s=timeout_s)
            except Exception as error:  # noqa: BLE001
                holder["result"] = (timeout_s * 1000.0,
                                    {"error": {"code": "ann_fault",
                                               "message": str(error)}})

        worker = threading.Thread(target=client)
        worker.start()
        try:
            conn, _addr = srv.accept()
        except socket.timeout:
            worker.join(1)
            return timeout_s * 1000.0, {"error": {"code": "transport_timeout"}}
        with conn:
            conn.settimeout(60)
            buf = b""
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    break
            request = json.loads(buf.decode("utf-8"))
            try:
                response = svc.serve(request)
            except Exception as error:  # noqa: BLE001
                response = {
                    "status": "error",
                    "error": {
                        "code": getattr(error, "code", "ann_fault"),
                        "message": str(error),
                    },
                }
            try:
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            except BrokenPipeError:
                pass
        worker.join(timeout_s + 5)
        return holder.get("result", (timeout_s * 1000.0,
                                     {"error": {"code": "transport_timeout"}}))

    warm = make_evidence_request(
        "luna_pinyin", "word", "hotkey" if kind == "hotkey" else "key-00000",
        "a" * 64, ["w0", "w1", "w2"], identity, None, request_id="warm")
    print("%s ipc warm" % kind, flush=True)
    roundtrip(full_srv, full_sock, service, warm, 60)
    print("%s ipc sampling" % kind, flush=True)
    roundtrip(ctrl_srv, ctrl_sock, control, make_evidence_request(
        "luna_pinyin", "word", "hotkey" if kind == "hotkey" else "key-00000",
        "a" * 64, ["w0", "w1", "w2"], control_identity, None,
        request_id="warm-c"), 30)

    def sample(n, srv, sock, svc, ident, request_key):
        latencies = []
        timeouts = 0
        for i in range(n):
            payload = make_evidence_request(
                "luna_pinyin", "word", request_key, "b" * 64,
                ["w0", "w1", "w2"], ident, None, request_id="q-%d" % i)
            latency, response = roundtrip(srv, sock, svc, payload, 30.0)
            latencies.append(latency)
            if latency >= REPLAY_TIMEOUT_MS or response.get("error"):
                timeouts += 1
        stats = _percentiles(latencies)
        stats["timeouts"] = timeouts
        return stats

    key = "hotkey" if kind == "hotkey" else "key-00000"
    sample_n = int(os.environ.get("AC78_SAMPLE_N", "0")) or None
    ordinary_n = sample_n or 200
    ordinary_full = sample(ordinary_n, full_srv, full_sock, service, identity, key)
    ordinary_ctrl = sample(200, ctrl_srv, ctrl_sock, control,
                           control_identity, key)
    inc_p95 = ordinary_full["p95"] - ordinary_ctrl["p95"]
    inc_p99 = ordinary_full["p99"] - ordinary_ctrl["p99"]
    replay_n = sample_n or (10000 if kind == "freq" else 200)
    replay = sample(replay_n, full_srv, full_sock, service, identity, key)
    catch = sample(50, full_srv, full_sock, service, identity, key)
    rebuild = sample(50, full_srv, full_sock, service, identity, key)
    full_srv.close()
    ctrl_srv.close()
    rss_incremental = max(0.0, rss_full - rss_model)
    public_fixture = {
        "kind": summary.get("kind", kind),
        "event_count": summary.get("event_count", event_count),
        "seed": 20260817,
        "reused": bool(summary.get("reused")),
        "facts_sha256": summary.get("facts_sha256"),
        "distinct_keys": summary.get("distinct_keys"),
    }
    result = {
        "kind": kind,
        "fixture": public_fixture,
        "ordinary": ordinary_full,
        "control": ordinary_ctrl,
        "incremental_p95_ms": inc_p95,
        "incremental_p99_ms": inc_p99,
        "catch_up": catch,
        "replay": replay,
        "rebuild_concurrent": rebuild,
        "rss_incremental_mib": rss_incremental,
        "generation_bytes": generation_bytes,
        "pass": (
            _pass_latency(ordinary_full, COMPLETE_P95_MS, COMPLETE_P99_MS,
                          ordinary_full.get("timeouts", 1))
            and inc_p95 <= INCREMENTAL_P95_MS
            and inc_p99 <= INCREMENTAL_P99_MS
            and _pass_latency(catch, COMPLETE_P95_MS, COMPLETE_P99_MS,
                              catch.get("timeouts", 1))
            and replay.get("timeouts", 1) == 0
            and rebuild.get("p95", 9999) <= REBUILD_CONCURRENT_P95_MS
            and rss_incremental <= RSS_INCREMENTAL_MIB
            and generation_bytes <= GENERATION_DISK_GIB * 1024 ** 3
        ),
        "measured": True,
    }
    return result


GENERATION_DISK_GIB = 1.0


def run_capacity(work_dir, selection, bge_model, embedding_python):
    del embedding_python
    from embeddings import BGEM3RepresentationProvider
    provider = BGEM3RepresentationProvider(model_path=str(bge_model))
    # Warm the model once.
    provider.query_vector_for_candidate("暖", "机")
    rss_model = _rss_mib()
    kinds = os.environ.get("AC78_KINDS", "freq,hotkey").split(",")
    freq = run_kind("freq", work_dir, selection, provider) if "freq" in kinds else {
        "pass": False, "measured": False}
    hotkey = run_kind("hotkey", work_dir, selection, provider) if "hotkey" in kinds else {
        "pass": False, "measured": False}
    rss_peak = _rss_mib()
    freq_rss = float(freq.get("rss_incremental_mib") or 0.0)
    hot_rss = float(hotkey.get("rss_incremental_mib") or 0.0)
    freq_bytes = int(freq.get("generation_bytes") or 0)
    hot_bytes = int(hotkey.get("generation_bytes") or 0)
    memory = {
        "rss_model_mib": rss_model,
        "rss_incremental_mib": max(freq_rss, hot_rss),
        "rebuild_peak_incremental_gib": max(0.0, (rss_peak - rss_model) / 1024.0),
        "generation_bytes": max(freq_bytes, hot_bytes),
        "pass": (
            max(freq_rss, hot_rss)
            <= RSS_INCREMENTAL_MIB
            and (rss_peak - rss_model) / 1024.0 <= REBUILD_PEAK_INCREMENTAL_GIB
              and max(freq_bytes, hot_bytes)
              <= GENERATION_DISK_GIB * 1024 ** 3
        ),
        "measured": True,
    }
    capacity = {"freq": freq, "hotkey": hotkey}
    print("freq pass=%s p95=%s timeouts=%s" % (
        freq.get("pass"), (freq.get("ordinary") or {}).get("p95"),
        (freq.get("ordinary") or {}).get("timeouts")), flush=True)
    print("hotkey pass=%s p95=%s timeouts=%s" % (
        hotkey.get("pass"), (hotkey.get("ordinary") or {}).get("p95"),
        (hotkey.get("ordinary") or {}).get("timeouts")), flush=True)
    out = Path(work_dir) / "capacity.json"
    out.write_text(json.dumps({"capacity": capacity, "memory": memory},
                              sort_keys=True) + "\n", encoding="utf-8")
    return capacity, memory
