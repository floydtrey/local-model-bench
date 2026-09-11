from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


EVIDENCE_SCHEMA_VERSION = "benchmark-lab-evidence:v2"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

RECORD_TYPES = frozenset(
    {
        "host_profile",
        "runtime_profile",
        "model_identity",
        "effective_runtime_config",
        "benchmark_input",
        "evaluator_identity",
        "trial_identity",
        "execution_binding",
        "run_manifest",
        "case_result",
        "evaluation_result",
        "intrinsic_execution_trace",
        "tool_execution_trace",
        "containment_execution",
    }
)


def _require_safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{label} must start with a letter or digit and contain only letters, "
            "digits, dot, underscore, or hyphen (max 128 chars)"
        )
    return value


def _freeze_json(value: Any) -> Any:
    """Recursively freeze already-normalized JSON data for in-memory safety."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Return ordinary JSON-compatible containers from frozen evidence data."""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes suitable for evidence hashing.

    Canonicalization deliberately preserves JSON null values. Unknown measured
    facts therefore remain explicit ``null`` evidence rather than being guessed or
    omitted unpredictably. NaN/Infinity are rejected because they are not portable
    JSON values and would make cross-runtime evidence ambiguous.
    """

    try:
        text = json.dumps(
            _thaw_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON data: {exc}") from exc
    return text.encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class EvidenceRef:
    record_type: str
    logical_id: str
    sha256: str

    def __post_init__(self) -> None:
        if self.record_type not in RECORD_TYPES:
            raise ValueError(f"unsupported evidence record type: {self.record_type!r}")
        _require_safe_id(self.logical_id, "logical_id")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "record_type": self.record_type,
            "logical_id": self.logical_id,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRef":
        if not isinstance(value, Mapping):
            raise ValueError("evidence reference must be an object")
        return cls(
            record_type=str(value.get("record_type", "")),
            logical_id=str(value.get("logical_id", "")),
            sha256=str(value.get("sha256", "")),
        )


@dataclass(frozen=True)
class SealedEvidence:
    """One immutable, content-addressed V2 evidence record.

    ``logical_id`` is an operator/project-facing stable name. ``sha256`` is the
    proof of the exact record type + logical ID + payload bytes. They are kept
    separate so a friendly name, path, model tag, repository URL, or other locator
    can never substitute for cryptographic evidence identity.

    The payload is recursively frozen after validation. Call ``to_dict()`` when a
    mutable JSON-compatible representation is needed for persistence or transport.
    """

    record_type: str
    logical_id: str
    payload: Mapping[str, Any]
    sha256: str
    schema_version: str = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported evidence schema_version: {self.schema_version!r}"
            )
        if self.record_type not in RECORD_TYPES:
            raise ValueError(f"unsupported evidence record type: {self.record_type!r}")
        _require_safe_id(self.logical_id, "logical_id")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")

        normalized = json.loads(canonical_json_bytes(self.payload).decode("utf-8"))
        expected = _evidence_digest(self.record_type, self.logical_id, normalized)
        if self.sha256 != expected:
            raise ValueError(
                f"evidence digest mismatch: expected {expected}, got {self.sha256}"
            )
        object.__setattr__(self, "payload", _freeze_json(normalized))

    @property
    def reference(self) -> EvidenceRef:
        return EvidenceRef(self.record_type, self.logical_id, self.sha256)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_type": self.record_type,
            "logical_id": self.logical_id,
            "sha256": self.sha256,
            "payload": _thaw_json(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SealedEvidence":
        if not isinstance(value, Mapping):
            raise ValueError("sealed evidence must be an object")
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("sealed evidence payload must be an object")
        return cls(
            schema_version=str(value.get("schema_version", "")),
            record_type=str(value.get("record_type", "")),
            logical_id=str(value.get("logical_id", "")),
            sha256=str(value.get("sha256", "")),
            payload=dict(payload),
        )


def _evidence_digest(
    record_type: str, logical_id: str, payload: Mapping[str, Any]
) -> str:
    envelope = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "record_type": record_type,
        "logical_id": logical_id,
        "payload": _thaw_json(payload),
    }
    return sha256_json(envelope)


def seal_evidence(
    record_type: str, logical_id: str, payload: Mapping[str, Any]
) -> SealedEvidence:
    if record_type not in RECORD_TYPES:
        raise ValueError(f"unsupported evidence record type: {record_type!r}")
    _require_safe_id(logical_id, "logical_id")
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")

    # Round-trip through canonical JSON before sealing so caller-owned mutable
    # dictionaries/lists cannot later change the in-memory meaning of the record.
    normalized = json.loads(canonical_json_bytes(dict(payload)).decode("utf-8"))
    digest = _evidence_digest(record_type, logical_id, normalized)
    return SealedEvidence(
        record_type=record_type,
        logical_id=logical_id,
        payload=normalized,
        sha256=digest,
    )
