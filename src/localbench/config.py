from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from .util import sha256_bytes, validate_id


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    path = path.resolve()
    data = path.read_bytes()
    config = json.loads(data.decode("utf-8-sig"))
    validate_config(config)
    return config, sha256_bytes(data)


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    if config.get("schema_version", 1) != 1:
        raise ValueError("only config schema_version 1 is supported")
    providers = config.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("config providers must be a non-empty object")
    for provider_id, provider in providers.items():
        validate_id(provider_id, "provider id")
        if not isinstance(provider, dict):
            raise ValueError(f"provider {provider_id!r} must be an object")
        if provider.get("type") not in {"ollama", "openai_compatible", "llama_cpp"}:
            raise ValueError(
                f"provider {provider_id!r} type must be ollama, openai_compatible, or llama_cpp"
            )
        if not isinstance(provider.get("base_url"), str):
            raise ValueError(f"provider {provider_id!r} needs base_url")
        if provider.get("type") == "llama_cpp":
            for field in ("server_path", "model_path"):
                if not isinstance(provider.get(field), str) or not provider[field]:
                    raise ValueError(f"provider {provider_id!r} needs {field}")
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("config models must be a non-empty ordered list")
    aliases: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("each model must be an object")
        alias = validate_id(model.get("id"), "model id")
        if alias in aliases:
            raise ValueError(f"duplicate model id: {alias}")
        aliases.add(alias)
        if model.get("provider") not in providers:
            raise ValueError(f"model {alias!r} references an unknown provider")
        if not isinstance(model.get("name"), str) or not model["name"]:
            raise ValueError(f"model {alias!r} needs a model name")
        if "options" in model and not isinstance(model["options"], dict):
            raise ValueError(f"model {alias!r} options must be an object")
    run = config.get("run", {})
    if not isinstance(run, dict):
        raise ValueError("run settings must be an object")
    if float(run.get("timeout_seconds", 600)) <= 0:
        raise ValueError("run.timeout_seconds must be positive")
    if "wall_clock_seconds" in run and float(run["wall_clock_seconds"]) <= 0:
        raise ValueError("run.wall_clock_seconds must be positive")
    if int(run.get("retries", 1)) < 0:
        raise ValueError("run.retries cannot be negative")
    evaluation = config.get("evaluation", {})
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation settings must be an object")


def resolve_suite_paths(config: dict[str, Any], config_path: Path) -> list[Path]:
    patterns = config.get("suites", [])
    if not isinstance(patterns, list) or any(not isinstance(item, str) for item in patterns):
        raise ValueError("config suites must be a list of paths or glob patterns")
    found: set[Path] = set()
    for pattern in patterns:
        absolute_pattern = str((config_path.parent / pattern).resolve())
        matches = [Path(item).resolve() for item in glob.glob(absolute_pattern)]
        if not matches and not any(char in pattern for char in "*?["):
            raise FileNotFoundError(f"suite not found: {pattern}")
        found.update(path for path in matches if path.is_file())
    return sorted(found, key=lambda path: str(path).casefold())
