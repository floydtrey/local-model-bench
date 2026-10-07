from __future__ import annotations

import json
import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from localbench.v2.configuration import CONFIG_SPEC_VERSION, resolve_effective_configuration
from localbench.v2.contracts import EvidenceRef, SealedEvidence, seal_evidence
from localbench.v2.execution_interface import execution_interface_identity
from localbench.v2.flashnext_role_harness import inspect_pricing_tests, run_python_check
from localbench.v2.flashnext_roles import build_role_cases, portable_role_input, run_role_campaign, run_role_case, verify_source_manifest
from localbench.v2.flashnext_role_trace import validate_role_execution_trace
from localbench.v2.orchestrator import EvidenceStore
from localbench.v2.records import host_profile, model_identity, runtime_profile
from localbench.v2.tool_harness import ModelTurnResponse, ToolCall

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns/flashnext-all-roles-v1"


def validate_schema(value, schema, document=None):
    """Dependency-free validator for the JSON Schema keywords in these two schemas.

    Unknown validation keywords fail the test, so a schema extension cannot be
    silently ignored. Production validation additionally checks sealed/event hashes.
    """
    document = schema if document is None else document
    known = {"$schema", "$id", "$defs", "title", "description", "$ref", "type", "required", "properties", "additionalProperties", "const", "enum", "pattern", "items", "uniqueItems", "minimum", "minLength", "allOf", "anyOf", "oneOf"}
    assert not set(schema) - known, f"unsupported schema keywords: {set(schema) - known}"
    if "$ref" in schema:
        assert schema["$ref"].startswith("#/"), "only local schema refs expected"
        referred = document
        for piece in schema["$ref"][2:].split("/"):
            referred = referred[piece]
        validate_schema(value, referred, document)
    for item in schema.get("allOf", []):
        validate_schema(value, item, document)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            matches = 0
            for choice in schema[keyword]:
                try:
                    validate_schema(value, choice, document)
                except AssertionError:
                    continue
                matches += 1
            assert matches >= 1 if keyword == "anyOf" else matches == 1
    kinds = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list), "string": lambda: isinstance(value, str), "integer": lambda: isinstance(value, int) and not isinstance(value, bool), "null": lambda: value is None, "boolean": lambda: isinstance(value, bool)}
    if "type" in schema:
        options = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        assert any(kinds[x]() for x in options), f"wrong type: expected {options}"
    if "const" in schema:
        assert value == schema["const"]
    if "enum" in schema:
        assert value in schema["enum"]
    if "pattern" in schema:
        assert re.search(schema["pattern"], value)
    if "minimum" in schema:
        assert value >= schema["minimum"]
    if "minLength" in schema:
        assert len(value) >= schema["minLength"]
    if isinstance(value, dict):
        assert set(schema.get("required", [])) <= set(value)
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], document)
            elif schema.get("additionalProperties") is False:
                raise AssertionError(f"unexpected property: {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_schema(item, schema["additionalProperties"], document)
    if isinstance(value, list):
        if schema.get("uniqueItems"):
            assert len(value) == len({json.dumps(x, sort_keys=True) for x in value})
        if "items" in schema:
            for item in value:
                validate_schema(item, schema["items"], document)


def foundation():
    runtime = runtime_profile("test-runtime", runtime_kind="llama.cpp", version="test", build=None, transport={}, executable=None, installation_digest=None, capabilities={})
    model = model_identity("test-model", family="test", name="C01", source={}, artifact_digest=None, provider_digest=None, parameter_count=None, quantization=None, precision=None, declared_context_tokens=262144)
    interface = execution_interface_identity("test-interface", runtime=runtime.reference, model=model.reference, backend_kind="llama.cpp", adapter_id="test", tool_transport_mode="native_structured", parser_mode="provider_native", parser_id="test", raw_interaction_contract="test:v1", capabilities={})
    host = host_profile("test-host", captured_at="2026-10-07T00:00:00Z", os_info={}, cpu={}, memory={}, gpus=[], storage=[], python={}, compute_runtimes=[])
    return {"host": host, "runtime": runtime, "model": model, "interface": interface}


def spec():
    return {
        "schema_version": CONFIG_SPEC_VERSION, "comparison_mode": "strict",
        "generation": {"context_tokens": 262144, "max_output_tokens": 8192, "temperature": 0, "seed": 42, "top_p": 1, "top_k": None, "repeat_penalty": None, "stop": [], "response_format": {"mode": "text", "schema": None}, "reasoning": {"mode": "enabled", "effort": None}},
        "execution": {"timeout_seconds": 600, "retries": 0, "retry_delay_seconds": 0, "concurrency": 1, "model_residency": {"mode": "unload_after_model", "keep_alive_seconds": 0}, "network_policy": "provider_only"},
        "tool_surface": {"id": "none", "tools": [], "max_tool_calls": 0, "schema_sha256": None},
    }


class Factory:
    def __init__(self, base, handler, store):
        self.base, self.handler, self.store = base, handler, store
        self.requests = []
        self.configs = []

    def __call__(self, config, evidence_dir):
        parent = self
        effective = resolve_effective_configuration(
            f"test-config-{len(self.configs)}", runtime=self.base["runtime"], model=self.base["model"], spec=config,
            adapter_resolution={"adapter_id": "test", "status": "exact", "effective_request": {}, "deviations": []},
        )
        self.configs.append(effective)

        class Driver:
            effective_config = effective

            def __call__(self, request):
                if not list((parent.store.root / "records/run_manifest").glob("*.json")):
                    raise AssertionError("manifest was not persisted before inference")
                parent.requests.append(request)
                return parent.handler(request)

        return Driver()


def tool(call_id, name, arguments):
    return ModelTurnResponse(tool_calls=(ToolCall(call_id, name, arguments),))


def title_worker(request):
    if request.turn == 1:
        return ModelTurnResponse(content="WORKER_READY")
    if request.turn == 2:
        return tool("read", "read_file", {"path": "reporting/config.py"})
    if request.turn == 3:
        read = request.messages[-1]["result"]
        source = read["content"].replace("class ReportConfig:\n", "class ReportConfig:\n    title: str = \"Report\"\n")
        return tool("write", "write_file", {"path": "reporting/config.py", "content": source, "expected_sha256": read["sha256"]})
    return ModelTurnResponse(content="Task 1 complete.\nHandoff note: Added ReportConfig.title default Report; rendering remains for Task 2.")


class FlashNextRolesTests(unittest.TestCase):
    def _run(self, temporary, role, index, handler):
        path = Path(temporary)
        base = foundation()
        store = EvidenceStore(path / "evidence")
        factory = Factory(base, handler, store)
        result = run_role_case(build_role_cases(CAMPAIGN, role)[index], foundation=base, base_config_spec=spec(), driver_factory=factory, evidence_store=store, output_dir=path / "case", ordinal=1)
        return result, factory, store

    def test_verbatim_corpus_and_representative_case_counts(self):
        self.assertEqual(len(verify_source_manifest(CAMPAIGN / "sources/local-model-bench")), 62)
        self.assertEqual(len(build_role_cases(CAMPAIGN, "worker")), 4)
        tester = build_role_cases(CAMPAIGN, "tester")
        self.assertEqual([x["expected_decision"] for x in tester], ["PASS", "FAIL", "PASS"])
        self.assertTrue(all(x["setup_expected_marker"] == "TESTER_READY" for x in tester))

    def test_two_turn_text_role_preserves_history_and_never_auto_qualifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, factory, store = self._run(temporary, "planner", 1, lambda request: ModelTurnResponse(content="Ready" if request.turn == 1 else "AMBIGUOUS\nTransient failure classification is missing."))
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["correctness"], "human-review-pending")
            self.assertIsNone(result["deterministic_passed"])
            self.assertEqual([x["role"] for x in factory.requests[1].messages], ["user", "assistant", "user"])
            self.assertEqual(factory.requests[1].messages[1]["content"], "Ready")
            self.assertTrue(all(not r.tools for r in factory.requests))
            self.assertEqual(len(list((store.root / "records/run_manifest").glob("*.json"))), 1)

    def test_worker_executes_real_fixture_checks_and_binds_tool_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, factory, store = self._run(temporary, "worker", 0, title_worker)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["deterministic_passed"])
            self.assertTrue(result["accepted_handoff"])
            self.assertEqual(factory.configs[0].payload["tool_surface"]["tools"], ())
            self.assertEqual(factory.configs[1].payload["tool_surface"]["tools"], ("read_file", "write_file", "run_tests"))
            self.assertFalse(factory.requests[0].tools)
            self.assertEqual(len(factory.requests[1].tools), 3)
            self.assertTrue((Path(temporary) / "case/events.jsonl").is_file())
            self.assertTrue((Path(temporary) / "case/assessment/first-pass-behavior.stdout.txt").read_text().startswith("CONFIG_BEHAVIOR_PASS"))
            self.assertEqual((Path(result["workspace"]) / "tests/test_render.py").read_bytes(), (CAMPAIGN / "sources/local-model-bench/benchmark/worker/fixture-01/tests/test_render.py").read_bytes())

    def test_tester_c_exposes_real_defect_and_oracle_rejects_unrelated_failure(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temporary:
                code = "import unittest\nfrom pricing.discount import apply_discount\n\nclass Added(unittest.TestCase):\n    def test_vip(self):\n        self.assertEqual(" + ("apply_discount(100, vip=True), 90" if valid else "1, 2") + ")\n"

                def handler(request):
                    if request.turn == 1:
                        return ModelTurnResponse(content="TESTER_READY")
                    if request.turn == 2:
                        return tool("write", "write_file", {"path": "tests/test_qualification.py", "content": code, "expected_sha256": None})
                    if request.turn == 3:
                        return tool("tests", "run_tests", {})
                    return ModelTurnResponse(content="My decision is FAIL. The focused test fails. VIP totals need the required 10 percent discount; production code was not changed.")

                result, _, _ = self._run(temporary, "tester", 1, handler)
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["deterministic_passed"], valid)
                self.assertTrue(result["human_review_required"])
                assessment = json.loads((Path(temporary) / "case/assessment/first-pass-assessment.json").read_text())
                self.assertEqual(assessment["oracle_validation"]["correct"]["exit_code"], 0 if valid else 1)
                self.assertEqual(assessment["observed_decision"], "FAIL")

    def test_schema_literal_normalization_repairs_string_null_without_hiding_raw_call(self):
        code = "import unittest\nfrom pricing.discount import apply_discount\n\nclass Added(unittest.TestCase):\n    def test_vip(self):\n        self.assertEqual(apply_discount(100, vip=True), 90)\n"

        def handler(request):
            if request.turn == 1:
                return ModelTurnResponse(content="TESTER_READY")
            if request.turn == 2:
                return tool("write-null-string", "write_file", {
                    "path": "tests/test_qualification.py",
                    "content": code,
                    "expected_sha256": "null",
                })
            if request.turn == 3:
                return tool("tests", "run_tests", {})
            return ModelTurnResponse(content="My decision is FAIL. The focused test exposes the VIP discount defect.")

        with tempfile.TemporaryDirectory() as temporary:
            result, _, store = self._run(temporary, "tester", 1, handler)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["deterministic_passed"])
            self.assertEqual(result["metrics"]["schema_normalizations"], 1)
            self.assertEqual(result["metrics"]["validation_failures"], 0)
            trace = store.load(EvidenceRef.from_dict(result["records"]["trace"]))
            events = [event for event in trace.payload["events"] if event["event_type"] == "tool_argument_normalization"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["payload"]["original_call"]["arguments"]["expected_sha256"], "null")
            self.assertIsNone(events[0]["payload"]["normalized_call"]["arguments"]["expected_sha256"])

    def test_invalid_tool_arguments_get_exactly_two_model_retries_then_stop(self):
        def handler(request):
            if request.turn == 1:
                return ModelTurnResponse(content="TESTER_READY")
            return tool(f"bad-{request.turn}", "run_tests", {"command": "forbidden"})

        with tempfile.TemporaryDirectory() as temporary:
            result, factory, store = self._run(temporary, "tester", 0, handler)
            self.assertEqual(result["status"], "resource_limit")
            self.assertEqual(result["stop_reason"], "tool_validation_retry_limit")
            self.assertEqual(result["metrics"]["validation_failures"], 3)
            self.assertEqual(result["metrics"]["validation_retry_turns"], 2)
            self.assertEqual(result["metrics"]["max_validation_retries"], 2)
            self.assertGreaterEqual(result["metrics"]["repetition_detections"], 2)
            dispatched = [request for request in factory.requests if request.turn > 1]
            self.assertEqual(len(dispatched), 3)
            trace = store.load(EvidenceRef.from_dict(result["records"]["trace"]))
            self.assertTrue(any(event["event_type"] == "limit_reached"
                                and event["payload"].get("limit") == "validation_retries"
                                for event in trace.payload["events"]))

    def test_model_cannot_supply_a_shell_command_to_fixed_test_tool(self):
        def handler(request):
            if request.turn == 1:
                return ModelTurnResponse(content="TESTER_READY")
            if request.turn == 2:
                return tool("bad", "run_tests", {"command": "do something else"})
            return ModelTurnResponse(content="BLOCKED\nTool arguments were denied.")

        with tempfile.TemporaryDirectory() as temporary:
            result, _, _ = self._run(temporary, "tester", 0, handler)
            self.assertEqual(result["metrics"]["denied_tool_calls"], 1)
            self.assertEqual(result["metrics"]["test_tool_calls"], 0)
            self.assertFalse(result["deterministic_passed"])

    def test_tester_host_import_is_inspected_before_any_process_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            shutil.copytree(CAMPAIGN / "sources/local-model-bench/benchmark/tester/fixtures/case-a", workspace)
            (workspace / "tests/test_qualification.py").write_text("import os\nos.system('unexpected')\n")
            inspection = inspect_pricing_tests(workspace)
            self.assertFalse(inspection["allowed"])
            result = run_python_check(workspace, root / "evidence", "inspection", inspect_tester_tests=True)
            self.assertIsNone(result["exit_code"])
            self.assertIn("controlled_test_source_policy", result["infrastructure_error"]["detail"])

    def test_request_timeout_is_bounded_model_resource_limit_not_protocol_failure(self):
        class RequestTimeout(RuntimeError):
            category = "timeout"
            provider_metadata = {"prompt_tokens": 7, "output_tokens": 0}

        def handler(request):
            if request.turn == 1:
                return ModelTurnResponse(content="WORKER_READY")
            raise RequestTimeout("total request deadline exceeded")

        with tempfile.TemporaryDirectory() as temporary:
            result, _, _ = self._run(temporary, "worker", 0, handler)
            self.assertEqual(result["status"], "resource_limit")
            self.assertEqual(result["stop_reason"], "timeout")
            self.assertEqual(result["runtime_compatibility"], "compatible")
            self.assertIsNone(result["deterministic_passed"])
            self.assertIn("not-assessed", result["correctness"])

    def test_parser_error_remains_unassessed_and_preserves_failure_metrics(self):
        class ParserError(RuntimeError):
            category = "tool_transport_incompatible"
            provider_metadata = {"prompt_tokens": 7, "output_tokens": 11, "generation_seconds": 0.5, "timings": {"predicted_n": 10}}

        def handler(request):
            raise ParserError("malformed native tool arguments")

        with tempfile.TemporaryDirectory() as temporary:
            result, _, _ = self._run(temporary, "worker", 0, handler)
            self.assertEqual(result["runtime_compatibility"], "unresolved")
            self.assertIsNone(result["deterministic_passed"])
            self.assertEqual(result["metrics"]["output_tokens"], 11)
            self.assertEqual(result["metrics"]["generation_tokens_per_second"], 20)
            self.assertEqual(result["metrics"]["generation_tokens"], 10)
            self.assertIn("not-assessed", result["correctness"])

    def test_worker_repair_reuses_session_and_failed_predecessor_blocks_later_tasks(self):
        def handler(request):
            if request.case_id == "worker-title-task-01":
                return title_worker(request)
            return ModelTurnResponse(content="WORKER_READY" if request.turn == 1 else "Handoff note: Unable to implement the task.")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = foundation()
            store = EvidenceStore(root / "evidence")
            factory = Factory(base, handler, store)
            summary = run_role_campaign(campaign_root=CAMPAIGN, roles=["worker"], repetitions=1, foundation=base, base_config_spec=spec(), driver_factory=factory, evidence_store=store, output_dir=root / "campaign")
            results = summary["results"]
            self.assertEqual(len(results), 4)
            self.assertTrue(results[1]["repair_attempted"])
            self.assertFalse(results[1]["deterministic_passed"])
            self.assertEqual([x["stop_reason"] for x in results[2:]], ["predecessor_not_accepted"] * 2)
            dispatched = [r for r in factory.requests if r.case_id == "worker-intent04-task-01"]
            self.assertEqual([r.turn for r in dispatched], [1, 2, 3])
            self.assertEqual([m["role"] for m in dispatched[-1].messages], ["user", "assistant", "user", "assistant", "user"])
            self.assertFalse(any(r.case_id.endswith("task-02") or r.case_id.endswith("task-03") for r in factory.requests))

    def test_three_repetition_text_campaign_uses_fresh_histories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = foundation()
            store = EvidenceStore(root / "evidence")
            factory = Factory(base, lambda request: ModelTurnResponse(content="Observed text"), store)
            summary = run_role_campaign(campaign_root=CAMPAIGN, roles=["planner"], repetitions=3, foundation=base, base_config_spec=spec(), driver_factory=factory, evidence_store=store, output_dir=root / "campaign")
            self.assertEqual(len(summary["results"]), 18)
            self.assertEqual(len(factory.requests), 36)
            self.assertTrue(all(len(r.messages) == 1 for r in factory.requests if r.turn == 1))
            self.assertEqual(summary["qualification_status"], "human-review-pending")

    def test_test_source_policy_rejects_assertion_rebinding_and_overrides(self):
        attacks = [
            "    def test_attack(self):\n        self.assertEqual = unittest.loader.os.system\n        self.assertEqual('bad')\n",
            "    def assertEqual(self, a, b):\n        pass\n    def test_vip(self):\n        self.assertEqual(1, 2)\n",
            "    def test_attack(self):\n        command = unittest.loader.os.system\n        self.assertEqual(command, 1)\n",
            "    def test_attack(self):\n        self = 1\n        self.assertEqual(1, 2)\n",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tests").mkdir()
            for attack in attacks:
                (root / "tests/test_attack.py").write_text("import unittest\nclass Attack(unittest.TestCase):\n" + attack)
                self.assertFalse(inspect_pricing_tests(root)["allowed"])
            (root / "tests/test_attack.py").write_text("import unittest\nfrom pricing.discount import apply_discount\nclass Ordinary(unittest.TestCase):\n    def test_vip(self):\n        cases = [(100, 90), (10, 9)]\n        for amount, expected in cases:\n            with self.subTest(amount=amount):\n                self.assertEqual(apply_discount(amount, vip=True), expected)\n")
            self.assertTrue(inspect_pricing_tests(root)["allowed"])

    def test_new_role_trace_roundtrip_schema_and_binding_preserve_v2_contracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, _, store = self._run(temporary, "worker", 0, title_worker)
            trace = store.load(EvidenceRef.from_dict(result["records"]["trace"]))
            self.assertEqual(trace.record_type, "role_execution_trace")
            restored = SealedEvidence.from_dict(json.loads(json.dumps(trace.to_dict())))
            validate_role_execution_trace(restored)
            schema = json.loads((ROOT / "schemas/v2/role-execution-trace.schema.json").read_text())
            validate_schema(restored.to_dict()["payload"], schema)
            changed = restored.to_dict()["payload"]
            changed["events"][0]["payload"]["unexpected"] = True
            with self.assertRaisesRegex(ValueError, "event digest"):
                validate_role_execution_trace(seal_evidence("role_execution_trace", "changed-trace", changed))
            binding_paths = list((store.root / "records/execution_binding").glob("*.json"))
            binding = json.loads(binding_paths[0].read_text())["payload"]
            validate_schema(binding, json.loads((ROOT / "schemas/v2/execution-binding.schema.json").read_text()))
            self.assertEqual(binding["context_assets"], [])
            self.assertIsNone(binding["containment"])
            manifest = json.loads((Path(temporary) / "case/manifest.json").read_text())["payload"]
            protocol = manifest["harness_source"]["role_protocol"]
            self.assertEqual(protocol["dispatch_prompt_sha256"], hashlib.sha256((Path(temporary) / "case/dispatch.txt").read_bytes()).hexdigest())
            evaluation = store.load(EvidenceRef.from_dict(result["records"]["evaluation"]))
            self.assertTrue(all(set(x) == {"id", "passed", "weight", "earned", "detail", "evidence"} for x in evaluation.payload["checks"]))

    def test_role_input_identity_does_not_depend_on_machine_source_locations(self):
        case = build_role_cases(CAMPAIGN, "worker")[1]
        portable = portable_role_input(case)
        relocated = json.loads(json.dumps(case))
        for key in ("fixture_path", "verifier_path", "criteria_path"):
            relocated[key] = "C:/Different/Checkout/" + portable[key]
        for item in relocated["source_refs"]:
            item["local_path"] = "C:/Another/Checkout/" + item["source_path"]
        self.assertEqual(portable_role_input(relocated), portable)
        self.assertNotIn("local_path", json.dumps(portable))


if __name__ == "__main__":
    unittest.main()
