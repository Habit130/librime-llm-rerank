# hnswlib ANN path (Squirrel#79)

Qualification-only. Does not enable live `α`/`γ`/evidence and does not
pick a production winner. Independent of the accepted #78
`usearch_disqualified` measurement: USearch recall/latency/RSS/disk
numbers are context, not this ticket's evidence.

## Isolated BGE wiring

The AC-79 runner may load exactly one heavyweight model,
`dedicated_bge_m3` / BGE-M3, from `.local-work/models/BGE-M3` via
`BGEM3RepresentationProvider`. Payload is `last64(preceding)+candidate`
with no instruction, dense mean pooling, FP32 L2, 1024-d. Qwen3 and L28
are not imported. Live schema and live facts are not opened.

Provider kind `bge_m3` on the evidence config seam is qualification-only.

## Identity layers

- **index_fingerprint**: retrieval backend `hnswlib-hnsw`, cosine metric,
  dtype `f32`, library version `hnswlib-hnsw-v1`, serialization ABI
  `hnswlib-index-v1-arm64`, HNSW *build* params `M` and `ef_construction`.
  Changing these rebuilds ANN from healthy FP32.
- **query identity** (`compose_config_identity`): `H` / `γ` / `k` / `τ` /
  `K_evidence` / `overfetch` / `query_search` (`ef`). Changing these does
  not rebuild the index. Exact-path identities omit the last two fields so
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

`hnswlib_qualified` or `hnswlib_disqualified`. Either may Pass the
measurement contract. Unmeasured gates never pass. Kernel-only,
FastService, `_Zero`, brute-force fallback, or USearch timings cannot
satisfy ANN79-7.

ANN79-7 times complete evidence IPC: `eval/ac79_evidence_daemon.py`
serves `EvidenceService` over a unix socket with BGE already warm and
the hnswlib sidecar loaded. The paired `γ=0` control is a second
`EvidenceService` in that same daemon, not a client stub. Catch-up
appends a real commit then measures the next request. Replay is 10k
requests on both fixtures. A hnswlib build failure is a fault; there
is no `BruteForceIndex` fallback. ANN79-8 walks published generation
bytes (FP32 + metadata + ANN sidecar) and `active+rollback+staging+delta`.
