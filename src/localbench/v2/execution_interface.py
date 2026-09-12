from __future__ import annotations

from typing import Any, Mapping

from .contracts import EvidenceRef, SealedEvidence, seal_evidence


EXECUTION_INTERFACE_VERSION = "benchmark-lab-execution-interface:v1"
NORMALIZED_TOOL_CALL_CONTRACT = "benchmark-lab-normalized-tool-call:v1"
TOOL_TRANSPORT_MODES = frozenset(
    {
        "native_structured",
        "model_aware_structured",
        "prompt_parsed",
        "unavailable",
    }
)
PARSER_MODES = frozenset({"provider_native", "model_aware", "prompt_based", "none"})
MALFORMED_CALL_POLICIES = frozenset({"fail_closed"})
BACKEND_TOOL_EXECUTION_POLICIES = frozenset({"forbidden"})


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _reference(
    value: EvidenceRef | Mapping[str, Any], expected_type: str, label: str
) -> dict[str, str]:
    reference = value if isinstance(value, EvidenceRef) else EvidenceRef.from_dict(value)
    if reference.record_type != expected_type:
        raise ValueError(
            f"{label} must reference {expected_type!r}, got {reference.record_type!r}"
        )
    return reference.to_dict()


def execution_interface_identity(
    logical_id: str,
    *,
    runtime: EvidenceRef | Mapping[str, Any],
    model: EvidenceRef | Mapping[str, Any],
    backend_kind: str,
    adapter_id: str,
    tool_transport_mode: str,
    parser_mode: str,
    parser_id: str | None,
    raw_interaction_contract: str,
    capabilities: Mapping[str, Any],
    malformed_call_policy: str = "fail_closed",
    backend_tool_execution: str = "forbidden",
) -> SealedEvidence:
    """Seal the exact runtime/parser interface used for one qualification path.

    This identity is intentionally separate from model identity. A model may be
    tested through several execution interfaces while BL-6 keeps the same authority,
    workspace, normalized ``ToolCall`` contract, and deterministic evaluator.

    The contract is fail-closed: this layer may normalize a provider/model response,
    but it may never execute a tool or expand authority itself.
    """

    backend_kind = _nonempty_string(backend_kind, "backend_kind")
    adapter_id = _nonempty_string(adapter_id, "adapter_id")
    raw_interaction_contract = _nonempty_string(
        raw_interaction_contract, "raw_interaction_contract"
    )

    if tool_transport_mode not in TOOL_TRANSPORT_MODES:
        raise ValueError(
            f"tool_transport_mode must be one of {sorted(TOOL_TRANSPORT_MODES)}"
        )
    if parser_mode not in PARSER_MODES:
        raise ValueError(f"parser_mode must be one of {sorted(PARSER_MODES)}")
    if malformed_call_policy not in MALFORMED_CALL_POLICIES:
        raise ValueError("malformed_call_policy must be fail_closed")
    if backend_tool_execution not in BACKEND_TOOL_EXECUTION_POLICIES:
        raise ValueError("backend_tool_execution must be forbidden")

    if parser_id is not None:
        parser_id = _nonempty_string(parser_id, "parser_id")

    if parser_mode == "none":
        if parser_id is not None:
            raise ValueError("parser_id must be null when parser_mode is none")
        if tool_transport_mode != "unavailable":
            raise ValueError(
                "parser_mode none is valid only when tool_transport_mode is unavailable"
            )
    else:
        if parser_id is None:
            raise ValueError("parser_id is required when parser_mode is not none")
        if tool_transport_mode == "unavailable":
            raise ValueError(
                "tool_transport_mode unavailable requires parser_mode none"
            )

    if parser_mode == "prompt_based" and tool_transport_mode != "prompt_parsed":
        raise ValueError("prompt_based parser_mode requires prompt_parsed transport")
    if tool_transport_mode == "prompt_parsed" and parser_mode != "prompt_based":
        raise ValueError("prompt_parsed transport requires prompt_based parser_mode")

    payload = {
        "interface_version": EXECUTION_INTERFACE_VERSION,
        "runtime": _reference(runtime, "runtime_profile", "runtime"),
        "model": _reference(model, "model_identity", "model"),
        "backend_kind": backend_kind,
        "adapter_id": adapter_id,
        "tool_transport_mode": tool_transport_mode,
        "parser_mode": parser_mode,
        "parser_id": parser_id,
        "raw_interaction_contract": raw_interaction_contract,
        "normalized_tool_call_contract": NORMALIZED_TOOL_CALL_CONTRACT,
        "capabilities": _object(capabilities, "capabilities"),
        "malformed_call_policy": malformed_call_policy,
        "backend_tool_execution": backend_tool_execution,
    }
    return seal_evidence("execution_interface_identity", logical_id, payload)


def validate_execution_interface_identity(record: SealedEvidence) -> None:
    """Fail closed if a sealed interface record violates the MI-1 contract."""

    if not isinstance(record, SealedEvidence) or record.record_type != "execution_interface_identity":
        raise ValueError("expected execution_interface_identity evidence")
    payload = record.payload
    if payload.get("interface_version") != EXECUTION_INTERFACE_VERSION:
        raise ValueError("unsupported execution interface version")
    if payload.get("normalized_tool_call_contract") != NORMALIZED_TOOL_CALL_CONTRACT:
        raise ValueError("execution interface normalized tool-call contract mismatch")

    rebuilt = execution_interface_identity(
        record.logical_id,
        runtime=payload.get("runtime"),
        model=payload.get("model"),
        backend_kind=payload.get("backend_kind"),
        adapter_id=payload.get("adapter_id"),
        tool_transport_mode=payload.get("tool_transport_mode"),
        parser_mode=payload.get("parser_mode"),
        parser_id=payload.get("parser_id"),
        raw_interaction_contract=payload.get("raw_interaction_contract"),
        capabilities=payload.get("capabilities"),
        malformed_call_policy=payload.get("malformed_call_policy"),
        backend_tool_execution=payload.get("backend_tool_execution"),
    )
    if rebuilt.reference != record.reference:
        raise ValueError("execution interface identity is not canonical")
