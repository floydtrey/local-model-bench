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

    def register(self,key,case='C01',binding=None):
        self.adapter.register(key,trial_id='trial',source_id='source',case_id=case,assessment_binding=binding)

    def test_exact_native_row_preserves_assessment_and_raw_capture(self):
        key=('fixture',str(self.native),'C01',1)
        self.register(key,binding={'case_id':'C01','_assessor_id':'assessor'})
        self.adapter.started(key=key)
        session=self.native/'execution'; session.mkdir(); (session/'raw.bin').write_bytes(b'raw\x00tool')
        assessment=self.native/'assessment.json'; assessment.write_text(json.dumps({'case_id':'C01','assessed_outcome':'PASS'}))
        row={'case_id':'C01','execution_status':'success','assessed_outcome':'PASS',
            'assessment_file':str(assessment),'evidence_directory':str(session),
            'evidence_refs':[file_reference(assessment,'assessment')], 'human_review_required':True,
            'first_pass_passed':True,'repair_attempted':False,'repair_passed':None}
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
        self.register(key,case='assistant001-t01')
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


if __name__=='__main__': unittest.main()
