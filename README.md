# librime-llm-rerank

A [librime](https://github.com/rime/librime) plugin that reranks IME candidates
with a language model conditioned on the preceding text of the current session.

Developed for the Squirrel (鼠鬚管) fork at
[Habit130/squirrel](https://github.com/Habit130/squirrel). The design spec is
[issue #16](https://github.com/Habit130/squirrel/issues/16); implementation
tickets are issues #17–#22 in that repository. **Issues and progress tracking
live in `Habit130/squirrel`, not here** — this repo receives code PRs only.

## Install

From a librime source tree (e.g. the `librime` submodule of Squirrel):

```sh
librime/install-plugins.sh Habit130/librime-llm-rerank
```

This strips the `librime-` prefix and clones the repo to
`librime/plugins/llm-rerank`, where librime's CMake auto-discovers it. Rebuild
librime with `make librime` from the Squirrel repo root; the plugin dylib lands
in `lib/rime-plugins/`.

## Releases

Tagging this repo with `v*` runs `.github/workflows/release.yml`, which builds
a universal (arm64 + x86_64) `librime-llm-rerank.dylib` against the pinned
librime revision used by Squirrel and attaches it to the GitHub Release.
Squirrel's `action-install.sh` downloads that artifact by tag and verifies its
sha256 on the fast build path; the from-source build path keeps using
`install-plugins.sh` instead.

## Scope

Simplified Chinese (简体) only, developed against the `luna_pinyin` schema.

## Dedicated Embedding Adapters

AC-110-v1 provides two model-free-testable candidate-conditioned adapters:
`qwen3-embedding-0.6b` with the frozen query instruction and
`bge-m3-dense-1024` with dense-only 1024-dimensional output. Both use the
AC-109 `last64(preceding_text) + candidate` payload, L2-normalized fp32 cosine
vectors, and identity-bound isolated dependency versions. A process loads at
most one heavyweight embedding model; load, inference, and identity faults
fail closed. See `docs/dedicated-embedding-adapters.md` for the isolated
`.venv-embeddings` setup and the deferred v2 boundary.

## Fact Maintenance

The semantic-memory fact root contains an owner-only `maintenance.lock`. Fact
writes and daemon fact readers take a shared advisory lease before opening
SQLite; maintenance callers take a bounded exclusive lease only after their
preflight and daemon prepare steps complete. The recorder never waits for that
exclusive lease, and its commit path never performs durable I/O at all. A
session constructed while the exclusive lease is held treats the locked open
as transient: recording stays enabled, events that cannot be retained surface
as gap/fault status, and the same session resumes after the lease is released
without an application restart. A single worker thread owns the store, the
per-process crash-evidence marker (`.recording_process.*`) and the gap-state
files. Complete commit batches and
their immediate retractions remain in one process-local FIFO, bounded at 256
commit batches or 16 MiB of documented logical payload. Overflow and shutdown
leftovers are recorded in the owner-only, versioned `recording_gap.json`
without private text or embeddings; a failed gap update first marks the
pre-existing `recording_gap.lock` unknown so the loss stays visible after a
restart. One residual combination remains: if the process marker cannot be
created, an exclusive maintenance lease keeps a commit only in the process
memory queue, and the process crashes before any durable evidence exists,
that selection can be lost without a gap record. Committed user text,
existing canonical facts, candidate fallback and stale-epoch safety are
unaffected; the impact is limited to semantic-learning and diagnostic
continuity. Revisited at the #75 shadow-baseline freeze (AC-75-v1): the
owner-approved decision carries this residual as RISK-75-1 — loss mechanism
is candidate-independent and cannot bias scheme comparison; containment is
this README statement plus the freeze record; revisit milestone is the #80
config lock or earlier evidence of in-window loss.

The daemon serves scoring and maintenance over separate Unix sockets. Both
sockets require an owner-only directory and `0600` socket file; the control
socket authenticates the peer UID, keeps a prepared lease until real EOF, and
fails closed when the fact-store epoch cannot be proven after reopen.

A fact-database replacement is staged for crash consistency: the existing
main database is first validated as a regular, owner-owned `0600` file
through the root directory fd (a symlink is rejected without ever following
its target), then checkpointed (its WAL merged into the main file) and its
sidecars removed before the new main database is published with one atomic
rename. A busy or incomplete checkpoint aborts before any sidecar removal.
A failure or crash therefore exposes only the complete old store or the
complete new store, never a new main database paired with old WAL/SHM files.

This is the reusable maintenance seam that `restore` and `clear` publish
their replacements through (see below).

## Fact schema migration

`squirrel-semantic-memory migrate` upgrades a supported-old fact store to the
current schema head. Fact schema evolution is owned exclusively by the C++
writer (`fact_store_tool migrate`): the ordered, forward-only step table,
the deterministic per-event-format projection and the pre-commit validation
(counts, event/commit identities, HLC total order, foreign keys, schema
invariants) all live in C++. Python only orchestrates the operation through
the maintenance seam: a verified safety snapshot is created BEFORE any
migration work (SQLite Online Backup API + full C++ validation), the
migration runs on a staging copy of that snapshot inside one SQLite
transaction per ordered step chain, and only a successfully migrated staging
file is published with the atomic replace under the exclusive maintenance
lease.

A migration that does not change the interpretation of existing events
preserves `history_id` AND `store_epoch`; a migration that changes event,
HLC-order or other fact interpretation generates a new `store_epoch`
(`history_id` is preserved). Every old event is deterministically projected
to the current canonical event through its `event_format_version`; a missing
field or an unconvertible event blocks the migration and the build — the
event is never silently skipped. A store newer than the program supports, a
missing migration step or a validation failure leaves the original database
unchanged and stops event recording with an explicit report. Downgrades,
best-effort in-place repair and creating an empty database to paper over a
failure are all refused, and a crash at any point exposes only the complete
old schema or the complete new schema (never a mix).

The production schema head is currently v1 and ships no migration steps
(decision B): a live v1 store is already current and `migrate` reports a
no-op. The full supported-old -> head path is exercised through a
test-registered predecessor step in the operation tests and the C++ migrator
tests.

## Physical clear

`squirrel-semantic-memory clear` is the supported way to physically reset
the semantic memory. It publishes a brand-new empty fact store with a fresh
`history_id`, a fresh `store_epoch` and a reset HLC, then deletes every
application-controlled copy of the old facts and derived state
(generations, delta, staging, derived manifests, quarantine, internal
snapshots, old operation records and the app-controlled trial `traces/`
directory -- see "Desensitized trial traces"), while the three schema
switches and any backup you copied outside the fact root stay untouched.

Interactive use prints the exact confirmation string
`CLEAR <history_id> AT <store_epoch>` (or `CLEAR PRISTINE` when no store
exists) and proceeds only when you type it verbatim. Non-interactive use
requires both confirmation and a store-epoch CAS:

```text
squirrel-semantic-memory clear --yes --expect-store-epoch <epoch>
```

There is deliberately no `--force` flag. The expected epoch is verified
before any destructive work and again under the exclusive maintenance
lease; a mismatch is a zero-side-effect failure. Text commits never wait
for the clear: commits buffered during the bounded (5 s) maintenance window
are written into the new history after the linearization point.

Crash recovery is phase-persistent. A crash before the atomic replacement
leaves the complete old store observable; after the replacement the durable
`published` marker and the staged identity let a retry recognize the
already-published store without regenerating history or epoch, and a retry
after cleanup only continues cleanup. Once published, the old epoch is
never served again. A cancel honored before publishing reopens the old
state; after publishing the operation is uncancellable and finishes its
cleanup. A Ctrl-C in the foreground CLI only detaches (exit 130) while the
detached executor continues. Re-running clear on an already-empty system
returns `already_clear` without generating new identities.

**Clear is application-level deletion.** It removes every copy the
application can currently address. It does not erase APFS snapshots, SSD
wear-leveling remnants, system backups, or backups you copied to a path the
application does not manage; clear never creates an implicit backup of the
old facts, so back up explicitly first if you may want the old history
later.

## Online fact backup and offline verify

`backup create` makes a consistent snapshot of the live fact store while
you keep typing — it never requests a quiesce, never takes the exclusive
maintenance lock and never blocks the recorder — and publishes it as a
single versioned `.squirrel-memory-backup` ZIP:

```text
squirrel-semantic-memory backup create --output <path>
squirrel-semantic-memory backup verify <backup>
```

The container holds exactly two members, `facts.sqlite3` and
`manifest.json`. The manifest records the backup format and backup ID, the
fact schema and event-format range, `history_id`, source `store_epoch`,
commit/event/retraction counts, the HLC and event high-water marks, the
creation time, the producer version, the database size and its SHA-256, and
whether the destination was explicitly confirmed as insecure. The snapshot
comes from the SQLite Online Backup API through the C++ `fact_store_tool`
seam (Python never interprets fact rows); it is fully integrity-checked,
checkpointed into a single file with no WAL/SHM dependency, fsynced and
re-verified before publication.

The destination must not exist — an existing path (or a symlink) returns
`destination_exists` and there is deliberately no `--force`. The container
is staged as an exclusive owner-only `0600` temp file in the destination
parent, fsynced, re-opened and self-verified, then published with a
hard-link rename that can never overwrite a concurrently created
destination, and the parent directory is fsynced. Staging is durable under
`<root>/.backup/<operation-id>/`, so a crash mid-publication resumes with
the same backup ID and never re-snapshots or overwrites.

The backup is **plaintext private input history**; it is not encrypted.
The destination medium must prove owner-only file permissions, otherwise
the create is refused. To accept a medium that cannot (for example a
filesystem without real Unix permissions), run with
`--allow-insecure-destination` and type the exact confirmation string
`ALLOW INSECURE BACKUP AT <absolute-path>`; the operation, the manifest and
any later verify permanently mark the container
`insecure_destination: true`. The flag alone is not a bypass — it is the
entry to a second, exact-string confirmation, and no-overwrite, integrity
and checksum guarantees still apply.

`backup verify` is completely offline: it never reads the live fact root,
never creates or touches the operation store, never connects to or starts
the daemon, never loads the model and never modifies application state. It
strictly parses the container (exact member set, safe names, no
directory/symlink/device members, no encryption, supported compression,
documented size and compression-ratio limits, CRC), extracts both members
into an owner-only temporary directory, re-computes the database checksum
and size and cross-checks every manifest identity/count/HLC field against
the C++ fact-store interpretation of the extracted database. Malformed,
tampered, corrupt or unsupported containers are rejected with a stable
error code and no state change.

Like `clear`, `backup create` is a persistent operation: the operation ID
is printed before any snapshot work, `operation show/wait/cancel` observe
it, a cancel honored before publishing cleans the staged snapshot and temp
without leaving a target, a publish makes the operation uncancellable, and
Ctrl-C in the foreground CLI only detaches (exit 130) while the detached
executor continues. The same operation ID with the same parameters reuses
the same backup; the same ID with different parameters is rejected.

## Whole-store restore

`squirrel-semantic-memory restore` atomically replaces the whole live fact
store with a verified backup, preserving the backup's logical history
(`history_id`, event/commit IDs, HLC state) while minting a **new**
`store_epoch` through the C++ seam (`fact_store_tool prepare-restore`).
Restore never merges events by ID.

```text
squirrel-semantic-memory restore --from <backup> \
    (--backup-current <new-path> | --discard-current)
squirrel-semantic-memory restore --from <backup> --yes \
    --expect-store-epoch <epoch> (--backup-current <new-path> | --discard-current)
squirrel-semantic-memory restore --from <backup> --discard-current \
    --accept-unreadable-current --expect-current-fingerprint <hash>
squirrel-semantic-memory restore --from <backup> --discard-current \
    --expect-no-store
```

Preflight validates the container (exact member set, names, attributes,
compression, sizes, ratios, CRC), the manifest, the extracted database's
SHA-256/size/integrity, its schema version and the available space. A
supported-old backup is classified through the migrate seam and is migrated
**only on the staging copy** during staging — the backup original is never
modified; a too-new or missing-step backup is refused in preflight. Every
preflight failure leaves the current store untouched.

Retention is explicit: the operator must choose `--backup-current <path>`
XOR `--discard-current` before any mutation. `--backup-current` runs AFTER
quiesce and BEFORE the replace, reusing the backup.create / snapshot path
(owner-only destination, no-overwrite publication, independent
verification); if that backup fails, the live store is unchanged.
`--discard-current` never writes a current backup — restore never secretly
saves the current store.

Confirmation is exact: interactive use prints the plan (current
history/epoch/event count -> backup history/high-water/event count) and
requires typing `RESTORE <backup_id> OVER <current_store_epoch>` verbatim.
Non-interactive use requires both `--yes` and `--expect-store-epoch`, which
must match the current live epoch (a stale expectation is a zero-side-effect
failure). Only a healthy current store can be restored over: an unreadable
current store fails closed, and a missing store fails closed.

**Unreadable current store (#57).** When the current `facts.sqlite3` is
present but the identity seam cannot read it (corrupt header, clock-invalid
meta, open/permission failure), restore is allowed ONLY with the atomic flag
pair `--accept-unreadable-current` + `--expect-current-fingerprint <sha256
hex>`. Classification runs the C++ `schema` seam on a throwaway copy of the
store (never the live file, so the as-is bytes stay untouched): a store the
seam reads is refused — healthy (not a bypass of the epoch CAS),
supported-old needs-migration, or too-new (migrate stays the only upgrade
path per RISK-57-2). The fingerprint is defined over the as-is DB+WAL+SHM
bytes that will be quarantined (documented in `daemon/quarantine.py`; tests
and manual probes compute the same value). After quiesce the fingerprint is
computed from the ALREADY-OPENED descriptors and compared with the
expectation; on a match the as-is bytes are copied into
`quarantine/<operation_id>/` (0700 dir, 0600 files), byte-identity-verified
and fsynced BEFORE the atomic replace. Any fingerprint mismatch,
copy/verify failure or space shortfall aborts with the current bytes
untouched and no successful-looking quarantine. `--backup-current` is
refused (an unreadable store cannot be snapshotted).

**Missing store (#57).** A truly absent `facts.sqlite3` uses the distinct
`--expect-no-store` branch: the backup's history is restored as a new epoch
with no quarantine and no current-epoch CAS (there is none). A present file
— even an unreadable one — never satisfies `--expect-no-store`.

**Quarantine.** The daemon never scans, repairs, merges or auto-restores
quarantine. `squirrel-semantic-memory quarantine list` reports only identity
(operation id, fingerprint, sizes, timestamp — never any private text);
`squirrel-semantic-memory quarantine purge <operation_id>
<content_fingerprint>` deletes exactly one operation's copy and only when
BOTH identifiers match exactly (a wrong fingerprint refuses the delete).
`clear` deletes all app-controlled quarantine; external backups are
untouched.

Crash recovery is phase-persistent. A crash before the atomic replace
leaves the complete old store observable; after the replace the durable
`published` marker and the staged identity let a retry recognize the
already-published store without regenerating history or epoch. A cancel
honored before publishing reopens the old state; after publishing the
operation is uncancellable. Ctrl-C in the foreground CLI only detaches
(exit 130) while the detached executor continues. The result reports
`fact_operation_succeeded` and `serving_ready` separately: the restore
waits for the daemon reopen and confirms the rebuild is durably queued, but
never waits for a full generation rebuild.

## Exact retrieval-evidence oracle

`daemon/oracle.py` implements the spec-fixed exact oracle (Habit130/squirrel
#43 "精确 oracle" / #59): the single ground truth every semantic-memory
evaluation compares against. It is model-free and stdlib-only, consumes
read-only fact stores plus caller-supplied deterministic per-event vectors,
and never produces or touches embeddings.

```text
choice_problem_key = schema_id + category + canonical_segment_input
r_i = clamp((cos_i - tau) / (1 - tau), 0, 1)
u_i = count of same-key active events with order > order(i)
d_i = 2 ** (-u_i / H)
a_i = r_i * d_i
kept = at most K_evidence events above the threshold, largest a_i
m_c = sum(a_i for kept events whose simplified-NFC selection == candidate c)
s_c = (m_c / M) * m_c / (m_c + k)   # M > 0; s_c = 0 otherwise
```

Semantics that must never drift:

- All same-key active events are fully evaluated (cosine, threshold
  relevance, usage age, final weight) **before** the top-K cut; taking a
  cosine top-K first and aging afterwards is a different, non-equivalent
  order (a fixed counterexample test proves this).
- Usage age advances only by same-key **active** events later in HLC order;
  calendar time, unrelated input and idle time never decay an event.
- Retraction follows HLC, mirroring `FactStore::QueryActiveEventsAsOf`:
  an event exits both the evidence set and the age clock at its retraction
  HLC, and a future retraction never backfills an earlier replay point.
- Zero evidence (empty store, no same-key events, nothing above `tau`,
  nothing matching the current group) is a successful result; missing or
  malformed stores, missing vectors and non-finite values are true faults
  (`OracleError`).
- Matching uses simplified-converted NFC text: NFC normalization plus the
  OpenCC `t2s` conversion (longest phrase match, character fallback, first
  alternative). The dictionary files under `daemon/opencc_data/` are copied
  verbatim from the OpenCC revision librime pins
  (`deps/opencc` @ `556ed224`, ver.1.1.2-148, Apache-2.0) — the same data
  librime's `zh_hans` simplifier uses — so oracle matching agrees with the
  candidate text librime actually shows.

Run the oracle tests with the rest of the daemon suite:

```sh
python3 -m unittest discover -s daemon -p 'test_*.py'
```

`daemon/test_oracle.py` covers every acceptance criterion of #59,
including the fixed counterexample for the top-K order and the retraction
timing scenarios.

## Accelerate exact retrieval backend (#72)

`daemon/accelerate.py` implements the #72 exact backend challenge: the same
exact evidence semantics as the oracle, with the per-event cosine computed by
Apple vecLib (`cblas_sgemv`) over the generation's canonical row-major
little-endian FP32 vector file — zero copy, no second resident copy.  It is
the #71 baseline's challenge object: the pure-Python oracle measured ~7.5 s
per query on the 100k single-hot-key fixture; the Accelerate path measures
single-digit milliseconds for the same query.

- **Same evidence, same aggregation.**  The engine plugs into
  `oracle.compute_evidence` through the `CosineEngine` seam
  (`batch_cosines`); the oracle's aggregation (threshold, usage age, final
  weight, top-K, `m_c` / `M` / `s_c`) is untouched and never duplicated
  (SCN-72-1/2).  Small same-key sets use the oracle's own Python float64
  scalar cosine (bit-identical by construction); large sets use one batched
  `cblas_sgemv`.
- **Backend identity.**  The backend is bound into `index_fingerprint`
  (`compose_backend_fingerprint(backend="accelerate-cblas-sgemv")`, library
  version `accelerate-vecLib-cblas-sgemv-v1`); serving Accelerate under the
  old `oracle-exact-v1` fingerprint is a contract failure (SCN-72-4).  The
  FP32 vector file itself is identical across backends.
- **Fail closed.**  If vecLib is unavailable at runtime the daemon raises a
  fault (`accelerate_fault`) — never a silent Python fallback presented as
  Accelerate (SCN-72-5).
- **Equivalence.**  `daemon/test_accelerate.py` (model-free) compares the
  engine against the oracle query-by-query: kept neighbors, event weights,
  candidate evidence `s_c` and final emit order, within a pinned 1e-6
  absolute cosine tolerance (measured deviation ~1e-8 at 100k x 1024).

Select the backend on the daemon config seam (`retrieval_backend`:
`"exact"` or `"accelerate-cblas-sgemv"`); the bench driver accepts
`--backend accelerate-cblas-sgemv` (see `daemon/bench_100k.py`).

## MLX exact retrieval backend (#73)

`daemon/mlx_engine.py` implements the #73 exact backend challenge: the same
exact evidence semantics as the oracle, with the per-event cosine computed by
MLX (`mx.matmul` over the generation's canonical row-major little-endian
FP32 vector matrix, plus per-row squared norms).  It is the #72
Accelerate-path challenger and the second exact backend over the same
canonical FP32 file.

- **Same evidence, same aggregation.**  The engine plugs into
  `oracle.compute_evidence` through the `CosineEngine` seam
  (`batch_cosines`); the oracle's aggregation (threshold, usage age, final
  weight, top-K, `m_c` / `M` / `s_c`) is untouched and never duplicated
  (SCN-73-1/2).  Small same-key sets (≤256) use the oracle's own Python
  float64 scalar cosine — bit-identical by construction, the #72 small-set
  contract; large sets use one batched `mx.matmul`.
- **No second resident model.**  The engine is a dense FP32 matrix-vector
  product over the already-built vector file; it never loads a model and
  never spawns a second daemon.  It shares the daemon process with the
  mean-token LM candidate scorer — the #73 contention measurement
  (`daemon/bench_contention.py`) exercises exactly that shared-process
  configuration (SCN-73-5).
- **Backend identity.**  The backend is bound into `index_fingerprint`
  (`compose_backend_fingerprint(backend="mlx-exact-matmul")`, library
  version `mlx-core-matmul-v1`); serving MLX under the oracle or the
  Accelerate fingerprint is a contract failure (SCN-73-4).  The FP32 vector
  file itself is identical across all backends.
- **Fail closed.**  If MLX is unavailable at runtime the daemon raises a
  fault (`mlx_fault`) — never a silent Accelerate/Python fallback presented
  as MLX (SCN-73-6).
- **Equivalence.**  `daemon/test_mlx.py` (model-free) compares the engine
  against the oracle query-by-query: kept neighbors, event weights,
  candidate evidence `s_c` and final emit order, within a pinned 1e-6
  absolute cosine tolerance (measured deviation ~3e-8 at 100k x 1024).
- **Memory.**  MLX 0.32 has no zero-copy CPU array constructor, so the
  engine holds one explicit in-process working copy of the canonical FP32
  matrix (~400 MiB at 100k x 1024) instead of #72's zero-copy mmap view;
  the file-backed generation stays the durable source of truth and the
  working copy is released with the snapshot.  The RSS cost is reported
  explicitly in the #73 memory/contention record (RISK-73-4).

Select the backend on the daemon config seam (`retrieval_backend`:
`"exact"`, `"accelerate-cblas-sgemv"` or `"mlx-exact-matmul"`); the bench
drivers accept `--backend mlx-exact-matmul` (`daemon/bench_100k.py`,
`daemon/bench_evidence_daemon.py`) and `daemon/bench_contention.py` measures
the shared-process contention window.

## Retrieval-evidence protocol (Squirrel#61)

The plugin asks the daemon for the oracle's candidate-level evidence of one
rerank group over the same unix socket, as an additive `kind: "evidence"`
request. The request carries the full AC61-1 contract: schema, choice
problem (schema + category + canonical segment input), the recent 64-char
上文, the current candidate group, the evidence config identity and the
plugin's declared fact high-water (`store_epoch` + max change HLC).

- `daemon/evidence.py` — `EvidenceService`: read-only facts + the canonical
  oracle behind an injectable `RepresentationProvider` seam (the #62
  generation hook). `FixtureRepresentationProvider` is the injected,
  deterministic, model-free implementation used by the daemon tests and the
  end-to-end gate; #62 plugs a real hidden-state provider behind the same
  interface.
- Success responses carry `status: "ok"` plus a per-candidate `s` array and
  an explicit `zero_evidence` flag. Zero evidence (empty store, no same-key
  events, nothing above the threshold, nothing matching the current group)
  is a success, never an error.
- True faults — missing/corrupt stores, config-identity mismatch, fact
  epoch mismatch, not caught up, representation/oracle faults — are explicit
  error objects. The plugin adds `gamma * s_c` to the base score only on a
  complete, identity-bound success; every fault passes the whole window
  through in original order.
- The old first-stage bigram term is gone: `ContextScorer`/`ContextMemory`
  were removed, and the plan's retrieval policy id is the exact-oracle
  evidence policy. There is no second term to double-count.

Run the evidence tests with the rest of the daemon and C++ suites:

```sh
python3 -m unittest discover -s daemon -p 'test_*.py'
ctest # llm_rerank_test (filter/protocol/recorder e2e)
```

## Desensitized trial traces and exit alarms (Squirrel#74)

The daemon records a local, app-controlled, owner-only `traces/` directory
under the semantic-memory root (`daemon/tracing.py`) so the real-trial
("真实试用") semantics of the evidence path stay explainable by identity
only:

- **Order changes** — when the semantic emit order of a complete rerank
  group differs from the γ=0 shadow baseline (the same group replayed with
  zero retrieval evidence), the daemon writes one structured trace with
  config/generation fingerprints, facts/derived watermarks, base and final
  ranks, the score decomposition (neighbor event IDs, cosine, `r_i`/`d_i`/
  `a_i`, aggregated `s_c`), the retrieval backend and segmented latencies.
- **True faults** — every fault records a stable error identity plus the
  fail-closed pass-through result.
- **Unchanged successes** — aggregates only: counts plus a segmented
  latency histogram, never a per-request trace.

The plugin declares its γ=0 base scores in the additive `trial` envelope of
each evidence request; the daemon replays the shadow and final emit orders
from those numbers.  Traces, errors, annotations and status never contain
上文, candidate text or embeddings — event IDs, request IDs, hashes and
numbers only (the store refuses non-ASCII identity bytes outright).

CLI verbs (on `squirrel-semantic-memory`):

```text
squirrel-semantic-memory annotate mispromotion --request-id <ID> [--event-id <ID>]
squirrel-semantic-memory alarm list [--json] [--all]
squirrel-semantic-memory alarm dismiss <alarm_id> [--reason <text>]
```

`annotate` records a user-confirmed mispromotion by request/event ID only
(never private facts) and refuses unknown IDs.  Exit **alarms** are advisory
and only ever suggest rollback to `γ=0`; they never write config or any
switch.  Sliding windows, pinned: 3 user-confirmed mispromotions in any
consecutive 100 actionable events; true-fault rate > 1% in any consecutive
300 semantic requests; two consecutive 300-request windows missing the
p95/p99 full-request latency gates (50/75 ms, the spec #43 gates #71/#72/
#73 measure against).  A user may dismiss an alarm (subjective veto);
dismissal never erases traces or annotations.  `status` reports the trial
dimension (trace count, aggregates, active alarms) and exits 1 while an
alarm is active.  `clear` removes the whole app-controlled `traces/`
directory (SCN-74-9); external copies you made are out of scope.

## Versioned hidden-state 上文 representations

`daemon/representations.py` (pure, model-free) and `daemon/hidden_state.py`
(MLX-bound, lazy imports) generate the pre-declared first-round 上文
representations for Habit130/squirrel#60: the seam that turns the raw last-64
chars of committed text into versioned, recomputable, comparably-scaled
vectors without a second resident model (ADR-0001).

The first-round candidate set is exactly what the manual prototype
(`feat/prototype-semantic-neighbors`, Habit130/squirrel#33) kept:

- `exact_l14_last`, `exact_l21_last`, `exact_l28_last` — one deterministic
  `encode(last 64 chars)` forward, last-token hidden state at layers 14/21/28;
- `split_l28_last` — the pre-declared split-reuse representation: the scoring
  seam's tokenized prefix + tail (prefix KV-cached), last token at layer 28.

Every vector applies Qwen's final RMSNorm to the snapshot (so intermediate
layers live on the same scale as the last), is cast to FP32 and L2-normalized,
so distance is cosine. EOS last-token, unnormalized dot, prefix-only
(drop-last-4-chars) and candidate-conditioned pair representations were
rejected by the manual prototype and are deliberately not first-round
candidates.

Each generated vector is bound to a deterministic `representation_id` that
covers the model/tokenizer content digests, the mlx-lm implementation version,
layer, pooling, truncation, seam, normalization, dimension, dtype and metric.
Any component change yields a different id, so a vector computed under one id
is incompatible with vectors under another (spec #43's "任何表示变化都会触发
正确重建"). Recomputing the same raw UTF-8 上文 under the same identity is
bit-identical across loads and processes; the `mlx_lm` forward graph is
version-constrained to Qwen3.

### AC-109 candidate-conditioned routes

The context-only routes above remain the accepted #69 v1 development/regression
artifact. AC-109 adds a separate frozen matrix without changing that v1
payload, route names, or digest:

- `candidate_l14_candidate_span_mean`
- `candidate_l21_candidate_span_mean`
- `candidate_l28_candidate_span_mean`
- `candidate_l28_last_candidate_token` (pooling control)

Each query and historical event is serialized as the last 64 Unicode characters
of 上文 followed immediately by one candidate, with no separator and
`add_special_tokens=False`. Token attribution uses the existing reconstruction
rule. Empty 上文 is valid; an empty candidate or an unprovable BPE boundary is
a representation fault. The sequence is RMSNormed, then only the attributed
candidate span is mean-pooled or last-token pooled and L2-normalized.

Evidence creates one query vector per current candidate and compares it only
with events whose selected candidate is that candidate inside the same choice
problem. Evidence remains positive-only and zero evidence remains a successful
result. `eval/candidate_conditioned_benchmark.py` is a model-free adapter over
#69 v1; the deferred v2 benchmark is not imported or run by this delivery.

The context-only #60 boundary rules remain unchanged: an empty window, a
window that tokenizes to no tokens, a model-forward fault and a non-finite or
zero-norm vector are explicit `RepresentationError` faults. For the AC-109
candidate routes, empty 上文 is valid because the candidate supplies the whole
payload; only an empty candidate, an unprovable span, or a dirty forward is a
fault.

Evidence commands (daemon venv required for the integration/latency run):

```sh
# model-free gate (no MLX/model)
python3 -m unittest discover -s daemon -p 'test_*.py'
# real-model determinism, no-second-model, seam/boundary, segmented latency
daemon/.venv/bin/python daemon/integration_hidden_state.py --rounds 32:32
```

The integration script writes a JSON evidence artifact (environment snapshot,
timestamps, representation ids and vector hashes, segmented latency) to
`--output` or a fresh temp dir; it reads and writes only temp/synthetic data,
never the private fact root or `~/Library/Rime`. Winner selection among these
candidates is intentionally deferred: no representation is declared a winner
without real selection-event evidence (Habit130/squirrel#77 / #80).

## Immutable shadow generations

`daemon/generation.py` builds immutable, byte-deterministic FP32 shadow
generations from the selection facts (Habit130/squirrel#62): each generation
is the pre-declared representation of every active event at a fixed fact
snapshot, stored so it can be re-verified, replayed and deterministically
rebuilt without ever becoming a second fact source.

Container layout (spec #43):

```text
<derived_root>/staging/<generation_id>/   in-progress / blocked builds
    progress.json   transient progress manifest (atomically advanced)
    manifest.json   identity + per-file checksums + chunk records + probes
    metadata.json   read-only row -> event projection
    vectors.fp32    row-major little-endian FP32, mmap-able, no header
<derived_root>/generations/<generation_id>/   immutable published generation
```

Identity composition — `generation_id = shadow-gen-v1:<sha256(identity +
rows_fingerprint)>` — binds `store_epoch`, the source HLC watermark `H0`, the
complete `representation_id`, vector dimension and format, the builder
version, and the retrieval backend and parameters. Two builds over the same
facts and identity produce the same id and byte-identical files; deleting a
generation and rebuilding from facts is bit-identical (spec's explicit
rebuild path, never an in-place update). The builder reads the facts
read-only inside one SQLite transaction (active events as of `H0`, ordered by
`(hlc, event_id)`), re-checks the store identity before publishing, writes
chunks with per-chunk row-range checksums in `progress.json`, and publishes by
atomic rename only after the full reopen verification (checksums, chunk
records, row/event bijection, finiteness and unit norm of every vector, and
the fixed exact-oracle probes) passes.

Deterministic parse, representation or model errors enter `blocked` with the
blocking event(s) named in `progress.json`; nothing is silently skipped, and a
blocked build is never published. `open_generation` re-verifies everything
and raises `GenerationRejected` for corrupt, truncated or identity-unknown
containers — never loading them as an empty memory. `replay_exact` replays one
query against the generation: the oracle's as-of point is pinned to `H0`, the
facts must carry the same `store_epoch` and the same active event set, and
event vectors come from the mmap'd file, so the evidence is bit-identical to
the canonical oracle on the same facts and vectors. `GenerationRepresentationProvider`
exposes the generation behind the #61 `RepresentationProvider` seam (the
online/delta integration is #63; the staging blue-green publish is
#64/#65).

The real-model provider (`HiddenStateRepresentationProvider` in
`daemon/hidden_state.py`) recomputes each event's vector from the raw
`preceding_text` stored in the facts — the facts stay the only raw-text
source; the container holds vectors, keys and candidate text only. No
winner is declared: the shadow build covers the whole pre-declared first-round
set (`exact_l14/21/28_last` and `split_l28_last`), one generation each.

Evidence commands (daemon venv required for the integration run):

```sh
# model-free gate (no MLX/model)
python3 -m unittest discover -s daemon -p 'test_*.py'
# real-model: build all first-round generations, determinism rerun,
# delete-rebuild and replay-vs-oracle equality on 24 synthetic events
daemon/.venv/bin/python daemon/integration_generation.py --events 24
```

The integration script writes a JSON evidence artifact (per-generation
identity and file hashes, determinism rerun hashes, replay equality) to
`--output` or a fresh temp dir; it never touches the private fact root,
`~/Library/Rime` or the live daemon.

## Persistent delta state machine

`daemon/delta.py` makes newly committed events and whole-commit retractions
immediately visible to the next successful semantic query (Habit130/squirrel#63),
on top of one verified immutable base generation (#62):

- A single catch-up worker absorbs fact changes in fact-transaction order
  and advances one `delta.sqlite3` checkpoint (WAL, `synchronous=FULL`)
  holding FP32 vector BLOBs, event metadata, retraction tombstones, the
  compatible identity (base generation, store epoch, representation,
  dimension) and the consumed change HLC.
- One catch-up batch embeds vectors, then advances rows + tombstones +
  watermark + change sequence in ONE SQLite transaction; only after that
  commit is a new read-only query snapshot published atomically. A
  retraction exits both evidence and the age clock in the same snapshot.
- Every query first re-reads `store_epoch` + max change HLC from the facts
  and succeeds only when the published snapshot has caught up; a snapshot
  behind the watermark (or a catch-up that misses the request deadline)
  fails explicitly with `not_caught_up`, never a stale-watermark success.
  Notifications are only a wake optimization.
- The checkpoint is a fast-recovery cache, never a second fact source:
  restart, lost notifications, checkpoint corruption (identity, checks,
  event-set equality) and `store_epoch` changes all replay deterministically
  from facts to evidence-identical results (文件级等价不作承诺).
- `EvidenceService` serves from the machine's snapshot when the evidence
  config declares `derived_root` + `generation_id`; the machine doubles as
  the maintenance coordinator's derived-state recovery (invalidate/rebuild)
  and quiesceable builder. Without the delta keys the direct live-facts path
  is unchanged.

Design decisions are recorded in `docs/delta-state-machine.md`.

Evidence commands:

```sh
# model-free gate (no MLX/model)
python3 -m unittest discover -s daemon -p 'test_*.py'
# real-model: immediate visibility + retraction, restart fast path,
# corrupt-checkpoint replay and epoch-change rebuild on synthetic facts
daemon/.venv/bin/python daemon/integration_delta.py --events 24
```

## Resumable staging generation build

`daemon/staging.py` builds the *desired* generation in the background while
the current healthy generation keeps serving and absorbing delta
(Habit130/squirrel#64), resumably and without ever disturbing the active
path:

- The staging fixes the target epoch, H0, all fingerprints and the builder
  version in an atomically advanced `progress.json` (`status`:
  `running | blocked | ready | discarded`), and each build chunk records
  its real row range (== event count), byte count and sha256.
- One chunk is embedded per worker cycle, so every intermediate state is a
  crashable resting state: a daemon restart (or any transient interruption)
  resumes from the last **verified** chunk — completed chunks are
  re-verified against the vectors file and never re-embedded. Resumption
  is gated on epoch, H0, fingerprints and builder version all matching the
  record; any mismatch (or a changed desired representation / store epoch /
  builder version) discards the staging in full — no continuation, no
  partial reuse.
- Deterministic parse/representation/model faults enter `blocked` naming
  the offending event(s); the worker parks (no auto-retry, and queries
  never wake the builder), `retry()` resumes from the last verified chunk.
- When the chunks are done, finalize writes metadata + the fixed
  exact-oracle probes + the #62 manifest and runs the full reopen
  self-verification before marking the staging `ready` — which is then
  re-verified once per daemon start. Nothing is published here (the
  publish lock and blue-green switch are #65).
- The config distinguishes **desired** from **active**
  (`desired_representation_id`, defaulting to the active one = idle); the
  desired configuration never reinterprets the active generation. A shared
  builder lock serializes this machine's chunk embeds against the delta
  machine's generation rebuilds (spec: 一次只运行一个 builder).
- The staged container is byte-identical to a one-shot `build_generation`
  of the same target (both share the same build core), pinned by tests and
  the real-model integration.

Design decisions are recorded in `docs/staging-resumable-build.md`.

Evidence commands:

```sh
# model-free gate (no MLX/model)
python3 -m unittest discover -s daemon -p 'test_*.py'
# real-model: chunked build + byte-identity, crash/resume, epoch and
# desired change discard, deterministic block, active serving
daemon/.venv/bin/python daemon/integration_staging.py --events 24
```

## Atomic blue-green publish

`daemon/publish.py` atomically switches the serving identity from the
current active generation to a `ready` staging generation
(Habit130/squirrel#65): after the publish-time reopen verification
(checksums, event set, row mapping, vectors, exact-oracle probes), the
publish reads the current facts watermark `H1` under a short daemon-
internal lock, absorbs `(H0, H1]` additions and whole-commit retractions
into the staging generation's **own** delta checkpoint
(`delta/<generation_id>/delta.sqlite3`, the spec's "active generation 与
staging generation 各自拥有独立 delta checkpoint"), then durably replaces
`<derived_root>/active_manifest.json` (temp + fsync + rename + parent
fsync) and swaps the in-memory query pointer through the delta machine's
`publish_switch` handshake:

- A crash before the manifest replace leaves the complete old active (and
  a publish that failed before the commit rolls the container rename back,
  so the publisher retries); a crash after the manifest replace loads the
  complete new generation on restart — the manifest, not the config, is
  then the source of truth for the active identity (SCN-65-2/3).
- Facts committed after `H1` (e.g. during the publish) are caught up by
  the new active before the next successful query — never a
  stale-watermark success (SCN-65-4); fact writes are never blocked by the
  publish (SCN-65-6).
- One query never mixes the old and the new representation / projection /
  index identity: the served query vector is bound to the snapshot's own
  representation (SCN-65-5).
- A store epoch change mid-publish aborts with the old active intact
  (SCN-65-7). Deterministic delta-embed faults mark the staging `blocked`
  with the event named; `retry()` re-arms it.
- The retired healthy active becomes the rollback pointer
  (`rollback_manifest.json`), and the retention sweep keeps at most
  {active, rollback, current staging}: generations outside the set are
  deleted, a space-short build keeps the current active (never the only
  rollback), and a damaged active is isolated under `derived_root/isolated/`
  (SCN-67-2/3).
- Old generations are never updated in place, and the desired
  configuration never reinterprets the active generation.

Design decisions are recorded in `docs/publish-atomic.md`.

## Compatibility matrix (Squirrel#66)

`daemon/compat.py` is the single reuse/load authority for derived state.
The desired and active layered identities (fact schema version,
representation id, vector format version, projection version, index
fingerprint, store epoch) are compared item by item and the matrix returns
the exact action union the build path must execute:

- `store_epoch` change -> invalidate all derived state, full rebuild from
  current facts (SCN-66-1).
- `representation_id` change -> re-embed all active events (SCN-66-2).
- only `projection_version` change (same representation) -> rebuild the
  projection from facts and reuse vectors by event_id when the old
  checksums verify (SCN-66-3/4).
- only `vector_format_version` change -> reuse FP32 only through a
  registered tested-equivalent converter, otherwise re-embed (never a
  byte-cast) (SCN-66-5/6).
- only `index_fingerprint` change -> no model, no projection rebuild; in
  the exact-only envelope this is a planned no-op with reason
  `no_ann_sidecar` (SCN-66-7, RISK-66-1).
- only query parameters change -> explicit no-op for the base (SCN-66-8).
- multi-layer change -> the action union, never a guessed smaller action
  (SCN-66-9).
- unknown identity / missing compat declaration / checksum failure ->
  refuse the load; no config-active fallback (SCN-66-10/12).
- during a desired build the status reports both fingerprints and the
  mismatch reasons; active queries still use the active identity only
  (SCN-66-11).

Evidence commands:

```sh
# model-free gate (no MLX/model)
python3 -m unittest discover -s daemon -p 'test_*.py'
# real-model: ready-staging publish with (H0,H1] replay, manifest replace,
# pointer swap, restart-from-manifest, epoch-abort, fact writes during
# the publish window (24 synthetic events)
daemon/.venv/bin/python daemon/integration_publish.py --events 24
```

## Retention, rollback and damage recovery (Squirrel#67)

`daemon/retention.py` owns the derived-state lifecycle: at most one active,
one **healthy** rollback and one staging; an explicit rollback pointer
(`rollback_manifest.json` next to `active_manifest.json`); damage isolation;
and the pre-build space estimate.

- **Rollback pointer** — after a successful publish the just-retired healthy
  active is registered as the rollback (before the manifest swap, so a crash
  mid-publish still keeps a rollback).  A damaged active is isolated, never
  registered.  The pointer is the ONLY recovery source — nothing scans
  `generations/` to pick a "newest" (SCN-67-7).
- **Retention sweep** — after a successful publish (or once at startup)
  deletes generations outside {active, rollback, current staging}; the only
  rollback is never deleted (SCN-67-2/3).
- **Space** — before a build the peak of active + rollback + staging + delta
  is estimated against `derived_disk_budget_bytes` (default 3 GiB, spec #43
  disk gate); a short budget keeps the current active and reports the error,
  never deleting the only rollback (SCN-67-3).
- **Damage** — base / metadata / manifest / checksum damage isolates the bad
  generation under `derived_root/isolated/` and serves only after the
  rollback is re-verified (identity + checksums + probes) and its delta
  catches up to the current facts watermark; catch-up failure is NOT a
  semantic success (AC67-5).  Delta-checkpoint damage drops the checkpoint
  and replays from the base watermark (AC67-4).  A missing ANN sidecar is
  never active-generation death (`no_ann_sidecar` pin, RISK-67-1).
- **No healthy rollback** — the semantic path fails closed (pass-through)
  and a background rebuild from facts is queued; fact recording / IME commit
  keep working (SCN-67-6).
- **Dirty scheduling** — the delta machine counts new vectors + tombstones
  against the base active row count (soft-dirty at `max(2048, 5% of base
  rows)` compacted when idle; hard-dirty at 20,000 changes or 128 MiB
  compacted even under input) and hands the compaction to the single staging
  builder (`request_compaction`) — one builder at a time (AC67-1).  A
  compaction/rebuild that reached `ready` survives a restart (the machine
  re-verifies it for the publisher instead of discarding it under the
  desired==active noop gate).
- `clear` deletes `isolated/` and `rollback_manifest.json` along with the
  other app-controlled derived state (SCN-67-8).

Evidence commands:

```sh
# model-free fault injection (SCN-67-1..9)
python3 -m unittest daemon.test_retention
```

## Explicit manual rebuild (Squirrel#68)

`squirrel-semantic-memory rebuild` explicitly triggers a manual rebuild of
the derived state (FP32 vectors, projection, delta and index) from facts,
through the EXISTING staging machine — never a second builder.  The rebuild
is a persistent #52 operation: it records an operation id AND a `build_id`
(the content-addressed staging generation id), which are deliberately
different; the same target already queued/building returns the same
`build_id`, and the same operation id with the same normalized parameters is
idempotent while different parameters are rejected (#52).

```text
squirrel-semantic-memory rebuild                      # auto
squirrel-semantic-memory rebuild --full               # force full rebuild
squirrel-semantic-memory rebuild --index-only         # ANN index only
squirrel-semantic-memory rebuild --retry <build_id>   # continue a staging
squirrel-semantic-memory rebuild --restart            # discard + rebuild
squirrel-semantic-memory rebuild --wait               # observe only
```

- **auto** — the compatibility matrix chooses the minimum safe scope; a
  healthy active that already matches the desired identity returns
  `already_current` with no new generation (AC68-1).
- **--full** — rebuilds FP32 / projection / delta / index from facts even
  when the fingerprint is unchanged; only an explicit `--full` mints a new
  generation for the same fingerprint (a fresh rebuild tag is bound into
  the generation identity; AC68-2).
- **--index-only** — allowed only when a healthy compatible FP32 + metadata
  + projection exist AND a real ANN sidecar is present; otherwise an
  EXPLICIT refusal (`no_ann_sidecar` / `index_only_*`), never a silent
  upgrade to full (AC68-3, RISK-68-1).  In the exact-only envelope the
  refusal is expected until #78/#79 land a real ANN backend; the allow
  branch (only reachable with an injected real sidecar) re-verifies the
  sidecar is a readable non-empty file before recording the outcome.
- **--retry <build_id>** — continues an existing blocked/incomplete staging;
  blocked builds never auto-retry (AC68-5).
- **--restart** — discards the current staging, then rebuilds from scratch
  (distinct from retry; AC68-5).
- **--wait** — observes only; Ctrl-C detaches (exit 130) and the durable
  build continues; cancellation is `operation cancel` and only before the
  publish (AC68-6).

Invariants (SCN-68-7/8/9): rebuild never modifies facts, `history_id`,
`store_epoch` or the three schema switches; it never quiesces the plugin
(no exclusive maintenance lease, no control socket); the current healthy
generation keeps serving during the blue-green build; and one builder is
preserved ACROSS processes — the rebuild executor takes a flock-based
single-builder lease (`<derived_root>/.rebuild-builder.lock`) around every
staging-machine cycle, so a concurrent rebuild (or a daemon staging worker
wired to the same lock) serializes instead of running a second builder, and
a crashed executor never wedges the lease (flock is kernel-released).  The
supported envelope is throwaway derived roots (RISK-68-2); the CLI resolves
the derived root from `SQUIRREL_SEMANTIC_MEMORY_DERIVED_ROOT` (else the
conventional `derived` sibling of the facts store).

Evidence commands:

```sh
# model-free: already_current, full mint, index-only refusal, build_id
# identity, retry/restart, wait/cancel, no-quiesce, single builder
python3 -m unittest daemon.test_rebuild
```

## Frozen baseline policy identity

The shadow baseline (Habit130/squirrel#75) pins a composed
`baseline_policy_id` in the deployed schema:

```text
frozen-baseline-v1:rule=<token-rule-id>:model=<model-dir-basename>
  :tokenizer=<model-dir-basename>:norm=<normalization-id>
  :fail=<failure-semantics-id>:squirrel=<squirrel-sha12>
  :plugin=<plugin-sha12>:alpha=<alpha>:beta_sys=<beta_sys>
  :beta_usr=<beta_usr>
```

The composition is deterministic and ordered; changing any component (code
SHA, model, token rule, alpha/beta, normalization or failure semantics)
produces a different id, which is how a baseline change is detected
(AC-75-v1 criterion AC75-6). The exact component values at freeze time are
recorded in the freeze record in `Habit130/squirrel` (docs/freeze/).

The daemon accepts the frozen-baseline form only when the components it can
verify match its own identity: `rule` must equal the scoring strategy's
canonical id (`mean-token-lm-v1` for the `mean_token` strategy) and
`model`/`tokenizer` must equal the daemon's own model directory basename.
The canonical id (`mean-token-lm-v1`) remains accepted for schemas that
declare no frozen id. Any other declared id fails closed with
`policy_mismatch`, and `legacy_sum` mode keeps the exact-match binding
(calibration only).

## Fixed semantic regression benchmark

`eval/semantic_benchmark.py` carries the fixed synthetic Simplified-Chinese
benchmark for Habit130/squirrel#69 (`AC-69-v1`). It is intentionally separate
from the daemon serving path and from the private fact root. The source records
derive 200 stable cases:

- 100 positive cases: two directions of 50 hand-authored same-choice-problem
  paraphrase pairs, with the same expected candidate;
- 100 hard negatives: related topics with a different intent, including
  polarity, named entity, number, tokenization seam, 64-character window and
  explicit preference changes;
- every case carries a stable ID, choice problem, candidate relation, axis
  labels and a deterministic version summary.

The distribution is 40 negation labels, 32 entity labels, 32 number-flip
labels, 32 BPE-seam labels, 32 64-character-window labels and 32
preference-change labels. Window cases are authored as a 64-character versus
over-64-character pair. BPE cases end in the known synthetic `今天天气?`
probe so the real tokenizer seam is checked rather than merely named.

The version summary is
`sha256(canonical_json(case_without_version_summary))[:24]`, where canonical
JSON uses UTF-8, sorted keys and compact separators. The benchmark digest binds
the contract, benchmark version, schema/category, fixture threshold, K and all
case payloads. This makes content changes visible without placing private
history in a report.

The model-free gate uses a disposable temporary facts root and controlled unit
vectors to exercise the #59 exact oracle, including the strict `cosine == tau`
boundary and exact top-K truncation. It is not a quality result for a real
representation; all four fixture entries intentionally share controlled
vectors:

```sh
python3 -m unittest eval.test_semantic_benchmark
python3 eval/semantic_benchmark.py --fixture
```

The opt-in real-model gate recomputes every synthetic 上文 with the #60
`Qwen3-0.6B-Base` extractor, then uses the same #59 oracle and temporary facts
root. The benchmark-only `tau=0.90`, `K_evidence=8`, `H=inf` values are fixed
regression inputs, not production calibration or a declared winner. A report
only says whether a representation should be eliminated as an obvious
regression; selection and production enablement remain outside this ticket.

```sh
daemon/.venv/bin/python daemon/integration_semantic_benchmark.py \
  --model /Users/habit/Models/Qwen/Qwen3-0.6B-Base
```

The integration artifact contains the benchmark digest, representation IDs,
case IDs for failures, coverage counts and numeric pass rates. It never writes
the synthetic raw 上文 or candidate text to the artifact, never reads
`~/Library/Rime`, never connects to the live daemon and never changes `gamma`.
Threshold/grid calibration (#70), walk-forward selection and announcement
(#77/#80), ANN and deployment remain deferred.

## License

BSD-3-Clause, matching librime.
