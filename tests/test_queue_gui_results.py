"""Actual Tk interactions against deterministic T13 files; no model processes."""
import gc
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from localbench.queue_gui.results import load_report, read_evidence, discover_reports
from results_fixtures import ReportFixture
from test_queue_gui_app import QueueGuiWidgetTests as _QueueTests


class ResultsReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_writer_values_and_original_files_are_preserved(self):
        fixture = ReportFixture(self.root / "run")
        fixture.case()
        path = fixture.write()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = load_report(path)
        original = json.loads(path.read_text())["qualification_v2_metrics"]
        self.assertEqual(report.metrics, original["metrics"])
        self.assertEqual(list(report.rows.values()), original["case_details"])
        self.assertEqual(report.workbook, path.with_suffix(".xlsx").resolve())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_corrupt_exact_binding_rejected(self):
        fixture = ReportFixture(self.root / "run")
        fixture.case()
        path = fixture.write()
        raw = json.loads(path.read_text())
        metric = next(m for m in raw["qualification_v2_metrics"]["metrics"] if m["case_refs"])
        metric["case_refs"][0]["attempt_id"] = "another-attempt"
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            load_report(path)

    def test_unknown_version_rejected(self):
        path = self.root / "review-package.json"
        path.write_text(json.dumps({"qualification_v2_metrics": {"schema_version": "future:99"}}))
        with self.assertRaisesRegex(ValueError, "Unsupported metric"):
            load_report(path)

    def test_legacy_exit_zero_never_becomes_qualification(self):
        path = self.root / "review-package.json"
        path.write_text(json.dumps({"schema_version": "flashnext-role-review-package:v1", "metadata": {},
            "case_results": [{"case_id": "legacy", "status": "success", "exit_code": 0}]}))
        report = load_report(path)
        self.assertEqual(report.metrics, [])
        row = report.rows["legacy-1"]
        self.assertEqual(row["normalized_status"], "unknown")
        self.assertIsNone(row["configuration"]["model_name"])

    def test_artifact_tampering_and_missing_file_never_fall_back_by_name(self):
        fixture = ReportFixture(self.root / "run")
        fixture.case()
        report = load_report(fixture.write())
        row = report.rows["row-1"]
        ref = row["verified_evidence_refs"][0]
        path = Path(ref["resolved_path"])
        self.assertEqual(read_evidence(report, row, ref)[1], "verified")
        path.write_text("changed")
        self.assertEqual(read_evidence(report, row, ref)[1], "stale")
        path.unlink()
        (path.parent / "similar-assessment-1.json").write_text("different case")
        with self.assertRaises(FileNotFoundError):
            read_evidence(report, row, ref)


class ResultsWidgetTests(unittest.TestCase):
    # Reuse the existing real-Tk fixture lifecycle without inheriting its tests.
    setUpClass = classmethod(_QueueTests.setUpClass.__func__)
    setUp = _QueueTests.setUp
    tearDown = _QueueTests.tearDown
    _create_app = _QueueTests._create_app
    _discover = _QueueTests._discover

    def test_r0_cases_exact_evidence_and_workbook_in_existing_app(self):
        fixture = ReportFixture(self.repo / "local-state" / "synthetic-run")
        fixture.case()
        path = fixture.write()
        self.app.results.discover()
        self.app.notebook.select(self.app.results)
        self.root.deiconify()
        self.root.update()
        view = self.app.results
        key = view.cases.get_children()[0]
        view.cases.selection_set(key)
        view.cases.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertEqual(view.selected_row["case_id"], "code-diagnosis")
        self.assertIn("attempt-1", view.detail.get("1.0", "end"))
        artifact = view.artifacts.get_children()[0]
        view.artifacts.selection_set(artifact)
        preview = view.preview_artifact()
        self.assertIn("Current integrity: verified", preview.winfo_children()[0].get("1.0", "end"))
        preview.destroy()
        with patch.object(view, "open_output") as opened:
            view.open_workbook()
            opened.assert_called_once_with(path.with_suffix(".xlsx").resolve(), True)
        self.assertEqual(self.runner.started, [])

    def test_r0_legacy_unknowns_and_missing_report_message(self):
        path = self.repo / "legacy.json"
        path.write_text(json.dumps({"schema_version": "flashnext-role-review-package:v1", "case_results": [
            {"case_id": "unknown", "status": "success"}]}))
        view = self.app.results
        view.load_paths([path, self.repo / "missing.json"])
        values = view.cases.item(view.cases.get_children()[0], "values")
        self.assertEqual(values[0], "Unknown")
        self.assertEqual(values[2], "unknown")
        self.assertIn("missing.json", view.message.get())
        self.assertEqual(self.runner.started, [])


# Avoid unittest treating the imported fixture class as another test suite.
del _QueueTests
