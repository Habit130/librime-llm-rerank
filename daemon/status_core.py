#!/usr/bin/env python3
"""Reusable status core for the semantic memory (Habit130/squirrel#51).

This module is NOT a CLI: argument parsing, `--json` / `--schema` flags and
process plumbing land with the `squirrel-semantic-memory` skeleton (#52). It
owns the status model, the observable-condition classification, the
JSON/human renderings and the 0/1/2 exit-code rule, so the CLI only wires
`collect_status` / `render_human` / `compute_exit_code`.

Privacy contract (spec "状态契约"): no output — JSON, human text or error
object — ever contains 上文, candidate text, canonical input or embeddings.
Only schema ids, stable codes, UUIDs, counts, clock values and timestamps.

Observable-condition mapping (design decision, #51):

- Config source per schema (mirrors the C++ ResolveSwitchConfig):
  * any v2 key present  -> v2. Missing v2 keys default to false (adoption is
    explicit; the documented v2 block writes all three keys, true/true/false).
    Coexisting legacy `enable` is ignored and flags deprecation_warning.
  * only `enable`        -> legacy. Reranking follows it, recording and
    semantic evidence are off (no silent collection, user story 26).
  * no keys at all       -> not_configured. Behavior keeps phase-1 defaults
    (visible reranking active, no evidence term, no
    recording); status reports not_configured so it is never confused with an
    intentional off.
- Duty states per schema (config.runtime_effective):
  * reranking: off when v2 says so; otherwise on unless the schema needs the
    daemon (alpha > 0) and it is offline/unknown.
  * recording: off unless v2 recording_enabled; on requires healthy facts
    (degraded/blocked/unknown fault states propagate).
  * evidence: off unless v2 evidence_enabled; suppressed by
    reranking disabled (`suppressed_by_reranking_disabled`) or gamma <= 0
    (`suppressed_by_gamma_zero`). The evidence term is the daemon-served
    semantic retrieval evidence (#61); the daemon's ability to serve it
    (representation seam health) joins status reporting later.
- Facts (global, read-only from disk): healthy / not_created (pristine zero
  evidence, not a fault) / degraded (transient: open/write failures) /
  blocked (deterministic: permission, owner, symlink, corrupt, unsupported
  version, invalid clock) / unknown (cannot be located or proven).
- Serving: up / offline (connect refused) / unknown (reachable but no valid
  health handshake). Probing never loads the model and never starts the
  daemon; the health request kind is model-free.
- Exit code: 0 = snapshot formed and no enabled duty is degraded/blocked/
  unknown (intentional off, not_configured, suppressed and zero evidence are
  not errors); 1 = snapshot formed but some enabled duty is degraded/blocked/
  unknown (includes daemon offline while a duty depends on it); 2 = no
  trustworthy snapshot could be formed (missing rime dir, assembly failure)
  or usage error (CLI side, #52).
"""

import json
import os
import socket
import sqlite3
import stat
from datetime import datetime, timezone

import yaml

from maintenance import MaintenanceError, MaintenanceLock, read_recording_gap

STATUS_VERSION = 2
NAMESPACE = "llm_rerank"
SWITCH_KEYS = ("reranking_enabled", "recording_enabled", "evidence_enabled")
LEGACY_KEY = "enable"
FACT_DB_FILENAME = "facts.sqlite3"
FACT_SCHEMA_VERSION = 1
DEFAULT_GAMMA = 2.0
DEFAULT_ALPHA = 0.0
HEALTH_DEADLINE_SECONDS = 2.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _iso(ms):
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Config resolution (mirrors src/llm_rerank_config.cc)
# ---------------------------------------------------------------------------

def resolve_switch_config(section):
    """Resolve the three switches from the resolved `llm_rerank:` YAML map.

    A key that is present but not a YAML boolean counts as absent (mirrors
    librime's Config::GetBool). Returns a dict with source / legacy_enable /
    deprecation_warning / configured / explicit_keys.
    """
    section = section if isinstance(section, dict) else {}
    explicit = {
        key: isinstance(section.get(key), bool) for key in SWITCH_KEYS
    }
    configured = {}
    for key in SWITCH_KEYS:
        value = section.get(key)
        configured[key] = bool(value) if isinstance(value, bool) else False

    legacy_value = section.get(LEGACY_KEY)
    has_legacy = isinstance(legacy_value, bool)
    legacy_enable = bool(legacy_value) if has_legacy else None

    # Any v2 key present with a bool value (explicit[] alone loses a
    # present-but-false key) -> v2 source.
    has_v2 = any(isinstance(section.get(key), bool) for key in SWITCH_KEYS)
    if has_v2:
        source = "v2"
        deprecation = has_legacy
    elif has_legacy:
        source = "legacy"
        configured = {
            "reranking_enabled": legacy_enable,
            "recording_enabled": False,
            "evidence_enabled": False,
        }
        deprecation = False
    else:
        source = "not_configured"
        configured = {
            "reranking_enabled": True,  # phase-1 default behavior
            "recording_enabled": False,
            "evidence_enabled": False,
        }
        deprecation = False
    return {
        "source": source,
        "legacy_enable": legacy_enable,
        "deprecation_warning": deprecation,
        "configured": configured,
        "explicit_keys": explicit,
    }


def _number(section, key, default):
    value = section.get(key) if isinstance(section, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


# ---------------------------------------------------------------------------
# Facts (read-only, provable from disk)
# ---------------------------------------------------------------------------

def _classify_fault(code):
    # Deterministic conditions need human action (blocked); transient I/O
    # conditions are degraded; an unprovable location is unknown.
    blocked = {
        "root_not_directory", "root_symlink", "root_owner", "root_permission",
        "db_symlink", "db_not_regular", "db_owner", "db_permission",
        "db_corrupt", "db_unsupported_version", "db_clock_invalid",
    }
    if code in blocked:
        return "blocked"
    if code in {"root_create_failed", "db_open_failed", "db_write_failed"}:
        return "degraded"
    return "unknown"


def _exact_mode(path, mode):
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == mode
    except OSError:
        return False


def _read_facts(facts_root):
    """Read the fact store state without ever writing to it.

    Returns a dict with health, fault_code and the provable facts fields.
    `not_created` means no store exists yet: pristine zero-evidence state,
    not a fault. `unknown` means the store could not be proven either way.
    """
    observed_at = _now_iso()
    root = os.path.join(facts_root, "") if facts_root else ""
    if not facts_root:
        return _facts_section(observed_at, "unknown", "no_home")
    if not os.path.lexists(root):
        return _facts_section(observed_at, "not_created", None)
    try:
        st = os.lstat(root)
    except OSError:
        return _facts_section(observed_at, "unknown", "no_home")
    if stat.S_ISLNK(st.st_mode):
        return _facts_section(observed_at, "blocked", "root_symlink")
    if not stat.S_ISDIR(st.st_mode):
        return _facts_section(observed_at, "blocked", "root_not_directory")
    if st.st_uid != os.getuid():
        return _facts_section(observed_at, "blocked", "root_owner")
    if not _exact_mode(root, 0o700):
        return _facts_section(observed_at, "blocked", "root_permission")

    db_path = os.path.join(facts_root, FACT_DB_FILENAME)
    if not os.path.lexists(db_path):
        facts = _facts_section(observed_at, "not_created", None)
        gap = read_recording_gap(facts_root)
        # A pristine root has neither facts nor a gap record. Any durable or
        # unsafe gap artifact must remain observable even after a replacement
        # has removed the facts database.
        if not (gap["state"] == "unknown" and gap["reason"] == "gap_missing"):
            facts["recording_gaps"] = gap
        return facts
    try:
        st = os.lstat(db_path)
    except OSError:
        return _facts_section(observed_at, "unknown", "no_home")
    if stat.S_ISLNK(st.st_mode):
        return _facts_section(observed_at, "blocked", "db_symlink")
    if not stat.S_ISREG(st.st_mode):
        return _facts_section(observed_at, "blocked", "db_not_regular")
    if st.st_uid != os.getuid():
        return _facts_section(observed_at, "blocked", "db_owner")
    if not _exact_mode(db_path, 0o600):
        return _facts_section(observed_at, "blocked", "db_permission")

    try:
        # A daemon/status fact handle has the same shared lease for its full
        # SQLite lifetime as a C++ reader. An exclusive maintainer therefore
        # sees no hidden WAL reader when prepare has completed.
        lease = MaintenanceLock(facts_root, exclusive=False, nonblocking=True,
                                create=False)
        lease.acquire()
    except MaintenanceError as error:
        if error.code == "maintenance_locked":
            return _facts_section(observed_at, "degraded", "maintenance_in_progress")
        return _facts_section(observed_at, "unknown", error.code)
    try:
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, timeout=0
            )
        except sqlite3.Error:
            return _facts_section(observed_at, "degraded", "db_open_failed")
        try:
            row = conn.execute("PRAGMA quick_check;").fetchone()
        except sqlite3.Error:
            return _facts_section(observed_at, "blocked", "db_corrupt")
        if not row or row[0] != "ok":
            return _facts_section(observed_at, "blocked", "db_corrupt")

        meta = {}
        try:
            for key, value in conn.execute("SELECT key, value FROM meta;"):
                meta[key] = value
        except sqlite3.Error:
            return _facts_section(observed_at, "blocked", "db_clock_invalid")

        def meta_int(key):
            try:
                return int(meta.get(key))
            except (TypeError, ValueError):
                return None

        if meta.get("fact_schema_version") != str(FACT_SCHEMA_VERSION):
            return _facts_section(observed_at, "blocked",
                                  "db_unsupported_version")
        physical = meta_int("hlc_physical_ms")
        logical = meta_int("hlc_logical")
        if (not meta.get("history_id") or not meta.get("store_epoch")
                or physical is None or physical < 0
                or logical is None or logical < 0):
            return _facts_section(observed_at, "blocked", "db_clock_invalid")

        def count(sql):
            row = conn.execute(sql).fetchone()
            return row[0] if row is not None else None

        try:
            active_events = count("SELECT COUNT(*) FROM active_events;")
            total_events = count("SELECT COUNT(*) FROM selection_events;")
            retracted_commits = count("SELECT COUNT(*) FROM retractions;")
            last_commit_ms = count(
                "SELECT MAX(utc_committed_at_ms) FROM selection_events;"
            )
            last_retraction_ms = count(
                "SELECT MAX(utc_retracted_at_ms) FROM retractions;"
            )
        except sqlite3.Error:
            return _facts_section(observed_at, "blocked", "db_corrupt")

        last_write = max(
            (ms for ms in (last_commit_ms, last_retraction_ms) if ms),
            default=None,
        )
        return {
            "observed_at": observed_at,
            "health": "healthy",
            "fault_code": None,
            "history_id": meta.get("history_id"),
            "store_epoch": meta.get("store_epoch"),
            "fact_schema_version": meta_int("fact_schema_version"),
            "event_format_version": meta_int("event_format_version"),
            "active_events": active_events,
            "retracted_commits": retracted_commits,
            "total_events": total_events,
            "fact_high_water": {
                "hlc_physical_ms": physical,
                "hlc_logical": logical,
            },
            "last_write_at_ms": last_write,
            "last_write_at": _iso(last_write),
            "recording_gaps": read_recording_gap(facts_root),
        }
    finally:
        if "conn" in locals():
            conn.close()
        lease.release()


def _facts_section(observed_at, health, fault_code):
    return {
        "observed_at": observed_at,
        "health": health,
        "fault_code": fault_code,
        "history_id": None,
        "store_epoch": None,
        "fact_schema_version": None,
        "event_format_version": None,
        "active_events": None,
        "retracted_commits": None,
        "total_events": None,
        "fact_high_water": {"hlc_physical_ms": None, "hlc_logical": None},
        "last_write_at_ms": None,
        "last_write_at": None,
        "recording_gaps": {
            "state": "none" if health == "not_created" else "unknown",
            "reason": "none" if health == "not_created"
            else "facts_unprovable",
        },
    }


# ---------------------------------------------------------------------------
# Serving (daemon health handshake, model-free)
# ---------------------------------------------------------------------------

def probe_daemon(socket_path, deadline_s=HEALTH_DEADLINE_SECONDS):
    """Probe the daemon with the model-free health handshake.

    Never loads the model and never starts the daemon. Returns serving state
    plus whatever the daemon truthfully reports; unprovable fields are None.
    """
    observed_at = _now_iso()
    request = {
        "version": 2,
        "request_id": "status-health",
        "kind": "health",
    }
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError:
        return _serving_section(observed_at, "unknown")
    try:
        sock.settimeout(deadline_s)
        try:
            sock.connect(socket_path)
        except (FileNotFoundError, ConnectionRefusedError, PermissionError,
                OSError):
            # Nothing is listening: provably offline.
            return _serving_section(observed_at, "offline")
        try:
            sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError:
            # Connected but the daemon dropped or wedged the connection: the
            # serving state cannot be proven.
            return _serving_section(observed_at, "unknown")
        response = json.loads(b"".join(chunks).decode("utf-8"))
        health = response.get("health")
        if (
            not isinstance(response, dict)
            or response.get("kind") != "health"
            or not isinstance(health, dict)
        ):
            return _serving_section(observed_at, "unknown")
        state = "up"
        if health.get("maintenance_state") not in (None, "serving"):
            state = "unknown"
        return {
            "observed_at": observed_at,
            "state": state,
            "model_loaded": bool(health.get("model_loaded")),
            "policy_id": health.get("policy_id"),
            "scoring_strategy": health.get("scoring_strategy"),
            "model_identity": health.get("model_identity"),
            "daemon_pid": health.get("pid"),
            "context_window": health.get("context_window"),
        }
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError,
            socket.timeout):
        return _serving_section(observed_at, "unknown")
    finally:
        sock.close()


def _serving_section(observed_at, state):
    return {
        "observed_at": observed_at,
        "state": state,
        "model_loaded": None,
        "policy_id": None,
        "scoring_strategy": None,
        "model_identity": None,
        "daemon_pid": None,
        "context_window": None,
    }


# ---------------------------------------------------------------------------
# Per-schema duty classification
# ---------------------------------------------------------------------------

def _duty_state(source, configured, alpha, gamma, facts, serving, duty):
    """Classify one duty's runtime effective state from observable
    conditions. Returns (state, reason)."""
    if duty == "reranking":
        if source == "v2" and not configured["reranking_enabled"]:
            return "off", "explicitly_disabled"
        if source == "v2":
            if alpha > 0:
                if serving["state"] == "offline":
                    return "degraded", "daemon_offline"
                if serving["state"] == "unknown":
                    return "unknown", "serving_unverifiable"
            return "on", None
        # legacy / not_configured: phase-1 visible reranking.
        if source == "legacy" and not configured["reranking_enabled"]:
            return "off", "legacy_disabled"
        if alpha > 0:
            if serving["state"] == "offline":
                return "degraded", "daemon_offline"
            if serving["state"] == "unknown":
                return "unknown", "serving_unverifiable"
        return "on", None

    if duty == "recording":
        if source != "v2" or not configured["recording_enabled"]:
            reason = {
                "v2": "explicitly_disabled",
                "legacy": "legacy_default",
                "not_configured": "not_configured",
            }[source]
            return "off", reason
        if facts["health"] in ("healthy", "not_created"):
            gap = facts.get("recording_gaps")
            gap_state = gap.get("state") if isinstance(gap, dict) else "unknown"
            if gap_state == "present":
                return "degraded", "recording_gap_present"
            if gap_state != "none":
                reason = gap.get("reason") if isinstance(gap, dict) else None
                return "unknown", reason or "recording_gap_unverifiable"
            if facts["health"] == "healthy":
                return "on", None
            return "on", "zero_evidence"
        if facts["health"] == "unknown":
            return "unknown", facts["fault_code"] or "facts_unprovable"
        # degraded / blocked
        return facts["health"], facts["fault_code"]

    # duty == "evidence"
    if source != "v2" or not configured["evidence_enabled"]:
        reason = {
            "v2": "explicitly_disabled",
            "legacy": "legacy_default",
            "not_configured": "not_configured",
        }[source]
        return "off", reason
    if not configured["reranking_enabled"]:
        return "suppressed", "suppressed_by_reranking_disabled"
    # gamma <= 0 means the evidence term has zero weight (γ>0 is part of the
    # evidence-valid condition, spec "三个配置开关").
    if gamma <= 0:
        return "suppressed", "suppressed_by_gamma_zero"
    return "on", None


def _schema_config_entry(schema_id, section, alpha, gamma, facts, serving):
    resolved = resolve_switch_config(section)
    configured = resolved["configured"]
    observed_at = _now_iso()
    duties = {}
    for duty in ("reranking", "recording", "evidence"):
        state, reason = _duty_state(resolved["source"], configured, alpha,
                                    gamma, facts, serving, duty)
        duties[duty] = {"state": state, "reason": reason}
    baseline_policy_id = section.get("baseline_policy_id")
    if not isinstance(baseline_policy_id, str) or not baseline_policy_id:
        baseline_policy_id = None
    return {
        "schema_id": schema_id,
        "config": {
            "source": resolved["source"],
            "legacy_enable": resolved["legacy_enable"],
            "deprecation_warning": resolved["deprecation_warning"],
            "observed_at": observed_at,
            "configured": configured,
            "explicit_keys": resolved["explicit_keys"],
            "gamma": gamma,
            "alpha": alpha,
            "baseline_policy_id": baseline_policy_id,
            "runtime_effective": {"observed_at": observed_at, **duties},
        },
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _component_schemas(rime_dir):
    """Deployed schemas that load a semantic-memory component.

    A schema counts as configured-component when its resolved build config
    has an `llm_rerank` section or lists llm_rerank / llm_rerank_recorder in
    its engine processors or filters.

    The schema list comes from the resolved default config: a deployed
    Squirrel user data dir keeps the merged result under `build/default.yaml`
    and does not carry a root-level `default.yaml` (that file is a shared
    data artifact). Prefer the root file when present (test fixtures), then
    the deployment-resolved build file.
    """
    build_dir = os.path.join(rime_dir, "build")
    for candidate in (os.path.join(rime_dir, "default.yaml"),
                      os.path.join(build_dir, "default.yaml")):
        if os.path.isfile(candidate):
            default_path = candidate
            break
    else:
        return None
    try:
        with open(default_path, encoding="utf-8") as f:
            default = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None
    schema_list = []
    for entry in default.get("schema_list", []):
        if isinstance(entry, dict) and isinstance(entry.get("schema"), str):
            schema_list.append(entry["schema"])
        elif isinstance(entry, str):
            schema_list.append(entry)
    result = []
    for schema_id in schema_list:
        path = os.path.join(build_dir, f"{schema_id}.schema.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                resolved = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            continue
        engine = resolved.get("engine") if isinstance(resolved.get("engine"),
                                                      dict) else {}
        processors = engine.get("processors") or []
        filters = engine.get("filters") or []
        names = [
            str(item) for item in list(processors) + list(filters)
            if isinstance(item, (str, dict))
        ]
        llm_rerank_section = resolved.get(NAMESPACE)
        has_component = (
            isinstance(llm_rerank_section, dict)
            or any(name.startswith(NAMESPACE) for name in names)
        )
        if has_component:
            result.append((schema_id, resolved))
    return result


def collect_status(rime_dir, facts_root, daemon_socket, now=None):
    """Assemble the versioned status snapshot.

    Never starts the daemon and never loads the model; all facts fields are
    provable from disk. Any assembly failure returns a snapshot_ok=false
    report with exit code 2 (no exception with raw text escapes).
    """
    generated_at = now or _now_iso()

    def failure(code):
        return {
            "status_version": STATUS_VERSION,
            "generated_at": generated_at,
            "snapshot_ok": False,
            "error": {"code": code, "message": _STABLE_MESSAGES[code]},
            "schemas": [],
            "facts": _facts_section(generated_at, "unknown", None),
            "serving": _serving_section(generated_at, "unknown"),
            "exit_code": 2,
        }

    if not rime_dir:
        return failure("rime_dir_unavailable")
    schemas = _component_schemas(rime_dir)
    if schemas is None:
        return failure("rime_dir_unavailable")

    facts = _read_facts(facts_root)
    serving = probe_daemon(daemon_socket)
    entries = []
    for schema_id, resolved in schemas:
        section = resolved.get(NAMESPACE)
        section = section if isinstance(section, dict) else {}
        alpha = _number(section, "alpha", DEFAULT_ALPHA)
        gamma = _number(section, "gamma", DEFAULT_GAMMA)
        entries.append(_schema_config_entry(schema_id, section, alpha, gamma,
                                            facts, serving))
    report = {
        "status_version": STATUS_VERSION,
        "generated_at": generated_at,
        "snapshot_ok": True,
        "schemas": entries,
        "facts": facts,
        "serving": serving,
    }
    report["exit_code"] = compute_exit_code(report)
    return report


_STABLE_MESSAGES = {
    "rime_dir_unavailable": "the rime data directory is not readable",
    "status_assembly_failed": "the status snapshot could not be assembled",
}


def compute_exit_code(report):
    """0 healthy (intentional off / suppressed / zero evidence included);
    1 some enabled duty degraded/blocked/unknown; 2 snapshot not formed."""
    if not report.get("snapshot_ok", False):
        return 2
    gap = (report.get("facts") or {}).get("recording_gaps")
    if isinstance(gap, dict) and gap.get("state") in ("present", "unknown"):
        return 1
    for entry in report.get("schemas", []):
        duties = entry["config"]["runtime_effective"]
        for duty in ("reranking", "recording", "evidence"):
            if duties[duty]["state"] in ("degraded", "blocked", "unknown"):
                return 1
    return 0


# ---------------------------------------------------------------------------
# Human rendering (no raw text anywhere)
# ---------------------------------------------------------------------------

def render_human(report):
    lines = [
        f"Semantic memory status (status_version {report.get('status_version', STATUS_VERSION)})",
        f"generated_at: {report.get('generated_at')}",
    ]
    if not report.get("snapshot_ok", False):
        error = report.get("error") or {}
        lines.append(f"snapshot: failed ({error.get('code', 'unknown')})")
        lines.append(f"exit: {report.get('exit_code', 2)}")
        return "\n".join(lines)
    schemas = report.get("schemas", [])
    lines.append(f"schemas ({len(schemas)}):")
    if not schemas:
        lines.append("  (none)")
    for entry in schemas:
        config = entry["config"]
        duties = config["runtime_effective"]
        parts = [
            f"{duty}: {duties[duty]['state']}"
            + (f" ({duties[duty]['reason']})" if duties[duty]["reason"] else "")
            for duty in ("reranking", "recording", "evidence")
        ]
        warning = " [legacy enable ignored: v2 keys win]" if config[
            "deprecation_warning"] else ""
        policy = f"; policy {config['baseline_policy_id']}" if config.get(
            "baseline_policy_id") else ""
        lines.append(
            f"  {entry['schema_id']}: source={config['source']}{warning}; "
            + "; ".join(parts) + policy
        )
    facts = report.get("facts", {})
    lines.append(
        f"facts: {facts.get('health', 'unknown')}"
        + (f" (fault: {facts['fault_code']})" if facts.get("fault_code") else "")
        + (
            f"; store_epoch {facts['store_epoch']}; schema v"
            f"{facts['fact_schema_version']}; {facts['active_events']} active"
            f" events; {facts['retracted_commits']} retracted commits"
            if facts.get("health") in ("healthy", "not_created")
            else ""
        )
    )
    gap = facts.get("recording_gaps")
    if not isinstance(gap, dict):
        lines.append("recording gap: unknown (gap_unverifiable)")
    elif gap.get("state") == "present":
        lines.append(
            "recording gap: present (%s; %s batches, %s events, %s retractions, "
            "%s bytes)" % (
                gap.get("reason", "unknown"), gap.get("dropped_batches", 0),
                gap.get("dropped_events", 0), gap.get("dropped_retractions", 0),
                gap.get("dropped_bytes", 0),
            )
        )
    elif gap.get("state") == "unknown":
        lines.append("recording gap: unknown (%s)" % gap.get("reason", "unknown"))
    else:
        lines.append("recording gap: none")
    serving = report.get("serving", {})
    serving_line = f"serving: {serving.get('state', 'unknown')}"
    if serving.get("state") == "up":
        loaded = "loaded" if serving.get("model_loaded") else "not loaded"
        serving_line += f" (model {loaded}"
        if serving.get("model_identity"):
            serving_line += f", {serving['model_identity']}"
        if serving.get("policy_id"):
            serving_line += f"; policy {serving['policy_id']}"
        serving_line += ")"
    lines.append(serving_line)
    lines.append(f"exit: {report.get('exit_code', 2)}")
    return "\n".join(lines)
