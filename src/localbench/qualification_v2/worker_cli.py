"""Worker subcommands of the existing qualification CLI (no controller)."""
import argparse
import json
from pathlib import Path
import sys

from localbench.assistant001.packet import repository_root, snapshot, write_json
from .worker import APIS, MODES, load_canonical, prepare_worker, verify_worker, validate_seed, authorize, run_worker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "prepare", "validate-seed", "run"))
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--project", choices=tuple(APIS), required=True)
    parser.add_argument("--mode", choices=MODES, default="ISOLATED_TASK")
    parser.add_argument("--task", choices=[f"T0{i}" for i in range(1, 7)], default="T01")
    parser.add_argument("--through", choices=[f"T0{i}" for i in range(1, 7)], default="T06")
    for name in ("output-root", "run-dir", "seed-run", "authorization-file"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--trusted-authorization-sha256")
    parser.add_argument("--model")
    parser.add_argument("--allow-model-inference", action="store_true")
    parser.add_argument("--allow-host-execution", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            load_canonical(args.project, args.repo_root)
            print("Canonical handoff verified; human approval pending; no execution authority")
        elif args.action == "prepare":
            if args.output_root is None:
                raise ValueError("prepare requires --output-root")
            print("RUN_DIR=" + str(prepare_worker(args.project, args.mode, args.output_root,
                repo=args.repo_root, task=args.task, seed_run=args.seed_run)))
        elif args.action == "validate-seed":
            if args.seed_run is None:
                raise ValueError("validate-seed requires --seed-run")
            result = validate_seed(args.project, args.task, args.seed_run, repo=args.repo_root,
                                   allow_host_execution=args.allow_host_execution)
            print(json.dumps(result, indent=2))
            return 0 if result["prevalidated"] else 1
        else:
            if not args.run_dir or not args.model or not args.allow_model_inference or not args.allow_host_execution:
                raise ValueError("run requires a model, fresh run and both separate execution consents")
            # Enforce identity and release before constructing a provider (which contacts Ollama).
            control = verify_worker(args.run_dir, args.repo_root)
            if control["project"] != args.project:
                raise ValueError("Project/run mismatch")
            authorize(control, args.authorization_file, args.trusted_authorization_sha256)
            if (args.run_dir / "summary.json").exists() or (args.run_dir / "roles").exists():
                raise ValueError("Use a fresh run")
            if snapshot(args.run_dir / "workspace") != control["initial_workspace_sha256"]:
                raise ValueError("Worker starting workspace changed")
            if control["worker_mode"] == "CUMULATIVE_PROJECT" and args.through not in [t["id"] for t in control["bundle"]["tasks"]]:
                raise ValueError("Unknown through task")
            if "flash" in args.model.lower() and "next" in args.model.lower():
                raise ValueError("Flash-Next is suspended; no runtime contact permitted")
            from localbench.assistant001.runtime import OllamaSessions
            from localbench.assistant001.cli import review_package
            sessions = OllamaSessions(args.repo_root, args.run_dir, args.model)
            write_json(args.run_dir / "runtime-identity.json", {k: v.reference.to_dict() for k, v in sessions.foundation.items()})
            write_json(args.run_dir / "runner-inputs.json", {"model": args.model,
                "transport": "direct_ollama", "context_tokens": 32768,
                "allow_model_inference": True, "allow_host_execution": True})
            result = run_worker(args.run_dir, sessions, repo=args.repo_root,
                authorization_file=args.authorization_file, trusted_sha256=args.trusted_authorization_sha256,
                allow_model_inference=True, allow_host_execution=True, through=args.through)
            review_package(args.run_dir, result, args.model, "controlled-worker", 32768)
            return 0 if result["passed"] else 1
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
