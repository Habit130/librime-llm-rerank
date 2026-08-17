# Walk-Forward Evaluation Summary (AC-70-v1)

- Issue: Habit130/squirrel#70
- Engine: hlc-walkforward-eval-v1
- Contract: AC-70-v1
- Snapshot SHA-256: `229246b06bc9cbe057ab40182522ada857d257f280770024476679feff92a23f`
- history_id: dc3ffbf1a21957e0bb4ceed535c9df56
- store_epoch: 8407bd6b456ba5c5a526b4b95951bac3
- HLC range: [1786806466751, 0] .. [1786936305188, 0]
- Seed: 20260817
- Report package SHA-256: `e4b7fb85d27042e12e1b14b9c473b1941c779d79605fbcaf5390fce9cce164bf`
- Milestone: **diagnostic** (诊断报告,不选方案: actionable complete=31 (need >=1000), keys=4 (need >=100), explicit_indexed=0 (need >=200), rank>1=0 (need >=200) (τ not calibratable: 29 hard-negative queries < 200))
- Selection: not_run

## Model / tokenizer summary

```json
{
  "hidden_dim": 1024,
  "mlxlm_version": "0.31.3",
  "model_digest": "7f3b14fa146519f6",
  "tokenizer_digest": "6fd1f1efb6b89f98"
}
```

## Replay counts

| metric | value |
|---|---|
| replayable targets | 916 |
| unrepresentable (empty 上文) | 8 |
| complete-competition | 39 |
| actionable | 611 |
| complete-competition coverage | 4.26% |
| scheme-rank reconstructable | 911 |

### Strata (source / confirmation rank)

| stratum | count |
|---|---|
| explicit_current/1 | 586 |
| explicit_current/>1 | 2 |
| explicit_indexed/>1 | 23 |

## τ calibration

- exact_l14_last: `not_calibratable` (29 hard-negative queries < 200 min)
- exact_l21_last: `not_calibratable` (29 hard-negative queries < 200 min)
- exact_l28_last: `not_calibratable` (29 hard-negative queries < 200 min)
- split_l28_last: `not_calibratable` (29 hard-negative queries < 200 min)

## Grid (per representation)

| representation | cells | Δ₁ eliminated | τ-dependence skipped |
|---|---|---|---|
| exact_l14_last | 240 | 60 | 180 |
| exact_l21_last | 240 | 60 | 180 |
| exact_l28_last | 240 | 60 | 180 |
| split_l28_last | 240 | 60 | 180 |

## Milestone counts (scheme-independent reference replay)

| gate | count | required |
|---|---|---|
| actionable complete-competition | 31 | >=1000 |
| choice-problem keys | 4 | >=100 |
| explicit_indexed | 0 | >=200 |
| confirmation rank >1 | 0 | >=200 |

## #69 fixed-benchmark gate state (quoted, not re-adjudicated)

```
{
 "benchmark_params": {
  "half_life": "inf",
  "k_evidence": 8,
  "saturation_k": 1.0,
  "tau": 0.9
 },
 "decision": "owner decided to proceed with #70 as planned; this report quotes the state and does not re-adjudicate it",
 "gate_state": "all four first-round representations fail both 95% gates (best positive 48% exact_l28/split_l28; best negative no-evidence 42% exact_l21)",
 "gates": {
  "hard_negative": ">=95%",
  "positive": ">=95%"
 },
 "real_model_measurements": {
  "exact_l14": {
   "hard_negative_no_evidence": "39/100 (39%)",
   "positive": "24/100 (24%)"
  },
  "exact_l21": {
   "hard_negative_no_evidence": "42/100 (42%)",
   "positive": "22/100 (22%)"
  },
  "exact_l28": {
   "hard_negative_no_evidence": "30/100 (30%)",
   "positive": "48/100 (48%)"
  },
  "split_l28": {
   "hard_negative_no_evidence": "30/100 (30%)",
   "positive": "46/100 (46%)"
  }
 },
 "source": "Habit130/squirrel#69 AC-69-v1 acceptance record, finding F1"
}
```

## margin_base

```
{"available": false, "reason": "facts do not persist per-candidate base scores"}
```
