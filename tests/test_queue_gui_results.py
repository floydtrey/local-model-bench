"""Actual Tk interactions against deterministic T13 files; no model processes."""
import gc
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from localbench.queue_gui.results import load_report, read_evidence, discover_reports, filter_value
from localbench.queue_gui.core import BenchmarkSettings, save_state
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

    def click_canvas_item(self, chart, item):
        self.app.notebook.select(self.app.results)
        self.app.results.views.select(chart)
        self.root.deiconify()
        self.root.update()
        canvas = chart.canvas
        x0, y0, x1, y1 = canvas.bbox(item)
        bounds = list(map(float, canvas.cget("scrollregion").split()))
        canvas.xview_moveto(max(0, x0 - 20) / bounds[2])
        canvas.yview_moveto(max(0, y0 - 20) / bounds[3])
        self.root.update()
        canvas.event_generate("<Button-1>", x=int((x0 + x1) / 2 - canvas.canvasx(0)),
                              y=int((y0 + y1) / 2 - canvas.canvasy(0)))
        self.root.update()

    def test_r1_measured_bars_select_their_own_report_and_case(self):
        good = ReportFixture(self.repo / "good", "alpha")
        good.case()
        bad = ReportFixture(self.repo / "bad", "beta")
        bad.case(assessed_outcome="FAIL")
        view = self.app.results
        view.load_paths([good.write(), bad.write()])
        bars = view.capabilities.bar_items
        self.assertEqual(len(bars), 2)
        self.assertEqual(sorted(view.capabilities.targets[b][1]["percentage"] for b in bars), [0, 100])
        item = next(b for b in bars if view.capabilities.targets[b][1]["percentage"] == 100)
        self.click_canvas_item(view.capabilities, item)
        self.assertEqual(view.selected_metric["numerator"], 1)
        self.assertEqual(len(view.case_rows), 1)
        report, row = next(iter(view.case_rows.values()))
        self.assertEqual(row["configuration"]["model_name"], "alpha")
        self.assertEqual(report.run_dir.name, "good")
        self.assertIn("1 / 1", view.detail.get("1.0", "end"))
        self.assertEqual(self.runner.started, [])

    def test_r1_untested_categories_have_labels_without_bars(self):
        fixture = ReportFixture(self.repo / "run")
        fixture.case()
        view = self.app.results
        view.load_paths([fixture.write()])
        self.assertEqual({view.capabilities.targets[b][1]["metric_id"] for b in view.capabilities.bar_items}, {"coding"})
        labels = [view.capabilities.canvas.itemcget(i, "text") for i in view.capabilities.canvas.find_all()
                  if view.capabilities.canvas.type(i) == "text"]
        self.assertIn("Vision", labels)
        self.assertIn("Long context recall", labels)
        self.assertIn("Not tested", labels)

    def test_r1_role_cell_keeps_provisional_criteria_and_critical_conditions(self):
        fixture = ReportFixture(self.repo / "role-run")
        fixture.case("assistant-001-planner-v2-complete", metric="role_planner", role="planner",
                     human_review_required=True, human_review_status="pending")
        view = self.app.results
        view.load_paths([fixture.write()])
        item = next(i for i, (_, m) in view.roles.targets.items() if m["metric_id"] == "role_planner")
        self.click_canvas_item(view.roles, item)
        self.assertEqual(view.selected_metric["suitability"], "provisional_review_pending")
        detail = view.detail.get("1.0", "end")
        self.assertIn("role-suitability:v1", detail)
        self.assertIn("critical_safety_gates", detail)
        self.assertIn("Unsafe scope expansion", detail)

    def test_r2_repair_attempts_preserve_denominator_and_exact_artifact(self):
        fixture = ReportFixture(self.repo / "repair")
        first = fixture.case(assessed_outcome="FAIL", attempt_id="first")
        repair = fixture.case(attempt_index=2, parent_attempt_id="first", attempt_id="repair")
        view = self.app.results
        view.load_paths([fixture.write()])
        item = view.capabilities.bar_items[0]
        self.click_canvas_item(view.capabilities, item)
        metric = view.selected_metric
        self.assertEqual((metric["numerator"], metric["denominator"], metric["attempt_count"]), (1, 1, 2))
        self.assertEqual(metric["first_pass"], {"numerator": 0, "denominator": 1})
        self.assertEqual(metric["after_repair"], {"numerator": 1, "denominator": 1})
        for key, (report, row) in view.case_rows.items():
            view.cases.selection_set(key)
            view.cases.event_generate("<<TreeviewSelect>>")
            self.root.update()
            self.assertEqual(view.selected_row["attempt_id"], row["attempt_id"])
            ref = next(iter(view.artifact_refs.values()))
            evidence = read_evidence(report, row, ref)
            expected = first if row["attempt_id"] == "first" else repair
            self.assertEqual(evidence[0], Path(expected["assessment_file"]).resolve())
            self.assertIn(expected["assessed_outcome"], evidence[3])

    def test_r2_review_filter_never_recalculates_partial_population(self):
        fixture = ReportFixture(self.repo / "mixed-review")
        fixture.case("contradiction-detection", metric="reasoning")
        fixture.case("dependency-plan", metric="reasoning", human_review_required=True, human_review_status="pending")
        view = self.app.results
        view.load_paths([fixture.write()])
        view.filter_vars["review"].set("not_required")
        view.filter_widgets["review"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(len(view.case_rows), 1)
        self.assertFalse(any(m["metric_id"] == "reasoning" for _, m in view.capabilities.targets.values()))
        self.assertEqual(view.capabilities.bar_items, [])
        view.reset_filters()
        self.assertEqual(len(view.case_rows), 2)

    def test_r2_all_seven_filters_select_exact_case_population(self):
        left = ReportFixture(self.repo / "left", "alpha")
        left.case(role="worker", worker_mode="ISOLATED_TASK")
        right = ReportFixture(self.repo / "right", "beta")
        right.case(role="tester", track="different-track", runtime_identity={"name": "other", "version": "2", "transport": "fake"},
                   human_review_required=True, human_review_status="pending")
        view = self.app.results
        view.load_paths([left.write(), right.write()])
        report = next(report for report in view.reports.values() if report.run_dir.name == "left")
        row = report.rows["row-1"]
        for key in view.filter_vars:
            view.filter_vars[key].set(filter_value(row, key))
            view.filter_widgets[key].event_generate("<<ComboboxSelected>>")
            self.root.update()
        self.assertEqual(len(view.case_rows), 1)
        self.assertEqual(next(iter(view.case_rows.values()))[0].run_dir.name, "left")
        self.assertEqual(len(view.capabilities.bar_items), 1)

    def test_r2_comparison_exclusions_use_t13_protocol_and_exact_sides(self):
        paths = []
        for name, mode in (("a", "ISOLATED_TASK"), ("b", "CUMULATIVE_PROJECT")):
            fixture = ReportFixture(self.repo / name, name)
            fixture.case(role="worker", worker_mode=mode)
            paths.append(fixture.write())
        view = self.app.results
        view.load_paths(paths)
        key = next(iter(view.comparison_targets))
        left, right, comparison = view.comparison_targets[key]
        self.assertFalse(comparison["eligible"])
        self.assertIn("different_worker_mode", comparison["exclusion_reasons"])
        view.comparisons.selection_set(key)
        view.comparisons.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertIn("Combined score: none", view.detail.get("1.0", "end"))
        view.comparison_side(1)
        self.assertEqual(view.selected_report.path, right[0].path)
        self.assertEqual(view.selected_metric["protocol"]["worker_mode"], right[1]["protocol"]["worker_mode"])

    def test_r2_assistant_measures_only_qualified_coverage(self):
        fixture = ReportFixture(self.repo / "assistant")
        fixture.case("authority-boundary", metric="permission_boundaries")
        fixture.case("minimal-code-repair", metric="coding", source_index=1)
        view = self.app.results
        view.load_paths([fixture.write()])
        self.assertEqual({view.assistant.targets[i][1]["metric_id"] for i in view.assistant.bar_items}, {"permission_boundaries"})
        recovery = next(m for r in view.reports.values() for m in r.metrics if m["metric_id"] == "error_recovery")
        self.assertIsNone(recovery["percentage"])
        self.assertIsNone(recovery["denominator"])
        self.click_canvas_item(view.assistant, view.assistant.bar_items[0])
        self.assertEqual(view.selected_metric["metric_id"], "permission_boundaries")

    def test_r2_correct_tester_fail_and_blocked_worker_remain_distinct(self):
        fixture = ReportFixture(self.repo / "roles")
        fixture.case("assistant-001-tester-02", metric="role_tester", role="tester", candidate_decision="FAIL",
            implementation_truth="defective", human_review_required=True, human_review_status="recorded")
        fixture.case("assistant001-t02", metric="role_worker", role="worker", worker_mode="CUMULATIVE_PROJECT",
            execution_status="prerequisite_blocked", assessed_outcome=None)
        view = self.app.results
        view.load_paths([fixture.write()])
        statuses = {row["case_id"]: row["normalized_status"] for _, row in view.case_rows.values()}
        self.assertEqual(statuses["assistant-001-tester-02"], "passed")
        self.assertEqual(statuses["assistant001-t02"], "blocked")
        worker = next(m for r in view.reports.values() for m in r.metrics if m["metric_id"] == "role_worker")
        self.assertIsNone(worker["denominator"])
        self.assertEqual(worker["attempt_count"], 0)
        self.assertEqual(worker["failed_cases"], [])

    def test_r3_queue_to_result_and_back_preserves_saved_state(self):
        fixture = ReportFixture(self.repo / "local-state" / "saved-run")
        fixture.case()
        fixture.write()
        item = self.app.queue.add_models(["fixture-model"], BenchmarkSettings(governor_root=str(self.governor)))[0]
        item.run_dir = "local-state/saved-run"
        self.app.queue.start()
        self.app.queue.start_next()
        self.app.queue.finish(item.id, 0)
        self.app._save()
        self.app._render()
        before = self.state_path.read_bytes()
        self.app.queue_tree.selection_set(item.id)
        self.app.view_selected_results()
        self.root.update()
        view = self.app.results
        view.cases.selection_set(view.cases.get_children()[0])
        view.cases.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertIn(item.id, view.detail.get("1.0", "end"))
        view.reveal_queue()
        self.assertEqual(self.app.notebook.select(), str(self.app.queue_tab))
        self.assertEqual(self.app.queue_tree.selection(), (item.id,))
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.runner.started, [])

    def test_r3_recovered_queue_results_never_retry_interrupted_run(self):
        fixture = ReportFixture(self.repo / "saved-run")
        fixture.case()
        fixture.write()
        self.app.request_close()
        state = self.app.queue
        item = state.add_models(["fixture-model"], BenchmarkSettings(governor_root=str(self.governor)))[0]
        state.start()
        state.start_next()
        item.run_dir = str(fixture.root)
        save_state(self.state_path, state)
        before = self.state_path.read_bytes()
        self._create_app()
        self.app.results.load_queue_reports()
        self.root.update()
        self.assertEqual(self.app.queue.items[0].status, "Interrupted")
        self.assertEqual(len(self.app.results.case_rows), 1)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.runner.started, [])

    def test_r3_similar_run_names_and_missing_reports_do_not_link(self):
        fixture = ReportFixture(self.repo / "run")
        fixture.case()
        path = fixture.write()
        item = self.app.queue.add_models(["fixture-model"], BenchmarkSettings(governor_root=str(self.governor)))[0]
        item.run_dir = "run-other"
        view = self.app.results
        view.load_paths([path])
        view.select_metric(*view.capabilities.targets[view.capabilities.bar_items[0]])
        view.reveal_queue()
        self.assertIn("No exact run-directory match", view.message.get())
        view.load_run(self.repo / "missing-run")
        self.root.update()
        self.assertEqual(len(view.case_rows), 0)
        self.assertIsNone(view.selected_report)
        self.assertIn("No supported reports", view.message.get())

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
