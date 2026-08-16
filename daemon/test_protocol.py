#!/usr/bin/env python3
"""Versioned scoring protocol tests with no model or private user data."""

import json
import math
import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from server import (
    LEGACY_SUM_POLICY_ID,
    MAX_REQUEST_BYTES,
    MEAN_TOKEN_POLICY_ID,
    PROTOCOL_VERSION,
    SCORING_STRATEGY_LEGACY_SUM,
    SCORING_STRATEGY_MEAN_TOKEN,
    NonFiniteTokenScoreError,
    TokenAttributionError,
    handle_health,
    handle_request,
    read_request,
    serve_scoring_connection,
)
from coordinator import MaintenanceCoordinator


class FakeState:
    def __init__(self, result=None, error=None):
        self.result = [1.25, -2.5] if result is None else result
        self.error = error
        self.scoring_strategy = SCORING_STRATEGY_MEAN_TOKEN
        self.loaded = False
        self.context_window = 64
        self.cache_limit_mb = 512
        self.model_path = "/fixture/models/Qwen3-0.6B-Base"

    def score(self, context, candidates):
        if self.error:
            raise RuntimeError(self.error)
        return self.result


def request(**overrides):
    value = {
        "version": PROTOCOL_VERSION,
        "request_id": "request-17",
        "plan_identity": "rerank-plan-v2:sha1:0123456789abcdef",
        "baseline_policy_id": MEAN_TOKEN_POLICY_ID,
        "context": "private context fixture",
        "candidates": ["candidate-a", "candidate-b"],
    }
    value.update(overrides)
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def encode_pairs(pairs):
    return "{" + ",".join(
        f"{json.dumps(key)}:{json.dumps(value, ensure_ascii=False)}"
        for key, value in pairs
    ) + "}"


class ScriptedSocket:
    """Deterministic recv script for framing and deadline tests."""

    def __init__(self, chunks, on_recv=None):
        self.chunks = list(chunks)
        self.timeouts = []
        self.on_recv = on_recv

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def recv(self, _size):
        if self.on_recv is not None:
            self.on_recv()
        if not self.chunks:
            return b""
        item = self.chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class BlockingResponseConnection:
    """A connection whose response write is explicitly controlled by the test."""

    def __init__(self, payload):
        self._chunks = [payload, b""]
        self.send_started = threading.Event()
        self.allow_send = threading.Event()
        self.writes = []

    def settimeout(self, _timeout):
        pass

    def recv(self, _size):
        return self._chunks.pop(0)

    def sendall(self, payload):
        self.writes.append(payload)
        self.send_started.set()
        self.allow_send.wait()


class ProtocolTest(unittest.TestCase):
    def assert_protocol_error(self, response, code):
        self.assertEqual(PROTOCOL_VERSION, response["version"])
        self.assertEqual(code, response["error"]["code"])
        self.assertEqual("validate", response["error"]["phase"])
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))

    def assert_bound_error(self, response):
        self.assertEqual("request-17", response["request_id"])
        self.assertEqual(
            "rerank-plan-v2:sha1:0123456789abcdef",
            response["plan_identity"],
        )

    def test_success_response_is_versioned_and_bound(self):
        response = handle_request(FakeState(), encode(request()))

        self.assertEqual(
            {
                "version": PROTOCOL_VERSION,
                "request_id": "request-17",
                "plan_identity": "rerank-plan-v2:sha1:0123456789abcdef",
                "scores": [1.25, -2.5],
            },
            response,
        )

    def test_prepare_waits_until_the_response_write_completes(self):
        drain_waiting = threading.Event()
        coordinator = MaintenanceCoordinator(
            "/unused",
            identity_reader=lambda _root: {
                "store_epoch": "epoch-a", "hlc_physical_ms": 1,
                "hlc_logical": 0,
            },
            prepare_wait_hook=drain_waiting.set,
        )
        connection = BlockingResponseConnection(
            (encode(request()) + "\n").encode("utf-8"))
        serving = threading.Thread(
            target=serve_scoring_connection,
            args=(FakeState(), connection, coordinator),
        )
        serving.start()
        connection.send_started.wait()

        prepared = {}
        preparing = threading.Thread(
            target=lambda: prepared.update(coordinator.prepare("op-response")))
        preparing.start()
        drain_waiting.wait()
        self.assertEqual("preparing", coordinator.health()["maintenance_state"])
        self.assertFalse(prepared)

        connection.allow_send.set()
        serving.join()
        preparing.join()
        self.assertTrue(prepared["ok"])
        self.assertEqual("prepared", coordinator.health()["maintenance_state"])
        self.assertEqual(1, len(connection.writes))

    def test_scoring_activity_is_touched_at_request_and_response_boundaries(self):
        connection = BlockingResponseConnection(
            (encode(request()) + "\n").encode("utf-8"))
        connection.allow_send.set()
        activity = []
        serve_scoring_connection(FakeState(), connection,
                                  activity_sink=lambda: activity.append(True))
        self.assertEqual(2, len(activity))

    def test_coordinated_requests_require_a_transport_completion_sink(self):
        coordinator = MaintenanceCoordinator(
            "/unused",
            identity_reader=lambda _root: {
                "store_epoch": "epoch-a", "hlc_physical_ms": 1,
                "hlc_logical": 0,
            },
        )
        response = handle_request(FakeState(), encode(request()), coordinator)
        self.assertEqual("server_error", response["error"]["code"])
        self.assertTrue(coordinator.prepare("op-no-sink")["ok"])

    def test_invalid_json_is_rejected(self):
        self.assert_protocol_error(
            handle_request(FakeState(), "not-json"), "invalid_json"
        )

    def test_missing_fields_are_rejected(self):
        for field in request():
            with self.subTest(field=field):
                damaged = request()
                del damaged[field]
                self.assert_protocol_error(
                    handle_request(FakeState(), encode(damaged)), "invalid_request"
                )

    def test_wrong_field_types_are_rejected(self):
        damaged_values = {
            "version": "1",
            "request_id": 17,
            "plan_identity": None,
            "baseline_policy_id": 17,
            "context": ["not", "text"],
            "candidates": "not-a-list",
        }
        for field, value in damaged_values.items():
            with self.subTest(field=field):
                self.assert_protocol_error(
                    handle_request(FakeState(), encode(request(**{field: value}))),
                    "invalid_request",
                )

    def test_duplicate_request_fields_are_rejected(self):
        fields = list(request().items())
        for key, value in fields:
            with self.subTest(key=key):
                response = handle_request(
                    FakeState(), encode_pairs(fields + [(key, value)])
                )
                self.assert_protocol_error(response, "invalid_json")

    def test_nested_duplicate_fields_are_rejected_before_type_validation(self):
        fields = list(request().items())
        context_index = next(
            index for index, (key, _) in enumerate(fields) if key == "context"
        )
        encoded_fields = [
            f"{json.dumps(key)}:{json.dumps(value, ensure_ascii=False)}"
            for key, value in fields
        ]
        encoded_fields[context_index] = '"context":{"x":1,"x":2}'
        response = handle_request(FakeState(), "{" + ",".join(encoded_fields) + "}")

        self.assert_protocol_error(response, "invalid_json")

    def test_trailing_payload_is_rejected(self):
        for suffix in (" ", "garbage", "\n" + encode(request())):
            with self.subTest(suffix=suffix[:10]):
                response = handle_request(FakeState(), encode(request()) + suffix)
                self.assert_protocol_error(response, "invalid_json")

    def test_split_trailing_payload_is_rejected_at_socket_framing(self):
        reader = ScriptedSocket([
            (encode(request()) + "\n").encode("utf-8"), b"garbage", b"",
        ])
        with self.assertRaises(ValueError):
            read_request(reader)

    def test_single_terminal_lf_is_accepted_at_socket_framing(self):
        reader, writer = socket.socketpair()
        encoded = encode(request())
        writer.sendall((encoded + "\n").encode("utf-8"))
        writer.shutdown(socket.SHUT_WR)
        try:
            self.assertEqual(encoded, read_request(reader))
        finally:
            reader.close()
            writer.close()

    def test_space_before_terminal_lf_is_rejected_end_to_end(self):
        reader, writer = socket.socketpair()
        writer.sendall((encode(request()) + " \n").encode("utf-8"))
        writer.shutdown(socket.SHUT_WR)
        try:
            response = handle_request(FakeState(), read_request(reader))
            self.assert_protocol_error(response, "invalid_json")
        finally:
            reader.close()
            writer.close()

    def test_request_read_uses_one_absolute_deadline(self):
        clock = [0.0]

        def advance():
            clock[0] += 0.01

        reader = ScriptedSocket([b"x", b"x", b"x", b"x"], on_recv=advance)
        with self.assertRaises(TimeoutError):
            read_request(reader, deadline_seconds=0.03, now=lambda: clock[0])
        self.assertEqual(3, len(reader.timeouts))
        for actual, expected in zip(reader.timeouts, (0.03, 0.02, 0.01)):
            self.assertAlmostEqual(expected, actual)

    def test_oversized_request_is_rejected_at_socket_framing(self):
        reader = ScriptedSocket([b"x" * (MAX_REQUEST_BYTES + 1)])
        with self.assertRaises(ValueError):
            read_request(reader)

    def test_extra_field_and_wrong_version_are_rejected(self):
        for damaged in (request(extra=True), request(version=PROTOCOL_VERSION + 1)):
            with self.subTest(damaged=damaged):
                response = handle_request(FakeState(), encode(damaged))
                self.assert_protocol_error(response, "invalid_request")

    def test_policy_mismatch_is_rejected_in_both_directions(self):
        # A mean-token daemon must reject a legacy-sum plan...
        mean_state = FakeState()
        response = handle_request(
            mean_state,
            encode(request(baseline_policy_id=LEGACY_SUM_POLICY_ID)),
        )
        self.assert_protocol_error(response, "policy_mismatch")
        self.assert_bound_error(response)
        # ...and a legacy-sum daemon must reject a mean-token plan.
        legacy_state = FakeState()
        legacy_state.scoring_strategy = SCORING_STRATEGY_LEGACY_SUM
        response = handle_request(
            legacy_state,
            encode(request(baseline_policy_id=MEAN_TOKEN_POLICY_ID)),
        )
        self.assert_protocol_error(response, "policy_mismatch")
        self.assert_bound_error(response)

    def test_matching_policy_is_accepted_in_both_modes(self):
        mean_state = FakeState()
        response = handle_request(
            mean_state,
            encode(request(baseline_policy_id=MEAN_TOKEN_POLICY_ID)),
        )
        self.assertIn("scores", response)
        legacy_state = FakeState()
        legacy_state.scoring_strategy = SCORING_STRATEGY_LEGACY_SUM
        response = handle_request(
            legacy_state,
            encode(request(baseline_policy_id=LEGACY_SUM_POLICY_ID)),
        )
        self.assertIn("scores", response)

    # -- frozen shadow baseline policy id (Habit130/squirrel#75) ----------

    def frozen_baseline_id(self, **overrides):
        value = ("frozen-baseline-v1:rule=mean-token-lm-v1:model=Qwen3-0.6B-Base"
                 ":tokenizer=Qwen3-0.6B-Base:norm=nfc-simplified:fail=fail-closed"
                 ":squirrel=0123456789ab:plugin=cdef01234567:alpha=0.0"
                 ":beta_sys=1.0:beta_usr=1.0")
        for key, replacement in overrides.items():
            marker = f"{key}="
            start = value.index(marker)
            end = value.find(":", start)
            value = value[:start] + marker + replacement + value[end:]
        return value

    def test_frozen_baseline_id_is_accepted_by_mean_token(self):
        response = handle_request(
            FakeState(),
            encode(request(baseline_policy_id=self.frozen_baseline_id())),
        )
        self.assertIn("scores", response)

    def test_frozen_baseline_id_is_rejected_by_legacy_sum(self):
        legacy_state = FakeState()
        legacy_state.scoring_strategy = SCORING_STRATEGY_LEGACY_SUM
        response = handle_request(
            legacy_state,
            encode(request(baseline_policy_id=self.frozen_baseline_id())),
        )
        self.assert_protocol_error(response, "policy_mismatch")
        self.assert_bound_error(response)

    def test_frozen_baseline_id_with_wrong_rule_is_rejected(self):
        response = handle_request(
            FakeState(),
            encode(request(
                baseline_policy_id=self.frozen_baseline_id(
                    rule=LEGACY_SUM_POLICY_ID))),
        )
        self.assert_protocol_error(response, "policy_mismatch")

    def test_frozen_baseline_id_with_wrong_model_is_rejected(self):
        response = handle_request(
            FakeState(),
            encode(request(
                baseline_policy_id=self.frozen_baseline_id(
                    model="SomeOtherModel"))),
        )
        self.assert_protocol_error(response, "policy_mismatch")
        # The mismatch error never echoes the declared identity.
        self.assertNotIn("SomeOtherModel", str(response))

    def test_frozen_baseline_id_with_wrong_tokenizer_is_rejected(self):
        response = handle_request(
            FakeState(),
            encode(request(
                baseline_policy_id=self.frozen_baseline_id(
                    tokenizer="SomeOtherTokenizer"))),
        )
        self.assert_protocol_error(response, "policy_mismatch")

    def test_malformed_frozen_baseline_ids_are_rejected(self):
        state = FakeState()
        for damaged in (
            "frozen-baseline-v1:",
            "frozen-baseline-v1:rule=mean-token-lm-v1",
            "frozen-baseline-v1:model=Qwen3-0.6B-Base:tokenizer=Qwen3-0.6B-Base",
            "frozen-baseline-v1:rule=mean-token-lm-v1:model=Qwen3-0.6B-Base"
            ":tokenizer=Qwen3-0.6B-Base:unknown=1",
            "frozen-baseline-v1:rule=mean-token-lm-v1:model=:tokenizer=qwen",
            "frozen-baseline-v1:rule=mean-token-lm-v1:rule=legacy-sum"
            ":model=Qwen3-0.6B-Base:tokenizer=Qwen3-0.6B-Base",
            "frozen-baseline-v1:rule=mean-token-lm-v1:model=Qwen3-0.6B-Base"
            ":tokenizer=Qwen3-0.6B-Base:bogus",
            "not-a-frozen-id",
            "frozen-baseline-v1:rule=mean-token-lm-v1:model=Qwen3-0.6B-Base"
            ":tokenizer=Qwen3-0.6B-Base:alpha=",
        ):
            with self.subTest(damaged=damaged):
                response = handle_request(
                    state, encode(request(baseline_policy_id=damaged)))
                self.assert_protocol_error(response, "policy_mismatch")

    def test_frozen_baseline_id_mismatch_does_not_echo_input(self):
        response = handle_request(
            FakeState(),
            encode(request(
                baseline_policy_id=self.frozen_baseline_id(
                    model="WrongModel"))),
        )
        self.assertEqual("policy_mismatch", response["error"]["code"])
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))
        self.assertNotIn("WrongModel", str(response["error"]))

    def test_policy_mismatch_does_not_echo_input(self):
        response = handle_request(
            FakeState(),
            encode(request(baseline_policy_id=LEGACY_SUM_POLICY_ID)),
        )
        self.assertEqual("policy_mismatch", response["error"]["code"])
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))
        self.assertNotIn("first-stage-base-v1", str(response["error"]))

    def test_score_count_mismatch_is_not_emitted_as_success(self):
        response = handle_request(FakeState(result=[1.0]), encode(request()))
        self.assert_protocol_error(response, "score_count_mismatch")
        self.assert_bound_error(response)

    def test_invalid_score_field_is_not_emitted_as_success(self):
        response = handle_request(
            FakeState(result=["not-a-score", 0.0]), encode(request())
        )
        self.assert_protocol_error(response, "invalid_score_result")
        self.assert_bound_error(response)

    def test_non_finite_score_is_not_emitted_as_success(self):
        for score in (math.nan, math.inf, -math.inf, 10**10000):
            with self.subTest(score=score):
                response = handle_request(
                    FakeState(result=[score, 0.0]), encode(request())
                )
                self.assert_protocol_error(
                    response,
                    "non_finite_score",
                )
                self.assert_bound_error(response)

    def test_inference_failure_does_not_echo_exception_or_input(self):
        secret = "private context fixture candidate-a hidden embedding"
        response = handle_request(FakeState(error=secret), encode(request()))

        self.assertEqual("inference_failed", response["error"]["code"])
        self.assert_bound_error(response)
        self.assertNotIn(secret, str(response))
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))

    def test_empty_candidate_is_rejected(self):
        response = handle_request(
            FakeState(), encode(request(candidates=["", "b"]))
        )
        self.assert_protocol_error(response, "invalid_request")
        self.assertNotIn('""', str(response["error"]))

    def test_token_attribution_failure_is_bound_and_silent(self):
        class AttributionFailingState(FakeState):
            def score(self, context, candidates):
                raise TokenAttributionError("token straddles boundary")

        response = handle_request(AttributionFailingState(), encode(request()))

        self.assertEqual("token_attribution_failed", response["error"]["code"])
        self.assertEqual("score", response["error"]["phase"])
        self.assert_bound_error(response)
        self.assertNotIn("straddles", str(response))
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))

    def test_non_finite_token_score_is_bound_and_silent(self):
        class NonFiniteState(FakeState):
            def score(self, context, candidates):
                raise NonFiniteTokenScoreError()

        response = handle_request(NonFiniteState(), encode(request()))

        self.assertEqual("non_finite_score", response["error"]["code"])
        self.assert_bound_error(response)
        self.assertNotIn("private context fixture", str(response))


class HealthHandshakeTest(unittest.TestCase):
    def health_request(self, **overrides):
        value = {
            "version": PROTOCOL_VERSION,
            "request_id": "health-1",
            "kind": "health",
        }
        value.update(overrides)
        return value

    def test_health_response_is_versioned_and_model_free(self):
        state = FakeState()
        state.scoring_strategy = SCORING_STRATEGY_MEAN_TOKEN
        response = handle_request(state, encode(self.health_request()))
        self.assertEqual(PROTOCOL_VERSION, response["version"])
        self.assertEqual("health-1", response["request_id"])
        self.assertEqual("health", response["kind"])
        health = response["health"]
        self.assertFalse(health["model_loaded"])
        self.assertEqual(MEAN_TOKEN_POLICY_ID, health["policy_id"])
        self.assertEqual(SCORING_STRATEGY_MEAN_TOKEN, health["scoring_strategy"])
        self.assertEqual("Qwen3-0.6B-Base", health["model_identity"])
        self.assertEqual(64, health["context_window"])
        self.assertIsInstance(health["pid"], int)
        # The daemon state is never touched by the handshake: loading stays
        # off and no score() call happens.
        self.assertFalse(state.loaded)

    def test_health_reports_loaded_model_state(self):
        state = FakeState()
        state.loaded = True
        response = handle_request(state, encode(self.health_request()))
        self.assertTrue(response["health"]["model_loaded"])

    def test_health_reports_legacy_sum_policy(self):
        state = FakeState()
        state.scoring_strategy = SCORING_STRATEGY_LEGACY_SUM
        response = handle_request(state, encode(self.health_request()))
        self.assertEqual(LEGACY_SUM_POLICY_ID, response["health"]["policy_id"])

    def test_health_rejects_extra_or_missing_fields(self):
        for damaged in (
            self.health_request(extra="x"),
            self.health_request(request_id=""),
            self.health_request(version=PROTOCOL_VERSION + 1),
            self.health_request(version="2"),
            {"version": PROTOCOL_VERSION, "kind": "health"},
            {"version": PROTOCOL_VERSION, "request_id": "health-1"},
        ):
            with self.subTest(damaged=damaged):
                response = handle_request(FakeState(), encode(damaged))
                self.assertEqual("invalid_request", response["error"]["code"])

    def test_scoring_request_with_kind_is_rejected(self):
        response = handle_request(
            FakeState(), encode(request(kind="health"))
        )
        self.assertEqual("invalid_request", response["error"]["code"])
        self.assertNotIn("private context fixture", str(response))

    def test_health_never_echoes_private_input(self):
        response = handle_request(FakeState(), encode(self.health_request()))
        self.assertNotIn("private context fixture", str(response))
        self.assertNotIn("candidate-a", str(response))

    def test_health_handshake_does_not_run_score(self):
        class ExplodingState(FakeState):
            def score(self, context, candidates):
                raise AssertionError("health must never score")

        response = handle_request(ExplodingState(), encode(self.health_request()))
        self.assertEqual("health", response["kind"])

    def test_handle_health_is_strict_on_field_shapes(self):
        state = FakeState()
        response = handle_health(state, {"version": PROTOCOL_VERSION,
                                         "request_id": "h", "kind": "health"})
        self.assertEqual("health", response["kind"])
        self.assertEqual("h", response["request_id"])


if __name__ == "__main__":
    unittest.main()
