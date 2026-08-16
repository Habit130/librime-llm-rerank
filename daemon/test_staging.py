#!/usr/bin/env python3
"""Resumable staging generation build tests (Habit130/squirrel#64, AC-64-v1).

Model-free, stdlib-only, sandboxed temp fact roots + derived roots and
injected deterministic representation fixtures -- never real private
history.  The suite maps one-to-one onto the frozen delivery contract:

  AC64-1  the staging fixes the target epoch, H0, all fingerprints, the
          builder version and the deterministic event list (identity test)
  AC64-2  every chunk record is real (row range / event count / checksum)
          and the progress manifest advances atomically (SCN-64-1)
  AC64-3  restart resume gate: epoch / H0 / fingerprints / builder version
          must all match, else no resume (SCN-64-3)
  AC64-4  target identity or epoch change discards the staging; no
          continuation, no partial reuse (SCN-64-4)
  AC64-5  deterministic parse/model errors block with the event id named;
          nothing is silently skipped (SCN-64-5)
  AC64-6  transient interruption resumes from the last verified chunk;
          completed chunks are never re-embedded (SCN-64-2)
  AC64-7  the current healthy generation keeps serving per its own
          identity and absorbs delta during the whole build; queries never
          drive build retries (SCN-64-6/7)

Machines are driven cycle-by-cycle (``start_worker=False``) so crashes and
restarts are deterministic; two end-to-end tests run the real worker thread.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from staging import (  # noqa: E402
    STAGING_PROGRESS_VERSION,
    StagingBuildMachine,
    StagingError,
    build_staging_machine_from_config,
)
from delta import DeltaStateMachine  # noqa: E402
from evidence import (  # noqa: E402
    EvidenceError,
    EvidenceService,
    RepresentationProvider,
)
from generation import (  # noqa: E402
    BUILD_VERSION,
    GENERATION_FILES,
    PROGRESS_FILENAME,
    _canonical_json,
    _verify_progress_chunks,
    _write_atomic,
    build_generation,
)
from oracle import OracleParams  # noqa: E402
from test_generation import make_facts, make_provider  # noqa: E402
from test_oracle import FactsFixture  # noqa: E402

ACTIVE_REPR = "staging-test-active-repr-v1"
DESIRED_REPR = "staging-test-desired-repr-v1"
ACTIVE_ID = "shadow-gen-v1:active-test-id-0000000000000000000000000000"
PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)

SECRET_PRECEDING = "机密上文内容绝对不许进容器"


class _CountingProvider(RepresentationProvider):
    """Wraps a fixture, counts event_vector calls and can fail on demand."""

    def __init__(self, inner, fail_event=None, fail_exc=None,
                 record_lock=False, lock=None):
        self._inner = inner
        self.fail_event = fail_event
        self.fail_exc = fail_exc
        self.calls = []
        self.lock_held = []
        self._lock = lock
        self._record_lock = record_lock

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        if self._lock is not None and self._record_lock:
            self.lock_held.append(self._lock.locked())
        if event.event_id == self.fail_event:
            if isinstance(self.fail_exc, EvidenceError):
                raise self.fail_exc
            raise self.fail_exc()
        self.calls.append(event.event_id)
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()

    @property
    def count(self):
        return len(self.calls)

    @property
    def event_ids(self):
        return list(self.calls)


def make_machine(facts_root, derived_root, desired_repr=DESIRED_REPR,
                 active_repr=ACTIVE_REPR, active_id=ACTIVE_ID,
                 chunk_rows=2, provider=None, builder_lock=None,
                 poll_interval=0.01):
    provider = provider or make_provider(desired_repr)
    return StagingBuildMachine(
        facts_root, derived_root, provider, active_repr, active_id,
        chunk_rows=chunk_rows, poll_interval=poll_interval,
        start_worker=False, builder_lock=builder_lock)


class StagingEnv:
    """One sandboxed facts root + derived root."""

    def __init__(self, facts=None):
        self.facts = facts or make_facts()
        self.facts.conn.execute("PRAGMA journal_mode=WAL;")
        self.facts.conn.execute(
            "UPDATE meta SET value = value WHERE key = 'store_epoch';")
        self.facts.conn.commit()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")

    @property
    def staging_root(self):
        return os.path.join(self.derived_root, "staging")

    def staging_dirs(self):
        if not os.path.isdir(self.staging_root):
            return []
        return sorted(os.listdir(self.staging_root))

    def progress(self, generation_id):
        path = os.path.join(self.staging_root, generation_id,
                            PROGRESS_FILENAME)
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def write_progress(self, generation_id, progress):
        path = os.path.join(self.staging_root, generation_id,
                            PROGRESS_FILENAME)
        _write_atomic(path, _canonical_json(progress).encode("utf-8"))

    def cleanup(self):
        self.facts.close()


class EnvTest(unittest.TestCase):
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

    def make_env(self, **kwargs):
        self.env = StagingEnv(**kwargs)
        return self.env

    def machine(self, *args, **kwargs):
        machine = make_machine(self.env.facts_root, self.env.derived_root,
                               *args, **kwargs)
        self.machines.append(machine)
        return machine

    def run_to_ready(self, machine, max_cycles=50):
        for _ in range(max_cycles):
            machine._cycle()
            progress = machine.status()["progress"]
            if progress is not None and progress["status"] == "ready":
                return progress
        self.fail("build did not reach ready: %s"
                  % machine.status()["last_error"])


class StagingLifecycleTest(EnvTest):
    """Fix the target, chunk honestly, finish verified, never publish."""

    def test_builds_when_desired_differs_from_active(self):
        env = self.make_env()
        machine = self.machine()
        progress = self.run_to_ready(machine)
        self.assertEqual("ready", progress["status"])
        self.assertEqual(6, progress["total_rows"])
        self.assertEqual(1, len(env.staging_dirs()))
        # The staging is complete but NOT published: publish is #65.  The
        # "ready" mark is only written after the full reopen
        # self-verification (the verification dance) passed.
        published = os.path.join(env.derived_root, "generations")
        self.assertTrue(not os.path.exists(published)
                        or os.listdir(published) == [])

    def test_no_build_when_desired_matches_active(self):
        env = self.make_env()
        machine = self.machine(desired_repr=ACTIVE_REPR)
        machine._cycle()
        self.assertEqual([], env.staging_dirs())
        # The target is derived every cycle; the desired==active gate
        # simply never starts a build.
        self.assertIsNone(machine.status()["progress"])

    def test_no_build_for_the_declared_active_id(self):
        env = self.make_env()
        probe = self.machine()
        probe._cycle()
        target_id = probe.status()["target_generation_id"]
        self.assertTrue(target_id)
        machine2 = self.machine(active_id=target_id)
        machine2._cycle()
        # The target equals the declared active id: never build; the
        # leftover staging of the same target is obsolete.
        self.assertEqual("discarded", env.progress(target_id)["status"])
        self.assertIsNone(machine2.status()["progress"])

    def test_ready_staging_is_byte_identical_to_build_generation(self):
        env = self.make_env()
        machine = self.machine()
        progress = self.run_to_ready(machine)
        direct_root = tempfile.mkdtemp(prefix="staging_direct_")
        try:
            provider = make_provider(DESIRED_REPR)
            gen = build_generation(env.facts_root, provider, direct_root,
                                   chunk_rows=2)
            self.assertEqual(progress["generation_id"], gen.generation_id)
            for name in GENERATION_FILES:
                with open(os.path.join(env.staging_root,
                                       progress["generation_id"], name),
                          "rb") as staged:
                    with open(os.path.join(direct_root, "generations",
                                           gen.generation_id, name),
                              "rb") as direct:
                        self.assertEqual(staged.read(), direct.read(), name)
            gen.close()
        finally:
            shutil.rmtree(direct_root, ignore_errors=True)

    def test_progress_fixes_epoch_hlc_fingerprints_and_builder(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()  # one chunk in
        progress = env.progress(machine.status()["target_generation_id"])
        self.assertEqual(STAGING_PROGRESS_VERSION,
                         progress["progress_version"])
        self.assertEqual("e1", progress["identity"]["store_epoch"])
        self.assertEqual([1000000, 6], progress["identity"]["source_hlc"])
        self.assertEqual(DESIRED_REPR,
                         progress["identity"]["representation_id"])
        self.assertEqual(BUILD_VERSION,
                         progress["identity"]["builder_version"])
        self.assertEqual(4, progress["identity"]["vector_dimension"])
        self.assertEqual(6, progress["total_rows"])
        self.assertTrue(progress["rows_fingerprint"])
        # The recorded fingerprint must match the final manifest's rows
        # fingerprint (the deterministic event list is pinned, AC64-1).
        direct_root = os.path.join(env.facts_root, "direct")
        provider = make_provider(DESIRED_REPR)
        gen = build_generation(env.facts_root, provider, direct_root)
        with open(os.path.join(direct_root, "generations",
                               gen.generation_id, "manifest.json"),
                  encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["rows"]["fingerprint"],
                         progress["rows_fingerprint"])
        gen.close()

    def test_chunk_records_are_real(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()  # start
        for _ in range(3):
            machine._cycle()
        progress = machine.status()["progress"]
        self.assertEqual(3, len(progress["chunks"]))
        expected = [{"start_row": 0, "end_row": 2},
                    {"start_row": 2, "end_row": 4},
                    {"start_row": 4, "end_row": 6}]
        self.assertEqual(expected, [
            {"start_row": c["start_row"], "end_row": c["end_row"]}
            for c in progress["chunks"]])
        for chunk in progress["chunks"]:
            self.assertEqual(2 * 4 * 4, chunk["bytes"])
            self.assertTrue(chunk["sha256"])
        # Every recorded checksum matches the real bytes on disk.
        vectors_path = os.path.join(env.staging_root,
                                    progress["generation_id"],
                                    "vectors.fp32")
        with open(vectors_path, "rb") as handle:
            for chunk in progress["chunks"]:
                handle.seek(chunk["start_row"] * 4 * 4)
                data = handle.read(chunk["bytes"])
                self.assertEqual(chunk["sha256"],
                                 hashlib.sha256(data).hexdigest(), chunk)
        # The recorded chunks re-verify against the file at every point
        # (progress manifest 原子推进, SCN-64-1).
        next_row, _ = _verify_progress_chunks(progress, vectors_path, 4)
        self.assertEqual(6, next_row)

    def test_progress_advances_atomically_per_chunk(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()  # start (no chunks yet)
        seen = []
        for _ in range(3):
            machine._cycle()
            progress = machine.status()["progress"]
            seen.append((len(progress["chunks"]), progress["status"]))
            with open(os.path.join(env.staging_root,
                                   progress["generation_id"],
                                   PROGRESS_FILENAME),
                      encoding="utf-8") as handle:
                json.load(handle)  # must always parse
        self.assertEqual([(1, "running"), (2, "running"), (3, "running")],
                         seen)

    def test_empty_store_builds_a_ready_empty_staging(self):
        env = self.make_env(facts=FactsFixture())
        machine = self.machine()
        progress = self.run_to_ready(machine)
        self.assertEqual(0, progress["total_rows"])
        self.assertEqual([], progress["chunks"])
        with open(os.path.join(env.staging_root, progress["generation_id"],
                               "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(0, manifest["rows"]["count"])
        self.assertEqual([], manifest["chunks"])
        self.assertEqual(0, manifest["files"]["vectors.fp32"]["size"])

    def test_missing_facts_idle(self):
        env = self.make_env(facts=FactsFixture())
        facts_root = os.path.join(env.facts_root, "gone")
        machine = make_machine(facts_root, env.derived_root)
        self.machines.append(machine)
        machine._cycle()
        self.assertEqual([], env.staging_dirs())

    def test_already_published_target_needs_no_build(self):
        env = self.make_env()
        provider = make_provider(DESIRED_REPR)
        gen = build_generation(env.facts_root, provider, env.derived_root)
        gen.close()
        machine = self.machine()
        machine._cycle()
        self.assertEqual([], env.staging_dirs())
        self.assertIsNone(machine.status()["progress"])

    def test_staging_never_contains_raw_preceding_text(self):
        env = self.make_env()
        machine = self.machine()
        progress = self.run_to_ready(machine)
        for name in GENERATION_FILES:
            path = os.path.join(env.staging_root, progress["generation_id"],
                                name)
            with open(path, "rb") as handle:
                content = handle.read()
            self.assertNotIn(SECRET_PRECEDING.encode("utf-8"), content)

    def test_status_reports_desired_and_active(self):
        env = self.make_env()
        machine = self.machine()
        status = machine.status()
        self.assertEqual(DESIRED_REPR, status["desired_representation_id"])
        self.assertEqual(ACTIVE_REPR, status["active_representation_id"])
        self.assertEqual(ACTIVE_ID, status["active_generation_id"])

    def test_retarget_validates_the_provider(self):
        env = self.make_env()
        machine = self.machine()
        with self.assertRaises(StagingError):
            machine.retarget(object())


class ResumeTest(EnvTest):
    """Transient interruption resumes from the last verified chunk."""

    def test_interrupted_build_resumes_and_is_bit_identical(self):
        env = self.make_env()
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine = self.machine(provider=counting)
        machine._cycle()  # start: fix the target
        machine._cycle()  # chunk 0-1 committed
        self.assertEqual(["e1", "e2"], counting.event_ids)
        machine.close()  # "crash": progress is on disk, worker is gone

        # Fresh machine over the same roots: resumes at row 2 and embeds
        # only the remaining events (SCN-64-2: 已完成块不重嵌入).
        counting2 = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting2)
        self.machines.append(machine2)
        progress = self.run_to_ready(machine2)
        self.assertEqual(["e3", "e4", "e5", "e6"], counting2.event_ids)
        self.assertEqual(3, len(progress["chunks"]))

        # The resumed build is byte-identical to an uninterrupted one.
        uninterrupted_root = tempfile.mkdtemp(prefix="staging_plain_")
        try:
            gen = build_generation(env.facts_root,
                                   make_provider(DESIRED_REPR),
                                   uninterrupted_root, chunk_rows=2)
            self.assertEqual(progress["generation_id"], gen.generation_id)
            for name in GENERATION_FILES:
                with open(os.path.join(env.staging_root,
                                       progress["generation_id"], name),
                          "rb") as staged:
                    with open(os.path.join(uninterrupted_root, "generations",
                                           gen.generation_id, name),
                              "rb") as plain:
                        self.assertEqual(staged.read(), plain.read(), name)
            gen.close()
        finally:
            shutil.rmtree(uninterrupted_root, ignore_errors=True)

    def test_facts_advanced_mid_build_keeps_fixed_H0(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()  # start pins H0 over the 6 events
        env.facts.add_event("e9", segment_input="shijie", selection="世界",
                            preceding_text="后来的上文",
                            competition=("世界", "时界"))
        progress = self.run_to_ready(machine)
        # The staging stays pinned at H0: 6 rows, not 7.
        self.assertEqual(6, progress["total_rows"])
        with open(os.path.join(env.staging_root, progress["generation_id"],
                               "metadata.json"), encoding="utf-8") as handle:
            metadata = json.load(handle)
        self.assertEqual(["e1", "e2", "e3", "e4", "e5", "e6"],
                         [row["event_id"] for row in metadata])

    def test_restart_gate_epoch_mismatch_discards(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        generation_id = machine.status()["target_generation_id"]
        progress = env.progress(generation_id)
        progress["identity"]["store_epoch"] = "e-tampered"
        env.write_progress(generation_id, progress)
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # invalidate the stale record, start fresh
        machine2._cycle()  # fresh build embeds chunk 0-1
        # Fresh build for the same target: chunks start over from row 0.
        self.assertEqual(["e1", "e2"], counting.event_ids)
        self.assertEqual("e1", env.progress(
            machine2.status()["target_generation_id"])["identity"]
            ["store_epoch"])

    def test_restart_gate_hlc_mismatch_discards(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        generation_id = machine.status()["target_generation_id"]
        progress = env.progress(generation_id)
        progress["identity"]["source_hlc"] = [999999, 0]
        env.write_progress(generation_id, progress)
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # invalidate the stale record, start fresh
        machine2._cycle()  # fresh build embeds chunk 0-1
        self.assertEqual(["e1", "e2"], counting.event_ids)
        self.assertIn("no longer match", machine2.status()
                      ["last_discard_reason"])

    def test_restart_gate_rows_fingerprint_mismatch_discards(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        generation_id = machine.status()["target_generation_id"]
        progress = env.progress(generation_id)
        progress["rows_fingerprint"] = "deadbeef" * 8
        env.write_progress(generation_id, progress)
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # invalidate the stale record, start fresh
        machine2._cycle()  # fresh build embeds chunk 0-1
        self.assertEqual(["e1", "e2"], counting.event_ids)
        self.assertIn("fingerprint", machine2.status()
                      ["last_discard_reason"])

    def test_restart_gate_builder_version_mismatch_discards(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        generation_id = machine.status()["target_generation_id"]
        progress = env.progress(generation_id)
        progress["identity"]["builder_version"] = "shadow-generation-" \
            "builder-v0"
        env.write_progress(generation_id, progress)
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # invalidate the stale record, start fresh
        machine2._cycle()  # fresh build embeds chunk 0-1
        self.assertEqual(["e1", "e2"], counting.event_ids)

    def test_restart_gate_representation_mismatch_discards(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        generation_id = machine.status()["target_generation_id"]
        progress = env.progress(generation_id)
        progress["identity"]["representation_id"] = "another-repr-v1"
        env.write_progress(generation_id, progress)
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # invalidate the stale record, start fresh
        machine2._cycle()  # fresh build embeds chunk 0-1
        self.assertEqual(["e1", "e2"], counting.event_ids)
        self.assertIn("changed", machine2.status()["last_discard_reason"])

    def test_restart_gate_all_elements_match_resumes(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()  # start
        machine._cycle()  # chunk 1 only
        machine.close()
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        progress = self.run_to_ready(machine2)
        self.assertEqual(["e3", "e4", "e5", "e6"], counting.event_ids)
        self.assertEqual(3, len(progress["chunks"]))

    def test_epoch_change_mid_build_discards_and_rebuilds(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        old_id = machine.status()["target_generation_id"]
        env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        env.facts.conn.commit()
        machine._cycle()
        self.assertEqual("discarded", env.progress(old_id)["status"])
        new_id = machine.status()["target_generation_id"]
        self.assertNotEqual(old_id, new_id)
        self.assertEqual("e2", env.progress(new_id)["identity"]
                         ["store_epoch"])
        self.assertEqual("running", env.progress(new_id)["status"])

    def test_epoch_change_never_reuses_old_chunks(self):
        env = self.make_env()
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine = self.machine(provider=counting)
        machine._cycle()  # start
        machine._cycle()  # chunk 0-1 embedded for the old epoch
        env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        env.facts.conn.commit()
        counting2 = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting2)
        self.machines.append(machine2)
        machine2._cycle()  # discard the old staging, start fresh
        machine2._cycle()  # the fresh build embeds from row 0 again
        self.assertEqual(["e1", "e2"], counting2.event_ids)

    def test_retarget_mid_build_discards_and_rebuilds(self):
        env = self.make_env()
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine = self.machine(provider=counting)
        machine._cycle()
        old_id = machine.status()["target_generation_id"]
        machine.retarget(make_provider("staging-test-desired-v2"))
        machine._cycle()
        self.assertEqual("discarded", env.progress(old_id)["status"])
        new_id = machine.status()["target_generation_id"]
        self.assertNotEqual(old_id, new_id)
        self.assertEqual("staging-test-desired-v2",
                         env.progress(new_id)["identity"]
                         ["representation_id"])
        self.assertEqual("running", env.progress(new_id)["status"])

    def test_crash_after_metadata_write_resumes_to_ready(self):
        env = self.make_env()
        machine = self.machine()
        progress = self.run_to_ready(machine)
        generation_id = progress["generation_id"]
        staging_dir = os.path.join(env.staging_root, generation_id)
        # Simulate a crash between metadata and manifest: manifest missing,
        # progress rolled back to running.
        os.remove(os.path.join(staging_dir, "manifest.json"))
        record = env.progress(generation_id)
        record["status"] = "running"
        env.write_progress(generation_id, record)
        machine2 = make_machine(env.facts_root, env.derived_root)
        self.machines.append(machine2)
        progress = self.run_to_ready(machine2)
        self.assertEqual("ready", progress["status"])
        self.assertEqual(3, len(progress["chunks"]))

    def test_corrupt_recorded_chunk_discards(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        machine._cycle()  # chunk 0-1 committed
        generation_id = machine.status()["target_generation_id"]
        vectors_path = os.path.join(env.staging_root, generation_id,
                                    "vectors.fp32")
        with open(vectors_path, "r+b") as handle:
            handle.seek(4)
            byte = handle.read(1)
            handle.seek(4)
            handle.write(bytes([byte[0] ^ 0xFF]))
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # checksum mismatch: discard + fresh start
        machine2._cycle()  # fresh build embeds chunk 0-1
        # The unverifiable staging was discarded (never partially
        # trusted); the fresh build for the same (content-addressed)
        # target starts over from row 0.
        self.assertIn("checksum", machine2.status()["last_discard_reason"])
        self.assertEqual(["e1", "e2"], counting.event_ids)
        self.assertEqual("running",
                         machine2.status()["progress"]["status"])

    def test_truncated_vectors_file_resumes_cleanly(self):
        env = self.make_env()
        machine = self.machine()
        machine._cycle()
        machine._cycle()  # chunk 0-1 committed
        generation_id = machine.status()["target_generation_id"]
        vectors_path = os.path.join(env.staging_root, generation_id,
                                    "vectors.fp32")
        # Crash mid-chunk-2: the file holds chunk 1 + half of chunk 2.
        with open(vectors_path, "r+b") as handle:
            handle.truncate(2 * 16 + 8)
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        progress = self.run_to_ready(machine2)
        self.assertEqual("ready", progress["status"])
        # Chunk 1 was verified and kept; rows 2..5 were re-embedded.
        self.assertEqual(["e3", "e4", "e5", "e6"], counting.event_ids)
        self.assertEqual(3, len(progress["chunks"]))
        self.assertEqual(6 * 16, os.path.getsize(vectors_path))


class BlockedTest(EnvTest):
    """Deterministic faults block with the event named; no silent skip."""

    def failing_provider(self, event="e3", exc=None):
        inner = make_provider(DESIRED_REPR)
        if exc is None:
            exc = lambda: EvidenceError("representation_fault",  # noqa: E731
                                        "model forward exploded")
        return _CountingProvider(inner, fail_event=event, fail_exc=exc)

    def test_provider_fault_blocks_naming_the_event(self):
        env = self.make_env()
        counting = self.failing_provider()
        machine = self.machine(provider=counting)
        machine._cycle()  # start
        machine._cycle()  # chunk 0-1
        machine._cycle()  # chunk 1-3: e3 blocks
        status = machine.status()
        self.assertTrue(status["blocked"])
        self.assertEqual(["e3"], status["blocked_events"])
        progress = env.progress(status["target_generation_id"])
        self.assertEqual("blocked", progress["status"])
        self.assertEqual(["e3"], progress["blocked_events"])
        self.assertIn("model forward exploded", progress["reason"])
        self.assertEqual("vector", progress["phase"])
        # Nothing is published.
        published = os.path.join(env.derived_root, "generations")
        self.assertTrue(not os.path.exists(published)
                        or os.listdir(published) == [])

    def test_blocked_park_no_auto_retry(self):
        env = self.make_env()
        counting = self.failing_provider()
        machine = self.machine(provider=counting)
        for _ in range(3):
            machine._cycle()
        calls_after_block = counting.count
        for _ in range(5):
            machine._cycle()
        self.assertEqual(calls_after_block, counting.count)

    def test_blocked_persists_across_restart(self):
        env = self.make_env()
        machine = self.machine(provider=self.failing_provider())
        for _ in range(3):
            machine._cycle()
        machine.close()
        counting2 = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting2)
        self.machines.append(machine2)
        machine2._cycle()
        # The block record re-derives: the worker parks, no embedding.
        self.assertEqual(0, counting2.count)
        self.assertTrue(machine2.status()["blocked"])

    def test_retry_resumes_from_last_verified_chunk(self):
        env = self.make_env()
        counting = self.failing_provider()
        machine = self.machine(provider=counting)
        for _ in range(3):
            machine._cycle()  # e1..e2 ok, e3 blocks
        self.assertEqual(["e1", "e2"], counting.event_ids)
        # Cause persists: retry re-attempts and re-blocks deterministically.
        machine.retry()
        machine._cycle()
        self.assertTrue(machine.status()["blocked"])
        self.assertEqual(["e3"], machine.status()["blocked_events"])
        self.assertEqual(["e1", "e2"], counting.event_ids)
        # Cause fixed: retry resumes from the last verified chunk (e1/e2
        # are never re-embedded).
        resumed = _CountingProvider(make_provider(DESIRED_REPR))
        machine.retarget(resumed)
        machine.retry()
        progress = self.run_to_ready(machine)
        self.assertEqual("ready", progress["status"])
        self.assertEqual(["e3", "e4", "e5", "e6"], resumed.event_ids)
        self.assertEqual(3, len(progress["chunks"]))

    def test_parse_error_blocks_before_any_staging(self):
        env = self.make_env()
        env.facts.add_event("e7", segment_input="shijie", selection="",
                            preceding_text="坏事件", competition=("世界",))
        machine = self.machine()
        machine._cycle()
        status = machine.status()
        self.assertTrue(status["blocked"])
        self.assertEqual(["e7"], status["blocked_events"])
        # No staging directory was created for the unparseable target.
        self.assertEqual([], env.staging_dirs())

    def test_parse_error_unblocks_on_input_change(self):
        env = self.make_env()
        env.facts.add_event("e7", segment_input="shijie", selection="",
                            preceding_text="坏事件", competition=("世界",))
        machine = self.machine()
        machine._cycle()
        self.assertTrue(machine.status()["blocked"])
        # A store replacement (new epoch, bad event gone) is an input
        # change: the block re-derives and the build proceeds.
        env.facts.conn.execute(
            "DELETE FROM selection_events WHERE event_id = 'e7';")
        env.facts.conn.execute(
            "DELETE FROM selection_candidates WHERE event_id = 'e7';")
        env.facts.conn.execute(
            "DELETE FROM commits WHERE commit_id = 'commit-e7';")
        env.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        env.facts.conn.commit()
        machine._cycle()
        self.assertFalse(machine.status()["blocked"])
        self.assertIsNotNone(machine.status()["target_generation_id"])

    def test_queries_do_not_drive_build_retry(self):
        env = self.make_env()
        counting = self.failing_provider()
        machine = self.machine(provider=counting)
        for _ in range(3):
            machine._cycle()
        self.assertTrue(machine.status()["blocked"])
        # An evidence service over the same facts serves queries while the
        # build is blocked; queries never wake the builder (SCN-64-7).
        service = EvidenceService(
            env.facts_root, PARAMS, make_provider(ACTIVE_REPR), 1.0)
        for _ in range(5):
            service.serve({
                "schema_id": "luna_pinyin",
                "category": "word",
                "canonical_segment_input": "shijie",
                "preceding_text": "我之前去",
                "candidates": ["世界", "时界"],
                "fact_high_water": None,
            })
        self.assertEqual(2, counting.count)
        self.assertTrue(machine.status()["blocked"])


class ReadyTest(EnvTest):
    """A ready staging survives restart and is re-verified, never trusted
    blindly."""

    def test_ready_survives_restart(self):
        env = self.make_env()
        machine = self.machine()
        progress = self.run_to_ready(machine)
        machine.close()
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()
        # No rebuild: the ready staging is kept (re-verification uses no
        # provider embedding at all).
        self.assertEqual(0, counting.count)
        self.assertEqual("ready",
                         machine2.status()["progress"]["status"])
        self.assertEqual(progress["generation_id"],
                         machine2.status()["target_generation_id"])

    def test_tampered_ready_staging_is_discarded_and_rebuilt(self):
        env = self.make_env()
        machine = self.machine()
        self.run_to_ready(machine)
        generation_id = machine.status()["target_generation_id"]
        machine.close()
        vectors_path = os.path.join(env.staging_root, generation_id,
                                    "vectors.fp32")
        with open(vectors_path, "r+b") as handle:
            handle.seek(20)
            byte = handle.read(1)
            handle.seek(20)
            handle.write(bytes([byte[0] ^ 0xFF]))
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting)
        self.machines.append(machine2)
        machine2._cycle()  # re-verification failed: discard + fresh start
        self.assertIn("re-verification",
                      machine2.status()["last_discard_reason"])
        self.assertEqual("running",
                         machine2.status()["progress"]["status"])
        # The next cycle embeds chunk 1 for the same (content-addressed)
        # target.
        machine2._cycle()
        self.assertEqual(["e1", "e2"], counting.event_ids)
        self.assertEqual("running",
                         machine2.status()["progress"]["status"])

    def test_ready_discarded_when_desired_becomes_active(self):
        env = self.make_env()
        machine = self.machine()
        self.run_to_ready(machine)
        generation_id = machine.status()["target_generation_id"]
        machine2 = make_machine(env.facts_root, env.derived_root,
                                desired_repr=ACTIVE_REPR)
        self.machines.append(machine2)
        machine2._cycle()
        self.assertEqual("discarded", env.progress(generation_id)["status"])

    def test_foreign_staging_records_are_marked_discarded(self):
        env = self.make_env()
        machine = self.machine()
        progress = self.run_to_ready(machine)
        # A leftover staging from an obsolete target (old desired).
        stale_id = "shadow-gen-v1:obsolete-target-000000000000000000000000"
        stale_dir = os.path.join(env.staging_root, stale_id)
        os.makedirs(stale_dir)
        env.write_progress(stale_id, {
            "progress_version": STAGING_PROGRESS_VERSION,
            "generation_id": stale_id,
            "status": "running",
            "total_rows": 6,
            "rows_fingerprint": "f" * 64,
            "identity": {
                "store_epoch": "e1",
                "source_hlc": [1000000, 6],
                "representation_id": "old-desired-repr",
                "vector_dimension": 4,
                "vector_format": "fp32-row-major-little-endian",
                "builder_version": BUILD_VERSION,
                "retrieval_backend": "exact",
                "retrieval_params": {},
            },
            "chunks": [],
        })
        machine._cycle()
        self.assertEqual("discarded", env.progress(stale_id)["status"])
        # The machine's own ready staging is untouched.
        self.assertEqual("ready", env.progress(
            progress["generation_id"])["status"])
        # Nothing is deleted by the machine.
        self.assertEqual(
            sorted([stale_id, progress["generation_id"]]),
            env.staging_dirs())


class ConcurrentServingTest(EnvTest):
    """SCN-64-6/7: the active generation keeps serving and absorbing delta
    while the staging build runs; queries never drive the build."""

    def test_active_serves_and_absorbs_delta_during_staging_build(self):
        env = self.make_env()
        active_provider = make_provider(ACTIVE_REPR)
        active_gen = build_generation(env.facts_root, active_provider,
                                      env.derived_root)
        delta = DeltaStateMachine(env.facts_root, env.derived_root,
                                  active_provider, active_gen.generation_id,
                                  poll_interval=0.01)
        self.machines.append(delta)
        service = EvidenceService(env.facts_root, PARAMS, active_provider,
                                  1.0, machine=delta)

        def query():
            return service.serve({
                "schema_id": "luna_pinyin",
                "category": "word",
                "canonical_segment_input": "shijie",
                "preceding_text": "我之前去",
                "candidates": ["世界", "时界"],
                "fact_high_water": {
                    "store_epoch": "e1",
                    "hlc_physical_ms": 1000000,
                    "hlc_logical": 99,
                },
            })

        staging = self.machine()
        # Build one chunk, then commit new facts and retract another while
        # the staging build continues -- the active path must absorb them.
        staging._cycle()
        env.facts.add_event("e9", segment_input="jinqi", selection="近期",
                            preceding_text="新事件上文",
                            competition=("近期", "今期"))
        env.facts.add_retraction("r9", "commit-e9", (1000000, 99))
        env.facts.add_event("e10", segment_input="jinqi", selection="今期",
                            preceding_text="另一个新事件",
                            competition=("近期", "今期"))
        progress = self.run_to_ready(staging)
        # The active machine served, caught up and kept its own identity.
        self.assertEqual("ok", query()["status"])
        snapshot = delta.ensure_caught_up()
        self.assertEqual(active_gen.generation_id,
                         snapshot.base_generation_id)
        self.assertEqual(7, len(snapshot.event_ids()))
        self.assertEqual(ACTIVE_REPR, snapshot.representation_id)
        # The staging is still pinned at H0 with 6 rows.
        self.assertEqual(6, progress["total_rows"])
        active_gen.close()

    def test_queries_never_wake_the_staging_builder(self):
        env = self.make_env()
        counting = _CountingProvider(make_provider(DESIRED_REPR))
        machine = self.machine(provider=counting)
        machine._cycle()  # start
        machine._cycle()  # chunk 0-1
        machine.close()
        # A restarted machine resumes on its own schedule; serving queries
        # must not change how many times the provider is consulted.
        counting2 = _CountingProvider(make_provider(DESIRED_REPR))
        machine2 = make_machine(env.facts_root, env.derived_root,
                                provider=counting2)
        self.machines.append(machine2)
        machine2._cycle()
        self.assertEqual(["e3", "e4"], counting2.event_ids)
        service = EvidenceService(env.facts_root, PARAMS,
                                  make_provider(ACTIVE_REPR), 1.0)
        for _ in range(10):
            service.serve({
                "schema_id": "luna_pinyin",
                "category": "word",
                "canonical_segment_input": "shijie",
                "preceding_text": "我之前去",
                "candidates": ["世界", "时界"],
                "fact_high_water": None,
            })
        self.assertEqual(["e3", "e4"], counting2.event_ids)


class LeaseTest(EnvTest):
    """Single-builder constraint (spec "一次只运行一个 builder")."""

    def test_staging_embeds_under_the_shared_lease(self):
        env = self.make_env()
        lock = threading.Lock()
        counting = _CountingProvider(make_provider(DESIRED_REPR),
                                     record_lock=True, lock=lock)
        machine = self.machine(provider=counting, builder_lock=lock)
        machine._cycle()  # start
        machine._cycle()  # chunk 0-1 embeds under the lease
        self.assertTrue(counting.lock_held)
        self.assertTrue(all(counting.lock_held))

    def test_delta_rebuild_uses_the_same_lease(self):
        env = self.make_env()
        lock = threading.Lock()
        plain = make_provider(ACTIVE_REPR)
        gen = build_generation(env.facts_root, plain, env.derived_root)
        gen.close()
        shutil.rmtree(os.path.join(env.derived_root, "generations",
                                   gen.generation_id))
        # The delta machine must rebuild the (now missing) declared
        # generation; its embedding runs under the same shared lease.
        counting = _CountingProvider(plain, record_lock=True, lock=lock)
        delta = DeltaStateMachine(env.facts_root, env.derived_root, counting,
                                  gen.generation_id, poll_interval=0.01,
                                  builder_lock=lock)
        self.machines.append(delta)
        # The machine rebuilt the (now missing) declared generation during
        # construction; every embed ran under the shared lease.
        self.assertTrue(counting.lock_held)
        self.assertTrue(all(counting.lock_held))
        self.assertTrue(os.path.isdir(os.path.join(
            env.derived_root, "generations", gen.generation_id)))


class ConfigWiringTest(unittest.TestCase):
    """desired/active config separation (spec: 配置区分 desired 与 active)."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.derived_root = os.path.join(self.facts_root, "derived")
        self.base_config = {
            "representation_id": ACTIVE_REPR,
            "derived_root": self.derived_root,
            "generation_id": ACTIVE_ID,
            "gamma": 0.5,
        }

    def tearDown(self):
        self.facts.close()

    def test_absent_keys_return_none(self):
        self.assertIsNone(build_staging_machine_from_config(
            self.facts_root, {"representation_id": ACTIVE_REPR}))

    def test_one_of_derived_or_generation_is_a_fault(self):
        only_derived = {key: value for key, value in self.base_config.items()
                        if key != "generation_id"}
        only_generation = {key: value
                           for key, value in self.base_config.items()
                           if key != "derived_root"}
        with self.assertRaises(EvidenceError):
            build_staging_machine_from_config(self.facts_root, only_derived)
        with self.assertRaises(EvidenceError):
            build_staging_machine_from_config(self.facts_root,
                                              only_generation)

    def test_default_desired_equals_active(self):
        machine = build_staging_machine_from_config(
            self.facts_root, self.base_config)
        try:
            status = machine.status()
            self.assertEqual(ACTIVE_REPR,
                             status["desired_representation_id"])
            self.assertEqual(ACTIVE_REPR,
                             status["active_representation_id"])
            machine._cycle()
            staging = os.path.join(self.derived_root, "staging")
            self.assertTrue(not os.path.isdir(staging)
                            or os.listdir(staging) == [])
        finally:
            machine.close()

    def test_desired_difference_queues_a_build(self):
        config = dict(self.base_config,
                      desired_representation_id=DESIRED_REPR)
        machine = build_staging_machine_from_config(
            self.facts_root, config)
        try:
            for _ in range(50):
                machine._cycle()
                progress = machine.status()["progress"]
                if progress is not None and progress["status"] == "ready":
                    break
            self.assertEqual("ready",
                             machine.status()["progress"]["status"])
            self.assertEqual(DESIRED_REPR,
                             machine.status()["desired_representation_id"])
        finally:
            machine.close()

    def test_malformed_desired_is_a_fault(self):
        with self.assertRaises(EvidenceError):
            build_staging_machine_from_config(
                self.facts_root,
                dict(self.base_config, desired_representation_id=""))


class WorkerThreadTest(EnvTest):
    """End-to-end runs with the real background worker."""

    def test_background_worker_reaches_ready(self):
        env = self.make_env()
        machine = StagingBuildMachine(
            env.facts_root, env.derived_root, make_provider(DESIRED_REPR),
            ACTIVE_REPR, ACTIVE_ID, chunk_rows=2, poll_interval=0.01)
        self.machines.append(machine)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            progress = machine.status()["progress"]
            if progress is not None and progress["status"] == "ready":
                break
            time.sleep(0.02)
        self.assertEqual("ready", machine.status()["progress"]["status"])
        with open(os.path.join(env.staging_root,
                               machine.status()["target_generation_id"],
                               "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(6, manifest["rows"]["count"])

    def test_request_stop_parks_the_worker(self):
        env = self.make_env()
        machine = StagingBuildMachine(
            env.facts_root, env.derived_root, make_provider(DESIRED_REPR),
            ACTIVE_REPR, ACTIVE_ID, chunk_rows=2, poll_interval=0.01)
        self.machines.append(machine)
        machine.request_stop()
        self.assertTrue(machine.wait_idle(2.0))
        chunks_before = len((machine.status()["progress"] or {})
                            .get("chunks", []))
        time.sleep(0.1)
        chunks_after = len((machine.status()["progress"] or {})
                           .get("chunks", []))
        self.assertEqual(chunks_before, chunks_after)
        machine.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            progress = machine.status()["progress"]
            if progress is not None and progress["status"] == "ready":
                break
            time.sleep(0.02)
        self.assertEqual("ready", machine.status()["progress"]["status"])


if __name__ == "__main__":
    unittest.main()
