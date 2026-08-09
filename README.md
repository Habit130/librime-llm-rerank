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
exclusive lease: complete commit batches and their immediate retractions remain
in one process-local FIFO, bounded at 256 commit batches or 16 MiB of documented
logical payload. Overflow and shutdown leftovers are recorded in the
owner-only, versioned `recording_gap.json` without private text or embeddings.

The daemon serves scoring and maintenance over separate Unix sockets. Both
sockets require an owner-only directory and `0600` socket file; the control
socket authenticates the peer UID, keeps a prepared lease until real EOF, and
fails closed when the fact-store epoch cannot be proven after reopen.

This is a reusable maintenance seam only. Public clear, restore and schema
migration operations remain separate tickets.

## License

BSD-3-Clause, matching librime.
