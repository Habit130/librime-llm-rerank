# Dedicated Embedding Adapters

AC-110-v1 adds two offline candidate-conditioned representation routes. Both
routes consume the AC-109 payload exactly: the last 64 Unicode characters of
preceding text followed immediately by the candidate, with no separator and no
special tokens. Query and historical event vectors are paired by candidate in
the same choice problem, and only the selected candidate's event can provide
positive evidence.

## Routes

- `qwen3-embedding-0.6b` uses `Qwen3-Embedding-0.6B`, last-token pooling, and
  the exact query instruction `Represent the candidate-conditioned query for
  semantic retrieval.`. The instruction is prepended only to the query input;
  historical/document inputs are the unchanged payload and do not search
  prompts.
- `bge-m3-dense-1024` uses `BGE-M3` dense mean pooling at the complete 1024
  dimensions. It has no instruction. Sparse, ColBERT and hybrid outputs are
  not loaded or exposed.

Both routes L2-normalize finite vectors and serve fp32 cosine representations.
Their `representation_id` binds the payload schema and serialization, model
and tokenizer digests, adapter/instruction, pooling, output dimension, vector
format, metric, and the pinned isolated dependency versions. A changed
identity is a representation fault, never a successful vector.

## Loading Boundary

The transformers runtime is lazy. A process-level registry permits one
heavyweight embedding model only; a request for a different model fails closed.
Model and tokenizer loads use `local_files_only=True`, so this path does not
download model files or use a global install. Model-free fixtures and the
`eval/dedicated_embedding_benchmark.py` adapter cover both route contracts when
weights are absent.

Create the allocated environment from the plugin worktree:

```sh
python3 -m venv .venv-embeddings
.venv-embeddings/bin/python -m pip install -r daemon/requirements-embeddings.txt
```

Do not use `daemon/.venv` for these dependencies. No live config, C++ schema,
projection, ANN, or winner selection is part of this adapter. The frozen v2
benchmark remains deferred and is not imported or run here.
