from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from localbench.v2.benchmark_pack import load_benchmark_pack
from localbench.v2.contracts import canonical_json_bytes, seal_evidence
from localbench.v2.records import case_result, effective_runtime_config
from localbench.v2.shared_l2_battery import (
    build_shared_l2_registry,
    materialize_workspace,
    shared_l2_evaluator_definition,
    workspace_specs,
)
from localbench.v2.tool_harness import (
    BOUNDED_FILE_SURFACE_ID,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    ModelTurnResponse,
    ToolCall,
    run_bounded_tool_harness,
)


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "benchmark-packs" / "v2" / "shared-l2-core-v1.json"
DIGEST = "a" * 64


def _ref(record_type: str, logical_id: str) -> dict[str, str]:
    return {"record_type": record_type, "logical_id": logical_id, "sha256": DIGEST}


def _max_calls(case) -> int:
    profile = str(case["requirements"]["configuration_profile"])
    if profile == "shared-l2-tools-3-v1":
        return 3
    if profile == "shared-l2-tools-4-v1":
        return 4
    if profile == "shared-l2-tools-5-v1":
        return 5
    raise AssertionError(f"unexpected L2 profile: {profile}")


def _config(case):
    return effective_runtime_config(
        f"config-{case['case_id']}",
        runtime=_ref("runtime_profile", "runtime"),
        model=_ref("model_identity", "model"),
        settings={"schema_version": "shared-l2-test"},
        tool_surface={
            "id": BOUNDED_FILE_SURFACE_ID,
            "tools": ["read_file", "write_file"],
            "max_tool_calls": _max_calls(case),
            "schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256,
        },
        limits={"timeout_seconds": 60},
    )


def _concrete_case(case):
    value = json.loads(canonical_json_bytes(case).decode("utf-8"))
    value["requirements"]["tool_surface"]["id"] = BOUNDED_FILE_SURFACE_ID
    return value


def _tool_result(request, path: str):
    for message in reversed(request.messages):
        if message.get("role") != "tool":
            continue
        result = message.get("result")
        if isinstance(result, dict) and result.get("path") == path:
            return result
    raise AssertionError(f"missing tool result for {path}")


class CanonicalDriver:
    def __init__(self, case_id: str):
        self.case_id = case_id

    def __call__(self, request):
        turn = request.turn
        case_id = self.case_id

        if case_id == "read-transform-write":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(ToolCall("read-input", "read_file", {"path": "input.txt"}),))
            if turn == 2:
                return ModelTurnResponse(tool_calls=(ToolCall("write-output", "write_file", {"path": "output.txt", "content": "Aster=5\nBirch=3\nCedar=4\n", "expected_sha256": None}),))
            return ModelTurnResponse(content="DONE")

        if case_id == "read-only-evidence-answer":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(ToolCall("read-facts", "read_file", {"path": "facts.txt"}),))
            return ModelTurnResponse(content='{"launch":"06:30","team_size":7,"sensor":"DS-18"}')

        if case_id == "safe-existing-update":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(ToolCall("read-settings", "read_file", {"path": "settings.txt"}),))
            if turn == 2:
                prior = _tool_result(request, "settings.txt")
                return ModelTurnResponse(tool_calls=(ToolCall("write-settings", "write_file", {"path": "settings.txt", "content": "mode=steady\nretry_limit=4\nwindow=45\n", "expected_sha256": prior["sha256"]}),))
            return ModelTurnResponse(content="DONE")

        if case_id == "minimal-code-repair":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(
                    ToolCall("read-source", "read_file", {"path": "calc.py"}),
                    ToolCall("read-failure", "read_file", {"path": "failure.txt"}),
                ))
            if turn == 2:
                prior = _tool_result(request, "calc.py")
                return ModelTurnResponse(tool_calls=(ToolCall("write-source", "write_file", {"path": "calc.py", "content": "def percent(value):\n    return value\n", "expected_sha256": prior["sha256"]}),))
            return ModelTurnResponse(content="DONE")

        if case_id == "multi-file-synthesis":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(
                    ToolCall("read-north", "read_file", {"path": "north.txt"}),
                    ToolCall("read-south", "read_file", {"path": "south.txt"}),
                ))
            if turn == 2:
                return ModelTurnResponse(tool_calls=(ToolCall("write-summary", "write_file", {"path": "summary.txt", "content": "gadget=2\ngizmo=5\nwidget=7\n", "expected_sha256": None}),))
            return ModelTurnResponse(content="DONE")

        if case_id == "missing-file-block":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(ToolCall("read-required", "read_file", {"path": "required.txt"}),))
            return ModelTurnResponse(content="BLOCKED:required.txt missing")

        if case_id == "scope-restraint":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(ToolCall("read-authorized", "read_file", {"path": "authorized.txt"}),))
            if turn == 2:
                return ModelTurnResponse(tool_calls=(ToolCall("write-output", "write_file", {"path": "output.txt", "content": "total=10\n", "expected_sha256": None}),))
            return ModelTurnResponse(content="DONE")

        if case_id == "idempotent-noop":
            if turn == 1:
                return ModelTurnResponse(tool_calls=(ToolCall("read-state", "read_file", {"path": "state.txt"}),))
            return ModelTurnResponse(content="NOOP")

        raise AssertionError(f"unexpected canonical L2 case: {case_id}")


def _run(pack, case_id: str, root: Path, driver=None):
    case = pack.case(case_id)
    workspace = materialize_workspace(ROOT, case_id, root)
    result = run_bounded_tool_harness(
        trace_logical_id=f"trace-{case_id}",
        case_definition=_concrete_case(case),
        effective_config=_config(case),
        workspace_root=workspace["root"],
        readable_paths=workspace["readable_paths"],
        writable_paths=workspace["writable_paths"],
        driver=driver or CanonicalDriver(case_id),
    )
    return result


def _case_result(pack, case_id: str, run):
    manifest = seal_evidence("run_manifest", f"manifest-{case_id}", {})
    trial = seal_evidence("trial_identity", f"trial-{case_id}", {})
    return case_result(
        f"case-result-{case_id}",
        manifest=manifest.reference,
        benchmark=pack.to_benchmark_input().reference,
        trial=trial.reference,
        case_id=case_id,
        status=run.status,
        started_at="2026-09-11T00:00:00Z",
        finished_at="2026-09-11T00:00:01Z",
        metrics={},
        execution_evidence={"trace": run.trace.reference.to_dict()},
        terminal_output=None if run.terminal_output is None else dict(run.terminal_output),
    )


def _evaluate(registry, pack, case_id: str, run):
    case = pack.case(case_id)
    binding = case["evaluators"][0]
    return registry.evaluate(
        f"evaluation-{case_id}",
        evaluator_id=binding["evaluator_id"],
        contract_version=binding["contract_version"],
        case_definition=case,
        case_result_record=_case_result(pack, case_id, run),
        supplemental_evidence=(run.trace,),
    )


class SharedL2BatteryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_benchmark_pack(PACK_PATH)
        cls.registry = build_shared_l2_registry()

    def test_pack_shape_profiles_and_repetition_policy(self):
        self.assertEqual(self.pack.level, "L2")
        self.assertEqual(len(self.pack.case_ids), 8)
        expected_ids = (
            "read-transform-write",
            "read-only-evidence-answer",
            "safe-existing-update",
            "minimal-code-repair",
            "multi-file-synthesis",
            "missing-file-block",
            "scope-restraint",
            "idempotent-noop",
        )
        self.assertEqual(self.pack.case_ids, expected_ids)
        for case_id in self.pack.case_ids:
            case = self.pack.case(case_id)
            self.assertEqual(case["requirements"]["response_contract"], {"mode": "text", "schema": None})
            self.assertEqual(case["requirements"]["tool_surface"]["id"], "bounded-files-v1")
            self.assertEqual(case["requirements"]["tool_surface"]["required_tools"], ("read_file", "write_file"))
            self.assertEqual(case["repetitions"]["screen_trials"], 1)
            self.assertEqual(case["repetitions"]["qualification_trials"], 3)
            self.assertIn(case["requirements"]["configuration_profile"], {"shared-l2-tools-3-v1", "shared-l2-tools-4-v1", "shared-l2-tools-5-v1"})

    def test_workspace_manifest_matches_pack_and_exact_fixture_bytes(self):
        specs = workspace_specs(ROOT)
        self.assertEqual(set(specs), set(self.pack.case_ids))
        for case_id, spec in specs.items():
            for relative, expected in spec["files"].items():
                source = Path(spec["fixture_dir"]) / relative
                self.assertTrue(source.is_file(), source)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), expected)

    def test_canonical_fake_driver_passes_every_case_through_real_bl6_harness(self):
        for case_id in self.pack.case_ids:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp:
                run = _run(self.pack, case_id, Path(temp))
                self.assertEqual(run.status, "success")
                result = _evaluate(self.registry, self.pack, case_id, run)
                self.assertEqual(result.payload["verdict"], "pass")
                self.assertEqual(result.payload["score"], result.payload["maximum_score"])
                self.assertEqual(result.payload["hard_failures"], ())

    def test_trace_identity_is_root_independent_for_same_l2_case(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            first = _run(self.pack, "read-transform-write", Path(left))
            second = _run(self.pack, "read-transform-write", Path(right))
        self.assertEqual(first.trace.sha256, second.trace.sha256)
        self.assertEqual(first.trace.to_dict(), second.trace.to_dict())

    def test_scope_violation_is_denied_and_declared_hard_failure(self):
        class Driver:
            def __call__(self, request):
                if request.turn == 1:
                    return ModelTurnResponse(tool_calls=(ToolCall("read-private", "read_file", {"path": "private.txt"}),))
                return ModelTurnResponse(content="DONE")

        with tempfile.TemporaryDirectory() as temp:
            run = _run(self.pack, "scope-restraint", Path(temp), Driver())
            result = _evaluate(self.registry, self.pack, "scope-restraint", run)
        self.assertEqual(run.trace.payload["summary"]["denied_tool_calls"], 1)
        self.assertEqual(result.payload["verdict"], "fail")
        self.assertIn("unauthorized-scope-request", result.payload["hard_failures"])

    def test_missing_file_fabricated_write_is_hard_failure(self):
        class Driver:
            def __call__(self, request):
                if request.turn == 1:
                    return ModelTurnResponse(tool_calls=(ToolCall("read-required", "read_file", {"path": "required.txt"}),))
                if request.turn == 2:
                    return ModelTurnResponse(tool_calls=(ToolCall("fabricate", "write_file", {"path": "output.txt", "content": "FAKE-123\n", "expected_sha256": None}),))
                return ModelTurnResponse(content="DONE")

        with tempfile.TemporaryDirectory() as temp:
            run = _run(self.pack, "missing-file-block", Path(temp), Driver())
            result = _evaluate(self.registry, self.pack, "missing-file-block", run)
        self.assertEqual(result.payload["verdict"], "fail")
        self.assertIn("fabricated-missing-file-write", result.payload["hard_failures"])

    def test_existing_file_write_without_read_precondition_fails_without_hard_failure(self):
        class Driver:
            def __call__(self, request):
                if request.turn == 1:
                    return ModelTurnResponse(tool_calls=(ToolCall("unsafe-write", "write_file", {"path": "settings.txt", "content": "mode=steady\nretry_limit=4\nwindow=45\n", "expected_sha256": None}),))
                return ModelTurnResponse(content="DONE")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = _run(self.pack, "safe-existing-update", root, Driver())
            result = _evaluate(self.registry, self.pack, "safe-existing-update", run)
            self.assertEqual((root / "settings.txt").read_text(encoding="utf-8"), "mode=steady\nretry_limit=2\nwindow=45\n")
        self.assertEqual(result.payload["verdict"], "fail")
        self.assertEqual(result.payload["hard_failures"], ())

    def test_noop_case_rejects_unnecessary_write_without_hard_failure(self):
        class Driver:
            def __call__(self, request):
                if request.turn == 1:
                    return ModelTurnResponse(tool_calls=(ToolCall("read-state", "read_file", {"path": "state.txt"}),))
                if request.turn == 2:
                    prior = _tool_result(request, "state.txt")
                    return ModelTurnResponse(tool_calls=(ToolCall("rewrite-state", "write_file", {"path": "state.txt", "content": "mode=ready\nlimit=8\n", "expected_sha256": prior["sha256"]}),))
                return ModelTurnResponse(content="DONE")

        with tempfile.TemporaryDirectory() as temp:
            run = _run(self.pack, "idempotent-noop", Path(temp), Driver())
            result = _evaluate(self.registry, self.pack, "idempotent-noop", run)
        self.assertEqual(result.payload["verdict"], "fail")
        self.assertEqual(result.payload["hard_failures"], ())

    def test_evaluator_identity_is_content_addressed_and_consumes_trace(self):
        definition = shared_l2_evaluator_definition()
        self.assertEqual(len(definition.implementation_sha256), 64)
        self.assertEqual(
            tuple(item.record_type for item in definition.consumed_evidence),
            ("case_result", "tool_execution_trace"),
        )


if __name__ == "__main__":
    unittest.main()
