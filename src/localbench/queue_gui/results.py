"""Read-only report navigation. The T13 writer owns all scores and populations."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from ..v2.metric_projection import (
    REPORT_VERSION, SOURCE_FIELDS, case_status, configuration_identity,
    human_review_state, compare_series,
)
from ..v2.report_adapter import normalize_legacy_report, normalize_rows


def display(value):
    """Missing facts are never replaced with zero or a successful outcome."""
    if value is None or value == "":
        return "Unknown"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


FILTERS = (("suite", "Benchmark suite"), ("role", "Role"), ("track", "Evaluation track"),
           ("worker_mode", "Worker mode"), ("configuration", "Model configuration"),
           ("runtime", "Runtime"), ("review", "Human review status"))


def filter_value(row, key):
    config = row.get("configuration") or {}
    if key == "suite":
        return f"{display(row.get('suite_id'))} @ {display(row.get('suite_version'))}"
    if key == "configuration":
        identity = json.dumps(config, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return f"{display(config.get('model_name'))} · {digest}"
    if key == "runtime":
        return display({k: config.get(k) for k in ("runtime", "runtime_version", "transport", "runtime_identity")})
    return display(row.get("human_review_state" if key == "review" else key))


def row_matches(row, filters):
    return all(value == "All" or filter_value(row, key) == value for key, value in filters.items())


def metric_matches(report, metric, filters):
    if all(value == "All" for value in filters.values()):
        return True
    rows = [report.rows[ref["row_id"]] for ref in metric["case_refs"]]
    # A filter selects complete published populations. It never changes a
    # denominator by removing inconvenient failures, blocks or pending reviews.
    return bool(rows) and all(row_matches(row, filters) for row in rows)


def compare_reports(series):
    """Use T13's existing compatibility rules; never calculate a combined score."""
    result = compare_series([metric for _, metric in series])
    for comparison in result:
        left_report, left = series[comparison["left_series"] - 1]
        right_report, right = series[comparison["right_series"] - 1]
        reasons = set(comparison["exclusion_reasons"])
        if left.get("metric_version") != right.get("metric_version"):
            reasons.add("different_metric_version")
        if left_report.projection.get("catalog_sha256") != right_report.projection.get("catalog_sha256"):
            reasons.add("different_catalog_sha256")
        comparison["eligible"] = not reasons
        comparison["exclusion_reasons"] = sorted(reasons)
    return result


def validate_projection(projection):
    if not isinstance(projection, dict) or projection.get("schema_version") != REPORT_VERSION:
        raise ValueError("Unsupported metric report version; use its matching reporting reader")
    if not all(isinstance(projection.get(k), list) for k in ("case_details", "metrics", "comparisons")):
        raise ValueError("Invalid T13 report collections")
    rows = {}
    for row in projection["case_details"]:
        if not isinstance(row, dict) or not row.get("row_id") or not row.get("case_id"):
            raise ValueError("Missing exact case row identity")
        if row["row_id"] in rows:
            raise ValueError("Duplicate case row identity")
        rows[row["row_id"]] = row
    for metric in projection["metrics"]:
        if not isinstance(metric, dict) or not isinstance(metric.get("case_refs"), list):
            raise ValueError("Invalid metric case references")
        for ref in metric["case_refs"]:
            row = rows.get(ref.get("row_id"))
            if row is None or any(ref.get(k) != row.get(k) for k in (
                    "case_id", "run_id", "trial_id", "attempt_id", "artifact_sha256")):
                raise ValueError("Metric-to-case identity mismatch")
            if any(metric.get(k) != row.get(k) for k in SOURCE_FIELDS):
                raise ValueError("Metric-to-case suite/rubric mismatch")
            if metric.get("configuration") != row.get("configuration"):
                raise ValueError("Metric-to-case configuration mismatch")
        for excluded in metric.get("excluded", []):
            for row_id in excluded.get("row_ids", []):
                if row_id not in rows or rows[row_id]["case_id"] != excluded.get("case_id"):
                    raise ValueError("Excluded case identity mismatch")
    return rows


@dataclass
class ReviewReport:
    path: Path
    sha256: str
    raw: dict
    rows: dict
    projection: dict | None
    run_dir: Path
    workbook: Path

    @property
    def metrics(self):
        return self.projection["metrics"] if self.projection else []

    def metric_rows(self, metric):
        # A row ID is local to this exact source report, never a global case name.
        ids = [ref["row_id"] for ref in metric["case_refs"]]
        ids.extend(r for item in metric.get("excluded", []) for r in item.get("row_ids", []))
        return [self.rows[key] for key in dict.fromkeys(ids)]


def load_report(path, *, evidence_root=None):
    path = Path(path).resolve()
    if path.suffix.lower() == ".csv" and (path.parent / "review-package.json").is_file():
        path = path.parent / "review-package.json"
    data = path.read_bytes()
    projection = None
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows = normalize_rows(rows, source_path=path)
        raw = {"source_kind": "legacy_case_csv", "case_results": rows}
    else:
        raw = json.loads(data)
        if not isinstance(raw, dict):
            raise ValueError("Report must be a JSON object")
        if raw.get("schema_version") == REPORT_VERSION:
            projection = raw
        elif "qualification_v2_metrics" in raw:
            projection = raw["qualification_v2_metrics"]
            if projection is None:
                raise ValueError("Invalid null metric projection")
        if projection is not None:
            rows = validate_projection(projection)
        else:
            root = evidence_root or (path.parent / "evidence")
            rows = normalize_legacy_report(path, evidence_root=root)["cases"]
    if projection is None:
        # Use T13's compatibility semantics only. Legacy percentages are not
        # invented or regenerated here; a versioned writer export enables charts.
        rows = {f"legacy-{i}": {**row, "row_id": f"legacy-{i}",
                "normalized_status": case_status(row),
                "human_review_state": human_review_state(row),
                "configuration": configuration_identity(row)}
                for i, row in enumerate(rows, 1)}
    run_dir = path.parent.parent if path.parent.name == "review" else path.parent
    review = raw.get("review_package") or {}
    workbook = review.get("xlsx") if isinstance(review, dict) else None
    if workbook:
        workbook = Path(workbook)
        if not workbook.is_absolute():
            workbook = path.parent / workbook
    else:
        workbook = run_dir / "review" / "review-package.xlsx"
    return ReviewReport(path, hashlib.sha256(data).hexdigest(), raw, rows,
                        projection, run_dir, workbook)


def discover_reports(roots):
    """Only named benchmark report files under explicitly supplied output roots."""
    found = set()
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        packages = list(root.rglob("review-package.json"))
        package_runs = [p.parent.parent if p.parent.name == "review" else p.parent for p in packages]
        found.update(p.resolve() for p in packages)
        for name in ("aggregate-report.json", "summary.json"):
            for path in root.rglob(name):
                if name == "summary.json" and any(path.is_relative_to(run) for run in package_runs):
                    continue
                found.add(path.resolve())
    return sorted(found)


def queue_run_path(repo_root, item):
    if not item.run_dir:
        return None
    path = Path(item.run_dir)
    return (path if path.is_absolute() else Path(repo_root) / path).resolve()


def queue_matches(report, items, repo_root):
    return [item for item in items if queue_run_path(repo_root, item) == report.run_dir.resolve()]


def evidence_path(report, row, ref):
    value = ref.get("resolved_path") or ref.get("path")
    if not value:
        raise ValueError("Evidence has no exact file path")
    path = Path(value)
    if not path.is_absolute():
        root = row.get("source_evidence_root")
        if root is None:
            raise ValueError("Relative evidence has no recorded source root")
        path = Path(root) / path
    return path.resolve()


def read_evidence(report, row, ref):
    """Read bytes, never shell-open generated programs or guess moved artifacts."""
    path = evidence_path(report, row, ref)
    data = path.read_bytes()
    observed = hashlib.sha256(data).hexdigest()
    expected = ref.get("sha256")
    integrity = "verified" if expected == observed else "stale" if expected else "unknown (no recorded hash)"
    preview = data[:2_000_000].decode("utf-8", errors="replace")
    if len(data) > 2_000_000:
        preview += "\n[Preview truncated; SHA-256 covers the entire file.]"
    return path, integrity, observed, preview
