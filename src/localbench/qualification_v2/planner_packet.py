"""Allowlisted, content-pinned Planner view. No candidate filesystem capability."""
from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from uuid import uuid4

from localbench.assistant001.packet import repository_root, write_json
from .contract import CONTROLLED, validate_disclosure, validate_selection

VERSION = "qualification-v2/blind-planner-input-v1"
PACKETS = {
    "assistant-001": "c5262e0f7f1a5ba5a93e7ac5e2d7b884c84c86352a448e0ba486a871eefcc93c",
    "assistant-002": "0d8d98cae44793ff6ea2b8d9203673421873ea868c030a261b45de814e8fd026",
}
CASES = ("complete", "missing-goal")
MISSING_GOAL = ("The owner has supplied source interfaces as background but has not supplied "
                "the intended goal or requested change. Do not infer a work order from these "
                "files. Explain what information is needed before a plan can be made.\n")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path) -> bytes:
    """Reject symlinks and Windows junction/reparse routes, including ancestors."""
    for part in (path, *path.parents):
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked/reparse input is prohibited")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Expected a regular input file")
    return path.read_bytes()


def build_packet(project: str, case: str = "complete", repo: Path | None = None):
    if project not in PACKETS or case not in CASES:
        raise ValueError("Unknown project or Planner case")
    repo = Path(repo or repository_root())
    validate_selection(CONTROLLED, "planner", "direct_ollama", repo_root=repo)
    validate_disclosure("planner", ["project_intent", "candidate_contract", "starter_readonly"], repo_root=repo)
    base = repo / "project-benchmarks" / project
    spec_path = base / "qualification-v2/PLANNER_PACKET.json"
    raw = read_regular(spec_path)
    if sha(raw) != PACKETS[project]:
        raise ValueError("Planner packet metadata changed; version/review required")
    spec = json.loads(raw)
    # Pin original manifest identity too: changing both source and manifest fails.
    if sha(read_regular(base / "v1/manifest.json")) != spec["source_manifest_sha256"]:
        raise ValueError("Frozen source manifest changed")
    files = {}
    for name, expected in spec["files"].items():
        raw = read_regular(base / "qualification-v2/planner-input-v1" / name)
        if sha(raw) != expected:
            raise ValueError("Planner input integrity mismatch: " + name)
        files[name] = raw.decode("utf-8")
    if case == "missing-goal":
        # Explicit counterfactual case: no released intent/contract is delivered.
        # Keep public interfaces but withhold scenarios/tests which imply a work order.
        files = {k: v for k, v in files.items() if k.endswith(".py") and not k.startswith("tests/")}
        files["PROJECT_INTENT.md"] = MISSING_GOAL
        files["CONTRACT.md"] = "No requested behavior has been supplied for this case.\n"
        files["README.md"] = "Background source only; this is not an implementation request.\n"
    # Defense in depth. Hashes/explicit selection, not this scan, enforce disclosure.
    text = "\n".join(k + "\n" + v for k, v in sorted(files.items()))
    if re.search(r"TASKS\.md|REFERENCE_PLAN|TRACEABILITY|assessor[/\\]|\bT0[1-6]\b|UPSTREAM\.json", text, re.I):
        raise ValueError("Scaffold/oracle disclosure in candidate view")
    prompt = ("Read the complete context below and respond in free prose. Plan only; "
              "no implementation or execution is authorized. There are no tools. "
              "Do not assume that successful planning grants any later role authority.\n")
    for name, content in sorted(files.items()):
        prompt += f"\n--- FILE: {name} ---\n{content}\n--- END FILE ---\n"
    if len(prompt.encode()) > 512000:
        raise ValueError("Planner context exceeds limit; no truncation")
    return {
        "project": project, "case": case, "case_id": project + "-planner-v2-" + case,
        "schema_version": VERSION, "packet_manifest_sha256": PACKETS[project],
        "input_sha256": sha(prompt.encode()), "prompt": prompt, "files": files,
        "file_sha256": {k: sha(v.encode()) for k, v in sorted(files.items())},
    }


def prepare(project: str, output: Path, *, case="complete", repo=None):
    packet = build_packet(project, case, repo)
    root = Path(repo or repository_root()).resolve()
    output = Path(output).resolve()
    protected = root / "project-benchmarks"
    if output == protected or protected in output.parents:
        raise ValueError("Output must be outside benchmark source packets")
    output.mkdir(parents=True, exist_ok=True)
    run = output / (packet["case_id"] + "-" + uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    for name, content in packet["files"].items():
        dest = run / "workspace" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.encode())
    (run / "prompt.txt").write_bytes(packet["prompt"].encode())
    write_json(run / "run.json", {k: v for k, v in packet.items() if k not in ("files", "prompt")})
    return run


def verify_run(run: Path, repo=None):
    run = Path(run)
    record = json.loads(read_regular(run / "run.json"))
    packet = build_packet(record["project"], record["case"], repo)
    expected = {k: v for k, v in packet.items() if k not in ("files", "prompt")}
    if record != expected or read_regular(run / "prompt.txt") != packet["prompt"].encode():
        raise ValueError("Run input/metadata changed")
    workspace = run / "workspace"
    actual = {}
    for path in workspace.rglob("*"):
        # Reject links even when they are directories or not selected files.
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked workspace path")
        if path.is_file():
            actual[path.relative_to(workspace).as_posix()] = sha(read_regular(path))
    if actual != packet["file_sha256"]:
        raise ValueError("Workspace differs from explicit Planner allowlist")
    return packet
