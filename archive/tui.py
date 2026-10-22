"""Minimal Overview/Timeline adapter.

This is not the five-view TUI. It reads and controls only through the shared
Interface. Closing it does not stop the collector or change policy unless the
operator issued a control command.
"""

from __future__ import annotations

from archive.interface import INTERFACE_VERSION
from archive.safety import escape_terminal_data

_DISCLOSURE = "legacy_selection_recording=separately_configured_may_continue"


class TuiSession(object):
    def __init__(self, client, stdin, stdout):
        self.client = client
        self.stdin = stdin
        self.stdout = stdout
        self.stopped = False
        self.annotation_page = None
        self.annotation_selection = None
        self.dataset_snapshot = None

    def run(self):
        self._overview()
        while not self.stopped:
            self.stdout.write("> ")
            self.stdout.flush()
            line = self.stdin.readline()
            if not line:
                break
            self._command(line.strip())
        self.stdout.write("SCREEN closed\n")
        self.stdout.write("collector_left_running=true\n")
        self.stdout.flush()

    def _command(self, line):
        if not line:
            return
        parts = line.split()
        command = parts[0]
        if command.startswith("dataset"):
            self._dataset_command(parts)
        elif command.startswith("annotation"):
            self._annotation_command(parts)
        elif command == "overview":
            self._overview()
        elif command == "timeline":
            self._timeline()
        elif command == "timing":
            self._timing()
        elif command == "expand" and len(parts) == 2:
            self._expand(parts[1])
        elif command == "pause":
            self._policy("paused")
        elif command == "resume":
            self._policy("enabled")
        elif command == "quit":
            self.stopped = True
        else:
            self.stdout.write("SCREEN error\ncode=invalid_request\ncontent_included=false\n")

    def _dataset_command(self, parts):
        from archive.dataset_adapter import render
        from archive.interface import InterfaceError, failure
        private = False
        try:
            command = parts[0]
            if command == "datasets" and len(parts) == 1:
                response = self.client.datasets("list")
            elif command == "dataset-preview" and len(parts) == 1:
                response = self.client.datasets("preview")
                if response.get("ok"):
                    self.dataset_snapshot = response["body"]["source"]
            elif command == "dataset-create" and len(parts) == 2 and self.dataset_snapshot:
                response = self.client.datasets("create", operation_id=parts[1], snapshot=self.dataset_snapshot)
            elif command in ("dataset-status", "dataset-verify", "dataset-cancel") and len(parts) == 2:
                response = self.client.datasets(command.split("-")[1], job_id=parts[1])
            elif command == "dataset-private" and len(parts) in (3, 4):
                if len(parts) == 4 and parts[3] != "include-test":
                    raise InterfaceError("invalid_request")
                private = True
                response = self.client.datasets("private", job_id=parts[1], artifact=parts[2], private_detail=True, include_test=len(parts) == 4, page_size=1)
            else:
                raise InterfaceError("invalid_request")
        except (ValueError, InterfaceError) as exc:
            response = failure("dataset", "", getattr(exc, "code", "invalid_request"))
        self.stdout.write("SCREEN datasets\n")
        self.stdout.write(render(response, private))
        self.stdout.flush()

    def _annotation_command(self, parts):
        from archive.annotation_adapter import read_private_json, render
        from archive.interface import InterfaceError, failure
        from archive.safety import UnsafeRoot

        private = False
        try:
            command = parts[0]
            if command == "annotations" and len(parts) in (1, 3):
                kwargs = {}
                if len(parts) == 3:
                    kwargs = {"as_of_durable_seq": int(parts[1]), "annotation_revision": int(parts[2])}
                response = self.client.annotations(**kwargs)
                self.annotation_page = response["body"] if response.get("ok") else None
                self.annotation_selection = None
            elif command == "annotation-next" and len(parts) == 1 and self.annotation_page and self.annotation_page.get("next_cursor"):
                response = self.client.annotations(cursor_token=self.annotation_page["next_cursor"])
                self.annotation_page = response["body"] if response.get("ok") else None
                self.annotation_selection = None
            elif command == "annotation-select" and len(parts) == 2 and self.annotation_page:
                seq = int(parts[1])
                matches = [row for row in self.annotation_page["observations"] if row["source_reference"]["durable_seq"] == seq]
                if len(matches) != 1:
                    raise InterfaceError("not_found")
                self.annotation_selection = matches[0]["source_reference"]
                response = self.client.annotations(source_reference=self.annotation_selection, as_of_durable_seq=self.annotation_page["as_of_durable_seq"], annotation_revision=self.annotation_page["annotation_revision"])
            elif command == "annotation-private" and len(parts) == 1 and self.annotation_selection and self.annotation_page:
                private = True
                response = self.client.annotations(source_reference=self.annotation_selection, as_of_durable_seq=self.annotation_page["as_of_durable_seq"], annotation_revision=self.annotation_page["annotation_revision"], private_detail=True)
            elif command == "annotation-edit" and len(parts) == 4 and self.annotation_selection:
                kind, operation, revision = parts[1:]
                if kind not in ("confirm", "correct", "exclude", "experience"):
                    raise InterfaceError("invalid_request")
                value = {}
                expected = int(revision)
                if kind != "confirm":
                    self.stdout.write("private_json_value_required=true\n")
                    self.stdout.flush()
                    value = read_private_json(self.stdin)
                response = self.client.annotate(self.annotation_selection, kind, value, expected, operation)
                # Keep the selected pinned page unchanged. Neither success nor
                # stale failure automatically turns it into a new human edit.
            else:
                raise InterfaceError("invalid_request")
        except (ValueError, InterfaceError, UnsafeRoot) as exc:
            response = failure("annotation", "", getattr(exc, "code", "invalid_request"))
        self.stdout.write("SCREEN annotations\n")
        self.stdout.write(render(response, private))
        self.stdout.flush()

    def _overview(self):
        # The overview screen is an Adapter over the shared Interface: the
        # versioned overview supplies the honest counts and the status read
        # supplies the durable policy/capacity keys the screen has always
        # shown. Neither opens storage; neither probes the daemon.
        status = self.client.status()
        overview = self.client.query("overview")
        self.stdout.write("SCREEN overview\n")
        self.stdout.write("interface_version=%s\n" % INTERFACE_VERSION)
        self._write_status(status)
        body = overview.get("body") or {}
        if overview.get("ok"):
            population = body.get("population") or {}
            storage = body.get("storage") or {}
            freshness = body.get("freshness") or {}
            self.stdout.write(
                "query_version=%s\n" % _plain(body.get("query_version"))
            )
            self.stdout.write(
                "population.observations=%s\n" % _plain(population.get("observations"))
            )
            managed = storage.get("managed") or {}
            self.stdout.write(
                "storage.managed.total_bytes=%s\n" % _plain(managed.get("total_bytes"))
            )
            self.stdout.write(
                "freshness.publication_state=%s\n"
                % _plain(freshness.get("publication_state"))
            )
            self.stdout.write(
                "freshness.received_unpublished=%s\n"
                % _plain(freshness.get("received_unpublished"))
            )
            operations = (body.get("timing") or {}).get("operations") or []
            for bucket in operations:
                self.stdout.write(
                    "timing.operation=%s valid=%s invalid=%s unknown=%s\n"
                    % (
                        _plain(bucket.get("operation")),
                        _plain(bucket.get("valid_samples")),
                        _plain(bucket.get("invalid_samples")),
                        _plain(bucket.get("unknown_samples")),
                    )
                )
        self.stdout.write("inference_availability=not_observed\n")
        self.stdout.write("ranking_benefit=false\n")
        self.stdout.write("five_view_complete=false\n")
        self.stdout.write("content_included=false\n")
        self.stdout.flush()

    def _timeline(self):
        response = self.client.query("timeline", page_size=20)
        self.stdout.write("SCREEN timeline\n")
        body = response.get("body") or {}
        self.stdout.write("content_included=false\n")
        self.stdout.write("ordering=%s\n" % body.get("ordering", "durable_seq_ascending"))
        for row in body.get("observations") or []:
            missing = ",".join(row.get("incompleteness") or []) or "none"
            self.stdout.write(
                "seq=%s process=%s kind=%s missing=%s host_persistence=%s\n"
                % (
                    row.get("durable_seq"),
                    row.get("process_id"),
                    row.get("observation_kind"),
                    missing,
                    row.get("host_persistence"),
                )
            )
        self.stdout.flush()

    def _timing(self):
        response = self.client.query("timing")
        self.stdout.write("SCREEN timing\n")
        body = response.get("body") or {}
        if not response.get("ok"):
            code = (response.get("error") or {}).get("code", "collector_unavailable")
            self.stdout.write("code=%s\ncontent_included=false\n" % code)
            self.stdout.flush()
            return
        self.stdout.write("content_included=false\n")
        self.stdout.write("frontend_timing_version=%s\n" % body.get("frontend_timing_version"))
        self.stdout.write(
            "unavailable_total=%s\n" % _plain(body.get("unavailable_total"))
        )
        for bucket in body.get("operations") or []:
            distributions = bucket.get("distributions") or {}
            valid = distributions.get("valid") or {}
            percentiles_block = valid.get("percentiles") or {}
            self.stdout.write(
                "operation=%s valid=%s invalid=%s unknown=%s p50=%s p95=%s p99=%s small_n=%s\n"
                % (
                    _plain(bucket.get("operation")),
                    _plain(bucket.get("valid_samples")),
                    _plain(bucket.get("invalid_samples")),
                    _plain(bucket.get("unknown_samples")),
                    _plain(percentiles_block.get("p50")),
                    _plain(percentiles_block.get("p95")),
                    _plain(percentiles_block.get("p99")),
                    _plain(valid.get("small_n")),
                )
            )
        self.stdout.flush()

    def _expand(self, process_id):
        response = self.client.query("process", process_id=process_id, private_detail=True, page_size=20)
        self.stdout.write("SCREEN private-detail\n")
        self.stdout.write("content_included=true\n")
        body = response.get("body") or {}
        for row in body.get("observations") or []:
            payload = row.get("payload")
            rendered = escape_terminal_data(_payload_text(payload))
            self.stdout.write(
                "process=%s kind=%s host_persistence=%s text=%s\n"
                % (row.get("process_id"), row.get("observation_kind"), row.get("host_persistence"), rendered)
            )
        if not (body.get("observations") or []):
            self.stdout.write("code=not_found\n")
        self.stdout.flush()

    def _policy(self, desired):
        status = self.client.status()
        revision = ((status.get("body") or {}).get("desired_revision"))
        response = self.client.set_policy(desired, revision)
        self.stdout.write("SCREEN control\n")
        if not response.get("ok"):
            code = (response.get("error") or {}).get("code", "invalid_request")
            self.stdout.write("code=%s\ncontent_included=false\n" % code)
        else:
            self._write_status(response)
            self.stdout.write("content_included=false\n")
        self.stdout.flush()

    def _write_status(self, response):
        body = response.get("body") or {}
        if not response.get("ok"):
            code = (response.get("error") or {}).get("code", "collector_unavailable")
            self.stdout.write("code=%s\n" % code)
            return
        for key in (
            "desired_policy",
            "desired_revision",
            "desired_durable",
            "collector_effective",
            "globally_effective",
            "scope",
            "durable_seq",
            "crash_tail",
            "known_dropped_units",
            "capacity_stop",
            "warning",
            "storage_failure",
        ):
            self.stdout.write("%s=%s\n" % (key, _plain(body.get(key))))
        self.stdout.write(_DISCLOSURE + "\n")
        self.stdout.write("legacy_switch_changed=false\n")
        self.stdout.write("scope=input_archive_only\n")


def _plain(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "unknown"
    return escape_terminal_data(str(value))


def _payload_text(payload):
    if isinstance(payload, dict):
        return str(payload.get("text", ""))
    if payload is None:
        return ""
    return str(payload)


def run(client, stdin, stdout):
    TuiSession(client, stdin, stdout).run()
