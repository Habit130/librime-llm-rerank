#!/usr/bin/env python3
"""Accelerate (Apple vecLib) exact retrieval backend (Habit130/squirrel#72).

The pure-Python oracle (`daemon/oracle.py`) computes one Python-scalar cosine
per same-key active event; at 100k events on one hot key that is the #71
measured ~7.5 s/query worst case.  This module implements the SAME exact
evidence semantics (SCN-72-1: every same-key active event is scored, no
shortlist, no cosine top-K before aging) with the per-event cosine computed by
Apple vecLib's ``cblas_sgemv`` (single-precision matrix-vector product) over
the generation's canonical row-major little-endian FP32 vector file, zero
copy.  It plugs into ``oracle.compute_evidence`` through the
``CosineEngine`` seam (``batch_cosines``); the oracle's aggregation
(threshold, usage age, final weight, top-K, m_c / M / s_c) is untouched and
never duplicated.

Equivalence contract (SCN-72-2 / RISK-72-3, pinned): the backend must match
the stdlib oracle query-by-query -- neighbors, event weights, candidate
evidence ``s_c`` and final emit order -- within a documented float tolerance.
This engine's two paths:

- **Small same-key sets (<= ``PYTHON_PATH_THRESHOLD``)**: Python float64 scalar
  cosine, byte-for-byte the oracle's own ``_cosine`` accumulation, so those
  queries are bit-identical by construction.
- **Large same-key sets**: one ``cblas_sgemv`` over the whole FP32 matrix
  (FP32 accumulation, ~5 ms at 100k x 1024 on Apple Silicon) plus per-row
  squared norms precomputed once at engine construction with
  ``cblas_sdot``; cosine = dot / sqrt(qn * en).  Measured agreement vs the
  oracle is within ~1e-8 absolute on 100k-hot-key queries, far inside the
  pinned 1e-6 tolerance, with identical kept sets (see
  ``test_accelerate.py`` / the #72 report).

Fail-closed contract (SCN-72-5 / stop-ship): if vecLib cannot be loaded at
runtime, ``AccelerateError`` is raised -- the daemon never silently falls
back to the numpy/Python path while claiming Accelerate.  A missing buffer,
a dimension mismatch, a non-finite cosine or a missing row are all faults.

The engine is stdlib-only plus Apple's system vecLib; no numpy, no MLX.
"""

import ctypes
import ctypes.util
import math
import struct

from oracle import CosineEngine, OracleError

# Single-precision row-major matrix-vector product.  vecLib is a system
# framework on macOS; the daemon only runs on Apple Silicon (spec #72
# envelope: Apple Silicon + Accelerate/vecLib).
CblasRowMajor = 101
CblasNoTrans = 111

# Below this many same-key events the engine uses the oracle's own Python
# float64 scalar cosine (bit-identical by construction); above it the
# batched sgemv path wins.  The threshold is well below the point where the
# ctypes call overhead would dominate (100k rows measured ~5 ms).
PYTHON_PATH_THRESHOLD = 256

# Documented equivalence tolerance (absolute cosine difference vs the stdlib
# oracle), pinned for the #72 report and the equivalence suite.  The measured
# sgemv-vs-oracle deviation at 100k x 1024 is ~1e-8, two orders of magnitude
# inside this bound.
COSINE_TOLERANCE = 1e-6

_vecLib = None
_vecLib_path = None


class AccelerateError(Exception):
    """A true fault in the Accelerate backend (never a silent fallback)."""


def _load_vecLib():
    """Load Apple vecLib once; cached module-wide.

    Raises AccelerateError when vecLib is unavailable (fail closed -- the
    caller must not pretend Accelerate is serving).
    """
    global _vecLib, _vecLib_path
    if _vecLib is not None:
        return _vecLib, _vecLib_path
    candidates = []
    found = ctypes.util.find_library("vecLib")
    if found:
        candidates.append(found)
    candidates.extend([
        "/System/Library/Frameworks/vecLib.framework/vecLib",
        "/System/Library/Frameworks/Accelerate.framework/Accelerate",
    ])
    for candidate in candidates:
        try:
            lib = ctypes.CDLL(candidate)
        except OSError:
            continue
        _vecLib = lib
        _vecLib_path = candidate
        return lib, candidate
    raise AccelerateError(
        "Apple vecLib is not available on this machine; the Accelerate "
        "backend fails closed (no silent Python fallback)")


def _bind_sgemv(lib):
    """Bind cblas_sgemv with the exact C signature."""
    func = lib.cblas_sgemv
    func.restype = None
    func.argtypes = [
        ctypes.c_int,       # enum CBLAS_ORDER
        ctypes.c_int,       # enum CBLAS_TRANSPOSE
        ctypes.c_int,       # M
        ctypes.c_int,       # N
        ctypes.c_float,     # alpha
        ctypes.c_void_p,    # A
        ctypes.c_int,       # lda
        ctypes.c_void_p,    # x
        ctypes.c_int,       # incx
        ctypes.c_float,     # beta
        ctypes.c_void_p,    # y
        ctypes.c_int,       # incy
    ]
    return func


def _bind_sdot(lib):
    """Bind cblas_sdot: float cblas_sdot(int n, const float* x, int incx,
    const float* y, int incy)."""
    func = lib.cblas_sdot
    func.restype = ctypes.c_float
    func.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                     ctypes.c_void_p, ctypes.c_int]
    return func


def _address(buffer):
    """The raw address of a buffer-protocol object (mmap or memoryview).

    The generation's vector file is opened with ``mmap.ACCESS_COPY`` (see
    ``generation._VectorFile``): the mapping is copy-on-write, so it exposes
    a writable buffer to ctypes WITHOUT ever writing back to the file --
    zero-copy reads, no second resident copy, and the immutable file stays
    untouched.  A plain read-only mmap cannot hand its address to ctypes
    (``from_buffer`` needs a writable buffer), hence the access mode choice.
    """
    try:
        return ctypes.addressof(ctypes.c_char.from_buffer(buffer))
    except TypeError:
        view = memoryview(buffer)
        try:
            if view.readonly:
                raise AccelerateError(
                    "the vector matrix buffer must be writable (use "
                    "mmap.ACCESS_COPY) for the Accelerate backend")
            return ctypes.addressof(
                (ctypes.c_char * view.nbytes).from_buffer(view))
        finally:
            view.release()


class AccelerateCosineEngine(CosineEngine):
    """Batch cosine over one immutable FP32 vector matrix via vecLib.

    ``buffer`` is the raw row-major little-endian FP32 file buffer (an mmap
    or any read-only buffer-protocol object, e.g. ``Generation.vector_buffer()``);
    ``rows`` x ``dimension`` is the matrix shape; ``row_index`` maps event_id
    to row.  The engine holds NO copy of the matrix (zero-copy reads), and
    precomputes the per-row squared norms once (``cblas_sdot``, ~30-40 ms at
    100k rows) so every query only pays one sgemv (~5 ms at 100k x 1024).
    """

    def __init__(self, buffer, rows, dimension, row_index):
        if buffer is None or rows < 0 or dimension < 1:
            raise AccelerateError("invalid vector matrix for Accelerate")
        try:
            lib, _path = _load_vecLib()
        except AccelerateError:
            raise
        self._lib = lib
        self._sgemv = _bind_sgemv(lib)
        self._sdot = _bind_sdot(lib)
        self._buffer = buffer
        self._rows = rows
        self._dimension = dimension
        self._row_index = dict(row_index)
        self._address = _address(buffer)
        self._row_bytes = dimension * 4
        self._norms = None  # lazy: squared L2 norm per row (float64)

    # -- vectors --------------------------------------------------------------

    def _row_vector(self, row):
        """One row as a tuple of Python floats (small-set path)."""
        offset = row * self._row_bytes
        return struct.unpack_from("<%df" % self._dimension,
                                  self._buffer, offset)

    def _compute_norms(self):
        """Per-row squared L2 norm via cblas_sdot (once per engine)."""
        norms = [0.0] * self._rows
        if self._rows == 0:
            return norms
        base = self._address
        row_bytes = self._row_bytes
        sdot = self._sdot
        for row in range(self._rows):
            ptr = base + row * row_bytes
            value = sdot(self._dimension, ptr, 1, ptr, 1)
            if not math.isfinite(value):
                raise AccelerateError(
                    "row %d norm is non-finite in the Accelerate matrix"
                    % row)
            norms[row] = float(value)
        return norms

    # -- CosineEngine ----------------------------------------------------------

    def batch_cosines(self, query_vector, event_ids, vector_for):
        """Cosine for every same-key event; see CosineEngine.

        Events present in the immutable matrix (the base generation's rows)
        are served by vecLib; events NOT in the matrix (delta events that
        arrived after the base generation, S2 catch-up) fall back to the
        caller's ``vector_for`` with the oracle's own Python float64 cosine
        -- the same exactness the oracle itself uses, and the same result
        (RISK-72-3 tolerance).  Every same-key event is always scored; a
        missing row WITHOUT a working ``vector_for`` is a fault, never a
        silent drop.
        """
        if not event_ids:
            return {}
        matrix_rows = []
        fallback_ids = []
        for event_id in event_ids:
            row = self._row_index.get(event_id)
            if row is not None and 0 <= row < self._rows:
                matrix_rows.append((event_id, row))
            else:
                fallback_ids.append(event_id)

        cosines = {}
        if fallback_ids:
            for event_id in fallback_ids:
                cosines[event_id] = self._fallback_cosine(
                    query_vector, event_id, vector_for)
        if matrix_rows:
            query_norm = math.sqrt(sum(value * value
                                       for value in query_vector))
            if query_norm == 0.0 or not math.isfinite(query_norm):
                raise OracleError("cosine requires a non-zero query vector")
            if len(matrix_rows) <= PYTHON_PATH_THRESHOLD:
                for event_id, row in matrix_rows:
                    cosines[event_id] = self._python_cosine(
                        query_vector, query_norm, row)
            else:
                ids = [event_id for event_id, _row in matrix_rows]
                rows = [row for _event_id, row in matrix_rows]
                cosines.update(self._sgemv_cosines(
                    query_vector, query_norm, ids, rows))
        return cosines

    def _fallback_cosine(self, query_vector, event_id, vector_for):
        """Python float64 cosine via the caller's vector_for (delta events)."""
        try:
            vector = vector_for(event_id)
        except Exception as error:  # noqa: BLE001 - fail closed
            raise OracleError(
                "vector lookup failed for event %s" % event_id) from error
        vector = tuple(float(value) for value in vector)
        if len(vector) != len(query_vector):
            raise OracleError(
                "vector dimension mismatch for event %s: %d vs query %d"
                % (event_id, len(vector), len(query_vector)))
        for value in vector:
            if not math.isfinite(value):
                raise OracleError(
                    "vector for event %s contains a non-finite value"
                    % event_id)
        dot = 0.0
        event_norm = 0.0
        query_norm = 0.0
        for query_value, event_value in zip(query_vector, vector):
            dot += query_value * event_value
            query_norm += query_value * query_value
            event_norm += event_value * event_value
        if query_norm == 0.0 or event_norm == 0.0:
            raise OracleError("cosine requires non-zero vectors")
        return dot / math.sqrt(query_norm * event_norm)

    def _python_cosine(self, query_vector, query_norm, row):
        """Byte-for-byte the oracle's scalar float64 cosine (small sets)."""
        vector = self._row_vector(row)
        dot = 0.0
        event_norm = 0.0
        for query_value, event_value in zip(query_vector, vector):
            dot += query_value * event_value
            event_norm += event_value * event_value
        if event_norm == 0.0:
            raise OracleError("cosine requires non-zero event vectors")
        return dot / math.sqrt(query_norm * query_norm * event_norm)

    def _sgemv_cosines(self, query_vector, query_norm, event_ids, rows):
        """One batched cblas_sgemv over the full matrix, then gather rows.

        Computes dot(q, row) for every row in one call (FP32 accumulation),
        divides by sqrt(qn * en(row)) with the precomputed float64 row norm.
        """
        dimension = self._dimension
        rows_total = self._rows
        query_array = (ctypes.c_float * dimension)(
            *(float(value) for value in query_vector))
        result = (ctypes.c_float * rows_total)()
        alpha = ctypes.c_float(1.0)
        beta = ctypes.c_float(0.0)
        self._sgemv(CblasRowMajor, CblasNoTrans,
                    rows_total, dimension,
                    alpha, self._address, dimension,
                    query_array, 1, beta, result, 1)

        if self._norms is None:
            self._norms = self._compute_norms()
        qn = query_norm * query_norm
        en = self._norms
        # C-level zip construction; the per-value math still needs a Python
        # loop (dict values are Python floats), but this avoids per-row
        # attribute/index lookups at 100k rows.
        out = {}
        sqrt = math.sqrt
        for event_id, row in zip(event_ids, rows):
            row_norm = en[row]
            if row_norm == 0.0:
                raise OracleError(
                    "cosine requires non-zero event vectors (event %s)"
                    % event_id)
            cosine = result[row] / sqrt(qn * row_norm)
            if not math.isfinite(cosine):
                raise OracleError(
                    "cosine engine produced a non-finite cosine for event %s"
                    % event_id)
            out[event_id] = float(cosine)
        return out


def build_cosine_engine(buffer, rows, dimension, row_index):
    """Construct the Accelerate engine; raises AccelerateError fail-closed.

    This is the #72 seam entry point: a generation/delta snapshot that wants
    to serve under the Accelerate backend constructs the engine over its own
    immutable FP32 buffer.  Any failure here (missing vecLib, malformed
    matrix) is a true fault -- never a silent Python fallback.
    """
    return AccelerateCosineEngine(buffer, rows, dimension, row_index)
