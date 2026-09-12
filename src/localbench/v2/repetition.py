from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ..util import validate_id
from .benchmark_pack import parse_benchmark_pack
from .configuration import resolve_effective_configuration
from .contracts import SealedEvidence, seal_evidence
from .evaluators import EvaluatorRegistry
from .execution_interface import validate_execution_interface_identity
from .orchestrator import (
    AssetLoader,
    Clock,
    ConfigurationBinding,
    DriverBinding,
    EvidenceStore,
    ORCHESTRATOR_VERSION,
    OrchestrationBlocked,
    WorkspaceBinding,
    _bl6_execution_case,
    _derived_id,
    _evaluator_identities,
    _execution_case,
    _intrinsic_trace,
    _materialize_reference_assets,
    _resolve_assets,
    _supplemental_for_definition,
    _thaw_json,
    _utc_now,
    _validate_case_configuration,
    _validate_foundation,
)
from .records import case_result, execution_binding, run_manifest, trial_identity
from .resource_telemetry import ResourceTelemetryBinding
from .resource_telemetry_integration import SafeResourceTelemetryCapture
from .tool_harness import (
    BoundedWorkspace,
    run_bounded_tool_harness,
    validate_tool_execution_trace,
)


REPETITION_RUNNER_VERSION = "benchmark-lab-repetition-runner:v1"
REPETITION_PHASES = MappingProxyType(
    {
        "screen": "screen_trials",
        "qualification": "qualification_trials",
    }
)


WorkspaceFactory = Callable[[str, int], WorkspaceBinding]


@dataclass(frozen=True)
class _PlannedTrial:
    case: Mapping[str, Any]
    effective: SealedEvidence
    execution_case: Mapping[str, Any]
    assets: tuple[Any, ...]
    workspace: WorkspaceBinding | None
    initial_workspace_sha256: str | None
    trial: SealedEvidence
    binding: SealedEvidence


@dataclass(frozen=True)
class RepeatedRun:
    repetition_phase: str
    planned_counts: Mapping[str, int]
    benchmark: SealedEvidence
    effective_configs: tuple[SealedEvidence, ...]
    trials: tuple[SealedEvidence, ...]
    execution_bindings: tuple[SealedEvidence, ...]
    manifest: SealedEvidence
    execution_evidence: tuple[SealedEvidence, ...]
    resource_telemetry: tuple[SealedEvidence, ...]
    case_results: tuple[SealedEvidence, ...]
    evaluation_results: tuple[SealedEvidence, ...]

    def __post_init__(self) -> None:
        if self.repetition_phase not in REPETITION_PHASES:
            raise ValueError(
                f"repetition_phase must be one of {sorted(REPETITION_PHASES)}"
            )
        if not isinstance(self.planned_counts, Mapping) or not self.planned_counts:
            raise ValueError("planned_counts must be a non-empty mapping")
        counts: dict[str, int] = {}
        for case_id, value in self.planned_counts.items():
            normalized = validate_id(case_id, "planned_counts case_id")
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("planned repetition counts must be integers >= 1")
            counts[normalized] = value
        object.__setattr__(self, "planned_counts", MappingProxyType(counts))

        if not isinstance(self.benchmark, SealedEvidence) or self.benchmark.record_type != "benchmark_input":
            raise ValueError("benchmark must be sealed benchmark_input evidence")
        if not isinstance(self.manifest, SealedEvidence) or self.manifest.record_type != "run_manifest":
            raise ValueError("manifest must be sealed run_manifest evidence")
        for name in (
            "effective_configs",
            "trials",
            "execution_bindings",
            "execution_evidence",
            "resource_telemetry",
            "case_results",
            "evaluation_results",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, SealedEvidence) for item in value
            ):
                raise ValueError(f"{name} must be a tuple of SealedEvidence values")
        if any(item.record_type != "resource_telemetry_trace" for item in self.resource_telemetry):
            raise ValueError("resource_telemetry must contain resource_telemetry_trace evidence")


def _trial_count(case: Mapping[str, Any], phase: str) -> int:
    field = REPETITION_PHASES[phase]
    repetitions = case.get("repetitions")
    if not isinstance(repetitions, Mapping):
        raise ValueError("case repetitions must be an object")
    value = repetitions.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"case {field} must be an integer >= 1")
    return value


def _workspace_with_reference_assets(
    workspace: WorkspaceBinding,
    assets: Sequence[Any],
) -> WorkspaceBinding:
    reference_paths = tuple(
        asset.reference_path for asset in assets if asset.reference_path is not None
    )
    if set(reference_paths) & set(workspace.writable_paths):
        raise OrchestrationBlocked("readonly context asset path cannot be writable")
    return WorkspaceBinding(
        root=workspace.root,
        readable_paths=tuple(sorted(set(workspace.readable_paths) | set(reference_paths))),
        writable_paths=workspace.writable_paths,
    )


def _initial_workspace_sha256(workspace: WorkspaceBinding) -> str:
    snapshot = BoundedWorkspace(
        workspace.root,
        readable_paths=workspace.readable_paths,
        writable_paths=workspace.writable_paths,
    ).snapshot()
    value = snapshot.get("snapshot_sha256")
    if not isinstance(value, str) or len(value) != 64:
        raise OrchestrationBlocked("BL-6 workspace snapshot did not produce a SHA-256 identity")
    return value


def run_v2_repetitions(
    *,
    run_id: str,
    repetition_phase: str,
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
    workspace_factory: WorkspaceFactory | None = None,
    asset_loader: AssetLoader | None = None,
    supplemental_evidence: Mapping[str, Sequence[SealedEvidence]] | None = None,
    resource_telemetry: ResourceTelemetryBinding | None = None,
    clock: Clock = _utc_now,
) -> RepeatedRun:
    """Execute the Benchmark Pack's predeclared repetition policy.

    BL-8B never invents repetition counts. ``screen`` selects each case's
    ``screen_trials`` value and ``qualification`` selects ``qualification_trials``.
    Repeated L2 trials require distinct disposable workspaces with identical sealed
    initial snapshots so one trial cannot influence another. Optional resource
    telemetry is observational, sealed separately, and cannot change scoring.
    """

    validate_id(run_id, "run_id")
    if repetition_phase not in REPETITION_PHASES:
        raise ValueError(f"repetition_phase must be one of {sorted(REPETITION_PHASES)}")
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
    if resource_telemetry is not None and not isinstance(
        resource_telemetry, ResourceTelemetryBinding
    ):
        raise ValueError("resource_telemetry must be ResourceTelemetryBinding or null")

    pack = parse_benchmark_pack(pack_source)
    if pack.level not in {"L0", "L1", "L2"}:
        raise OrchestrationBlocked(
            f"repetition runner supports only L0/L1/L2, got {pack.level}"
        )
    execution_interface = driver_binding.execution_interface
    if pack.level == "L2":
        if execution_interface is None:
            raise OrchestrationBlocked(
                "L2 execution requires an explicit execution_interface_identity"
            )
        validate_execution_interface_identity(execution_interface)
        if _thaw_json(execution_interface.payload.get("runtime")) != runtime.reference.to_dict():
            raise OrchestrationBlocked(
                "execution interface runtime does not match the run runtime"
            )
        if _thaw_json(execution_interface.payload.get("model")) != model.reference.to_dict():
            raise OrchestrationBlocked(
                "execution interface model does not match the run model"
            )
    if resource_telemetry is not None and pack.level != "L2":
        raise OrchestrationBlocked("resource telemetry is enabled only for L2 repetitions")
    benchmark = pack.to_benchmark_input(source_locator=pack_source_locator)
    workspaces = {} if workspaces is None else dict(workspaces)
    supplemental_evidence = {} if supplemental_evidence is None else dict(supplemental_evidence)
    if pack.level != "L2" and (workspaces or workspace_factory is not None):
        raise OrchestrationBlocked("workspace bindings are only valid for L2 repetitions")

    containment = driver_binding.containment_binding()
    evaluator_identities = _evaluator_identities(pack, evaluator_registry)
    effective_by_profile: dict[str, SealedEvidence] = {}
    config_order: list[SealedEvidence] = []
    planned: list[_PlannedTrial] = []
    planned_counts: dict[str, int] = {}
    used_roots: set[Path] = set()
    baseline_by_case: dict[str, str] = {}
    layer = "lab_tool" if pack.level == "L2" else "intrinsic"

    for case in pack.cases:
        case_id = str(case["case_id"])
        count = _trial_count(case, repetition_phase)
        planned_counts[case_id] = count
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
        execution_case = _execution_case(case, assets)
        repeat_group = _derived_id(
            "repeat",
            pack.pack_id,
            pack.pack_version,
            case_id,
            repetition_phase,
        )

        for ordinal in range(1, count + 1):
            workspace: WorkspaceBinding | None = None
            initial_sha256: str | None = None
            workspace_scope: Mapping[str, Any] | None = None
            if pack.level == "L2":
                if workspace_factory is not None:
                    workspace = workspace_factory(case_id, ordinal)
                else:
                    if count > 1:
                        raise OrchestrationBlocked(
                            "repeated L2 trials require workspace_factory so each trial starts in a distinct workspace"
                        )
                    workspace = workspaces.get(case_id)
                if not isinstance(workspace, WorkspaceBinding):
                    raise OrchestrationBlocked(
                        f"L2 repetition {case_id!r} ordinal {ordinal} requires WorkspaceBinding"
                    )
                workspace = _workspace_with_reference_assets(workspace, assets)
                if workspace.root in used_roots:
                    raise OrchestrationBlocked(
                        "repetition workspaces must use distinct roots; workspace reuse would contaminate trials"
                    )
                used_roots.add(workspace.root)
                _materialize_reference_assets(workspace, assets)
                initial_sha256 = _initial_workspace_sha256(workspace)
                expected = baseline_by_case.setdefault(case_id, initial_sha256)
                if expected != initial_sha256:
                    raise OrchestrationBlocked(
                        f"repeated L2 case {case_id!r} has inconsistent initial workspace state"
                    )
                workspace_scope = {
                    "readable_paths": list(workspace.readable_paths),
                    "writable_paths": list(workspace.writable_paths),
                    "initial_state_sha256": initial_sha256,
                }

            trial = trial_identity(
                _derived_id(
                    "trial",
                    pack.pack_id,
                    pack.pack_version,
                    case_id,
                    repetition_phase,
                    ordinal,
                ),
                layer=layer,
                ordinal=ordinal,
                repeat_group=repeat_group,
                benchmark=benchmark.reference,
                case_id=case_id,
                effective_config=effective.reference,
            )
            driver_descriptor = driver_binding.identity_dict()
            if tool_binding is not None:
                driver_descriptor["tool_surface_binding"] = _thaw_json(tool_binding)
            binding = execution_binding(
                _derived_id("binding", trial.sha256),
                trial=trial.reference,
                execution_mode=layer,
                driver=driver_descriptor,
                workspace_scope=workspace_scope,
                context_assets=[asset.binding_descriptor for asset in assets],
                containment=containment,
                execution_interface=None
                if execution_interface is None
                else execution_interface.reference,
            )
            planned.append(
                _PlannedTrial(
                    case=case,
                    effective=effective,
                    execution_case=execution_case,
                    assets=tuple(assets),
                    workspace=workspace,
                    initial_workspace_sha256=initial_sha256,
                    trial=trial,
                    binding=binding,
                )
            )

    manifest_source = {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "repetition_runner_version": REPETITION_RUNNER_VERSION,
        "repetition_phase": repetition_phase,
        "source": _thaw_json(harness_source),
    }
    if resource_telemetry is not None:
        manifest_source["resource_telemetry"] = resource_telemetry.descriptor()

    manifest = run_manifest(
        run_id,
        host=host.reference,
        runtime=runtime.reference,
        model=model.reference,
        effective_configs=[record.reference for record in config_order],
        benchmarks=[benchmark.reference],
        evaluators=[record.reference for record in evaluator_identities],
        trials=[item.trial.reference for item in planned],
        execution_bindings=[item.binding.reference for item in planned],
        harness_source=manifest_source,
    )

    if execution_interface is not None:
        evidence_store.persist(execution_interface)
    evidence_store.persist_many(
        (
            host,
            runtime,
            model,
            benchmark,
            *config_order,
            *evaluator_identities,
            *(item.trial for item in planned),
            *(item.binding for item in planned),
            manifest,
        )
    )

    if driver_binding.execution_kind == "subprocess":
        raise OrchestrationBlocked(
            "subprocess repetition binding was preflighted and sealed, but no BL-7-routed model-driver adapter exists; direct-call fallback is forbidden"
        )

    execution_records: list[SealedEvidence] = []
    telemetry_records: list[SealedEvidence] = []
    case_records: list[SealedEvidence] = []
    evaluation_records: list[SealedEvidence] = []

    for item in planned:
        case_id = str(item.case["case_id"])
        started_at = clock()
        if not isinstance(started_at, str) or not started_at:
            raise ValueError("clock must return non-empty timestamp strings")
        telemetry_record: SealedEvidence | None = None

        if pack.level == "L2":
            assert item.workspace is not None
            assert execution_interface is not None
            current_sha256 = _initial_workspace_sha256(item.workspace)
            if current_sha256 != item.initial_workspace_sha256:
                raise OrchestrationBlocked(
                    f"workspace for {case_id!r} ordinal {item.trial.payload['ordinal']} changed after manifest sealing"
                )
            capture: SafeResourceTelemetryCapture | None = None
            if resource_telemetry is not None:
                capture = SafeResourceTelemetryCapture(
                    resource_telemetry,
                    _derived_id("telemetry", item.trial.sha256),
                    case_id,
                    item.trial.reference,
                )
                capture.start()
            try:
                result = run_bounded_tool_harness(
                    trace_logical_id=_derived_id("tooltrace", item.trial.sha256),
                    case_definition=_bl6_execution_case(item.execution_case),
                    effective_config=item.effective,
                    workspace_root=item.workspace.root,
                    readable_paths=item.workspace.readable_paths,
                    writable_paths=item.workspace.writable_paths,
                    driver=driver_binding.driver,
                )
            finally:
                finished_at = clock()
                if capture is not None:
                    telemetry_record = capture.stop()
            status = result.status
            stop_reason = result.stop_reason
            terminal_output = None if result.terminal_output is None else _thaw_json(result.terminal_output)
            trace = seal_evidence(
                "tool_execution_trace",
                result.trace.logical_id,
                {
                    **_thaw_json(result.trace.payload),
                    "execution_interface": execution_interface.reference.to_dict(),
                },
            )
            validate_tool_execution_trace(trace)
            metrics = {
                "execution_mode": "lab_tool",
                "stop_reason": stop_reason,
                "repetition_phase": repetition_phase,
                "trial_ordinal": item.trial.payload["ordinal"],
                "tool_summary": _thaw_json(trace.payload["summary"]),
            }
            if telemetry_record is not None:
                metrics["resource_telemetry_summary"] = _thaw_json(
                    telemetry_record.payload["summary"]
                )
        else:
            status, stop_reason, terminal_output, trace = _intrinsic_trace(
                logical_id=_derived_id("intrinsic", item.trial.sha256),
                case_definition=item.execution_case,
                driver=driver_binding.driver,
            )
            metrics = {
                "execution_mode": "intrinsic",
                "stop_reason": stop_reason,
                "repetition_phase": repetition_phase,
                "trial_ordinal": item.trial.payload["ordinal"],
                "model_turns": 1,
            }
            finished_at = clock()

        if not isinstance(finished_at, str) or not finished_at:
            raise ValueError("clock must return non-empty timestamp strings")
        evidence_store.persist(trace)
        execution_records.append(trace)
        execution_evidence = {
            "primary": trace.reference.to_dict(),
            "execution_binding": item.binding.reference.to_dict(),
        }
        if telemetry_record is not None:
            evidence_store.persist(telemetry_record)
            telemetry_records.append(telemetry_record)
            execution_evidence["resource_telemetry"] = telemetry_record.reference.to_dict()
        case_record = case_result(
            _derived_id("case", manifest.sha256, item.trial.sha256),
            manifest=manifest.reference,
            benchmark=benchmark.reference,
            trial=item.trial.reference,
            case_id=case_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            execution_evidence=execution_evidence,
            terminal_output=terminal_output,
        )
        evidence_store.persist(case_record)
        case_records.append(case_record)

        if status == "error" and stop_reason == "model_driver_error":
            raise OrchestrationBlocked(
                f"model driver failed for case {case_id}; "
                "qualification evidence was preserved and scoring was stopped"
            )

        extras = supplemental_evidence.get(case_id, ())
        if isinstance(extras, (str, bytes, bytearray)):
            raise ValueError("supplemental_evidence values must be sequences")
        for extra in extras:
            if not isinstance(extra, SealedEvidence):
                raise ValueError("supplemental_evidence must contain SealedEvidence values")
        observed_telemetry = () if telemetry_record is None else (telemetry_record,)
        interface_evidence = () if execution_interface is None else (execution_interface,)
        available = (
            host,
            runtime,
            model,
            benchmark,
            item.effective,
            item.trial,
            *interface_evidence,
            item.binding,
            manifest,
            trace,
            *observed_telemetry,
            *tuple(extras),
        )
        for evaluator_ref in item.case["evaluators"]:
            evaluator_id = str(evaluator_ref["evaluator_id"])
            contract_version = str(evaluator_ref["contract_version"])
            definition = evaluator_registry.resolve(evaluator_id, contract_version)
            evaluation = evaluator_registry.evaluate(
                _derived_id(
                    "evaluation",
                    case_record.sha256,
                    evaluator_id,
                    contract_version,
                ),
                evaluator_id=evaluator_id,
                contract_version=contract_version,
                case_definition=item.case,
                case_result_record=case_record,
                supplemental_evidence=_supplemental_for_definition(definition, available),
            )
            evidence_store.persist(evaluation)
            evaluation_records.append(evaluation)

    return RepeatedRun(
        repetition_phase=repetition_phase,
        planned_counts=planned_counts,
        benchmark=benchmark,
        effective_configs=tuple(config_order),
        trials=tuple(item.trial for item in planned),
        execution_bindings=tuple(item.binding for item in planned),
        manifest=manifest,
        execution_evidence=tuple(execution_records),
        resource_telemetry=tuple(telemetry_records),
        case_results=tuple(case_records),
        evaluation_results=tuple(evaluation_records),
    )
