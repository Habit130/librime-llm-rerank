# Personal-layer 2x2 candidate contribution (AC-155-v1)

- contract: `AC-155-v1`
- code SHA: `0387dd7dcd15b477934999f905bb20ec9ea3b1bf`
- prefix pin hash: `b1bfde41a9399a67409691f0de22dda7690a69ceb87edebcd3fe44059c87ba76`
- snapshot SHA-256: `ce69b7292a92cf6a64c24c512d843250cfdd2a3c837c3772b277bae686709be7`
- HLC window: `[1786806466751,0] .. [1787065441087,0]`
- payload: `last64(preceding)+candidate` (all four 2x2 cells; none (Qwen3-emb query instruction not applied))
- routes: `dedicated_qwen3_embedding_0_6b, qwen_l28_candidate_span_mean`
- complete keys: 244 (threshold 30)
- incomplete: no_partner_window=256; no_replayable_base=0; no_replayable_payload=37
- terminal: `判定`

| route | median(key_d_cand) | median(key_d_ctx) | r | knife |
| --- | --- | --- | --- | --- |
| `dedicated_qwen3_embedding_0_6b` | 0.505763 | 0.237851 | 2.126382 | 候选信号不低于上文 |
| `qwen_l28_candidate_span_mean` | 0.147999 | 0.096821 | 1.528581 | 候选信号不低于上文 |

cross-route: **双有信号**

The personal 2x2 answers candidate contribution only: it does not calibrate the public gate, does not approve `gamma`, does not start #113, and public-layer B accuracy did not enter `r`.
