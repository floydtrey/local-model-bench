"""Abrupt-process boundary simulations on authored storage fixtures only.

These tests do not demonstrate physical power-loss survival and never execute
models, generated/candidate code, or a queue controller.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from localbench.database_v2 import connect
from localbench.database_v2.publication import CasePublisher
from localbench.database_v2.store import wal_runtime_safe

CHILD = r'''
import os,sys,json
from pathlib import Path
sys.path.insert(0,str(Path('tests').resolve()))
import test_case_publication as fixture
from localbench.database_v2.publication import CasePublisher
case=fixture.PublicationTests(); case.setUp()
Path(sys.argv[2]).write_text(str(case.root),encoding='utf-8')
case.prepared(); case.pub.commit('attempt')
case.db.execute("INSERT INTO trials VALUES('trial2','run','suite','case',2,2,'repeat','source')")
boundary=sys.argv[1]
def fault(name):
    if name==boundary: os._exit(71)
case.pub=case.publisher(fault=fault)
case.pub.schedule(attempt_id='second',trial_id='trial2',source_id='source')
case.pub.started('second')
model=case.pub.artifact('second','capture',b'exact model output prefix')
case.pub._boundary('during_model_output_capture')
tool=case.pub.artifact('second','tool_capture',b'exact tool output prefix')
case.pub._boundary('during_tool_capture')
capture_boundary=boundary in ('during_capture_transaction','before_capture_commit','after_capture_commit')
pending={'case_id':'C01','execution_status':'success','assessment_state':'pending','assessed_outcome':None,'score':None,'maximum_score':None}
case.pub.executed('second',[model,tool],publication_row=pending if capture_boundary else None)
assessment_artifact=case.pub.artifact('second','assessment',b'{"case_id":"C01","outcome":"PASS"}')
assessment=dict(id='second-assessment',attempt_id='second',assessor_id='assessor',protocol_id='protocol',source_id='source',artifact_id=assessment_artifact['id'],outcome='PASS',detail_json='{}')
case.pub.prepare('second',outcome='PASS',artifacts=[model,tool,assessment_artifact],assessment=assessment,projection_row={'case_id':'C01','execution_status':'completed','assessed_outcome':'pass'})
case.pub.commit('second')
case.pub.export(case.root/'snapshot.json')
raise AssertionError('Boundary did not interrupt')
'''


class AbruptPublicationTests(unittest.TestCase):
    def test_process_restart_preserves_prior_case_and_truthful_boundary_state(self):
        boundaries=('scheduled','started','during_model_output_capture','during_tool_capture',
            'execution_recorded','evidence_written','publication_prepared','before_assessment_commit',
            'during_transaction','before_db_commit','after_db_commit','during_report_export','after_report_replace',
            'during_capture_transaction','before_capture_commit','after_capture_commit')
        for boundary in boundaries:
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); marker=root/'child-root.txt'
                env={**os.environ,'TEMP':str(root),'TMP':str(root),'PYTHONDONTWRITEBYTECODE':'1'}
                child=subprocess.run([sys.executable,'-c',CHILD,boundary,str(marker)],env=env,capture_output=True,timeout=30)
                self.assertEqual(child.returncode,71,child.stderr.decode(errors='replace'))
                child_root=Path(marker.read_text(encoding='utf-8'))
                con=connect(child_root/'cases.sqlite3',validation_only=not wal_runtime_safe())
                try:
                    pub=CasePublisher(con,child_root/'artifacts',clock=lambda:'now',validation_only=not wal_runtime_safe())
                    self.assertEqual(con.execute('PRAGMA integrity_check').fetchone(),('ok',))
                    self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
                    preserved=con.execute("SELECT outcome FROM committed_results WHERE attempt_id='attempt'").fetchone()
                    self.assertEqual(preserved,('PASS',))
                    committed=boundary in ('after_db_commit','during_report_export','after_report_replace')
                    self.assertEqual(con.execute('SELECT count(*) FROM committed_results').fetchone()[0],2 if committed else 1)
                    observations=pub.recover()
                    second=next(r for r in observations if r['attempt_id']=='second')
                    if committed or boundary=='after_capture_commit': self.assertEqual(second['disposition'],'preserved')
                    elif boundary=='scheduled': self.assertEqual(second['disposition'],'incomplete')
                    elif boundary in ('started','during_model_output_capture','during_tool_capture','during_capture_transaction','before_capture_commit'): self.assertEqual(second['disposition'],'interrupted')
                    elif boundary in ('execution_recorded','evidence_written'): self.assertEqual(second['disposition'],'incomplete')
                    else: self.assertEqual(second['disposition'],'owner_action_required')
                    self.assertEqual(con.execute('SELECT count(*) FROM queue_snapshots').fetchone(),(0,))
                    self.assertEqual(con.execute('SELECT count(*) FROM controller_identity').fetchone(),(0,))
                    pub.export(root/'rebuilt.json')
                    self.assertEqual(json.loads((root/'rebuilt.json').read_bytes())['committed_results'],2 if committed else 1)
                    if boundary=='after_capture_commit':
                        report=json.loads((root/'rebuilt.json').read_bytes())
                        self.assertEqual(report['published_attempts'],2)
                        pending=next(r for r in report['rows'] if r.get('assessment_state')=='pending')
                        self.assertIsNone(pending['assessed_outcome']); self.assertIsNone(pending['score'])
                finally: con.close()


if __name__=='__main__': unittest.main()
