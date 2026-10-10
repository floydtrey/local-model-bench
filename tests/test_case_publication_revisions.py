"""Positive native capture visibility and same-identity late assessment tests."""
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_case_publication as foundation
from localbench.database_v2.native_rows import NativeRowPublisher
from localbench.database_v2.publication import CasePublisher
from localbench.database_v2.store import migrate,migrations,wal_runtime_safe
from localbench.v2.report_adapter import file_reference


class PublicationRevisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=foundation.PublicationTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root,self.db,self.pub=self.fixture.root,self.fixture.db,self.fixture.pub
        self.seen=[]; self.pub.notify=self.seen.append
        self.adapter=NativeRowPublisher(self.pub,report_path=self.root/'partial.json')

    def register(self,run,case='C01',trial='trial'):
        key=('controlled-role',str(run.resolve()),'planner',case,1)
        self.adapter.register(key,trial_id=trial,source_id='source',case_id=case,
            assessment_binding={'case_id':case,'_assessor_id':'assessor'},
            configuration_binding={'config_id':'config','row_fields':{'effective_settings':{'context':4096}}})
        return key

    def capture(self,run,key,case='C01'):
        run.mkdir(); evidence=run/'session'; evidence.mkdir(); (evidence/'final.txt').write_bytes(b'authored output')
        session=run/'session.json'; session.write_text('{"status":"success","final_response":"authored output"}')
        self.adapter.started(key=key)
        return self.adapter.capture_completed(key=key,case_id=case,capture=json.loads(session.read_bytes()),
            native_root=run,artifact_paths=[session,evidence])

    def assessed(self,run,key,case='C01'):
        assessment=run/'assessment.json'; assessment.write_text(json.dumps({'case_id':case,'assessed_outcome':'PASS'}))
        self.adapter.completed(key=key,row={'case_id':case,'execution_status':'success','assessed_outcome':'PASS',
            'assessment_file':str(assessment),'evidence_directory':str(run/'session'),
            'effective_settings':{'context':4096},'evidence_refs':[file_reference(assessment,'assessment')]},native_root=run)

    def test_two_real_native_calls_publish_first_before_second_starts_then_assess_without_rerun(self):
        from localbench.qualification_v2.planner import run_planner
        first,second=self.root/'first',self.root/'second'; first.mkdir(); second.mkdir()
        self.db.execute("INSERT INTO cases VALUES('case2','C02','1','source',?,'{}')",('b'*64,))
        self.db.execute("INSERT INTO suite_cases VALUES('suite','case2',2)")
        self.db.execute("INSERT INTO trials VALUES('trial2','run','suite','case2',1,1,'second','source')")
        key1=self.register(first); self.register(second,'C02','trial2')
        calls=[]
        def verify(run,repo=None): return {'case_id':'C01' if Path(run).resolve()==first.resolve() else 'C02','prompt':'authored fixture'}
        def session(**kwargs):
            if calls:
                report=self.pub.projection()
                self.assertEqual(report['published_attempts'],1); self.assertEqual(report['committed_results'],0)
                self.assertEqual(report['rows'][0]['assessment_state'],'pending')
                self.assertIsNone(report['rows'][0]['assessed_outcome']); self.assertIsNone(report['rows'][0]['score'])
                self.assertEqual(self.seen[0]['stage'],'capture')
                self.assertEqual(json.loads((self.root/'partial.json').read_bytes())['published_attempts'],1)
            calls.append(kwargs['case_id'])
            return {'status':'success','final_response':'authored output','metrics':{}}
        with patch('localbench.qualification_v2.planner.verify_run',side_effect=verify):
            run_planner(first,session,case_publisher=self.adapter)
            initial=self.db.execute("SELECT * FROM case_publication_revisions WHERE stage='capture'").fetchone()
            run_planner(second,session,case_publisher=self.adapter)
        cursor=self.pub.events()[-1]['sequence']; self.assessed(first,key1)
        self.assertEqual(calls,['C01','C02'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM attempts').fetchone(),(2,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM trials').fetchone(),(2,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(1,))
        report=self.pub.projection(); self.assertEqual(report['published_attempts'],2)
        first_row=next(row for row in report['rows'] if row['case_id']=='C01')
        self.assertEqual(first_row['assessed_outcome'],'PASS'); self.assertEqual(first_row['assessment_state'],'completed')
        self.assertEqual(self.pub.events(after=cursor)[0]['stage'],'assessed')
        self.assertEqual(self.db.execute('SELECT * FROM case_publication_revisions WHERE id=?',(initial[0],)).fetchone(),initial)

    def test_restart_preserves_pending_publication_and_late_assessment_updates_same_attempt(self):
        run=self.root/'capture'; key=self.register(run); publication=self.capture(run,key)
        before=self.db.execute('SELECT * FROM case_publication_revisions').fetchone()
        # A fresh storage adapter is restart reconciliation, never a model runner.
        restarted=CasePublisher(self.db,self.pub.root,clock=lambda:'now',validation_only=not wal_runtime_safe())
        self.assertEqual(restarted.recover()[0]['disposition'],'preserved')
        self.assertEqual(restarted.projection()['rows'][0]['assessment_state'],'pending')
        self.assertEqual(restarted.events()[0]['id'],publication)
        self.assessed(run,key)
        self.assertEqual(self.pub.projection()['published_attempts'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM attempts').fetchone(),(1,))
        self.assertEqual(self.db.execute('SELECT * FROM case_publication_revisions WHERE id=?',(before[0],)).fetchone(),before)

    def test_capture_transaction_rollback_does_not_publish_or_advance_execution(self):
        run=self.root/'rollback'; key=self.register(run)
        def fault(boundary):
            if boundary=='during_capture_transaction': raise RuntimeError('authored rollback')
        self.pub.fault=fault
        with self.assertRaises(RuntimeError): self.capture(run,key)
        self.assertEqual(self.pub.events(),[]); self.assertEqual(self.pub.projection()['published_attempts'],0)
        self.assertEqual(self.db.execute('SELECT execution_status FROM attempt_execution_state').fetchone(),('started',))
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_capture_notification_retry_replays_same_id_without_duplicate_revision(self):
        run=self.root/'notify'; key=self.register(run)
        def fault(boundary):
            if boundary=='after_notify': raise RuntimeError('delivery interrupted')
        self.pub.fault=fault; publication=self.capture(run,key)
        self.assertEqual(self.pub.projection()['published_attempts'],1)
        self.assertEqual(len(self.adapter.post_commit_errors),1)
        self.pub.fault=lambda boundary:None; self.pub.deliver(); self.pub.deliver()
        self.assertEqual([event['id'] for event in self.seen],[publication,publication])
        self.assertEqual(self.db.execute('SELECT count(*) FROM case_publication_revisions').fetchone(),(1,))

    def test_corrupt_capture_stays_visible_unavailable_and_blocks_late_success(self):
        run=self.root/'corrupt'; key=self.register(run); self.capture(run,key)
        path=self.db.execute("SELECT ar.relative_path FROM artifacts ar JOIN attempt_artifacts aa ON aa.artifact_id=ar.id WHERE aa.purpose LIKE 'native_file:%final.txt'").fetchone()[0]
        (self.pub.root/path).write_bytes(b'corrupt')
        row=self.pub.projection()['rows'][0]
        self.assertEqual(row['publication_integrity'],'evidence_unavailable'); self.assertIsNone(row['assessed_outcome'])
        with self.assertRaises(RuntimeError): self.assessed(run,key)
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone(),(0,))

    def test_revision_immutability_covers_alternate_stage_identity(self):
        run=self.root/'immutable'; key=self.register(run); self.capture(run,key)
        self.db.execute('PRAGMA recursive_triggers=OFF')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT OR REPLACE INTO case_publication_revisions SELECT 'different',attempt_id,revision+1,stage,result_id,snapshot_artifact_id,row_json,row_sha256,artifacts_json FROM case_publication_revisions")
        self.assertEqual(self.db.execute('SELECT count(*) FROM case_publication_revisions').fetchone(),(1,))

    def test_upgrade_preserves_existing_final_event_cursor_receipts_and_history(self):
        self.fixture.prepared(); self.pub.commit('attempt'); self.pub.deliver()
        old=sqlite3.connect(self.root/'schema9.sqlite3',isolation_level=None)
        try:
            old.execute('PRAGMA foreign_keys=ON'); old.execute('PRAGMA recursive_triggers=ON')
            old.execute('PRAGMA journal_mode=WAL'); old.execute('PRAGMA synchronous=FULL')
            migrate(old,migrations()[:9])
            tables=[r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")
                if r[0] not in ('schema_migrations','case_publication_revisions','case_publication_events','case_publication_receipts')]
            with __import__('localbench.database_v2',fromlist=['transaction']).transaction(old):
                for table in tables:
                    for row in self.db.execute('SELECT * FROM '+table):
                        old.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in row)+')',row)
            before=old.execute('SELECT * FROM committed_results').fetchall()
            legacy_events=old.execute('SELECT sequence,id,result_id FROM case_commit_events').fetchall()
            migrate(old)
            migrated=CasePublisher(old,self.pub.root,clock=lambda:'now',notify=self.seen.append,validation_only=not wal_runtime_safe())
            self.assertEqual([(e['sequence'],e['id'],e['result_id']) for e in migrated.events()],legacy_events)
            self.assertEqual(migrated.deliver(),[])
            self.assertEqual(old.execute('SELECT * FROM committed_results').fetchall(),before)
            self.assertEqual(migrated.projection()['committed_results'],1)
        finally: old.close()


if __name__=='__main__': unittest.main()
