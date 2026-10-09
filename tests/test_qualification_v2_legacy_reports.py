"""Read-only legacy adapter fixtures: missing fields never become zero/pass."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from localbench.v2.report_adapter import normalize_legacy_report


class LegacyReportAdapterTests(unittest.TestCase):
    def test_historical_role_report_missing_values_remain_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review-package.json"
            path.write_text(json.dumps({
                "schema_version": "flashnext-role-review-package:v1",
                "metadata": {"candidate_id": "legacy"},
                "case_results": [{"case_id": "tester-case-c", "role": "tester",
                                  "status": "success", "deterministic_passed": True}],
            }), encoding="utf-8")
            row = normalize_legacy_report(path)["cases"][0]
            self.assertIsNone(row["human_adjudication"])
            self.assertIsNone(row["suite_version"])
            self.assertIsNone(row["model_identity"])
            self.assertEqual(row["deterministic_passed"], True)

    def test_assistant_blocked_successor_not_attempted_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps({
                "campaign": "assistant-001-v1", "track": "fixed-plan-worker-chain",
                "results": [{"case_id": "T01", "status": "error",
                             "deterministic_passed": False},
                            {"case_id": "T02", "status": "blocked",
                             "deterministic_passed": None}],
            }), encoding="utf-8")
            report = normalize_legacy_report(path)
            self.assertEqual(report["source_kind"], "assistant-worker-project")
            self.assertIsNone(report["cases"][1]["deterministic_passed"])
            self.assertEqual(report["cases"][1]["execution_status"], "blocked")
            self.assertIsNone(report["role_qualification"])

    def test_unknown_report_rejected_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.json"
            path.write_text('{"status":"success"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                normalize_legacy_report(path)


if __name__ == "__main__":
    unittest.main()
