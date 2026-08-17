#!/usr/bin/env python3
"""Tests for the desensitized diagnostic report (SCN-70-6).

Pins: no raw preceding text / candidate text / traces; the report carries
code/model summaries, fingerprints, snapshot SHA-256, HLC range, seeds,
inclusion/exclusion counts, coverage, stratified metrics, milestone state
and the #69 reference; the decision record is embedded.
"""

import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from report import build_report, render_markdown  # noqa: E402
from walkforward import ENGINE_VERSION  # noqa: E402


class DummySnapshot(dict):
    def __init__(self):
        super().__init__(
            sha256="a" * 64,
            identity={"history_id": "h-1", "store_epoch": "e-1",
                      "hlc_physical_ms": "12345"},
            status={"status_check": "skipped"})


class DummyEpochIdentity:
    model_digest = "m" * 16
    tokenizer_digest = "t" * 16
    mlxlm_version = "0.31.3"
    hidden_dim = 768


def _base_report():
    return build_report(
        ENGINE_VERSION,
        DummySnapshot(),
        {"replayable_targets": 10, "complete_competition": 2,
         "actionable": 3, "coverage": 0.2, "gamma": 0.0},
        {"repr": {"state": "not_calibratable", "queries": 5}},
        [{"representation": "repr", "tau": {"state": "not_calibratable"}}],
        {"state": "diagnostic", "reason": "diagnostic"},
        {"benchmark": "quoted #69 gate state"},
        ["D1 test decision", "D2 test decision"],
        seed=42)


class ReportTest(unittest.TestCase):

    def test_report_has_no_raw_text(self):
        """The report must not contain preceding/candidate raw text."""
        report = _base_report()
        text = json.dumps(report, ensure_ascii=False)
        for prohibited in ("preceding_text", "candidate_text", "final_selection"):
            self.assertNotIn('"%s"' % prohibited, text)
        for probe in ("的的的", "我选的", "原始上文样本"):
            self.assertNotIn(probe, text)

    def test_report_carries_required_fingerprints(self):
        report = _base_report()
        self.assertEqual(report["snapshot"]["sha256"], "a" * 64)
        self.assertEqual(report["snapshot"]["history_id"], "h-1")
        self.assertEqual(report["snapshot"]["store_epoch"], "e-1")
        self.assertIn("report_sha256", report)
        self.assertIn("seed", report)
        self.assertEqual(report["seed"], 42)
        self.assertIn("decisions", report)
        self.assertEqual(report["contract"], "AC-70-v1")

    def test_report_digest_is_deterministic(self):
        first = _base_report()["report_sha256"]
        second = _base_report()["report_sha256"]
        self.assertEqual(first, second)

    def test_markdown_render_includes_headings(self):
        markdown = render_markdown(_base_report())
        self.assertIn("# Walk-Forward Evaluation Report", markdown)
        self.assertIn("Snapshot SHA-256", markdown)
        self.assertIn("Milestone", markdown)
        self.assertIn("#69", markdown)
        self.assertIn("Decision record", markdown)

    def test_milestone_diagnostic_stated(self):
        markdown = render_markdown(_base_report())
        self.assertIn("diagnostic", markdown)
        self.assertIn("not_run", markdown)


if __name__ == "__main__":
    unittest.main()
