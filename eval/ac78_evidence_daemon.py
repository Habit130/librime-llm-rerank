#!/usr/bin/env python3
"""AC-78 EvidenceService unix-socket daemon (usearch + optional BGE)."""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
if _DAEMON not in sys.path:
    sys.path.insert(0, _DAEMON)

from ann import (  # noqa: E402
    USEARCH_BACKEND, load_ann_sidecar, sidecar_dir,
)
from control import validate_control_path  # noqa: E402
from delta import build_delta_machine_from_config  # noqa: E402
from evidence import (  # noqa: E402
    EVIDENCE_KIND, EvidenceError, build_evidence_service_from_config,
)
from server import read_request  # noqa: E402


def _rss_mib(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip()) / 1024.0
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def _load_index(derived_root, generation_id, query_search):
    directory = sidecar_dir(derived_root, generation_id)
    index, meta = load_ann_sidecar(
        directory, expected_generation_id=generation_id,
        query_search=query_search)
    if meta.get("backend") != USEARCH_BACKEND:
        raise EvidenceError(
            "ann_identity",
            "ANN sidecar backend %r is not usearch-hnsw" % meta.get("backend"))
    return index, meta


def _rebuild_worker(derived_root, generation_id, build_params, fingerprint):
    try:
        from generation import open_generation
        from ann import rebuild_ann_from_generation
        published = os.path.join(derived_root, "generations", generation_id)
        generation = open_generation(published)
        try:
            staging_root = os.path.join(derived_root, "staging")
            os.makedirs(staging_root, mode=0o700, exist_ok=True)
            rebuild_ann_from_generation(
                generation, staging_root, "ann-rebuild-" + generation_id,
                build_params, fingerprint)
        finally:
            generation.close()
        print("REBUILD_DONE", flush=True)
    except Exception as error:  # noqa: BLE001
        print("REBUILD_FAIL %s" % error, flush=True)


def service_handle(state, data):
    from server import EVIDENCE_FIELDS, PROTOCOL_VERSION
    try:
        req = json.loads(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"version": 2, "error": {"code": "invalid_json"}}
    if (not isinstance(req, dict) or set(req) != EVIDENCE_FIELDS
            or req.get("kind") != EVIDENCE_KIND
            or req.get("version") != PROTOCOL_VERSION):
        return {"version": 2, "error": {"code": "invalid_request"}}
    service = state.services.get(req["config_identity"])
    if service is None:
        return {"version": 2, "error": {"code": "config_identity_mismatch"}}
    try:
        result = service.serve(req)
        return {
            "version": PROTOCOL_VERSION,
            "kind": EVIDENCE_KIND,
            "request_id": req["request_id"],
            "plan_identity": req["plan_identity"],
            "config_identity": req["config_identity"],
            "fact_high_water": req["fact_high_water"],
            "status": "ok",
            "zero_evidence": result["zero_evidence"],
            "evidence": result["evidence"],
            "query_point": result["query_point"],
        }
    except EvidenceError as error:
        return {"version": 2, "error": {
            "code": error.code, "message": error.message,
            "phase": "evidence"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--status-file", default=None)
    parser.add_argument("--rebuild-concurrent", action="store_true")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as handle:
        config = json.load(handle)

    validate_control_path(args.socket)

    from publish import read_active_manifest
    manifest, reason = read_active_manifest(config["derived_root"])
    if manifest is None:
        print("FAIL: no active manifest: %s" % reason, file=sys.stderr)
        return 2
    config["generation_id"] = manifest["generation_id"]
    config["representation_id"] = manifest["representation_id"]
    config["retrieval_backend"] = "usearch-hnsw"
    overfetch = int(config["overfetch"])
    query_search = int(config["query_search"])
    control_gamma = float(config.get("control_gamma", 0.0))

    rss_model = None
    if config.get("provider_kind") == "bge_m3":
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from embeddings import BGEM3RepresentationProvider
        warmer = BGEM3RepresentationProvider(
            model_path=config["bge_model_path"])
        warmer.query_vector_for_candidate("暖", "机")
        try:
            import torch
            if torch.backends.mps.is_available():
                warmer._adapter._model.to(torch.device("mps"))
                warmer.query_vector_for_candidate("暖", "机")
        except Exception:  # noqa: BLE001
            pass
        rss_model = _rss_mib()

    try:
        ann_index, ann_meta = _load_index(
            config["derived_root"], config["generation_id"], query_search)
    except Exception as error:  # noqa: BLE001
        print("FAIL: usearch sidecar: %s" % error, file=sys.stderr)
        return 2

    machine = build_delta_machine_from_config(config["facts_root"], config)
    full_config = dict(config)
    full_config["ann_index"] = ann_index
    full_config["overfetch"] = overfetch
    full_config["query_search"] = query_search
    service = build_evidence_service_from_config(
        config["facts_root"], full_config, machine=machine)
    control_config = dict(full_config)
    control_config["gamma"] = control_gamma
    control = build_evidence_service_from_config(
        config["facts_root"], control_config, machine=machine)

    class State:
        pass

    state = State()
    state.services = {
        service.config_identity(): service,
        control.config_identity(): control,
    }

    rss_ready = _rss_mib()
    status = {
        "pid": os.getpid(),
        "generation_id": config["generation_id"],
        "ann_backend": ann_meta.get("backend"),
        "config_identity": service.config_identity(),
        "control_identity": control.config_identity(),
        "rss_model_mib": rss_model,
        "rss_ready_mib": rss_ready,
        "event_count": len(ann_index.event_ids()),
        "provider_kind": config.get("provider_kind"),
    }
    if args.status_file:
        with open(args.status_file, "w", encoding="utf-8") as handle:
            json.dump(status, handle, sort_keys=True)
            handle.write("\n")

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(args.socket)
    os.chmod(args.socket, 0o600)
    srv.listen(8)
    srv.settimeout(1.0)
    print("READY %s" % args.socket, flush=True)

    rebuild_thread = None
    if args.rebuild_concurrent:
        build_params = dict(ann_meta.get("build_params") or {})
        fingerprint = ann_meta.get("index_fingerprint")
        rebuild_thread = threading.Thread(
            target=_rebuild_worker,
            args=(config["derived_root"], config["generation_id"],
                  build_params, fingerprint),
            daemon=True)
        rebuild_thread.start()

    try:
        while True:
            try:
                conn, _ignored = srv.accept()
            except socket.timeout:
                continue
            try:
                conn.settimeout(30.0)
                data = read_request(conn, deadline_seconds=30.0)
                if data is not None:
                    try:
                        response = service_handle(state, data)
                    except EvidenceError as error:
                        response = {"version": 2, "error": {
                            "code": error.code, "message": error.message,
                            "phase": "evidence"}}
                    except Exception as error:  # noqa: BLE001
                        response = {"version": 2, "error": {
                            "code": "oracle_fault", "message": str(error),
                            "phase": "evidence"}}
                    conn.sendall(
                        (json.dumps(response, ensure_ascii=False) + "\n")
                        .encode("utf-8"))
            except Exception:  # noqa: BLE001
                pass
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if machine is not None:
            machine.close()
        if os.path.exists(args.socket):
            os.unlink(args.socket)
        if rebuild_thread is not None:
            rebuild_thread.join(30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
