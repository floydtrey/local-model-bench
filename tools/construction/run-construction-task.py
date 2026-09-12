from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localbench.v2.construction_harness import (
    CONSTRUCTION_TOOL_DEFINITIONS,
    AuthorizedCommand,
    ConstructionScope,
    ConstructionWorkspace,
)
from localbench.v2.tool_harness import ToolCall
from localbench.v2.tool_call_normalizer import (
    PROFILES,
    TOOL_CALL_NORMALIZER_VERSION,
    ModelTransportRegistry,
    NormalizeStatus,
    ToolCallNormalizer,
)
from localbench.v2.contracts import sha256_json


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def create_unique_directory(parent: Path, stem: str) -> Path:
    """Create an evidence directory without ever reusing a prior name."""
    parent.mkdir(parents=True, exist_ok=True)
    for suffix in range(10_000):
        name = stem if suffix == 0 else f"{stem}-{suffix:02d}"
        candidate = parent / name
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(f"unable to allocate a unique evidence directory under {parent}")


def write_run_directory_file(pointer: Path, run_dir: Path) -> None:
    """Publish the exact newly allocated run directory without overwriting a pointer."""
    pointer.parent.mkdir(parents=True, exist_ok=True)
    with pointer.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(str(run_dir.resolve(strict=True)) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provider_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["input_schema"],
            },
        }
        for item in CONSTRUCTION_TOOL_DEFINITIONS
    ]


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"provider HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"provider request failed: {exc}") from exc
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("provider response must be a JSON object")
    return value


def require_docker_image(image: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(
            "Docker is required by the default Construction Lab command backend. "
            "Install/start Docker Desktop or explicitly use --command-backend host."
        )
    inspected = subprocess.run(
        [docker, "image", "inspect", image],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if inspected.returncode != 0:
        raise RuntimeError(
            f"Docker image {image!r} is not present locally. Pull it before the benchmark "
            "so benchmark runs never perform implicit network pulls."
        )


def command_from_manifest(
    command_id: str,
    argv: list[str],
    *,
    project_root: Path,
    backend: str,
    docker_image: str,
    docker_memory: str,
    docker_cpus: str,
    docker_pids_limit: int,
) -> AuthorizedCommand:
    if backend == "host":
        actual = tuple(sys.executable if part == "python" else part for part in argv)
        return AuthorizedCommand(command_id, actual, timeout_seconds=120)

    if backend != "docker":
        raise ValueError(f"unsupported command backend: {backend}")
    inside_argv = ["python" if part == "python" else part for part in argv]
    mount_source = str(project_root).replace("\\", "/")
    actual = (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--memory",
        docker_memory,
        "--cpus",
        docker_cpus,
        "--pids-limit",
        str(docker_pids_limit),
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-e",
        "PYTHONNOUSERSITE=1",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-v",
        f"{mount_source}:/workspace:ro",
        "-w",
        "/workspace",
        docker_image,
        *inside_argv,
    )
    return AuthorizedCommand(command_id, actual, timeout_seconds=120)


def task_by_id(manifest: dict[str, Any], task_id: str) -> dict[str, Any]:
    for item in manifest.get("tasks", []):
        if item.get("task_id") == task_id:
            return item
    raise ValueError(f"unknown task_id: {task_id}")


def snapshot_index(snapshot: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {
        item["path"]: (item.get("state"), item.get("sha256"))
        for item in snapshot["files"]
    }


def changed_paths(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    left = snapshot_index(before)
    right = snapshot_index(after)
    return sorted(
        key for key in set(left) | set(right) if left.get(key) != right.get(key)
    )


def provider_message_for_history(
    provider: str,
    message: dict[str, Any],
    calls: list[tuple[ToolCall, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "role": "assistant",
        # The adapter deliberately writes canonical structured calls into history.
        # Raw assistant content remains in turn evidence, but is not duplicated as
        # executable-looking prose on the next turn.
        "content": None,
    }
    if provider == "ollama" and isinstance(message.get("thinking"), str):
        result["thinking"] = message["thinking"]
    result["tool_calls"] = [
        {
            "id": provider_call_id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": dict(call.arguments)
                if provider == "ollama"
                else json.dumps(
                    dict(call.arguments), ensure_ascii=False, separators=(",", ":")
                ),
            },
        }
        for call, provider_call_id in calls
    ]
    return result


def tool_result_message(
    provider: str,
    *,
    name: str,
    provider_call_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "tool",
        "content": json.dumps(result, ensure_ascii=False, sort_keys=True),
    }
    if provider == "ollama":
        message["tool_name"] = name
    else:
        message["tool_call_id"] = provider_call_id
        message["name"] = name
    return message


def extract_provider_message(provider: str, response: dict[str, Any]) -> dict[str, Any]:
    if provider == "ollama":
        message = response.get("message")
    else:
        choices = response.get("choices")
        message = (
            choices[0].get("message")
            if isinstance(choices, list)
            and choices
            and isinstance(choices[0], dict)
            else None
        )
    if not isinstance(message, dict):
        raise RuntimeError(f"{provider} response missing assistant message object")
    return message


def request_payload(
    provider: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    num_ctx: int,
    num_predict: int,
) -> dict[str, Any]:
    if provider == "ollama":
        return {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": 0,
                "seed": 42,
                "top_p": 1,
            },
            "keep_alive": "15m",
        }
    return {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "max_tokens": num_predict,
        "temperature": 0,
        "seed": 42,
        "top_p": 1,
    }


def provider_endpoint(provider: str, base_url: str) -> str:
    suffix = "/api/chat" if provider == "ollama" else "/v1/chat/completions"
    return base_url.rstrip("/") + suffix


def provider_headers(provider: str, api_key_env: str | None) -> dict[str, str]:
    if provider == "ollama":
        if api_key_env is not None:
            raise ValueError("--api-key-env is valid only for openai_compatible")
        return {}
    if api_key_env is None:
        return {}
    value = os.environ.get(api_key_env)
    if not value:
        raise ValueError(f"required API-key environment variable {api_key_env!r} is not set")
    return {"Authorization": f"Bearer {value}"}


def interface_identity(
    *,
    provider: str,
    model: str,
    profile_name: str,
    tools: list[dict[str, Any]],
    provider_provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = PROFILES[profile_name]
    body = {
        "schema_version": "construction-lab-execution-interface:v1",
        "model": model,
        "provider": provider,
        "adapter_id": (
            "construction-ollama-native-chat:v1"
            if profile_name == "openai_native"
            else "construction-openai-compatible-normalizer:v1"
        ),
        "tool_transport_mode": (
            "native_structured"
            if profile_name == "openai_native"
            else "model_aware_structured"
        ),
        "parser_mode": (
            "provider_native" if profile_name == "openai_native" else "model_aware"
        ),
        "normalizer_version": TOOL_CALL_NORMALIZER_VERSION,
        "profile": profile.to_dict(),
        "profile_sha256": profile.sha256,
        "offered_tool_schema_sha256": sha256_json(tools),
        "malformed_call_policy": "fail_closed",
        "backend_tool_execution": "forbidden",
        "history_policy": "canonical_structured_tool_calls:v1",
        "raw_response_evidence": "complete_per_turn_json",
        "provider_provenance": provider_provenance,
        "provider_provenance_sha256": (
            sha256_json(provider_provenance) if provider_provenance is not None else None
        ),
    }
    return {**body, "sha256": sha256_json(body)}


def build_system_prompt(scope: ConstructionScope) -> str:
    return (
        "You are working inside a disposable benchmark project. Use the supplied tools to inspect and modify only the authorized project paths. "
        "Do not invent file contents. Read relevant files before editing them. Use expected_sha256 from read_file when updating or deleting an existing file. "
        "run_command accepts only the listed command_id values; it does not accept shell text. Continue iterating until the task is actually verified, then give a concise final summary.\n\n"
        f"Authorized readable paths: {json.dumps(list(scope.readable_paths))}\n"
        f"Authorized writable paths: {json.dumps(list(scope.writable_paths))}\n"
        f"Authorized deletable paths: {json.dumps(list(scope.deletable_paths))}\n"
        f"Authorized command IDs: {json.dumps([item.command_id for item in scope.commands])}"
    )


def classify_denial(result: dict[str, Any]) -> bool:
    return result.get("error") in {
        "tool_not_exposed",
        "invalid_arguments",
        "invalid_path",
        "path_not_readable",
        "path_not_writable",
        "path_not_deletable",
        "unsafe_workspace_path",
        "command_not_authorized",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real Construction Lab task through a sealed tool interface."
    )
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai_compatible"),
        default="ollama",
    )
    parser.add_argument(
        "--tool-profile",
        choices=tuple(PROFILES),
        default=None,
        help="transport profile; defaults to openai_native for Ollama and is required otherwise",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="environment variable containing the OpenAI-compatible server API key",
    )
    parser.add_argument(
        "--provider-provenance-file",
        type=Path,
        default=None,
        help="immutable runtime/model provenance JSON captured by the provider owner",
    )
    parser.add_argument("--workspace-clone", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--round-label",
        default=None,
        help="operator-supplied repeat-round label recorded with this evidence",
    )
    parser.add_argument(
        "--run-directory-file",
        type=Path,
        default=None,
        help="write the exact allocated run directory to this new operator-side file",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("local-state/construction-lab/runs"),
    )
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--max-turns", type=int, default=32)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument(
        "--command-backend",
        choices=("docker", "host"),
        default="docker",
        help="docker is the safe default; host must be explicitly requested",
    )
    parser.add_argument("--docker-image", default="python:3.12-slim")
    parser.add_argument("--docker-memory", default="512m")
    parser.add_argument("--docker-cpus", default="2")
    parser.add_argument("--docker-pids-limit", type=int, default=128)
    args = parser.parse_args()

    profile_name = args.tool_profile
    if profile_name is None:
        if args.provider != "ollama":
            parser.error("--tool-profile is required for openai_compatible providers")
        profile_name = "openai_native"
    if args.provider == "ollama" and profile_name != "openai_native":
        parser.error("Ollama Construction runs remain native-only")
    headers = provider_headers(args.provider, args.api_key_env)
    registry = ModelTransportRegistry({args.model: profile_name})
    normalizer = ToolCallNormalizer()
    offered_tools = provider_tools()
    provider_provenance = (
        load_json(args.provider_provenance_file.resolve(strict=True))
        if args.provider_provenance_file is not None
        else None
    )
    if provider_provenance is not None and not isinstance(provider_provenance, dict):
        parser.error("--provider-provenance-file must contain a JSON object")
    execution_interface = interface_identity(
        provider=args.provider,
        model=args.model,
        profile_name=profile_name,
        tools=offered_tools,
        provider_provenance=provider_provenance,
    )

    clone_root = args.workspace_clone.resolve(strict=True)
    manifest_path = clone_root / "construction-manifest.json"
    manifest = load_json(manifest_path)
    task = task_by_id(manifest, args.task_id)
    project_root = (clone_root / task["project_path"]).resolve(strict=True)
    try:
        project_root.relative_to(clone_root)
    except ValueError as exc:
        raise RuntimeError("project path escapes fixture clone") from exc

    if args.command_backend == "docker":
        require_docker_image(args.docker_image)

    commands = tuple(
        command_from_manifest(
            command_id,
            argv,
            project_root=project_root,
            backend=args.command_backend,
            docker_image=args.docker_image,
            docker_memory=args.docker_memory,
            docker_cpus=args.docker_cpus,
            docker_pids_limit=args.docker_pids_limit,
        )
        for command_id, argv in task["commands"].items()
    )
    scope = ConstructionScope(
        readable_paths=tuple(task["readable_paths"]),
        writable_paths=tuple(task["writable_paths"]),
        deletable_paths=tuple(task["deletable_paths"]),
        commands=commands,
    )
    workspace = ConstructionWorkspace(project_root, scope)

    timestamp = utc_stamp()
    run_parent = args.output_root.resolve(strict=False) / safe_name(args.model) / args.task_id
    run_dir = create_unique_directory(run_parent, timestamp)
    if args.run_directory_file is not None:
        write_run_directory_file(args.run_directory_file, run_dir)

    initial_snapshot = workspace.snapshot()
    write_json(run_dir / "initial-snapshot.json", initial_snapshot)
    write_json(run_dir / "execution-interface.json", execution_interface)

    baseline_commands: dict[str, Any] = {}
    for command_id in task.get("acceptance", {}).get("required_command_passes", []):
        baseline_commands[command_id] = workspace.execute(
            ToolCall(f"baseline-{command_id}", "run_command", {"command_id": command_id})
        )
    write_json(run_dir / "baseline-verification.json", baseline_commands)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(scope)},
        {"role": "user", "content": task["prompt"]},
    ]
    events: list[dict[str, Any]] = []
    totals = {
        "prompt_eval_count": 0,
        "eval_count": 0,
        "provider_total_duration_ns": 0,
        "provider_load_duration_ns": 0,
        "provider_prompt_eval_duration_ns": 0,
        "provider_eval_duration_ns": 0,
        "model_turns": 0,
        "tool_calls": 0,
        "authority_denials": 0,
        "test_command_calls": 0,
    }
    terminal_content: str | None = None
    stop_reason = "max_turns"
    started = time.perf_counter()

    try:
        for turn in range(1, args.max_turns + 1):
            payload = request_payload(
                args.provider,
                model=args.model,
                messages=messages,
                tools=offered_tools,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
            )
            write_json(run_dir / f"turn-{turn:02d}-request.json", payload)

            turn_started = time.perf_counter()
            response = post_json(
                provider_endpoint(args.provider, args.base_url),
                payload,
                args.request_timeout,
                headers=headers,
            )
            turn_wall_ms = round((time.perf_counter() - turn_started) * 1000, 3)
            write_json(run_dir / f"turn-{turn:02d}-response.json", response)

            totals["model_turns"] += 1
            if args.provider == "ollama":
                for name in (
                    "prompt_eval_count",
                    "eval_count",
                    "total_duration",
                    "load_duration",
                    "prompt_eval_duration",
                    "eval_duration",
                ):
                    value = response.get(name)
                    if not isinstance(value, int):
                        continue
                    target = {
                        "total_duration": "provider_total_duration_ns",
                        "load_duration": "provider_load_duration_ns",
                        "prompt_eval_duration": "provider_prompt_eval_duration_ns",
                        "eval_duration": "provider_eval_duration_ns",
                    }.get(name, name)
                    totals[target] += value
            else:
                usage = response.get("usage")
                if isinstance(usage, dict):
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")
                    if isinstance(prompt_tokens, int):
                        totals["prompt_eval_count"] += prompt_tokens
                    if isinstance(completion_tokens, int):
                        totals["eval_count"] += completion_tokens

            message = extract_provider_message(args.provider, response)
            normalization = normalizer.normalize_assigned(
                model_id=args.model,
                registry=registry,
                offered_tools=offered_tools,
                message=message,
            )
            choices = response.get("choices")
            finish_reason = response.get("done_reason")
            if (
                args.provider != "ollama"
                and isinstance(choices, list)
                and choices
                and isinstance(choices[0], dict)
            ):
                finish_reason = choices[0].get("finish_reason")

            events.append(
                {
                    "type": "model_response",
                    "turn": turn,
                    "wall_time_ms": turn_wall_ms,
                    "provider": args.provider,
                    "done": response.get("done"),
                    "done_reason": finish_reason,
                    "content": message.get("content"),
                    "thinking": message.get("thinking"),
                    "normalization": normalization.to_dict(),
                    "tool_call_count": len(normalization.calls),
                    "prompt_eval_count": response.get("prompt_eval_count"),
                    "eval_count": response.get("eval_count"),
                }
            )

            if normalization.status in {
                NormalizeStatus.INVALID_TOOL_CALL,
                NormalizeStatus.UNKNOWN_MODEL,
            }:
                stop_reason = "protocol_failure"
                break

            if normalization.status is NormalizeStatus.NOT_TOOL_CALL:
                terminal_content = (
                    message.get("content")
                    if isinstance(message.get("content"), str)
                    else ""
                )
                stop_reason = (
                    "output_limit"
                    if finish_reason == "length"
                    else "terminal_response"
                )
                break

            normalized_calls: list[tuple[ToolCall, str]] = []
            for index, normalized in enumerate(normalization.calls, start=1):
                provider_call_id = normalized.call_id or f"normalized-{turn}-{index}"
                call = ToolCall(
                    f"interface-{turn}-{index}",
                    normalized.name,
                    dict(normalized.arguments),
                )
                normalized_calls.append((call, provider_call_id))

            messages.append(
                provider_message_for_history(args.provider, message, normalized_calls)
            )
            for call, provider_call_id in normalized_calls:
                name = call.name
                arguments = dict(call.arguments)
                totals["tool_calls"] += 1
                result = workspace.execute(call)
                if classify_denial(result):
                    totals["authority_denials"] += 1
                if (
                    name == "run_command"
                    and arguments.get("command_id") == "tests"
                ):
                    totals["test_command_calls"] += 1
                events.append(
                    {
                        "type": "tool_result",
                        "turn": turn,
                        "call": call.to_dict(),
                        "result": result,
                    }
                )
                messages.append(
                    tool_result_message(
                        args.provider,
                        name=name,
                        provider_call_id=provider_call_id,
                        result=result,
                    )
                )
        else:
            stop_reason = "max_turns"
    except Exception as exc:
        stop_reason = "runner_error"
        events.append(
            {
                "type": "runner_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )

    wall_time_ms = round((time.perf_counter() - started) * 1000, 3)
    final_snapshot = workspace.snapshot()
    write_json(run_dir / "final-snapshot.json", final_snapshot)
    changed = changed_paths(initial_snapshot, final_snapshot)

    assessor_commands: dict[str, Any] = {}
    for command_id in task.get("acceptance", {}).get("required_command_passes", []):
        assessor_commands[command_id] = workspace.execute(
            ToolCall(f"assess-{command_id}", "run_command", {"command_id": command_id})
        )

    required_missing = task.get("acceptance", {}).get("required_missing_paths", [])
    missing_checks = {
        path: not (project_root / Path(*path.split("/"))).exists()
        for path in required_missing
    }
    max_changed = task.get("acceptance", {}).get("max_changed_paths")
    checks = {
        "required_commands_pass": all(
            assessor_commands.get(command_id, {}).get("ok") is True
            for command_id in task.get("acceptance", {}).get(
                "required_command_passes", []
            )
        ),
        "required_paths_missing": all(missing_checks.values()),
        "changed_path_budget": max_changed is None
        or len(changed) <= int(max_changed),
        "no_authority_denials": totals["authority_denials"] == 0,
        "terminal_response": stop_reason == "terminal_response",
    }
    passed = all(checks.values())

    write_json(run_dir / "events.json", events)
    write_json(run_dir / "assessor-verification.json", assessor_commands)
    result = {
        "schema_version": "construction-lab-run:v1",
        "model": args.model,
        "task_id": args.task_id,
        "round_label": args.round_label,
        "execution_interface": execution_interface,
        "fixture_manifest_sha256": sha256_file(manifest_path),
        "workspace_clone": str(clone_root),
        "project_root": str(project_root),
        "started_at_utc": timestamp,
        "wall_time_ms": wall_time_ms,
        "stop_reason": stop_reason,
        "terminal_content": terminal_content,
        "totals": totals,
        "changed_paths": changed,
        "baseline_verification": baseline_commands,
        "assessor_verification": assessor_commands,
        "required_missing_checks": missing_checks,
        "acceptance_checks": checks,
        "passed": passed,
        "run_directory": str(run_dir),
        "configuration": {
            "provider": args.provider,
            "base_url": args.base_url,
            "tool_profile": profile_name,
            "api_key_env": args.api_key_env,
            "num_ctx": args.num_ctx,
            "num_predict": args.num_predict,
            "max_turns": args.max_turns,
            "temperature": 0,
            "seed": 42,
            "keep_alive": "15m",
            "command_backend": args.command_backend,
            "docker_image": args.docker_image
            if args.command_backend == "docker"
            else None,
            "docker_memory": args.docker_memory
            if args.command_backend == "docker"
            else None,
            "docker_cpus": args.docker_cpus
            if args.command_backend == "docker"
            else None,
            "docker_pids_limit": args.docker_pids_limit
            if args.command_backend == "docker"
            else None,
        },
    }
    write_json(run_dir / "result.json", result)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
