"""Read-only legacy adapter fixtures: missing fields never become zero/pass."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from localbench.v2.report_adapter import normalize_legacy_report


class LegacyReportAdapterTests(unittest.TestCase):
    def test_historical_role_report_missing_values_remain_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review-package.json"
            path.write_text(json.dumps({
                "schema_version": "flashnext-role-review-package:v1",
                "metadata": {"candidate_id": "legacy"},
                "case_results": [{"case_id": "tester-case-c", "role": "tester",
                                  "status": "success", "deterministic_passed": True}],
            }), encoding="utf-8")
            row = normalize_legacy_report(path)["cases"][0]
            self.assertIsNone(row["human_adjudication"])
            self.assertIsNone(row["suite_version"])
            self.assertIsNone(row["model_identity"])
            self.assertEqual(row["deterministic_passed"], True)

    def test_assistant_blocked_successor_not_attempted_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps({
                "campaign": "assistant-001-v1", "track": "fixed-plan-worker-chain",
                "results": [{"case_id": "T01", "status": "error",
                             "deterministic_passed": False},
                            {"case_id": "T02", "status": "blocked",
                             "deterministic_passed": None}],
            }), encoding="utf-8")
            report = normalize_legacy_report(path)
            self.assertEqual(report["source_kind"], "assistant-worker-project")
            self.assertIsNone(report["cases"][1]["deterministic_passed"])
            self.assertEqual(report["cases"][1]["execution_status"], "blocked")
            self.assertIsNone(report["role_qualification"])

    def test_unknown_report_rejected_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.json"
            path.write_text('{"status":"success"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                normalize_legacy_report(path)


class AggregateAndQualificationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def aggregate(self):
        import test_v2_repetition_reporting as f
        from localbench.v2.reporting import aggregate_repeated_run
        host,runtime,model=f.foundation()
        pack=self.root/'pack.json'
        pack.write_bytes(f.pack_bytes(level='L0',screen_trials=1,qualification_trials=3))
        store=f.EvidenceStore(self.root/'evidence')
        outputs=iter(['good','bad','good'])
        run=f.run_v2_repetitions(run_id='t13-fixture',repetition_phase='qualification',
            pack_source=pack.read_bytes(),pack_source_locator=str(pack),host=host,runtime=runtime,model=model,
            configuration_bindings={'profile-a':f.configuration(tools=False)},evaluator_registry=f.registry(),
            driver_binding=f.DriverBinding('fake',f.DRIVER_DIGEST,lambda request:f.ModelTurnResponse(content=next(outputs))),
            evidence_store=store,harness_source={'kind':'git','commit':f.HARNESS_COMMIT},clock=f.fixed_clock(3))
        report=aggregate_repeated_run('t13-report',run)
        path=store.persist(report)
        return path,store,run

    def test_sealed_aggregate_reads_actual_trials_without_inflating_cases(self):
        path,store,run=self.aggregate()
        original=path.read_bytes()
        report=normalize_legacy_report(path,evidence_root=store.root)
        self.assertEqual(report['source_kind'],'v2-aggregate-report')
        self.assertEqual(len(report['cases']),3)
        self.assertEqual({r['case_id'] for r in report['cases']},{'case-a'})
        self.assertEqual([r['assessed_outcome'] for r in report['cases']],['pass','fail','pass'])
        self.assertEqual({r['suite_version'] for r in report['cases']},{'1.0.0'})
        self.assertEqual({r['rubric_id'] for r in report['cases']},{'synthetic-evaluator'})
        self.assertEqual({r['planned_trial_count'] for r in report['cases']},{3})
        self.assertEqual({r['acceptance_check_unit'] for r in report['cases']},{'evaluator_checks_in_trial'})
        self.assertEqual([r['assessment_check_score']['score'] for r in report['cases']],[1.0,0.0,1.0])
        self.assertEqual(report['cases'][0]['model_identity']['provider_digest'],'a'*64)
        self.assertIsNone(report['cases'][0]['model_identity']['quantization'])
        self.assertTrue(any(r['kind']=='intrinsic_execution_trace' for r in report['cases'][0]['evidence_refs']))
        self.assertEqual(path.read_bytes(),original)

    def test_unavailable_raw_aggregate_evidence_is_unknown(self):
        path,store,run=self.aggregate()
        report=normalize_legacy_report(path)
        self.assertEqual(len(report['cases']),1)
        self.assertIsNone(report['cases'][0]['assessed_outcome'])
        self.assertIn('unavailable',report['cases'][0]['adapter_exclusion_reason'])

    def test_changed_sealed_evidence_and_missing_execution_are_detected(self):
        path,store,run=self.aggregate()
        target=store.path_for(run.execution_evidence[0])
        target.unlink()
        report=normalize_legacy_report(path,evidence_root=store.root)
        self.assertEqual(len(report['cases']),1)
        self.assertIsNone(report['cases'][0]['assessed_outcome'])
        target=store.path_for(run.case_results[0])
        raw=json.loads(target.read_text()); raw['payload']['status']='blocked'
        target.write_text(json.dumps(raw))
        report=normalize_legacy_report(path,evidence_root=store.root)
        self.assertIn('digest',report['cases'][0]['adapter_exclusion_reason'])

    def test_tampered_aggregate_envelope_is_rejected(self):
        path,store,run=self.aggregate()
        raw=json.loads(path.read_text()); raw['payload']['observed_trials']=900
        path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError): normalize_legacy_report(path,evidence_root=store.root)

    def test_available_role_settings_are_resolved_from_sealed_events(self):
        from localbench.v2.contracts import sha256_json, seal_evidence
        path,store,run=self.aggregate()
        identity={k:run.manifest.to_dict()['payload'][k] for k in ('model','runtime')}
        (self.root/'runtime-identity.json').write_text(json.dumps(identity))
        (self.root/'runner-inputs.json').write_text(json.dumps({'timeout_seconds':30}))
        session=self.root/'session'; session.mkdir()
        config=run.effective_configs[0]
        def events(reference):
            event={'sequence':1,'event_type':'assistant001_effective_config','payload':reference}
            (session/'events.jsonl').write_text(json.dumps({**event,'event_sha256':sha256_json(event)})+'\n')
        events(config.reference.to_dict())
        summary=self.root/'summary.json'
        summary.write_text(json.dumps({'campaign':'assistant-001-v1','results':[
            {'case_id':'assistant001-t01','role':'worker','evidence_directory':str(session),'status':'success'}]}))
        row=normalize_legacy_report(summary)['cases'][0]
        self.assertEqual(row['model_identity']['name'],'synthetic-model')
        self.assertEqual(row['context_tokens'],4096)
        self.assertEqual(row['effective_configuration_observations'],[config.to_dict()['payload']])
        self.assertEqual(row['effective_settings'][0]['limits']['timeout_seconds'],30)
        self.assertIsNone(row['model_identity']['quantization'])
        wrong=config.to_dict()['payload']; wrong['model']={**identity['model'],'sha256':'f'*64}
        different=seal_evidence('effective_runtime_config','wrong-config',wrong); store.persist(different)
        events(different.reference.to_dict())
        row=normalize_legacy_report(summary)['cases'][0]
        self.assertIn('identity mismatch',row['adapter_exclusion_reason'])

    def test_legacy_project_checks_and_workbook_path_are_preserved(self):
        for campaign,count in [('assistant-001-v1',79),('assistant-002-v1',96)]:
            path=self.root/(campaign+'.json')
            source={'campaign':campaign,'track':'fixed-plan-worker-chain',
                'review_package':{'xlsx':'original/review/review-package.xlsx'},
                'results':[{'case_id':campaign+'-t06','role':'worker','status':'success',
                    'deterministic_passed':True,'human_review_required':True,'acceptance_check_count':count}]}
            path.write_text(json.dumps(source)); before=path.read_bytes()
            report=normalize_legacy_report(path)
            self.assertEqual(report['review_package'],source['review_package'])
            self.assertEqual(report['cases'][0]['acceptance_check_count'],count)
            self.assertIsNone(report['cases'][0]['suite_version'])
            self.assertEqual(path.read_bytes(),before)

    def test_qualification_summary_keeps_substantive_review_and_versions(self):
        path=self.root/'summary.json'
        source={'campaign':'qualification-v2-planner','track':'controlled_role_qualification','results':[
            {'case_id':'assistant-001-planner-v2-complete','rubric_version':'qualification-v2/planner-equivalence-v1',
             'execution_status':'success','assessed_outcome':'PASS','human_adjudication':{'verdict':'PASS'},
             'model_identity':{'name':'fake','digest':'a'*64},'custom_original_field':'preserved'}]}
        path.write_text(json.dumps(source))
        row=normalize_legacy_report(path)['cases'][0]
        self.assertEqual(row['suite_id'],'qualification-v2/blind-planner-input-v1')
        self.assertEqual(row['human_adjudication'],{'verdict':'PASS'})
        self.assertEqual(row['custom_original_field'],'preserved')
        self.assertEqual(row['model_identity']['digest'],'a'*64)

    def test_reexport_uses_original_writer_and_refuses_overwrite(self):
        from localbench.v2.report_adapter import write_normalized_review
        path=self.root/'legacy.json'
        path.write_text(json.dumps({'schema_version':'flashnext-role-review-package:v1','metadata':{},
            'case_results':[{'case_id':'tester-case-c','status':'success','deterministic_passed':True}]}))
        before=path.read_bytes()
        output=write_normalized_review(path,self.root/'new')
        self.assertTrue(Path(output['xlsx']).is_file())
        self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(FileExistsError): write_normalized_review(path,self.root/'new')


if __name__ == "__main__":
    unittest.main()
