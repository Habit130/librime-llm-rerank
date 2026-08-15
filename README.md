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
continuity. This residual will be revisited before the #75 shadow-recording
baseline freezes.

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

## License

BSD-3-Clause, matching librime.
