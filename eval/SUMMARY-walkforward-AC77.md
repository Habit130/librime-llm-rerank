# Walk-Forward Evaluation Summary (AC-77-v1)

- Issue: Habit130/squirrel#77
- Engine: hlc-walkforward-eval-v2
- Contract: AC-77-v1
- Snapshot SHA-256: `b1bfde41a9399a67409691f0de22dda7690a69ceb87edebcd3fe44059c87ba76`
- history_id: dc3ffbf1a21957e0bb4ceed535c9df56
- store_epoch: 8407bd6b456ba5c5a526b4b95951bac3
- HLC range: [1786806466751, 0] .. [1787065441087, 0]
- Freeze watermark (inclusive): 1786806466751/0
- Seed: 20260817
- Status continuity: `status_check=ok`, gap `none`, epoch unchanged, high-water non-decreasing
- Report package SHA-256: `2b002dab566d8756f924bd5371514034e7805e85f90e2e29ae8e3083cbbb85a1`
- Terminal outcome: **无合格方案** (RISK-77-1: #69 F1 eliminates all four representations from the exact quality shortlist)
- Lift claimable: False (#69 fixed-benchmark elimination, quoted F1)
- Live γ: 0.0 (not enabled)
- Selection: not_run

## Replay counts

| metric | value |
|---|---|
| replayable targets | 2116 |
| unrepresentable (empty 上文) | 20 |
| group-complete (size < 32) | 1449 |
| persisted competition_complete bit | 91 |
| actionable | 1584 |
| group-complete coverage | 68.48% |
| scheme-rank reconstructable | 2104 |

## Data state (reference replay, scheme-independent)

| gate | count | required (start gate) |
|---|---|---|
| group-complete replayable | 1449 | >= 1000 (Pass) |
| choice-problem keys | 451 | >= 100 (Pass) |
| actionable group-complete | 998 | report-only |
| actionable keys | 231 | report-only |
| explicit_indexed | 87 | report-only (< 200, not claimed) |
| confirmation rank >1 | 99 | report-only (< 200, not claimed) |

## τ calibration

- exact_l14_last / exact_l21_last / exact_l28_last / split_l28_last:
  all `not_calibratable` (108 hard-negative queries < 200 min) — no τ
  invented, τ-dependent cells eliminated.

## Grid (per representation)

| representation | cells | Δ₁ eliminated | τ-dependence skipped |
|---|---|---|---|
| exact_l14_last | 240 | 60 | 180 |
| exact_l21_last | 240 | 60 | 180 |
| exact_l28_last | 240 | 60 | 180 |
| split_l28_last | 240 | 60 | 180 |

Pre-declared grid manifest (written before metrics, α=0 per AC-106-v2):
H ∈ {8,32,128,512,∞}, K_evidence ∈ {8,16,32,64}, γ ∈ {0.5,1,2,4},
k ∈ {1,3,7}, τ ∈ {Q95,Q97.5,Q99,Q99.5} (only if calibratable).  No extra
cells, no continuous optimizer.

## #69 fixed-benchmark gate state (quoted, not re-adjudicated)

All four first-round representations fail both 95% gates at the benchmark
parameters (τ=0.90, K=8): positive 24/22/48/46% (need >=95%),
hard-negative no-evidence 39/42/30/30% (need >=95%).  Per AC-77-v1 seam 8
these representations **cannot enter the exact quality shortlist**; their
walk-forward still ran and is reported as a diagnostic (RISK-77-1).

## margin_base

```
{"available": false, "reason": "facts do not persist per-candidate base scores"}
```

## Rerun milestones (可作用组完整)

1500 / 2000 / 3000 / 5000, then every +2500.  Live `γ` stays 0 until a
qualifying rerun or a later explicit enablement decision.
