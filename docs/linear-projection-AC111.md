# AC-111-v2 Linear Projection

This document records the implementation contract for the offline projection
delivery. It does not enable live evidence or select a production parameter.

## Representation

The input is the ordered concatenation `L14 || L21 || L28` of the existing
AC-109 `candidate_span_mean` vectors. Each source is a 1024-dimensional,
FP32, L2-normalized Qwen vector, so the input is exactly 3072 dimensions. One
global matrix maps 3072 dimensions to 256 dimensions and the result is L2
normalized. There is no bias, MLP, per-choice parameter, extra layer, dynamic
dimension, or online update.

`daemon/linear_projection.py` owns matrix validation and the provider adapter.
`ProjectedCandidateRepresentationProvider` applies a locally loaded matrix
after the three AC-109 candidate-conditioned providers. Its representation id
is the projection fingerprint, not a production configuration id.

## Prefix Training

`eval/train_linear_projection.py` verifies the complete SHA-256 of the
confirmed prefix snapshot before opening it. The expected history id, store
epoch, maximum HLC, and retraction HLCs are also checked. A post-cutoff event
or retraction is a hard error; it is never silently filtered into an accepted
run.

Active events with complete choice-problem identity and a saved competition
containing the selected candidate are eligible. Retracted, malformed, and
unreplayable events are counted and excluded. Empty preceding text remains
eligible because the AC-109 candidate-conditioned payload is the candidate
itself in that case.

Events are ordered by `(HLC, event_id)` and split 80/20. Pairs never cross the
split. A positive pair has the same choice-problem key and the same recorded
`final_selection_text` field. A hard negative has the same key and a different
`final_selection_text` field. Saved competition membership is checked with the
existing simplified-NFC fact semantics, but it does not rewrite the pair label.
All valid pairs are enumerated first; each class is then capped at 1024 by
evenly spaced stable order, with no replacement.

Training is full-batch and class-balanced. The positive loss targets cosine 1;
the negative loss is a squared hinge above margin 0.20. The matrix has no bias,
uses learning rate 0.05 and L2 mean-weight-square regularization `1e-4`, and
starts from a NumPy generator seeded with `20260822`. Validation loss uses
patience 20 with `1e-8` minimum improvement and a maximum of 120 epochs. These
choices are encoded into the projection fingerprint before the weight digest
is accepted.

## Identity And Privacy

The projection fingerprint binds source representation ids, training-code
digest, prefix SHA-256, history id, store epoch, inclusive HLC cutoff, split,
sampling, loss, regularization, seed, stop rule, weight digest, dimensions,
vector format, and metric. The matrix is stored only in an ignored local NPZ
artifact below `.local-work`; the committed summary contains its digest and
fingerprint but not the matrix.

The training path does not import or run the v2 benchmark, does not open or
write live facts, does not take a snapshot, and does not modify alpha, gamma,
schema, ANN, production configuration, or C++.

## Local Adapter

The adapter is model-free when supplied with three fixture providers and a
locally created projection artifact. No projection weights are required in
Git. Real use remains an offline #69-v1 development path; live ranking remains
at `alpha=0` and `gamma=0` until a later contract explicitly enables it.
