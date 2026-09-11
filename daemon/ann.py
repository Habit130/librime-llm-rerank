#!/usr/bin/env python3
"""ANN retrieval path (USearch #78, hnswlib #79).

Approximate neighbor retrieval only.  The exact oracle in ``oracle.py``
remains ground truth: same-key active events, cosine → r_i → d_i → a_i,
then take K_evidence.  ANN overfetch is FP32-reranked, merged with the
exact delta, then K / aggregate / emission.  Cosine top-K is never ground
truth.  Index or identity faults fail closed; the exact path is not a
semantic fallback.
"""

import hashlib
import json
import math
import os
import shutil
import tempfile

from oracle import (
    CandidateEvidence,
    EventContribution,
    OracleError,
    OracleParams,
    OracleQuery,
    OracleResult,
    match_text,
)

USEARCH_BACKEND = "usearch-hnsw"
USEARCH_METRIC = "cos"
USEARCH_DTYPE = "f32"
USEARCH_LIBRARY_VERSION = "usearch-hnsw-v1"
USEARCH_SERIALIZATION_ABI = "usearch-index-v1-arm64"
HNSWLIB_BACKEND = "hnswlib-hnsw"
HNSWLIB_METRIC = "cosine"
HNSWLIB_DTYPE = "f32"
HNSWLIB_LIBRARY_VERSION = "hnswlib-hnsw-v1"
HNSWLIB_SERIALIZATION_ABI = "hnswlib-index-v1-arm64"
OVERFETCH_MULTIPLIERS = (2, 4, 8)
OVERFETCH_FLOOR = 32
ANN_SIDECAR_NAME = "index.ann"
ANN_META_NAME = "index.meta.json"
ANN_KEYS_NAME = "index.keys.json"
ANN_SEED = 20260817

BUILD_PRESETS = (
    {"preset_id": "m8-e64", "connectivity": 8, "expansion_add": 64},
    {"preset_id": "m16-e128", "connectivity": 16, "expansion_add": 128},
    {"preset_id": "m16-e256", "connectivity": 16, "expansion_add": 256},
    {"preset_id": "m32-e128", "connectivity": 32, "expansion_add": 128},
)
QUERY_SEARCH_VALUES = (16, 32, 64, 128)
HNSWLIB_BUILD_PRESETS = (
    {"preset_id": "m8-efc100", "M": 8, "ef_construction": 100},
    {"preset_id": "m16-efc200", "M": 16, "ef_construction": 200},
    {"preset_id": "m16-efc400", "M": 16, "ef_construction": 400},
    {"preset_id": "m32-efc200", "M": 32, "ef_construction": 200},
)
HNSWLIB_QUERY_SEARCH_VALUES = (32, 64, 128, 256)


class AnnError(Exception):
    """A true ANN-path fault. Never silent exact fallback."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def overfetch_count(k_evidence, multiplier):
    if not isinstance(k_evidence, int) or k_evidence < 1:
        raise AnnError("ann_config", "k_evidence must be a positive int")
    if multiplier not in OVERFETCH_MULTIPLIERS:
        raise AnnError("ann_config", "overfetch multiplier must be 2, 4 or 8")
    return max(OVERFETCH_FLOOR, int(multiplier) * int(k_evidence))


def usearch_library_version():
    try:
        import usearch
    except ImportError:
        return USEARCH_LIBRARY_VERSION
    package = getattr(usearch, "__version__", "unknown")
    return "%s+usearch-%s" % (USEARCH_LIBRARY_VERSION, package)


def compose_usearch_build_params(preset):
    return {
        "connectivity": int(preset["connectivity"]),
        "expansion_add": int(preset["expansion_add"]),
    }


def hnswlib_library_version():
    try:
        import hnswlib
    except ImportError:
        return HNSWLIB_LIBRARY_VERSION
    package = getattr(hnswlib, "__version__", "unknown")
    return "%s+hnswlib-%s" % (HNSWLIB_LIBRARY_VERSION, package)


def compose_hnswlib_build_params(preset):
    return {
        "M": int(preset["M"]),
        "ef_construction": int(preset["ef_construction"]),
    }


def _infer_ann_backend(build_params, backend=None):
    if backend:
        return backend
    if build_params and "M" in build_params:
        return HNSWLIB_BACKEND
    return USEARCH_BACKEND


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _sha256_hex(content):
    return hashlib.sha256(content).hexdigest()


def _as_float_vector(vector, label):
    if vector is None:
        raise OracleError("%s is missing" % label)
    try:
        values = tuple(float(value) for value in vector)
    except (TypeError, ValueError) as error:
        raise OracleError("%s is not a numeric vector" % label) from error
    if not values:
        raise OracleError("%s is empty" % label)
    for value in values:
        if not math.isfinite(value):
            raise OracleError("%s is not finite" % label)
    return values


def _cosine(query_vector, event_vector):
    dot = 0.0
    query_norm = 0.0
    event_norm = 0.0
    for query_value, event_value in zip(query_vector, event_vector):
        dot += query_value * event_value
        query_norm += query_value * query_value
        event_norm += event_value * event_value
    if query_norm == 0.0 or event_norm == 0.0:
        raise OracleError("cosine requires non-zero vectors")
    return dot / math.sqrt(query_norm * event_norm)


def _age_factor(usage_age, half_life):
    if math.isinf(half_life):
        return 1.0
    return 2.0 ** (-usage_age / half_life)


def sidecar_dir(derived_root, generation_id):
    return os.path.join(derived_root, "index", generation_id)


def sidecar_path(derived_root, generation_id, name=ANN_SIDECAR_NAME):
    return os.path.join(sidecar_dir(derived_root, generation_id), name)


class NeighborIndex:
    """Neighbor retrieval over one published ANN generation."""

    def event_ids(self):
        raise NotImplementedError

    def search(self, query_vector, count, query_search=None):
        raise NotImplementedError

    def save(self, directory, meta):
        raise NotImplementedError


class BruteForceIndex(NeighborIndex):
    """Exact cosine top-N used by model-free tests (not a production ANN)."""

    def __init__(self, ids, vectors, dimension=None):
        if len(ids) != len(vectors):
            raise AnnError("ann_index", "ids and vectors length mismatch")
        self._ids = tuple(ids)
        self._vectors = tuple(_as_float_vector(vector, "ann vector")
                              for vector in vectors)
        if dimension is None:
            dimension = len(self._vectors[0]) if self._vectors else 0
        for vector in self._vectors:
            if len(vector) != dimension:
                raise AnnError("ann_index", "vector dimension mismatch")
        self._dimension = dimension
        self._by_id = {event_id: vector
                       for event_id, vector in zip(self._ids, self._vectors)}

    def event_ids(self):
        return self._ids

    def dimension(self):
        return self._dimension

    def add(self, event_id, vector):
        vector = _as_float_vector(vector, "ann vector")
        if self._dimension and len(vector) != self._dimension:
            raise AnnError("ann_index", "vector dimension mismatch")
        if not self._dimension:
            self._dimension = len(vector)
        self._ids = self._ids + (event_id,)
        self._vectors = self._vectors + (vector,)
        self._by_id[event_id] = vector

    def search(self, query_vector, count, query_search=None):
        del query_search
        if count < 1:
            return []
        query = _as_float_vector(query_vector, "ann query")
        if self._dimension and len(query) != self._dimension:
            raise AnnError("ann_index", "query dimension mismatch")
        ranked = []
        for event_id, vector in zip(self._ids, self._vectors):
            ranked.append((_cosine(query, vector), event_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [event_id for _cosine_value, event_id in ranked[:count]]

    def save(self, directory, meta):
        os.makedirs(directory, mode=0o700, exist_ok=True)
        payload = {
            "ids": list(self._ids),
            "vectors": [list(vector) for vector in self._vectors],
            "dimension": self._dimension,
        }
        _atomic_write_json(os.path.join(directory, "brute.json"), payload)
        _atomic_write_json(os.path.join(directory, ANN_KEYS_NAME),
                           list(self._ids))
        _atomic_write_json(os.path.join(directory, ANN_META_NAME), meta)
        marker = os.path.join(directory, ANN_SIDECAR_NAME)
        _atomic_write_bytes(marker, b"brute-force-index-v1\n")

    @classmethod
    def load(cls, directory):
        meta = _read_json(os.path.join(directory, ANN_META_NAME))
        payload = _read_json(os.path.join(directory, "brute.json"))
        index = cls(payload["ids"], payload["vectors"],
                    dimension=payload.get("dimension"))
        return index, meta


class USearchIndex(NeighborIndex):
    """USearch HNSW sidecar bound to one FP32 generation."""

    def __init__(self, index, ids, dimension, build_params, query_search=None):
        self._index = index
        self._ids = tuple(ids)
        self._id_of_key = {index_key: event_id
                           for index_key, event_id in enumerate(self._ids)}
        self._dimension = dimension
        self._build_params = dict(build_params)
        self._query_search = query_search

    def event_ids(self):
        return self._ids

    def dimension(self):
        return self._dimension

    def add(self, event_id, vector):
        vector = _as_float_vector(vector, "ann vector")
        if len(vector) != self._dimension:
            raise AnnError("ann_index", "vector dimension mismatch")
        key = len(self._ids)
        try:
            import numpy
            self._index.add(
                numpy.uint64(key),
                numpy.asarray(vector, dtype=numpy.float32))
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index", "usearch add failed: %s" % error) from error
        self._id_of_key[key] = event_id
        self._ids = self._ids + (event_id,)

    def search(self, query_vector, count, query_search=None):
        if count < 1:
            return []
        if not self._ids:
            return []
        query = _as_float_vector(query_vector, "ann query")
        if len(query) != self._dimension:
            raise AnnError("ann_index", "query dimension mismatch")
        expansion = (query_search if query_search is not None
                     else self._query_search)
        try:
            import numpy
            if expansion is not None:
                self._index.expansion_search = int(expansion)
            matches = self._index.search(
                numpy.asarray(query, dtype=numpy.float32),
                int(count))
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index", "usearch search failed: %s" % error) from error
        keys = getattr(matches, "keys", matches)
        try:
            key_list = list(keys)
        except TypeError:
            key_list = [keys]
        out = []
        for key in key_list:
            if hasattr(key, "__iter__") and not isinstance(key, (str, bytes)):
                inner = list(key)
                if not inner:
                    continue
                key = inner[0]
            event_id = self._id_of_key.get(int(key))
            if event_id is not None:
                out.append(event_id)
        return out[:count]

    def save(self, directory, meta):
        os.makedirs(directory, mode=0o700, exist_ok=True)
        tmp = directory + ".tmp-%s" % os.getpid()
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp, mode=0o700)
        try:
            self._index.save(os.path.join(tmp, ANN_SIDECAR_NAME))
            _atomic_write_json(os.path.join(tmp, ANN_KEYS_NAME),
                               list(self._ids))
            _atomic_write_json(os.path.join(tmp, ANN_META_NAME), meta)
            _replace_directory(tmp, directory)
        finally:
            if os.path.exists(tmp):
                shutil.rmtree(tmp, ignore_errors=True)

    @classmethod
    def build(cls, ids, vectors, dimension, build_params, query_search=None):
        usearch_index = _make_usearch_index(dimension, build_params,
                                            query_search)
        if ids:
            import numpy
            matrix = numpy.asarray(vectors, dtype=numpy.float32)
            keys = numpy.arange(len(ids), dtype=numpy.uint64)
            usearch_index.add(keys, matrix)
        return cls(usearch_index, ids, dimension, build_params, query_search)

    @classmethod
    def load(cls, directory, query_search=None):
        meta = _read_json(os.path.join(directory, ANN_META_NAME))
        _validate_usearch_meta(meta)
        ids = _read_json(os.path.join(directory, ANN_KEYS_NAME))
        if not isinstance(ids, list):
            raise AnnError("ann_identity", "ANN key list is not a list")
        path = os.path.join(directory, ANN_SIDECAR_NAME)
        try:
            from usearch.index import Index
            loaded = Index.restore(path)
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index",
                           "usearch restore failed: %s" % error) from error
        build_params = dict(meta.get("build_params") or {})
        dimension = int(meta["dimension"])
        return cls(loaded, ids, dimension, build_params, query_search), meta


class HnswlibIndex(NeighborIndex):
    """hnswlib HNSW sidecar bound to one FP32 generation."""

    def __init__(self, index, ids, dimension, build_params, query_search=None):
        self._index = index
        self._ids = tuple(ids)
        self._id_of_key = {index_key: event_id
                           for index_key, event_id in enumerate(self._ids)}
        self._dimension = dimension
        self._build_params = dict(build_params)
        self._query_search = query_search

    def event_ids(self):
        return self._ids

    def dimension(self):
        return self._dimension

    def _ensure_capacity(self, needed):
        current_max = int(self._index.get_max_elements())
        if needed <= current_max:
            return
        grown = max(needed, current_max * 2, 1024)
        try:
            self._index.resize_index(grown)
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index",
                           "hnswlib resize failed: %s" % error) from error

    def add(self, event_id, vector):
        vector = _as_float_vector(vector, "ann vector")
        if len(vector) != self._dimension:
            raise AnnError("ann_index", "vector dimension mismatch")
        key = len(self._ids)
        self._ensure_capacity(key + 1)
        try:
            import numpy
            self._index.add_items(
                numpy.asarray([vector], dtype=numpy.float32),
                numpy.asarray([key], dtype=numpy.int64))
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index",
                           "hnswlib add failed: %s" % error) from error
        self._id_of_key[key] = event_id
        self._ids = self._ids + (event_id,)

    def search(self, query_vector, count, query_search=None):
        if count < 1:
            return []
        if not self._ids:
            return []
        query = _as_float_vector(query_vector, "ann query")
        if len(query) != self._dimension:
            raise AnnError("ann_index", "query dimension mismatch")
        expansion = (query_search if query_search is not None
                     else self._query_search)
        k = min(int(count), len(self._ids))
        if k < 1:
            return []
        try:
            import numpy
            if expansion is not None:
                self._index.set_ef(max(int(expansion), k))
            labels, _distances = self._index.knn_query(
                numpy.asarray(query, dtype=numpy.float32), k=k)
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index",
                           "hnswlib search failed: %s" % error) from error
        out = []
        if labels is None:
            return out
        flat = numpy.asarray(labels).reshape(-1)
        for key in flat:
            event_id = self._id_of_key.get(int(key))
            if event_id is not None:
                out.append(event_id)
        return out[:count]

    def save(self, directory, meta):
        os.makedirs(directory, mode=0o700, exist_ok=True)
        tmp = directory + ".tmp-%s" % os.getpid()
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp, mode=0o700)
        try:
            self._index.save_index(os.path.join(tmp, ANN_SIDECAR_NAME))
            _atomic_write_json(os.path.join(tmp, ANN_KEYS_NAME),
                               list(self._ids))
            _atomic_write_json(os.path.join(tmp, ANN_META_NAME), meta)
            _replace_directory(tmp, directory)
        finally:
            if os.path.exists(tmp):
                shutil.rmtree(tmp, ignore_errors=True)

    @classmethod
    def build(cls, ids, vectors, dimension, build_params, query_search=None):
        hnsw_index = _make_hnswlib_index(
            dimension, build_params, query_search,
            max_elements=max(len(ids), 1024))
        if ids:
            import numpy
            matrix = numpy.asarray(vectors, dtype=numpy.float32)
            keys = numpy.arange(len(ids), dtype=numpy.int64)
            hnsw_index.add_items(matrix, keys)
        return cls(hnsw_index, ids, dimension, build_params, query_search)

    @classmethod
    def load(cls, directory, query_search=None):
        meta = _read_json(os.path.join(directory, ANN_META_NAME))
        _validate_hnswlib_meta(meta)
        ids = _read_json(os.path.join(directory, ANN_KEYS_NAME))
        if not isinstance(ids, list):
            raise AnnError("ann_identity", "ANN key list is not a list")
        path = os.path.join(directory, ANN_SIDECAR_NAME)
        dimension = int(meta["dimension"])
        build_params = dict(meta.get("build_params") or {})
        try:
            loaded = _make_hnswlib_index(
                dimension, build_params, query_search,
                max_elements=max(len(ids), 1024), initialize=False)
            loaded.load_index(path, max_elements=max(len(ids), 1024))
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index",
                           "hnswlib load failed: %s" % error) from error
        if query_search is not None:
            try:
                loaded.set_ef(int(query_search))
            except Exception as error:  # noqa: BLE001
                raise AnnError("ann_index",
                               "hnswlib set_ef failed: %s" % error) from error
        return cls(loaded, ids, dimension, build_params, query_search), meta


def _make_usearch_index(dimension, build_params, query_search):
    try:
        from usearch.index import Index
    except ImportError as error:
        raise AnnError("ann_unavailable",
                       "usearch is not installed") from error
    kwargs = {
        "ndim": int(dimension),
        "metric": USEARCH_METRIC,
        "dtype": USEARCH_DTYPE,
        "connectivity": int(build_params["connectivity"]),
        "expansion_add": int(build_params["expansion_add"]),
    }
    if query_search is not None:
        kwargs["expansion_search"] = int(query_search)
    try:
        return Index(**kwargs)
    except Exception as error:  # noqa: BLE001 - fail closed
        raise AnnError("ann_index",
                       "usearch index construct failed: %s" % error) from error


def _make_hnswlib_index(dimension, build_params, query_search,
                        max_elements=1024, initialize=True):
    try:
        import hnswlib
    except ImportError as error:
        raise AnnError("ann_unavailable",
                       "hnswlib is not installed") from error
    try:
        index = hnswlib.Index(space=HNSWLIB_METRIC, dim=int(dimension))
        if initialize:
            index.init_index(
                max_elements=max(int(max_elements), 1),
                ef_construction=int(build_params["ef_construction"]),
                M=int(build_params["M"]))
        if query_search is not None:
            index.set_ef(int(query_search))
        return index
    except AnnError:
        raise
    except Exception as error:  # noqa: BLE001 - fail closed
        raise AnnError("ann_index",
                       "hnswlib index construct failed: %s" % error) from error


def _validate_usearch_meta(meta):
    if not isinstance(meta, dict):
        raise AnnError("ann_identity", "ANN meta is not an object")
    if meta.get("backend") != USEARCH_BACKEND:
        raise AnnError("ann_identity", "unknown ANN backend")
    if meta.get("metric") != USEARCH_METRIC:
        raise AnnError("ann_identity", "unknown ANN metric")
    if meta.get("dtype") != USEARCH_DTYPE:
        raise AnnError("ann_identity", "unknown ANN dtype")
    if meta.get("serialization_abi") != USEARCH_SERIALIZATION_ABI:
        raise AnnError("ann_identity", "unknown ANN serialization ABI")
    fingerprint = meta.get("index_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.startswith(
            "index-fingerprint-v1:"):
        raise AnnError("ann_identity", "unknown ANN index fingerprint")
    dimension = meta.get("dimension")
    if not isinstance(dimension, int) or dimension < 1:
        raise AnnError("ann_identity", "ANN dimension missing")


def _validate_hnswlib_meta(meta):
    if not isinstance(meta, dict):
        raise AnnError("ann_identity", "ANN meta is not an object")
    if meta.get("backend") != HNSWLIB_BACKEND:
        raise AnnError("ann_identity", "unknown ANN backend")
    if meta.get("metric") != HNSWLIB_METRIC:
        raise AnnError("ann_identity", "unknown ANN metric")
    if meta.get("dtype") != HNSWLIB_DTYPE:
        raise AnnError("ann_identity", "unknown ANN dtype")
    if meta.get("serialization_abi") != HNSWLIB_SERIALIZATION_ABI:
        raise AnnError("ann_identity", "unknown ANN serialization ABI")
    fingerprint = meta.get("index_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.startswith(
            "index-fingerprint-v1:"):
        raise AnnError("ann_identity", "unknown ANN index fingerprint")
    dimension = meta.get("dimension")
    if not isinstance(dimension, int) or dimension < 1:
        raise AnnError("ann_identity", "ANN dimension missing")
    params = meta.get("build_params") or {}
    if "M" not in params or "ef_construction" not in params:
        raise AnnError("ann_identity", "hnswlib build params missing")


def load_ann_sidecar(directory, expected_fingerprint=None,
                     expected_generation_id=None, query_search=None):
    meta_path = os.path.join(directory, ANN_META_NAME)
    if not os.path.isfile(meta_path):
        raise AnnError("ann_index", "ANN sidecar meta missing")
    meta = _read_json(meta_path)
    backend = meta.get("backend")
    if expected_fingerprint is not None \
            and meta.get("index_fingerprint") != expected_fingerprint:
        raise AnnError("ann_identity", "ANN index fingerprint mismatch")
    if expected_generation_id is not None \
            and meta.get("generation_id") != expected_generation_id:
        raise AnnError("ann_identity", "mixed-generation ANN refuse")
    if backend == "brute-force":
        return BruteForceIndex.load(directory)
    if backend == USEARCH_BACKEND:
        return USearchIndex.load(directory, query_search=query_search)
    if backend == HNSWLIB_BACKEND:
        return HnswlibIndex.load(directory, query_search=query_search)
    raise AnnError("ann_identity", "unknown ANN backend")


def build_ann_from_fp32(generation, build_params, query_search=None,
                        backend=None):
    ids = list(generation.event_ids())
    vectors = [generation.event_vector(event_id) for event_id in ids]
    dimension = generation.vector_dimension
    backend = _infer_ann_backend(build_params, backend)
    if backend == HNSWLIB_BACKEND:
        return HnswlibIndex.build(ids, vectors, dimension, build_params,
                                  query_search=query_search)
    return USearchIndex.build(ids, vectors, dimension, build_params,
                              query_search=query_search)


def publish_ann_sidecar(index, derived_root, generation_id, meta):
    directory = sidecar_dir(derived_root, generation_id)
    index.save(directory, meta)
    return directory


def rebuild_ann_from_generation(generation, derived_root, generation_id,
                                build_params, fingerprint, query_search=None,
                                backend=None):
    try:
        generation.event_ids()
        generation.event_vector(generation.event_ids()[0]) if generation.event_ids() else None
    except Exception as error:  # noqa: BLE001 - unhealthy FP32
        raise AnnError("unhealthy_fp32",
                       "cannot rebuild ANN from unhealthy FP32: %s"
                       % error) from error
    backend = _infer_ann_backend(build_params, backend)
    index = build_ann_from_fp32(generation, build_params, query_search,
                                backend=backend)
    if backend == HNSWLIB_BACKEND:
        meta = {
            "backend": HNSWLIB_BACKEND,
            "metric": HNSWLIB_METRIC,
            "dtype": HNSWLIB_DTYPE,
            "dimension": generation.vector_dimension,
            "library_version": hnswlib_library_version(),
            "serialization_abi": HNSWLIB_SERIALIZATION_ABI,
            "build_params": compose_hnswlib_build_params(build_params),
            "index_fingerprint": fingerprint,
            "generation_id": generation_id,
            "event_count": len(index.event_ids()),
            "event_ids_sha256": _sha256_hex(
                "\0".join(index.event_ids()).encode("utf-8")),
        }
    else:
        meta = {
            "backend": USEARCH_BACKEND,
            "metric": USEARCH_METRIC,
            "dtype": USEARCH_DTYPE,
            "dimension": generation.vector_dimension,
            "library_version": usearch_library_version(),
            "serialization_abi": USEARCH_SERIALIZATION_ABI,
            "build_params": compose_usearch_build_params(
                {"connectivity": build_params["connectivity"],
                 "expansion_add": build_params["expansion_add"]}),
            "index_fingerprint": fingerprint,
            "generation_id": generation_id,
            "event_count": len(index.event_ids()),
            "event_ids_sha256": _sha256_hex(
                "\0".join(index.event_ids()).encode("utf-8")),
        }
    publish_ann_sidecar(index, derived_root, generation_id, meta)
    return index, meta


def compute_ann_evidence(reader, params, query, vector_for, neighbor_index,
                         overfetch, query_search=None, delta_ids=None):
    """ANN overfetch + FP32 rerank + exact delta, then oracle K/aggregate.

    Age clock uses every same-key active event.  Only overfetch hits and
    exact-delta ids receive a cosine.  Duplicate base/delta ids keep the
    delta copy.
    """
    if not isinstance(params, OracleParams):
        raise OracleError("params must be an OracleParams")
    if not isinstance(query, OracleQuery):
        raise OracleError("query must be an OracleQuery")
    if neighbor_index is None:
        raise AnnError("ann_index", "neighbor index missing")
    if overfetch < 1:
        raise AnnError("ann_config", "overfetch must be positive")

    as_of = query.as_of if query.as_of is not None else reader.default_as_of()
    candidates = tuple(match_text(candidate) for candidate in query.candidates)
    if query.is_candidate_conditioned:
        candidate_vectors = [
            _as_float_vector(vector, "query vector for candidate %d" % index)
            for index, vector in enumerate(query.candidate_query_vectors)
        ]
        query_vector = None
    else:
        candidate_vectors = None
        query_vector = _as_float_vector(query.query_vector, "query_vector")

    same_key = []
    query_key = query.key
    exclude = query.exclude_event_ids
    for event in reader.read_active_events(as_of):
        if event.event_id in exclude:
            continue
        if event.key == query_key:
            same_key.append(event)
    same_key.sort(key=lambda event: (event.hlc, event.event_id))

    same_key_ids = {event.event_id for event in same_key}
    base_ids = set(neighbor_index.event_ids())
    delta_set = set(delta_ids or ())
    allowed = set()
    if candidate_vectors is not None:
        for candidate_index, candidate_vector in enumerate(candidate_vectors):
            try:
                hits = neighbor_index.search(
                    candidate_vector, overfetch, query_search=query_search)
            except AnnError:
                raise
            except Exception as error:  # noqa: BLE001 - fail closed
                raise AnnError("ann_index",
                               "neighbor search failed: %s" % error) from error
            for event_id in hits:
                if event_id in delta_set:
                    continue
                allowed.add(event_id)
    else:
        try:
            hits = neighbor_index.search(
                query_vector, overfetch, query_search=query_search)
        except AnnError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise AnnError("ann_index",
                           "neighbor search failed: %s" % error) from error
        for event_id in hits:
            if event_id not in delta_set:
                allowed.add(event_id)
    allowed |= (delta_set & same_key_ids)
    allowed &= same_key_ids

    contributions = []
    if candidate_vectors is not None:
        for index, event in enumerate(same_key):
            if event.event_id not in allowed:
                continue
            selected = match_text(event.final_selection_text)
            matched = next((candidate_index for candidate_index, candidate
                            in enumerate(candidates)
                            if candidate == selected), None)
            if matched is None:
                continue
            try:
                vector = _as_float_vector(
                    vector_for(event.event_id),
                    "vector for event %s" % event.event_id)
            except Exception as error:
                raise OracleError(
                    "vector lookup failed for event %s" % event.event_id
                ) from error
            query_for_candidate = candidate_vectors[matched]
            if len(vector) != len(query_for_candidate):
                raise OracleError(
                    "vector dimension mismatch for event %s" % event.event_id)
            cosine = _cosine(query_for_candidate, vector)
            relevance = min(
                max((cosine - params.tau) / (1.0 - params.tau), 0.0), 1.0)
            usage_age = len(same_key) - 1 - index
            age_factor = _age_factor(usage_age, params.half_life)
            weight = relevance * age_factor
            contributions.append([event, cosine, relevance, usage_age,
                                  age_factor, weight, matched])
    else:
        for index, event in enumerate(same_key):
            if event.event_id not in allowed:
                continue
            try:
                vector = _as_float_vector(
                    vector_for(event.event_id),
                    "vector for event %s" % event.event_id)
            except Exception as error:
                raise OracleError(
                    "vector lookup failed for event %s" % event.event_id
                ) from error
            if len(vector) != len(query_vector):
                raise OracleError(
                    "vector dimension mismatch for event %s" % event.event_id)
            cosine = _cosine(query_vector, vector)
            relevance = min(
                max((cosine - params.tau) / (1.0 - params.tau), 0.0), 1.0)
            usage_age = len(same_key) - 1 - index
            age_factor = _age_factor(usage_age, params.half_life)
            weight = relevance * age_factor
            contributions.append([event, cosine, relevance, usage_age,
                                  age_factor, weight, None])

    passed = [entry for entry in contributions if entry[5] > 0.0]
    kept = sorted(passed, key=lambda entry:
                  (-entry[5], entry[0].hlc, entry[0].event_id))
    kept = kept[:params.k_evidence]
    if candidate_vectors is None:
        for entry in kept:
            normalized_selection = match_text(entry[0].final_selection_text)
            matched = -1
            for candidate_index, candidate in enumerate(candidates):
                if normalized_selection == candidate:
                    matched = candidate_index
                    break
            entry[6] = matched

    masses = [0.0] * len(candidates)
    for entry in kept:
        if entry[6] >= 0:
            masses[entry[6]] += entry[5]
    total_mass = sum(masses)
    candidate_evidence = []
    for candidate_index, candidate_mass in enumerate(masses):
        if total_mass > 0.0:
            share = candidate_mass / total_mass
            saturation = candidate_mass / (
                candidate_mass + params.saturation_k)
            score = share * saturation
        else:
            score = 0.0
        candidate_evidence.append((candidate_index, candidate_mass, score))

    return OracleResult(
        query_point=as_of,
        same_key_active=len(same_key),
        kept=tuple(EventContribution(
            event_id=entry[0].event_id,
            commit_id=entry[0].commit_id,
            hlc=entry[0].hlc,
            cosine=entry[1],
            relevance=entry[2],
            usage_age=entry[3],
            age_factor=entry[4],
            weight=entry[5],
            matched_candidate=entry[6]) for entry in kept),
        candidates=tuple(CandidateEvidence(
            index=index, m=mass, s=score)
            for index, mass, score in candidate_evidence),
        total_mass=total_mass,
        derived_key=query.key)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.loads(handle.read())
    except (OSError, ValueError) as error:
        raise AnnError("ann_index", "cannot read %s: %s" % (os.path.basename(path), error)) from error


def _atomic_write_json(path, value):
    _atomic_write_bytes(path, (_canonical_json(value) + "\n").encode("utf-8"))


def _atomic_write_bytes(path, payload):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ann-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _replace_directory(source, dest):
    parent = os.path.dirname(dest)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    backup = dest + ".bak"
    if os.path.exists(backup):
        shutil.rmtree(backup, ignore_errors=True)
    if os.path.exists(dest):
        os.rename(dest, backup)
    os.rename(source, dest)
    if os.path.exists(backup):
        shutil.rmtree(backup, ignore_errors=True)
    try:
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass
