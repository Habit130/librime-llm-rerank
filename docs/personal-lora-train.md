# Frozen personal LoRA training (`personal-lora-train`)

This document is the authoritative description of the Squirrel#177 execution
(contract AC-177-v1, parent spec #174). It covers the frozen completion-only
objective seam, the pinned identities, the frozen hyperparameters, the
predeclared checkpoint-selection rule, the per-epoch checkpoint/resume
protocol, the save/reload agreement check, the private/public output
boundary, and the one frozen run's selected checkpoint.

The delivery trains and selects exactly one personal LoRA adapter. It does
not score the sealed test partition, claim ranking benefit, change live
`alpha`/`gamma`/evidence, upload data, or start #178. The implementation is
`eval/personal_lora_train.py`; synthetic tests are
`eval/test_personal_lora_train_objective.py`,
`eval/test_personal_lora_train_runner.py` and
`eval/test_personal_lora_train_isolation.py`.

## Objective and serialization

The objective and serialization seam is imported from the accepted #176 pilot
(`eval/personal_lora_pilot.py`) so the training and validation masks cannot
drift from the frozen rule:

- one train/validation example is the raw string concatenation
  `prompt + completion`; the pinned tokenizer is called **once** on it, with
  no chat or instruction wrapper and no synthetic EOS material;
- token sides come from tokenizer character offsets: a token whose first
  character is at or after the prompt/completion boundary is completion-side;
  a token that spans the boundary is charged to the prompt side, counted and
  reported, never assigned to the loss;
- loss is completion-only causal cross-entropy: target position `t`
  contributes only when `t >= max(1, prompt_side)`, so no prompt token and no
  boundary-spanning token is ever trained;
- examples with no completion-side target are untrainable; they are skipped
  and reported, never repaired or padded into the loss;
- batches are right-padded to the batch maximum; padding targets are masked
  out and the prompt mask is unchanged by padding.

Validation uses the same mask: the mean completion-only loss is the
token-weighted mean of per-example completion cross-entropy over all
trainable validation examples (`sum NLL / sum completion tokens`).

## Pinned identities

- Model: causal `Qwen3-0.6B-Base` at `/Users/habit/Models/Qwen/Qwen3-0.6B-Base`
  (read-only). The identity manifest records per-file SHA-256, the composite
  digest and the key model-config fields; `model_type=qwen3` and
  `architectures=[Qwen3ForCausalLM]` are asserted, and the composite must
  equal the accepted #176 identity
  `f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa` or the
  run is an `environment_blocker`.
- Fresh LoRA only: the training model is loaded from the base directory and
  LoRA layers are initialized by `linear_to_lora_layers` after
  `mx.random.seed(176)`; no adapter path is ever loaded before training. The
  pilot adapter is not a warm start and is not referenced.
- Runtime: ticket-local venv with `mlx==0.32.0`, `mlx-lm==0.31.3`,
  `numpy==2.4.6`. Any mismatch is an `environment_blocker`; the pins are
  never bumped here.
- Dataset: the Completed #175 freeze at plugin
  `origin/master@2076d0a6c92dbf57833b7a123ea54aab10ddd49d`.
  `train.jsonl`
  `c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2`,
  `validation.jsonl`
  `80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8bdeaa880`,
  `manifest.json`
  `5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704774bae`; the
  manifest train binding and line counts are re-checked.
- `test.jsonl` is checksummed only
  (`12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a9f2d2b`). It is
  opened in binary mode for hashing and is never parsed; the test partition
  is not an input to training, validation, selection or this delivery's
  claims.
- The frozen run also records the model weight file SHA-256
  (`model.safetensors`), the tokenizer class/backend and the train/validation
  token aggregates in its private identity manifest and public report.

## Frozen hyperparameters

No search, no extra grid, no early stop. The config's `run` section is
compared against these values and any deviation is refused before the run
starts; the canonical hash of the resolved shape is the run's
`config_sha256`.

| Item | Frozen value |
| --- | --- |
| epochs | 3 |
| LoRA rank / alpha / dropout | 16 / 16 / 0 |
| LoRA modules | `self_attn.q_proj`, `k_proj`, `v_proj`, `o_proj` on all decoder layers |
| precision | bf16 base weights, fp32 LoRA and optimizer |
| micro-batch / accumulation / effective batch | 8 / 1 / 8, padded to the batch maximum |
| optimizer | AdamW, lr `1e-4`, weight decay `0` |
| seed | 176 |
| cache policy | `mx.clear_cache()` whenever the MLX cache exceeds 2,000,000,000 bytes, and at least once per epoch |
| validation | frozen validation partition, completion-only loss after every epoch |
| selection | lowest validation loss; an exact tie goes to the later epoch |
| budget | 12 hours for the run plus per-epoch validation/checkpointing |

## Epochs, checkpoints and resume

Each epoch is one deterministic shuffled pass over the 11,259 trainable train
examples in batches of 8 (`random.Random(seed + epoch)`); the final batch is
smaller when the count is not divisible. After every epoch the runner
computes the validation loss, records the frozen 32-example train subset
log-sums for that epoch's weights, and writes an owner-only checkpoint under
`epochs/epoch-<n>/` (`adapters.safetensors` plus `adapter_config.json`). A
`run/epochs.json` row and `state.json` are written after each epoch, so an
interrupted run is resumable.

The run stops with `runtime_blocker` (wall clock) or `capacity_blocker`
(out of memory) if the frozen work cannot complete, leaving the last complete
epoch's checkpoint plus `next_epoch` in `state.json`. A rerun with the same
binding resumes from `next_epoch` with the last checkpoint's weights (the
optimizer state is re-initialized; the interrupted partial epoch is
discarded and re-run from its seeded order) and records
`resumed_from_epoch`. A run that reached `trained` is never rewritten: a
rerun re-verifies the recorded artifacts and reports `run_reused=true`.
`identity.json` is written once and is never overwritten by a reuse or resume.

After the third epoch the runner selects the checkpoint by the predeclared
rule and copies it to `selected/`. It then loads a fresh base model, applies
that adapter through `mlx_lm.tuner.utils.load_adapters`, and requires the
per-example completion log-sums of the frozen 32-example train subset to
agree with those recorded at checkpoint time within `1e-4`. The same check is
available standalone as `--verify-reload`.

## CLI, artifacts and boundaries

```sh
# ticket-local venv (`mlx==0.32.0`, `mlx-lm==0.31.3`, `numpy==2.4.6`)
python3 eval/personal_lora_train.py --self-test
python3 eval/personal_lora_train.py --run \
  --config .local-work/personal-lora-train/config.json
python3 eval/personal_lora_train.py --verify-reload \
  --config .local-work/personal-lora-train/config.json
```

Exit status: `0` run recorded its terminal (`trained` or a precise blocker)
or verify-reload PASS; `1` config/isolation/schema/internal error or
verify-reload FAIL; `3` `environment_blocker` with the failing identity or
runtime.

All private outputs stay under `<worktree>/.local-work/personal-lora-train/`
with owner-only permissions (0700 directories, 0600 files); the ticket-local
venv lives next to it and is not part of the artifact root:

```text
config.json                     operator-supplied paths, expected digests, run
identity.json                   model/dataset/runtime/token identity manifest
state.json                      terminal, next_epoch, selection, resume record
run/epochs.json                 one row per epoch (losses, timings, subset scores)
run/measurement.json            terminal, wall clock, memory, cache clears
run/verification.json           selected adapter, log-sum agreement, digests
epochs/epoch-<n>/adapters.safetensors   per-epoch private checkpoint
epochs/epoch-<n>/adapter_config.json    reload metadata
selected/adapters.safetensors   selected private adapter
selected/adapter_config.json    selected reload metadata
public-report.md                desensitized aggregate report
```

The public report contains identities, frozen hyperparameters, token
aggregates, the per-epoch train/validation loss table, the selected epoch,
the selected adapter digest and size, the reload agreement, wall clock,
memory and cache-clear counts. It contains no prompt/completion text, no
event identifiers and no absolute private paths; the default console output
is aggregate-only.

Isolation rules enforced by the implementation:

- `test.jsonl` is opened only in binary mode for SHA-256 checksumming and is
  never parsed; invalid JSON in the sealed test file cannot block or
  influence the run;
- `validation.jsonl` is parsed for the frozen selection rule only; no
  validation text is printed, written to the public report or copied into an
  identity/measurement artifact;
- artifact roots outside the ticket root or inside live locations
  (`~/Library/Application Support/Squirrel`, `~/Library/Rime`) are refused,
  including symlink aliases;
- no live input-method, deployment, fact-store or configuration mutation; no
  upload; no network use beyond the pinned packages;
- `--run` is immutable for a completed run: the recorded binding (tool,
  model composite, dataset digests, config hash) is verified before any
  write, a mismatch refuses to replace the artifacts, and a matching rerun
  only re-verifies.

## Frozen run (2026-09-15, aggregate-only evidence)

The one frozen run was executed from the delivery worktree with the
ticket-local venv (`executed_at_utc` 2026-09-15T00:11:25Z, `done` 00:28:18Z)
and exited `0` with terminal **`trained`**. The recorded tool SHA-256 is
`1017cffb0facb82936e37230bb0ce8764d63f32024f6e30f02e88502c05a73bc`, which is
the delivered `eval/personal_lora_train.py`; `--run` and `--verify-reload` at
the delivery head re-verify against it. A private desensitized copy is at
`.local-work/personal-lora-train/public-report.md`.

- Identities: causal `Qwen3ForCausalLM` composite sha256
  `f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa`,
  `model.safetensors` sha256
  `cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba`
  (1,192,135,096 bytes); runtime `mlx 0.32.0 / mlx-lm 0.31.3 / numpy 2.4.6`;
  dataset freeze commit `2076d0a6c92dbf57833b7a123ea54aab10ddd49d`, train
  `c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2`,
  validation
  `80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8bdeaa880`,
  manifest
  `5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704774bae`;
  sealed test checksum-only
  `12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a9f2d2b`.
- Config: `config_sha256`
  `2dbc170341799901be5733b6e5b37e0bb7b775ac29b39d863fcdb3d299f26abb` for the
  frozen shape exactly as tabled above; no search and no early stop.
- Fresh start: `warm_start=false`, `mlx_random_seed_176`, 4,587,520 trainable
  parameters before the first update; no adapter was loaded before training,
  and the pilot adapter is not referenced.
- Token aggregates match the accepted #176 seam: train 12,675 examples
  (11,259 trainable; 1,416 untrainable; 1,381 boundary-spanning tokens over
  1,381 examples; 131 empty-context, 23 trainable); validation 1,657
  examples (1,451 trainable; 206 untrainable; 208 boundary-spanning tokens;
  16 empty-context, 4 trainable).
- No resume was needed (`resumed_from_epoch: null`). Wall clock
  **1,016.17 s (0.282 h)** against the 12 h budget, including identity,
  tokenization, per-epoch validation, per-epoch checkpoints and the
  save/reload verification. Peak MLX memory **2.775 GB** (active 1.247 GB,
  cache 2.060 GB; process max RSS 2,468 MB). The 2 GB cache policy cleared
  the allocator 2,020 times above threshold plus the 3 epoch floors.

  | epoch | steps | train loss first/last/mean | validation loss | seconds | cache clears | peak GB | selected |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 1408 | 8.76667/3.7875/3.40113 | 5.085509 | 306.44 | 678 | 2.7742 | yes |
  | 2 | 1408 | 2.3875/2.675/2.88943 | 5.122387 | 352.13 | 674 | 2.7742 |  |
  | 3 | 1408 | 2.32083/2.28125/2.49585 | 5.295240 | 353.35 | 671 | 2.7751 |  |

- Selection: **epoch 1** by the predeclared rule (lowest validation
  completion-only loss; no exact tie). Train loss fell while validation loss
  rose over the three epochs; the rule selects on validation only and this
  table is reported as-is. Selected adapter sha256
  `33caed621f05be443778588430b6083520cae78fb149ebae8cb651654951fec8`,
  18,374,616 bytes, identical to the epoch-1 checkpoint; the fresh
  in-process reload and the standalone `--verify-reload` both pass with max
  abs completion log-sum difference **0.0** on the frozen 32-example train
  subset (tolerance `1e-4`). The trainable-weight digest changed from
  `8a4753a6d91345c8cf28b01a3e8f498770ba5bf45e299f28b945b8e5dfa7cfbd` to
  `a95c066852b4b7e221b2e5ebeb4674059ed69ebd7fe307a3783812e8816266ca`.
- Isolation and cleanup: `test.jsonl` checksummed only; `validation.jsonl`
  used only for the frozen rule; no live mutation, deployment, upload, pin
  bump or #178 scoring; all artifacts owner-only; the training process exited
  and the GPU/quiet-machine interval is released. The live input method
  stayed running during the run.

## Limitations

- The boundary rule deliberately charges spanning tokens to the prompt side;
  its cost is an honest aggregate (untrainable examples and untrained
  completion tokens) rather than a silent loss-side assignment.
- Improved training or validation loss is not ranking benefit; the sealed
  test partition and #178 group ranking are out of scope.
- This ticket trains one frozen configuration. It is not a quality search and
  it does not select hyperparameters by outcome.
- Timings are single-machine, single-run measurements on a shared personal
  Mac; the quiet-machine interval and any contention are recorded.
