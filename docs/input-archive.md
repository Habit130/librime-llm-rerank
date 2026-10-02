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
| Storage | Append-only `observations.jsonl` plus a fsynced `state.json` watermark. Quarantine is a separate file. |
| TUI | Line-oriented Overview/Timeline adapter. No third-party TUI library and no five-view claim. |
| Index | Rebuildable offset index of durable records. Payloads are not kept as a resident history copy. |
| Clocks | Event and observation clocks are client-supplied numbers or unknown. Wall-clock proximity is not a join. |

Incompatibility is an error, never a successful semantic interpretation:
`unsupported_version`, `unsupported_schema`, `stale_revision`, `unsafe_root`,
`page_bound`, `identity_conflict`.

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

Capture starts disabled. A merge does not enable capture. This slice does not
certify frontend latency, ranking benefit, annotation, export, or the five-view
TUI.

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
`received_unpublished` is a queue length. `durable_seq` advances only at the
publication point:

1. Append complete JSONL lines.
2. Flush and fsync that file.
3. Write the new watermark to `state.json`, fsync it, and fsync the directory.

A crash before step 3 does not make those bytes durable. Restart truncates to
the watermark, reports `crash_tail=unknown`, and does not parse the discarded
bytes into observations or add them to `known_dropped_units`. Only a provable
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

Archive roots are local and owner-only: directories `0700`, files and the
socket `0600`. Unsafe roots are rejected before writing: symlink components,
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
root. It does not prove real frontend behavior, p95/p99 input latency, model
application, ranking benefit, annotation, dataset export, backup, deletion, or
legacy-history access. Skipped required checks are failures, not passes.
