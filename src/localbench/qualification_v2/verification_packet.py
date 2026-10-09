"""Frozen Tester/Reviewer views over the existing project packets (no execution)."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from uuid import uuid4

from localbench.assistant001.packet import repository_root, scope_diff, snapshot, write_json
from localbench.v2.contracts import sha256_json
from .planner_packet import read_regular, sha
from .worker import APIS

VERSION = "qualification-v2/verification-cases-v1"
FREEZE_SHA256 = "c721ff4357d79153aa775d1abcb12e9560a83528b31889c888beb25b0a76ab81"
WRITABLE = ["tests/test_candidate.py"]


def fixture_root(repo=None):
    return Path(repo or repository_root()) / "docs/qualification-v2/verification-v1"


def load_cases(repo=None):
    root = fixture_root(repo)
    raw = read_regular(root / "freeze.json")
    if sha(raw) != FREEZE_SHA256:
        raise ValueError("Verification freeze changed; version and review required")
    freeze = json.loads(raw)
    for name, expected in freeze["files"].items():
        if sha(read_regular(root / name)) != expected:
            raise ValueError("Frozen verification material changed: " + name)
    for name, expected in freeze["sources"].items():
        if sha(read_regular(Path(repo or repository_root()) / name)) != expected:
            raise ValueError("Verification source changed: " + name)
    return json.loads(read_regular(root / "cases.json"))["cases"]


def case_spec(case_id, repo=None):
    return next(c for c in load_cases(repo) if c["case_id"] == case_id)


def implementation(project, variant, repo=None):
    """Explicit authored fixtures; never installed into a Worker continuation.

    Reuse immutable reference bytes and mutation recipes. Remove only module
    provenance docstrings from the *new* visible copies to avoid answer leakage.
    """
    api = APIS[project]
    api.validate_packet(repo)
    root = api.packet_root(repo)
    package = "assistant_journal" if project == "assistant-001" else "assistant_simulator"
    files = {}
    for path in sorted((root / "starter").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            name = path.relative_to(root / "starter").as_posix()
            if name.startswith((package + "/", "scenarios/")):
                files[name] = path.read_text(encoding="utf-8")
    if variant != "incomplete":
        source = root / "assessor/reference"
        if project == "assistant-001":
            source /= package
        for path in sorted(source.glob("*.py")):
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            if ast.get_docstring(tree):
                content = "".join(content.splitlines(keepends=True)[tree.body[0].end_lineno:])
            files[package + "/" + path.name] = content
    if variant in ("defective", "multiple"):
        from localbench.assistant001.calibration import MUTATIONS as M1
        from localbench.assistant002.calibration import MUTATIONS as M2
        mutation = (M1 if project == "assistant-001" else M2)[0]
        _, filename, before, after, _, _ = mutation
        path = package + "/" + filename
        if files[path].count(before) != 1:
            raise ValueError("Mutation anchor changed")
        files[path] = files[path].replace(before, after)
        if variant == "multiple":
            before, after = (("type(ttl) is not int", "not isinstance(ttl, int)")
                             if project == "assistant-001" else
                             ("if len(set(ids)) != len(ids):", "if False:"))
            if files[path].count(before) != 1:
                raise ValueError("Second mutation anchor changed")
            files[path] = files[path].replace(before, after)
    return files


def build_packet(case_id, repo=None):
    spec = case_spec(case_id, repo)
    root = fixture_root(repo)
    files = implementation(spec["project"], spec["variant"], repo)
    for name, source in spec["test_files"].items():
        files[name] = read_regular(root / source).decode()
    if spec.get("scope_extra"):
        files["unrequested.txt"] = "Unrequested scope expansion.\n"
    hashes = {k: sha(v.encode()) for k, v in sorted(files.items())}
    if hashes != spec["artifact_sha256"]:
        raise ValueError("Frozen implementation view changed")
    api = APIS[spec["project"]]
    prompt = ("Evaluate the supplied task and actual artifacts. Respond in natural language with "
              "PASS, FAIL or BLOCKED, precise evidence, uncertainty and bounded next steps. "
              "Claims and exit codes alone are not proof. Your verdict grants no permissions.\n")
    if spec["role"] == "tester":
        prompt += ("Only tests/test_candidate.py may be edited. Production files, requirements and "
                   "other tests are read-only. Use existing file tools and run_tests. Identify coverage "
                   "gaps, add meaningful tests where needed, and distinguish faulty tests from faulty code.\n")
    else:
        prompt += "Read-only review: no tools, file changes or execution are authorized.\n"
    for name in ("PROJECT_INTENT.md", "CONTRACT.md"):
        prompt += "\n# " + name + "\n" + (api.packet_root(repo) / name).read_text(encoding="utf-8")
    prompt += "\n# Assigned acceptance scope\n" + spec["assignment"]
    for name, content in sorted(files.items()):
        prompt += f"\n# File {name}\nSHA256: {hashes[name]}\n{content}\n"
    evidence = json.loads(read_regular(root / spec["evidence_file"]))
    prompt += "\n# Supplied evidence (claims are labeled separately)\n" + json.dumps(evidence, sort_keys=True)
    if len(prompt.encode()) > 512000:
        raise ValueError("Verification context exceeds limit; no truncation")
    return {"schema_version": VERSION, "case_id": case_id, "role": spec["role"],
            "project": spec["project"], "prompt": prompt, "files": files,
            "artifact_sha256": hashes, "input_sha256": sha(prompt.encode()),
            "evidence": evidence, "evidence_sha256": sha256_json(evidence)}


def prepare(case_id, output, repo=None):
    packet = build_packet(case_id, repo)
    root = Path(repo or repository_root()).resolve()
    output = Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError("Disposable verification runs must be outside the repository")
    run = output / uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    for name, content in packet["files"].items():
        dest = run / "workspace" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.encode())
    (run / "prompt.txt").write_bytes(packet["prompt"].encode())
    write_json(run / "verification-input.json", {k: v for k, v in packet.items()
                                               if k not in ("files", "prompt", "evidence")})
    return run


def safe_snapshot(workspace):
    # Extend the reused snapshot's link check to Windows junctions and ancestors.
    for path in Path(workspace).rglob("*"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked/reparse workspace")
        if path.is_file():
            read_regular(path)
    return snapshot(workspace)


def verify_run(run, repo=None, *, pristine=False):
    run = Path(run)
    record = json.loads(read_regular(run / "verification-input.json"))
    packet = build_packet(record["case_id"], repo)
    expected = {k: v for k, v in packet.items() if k not in ("files", "prompt", "evidence")}
    if record != expected or read_regular(run / "prompt.txt") != packet["prompt"].encode():
        raise ValueError("Verification input changed")
    actual = safe_snapshot(run / "workspace")
    if pristine and actual != packet["artifact_sha256"]:
        raise ValueError("Fresh case workspace required")
    return packet, scope_diff(packet["artifact_sha256"], actual,
                              WRITABLE if packet["role"] == "tester" else [])
