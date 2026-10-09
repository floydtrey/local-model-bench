"""Results inside the existing Tk application; no execution or persistence."""
from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from .results import (FILTERS, case_evidence_refs, compare_reports, discover_reports, display, filter_value,
                      load_report, metric_matches, queue_matches, queue_run_path, read_evidence, row_matches)
from .results_charts import ASSISTANT, MetricChart, RoleMatrix, configuration_label


def tree(parent, columns, *, height=8):
    frame = ttk.Frame(parent)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    widget = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
    for key, label, width in columns:
        widget.heading(key, text=label)
        widget.column(key, width=width, minwidth=55)
    widget.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=widget.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    widget.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    return frame, widget


def set_text(widget, value):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")


class ResultsView(ttk.Frame):
    def __init__(self, parent, repo_root, open_output, queue_items=lambda: (), show_queue=None):
        super().__init__(parent, padding=10)
        self.repo_root = Path(repo_root)
        self.open_output = open_output
        self.queue_items = queue_items
        self.show_queue = show_queue
        self.reports = {}
        self.case_rows = {}
        self.artifact_refs = {}
        self.selected_report = None
        self.selected_row = None
        self.selected_metric = None
        self.empty_run = False
        self.rowconfigure(4, weight=1)
        self.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, sticky="ew")
        ttk.Button(toolbar, text="Load reports…", command=self.choose_reports).pack(side="left")
        ttk.Button(toolbar, text="Discover saved reports", command=self.discover).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Load saved queue reports", command=self.load_queue_reports).pack(side="left")
        self.message = tk.StringVar(value="Load existing reports. Results never starts a model or changes a queue.")
        ttk.Label(self, textvariable=self.message, wraplength=1100).grid(row=1, sticky="ew", pady=5)
        frame, self.report_tree = tree(self, [("path", "Source report (select several to compare)", 600),
            ("cases", "Case rows", 80), ("version", "Metric contract", 240)], height=3)
        frame.grid(row=2, sticky="ew")
        self.report_tree.bind("<<TreeviewSelect>>", lambda e: self.refresh())
        filters = ttk.LabelFrame(self, text="Filters select whole published metric populations; case rows filter independently", padding=5)
        filters.grid(row=3, sticky="ew", pady=5)
        self.filter_vars, self.filter_widgets = {}, {}
        for index, (key, title) in enumerate(FILTERS):
            column, row = (index % 4) * 2, (index // 4) * 2
            ttk.Label(filters, text=title).grid(row=row, column=column, sticky="w")
            variable = tk.StringVar(value="All")
            widget = ttk.Combobox(filters, textvariable=variable, state="readonly", width=27)
            widget.grid(row=row + 1, column=column, sticky="ew", padx=(0, 8))
            widget.bind("<<ComboboxSelected>>", lambda e: self.refresh())
            filters.columnconfigure(column, weight=1)
            self.filter_vars[key], self.filter_widgets[key] = variable, widget
        ttk.Button(filters, text="Reset filters", command=self.reset_filters).grid(row=3, column=6, sticky="w")
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=4, sticky="nsew", pady=6)
        self.views = ttk.Notebook(panes, width=700)
        self.capabilities = MetricChart(self.views, self.select_metric)
        self.roles = RoleMatrix(self.views, self.select_metric)
        self.assistant = MetricChart(self.views, self.select_metric, ASSISTANT)
        self.views.add(self.capabilities, text="Capabilities")
        self.views.add(self.roles, text="Role suitability")
        self.views.add(self.assistant, text="Assistant")
        case_frame, self.cases = tree(self.views, [("model", "Model configuration", 180),
            ("case", "Suite / case", 280), ("status", "Outcome / status", 130),
            ("review", "Human review", 100), ("attempt", "Run / trial / attempt", 260),
            ("membership", "Selected metric membership", 220)])
        self.views.add(case_frame, text="Cases")
        self.case_frame = case_frame
        self.cases.configure(selectmode="browse")
        self.cases.bind("<<TreeviewSelect>>", self.select_case)
        comparisons = ttk.Frame(self.views)
        comparisons.rowconfigure(0, weight=1)
        comparisons.columnconfigure(0, weight=1)
        cf, self.comparisons = tree(comparisons, [("metric", "Metric", 130), ("left", "Left configuration / run", 240),
            ("right", "Right configuration / run", 240), ("eligible", "Comparable", 85), ("reasons", "Exclusions", 350)])
        cf.grid(row=0, sticky="nsew")
        self.comparisons.configure(selectmode="browse")
        self.comparisons.bind("<<TreeviewSelect>>", self.select_comparison)
        cb = ttk.Frame(comparisons)
        cb.grid(row=1, sticky="w")
        ttk.Button(cb, text="Inspect left result", command=lambda: self.comparison_side(0)).pack(side="left")
        ttk.Button(cb, text="Inspect right result", command=lambda: self.comparison_side(1)).pack(side="left", padx=5)
        self.views.add(comparisons, text="Comparisons")
        self.comparison_targets = {}
        panes.add(self.views, weight=3)
        details = ttk.LabelFrame(panes, text="Selected result · exact source evidence", padding=6)
        details.rowconfigure(1, weight=1)
        details.columnconfigure(0, weight=1)
        controls = ttk.Frame(details)
        controls.grid(row=0, sticky="ew")
        ttk.Button(controls, text="Run folder", command=self.open_run).grid(row=0, column=0, sticky="ew")
        ttk.Button(controls, text="Review workbook", command=self.open_workbook).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(controls, text="Case rows", command=lambda: self.views.select(self.case_frame)).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(controls, text="Queue entry", command=self.reveal_queue).grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        self.detail = tk.Text(details, wrap="word", state="disabled", width=48, height=14)
        self.detail.grid(row=1, sticky="nsew")
        scroll = ttk.Scrollbar(details, command=self.detail.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=scroll.set)
        artifacts, self.artifacts = tree(details, [("kind", "Evidence", 110),
            ("path", "Exact artifact path", 240), ("integrity", "At report time", 100)], height=4)
        artifacts.grid(row=2, sticky="ew")
        self.artifacts.configure(selectmode="browse")
        self.artifacts.bind("<Double-1>", lambda e: self.preview_artifact())
        ttk.Button(details, text="Inspect selected artifact (read only)", command=self.preview_artifact).grid(row=3, sticky="w", pady=4)
        panes.add(details, weight=2)

    def choose_reports(self):
        paths = filedialog.askopenfilenames(parent=self, title="Existing Benchmark Lab reports",
            filetypes=[("Benchmark reports", "*.json *.csv")])
        self.load_paths(paths)

    def discover(self):
        self.load_paths(discover_reports([self.repo_root / "local-state", self.repo_root / "results"]))

    def load_queue_reports(self):
        roots = [queue_run_path(self.repo_root, item) for item in self.queue_items() if item.run_dir]
        self.load_paths(discover_reports(roots))

    def load_run(self, run_dir):
        paths = discover_reports([run_dir])
        self.load_paths(paths)
        keys = [str(path) for path in paths if str(path) in self.reports]
        self.report_tree.selection_set(keys)
        self.empty_run = not keys
        if not keys:
            self.clear_detail()
            self.message.set(f"No supported reports found for {run_dir}. No benchmark was started.")
        self.refresh()

    def queue_detail(self, report):
        matches = queue_matches(report, self.queue_items(), self.repo_root)
        return "Saved queue identities: " + (", ".join(f"{item.id} ({item.status})" for item in matches)
            if matches else "No exact run-directory match") + "\n"

    def reveal_queue(self):
        if not self.selected_report:
            return
        matches = queue_matches(self.selected_report, self.queue_items(), self.repo_root)
        if len(matches) != 1:
            self.message.set("Queue link unavailable or ambiguous: " + self.queue_detail(self.selected_report))
        elif self.show_queue:
            self.show_queue(matches[0].id)

    def load_paths(self, paths):
        self.empty_run = False
        errors = []
        for path in paths:
            try:
                report = load_report(path)
                self.reports[str(report.path)] = report
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{path}: {exc}")
        self.report_tree.delete(*self.report_tree.get_children())
        for key, report in self.reports.items():
            self.report_tree.insert("", "end", iid=key, values=(key, len(report.rows),
                report.projection["schema_version"] if report.projection else "Legacy · metrics unavailable"))
        self.message.set("\n".join(errors) if errors else f"{len(self.reports)} source reports loaded read only. Saved metrics are never combined or rescored.")
        self.refresh()

    def visible_reports(self):
        if self.report_tree.selection():
            self.empty_run = False
        if self.empty_run:
            return []
        keys = self.report_tree.selection() or tuple(self.reports)
        return [self.reports[key] for key in keys]

    def refresh(self):
        reports = self.visible_reports()
        for key, _ in FILTERS:
            choices = ["All"] + sorted({filter_value(row, key) for report in reports for row in report.rows.values()})
            if self.filter_vars[key].get() not in choices:
                choices.append(self.filter_vars[key].get())
            self.filter_widgets[key].configure(values=choices)
        filters = {key: var.get() for key, var in self.filter_vars.items()}
        filtered = any(value != "All" for value in filters.values())
        self.selected_metric = None
        self.show_cases([(report, row) for report in reports for row in report.rows.values() if row_matches(row, filters)])
        series = [(report, metric) for report in reports for metric in report.metrics if metric_matches(report, metric, filters)]
        self.capabilities.render(series, filtered=filtered)
        self.roles.render(reports, series)
        self.assistant.render(series, filtered=filtered)
        self.comparisons.delete(*self.comparisons.get_children())
        self.comparison_targets.clear()
        # Empty, unmeasured placeholders do not constitute a comparison pair.
        series = [(report, metric) for report, metric in series if metric.get("case_refs")]
        for index, comparison in enumerate(compare_reports(series)):
            left, right = series[comparison["left_series"] - 1], series[comparison["right_series"] - 1]
            key = f"comparison-{index}"
            self.comparison_targets[key] = (left, right, comparison)
            self.comparisons.insert("", "end", iid=key, values=(comparison["metric_id"],
                configuration_label(left[1].get("configuration")) + " / " + left[0].run_dir.name,
                configuration_label(right[1].get("configuration")) + " / " + right[0].run_dir.name,
                comparison["eligible"], ", ".join(comparison["exclusion_reasons"])))

    def reset_filters(self):
        for var in self.filter_vars.values():
            var.set("All")
        self.refresh()

    def select_comparison(self, _event=None):
        selection = self.comparisons.selection()
        if not selection or selection[0] not in self.comparison_targets:
            return
        left, right, comparison = self.comparison_targets[selection[0]]
        self.clear_detail()
        self.selected_metric = None
        set_text(self.detail, f"Comparison: {comparison['metric_id']}\nEligible: {comparison['eligible']}\n"
            f"Exclusions: {display(comparison['exclusion_reasons'])}\nCombined score: none\n\n"
            + "LEFT\n" + self.metric_detail(*left) + "\nRIGHT\n" + self.metric_detail(*right))

    def comparison_side(self, side):
        selection = self.comparisons.selection()
        if selection and selection[0] in self.comparison_targets:
            self.select_metric(*self.comparison_targets[selection[0]][side])
            self.views.select(self.case_frame)

    def select_metric(self, report, metric):
        self.show_cases([(report, row) for row in report.metric_rows(metric)], metric)
        self.selected_report, self.selected_metric = report, metric
        set_text(self.detail, self.queue_detail(report) + self.metric_detail(report, metric) +
            "\nSelect Case rows to inspect each exact attempt and artifact.\n\n" + json.dumps(metric, indent=2, ensure_ascii=False))

    @staticmethod
    def metric_detail(report, metric):
        return (f"{metric['metric_id']} @ {display(metric.get('metric_version'))}\n"
                f"Model: {configuration_label(metric.get('configuration'))}\n"
                f"Configuration ID: {display(metric.get('configuration_id'))}\n"
                f"Measured outcome: {display(metric.get('suitability') or metric.get('status'))}\n"
                f"Numerator / denominator: {display(metric.get('numerator'))} / {display(metric.get('denominator'))}\n"
                f"Distinct cases: {display(metric.get('distinct_cases'))} · Attempts: {display(metric.get('attempt_count'))}\n"
                f"Suite: {display(metric.get('suite_id'))} @ {display(metric.get('suite_version'))}\n"
                f"Rubric: {display(metric.get('rubric_id'))} @ {display(metric.get('rubric_version'))}\n"
                f"Review: {display(metric.get('review_status'))}\n"
                f"First pass: {display(metric.get('first_pass'))}\nAfter repair: {display(metric.get('after_repair'))}\n"
                f"Failed cases: {display(metric.get('final_failed_cases'))}\nBlocked cases: {display(metric.get('blocked_cases'))}\n"
                f"Comparison eligible: {display(metric.get('comparison_eligible'))}\n"
                f"Exclusions: {display(metric.get('comparison_exclusion_reasons'))}\n"
                f"Definition: {display(metric.get('definition'))}\nSource: {report.path}\n"
                "Counts are distinct cases; attempts and cumulative acceptance checks remain separate.\n")

    def show_cases(self, rows, metric=None):
        self.cases.delete(*self.cases.get_children())
        self.case_rows.clear()
        self.clear_detail()
        for index, (report, row) in enumerate(rows):
            key = f"case-{index}"
            self.case_rows[key] = (report, row)
            config = row.get("configuration") or {}
            member = "Source report row"
            if metric:
                refs = [ref for ref in metric["case_refs"] if ref["row_id"] == row["row_id"]]
                member = "Included" if refs and refs[0]["included"] else "Excluded · see reasons in result"
            model = configuration_label(config) if config.get("model_name") else display(row.get("candidate_name"))
            self.cases.insert("", "end", iid=key, values=(model,
                f"{display(row.get('suite_id'))} / {row['case_id']}", display(row.get("normalized_status")),
                display(row.get("human_review_state")),
                " / ".join(display(row.get(k)) for k in ("run_id", "trial_id", "attempt_id")), member))

    def clear_detail(self):
        self.selected_report = self.selected_row = None
        self.artifacts.delete(*self.artifacts.get_children())
        self.artifact_refs.clear()
        set_text(self.detail, "Select a case to inspect its recorded outcome and exact evidence. Unknown fields remain unknown.")

    def select_case(self, _event=None):
        selection = self.cases.selection()
        if not selection or selection[0] not in self.case_rows:
            return
        report, row = self.case_rows[selection[0]]
        self.selected_report, self.selected_row = report, row
        prefix = self.metric_detail(report, self.selected_metric) if self.selected_metric else ""
        if self.selected_metric:
            refs = [ref for ref in self.selected_metric["case_refs"] if ref["row_id"] == row["row_id"]]
            excluded = [ref for ref in self.selected_metric.get("excluded", []) if row["row_id"] in ref.get("row_ids", [])]
            prefix += "Selected metric membership: " + display(refs or excluded) + "\n"
        set_text(self.detail, self.queue_detail(report) + prefix + f"Source: {report.path}\nReport SHA-256: {report.sha256}\n"
                 f"Human review: {display(row.get('human_review_state'))}\n"
                 f"Technical/reference review: {display(row.get('technical_review_status') or row.get('reference_review_status'))}\n"
                 f"First pass: {display(row.get('first_pass_passed'))}\nRepair attempted: {display(row.get('repair_attempted'))}\n"
                 f"Repair passed: {display(row.get('repair_passed'))}\n"
                 "Missing fields: Unknown. Assessment and execution are separate.\n\n" + json.dumps(row, indent=2, ensure_ascii=False))
        self.artifacts.delete(*self.artifacts.get_children())
        self.artifact_refs.clear()
        for index, ref in enumerate(case_evidence_refs(row)):
            key = f"artifact-{index}"
            self.artifact_refs[key] = ref
            self.artifacts.insert("", "end", iid=key, values=(display(ref.get("kind")),
                display(ref.get("resolved_path") or ref.get("path")), display(ref.get("integrity"))))

    def preview_artifact(self):
        selection = self.artifacts.selection()
        if not self.selected_row or not selection:
            self.message.set("Select an exact case artifact first.")
            return
        try:
            path, integrity, digest, content = read_evidence(self.selected_report, self.selected_row,
                self.artifact_refs[selection[0]])
        except (OSError, ValueError) as exc:
            self.message.set(f"Evidence unavailable: {exc}. No substitute file was selected.")
            return
        window = tk.Toplevel(self)
        window.title(f"Evidence · {path.name}")
        window.geometry("900x650")
        viewer = tk.Text(window, wrap="word")
        viewer.pack(fill="both", expand=True)
        set_text(viewer, f"{path}\nCurrent integrity: {integrity}\nObserved SHA-256: {digest}\n\n{content}")
        return window

    def open_run(self):
        if self.selected_report:
            self.open_output(self.selected_report.run_dir, False)

    def open_workbook(self):
        if self.selected_report:
            self.open_output(self.selected_report.workbook, True)
