#!/usr/bin/env python3
"""Versioned scoring protocol tests with no model or private user data."""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from server import PROTOCOL_VERSION, handle_request


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
        "plan_identity": "rerank-plan-v1:sha1:0123456789abcdef",
        "context": "private context fixture",
        "candidates": ["candidate-a", "candidate-b"],
    }
    value.update(overrides)
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False)


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
            "rerank-plan-v1:sha1:0123456789abcdef",
            response["plan_identity"],
        )

    def test_success_response_is_versioned_and_bound(self):
        response = handle_request(FakeState(), encode(request()))

        self.assertEqual(
            {
                "version": PROTOCOL_VERSION,
                "request_id": "request-17",
                "plan_identity": "rerank-plan-v1:sha1:0123456789abcdef",
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
