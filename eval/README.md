# Evaluation & Calibration Tooling

This directory carries the canonical 120/402 eval fixture and the calibration
driver for the mean-token LM scoring policy (Habit130/squirrel#46).

## Public-layer source slices (Habit130/squirrel#153)

`public_layer_slicer.py` + `run_public_layer.py` freeze the first public-layer
original-text slices and true-homophone expansions. The committed artifacts
under `public_layer/` are raw material only: exact source substrings, lexicon
homophones, offsets, and a twice-reproducible manifest digest. This ticket
does **not** load a model, emit pairwise scores, pick a public winner, run the
personal 2×2, or change live `α`/`γ`.

The retired v1/v2 95% representation gates from #69 / #150 are demoted. They
are not applied to this corpus and do not gate #153. Later public-layer tickets
use the #150 pairwise rule (A-winner accuracy on B ≥ 70%), not those 95% gates.

```sh
python3 eval/run_public_layer.py
python3 -m unittest eval.test_public_layer
```

Sources are fetched by the frozen SHAs in the #153 table. The `luna_pinyin`
system lexicon is `rime/rime-luna-pinyin` + `rime/rime-essay` at the SHAs
recorded in the manifest (squirrel `fcda5e3f639478998e4de3693909fce91745309e`,
plum `b1be1969f914cc005add4090631b855db00c2591`). User dictionary and
`~/Library/Rime` are never read. Committed artifacts are `public_layer/manifest.json`,
`public_layer/slices.tsv`, and `public_layer/REPORT.md`.

## Public-layer A winner (Habit130/squirrel#154)

`public_layer_a.py` + `run_public_layer_a.py` run the three frozen routes on
every #153 A pair whose **target length is ≥ 2**. A only selects a
representation on that len≥2 set. Single-character pairs stay in the #153
corpus and are not scored. The public 70% pairwise gate is #156 on split B
with the same query and length rules. The retired v1/v2 95% gates stay
demoted and do not choose the A winner.

```sh
python3 eval/run_public_layer_a.py
python3 -m unittest eval.test_public_layer_a
```

A CPU pass writes a compact competitor table, then drops the slicer
lexicon. GPU scoring streams that table and must not load essay-DFS or
full `pinyin_to_words`. A scoring process that exceeds 8G physical
footprint stops.

Identity is frozen before any score: #153 digest, code SHA, the three
runtime fingerprints, pair-set rule `target_len>=2`, and query rule
`ctx-as-query:last64`. Pair = one eligible A slice × one lexicon
competitor. Query text is `last64(preceding)` via `window_text(..., 64)`.
Candidate text is `candidate_conditioned_payload(preceding, word)`. Hit iff
`cos(enc(query), enc(ctx+target)) > cos(enc(query), enc(ctx+homophone))`
(strict). Equal cosine is a miss. The three routes share that pair set. B
and len=1 are not scored. Committed outputs are `public_layer/a_freeze.json`,
`public_layer/a_report.json`, and `public_layer/A_REPORT.md`.

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

The script generates **every** committed artifact itself — run metrics,
per-case baseline candidate checksums (ordered + multiset), the decision
fields (`final_alpha`, `final_alpha_value`, `internal_optimum`,
`positive_alpha_qualified`, `final_alpha_rationale`), the manifest with its
canonical checksum, and the summary. Nothing is hand-edited afterwards.

```sh
# build the plugin first (Squirrel repo root):
#   export BOOST_ROOT=/opt/homebrew/opt/boost MACOSX_DEPLOYMENT_TARGET=13.0
#   make librime

eval/.venv/bin/python eval/calibrate.py \
    --console <squirrel>/librime/build/bin/rime_api_console \
    --template-dir <squirrel>/librime/build/bin
```

Requirements:

- `numpy>=2.0,<3` for the AC-111 projection trainer and model-free projection
  adapter tests;
- the matching `daemon/requirements.txt` numeric dependency for daemon
  projection tests;
- the daemon venv at `daemon/.venv` with mlx/mlx-lm and the model at
  `--model` (default `/Users/habit/Models/Qwen/Qwen3-0.6B-Base`);
- a quiet machine (latency-sensitive); total runtime is roughly 2 hours;
- isolated disposable `rime_dir`s; `~/Library/Rime` is never touched.

Outputs (all committed): `manifest.json` (identities, pre-declared grid,
decision fields, canonical checksum), `results.json` (metrics, per-case
ranks, baseline candidate checksums, distribution summary), `SUMMARY.md`.
`telemetry.jsonl` (daemon score/token-count telemetry) is regenerated and
gitignored.

### Artifact verifier (read-only)

```sh
eval/.venv/bin/python eval/verify_artifacts.py \
    --dict <librime>/build/bin/luna_pinyin.dict.yaml
```

Checks the committed fixture, the manifest checksum (canonical rule:
`sha256(canonical_json(manifest minus manifest_sha256))`), results<->manifest
consistency, metrics and harmful-regression counts recomputed from committed
`case_ranks` (both copied summaries and the decision must match those derived
values), the baseline candidate manifest (including that at least one case's
ordered checksum differs from its multiset checksum, i.e. the ordered hash
really captures emission order), and byte-for-byte summary regeneration. Must
pass on the committed artifacts.

## Model-free vs integration tests

- **Model-free gate** (clean Python, no transformers/MLX/model):
  `python3 -m unittest discover -s daemon -p 'test_*.py'` — protocol, fake
  tokenizer, fake logits, pure functions — plus
  `python3 -m unittest discover -s eval -p 'test_*.py'` — candidate-checksum
  contract. Both must pass without any model dependency.
- **Integration** (explicit opt-in, daemon venv; missing model or
  transformers fails with an explicit configuration error):
  `daemon/.venv/bin/python daemon/integration_tokenizer.py`,
  `daemon/integration_prefix_invariant.py`,
  `daemon/integration_cache_limit.py`, and an isolated daemon plus
  `daemon/integration_memory.py --socket <sock> --pid <pid>`.

## Candidate-conditioned benchmark v2 (AC-108-v1 / AC-112-v2)

`semantic_benchmark.py` is the unchanged #69 v1 development/regression set.
`semantic_benchmark_v2.py` adds exactly 50 new synthetic Simplified-Chinese
families and expands them into 100 positive and 100 hard-negative directions.
Its payload represents the query as the last 64 characters of 上文 plus one
candidate, and history as the historical last-64 上文 plus its selected
candidate. Choice problems remain hard partitions and hard-negative evidence
is never inferred from candidate identity alone.

The v2 manifest must be frozen before a report is accepted. Each route attempts
all 100 v1 hard-negative cases and calibrates its threshold from the finite
cosines by nearest-rank Q95; evidence uses strict `cosine > tau`. A
candidate-span or model-forward fault is recorded as an unreplayable stable
case ID, never as an invented vector or cosine. A route with fewer than 80
finite v1 hard-negative cosines writes a pre-claim refusal and does not start
the v2 shot. The seven route descriptor binds payload, model/instruction,
64-character window, pooling, vector format, dimensions, and metric. It and
the manifest digest are checked before metrics. The model-free fixture proves
exact top-K, strict equality, positive and no-evidence decisions, manifest
verification, and report identity without loading a model or producing v2
quality results:

```sh
python3 eval/semantic_benchmark_v2.py --fixture --artifact-dir <dir>
```

`--run-quality` is the AC-112 real runner. It binds the two AC-110 embedding
adapters, the four AC-109 Qwen pooling routes, and the AC-111 projection to the
frozen matrix before scoring. It uses one MLX process for Qwen/pooling/
projection and a separate sequential `.venv-embeddings` process for each
embedding model. It freezes all seven v1-only thresholds, K, payload,
instructions, model/tokenizer and dependency identities, projection identity,
code SHA, seed, and start time before it atomically claims the one permitted v2
attempt. The code worktree must be clean before calibration and remain on that
same commit until the freeze is written. The runner rechecks that snapshot
immediately before and after v2 forwards; a drift consumes the claim as a
contract failure rather than accepting a report with an ambiguous code SHA.

```sh
daemon/.venv/bin/python eval/semantic_benchmark_v2.py --run-quality \
  --artifact-dir .local-work/ac112/v2-quality \
  --model /Users/habit/Models/Qwen/Qwen3-0.6B-Base \
  --projection /Users/habit/Developer/librime-llm-rerank/.local-work/ac112/candidate-conditioned-linear.npz \
  --qwen3-embedding-model .local-work/models/Qwen3-Embedding-0.6B \
  --bge-m3-model .local-work/models/BGE-M3
```

The real artifact contains stable case IDs, failure axes, numeric evidence, and
identity hashes only. It never contains source text, candidate text, live facts,
or absolute paths. A v2 positive with an unreplayable request is a miss; a v2
hard-negative with one is no-evidence. Both denominators remain 100. A second
claim or acceptance fails. If either dedicated embedding directory is missing,
the command stops before threshold calibration, v2 metrics, or a quality
artifact; it must not publish a five-route judgment.

The only completed quality terminal states are `at_least_one_v2_pass` and
`seven_route_all_fail`. The latter is a valid one-shot result, keeps live
`gamma=0`, and does not authorize suffix evaluation, ANN, or #113 work. A
v2-pass route still does not enable live evidence: live `alpha=0`, `gamma=0`
remain unchanged until the separate #113 gate.

The AC-111 offline projection driver consumes only the confirmed prefix
snapshot. Its matrix and extracted features remain local;
`eval/SUMMARY-linear-projection-AC111.md` is the desensitized result.

```sh
daemon/.venv/bin/python eval/train_linear_projection.py \
  --snapshot <confirmed-prefix-snapshot> \
  --model /Users/habit/Models/Qwen/Qwen3-0.6B-Base \
  --output-dir .local-work/ac111 \
  --summary eval/SUMMARY-linear-projection-AC111.md
```

The driver refuses to write matrix artifacts outside `.local-work`.

## Strict-HLC walk-forward evaluation (Habit130/squirrel#70/#77)

`walkforward.py` + `metrics.py` / `bootstrap.py` / `calibration.py` /
`grid.py` / `shortlist.py` / `snapshot.py` / `report.py` implement the
frozen-fact walk-forward quality and safety evaluation on top of the #59
exact oracle and the #60 hidden-state representations. The driver is
`run_walkforward.py`:

```sh
# model-free fixture smoke (fast, no model):
python3 eval/run_walkforward.py --fixture --work-dir <dir>

# real-model diagnostic over a frozen snapshot (daemon venv; the live
# recorder is not disturbed, SCN-70-7):
daemon/.venv/bin/python eval/run_walkforward.py \
  --live-db <live facts.sqlite3> \
  --status-cli <daemon>/squirrel-semantic-memory \
  --work-dir <dir> \
  --model /Users/habit/Models/Qwen/Qwen3-0.6B-Base
```

Engine contract (AC-70-v1 + AC-77-v1; the decision record is embedded in
every report):

- **Strict HLC walk-forward**: every target event replays with `as_of` =
  its commit HLC and the whole commit excluded — score first, then add to
  memory; only facts committed at-or-before and active at the point are
  visible; retractions apply as-of and never backfill (SCN-70-1).
- **Group-complete denominator (AC-77-v1 seam 3, #76/#77 rewrite)**: an
  event enters the top-1 / MRR / mispromotion / safety / pollution /
  event-count gates iff its saved same-group competition size is `< 32`
  (`GROUP_COMPLETE_N`).  The persisted `competition_complete` bit is NOT
  the gate — it is reported as a diagnostic only (a size-32 event with
  bit=true is out; a size-10 event with bit=false is in).  Events that are
  not group-complete still provide positive historical evidence
  (SCN-70-2, rewritten).
- **Actionable / actionable union / coverage / strata** are computed per
  spec (SCN-70-3).  The #70 D7 selection-milestone gates are superseded
  by the #76 start gate (group-complete replayable >= 1000, keys >= 100);
  `explicit_indexed` / rank>1 / coverage / hard-neg / actionable are
  report-only strata, never start gates, never claimed when thin.
- **Bootstrap** is key-clustered with a fixed seed and >=10000 replicates,
  95% percentile CI, paired differences on the common actionable union
  (SCN-70-4).
- **Pre-declared grid** (representations x H x K x gamma x k), α frozen at
  0 (AC-106-v2), τ per representation only from the dev-prefix
  hard-negative protocol (>=200 queries, Q95/Q97.5/Q99/Q99.5); below 200
  the state is `not_calibratable` and no τ is invented; Δ₁ single-event
  boundary eliminates cells; finite-H gates compare each finite-H cell
  against its H=inf twin (SCN-70-5).  No continuous optimizer anywhere.
- **AC-77 hard gates** (spec #43, on the group-complete denominator):
  overall safety (top-1 CI lower >= -0.5pp, MRR CI lower >= -0.005),
  mispromotion (point <= 2%, CI upper <= 3%), majority pollution
  (point <= 5%, CI upper <= 7.5%), finite-H vs H=inf (top-1 lower >= -1pp,
  mispromotion/pollution upper <= +1pp), and the #69 fixed-benchmark
  elimination (quoted F1: a representation that failed the fixed benchmark
  cannot sit on the exact quality shortlist).
- **Terminal outcome** (`shortlist.py`, AC-77-v1 seam 11): exactly one of
  exact quality shortlist / 收窄声称 shortlist / 仅安全、涨幅未测准 /
  无合格方案.  `+3pp` is a claim condition, not a ticket-fail: it may be
  claimed only when the actionable group-complete sample (>= 1000) and the
  correction / explicit_indexed strata (>= 200) are sufficient; thin
  strata are reported, never claimed.  No ANN / production winner is
  picked here (#80).  When 无合格方案, live `γ` stays 0 and the report
  lists the next rerun milestones (可作用组完整 1500/2000/3000/5000,
  then +2500).
- **Report** is desensitized: code/model summaries, fingerprints, snapshot
  SHA-256, HLC range, inclusion/exclusion counts (including the
  group-complete size<32 count and the persisted bit count), coverage,
  strata, terminal outcome and the #69 fixed-benchmark gate state (quoted,
  not re-adjudicated); never raw preceding/candidate text (SCN-70-6).

Base-score reconstruction: the facts persist only the recorded competition
order and the confirmation position of the final selection, so the scheme
base proxy pins the selection at its recorded position and keeps the
remaining candidates in recorded order around it — γ=0 then reproduces the
shadow baseline exactly (fixture-tested); page>1 confirmations are
non-reconstructable and reported in the fidelity diagnostic. Real snapshots
report `margin_base unavailable` and enforce the Δ₁ <= 0.5 hard cap;
synthetic fixtures inject base scores and pin the full Δ₁ boundary in the
test suite.

## Policy reference

The scoring policies under calibration are defined in
`../docs/token-attribution.md`.

## Offline α recalibration from real selection events (Habit130/squirrel#106)

`recalibrate.py` + `primary_events.py` + `template_weights.py` +
`daemon_scoring.py` + `decide.py` + `control_denominator.py` +
`console_replay.py` + `recalib_report.py` + `run_recalibrate.py` implement
the offline α recalibration of the mean-token LM coefficient over frozen
real selection events (contract AC-106-v1):

- **Primary denominator**: freeze-inclusive (`hlc >= 1786806466751/0`),
  unretracted, **group-complete** (saved competition size `< 32`, NOT the
  persisted `competition_complete` bit — spec #43 / #76 rewrite) events from
  one consistent read-only facts snapshot (Online Backup API, SCN-106-1);
  上文 = the stored `preceding_text` (asserted `<= 64` chars; empty is a
  valid window, reported as a stratum, never a fault).
- **Scoring seam (D-A106-1)**: `score(c) = α·mean_token_lm(c|上文) + β·weight(c)`,
  γ=0.  The librime runtime dictionary weight is recovered from the template
  compiled table (`rime_table_decompiler` dump of the librime build tree's
  `luna_pinyin.table.bin`: `log(raw) - kS`, byte-verified against the
  plugin `WeightScorer` verbose logs); the LM score comes from the daemon
  `mean_token` protocol (same socket the plugin `LlmScorer` uses).  The
  saved competition set is pinned by construction — only the recorded
  candidates are ranked, never a regenerated set.  A saved candidate
  without a finite weight or LM score makes the whole event 无法重放
  (SCN-106-5), counted per reason.
- **Decision**: primary-only top-1, then MRR, then smaller α; α=0 in the
  selection domain; pre-declared grid `{0, 0.5, 1, 2, 3, 4, 5, 7, 10}` with
  the #46 extension rule `{14, 20}` applied only when the winner is the
  upper bound (SCN-106-11: an upper-bound winner after extension is not a
  calibrated internal optimum).  Control metrics never enter `decide_final`
  (SCN-106-6).  SCN-106-10: if the remaining primary set after 无法重放
  falls below 1000 events or 100 keys, no α* is declared and the driver
  hands back a specification blocker.
- **Control denominator**: the committed 120/402 fixture's word cases with
  in-sentence prefixes (`上文 = sentence[:source_start]`; empty-prefix cases
  dropped and counted), ranked inside the engine competition set for the
  pinyin in a disposable rime_dir (console + full template dict, the #46
  pattern); published as a separate table that never selects.
- **Report**: desensitized (event ids, HLCs, hashes, counts, ranks — never
  raw 上文/candidate text), versioned with a report SHA-256, snapshot
  SHA-256, HLC range, freeze watermark, inclusion/exclusion counts, per-α
  top-1/MRR/M1/M2, 无法重放 counts, the α=0 fidelity diagnostic (reconstructed
  α=0 top-1 vs observed confirmation), and the decision record.

```sh
# model-free gate:
python3 -m unittest eval.test_recalibrate

# full offline run (daemon venv; quiet machine for the real-model grid):
daemon/.venv/bin/python eval/run_recalibrate.py \
    --snapshot <snapshot.sqlite3> \
    --decompiled-table <luna_pinyin.table.decompiled.txt> \
    --daemon-socket <workdir>/sock/calib.sock \
    --work-dir <local report dir> \
    --console <librime>/build/bin/rime_api_console \
    --template-dir <librime>/build/bin
```

The decompiled table is produced read-only from the librime build tree:

```sh
<librime>/build/bin/rime_table_decompiler \
    <librime>/build/bin/luna_pinyin.table.bin luna_pinyin.table.decompiled.txt
```
