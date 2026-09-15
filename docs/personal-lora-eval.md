# Personal LoRA candidate-ranking evaluation (`personal-lora-eval`)

This document is the authoritative description of the Squirrel#178 execution
(contract AC-178-v1, parent spec #174). It covers the frozen scoring seam,
the validation-only policy lock, the single locked test pass, the verdict
rule, the Mac candidate-scoring latency protocol, the private/public output
boundary, and the one frozen run's aggregate evidence.

The delivery evaluates whether the selected #177 epoch-2 personal LoRA
adapter improves real candidate ranking relative to the historical Rime
display order and unadapted Qwen, and whether candidate scoring is practical
on this Mac. It does not activate the adapter live, replace BGE, upload data,
change pins, or claim that offline scoring repairs live `get_context` wait.
The implementation is `eval/personal_lora_eval.py`; synthetic tests are
`eval/test_personal_lora_eval_objective.py`,
`eval/test_personal_lora_eval_runner.py` and
`eval/test_personal_lora_eval_isolation.py`.

## Systems and scoring seam

Three systems rank the same saved competition of a ranking-eligible event:

1. **Rime reference** — the recorded historical `display_page`/`display_rank`
   of the finally committed target. Top-1 means the target was recorded at
   page 1 rank 1; MRR uses `1/display_rank` on page 1 and `0` on a deeper
   page. It is disclosed as the observed UI order, not an as-of Rime weight
   replay. The saved target position and the recorded rank disagree in 20 of
   1,121 validation groups and 13 of 1,098 test groups; the recorded rank is
   used and the disagreement is reported.
2. **unadapted Qwen** — pinned causal `Qwen3-0.6B-Base`.
3. **LoRA adapter** — the selected #177 epoch-2 adapter.

Candidates are never generated: a ranking-eligible JSONL row is joined to
the frozen snapshot by `event_id` and the candidate texts are exactly the
saved `selection_candidates` rows in ascending `merge_order`. The target is
the first saved candidate whose simplified-NFC text matches the row's
committed target; the frozen `#175` ranking-eligibility flags and integrity
checks (non-empty saved list, strictly increasing merge order, target
membership, snapshot `preceding_text`/`final_selection_text` equal to the
JSONL `prompt`/`completion`) are re-verified and any mismatch fails closed.

Completion scoring reuses the accepted #176/#177 seam: the pinned tokenizer
is called once on `prompt + candidate`; a token whose first character is at
or after the prompt boundary is completion-side; a boundary-spanning token
is charged to the prompt side, counted, and never scored. The per-candidate
value is the completion-only log-sum over positions
`t >= max(1, prompt_side)` and `t < total_tokens`. Candidates with no
completion-side target are unscored omissions: counted per system, excluded
from that system's argmax, and never silently ranked last. Scores are
compared in fp32; ties keep the saved merge order.

## Frozen policies and the lock (EVAL-2)

| Policy | Definition | Availability |
| --- | --- | --- |
| S1 | completion log-sum / completion tokens (mean log-prob) | always |
| S2 | completion log-sum | always |
| S3 | `dict_weight + 1.0 * mean_logprob` | only with a finite saved numeric weight for every scored validation candidate |
| S4 | `dict_weight + 0.5 * mean_logprob` | same precondition |

The frozen #175 snapshot saves `(event_id, merge_order, text)` and no
numeric candidate weight, so the S3/S4 precondition is **not available** in
this dataset. That is recorded as `n/a`, not a Fail. The lock records the
observed candidate columns and the number of validation candidates examined.

Selection runs on the **validation ranking-eligible** groups only, using the
LoRA adapter's top-1 first, then LoRA MRR, then the fixed policy order
`S1 > S2 > S3 > S4`. `policy_lock.json` is written before `test.jsonl` is
parsed as text; before that the sealed test file is opened only in binary
mode for its SHA-256 checksum. `--eval-test` refuses to run without a lock
that matches the current identities and binds the sealed test checksum, and
a conflict between the recomputed selection and an existing lock is an
error, never an overwrite. The locked policy is applied to all three systems
(and to unadapted Qwen) in the test pass.

## Metrics, verdict and strata (EVAL-3/4)

The locked test pass scores the sealed test partition once under the locked
policy and reports, on the common denominator (rows where both model systems
score the target):

- top-1 and MRR per system;
- mispromotion: the Rime reference had the target first and the model moved
  it out of first;
- target completion log-loss (token-weighted mean NLL over targets with at
  least one completion-side token), reported separately from ranking;
- replay/unscored omissions: candidate omissions and rows whose target could
  not be scored (empty-context and consumed completions), per system;
- strata: empty vs nonempty context, train-seen vs unseen exact
  `(prompt, completion)` pair, train-seen vs unseen choice key, where
  membership is taken from `train.jsonl` read-only.

The verdict rule is frozen: `inconclusive` iff the ranking-eligible scored
denominator is `< 200` or omitted ranking-eligible rows exceed `20%`;
otherwise `benefit` iff LoRA top-1 is strictly greater than both the Rime
reference and unadapted Qwen, else `no_benefit`. An improved target log-loss
is not ranking benefit. No extra policy search, no post-test retuning and no
second test pass are allowed; a completed `test/results.json` is verified
and reused rather than recomputed.

## Mac scoring latency (EVAL-5)

`--measure-latency` scores **all** validation ranking-eligible groups
(1,121) with the exact adapter, one group at a time. It requires the
matching `policy_lock.json` and uses the locked policy for the ranking step.
Cold is the first group after the model load; warm is every remaining group.
The timed per-group wall clock covers candidate tokenization, the padded
model forward, the completion-only log-sum, the locked-policy score
application and the candidate sort; per-candidate time is the group time
divided by the group's saved candidates. p50/p90/p99 are reported for both,
together with the model load time, MLX peak/active/cache memory, process max
RSS, swap before/after and the surrounding system samples. This is offline
candidate scoring only: not IMK/panel presentation and not a live
`get_context` wait repair claim.

## CLI, artifacts and boundaries

```sh
# ticket-local venv (`mlx==0.32.0`, `mlx-lm==0.31.3`, `numpy==2.4.6`)
python3 eval/personal_lora_eval.py --self-test
python3 eval/personal_lora_eval.py --select-policy \
  --config .local-work/personal-lora-eval/config.json
python3 eval/personal_lora_eval.py --eval-test \
  --config .local-work/personal-lora-eval/config.json
python3 eval/personal_lora_eval.py --measure-latency \
  --config .local-work/personal-lora-eval/config.json
```

Exit status: `0` the command recorded or reused its artifact; `1`
config/isolation/schema/lock/internal error; `3` `environment_blocker` with
the failing identity or runtime.

All private outputs stay under `<worktree>/.local-work/personal-lora-eval/`
with owner-only permissions (0700 directories, 0600 files); the ticket-local
venv lives next to it and is not part of the artifact root:

```text
config.json                    operator-supplied paths and expected digests
identity.json                  model/adapter/dataset/snapshot/runtime identity
policy_lock.json               the frozen validation selection (write-once)
validation/selection.json      validation policy statistics and group summary
test/results.json              the single locked test pass and verdict
test/per-group.json            private per-group ranks and log-sums (no text)
latency/measurement.json       cold/warm latency and resource log
latency/per-group.json         private per-group timings
public-report.md               desensitized aggregate report
```

The public report contains identities, the lock, aggregate counts, the
comparisons, the verdict and timings. It contains no prompt, completion or
candidate text, no event identifiers and no absolute private paths; the
default console output is aggregate-only. Errors refuse rather than rebind:
`identity.json` is written once per binding, the lock is immutable under a
conflict, and completed test results or latency measurements are reused only
when the identities, tool digests and lock checksum match.

Isolation rules enforced by the implementation:

- `test.jsonl` is parsed only after a matching `policy_lock.json` exists; a
  pure-Python guard refuses any earlier text parse, and the pre-lock path
  opens the file in binary mode only. Invalid JSON in the sealed file cannot
  block the validation-only selection;
- artifact roots outside the ticket root or inside live locations
  (`~/Library/Application Support/Squirrel`, `~/Library/Rime`) are refused,
  including symlink aliases;
- no live input-method, deployment, fact-store or configuration mutation; no
  upload; no network use beyond the pinned packages; no pin bump;
- the identity manifest binds the executed `personal_lora_data`,
  `personal_lora_pilot` and `oracle` module digests, the adapter
  `adapters.safetensors` digest **and** the `adapter_config.json` digest, so
  a changed seam or a changed effective adapter config invalidates reuse and
  verification;

## Frozen run (2026-09-15, aggregate-only evidence)

Executed from the delivery worktree with the ticket-local venv in announced
GPU/quiet-machine intervals: `--select-policy` (validation only),
`--eval-test` (one locked pass), `--measure-latency`. Identities:

- model composite sha256
  `f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa`
  (causal `Qwen3ForCausalLM`); runtime `mlx 0.32.0 / mlx-lm 0.31.3 /
  numpy 2.4.6`;
- selected adapter `adapters.safetensors` sha256
  `7622f26d71efa34f5b9b1e92ebef2c064bd06363c3eac4c88fb0adb44b1462d9`
  (18,374,616 bytes), `adapter_config.json` sha256
  `d11ca5ab361149c8b95c0b1a8ceaf3678d0d17ad42209e3d0de02bc6a70d65cd`,
  `epoch=2`, `base_model_composite_sha256` equal to the frozen base
  composite, `rank=16`, `alpha=16`, `mlx_scale=1.0`, `num_layers=28`,
  dropout 0, `q/k/v/o`; the selected bytes are identical to the
  `epochs/epoch-2/adapters.safetensors` checkpoint
  (`matches_selected=true`), which excludes a warm start or a different
  checkpoint;
- dataset freeze commit `2076d0a6c92dbf57833b7a123ea54aab10ddd49d`, train
  `c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2`,
  validation
  `80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8bdeaa880`,
  manifest
  `5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704774bae`,
  sealed test
  `12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a9f2d2b`;
- snapshot sha256
  `be2b09256dd2c24485ed618501fc06408b4441e1d14a8d86d2645797e82ae6de`
  (`store_epoch 8407bd6b456ba5c5a526b4b95951bac3`, `history_id
  dc3ffbf1a21957e0bb4ceed535c9df56`, high-water `1789348852036, 0`);
- delivery tool sha256
  `f5a5c3c6e4c7b2624bcab161ed87e81c8ccda45c11b23ddd80395e1543d98234`;
  the tool pins the exact `adapter_config.json` digest and its semantic
  fields (epoch, rank, alpha, MLX scale, dropout, modules, layer count,
  objective, seed, training config hash, `#175` train partition and freeze
  commit) in addition to the adapter weight digest.

### Validation-only policy lock

| Policy | Validation top-1 | Validation MRR | Ranked rows |
| --- | --- | --- | --- |
| S1 | 830 (0.791985) | 0.869518 | 1048 |
| S2 | 969 (0.924618) | 0.956824 | 1048 |
| S3 | n/a | n/a | n/a |
| S4 | n/a | n/a | n/a |

Selected policy: **S2** (completion log-sum). Weight precondition: not
available (the frozen snapshot saves no candidate numeric weight); S3/S4 are
recorded `n/a`, not a Fail. Validation ranking-eligible groups 1,121 (536
ineligible), saved candidates 8,222, empty-context 14, deeper than first page
0, recorded display rank equals saved position 1,101/1,121, 984/1,121 choice
keys and 11 exact pairs seen in train; 73 rows had an unscored target and 82
candidates were unscored omissions, 199 candidates were boundary-spanning.

### Locked test ranking (one pass, policy S2, common denominator 1,035)

| System | Ranked rows | Top-1 | Top-1 rate | MRR | Mispromotion | Target log-loss |
| --- | --- | --- | --- | --- | --- | --- |
| Rime reference | 1,035 | 1,000 | 0.966184 | 0.981594 | 0 | n/a |
| unadapted Qwen | 1,035 | 970 | 0.937198 | 0.963879 | 54 | 5.638324 |
| LoRA epoch 2 | 1,035 | 980 | 0.946860 | 0.969499 | 41 | 4.688958 |

Test partition: 1,098 ranking-eligible (500 ineligible), saved candidates
8,115, empty-context 3, deeper than first page 1, recorded rank equals saved
position 1,085/1,098; 63 rows had an unscored target (denominator
omission rate 0.057377, below the 20% cap), 66 candidate omissions and 149
boundary-spanning candidates; 974/1,098 choice keys and 2 exact pairs seen in
train.

Strata on the common denominator:

| choice_key | rows | Rime top-1 | Qwen top-1 | LoRA top-1 | LoRA MRR |
| --- | --- | --- | --- | --- | --- |
| train_seen | 913 | 892 | 875 | 887 | 0.984337 |
| train_unseen | 122 | 108 | 95 | 93 | 0.858456 |

| context | rows | Rime top-1 | Qwen top-1 | LoRA top-1 | LoRA MRR |
| --- | --- | --- | --- | --- | --- |
| empty | 0 | 0 | 0 | 0 | 0.000000 |
| nonempty | 1,035 | 1,000 | 970 | 980 | 0.969499 |

| exact_pair | rows | Rime top-1 | Qwen top-1 | LoRA top-1 | LoRA MRR |
| --- | --- | --- | --- | --- | --- |
| train_seen | 1 | 1 | 1 | 1 | 1.000000 |
| train_unseen | 1,034 | 999 | 969 | 979 | 0.969470 |

Empty-context rows are structurally unscored by the models (an empty prompt
leaves a one-token candidate with no predictable completion token), so the
empty stratum has zero common-denominator rows; those rows are counted in the
omission rate instead.

### Verdict (EVAL-4)

**`no_benefit`** — LoRA top-1 is 980 (0.946860), the Rime reference is 1,000
(0.966184) and unadapted Qwen is 970 (0.937198). LoRA is strictly greater
than unadapted Qwen but not greater than the Rime reference, so the frozen
rule returns `no_benefit`. The adapter's target completion log-loss is lower
than unadapted Qwen (4.688958 vs 5.638324) and its unseen-choice-key top-1 is
similar to unadapted Qwen (93 vs 95 of 122), which is reported as a separate
observation and not as ranking benefit.

### Mac candidate-scoring latency

| Metric | cold (1 group) | warm (1,120 groups) | all (1,121 groups) |
| --- | --- | --- | --- |
| group seconds p50/p90/p99 | 0.088407/0.088407/0.088407 | 0.118844/0.295518/0.551713 | 0.118768/0.295518/0.551713 |
| per-candidate seconds p50/p90/p99 | 0.011051/0.011051/0.011051 | 0.020781/0.048861/0.105857 | 0.020763/0.048861/0.105857 |

The timed region is candidate tokenization + padded model forward +
completion-only log-sum + locked-policy (S2) ranking. Model load 0.3340 s
(warm page cache); scoring 178.95 s for 1,121 groups and 8,222 candidates;
MLX peak 3.2164 GB, active 1.1273 GB, cache 0.1530 GB; process max RSS
1,427.1 MB; system swap before/after 5,746.6/6,130.5 MB (the shared machine
was not idle: the pre-run top-CPU process was the ticket-owned Python
process at 85.9%, the post-run top process a browser helper at 74.2%; the
live input method stayed running). The three passes measured the same warm
p50 in the range 0.062–0.119 s per group (0.012–0.021 s per candidate),
which is disclosed as shared-machine contention rather than a protocol
change; the delivered pass is the one bound in `latency/measurement.json`.

### Provenance and superseded passes

Two earlier passes were archived before Acceptance, each after a Codex
review round whose findings were confirmed and fixed:

- pass 1 (tool `0a9a4dc111b6d5499eb69356014abf1fe880647bd0cac388c89f1418d12bee1e`,
  archived `superseded/20260915T075708Z/`) — findings: the model-free
  release gate would fail on an unconditional `mlx` import in the objective
  tests (MLX tests now skip when `mlx` is absent); the fake-backend tests
  reached the pinned-runtime check under the model-free venv (the fixture
  now stubs the runtime probe); the adapter `adapter_config.json` digest was
  not bound (now bound); the latency timer excluded the ranking step (now
  included, and `--measure-latency` requires the lock);
- pass 2 (tool `3464ffd2d20745bd59bacb3adf2d6ffd7e73a4de016068d958eea82c46c1327f`,
  archived `superseded/20260915T082522Z/`) — findings: the adapter config
  was bound between phases but not authenticated against a frozen digest
  (now pinned with semantic checks); latency reuse did not verify the lock
  digest or policy (now stored and verified).

The delivered pass re-selected the policy on validation only (S2 again;
per-policy statistics and test aggregates bit-identical across all three
passes, which is recorded as determinism evidence). No test-informed change,
no retuning, no competitor invention and no second locked pass on the
delivered artifacts were made; the delivered artifact set contains exactly
one test pass.

### Isolation and cleanup

`test.jsonl` was checksummed before the lock and parsed only after the
matching lock existed; the delivered test pass ran exactly once and was
reused by later verification; no live mutation, deployment, upload or pin
bump happened; all artifacts are owner-only; the scoring processes exited and
the GPU/quiet-machine intervals are released.

## Limitations

- The Rime reference is the recorded observed UI order, not an as-of Rime
  weight replay; the saved position and recorded rank disagree in a small
  number of groups (reported).
- Models only rerank the saved same-group competition; deeper-page recall
  expansion, sentence generation and cross-group overrides are out of scope.
- Completion-side scoring excludes boundary-spanning tokens and candidates
  with no completion-side target; those omissions are counted, and
  empty-context rows cannot be ranked by the models at all.
- The test partition is a sealed historical split, not a project-wide
  untouched prospective test; later retractions require a new
  dataset/adapter version. Improved train/validation loss is not ranking
  benefit.
- Latency is offline candidate scoring on a shared personal Mac, not
  IMK/panel presentation, not training-step time and not a live
  `get_context` wait repair claim.
- The one frozen run cannot distinguish a policy difference that would have
  appeared under a different finite policy; S3/S4 were unavailable in this
  snapshot and are recorded, not searched.
