"""Results inside the existing Tk application; no execution or persistence."""
from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from .results import discover_reports, display, load_report, read_evidence
from .results_charts import MetricChart, RoleMatrix


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
    def __init__(self, parent, repo_root, open_output):
        super().__init__(parent, padding=10)
        self.repo_root = Path(repo_root)
        self.open_output = open_output
        self.reports = {}
        self.case_rows = {}
        self.artifact_refs = {}
        self.selected_report = None
        self.selected_row = None
        self.selected_metric = None
        self.rowconfigure(3, weight=1)
        self.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, sticky="ew")
        ttk.Button(toolbar, text="Load reports…", command=self.choose_reports).pack(side="left")
        ttk.Button(toolbar, text="Discover saved reports", command=self.discover).pack(side="left", padx=6)
        self.message = tk.StringVar(value="Load existing reports. Results never starts a model or changes a queue.")
        ttk.Label(self, textvariable=self.message, wraplength=1100).grid(row=1, sticky="ew", pady=5)
        frame, self.report_tree = tree(self, [("path", "Source report (select several to compare)", 600),
            ("cases", "Case rows", 80), ("version", "Metric contract", 240)], height=3)
        frame.grid(row=2, sticky="ew")
        self.report_tree.bind("<<TreeviewSelect>>", lambda e: self.refresh())
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=3, sticky="nsew", pady=6)
        self.views = ttk.Notebook(panes)
        self.capabilities = MetricChart(self.views, self.select_metric)
        self.roles = RoleMatrix(self.views, self.select_metric)
        self.views.add(self.capabilities, text="Capabilities")
        self.views.add(self.roles, text="Role suitability")
        case_frame, self.cases = tree(self.views, [("model", "Model configuration", 180),
            ("case", "Suite / case", 280), ("status", "Outcome / status", 130),
            ("review", "Human review", 100), ("attempt", "Run / trial / attempt", 260)])
        self.views.add(case_frame, text="Cases")
        self.case_frame = case_frame
        self.cases.configure(selectmode="browse")
        self.cases.bind("<<TreeviewSelect>>", self.select_case)
        panes.add(self.views, weight=3)
        details = ttk.LabelFrame(panes, text="Selected result · exact source evidence", padding=6)
        details.rowconfigure(1, weight=1)
        details.columnconfigure(0, weight=1)
        controls = ttk.Frame(details)
        controls.grid(row=0, sticky="ew")
        ttk.Button(controls, text="Run folder", command=self.open_run).pack(side="left")
        ttk.Button(controls, text="Review workbook", command=self.open_workbook).pack(side="left", padx=4)
        ttk.Button(controls, text="Case rows", command=lambda: self.views.select(self.case_frame)).pack(side="left")
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

    def load_paths(self, paths):
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
        keys = self.report_tree.selection() or tuple(self.reports)
        return [self.reports[key] for key in keys]

    def refresh(self):
        reports = self.visible_reports()
        self.selected_metric = None
        self.show_cases([(report, row) for report in reports for row in report.rows.values()])
        series = [(report, metric) for report in reports for metric in report.metrics]
        self.capabilities.render(series)
        self.roles.render(reports, series)

    def select_metric(self, report, metric):
        self.show_cases([(report, row) for row in report.metric_rows(metric)])
        self.selected_report, self.selected_metric = report, metric
        set_text(self.detail, self.metric_detail(report, metric) +
            "\nSelect Case rows to inspect each exact attempt and artifact.\n\n" + json.dumps(metric, indent=2, ensure_ascii=False))

    @staticmethod
    def metric_detail(report, metric):
        return (f"{metric['metric_id']} @ {display(metric.get('metric_version'))}\nSource: {report.path}\n"
                f"Measured outcome: {display(metric.get('suitability') or metric.get('status'))}\n"
                f"Numerator / denominator: {display(metric.get('numerator'))} / {display(metric.get('denominator'))}\n"
                f"Review: {display(metric.get('review_status'))}\n"
                f"Comparison eligible: {display(metric.get('comparison_eligible'))}\n"
                f"Exclusions: {display(metric.get('comparison_exclusion_reasons'))}\n"
                "Counts are distinct cases; attempts and cumulative acceptance checks remain separate.\n")

    def show_cases(self, rows):
        self.cases.delete(*self.cases.get_children())
        self.case_rows.clear()
        self.clear_detail()
        for index, (report, row) in enumerate(rows):
            key = f"case-{index}"
            self.case_rows[key] = (report, row)
            config = row.get("configuration") or {}
            self.cases.insert("", "end", iid=key, values=(display(config.get("model_name")),
                f"{display(row.get('suite_id'))} / {row['case_id']}", display(row.get("normalized_status")),
                display(row.get("human_review_state")),
                " / ".join(display(row.get(k)) for k in ("run_id", "trial_id", "attempt_id"))))

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
        set_text(self.detail, prefix + f"Source: {report.path}\nReport SHA-256: {report.sha256}\n"
                 "Missing fields: Unknown. Assessment and execution are separate.\n\n" + json.dumps(row, indent=2, ensure_ascii=False))
        self.artifacts.delete(*self.artifacts.get_children())
        self.artifact_refs.clear()
        for index, ref in enumerate(row.get("verified_evidence_refs") or row.get("evidence_refs") or []):
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
