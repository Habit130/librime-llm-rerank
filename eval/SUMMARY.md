# Mean-Token Scoring Calibration Summary

- Issue: Habit130/squirrel#46
- Canonical fixture: Squirrel PR #24 head `b4ff9387ec65f6333e4c0ffb83cf8e78aab0f15b` (120 sentences, 402 word cases; corpus SHA-256 `a89a2bdfe41fbddb077aa5e7088a01616bb6d0240a5d04b3b3738dd94a145aae`)
- Fixture librime: `33e78140250125871856cdc5b42ddc6a5fcd3cd4` (1.17.0)
- Word manifest SHA-256: `9a7dac7704da766b4c1b6519c14d9c7a9d50675517339c7f0bf0c8eb61c5e2c3`
- Model/tokenizer: /Users/habit/Models/Qwen/Qwen3-0.6B-Base (files SHA-256 `2d1e90580a12714176ec47d2e25aa4a4318acdefc91365538f914c8e707ad183`)
- Random seed: 42 (pipeline is deterministic)
- Fixed coefficients: beta_sys=beta_usr=1, gamma=0, saturate_k=3, window=32; grammar data: not installed (PR #24 fixture environment)
- Alpha grid (pre-declared): [0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]
- Grid extension rule: if the best alpha sits on the grid's upper boundary, extend by [14.0, 20.0]; if still on the boundary, report that no internal optimum exists

## Word-level results (primary denominator: 402 word cases)

| run | policy | alpha | top-1 | top-5 | MRR | samples | not found | harmful regressions |
|---|---|---|---|---|---|---|---|
| baseline | mean-token-lm-v1 | 0.0 | 0.3134 (126/402) | 0.7861 | 0.5130 | 402 | 0 | 0 |
| legacy_sum_alpha_2.0 | first-stage-base-v1 | 2.0 | 0.3134 (126/402) | 0.7861 | 0.5132 | 402 | 0 | 0 |
| mean_alpha_0.5 | mean-token-lm-v1 | 0.5 | 0.2960 (119/402) | 0.7687 | 0.4951 | 402 | 0 | 10 |
| mean_alpha_1.0 | mean-token-lm-v1 | 1.0 | 0.2687 (108/402) | 0.7488 | 0.4720 | 402 | 0 | 20 |
| mean_alpha_2.0 | mean-token-lm-v1 | 2.0 | 0.2488 (100/402) | 0.7239 | 0.4516 | 402 | 0 | 26 |
| mean_alpha_3.0 | mean-token-lm-v1 | 3.0 | 0.2413 (97/402) | 0.7189 | 0.4434 | 402 | 0 | 29 |
| mean_alpha_4.0 | mean-token-lm-v1 | 4.0 | 0.2388 (96/402) | 0.7139 | 0.4406 | 402 | 0 | 30 |
| mean_alpha_5.0 | mean-token-lm-v1 | 5.0 | 0.2363 (95/402) | 0.7090 | 0.4374 | 402 | 0 | 31 |
| mean_alpha_7.0 | mean-token-lm-v1 | 7.0 | 0.2338 (94/402) | 0.7065 | 0.4353 | 402 | 0 | 32 |
| mean_alpha_10.0 | mean-token-lm-v1 | 10.0 | 0.2338 (94/402) | 0.7040 | 0.4341 | 402 | 0 | 32 |

## Sentence-level results (guard only, not a denominator)

| run | policy | alpha | top-1 |
|---|---|---|---|
| baseline | mean-token-lm-v1 | 0.0 | 0.5833 |
| legacy_sum_alpha_2.0 | first-stage-base-v1 | 2.0 | 0.5833 |
| mean_alpha_0.5 | mean-token-lm-v1 | 0.5 | 0.5833 |
| mean_alpha_1.0 | mean-token-lm-v1 | 1.0 | 0.5833 |
| mean_alpha_2.0 | mean-token-lm-v1 | 2.0 | 0.5833 |
| mean_alpha_3.0 | mean-token-lm-v1 | 3.0 | 0.5833 |
| mean_alpha_4.0 | mean-token-lm-v1 | 4.0 | 0.5833 |
| mean_alpha_5.0 | mean-token-lm-v1 | 5.0 | 0.5833 |
| mean_alpha_7.0 | mean-token-lm-v1 | 7.0 | 0.5833 |
| mean_alpha_10.0 | mean-token-lm-v1 | 10.0 | 0.5833 |

## Final alpha

- **final mean-token alpha = 0.5** (run `mean_alpha_0.5`); word top-1 0.2960, MRR 0.4951
- **No internal optimum exists in the pre-declared grid**: word top-1
  degrades monotonically as alpha grows, and the best grid point sits on the
  lower boundary (the pre-declared extension rule covers the upper boundary
  only). 0.5 is the least-harmful in-grid value, selected as a documented
  boundary choice; a future contextual fixture must re-calibrate.
- Baseline (no LM term): top-1 0.3134, MRR 0.5130
- Old sum policy alpha=2.0: top-1 0.3134, MRR 0.5132
- Delta vs baseline: top-1 -0.0174; vs old policy: -0.0174
- Harmful regressions at final alpha: 10 cases whose expected word dropped from rank 1
- Historical 78-case numbers are background only and are NOT a paired baseline (different denominator).
