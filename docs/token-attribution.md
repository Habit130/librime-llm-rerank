# Mean-Token Scoring: Token Attribution and Calibration Design

Status: implemented by Habit130/squirrel#46 (branch `feat/token-normalized-scoring`).

This document records the engineering decisions made before implementation:
the token attribution rules, the fail-closed boundary handling, the new
scoring-policy identity, and the calibration protocol. It is the normative
reference for the tests and for the daemon implementation.

## Problem

`ModelState.score()` tokenized `tail_text + candidate` as one string and
accumulated the log probability of **every** suffix token — including tokens
that belong to the context tail, and dropping the first suffix token when the
prefix KV cache was empty. Candidates were therefore scored by the *sum* of
log probs over a token count that varied with candidate length and with the
context tail, which (a) lets context-tail tokens enter candidate scores and
(b) biases comparison toward shorter candidates (measured in
Habit130/squirrel#22: within-group correlation -0.72 between token count and
LLM score).

The fix: score each candidate by the **mean** of the log probabilities of
tokens that can be *proven* to belong to the candidate text, and fail closed
whenever attribution is not provable.

## Token attribution rules

### Text boundary unit

The text boundary is a **whole-character boundary**: the windowed context is
split into `prefix` (all but the last 4 characters) and `tail` (the last 4
characters), and the candidate is appended as whole characters. The boundary
is therefore always at a Unicode character boundary.

### Attribution by reconstruction

Attribution is by **reconstruction**, which is provably safe and robust to
Qwen's byte-level BPE:

- `full = tail_text + candidate` is tokenized once (`suffix_ids`).
- **Round-trip precondition**: `decode(suffix_ids) == full` must hold,
  otherwise the tokenization is lossy and the request fails closed.
- The smallest `k` such that `decode(suffix_ids[:k]) == tail_text` is the
  boundary position: tokens `[0, k)` cover exactly the tail characters and
  tokens `[k, n)` cover exactly the candidate characters (by the round-trip
  precondition). The first target token's conditional probability is taken
  from the model output at position `k-1` (or from the prefix KV cache when
  `k == 0`).
- If no such `k` exists, a single BPE token spans the tail/candidate
  boundary and the request fails closed: the model only produces whole-token
  probabilities, so no well-defined conditional probability exists for the
  candidate's portion.
- **Byte-level fallback pairs**: Qwen's BPE tokenizes rare characters as two
  byte-fallback tokens whose offset mappings are unreliable (both tokens
  report the same range; verified empirically, e.g. `匑` ->
  `[13465, 239]` both `(0,1)`). Reconstruction handles them correctly: the
  pair decodes to the single character it covers, so it stays whole on
  whichever side of the boundary it falls. A boundary can never split a
  pair, because a pair covers exactly one character.

An earlier offset-mapping-based design (character/byte unit detection +
per-token range classification) was discarded after the empirical finding
above: it failed closed on every window containing a rare character, which
would have silently disabled reranking for ordinary input containing rare
characters and biased the calibration fixture.

### Prediction positions

The model input per candidate is `[prefix tokens] + suffix`, where `prefix`
is tokenized once from `context[:-TAIL_CHARS]` (KV-cached, shared across the
batch) and `suffix` is the attributed `suffix_ids`.

For a target token at suffix position `p`:

- `p == 0`: its conditional probability is
  `prefix_last_lp[suffix[p]]` — the log prob of the first suffix token given
  the prefix.
- `p > 0`: its conditional probability is
  `lp[batch, p-1, suffix[p]]` — the log prob of suffix token `p` given
  `prefix + suffix[0..p-1]` (in particular, given the tail tokens that
  precede it).

### First candidate token when the model input would be empty

When the windowed context is empty (no prefix tokens and no tail tokens), the
first target token would be at position 0 with no conditioning tokens at all,
so its conditional probability is undefined. Rather than silently dropping it
(the old behavior), the daemon applies a **defined model-input rule**: the
EOS token (`<|endoftext|>`, id 151643) is prepended as an anchor conditioning
token, and the first target token is conditioned on it. This is:

- deterministic and identical for every candidate in the batch, so it cannot
  bias candidate comparison;
- required by the standalone-word fixture protocol (preceding text empty);
- documented as part of the scoring-policy semantics covered by
  `baseline_policy_id`.

When the prefix is empty but the tail is non-empty, no anchor is added: the
target tokens are conditioned on the tail tokens, whose own probabilities are
never accumulated. This mirrors the non-empty-prefix case.

### Padding

Right-padding with `pad_id` is used only to align the batch for the MLX
forward. Padding positions are never read by the reducer (accumulation only
touches positions `< len(real suffix)`), never enter the numerator, and never
enter the denominator — the count is each candidate's **own** target token
count.

### Score formula

```
mean_token_lm_score(c | context) =
    ( Σ over target tokens t of log P(t | prefix + suffix[:p_t]) ) / count(c)
```

- The same formula applies to single-token and multi-token candidates.
- Two candidates with identical per-token log probabilities but different
  token counts receive identical mean scores.
- The count is the number of target tokens, never the batch padding length.

### Fail-closed conditions

The whole batch request fails (`token_attribution_failed`) when any candidate
has:

- empty text (rejected earlier, at protocol validation, as `invalid_request`);
- zero target tokens;
- a straddling token;
- a coverage or contiguity violation;
- any non-finite per-token log probability or non-finite mean
  (`non_finite_score`).

The C++ client treats any daemon error as a batch failure and passes the
entire window through in original order (established in #11, unchanged here).
Errors and logs never include raw context, candidate text, token text, model
input, or embeddings (protocol guarantees from #11; new error codes carry
only code, message, and identity fields).

## Scoring-policy identity

- Old: `baseline_policy_id = "first-stage-base-v1"` with sum-of-suffix-token
  scores.
- New: `baseline_policy_id = "mean-token-lm-v1"` with mean-target-token
  scores and default `alpha = 0` (owner decision, see the calibration
  result below: no positive alpha qualified on the canonical fixture).
- The plan identity (`rerank-plan-v2:sha1:...`) hashes the whole scoring
  policy — `baseline_policy_id`, `alpha`, and all coefficients — so any
  change of normalization or of `alpha` changes the plan identity, and a
  persisted old plan (carrying `first-stage-base-v1`) can never be
  reinterpreted as a mean-token plan.
- `baseline_policy_id` becomes schema-configurable
  (`llm_rerank/baseline_policy_id`) with the new value as the compiled
  default. This lets deployments pin the strategy explicitly and lets the
  calibration harness emit plans with the correct identity for each policy.
- **Policy binding (round-2 acceptance)**: the daemon transport protocol is
  **version 2** and every request carries an explicit
  `baseline_policy_id`. Each daemon scoring mode accepts exactly one
  declared policy id (`mean_token` accepts `mean-token-lm-v1`; the
  calibration-only `legacy_sum` mode accepts `first-stage-base-v1`) and
  fails the request closed with a structured, content-free `policy_mismatch`
  error on any other id. A mean-token plan can therefore never be silently
  served by a legacy daemon or vice versa; the C++ client passes the whole
  window through in original order. There is no v1 compatibility layer (no
  consumer exists for it).
- The daemon gains a `--scoring` switch: `mean_token` (production default,
  this ticket) and `legacy_sum` (calibration-only faithful reproduction of
  the pre-change algorithm — sum over all suffix tokens, first token skipped
  when the prefix is empty, no anchor). The legacy mode exists solely so the
  old policy's numbers can be reported on the 120/402 denominator without
  duplicating scoring logic in the calibration tooling, and it only serves
  legacy plans (`first-stage-base-v1`), never production mean-token plans.

## Calibration protocol

Canonical fixture (owner decision, Habit130/squirrel#46): the versioned
120/402 fixture from Squirrel PR #24, head commit
`b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b`:

- corpus: `scripts/eval/corpus/sentences.txt` (120 sentences, SHA-256
  `a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae`);
- word cases: 402 deduplicated standalone word cases in sorted order from
  that commit's deterministic `derive_word_cases`;
- fixture librime: `33e78140250125871856cdc5b42ddc6a5fcd3cd4` (1.17.0);
- pinyin: `pypinyin==0.55.0`;
- context: standalone word protocol — preceding text empty (which is what
  makes the EOS anchor rule above a required part of the policy).

The calibration harness lives in `eval/` of this repository, with the corpus,
the generated fixture manifest, the driver, the verifier, and the final
manifest/results committed, so a fresh checkout can re-verify.

Protocol:

1. Isolated disposable `rime_dir` per parameter set; never
   `~/Library/Rime`.
2. Full 402 word cases are the primary denominator (no subsampling); the 120
   sentence cases are reported separately as a guard that sentence candidates
   are unaffected.
3. Freeze inputs, expected words, candidate sets, and merge order before the
   sweep; assert per case that the candidate text multiset is identical at
   every `alpha` (the filter only reorders, it never changes the set).
4. `beta_sys = beta_usr = 1`, `gamma = 0`, `saturate_k = 3` fixed; the only
   variation is LM normalization and `alpha`.
5. Pre-declared `alpha` grid written to the manifest before looking at any
   metric: `[0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]`. If the optimum
   falls on the grid's upper boundary, extend by `{14.0, 20.0}`; if it is
   still on the boundary, report that no internal optimum exists.
6. Random seed fixed at 42 and reported; the pipeline is deterministic (the
   seed governs auxiliary analysis only).
7. Report per policy: word top-1 / top-5 / MRR, sample counts, and
   score/token-count distributions; old `alpha`, new `alpha`, the delta, and
   any harmful regression (a case whose expected word was rank 1 without the
   LLM term and is no longer rank 1 with it).
8. Historical 78-case numbers are background only, never a paired baseline.

## Calibration result

Run on the canonical 120/402 fixture (see `eval/manifest.json` and
`eval/SUMMARY.md`):

- Baseline (no LM term): word top-1 126/402 = 0.3134, MRR 0.5130.
- Legacy sum policy at `alpha=2.0`: top-1 126/402 = 0.3134, MRR 0.5132 —
  inert on this denominator (with empty preceding text the old algorithm
  skips the first suffix token, leaving single-token candidates unscored).
- Mean-token sweep: word top-1 degrades monotonically with `alpha` (0.2960
  at 0.5 down to 0.2338 at 10.0); no internal optimum exists in the
  pre-declared grid, and the best grid point sits on the lower boundary, so
  per the pre-declared protocol no unique optimum is declared.
- **Final alpha = 0, `internal_optimum=false`,
  `positive_alpha_qualified=false`** (owner decision): no positive alpha
  qualifies on the canonical fixture — `alpha=0` beats every positive grid
  point on top-1 and MRR. The mean-token implementation and its versioned
  policy identity remain available as a schema-configurable capability, but
  the compiled default keeps the LM term disabled until a contextual
  fixture produces evidence for a positive coefficient. The full positive
  grid is preserved as evidence that no positive value qualified.
- The sentence-level guard is flat at 0.5833 across every run: the filter
  does not reorder sentence candidates.
- Score/token-count distribution (mean-token runs): token counts 1-5
  (histogram 21824/41808/9664/520/8), scores in [-25.0, -5.25] with mean
  -12.05, from 5632 daemon requests / 73824 scored candidates.

## Artifacts and re-verification

`calibrate.py` generates every committed artifact itself — run metrics,
per-case candidate checksums (ordered + multiset), the decision fields
(`final_alpha`, `final_alpha_value`, `internal_optimum`,
`positive_alpha_qualified`, `final_alpha_rationale`), the manifest with its
canonical checksum, and the summary — with no hand-editing afterwards:

- `manifest_sha256 = sha256(canonical_json(manifest minus manifest_sha256))`
  where `canonical_json` is `json.dumps(obj, ensure_ascii=False,
  sort_keys=True, separators=(",", ":"))` — the same rule
  `eval/verify_artifacts.py` recomputes with.
- `model_identity` covers the actual model weight files (name, size,
  SHA-256 of every shard) and the tokenizer files separately; the absolute
  path is display-only.
- `baseline_candidate_checksums` in results.json carries per-case ordered
  (merge order) and multiset (duplicate-preserving) SHA-256 checksums; the
  manifest carries their canonical aggregate. Every later alpha run must
  reproduce the baseline multiset checksums.
- `eval/verify_artifacts.py` (read-only) checks the fixture, the manifest
  checksum, results<->manifest consistency, metrics and harmful-regression
  counts recomputed from committed `case_ranks` (both copied summaries and
  the decision must match those derived values), the baseline candidate
  manifest, and that SUMMARY.md regenerates byte-for-byte.

## Verification

- C++: `cmake --build . --target llm_rerank_test` and the test binary; the
  mean-token change adds attribution/identity/policy-binding tests.
- Model-free daemon gate (clean Python, no transformers/MLX/model):
  `python3 -m unittest discover -s daemon -p 'test_*.py'` — protocol, fake
  tokenizer, fake logits, pure functions.
- Integration (explicit opt-in, daemon venv required):
  `daemon/.venv/bin/python daemon/integration_tokenizer.py`,
  `daemon/integration_prefix_invariant.py`,
  `daemon/integration_cache_limit.py`, and an isolated daemon plus
  `daemon/integration_memory.py`. Missing transformers/model fails these
  with an explicit configuration error, never a fake pass.
- `eval/.venv/bin/python eval/verify_fixture.py --dict ...` and
  `eval/verify_artifacts.py --dict ...` for the committed artifacts.
- `make librime` from the Squirrel repo root and confirm both dylib copies.
