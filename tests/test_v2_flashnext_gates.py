"""Gate attacks against real V2 evidence from a synthetic local HTTP runtime.

All source packs, evaluators and bounded tools are real. Responses are fixtures;
these tests make no statement about Flash-Next ability and load no model.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from localbench.v2 import flashnext_campaign as campaign
from localbench.v2.contracts import SealedEvidence, canonical_json_bytes, seal_evidence, sha256_json
from localbench.v2.flashnext_gates import verify_gate
from localbench.v2.flashnext_runtime import FlashNextBlocked, file_digest

from test_v2_flashnext_campaign import ROOT, _FixtureEndpoint, _foundation, _profile, _run_chain


def _json(path):
    return json.loads(path.read_bytes())


def _write(path, value):
    path.write_bytes(canonical_json_bytes(value))


def _gate_edit(root, mutate):
    value = _json(root / "gate.json")
    mutate(value["payload"])
    value["sha256"] = sha256_json(value["payload"])
    _write(root / "gate.json", value)


def _ref_key(value):
    return value["record_type"], value["logical_id"], value["sha256"]


def _edit_record(root, record_type, mutate, *, choose=lambda record: True):
    """Reseal a changed record and every referring record, leaving no bad hash.

    Negative tests must exercise semantic closure, not stop at the envelope
    digest. Preserve the original store copies of equivalent foundation records.
    """
    gate = _json(root / "gate.json")["payload"]
    old = [(item["path"], SealedEvidence.from_dict(_json(root / item["path"]))) for item in gate["evidence"]]
    current = {record.sha256: record for _, record in old}
    target = next(record for record in current.values() if record.record_type == record_type and choose(record))
    payload = json.loads(canonical_json_bytes(target.payload))
    mutate(payload)
    changed = seal_evidence(target.record_type, target.logical_id, payload)
    replacements = {_ref_key(target.reference.to_dict()): changed.reference.to_dict()}
    current[target.sha256] = changed

    def replace(value):
        if isinstance(value, dict):
            if set(value) == {"record_type", "logical_id", "sha256"}:
                return replacements.get(_ref_key(value), value)
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    for _ in range(len(current) + 1):
        updated = False
        for old_sha, record in list(current.items()):
            payload = replace(json.loads(canonical_json_bytes(record.payload)))
            revised = seal_evidence(record.record_type, record.logical_id, payload)
            if revised.sha256 != record.sha256:
                replacements[_ref_key(record.reference.to_dict())] = revised.reference.to_dict()
                # References can still use the original form several edges away.
                for key, value in list(replacements.items()):
                    if _ref_key(value) == _ref_key(record.reference.to_dict()):
                        replacements[key] = revised.reference.to_dict()
                current[old_sha] = revised
                updated = True
        if not updated:
            break
    else:
        raise AssertionError("test record mutation unexpectedly contains a cycle")
    for relative, _ in old:
        (root / relative).unlink()
    references = []
    for relative, record in old:
        revised = current[record.sha256]
        path = root / Path(relative).parent / f"{revised.sha256}.json"
        _write(path, revised.to_dict())
        references.append({"path": path.relative_to(root).as_posix(), "reference": revised.reference.to_dict()})
    _gate_edit(root, lambda payload: payload.update(evidence=references))


def _refresh_artifacts(root):
    artifacts = [{"path": path.relative_to(root).as_posix(), "sha256": file_digest(path), "bytes": path.stat().st_size}
                 for path in sorted(root.rglob("*")) if path.is_file()
                 and ({"runtime", "raw"} & set(path.relative_to(root).parts))]
    _gate_edit(root, lambda payload: payload.update(artifact_files=artifacts))


def _rewrite_raw_response(root, mutate):
    observation = next(root.glob("l0/observations/*/raw/*/observation.json"))
    metadata = _json(observation)
    response = observation.parent / "response.body"
    raw = _json(response)
    mutate(raw)
    _write(response, raw)
    metadata["artifacts"]["response_body"].update(sha256=file_digest(response), size_bytes=response.stat().st_size)
    _write(observation, metadata)

    def update_trace(payload):
        payload["response"]["provider_metadata"]["artifacts"] = metadata["artifacts"]

    _edit_record(root, "intrinsic_execution_trace", update_trace,
                 choose=lambda record: record.payload["case_id"] == metadata["case_id"])
    _refresh_artifacts(root)


class FlashNextGateClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.TemporaryDirectory()
        cls.chain = _run_chain(Path(cls.storage.name) / "chain")
        cls.fingerprint = cls.chain["foundation"]["fingerprint"]

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def copied(self, stage="smoke"):
        source = self.chain["smoke_dir" if stage == "smoke" else "shared_dir"]
        path = self.root / stage
        shutil.copytree(source, path)
        return path

    def rejected(self, path, stage="smoke"):
        with self.assertRaises(FlashNextBlocked):
            verify_gate(path, stage=stage, fingerprint=self.fingerprint, repo_root=ROOT)

    def test_real_v2_smoke_and_full_shared_with_parent_verify(self):
        for stage, key in (("smoke", "smoke_dir"), ("shared-screen", "shared_dir")):
            result = verify_gate(self.chain[key], stage=stage, fingerprint=self.fingerprint, repo_root=ROOT)
            self.assertEqual(result["status"], "pass")
            self.assertFalse(result["role_or_model_qualified"])
        # Four execution-host copies plus the independent BL-3 stability capture
        # are legitimate. The second capture has a distinct identity but same facts.
        refs = self.chain["smoke_gate"]["evidence"]
        hosts = [item for item in refs if item["reference"]["record_type"] == "host_profile"]
        self.assertEqual(len(hosts), 5)
        self.assertEqual(len({item["reference"]["sha256"] for item in hosts}), 2)
        self.assertEqual(sum(item["reference"]["logical_id"] == "flashnext-host-capture-1" for item in hosts), 4)
        self.assertEqual(sum(item["reference"]["logical_id"] == "flashnext-host-capture-2" for item in hosts), 1)
        self.assertEqual({
            _json(self.chain["smoke_dir"] / item["path"])["payload"]["facts_sha256"] for item in hosts
        }, {self.fingerprint["host_facts_sha256"]})

    def test_gate_rejects_unsupported_stage_and_wrong_fingerprint(self):
        with self.assertRaises(FlashNextBlocked):
            verify_gate(self.chain["smoke_dir"], stage="roles", fingerprint=self.fingerprint)
        with self.assertRaises(FlashNextBlocked):
            verify_gate(self.chain["smoke_dir"], stage="smoke", fingerprint={**self.fingerprint, "model_sha256": "f" * 64})

    def test_duplicate_case_trial_or_evaluation_reference_is_rejected(self):
        for kind in ("case_result", "trial_identity", "evaluation_result"):
            with self.subTest(kind=kind):
                path = self.root / kind
                shutil.copytree(self.chain["smoke_dir"], path)
                def duplicate(payload):
                    items = [item for item in payload["evidence"] if item["reference"]["record_type"] == kind]
                    replacement = items[0]
                    payload["evidence"] = [replacement if item in items else item for item in payload["evidence"]]
                _gate_edit(path, duplicate)
                self.rejected(path)

    def test_missing_reference_cannot_be_hidden_by_resealed_gate(self):
        path = self.copied()
        _gate_edit(path, lambda payload: payload.update(evidence=payload["evidence"][1:]))
        self.rejected(path)

    def test_missing_record_and_reference_breaks_transitive_closure(self):
        path = self.copied()
        gate = _json(path / "gate.json")["payload"]
        removed = next(item for item in gate["evidence"] if item["reference"]["record_type"] == "trial_identity")
        (path / removed["path"]).unlink()
        _gate_edit(path, lambda payload: payload.update(evidence=[item for item in payload["evidence"] if item != removed]))
        self.rejected(path)

    def test_evaluation_for_another_existing_case_cannot_fill_coverage(self):
        path = self.copied()
        case = next(item["reference"] for item in _json(path / "gate.json")["payload"]["evidence"]
                    if item["reference"]["record_type"] == "case_result")
        _edit_record(path, "evaluation_result", lambda payload: payload.update(case=case),
                     choose=lambda record: record.payload["case"]["sha256"] != case["sha256"])
        self.rejected(path)

    def test_foreign_case_identity_is_rejected_after_whole_graph_reseal(self):
        path = self.copied("shared-screen")
        _edit_record(path, "case_result", lambda payload: payload.update(case_id="foreign-but-unique-case"))
        self.rejected(path, "shared-screen")

    def test_trial_cannot_claim_another_case_or_second_ordinal(self):
        for change in ({"case_id": "foreign-case"}, {"ordinal": 2}):
            with self.subTest(change=change):
                path = self.root / str(len(list(self.root.iterdir())))
                shutil.copytree(self.chain["smoke_dir"], path)
                _edit_record(path, "trial_identity", lambda payload: payload.update(change))
                self.rejected(path)

    def test_resealed_successful_case_cannot_hide_execution_failure(self):
        path = self.copied()
        _edit_record(path, "case_result", lambda payload: payload.update(status="protocol_failure"))
        self.rejected(path)

    def test_deterministic_evaluator_replay_rejects_resealed_verdict(self):
        path = self.copied()
        _edit_record(path, "evaluation_result", lambda payload: payload.update(score=0.0))
        self.rejected(path)

    def test_foreign_evaluator_source_identity_is_rejected(self):
        path = self.copied()
        _edit_record(path, "evaluator_identity", lambda payload: payload.update(implementation_sha256="e" * 64))
        self.rejected(path)

    def test_manifest_trial_list_cannot_omit_a_completed_trial(self):
        path = self.copied()
        _edit_record(path, "run_manifest", lambda payload: payload.update(trials=[]))
        self.rejected(path)

    def test_source_pack_and_provenance_must_match_accepted_projection(self):
        for filename in ("pack-input.json", "pack-provenance.json"):
            with self.subTest(filename=filename):
                path = self.root / filename
                shutil.copytree(self.chain["smoke_dir"], path)
                data = _json(path / "l0" / filename)
                data["unapproved_change"] = True
                _write(path / "l0" / filename, data)
                self.rejected(path)

    def test_native_parser_compatibility_unknown_cannot_unlock_shared_gate(self):
        path = self.copied("shared-screen")
        _edit_record(path, "tool_compatibility_observation",
            lambda payload: payload["dimensions"]["protocol_parser_compatibility"].update(status="unknown"))
        self.rejected(path, "shared-screen")

    def test_missing_raw_artifact_entry_is_rejected_even_when_gate_is_resealed(self):
        path = self.copied()
        _gate_edit(path, lambda payload: payload.update(artifact_files=payload["artifact_files"][1:]))
        self.rejected(path)

    def test_raw_artifact_change_is_rejected(self):
        path = self.copied()
        next(path.rglob("response.body")).write_bytes(b"changed raw evidence")
        self.rejected(path)

    def test_raw_sidecar_hash_is_checked_independently_of_gate_inventory(self):
        path = self.copied()
        next(path.rglob("response.body")).write_bytes(b"changed raw evidence")
        _refresh_artifacts(path)
        self.rejected(path)

    def test_resealed_observation_cannot_claim_success_with_raw_truncation(self):
        path = self.copied()
        _rewrite_raw_response(path, lambda raw: raw["choices"][0].update(finish_reason="length"))
        self.rejected(path)

    def test_resealed_observation_cannot_change_raw_runtime_model(self):
        path = self.copied()
        _rewrite_raw_response(path, lambda raw: raw.update(model="another-model"))
        self.rejected(path)

    def test_resealed_observation_cannot_change_raw_assistant_content(self):
        path = self.copied()
        _rewrite_raw_response(path, lambda raw: raw["choices"][0]["message"].update(content="foreign result"))
        self.rejected(path)

    def test_resealed_raw_response_must_obey_adapter_parser_types(self):
        changes = (lambda raw: raw["choices"][0].update(index=False),
                   lambda raw: raw["choices"][0]["message"].update(tool_calls=""))
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                path = self.root / str(index)
                shutil.copytree(self.chain["smoke_dir"], path)
                _rewrite_raw_response(path, change)
                self.rejected(path)

    def test_tool_text_parser_uncertainty_cannot_be_resealed_as_success(self):
        path = self.copied()
        observation = next(path.glob("l2/observations/*/raw/*/observation.json"))
        metadata = _json(observation)
        metadata["tool_text_diagnostic"] = "potential_tool_shaped_prose"
        _write(observation, metadata)
        def change(payload):
            for event in payload["events"]:
                if event["event_type"] == "model_response" and event["payload"]["provider_metadata"]["observation_file"] == metadata["observation_file"]:
                    event["payload"]["provider_metadata"]["tool_text_diagnostic"] = metadata["tool_text_diagnostic"]
                    event["event_sha256"] = sha256_json({key: event[key] for key in ("sequence", "event_type", "payload")})
        _edit_record(path, "tool_execution_trace", change)
        _refresh_artifacts(path)
        self.rejected(path)

    def test_removed_raw_turn_cannot_be_hidden_by_complete_remaining_inventory(self):
        path = self.copied()
        observation = next(path.rglob("observation.json"))
        shutil.rmtree(observation.parent)
        _refresh_artifacts(path)
        self.rejected(path)

    def test_shared_gate_requires_real_smoke_parent_and_matching_digest(self):
        changes = ({"parent_smoke_run": None}, {"parent_smoke_run": "relative/smoke"},
                   {"parent_gate_sha256": "f" * 64})
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                path = self.root / str(index)
                shutil.copytree(self.chain["shared_dir"], path)
                _gate_edit(path, lambda payload: payload.update(change))
                self.rejected(path, "shared-screen")

    def test_shared_gate_rejects_cycle_and_tampered_parent_raw_evidence(self):
        path = self.copied("shared-screen")
        _gate_edit(path, lambda payload: payload.update(parent_smoke_run=str(path.resolve())))
        self.rejected(path, "shared-screen")
        parent = self.copied()
        next(parent.rglob("response.body")).write_bytes(b"parent runtime evidence changed")
        _gate_edit(path, lambda payload: payload.update(parent_smoke_run=str(parent.resolve())))
        self.rejected(path, "shared-screen")

    def test_smoke_gate_rejects_parent_even_if_parent_hash_is_present(self):
        path = self.copied()
        _gate_edit(path, lambda payload: payload.update(parent_smoke_run=str(path), parent_gate_sha256="f" * 64))
        self.rejected(path)

    def test_shared_correctness_failure_stays_separate_from_runtime_compatibility(self):
        # This case is absent from smoke. The runtime and native tools work;
        # only the accepted deterministic answer check fails on shared screen.
        with _FixtureEndpoint(incorrect_case="code-diagnosis") as (_, url):
            smoke, shared = self.root / "incorrect-smoke", self.root / "incorrect-shared"
            foundation = _foundation(url, smoke)
            smoke_result = campaign.run_shared(repo_root=ROOT, output_dir=smoke, foundation=foundation,
                profile=_profile(), server=None, stage="smoke", progress=lambda _: None)
            smoke_gate = campaign.create_gate(output_dir=smoke, stage="smoke", foundation=foundation, result=smoke_result)
            foundation = _foundation(url, shared)
            shared_result = campaign.run_shared(repo_root=ROOT, output_dir=shared, foundation=foundation,
                profile=_profile(), server=None, stage="shared-screen", progress=lambda _: None)
            campaign.create_gate(output_dir=shared, stage="shared-screen", foundation=foundation, result=shared_result,
                                 parent_gate=smoke_gate, parent_smoke_run=smoke)
        result = verify_gate(shared, stage="shared-screen", fingerprint=foundation["fingerprint"], repo_root=ROOT)
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["correctness_all_pass"])
        self.assertFalse(result["role_or_model_qualified"])


if __name__ == "__main__":
    unittest.main()
