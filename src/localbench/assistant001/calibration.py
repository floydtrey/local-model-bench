"""Prove the assessor accepts a reference and rejects named behavioral defects."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from .packet import packet_root, validate_packet

# (name, file, exact source before/after, task, required failing check)
MUTATIONS = (
    ("boolean-confidence", "validation.py", "type(confidence) not in (int, float)",
     "not isinstance(confidence, (int, float))", "T01", "test_reject_boolean_confidence"),
    ("duplicate-conflict-ignored", "journal.py", 'raise EventConflictError("Event ID conflicts with existing evidence")',
     "return False", "T02", "test_duplicate_is_idempotent_and_conflict_immutable"),
    ("commit-deferred", "journal.py", "        with self._db:\n            return self._append(normalized)",
     "        return self._append(normalized)", "T02", "test_process_exit_after_successful_append_is_durable"),
    ("history-entity-filter-lost", "journal.py", 'and (entity is None or e["entity"] == entity)',
     "and True", "T03", "test_all_filters_precede_pagination"),
    ("arrival-order-state", "journal.py", 'if previous is None or (event["timestamp"], event["event_id"]) > (previous["timestamp"], previous["event_id"]):',
     "if True:", "T04", "test_late_arrival_never_overwrites_newer_observation"),
    ("inclusive-expiry", "journal.py", 'if now < instant(e["timestamp"]) + timedelta(seconds=e["ttl_seconds"])',
     'if now <= instant(e["timestamp"]) + timedelta(seconds=e["ttl_seconds"])',
     "T04", "test_expiry_is_half_open_and_does_not_resurrect"),
    ("source-fusion", "journal.py", 'key = (event["source"], event["entity"], event["type"])',
     'key = ("all", event["entity"], event["type"])', "T04", "test_source_entity_and_type_remain_distinct"),
    ("future-event-hides-present", "journal.py", 'if instant(event["timestamp"]) > now:',
     "if False:", "T04", "test_future_event_cannot_suppress_current_event"),
    ("confidence-over-time", "journal.py", 'if previous is None or (event["timestamp"], event["event_id"]) > (previous["timestamp"], previous["event_id"]):',
     'if previous is None or event["confidence"] > previous["confidence"]:',
     "T04", "test_confidence_does_not_override_time"),
    ("batch-partial-commits", "journal.py", "return [self._append(e) for e in normalized]",
     "return [self.append(e) for e in normalized]", "T05", "test_batch_conflict_rolls_back_all_new_rows"),
)


def install_reference(workspace, repo=None):
    """Trusted calibration helper only; production runners never call this."""
    root = packet_root(repo); workspace = Path(workspace)
    shutil.copytree(root / "starter", workspace, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in (root / "assessor/reference/assistant_journal").glob("*.py"):
        shutil.copyfile(path, workspace / "assistant_journal" / path.name)
    (workspace / "tests/test_candidate.py").write_text(
        "import unittest\nfrom assistant_journal import normalize_event\n"
        "class CalibrationPublicTest(unittest.TestCase):\n"
        "    def test_invalid_input(self):\n"
        "        with self.assertRaises(ValueError): normalize_event(None)\n", encoding="utf-8")
    return workspace


def check_workspace(workspace, task, result_path, repo=None, case=None):
    code = subprocess.run([sys.executable, "-I", "-B", str(packet_root(repo) / "assessor/checks.py"),
        "--workspace", str(workspace), "--task", task, "--result", str(result_path)] +
        (["--case", case] if case else []),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    return code.returncode, result


def self_test(repo=None):
    validate_packet(repo)
    with tempfile.TemporaryDirectory(prefix="assistant001-calibration-") as folder:
        root = Path(folder)
        reference = install_reference(root / "reference", repo)
        code, reference_result = check_workspace(reference, "T06", root / "reference.json", repo)
        rows = [{"name": "reference", "passed": code == 0 and reference_result["passed"],
                 "checks_executed": reference_result.get("executed")}]
        for name, filename, before, after, task, expected_failure in MUTATIONS:
            workspace = root / name; shutil.copytree(reference, workspace)
            path = workspace / "assistant_journal" / filename
            text = path.read_text(encoding="utf-8")
            if text.count(before) != 1:
                raise ValueError("Mutation target is no longer unique: " + name)
            path.write_text(text.replace(before, after), encoding="utf-8")
            code, result = check_workspace(workspace, task, root / (name + ".json"), repo, case=expected_failure)
            failed = [r["case_id"] for r in result.get("checks", []) if not r["passed"]]
            rows.append({"name": name, "passed": code == 1 and result.get("status") == "completed" and expected_failure in failed
                         and any("AssertionError" in r.get("diagnostics", "") for r in result.get("checks", [])),
                         "required_failure": expected_failure, "observed_failures": failed})
        # Starter rejection proves a blank implementation cannot be called a pass.
        starter = root / "starter"; shutil.copytree(packet_root(repo) / "starter", starter,
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        code, result = check_workspace(starter, "T01", root / "starter.json", repo)
        rows.append({"name": "unsolved-starter-rejected", "passed": code == 1 and not result["passed"]})
    return {"packet_id": "assistant-001-v1", "passed": all(row["passed"] for row in rows),
            "checks": rows, "real_models_started": 0, "production_services_contacted": 0}
