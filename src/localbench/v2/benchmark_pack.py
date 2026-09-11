from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..util import sha256_bytes, validate_id
from .contracts import canonical_json_bytes, sha256_json
from .records import benchmark_input


PACK_SCHEMA_VERSION = "benchmark-lab-pack:v2"
CAPABILITY_LEVELS = frozenset({"L0", "L1", "L2", "L3", "L4"})
RESPONSE_MODES = frozenset({"text", "json_object", "json_schema"})
ASSET_DELIVERY_MODES = frozenset({"inline_context", "readonly_reference"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array")
    return list(value)


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {unknown}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _nullable_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, label)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be an integer >= 1")
    return value


def _nullable_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, label)


def _safe_id(value: Any, label: str) -> str:
    return validate_id(value, label)


def _safe_id_list(value: Any, label: str) -> list[str]:
    items = _array(value, label)
    result = [_safe_id(item, f"{label}[{index}]") for index, item in enumerate(items)]
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must not contain duplicates")
    return result


def _normalize_message(value: Any, label: str) -> dict[str, str]:
    message = _object(value, label)
    _reject_unknown(message, {"role", "content"}, label)
    role = message.get("role")
    if role not in {"system", "user", "assistant"}:
        raise ValueError(f"{label}.role must be system, user, or assistant")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError(f"{label}.content must be a string")
    return {"role": role, "content": content}


def _normalize_asset(value: Any, label: str) -> dict[str, Any]:
    asset = _object(value, label)
    _reject_unknown(
        asset,
        {"asset_id", "sha256", "media_type", "delivery", "source_locator"},
        label,
    )
    asset_id = _safe_id(asset.get("asset_id"), f"{label}.asset_id")
    digest = asset.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(f"{label}.sha256 must be a lowercase SHA-256 digest")
    media_type = _nonempty_string(asset.get("media_type"), f"{label}.media_type")
    delivery = asset.get("delivery")
    if delivery not in ASSET_DELIVERY_MODES:
        raise ValueError(
            f"{label}.delivery must be one of {sorted(ASSET_DELIVERY_MODES)}"
        )
    locator = _nullable_string(asset.get("source_locator"), f"{label}.source_locator")
    if locator is None:
        raise ValueError(
            f"{label}.source_locator must locate the fixture bytes; sha256 remains their identity"
        )
    return {
        "asset_id": asset_id,
        "sha256": digest,
        "media_type": media_type,
        "delivery": delivery,
        "source_locator": locator,
    }


def _normalize_input(value: Any, label: str) -> dict[str, Any]:
    case_input = _object(value, label)
    _reject_unknown(case_input, {"messages", "context_assets"}, label)
    messages = _array(case_input.get("messages"), f"{label}.messages")
    if not messages:
        raise ValueError(f"{label}.messages must not be empty")
    normalized_messages = [
        _normalize_message(message, f"{label}.messages[{index}]")
        for index, message in enumerate(messages)
    ]
    assets = _array(case_input.get("context_assets", []), f"{label}.context_assets")
    normalized_assets = [
        _normalize_asset(asset, f"{label}.context_assets[{index}]")
        for index, asset in enumerate(assets)
    ]
    asset_ids = [asset["asset_id"] for asset in normalized_assets]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError(f"{label}.context_assets contains duplicate asset_id values")
    return {"messages": normalized_messages, "context_assets": normalized_assets}


def _normalize_response_contract(value: Any, label: str) -> dict[str, Any]:
    response = _object(value, label)
    _reject_unknown(response, {"mode", "schema"}, label)
    mode = response.get("mode")
    if mode not in RESPONSE_MODES:
        raise ValueError(f"{label}.mode must be one of {sorted(RESPONSE_MODES)}")
    schema = response.get("schema")
    if mode == "json_schema":
        if not isinstance(schema, Mapping):
            raise ValueError(f"{label}.schema must be an object for json_schema mode")
        schema = dict(schema)
    elif schema is not None:
        raise ValueError(f"{label}.schema is only valid for json_schema mode")
    return {"mode": mode, "schema": schema}


def _normalize_tool_surface(value: Any, label: str) -> dict[str, Any]:
    surface = _object(value, label)
    _reject_unknown(surface, {"id", "required_tools"}, label)
    surface_id = _safe_id(surface.get("id"), f"{label}.id")
    tools = _safe_id_list(surface.get("required_tools"), f"{label}.required_tools")
    if surface_id == "none" and tools:
        raise ValueError(f"{label} with id='none' cannot require tools")
    if surface_id != "none" and not tools:
        raise ValueError(f"{label} with a tool surface must name at least one required tool")
    return {"id": surface_id, "required_tools": tools}


def _normalize_requirements(value: Any, label: str) -> dict[str, Any]:
    requirements = _object(value, label)
    _reject_unknown(
        requirements,
        {
            "configuration_profile",
            "response_contract",
            "tool_surface",
            "minimum_context_tokens",
        },
        label,
    )
    return {
        "configuration_profile": _safe_id(
            requirements.get("configuration_profile"),
            f"{label}.configuration_profile",
        ),
        "response_contract": _normalize_response_contract(
            requirements.get("response_contract"), f"{label}.response_contract"
        ),
        "tool_surface": _normalize_tool_surface(
            requirements.get("tool_surface"), f"{label}.tool_surface"
        ),
        "minimum_context_tokens": _nullable_positive_int(
            requirements.get("minimum_context_tokens"),
            f"{label}.minimum_context_tokens",
        ),
    }


def _normalize_evaluator_ref(value: Any, label: str) -> dict[str, str]:
    evaluator = _object(value, label)
    _reject_unknown(evaluator, {"evaluator_id", "contract_version"}, label)
    return {
        "evaluator_id": _safe_id(evaluator.get("evaluator_id"), f"{label}.evaluator_id"),
        "contract_version": _safe_id(
            evaluator.get("contract_version"), f"{label}.contract_version"
        ),
    }


def _normalize_hard_failure(value: Any, label: str) -> dict[str, str]:
    rule = _object(value, label)
    _reject_unknown(rule, {"evaluator_id", "rule_id"}, label)
    return {
        "evaluator_id": _safe_id(rule.get("evaluator_id"), f"{label}.evaluator_id"),
        "rule_id": _safe_id(rule.get("rule_id"), f"{label}.rule_id"),
    }


def _normalize_repetitions(value: Any, label: str) -> dict[str, int]:
    repetitions = _object(value, label)
    _reject_unknown(repetitions, {"screen_trials", "qualification_trials"}, label)
    screen = _positive_int(repetitions.get("screen_trials"), f"{label}.screen_trials")
    qualification = _positive_int(
        repetitions.get("qualification_trials"), f"{label}.qualification_trials"
    )
    if qualification < screen:
        raise ValueError(f"{label}.qualification_trials must be >= screen_trials")
    return {"screen_trials": screen, "qualification_trials": qualification}


def _normalize_case(value: Any, *, level: str, index: int) -> dict[str, Any]:
    label = f"cases[{index}]"
    case = _object(value, label)
    _reject_unknown(
        case,
        {
            "case_id",
            "objective",
            "input",
            "requirements",
            "evaluators",
            "hard_failure_rules",
            "repetitions",
            "tags",
        },
        label,
    )
    case_id = _safe_id(case.get("case_id"), f"{label}.case_id")
    case_input = _normalize_input(case.get("input"), f"{label}.input")
    requirements = _normalize_requirements(case.get("requirements"), f"{label}.requirements")

    if level == "L0" and case_input["context_assets"]:
        raise ValueError(f"{label}: L0 cases cannot declare context assets")
    if level in {"L0", "L1"} and requirements["tool_surface"]["id"] != "none":
        raise ValueError(f"{label}: {level} cases cannot require a tool surface")

    evaluators_raw = _array(case.get("evaluators"), f"{label}.evaluators")
    if not evaluators_raw:
        raise ValueError(f"{label}.evaluators must not be empty")
    evaluators = [
        _normalize_evaluator_ref(item, f"{label}.evaluators[{i}]")
        for i, item in enumerate(evaluators_raw)
    ]
    evaluator_ids = [item["evaluator_id"] for item in evaluators]
    if len(evaluator_ids) != len(set(evaluator_ids)):
        raise ValueError(f"{label}.evaluators must not repeat evaluator_id values")

    failures_raw = _array(
        case.get("hard_failure_rules", []), f"{label}.hard_failure_rules"
    )
    failures = [
        _normalize_hard_failure(item, f"{label}.hard_failure_rules[{i}]")
        for i, item in enumerate(failures_raw)
    ]
    failure_keys = [(item["evaluator_id"], item["rule_id"]) for item in failures]
    if len(failure_keys) != len(set(failure_keys)):
        raise ValueError(f"{label}.hard_failure_rules must not contain duplicates")
    unknown_evaluators = sorted(
        {item["evaluator_id"] for item in failures} - set(evaluator_ids)
    )
    if unknown_evaluators:
        raise ValueError(
            f"{label}.hard_failure_rules reference undeclared evaluators: {unknown_evaluators}"
        )

    return {
        "case_id": case_id,
        "objective": _nonempty_string(case.get("objective"), f"{label}.objective"),
        "input": case_input,
        "requirements": requirements,
        "evaluators": evaluators,
        "hard_failure_rules": failures,
        "repetitions": _normalize_repetitions(
            case.get("repetitions"), f"{label}.repetitions"
        ),
        "tags": _safe_id_list(case.get("tags", []), f"{label}.tags"),
    }


def _semantic_projection(normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Return behavior-bearing pack content independent of locator/reporting metadata."""

    projection = _thaw_json(normalized)
    projection.pop("name", None)
    projection.pop("description", None)
    for case in projection["cases"]:
        case.pop("tags", None)
        for asset in case["input"]["context_assets"]:
            asset.pop("source_locator", None)
    return projection


@dataclass(frozen=True)
class BenchmarkPack:
    pack_id: str
    pack_version: str
    name: str
    level: str
    description: str | None
    cases: tuple[Mapping[str, Any], ...]
    source_sha256: str
    semantic_sha256: str
    schema_version: str = PACK_SCHEMA_VERSION

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(str(case["case_id"]) for case in self.cases)

    def case(self, case_id: str) -> Mapping[str, Any]:
        _safe_id(case_id, "case_id")
        for case in self.cases:
            if case["case_id"] == case_id:
                return case
        raise KeyError(case_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "cases": [_thaw_json(case) for case in self.cases],
        }

    def to_benchmark_input(self, *, source_locator: str | None = None):
        locator = _nullable_string(source_locator, "source_locator")
        return benchmark_input(
            self.pack_id,
            suite_id=f"{self.pack_id}@{self.pack_version}",
            source_sha256=self.source_sha256,
            level=self.level,
            case_ids=self.case_ids,
            source_format=PACK_SCHEMA_VERSION,
            source_locator=locator,
        )


def parse_benchmark_pack(data: bytes) -> BenchmarkPack:
    if not isinstance(data, bytes):
        raise ValueError("benchmark pack source must be bytes")
    source_digest = sha256_bytes(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("benchmark pack must be UTF-8 JSON") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"benchmark pack is not valid JSON: {exc}") from exc
    root = _object(raw, "benchmark pack")
    _reject_unknown(
        root,
        {
            "schema_version",
            "pack_id",
            "pack_version",
            "name",
            "description",
            "level",
            "cases",
        },
        "benchmark pack",
    )
    if root.get("schema_version") != PACK_SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {PACK_SCHEMA_VERSION!r}")
    pack_id = _safe_id(root.get("pack_id"), "pack_id")
    pack_version = _safe_id(root.get("pack_version"), "pack_version")
    name = _nonempty_string(root.get("name"), "name")
    description = _nullable_string(root.get("description"), "description")
    level = root.get("level")
    if level not in CAPABILITY_LEVELS:
        raise ValueError(f"level must be one of {sorted(CAPABILITY_LEVELS)}")
    raw_cases = _array(root.get("cases"), "cases")
    if not raw_cases:
        raise ValueError("cases must not be empty")
    normalized_cases = [
        _normalize_case(case, level=level, index=index)
        for index, case in enumerate(raw_cases)
    ]
    case_ids = [case["case_id"] for case in normalized_cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("cases must not contain duplicate case_id values")

    normalized = {
        "schema_version": PACK_SCHEMA_VERSION,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "name": name,
        "description": description,
        "level": level,
        "cases": normalized_cases,
    }
    # Canonical round-trip rejects NaN/Infinity and strips caller-owned mutability.
    canonical = json.loads(canonical_json_bytes(normalized).decode("utf-8"))
    semantic_digest = sha256_json(_semantic_projection(canonical))
    return BenchmarkPack(
        pack_id=pack_id,
        pack_version=pack_version,
        name=name,
        level=level,
        description=description,
        cases=tuple(_freeze_json(case) for case in canonical["cases"]),
        source_sha256=source_digest,
        semantic_sha256=semantic_digest,
    )


def load_benchmark_pack(path: Path) -> BenchmarkPack:
    path = path.resolve()
    return parse_benchmark_pack(path.read_bytes())
