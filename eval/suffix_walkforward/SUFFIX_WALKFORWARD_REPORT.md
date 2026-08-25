# Suffix Walk-Forward Report (AC-157-v1)

- Engine: suffix-walkforward-v1
- Code SHA: `8dc0dcf2764ee5475bc4b60f4c92ec8440b1ad25`
- Snapshot SHA-256: `aa39556a984ebf6b18c416b348882a1aa2c243f4d8853541d3177f1a0b2fb394`
- Split cutoff HLC: `[1787065441087,0]`
- Prefix events: 2136 (sha256 `db10ad16730dfeb2b62817e7d4310444b4175771e7c758437c7f36a3861c69c0`)
- Suffix events: 2708 (sha256 `e4589a676966bde5efee02f3e61b975655122ca20ff105c372cece39e5b398fd`)
- Seed: 20260817 / replicates: 10000
- Terminal outcome: **无合格方案**
- Live γ: 0.0

## τ calibration (prefix only)

```json
[
  {
    "route_id": "dedicated_qwen3_embedding_0_6b",
    "tau": {
      "state": "not_calibratable",
      "queries": 195,
      "min_queries": 200,
      "prefix_count": 2136
    }
  },
  {
    "route_id": "qwen_l28_candidate_span_mean",
    "tau": {
      "state": "not_calibratable",
      "queries": 195,
      "min_queries": 200,
      "prefix_count": 2136
    }
  },
  {
    "route_id": "dedicated_bge_m3",
    "tau": {
      "state": "not_calibratable",
      "queries": 195,
      "min_queries": 200,
      "prefix_count": 2136
    }
  }
]
```

## Data state

```json
{
  "prefix": {
    "replayable": 2136,
    "group_complete": 1468,
    "keys": 456,
    "explicit_indexed": 88,
    "rank_gt1": 101,
    "actionable_group_complete": 0,
    "actionable_keys": 0,
    "coverage": 0.6872659176029963,
    "actionable_note": "not scored: no route calibratable from the prefix (RISK-157-3)"
  },
  "suffix": {
    "replayable": 2708,
    "group_complete": 1858,
    "keys": 572,
    "explicit_indexed": 130,
    "rank_gt1": 133,
    "actionable_group_complete": 0,
    "actionable_keys": 0,
    "coverage": 0.6861152141802068,
    "actionable_note": "not scored: no route calibratable from the prefix (RISK-157-3)"
  }
}
```

## Decision

```json
{
  "outcome": "无合格方案",
  "reason": "all routes τ not_calibratable (prefix hard-negative queries 195 < 200); no τ is invented, no cell is evaluated and the suffix claim gates cannot run (RISK-157-3)",
  "data": {
    "prefix": {
      "replayable": 2136,
      "group_complete": 1468,
      "keys": 456,
      "explicit_indexed": 88,
      "rank_gt1": 101,
      "actionable_group_complete": 0,
      "actionable_keys": 0,
      "coverage": 0.6872659176029963,
      "actionable_note": "not scored: no route calibratable from the prefix (RISK-157-3)"
    },
    "suffix": {
      "replayable": 2708,
      "group_complete": 1858,
      "keys": 572,
      "explicit_indexed": 130,
      "rank_gt1": 133,
      "actionable_group_complete": 0,
      "actionable_keys": 0,
      "coverage": 0.6861152141802068,
      "actionable_note": "not scored: no route calibratable from the prefix (RISK-157-3)"
    }
  },
  "per_route": [
    {
      "route_id": "dedicated_qwen3_embedding_0_6b",
      "tau": {
        "state": "not_calibratable",
        "queries": 195,
        "min_queries": 200,
        "prefix_count": 2136
      },
      "cells": [
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_qwen3_embedding_0_6b",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        }
      ],
      "data": {
        "prefix": {},
        "suffix": {}
      },
      "selection": "not_run"
    },
    {
      "route_id": "qwen_l28_candidate_span_mean",
      "tau": {
        "state": "not_calibratable",
        "queries": 195,
        "min_queries": 200,
        "prefix_count": 2136
      },
      "cells": [
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "qwen_l28_candidate_span_mean",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        }
      ],
      "data": {
        "prefix": {},
        "suffix": {}
      },
      "selection": "not_run"
    },
    {
      "route_id": "dedicated_bge_m3",
      "tau": {
        "state": "not_calibratable",
        "queries": 195,
        "min_queries": 200,
        "prefix_count": 2136
      },
      "cells": [
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 8,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 16,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 32,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 0.5,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 1.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 2.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 1
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 3
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 8,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 32,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 128,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": 512,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        },
        {
          "cell": {
            "route_id": "dedicated_bge_m3",
            "half_life": Infinity,
            "k_evidence": 64,
            "gamma": 4.0,
            "saturation_k": 7
          },
          "eliminated": "tau_not_calibratable"
        }
      ],
      "data": {
        "prefix": {},
        "suffix": {}
      },
      "selection": "not_run"
    }
  ],
  "total_eligible_cells": 0,
  "any_evaluated": false,
  "live_gamma": 0.0
}
```

## Routes

### dedicated_qwen3_embedding_0_6b

```json
{
  "route_id": "dedicated_qwen3_embedding_0_6b",
  "tau": {
    "state": "not_calibratable",
    "queries": 195,
    "min_queries": 200,
    "prefix_count": 2136
  },
  "cells": [
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    }
  ],
  "data": {
    "prefix": {},
    "suffix": {}
  },
  "selection": "not_run"
}
```

### qwen_l28_candidate_span_mean

```json
{
  "route_id": "qwen_l28_candidate_span_mean",
  "tau": {
    "state": "not_calibratable",
    "queries": 195,
    "min_queries": 200,
    "prefix_count": 2136
  },
  "cells": [
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "qwen_l28_candidate_span_mean",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    }
  ],
  "data": {
    "prefix": {},
    "suffix": {}
  },
  "selection": "not_run"
}
```

### dedicated_bge_m3

```json
{
  "route_id": "dedicated_bge_m3",
  "tau": {
    "state": "not_calibratable",
    "queries": 195,
    "min_queries": 200,
    "prefix_count": 2136
  },
  "cells": [
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 8,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 16,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 32,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 0.5,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 1.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 2.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 1
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 3
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 8,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 32,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 128,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": 512,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    },
    {
      "cell": {
        "route_id": "dedicated_bge_m3",
        "half_life": Infinity,
        "k_evidence": 64,
        "gamma": 4.0,
        "saturation_k": 7
      },
      "eliminated": "tau_not_calibratable"
    }
  ],
  "data": {
    "prefix": {},
    "suffix": {}
  },
  "selection": "not_run"
}
```

## Notes

- public-B accuracy (11953/14725) was never read into the selection or the terminal decision (AC-157-5)
- the personal 2x2 r was never read into the selection, tie-breaking or suffix-rank interpretation (AC-157-5)
- live gamma is unchanged at 0 (AC-157-7)

## Decision record

- d1 split: the snapshot is the claim-time Online Backup copy; prefix = hlc <= [1787065441087,0] (inclusive), suffix = the claim set; selection uses the prefix only, claims use the suffix only (AC-157-2)
- d2 payload: last64(preceding)+candidate, no separator; the query side uses the frozen Qwen3-emb instruction only for dedicated_qwen3_embedding_0_6b; document/history side never applies an instruction (AC-157-1)
- d3 L28 pools the candidate token span [start, start+count) via candidate_span_mean; whole-payload pooling would be a contract failure (AC-157-1)
- d4 rank denominator: saved same-group competition size < 32 (group-complete), never the persisted competition_complete bit (issue #157 body)
- d5 τ: per route only from prefix query-level hard negatives, >= 200 queries, Q95/Q97.5/Q99/Q99.5; below 200 the route is not_calibratable and leaves the shortlist (AC-157-3)
- d6 grid: H {8,32,128,512,inf} x K {8,16,32,64} x gamma {0.5,1,2,4} x k {1,3,7}, alpha=0; no extra cells, no continuous optimizer (AC-157-3)
- d7 bootstrap: key-clustered (choice-problem key), fixed seed, >= 10000 replicates, 95% CI; differences paired per event (issue #157 body)
- d8 cross-route metrics use the common actionable union; an event without evidence for a route scores as that route's shadow baseline (issue #157 body)
- d9 Δ₁ = gamma/(1+k) <= min(0.5, P10(margin_base)) with margin_base from the prefix: real snapshots do not persist base scores, the engine records the reconstructed rank gap and enforces the hard cap
- d10 terminals: exact shortlist / 收窄声称 shortlist / 无合格方案 / 数据不足; ties are reported, never broken by model name; no ANN, no production winner (issue #157 body)

Report SHA-256: `11753c87f5bd625fa35fa61bf482d5d364d08cc26c51c8cab9966281274ab024`