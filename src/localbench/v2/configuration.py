from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .contracts import SealedEvidence
from .records import effective_runtime_config


CONFIG_SPEC_VERSION = "benchmark-lab-runtime-config:v3"
COMPARISON_MODES = frozenset({"strict", "exploratory"})
ADAPTER_STATUSES = frozenset({"exact", "degraded", "unresolved"})
NETWORK_POLICIES = frozenset({"provider_only", "disabled", "task_allowed"})
RESIDENCY_MODES = frozenset({"unload_after_model", "keep_loaded"})
RESPONSE_FORMAT_MODES = frozenset({"text", "json_object", "json_schema"})
REASONING_MODES = frozenset({"enabled", "disabled", "unsupported"})
REASONING_EFFORTS = frozenset({"low", "medium", "high", "max"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")

GENERATION_DEFAULTS: dict[str, Any] = {
    "temperature": 0.0,
    "seed": 42,
    "top_p": 1.0,
    "top_k": None,
    "repeat_penalty": None,
    "stop": [],
}
EXECUTION_DEFAULTS: dict[str, Any] = {
    "retries": 0,
    "retry_delay_seconds": 0.0,
    "concurrency": 1,
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {unknown}")


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be an integer >= 1")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be an integer >= 0")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return result


def _nullable_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, label)


def _nullable_positive_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    result = _number(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be > 0 or null")
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array of strings")
    result = list(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{label} must contain non-empty strings")
    return result


def _apply_defaults(
    source: dict[str, Any], defaults: Mapping[str, Any], prefix: str
) -> tuple[dict[str, Any], list[str]]:
    result = dict(source)
    applied: list[str] = []
    for key, value in defaults.items():
        if key not in result:
            result[key] = list(value) if isinstance(value, list) else value
            applied.append(f"{prefix}.{key}")
    return result, applied


def _normalize_response_format(value: Any) -> dict[str, Any]:
    response = _mapping(value, "generation.response_format")
    _reject_unknown_keys(response, {"mode", "schema"}, "generation.response_format")
    mode = response.get("mode")
    if mode not in RESPONSE_FORMAT_MODES:
        raise ValueError(
            f"generation.response_format.mode must be one of {sorted(RESPONSE_FORMAT_MODES)}"
        )
    schema = response.get("schema")
    if mode == "json_schema":
        if not isinstance(schema, Mapping):
            raise ValueError("json_schema response format requires a schema object")
        schema = dict(schema)
    elif schema is not None:
        raise ValueError("response schema is only valid for json_schema mode")
    return {"mode": mode, "schema": schema}


def _normalize_reasoning(value: Any) -> dict[str, Any]:
    reasoning = _mapping(value, "generation.reasoning")
    _reject_unknown_keys(reasoning, {"mode", "effort"}, "generation.reasoning")
    if "mode" not in reasoning or "effort" not in reasoning:
        raise ValueError("generation.reasoning.mode and effort must be explicit")
    mode = reasoning["mode"]
    effort = reasoning["effort"]
    if mode not in REASONING_MODES:
        raise ValueError(
            f"generation.reasoning.mode must be one of {sorted(REASONING_MODES)}"
        )
    if effort is not None and effort not in REASONING_EFFORTS:
        raise ValueError(
            f"generation.reasoning.effort must be null or one of {sorted(REASONING_EFFORTS)}"
        )
    if mode != "enabled" and effort is not None:
        raise ValueError("reasoning effort is only valid when reasoning is enabled")
    return {"mode": mode, "effort": effort}


def _normalize_generation(
    value: Any,
) -> tuple[dict[str, Any], list[str]]:
    generation = _mapping(value, "generation")
    _reject_unknown_keys(
        generation,
        {
            "context_tokens",
            "max_output_tokens",
            "temperature",
            "seed",
            "top_p",
            "top_k",
            "repeat_penalty",
            "stop",
            "response_format",
            "reasoning",
        },
        "generation",
    )
    for required in (
        "context_tokens",
        "max_output_tokens",
        "response_format",
        "reasoning",
    ):
        if required not in generation:
            raise ValueError(f"generation.{required} must be explicit")
    generation, applied = _apply_defaults(generation, GENERATION_DEFAULTS, "generation")
    result = {
        "context_tokens": _positive_int(generation["context_tokens"], "generation.context_tokens"),
        "max_output_tokens": _positive_int(
            generation["max_output_tokens"], "generation.max_output_tokens"
        ),
        "temperature": _number(generation["temperature"], "generation.temperature", minimum=0),
        "seed": _nonnegative_int(generation["seed"], "generation.seed"),
        "top_p": _number(generation["top_p"], "generation.top_p", minimum=0),
        "top_k": _nullable_positive_int(generation["top_k"], "generation.top_k"),
        "repeat_penalty": _nullable_positive_number(
            generation["repeat_penalty"], "generation.repeat_penalty"
        ),
        "stop": _string_list(generation["stop"], "generation.stop"),
        "response_format": _normalize_response_format(generation["response_format"]),
        "reasoning": _normalize_reasoning(generation["reasoning"]),
    }
    if result["top_p"] > 1:
        raise ValueError("generation.top_p must be <= 1")
    return result, applied


def _normalize_residency(value: Any) -> dict[str, Any]:
    residency = _mapping(value, "execution.model_residency")
    _reject_unknown_keys(
        residency, {"mode", "keep_alive_seconds"}, "execution.model_residency"
    )
    mode = residency.get("mode")
    if mode not in RESIDENCY_MODES:
        raise ValueError(
            f"execution.model_residency.mode must be one of {sorted(RESIDENCY_MODES)}"
        )
    keep_alive = residency.get("keep_alive_seconds")
    if mode == "unload_after_model":
        if keep_alive not in (None, 0):
            raise ValueError("unload_after_model requires keep_alive_seconds 0 or null")
        keep_alive = 0
    else:
        keep_alive = _number(keep_alive, "execution.model_residency.keep_alive_seconds")
        if keep_alive <= 0:
            raise ValueError("keep_loaded requires keep_alive_seconds > 0")
    return {"mode": mode, "keep_alive_seconds": keep_alive}


def _normalize_execution(value: Any) -> tuple[dict[str, Any], list[str]]:
    execution = _mapping(value, "execution")
    _reject_unknown_keys(
        execution,
        {
            "timeout_seconds",
            "retries",
            "retry_delay_seconds",
            "concurrency",
            "model_residency",
            "network_policy",
        },
        "execution",
    )
    for required in ("timeout_seconds", "model_residency", "network_policy"):
        if required not in execution:
            raise ValueError(f"execution.{required} must be explicit")
    execution, applied = _apply_defaults(execution, EXECUTION_DEFAULTS, "execution")
    timeout = _number(execution["timeout_seconds"], "execution.timeout_seconds")
    if timeout <= 0:
        raise ValueError("execution.timeout_seconds must be > 0")
    delay = _number(execution["retry_delay_seconds"], "execution.retry_delay_seconds")
    if delay < 0:
        raise ValueError("execution.retry_delay_seconds must be >= 0")
    policy = execution["network_policy"]
    if policy not in NETWORK_POLICIES:
        raise ValueError(f"execution.network_policy must be one of {sorted(NETWORK_POLICIES)}")
    result = {
        "timeout_seconds": timeout,
        "retries": _nonnegative_int(execution["retries"], "execution.retries"),
        "retry_delay_seconds": delay,
        "concurrency": _positive_int(execution["concurrency"], "execution.concurrency"),
        "model_residency": _normalize_residency(execution["model_residency"]),
        "network_policy": policy,
    }
    return result, applied


def _normalize_tool_surface(value: Any, *, strict: bool) -> dict[str, Any]:
    surface = _mapping(value, "tool_surface")
    _reject_unknown_keys(
        surface, {"id", "tools", "max_tool_calls", "schema_sha256"}, "tool_surface"
    )
    for required in ("id", "tools", "max_tool_calls", "schema_sha256"):
        if required not in surface:
            raise ValueError(f"tool_surface.{required} must be explicit")
    surface_id = surface["id"]
    if not isinstance(surface_id, str) or not surface_id:
        raise ValueError("tool_surface.id must be a non-empty string")
    tools = _string_list(surface["tools"], "tool_surface.tools")
    maximum = _nonnegative_int(surface["max_tool_calls"], "tool_surface.max_tool_calls")
    schema_sha = surface["schema_sha256"]
    if schema_sha is not None and (
        not isinstance(schema_sha, str) or not SHA256.fullmatch(schema_sha)
    ):
        raise ValueError("tool_surface.schema_sha256 must be a lowercase SHA-256 digest or null")
    if not tools and maximum != 0:
        raise ValueError("tool_surface without tools must have max_tool_calls=0")
    if tools and maximum < 1:
        raise ValueError("tool_surface with tools must allow at least one tool call")
    if strict and tools and schema_sha is None:
        raise ValueError("strict tool configuration requires tool_surface.schema_sha256")
    return {
        "id": surface_id,
        "tools": tools,
        "max_tool_calls": maximum,
        "schema_sha256": schema_sha,
    }


def _normalize_adapter_resolution(value: Any, *, strict: bool) -> dict[str, Any]:
    adapter = _mapping(value, "adapter_resolution")
    _reject_unknown_keys(
        adapter,
        {"adapter_id", "status", "effective_request", "deviations"},
        "adapter_resolution",
    )
    for required in ("adapter_id", "status", "effective_request", "deviations"):
        if required not in adapter:
            raise ValueError(f"adapter_resolution.{required} must be explicit")
    adapter_id = adapter["adapter_id"]
    if not isinstance(adapter_id, str) or not adapter_id:
        raise ValueError("adapter_resolution.adapter_id must be a non-empty string")
    status = adapter["status"]
    if status not in ADAPTER_STATUSES:
        raise ValueError(f"adapter_resolution.status must be one of {sorted(ADAPTER_STATUSES)}")
    effective_request = _mapping(adapter["effective_request"], "adapter_resolution.effective_request")
    deviations = _string_list(adapter["deviations"], "adapter_resolution.deviations")
    if strict and (status != "exact" or deviations):
        raise ValueError(
            "strict comparison requires exact adapter resolution with no deviations"
        )
    return {
        "adapter_id": adapter_id,
        "status": status,
        "effective_request": effective_request,
        "deviations": deviations,
    }


def resolve_effective_configuration(
    logical_id: str,
    *,
    runtime: SealedEvidence,
    model: SealedEvidence,
    spec: Mapping[str, Any],
    adapter_resolution: Mapping[str, Any],
) -> SealedEvidence:
    """Resolve one case/trial configuration without contacting a model.

    Provider/backend adapters are responsible for translating the canonical
    generation/execution/tool contract into their exact request/launch settings.
    Their resolved request is sealed here before scored execution.
    """

    if runtime.record_type != "runtime_profile":
        raise ValueError("runtime must be a runtime_profile evidence record")
    if model.record_type != "model_identity":
        raise ValueError("model must be a model_identity evidence record")
    request = _mapping(spec, "spec")
    _reject_unknown_keys(
        request,
        {"schema_version", "comparison_mode", "generation", "execution", "tool_surface"},
        "spec",
    )
    if request.get("schema_version") != CONFIG_SPEC_VERSION:
        raise ValueError(f"spec.schema_version must equal {CONFIG_SPEC_VERSION!r}")
    comparison_mode = request.get("comparison_mode")
    if comparison_mode not in COMPARISON_MODES:
        raise ValueError(f"spec.comparison_mode must be one of {sorted(COMPARISON_MODES)}")
    strict = comparison_mode == "strict"

    generation, generation_defaults = _normalize_generation(request.get("generation"))
    execution, execution_defaults = _normalize_execution(request.get("execution"))
    tool_surface = _normalize_tool_surface(request.get("tool_surface"), strict=strict)
    adapter = _normalize_adapter_resolution(adapter_resolution, strict=strict)

    deviations = list(adapter["deviations"])
    declared_context = model.payload.get("declared_context_tokens")
    if isinstance(declared_context, int) and generation["context_tokens"] > declared_context:
        message = (
            f"requested context {generation['context_tokens']} exceeds model-declared "
            f"context {declared_context}"
        )
        if strict:
            raise ValueError(message)
        deviations.append(message)

    settings = {
        "schema_version": CONFIG_SPEC_VERSION,
        "comparison_mode": comparison_mode,
        "generation": generation,
        "adapter_resolution": {
            **adapter,
            "deviations": deviations,
        },
        "applied_defaults": sorted(generation_defaults + execution_defaults),
    }
    return effective_runtime_config(
        logical_id,
        runtime=runtime.reference,
        model=model.reference,
        settings=settings,
        tool_surface=tool_surface,
        limits=execution,
    )
