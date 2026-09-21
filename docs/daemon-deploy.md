# Phase-one daemon deploy

Source-install path for the Python inference daemon (Habit130/squirrel#131).
This is not a Squirrel.app package and does not redistribute model weights.

## What you need

- Python 3.10+ (3.11 recommended) to create `daemon/.venv`
- The pinned inference set in `daemon/requirements-daemon.txt`
- A local mlx-lm model directory for **scoring**. The repository does not
  ship one. Set `LLM_RERANK_MODEL` or pass `--model` to an on-disk checkout
  such as Qwen3-0.6B-Base. Isolated start/health/stop uses `--health-only`
  and a documented stand-in directory that is not a real model.
- Optional personal LoRA: `--adapter` or `LLM_RERANK_ADAPTER` points at a
  local adapter directory. Empty keeps base-only scoring. When set, the
  daemon fail-closes unless the Established #184 identities match. This is
  not a schema key. See `docs/personal-lora-live.md`.

## Install, start, health, stop

From the plugin checkout:

```sh
python3 daemon/deploy.py install
python3 daemon/deploy.py start --health-only
python3 daemon/deploy.py health
python3 daemon/deploy.py stop
```

`install` creates project-local `daemon/.venv` and installs the pinned
compatible versions. `start` without `--health-only` requires `--model` or
`LLM_RERANK_MODEL` and uses the venv interpreter.

Default runtime files stay under `daemon/.local-run/` (owner-only). They are
not `~/Library/Rime` and not the live Squirrel semantic-memory root. Override
any path:

```text
--checkout      plugin checkout root
--interpreter   python that runs server.py (default: daemon/.venv/bin/python)
--model         local mlx-lm model directory
--adapter       local LoRA adapter directory (optional; empty = base-only)
--socket        unix socket path
--log           stdout log
--log-err       stderr log
--facts-root    isolated facts root used by this process
--runtime-dir   parent for the default socket, logs, pid, and stand-in model
```

## launchd template

`daemon/com.squirrel.llm-rerank.plist` is a template. It contains no
machine-specific absolute paths. Render it after choosing explicit checkout,
interpreter, model, log, and socket paths:

```sh
python3 daemon/deploy.py render-plist \
  --checkout "$PWD" \
  --interpreter "$PWD/daemon/.venv/bin/python" \
  --model "$LLM_RERANK_MODEL" \
  --adapter "${LLM_RERANK_ADAPTER:-}" \
  --socket "$HOME/Library/Application Support/Squirrel/llm-rerank.sock" \
  --log /tmp/llm-rerank-daemon.log \
  --log-err /tmp/llm-rerank-daemon.err \
  --facts-root "$HOME/Library/Application Support/Squirrel/SemanticMemory" \
  --output /tmp/com.squirrel.llm-rerank.plist
```

Loading that plist with `launchctl` is optional and is not part of the
isolated verification path. Owner-authorized daily leave-on (Squirrel#186)
installs the phase-1 job with `RunAtLoad` / `KeepAlive`, the Established
model/adapter pins, lazy load, and `IDLE_TIMEOUT=300`; see
`docs/personal-lora-live.md`. Merge does not self-enable. Isolated
render/verify still refuse maintainer `/Users/habit` paths.

## Isolated verification

```sh
python3 daemon/deploy.py verify --skip-install
python3 daemon/deploy.py verify
```

Both commands copy `daemon/` into a temporary checkout, start a health-only
process, query the socket handshake, render the plist, and stop. The default
`verify` also creates a venv and installs `daemon/requirements-daemon.txt`.
`--skip-install` uses the current interpreter and is the model-free stand-in
path. Neither command writes `~/Library/Rime` or the live semantic-memory
root.
