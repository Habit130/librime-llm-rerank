# Personal LoRA completion dataset freeze (`personal-lora-completion-v1`)

This document is the authoritative description of the private completion
dataset produced for Squirrel#182 (contract AC-182-v1, parent spec #180).
It covers the dataset schema, training vs ranking eligibility, the
deterministic temporal split rule, the CLI, the private/public output
boundary, freeze verification and the frozen run's aggregate
qualification evidence.

This is a new dataset freeze identity for the replacement adapter. It
does not restore deleted #175 artifacts and does not treat historically
published #175 checksums as this freeze's identity. #176/#177/#178
consumed that earlier freeze; those artifacts are gone.

Data and evaluation tooling only: this delivery does not download or load
a model, train, change live behavior, or write to the live fact store.
The implementation is `eval/personal_lora_data.py`; synthetic tests are
`eval/test_personal_lora_data*.py`; the synthetic source builder is
`eval/personal_lora_fixture.py`.

## Dataset semantics

One eligible stored selection event becomes exactly one completion
example:

- `prompt` — the stored raw causal 上文 `preceding_text`, already the last
  at most 64 Unicode characters as recorded. Empty 上文 is a valid,
  counted stratum, never a fault.
- `completion` — the stored `final_selection_text`, the finally committed
  selected word.
- `loss` — `completion_only`: the loss-boundary intent exported for
  training. No tokenizer-dependent mask is validated or claimed here;
  token lengths are explicitly deferred until training (#183) pins a
  tokenizer.

Records are never concatenated into documents, later choices are never
used as preceding text, and no candidate-negative, synthetic response or
automatic EOS material is added. Each JSONL line also carries local
provenance (event/commit/session identity, HLC, span, group size,
ranking-eligibility flag, empty-context flag, character counts and
partition). Raw text and per-example fingerprints stay in the private
JSONL files only.

Separate splits are written so downstream training can consume only its
permitted partition:

```text
dataset/train.jsonl  dataset/validation.jsonl  dataset/test.jsonl
```

## Training eligibility

An event enters the training dataset when every rule below holds
(`audit.excluded_by_reason` / `audit.data_faults_by_reason` record each
exclusion):

- the commit is not present in the snapshot's `retractions` table
  (retraction resolved as of the snapshot, including immediate
  retraction);
- `confirmation_source` is one of `explicit_current`,
  `explicit_indexed`;
- the schema is `luna_pinyin`, the repository's Simplified-Chinese scope
  (other schemas are excluded as `not_supported_schema`);
- `category` is `word`;
- required fields (`event_id`, `commit_id`, `schema_id`,
  `canonical_segment_input`, `category`, `session_id`, `session_seq`,
  `span_start`, `span_end`, `display_rank`, `display_page`,
  `hlc_physical_ms`, `hlc_logical`) are present and non-empty;
- `final_selection_text` is non-empty (missing target is an exclusion);
- `preceding_text` is at most 64 Unicode characters (overlong stored
  context is a data fault, never silently truncated);
- the span is valid (`0 <= span_start < span_end`);
- the commit exists in `commits`.

Duplicate rules:

- one event identity yields one sample; a byte-identical duplicate row
  under one `event_id` collapses (the extra rows are counted as
  `duplicates_collapsed`);
- a duplicate capture (same `session_id` + `session_seq`, distinct
  `event_id`) with identical content collapses to the earliest record;
- a conflicting duplicate identity is a data fault and its rows are
  excluded, never repaired;
- distinct events with identical text are genuine repetitions and remain;
- an event with an incomplete competition is still a valid training
  example.

Reading order is `(hlc_physical_ms, hlc_logical, event_id)`. Retraction,
HLC ordering and the group-completeness convention mirror the existing
`eval/walkforward.py` semantics; simplified-NFC text matching reuses
`daemon/oracle.py`.

## Ranking-evaluation eligibility (independent)

Training admission never requires a complete competition. Ranking
eligibility is computed separately per sample and requires all of:

- saved same-group competition size `< 32` (the `#76`/`#77`
  group-complete convention), **not** the persisted
  `competition_complete` flag;
- target membership: the target's simplified-NFC text equals a saved
  candidate's simplified-NFC text;
- valid saved same-span/same-category candidate data: at least one saved
  candidate, distinct increasing merge order, no empty candidate text.

The historical 4907 retrieval-actionable count is not a training or
ranking admission threshold. No history/actionable/cosine minimum is
applied.

## Deterministic temporal freeze

- The stream is sorted by HLC and cut only between commit units, so an
  entire commit always stays in one partition. A commit that is not
  contiguous in HLC order is a data fault and blocks the freeze instead
  of silently splitting it.
- Candidate cuts are the ends of commit units. A cut is preferred at a
  session end (the HLC position after which a persisted `session_id` never
  appears again) when one is within `1%` of the target event position
  (`max(1, floor(N * 0.01))` events). Otherwise the nearest commit-unit
  boundary is used. Ties prefer the smaller absolute deviation, then the
  earlier position.
- Targets are event positions `round(0.8 * N)` and `round(0.9 * N)`; the
  achieved proportions, chosen positions, targets, boundary kinds,
  tolerance and per-part first/last HLC are recorded in the manifest.
- No random split, no commit split, no test-driven repartition. Later
  transformations inherit the source partition; train-side shuffling is
  legal.
- The manifest records per split: event/commit/session/key counts, empty
  context counts, ranking-eligible counts, Unicode-character length
  distributions (prompt and completion), file sha256/bytes/lines, and
  exact context+target and choice-key overlap with training.
- Sessions may span partitions when persisted sessions interleave; the
  count is reported.

## Artifacts and sealing

All private outputs live under the ticket-owned, gitignored root
`<worktree>/.local-work/personal-lora-data/` with owner-only permissions
(0700 directories, 0600 files):

```text
config.json
acquisition/state.json             attempt history + frozen identity
snapshot/facts-snapshot.sqlite3    the one successful Online Backup
dataset/{train,validation,test}.jsonl
dataset/manifest.json              aggregate-only frozen manifest
dataset/public-report.md           desensitized qualification report
```

Config keys: `source_db` and `artifact_root` (required); `status_cli`,
`status_timeout_seconds`, `expected_fact_schema_version` (optional).
Relative paths resolve against the repository root. Unknown keys and
invalid values fail closed. Writable paths that resolve into live
fact/Rime/app locations, outside this ticket-owned root, or through
symlink aliases are refused.

- The live source is opened read-only/query-only and only through the
  SQLite Online Backup API. No source mutation, maintenance, restart,
  userdb access or remote upload happens here.
- A recorded successful snapshot is verified by checksum and reused;
  retries after a failure create explicitly recorded failed attempts and
  never silently replace the successful frozen identity. Missing or
  tampered frozen artifacts are an error, not a reason to re-acquire.
- An existing `dataset/manifest.json` (successful freeze) makes the run
  refuse to overwrite or rebind; only `--verify-only` may touch it
  afterwards. A recovered older freeze in this root is also refused,
  never overwritten.
- The public report contains aggregate counts, choices, HLC boundaries
  and artifact checksums only: no raw text, token sequences, per-example
  fingerprints, event identifiers or absolute private paths.

## CLI

```sh
python3 eval/personal_lora_data.py --config .local-work/personal-lora-data/config.json
python3 eval/personal_lora_data.py --verify-only \
    --manifest .local-work/personal-lora-data/dataset/manifest.json
```

Exit status:

- `0` — run: `dataset_frozen`; or verify-only: verification PASS;
- `2` — run: `needs_owner_decision` (honest report over a legal but
  unusable dataset: data faults present, empty partitions, no evaluable
  validation/test groups, or a split approximation outside the recorded
  tolerance);
- `1` — error/blocker: source corruption or access failure, schema fault,
  isolation violation, tampered or unreproducible freeze.

Health observations are advisory and separate from source continuity.
Continuity comes from direct read-only pre/post metadata (store epoch,
history id, schema fingerprint, monotonic high-water). A missing or
timed-out status CLI is reported as health `unknown`, never as snapshot
corruption or as health success.

`--verify-only` checks the manifest schema/tool version, the snapshot
checksum, integrity, identity and foreign keys, every part file's
checksum/line count, owner-only permissions, and then **re-derives the
audit, split rule, complete split metadata, terminal decision and every
part byte from the frozen snapshot** so a tampered or non-reproducible
freeze fails without changing anything.

## Frozen run (2026-09-17, aggregate-only evidence)

- terminal: `dataset_frozen`; exit status `0`.
- created_at_utc: `2026-09-17T09:38:23Z`.
- snapshot sha256:
  `be2b09256dd2c24485ed618501fc06408b4441e1d14a8d86d2645797e82ae6de`
  (34,095,104 bytes, `integrity ok`, no foreign-key violations).
- schema fingerprint sha256:
  `778b624383a57a48b5d7caff573529023728d712d17920cb55c7af20ef655226`.
- identity: `store_epoch 8407bd6b456ba5c5a526b4b95951bac3`,
  `history_id dc3ffbf1a21957e0bb4ceed535c9df56`,
  `fact_schema_version 1`, `event_format_version 1`,
  high-water `[1789348852036, 0]`.
- acquisition attempts: 1 — attempt 1 succeeded (`reused=False`).
  Metadata continuity held across the successful acquisition
  (`store_epoch`, `history_id`, schema fingerprint and source path
  stable; high-water monotonic).
- health: `unknown` (no status CLI is configured for this run;
  continuity is from direct metadata, not from service health).
- rows 16792; training samples 15930; exclusions `retracted` 862;
  duplicate rows collapsed 0; data faults 0; empty-context samples 151;
  ranking-eligible samples 10926; ranking ineligibility
  `group_at_or_above_window` 5004.

| split | events | proportion | commits | sessions | keys | empty context | ranking eligible | sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 12675 | 79.57% | 12664 | 233 | 1712 | 131 | 8707 | `c66ff3adb7a30dc40c33f94de7d777eb9ab304820b0066433d806755c80d8dd2` |
| validation | 1657 | 10.40% | 1653 | 36 | 530 | 16 | 1121 | `80e58ebe0688bb28a083e723cb4d38c5386fa7856c0dc592d526e0f8bdeaa880` |
| test | 1598 | 10.03% | 1596 | 19 | 498 | 4 | 1098 | `12e973269edaa12fd56b54c644c05943dadf51d504ff519bdae38adc6a9f2d2b` |

- boundaries: chosen event positions `[12675, 14332]` (both session
  ends; targets `[12744, 14337]`, tolerance 159); train last HLC
  `[1788947195741, 0]` < validation `[1788947245534, 0] .. [1789114182621, 0]`
  < test `[1789114202810, 0] .. [1789348852036, 0]`.
- sessions spanning partitions: 5.
- overlap with training: validation 12/1657 exact context+target and
  1499/1657 choice keys; test 2/1598 exact and 1457/1598 keys.
- prompt Unicode-character lengths (min/p50/p90/p99/max):
  train `0/64/64/64/64`, validation `0/64/64/64/64`,
  test `0/64/64/64/64`; completion lengths: all splits `1/2/2/3/4`.
- tool: `personal_lora_data` version 1, script sha256
  `8d4a9ddaa5c46de4264c88c00180e4926afb7acb7d593538f857421339f2031d`.
- manifest sha256:
  `3c955756c7e109a8274f7796396c43208f178d4328670fe77d4c3141e3239b88`.
- The private manifest and public report are at
  `.local-work/personal-lora-data/dataset/manifest.json` and
  `.local-work/personal-lora-data/dataset/public-report.md`.

The snapshot and split-file sha256 values are byte-identical to the
numbers historically published for #175. That is a property of the live
store at acquisition time (it had not advanced), not a restoration of
#175 files and not this freeze's binding identity. The binding identity
is the new acquisition record, `created_at_utc`, manifest sha256 and
tool script sha256 above.

## Limitations

- The split is a static historical snapshot-as-of-retractions; later
  retractions require a new dataset/adapter version. This is not instant
  unlearning.
- Earlier project experiments, including #174/#175/#176/#177/#178, may
  have seen this historical period; the test partition is not claimed as
  an untouched project-wide prospective test. New post-freeze events
  belong to later prospective confirmation.
- Token lengths and the tokenizer-dependent loss mask are deferred to
  #183; the exported `loss` field is intent only.
- The 4907 historical retrieval-actionable count is not a training
  admission threshold, and nonzero counts are not a statistical adequacy
  claim.
- Persisted `session_id`s interleave; five sessions span partitions and
  are disclosed rather than hidden.

## Downstream sealing

- #183 consumes `dataset/train.jsonl` (and validation where that
  contract allows) only; training must not parse test outcomes.
- Any new snapshot produces a new freeze and a new adapter identity; the
  frozen files and their checksums are never edited or replaced.
- `--verify-only` is the read-only provenance gate for #183 and for
  independent Acceptance.
