# Candidate-Conditioned Representation

AC-109 keeps the accepted #69 v1 context-only benchmark unchanged and adds
exactly four Qwen3-0.6B-Base candidate-conditioned routes:

- L14 `candidate_span_mean`
- L21 `candidate_span_mean`
- L28 `candidate_span_mean`
- L28 `last_candidate_token` control

The serialized object is `last_64(preceding_text) + candidate`, with no
separator or special tokens. The candidate span is attributed by the existing
token decode/reconstruction seam. Empty preceding text is valid and an empty
candidate is a representation fault. The sequence is RMSNormed before pooling;
the selected span is then pooled and L2-normalized.

The evidence path creates one query vector for every current candidate. An
event's vector is compared only with the query vector for its selected
candidate, after the existing choice-problem hard partition. Evidence remains
positive-only, bounded, and exactly zero when no history qualifies. The fact
schema and live `alpha=0`, `gamma=0`, and evidence switches are unchanged.

`eval/candidate_conditioned_benchmark.py` is the model-free development
adapter. It consumes only the existing #69 v1 case fields and verifies the
four route identities and positive evidence plumbing. The v2 benchmark remains
deferred and is neither imported nor run by this delivery.
