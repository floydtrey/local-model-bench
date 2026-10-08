"""Runtime-neutral five-role qualification entrypoint for Ollama candidates.

Reuses the frozen Planner/Governor/Worker/Tester/Reviewer packets and the same
role harness/review workbook used by the Flash-Next campaign. No shared-screen
or smoke prerequisite is required.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .configuration import CONFIG_SPEC_VERSION, resolve_effective_configuration
from .contracts import canonical_json_bytes, sha256_json
from .execution_interface import execution_interface_identity
from .flashnext_review import write_review_package
from .flashnext_roles import ROLE_NAMES, build_role_cases, run_role_campaign
from .host import SystemHostProbe, collect_host_profile
from .ollama_driver import OLLAMA_ADAPTER_ID, OllamaChatDriver, ollama_adapter_resolution
from .orchestrator import EvidenceStore
from .records import model_identity, runtime_profile
from .resource_telemetry import system_resource_telemetry_binding
from .resource_telemetry_integration import SafeResourceTelemetryCapture


CAMPAIGN_NAME = "all-roles-v1"
SOURCE_CAMPAIGN = "flashnext-all-roles-v1"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class CampaignBlocked(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _http_json(base_url: str, path: str, *, payload: Mapping[str, Any] | None = None,
               timeout: float = 15) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = None if payload is None else canonical_json_bytes(dict(payload))
    request = urllib.request.Request(
        url, data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise CampaignBlocked(f"Ollama API request failed for {path}: {exc}") from exc
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignBlocked(f"Ollama API returned invalid JSON for {path}") from exc
    if not isinstance(value, dict):
        raise CampaignBlocked(f"Ollama API returned non-object JSON for {path}")
    if isinstance(value.get("error"), str):
        raise CampaignBlocked(f"Ollama API error for {path}: {value['error']}")
    return value


def _digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.removeprefix("sha256:").strip().lower()
    return candidate if re.fullmatch(r"[0-9a-f]{64}", candidate) else None


def _parameter_count(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([BbMm])\s*", value)
    if not match:
        return None
    multiplier = 1_000_000_000 if match.group(2).lower() == "b" else 1_000_000
    return int(float(match.group(1)) * multiplier)


def _declared_context(show: Mapping[str, Any]) -> int | None:
    info = show.get("model_info")
    if not isinstance(info, Mapping):
        return None
    values = [value for key, value in info.items()
              if isinstance(key, str) and key.endswith(".context_length")
              and isinstance(value, int) and not isinstance(value, bool) and value > 0]
    return max(values) if values else None


def _executable_identity() -> tuple[dict[str, Any] | None, str | None]:
    executable = shutil.which("ollama")
    if not executable:
        return None, None
    path = Path(executable).resolve()
    try:
        raw = path.read_bytes()
    except OSError:
        return {"path": str(path)}, None
    digest = hashlib.sha256(raw).hexdigest()
    return {"path": str(path), "sha256": digest, "bytes": len(raw)}, digest


def inspect_ollama_model(base_url: str, model_name: str) -> dict[str, Any]:
    version = _http_json(base_url, "/api/version")
    tags = _http_json(base_url, "/api/tags")
    show = _http_json(base_url, "/api/show", payload={"model": model_name, "verbose": True}, timeout=30)
    models = tags.get("models")
    if not isinstance(models, list):
        raise CampaignBlocked("Ollama /api/tags did not return a models array")
    matched = next((item for item in models if isinstance(item, Mapping)
                    and item.get("name") == model_name), None)
    if matched is None:
        matched = next((item for item in models if isinstance(item, Mapping)
                        and item.get("model") == model_name), None)
    if matched is None:
        available = sorted(str(item.get("name")) for item in models
                           if isinstance(item, Mapping) and item.get("name"))
        raise CampaignBlocked(
            f"Ollama model {model_name!r} is not installed. Installed tags: {', '.join(available)}"
        )
    provider_digest = _digest(matched.get("digest"))
    if provider_digest is None:
        raise CampaignBlocked("Installed Ollama tag did not expose a canonical SHA-256 digest")
    details = show.get("details") if isinstance(show.get("details"), Mapping) else {}
    capabilities = show.get("capabilities") if isinstance(show.get("capabilities"), list) else []
    return {
        "version": version.get("version") if isinstance(version.get("version"), str) else None,
        "tag": model_name,
        "provider_digest": provider_digest,
        "family": details.get("family") if isinstance(details.get("family"), str) else None,
        "parameter_size": details.get("parameter_size") if isinstance(details.get("parameter_size"), str) else None,
        "parameter_count": _parameter_count(details.get("parameter_size")),
        "quantization": details.get("quantization_level") if isinstance(details.get("quantization_level"), str) else None,
        "declared_context_tokens": _declared_context(show),
        "capabilities": sorted(str(x) for x in capabilities if isinstance(x, str)),
        "show_sha256": sha256_json(show),
        "tags_entry_sha256": sha256_json(dict(matched)),
    }


def generation_spec(*, context_tokens: int, max_output_tokens: int, timeout_seconds: float,
                    reasoning_transport: str, keep_alive_seconds: float) -> dict[str, Any]:
    reasoning = (
        {"mode": "unsupported", "effort": None}
        if reasoning_transport == "unsupported"
        else {"mode": "enabled", "effort": None}
    )
    return {
        "schema_version": CONFIG_SPEC_VERSION,
        "comparison_mode": "strict",
        "generation": {
            "context_tokens": context_tokens,
            "max_output_tokens": max_output_tokens,
            "temperature": 0,
            "seed": 42,
            "top_p": 1,
            "top_k": None,
            "repeat_penalty": None,
            "stop": [],
            "response_format": {"mode": "text", "schema": None},
            "reasoning": reasoning,
        },
        "execution": {
            "timeout_seconds": timeout_seconds,
            "retries": 0,
            "retry_delay_seconds": 0,
            "concurrency": 1,
            "model_residency": {
                "mode": "keep_loaded",
                "keep_alive_seconds": keep_alive_seconds,
            },
            "network_policy": "provider_only",
        },
        "tool_surface": {
            "id": "none",
            "tools": [],
            "max_tool_calls": 0,
            "schema_sha256": None,
        },
    }


def build_foundation(*, repo_root: Path, store: EvidenceStore, base_url: str,
                     model_name: str, context_tokens: int) -> tuple[dict[str, Any], dict[str, Any]]:
    observed = inspect_ollama_model(base_url, model_name)
    declared = observed["declared_context_tokens"]
    if declared is not None and context_tokens > declared:
        raise CampaignBlocked(
            f"requested context {context_tokens} exceeds model-declared context {declared}"
        )
    executable, installation_digest = _executable_identity()
    runtime = runtime_profile(
        "ollama-runtime",
        runtime_kind="ollama",
        version=observed["version"],
        build=None,
        transport={"kind": "loopback_http", "base_uri": base_url.rstrip("/")},
        executable=executable,
        installation_digest=installation_digest,
        capabilities={"chat": True, "tools_api": True},
    )
    model = model_identity(
        "ollama-model",
        family=observed["family"],
        name=model_name,
        source={
            "kind": "ollama-local-registry",
            "locator": model_name,
            "show_sha256": observed["show_sha256"],
            "tags_entry_sha256": observed["tags_entry_sha256"],
            "capabilities": observed["capabilities"],
        },
        artifact_digest=None,
        provider_digest=observed["provider_digest"],
        parameter_count=observed["parameter_count"],
        quantization=observed["quantization"],
        precision=None,
        declared_context_tokens=declared,
    )
    model_tools = "tools" in observed["capabilities"]
    interface = execution_interface_identity(
        "ollama-execution-interface",
        runtime=runtime.reference,
        model=model.reference,
        backend_kind="ollama",
        adapter_id=OLLAMA_ADAPTER_ID,
        tool_transport_mode="native_structured" if model_tools else "unavailable",
        parser_mode="provider_native" if model_tools else "none",
        parser_id="ollama-api-chat-function-tools:v1" if model_tools else None,
        raw_interaction_contract="ollama-api-chat-json:v1",
        capabilities={
            "chat": True,
            "model_tools": model_tools,
            "thinking": "thinking" in observed["capabilities"],
            "vision": "vision" in observed["capabilities"],
        },
    )
    host = collect_host_profile(
        "ollama-host",
        probe=SystemHostProbe(target_path=repo_root),
    )
    store.persist_many([host, runtime, model, interface])
    return {"host": host, "runtime": runtime, "model": model, "interface": interface}, observed


def run_campaign(*, repo_root: Path, output_dir: Path, model_name: str, base_url: str,
                 phase: str, governor_root: Path, context_tokens: int,
                 max_output_tokens: int, timeout_seconds: float,
                 keep_alive_seconds: float, progress) -> dict[str, Any]:
    campaign_root = repo_root / "campaigns" / SOURCE_CAMPAIGN
    if not campaign_root.is_dir():
        raise CampaignBlocked(f"role packet campaign not found: {campaign_root}")
    store = EvidenceStore(output_dir / "evidence")
    foundation, observed = build_foundation(
        repo_root=repo_root, store=store, base_url=base_url,
        model_name=model_name, context_tokens=context_tokens,
    )
    reasoning_transport = "boolean" if "thinking" in observed["capabilities"] else "unsupported"
    base_spec = generation_spec(
        context_tokens=context_tokens,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        reasoning_transport=reasoning_transport,
        keep_alive_seconds=keep_alive_seconds,
    )
    counter = 0

    def driver_factory(spec, evidence_dir):
        nonlocal counter
        counter += 1
        adapter = ollama_adapter_resolution(
            spec,
            runtime=foundation["runtime"],
            model=foundation["model"],
            reasoning_transport=reasoning_transport,
        )
        effective = resolve_effective_configuration(
            f"ollama-role-config-{counter:04d}",
            runtime=foundation["runtime"],
            model=foundation["model"],
            spec=spec,
            adapter_resolution=adapter,
        )
        driver = OllamaChatDriver(effective)
        object.__setattr__(driver, "effective_config", effective)
        return driver

    @contextlib.contextmanager
    def case_context(case_dir, trial):
        binding = system_resource_telemetry_binding(sampling_interval_ms=1000)
        capture = SafeResourceTelemetryCapture(
            binding,
            f"ollama-resource-{trial.sha256[:24]}",
            trial.payload["case_id"],
            trial.reference,
        )
        capture.start()
        try:
            yield capture
        finally:
            trace = capture.stop()
            store.persist(trace)
            _write_json(Path(case_dir) / "resource-telemetry-ref.json", trace.reference.to_dict())

    driver_path = Path(__file__).with_name("ollama_driver.py")
    driver_binding = {
        "driver_id": "ollama-role-conversation-v1",
        "implementation_sha256": hashlib.sha256(driver_path.read_bytes()).hexdigest(),
        "execution_kind": "in_process_http_client",
    }
    repetitions = 1 if phase == "screen" else 3
    aggregate_results = []
    role_summaries = {}
    stopped_roles = {}
    planned_cases = 0

    for role in ROLE_NAMES:
        role_case_count = len(build_role_cases(
            campaign_root, role, governor_root=governor_root
        )) * repetitions
        planned_cases += role_case_count
        progress(f"Starting role {role}: {role_case_count} planned case(s).")

        def role_progress(event):
            suffix = (
                f" ({event.get('status', event.get('runtime_compatibility', 'evidence saved'))})"
                if event.get("event") == "case_complete" else ""
            )
            progress(
                f"Role {event.get('case_id', '')} trial {event.get('ordinal', '')}: "
                f"{event.get('event', '')}{suffix}"
            )

        summary = run_role_campaign(
            campaign_root=campaign_root,
            roles=[role],
            repetitions=repetitions,
            foundation=foundation,
            base_config_spec=base_spec,
            driver_factory=driver_factory,
            evidence_store=store,
            output_dir=output_dir / "roles" / role,
            governor_root=governor_root,
            case_context_factory=case_context,
            progress=role_progress,
            driver_binding=driver_binding,
        )
        role_summaries[role] = summary
        aggregate_results.extend(summary["results"])
        if summary.get("stopped") is not None:
            stopped_roles[role] = summary["stopped"]
            progress(f"Role {role} stopped early; continuing with the next independent role.")

    combined = {
        "campaign": CAMPAIGN_NAME,
        "source_role_packets": SOURCE_CAMPAIGN,
        "runtime": "ollama",
        "model": model_name,
        "phase": phase,
        "roles": list(ROLE_NAMES),
        "repetitions": repetitions,
        "results": aggregate_results,
        "planned_cases": planned_cases,
        "completed_cases": len(aggregate_results),
        "stopped": stopped_roles or None,
        "qualification_status": "human-review-pending",
        "reviewer_status": "provisional-unqualified",
        "role_summaries": role_summaries,
        "runtime_observation": observed,
        "performance_policy": (
            "Compare generation throughput, tokens/verbosity, load overhead, "
            "resource telemetry, retries, and total wall time separately."
        ),
        "accepted_batteries_modified": False,
    }
    _write_json(output_dir / "summary.json", combined)
    review_profile = {
        "candidate_id": model_name,
        "candidate_name": model_name,
        "model_entry": model_name,
        "server_executable": "ollama",
        "fork_revision": None,
        "context_tokens": context_tokens,
    }
    package = write_review_package(
        output_dir=output_dir,
        summary=combined,
        profile=review_profile,
        shared_run=None,
        phase=phase,
    )
    combined["review_package"] = package
    _write_json(output_dir / "summary-with-review.json", combined)
    return combined


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="python -m localbench.v2.ollama_role_campaign",
        description="Run the full five-role screen/qualification through a local Ollama model.",
    )
    result.add_argument("--repo-root", type=Path, required=True)
    result.add_argument("--model", required=True)
    result.add_argument("--phase", choices=("screen", "qualification"), default="screen")
    result.add_argument("--governor-root", type=Path, required=True)
    result.add_argument("--base-url", default=DEFAULT_BASE_URL)
    result.add_argument("--context-tokens", type=int, default=32768)
    result.add_argument("--max-output-tokens", type=int, default=8192)
    result.add_argument("--timeout-seconds", type=float, default=600)
    result.add_argument("--keep-alive-seconds", type=float, default=3600)
    result.add_argument("--output-root", type=Path)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    governor_root = args.governor_root.resolve()
    if not governor_root.is_dir():
        print(f"BLOCKED: Governor root does not exist: {governor_root}", file=sys.stderr)
        return 2
    if args.context_tokens < 1 or args.max_output_tokens < 1 or args.timeout_seconds <= 0:
        print("BLOCKED: context/output tokens and timeout must be positive", file=sys.stderr)
        return 2
    root = (args.output_root or repo_root / "local-state" / CAMPAIGN_NAME).resolve()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-roles-" + re.sub(r"[^A-Za-z0-9._-]+", "-", args.model)[:40]
        + "-" + uuid.uuid4().hex[:8]
    )
    output_dir = root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)

    def progress(message: str) -> None:
        line = f"[{_utc_now()}] {message}"
        print(line, flush=True)
        with (output_dir / "progress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": _utc_now(), "message": message}) + "\n")

    _write_json(output_dir / "requested-campaign.json", {
        "runtime": "ollama",
        "model": args.model,
        "phase": args.phase,
        "base_url": args.base_url,
        "context_tokens": args.context_tokens,
        "max_output_tokens": args.max_output_tokens,
        "timeout_seconds": args.timeout_seconds,
        "keep_alive_seconds": args.keep_alive_seconds,
        "governor_root": str(governor_root),
        "created_at": _utc_now(),
    })
    progress(f"Evidence directory: {output_dir}")
    try:
        result = run_campaign(
            repo_root=repo_root,
            output_dir=output_dir,
            model_name=args.model,
            base_url=args.base_url,
            phase=args.phase,
            governor_root=governor_root,
            context_tokens=args.context_tokens,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,
            keep_alive_seconds=args.keep_alive_seconds,
            progress=progress,
        )
    except (CampaignBlocked, OSError, ValueError, TypeError) as exc:
        progress(f"BLOCKED: {exc}")
        print(f"Preserved evidence: {output_dir}", flush=True)
        return 2
    progress(
        f"All-role {args.phase} finished: {result['completed_cases']}/{result['planned_cases']} case records. "
        f"Review workbook: {result['review_package']['xlsx']}"
    )
    print(f"RUN_DIR={output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
