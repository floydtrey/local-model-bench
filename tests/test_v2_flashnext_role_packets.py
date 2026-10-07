from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from localbench.v2.flashnext_role_packets import (
    REVIEWER_SETUP_SUFFIX,
    build_role_cases,
    reviewer_packet,
)


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "flashnext-all-roles-v1"


class FlashNextRolePacketTests(unittest.TestCase):
    def test_planner_reuses_exact_role_and_intents_as_two_user_turns(self) -> None:
        corpus = CAMPAIGN / "sources" / "local-model-bench" / "benchmark" / "planner"
        cases = build_role_cases(CAMPAIGN, "planner")
        self.assertEqual(len(cases), 6)
        for case in cases:
            self.assertEqual(case["setup_prompt"].encode(), (corpus / "ROLE_PROMPT.txt").read_bytes())
            self.assertIsNone(case["setup_expected_marker"])
            intent = next(ref for ref in case["source_refs"] if "/intent-" in ref["source_path"])
            self.assertEqual(case["task_prompt"].encode(), Path(intent["local_path"]).read_bytes())
            self.assertEqual(case["tools"], [])
            self.assertEqual(case["correctness"], "human-review-pending")
            self.assertNotIn("system", case)

    def test_governor_requires_real_documents_and_preserves_their_bytes(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical Governor"):
            build_role_cases(CAMPAIGN, "governor")
        with tempfile.TemporaryDirectory() as temp:
            governor = Path(temp)
            docs = governor / "docs"
            docs.mkdir()
            data = {
                "LAW.md": b"LAW sentinel\r\nOwner boundary.\r\n",
                "STATE.md": b"STATE sentinel\n",
                "GENERAL_INTENT.md": b"GENERAL sentinel\n",
            }
            for name, contents in data.items():
                (docs / name).write_bytes(contents)
            cases = build_role_cases(CAMPAIGN, "governor", governor_root=governor)
            self.assertEqual(len(cases), 4)
            packet = cases[0]["task_prompt"]
            headings = ["## Qualification Condition", "## Original Project Intent", "## Proposed Plan", "## Law", "## State", "## General Intent", "## Project Intent"]
            self.assertEqual([packet.index(heading) for heading in headings], sorted(packet.index(heading) for heading in headings))
            self.assertIn("unless the proposed plan itself requires an Owner-only action or changes a protected assignment", packet)
            for name, contents in data.items():
                ref = next(ref for ref in cases[0]["source_refs"] if ref["source_path"] == "docs/" + name)
                self.assertEqual(ref["sha256"], hashlib.sha256(contents).hexdigest())
                self.assertIn(contents.decode(), packet)
            (docs / "STATE.md").unlink()
            with self.assertRaises(FileNotFoundError):
                build_role_cases(CAMPAIGN, "governor", governor_root=governor)

    def test_modified_frozen_source_is_rejected_before_packet_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign = Path(temp)
            source = campaign / "sources" / "local-model-bench"
            source.parent.mkdir()
            shutil.copytree(CAMPAIGN / "sources" / "local-model-bench", source)
            path = source / "benchmark" / "planner" / "ROLE_PROMPT.txt"
            path.write_bytes(path.read_bytes() + b"Unexpected changed behavior.\n")
            with self.assertRaisesRegex(ValueError, "Pinned source bytes changed"):
                build_role_cases(campaign, "planner")

    def test_reviewer_retains_provisional_status_and_evidence_claim_distinction(self) -> None:
        cases = {case["case_id"]: case for case in build_role_cases(CAMPAIGN, "reviewer")}
        role = (CAMPAIGN / "sources" / "deepseek-lab" / "native-lab" / "reviewer-role.md").read_bytes().decode()
        for case in cases.values():
            self.assertEqual(case["setup_prompt"], role + REVIEWER_SETUP_SUFFIX)
            self.assertEqual(case["setup_expected_marker"], "REVIEWER_READY")
            self.assertEqual(case["correctness"], "human-review-pending")
            self.assertEqual(case["qualification_status"], "provisional-unqualified")
            self.assertEqual(case["tools"], [])
            self.assertIn("synthetic qualification packet", case["expected_observations"]["evidence_origin"])
        claim_only = cases["reviewer-title-claim-only"]
        self.assertIn("No independently captured test result", claim_only["task_prompt"])
        self.assertIn("I ran tests.", claim_only["task_prompt"])
        self.assertIsNone(claim_only["expected_observations"]["expected_verdict"])
        self.assertEqual(cases["reviewer-note-wrong-content"]["expected_observations"]["expected_verdict"], "FAIL")
        self.assertEqual(cases["reviewer-note-missing-evidence"]["expected_observations"]["expected_verdict"], "BLOCKED")
        for case_id, case in cases.items():
            if case_id.startswith("reviewer-note-"):
                self.assertIn("New evidence case derived", case["fixture_transformations"][0])

    @unittest.skipUnless(shutil.which("node"), "Node is needed to compare with the original JavaScript packet builder")
    def test_python_reviewer_packet_matches_original_javascript_bytes(self) -> None:
        original = CAMPAIGN / "sources" / "deepseek-lab" / "native-lab" / "reviewer-dispatch.mjs"
        source = original.read_text(encoding="utf-8")
        start = source.index("export function reviewerPacket(")
        end = source.index("\n}\n", start) + 2
        function = source[start:end].removeprefix("export ")
        script = (
            "import {readFileSync} from 'node:fs';\n" + function + "\n"
            "const values = JSON.parse(readFileSync(0, 'utf8'));\n"
            "process.stdout.write(JSON.stringify(values.map(reviewerPacket)));\n"
        )
        payloads = [case["packet_inputs"] for case in build_role_cases(CAMPAIGN, "reviewer")]
        payloads.append({
            "intent": "intent\r\n", "plan": "plan", "guidance": "guidance", "task": "task",
            "workerFinal": "claim", "changes": [], "tests": [], "workspace": "fixture", "execution": None,
        })
        payloads.append({
            **payloads[-1],
            "changes": [{"path": "deleted", "status": "deleted", "sha256": None},
                        {"path": "empty", "status": "changed", "sha256": "", "content": ""}],
        })
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            input=json.dumps(payloads, ensure_ascii=False), text=True, capture_output=True,
            check=True, timeout=15,
        )
        expected = json.loads(result.stdout)
        self.assertEqual([reviewer_packet(**payload) for payload in payloads], expected)


if __name__ == "__main__":
    unittest.main()
