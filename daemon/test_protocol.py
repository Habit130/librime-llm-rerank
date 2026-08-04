#!/usr/bin/env python3
"""Versioned scoring protocol tests with no model or private user data."""

import json
import math
import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from server import (
    MAX_REQUEST_BYTES,
    PROTOCOL_VERSION,
    handle_request,
    read_request,
)


class FakeState:
    def __init__(self, result=None, error=None):
        self.result = [1.25, -2.5] if result is None else result
        self.error = error

    def score(self, context, candidates):
        if self.error:
            raise RuntimeError(self.error)
        return self.result


def request(**overrides):
    value = {
        "version": PROTOCOL_VERSION,
        "request_id": "request-17",
        "plan_identity": "rerank-plan-v2:sha1:0123456789abcdef",
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
        reader, writer = socket.socketpair()

        def send_split_request():
            writer.sendall((encode(request()) + "\n").encode("utf-8"))
            time.sleep(0.01)
            writer.sendall(b"garbage")
            writer.shutdown(socket.SHUT_WR)

        thread = threading.Thread(target=send_split_request)
        thread.start()
        try:
            with self.assertRaises(ValueError):
                read_request(reader)
        finally:
            thread.join()
            reader.close()
            writer.close()

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
        reader, writer = socket.socketpair()

        def drip_request():
            try:
                for _ in range(20):
                    writer.sendall(b"x")
                    time.sleep(0.01)
            except OSError:
                pass

        thread = threading.Thread(target=drip_request)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                read_request(reader, deadline_seconds=0.03)
            self.assertLess(time.monotonic() - started, 0.15)
        finally:
            reader.close()
            writer.close()
            thread.join()

    def test_oversized_request_is_rejected_at_socket_framing(self):
        reader, writer = socket.socketpair()

        def send_oversized_request():
            writer.sendall(b"x" * (MAX_REQUEST_BYTES + 1))
            writer.shutdown(socket.SHUT_WR)

        thread = threading.Thread(target=send_oversized_request)
        thread.start()
        try:
            with self.assertRaises(ValueError):
                read_request(reader)
        finally:
            thread.join()
            reader.close()
            writer.close()

    def test_extra_field_and_wrong_version_are_rejected(self):
        for damaged in (request(extra=True), request(version=2)):
            with self.subTest(damaged=damaged):
                response = handle_request(FakeState(), encode(damaged))
                self.assert_protocol_error(response, "invalid_request")

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


if __name__ == "__main__":
    unittest.main()
