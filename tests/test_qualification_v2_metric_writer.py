"""Writer parity and no-fabrication regression for the T13 metric projection."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from localbench.v2.flashnext_review import write_review_package


class MetricWriterTests(unittest.TestCase):
    def test_legacy_package_remains_usable_and_new_metrics_are_unscored(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = write_review_package(
                output_dir=out, phase="screen", shared_run=None,
                profile={"candidate_id": "C01", "candidate_name": "example"},
                summary={"results": [
                    {"role": "tester", "case_id": "tester-case-c", "status": "success",
                     "human_review_required": True, "deterministic_passed": True,
                     "evidence_directory": str(out / "evidence")},
                    {"role": "worker", "case_id": "task2", "status": "blocked",
                     "execution_status": "prerequisite_blocked"},
                ], "roles": ["tester", "worker"], "planned_cases": 2,
                    "completed_cases": 1, "stopped": None})
            self.assertTrue(Path(result["xlsx"]).exists())
            self.assertTrue(Path(result["metric_summary_csv"]).exists())
            package = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertEqual(package["schema_version"], "flashnext-role-review-package:v1")
            self.assertEqual(len(package["case_results"]), 2)
            metrics = package["qualification_v2_metrics"]
            self.assertIsNone(metrics["universal_intelligence_score"])
            self.assertFalse(metrics["automatic_role_assignment"])
            self.assertTrue(all(x["percentage"] is None for x in metrics["metrics"]))
            vision = next(x for x in metrics["metrics"] if x["metric_id"] == "vision")
            self.assertEqual(vision["status"], "not_tested")
            with Path(result["metric_summary_csv"]).open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), len(metrics["metrics"]))
            self.assertEqual(next(r for r in rows if r["metric_id"] == "vision")["percentage"], "")
            with zipfile.ZipFile(result["xlsx"]) as z:
                self.assertIn("xl/worksheets/sheet6.xml", z.namelist())
            self.assertEqual(package["case_results"][1]["execution_status"], "prerequisite_blocked")


if __name__ == "__main__":
    unittest.main()
