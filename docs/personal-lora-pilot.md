# Local MLX LoRA feasibility pilot (`personal-lora-pilot`)

This document is the authoritative description of the Squirrel#176 pilot
(contract AC-176-v1, parent spec #174). It covers the completion-only
objective seam, the pinned identities, the bounded envelope probes, the
sustained measurement protocol, the save/reload agreement check, the private
and public output boundary, and the recommended #177 training shape or
blocker.

The pilot only measures whether one genuine local MLX LoRA train/save/reload
path is operable on the M5/24 GB Mac and how long a full run should take. It
does not train the production adapter, score the sealed test partition, claim
ranking benefit, upload data, or change live behavior. The implementation is
`eval/personal_lora_pilot.py`; synthetic tests are
`eval/test_personal_lora_pilot_objective.py`,
`eval/test_personal_lora_pilot_isolation.py` and
`eval/test_personal_lora_pilot_runner.py`.

## Objective and serialization

One train example is the raw string concatenation `prompt + completion` from
`dataset/train.jsonl` (`prompt` = stored 上文, `completion` = the finally
committed selected word). The serialization seam is frozen:

- the pinned tokenizer is called **once** on the concatenated string; no chat
  or instruction template is applied and no EOS/sentence-end material is
  appended;
- token sides are assigned by the tokenizer's character offsets: a token
  whose first character lies at or after the prompt/completion boundary is
  completion-side, every other token is prompt-side;
- a token that **spans** the boundary is charged to the **prompt side**, is
  counted, and is reported; it is never silently assigned to the loss side.
  This keeps prompt characters out of the loss at the cost of not training
  the merged token, and it makes examples whose whole completion is absorbed
  into a boundary-spanning token untrainable (counted in the aggregate);
- loss is completion-only causal language-model cross-entropy: with inputs
  `x[:-1]` and targets `x[1:]`, target position `t` contributes only when
  `t >= prompt_side`, so the prompt is never trained;
- the pinned Qwen3 tokenizer has `add_bos_token = false`; if a tokenizer
  required a BOS it would be an input-only token charged to the prompt side,
  never a target;
- batches are right-padded to the batch maximum; padding targets are masked
  out and, because padding is at the end, no attention mask is needed.

Synthetic fixtures in `eval/test_personal_lora_pilot_objective.py` pin each
rule, including the boundary-spanning fixture.

## Pinned identities

- Model: causal `Qwen3-0.6B-Base` at `/Users/habit/Models/Qwen/Qwen3-0.6B-Base`
  (read-only). The identity manifest records per-file SHA-256 for every model
  file, a composite digest, the tokenizer class, and the key model-config
  fields; `model_type=qwen3` and `architectures=[Qwen3ForCausalLM]` are
  asserted, embedding and encoder-decoder substitutes are refused.
- Runtime: ticket-local venv with `mlx==0.32.0`, `mlx-lm==0.31.3`,
  `numpy==2.4.6` (matching `daemon/requirements-daemon.txt`). Any mismatch is
  an `environment_blocker`; the pins are never bumped here.
- Dataset: the Completed #175 freeze at plugin
  `origin/master@2076d0a6c92dbf57833b7a123ea54aab10ddd49d`. `train.jsonl`
  `c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2`,
  `manifest.json`
  `5d02844d5e365d67360c52d2946ef54c4d1d0a00730c84fa3314562704774bae`;
  the manifest train binding and line count are re-checked.

## Envelope and probes

The frozen envelope is ranks `{8, 16}` and micro-batches `{1, 2, 4, 8}`, LoRA
modules `q_proj, k_proj, v_proj, o_proj`, LoRA alpha = rank (MLX `scale =
alpha / rank = 1.0`), dropout 0, AdamW `learning_rate 1e-4`, `weight_decay 0`,
seed `176`, gradient accumulation to effective batch 8 examples, padding to
the batch max. The base weights are bfloat16; LoRA parameters and optimizer
state are float32.

At most one short probe runs per declared `(rank, micro-batch)` pair: one
warmup group (accumulate micro-batches plus one optimizer update) and three
measured groups. A probe is rejected when it runs out of memory or when swap
usage grows by more than 256 MB. The pair is chosen by: no sustained swap
growth, then highest examples/s, then rank 16 over rank 8 within a 2%
throughput tie. Probe results are persisted after every pair and resumed, so
a rerun never repeats a probe.

## Sustained measurement

At the chosen pair the pilot reloads the base model, applies fresh LoRA, runs
two warmup groups and then measures at least 20 minutes of post-warmup
train-partition training. Setup (identity, tokenization, probes) and warmup
are reported separately. The run records wall-clock micro-batch and optimizer
update times, padded widths, per-group loss, `mx.get_peak_memory()`, periodic
`vm.swapusage` and thermal samples, and the top-CPU process before the run.
Train-side save/validation cost is measured with 192 frozen train examples
and one adapter save; the sealed validation/test files are never parsed or
used as tuning or save-cost material (their file checksums are recorded).

After the sustained window the pilot verifies the frozen 32-example train
subset (the first 32 trainable examples in file order): the trained
in-memory adapter's per-example completion log-sum and the same log-sum after
`mx.save_safetensors` plus a fresh process-free reload through
`mlx_lm.tuner.utils.load_adapters` must agree within `1e-4`. Adapter weight
digests before and after the optimizer steps prove the update is real.

## Feasibility estimate

The full-run estimate uses only measured quantities: the post-warmup
micro-batch and update times, the chosen accumulation, the trainable example
count, the measured per-example train-side evaluation cost, the measured
adapter save time, and the frozen validation partition line count. Steps per
epoch are `ceil(trainable_examples / 8)`; the estimate covers the recommended
number of epochs, each with a validation pass and a checkpoint save. The
terminal is `local_feasible` with the estimate when the total is within 12
hours, otherwise `capacity_blocker` with the failing measurement.

## CLI, artifacts and boundaries

```sh
# ticket-local venv; relative paths resolve against the repository root
python3 eval/personal_lora_pilot.py --self-test
python3 eval/personal_lora_pilot.py --run --config .local-work/personal-lora-pilot/config.json
python3 eval/personal_lora_pilot.py --verify-reload --config .local-work/personal-lora-pilot/config.json
```

Exit status: `0` run completed with its terminal or verify-reload PASS; `1`
config/isolation/schema/internal error or verify-reload FAIL; `3`
`environment_blocker` with the failing identity or runtime.

All private outputs stay under `<worktree>/.local-work/personal-lora-pilot/`
with owner-only permissions (0700 directories, 0600 files); the ticket-local
venv lives next to it and is not part of the artifact root:

```text
config.json                 operator-supplied paths, expected digests, run
identity.json               model/dataset/runtime identity manifest
run/probes.json             one row per declared envelope pair
run/measurement.json        chosen pair, timings, estimate, terminal
run/verification.json       pre/post log-sum scores, digests, agreement
adapter/adapters.safetensors  private adapter weights
adapter/adapter_config.json   reload metadata (rank/scale/modules/layers)
public-report.md            desensitized aggregate report
```

The public report contains versions, digests, aggregate token-length tables,
probe/timing/memory/swap/thermal aggregates, the agreement result and the
estimate. It contains no prompt/completion text, no event identifiers and no
absolute private paths; the default console output is aggregate-only.

Isolation rules enforced by the implementation:

- `validation.jsonl` and `test.jsonl` are opened only in binary mode for
  SHA-256 checksumming and are never parsed; an invalid-JSON sealed file must
  not block or influence the run;
- artifact roots outside the ticket root or inside live locations
  (`~/Library/Application Support/Squirrel`, `~/Library/Rime`) are refused,
  including symlink aliases;
- no live input-method, deployment, fact-store or configuration mutation; no
  upload; no network use beyond the pinned packages;
- `--run` is idempotent: a completed measurement whose tool, dataset and run
  bindings match is re-verified (adapter digest, verification scores, public
  report) instead of replaced, so a rerun cannot duplicate probes or the
  sustained window; a binding mismatch refuses to replace the artifacts.

## Frozen run

The frozen measurement for this delivery is appended to this section by the
delivery-head commit (aggregate-only evidence). The private report lives at
`.local-work/personal-lora-pilot/public-report.md`.

## Limitations

- The boundary rule deliberately charges spanning tokens to the prompt side;
  its cost is an honest aggregate (untrainable examples and untrained
  completion tokens) rather than a silent loss-side assignment.
- The estimate covers one complete run plus routine validation/checkpointing
  only; data preparation and the #178 ranking evaluation are separate.
- Rank, alpha and modules are a bounded feasibility envelope, not a quality
  search; no ranking benefit is claimed or measurable here.
- Timings are single-machine, single-run measurements on a shared personal
  Mac; the quiet-machine interval and any contention are recorded.
