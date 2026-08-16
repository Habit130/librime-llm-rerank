# Persistent delta state machine (Squirrel#63) — decision record

Delivery contract: AC-63-v1. The machine is `daemon/delta.py`; its model-free
suite is `daemon/test_delta.py`; the real-model integration is
`daemon/integration_delta.py`.

## What it is

On top of one verified immutable base generation (#62), a single catch-up
worker absorbs newly committed selection events and whole-commit retractions
from the fact store in fact-transaction order, durably advances one
`delta.sqlite3` checkpoint, and atomically publishes a new read-only query
snapshot. Every evidence query first reads the facts' identity
(`store_epoch` + max change HLC), then succeeds only once the published
snapshot covers that watermark — a snapshot behind the watermark is a true
fault (`not_caught_up`), never a stale success (spec #43 "持久 delta 与立即可
见性").

## Delta schema (`<derived_root>/delta.sqlite3`)

```sql
meta            delta_schema_version, base_generation_id, store_epoch,
                representation_id, vector_dimension, base HLC (H0),
                consumed change HLC, change_seq, optional blocked record
delta_events    event_id PK, commit_id, schema_id, canonical_segment_input,
                category, final_selection_text, hlc, vector BLOB (FP32
                row-major little-endian), change_seq UNIQUE
retractions     commit_id PK, retraction HLC, change_seq UNIQUE
```

- WAL journal + `synchronous=FULL`. `journal_mode` is durable in the file
  header and is set exactly once, at checkpoint creation; later connections
  only verify it. `synchronous` is connection-local, so FULL is re-applied
  on every checkpoint connection (verified by test). Re-setting
  `journal_mode` per connection would acquire the write lock every time and
  make maintenance connections collide with the worker's write lock
  (AC-63-v1 repair; see "Connection classes" below).
- `change_seq` is one global counter advanced inside the batch transaction;
  it preserves the fact store's total order across both tables.
- The raw `preceding_text` is never stored — facts stay the only raw-text
  source (mirrors #62).
- The checkpoint is a fast-recovery cache, never a second fact source: it is
  loaded only after `quick_check`, pragma, compatible-identity
  (schema version, base generation id, store epoch, representation id,
  dimension, H0), per-row vector (dimension/finite/unit norm) and
  change-sequence verification, plus the strongest check — the projected
  active event set must equal the facts' active set at the consumed
  watermark. Any doubt drops the checkpoint and replays from `H0`
  (SCN-63-6). A same-epoch HLC regression (consumed beyond facts max) is
  treated as corruption and dropped.

## Worker and snapshot publish ordering

- One worker thread is the only writer of the checkpoint and the only
  publisher of snapshots; requests never write (SCN-63-8).
- A batch: read facts changes in `(consumed, W]` inside one read-only
  transaction whose identity is re-checked before commit; embed vectors
  (slow, outside the transaction); then ONE durable transaction inserts the
  surviving event rows + tombstones in fact order, advances the consumed HLC
  and the change sequence; only after COMMIT is the new in-memory snapshot
  built from the committed mirror and published under the machine condition
  (AC63-3/4).
- Events whose whole commit is retracted inside the same batch are never
  embedded and never recorded (their tombstone filters them from the
  projection anyway; the projected active set is identical — evidence
  equivalence). Events consumed earlier but retracted later keep their rows
  (append-only, like facts) and are filtered by the tombstone.
- If publishing fails after a commit, the next cycle resumes from the
  checkpoint's committed watermark (never re-embeds) and re-publishes.
- A retraction exits both the evidence set and the age clock in the same
  published snapshot, because both are derived from the same active
  projection (SCN-63-2).

## Query gate and deadline semantics (AC63-1/6)

`ensure_caught_up(deadline)` re-reads `store_epoch` + max change HLC from the
facts on every call — notifications are only a wake optimization; a lost
notification or restart never loses events. It returns the snapshot only
when epoch matches and consumed ≥ facts max. Otherwise it wakes the worker
and waits; on deadline expiry it raises `not_caught_up` (transient,
`retryable: true` in the server response) — never a stale-watermark success.
A deterministic block (representation/parse fault naming the event) raises
`representation_fault` and is recorded in the checkpoint until `retry()`
(spec: 确定性失败保持 blocked). While blocked the worker parks: catch-up
stays halted (no repeated embedding of the failing batch, no repeated
diagnosis writes) until `retry()` or a rebuild clears the block — which
also keeps the checkpoint free of concurrent writers during the maintenance
`retry()` path. The block is persisted BEFORE it is published to waiting
requests, and `retry()` deletes the diagnosis record BEFORE clearing the
block and waking the worker, so the two can never race on the checkpoint
write lock. The worker keeps working after a request deadline; a later
request can succeed on the same snapshot.

## Connection classes

`_connect_delta(path, busy_timeout)` distinguishes two locking behaviors
(AC-63-v1 repair):

- **Writer and maintenance connections** (schema creation, the batch
  transaction, the blocked-record write, `retry()`): `busy_timeout = 5 s`.
  They wait for a concurrent lock holder — the worker's own transactions
  are milliseconds, so a maintenance path that fails instead of waiting
  (e.g. `retry()` racing the worker's write) is a spurious fault.
- **Read/verify connections** (load-time checkpoint verification in
  `open_delta_checkpoint`): fail-fast `timeout = 0`, preserved by design.
  Verification runs before the worker starts, and a verification that would
  block indicates a real problem — the checkpoint is dropped and replayed
  from `H0` anyway.
- `journal_mode=WAL` is never re-set by any connection except creation
  (`_create_delta_schema`): it is durable in the header, and re-setting it
  requires the write lock. Every other connection verifies the header mode
  and re-applies the connection-local `synchronous=FULL`.

The AC-63-v1 gate-determinism defect was exactly this: `_connect_delta`
re-set `journal_mode=WAL` with `timeout=0`, so `retry()` failed
immediately with a spurious `DeltaRejected` whenever the worker held the
write lock. The regression is pinned by `test_retry_waits_for_the_delta_write_lock`
(lock held 0.3 s while `retry()` runs: it waits and completes) and
`test_retry_under_worker_write_concurrency` (8 rounds of block → retry →
catch-up with a 30-event batch per round, ending fully caught up).

## Replay equivalence (AC63-7)

Deterministic replay equivalence is **evidence-level**: after restart / lost
notification / checkpoint corruption / epoch change, the replayed state
serves, for every query, the same per-candidate `s` array and query point as
the canonical oracle computed on the same facts at the same watermark with
the same fp32-quantized vectors. File-level identity is never promised for
the checkpoint. Restart paths:

- checkpoint valid → load without re-embedding (fast path);
- checkpoint missing/corrupt/identity-mismatched → drop, replay from `H0`
  (recompute only post-`H0` vectors);
- facts advanced while down → resume from the checkpoint's consumed HLC;
- `store_epoch` changed → discard ALL derived state (generation, checkpoint,
  snapshot) and rebuild from facts (SCN-63-4); the machine then serves the
  rebuilt generation, not the declared one.

## Wiring

- `EvidenceService(facts_root, params, provider, gamma, machine=None)`: with
  a machine and an existing fact store, every request is served from the
  machine's caught-up snapshot (the request watermark is still checked
  against the snapshot: epoch + at-or-before). The query vector comes from
  the snapshot itself (#65): the snapshot binds its own representation at
  publish time, so one query never mixes the old and the new identity.
  Without a machine, the direct live-facts path is unchanged
  (offline/calibration). Missing fact store with a machine keeps the #61
  missing-store semantics (zero-ok without a declared watermark,
  `fact_store_fault` with one).
- `server.run_server`: when the evidence config declares `derived_root` +
  `generation_id`, the machine is constructed, registered as the
  coordinator's derived-state recovery (`invalidate`/`rebuild` seam, wired
  through `MaintenanceCoordinator(recovery=...)`) and as a quiesceable
  builder (`request_stop`/`wait_idle`), and passed into the service. The
  active generation must be declared explicitly — no directory scanning
  (spec clause 不扫描目录猜测最新 generation). After a runtime publish
  (#65) the durable active manifest resolves the active generation id and
  representation at startup; the config seam receives them as overrides.
- The config seam stays fixture-driven (like #61 today); the real
  hidden-state provider plugs at the same `RepresentationProvider` seam and
  is exercised by `integration_delta.py`.

## Deferred by decision

- **hidden-state reuse cache** (spec optional): not implemented. The cache
  is performance-only by contract; omitting it cannot affect correctness or
  reconstructibility. The worker's `_embed_vector` is the single seam where
  a cache keyed by `representation_id` + `preceding_text` digest (verified
  against the raw UTF-8 text) could later slot in without touching the state
  machine.
- Compaction/rollback (#66/#67), ANN, real-data replay (#70), deployment:
  out of scope, recorded as deferred in the delivery contract.
- The blue-green publish itself is delivered (#65): `publish_switch` is the
  in-memory pointer swap; the durable manifest, the staging-side delta and
  the publish lock are documented in `docs/publish-atomic.md`.
- **Checkpoint layout** (#65): the checkpoint is per-generation
  (`delta/<generation_id>/delta.sqlite3`), so the active and the staging
  generation each own one (spec clause); `open_delta_checkpoint` accepts
  `change_seq == -1` for an empty-window generation.
- **Fact-store read connections** (#65): the macOS WAL `-shm` handshake can
  transiently return SQLITE_BUSY when threads open fresh read-only
  connections at the same instant (the worker + query-gate pattern, which
  the publish's extra readers widen); fact-store reads use a short busy
  wait (2 s) instead of fail-fast. The fail-fast `timeout=0` stays only on
  the delta-checkpoint verification connections, where the #63 rationale
  still applies.

## Test-time note

`test_delta.py` runs the fact fixture in WAL mode (mirroring the production
C++ store, which also runs WAL). The fixture's `-wal`/`-shm` sidecars are
materialized before the machine reads, because a read-only connection cannot
create them itself.
