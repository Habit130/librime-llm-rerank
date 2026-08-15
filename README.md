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
