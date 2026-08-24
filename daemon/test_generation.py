#!/usr/bin/env python3
"""Immutable shadow generation tests (Habit130/squirrel#62, AC-62-v1).

Model-free, stdlib-only, sandboxed temp fact roots and injected deterministic
representation fixtures -- never real private history.  The suite is
adversarial by design:

  AC62-1  the builder fixes the store epoch and the source HLC watermark and
          derives a deterministic ordered active-event list on a consistent
          snapshot
  AC62-2  the container binds identity (epoch, source watermark, complete
          representation id, dimension and format, builder version,
          retrieval backend and params), is row-major FP32, and every file
          carries size + checksum
  AC62-3  row <-> event id / choice problem key / candidate / HLC mapping is
          bidirectional and verified
  AC62-4  reopen self-verification (SCN-62-2)
  AC62-5  shadow state only diagnoses/retrieves (SCN-62-6, covered by the
          untouched existing suite plus scope review)
  AC62-6  facts stay the only raw-text source; deleting a generation allows a
          deterministic full rebuild (SCN-62-5)
  AC62-7  corrupt or identity-unknown generations are rejected, never loaded
          as empty memory (SCN-62-3)
"""

import json
import math
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from evidence import (CandidateFixtureRepresentationProvider, EvidenceError,
                      FixtureRepresentationProvider,  # noqa: E402
                      RepresentationProvider)
from generation import (  # noqa: E402
    BUILD_VERSION,
    CHUNK_ROWS,
    GENERATION_FILES,
    GENERATION_ID_PREFIX,
    MANIFEST_VERSION,
    PROBE_COUNT,
    PROGRESS_VERSION,
    RETRIEVAL_BACKEND,
    UNIT_NORM_TOLERANCE,
    VECTOR_FORMAT,
    AtomicWriteCommitted,
    BuildBlockedError,
    BuildEpochChangedError,
    BuildTargetExistsError,
    Generation,
    GenerationError,
    GenerationRejected,
    GenerationRepresentationProvider,
    _write_atomic,
    build_generation,
    open_generation,
    replay_exact,
)
from oracle import (FactReader, OracleParams, OracleQuery,  # noqa: E402
                    compute_evidence)
from test_oracle import FactsFixture  # noqa: E402

REPR_ID = "shadow-gen-test-repr-v1"
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)

PARAMS = OracleParams(tau=0.5, k_evidence=8, half_life=32.0, saturation_k=1.0)

# A secret 上文 that must never appear in any generation file: facts are the
# only raw-text source (AC62-6).
SECRET_PRECEDING = "机密上文内容绝对不许进容器"


def make_provider(representation_id=REPR_ID):
    return FixtureRepresentationProvider(
        representation_id,
        {"我之前去": QUERY_VECTOR,
         "我之后去": (0.8, 0.6, 0.0, 0.0),
         SECRET_PRECEDING: (0.0, 0.0, 1.0, 0.0)},
        {"luna_pinyin|shijie|时界": (0.9, 0.43589, 0.0, 0.0),
         "luna_pinyin|shijie|世界": (0.3, 0.953939, 0.0, 0.0),
         "luna_pinyin|gongji|攻击": (0.2, 0.979796, 0.0, 0.0),
         "luna_pinyin|gongji|公鸡": (0.6, 0.8, 0.0, 0.0),
         "luna_pinyin|jinqi|近期": (0.7, 0.714143, 0.0, 0.0)},
        default_event=(0.0, 1.0, 0.0, 0.0))


def make_facts():
    f = FactsFixture()
    f.add_event("e1", segment_input="shijie", selection="时界",
                preceding_text="我之前去", competition=("世界", "时界"))
    f.add_event("e2", segment_input="shijie", selection="世界",
                preceding_text="我之后去", competition=("世界", "时界"))
    f.add_event("e3", segment_input="gongji", selection="攻击",
                preceding_text="部队发起", competition=("攻击", "公鸡"))
    f.add_event("e4", segment_input="gongji", selection="公鸡",
                preceding_text="农场清晨", competition=("攻击", "公鸡"))
    f.add_event("e5", segment_input="shijie", selection="时界",
                preceding_text=SECRET_PRECEDING,
                competition=("世界", "时界"))
    f.add_event("e6", segment_input="jinqi", selection="近期",
                preceding_text="讨论进展", competition=("近期", "今期"))
    return f


def fp32(vector):
    """Quantize to the container's FP32 row semantics (exact round trip)."""
    return tuple(struct.unpack("<f", struct.pack("<f", float(value)))[0]
                 for value in vector)


def read_generation_file(root, generation_id, name):
    with open(os.path.join(root, "generations", generation_id, name),
              "rb") as handle:
        return handle.read()


def manifest_of(root, generation_id):
    return json.loads(read_generation_file(root, generation_id,
                                           "manifest.json").decode("utf-8"))


class GenerationBuildTest(unittest.TestCase):
    """The builder: identity fixing, container format, determinism (AC62-1/2)."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.root = tempfile.mkdtemp(prefix="gen_build_")
        self.provider = make_provider()

    def tearDown(self):
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, provider=None, **kwargs):
        return build_generation(self.facts_root,
                                provider or self.provider, self.root,
                                **kwargs)

    def test_build_publishes_verified_generation(self):
        gen = self.build()
        self.assertEqual(os.path.join(self.root, "generations",
                                      gen.generation_id), gen.generation_dir)
        self.assertTrue(os.path.isdir(gen.generation_dir))
        self.assertEqual([], os.listdir(os.path.join(self.root, "staging")))
        gen.close()

    def test_identity_binds_every_spec_component(self):
        gen = self.build()
        identity = gen.identity()
        self.assertEqual("e1", identity["store_epoch"])
        self.assertEqual([1000000, 6], identity["source_hlc"])
        self.assertEqual(REPR_ID, identity["representation_id"])
        self.assertEqual(4, identity["vector_dimension"])
        self.assertEqual(VECTOR_FORMAT, identity["vector_format"])
        self.assertEqual(BUILD_VERSION, identity["builder_version"])
        self.assertEqual(RETRIEVAL_BACKEND, identity["retrieval_backend"])
        self.assertEqual({}, identity["retrieval_params"])
        self.assertTrue(gen.generation_id.startswith(GENERATION_ID_PREFIX))
        gen.close()

    def test_generation_id_depends_on_epoch_and_representation(self):
        base = self.build().generation_id
        other_repr = self.build(provider=make_provider("other-repr-v1"))
        self.assertNotEqual(base, other_repr.generation_id)
        other_repr.close()
        self.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        self.facts.conn.commit()
        other_epoch = self.build()
        self.assertNotEqual(base, other_epoch.generation_id)
        other_epoch.close()

    def test_row_order_is_hlc_then_event_id(self):
        gen = self.build()
        self.assertEqual(["e1", "e2", "e3", "e4", "e5", "e6"],
                         gen.event_ids())
        for index, event_id in enumerate(gen.event_ids()):
            self.assertEqual(index, gen.event_row(event_id))
        gen.close()

    def test_retracted_events_are_excluded_at_the_source_watermark(self):
        self.facts.add_event("e7", segment_input="shijie", selection="世界",
                             preceding_text="撤销前的上文",
                             competition=("世界", "时界"))
        self.facts.add_retraction("r1", "commit-e7", (1000000, 99))
        gen = self.build()
        self.assertNotIn("e7", gen.event_ids())
        gen.close()

    def test_build_is_byte_deterministic(self):
        first = self.build()
        second_root = tempfile.mkdtemp(prefix="gen_build2_")
        try:
            second = build_generation(self.facts_root, self.provider,
                                      second_root)
            self.assertEqual(first.generation_id, second.generation_id)
            for name in GENERATION_FILES:
                self.assertEqual(
                    read_generation_file(self.root, first.generation_id,
                                          name),
                    read_generation_file(second_root, second.generation_id,
                                          name))
            second.close()
        finally:
            shutil.rmtree(second_root, ignore_errors=True)
        first.close()

    def test_rebuild_after_delete_is_bit_identical(self):
        first = self.build()
        generation_id = first.generation_id
        files = {name: read_generation_file(self.root, generation_id, name)
                 for name in GENERATION_FILES}
        first.close()
        shutil.rmtree(os.path.join(self.root, "generations", generation_id))
        second = self.build()
        self.assertEqual(generation_id, second.generation_id)
        for name in GENERATION_FILES:
            self.assertEqual(files[name],
                             read_generation_file(self.root, generation_id,
                                                  name))
        second.close()

    def test_build_target_exists_is_rejected(self):
        first = self.build()
        first.close()
        with self.assertRaises(BuildTargetExistsError):
            self.build()

    def test_empty_store_builds_a_valid_empty_generation(self):
        empty = FactsFixture()
        empty_root = os.path.dirname(empty.db_path)
        try:
            gen = build_generation(empty_root, self.provider, self.root)
            self.assertEqual(0, gen.row_count)
            self.assertEqual([], gen.event_ids())
            gen.close()
            with self.assertRaises(GenerationError):
                gen.event_row("anything")
            manifest = manifest_of(self.root, gen.generation_id)
            self.assertEqual(0, manifest["rows"]["count"])
            self.assertEqual([], manifest["chunks"])
            self.assertEqual([], manifest["probes"]["items"])
        finally:
            empty.close()

    def test_build_never_puts_raw_preceding_text_into_the_container(self):
        gen = self.build()
        for name in GENERATION_FILES:
            content = read_generation_file(self.root, gen.generation_id, name)
            self.assertNotIn(SECRET_PRECEDING.encode("utf-8"), content)
            self.assertNotIn(SECRET_PRECEDING, content.decode("utf-8",
                                                              "ignore"))
        gen.close()

    def test_metadata_contains_only_the_declared_projection(self):
        gen = self.build()
        metadata = json.loads(
            read_generation_file(self.root, gen.generation_id,
                                 "metadata.json").decode("utf-8"))
        self.assertEqual(6, len(metadata))
        for index, row in enumerate(metadata):
            self.assertEqual(set(row), {"row", "event_id",
                                        "choice_problem_key", "candidate",
                                        "hlc"})
            self.assertEqual(index, row["row"])
        gen.close()

    def test_chunk_records_tile_the_row_range(self):
        gen = self.build(chunk_rows=2)
        manifest = manifest_of(self.root, gen.generation_id)
        chunks = manifest["chunks"]
        self.assertEqual([{"start_row": 0, "end_row": 2},
                          {"start_row": 2, "end_row": 4},
                          {"start_row": 4, "end_row": 6}],
                         [{"start_row": c["start_row"], "end_row": c["end_row"]}
                          for c in chunks])
        for chunk in chunks:
            self.assertEqual(2 * 4 * 4, chunk["bytes"])
            self.assertTrue(chunk["sha256"])
        gen.close()

    def test_all_files_are_owner_only(self):
        gen = self.build()
        for entry in os.listdir(gen.generation_dir):
            path = os.path.join(gen.generation_dir, entry)
            self.assertEqual(0o600, os.stat(path).st_mode & 0o777, entry)
        self.assertEqual(0o700,
                         os.stat(gen.generation_dir).st_mode & 0o777)
        gen.close()

    def test_builder_fixes_the_watermark_even_with_later_events(self):
        # An event committed after the snapshot is not part of the
        # generation, but its facts remain available for the next build.
        first = self.build()
        self.assertEqual(6, first.row_count)
        first.close()
        self.facts.add_event("e9", segment_input="shijie", selection="世界",
                             preceding_text="后来的上文",
                             competition=("世界", "时界"))
        second = self.build()
        self.assertEqual(7, second.row_count)
        self.assertNotEqual(first.generation_id, second.generation_id)
        second.close()


class ReopenVerificationTest(unittest.TestCase):
    """Reopen self-verification and the bidirectional mapping (AC62-3/4)."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.root = tempfile.mkdtemp(prefix="gen_reopen_")
        self.provider = make_provider()
        self.gen = build_generation(self.facts_root, self.provider, self.root,
                                    chunk_rows=2)
        self.dir = os.path.join(self.root, "generations", self.gen.generation_id)

    def tearDown(self):
        self.gen.close()
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_reopen_verifies_checksums_event_set_and_mapping(self):
        reopened = open_generation(self.dir)
        try:
            self.assertEqual(self.gen.generation_id, reopened.generation_id)
            self.assertEqual(["e1", "e2", "e3", "e4", "e5", "e6"],
                             reopened.event_ids())
        finally:
            reopened.close()

    def test_row_mapping_is_bidirectional(self):
        reopened = open_generation(self.dir)
        try:
            for index, event_id in enumerate(reopened.event_ids()):
                row = reopened.row_event(index)
                self.assertEqual(event_id, row["event_id"])
                self.assertEqual(index, row["row"])
                self.assertEqual(index, reopened.event_row(event_id))
                self.assertEqual(row, reopened.row_event(
                    reopened.event_row(event_id)))
                self.assertEqual(reopened.vector(index),
                                 reopened.event_vector(event_id))
            with self.assertRaises(GenerationError):
                reopened.event_row("no-such-event")
            with self.assertRaises(GenerationError):
                reopened.row_event(999)
        finally:
            reopened.close()

    def test_choice_problem_key_and_hlc_are_stored_per_row(self):
        reopened = open_generation(self.dir)
        try:
            row = reopened.row_event(0)
            self.assertEqual(["luna_pinyin", "word", "shijie"],
                             row["choice_problem_key"])
            self.assertEqual([1000000, 1], row["hlc"])
            self.assertEqual("时界", row["candidate"])
        finally:
            reopened.close()

    def test_vectors_are_finite_and_unit(self):
        reopened = open_generation(self.dir)
        try:
            for index in range(reopened.row_count):
                vector = reopened.vector(index)
                self.assertEqual(4, len(vector))
                for value in vector:
                    self.assertTrue(math.isfinite(value))
                norm = math.sqrt(sum(value * value for value in vector))
                self.assertAlmostEqual(1.0, norm, delta=UNIT_NORM_TOLERANCE)
        finally:
            reopened.close()

    def test_probes_are_recorded_and_reverified(self):
        manifest = manifest_of(self.root, self.gen.generation_id)
        probes = manifest["probes"]
        self.assertEqual(PROBE_COUNT, len(probes["items"]))
        for probe in probes["items"]:
            self.assertIn("schema_id", probe)
            self.assertIn("canonical_segment_input", probe)
            self.assertIn("candidates", probe)
            self.assertIn("query_vector", probe)
            self.assertTrue(probe["results_fingerprint"])
        reopened = open_generation(self.dir)  # recomputes every probe
        reopened.close()

    def test_open_rejects_a_non_generation_directory(self):
        plain = tempfile.mkdtemp(prefix="gen_plain_")
        try:
            with open(os.path.join(plain, "manifest.json"), "w") as handle:
                handle.write("{}")
            with self.assertRaises(GenerationRejected):
                open_generation(plain)
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_open_rejects_extra_directory_entries(self):
        with open(os.path.join(self.dir, "stray.txt"), "w") as handle:
            handle.write("x")
        try:
            with self.assertRaises(GenerationRejected):
                open_generation(self.dir)
        finally:
            os.unlink(os.path.join(self.dir, "stray.txt"))


class RejectionMatrixTest(unittest.TestCase):
    """Corruption / truncation / unknown identity must reject (SCN-62-3)."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.root = tempfile.mkdtemp(prefix="gen_reject_")
        self.provider = make_provider()
        self.gen = build_generation(self.facts_root, self.provider, self.root)
        self.dir = os.path.join(self.root, "generations", self.gen.generation_id)

    def tearDown(self):
        self.gen.close()
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def assert_rejected(self):
        with self.assertRaises(GenerationRejected) as ctx:
            open_generation(self.dir)
        return ctx.exception.reason

    def test_flipped_vector_byte_is_rejected(self):
        with open(self.path("vectors.fp32"), "r+b") as handle:
            handle.seek(0)
            byte = handle.read(1)
            handle.seek(0)
            handle.write(bytes([byte[0] ^ 0x01]))
        self.assert_rejected()

    def test_truncated_vectors_file_is_rejected(self):
        with open(self.path("vectors.fp32"), "r+b") as handle:
            handle.truncate(os.path.getsize(self.path("vectors.fp32")) - 4)
        self.assert_rejected()

    def test_appended_vectors_garbage_is_rejected(self):
        with open(self.path("vectors.fp32"), "ab") as handle:
            handle.write(b"\x00\x00\x80\x7f")
        self.assert_rejected()

    def test_corrupt_metadata_is_rejected(self):
        with open(self.path("metadata.json"), "r+b") as handle:
            handle.seek(4)
            byte = handle.read(1)
            handle.seek(4)
            handle.write(bytes([byte[0] ^ 0x01]))
        self.assert_rejected()

    def test_removed_vectors_file_is_rejected(self):
        os.unlink(self.path("vectors.fp32"))
        self.assert_rejected()

    def test_tampered_manifest_checksum_is_rejected(self):
        with open(self.path("manifest.json"), "r+b") as handle:
            handle.seek(8)
            byte = handle.read(1)
            handle.seek(8)
            handle.write(bytes([byte[0] ^ 0x01]))
        self.assert_rejected()

    def test_renamed_directory_is_an_unknown_identity(self):
        moved = self.dir + "-moved"
        os.rename(self.dir, moved)
        try:
            with self.assertRaises(GenerationRejected) as ctx:
                open_generation(moved)
            self.assertIn("identity", ctx.exception.reason)
        finally:
            os.rename(moved, self.dir)

    def test_identity_that_does_not_recompute_is_rejected(self):
        manifest_path = self.path("manifest.json")
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["generation_id"] = GENERATION_ID_PREFIX + ":" + "0" * 32
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True)
        self.assert_rejected()

    def test_tampered_store_epoch_in_identity_is_rejected(self):
        manifest_path = self.path("manifest.json")
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["identity"]["store_epoch"] = "e2"
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True)
        self.assert_rejected()

    def test_tampered_probe_fingerprint_is_rejected(self):
        manifest_path = self.path("manifest.json")
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["probes"]["items"][0]["results_fingerprint"] = "0" * 64
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True)
        self.assert_rejected()

    def test_unsupported_manifest_version_is_rejected(self):
        manifest_path = self.path("manifest.json")
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["manifest_version"] = "future-version"
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True)
        self.assert_rejected()

    def test_unsupported_retrieval_backend_is_rejected(self):
        manifest_path = self.path("manifest.json")
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        manifest["identity"]["retrieval_backend"] = "ann"
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True)
        self.assert_rejected()


class ReplayTest(unittest.TestCase):
    """Generation replay equals the canonical oracle on same facts+vectors."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.root = tempfile.mkdtemp(prefix="gen_replay_")
        self.provider = make_provider()
        self.gen = build_generation(self.facts_root, self.provider, self.root)

    def tearDown(self):
        self.gen.close()
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def query(self, schema_id="luna_pinyin", canonical="shijie",
              candidates=("世界", "时界"), preceding="我之前去"):
        return OracleQuery(
            schema_id=schema_id,
            canonical_segment_input=canonical,
            candidates=list(candidates),
            query_vector=list(self.provider.query_vector(preceding)),
        )

    def direct_result(self, query):
        """The canonical oracle on the same facts and fp32-quantized vectors."""
        reader = FactReader(os.path.join(self.facts_root, "facts.sqlite3"))

        def vector_for(event_id):
            for event in reader.read_active_events(self.gen.source_hlc):
                if event.event_id == event_id:
                    return fp32(self.provider.event_vector(event))
            raise KeyError(event_id)

        try:
            return compute_evidence(
                reader, PARAMS,
                OracleQuery(schema_id=query.schema_id,
                            canonical_segment_input=query.canonical_segment_input,
                            candidates=list(query.candidates),
                            query_vector=list(query.query_vector),
                            category=query.category,
                            as_of=self.gen.source_hlc),
                vector_for)
        finally:
            reader.close()

    def test_replay_matches_the_direct_oracle_bit_identically(self):
        for preceding, canonical in (("我之前去", "shijie"),
                                     ("我之后去", "shijie"),
                                     ("讨论进展", "jinqi")):
            with self.subTest(preceding=preceding, canonical=canonical):
                query = self.query(preceding=preceding, canonical=canonical)
                via_gen = replay_exact(self.gen, self.facts_root, PARAMS,
                                       query)
                direct = self.direct_result(query)
                self.assertEqual(via_gen.same_key_active,
                                 direct.same_key_active)
                self.assertEqual(via_gen.total_mass, direct.total_mass)
                self.assertEqual(
                    [(c.index, c.m, c.s) for c in via_gen.candidates],
                    [(c.index, c.m, c.s) for c in direct.candidates])
                self.assertEqual(
                    [(e.event_id, e.cosine, e.weight, e.matched_candidate)
                     for e in via_gen.kept],
                    [(e.event_id, e.cosine, e.weight, e.matched_candidate)
                     for e in direct.kept])

    def test_replay_zero_evidence_on_empty_generation(self):
        empty = FactsFixture()
        empty_root = os.path.dirname(empty.db_path)
        try:
            gen = build_generation(empty_root, self.provider, self.root)
            result = replay_exact(gen, empty_root, PARAMS, self.query())
            self.assertEqual(0, result.same_key_active)
            self.assertEqual(0.0, result.total_mass)
            self.assertTrue(all(c.s == 0.0 for c in result.candidates))
            gen.close()
        finally:
            empty.close()

    def test_replay_fact_epoch_mismatch_is_fault(self):
        self.facts.conn.execute(
            "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
        self.facts.conn.commit()
        with self.assertRaises(EvidenceError) as ctx:
            replay_exact(self.gen, self.facts_root, PARAMS, self.query())
        self.assertEqual("fact_identity_mismatch", ctx.exception.code)

    def test_replay_store_behind_the_watermark_is_fault(self):
        self.facts.set_clock(1000000, 1)
        with self.assertRaises(EvidenceError) as ctx:
            replay_exact(self.gen, self.facts_root, PARAMS, self.query())
        self.assertEqual("not_caught_up", ctx.exception.code)

    def test_replay_watermark_beyond_the_generation_is_fault(self):
        with self.assertRaises(EvidenceError) as ctx:
            replay_exact(self.gen, self.facts_root, PARAMS, self.query(),
                         request_watermark={"store_epoch": "e1",
                                            "hlc_physical_ms": 1000000,
                                            "hlc_logical": 99})
        self.assertEqual("not_caught_up", ctx.exception.code)

    def test_replay_watermark_epoch_mismatch_is_fault(self):
        with self.assertRaises(EvidenceError) as ctx:
            replay_exact(self.gen, self.facts_root, PARAMS, self.query(),
                         request_watermark={"store_epoch": "other",
                                            "hlc_physical_ms": 1000000,
                                            "hlc_logical": 0})
        self.assertEqual("fact_identity_mismatch", ctx.exception.code)

    def test_replay_event_set_drift_is_fault(self):
        # Facts drift under the same epoch: the container no longer equals
        # the facts' active set at the source watermark -> explicit fault.
        self.facts.conn.execute(
            "DELETE FROM selection_events WHERE event_id = 'e2';")
        self.facts.conn.commit()
        with self.assertRaises(EvidenceError) as ctx:
            replay_exact(self.gen, self.facts_root, PARAMS, self.query())
        self.assertEqual("event_set_mismatch", ctx.exception.code)

    def test_replay_is_pinned_to_the_generation_watermark(self):
        # Even though the store clock advanced past H0, the replay sees
        # exactly the generation snapshot (later events are invisible).
        before = replay_exact(self.gen, self.facts_root, PARAMS, self.query())
        self.facts.add_event("e9", segment_input="shijie", selection="世界",
                             preceding_text="更晚的上文",
                             competition=("世界", "时界"))
        after = replay_exact(self.gen, self.facts_root, PARAMS, self.query())
        self.assertEqual(before.same_key_active, after.same_key_active)
        self.assertEqual(
            [(c.index, c.m, c.s) for c in before.candidates],
            [(c.index, c.m, c.s) for c in after.candidates])


class BlockedBuildTest(unittest.TestCase):
    """Deterministic errors block the build with the event named (SCN-62-7)."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.root = tempfile.mkdtemp(prefix="gen_blocked_")
        self.provider = make_provider()

    def tearDown(self):
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def staging_progress(self, generation_id):
        with open(os.path.join(self.root, "staging", generation_id,
                               "progress.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_provider_fault_blocks_naming_the_event(self):
        class FailingProvider(FixtureRepresentationProvider):
            def event_vector(self, event):
                if event.event_id == "e3":
                    raise EvidenceError("representation_fault",
                                        "model forward exploded")
                return super().event_vector(event)

        with self.assertRaises(BuildBlockedError) as ctx:
            build_generation(self.facts_root, FailingProvider(REPR_ID, {}, {}),
                             self.root)
        self.assertEqual(["e3"], list(ctx.exception.blocked_events))
        self.assertEqual("vector", ctx.exception.phase)
        # Locate the single staging dir and read its progress record.
        staging_entries = os.listdir(os.path.join(self.root, "staging"))
        self.assertEqual(1, len(staging_entries))
        progress = self.staging_progress(staging_entries[0])
        self.assertEqual("blocked", progress["status"])
        self.assertEqual(["e3"], progress["blocked_events"])
        self.assertIn("model forward exploded", progress["reason"])
        # Nothing is published.
        published = os.path.join(self.root, "generations")
        self.assertTrue(not os.path.exists(published)
                        or os.listdir(published) == [])

    def test_dirty_vector_blocks_naming_the_event(self):
        class DirtyProvider(FixtureRepresentationProvider):
            def event_vector(self, event):
                if event.event_id == "e3":
                    return (2.0, 2.0, 2.0, 2.0)  # norm 4, not unit
                return super().event_vector(event)

        with self.assertRaises(BuildBlockedError) as ctx:
            build_generation(self.facts_root, DirtyProvider(REPR_ID, {}, {}),
                             self.root)
        self.assertEqual(["e3"], list(ctx.exception.blocked_events))

    def test_wrong_dimension_vector_blocks_naming_the_event(self):
        class WrongDimProvider(FixtureRepresentationProvider):
            def event_vector(self, event):
                if event.event_id == "e3":
                    return (1.0, 0.0, 0.0)
                return super().event_vector(event)

        with self.assertRaises(BuildBlockedError) as ctx:
            build_generation(self.facts_root,
                             WrongDimProvider(REPR_ID, {}, {}), self.root)
        self.assertEqual(["e3"], list(ctx.exception.blocked_events))
        self.assertIn("dimension", ctx.exception.message)

    def test_parse_error_blocks_naming_the_event(self):
        self.facts.add_event("e7", segment_input="shijie", selection="",
                             preceding_text="坏事件", competition=("世界",))
        with self.assertRaises(BuildBlockedError) as ctx:
            build_generation(self.facts_root, self.provider, self.root)
        self.assertEqual(["e7"], list(ctx.exception.blocked_events))
        self.assertEqual("parse", ctx.exception.phase)

    def test_probe_query_vector_fault_blocks(self):
        class ProbeFailingProvider(FixtureRepresentationProvider):
            def query_vector(self, preceding_text):
                if preceding_text == "我之前去":
                    raise EvidenceError("representation_fault",
                                        "query forward failed")
                return super().query_vector(preceding_text)

        with self.assertRaises(BuildBlockedError) as ctx:
            build_generation(self.facts_root,
                             ProbeFailingProvider(REPR_ID, {}, {}), self.root)
        self.assertEqual("probe", ctx.exception.phase)
        self.assertEqual(["e1"], list(ctx.exception.blocked_events))

    def test_epoch_change_discards_the_staging(self):
        from generation import _check_identity_unchanged as real_check

        def simulate_concurrent_restore(facts_root, store_epoch, source_hlc):
            conn = sqlite3.connect(self.facts.db_path)
            try:
                conn.execute("UPDATE meta SET value = 'e-new' "
                             "WHERE key = 'store_epoch';")
                conn.commit()
            finally:
                conn.close()
            return real_check(facts_root, store_epoch, source_hlc)

        with mock.patch(
                "generation._check_identity_unchanged",
                side_effect=simulate_concurrent_restore):
            with self.assertRaises(BuildEpochChangedError):
                build_generation(self.facts_root, self.provider, self.root)
        staging_entries = os.listdir(os.path.join(self.root, "staging"))
        self.assertEqual(1, len(staging_entries))
        progress = self.staging_progress(staging_entries[0])
        self.assertEqual("discarded", progress["status"])
        self.assertIn("epoch", progress["reason"])


class SeamTest(unittest.TestCase):
    """The generation behind the #61 RepresentationProvider seam."""

    def setUp(self):
        self.facts = make_facts()
        self.facts_root = os.path.dirname(self.facts.db_path)
        self.root = tempfile.mkdtemp(prefix="gen_seam_")
        self.provider = make_provider()
        self.gen = build_generation(self.facts_root, self.provider, self.root)

    def tearDown(self):
        self.gen.close()
        self.facts.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_provider_serves_the_generation_identity(self):
        provider = GenerationRepresentationProvider(self.gen, self.provider)
        self.assertEqual(self.gen.representation_id, provider.representation_id())
        self.assertEqual(self.gen.vector_dimension, provider.vector_dimension())

    def test_event_vector_comes_from_the_stored_rows(self):
        provider = GenerationRepresentationProvider(self.gen, self.provider)
        for event_id in self.gen.event_ids():
            vector = provider.event_vector(
                type("Event", (), {"event_id": event_id})())
            self.assertEqual(list(fp32(self.gen.vector(
                self.gen.event_row(event_id)))), list(vector))

    def test_query_vector_delegates_to_the_query_provider(self):
        provider = GenerationRepresentationProvider(self.gen, self.provider)
        self.assertEqual(list(self.provider.query_vector("我之前去")),
                         list(provider.query_vector("我之前去")))

    def test_query_provider_identity_mismatch_is_a_fault(self):
        with self.assertRaises(EvidenceError) as ctx:
            GenerationRepresentationProvider(
                self.gen, make_provider("different-repr-v1"))
        self.assertEqual("representation_fault", ctx.exception.code)


class CandidateGenerationTest(unittest.TestCase):
    """Generation probes carry one query vector for every current candidate."""

    def test_candidate_generation_does_not_accept_the_old_representation(self):
        facts = make_facts()
        root = tempfile.mkdtemp(prefix="gen_candidate_")
        old_root = tempfile.mkdtemp(prefix="gen_context_only_")
        try:
            provider = CandidateFixtureRepresentationProvider(
                "candidate-conditioned-fixture-v1", {}, {},
                default_event=(0.0, 1.0, 0.0, 0.0))
            generation = build_generation(
                os.path.dirname(facts.db_path), provider, root)
            try:
                manifest = generation.manifest()
                self.assertIn("candidate-conditioned", generation.representation_id)
                self.assertTrue(all(
                    len(item["query_vectors"]) == len(item["candidates"])
                    for item in manifest["probes"]["items"]))
                with self.assertRaises(EvidenceError) as ctx:
                    GenerationRepresentationProvider(
                        generation, make_provider(REPR_ID))
                self.assertEqual("representation_fault", ctx.exception.code)
            finally:
                generation.close()
            old_generation = build_generation(
                os.path.dirname(facts.db_path), make_provider(REPR_ID),
                old_root)
            try:
                with self.assertRaises(EvidenceError) as ctx:
                    GenerationRepresentationProvider(old_generation, provider)
                self.assertEqual("representation_fault", ctx.exception.code)
            finally:
                old_generation.close()
        finally:
            facts.close()
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(old_root, ignore_errors=True)


class EmptyContainerEdgeTest(unittest.TestCase):
    """Zero-row generations are valid and never interpretable as memory."""

    def test_zero_rows_replay_is_zero_evidence_not_a_fault(self):
        facts = FactsFixture()
        root = tempfile.mkdtemp(prefix="gen_empty_")
        try:
            facts_root = os.path.dirname(facts.db_path)
            provider = make_provider()
            gen = build_generation(facts_root, provider, root)
            self.assertEqual(0, gen.row_count)
            self.assertEqual(0, os.path.getsize(os.path.join(
                root, "generations", gen.generation_id, "vectors.fp32")))
            query = OracleQuery(schema_id="luna_pinyin",
                                canonical_segment_input="shijie",
                                candidates=["世界", "时界"],
                                query_vector=list(QUERY_VECTOR))
            result = replay_exact(gen, facts_root, PARAMS, query)
            self.assertTrue(all(c.s == 0.0 for c in result.candidates))
            gen.close()
        finally:
            facts.close()
            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC-133: pre-rename vs post-rename classification of _write_atomic
# ---------------------------------------------------------------------------

class AtomicWriteCommitTest(unittest.TestCase):
    """SCN-133-1/2: temp write, temp fsync and rename stay pre-commit;
    parent fsync after a successful replace is committed/ambiguous."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="atomic_write_")
        self.path = os.path.join(self.root, "target.json")
        with open(self.path, "wb") as handle:
            handle.write(b"old-bytes")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_temp_write_failure_leaves_the_target_unchanged(self):
        original = os.write

        def boom(fd, data):
            raise OSError("injected temp write failed")

        os.write = boom
        try:
            with self.assertRaises(OSError) as raised:
                _write_atomic(self.path, b"new-bytes")
        finally:
            os.write = original
        self.assertNotIsInstance(raised.exception, AtomicWriteCommitted)
        self.assertFalse(getattr(raised.exception, "committed", False))
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), b"old-bytes")

    def test_temp_fsync_failure_leaves_the_target_unchanged(self):
        original = os.fsync

        def boom(fd):
            raise OSError("injected temp fsync failed")

        os.fsync = boom
        try:
            with self.assertRaises(OSError) as raised:
                _write_atomic(self.path, b"new-bytes")
        finally:
            os.fsync = original
        self.assertNotIsInstance(raised.exception, AtomicWriteCommitted)
        self.assertFalse(getattr(raised.exception, "committed", False))
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), b"old-bytes")

    def test_rename_failure_leaves_the_target_unchanged(self):
        original = os.replace

        def boom(src, dst):
            raise OSError("injected rename failed")

        os.replace = boom
        try:
            with self.assertRaises(OSError) as raised:
                _write_atomic(self.path, b"new-bytes")
        finally:
            os.replace = original
        self.assertNotIsInstance(raised.exception, AtomicWriteCommitted)
        self.assertFalse(getattr(raised.exception, "committed", False))
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), b"old-bytes")

    def test_parent_fsync_failure_is_committed_and_keeps_the_new_bytes(self):
        import generation
        original = generation._fsync_directory

        def boom(path):
            raise OSError("injected parent fsync failed")

        generation._fsync_directory = boom
        try:
            with self.assertRaises(AtomicWriteCommitted) as raised:
                _write_atomic(self.path, b"new-bytes")
        finally:
            generation._fsync_directory = original
        self.assertTrue(raised.exception.committed)
        self.assertIn("post-rename fsync failed", str(raised.exception))
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), b"new-bytes")


if __name__ == "__main__":
    unittest.main()
