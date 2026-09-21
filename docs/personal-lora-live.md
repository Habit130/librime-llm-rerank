# Personal LoRA live load (`mean-token-lm-v1`)

Squirrel#184: load the accepted #183 personal LoRA onto local Qwen3-0.6B-Base
in the existing scoring daemon, prove that `alpha=1.0` can change emission
order for one controlled same-span/same-category rerank group, then stop to
dictionary-only `alpha=0`. Ranking quality is not a Pass/Fail gate. Improved
training loss is not ranking benefit. Merge of this plugin PR does not enable
daily use.

This is not the BGE personal path (`docs/personal-bge-experiment-runtime.md`,
`docs/personal-experiment-activation.md`). Those documents stay valid. This
ticket does not restore BGE as the stop target. Historical #177/#178
`no_benefit` is not this live evidence.

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
schema key. Health may report `adapter_digest`. The public example stays
`alpha: 0.0`.

## Copy (owner-only)

Hash-verify the accepted #183 selected adapter, then copy into this
worktree's live root. Do not rewrite #182/#183 artifacts.

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

```sh
python3 daemon/deploy.py install
python3 daemon/deploy.py start \
  --model "$LLM_RERANK_MODEL" \
  --adapter .local-work/personal-lora-live
python3 daemon/deploy.py health
python3 daemon/deploy.py stop
```

`deploy.py render-plist` substitutes `__ADAPTER__` and sets
`LLM_RERANK_ADAPTER`. Isolated `verify` stays `--health-only` and does not
need an adapter.

At most one heavyweight model may be resident. Qwen+LoRA replaces BGE on
this path. `--health-only` is the BGE/model-free handshake; it does not load
Qwen.

## Live-switch (announced interval only)

Personal live YAML is machine-local (`~/Library/Rime`). Do not ship it. Do
not edit the tracked `data/luna_pinyin.custom.yaml` or the public contract
example.

During the interval only:

- `reranking_enabled: true`
- `alpha: 1.0`
- `sys_coeff: 1.0`, `usr_coeff: 1.0`
- `evidence_enabled: false`
- candidate `window: 32`, `deadline_ms: 200`
- recording stays enabled if it is already enabled

`alpha>0` is what opens the filter socket. Redeploy the schema after editing.
Enable only long enough to collect load, BGE-absence, order-change, and
fault-passthrough evidence. Public output is aggregate / identity /
order-changed-or-not. Controlled-group texts may be published only when they
are synthetic or ordinary dictionary strings.

Timeouts, unavailable model, and identity faults emit the entire original
window. Commit stays unblocked.

## Stop

Before handback:

1. Set machine-local `alpha: 0.0` and keep `evidence_enabled: false`.
2. Leave `recording_enabled` unchanged (do not turn recording off).
3. Stop the scoring daemon so Qwen is unloaded.
4. Do not restore BGE. Do not delete facts.
5. Confirm the tracked public example is still `alpha: 0.0`.

Daily re-enable is habit-only after independent Acceptance Pass.

## Tests

```sh
python3 -m unittest discover -s daemon -p 'test_personal_lora_live*.py'
python3 -m unittest daemon.test_protocol daemon.test_scoring daemon.test_mlx \
  daemon.test_cli daemon.test_deploy
```
