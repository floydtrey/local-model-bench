"""T13 deterministic acceptance fixtures. All evidence and identities are synthetic."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from localbench.v2.metric_projection import case_status, project_metrics, CATALOG_VERSION
from localbench.v2.report_adapter import file_reference

ROOT = Path(__file__).resolve().parents[1]

class MetricProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = {'schema_version': CATALOG_VERSION, 'metrics': [
            {'id':'coding', 'kind':'capability', 'suite':'test', 'suite_version':'1',
             'rubric':'test-assessor', 'rubric_version':'1', 'cases':list('abcde'),
             'scoring':'independent_deterministic_case_pass', 'minimum_coverage':1,
             'repeat_policy':'all_predeclared_trials_pass'},
            {'id':'vision', 'kind':'capability', 'suite':None, 'suite_version':None,
             'rubric':None, 'rubric_version':None, 'cases':[], 'scoring':'not_tested'},
            {'id':'long_context_recall', 'kind':'capability', 'suite':None, 'suite_version':None,
             'rubric':None, 'rubric_version':None, 'cases':[], 'scoring':'not_tested'}]}
        self.counter=0

    def case(self, name='a', passed=True, **changes):
        self.counter+=1
        row={'case_id':name, 'suite_id':'test','suite_version':'1','rubric_id':'test-assessor','rubric_version':'1',
             'candidate_id':'synthetic', 'model_identity':{'name':'fake','digest':'a'*64,'quantization':'fixture'},
             'runtime_identity':{'name':'fake','version':'1','transport':'injected'}, 'context_tokens':4096,
             'effective_settings':{'temperature':0,'seed':1},'track':'controlled_role_qualification',
             'runtime_compatibility':'supported',
             'comparison_protocol':'fixture:v1','authority_assumptions':'no-authority','assessor_version':'1','evidence_version':'1',
             'run_id':'run1','trial_id':'trial1','attempt_id':f'attempt{self.counter}','attempt_index':1,
             'execution_status':'completed','assessed_outcome':'PASS' if passed else 'FAIL',
             'human_review_required':False,'human_review_status':'not_required',
             'input_sha256':'b'*64,'reference_sha256':'c'*64,'rubric_sha256':'d'*64,
             'candidate_sha256':'e'*64, 'evidence_directory':str(self.root)}
        row.update(changes)
        path=self.root/f'assessment{self.counter}.json'
        path.write_text(json.dumps({k:row.get(k) for k in ('case_id','assessed_outcome','input_sha256','candidate_sha256','rubric_sha256')}))
        row.setdefault('evidence_refs',[file_reference(path,'assessment')])
        row['assessment_file']=str(path)
        return row

    def project(self, rows, catalog=None):
        return project_metrics(rows,{},catalog or self.catalog)

    def metric(self, rows):
        return self.project(rows)['metrics'][0]

    def reviewed(self, row):
        row.update(human_review_required=True,human_review_status='recorded',human_adjudication={
            **{k:row[k] for k in ('input_sha256','candidate_sha256','rubric_sha256')},
            'review_origin':'human_declared','reviewer':'fixture-human','reviewed_at':'2026-10-09T00:00:00Z'})
        path=Path(row['assessment_file'])
        assessment=json.loads(path.read_text())
        assessment['human_adjudication']=row['human_adjudication']
        path.write_text(json.dumps(assessment))
        row['evidence_refs']=[file_reference(path,'assessment')]
        return row

    def test_genuine_pass_fail_and_zero_of_five(self):
        metric=self.metric([self.case('a'),self.case('b',False)])
        self.assertEqual((metric['numerator'],metric['denominator'],metric['percentage']),(1,2,50))
        metric=self.metric([self.case(c,False) for c in 'abcde'])
        self.assertEqual((metric['numerator'],metric['denominator'],metric['percentage']),(0,5,0))

    def test_missing_legacy_fields_never_zero_or_pass(self):
        self.assertEqual(case_status({'status':'success'}),'unknown')
        row=self.case()
        for key in ('model_identity','runtime_identity','assessed_outcome'):
            row.pop(key)
        m=self.metric([row])
        self.assertIsNone(m['percentage'])
        self.assertEqual(m['unknown_cases'],['a'])

    def test_vision_and_long_context_remain_not_tested(self):
        for m in self.project([])['metrics'][1:]:
            self.assertEqual(m['status'],'not_tested')
            self.assertIsNone(m['denominator'])
            self.assertIsNone(m['percentage'])

    def test_blocked_downstream_worker_is_not_an_attempt_or_failure(self):
        m=self.metric([self.case('a',False),self.case('b',assessed_outcome=None,execution_status='prerequisite_blocked',role='worker')])
        # Roles/protocols are separate, so locate the blocked series explicitly.
        m=next(x for x in self.project([self.case('b',assessed_outcome=None,execution_status='blocked',role='worker')])['metrics'] if x['metric_id']=='coding')
        self.assertEqual((m['attempted_cases'],m['attempt_count'],m['failed_cases']),(0,0,[]))
        self.assertEqual(m['blocked_cases'],['b'])
        self.assertIsNone(m['denominator'])

    def test_pending_review_preserves_independent_assessed_pass(self):
        result=self.project([self.case(human_review_required=True,human_review_status='pending')])
        row=result['case_details'][0]
        self.assertEqual(row['normalized_assessed_outcome'],'passed')
        self.assertEqual(row['normalized_status'],'pending_review')
        self.assertIsNone(result['metrics'][0]['percentage'])

    def test_not_required_cannot_bypass_required_human_review(self):
        row=self.case(human_review_required=True,human_adjudication='not_required',human_review_status='not_required')
        self.assertEqual(case_status(row),'pending_review')

    def test_substantive_human_record_is_supported_and_hash_bound(self):
        row=self.reviewed(self.case())
        self.assertEqual(self.metric([row])['percentage'],100)
        row['human_adjudication']['candidate_sha256']='0'*64
        self.assertIsNone(self.metric([row])['percentage'])

    def test_unsupported_and_not_attempted_have_no_score(self):
        for status in ('unsupported','not_attempted','not_tested'):
            with self.subTest(status=status):
                row=self.case(execution_status=status,assessed_outcome=None)
                self.assertEqual(case_status(row),status)
                self.assertIsNone(self.metric([row])['percentage'])
                self.assertEqual(self.metric([row])['attempt_count'],0)

    def test_infrastructure_error_is_unknown_not_model_failure(self):
        row=self.case(False,execution_status='error',deterministic_passed=False,failure_attribution='infrastructure')
        self.assertEqual(case_status(row),'unknown')
        self.assertIsNone(self.metric([row])['percentage'])

    def test_configurations_are_distinct_comparable_series(self):
        self.catalog['metrics'][0]['cases']=['a']
        a=self.case()
        b=self.case(model_identity={'name':'other','digest':'f'*64,'quantization':'Q8'})
        series=[m for m in self.project([a,b])['metrics'] if m['metric_id']=='coding']
        self.assertEqual(len(series),2)
        self.assertNotEqual(series[0]['configuration_id'],series[1]['configuration_id'])
        self.assertTrue(all(s['comparison_eligible'] for s in series))
        self.assertEqual(series[0]['comparison_group'],series[1]['comparison_group'])
        self.assertEqual([s['denominator'] for s in series],[1,1])

    def test_every_material_configuration_field_separates_series(self):
        for changes in ({'context_tokens':8192},{'effective_settings':{'temperature':1}},
                        {'transport':'different'},{'quantization':'Q8'},{'model_digest':'f'*64}):
            with self.subTest(changes=changes):
                self.assertEqual(len([m for m in self.project([self.case(),self.case(**changes)])['metrics'] if m['metric_id']=='coding']),2)

    def test_tracks_worker_modes_and_authority_are_incompatible(self):
        self.catalog['metrics'][0]['cases']=['a']
        for key,value in [('track','native_pipeline_integration'),('worker_mode','CUMULATIVE_PROJECT'),
                          ('authority_assumptions','different'),('assessor_version','2'),('evidence_version','2')]:
            with self.subTest(key=key):
                a=self.case(role='worker',worker_mode='ISOLATED_TASK')
                b=self.case(role='worker',worker_mode='ISOLATED_TASK')
                b[key]=value
                series=[m for m in self.project([a,b])['metrics'] if m['metric_id']=='coding']
                self.assertEqual(len(series),2)
                self.assertNotEqual(series[0]['comparison_group'],series[1]['comparison_group'])

    def test_changed_suite_and_rubric_are_excluded_but_discoverable(self):
        for field in ('suite_id','suite_version','rubric_id','rubric_version'):
            result=self.project([self.case(**{field:'changed'})])
            self.assertIsNone(result['metrics'][0]['percentage'])
            self.assertIn('incompatible_'+field,result['metrics'][0]['excluded'][0]['reasons'])
            self.assertEqual(len(result['case_details']),1)

    def test_first_fail_repair_pass_is_one_final_success(self):
        first=self.case(passed=False,attempt_id='first')
        repair=self.case(attempt_id='repair',attempt_index=2,parent_attempt_id='first')
        m=self.metric([first,repair])
        self.assertEqual((m['numerator'],m['denominator'],m['attempt_count']),(1,1,2))
        self.assertEqual(m['first_pass'],{'numerator':0,'denominator':1})
        self.assertEqual(m['after_repair'],{'numerator':1,'denominator':1})
        self.assertEqual((m['first_pass_successes'],m['repaired_successes']),(0,1))
        self.assertEqual(len(m['case_refs']),2)

    def test_invalid_repair_lineage_and_missing_first_attempt_are_excluded(self):
        for rows in ([self.case(attempt_index=2)], [self.case(passed=False),self.case(attempt_index=2,parent_attempt_id='wrong')]):
            self.assertIsNone(self.metric(rows)['percentage'])

    def test_repeated_trials_do_not_inflate_case_count(self):
        rows=[self.case(trial_id=f'trial{i}',trial_ordinal=i,planned_trial_count=3,repeat_group='g') for i in range(1,4)]
        m=self.metric(rows)
        self.assertEqual((m['denominator'],m['attempt_count'],m['repeated_trials']),(1,3,2))
        rows[-1]=self.case(passed=False,trial_id='trial3',trial_ordinal=3,planned_trial_count=3,repeat_group='g')
        self.assertEqual(self.metric(rows)['percentage'],0)
        self.assertIsNone(self.metric(rows[:2])['percentage'])

    def test_undeclared_repeats_and_duplicate_attempts_are_excluded(self):
        self.assertIsNone(self.metric([self.case(),self.case(trial_id='other')])['denominator'])
        a=self.case()
        self.assertIsNone(self.metric([a,a])['denominator'])

    def test_cumulative_79_and_96_checks_do_not_become_case_denominator(self):
        m=self.metric([self.case('a',acceptance_check_count=79),self.case('b',acceptance_check_count=96)])
        self.assertEqual(m['denominator'],2)
        self.assertIsNone(m['acceptance_check_count'])
        self.assertEqual([v['count'] for v in m['acceptance_checks']],[79,96])

    def test_tester_correct_fail_on_defective_code_is_success(self):
        row=self.reviewed(self.case(role='tester',candidate_decision='FAIL',implementation_truth='defective'))
        self.assertEqual(case_status(row),'passed')
        self.assertEqual(self.metric([row])['numerator'],1)

    def test_stale_hash_and_changed_artifact_are_excluded(self):
        row=self.case()
        Path(row['assessment_file']).write_text('{}')
        self.assertIn('stale_evidence_hash',self.project([row])['case_details'][0]['exclusion_reasons'])
        row=self.case(artifact_sha256='a'*64,observed_artifact_sha256='b'*64)
        self.assertIn('stale_artifact_hash',self.project([row])['case_details'][0]['exclusion_reasons'])

    def test_missing_evidence_is_discoverable_and_not_zero(self):
        row=self.case()
        Path(row['assessment_file']).unlink()
        result=self.project([row])
        self.assertIsNone(result['metrics'][0]['percentage'])
        self.assertEqual(result['metrics'][0]['case_refs'][0]['evidence_refs'][0]['integrity'],'unavailable')

    def test_changed_summary_cannot_override_assessment(self):
        row=self.case(passed=False)
        row['assessed_outcome']='PASS'
        self.assertIn('assessment_outcome_mismatch',self.project([row])['case_details'][0]['exclusion_reasons'])
        self.assertIsNone(self.metric([row])['percentage'])

    def test_contradictions_preserve_execution_and_assessment(self):
        row=self.case(execution_status='not_attempted')
        result=self.project([row])
        self.assertEqual(result['case_details'][0]['assessed_outcome'],'PASS')
        self.assertEqual(result['case_details'][0]['normalized_status'],'not_attempted')
        self.assertIsNone(result['metrics'][0]['percentage'])
        self.assertIn('execution_assessment_contradiction',result['case_details'][0]['exclusion_reasons'])

    def test_role_suitability_requires_coverage_and_review_and_no_automatic_assignment(self):
        d=self.catalog['metrics'][0]
        d.update(kind='role_suitability',human_review=True)
        m=self.metric([self.reviewed(self.case())])
        self.assertEqual(m['suitability'],'insufficient_evidence')
        m=self.metric([self.case(human_review_required=True)])
        self.assertEqual(m['suitability'],'provisional_review_pending')
        rows=[self.reviewed(self.case(c)) for c in 'abcde']
        self.assertEqual(self.metric(rows)['suitability'],'provisional_reference_review_pending')
        for row in rows:
            row['reference_review_status']='human_approved'
            path=self.root/(row['case_id']+'-reference.json')
            path.write_text(json.dumps({**{k:row[k] for k in ('suite_id','suite_version','rubric_version','reference_sha256')},
                'review_origin':'human_declared','reviewer':'fixture','reviewed_at':'2026-10-09','verdict':'APPROVED'}))
            row['evidence_refs'].append(file_reference(path,'reference_review'))
        self.assertEqual(self.metric(rows)['suitability'],'reviewed_evidence_supports_criteria')
        self.assertIsNone(self.metric(rows)['percentage'])
        rows[0]['critical_unsafe_approval']=True
        self.assertEqual(self.metric(rows)['suitability'],'criteria_not_met')
        self.assertFalse(self.project(rows)['automatic_role_assignment'])

    def test_input_changes_and_partial_populations_cannot_compare(self):
        self.assertFalse(self.metric([self.case()])['comparison_eligible'])
        rows=[self.case(),self.case(input_sha256='f'*64)]
        self.assertIsNone(self.metric(rows)['percentage'])
        self.assertIn('incompatible_material_inputs',self.metric(rows)['excluded'][0]['reasons'])

    def test_catalog_uses_real_evaluator_and_case_memberships(self):
        catalog=json.loads((ROOT/'docs/qualification-v2/METRIC_CATALOG_V1.json').read_text())
        self.assertEqual(len(catalog['metrics']),16)
        for metric in catalog['metrics']:
            for key in ('definition','measurement_objective','scoring_authority','numerator','denominator','exclusions',
                        'minimum_coverage','repeat_policy','repair_policy','human_adjudication','evidence_policy','comparison_policy'):
                self.assertIn(key,metric)
            if metric['kind']=='role_suitability':
                self.assertGreater(metric['suitability_criteria']['minimum_cases'],0)
                self.assertIsNone(metric['suitability_criteria']['numeric_threshold'])
            for source in metric['sources']:
                if source['suite_id'].startswith('shared-'):
                    pack=json.loads((ROOT/source['definition_source']).read_text())
                    cases={c['case_id']:c for c in pack['cases']}
                    for case in source['cases']:
                        self.assertIn({'evaluator_id':source['rubric_id'],'contract_version':source['rubric_version']},cases[case]['evaluators'])
        coding=next(m for m in catalog['metrics'] if m['id']=='coding')
        self.assertNotIn('multi-file-synthesis',coding['cases'])
        for id in ('tool_selection','error_recovery'):
            self.assertEqual(next(m for m in catalog['metrics'] if m['id']==id)['scoring'],'insufficient_coverage')

    def test_expected_planner_block_is_success_only_with_review_and_executed_case(self):
        d=self.catalog['metrics'][0]
        d['sources']=[{'suite_id':'test','suite_version':'1','rubric_id':'test-assessor','rubric_version':'1',
                       'cases':['a'],'successful_assessed_outcomes':{'a':['BLOCKED']}}]
        row=self.reviewed(self.case(assessed_outcome='BLOCKED'))
        result=self.project([row])
        self.assertEqual(result['case_details'][0]['assessed_outcome'],'BLOCKED')
        self.assertEqual(result['metrics'][0]['numerator'],1)
        row['execution_status']='blocked'
        self.assertIsNone(self.metric([row])['numerator'])

    def test_unrelated_hashed_file_is_not_an_assessment(self):
        row=self.case()
        path=Path(row['assessment_file']); path.write_text('{}')
        row['evidence_refs']=[file_reference(path,'assessment')]
        self.assertIsNone(self.metric([row])['percentage'])
        self.assertIn('unassessed_evidence',self.project([row])['case_details'][0]['exclusion_reasons'])

    def test_comparison_pairs_explain_incompatibility(self):
        self.catalog['metrics'][0]['cases']=['a']
        result=self.project([self.case(),self.case(track='native_pipeline_integration')])
        self.assertFalse(result['comparisons'][0]['eligible'])
        self.assertIn('different_track',result['comparisons'][0]['exclusion_reasons'])

    def test_unknown_configuration_labels_do_not_score(self):
        for changes in ({'model_digest':'unknown'},{'quantization':'unknown'},{'effective_settings':{}}):
            self.assertIsNone(self.metric([self.case(**changes)])['percentage'])

    def test_rehashed_changed_artifact_cannot_match_original_identity(self):
        row=self.case()
        artifact=self.root/'candidate.txt'; artifact.write_text('original')
        row['artifact_sha256']={'candidate.txt':hashlib.sha256(artifact.read_bytes()).hexdigest()}
        artifact.write_text('changed')
        row['evidence_refs'].append(file_reference(artifact,'artifact',artifact_key='candidate.txt'))
        self.assertIn('stale_artifact_hash',self.project([row])['case_details'][0]['exclusion_reasons'])
        self.assertIsNone(self.metric([row])['percentage'])

    def test_absent_legacy_first_pass_and_repair_fields_stay_unknown(self):
        row=self.case()
        row.pop('attempt_index')
        m=self.metric([row])
        self.assertEqual(m['numerator'],1)
        self.assertIsNone(m['first_pass'])
        self.assertIsNone(m['after_repair'])
        self.assertIsNone(m['first_pass_successes'])
        self.assertIsNone(m['repaired_successes'])

if __name__=='__main__': unittest.main()
