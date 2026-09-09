# Suffix Walk-Forward Report (AC-164-v1)

- Engine: suffix-walkforward-v2
- Code SHA: `972d4c41f5cedcca6b869bda604f6c510a01ee8e`
- Snapshot SHA-256: `111517b4548ad97cb73c801a3099076d70f90afc36bf94eb13f3fd1121cd94f5`
- Split cutoff HLC: `[1787667799562,0]`
- Prefix events: 4844 (sha256 `e50349a8630a9505c667569bde93c5bbfc9b1206d28c51d0ec5c80d96bb201a1`)
- Suffix events: 3901 (sha256 `9a7dd8b9444a397431a6c0212cfa2379dcfdac5f5a1cefc7150a1324cf3bb7a2`)
- Seed: 20260817 / replicates: 10000
- Terminal outcome: **收窄声称_shortlist**
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
    "replayable": 3901,
    "group_complete": 2694,
    "keys": 707,
    "explicit_indexed": 96,
    "rank_gt1": 98,
    "actionable_group_complete": 2370,
    "actionable_keys": 479,
    "coverage": 0.6905921558574725
  }
}
```

## Decision

```json
{
  "outcome": "收窄声称_shortlist",
  "reason": "eligible cells exist but the +3pp lift is not claimable on the suffix actionable group-complete sample of 2370 (need >= 1000); report the narrowed claim (收窄声称)",
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
      "replayable": 3901,
      "group_complete": 2694,
      "keys": 707,
      "explicit_indexed": 96,
      "rank_gt1": 98,
      "actionable_group_complete": 2370,
      "actionable_keys": 479,
      "coverage": 0.6905921558574725
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
        "hard_gates:pollution_point,pollution_ci": 180
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
        "hard_gates:pollution_point,pollution_ci": 180
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
      "eligible_cells": 180,
      "eliminated_by_reason": {
        "prefix_not_selected": 540,
        "eliminated:delta_one": 240
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
      "eligible": [
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 8,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 8,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 8,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 8,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 8,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 16,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 16,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 16,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 16,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 16,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 32,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 32,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 32,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 32,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 32,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 0.5,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 1,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 1.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 3,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 2.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 8,
          "k_evidence": 64,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 32,
          "k_evidence": 64,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 128,
          "k_evidence": 64,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": 512,
          "k_evidence": 64,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": {
            "pass": true,
            "evaluated": true,
            "union_events": 13,
            "top1_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mispromotion_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "majority_pollution_diff": [
              0.0,
              [
                0.0,
                0.0
              ]
            ]
          },
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        },
        {
          "route_id": "dedicated_bge_m3",
          "half_life": Infinity,
          "k_evidence": 64,
          "gamma": 4.0,
          "saturation_k": 7,
          "tau_quantile": "0.995",
          "tau": 0.9976091526745896,
          "prefix_metrics": {
            "actionable_group_complete": 17,
            "group_complete": 3326,
            "top1": 0.7647058823529411,
            "baseline_top1": 0.7647058823529411,
            "mrr": 0.8549019607843137
          },
          "metrics": {
            "top1": 1.0,
            "baseline_top1": 1.0,
            "mrr": 1.0,
            "mispromotion_rate": 0.0,
            "mispromotion_denominator": 13,
            "mispromotion_numerator": 0,
            "pollution": {
              "mean": 0.0,
              "p50": 0.0,
              "p95": 0.0,
              "positive_share": 0.0,
              "majority_share": 0.0,
              "count": 13
            },
            "majority_pollution_rate": 0.0,
            "actionable_group_complete": 13,
            "group_complete": 2694
          },
          "ci": {
            "top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "mrr_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_top1_vs_baseline": [
              0.0,
              [
                0.0,
                0.0
              ]
            ],
            "safety_mrr_vs_baseline": [
              -0.0014487369985141155,
              [
                -0.0023570831841508537,
                -0.0007078729281767956
              ]
            ],
            "mispromotion": [
              0.0,
              0.0
            ],
            "majority_pollution": [
              0.0,
              0.0
            ]
          },
          "hard_gates": {
            "pass": true,
            "evaluated": true,
            "unevaluated": [],
            "safety_top1_ok": true,
            "safety_mrr_ok": true,
            "mispromotion_point_ok": true,
            "mispromotion_ci_ok": true,
            "pollution_point_ok": true,
            "pollution_ci_ok": true
          },
          "finite_h_gate": null,
          "lift": {
            "claimable": false,
            "pass": null,
            "reason": "suffix actionable group-complete 13 < 1000: +3pp unclaimable"
          }
        }
      ]
    }
  ],
  "total_eligible_cells": 180,
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
| 8 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 8 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 32 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 128 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| 512 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |
| inf | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | fail | - |

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
      "replayable": 3901,
      "group_complete": 2694,
      "keys": 707,
      "explicit_indexed": 96,
      "rank_gt1": 98,
      "actionable_group_complete": 2370,
      "actionable_keys": 479,
      "coverage": 0.6905921558574725
    },
    "total": {
      "replayable": 8745,
      "group_complete": 6020,
      "keys": 1115,
      "explicit_indexed": 314,
      "rank_gt1": 332,
      "actionable_group_complete": 4907,
      "actionable_keys": 611,
      "coverage": 0.6883933676386507
    },
    "omissions": {
      "event_omitted": 0,
      "event_rows": 9116,
      "event_vectors": 9116,
      "query_omitted": 0,
      "query_rows": 9075,
      "query_vectors": 9075,
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
    "event_rows": 9116,
    "event_vectors": 9116,
    "query_omitted": 0,
    "query_rows": 9075,
    "query_vectors": 9075,
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
| 8 | 8 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 8 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 8 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 8 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 8 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 8 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 16 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 16 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 16 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 16 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 16 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 32 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 32 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 32 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 32 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 32 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 0.5 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 0.5 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 0.5 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 1.0 | 1 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 1.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 1.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 2.0 | 3 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 2.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 8 | 64 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 32 | 64 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 128 | 64 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| 512 | 64 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |
| inf | 64 | 4.0 | 7 | 0.995 | 0.9118 | 0.9559 | fail | - |

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
      "replayable": 3901,
      "group_complete": 2694,
      "keys": 707,
      "explicit_indexed": 96,
      "rank_gt1": 98,
      "actionable_group_complete": 2242,
      "actionable_keys": 466,
      "coverage": 0.6905921558574725
    },
    "total": {
      "replayable": 8745,
      "group_complete": 6020,
      "keys": 1115,
      "explicit_indexed": 314,
      "rank_gt1": 332,
      "actionable_group_complete": 4627,
      "actionable_keys": 596,
      "coverage": 0.6883933676386507
    },
    "omissions": {
      "event_omitted": 918,
      "event_rows": 9116,
      "event_vectors": 8198,
      "query_omitted": 858,
      "query_rows": 9075,
      "query_vectors": 8217,
      "reason_counts": {
        "boundary_straddled": 1776
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
    "event_omitted": 918,
    "event_rows": 9116,
    "event_vectors": 8198,
    "query_omitted": 858,
    "query_rows": 9075,
    "query_vectors": 8217,
    "reason_counts": {
      "boundary_straddled": 1776
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
| 8 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 8 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 16 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 32 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 0.5 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 0.5 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 0.5 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 1.0 | 1 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 1.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 1.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 2.0 | 3 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 2.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 8 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 32 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 128 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| 512 | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |
| inf | 64 | 4.0 | 7 | 0.995 | 1.0000 | 1.0000 | pass | - |

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
      "replayable": 3901,
      "group_complete": 2694,
      "keys": 707,
      "explicit_indexed": 96,
      "rank_gt1": 98,
      "actionable_group_complete": 2370,
      "actionable_keys": 479,
      "coverage": 0.6905921558574725
    },
    "total": {
      "replayable": 8745,
      "group_complete": 6020,
      "keys": 1115,
      "explicit_indexed": 314,
      "rank_gt1": 332,
      "actionable_group_complete": 4907,
      "actionable_keys": 611,
      "coverage": 0.6883933676386507
    },
    "omissions": {
      "event_omitted": 0,
      "event_rows": 9116,
      "event_vectors": 9116,
      "query_omitted": 0,
      "query_rows": 9075,
      "query_vectors": 9075,
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
    "event_rows": 9116,
    "event_vectors": 9116,
    "query_omitted": 0,
    "query_rows": 9075,
    "query_vectors": 9075,
    "reason_counts": {},
    "route_id": "dedicated_bge_m3"
  }
}
```

## Notes

- public-B accuracy (11953/14725) was never read into the selection or the terminal decision (AC-159-6)
- the personal 2x2 r was never read into the selection, tie-breaking or suffix-rank interpretation (AC-159-6)
- live gamma is unchanged at 0 (AC-159-7)
- AC-164 uses the preserved AC-162 snapshot only; a later live backup is refused (WF3000-1)
- Qwen3 reference-route entry census must reproduce 2537/2370/4907 and keys 421/479/611 (WF3000-3)
- public-B accuracy and the personal 2x2 r were never read into selection, tie-breaking or interpretation (WF3000-5)
- live alpha/gamma/evidence, facts, ANN and deployment are unchanged (WF3000-8)

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

Report SHA-256: `bcfbe8395a2670ca2df1a3965759473e12ba047eb57809a757338dfa4919b5ec`