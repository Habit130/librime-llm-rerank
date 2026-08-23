# AC-112-v2 Seven-Route Quality Summary

## Terminal State

- Contract: `AC-112-v2`
- Run kind: `seven_route_v2_quality`
- Terminal state: `seven_route_all_fail`
- V2-pass routes: none
- One-shot state: claimed before v2 metrics; rerun refused
- Live gamma: `0`
- Selection and production enablement: `not_run`
- Code SHA: `8db65a36f33967b26ade2379fb2110cba99df621`
- Failed AC-112-v1 continuation metrics used: none

## Frozen Identity

| Field | Digest |
| --- | --- |
| Benchmark manifest | `4d2ed16b607f127c125f1d5c4cd2bfaced0ad9829550bf3788e637727429e01c` |
| Route matrix | `592f42dbd59a06e56f44f07a824ab7aec73758026db15ee058f62e656633b602` |
| Run freeze | `b8716f8bb90098457696e1daa4289a444bbdf7319dbcf117b4fa4e205e251409` |
| Accepted report | `e33a283d6befb26fff59540a21c5a92ce0ce8c63646cbec2cee127b9092ed18e` |

## Route Results

| Route | Finite v1 HN | Excluded v1 IDs | Tau | Positive qualified | HN no-evidence | V2 unreplayable | Gate |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| `dedicated_qwen3_embedding_0_6b` | 100 | none | 0.9363934825080772 | 0/100 (0.00) | 92/100 (0.92) | 0 | Fail |
| `dedicated_bge_m3` | 100 | none | 0.9608117199461162 | 0/100 (0.00) | 85/100 (0.85) | 0 | Fail |
| `qwen_l14_candidate_span_mean` | 98 | `hard_negative-negation-05-02`, `hard_negative-window-05-01` | 0.9879328074932006 | 0/100 (0.00) | 94/100 (0.94) | 0 | Fail |
| `qwen_l21_candidate_span_mean` | 98 | `hard_negative-negation-05-02`, `hard_negative-window-05-01` | 0.9901803300954283 | 0/100 (0.00) | 93/100 (0.93) | 0 | Fail |
| `qwen_l28_candidate_span_mean` | 98 | `hard_negative-negation-05-02`, `hard_negative-window-05-01` | 0.996643654579699 | 0/100 (0.00) | 93/100 (0.93) | 0 | Fail |
| `qwen_l28_last_candidate_token_control` | 98 | `hard_negative-negation-05-02`, `hard_negative-window-05-01` | 0.9920838944013405 | 0/100 (0.00) | 90/100 (0.90) | 0 | Fail |
| `qwen_global_l14_l21_l28_projection_3072_to_256` | 98 | `hard_negative-negation-05-02`, `hard_negative-window-05-01` | 0.9835883393828465 | 0/100 (0.00) | 94/100 (0.94) | 0 | Fail |

All seven routes used `K=8` and strict `cosine > tau`. The repair isolated the two v1 Qwen span faults without inventing vectors or cosines; all routes remained above the 80-finite-HN pre-claim minimum. No v2 request was unreplayable.

## Runtime Bindings

| Route | Runtime ID |
| --- | --- |
| `dedicated_qwen3_embedding_0_6b` | `dedicated-embedding-repr-v1:route=qwen3-embedding-0.6b:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=09f7f379c919ff068b2d943ae8eaaa1260a0b16ffb5d3c799c9e383b241b4b81:tokenizer=83454d38a40edd5660ddae6fc9c31429d8fcd1cd4cae8e894489a97fd463d0b5:adapter=qwen3:instruction=Represent the candidate-conditioned query for semantic retrieval.:pool=last-token:dim=1024:format=fp32-l2:metric=cosine:deps=torch@2.7.1,transformers@4.52.4,tokenizers@0.21.1,safetensors@0.5.3` |
| `dedicated_bge_m3` | `dedicated-embedding-repr-v1:route=bge-m3-dense-1024:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=b9d800590cbaf23471af0d0722870b0a6f8681dc09630ed12cd57db0a9c34b2d:tokenizer=ec113500465479de593e55e1972aee45f0932447604272792b5e98db0fb9a35a:adapter=bge-m3:instruction=none:pool=dense-mean:dim=1024:format=fp32-l2:metric=cosine:deps=torch@2.7.1,transformers@4.52.4,tokenizers@0.21.1,safetensors@0.5.3` |
| `qwen_l14_candidate_span_mean` | `candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=14:pool=candidate_span_mean:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine` |
| `qwen_l21_candidate_span_mean` | `candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=21:pool=candidate_span_mean:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine` |
| `qwen_l28_candidate_span_mean` | `candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=28:pool=candidate_span_mean:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine` |
| `qwen_l28_last_candidate_token_control` | `candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=28:pool=last_candidate_token:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine` |
| `qwen_global_l14_l21_l28_projection_3072_to_256` | `candidate-conditioned-linear-v1:cc64768fdc016285eff08a49340efe0351cd39e9b82f99566c6d2e4e72d1307b` |

## Artifact Hashes

| Artifact | SHA-256 |
| --- | --- |
| `semantic_benchmark_v2_manifest.json` | `9b5098fe55c3bfa8ce61618815421718a3079e137d543548231dd359ed086abb` |
| `semantic_benchmark_v2.frozen` | `5ee8d86aa90678333461a0eae6837df18ef1839116abfa7a722729c07ab52547` |
| `semantic_benchmark_v2_run_freeze.json` | `9a6f19b5cef4246c9afb2be92ef47fe7e5f7e7463bb96b95535bb35ea5b44a45` |
| `semantic_benchmark_v2.quality_started` | `0012090072ee65e433a110294de002eb1414cff4e7fb57a5062bcbd4b733c7e8` |
| `semantic_benchmark_v2_report.json` | `4040b6e1b14416124f73a91b52eb3268c80313298aeecaf53e079538e33c4c38` |
| `semantic_benchmark_v2.accepted` | `bc36bf781425c13e612e34b97a4dde6a5e27a32c89954c9cceb78a73d5d057a3` |

## Privacy And Scope

`verify_artifact_privacy` passed. The local raw artifact boundary remains ignored; this committed summary contains only IDs, aggregate metrics, runtime identities, and hashes. It contains no preceding text, candidate text, live paths, facts, vectors, or secrets. No live configuration, suffix evaluation, ANN, latency gate, or #113 work was started.
