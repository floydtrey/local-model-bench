"""Canvas views of published T13 values. No scoring or population aggregation."""
import hashlib
import tkinter as tk
from tkinter import ttk

from .results import display

CAPABILITIES = ("reasoning", "coding", "vision", "tool_use", "instruction_following", "long_context_recall")
ASSISTANT = ("multi_step_tasks", "tool_selection", "error_recovery", "permission_boundaries", "evidence_accuracy")
ROLES = ("planner", "governor", "worker", "tester", "reviewer")


def label(value):
    return display(value).replace("_", " ").capitalize()


def configuration_label(config):
    config = config or {}
    return (f"{display(config.get('model_name'))} · {display(config.get('quantization'))} · "
            f"{display(config.get('context_tokens'))} ctx · {display(config.get('runtime'))}")


class ScrollCanvas(ttk.Frame):
    def __init__(self, parent, select):
        super().__init__(parent)
        self.select = select
        self.targets = {}
        self.bar_items = []
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background="#fafbfd", highlightthickness=0, width=640, height=300)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def click(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            if item in self.targets:
                self.select(*self.targets[item])
                break

    def reset(self):
        self.canvas.delete("all")
        self.targets.clear()
        self.bar_items.clear()

    def text(self, x, y, text, *, target=None, **kwargs):
        item = self.canvas.create_text(x, y, text=text, anchor="nw", fill="#203145", **kwargs)
        if target:
            self.targets[item] = target
        return item


class MetricChart(ScrollCanvas):
    def __init__(self, parent, select, categories=CAPABILITIES):
        super().__init__(parent, select)
        self.categories = categories

    def render(self, series, *, filtered=False):
        self.reset()
        y = 14
        for category in self.categories:
            self.text(14, y, label(category), font=("Segoe UI", 12, "bold"))
            y += 29
            members = [(report, metric) for report, metric in series if metric["metric_id"] == category]
            if not members:
                self.text(28, y, "No complete population matches filters" if filtered else
                          "Not tested · no qualifying versioned measurements in this selection")
                y += 36
                continue
            # Each exported population stays a separate row, including repeats
            # across reports. Sorting is presentation only, never aggregation.
            members.sort(key=lambda pair: (display(pair[1].get("suite_id")), display(pair[1].get("rubric_id")),
                display(pair[1].get("comparison_group")), configuration_label(pair[1].get("configuration")), str(pair[0].path)))
            for report, metric in members:
                target = (report, metric)
                config = metric.get("configuration")
                measured = metric.get("status") == "measured" and metric.get("percentage") is not None
                self.text(28, y, configuration_label(config) if config else "No measured configuration", target=target, width=320)
                state = label(metric.get("status"))
                if measured:
                    value = metric["percentage"]
                    color = ("#176b9c", "#8f538c", "#177a67", "#ad6525")[int(hashlib.sha256(display(config).encode()).hexdigest()[:4], 16) % 4]
                    track = self.canvas.create_rectangle(370, y + 2, 670, y + 20, fill="#e4eaf1", outline="")
                    bar = self.canvas.create_rectangle(370, y + 2, 370 + 3 * value, y + 20, fill=color, outline="")
                    self.targets[track] = self.targets[bar] = target
                    self.bar_items.append(bar)
                    state = f"{value:g}% · {metric['numerator']}/{metric['denominator']} scored cases"
                self.text(688, y, state, target=target, width=310)
                first, repair = metric.get("first_pass"), metric.get("after_repair")
                fraction = lambda v: f"{v['numerator']}/{v['denominator']}" if v else "Unknown"
                self.text(370, y + 25, f"First pass: {fraction(first)} · Repaired: {fraction(repair)} · Distinct: {display(metric.get('distinct_cases'))}", target=target)
                self.text(28, y + 50, f"{display(metric.get('suite_id'))} @ {display(metric.get('suite_version'))} · "
                    f"{display(metric.get('rubric_id'))} @ {display(metric.get('rubric_version'))}", target=target, width=960)
                eligible = "Eligible within matching protocol" if metric.get("comparison_eligible") else "Comparison excluded: " + ", ".join(metric.get("comparison_exclusion_reasons", []))
                self.text(28, y + 70, f"Review: {display(metric.get('review_status'))} · {eligible}", target=target, width=960)
                y += 113
            y += 12
        self.canvas.configure(scrollregion=(0, 0, 1020, y))


class RoleMatrix(ScrollCanvas):
    def render(self, reports, series):
        self.reset()
        self.text(14, 12, "Versioned role criteria · advisory evidence only · no automatic role assignment", font=("Segoe UI", 11, "bold"))
        for index, role in enumerate(ROLES):
            self.text(270 + index * 190, 45, role.title(), font=("Segoe UI", 11, "bold"))
        groups = {}
        for report, metric in series:
            if metric["kind"] != "role_suitability" or metric.get("configuration") is None:
                continue
            key = (str(report.path), metric["configuration_id"])
            groups.setdefault(key, (report, metric["configuration"], {}))[2].setdefault(metric["metric_id"], []).append(metric)
        y = 78
        if not groups:
            self.text(14, y, "Not assessed · no qualifying role measurements in the selected reports")
            y += 50
        for report, config, metrics in groups.values():
            height = max(len(values) for values in metrics.values()) * 132
            self.text(14, y, configuration_label(config) + "\n" + report.run_dir.name, width=235)
            for index, role in enumerate(ROLES):
                x = 270 + index * 190
                items = metrics.get("role_" + role, [])
                if not items:
                    self.text(x + 6, y + 8, "Not assessed", width=175)
                for offset, metric in enumerate(items):
                    top = y + offset * 132
                    target = (report, metric)
                    status = metric.get("suitability")
                    color = "#f9e1dd" if status == "criteria_not_met" else "#fff0cc" if status and status.startswith("provisional") else "#e3eaf1"
                    item = self.canvas.create_rectangle(x, top, x + 183, top + 125, fill=color, outline="#c5cfdb")
                    self.targets[item] = target
                    self.text(x + 6, top + 5, f"{label(status)}\nCoverage: {display(metric.get('denominator'))}/{display(metric.get('coverage_required'))}\n"
                        f"Review: {display(metric.get('review_status'))}\n{display((metric.get('criteria') or {}).get('version'))}", target=target, width=172)
            y += height + 14
        self.canvas.configure(scrollregion=(0, 0, 1230, y))
