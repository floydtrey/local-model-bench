"""Immutable packet loading and candidate-only materialization."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

PACKET_ID = "assistant-001-v1"
DOCS = ("PROJECT_INTENT.md", "CONTRACT.md", "TASKS.md")


def repository_root():
    return Path(__file__).resolve().parents[3]


def packet_root(repo=None):
    return Path(repo or repository_root()) / "project-benchmarks/assistant-001/v1"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(root):
    root = Path(root); result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in benchmark workspaces")
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_file():
            if path.stat().st_size > 2_000_000:
                raise ValueError("Candidate file exceeds 2 MB review limit")
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def write_json(path, value):
    """Atomic checkpoint replacement; raw run evidence is kept separately."""
    import os
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def validate_packet(repo=None):
    root = packet_root(repo)
    lock = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if lock.get("packet_id") != PACKET_ID:
        raise ValueError("Unexpected packet identity")
    actual = snapshot(root); actual.pop("manifest.json", None)
    if actual != lock.get("files"):
        changed = sorted(k for k in set(actual) | set(lock.get("files", {}))
                         if actual.get(k) != lock.get("files", {}).get(k))
        raise ValueError("Packet integrity mismatch: " + ", ".join(changed))
    packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
    if [t["id"] for t in packet["tasks"]] != [f"T0{i}" for i in range(1, 7)]:
        raise ValueError("Invalid fixed task sequence")
    return packet, digest(root / "manifest.json")


def task_info(task, repo=None):
    packet, _ = validate_packet(repo)
    return next(t for t in packet["tasks"] if t["id"] == task)


def prepare(output_root=None, *, repo=None, label="candidate"):
    repo = Path(repo or repository_root()).resolve()
    packet, packet_hash = validate_packet(repo)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", label):
        raise ValueError("Label must be a short filesystem-safe identifier")
    output = Path(output_root or repo / "local-state/assistant-001").resolve()
    source = packet_root(repo)
    if output == source or source in output.parents:
        raise ValueError("Output cannot be inside the frozen packet")
    output.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + label + "-" + uuid4().hex[:8]
    run = output / name
    run.mkdir(exist_ok=False)
    workspace = run / "workspace"
    shutil.copytree(source / "starter", workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for doc in DOCS:
        shutil.copyfile(source / doc, workspace / doc)
    write_json(run / "run.json", {
        "packet_id": PACKET_ID, "packet_sha256": packet_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_initial_sha256": snapshot(workspace),
        "candidate_view": "starter + released contract only; no assessor or reference",
        "qualification_status": "human-review-pending", "os_sandbox": False,
    })
    return run


def read_run(run, repo=None):
    run = Path(run).resolve()
    packet, packet_hash = validate_packet(repo)
    record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if record.get("packet_id") != PACKET_ID or record.get("packet_sha256") != packet_hash:
        raise ValueError("Run does not belong to this exact frozen packet")
    workspace = run / "workspace"
    if not workspace.is_dir() or workspace.is_symlink():
        raise ValueError("Missing or invalid run workspace")
    snapshot(workspace)
    return record, packet


def scope_diff(before, after, writable):
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    unauthorized = sorted(set(changed) - set(writable))
    return {"changed_paths": changed, "unauthorized_paths": unauthorized,
            "passed": not unauthorized, "after_sha256": after}


def task_prompt(run, task, previous_handoff, repo=None):
    root = packet_root(repo); info = task_info(task, repo)
    task_text = (root / "TASKS.md").read_text(encoding="utf-8")
    span = task_text.split(f"## {task}:", 1)[1].split("\n## T", 1)[0]
    return (f"# {PACKET_ID} / {task}\n\n" + f"## {task}:" + span +
            "\n## Required source context\n" +
            "\n".join((root / doc).read_text(encoding="utf-8") for doc in DOCS[:2]) +
            "\n## Actual predecessor handoff\n" + (previous_handoff or "First task; there is no predecessor.") +
            "\n## Workspace\n" + str(Path(run) / "workspace") +
            "\nRead existing files before changing them. Use list_files, read_file, write_file and run_tests "
            "only as exposed. run_tests takes no arguments and executes the visible unittest suite. "
            "Only these files may change: " + ", ".join(info["writable_paths"]) +
            ". Keep your final handoff in useful free prose, not an invented result form. "
            "The supplied public tests are examples, not proof of complete acceptance.\n")
