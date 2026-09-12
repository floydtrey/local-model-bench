from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..util import validate_id
from .benchmark_pack import BenchmarkPack, parse_benchmark_pack
from .configuration import resolve_effective_configuration
from .containment import ContainmentBackend, ContainmentPolicy, preflight
from .contracts import EvidenceRef, SealedEvidence, canonical_json_bytes, seal_evidence, sha256_json
from .evaluators import EvaluatorDefinition, EvaluatorRegistry
from .records import case_result, execution_binding, run_manifest, trial_identity
from .tool_harness import (
    BOUNDED_FILE_SURFACE_ID,
    BOUNDED_FILE_TOOL_DEFINITIONS,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    ModelDriver,
    ModelTurnRequest,
    ModelTurnResponse,
    run_bounded_tool_harness,
)


ORCHESTRATOR_VERSION = "benchmark-lab-orchestrator:v1"
INTRINSIC_TRACE_VERSION = "benchmark-lab-intrinsic-trace:v1"
PORTABLE_BOUNDED_FILES_CAPABILITY = "bounded-files-v1"
SUPPORTED_LEVELS = frozenset({"L0", "L1", "L2"})
EXECUTION_KINDS = frozenset({"in_process", "subprocess"})
SHA256_CHARS = frozenset("0123456789abcdef")


class OrchestrationBlocked(RuntimeError):
    pass


class EvidenceStoreError(RuntimeError):
    pass


AssetLoader = Callable[[Mapping[str, Any]], bytes]
Clock = Callable[[], str]


def _freeze_json(value: Any) -> Any:
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in SHA256_CHARS for c in value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _derived_id(prefix: str, *parts: Any) -> str:
    validate_id(prefix, "derived ID prefix")
    return f"{prefix}-{sha256_json(list(parts))[:32]}"


def _canonical_relative_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if "\\" in value or "\x00" in value or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} must use canonical forward-slash syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise ValueError(f"{label} must be relative")
    for part in path.parts:
        if part in {"", ".", ".."} or part.casefold() == ".git" or ":" in part:
            raise ValueError(f"{label} contains a forbidden path segment")
    normalized = path.as_posix()
    if normalized != value:
        raise ValueError(f"{label} must already be canonical")
    return normalized


def _scope(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a sequence of relative paths")
    normalized = tuple(sorted(_canonical_relative_path(item, label) for item in values))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(str(path)))


@dataclass(frozen=True)
class ConfigurationBinding:
    profile_id: str
    spec: Mapping[str, Any]
    adapter_resolution: Mapping[str, Any]
    effective_logical_id: str | None = None
    expected_effective_config: EvidenceRef | None = None

    def __post_init__(self) -> None:
        validate_id(self.profile_id, "profile_id")
        if not isinstance(self.spec, Mapping) or not isinstance(self.adapter_resolution, Mapping):
            raise ValueError("spec and adapter_resolution must be objects")
        if self.effective_logical_id is not None:
            validate_id(self.effective_logical_id, "effective_logical_id")
        if self.expected_effective_config is not None:
            if (
                not isinstance(self.expected_effective_config, EvidenceRef)
                or self.expected_effective_config.record_type
                != "effective_runtime_config"
            ):
                raise ValueError(
                    "expected_effective_config must reference effective_runtime_config"
                )
        if (self.effective_logical_id is None) != (
            self.expected_effective_config is None
        ):
            raise ValueError(
                "effective_logical_id and expected_effective_config must be supplied together"
            )
        if (
            self.expected_effective_config is not None
            and self.expected_effective_config.logical_id
            != self.effective_logical_id
        ):
            raise ValueError(
                "expected effective configuration logical ID does not match binding"
            )
        object.__setattr__(self, "spec", _freeze_json(self.spec))
        object.__setattr__(self, "adapter_resolution", _freeze_json(self.adapter_resolution))

    @property
    def resolution_logical_id(self) -> str:
        return self.effective_logical_id or self.profile_id

    def require_expected(self, effective: SealedEvidence) -> None:
        expected = self.expected_effective_config
        if expected is not None and effective.reference != expected:
            raise OrchestrationBlocked(
                "resolved effective configuration does not match its presealed identity"
            )


@dataclass(frozen=True)
class WorkspaceBinding:
    root: Path
    readable_paths: tuple[str, ...]
    writable_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        root = Path(self.root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("workspace root must be an existing directory")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "readable_paths", _scope(self.readable_paths, "readable_paths"))
        object.__setattr__(self, "writable_paths", _scope(self.writable_paths, "writable_paths"))


@dataclass(frozen=True)
class DriverBinding:
    driver_id: str
    implementation_sha256: str
    driver: ModelDriver
    execution_kind: str = "in_process"
    containment_policy: ContainmentPolicy | None = None
    containment_backend: ContainmentBackend | None = None

    def __post_init__(self) -> None:
        validate_id(self.driver_id, "driver_id")
        if not _is_sha256(self.implementation_sha256):
            raise ValueError("implementation_sha256 must be a lowercase SHA-256 digest")
        if not callable(self.driver):
            raise ValueError("driver must be callable")
        if self.execution_kind not in EXECUTION_KINDS:
            raise ValueError(f"execution_kind must be one of {sorted(EXECUTION_KINDS)}")
        if self.execution_kind == "in_process":
            if self.containment_policy is not None or self.containment_backend is not None:
                raise ValueError("in_process driver cannot declare subprocess containment")
        elif self.containment_policy is None or self.containment_backend is None:
            raise ValueError("subprocess driver requires containment_policy and containment_backend")

    def containment_binding(self) -> Mapping[str, Any] | None:
        if self.execution_kind == "in_process":
            return None
        assert self.containment_policy is not None
        assert self.containment_backend is not None
        result = preflight(self.containment_policy, self.containment_backend.capabilities)
        result.require_allowed()
        return {
            "policy_sha256": self.containment_policy.sha256,
            "backend": self.containment_backend.capabilities.to_dict(),
        }

    def identity_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "implementation_sha256": self.implementation_sha256,
            "execution_kind": self.execution_kind,
        }


@dataclass(frozen=True)
class _ResolvedAsset:
    candidate_descriptor: Mapping[str, Any]
    binding_descriptor: Mapping[str, Any]
    data: bytes
    reference_path: str | None


@dataclass(frozen=True)
class OrchestratedRun:
    benchmark: SealedEvidence
    effective_configs: tuple[SealedEvidence, ...]
    trials: tuple[SealedEvidence, ...]
    execution_bindings: tuple[SealedEvidence, ...]
    manifest: SealedEvidence
    execution_evidence: tuple[SealedEvidence, ...]
    case_results: tuple[SealedEvidence, ...]
    evaluation_results: tuple[SealedEvidence, ...]


class EvidenceStore:
    """Append-only content-addressed persistence for sealed V2 evidence."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise EvidenceStoreError("evidence store root is not a directory")

    def path_for(self, reference: EvidenceRef | SealedEvidence) -> Path:
        ref = reference.reference if isinstance(reference, SealedEvidence) else reference
        return self.root / "records" / ref.record_type / f"{ref.sha256}.json"

    def contains(self, reference: EvidenceRef | SealedEvidence) -> bool:
        return self.path_for(reference).is_file()

    def persist(self, record: SealedEvidence) -> Path:
        if not isinstance(record, SealedEvidence):
            raise ValueError("record must be SealedEvidence")
        path = self.path_for(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_bytes(record.to_dict())
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.read_bytes() != data:
                raise EvidenceStoreError(
                    f"existing evidence bytes do not match sealed record: {record.sha256}"
                )
        return path

    def persist_many(self, records: Iterable[SealedEvidence]) -> None:
        for record in records:
            self.persist(record)

    def load(self, reference: EvidenceRef) -> SealedEvidence:
        if not isinstance(reference, EvidenceRef):
            raise ValueError("reference must be EvidenceRef")
        path = self.path_for(reference)
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceStoreError(f"stored evidence is invalid JSON: {path}") from exc
        record = SealedEvidence.from_dict(value)
        if record.reference != reference:
            raise EvidenceStoreError("stored evidence does not match requested reference")
        return record


def _validate_foundation(host: SealedEvidence, runtime: SealedEvidence, model: SealedEvidence) -> None:
    for record, expected, label in (
        (host, "host_profile", "host"),
        (runtime, "runtime_profile", "runtime"),
        (model, "model_identity", "model"),
    ):
        if not isinstance(record, SealedEvidence) or record.record_type != expected:
            raise ValueError(f"{label} must be sealed {expected} evidence")


def _resolve_assets(
    case_definition: Mapping[str, Any],
    *,
    level: str,
    asset_loader: AssetLoader | None,
) -> tuple[_ResolvedAsset, ...]:
    case_input = case_definition.get("input")
    if not isinstance(case_input, Mapping):
        raise ValueError("case input is missing")
    raw_assets = case_input.get("context_assets", ())
    if not isinstance(raw_assets, Sequence) or isinstance(raw_assets, (str, bytes, bytearray)):
        raise ValueError("case context_assets must be an array")
    if raw_assets and asset_loader is None:
        raise OrchestrationBlocked("context assets require an explicit asset_loader")

    resolved: list[_ResolvedAsset] = []
    for item in raw_assets:
        if not isinstance(item, Mapping):
            raise ValueError("context asset must be an object")
        assert asset_loader is not None
        data = asset_loader(item)
        if not isinstance(data, bytes):
            raise ValueError("asset_loader must return bytes")
        actual = _sha256_bytes(data)
        if actual != item.get("sha256"):
            raise OrchestrationBlocked(
                f"context asset digest mismatch for {item.get('asset_id')!r}"
            )
        common = {
            "asset_id": str(item.get("asset_id")),
            "sha256": actual,
            "media_type": str(item.get("media_type")),
            "delivery": item.get("delivery"),
        }
        if item.get("delivery") == "inline_context":
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OrchestrationBlocked("inline context assets must be UTF-8") from exc
            resolved.append(
                _ResolvedAsset(
                    {**common, "content_utf8": text},
                    {**common, "delivery_target": "inline_context"},
                    data,
                    None,
                )
            )
            continue
        if item.get("delivery") == "readonly_reference":
            if level != "L2":
                raise OrchestrationBlocked("readonly_reference assets require L2")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OrchestrationBlocked("readonly reference assets must be UTF-8") from exc
            relative = _canonical_relative_path(
                f"context-assets/{common['asset_id']}", "context asset reference path"
            )
            resolved.append(
                _ResolvedAsset(
                    {**common, "reference_path": relative},
                    {**common, "delivery_target": relative},
                    data,
                    relative,
                )
            )
            continue
        raise OrchestrationBlocked(
            f"unsupported context asset delivery mode: {item.get('delivery')!r}"
        )
    return tuple(resolved)


def _execution_case(
    case_definition: Mapping[str, Any], assets: Sequence[_ResolvedAsset]
) -> dict[str, Any]:
    case = _thaw_json(case_definition)
    case["input"]["context_assets"] = [
        _thaw_json(asset.candidate_descriptor) for asset in assets
    ]
    return case


def _bl6_execution_case(case_definition: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a portable L2 case to BL-6's concrete harness contract.

    The portable Benchmark Pack remains unchanged and is what the benchmark/trial
    identities bind. The execution binding separately seals this exact mapping.
    This derived view exists only at the BL-6 call boundary.
    """

    case = _thaw_json(case_definition)
    requirements = case.get("requirements")
    if not isinstance(requirements, dict):
        raise ValueError("execution case requirements must be an object")
    portable = requirements.get("tool_surface")
    expected_tools = [item["name"] for item in BOUNDED_FILE_TOOL_DEFINITIONS]
    if not isinstance(portable, dict):
        raise ValueError("execution case tool_surface must be an object")
    if portable.get("id") != PORTABLE_BOUNDED_FILES_CAPABILITY:
        raise OrchestrationBlocked("portable L2 capability changed after planning")
    if list(portable.get("required_tools", ())) != expected_tools:
        raise OrchestrationBlocked("portable L2 tool list changed after planning")
    requirements["tool_surface"] = {
        "id": BOUNDED_FILE_SURFACE_ID,
        "required_tools": expected_tools,
    }
    return case


def _validate_case_configuration(
    case_definition: Mapping[str, Any],
    *,
    level: str,
    effective_config: SealedEvidence,
) -> Mapping[str, Any] | None:
    requirements = case_definition.get("requirements")
    if not isinstance(requirements, Mapping):
        raise ValueError("case requirements must be an object")
    settings = effective_config.payload.get("settings")
    if not isinstance(settings, Mapping):
        raise ValueError("effective configuration settings are missing")
    generation = settings.get("generation")
    if not isinstance(generation, Mapping):
        raise ValueError("effective configuration generation settings are missing")

    if _thaw_json(requirements.get("response_contract")) != _thaw_json(
        generation.get("response_format")
    ):
        raise OrchestrationBlocked("case response contract does not match effective configuration")
    minimum_context = requirements.get("minimum_context_tokens")
    if minimum_context is not None and generation.get("context_tokens", 0) < minimum_context:
        raise OrchestrationBlocked("effective context window is smaller than case requirement")

    required_surface = requirements.get("tool_surface")
    actual_surface = effective_config.payload.get("tool_surface")
    if not isinstance(required_surface, Mapping) or not isinstance(actual_surface, Mapping):
        raise ValueError("tool surface contracts are missing")

    required_tools = list(required_surface.get("required_tools", ()))
    actual_tools = list(actual_surface.get("tools", ()))
    if level in {"L0", "L1"}:
        if required_surface.get("id") != "none" or required_tools:
            raise OrchestrationBlocked(f"{level} case must remain tool-free")
        if actual_tools:
            raise OrchestrationBlocked(f"{level} effective configuration must remain tool-free")
        return None

    if level != "L2":
        raise OrchestrationBlocked(f"orchestrator v1 does not execute {level}")
    if required_surface.get("id") != PORTABLE_BOUNDED_FILES_CAPABILITY:
        raise OrchestrationBlocked(
            f"L2 case must require portable capability {PORTABLE_BOUNDED_FILES_CAPABILITY!r}"
        )
    expected_tools = [item["name"] for item in BOUNDED_FILE_TOOL_DEFINITIONS]
    if required_tools != expected_tools:
        raise OrchestrationBlocked(f"L2 case must require tools in canonical order: {expected_tools}")
    if actual_surface.get("id") != BOUNDED_FILE_SURFACE_ID:
        raise OrchestrationBlocked("effective configuration is not bound to the BL-6 lab harness")
    if actual_tools != expected_tools:
        raise OrchestrationBlocked("effective configuration tool list does not match BL-6")
    if actual_surface.get("schema_sha256") != BOUNDED_FILE_TOOL_SCHEMA_SHA256:
        raise OrchestrationBlocked("effective configuration tool schema digest does not match BL-6")
    return {
        "required_capability": PORTABLE_BOUNDED_FILES_CAPABILITY,
        "required_tools": expected_tools,
        "concrete_surface": BOUNDED_FILE_SURFACE_ID,
        "concrete_schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    }


def _materialize_reference_assets(
    workspace: WorkspaceBinding, assets: Sequence[_ResolvedAsset]
) -> None:
    for asset in assets:
        if asset.reference_path is None:
            continue
        target = workspace.root.joinpath(*PurePosixPath(asset.reference_path).parts)
        parent = target.parent
        if parent.exists():
            if not parent.is_dir() or _link_like(parent):
                raise OrchestrationBlocked("context asset parent is not a safe directory")
        else:
            if parent.parent != workspace.root:
                raise OrchestrationBlocked("context asset staging depth is unsupported")
            parent.mkdir()
        resolved_parent = parent.resolve(strict=True)
        try:
            resolved_parent.relative_to(workspace.root)
        except ValueError as exc:
            raise OrchestrationBlocked("context asset staging escapes workspace") from exc
        if target.exists():
            if _link_like(target) or not target.is_file() or target.read_bytes() != asset.data:
                raise OrchestrationBlocked(
                    f"context asset materialization collides with path: {asset.reference_path}"
                )
            continue
        with target.open("xb") as handle:
            handle.write(asset.data)
            handle.flush()
            os.fsync(handle.fileno())


def _intrinsic_trace(
    *,
    logical_id: str,
    case_definition: Mapping[str, Any],
    driver: ModelDriver,
) -> tuple[str, str, Mapping[str, Any] | None, SealedEvidence]:
    case_id = validate_id(case_definition.get("case_id"), "case_id")
    case_input = case_definition.get("input")
    if not isinstance(case_input, Mapping):
        raise ValueError("case input must be an object")
    request = ModelTurnRequest(
        case_id=case_id,
        turn=1,
        messages=tuple(case_input.get("messages", ())),
        context_assets=tuple(case_input.get("context_assets", ())),
        tools=(),
    )
    response_value: Mapping[str, Any] | None = None
    error_value: Mapping[str, Any] | None = None
    terminal: Mapping[str, Any] | None = None
    try:
        response = driver(request)
    except Exception as exc:
        status = "error"
        stop_reason = "model_driver_error"
        error_value = {"error_type": type(exc).__name__, "detail": str(exc)}
    else:
        if not isinstance(response, ModelTurnResponse):
            status = "protocol_failure"
            stop_reason = "invalid_model_response"
            error_value = {"reason": "driver_returned_invalid_response_type"}
        elif response.tool_calls:
            status = "protocol_failure"
            stop_reason = "tools_forbidden"
            response_value = response.to_dict()
            error_value = {"reason": "intrinsic execution returned tool calls"}
        else:
            status = "success"
            stop_reason = "terminal_output"
            response_value = response.to_dict()
            content = response.content or ""
            raw = content.encode("utf-8")
            terminal = {
                "kind": "assistant_text",
                "content": content,
                "sha256": _sha256_bytes(raw),
                "size_bytes": len(raw),
            }
    trace = seal_evidence(
        "intrinsic_execution_trace",
        logical_id,
        {
            "trace_version": INTRINSIC_TRACE_VERSION,
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "case_id": case_id,
            "request": request.to_dict(),
            "response": response_value,
            "error": error_value,
            "status": status,
            "stop_reason": stop_reason,
            "terminal_output": terminal,
        },
    )
    validate_intrinsic_execution_trace(trace)
    return status, stop_reason, terminal, trace


def validate_intrinsic_execution_trace(trace: SealedEvidence) -> None:
    if not isinstance(trace, SealedEvidence) or trace.record_type != "intrinsic_execution_trace":
        raise ValueError("expected intrinsic_execution_trace evidence")
    payload = trace.payload
    if payload.get("trace_version") != INTRINSIC_TRACE_VERSION:
        raise ValueError("unsupported intrinsic trace version")
    if payload.get("orchestrator_version") != ORCHESTRATOR_VERSION:
        raise ValueError("intrinsic trace orchestrator version mismatch")
    request = payload.get("request")
    if not isinstance(request, Mapping) or list(request.get("tools", ())) != []:
        raise ValueError("intrinsic trace must contain a tool-free request")
    if payload.get("status") not in {
        "success",
        "error",
        "blocked",
        "resource_limit",
        "protocol_failure",
    }:
        raise ValueError("intrinsic trace status is invalid")
    if payload.get("status") == "success" and not isinstance(
        payload.get("terminal_output"), Mapping
    ):
        raise ValueError("successful intrinsic trace requires terminal output")


def _evaluator_identities(
    pack: BenchmarkPack, registry: EvaluatorRegistry
) -> tuple[SealedEvidence, ...]:
    values: list[SealedEvidence] = []
    seen: set[str] = set()
    for case in pack.cases:
        for binding in case["evaluators"]:
            definition = registry.resolve(
                str(binding["evaluator_id"]), str(binding["contract_version"])
            )
            identity = definition.identity
            if identity.sha256 not in seen:
                values.append(identity)
                seen.add(identity.sha256)
    return tuple(values)


def _supplemental_for_definition(
    definition: EvaluatorDefinition,
    available: Sequence[SealedEvidence],
) -> tuple[SealedEvidence, ...]:
    declared = {item.record_type for item in definition.consumed_evidence}
    return tuple(
        item
        for item in available
        if item.record_type != "case_result" and item.record_type in declared
    )


def run_v2_pack(
    *,
    run_id: str,
    pack_source: bytes,
    pack_source_locator: str | None,
    host: SealedEvidence,
    runtime: SealedEvidence,
    model: SealedEvidence,
    configuration_bindings: Mapping[str, ConfigurationBinding],
    evaluator_registry: EvaluatorRegistry,
    driver_binding: DriverBinding,
    evidence_store: EvidenceStore,
    harness_source: Mapping[str, Any],
    workspaces: Mapping[str, WorkspaceBinding] | None = None,
    asset_loader: AssetLoader | None = None,
    supplemental_evidence: Mapping[str, Sequence[SealedEvidence]] | None = None,
    clock: Clock = _utc_now,
) -> OrchestratedRun:
    """Plan, seal, persist, execute and evaluate one Benchmark Pack.

    BL-8A runs exactly one trial per case. Repetition planning and aggregate reports
    belong to BL-8B. A subprocess-bound driver is preflighted and bound into the
    manifest, but execution is blocked until a model-driver adapter actually routes
    each invocation through BL-7 rather than calling the Python driver directly.
    """

    validate_id(run_id, "run_id")
    _validate_foundation(host, runtime, model)
    if not isinstance(configuration_bindings, Mapping) or not configuration_bindings:
        raise ValueError("configuration_bindings must be a non-empty mapping")
    if not isinstance(evaluator_registry, EvaluatorRegistry):
        raise ValueError("evaluator_registry must be an EvaluatorRegistry")
    if not isinstance(driver_binding, DriverBinding):
        raise ValueError("driver_binding must be DriverBinding")
    if not isinstance(evidence_store, EvidenceStore):
        raise ValueError("evidence_store must be EvidenceStore")
    if not isinstance(harness_source, Mapping):
        raise ValueError("harness_source must be an object")

    pack = parse_benchmark_pack(pack_source)
    if pack.level not in SUPPORTED_LEVELS:
        raise OrchestrationBlocked(
            f"orchestrator v1 supports only {sorted(SUPPORTED_LEVELS)}, got {pack.level}"
        )
    benchmark = pack.to_benchmark_input(source_locator=pack_source_locator)
    workspaces = {} if workspaces is None else dict(workspaces)
    supplemental_evidence = {} if supplemental_evidence is None else dict(supplemental_evidence)

    containment = driver_binding.containment_binding()
    evaluator_identities = _evaluator_identities(pack, evaluator_registry)
    effective_by_profile: dict[str, SealedEvidence] = {}
    assets_by_case: dict[str, tuple[_ResolvedAsset, ...]] = {}
    execution_cases: dict[str, dict[str, Any]] = {}
    workspace_by_case: dict[str, WorkspaceBinding] = {}
    trials: list[SealedEvidence] = []
    bindings: list[SealedEvidence] = []
    config_order: list[SealedEvidence] = []
    layer = "lab_tool" if pack.level == "L2" else "intrinsic"

    for case in pack.cases:
        case_id = str(case["case_id"])
        profile_id = str(case["requirements"]["configuration_profile"])
        configured = configuration_bindings.get(profile_id)
        if configured is None:
            raise OrchestrationBlocked(
                f"case {case_id!r} references missing configuration profile {profile_id!r}"
            )
        if not isinstance(configured, ConfigurationBinding) or configured.profile_id != profile_id:
            raise ValueError("configuration binding key/profile_id mismatch")
        effective = effective_by_profile.get(profile_id)
        if effective is None:
            effective = resolve_effective_configuration(
                configured.resolution_logical_id,
                runtime=runtime,
                model=model,
                spec=_thaw_json(configured.spec),
                adapter_resolution=_thaw_json(configured.adapter_resolution),
            )
            configured.require_expected(effective)
            effective_by_profile[profile_id] = effective
            config_order.append(effective)

        tool_binding = _validate_case_configuration(
            case, level=pack.level, effective_config=effective
        )
        assets = _resolve_assets(case, level=pack.level, asset_loader=asset_loader)
        assets_by_case[case_id] = assets
        execution_cases[case_id] = _execution_case(case, assets)

        workspace_scope: Mapping[str, Any] | None = None
        if pack.level == "L2":
            workspace = workspaces.get(case_id)
            if not isinstance(workspace, WorkspaceBinding):
                raise OrchestrationBlocked(f"L2 case {case_id!r} requires WorkspaceBinding")
            reference_paths = tuple(
                asset.reference_path for asset in assets if asset.reference_path is not None
            )
            if set(reference_paths) & set(workspace.writable_paths):
                raise OrchestrationBlocked("readonly context asset path cannot be writable")
            workspace = WorkspaceBinding(
                root=workspace.root,
                readable_paths=tuple(sorted(set(workspace.readable_paths) | set(reference_paths))),
                writable_paths=workspace.writable_paths,
            )
            workspace_by_case[case_id] = workspace
            workspace_scope = {
                "readable_paths": list(workspace.readable_paths),
                "writable_paths": list(workspace.writable_paths),
            }
        elif case_id in workspaces:
            raise OrchestrationBlocked("workspace bindings are only valid for L2 cases")

        trial = trial_identity(
            _derived_id("trial", pack.pack_id, pack.pack_version, case_id, 1),
            layer=layer,
            ordinal=1,
            repeat_group=None,
            benchmark=benchmark.reference,
            case_id=case_id,
            effective_config=effective.reference,
        )
        trials.append(trial)
        driver_descriptor = driver_binding.identity_dict()
        if tool_binding is not None:
            driver_descriptor["tool_surface_binding"] = _thaw_json(tool_binding)
        bindings.append(
            execution_binding(
                _derived_id("binding", trial.sha256),
                trial=trial.reference,
                execution_mode=layer,
                driver=driver_descriptor,
                workspace_scope=workspace_scope,
                context_assets=[asset.binding_descriptor for asset in assets],
                containment=containment,
            )
        )

    manifest = run_manifest(
        run_id,
        host=host.reference,
        runtime=runtime.reference,
        model=model.reference,
        effective_configs=[record.reference for record in config_order],
        benchmarks=[benchmark.reference],
        evaluators=[record.reference for record in evaluator_identities],
        trials=[record.reference for record in trials],
        execution_bindings=[record.reference for record in bindings],
        harness_source={
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "source": _thaw_json(harness_source),
        },
    )

    evidence_store.persist_many(
        (
            host,
            runtime,
            model,
            benchmark,
            *config_order,
            *evaluator_identities,
            *trials,
            *bindings,
            manifest,
        )
    )

    if driver_binding.execution_kind == "subprocess":
        raise OrchestrationBlocked(
            "subprocess driver binding was preflighted and sealed, but BL-8A has no "
            "model-driver adapter that routes invocation through BL-7; direct-call fallback is forbidden"
        )

    execution_records: list[SealedEvidence] = []
    case_records: list[SealedEvidence] = []
    evaluation_records: list[SealedEvidence] = []
    trial_by_case = {str(case["case_id"]): trial for case, trial in zip(pack.cases, trials)}
    binding_by_case = {str(case["case_id"]): item for case, item in zip(pack.cases, bindings)}

    for case in pack.cases:
        case_id = str(case["case_id"])
        effective = effective_by_profile[str(case["requirements"]["configuration_profile"])]
        trial = trial_by_case[case_id]
        binding = binding_by_case[case_id]
        started_at = clock()
        if not isinstance(started_at, str) or not started_at:
            raise ValueError("clock must return non-empty timestamp strings")

        if pack.level == "L2":
            workspace = workspace_by_case[case_id]
            _materialize_reference_assets(workspace, assets_by_case[case_id])
            result = run_bounded_tool_harness(
                trace_logical_id=_derived_id("tooltrace", trial.sha256),
                case_definition=_bl6_execution_case(execution_cases[case_id]),
                effective_config=effective,
                workspace_root=workspace.root,
                readable_paths=workspace.readable_paths,
                writable_paths=workspace.writable_paths,
                driver=driver_binding.driver,
            )
            status = result.status
            stop_reason = result.stop_reason
            terminal_output = None if result.terminal_output is None else _thaw_json(result.terminal_output)
            trace = result.trace
            metrics = {
                "execution_mode": "lab_tool",
                "stop_reason": stop_reason,
                "tool_summary": _thaw_json(trace.payload["summary"]),
            }
        else:
            status, stop_reason, terminal_output, trace = _intrinsic_trace(
                logical_id=_derived_id("intrinsic", trial.sha256),
                case_definition=execution_cases[case_id],
                driver=driver_binding.driver,
            )
            metrics = {
                "execution_mode": "intrinsic",
                "stop_reason": stop_reason,
                "model_turns": 1,
            }

        finished_at = clock()
        if not isinstance(finished_at, str) or not finished_at:
            raise ValueError("clock must return non-empty timestamp strings")
        evidence_store.persist(trace)
        execution_records.append(trace)
        case_record = case_result(
            _derived_id("case", manifest.sha256, trial.sha256),
            manifest=manifest.reference,
            benchmark=benchmark.reference,
            trial=trial.reference,
            case_id=case_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            execution_evidence={
                "primary": trace.reference.to_dict(),
                "execution_binding": binding.reference.to_dict(),
            },
            terminal_output=terminal_output,
        )
        evidence_store.persist(case_record)
        case_records.append(case_record)

        # A model-driver exception is an operational qualification failure,
        # not evidence of candidate capability. Preserve the execution trace
        # and case result, then stop before deterministic scoring can turn the
        # infrastructure failure into a model score.
        if status == "error" and stop_reason == "model_driver_error":
            raise OrchestrationBlocked(
                f"model driver failed for case {case_id}; "
                "qualification evidence was preserved and scoring was stopped"
            )

        extras = supplemental_evidence.get(case_id, ())
        if isinstance(extras, (str, bytes, bytearray)):
            raise ValueError("supplemental_evidence values must be sequences")
        for item in extras:
            if not isinstance(item, SealedEvidence):
                raise ValueError("supplemental_evidence must contain SealedEvidence values")
        available = (
            host,
            runtime,
            model,
            benchmark,
            effective,
            trial,
            binding,
            manifest,
            trace,
            *tuple(extras),
        )
        for evaluator_ref in case["evaluators"]:
            evaluator_id = str(evaluator_ref["evaluator_id"])
            contract_version = str(evaluator_ref["contract_version"])
            definition = evaluator_registry.resolve(evaluator_id, contract_version)
            evaluation = evaluator_registry.evaluate(
                _derived_id("evaluation", case_record.sha256, evaluator_id, contract_version),
                evaluator_id=evaluator_id,
                contract_version=contract_version,
                case_definition=case,
                case_result_record=case_record,
                supplemental_evidence=_supplemental_for_definition(definition, available),
            )
            evidence_store.persist(evaluation)
            evaluation_records.append(evaluation)

    return OrchestratedRun(
        benchmark=benchmark,
        effective_configs=tuple(config_order),
        trials=tuple(trials),
        execution_bindings=tuple(bindings),
        manifest=manifest,
        execution_evidence=tuple(execution_records),
        case_results=tuple(case_records),
        evaluation_results=tuple(evaluation_records),
    )

