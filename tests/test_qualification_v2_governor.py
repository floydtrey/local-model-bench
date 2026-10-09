"""Governor contract, privacy, adjudication and real role-engine tests without inference."""
from __future__ import annotations

import copy
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from localbench.assistant001.packet import write_json
from localbench.qualification_v2 import governor_packet as packets
from localbench.qualification_v2.governor import run_governor, assess_run, verified_comparison_row, main
from localbench.qualification_v2.governor_assessment import assess, draft_review, rubric, validate_review, compare
from localbench.qualification_v2.governor_calibration import calibrate
from localbench.qualification_v2.governor_evidence import captured_protocol
from localbench.qualification_v2.planner_packet import sha
from localbench.v2.contracts import seal_evidence
from localbench.v2.tool_harness import ModelTurnResponse, ToolCall

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "docs/qualification-v2/governor-calibration"


def authored(name="correct-approval", project="assistant-001"):
    manifest = json.loads((CAL / "manifest.json").read_bytes())
    record = next(f for f in manifest["fixtures"] if f["name"] == name and f["project"] == project)
    return (record["packet_binding"], (CAL / project / (name + ".txt")).read_bytes().decode(),
            json.loads((CAL / project / (name + ".json")).read_bytes()))


def unit_review(packet, text, repo):
    """Synthetic human declaration for wiring tests; never published as a real review."""
    review = draft_review(packet, text, repo)
    evidence = [{"start": 0, "end": len(text), "quote": text}]
    review.update(reviewer="SYNTHETIC UNIT TEST", reviewed_at="2026-10-09T18:00:00Z",
                  decision="APPROVE", verdict="PASS", rationale="Synthetic record consistency test.", decision_evidence=evidence)
    for row in [review["reasoning"], *review["restrictions"], review["authority_claim"], review["plan_fidelity"]]:
        row.update(status="covered", evidence=evidence, rationale="Synthetic record consistency test.")
    return review


class GovernorFrozenTests(unittest.TestCase):
    def test_complete_frozen_inventory_and_review_status(self):
        freeze = packets.load_freeze(ROOT)
        self.assertEqual(freeze["human_review_status"], "PENDING")
        self.assertEqual(freeze["independent_review_status"], "PENDING")
        self.assertFalse(freeze["model_qualification_complete"])
        for project in packets.PROJECTS:
            base = packets.fixture_root(ROOT) / project
            inputs = json.loads((base / "inputs.json").read_bytes())["cases"]
            oracle = json.loads((base / "oracle.json").read_bytes())["cases"]
            self.assertEqual(len(inputs), 14)
            self.assertEqual([r["case_id"] for r in inputs], [r["case_id"] for r in oracle])
            self.assertEqual({r["expected_decision"] for r in oracle}, {"APPROVE", "DENY", "ESCALATE"})
            for row in oracle:
                self.assertTrue(row["rationale"] and row["law_references"] and row["restrictions"])
                self.assertEqual(row["review_status"], "HUMAN_REVIEW_PENDING")
            self.assertNotIn("expected_decision", json.dumps(inputs))
            self.assertEqual({r["coverage"] for r in oracle}, {
                "bounded", "forbidden", "law-intent", "fabricated-grant", "scoped-disclosure-grant",
                "exception-missing", "identity", "permission", "scope-drift", "external", "uncertainty",
                "invariant", "unsupported-exception", "explicit-override"})
        # No canonical document content is packaged in this additive corpus.
        self.assertFalse(any(p.name in packets.DOCUMENTS for p in packets.fixture_root(ROOT).rglob("*")))

    def test_calibration_negative_controls_and_alternative_prose(self):
        result = calibrate(ROOT)
        self.assertEqual(len(result["fixtures"]), 16)
        self.assertEqual(result["semantic_calibration_status"], "HUMAN_REVIEW_PENDING")
        self.assertFalse(result["qualification_complete"])
        for project in packets.PROJECTS:
            for name, classification in (("unsafe-approval", "unsafe_approval"), ("blanket-denial", "false_denial"),
                                         ("erroneous-escalation", "erroneous_escalation"), ("omitted-constraints", "omitted_constraints")):
                packet, text, review = authored(name, project)
                review["review_origin"] = "human_declared"  # synthetic declaration in test only
                result = assess(packet, text, review=review, repo=ROOT)
                self.assertEqual(result["assessed_outcome"], "FAIL")
                self.assertIn(classification, result["failure_classifications"])
                if name in ("unsafe-approval", "omitted-constraints"):
                    self.assertTrue(result["critical_unsafe_approval"])
            for name in ("correct-approval", "alternate-approval", "correct-denial", "correct-escalation"):
                packet, text, review = authored(name, project)
                self.assertNotIn(review["decision"], text)  # no magic token requirement
                review["review_origin"] = "human_declared"
                self.assertEqual(assess(packet, text, review=review, repo=ROOT)["assessed_outcome"], "PASS")

    def test_tokens_and_authored_annotations_never_auto_pass(self):
        packet, _, fixture = authored()
        for text in ("", "APPROVE", "DENY", "ESCALATE", "APPROVE DENY ESCALATE", "{\"decision\":\"APPROVE\"}"):
            result = assess(packet, text, repo=ROOT)
            self.assertEqual(result["assessed_outcome"], "NOT_ASSESSED")
            self.assertIsNone(result["critical_unsafe_approval"])
            self.assertFalse(result["project_execution_authorized"])
        packet, text, fixture = authored()
        with self.assertRaisesRegex(ValueError, "origin"):
            assess(packet, text, review=fixture, repo=ROOT)

    def test_review_bindings_and_material_omissions_fail_closed(self):
        packet, text, original = authored()
        original["review_origin"] = "human_declared"
        for mutate in (
            lambda r: r.update(input_sha256="0" * 64), lambda r: r.update(candidate_sha256="0" * 64),
            lambda r: r.update(rubric_sha256="0" * 64), lambda r: r.update(case_id="other"),
            lambda r: r.update(reviewer=""), lambda r: r.update(reviewed_at="2026-10-09"),
            lambda r: r["restrictions"].pop(), lambda r: r["restrictions"].append(None),
            lambda r: r["restrictions"][0].update(status="missing", evidence=[]),
            lambda r: r["decision_evidence"][0].update(quote="fabricated"),
            lambda r: r.update(reasoning=None), lambda r: r["reasoning"].update(id="unexpected"),
            lambda r: r.update(decision="DENY"),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.assertRaises(ValueError):
                validate_review(changed, packet, text, repo=ROOT)
        for status, violation in (("error", 0), ("blocked", 0), ("success", 1), ("success", -1)):
            with self.assertRaises(ValueError):
                validate_review(original, packet, text, execution_status=status, authority_violations=violation, repo=ROOT)

    def test_undetermined_or_empty_answer_can_be_reviewed_as_failure(self):
        packet, _, _ = authored()
        for text in ("", "I both approve and deny, with no resolution."):
            review = draft_review(packet, text, ROOT)
            review.update(reviewer="SYNTHETIC TEST", reviewed_at="2026-10-09T18:00:00Z", decision="UNDETERMINED",
                          verdict="FAIL", rationale="No unambiguous ruling or necessary constraints.")
            for row in [review["reasoning"], *review["restrictions"], review["authority_claim"], review["plan_fidelity"]]:
                row.update(status="missing", rationale="Missing or unresolved in the entire answer.")
            result = assess(packet, text, review=review, repo=ROOT)
            self.assertIn("missing_decision", result["failure_classifications"])


class GovernorPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "public-repo"
        self.governor = self.base / "private-test-governance"
        shutil.copytree(packets.fixture_root(ROOT), packets.fixture_root(self.repo))
        target = self.repo / "docs/qualification-v2/EVALUATION_MODES_V1.json"
        target.write_bytes((ROOT / "docs/qualification-v2/EVALUATION_MODES_V1.json").read_bytes())
        freeze = packets.load_freeze(ROOT)
        for project, files in freeze["project_sources"].items():
            for name in files:
                path = self.repo / "project-benchmarks" / project / "v1" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / path.relative_to(self.repo)).read_bytes())
        from localbench.assistant001.runtime import ROLE_FILES
        relative = Path("campaigns/flashnext-all-roles-v1/sources") / ROLE_FILES["governor"][0]
        (self.repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / relative).write_bytes((ROOT / relative).read_bytes())
        # CI uses only obvious synthetic documents and its OWN pinned test freeze.
        # No canonical private bytes or private checkout is needed for any test.
        path = packets.fixture_root(self.repo) / "canonical-provenance.json"
        provenance = json.loads(path.read_bytes())
        for name in packets.DOCUMENTS:
            raw = ("SYNTHETIC UNIT TEST DOCUMENT " + name + "\nNot real governing authority.\n").encode()
            dest = self.governor / "docs" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            provenance["documents"][name] = sha(raw)
        write_json(path, provenance)
        freeze["files"]["canonical-provenance.json"] = sha(path.read_bytes())
        path = packets.fixture_root(self.repo) / "freeze.json"
        write_json(path, freeze)
        pin = patch.object(packets, "FREEZE_SHA256", sha(path.read_bytes()))
        pin.start()
        self.addCleanup(pin.stop)

    def prepare(self, project="assistant-001", case="01"):
        return packets.prepare(project, self.base / "private-evidence", case=case, governor_root=self.governor, repo=self.repo)

    def test_all_cases_stable_without_oracle_metadata_paths_or_workspace(self):
        for project in packets.PROJECTS:
            for case in packets.CASES:
                run = self.prepare(project, case)
                packet = packets.verify_run(run, self.repo)
                self.assertEqual(packet, packets.build_packet(project, case, self.governor, self.repo))
                self.assertEqual(packet["input_sha256"], sha(packet["prompt"].encode()))
                self.assertFalse((run / "workspace").exists())
                for secret in ("oracle.json", "expected_decision", "AUTHORED_SYNTHETIC_REFERENCE", "calibration_fixture",
                               "governor-calibration", "rubric_sha256", str(self.repo), str(self.governor)):
                    self.assertNotIn(secret, packet["prompt"])
                for name in packets.DOCUMENTS:
                    self.assertEqual((run / "governance/docs" / name).read_bytes(), (self.governor / "docs" / name).read_bytes())

    def test_private_output_in_repository_or_git_ancestor_is_rejected(self):
        for output in (self.repo, self.repo / "local-state", self.repo / "nested/deep"):
            with self.assertRaises(ValueError):
                packets.prepare("assistant-001", output, governor_root=self.governor, repo=self.repo)
        outer = self.base / "other-repository"
        outer.mkdir()
        (outer / ".git").write_text("gitdir: somewhere")
        with self.assertRaises(ValueError):
            packets.external_directory(outer / "private", self.repo)

    def test_drift_in_any_governance_document_blocks_dispatch(self):
        for name in packets.DOCUMENTS:
            run = self.prepare()
            (run / "governance/docs" / name).write_bytes(b"CHANGED")
            session = Mock()
            with self.assertRaisesRegex(ValueError, "drift"):
                run_governor(run, session, repo=self.repo)
            session.assert_not_called()

    def test_prompt_run_metadata_and_workspace_injection_block_dispatch(self):
        for attack in ("prompt", "metadata", "workspace"):
            run = self.prepare()
            if attack == "prompt":
                (run / "prompt.txt").write_text("oracle injected")
            elif attack == "metadata":
                obj = json.loads((run / "run.json").read_bytes())
                obj["input_sha256"] = "0" * 64
                write_json(run / "run.json", obj)
            else:
                (run / "workspace").mkdir()
                (run / "workspace/oracle.json").write_text("SECRET")
            session = Mock()
            with self.assertRaises(ValueError):
                run_governor(run, session, repo=self.repo)
            session.assert_not_called()

    def test_frozen_case_and_rehashed_manifest_drift_are_rejected(self):
        base = packets.fixture_root(self.repo)
        target = base / "assistant-001/inputs.json"
        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "material changed"):
            self.prepare()
        freeze = json.loads((base / "freeze.json").read_bytes())
        freeze["files"]["assistant-001/inputs.json"] = sha(target.read_bytes())
        write_json(base / "freeze.json", freeze)
        with self.assertRaisesRegex(ValueError, "freeze changed"):
            self.prepare()

    def test_link_and_reparse_routes_rejected(self):
        link = self.base / "linked-private"
        try:
            link.symlink_to(self.governor, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            import subprocess
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.governor)], capture_output=True)
            self.assertEqual(result.returncode, 0)
        with self.assertRaises(ValueError):
            packets.build_packet("assistant-001", "01", link, self.repo)
        with self.assertRaises(ValueError):
            packets.external_directory(link / "evidence", self.repo)
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()  # Remove the junction itself, never recurse through it.

    def test_redirected_private_report_directory_cannot_leak_into_public_repo(self):
        run = self.prepare()
        link = run / "assessments"
        try:
            link.symlink_to(self.repo, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            import subprocess
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.repo)], check=True, capture_output=True)
        try:
            with self.assertRaisesRegex(ValueError, "descendant"):
                packets.verify_run(run, self.repo)
        finally:
            if link.is_symlink():
                link.unlink()
            else:
                link.rmdir()

    def test_cli_consent_gate_and_failed_session_do_not_touch_provider(self):
        run = self.prepare()
        with patch("localbench.assistant001.runtime.OllamaSessions") as factory:
            self.assertEqual(main(["run", "--repo-root", str(self.repo), "--run-dir", str(run), "--model", "fake"]), 1)
            factory.assert_not_called()
        result = run_governor(run, Mock(side_effect=TimeoutError("synthetic failure")), repo=self.repo)
        self.assertEqual(result["status"], "error")
        target, assessed = assess_run(run, repo=self.repo)
        self.assertEqual(assessed["assessed_outcome"], "NOT_ASSESSED")
        self.assertFalse(json.loads((target / "summary.json").read_bytes())["results"][0]["comparison_eligible"])

    def test_imports_use_shared_writer_and_never_claim_runtime_or_authority(self):
        run = self.prepare()
        text = "A synthetic reviewer wiring example."
        candidate = self.base / "candidate.txt"
        candidate.write_bytes(text.encode())
        target, result = assess_run(run, candidate_file=candidate, repo=self.repo)
        self.assertEqual(result["assessed_outcome"], "NOT_ASSESSED")
        review = unit_review(packets.verify_run(run, self.repo), text, self.repo)
        review_path = self.base / "review.json"
        write_json(review_path, review)
        second, result = assess_run(run, candidate_file=candidate, review_file=review_path, repo=self.repo)
        self.assertNotEqual(target, second)
        self.assertEqual(result["assessed_outcome"], "PASS")
        self.assertFalse(result["project_execution_authorized"])
        with (second / "review/case-results.csv").open(encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
            self.assertEqual(row["assessed_outcome"], "PASS")
            self.assertEqual(row["comparison_eligible"], "False")
            self.assertEqual(row["reference_review_status"], "HUMAN_REVIEW_PENDING")
        package = json.loads((second / "review/review-package.json").read_bytes())
        self.assertIsNone(package["case_results"][0]["deterministic_passed"])
        self.assertEqual(package["role_summary"][0]["deterministic_evaluated"], 0)
        self.assertTrue((second / "review/review-package.xlsx").exists())

    def runtime(self, run, model="synthetic-a", thinking=False, attack=False):
        from localbench.assistant001.runtime import OllamaSessions
        from localbench.v2.records import runtime_profile, model_identity
        requests = []

        def foundation(**kwargs):
            runtime = runtime_profile("test-runtime", runtime_kind="ollama", version="unit-test", build=None,
                                      transport={"base_uri": "http://127.0.0.1:11434"}, executable=None,
                                      installation_digest=None, capabilities={"chat": True})
            identity = model_identity("test-model", family="synthetic", name=model, source={"kind": "synthetic"},
                                      artifact_digest=None, provider_digest=sha(model.encode()), parameter_count=None,
                                      quantization="test", precision=None, declared_context_tokens=32768)
            host = seal_evidence("host_profile", "test-host", {"facts_sha256": "a" * 64})
            interface = seal_evidence("execution_interface_identity", "test-interface",
                                      {"runtime": runtime.reference.to_dict(), "model": identity.reference.to_dict()})
            records = {"runtime": runtime, "model": identity, "host": host, "interface": interface}
            kwargs["store"].persist_many(records.values())
            return records, {"capabilities": ["tools", "thinking"] if thinking else ["tools"]}

        def driver(request):
            requests.append(request)
            if len(request.messages) == 1:
                return ModelTurnResponse(content="Understood.")
            if attack and len(request.messages) == 3:
                return ModelTurnResponse(tool_calls=tuple(ToolCall(str(i), name, args) for i, (name, args) in enumerate([
                    ("list_files", {}), ("read_file", {"path": "../../governor-v1/assistant-001/oracle.json"}),
                    ("read_file", {"path": str(ROOT / 'docs/qualification-v2/governor-calibration/manifest.json')}),
                    ("write_file", {"path": "candidate.py", "content": "raise RuntimeError"}), ("run_tests", {})])))
            return ModelTurnResponse(content="Synthetic no-inference test response.")

        with patch("urllib.request.urlopen", side_effect=AssertionError("No network permitted")), \
             patch("localbench.v2.flashnext_role_harness.run_python_check", side_effect=AssertionError("No candidate code execution")), \
             patch("localbench.v2.ollama_role_campaign.build_foundation", side_effect=foundation), \
             patch("localbench.v2.ollama_driver.OllamaChatDriver", return_value=driver):
            sessions = OllamaSessions(self.repo, run, model)
            write_json(run / "runtime-identity.json", {k: v.reference.to_dict() for k, v in sessions.foundation.items()})
            write_json(run / "runner-inputs.json", {"model": model, "context_tokens": 32768, "max_output_tokens": 8192,
                "timeout_seconds": 600, "transport": "direct_ollama", "host_execution_authorized": False,
                "session_policy": "fresh no-tools RoleConversation", "governor_mode": "independent_frozen_simulation"})
            result = run_governor(run, sessions, repo=self.repo)
        return result, requests

    def test_real_role_engine_denies_tools_paths_and_generated_code(self):
        run = self.prepare()
        result, requests = self.runtime(run, attack=True)
        self.assertEqual(result["authority_violations"], 5)
        self.assertEqual(result["test_tool_calls"], 0)
        self.assertTrue(all(not r.tools and not r.context_assets for r in requests))
        for request in requests:
            for message in request.messages:
                if message["role"] == "tool":
                    self.assertEqual(message["result"]["reason"], "tool_not_exposed")
        with self.assertRaises(ValueError):
            run_governor(run, Mock(), repo=self.repo)
        target, _ = assess_run(run, repo=self.repo)
        self.assertFalse(json.loads((target / "summary.json").read_bytes())["results"][0]["comparison_eligible"])

    def captured_row(self, model, thinking=False):
        run = self.prepare()
        result, _ = self.runtime(run, model=model, thinking=thinking)
        packet = packets.verify_run(run, self.repo)
        review = unit_review(packet, result["final_response"], self.repo)
        review_path = self.base / (run.name + "-review.json")
        write_json(review_path, review)
        target, _ = assess_run(run, review_file=review_path, repo=self.repo)
        return run, result, json.loads((target / "summary.json").read_bytes())["results"][0]

    def test_comparison_uses_effective_evidence_and_is_order_symmetric(self):
        first, _, a = self.captured_row("synthetic-a")
        second, _, b = self.captured_row("synthetic-b")
        self.assertNotEqual(first, second)
        self.assertTrue(a["comparison_eligible"], a["provenance_note"])
        self.assertTrue(b["comparison_eligible"], b["provenance_note"])
        self.assertTrue(compare([a, b])["comparable"])
        self.assertTrue(compare([b, a])["comparable"])
        source_a = Path(a["assessment_file"]).parent / "summary.json"
        source_b = Path(b["assessment_file"]).parent / "summary.json"
        self.assertEqual(verified_comparison_row(source_a, self.repo), a)
        self.assertEqual(verified_comparison_row(source_b, self.repo), b)
        original = source_b.read_bytes()
        tampered = json.loads(original)
        tampered["results"][0]["candidate_decision"] = "DENY"
        write_json(source_b, tampered)
        with self.assertRaisesRegex(ValueError, "summary differs"):
            verified_comparison_row(source_b, self.repo)
        source_b.write_bytes(original)
        self.assertFalse(compare([a, a])["comparable"])
        self.assertFalse(compare([a, b])["qualification_complete"])
        for field, value in (("input_sha256", "different"), ("rubric_sha256", "different"),
                             ("governance_sha256", "different"), ("human_review_status", "pending"),
                             ("output_origin", "external_text_no_model_run_claim"), ("authority_violations", 1)):
            changed = copy.deepcopy(b)
            changed[field] = value
            self.assertFalse(compare([a, changed])["comparable"])
        _, _, thinking = self.captured_row("synthetic-thinking", thinking=True)
        self.assertTrue(thinking["comparison_eligible"])
        self.assertFalse(compare([a, thinking])["comparable"])

    def test_missing_changed_runtime_evidence_and_output_block_comparison(self):
        run, result, _ = self.captured_row("synthetic-a")
        packet = packets.verify_run(run, self.repo)
        paths = [run / "roles/governor/events.jsonl", run / "roles/governor/dispatch.txt",
                 next((run / "evidence/records/effective_runtime_config").glob("*.json"))]
        for path in paths:
            saved = path.read_bytes()
            path.write_bytes(b"{}")
            with self.assertRaises((ValueError, KeyError)):
                captured_protocol(run, packet, result, self.repo)
            path.write_bytes(saved)
        (run / "roles/governor/final.txt").write_text("different candidate")
        with self.assertRaisesRegex(ValueError, "differs"):
            assess_run(run, repo=self.repo)


if __name__ == "__main__":
    unittest.main()
