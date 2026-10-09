"""Evidence-linked projections of assessor-owned results, never a second scorer."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

CATALOG_VERSION = "qualification-v2/metric-catalog:v1"
REPORT_VERSION = "qualification-v2/metrics:v2"
STATUS = frozenset({"passed", "failed", "blocked", "not_attempted", "not_tested",
                    "unsupported", "pending_review", "unknown"})
COMPLETED = {"completed", "success", "passed", "failed", "fail"}
ERRORS = {"error", "protocol_failure", "timeout", "interrupted", "runtime_error", "resource_limit"}
BLOCKED = {"blocked", "prerequisite_blocked", "authority_blocked"}
UNATTEMPTED = {"not_attempted", "waiting", "skipped"}
PROTOCOL_FIELDS = ("track", "role", "worker_mode", "planner_mode", "governor_mode", "verification_mode",
                   "comparison_protocol", "authority_assumptions", "assessor_version", "evidence_version",
                   "runtime_compatibility")
SOURCE_FIELDS = ("suite_id", "suite_version", "rubric_id", "rubric_version")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _lower(value):
    return str(value).lower() if value is not None else "unknown"


def assessed_outcome(row):
    value = _lower(row.get("assessed_outcome", row.get("assessment_outcome")))
    if value in ("pass", "passed"):
        return "passed"
    if value in ("fail", "failed"):
        return "failed"
    if value == "blocked":
        return "blocked"
    if value in ("unknown", "not_assessed", "none") and type(row.get("deterministic_passed")) is bool:
        return "passed" if row["deterministic_passed"] else "failed"
    return "unknown"


def human_review_state(row):
    review = row.get("human_adjudication")
    required, status = row.get("human_review_required"), _lower(row.get("human_review_status"))
    if isinstance(review, Mapping):
        bound = all(row.get(k) and review.get(k) == row[k]
                    for k in ("input_sha256", "candidate_sha256", "rubric_sha256"))
        if (bound and review.get("review_origin") == "human_declared" and review.get("reviewer")
                and review.get("reviewed_at") and status == "recorded"):
            return "recorded"
        return "pending"
    if required is True or status in ("pending", "human_review_pending", "review_pending"):
        return "pending"
    if _lower(review) == "rejected" or status == "rejected":
        return "rejected"
    if required is False and status in ("not_required", "unknown"):
        return "not_required"
    return "unknown"


def contradictions(row):
    reasons = []
    outcome, execution = assessed_outcome(row), _lower(row.get("execution_status"))
    if outcome in ("passed", "failed") and execution in BLOCKED | UNATTEMPTED | ERRORS | {"unsupported", "not_tested"}:
        reasons.append("execution_assessment_contradiction")
    explicit = _lower(row.get("assessed_outcome", row.get("assessment_outcome")))
    if (type(row.get("deterministic_passed")) is bool and explicit in ("pass", "passed", "fail", "failed")
            and row["deterministic_passed"] != (outcome == "passed")):
        reasons.append("conflicting_assessments")
    if row.get("first_pass_passed") is True and row.get("repair_attempted") is True:
        reasons.append("repair_after_claimed_first_pass_success")
    if row.get("repair_passed") is True and (row.get("repair_attempted") is not True or outcome != "passed"):
        reasons.append("conflicting_repair_outcome")
    if (row.get("first_pass_passed") is False and outcome == "passed"
            and row.get("repair_attempted") is not True):
        reasons.append("success_without_declared_repair")
    if row.get("first_pass_passed") is True and outcome == "failed":
        reasons.append("first_pass_final_outcome_contradiction")
    return reasons


def case_status(row: Mapping[str, Any]) -> str:
    execution = _lower(row.get("execution_status"))
    if execution in BLOCKED:
        return "blocked"
    if execution in UNATTEMPTED:
        return "not_attempted"
    if execution == "not_tested":
        return "not_tested"
    if execution == "unsupported" or _lower(row.get("runtime_compatibility")) == "unsupported":
        return "unsupported"
    if execution in ERRORS or row.get("failure_attribution") in (
            "infrastructure", "session_infrastructure", "test_infrastructure", "resource_limit"):
        return "unknown"
    if contradictions(row):
        return "unknown"
    review = human_review_state(row)
    if review == "pending":
        return "pending_review"
    if review == "rejected":
        return "unknown"
    return assessed_outcome(row)


def inspect_evidence(row, root=None):
    """Verify declared local artifact bytes; directories alone are not evidence."""
    refs, verified, reasons = row.get("evidence_refs") or [], [], []
    root = row.get("source_evidence_root") or root
    if not refs:
        return [], ["missing_case_evidence"]
    for ref in refs:
        item = dict(ref)
        try:
            path = Path(ref["path"])
            if not path.is_absolute():
                if root is None:
                    raise ValueError("relative evidence needs an explicit root")
                path = Path(root) / path
            data = path.read_bytes()
            observed = hashlib.sha256(data).hexdigest()
            item["resolved_path"] = str(path.resolve())
            item["observed_sha256"] = observed
            if not ref.get("sha256"):
                reasons.append("unbound_evidence_hash")
                item["integrity"] = "unknown"
            elif observed != ref["sha256"]:
                reasons.append("stale_evidence_hash")
                item["integrity"] = "stale"
            else:
                item["integrity"] = "verified"
                if ref.get("kind") == "assessment":
                    assessment = json.loads(data)
                    task_matches = (row.get("role") == "worker" and assessment.get("task")
                                    == str(row.get("case_id", "")).rsplit("-", 1)[-1].upper())
                    if not assessment.get("case_id") and not task_matches:
                        reasons.append("missing_assessment_case_binding")
                    for key in ("case_id", "input_sha256", "candidate_sha256", "rubric_sha256"):
                        if key in assessment and row.get(key) != assessment[key]:
                            reasons.append("assessment_binding_mismatch")
                    outcome = assessment.get("assessed_outcome")
                    if outcome is not None and _lower(outcome) != _lower(row.get("assessed_outcome")):
                        reasons.append("assessment_outcome_mismatch")
                    if outcome is None:
                        if type(assessment.get("passed")) is not bool:
                            reasons.append("unassessed_evidence")
                        elif assessment["passed"] != row.get("deterministic_passed"):
                            reasons.append("implementation_and_task_outcome_differ")
                    if row.get("human_adjudication") is not None and assessment.get("human_adjudication") != row["human_adjudication"]:
                        reasons.append("assessment_review_mismatch")
                if ref.get("kind") == "candidate" and row.get("candidate_sha256") != observed:
                    reasons.append("stale_candidate_hash")
                if ref.get("kind") == "artifact":
                    expected = row.get("artifact_sha256")
                    if isinstance(expected, Mapping):
                        expected = expected.get(ref.get("artifact_key"))
                    if expected is not None and expected != observed:
                        reasons.append("stale_artifact_hash")
                if ref.get("kind") == "reference_review":
                    review = json.loads(data)
                    item["substantive_reference_review"] = (
                        review.get("review_origin") == "human_declared" and bool(review.get("reviewer"))
                        and bool(review.get("reviewed_at")) and review.get("verdict") == "APPROVED"
                        and all(row.get(k) and review.get(k) == row[k] for k in
                                ("suite_id", "suite_version", "rubric_version", "reference_sha256")))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            reasons.append("missing_case_evidence")
            item["integrity"] = "unavailable"
        verified.append(item)
    if row.get("artifact_sha256") is not None and row.get("observed_artifact_sha256") is not None:
        if row["artifact_sha256"] != row["observed_artifact_sha256"]:
            reasons.append("stale_artifact_hash")
    if not any(ref.get("kind") in ("assessment", "evaluation_result") for ref in refs):
        reasons.append("missing_scoring_authority_evidence")
    return verified, sorted(set(reasons))


def configuration_identity(row):
    model, runtime = row.get("model_identity"), row.get("runtime_identity")
    model = model if isinstance(model, Mapping) else {}
    runtime = runtime if isinstance(runtime, Mapping) else {}
    return {"candidate_id": row.get("candidate_id"),
        "model_name": row.get("model_name") or model.get("name"),
        "model_digest": row.get("model_digest") or model.get("provider_digest") or model.get("artifact_digest") or model.get("digest"),
        "quantization": row.get("quantization") or model.get("quantization"),
        "runtime": row.get("runtime") or runtime.get("runtime_kind") or runtime.get("name"),
        "runtime_version": row.get("runtime_version") or runtime.get("version"),
        "transport": row.get("transport") or runtime.get("transport"),
        "context_tokens": row.get("context_tokens"), "effective_settings": row.get("effective_settings"),
        "model_identity": row.get("model_identity"), "runtime_identity": row.get("runtime_identity")}


def _sources(definition):
    return definition.get("sources") or [{"suite_id": definition.get("suite"),
        "suite_version": definition.get("suite_version"), "rubric_id": definition.get("rubric"),
        "rubric_version": definition.get("rubric_version"), "cases": definition["cases"]}]


def _trial_result(rows):
    """One initial attempt and linked repairs; never select the best fresh trial."""
    if len(rows) == 1:
        row = rows[0]
        if row.get("attempt_index", 1) != 1:
            return None, "missing_initial_attempt"
        passed, first = row["normalized_status"] == "passed", row.get("first_pass_passed")
        if row.get("repair_attempted") is True:
            kinds = {ref.get("kind") for ref in row.get("evidence_refs", [])}
            if not {"first_pass", "repair"}.issubset(kinds) or type(first) is not bool:
                return None, "missing_repair_attempt_evidence"
            return (passed, first, True), None
        if row.get("attempt_index") == 1:
            return (passed, passed if first is None else first, False), None
        # A legacy final result without attempt provenance does not establish
        # that it was achieved on the first pass, or that no repair occurred.
        return (passed, first, row.get("repair_attempted")), None
    if any(type(r.get("attempt_index")) is not int or not r.get("attempt_id") for r in rows):
        return None, "multiple_attempts_without_selection_policy"
    ordered = sorted(rows, key=lambda r: r["attempt_index"])
    if [r["attempt_index"] for r in ordered] != list(range(1, len(rows) + 1)):
        return None, "noncontiguous_repair_attempts"
    if len({r["attempt_id"] for r in ordered}) != len(ordered):
        return None, "duplicate_attempt_identity"
    for before, after in zip(ordered, ordered[1:]):
        if after.get("parent_attempt_id") != before["attempt_id"] or before["normalized_status"] != "failed":
            return None, "invalid_repair_lineage"
    return (ordered[-1]["normalized_status"] == "passed", ordered[0]["normalized_status"] == "passed", True), None


def _case_result(rows, policy):
    trials = defaultdict(list)
    for row in rows:
        trials[(row.get("run_id"), row.get("trial_id"))].append(row)
    if len(trials) > 1:
        if (policy != "all_predeclared_trials_pass" or None in {r.get("trial_id") for r in rows}
                or {r.get("planned_trial_count") for r in rows} != {len(trials)}
                or {r.get("trial_ordinal") for r in rows} != set(range(1, len(trials) + 1))
                or len({r.get("repeat_group") for r in rows}) != 1 or not rows[0].get("repeat_group")):
            return None, "repeated_trials_without_complete_predeclared_population"
    results = []
    for group in trials.values():
        if len({r.get("trial_ordinal") for r in group}) != 1:
            return None, "conflicting_trial_ordinal"
        result, error = _trial_result(group)
        if error:
            return None, error
        results.append(result)
    expected = rows[0].get("planned_trial_count")
    if expected is not None and expected != len(trials):
        return None, "missing_planned_trials"
    return (all(r[0] for r in results),
            all(r[1] for r in results) if all(type(r[1]) is bool for r in results) else None,
            any(r[2] for r in results) if all(type(r[2]) is bool for r in results) else None), None


def _project_group(definition, source, rows, incompatible):
    # A released rubric may define a justified refusal as the successful task
    # disposition. Keep the raw outcome in case_details; only project its criterion.
    rows = [dict(row) for row in rows]
    for row in rows:
        accepted = source.get("successful_assessed_outcomes", {}).get(row["case_id"], [])
        if (_lower(row.get("assessed_outcome")) in [_lower(x) for x in accepted]
                and row["human_review_state"] == "recorded"
                and _lower(row.get("execution_status")) in COMPLETED and not row["exclusion_reasons"]):
            row["normalized_status"] = "passed"
    cases = source["cases"]
    config = rows[0]["configuration"] if rows else None
    protocol = {k: rows[0].get(k) for k in PROTOCOL_FIELDS} if rows else None
    item = {"metric_id": definition["id"], "metric_version": definition.get("version", "1"),
        "kind": definition["kind"], **{k: source.get(k) for k in SOURCE_FIELDS},
        "scoring": definition["scoring"], "membership": cases,
        "scoring_authority": definition.get("scoring_authority"), "definition": definition.get("definition"),
        "numerator_rule": definition.get("numerator"), "denominator_rule": definition.get("denominator"),
        "repeat_policy": definition.get("repeat_policy", "exclude_repeats"), "repair_policy": definition.get("repair_policy"),
        "configuration_id": _sha(config) if config else None, "configuration": config, "protocol": protocol,
        "numerator": None, "denominator": None, "percentage": None, "status": "not_tested",
        "review_status": "not_assessed", "first_pass": None, "after_repair": None,
        "comparison_eligible": False, "comparison_group": None, "comparison_exclusion_reasons": [],
        "case_refs": [], "excluded": list(incompatible),
        "coverage_required": source.get("minimum_coverage", definition.get("minimum_coverage", 1)),
        "planned_cases": len(cases), "distinct_cases": len({r["case_id"] for r in rows}),
        "distinct_evaluated_cases": len({r["case_id"] for r in rows if r["attempted"]
            and not contradictions(r) and r["normalized_assessed_outcome"] in ("passed", "failed")}),
        "attempted_cases": len({r["case_id"] for r in rows if r["attempted"]}),
        "attempt_count": sum(r["attempted"] for r in rows), "repeated_trials": 0,
        "acceptance_check_count": None,
        "acceptance_checks": [{"row_id": r["row_id"], "count": r.get("acceptance_check_count"),
                               "unit": r.get("acceptance_check_unit", "unknown")} for r in rows if r.get("acceptance_check_count") is not None],
        "first_pass_successes": 0, "repaired_successes": 0,
        "final_passed_cases": [], "final_failed_cases": [],
        "suitability": None, "criteria": definition.get("suitability_criteria")}
    for status in sorted(STATUS):
        item[status + "_cases"] = sorted({r["case_id"] for r in rows if r["normalized_status"] == status})
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    scored, population = [], {}
    for case_id, attempts in sorted(by_case.items()):
        trials = {(r.get("run_id"), r.get("trial_id")) for r in attempts if r["attempted"]}
        item["repeated_trials"] += max(0, len(trials) - 1)
        reasons = set()
        identities = {_json({k: r.get(k) for k in ("input_sha256", "reference_sha256", "rubric_sha256")}) for r in attempts}
        if len(identities) != 1:
            reasons.add("incompatible_material_inputs")
        for row in attempts:
            reasons.update(row["exclusion_reasons"])
            if row["normalized_status"] not in ("passed", "failed"):
                reasons.add(row["normalized_status"])
            if definition.get("human_review") and row["human_review_state"] != "recorded":
                reasons.add("substantive_human_review_required")
            if definition.get("role") and _lower(row.get("role")) != definition["role"]:
                reasons.add("incompatible_role")
        result = None
        if not reasons:
            result, error = _case_result(attempts, definition.get("repeat_policy", "exclude_repeats"))
            if error:
                reasons.add(error)
        for row in attempts:
            item["case_refs"].append({"case_id": case_id, "row_id": row["row_id"], "run_id": row.get("run_id"),
                "trial_id": row.get("trial_id"), "attempt_id": row.get("attempt_id"), "ordinal": row.get("ordinal"),
                "status": row["normalized_status"], "included": not reasons, "exclusion_reasons": sorted(reasons),
                "evidence_directory": row.get("evidence_directory"), "assessment_file": row.get("assessment_file"),
                "artifact_sha256": row.get("artifact_sha256"), "evidence_refs": row["verified_evidence_refs"]})
        if reasons:
            item["excluded"].append({"case_id": case_id, "row_ids": [r["row_id"] for r in attempts],
                                     "reasons": sorted(reasons), "reason": sorted(reasons)[0]})
        elif result:
            scored.append(result)
            item["final_passed_cases" if result[0] else "final_failed_cases"].append(case_id)
            population[case_id] = json.loads(next(iter(identities)))
    if rows:
        item["status"] = "insufficient_evidence"
        if any(r["human_review_state"] == "pending" for r in rows):
            item["status"] = "pending_review"
        else:
            for status in ("unsupported", "blocked", "not_attempted"):
                if all(r["normalized_status"] == status for r in rows):
                    item["status"] = status
        item["review_status"] = "pending" if item["status"] == "pending_review" else "observed"
    if scored:
        item["numerator"], item["denominator"] = sum(r[0] for r in scored), len(scored)
        item["first_pass_successes"] = sum(r[1] for r in scored) if all(type(r[1]) is bool for r in scored) else None
        item["repaired_successes"] = (sum(r[0] and not r[1] and r[2] for r in scored)
                                      if all(type(r[1]) is bool and type(r[2]) is bool for r in scored) else None)
        if item["first_pass_successes"] is not None:
            item["first_pass"] = {"numerator": item["first_pass_successes"], "denominator": len(scored)}
        repairs = [r for r in scored if r[2] is True]
        if repairs and all(type(r[1]) is bool for r in repairs):
            item["after_repair"] = {"numerator": sum(r[0] and not r[1] for r in repairs), "denominator": len(repairs)}
        if len(scored) >= item["coverage_required"]:
            item["status"], item["percentage"] = "measured", 100.0 * item["numerator"] / len(scored)
        item["review_status"] = ("pending" if any(r["human_review_state"] == "pending" for r in rows)
                                 else "substantive_review_recorded" if definition.get("human_review") else "deterministic_only")
    item["scored_population"] = population
    item["missing_coverage"] = sorted(set(cases) - set(population))
    reasons = set()
    if item["missing_coverage"]:
        reasons.add("incomplete_case_population")
    for row in rows:
        if row.get("comparison_eligible") is False:
            reasons.add("source_comparison_ineligible")
        for key in ("track", "comparison_protocol", "authority_assumptions", "assessor_version", "evidence_version", "runtime_compatibility"):
            if row.get(key) is None:
                reasons.add("unknown_" + key)
        if _lower(row.get("role")) == "worker" and not row.get("worker_mode"):
            reasons.add("unknown_worker_mode")
    if not rows or not scored:
        reasons.add("no_eligible_scored_cases")
    item["comparison_exclusion_reasons"], item["comparison_eligible"] = sorted(reasons), not reasons
    if not reasons:
        item["comparison_group"] = _sha({"metric": definition["id"], "version": item["metric_version"],
            "source": source, "protocol": protocol, "population": population})
    if definition["kind"] == "role_suitability":
        item["percentage"] = None
        relevant = [r for r in rows if not definition.get("role") or _lower(r.get("role")) == definition["role"]]
        gates = [r for r in relevant if r.get("critical_failures") or r.get("critical_unsafe_approval") or r.get("scope_violation")]
        if not relevant:
            label = "not_assessed"
        elif gates or any(r["normalized_status"] == "failed" for r in relevant):
            label = "criteria_not_met"
        elif any(r["human_review_state"] != "recorded" for r in rows):
            label = "provisional_review_pending"
        elif item["missing_coverage"]:
            label = "insufficient_evidence"
        elif not item["comparison_eligible"]:
            label = "provisional_evidence_eligibility"
        elif any(r.get("reference_review_status") != "human_approved" or not any(
                ref.get("substantive_reference_review") for ref in r["verified_evidence_refs"]) for r in rows):
            label = "provisional_reference_review_pending"
        else:
            label = "reviewed_evidence_supports_criteria"
        item["suitability"] = label
    if not cases and definition["scoring"] != "not_tested":
        item["status"] = "insufficient_coverage"
    return item


def compare_series(metrics):
    """Explain protocol differences without treating varied models as incompatible."""
    result = []
    for i, left in enumerate(metrics):
        for j, right in enumerate(metrics[i + 1:], i + 1):
            if left["metric_id"] != right["metric_id"]:
                continue
            reasons = set(left["comparison_exclusion_reasons"] + right["comparison_exclusion_reasons"])
            for key in SOURCE_FIELDS + ("membership", "scored_population"):
                if left[key] != right[key]:
                    reasons.add("different_" + key)
            for key in PROTOCOL_FIELDS:
                if (left["protocol"] or {}).get(key) != (right["protocol"] or {}).get(key):
                    reasons.add("different_" + key)
            result.append({"metric_id": left["metric_id"], "left_series": i + 1, "right_series": j + 1,
                           "eligible": not reasons, "exclusion_reasons": sorted(reasons),
                           "combined_score": None})
    return result


def project_metrics(rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any],
                    catalog: Mapping[str, Any], *, evidence_root=None) -> dict[str, Any]:
    if catalog.get("schema_version") != CATALOG_VERSION:
        raise ValueError("unsupported metric catalog version")
    details = []
    for index, raw in enumerate(rows):
        row = {**metadata, **raw}
        if evidence_root is not None:
            row.setdefault("source_evidence_root", str(Path(evidence_root).resolve()))
        row["row_id"] = f"row-{index + 1}"
        row["normalized_assessed_outcome"] = assessed_outcome(row)
        row["human_review_state"], row["normalized_status"] = human_review_state(row), case_status(row)
        row["attempted"] = _lower(row.get("execution_status")) in COMPLETED | ERRORS
        row["configuration"] = configuration_identity(row)
        row["verified_evidence_refs"], reasons = inspect_evidence(row, evidence_root)
        if row.get("adapter_exclusion_reason"):
            reasons.append("adapter_evidence_unavailable_or_invalid")
        reasons += contradictions(row)
        required = ("model_name", "model_digest", "quantization", "runtime", "runtime_version", "transport", "context_tokens", "effective_settings")
        if any(row["configuration"][k] in (None, "", "unknown", {}) for k in required):
            reasons.append("unknown_model_or_runtime_identity")
        for key in ("track", "comparison_protocol", "authority_assumptions", "assessor_version", "evidence_version"):
            if row.get(key) is None:
                reasons.append("unknown_" + key)
        if _lower(row.get("role")) == "worker" and not row.get("worker_mode"):
            reasons.append("unknown_worker_mode")
        for key in ("input_sha256", "reference_sha256", "rubric_sha256", "run_id", "trial_id", "attempt_id"):
            if not row.get(key):
                reasons.append("unknown_" + key)
        if not row["attempted"]:
            reasons.append("execution_not_observed")
        row["exclusion_reasons"] = sorted(set(reasons))
        details.append(row)
    output = []
    for definition in catalog["metrics"]:
        for source in _sources(definition):
            candidates, incompatible = [], []
            for row in details:
                if row.get("case_id") not in source["cases"]:
                    continue
                mismatches = ["incompatible_" + k for k in SOURCE_FIELDS if row.get(k) != source.get(k)]
                if mismatches:
                    incompatible.append({"case_id": row["case_id"], "row_ids": [row["row_id"]], "reasons": mismatches, "reason": mismatches[0]})
                else:
                    candidates.append(row)
            groups = defaultdict(list)
            for row in candidates:
                groups[_json([row["configuration"], {k: row.get(k) for k in PROTOCOL_FIELDS}])].append(row)
            if not groups:
                output.append(_project_group(definition, source, [], incompatible))
            for key in sorted(groups):
                output.append(_project_group(definition, source, groups[key], incompatible))
    return {"schema_version": REPORT_VERSION, "catalog_version": catalog.get("revision", CATALOG_VERSION),
        "catalog_sha256": _sha(catalog), "metrics": output, "case_details": details,
        "comparisons": compare_series(output),
        "universal_intelligence_score": None, "automatic_role_assignment": False,
        "aggregation_policy": "Separate configurations and protocols; each case earns at most one success. See catalog."}
