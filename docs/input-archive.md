# Input archive

Isolated recording/management foundation for Habit130/squirrel#188. This
delivery records and browses invented `luna_pinyin` observations. It does not
hook real input, score candidates, load a model, or enable capture on install
or merge.

CLI and TUI are Adapters. They call the Interface below and do not open
observation storage.

## Verified backup and explicit historical restore (#195)

`input-archive-management-v1` is an additive collector-owned management Interface.
It does not import models, score, alter the legacy fact domain, enable capture,
restart producers or deploy an input method. The desired archive policy remains
separate from management and producer availability. **Merge never enables capture.**

### Source registration and the supported cutover

The collector durably registers a safe source ID through the existing
`policy_observe` Interface before returning a usable enabled policy. A direct
unregistered `admit_batch` cannot register itself: each item is refused with the
existing terminal `invalid_request` code understood by native producers. Sources
already present in published history are inventoried at the initial cutover.
Producer/source wire formats are unchanged. Direct synthetic clients must first
call `policy_observe` for their actual `source_instance_id`; the contract-checker
fixture client performs this explicit setup over the same Interface.

Native and Python queues do not carry capture-time serving generation. A policy
repoll alone cannot establish that delayed queued content was captured after a
restore. Consequently **all pre-switch registered/known source IDs are permanently
fenced at restore**. Admission, registration and the serving switch have one
coherent ordering; accepted unpublished work makes restore busy, rather than
being silently swept into the replacement. Fences survive policy resume, collector
restart, repeated historical restoration and source-ID reuse. No fenced ID is
evicted to make room. Source IDs not previously registered are not retrospectively
classified using timestamps, PIDs or text; a new producer must establish the
supported current registration boundary. This is not a same-account forgery
defense.

An already-running producer **cannot resume capture merely by polling/resuming**.
Producer recreation with a genuinely new source identity and current registration
is required. A fenced poll returns non-enabled `desired_policy=off` to the existing
producer, `registration_code=source_recreation_required`, and the separately named
`current_desired_policy`. The durable current off/paused/enabled policy and revision
are not changed to hide the fence. Status counts fenced sources, marks their
observations ineffective, and does not claim globally effective enabled capture.
Management CLI/TUI disclose the recreation requirement; no automatic input-method,
plugin, daemon or service restart is performed.

### Snapshot scope and private layout

`backup preview` is `Client.management("preview")`. Its content-free plan binds
the historical archive identity, published durable sequence/byte prefix, retained
annotation revision/chain, dataset frontier, current serving generation, collector
epoch, policy revision, versions/code identity, relative file names, sizes and
SHA-256 checksums. It includes published observations, published quarantine bytes,
quality/incompleteness state, annotation identity and complete retained history,
and successful registered dataset job/manifest/output bytes and dependencies.
Incomplete dataset content copies are explicitly inventoried as excluded with
their lifecycle, bytes and integrity. No partial/failed/cancelled dataset is promoted.
This is a published-new-archive backup, not a full filesystem/domain backup.

Excluded: unpublished queue/crash tails, locks/sockets/PIDs/logs, derived caches,
legacy facts/semantic state/traces/old datasets, models/tokenizers/unrelated files,
and other management backup/retained payloads. There is no recursive backup of
backups. Current capture policy and non-rollback registration/fence authority are
not historical restore payloads. A busy publisher, unpublished tail, incompatible
dependency, advancing frontier or over-bound inventory yields an explicit refusal.
Later append is never silently added to an already confirmed plan. Long scans,
copy and verification use bounded buffers outside the admission lock.

All management roots are beneath the validated private owner root:
`management/jobs/<hashed-operation-id>/backup/` for immutable successful backups;
`.../restored/` for a distinct mutable restored serving incarnation. Directories
are `0700`; files are regular, single-link owner `0600` files. Supplied plans never
resolve arbitrary paths: the collector recomputes their entire supported plan
before mutation. Symlinks, hardlinks, unsafe ancestors/cloud roots, foreign modes,
FIFOs/sockets/devices and manifest escapes are refused before opening/mutation.
Verify never chmods or repairs an input. Private plaintext is not a sandbox against
same-account compromise, and backup artifacts are not public report attachments.

### Jobs, semantic verification and immutable retry

`management create` acknowledges a fsynced request descriptor, **not completion**.
IDs hash the owner namespace and operation ID; request digests bind the plan and
explicit restore choice. Identical retries return the existing durable result;
conflicting reuse refuses without overwrite. Pending/running/succeeded/failed/
cancelled/unknown, actual copied bytes/files, irreversible phase and cleanup are
separate fields. List and registry are paginated. Closing/detaching CLI/TUI does
not cancel or repeat a job. Explicit cancellation is supported before commit;
after commit it is refused (`management_committed`). Interrupted precommit jobs
recover as unknown/incomplete, not successful artifacts, and remain registered.

Each new content file is reserved in `job.json` before creation. Backup success is
the fsynced atomic descriptor publishing the complete immutable file/dependency
registry. Staging, partial, cancelled and retained/replaced copies keep their own
honest lifecycle. Registry `replaced/...` references are owner-relative to the
descriptor's explicitly recorded `old_content` root, not an arbitrary alias.
An active restored copy's initial checksum is labeled
`active_initial_snapshot_checksum`; it is not a claim that later capture leaves a
mutable serving file byte-identical. Lineage is input for #196, not deletion authority.

Verify reads only the selected registered backup: exact manifest/versions/code,
safe file set/checksums, publication sequence/offset, original archive identity,
annotation chain/source references, and recomputed dataset source/annotation/
partition/admission/output semantics. Its original live source may be absent.
It never substitutes today's source, normalizes bytes or loads a model. Empty is
legal. Unsupported, corrupt/tampered, unavailable, incomplete and bounded outcomes
are not successful semantic availability. Compatibility is exact, including the
dataset tool's existing code identity; older incompatible code is reported, not
upgraded by assertion or migrated. SHA-256 is deterministic for the exact pinned
file bytes. A plan/content identity additionally binds its versions and snapshot
metadata; it is not a text-only hash invariant across collector epochs. Operation
IDs/job status/progress are outside immutable backup contents. A changed registry
frontier is a different declared snapshot, even when raw observation bytes match.

### Restore confirmation, retention and recovery

`restore_preview` fully verifies the selected backup and binds the current target
frontier, serving incarnation, desired policy revision and managed inventory.
`restore_confirm` requires that complete plan, `confirm=true` and exactly one of
`retain-current` or `discard-replaced-current`. No default choice, automatic hidden
backup, merge or unconfirmed-later-input overwrite exists. Bad/capacity/busy/stale
preflight leaves current content/policy/binding intact. The staged copy is validated
before the switch and the confirmed frontier is rechecked under the shared
reader/writer/registration/publication transition gate. Input-path admission never
waits for that gate; it is boundedly refused during the switch.

The sole irreversible restore point is the fsynced atomic `management/control.json`
serving-pointer, generation and permanent source-fence commit. Its owner namespace
is anchored outside replaced content in `management-namespace.json` and the current
policy metadata. Missing/corrupt/incompatible authority cannot become an empty
successful namespace. Crash before commit preserves complete old serving content;
after commit restart loads the complete staged generation and resolves that same
operation, not a second restore or rollback. Ambiguous fsync/load failures report
unavailable/unknown until restart; shutdown does not publish an old in-memory state
over a possibly switched generation. No discarded state is resurrected.

Retain-current registers the exact old bytes in place: ownership transfers, with
no hidden second plaintext copy. Discard authorizes only the six confirmed replaced
new-archive core files. Independent dataset bytes, backup payloads, policy, authority,
unrelated files and directories are not deleted. Retained dataset copies whose
source was discarded are explicitly source-unavailable; they do not become a new
default training candidate. Failed cleanup remains a registered residual with
`incomplete_registered_residuals`, not falsely gone. Desired off/paused policy and
revision survive restore and restart. A fresh continuity boundary follows restore;
no paused/refused/unknown interval is backfilled.

Historical crash-tail/loss/discard metadata is separately reported as bounded
`management.restored_source_quality` (at most 128 point summaries), not replaced
with the new collector's clean/current-tail label. Cleanup retries recheck each
confirmed old file's exact size/checksum; a later different file at that name is
left untouched and reported `changed_replacement_refused`. After cutover, use the
compatible collector for this namespace: downgrading to a collector that ignores
the serving/fence authority is unsupported and must not be used to bypass fences.

Historical archive/source/observation IDs remain original. Query cursors still bind
collector epoch. After restore, content query/annotation/edit/dataset requests must
also explicitly bind `serving_generation`; absent/stale bindings refuse rather than
retarget old edits to reused IDs. `Client.serving_generation` and CLI global
`--serving-generation N` supply that non-producer binding. TUI explicit Overview
refresh clears stale selections on a generation change; restore acknowledgement
does not implicitly refresh an old edit selection.

### Management commands and finite bounds

```sh
"$PYTHON" -m archive.cli --socket "$SOCKET" management preview
# Save the bounded content-free preview response to an owner-only private plan
# file, or feed it through stdin. No private text is required in process argv.
"$PYTHON" -m archive.cli --socket "$SOCKET" management create \
  --operation-id example-backup --input-file "$PLAN"
"$PYTHON" -m archive.cli --socket "$SOCKET" management status --job-id "$JOB"
"$PYTHON" -m archive.cli --socket "$SOCKET" management verify --job-id "$JOB"
"$PYTHON" -m archive.cli --socket "$SOCKET" management restore-preview --job-id "$JOB"
"$PYTHON" -m archive.cli --socket "$SOCKET" management restore-confirm \
  --operation-id example-restore --input-file "$RESTORE_PLAN" \
  --retention retain-current --confirm
```

Other actions: `list`, `registry`, `cancel`, `availability`. The minimal line TUI
supports `management`, `backups`, `backup-preview`, `backup-create OP`,
`management-status/verify/cancel/registry JOB`, `restore-preview JOB`, and
`restore-confirm OP retain-current|discard-replaced-current confirm`. It stores
only bounded metadata plans, never a second text archive. All errors/statuses
are content-free and terminal-escaped; deliberate existing private detail remains
explicit and bounded.

Bounds: 64 KiB copy buffer; 8 MiB descriptor; 2 GiB total planned copy bytes;
8192 files; 128 management jobs; 32 metadata rows/page; 65,536 observations and
65,536 annotation revisions per snapshot; 8192 non-evicting source registrations/
fences and 2 MiB authority bytes. Existing dataset item/group bounds still apply.
Transport frames remain bounded by the existing Interface. Exhaustion is an explicit
refusal, never truncation, fence recycling or a free-space deletion job. The checker
reports actual 256/4096 mixed-source copied bytes, processed files, fanout and elapsed
work; fixed copy-buffer bounds are not total-RAM independence or latency certification.

```sh
"$PYTHON" tools/check_input_archive_management.py --self-test
MGMT195_NATIVE_BUILD="$HOST/librime/build" "$PYTHON" \
  tools/check_input_archive_management.py --suite contract \
  --root "$RUNTIME/management/run" --report "$EVIDENCE/management.json"
```

The real source-built `llm_rerank_management_producer_probe` links the production
native producer object and uses only its existing diagnostic queue controls.
Old delayed commit/receipt-dependent payloads, repoll, restored persisted absence,
fresh recreated producers, both retention paths, restart/faults, private Adapters
and bounds are finite controls, not alternate producers or stronger losslessness
claims. Keep unique command/log/report paths, including failed/partial probes.
Never overwrite prior evidence or claim missing historical log bodies were retained.

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

Capture starts disabled. A merge does not enable capture. The foundation does
not certify frontend latency or ranking benefit. Versioned human annotations
are the separate additive surface documented below; export and the five-view
TUI remain outside this delivery.

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

The `daemon` view is the passive last-observed daemon state; see "Daemon
observation". It reads durable daemon observation summaries at the published
watermark and never queries or probes the daemon.

`overview`, `timeline`, `process`, `losses`, `timing` and `choice` share one
versioned join/aggregate semantic layer, `input-archive-query-v1`; see the next
section for its bounds, relations, denominators, timing and choice rules. The
CLI and TUI call those views and do not import storage.

## Query Interface (input-archive-query-v1)

`input-archive-query-v1` is the additive semantic layer for the query surface.
It is carried in the `body` of `input-archive-v1` responses; it is not a new
frame version. Supported versions are exactly `input-archive-query-v1`; any
other version in a cursor is `unsupported_query_version`. Views:

| View | Read | Notes |
| --- | --- | --- |
| `overview` | published prefix | Honest counts, timing summary, storage, freshness |
| `timeline` | pages | Bounded page of durable rows with relation reads |
| `process` | pages | Deliberate process detail; the only private content view |
| `choice` | full run, bounded | Per-group choice projection for one process |
| `timing` | published prefix | Operation-separated frontend timing distributions |
| `losses` | pages | Loss notices only |
| `status` | collector state | The durable policy/capacity snapshot |
| `daemon` | published prefix | Passive last-observed daemon state |

Filters: available observed time (`since_ms`/`until_ms`), source instance,
process, segment, observation kind and observed outcome state. An unavailable
field is reported unknown, never invented: a row whose observation time is
missing does not match a time filter, a filter value outside the safe token
alphabet is refused with `invalid_request`. Empty strings on text filters
(`process_id`, `source_instance_id`, `segment_id`, `observation_kind`, `state`,
`application`, `group_id`) mean omission, not a value matching nothing.
Time bounds require numeric values (not bool, empty strings, NaN or ±Infinity);
non-finite bounds are refused before comparison, fingerprinting or echo, so
responses contain no non-standard JSON numeric tokens. A filter naming a field
this archive never observes (application metadata) is refused rather than
silently matching nothing. Every supported row filter applies before any
aggregation or pagination: `overview`, `timing`, `timeline` and `choice` count
and page only the filtered rows, including the `process_id` scope in the
legacy views; the response echoes `filters_applied`, and the fingerprint binds
the same scope into the cursor. The `process` view is process-scoped and
refuses a request without a usable process filter. `choice` also accepts
`group_id`, which projects exactly that captured group (so a requested group is
returned even when the unfiltered projection would truncate first).
`group_id` is refused with `invalid_request` on all non-choice data views
(`overview`, `timing`, `timeline`, `process`, `losses`); it is never echoed as
an applied but inert filter.

Bounds. `page_size_max` (default 50) bounds a page; a successful non-private
page of a bounded query view (`op=query` with view `overview`, `timing`,
`choice`, `timeline`, `process` or `losses`) is refused with `page_bytes_bound`
when its encoded response exceeds `query_page_bytes_max` (default 1 MiB)
instead of silently delivering an oversized page. The bound never applies to
startup or management/control responses (`status`, `set_policy`,
`checkpoint`, `admit_batch`, `policy_observe`, `shutdown` and the top-level
`overview` snapshot op), to the fixed-shape `status`/`daemon` query state
reads, or to refusals: a refusal keeps its own code. Any accepted positive
`query_page_bytes_max` (including 128) therefore starts the collector and
keeps those operations working; it only limits pages. Deliberate private
detail and every unbounded response are bounded by `max_frame_bytes`.
Expansion bounds are
`query_timing_rows_max` (4096), `query_choice_groups_max` (64),
`query_group_members_max` (256) and `query_high_fanout_updates_max` (512).
The high-fanout bound caps the rendered owner evidence of a reused token: the
response keeps the total count and sets `owners_truncated` with
`owners_truncation_reason=query_high_fanout_updates_max`; the other bounds
report their truncation reason per response (group bound, member evidence,
timing rows). Join/aggregate state is a rebuildable bounded index maintained
incrementally as rows are published (the identity-owner and daemon
request/plan maps; a declared row width times rows for the derived estimate),
plus per-request streaming over the published prefix; no query loads the whole
payload history, re-derives the joins over the history, or holds the admission
lock over a disk scan.
Each distinct owner/plan edge retains its first durable witness sequence, not
an unversioned membership bit. Prefix projection includes only edges with a
witness at or below the watermark; update witnesses and daemon request-row
lists are also prefix-filtered. Persistent relation state is O(E + U + R),
where E is distinct owner/plan edges, U distinct update tokens and R request
witnesses (each at most a constant multiple of durable rows N). Prefix
projection does O(E + U + R) metadata work and temporary state; existing page
selection/summary context does O(N) index-metadata work/state, without reading
payloads except deliberate bounded private detail. No per-token or per-prefix
map copies are retained, so cursor count adds no persistent relation state.
The checker reports collector RSS before/after ingestion and after query
iteration, plus total iteration time at 256/4096 rows; these are observed
resource figures, not a total-RAM-independent or quiet-machine latency claim.

Cursors. A `cursor_token` is an opaque `q1.` base64url token naming the view,
the canonical filter set, the snapshot (`as_of_durable_seq`) and the collector
epoch. It is rejected with `invalid_request` when it names a different view or
filter set, and with `cursor_snapshot_unknown` when it names an unpublished
position or a previous collector epoch (restart). Snapshot data is immutable:
the same token and pagination parameters return the same observations **and
semantic relations** while the epoch is unchanged, and a
continuation reads the token's own as-of prefix rather than whatever has been
published since, and the response's nested blocks (for example the timing block
nested in an overview) carry that same snapshot label. `next_cursor` is the last returned `durable_seq` and
continuation repeats no record and omits none inside the snapshot. Append, a
held publication or a restart cannot leak unpublished work: reads always see
the durable prefix only, and `received_unpublished` stays a separate figure.
For `overview`, `snapshot_scope` names the pinned population/inclusion/stage/
timing/outcome/slice data. `response_time_state` explicitly identifies
`quality`, `storage` and `freshness` as sampled at response time, not frozen by
the token: live counters, policy, capacity, published/pending watermark and
ages may advance. These mixed-state blocks are outside `snapshot_lifetime`;
their observation-derived subcounts still use the declared prefix. The token
does not freeze wall clocks, capacity or producer activity.

### Identity relations

Every timeline/process row carries a `relations` object with an explicit
status and basis, and a `relations_summary` count map. Statuses used:
`valid`, `stale`, `unmatched`, `not_observed`, `absent`, `unknown`,
`conflicting`, `ambiguous`, `unknown_owner`, `malformed`, `invalid`,
`not_issued`, `linked`. Joins never use nearest time, text equality, PID,
arrival order or a plan digest alone.

- Capture identity is `source_instance_id` plus `source_local_sequence`. A
  retry with the same pair and content is one observation, not two; the same
  pair with different content is `identity_conflict` and does not replace the
  original.
- `parent_reference` resolves an absent/missing `parent_update_id` against
  durable records at this prefix. An out-of-order record can resolve it at a
  later prefix; an earlier snapshot is never rewritten, only re-read.
- `process_identity`/`commit_identity`/`segment_identity` resolve exact tokens
  scoped to their owner source. A token recorded under several owners keeps
  its owners visible and is never silently merged.
- `association` resolves the plugin's declared `engine_entry_context`
  reference (`valid`, `stale`, `unmatched`, `absent`, `invalid`,
  `malformed`, `unknown_owner`). It is a snapshot of the frontend entry
  context: `proves_current_frontend_result` stays false and `frontend_terminal`
  stays `unknown`; a valid reference asserts owned references only.
  When an update token has multiple owners, an exact declared source/process
  pair resolves against that owner's first witness at this prefix, not the
  first unscoped token witness. A different owner's earlier record is not
  evidence that the exact recorded relation is stale.
- `request_identity` and `plan_identity` associate an issued plugin exchange
  with daemon observations by the native request id (`linked`, `unmatched`,
  `ambiguous`, `conflicting`, `not_issued`). A plan digest that several
  requests claim, or daemon rows that disagree on one request's plan, stay
  conflicting. Substituted or failed exchanges keep their issued request id.
- Collector per-item admission acknowledgements are `durable:false`; a
  post-admission eviction yields `known_dropped_units` and a continuity break,
  which is not necessarily a loss-notice row, and no exact cause is claimed
  for a missing reference. There is no reconstruction and no zero-loss
  guarantee.

### Stage, group and denominator semantics

Computed scoring (daemon `scoring` outcome), plugin emission
(applied/unchanged/fallback/no-request), frontend update-call completion and
commit attempts (`observed_attempt`/`raw_finalized`/`cancelled`/
`unavailable_client`/`unknown`) stay distinct. Successful daemon scoring alone
proves none of plugin application, frontend presentation, host persistence or
ranking benefit; `host_persistence_proof`, `application_proof` and
`ranking_benefit` stay false. `applied` with `emission_matches_upstream: true`
is an applied plan, not a benefit; order change is not correctness.

The overview counts one unit per capture identity (source instance plus
source-local sequence) and collapses same-identity retries; every other unit
keeps its own bucket. Numerators and denominators are explicit per figure, and
unknown sources remain in the eligible population rather than disappearing to
improve a rate. Known drops, refusals, capacity stop, storage failure,
identity conflicts, crash-tail state (`unknown` when the tail cannot be
classified), discarded bytes, desired/effective policy and producer freshness
are separate figures. Storage distinguishes managed archive/quarantine bytes
from derived index bytes; growth is a rate only from two declared comparable
samples with an elapsed interval, otherwise `growth: null` with a reason.

Freshness is last-observed state with a source and basis, never current
residency: producer freshness comes from the producer poll and the published
prefix, `received_unpublished` is the pending admission figure, and passive
reads (`daemon` view, `overview`, `timing`, `choice`) never query health or
score, never import MLX or load a model, and never extend model activity. There
is no periodic forced probe.
Non-finite stored observation times do not yield an age: overview reports
`last_observation_age_ms: null` with
`publication_age_basis: durable_observation_has_nonfinite_client_observation_time`.
This query projection leaves the original observation unchanged.

### Frontend timing and choice projection

A `provenance` row with `stage: frontend_timing` carries
`payload.frontend_timing` version 1. The projection parses that actual
declared schema: an object with an unknown key, a wrong-typed field, a
non-integer timebase, a bounded-fold violation, a bad update-call or
commit-call shape, or an unsupported version is refused at admission with
`invalid_request` — as is a nonempty primary `endpoint` outside the v1 domain
(`marked_text`, `panel_update`, `unavailable`): `unsupported_frontend_endpoint`.
Declared `action`/`operation` must be strings, including when explicitly null:
wrong types are refused (`timing_action_type`/`timing_operation_type` parser
reasons, public admission code `invalid_request`). Absent optional labels
retain the existing missing/unknown projection (missing operation goes to the
`unknown` bucket); they are not coerced from supplied wrong-typed labels.
A well-typed object is stored canonicalized and its value re-derived from
`entry_ticks`, `endpoint_ticks` and the object's own timebase with
overflow-safe integer math. A declared `duration_ns` is compared, not trusted:
a mismatch, a non-monotone endpoint, a zero/negative/absent endpoint, an
unrepresentable conversion or a declared `unavailable` endpoint yields
`validity: invalid`/`unknown` with an explicit `unknown_reason`, never a zero
latency. The declared primary endpoint must also be the operation's own last
completed update call: a `marked_text`/`panel_update` endpoint with no
completed call for that endpoint is invalid (`missing_primary_completion_call`),
a tick value that is not that call's completion is
`primary_endpoint_not_completed_call`, a later completed call than the declared
one is `primary_endpoint_not_last_completed_call`, and an `unavailable`
endpoint with completed calls is
`endpoint_unavailable_with_completed_calls`. The primary figure is the
operation-separated interval from the real action entry to the last
`marked_text`/`panel_update` call completion; `commit_call` is a separate
interval. A valid standalone frontend interval is retained when backend phases
or association rows are absent, and association quality is disclosed
separately. Percentiles use the documented
`nearest_rank_ceil_p_n_first_observed_value` method over observed integer
nanoseconds, with p50/p95/p99 when samples exist and a small-N disclosure
below 20 samples; there is no SLA or statistical-adequacy claim. Overview
counts the same canonical samples: `frontend_timing_valid` agrees with the
timing view's valid samples for the same snapshot and filter, and
`frontend_timing_invalid`/`frontend_timing_unknown`/`frontend_timing_unavailable`
keep every other declared action visible in its own bucket (an action with no
usable payload is `unavailable`). Old flat
timing, #189 measurement scopes and backend daemon times are never mixed into
this total. Available daemon scoring/load/unload durations keep their true
scope (`scoring_ms` may include the load; no fabricated materialize/wait
subphases, no summing overlapping durations), and the mach-absolute_time
frontend clock, the daemon-relative millisecond clock and the wall event/
observation clocks remain distinct: no cross-process clock subtraction invents
a phase or an event-queue wait, and `event_queue_wait` stays `unknown`.
Cold/hot/idle-resumption/application/input-size slices are reported as an
explicit `not_observed` summary with those named unknown buckets; no slice is
inferred from timing, PID, text or arrival order.

`choice` projects per captured rerank group (span AND category, source/window/
group identity) with captured member evidence, coverage basis, target
membership, request/stage evidence, submission provenance, eligibility and
explicit reasons. Only a plugin observation with the complete scoped identity
(source instance, `window_id` and `group_id`; `identity_rule` is
`scoped_source_window_group_required`) joins a group, whose
`group_identity.status` is `scoped`. An observation missing any of them is
never merged by its absent keys: it is listed in `unidentified_observations`
as its own per-observation entry (`durable_seq`, observed IDs,
`group_identity.status` `missing` when both window and group are absent,
otherwise `partial`, and the `missing` field names) with
`coverage_claim_accepted=false`, no member evidence, completeness
`scoped_group_identity_unavailable` and `evidence_permitted=false` with
`evidence_not_permitted_reason=scoped_group_identity_required`; it never
borrows another observation's coverage. `unidentified_observations_total`
counts every such observation; the list has its own
`query_choice_groups_max` bound (`unidentified_observations_truncated`,
reason `choice_group_bound`) and never crowds identified groups out of
`groups`. A `group_id` filter matches the observed group value in both lists.
The CLI JSON omits the `groups` key under the existing content-key rule and
renders the same `unidentified_observations`, cursor and snapshot fields.
Completeness is accepted only with
`captured_group_members_and_target` basis, equal positive captured/member
counts, target `present`/`absent` and no truncated-window marker; a
whole-window flag, a candidate-count shortcut, a legacy complete boolean or a
truncated window is refused or reported as incomplete, never accepted.
`evidence_permitted` marks groups a dataset step could consume. An explicit
committed preference is not human correctness, a default submission is weak,
cancelled/retracted/raw/unavailable/unknown outcomes never become default
positive labels, and unselected is not negative. This delivery writes no
annotation, dataset, partitioner, freeze or training step.

### Query reproduction

From the plugin checkout, with an isolated `make librime` in the Squirrel build
host and an own source export staged at
`$HOST/librime/plugins/llm-rerank`-style path (`librime/plugins/llm-rerank`):

```sh
"$PYTHON" tools/check_input_archive_query.py --self-test --root "$RUNTIME/q-self"
"$PYTHON" tools/check_input_archive_query.py --suite contract \
  --frontend "$HOST" --native-build "$HOST/librime/build" \
  --root "$RUNTIME/query/run" --report "$EVIDENCE/query.json"
```

Use a short runtime root: the accepted frontend and the fixture daemon connect
and bind with the full socket path, and the collector requires its socket
inside its own archive root, so a root whose fixture socket paths exceed the
macOS `sun_path` bound is refused with `socket_path_too_long_for_frontend`
rather than worked around.

The contract suite drives the versioned Interface over a genuine collector with
invented fixtures at the 256 and 4096 observation scales, then compiles the
read-only accepted Squirrel frontend against the source-built librime and the
final plugin source export, runs the production controller/plugin chain and a
model-free fixture daemon request handler, and inspects the shared Interface
outcomes and persisted frontend timing rows. The fixture daemon answers with a
deterministic in-process scorer: that proves association and handler transport,
never actual MLX phases or model performance. `--self-test` is supplementary;
a skipped required case fails. The historical frontend timing checker at
`$HOST/scripts/check-input-archive-frontend-timing.py` keeps its own pinned
backend and result; this suite does not relabel it, edit it or treat it as
current-backend evidence.


### Errors

Error objects are `{code, message, retryable, content_included: false}`.
Messages are fixed and do not quote payloads. Stable codes:

`unsupported_version`, `unsupported_schema`, `malformed_frame`,
`event_too_large`, `capture_disabled`, `policy_not_effective`,
`stale_revision`, `identity_conflict`, `queue_saturated`, `capacity_stop`,
`storage_failure`, `collector_unavailable`, `unsafe_root`, `not_found`,
`invalid_request`, `page_bound`, `collector_already_running`,
`admission_refused`, `unsupported_plugin_observation`,
`unsupported_daemon_observation`.

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
DEFAULT query_page_bytes_max=1048576
DEFAULT query_timing_rows_max=4096
DEFAULT query_group_members_max=256
DEFAULT query_choice_groups_max=64
DEFAULT query_high_fanout_updates_max=512

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

Admission results are per item. The worker parses the ordered `codes` array of
the `admit_batch` reply and binds each code to the matching outstanding
observation in the same batch and binding generation. Only `admitted`, or the
collector's same-identity/same-content `duplicate`, establish semantic
admission; `capture_disabled`, `event_too_large`, `invalid_request`,
`unsupported_version`, `unsupported_plugin_observation`, `capacity_stop`,
`storage_failure`, `identity_conflict`, and `queue_saturated` are definite
refusals and are terminal for that observation. A reply whose per-item result
is missing, malformed, or not exactly one code per item stays unknown; unknown
content is not replayed and never becomes admitted. Envelope `ok:true`,
transport success, queue position, counters, or a fresh local policy snapshot
are not admission.

Commit text is not retained by the session for a later retraction. A locally
eligible commit registers at most one bounded worker-owned receipt (count cap
8, oldest evicted); the immediate BackSpace queues a content-free reference
intent. The worker sends that retraction only after the exact originating
commit's per-item result resolved as admitted or same-content duplicate, and
it attaches only that commit's approved content. A refused, unknown, absent,
evicted, retargeted, or generation-mismatched result degrades the intent to a
content-free exclusion notice (`retraction_commit_refused` or
`retraction_commit_unknown`), and a later reply cannot revive it. Receipt
payload content exists only for admitted commits and is released when the
dependency is consumed or evicted. A pending intent does not wait on the
input path; it waits inside the worker-owned queue, and an unknown result is
bounded by the same retry and loss rules as any other observation.

A held publication, absent collector, saturated queue, capacity stop, or
blocked control call must not stop emission, selection, or commit. The fault
watchdog is 2000 ms. It detects a dependency; it is not a p95/p99 certification.
No quiet-machine or plugin-cost certification is claimed. #189 timing is
frontend evidence only.

Pause survives producer recreation because policy is durable in the collector.
A temporary selection observed while the producer is not locally effective —
paused, off, stale, or not yet observed — is an excluded prefix, exactly like
a window or demand observation: the tentative selection is cleared, its text
is not admitted, and resume does not backfill it into a later commit. A commit
or cancellation while the producer is not locally effective follows the same
rule. Commit text is not retained by the session; a later retraction is a
content-free reference resolved by the worker against the collector's
per-item result. Resume therefore backfills neither a locally excluded commit
nor a commit the collector refused per item — for example `capture_disabled`
while a pause races a still-fresh local policy snapshot. Retarget and
destruction drop
queued snapshots and receipts instead of sending them to a new socket. Engine
recreation
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

The native `llm_rerank_test` fixture asserts its own workspace socket-path
bound (`< 104` characters for `lm.sock`), so a build tree under a long host
path must run it with a short owned workspace, for example
`LLM_RERANK_ARCHIVE_WORKSPACE=<short-runtime>/native make -C librime test`.
That is an environment requirement of the fixture, not a skipped case.

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

## Daemon observation

This section is the passive daemon path for Habit130/squirrel#191. It observes
actual scoring requests, effective scoring conditions, completed work and
lifecycle through the same archive Interface. Install and merge do not enable
capture; a running collector is not permission to record, and the daemon
scoring wire, scoring results, deadline, fallback and idle policy are
unchanged.

### Opt-in

Both are required before any daemon content is admitted:

1. The daemon was started with an absolute `--archive-socket` (or
   `LLM_RERANK_ARCHIVE_SOCKET`). There is no HOME default. The socket's
   immediate parent must be an owner-only directory and, when it exists, the
   socket itself must be an owner socket with no group or other permission.
   This is re-checked before every admission; a foreign or non-socket occupant
   is refused and no content is held. A daemon started while the configured
   destination fails this check stays off for that process. The scoring
   `socket_path` is not this socket.
2. A fresh observation that the collector desired policy is `enabled`. Initial,
   unknown, stale, `off`, and `paused` observations do not admit text. The
   observer re-checks the producer's local policy snapshot before building a
   payload; transport and storage happen on the producer worker, never on the
   request path.

### Observed window and representation

`interface_version` remains `input-archive-v1`. Envelope and content versions
remain 1. Daemon observations use the additive kind `daemon_observation` with
`daemon_observation_version` 1. An absent, non-integer, or other version is
`unsupported_daemon_observation`. It is not coerced to `unknown_outcome` and
is not a successful current semantic result. Malformed field content (bad wall
time, negative durations, edges outside the stage's named set, out-of-range
counts, non-hex digests) is `invalid_request`.

The observed window starts when the daemon has accepted a scoring request for
scoring (protocol and policy valid, serving lease acquired). It ends at the
decided response. Requests refused before scoring — malformed JSON, missing or
extra fields, policy mismatch, maintenance quiesce — are not daemon
observations; the daemon is not scoring them. Health requests are never
observed. A transport-level failure after the response decision (for example a
client that never finishes its request frame) has no observation.

Stages and their content-free fields:

- `request` — `request_id` and `plan_identity` as safe tokens (a value outside
  the token alphabet is reported absent, not guessed), `effective_policy_id`
  (the daemon's own canonical policy id for its scoring strategy),
  `declared_policy_digest` (SHA-256 of the wire `baseline_policy_id`) and
  `declared_policy_exact`, the scoring strategy and the named rules
  `context_window_rule=unicode_char_tail` and
  `attribution_rule=decode_prefix_reconstruction`, `context_window_chars`,
  `requested_context_chars`, `effective_context_chars`, `context_truncated`,
  `candidate_count`, `candidate_chars`, `model_identity`,
  `model_identity_basis`, `adapter_present`, `adapter_digest`.
- `scoring` — `outcome_code` (`ok` or the protocol error code), `error_phase`
  when failed, `scoring_started`, `load_included`, `scoring_ms`, `load_ms`
  (only when a load actually happened inside this request), `scores_returned`,
  and the named edges `request_accepted`, `scoring_started`,
  `scoring_completed`, `outcome_decided`. `scoring_ms` spans the scoring call
  itself; a cold request performs its load inside that span, which
  `load_included`/`load_ms` report (the reduction is not split further).
- `load` — `load_outcome` (`completed`/`failed`), `load_ms`,
  `model_identity`, `tokenizer_identity` (null, basis
  `unverified_from_scoring_process`), `adapter_present`, `adapter_digest`,
  `model_weights_sha256`, `runtime_versions`, edges `load_started` /
  `load_completed`.
- `unload` — `unload_reason`, `unload_ms`, edges `unload_started` /
  `unload_completed`. The reason enum reports what the unloading call site
  itself declared: `identity_change` and `identity_invalid` for the adapter
  identity paths, and `unspecified` for the production idle watchdog, which
  unloads without a distinguished reason. Nothing is inferred from timing,
  PID or wall clock.

The requested context and the effective preceding-text window are preserved
separately: counts and the truncation flag describe the request, the private
payload carries both the wire `requested_context` and the
`effective_context` actually scored (the last `context_window_chars` Unicode
characters, default 64), plus the `candidates`. The daemon declares
`schema_id` `unknown`: the scoring wire carries no schema identity, so the
observation does not claim a schema interpretation.

Clock domains are explicit. `observed_at_wall_ms` is absolute UTC wall
milliseconds on `system_wall_utc_ms`, the only cross-process clock. Edges,
durations and `monotonic_domain=daemon_process_relative_ms` values are
monotonic milliseconds relative to that daemon process, bound to the
observation's `source_instance_id`; they are not comparable across
incarnations.

Completed work is observed at real completion points only. A request that is
merely scheduled does not increment the load generation; only an attempted
load is reported, as `completed` or `failed`. The compute span
(`scoring_ms`) includes tokenization, the forward pass and scalar extraction;
`decomposition=combined_tokenize_forward_scalar_extraction` states that
materialization is not separately timed. No fabricated subphase duration is
reported, and no extra inference or evaluation is forced to fill a field.
Daemon success is not plugin application, frontend display or host
persistence; the archive publishes `host_persistence_proof=false` and
`application_proof=false`.

### Passive state

`query` view `daemon` exposes the cached last-observed state from durable
daemon observations at the published `as_of_durable_seq`:

- `state` is `loaded`, `unloaded`, or `unknown`, derived only from the newest
  durable lifecycle observation (`load`/`unload`); it is never inferred from
  scoring activity, text, PID or wall time.
- `freshness` is `fresh` while the state observation is younger than
  `freshness_window_ms` (the archive's generic observation-freshness window),
  `stale` afterwards, `unavailable` when the archive holds no daemon
  observations, and `unknown` when the state or its timestamp cannot be
  derived. `unknown_reason` names the reason.
- `source_instance_id`, `state_observed_at_wall_ms`, `state_age_ms`,
  `clock_domain`, `last_observation`, `last_request` and `last_scoring`
  report the newest durable observations as content-free summaries.

Reading this view never connects to the daemon: it does not call scoring or
health, does not change the daemon's last-activity clock, and cannot load,
unload, or extend the life of a model. The legacy health transport marks
activity and is not a passive source; no new passive consumer uses it. The
300-second idle policy is unchanged: observations follow real unload
transitions, including a natural idle unload, and passive reads do not create
activity or refresh the reported status.

### Bounds, faults, and continuity

The observer copies an owned snapshot on the real edge and attempts a bounded
non-waiting `Producer.admit`; it never serializes, connects, retries, or waits.
Producer queue count 256, queue bytes 1048576, batch 64, event budget 65536
apply unchanged. Refusals are terminal and counted locally by the producer
(`known_refused`) and the observer (`refused_untrusted`) for in-process
inspection and tests; no new wire field reports them. A refused snapshot is
dropped and is never held for a later backfill. A snapshot that
was authorized while the policy was fresh and enabled may still finish
delivery later under the documented policy linearization: the collector
re-checks the durable desired policy per item and a
`capture_disabled`/`policy_not_effective`/`capacity_stop`/`storage_failure`
refusal stays final. A malformed or missing peer result is never admission or
durability.

Archive availability is never an inference dependency. An absent, held,
saturated, failed or malformed collector cannot change a scoring response,
delay it past its own bounds, or leak input: observation faults are swallowed
at every hook, and the scoring transport, response shapes, error codes,
deadline and fallback are unchanged. The transient validation controls in the
daemon checker cross the real daemon transport and a genuine collector; the
2000 ms watchdog detects a dependency and is not a p95/p99 certification.

### Checks

From the plugin checkout, with a model-free Python for the contract suite and
the approved scoring interpreter for the model suite:

```sh
"$PYTHON" tools/check_input_archive_daemon.py --self-test
"$PYTHON" tools/check_input_archive_daemon.py --suite contract \
  --root "$RUNTIME/dc/run" \
  --report "$EVIDENCE/daemon-contract-report.json"
"$SCORING_PYTHON" tools/check_input_archive_daemon.py --suite model \
  --root "$RUNTIME/model/run" \
  --report "$EVIDENCE/daemon-model-report.json" \
  --model "$BASE" --adapter "$ADAPTER"
```

`--self-test` uses its own fresh private temporary root. The contract suite
drives the real `run_server` handler over a real socket with a deterministic
fixture state into a real collector and asserts every required case; missing
or skipped required cases fail. Its controlled-clock fixture patches the
daemon's `IDLE_TIMEOUT` module global inside the fixture process only, so the
production default (`IDLE_TIMEOUT = 300`) and its source stay untouched while
the idle watchdog is exercised quickly. The model suite runs the real daemon
process with the approved local model and sealed adapter, observes a cold load
and actual requests (long and empty preceding text), compares capture-off/on
scores, and observes a natural idle unload while passive reads continue.
Watchdogs: 60 s per cold/request exchange, 420 s for the natural idle
observation, 2000 ms for model-free completion under archive faults. Exceeding
them is a finite failed run with records, not permission for unbounded retry.

The checker is an orchestration entry, not a replacement daemon. Ordinary
stdout, stderr, status, errors and the report are content-free; private text
is only in a deliberate private-detail query. Stop only the collector the
check started:

```sh
"$PYTHON" -m archive.cli --root "$ROOT" --socket "$ROOT/collector.sock" collector stop
```

This slice does not certify frontend pixels, host persistence, ranking
benefit, plugin cost, latency percentiles or five-view completeness. **Merge
never enables capture.**

## Versioned human annotations (AC-193-v1)

`input-archive-annotations-v1` is an additive management Interface, not a
source observation, recording-policy revision, training label generator or
dataset job. The existing envelope remains `input-archive-v1`, version 1.
Use `Client.annotations(**read)` / `annotation_query` and
`Client.annotate(reference, kind, value, expected_revision, operation_id)` /
`annotation_edit`. Both CLI and the minimal Annotation TUI call these same
operations and never open the store or implement their own eligibility joins.

### Exact identity and reads

The collector creates a random stable `archive_id` in owner-only
`annotation-identity.json`. It is independent of paths, PID and collector
epoch. A source reference returned on every annotation row has exactly
`archive_id`, `source_instance_id`, `source_local_sequence`, `durable_seq`, and
`record_digest` (SHA-256 of the canonical complete durable observation record).
The source must be in the published observation prefix, be uniquely addressed
by the capture pair, and match its full recorded digest. Missing/unpublished
sources fail `not_found`; a different archive fails `annotation_foreign_archive`;
an ambiguous capture identity, wrong durable sequence or changed content fails
`annotation_source_mismatch`. There are no text/time/nearest-record matches.
Only additive identity metadata is initialized; no legacy migration/backfill
or raw observation rewrite is performed.

Read parameters are `annotation_version`, optional `archive_id`,
`source_reference` (exact detail), `as_of_durable_seq`, `annotation_revision`,
`page_size`, `cursor_token`, and boolean `private_detail`. Unspecified prefix
and revision select the latest published pair **once for that request**. The
response explicitly returns `archive_id`, `as_of_durable_seq`, and
`annotation_revision`. Supply that pair deliberately to reproduce it after
later capture, edits or collector restart. Previously published revisions are
retained without garbage collection. Unknown, negative, boolean, too-large
revisions or prefixes fail `annotation_revision_unknown`, never read latest.

Listing includes all durable sources (also unannotated sources), ordered by
`durable_seq`. Exact reads require the whole source reference. Each row exposes
`kind_revisions`, observed kind/outcome/submission, effective target provenance,
human revision, exclusion/reason/revision and bounded experience metadata.
Only explicit `private_detail=true` adds `private_values.effective_target`,
`observed_target`, and `experience_note`. Metadata requests never return them.
The response's `content_included` states this opt-in, including an empty page;
errors are always content-free. Unavailable evidence stays unavailable.

`next_cursor` is an opaque `a1.` continuation naming archive, source prefix,
annotation revision, position and private-detail mode. Continuation need not
repeat the pair; if repeated it must match. Cross-root, incompatible pair/mode,
unknown position or malformed cursors fail explicitly. Changing annotation
state never changes a source-only #192 query or converts a #192 cursor into
an annotation snapshot. #192 cursors retain their existing epoch semantics.

### Four human operations and provenance

Edits require exactly `annotation_version`, `source_reference`, `kind`,
`value`, `expected_revision`, and `operation_id` (optional `value` defaults to
`{}`). All carry explicit `provenance=human` in retained journal evidence.

| Kind | Value | Meaning |
| --- | --- | --- |
| `confirm` | `{}` | Review the concrete observed target. Only `commit_attempt.payload.text` or plugin commit `payload.text` supplies a target; no host/composition/unselected-text inference. Missing, empty, unsupported or oversized targets fail `annotation_target_unavailable`. |
| `correct` | `{"text": ...}` | Explicit replacement, independent of originally observed text. New corrections supersede effective target at newer revisions; old text and every earlier revision remain. |
| `exclude` | `{"reason": "private"\|"sensitive"\|"unrepresentative"\|"other"}` | Monotonic training exclusion (`excluded=true`); not deletion, pause, unlearning or a dataset transformation. No unexclude operation in v1. |
| `experience` | `{"kind": ..., "value": ..., "note": ...}` | Subjective judgement: kind `input_difficulty`, `candidate_issue`, `unexpected_behavior` or `other`; severity `minor`, `major` or `blocking`; optional private note defaults empty. Not target correctness, measured latency or ranking benefit. Latest experience supersedes effective experience only. |

The newer of confirm/correct controls effective target: `human_reviewed` or
`human_corrected`. Without either, a concrete observed target is
`observed_explicit_preference`, `observed_default_weak`, or
`observed_submission_unknown`; absent target is `unavailable`. None claims
objective correctness or proves host persistence. Cancellation, replacement,
retraction, raw finalization, unavailable/unknown outcomes and unselected
candidates do not automatically acquire targets or positive/negative labels.
A deliberate correction can describe such a source without rewriting its
outcome or fabricating membership in any captured competition.

The downstream #194 reader receives effective target/provenance/exclusion at
one pinned pair, with no consumer-side join. `language_material` states
evidence availability, exclusion and `admission=not_decided`.
`ranking_evaluation` separately reports the existing shared #192 scoped choice
projection. Eligibility additionally requires an observed engine commit, no
retraction/exclusion, complete captured-group evidence, observed membership
`present`, and an effective target identical to that observed target. An
outside-group correction never invents membership or completeness;
`corrected_target_membership=not_asserted`. Missing/oversized group history
stays ineligible. This conservative v1 projection does not search private
candidate text to admit a correction, transform a corpus, or certify ranking
gain. All objective-correctness, host-persistence and ranking-benefit proof
flags remain false.

### Revision, idempotency, publication and recovery

One total annotation revision order per archive starts at zero; every new
published operation increments it by one, independently of capture/policy.
The expected revision must equal the current annotation revision. Two clients
at one expected revision cannot both win; loser receives
`annotation_stale_revision` without mutation. Neither Adapter refreshes or
retries a stale human decision automatically.

`operation_id` is a nonempty <=128-character safe token (ASCII letters, digits,
`_.:-`). It identifies the exact semantic operation, including source, kind,
normalized value, explicit human provenance **and expected revision**. Exact
replay returns the original `annotation_revision`, `replayed=true`,
`current_annotation_revision` and `durable=true`, even after later edits or
restart. Changing content or expected revision with that ID fails
`annotation_operation_conflict`; make a new ID for a new deliberate decision.
The original success response has `replayed=false`. It contains no target/note
or operation-content echo.

The collector holds its existing lifetime ownership lock over all annotation
storage. `annotations.jsonl` is an append-only revision journal with chain and
semantic hashes; `annotation-state.json` publishes exact byte offset,
revision and chain under the same archive ID. A mutation serializes under a
dedicated management lock: write complete row, fsync journal, atomically
replace and fsync the manifest and directory, update lightweight indexes,
then acknowledge durable success. Disk/annotation I/O is never on a producer
input path or under the admission lock. Annotation operations work with
capture off/paused and cannot change recording policy or legacy recording.

A pre-publication failure exposes no new revision; an unpublished tail is
truncated on restart. Published-but-lost-reply retries return that same
operation once. Uncertain write failures return `storage_failure` and poison
the annotation instance until collector restart, rather than roll a possibly
published result backwards. Queries then fail `annotation_state_invalid`, not
success/empty. Startup streams/validates the published journal, chain and
manifest; missing, malformed, truncated or incompatible persisted state is
`annotation_state_invalid`, never reset to empty. Interrupted first-time
initialization is likewise refused. Managed annotation artifacts must be
owner-owned, mode 0600, regular and single-link; alias/non-private artifacts
fail `unsafe_root` before following or rewriting targets. The root remains
0700. This is the existing personal-account threat model, not protection
against malicious same-account replacement of the complete archive.

### Bounds and work

- Replacement/observed target: <=8192 UTF-8 bytes, nonempty. Note: <=2048
  UTF-8 bytes, possibly empty. Invalid strings/types fail `invalid_request`;
  oversized private values fail `annotation_input_bound`.
- Private input JSON: one bounded line on stdin/interactive stream, or a
  <=131072-byte validated private regular file. No private text is required in
  argv. Symlinked parent/file, hardlink, non-owner or group/other-readable
  files are refused. Interactive TTY echo is disabled while reading values.
- Page size defaults to the existing limit (20), maximum 50 by default, using
  existing configured page limits. Bad sizes fail `invalid_request` or
  `page_bound`. Both ordinary **and private** annotation query responses are
  bounded by min(1048576, `query_page_bytes_max`) encoded frame bytes. Oversize
  responses fail `page_bytes_bound` (reduce page size); no partial success or
  silent truncation. Mutation acknowledgements are not pages.
- Journal row <=131072 bytes, request/frame limits unchanged. Revisions and
  positions are nonnegative integer values <=2^63-1. Unknown protocol versions
  fail `unsupported_annotation_version`; malformed requests use fixed errors.
- Startup: O(R) streamed journal validation, O(R) resident offset/hash/revision
  and idempotency metadata for R revisions, no retained private history.
  Source indexes add O(S) metadata to the existing source index. Journal disk
  use grows O(R); annotation history is separate from observation-capacity
  accounting and is not garbage-collected in this contract.
- Listing seeks the existing durable source index in O(log S) and copies at
  most page_size+1 entries. Each row reads one bounded source record and at
  most four journal rows, with O(log H) revision lookup per kind for H edits of
  that source. Group projection reuses shared #192 semantics with at most
  `query_group_members_max` metadata witnesses (default 256); larger groups
  remain ineligible. No payload-history scan or full-copy cursor.
- The checker reports finite 256/4096 operations, complete pinned iteration,
  a 256-revision single source, resource samples, actual runtime/source hashes
  and failure/restart/Adapter controls. RSS samples and checker tracemalloc
  are measurements, **not a total-RAM, latency or zero-loss guarantee**.

### CLI and minimal Annotation TUI

No default live root and no service enablement. Examples assume an already
running collector at `$SOCKET`; private JSON files must be owner-only.

```sh
# Metadata only: use a returned source_reference verbatim, never guess text.
"$PYTHON" -m archive.cli --socket "$SOCKET" annotations list --page-size 20
# reference.json: {"source_reference": <exact returned reference>}
"$PYTHON" -m archive.cli --socket "$SOCKET" annotations show \
  --input-file "$PRIVATE/reference.json" --prefix 10 --revision 3
# edit.json: {"source_reference": <reference>, "value": {"text": <private text>}}
"$PYTHON" -m archive.cli --socket "$SOCKET" annotations correct \
  --input-file "$PRIVATE/edit.json" --expect-revision 3 --operation-id decision-4
# confirm/exclude/experience have the same flags and their value shapes above.
# Explicit private read only; terminal controls are rendered as JSON escapes.
"$PYTHON" -m archive.cli --socket "$SOCKET" annotations show \
  --input-file "$PRIVATE/reference.json" --prefix 10 --revision 4 --private-detail
```

Omit `--input-file` (or use `-`) to read one JSON line from stdin. Ordinary
and private Annotation output is structurally identical JSON, including error,
provenance, revision and durable outcome; the `--json` global flag is optional
for this surface. Bad arguments never echo supplied values. Private content
is absent from ordinary stdout/stderr, diagnostics and reports. Private
opt-in output is not suitable for public logs or issue comments.

In the existing line-oriented TUI:

- `annotations` lists a fresh pinned page; `annotations PREFIX REVISION` reads
  an explicit pair. `annotation-next` continues it.
- `annotation-select DURABLE_SEQ` selects an exact source reference from the
  displayed page (not arbitrary text or an unstated root).
- `annotation-edit KIND OPERATION_ID EXPECTED_REVISION` edits the selection.
  For correct/exclude/experience the next line is private JSON **value only**;
  confirm requires no extra line. The prompt does not echo supplied content.
- `annotation-private` deliberately reads the selected row at the displayed
  pair. Edits do not silently refresh that pair; issue `annotations` to read
  latest deliberately. Stale edits, missing selection, invalid values and
  disconnected collectors display explicit errors, not success/empty.
- `quit`/EOF leaves collector and capture policy unchanged.

Reproduction (invented private fixtures only, fresh roots):

```sh
"$PYTHON" tools/check_input_archive_annotations.py --self-test
"$PYTHON" tools/check_input_archive_annotations.py --suite contract \
  --root "$PRIVATE/fresh-annotation-run" --report "$PRIVATE/annotations.json"
```

The suite drives real collector subprocesses, shared Interface, CLI and TUI;
faults are injected in its owned launcher (before publication, disk error,
crash boundaries and published/lost reply), not in production producers.
Required cases never skip; no model, network scorer, health probe, host document,
live input method or real deployment is used. Dataset jobs/freezes/partitions,
backup/delete/restore, legacy migration, general TUI redesign, frontend capture,
ranking/scoring and training remain deferred by that annotation slice. Dataset
work below is additive; the annotation restrictions above are unchanged.
**Merge never enables capture.**

## Immutable two-view dataset freezes (AC-194-v1)

The shared `input-archive-datasets-v1` Interface adds the `dataset` operation.
CLI and Datasets TUI are rendering/input Adapters only. No model, tokenizer,
training, health/score request, deployment or capture enablement occurs. Legacy
fact/trace/SQLite exports are never implicit inputs.

### Snapshot, identity and temporal partition

`snapshot` returns an explicit pair: archive identity, first durable sequence
(inclusive), published durable prefix (inclusive), retained annotation revision,
canonical source-reference/content digest, content v1, current query version and
annotation version. The digest is computed from bounded metadata pages and is
required on create: an old pair cannot silently bind changed source after restart.
Source content identity follows #193 canonical record digests, not JSON whitespace.
Preview may select the
current pair; create requires the **complete explicit pair**. A retry never
substitutes a new prefix/revision. Each source reference includes archive ID,
source incarnation/local sequence, durable sequence and record digest. Raw
observations and annotation history are not rewritten. Text equality never
deduplicates independent captures; admission retries retain foundation identity
deduplication/conflict behavior.

Partition rule `whole-segment-durable-interval-v1` orders by published durable
sequence, not wall time and not a claimed causal relation between producers.
Segments are scoped `(source_instance_id, continuity_segment_id)` and processes
are scoped `(source_instance_id, process_id)`. A segment requires observed
process starts and terminal outcomes, no observed loss/unknown/gap, and a later
different segment on the same source-local sequence chain to be treated as
closed. Reappearance of an already closed segment is uncertain. The last/open,
missing-ID, discontinuous or incomplete segment is explicitly ineligible.

Every segment/process occupies its whole observed durable interval. Overlapping
intervals merge; actual recorded frontend-update and shared request-link
dependencies add intervals too. This prevents interleaved sources or later
transformations crossing a split. Legal cuts stop before the earliest uncertain
segment: this deliberately conservative rule may make otherwise large inputs
unusable. Unknown continuity never becomes fabricated singleton segments.

Among legal pairs of strict cuts, minimize the integer L1 deviation of cumulative
source counts from 80% and 90%; ties choose the earliest durable pair. A suffix
minimum makes cut selection linear after interval sorting. No legal pair yields
`unusable`, with the source map retained as `unassigned`, not corrupt source or a
forced random split. Both views inherit the exact same map **before filtering**.
An oversized segment is never split to improve ratios. All source units,
including unknown/excluded/unadmitted units, remain in `partition.jsonl`.

The manifest reports source/view exported-row counts, partition proportions,
normal-commit populations, eligible/ineligible choice populations, overlapping
reason incidences and label provenance. The denominator for source proportions
is all selected durable observations; each view's denominator is its own exported
rows. Eligibility has its own count, not an implied property of a nonempty file.
Cross-partition equal-target overlap counts distinct SHA-256 hashes of exact UTF-8
effective targets appearing in multiple partitions; genuine repeated text stays.
Source-identity overlap is zero by construction and semantic verification checks
the regenerated map, not only checksums. No statistical adequacy or untouched
prospective-confirmation claim follows from any ratio or historical test file.

### Views and exclusions

- `corpus.jsonl`: admitted normal frontend commit attempts and engine commits,
  explicitly distinguished by observation scope (neither proves host persistence).
  Independent source captures are not equated by their text. Original/effective
  targets, human revision and human-reviewed/corrected, observed-explicit,
  default-weak or unknown-submission provenance stay distinct. Cancel/raw/
  unavailable/unknown outcomes are not positive material. Shared observed group
  retraction/exclusion is honored. There is no fixed tokenizer, prompt format,
  candidate count or 64-character corpus window.
- Context is an exact reference to **one** earlier admitted commit whose owned
  update is the recorded parent, in the same observed segment and partition.
  Absence of such evidence means unavailable context, not inferred adjacency or
  a reconstructed host document. Exclusion/inadmissibility of that parent excludes
  the dependent example, rather than copying its target as usable context.
- `choice.jsonl`: observed engine-commit choice examples, including explicitly
  ineligible examples/reasons. It preserves the shared #192 group projection and
  actual structured competition/emission/commit payloads, input, span, category,
  captured member indexes, Merge Order and Emission Order. Structured membership,
  span/category, counts, permutations and original target must agree.
  Missing/ill-typed span/category/input/member text/Merge Order or non-integer
  order indexes cannot serve as complete structured competition. Boolean indexes
  are not integers. Captured group `plan_complete` must be explicitly true, in
  addition to (never instead of) the shared group-members-and-target coverage basis.
  Conflicting member identities, absent fields, unknown/truncated competition, default weak
  labels, retraction/exclusion and outside/changed human targets are not ranking
  evidence. Unselected candidates receive no invented negative labels.
- Actual observed native request/plan relations use `RelationContext`, not a plan,
  text/time/PID join. Linked daemon request identity/model/policy/window metadata
  is preserved with its source reference. Actual model input remains unknown when
  capture does not provide it; captured preceding text is not relabeled as the
  effective scoring request or reconstructed from display strings.
- Excluding any member of a scoped competition removes the dependent choice
  example. Structured payloads contain the whole captured window, so exclusion
  propagates to sibling groups in that same owned process/window too; a group
  never re-exports an excluded sibling's candidates from a shared payload.
  Captured preceding text has no complete source-reference vector; if
  any exclusion exists at the pinned revision, an example containing such
  unattributed preceding text is omitted with an explicit dependency reason.
  This is conservative exclusion, not a text-equality heuristic. No excluded raw
  evidence is altered. Unknown/ineligible and excluded populations stay separate.

### Jobs, managed artifacts and immutable publication

Managed writes are fixed paths under the validated private archive's `datasets/`
root, never arbitrary supplied export destinations. Dataset roots are 0700;
regular artifacts are owner-owned 0600/single-link. Symlinked components, unsafe
owners/modes, aliases, hardlinks and synchronized destinations fail closed.
The personal-account threat model above remains (not protection against complete
malicious same-account replacement). No real private history is read by tests.

One background dataset job runs at a time; another request gets `dataset_busy`.
Its ID is a hash of archive and bounded operation identity. Persisted request,
progress and lifecycle states are `pending`, `running`, `succeeded`, `failed`,
`cancelled`, `unknown`. An acknowledged request is **not a completed freeze**.
The source/rule/code request digest excludes the operation name: identical pinned
input/rules produces identical artifact streams even under a new operation ID.
Reusing one operation with a different pair/rules refuses without rebinding or
overwriting any successful bytes. Identical retries resolve the original job,
including its failed/unknown outcome; a deliberate new operation is needed for
a new attempt. There is no automatic background retry or capture-policy change.

Each job reserves/registers three JSONL views/maps plus `manifest.json`, their
owner-relative fixed paths, source identity/range/revision dependencies, sizes,
SHA-256 checksums and lifecycle. The checksummed partition artifact is the exact
source-reference dependency map; the manifest binds source-content identity and
all versions/rules/code identity, counts/reasons/boundaries/overlap. The durable
`job.json` success descriptor is the single publication/registration marker,
written only after every complete artifact and its directory have been fsynced.
There is no interval in which a published successful freeze lacks its registry.
Corrupt/unsafe dataset state is isolated to dataset errors on collector restart;
it does not make otherwise valid source capture depend on repairing a freeze.

Failed/cancelled copies are retained and marked incomplete/not-created, not hidden
as successful output. A crash before publication becomes `unknown` on restart;
a complete published marker recovers the immutable result. An interruption
before request acknowledgement is an explicitly unacknowledged unknown orphan,
not an empty/successful request. It cannot be rebound by retry. Any uncertain
late publication durability remains unknown until restart. No cleanup, backup,
delete, restore, unlearning or automatic retraining is implemented; this registry
is input to future lifecycle work, not authority for it.

Cancellation is explicit and supported before publication; after publication it
is refused. EOF/closing a TUI only detaches the observer and leaves the collector,
job and recording policy alone. A completed freeze is never regenerated by
verify, renamed over a previous success, or silently upgraded on append/restart.

### Verification, current exclusions and errors

`verify` is model-free **semantic** verification: manifest/version/identity,
safe fixed relative paths, registry/dependencies, sizes/checksums and regenerated
partition/provenance/admission streams bound to the exact source/annotation pair.
Recomputation hashes streams without creating new private copies or repairing
the freeze. Missing source is `dataset_source_unavailable`; corrupt/tampered
state is `dataset_corrupt`; unsupported source/tool versions/code identity are
`dataset_incompatible`; bounds are `dataset_bound`. Foreign/stale annotation
references retain their established errors. `unusable` is legal data, not a
verification failure. Artifact-integrity-only success is not exposed.

Status/list/preview compute current-policy compatibility separately from frozen
bytes. Any new archive exclusion conservatively invalidates default candidacy,
including possible unknown captured-context dependencies outside the selected
range. Exclusion drift during a compatibility scan yields unknown/not-default,
never false current consistency. Missing/changed source similarly prevents a
default-candidate claim. Old frozen targets/manifests remain untouched; regenerate
under a new deliberate operation/revision. No claim of model unlearning follows.

### Bounds, privacy and commands

Per selected input: at most 65,536 payload-free source metadata entries, O(S)
scoped interval/identity/hash metadata, sorted interval work O(S log S), two
streamed source passes, at most 64 reference entries per page, one source payload
of at most 131,072 stored bytes (larger legal captures refuse with `dataset_bound`)
plus a configured bounded captured-window expansion (default 256 observations,
using the existing group-member bound) and at most 8 MiB per
output line. Group expansion beyond its bound is explicitly ineligible and the
freeze outcome is `bounded_unusable`, never a truncated complete dataset.
More source rows fail `dataset_bound`. There are at most 1,024 owned jobs;
listing pages at most 64 descriptors; private pages at most four rows and 1 MiB
response content (also subject to the existing Interface frame/page bound).
Cursor-like positions store no payload/history copies. Disk scans, whole jobs
and TUI waits never hold the collector admission lock. Query/annotation group
bounds are unchanged. Source/annotation metadata and disk growth are **not** a
total-RAM or retention bound; finite 256/4096 high-fanout work samples are not a
quiet-machine latency guarantee.

Ordinary output/errors/status are aggregate/content-free. Private detail is a
separate explicit operation, JSON/terminal-escaped; test-partition detail is
hidden unless separately opted in. No target text is required in process argv.
Use the bounded owner-only private file/stdin input helper for a snapshot.
There is no default live root or automatic collector start:

```sh
"$PYTHON" -m archive --socket "$SOCKET" datasets snapshot
"$PYTHON" -m archive --socket "$SOCKET" datasets preview
# pair.json contains ONLY the returned snapshot object, not the response wrapper.
"$PYTHON" -m archive --socket "$SOCKET" datasets create \
  --operation-id deliberate-freeze-1 --input-file "$PRIVATE/pair.json"
"$PYTHON" -m archive --socket "$SOCKET" datasets list
"$PYTHON" -m archive --socket "$SOCKET" datasets status --job-id "$JOB"
"$PYTHON" -m archive --socket "$SOCKET" datasets verify --job-id "$JOB"
"$PYTHON" -m archive --socket "$SOCKET" datasets cancel --job-id "$JOB"
"$PYTHON" -m archive --socket "$SOCKET" datasets private --job-id "$JOB" \
  --artifact corpus.jsonl --page-size 1 --private-detail
# --include-test is a separate deliberate private-test access opt-in.
```

TUI commands: `datasets`, `dataset-preview`, `dataset-create OPERATION_ID`
(uses the preview's pinned pair), `dataset-status JOB`, `dataset-verify JOB`,
`dataset-cancel JOB`, and `dataset-private JOB ARTIFACT [include-test]`.
Every command exposes the actual pending/running/failure state, not success on
request save; errors do not echo hostile supplied values. No five-view redesign.

```sh
"$PYTHON" tools/check_input_archive_datasets.py --self-test
"$PYTHON" tools/check_input_archive_datasets.py --suite contract \
  --root "$PRIVATE/fresh-datasets-run" --report "$PRIVATE/datasets.json"
```

The checker uses genuine collector/Interface/CLI/TUI, invented Simplified-Chinese
fixtures, model/network tripwires, pinned append/restart, whole-segment controls,
two-view provenance, exclusions, deterministic bytes, tamper/unsafe references,
publication crashes/disk faults, cancellation/detach and finite 256/4096 resource/
work controls. Required cases never skip; helper self-tests supplement them.
Reports bind source/rules/runtime and retained private artifacts without text.
Baseline source-built native/model-free/foundation/plugin/passive-daemon/query/
annotation gates remain required. Only the inherited absent-model skips apply.
**Merge never enables capture.**
