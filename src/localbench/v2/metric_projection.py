"""Case-level, evidence-linked metric projections for the existing review writer.

This module never executes a benchmark and never infers PASS from process exit.
Only explicitly versioned, deterministic case results are scored. The catalog
does not qualify models or authorize role assignments.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence


CATALOG_VERSION = "qualification-v2/metric-catalog:v1"
REPORT_VERSION = "qualification-v2/metrics:v1"
STATUS = frozenset({"passed", "failed", "blocked", "not_attempted",
                    "not_tested", "unsupported", "pending_review", "unknown"})


def case_status(row: Mapping[str, Any]) -> str:
    """Separate execution, assessment and human review; legacy gaps are unknown."""
    execution = row.get("execution_status")
    if execution in ("blocked", "prerequisite_blocked", "authority_blocked"):
        return "blocked"
    if execution in ("not_attempted", "waiting", "skipped"):
        return "not_attempted"
    if execution in ("error", "protocol_failure", "timeout", "interrupted", "runtime_error"):
        return "unknown"
    if execution == "unsupported" or row.get("runtime_compatibility") == "unsupported":
        return "unsupported"
    review = row.get("human_review_status")
    if row.get("human_review_required") is True and row.get("human_adjudication") not in ("approved", "APPROVED", "not_required"):
        return "pending_review"
    if review in ("pending", "HUMAN_REVIEW_PENDING", "review_pending"):
        return "pending_review"
    if row.get("human_review_required") is True and review not in ("approved", "recorded", "not_required"):
        return "pending_review"
    outcome = row.get("assessed_outcome")
    if outcome in ("pass", "passed", "PASS"):
        return "passed"
    if outcome in ("fail", "failed", "FAIL"):
        return "failed"
    if outcome in ("blocked", "BLOCKED"):
        return "blocked"
    if row.get("deterministic_passed") is True:
        return "passed"
    if row.get("deterministic_passed") is False:
        return "failed"
    return "unknown"


def _identity(row: Mapping[str, Any], meta: Mapping[str, Any]) -> tuple[Any, ...]:
    # Absent identity is never silently made comparable.
    return tuple(row.get(k) if row.get(k) is not None else meta.get(k)
                 for k in ("candidate_id", "model_identity", "runtime_identity",
                           "track", "worker_mode", "comparison_protocol"))


def project_metrics(
    rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    if catalog.get("schema_version") != CATALOG_VERSION:
        raise ValueError("unsupported metric catalog version")
    output = []
    for definition in catalog["metrics"]:
        case_ids = definition["cases"]
        base = {
            "metric_id": definition["id"], "kind": definition["kind"],
            "suite_id": definition["suite"], "suite_version": definition["suite_version"],
            "rubric_id": definition["rubric"], "rubric_version": definition["rubric_version"],
            "scoring": definition["scoring"], "membership": case_ids,
            "numerator": None, "denominator": None, "percentage": None,
            "distinct_cases": 0, "attempt_count": 0, "acceptance_check_count": None,
            "blocked_cases": [], "not_attempted_cases": [], "pending_review_cases": [],
            "unknown_cases": [], "unsupported_cases": [],
            "status": "not_tested", "review_status": "not_assessed",
            "case_refs": [], "excluded": [], "first_pass": None, "after_repair": None,
        }
        if not case_ids or definition["scoring"] != "independent_deterministic_case_pass":
            output.append(base)
            continue
        candidates = [r for r in rows
                      if r.get("suite_id") == definition["suite"]
                      and r.get("suite_version") == definition["suite_version"]
                      and r.get("rubric_version") == definition["rubric_version"]
                      and r.get("case_id") in case_ids]
        if not candidates:
            output.append(base)
            continue
        groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
        for row in candidates:
            identity = _identity(row, metadata)
            # Incomplete identity is evidence, but not an eligible cross-model score.
            if any(v is None for v in identity[:3]):
                base["excluded"].append({"case_id": row.get("case_id"), "reason": "unknown_model_or_runtime_identity"})
                continue
            groups[tuple(str(x) for x in identity)].append(row)
        # Do not combine configurations or protocols, even when the same case IDs occur.
        if len(groups) != 1:
            for group in groups.values():
                for row in group:
                    base["excluded"].append({"case_id": row.get("case_id"), "reason": "incompatible_configuration"})
            output.append(base)
            continue
        chosen = next(iter(groups.values()))
        by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in chosen:
            by_case[str(row["case_id"])].append(row)
        scored = []
        for case_id, attempts in sorted(by_case.items()):
            statuses = [case_status(r) for r in attempts]
            for label, target in (("blocked", "blocked_cases"), ("not_attempted", "not_attempted_cases"),
                                  ("pending_review", "pending_review_cases"), ("unknown", "unknown_cases"),
                                  ("unsupported", "unsupported_cases")):
                if label in statuses:
                    base[target].append(case_id)
            if any(s not in ("passed", "failed") for s in statuses):
                base["excluded"].append({"case_id": case_id, "reason": "unassessed_or_blocked_attempt"})
                continue
            # Repetitions are not independent cases. A final-case rate requires
            # an explicit attempt-selection policy; absent that, mark repeated
            # case trials as incomparable rather than cherry-picking a success.
            if len(attempts) != 1:
                base["excluded"].append({"case_id": case_id, "reason": "multiple_attempts_without_selection_policy"})
                continue
            row = attempts[0]
            if not row.get("evidence_directory") and not row.get("assessment_file"):
                base["excluded"].append({"case_id": case_id, "reason": "missing_case_evidence"})
                continue
            scored.append((case_id, statuses[0], row))
        base["attempt_count"] = len(chosen)
        base["distinct_cases"] = len(by_case)
        base["case_refs"] = [
            {"case_id": case_id, "ordinal": row.get("ordinal"),
             "first_pass_passed": row.get("first_pass_passed"),
             "repair_attempted": row.get("repair_attempted"),
             "repair_passed": row.get("repair_passed"),
             "status": status, "evidence_directory": row.get("evidence_directory"),
             "assessment_file": row.get("assessment_file"),
             "artifact_sha256": row.get("artifact_sha256")}
            for case_id, status, row in scored
        ]
        if scored:
            base["denominator"] = len(scored)
            base["numerator"] = sum(status == "passed" for _, status, _ in scored)
            base["percentage"] = 100.0 * base["numerator"] / base["denominator"]
            base["status"] = "measured"
            base["review_status"] = "deterministic_only"
            if all(type(row.get("first_pass_passed")) is bool for _, _, row in scored):
                base["first_pass"] = {
                    "numerator": sum(row["first_pass_passed"] for _, _, row in scored),
                    "denominator": len(scored),
                }
            if all(type(row.get("repair_attempted")) is bool for _, _, row in scored):
                repaired = [row for _, _, row in scored if row["repair_attempted"]]
                if repaired and all(type(row.get("repair_passed")) is bool for row in repaired):
                    base["after_repair"] = {
                        "numerator": sum(row["repair_passed"] for row in repaired),
                        "denominator": len(repaired),
                    }
        output.append(base)
    return {"schema_version": REPORT_VERSION, "metrics": output,
            "universal_intelligence_score": None, "automatic_role_assignment": False}
