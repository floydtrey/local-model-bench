from pathlib import Path
import json
import os
import tempfile
import unittest

from localbench.database_v2 import connect
from localbench.database_v2.publication import CasePublisher
from localbench.database_v2.native_v2 import NativeV2Publisher
from localbench.database_v2.store import wal_runtime_safe
from localbench.v2 import DriverBinding, EvidenceStore, ModelTurnResponse, OrchestrationBlocked, run_v2_pack, ToolCall, WorkspaceBinding
from localbench.v2.repetition import run_v2_repetitions
import test_v2_orchestrator as fixture
import test_v2_repetition_reporting as repetition_fixture


class NativePublicationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        validation=not wal_runtime_safe()
        if os.environ.get('LOCALBENCH_REQUIRE_OPERATIONAL_DB')=='1': self.assertFalse(validation)
        self.db=connect(self.root/'native.sqlite3',validation_only=validation); self.addCleanup(self.db.close)
        self.pub=CasePublisher(self.db,self.root/'published',clock=lambda:'now',validation_only=validation)
        self.store=EvidenceStore(self.root/'native')
        self.adapter=NativeV2Publisher(self.pub,self.store,origin='synthetic_test',report_path=self.root/'partial.json')
        self.helper=fixture.BL8AOrchestratorTests()

    def run_pack(self, driver, *, registry=None, source=None):
        host,runtime,model=self.helper.foundation()
        return run_v2_pack(run_id='native-fixture',pack_source=source or fixture.pack_bytes(level='L0'),
            pack_source_locator=None,host=host,runtime=runtime,model=model,
            configuration_bindings={'profile-a':self.helper.config(tools=False)},
            evaluator_registry=registry or self.helper.registry('intrinsic_execution_trace'),
            driver_binding=DriverBinding('fixture-driver',fixture.DRIVER_DIGEST,driver),
            evidence_store=self.store,harness_source={'kind':'fixture','commit':fixture.DIGEST_B},
            clock=lambda:'2026-10-09T00:00:00Z',case_publisher=self.adapter)

    def count(self,table): return self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def test_native_pack_publishes_before_next_case_and_partial_projection(self):
        source=json.loads(fixture.pack_bytes(level='L0'))
        second=json.loads(json.dumps(source['cases'][0])); second['case_id']='case-b'; source['cases'].append(second)
        calls=[]
        def driver(request):
            self.assertEqual(self.count('committed_results'),len(calls))
            if calls: self.assertEqual(json.loads((self.root/'partial.json').read_bytes())['committed_results'],1)
            calls.append(request.case_id)
            return ModelTurnResponse(content='exact response')
        result=self.run_pack(driver,source=json.dumps(source).encode())
        self.assertEqual(calls,['case-a','case-b']); self.assertEqual(self.count('committed_results'),2)
        self.assertEqual([r[0] for r in self.db.execute('SELECT outcome FROM committed_results')],['PASS','PASS'])
        self.assertEqual(self.count('queue_snapshots'),0)
        self.assertEqual(len(result.evaluation_results),2)
        self.assertEqual(len(self.pub.projection()['rows']),2)
        self.assertEqual(self.pub.recover()[0]['disposition'],'preserved')

    def test_native_driver_error_durably_publishes_unassessed_and_preserves_native_stop(self):
        def driver(request): raise RuntimeError('deterministic capture failure')
        with self.assertRaises(OrchestrationBlocked): self.run_pack(driver)
        self.assertEqual(self.count('committed_results'),1)
        self.assertEqual(self.count('assessments'),0)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))
        row=self.pub.projection()['rows'][0]
        self.assertEqual(row['execution_status'],'error')
        self.assertIn('unavailable',row['adapter_exclusion_reason'])

    def test_native_assessor_failure_commits_execution_without_inventing_assessment(self):
        registry=self.helper.registry('intrinsic_execution_trace')
        def unavailable(*args,**kwargs): raise RuntimeError('assessor unavailable')
        registry.evaluate=unavailable
        with self.assertRaises(RuntimeError): self.run_pack(lambda request:ModelTurnResponse(content='raw'),registry=registry)
        self.assertEqual(self.count('committed_results'),1)
        self.assertEqual(self.count('assessments'),0)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))

    def test_native_protocol_failure_and_failed_assessment_are_not_process_qualification(self):
        self.run_pack(lambda request:None)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))
        self.assertEqual(self.db.execute('SELECT outcome FROM assessments').fetchone(),('FAIL',))

    def test_repetition_trials_preserve_ordinals_and_publish_while_battery_continues(self):
        host,runtime,model=repetition_fixture.foundation()
        calls=[]
        def driver(request):
            self.assertEqual(self.count('committed_results'),len(calls)); calls.append(request)
            return ModelTurnResponse(content='good')
        run=run_v2_repetitions(run_id='repeat-fixture',repetition_phase='screen',
            pack_source=repetition_fixture.pack_bytes(level='L0',screen_trials=2,qualification_trials=4,two_cases=True),
            pack_source_locator=None,host=host,runtime=runtime,model=model,
            configuration_bindings={'profile-a':repetition_fixture.configuration(tools=False)},
            evaluator_registry=repetition_fixture.registry(),driver_binding=DriverBinding('fixture',fixture.DRIVER_DIGEST,driver),
            evidence_store=self.store,harness_source={'kind':'fixture'},clock=lambda:'2026-10-09T00:00:00Z',
            case_publisher=self.adapter)
        self.assertEqual(self.count('committed_results'),5)
        self.assertEqual(sorted(r[0] for r in self.db.execute('SELECT ordinal FROM trials')),[1,1,2,2,3])
        self.assertEqual(run.planned_counts,{'case-a':2,'case-b':3})
        self.assertTrue(all(r['assessed_outcome']=='pass' for r in self.pub.projection()['rows']))

    def test_default_native_execution_remains_unwired(self):
        host,runtime,model=self.helper.foundation()
        run_v2_pack(run_id='default-fixture',pack_source=fixture.pack_bytes(level='L0'),pack_source_locator=None,
            host=host,runtime=runtime,model=model,configuration_bindings={'profile-a':self.helper.config(tools=False)},
            evaluator_registry=self.helper.registry('intrinsic_execution_trace'),
            driver_binding=DriverBinding('fixture',fixture.DRIVER_DIGEST,lambda request:ModelTurnResponse(content='raw')),
            evidence_store=self.store,harness_source={'kind':'fixture'},clock=lambda:'2026-10-09T00:00:00Z')
        self.assertEqual(self.count('attempts'),0); self.assertEqual(self.count('committed_results'),0)

    def test_l1_context_bytes_are_preserved_inside_exact_native_trace(self):
        host,runtime,model=self.helper.foundation()
        data=b'authored context bytes'
        asset={'asset_id':'context','sha256':fixture.sha(data),'media_type':'text/plain','delivery':'inline_context','source_locator':'fixture.txt'}
        run_v2_pack(run_id='l1-fixture',pack_source=fixture.pack_bytes(level='L1',asset=asset),pack_source_locator=None,
            host=host,runtime=runtime,model=model,configuration_bindings={'profile-a':self.helper.config(tools=False)},
            evaluator_registry=self.helper.registry('intrinsic_execution_trace'),
            driver_binding=DriverBinding('fixture',fixture.DRIVER_DIGEST,lambda request:ModelTurnResponse(content='raw')),
            evidence_store=self.store,harness_source={'kind':'fixture'},clock=lambda:'2026-10-09T00:00:00Z',asset_loader=lambda descriptor:data,
            case_publisher=self.adapter)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('PASS',))
        captures=[(self.pub.root/path[0]).read_bytes() for path in self.db.execute("SELECT ar.relative_path FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE purpose='execution'")]
        self.assertTrue(any(data in raw for raw in captures))

    def test_l2_author_controlled_tool_bytes_and_final_files_are_published(self):
        host,runtime,model=self.helper.foundation(); interface=self.helper.execution_interface(runtime,model)
        workspace=self.root/'workspace'; workspace.mkdir(); (workspace/'input.txt').write_bytes(b'authored input')
        def driver(request):
            if request.turn==1: return ModelTurnResponse(tool_calls=(ToolCall('read','read_file',{'path':'input.txt'}),))
            if request.turn==2: return ModelTurnResponse(tool_calls=(ToolCall('write','write_file',{'path':'out.txt','content':'authored output','expected_sha256':None}),))
            return ModelTurnResponse(content='finished')
        run_v2_pack(run_id='l2-fixture',pack_source=fixture.pack_bytes(level='L2'),pack_source_locator=None,
            host=host,runtime=runtime,model=model,configuration_bindings={'profile-a':self.helper.config(tools=True)},
            evaluator_registry=self.helper.registry('tool_execution_trace'),
            driver_binding=DriverBinding('fixture',fixture.DRIVER_DIGEST,driver,execution_interface=interface),
            evidence_store=self.store,harness_source={'kind':'fixture'},clock=lambda:'2026-10-09T00:00:00Z',
            workspaces={'case-a':WorkspaceBinding(root=workspace,readable_paths=('input.txt',),writable_paths=('out.txt',))},case_publisher=self.adapter)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('PASS',))
        paths=self.db.execute("SELECT ar.relative_path FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE purpose='tool_file:out.txt'").fetchall()
        self.assertEqual(len(paths),1); self.assertEqual((self.pub.root/paths[0][0]).read_bytes(),b'authored output')


if __name__=='__main__': unittest.main()
