# USearch ANN path (Squirrel#78)

Qualification-only. Does not enable live `α`/`γ`/evidence and does not
pick a production winner.

## Isolated BGE wiring

The AC-78 runner may load exactly one heavyweight model,
`dedicated_bge_m3` / BGE-M3, from `.local-work/models/BGE-M3` via
`BGEM3RepresentationProvider`. Payload is `last64(preceding)+candidate`
with no instruction, dense mean pooling, FP32 L2, 1024-d. Qwen3 and L28
are not imported. Live schema and live facts are not opened.

Provider kind `bge_m3` on the evidence config seam is qualification-only.

## Identity layers

- **index_fingerprint**: retrieval backend `usearch-hnsw`, cosine metric,
  dtype `f32`, library version `usearch-hnsw-v1`, serialization ABI
  `usearch-index-v1-arm64`, HNSW *build* params `connectivity` and
  `expansion_add`. Changing these rebuilds ANN from healthy FP32.
- **query identity** (`compose_config_identity`): `H` / `γ` / `k` / `τ` /
  `K_evidence` / `overfetch` / `query_search`. Changing these does not
  rebuild the index. Exact-path identities omit the last two fields so
  they stay byte-identical with the C++ plugin.

## Fail-closed

Timeout, protocol, identity, index, or catch-up faults return an error.
The plugin emits the original window. Exact-path semantic fallback during
ANN repair is not authorized.

Sidecar layout (outside the three-file generation container):

```
<derived_root>/index/<generation_id>/index.ann
<derived_root>/index/<generation_id>/index.meta.json
<derived_root>/index/<generation_id>/index.keys.json
```

Unknown or mixed-generation meta refuses to load. Corrupt ANN rebuilds
from healthy FP32. Index-only on unhealthy FP32 refuses.

## Legal terminals

`usearch_qualified` or `usearch_disqualified`. Either may Pass the
measurement contract. Unmeasured gates never pass. Kernel-only or
seed-vector timings cannot satisfy ANN78-7.
