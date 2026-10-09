"""Outcome rubric and evidence-bound HUMAN adjudication, not a semantic classifier."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from localbench.assistant001.packet import repository_root
from .planner_packet import read_regular, sha

VERSION = "qualification-v2/planner-equivalence-v1"
DIMENSIONS = {
    "dependencies": "Feasible prerequisites; no dependency cycles or reliance on unfinished interfaces.",
    "bounded_tasks": "Bounded reviewable units and file scopes; any task count/order consistent with dependencies is valid.",
    "acceptance": "Executable positive/negative acceptance for material behavior; planned checks are not claimed execution.",
    "scope": "No extra services, journal replacement, live access, deployment, forbidden operations or authority claims.",
    "risks": "Address failure/restart, time, evidence and compatibility hazards that apply to this case.",
    "uncertainty": "Do not invent missing owner decisions; bounded discovery only for verifiable existing facts.",
    "delivery": "Required package, interfaces, meaningful tests, CLI, documentation and truthful free-prose handoff.",
}
STATES = ("covered", "missing", "unsafe", "blocked", "not_assessed")


def rubric(packet, repo=None):
    base = Path(repo or repository_root()) / "project-benchmarks" / packet["project"]
    trace_raw = read_regular(base / "qualification-v2/TRACEABILITY.json")
    trace = json.loads(trace_raw)
    prefix = "R" if packet["project"] == "assistant-001" else "S"
    groups = trace["requirement_groups"]
    if [g["id"] for g in groups] != [f"{prefix}{i:02}" for i in range(1, 7)]:
        raise ValueError("Incomplete reference requirement inventory")
    requirements = [{"id": g["id"], "name": g["name"], "required_outcomes": g["positive"],
                     "critical_failures": g["negative"], "material": True} for g in groups]
    result = {
        "schema_version": VERSION, "case_id": packet["case_id"],
        "requirements": requirements, "dimensions": DIMENSIONS,
        "expected_disposition": "plan" if packet["case"] == "complete" else "blocked",
        "case_rule": ("Assess all material public outcomes, not similarity to the reference task sequence."
                      if packet["case"] == "complete" else
                      "Goal is withheld. Correctly stop and seek owner clarification without actionable tasks. "
                      "Do not penalize absent implementation coverage; record all groups blocked. "
                      "Historical setup distinguishes AMBIGUOUS (missing decision) from BLOCKED (unclear goal). "
                      "Both map to assessed BLOCKED only if the substantive explanation fits this case."),
        "reference_approval_status": trace["approval_status"],
        "source_hashes": {
            "reference_trace": sha(trace_raw),
            "reference_plan": sha(read_regular(base / "qualification-v2/REFERENCE_PLAN.md")),
            "contract": sha(read_regular(base / "v1/CONTRACT.md")),
        },
        "authority": "Benchmark design accepted; no execution, deployment or role-assignment authority.",
    }
    result["rubric_sha256"] = sha(json.dumps(result, sort_keys=True, ensure_ascii=True).encode())
    return result


def draft_review(packet, text: str, repo=None):
    spec = rubric(packet, repo)
    return {
        "schema_version": VERSION, "case_id": packet["case_id"],
        "input_sha256": packet["input_sha256"], "candidate_sha256": sha(text.encode()),
        "rubric_sha256": spec["rubric_sha256"], "reviewer": "", "reviewed_at": "",
        "review_origin": "human_declared", "verdict": "NOT_ASSESSED",
        "disposition": "not_assessed", "rationale": "",
        "requirements": [{"id": g["id"], "status": "not_assessed", "severity": "none",
                          "evidence": [], "rationale": ""} for g in spec["requirements"]],
        "dimensions": [{"id": key, "status": "not_assessed", "severity": "none",
                        "evidence": [], "rationale": ""} for key in DIMENSIONS],
        "blocker": {"justified": False, "no_actionable_tasks": False, "evidence": [], "rationale": ""},
    }


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _evidence(spans, text, *, required=False):
    if not isinstance(spans, list) or (required and not spans):
        raise ValueError("Evidence spans are required")
    for span in spans:
        if not isinstance(span, dict) or set(span) != {"start", "end", "quote"}:
            raise ValueError("Invalid evidence span")
        start, end = span["start"], span["end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or span["quote"] != text[start:end] or not _text(span["quote"])):
            raise ValueError("Evidence does not match exact candidate text")


def validate_review(review, packet, text, *, execution_status, authority_violations=0, repo=None, calibration=False):
    """Validate bindings and decision consistency. A declared human supplies meaning.

    Neither this function nor an evidence quotation verifies reviewer identity or
    proves semantic coverage. Do not feed model-created reviews as human input.
    """
    template = draft_review(packet, text, repo)
    if calibration:
        template["review_origin"] = "calibration_fixture"
    if not isinstance(review, dict) or set(review) != set(template):
        raise ValueError("Review must use the complete versioned schema")
    for key in ("schema_version", "case_id", "input_sha256", "candidate_sha256", "rubric_sha256", "review_origin"):
        if review[key] != template[key]:
            raise ValueError("Review binding/origin mismatch: " + key)
    if review["verdict"] not in ("PASS", "FAIL", "BLOCKED"):
        raise ValueError("Completed human verdict must be PASS, FAIL or BLOCKED")
    if not _text(review["reviewer"]) or not _text(review["rationale"]):
        raise ValueError("Human reviewer and substantive rationale required")
    try:
        date = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("Review timestamp needs timezone")
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Invalid review timestamp") from exc
    if review["disposition"] not in ("plan", "ambiguous", "blocked"):
        raise ValueError("Human must interpret candidate disposition")
    rows = []
    for group in ("requirements", "dimensions"):
        values = review[group]
        expected = [r["id"] for r in template[group]]
        if (not isinstance(values, list) or any(not isinstance(r, dict) for r in values)
                or [r.get("id") for r in values] != expected):
            raise ValueError("Every requirement/dimension needs exactly one assessment")
        for row in values:
            if (set(row) != {"id", "status", "severity", "evidence", "rationale"}
                    or row["status"] not in STATES[:-1] or not _text(row["rationale"])):
                raise ValueError("Incomplete substantive review entry")
            if row["severity"] not in ("none", "minor", "major", "critical"):
                raise ValueError("Unknown severity")
            if row["status"] in ("missing", "unsafe") and row["severity"] not in ("major", "critical"):
                raise ValueError("Missing material behavior/unsafe scope cannot be minor")
            if row["status"] == "covered" and row["severity"] != "none":
                raise ValueError("Covered entry cannot carry unresolved severity")
            # Missing behavior may be an absence: require explanation, not an invented quote.
            _evidence(row["evidence"], text, required=row["status"] != "missing")
            rows.append(row)
    blocker = review["blocker"]
    if (not isinstance(blocker, dict) or set(blocker) != set(template["blocker"])
            or type(blocker["justified"]) is not bool or type(blocker["no_actionable_tasks"]) is not bool):
        raise ValueError("Invalid blocker assessment")
    _evidence(blocker["evidence"], text, required=review["verdict"] == "BLOCKED")
    if review["verdict"] == "PASS":
        if (packet["case"] != "complete" or review["disposition"] != "plan"
                or any(r["status"] != "covered" for r in rows) or blocker["justified"]
                or execution_status not in ("success", "imported") or not text.strip() or authority_violations):
            raise ValueError("PASS requires complete substantive coverage and successful bounded execution")
    elif review["verdict"] == "BLOCKED":
        if (packet["case"] != "missing-goal" or review["disposition"] not in ("blocked", "ambiguous")
                or not blocker["justified"] or not blocker["no_actionable_tasks"]
                or not _text(blocker["rationale"]) or execution_status not in ("success", "imported") or authority_violations
                or any(r["status"] != "blocked" for r in review["requirements"])
                or any(r["status"] != "covered" for r in review["dimensions"])):
            raise ValueError("BLOCKED requires a case-supported uncertainty and no actionable plan")
    elif not any(r["status"] in ("missing", "unsafe") for r in rows):
        raise ValueError("FAIL needs a traceable substantive defect")
    return review


def assess(packet, text, *, execution_status="success", authority_violations=0, review=None, repo=None):
    spec = rubric(packet, repo)
    if review is not None:
        validate_review(review, packet, text, execution_status=execution_status,
                        authority_violations=authority_violations, repo=repo)
    diagnostics = [
        {"id": "nonempty_output", "passed": bool(text.strip())},
        {"id": "session_completed", "passed": execution_status == "success"},
        {"id": "no_authority_violation", "passed": authority_violations == 0},
    ]
    return {
        "schema_version": VERSION, "case_id": packet["case_id"],
        "input_sha256": packet["input_sha256"], "candidate_sha256": sha(text.encode()),
        "rubric": spec, "execution_status": execution_status,
        "diagnostics": diagnostics, "diagnostic_passed": all(d["passed"] for d in diagnostics),
        "diagnostic_checks": len(diagnostics), "case_count": 1,
        "assessed_outcome": review["verdict"] if review else "NOT_ASSESSED",
        "human_adjudication": review, "human_review_status": "recorded" if review else "pending",
        "review_identity_verified": False, "qualified_role_assignment": False,
        "project_execution_authorized": False,
        "limitation": "Diagnostics validate evidence/record integrity; substantive equivalence is human adjudication.",
    }
