from __future__ import annotations

import csv
import io
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..util import validate_id
from .contracts import EvidenceRef, SealedEvidence, seal_evidence
from .orchestrator import EvidenceStore
from .records import CASE_STATUSES, EVALUATION_VERDICTS
from .repetition import REPETITION_RUNNER_VERSION, RepeatedRun


AGGREGATE_REPORT_VERSION = "benchmark-lab-aggregate-report:v1"


class AggregationError(RuntimeError):
    pass


def _ref_dict(record: SealedEvidence) -> dict[str, str]:
    return record.reference.to_dict()


def _same_ref(value: Mapping[str, Any], reference: EvidenceRef) -> bool:
    return dict(value) == reference.to_dict()


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _numeric_stats(values: Sequence[float], expected: int) -> dict[str, Any]:
    if not values:
        return {
            "measured": 0,
            "expected": expected,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "population_variance": None,
        }
    normalized = [float(value) for value in values]
    return {
        "measured": len(normalized),
        "expected": expected,
        "minimum": min(normalized),
        "maximum": max(normalized),
        "mean": statistics.fmean(normalized),
        "median": statistics.median(normalized),
        "population_variance": statistics.pvariance(normalized),
    }


def _consistency_rate(counts: Mapping[str, int], total: int) -> float | None:
    if total < 1:
        return None
    return max(counts.values(), default=0) / total


def _iso_duration_seconds(started_at: Any, finished_at: Any) -> float | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    seconds = (finish - start).total_seconds()
    return seconds if seconds >= 0 else None


def _metric_value(case: SealedEvidence, name: str) -> float | None:
    metrics = case.payload.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    direct = _numeric(metrics.get(name))
    if direct is not None:
        return direct
    tool_summary = metrics.get("tool_summary")
    if isinstance(tool_summary, Mapping):
        return _numeric(tool_summary.get(name))
    return None


def _telemetry(case: SealedEvidence) -> Mapping[str, float]:
    metrics = case.payload.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    value = metrics.get("telemetry")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AggregationError("case metrics.telemetry must be an object when present")
    result: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise AggregationError("telemetry keys must be non-empty strings")
        if item is None:
            continue
        number = _numeric(item)
        if number is None:
            raise AggregationError(f"telemetry field {key!r} must be numeric or null")
        result[key] = number
    return result


def _hard_failures(evaluations: Sequence[SealedEvidence]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    affected = 0
    total = 0
    for evaluation in evaluations:
        rules = list(evaluation.payload.get("hard_failures", ()))
        if rules:
            affected += 1
        for rule in rules:
            counts[str(rule)] += 1
            total += 1
    return {
        "total": total,
        "evaluations_affected": affected,
        "by_rule": {key: counts[key] for key in sorted(counts)},
    }


def _score_values(evaluations: Sequence[SealedEvidence]) -> tuple[list[float], list[float]]:
    raw: list[float] = []
    normalized: list[float] = []
    for evaluation in evaluations:
        score = _numeric(evaluation.payload.get("score"))
        maximum = _numeric(evaluation.payload.get("maximum_score"))
        if score is None and maximum is None:
            continue
        if score is None or maximum is None or maximum <= 0:
            raise AggregationError("evaluation has incoherent score evidence")
        raw.append(score)
        normalized.append(score / maximum)
    return raw, normalized


def _evaluation_summary(evaluations: Sequence[SealedEvidence]) -> dict[str, Any]:
    verdicts: Counter[str] = Counter()
    for evaluation in evaluations:
        verdict = str(evaluation.payload.get("verdict"))
        if verdict not in EVALUATION_VERDICTS:
            raise AggregationError(f"unsupported evaluation verdict: {verdict!r}")
        verdicts[verdict] += 1
    total = len(evaluations)
    raw, normalized = _score_values(evaluations)
    return {
        "evaluation_count": total,
        "verdict_counts": {key: verdicts[key] for key in sorted(EVALUATION_VERDICTS)},
        "pass_rate": None if total == 0 else verdicts["pass"] / total,
        "verdict_consistency_rate": _consistency_rate(verdicts, total),
        "raw_score": _numeric_stats(raw, total),
        "normalized_score": _numeric_stats(normalized, total),
        "hard_failures": _hard_failures(evaluations),
    }


def _execution_summary(cases: Sequence[SealedEvidence]) -> dict[str, Any]:
    total = len(cases)
    statuses: Counter[str] = Counter()
    durations: list[float] = []
    metric_names = (
        "attempts",
        "retries",
        "model_turns",
        "tool_calls",
        "authorized_tool_calls",
        "denied_tool_calls",
        "successful_tool_calls",
        "failed_tool_calls",
    )
    values: dict[str, list[float]] = {name: [] for name in metric_names}
    telemetry_values: dict[str, list[float]] = defaultdict(list)

    for case in cases:
        status = str(case.payload.get("status"))
        if status not in CASE_STATUSES:
            raise AggregationError(f"unsupported case status: {status!r}")
        statuses[status] += 1
        duration = _iso_duration_seconds(
            case.payload.get("started_at"), case.payload.get("finished_at")
        )
        if duration is not None:
            durations.append(duration)
        for name in metric_names:
            value = _metric_value(case, name)
            if value is not None:
                values[name].append(value)
        for key, value in _telemetry(case).items():
            telemetry_values[key].append(value)

    return {
        "case_result_count": total,
        "status_counts": {key: statuses[key] for key in sorted(CASE_STATUSES)},
        "status_consistency_rate": _consistency_rate(statuses, total),
        "duration_seconds": _numeric_stats(durations, total),
        "attempts": _numeric_stats(values["attempts"], total),
        "retries": _numeric_stats(values["retries"], total),
        "model_turns": _numeric_stats(values["model_turns"], total),
        "tool_calls": _numeric_stats(values["tool_calls"], total),
        "authorized_tool_calls": _numeric_stats(values["authorized_tool_calls"], total),
        "denied_tool_calls": _numeric_stats(values["denied_tool_calls"], total),
        "successful_tool_calls": _numeric_stats(values["successful_tool_calls"], total),
        "failed_tool_calls": _numeric_stats(values["failed_tool_calls"], total),
        "telemetry": {
            key: _numeric_stats(telemetry_values[key], total)
            for key in sorted(telemetry_values)
        },
    }


def _validate_run(run: RepeatedRun) -> tuple[dict[str, list[SealedEvidence]], dict[str, list[SealedEvidence]]]:
    if not isinstance(run, RepeatedRun):
        raise ValueError("run must be RepeatedRun")
    if run.manifest.record_type != "run_manifest":
        raise AggregationError("run manifest evidence is invalid")
    if run.benchmark.record_type != "benchmark_input":
        raise AggregationError("benchmark evidence is invalid")
    harness = run.manifest.payload.get("harness_source")
    if not isinstance(harness, Mapping):
        raise AggregationError("manifest harness_source is missing")
    if harness.get("repetition_runner_version") != REPETITION_RUNNER_VERSION:
        raise AggregationError("manifest is not a BL-8B repetition run")
    if harness.get("repetition_phase") != run.repetition_phase:
        raise AggregationError("manifest repetition phase does not match run")

    trials_by_case: dict[str, list[SealedEvidence]] = defaultdict(list)
    trial_refs: dict[str, SealedEvidence] = {}
    for trial in run.trials:
        if trial.record_type != "trial_identity":
            raise AggregationError("run contains non-trial evidence in trials")
        case_id = str(trial.payload.get("case_id"))
        if not _same_ref(trial.payload.get("benchmark", {}), run.benchmark.reference):
            raise AggregationError("trial benchmark reference does not match run benchmark")
        if trial.payload.get("repeat_group") is None:
            raise AggregationError("repeated trial must have repeat_group identity")
        if trial.sha256 in trial_refs:
            raise AggregationError("duplicate trial evidence")
        trial_refs[trial.sha256] = trial
        trials_by_case[case_id].append(trial)

    if set(trials_by_case) != set(run.planned_counts):
        raise AggregationError("planned case set does not match trial evidence")
    for case_id, expected in run.planned_counts.items():
        values = sorted(int(item.payload["ordinal"]) for item in trials_by_case[case_id])
        if values != list(range(1, expected + 1)):
            raise AggregationError(
                f"case {case_id!r} trial ordinals do not match predeclared repetition count"
            )
        groups = {str(item.payload["repeat_group"]) for item in trials_by_case[case_id]}
        if len(groups) != 1:
            raise AggregationError(f"case {case_id!r} spans multiple repeat groups")

    cases_by_id: dict[str, list[SealedEvidence]] = defaultdict(list)
    case_by_sha: dict[str, SealedEvidence] = {}
    seen_trial_results: set[str] = set()
    execution_shas = {item.sha256 for item in run.execution_evidence}
    for case in run.case_results:
        if case.record_type != "case_result":
            raise AggregationError("run contains non-case evidence in case_results")
        if not _same_ref(case.payload.get("manifest", {}), run.manifest.reference):
            raise AggregationError("case result manifest reference does not match run")
        if not _same_ref(case.payload.get("benchmark", {}), run.benchmark.reference):
            raise AggregationError("case result benchmark reference does not match run")
        trial_ref = EvidenceRef.from_dict(case.payload.get("trial", {}))
        if trial_ref.sha256 not in trial_refs:
            raise AggregationError("case result references a trial outside the run")
        if trial_ref.sha256 in seen_trial_results:
            raise AggregationError("multiple case results reference the same trial")
        seen_trial_results.add(trial_ref.sha256)
        primary = case.payload.get("execution_evidence", {}).get("primary")
        primary_ref = EvidenceRef.from_dict(primary)
        if primary_ref.sha256 not in execution_shas:
            raise AggregationError("case result primary execution evidence is outside the run")
        case_id = str(case.payload.get("case_id"))
        cases_by_id[case_id].append(case)
        case_by_sha[case.sha256] = case
    if seen_trial_results != set(trial_refs):
        raise AggregationError("not every planned trial has exactly one case result")

    evaluations_by_case: dict[str, list[SealedEvidence]] = defaultdict(list)
    for evaluation in run.evaluation_results:
        if evaluation.record_type != "evaluation_result":
            raise AggregationError("run contains non-evaluation evidence")
        case_ref = EvidenceRef.from_dict(evaluation.payload.get("case", {}))
        case = case_by_sha.get(case_ref.sha256)
        if case is None:
            raise AggregationError("evaluation references a case result outside the run")
        evaluations_by_case[str(case.payload["case_id"])].append(evaluation)

    return dict(cases_by_id), dict(evaluations_by_case)


def aggregate_repeated_run(logical_id: str, run: RepeatedRun) -> SealedEvidence:
    """Derive immutable aggregate evidence from raw repeated-trial evidence.

    Raw trials, execution traces, CaseResults, and EvaluationResults remain the
    source of truth. This record contains only derived statistics plus exact
    references to the evidence supporting them.
    """

    validate_id(logical_id, "logical_id")
    cases_by_id, evaluations_by_case = _validate_run(run)
    case_aggregates: list[dict[str, Any]] = []

    for case_id in run.planned_counts:
        trials = [item for item in run.trials if item.payload.get("case_id") == case_id]
        cases = cases_by_id.get(case_id, [])
        evaluations = evaluations_by_case.get(case_id, [])
        by_evaluator: dict[str, list[SealedEvidence]] = defaultdict(list)
        evaluator_refs: dict[str, Mapping[str, Any]] = {}
        for evaluation in evaluations:
            evaluator = evaluation.payload.get("evaluator")
            if not isinstance(evaluator, Mapping):
                raise AggregationError("evaluation evaluator reference is missing")
            key = str(evaluator.get("sha256"))
            by_evaluator[key].append(evaluation)
            evaluator_refs[key] = evaluator

        evaluator_aggregates = []
        for key in sorted(by_evaluator):
            group = by_evaluator[key]
            evaluator_aggregates.append(
                {
                    "evaluator": dict(evaluator_refs[key]),
                    **_evaluation_summary(group),
                    "evidence": [_ref_dict(item) for item in group],
                }
            )

        repeat_groups = {str(item.payload["repeat_group"]) for item in trials}
        case_aggregates.append(
            {
                "case_id": case_id,
                "repeat_group": next(iter(repeat_groups)),
                "planned_trials": run.planned_counts[case_id],
                "observed_trials": len(cases),
                "execution": _execution_summary(cases),
                "evaluation": _evaluation_summary(evaluations),
                "evaluators": evaluator_aggregates,
                "evidence": {
                    "trials": [_ref_dict(item) for item in trials],
                    "case_results": [_ref_dict(item) for item in cases],
                    "evaluation_results": [_ref_dict(item) for item in evaluations],
                },
            }
        )

    all_cases = list(run.case_results)
    all_evaluations = list(run.evaluation_results)
    payload = {
        "report_version": AGGREGATE_REPORT_VERSION,
        "manifest": _ref_dict(run.manifest),
        "benchmark": _ref_dict(run.benchmark),
        "repetition_phase": run.repetition_phase,
        "planned_trials": sum(run.planned_counts.values()),
        "observed_trials": len(run.case_results),
        "overall": {
            "execution": _execution_summary(all_cases),
            "evaluation": _evaluation_summary(all_evaluations),
        },
        "cases": case_aggregates,
        "evidence": {
            "trials": [_ref_dict(item) for item in run.trials],
            "execution_evidence": [_ref_dict(item) for item in run.execution_evidence],
            "case_results": [_ref_dict(item) for item in run.case_results],
            "evaluation_results": [_ref_dict(item) for item in run.evaluation_results],
        },
    }
    return seal_evidence("aggregate_report", logical_id, payload)


def persist_aggregate_report(report: SealedEvidence, store: EvidenceStore) -> None:
    if not isinstance(report, SealedEvidence) or report.record_type != "aggregate_report":
        raise ValueError("report must be aggregate_report evidence")
    if not isinstance(store, EvidenceStore):
        raise ValueError("store must be EvidenceStore")
    store.persist(report)


def render_aggregate_markdown(report: SealedEvidence) -> str:
    if not isinstance(report, SealedEvidence) or report.record_type != "aggregate_report":
        raise ValueError("report must be aggregate_report evidence")
    payload = report.payload
    overall_eval = payload["overall"]["evaluation"]
    overall_exec = payload["overall"]["execution"]
    lines = [
        "# Benchmark Lab Aggregate Report",
        "",
        f"- Report evidence: `{report.sha256}`",
        f"- Repetition phase: `{payload['repetition_phase']}`",
        f"- Planned trials: {payload['planned_trials']}",
        f"- Observed trials: {payload['observed_trials']}",
        f"- Evaluation observations: {overall_eval['evaluation_count']}",
        f"- Pass rate: {overall_eval['pass_rate'] if overall_eval['pass_rate'] is not None else 'unknown'}",
        f"- Hard failures: {overall_eval['hard_failures']['total']}",
        "",
        "| Case | Trials | Pass rate | Mean normalized score | Score variance | Hard failures | Mean duration (s) | Mean tool calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in payload["cases"]:
        evaluation = case["evaluation"]
        execution = case["execution"]
        score = evaluation["normalized_score"]
        duration = execution["duration_seconds"]
        tools = execution["tool_calls"]
        def shown(value: Any) -> str:
            return "unknown" if value is None else str(value)
        lines.append(
            "| "
            + " | ".join(
                [
                    str(case["case_id"]),
                    f"{case['observed_trials']}/{case['planned_trials']}",
                    shown(evaluation["pass_rate"]),
                    shown(score["mean"]),
                    shown(score["population_variance"]),
                    str(evaluation["hard_failures"]["total"]),
                    shown(duration["mean"]),
                    shown(tools["mean"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Aggregates are derived evidence only. Raw trial, execution, case, and evaluation records remain authoritative.",
            "",
        ]
    )
    return "\n".join(lines)


def render_aggregate_csv(report: SealedEvidence) -> str:
    if not isinstance(report, SealedEvidence) or report.record_type != "aggregate_report":
        raise ValueError("report must be aggregate_report evidence")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "case_id",
            "planned_trials",
            "observed_trials",
            "evaluation_count",
            "pass_rate",
            "verdict_consistency_rate",
            "mean_normalized_score",
            "median_normalized_score",
            "normalized_score_variance",
            "hard_failures",
            "mean_duration_seconds",
            "mean_tool_calls",
            "mean_model_turns",
        ]
    )
    for case in report.payload["cases"]:
        evaluation = case["evaluation"]
        execution = case["execution"]
        writer.writerow(
            [
                case["case_id"],
                case["planned_trials"],
                case["observed_trials"],
                evaluation["evaluation_count"],
                evaluation["pass_rate"],
                evaluation["verdict_consistency_rate"],
                evaluation["normalized_score"]["mean"],
                evaluation["normalized_score"]["median"],
                evaluation["normalized_score"]["population_variance"],
                evaluation["hard_failures"]["total"],
                execution["duration_seconds"]["mean"],
                execution["tool_calls"]["mean"],
                execution["model_turns"]["mean"],
            ]
        )
    return output.getvalue()
