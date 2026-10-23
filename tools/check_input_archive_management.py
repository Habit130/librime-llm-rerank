#!/usr/bin/env python3
"""Finite MGMT195 controls over genuine collectors, producers and Adapters.

Only fresh, explicitly supplied, owned invented fixtures. No model/scoring probe,
live archive, arbitrary backup discovery or production producer modification.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.abc
import io
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
from archive.collector import Collector
from archive.interface import Client, InterfaceError, canonical_bytes
from archive.limits import resolve
from archive.management import CORE, Management, code_identity
from archive.management_authority import VERSION
from archive import management_authority as authority_module
from archive import management_io as private_io
from archive.producer import Producer
from archive.safety import UnsafeRoot, validate_root
from archive.tui import TuiSession

CANARY = "MGMT195PRIVATECANARY"
TEXT = "虚构春风样例" + CANARY + "\x1b[31m\x85"
CASES = ("CoherentScopeAndSemanticBackup", "ImmutableRetriesAndSourceAbsent",
         "TamperVersionsAndUnsafePaths", "RestoreRetentionAndStalePreflight",
         "PausedOffAndPersistentAuthority", "JobsProgressCancellationAndDetach",
         "TransactionFaultsAndCrashRecovery", "PythonDelayedBatchAndFreshProducer",
         "NativeDelayedReceiptAndFreshProducer", "Scales256And4096",
         "CLIAndManagementTUIPrivacy", "AuthorityBoundsAndInputIndependence")


class Failure(Exception):
    pass


def require(value, code):
    if not value:
        raise Failure(code)


def body(response):
    require(response.get("ok"), "interface_refusal:" + str(response.get("error", {}).get("code", "unknown")))
    return response["body"]


def error(response, code):
    require(not response.get("ok") and response.get("error", {}).get("code") == code, "expected_refusal:" + code)


def wait(predicate, code="deadline", seconds=30):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        result = predicate()
        if result:
            return result
        time.sleep(.01)
    raise Failure(code)


def no_private(value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    require(CANARY not in raw and "虚构春风样例" not in raw and "\\u865a\\u6784\\u6625" not in raw, "private_output")
    require("\x1b" not in raw and "\x85" not in raw, "terminal_output")


def observation(source, seq, kind="commit_attempt", **extra):
    return {"schema_id": "luna_pinyin", "source_instance_id": source, "source_local_sequence": seq,
            "process_id": "process-" + str(seq // 2), "observation_kind": kind,
            "outcome": "observed_attempt", "continuity_segment_id": "segment-" + str(seq // 2),
            "update_id": "shared-high-fanout-update", "payload": {"text": TEXT}, **extra}


def hashes(root, names=CORE):
    return {name: private_io.measure(Path(root) / name) for name in names}


def inventory(root):
    """Bounded fixture inventory; refuses special nodes rather than opening them."""
    result = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        require(len(result) < 20000, "fixture_inventory_bound")
        for name in files:
            path = Path(current) / name
            if path.name in ("collector.sock", "collector.lock", "collector.pid"):
                continue
            st = path.lstat()
            import stat
            require(stat.S_ISREG(st.st_mode), "fixture_special_node")
            result[str(path.relative_to(root))] = (st.st_size, st.st_mode & 0o777, hashlib.sha256(path.read_bytes()).hexdigest(), st.st_ctime_ns)
    return result


class Fixture:
    def __init__(self, root, crash=None, restart=False):
        self.root = Path(root)
        self.crash = crash
        self.proc = None
        self.thread = None
        self.collector = None
        self.client = Client(str(self.root / "collector.sock"), timeout=10)
        self.start(restart)

    def start(self, restart=False):
        if self.crash is not None:
            log = self.root.parent / (self.root.name + "-child-" + uuid.uuid4().hex + ".log")
            self.log = log
            stream = log.open("xb")
            self.proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(self.root), self.crash],
                                         cwd=REPO, stdout=stream, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            stream.close()
        else:
            self.collector = Collector(str(self.root), str(self.root / "collector.sock"), resolve())
            self.collector.prepare()
            self.thread = threading.Thread(target=self.collector.serve, daemon=True)
            self.thread.start()
        wait(lambda: self.client.status().get("ok"), "collector_start")
        status = body(self.client.status())
        self.client.serving_generation = status["management"]["serving_generation"]
        if not restart:
            body(self.client.set_policy("enabled", status["desired_revision"]))

    def close(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.client.shutdown()
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
                    self.proc.wait(5)
        elif self.thread is not None:
            self.client.shutdown()
            self.thread.join(10)
            require(not self.thread.is_alive(), "collector_shutdown")
            self.collector.release_ownership()
        self.thread = self.proc = None

    def restart(self):
        self.close()
        self.crash = None
        self.start(True)

    def register(self, source):
        return body(self.client.call("policy_observe", {"source_instance_id": source,
                           "observed_revision": body(self.client.status())["desired_revision"]}))

    def seed(self, count=4, source="invented-source", start=1):
        self.register(source)
        before = body(self.client.status())["durable_seq"]
        for offset in range(0, count, 32):
            rows = [observation(source, seq, kind="start" if seq % 2 else "commit_attempt") for seq in range(start + offset, min(start + count, start + offset + 32))]
            result = body(self.client.call("admit_batch", {"observations": rows}))
            require(all(code == "admitted" for code in result["codes"]), "fixture_admission")
            expected = before + min(offset + 32, count)
            wait(lambda: body(self.client.checkpoint())["durable_seq"] == expected, "fixture_publication")

    def m(self, action, **kwargs):
        return body(self.client.management(action, **kwargs))

    def job(self, job_id, state="succeeded"):
        result = wait(lambda: self._terminal(job_id), "job_completion", seconds=120)
        require(result["state"] == state, "job_outcome:" + str(result["reason"]))
        return result

    def _terminal(self, job_id):
        response = self.client.management("status", job_id=job_id)
        if response.get("ok") and response["body"]["state"] not in ("pending", "running"):
            if response["body"]["kind"] == "restore" and response["body"]["state"] == "succeeded" and response["body"]["cleanup"] == "pending":
                return None
            return response["body"]
        return None

    def backup(self, operation="backup"):
        plan = self.m("preview")["plan"]
        job = self.m("create", operation_id=operation, plan=plan)["job_id"]
        self.job(job)
        return job, plan

    def restore(self, backup, retention="retain-current", operation="restore"):
        plan = self.m("restore_preview", job_id=backup)["plan"]
        job = self.m("restore_confirm", operation_id=operation, plan=plan, retention=retention, confirm=True)["job_id"]
        result = self.job(job)
        self.client.serving_generation = body(self.client.status())["management"]["serving_generation"]
        return job, result

    def annotate(self):
        page = body(self.client.annotations(page_size=1))
        ref = page["observations"][0]["source_reference"]
        return body(self.client.annotate(ref, "experience", {"kind": "note", "value": "neutral", "note": TEXT}, 0, "invented-human-edit"))

    def dataset(self, operation="dataset"):
        pair = body(self.client.datasets("snapshot"))["snapshot"]
        job = body(self.client.datasets("create", snapshot=pair, operation_id=operation))["job_id"]
        result = wait(lambda: self._dataset_terminal(job), "dataset_completion", seconds=120)
        require(result["state"] == "succeeded", "dataset_fixture_outcome")
        return job

    def _dataset_terminal(self, job):
        result = body(self.client.datasets("status", job_id=job))
        return result if result["state"] not in ("pending", "running") else None


@contextlib.contextmanager
def fixture(root, **kwargs):
    f = Fixture(root, **kwargs)
    try:
        yield f
    finally:
        f.close()


def coherent(root, native):
    with fixture(root) as f:
        f.register("invented-source")
        rows = []
        for index in range(10):
            common = {"process_id": "complete-process-" + str(index), "continuity_segment_id": "complete-segment-" + str(index)}
            rows += [observation("invented-source", 2*index+1, "start", update_id="start-"+str(index), **common),
                     observation("invented-source", 2*index+2, "commit_attempt", update_id="commit-"+str(index), parent_update_id="start-"+str(index), **common)]
        rows.append(observation("invented-source", 21, "start", process_id="open-process", continuity_segment_id="open-segment", update_id="open-update"))
        require(body(f.client.call("admit_batch", {"observations": rows}))["counts"].get("admitted") == 21, "usable_fixture_admission")
        wait(lambda: body(f.client.checkpoint())["durable_seq"] == 21, "usable_fixture_publication")
        # Confirm/correct values use the supported shared annotation Interface.
        page = body(f.client.annotations(page_size=1))
        ref = page["observations"][0]["source_reference"]
        body(f.client.annotate(ref, "correct", {"text": TEXT}, 0, "human-correction"))
        dataset = f.dataset()
        dataset_status = body(f.client.datasets("status", job_id=dataset))
        require(dataset_status["outcome"] == "usable" and dataset_status["current"]["default_training_candidate"], "usable_dataset_positive_control")
        before = hashes(f.root)
        backup, plan = f.backup()
        verified = f.m("verify", job_id=backup)
        require(before == hashes(f.root), "backup_mutated_source")
        require(plan["counts"]["datasets"] == 1 and plan["counts"]["annotation_revisions"] == 1, "coherent_counts")
        require(plan["counts"]["files"] == 11 and "other_backup_and_retained_payloads" in plan["exclusions"], "scope_exclusions")
        require(f.m("create", operation_id="backup", plan=plan)["job_id"] == backup, "backup_retry")
        drift = dict(plan, counts={**plan["counts"], "observations": 999})
        error(f.client.management("create", operation_id="backup", plan=drift), "management_operation_conflict")
        f.seed(2, source="later-append")
        error(f.client.management("create", operation_id="stale", plan=plan), "management_stale")
        # Hold the real publication after append and before its watermark.
        fifo = root.parent / (root.name + "-publication.fifo")
        os.mkfifo(fifo, 0o600)
        f.collector.phase_hold = str(fifo)
        f.register("held-publication-source")
        body(f.client.call("admit_batch", {"observations": [observation("held-publication-source", 1)]}))
        wait(lambda: body(f.client.status())["publication_phase_hold"], "publication_phase_not_held")
        try:
            error(f.client.management("preview"), "management_busy")
        finally:
            f.collector.phase_hold = ""
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK); os.write(fd, b"x"); os.close(fd)
        wait(lambda: body(f.client.checkpoint())["durable_seq"] == 24, "held_publication_release")
        # A later annotation cannot silently replace the confirmed revision.
        annotation_plan = f.m("preview")["plan"]
        body(f.client.annotate(ref, "correct", {"text": "虚构另一个修订"}, 1, "later-correction"))
        error(f.client.management("create", operation_id="annotation-stale", plan=annotation_plan), "management_stale")
        entered, release = threading.Event(), threading.Event()
        inspect = f.collector._datasets.inspect
        def held_dataset(*args, **kwargs):
            entered.set(); release.wait(20)
            return inspect(*args, **kwargs)
        f.collector._datasets.inspect = held_dataset
        pair = body(f.client.datasets("snapshot"))["snapshot"]
        concurrent = body(f.client.datasets("create", snapshot=pair, operation_id="held-dataset-publication"))["job_id"]
        try:
            require(entered.wait(5), "dataset_publication_not_held")
            error(f.client.management("preview"), "management_busy")
        finally: release.set()
        require(wait(lambda: f._dataset_terminal(concurrent))["state"] == "succeeded", "dataset_publication_release")
        f.collector._datasets.inspect = inspect
        f.restore(backup)
        restored_dataset = body(f.client.datasets("status", job_id=dataset))
        require(not restored_dataset["current"]["default_training_candidate"] and restored_dataset["current"].get("historical_restored_freeze"), "restored_freeze_became_default")
        no_private(verified)
        return {"frontier": plan["frontier"], "counts": plan["counts"], "dataset_id": dataset,
                "source_unchanged": before, "verified_identity": verified["content_identity"], "stale_append_refused": True,
                "usable_dataset_default_before_restore": True, "historical_dataset_default_after_restore": False}


def immutable(root, native):
    with fixture(root) as f:
        f.seed()
        backup, plan = f.backup()
        path = f.root / "management" / "jobs" / backup / "backup"
        before = inventory(path)
        source = f.root / "observations.jsonl"
        absent = f.root / "test-only-source-absent.jsonl"
        source.rename(absent)  # owned fixture mutation; not a feature-created copy
        try:
            require(f.m("verify", job_id=backup)["verified"], "source_absent_verify")
            require(before == inventory(path), "verify_mutated_backup")
        finally:
            absent.rename(source)
        f.restart()
        require(f.m("create", operation_id="backup", plan=plan)["job_id"] == backup, "restart_retry")
        require(before == inventory(path), "restart_mutated_backup")
        return {"registered_files": len(before), "backup_bytes": sum(r[0] for r in before.values()),
                "source_absent_semantic_verify": True, "immutable_inventory": before}


def tamper(root, native):
    outcomes = {}
    for index, mode in enumerate(("checksum", "version", "path", "mode", "symlink", "hardlink", "fifo")):
        with fixture(root.parent / (root.name + str(index))) as f:
            backup, _ = f.backup()
            path = f.root / "management" / "jobs" / backup / "backup"
            target = path / "observations.jsonl"
            if mode == "checksum":
                with target.open("ab") as stream: stream.write(b"x")
            elif mode in ("version", "path"):
                manifest = json.loads((path / "manifest.json").read_bytes())
                if mode == "version": manifest["version"] = "unsupported"
                else: manifest["plan"]["files"][0]["path"] = "../../outside"
                (path / "manifest.json").write_bytes(canonical_bytes(manifest))
            elif mode == "mode": os.chmod(target, 0o644)
            elif mode == "symlink":
                target.unlink(); target.symlink_to(f.root / "unmanaged-never-created")
            elif mode == "hardlink": os.link(target, f.root / "unmanaged-link")
            elif mode == "fifo": target.unlink(); os.mkfifo(target, 0o600)
            # Do not inventory/open the malicious special node. Metadata and
            # manifest bytes prove verify-only does not fix or chmod it.
            before = (target.lstat().st_mode, (path / "manifest.json").read_bytes())
            response = f.client.management("verify", job_id=backup)
            require(not response.get("ok"), "tamper_accepted")
            require(before == (target.lstat().st_mode, (path / "manifest.json").read_bytes()), "verify_repaired_input")
            no_private(response)
            outcomes[mode] = response["error"]["code"]
    return {"refusals": outcomes, "special_nodes_not_opened": True}


def retention(root, native):
    results = {}
    for index, choice in enumerate(("retain-current", "discard-replaced-current")):
        with fixture(root.parent / (root.name + str(index))) as f:
            f.seed(4)
            backup, plan = f.backup()
            f.seed(2, source="current-only")
            preview = f.m("restore_preview", job_id=backup)["plan"]
            before = hashes(f.root)
            old_cursor = body(f.client.query("timeline", page_size=1))["cursor_token"]
            import archive.management as module
            disk_usage = module.shutil.disk_usage
            module.shutil.disk_usage = lambda path: type("Capacity", (), {"free": 0})()
            try:
                error(f.client.management("restore_confirm", operation_id="capacity", plan=preview,
                                         retention=choice, confirm=True), "management_capacity")
            finally: module.shutil.disk_usage = disk_usage
            error(f.client.management("restore_confirm", operation_id="missing-choice", plan=preview, confirm=True), "invalid_request")
            require(before == hashes(f.root), "preflight_changed_target")
            if index == 0:
                entered, release = threading.Event(), threading.Event()
                read_payload = f.collector._read_payload
                def held_read(entry):
                    entered.set(); release.wait(20)
                    return read_payload(entry)
                f.collector._read_payload = held_read
                query_outcome = []
                reader = threading.Thread(target=lambda: query_outcome.append(f.client.query("process", process_id="process-1", private_detail=True).get("ok")))
                reader.start()
                try:
                    require(entered.wait(5), "genuine_reader_not_held")
                    refused_job = f.m("restore_confirm", operation_id="held-reader", plan=preview, retention=choice, confirm=True)["job_id"]
                    refused_status = f.job(refused_job, "failed")
                    require(refused_status["reason"] == "management_busy", "restore_did_not_refuse_held_reader")
                    require(before == hashes(f.root), "held_reader_switch_changed_target")
                finally:
                    release.set(); reader.join(10)
                    f.collector._read_payload = read_payload
                require(query_outcome == [True], "held_reader_did_not_finish_old_state")
                preview = f.m("restore_preview", job_id=backup)["plan"]
            f.seed(2, source="unconfirmed-later")
            error(f.client.management("restore_confirm", operation_id="stale", plan=preview, retention=choice, confirm=True), "management_stale")
            require(body(f.client.status())["durable_seq"] == 8, "unconfirmed_append_swept")
            old = hashes(f.root)
            job, status = f.restore(backup, choice)
            require(body(f.client.status())["durable_seq"] == 4, "restore_frontier")
            require(f.m("verify", job_id=backup)["verified"], "unrelated_backup_deleted")
            stale_client = Client(str(f.root / "collector.sock"))
            error(stale_client.annotations(), "management_stale")
            error(f.client.annotations(serving_generation=0), "management_stale")
            error(stale_client.query("timeline", cursor_token=old_cursor, page_size=1), "management_stale")
            error(f.client.query("timeline", cursor_token=old_cursor, page_size=1), "cursor_snapshot_unknown")
            if choice == "retain-current": require(old == hashes(f.root), "retention_changed_old_bytes")
            else: require(all(not (f.root / name).exists() for name in CORE), "discard_left_core_unreported")
            response = f.client.management("cancel", job_id=job)
            error(response, "management_committed")
            registry = f.m("registry", job_id=job)
            results[choice] = {"restored_rows": 4, "replaced_rows": 8, "cleanup": status["cleanup"],
                               "registry": registry, "generation": body(f.client.status())["management"]["serving_generation"]}
    return results


def policy(root, native):
    with fixture(root) as f:
        f.seed()
        backup, _ = f.backup()
        transitions = []
        for index, desired in enumerate(("paused", "off")):
            previous = body(f.client.status())
            changed = body(f.client.set_policy(desired, previous["desired_revision"]))
            job, _ = f.restore(backup, operation="restore" + str(index))
            current = body(f.client.status())
            require(current["desired_policy"] == desired and current["desired_revision"] == changed["desired_revision"], "restore_unpaused_policy")
            require(f.register("invented-source")["desired_policy"] != "enabled", "fenced_policy_enabled")
            f.restart()
            require(body(f.client.status())["desired_policy"] == desired, "restart_unpaused")
            require(f.register("invented-source")["registration_code"] == "source_recreation_required", "restart_fence_lost")
            transitions.append({"desired": desired, "revision": current["desired_revision"], "generation": current["management"]["serving_generation"], "job": job})
        current = body(f.client.status())
        body(f.client.set_policy("enabled", current["desired_revision"]))
        f.seed(2, "fresh-after-second-restore")
        require(body(f.client.status())["durable_seq"] == 6, "fresh_after_restart")
        return {"transitions": transitions, "new_source_healthy": True, "reused_old_source_refused": True,
                "authority": f.m("availability"), "legacy_switch_changed": current["legacy_switch_changed"]}


def jobs(root, native):
    with fixture(root) as f:
        f.seed(64)
        entered, release = threading.Event(), threading.Event()
        def hook(phase):
            if phase == "copy_chunk": entered.set(); release.wait(20)
        f.collector._management.hook = hook
        plan = f.m("preview")["plan"]
        job = f.m("create", operation_id="cancel", plan=plan)["job_id"]
        require(entered.wait(5), "held_copy_not_reached")
        progress = f.m("status", job_id=job)
        require(progress["progress_bytes"] > 0, "no_real_progress")
        output = io.StringIO()
        try:
            TuiSession(f.client, io.StringIO("management\nquit\n"), output).run()
            require(f.m("status", job_id=job)["state"] == "running", "detach_cancelled_job")
            TuiSession(f.client, io.StringIO("management-status " + job + "\nmanagement-cancel " + job + "\nquit\n"), output).run()
        finally: release.set()
        cancelled = f.job(job, "cancelled")
        registry = f.m("registry", job_id=job)
        require(any(r["state"] == "incomplete" for r in registry["registry"]), "partial_copy_hidden")
        f.collector._management.hook = lambda phase: None
        completed, _ = f.backup("after-cancel")
        no_private(output.getvalue())
        return {"held_progress": progress, "cancelled": cancelled, "partial_registry": registry,
                "later_completed_job": completed, "detaching_did_not_cancel": True}


def faults(root, native):
    results = {}
    for index, phase in enumerate(("before_restore_commit", "after_restore_commit", "before_backup_commit", "after_backup_commit")):
        leaf = root.parent / (root.name + str(index))
        with fixture(leaf, crash=phase) as f:
            f.seed()
            if "backup" in phase:
                plan = f.m("preview")["plan"]
                response = f.client.management("create", operation_id="crash-backup", plan=plan)
                job = response.get("body", {}).get("job_id")
            else:
                backup, _ = f.backup()
                f.seed(2, source="replaced-before-crash")
                plan = f.m("restore_preview", job_id=backup)["plan"]
                response = f.client.management("restore_confirm", operation_id="crash-restore", plan=plan,
                                               retention="discard-replaced-current", confirm=True)
                job = response.get("body", {}).get("job_id")
            wait(lambda: f.proc.poll() is not None, "injected_crash", seconds=15)
            exit_code = f.proc.returncode
            f.restart()
            current = body(f.client.status())
            if "restore" in phase:
                require(current["durable_seq"] == (6 if phase.startswith("before") else 4), "mixed_crash_result")
                require(current["management"]["serving_generation"] == (0 if phase.startswith("before") else 1), "crash_fence_binding")
            # Lost acknowledgement is resolved by the same operation/request,
            # never a second restore or new staging copy.
            action = "create" if "backup" in phase else "restore_confirm"
            kwargs = {"operation_id": "crash-backup" if "backup" in phase else "crash-restore", "plan": plan}
            if action == "restore_confirm": kwargs.update(retention="discard-replaced-current", confirm=True)
            retry = f.m(action, **kwargs)
            require(retry["state"] == ("unknown" if phase.startswith("before") else "succeeded"), "crash_retry_outcome")
            results[phase] = {"exit": exit_code, "job": job or retry["job_id"], "retry_state": retry["state"],
                              "durable_seq": current["durable_seq"], "generation": current["management"]["serving_generation"],
                              "primary_child_log": str(f.log)}
            if phase == "before_backup_commit":
                require(current["crash_tail"] == "unknown", "genuine_crash_quality_fixture")
                historical, _ = f.backup("post-crash-source")
                f.restore(historical, operation="restore-crash-quality")
                source_quality = body(f.client.status())["management"]["restored_source_quality"]
                require(source_quality[-1]["crash_tail"] == "unknown", "historical_unknown_quality_lost")
                results[phase]["restored_source_crash_tail"] = source_quality[-1]["crash_tail"]
    # Real short-write and fsync/cleanup failure controls are contained to owned
    # fixture I/O, with no product/global fault switch exposed to Adapters.
    with fixture(root.parent / (root.name + "disk")) as f:
        f.seed()
        backup, _ = f.backup()
        original = private_io.write_all
        fired = [False]
        def short(fd, raw):
            if not fired[0] and b"MGMT195PRIVATECANARY" in raw:
                fired[0] = True
                os.write(fd, raw[:7])
                raise OSError("injected_short_write")
            return original(fd, raw)
        private_io.write_all = short
        try:
            plan = f.m("preview")["plan"]
            job = f.m("create", operation_id="short-write", plan=plan)["job_id"]
            result = f.job(job, "failed")
        finally:
            private_io.write_all = original
        require(fired[0], "short_write_hook_unused")
        f.collector._management.hook = lambda phase: (_ for _ in ()).throw(OSError("cleanup_fault")) if phase == "before_cleanup" else None
        restore, status = f.restore(backup, "discard-replaced-current", "cleanup-fault")
        require(status["cleanup"] == "incomplete_registered_residuals", "cleanup_lie")
        changed = f.root / "observations.jsonl"
        changed.write_bytes("虚构后来替换的内容".encode())
        changed_hash = hashlib.sha256(changed.read_bytes()).hexdigest()
        f.restart()
        require(changed.exists() and hashlib.sha256(changed.read_bytes()).hexdigest() == changed_hash, "cleanup_retry_deleted_changed_file")
        registry = f.m("registry", job_id=restore)
        require(any(item["state"] == "changed_replacement_refused" for item in registry["registry"]), "changed_replacement_not_reported")
        results["disk"] = {"short_write": result, "cleanup": status["cleanup"], "job": restore}
    for index, phase in enumerate(("staging_fsync", "authority_fsync")):
        with fixture(root.parent / (root.name + "sync" + str(index))) as f:
            f.seed()
            backup, _ = f.backup()
            f.seed(2, "current-before-sync-fault")
            before = hashes(f.root)
            plan = f.m("restore_preview", job_id=backup)["plan"]
            original_sync = private_io.sync
            fired = [False]
            def fail_sync(path):
                is_target = Path(path).name == "restored" if phase == "staging_fsync" else Path(path) == f.root / "management"
                if is_target and not fired[0]:
                    fired[0] = True
                    raise OSError("injected_fsync_failure")
                return original_sync(path)
            private_io.sync = fail_sync
            try:
                job = f.m("restore_confirm", operation_id="sync-fault", plan=plan, retention="discard-replaced-current", confirm=True)["job_id"]
                if phase == "staging_fsync":
                    result = f.job(job, "failed")
                    require(before == hashes(f.root), "failed_staging_changed_target")
                else:
                    wait(lambda: f.collector._maintenance_unavailable, "ambiguous_commit_not_unavailable")
                    error(f.client.management("status", job_id=job), "management_authority_unavailable")
                    error(f.client.query("timeline"), "management_authority_unavailable")
                    result = {"state": "unknown_until_restart"}
            finally: private_io.sync = original_sync
            require(fired[0], "fsync_hook_unused")
            f.restart()
            current = body(f.client.status())
            require(current["durable_seq"] == (6 if phase == "staging_fsync" else 4), "fsync_recovery_mixed")
            results[phase] = {"before_restart": result["state"], "restart_rows": current["durable_seq"],
                              "generation": current["management"]["serving_generation"], "job": job}
    return results


def python_producer(root, native):
    with fixture(root) as f:
        f.seed()
        backup, _ = f.backup()
        entered, release = threading.Event(), threading.Event()
        producer = Producer(str(f.root / "collector.sock"), "python-held", limits={"heartbeat_interval_ms": 20})
        outcomes = []
        class ObservedClient(Client):
            def call(self, op, *args, **kwargs):
                response = super().call(op, *args, **kwargs)
                if op == "admit_batch": outcomes.append(response.get("body", {}).get("codes"))
                return response
        producer._client = lambda: ObservedClient(str(f.root / "collector.sock"))
        original = producer._send_batch
        def held(batch):
            entered.set(); release.wait(20)
            return original(batch)
        producer._send_batch = held
        try:
            wait(lambda: producer.local_status()["fresh"], "python_policy")
            require(producer.admit(observation("python-held", 1)).admitted, "python_local_admission")
            require(entered.wait(5), "python_batch_not_held")
            f.restore(backup)
            producer._last_poll = None
            producer._poll_policy()
            require(producer.local_status()["observed_desired"] == "off", "python_fence_repoll")
            release.set()
            wait(lambda: outcomes, "python_delayed_reply")
            require(outcomes[0] == ["invalid_request"], "python_old_payload_accepted")
            require(body(f.client.status())["durable_seq"] == 4, "python_old_payload_persisted")
        finally:
            release.set(); producer.close()
        fresh = Producer(str(f.root / "collector.sock"), "python-recreated", limits={"heartbeat_interval_ms": 20})
        try:
            wait(lambda: fresh.local_status()["fresh"] and fresh.local_status()["observed_desired"] == "enabled", "fresh_python_policy")
            require(fresh.admit(observation("python-recreated", 1)).admitted, "fresh_python_admission")
            wait(lambda: body(f.client.checkpoint())["durable_seq"] == 5, "fresh_python_publication")
        finally: fresh.close()
        f.restart()
        require(f.register("python-held")["registration_code"] == "source_recreation_required", "python_restart_fence")
        return {"old_delayed_per_item_codes": outcomes, "persisted_old_units": 0, "fresh_durable_units": 1,
                "restart_fence_retained": True}


class Native:
    def __init__(self, binary, socket_path, source):
        self.proc = subprocess.Popen([str(binary), str(socket_path), source], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    def command(self, command):
        self.proc.stdin.write(command + "\n"); self.proc.stdin.flush()
        ready, _, _ = select.select([self.proc.stdout], [], [], 5)
        require(ready, "native_input_waited")
        return self.proc.stdout.readline().strip()
    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.write("quit\n"); self.proc.stdin.flush()
            try: self.proc.wait(5)
            except subprocess.TimeoutExpired: self.proc.terminate(); self.proc.wait(5)
        require(self.proc.returncode == 0, "native_probe_exit")


def native_producer(root, native):
    require(native and native.is_file(), "required_native_probe_unavailable")
    with fixture(root) as f:
        f.seed()
        backup, _ = f.backup()
        fifo = root.parent / (root.name + "-producer.fifo")
        os.mkfifo(fifo, 0o600)
        old = Native(native, f.root / "collector.sock", "native-held")
        released = False
        try:
            wait(lambda: old.command("poll") == "effective=1", "native_policy")
            require(old.command("hold " + str(fifo)) == "held=1", "native_hold")
            time.sleep(.1)
            require(old.command("admit") == "admitted=1 durable=0", "native_commit_queue")
            require(old.command("intent") == "admitted=1 durable=0", "native_receipt_intent_queue")
            f.restore(backup)
            require(old.command("poll") == "effective=0", "native_repoll_fence")
            old.command("release")
            # Only the explicitly created diagnostic FIFO is opened, never an
            # adversarial managed artifact or historical special node.
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, b"x"); os.close(fd); released = True
            require(old.command("flush") == "flushed=1", "native_refusal_drain")
            require(body(f.client.checkpoint())["durable_seq"] == 4, "native_old_receipt_payload_persisted")
        finally:
            if not released:
                old.command("release")
                try:
                    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK); os.write(fd, b"x"); os.close(fd)
                except OSError: pass
            old.close()
        fresh = Native(native, f.root / "collector.sock", "native-recreated")
        try:
            wait(lambda: fresh.command("poll") == "effective=1", "fresh_native_policy")
            require(fresh.command("admit") == "admitted=1 durable=0", "fresh_native_admission")
            fresh.command("flush")
            wait(lambda: body(f.client.checkpoint())["durable_seq"] == 5, "fresh_native_durable")
        finally: fresh.close()
        f.restart()
        require(f.register("native-held")["desired_policy"] == "off", "native_restart_fence")
        f.restore(backup, operation="native-second-historical-restore")
        reused = Native(native, f.root / "collector.sock", "native-held")
        try:
            require(reused.command("poll") == "effective=0", "native_reused_id_enabled")
            require(reused.command("admit") == "admitted=0 durable=0", "native_reused_id_admitted")
        finally: reused.close()
        return {"held_commit_and_dependent_retraction": True, "postrestore_repoll_effective": False,
                "old_payload_persisted": 0, "fresh_native_durable": 1,
                "native_binary_sha256": hashlib.sha256(native.read_bytes()).hexdigest()}


def scales(root, native):
    measurements = []
    for count in (256, 4096):
        with fixture(root.parent / (root.name + str(count))) as f:
            started = time.monotonic()
            f.seed(count)
            page = body(f.client.annotations(page_size=1))
            ref = page["observations"][0]["source_reference"]
            body(f.client.annotate(ref, "correct", {"text": TEXT}, 0, "scale-human-correction"))
            dataset = f.dataset()
            backup, plan = f.backup()
            verified = f.m("verify", job_id=backup)
            status = f.m("status", job_id=backup)
            require(status["progress_bytes"] == plan["counts"]["bytes"], "copy_work_count")
            require(plan["counts"]["observations"] == count, "scale_source_count")
            measurements.append({"observations": count, "annotation_revisions": 1, "datasets": 1,
                                 "high_fanout_update_witnesses": count, "copy_bytes": status["progress_bytes"],
                                 "processed_files": status["progress_files"], "max_copy_buffer_bytes": private_io.CHUNK,
                                 "elapsed_seconds": time.monotonic() - started, "dataset_id": dataset,
                                 "verified_identity": verified["content_identity"]})
    return {"measurements": measurements, "not_total_ram_or_latency_certification": True}


def adapters(root, native):
    with fixture(root) as f:
        f.seed()
        def cli(*args, input=None):
            result = subprocess.run([sys.executable, "-m", "archive.cli", "--socket", str(f.root / "collector.sock"), "management", *args],
                                    cwd=REPO, input=input, capture_output=True, text=True)
            no_private(result.stdout + result.stderr)
            return result
        preview = cli("preview")
        require(preview.returncode == 0, "cli_preview")
        created = cli("create", "--operation-id", "cli-backup", input=preview.stdout)
        require(created.returncode == 0, "cli_create")
        job = json.loads(created.stdout)["body"]["job_id"]
        f.job(job)
        require(cli("list").returncode == 0 and cli("status", "--job-id", job).returncode == 0, "cli_list_status")
        require(cli("verify", "--job-id", job).returncode == 0, "cli_verify")
        restore = cli("restore-preview", "--job-id", job)
        confirmed = cli("restore-confirm", "--operation-id", "cli-restore", "--retention", "retain-current", "--confirm", input=restore.stdout)
        require(confirmed.returncode == 0, "cli_confirm")
        restored = json.loads(confirmed.stdout)["body"]["job_id"]
        f.job(restored)
        require(cli("cancel", "--job-id", restored).returncode != 0, "cli_postcommit_cancel")
        require(cli("create", "--operation-id", CANARY, input='{\x1bmalformed').returncode != 0, "cli_hostile_input")
        output = io.StringIO()
        TuiSession(f.client, io.StringIO("management\nbackups\nbackup-preview\nbackup-create tui-backup\nmanagement-status " + restored + "\nmanagement-verify " + job + "\nrestore-preview " + job + "\nquit\n"), output).run()
        tui_job = private_io.digest({"namespace": f.collector._management.authority.value["namespace"], "operation_id": "tui-backup"})
        f.job(tui_job)
        TuiSession(f.client, io.StringIO("restore-preview " + tui_job + "\nrestore-confirm tui-restore discard-replaced-current confirm\nquit\n"), output).run()
        tui_restore = private_io.digest({"namespace": f.collector._management.authority.value["namespace"], "operation_id": "tui-restore"})
        f.job(tui_restore)
        no_private(output.getvalue())
        require("producer_recreation" in output.getvalue() and "SCREEN management" in output.getvalue(), "tui_recreation_disclosure")
        require(body(f.client.status())["desired_policy"] == "enabled", "page_closed_capture_changed")
        no_private(f.client.call("management", {"management_version": VERSION, "action": "availability"}, request_id=CANARY + "\x1b"))
        generation = body(f.client.status())["management"]["serving_generation"]
        private_cli = subprocess.run([sys.executable, "-m", "archive.cli", "--socket", str(f.root / "collector.sock"),
                                      "--serving-generation", str(generation), "--json", "query", "process",
                                      "--process-id", "process-1", "--private-detail"], cwd=REPO, capture_output=True, text=True)
        require(private_cli.returncode == 0 and CANARY in private_cli.stdout and "\x1b" not in private_cli.stdout and "\x85" not in private_cli.stdout, "private_cli_escape")
        private_output = io.StringIO()
        TuiSession(f.client, io.StringIO("expand process-1\nquit\n"), private_output).run()
        require(CANARY in private_output.getvalue() and "\x1b" not in private_output.getvalue() and "\x85" not in private_output.getvalue(), "private_tui_escape")
        return {"cli_actions": ["preview", "create", "list", "status", "verify", "restore-preview", "restore-confirm", "cancel-error", "hostile-error"],
                "tui_screen_bytes": len(output.getvalue().encode()), "closing_page_preserved_policy": True,
                "ordinary_output_private_canary_absent": True}


def bounds(root, native):
    with fixture(root) as f:
        source = "unregistered-direct"
        refused = body(f.client.call("admit_batch", {"observations": [observation(source, 1)]}))
        require(refused["codes"] == ["invalid_request"], "unregistered_batch_registered_itself")
        old_limit = authority_module.MAX_SOURCES
        authority_module.MAX_SOURCES = 1
        try:
            require(f.register("first-source")["registration_code"] == "registered", "first_registration")
            result = f.register("over-bound-source")
            require(result["desired_policy"] != "enabled", "authority_bound_enabled")
            require(f.m("availability")["registered_sources"] == 1, "registration_evicted")
        finally: authority_module.MAX_SOURCES = old_limit
        # Hold real management disk work and use the real Python input API.
        entered, release = threading.Event(), threading.Event()
        def hook(phase):
            if phase == "before_copy": entered.set(); release.wait(20)
        f.collector._management.hook = hook
        f.seed(2, "first-source")
        plan = f.m("preview")["plan"]
        job = f.m("create", operation_id="held-disk", plan=plan)["job_id"]
        require(entered.wait(5), "management_hold")
        producer = Producer(str(f.root / "collector.sock"), "bounded-input", limits={"heartbeat_interval_ms": 20})
        native_input = Native(native, f.root / "collector.sock", "native-held-management")
        try:
            wait(lambda: producer.local_status()["fresh"], "bounded_policy")
            start = time.monotonic()
            result = producer.admit(observation("bounded-input", 1))
            duration = time.monotonic() - start
            require(result.admitted and duration < 2, "producer_waited_on_management")
            wait(lambda: native_input.command("poll") == "effective=1", "native_held_management_policy")
            native_started = time.monotonic()
            require(native_input.command("admit") == "admitted=1 durable=0", "native_held_management_admission")
            native_duration = time.monotonic() - native_started
            require(native_duration < 2, "native_waited_on_management")
        finally:
            producer.close(); native_input.close(); release.set()
        f.job(job)
        # Finite over-bound controls use the same production guards at a small
        # declared test budget, never truncated successful snapshots or eviction.
        import archive.management as management_module
        old_observations, old_files = management_module.MAX_OBSERVATIONS, private_io.MAX_FILES
        before = hashes(f.collector.content_root)
        try:
            management_module.MAX_OBSERVATIONS = 1
            error(f.client.management("preview"), "management_bound")
            management_module.MAX_OBSERVATIONS = old_observations
            private_io.MAX_FILES = 1
            error(f.client.management("preview"), "management_bound")
        finally:
            management_module.MAX_OBSERVATIONS, private_io.MAX_FILES = old_observations, old_files
        require(before == hashes(f.collector.content_root), "bounded_refusal_mutated_source")
        error(f.client.management("registry", job_id=job, page_size=33), "management_bound")
        marker = f.root / "management-namespace.json"
        saved = marker.read_bytes()
        f.close()
        marker.unlink()
        other = Collector(str(f.root), str(f.root / "collector.sock"), resolve())
        try:
            try: other.prepare()
            except InterfaceError as exc: require(exc.code == "management_authority_unavailable", "authority_missing_wrong_error")
            else: raise Failure("missing_authority_reinitialized")
        finally:
            other.release_ownership()
            # Test-owned external tamper restoration, not product repair.
            private_io.write_new(marker, saved)
        control = f.root / "management" / "control.json"
        original_control = control.read_bytes()
        corrupt_outcomes = []
        for raw in (b"[]", canonical_bytes({"version": "unsupported"})):
            control.write_bytes(raw)
            other = Collector(str(f.root), str(f.root / "collector.sock"), resolve())
            try:
                try: other.prepare()
                except InterfaceError as exc: corrupt_outcomes.append(exc.code)
                else: raise Failure("corrupt_authority_reinitialized")
            finally: other.release_ownership()
        control.write_bytes(original_control)
        return {"direct_unregistered_codes": refused["codes"], "registration_bound_exhaustion_refused": True,
                "missing_authority_fail_closed": True, "actual_input_admission_seconds_held_disk": duration,
                "native_input_admission_seconds_held_disk": native_duration,
                "corrupt_authority_outcomes": corrupt_outcomes, "bounded_inventory_source_unchanged": True,
                "not_latency_certification": True}


FUNCTIONS = (coherent, immutable, tamper, retention, policy, jobs, faults, python_producer,
             native_producer, scales, adapters, bounds)


def child(root, phase):
    c = Collector(root, str(Path(root) / "collector.sock"), resolve())
    c.prepare()
    def hook(current):
        if current == phase: os._exit(91)
    c._management.hook = hook
    try: c.serve()
    finally: c.release_ownership()
    return 0


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split(".")[0] in {"mlx", "mlx_lm", "torch", "transformers", "tokenizers"}:
            raise Failure("forbidden_model_import")


def main():
    os.umask(0o077)
    sys.meta_path.insert(0, NoModels())
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=2)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract",))
    parser.add_argument("--root")
    parser.add_argument("--report")
    parser.add_argument("--native-build", default=os.environ.get("MGMT195_NATIVE_BUILD", ""))
    args = parser.parse_args()
    if args.child: return child(*args.child)
    if args.self_test:
        require(len(CASES) == len(FUNCTIONS) == 12 and len(set(CASES)) == 12, "self_case_inventory")
        require(private_io.CHUNK == 65536 and authority_module.MAX_SOURCES >= 4096, "self_bounds")
        for value in ("../escape", "/absolute", "a//b", "a/./b", "a/../../b"):
            try: private_io.relative(value)
            except UnsafeRoot: pass
            else: raise Failure("self_relative_path")
        print(json.dumps({"self_test": "Pass", "required_cases": list(CASES), "skips": 0}))
        return 0
    require(args.suite == "contract" and args.root and args.report, "explicit_root_report_required")
    root, report = Path(args.root).absolute(), Path(args.report).absolute()
    validate_root(str(root)); validate_root(str(report.parent))
    require(not root.exists() and not report.exists(), "fresh_root_report_required")
    root.mkdir(mode=0o700)
    native = Path(args.native_build) / "plugins" / "llm-rerank" / "test" / "llm_rerank_management_producer_probe" if args.native_build else None
    results = []
    for name, function in zip(CASES, FUNCTIONS):
        try:
            details = function(root / ("c" + str(len(results))), native)
            no_private(details)
            result = {"case": name, "status": "Pass", "evidence": details}
        except Exception as exc:
            result = {"case": name, "status": "Fail", "reason": str(exc) if isinstance(exc, Failure) else type(exc).__name__}
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k != "evidence"}), flush=True)
    data = {"contract": "AC-195-v2", "required_cases": list(CASES), "skips": 0,
            "cases": results, "source_code_identity": code_identity(), "runtime": {"python": sys.version.split()[0], "executable": sys.executable},
            "source_files": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((REPO / "archive").glob("*.py"))},
            "native_probe": {"path": str(native), "sha256": hashlib.sha256(native.read_bytes()).hexdigest()} if native and native.is_file() else None,
            "limits": {"copy_buffer_bytes": private_io.CHUNK, "max_files": private_io.MAX_FILES, "max_jobs": private_io.MAX_JOBS,
                       "max_copy_bytes": private_io.MAX_BYTES, "max_sources": authority_module.MAX_SOURCES},
            "content_included": False, "live_or_model_operation": False}
    no_private(data)
    with report.open("x") as stream: json.dump(data, stream, indent=2, sort_keys=True)
    return 0 if all(r["status"] == "Pass" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
