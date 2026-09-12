from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


TOOL_CALL_NORMALIZER_VERSION = "benchmark-lab-tool-call-normalizer:v1"
DEFAULT_MAX_CONTENT_BYTES = 1_048_576
DEFAULT_MAX_CALLS = 32
DEFAULT_MAX_JSON_DEPTH = 64


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class NormalizeStatus(str, Enum):
    NORMALIZED = "normalized"
    NOT_TOOL_CALL = "not_tool_call"
    INVALID_TOOL_CALL = "invalid_tool_call"
    UNKNOWN_MODEL = "unknown_model"


@dataclass(frozen=True)
class CanonicalToolCall:
    name: str
    arguments: Mapping[str, Any]
    call_id: str | None = None
    source_format: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": dict(self.arguments),
            "call_id": self.call_id,
            "source_format": self.source_format,
        }


@dataclass(frozen=True)
class NormalizationResult:
    status: NormalizeStatus
    calls: tuple[CanonicalToolCall, ...] = ()
    source_format: str | None = None
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is NormalizeStatus.NORMALIZED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "source_format": self.source_format,
            "calls": [call.to_dict() for call in self.calls],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class TransportProfile:
    name: str
    allowed_formats: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allowed_formats": list(self.allowed_formats),
            "normalizer_version": TOOL_CALL_NORMALIZER_VERSION,
        }

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


OPENAI_NATIVE = TransportProfile("openai_native", ("openai_native",))
QWEN_CANONICAL = TransportProfile(
    "qwen_canonical", ("openai_native", "tool_call_xml")
)
QWEN_25_COMPAT = TransportProfile(
    "qwen_25_compat",
    (
        "openai_native",
        "tool_call_xml",
        "function_call_xml",
        "tools_xml",
        "fenced_json",
        "plain_json",
    ),
)
FUNCTION_XML = TransportProfile(
    "function_xml", ("openai_native", "function_call_xml")
)
JSON_CALL = TransportProfile(
    "json_call", ("openai_native", "fenced_json", "plain_json")
)

PROFILES: Mapping[str, TransportProfile] = MappingProxyType(
    {
        profile.name: profile
        for profile in (
            OPENAI_NATIVE,
            QWEN_CANONICAL,
            QWEN_25_COMPAT,
            FUNCTION_XML,
            JSON_CALL,
        )
    }
)


class ModelTransportRegistry:
    """Immutable exact model-to-profile assignments."""

    def __init__(self, assignments: Mapping[str, str]):
        normalized: dict[str, str] = {}
        for model_id, profile_name in assignments.items():
            if not isinstance(model_id, str) or not model_id:
                raise ValueError("model IDs must be non-empty strings")
            if profile_name not in PROFILES:
                raise ValueError(f"unknown profile: {profile_name}")
            normalized[model_id] = profile_name
        self._assignments = MappingProxyType(normalized)

    def resolve(self, model_id: str) -> TransportProfile | None:
        profile_name = self._assignments.get(model_id)
        return PROFILES.get(profile_name) if profile_name else None

    def to_dict(self) -> dict[str, str]:
        return dict(self._assignments)

    @property
    def sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    parameters: Mapping[str, Any]

    @classmethod
    def from_openai(cls, raw: Mapping[str, Any]) -> "ToolDefinition":
        if not isinstance(raw, Mapping) or raw.get("type") != "function":
            raise ValueError("only OpenAI-style function tools are supported")
        fn = raw.get("function")
        if not isinstance(fn, Mapping):
            raise ValueError("tool.function must be an object")
        name = fn.get("name")
        parameters = fn.get("parameters")
        if not isinstance(name, str) or not name:
            raise ValueError("tool.function.name must be a non-empty string")
        if not isinstance(parameters, Mapping):
            raise ValueError(f"tool {name!r} parameters must be an object")
        try:
            Draft202012Validator.check_schema(parameters)
        except SchemaError as exc:
            raise ValueError(f"tool {name!r} schema is invalid: {exc.message}") from exc
        return cls(name=name, parameters=dict(parameters))


@dataclass(frozen=True)
class ParsedCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class ParseAttempt:
    matched: bool
    calls: tuple[ParsedCall, ...] = ()
    error: str | None = None


def _json_depth(value: Any) -> int:
    maximum = 1
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        maximum = max(maximum, depth)
        if isinstance(item, Mapping):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return maximum


def _decode_arguments(value: Any, *, max_json_depth: int) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"arguments is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("arguments must decode to a JSON object")
    if _json_depth(value) > max_json_depth:
        raise ValueError("arguments exceed the configured JSON depth limit")
    return value


def _call_from_object(obj: Any, *, max_json_depth: int) -> ParsedCall:
    if not isinstance(obj, Mapping):
        raise ValueError("tool call must be a JSON object")
    allowed = {"name", "arguments", "id", "call_id"}
    extra = set(obj) - allowed
    if extra:
        raise ValueError(f"unexpected tool-call keys: {sorted(extra)}")
    if set(obj) & {"id", "call_id"} == {"id", "call_id"}:
        raise ValueError("tool call may not contain both id and call_id")
    name = obj.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("tool call name must be a non-empty string")
    if "arguments" not in obj:
        raise ValueError("tool call is missing arguments")
    call_id = obj.get("id", obj.get("call_id"))
    if call_id is not None and (not isinstance(call_id, str) or not call_id):
        raise ValueError("call id must be a non-empty string")
    return ParsedCall(
        name=name,
        arguments=_decode_arguments(obj["arguments"], max_json_depth=max_json_depth),
        call_id=call_id,
    )


def _calls_from_json_value(
    value: Any, *, max_calls: int, max_json_depth: int
) -> tuple[ParsedCall, ...]:
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ValueError("tool-call array may not be empty")
    if len(values) > max_calls:
        raise ValueError("tool-call count exceeds the configured limit")
    return tuple(
        _call_from_object(item, max_json_depth=max_json_depth) for item in values
    )


class ToolCallNormalizer:
    def __init__(
        self,
        *,
        max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
        max_calls: int = DEFAULT_MAX_CALLS,
        max_json_depth: int = DEFAULT_MAX_JSON_DEPTH,
    ) -> None:
        if min(max_content_bytes, max_calls, max_json_depth) < 1:
            raise ValueError("normalizer limits must be positive")
        self.max_content_bytes = max_content_bytes
        self.max_calls = max_calls
        self.max_json_depth = max_json_depth

    def normalize(
        self,
        *,
        profile: TransportProfile,
        offered_tools: Sequence[Mapping[str, Any]],
        message: Mapping[str, Any] | None = None,
        content: str | None = None,
    ) -> NormalizationResult:
        if message is not None and not isinstance(message, Mapping):
            return self._invalid("message must be an object when supplied")
        message_content = message.get("content") if message is not None else None
        if message_content is not None and not isinstance(message_content, str):
            return self._invalid("message.content must be a string or null")
        if content is not None and not isinstance(content, str):
            return self._invalid("content must be a string or null")
        if content is not None and message is not None and content != message_content:
            return self._invalid("explicit content disagrees with message.content")
        if content is None:
            content = message_content
        if content is not None and len(content.encode("utf-8")) > self.max_content_bytes:
            return self._invalid("assistant content exceeds the configured byte limit")

        try:
            catalog = self._build_catalog(offered_tools)
        except ValueError as exc:
            return self._invalid(f"invalid offered tool catalog: {exc}")

        native_present = message is not None and "tool_calls" in message
        if not catalog:
            if native_present or self._looks_like_profile_call(profile, content):
                return self._invalid(
                    "tool-call shaped output received when no tools were offered"
                )
            return NormalizationResult(status=NormalizeStatus.NOT_TOOL_CALL)

        for fmt in profile.allowed_formats:
            parser = self._parsers().get(fmt)
            if parser is None:
                return self._invalid(f"profile references unknown parser format {fmt!r}")
            attempt = parser(message if fmt == "openai_native" else content)
            if not attempt.matched:
                continue
            if attempt.error:
                return self._invalid(attempt.error, source_format=fmt)
            return self._validate_calls(fmt, attempt.calls, catalog)
        return NormalizationResult(status=NormalizeStatus.NOT_TOOL_CALL)

    def normalize_assigned(
        self,
        *,
        model_id: str,
        registry: ModelTransportRegistry,
        offered_tools: Sequence[Mapping[str, Any]],
        message: Mapping[str, Any] | None = None,
        content: str | None = None,
    ) -> NormalizationResult:
        profile = registry.resolve(model_id)
        if profile is None:
            return NormalizationResult(
                status=NormalizeStatus.UNKNOWN_MODEL,
                errors=(f"model {model_id!r} has no assigned transport profile",),
            )
        return self.normalize(
            profile=profile,
            offered_tools=offered_tools,
            message=message,
            content=content,
        )

    @staticmethod
    def _invalid(error: str, *, source_format: str | None = None) -> NormalizationResult:
        return NormalizationResult(
            status=NormalizeStatus.INVALID_TOOL_CALL,
            source_format=source_format,
            errors=(error,),
        )

    @staticmethod
    def _build_catalog(
        tools: Sequence[Mapping[str, Any]],
    ) -> dict[str, ToolDefinition]:
        if isinstance(tools, (str, bytes, bytearray)):
            raise ValueError("tools must be a sequence of objects")
        catalog: dict[str, ToolDefinition] = {}
        for raw in tools:
            tool = ToolDefinition.from_openai(raw)
            if tool.name in catalog:
                raise ValueError(f"duplicate tool name: {tool.name}")
            catalog[tool.name] = tool
        return catalog

    def _validate_calls(
        self,
        fmt: str,
        calls: tuple[ParsedCall, ...],
        catalog: Mapping[str, ToolDefinition],
    ) -> NormalizationResult:
        if not calls:
            return self._invalid("parser returned no calls", source_format=fmt)
        canonical: list[CanonicalToolCall] = []
        errors: list[str] = []
        for index, call in enumerate(calls):
            tool = catalog.get(call.name)
            if tool is None:
                errors.append(f"call[{index}] references unavailable tool {call.name!r}")
                continue
            validator = Draft202012Validator(tool.parameters)
            validation_errors = sorted(
                validator.iter_errors(call.arguments), key=lambda error: list(error.path)
            )
            for error in validation_errors:
                path = ".".join(str(part) for part in error.absolute_path) or "$"
                errors.append(f"call[{index}] {call.name}.{path}: {error.message}")
            if not validation_errors:
                canonical.append(
                    CanonicalToolCall(
                        name=call.name,
                        arguments=call.arguments,
                        call_id=call.call_id,
                        source_format=fmt,
                    )
                )
        if errors:
            return NormalizationResult(
                status=NormalizeStatus.INVALID_TOOL_CALL,
                source_format=fmt,
                errors=tuple(errors),
            )
        return NormalizationResult(
            status=NormalizeStatus.NORMALIZED,
            calls=tuple(canonical),
            source_format=fmt,
        )

    def _parsers(self) -> Mapping[str, Callable[[Any], ParseAttempt]]:
        return {
            "openai_native": self._parse_openai_native,
            "tool_call_xml": lambda value: self._parse_repeated_xml(value, "tool_call"),
            "function_call_xml": lambda value: self._parse_repeated_xml(
                value, "function_call"
            ),
            "tools_xml": lambda value: self._parse_repeated_xml(value, "tools"),
            "fenced_json": self._parse_fenced_json,
            "plain_json": self._parse_plain_json,
        }

    def _parse_openai_native(self, message: Any) -> ParseAttempt:
        if not isinstance(message, Mapping) or "tool_calls" not in message:
            return ParseAttempt(matched=False)
        raw_calls = message.get("tool_calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            return ParseAttempt(
                matched=True, error="message.tool_calls must be a non-empty array"
            )
        if len(raw_calls) > self.max_calls:
            return ParseAttempt(
                matched=True, error="tool-call count exceeds the configured limit"
            )
        calls: list[ParsedCall] = []
        try:
            for raw in raw_calls:
                if not isinstance(raw, Mapping):
                    raise ValueError("native tool call must be an object")
                extra = set(raw) - {"id", "type", "function"}
                if extra:
                    raise ValueError(f"unexpected native tool-call keys: {sorted(extra)}")
                if raw.get("type") != "function":
                    raise ValueError("native tool call type must be 'function'")
                function = raw.get("function")
                if not isinstance(function, Mapping):
                    raise ValueError("native tool call function must be an object")
                function_extra = set(function) - {"name", "arguments"}
                if function_extra:
                    raise ValueError(
                        f"unexpected native function keys: {sorted(function_extra)}"
                    )
                obj: dict[str, Any] = {
                    "name": function.get("name"),
                    "arguments": function.get("arguments"),
                }
                if raw.get("id") is not None:
                    obj["id"] = raw["id"]
                calls.append(
                    _call_from_object(obj, max_json_depth=self.max_json_depth)
                )
        except ValueError as exc:
            return ParseAttempt(matched=True, error=str(exc))
        return ParseAttempt(matched=True, calls=tuple(calls))

    def _parse_repeated_xml(self, content: Any, tag: str) -> ParseAttempt:
        if not isinstance(content, str):
            return ParseAttempt(matched=False)
        remaining = content.strip()
        opening = f"<{tag}>"
        closing = f"</{tag}>"
        if not remaining.startswith(opening):
            return ParseAttempt(matched=False)
        calls: list[ParsedCall] = []
        try:
            while remaining:
                if not remaining.startswith(opening):
                    raise ValueError(f"unexpected content outside <{tag}> blocks")
                end = remaining.find(closing, len(opening))
                if end < 0:
                    raise ValueError(f"missing {closing}")
                payload = remaining[len(opening) : end].strip()
                if not payload:
                    raise ValueError(f"empty <{tag}> payload")
                value = json.loads(payload)
                calls.extend(
                    _calls_from_json_value(
                        value,
                        max_calls=self.max_calls,
                        max_json_depth=self.max_json_depth,
                    )
                )
                if len(calls) > self.max_calls:
                    raise ValueError("tool-call count exceeds the configured limit")
                remaining = remaining[end + len(closing) :].strip()
        except (ValueError, json.JSONDecodeError) as exc:
            return ParseAttempt(matched=True, error=str(exc))
        return ParseAttempt(matched=True, calls=tuple(calls))

    _FENCE = re.compile(
        r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```\Z",
        re.IGNORECASE | re.DOTALL,
    )

    def _parse_fenced_json(self, content: Any) -> ParseAttempt:
        if not isinstance(content, str):
            return ParseAttempt(matched=False)
        match = self._FENCE.fullmatch(content.strip())
        if not match:
            return ParseAttempt(matched=False)
        try:
            value = json.loads(match.group("body"))
            return ParseAttempt(
                matched=True,
                calls=_calls_from_json_value(
                    value,
                    max_calls=self.max_calls,
                    max_json_depth=self.max_json_depth,
                ),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return ParseAttempt(matched=True, error=str(exc))

    def _parse_plain_json(self, content: Any) -> ParseAttempt:
        if not isinstance(content, str):
            return ParseAttempt(matched=False)
        text = content.strip()
        if not text or text[0] not in "[{":
            return ParseAttempt(matched=False)
        try:
            value = json.loads(text)
            return ParseAttempt(
                matched=True,
                calls=_calls_from_json_value(
                    value,
                    max_calls=self.max_calls,
                    max_json_depth=self.max_json_depth,
                ),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return ParseAttempt(matched=True, error=str(exc))

    @staticmethod
    def _looks_like_profile_call(
        profile: TransportProfile, content: str | None
    ) -> bool:
        if not isinstance(content, str):
            return False
        stripped = content.strip()
        starts = {
            "tool_call_xml": ("<tool_call>",),
            "function_call_xml": ("<function_call>",),
            "tools_xml": ("<tools>",),
            "fenced_json": ("```",),
            "plain_json": ("{", "["),
        }
        return any(
            stripped.startswith(prefix)
            for fmt in profile.allowed_formats
            for prefix in starts.get(fmt, ())
        )
