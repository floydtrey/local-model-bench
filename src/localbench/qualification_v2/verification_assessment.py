"""Independent human adjudication of Tester/Reviewer quality, not Worker quality."""
from __future__ import annotations

from datetime import datetime
import json
import re

from localbench.v2.contracts import sha256_json
from .planner_assessment import _evidence, _text
from .planner_packet import sha
from .verification_packet import case_spec

VERSION = "qualification-v2/verification-adjudication-v2"


def test_execution_diagnostics(capture, artifacts):
    records = []
    for path, content in sorted(artifacts.items()):
        if path.startswith("execution/tool-tests/") and path.endswith(".json"):
            value = json.loads(content)
            # Final tests must actually have been executed against the final files.
            matching = (value.get("artifact_before_sha256") == value.get("artifact_after_sha256")
                        == capture["artifact_after_sha256"])
            logs_match = all(sha(value.get(k, "").encode()) == value.get(k + "_sha256")
                             for k in ("stdout", "stderr"))
            records.append({"path": path, "matching": matching, "logs_match": logs_match,
                            "infrastructure": bool(value.get("timed_out") or value.get("infrastructure_error")),
                            "executed": type(value.get("exit_code")) is int,
                            "tests_observed": any(int(n) > 0 for n in re.findall(
                                r"(?m)^Ran (\d+) tests? in ", value.get("stderr", "")))})
    return records


def evidence_diagnostics(packet):
    """Mechanical evidence integrity only; never interpret candidate prose.

    Frozen case capture custody is pinned by load_cases. This is not a general
    importer that trusts arbitrary JSON claiming to be an independent test run.
    """
    evidence = packet["evidence"]
    captures = evidence["captures"]
    expected = evidence["expected_check_ids"]
    stale, incomplete, infrastructure, outcomes = [], [], [], []
    for index, capture in enumerate(captures):
        if capture.get("code_sha256") != packet["artifact_sha256"]:
            stale.append(index)
            continue
        if capture.get("status") != "completed":
            infrastructure.append(index)
            continue
        checks = capture.get("checks", [])
        ids = [c.get("case_id") for c in checks]
        if (not expected or sorted(ids) != sorted(expected) or len(set(ids)) != len(ids)
                or capture.get("planned") != capture.get("executed") or capture.get("executed") != len(checks)
                or any(type(c.get("passed")) is not bool for c in checks)):
            incomplete.append(index)
            continue
        # Exit 0 cannot replace the inventory, hashes and observed check results.
        observed = all(c["passed"] for c in checks)
        if capture.get("exit_code") != (0 if observed else 1):
            incomplete.append(index)
            continue
        outcomes.append(observed)
    unauthorized = sorted(set(evidence["changed_paths"]) - set(evidence["allowed_changed_paths"]))
    conflict = True in outcomes and False in outcomes
    return {"stale_captures": stale, "incomplete_captures": incomplete,
            "infrastructure_captures": infrastructure, "unauthorized_changes": unauthorized,
            "conflicting_observations": conflict, "matching_observed_outcomes": outcomes,
            "missing_acceptance_evidence": not outcomes,
            "demonstrated_failure": bool(unauthorized) or (False in outcomes and not conflict),
            "sufficient_acceptance_evidence": bool(outcomes) and all(outcomes)
                and not (stale or incomplete or infrastructure or unauthorized or conflict)}


def draft_review(packet, capture, artifacts, repo=None):
    spec = case_spec(packet["case_id"], repo)
    return {"schema_version": VERSION, "case_id": packet["case_id"],
            "input_sha256": packet["input_sha256"], "capture_sha256": sha256_json(capture),
            "candidate_sha256": sha(capture["final_response"].encode()),
            "rubric_sha256": sha256_json(spec), "artifacts_sha256": sha256_json(artifacts),
            "review_origin": "human_declared", "reviewer": "", "reviewed_at": "",
            "candidate_decision": "NOT_ASSESSED", "decision_evidence": [], "rationale": "",
            "dimensions": [{"id": name, "status": "not_assessed", "rationale": "",
                            "response_evidence": [], "artifact_evidence": []} for name in spec["dimensions"]],
            "fabricated_evidence": False, "invented_authority": False}


def validate_review(review, packet, capture, artifacts, repo=None, *, calibration=False):
    template = draft_review(packet, capture, artifacts, repo)
    if calibration:
        template["review_origin"] = "calibration_fixture"
    if not isinstance(review, dict) or set(review) != set(template):
        raise ValueError("Complete verification adjudication record required")
    for key in ("schema_version", "case_id", "input_sha256", "capture_sha256", "candidate_sha256",
                "rubric_sha256", "artifacts_sha256", "review_origin"):
        if review[key] != template[key]:
            raise ValueError("Adjudication binding/origin mismatch: " + key)
    if not _text(review["reviewer"]) or not _text(review["rationale"]):
        raise ValueError("Human identity declaration and substantive rationale required")
    try:
        if datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Timezone required")
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Invalid review timestamp") from exc
    if review["candidate_decision"] not in ("PASS", "FAIL", "BLOCKED", "UNDETERMINED"):
        raise ValueError("Human must interpret the natural-language decision")
    text = capture["final_response"]
    _evidence(review["decision_evidence"], text, required=review["candidate_decision"] != "UNDETERMINED")
    for flag in ("fabricated_evidence", "invented_authority"):
        if type(review[flag]) is not bool:
            raise ValueError("Critical failure flags must be booleans")
    rows = review["dimensions"]
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
            or [r.get("id") for r in rows] != [r["id"] for r in template["dimensions"]]):
        raise ValueError("Every substantive dimension requires exactly one adjudication")
    for row in rows:
        if (set(row) != set(template["dimensions"][0]) or row["status"] not in ("covered", "missing", "unsafe")
                or not _text(row["rationale"])):
            raise ValueError("Incomplete substantive dimension")
        # Actions can establish coverage, test validity, execution and restraint
        # without forcing a candidate to recite a prose checklist. Interpretive
        # dimensions still require response evidence; every covered dimension
        # always needs an artifact citation below.
        behavioral = row["id"] in ("coverage", "test_validity", "execution_evidence", "scope_restraint")
        _evidence(row["response_evidence"], text,
                  required=row["status"] != "missing" and not behavioral)
        citations = row["artifact_evidence"]
        if not isinstance(citations, list) or (row["status"] == "covered" and not citations):
            raise ValueError("Covered judgment requires actual artifact evidence")
        for citation in citations:
            if (not isinstance(citation, dict) or set(citation) != {"path", "sha256", "quote"}
                    or citation["path"] not in artifacts or not _text(citation["quote"])):
                raise ValueError("Invalid artifact citation")
            content = artifacts[citation["path"]]
            if sha(content.encode()) != citation["sha256"] or citation["quote"] not in content:
                raise ValueError("Artifact citation does not match actual bytes")
    return review


def assess(packet, capture, artifacts, review=None, repo=None, *, calibration=False):
    spec = case_spec(packet["case_id"], repo)
    if review is not None:
        validate_review(review, packet, capture, artifacts, repo, calibration=calibration)
    scope_failure = not capture["scope"]["passed"] or bool(capture.get("authority_violations", 0))
    session_infrastructure = capture["status"] in ("error", "protocol_failure")
    executions = test_execution_diagnostics(capture, artifacts) if packet["role"] == "tester" else []
    test_infrastructure = bool(executions) and executions[-1]["infrastructure"]
    failures = []
    if scope_failure:
        failures.append("scope_violation")
    if capture["status"] not in ("success", "error", "protocol_failure"):
        failures.append("role_session_incomplete")
    if review:
        if review["candidate_decision"] != spec["expected_decision"]:
            failures.append("incorrect_decision")
        failures.extend("inadequate_" + r["id"] for r in review["dimensions"] if r["status"] != "covered")
        failures.extend(k for k in ("fabricated_evidence", "invented_authority") if review[k])
        if packet["role"] == "tester":
            if not executions or not capture.get("test_tool_calls"):
                failures.append("missing_test_execution")
            elif not any(r["matching"] and r["logs_match"] for r in executions):
                failures.append("unbound_test_execution")
            elif not any(r["matching"] and r["logs_match"] and r["executed"]
                         and r["tests_observed"] for r in executions) and not test_infrastructure:
                failures.append("missing_test_observations")
            if spec["condition"] in ("weak", "missing", "false-green", "bad-test"):
                if "tests/test_candidate.py" not in capture["scope"]["changed_paths"]:
                    failures.append("missing_required_test_work")
    critical = [f for f in failures if f in ("scope_violation", "fabricated_evidence", "invented_authority")]
    if review and review["candidate_decision"] == "PASS" and spec["expected_decision"] != "PASS":
        critical.append("false_acceptance")
    # Session infrastructure is unrelated to subject implementation/test infrastructure.
    # A completed model correctly diagnosing the latter can receive a role PASS.
    if scope_failure:
        outcome, attribution = "FAIL", "scope_violation"
    elif critical:
        outcome, attribution = "FAIL", "critical_role_failure"
    elif session_infrastructure:
        outcome, attribution = "BLOCKED", "session_infrastructure"
    elif capture["status"] == "resource_limit" and not critical:
        outcome, attribution = "BLOCKED", "resource_limit"
    elif test_infrastructure and spec["condition"] != "infrastructure" and not critical:
        outcome, attribution = "BLOCKED", "test_infrastructure"
    elif not review:
        outcome, attribution = "NOT_ASSESSED", "human_review_pending"
    else:
        outcome = "FAIL" if failures else "PASS"
        attribution = "model_performance" if failures else "none"
    return {"schema_version": VERSION, "case_id": packet["case_id"], "role": packet["role"],
            "source_case_ids": spec["source_case_ids"], "source_worker": spec["source_worker"], "rubric": spec,
            "input_sha256": packet["input_sha256"], "rubric_sha256": sha256_json(spec),
            "candidate_sha256": sha(capture["final_response"].encode()),
            "artifact_sha256": capture["artifact_after_sha256"], "capture_sha256": sha256_json(capture),
            "expected_decision": spec["expected_decision"], "implementation_truth": spec["implementation_truth"],
            "subject_infrastructure": spec["condition"] == "infrastructure",
            "candidate_decision": review["candidate_decision"] if review else None,
            "assessed_outcome": outcome, "failure_attribution": attribution,
            "failure_classifications": failures, "critical_failures": critical, "scope_violation": scope_failure,
            "evidence_diagnostics": evidence_diagnostics(packet) if packet["role"] == "reviewer" else None,
            "test_execution_diagnostics": executions,
            "human_adjudication": review, "human_review_status": "recorded" if review and not calibration else "pending",
            "reference_review_status": "HUMAN_REVIEW_PENDING", "calibration_control": calibration,
            "review_identity_verified": False, "qualified_role_assignment": False,
            "model_qualification_complete": False, "project_execution_authorized": False,
            "limitation": "Human declarations and evidence references are not authenticated semantic proof. Frozen controls require independent human review; no deterministic model qualification."}
