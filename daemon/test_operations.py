#!/usr/bin/env python3
"""Tests for the persistent long-operation engine (Habit130/squirrel#52).

Model-free and daemon-free: everything runs against temporary directories
with the test-only fixture operation type registered in-process. Covers the
operation model, the idempotency contract, the centralized state/phase
machine, the crash-recovery seams, cancel semantics (pre- and
post-irreversible), wait streaming, the error protocol and the owner-only
security boundary. All filesystem fixtures are isolated temp dirs.
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from fixture_operations import (  # noqa: E402
    FIXTURE_CHUNKS,
    FIXTURE_IRREVERSIBLE_PHASE,
    FIXTURE_PHASES,
    fixture_spec,
)
from operations import (  # noqa: E402
    OPERATION_VERSION,
    OperationBlocked,
    OperationFailed,
    OperationIdConflict,
    OperationNotFound,
    OperationRegistry,
    OperationStore,
    SimulatedCrash,
    StoreBlocked,
    UnsupportedOperationType,
    UnsupportedPrivilege,
    cancel_operation,
    create_operation,
    is_cancelable,
    new_operation,
    operation_outcome_exit_code,
    parameters_fingerprint,
    run_pending_steps,
    validate_phase_transition,
    validate_record,
    validate_state_transition,
    wait_for_terminal,
)
from operations import InvalidTransition  # noqa: E402


def fixture_registry():
    registry = OperationRegistry()
    registry.register(fixture_spec())
    return registry


def raising_hook(error_factory):
    def hook(phase, step_index, point):
        raise error_factory(phase)
    return hook


class OperationEngineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_ops_")
        self.root = os.path.join(self._tmp, "semantic_memory")
        self.work = os.path.join(self._tmp, "work")
        os.makedirs(self.work)
        self.registry = fixture_registry()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def store(self):
        return OperationStore(self.root)

    def params(self, **overrides):
        values = {"work_dir": self.work, "private_label": "label"}
        values.update(overrides)
        return values

    def create(self, operation_id=None, **overrides):
        return create_operation(self.store(), self.registry,
                                "fixture.maintenance",
                                self.params(**overrides),
                                operation_id=operation_id)

    def run_steps(self, operation_id, **kwargs):
        return run_pending_steps(self.store(), self.registry, operation_id,
                                 **kwargs)

    def read_work(self, name):
        path = os.path.join(self.work, name)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read().strip()

    # -- creation, idempotency, fingerprint ---------------------------------

    def test_create_generates_id_before_any_work(self):
        record = self.create()
        self.assertTrue(record["operation_id"])
        self.assertEqual("queued", record["state"])
        self.assertEqual("preflight", record["phase"])
        self.assertEqual(OPERATION_VERSION, record["operation_version"])
        self.assertEqual(FIXTURE_PHASES, tuple(record["phases"]))
        self.assertEqual(FIXTURE_IRREVERSIBLE_PHASE,
                         record["irreversible_phase"])
        # No work has happened yet.
        self.assertEqual(0, record["progress"]["events"])
        self.assertIsNone(self.read_work("preflight.marker"))

    def test_fingerprint_is_deterministic_and_key_order_free(self):
        a = parameters_fingerprint({"work_dir": "/x", "k": 1})
        b = parameters_fingerprint({"k": 1, "work_dir": "/x"})
        c = parameters_fingerprint({"work_dir": "/x", "k": 2})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_parameters_are_normalized(self):
        # Relative path -> absolute, NFC-normalized; int sleep -> float.
        nfc = "e\u0301"
        record = create_operation(self.store(), self.registry,
                                  "fixture.maintenance",
                                  {"work_dir": os.path.join(
                                      self._tmp, "sub", nfc),
                                   "sleep_s": 1},
                                  operation_id="norm-1")
        self.assertTrue(os.path.isabs(record["parameters"]["work_dir"]))
        self.assertTrue(record["parameters"]["work_dir"].endswith("é"))
        self.assertEqual(1.0, record["parameters"]["sleep_s"])

    def test_same_id_same_params_returns_existing(self):
        first = self.create(operation_id="idem-1")
        second = self.create(operation_id="idem-1")
        self.assertEqual(first["operation_id"], second["operation_id"])
        self.assertEqual(first["parameters_fingerprint"],
                         second["parameters_fingerprint"])
        # Only one record file exists.
        self.assertEqual(["idem-1"], self.store().list_ids())

    def test_same_id_different_params_rejected(self):
        self.create(operation_id="conflict-1")
        with self.assertRaises(OperationIdConflict):
            self.create(operation_id="conflict-1", private_label="other")

    def test_unknown_type_rejected(self):
        with self.assertRaises(UnsupportedOperationType):
            create_operation(self.store(), self.registry, "backup",
                             self.params())

    def test_idempotent_retry_returns_same_terminal_result(self):
        first = self.create(operation_id="term-1")
        self.run_steps(first["operation_id"])
        completed = self.store().load(first["operation_id"])
        again = self.create(operation_id="term-1")
        self.assertEqual("succeeded", again["state"])
        self.assertEqual(completed["result"], again["result"])

    # -- state machine ------------------------------------------------------

    def test_legal_and_illegal_state_transitions(self):
        legal = [
            ("queued", "running"), ("queued", "cancelled"),
            ("running", "blocked"), ("running", "failed"),
            ("running", "succeeded"), ("running", "cancelled"),
            ("blocked", "running"), ("blocked", "cancelled"),
        ]
        illegal = [
            ("queued", "succeeded"), ("running", "queued"),
            ("succeeded", "running"), ("failed", "running"),
            ("cancelled", "running"), ("blocked", "queued"),
            ("blocked", "succeeded"), ("running", "running"),
        ]
        for current, new_state in legal:
            self.assertTrue(validate_state_transition(current, new_state))
        for current, new_state in illegal:
            with self.assertRaises(InvalidTransition):
                validate_state_transition(current, new_state)

    def test_phase_transitions_are_forward_only(self):
        record = new_operation("t", {}, list(FIXTURE_PHASES),
                               FIXTURE_IRREVERSIBLE_PHASE)
        # Staying in a phase is legal; advancing to the immediate successor
        # is legal; everything else is rejected.
        for phase in FIXTURE_PHASES:
            record["phase"] = phase
            self.assertTrue(validate_phase_transition(record, phase))
        record["phase"] = "preflight"
        self.assertTrue(validate_phase_transition(record, "staging"))
        with self.assertRaises(InvalidTransition):
            validate_phase_transition(record, "publishing")
        record["phase"] = "staging"
        with self.assertRaises(InvalidTransition):
            validate_phase_transition(record, "preflight")

    def test_cancelability_tracks_irreversible_phase(self):
        record = new_operation("t", {}, list(FIXTURE_PHASES),
                               FIXTURE_IRREVERSIBLE_PHASE)
        for phase, cancelable in [("preflight", True),
                                  ("staging", True),
                                  ("publishing", False),
                                  ("cleanup", False)]:
            record["phase"] = phase
            record["state"] = "running"
            self.assertEqual(cancelable, is_cancelable(record), phase)

    def test_validate_record_rejects_corrupt_machines(self):
        good = new_operation("t", {}, list(FIXTURE_PHASES),
                             FIXTURE_IRREVERSIBLE_PHASE)
        self.assertTrue(validate_record(good))
        # A phase outside this operation's recorded machine.
        bad_phase = dict(good, phase="reopening")
        self.assertFalse(validate_record(bad_phase))
        bad_state = dict(good, state="exploded")
        self.assertFalse(validate_record(bad_state))
        bad_version = dict(good, operation_version=99)
        self.assertFalse(validate_record(bad_version))
        non_monotonic = dict(good)
        non_monotonic["log"] = [
            {"event_version": 1, "seq": 5, "kind": "x"},
            {"event_version": 1, "seq": 3, "kind": "x"},
        ]
        self.assertFalse(validate_record(non_monotonic))

    # -- full run -----------------------------------------------------------

    def test_full_run_succeeds_with_real_units(self):
        record = self.create()
        final = self.run_steps(record["operation_id"])
        self.assertEqual("succeeded", final["state"])
        self.assertEqual("cleanup", final["phase"])
        self.assertEqual(FIXTURE_CHUNKS,
                         final["progress"]["chunks"])
        # events: 1 preflight + 1 staging-final + 1 cleanup.
        self.assertEqual(3, final["progress"]["events"])
        self.assertTrue(final["progress"]["bytes"] > 0)
        self.assertTrue(final["result"]["completed"])
        # Phases advanced strictly in recorded order: the queued -> running
        # transition carries the first phase, each advance carries the new
        # phase.
        transitions = [e["phase"] for e in final["log"]
                       if e["kind"] == "transition"]
        self.assertEqual(list(FIXTURE_PHASES), transitions)
        # Log sequence numbers are strictly increasing and versioned.
        seqs = [e["seq"] for e in final["log"]]
        self.assertEqual(sorted(seqs), seqs)
        self.assertTrue(all(e["event_version"] == 1 for e in final["log"]))
        # Side effects happened exactly once each.
        self.assertEqual("ok", self.read_work("preflight.marker"))
        self.assertEqual("ok", self.read_work("cleanup.marker"))
        self.assertEqual("published", self.read_work("published.marker"))
        self.assertEqual("1", self.read_work("publish.count"))

    def test_restart_resumes_from_persisted_phase(self):
        record = self.create()
        after_first = self.run_steps(record["operation_id"], max_steps=1)
        self.assertEqual("running", after_first["state"])
        self.assertEqual("staging", after_first["phase"])
        self.assertEqual(0, after_first["progress"]["chunks"])
        # "Restart": a fresh store and runner over the same directory.
        final = run_pending_steps(OperationStore(self.root), self.registry,
                                  record["operation_id"])
        self.assertEqual("succeeded", final["state"])
        self.assertEqual(FIXTURE_CHUNKS, final["progress"]["chunks"])
        self.assertEqual("1", self.read_work("publish.count"))

    # -- fault injection and crash recovery ---------------------------------

    def crash_hook(self, crash_at):
        def hook(phase, step_index, point):
            if (phase, step_index, point) == crash_at:
                raise SimulatedCrash()
        return hook

    def test_crash_before_first_step_resumes(self):
        record = self.create()
        with self.assertRaises(SimulatedCrash):
            self.run_steps(record["operation_id"],
                     fault_hook=self.crash_hook(
                         ("preflight", 0, "before_step")))
        # The queued -> running transition was persisted; no step ran.
        mid = self.store().load(record["operation_id"])
        self.assertEqual("running", mid["state"])
        self.assertEqual("preflight", mid["phase"])
        self.assertIsNone(self.read_work("preflight.marker"))
        final = self.run_steps(record["operation_id"])
        self.assertEqual("succeeded", final["state"])
        self.assertEqual("ok", self.read_work("preflight.marker"))

    def test_crash_mid_phase_resumes_chunks(self):
        record = self.create()
        # Run preflight + 2 staging chunks, then crash before the 3rd.
        self.run_steps(record["operation_id"], max_steps=3)
        with self.assertRaises(SimulatedCrash):
            self.run_steps(record["operation_id"],
                     fault_hook=self.crash_hook(
                         ("staging", 2, "before_step")))
        mid = self.store().load(record["operation_id"])
        self.assertEqual("staging", mid["phase"])
        self.assertEqual(2, mid["progress"]["chunks"])
        final = self.run_steps(record["operation_id"])
        self.assertEqual(FIXTURE_CHUNKS, final["progress"]["chunks"])
        self.assertEqual("1", self.read_work("publish.count"))

    def test_irreversible_publish_not_reexecuted_after_crash(self):
        record = self.create()
        # Run preflight + all staging chunks: the recorded phase is now the
        # irreversible publishing phase, but no publish effect has run.
        self.run_steps(record["operation_id"], max_steps=4)
        mid = self.store().load(record["operation_id"])
        self.assertEqual("publishing", mid["phase"])
        self.assertIsNone(self.read_work("published.marker"))
        # Execute up to and including the publish *effect*, then crash
        # before the effect result is persisted.
        with self.assertRaises(SimulatedCrash):
            self.run_steps(record["operation_id"],
                           fault_hook=self.crash_hook(
                               ("publishing", 0, "after_step")))
        # The effect happened but the record still sits at publishing.
        self.assertEqual("published", self.read_work("published.marker"))
        mid = self.store().load(record["operation_id"])
        self.assertEqual("publishing", mid["phase"])
        # Restart: the publish step runs again but the irreversible effect
        # must NOT be repeated.
        final = self.run_steps(record["operation_id"])
        self.assertEqual("succeeded", final["state"])
        self.assertEqual(1, len(self.read_work("publish.count").split()))

    def test_deterministic_error_blocks_and_requires_explicit_retry(self):
        record = self.create()
        self.run_steps(record["operation_id"],
                       fault_hook=raising_hook(
                           lambda phase: OperationBlocked(
                               code="fixture_preflight_failed", phase=phase)))
        blocked = self.store().load(record["operation_id"])
        self.assertEqual("blocked", blocked["state"])
        self.assertEqual("preflight", blocked["phase"])
        error = blocked["error"]
        for field in ("code", "message", "occurred_at", "retryable", "phase",
                      "remediation", "cause", "error_version"):
            self.assertIn(field, error)
        self.assertFalse(error["retryable"])
        self.assertEqual("fixture_preflight_failed", error["code"])
        # A plain runner invocation must NOT auto-retry a blocked op.
        still = self.run_steps(record["operation_id"])
        self.assertEqual("blocked", still["state"])
        # The explicit retry (the fault being "fixed" by removing it)
        # resumes and completes.
        final = self.run_steps(record["operation_id"], retry_blocked=True)
        self.assertEqual("succeeded", final["state"])

    def test_transient_error_fails_and_stays_terminal(self):
        record = self.create()
        self.run_steps(record["operation_id"],
                       fault_hook=raising_hook(
                           lambda phase: OperationFailed(
                               code="transient_step_failure", phase=phase)))
        failed = self.store().load(record["operation_id"])
        self.assertEqual("failed", failed["state"])
        self.assertTrue(failed["error"]["retryable"])
        # Restart does not re-execute a failed operation.
        final = self.run_steps(record["operation_id"], retry_blocked=True)
        self.assertEqual("failed", final["state"])

    def test_crash_after_persisted_step_does_not_regress(self):
        record = self.create()
        self.run_steps(record["operation_id"], max_steps=2)
        with self.assertRaises(SimulatedCrash):
            self.run_steps(record["operation_id"],
                     fault_hook=self.crash_hook(("staging", 1, "before_step")))
        final = self.run_steps(record["operation_id"])
        self.assertEqual("succeeded", final["state"])
        self.assertEqual(1, len(self.read_work("publish.count").split()))

    def test_unsupported_type_fails_deterministically(self):
        # Bypass create_operation (which validates the type) and plant a
        # record for an unregistered type directly in the store.
        store = self.store()
        store.open()
        record = new_operation("clear", {}, ("preflight", "publishing"),
                               "publishing", operation_id="ghost-1")
        store.create(record)
        empty_registry = OperationRegistry()
        final = run_pending_steps(store, empty_registry, "ghost-1")
        self.assertEqual("failed", final["state"])
        self.assertEqual("unsupported_operation_type",
                         final["error"]["code"])

    def test_max_steps_bounds_execution(self):
        record = self.create()
        bounded = self.run_steps(record["operation_id"], max_steps=1)
        self.assertEqual("staging", bounded["phase"])
        self.assertEqual(0, bounded["progress"]["chunks"])

    # -- cancel -------------------------------------------------------------

    def test_cancel_queued_before_any_run(self):
        record = self.create()
        cancelled_record, disposition = cancel_operation(
            self.store(), record["operation_id"])
        self.assertEqual("requested", disposition)
        self.assertTrue(cancelled_record["cancel_requested"])
        final = self.run_steps(record["operation_id"])
        self.assertEqual("cancelled", final["state"])
        self.assertIsNone(self.read_work("preflight.marker"))

    def test_cancel_during_staging_is_honored_at_checkpoint(self):
        record = self.create()
        self.run_steps(record["operation_id"], max_steps=1)
        _, disposition = cancel_operation(self.store(),
                                          record["operation_id"])
        self.assertEqual("requested", disposition)
        final = self.run_steps(record["operation_id"])
        self.assertEqual("cancelled", final["state"])
        # Never reached the irreversible phase.
        self.assertIsNone(self.read_work("published.marker"))
        self.assertIsNone(self.read_work("publish.count"))

    def test_repeat_cancel_is_idempotent(self):
        record = self.create()
        self.run_steps(record["operation_id"], max_steps=1)
        cancel_operation(self.store(), record["operation_id"])
        again, disposition = cancel_operation(self.store(),
                                              record["operation_id"])
        self.assertEqual("requested", disposition)
        self.assertEqual(1, len([e for e in again["log"]
                                 if e["kind"] == "cancel_requested"]))

    def test_cancel_after_irreversible_point_is_refused_and_continues(self):
        record = self.create()
        # Run through the staging advance: now at the irreversible phase,
        # with the publish effect not yet executed.
        self.run_steps(record["operation_id"], max_steps=4)
        mid = self.store().load(record["operation_id"])
        self.assertEqual("publishing", mid["phase"])
        _, disposition = cancel_operation(self.store(),
                                          record["operation_id"])
        self.assertEqual("uncancellable", disposition)
        self.assertFalse(mid["cancel_requested"])
        # Cleanup continues and the operation succeeds.
        final = self.run_steps(record["operation_id"])
        self.assertEqual("succeeded", final["state"])
        self.assertEqual("ok", self.read_work("cleanup.marker"))

    def test_cancel_of_terminal_operation_is_refused(self):
        record = self.create()
        self.run_steps(record["operation_id"])
        _, disposition = cancel_operation(self.store(),
                                          record["operation_id"])
        self.assertEqual("terminal", disposition)

    # -- wait ---------------------------------------------------------------

    def test_wait_streams_versioned_events_with_increasing_seq(self):
        record = self.create(work_dir=self.work, sleep_s=0.02)
        events = []
        result = {}

        def executor():
            self.run_steps(record["operation_id"])

        thread = threading.Thread(target=executor)
        thread.start()
        final, outcome = wait_for_terminal(
            self.store(), record["operation_id"], poll_interval=0.01,
            emit=events.append)
        thread.join(timeout=10)
        self.assertEqual("succeeded", outcome)
        self.assertEqual("succeeded", final["state"])
        self.assertTrue(events)
        seqs = [e["seq"] for e in events]
        self.assertEqual(sorted(seqs), seqs)
        self.assertTrue(all(e["event_version"] == 1 for e in events))
        self.assertEqual("terminal", events[-1]["kind"])
        self.assertEqual("succeeded", events[-1]["outcome"])

    def test_wait_on_terminal_operation_returns_immediately(self):
        record = self.create()
        self.run_steps(record["operation_id"])
        events = []
        final, outcome = wait_for_terminal(self.store(),
                                           record["operation_id"],
                                           emit=events.append)
        self.assertEqual("succeeded", outcome)
        self.assertEqual(final["log"], events)

    def test_wait_timeout_returns_nonterminal_with_exit_two(self):
        record = self.create(sleep_s=0.5)
        self.run_steps(record["operation_id"], max_steps=1)
        final, outcome = wait_for_terminal(
            self.store(), record["operation_id"], poll_interval=0.02,
            timeout_s=0.1)
        self.assertIsNone(outcome)
        self.assertEqual("running", final["state"])
        self.assertEqual(2, operation_outcome_exit_code(outcome))
        self.run_steps(record["operation_id"])

    def test_outcome_exit_codes(self):
        self.assertEqual(0, operation_outcome_exit_code("succeeded"))
        self.assertEqual(0, operation_outcome_exit_code("cancelled"))
        self.assertEqual(1, operation_outcome_exit_code("failed"))
        self.assertEqual(1, operation_outcome_exit_code("blocked"))
        self.assertEqual(2, operation_outcome_exit_code(None))

    # -- security boundary --------------------------------------------------

    def test_store_dirs_and_files_are_owner_only(self):
        record = self.create()
        self.assertEqual(0o700, stat.S_IMODE(os.lstat(self.root).st_mode))
        operations_dir = os.path.join(self.root, "operations")
        self.assertEqual(0o700, stat.S_IMODE(os.lstat(operations_dir).st_mode))
        record_path = os.path.join(operations_dir, "%s.json"
                                   % record["operation_id"])
        self.assertEqual(0o600, stat.S_IMODE(os.lstat(record_path).st_mode))
        # No temp files survive an atomic write.
        leftovers = [name for name in os.listdir(operations_dir)
                     if ".tmp-" in name]
        self.assertEqual([], leftovers)

    def test_missing_root_is_created_owner_only(self):
        store = OperationStore(self.root)
        store.open()
        self.assertEqual(0o700, stat.S_IMODE(os.lstat(self.root).st_mode))
        self.assertTrue(os.path.isdir(os.path.join(self.root,
                                                   "operations")))

    def test_root_symlink_refused(self):
        real = os.path.join(self._tmp, "real")
        os.makedirs(real)
        os.symlink(real, self.root)
        with self.assertRaises(StoreBlocked) as raised:
            self.store().open()
        self.assertEqual("root_symlink", raised.exception.fault_code)

    def test_loose_root_permission_refused(self):
        os.makedirs(self.root)
        os.chmod(self.root, 0o755)
        with self.assertRaises(StoreBlocked) as raised:
            self.store().open()
        self.assertEqual("root_permission", raised.exception.fault_code)

    def test_operations_dir_symlink_refused(self):
        os.makedirs(self.root)
        os.chmod(self.root, 0o700)
        real = os.path.join(self._tmp, "op_real")
        os.makedirs(real)
        os.symlink(real, os.path.join(self.root, "operations"))
        with self.assertRaises(StoreBlocked) as raised:
            self.store().open()
        self.assertEqual("op_dir_symlink", raised.exception.fault_code)

    def test_record_symlink_refused(self):
        record = self.create()
        operations_dir = os.path.join(self.root, "operations")
        target = os.path.join(self._tmp, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as f:
            f.write("{}")
        os.unlink(os.path.join(operations_dir, "%s.json"
                               % record["operation_id"]))
        os.symlink(target, os.path.join(operations_dir, "%s.json"
                                        % record["operation_id"]))
        with self.assertRaises(StoreBlocked) as raised:
            self.store().load(record["operation_id"])
        self.assertEqual("operation_symlink", raised.exception.fault_code)

    def test_loose_record_permission_refused(self):
        record = self.create()
        record_path = os.path.join(self.root, "operations", "%s.json"
                                   % record["operation_id"])
        os.chmod(record_path, 0o644)
        with self.assertRaises(StoreBlocked) as raised:
            self.store().load(record["operation_id"])
        self.assertEqual("operation_permission", raised.exception.fault_code)

    def test_missing_record_is_not_found(self):
        with self.assertRaises(OperationNotFound):
            self.store().load("no-such-id")

    def test_elevated_privilege_refused(self):
        store = OperationStore(self.root, euid=0)
        with self.assertRaises(UnsupportedPrivilege):
            store.open()

    # -- privacy ------------------------------------------------------------

    def test_logs_and_errors_never_echo_private_input(self):
        marker = "PRIVATE_MARKER_上文_候选_embedding_%s" % "secret"
        record = self.create(private_label=marker)
        final = self.run_steps(record["operation_id"])
        # The parameters themselves legitimately hold the label (it is the
        # idempotency credential); everything else must never echo it.
        self.assertIn(marker, json.dumps(final["parameters"],
                                         ensure_ascii=False))
        self.assertNotIn(marker, json.dumps(final["log"], ensure_ascii=False))
        self.assertNotIn(marker, json.dumps(final["result"],
                                            ensure_ascii=False))
        # Blocked/failed error objects carry only stable codes.
        record2 = self.create(private_label=marker)
        self.run_steps(record2["operation_id"],
                       fault_hook=raising_hook(
                           lambda phase: OperationBlocked(
                               code="fixture_preflight_failed", phase=phase)))
        blocked = self.store().load(record2["operation_id"])
        self.assertNotIn(marker, json.dumps(blocked["error"],
                                            ensure_ascii=False))
        self.assertNotIn(marker, json.dumps(blocked["log"],
                                            ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
