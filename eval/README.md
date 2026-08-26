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
the **stride-8 subset** of every #153 A pair whose target length is ≥ 2:
starting from the full len≥2 v3 compact table, keep every 8th A slice in
file order (`index % 8 == 0`) and keep every competitor on a kept slice.
A only selects a representation on that stride filter. The step exists
because full len≥2 (425,528 pairs × 3 routes) is too slow on this machine.
The retired v1-v3 gates keep no official status; the v3 full-set Qwen3
score is diagnostic only and is not the A gate. The public 70% pairwise
gate is #156 on split B with the same query, length, and stride rules.
Single-character pairs stay in the #153 corpus and are not scored.

```sh
python3 eval/run_public_layer_a.py
python3 -m unittest eval.test_public_layer_a
```

A CPU pass writes the full len≥2 source table (v3 contract), then derives
the stride-8 compact table and drops the slicer lexicon. GPU scoring
streams that compact table and must not load essay-DFS or full
`pinyin_to_words`. One shot after freeze: do not tighten or loosen the
stride after seeing stride scores. A scoring process that exceeds 8G
physical footprint stops.

Identity is frozen before any score: #153 digest, code SHA, the three
runtime fingerprints, pair-set rule `target_len>=2;stride=8;index_mod=0`,
and query rule `ctx-as-query:last64`. Pair = one eligible A slice × one
lexicon competitor. Query text is `last64(preceding)` via
`window_text(..., 64)`. Candidate text is
`candidate_conditioned_payload(preceding, word)`. Hit iff
`cos(enc(query), enc(ctx+target)) > cos(enc(query), enc(ctx+homophone))`
(strict). Equal cosine is a miss. The three routes share that stride pair
set. B and len=1 are not scored. Committed outputs are
`public_layer/a_freeze.json`, `public_layer/a_report.json`, and
`public_layer/A_REPORT.md`.

## Public-layer B gate (Habit130/squirrel#156)

`public_layer_b.py` + `run_public_layer_b.py` score **only** the frozen A
winner `dedicated_bge_m3` on the **stride-8 subset** of every #153 B slice
whose target length is ≥ 2: same compact-table sorting and file-order
`i % 8 == 0` rule as A, all competitors kept, rebuilt from B slices
(`pair_set_rule target_len>=2;stride=8;index_mod=0;split=B`). BGE gets no
instruction on either side. A is never rescored and its winner is not
re-picked after B is seen.

```sh
python3 eval/run_public_layer_b.py
python3 -m unittest eval.test_public_layer_b
```

The B compact table is rebuilt from the B source table, never from the A
stride file. The build phase drops the slicer lexicon before any scoring;
the scoring process streams the compact table and must not load essay-DFS
or full `pinyin_to_words`. A scoring process that exceeds 8G physical
footprint stops.

The gate is the #150 public rule: `accuracy >= 0.70` on B → public winner
`dedicated_bge_m3`; below → `无公开赢家`. Both are legal terminals. It is
not the retired 95% τ, not a personal `r`, and a public winner here does
not enable `γ` or #113. #155 is not started by this ticket. Identity is
frozen before any score: #153 digest, A-winner fingerprint from the #154
freeze, this ticket's code SHA, and the B pair-set rule. Committed outputs
are `public_layer/b_freeze.json`, `public_layer/b_report.json`, and
`public_layer/B_REPORT.md`.

## Personal-layer 2x2 candidate contribution (Habit130/squirrel#155)

`personal_layer_2x2.py` + `run_personal_layer_2x2.py` run the frozen
complete-key 2x2 on the #77 pinned prefix snapshot with exactly two routes
(`dedicated_qwen3_embedding_0_6b`, `qwen_l28_candidate_span_mean`). Key =
`(schema_id, category, canonical_segment_input)`; base/partner follow the
frozen pair rule (earliest replayable base with an unselected real candidate,
earliest partner with a literally different last-64 window). Every complete
key contributes `key_d_cand = median(1-cos(ctx1,sel vs ctx1,u))` and
`key_d_ctx = 1-cos(ctx1,sel vs ctx2,sel)`; all four cells use the
`last64(preceding)+candidate` payload and the Qwen3-emb query instruction is
not applied. Route `r = median(key_d_cand) / median(key_d_ctx)` with the
frozen knife (`< 0.5` context-dominant, `>= 1` candidate signal,
`[0.5, 1)` grey, `median == 0` or no keys no conclusion); fewer than 30
complete keys stops the layer with **无结论**. Cross-route synthesis is one
of 双主导 / 双有信号 / 分裂 / 任一灰色, and grey after exhausting the prefix
keys stops.

The personal layer answers **candidate contribution only**: it cannot
calibrate the public gate (#156 B accuracy is never mixed into `r`), cannot
approve `gamma` (#113 stays parked), and is a different question from the
public-layer pairwise gate. Committed artifacts
(`eval/personal_layer/prefix_2x2_freeze.json`,
`eval/personal_layer/prefix_2x2_report.json`,
`eval/personal_layer/PX2X_REPORT.md`) carry key hashes, complete/incomplete
counts, per-route medians and `r`, the knife and the cross-route verdict
only — never preceding text, candidate text, machine paths or live facts.

```sh
python3 -m unittest eval.test_personal_layer_2x2
python3 eval/run_personal_layer_2x2.py
```

The runner byte-verifies the pinned #77 prefix snapshot (primary
`b1bfde41...` or the accepted AC-111 extract `ce69b729...`), copies it
read-only into `eval/.cache/personal_layer_2x2/`, and scores the two routes
with two isolated workers (`.local-work/venv-embeddings` for the embedding
route, `daemon/.venv` for the L28 route). Missing pins or models are
environment blockers that stop before any score.

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

## Candidate-conditioned suffix walk-forward (Habit130/squirrel#159, AC-159-v1)

`walkforward_cc.py` + `calibration_cc.py` + `grid_cc.py` + `shortlist_cc.py`
+ `suffix_report.py` + `run_suffix_walkforward.py` drive the exact
walk-forward for the three frozen candidate-conditioned routes
(`dedicated_qwen3_embedding_0_6b`, `qwen_l28_candidate_span_mean`,
`dedicated_bge_m3`) over a **claim-time** read-only Online-Backup snapshot
split at the frozen HLC cutoff `[1787667799562, 0]` (prefix inclusive).

The AC-159-v1 wiring onto the #77 seam:

- **Payload**: `last64(preceding)+candidate`, no separator (ADR-0003 /
  #109 / #110).  L28 pools the candidate token span `[start, start+count)`
  via `candidate_span_mean` (whole-payload pooling is a contract failure).
- **Query side**: Qwen3-emb uses the frozen instruction
  `Represent the candidate-conditioned query for semantic retrieval.` +
  newline + payload; BGE and L28 have none.  Document/history side: none.
- **Split**: prefix = `hlc <= [1787667799562, 0]` (τ calibration + grid
  selection); suffix = strictly later events, the claim set (quality and
  safety gates only).  Prefix selection chooses the family by prefix top-1,
  then MRR, then actionable count, retaining all H variants for the finite-H
  gate.  The replay memory still accumulates over the whole snapshot — suffix
  targets see prefix history (exact HLC-causal walk-forward).  Folding the
  suffix into development is a contract failure.
- **Snapshot**: a fresh Online Backup copy is taken at claim
  (`take_snapshot`); the #77/#155 prefix files are not a sufficient store.
  Missing snapshot -> environment blocker.  No suffix events past the
  cutoff -> **数据不足** (legal terminal).
- **τ**: per route only from prefix query-level hard negatives (>= 200
  queries, nearest-rank Q95/Q97.5/Q99/Q99.5); below that the route is
  `not_calibratable` and leaves the shortlist — no τ is invented.
  All three not_calibratable -> **无合格方案**.
- **Grid**: H {8,32,128,512,inf} x K {8,16,32,64} x gamma {0.5,1,2,4} x k
  {1,3,7}, alpha=0 (AC-106-v2); no extra cells, no continuous optimizer.
- **Denominator**: group-complete (saved competition size < 32); the
  persisted `competition_complete` bit is diagnostic only.  Shadow
  baseline: same events/set, alpha=0, gamma=0 (recorded confirmation
  position).
- **Suffix gates** (claim set; issue #159 body): Δ₁ <= min(0.5,
  P10(margin_base)) with margin_base from prefix baseline-correct events;
  finite-H vs H=inf on the common actionable union (top-1 CI lower >= -1pp,
  mispromotion upper <= +1pp, pollution upper <= +1pp; H=inf alone is never
  a stand-in); +3pp own-actionable lift only when the suffix actionable
  group-complete sample can support the claim (else **收窄声称** — never
  claim an unmeasured lift); overall safety (top-1 CI lower >= -0.5pp, MRR
  CI lower >= -0.005); mispromotion (point <= 2%, CI upper <= 3%);
  majority pollution (point <= 5%, CI upper <= 7.5%).  Bootstrap:
  key-clustered, fixed seed, >= 10000 replicates.
- **Terminals**: exact shortlist / 收窄声称 shortlist / 无合格方案 /
  数据不足.  Ties are reported, never broken by model name; no ANN, no
  production winner; public-B accuracy and the personal 2x2 r never enter
  the decision; live `alpha`/`gamma` unchanged.

```sh
# model-free gate (no model, no venv):
python3 -m unittest eval.test_suffix_walkforward

# one-shot real run (exclusive GPU/MLX; takes a fresh snapshot):
python3 eval/run_suffix_walkforward.py \
  --work-dir <local snapshot+report dir> \
  --artifact-dir eval/suffix_walkforward \
  --embedding-python <repo>/.local-work/venv-embeddings/bin/python \
  --daemon-python <repo>/daemon/.venv/bin/python

# reuse an existing claim-time snapshot for the rerun (identity must match):
python3 eval/run_suffix_walkforward.py \
  --snapshot <claim-time snapshot> --artifact-dir eval/suffix_walkforward ...
```

Committed artifacts (`eval/suffix_walkforward/`) carry the freeze
(contract, code SHA, snapshot/split hashes, route fingerprints, grid
manifest, seed) written **before** any score, plus the desensitized report
(counts, cell identities, CIs, gate states, terminal) and its SHA-256.
The vector cache and snapshot copies stay private under `.cache/` /
`.local-work/`; reports never contain preceding text, candidate text or
machine paths.
