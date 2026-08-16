# Resumable staging generation build (Squirrel#64) — decision record

Delivery contract: AC-64-v1. The machine is `daemon/staging.py`; its
model-free suite is `daemon/test_staging.py`; the real-model integration is
`daemon/integration_staging.py`. It builds on the #62 one-shot builder
(`daemon/generation.py`) and runs beside the #63 delta machine
(`daemon/delta.py`).

## What it is

While the current healthy generation keeps serving and absorbing delta, a
single background builder chunks the *desired* generation into
`<derived_root>/staging/<generation_id>/`, durably advances one atomic
progress manifest, and leaves the fully re-verified container as a `ready`
staging for the later publish step (#65). Builds are resumable across
daemon restarts; deterministic faults block with the offending event
named; a changed target identity or store epoch discards the staging in
full — never a partial reuse, never a partial publish.

## Staging directory and progress manifest layout

```
<derived_root>/staging/<generation_id>/   the machine's own build
    progress.json    atomically replaced (temp + fsync + rename + dir
                     fsync); the durable state machine record
    vectors.fp32     row-major little-endian FP32, appended chunk by chunk
    metadata.json    written once at finalize (immutable)
    manifest.json    written once at finalize (immutable, exactly the #62
                     format, self-checksummed)
<derived_root>/staging/.verify-<id>.tmp   progress parked outside the
                     container during the reopen-verification dance
<derived_root>/generations/<generation_id>/   published generations (#62)
```

`progress.json` (schema version `shadow-generation-progress-v2`):

```json
{
  "progress_version": "shadow-generation-progress-v2",
  "generation_id": "...",            // the fixed, content-addressed target
  "status": "running" | "blocked" | "ready" | "discarded",
  "total_rows": 24,                  // deterministic active-event count at H0
  "rows_fingerprint": "...",         // sha256 of the ordered row projection
  "identity": { store_epoch, source_hlc [H0], representation_id,
                vector_dimension, vector_format, builder_version,
                retrieval_backend, retrieval_params },
  "chunks": [{ "start_row", "end_row", "bytes", "sha256" }, ...],
  "blocked_events": [...], "reason": "...", "phase": "..."   // when blocked
}
```

The `identity` + `rows_fingerprint` are exactly the #62 target identity
(AC64-1): epoch, H0, all fingerprints and the builder version are fixed at
build start, so the *record* alone pins the whole target. Every chunk
record is real — row range (== event count, 1:1 row↔event), byte count and
the sha256 of the bytes actually written (AC64-2). `progress.json` is
replaced atomically after every chunk, so at every observable point it
either matches the file prefix or is the previous complete record.

## The state machine (one step per cycle)

One worker thread runs `_cycle()` on a wake/poll cadence. Every
intermediate state is a crashable resting state: the machine embeds **one
chunk per cycle**, so a crash between chunks, between the chunk loop and
finalize, or inside finalize resumes exactly where the last *verified*
record says.

Cycle order:

1. Read the facts identity; park (progress-less block) unless the epoch
   changed.
2. Derive the fresh target from the current facts + desired provider.
3. `desired == active` → never build (spec: 配置区分 desired 与 active);
   stale records are invalidated.
4. Locate the machine's own **live record** by scanning the staging
   namespace for a record whose epoch, desired representation and builder
   version match the current configuration.  The build is pinned to the
   H0 of its start, so after facts advanced the record lives under a
   different generation id than today's fresh target; the scan is the only
   way to find it.  This is selection of the machine's OWN build, never
   "scanning the directory to guess the latest generation" (the delta
   machine's transient one-shot staging carries the ACTIVE representation
   and can therefore never be selected).
5. No-op gates: target already published, or target == declared active id
   → mark the record discarded and idle.
6. Per-status continuation: `blocked` → park until `retry()` or a target
   change; `ready` → reopen-verify once; `running` → resume.

A gate/verification failure marks the record `discarded` and starts the
fresh build in the same cycle (one step, no recursion); the first chunk
embeds on the next cycle. All records except the live one are invalidated
(marked `discarded` with the precise reason — epoch / desired / builder
version change, or an obsolete target). Records are **marked, never
deleted** by this machine: physical cleanup belongs to `clear` (already
implemented) and the #66 retention work; deletion would risk racing the
delta machine's transient one-shot staging directory.

## Resume gate (AC64-3, SCN-64-3)

A running staging is resumed only when the recorded epoch, H0, every
fingerprint and the builder version all still match. The gate recomputes
the **pinned target** from the facts at the recorded H0 (facts are
immutable within one epoch, so a mismatch is genuine drift — tampered
record, replaced store, changed representation or code) and compares the
composed generation id and the rows fingerprint; the pinned event list is
what the resume embeds. Any mismatch discards the staging in full — no
continuation, no partial reuse. Completed chunks are re-verified against
the vectors file (`_verify_progress_chunks`) before any continuation; the
file is truncated to the last verified chunk and embedding continues from
there, so a crash mid-chunk never leaves trusted garbage.

## Discard triggers (SCN-64-4)

- `store_epoch` change (clear/restore) → the record fails the live-record
  filter; it is marked discarded with "fact store epoch changed".
- desired representation change (`retarget()`, or a new config at restart)
  → "desired representation changed".
- builder version change (new daemon code) → "builder version changed".
- target already published, or target == declared active id → obsolete.

A discarded staging is never resumed or partially reused; the reason is
kept in `health()["staging_last_discard_reason"]`.

## Blocked semantics (SCN-64-5)

A deterministic parse/representation/model fault names the offending
event(s) in the record (`status: blocked`, `blocked_events`, `reason`,
`phase`) and parks the worker: no auto-retry, and — because nothing in the
query path ever calls into the machine — no per-query retry storm
(SCN-64-7). `retry()` (maintenance) clears the block and the build resumes
from the last verified chunk; if the cause persists the same event
re-blocks deterministically. A restart re-derives a progress-less block;
a progress-backed block stays parked. A store epoch change is an input
change: the block re-derives and the build proceeds. Transient faults
(I/O, concurrent store replacement) surface as errors and retry on the
next poll at the poll cadence — again, never driven by queries.

## Reopen self-verification (spec clause 6)

Finalize writes metadata + probes + manifest (idempotently: already
written immutable files are reused and re-verified), then runs the full
reopen verification (`open_generation`: file checksums incl. the manifest
self-checksum, chunk records, row/event bijection, finiteness + unit norm,
and the fixed exact-oracle probes) with `progress.json` parked outside the
container (the public verifier requires exactly the three immutable
files). Only after the verification passes is the record marked `ready`.
A `ready` staging is re-verified once per machine start; one that fails is
discarded and rebuilt — never served, never published. Nothing is ever
published by this machine (publish is #65).

## Determinism across build paths

The chunk loop, probes and manifest composition are shared code with
`build_generation` (#62): `_read_snapshot`, `_prepare_target`,
`_build_chunks` (with `chunk_limit` for one-chunk-per-cycle),
`_compute_probes`, `_compose_manifest`. A staged build therefore produces
the same generation id and byte-identical files as a one-shot build of the
same target — pinned by tests (`test_ready_staging_is_byte_identical...`,
`test_interrupted_build_resumes_and_is_bit_identical`) and by the
real-model integration.

## Relationship to #62 `build_generation` and #63 `DeltaStateMachine`

- **#62**: the one-shot builder is now a thin wrapper over the shared
  build core; its behavior and output are unchanged (the #62 suite pins
  it). The staging machine is the resumable, daemon-owned variant of the
  same core.
- **#63**: the delta machine serves the active generation; the staging
  machine is a sibling that shares `derived_root` but never writes the
  delta checkpoint, the active generation or the facts, holds no fact
  handles, and is never invoked by the query path. Epoch changes are
  detected independently by both machines (each discards its own state).
- **Single-builder constraint** (spec "一次只运行一个 builder"): a shared
  `threading.Lock` is wired to both machines. The staging machine holds it
  around every chunk embed (and the delta machine around its generation
  rebuild), so two builders never run the model concurrently. The lock is
  optional and off by default for both (backwards compatible).
- **Coordinator**: the staging machine is NOT registered with the
  maintenance coordinator. It holds no fact leases and its writes never
  touch facts or active derived state, so quiescing it adds no safety, and
  no resume hook exists for non-recovery builders (registering it would
  silently stall every background build behind the first maintenance run).
  It still implements `request_stop`/`start`/`wait_idle` as builder seams
  for tests and future wiring.

## desired / active config separation

```json
{
  "derived_root": "...",
  "generation_id": "<active generation id>",   // #63, unchanged
  "representation_id": "<active representation id>",  // #63, unchanged
  "desired_representation_id": "<desired target>",    // #64 (default: the
                                                      // active one = idle)
  "staging_poll_interval_ms": 2000
}
```

The active machine is constructed exactly as before; the staging machine
derives its target from the desired representation only. The desired
configuration never reinterprets the active generation (its provider
instance and generation id are untouched), and `retarget()` — the runtime
seam for "新 desired fingerprint 可以取消尚未发布的旧 staging" — swaps only
the desired provider.

## Deferred by decision

- Publish lock and blue-green switch (#65), compaction/retention/rollback
  (#66/#67), ANN probes (#78/#79), real-data replay (#70), deployment:
  out of scope, recorded as deferred in the delivery contract. Physical
  deletion of discarded staging records belongs to clear and #66, not to
  this machine.
