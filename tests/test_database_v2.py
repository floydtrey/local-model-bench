"""Stage A synthetic storage tests only: no runner, model or candidate program."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from localbench.database_v2 import connect, transaction, record_identity, backup, restore, verify_backup
from localbench.database_v2.store import DatabaseError, Migration, migrate, migrations, validate_schema, wal_runtime_safe


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Explicit isolated schema validation on native runtime, not operational.
        self.db = connect(self.root/'test.sqlite3',validation_only=True)
        self.addCleanup(self.db.close)
        self.insert('sources',id='source',kind='synthetic_test',format_version='1',location='fixture',
                    sha256='a'*64,captured_at='2026-10-09T00:00:00Z',producer_version='test',metadata_json='{}')

    def insert(self,table,**values):
        self.db.execute('INSERT INTO '+table+'('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))

    def foundation(self):
        record_identity(self.db,'models',id='model',source_id='source',version='v2',payload={'name':'test','digest':None})
        record_identity(self.db,'runtime_configs',id='config',source_id='source',version='v3',model_id='model',payload={'context':4096,'temperature':0})
        self.insert('suites',id='suite',name='fixture',version='1',source_id='source',definition_json='{}')
        self.insert('cases',id='case',logical_id='C01',version='1',source_id='source',input_sha256='b'*64,definition_json='{}')
        self.insert('suite_cases',suite_id='suite',case_id='case',position=1)
        self.insert('protocols',id='protocol',name='fixture',version='1',source_id='source',track='L0',definition_json='{}')
        self.insert('environments',id='environment',source_id='source',version='v2',facts_json='{}',captured_at='now')
        self.make_run('run')
        self.trial('trial','run')
        self.insert('assessors',id='assessor',name='test',version='1',implementation_sha256='c'*64,source_id='source',definition_json='{}')
        self.insert('protocol_evidence_requirements',protocol_id='protocol',purpose='candidate',minimum_count=1)

    # Do not call this helper run: unittest owns TestCase.run.
    def make_run(self,id,config='config',protocol='protocol',suite='suite'):
        self.insert('runs',id=id,source_id='source',suite_id=suite,protocol_id=protocol,config_id=config,
                    environment_id='environment',created_at='now',origin='synthetic_test',manifest_json='{}')

    def trial(self,id,run,ordinal=1,case='case',suite='suite'):
        self.insert('trials',id=id,run_id=run,suite_id=suite,case_id=case,ordinal=ordinal,planned_trials=2,repeat_group='repeat',source_id='source')

    def attempt(self,id='attempt',trial='trial',status='completed',index=1,parent=None,parent_index=None):
        self.insert('attempts',id=id,trial_id=trial,attempt_index=index,parent_id=parent,parent_index=parent_index,
                    source_id='source',execution_status=status,exit_code=0,observations_json='{}')

    def artifact(self,id='artifact',integrity='verified',path=None):
        content=b'synthetic evidence\n'
        path=path or id+'.txt'
        if integrity=='verified':
            target=self.root/'evidence'/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(content)
        self.insert('artifacts',id=id,source_id='source',relative_path=path,sha256=sha256(content).hexdigest() if integrity=='verified' else None,
                    byte_count=len(content) if integrity=='verified' else None,media_type='text/plain',integrity=integrity,verified_at='now' if integrity=='verified' else None)

    def assessment(self,id='assessment',attempt='attempt',outcome='PASS',artifact='artifact',protocol='protocol',**extra):
        self.insert('assessments',id=id,attempt_id=attempt,assessor_id='assessor',protocol_id=protocol,
                    source_id='source',artifact_id=artifact,outcome=outcome,detail_json='{}',**extra)

    def result(self,id='result',attempt='attempt',assessment='assessment',outcome='PASS'):
        self.insert('committed_results',id=id,attempt_id=attempt,assessment_id=assessment,outcome=outcome,
                    source_id='source',committed_at='now',snapshot_artifact_id='artifact')

    def metric(self,id='metric-result',run='run',config='config',metric='metric',population='{}',**extra):
        self.insert('metric_results',id=id,metric_id=metric,run_id=run,config_id=config,source_id='source',
                    projection_version='T13:v2',status='measured',population_json=population,**extra)

    def test_native_version_policy_is_explicit_and_fail_closed(self):
        for version in [(3,49,1),(3,51,2),(3,44,5),(3,50,6),(3,45,0)]:
            self.assertFalse(wal_runtime_safe(version),version)
        for version in [(3,44,6),(3,44,7),(3,50,7),(3,50,8),(3,51,3),(3,52,0)]:
            self.assertTrue(wal_runtime_safe(version),version)
        path=self.root/'never-created.sqlite3'
        with patch('localbench.database_v2.store.wal_runtime_safe',return_value=False):
            with self.assertRaises(DatabaseError): connect(path)
        self.assertFalse(path.exists())

    def test_durability_pragmas_and_schema_are_deterministic(self):
        for name,value in [('journal_mode','wal'),('synchronous',2),('foreign_keys',1),('recursive_triggers',1),('busy_timeout',5000),('user_version',len(migrations()))]:
            self.assertEqual(self.db.execute('PRAGMA '+name).fetchone()[0],value)
        other=connect(self.root/'other.sqlite3',validation_only=True)
        try:
            query="SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            self.assertEqual(self.db.execute(query).fetchall(),other.execute(query).fetchall())
            self.assertEqual(validate_schema(other),len(migrations()))
        finally: other.close()

    def test_migration_replay_does_not_change_ledger(self):
        before=self.db.execute('SELECT * FROM schema_migrations').fetchall()
        migrate(self.db)
        self.assertEqual(before,self.db.execute('SELECT * FROM schema_migrations').fetchall())

    def test_v1_upgrade_and_failed_batch_are_atomic(self):
        con=sqlite3.connect(self.root/'upgrade.sqlite3',isolation_level=None)
        try:
            first=migrations()[0]
            migrate(con,[first])
            con.execute("INSERT INTO sources VALUES('s','test',NULL,'p',?,'now',NULL,'{}')",('d'*64,))
            bad=Migration(2,'002_bad.sql','CREATE TABLE partial (id TEXT);\nINSERT INTO absent VALUES(1);\n')
            with self.assertRaises(sqlite3.OperationalError): migrate(con,[first,bad])
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone())
            self.assertEqual(con.execute('SELECT count(*) FROM sources').fetchone()[0],1)
            migrate(con)
            self.assertEqual(validate_schema(con),len(migrations()))
            self.assertEqual(con.execute('SELECT count(*) FROM sources').fetchone()[0],1)
        finally: con.close()

    def test_newer_tampered_foreign_and_noncontiguous_schemas_rejected(self):
        with self.assertRaises(DatabaseError): migrate(self.db,[replace(migrations()[0],sql=migrations()[0].sql+'\n-- tampered\n'),*migrations()[1:]])
        self.db.execute('PRAGMA user_version='+str(len(migrations())+1))
        with self.assertRaises(DatabaseError): migrate(self.db)
        self.db.execute('PRAGMA user_version='+str(len(migrations())))
        with self.assertRaises(DatabaseError): migrate(self.db,[migrations()[1]])
        foreign=sqlite3.connect(':memory:',isolation_level=None)
        try:
            foreign.execute('CREATE TABLE foreign_data(id TEXT)')
            with self.assertRaises(DatabaseError): migrate(foreign)
            self.assertEqual(foreign.execute('PRAGMA application_id').fetchone()[0],0)
        finally: foreign.close()

    def test_all_immutable_tables_block_update_delete(self):
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE sources SET location='changed'")
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM sources')
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE schema_migrations SET sha256='bad'")
        tables={x[0] for x in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        triggers={x[0] for x in self.db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        for table in tables:
            self.assertIn('immutable_'+table+'_update',triggers)
            self.assertIn('immutable_'+table+'_delete',triggers)

    def test_transaction_rollback_preserves_prior_records(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with transaction(self.db):
                self.insert('sources',id='pending',kind='test',location='pending',sha256='e'*64,captured_at='now',metadata_json='{}')
                self.insert('models',id='bad',source_id='absent',version='1',identity_json='{}',identity_sha256='f'*64)
        self.assertEqual(self.db.execute('SELECT id FROM sources').fetchall(),[('source',)])
        with transaction(self.db):
            with self.assertRaises(DatabaseError):
                with transaction(self.db): pass

    def test_model_discovery_is_independent_and_configs_never_merge(self):
        self.foundation()
        digest=record_identity(self.db,'runtime_configs',id='other',source_id='source',version='v3',model_id='model',payload={'context':8192,'temperature':0})
        self.assertNotEqual(digest,self.db.execute("SELECT config_sha256 FROM runtime_configs WHERE id='config'").fetchone()[0])
        self.insert('discovery_observations',id='absent',source_id='source',model_id='model',observed_at='now',installation='fixture',tag='same-tag',state='absent',observation_json='{}')
        self.assertEqual(self.db.execute('SELECT count(*) FROM runs').fetchone()[0],1)
        record_identity(self.db,'models',id='model',source_id='source',version='v2',payload={'digest':None,'name':'test'})
        with self.assertRaises(DatabaseError): record_identity(self.db,'models',id='model',source_id='source',version='v2',payload={'name':'changed'})
        with self.assertRaises(sqlite3.IntegrityError): record_identity(self.db,'models',id='alias',source_id='source',version='v2',payload={'name':'test','digest':None})

    def test_suite_membership_and_run_binding_enforced(self):
        self.foundation()
        self.insert('suites',id='other-suite',name='other',version='1',source_id='source',definition_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): self.trial('wrong','run',suite='other-suite')
        with self.assertRaises(sqlite3.IntegrityError): self.trial('absent-case','run',case='absent')
        with self.assertRaises(sqlite3.IntegrityError): self.trial('duplicate','run')

    def test_repeats_and_repairs_remain_one_distinct_case(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment(outcome='FAIL')
        self.attempt('repair',index=2,parent='attempt',parent_index=1)
        self.assessment('repair-assessment',attempt='repair')
        self.trial('repeat','run',ordinal=2); self.attempt('repeat-attempt',trial='repeat')
        self.assertEqual(self.db.execute('SELECT count(DISTINCT case_id),count(*) FROM trials').fetchone(),(1,2))
        self.assertEqual(self.db.execute('SELECT count(*) FROM attempts').fetchone()[0],3)
        with self.assertRaises(sqlite3.IntegrityError): self.attempt('skip',index=4,parent='repair',parent_index=2)
        with self.assertRaises(sqlite3.IntegrityError): self.attempt('cross',trial='repeat',index=2,parent='attempt',parent_index=1)
        with self.assertRaises(sqlite3.IntegrityError): self.attempt('not-failed',index=3,parent='repair',parent_index=2)

    def test_execution_exit_zero_never_creates_qualification(self):
        self.foundation(); self.attempt(); self.artifact()
        with self.assertRaises(sqlite3.IntegrityError): self.result(assessment=None)
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone()[0],0)

    def test_blocked_incomplete_unsupported_unknown_have_no_invented_score(self):
        self.foundation(); self.artifact()
        for ordinal,(status,outcome) in enumerate([('blocked','BLOCKED'),('interrupted','INCOMPLETE'),('unsupported','UNSUPPORTED'),('not_tested','NOT_TESTED')],1):
            if ordinal>1: self.trial('t'+str(ordinal),'run',ordinal=2) if ordinal==2 else self.make_new_case_trial(ordinal)
            trial='trial' if ordinal==1 else 't'+str(ordinal)
            self.attempt('a'+str(ordinal),trial=trial,status=status)
            self.assessment('s'+str(ordinal),attempt='a'+str(ordinal),outcome=outcome)
            self.result('r'+str(ordinal),attempt='a'+str(ordinal),assessment='s'+str(ordinal),outcome=outcome)
            with self.assertRaises(sqlite3.IntegrityError): self.assessment('bad'+str(ordinal),attempt='a'+str(ordinal),outcome='PASS')
        self.assertEqual(self.db.execute('SELECT score FROM assessments').fetchall(),[(None,)]*4)

    def make_new_case_trial(self,index):
        case='case'+str(index)
        self.insert('cases',id=case,logical_id=case,version='1',source_id='source',input_sha256='b'*64,definition_json='{}')
        self.insert('suite_cases',suite_id='suite',case_id=case,position=index)
        self.trial('t'+str(index),'run',case=case)

    def test_tester_success_can_detect_defective_subject(self):
        self.foundation(); self.attempt(); self.artifact()
        self.assessment(implementation_truth='defective',candidate_decision='FAIL',outcome='PASS',acceptance_checks=79,check_unit='cumulative_checks_at_task')
        self.assertEqual(self.db.execute('SELECT outcome,implementation_truth,candidate_decision FROM assessments').fetchone(),('PASS','defective','FAIL'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM trials').fetchone()[0],1)

    def test_assessment_protocol_and_result_attempt_binding(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment()
        self.insert('protocols',id='other-protocol',name='other',version='1',source_id='source',track='L1',definition_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): self.assessment('bad-protocol',protocol='other-protocol')
        self.trial('repeat','run',ordinal=2); self.attempt('other',trial='repeat')
        with self.assertRaises(sqlite3.IntegrityError): self.result(attempt='other')
        with self.assertRaises(sqlite3.IntegrityError): self.result(outcome='FAIL')

    def test_success_requires_required_verified_evidence(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment()
        with self.assertRaises(sqlite3.IntegrityError): self.result()
        self.artifact('missing',integrity='missing')
        self.insert('attempt_artifacts',attempt_id='attempt',artifact_id='missing',purpose='candidate',required=1)
        with self.assertRaises(sqlite3.IntegrityError): self.result()
        self.result(outcome='UNKNOWN',assessment=None)
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone()[0],'UNKNOWN')

    def test_per_case_publication_rolls_back_without_losing_completed_case(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment()
        self.insert('attempt_artifacts',attempt_id='attempt',artifact_id='artifact',purpose='candidate',required=1)
        self.result()
        self.trial('repeat','run',ordinal=2); self.attempt('other',trial='repeat')
        with self.assertRaises(sqlite3.IntegrityError):
            with transaction(self.db):
                self.assessment('other-assessment',attempt='other')
                self.result('other-result',attempt='other',assessment='other-assessment')
        self.assertEqual(self.db.execute('SELECT id FROM committed_results').fetchall(),[('result',)])
        self.assertIsNone(self.db.execute("SELECT id FROM assessments WHERE id='other-assessment'").fetchone())

    def test_evidence_hash_shape_path_and_provenance_constraints(self):
        for path in ['../secret','C:/secret','/absolute','dir/../secret','dir\\secret','./secret','dir//file']:
            with self.assertRaises(sqlite3.IntegrityError): self.artifact('bad',integrity='missing',path=path)
        with self.assertRaises(sqlite3.IntegrityError): self.insert('artifacts',id='bad',source_id='source',relative_path='safe',media_type='text',integrity='verified')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('artifacts',id='bad',source_id='absent',relative_path='safe',media_type='text',integrity='missing')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('sources',id='bad',kind='test',location='bad',sha256='z'*64,captured_at='now',metadata_json='{}')

    def test_review_is_append_only_and_cannot_authorize_execution(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment()
        self.insert('reviews',id='review',assessment_id='assessment',source_id='source',artifact_id='artifact',kind='technical',status='completed',reviewer='declaration',identity_verified=0,recorded_at='now',binding_json='{}')
        self.insert('reviews',id='next-review',assessment_id='assessment',source_id='source',artifact_id='artifact',supersedes_id='review',kind='technical',status='completed',identity_verified=0,recorded_at='later',binding_json='{}')
        self.assertEqual(self.db.execute('SELECT count(*) FROM reviews').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM queue_items').fetchone()[0],0)
        with self.assertRaises(sqlite3.IntegrityError): self.insert('reviews',id='bad-review',assessment_id='assessment',source_id='source',artifact_id='artifact',supersedes_id='review',kind='human',status='completed',identity_verified=0,recorded_at='later',binding_json='{}')

    def test_comparison_config_separation_and_protocol_exclusion(self):
        self.foundation()
        self.insert('metric_definitions',id='metric',name='coding',version='1',source_id='source',kind='capability',definition_json='{}')
        self.metric(numerator=0,denominator=1,percentage=0)
        record_identity(self.db,'runtime_configs',id='config2',source_id='source',version='v3',model_id='model',payload={'context':8192})
        self.make_run('run2',config='config2'); self.metric('metric2','run2','config2',numerator=1,denominator=1,percentage=100)
        self.insert('comparison_decisions',id='compatible',left_metric_id='metric-result',right_metric_id='metric2',source_id='source',policy_version='T13:v2',eligible=1,reasons_json='[]')
        self.insert('protocols',id='protocol2',name='fixture',version='2',source_id='source',track='L0',definition_json='{}')
        self.make_run('run3',protocol='protocol2'); self.metric('metric3','run3')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('comparison_decisions',id='incompatible',left_metric_id='metric-result',right_metric_id='metric3',source_id='source',policy_version='T13:v2',eligible=1,reasons_json='[]')
        self.insert('comparison_decisions',id='excluded',left_metric_id='metric-result',right_metric_id='metric3',source_id='source',policy_version='T13:v2',eligible=0,reasons_json='["different_protocol"]')
        with self.assertRaises(sqlite3.IntegrityError): self.metric('wrong-config',config='config2')
        with self.assertRaises(sqlite3.IntegrityError): self.metric('bad-zero',numerator=0,denominator=0,percentage=0)

    def test_role_metric_has_no_percentage_and_unknown_is_null(self):
        self.foundation()
        self.insert('metric_definitions',id='metric',name='worker',version='1',source_id='source',kind='role_suitability',definition_json='{}')
        self.metric()
        self.assertIsNone(self.db.execute('SELECT percentage FROM metric_results').fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError): self.metric('bad',numerator=1,denominator=1,percentage=100)

    def test_import_idempotence_and_unknown_fields_survive(self):
        self.insert('import_mappings',id='map:v1',version='1',implementation_sha256='a'*64,definition_json='{}',source_id='source')
        values=dict(id='import',source_id='source',mapping_id='map:v1',source_pointer='/cases/0',status='excluded',unknown_fields_json='{"unrecognized":17}')
        self.insert('import_records',**values)
        with self.assertRaises(sqlite3.IntegrityError): self.insert('import_records',**dict(values,id='replay'))
        self.insert('import_exceptions',id='exception',import_id='import',reason='missing_evidence',detail_json='{}')
        self.assertEqual(json.loads(self.db.execute('SELECT unknown_fields_json FROM import_records').fetchone()[0]),{'unrecognized':17})

    def test_queue_single_owner_single_active_and_recovery_does_not_start(self):
        self.insert('controller_identity',singleton=1,name='existing-queue-process-controller',source_id='source')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('controller_identity',singleton=2,name='existing-queue-process-controller',source_id='source')
        self.insert('queue_snapshots',id='snapshot',controller_id=1,source_id='source',version='v2',captured_at='now',state='Running',state_json='{}')
        self.insert('queue_items',snapshot_id='snapshot',item_id='one',position=1,state='Running',observations_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('queue_items',snapshot_id='snapshot',item_id='two',position=2,state='Running',observations_json='{}')
        self.insert('recovery_records',id='recovery',controller_id=1,source_id='source',queue_snapshot_id='snapshot',observed_at='now',disposition='owner_action_required',detail_json='{}')
        self.assertEqual(self.db.execute('SELECT state FROM queue_items').fetchone()[0],'Running')
        # Recovery stores observation only, not a second controller or auto-rerun.

    def test_public_approval_never_confers_queue_control(self):
        self.artifact('public'); self.artifact('approval')
        self.insert('publication_records',id='publication',dataset_version='1',sanitizer_version='1',source_id='source',approved_by='test-owner',approved_at='now',public_artifact_id='public',approval_artifact_id='approval',manifest_json='{}')
        self.assertEqual(self.db.execute('SELECT count(*) FROM controller_identity').fetchone()[0],0)

    def test_backup_snapshot_includes_wal_and_restore_preserves_hashes(self):
        self.artifact(); self.artifact('missing',integrity='missing')
        self.db.execute('PRAGMA wal_autocheckpoint=0')
        before=self.db.execute('SELECT * FROM sources').fetchall()
        manifest=backup(self.db,self.root/'evidence',self.root/'backup')
        self.assertEqual(manifest['unavailable_artifacts'],[{'id':'missing','integrity':'missing'}])
        restore(self.root/'backup',self.root/'restored')
        restored=sqlite3.connect(self.root/'restored'/'database.sqlite3')
        try:
            self.assertEqual(restored.execute('SELECT * FROM sources').fetchall(),before)
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally: restored.close()
        self.assertEqual((self.root/'restored'/'artifacts'/'artifact.txt').read_bytes(),b'synthetic evidence\n')
        self.assertEqual(verify_backup(self.root/'backup'),manifest)
        with self.assertRaises(FileExistsError): restore(self.root/'backup',self.root/'restored')

    def test_backup_corruption_and_missing_required_artifact_fail_without_promotion(self):
        self.artifact()
        (self.root/'evidence'/'artifact.txt').write_bytes(b'tampered')
        with self.assertRaises(DatabaseError): backup(self.db,self.root/'evidence',self.root/'failed')
        self.assertFalse((self.root/'failed').exists())
        (self.root/'evidence'/'artifact.txt').write_bytes(b'synthetic evidence\n')
        backup(self.db,self.root/'evidence',self.root/'backup')
        (self.root/'backup'/'artifacts'/'artifact.txt').unlink()
        with self.assertRaises(FileNotFoundError): restore(self.root/'backup',self.root/'failed-restore')
        self.assertFalse((self.root/'failed-restore').exists())

    def test_backup_manifest_traversal_extra_files_and_registry_tamper_rejected(self):
        self.artifact(); backup(self.db,self.root/'evidence',self.root/'backup')
        path=self.root/'backup'/'manifest.json'
        original=path.read_text()
        manifest=json.loads(original); manifest['files'][1]['path']='../secret'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(DatabaseError): verify_backup(self.root/'backup')
        path.write_text(original)
        extra=self.root/'backup'/'unexpected'; extra.write_text('extra')
        with self.assertRaises(DatabaseError): verify_backup(self.root/'backup')
        extra.unlink()
        manifest=json.loads(original); manifest['files']=manifest['files'][:1]; path.write_text(json.dumps(manifest))
        with self.assertRaises(DatabaseError): verify_backup(self.root/'backup')

    def test_backup_inside_transaction_refuses_and_keeps_destination_absent(self):
        with transaction(self.db):
            with self.assertRaises(DatabaseError): backup(self.db,self.root/'evidence',self.root/'failed')
        self.assertFalse((self.root/'failed').exists())

    def test_scheduled_identity_finalizes_via_immutable_lifecycle_observations(self):
        self.foundation(); self.attempt(status='scheduled'); self.artifact()
        with self.assertRaises(sqlite3.IntegrityError): self.assessment()
        def event(sequence,stage):
            self.insert('lifecycle_events',id='event'+str(sequence),attempt_id='attempt',sequence=sequence,
                        occurred_at='now',stage=stage,source_id='source',detail_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): event(1,'execution_completed')
        event(1,'started')
        with self.assertRaises(sqlite3.IntegrityError): self.assessment()
        with self.assertRaises(sqlite3.IntegrityError): event(3,'execution_completed')
        event(2,'execution_completed'); event(3,'evidence_finalized')
        self.assessment(); self.insert('attempt_artifacts',attempt_id='attempt',artifact_id='artifact',purpose='candidate',required=1)
        self.result()
        self.assertEqual(self.db.execute('SELECT execution_status FROM attempts').fetchone()[0],'scheduled')
        self.assertEqual(self.db.execute('SELECT execution_status FROM attempt_execution_state').fetchone()[0],'completed')
        with self.assertRaises(sqlite3.IntegrityError): event(4,'started')
        self.assertEqual(self.db.execute('SELECT count(*) FROM committed_results').fetchone()[0],1)

    def test_additive_v2_upgrade_preserves_terminal_snapshot_and_hash_constraints(self):
        con=sqlite3.connect(self.root/'v2.sqlite3',isolation_level=None)
        try:
            migrate(con,migrations()[:2])
            con.execute("INSERT INTO sources VALUES('s','test',NULL,'p',?,'now',NULL,'{}')",('d'*64,))
            migrate(con)
            self.assertEqual(validate_schema(con),len(migrations()))
            self.assertEqual(con.execute('SELECT count(*) FROM sources').fetchone()[0],1)
        finally: con.close()
        self.foundation()
        with self.assertRaises(sqlite3.IntegrityError): self.insert('cases',id='bad',logical_id='bad',version='1',source_id='source',input_sha256='wrong',definition_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('assessors',id='bad',name='bad',version='1',source_id='source',implementation_sha256='wrong',definition_json='{}')

    def test_protocol_required_purposes_and_completed_review_integrity(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment()
        self.insert('attempt_artifacts',attempt_id='attempt',artifact_id='artifact',purpose='candidate',required=1)
        self.insert('protocol_evidence_requirements',protocol_id='protocol',purpose='trace',minimum_count=1)
        with self.assertRaises(sqlite3.IntegrityError): self.result()
        self.insert('attempt_artifacts',attempt_id='attempt',artifact_id='artifact',purpose='trace',required=1)
        self.result()
        self.artifact('missing',integrity='missing')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('reviews',id='bad',assessment_id='assessment',source_id='source',artifact_id='missing',kind='human',status='completed',identity_verified=0,recorded_at='now',binding_json='{}')

    def test_numeric_affinity_cannot_manufacture_counts_or_scores(self):
        self.foundation(); self.attempt(); self.artifact()
        for index,values in enumerate([{'score':'unknown','maximum_score':'unknown'}, {'score':float('inf'),'maximum_score':float('inf')}, {'acceptance_checks':'unknown','check_unit':'checks'}]):
            with self.subTest(values=values):
                with self.assertRaises(sqlite3.IntegrityError): self.assessment('bad'+str(index),**values)
        self.insert('cases',id='typed-case',logical_id='typed-case',version='1',source_id='source',input_sha256='b'*64,definition_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): self.insert('suite_cases',suite_id='suite',case_id='typed-case',position=1.5)
        self.insert('metric_definitions',id='metric',name='coding',version='1',source_id='source',kind='capability',definition_json='{}')
        with self.assertRaises(sqlite3.IntegrityError): self.metric(numerator='unknown',denominator='unknown')
        self.metric(numerator=0,denominator=1,percentage=0)
        self.assertEqual(self.db.execute('SELECT numerator,percentage FROM metric_results').fetchone(),(0,0.0))

    def test_type_migration_rejects_existing_invalid_rows_atomically(self):
        con=sqlite3.connect(self.root/'untyped.sqlite3',isolation_level=None)
        try:
            migrate(con,migrations()[:3])
            # A real SQLite-affinity loophole, retained to prove upgrade rejection.
            con.execute("INSERT INTO sources VALUES('s','test',NULL,'p',?,'now',NULL,'{}')",('d'*64,))
            con.execute("INSERT INTO models VALUES('m','s','1','{}',?)",('b'*64,))
            con.execute("INSERT INTO discovery_observations VALUES('d','s','m','now','fixture','tag','present','{}')")
            con.execute("INSERT INTO artifacts VALUES('a','s','a.txt',NULL,'unknown','text/plain','missing',NULL)")
            with self.assertRaises(sqlite3.IntegrityError): migrate(con)
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(con.execute("SELECT byte_count FROM artifacts WHERE id='a'").fetchone()[0],'unknown')
            self.assertEqual(con.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'typed_%'").fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],3)
        finally: con.close()

    def test_replacement_insert_cannot_rewrite_committed_evidence_config_or_result(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment()
        self.insert('attempt_artifacts',attempt_id='attempt',artifact_id='artifact',purpose='candidate',required=1)
        self.result()
        tables=['artifacts','runtime_configs','committed_results','runs']
        before={table:self.db.execute('SELECT * FROM '+table).fetchall() for table in tables}
        for recursive in (0,1):
            self.db.execute('PRAGMA recursive_triggers='+str(recursive))
            statements=[
                "INSERT OR REPLACE INTO artifacts SELECT id,source_id,relative_path,NULL,NULL,media_type,'missing',NULL FROM artifacts WHERE id='artifact'",
                "INSERT OR REPLACE INTO runtime_configs SELECT id,source_id,model_id,version,'{\"context\":8192}',? FROM runtime_configs WHERE id='config'",
                "INSERT OR REPLACE INTO committed_results SELECT 'replacement-result',attempt_id,assessment_id,outcome,source_id,committed_at,snapshot_artifact_id FROM committed_results",
            ]
            for sql in statements:
                with self.subTest(recursive=recursive,sql=sql):
                    with self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql,('f'*64,) if '?' in sql else ())
            self.assertEqual({table:self.db.execute('SELECT * FROM '+table).fetchall() for table in tables},before)
            self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(validate_schema(self.db),len(migrations()))
        self.db.execute('PRAGMA recursive_triggers=ON')
        manifest=backup(self.db,self.root/'evidence',self.root/'retained-evidence')
        self.assertEqual(manifest['unavailable_artifacts'],[])
        self.assertEqual(self.db.execute('SELECT outcome FROM committed_results').fetchone()[0],'PASS')

    def test_replacement_alternate_unique_conflicts_preserve_unreferenced_history(self):
        self.foundation(); self.artifact('unused')
        record_identity(self.db,'runtime_configs',id='unused-config',source_id='source',version='v3',model_id='model',payload={'context':8192})
        record_identity(self.db,'models',id='unused-model',source_id='source',version='v2',payload={'name':'unused-model'})
        self.insert('sources',id='unused-source',kind='test',location='unreferenced',sha256='d'*64,captured_at='now',metadata_json='{}')
        tables=['artifacts','runtime_configs','models','sources']
        before={table:self.db.execute('SELECT * FROM '+table+' ORDER BY id').fetchall() for table in tables}
        self.db.execute('PRAGMA recursive_triggers=OFF')
        statements=[
            "INSERT OR REPLACE INTO artifacts SELECT 'new-artifact',source_id,relative_path,sha256,byte_count,media_type,integrity,verified_at FROM artifacts WHERE id='unused'",
            "INSERT OR REPLACE INTO runtime_configs SELECT 'new-config',source_id,model_id,version,config_json,config_sha256 FROM runtime_configs WHERE id='unused-config'",
            "INSERT OR REPLACE INTO models SELECT 'new-model',source_id,version,identity_json,identity_sha256 FROM models WHERE id='unused-model'",
            "INSERT OR REPLACE INTO sources SELECT 'new-source',kind,format_version,location,sha256,captured_at,producer_version,metadata_json FROM sources WHERE id='unused-source'",
        ]
        for sql in statements:
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
        self.assertEqual({table:self.db.execute('SELECT * FROM '+table+' ORDER BY id').fetchall() for table in tables},before)
        self.db.execute('PRAGMA recursive_triggers=ON')

    def test_null_parent_cannot_bypass_same_trial_immediate_predecessor(self):
        self.foundation(); self.attempt(); self.artifact(); self.assessment(outcome='FAIL')
        self.make_run('other-run'); self.trial('other-trial','other-run')
        for trial,index,parent_index in [('other-trial',2,None),('trial',2,None),('other-trial',2,1),('trial',3,1)]:
            with self.subTest(trial=trial,index=index,parent_index=parent_index):
                with self.assertRaises(sqlite3.IntegrityError): self.attempt('bad-repair',trial=trial,index=index,parent='attempt',parent_index=parent_index)
        self.attempt('valid-repair',trial='trial',index=2,parent='attempt',parent_index=1)
        self.assertEqual(self.db.execute("SELECT trial_id,parent_id,parent_index FROM attempts WHERE id='valid-repair'").fetchone(),('trial','attempt',1))
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(self.db.execute("SELECT count(*) FROM attempts WHERE trial_id='other-trial'").fetchone()[0],0)

    def test_review_migration_rejects_old_null_parent_rows_without_rewriting_them(self):
        con=sqlite3.connect(self.root/'old-lineage.sqlite3',isolation_level=None)
        original=self.db
        try:
            con.execute('PRAGMA foreign_keys=ON'); migrate(con,migrations()[:4])
            self.db=con
            self.insert('sources',id='source',kind='test',location='legacy',sha256='a'*64,captured_at='now',metadata_json='{}')
            self.foundation(); self.attempt(); self.artifact(); self.assessment(outcome='FAIL')
            self.make_run('other-run'); self.trial('other-trial','other-run')
            self.attempt('bad-repair',trial='other-trial',index=2,parent='attempt',parent_index=None)
            before=con.execute('SELECT * FROM attempts').fetchall()
            with self.assertRaises(sqlite3.IntegrityError): migrate(con)
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertEqual(con.execute('SELECT * FROM attempts').fetchall(),before)
            self.assertEqual(con.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],4)
        finally:
            self.db=original; con.close()

    def test_overlap_rejection_keeps_retained_backup_bytes_and_tree_unchanged(self):
        self.artifact(); backup(self.db,self.root/'evidence',self.root/'backup')
        source=self.root/'backup'
        def snapshot():
            return {p.relative_to(source).as_posix():sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        before=snapshot(); entries=sorted(p.relative_to(source).as_posix() for p in source.rglob('*'))
        for destination in [source,source/'restored',source/'new-parent'/'restored',source/'..'/'backup'/'alias-child',self.root]:
            with self.subTest(destination=destination):
                with self.assertRaises(DatabaseError): restore(source,destination)
            self.assertEqual(snapshot(),before)
            self.assertEqual(sorted(p.relative_to(source).as_posix() for p in source.rglob('*')),entries)
            verify_backup(source)
        restore(source,self.root/'safe-restored')
        verify_backup(source); verify_backup(self.root/'safe-restored')
        self.assertEqual(snapshot(),before)

    def test_backup_overlap_does_not_write_original_artifact_root(self):
        self.artifact(); source=self.root/'evidence'
        before={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
        with self.assertRaises(DatabaseError): backup(self.db,source,source/'nested'/'backup')
        self.assertFalse((source/'nested').exists())
        self.assertEqual({p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()},before)


if __name__=='__main__':
    unittest.main()
