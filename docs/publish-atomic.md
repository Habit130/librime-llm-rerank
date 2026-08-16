# Atomic blue-green publish (Squirrel#65) — decision record

Delivery contract: AC-65-v1. The publish path is `daemon/publish.py`
(`GenerationPublisher` + `publish_ready_staging`); the in-memory pointer
swap lives in `daemon/delta.py` (`DeltaStateMachine.publish_switch`); the
staging machine gains publish seams in `daemon/staging.py`. The model-free
suite is `daemon/test_publish.py`; the real-model integration is
`daemon/integration_publish.py`.

## What it is

On top of the #64 resumable staging machine (a fully re-verified `ready`
container) and the #63 delta machine (the serving query snapshot), the
publisher performs the spec's publish transaction (spec #43 "并发重建与
蓝绿发布", clauses 7–11) so a crash before the commit point leaves the
complete old active and a crash after it loads the complete new
generation — never a partial or mixed state.

## Active manifest layout and fsync order (AC65-3/4)

`<derived_root>/active_manifest.json` (`active-manifest-v1`) is the durable
active pointer — the source of truth for "what is active" after a runtime
publish (the config's `generation_id`/`representation_id` are the operator's
*desired* values and become stale at publish). It records the orthogonal
identities the spec requires (fact schema version, representation id,
vector format version, projection version, index fingerprint) plus the
active generation binding (id, store epoch, H0) and its delta checkpoint
path (`delta/<generation_id>/delta.sqlite3`, manifest-relative, validated
to stay under the derived root). The config seam (`server.py`) resolves the
active id + representation from the manifest at startup; a missing manifest
falls back to the config, a malformed manifest is diagnosed and ignored
(no derived state is loaded per an unknown identity; #66/#67 own manifest
repair).

Publish durability order (each step fsynced before the next):

1. The ready container is reopened and fully re-verified (progress.json
   parked outside; checksums, chunk records, row/event bijection, vector
   finiteness + unit norm, exact-oracle probes) — the AC65-1 precondition.
2. `(H0, H1]` additions + whole-commit retractions are absorbed into
   `delta/<generation_id>/delta.sqlite3` in ONE `synchronous=FULL` WAL
   transaction (the #63 checkpoint format; events retracted inside the
   window are never embedded — projected active set identical).
3. The container is renamed `staging/<id> → generations/<id>` and both
   parent directories fsynced (the generation becomes durable).
4. The active manifest is replaced with `_write_atomic` (temp write +
   fsync + rename + parent fsync) — **the commit point**.
5. The in-memory query pointer swaps via `publish_switch` (synchronous
   handshake with the delta worker, still under the publish lock).

A failure at any point before step 4 rolls the container rename back
(`_write_atomic` only raises before its own rename, so the manifest is
provably unreplaced) and restores the parked progress record: the ready
staging survives for the publisher's next attempt. A failure at/after
step 4 leaves the manifest committed; the switch handshake is retried by
the publisher on later polls, and a restart loads the new generation.

## The publish lock and its scope (AC65-2, SCN-65-6)

One `threading.Lock` is shared by the staging machine's worker (acquired
around every state-machine cycle) and the publisher (held for the whole
transaction). This serializes the publisher's verify/rename against any
worker cycle that touches the same staging namespace (resume/finalize/
reverify/discard). The delta worker never takes the lock (the switch
handshake waits on the machine condition instead), so there is no lock
cycle. The lock is daemon-internal only: fact writes never wait on it
(SCN-65-6) — the `(H0,H1]` read and the fact writes overlap freely, and
facts past `H1` are caught up by the new active before the next successful
query (SCN-65-4, AC65-5). With no publisher wired the lock is None and the
staging machine behaves exactly as #64.

## Staging delta and its relationship to the #63 machine

Each generation owns its own delta checkpoint:
`<derived_root>/delta/<generation_id>/delta.sqlite3` (spec: active 与
staging 各自拥有独立 delta checkpoint). The active machine's checkpoint
path follows its served generation (`delta_checkpoint_path()`), including
after an epoch-change rebuild. The #65 publish writes the staging
generation's checkpoint; the `publish_switch` worker then re-verifies it
(`open_delta_checkpoint`: quick_check, pragmas, identity binding, vector
validation, change-seq consistency) plus the full generation reopen, and
**adopts** it as the machine's active checkpoint. A leftover staging
checkpoint from a crashed publish is deterministic derived state and is
superseded by the next publish of the same generation id; an orphaned one
is ignored at startup (nothing scans for it) and belongs to #66 retention.
`open_delta_checkpoint` accepts `change_seq == -1`: the legitimate fresh
state of a generation whose `(H0,H1]` window was empty.

## Crash-point matrix (SCN-65-2/3, AC65-6)

| point | disk state | restart result |
| --- | --- | --- |
| before the delta build | staging untouched | old active |
| mid-delta build (deterministic fault) | staging `blocked` (events named) | old active; `retry()` re-arms |
| after delta, before rename | staging intact + orphan `delta/<id>/` | old active; next publish of the id supersedes |
| after rename, before manifest | container rolled back (in-process) or orphaned (crash) | old active |
| **after manifest replace** | new generation + its checkpoint + new manifest | **complete new generation loads** |
| during/after the switch | manifest new, live process old | complete new generation loads |

The matrix is proven in-process by raising at the exact seam and asserting
the durable state (identical to a real crash at that point), plus the
fsync-order instrumentation test and the restart tests.

## Old-generation retention

The publish never deletes: the retired active generation directory, its
delta checkpoint, or any orphaned published container stay on disk.
Rollback registration, compaction and retention are #66/#67. `clear`'s
derived-state allowlist already covers the `delta/` directory namespace
(prefix `delta`).

## Pointer swap and the EvidenceService query path (SCN-65-5, AC65-7)

The swap runs on the delta worker (queued via `publish_switch`): it
re-verifies the published generation and its checkpoint, then atomically —
under the machine condition — swaps generation, representation provider,
checkpoint mirror and snapshot. A queued switch is processed before
catch-up and clears any deterministic catch-up block (a publish is a
representation/config change, which the spec counts as an unblocking input
change; if the fault persists past `H1` it re-blocks).

Single-query identity atomicity is by construction: `DeltaSnapshot` binds
its own representation provider at publish time, and `EvidenceService`
serves the query vector from the snapshot (`snapshot.query_vector`) — a
query can never mix the old query representation with new stored vectors.
The service's `config_identity()` follows the machine's published snapshot
representation, so the identity the daemon claims is exactly the identity
it serves, and it flips at the same instant as the pointer. (Deployment of
the matching plugin-side config identity is the #80 config lock, out of
scope here.)

## Deterministic faults and aborts

- Publish-time reopen verification failure → the staging is marked
  `discarded` (never published, rebuilt on the next cycle).
- Deterministic delta-embed fault (parse/vector) → `PublishBlocked` names
  the events; the staging is marked `blocked` (spec: 确定性失败保持
  blocked) and the old active keeps serving; `retry()` re-arms.
- `store_epoch` change mid-publish → abort with the old active untouched
  (SCN-65-7); the staging machine discards the stale record on its next
  cycle. The switch itself re-checks the epoch under the lock and aborts
  the same way.
- A `ready` staging whose record no longer matches (epoch/H0/fingerprints)
  fails the publish's resume gate and is discarded.

## Deferred by decision

- Rollback registration, compaction, retention, quarantine (#66/#67),
  ANN probes (#78/#79), real-data replay (#70), deployment: out of scope.
- The active manifest's query-parameter layer (H, γ, k, τ, K_evidence) is
  bound on the service side via the #61 config identity, not duplicated in
  the manifest (the manifest records the generation-bound identities only).
- The delta machine's own checkpoint path at *startup* is resolved from
  the manifest by the config seam, mirroring the fixture provider seam;
  the real hidden-state provider plugs at the same seam.
