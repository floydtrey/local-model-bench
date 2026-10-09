"""T02 authority/mode contract and frozen-v1 regression (no models)."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from localbench.qualification_v2.contract import (
    CONTROLLED, INTEGRATION, TRACK_ROLES, TRACK_TRANSPORTS, WORKER_MODES,
    load_registry, validate_selection, validate_disclosure,
)


ROOT = Path(__file__).resolve().parents[1]


def git_blob_sha1(data: bytes) -> str:
    """Git object ID of the exact unchanged source bytes, no git command required."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


class RegistryContractTests(unittest.TestCase):
    def test_exact_two_tracks_five_roles_and_worker_modes(self):
        mode = load_registry(ROOT)
        self.assertEqual(set(mode["tracks"]), {CONTROLLED, INTEGRATION})
        self.assertEqual(tuple(mode["tracks"][CONTROLLED]["roles"]), TRACK_ROLES[CONTROLLED])
        self.assertEqual(tuple(mode["tracks"][INTEGRATION]["roles"]), ("pipeline",))
        self.assertEqual(tuple(mode["tracks"][CONTROLLED]["worker_modes"]), WORKER_MODES)
        self.assertEqual(tuple(mode["tracks"][INTEGRATION]["transports"]), ("native_dsh",))
        self.assertEqual(mode["implementation_status"], "CONTRACT_ONLY_NOT_CONNECTED_TO_LAUNCHERS")

    def test_valid_metadata_selection_does_not_run_anything(self):
        self.assertEqual(validate_selection(CONTROLLED, "planner", "direct_ollama", repo_root=ROOT)["role"], "planner")
        self.assertEqual(validate_selection(CONTROLLED, "governor", "native_dsh", repo_root=ROOT)["transport"], "native_dsh")
        self.assertEqual(validate_selection(CONTROLLED, "worker", "direct_ollama", "isolated_task", repo_root=ROOT)["worker_mode"], "isolated_task")
        self.assertEqual(validate_selection(CONTROLLED, "worker", "native_dsh", "cumulative_project", repo_root=ROOT)["worker_mode"], "cumulative_project")
        self.assertEqual(validate_selection(INTEGRATION, "pipeline", "native_dsh", repo_root=ROOT)["track"], INTEGRATION)

    def test_unknown_or_cross_track_misconfiguration_fails_closed(self):
        bad = [
            ("unknown", "planner", "direct_ollama", None),
            ("CONTROLLED", "planner", "direct_ollama", None),
            (CONTROLLED, "pipeline", "direct_ollama", None),
            (INTEGRATION, "planner", "native_dsh", None),
            (INTEGRATION, "pipeline", "direct_ollama", None),
            (CONTROLLED, "worker", "direct_ollama", None),
            (CONTROLLED, "worker", "direct_ollama", "task6"),
            (CONTROLLED, "planner", "direct_ollama", "isolated_task"),
            (INTEGRATION, "pipeline", "native_dsh", "cumulative_project"),
            (CONTROLLED, "-Model", "direct_ollama", None),
            (CONTROLLED, "planner", "powershell", None),
            (CONTROLLED, True, "direct_ollama", None),
        ]
        for track, role, transport, worker_mode in bad:
            with self.subTest(track=track, role=role, transport=transport, mode=worker_mode):
                with self.assertRaises(ValueError):
                    validate_selection(track, role, transport, worker_mode, repo_root=ROOT)

    def test_planner_disclosure_forbids_both_plan_exposure_routes(self):
        registry = load_registry(ROOT)
        required = registry["role_inputs"]["planner"]["required"]
        self.assertEqual(validate_disclosure("planner", required, repo_root=ROOT), frozenset(required))
        for source in ("fixed_worker_tasks", "reference_plan", "governor_expected_decision",
                       "assessor_checks", "assessor_reference", "hidden_tests",
                       "candidate_workspace_with_tasks", "other_unknown_source"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_disclosure("planner", [*required, source], repo_root=ROOT)
        with self.assertRaises(ValueError):
            validate_disclosure("planner", required[:-1], repo_root=ROOT)
        with self.assertRaises(ValueError):
            validate_disclosure("planner", "project_intent", repo_root=ROOT)

    def test_governor_worker_tester_reviewer_do_not_inherit_authority_from_labels(self):
        registry = load_registry(ROOT)
        for role, injected in [
            ("governor", "governor_expected_decision"),
            ("governor", "owner_approval_forgery"),
            ("worker", "candidate_governor_verdict_as_authority"),
            ("worker", "reference_solution"),
            ("tester", "expected_tester_verdict"),
            ("reviewer", "expected_reviewer_verdict"),
        ]:
            with self.subTest(role=role, injected=injected):
                required = registry["role_inputs"][role]["required"]
                with self.assertRaises(ValueError):
                    validate_disclosure(role, [*required, injected], repo_root=ROOT)
        with self.assertRaises(ValueError):
            validate_disclosure("pipeline", ["project_intent"], repo_root=ROOT)

    def test_tampered_registry_rejected_before_any_launcher(self):
        original = load_registry(ROOT)
        for index, change in enumerate([
            lambda x: x["tracks"].update({"make_more": {}}),
            lambda x: x["tracks"][INTEGRATION]["transports"].append("direct_ollama"),
            lambda x: x["role_inputs"]["planner"]["prohibited"].remove("fixed_worker_tasks"),
            lambda x: x["role_inputs"]["planner"]["required"].append("reference_plan"),
            lambda x: x["safety"].update({"model_governor_verdict_is_authority": True}),
            lambda x: x["safety"].update({"candidate_python_os_sandboxed": True}),
            lambda x: x["authority_origins"].append("governor_said_yes"),
            lambda x: x["worker_modes"].update({"inject_gold_after_failure": {}}),
        ]):
            with self.subTest(mutation=index), tempfile.TemporaryDirectory() as temp:
                changed = copy.deepcopy(original)
                change(changed)
                path = Path(temp) / "docs" / "qualification-v2" / "EVALUATION_MODES_V1.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_registry(Path(temp))
        self.assertFalse(original["safety"]["automatic_role_promotion"])
        self.assertTrue(original["safety"]["native_execution_requires_installed_provenance"])
        self.assertFalse(original["safety"]["private_governance_source_belongs_in_public_repo"])

    def test_historical_role_sources_remain_verified_and_complete(self):
        # Pin the two historic corpus manifests as *original Git blobs* as well
        # as verifying every source entry listed by each manifest. Otherwise a
        # changed fixture and a recomputed manifest could wrongly look frozen.
        manifests = {
            "campaigns/flashnext-all-roles-v1/sources/local-model-bench/SOURCE_MANIFEST.json":
                "7088a0b5c437f4dea51d5b42cb4a7ac75c665d38",
            "campaigns/flashnext-all-roles-v1/sources/deepseek-lab/SOURCE_MANIFEST.json":
                "e77af7d3db97754f8d94b6e00b84ff73f2d1722f",
        }
        for path, expected_blob in manifests.items():
            with self.subTest(path=path):
                self.assertEqual(git_blob_sha1((ROOT / path).read_bytes()), expected_blob)
        # Build packets with synthetic Governor docs only; this does not contact
        # the private canonical Governor repository or grant any real authority.
        from localbench.v2.flashnext_roles import build_role_cases
        suite = ROOT / "campaigns" / "flashnext-all-roles-v1"
        with tempfile.TemporaryDirectory(prefix="qualification-v2-gov-") as tmp:
            governor = Path(tmp)
            docs = governor / "docs"
            docs.mkdir()
            for name in ("LAW.md", "STATE.md", "GENERAL_INTENT.md"):
                (docs / name).write_text("Synthetic fixture for source integrity only.\\n", encoding="utf-8")
            for role, expected in [
                ("planner", 6), ("governor", 4), ("worker", 4),
                ("tester", 3), ("reviewer", 6),
            ]:
                with self.subTest(role=role):
                    cases = build_role_cases(suite, role, governor_root=governor)
                    self.assertEqual(len(cases), expected)
                    self.assertEqual(len(set(case["case_id"] for case in cases)), expected)

    def test_baseline_guard_pins_frozen_packets_but_not_extendable_implementation(self):
        lock = __import__("json").loads((ROOT / "docs/qualification-v2/T01_BASELINE_LOCK.json").read_text(encoding="utf-8"))
        fixed = [
            "campaigns/flashnext-all-roles-v1/role-suite.json",
            "campaigns/flashnext-all-roles-v1/accepted-battery-lock.json",
            "project-benchmarks/assistant-001/v1/manifest.json",
            "project-benchmarks/assistant-001/v1/CONTRACT.md",
            "project-benchmarks/assistant-001/v1/TASKS.md",
            "project-benchmarks/assistant-002/v1/manifest.json",
            "project-benchmarks/assistant-002/v1/CONTRACT.md",
            "project-benchmarks/assistant-002/v1/TASKS.md",
        ]
        for path in fixed:
            with self.subTest(path=path):
                self.assertEqual(git_blob_sha1((ROOT / path).read_bytes()),
                                 lock["git_blob_sha1"][path])
        self.assertTrue(any(p.startswith("src/") for p in lock["git_blob_sha1"]))
        # Executable code intentionally is NOT frozen by this v1-doc guard.


if __name__ == "__main__":
    unittest.main()
