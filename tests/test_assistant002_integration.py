"""Full-checkout integration; controlled fixtures, no Ollama requests."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from localbench.assistant002 import packet as api
from localbench.assistant002.calibration import install_reference
from localbench.assistant002.cli import interop, main


class ExistingProjectIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (api.repository_root()/'project-benchmarks/assistant-001/v1/manifest.json').is_file():
            if os.environ.get('ASSISTANT002_REQUIRE_FULL')=='1':
                raise RuntimeError('Complete A001 base checkout is required')
            raise unittest.SkipTest('Full original checkout required; exercised in mandatory Windows/Linux CI')

    def test_existing_review_writer_accepts_assistant002_rows(self):
        from localbench.assistant001.cli import review_package
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            summary=dict(campaign='assistant-002-v1',results=[dict(case_id='assistant002-t01',role='worker',
                ordinal=1,status='success',deterministic_passed=True,first_pass_passed=True,
                human_review_required=True,metrics={'wall_seconds':1})],planned_cases=1,completed_cases=1,
                qualification_status='human-review-pending')
            review_package(root,summary,'fixture:only','screen',32768)
            for name in ('review-package.xlsx','review-package.json','case-results.csv','role-summary.csv'):
                self.assertTrue((root/'review'/name).is_file())

    def test_joint_run_copies_journal_and_retains_source_hashes(self):
        from localbench.assistant001.packet import prepare as prepare_journal
        from localbench.assistant001.calibration import install_reference as install_journal
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); sim=api.prepare(root/'sim'); journal=prepare_journal(root/'journal')
            install_reference(sim/'workspace'); install_journal(journal/'workspace')
            original=api.snapshot(journal/'workspace')
            result,evidence=interop(sim,journal,repo=api.repository_root(),allow_host_execution=True)
            self.assertTrue(result['passed'],json.dumps(result,indent=2))
            self.assertEqual(result['executed'],96)
            self.assertTrue(result['pair']['copy_unchanged']);self.assertTrue(result['pair']['source_unchanged'])
            self.assertEqual(api.snapshot(journal/'workspace'),original)
            self.assertNotEqual(Path(result['pair']['tested_copy']).resolve(),(journal/'workspace').resolve())
            self.assertTrue((evidence/'assessment.json').is_file())

    def test_qualification_uses_three_fresh_worker_workspaces(self):
        from test_assistant002 import FakeSessions
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); sessions=FakeSessions(root); exporter=Mock()
            with patch('urllib.request.urlopen',side_effect=AssertionError('No provider access')), \
                 contextlib.redirect_stdout(io.StringIO()):
                code=main(['run','--model','fixture:only','--through','T01','--phase','qualification',
                    '--allow-host-execution','--output-root',str(root/'runs')],
                    sessions_factory=lambda *args,**kwargs:sessions,export=exporter)
            self.assertEqual(code,0);self.assertEqual(len(sessions.calls),3)
            self.assertEqual(len({str(call[1]) for call in sessions.calls}),3)
            summary=exporter.call_args.args[1]
            self.assertEqual([r['ordinal'] for r in summary['results']],[1,2,3])
            self.assertTrue(summary['passed'])

if __name__=='__main__':
    unittest.main()
