"""Independent Planner preparation, optional inference and human review CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from localbench.assistant001.packet import repository_root, write_json
from .planner_packet import PACKETS, CASES, prepare, verify_run
from .planner import run_planner, assess_run


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "worker":
        from .worker_cli import main as worker_main
        return worker_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "assess", "calibrate"))
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--project", choices=tuple(PACKETS))
    parser.add_argument("--case", choices=CASES, default="complete")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--allow-model-inference", action="store_true",
                        help="Explicit consent for this Ollama text-only trial; grants no code execution.")
    parser.add_argument("--context-tokens", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        if args.action == "calibrate":
            from .planner_calibration import calibrate
            print(json.dumps(calibrate(args.repo_root), indent=2))
            return 0
        if args.action == "prepare":
            if not args.project or not args.output_root:
                raise ValueError("prepare requires --project and --output-root")
            run = prepare(args.project, args.output_root, case=args.case, repo=args.repo_root)
            print(f"RUN_DIR={run}")
            return 0
        if not args.run_dir:
            raise ValueError("run/assess requires --run-dir")
        verify_run(args.run_dir, args.repo_root)
        if args.action == "run":
            if not args.allow_model_inference or not args.model:
                raise ValueError("run requires --model and explicit --allow-model-inference consent")
            if args.plan_file or args.review_file:
                raise ValueError("Model runs do not accept candidate plans or review material as input")
            if (args.run_dir / "session.json").exists() or (args.run_dir / "roles").exists():
                raise ValueError("Use a fresh prepared run for every trial")
            from localbench.assistant001.runtime import OllamaSessions
            sessions = OllamaSessions(args.repo_root, args.run_dir, args.model,
                                      context_tokens=args.context_tokens, max_output_tokens=args.max_output_tokens,
                                      timeout_seconds=args.timeout_seconds)
            write_json(args.run_dir / "runtime-identity.json", {
                k: v.reference.to_dict() for k, v in sessions.foundation.items()
            })
            write_json(args.run_dir / "runner-inputs.json", {
                "model": args.model, "context_tokens": args.context_tokens,
                "max_output_tokens": args.max_output_tokens, "timeout_seconds": args.timeout_seconds,
                "transport": "direct_ollama", "host_execution_authorized": False,
                "session_policy": "fresh RoleConversation; no candidate tools or filesystem",
                "planner_mode": "independent_blind",
            })
            result = run_planner(args.run_dir, sessions, repo=args.repo_root)
            target, _ = assess_run(args.run_dir, repo=args.repo_root, model=args.model, context_tokens=args.context_tokens)
            print(f"ASSESSMENT_DIR={target}")
            return 0 if result["status"] == "success" else 1
        # Metadata supplied on assess cannot relabel a captured model/configuration.
        model, context = "unknown-import", None
        inputs = args.run_dir / "runner-inputs.json"
        if args.plan_file is None and inputs.exists():
            info = json.loads(inputs.read_text(encoding="utf-8"))
            model, context = info["model"], info["context_tokens"]
        target, result = assess_run(args.run_dir, plan_file=args.plan_file, review_file=args.review_file,
                                    repo=args.repo_root, model=model, context_tokens=context)
        print(f"ASSESSMENT_DIR={target}\nOUTCOME={result['assessed_outcome']}")
        # Exit zero means records written; never a qualification pass.
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
