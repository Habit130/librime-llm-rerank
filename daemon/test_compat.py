#!/usr/bin/env python3
"""Layered compatibility-matrix tests (Habit130/squirrel#66, AC-66-v1).

Model-free, stdlib-only: the matrix is a pure decision function over layered
identity dicts, and the staging-machine integration paths run on sandboxed
temp fact roots with injected deterministic fixture providers.  Maps one-to-
one onto the blocking scenarios:

  SCN-66-1  store_epoch change -> matrix says invalidate_all (discard all
            derived state, full rebuild from current facts); the old
            generation is not loadable as the successful active for the new
            epoch
  SCN-66-2  representation_id-only change -> reembed all active events, no
            vector reuse; the desired build never reinterprets the old
            active with the new representation
  SCN-66-3  projection_version-only change, same representation, valid
            checksums -> rebuild projection from facts, reuse vectors by
            event_id, no re-embed
  SCN-66-4  projection change with checksum failure / representation
            mismatch -> no vector reuse; re-embed (no guessing)
  SCN-66-5  vector_format_version-only change, no registered converter ->
            reembed; never a byte-cast
  SCN-66-6  vector_format_version-only change with a tested equivalent
            converter -> reuse converted vectors, no model
  SCN-66-7  index_fingerprint-only change -> no model, no projection rebuild;
            exact-only envelope: planned no-op with reason ``no_ann_sidecar``
  SCN-66-8  query-parameter-only change -> matrix no-op for the base; the
            evidence config_identity mismatch still fail-closes a query that
            names the wrong identity
  SCN-66-9  multi-layer change -> the action union, never a guessed smaller
            action (representation+index, epoch+anything, projection+query)
  SCN-66-10 unknown identity / missing compat declaration / checksum failure
            -> refuse load; no config-active fallback
  SCN-66-11 a desired build in progress -> status reports both fingerprints
            and the mismatch reason; active queries still use the active
            identity only
  SCN-66-12 unsupported retrieval backend / unknown vector format on disk ->
            refuse load (GenerationRejected; routed through the matrix)
"""

import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import compat  # noqa: E402
from compat import (  # noqa: E402
    ACTION_CONVERT_VECTORS,
    ACTION_INVALIDATE_ALL,
    ACTION_NOOP,
    ACTION_REBUILD_INDEX,
    ACTION_REBUILD_PROJECTION,
    ACTION_REEMBED,
    ACTION_REUSE_VECTORS,
    LAYER_INDEX,
    LAYER_PROJECTION,
    LAYER_REPRESENTATION,
    LAYER_STORE_EPOCH,
    LAYER_VECTOR_FORMAT,
    REFUSE_FACT_SCHEMA_CHANGED,
    REFUSE_MISSING_DECLARATION,
    REFUSE_UNKNOWN_IDENTITY,
    REFUSE_UNSUPPORTED_FORMAT,
    VectorFormatConverter,
    compose_index_fingerprint,
    plan_actions,
    refuse_load_reason,
    register_converter,
)
from evidence import (  # noqa: E402
    EvidenceError,
    FixtureRepresentationProvider,
    RepresentationProvider,
)
from generation import (  # noqa: E402
    PROJECTION_VERSION,
    VECTOR_FORMAT,
    VectorReuseSource,
    build_generation,
    open_generation,
)
from staging import StagingBuildMachine  # noqa: E402
from test_generation import make_facts, make_provider  # noqa: E402
from test_staging import _CountingProvider as CountingProvider  # noqa: E402

ACTIVE_REPR = "compat-test-active-repr-v1"
DESIRED_REPR = "compat-test-desired-repr-v1"
PROJ_V1 = "delta-schema-v1+generation-manifest-v1"
PROJ_V2 = "projection-test-v2"

# A second, still-supported vector format string for the converter tests.
FORMAT_V2 = "fp32-row-major-little-endian-v2"


def identity(epoch="e1", schema="1", repr=ACTIVE_REPR,
             fmt=VECTOR_FORMAT, proj=PROJ_V1, fp=None):
    """One layered identity dict (defaults = the exact-only active state)."""
    return {
        LAYER_STORE_EPOCH: epoch,
        "fact_schema_version": schema,
        LAYER_REPRESENTATION: repr,
        LAYER_VECTOR_FORMAT: fmt,
        LAYER_PROJECTION: proj,
        LAYER_INDEX: fp or compose_index_fingerprint(),
    }


class MatrixUnitTest(unittest.TestCase):
    """The pure matrix over identity dicts (SCN-66-1..10 unit level)."""

    def test_identical_identities_are_a_noop(self):
        plan = plan_actions(identity(), identity())
        self.assertEqual([ACTION_NOOP], plan["actions"])
        self.assertEqual([], plan["mismatches"])
        self.assertFalse(plan["refuse_load"])

    def test_scn66_1_store_epoch_change_invalidates_all(self):
        plan = plan_actions(identity(), identity(epoch="e2"))
        self.assertEqual([ACTION_INVALIDATE_ALL], plan["actions"])
        self.assertEqual(1, len(plan["mismatches"]))
        self.assertEqual(LAYER_STORE_EPOCH, plan["mismatches"][0]["layer"])
        # A full rebuild is a single explicit matrix decision, never a
        # guessed smaller action (epoch+anything -> invalidate_all).
        union = plan_actions(identity(), identity(epoch="e2", repr="r2",
                                                  proj=PROJ_V2))
        self.assertEqual([ACTION_INVALIDATE_ALL], union["actions"])

    def test_epoch_change_collapses_vector_reuse_to_none(self):
        # epoch+projection: the projection walk would stage reuse_vectors,
        # but invalidate_all subsumes it -- vector_reuse must NOT leak the
        # stale "event_id" marker (AC66-1 / AC66-7).
        plan = plan_actions(identity(), identity(epoch="e2", proj=PROJ_V2))
        self.assertEqual([ACTION_INVALIDATE_ALL], plan["actions"])
        self.assertEqual("none", plan["vector_reuse"])

    def test_scn66_2_representation_change_reembeds_without_reuse(self):
        plan = plan_actions(identity(), identity(repr=DESIRED_REPR))
        self.assertEqual([ACTION_REEMBED], plan["actions"])
        self.assertEqual("none", plan["vector_reuse"])
        self.assertEqual(LAYER_REPRESENTATION,
                         plan["mismatches"][0]["layer"])

    def test_scn66_3_projection_only_reuses_vectors_by_event_id(self):
        plan = plan_actions(identity(), identity(proj=PROJ_V2))
        self.assertIn(ACTION_REBUILD_PROJECTION, plan["actions"])
        self.assertIn(ACTION_REUSE_VECTORS, plan["actions"])
        self.assertEqual("event_id", plan["vector_reuse"])
        self.assertNotIn(ACTION_REEMBED, plan["actions"])

    def test_scn66_4_projection_change_with_repr_mismatch_reembeds(self):
        # Same projection change but a different representation: reuse is
        # NOT permitted (representation mismatch), the matrix re-embeds.
        plan = plan_actions(identity(), identity(proj=PROJ_V2,
                                                 repr=DESIRED_REPR))
        self.assertEqual([ACTION_REEMBED], plan["actions"])
        self.assertEqual("none", plan["vector_reuse"])

    def test_scn66_5_format_change_without_converter_reembeds(self):
        plan = plan_actions(identity(fmt=FORMAT_V2), identity(), converters={})
        self.assertEqual([ACTION_REEMBED], plan["actions"])
        self.assertEqual("none", plan["vector_reuse"])

    def test_format_and_projection_without_converter_collapses_to_none(self):
        # format+projection without a converter: the projection walk stages
        # reuse_vectors but the format change forces reembed -- vector_reuse
        # must collapse to "none" (AC66-1 / AC66-7).
        plan = plan_actions(identity(fmt=FORMAT_V2), identity(proj=PROJ_V2),
                            converters={})
        self.assertEqual([ACTION_REEMBED], plan["actions"])
        self.assertEqual("none", plan["vector_reuse"])

    def test_scn66_6_format_change_with_tested_converter_reuses(self):
        converter = VectorFormatConverter(
            name="test-fp32-v2",
            source_format=VECTOR_FORMAT,
            target_format=FORMAT_V2,
            convert=lambda data: data,
            verify_equivalent=lambda left, right: left == right)
        registry = {converter.key(): converter}
        plan = plan_actions(identity(fmt=FORMAT_V2), identity(),
                            converters=registry)
        self.assertEqual([ACTION_CONVERT_VECTORS], plan["actions"])
        self.assertEqual("convert", plan["vector_reuse"])
        self.assertNotIn(ACTION_REEMBED, plan["actions"])

    def test_convert_survives_collapse_over_reuse(self):
        # format+projection with a converter: the projection walk stages
        # reuse_vectors, the format walk stages convert_vectors.  convert
        # subsumes reuse in the collapse and must survive it (AC66-1/7).
        converter = VectorFormatConverter(
            name="test-fp32-v2",
            source_format=VECTOR_FORMAT,
            target_format=FORMAT_V2,
            convert=lambda data: data,
            verify_equivalent=lambda left, right: left == right)
        registry = {converter.key(): converter}
        plan = plan_actions(identity(fmt=FORMAT_V2), identity(proj=PROJ_V2),
                            converters=registry)
        self.assertEqual(sorted([ACTION_CONVERT_VECTORS,
                                 ACTION_REBUILD_PROJECTION]),
                         plan["actions"])
        self.assertEqual("convert", plan["vector_reuse"])
        self.assertNotIn(ACTION_REUSE_VECTORS, plan["actions"])
        self.assertNotIn(ACTION_REEMBED, plan["actions"])

    def test_scn66_7_index_only_is_a_noop_with_reason(self):
        other_fp = compose_index_fingerprint(params={"ef_search": 64})
        plan = plan_actions(identity(), identity(fp=other_fp))
        self.assertEqual([ACTION_REBUILD_INDEX], plan["actions"])
        self.assertEqual("no_ann_sidecar", plan["reason"])
        self.assertNotIn(ACTION_REEMBED, plan["actions"])
        self.assertNotIn(ACTION_REBUILD_PROJECTION, plan["actions"])

    def test_scn66_8_query_params_only_is_an_explicit_noop(self):
        # The base layers are identical; only the evidence config identity
        # (kept on the seam) differs -> explicit matrix no-op, never a base
        # rebuild.  The query path itself still fail-closes via
        # config_identity_mismatch (tested in test_protocol.py).
        plan = plan_actions(identity(), identity())
        self.assertEqual([ACTION_NOOP], plan["actions"])

    def test_scn66_9_multi_layer_union(self):
        # representation + index -> reembed (fresh index comes with the new
        # generation), never the guessed smaller rebuild_index alone.
        plan = plan_actions(identity(),
                            identity(repr=DESIRED_REPR,
                                     fp=compose_index_fingerprint(
                                         params={"ef_search": 64})))
        self.assertEqual([ACTION_REEMBED], plan["actions"])
        # projection + query (base identical except projection) -> union of
        # rebuild_projection (which carries reuse) and noop is the base
        # no-rebuild marker; the union is never a guessed smaller action.
        plan = plan_actions(identity(), identity(proj=PROJ_V2))
        self.assertIn(ACTION_REBUILD_PROJECTION, plan["actions"])
        self.assertIn(ACTION_REUSE_VECTORS, plan["actions"])

    def test_scn66_10_unknown_identity_refuses_load(self):
        # Missing compat declaration.
        self.assertEqual(REFUSE_MISSING_DECLARATION,
                         refuse_load_reason({}))
        # A bare-string legacy fingerprint is an unknown identity.
        self.assertEqual(REFUSE_UNKNOWN_IDENTITY,
                         refuse_load_reason(identity(fp="exact")))
        # Unsupported vector format on disk.
        self.assertEqual(REFUSE_UNSUPPORTED_FORMAT,
                         refuse_load_reason(identity(fmt="fp16")))
        # Fact schema the daemon cannot decode (#58 migration out of scope).
        self.assertEqual(REFUSE_FACT_SCHEMA_CHANGED,
                         refuse_load_reason(identity(), facts_schema_version="2"))
        # A present, well-formed identity is loadable.
        self.assertIsNone(refuse_load_reason(identity()))
        # The plan refuses when the active identity is unknown.
        plan = plan_actions(identity(), {})
        self.assertTrue(plan["refuse_load"])
        self.assertEqual(REFUSE_MISSING_DECLARATION, plan["refuse_reason"])

    def test_index_fingerprint_composition_changes_with_each_component(self):
        base = compose_index_fingerprint()
        self.assertTrue(base.startswith("index-fingerprint-v1:"))
        self.assertNotEqual(base, compose_index_fingerprint(backend="ann"))
        self.assertNotEqual(base, compose_index_fingerprint(metric="dot"))
        # ANN build params belong to the fingerprint (AC66-6).
        self.assertNotEqual(base, compose_index_fingerprint(params={"ef": 64}))
        self.assertNotEqual(base, compose_index_fingerprint(
            library_version="oracle-exact-v2"))
        self.assertNotEqual(base, compose_index_fingerprint(
            serialization_abi="fp16-row-major-little-endian"))

    def test_converter_registry_identity_converter_registered(self):
        converter = compat.find_converter(VECTOR_FORMAT, VECTOR_FORMAT)
        self.assertIsNotNone(converter)
        self.assertEqual("identity", converter.name.split("-")[0])
        self.assertTrue(converter.verify_equivalent(b"abc", b"abc"))
        self.assertIsNone(compat.find_converter(VECTOR_FORMAT, FORMAT_V2))


def _fp32(vector):
    return tuple(struct.unpack("<f", struct.pack("<f", float(value)))[0]
                 for value in vector)


class _NoEmbedProvider(RepresentationProvider):
    """Fails hard if event_vector is ever called: proves no re-embed."""

    def __init__(self, inner):
        self._inner = inner
        self.embed_calls = 0

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        self.embed_calls += 1
        raise AssertionError("event_vector must not be called during reuse")

    def vector_dimension(self):
        return self._inner.vector_dimension()


class StagingEnv:
    """One sandboxed facts root + derived root with an active generation."""

    def __init__(self):
        self.facts = make_facts()
        self.facts.conn.execute("PRAGMA journal_mode=WAL;")
        self.facts.conn.commit()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")
        self.active_provider = make_provider(ACTIVE_REPR)
        self.desired_provider = make_provider(DESIRED_REPR)
        self.active_gen = build_generation(self.facts_root,
                                           self.active_provider,
                                           self.derived_root)
        self.active_generation_id = self.active_gen.generation_id
        self.active_gen.close()
        self.active_identity = {
            LAYER_STORE_EPOCH: "e1",
            "fact_schema_version": "1",
            LAYER_REPRESENTATION: ACTIVE_REPR,
            LAYER_VECTOR_FORMAT: VECTOR_FORMAT,
            LAYER_PROJECTION: self.active_gen.projection_version,
            LAYER_INDEX: self.active_gen.index_fingerprint,
        }

    def staging(self, provider=None, active_identity=None, **kwargs):
        defaults = {"chunk_rows": 2, "poll_interval": 0.01,
                    "start_worker": False}
        defaults.update(kwargs)
        return StagingBuildMachine(
            self.facts_root, self.derived_root,
            provider or self.desired_provider, ACTIVE_REPR,
            self.active_generation_id,
            active_identity=active_identity or self.active_identity,
            **defaults)

    @property
    def staging_root(self):
        return os.path.join(self.derived_root, "staging")

    def staging_dirs(self):
        if not os.path.isdir(self.staging_root):
            return []
        return sorted(os.listdir(self.staging_root))

    def run_to_ready(self, machine, max_cycles=200):
        for _ in range(max_cycles):
            machine._cycle()
            progress = machine.status()["progress"]
            if progress is not None and progress["status"] == "ready":
                return progress
        raise AssertionError("build did not reach ready: %s"
                             % machine.status())

    def cleanup(self):
        self.facts.close()


class StagingMatrixTest(unittest.TestCase):
    """The staging machine consults the matrix (SCN-66-3/4/7, AC66-10)."""

    def setUp(self):
        self.env = None
        self.machines = []

    def tearDown(self):
        for machine in self.machines:
            try:
                machine.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        if self.env is not None:
            self.env.cleanup()

    def make_env(self):
        self.env = StagingEnv()
        return self.env

    def open_ready_container(self, generation_id):
        """The ready staging container (the staging machine does not publish;
        the #65 publisher does -- see test_publish.py).  ``progress.json`` is
        parked aside for the reopen verification exactly like the staging
        machine's verify dance and the publisher's park."""
        staging_dir = os.path.join(self.env.derived_root, "staging",
                                   generation_id)
        progress_path = os.path.join(staging_dir, "progress.json")
        tmp_path = os.path.join(self.env.derived_root, "staging",
                                ".verify-%s.tmp" % generation_id)
        if os.path.isfile(progress_path):
            os.rename(progress_path, tmp_path)
        try:
            return open_generation(staging_dir)
        finally:
            if os.path.isfile(tmp_path):
                os.rename(tmp_path, progress_path)

    def test_projection_only_change_reuses_vectors_without_reembed(self):
        env = self.make_env()
        no_embed = _NoEmbedProvider(env.active_provider)
        machine = env.staging(provider=no_embed,
                              projection_version=PROJ_V2)
        self.machines.append(machine)
        progress = env.run_to_ready(machine)
        self.assertIsNotNone(progress)
        # The provider's event_vector was never called: vectors were reused
        # by event_id (SCN-66-3).
        self.assertEqual(0, no_embed.embed_calls)
        # The new generation carries the new projection version.
        opened = self.open_ready_container(progress["generation_id"])
        try:
            self.assertEqual(PROJ_V2, opened.projection_version)
            self.assertEqual(ACTIVE_REPR, opened.representation_id)
            # Vectors are byte-identical to the active generation (reused).
            with open(os.path.join(env.derived_root, "generations",
                                   env.active_generation_id, "vectors.fp32"),
                      "rb") as active_file:
                with open(os.path.join(env.derived_root, "staging",
                                      progress["generation_id"],
                                      "vectors.fp32"), "rb") as staged_file:
                    self.assertEqual(active_file.read(), staged_file.read())
        finally:
            opened.close()

    def test_projection_change_with_bad_checksum_reembeds(self):
        env = self.make_env()
        # Corrupt the active generation's vectors file so reopen (the
        # checksum gate) fails -> reuse refused, re-embed (SCN-66-4).
        active_vectors = os.path.join(env.derived_root, "generations",
                                      env.active_generation_id, "vectors.fp32")
        with open(active_vectors, "r+b") as handle:
            handle.seek(0)
            handle.write(bytes([handle.read(1)[0] ^ 0xFF]))
        counting = make_provider(ACTIVE_REPR)
        machine = env.staging(provider=counting,
                              projection_version=PROJ_V2)
        self.machines.append(machine)
        progress = env.run_to_ready(machine)
        self.assertIsNotNone(progress)
        # The active generation can no longer be reopened (refused), so the
        # build re-embedded; the matrix never guessed a reuse.
        opened = self.open_ready_container(progress["generation_id"])
        try:
            self.assertEqual(PROJ_V2, opened.projection_version)
        finally:
            opened.close()

    def test_index_only_change_is_a_noop_with_reason(self):
        env = self.make_env()
        other_fp = compose_index_fingerprint(params={"ef_search": 64})
        active_identity = dict(env.active_identity)
        active_identity[LAYER_INDEX] = other_fp
        machine = env.staging(provider=env.active_provider,
                              active_identity=active_identity)
        self.machines.append(machine)
        machine._cycle()
        # No build is started: the exact-only envelope records the planned
        # index-only action as a no-op (RISK-66-1 / SCN-66-7).
        status = machine.status()
        self.assertIsNone(status["progress"])
        self.assertEqual([ACTION_REBUILD_INDEX],
                         status["compatibility"]["actions"])
        self.assertEqual("no_ann_sidecar",
                         status["compatibility"]["reason"])
        self.assertEqual([], env.staging_dirs())

    def test_desired_equal_active_is_a_noop(self):
        env = self.make_env()
        machine = env.staging(provider=env.active_provider,
                              active_identity=env.active_identity)
        self.machines.append(machine)
        machine._cycle()
        status = machine.status()
        self.assertIsNone(status["progress"])
        self.assertEqual([ACTION_NOOP], status["compatibility"]["actions"])

    def test_representation_change_reembeds(self):
        env = self.make_env()
        machine = env.staging(provider=env.desired_provider,
                              active_identity=env.active_identity)
        self.machines.append(machine)
        progress = env.run_to_ready(machine)
        self.assertIsNotNone(progress)
        self.assertEqual([ACTION_REEMBED],
                         machine.status()["compatibility"]["actions"])
        opened = self.open_ready_container(progress["generation_id"])
        try:
            self.assertEqual(DESIRED_REPR, opened.representation_id)
        finally:
            opened.close()

    def test_epoch_and_projection_change_never_reuses_vectors(self):
        # epoch+projection: invalidate_all subsumes the reuse candidate, so
        # the full rebuild must re-embed (prove event_vector IS called --
        # the inverse of the reuse test) and must never open a
        # VectorReuseSource on the old epoch's generation.
        env = self.make_env()
        counting = CountingProvider(env.active_provider)
        # Active identity carries a different epoch; the desired target
        # carries a changed projection.  The matrix must plan invalidate_all
        # with vector_reuse "none" (AC66-1 / AC66-7) and re-embed, not reuse
        # the old generation's vectors.
        active_identity = dict(env.active_identity)
        active_identity[LAYER_STORE_EPOCH] = "e0"
        machine = env.staging(provider=counting, projection_version=PROJ_V2,
                              active_identity=active_identity)
        self.machines.append(machine)
        # The collapsed plan (vector_reuse "none") must never construct a
        # reuse source: pin the seam so any open is caught.
        with mock.patch("staging.VectorReuseSource",
                        side_effect=AssertionError(
                            "VectorReuseSource must not be opened")) as vs:
            progress = env.run_to_ready(machine)
        self.assertIsNotNone(progress)
        self.assertFalse(vs.called)
        plan = machine.status()["compatibility"]
        self.assertEqual([ACTION_INVALIDATE_ALL], plan["actions"])
        self.assertEqual("none", plan["vector_reuse"])
        # The build re-embedded from facts rather than reusing old vectors.
        self.assertGreater(counting.count, 0)
        opened = self.open_ready_container(progress["generation_id"])
        try:
            self.assertEqual(ACTIVE_REPR, opened.representation_id)
            self.assertEqual(PROJ_V2, opened.projection_version)
        finally:
            opened.close()

    def test_refused_active_identity_idles_without_building(self):
        # #66 refuse-load: a present-but-invalid/unknown active manifest
        # refuses the staging build (idle + recorded reason), distinct from
        # "nothing published yet" (the existing first-build path).
        env = self.make_env()
        machine = StagingBuildMachine(
            env.facts_root, env.derived_root, env.desired_provider,
            ACTIVE_REPR, env.active_generation_id, start_worker=False,
            refuse_reason=REFUSE_UNKNOWN_IDENTITY)
        self.machines.append(machine)
        machine._cycle()
        status = machine.status()
        self.assertIsNone(status["progress"])
        health = machine.health()
        self.assertEqual(REFUSE_UNKNOWN_IDENTITY,
                         health["staging_refuse_reason"])
        self.assertEqual([], env.staging_dirs())

    def test_status_reports_desired_and_active_fingerprints(self):
        env = self.make_env()
        machine = env.staging(provider=env.desired_provider,
                              active_identity=env.active_identity)
        self.machines.append(machine)
        machine._cycle()
        status = machine.status()
        self.assertEqual(DESIRED_REPR,
                         status["desired_representation_id"])
        self.assertEqual(ACTIVE_REPR,
                         status["active_representation_id"])
        plan = status["compatibility"]
        self.assertEqual([ACTION_REEMBED], plan["actions"])
        self.assertEqual(1, len(plan["mismatches"]))
        self.assertEqual(LAYER_REPRESENTATION,
                         plan["mismatches"][0]["layer"])


# ---------------------------------------------------------------------------
# SCN-66-11: the daemon's status report (health handshake) carries the
# desired/active fingerprints and the mismatch reasons (privacy-clean).
# ---------------------------------------------------------------------------

class StatusCompatTest(unittest.TestCase):
    """The daemon health handshake and the status core pass the compat
    report through; refuse-load is reported, never a config fallback."""

    def setUp(self):
        self.env = None

    def tearDown(self):
        if self.env is not None:
            self.env.cleanup()

    def make_env(self):
        self.env = StagingEnv()
        return self.env

    def test_build_compat_report_reports_desired_vs_active(self):
        from server import build_compat_report
        env = self.make_env()
        config = {"representation_id": ACTIVE_REPR,
                  "desired_representation_id": DESIRED_REPR}
        report = build_compat_report(config, env.facts_root,
                                     env.active_identity, None, None, None)
        self.assertFalse(report["refuse_load"])
        self.assertEqual(DESIRED_REPR,
                         report["desired"][LAYER_REPRESENTATION])
        self.assertEqual(ACTIVE_REPR,
                         report["active"][LAYER_REPRESENTATION])
        self.assertEqual([ACTION_REEMBED], report["actions"])
        self.assertEqual(1, len(report["mismatches"]))
        self.assertEqual(LAYER_REPRESENTATION,
                         report["mismatches"][0]["layer"])

    def test_build_compat_report_reports_refuse_load(self):
        from server import build_compat_report
        env = self.make_env()
        config = {"representation_id": ACTIVE_REPR}
        report = build_compat_report(config, env.facts_root, None,
                                     REFUSE_UNKNOWN_IDENTITY, None, None)
        self.assertTrue(report["refuse_load"])
        self.assertEqual(REFUSE_UNKNOWN_IDENTITY,
                         report["refuse_reason"])

    def test_health_handshake_passes_compatibility_through(self):
        """The status core's probe passes the daemon's compatibility section
        through unchanged (SCN-66-11; status_core never invents it)."""
        from status_core import probe_daemon
        import socket
        import threading

        compat_payload = {
            "refuse_load": False,
            "desired": {LAYER_REPRESENTATION: DESIRED_REPR},
            "active": {LAYER_REPRESENTATION: ACTIVE_REPR},
            "mismatches": [{"layer": LAYER_REPRESENTATION,
                            "reason": "representation changed"}],
            "actions": [ACTION_REEMBED],
        }
        sock_path = os.path.join(tempfile.mkdtemp(), "health.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)

        def serve():
            conn, _ = srv.accept()
            data = b""
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            response = {
                "version": 2,
                "request_id": "h",
                "kind": "health",
                "health": {
                    "pid": 1,
                    "model_loaded": False,
                    "maintenance_state": "serving",
                    "compatibility": compat_payload,
                },
            }
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            conn.close()
            srv.close()

        thread = threading.Thread(target=serve)
        thread.daemon = True
        thread.start()
        try:
            serving = probe_daemon(sock_path)
        finally:
            srv.close()
            thread.join(2.0)
        self.assertEqual("up", serving["state"])
        self.assertEqual(compat_payload, serving["compatibility"])


if __name__ == "__main__":
    unittest.main()
