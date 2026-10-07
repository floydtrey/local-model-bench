"""Gated Flash-Next campaign on the accepted Benchmark Lab V2 primitives.

Run ``python -m localbench.v2.flashnext_campaign --help``. No model is started by
importing this module or by the validate/preflight stages. The accepted batteries
and evaluators are read verbatim; smoke is an explicitly identified projection.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .compatibility import CompatibilityDimension, compatibility_observation, seal_compatibility_observation
from .configuration import CONFIG_SPEC_VERSION, resolve_effective_configuration
from .contracts import EvidenceRef, SealedEvidence, canonical_json_bytes, sha256_json
from .flashnext_runtime import (
    BASE_COMMIT, CAMPAIGN_NAME, FlashNextBlocked, OwnedFlashNextServer,
    file_digest, preflight_identity, read_json, validate_profile, validate_sources,
    write_bytes_once, write_json_once,
)
from .flashnext_gates import verify_gate, verify_shared_run_for_roles
from .llama_cpp_driver import LLAMA_CPP_ADAPTER_ID, LlamaCppChatDriver, llama_cpp_adapter_resolution
from .orchestrator import ConfigurationBinding, DriverBinding, EvidenceStore, WorkspaceBinding
from .repetition import run_v2_repetitions
from .reporting import aggregate_repeated_run, render_aggregate_csv, render_aggregate_markdown
from .resource_telemetry import system_resource_telemetry_binding
from .resource_telemetry_integration import SafeResourceTelemetryCapture
from .shared_battery import register_shared_battery_evaluators
from .shared_l2_battery import build_shared_l2_registry, materialize_workspace
from .tool_harness import BOUNDED_FILE_SURFACE_ID, BOUNDED_FILE_TOOL_SCHEMA_SHA256, ModelTurnResponse


SMOKE_CASES = {"L0": ("structured-transformation",), "L1": ("evidence-traceability",),
               "L2": ("read-transform-write",)}
ROLES = ("planner", "governor", "worker", "tester", "reviewer")
SHARED_TOOL_LIMITS = {"shared-l2-tools-3-v1": 3, "shared-l2-tools-4-v1": 4, "shared-l2-tools-5-v1": 5}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def json_copy(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def generation_spec(profile: Mapping[str, Any], *, tools=False, response_format="text") -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SPEC_VERSION, "comparison_mode": "strict",
        "generation": {"context_tokens": profile["context_tokens"], **profile["generation"],
                       "response_format": {"mode": response_format, "schema": None}},
        "execution": {"timeout_seconds": profile["limits"]["case_seconds"], "retries": 0,
                      "retry_delay_seconds": 0, "concurrency": 1,
                      "model_residency": {"mode": "unload_after_model", "keep_alive_seconds": 0},
                      "network_policy": "provider_only"},
        "tool_surface": {"id": BOUNDED_FILE_SURFACE_ID if tools else "none",
                         "tools": ["read_file", "write_file"] if tools else [],
                         "max_tool_calls": profile["limits"]["max_tool_calls"] if tools else 0,
                         "schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256 if tools else None},
    }


def config_for(spec: Mapping[str, Any], foundation: Mapping[str, Any], logical_id: str):
    adapter = llama_cpp_adapter_resolution(spec, runtime=foundation["runtime"], model=foundation["model"],
                                           reasoning_transport="server_default", model_alias="C01")
    effective = resolve_effective_configuration(logical_id, runtime=foundation["runtime"], model=foundation["model"],
                                                 spec=spec, adapter_resolution=adapter)
    return adapter, effective


def pack_bytes(repo_root: Path, level: str, *, smoke: bool) -> tuple[bytes, dict[str, Any]]:
    relative = f"benchmark-packs/v2/shared-{level.lower()}-core-v1.json"
    original = (repo_root / relative).read_bytes()
    provenance = {"path": relative, "source_sha256": hashlib.sha256(original).hexdigest(),
                  "base_commit": BASE_COMMIT, "case_projection": None}
    if not smoke:
        return original, provenance
    pack = json.loads(original)
    selected = [case for case in pack["cases"] if case["case_id"] in SMOKE_CASES[level]]
    if len(selected) != len(SMOKE_CASES[level]):
        raise FlashNextBlocked(f"smoke projection cannot resolve accepted {level} cases")
    # Only enclosing pack identity and selected case list change. Every selected
    # case, evaluator and repetition declaration stays exactly as accepted.
    pack.update(pack_id=f"flashnext-interface-smoke-{level.lower()}", pack_version="1.0.0",
                name=f"Flash-Next {level} interface smoke projection",
                description="Explicit diagnostic projection of the frozen V2 shared battery; not the complete screen.",
                cases=selected)
    provenance["case_projection"] = list(SMOKE_CASES[level])
    return canonical_json_bytes(pack), provenance


def evidence_reference(path: Path, record: SealedEvidence, root: Path) -> dict[str, Any]:
    return {"path": path.relative_to(root).as_posix(), "reference": record.reference.to_dict()}


def write_derived(path: Path, *, schema_version: str, payload: Mapping[str, Any]) -> None:
    write_json_once(path, {"schema_version": schema_version, "payload": payload, "sha256": sha256_json(payload)})


def load_derived(path: Path, schema_version: str) -> dict[str, Any]:
    value = read_json(path)
    if value.get("schema_version") != schema_version or sha256_json(value.get("payload")) != value.get("sha256"):
        raise FlashNextBlocked(f"invalid or changed derived evidence: {path}")
    return value["payload"]


class SharedDriverRouter:
    """Select the already sealed case config and capture per-trial measurements."""

    def __init__(self, *, pack, configs, foundation, store, output_dir, profile, server, progress,
                 driver_class=LlamaCppChatDriver):
        self.pack, self.configs, self.foundation, self.store = pack, configs, foundation, store
        self.output_dir, self.profile, self.server, self.progress = output_dir, profile, server, progress
        self.driver_class = driver_class
        self.counts = {}
        self.current = None
        self.driver = None
        self.capture = None
        self.timer = None
        self.rows = []
        self.telemetry = []

    def _begin(self, request):
        self.close()
        ordinal = self.counts.get(request.case_id, 0) + 1
        self.counts[request.case_id] = ordinal
        trials = []
        for path in (self.store.root / "records/trial_identity").glob("*.json"):
            trial = SealedEvidence.from_dict(read_json(path))
            if trial.payload["case_id"] == request.case_id and trial.payload["ordinal"] == ordinal:
                trials.append(trial)
        if len(trials) != 1:
            raise FlashNextBlocked("cannot bind driver measurement to one presealed V2 trial")
        trial = trials[0]
        case = next(c for c in self.pack["cases"] if c["case_id"] == request.case_id)
        config = self.configs[case["requirements"]["configuration_profile"]]
        case_dir = self.output_dir / "observations" / f"{request.case_id}-{ordinal:02d}"
        self.driver = self.driver_class(config, case_dir / "raw")
        self.current = {"case_id": request.case_id, "ordinal": ordinal, "trial": trial.reference.to_dict(),
                        "started_at": utc_now(), "started_monotonic": time.monotonic(),
                        "effective_config": config.reference.to_dict(), "observations": [], "case_directory": str(case_dir)}
        self.progress(f"{self.pack['level']} {request.case_id} trial {ordinal}: started")
        if self.server is not None:
            self.timer = self.server.watchdog(self.profile["limits"]["case_seconds"])
        # BL-8B already captures L2 telemetry. Add the same V2 resource trace to
        # intrinsic cases without modifying the accepted repetition runner.
        if self.pack["level"] != "L2":
            binding = system_resource_telemetry_binding(sampling_interval_ms=self.profile["limits"]["telemetry_interval_ms"])
            self.capture = SafeResourceTelemetryCapture(binding, f"flashnext-resource-{trial.sha256[:24]}", request.case_id, trial.reference)
            self.capture.start()

    def __call__(self, request):
        if request.turn == 1:
            self._begin(request)
        if self.current is None or self.driver is None:
            raise FlashNextBlocked("model turn has no active case binding")
        try:
            result = self.driver(request)
        except BaseException:
            self._sync_observations()
            self.close()
            raise
        self._sync_observations()
        metadata = json_copy(result.provider_metadata or {})
        calls = getattr(self.server, "model_request_count", 0) if self.server is not None else 0
        metadata["residency_observation"] = "first_request_after_process_load" if calls == 0 else "warm_resident"
        metadata["os_file_cache_state"] = "unmeasured"
        self.current["observations"][-1].update(
            residency_observation=metadata["residency_observation"], os_file_cache_state="unmeasured")
        if self.server is not None:
            self.server.model_request_count = calls + 1
        wrapped = ModelTurnResponse(content=result.content, tool_calls=result.tool_calls,
                                    reasoning=result.reasoning, provider_metadata=metadata)
        if not result.tool_calls:
            self.close()
        return wrapped

    def _sync_observations(self):
        observed = json_copy(self.driver.observations)
        for previous, current in zip(self.current["observations"], observed):
            for key in ("residency_observation", "os_file_cache_state"):
                if key in previous:
                    current[key] = previous[key]
        self.current["observations"] = observed

    def close(self):
        if self.current is None:
            return
        finished_monotonic, finished_at = time.monotonic(), utc_now()
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.capture is not None:
            trace = self.capture.stop()
            self.store.persist(trace)
            self.telemetry.append(trace)
            self.current["resource_telemetry"] = trace.reference.to_dict()
            self.current["resource_summary"] = json_copy(trace.payload["summary"])
            self.capture = None
        self.current["wall_seconds"] = finished_monotonic - self.current.pop("started_monotonic")
        self.current["finished_at"] = finished_at
        self.rows.append(self.current)
        self.current = None


def _finite_sum(observations, key):
    values = [observation.get(key) for observation in observations]
    if not values or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
        return None
    return sum(values)


def measurement_rows(router: SharedDriverRouter, run=None) -> list[dict[str, Any]]:
    rows = []
    for raw in router.rows:
        obs = raw["observations"]
        output_tokens = _finite_sum(obs, "output_tokens")
        generation_seconds = _finite_sum(obs, "generation_seconds")
        predicted = [item.get("timings", {}).get("predicted_n") if isinstance(item.get("timings"), Mapping) else None for item in obs]
        generation_tokens = sum(predicted) if predicted and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in predicted) else None
        generation_rate = generation_tokens / generation_seconds if generation_tokens is not None and generation_seconds and generation_seconds > 0 else None
        if generation_rate is None and len(obs) == 1:
            generation_rate = obs[0].get("generation_tokens_per_second")
        row = {key: raw[key] for key in ("case_id", "ordinal", "trial", "effective_config", "started_at", "finished_at", "wall_seconds")}
        row.update({"prompt_tokens": _finite_sum(obs, "prompt_tokens"), "output_tokens": output_tokens,
                    "generation_seconds": generation_seconds,
                    "generation_tokens": generation_tokens, "generation_tokens_per_second": generation_rate,
                    "generation_throughput_sources": [item.get("generation_throughput_source") for item in obs],
                    "residency_observation": obs[0].get("residency_observation") if obs else None,
                    "os_file_cache_state": "unmeasured", "fresh_conversation": True,
                    "raw_evidence_directory": str(Path(raw["case_directory"]) / "raw"),
                    "output_tokens_per_wall_second": output_tokens / raw["wall_seconds"]
                    if output_tokens is not None and raw["wall_seconds"] > 0 else None,
                    "prompt_processing_seconds": _finite_sum(obs, "prompt_processing_seconds"),
                    "output_words": _finite_sum(obs, "output_words"), "output_characters": _finite_sum(obs, "output_characters"),
                    "reasoning_words": _finite_sum(obs, "reasoning_words"), "reasoning_tokens": _finite_sum(obs, "reasoning_tokens"),
                    "tool_calls": _finite_sum(obs, "tool_call_count"), "model_turns": len(obs),
                    "truncated": any(item.get("truncated") for item in obs),
                    "runtime_errors": [item.get("category") for item in obs if item.get("status") != "success"],
                    "raw_observations": obs, "attempts": 1, "automatic_retries": 0,
                    "resource_summary": raw.get("resource_summary"), "correctness": "not_scored",
                    "runtime_compatibility": "fail" if any(item.get("status") != "success" for item in obs) else "pass"})
        if run is not None:
            case = next(c for c in run.case_results if c.payload["trial"] == raw["trial"])
            evaluation = next(e for e in run.evaluation_results if e.payload["case"] == case.reference.to_dict())
            row.update(case_result=case.reference.to_dict(), evaluation_result=evaluation.reference.to_dict(),
                       correctness=evaluation.payload["verdict"], execution_status=case.payload["status"],
                       stop_reason=case.payload["metrics"].get("stop_reason"),
                       resource_summary=json_copy(case.payload["metrics"].get("resource_telemetry_summary", row["resource_summary"])))
        rows.append(row)
    return rows


def compatibility_records(run, interface, store) -> list[SealedEvidence]:
    records = []
    if run.benchmark.payload["level"] != "L2":
        return records
    for trace, case, evaluation in zip(run.execution_evidence, run.case_results, run.evaluation_results):
        requests = [event["payload"] for event in trace.payload["events"] if event["event_type"] == "tool_request"]
        results = [event["payload"] for event in trace.payload["events"] if event["event_type"] == "tool_result"]
        native = bool(requests)
        allowed_names = all(call.get("name") in {"read_file", "write_file"} for call in requests)
        checks = {check["id"]: check["passed"] for check in evaluation.payload.get("checks", ())}
        # Successful end-to-end work is evidence of sufficient selection/arguments.
        # Otherwise retain unknown unless the actual bounded trace proves a fault.
        success = evaluation.payload["verdict"] == "pass"
        semantic = "pass" if success and native else ("fail" if native and not allowed_names else "unknown")
        arguments = "pass" if success and native else "unknown"
        failures = [item for item in results if item.get("result", {}).get("ok") is False]
        if failures:
            arguments = "unknown"  # missing files and authorized refusals can be intentional
        diagnostic = compatibility_observation(
            case_id=case.payload["case_id"], turn=1, execution_interface=interface.reference,
            semantic_tool_selection=CompatibilityDimension(semantic, "Derived conservatively from accepted deterministic checks and actual tool trace.", (trace.reference, evaluation.reference)),
            argument_correctness=CompatibilityDimension(arguments, "No semantics are inferred from unparsed prose.", (trace.reference, evaluation.reference)),
            protocol_parser_compatibility=CompatibilityDimension("pass" if native else "unknown",
                "Native structured calls crossed the existing BL-6 boundary." if native else "No native call observed; inspect raw output before attributing a model or parser failure.", (trace.reference,)),
            end_to_end_success=CompatibilityDimension("pass" if success else "fail", "Unchanged shared deterministic evaluator result.", (case.reference, evaluation.reference)),
            diagnostic_metadata={"native_call_count": len(requests), "native_tool_names": [r.get("name") for r in requests],
                                 "accepted_check_results": checks, "intrinsic_model_failure_inferred": False})
        record = seal_compatibility_observation(f"flashnext-compat-{case.sha256[:24]}", diagnostic)
        store.persist(record)
        records.append(record)
    return records


def _csv_view(rows):
    fields = ["level", "case_id", "ordinal", "correctness", "runtime_compatibility", "execution_status", "wall_seconds",
              "prompt_tokens", "output_tokens", "generation_seconds", "generation_tokens_per_second",
              "output_tokens_per_wall_second", "output_words", "reasoning_words", "tool_calls", "model_turns", "truncated",
              "residency_observation"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def run_shared(*, repo_root: Path, output_dir: Path, foundation, profile, server, stage: str, progress=print,
               driver_class=LlamaCppChatDriver) -> dict[str, Any]:
    smoke = stage == "smoke"
    phase = "qualification" if stage == "shared-qualification" else "screen"
    completed, references, all_rows, compatibility = [], [], [], []
    driver_source = Path(sys.modules[LlamaCppChatDriver.__module__].__file__)
    for level in ("L0", "L1", "L2"):
        source, provenance = pack_bytes(repo_root, level, smoke=smoke)
        pack = json.loads(source)
        folder = output_dir / level.lower()
        folder.mkdir(parents=True, exist_ok=True)
        write_bytes_once(folder / "pack-input.json", source)
        write_json_once(folder / "pack-provenance.json", provenance)
        store = EvidenceStore(folder / "evidence")
        bindings, configs = {}, {}
        for case in pack["cases"]:
            name = case["requirements"]["configuration_profile"]
            if name in configs:
                continue
            spec = generation_spec(profile, tools=level == "L2", response_format=case["requirements"]["response_contract"]["mode"])
            if level == "L2":
                if name not in SHARED_TOOL_LIMITS:
                    raise FlashNextBlocked(f"unknown accepted L2 configuration profile: {name}")
                spec["tool_surface"]["max_tool_calls"] = SHARED_TOOL_LIMITS[name]
            adapter, effective = config_for(spec, foundation, f"flashnext-{name}")
            bindings[name] = ConfigurationBinding(name, spec=spec, adapter_resolution=adapter,
                                                   effective_logical_id=effective.logical_id, expected_effective_config=effective.reference)
            configs[name] = effective
        registry = build_shared_l2_registry()
        register_shared_battery_evaluators(registry)
        router = SharedDriverRouter(pack=pack, configs=configs, foundation=foundation, store=store,
                                    output_dir=folder, profile=profile, server=server, progress=progress, driver_class=driver_class)
        def workspace_factory(case_id, ordinal):
            materialized = materialize_workspace(repo_root, case_id, folder / "workspaces" / f"{case_id}-{ordinal:02d}")
            return WorkspaceBinding(**materialized)
        run = None
        try:
            run = run_v2_repetitions(
                run_id=f"flashnext-{stage}-{level.lower()}", repetition_phase=phase, pack_source=source,
                pack_source_locator=f"campaigns/{CAMPAIGN_NAME}/smoke-{level.lower()}" if smoke else provenance["path"],
                host=foundation["host"], runtime=foundation["runtime"], model=foundation["model"],
                configuration_bindings=bindings, evaluator_registry=registry,
                driver_binding=DriverBinding("flashnext-llama-cpp-chat-v1", file_digest(driver_source), router, execution_interface=foundation["interface"]),
                evidence_store=store, harness_source={"campaign": CAMPAIGN_NAME, "v2_base_commit": BASE_COMMIT,
                    "implementation_sha256": foundation["fingerprint"]["implementation_sha256"], "accepted_pack": provenance,
                    "runtime_fallback": "forbidden", "role_qualification_claim": False},
                workspace_factory=workspace_factory if level == "L2" else None,
                asset_loader=lambda asset: (repo_root / asset["source_locator"]).read_bytes(),
                resource_telemetry=system_resource_telemetry_binding(sampling_interval_ms=profile["limits"]["telemetry_interval_ms"]) if level == "L2" else None)
        finally:
            router.close()
            rows = measurement_rows(router, run)
            for row in rows:
                row["level"] = level
            all_rows.extend(rows)
            write_derived(folder / "measurements.json", schema_version="flashnext-measurements:v1",
                          payload={"complete": run is not None, "level": level, "rows": rows,
                                   "generation_throughput_is_not_wall_throughput": True})
            write_bytes_once(folder / "measurements.csv", _csv_view(rows))
        aggregate = aggregate_repeated_run(f"flashnext-{stage}-{level.lower()}-aggregate", run)
        store.persist(aggregate)
        write_bytes_once(folder / "aggregate.md", render_aggregate_markdown(aggregate).encode("utf-8"))
        write_bytes_once(folder / "aggregate.csv", render_aggregate_csv(aggregate).encode("utf-8"))
        diagnostic = compatibility_records(run, foundation["interface"], store)
        compatibility.extend(diagnostic)
        completed.extend(run.case_results)
        progress(f"{level} complete: {len(run.case_results)} observations, {sum(e.payload['verdict'] == 'pass' for e in run.evaluation_results)} deterministic passes.")
    for path in sorted(output_dir.rglob("*.json")):
        if path.parent.parent.name == "records":
            record = SealedEvidence.from_dict(read_json(path))
            references.append(evidence_reference(path, record, output_dir))
    result = {"stage": stage, "completed_observations": len(completed), "rows": all_rows, "evidence": references,
              "all_correct": all(row["correctness"] == "pass" for row in all_rows),
              "native_tool_smoke_pass": bool(compatibility) and all(r.payload["dimensions"]["protocol_parser_compatibility"]["status"] == "pass" for r in compatibility),
              "role_qualified": False}
    write_derived(output_dir / "measurements.json", schema_version="flashnext-measurements:v1", payload=result)
    write_bytes_once(output_dir / "measurements.csv", _csv_view(all_rows))
    return result


def create_gate(*, output_dir: Path, stage: str, foundation, result, parent_gate=None, parent_smoke_run: Path | None = None) -> dict[str, Any]:
    expected = 3 if stage == "smoke" else 22
    passed = result["completed_observations"] == expected
    passed = passed and all(row.get("runtime_compatibility") == "pass"
                            and not row.get("truncated") and not row.get("runtime_errors") for row in result["rows"])
    passed = passed and result["native_tool_smoke_pass"]
    if stage != "smoke":
        passed = passed and all(
            row.get("execution_status") == "success"
            or (row.get("level") == "L2" and row.get("execution_status") == "resource_limit"
                and row.get("stop_reason") == "max_tool_calls")
            for row in result["rows"]
        )
    # Smoke and shared progression prove runtime/interface compatibility. Candidate
    # correctness and bounded L2 tool-loop exhaustion remain scored model behavior,
    # not infrastructure invalidation.
    artifacts = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and ("runtime" in path.relative_to(output_dir).parts or "raw" in path.relative_to(output_dir).parts):
            artifacts.append({"path": path.relative_to(output_dir).as_posix(), "sha256": file_digest(path), "bytes": path.stat().st_size})
    gate = {"stage": stage, "status": "pass" if passed else "blocked", "fingerprint": foundation["fingerprint"],
            "completed_observations": result["completed_observations"], "evidence": result["evidence"],
            "artifact_files": artifacts, "correctness_all_pass": result["all_correct"],
            "native_tool_smoke_pass": result["native_tool_smoke_pass"], "role_or_model_qualified": False,
            "parent_gate_sha256": sha256_json(parent_gate) if parent_gate else None,
            "parent_smoke_run": str(parent_smoke_run.resolve()) if parent_smoke_run else None,
            "gate_meaning": "bounded runtime/interface smoke passed; correctness reported separately" if stage == "smoke" else "complete shared screen with correctness reported separately"}
    write_derived(output_dir / "gate.json", schema_version="flashnext-campaign-gate:v1", payload=gate)
    return gate


def role_runner(*, foundation, profile, output_dir, campaign_root, server, roles, phase, governor_root, progress):
    from .flashnext_roles import run_role_campaign
    store = foundation["store"]
    counter = 0
    def driver_factory(spec, evidence_dir):
        nonlocal counter
        counter += 1
        _, effective = config_for(spec, foundation, f"flashnext-role-config-{sha256_json(spec)[:24]}")
        inner = LlamaCppChatDriver(effective, evidence_dir)
        class ResidentDriver:
            effective_config = effective
            @property
            def observations(self):
                return inner.observations
            def __call__(self, request):
                result = inner(request)
                metadata = json_copy(result.provider_metadata or {})
                count = getattr(server, "model_request_count", 0)
                server.model_request_count = count + 1
                metadata.update(residency_observation="first_request_after_process_load" if count == 0 else "warm_resident",
                                os_file_cache_state="unmeasured")
                return ModelTurnResponse(content=result.content, tool_calls=result.tool_calls, reasoning=result.reasoning,
                                         provider_metadata=metadata)
        return ResidentDriver()
    @contextlib.contextmanager
    def case_context(case_dir, trial):
        binding = system_resource_telemetry_binding(sampling_interval_ms=profile["limits"]["telemetry_interval_ms"])
        capture = SafeResourceTelemetryCapture(binding, f"flashnext-resource-{trial.sha256[:24]}", trial.payload["case_id"], trial.reference)
        timer = server.watchdog(profile["limits"]["case_seconds"])
        capture.start()
        try:
            yield capture
        finally:
            timer.cancel()
            trace = capture.stop()
            store.persist(trace)
            write_json_once(Path(case_dir) / "resource-telemetry-ref.json", trace.reference.to_dict())
    def role_progress(event):
        progress(f"Role {event.get('case_id', '')} trial {event.get('ordinal', '')}: {event.get('event', '')}"
                 + (f" ({event.get('status', event.get('runtime_compatibility', 'evidence saved'))})" if event.get("event") == "case_complete" else ""))
    return run_role_campaign(campaign_root=campaign_root, roles=roles, repetitions=1 if phase == "screen" else 3,
               foundation={key: foundation[key] for key in ("host", "runtime", "model", "interface")},
               base_config_spec=generation_spec(profile), driver_factory=driver_factory,
               evidence_store=store, output_dir=output_dir / "roles", governor_root=governor_root,
               case_context_factory=case_context, progress=role_progress)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Flash-Next V2 campaign. Default action validates setup without starting a model.")
    result.add_argument("stage", nargs="?", default="validate", choices=("validate", "preflight", "smoke", "shared-screen", "shared-qualification", "roles"))
    result.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    result.add_argument("--profile", type=Path)
    result.add_argument("--output-root", type=Path, help="default: local-state/flashnext-all-roles-v1; never reuse an existing run directory")
    result.add_argument("--smoke-run", type=Path, help="exact prior smoke run directory containing passing gate.json")
    result.add_argument("--shared-run", type=Path, help="exact completed shared-screen run directory")
    result.add_argument("--role", action="append", choices=(*ROLES, "all"), help="explicit role(s); all is opt-in")
    result.add_argument("--phase", choices=("screen", "qualification"), default="screen")
    result.add_argument("--governor-root", type=Path, help="canonical Governor repository containing docs/LAW.md, docs/STATE.md, docs/GENERAL_INTENT.md")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    campaign_root = repo_root / "campaigns" / CAMPAIGN_NAME
    profile_path = args.profile or campaign_root / "runtime-profile.json"
    output_dir = None
    def progress(message):
        print(f"[{utc_now()}] {message}", flush=True)
        if output_dir is not None:
            with (output_dir / "progress.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time": utc_now(), "message": message}) + "\n")
    try:
        profile = read_json(profile_path)
        validate_profile(profile)
        sources = validate_sources(repo_root, campaign_root)
        # Validate explicit stage selection before any hashing, subprocess, or load.
        if args.stage in {"shared-screen", "shared-qualification"} and args.smoke_run is None:
            raise FlashNextBlocked("--smoke-run is required; first run the bounded smoke")
        if args.stage in {"roles", "shared-qualification"} and args.shared_run is None:
            raise FlashNextBlocked("--shared-run is required; first complete the unchanged 22-case shared screen")
        if args.stage == "roles" and not args.role:
            raise FlashNextBlocked("select --role planner/governor/worker/tester/reviewer (or explicitly all)")
        roles = list(ROLES) if args.role and "all" in args.role else list(dict.fromkeys(args.role or []))
        if args.stage == "roles" and "governor" in roles and args.governor_root is None:
            raise FlashNextBlocked("Governor requires --governor-root; canonical Law/State/General Intent are not invented")
        if args.stage == "validate":
            print(json.dumps({"status": "pass", "stage": "validate", "model_started": False,
                              "candidate": profile["candidate_name"], "base_commit": BASE_COMMIT, **sources}, indent=2))
            return 0
        root = (args.output_root or repo_root / "local-state" / CAMPAIGN_NAME).resolve()
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{args.stage}-{uuid.uuid4().hex[:8]}"
        output_dir = root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        write_json_once(output_dir / "requested-campaign.json", {"stage": args.stage, "phase": args.phase,
            "roles": roles, "profile": profile, "sources": sources, "created_at": utc_now(),
            "smoke_run": str(args.smoke_run) if args.smoke_run else None, "shared_run": str(args.shared_run) if args.shared_run else None})
        progress(f"Evidence directory: {output_dir}")
        foundation = preflight_identity(profile=profile, repo_root=repo_root, campaign_root=campaign_root,
                                        output_dir=output_dir, progress=progress)
        if args.stage == "preflight":
            progress("Preflight passed. No model was loaded and no qualification was awarded.")
            return 0
        parent = None
        if args.stage in {"shared-screen", "shared-qualification"}:
            parent = verify_gate(args.smoke_run.resolve(), stage="smoke", fingerprint=foundation["fingerprint"], repo_root=repo_root)
        if args.stage == "roles":
            parent = verify_shared_run_for_roles(args.shared_run.resolve(), current_fingerprint=foundation["fingerprint"], repo_root=repo_root)
            write_json_once(output_dir / "shared-progression-receipt.json", parent)
        elif args.stage == "shared-qualification":
            parent = verify_gate(args.shared_run.resolve(), stage="shared-screen", fingerprint=foundation["fingerprint"], repo_root=repo_root)
        server = OwnedFlashNextServer(profile, output_dir / "runtime", progress=progress)
        # Smoke is bounded across startup + all three projected cases, not 600s
        # per request. Preflight artifact hashing is separately timed preparation.
        smoke_timer = server.watchdog(profile["limits"]["smoke_total_seconds"]) if args.stage == "smoke" else None
        try:
            with server:
                if args.stage == "roles":
                    result = role_runner(foundation=foundation, profile=profile, output_dir=output_dir,
                                         campaign_root=campaign_root, server=server, roles=roles, phase=args.phase,
                                         governor_root=args.governor_root, progress=progress)
                    if set(roles) == set(ROLES):
                        from .flashnext_review import write_review_package
                        package = write_review_package(
                            output_dir=output_dir, summary=result, profile=profile,
                            shared_run=args.shared_run, phase=args.phase,
                        )
                        result = {**result, "review_package": package}
                else:
                    result = run_shared(repo_root=repo_root, output_dir=output_dir, foundation=foundation,
                                         profile=profile, server=server, stage=args.stage, progress=progress)
                if server.expired:
                    raise FlashNextBlocked("campaign time budget expired; preserved partial evidence cannot unlock a gate")
        finally:
            if smoke_timer is not None:
                smoke_timer.cancel()
        # Log bytes are final before they are bound into a gate.
        if args.stage in {"smoke", "shared-screen"}:
            gate = create_gate(output_dir=output_dir, stage=args.stage, foundation=foundation, result=result, parent_gate=parent,
                               parent_smoke_run=args.smoke_run if args.stage == "shared-screen" else None)
            if gate["status"] != "pass":
                raise FlashNextBlocked("runtime/interface progression gate did not pass; inspect correctness and compatibility separately")
            progress(f"{args.stage} gate PASS. Model/role qualification remains separate. Gate: {output_dir / 'gate.json'}")
        else:
            write_derived(output_dir / "run-summary.json", schema_version="flashnext-stage-summary:v1", payload=result)
            progress(f"{args.stage} finished. Review the preserved role/test evidence before declaring any role qualified.")
        print(f"RUN_DIR={output_dir}", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        if output_dir is not None:
            write_json_once(output_dir / "failure.json", {"status": "blocked", "error_type": type(exc).__name__,
                            "detail": str(exc), "intrinsic_model_failure_inferred": False, "time": utc_now()})
        print(f"BLOCKED: {exc}", file=sys.stderr, flush=True)
        if output_dir is not None:
            print(f"Preserved evidence: {output_dir}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
