# Model-free gates

The model-free gate is `scripts/run-model-free-gates.sh`. It discovers every
`daemon/test_*.py` and `eval/test_*.py` case. A daemon failure must not hide
an unrun eval suite. Required maintenance, permission, and deploy cases cannot
be skipped, xfailed, or filtered out of that script.

This does not certify a model, a live Rime deployment, launchd, latency, or
capture. Merge does not enable capture.

## Runtime

Reproduce the inherited gate with Python 3.11.15 and its bundled SQLite
3.53.3. The project-local pins for that interpreter are `numpy==2.2.6`,
`pypinyin==0.55.0`, and `PyYAML==6.0.2`. Do not treat a pass on a different
SQLite as evidence that a SQLite 3.53.3 failure is fixed. Native fact
operations still go through `fact_store_tool`; run the Python suites from a
source export whose `../../../build/plugins/llm-rerank/bin/fact_store_tool`
is the helper built from that same export.

## Fingerprint boundary

An unreadable-current restore is accepted only with both
`--accept-unreadable-current` and `--expect-current-fingerprint`. After
quiesce, the daemon opens the DB/WAL/SHM descriptors that still exist and
hashes those bytes. An absent sidecar contributes a zero length. WAL and SHM
are not removed from the hash, and a mismatch does not publish quarantine or
replace the store.

Python SQLite 3.53.3 deletes WAL/SHM when the live fact handle closes. Those
sidecars can exist only because the control server has the store open. A
directory listing taken before quiesce is therefore not the protected
expectation, and it must not be treated as equivalent to the post-quiesce
opened-descriptor set. The durable DB bytes are what remain on this runtime.
The CLI still performs that real quiesce; the caller has to supply the
post-quiesce fingerprint, not the open-handle snapshot. A wrong or stale
fingerprint, including that open-handle snapshot, is refused with no
publication.

## Control-root permissions

`validate_control_path` accepts an owner-private directory mode `0700` and
refuses a group/other-accessible directory, a symlink, and a foreign peer
UID. `os.mkdir(path, mode)` does not override umask, so fixtures must set
the mode with `chmod` and assert the actual mode. The same fixture must pass
under umask `077` and `022`. Do not chmod evidence or production roots.

## Explicit portable paths

`daemon/deploy.py` substitutes explicit checkout, interpreter, server, model,
adapter, socket, log, and facts paths into
`daemon/com.squirrel.llm-rerank.plist`. The template itself has no maintainer
path and no unresolved placeholder may remain. A rendered `/Users/habit`
path is accepted only when it is exactly one of those declared values. Any
other `/Users/habit` path is an undeclared baked-in default and is rejected.
Isolated install and skip-install verification keep a real health-only
process, `model_loaded=false`, an owner-private runtime, and no launchd
registration or model load.

## Evidence checker

`tools/check_model_free_gate_prerequisite.py` is content-free. It refuses an
existing `--root` or `--report`, does not follow symlinks, and does not open
sockets or FIFOs as evidence files. `--self-test` checks those invariants.
`--suite contract` checks the Python/SQLite pins, the paired native helper,
and the named restore, control, and deploy cases, and it keeps their primary
stores and terminal records after unittest teardown. Helper booleans are not
a substitute for those records.

```sh
python3 tools/check_model_free_gate_prerequisite.py \
  --self-test --root "$RUNTIME/self-test" --report "$EVIDENCE/self-test-report.json"
python3 tools/check_model_free_gate_prerequisite.py \
  --suite contract --native-build "$HOST/librime/build" \
  --root "$RUNTIME/contract" --report "$EVIDENCE/contract-report.json"
```

Inherited model-only or optional skips in the full gate stay skips only when
their own condition is unmet. They are not a blanket allowance, and they do
not cover the required cases above. Identify each skip from the full-gate
log. The gate makes no model, latency, or memory certification.
