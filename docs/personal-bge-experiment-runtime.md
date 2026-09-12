# Personal BGE experiment runtime (`personal-bge-experiment-v1`)

Squirrel#168 wires the frozen personal profile through the daemon's online
memory and evidence path. This document is the supported launch and
configuration surface for that loop. It does not enable live evidence, does
not retune `tau` / `H` / `K_evidence` / `gamma` / `k`, and is not a hot-path
latency Pass.

Profile numbers live in Squirrel
`docs/personal-experiment-profile.md` (`personal-bge-experiment-v1`). This
plugin consumes them.

## What this loop is

- One heavyweight model: the pinned BGE-M3 dense adapter
  (`provider_kind: bge_m3` / route `bge-m3-dense-1024`).
- Exact same-key retrieval (`retrieval_backend: exact`).
- Positive-only bounded evidence. Successful zero evidence is `status: ok`.
- Faults keep whole-window passthrough. Canonical facts are not relabeled
  or cleared.
- `alpha = 0`: do not load a resident Qwen LM. Start the daemon with
  `--health-only` so scoring does not import MLX.
- Candidate window 32 and synchronous deadline 200 ms stay at the public
  contract defaults. Offline throughput and fixture-only timings are not
  evidence that the hot path meets 200 ms.

Live schema `evidence_enabled` stays false until Squirrel#170. This PR does
not write `~/Library/Rime` or the live semantic-memory root.

## Isolated runtime

Create the embeddings venv in the plugin worktree. Do not use `daemon/.venv`.

```sh
python3 -m venv .local-work/ac168-bge-runtime/venv
.local-work/ac168-bge-runtime/venv/bin/python -m pip install \
  -r daemon/requirements-embeddings.txt
```

Pins: `torch==2.7.1`, `transformers==4.52.4`, `tokenizers==0.21.1`,
`safetensors==0.5.3`. Loads use `local_files_only=True`. Missing local BGE
weights for upstream `BAAI/bge-m3` revision
`5617a9f61b028005a4858fdac845db406aefb181` is an environment blocker; do not
download into a global install.

Isolated synthetic facts, caches, and this venv belong under
`.local-work/ac168-bge-runtime/`. That directory is gitignored.

## Evidence config

JSON passed as `--evidence-config`. Builder, delta, evidence, and staging
desired-provider all construct `BGEM3RepresentationProvider`. Identity is
derived from local model and tokenizer file digests. A configured
`representation_id` or `desired_representation_id` that disagrees fails
closed without rewriting vectors or mutating facts.

```json
{
  "provider_kind": "bge_m3",
  "bge_model_path": "/absolute/path/to/local/BGE-M3",
  "tau": 0.5,
  "k_evidence": 8,
  "half_life": 128,
  "saturation_k": 3.0,
  "gamma": 1.0,
  "retrieval_backend": "exact",
  "derived_root": "/absolute/isolated/derived",
  "generation_id": "<active generation id after cold build>"
}
```

`representation_id` may be omitted: the provider fills it. Config identity
is then:

```text
evidence-v1:repr=<provider representation_id>:tau=0.5:kev=8:H=128:sat=3:gamma=1
```

## Launch (not live enablement)

Use the embeddings interpreter, an isolated `--facts-root`, and
`--health-only` so no Qwen LM is loaded:

```sh
.local-work/ac168-bge-runtime/venv/bin/python daemon/server.py \
  --serve --health-only \
  --facts-root /absolute/isolated/facts \
  --evidence-config /absolute/isolated/evidence.json \
  --socket /absolute/isolated/llm-rerank.sock
```

Do not point `--facts-root` at `~/Library/Application Support/Squirrel/SemanticMemory`
or `~/Library/Rime` for this ticket.

Plugin-side schema for later activation remains out of scope. The public
example stays `evidence_enabled: false`.

## Hot path bounds

- Event vectors come from the generation mmap and delta checkpoint. The
  daemon does not re-encode full history on every evidence request.
- Query vectors are cached per `(preceding_text, candidate)` with an LRU
  cap of 256 entries (`QUERY_CACHE_LIMIT`).
- Identity re-validation on an already loaded adapter uses a directory
  stat fingerprint (path, size, mtime) and only re-hashes weights when
  that fingerprint changes. A changed identity is a representation fault.

## Verification

Model-free:

```sh
bash scripts/run-model-free-gates.sh python3
```

Dedicated real-BGE tests (not a skip Pass if weights are missing):

```sh
AC168_BGE_MODEL=/absolute/path/to/local/BGE-M3 \
  .local-work/ac168-bge-runtime/venv/bin/python \
  daemon/integration_bge_online_memory.py
```

C++ `llm_rerank_test` is unchanged: `HitChangesWithinGroupOrder`,
`TimeoutPassesThroughWholeWindow`, and
`ExhaustedWindowDeadlineSkipsLaterGroup` remain the filter emission and
later-group passthrough proof.
