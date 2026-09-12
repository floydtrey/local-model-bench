from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import EvidenceRef, SealedEvidence, canonical_json_bytes, seal_evidence


COMPATIBILITY_OBSERVATION_VERSION = "benchmark-lab-tool-compatibility-observation:v1"
COMPATIBILITY_DIMENSIONS = (
    "semantic_tool_selection",
    "argument_correctness",
    "protocol_parser_compatibility",
    "end_to_end_success",
)
COMPATIBILITY_STATUSES = frozenset({"pass", "fail", "unknown", "not_applicable"})


def _freeze_json(value: Any) -> Any:
    import json

    normalized = json.loads(canonical_json_bytes(value).decode("utf-8"))

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(normalized)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class CompatibilityDimension:
    status: str
    detail: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in COMPATIBILITY_STATUSES:
            raise ValueError(
                f"compatibility status must be one of {sorted(COMPATIBILITY_STATUSES)}"
            )
        if self.detail is not None and (not isinstance(self.detail, str) or not self.detail):
            raise ValueError("compatibility detail must be a non-empty string or null")
        refs = tuple(self.evidence)
        if any(not isinstance(ref, EvidenceRef) for ref in refs):
            raise ValueError("compatibility evidence must contain EvidenceRef values")
        if len({(ref.record_type, ref.logical_id, ref.sha256) for ref in refs}) != len(refs):
            raise ValueError("compatibility evidence must not contain duplicate references")
        object.__setattr__(self, "evidence", refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "evidence": [ref.to_dict() for ref in self.evidence],
        }


@dataclass(frozen=True)
class ToolCompatibilityObservation:
    """Diagnostic-only tool-compatibility observation.

    This object deliberately has no conversion to ToolCall and no execution hook.
    It may describe semantic intent visible in raw provider output, including cases
    where no structured tool call was produced, but it cannot authorize BL-6 tool
    execution or silently reinterpret assistant prose as an executable call.
    """

    case_id: str
    turn: int
    execution_interface: EvidenceRef
    semantic_tool_selection: CompatibilityDimension
    argument_correctness: CompatibilityDimension
    protocol_parser_compatibility: CompatibilityDimension
    end_to_end_success: CompatibilityDimension
    diagnostic_metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError("case_id must be a non-empty string")
        if not isinstance(self.turn, int) or isinstance(self.turn, bool) or self.turn < 1:
            raise ValueError("turn must be an integer >= 1")
        if not isinstance(self.execution_interface, EvidenceRef):
            raise ValueError("execution_interface must be an EvidenceRef")
        if self.execution_interface.record_type != "execution_interface_identity":
            raise ValueError("execution_interface must reference execution_interface_identity")
        for name in COMPATIBILITY_DIMENSIONS:
            if not isinstance(getattr(self, name), CompatibilityDimension):
                raise ValueError(f"{name} must be CompatibilityDimension")
        if self.diagnostic_metadata is not None:
            if not isinstance(self.diagnostic_metadata, Mapping):
                raise ValueError("diagnostic_metadata must be an object or null")
            object.__setattr__(
                self,
                "diagnostic_metadata",
                _freeze_json(dict(self.diagnostic_metadata)),
            )

    def to_dict(self) -> dict[str, Any]:
        dimensions = {
            name: getattr(self, name).to_dict() for name in COMPATIBILITY_DIMENSIONS
        }
        return {
            "observation_version": COMPATIBILITY_OBSERVATION_VERSION,
            "case_id": self.case_id,
            "turn": self.turn,
            "execution_interface": self.execution_interface.to_dict(),
            "dimensions": dimensions,
            "diagnostic_only": True,
            "execution_authority": "none",
            "diagnostic_metadata": None
            if self.diagnostic_metadata is None
            else _thaw_json(self.diagnostic_metadata),
        }


def compatibility_observation(
    *,
    case_id: str,
    turn: int,
    execution_interface: EvidenceRef,
    semantic_tool_selection: CompatibilityDimension,
    argument_correctness: CompatibilityDimension,
    protocol_parser_compatibility: CompatibilityDimension,
    end_to_end_success: CompatibilityDimension,
    diagnostic_metadata: Mapping[str, Any] | None = None,
) -> ToolCompatibilityObservation:
    return ToolCompatibilityObservation(
        case_id=case_id,
        turn=turn,
        execution_interface=execution_interface,
        semantic_tool_selection=semantic_tool_selection,
        argument_correctness=argument_correctness,
        protocol_parser_compatibility=protocol_parser_compatibility,
        end_to_end_success=end_to_end_success,
        diagnostic_metadata=diagnostic_metadata,
    )


def seal_compatibility_observation(
    logical_id: str, observation: ToolCompatibilityObservation
) -> SealedEvidence:
    """Seal one diagnostic observation without granting any execution authority."""

    if not isinstance(observation, ToolCompatibilityObservation):
        raise TypeError("observation must be a ToolCompatibilityObservation")
    evidence = seal_evidence(
        "tool_compatibility_observation",
        logical_id,
        observation.to_dict(),
    )
    validate_compatibility_observation_evidence(evidence)
    return evidence


def validate_compatibility_observation_evidence(evidence: SealedEvidence) -> None:
    if not isinstance(evidence, SealedEvidence):
        raise TypeError("evidence must be SealedEvidence")
    if evidence.record_type != "tool_compatibility_observation":
        raise ValueError("expected tool_compatibility_observation evidence")
    payload = evidence.payload
    if payload.get("observation_version") != COMPATIBILITY_OBSERVATION_VERSION:
        raise ValueError("unsupported compatibility observation version")
    if payload.get("diagnostic_only") is not True:
        raise ValueError("compatibility observation must remain diagnostic-only")
    if payload.get("execution_authority") != "none":
        raise ValueError("compatibility observation must have no execution authority")
    interface = payload.get("execution_interface")
    if not isinstance(interface, Mapping):
        raise ValueError("compatibility observation execution interface is missing")
    if interface.get("record_type") != "execution_interface_identity":
        raise ValueError("compatibility observation interface reference type is invalid")
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise ValueError("compatibility observation dimensions are missing")
    if set(dimensions) != set(COMPATIBILITY_DIMENSIONS):
        raise ValueError("compatibility observation dimensions are not canonical")
    for name in COMPATIBILITY_DIMENSIONS:
        dimension = dimensions.get(name)
        if not isinstance(dimension, Mapping):
            raise ValueError(f"compatibility dimension {name} must be an object")
        if dimension.get("status") not in COMPATIBILITY_STATUSES:
            raise ValueError(f"compatibility dimension {name} has invalid status")
        refs = dimension.get("evidence")
        if not isinstance(refs, (list, tuple)):
            raise ValueError(f"compatibility dimension {name} evidence must be an array")
        for ref in refs:
            EvidenceRef.from_dict(ref)
