# Personal experiment activation (`personal-bge-experiment-v1`)

Squirrel#170 install, identity pin, isolated verification, and owner
enable/stop runbook. It consumes the frozen profile and the #168/#169
runtime. It is **not** a production `unique_lock`, not a +3pp Pass, and not
completion of #81–#84.

Do not enable live evidence in this ticket. Owner enable happens only after
independent Acceptance, by habit, using the commands below.

## Identities

Fill from the isolated record
`.local-work/ac170-activate/activation-identities.json` after real-BGE
verification. YAML-only edits without these identity checks fail closed.

| Field | Placeholder |
| --- | --- |
| Plugin head | `<ACTIVATED_PLUGIN_SHA>` |
| Squirrel pin (from-source tree) | `<ACTIVATED_SQUIRREL_SHA>` |
| Upstream BGE revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| Installed model digest | `<ACTIVATED_MODEL_DIGEST>` |
| Installed tokenizer digest | `<ACTIVATED_TOKENIZER_DIGEST>` |
| `representation_id` | `<ACTIVATED_REPRESENTATION_ID>` |
| `config_identity` | `<ACTIVATED_CONFIG_IDENTITY>` |
| Baseline policy | `mean-token-lm-v1` (`sys_coeff=1.0`, `usr_coeff=1.0`, `alpha=0`) |
| Retrieval backend | `exact` |
| Window / deadline | `32` / `200` ms |

`local_files_only=True`. Missing local BGE weights for that revision is an
environment blocker; do not download into a global install.

## Isolated runtime

```sh
python3 -m venv .local-work/ac170-activate/venv
.local-work/ac170-activate/venv/bin/python -m pip install \
  -r daemon/requirements-embeddings.txt
```

Disposable rime_dir, facts, and this venv belong under
`.local-work/ac170-activate/` (gitignored). Do not point `--facts-root` at
`~/Library/Application Support/Squirrel/SemanticMemory` for this ticket.

```sh
.local-work/ac170-activate/venv/bin/python daemon/server.py \
  --serve --health-only \
  --facts-root /absolute/isolated/facts \
  --evidence-config /absolute/isolated/evidence.json \
  --socket /absolute/isolated/llm-rerank.sock
```

`--health-only` keeps Qwen LM unloaded. Evidence config:

```json
{
  "provider_kind": "bge_m3",
  "bge_model_path": "/absolute/path/to/local/BGE-M3",
  "tau": 0.5,
  "k_evidence": 8,
  "half_life": 128,
  "saturation_k": 3.0,
  "gamma": 1.0,
  "retrieval_backend": "exact",
  "derived_root": "/absolute/isolated/derived"
}
```

From-source plugin install (allocated squirrel tree):

```sh
ln -sfn /absolute/plugin/worktree librime/plugins/llm-rerank
export BOOST_ROOT=/opt/homebrew/opt/boost
export MACOSX_DEPLOYMENT_TARGET=13.0
make librime
```

## Isolated verification

```sh
bash scripts/run-model-free-gates.sh python3
AC170_BGE_MODEL=/absolute/path/to/local/BGE-M3 \
  .local-work/ac170-activate/venv/bin/python \
  daemon/integration_personal_experiment_activation.py
ctest --test-dir librime/build -R '^llm_rerank_test$' --output-on-failure
```

Skipped-as-pass is forbidden for the real-BGE command. Quiet-machine timings
are fail-closed / resource notes, not permission to relax 200 ms or window 32.

## Apply vs computed

Daemon traces are **computed**. Client `traces/client_apply.jsonl` is the
display claim: `applied`, `fallback`, or `unknown` until ack. Production
`AppendClientApplyRecord` uses `FactStore::DefaultRootDir()` when the test
override is empty. Observation write failure does not change emission.

## Stop evidence without deleting facts

Set `llm_rerank/evidence_enabled: false`. Keep `recording_enabled: true`.
Do not clear facts. Derived rebuild on identity mismatch is not a fact
clear. Configuration faults pass the whole window through.

```sh
squirrel-semantic-memory annotate mispromotion --request-id <ID> [--event-id <ID>]
squirrel-semantic-memory status --json
```

## Owner live enable (after Acceptance only)

Execution and Acceptance must not apply this write. Live
`~/Library/Rime/luna_pinyin.custom.yaml` stays `evidence_enabled: false`
until habit runs:

```yaml
patch:
  llm_rerank/recording_enabled: true
  llm_rerank/reranking_enabled: true
  llm_rerank/evidence_enabled: true
  llm_rerank/alpha: 0.0
  llm_rerank/sys_coeff: 1.0
  llm_rerank/usr_coeff: 1.0
  llm_rerank/gamma: 1.0
  llm_rerank/saturate_k: 3.0
  llm_rerank/tau: 0.5
  llm_rerank/k_evidence: 8
  llm_rerank/half_life: 128
  llm_rerank/window: 32
  llm_rerank/deadline_ms: 200
  llm_rerank/baseline_policy_id: "mean-token-lm-v1"
  llm_rerank/representation_id: "<ACTIVATED_REPRESENTATION_ID>"
```

Redeploy the schema. Record the start boundary (identities only, no 上文):

```text
activated_at: <ISO-8601>
plugin_sha: <ACTIVATED_PLUGIN_SHA>
squirrel_sha: <ACTIVATED_SQUIRREL_SHA>
representation_id: <ACTIVATED_REPRESENTATION_ID>
config_identity: <ACTIVATED_CONFIG_IDENTITY>
model_digest: <ACTIVATED_MODEL_DIGEST>
tokenizer_digest: <ACTIVATED_TOKENIZER_DIGEST>
upstream_revision: 5617a9f61b028005a4858fdac845db406aefb181
```

## Owner live stop

```yaml
patch:
  llm_rerank/evidence_enabled: false
  llm_rerank/recording_enabled: true
```

Redeploy. Recording and canonical facts remain. This is not a fact clear
and not a unique_lock rollback of #81–#84.
