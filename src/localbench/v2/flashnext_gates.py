"""Verify the complete evidence behind a Flash-Next progression gate.

A gate is a content-closure check, not a signature or a model qualification.
The caller supplies the freshly verified runtime/configuration fingerprint. This
module checks its preserved sources, linked V2 records, deterministic evaluations
and raw HTTP sidecars before allowing the next bounded stage.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from .benchmark_pack import parse_benchmark_pack
from .configuration import resolve_effective_configuration
from .contracts import EvidenceRef, SealedEvidence, canonical_json_bytes, sha256_json
from .execution_interface import validate_execution_interface_identity
from .flashnext_runtime import BASE_COMMIT, CAMPAIGN_NAME, FlashNextBlocked, file_digest, read_json
from .llama_cpp_driver import LLAMA_CPP_ADAPTER_ID, _messages, _metrics, _strict_json, llama_cpp_adapter_resolution
from .orchestrator import (
    _execution_case, _resolve_assets, _supplemental_for_definition,
    _validate_case_configuration, validate_intrinsic_execution_trace,
)
from .shared_battery import register_shared_battery_evaluators
from .shared_l2_battery import build_shared_l2_registry, workspace_specs
from .tool_harness import BOUNDED_FILE_TOOL_DEFINITIONS, ModelTurnRequest, ToolCall, validate_tool_execution_trace


_SMOKE_CASES = {"L0": ("structured-transformation",), "L1": ("evidence-traceability",),
                "L2": ("read-transform-write",)}
_REUSABLE = {"host_profile", "runtime_profile", "model_identity", "execution_interface_identity",
             "effective_runtime_config", "evaluator_identity"}
_RECORD_TYPES = _REUSABLE | {
    "benchmark_input", "trial_identity", "execution_binding", "run_manifest", "case_result",
    "evaluation_result", "intrinsic_execution_trace", "tool_execution_trace",
    "tool_compatibility_observation", "resource_telemetry_trace", "aggregate_report",
}
_TOOL_LIMITS = {"shared-l2-tools-3-v1": 3, "shared-l2-tools-4-v1": 4, "shared-l2-tools-5-v1": 5}


def _require(condition: Any, detail: str) -> None:
    if not condition:
        raise FlashNextBlocked(f"gate evidence verification: {detail}")


def _copy(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _same(left: Any, right: Any) -> bool:
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _path(root: Path, relative: Any) -> Path:
    _require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
             "invalid relative evidence path")
    local = Path(relative)
    _require(not local.is_absolute() and ".." not in local.parts and local.as_posix() == relative,
             f"escaping or noncanonical evidence path: {relative}")
    path = (root / local).resolve()
    _require(path.is_relative_to(root.resolve()) and path.is_file(), f"missing evidence: {relative}")
    return path


def _key(reference: Any) -> tuple[str, str, str]:
    ref = reference.reference if isinstance(reference, SealedEvidence) else EvidenceRef.from_dict(reference)
    return ref.record_type, ref.logical_id, ref.sha256


def _reference_keys(values: Any) -> set[tuple[str, str, str]]:
    _require(isinstance(values, (list, tuple)), "reference list is absent")
    keys = [_key(value) for value in values]
    _require(len(keys) == len(set(keys)), "duplicate reference in evidence relationship")
    return set(keys)


def _nested_references(value: Any):
    if isinstance(value, Mapping):
        if set(value) == {"record_type", "logical_id", "sha256"}:
            yield value
        else:
            for item in value.values():
                yield from _nested_references(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _nested_references(item)


class _Records:
    def __init__(self, root: Path, references: Any):
        _require(isinstance(references, list) and references, "no immutable supporting evidence")
        self.records: dict[tuple[str, str, str], SealedEvidence] = {}
        self.by_type: dict[str, list[SealedEvidence]] = defaultdict(list)
        paths, logical = set(), {}
        for item in references:
            path = _path(root, item.get("path"))
            relative = path.relative_to(root).as_posix()
            _require(relative not in paths, "duplicate evidence path")
            paths.add(relative)
            record = SealedEvidence.from_dict(read_json(path))
            _require(record.record_type in _RECORD_TYPES, "foreign record type in shared gate")
            key = _key(record)
            _require(key == _key(item["reference"]), "evidence identity mismatch")
            _require(path.parent.name == record.record_type and path.parent.parent.name == "records"
                     and path.name == f"{record.sha256}.json", "record is outside its content-addressed location")
            name = key[:2]
            _require(name not in logical or logical[name] == key, "conflicting evidence with one logical identity")
            logical[name] = key
            if key in self.records:
                _require(record.record_type in _REUSABLE, f"duplicate {record.record_type} evidence")
            else:
                self.records[key] = record
                self.by_type[record.record_type].append(record)
        actual = {path.relative_to(root).as_posix() for path in root.rglob("*.json")
                  if path.is_file() and path.parent.parent.name == "records"}
        _require(paths == actual, "record inventory is incomplete or contains foreign paths")
        for record in self.records.values():
            for ref in _nested_references(record.payload):
                self.get(ref)

    def get(self, reference: Any, expected: str | None = None) -> SealedEvidence:
        key = _key(reference)
        _require(key in self.records, f"unresolved {key[0]} reference")
        _require(expected is None or key[0] == expected, f"expected {expected} reference")
        return self.records[key]

    def one(self, record_type: str) -> SealedEvidence:
        values = self.by_type[record_type]
        _require(len(values) == 1, f"expected exactly one {record_type} identity")
        return values[0]


def _packs(repo_root: Path, root: Path, stage: str):
    lock = read_json(repo_root / "campaigns" / CAMPAIGN_NAME / "accepted-battery-lock.json")
    _require(lock.get("base_commit") == BASE_COMMIT, "accepted battery lock has a different lineage")
    for item in lock["files"]:
        _require(file_digest(_path(repo_root, item["path"])) == item["sha256"], "accepted battery/source drift")
    result = {}
    for level in ("L0", "L1", "L2"):
        relative = f"benchmark-packs/v2/shared-{level.lower()}-core-v1.json"
        raw = (repo_root / relative).read_bytes()
        provenance = {"path": relative, "source_sha256": hashlib.sha256(raw).hexdigest(),
                      "base_commit": BASE_COMMIT, "case_projection": None}
        if stage == "smoke":
            pack = json.loads(raw)
            selected = [case for case in pack["cases"] if case["case_id"] in _SMOKE_CASES[level]]
            _require(len(selected) == len(_SMOKE_CASES[level]), "smoke source cases are absent")
            pack.update(pack_id=f"flashnext-interface-smoke-{level.lower()}", pack_version="1.0.0",
                        name=f"Flash-Next {level} interface smoke projection",
                        description="Explicit diagnostic projection of the frozen V2 shared battery; not the complete screen.",
                        cases=selected)
            raw = canonical_json_bytes(pack)
            provenance["case_projection"] = list(_SMOKE_CASES[level])
        _require(_path(root, f"{level.lower()}/pack-input.json").read_bytes() == raw,
                 f"{level} preserved pack is not the accepted source/projection")
        _require(_same(read_json(_path(root, f"{level.lower()}/pack-provenance.json")), provenance),
                 f"{level} pack provenance changed")
        result[level] = parse_benchmark_pack(raw), provenance
    return result


def _artifacts(root: Path, items: Any):
    _require(isinstance(items, list) and items, "no preserved raw runtime/tool artifacts")
    paths = set()
    for item in items:
        path = _path(root, item.get("path"))
        relative = path.relative_to(root).as_posix()
        _require(relative not in paths, "duplicate raw artifact path")
        paths.add(relative)
        _require(file_digest(path) == item.get("sha256") and path.stat().st_size == item.get("bytes"),
                 f"raw artifact changed: {relative}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
              and ({"runtime", "raw"} & set(path.relative_to(root).parts))}
    _require(paths == actual, "raw runtime/tool artifact inventory is incomplete")
    observations = {}
    for relative in sorted(paths):
        if Path(relative).name != "observation.json" or "raw" not in Path(relative).parts:
            continue
        path = root / relative
        metadata = read_json(path)
        key = (metadata.get("case_id"), metadata.get("turn"), metadata.get("effective_config_sha256"))
        _require(key not in observations, "duplicate raw model-turn observation")
        _require(metadata.get("status") == "success" and metadata.get("category") is None
                 and metadata.get("http_status") == 200 and metadata.get("response_complete") is True
                 and metadata.get("truncated") is False and metadata.get("finish_reason") in {"stop", "tool_calls"}
                 and metadata.get("tool_text_diagnostic") is None,
                 "runtime/parser failure, incomplete response, or truncation cannot unlock a gate")
        raw_root = path.parent.parent
        _require(raw_root.name == "raw" and _path(raw_root, metadata.get("observation_file")) == path,
                 "raw observation location does not match its sidecar")
        artifacts = metadata.get("artifacts", {})
        _require(set(artifacts) == {"request_body", "request_metadata", "response_body", "response_metadata"},
                 "raw HTTP observation is incomplete")
        resolved = {}
        for name, descriptor in artifacts.items():
            artifact = _path(raw_root, descriptor.get("path"))
            _require(artifact.parent == path.parent and artifact.relative_to(root).as_posix() in paths,
                     "raw observation refers to a foreign or unbound sidecar")
            _require(file_digest(artifact) == descriptor.get("sha256")
                     and artifact.stat().st_size == descriptor.get("size_bytes"), "raw sidecar hash/size mismatch")
            resolved[name] = artifact
        observations[key] = (metadata, resolved)
    _require(observations, "no raw model-turn observations")
    return observations


def _http_turn(request_value, response, effective, observations, consumed):
    request = ModelTurnRequest(**request_value)
    key = (request.case_id, request.turn, effective.sha256)
    _require(key in observations and key not in consumed, "missing or reused raw turn evidence")
    consumed.add(key)
    metadata, artifacts = observations[key]
    provider = response.get("provider_metadata", {})
    _require(all(key in provider and _same(value, provider[key]) for key, value in metadata.items()),
             "trace provider metadata differs from raw observation")
    _require(metadata.get("adapter_id") == LLAMA_CPP_ADAPTER_ID, "foreign runtime adapter observation")
    static = effective.payload["settings"]["adapter_resolution"]["effective_request"]
    wire = _copy(static["parameters"])
    wire.update(model=static["model"], messages=_messages(request), stream=False, n=1)
    if request.tools:
        wire.update(tools=[{"type": "function", "function": {"name": tool["name"], "description": tool["description"],
                          "parameters": _copy(tool["input_schema"])}} for tool in request.tools],
                    tool_choice="auto", parallel_tool_calls=True)
    _require(artifacts["request_body"].read_bytes() == canonical_json_bytes(wire),
             "raw request differs from sealed model-turn/configuration")
    request_meta, response_meta = read_json(artifacts["request_metadata"]), read_json(artifacts["response_metadata"])
    _require(request_meta.get("method") == "POST" and request_meta.get("url") == static["base_url"] + static["path"]
             and response_meta.get("status") == 200, "raw HTTP endpoint or response status changed")
    raw = _strict_json(artifacts["response_body"].read_bytes())
    _require(isinstance(raw, dict) and raw.get("error") is None and raw.get("truncated") is not True
             and raw.get("model") == static["model"] == "C01", "raw runtime response identity/error mismatch")
    choices = raw.get("choices")
    _require(isinstance(choices, list) and len(choices) == 1 and type(choices[0].get("index")) is int and choices[0]["index"] == 0,
             "raw response choices are not the qualified contract")
    choice, message = choices[0], choices[0].get("message", {})
    calls = message.get("tool_calls", [])
    calls = [] if calls is None else calls
    _require(isinstance(calls, list), "raw native tool_calls must be an array")
    _require(message.get("content") is None or isinstance(message["content"], str), "raw assistant content has an invalid type")
    _require(message.get("reasoning_content") is None or isinstance(message["reasoning_content"], str), "raw reasoning has an invalid type")
    _require(calls or message.get("content") is not None, "raw response has neither content nor native calls")
    _require(choice.get("finish_reason") == ("tool_calls" if calls else "stop")
             and metadata["finish_reason"] == choice["finish_reason"] and message.get("role") == "assistant"
             and message.get("function_call") is None, "raw native parser/finish contract mismatch")
    normalized = []
    for call in calls:
        _require(call.get("type") == "function" and isinstance(call.get("function", {}).get("arguments"), str),
                 "raw native tool call is malformed")
        arguments = _strict_json(call["function"]["arguments"])
        _require(isinstance(arguments, dict), "native tool arguments must be a JSON object")
        normalized.append(ToolCall(call["id"], call["function"]["name"], arguments).to_dict())
    native_ids = {call["call_id"] for call in normalized}
    prior_ids = {call.get("call_id") for message in request.messages for call in message.get("tool_calls", ())}
    _require(len(native_ids) == len(normalized) and not native_ids.intersection(prior_ids), "duplicate/reused native call IDs")
    _require(_same(normalized, response.get("tool_calls", [])) and message.get("content") == response.get("content")
             and message.get("reasoning_content") == response.get("reasoning"), "raw response differs from normalized trace")
    _require(all(_same(value, metadata.get(key)) for key, value in _metrics(raw).items()),
             "token/throughput observation differs from raw runtime metrics")
    _require(metadata.get("tool_call_count") == len(normalized)
             and metadata.get("native_tool_call_ids") == [call["call_id"] for call in normalized]
             and metadata.get("tool_call_names") == [call["name"] for call in normalized],
             "native tool-call observation differs from raw response")
    for prefix, content in (("output", message.get("content") or ""), ("reasoning", message.get("reasoning_content") or "")):
        _require(metadata.get(f"{prefix}_characters") == len(content) and metadata.get(f"{prefix}_utf8_bytes") == len(content.encode("utf-8"))
                 and metadata.get(f"{prefix}_words") == len(content.split()), "verbosity observation differs from raw response")


def _terminal(content: str | None) -> dict[str, Any]:
    content = content or ""
    raw = content.encode("utf-8")
    return {"kind": "assistant_text", "content": content, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def _trace(trace, case, source_case, level, effective, binding, interface, repo_root, observations, consumed, specs, *, allow_model_behavior_failure=False):
    assets = _resolve_assets(source_case, level=level, asset_loader=lambda asset: _path(repo_root, asset["source_locator"]).read_bytes())
    execution = _execution_case(source_case, assets)
    initial = ModelTurnRequest(case_id=case.payload["case_id"], turn=1,
        messages=tuple(execution["input"]["messages"]), context_assets=tuple(execution["input"]["context_assets"]),
        tools=tuple(BOUNDED_FILE_TOOL_DEFINITIONS) if level == "L2" else ()).to_dict()
    _require(trace.payload.get("case_id") == source_case["case_id"], "foreign case execution trace")
    _require(_same(binding.payload.get("context_assets"), [asset.binding_descriptor for asset in assets]),
             "execution binding context assets differ from accepted source")
    if level != "L2":
        validate_intrinsic_execution_trace(trace)
        payload = trace.payload
        _require(payload.get("status") == "success" and payload.get("stop_reason") == "terminal_output"
                 and payload.get("error") is None and _same(payload["request"], initial),
                 "intrinsic trace failed or used foreign input")
        _http_turn(payload["request"], payload["response"], effective, observations, consumed)
        terminal = _terminal(payload["response"].get("content"))
        _require(not payload["response"].get("tool_calls") and _same(payload["terminal_output"], terminal)
                 and binding.payload.get("workspace_scope") is None, "intrinsic output/tool scope mismatch")
    else:
        validate_tool_execution_trace(trace)
        payload = trace.payload
        _require(_same(payload.get("execution_interface"), interface.reference.to_dict()), "foreign tool execution interface")
        summary = payload["summary"]
        if allow_model_behavior_failure:
            _require((summary.get("status"), summary.get("stop_reason")) in {("success", "terminal_output"), ("resource_limit", "max_tool_calls")},
                     "tool execution has an operational failure rather than a bounded model-behavior outcome")
        else:
            _require(summary.get("status") == "success" and summary.get("stop_reason") == "terminal_output",
                     "tool execution failed or exhausted a limit")
        spec = specs[source_case["case_id"]]
        readable = sorted(set(spec["readable_paths"]) | {asset.reference_path for asset in assets if asset.reference_path})
        writable = list(spec["writable_paths"])
        files = {}
        for name, digest in spec["files"].items():
            files[name] = {"path": name, "state": "file", "sha256": digest,
                           "size_bytes": (Path(spec["fixture_dir"]) / name).stat().st_size}
        for asset in assets:
            if asset.reference_path:
                files[asset.reference_path] = {"path": asset.reference_path, "state": "file",
                    "sha256": hashlib.sha256(asset.data).hexdigest(), "size_bytes": len(asset.data)}
        snapshot = [files.get(name, {"path": name, "state": "missing", "sha256": None, "size_bytes": None})
                    for name in sorted(set(readable) | set(writable))]
        _require(_same(payload["initial_workspace"]["files"], snapshot), "initial workspace differs from accepted fixtures")
        scope = {"readable_paths": readable, "writable_paths": writable}
        _require(_same(payload["scope"], scope) and _same(binding.payload["workspace_scope"],
            {**scope, "initial_state_sha256": payload["initial_workspace"]["snapshot_sha256"]}), "bounded workspace scope changed")
        events, index, turn, call_count = payload["events"], 0, 0, 0
        history = _copy(initial["messages"])
        terminal = None
        limit_reached = False
        while index < len(events):
            turn += 1
            expected = {**initial, "turn": turn, "messages": history}
            _require(events[index]["event_type"] == "model_request" and _same(events[index]["payload"], expected),
                     "tool trace request/history differs from accepted input and preceding evidence")
            index += 1
            _require(index < len(events) and events[index]["event_type"] == "model_response", "model error or missing response event")
            response = events[index]["payload"]
            _http_turn(expected, response, effective, observations, consumed)
            index += 1
            calls = response.get("tool_calls", [])
            if not calls:
                terminal = _terminal(response.get("content"))
                _require(index == len(events) - 1 and events[index]["event_type"] == "terminal_output"
                         and _same(events[index]["payload"], terminal), "tool trace terminal output is incomplete")
                index += 1
                break
            assistant = {"role": "assistant", "content": response.get("content"), "tool_calls": _copy(calls)}
            if response.get("reasoning") is not None:
                assistant["reasoning"] = response["reasoning"]
            history.append(assistant)
            for call in calls:
                if allow_model_behavior_failure and index < len(events) and events[index]["event_type"] == "limit_reached":
                    limit = events[index]["payload"]
                    _require(_same(limit.get("blocked_call"), call) and limit.get("limit") == "max_tool_calls"
                             and limit.get("maximum") == effective.payload["tool_surface"]["max_tool_calls"],
                             "resource-limit evidence does not bind the blocked native call")
                    index += 1
                    limit_reached = True
                    break
                _require(index + 2 < len(events), "tool request/result exchange is incomplete")
                request_event, authorization, result = events[index:index + 3]
                _require(request_event["event_type"] == "tool_request" and _same(request_event["payload"], call)
                         and authorization["event_type"] == "tool_authorization" and result["event_type"] == "tool_result",
                         "tool trace does not preserve the native request/authorization/result sequence")
                for event in (authorization, result):
                    _require(event["payload"].get("call_id") == call["call_id"] and event["payload"].get("tool") == call["name"],
                             "foreign tool authorization/result")
                history.append({"role": "tool", "tool_call_id": call["call_id"], "name": call["name"],
                                "result": _copy(result["payload"]["result"])})
                call_count += 1
                index += 3
            if limit_reached:
                break
        _require(call_count > 0 and call_count <= effective.payload["tool_surface"]["max_tool_calls"]
                 and summary.get("tool_calls") == call_count and summary.get("model_turns") == turn,
                 "native tool interface/counts not proven")
        if summary.get("status") == "success":
            _require(terminal is not None and summary.get("terminal_output_sha256") == terminal["sha256"],
                     "successful tool trace terminal output is not proven")
        else:
            _require(allow_model_behavior_failure and limit_reached and terminal is None
                     and summary.get("terminal_output_sha256") is None and index == len(events),
                     "bounded model-behavior resource limit is not completely evidenced")
    _require(_same(case.payload["terminal_output"], terminal), "case output differs from its execution trace")
    return assets


def _verify(root: Path, *, stage: str, fingerprint: Mapping[str, Any], repo_root: Path):
    _require(stage in {"smoke", "shared-screen"}, "unsupported progression gate stage")
    envelope = read_json(root / "gate.json")
    gate = envelope.get("payload")
    _require(envelope.get("schema_version") == "flashnext-campaign-gate:v1" and isinstance(gate, dict)
             and sha256_json(gate) == envelope.get("sha256"), "invalid or changed gate envelope")
    _require(gate.get("stage") == stage and gate.get("status") == "pass", f"a passing {stage} gate is required")
    _require(_same(gate.get("fingerprint"), fingerprint), "different runtime/model/host/configuration/implementation fingerprint")
    _require(gate.get("role_or_model_qualified") is False and gate.get("native_tool_smoke_pass") is True,
             "gate must prove interface operation without claiming model/role qualification")
    if stage == "smoke":
        _require(gate.get("parent_smoke_run") is None and gate.get("parent_gate_sha256") is None, "smoke gate cannot have a parent")
    else:
        parent = gate.get("parent_smoke_run")
        _require(isinstance(parent, str) and Path(parent).is_absolute(), "shared gate requires its absolute smoke parent")
        parent_path = Path(parent).resolve()
        _require(parent_path != root, "gate ancestry cycle")
        parent_gate = _verify(parent_path, stage="smoke", fingerprint=fingerprint, repo_root=repo_root)
        _require(gate.get("parent_gate_sha256") == sha256_json(parent_gate), "smoke parent gate changed")
    packs = _packs(repo_root, root, stage)
    expected_cases = {case["case_id"]: (level, case) for level, (pack, _) in packs.items() for case in pack.cases}
    count = len(expected_cases)
    _require(type(gate.get("completed_observations")) is int and gate["completed_observations"] == count,
             "gate observation count is incomplete")
    records = _Records(root, gate.get("evidence"))
    observations = _artifacts(root, gate.get("artifact_files"))
    runtime, model, interface = [records.one(kind) for kind in
        ("runtime_profile", "model_identity", "execution_interface_identity")]
    host_profiles = records.by_type["host_profile"]
    _require(1 <= len(host_profiles) <= 2, "expected one execution host plus at most one BL-3 stability capture")
    _require(all(host.payload.get("facts_sha256") == fingerprint.get("host_facts_sha256")
                 for host in host_profiles), "foreign or unstable host facts")
    if len(host_profiles) == 2:
        _require({host.logical_id for host in host_profiles}
                 == {"flashnext-host-capture-1", "flashnext-host-capture-2"},
                 "unexpected extra host-profile identity")
    manifests_for_host = records.by_type["run_manifest"]
    _require(manifests_for_host, "run manifests are missing")
    first_host_ref = manifests_for_host[0].payload.get("host")
    _require(isinstance(first_host_ref, Mapping), "run manifest host reference is missing")
    host = records.get(first_host_ref, "host_profile")
    _require(all(_same(record.payload.get("host"), host.reference.to_dict()) for record in manifests_for_host),
             "run manifests do not bind one execution host")
    for record, key in ((runtime, "runtime_sha256"), (model, "model_sha256"), (interface, "execution_interface_sha256")):
        _require(record.sha256 == fingerprint.get(key), f"foreign {record.record_type} fingerprint")
    validate_execution_interface_identity(interface)
    _require(_same(interface.payload["runtime"], runtime.reference.to_dict())
             and _same(interface.payload["model"], model.reference.to_dict())
             and interface.payload.get("backend_kind") == "llama_cpp" and interface.payload.get("adapter_id") == LLAMA_CPP_ADAPTER_ID,
             "runtime interface identity or adapter changed")
    for kind in ("case_result", "evaluation_result", "trial_identity", "execution_binding", "resource_telemetry_trace"):
        _require(len(records.by_type[kind]) == count, f"incomplete or duplicated {kind} set")
    _require(len(records.by_type["benchmark_input"]) == len(records.by_type["run_manifest"]) == 3,
             "all three shared levels require benchmark/manifest evidence")
    cases = {record.payload["case_id"]: record for record in records.by_type["case_result"]}
    _require(len(cases) == count and set(cases) == set(expected_cases), "case coverage is not the exact accepted screen")
    registry = build_shared_l2_registry()
    register_shared_battery_evaluators(registry)
    specs = workspace_specs(repo_root)
    consumed, used_trials, used_evaluations, used_bindings, used_traces, used_configs, used_evaluators = (set() for _ in range(7))
    manifests = {}
    for level, (pack, provenance) in packs.items():
        benchmarks = [record for record in records.by_type["benchmark_input"] if record.payload.get("level") == level]
        _require(len(benchmarks) == 1, f"foreign or missing {level} benchmark")
        benchmark = benchmarks[0]
        _require(benchmark.reference == pack.to_benchmark_input(source_locator=benchmark.payload.get("source_locator")).reference,
                 "benchmark input does not bind exact accepted pack bytes")
        matches = [record for record in records.by_type["run_manifest"]
                   if _reference_keys(record.payload["benchmarks"]) == {_key(benchmark)}]
        _require(len(matches) == 1, "missing/ambiguous level manifest")
        manifest = matches[0]
        manifests[level] = manifest
        for name, foundation in (("host", host), ("runtime", runtime), ("model", model)):
            _require(_same(manifest.payload[name], foundation.reference.to_dict()), "manifest foundation changed")
        harness = manifest.payload["harness_source"]
        _require(harness.get("repetition_phase") == "screen" and _same(harness.get("source"), {
            "campaign": CAMPAIGN_NAME, "v2_base_commit": BASE_COMMIT,
            "implementation_sha256": fingerprint["implementation_sha256"], "accepted_pack": provenance,
            "runtime_fallback": "forbidden", "role_qualification_claim": False}), "foreign stage/source manifest")
        local_trials, local_bindings, local_configs, local_evaluators = (set() for _ in range(4))
        for case_id in pack.case_ids:
            case, source_case = cases[case_id], pack.case(case_id)
            payload = case.payload
            if stage == "smoke" or level == "L2":
                _require((payload.get("status"), payload.get("metrics", {}).get("stop_reason")) in {
                    ("success", "terminal_output"), ("resource_limit", "max_tool_calls")},
                    "case has an operational failure rather than a bounded model-behavior outcome")
            else:
                _require(payload.get("status") == "success" and payload.get("metrics", {}).get("stop_reason") == "terminal_output",
                         "unsuccessful intrinsic shared-screen case execution")
            _require(_same(payload["manifest"], manifest.reference.to_dict())
                     and _same(payload["benchmark"], benchmark.reference.to_dict()), "foreign case execution")
            trial = records.get(payload["trial"], "trial_identity")
            _require(_key(trial) not in used_trials and trial.payload.get("case_id") == case_id
                     and type(trial.payload.get("ordinal")) is int and trial.payload["ordinal"] == 1
                     and _same(trial.payload["benchmark"], benchmark.reference.to_dict())
                     and trial.payload.get("layer") == ("lab_tool" if level == "L2" else "intrinsic"), "duplicate/foreign trial identity")
            effective = records.get(trial.payload["effective_config"], "effective_runtime_config")
            _validate_case_configuration(source_case, level=level, effective_config=effective)
            settings = effective.payload["settings"]
            spec = {"schema_version": settings["schema_version"], "comparison_mode": settings["comparison_mode"],
                    "generation": settings["generation"], "execution": effective.payload["limits"], "tool_surface": effective.payload["tool_surface"]}
            adapter = llama_cpp_adapter_resolution(spec, runtime=runtime, model=model, reasoning_transport="server_default", model_alias="C01")
            rebuilt = resolve_effective_configuration(effective.logical_id, runtime=runtime, model=model, spec=spec, adapter_resolution=adapter)
            _require(rebuilt.reference == effective.reference and settings["generation"]["context_tokens"] == 262144,
                     "effective configuration differs from the bound Flash-Next adapter")
            if level == "L2":
                _require(effective.payload["tool_surface"]["max_tool_calls"] == _TOOL_LIMITS[source_case["requirements"]["configuration_profile"]],
                         "accepted L2 tool limit changed")
            binding = records.get(payload["execution_evidence"]["execution_binding"], "execution_binding")
            _require(_key(binding) not in used_bindings and _same(binding.payload["trial"], trial.reference.to_dict())
                     and binding.payload.get("execution_mode") == trial.payload["layer"]
                     and _same(binding.payload.get("execution_interface"), interface.reference.to_dict())
                     and binding.payload["driver"].get("driver_id") == "flashnext-llama-cpp-chat-v1"
                     and binding.payload["driver"].get("implementation_sha256") == file_digest(repo_root / "src/localbench/v2/llama_cpp_driver.py"),
                     "foreign execution binding/driver")
            trace = records.get(payload["execution_evidence"]["primary"], "tool_execution_trace" if level == "L2" else "intrinsic_execution_trace")
            _require(_key(trace) not in used_traces, "reused execution trace")
            _trace(trace, case, source_case, level, effective, binding, interface, repo_root, observations, consumed, specs,
                   allow_model_behavior_failure=stage == "smoke" or level == "L2")
            evaluations = [record for record in records.by_type["evaluation_result"] if _same(record.payload["case"], case.reference.to_dict())]
            _require(len(evaluations) == len(source_case["evaluators"]) == 1, "missing/duplicate case evaluator result")
            evaluation, evaluator_binding = evaluations[0], source_case["evaluators"][0]
            definition = registry.resolve(evaluator_binding["evaluator_id"], evaluator_binding["contract_version"])
            _require(_same(evaluation.payload["evaluator"], definition.identity.reference.to_dict()), "foreign evaluator identity")
            available = (host, runtime, model, benchmark, effective, trial, interface, binding, manifest, trace)
            replay = registry.evaluate(evaluation.logical_id, evaluator_id=definition.evaluator_id, contract_version=definition.contract_version,
                case_definition=source_case, case_result_record=case, supplemental_evidence=_supplemental_for_definition(definition, available))
            _require(replay.reference == evaluation.reference, "deterministic evaluation differs from preserved case/trace")
            for collection, record in ((used_trials, trial), (local_trials, trial), (used_bindings, binding), (local_bindings, binding),
                (used_traces, trace), (used_evaluations, evaluation), (used_configs, effective), (local_configs, effective),
                (used_evaluators, definition.identity), (local_evaluators, definition.identity)):
                collection.add(_key(record))
        for name, wanted in (("trials", local_trials), ("execution_bindings", local_bindings), ("effective_configs", local_configs), ("evaluators", local_evaluators)):
            _require(_reference_keys(manifest.payload[name]) == wanted, f"manifest {name} relationship is incomplete/foreign")
    for kind, used in (("evaluation_result", used_evaluations), ("trial_identity", used_trials), ("execution_binding", used_bindings),
                       ("effective_runtime_config", used_configs), ("evaluator_identity", used_evaluators)):
        _require({_key(record) for record in records.by_type[kind]} == used, f"foreign unconsumed {kind} evidence")
    _require({_key(record) for kind in ("intrinsic_execution_trace", "tool_execution_trace") for record in records.by_type[kind]} == used_traces,
             "foreign execution trace evidence")
    _require(consumed == set(observations), "unconsumed/foreign raw model-turn observations")
    telemetry_trials = set()
    for telemetry in records.by_type["resource_telemetry_trace"]:
        trial = records.get(telemetry.payload["trial"], "trial_identity")
        _require(_key(trial) not in telemetry_trials and telemetry.payload.get("case_id") == trial.payload["case_id"], "foreign/duplicate resource telemetry trial")
        telemetry_trials.add(_key(trial))
    _require(telemetry_trials == used_trials, "resource telemetry does not close over all trials")
    l2_cases = {case_id for case_id, (level, _) in expected_cases.items() if level == "L2"}
    compatibility = records.by_type["tool_compatibility_observation"]
    _require(len(compatibility) == len(l2_cases) and {record.payload.get("case_id") for record in compatibility} == l2_cases,
             "native parser observations do not cover the exact L2 screen")
    for observation in compatibility:
        case = cases[observation.payload["case_id"]]
        trace = records.get(case.payload["execution_evidence"]["primary"])
        dimension = observation.payload["dimensions"]["protocol_parser_compatibility"]
        _require(_same(observation.payload["execution_interface"], interface.reference.to_dict())
                 and dimension.get("status") == "pass" and _reference_keys(dimension.get("evidence")) == {_key(trace)},
                 "native parser compatibility is absent, foreign, or failed")
    all_correct = all(record.payload["verdict"] == "pass" for record in records.by_type["evaluation_result"])
    _require(gate.get("correctness_all_pass") is all_correct, "gate correctness summary differs from evaluation evidence")
    return gate


def verify_gate(run_dir: Path, *, stage: str, fingerprint: Mapping[str, Any], repo_root: Path | None = None) -> dict[str, Any]:
    """Reject stale, incomplete or incompatible smoke/shared progression evidence.

    Shared correctness failures remain visible and do not by themselves block
    later role investigation. Every response must still have a successful native
    runtime/transport execution, with complete raw evidence and smoke ancestry.
    """
    try:
        return _verify(Path(run_dir).resolve(), stage=stage, fingerprint=fingerprint,
                       repo_root=Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[3])
    except FlashNextBlocked:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError, UnboundLocalError) as exc:
        raise FlashNextBlocked(f"gate evidence verification failed: {type(exc).__name__}: {exc}") from exc
