#!/usr/bin/env python3
"""Desensitized trial traces and exit alarms (Habit130/squirrel#74, AC-74-v1).

Model-free, sandboxed temp fact stores and throwaway trace roots with
synthetic request/event ids -- never real private history.  Maps one-to-one
onto the delivery contract's blocking scenarios:

  SCN-74-1  order-change request -> full identity-only trace (ranks,
            fingerprints, watermarks, neighbor event IDs, score parts,
            latencies)
  SCN-74-2  true fault -> stable error id + passthrough recorded
  SCN-74-3  unchanged success -> aggregates only
  SCN-74-4  no 上文 / candidate text / embedding in traces, errors,
            annotations, status
  SCN-74-5  annotate mispromotion by request/event ID; unknown ID refuses;
            no private fact copy
  SCN-74-6  3/100 confirmed mispromotions, >1%/300 faults, or two
            consecutive latency-window misses -> alarm suggesting gamma=0
  SCN-74-7  alarm does not write config; user can dismiss; traces remain
  SCN-74-8  live facts / Rime / freeze / switches untouched
  SCN-74-9  clear removes app-controlled traces
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from tracing import (  # noqa: E402
    FAULT_WINDOW,
    LATENCY_WINDOW,
    MISPROMOTION_LIMIT,
    MISPROMOTION_WINDOW,
    TraceStore,
    TracingError,
)

PRIVATE = "PRIVATE_MARKER_上文_候选_embedding_%s" % "trace_secret"


def request_meta(request_id, complete_comparable=True, **overrides):
    meta = {
        "schema_id": "luna_pinyin",
        "category": "word",
        "canonical_segment_input": "shijie",
        "request_id": request_id,
        "plan_identity": "plan-v2:test",
        "config_identity": "evidence-v1:repr=e2e-fixture-repr-v1:tau=0.5:"
                           "kev=8:H=32:sat=1:gamma=2",
        "fact_high_water": {"store_epoch": "e1", "hlc_physical_ms": 1000000,
                            "hlc_logical": 0},
        "complete_comparable": complete_comparable,
        "candidate_count": 2,
    }
    meta.update(overrides)
    return meta


def order_change_trace(request_id):
    return {
        "kind": "order_change",
        "request_id": request_id,
        "schema_id": "luna_pinyin",
        "category": "word",
        "canonical_segment_input": "shijie",
        "plan_identity": "plan-v2:test",
        "config_identity": "evidence-v1:repr=e2e-fixture-repr-v1:tau=0.5:"
                           "kev=8:H=32:sat=1:gamma=2",
        "retrieval_backend": "exact",
        "fact_high_water": {"store_epoch": "e1", "hlc_physical_ms": 1000000,
                            "hlc_logical": 0},
        "base_scores": [1.0, 2.0],
        "shadow_order": [0, 1],
        "final_order": [1, 0],
        "base_ranks": [0, 1],
        "final_ranks": [1, 0],
        "candidate_count": 2,
        "facts_watermark": {"store_epoch": "e1", "hlc_physical_ms": 1000000,
                            "hlc_logical": 0},
        "derived_watermark": None,
        "neighbors": [
            {"event_id": "evt-1", "commit_id": "c1", "cosine": 0.95,
             "r_i": 0.9, "d_i": 1.0, "a_i": 0.9, "usage_age": 0,
             "matched_candidate": 1},
        ],
        "aggregate_s_c": [{"index": 0, "s": 0.0}, {"index": 1, "s": 0.5}],
    }


class TraceStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="llm_rerank_trace_")
        self.root = os.path.join(self._tmp, "sm")
        self.store = TraceStore(self.root)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def trace_files(self):
        directory = self.store.directory()
        if not os.path.isdir(directory):
            return []
        return sorted(os.listdir(directory))

    def read_trace(self, trace_id):
        with open(os.path.join(self.store.directory(),
                               "trace-%s.json" % trace_id),
                  encoding="utf-8") as f:
            return json.load(f)

    def test_scn74_1_order_change_writes_full_identity_trace(self):
        meta = request_meta("req-oc-1")
        self.store.record_request(
            meta, "ok", trace_payload=order_change_trace("req-oc-1"),
            latency_segments={"full_request_ms": 5.0, "oracle_ms": 3.0})
        trace_files = [name for name in self.trace_files()
                       if name.startswith("trace-tr-req-oc-1-")]
        self.assertEqual(1, len(trace_files))
        trace = self.read_trace(trace_files[0][6:-5])
        for field in ("trace_id", "trace_version", "kind", "schema_id",
                      "category", "canonical_segment_input", "plan_identity",
                      "config_identity", "retrieval_backend",
                      "fact_high_water", "request_id", "base_scores",
                      "shadow_order", "final_order", "base_ranks",
                      "final_ranks", "candidate_count", "facts_watermark",
                      "derived_watermark", "neighbors", "aggregate_s_c"):
            self.assertIn(field, trace, field)
        self.assertEqual(["evt-1"],
                         [n["event_id"] for n in trace["neighbors"]])
        self.assertEqual([1, 0], trace["final_ranks"])
        self.assertEqual([1, 0], trace["final_order"])
        # aggregates updated too
        agg = self.store.aggregates()
        self.assertEqual(1, agg["semantic_requests"])
        self.assertEqual(1, agg["order_changes"])
        self.assertEqual(1, agg["actionable_events"])

    def test_scn74_2_true_fault_records_stable_identity_and_passthrough(self):
        meta = request_meta("req-fault-1")
        self.store.record_request(
            meta, "oracle_fault",
            trace_payload={"kind": "fault", "error_code": "oracle_fault",
                           "passthrough": True},
            latency_segments={"full_request_ms": 2.0})
        trace_files = [f for f in self.trace_files()
                       if f.startswith("trace-tr-req-fault-1-")]
        self.assertEqual(1, len(trace_files))
        trace = self.read_trace(trace_files[0][6:-5])
        self.assertEqual("fault", trace["kind"])
        self.assertEqual("oracle_fault", trace["error_code"])
        self.assertTrue(trace["passthrough"])
        agg = self.store.aggregates()
        self.assertEqual(1, agg["faults"])
        self.assertEqual(1, agg["passthroughs"])
        # index lists the fault trace
        self.assertEqual("oracle_fault", self.store.list_traces()[0]["kind"])

    def test_scn74_3_unchanged_success_is_aggregates_only(self):
        for i in range(3):
            self.store.record_request(
                request_meta("req-ok-%d" % i), "ok",
                latency_segments={"full_request_ms": 4.0 + i})
        self.assertEqual(3, self.store.aggregates()["semantic_requests"])
        self.assertEqual(0, self.store.aggregates()["order_changes"])
        # Only the aggregates/index-less store files exist; no trace body
        # was written for unchanged successes.
        files = self.trace_files()
        self.assertEqual([], [f for f in files if f.startswith("trace-")])
        self.assertIn("aggregates.json", files)
        histogram = self.store.aggregates()["latency_histogram"]
        self.assertEqual(3, sum(histogram.values()))

    def test_scn74_4_privacy_probes_every_output(self):
        # Raw 上文 / candidate text / embedding bytes must never appear in
        # any persisted output.  The store refuses non-ASCII identity bytes
        # outright (AC74-4 gate), so a leaked raw-text payload never lands
        # on disk.
        meta = request_meta("req-priv-1")
        self.store.record_request(meta, "ok",
                                  trace_payload=order_change_trace(
                                      "req-priv-1"),
                                  latency_segments={"full_request_ms": 1.0})
        self.store.record_annotation("req-priv-1", "evt-1")
        for name in self.trace_files():
            with open(os.path.join(self.store.directory(), name),
                      encoding="utf-8") as f:
                self.assertNotIn(PRIVATE, f.read())
        self.assertNotIn(PRIVATE, json.dumps(self.store.list_traces()))
        self.assertNotIn(PRIVATE, json.dumps(self.store.aggregates()))
        self.assertNotIn(PRIVATE, json.dumps(self.store.list_alarms()))
        self.assertNotIn(PRIVATE, json.dumps(self.store.annotations()))
        # A trace payload that tries to carry raw text is refused outright
        # (nothing is written, no partial trace).
        before = self.trace_files()
        leaked = order_change_trace("req-priv-2")
        leaked["candidate_text"] = PRIVATE
        with self.assertRaises(TracingError):
            self.store.record_request(request_meta("req-priv-2"), "ok",
                                      trace_payload=leaked)
        self.assertEqual(before, self.trace_files())

    def test_scn74_4_unsafe_identity_is_refused(self):
        # Identity fields carrying raw text (e.g. an event id that is really
        # 上文) refuse the whole trace; nothing partial is written.
        leaked_neighbor = order_change_trace("req-bad")
        leaked_neighbor["neighbors"][0]["event_id"] = PRIVATE
        with self.assertRaises(TracingError):
            self.store.record_request(request_meta("req-bad"), "ok",
                                      trace_payload=leaked_neighbor)
        self.assertEqual([], self.trace_files())

    def test_scn74_5_annotate_by_id_and_refuse_unknown(self):
        self.store.record_request(
            request_meta("req-ann-1"), "ok",
            trace_payload=order_change_trace("req-ann-1"))
        result = self.store.record_annotation("req-ann-1", "evt-1")
        self.assertIsNotNone(result)
        record, _ = result
        self.assertEqual("mispromotion", record["kind"])
        self.assertEqual("req-ann-1", record["request_id"])
        self.assertEqual("evt-1", record["event_id"])
        # Unknown request id refuses; no private fact copy.
        self.assertIsNone(self.store.record_annotation("req-unknown"))
        self.assertEqual(1, len(self.store.annotations()))

    def test_scn74_5_fault_trace_cannot_be_annotated(self):
        # A mispromotion is a judgement about an emitted order; a fault
        # trace has no emission to judge, so annotate refuses it.
        self.store.record_request(
            request_meta("req-fault-ann"), "oracle_fault",
            trace_payload={"kind": "fault", "error_code": "oracle_fault",
                           "passthrough": True})
        self.assertIsNone(
            self.store.record_annotation("req-fault-ann"))
        self.assertEqual([], self.store.annotations())

    def test_scn74_6_mispromotion_alarm_3_in_100(self):
        # 100 complete-comparable requests, 3 of them confirmed
        # mispromotions.  Denominator is that bit, not domain-actionable.
        confirmed = (3, 50, 99)
        for i in range(MISPROMOTION_WINDOW):
            rid = "req-mp-%d" % i
            if i in confirmed:
                self.store.record_request(
                    request_meta(rid), "ok",
                    trace_payload=order_change_trace(rid))
                self.store.record_annotation(rid)
            else:
                self.store.record_request(request_meta(rid), "ok")
        alarms = self.store.list_alarms()
        self.assertEqual(1, len(alarms))
        self.assertEqual("mispromotion_rate", alarms[0]["kind"])
        self.assertEqual("rollback to gamma=0", alarms[0]["suggestion"])
        self.assertEqual(MISPROMOTION_LIMIT,
                         alarms[0]["detail"]["confirmed"])
        self.assertIn("complete-comparable", alarms[0]["message"])

    def test_scn74_6_mispromotion_delayed_confirmation_still_fires(self):
        # A confirmation arriving long after the event (past the 100-event
        # ring) must still count: the window is over the complete-comparable
        # stream, not the recent ring.
        confirmed = (3, 50, 99)
        for i in range(MISPROMOTION_WINDOW + 50):
            rid = "req-dc-%d" % i
            if i in confirmed:
                self.store.record_request(
                    request_meta(rid), "ok",
                    trace_payload=order_change_trace(rid))
            else:
                self.store.record_request(request_meta(rid), "ok")
        # No alarm yet: none of the confirmations have been recorded.
        self.assertEqual([], self.store.list_alarms())
        # The user confirms the three mispromotions much later.
        for i in confirmed:
            self.store.record_annotation("req-dc-%d" % i)
        alarms = self.store.list_alarms()
        self.assertEqual(1, len(alarms))
        self.assertEqual("mispromotion_rate", alarms[0]["kind"])
        self.assertEqual(3, alarms[0]["detail"]["confirmed"])
        self.assertLessEqual(alarms[0]["detail"]["span_events"],
                             MISPROMOTION_WINDOW)

    def test_scn74_6_mispromotion_outside_window_does_not_fire(self):
        # Three confirmations spanning more than 100 complete-comparable
        # requests must not fire (no 100-event window contains all three).
        confirmed = (1, 60, 150)
        for i in range(200):
            rid = "req-ow-%d" % i
            if i in confirmed:
                self.store.record_request(
                    request_meta(rid), "ok",
                    trace_payload=order_change_trace(rid))
                self.store.record_annotation(rid)
            else:
                self.store.record_request(request_meta(rid), "ok")
        self.assertEqual([], self.store.list_alarms())

    def test_scn74_6_fault_rate_alarm_gt_1_percent_in_300(self):
        # 4 faults in 300 semantic requests = 1.33% > 1%.
        for i in range(FAULT_WINDOW):
            rid = "req-fr-%d" % i
            if i < 4:
                self.store.record_request(
                    request_meta(rid, complete_comparable=False),
                    "oracle_fault",
                    trace_payload={"kind": "fault",
                                   "error_code": "oracle_fault",
                                   "passthrough": True})
            else:
                self.store.record_request(
                    request_meta(rid, complete_comparable=False), "ok")
        alarms = self.store.list_alarms()
        self.assertEqual(1, len(alarms))
        self.assertEqual("fault_rate", alarms[0]["kind"])
        self.assertEqual(4, alarms[0]["detail"]["faults"])
        self.assertGreater(alarms[0]["detail"]["rate"], 0.01)

    def test_scn74_6_latency_alarm_two_consecutive_windows(self):
        # Two consecutive 300-request windows above the 50/75 ms gates.
        for i in range(2 * LATENCY_WINDOW + 5):
            self.store.record_request(
                request_meta("req-lat-%d" % i, complete_comparable=False),
                "ok",
                latency_segments={"full_request_ms": 60.0})
        alarms = self.store.list_alarms()
        self.assertEqual(1, len(alarms))
        self.assertEqual("latency_gate", alarms[0]["kind"])
        detail = alarms[0]["detail"]
        self.assertEqual(LATENCY_WINDOW, detail["window"])
        self.assertGreater(detail["first"]["p95_ms"], 50.0)

    def test_scn74_6_no_alarm_below_thresholds(self):
        for i in range(FAULT_WINDOW):
            self.store.record_request(
                request_meta("req-n-%d" % i, complete_comparable=False), "ok",
                latency_segments={"full_request_ms": 1.0})
        self.assertEqual([], self.store.list_alarms())

    def test_scn74_7_alarm_never_writes_config_and_dismiss_keeps_traces(self):
        # The store's only footprint is <root>/traces -- alarms never write
        # config, switches or facts anywhere else under the root.
        confirmed = (3, 50, 99)
        for i in range(MISPROMOTION_WINDOW):
            rid = "req-d-%d" % i
            if i in confirmed:
                self.store.record_request(
                    request_meta(rid), "ok",
                    trace_payload=order_change_trace(rid))
                self.store.record_annotation(rid)
            else:
                self.store.record_request(request_meta(rid), "ok")
        alarms = self.store.list_alarms()
        self.assertEqual(1, len(alarms))
        # No config / switch / facts files were created under the root.
        self.assertEqual(["traces"], os.listdir(self.root))
        trace_count = len(self.trace_files())
        dismissed = self.store.dismiss_alarm(alarms[0]["alarm_id"],
                                             "subjective veto")
        self.assertTrue(dismissed["dismissed"])
        self.assertEqual("subjective veto", dismissed["dismiss_reason"])
        self.assertEqual([], self.store.list_alarms())
        self.assertEqual(trace_count, len(self.trace_files()))  # kept
        self.assertEqual(3, len(self.store.annotations()))  # kept

    def test_scn74_8_facts_and_switches_untouched(self):
        # The store's only footprint is <root>/traces; it never opens facts
        # and never writes anything else.
        self.store.record_request(request_meta("req-s8"), "ok",
                                  trace_payload=order_change_trace("req-s8"))
        entries = os.listdir(self.root)
        self.assertEqual(["traces"], entries)

    def test_scn74_9_clear_removes_app_controlled_traces(self):
        self.store.record_request(request_meta("req-c1"), "ok",
                                  trace_payload=order_change_trace("req-c1"))
        self.store.record_annotation("req-c1")
        self.store.clear()
        self.assertFalse(os.path.exists(self.store.directory()))
        self.assertFalse(os.listdir(self.root))

    def test_trace_dir_is_owner_only(self):
        self.store.record_request(request_meta("req-mode"), "ok",
                                  trace_payload=order_change_trace("req-mode"))
        st = os.lstat(self.store.directory())
        self.assertEqual(0o700, stat.S_IMODE(st.st_mode))
        self.assertEqual(os.getuid(), st.st_uid)
        for name in self.trace_files():
            path = os.path.join(self.store.directory(), name)
            st = os.lstat(path)
            self.assertEqual(0o600, stat.S_IMODE(st.st_mode))

    def test_complete_comparable_and_all_request_denominators_never_mixed(
            self):
        # Mispromotion windows count complete-comparable requests only
        # (Squirrel#152); not domain-actionable and not all semantic
        # requests.  Fault/latency windows count all semantic requests.
        # Persisted ring key recent_actionable is historical.
        for i in range(MISPROMOTION_WINDOW):
            rid = "req-mix-%d" % i
            # Not complete-comparable: must not enter the ring.
            self.store.record_request(
                request_meta(rid, complete_comparable=False), "ok",
                latency_segments={"full_request_ms": 1.0})
        self.assertEqual(0, len(self.store.aggregates()["recent_actionable"]))
        self.assertEqual(MISPROMOTION_WINDOW,
                         len(self.store.aggregates()["recent_outcomes"]))
        # Annotations on non-complete-comparable traces still require a
        # trace.
        self.store.record_request(
            request_meta("req-mix-ann", complete_comparable=False), "ok",
            trace_payload=order_change_trace("req-mix-ann"))
        self.store.record_annotation("req-mix-ann")
        self.assertEqual([], self.store.list_alarms())


if __name__ == "__main__":
    unittest.main()
