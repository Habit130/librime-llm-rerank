# AC-111-v2 Linear Projection Summary

```json
{
  "contract": "AC-111-v2",
  "counts": {
    "active_events": 2136,
    "eligible_events": 1910,
    "empty_preceding": 20,
    "excluded_events": 358,
    "incomplete_identity": 0,
    "representation_unreplayable": 226,
    "retracted_events": 132,
    "snapshot_events": 2268,
    "snapshot_retractions": 132,
    "suffix_events": 0,
    "suffix_retractions": 0,
    "unreplayable_events": 226
  },
  "declarations": {
    "bias": "none",
    "loss": "class-balanced-cosine-positive-and-negative-margin-hinge",
    "regularization": "L2 mean weight square",
    "sampling": "all-valid-pairs-then-evenly-spaced-class-cap",
    "seed": 20260822,
    "split": "HLC event order, 80/20, no cross-split pairs",
    "stop": "validation loss patience 20, max 120 epochs"
  },
  "fit": {
    "fit": {
      "best_epoch": 120,
      "best_validation_loss": 0.10151128944414559,
      "epochs_run": 120,
      "stop_reason": "max_epochs",
      "train_loss": 0.06035821379718097,
      "validation_loss": 0.10151128944414559
    },
    "pairs": {
      "train_events": 1528,
      "train_pairs": 1229,
      "validation_events": 382,
      "validation_pairs": 1036
    },
    "weight_digest": "65516648791f3db8c53885b272ab913450e71b618bbaaa858e277231bc7364c5"
  },
  "isolation": {
    "alpha": 0,
    "gamma": 0,
    "live_facts_opened_or_written": false,
    "new_snapshot_taken": false,
    "suffix_events_read": 0,
    "v2_imported_or_run": false
  },
  "pairs": {
    "max_pairs_per_class": 1024,
    "split_fraction": 0.8,
    "split_index": 1528,
    "train": {
      "raw_hard_negative": 205,
      "raw_positive": 18450,
      "sampled_hard_negative": 205,
      "sampled_positive": 1024
    },
    "train_events": 1528,
    "validation": {
      "raw_hard_negative": 12,
      "raw_positive": 1035,
      "sampled_hard_negative": 12,
      "sampled_positive": 1024
    },
    "validation_events": 382
  },
  "privacy": {
    "candidate_text": "not committed",
    "projection_weights": "owner-local ignored artifact (path withheld)",
    "raw_preceding_text": "not committed",
    "vectors": "not committed"
  },
  "projection": {
    "fingerprint": "candidate-conditioned-linear-v1:252fe7d1bbe7e1a178dd3d01278afef6edd6b09ff58dc9a4ce77a6f224392e1a",
    "input_dim": 3072,
    "metric": "cosine",
    "output_dim": 256,
    "source_representation_ids": [
      "candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=14:pool=candidate_span_mean:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine",
      "candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=21:pool=candidate_span_mean:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine",
      "candidate-conditioned-repr-v1:payload=candidate-conditioned-concat-v1:serialization=last64-preceding-plus-candidate:no-separator:no-special:model=7f3b14fa146519f6:tokenizer=6fd1f1efb6b89f98:mlxlm=0.31.3:graph=1:layer=28:pool=candidate_span_mean:window=64:span=candidate-token-span-v1:norm=rmsnorm+l2:dim=1024:dtype=fp32:metric=cosine"
    ],
    "training_code_digest": "0f2699966ec3dfc2fffac82554ad75a80c7eb35fc50035e3ef83103746b1a61f",
    "vector_format": "fp32-l2",
    "weight_digest": "65516648791f3db8c53885b272ab913450e71b618bbaaa858e277231bc7364c5"
  },
  "snapshot": {
    "history_id": "dc3ffbf1a21957e0bb4ceed535c9df56",
    "hlc_cutoff": [
      1787065441087,
      0
    ],
    "path": "owner-local confirmed-prefix snapshot (path withheld)",
    "sha256": "ce69b7292a92cf6a64c24c512d843250cfdd2a3c837c3772b277bae686709be7",
    "store_epoch": "8407bd6b456ba5c5a526b4b95951bac3"
  }
}
```
