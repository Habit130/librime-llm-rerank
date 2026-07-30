# AGENTS.md

Guidance for coding agents working in this repository. The machine-global
`~/.config/opencode/AGENTS.md` applies; this file holds repo-specific rules.
(`CLAUDE.md` is a pointer here.)

## What this repository is

`librime-llm-rerank` is a librime plugin that reranks IME candidates with a
language model conditioned on preceding text (上文). It is **not** part of
`Habit130/squirrel` and not a submodule of it. It is installed into librime
with `librime/install-plugins.sh Habit130/librime-llm-rerank`, which strips the
`librime-` prefix and clones it to `librime/plugins/llm-rerank`, where
librime's CMake auto-discovers it (`file(GLOB ...)` in
`librime/plugins/CMakeLists.txt`).

The design spec is `Habit130/squirrel` issue #16; implementation tickets are
issues #17–#22 there.

## Scope constraint

**简体中文 (Simplified Chinese) only.** The whole development targets
Simplified Chinese output via the `luna_pinyin` schema. Do not build or
generalize for Traditional Chinese or other script variants, and do not widen
the scope beyond what the current ticket asks for.

## Terminology and issue tracker (pointers back to Habit130/squirrel)

A session working here does not get the Squirrel repo's AGENTS.md, so:

- **Domain vocabulary** — 候选 / span / 类别 / 重排组 / 同音候选 / 权重 /
  品质 / 合并序 / 发射顺序 / 重排 / 组句 / 上文 / 语言模型分数 — is defined in
  **`CONTEXT.md` at the root of `Habit130/squirrel`**. Use those terms exactly;
  in particular 权重 (log-space) and 品质 (probability space) are different
  quantities and must not be mixed.
- **Issues, the task map, and blocking edges** live on `Habit130/squirrel`
  (never `rime/squirrel`), driven via the `gh` CLI — see
  **`docs/agents/issue-tracker.md`** in that repo for the workflow. Claim,
  comment, and close tickets there; only code PRs come here.

## Git flow

- Branch from latest `master`; branch prefixes `feat/` `fix/` `docs/`
  `refactor/` `chore/`; Conventional Commits in English (`<type>: <summary>`).
- PRs against `master`. The repo allows **squash merge only**, performed by the
  owner on the GitHub web UI. No auto-merge, no force-push, no direct pushes to
  `master` beyond the initial scaffolding commit.
- PR descriptions in English: motivation, what changed, how it was verified.

## Code style precedents (librime)

Match the surrounding librime idioms; do not introduce abstraction layers that
are foreign to the codebase. Concrete precedents to copy:

- **Rerank filter** — copy `librime/src/rime/gear/single_char_filter.cc`: a
  `PrefetchTranslation` subclass that rearranges candidates into `cache_` via
  `cache_.splice(cache_.end(), ...)`, wrapped by a `Filter` subclass whose
  `Apply` returns the wrapping translation.
- **Reading schema config** — copy `TranslatorOptions` in
  `librime/src/rime/gear/translator_commons.cc` (around line 126): guard
  `if (!ticket.schema) return;`, then read via
  `config->Get*(ticket.name_space + "/key", &member_)`. All parameters come
  from the schema config under the component's own namespace, so the existing
  `.custom.yaml` patch mechanism can override them per machine.
- **Subscribing to engine notifiers** — copy
  `librime/src/rime/gear/memory.cc:84-94`: connect in the constructor and
  `disconnect()` every connection in the destructor.

## Build rule (the one that bites)

**Always build with `make librime` from the Squirrel repo root — never plain
`make`.** The top-level `$(RIME_LIBRARY)` rule only checks whether
`lib/librime.1.dylib` exists, so plain `make` silently skips the entire librime
and plugin build even after plugin source changes. Before building:

```sh
export BOOST_ROOT=/opt/homebrew/opt/boost
export MACOSX_DEPLOYMENT_TARGET=13.0
make librime
```

After the plugin directory is first added, librime's CMake must re-run its
configure step so the `file(GLOB ...)` picks it up — `make -C librime release`
reconfigures in place; do **not** wipe `librime/deps/*/build` (the vendored
dependencies do not need rebuilding).

Proof the plugin really got compiled in: the dylib appears under
`lib/rime-plugins/` (and `librime/build/lib/rime-plugins/`). "Behavior looks
unchanged" cannot distinguish an identity filter from a plugin that was never
built.

## Tests

librime's own `rime_test` target does **not** link plugin libraries, so this
repo carries its own gtest target (`test/`, built under `librime/build` when
`BUILD_TEST=ON`, which is the default). Precedents for a plugin adding its own
build target: `librime-octagram` / `librime-predict` `tools/CMakeLists.txt`.

Good tests assert only externally observable behavior: given a candidate
sequence and a set of scores, what emission order comes out. They must pass
deterministically with no model, no dictionary, and no deployed user data
directory. The candidate-order assertion pattern follows librime's
`test/menu_test.cc` (hand-written `Translation` subclass producing known
candidates).
