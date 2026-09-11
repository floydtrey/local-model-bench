from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .contracts import EvidenceRef, SealedEvidence, seal_evidence, sha256_json


SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_LAYERS = frozenset({"intrinsic", "lab_tool", "acl_system", "role"})
CASE_STATUSES = frozenset(
    {"success", "error", "blocked", "resource_limit", "protocol_failure"}
)
EVALUATION_VERDICTS = frozenset({"pass", "fail", "review", "not_scored"})


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        result.append(_object(item, f"{label}[{index}]"))
    return result


def _string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array of strings")
    result = list(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{label} must contain non-empty strings")
    if not allow_empty and not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _nullable_string(value: Any, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{label} must be a string or null")
    return value


def _nullable_int(value: Any, label: str, *, minimum: int = 0) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum} or null")
    return value


def _nullable_number(value: Any, label: str, *, minimum: float = 0) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label} must be a number >= {minimum} or null")
    return float(value)


def _sha256_or_null(value: Any, label: str) -> str | None:
    value = _nullable_string(value, label)
    if value is not None and not SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest or null")
    return value


def _ref(value: EvidenceRef | Mapping[str, Any], expected_type: str, label: str) -> dict[str, str]:
    reference = value if isinstance(value, EvidenceRef) else EvidenceRef.from_dict(value)
    if reference.record_type != expected_type:
        raise ValueError(
            f"{label} must reference {expected_type!r}, got {reference.record_type!r}"
        )
    return reference.to_dict()


def _refs(
    values: Iterable[EvidenceRef | Mapping[str, Any]], expected_type: str, label: str
) -> list[dict[str, str]]:
    result = [_ref(value, expected_type, label) for value in values]
    if not result:
        raise ValueError(f"{label} must contain at least one reference")
    return result


def host_profile(
    logical_id: str,
    *,
    captured_at: str,
    os_info: Mapping[str, Any],
    cpu: Mapping[str, Any],
    memory: Mapping[str, Any],
    gpus: Sequence[Mapping[str, Any]],
    storage: Sequence[Mapping[str, Any]],
    python: Mapping[str, Any],
    compute_runtimes: Sequence[Mapping[str, Any]],
    power_thermal: Mapping[str, Any] | None = None,
) -> SealedEvidence:
    if not isinstance(captured_at, str) or not captured_at:
        raise ValueError("captured_at must be a non-empty string")
    facts = {
        "os": _object(os_info, "os_info"),
        "cpu": _object(cpu, "cpu"),
        "memory": _object(memory, "memory"),
        "gpus": _object_list(gpus, "gpus"),
        "storage": _object_list(storage, "storage"),
        "python": _object(python, "python"),
        "compute_runtimes": _object_list(compute_runtimes, "compute_runtimes"),
        "power_thermal": None
        if power_thermal is None
        else _object(power_thermal, "power_thermal"),
    }
    payload = {
        "captured_at": captured_at,
        "facts_sha256": sha256_json(facts),
        **facts,
    }
    return seal_evidence("host_profile", logical_id, payload)


def runtime_profile(
    logical_id: str,
    *,
    runtime_kind: str,
    version: str | None,
    build: str | None,
    transport: Mapping[str, Any],
    executable: Mapping[str, Any] | None,
    installation_digest: str | None,
    capabilities: Mapping[str, Any],
) -> SealedEvidence:
    if not isinstance(runtime_kind, str) or not runtime_kind:
        raise ValueError("runtime_kind must be a non-empty string")
    payload = {
        "runtime_kind": runtime_kind,
        "version": _nullable_string(version, "version"),
        "build": _nullable_string(build, "build"),
        "transport": _object(transport, "transport"),
        "executable": None if executable is None else _object(executable, "executable"),
        "installation_digest": _sha256_or_null(
            installation_digest, "installation_digest"
        ),
        "capabilities": _object(capabilities, "capabilities"),
    }
    return seal_evidence("runtime_profile", logical_id, payload)


def model_identity(
    logical_id: str,
    *,
    family: str | None,
    name: str,
    source: Mapping[str, Any],
    artifact_digest: str | None,
    provider_digest: str | None,
    parameter_count: int | None,
    quantization: str | None,
    precision: str | None,
    declared_context_tokens: int | None,
) -> SealedEvidence:
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    payload = {
        "family": _nullable_string(family, "family"),
        "name": name,
        "source": _object(source, "source"),
        "artifact_digest": _sha256_or_null(artifact_digest, "artifact_digest"),
        "provider_digest": _sha256_or_null(provider_digest, "provider_digest"),
        "parameter_count": _nullable_int(parameter_count, "parameter_count"),
        "quantization": _nullable_string(quantization, "quantization"),
        "precision": _nullable_string(precision, "precision"),
        "declared_context_tokens": _nullable_int(
            declared_context_tokens, "declared_context_tokens", minimum=1
        ),
    }
    return seal_evidence("model_identity", logical_id, payload)


def effective_runtime_config(
    logical_id: str,
    *,
    runtime: EvidenceRef | Mapping[str, Any],
    model: EvidenceRef | Mapping[str, Any],
    settings: Mapping[str, Any],
    tool_surface: Mapping[str, Any],
    limits: Mapping[str, Any],
) -> SealedEvidence:
    payload = {
        "runtime": _ref(runtime, "runtime_profile", "runtime"),
        "model": _ref(model, "model_identity", "model"),
        "settings": _object(settings, "settings"),
        "tool_surface": _object(tool_surface, "tool_surface"),
        "limits": _object(limits, "limits"),
    }
    return seal_evidence("effective_runtime_config", logical_id, payload)


def benchmark_input(
    logical_id: str,
    *,
    suite_id: str,
    source_sha256: str,
    level: str,
    case_ids: Sequence[str],
    source_format: str,
    source_locator: str | None,
) -> SealedEvidence:
    if not isinstance(suite_id, str) or not suite_id:
        raise ValueError("suite_id must be a non-empty string")
    if not SHA256.fullmatch(source_sha256):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if level not in {"L0", "L1", "L2", "L3", "L4"}:
        raise ValueError("level must be one of L0, L1, L2, L3, or L4")
    if not isinstance(source_format, str) or not source_format:
        raise ValueError("source_format must be a non-empty string")
    payload = {
        "suite_id": suite_id,
        "source_sha256": source_sha256,
        "level": level,
        "case_ids": _string_list(case_ids, "case_ids", allow_empty=False),
        "source_format": source_format,
        "source_locator": _nullable_string(source_locator, "source_locator"),
    }
    return seal_evidence("benchmark_input", logical_id, payload)


def evaluator_identity(
    logical_id: str,
    *,
    evaluator_id: str,
    version: str,
    implementation_sha256: str,
    result_contract: str,
    requires_human_review: bool,
) -> SealedEvidence:
    if not all(isinstance(value, str) and value for value in (evaluator_id, version, result_contract)):
        raise ValueError("evaluator_id, version, and result_contract must be non-empty strings")
    if not SHA256.fullmatch(implementation_sha256):
        raise ValueError("implementation_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(requires_human_review, bool):
        raise ValueError("requires_human_review must be boolean")
    payload = {
        "evaluator_id": evaluator_id,
        "version": version,
        "implementation_sha256": implementation_sha256,
        "result_contract": result_contract,
        "requires_human_review": requires_human_review,
    }
    return seal_evidence("evaluator_identity", logical_id, payload)


def trial_identity(
    logical_id: str,
    *,
    layer: str,
    ordinal: int,
    repeat_group: str | None,
    benchmark: EvidenceRef | Mapping[str, Any],
) -> SealedEvidence:
    if layer not in RUN_LAYERS:
        raise ValueError(f"layer must be one of {sorted(RUN_LAYERS)}")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ValueError("ordinal must be an integer >= 1")
    payload = {
        "layer": layer,
        "ordinal": ordinal,
        "repeat_group": _nullable_string(repeat_group, "repeat_group"),
        "benchmark": _ref(benchmark, "benchmark_input", "benchmark"),
    }
    return seal_evidence("trial_identity", logical_id, payload)


def run_manifest(
    logical_id: str,
    *,
    host: EvidenceRef | Mapping[str, Any],
    runtime: EvidenceRef | Mapping[str, Any],
    model: EvidenceRef | Mapping[str, Any],
    effective_config: EvidenceRef | Mapping[str, Any],
    benchmarks: Iterable[EvidenceRef | Mapping[str, Any]],
    evaluators: Iterable[EvidenceRef | Mapping[str, Any]],
    trials: Iterable[EvidenceRef | Mapping[str, Any]],
    harness_source: Mapping[str, Any],
) -> SealedEvidence:
    """Seal the immutable pre-run definition.

    Mutable run status/checkpoint fields are deliberately excluded. A running or
    completed state may change over time; the exact experiment definition must not.
    """

    payload = {
        "host": _ref(host, "host_profile", "host"),
        "runtime": _ref(runtime, "runtime_profile", "runtime"),
        "model": _ref(model, "model_identity", "model"),
        "effective_config": _ref(
            effective_config, "effective_runtime_config", "effective_config"
        ),
        "benchmarks": _refs(benchmarks, "benchmark_input", "benchmarks"),
        "evaluators": _refs(evaluators, "evaluator_identity", "evaluators"),
        "trials": _refs(trials, "trial_identity", "trials"),
        "harness_source": _object(harness_source, "harness_source"),
    }
    return seal_evidence("run_manifest", logical_id, payload)


def case_result(
    logical_id: str,
    *,
    manifest: EvidenceRef | Mapping[str, Any],
    benchmark: EvidenceRef | Mapping[str, Any],
    trial: EvidenceRef | Mapping[str, Any],
    case_id: str,
    status: str,
    started_at: str,
    finished_at: str,
    metrics: Mapping[str, Any],
    execution_evidence: Mapping[str, Any],
    terminal_output: Mapping[str, Any] | None,
) -> SealedEvidence:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be a non-empty string")
    if status not in CASE_STATUSES:
        raise ValueError(f"status must be one of {sorted(CASE_STATUSES)}")
    if not isinstance(started_at, str) or not started_at:
        raise ValueError("started_at must be a non-empty string")
    if not isinstance(finished_at, str) or not finished_at:
        raise ValueError("finished_at must be a non-empty string")
    payload = {
        "manifest": _ref(manifest, "run_manifest", "manifest"),
        "benchmark": _ref(benchmark, "benchmark_input", "benchmark"),
        "trial": _ref(trial, "trial_identity", "trial"),
        "case_id": case_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "metrics": _object(metrics, "metrics"),
        "execution_evidence": _object(execution_evidence, "execution_evidence"),
        "terminal_output": None
        if terminal_output is None
        else _object(terminal_output, "terminal_output"),
    }
    return seal_evidence("case_result", logical_id, payload)


def evaluation_result(
    logical_id: str,
    *,
    case: EvidenceRef | Mapping[str, Any],
    evaluator: EvidenceRef | Mapping[str, Any],
    verdict: str,
    score: float | None,
    maximum_score: float | None,
    hard_failures: Sequence[str],
    checks: Sequence[Mapping[str, Any]],
) -> SealedEvidence:
    if verdict not in EVALUATION_VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(EVALUATION_VERDICTS)}")
    score_value = _nullable_number(score, "score")
    maximum_value = _nullable_number(maximum_score, "maximum_score")
    if (score_value is None) != (maximum_value is None):
        raise ValueError("score and maximum_score must both be present or both be null")
    if score_value is not None and maximum_value is not None:
        if maximum_value <= 0:
            raise ValueError("maximum_score must be greater than zero when scored")
        if score_value > maximum_value:
            raise ValueError("score cannot exceed maximum_score")
    payload = {
        "case": _ref(case, "case_result", "case"),
        "evaluator": _ref(evaluator, "evaluator_identity", "evaluator"),
        "verdict": verdict,
        "score": score_value,
        "maximum_score": maximum_value,
        "hard_failures": _string_list(hard_failures, "hard_failures"),
        "checks": _object_list(checks, "checks"),
    }
    return seal_evidence("evaluation_result", logical_id, payload)
