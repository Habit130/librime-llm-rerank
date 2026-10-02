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
        if command == "overview":
            self._overview()
        elif command == "timeline":
            self._timeline()
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

    def _overview(self):
        response = self.client.query("overview")
        self.stdout.write("SCREEN overview\n")
        self.stdout.write("interface_version=%s\n" % INTERFACE_VERSION)
        self._write_status(response)
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
