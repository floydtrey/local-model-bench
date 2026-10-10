import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_case_publication as foundation
from localbench.database_v2.native_rows import NativeRowPublisher
from localbench.v2.report_adapter import file_reference


class NativeRowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=foundation.PublicationTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root; self.db=self.fixture.db; self.pub=self.fixture.pub
        self.adapter=NativeRowPublisher(self.pub,report_path=self.root/'projection.json')
        self.native=self.root/'native'; self.native.mkdir()

    def register(self,key,case='C01',binding=None,configuration=None,trial='trial'):
        self.adapter.register(key,trial_id=trial,source_id='source',case_id=case,assessment_binding=binding,configuration_binding=configuration)

    def test_exact_native_row_preserves_assessment_and_raw_capture(self):
        key=('fixture',str(self.native),'C01',1)
        self.register(key,binding={'case_id':'C01','_assessor_id':'assessor'},configuration={'config_id':'config','row_fields':{'effective_settings':{'context':4096}}})
        self.adapter.started(key=key)
        session=self.native/'execution'; session.mkdir(); (session/'raw.bin').write_bytes(b'raw\x00tool')
        assessment=self.native/'assessment.json'; assessment.write_text(json.dumps({'case_id':'C01','assessed_outcome':'PASS'}))
        row={'case_id':'C01','execution_status':'success','assessed_outcome':'PASS',
            'assessment_file':str(assessment),'evidence_directory':str(session),
            'evidence_refs':[file_reference(assessment,'assessment')], 'human_review_required':True,
            'first_pass_passed':True,'repair_attempted':False,'repair_passed':None,'effective_settings':{'context':4096}}
        self.adapter.completed(key=key,row=row,native_root=self.native)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('PASS',))
        self.assertEqual(self.db.execute('SELECT outcome FROM assessments').fetchone(),('PASS',))
        self.assertTrue(any((self.pub.root/p[0]).read_bytes()==b'raw\x00tool' for p in self.db.execute('SELECT relative_path FROM artifacts')))
        self.assertEqual(self.pub.projection()['rows'][0]['first_pass_passed'],True)

    def test_missing_native_metadata_never_becomes_qualification(self):
        key=('legacy',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        path=self.native/'case.json'; path.write_text('{"case_id":"C01","status":"success","attempts":[{"output":"raw"}]}')
        row=json.loads(path.read_bytes())
        self.adapter.completed(key=key,row=row,native_root=self.native,artifact_paths=[path])
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))
        self.assertEqual(self.db.execute('SELECT count(*) FROM assessments').fetchone(),(0,))
        self.assertIn('missing_case_evidence',self.pub.projection()['rows'][0]['adapter_exclusion_reason'])

    def test_blocked_without_session_files_is_durable(self):
        key=('blocked',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        self.adapter.completed(key=key,row={'case_id':'C01','status':'blocked','evidence_directory':str(self.native/'never-executed')},native_root=self.native)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('BLOCKED',))

    def test_row_case_mismatch_and_unregistered_keys_stop_before_execution(self):
        key=('fixture',str(self.native),'C01',1); self.register(key)
        with self.assertRaises(RuntimeError): self.adapter.started(key=('other',))
        self.adapter.started(key=key)
        with self.assertRaises(RuntimeError): self.adapter.completed(key=key,row={'case_id':'wrong'},native_root=self.native)
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_assistant_chain_callback_failure_cannot_advance_dependent_task(self):
        from localbench.assistant001.campaign import run_worker_chain
        from localbench.assistant001 import packet
        from types import SimpleNamespace
        run=self.native
        api=SimpleNamespace(read_run=lambda run,repo:({'packet_id':'assistant-001-v1'},
            {'tasks':[{'id':'T01','title':'one','writable_paths':[]},{'id':'T02','title':'two','writable_paths':[]}]}),
            task_prompt=lambda *args:'fixture input')
        key=('assistant-chain',str(run.resolve()),'assistant001-t01',1)
        self.db.execute("INSERT INTO cases VALUES('chain-case','assistant001-t01','1','source',?,'{}')",('b'*64,))
        self.db.execute("INSERT INTO suite_cases VALUES('suite','chain-case',2)")
        self.db.execute("INSERT INTO trials VALUES('chain-trial','run','suite','chain-case',1,1,'chain','source')")
        self.register(key,case='assistant001-t01',trial='chain-trial')
        calls=[]
        def sessions(**kwargs):
            calls.append(kwargs['case_id']); return {'status':'error','final_response':'raw'}
        def assessor(*args,**kwargs): raise RuntimeError('mock unavailable assessor')
        def fault(boundary):
            if boundary=='before_db_commit': raise RuntimeError('storage failure')
        self.pub.fault=fault
        with patch.object(packet,'snapshot',return_value={}),patch('localbench.assistant001.campaign.snapshot',return_value={}):
            with self.assertRaises(RuntimeError): run_worker_chain(run,sessions,through='T02',allow_host_execution=True,
                assessor=assessor,packet_api=api,case_publisher=self.adapter)
        self.assertEqual(calls,['assistant001-t01'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_committed_native_rows_reuse_T13_first_pass_repair_and_coverage_semantics(self):
        import test_qualification_v2_metrics as metric_fixture
        helper=metric_fixture.MetricProjectionTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        # The native case is an authored T13 fixture; the database only stores it.
        row=helper.case('C01',first_pass_passed=False,repair_attempted=True,repair_passed=True)
        native=helper.root
        (native/'session.json').write_text(json.dumps({'case_id':'C01','status':'completed','origin':'authored_storage_fixture'}))
        first=native/'first-pass.json'; first.write_text('{"case_id":"C01","outcome":"FAIL","attempt":1}')
        repair=native/'repair.json'; repair.write_text('{"case_id":"C01","outcome":"PASS","attempt":2,"parent":1}')
        row['evidence_refs'] += [file_reference(first,'first_pass'),file_reference(repair,'repair')]
        key=('t13-fixture',str(native),'C01',1)
        self.register(key,binding={'case_id':'C01','_assessor_id':'assessor'},configuration={'config_id':'config','row_fields':{'effective_settings':row['effective_settings'],'context_tokens':row['context_tokens']}}); self.adapter.started(key=key)
        self.adapter.completed(key=key,row=row,native_root=native)
        catalog={**helper.catalog,'metrics':[{**helper.catalog['metrics'][0],'cases':['C01','missing']} ]}
        report=self.pub.projection(catalog=catalog)
        metric=report['metrics']['metrics'][0]
        self.assertEqual((metric['numerator'],metric['denominator']),(1,1))
        self.assertEqual(metric['first_pass'],{'numerator':0,'denominator':1})
        self.assertEqual(metric['after_repair'],{'numerator':1,'denominator':1})
        self.assertEqual(metric['missing_coverage'],['missing'])

    def test_native_configuration_mismatch_cannot_commit_pass_or_merge_settings(self):
        key=('configuration-mismatch',str(self.native),'C01',1)
        self.register(key,binding={'case_id':'C01','_assessor_id':'assessor'},configuration={'config_id':'config','row_fields':{'effective_settings':{'context':4096}}})
        self.adapter.started(key=key)
        assessment=self.native/'assessment.json'; assessment.write_text('{"case_id":"C01","assessed_outcome":"PASS"}')
        capture=self.native/'capture.bin'; capture.write_bytes(b'authored capture')
        row={'case_id':'C01','execution_status':'completed','assessed_outcome':'PASS','effective_settings':{'context':8192},
             'assessment_file':str(assessment),'evidence_directory':str(self.native),'evidence_refs':[file_reference(assessment,'assessment')]}
        self.adapter.completed(key=key,row=row,native_root=self.native)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))
        self.assertEqual(self.db.execute('SELECT count(*) FROM runtime_configs').fetchone(),(1,))
        self.assertIn('configuration_binding_mismatch',self.pub.projection()['rows'][0]['adapter_exclusion_reason'])

    def test_restore_rebuilds_native_projection_from_copied_relative_evidence(self):
        from localbench.database_v2 import backup,restore,connect
        from localbench.database_v2.publication import CasePublisher
        from localbench.database_v2.store import wal_runtime_safe
        key=('restore-fixture',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        capture=self.native/'case.json'; capture.write_text('{"case_id":"C01","status":"error"}')
        self.adapter.completed(key=key,row=json.loads(capture.read_bytes()),native_root=self.native,artifact_paths=[capture])
        backup(self.db,self.pub.root,self.root/'backup'); restore(self.root/'backup',self.root/'restored')
        restored=connect(self.root/'restored/database.sqlite3',validation_only=not wal_runtime_safe())
        try:
            publisher=CasePublisher(restored,self.root/'restored/artifacts',clock=lambda:'now',validation_only=not wal_runtime_safe())
            self.assertEqual(publisher.recover()[0]['disposition'],'preserved')
            self.assertEqual(publisher.projection()['committed_results'],1)
            self.assertEqual(publisher.projection()['rows'][0]['case_id'],'C01')
        finally: restored.close()

    def test_native_first_pass_and_repair_observations_have_exact_failed_parent(self):
        key=('native-phases',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        first={'deterministic_passed':False,'checks':[{'id':'authored','passed':False}]}
        repair={'deterministic_passed':True,'checks':[{'id':'authored','passed':True}]}
        first_path=self.native/'first.json'; first_path.write_text(json.dumps(first))
        repair_path=self.native/'repair.json'; repair_path.write_text(json.dumps(repair))
        self.adapter.completed(key=key,row={'case_id':'C01','status':'success','first_pass_passed':False,'repair_attempted':True,'repair_passed':True},
            native_root=self.native,native_attempts=[{'kind':'first_pass','observations':first,'evidence_path':first_path},
                {'kind':'repair','observations':repair,'evidence_path':repair_path}])
        observations=self.db.execute('SELECT id,kind,parent_id,observations_json FROM native_attempt_observations ORDER BY ordinal').fetchall()
        self.assertEqual(len(observations),2); self.assertEqual(observations[1][2],observations[0][0])
        self.assertEqual(json.loads(observations[0][3]),first); self.assertEqual(json.loads(observations[1][3]),repair)
        self.assertEqual(self.db.execute('SELECT count(*) FROM attempts').fetchone(),(1,))
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))

    def test_native_repair_after_a_pass_is_rejected_without_partial_result(self):
        key=('bad-repair',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.adapter.completed(key=key,row={'case_id':'C01','status':'success'},native_root=self.native,
                native_attempts=[{'kind':'first_pass','observations':{'deterministic_passed':True}},
                    {'kind':'repair','observations':{'deterministic_passed':True}}])
        self.assertEqual(self.db.execute('SELECT count(*) FROM native_attempt_observations').fetchone(),(0,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_numeric_zero_cannot_replace_an_explicit_failed_boolean_parent(self):
        key=('numeric-parent',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.adapter.completed(key=key,row={'case_id':'C01','status':'success'},native_root=self.native,
                native_attempts=[{'kind':'first_pass','observations':{'deterministic_passed':0}},
                    {'kind':'repair','observations':{'deterministic_passed':True}}])
        self.assertEqual(self.db.execute('SELECT count(*) FROM native_attempt_observations').fetchone(),(0,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_phase_bytes_are_type_exact_even_for_boolean_zero_equality(self):
        key=('phase-type',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        path=self.native/'phase.json'; path.write_text('{"deterministic_passed":false}')
        with self.assertRaises(RuntimeError): self.adapter.completed(key=key,row={'case_id':'C01','status':'success'},native_root=self.native,
            native_attempts=[{'kind':'first_pass','observations':{'deterministic_passed':0},'evidence_path':path}])
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_real_native_role_boundary_plans_actual_sealed_identities_and_publishes(self):
        import test_v2_flashnext_roles as role_fixture
        from localbench.v2.flashnext_roles import run_role_case
        from localbench.v2.orchestrator import EvidenceStore
        from localbench.v2.tool_harness import ModelTurnResponse
        from localbench.v2.contracts import EvidenceRef
        foundation_records=role_fixture.foundation()
        store=EvidenceStore(self.root/'role-evidence')
        factory=role_fixture.Factory(foundation_records,lambda request:ModelTurnResponse(content='Ready' if request.turn==1 else 'Authored advisory observation'),store)
        adapter=NativeRowPublisher(self.pub,origin='synthetic_test')
        spec=role_fixture.build_role_cases(role_fixture.CAMPAIGN,'planner')[1]
        result=run_role_case(spec,foundation=foundation_records,base_config_spec=role_fixture.spec(),
            driver_factory=factory,evidence_store=store,output_dir=self.root/'role-case',ordinal=1,case_publisher=adapter)
        self.assertEqual(result['status'],'success'); self.assertTrue(result['human_review_required'])
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))
        actual_model=self.db.execute('SELECT m.identity_json FROM committed_results cr JOIN attempts a ON a.id=cr.attempt_id JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id JOIN runtime_configs c ON c.id=r.config_id JOIN models m ON m.id=c.model_id').fetchone()[0]
        self.assertEqual(json.loads(actual_model),foundation_records['model'].to_dict())
        self.assertEqual(self.db.execute('SELECT count(*) FROM native_attempt_observations').fetchone(),(1,))
        trace_bytes=store.path_for(EvidenceRef.from_dict(result['records']['trace'])).read_bytes()
        self.assertTrue(any((self.pub.root/path[0]).read_bytes()==trace_bytes for path in self.db.execute(
            "SELECT ar.relative_path FROM artifacts ar JOIN attempt_artifacts aa ON aa.artifact_id=ar.id WHERE aa.purpose='execution'")))

    def test_real_v1_runner_publishes_before_next_case_without_claiming_qualification(self):
        import test_localbench as v1_fixture
        from localbench.runner import BenchmarkRunner
        from localbench.models import ProviderResponse
        from localbench.database_v2.store import record_identity
        from localbench.config import load_config
        from localbench.v2.contracts import canonical_json_bytes
        from hashlib import sha256
        from types import SimpleNamespace
        helper=v1_fixture.RunnerTests()
        config_path,config,config_hash,suites=helper._write_inputs(self.native,'http://example.invalid')
        raw_config=json.loads(config_path.read_bytes()); raw_config['models']=raw_config['models'][:1]
        config_path.write_text(json.dumps(raw_config)); config,config_hash=load_config(config_path)
        model=config['models'][0]
        record_identity(self.db,'models',id='v1-model',source_id='source',version='native-v1-declared',payload=model)
        record_identity(self.db,'runtime_configs',id='v1-config',source_id='source',version='native-v1-declared',model_id='v1-model',payload=config)
        self.db.execute("INSERT INTO suites VALUES('v1-suite',?,'native-v1','source',?)",(suites[0].id,json.dumps(json.loads(suites[0].source_path.read_bytes()))))
        self.db.execute("INSERT INTO runs VALUES('v1-run','source','v1-suite','protocol','v1-config','env','now','synthetic_test','{}')")
        runner=BenchmarkRunner(config,config_path,config_hash,suites,run_id='native-v1-fixture',case_publisher=self.adapter)
        for index,case in enumerate(suites[0].cases,1):
            self.db.execute("INSERT INTO cases VALUES(?,?,'1','source',?,?)",('v1-case'+str(index),case.id,sha256(canonical_json_bytes(case.messages)).hexdigest(),json.dumps(case.messages)))
            self.db.execute('INSERT INTO suite_cases VALUES(?,?,?)',('v1-suite','v1-case'+str(index),index))
            self.db.execute("INSERT INTO trials VALUES(?,'v1-run','v1-suite',?,1,1,'v1','source')",('v1-trial'+str(index),'v1-case'+str(index)))
            self.adapter.register(('v1',str(runner.run_dir),model['id'],suites[0].id,case.id),trial_id='v1-trial'+str(index),source_id='source',case_id=case.id)
        calls=[]
        def chat(*args,**kwargs):
            self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone()[0],len(calls))
            calls.append(args)
            return ProviderResponse(content='authored native output',raw={'fixture':True})
        provider=SimpleNamespace(runtime_metadata=lambda timeout:{'version':'authored'},model_metadata=lambda name,timeout:None,
            chat=chat,unload=lambda name,timeout:{'status':'authored'})
        with patch('localbench.runner.make_provider',return_value=provider): runner.run()
        self.assertEqual(len(calls),2)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchall(),[('UNKNOWN',),('UNKNOWN',)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM native_attempt_observations').fetchone(),(2,))

    def test_separate_native_capture_and_assessment_boundary_preserves_execution_on_restart(self):
        key=('separate-capture',str(self.native),'C01',1); self.register(key); self.adapter.started(key=key)
        evidence=self.native/'session'; evidence.mkdir(); (evidence/'final.txt').write_bytes(b'authored captured output')
        session=self.native/'session.json'; session.write_text('{"status":"error","final_response":"authored captured output"}')
        capture=json.loads(session.read_bytes())
        self.adapter.capture_completed(key=key,case_id='C01',capture=capture,native_root=self.native,artifact_paths=[session,evidence])
        self.assertEqual(self.db.execute('SELECT execution_status FROM attempt_execution_state').fetchone(),('completed',))
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))
        self.assertEqual(self.pub.recover()[0]['disposition'],'incomplete')
        self.adapter.completed(key=key,row={'case_id':'C01',**capture,'evidence_directory':str(evidence)},native_root=self.native)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone(),('UNKNOWN',))
        self.assertEqual(self.db.execute("SELECT count(*) FROM lifecycle_events WHERE stage='execution_completed'").fetchone(),(1,))


if __name__=='__main__': unittest.main()
