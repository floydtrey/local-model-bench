from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..util import validate_id
from .contracts import RECORD_TYPES, EvidenceRef, SealedEvidence, canonical_json_bytes, sha256_json
from .records import EVALUATION_VERDICTS, evaluation_result, evaluator_identity


EVALUATOR_SPEC_VERSION = "benchmark-lab-evaluator:v2"
SCORING_MODES = frozenset({"weighted", "unscored"})


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return number


@dataclass(frozen=True)
class EvidenceConsumption:
    record_type: str
    required: bool = True
    multiple: bool = False

    def __post_init__(self) -> None:
        if self.record_type not in RECORD_TYPES:
            raise ValueError(f"unsupported consumed evidence record type: {self.record_type!r}")
        if not isinstance(self.required, bool) or not isinstance(self.multiple, bool):
            raise ValueError("required and multiple must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "required": self.required,
            "multiple": self.multiple,
        }


@dataclass(frozen=True)
class EvaluatorDefinition:
    evaluator_id: str
    contract_version: str
    implementation_sha256: str
    input_contract: str
    result_contract: str
    consumed_evidence: tuple[EvidenceConsumption, ...]
    requires_human_review: bool
    scoring_mode: str = "weighted"
    schema_version: str = EVALUATOR_SPEC_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVALUATOR_SPEC_VERSION:
            raise ValueError(f"unsupported evaluator schema_version: {self.schema_version!r}")
        validate_id(self.evaluator_id, "evaluator_id")
        validate_id(self.contract_version, "contract_version")
        _sha256(self.implementation_sha256, "implementation_sha256")
        _nonempty_string(self.input_contract, "input_contract")
        _nonempty_string(self.result_contract, "result_contract")
        if self.scoring_mode not in SCORING_MODES:
            raise ValueError(f"scoring_mode must be one of {sorted(SCORING_MODES)}")
        if not isinstance(self.requires_human_review, bool):
            raise ValueError("requires_human_review must be boolean")
        if not isinstance(self.consumed_evidence, tuple) or not self.consumed_evidence:
            raise ValueError("consumed_evidence must be a non-empty tuple")
        if any(not isinstance(item, EvidenceConsumption) for item in self.consumed_evidence):
            raise ValueError("consumed_evidence must contain EvidenceConsumption values")
        types = [item.record_type for item in self.consumed_evidence]
        if len(types) != len(set(types)):
            raise ValueError("consumed_evidence must not repeat record types")
        case_contract = next(
            (item for item in self.consumed_evidence if item.record_type == "case_result"),
            None,
        )
        if case_contract is None or not case_contract.required or case_contract.multiple:
            raise ValueError(
                "every evaluator must consume exactly one required case_result"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluator_id": self.evaluator_id,
            "contract_version": self.contract_version,
            "implementation_sha256": self.implementation_sha256,
            "input_contract": self.input_contract,
            "result_contract": self.result_contract,
            "consumed_evidence": [item.to_dict() for item in self.consumed_evidence],
            "requires_human_review": self.requires_human_review,
            "scoring_mode": self.scoring_mode,
        }

    @property
    def definition_sha256(self) -> str:
        return sha256_json(self.to_dict())

    @property
    def identity(self) -> SealedEvidence:
        # The logical ID is content-addressed by the complete evaluator definition.
        # The existing evaluator_identity payload separately preserves the exact
        # implementation source digest, public ID/version, result contract, and
        # human-review policy. Together they bind both implementation and declared
        # evaluator behavior without changing the already-accepted BL-2 record type.
        return evaluator_identity(
            f"eval-{self.definition_sha256}",
            evaluator_id=self.evaluator_id,
            version=self.contract_version,
            implementation_sha256=self.implementation_sha256,
            result_contract=self.result_contract,
            requires_human_review=self.requires_human_review,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluatorDefinition":
        if not isinstance(value, Mapping):
            raise ValueError("evaluator definition must be an object")
        allowed = {
            "schema_version",
            "evaluator_id",
            "contract_version",
            "implementation_sha256",
            "input_contract",
            "result_contract",
            "consumed_evidence",
            "requires_human_review",
            "scoring_mode",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"evaluator definition has unknown fields: {unknown}")
        raw_consumed = value.get("consumed_evidence")
        if not isinstance(raw_consumed, Sequence) or isinstance(
            raw_consumed, (str, bytes, bytearray)
        ):
            raise ValueError("consumed_evidence must be an array")
        consumed: list[EvidenceConsumption] = []
        for index, item in enumerate(raw_consumed):
            if not isinstance(item, Mapping):
                raise ValueError(f"consumed_evidence[{index}] must be an object")
            unknown_item = sorted(set(item) - {"record_type", "required", "multiple"})
            if unknown_item:
                raise ValueError(
                    f"consumed_evidence[{index}] has unknown fields: {unknown_item}"
                )
            consumed.append(
                EvidenceConsumption(
                    record_type=str(item.get("record_type", "")),
                    required=item.get("required", True),
                    multiple=item.get("multiple", False),
                )
            )
        return cls(
            schema_version=str(value.get("schema_version", "")),
            evaluator_id=str(value.get("evaluator_id", "")),
            contract_version=str(value.get("contract_version", "")),
            implementation_sha256=str(value.get("implementation_sha256", "")),
            input_contract=str(value.get("input_contract", "")),
            result_contract=str(value.get("result_contract", "")),
            consumed_evidence=tuple(consumed),
            requires_human_review=value.get("requires_human_review"),
            scoring_mode=str(value.get("scoring_mode", "")),
        )


@dataclass(frozen=True)
class EvaluationCheck:
    check_id: str
    passed: bool
    weight: float
    earned: float
    detail: str
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.check_id, "check_id")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be boolean")
        weight = _number(self.weight, "weight")
        earned = _number(self.earned, "earned")
        if earned > weight:
            raise ValueError("earned cannot exceed weight")
        _nonempty_string(self.detail, "detail")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, EvidenceRef) for item in self.evidence
        ):
            raise ValueError("evidence must be a tuple of EvidenceRef values")
        object.__setattr__(self, "weight", weight)
        object.__setattr__(self, "earned", earned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "passed": self.passed,
            "weight": self.weight,
            "earned": self.earned,
            "detail": self.detail,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class EvaluationDraft:
    verdict: str
    checks: tuple[EvaluationCheck, ...]
    hard_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in EVALUATION_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(EVALUATION_VERDICTS)}")
        if not isinstance(self.checks, tuple) or any(
            not isinstance(item, EvaluationCheck) for item in self.checks
        ):
            raise ValueError("checks must be a tuple of EvaluationCheck values")
        ids = [item.check_id for item in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("checks must not repeat check_id values")
        if not isinstance(self.hard_failures, tuple):
            raise ValueError("hard_failures must be a tuple")
        normalized: list[str] = []
        for index, item in enumerate(self.hard_failures):
            normalized.append(validate_id(item, f"hard_failures[{index}]"))
        if len(normalized) != len(set(normalized)):
            raise ValueError("hard_failures must not contain duplicates")
        object.__setattr__(self, "hard_failures", tuple(normalized))


@dataclass(frozen=True)
class EvaluationContext:
    case_definition: Mapping[str, Any]
    case_result: SealedEvidence
    evidence_by_type: Mapping[str, tuple[SealedEvidence, ...]]
    hard_failure_rules: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.case_definition, Mapping):
            raise ValueError("case_definition must be an object")
        if not isinstance(self.case_result, SealedEvidence) or self.case_result.record_type != "case_result":
            raise ValueError("case_result must be sealed case_result evidence")
        object.__setattr__(self, "case_definition", _freeze_json(self.case_definition))
        frozen_evidence = MappingProxyType(
            {
                record_type: tuple(records)
                for record_type, records in self.evidence_by_type.items()
            }
        )
        object.__setattr__(self, "evidence_by_type", frozen_evidence)


EvaluatorImplementation = Callable[[EvaluationContext], EvaluationDraft]


@dataclass(frozen=True)
class _RegisteredEvaluator:
    definition: EvaluatorDefinition
    implementation: EvaluatorImplementation


class EvaluatorRegistry:
    """Fail-closed registry and execution boundary for deterministic evaluators."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _RegisteredEvaluator] = {}

    def register(
        self,
        definition: EvaluatorDefinition,
        implementation: EvaluatorImplementation,
    ) -> None:
        if not isinstance(definition, EvaluatorDefinition):
            raise ValueError("definition must be an EvaluatorDefinition")
        if not callable(implementation):
            raise ValueError("implementation must be callable")
        key = (definition.evaluator_id, definition.contract_version)
        if key in self._entries:
            raise ValueError(
                f"evaluator already registered: {definition.evaluator_id}@{definition.contract_version}"
            )
        self._entries[key] = _RegisteredEvaluator(definition, implementation)

    def resolve(self, evaluator_id: str, contract_version: str) -> EvaluatorDefinition:
        validate_id(evaluator_id, "evaluator_id")
        validate_id(contract_version, "contract_version")
        entry = self._entries.get((evaluator_id, contract_version))
        if entry is None:
            raise KeyError(f"unregistered evaluator: {evaluator_id}@{contract_version}")
        return entry.definition

    def identities(self) -> tuple[SealedEvidence, ...]:
        return tuple(
            entry.definition.identity
            for _, entry in sorted(self._entries.items())
        )

    def evaluate(
        self,
        logical_id: str,
        *,
        evaluator_id: str,
        contract_version: str,
        case_definition: Mapping[str, Any],
        case_result_record: SealedEvidence,
        supplemental_evidence: Iterable[SealedEvidence] = (),
    ) -> SealedEvidence:
        validate_id(logical_id, "logical_id")
        key = (evaluator_id, contract_version)
        entry = self._entries.get(key)
        if entry is None:
            raise KeyError(f"unregistered evaluator: {evaluator_id}@{contract_version}")
        definition = entry.definition

        if not isinstance(case_result_record, SealedEvidence) or case_result_record.record_type != "case_result":
            raise ValueError("case_result_record must be sealed case_result evidence")
        if not isinstance(case_definition, Mapping):
            raise ValueError("case_definition must be an object")
        case_id = case_definition.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_definition.case_id must be a non-empty string")
        if case_result_record.payload.get("case_id") != case_id:
            raise ValueError("case definition and CaseResult case_id do not match")

        evaluator_bindings = case_definition.get("evaluators")
        if not isinstance(evaluator_bindings, Sequence) or isinstance(
            evaluator_bindings, (str, bytes, bytearray)
        ):
            raise ValueError("case_definition.evaluators must be an array")
        exact_binding = False
        for index, binding in enumerate(evaluator_bindings):
            if not isinstance(binding, Mapping):
                raise ValueError(f"case_definition.evaluators[{index}] must be an object")
            if (
                binding.get("evaluator_id") == evaluator_id
                and binding.get("contract_version") == contract_version
            ):
                exact_binding = True
        if not exact_binding:
            raise ValueError(
                f"case does not bind evaluator {evaluator_id}@{contract_version}"
            )

        hard_failure_bindings = case_definition.get("hard_failure_rules")
        if not isinstance(hard_failure_bindings, Sequence) or isinstance(
            hard_failure_bindings, (str, bytes, bytearray)
        ):
            raise ValueError("case_definition.hard_failure_rules must be an array")
        allowed_rules: list[str] = []
        for index, binding in enumerate(hard_failure_bindings):
            if not isinstance(binding, Mapping):
                raise ValueError(
                    f"case_definition.hard_failure_rules[{index}] must be an object"
                )
            if binding.get("evaluator_id") == evaluator_id:
                rule_id = validate_id(
                    binding.get("rule_id"),
                    f"case_definition.hard_failure_rules[{index}].rule_id",
                )
                allowed_rules.append(rule_id)
        if len(allowed_rules) != len(set(allowed_rules)):
            raise ValueError(
                f"case repeats hard-failure rules for evaluator {evaluator_id!r}"
            )

        declared = {item.record_type: item for item in definition.consumed_evidence}
        grouped: dict[str, list[SealedEvidence]] = {"case_result": [case_result_record]}
        for item in supplemental_evidence:
            if not isinstance(item, SealedEvidence):
                raise ValueError("supplemental_evidence must contain SealedEvidence values")
            contract = declared.get(item.record_type)
            if contract is None:
                raise ValueError(
                    f"evaluator did not declare consumption of {item.record_type!r} evidence"
                )
            grouped.setdefault(item.record_type, []).append(item)

        for record_type, contract in declared.items():
            records = grouped.get(record_type, [])
            if contract.required and not records:
                raise ValueError(f"required evaluator evidence is missing: {record_type}")
            if not contract.multiple and len(records) > 1:
                raise ValueError(
                    f"evaluator allows at most one {record_type} record, got {len(records)}"
                )

        context = EvaluationContext(
            case_definition=case_definition,
            case_result=case_result_record,
            evidence_by_type={key: tuple(value) for key, value in grouped.items()},
            hard_failure_rules=tuple(allowed_rules),
        )
        draft = entry.implementation(context)
        if not isinstance(draft, EvaluationDraft):
            raise ValueError("evaluator implementation must return EvaluationDraft")

        undeclared_failures = sorted(set(draft.hard_failures) - set(allowed_rules))
        if undeclared_failures:
            raise ValueError(
                f"evaluator emitted undeclared hard-failure rules: {undeclared_failures}"
            )
        if draft.hard_failures and draft.verdict != "fail":
            raise ValueError("hard failures require verdict='fail'")
        if definition.requires_human_review and draft.verdict == "pass":
            raise ValueError(
                "evaluator requiring human review cannot emit a final pass verdict"
            )

        checks = [item.to_dict() for item in draft.checks]
        if definition.scoring_mode == "weighted":
            score = sum(item.earned for item in draft.checks)
            maximum = sum(item.weight for item in draft.checks)
            if maximum <= 0:
                raise ValueError("weighted evaluator must define positive total check weight")
        else:
            if any(item.weight != 0 or item.earned != 0 for item in draft.checks):
                raise ValueError("unscored evaluator checks must have zero weight and earned points")
            score = None
            maximum = None

        return evaluation_result(
            logical_id,
            case=case_result_record.reference,
            evaluator=definition.identity.reference,
            verdict=draft.verdict,
            score=score,
            maximum_score=maximum,
            hard_failures=draft.hard_failures,
            checks=checks,
        )


def definition_sha256(value: Mapping[str, Any]) -> str:
    """Hash a serialized evaluator definition without registering or executing it."""

    definition = EvaluatorDefinition.from_mapping(value)
    return definition.definition_sha256


def canonical_definition_bytes(value: Mapping[str, Any]) -> bytes:
    """Return canonical bytes for tooling that stores evaluator definitions externally."""

    definition = EvaluatorDefinition.from_mapping(value)
    return canonical_json_bytes(definition.to_dict())
