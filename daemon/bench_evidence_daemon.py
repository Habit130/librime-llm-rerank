#!/usr/bin/env python3
"""#71 capacity-benchmark evidence daemon.

Serves the retrieval-evidence protocol over a unix socket from one #71
fixture facts root + its built generation + a delta state machine, exactly
the production daemon wiring (server.py run_server) but pointed at the
disposable fixture roots and a fixed-seed representation, and without the
maintenance coordinator (the bench has no backup/restore/clear).  The
socket parent dir must be 0700 (control-path invariant), so the caller
passes a dedicated bench root.

Optional ``--staging-config`` (S4 scenario): also starts the staging build
machine with a desired representation different from the active one, so
the background-rebuild concurrency measurement runs the real staging
machinery (chunked embedding) while the delta machine serves queries.

Usage:
    python3 daemon/bench_evidence_daemon.py \
        --facts-root <fixture facts root> \
        --derived-root <built generation root> \
        --socket <path under a 0700 dir> \
        --seed 20260817 --dimension 1024 \
        --representation-id seed-fixture-v1:1024 \
        [--staging-config <json with desired_representation_id/desired_seed>]
"""

import argparse
import json
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from control import validate_control_path  # noqa: E402
from delta import build_delta_machine_from_config  # noqa: E402
from evidence import (EVIDENCE_KIND, EvidenceError,  # noqa: E402
                      build_evidence_service_from_config)
from server import read_request  # noqa: E402


def _evidence_config(facts_root, derived_root, representation_id, seed,
                     dimension, backend="exact"):
    return {
        "provider_kind": "seed_vectors",
        "representation_id": representation_id,
        "seed": seed,
        "vector_dimension": dimension,
        "derived_root": derived_root,
        "generation_id": None,  # resolved from the active manifest below
        "retrieval_backend": backend,
        "tau": 0.4,
        "k_evidence": 8,
        "half_life": 32.0,
        "saturation_k": 2.0,
        "gamma": 2.0,
        "catch_up_deadline_ms": 5000,
        "poll_interval_ms": 500,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts-root", required=True)
    parser.add_argument("--derived-root", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--representation-id", required=True)
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--dimension", type=int, default=1024)
    parser.add_argument("--backend", default="exact",
                        choices=("exact", "accelerate-cblas-sgemv"),
                        help="exact retrieval backend: the #71 python oracle "
                             "or the #72 Apple vecLib Accelerate path")
    parser.add_argument("--staging-config", default=None,
                        help="JSON file with desired_representation_id / "
                             "desired_seed for the S4 rebuild scenario")
    args = parser.parse_args()

    validate_control_path(args.socket)

    from publish import read_active_manifest
    manifest, _reason = read_active_manifest(args.derived_root)
    if manifest is None:
        print("FAIL: no active manifest under %s" % args.derived_root,
              file=sys.stderr)
        return 2
    config = _evidence_config(args.facts_root, args.derived_root,
                              args.representation_id, args.seed,
                              args.dimension, backend=args.backend)
    config["generation_id"] = manifest["generation_id"]
    config["representation_id"] = manifest["representation_id"]

    machine = build_delta_machine_from_config(args.facts_root, config)
    service = build_evidence_service_from_config(
        args.facts_root, config, machine=machine)

    staging_machine = None
    if args.staging_config:
        with open(args.staging_config, encoding="utf-8") as handle:
            staging_cfg = json.load(handle)
        staging_cfg["derived_root"] = args.derived_root
        staging_cfg["generation_id"] = manifest["generation_id"]
        staging_cfg["representation_id"] = manifest["representation_id"]
        from staging import build_staging_machine_from_config
        staging_machine = build_staging_machine_from_config(
            args.facts_root, staging_cfg,
            active_generation_id=manifest["generation_id"],
            active_representation_id=manifest["representation_id"])

    class State:
        pass

    state = State()
    state.evidence_service = service

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(args.socket)
    os.chmod(args.socket, 0o600)
    srv.listen(8)
    srv.settimeout(1.0)
    # #72 warm-up: when serving the Accelerate backend, construct the cosine
    # engine once BEFORE the measurement window so the one-time per-row norm
    # precomputation (~40 ms at 100k rows) never lands inside a measured
    # request (spec: model-warm windows; the bench client's first S1 request
    # must not pay the engine's construction cost).
    if args.backend != "exact" and machine is not None:
        try:
            snapshot = machine.ensure_caught_up()
            engine = snapshot.accelerate_engine()
            # Touch the matrix once (one real sgemv over a >threshold batch)
            # so the first measured request never pays the one-time cold-
            # matrix / vecLib warm cost (~150 ms at 100k x 1024).  The probe
            # vector is synthetic and its result is discarded; nothing here
            # touches live data.  The batch must exceed the engine's Python
            # path threshold to force the sgemv branch.
            from accelerate import PYTHON_PATH_THRESHOLD
            if len(snapshot.active_events) >= PYTHON_PATH_THRESHOLD:
                probe_ids = tuple(
                    event.event_id
                    for event in snapshot.active_events[:PYTHON_PATH_THRESHOLD * 2])
                engine.batch_cosines(
                    [1.0] * snapshot.vector_dimension, probe_ids,
                    snapshot.vector_for)
        except Exception as error:  # noqa: BLE001 - fail closed at startup
            print("FAIL: Accelerate engine warm-up: %s" % error,
                  file=sys.stderr)
            machine.close()
            srv.close()
            if os.path.exists(args.socket):
                os.unlink(args.socket)
            return 2
    print("READY %s" % args.socket, flush=True)

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            try:
                conn.settimeout(5.0)
                data = read_request(conn)
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
            except Exception:  # noqa: BLE001 - transport best effort
                pass
            finally:
                conn.close()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if machine is not None:
            machine.close()
        if staging_machine is not None:
            staging_machine.close()
        if os.path.exists(args.socket):
            os.unlink(args.socket)
    return 0


def service_handle(state, data):
    """Route one framed evidence request (mirrors server.handle_evidence_request
    minus the coordinator lease; the bench daemon has no maintenance)."""
    from server import (EVIDENCE_FIELDS, PROTOCOL_VERSION,  # noqa: E402
                        handle_evidence_request)
    try:
        req = json.loads(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"version": 2, "error": {"code": "invalid_json"}}
    if (not isinstance(req, dict) or set(req) != EVIDENCE_FIELDS
            or req.get("kind") != EVIDENCE_KIND
            or req.get("version") != PROTOCOL_VERSION):
        return {"version": 2, "error": {"code": "invalid_request"}}
    service = getattr(state, "evidence_service", None)
    if service is None:
        return {"version": 2, "error": {"code": "evidence_unavailable"}}
    if req["config_identity"] != service.config_identity():
        return {"version": 2, "error": {
            "code": "config_identity_mismatch"}}
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


if __name__ == "__main__":
    sys.exit(main())
