#!/usr/bin/env python3
"""Passive daemon archive observation tests (Habit130/squirrel#191).

These are model-free: a recording producer stub captures what the observer
would admit, and the production handle_request/ModelState hook wiring is
exercised with deterministic fixture states. No collector, no MLX, no model.
"""

import json
import os
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from archive_observation import (  # noqa: E402
    DAEMON_OBSERVATION_VERSION,
    DaemonArchiveObserver,
    monotonic_ms,
)
from server import (  # noqa: E402
    ModelState,
    handle_request,
    make_request,
    window_context,
)


def _wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class RecordingProducer(object):
    def __init__(self, fresh=True, desired="enabled", unavailable=False):
        self.frames = []
        self.closed = False
        self.fresh = fresh
        self.desired = desired
        self.unavailable = unavailable

    def admit(self, frame):
        self.frames.append(json.loads(json.dumps(frame)))

        class Result(object):
            admitted = True
            code = "admitted"

        return Result()

    def local_status(self):
        return {
            "interface_version": "input-archive-v1",
            "source_instance_id": "stub",
            "observed_revision": 1,
            "observed_desired": self.desired,
            "fresh": self.fresh,
            "collector_unavailable": self.unavailable,
            "queued": 0,
            "known_refused": 0,
            "known_dropped": 0,
            "content_included": False,
        }

    def close(self):
        self.closed = True


class RecordingObserver(object):
    def __init__(self):
        self.calls = []
        self.fail = False

    def _record(self, name, payload=None):
        if self.fail:
            raise RuntimeError("observer fault")
        self.calls.append((name, payload))

    def next_process_id(self):
        if self.fail:
            raise RuntimeError("observer fault")
        return "dsr-test-1"

    def observe_request(self, request, state, process_id, effective_policy_id):
        self._record("request", (request["request_id"], process_id))
        return {"request_accepted": 1.0}

    def observe_scoring_outcome(self, meta):
        if self.fail:
            raise RuntimeError("observer fault")
        self.calls.append(("outcome", meta))

    def note_load_started(self):
        if self.fail:
            raise RuntimeError("observer fault")
        self.calls.append(("load_started", None))
        return 1.0

    def note_load_finished(self, started_ms, ok, state):
        if self.fail:
            raise RuntimeError("observer fault")
        self.calls.append(("load_finished", ok))

    def note_unload(self, reason, state):
        if self.fail:
            raise RuntimeError("observer fault")
        self.calls.append(("unload", reason))


class FakeState(object):
    """The subset of ModelState that handle_request touches."""

    def __init__(self, observer=None, fail_score=False, scores=None,
                 context_window=64):
        self.observer = observer
        self.model_path = "/models/Qwen3-0.6B-Base"
        self.adapter_path = ""
        self.adapter_digest = None
        self.context_window = context_window
        self.scoring_strategy = "mean_token"
        self.load_generation = 0
        self.last_load_ms = None
        self.fail_score = fail_score
        self.scores = scores
        self.score_calls = []

    def score(self, context, candidates):
        self.score_calls.append((context, list(candidates)))
        if self.fail_score:
            raise RuntimeError("fixture failure")
        if self.scores is not None:
            return list(self.scores)
        return [-(index + 1) * 0.25 for index in range(len(candidates))]


class ObserverFrameTests(unittest.TestCase):
    def _observer(self, parent_mode=0o700, **stub_kwargs):
        root = tempfile.mkdtemp(prefix="ac191-unit-")
        root = os.path.realpath(root)
        os.chmod(root, 0o700)
        if parent_mode != 0o700:
            os.chmod(root, parent_mode)
        observer = DaemonArchiveObserver(
            os.path.join(root, "collector.sock"),
            source_instance_id="daemon-test-1",
        )
        observer._producer.close()
        observer._producer = RecordingProducer(**stub_kwargs)
        return observer, root

    def test_request_frame_shape_and_payload(self):
        observer, root = self._observer()
        state = FakeState()
        request = make_request(
            "req-1", "rerank-plan-v2:sha1:abc", "1234567890\u4e0a\u6587",
            ["\u653b\u51fb", "\u516c\u9e21"],
        )
        request["baseline_policy_id"] = "mean-token-lm-v1"
        edges = observer.observe_request(
            request, state, "dsr-test-1", "mean-token-lm-v1")
        self.assertEqual(edges["request_accepted"], edges["request_accepted"])
        frames = observer._producer.frames
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame["observation_kind"], "daemon_observation")
        self.assertEqual(frame["daemon_observation_version"], DAEMON_OBSERVATION_VERSION)
        self.assertEqual(frame["daemon_stage"], "request")
        self.assertEqual(frame["source_instance_id"], "daemon-test-1")
        self.assertEqual(frame["request_id"], "req-1")
        self.assertEqual(frame["plan_identity"], "rerank-plan-v2:sha1:abc")
        self.assertEqual(frame["effective_policy_id"], "mean-token-lm-v1")
        self.assertEqual(frame["context_window_chars"], 64)
        self.assertEqual(frame["requested_context_chars"], 12)
        self.assertEqual(frame["effective_context_chars"],
                         len(window_context("1234567890\u4e0a\u6587", 64)))
        self.assertFalse(frame["context_truncated"])
        self.assertEqual(frame["candidate_count"], 2)
        self.assertEqual(frame["candidate_chars"], 4)
        self.assertTrue(frame["declared_policy_exact"])
        self.assertEqual(len(frame["declared_policy_digest"]), 64)
        self.assertEqual(frame["model_identity"], "Qwen3-0.6B-Base")
        self.assertFalse(frame["adapter_present"])
        self.assertEqual(
            frame["payload"],
            {
                "requested_context": "1234567890\u4e0a\u6587",
                "effective_context": "1234567890\u4e0a\u6587",
                "candidates": ["\u653b\u51fb", "\u516c\u9e21"],
            },
        )
        self.assertEqual(observer.local_status()["content_included"], False)
        json.dumps(observer.local_status(), sort_keys=True)

    def test_request_window_truncation_and_unsafe_tokens(self):
        observer, root = self._observer()
        state = FakeState(context_window=8)
        context = "abcdefghijkl"
        request = make_request(
            "req with space", "plan/unsafe", context, ["x"],
        )
        observer.observe_request(request, state, "dsr-test-1",
                                 "mean-token-lm-v1")
        frame = observer._producer.frames[0]
        self.assertEqual(frame["context_window_chars"], 8)
        self.assertEqual(frame["effective_context_chars"], 8)
        self.assertTrue(frame["context_truncated"])
        self.assertEqual(frame["payload"]["effective_context"], "efghijkl")
        # Non-token identities degrade to unknown instead of failing the frame.
        self.assertIsNone(frame["request_id"])
        self.assertIsNone(frame["plan_identity"])

    def test_outcome_frame_carries_edges_and_no_payload(self):
        observer, root = self._observer()
        observer.observe_scoring_outcome({
            "process_id": "dsr-test-1",
            "request_id": "req-1",
            "outcome_code": "ok",
            "error_phase": None,
            "scoring_started": True,
            "load_included": True,
            "scoring_ms": 12.5,
            "load_ms": 8.25,
            "scores_returned": 2,
            "edges": {
                "request_accepted": 1.0,
                "scoring_started": 1.5,
                "scoring_completed": 14.0,
                "outcome_decided": 14.1,
            },
        })
        frame = observer._producer.frames[0]
        self.assertEqual(frame["daemon_stage"], "scoring")
        self.assertEqual(frame["outcome_code"], "ok")
        self.assertIsNone(frame["error_phase"])
        self.assertEqual(frame["scoring_ms"], 12.5)
        self.assertEqual(frame["load_ms"], 8.25)
        self.assertEqual(frame["scores_returned"], 2)
        self.assertNotIn("payload", frame)

    def test_load_and_unload_frames(self):
        observer, root = self._observer()
        state = FakeState()
        state.identity_record = {
            "model": {
                "basename": "Qwen3-0.6B-Base",
                "files": {"model.safetensors": {"sha256": "a" * 64}},
            },
            "versions": {"mlx": "0.32.0", "mlx-lm": "0.31.3", "numpy": "2.4.6"},
        }
        started = observer.note_load_started()
        observer.note_load_finished(started, True, state)
        frame = observer._producer.frames[0]
        self.assertEqual(frame["daemon_stage"], "load")
        self.assertEqual(frame["load_outcome"], "completed")
        self.assertGreaterEqual(frame["load_ms"], 0)
        self.assertEqual(frame["model_identity"], "Qwen3-0.6B-Base")
        self.assertEqual(frame["model_weights_sha256"], "a" * 64)
        self.assertIsNone(frame["tokenizer_identity"])
        self.assertEqual(frame["runtime_versions"]["mlx"], "0.32.0")
        observer.note_unload("identity_change", state)
        frame = observer._producer.frames[1]
        self.assertEqual(frame["daemon_stage"], "unload")
        self.assertEqual(frame["unload_reason"], "identity_change")
        observer.note_unload("weird", state)
        self.assertEqual(observer._producer.frames[2]["unload_reason"],
                         "unspecified")

    def test_ineffective_policy_never_builds_payload(self):
        observer, root = self._observer(fresh=False)
        state = FakeState()
        request = make_request("req-1", "plan-1", "secret", ["c"])
        edges = observer.observe_request(request, state, "dsr-test-1",
                                         "mean-token-lm-v1")
        self.assertIn("request_accepted", edges)
        self.assertFalse(observer.capture_effective())
        self.assertEqual(observer._producer.frames, [])
        observer2, root2 = self._observer(desired="paused")
        self.assertFalse(observer2.capture_effective())
        self.assertEqual(observer2._producer.frames, [])
        observer3, root3 = self._observer(unavailable=True)
        self.assertFalse(observer3.capture_effective())

    def test_untrusted_socket_is_refused_before_content(self):
        observer, root = self._observer(parent_mode=0o755)
        self.assertEqual(observer.disabled_reason, "unsafe_archive_socket")
        state = FakeState()
        response_edges = observer.observe_request(
            make_request("req-1", "plan-1", "secret", ["c"]),
            state, "dsr-test-1", "mean-token-lm-v1")
        self.assertIn("request_accepted", response_edges)
        self.assertEqual(observer._producer.frames, [])
        self.assertEqual(observer.local_status()["refused_untrusted"], 0)

    def test_malformed_collector_results_never_certify_persistence(self):
        """A peer that answers well-formed frames with an empty body (no
        per-item `codes`) must leave the observation unaccounted, counted as
        refused, and never durable."""

        class FakePeer(object):
            def __init__(self, path):
                self.path = path
                self._stop = False
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.bind(path)
                os.chmod(path, 0o600)
                self._sock.listen(4)
                self._sock.settimeout(0.2)
                self._thread = threading.Thread(target=self._serve, daemon=True)
                self._thread.start()

            def _serve(self):
                while not self._stop:
                    try:
                        conn, _ = self._sock.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    try:
                        conn.settimeout(1.0)
                        header = conn.recv(4)
                        if len(header) < 4:
                            continue
                        (size,) = struct.unpack(">I", header)
                        payload = b""
                        while len(payload) < size:
                            chunk = conn.recv(size - len(payload))
                            if not chunk:
                                break
                            payload += chunk
                        request = json.loads(payload.decode("utf-8"))
                        body = {}
                        if request.get("op") == "policy_observe":
                            body = {
                                "desired_policy": "enabled",
                                "desired_revision": 7,
                            }
                        reply = json.dumps({
                            "interface_version": "input-archive-v1",
                            "envelope_version": 1,
                            "op": request.get("op"),
                            "ok": True,
                            "body": body,
                            "content_included": False,
                        }).encode("utf-8")
                        conn.sendall(struct.pack(">I", len(reply)) + reply)
                    except Exception:
                        pass
                    finally:
                        conn.close()

            def stop(self):
                self._stop = True
                try:
                    self._sock.close()
                except OSError:
                    pass

        root = os.path.realpath(tempfile.mkdtemp(prefix="ac191-peer-"))
        os.chmod(root, 0o700)
        peer = FakePeer(os.path.join(root, "collector.sock"))
        try:
            observer = DaemonArchiveObserver(
                os.path.join(root, "collector.sock"),
                source_instance_id="daemon-peer-test",
            )
            self.assertTrue(_wait_until(
                lambda: observer.local_status()["observed_desired"] == "enabled",
                timeout=5.0,
            ))
            result = observer.observe_request(
                make_request("req-peer", "plan-peer", "\u540c\u4f34", ["\u540c\u4f34"]),
                FakeState(), "dsr-test-1", "mean-token-lm-v1",
            )
            self.assertIsInstance(result, dict)
            self.assertTrue(_wait_until(
                lambda: observer.local_status()["known_refused"] >= 1,
                timeout=5.0,
            ))
            status = observer.local_status()
            self.assertGreaterEqual(status["known_refused"], 1)
            self.assertNotIn("durable", status)
            observer.close()
        finally:
            peer.stop()

    def test_foreign_socket_file_is_refused_per_admission(self):
        observer, root = self._observer()
        # A foreign, non-socket occupant appears at the configured path.
        path = os.path.join(root, "collector.sock")
        with open(path, "w") as handle:
            handle.write("x")
        os.chmod(path, 0o644)
        observer.observe_request(
            make_request("req-1", "plan-1", "secret", ["c"]),
            FakeState(), "dsr-test-1", "mean-token-lm-v1",
        )
        self.assertEqual(observer._producer.frames, [])
        # The admission gate re-checks before any frame is held.
        observer._admit({"observation_kind": "daemon_observation"})
        self.assertEqual(observer._producer.frames, [])
        self.assertGreaterEqual(observer.local_status()["refused_untrusted"], 1)


class ObservedModelStateTests(unittest.TestCase):
    def _fixture_state(self, observer):
        class FixtureState(ModelState):
            def __init__(self):
                super().__init__("fixture-model", adapter_path="")
                self.observer = observer
                self.fail_next = False

            def _load_base_model(self):
                if self.fail_next:
                    self.fail_next = False
                    raise RuntimeError("fixture load failure")
                self.model = object()

                class _Tokenizer:
                    pad_token_id = 1
                    eos_token_id = 1

                self.tokenizer = _Tokenizer()
                self.pad_id = 1

        return FixtureState()

    def test_load_unload_hooks_fire_once_per_transition(self):
        observer = RecordingObserver()
        state = self._fixture_state(observer)
        state.load()
        state.load()
        self.assertEqual(
            [name for name, _ in observer.calls],
            ["load_started", "load_finished"],
        )
        self.assertEqual(state.load_generation, 1)
        self.assertIsNotNone(state.last_load_ms)
        state.unload(reason="idle")
        self.assertEqual(observer.calls[-1], ("unload", "idle"))
        state.unload(reason="idle")
        self.assertEqual(
            [name for name, _ in observer.calls].count("unload"), 1)

    def test_failed_load_is_observed_and_propagates(self):
        observer = RecordingObserver()
        state = self._fixture_state(observer)
        state.fail_next = True
        with self.assertRaises(RuntimeError):
            state.load()
        self.assertEqual(
            [name for name, _ in observer.calls],
            ["load_started", "load_finished"],
        )
        self.assertEqual(observer.calls[-1][1], False)
        self.assertEqual(state.load_generation, 1)
        self.assertIsNone(state.model)

    def test_observer_faults_do_not_change_load_results(self):
        observer = RecordingObserver()
        observer.fail = True
        state = self._fixture_state(observer)
        state.load()
        self.assertTrue(state.loaded)
        state.unload(reason="idle")
        self.assertFalse(state.loaded)


class HandleRequestObservationTests(unittest.TestCase):
    def _request_bytes(self, **overrides):
        request = make_request(
            overrides.pop("request_id", "req-1"),
            overrides.pop("plan_identity", "plan-1"),
            overrides.pop("context", "\u4e0a\u6587"),
            overrides.pop("candidates", ["\u653b\u51fb", "\u516c\u9e21"]),
        )
        request.update(overrides)
        return json.dumps(request, ensure_ascii=False)

    def test_success_binds_request_and_outcome(self):
        observer = RecordingObserver()
        state = FakeState(observer=observer)
        response = handle_request(state, self._request_bytes())
        self.assertIn("scores", response)
        names = [name for name, _ in observer.calls]
        self.assertEqual(names[0], "request")
        self.assertEqual(names[1], "outcome")
        request_id, process_id = observer.calls[0][1]
        self.assertEqual(request_id, "req-1")
        meta = observer.calls[1][1]
        self.assertEqual(meta["process_id"], process_id)
        self.assertEqual(meta["outcome_code"], "ok")
        self.assertTrue(meta["scoring_started"])
        self.assertFalse(meta["load_included"])
        self.assertIsNone(meta["load_ms"])
        self.assertEqual(meta["scores_returned"], 2)
        self.assertGreaterEqual(meta["scoring_ms"], 0)
        edges = meta["edges"]
        self.assertLessEqual(edges["request_accepted"], edges["scoring_started"])
        self.assertLessEqual(edges["scoring_started"], edges["scoring_completed"])
        self.assertLessEqual(edges["scoring_completed"], edges["outcome_decided"])

    def test_load_inclusion_uses_generation_not_inference(self):
        observer = RecordingObserver()
        state = FakeState(observer=observer)

        def score(context, candidates):
            state.load_generation += 1
            state.last_load_ms = 3.5
            return [-1.0 for _ in candidates]

        state.score = score
        response = handle_request(state, self._request_bytes())
        self.assertIn("scores", response)
        meta = observer.calls[1][1]
        self.assertTrue(meta["load_included"])
        self.assertEqual(meta["load_ms"], 3.5)

    def test_scoring_error_outcome_and_unchanged_response(self):
        observer = RecordingObserver()
        state = FakeState(observer=observer, fail_score=True)
        response = handle_request(state, self._request_bytes())
        self.assertEqual(response["error"]["code"], "inference_failed")
        self.assertEqual(response["error"]["phase"], "score")
        meta = observer.calls[1][1]
        self.assertEqual(meta["outcome_code"], "inference_failed")
        self.assertEqual(meta["error_phase"], "score")
        self.assertTrue(meta["scoring_started"])

    def test_pre_scoring_refusals_are_not_observed(self):
        observer = RecordingObserver()
        state = FakeState(observer=observer)
        response = handle_request(
            state, self._request_bytes(baseline_policy_id="other-policy-v1"))
        self.assertEqual(response["error"]["code"], "policy_mismatch")
        self.assertEqual(observer.calls, [])
        response = handle_request(state, "not-json\n")
        self.assertEqual(response["error"]["code"], "invalid_json")
        self.assertEqual(observer.calls, [])
        self.assertEqual(state.score_calls, [])

    def test_observer_faults_never_replace_valid_responses(self):
        observer = RecordingObserver()
        observer.fail = True
        state = FakeState(observer=observer)
        response = handle_request(state, self._request_bytes())
        self.assertIn("scores", response)
        self.assertEqual(response["scores"], [-0.25, -0.5])

    def test_no_observer_means_no_calls(self):
        state = FakeState(observer=None)
        response = handle_request(state, self._request_bytes())
        self.assertIn("scores", response)

    def test_invalid_score_results_stay_truthful(self):
        observer = RecordingObserver()
        state = FakeState(observer=observer, scores=[float("inf"), 1.0])
        response = handle_request(state, self._request_bytes())
        self.assertEqual(response["error"]["code"], "non_finite_score")
        self.assertEqual(observer.calls[1][1]["outcome_code"], "non_finite_score")
        self.assertIsNone(observer.calls[1][1]["scores_returned"])
        state = FakeState(observer=observer, scores=[1.0])
        response = handle_request(state, self._request_bytes())
        self.assertEqual(response["error"]["code"], "score_count_mismatch")


if __name__ == "__main__":
    unittest.main()
