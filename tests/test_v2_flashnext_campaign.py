"""Synthetic HTTP integration of the campaign through unchanged V2 batteries.

No model/server executable is started. Canonical expected responses are reused
from the accepted battery engineering tests; their evaluators still judge every
result. These tests establish wiring and evidence behavior, not model ability.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from localbench.v2 import flashnext_campaign as campaign
from localbench.v2.contracts import SealedEvidence, canonical_json_bytes, sha256_json
from localbench.v2.execution_interface import execution_interface_identity
from localbench.v2.flashnext_runtime import FlashNextBlocked
from localbench.v2.llama_cpp_driver import LLAMA_CPP_ADAPTER_ID
from localbench.v2.orchestrator import EvidenceStore, OrchestrationBlocked
from localbench.v2.records import host_profile, model_identity, runtime_profile
from localbench.v2.tool_harness import ModelTurnRequest, ModelTurnResponse

from test_v2_shared_battery import PERFECT_L0, PERFECT_L1
from test_v2_shared_l2_battery import CanonicalDriver


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = ROOT / "campaigns" / "flashnext-all-roles-v1"


def _profile():
    profile = json.loads((CAMPAIGN_ROOT / "runtime-profile.json").read_bytes())
    profile["limits"]["case_seconds"] = 5
    return profile


def _foundation(base_url: str, output_dir: Path):
    host = host_profile(
        "flashnext-host-capture-1", captured_at="2026-10-07T00:00:00Z",
        os_info={"name": "synthetic-fixture", "build": "1"},
        cpu={"model": "synthetic-cpu", "physical_cores": 2, "logical_cores": 4},
        memory={"installed_bytes": 64_000_000_000, "available_bytes": None},
        gpus=[], storage=[], python={"version": "3.12", "implementation": "CPython"},
        compute_runtimes=[], power_thermal=None,
    )
    host2 = host_profile(
        "flashnext-host-capture-2", captured_at="2026-10-07T00:00:01Z",
        os_info={"name": "synthetic-fixture", "build": "1"},
        cpu={"model": "synthetic-cpu", "physical_cores": 2, "logical_cores": 4},
        memory={"installed_bytes": 64_000_000_000, "available_bytes": None},
        gpus=[], storage=[], python={"version": "3.12", "implementation": "CPython"},
        compute_runtimes=[], power_thermal=None,
    )
    runtime = runtime_profile(
        "fixture-llama-runtime", runtime_kind="llama_cpp", version="synthetic-test-only", build=None,
        transport={"kind": "loopback_http", "base_uri": base_url, "context_tokens": 262144,
                   "model_alias": "C01", "reasoning_mode": "auto"},
        executable=None, installation_digest="b" * 64, capabilities={"synthetic_test_fixture": True},
    )
    model = model_identity(
        "fixture-model", family="synthetic-test-only", name="synthetic-test-only",
        source={"kind": "engineering_fixture"}, artifact_digest="c" * 64, provider_digest=None,
        parameter_count=None, quantization=None, precision=None, declared_context_tokens=262144,
    )
    interface = execution_interface_identity(
        "fixture-llama-interface", runtime=runtime.reference, model=model.reference,
        backend_kind="llama_cpp", adapter_id=LLAMA_CPP_ADAPTER_ID,
        tool_transport_mode="model_aware_structured", parser_mode="model_aware",
        parser_id="fixture-openai-native", raw_interaction_contract="llama-cpp-raw-http-sidecars:v1",
        capabilities={"synthetic_test_fixture": True, "plain_text_tool_fallback": False},
    )
    store = EvidenceStore(output_dir / "evidence")
    store.persist_many((host, host2, runtime, model, interface))
    return {"host": host, "runtime": runtime, "model": model, "interface": interface, "store": store,
            "fingerprint": {"synthetic_fixture": True, "implementation_sha256": "d" * 64,
                            "host_facts_sha256": host.payload["facts_sha256"], "runtime_sha256": runtime.sha256,
                            "model_sha256": model.sha256, "execution_interface_sha256": interface.sha256}}


class _FixtureEndpoint:
    """Supply accepted synthetic outputs through the real llama.cpp HTTP driver."""

    def __init__(self, *, parser_failure=None, incorrect_case=None, prose_tools=False, static_response=None):
        self.requests = []
        by_user = {}
        for level in ("L0", "L1", "L2"):
            pack = json.loads((ROOT / f"benchmark-packs/v2/shared-{level.lower()}-core-v1.json").read_bytes())
            for case in pack["cases"]:
                first_user = next(m["content"] for m in case["input"]["messages"] if m["role"] == "user")
                if first_user in by_user:
                    raise AssertionError("fixture cannot unambiguously match the accepted user messages")
                by_user[first_user] = (level, case["case_id"])
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received = self.rfile.read(int(self.headers["Content-Length"]))
                wire = json.loads(received)
                first_user = next(m["content"] for m in wire["messages"] if m["role"] == "user")
                level, case_id = by_user[first_user] if static_response is None else ("role", "synthetic-role")
                turn = 1 + sum(bool(m.get("tool_calls")) for m in wire["messages"] if m["role"] == "assistant")
                if static_response is not None:
                    response = ModelTurnResponse(content=static_response)
                elif level == "L0":
                    content = "B,D" if case_id == "output-discipline" else json.dumps(PERFECT_L0[case_id])
                    response = ModelTurnResponse(content=content)
                elif level == "L1":
                    response = ModelTurnResponse(content=json.dumps(PERFECT_L1[case_id]))
                else:
                    history = []
                    for msg in wire["messages"]:
                        if msg["role"] == "tool":
                            history.append({"role": "tool", "tool_call_id": msg["tool_call_id"],
                                            "result": json.loads(msg["content"])})
                        else:
                            history.append({"role": msg["role"], "content": msg["content"]})
                    request = ModelTurnRequest(case_id=case_id, turn=turn, messages=tuple(history), context_assets=(), tools=())
                    response = CanonicalDriver(case_id)(request)
                if incorrect_case == case_id:
                    response = ModelTurnResponse(content="INCORRECT_SYNTHETIC_RESPONSE")
                if prose_tools and level == "L2":
                    response = ModelTurnResponse(content='{"name":"read_file","arguments":{"path":"input.txt"}}')
                message = {"role": "assistant", "content": response.content}
                if response.tool_calls:
                    message["tool_calls"] = [{"id": call.call_id, "type": "function", "function": {
                        "name": call.name, "arguments": canonical_json_bytes(call.arguments).decode("utf-8")}}
                        for call in response.tool_calls]
                if parser_failure == case_id:
                    message["tool_calls"] = [{"id": "malformed-native-call", "type": "function",
                                              "function": {"name": "read_file", "arguments": '{"path":'}}]
                result = {"id": f"fixture-{case_id}-{turn}", "model": "C01",
                          "choices": [{"index": 0, "message": message,
                                       "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                          "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26},
                          "timings": {"prompt_n": 17, "cache_n": 0, "prompt_ms": 20,
                                      "predicted_n": 9, "predicted_ms": 90, "predicted_per_second": 100}}
                body = canonical_json_bytes(result)
                outer.requests.append({"case_id": case_id, "turn": turn, "request_body": received,
                                       "response_body": body, "wire": wire})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        return self, f"http://{host}:{port}"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _run(output_dir, *, stage="smoke", server=None, **endpoint_options):
    with _FixtureEndpoint(**endpoint_options) as (endpoint, url):
        foundation = _foundation(url, output_dir)
        result = campaign.run_shared(repo_root=ROOT, output_dir=output_dir, foundation=foundation,
                                     profile=_profile(), server=server, stage=stage, progress=lambda msg: None)
    return result, foundation, endpoint.requests


def _run_chain(root: Path):
    """A smoke and shared screen with the same endpoint and sealed foundation."""
    with _FixtureEndpoint() as (endpoint, url):
        smoke_dir = root / "smoke"
        smoke_foundation = _foundation(url, smoke_dir)
        smoke_result = campaign.run_shared(repo_root=ROOT, output_dir=smoke_dir, foundation=smoke_foundation,
                                          profile=_profile(), server=None, stage="smoke", progress=lambda msg: None)
        smoke_gate = campaign.create_gate(output_dir=smoke_dir, stage="smoke", foundation=smoke_foundation, result=smoke_result)
        shared_dir = root / "shared"
        shared_foundation = _foundation(url, shared_dir)
        shared_result = campaign.run_shared(repo_root=ROOT, output_dir=shared_dir, foundation=shared_foundation,
                                           profile=_profile(), server=None, stage="shared-screen", progress=lambda msg: None)
        shared_gate = campaign.create_gate(output_dir=shared_dir, stage="shared-screen", foundation=shared_foundation,
                                           result=shared_result, parent_gate=smoke_gate, parent_smoke_run=smoke_dir)
    return {"smoke_dir": smoke_dir, "smoke_result": smoke_result, "smoke_gate": smoke_gate,
            "shared_dir": shared_dir, "shared_result": shared_result, "shared_gate": shared_gate,
            "foundation": shared_foundation, "requests": endpoint.requests}


def _rewrite_gate(path: Path, mutate):
    value = json.loads(path.read_bytes())
    mutate(value["payload"])
    value["sha256"] = sha256_json(value["payload"])
    path.write_bytes(canonical_json_bytes(value))


class _SyntheticResidentServer:
    """Observe residency labels without starting an actual model process."""

    model_request_count = 0

    def watchdog(self, seconds):
        # The real HTTP driver supplies a finite deadline. This unit fixture's
        # outer watchdog has no runtime process to terminate and is never started.
        return threading.Timer(seconds, lambda: None)


class FlashNextCampaignSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "smoke"
        cls.result, cls.foundation, cls.requests = _run(cls.output)
        cls.gate = campaign.create_gate(output_dir=cls.output, stage="smoke", foundation=cls.foundation, result=cls.result)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_three_case_smoke_uses_actual_driver_evaluators_tools_and_evidence(self):
        result = self.result
        self.assertEqual(result["completed_observations"], 3)
        self.assertTrue(result["all_correct"])
        self.assertTrue(result["native_tool_smoke_pass"])
        self.assertFalse(result["role_qualified"])
        self.assertEqual([r["case_id"] for r in result["rows"]],
                         ["structured-transformation", "evidence-traceability", "read-transform-write"])
        self.assertEqual(len(self.requests), 5)
        self.assertEqual((self.output / "l2/workspaces/read-transform-write-01/output.txt").read_bytes(),
                         b"Aster=5\nBirch=3\nCedar=4\n")
        for row in result["rows"]:
            self.assertEqual(row["correctness"], "pass")
            self.assertEqual(row["runtime_compatibility"], "pass")
            self.assertEqual(row["execution_status"], "success")
            self.assertEqual(row["generation_tokens_per_second"], 100)
            self.assertGreater(row["wall_seconds"], 0)
        l2 = result["rows"][2]
        self.assertEqual(l2["model_turns"], 3)
        self.assertEqual(l2["tool_calls"], 2)
        self.assertEqual(l2["output_tokens"], 27)
        self.assertEqual(l2["generation_seconds"], .27)
        self.assertTrue(l2["resource_summary"])
        for reference in result["evidence"]:
            record = SealedEvidence.from_dict(json.loads((self.output / reference["path"]).read_bytes()))
            self.assertEqual(record.reference.to_dict(), reference["reference"])
        record_types = {r["reference"]["record_type"] for r in result["evidence"]}
        self.assertTrue({"case_result", "evaluation_result", "trial_identity", "tool_execution_trace",
                         "tool_compatibility_observation", "resource_telemetry_trace", "effective_runtime_config"}.issubset(record_types))

    def test_passing_gate_verifies_and_binds_every_received_http_body(self):
        gate = campaign.verify_gate(self.output, stage="smoke", fingerprint=self.foundation["fingerprint"])
        self.assertEqual(gate["status"], "pass")
        self.assertFalse(gate["role_or_model_qualified"])
        response_refs = [a for a in gate["artifact_files"] if a["path"].endswith("response.body")]
        request_refs = [a for a in gate["artifact_files"] if a["path"].endswith("request.body")]
        self.assertEqual(len(response_refs), 5)
        self.assertEqual(len(request_refs), 5)
        self.assertEqual({a["sha256"] for a in response_refs},
                         {hashlib.sha256(r["response_body"]).hexdigest() for r in self.requests})
        for item in gate["artifact_files"]:
            content = (self.output / item["path"]).read_bytes()
            self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())

    def test_gate_rejects_wrong_fingerprint_stage_and_changed_gate_digest(self):
        with self.assertRaises(FlashNextBlocked):
            campaign.verify_gate(self.output, stage="smoke", fingerprint={**self.foundation["fingerprint"], "model_sha256": "f" * 64})
        with self.assertRaises(FlashNextBlocked):
            campaign.verify_gate(self.output, stage="shared-screen", fingerprint=self.foundation["fingerprint"])
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy"
            shutil.copytree(self.output, copy)
            value = json.loads((copy / "gate.json").read_bytes())
            value["payload"]["completed_observations"] = 99
            (copy / "gate.json").write_bytes(canonical_json_bytes(value))
            with self.assertRaises(FlashNextBlocked):
                campaign.verify_gate(copy, stage="smoke", fingerprint=self.foundation["fingerprint"])

    def test_gate_rejects_missing_or_changed_runtime_response_artifact(self):
        artifact = next(a for a in self.gate["artifact_files"] if a["path"].endswith("response.body"))
        for action in ("delete", "change"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "copy"
                shutil.copytree(self.output, copy)
                path = copy / artifact["path"]
                if action == "delete":
                    path.unlink()
                else:
                    path.write_bytes(path.read_bytes() + b"changed")
                with self.assertRaises(FlashNextBlocked):
                    campaign.verify_gate(copy, stage="smoke", fingerprint=self.foundation["fingerprint"])

    def test_gate_rejects_incomplete_observations_and_evaluation_evidence(self):
        mutations = [lambda gate: gate.update(completed_observations=2),
                     lambda gate: gate.update(evidence=[r for r in gate["evidence"] if r["reference"]["record_type"] != "evaluation_result"])]
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "copy"
                shutil.copytree(self.output, copy)
                _rewrite_gate(copy / "gate.json", mutate)
                with self.assertRaises(FlashNextBlocked):
                    campaign.verify_gate(copy, stage="smoke", fingerprint=self.foundation["fingerprint"])

    def test_gate_rejects_repeated_evaluation_reference_replacing_an_unchecked_case(self):
        def duplicate_evaluation(gate):
            evaluations = [r for r in gate["evidence"] if r["reference"]["record_type"] == "evaluation_result"]
            replaced = evaluations[-1]
            gate["evidence"] = [evaluations[0] if r == replaced else r for r in gate["evidence"]]
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy"
            shutil.copytree(self.output, copy)
            _rewrite_gate(copy / "gate.json", duplicate_evaluation)
            with self.assertRaises(FlashNextBlocked):
                campaign.verify_gate(copy, stage="smoke", fingerprint=self.foundation["fingerprint"])


class FlashNextCampaignFailureTests(unittest.TestCase):
    def test_tool_parser_failure_preserves_raw_and_stops_before_evaluation_or_gate(self):
        with tempfile.TemporaryDirectory() as tmp, _FixtureEndpoint(parser_failure="read-transform-write") as (endpoint, url):
            output = Path(tmp)
            foundation = _foundation(url, output)
            with self.assertRaises(OrchestrationBlocked):
                campaign.run_shared(repo_root=ROOT, output_dir=output, foundation=foundation,
                                    profile=_profile(), server=None, stage="smoke", progress=lambda msg: None)
            self.assertFalse((output / "gate.json").exists())
            measured = campaign.load_derived(output / "l2/measurements.json", "flashnext-measurements:v1")
            self.assertFalse(measured["complete"])
            row = measured["rows"][0]
            self.assertEqual(row["runtime_errors"], ["tool_transport_incompatible"])
            self.assertEqual(row["runtime_compatibility"], "fail")
            self.assertEqual(row["correctness"], "not_scored")
            self.assertEqual(len(endpoint.requests), 3)
            raw = next((output / "l2/observations").rglob("response.body"))
            self.assertEqual(raw.read_bytes(), endpoint.requests[-1]["response_body"])
            case_paths = list((output / "l2/evidence/records/case_result").glob("*.json"))
            self.assertEqual(len(case_paths), 1)
            case = SealedEvidence.from_dict(json.loads(case_paths[0].read_bytes()))
            self.assertEqual(case.payload["status"], "error")
            self.assertEqual(list((output / "l2/evidence/records/evaluation_result").glob("*.json")), [])

    def test_correctness_failure_is_separate_from_runtime_and_does_not_block_smoke_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            result, foundation, requests = _run(output, incorrect_case="structured-transformation")
            self.assertEqual(len(requests), 5)
            self.assertEqual(result["rows"][0]["correctness"], "fail")
            self.assertEqual(result["rows"][0]["runtime_compatibility"], "pass")
            gate = campaign.create_gate(output_dir=output, stage="smoke", foundation=foundation, result=result)
            self.assertEqual(gate["status"], "pass")
            verified = campaign.verify_gate(output, stage="smoke", fingerprint=foundation["fingerprint"])
            self.assertFalse(verified["correctness_all_pass"])

    def test_tool_shaped_prose_never_executes_and_cannot_unlock_native_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            result, foundation, requests = _run(output, prose_tools=True)
            self.assertEqual(len(requests), 3)
            self.assertFalse((output / "l2/workspaces/read-transform-write-01/output.txt").exists())
            self.assertFalse(result["native_tool_smoke_pass"])
            row = result["rows"][-1]
            self.assertEqual(row["tool_calls"], 0)
            self.assertEqual(row["runtime_compatibility"], "pass")
            self.assertEqual(row["correctness"], "fail")
            self.assertEqual(row["raw_observations"][0]["tool_text_diagnostic"], "potential_tool_shaped_prose")
            gate = campaign.create_gate(output_dir=output, stage="smoke", foundation=foundation, result=result)
            self.assertEqual(gate["status"], "blocked")


class FlashNextCampaignContractTests(unittest.TestCase):
    def test_residency_observations_survive_every_tool_turn_in_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = _SyntheticResidentServer()
            result, _, requests = _run(Path(tmp), server=server)
            metadata = [item for row in result["rows"] for item in row["raw_observations"]]
            self.assertEqual(server.model_request_count, len(requests))
            self.assertEqual(metadata[0].get("residency_observation"), "first_request_after_process_load")
            self.assertEqual([item.get("residency_observation") for item in metadata[1:]], ["warm_resident"] * 4)
            self.assertTrue(all(item.get("os_file_cache_state") == "unmeasured" for item in metadata))

    def test_established_planner_setup_and_dispatch_reach_real_http_without_auto_qualification(self):
        from localbench.v2.flashnext_role_packets import build_role_cases

        with tempfile.TemporaryDirectory() as tmp, _FixtureEndpoint(static_response="Synthetic fixture response; human review required.") as (endpoint, url):
            output = Path(tmp)
            foundation = _foundation(url, output)
            server = _SyntheticResidentServer()
            summary = campaign.role_runner(
                foundation=foundation, profile=_profile(), output_dir=output, campaign_root=CAMPAIGN_ROOT,
                server=server, roles=["planner"], phase="screen", governor_root=None, progress=lambda msg: None,
            )
            self.assertEqual(summary["completed_cases"], 6)
            self.assertEqual(summary["qualification_status"], "human-review-pending")
            self.assertEqual(summary["reviewer_status"], "provisional-unqualified")
            self.assertIsNone(summary["stopped"])
            self.assertEqual(len(endpoint.requests), 12)
            self.assertEqual(server.model_request_count, 12)
            first = build_role_cases(CAMPAIGN_ROOT, "planner")[0]
            self.assertEqual(endpoint.requests[0]["wire"]["messages"], [{"role": "user", "content": first["setup_prompt"]}])
            dispatch = endpoint.requests[1]["wire"]["messages"]
            self.assertEqual([message["role"] for message in dispatch], ["user", "assistant", "user"])
            self.assertEqual(dispatch[-1]["content"], first["task_prompt"])
            self.assertTrue(all("tools" not in request["wire"] for request in endpoint.requests))
            for case in summary["results"]:
                self.assertEqual(case["status"], "success")
                self.assertEqual(case["correctness"], "human-review-pending")
                self.assertTrue(case["human_review_required"])
                self.assertEqual(case["metrics"]["model_turns"], 2)
                self.assertEqual(case["metrics"]["output_tokens"], 18)
                self.assertEqual(case["metrics"]["generation_tokens_per_second"], 100)
                raw_files = list(Path(case["evidence_directory"]).rglob("response.body"))
                self.assertEqual(len(raw_files), 2)
                self.assertTrue((Path(case["evidence_directory"]) / "resource-telemetry-ref.json").exists())

    def test_smoke_projection_preserves_cases_and_complete_screen_preserves_original_bytes(self):
        total = 0
        for level in ("L0", "L1", "L2"):
            original = (ROOT / f"benchmark-packs/v2/shared-{level.lower()}-core-v1.json").read_bytes()
            complete, full_provenance = campaign.pack_bytes(ROOT, level, smoke=False)
            projected, smoke_provenance = campaign.pack_bytes(ROOT, level, smoke=True)
            self.assertEqual(complete, original)
            self.assertEqual(full_provenance["source_sha256"], hashlib.sha256(original).hexdigest())
            self.assertIsNone(full_provenance["case_projection"])
            source = json.loads(original)
            selected = json.loads(projected)
            total += len(source["cases"])
            expected = [case for case in source["cases"] if case["case_id"] in campaign.SMOKE_CASES[level]]
            self.assertEqual(selected["cases"], expected)
            self.assertEqual(selected["level"], source["level"])
            self.assertEqual(smoke_provenance["source_sha256"], full_provenance["source_sha256"])
        self.assertEqual(total, 22)

    def test_default_validate_does_not_preflight_or_start_a_runtime(self):
        with patch.object(campaign, "preflight_identity") as preflight, \
             patch.object(campaign, "OwnedFlashNextServer") as server, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(campaign.main(["--repo-root", str(ROOT)]), 0)
        preflight.assert_not_called()
        server.assert_not_called()

    def test_missing_explicit_prerequisites_block_before_preflight_or_model_load(self):
        for args in (["shared-screen"], ["shared-qualification"], ["roles"],
                     ["roles", "--shared-run", "some-run"],
                     ["roles", "--shared-run", "some-run", "--role", "governor"]):
            with self.subTest(args=args), patch.object(campaign, "preflight_identity") as preflight, \
                 patch.object(campaign, "OwnedFlashNextServer") as server, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(campaign.main([*args, "--repo-root", str(ROOT)]), 2)
                preflight.assert_not_called()
                server.assert_not_called()

    def test_full_shared_screen_runs_all_22_accepted_cases_with_real_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            chain = _run_chain(Path(tmp))
            output, result, foundation = chain["shared_dir"], chain["shared_result"], chain["foundation"]
            self.assertEqual(result["completed_observations"], 22)
            self.assertEqual(len({r["case_id"] for r in result["rows"]}), 22)
            self.assertTrue(result["all_correct"])
            self.assertTrue(result["native_tool_smoke_pass"])
            self.assertFalse(result["role_qualified"])
            self.assertEqual(len(chain["requests"]), 5 + 35)
            gate = chain["shared_gate"]
            self.assertEqual(gate["status"], "pass")
            self.assertEqual(gate["parent_smoke_run"], str(chain["smoke_dir"].resolve()))
            self.assertEqual(gate["parent_gate_sha256"], sha256_json(chain["smoke_gate"]))
            for ref in result["evidence"]:
                if ref["reference"]["record_type"] != "effective_runtime_config" or not ref["path"].startswith("l2/"):
                    continue
                record = SealedEvidence.from_dict(json.loads((output / ref["path"]).read_bytes()))
                profile = record.logical_id.removeprefix("flashnext-")
                expected_max = {"shared-l2-tools-3-v1": 3, "shared-l2-tools-4-v1": 4, "shared-l2-tools-5-v1": 5}[profile]
                self.assertEqual(record.payload["tool_surface"]["max_tool_calls"], expected_max)
            verified = campaign.verify_gate(output, stage="shared-screen", fingerprint=foundation["fingerprint"])
            self.assertEqual(verified["completed_observations"], 22)


if __name__ == "__main__":
    unittest.main()
