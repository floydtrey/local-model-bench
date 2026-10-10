"""Deterministic publication tests; never invoke a model or candidate code."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from localbench.database_v2 import connect, backup, restore
from localbench.database_v2.publication import CasePublisher, stable_id
from localbench.database_v2.store import DatabaseError, wal_runtime_safe


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.validation = not wal_runtime_safe()
        if os.environ.get('LOCALBENCH_REQUIRE_OPERATIONAL_DB') == '1':
            self.assertFalse(self.validation, 'Operational gate requires actual patched SQLite')
        self.db = connect(self.root/'cases.sqlite3', validation_only=self.validation)
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO sources VALUES('source','synthetic_test','1','fixture',?,'now','test','{}')", ('a'*64,))
        from localbench.database_v2.store import record_identity
        record_identity(self.db,'models',id='model',source_id='source',version='1',payload={'name':'fixture'})
        record_identity(self.db,'runtime_configs',id='config',source_id='source',model_id='model',version='1',payload={'context':4096})
        self.db.execute("INSERT INTO suites VALUES('suite','fixture','1','source','{}')")
        self.db.execute("INSERT INTO cases VALUES('case','C01','1','source',?,'{}')", ('b'*64,))
        self.db.execute("INSERT INTO suite_cases VALUES('suite','case',1)")
        self.db.execute("INSERT INTO protocols VALUES('protocol','fixture','1','source','L0',NULL,NULL,'{}')")
        self.db.execute("INSERT INTO environments VALUES('env','source','1','{}','now')")
        self.db.execute("INSERT INTO runs VALUES('run','source','suite','protocol','config','env','now','synthetic_test','{}')")
        self.db.execute("INSERT INTO trials VALUES('trial','run','suite','case',1,2,'repeat','source')")
        self.db.execute("INSERT INTO assessors VALUES('assessor','fixture','1',?,'source','{}')", ('c'*64,))
        self.db.execute("INSERT INTO protocol_evidence_requirements VALUES('protocol','capture',1)")
        self.pub = self.publisher()

    def publisher(self, **kwargs):
        return CasePublisher(self.db,self.root/'artifacts',clock=lambda:'now',validation_only=self.validation,**kwargs)

    def schedule(self, attempt='attempt', **kwargs):
        self.pub.schedule(attempt_id=attempt,trial_id='trial',source_id='source',**kwargs)

    def prepared(self, *, outcome='PASS', attempt='attempt', index=1, parent=None):
        self.schedule(attempt,attempt_index=index,parent_id=parent)
        self.pub.started(attempt)
        capture = self.pub.artifact(attempt,'capture',b'exact raw output\x00tool bytes\n')
        self.pub.executed(attempt,[capture])
        assessment_artifact = self.pub.artifact(attempt,'assessment',json.dumps({'case_id':'C01','outcome':outcome}).encode())
        assessment = dict(id=stable_id('assessment',attempt),attempt_id=attempt,
            assessor_id='assessor',protocol_id='protocol',source_id='source',
            artifact_id=assessment_artifact['id'],outcome=outcome,detail_json='{}')
        self.pub.prepare(attempt,outcome=outcome,artifacts=[capture,assessment_artifact],
            assessment=assessment,projection_row={'case_id':'C01','execution_status':'completed',
                'assessed_outcome':outcome.lower(),'attempt_id':attempt,'attempt_index':index,
                'human_review_required':True,'run_id':'run'})
        return capture

    def count(self, table):
        return self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def test_default_operational_gate_and_pragmas(self):
        if not self.validation:
            self.assertEqual(self.db.execute('pragma synchronous').fetchone(),(2,))
            self.assertEqual(self.db.execute('pragma journal_mode').fetchone(),('wal',))
        with patch('localbench.database_v2.publication.wal_runtime_safe',return_value=False):
            with self.assertRaises(DatabaseError): CasePublisher(self.db,self.root/'rejected',clock=lambda:'now')
        self.assertFalse((self.root/'rejected').exists())

    def test_case_commits_before_suite_completion_exact_bytes_and_review(self):
        capture=self.prepared()
        self.pub.commit('attempt')
        self.assertEqual(self.count('committed_results'),1)
        self.assertEqual((self.root/'artifacts'/capture['relative_path']).read_bytes(),b'exact raw output\x00tool bytes\n')
        self.assertEqual(self.count('reviews'),1)
        self.assertEqual(self.db.execute('SELECT status FROM reviews').fetchone(),('pending',))
        self.assertEqual(self.pub.projection()['committed_results'],1)
        self.assertEqual(self.db.execute('SELECT planned_trials FROM trials').fetchone(),(2,))
        stages=[r[0] for r in self.db.execute('SELECT stage FROM lifecycle_events ORDER BY sequence')]
        self.assertEqual(stages,['scheduled','started','execution_completed','evidence_finalized','assessment_completed','result_committed','review_pending'])

    def test_missing_or_changed_evidence_prevents_success(self):
        capture=self.prepared()
        path=self.root/'artifacts'/capture['relative_path']
        path.write_bytes(b'changed')
        with self.assertRaises(DatabaseError): self.pub.commit('attempt')
        self.assertEqual(self.count('committed_results'),0)
        self.assertEqual(self.pub.recover()[0]['disposition'],'evidence_unavailable')

    def test_absent_required_capture_cannot_commit_pass(self):
        self.prepared(outcome='FAIL'); self.pub.commit('attempt')
        intent=json.loads(self.db.execute('SELECT envelope_json FROM case_publication_intents').fetchone()[0])
        # Native caller may attempt to omit protocol-required evidence; DB guards it.
        # A fresh repair has no capture even though its predecessor had one.
        self.schedule('repair',attempt_index=2,parent_id='attempt')
        self.pub.started('repair'); self.pub.executed('repair',[])
        a=self.pub.artifact('repair','assessment',b'{}')
        assessment={**intent['envelope']['assessment'],'id':'repair-assessment','attempt_id':'repair','artifact_id':a['id'],'outcome':'PASS'}
        self.pub.prepare('repair',outcome='PASS',artifacts=[a],assessment=assessment)
        with self.assertRaises(sqlite3.IntegrityError): self.pub.commit('repair')
        self.assertEqual(self.count('committed_results'),1)

    def test_exact_replay_and_conflicting_prepare(self):
        self.prepared(); result=self.pub.commit('attempt')
        self.assertEqual(self.pub.commit('attempt'),result)
        self.assertEqual(self.count('case_commit_events'),1)
        with self.assertRaises(DatabaseError): self.pub.prepare('attempt',outcome='UNKNOWN',artifacts=[])

    def test_other_attempt_artifact_rejected_without_fuzzy_matching(self):
        self.schedule(); self.pub.started('attempt')
        wrong=self.pub.artifact('same-case-different-attempt','capture',b'raw')
        with self.assertRaises(DatabaseError): self.pub.executed('attempt',[wrong])

    def test_failure_blocked_and_unassessed_cases_publish_honestly(self):
        self.prepared(outcome='FAIL'); self.pub.commit('attempt')
        for index,outcome in enumerate(('BLOCKED','UNKNOWN','UNSUPPORTED','INCOMPLETE','NOT_TESTED'),2):
            attempt='a'+str(index)
            self.db.execute("INSERT INTO runs VALUES(?,'source','suite','protocol','config','env','now','synthetic_test','{}')",('run'+str(index),))
            self.db.execute("INSERT INTO trials VALUES(?,?,'suite','case',1,1,'repeat','source')",('trial'+str(index),'run'+str(index)))
            self.pub.schedule(attempt_id=attempt,trial_id='trial'+str(index),source_id='source')
            self.pub.prepare(attempt,outcome=outcome,artifacts=[],projection_row={'case_id':'C01','assessed_outcome':'unknown'})
            self.pub.commit(attempt)
        self.assertEqual([r[0] for r in self.db.execute('SELECT outcome FROM committed_results ORDER BY rowid')],['FAIL','BLOCKED','UNKNOWN','UNSUPPORTED','INCOMPLETE','NOT_TESTED'])
        self.assertEqual(self.count('assessments'),1)

    def test_transaction_failures_rollback_all_result_rows(self):
        self.prepared()
        for boundary in ('before_assessment_commit','during_transaction','before_db_commit'):
            def fault(name):
                if name==boundary: raise RuntimeError(boundary)
            with self.assertRaises(RuntimeError): self.publisher(fault=fault).commit('attempt')
            for table in ('assessments','committed_results','reviews','case_projection_inputs','case_commit_events'):
                self.assertEqual(self.count(table),0,table)
        self.pub.commit('attempt'); self.assertEqual(self.count('committed_results'),1)

    def test_commit_survives_after_commit_exception(self):
        self.prepared()
        def fault(name):
            if name=='after_db_commit': raise RuntimeError('process boundary')
        with self.assertRaises(RuntimeError): self.publisher(fault=fault).commit('attempt')
        self.assertEqual(self.count('committed_results'),1)
        self.assertEqual(self.pub.recover()[0]['disposition'],'preserved')

    def test_notifications_are_post_commit_ordered_and_deduplicated(self):
        self.prepared()
        seen=[]
        def notify(event):
            self.assertEqual(self.count('committed_results'),1)
            self.assertFalse(self.db.in_transaction)
            seen.append(event)
        pub=self.publisher(notify=notify)
        self.assertEqual(pub.deliver(),[])
        pub.commit('attempt'); pub.deliver(); pub.deliver()
        self.assertEqual(len(seen),1)
        self.assertEqual(pub.events(after=1),[])

    def test_notification_failure_does_not_rollback_and_can_retry(self):
        self.prepared(); self.pub.commit('attempt')
        def notify(event): raise RuntimeError('viewer offline')
        with self.assertRaises(RuntimeError): self.publisher(notify=notify).deliver()
        self.assertEqual(self.count('committed_results'),1)
        self.assertEqual(self.count('case_event_receipts'),0)
        seen=[]; self.publisher(notify=seen.append).deliver()
        self.assertEqual(len(seen),1)

    def test_notification_crash_after_delivery_is_at_least_once(self):
        self.prepared(); self.pub.commit('attempt'); seen=[]
        def fault(name):
            if name=='after_notify': raise RuntimeError('abrupt stop')
        with self.assertRaises(RuntimeError): self.publisher(notify=seen.append,fault=fault).deliver()
        self.publisher(notify=seen.append).deliver()
        self.assertEqual(len(seen),2); self.assertEqual(seen[0]['id'],seen[1]['id'])

    def test_atomic_export_failure_retains_prior_snapshot_and_db(self):
        target=self.root/'snapshot.json'; target.write_bytes(b'old')
        self.prepared(); self.pub.commit('attempt')
        def fault(name):
            if name=='during_report_export': raise RuntimeError('export failure')
        with self.assertRaises(RuntimeError): self.publisher(fault=fault).export(target)
        self.assertEqual(target.read_bytes(),b'old'); self.assertEqual(self.count('committed_results'),1)
        self.pub.export(target)
        self.assertEqual(json.loads(target.read_bytes())['committed_results'],1)
        self.assertEqual(list(self.root.glob('snapshot.json.pending-*')),[])

    def test_recovery_prepared_exact_replay_without_execution(self):
        self.prepared()
        self.assertEqual(self.pub.recover()[0]['disposition'],'owner_action_required')
        self.assertEqual(self.count('committed_results'),0)
        self.assertEqual(self.pub.recover(reconcile_prepared=True)[0]['disposition'],'preserved')
        self.pub.recover(reconcile_prepared=True)
        self.assertEqual(self.count('committed_results'),1)
        self.assertEqual(self.count('case_commit_events'),1)
        self.assertEqual(self.count('controller_identity'),0)
        self.assertEqual(self.count('queue_snapshots'),0)

    def test_recovery_incomplete_interrupted_and_corrupt_committed(self):
        self.schedule()
        self.assertEqual(self.pub.recover()[0]['disposition'],'incomplete')
        self.pub.started('attempt')
        self.assertEqual(self.pub.recover()[0]['disposition'],'interrupted')
        self.pub.prepare('attempt',outcome='INCOMPLETE',artifacts=[])
        self.pub.commit('attempt')
        path=self.root/'artifacts'/self.db.execute('SELECT relative_path FROM artifacts').fetchone()[0]
        path.unlink()
        self.assertEqual(self.pub.recover()[0]['disposition'],'evidence_unavailable')
        self.assertEqual(self.count('committed_results'),1)

    def test_immutable_publication_rows_reject_replace_even_without_recursive_triggers(self):
        self.prepared(); self.pub.commit('attempt'); self.pub.recover()
        self.publisher(notify=lambda event:None).deliver()
        self.db.execute('pragma recursive_triggers=OFF')
        for table in ('case_publication_intents','case_projection_inputs','case_commit_events','case_event_receipts','case_recovery_observations'):
            with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table)
            with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM '+table)

    def test_backup_restore_preserves_committed_intents_events_and_exact_evidence(self):
        self.prepared(); self.pub.commit('attempt')
        backup(self.db,self.root/'artifacts',self.root/'backup')
        restore(self.root/'backup',self.root/'restored')
        restored=connect(self.root/'restored/database.sqlite3',validation_only=self.validation)
        try:
            pub=CasePublisher(restored,self.root/'restored/artifacts',clock=lambda:'now',validation_only=self.validation)
            self.assertEqual(pub.events(),self.pub.events())
            self.assertEqual(pub.recover()[0]['disposition'],'preserved')
        finally: restored.close()

    def test_completed_review_is_audited_and_never_grants_execution_permission(self):
        self.prepared(); self.pub.commit('attempt')
        assessment=self.db.execute('SELECT id FROM assessments').fetchone()[0]
        pending=self.db.execute('SELECT id FROM reviews').fetchone()[0]
        review=self.pub.record_review(assessment,review_bytes=b'{"technical_review":"completed"}',reviewer='authored fixture',supersedes_id=pending)
        self.assertEqual(self.pub.record_review(assessment,review_bytes=b'{"technical_review":"completed"}',reviewer='authored fixture',supersedes_id=pending),review)
        self.assertEqual(self.db.execute('SELECT status,identity_verified FROM reviews WHERE id=?',(review,)).fetchone(),('completed',0))
        binding=json.loads(self.db.execute('SELECT binding_json FROM reviews WHERE id=?',(review,)).fetchone()[0])
        self.assertFalse(binding['execution_permission'])
        self.assertEqual(self.count('controller_identity'),0); self.assertEqual(self.count('queue_snapshots'),0)
        with self.assertRaises(DatabaseError): self.pub.record_review(assessment,review_bytes=b'{}',reviewer='fixture',supersedes_id='unknown-review')

    def test_export_refuses_authoritative_database_or_evidence_replacement(self):
        capture=self.prepared(); self.pub.commit('attempt')
        original=(self.root/'artifacts'/capture['relative_path']).read_bytes()
        for destination in (self.root/'cases.sqlite3',self.root/'cases.sqlite3-wal',self.root/'artifacts'/capture['relative_path']):
            with self.assertRaises(DatabaseError): self.pub.export(destination)
        self.assertEqual((self.root/'artifacts'/capture['relative_path']).read_bytes(),original)
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone(),('ok',))

    def test_evidence_disappearing_during_transaction_rolls_back_success(self):
        capture=self.prepared()
        def fault(boundary):
            if boundary=='before_db_commit': (self.pub.root/capture['relative_path']).unlink()
        with self.assertRaises(FileNotFoundError): self.publisher(fault=fault).commit('attempt')
        for table in ('assessments','committed_results','case_projection_inputs','case_commit_events'):
            self.assertEqual(self.count(table),0)


if __name__ == '__main__': unittest.main()
