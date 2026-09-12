from __future__ import annotations

import argparse
import hashlib
import json
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


def ollama_tools() -> list[dict[str, Any]]:
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


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Ollama response must be a JSON object")
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


def provider_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content") or "",
    }
    if isinstance(message.get("thinking"), str):
        result["thinking"] = message["thinking"]
    if isinstance(message.get("tool_calls"), list):
        result["tool_calls"] = message["tool_calls"]
    return result


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
    parser = argparse.ArgumentParser(description="Run one real Construction Lab task against Ollama.")
    parser.add_argument("--model", required=True)
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
            request_payload = {
                "model": args.model,
                "messages": messages,
                "tools": ollama_tools(),
                "stream": False,
                "options": {
                    "num_ctx": args.num_ctx,
                    "num_predict": args.num_predict,
                    "temperature": 0,
                    "seed": 42,
                    "top_p": 1,
                },
                "keep_alive": "15m",
            }
            write_json(run_dir / f"turn-{turn:02d}-request.json", request_payload)

            turn_started = time.perf_counter()
            response = post_json(
                args.base_url.rstrip("/") + "/api/chat",
                request_payload,
                args.request_timeout,
            )
            turn_wall_ms = round((time.perf_counter() - turn_started) * 1000, 3)
            write_json(run_dir / f"turn-{turn:02d}-response.json", response)

            totals["model_turns"] += 1
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

            message = response.get("message")
            if not isinstance(message, dict):
                raise RuntimeError("Ollama response missing message object")
            tool_calls = message.get("tool_calls")
            if tool_calls is None:
                tool_calls = []
            if not isinstance(tool_calls, list):
                raise RuntimeError(
                    "Ollama message.tool_calls must be an array when present"
                )

            events.append(
                {
                    "type": "model_response",
                    "turn": turn,
                    "wall_time_ms": turn_wall_ms,
                    "done": response.get("done"),
                    "done_reason": response.get("done_reason"),
                    "content": message.get("content"),
                    "thinking": message.get("thinking"),
                    "tool_call_count": len(tool_calls),
                    "prompt_eval_count": response.get("prompt_eval_count"),
                    "eval_count": response.get("eval_count"),
                }
            )

            if not tool_calls:
                terminal_content = (
                    message.get("content")
                    if isinstance(message.get("content"), str)
                    else ""
                )
                stop_reason = (
                    "output_limit"
                    if response.get("done_reason") == "length"
                    else "terminal_response"
                )
                break

            messages.append(provider_message_for_history(message))
            for index, raw_call in enumerate(tool_calls, start=1):
                function = raw_call.get("function") if isinstance(raw_call, dict) else None
                if not isinstance(function, dict):
                    raise RuntimeError("tool call missing function object")
                name = function.get("name")
                arguments = function.get("arguments")
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise RuntimeError(
                        "tool call requires string name and object arguments"
                    )
                call = ToolCall(f"ollama-{turn}-{index}", name, arguments)
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
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(
                            result, ensure_ascii=False, sort_keys=True
                        ),
                    }
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
            "base_url": args.base_url,
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
