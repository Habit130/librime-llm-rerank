# Input archive

Isolated recording/management foundation for Habit130/squirrel#188. This
delivery records and browses invented `luna_pinyin` observations. It does not
hook real input, score candidates, load a model, or enable capture on install
or merge.

CLI and TUI are Adapters. They call the Interface below and do not open
observation storage.

## Engineering choices

| Choice | Decision |
| --- | --- |
| Language | Python 3.9+ standard library only. No project venv and no extra install. |
| Transport | Unix domain socket inside the archive root. One length-prefixed JSON frame per connection. Bind/connect use the socket basename so a long checkout path still fits macOS `sun_path`. |
| Ownership | One collector per root, via a non-blocking exclusive `fcntl.flock` on the private regular `collector.lock`, held for the collector lifetime. See "Ownership and lifecycle". |
| Storage | Append-only `observations.jsonl` plus a fsynced `state.json` watermark. Quarantine is a separate file. |
| TUI | Line-oriented Overview/Timeline adapter. No third-party TUI library and no five-view claim. |
| Index | Rebuildable offset index of durable records. Payloads are not kept as a resident history copy. |
| Clocks | Event and observation clocks are client-supplied numbers or unknown. Wall-clock proximity is not a join. |

Incompatibility is an error, never a successful semantic interpretation:
`unsupported_version`, `unsupported_schema`, `stale_revision`, `unsafe_root`,
`page_bound`, `identity_conflict`, `invalid_request`. A symlink at a managed
artifact path, including `observations.jsonl`, `quarantine.jsonl`, and the CLI
logs, is `unsafe_root` before chmod, truncate, or append. The link target is
not created or rewritten.

## Start, check, stop

From a checkout, with any Python 3.9+ as `PYTHON`. The parent of `--root` must
already exist. The root must be absolute, owner-controlled, not a symlink, and
not a known synchronized destination. There is no default live root.

```sh
PYTHON=/usr/bin/python3
ROOT="$PWD/.local-work/input-archive-demo"
mkdir -p "$(dirname "$ROOT")"
"$PYTHON" -m archive.cli --root "$ROOT" --socket "$ROOT/collector.sock" collector start
"$PYTHON" -m archive.cli --socket "$ROOT/collector.sock" status
"$PYTHON" -m archive.cli --socket "$ROOT/collector.sock" policy enable --expect-revision 0
"$PYTHON" -m archive.cli --root "$ROOT" --socket "$ROOT/collector.sock" collector stop
```

Contract check, from the same checkout:

```sh
"$PYTHON" tools/check_input_archive.py --self-test
"$PYTHON" tools/check_input_archive.py --suite contract \
  --root .local-work/ac188-check \
  --report .local-work/ac188-report.json
```

Stop only the collector pid this checkout started. Do not signal an unrelated
process. Closing the CLI or TUI does not stop the collector and does not change
policy unless a control command was issued.

`collector start` exits `0` only for a collector it confirmed as the ready owner
of that root; a duplicate start on an owned root exits `1` with
`code=collector_already_running` on stderr. The ownership, readiness, and
reclaim rules are in "Ownership and lifecycle".

Capture starts disabled. A merge does not enable capture. This slice does not
certify frontend latency, ranking benefit, annotation, export, or the five-view
TUI.

## Ownership and lifecycle

One collector owns one archive root. Ownership is an OS-backed, non-blocking,
exclusive descriptor lock (`fcntl.flock`) on the private regular artifact
`collector.lock`. A collector acquires it before it loads policy or state,
reconciles a durable tail, writes its PID, or binds the socket. Both supported
entries are gated this way: `archive.cli ... collector start` and the direct
`python -m archive.collector` entry.

The owner holds that lock for its whole lifetime, through the final checkpoint,
clean-stop marking, and socket cleanup. A second start on the same root is
refused immediately and exits nonzero with `code=collector_already_running`; it
does not wait, does not reload, reconcile, truncate, or rebind the winner's
managed paths, and leaves no collector process behind. Its startup diagnostics
append to `collector.out`/`collector.err` instead of truncating the running
owner's log. Different roots are independent.

`collector start` reports success only for the child it spawned. The collector
receives an inherited pipe and a per-start token and writes `ready` on it only
after it owns the root, is listening, and is serving its own publication path.
The CLI then confirms that the answering endpoint reports the same pid in
`owner_pid` and that `collector.pid` names that pid, re-probing inside a bounded
window before it calls a start unverified, so one stalled round trip does not
condemn a healthy owner. A refused, failed, or unverified start prints
`code=<reason>` on stderr, never prints `collector_started=true`, and reaps the
child it spawned. A start whose readiness deadline passes is also reaped, so no
unconfirmed collector is left running.

Exit codes: `collector start` returns `0` started; `1` when this start did not
become the confirmed owner or its startup failed, with the stderr `code` naming
the reason (this includes a child-side `unsafe_root` such as an occupied socket
path); `2` when the request is rejected before spawning (`invalid_request`, an
unsafe root, or an unsafe request argument). The collector process returns `0`
after a normal stop, `1` when it refused ownership, and `2` for an unsafe or
invalid request.

Ownership is released by the kernel when the owning process ends. A normal stop,
a contained prepare/bind failure after acquisition, and `SIGKILL` all let the
next legitimate start proceed without deleting archive content, editing state,
or clearing a live owner's lock. Stale `collector.pid`, `collector.sock`, and
`collector.lock` files are metadata, not ownership, and need no manual cleanup;
a stale PID is never proof that a root is owned, and a PID naming a live
collector of a *different* root does not block an unowned root. The diagnostic
PID gate refuses only a live `archive.collector` started for this same root. The
next successful start reclaims a stale socket left by a dead owner. Any other
occupant of the socket path, and a symlinked, directory, socket, or other
non-regular `collector.lock`, is refused as `unsafe_root` before it is followed,
truncated, or replaced. `collector.lock` is opened `O_NOFOLLOW`, stays a `0600`
owner file, and is never unlinked or replaced, so every contender locks the same
inode.

`collector stop` is the documented stop for the matching root and socket. It
requests `shutdown`, waits briefly for the recorded collector PID, and escalates
to `SIGTERM` only when that PID is still a live `archive.collector`. It never
signals an unrelated process.

This is finite single-machine ownership for one account, not a distributed
lock or a same-account adversary defense. It does not repair the unrelated
root/socket stop mismatch: passing a socket from one root with another root's
PID metadata is still contradictory operator input.

## Interface

`interface_version` is `input-archive-v1`. `envelope_version` and
`content_version` are `1`. Import the public surface:

```python
from archive import Client, Producer, INTERFACE_VERSION
```

Later frontend (#189), daemon observation (#191), and legacy-history (#197)
work can use this surface without importing collector storage. #197 must not
treat this module as a reader of the old fact store; missing legacy fields stay
unknown.

Frame layout: 4-byte big-endian length, then UTF-8 JSON. Requests:

```json
{
  "interface_version": "input-archive-v1",
  "envelope_version": 1,
  "content_version": 1,
  "op": "status",
  "request_id": "example",
  "body": {}
}
```

Ops: `status`, `query`, `set_policy`, `checkpoint`, `admit_batch`,
`policy_observe`, `shutdown`. Unknown ops return `invalid_request`.

`status` reports `owner_pid`, the process currently serving this socket. It is
the collector's own pid and is content-free; `collector start` uses it to bind a
claimed success to the child it spawned.

### Admission

Input-path admission is `Producer.admit`. It copies an owned snapshot, checks
the size budget, and inserts into a bounded memory queue or refuses. It does
not serialize, compress, connect, flush, or wait for the collector, a full
queue, or a query/control lock. `durable` in the admission result is always
false. A background sender performs transport.

```python
producer = Producer("/abs/archive/collector.sock", source_instance_id="frontend-1")
result = producer.admit({
    "envelope_version": 1,
    "content_version": 1,
    "schema_id": "luna_pinyin",
    "source_instance_id": "frontend-1",
    "source_local_sequence": 1,
    "observation_kind": "commit_attempt",
    "process_id": "proc-1",
    "update_id": "u-1",
    "commit_id": "c-1",
    "outcome": "observed_attempt",
    "host_persistence": "unknown",
    "payload": {"text": "INV-NIHAO"}
})
```

`Producer.admit` refuses a missing `source_local_sequence` or an identity that
is not a safe token before enqueue. That result is `admitted=false`,
`code=invalid_request`, and `durable=false`. It increments the producer
`known_refused` count and is not a durable observation. A direct `admit_batch`
item with the same defect returns `invalid_request` and increments
`admission_refused_units`. Collector-accounted results, including
`identity_conflict`, are not counted again by the sender.

`source_instance_id` plus `source_local_sequence` identifies a capture attempt.
The same pair and the same content is an idempotent retry. The same pair with
different content is `identity_conflict`: the original stays, and the new
payload is quarantined or dropped if it cannot be stored. It is not a silent
replacement.

Missing or out-of-order `parent_update_id` values stay missing. Text, pid, and
timestamps are not joins. An observed commit attempt is not host persistence.
Query `host_persistence` is `unknown` and `host_persistence_proof` is false
even if the client sent another claim.

Supported observation kinds: `start`, `input_change`, `replacement`,
`temporary_selection`, `commit_attempt`, `cancellation`, `raw_finalization`,
`unavailable_client`, `unknown_outcome`. A commit with no stored intermediate
observations remains a commit and reports `missing_intermediate`.

`eligibility: excluded` records a content-free exclusion notice. Real
secure-field detection is not this slice.

### Policy

Initial desired policy is `off`, revision `0`. `set_policy` requires
`expected_revision`. A mismatch is `stale_revision` and does not write.
Acknowledgement scope is `collector_durable_desired_policy`: the durable desired
policy at the collector. It does not claim producer or global effectiveness.

```json
{
  "op": "set_policy",
  "body": {"desired": "paused", "expected_revision": 1}
}
```

`desired` is `off`, `enabled`, or `paused`. Resume is `enabled`. Pause survives
collector restart. Restart does not unpause and does not invent observations for
the paused interval. Policy changes, collector recreation, and known loss break
observed continuity.

Status separates `desired_policy`, `collector_effective`, and
`producer_observations` freshness. `globally_effective` is true only when
desired and collector-effective capture are enabled and every observed producer
is fresh at that revision. A saved request or a stale producer is not globally
effective.

A `policy_observe` call records the revision the caller **declares** in
`observed_revision`, not the revision that response delivers. A declaration that
is absent, negative, or not an integer is recorded as no declaration and never
matches. A delivered revision therefore does not acknowledge itself: after
`set_policy` raises the revision to 1, a caller still declaring revision `0` is
recorded at `0`, stays `matches_desired_revision=false`, and is not effective or
globally effective. That caller becomes acknowledged only when a later
observation reports revision `1`. A producer that starts before any
observation reports nothing and is stale until its first response is applied.

Scope is archive-only. Status always discloses
`legacy_selection_recording=separately_configured_may_continue` and
`legacy_switch_changed=false`. This module does not read or write the legacy
selection-recording switch.

### Query

Ordering is `durable_seq_ascending`. Cursor is the last returned `durable_seq`.
Pages are bounded by `page_size_max`. A larger request is `page_bound`.
Ordinary overview, timeline, status, and errors omit payloads. Private text is
returned only for `query` view `process` with `private_detail: true`.

Timeline summaries include incompleteness. They are not host documents.

### Errors

Error objects are `{code, message, retryable, content_included: false}`.
Messages are fixed and do not quote payloads. Stable codes:

`unsupported_version`, `unsupported_schema`, `malformed_frame`,
`event_too_large`, `capture_disabled`, `policy_not_effective`,
`stale_revision`, `identity_conflict`, `queue_saturated`, `capacity_stop`,
`storage_failure`, `collector_unavailable`, `unsafe_root`, `not_found`,
`invalid_request`, `page_bound`, `collector_already_running`,
`admission_refused`.

## Durability and loss

Captured and admitted positions are not durable positions.
`received_unpublished` counts queued and currently publishing units (including
an unresolved failed publication). `durable_seq` advances only at the
publication point:

1. Append complete JSONL lines.
2. Flush and fsync that file.
3. Write the new watermark to `state.json`, fsync it, and fsync the directory.

The pending watermark and index rows stay separate from the published prefix.
Status and queries continue to see the previous prefix during step 3; only its
successful completion installs the new watermark and rows together. No disk I/O
is performed under the admission/query state lock. If append/fsync succeeds but
watermark publication fails, the collector reports `storage_failure` and an
unknown tail without advancing the published prefix or inventing known drops.
Publication stops; restoring writable storage does not itself acknowledge or
publish that tail. Stop/restart preserves the last published prefix and restart
discards the unpublished bytes. A failed store can still prevent graceful stop;
fix the owned storage fault before restarting.

`checkpoint` is a bounded request followed by a status snapshot, not a guarantee
that every admitted unit is durable. A held or failed publication can return
the unchanged durable prefix with backlog/failure disclosed. Callers must check
the returned `durable_seq` and failure fields, not infer durability from `ok`.
Shutdown does not write a competing watermark if the publication thread has not
finished; neither an unresolved storage failure nor an unpublished observation
or quarantine tail is marked as a clean stop.

A crash before step 3 does not make those bytes durable. Restart truncates both
the observation log and the quarantine file to their durable watermarks,
reports `crash_tail=unknown`, and does not parse the discarded bytes into
observations or add them to `known_dropped_units`. A quarantine tail left on
disk is not omitted from capacity accounting; it is truncated back to
`quarantine_bytes` or the archive fails closed if the file is shorter than
that watermark. Only a provable
drop, refusal, or storage failure increments its own counter.

Known queue pressure is `known_dropped_units` / `queue_saturated`. Storage
failure and capacity stop are separate. Capacity stop refuses new archive
admission and does not overwrite or delete existing history. There is no
zero-loss guarantee and no frontend latency certification.

Under queue pressure the collector keeps self-describing commit, finalization,
cancellation, unavailable/unknown outcomes, and loss notices ahead of
intermediate observations when it can do so without blocking admission. Severe
pressure still refuses.

## Privacy

Archive roots are local and owner-only: directories `0700`, files (including
`collector.lock`, `collector.pid`, and the logs) and the socket `0600`. Unsafe
roots are rejected before writing: symlink components,
non-owner paths, and path components naming known synchronized destinations
(`CloudStorage`, `Dropbox`, `OneDrive`, `Mobile Documents`, `iCloud`,
`Google Drive`, `com~apple~CloudDocs`, `Box Sync`, `SynologyDrive`). The
collector does not traverse arbitrary external paths and does not upload.

Ordinary stdout, stderr, status, errors, and the contract report are
content-free. The TUI renders untrusted text as data and emits no C0/C1
control bytes from content. Collector, status, and TUI do not import or probe
inference, scoring, or a model. `inference_availability` stays `not_observed`.

Same-account compromise can read local plaintext. This slice does not claim
otherwise, and it does not claim universal sensitive detection.

## Limits and accounting

`durable_bytes` is the exact UTF-8 JSONL byte length, including newlines.
Quarantine bytes count toward the same capacity. Warning is
`durable_bytes + quarantine_bytes >= capacity * warning_ratio` before stop.
At capacity, new admission stops. These defaults are configurable engineering
choices, checked by the contract suite's page and capacity observations, not a
measured RAM ceiling or a retention period inferred from memory size.

`max_event_bytes` is enforced on the collector's canonical semantic encoding of
a prepared observation. The producer's input-path budget is a separate, cheaper
bound on the owned snapshot; it does not compute that canonical encoding and
does not serialize payload content. The two measurements can therefore disagree
at the boundary: an observation can fit the producer budget, be admitted
locally, and still be refused `event_too_large` by the collector. Neither
refusal is silent. A producer-local refusal is `admitted=false`,
`code=event_too_large`, increments the producer `known_refused`, is not a
durable observation, and is never shipped, so it is not also counted by the
collector. A collector refusal returns `event_too_large` in the batch `codes`
and increments `admission_refused_units`, which is the same counter that
accounts a direct `invalid_request` refusal. The refused item is absent from
query results; absence alone is not the evidence, the counter movement is.

DEFAULT producer_queue_count=256
DEFAULT producer_queue_bytes=1048576
DEFAULT collector_queue_count=256
DEFAULT collector_queue_bytes=1048576
DEFAULT max_event_bytes=65536
DEFAULT archive_capacity_bytes=67108864
DEFAULT warning_ratio=0.8
DEFAULT page_size_default=20
DEFAULT page_size_max=50
DEFAULT checkpoint_interval_ms=250
DEFAULT freshness_window_ms=2000
DEFAULT heartbeat_interval_ms=500
DEFAULT max_frame_bytes=4194304
DEFAULT batch_size=64
DEFAULT connect_timeout_ms=1000
DEFAULT management_timeout_ms=5000

## Diagnostic holds

`--publication-hold`, `--publication-phase-hold`, and `--control-hold` block
the real publication or control path on a FIFO read. They are off unless
passed. They do not enable capture. Phase hold sits after the observation
append and before the watermark, so a crash there is a crash before durable
publication.

## Test limitations

The contract checker drives this Interface with invented text in a ticket-owned
root. Its ownership pass starts real CLI and direct-entry subprocesses: two
concurrent starts per fresh root over five rounds, a seeded durable commit and
paused policy across a raced restart, an incumbent against a duplicate start and
the direct entry, a SIGKILL reclaim, one real socket-bind failure after
ownership, the lock artifact's alias/non-regular/mode/inode rules, and
different-root independence with the healthy start/admit/checkpoint/pause/
stop/restart flow. It counts fixture collectors by exact command line, so a
rejected child that never printed a PID is still counted; a stable repeated
sample supports the exclusion argument but is not a mathematical zero-race
guarantee. The checker does not prove real frontend behavior, p95/p99 input
latency, model application, ranking benefit, annotation, dataset export,
backup, deletion, or legacy-history access. Skipped required checks are
failures, not passes.

## Plugin observation

This section is the passive plugin path for Habit130/squirrel#190. Install and
merge do not enable capture. A running collector is not permission to record.
The legacy recording, evidence, and reranking switches are unchanged by archive
policy. Status still reports
`legacy_selection_recording=separately_configured_may_continue` and
`legacy_switch_changed=false`.

### Opt-in

Both are required before any candidate or commit text is admitted:

1. `llm_rerank/input_archive/socket` in the schema, an absolute local socket.
   There is no HOME default. A relative path, a symlink component, or a known
   synchronized destination stays off. Before connect, the socket's immediate
   parent must be an owner-only directory (no group or other permission) and,
   if the socket already exists, it must be an owner socket with no group or
   other permission. A world-writable or foreign parent is not a collector.
   Ancestors above that parent are checked only for symlinks and denied names.
   The scoring `socket_path` is not this socket.
2. A fresh observation that the collector desired policy is `enabled`. Initial,
   unknown, stale, `off`, and `paused` observations do not admit text. Freshness
   is 2000 ms from the producer's last policy poll. The poll runs on the worker,
   every 500 ms, not on the input path. An older in-flight poll cannot replace a
   newer observation.

`llm_rerank` and `llm_rerank_recorder` must both be registered for the full
passive path. The filter observes already-materialized competition and the
emission queue before it is spliced into the menu cache, so `emission_order`
is the order actually handed to the menu. With reranking off, the demand
wrapper does not pull upstream at construction; the menu's Peek/Next is the
pull. Commit, abort, and an empty-composition update flush those already
demanded candidates before composition state is cleared. The translation
destructor still flushes a window the menu released without a notifier.
Clearing the demand buffer first would drop competition and emission for a
completed composition. The recorder observes select, commit, abort, update,
and known immediate retraction through the existing notifiers. Subscriptions
are released with the owning component. This is not a new frontend integration
and not SYS-05/16 certification.

Only `luna_pinyin` content is admitted. Production direct input is
`ascii_composer` returning the key unhandled while `ascii_mode` is on and
there is no composition; that key never becomes an engine commit, so
`ObserveCommit` does not archive it. This is not a character-script filter.
Return raw finalization of a Chinese composition remains an engine commit
observation. Engine recreation allocates a new `ps<pid>eN` source instance
from a process-lifetime counter. Destroying an engine and creating another
does not reuse the old id.

### Representation

`interface_version` remains `input-archive-v1`. Envelope and content versions
remain 1. Plugin observations use the additive kind `plugin_observation` with
`plugin_observation_version` 1. An absent, non-integer, or other version is
`unsupported_plugin_observation`. It is not coerced to `unknown_outcome` and is
not a successful current semantic result. A `coverage=complete` claim is stored
only with basis `captured_group_members_and_target`, equal positive captured and
group member counts, and `target_membership` `present` or `absent`. Any other
complete claim, including a legacy snapshot boolean, is `invalid_request`.
Query repeats that check as `coverage_claim_accepted`.

`association_role=engine_entry_context` is an engine-entry property snapshot
(`squirrel_archive_source`, `squirrel_archive_process`, `squirrel_archive_update`,
`squirrel_archive_segment`, `squirrel_archive_association`). It is not this
operation's new frontend result update. `proves_current_frontend_result` and
`frontend_terminal` stay false / `unknown`. Query reports `valid_reference`
only when those tokens match a stored non-plugin observation, `stale` when the
process exists but the update does not, and `unmatched` otherwise. Missing or
malformed properties stay `absent` / `malformed` / `invalid`.

Stages: `competition`, `emission`, `temporary_selection`, `commit`,
`cancellation`, `retraction`, `loss`, `exclusion`. Apply states: `applied`,
`unchanged`, `fallback`, `not_applicable`. `unchanged` means a plan was applied
and emission order matched upstream order. That is not ranking benefit.
`lm_request_state` is `issued_succeeded`, `issued_failed`, or `no_request`.
The request id is the native scorer id from the exchange that was actually
attempted. Evidence request ids, pid, time, and equal text are not substitutes.
No request id is stored when no LM request was issued.

Weight is `phrase.weight` in log space when the candidate is a system or user
dictionary word. Quality is `candidate.quality` in probability space. LM score
is the protocol v2 raw log score before alpha, only for candidates in a
successful exchange. Retrieval evidence is the evidence term in log space, only
when that evidence call succeeded. Unavailable components are `unknown`, not a
fabricated zero. Overlapping spans and different categories stay separate
groups. A truncated window or a legacy complete flag is not group-complete
competition.

### Bounds, faults, and continuity

The input path copies an owned snapshot and `try_lock`s the producer queue. It
does not serialize, compress, connect, read, wait, or retry. The worker does
transport. Retries of a retryable send are at most 3, on the worker. A failed
loss-notice send is restored to that same bounded queue; it is not discarded.
The collector keeps `observation_kind=loss_notice` even when the notice carries
no content. It is not rewritten to an exclusion notice.
After the retry cap, one continuity notice is held and delivered on the next
successful policy exchange or content send. That is not a tight retry loop,
and a generation change or abandon drops it instead of retargeting it. Queue
count 256, queue bytes 1048576, event budget 65536, batch 64. A failed
`try_lock` refuses `queue_saturated`. Commit, cancellation, retraction, loss,
and exclusion outrank competition and emission snapshots.

A held publication, absent collector, saturated queue, capacity stop, or
blocked control call must not stop emission, selection, or commit. The fault
watchdog is 2000 ms. It detects a dependency; it is not a p95/p99 certification.
No quiet-machine or plugin-cost certification is claimed. #189 timing is
frontend evidence only.

Pause survives producer recreation because policy is durable in the collector.
A commit or cancellation while the producer is not locally effective — paused,
off, stale, or not yet observed — is an excluded prefix. Its text is not
retained for a later retraction, and resume does not backfill that text.
Resume does not backfill any other excluded prefix either. Retarget and
destruction drop queued snapshots instead of sending them to a new socket. Engine recreation
uses a new process-lifetime source instance; a destroyed engine's id is not
recycled. Schema, secure input, and an ineligible prefix cut continuity. Secure input uses `IsSecureEventInputEnabled` when it can be
resolved; if that gate cannot be resolved, text is not admitted. That is not a
universal sensitive detector. Invalid frontend association is not sensitivity
clearance. Archive failure must not terminate input: sockets set
`SO_NOSIGPIPE`, and a refused admission is not a commit failure.

### Checks

From the plugin checkout, after an isolated `make librime` in the Squirrel
build host:

```sh
"$PYTHON" tools/check_input_archive_plugin.py --self-test \
  --root "$RUNTIME/p-self"
"$PYTHON" tools/check_input_archive_plugin.py --suite contract \
  --native-build "$HOST/librime/build" \
  --root "$RUNTIME/pc/run" \
  --report "$EVIDENCE/plugin-report.json"
```

`--self-test` requires an explicit fresh root. It does not fall back to an
older attempt directory. The contract suite derives its native workspace from
the root's parent, so keep that parent separate from the self-test leaf.

The checker is an orchestration entry, not a replacement plugin. It binds the
built dylib and source, runs the registered native observation cases, and
preserves primary evidence. Ordinary status, errors, and the report are
content-free. Private text is only in a deliberate detail query. Stop only the
collector that check started:

```sh
"$PYTHON" -m archive.cli --root "$ROOT" --socket "$ROOT/collector.sock" collector stop
```

This slice does not certify pixels, host persistence, ranking benefit, added
plugin cost, or integrated SYS acceptance. **Merge never enables capture.**
