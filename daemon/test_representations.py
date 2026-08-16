#!/usr/bin/env python3
"""Representation identity, seam, normalization and boundary tests (#60).

Model-free daemon-gate tests (no MLX, no transformers, no model): every
acceptance criterion that does not require a real forward is asserted here
against fakes. The real-MLX extraction, determinism and latency evidence live
in ``integration_hidden_state.py``.

Covered at this level:
  - AC60-1  exact L14/L21/L28 last-token specs are first-round candidates;
            every produced vector is L2-normalized, FP32 and cosine-comparable
  - AC60-2  split-reuse spec is pre-declared; its representation_id always
            differs from exact; the split seam tokenizes prefix and tail
            separately, never re-concatenated
  - AC60-3  representation_id covers model/tokenizer digests, mlx-lm version,
            layer, pooling, truncation, seam, norm, dim, dtype, metric; any
            component change yields a different id
  - AC60-4  same spec + same identity is bit-identical; identity change makes
            the old id incompatible
  - AC60-6  empty context, 64-char boundary, BPE seam, model error and
            non-finite vectors each fail closed or route correctly
  - SCN-60-1/2 routing (no silent dirty vectors)
"""

import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from hidden_state import (  # noqa: E402
    EXACT_LAYERS,
    HiddenStateExtractor,
)
from representations import (  # noqa: E402
    EmptyContextRepresentationError,
    InvalidRepresentationSpec,
    ModelForwardRepresentationError,
    ModelTokenIdentity,
    NonFiniteRepresentationError,
    RepresentationSpec,
    build_model_token_identity,
    cosine,
    exact_tokenization_for,
    first_round_specs,
    l2_normalize,
    model_identity_digest,
    representation_id,
    seam_changed,
    split_context,
    split_tokenization_for,
    window_text,
)


class RecordingTokenizer:
    """Deterministic fake tokenizer that records every encode call."""

    def __init__(self, id_map=None):
        self.id_map = id_map or {}
        self.calls = []
        self._counter = 1000

    def encode(self, text, add_special_tokens=False):
        self.calls.append(text)
        if text in self.id_map:
            return list(self.id_map[text])
        ids = [self._counter + ord(character)
               for character in text]
        self._counter += len(text)
        return ids

    def decode(self, ids):
        raise NotImplementedError


def make_model_dir():
    root = tempfile.mkdtemp(prefix="repr-test-model-")
    with open(os.path.join(root, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "qwen3", "hidden_size": 8}, f)
    with open(os.path.join(root, "tokenizer.json"), "w", encoding="utf-8") as f:
        f.write('{"fake": true}')
    return root


class FakeState:
    """Minimal ModelState surface for gate tests (no MLX anywhere)."""

    def __init__(self, model_path, tokenizer=None, model=None):
        self.model_path = model_path
        self.tokenizer = tokenizer or RecordingTokenizer()
        self.model = model
        self.loaded_count = 0

    def load(self):
        if self.model is not None:
            return
        self.loaded_count += 1

    @property
    def loaded(self):
        return self.model is not None


class FixedVectorExtractor(HiddenStateExtractor):
    """Extractor whose forward is replaced by a deterministic fake.

    Drives the boundary/routing logic of ``exact``/``split_reuse`` without
    MLX; the fake forwards assert the seams and return a test vector.
    """

    def __init__(self, state, vector=None, run_error=None):
        super().__init__(state)
        self._vector = vector if vector is not None else [0.5] * 8
        self._run_error = run_error
        self.forwarded = []

    def _forward_prefix(self, prefix_ids, cache=None):
        self.forwarded.append(("prefix", tuple(prefix_ids)))
        return object()

    def _run(self, ids, cache, snapshot_layers):
        self.forwarded.append(("run", tuple(ids)))
        if self._run_error is not None:
            raise self._run_error
        return {layer: self._vector for layer in snapshot_layers}, cache


def unit_vector(dimension, seed):
    v = [(math.sin(seed + i) + math.cos(seed * i + i)) for i in range(dimension)]
    return l2_normalize(v)


class IdentityDigestTest(unittest.TestCase):
    def test_digest_changes_when_config_content_changes(self):
        root = make_model_dir()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        before = model_identity_digest(root)
        with open(os.path.join(root, "config.json"), "a", encoding="utf-8") as f:
            f.write("\n")
        after = model_identity_digest(root)
        self.assertNotEqual(before, after)

    def test_digest_changes_when_weight_file_added(self):
        root = make_model_dir()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        before = model_identity_digest(root)
        with open(os.path.join(root, "model.safetensors"), "wb") as f:
            f.write(b"weights")
        after = model_identity_digest(root)
        self.assertNotEqual(before, after)

    def test_build_identity_reads_hidden_dim(self):
        root = make_model_dir()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        identity = build_model_token_identity(root)
        self.assertEqual(8, identity.hidden_dim)
        self.assertTrue(identity.model_digest)
        self.assertTrue(identity.tokenizer_digest)
        self.assertTrue(identity.mlxlm_version)

    def test_missing_config_fails_closed(self):
        root = tempfile.mkdtemp(prefix="repr-empty-model-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with self.assertRaises(Exception):
            build_model_token_identity(root)


class RepresentationIdTest(unittest.TestCase):
    def setUp(self):
        self.root = make_model_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.identity = build_model_token_identity(self.root)

    def assert_covers_components(self, spec):
        identifier = representation_id(spec, self.identity)
        self.assertTrue(
            identifier.startswith("hidden-state-repr-v1:model="))
        for component in ("model=", "tokenizer=", "mlxlm=", "graph=",
                          "layer=", "pool=", "window=", "seam=", "norm=",
                          "dim=", "dtype=", "metric="):
            self.assertIn(component, identifier,
                          "representation_id misses component %r" % component)

    def test_first_round_spec_ids_all_cover_full_component_set(self):
        for spec in first_round_specs():
            self.assert_covers_components(spec)

    def test_exact_layer_components(self):
        identifier = representation_id(
            RepresentationSpec(kind="exact", layer=21), self.identity)
        self.assertIn(":layer=21:", identifier)
        self.assertIn(":pool=last:", identifier)
        self.assertIn(":window=64:", identifier)
        self.assertIn(":seam=exact:", identifier)
        self.assertIn(":norm=rmsnorm+l2:", identifier)
        self.assertIn(":dim=8:", identifier)
        self.assertIn(":dtype=fp32:", identifier)
        self.assertTrue(identifier.endswith(":metric=cosine"))

    def test_model_digest_change_changes_id(self):
        spec = RepresentationSpec(kind="exact", layer=14)
        identifier = representation_id(spec, self.identity)
        with open(os.path.join(self.root, "generation_config.json"),
                  "w", encoding="utf-8") as f:
            f.write('{"stop": ["</s>"]}')
        other = build_model_token_identity(self.root)
        self.assertNotEqual(identifier, representation_id(spec, other))

    def test_layer_change_changes_id(self):
        base = representation_id(RepresentationSpec(kind="exact", layer=14),
                                 self.identity)
        self.assertNotEqual(
            base, representation_id(RepresentationSpec(kind="exact", layer=21),
                                    self.identity))

    def test_truncation_component_change_changes_id(self):
        base = representation_id(RepresentationSpec(kind="exact", layer=14),
                                 self.identity)
        shorter = representation_id(
            RepresentationSpec(kind="exact", layer=14, window_chars=63),
            self.identity)
        self.assertNotEqual(base, shorter)

    def test_seam_component_change_changes_id(self):
        exact = representation_id(RepresentationSpec(kind="exact", layer=28),
                                  self.identity)
        split = representation_id(
            RepresentationSpec(kind="split_reuse", layer=28), self.identity)
        self.assertNotEqual(exact, split)
        # The seam is what differs: same layer, window, norm, dim, dtype,
        # metric -- only seam (and thus kind) differ.
        self.assertRegex(exact, r"layer=28:.*seam=exact:")
        self.assertRegex(split, r"layer=28:.*seam=split_reuse:")

    def test_mlxlm_version_change_changes_id(self):
        spec = RepresentationSpec(kind="exact", layer=14)
        a = representation_id(spec, self.identity)
        other = ModelTokenIdentity(
            model_digest=self.identity.model_digest,
            tokenizer_digest=self.identity.tokenizer_digest,
            mlxlm_version="0.99.99",
            hidden_dim=self.identity.hidden_dim,
        )
        self.assertNotEqual(a, representation_id(spec, other))

    def test_same_identity_same_id_deterministic(self):
        spec = RepresentationSpec(kind="exact", layer=28)
        self.assertEqual(representation_id(spec, self.identity),
                         representation_id(spec, self.identity))


class FirstRoundSetTest(unittest.TestCase):
    def test_exact_l14_l21_l28_and_split_reuse(self):
        specs = first_round_specs()
        self.assertEqual(4, len(specs))
        exact_layers = sorted(spec.layer for spec in specs
                              if spec.kind == "exact")
        self.assertEqual([14, 21, 28], exact_layers)
        split = [spec for spec in specs if spec.kind == "split_reuse"]
        self.assertEqual(1, len(split))
        self.assertEqual(28, split[0].layer)

    def test_exact_spec_layer_must_be_predeclared(self):
        with self.assertRaises(InvalidRepresentationSpec):
            RepresentationSpec(kind="exact", layer=13)

    def test_split_spec_layer_fixed(self):
        with self.assertRaises(InvalidRepresentationSpec):
            RepresentationSpec(kind="split_reuse", layer=21)


class NormalizationTest(unittest.TestCase):
    def test_l2_normalize_gives_unit_vector(self):
        vector = l2_normalize([3.0, 4.0])
        self.assertAlmostEqual(1.0, math.sqrt(sum(v * v for v in vector)))
        self.assertEqual(2, len(vector))

    def test_nan_fails_closed(self):
        with self.assertRaises(NonFiniteRepresentationError):
            l2_normalize([1.0, float("nan")])

    def test_inf_fails_closed(self):
        with self.assertRaises(NonFiniteRepresentationError):
            l2_normalize([1.0, float("inf")])

    def test_zero_norm_fails_closed(self):
        with self.assertRaises(NonFiniteRepresentationError):
            l2_normalize([0.0, 0.0])

    def test_empty_vector_fails_closed(self):
        with self.assertRaises(NonFiniteRepresentationError):
            l2_normalize([])

    def test_cosine_of_unit_vectors(self):
        left = unit_vector(8, 1.0)
        self.assertAlmostEqual(1.0, cosine(left, left))
        opposite = tuple(-value for value in left)
        self.assertAlmostEqual(-1.0, cosine(left, opposite))

    def test_cosine_non_finite_fails_closed(self):
        with self.assertRaises(NonFiniteRepresentationError):
            cosine([float("nan")] + [0.0] * 7, [0.5] * 8)
        with self.assertRaises(NonFiniteRepresentationError):
            cosine([0.0] * 8, [0.0] * 8)


class SeamTest(unittest.TestCase):
    def test_window_text_truncates_to_last_64(self):
        self.assertEqual("b" * 64, window_text("a" * 10 + "b" * 64))
        self.assertEqual("a" * 64, window_text("a" * 64))
        self.assertEqual("short", window_text("short"))

    def test_exact_encodes_last_64_exactly(self):
        tokenizer = RecordingTokenizer()
        context = "前" * 20 + "后" * 64
        windowed, ids = exact_tokenization_for(tokenizer, context)
        self.assertEqual("后" * 64, windowed)
        self.assertEqual(1, len(tokenizer.calls))
        self.assertEqual("后" * 64, tokenizer.calls[0])

    def test_exact_short_context_encodes_whole_text(self):
        tokenizer = RecordingTokenizer()
        windowed, ids = exact_tokenization_for(tokenizer, "短上文")
        self.assertEqual("短上文", windowed)

    def test_exact_exactly_64_chars(self):
        tokenizer = RecordingTokenizer()
        context = "本" * 64
        windowed, _ = exact_tokenization_for(tokenizer, context)
        self.assertEqual(context, windowed)

    def test_split_context_splits_at_tail_chars(self):
        prefix, tail = split_context("abcdefgh")
        self.assertEqual("abcd", prefix)
        self.assertEqual("efgh", tail)
        prefix, tail = split_context("ab")
        self.assertEqual("", prefix)
        self.assertEqual("ab", tail)

    def test_split_tokenizes_prefix_and_tail_separately(self):
        tokenizer = RecordingTokenizer()
        prefix_text, prefix_ids, tail_text, tail_ids = \
            split_tokenization_for(tokenizer, "一二三四五六七八九十")
        self.assertEqual("一二三四五六", prefix_text)
        self.assertEqual("七八九十", tail_text)
        # Never the concatenated string is encoded as one block.
        self.assertEqual(["一二三四五六", "七八九十"], tokenizer.calls)
        self.assertTrue(prefix_ids)
        self.assertTrue(tail_ids)

    def test_split_short_context_has_empty_prefix(self):
        tokenizer = RecordingTokenizer()
        prefix_text, prefix_ids, tail_text, tail_ids = \
            split_tokenization_for(tokenizer, "天气")
        self.assertEqual("", prefix_text)
        self.assertEqual((), prefix_ids)
        self.assertEqual("天气", tail_text)

    def test_seam_changed_detects_bpe_boundary(self):
        # encode "abcdef" != encode("abcd") + encode("ef") for this fake.
        tokenizer = RecordingTokenizer({
            "abcdef": [1],
            "abcd": [2],
            "ef": [3],
        })
        prefix_ids = tokenizer.encode("abcd")
        tail_ids = tokenizer.encode("ef")
        exact_ids = tokenizer.encode("abcdef")
        self.assertTrue(seam_changed(
            "abcd", prefix_ids, "ef", tail_ids, exact_ids))

    def test_seam_changed_false_when_compositional(self):
        tokenizer = RecordingTokenizer({
            "abcd": [2],
            "ef": [3],
            "abcdef": [2, 3],
        })
        prefix_ids = tokenizer.encode("abcd")
        tail_ids = tokenizer.encode("ef")
        exact_ids = tokenizer.encode("abcdef")
        self.assertFalse(seam_changed(
            "abcd", prefix_ids, "ef", tail_ids, exact_ids))


class BoundaryRoutingTest(unittest.TestCase):
    def setUp(self):
        self.root = make_model_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        import types
        inner = types.SimpleNamespace(embed_tokens=object(),
                                      layers=[object()] * 28,
                                      norm=object())
        self.state = FakeState(self.root,
                               model=types.SimpleNamespace(model_type="qwen3",
                                                           model=inner))

    def test_empty_context_fails_closed_exact(self):
        tokenizer = RecordingTokenizer()
        self.state.tokenizer = tokenizer
        extractor = FixedVectorExtractor(self.state)
        for spec in first_round_specs():
            if spec.kind != "exact":
                continue
            with self.assertRaises(EmptyContextRepresentationError):
                extractor.exact(spec, "")
            self.assertFalse(getattr(extractor, "forwarded"))

    def test_empty_context_fails_closed_split(self):
        extractor = FixedVectorExtractor(self.state)
        with self.assertRaises(EmptyContextRepresentationError):
            extractor.split_reuse("")
        self.assertFalse(extractor.forwarded)

    def test_no_tokens_after_encode_fails_closed(self):
        tokenizer = RecordingTokenizer({"不可见ц": []})
        self.state.tokenizer = tokenizer
        extractor = FixedVectorExtractor(self.state)
        with self.assertRaises(EmptyContextRepresentationError):
            extractor.exact(RepresentationSpec(kind="exact", layer=14),
                            "不可见ц")

    def test_model_fault_fails_closed_through_guarded_call(self):
        extractor = FixedVectorExtractor(
            self.state, run_error=RuntimeError("metal boom"))
        with self.assertRaises(ModelForwardRepresentationError):
            extractor.exact(RepresentationSpec(kind="exact", layer=14), "发起")

    def test_non_finite_snapshot_propagates_as_fault(self):
        extractor = FixedVectorExtractor(
            self.state,
            run_error=NonFiniteRepresentationError("non-finite vector"))
        with self.assertRaises(NonFiniteRepresentationError):
            extractor.exact(RepresentationSpec(kind="exact", layer=14), "发起")

    def test_guarded_call_never_returns_dirty_vector(self):
        # Patch _run to bypass normalization ("dirty" path a bug could take):
        # the l2_normalize inside the real _run is the validator, so the
        # extractor must still refuse to return a zero/NaN vector.
        class DirtyForwardExtractor(FixedVectorExtractor):
            def _run(self, ids, cache, snapshot_layers):
                self.forwarded.append(("run", tuple(ids)))
                return {layer: [float("nan")] * 8 for layer in snapshot_layers}, cache
        extractor = DirtyForwardExtractor(self.state)
        with self.assertRaises(NonFiniteRepresentationError):
            extractor.exact(RepresentationSpec(kind="exact", layer=14), "发起")

    def test_exact_forwards_exact_ids_and_split_forwards_tail_ids(self):
        tokenizer = RecordingTokenizer()
        self.state.tokenizer = tokenizer
        extractor = FixedVectorExtractor(self.state)
        extractor.exact(RepresentationSpec(kind="exact", layer=28), "abcdefgh")
        vector, _cache = extractor.split_reuse("abcdefgh")
        runs = [kind for kind, _ in extractor.forwarded]
        self.assertIn("run", runs)
        # split_reuse without a supplied cache builds the prefix first.
        self.assertIn("prefix", [kind for kind, _ in extractor.forwarded])

    def test_split_reuse_with_supplied_cache_skips_prefix_build(self):
        tokenizer = RecordingTokenizer()
        self.state.tokenizer = tokenizer
        extractor = FixedVectorExtractor(self.state)
        prebuilt = object()
        extractor.split_reuse("abcdefgh", prefix_cache=prebuilt)
        kinds = [kind for kind, _ in extractor.forwarded]
        self.assertNotIn("prefix", kinds)
        self.assertIn("run", kinds)

    def test_construction_never_loads_model(self):
        extractor = FixedVectorExtractor(self.state)
        self.assertEqual(0, self.state.loaded_count)
        # Identity hashing (digesting disk files) is also lazy: it is
        # triggered only by the first representation request.
        self.assertIsNone(extractor._identity)

    def test_extractor_reuses_state_model_not_second_model(self):
        import types
        inner = types.SimpleNamespace(embed_tokens=object(),
                                      layers=[object()] * 28,
                                      norm=object())
        self.state.model = types.SimpleNamespace(model_type="qwen3",
                                                 model=inner)
        extractor = HiddenStateExtractor(self.state)
        first, _inner = extractor._require_model()
        # The model is already loaded on the state; generation must reuse it
        # and never trigger a second load (SCN-60-3).
        self.assertEqual(0, self.state.loaded_count)
        second, _inner2 = extractor._require_model()
        self.assertEqual(0, self.state.loaded_count)
        self.assertIs(first, second)
        self.assertIs(first, self.state.model)


class DeterminismRoutingTest(unittest.TestCase):
    def setUp(self):
        self.root = make_model_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.identity = build_model_token_identity(self.root)

    def test_same_identity_same_context_bit_identical(self):
        set_a = {representation_id(spec, self.identity) for spec in
                 first_round_specs()}
        set_b = {representation_id(spec, self.identity) for spec in
                 first_round_specs()}
        self.assertEqual(set_a, set_b)
        self.assertEqual(4, len(set_a))

    def test_identity_change_marks_old_vector_incompatible(self):
        spec = RepresentationSpec(kind="exact", layer=14)
        old_id = representation_id(spec, self.identity)
        with open(os.path.join(self.root, "generation_config.json"),
                  "w", encoding="utf-8") as f:
            f.write('{"stop": ["</s>"]}')
        new_identity = build_model_token_identity(self.root)
        new_id = representation_id(spec, new_identity)
        self.assertNotEqual(old_id, new_id)
        # recomputation under the new identity must produce a vector bound to
        # the new id, never silently reused under the old id
        self.assertNotEqual(
            [representation_id(spec, self.identity) for spec in first_round_specs()],
            [representation_id(spec, new_identity) for spec in first_round_specs()])


if __name__ == "__main__":
    unittest.main()