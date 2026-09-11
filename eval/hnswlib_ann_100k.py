#!/usr/bin/env python3
"""AC-79 100k full-IPC capacity/memory measurement via daemon EvidenceService."""

import json
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_REPO = _ROOT.parent
_DAEMON = _REPO / "daemon"
for path in (str(_DAEMON), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ac79_ipc import (  # noqa: E402
    append_commit, fact_high_water, percentiles, rss_mib, send,
    start_daemon, start_rebuild_process, stop_daemon,
)
from ann import (  # noqa: E402
    HNSWLIB_BACKEND, HnswlibIndex, compose_hnswlib_build_params,
    overfetch_count, publish_ann_sidecar, sidecar_dir,
)
from compat import compose_backend_fingerprint  # noqa: E402
from evidence import (  # noqa: E402
    make_evidence_request,
)
from hnswlib_ann import (  # noqa: E402
    COMPLETE_P95_MS, COMPLETE_P99_MS, DERIVED_DISK_GIB, GENERATION_DISK_GIB,
    INCREMENTAL_P95_MS, INCREMENTAL_P99_MS, REBUILD_CONCURRENT_P95_MS,
    REBUILD_PEAK_INCREMENTAL_GIB, REPLAY_TIMEOUT_MS, RSS_INCREMENTAL_MIB,
    Ann79Error, derived_state_bytes, published_generation_bytes,
)
from usearch_ann_100k import (  # noqa: E402
    CachedEventProvider, encode_fixture_events, _bge_representation_id,
    _ensure_fixture, _pass_latency, _request_keys, _sample,
)


def _publish_generation(facts_root, derived_root, representation_id,
                         event_vectors, selection):
    from generation import build_generation
    from publish import (
        write_active_manifest, _compose_active_manifest,
        _read_fact_schema_version, DELTA_FILENAME,
    )
    if derived_root.exists():
        shutil.rmtree(derived_root)
    derived_root.mkdir(parents=True)
    provider = CachedEventProvider(representation_id, event_vectors)
    build_params = compose_hnswlib_build_params({
        "M": int(selection["M"]),
        "ef_construction": int(selection["ef_construction"]),
    })
    generation = build_generation(
        str(facts_root), provider, str(derived_root),
        retrieval_backend="exact", retrieval_params=build_params)
    ids = generation.event_ids()
    if not ids:
        generation.close()
        raise Ann79Error("generation has no events")
    import numpy
    matrix = numpy.asarray(
        [generation.event_vector(event_id) for event_id in ids],
        dtype=numpy.float32)
    try:
        index = HnswlibIndex.build(
            ids, matrix, 1024, build_params,
            query_search=int(selection["query_search"]))
    except Exception as error:
        generation.close()
        raise Ann79Error("hnswlib build failed (no brute-force fallback): %s"
                         % error) from error
    fingerprint = compose_backend_fingerprint(
        backend=HNSWLIB_BACKEND, params=build_params)
    meta = {
        "backend": HNSWLIB_BACKEND,
        "metric": "cosine",
        "dtype": "f32",
        "dimension": 1024,
        "library_version": "hnswlib-hnsw-v1",
        "serialization_abi": "hnswlib-index-v1-arm64",
        "build_params": build_params,
        "index_fingerprint": fingerprint,
        "generation_id": generation.generation_id,
        "event_count": len(ids),
    }
    publish_ann_sidecar(index, str(derived_root), generation.generation_id, meta)
    from ann import load_ann_sidecar
    loaded, loaded_meta = load_ann_sidecar(
        sidecar_dir(str(derived_root), generation.generation_id),
        expected_generation_id=generation.generation_id)
    if loaded_meta.get("backend") != HNSWLIB_BACKEND:
        generation.close()
        raise Ann79Error("published sidecar is not hnswlib-hnsw")
    if len(loaded.event_ids()) != len(ids):
        generation.close()
        raise Ann79Error("hnswlib restore lost events")
    manifest = _compose_active_manifest(
        generation,
        "delta/%s/%s" % (generation.generation_id, DELTA_FILENAME),
        _read_fact_schema_version(str(facts_root)))
    write_active_manifest(str(derived_root), manifest)
    generation_id = generation.generation_id
    generation.close()
    return generation_id


def _write_daemon_config(path, facts_root, derived_root, bge_model, selection,
                         gamma=0.5):
    overfetch = overfetch_count(8, int(selection["overfetch_multiplier"]))
    payload = {
        "provider_kind": "bge_m3",
        "bge_model_path": str(bge_model),
        "facts_root": str(facts_root),
        "derived_root": str(derived_root),
        "tau": 0.5,
        "k_evidence": 8,
        "half_life": 32.0,
        "saturation_k": 1.0,
        "gamma": gamma,
        "control_gamma": 0.0,
        "overfetch": overfetch,
        "query_search": int(selection["query_search"]),
        "retrieval_backend": "hnswlib-hnsw",
        "catch_up_deadline_ms": 5000,
        "poll_interval_ms": 100,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def run_kind(kind, work_dir, selection, bge_model, python, representation_id,
             event_count=100000):
    root, summary = _ensure_fixture(kind, work_dir, event_count=event_count)
    print("%s vectors ready" % kind, flush=True)
    from embeddings import BGEM3RepresentationProvider
    provider = BGEM3RepresentationProvider(model_path=str(bge_model))
    event_vectors = encode_fixture_events(root, provider)
    print("%s encoding done n=%d" % (kind, len(event_vectors)), flush=True)
    derived_root = Path(work_dir) / ("%s-derived" % kind)
    from publish import read_active_manifest
    manifest, _reason = read_active_manifest(str(derived_root)) if (
        derived_root / "generations").is_dir() else (None, None)
    sidecar_ok = False
    if manifest is not None:
        sidecar_path = Path(sidecar_dir(str(derived_root),
                                        manifest["generation_id"])) / "index.ann"
        sidecar_ok = sidecar_path.is_file() and sidecar_path.stat().st_size > 0
    if sidecar_ok:
        generation_id = manifest["generation_id"]
        print("%s reusing hnswlib sidecar %s" % (kind, generation_id),
              flush=True)
    else:
        print("%s building generation+hnswlib n=%d" % (
            kind, len(event_vectors)), flush=True)
        generation_id = _publish_generation(
            root, derived_root, representation_id, event_vectors, selection)
        print("%s hnswlib sidecar ready %s" % (kind, generation_id), flush=True)
    generation_bytes = published_generation_bytes(
        str(derived_root), generation_id)
    derived_bytes = derived_state_bytes(str(derived_root), generation_id)

    keys = _request_keys(kind)
    sample_n = int(os.environ.get("AC79_SAMPLE_N", "0")) or None
    ordinary_n = sample_n or 200
    replay_n = sample_n or 10000
    catch_n = sample_n or 50
    rebuild_n = sample_n or 200

    sock_dir = Path(work_dir) / ("%s-sock" % kind)
    config_path = Path(work_dir) / ("%s-daemon.json" % kind)
    status_path = Path(work_dir) / ("%s-status.json" % kind)
    log_path = Path(work_dir) / ("%s-daemon.log" % kind)
    _write_daemon_config(config_path, root, derived_root, bge_model, selection)
    proc = log = None
    peak = 0.0
    serve_status = {}
    try:
        proc, log, sock_path, status = start_daemon(
            python, config_path, str(sock_dir), str(log_path),
            str(status_path), timeout_s=300)
        serve_status = status
        if status.get("ann_backend") != HNSWLIB_BACKEND:
            raise Ann79Error("daemon did not load hnswlib-hnsw")
        identity = status["config_identity"]
        control_identity = status["control_identity"]
        if identity == control_identity:
            raise Ann79Error("gamma=0 control identity collapsed into full")
        water = fact_high_water(str(root))
        warm = make_evidence_request(
            "luna_pinyin", "word", keys[0], "b" * 64, ["w0", "w1", "w2"],
            identity, water, request_id="warm")
        print("%s ipc warm" % kind, flush=True)
        warm_ms, warm_resp = send(sock_path, warm, timeout_s=60)
        print("%s ipc warm latency_ms=%.3f status=%s" % (
            kind, warm_ms, warm_resp.get("status") or warm_resp.get("error")),
              flush=True)
        send(sock_path, make_evidence_request(
            "luna_pinyin", "word", keys[0], "b" * 64, ["w0", "w1", "w2"],
            control_identity, water, request_id="warm-c"), timeout_s=60)
        print("%s ordinary n=%d" % (kind, ordinary_n), flush=True)
        ordinary_full = _sample(
            sock_path, identity, keys, water, ordinary_n, 30.0,
            REPLAY_TIMEOUT_MS, "ord")
        print("%s ordinary %s" % (kind, ordinary_full), flush=True)
        ordinary_ctrl = _sample(
            sock_path, control_identity, keys, water, ordinary_n, 30.0,
            REPLAY_TIMEOUT_MS, "ctrl")
        print("%s control %s" % (kind, ordinary_ctrl), flush=True)
        inc_p95 = ordinary_full["p95"] - ordinary_ctrl["p95"]
        inc_p99 = ordinary_full["p99"] - ordinary_ctrl["p99"]
        print("%s replay n=%d" % (kind, replay_n), flush=True)
        replay = _sample(
            sock_path, identity, keys, water, replay_n, 30.0,
            REPLAY_TIMEOUT_MS, "replay")
        print("%s replay %s" % (kind, replay), flush=True)
        print("%s rebuild-concurrent n=%d" % (kind, rebuild_n), flush=True)
        rebuild_log = Path(work_dir) / ("%s-rebuild.log" % kind)
        rebuild_proc, rebuild_log_handle = start_rebuild_process(
            python, derived_root, generation_id, str(rebuild_log))
        peak_serving = rss_mib(proc.pid) or 0.0
        try:
            rebuild = _sample(
                sock_path, identity, keys, water, rebuild_n, 30.0,
                REPLAY_TIMEOUT_MS, "rebuild")
            sampled = rss_mib(proc.pid)
            if sampled is not None:
                peak_serving = max(peak_serving, sampled)
            rebuild_rss = rss_mib(rebuild_proc.pid) or 0.0
            peak = peak_serving + rebuild_rss
        finally:
            stop_daemon(rebuild_proc, rebuild_log_handle)
        print("%s rebuild %s peak_rss_mib=%s" % (kind, rebuild, peak),
              flush=True)
        stop_daemon(proc, log)
        proc = log = None

        catch_facts = Path(work_dir) / ("%s-catch-facts" % kind)
        catch_derived = Path(work_dir) / ("%s-catch-derived" % kind)
        shutil.rmtree(catch_facts, ignore_errors=True)
        shutil.rmtree(catch_derived, ignore_errors=True)
        shutil.copytree(root, catch_facts)
        shutil.copytree(derived_root, catch_derived)
        catch_config = Path(work_dir) / ("%s-catch-daemon.json" % kind)
        _write_daemon_config(
            catch_config, catch_facts, catch_derived, bge_model, selection)
        catch_status = Path(work_dir) / ("%s-catch-status.json" % kind)
        catch_log = Path(work_dir) / ("%s-catch.log" % kind)
        proc, log, sock_path, status = start_daemon(
            python, catch_config, str(sock_dir) + "-catch", str(catch_log),
            str(catch_status), timeout_s=300)
        identity = status["config_identity"]
        catch_key = "hotkey" if kind == "hotkey" else "key-00000"
        water = fact_high_water(str(catch_facts))
        send(sock_path, make_evidence_request(
            "luna_pinyin", "word", catch_key, "b" * 64, ["w0", "w1", "w2"],
            identity, water, request_id="catch-warm"), timeout_s=60)
        print("%s catch-up n=%d" % (kind, catch_n), flush=True)
        catch_latencies = []
        catch_timeouts = 0
        catch_faults = 0
        base_physical = water["hlc_physical_ms"]
        for i in range(catch_n):
            new_physical = base_physical + i + 1
            append_commit(
                str(catch_facts), catch_key, new_physical, i, 900000 + i)
            payload = make_evidence_request(
                "luna_pinyin", "word", catch_key, "b" * 64,
                ["w0", "w1", "w2"], identity, {
                    "store_epoch": water["store_epoch"],
                    "hlc_physical_ms": new_physical,
                    "hlc_logical": i,
                }, request_id="catch-%d" % i)
            latency, response = send(sock_path, payload, timeout_s=30.0)
            catch_latencies.append(latency)
            if latency >= REPLAY_TIMEOUT_MS:
                catch_timeouts += 1
            if response.get("error") or response.get("status") != "ok":
                catch_faults += 1
        catch = percentiles(catch_latencies)
        catch["timeouts"] = catch_timeouts
        catch["faults"] = catch_faults
    finally:
        stop_daemon(proc, log)

    rss_model = float(serve_status.get("rss_model_mib") or 0.0)
    rss_ready = float(serve_status.get("rss_ready_mib") or 0.0)
    rss_incremental = max(0.0, rss_ready - rss_model)
    rebuild_peak_incremental_gib = max(0.0, (peak - rss_model) / 1024.0)
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
        "ipc": "daemon-EvidenceService",
        "backend": HNSWLIB_BACKEND,
        "gamma0_control": "EvidenceService",
        "brute_force_fallback": False,
        "ordinary": ordinary_full,
        "control": ordinary_ctrl,
        "incremental_p95_ms": inc_p95,
        "incremental_p99_ms": inc_p99,
        "catch_up": catch,
        "replay": replay,
        "rebuild_concurrent": rebuild,
        "rss_incremental_mib": rss_incremental,
        "rss_model_mib": rss_model,
        "generation_bytes": generation_bytes,
        "derived_bytes": derived_bytes,
        "generation_id": generation_id,
        "pass": (
            _pass_latency(ordinary_full, COMPLETE_P95_MS, COMPLETE_P99_MS,
                          ordinary_full.get("timeouts", 1))
            and inc_p95 <= INCREMENTAL_P95_MS
            and inc_p99 <= INCREMENTAL_P99_MS
            and _pass_latency(catch, COMPLETE_P95_MS, COMPLETE_P99_MS,
                              catch.get("timeouts", 1))
            and replay.get("timeouts", 1) == 0
            and replay.get("n") == replay_n
            and rebuild.get("p95", 9999) <= REBUILD_CONCURRENT_P95_MS
            and rss_incremental <= RSS_INCREMENTAL_MIB
            and generation_bytes <= GENERATION_DISK_GIB * 1024 ** 3
            and derived_bytes <= DERIVED_DISK_GIB * 1024 ** 3
        ),
        "measured": True,
    }
    return result, {
        "rss_model_mib": rss_model,
        "rss_incremental_mib": rss_incremental,
        "rebuild_peak_incremental_gib": rebuild_peak_incremental_gib,
        "generation_bytes": generation_bytes,
        "derived_bytes": derived_bytes,
        "derived_root": str(derived_root),
        "generation_id": generation_id,
    }


def run_capacity(work_dir, selection, bge_model, embedding_python):
    python = str(embedding_python)
    representation_id = _bge_representation_id(bge_model)
    kinds = os.environ.get("AC79_KINDS", "freq,hotkey").split(",")
    freq = {"pass": False, "measured": False}
    hotkey = {"pass": False, "measured": False}
    freq_mem = {}
    hot_mem = {}
    if "freq" in kinds:
        freq, freq_mem = run_kind(
            "freq", work_dir, selection, bge_model, python, representation_id)
    if "hotkey" in kinds:
        hotkey, hot_mem = run_kind(
            "hotkey", work_dir, selection, bge_model, python,
            representation_id)
    freq_rss = float(freq.get("rss_incremental_mib") or 0.0)
    hot_rss = float(hotkey.get("rss_incremental_mib") or 0.0)
    freq_bytes = int(freq.get("generation_bytes") or 0)
    hot_bytes = int(hotkey.get("generation_bytes") or 0)
    freq_derived = int(freq.get("derived_bytes") or 0)
    hot_derived = int(hotkey.get("derived_bytes") or 0)
    rss_model = float(freq_mem.get("rss_model_mib")
                      or hot_mem.get("rss_model_mib") or 0.0)
    peak = max(float(freq_mem.get("rebuild_peak_incremental_gib") or 0.0),
               float(hot_mem.get("rebuild_peak_incremental_gib") or 0.0))
    generation_bytes = max(freq_bytes, hot_bytes)
    derived_bytes = max(freq_derived, hot_derived)
    memory = {
        "rss_model_mib": rss_model,
        "rss_incremental_mib": max(freq_rss, hot_rss),
        "rebuild_peak_incremental_gib": peak,
        "generation_bytes": generation_bytes,
        "derived_bytes": derived_bytes,
        "generation_disk_measured": True,
        "derived_disk_measured": True,
        "pass": (
            max(freq_rss, hot_rss) <= RSS_INCREMENTAL_MIB
            and peak <= REBUILD_PEAK_INCREMENTAL_GIB
            and generation_bytes <= GENERATION_DISK_GIB * 1024 ** 3
            and derived_bytes <= DERIVED_DISK_GIB * 1024 ** 3
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
