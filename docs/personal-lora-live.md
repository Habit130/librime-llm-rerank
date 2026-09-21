# Personal LoRA live load (`mean-token-lm-v1`)

Squirrel#184: load the accepted #183 personal LoRA onto local Qwen3-0.6B-Base
in the existing scoring daemon and prove that `alpha=1.0` can change emission
order for one controlled same-span/same-category rerank group. Ranking quality
is not a Pass/Fail gate. Improved training loss is not ranking benefit.

Squirrel#186 is habit's owner-authorized **daily leave-on** of that same path
on the allocated machine: launchd login start, lazy model load, 5-minute idle
unload, BGE replaced, machine-local `alpha=1.0`. Merge of this plugin PR still
does **not** self-enable any machine. Live enablement is the machine state
after an owner-authorized Pass, not the squash-merge.

This is not the BGE personal path (`docs/personal-bge-experiment-runtime.md`,
`docs/personal-experiment-activation.md`). Those documents stay valid. #184
and #186 do not restore BGE. Historical #177/#178 `no_benefit` is not this
live evidence. Do not relabel the #184 stop-state as daily-leave-on evidence.

## Identities

Refuse copy, load, health/reuse, and reload on any mismatch. A mutable YAML
or env var cannot waive these pins.

| Item | Pin |
| --- | --- |
| Base composite SHA-256 | `f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa` |
| `model.safetensors` SHA-256 | `cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba` |
| Selected adapter SHA-256 | `7622f26d71efa34f5b9b1e92ebef2c064bd06363c3eac4c88fb0adb44b1462d9` |
| `adapter_config.json` SHA-256 | `656e2ea61b91f270bbca559b0d6377cac01ede1de7ea11710893a5a7ad4671b8` |
| Runtime | `mlx==0.32.0`, `mlx-lm==0.31.3`, `numpy==2.4.6` in `daemon/.venv` |
| Architecture | causal `Qwen3ForCausalLM`, not embedding/BGE |
| Scoring policy | `baseline_policy_id=mean-token-lm-v1` |

Adapter identity is **not** a scoring-protocol field and **not** a released
schema key. Health may report `adapter_digest`. The tracked public example
stays `alpha: 0.0`.

## Copy (owner-only)

#184 hash-verified the accepted #183 selected adapter and copied it into an
owner-only live root. Do not rewrite #182/#183 artifacts. Do not overwrite,
rebind, or regenerate the sealed `adapter_config.json` / `adapters.safetensors`
bytes.

#186 points launchd/CLI at that sealed dest. Do not copy into a new dest
unless the sealed files would have to be mutated.

```sh
python3 daemon/personal_lora_live.py copy \
  --source /absolute/read-only/selected \
  --dest .local-work/personal-lora-live
python3 daemon/personal_lora_live.py preflight \
  --model /absolute/Qwen3-0.6B-Base \
  --adapter .local-work/personal-lora-live
```

The destination directory is `0700`; copied files are `0600`. Preflight
records tokenizer/config/weight digests and fails closed on mismatch,
including a wrong adapter with the right base.

## Daemon CLI / env / launchd

Use the daemon scoring venv (`daemon/requirements-daemon.txt`). Do not use
the embeddings venv. Do not download models.

```text
--adapter / LLM_RERANK_ADAPTER   local adapter directory; empty = base-only
--model   / LLM_RERANK_MODEL     local Qwen3-0.6B-Base directory
--context-window 64              上文 tail (not the candidate window 32)
```

ADR-0001 lifecycle remains in force:

- launchd job `com.squirrel.llm-rerank` has `RunAtLoad=true` and
  `KeepAlive=true` (login start, restart on crash).
- The daemon process is managed by launchd. Do not also `deploy.py start` on
  the daily path (that would be a second process on the live socket).
- The model is **not** loaded because the daemon started. First scoring
  request pays cold load.
- `IDLE_TIMEOUT` stays 300 seconds and unloads weights. Next request reloads.
  Sleep/lock is not a second timer: no typing means no requests, so idle
  unload covers it.

```sh
python3 daemon/deploy.py install
python3 daemon/deploy.py render-plist \
  --model "$LLM_RERANK_MODEL" \
  --adapter /absolute/sealed-personal-lora-live \
  --output /tmp/com.squirrel.llm-rerank.plist
```

`deploy.py render-plist` substitutes `__ADAPTER__` and sets
`LLM_RERANK_ADAPTER`. Isolated `verify` stays `--health-only` and does not
need an adapter. Isolated render/verify refuse maintainer `/Users/habit`
paths; the allocated-machine LaunchAgents plist is local, untracked, and
carries the Established model/adapter pins.

Foreground start/health/stop remains the isolated and #184 proof path, not
daily leave-on:

```sh
python3 daemon/deploy.py \
  --model "$LLM_RERANK_MODEL" \
  --adapter /absolute/sealed-personal-lora-live \
  start
python3 daemon/deploy.py health
python3 daemon/deploy.py stop
```

At most one heavyweight model may be resident. Qwen+LoRA replaces BGE on
this path. `--health-only` is the BGE/model-free handshake; it does not load
Qwen. Do not restore BGE after leave-on.

## Live-switch (announced interval)

Personal live YAML is machine-local (`~/Library/Rime`). Do not ship it. Do
not edit the tracked `data/luna_pinyin.custom.yaml` or the public contract
example.

Personal parameters:

- `reranking_enabled: true`
- `alpha: 1.0`
- `sys_coeff: 1.0`, `usr_coeff: 1.0`
- `evidence_enabled: false`
- candidate `window: 32`, `deadline_ms: 200`
- recording stays enabled if it is already enabled

`alpha>0` is what opens the filter socket. Redeploy the schema after editing.
Public output is aggregate / identity / lifecycle / order-changed-or-not.
Controlled-group texts may be published only when they are synthetic or
ordinary dictionary strings.

Timeouts, unavailable model (including idle-unloaded), and identity faults
emit the entire original window. Commit stays unblocked.

#184 used this interval only long enough to collect load, BGE-absence,
order-change, and fault-passthrough evidence, then performed the stop
procedure below. #186 keeps the same parameters **on** after handback.

## Daily leave-on (Squirrel#186)

Owner-authorized on the allocated machine only. After DAILY evidence:

- leave launchd loaded (`RunAtLoad` / `KeepAlive`)
- leave machine-local `alpha: 1.0`
- leave `evidence_enabled: false`
- leave `recording_enabled` unchanged
- do not `deploy.py stop`, do not unload Qwen for handback, do not boot out
  launchd, do not delete facts, do not restore BGE

Writer release is not path release. Other tickets must not steal the live
daemon/socket/heavyweight slot without a new contract. Merge still does not
enable other machines.

## Stop

The #184 stop procedure is how to stop this path. It is **not** the #186
handback.

1. Set machine-local `alpha: 0.0` and keep `evidence_enabled: false`.
2. Leave `recording_enabled` unchanged (do not turn recording off).
3. Stop the scoring daemon so Qwen is unloaded (`deploy.py stop` and/or
   launchd bootout of `com.squirrel.llm-rerank`).
4. Do not restore BGE. Do not delete facts.
5. Confirm the tracked public example is still `alpha: 0.0`.

## Tests

```sh
python3 -m unittest discover -s daemon -p 'test_personal_lora_live*.py'
python3 -m unittest daemon.test_protocol daemon.test_scoring daemon.test_mlx \
  daemon.test_cli daemon.test_deploy
```
