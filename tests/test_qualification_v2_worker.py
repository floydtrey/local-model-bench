"""Deterministic adapters and fail-closed gates; no provider or candidate execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localbench.assistant001.packet import digest, snapshot, write_json
from localbench.qualification_v2.worker import (
    APIS, canonical, load_canonical, prepare_worker, verify_worker, authorize,
    validate_seed, run_worker)
from localbench.v2.contracts import sha256_json

REPO = Path(__file__).resolve().parents[1]


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def prepare(self, project="assistant-001", mode="CUMULATIVE_PROJECT", **kwargs):
        return prepare_worker(project, mode, self.root, repo=REPO, **kwargs)

    def grant(self, run, origin="trusted_operator"):
        control = verify_worker(run, REPO)
        grant = {"schema_version": "qualification-v2/worker-authorization-v1", "origin": origin,
            "input_sha256": control["input_sha256"], "bundle_sha256": control["bundle_sha256"],
            "reference_review": "approved", "allow_model_inference": True,
            "allow_host_execution": True, "exceptions": [],
            "provenance_reference": "DETERMINISTIC TEST ONLY; not real authorization",
            "seed_validation_sha256": sha256_json(control["seed"]), "target_unsolved_review": "approved"}
        path = self.root / (run.name + "-test-grant.json")
        write_json(path, grant)
        return path, digest(path)

    def execute(self, run, sessions, **kwargs):
        path, sha = self.grant(run)
        return run_worker(run, sessions, repo=REPO, authorization_file=path,
            trusted_sha256=sha, allow_model_inference=True, allow_host_execution=True, **kwargs)

    def assessor(self, passed=True, status="completed"):
        def check(run, task, **kwargs):
            path = Path(run) / "assessments" / task
            result = {"passed": passed, "status": status, "checks": [{"case_id": task, "passed": passed}],
                      "planned": 1, "executed": 1}
            write_json(path / "assessment.json", result)
            return result, path
        return check

    def seed(self, project="assistant-001", task="T02"):
        # A fake assessor is explicitly injected; these fixtures never claim
        # substantive implementation correctness or operator release authority.
        run = APIS[project].prepare(self.root, repo=REPO, label="test-seed")
        def check(run, stage, **kwargs):
            return self.assessor(passed=stage != task)(run, stage, **kwargs)
        validate_seed(project, task, run, repo=REPO, allow_host_execution=True, assessor=check)
        return run

    def test_versioned_bundles_cover_both_projects_and_six_tasks(self):
        for project in APIS:
            bundle = load_canonical(project, REPO)
            self.assertEqual(bundle, canonical(project, REPO))
            self.assertEqual([t["id"] for t in bundle["tasks"]], [f"T0{i}" for i in range(1, 7)])
            self.assertFalse(bundle["authorization"]["execution_authority"])
            self.assertEqual(bundle["reference_review_status"], "HUMAN_REVIEW_PENDING")
            self.assertEqual(bundle["authorization"]["exceptions"], [])
            for task in bundle["tasks"]:
                self.assertIn(task["id"], task["assigned_task"])
                self.assertTrue(task["acceptance_requirements"])
                self.assertTrue(task["writable_paths"])

    def test_equivalent_inputs_and_independent_workspace_copies(self):
        for project in APIS:
            for task in [f"T0{i}" for i in range(1, 7)]:
                seed = self.seed(project, task)
                a = self.prepare(project, "ISOLATED_TASK", task=task, seed_run=seed)
                b = self.prepare(project, "ISOLATED_TASK", task=task, seed_run=seed)
                self.assertEqual(verify_worker(a, REPO)["input_sha256"], verify_worker(b, REPO)["input_sha256"])
                (a / "workspace/tests/test_candidate.py").write_text("# candidate A", encoding="utf-8")
                self.assertEqual(snapshot(b / "workspace"), snapshot(seed / "workspace"))

    def test_prevalidated_seed_blocks_failed_or_changed_prerequisites(self):
        seed = self.seed()
        validation = seed / "seed-validation.json"
        record = json.loads(validation.read_text())
        record["prevalidated"] = False
        write_json(validation, record)
        with self.assertRaisesRegex(ValueError, "Seed prerequisites"):
            self.prepare(mode="ISOLATED_TASK", task="T02", seed_run=seed)
        record["prevalidated"] = True
        write_json(validation, record)
        (seed / "workspace/README.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Seed prerequisites"):
            self.prepare(mode="ISOLATED_TASK", task="T02", seed_run=seed)
        with self.assertRaises(ValueError):
            self.prepare(seed_run=seed)

    def test_validation_cannot_make_target_failure_into_unsolved_signoff(self):
        seed = APIS["assistant-001"].prepare(self.root, repo=REPO)
        result = validate_seed("assistant-001", "T02", seed, repo=REPO,
                               allow_host_execution=True, assessor=self.assessor(False))
        self.assertFalse(result["prevalidated"])
        self.assertEqual(result["target_unsolved_review"], "HUMAN_REVIEW_PENDING")
        second = APIS["assistant-001"].prepare(self.root, repo=REPO)
        result = validate_seed("assistant-001", "T01", second, repo=REPO,
            allow_host_execution=True, assessor=self.assessor(False, "assessor_result_missing_or_invalid"))
        self.assertFalse(result["prevalidated"])

    def test_provenance_rejects_model_simulation_wrong_digest_and_wrong_inputs(self):
        run = self.prepare()
        for origin in ("candidate_governor", "synthetic_approval"):
            path, sha = self.grant(run, origin)
            with self.assertRaises(ValueError):
                authorize(verify_worker(run, REPO), path, sha)
        path, sha = self.grant(run)
        with self.assertRaises(ValueError):
            authorize(verify_worker(run, REPO), path, "0" * 64)
        value = json.loads(path.read_text()); value["input_sha256"] = "wrong"
        write_json(path, value)
        with self.assertRaises(ValueError):
            authorize(verify_worker(run, REPO), path, digest(path))
        with self.assertRaises(ValueError):
            run_worker(run, lambda **k: self.fail("must not dispatch"), repo=REPO)

    def test_seed_review_cannot_be_replaced_by_reference_approval(self):
        run = self.prepare(mode="ISOLATED_TASK", task="T02", seed_run=self.seed())
        path, sha = self.grant(run)
        value = json.loads(path.read_text()); value.pop("target_unsolved_review")
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "unsolved-target"):
            authorize(verify_worker(run, REPO), path, digest(path))

    def test_scope_failure_blocks_successors_without_running_assessor(self):
        run = self.prepare()
        def sessions(**kwargs):
            (kwargs["workspace"] / "CONTRACT.md").write_text("scope breach", encoding="utf-8")
            return {"status": "success", "final_response": "claimed pass"}
        result = self.execute(run, sessions, through="T02", assessor=lambda *a, **k: self.fail("scope must block execution"))
        self.assertEqual([r["failure_attribution"] for r in result["results"]], ["scope", "predecessor"])
        self.assertEqual(result["results"][1]["assessment_outcome"], "unknown")

    def test_cumulative_uses_candidate_predecessor_and_never_inserts_reference(self):
        for project in APIS:
            run = self.prepare(project)
            before = snapshot(run / "workspace")
            observed = []
            def sessions(**kwargs):
                target = kwargs["workspace"] / "tests/test_candidate.py"
                observed.append((target.read_text(), kwargs["prompt"]))
                target.write_text("# real candidate predecessor", encoding="utf-8")
                return {"status": "success", "final_response": "actual candidate handoff"}
            result = self.execute(run, sessions, through="T02", assessor=self.assessor())
            self.assertEqual(observed[1][0], "# real candidate predecessor")
            self.assertIn("actual candidate handoff", observed[1][1])
            link = json.loads((run / "canonical-handoffs/T02/canonical-handoff.json").read_text())
            self.assertNotEqual(link["starting_workspace_sha256"], before)
            self.assertEqual(link["previous_handoff_origin"], "actual_candidate")
            self.assertEqual(result["worker_mode"], "CUMULATIVE_PROJECT")
            self.assertTrue(result["passed"])

    def test_isolated_failure_retains_code_seed_and_runs_only_assigned_task(self):
        seed = self.seed()
        before = snapshot(seed / "workspace")
        run = self.prepare(mode="ISOLATED_TASK", task="T02", seed_run=seed)
        seen = []
        def sessions(**kwargs):
            seen.append(kwargs["case_id"])
            (kwargs["workspace"] / "tests/test_candidate.py").write_text("# failed candidate", encoding="utf-8")
            return {"status": "success", "final_response": "candidate failure"}
        result = self.execute(run, sessions, assessor=self.assessor(False))
        self.assertEqual(seen, ["assistant001-t02"])
        self.assertEqual(result["results"][0]["failure_attribution"], "worker")
        self.assertEqual(snapshot(seed / "workspace"), before)
        self.assertEqual((run / "workspace/tests/test_candidate.py").read_text(), "# failed candidate")

    def test_infrastructure_failure_is_unknown_and_blocks_successors(self):
        run = self.prepare()
        def sessions(**kwargs):
            raise RuntimeError("fake transport unavailable")
        result = self.execute(run, sessions, through="T02", assessor=self.assessor())
        self.assertEqual([r["failure_attribution"] for r in result["results"]], ["infrastructure", "predecessor"])
        self.assertEqual(result["results"][0]["assessment_outcome"], "unknown")

    def test_input_tampering_and_repeated_trial_block(self):
        run = self.prepare()
        (run / "workspace/README.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "starting workspace"):
            self.execute(run, lambda **k: self.fail("must not run"), assessor=self.assessor())
        with self.assertRaisesRegex(ValueError, "protected benchmark"):
            prepare_worker("assistant-001", "CUMULATIVE_PROJECT",
                REPO / "project-benchmarks/assistant-002/v1", repo=REPO)
        fresh = self.prepare()
        self.execute(fresh, lambda **k: {"status": "success", "final_response": "handoff"},
                     through="T01", assessor=self.assessor())
        with self.assertRaisesRegex(ValueError, "fresh prepared"):
            self.execute(fresh, lambda **k: self.fail("must not rerun"), assessor=self.assessor())

    def test_cli_blocks_before_provider_construction(self):
        from localbench.qualification_v2.__main__ import main
        with patch("localbench.assistant001.runtime.OllamaSessions", side_effect=AssertionError("provider contacted")):
            self.assertEqual(main(["worker", "run", "--project", "assistant-001", "--model", "fake",
                                   "--run-dir", str(self.prepare())]), 2)

    def test_shared_writer_preserves_modes_provenance_and_unknown_failures(self):
        import csv
        from localbench.assistant001.cli import review_package
        run = self.prepare()
        result = self.execute(run, lambda **k: {"status": "success", "final_response": "claim"},
            through="T02", assessor=self.assessor(False, "assessor_timeout"))
        review_package(run, result, "deterministic-fixture-only", "controlled-worker", 32768)
        package = json.loads((run / "review/review-package.json").read_text())
        rows = package["case_results"]
        self.assertEqual(rows[0]["worker_mode"], "CUMULATIVE_PROJECT")
        self.assertEqual(rows[0]["failure_attribution"], "infrastructure")
        self.assertIsNone(rows[0]["deterministic_passed"])
        self.assertEqual(rows[1]["failure_attribution"], "predecessor")
        self.assertEqual(package["role_summary"][0]["deterministic_evaluated"], 0)
        self.assertTrue(rows[0]["authorization_sha256"])
        with (run / "review/case-results.csv").open(encoding="utf-8-sig", newline="") as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual(exported[0]["worker_mode"], rows[0]["worker_mode"])
        self.assertEqual(exported[0]["reference_bundle_sha256"], rows[0]["reference_bundle_sha256"])
        self.assertTrue((run / "review/review-package.xlsx").is_file())


if __name__ == "__main__":
    unittest.main()
