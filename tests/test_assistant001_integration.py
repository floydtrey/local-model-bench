"""Verify real V2 wiring with fake provider responses, never live inference."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from localbench.assistant001.packet import repository_root


class ExistingV2Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import localbench.v2.flashnext_review
        except ImportError as exc:
            if os.environ.get("ASSISTANT001_REQUIRE_V2") == "1":
                raise
            raise unittest.SkipTest("Full base checkout required for existing V2 integration") from exc

    def test_existing_review_writer_produces_standard_files(self):
        from localbench.assistant001.cli import review_package
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            summary = {"campaign": "assistant-001-v1", "results": [
                {"case_id": "assistant001-t01", "role": "worker", "ordinal": 1,
                 "status": "success", "deterministic_passed": True, "first_pass_passed": True,
                 "human_review_required": True, "metrics": {"wall_seconds": 1.5}}],
                "planned_cases": 1, "completed_cases": 1,
                "qualification_status": "human-review-pending"}
            review_package(run, summary, "fixture:only", "screen", 32768)
            for name in ("review-package.xlsx", "review-package.json", "case-results.csv", "role-summary.csv"):
                self.assertTrue((run / "review" / name).is_file(), name)

    def test_runtime_uses_existing_conversation_and_separate_setup_dispatch_configs(self):
        from localbench.assistant001.runtime import OllamaSessions
        from localbench.v2.tool_harness import ModelTurnResponse
        observed = {"capabilities": ["tools"]}
        effective = SimpleNamespace(reference=SimpleNamespace(to_dict=lambda: {"fixture": "sealed-reference"}))
        requests = []
        def driver(request):
            requests.append(request)
            return ModelTurnResponse(content="Ready" if len(requests) % 2 else "Useful plain-prose handoff")
        with tempfile.TemporaryDirectory() as folder, \
             patch("urllib.request.urlopen", side_effect=AssertionError("No network in unit tests")), \
             patch("localbench.v2.ollama_role_campaign.build_foundation", return_value=({"runtime": "fixture-runtime", "model": "fixture-model"}, observed)), \
             patch("localbench.v2.orchestrator.EvidenceStore", return_value=Mock()), \
             patch("localbench.v2.ollama_driver.ollama_adapter_resolution", return_value={}), \
             patch("localbench.v2.configuration.resolve_effective_configuration", return_value=effective) as resolve, \
             patch("localbench.v2.ollama_driver.OllamaChatDriver", return_value=driver):
            run = Path(folder); workspace = run / "workspace"; workspace.mkdir()
            (workspace / "example.py").write_text("# fixture\n")
            sessions = OllamaSessions(repository_root(), run, "fixture:only")
            for i in range(2):
                result = sessions(role="worker", case_id="assistant001-t01", prompt="Test no-op",
                                  workspace=workspace, writable=["example.py"], evidence=run / f"session-{i}")
                self.assertEqual(result["status"], "success")
            ids = [call.args[0] for call in resolve.call_args_list]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertFalse(requests[0].tools)
            self.assertTrue(requests[1].tools)
            self.assertEqual(requests[1].messages[1]["content"], "Ready")
            specs = [call.kwargs["spec"] for call in resolve.call_args_list]
            self.assertEqual(specs[0]["tool_surface"]["id"], "none")
            self.assertEqual(specs[1]["tool_surface"]["id"], "flashnext-role-files-tests:v1")
            self.assertTrue(all(s["execution"]["concurrency"] == 1 for s in specs))
            self.assertTrue(all(0 < s["execution"]["timeout_seconds"] <= 600 for s in specs))

if __name__ == "__main__":
    unittest.main()
