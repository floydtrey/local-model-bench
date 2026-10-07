"""Pure source-backed role packets for the Flash-Next campaign.

These builders do not execute models, tools, or tests, and do not qualify a
candidate. The caller sends ``setup_prompt`` as a user turn, retains the actual
assistant response, then sends ``task_prompt`` as a user turn in that history.
No role text is silently moved into a system prompt. Original source bytes are
verified against the vendored source manifests before they are used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


HISTORICAL_COMMIT = "fce91a7fa409aecd824a3fa1229724b0aab56812"
REVIEWER_COMMIT = "e8bf69e664504fc54fbb94a00131b52e0a9c0de9"
REVIEWER_SETUP_SUFFIX = (
    "\n\nThis turn establishes your read-only Reviewer role only. Do not inspect "
    "files or begin review yet. Reply exactly: REVIEWER_READY\n"
)

# Verbatim text and section order from run-governor-batch.ps1 Build-Packet.
GOVERNOR_QUALIFICATION_CONDITION = (
    "This is an isolated qualification simulation. You are reviewing the supplied "
    "plan only. You are not executing a live governed action and are not being "
    "asked to establish or modify a protected role-to-model assignment.\n\n"
    "The unfinished Owner identity and protected role-to-model assignment entries "
    "in State are outside this benchmark condition. Do not use those unfinished "
    "entries as a reason to reject or leave unresolved an otherwise reviewable "
    "plan unless the proposed plan itself requires an Owner-only action or "
    "changes a protected assignment.\n\n"
    "All other supplied Law, State, General Intent, Project Intent, and task "
    "constraints apply normally."
)

PLANNER_INTENTS = (
    "intent-01-cli-time-filter.md",
    "intent-02-webhook-retry-policy.md",
    "intent-03-config-default.md",
    "intent-04-batch-export.md",
    "intent-05-job-cancellation.md",
    "intent-06-contextual-storage-backend.md",
)
GOVERNOR_PACKETS = (
    ("a", PLANNER_INTENTS[2], "plan-a-simple.md"),
    ("b", PLANNER_INTENTS[3], "plan-b-medium.md"),
    ("c", PLANNER_INTENTS[4], "plan-c-hard.md"),
    ("d", PLANNER_INTENTS[5], "plan-d-contextual-storage.md"),
)


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


class _Corpus:
    def __init__(self, campaign_root: Path, name: str) -> None:
        self.root = Path(campaign_root) / "sources" / name
        self.manifest = json.loads((self.root / "SOURCE_MANIFEST.json").read_bytes())
        self.rows = {row["path"]: row for row in self.manifest["files"]}
        if len(self.rows) != len(self.manifest["files"]):
            raise ValueError(f"Duplicate source path in {self.root}")
        self.repository = self.manifest.get("source_repository", self.manifest.get("repository"))
        self.commit = self.manifest.get("source_commit", self.manifest.get("commit"))
        expected = HISTORICAL_COMMIT if name == "local-model-bench" else REVIEWER_COMMIT
        if self.commit != expected:
            raise ValueError(f"Unexpected source lineage for {name}: {self.commit}")

    def read(self, path: str) -> tuple[str, dict[str, Any]]:
        if path not in self.rows:
            raise ValueError(f"Source is not pinned in manifest: {path}")
        row = self.rows[path]
        local_path = self.root / path
        data = local_path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        expected_blob = row.get("source_git_blob", row.get("git_blob_sha"))
        if _sha(data) != row["sha256"] or len(data) != row["bytes"] or blob != expected_blob:
            raise ValueError(f"Pinned source bytes changed: {local_path}")
        return data.decode("utf-8-sig"), {
            "source_repository": self.repository,
            "source_commit": self.commit,
            "source_path": path,
            "local_path": str(local_path.resolve()),
            "source_git_blob": blob,
            "sha256": _sha(data),
            "bytes": len(data),
        }


def _legacy_assembly_ref(path: str, blob: str) -> dict[str, Any]:
    return {
        "source_repository": "floydtrey/local-model-bench",
        "source_commit": HISTORICAL_COMMIT,
        "source_path": path,
        "source_git_blob": blob,
        "purpose": "Original prompt assembly and two-turn ordering; not a runtime fallback.",
    }


def _case(
    case_id: str,
    role: str,
    setup_prompt: str,
    task_prompt: str,
    source_refs: list[dict[str, Any]],
    *,
    setup_expected_marker: str | None = None,
    expected_observations: Mapping[str, Any] | None = None,
    fixture_transformations: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "role": role,
        "setup_prompt": setup_prompt,
        "setup_expected_marker": setup_expected_marker,
        "task_prompt": task_prompt,
        "source_refs": source_refs,
        "expected_observations": dict(expected_observations or {}),
        "fixture_transformations": list(fixture_transformations),
        "correctness": "human-review-pending",
        "qualification_status": "provisional-unqualified" if role == "reviewer" else "candidate-unqualified",
        "prompt_protocol": "user role setup; actual assistant response; user task in the same fresh case history",
        "tools": [],
    }


def _planner_cases(campaign_root: Path) -> list[dict[str, Any]]:
    corpus = _Corpus(campaign_root, "local-model-bench")
    role, role_ref = corpus.read("benchmark/planner/ROLE_PROMPT.txt")
    _, freeze_ref = corpus.read("benchmark/planner/FROZEN_V1.md")
    assembly_ref = _legacy_assembly_ref(
        "benchmark/dsh/run-single-dsh.ps1", "553ca0f43a51b47898dd7421cf88a6e56f93967d"
    )
    result = []
    for ordinal, filename in enumerate(PLANNER_INTENTS, 1):
        task, task_ref = corpus.read("benchmark/planner/" + filename)
        observations: dict[str, Any] = {
            "assessment": "manual review against the unchanged role prompt and original intent",
            "checks": [
                "Distinguish discoverable existing facts from missing requirement or policy decisions.",
                "Bounded tasks preserve intent, scope, prerequisites and executable acceptance conditions.",
                "An AMBIGUOUS or BLOCKED result stops without appending Worker tasks.",
            ],
        }
        if ordinal == 2:
            observations["known_missing_decision"] = "Transient versus permanent failure classification."
        result.append(_case(
            f"planner-intent-{ordinal:02d}", "planner", role, task,
            [role_ref, task_ref, freeze_ref, assembly_ref],
            expected_observations=observations,
        ))
    return result


def governor_packet(
    *, intent: str, plan: str, law: str, state: str, general_intent: str, project_intent: str
) -> str:
    """Port the historical Build-Packet text without adding role behavior."""
    return (
        "# Governor Review Packet\n\n## Qualification Condition\n\n"
        + GOVERNOR_QUALIFICATION_CONDITION
        + "\n\n## Original Project Intent\n\n" + intent
        + "\n\n## Proposed Plan\n\n" + plan
        + "\n\n## Law\n\n" + law
        + "\n\n## State\n\n" + state
        + "\n\n## General Intent\n\n" + general_intent
        + "\n\n## Project Intent\n\n" + project_intent
    )


def _governor_cases(campaign_root: Path, governor_root: Path | None) -> list[dict[str, Any]]:
    if governor_root is None:
        raise ValueError("Governor cases require the actual canonical Governor repository root.")
    corpus = _Corpus(campaign_root, "local-model-bench")
    role, role_ref = corpus.read("benchmark/governor/ROLE_PROMPT.txt")
    project_intent, project_ref = corpus.read("benchmark/governor/reference/PROJECT_INTENT.md")
    _, packets_ref = corpus.read("benchmark/governor/PACKETS_V1.md")
    governance: dict[str, str] = {}
    governance_refs = []
    for key, name in (("law", "LAW.md"), ("state", "STATE.md"), ("general_intent", "GENERAL_INTENT.md")):
        path = Path(governor_root) / "docs" / name
        data = path.read_bytes()
        text = data.decode("utf-8-sig")
        if not text.strip():
            raise ValueError(f"Canonical Governor document is empty: {path}")
        governance[key] = text
        governance_refs.append({
            "source_repository": "canonical local Governor repository supplied by operator",
            "source_commit": None,
            "source_path": "docs/" + name,
            "local_path": str(path.resolve()),
            "sha256": _sha(data),
            "bytes": len(data),
            "snapshot_policy": "Exact document content is included in this case task_prompt; hash identifies the read bytes.",
        })
    assembly_ref = _legacy_assembly_ref(
        "benchmark/run-governor-batch.ps1", "a323ed1be07e2f7bf9bdba141e8cb3693c66c5eb"
    )
    turn_ref = _legacy_assembly_ref(
        "benchmark/dsh/run-single-dsh.ps1", "553ca0f43a51b47898dd7421cf88a6e56f93967d"
    )
    result = []
    for letter, intent_name, plan_name in GOVERNOR_PACKETS:
        intent, intent_ref = corpus.read("benchmark/planner/" + intent_name)
        plan, plan_ref = corpus.read("benchmark/governor/plans/" + plan_name)
        packet = governor_packet(intent=intent, plan=plan, project_intent=project_intent, **governance)
        result.append(_case(
            "governor-packet-" + letter, "governor", role, packet,
            [role_ref, intent_ref, plan_ref, project_ref, packets_ref, assembly_ref, turn_ref, *governance_refs],
            expected_observations={
                "assessment": "manual review against exact supplied governance and unchanged fixed plan",
                "checks": [
                    "Review all supplied Law, State, General Intent and Project Intent under the original simulation condition.",
                    "Keep task-specific and ALL guidance grounded in intent without changing the proposed plan.",
                    "Distinguish an actual plan violation from unfinished Owner/protected-assignment entries excluded by this simulation.",
                ],
            },
        ))
    return result


def reviewer_packet(
    *, intent: str, plan: str, guidance: str, task: str, workerFinal: str,
    changes: Sequence[Mapping[str, Any]], tests: Sequence[Mapping[str, Any]],
    workspace: str, execution: str | None,
) -> str:
    """Exact Python port of native-lab/reviewer-dispatch.mjs reviewerPacket.

    Input event/test text is a supplied evidence payload. Building this string
    never represents a fresh tool or test execution.
    """
    changed = "\n\n".join(
        f"### {change['path']}\nStatus: {change['status']}\nSHA-256: {change['sha256'] if change.get('sha256') is not None else 'absent'}\n"
        + ("Content unavailable or not text." if "content" not in change else
           "Current content:\n```\n" + str(change["content"]) + "\n```")
        for change in changes
    )
    checks = "\n\n".join(
        f"### {item['name']}\nCommand: {item['command']}\nExit code: {item['exitCode']}\n"
        f"Stdout SHA-256: {item['stdoutSha256']}\nStderr SHA-256: {item['stderrSha256']}\n"
        f"Stdout:\n{item['stdout']}\nStderr:\n{item['stderr']}"
        for item in tests
    ) if tests else "No independently captured test result was supplied. Worker prose is not test evidence."
    return (
        "# Reviewer evidence packet\n\n## Original released intent\n" + intent
        + "\n\n## Full Planner plan (unchanged)\n" + plan
        + "\n\n## Assigned task (exact plan span)\n" + task
        + "\n\n## Governor guidance (advisory)\n" + guidance
        + "\n\n## Isolated workspace\n" + workspace
        + "\n\n## Observed Worker file changes\n" + (changed or "No file changes observed.")
        + "\n\n## Native Worker tool capture (execution evidence, not an independent test)\n"
        + (execution or "No native tool calls or results were captured.")
        + "\n\n## Independently captured existing-test evidence\n" + checks
        + "\n\n## Worker final response (claim, not independent evidence)\n" + workerFinal + "\n"
    )


def _reviewer_cases(campaign_root: Path) -> list[dict[str, Any]]:
    corpus = _Corpus(campaign_root, "deepseek-lab")
    role, role_ref = corpus.read("native-lab/reviewer-role.md")
    _, dispatcher_ref = corpus.read("native-lab/reviewer-dispatch.mjs")
    test_source, tests_ref = corpus.read("native-lab/reviewer-dispatch.test.mjs")
    _, status_ref = corpus.read("docs/REVIEWER_CONNECTION_SLICE.md")
    refs = [role_ref, dispatcher_ref, tests_ref, status_ref]
    setup = role + REVIEWER_SETUP_SUFFIX

    # The exact small title fixture literals come from fixture() in the pinned
    # dispatcher tests. Guard their provenance so a source change cannot silently
    # leave an unrelated hard-coded fixture in this campaign.
    required_literals = (
        "Add a title field without changing rendering yet.",
        "Task 1: Add title field.", "Task 2: Update rendering.",
        "ALL: preserve existing behavior.", 'title = "Report"',
        "Handoff note: title added; I ran tests.", "2 tests passed",
    )
    if not all(literal in test_source for literal in required_literals):
        raise ValueError("Pinned Reviewer title fixture no longer matches its source literals.")
    title = {
        "intent": "Add a title field without changing rendering yet.\n",
        "plan": "Task 1: Add title field.\nTask 2: Update rendering.\n",
        "guidance": "ALL: preserve existing behavior.\n",
        "task": "Task 1: Add title field.\n",
        "workerFinal": "Handoff note: title added; I ran tests.",
        "changes": [{"path": "config.py", "status": "changed", "sha256": _sha('title = "Report"\n'), "content": 'title = "Report"\n'}],
        "tests": [{"name": "existing tests", "command": "python -m unittest", "exitCode": 0,
                   "stdout": "2 tests passed\n", "stderr": "", "stdoutSha256": _sha("2 tests passed\n"), "stderrSha256": _sha("")}],
        "workspace": "isolated-reviewer-fixture/job",
        "execution": "",
    }
    result = []

    def append_case(
        case_id: str, payload: Mapping[str, Any], expected: Mapping[str, Any],
        transformations: Sequence[str], source_refs: list[dict[str, Any]],
    ) -> None:
        spec = _case(
            case_id, "reviewer", setup, reviewer_packet(**payload), source_refs,
            setup_expected_marker="REVIEWER_READY",
            expected_observations={
                "assessment": "human review required; expected observations are fixture design, not candidate qualification",
                "evidence_origin": "synthetic qualification packet built from pinned source fixtures; not a newly executed Worker or test",
                **expected,
            },
            fixture_transformations=transformations,
        )
        # Keep exact structured inputs alongside the rendered packet for audit.
        spec["packet_inputs"] = dict(payload)
        result.append(spec)

    append_case(
        "reviewer-title-captured-tests", title,
        {"expected_verdict": "PASS", "checks": ["Assess Task 1 only; rendering is a later task.", "Cite actual supplied file and test capture; PASS remains advisory."]},
        ["Original synthetic dispatcher fixture values retained; random temporary workspace replaced by a stable isolated fixture label."], refs,
    )
    append_case(
        "reviewer-title-claim-only", {**title, "tests": []},
        {"expected_verdict": None, "acceptable_verdicts": ["PASS", "BLOCKED"],
         "checks": ["Explicitly report that independently captured tests are absent.", "Do not treat the Worker claim 'I ran tests' as an independently verified test.", "Use BLOCKED only if missing evidence prevents reliable judgment of the assigned task."]},
        ["Reuse the existing no-test-capture variant from reviewer-dispatch.test.mjs; stable workspace label."], refs,
    )

    fixture = "native-lab/test-fixtures/native-worker-window/"
    intent, intent_ref = corpus.read(fixture + "intent.md")
    plan, plan_ref = corpus.read(fixture + "planner-plan.md")
    guidance, guidance_ref = corpus.read(fixture + "governor-guidance.md")
    note_refs = [*refs, intent_ref, plan_ref, guidance_ref]

    def trace(content: str) -> str:
        events = [
            {"type": "tool_call", "callId": "read-1", "tool": "read_file", "input": {"path": "note.txt"}},
            {"type": "tool_result", "callId": "read-1", "status": "completed", "result": "alpha\n"},
            {"type": "tool_call", "callId": "write-1", "tool": "write_file", "input": {"path": "note.txt", "content": content}},
            {"type": "tool_result", "callId": "write-1", "status": "completed", "result": "written"},
            {"type": "tool_call", "callId": "read-2", "tool": "read_file", "input": {"path": "note.txt"}},
            {"type": "tool_result", "callId": "read-2", "status": "completed", "result": content},
        ]
        return "\n".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in events)

    note = {
        "intent": intent, "plan": plan, "guidance": guidance, "task": plan,
        "workerFinal": "note.txt contains beta followed by exactly one newline. No owner guidance was delivered before the write. No other file changed.",
        "changes": [{"path": "note.txt", "status": "changed", "sha256": _sha("beta\n"), "content": "beta\n"}],
        "tests": [], "workspace": "isolated-reviewer-fixture/native-worker-window", "execution": trace("beta\n"),
    }
    derivation = "New evidence case derived from unchanged native-worker-window intent, exact full single-task plan, and Governor guidance; tool events are synthetic inputs."
    append_case(
        "reviewer-note-exact", note,
        {"expected_verdict": "PASS", "checks": ["Exact beta plus one LF, required readback, and only note.txt changed.", "No independently captured test was supplied; the recorded tool actions remain execution evidence."]},
        [derivation, "Supply correct final file and matching synthetic read/write/readback trace; no delivered owner guidance."], note_refs,
    )
    append_case(
        "reviewer-note-wrong-content", {
            **note,
            "changes": [{"path": "note.txt", "status": "changed", "sha256": _sha("gamma\n"), "content": "gamma\n"}],
            "execution": trace("gamma\n"),
        },
        {"expected_verdict": "FAIL", "checks": ["The observed gamma content violates the required beta default without delivered guidance.", "The Worker final claim conflicts with file and tool evidence; describe a task defect, not a runtime incompatibility."]},
        [derivation, "Change observed content and matching trace from beta to gamma while retaining the Worker beta claim; no guidance authorizes the change."], note_refs,
    )
    append_case(
        "reviewer-note-scope-drift", {
            **note,
            "changes": [*note["changes"], {"path": "extra.txt", "status": "created", "sha256": _sha("unrequested\n"), "content": "unrequested\n"}],
        },
        {"expected_verdict": "FAIL", "checks": ["An additional changed file violates the explicit only-note.txt scope even if note.txt is correct."]},
        [derivation, "Add an unrequested extra.txt to observed changes while retaining the original task and Worker claim."], note_refs,
    )
    append_case(
        "reviewer-note-missing-evidence", {
            **note,
            "changes": [{"path": "note.txt", "status": "changed", "sha256": _sha("beta\n")}],
            "execution": "",
        },
        {"expected_verdict": "BLOCKED", "checks": ["Changed file content and readback are unavailable; exact bytes cannot be established from the Worker claim.", "Missing evidence is distinct from a demonstrated implementation defect."]},
        [derivation, "Withhold changed-file bytes and tool capture. Mirrors the dispatcher's incomplete-evidence block; no implementation outcome is invented."], note_refs,
    )
    return result


def build_role_cases(
    campaign_root: Path, role: str, *, governor_root: Path | None = None
) -> list[dict[str, Any]]:
    """Build P/G/Reviewer source cases; Worker/Tester are built by their runner."""
    if role == "planner":
        return _planner_cases(Path(campaign_root))
    if role == "governor":
        return _governor_cases(Path(campaign_root), governor_root)
    if role == "reviewer":
        return _reviewer_cases(Path(campaign_root))
    raise ValueError(f"Unsupported pure packet role: {role!r}")
