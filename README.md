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

## Fact Maintenance

The semantic-memory fact root contains an owner-only `maintenance.lock`. Fact
writes and daemon fact readers take a shared advisory lease before opening
SQLite; maintenance callers take a bounded exclusive lease only after their
preflight and daemon prepare steps complete. The recorder never waits for that
exclusive lease, and its commit path never performs durable I/O at all: a
single worker thread owns the store, the per-process crash-evidence marker
(`.recording_process.*`) and the gap-state files. Complete commit batches and
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

This is a reusable maintenance seam only. Public restore and schema
migration operations remain separate tickets.

## Physical clear

`squirrel-semantic-memory clear` is the supported way to physically reset
the semantic memory. It publishes a brand-new empty fact store with a fresh
`history_id`, a fresh `store_epoch` and a reset HLC, then deletes every
application-controlled copy of the old facts and derived state
(generations, delta, staging, derived manifests, quarantine, internal
snapshots and old operation records), while the three schema switches and
any backup you copied outside the fact root stay untouched.

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

Fail-closed boundary rules: an empty window, a window that tokenizes to no
tokens, a model-forward fault and a non-finite or zero-norm vector are all
explicit `RepresentationError` faults — a dirty vector can never leave the
generation path. An empty 上文 is a fault, not a phantom EOS-anchored vector,
because a representation of void text could later contribute bogus evidence.

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
online/delta integration and staging blue-green publish are deferred to
#63/#64/#65).

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

## License

BSD-3-Clause, matching librime.
