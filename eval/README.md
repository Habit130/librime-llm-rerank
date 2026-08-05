# Evaluation & Calibration Tooling

This directory carries the canonical 120/402 eval fixture and the calibration
driver for the mean-token LM scoring policy (Habit130/squirrel#46).

## Canonical fixture

The fixture is reproduced from Squirrel PR #24 (head commit
`b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b`):

- `corpus/sentences.txt` — 120 simplified-Chinese sentences. SHA-256:
  `a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae`
- `fixture.json` — the committed, generated fixture: 120 sentence cases and
  402 standalone word cases (deduplicated by word text, sorted), each with
  its pinyin and provenance. The word manifest SHA-256 is
  `9a7dac7704da766b4c1b6519c14d9c7a9d50675517339c7f0bf0c8eb61c5e2c3`.
- Context protocol: standalone word, preceding text empty.

Generation requires `pypinyin==0.55.0` (see `requirements.txt`) and the
fixture librime's `luna_pinyin.dict.yaml` (librime commit
`33e78140250125871856cdc5b42ddc6a5fcd3cd4`, i.e. the `librime/build/bin`
template of that build).

### Regenerate / verify

```sh
python3 -m venv eval/.venv
eval/.venv/bin/pip install -r eval/requirements.txt

# regenerate fixture.json from corpus + dict:
eval/.venv/bin/python eval/derive_cases.py --dict <librime>/build/bin/luna_pinyin.dict.yaml

# re-verify the committed fixture.json (fresh-checkout re-verification):
eval/.venv/bin/python eval/verify_fixture.py --dict <librime>/build/bin/luna_pinyin.dict.yaml
```

## Calibration

`calibrate.py` reproduces the fixture environment with the `llm_rerank`
filter enabled and sweeps `alpha` over the pre-declared grid
`[0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]` (boundary extension rule:
`[14.0, 20.0]`), reporting the legacy sum policy at `alpha=2.0` and the
mean-token sweep on the full 402-case word denominator, with the 120
sentence cases as a separate guard.

```sh
# build the plugin first (Squirrel repo root):
#   export BOOST_ROOT=/opt/homebrew/opt/boost MACOSX_DEPLOYMENT_TARGET=13.0
#   make librime

eval/.venv/bin/python eval/calibrate.py \
    --console <squirrel>/librime/build/bin/rime_api_console \
    --template-dir <squirrel>/librime/build/bin
```

Requirements:

- the daemon venv at `daemon/.venv` with mlx/mlx-lm and the model at
  `--model` (default `/Users/habit/Models/Qwen/Qwen3-0.6B-Base`);
- a quiet machine (latency-sensitive); total runtime is roughly 2 hours;
- isolated disposable `rime_dir`s; `~/Library/Rime` is never touched.

Outputs (committed): `manifest.json` (identities, pre-declared grid, final
alpha), `results.json` (stable machine-readable metrics, per-case ranks,
distributions), `SUMMARY.md` (short summary), `telemetry.jsonl` (daemon
score/token-count telemetry; regenerated, not committed).

## Policy reference

The scoring policies under calibration are defined in
`../docs/token-attribution.md`.
