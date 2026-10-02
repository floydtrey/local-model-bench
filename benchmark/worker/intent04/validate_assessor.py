from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURE = REPO / "benchmark" / "worker" / "fixture-02"
VERIFIER = HERE / "verify_stage.py"
CRITERIA = HERE / "ASSESSOR_CRITERIA.json"

GOLD = {
    1: HERE / "gold" / "task-01" / "inventory" / "cli.py",
    2: HERE / "gold" / "task-02" / "inventory" / "cli.py",
    3: HERE / "gold" / "task-03" / "inventory" / "cli.py",
}

REQUIRED_CRITERIA = {
    "I04-T1-PARSER-SURFACE",
    "I04-T1-LIST-REGRESSION",
    "I04-T1-NO-EARLY-CSV",
    "I04-T1-NO-EARLY-EXPORT",
    "I04-T2-PARSER-SURFACE",
    "I04-T2-DEFAULT-FILTER",
    "I04-T2-INACTIVE-FILTER",
    "I04-T2-CSV-SCHEMA",
    "I04-T2-STDOUT",
    "I04-T2-USES-CSV-MODULE",
    "I04-T2-NO-EARLY-FILE-OUTPUT",
    "I04-T2-LIST-REGRESSION",
    "I04-T3-PARSER-SURFACE",
    "I04-T3-STDOUT-PRESERVED",
    "I04-T3-FILE-OUTPUT",
    "I04-T3-NO-STDOUT-ON-FILE",
    "I04-T3-FILE-ERROR",
    "I04-T3-CSV-SCHEMA",
    "I04-T3-FILTERING",
    "I04-T3-LIST-REGRESSION",
    "I04-IMPORT",
}


def run(cmd: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def main() -> int:
    criteria = json.loads(CRITERIA.read_text(encoding="utf-8"))
    present = set(criteria.get("checks", {}))
    missing = sorted(REQUIRED_CRITERIA - present)
    if missing:
        raise RuntimeError(f"assessor criteria missing check IDs: {missing}")

    with tempfile.TemporaryDirectory(prefix="worker-intent04-assessor-") as tmp:
        workspace = pathlib.Path(tmp) / "workspace"
        shutil.copytree(FIXTURE, workspace)

        baseline = run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            workspace,
        )
        require_ok(baseline, "fixture baseline regression suite")

        for stage in (1, 2, 3):
            target = workspace / "inventory" / "cli.py"
            shutil.copy2(GOLD[stage], target)

            for cache in workspace.rglob("__pycache__"):
                if cache.is_dir():
                    shutil.rmtree(cache, ignore_errors=True)

            verify = run(
                [sys.executable, str(VERIFIER), str(stage), "--json"],
                workspace,
            )
            require_ok(verify, f"gold stage {stage} deterministic verifier")
            parsed = json.loads(verify.stdout)
            if not parsed.get("passed"):
                raise RuntimeError(
                    f"gold stage {stage} verifier returned failure: {parsed}"
                )

            regressions = run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                workspace,
            )
            require_ok(regressions, f"gold stage {stage} regression suite")

            print(f"gold stage {stage}: PASS")

    print("INTENT04_DETERMINISTIC_ASSESSOR_VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
