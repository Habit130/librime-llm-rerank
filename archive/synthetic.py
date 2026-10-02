"""Invented luna_pinyin observations for the isolated archive.

These fixtures are not real input, not host documents, and not evidence of
frontend timing or model application.
"""

from __future__ import annotations

from archive.interface import CONTENT_VERSION, ENVELOPE_VERSION, SUPPORTED_SCHEMA

INVENTED_TEXT = "INV-NIHAO"


def observation(kind, process_id, sequence, source_instance_id, **extra):
    record = {
        "envelope_version": ENVELOPE_VERSION,
        "content_version": CONTENT_VERSION,
        "schema_id": SUPPORTED_SCHEMA,
        "source_instance_id": source_instance_id,
        "source_local_sequence": sequence,
        "observation_kind": kind,
        "process_id": process_id,
        "clocks": {"event_time": None, "observation_time": None, "clock_domain": "unknown"},
        "stage": "unknown",
        "host_persistence": "unknown",
    }
    record.update(extra)
    return record


def supported_processes(source_instance_id):
    """One invented process for each required outcome, linked by explicit ids."""
    processes = []
    processes.extend(_commit_process(source_instance_id))
    processes.extend(_cancel_process(source_instance_id))
    processes.extend(_raw_process(source_instance_id))
    processes.extend(_unavailable_process(source_instance_id))
    processes.extend(_unknown_process(source_instance_id))
    processes.append(
        observation(
            "commit_attempt",
            "proc-commit-only",
            50,
            source_instance_id,
            update_id="commit-only-u",
            commit_id="commit-only-c",
            parent_update_id="missing-parent-u",
            outcome="observed_attempt",
            host_persistence="persisted",
            payload={"text": INVENTED_TEXT, "role": "commit-only"},
        )
    )
    return processes


def _commit_process(source):
    process_id = "proc-commit"
    return [
        observation("start", process_id, 1, source, update_id="commit-start", payload={"text": INVENTED_TEXT}),
        observation(
            "input_change",
            process_id,
            2,
            source,
            update_id="commit-change",
            parent_update_id="commit-start",
            payload={"text": INVENTED_TEXT},
        ),
        observation(
            "replacement",
            process_id,
            3,
            source,
            update_id="commit-replace",
            parent_update_id="commit-change",
            payload={"text": INVENTED_TEXT},
        ),
        observation(
            "temporary_selection",
            process_id,
            4,
            source,
            update_id="commit-select",
            parent_update_id="commit-replace",
            payload={"text": INVENTED_TEXT, "temporary": True},
        ),
        observation(
            "commit_attempt",
            process_id,
            5,
            source,
            update_id="commit-final",
            commit_id="commit-c",
            parent_update_id="commit-select",
            outcome="observed_attempt",
            payload={"text": INVENTED_TEXT, "role": "commit"},
        ),
    ]


def _cancel_process(source):
    return [
        observation("start", "proc-cancel", 10, source, update_id="cancel-start", payload={"text": "INV-CANCEL"}),
        observation(
            "cancellation",
            "proc-cancel",
            11,
            source,
            update_id="cancel-end",
            parent_update_id="cancel-start",
            outcome="cancelled",
            payload={"text": "INV-CANCEL"},
        ),
    ]


def _raw_process(source):
    return [
        observation(
            "raw_finalization",
            "proc-raw",
            20,
            source,
            update_id="raw-u",
            commit_id="raw-c",
            outcome="raw_finalized",
            payload={"text": "INV-RAW"},
        )
    ]


def _unavailable_process(source):
    return [
        observation(
            "unavailable_client",
            "proc-unavailable",
            30,
            source,
            update_id="unavail-u",
            outcome="unavailable_client",
            payload={"text": "INV-UNAVAILABLE"},
        )
    ]


def _unknown_process(source):
    return [
        observation(
            "unknown_outcome",
            "proc-unknown",
            40,
            source,
            outcome="unknown",
            stage="unknown",
            payload={"text": "INV-UNKNOWN"},
        )
    ]


def scale_observation(index, source_instance_id):
    return observation(
        "commit_attempt",
        "scale-%s" % index,
        index,
        source_instance_id,
        update_id="scale-u-%s" % index,
        commit_id="scale-c-%s" % index,
        outcome="observed_attempt",
        payload={"n": index},
    )
