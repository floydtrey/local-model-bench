"""Independent acceptance subprocess; explicit host execution, bounded evidence."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4
from .packet import digest, packet_root, read_run, scope_diff, snapshot, validate_packet, write_json


def terminate_owned(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15, check=True)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def assess(run, task="T06", *, repo=None, allow_host_execution=False,
           before=None, writable=None, timeout=120, packet_api=None, assessor_args=()):
    from . import packet as default_packet
    api = packet_api or default_packet
    if not allow_host_execution:
        raise ValueError("Candidate Python is not OS-sandboxed. Explicit --allow-host-execution is required.")
    if type(timeout) not in (float, int) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Assessor timeout must be finite and positive")
    run = Path(run).resolve(); record, packet = api.read_run(run, repo)
    tasks = [item for item in packet["tasks"] if item["id"] <= task]
    if task not in [item["id"] for item in tasks]:
        raise ValueError("Unknown task")
    workspace = run / "workspace"
    before = record["candidate_initial_sha256"] if before is None else before
    writable = [p for item in tasks for p in item["writable_paths"]] if writable is None else writable
    pre = snapshot(workspace); scope = scope_diff(before, pre, writable)
    evidence = run / "assessments" / (task + "-" + uuid4().hex[:8]); evidence.mkdir(parents=True)
    base = {"packet_id": record["packet_id"], "task": task, "passed": False,
            "scope": scope, "candidate_sha256": pre, "os_sandbox": False,
            "qualification_status": "human-review-pending"}
    if not scope["passed"]:
        base.update(status="scope_failure", exit_code=None, checks=[])
        write_json(evidence / "assessment.json", base)
        return base, evidence
    result_path = evidence / "checks.json"
    command = [sys.executable, "-I", "-B", str(api.packet_root(repo) / "assessor/checks.py"),
               "--workspace", str(workspace), "--task", task, "--result", str(result_path), *assessor_args]
    env = {k: v for k, v in os.environ.items() if k in
           ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL")}
    env["PYTHONIOENCODING"] = "utf-8"
    inventory = getattr(api, "expected_check_ids", None)
    expected = inventory(task, repo) if inventory else None
    started = time.monotonic(); reason = None
    out_path, err_path = evidence / "stdout.txt", evidence / "stderr.txt"
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with out_path.open("wb") as out, err_path.open("wb") as err:
        process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, shell=False, **options)
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    reason = "assessor_timeout"; terminate_owned(process); break
                if out_path.stat().st_size + err_path.stat().st_size > 8_000_000:
                    reason = "assessor_output_limit"; terminate_owned(process); break
                time.sleep(0.02)
        except BaseException:
            terminate_owned(process)
            raise
    base.update(exit_code=process.returncode, wall_seconds=time.monotonic() - started,
                assessor_sha256=digest(api.packet_root(repo) / "assessor/checks.py"))
    try:
        checks = json.loads(result_path.read_text(encoding="utf-8")) if reason is None else None
        valid = (isinstance(checks, dict) and checks.get("contract") == record["packet_id"]
                 and checks.get("task") == task and isinstance(checks.get("checks"), list))
        if not valid:
            raise ValueError("Missing or invalid assessor result")
        base.update(checks=checks["checks"], planned=checks.get("planned"), executed=checks.get("executed"),
                    status=checks.get("status", "candidate_error"), error=checks.get("error"))
        rows = checks["checks"]
        if expected is not None and sorted(r.get("case_id", "") for r in rows) != sorted(expected):
            raise ValueError("Assessor did not execute the frozen check inventory")
        base["passed"] = (process.returncode == 0 and checks.get("passed") is True and bool(rows)
                          and checks.get("executed") == checks.get("planned") == len(rows)
                          and all(r.get("passed") is True for r in rows))
    except (OSError, ValueError, KeyError):
        base.update(status=reason or "assessor_result_missing_or_invalid", checks=[])
    # Checks may import candidate code. Reverify frozen packet and the whole workspace.
    api.validate_packet(repo)
    post = snapshot(workspace)
    base["post_test_candidate_sha256"] = post
    if post != pre:
        base.update(passed=False, status="candidate_changed_during_assessment")
    write_json(evidence / "assessment.json", base)
    return base, evidence
