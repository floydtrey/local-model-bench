"""Deterministic packet/workflow tests; no real models or production services."""
from __future__ import annotations
import contextlib
from functools import partial
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
from localbench.assistant001.assessment import assess
from localbench.assistant001.campaign import run_probe, run_worker_chain
from localbench.assistant002 import packet as api
from localbench.assistant002.calibration import install_reference, self_test
from localbench.assistant002.cli import main


class FakeSessions:
    """Writes trusted reference fixtures only for controller tests, not evaluation."""
    def __init__(self, root, fail_task=None, empty_handoff=False):
        self.reference=install_reference(Path(root)/'reference')
        self.calls=[]; self.fail_task=fail_task; self.empty_handoff=empty_handoff

    def __call__(self, *, role, case_id, prompt, workspace, writable, evidence):
        task=case_id[-3:].upper(); self.calls.append((task,workspace,prompt,role))
        evidence=Path(evidence); evidence.mkdir(parents=True,exist_ok=False)
        if role=='worker' and task!=self.fail_task:
            for path in writable:
                source=self.reference/path
                if source.is_file(): shutil.copyfile(source,Path(workspace)/path)
        final='' if self.empty_handoff else f'Actual free prose from {case_id}. Tests and limits belong here.'
        (evidence/'final.txt').write_text(final,encoding='utf-8')
        return dict(status='success',stop_reason='terminal_output',final_response=final,metrics={},authority_violations=0)


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='a002-tests-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_prepare_validate_are_offline_and_candidate_is_unsolved(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No child process expected')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('No provider expected')):
            packet,_=api.validate_packet(); run=api.prepare(self.root)
            with contextlib.redirect_stdout(io.StringIO()) as out: code=main(['validate'])
        self.assertEqual(code,0); self.assertEqual(json.loads(out.getvalue())['model_calls'],0)
        self.assertEqual(packet['packet_id'],'assistant-002-v1')
        self.assertFalse((run/'workspace/assessor').exists())
        self.assertFalse((run/'workspace/assistant_journal').exists())
        self.assertIn('NotImplementedError',(run/'workspace/assistant_simulator/replay.py').read_text())
        self.assertTrue((run/'workspace/assistant_simulator/event_contract.py').is_file())
        self.assertEqual(len(list((run/'workspace/scenarios').glob('*.json'))),8)

    def test_reference_and_twelve_negative_controls(self):
        result=self_test()
        self.assertTrue(result['passed'],json.dumps(result,indent=2))
        self.assertEqual(len(result['checks']),14)
        self.assertEqual(result['checks'][0]['checks_executed'],len(api.expected_check_ids('T06')))
        self.assertEqual(result['real_models_started'],0)

    def test_stage_inventories_are_cumulative_distinct_and_nonempty(self):
        previous=set()
        for i in range(1,7):
            current=api.expected_check_ids(f'T0{i}')
            self.assertGreater(len(current),len(previous)); self.assertTrue(previous<set(current))
            self.assertEqual(len(current),len(set(current))); previous=set(current)
        self.assertEqual(len(previous),96)

    def test_run_identity_separation_and_unique_directories(self):
        one,two=api.prepare(self.root),api.prepare(self.root)
        self.assertNotEqual(one,two)
        record=json.loads((one/'run.json').read_text());record['packet_id']='assistant-001-v1'
        api.write_json(one/'run.json',record)
        with self.assertRaises(ValueError): api.read_run(one)

    def test_frozen_contract_tamper_rejected(self):
        repo=self.root/'repo'; target=repo/'project-benchmarks/assistant-002/v1'
        shutil.copytree(api.packet_root(),target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        (target/'CONTRACT.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'integrity'):api.validate_packet(repo)

    def test_frozen_output_scope_and_bad_label_rejected(self):
        with self.assertRaises(ValueError):api.prepare(api.packet_root()/'runs')
        with self.assertRaises(ValueError):api.prepare(self.root,label='../bad')

    def test_host_execution_acknowledgement_precedes_provider_use(self):
        factory=Mock(side_effect=AssertionError('Must not start provider'))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['run','--model','fixture:only'],sessions_factory=factory),2)
        factory.assert_not_called()
        run=api.prepare(self.root)
        with self.assertRaisesRegex(ValueError,'not OS-sandboxed'):
            assess(run,packet_api=api)

    def test_scope_violation_blocks_before_candidate_execution(self):
        run=api.prepare(self.root);(run/'workspace/CONTRACT.md').write_text('tampered')
        with patch('subprocess.Popen',side_effect=AssertionError('Must not execute')):
            result,_=assess(run,'T01',allow_host_execution=True,packet_api=api)
        self.assertFalse(result['passed']);self.assertEqual(result['status'],'scope_failure')

    def test_unsolved_starter_cannot_pass(self):
        run=api.prepare(self.root)
        result,_=assess(run,'T01',allow_host_execution=True,packet_api=api)
        self.assertFalse(result['passed']);self.assertEqual(result['status'],'completed')
        self.assertEqual(result['executed'],len(api.expected_check_ids('T01')))

    def test_omitted_check_cannot_be_reported_as_complete(self):
        run=api.prepare(self.root)
        def fake_launch(command,**kwargs):
            path=Path(command[command.index('--result')+1])
            row=dict(case_id='invented-test',passed=True)
            api.write_json(path,dict(contract='assistant-002-v1',task='T01',passed=True,status='completed',
                                    checks=[row],planned=1,executed=1))
            return Mock(returncode=0,poll=Mock(return_value=0))
        with patch('localbench.assistant001.assessment.subprocess.Popen',side_effect=fake_launch):
            result,_=assess(run,'T01',allow_host_execution=True,packet_api=api)
        self.assertFalse(result['passed']);self.assertEqual(result['status'],'assessor_result_missing_or_invalid')

    def test_task_handoff_is_not_parsed_into_a_fixed_form(self):
        run=api.prepare(self.root); prose='This is useful prose without a Handoff note field.'
        text=api.task_prompt(run,'T02',prose)
        self.assertIn(prose,text);self.assertNotIn('WORKER_READY',text)
        self.assertNotIn('assessor/reference',text)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='a002-flow-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.run=api.prepare(self.root/'runs')

    def execute(self,sessions,through='T06'):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_worker_chain(self.run,sessions,through=through,allow_host_execution=True,
                                    packet_api=api,assessor=partial(assess,packet_api=api))

    def test_shared_worker_engine_builds_all_six_stages(self):
        sessions=FakeSessions(self.root);result=self.execute(sessions)
        self.assertTrue(result['passed'],json.dumps(result,indent=2));self.assertEqual(len(sessions.calls),6)
        self.assertEqual(result['campaign'],'assistant-002-v1')
        self.assertTrue(all(r['case_id'].startswith('assistant002-') for r in result['results']))
        for previous,current in zip(sessions.calls,sessions.calls[1:]):
            self.assertEqual(previous[1],current[1])
            self.assertIn(f'Actual free prose from assistant002-{previous[0].lower()}',current[2])
        self.assertTrue((self.run/'roles/worker/T06/handoff-link.json').is_file())

    def test_failed_stage_blocks_successors_without_reference_continuation(self):
        sessions=FakeSessions(self.root,fail_task='T02');result=self.execute(sessions)
        self.assertFalse(result['passed']);self.assertEqual(len(sessions.calls),2)
        self.assertTrue(all(r['status']=='blocked' for r in result['results'][2:]))
        self.assertIn('NotImplementedError',(self.run/'workspace/assistant_simulator/schedule.py').read_text())

    def test_empty_handoff_blocks_despite_correct_code(self):
        sessions=FakeSessions(self.root,empty_handoff=True);result=self.execute(sessions,through='T02')
        self.assertFalse(result['passed']);self.assertEqual(len(sessions.calls),1)
        self.assertFalse(result['results'][0]['handoff_present'])

    def test_previous_summary_is_never_overwritten(self):
        sessions=FakeSessions(self.root);self.execute(sessions,'T01')
        before=(self.run/'summary.json').read_bytes()
        with self.assertRaises(ValueError):self.execute(sessions,'T01')
        self.assertEqual((self.run/'summary.json').read_bytes(),before)

    def test_advisory_planner_probe_uses_new_packet_and_preserves_source(self):
        target=api.prepare(self.root/'probes');sessions=FakeSessions(self.root)
        before=api.snapshot(self.run/'workspace')
        result=run_probe(target,self.run,sessions,role='planner',packet_api=api)
        self.assertEqual(result['campaign'],'assistant-002-v1')
        self.assertEqual(api.snapshot(self.run/'workspace'),before)
        self.assertIn('ASSISTANT-002',sessions.calls[0][2])
        self.assertIsNone(sessions.calls[0][1])
        self.assertIsNone(result['results'][0]['deterministic_passed'])

    def test_probe_does_not_skip_governance_or_host_execution_gate(self):
        target=api.prepare(self.root/'probes');sessions=FakeSessions(self.root)
        with self.assertRaisesRegex(ValueError,'actual --plan-file'):
            run_probe(target,self.run,sessions,role='governor',packet_api=api)
        with self.assertRaisesRegex(ValueError,'host-execution'):
            run_probe(target,self.run,sessions,role='tester',packet_api=api)
        self.assertEqual(sessions.calls,[])

    def test_default_packet_adapter_remains_assistant001(self):
        # Omission retains A001 validation rather than silently accepting A002 runs.
        with self.assertRaises((ValueError,OSError)):
            run_worker_chain(self.run,FakeSessions(self.root),through='T01',allow_host_execution=True)


if __name__=='__main__':
    unittest.main()
