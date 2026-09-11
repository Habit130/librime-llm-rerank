#!/usr/bin/env python3
"""Isolated real hnswlib sidecar lifecycle for ANN79-6."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_ROOT)
_DAEMON = os.path.join(_REPO, "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from ann import (  # noqa: E402
    AnnError, HNSWLIB_BACKEND, HnswlibIndex, compose_hnswlib_build_params,
    load_ann_sidecar, publish_ann_sidecar, rebuild_ann_from_generation,
    sidecar_dir,
)
from compat import compose_backend_fingerprint  # noqa: E402
from evidence import make_evidence_request  # noqa: E402
from generation import open_generation  # noqa: E402
from seed_vectors import SeedVectorProvider  # noqa: E402
from hnswlib_ann import Ann79Error  # noqa: E402

LIFECYCLE_REPR = "ac79-lifecycle-seed:1024"
LIFECYCLE_SEED = 20260817
LIFECYCLE_EVENTS = 64


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n",
                    encoding="utf-8")


def _hnswlib_available():
    try:
        import hnswlib  # noqa: F401
    except ImportError:
        return False
    return True


def _build_isolated(work_dir, selection):
    from importlib.machinery import SourceFileLoader
    fixtures = SourceFileLoader(
        "fixtures_100k", os.path.join(_ROOT, "100k_fixtures.py")).load_module()
    from generation import build_generation
    from publish import (
        write_active_manifest, _compose_active_manifest,
        _read_fact_schema_version, DELTA_FILENAME,
    )
    facts_root = os.path.join(work_dir, "facts")
    derived_root = os.path.join(work_dir, "derived")
    shutil.rmtree(facts_root, ignore_errors=True)
    shutil.rmtree(derived_root, ignore_errors=True)
    os.makedirs(facts_root, mode=0o700)
    os.makedirs(derived_root, mode=0o700)
    fixtures.build_fixture_facts(
        facts_root, "freq", seed=LIFECYCLE_SEED, event_count=LIFECYCLE_EVENTS)
    provider = SeedVectorProvider(LIFECYCLE_REPR, LIFECYCLE_SEED, 1024)
    build_params = compose_hnswlib_build_params({
        "M": int(selection["M"]),
        "ef_construction": int(selection["ef_construction"]),
    })
    generation = build_generation(
        facts_root, provider, derived_root, retrieval_backend="exact",
        retrieval_params=build_params)
    ids = generation.event_ids()
    import numpy
    vectors = numpy.asarray(
        [generation.event_vector(event_id) for event_id in ids],
        dtype=numpy.float32)
    index = HnswlibIndex.build(
        ids, vectors, 1024, build_params,
        query_search=int(selection["query_search"]))
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
    publish_ann_sidecar(index, derived_root, generation.generation_id, meta)
    manifest = _compose_active_manifest(
        generation,
        "delta/%s/%s" % (generation.generation_id, DELTA_FILENAME),
        _read_fact_schema_version(facts_root))
    write_active_manifest(derived_root, manifest)
    generation_id = generation.generation_id
    generation.close()
    return {
        "facts_root": facts_root,
        "derived_root": derived_root,
        "generation_id": generation_id,
        "build_params": build_params,
        "fingerprint": fingerprint,
        "event_ids": list(ids),
        "meta": meta,
    }


def _check_restart_load(derived_root, generation_id, expected_ids):
    loaded, meta = load_ann_sidecar(
        sidecar_dir(derived_root, generation_id),
        expected_generation_id=generation_id)
    if meta.get("backend") != HNSWLIB_BACKEND:
        raise Ann79Error("restart load used non-hnswlib backend")
    got = list(loaded.event_ids())
    if got != list(expected_ids):
        raise Ann79Error("restart load event id mismatch")
    probe = loaded.search([1.0] + [0.0] * 1023, 4)
    if not isinstance(probe, list):
        raise Ann79Error("restart load search failed")
    return True


def _check_mixed_generation_refuse(derived_root, generation_id):
    try:
        load_ann_sidecar(
            sidecar_dir(derived_root, generation_id),
            expected_generation_id="not-" + generation_id)
    except AnnError as error:
        if error.code == "ann_identity":
            return True
        raise Ann79Error("mixed-generation refuse used %s" % error.code)
    raise Ann79Error("mixed-generation sidecar loaded")


def _check_corrupt_rebuild(bundle):
    derived_root = bundle["derived_root"]
    generation_id = bundle["generation_id"]
    directory = sidecar_dir(derived_root, generation_id)
    ann_path = os.path.join(directory, "index.ann")
    with open(ann_path, "wb") as handle:
        handle.write(b"corrupt-hnswlib-index")
    generation = open_generation(
        os.path.join(derived_root, "generations", generation_id))
    try:
        rebuild_ann_from_generation(
            generation, derived_root, generation_id,
            bundle["build_params"], bundle["fingerprint"],
            backend=HNSWLIB_BACKEND)
    finally:
        generation.close()
    _check_restart_load(derived_root, generation_id, bundle["event_ids"])
    return True


def _check_unhealthy_fp32_refuse(bundle):
    copy_root = bundle["derived_root"] + "-unhealthy"
    shutil.rmtree(copy_root, ignore_errors=True)
    shutil.copytree(bundle["derived_root"], copy_root)
    generation_id = bundle["generation_id"]
    fp32 = os.path.join(copy_root, "generations", generation_id, "vectors.fp32")
    with open(fp32, "wb") as handle:
        handle.write(b"corrupt")
    try:
        generation = open_generation(
            os.path.join(copy_root, "generations", generation_id))
    except Exception:
        generation = None
    refused = generation is None
    if generation is not None:
        try:
            rebuild_ann_from_generation(
                generation, copy_root, generation_id,
                bundle["build_params"], bundle["fingerprint"],
                backend=HNSWLIB_BACKEND)
        except AnnError as error:
            refused = error.code == "unhealthy_fp32"
        finally:
            generation.close()
    shutil.rmtree(copy_root, ignore_errors=True)
    if not refused:
        raise Ann79Error("unhealthy FP32 did not refuse index rebuild")
    return True


def _check_catch_up_ipc(python, bundle, selection, work_dir):
    from ac79_ipc import (
        append_commit, fact_high_water, send, start_daemon, stop_daemon,
    )
    sock_dir = os.path.join(work_dir, "sock")
    config_path = os.path.join(work_dir, "daemon.json")
    status_path = os.path.join(work_dir, "status.json")
    log_path = os.path.join(work_dir, "daemon.log")
    overfetch = max(32, int(selection["overfetch_multiplier"]) * 8)
    config = {
        "provider_kind": "seed_vectors",
        "representation_id": LIFECYCLE_REPR,
        "seed": LIFECYCLE_SEED,
        "vector_dimension": 1024,
        "facts_root": bundle["facts_root"],
        "derived_root": bundle["derived_root"],
        "tau": 0.5,
        "k_evidence": 8,
        "half_life": 32.0,
        "saturation_k": 1.0,
        "gamma": 0.5,
        "control_gamma": 0.0,
        "overfetch": overfetch,
        "query_search": int(selection["query_search"]),
        "retrieval_backend": "hnswlib-hnsw",
        "catch_up_deadline_ms": 5000,
        "poll_interval_ms": 100,
    }
    _write_json(config_path, config)
    proc = log = None
    try:
        proc, log, sock_path, status = start_daemon(
            python, config_path, sock_dir, log_path, status_path,
            timeout_s=120)
        identity = status["config_identity"]
        water = fact_high_water(bundle["facts_root"])
        payload = make_evidence_request(
            "luna_pinyin", "word", "key-00000", "a" * 64,
            ["w0", "w1", "w2"], identity, water, request_id="life-warm")
        _latency, response = send(sock_path, payload, timeout_s=30)
        if response.get("status") != "ok":
            raise Ann79Error("lifecycle warm query failed: %s" % response)
        new_physical = water["hlc_physical_ms"] + 1
        event_id = append_commit(
            bundle["facts_root"], "key-00000", new_physical, 1, 900001)
        new_water = {
            "store_epoch": water["store_epoch"],
            "hlc_physical_ms": new_physical,
            "hlc_logical": 1,
        }
        payload = make_evidence_request(
            "luna_pinyin", "word", "key-00000", "a" * 64,
            ["w0", "w1", "w2"], identity, new_water,
            request_id="life-catch")
        _latency, response = send(sock_path, payload, timeout_s=30)
        if response.get("status") != "ok":
            raise Ann79Error(
                "catch-up query failed after commit %s: %s"
                % (event_id, response))
        if response.get("error"):
            raise Ann79Error("catch-up returned error %s" % response)
        return True, status
    finally:
        stop_daemon(proc, log)


def run_lifecycle(work_dir, selection, python, qualification_derived=None):
    if not _hnswlib_available():
        raise Ann79Error("hnswlib is required for the isolated lifecycle run")
    work_dir = str(work_dir)
    os.makedirs(work_dir, mode=0o700, exist_ok=True)
    result = {
        "measured": False,
        "pass": False,
        "backend": HNSWLIB_BACKEND,
        "brute_force": False,
        "catch_up": False,
        "atomic_publish": False,
        "restart_load": False,
        "mixed_generation_refuse": False,
        "corrupt_rebuild": False,
        "index_only_unhealthy_refuse": False,
        "qualification_sidecar_restore": False,
    }
    isolated = tempfile.mkdtemp(prefix="ac79-life-", dir=work_dir)
    os.chmod(isolated, 0o700)
    bundle = _build_isolated(isolated, selection)
    result["atomic_publish"] = os.path.isfile(
        os.path.join(sidecar_dir(bundle["derived_root"],
                                 bundle["generation_id"]), "index.ann"))
    result["restart_load"] = _check_restart_load(
        bundle["derived_root"], bundle["generation_id"], bundle["event_ids"])
    result["mixed_generation_refuse"] = _check_mixed_generation_refuse(
        bundle["derived_root"], bundle["generation_id"])
    result["catch_up"], _status = _check_catch_up_ipc(
        python, bundle, selection, os.path.join(isolated, "ipc"))
    result["corrupt_rebuild"] = _check_corrupt_rebuild(bundle)
    result["index_only_unhealthy_refuse"] = _check_unhealthy_fp32_refuse(bundle)
    if qualification_derived:
        from publish import read_active_manifest
        manifest, _reason = read_active_manifest(qualification_derived)
        if manifest is not None:
            qcopy = os.path.join(isolated, "qualify-copy")
            shutil.rmtree(qcopy, ignore_errors=True)
            shutil.copytree(qualification_derived, qcopy)
            loaded, meta = load_ann_sidecar(
                sidecar_dir(qcopy, manifest["generation_id"]),
                expected_generation_id=manifest["generation_id"])
            result["qualification_sidecar_restore"] = (
                meta.get("backend") == HNSWLIB_BACKEND
                and len(loaded.event_ids()) > 0)
    result["measured"] = all(
        result[key] is not False for key in (
            "catch_up", "atomic_publish", "restart_load",
            "mixed_generation_refuse", "corrupt_rebuild",
            "index_only_unhealthy_refuse"))
    result["pass"] = bool(result["measured"])
    result["note"] = (
        "isolated real hnswlib sidecar lifecycle; EvidenceService IPC catch-up")
    _write_json(os.path.join(work_dir, "lifecycle.json"), result)
    return result
