from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_config, resolve_suite_paths
from .evaluate import evaluate_run
from .providers import make_provider
from .runner import BenchmarkRunner
from .suites import load_suite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-model-bench",
        description="Run reproducible prompt suites against local chat model endpoints.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="start or resume a benchmark run")
    run.add_argument("--config", type=Path, required=True, help="benchmark config JSON")
    run.add_argument(
        "--suite",
        type=Path,
        action="append",
        help="suite JSON/Markdown; repeat to override config suite globs",
    )
    run.add_argument("--run-id", help="stable run directory name for a new run")
    run.add_argument("--resume", type=Path, help="existing run directory to resume")
    run.add_argument(
        "--rerun-errors", action="store_true", help="retry terminal error cases while resuming"
    )
    run.add_argument("--verbose", action="store_true", help="print case progress")

    validate = subparsers.add_parser("validate", help="validate config and prompt suites")
    validate.add_argument("--config", type=Path, required=True)
    validate.add_argument("--suite", type=Path, action="append")

    doctor = subparsers.add_parser("doctor", help="check providers and configured models")
    doctor.add_argument("--config", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate", help="score completed result contracts")
    evaluate.add_argument("--run", type=Path, required=True, help="benchmark result directory")
    evaluate.add_argument(
        "--snapshot",
        help="write a named, non-destructive report under RUN/snapshots/NAME",
    )

    return parser


def _load_inputs(config_path: Path, suite_overrides: list[Path] | None):
    config_path = config_path.resolve()
    config, config_hash = load_config(config_path)
    paths = (
        sorted({path.resolve() for path in suite_overrides}, key=lambda p: str(p).casefold())
        if suite_overrides
        else resolve_suite_paths(config, config_path)
    )
    if not paths:
        raise ValueError("no prompt suites matched; configure suites or pass --suite")
    suites = [load_suite(path) for path in paths]
    duplicate_ids = sorted(
        {suite.id for suite in suites if sum(item.id == suite.id for item in suites) > 1}
    )
    if duplicate_ids:
        raise ValueError(f"duplicate suite ids: {', '.join(duplicate_ids)}")
    return config, config_hash, suites


def _run(args: argparse.Namespace) -> int:
    if args.run_id and args.resume:
        raise ValueError("--run-id and --resume cannot be used together")
    config, config_hash, suites = _load_inputs(args.config, args.suite)
    progress = print if args.verbose else None
    runner = BenchmarkRunner(
        config,
        args.config,
        config_hash,
        suites,
        run_id=args.run_id,
        resume_dir=args.resume,
        rerun_errors=args.rerun_errors,
        progress=progress,
    )
    try:
        run_dir = runner.run()
    except KeyboardInterrupt:
        print(f"interrupted; resume safely with --resume {runner.run_dir}", file=sys.stderr)
        return 130
    print(str(run_dir))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if config.get("evaluation", {}).get("enabled"):
        evaluate_run(run_dir)
    if manifest.get("status") == "wall_clock_exhausted":
        return 124
    return 1 if manifest.get("status") == "completed_with_errors" else 0


def _validate(args: argparse.Namespace) -> int:
    config, config_hash, suites = _load_inputs(args.config, args.suite)
    output = {
        "valid": True,
        "config_sha256": config_hash,
        "model_order": [model["id"] for model in config["models"]],
        "suites": [
            {
                "suite_id": suite.id,
                "case_count": len(suite.cases),
                "source_sha256": suite.source_sha256,
            }
            for suite in suites
        ],
    }
    print(json.dumps(output, indent=2))
    return 0


def _doctor(args: argparse.Namespace) -> int:
    config, _ = load_config(args.config)
    timeout = min(float(config.get("run", {}).get("timeout_seconds", 600)), 30)
    status: list[dict[str, Any]] = []
    providers = {
        provider_id: make_provider(provider_id, settings)
        for provider_id, settings in config["providers"].items()
    }
    all_ready = True
    try:
        for model in config["models"]:
            record: dict[str, Any] = {
                "id": model["id"],
                "name": model["name"],
                "provider": model["provider"],
            }
            try:
                metadata = providers[model["provider"]].model_metadata(model["name"], timeout)
                record["reachable"] = True
                record["installed"] = metadata is not None
                record["metadata"] = metadata
                all_ready = all_ready and metadata is not None
            except BaseException as exc:
                record["reachable"] = False
                record["installed"] = None
                record["error"] = {"type": type(exc).__name__, "message": str(exc)}
                all_ready = False
            status.append(record)
    finally:
        for provider_id, provider in providers.items():
            if config["providers"][provider_id]["type"] == "llama_cpp":
                provider.unload_model("", timeout)
    print(json.dumps({"ready": all_ready, "models": status}, indent=2))
    return 0 if all_ready else 2


def _evaluate(args: argparse.Namespace) -> int:
    report = evaluate_run(args.run, snapshot=args.snapshot)
    print(json.dumps({"run_id": report["run_id"], "models": report["models"]}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "evaluate":
            return _evaluate(args)
        raise AssertionError(f"unknown command: {args.command}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
