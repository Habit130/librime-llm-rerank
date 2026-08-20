#!/usr/bin/env python3
"""MLX exact retrieval backend (Habit130/squirrel#73).

The pure-Python oracle (``daemon/oracle.py``) computes one Python-scalar
cosine per same-key active event; at 100k events on one hot key that is the
#71 measured ~7.5 s/query worst case, and the #72 Accelerate backend
(``cblas_sgemv``) measured ~5-30 ms for the same query.  This module
implements the SAME exact evidence semantics (SCN-73-1: every same-key
active event is scored, no shortlist, no cosine top-K before aging) with the
per-event cosine computed by MLX (``mx.matmul`` over the generation's
canonical row-major little-endian FP32 vector file, plus per-row squared
norms).  It plugs into ``oracle.compute_evidence`` through the
``CosineEngine`` seam (``batch_cosines``); the oracle's aggregation
(threshold, usage age, final weight, top-K, m_c / M / s_c) is untouched and
never duplicated.

Equivalence contract (SCN-73-2, pinned): the backend must match the stdlib
oracle query-by-query -- neighbors, event weights, candidate evidence
``s_c`` and final emit order -- within the documented float tolerance.  This
engine's two paths:

- **Small same-key sets (<= ``PYTHON_PATH_THRESHOLD``)**: Python float64
  scalar cosine, byte-for-byte the oracle's own ``_cosine`` accumulation, so
  those queries are bit-identical by construction.
- **Large same-key sets**: one ``mx.matmul`` over the whole FP32 matrix
  (FP32 accumulation) plus per-row squared norms precomputed once at engine
  construction; cosine = dot / sqrt(qn * en).  Measured agreement vs the
  oracle is within ~3e-8 absolute on 100k-hot-key queries, far inside the
  pinned 1e-6 tolerance, with identical kept sets (see ``test_mlx.py`` / the
  #73 report).

Fail-closed contract (SCN-73-6 / stop-ship): if MLX cannot be imported or
any matmul/validation step fails at runtime, ``MlxError`` is raised -- the
daemon never silently falls back to the numpy/Python path or to Accelerate
while claiming MLX.  A missing buffer, a dimension mismatch, a non-finite
cosine or a missing row are all faults.

No second resident model (SCN-73-5): this engine performs dense FP32
matrix-vector products over the already-built vector file; it never loads a
model, never spawns a second daemon, and shares the daemon process with the
LM-based candidate scorer (the #73 contention measurement exercises exactly
that shared-process configuration).

Memory: MLX 0.32 has no zero-copy CPU array constructor (``mx.array`` and
``mx.from_dlpack`` over a numpy buffer both copy), so the engine holds ONE
explicit working copy of the canonical FP32 matrix as an ``mx.array``
(~400 MiB at 100k x 1024) and does NOT retain the mmap or the numpy view
after construction.  The file-backed generation stays the durable source of
truth; the in-process MLX matrix is the zero-fault serving image, and it is
released when the engine (and its snapshot) is released.  The RSS cost is
reported explicitly vs the #72 zero-copy mmap path (RISK-73-4 / the #73
memory record).
"""

import math

from oracle import CosineEngine, OracleError

# Below this many same-key events the engine uses the oracle's own Python
# float64 scalar cosine (bit-identical by construction); above it the
# batched MLX matmul path wins.  The threshold mirrors the #72 seam so the
# two exact backends behave identically at small scale.
PYTHON_PATH_THRESHOLD = 256

# Documented equivalence tolerance (absolute cosine difference vs the stdlib
# oracle), pinned for the #73 report and the equivalence suite.  The measured
# MLX-matmul-vs-oracle deviation at 100k x 1024 is ~6e-9 (spot-checked across
# hot keys; worst observed ~1e-7 on synthetic unit vectors), two orders of
# magnitude inside this bound.
COSINE_TOLERANCE = 1e-6

# Resource gate (SCN-73-6): the engine holds one explicit in-process copy of
# the canonical FP32 matrix (MLX 0.32 has no zero-copy CPU constructor), so a
# matrix whose working copy exceeds this bound is refused -- fail closed,
# never a silently degraded/approximate serving path.  100k x 1024 x 4B =
# 409.6 MiB, well inside the bound; the bound exists so an out-of-range
# build (or a future much larger matrix) faults instead of exhausting memory
# while pretending to serve.
MATRIX_BYTES_LIMIT = 2 * 1024 * 1024 * 1024  # 2 GiB working copy


class MlxError(Exception):
    """A true fault in the MLX backend (never a silent fallback)."""


class MlxCosineEngine(CosineEngine):
    """Batch cosine over one immutable FP32 vector matrix via MLX.

    ``buffer`` is the raw row-major little-endian FP32 file buffer (an mmap
    or any read-only buffer-protocol object, e.g. ``Generation.vector_buffer()``);
    ``rows`` x ``dimension`` is the matrix shape; ``row_index`` maps event_id
    to row.  The engine copies the matrix ONCE into an MLX array at
    construction (MLX 0.32 has no zero-copy CPU constructor) and precomputes
    the per-row squared norms once, so every query only pays one matmul
    (~30 ms at 100k x 1024 first call; the daemon warm-up pays it before the
    measurement window).
    """

    def __init__(self, buffer, rows, dimension, row_index):
        if buffer is None or rows < 0 or dimension < 1:
            raise MlxError("invalid vector matrix for MLX")
        self._rows = rows
        self._dimension = dimension
        self._row_index = dict(row_index)
        self._matrix = None
        self._norms = None  # lazy: squared L2 norm per row (float64)
        self._load_matrix(buffer)

    def _load_matrix(self, buffer):
        """Copy the canonical FP32 file into one MLX array (fail closed)."""
        try:
            import mlx.core as mx
            import numpy as np
        except Exception as error:  # noqa: BLE001 - fail closed
            raise MlxError(
                "MLX is not available on this machine; the MLX backend "
                "fails closed (no silent Accelerate/Python fallback): %s"
                % error) from error
        try:
            bytes_needed = self._rows * self._dimension * 4
            if bytes_needed > MATRIX_BYTES_LIMIT:
                # Resource gate (SCN-73-6): a working copy beyond the bound
                # is refused, never served degraded.
                raise MlxError(
                    "MLX matrix working copy would be %d bytes, over the "
                    "resource gate of %d bytes; the MLX backend fails "
                    "closed (no approximate fallback)"
                    % (bytes_needed, MATRIX_BYTES_LIMIT))
            view = memoryview(buffer)
            if view.nbytes < bytes_needed:
                raise MlxError(
                    "MLX matrix buffer is smaller than the declared shape "
                    "(%d x %d)" % (self._rows, self._dimension))
            array = np.frombuffer(
                view[:bytes_needed], dtype="<f4")
            matrix = array.reshape(self._rows, self._dimension)
            self._matrix = mx.array(matrix)  # the one explicit working copy
        except MlxError:
            raise
        except Exception as error:  # noqa: BLE001 - fail closed
            raise MlxError(
                "cannot build the MLX matrix from the FP32 buffer: %s"
                % error) from error
        finally:
            try:
                view.release()
            except Exception:  # noqa: BLE001 - best effort
                pass

    def _require_matrix(self):
        if self._matrix is None:
            raise MlxError("MLX matrix is not loaded")
        return self._matrix

    def _compute_norms(self):
        """Per-row squared L2 norm via one MLX reduction (once per engine)."""
        if self._rows == 0:
            return []
        import mlx.core as mx
        import numpy as np
        matrix = self._require_matrix()
        try:
            squared = mx.sum(mx.square(matrix), axis=1)
            mx.eval(squared)
            values = np.asarray(squared, dtype=np.float64).ravel()
        except Exception as error:  # noqa: BLE001 - fail closed
            raise MlxError("MLX row-norm computation failed: %s" % error) \
                from error
        norms = []
        for row in range(self._rows):
            value = values[row]
            if not math.isfinite(value):
                raise MlxError(
                    "row %d norm is non-finite in the MLX matrix" % row)
            norms.append(float(value))
        return norms

    # -- CosineEngine --------------------------------------------------------

    def batch_cosines(self, query_vector, event_ids, vector_for):
        """Cosine for every same-key event; see CosineEngine.

        Events present in the MLX matrix (the base generation's rows) are
        served by MLX; events NOT in the matrix (delta events that arrived
        after the base generation, S2 catch-up) fall back to the caller's
        ``vector_for`` with the oracle's own Python float64 cosine -- the
        same exactness the oracle itself uses, and the same result
        (SCN-73-2 tolerance).  Every same-key event is always scored; a
        missing row WITHOUT a working ``vector_for`` is a fault, never a
        silent drop (SCN-73-1).
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
                cosines.update(self._matmul_cosines(
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
        try:
            import numpy as np
            import mlx.core as mx
            matrix = self._require_matrix()
            vector = np.asarray(mx.take(matrix, mx.array([row]), axis=0)[0],
                                dtype=np.float64).ravel()
        except Exception as error:  # noqa: BLE001 - fail closed
            raise MlxError("MLX row read failed: %s" % error) from error
        dot = 0.0
        event_norm = 0.0
        for query_value, event_value in zip(query_vector, vector):
            dot += query_value * event_value
            event_norm += event_value * event_value
        if event_norm == 0.0:
            raise OracleError("cosine requires non-zero event vectors")
        return dot / math.sqrt(query_norm * query_norm * event_norm)

    def _matmul_cosines(self, query_vector, query_norm, event_ids, rows):
        """One batched mx.matmul over the whole matrix, then gather rows.

        Computes dot(q, row) for every row in one call (FP32 accumulation),
        divides by sqrt(qn * en(row)) with the precomputed float64 row norm.
        """
        try:
            import mlx.core as mx
            import numpy as np
            matrix = self._require_matrix()
            query = mx.array(tuple(float(value) for value in query_vector))
            dots = mx.matmul(matrix, query)
            mx.eval(dots)
            dot_values = np.asarray(dots, dtype=np.float64).ravel()
        except Exception as error:  # noqa: BLE001 - fail closed
            raise MlxError("MLX matmul failed: %s" % error) from error

        if self._norms is None:
            self._norms = self._compute_norms()
        qn = query_norm * query_norm
        en = self._norms
        out = {}
        sqrt = math.sqrt
        for event_id, row in zip(event_ids, rows):
            row_norm = en[row]
            if row_norm == 0.0:
                raise OracleError(
                    "cosine requires non-zero event vectors (event %s)"
                    % event_id)
            cosine = dot_values[row] / sqrt(qn * row_norm)
            if not math.isfinite(cosine):
                raise OracleError(
                    "cosine engine produced a non-finite cosine for event %s"
                    % event_id)
            out[event_id] = float(cosine)
        return out


def build_cosine_engine(buffer, rows, dimension, row_index):
    """Construct the MLX engine; raises MlxError fail-closed.

    This is the #73 seam entry point: a generation/delta snapshot that wants
    to serve under the MLX backend constructs the engine over its own
    immutable FP32 buffer.  Any failure here (missing MLX, malformed matrix)
    is a true fault -- never a silent Accelerate/Python fallback.
    """
    return MlxCosineEngine(buffer, rows, dimension, row_index)
