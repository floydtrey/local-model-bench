"""CLI for frozen packet validation, preparation, acceptance, and role trials."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .assessment import assess
from .packet import prepare, read_run, repository_root, snapshot, validate_packet, write_json


def review_package(run, summary, model, phase, context_tokens):
    # Exactly the existing standardized review writer, never a duplicate workbook implementation.
    from localbench.v2.flashnext_review import write_review_package
    result = write_review_package(output_dir=Path(run), summary=summary,
        profile={"candidate_id": model, "candidate_name": model, "model_entry": model,
                 "server_executable": "ollama", "fork_revision": None, "context_tokens": context_tokens},
        shared_run=None, phase=phase)
    summary["review_package"] = result
    write_json(Path(run) / "summary-with-review.json", summary)


def parser():
    result = argparse.ArgumentParser(description="ASSISTANT-001: additive real-project benchmark; no production integration.")
    result.add_argument("action", choices=("validate", "prepare", "assess", "run", "probe", "self-test"))
    result.add_argument("--repo-root", type=Path, default=repository_root())
    result.add_argument("--output-root", type=Path)
    result.add_argument("--run-dir", type=Path)
    result.add_argument("--input-run", type=Path)
    result.add_argument("--model")
    result.add_argument("--phase", choices=("screen", "qualification"), default="screen")
    result.add_argument("--through", choices=[f"T0{i}" for i in range(1, 7)], default="T01")
    result.add_argument("--task", choices=[f"T0{i}" for i in range(1, 7)], default="T06")
    result.add_argument("--role", choices=("planner", "governor", "tester", "reviewer"))
    result.add_argument("--governor-root", type=Path)
    result.add_argument("--plan-file", type=Path)
    result.add_argument("--context-tokens", type=int, default=32768)
    result.add_argument("--max-output-tokens", type=int, default=8192)
    result.add_argument("--timeout-seconds", type=float, default=600)
    result.add_argument("--keep-alive-seconds", type=float, default=3600)
    result.add_argument("--allow-host-execution", action="store_true",
                        help="Explicitly accept running candidate Python on this host; tool scope is not an OS sandbox.")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        packet, sha = validate_packet(args.repo_root)
        if args.action == "validate":
            print(json.dumps({"packet": packet["packet_id"], "packet_sha256": sha,
                              "tasks": len(packet["tasks"]), "status": "integrity-verified",
                              "candidate_code_executed": False, "model_calls": 0}, indent=2))
            return 0
        if args.action == "self-test":
            from .calibration import self_test
            result = self_test(args.repo_root)
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] else 1
        if args.action == "prepare":
            run = prepare(args.output_root, repo=args.repo_root)
            print(f"WORKSPACE={run / 'workspace'}\nRUN_DIR={run}", flush=True)
            return 0
        if args.action == "assess":
            if args.run_dir is None:
                raise ValueError("assess requires --run-dir")
            result, path = assess(args.run_dir, args.task, repo=args.repo_root,
                                  allow_host_execution=args.allow_host_execution)
            print(f"ASSESSMENT_DIR={path}\nRUN_DIR={args.run_dir.resolve()}", flush=True)
            print(json.dumps({"passed": result["passed"], "status": result["status"],
                              "executed": result.get("executed")}, indent=2))
            return 0 if result["passed"] else 1
        if not args.model:
            raise ValueError("run/probe requires --model")
        if args.action == "run" and not args.allow_host_execution:
            raise ValueError("run requires --allow-host-execution; candidate Python is not OS-sandboxed")
        if args.action == "probe":
            if args.role is None or args.input_run is None:
                raise ValueError("probe requires --role and an existing --input-run")
            if args.phase != "screen":
                raise ValueError("Advisory probes are single trials; phase qualification applies only to Worker chains")
            read_run(args.input_run, args.repo_root)
            if args.role == "tester" and not args.allow_host_execution:
                raise ValueError("Tester requires --allow-host-execution")
            if args.role == "governor" and (args.governor_root is None or args.plan_file is None):
                raise ValueError("Governor requires --governor-root and an actual --plan-file")
        from .campaign import run_probe, run_worker_chain
        from .runtime import OllamaSessions
        run = prepare(args.output_root, repo=args.repo_root, label=args.action)
        # Emit before inference so incomplete/error runs are still locatable.
        print(f"RUN_DIR={run}", flush=True)
        write_json(run / "runner-inputs.json", {
            "model": args.model, "phase": args.phase, "through": args.through,
            "role": args.role, "host_execution_acknowledged": args.allow_host_execution,
            "context_tokens": args.context_tokens, "max_output_tokens": args.max_output_tokens,
            "timeout_seconds": args.timeout_seconds, "keep_alive_seconds": args.keep_alive_seconds,
            "runner_sha256": snapshot(Path(__file__).parent),
            "repetition_note": "temperature 0 / seed 42; repeated rollouts are not independent statistical samples",
            "comparison": "same packet, prompts, runtime/model identity and settings required",
        })
        sessions = OllamaSessions(args.repo_root, run, args.model,
                    context_tokens=args.context_tokens, max_output_tokens=args.max_output_tokens,
                    timeout_seconds=args.timeout_seconds, keep_alive_seconds=args.keep_alive_seconds)
        if args.action == "probe":
            summary = run_probe(run, args.input_run, sessions, role=args.role, repo=args.repo_root,
                    governor_root=args.governor_root, plan_file=args.plan_file,
                    allow_host_execution=args.allow_host_execution)
            row = summary["results"][0]
            code = 0 if row["status"] == "success" and row["scope"]["passed"] and row["source_unchanged"] else 1
        else:
            repetitions = 1 if args.phase == "screen" else 3
            summaries = []
            for ordinal in range(1, repetitions + 1):
                trial = run if ordinal == 1 else prepare(run / "repetitions", repo=args.repo_root, label=f"r{ordinal}")
                summaries.append(run_worker_chain(trial, sessions, through=args.through,
                    repo=args.repo_root, ordinal=ordinal, allow_host_execution=True))
                write_json(run / "repetition-progress.json", {"finished": ordinal, "planned": repetitions})
            summary = {"campaign": "assistant-001-v1", "track": "fixed-plan-worker-chain",
                "phase": args.phase, "repetitions": repetitions,
                "results": [r for s in summaries for r in s["results"]],
                "planned_cases": sum(s["planned_cases"] for s in summaries),
                "completed_cases": sum(s["completed_cases"] for s in summaries),
                "passed": all(s["passed"] for s in summaries),
                "qualification_status": "human-review-pending", "os_sandbox": False}
            code = 0 if summary["passed"] else 1
        write_json(run / "summary.json", summary)
        review_package(run, summary, args.model, args.phase, args.context_tokens)
        print(f"RUN_DIR={run}", flush=True)
        return code
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
