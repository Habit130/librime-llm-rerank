#!/usr/bin/env python3
"""Test-only fixture operation type for the persistent-operation engine
(Habit130/squirrel#52).

#52 ships no production maintenance operation (real backup/restore/clear/
rebuild arrive with #54/#55/#57/#68). This fixture registers a controlled
maintenance-shaped operation into the engine registry inside tests only, so
the persistent-execution, wait, cancel, crash-recovery and irreversible-phase
semantics can be proven end to end. It is never registered by the CLI or by
production code.

Fixture machine: preflight -> staging (3 chunks) -> publishing (irreversible)
-> cleanup. Side effects land in `work_dir` so tests can count executions:

  work_dir/preflight.marker   written by the preflight step
  work_dir/chunks             staging chunk counter file (resume-proof)
  work_dir/published.marker   the irreversible artifact; the publish step
                              refuses to create it twice
  work_dir/publish.count      append-only log of publish *effect* executions
  work_dir/cleanup.marker     written by the cleanup step

The publish step follows the spec's irreversible-publish pattern: it checks
the artifact it created before creating it, so a crash between the effect
and the persist can never cause a duplicate publish on restart.

Parameters (normalized at creation):
  work_dir:      directory for side effects (absolute, NFC)
  sleep_s:       per-step sleep for the Ctrl-C detach tests (default 0)
  private_label: arbitrary string persisted in `parameters` only; the
                 privacy tests use it to prove logs/errors/output never
                 echo parameter values
"""

import os
import time
import unicodedata

from operations import (  # noqa: E402
    OperationBlocked,
    OperationFailed,
    OperationTypeSpec,
)

FIXTURE_TYPE = "fixture.maintenance"
FIXTURE_PHASES = ("preflight", "staging", "publishing", "cleanup")
FIXTURE_IRREVERSIBLE_PHASE = "publishing"
FIXTURE_CHUNKS = 3


def _nfc(value):
    return unicodedata.normalize("NFC", value)


def _normalize(parameters):
    if not isinstance(parameters, dict):
        raise ValueError("fixture parameters must be a dict")
    work_dir = parameters.get("work_dir")
    if not isinstance(work_dir, str) or not work_dir:
        raise ValueError("fixture requires a work_dir")
    return {
        "work_dir": os.path.abspath(_nfc(work_dir)),
        "sleep_s": float(parameters.get("sleep_s") or 0.0),
        "private_label": str(parameters.get("private_label") or ""),
    }


def _sleep(record):
    seconds = record["parameters"].get("sleep_s") or 0.0
    if seconds > 0:
        time.sleep(seconds)


def _work_dir(record):
    work_dir = record["parameters"]["work_dir"]
    os.makedirs(work_dir, exist_ok=True)
    return work_dir


def _step_preflight(record, ctx):
    _sleep(record)
    work_dir = _work_dir(record)
    marker = os.path.join(work_dir, "preflight.marker")
    if not os.path.isfile(marker):
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ok\n")
    return {"progress": {"events": 1}, "advance": True}


def _step_staging(record, ctx):
    _sleep(record)
    work_dir = _work_dir(record)
    chunks = record["progress"].get("chunks") or 0
    chunks += 1
    with open(os.path.join(work_dir, "chunks"), "w",
              encoding="utf-8") as f:
        f.write("%d\n" % chunks)
    if chunks < FIXTURE_CHUNKS:
        return {"progress": {"chunks": 1}}
    # The final chunk also advances to the irreversible publishing phase.
    return {"progress": {"chunks": 1, "events": 1}, "advance": True}


def _step_publishing(record, ctx):
    _sleep(record)
    work_dir = _work_dir(record)
    marker = os.path.join(work_dir, "published.marker")
    count_path = os.path.join(work_dir, "publish.count")
    if not os.path.isfile(marker):
        # The irreversible effect: only when it has never happened.
        with open(marker, "w", encoding="utf-8") as f:
            f.write("published\n")
        with open(count_path, "a", encoding="utf-8") as f:
            f.write("1\n")
    with open(marker, "rb") as f:
        size = len(f.read())
    return {"progress": {"bytes": size}, "advance": True}


def _step_cleanup(record, ctx):
    _sleep(record)
    work_dir = _work_dir(record)
    marker = os.path.join(work_dir, "cleanup.marker")
    if not os.path.isfile(marker):
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ok\n")
    return {"progress": {"events": 1}, "advance": True,
            "result": {"completed": True,
                       "chunks": record["progress"].get("chunks")}}


def fixture_spec():
    return OperationTypeSpec(
        operation_type=FIXTURE_TYPE,
        phases=FIXTURE_PHASES,
        irreversible_phase=FIXTURE_IRREVERSIBLE_PHASE,
        normalize=_normalize,
        steps={
            "preflight": _step_preflight,
            "staging": _step_staging,
            "publishing": _step_publishing,
            "cleanup": _step_cleanup,
        },
    )
