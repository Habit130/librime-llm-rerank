# Suffix Walk-Forward Report (AC-159-v1)

- Engine: suffix-walkforward-v2
- Code SHA: `cfe9ea7356bed7b41597c935623191962ed3db2f`
- Snapshot SHA-256: `4aebca791976c520d749525e177e2c6769a999290e5d49a58001f5a99f4359e9`
- Split cutoff HLC: `[1787667799562,0]`
- Prefix events: 4844 (sha256 `c80eb2e34f80adbf5aabe2c472adc1d2d3987f916eed04c2484d0ab53443a864`)
- Suffix events: 22 (sha256 `cd27a8f54b1c223c60d8c4a1a1eadded291ebd72af762846b5c146f3c8103d0b`)
- Seed: 20260817 / replicates: 10000
- Terminal outcome: **数据不足**
- Live γ: 0.0

## τ calibration (prefix only)

```json
[
  {
    "route_id": "dedicated_qwen3_embedding_0_6b",
    "tau": {
      "queries": 760,
      "min_queries": 200,
      "prefix_count": 4844,
      "state": "calibratable",
      "quantiles": {
        "0.95": 0.9132000853193079,
        "0.975": 0.929093154233482,
        "0.99": 0.9446309828290896,
        "0.995": 0.9492329638740632
      }
    }
  },
  {
    "route_id": "qwen_l28_candidate_span_mean",
    "tau": {
      "queries": 736,
      "min_queries": 200,
      "prefix_count": 4844,
      "state": "calibratable",
      "quantiles": {
        "0.95": 0.9756521249990604,
        "0.975": 0.9844813294619092,
        "0.99": 0.9873768919492322,
        "0.995": 0.9904414502465095
      }
    }
  },
  {
    "route_id": "dedicated_bge_m3",
    "tau": {
      "queries": 760,
      "min_queries": 200,
      "prefix_count": 4844,
      "state": "calibratable",
      "quantiles": {
        "0.95": 0.9787688401385186,
        "0.975": 0.9883327802938267,
        "0.99": 0.994185752178467,
        "0.995": 0.9976091526745896
      }
    }
  }
]
```

## Data state

```json
{
  "prefix": {
    "replayable": 4844,
    "group_complete": 3326,
    "keys": 791,
    "explicit_indexed": 218,
    "rank_gt1": 234,
    "actionable_group_complete": 2537,
    "actionable_keys": 421,
    "coverage": 0.6866226259289843
  },
  "suffix": {
    "replayable": 22,
    "group_complete": 14,
    "keys": 10,
    "explicit_indexed": 0,
    "rank_gt1": 0,
    "actionable_group_complete": 13,
    "actionable_keys": 9,
    "coverage": 0.6363636363636364
  }
}
```

## Decision

```json
{
  "outcome": "数据不足",
  "reason": "suffix claim set holds 14 group-complete / 13 actionable group-complete events, but the claim gates could not be evaluated at the operating cell: every selected cell has an empty hard-gate or finite-H denominator (None CI)",
  "data": {
    "prefix": {
      "replayable": 4844,
      "group_complete": 3326,
      "keys": 791,
      "explicit_indexed": 218,
      "rank_gt1": 234,
      "actionable_group_complete": 2537,
      "actionable_keys": 421,
      "coverage": 0.6866226259289843
    },
    "suffix": {
      "replayable": 22,
      "group_complete": 14,
      "keys": 10,
      "explicit_indexed": 0,
      "rank_gt1": 0,
      "actionable_group_complete": 13,
      "actionable_keys": 9,
      "coverage": 0.6363636363636364
    }
  },
  "per_route": [
    {
      "route_id": "dedicated_qwen3_embedding_0_6b",
      "tau": {
        "queries": 760,
        "min_queries": 200,
        "prefix_count": 4844,
        "state": "calibratable",
        "quantiles": {
          "0.95": 0.9132000853193079,
          "0.975": 0.929093154233482,
          "0.99": 0.9446309828290896,
          "0.995": 0.9492329638740632
        }
      },
      "eligible_cells": 0,
      "eliminated_by_reason": {
        "prefix_not_selected": 540,
        "eliminated:delta_one": 240,
        "hard_gates:not_evaluated:mispromotion_ci,mispromotion_point,pollution_ci,pollution_point": 180
      },
      "evaluated_cells": 720,
      "selected_cells": 180,
      "selection": {
        "mode": "prefix_only",
        "reason": "max_prefix_top1_mrr_actionable",
        "selected_cells": 180,
        "selected_families": [
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          }
        ]
      },
      "eligible": []
    },
    {
      "route_id": "qwen_l28_candidate_span_mean",
      "tau": {
        "queries": 736,
        "min_queries": 200,
        "prefix_count": 4844,
        "state": "calibratable",
        "quantiles": {
          "0.95": 0.9756521249990604,
          "0.975": 0.9844813294619092,
          "0.99": 0.9873768919492322,
          "0.995": 0.9904414502465095
        }
      },
      "eligible_cells": 0,
      "eliminated_by_reason": {
        "prefix_not_selected": 540,
        "eliminated:delta_one": 240,
        "hard_gates:not_evaluated:mispromotion_ci,mispromotion_point,pollution_ci,pollution_point": 180
      },
      "evaluated_cells": 720,
      "selected_cells": 180,
      "selection": {
        "mode": "prefix_only",
        "reason": "max_prefix_top1_mrr_actionable",
        "selected_cells": 180,
        "selected_families": [
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          }
        ]
      },
      "eligible": []
    },
    {
      "route_id": "dedicated_bge_m3",
      "tau": {
        "queries": 760,
        "min_queries": 200,
        "prefix_count": 4844,
        "state": "calibratable",
        "quantiles": {
          "0.95": 0.9787688401385186,
          "0.975": 0.9883327802938267,
          "0.99": 0.994185752178467,
          "0.995": 0.9976091526745896
        }
      },
      "eligible_cells": 0,
      "eliminated_by_reason": {
        "prefix_not_selected": 540,
        "eliminated:delta_one": 240,
        "hard_gates:not_evaluated:mispromotion_ci,mispromotion_point,pollution_ci,pollution_point": 180
      },
      "evaluated_cells": 720,
      "selected_cells": 180,
      "selection": {
        "mode": "prefix_only",
        "reason": "max_prefix_top1_mrr_actionable",
        "selected_cells": 180,
        "selected_families": [
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          {
            "tau_quantile": "0.995",
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          }
        ]
      },
      "eligible": []
    }
  ],
  "total_eligible_cells": 0,
  "any_evaluated": true,
  "live_gamma": 0.0
}
```

## Routes

### dedicated_qwen3_embedding_0_6b

- τ: `calibratable` (queries 760 / prefix 4844)
- cells: 720 evaluated, delta_one=240

| H | K | γ | k | τq | top-1 | MRR | gates | lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |

```json
{
  "route_id": "dedicated_qwen3_embedding_0_6b",
  "tau": {
    "queries": 760,
    "min_queries": 200,
    "prefix_count": 4844,
    "state": "calibratable",
    "quantiles": {
      "0.95": 0.9132000853193079,
      "0.975": 0.929093154233482,
      "0.99": 0.9446309828290896,
      "0.995": 0.9492329638740632
    }
  },
  "data": {
    "prefix": {
      "replayable": 4844,
      "group_complete": 3326,
      "keys": 791,
      "explicit_indexed": 218,
      "rank_gt1": 234,
      "actionable_group_complete": 2537,
      "actionable_keys": 421,
      "coverage": 0.6866226259289843
    },
    "suffix": {
      "replayable": 22,
      "group_complete": 14,
      "keys": 10,
      "explicit_indexed": 0,
      "rank_gt1": 0,
      "actionable_group_complete": 13,
      "actionable_keys": 9,
      "coverage": 0.6363636363636364
    },
    "omissions": {
      "event_omitted": 0,
      "event_rows": 5096,
      "event_vectors": 5096,
      "query_omitted": 0,
      "query_rows": 4617,
      "query_vectors": 4617,
      "reason_counts": {},
      "route_id": "dedicated_qwen3_embedding_0_6b"
    }
  },
  "selection": {
    "mode": "prefix_only",
    "reason": "max_prefix_top1_mrr_actionable",
    "selected_cells": 180,
    "selected_families": [
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      }
    ]
  },
  "omissions": {
    "event_omitted": 0,
    "event_rows": 5096,
    "event_vectors": 5096,
    "query_omitted": 0,
    "query_rows": 4617,
    "query_vectors": 4617,
    "reason_counts": {},
    "route_id": "dedicated_qwen3_embedding_0_6b"
  }
}
```

### qwen_l28_candidate_span_mean

- τ: `calibratable` (queries 736 / prefix 4844)
- cells: 720 evaluated, delta_one=240

| H | K | γ | k | τq | top-1 | MRR | gates | lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |

```json
{
  "route_id": "qwen_l28_candidate_span_mean",
  "tau": {
    "queries": 736,
    "min_queries": 200,
    "prefix_count": 4844,
    "state": "calibratable",
    "quantiles": {
      "0.95": 0.9756521249990604,
      "0.975": 0.9844813294619092,
      "0.99": 0.9873768919492322,
      "0.995": 0.9904414502465095
    }
  },
  "data": {
    "prefix": {
      "replayable": 4844,
      "group_complete": 3326,
      "keys": 791,
      "explicit_indexed": 218,
      "rank_gt1": 234,
      "actionable_group_complete": 2385,
      "actionable_keys": 409,
      "coverage": 0.6866226259289843
    },
    "suffix": {
      "replayable": 22,
      "group_complete": 14,
      "keys": 10,
      "explicit_indexed": 0,
      "rank_gt1": 0,
      "actionable_group_complete": 12,
      "actionable_keys": 8,
      "coverage": 0.6363636363636364
    },
    "omissions": {
      "event_omitted": 516,
      "event_rows": 5096,
      "event_vectors": 4580,
      "query_omitted": 465,
      "query_rows": 4617,
      "query_vectors": 4152,
      "reason_counts": {
        "boundary_straddled": 981
      },
      "route_id": "qwen_l28_candidate_span_mean"
    }
  },
  "selection": {
    "mode": "prefix_only",
    "reason": "max_prefix_top1_mrr_actionable",
    "selected_cells": 180,
    "selected_families": [
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      }
    ]
  },
  "omissions": {
    "event_omitted": 516,
    "event_rows": 5096,
    "event_vectors": 4580,
    "query_omitted": 465,
    "query_rows": 4617,
    "query_vectors": 4152,
    "reason_counts": {
      "boundary_straddled": 981
    },
    "route_id": "qwen_l28_candidate_span_mean"
  }
}
```

### dedicated_bge_m3

- τ: `calibratable` (queries 760 / prefix 4844)
- cells: 720 evaluated, delta_one=240

| H | K | γ | k | τq | top-1 | MRR | gates | lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.95 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.95 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.975 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.975 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.99 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.99 | - | - | fail | - |
| 8 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 8 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 8 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 16 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 16 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 32 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 32 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 1 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 0.5 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 1 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 1.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 32 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 128 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 512 | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| inf | 64 | 2.0 | 3 | 0.995 | - | - | fail | - |
| 8 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 2.0 | 7 | 0.995 | - | - | fail | - |
| 8 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 32 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 128 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| 512 | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |
| inf | 64 | 4.0 | 7 | 0.995 | - | - | fail | - |

```json
{
  "route_id": "dedicated_bge_m3",
  "tau": {
    "queries": 760,
    "min_queries": 200,
    "prefix_count": 4844,
    "state": "calibratable",
    "quantiles": {
      "0.95": 0.9787688401385186,
      "0.975": 0.9883327802938267,
      "0.99": 0.994185752178467,
      "0.995": 0.9976091526745896
    }
  },
  "data": {
    "prefix": {
      "replayable": 4844,
      "group_complete": 3326,
      "keys": 791,
      "explicit_indexed": 218,
      "rank_gt1": 234,
      "actionable_group_complete": 2537,
      "actionable_keys": 421,
      "coverage": 0.6866226259289843
    },
    "suffix": {
      "replayable": 22,
      "group_complete": 14,
      "keys": 10,
      "explicit_indexed": 0,
      "rank_gt1": 0,
      "actionable_group_complete": 13,
      "actionable_keys": 9,
      "coverage": 0.6363636363636364
    },
    "omissions": {
      "event_omitted": 0,
      "event_rows": 5096,
      "event_vectors": 5096,
      "query_omitted": 0,
      "query_rows": 4617,
      "query_vectors": 4617,
      "reason_counts": {},
      "route_id": "dedicated_bge_m3"
    }
  },
  "selection": {
    "mode": "prefix_only",
    "reason": "max_prefix_top1_mrr_actionable",
    "selected_cells": 180,
    "selected_families": [
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      {
        "tau_quantile": "0.995",
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      }
    ]
  },
  "omissions": {
    "event_omitted": 0,
    "event_rows": 5096,
    "event_vectors": 5096,
    "query_omitted": 0,
    "query_rows": 4617,
    "query_vectors": 4617,
    "reason_counts": {},
    "route_id": "dedicated_bge_m3"
  }
}
```

## Notes

- public-B accuracy (11953/14725) was never read into the selection or the terminal decision (AC-159-6)
- the personal 2x2 r was never read into the selection, tie-breaking or suffix-rank interpretation (AC-159-6)
- live gamma is unchanged at 0 (AC-159-7)

## Decision record

- d1 split: the snapshot is the claim-time Online Backup copy; prefix = hlc <= [1787667799562,0] (inclusive), suffix = the claim set; selection uses the prefix only, claims use the suffix only (AC-159-2)
- d2 payload: last64(preceding)+candidate, no separator; the query side uses the frozen Qwen3-emb instruction only for dedicated_qwen3_embedding_0_6b; document/history side never applies an instruction (AC-159-1)
- d3 L28 pools the candidate token span [start, start+count) via candidate_span_mean; whole-payload pooling would be a contract failure (AC-159-1)
- d4 rank denominator: saved same-group competition size < 32 (group-complete), never the persisted competition_complete bit (issue #159 body)
- d5 τ: per route only from prefix query-level hard negatives, >= 200 queries, Q95/Q97.5/Q99/Q99.5; the #158 expected count is a facts-only contract invariant; after L28 omissions, only that route may be not_calibratable and leave the shortlist, while sibling routes continue (AC-159-4)
- d6 grid: H {8,32,128,512,inf} x K {8,16,32,64} x gamma {0.5,1,2,4} x k {1,3,7}, alpha=0; no extra cells, no continuous optimizer (AC-159-4)
- d7 bootstrap: key-clustered (choice-problem key), fixed seed, >= 10000 replicates, 95% CI; differences paired per event (issue #159 body)
- d8 cross-route metrics use the common actionable union; an event without evidence for a route scores as that route's shadow baseline (issue #159 body)
- d9 Δ₁ = gamma/(1+k) <= min(0.5, P10(margin_base)) with margin_base from the prefix: real snapshots do not persist base scores, the engine records the reconstructed rank gap and enforces the hard cap
- d10 prefix selection: per route, select the family with the best prefix top-1, then MRR, then actionable count; retain all H variants so suffix gates cannot influence selection
- d11 terminals: exact shortlist / 收窄声称 shortlist / 无合格方案 / 数据不足; ties are reported, never broken by model name; no ANN, no production winner (issue #159 body)

Report SHA-256: `3b3e5cf1d201e60e21b428722e04542d8250e78bf03f1f8700ab3bba75a98e10`