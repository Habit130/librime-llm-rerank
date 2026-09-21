#!/usr/bin/env python3
"""Daily leave-on lifecycle pins (Habit130/squirrel#186)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import server
from server import ModelState

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKOUT = os.path.dirname(HERE)


class DailyLifecycleTest(unittest.TestCase):
    def test_idle_timeout_remains_five_minutes(self):
        self.assertEqual(300, server.IDLE_TIMEOUT)

    def test_unload_clears_resident_weights(self):
        state = ModelState("/tmp/unused-model")
        state.model = object()
        state.tokenizer = object()
        self.assertTrue(state.loaded)
        state.unload()
        self.assertFalse(state.loaded)
        self.assertIsNone(state.model)
        self.assertIsNone(state.tokenizer)

    def test_idle_watchdog_still_unloads_on_injected_timeout(self):
        state = ModelState("/tmp/unused-model")
        state.model = object()
        last_activity = 0.0
        idle_timeout = 0.05
        now = last_activity + idle_timeout + 0.01
        if state.loaded and (now - last_activity) > idle_timeout:
            state.unload()
        self.assertFalse(state.loaded)

    def test_watchdog_source_uses_idle_timeout_and_has_no_sleep_timer(self):
        path = os.path.join(HERE, "server.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("IDLE_TIMEOUT = 300", text)
        self.assertIn(
            "if state.loaded and (time.time() - last_activity) > IDLE_TIMEOUT:",
            text,
        )
        self.assertIn("state.unload()", text)
        self.assertNotIn("post-sleep", text)
        self.assertNotIn("on_wake", text)
        self.assertNotIn("SLEEP_TIMEOUT", text)

    def test_launchd_template_keeps_phase1_lifecycle(self):
        path = os.path.join(HERE, "com.squirrel.llm-rerank.plist")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("<key>RunAtLoad</key>", text)
        self.assertIn("<key>KeepAlive</key>", text)
        self.assertIn("<true/>", text)
        self.assertIn("--adapter", text)
        self.assertIn("LLM_RERANK_ADAPTER", text)
        self.assertIn("<string>64</string>", text)
        self.assertNotIn("--health-only", text)

    def test_runbook_keeps_public_alpha_zero_and_stop_as_procedure(self):
        path = os.path.join(CHECKOUT, "docs", "personal-lora-live.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("alpha: 0.0", text)
        self.assertIn("does **not** self-enable", text)
        self.assertIn("not** the #186", text)
        self.assertIn("IDLE_TIMEOUT", text)
        self.assertIn("RunAtLoad", text)


if __name__ == "__main__":
    unittest.main()
