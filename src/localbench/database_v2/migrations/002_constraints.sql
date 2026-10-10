CREATE INDEX trials_run_case ON trials(run_id,case_id);
CREATE INDEX assessments_attempt ON assessments(attempt_id,assessor_id);
CREATE INDEX events_attempt ON lifecycle_events(attempt_id,sequence);
CREATE INDEX reviews_assessment ON reviews(assessment_id,recorded_at);
CREATE INDEX artifact_digest ON artifacts(sha256);
CREATE INDEX discovery_installation ON discovery_observations(installation,tag,observed_at);
CREATE INDEX imports_source ON import_records(source_id,mapping_id);
CREATE INDEX metrics_run ON metric_results(run_id,metric_id,config_id);
CREATE INDEX telemetry_attempt ON telemetry(attempt_id,observed_at);
CREATE INDEX recovery_run ON recovery_records(run_id,attempt_id);
CREATE UNIQUE INDEX queue_one_active ON queue_items(snapshot_id) WHERE state='Running';
CREATE TRIGGER assessment_protocol BEFORE INSERT ON assessments BEGIN
 SELECT CASE WHEN NEW.protocol_id != (SELECT r.protocol_id FROM attempts a JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id WHERE a.id=NEW.attempt_id)
 THEN RAISE(ABORT,'assessment protocol mismatch') END;
 SELECT CASE WHEN NEW.outcome IN ('PASS','FAIL') AND (SELECT execution_status FROM attempts WHERE id=NEW.attempt_id)!='completed'
 THEN RAISE(ABORT,'uncompleted execution cannot earn PASS/FAIL') END;
 SELECT CASE WHEN (SELECT integrity FROM artifacts WHERE id=NEW.artifact_id)!='verified'
 THEN RAISE(ABORT,'assessment artifact unverified') END;
END;
CREATE TRIGGER repair_failed_parent BEFORE INSERT ON attempts WHEN NEW.attempt_index>1 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM assessments WHERE attempt_id=NEW.parent_id AND outcome='FAIL')
 THEN RAISE(ABORT,'repair requires explicit failed parent assessment') END;
END;
CREATE TRIGGER review_lineage BEFORE INSERT ON reviews WHEN NEW.supersedes_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM reviews WHERE id=NEW.supersedes_id AND assessment_id=NEW.assessment_id AND kind=NEW.kind)
 THEN RAISE(ABORT,'review lineage mismatch') END;
END;
CREATE TRIGGER result_integrity BEFORE INSERT ON committed_results BEGIN
 SELECT CASE WHEN NEW.assessment_id IS NOT NULL AND NEW.outcome IN ('PASS','FAIL','BLOCKED','UNSUPPORTED','INCOMPLETE','NOT_TESTED') AND
   NEW.outcome != (SELECT outcome FROM assessments WHERE id=NEW.assessment_id)
 THEN RAISE(ABORT,'result assessment contradiction') END;
 SELECT CASE WHEN (SELECT integrity FROM artifacts WHERE id=NEW.snapshot_artifact_id)!='verified'
 THEN RAISE(ABORT,'unverified result snapshot') END;
 SELECT CASE WHEN NEW.outcome='PASS' AND (
   (SELECT execution_status FROM attempts WHERE id=NEW.attempt_id)!='completed' OR
   NOT EXISTS(SELECT 1 FROM attempt_artifacts WHERE attempt_id=NEW.attempt_id AND required=1) OR
   NOT EXISTS(SELECT 1 FROM protocol_evidence_requirements pr JOIN runs r ON r.protocol_id=pr.protocol_id
       JOIN trials t ON t.run_id=r.id JOIN attempts a ON a.trial_id=t.id WHERE a.id=NEW.attempt_id) OR
   EXISTS(SELECT 1 FROM protocol_evidence_requirements pr JOIN runs r ON r.protocol_id=pr.protocol_id
       JOIN trials t ON t.run_id=r.id JOIN attempts a ON a.trial_id=t.id WHERE a.id=NEW.attempt_id AND
       (SELECT count(DISTINCT aa.artifact_id) FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id
        WHERE aa.attempt_id=NEW.attempt_id AND aa.purpose=pr.purpose AND aa.required=1 AND ar.integrity='verified')<pr.minimum_count) OR
   EXISTS(SELECT 1 FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE aa.attempt_id=NEW.attempt_id AND aa.required=1 AND ar.integrity!='verified'))
 THEN RAISE(ABORT,'success requires finalized evidence and completed execution') END;
END;
CREATE TRIGGER immutable_protocol_evidence_requirements_update BEFORE UPDATE ON protocol_evidence_requirements BEGIN SELECT RAISE(ABORT,'append-only protocol_evidence_requirements'); END;
CREATE TRIGGER immutable_protocol_evidence_requirements_delete BEFORE DELETE ON protocol_evidence_requirements BEGIN SELECT RAISE(ABORT,'append-only protocol_evidence_requirements'); END;
CREATE TRIGGER metric_config BEFORE INSERT ON metric_results BEGIN
 SELECT CASE WHEN NEW.config_id!=(SELECT config_id FROM runs WHERE id=NEW.run_id)
 THEN RAISE(ABORT,'metric configuration mismatch') END;
 SELECT CASE WHEN NEW.percentage IS NOT NULL AND (SELECT kind FROM metric_definitions WHERE id=NEW.metric_id)='role_suitability'
 THEN RAISE(ABORT,'role suitability has no percentage') END;
END;
CREATE TRIGGER metric_member_binding BEFORE INSERT ON metric_members BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM committed_results cr JOIN attempts a ON a.id=cr.attempt_id JOIN trials t ON t.id=a.trial_id
   JOIN metric_results mr ON mr.id=NEW.metric_result_id WHERE cr.id=NEW.result_id AND t.case_id=NEW.case_id AND t.run_id=mr.run_id)
 THEN RAISE(ABORT,'metric member binding mismatch') END;
END;
CREATE TRIGGER public_integrity BEFORE INSERT ON publication_records BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM artifacts WHERE id IN (NEW.public_artifact_id,NEW.approval_artifact_id) AND integrity!='verified')
 THEN RAISE(ABORT,'public publication requires verified dataset and approval') END;
END;
CREATE TRIGGER comparison_eligibility BEFORE INSERT ON comparison_decisions WHEN NEW.eligible=1 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM metric_results lm JOIN runs lr ON lr.id=lm.run_id
   JOIN metric_results rm ON rm.id=NEW.right_metric_id JOIN runs rr ON rr.id=rm.run_id
   WHERE lm.id=NEW.left_metric_id AND lm.metric_id=rm.metric_id AND lm.projection_version=rm.projection_version
     AND lr.suite_id=rr.suite_id AND lr.protocol_id=rr.protocol_id AND lm.population_json=rm.population_json)
 THEN RAISE(ABORT,'comparison protocol/version/population mismatch') END;
END;
CREATE TRIGGER queue_binding BEFORE INSERT ON queue_items BEGIN
 SELECT CASE WHEN NEW.run_id IS NOT NULL AND (NEW.config_id IS NULL OR NEW.config_id!=(SELECT config_id FROM runs WHERE id=NEW.run_id))
 THEN RAISE(ABORT,'queue run configuration mismatch') END;
 SELECT CASE WHEN NEW.state='Running' AND (SELECT state FROM queue_snapshots WHERE id=NEW.snapshot_id)!='Running'
 THEN RAISE(ABORT,'queue active state mismatch') END;
END;
CREATE TRIGGER recovery_binding BEFORE INSERT ON recovery_records WHEN NEW.attempt_id IS NOT NULL AND NEW.run_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM attempts a JOIN trials t ON t.id=a.trial_id WHERE a.id=NEW.attempt_id AND t.run_id=NEW.run_id)
 THEN RAISE(ABORT,'recovery run attempt mismatch') END;
END;
CREATE TRIGGER immutable_schema_migrations_update BEFORE UPDATE ON schema_migrations BEGIN SELECT RAISE(ABORT,'append-only schema_migrations'); END;
CREATE TRIGGER immutable_schema_migrations_delete BEFORE DELETE ON schema_migrations BEGIN SELECT RAISE(ABORT,'append-only schema_migrations'); END;
CREATE TRIGGER immutable_sources_update BEFORE UPDATE ON sources BEGIN SELECT RAISE(ABORT,'append-only sources'); END;
CREATE TRIGGER immutable_sources_delete BEFORE DELETE ON sources BEGIN SELECT RAISE(ABORT,'append-only sources'); END;
CREATE TRIGGER immutable_import_mappings_update BEFORE UPDATE ON import_mappings BEGIN SELECT RAISE(ABORT,'append-only import_mappings'); END;
CREATE TRIGGER immutable_import_mappings_delete BEFORE DELETE ON import_mappings BEGIN SELECT RAISE(ABORT,'append-only import_mappings'); END;
CREATE TRIGGER immutable_import_records_update BEFORE UPDATE ON import_records BEGIN SELECT RAISE(ABORT,'append-only import_records'); END;
CREATE TRIGGER immutable_import_records_delete BEFORE DELETE ON import_records BEGIN SELECT RAISE(ABORT,'append-only import_records'); END;
CREATE TRIGGER immutable_import_exceptions_update BEFORE UPDATE ON import_exceptions BEGIN SELECT RAISE(ABORT,'append-only import_exceptions'); END;
CREATE TRIGGER immutable_import_exceptions_delete BEFORE DELETE ON import_exceptions BEGIN SELECT RAISE(ABORT,'append-only import_exceptions'); END;
CREATE TRIGGER immutable_models_update BEFORE UPDATE ON models BEGIN SELECT RAISE(ABORT,'append-only models'); END;
CREATE TRIGGER immutable_models_delete BEFORE DELETE ON models BEGIN SELECT RAISE(ABORT,'append-only models'); END;
CREATE TRIGGER immutable_discovery_observations_update BEFORE UPDATE ON discovery_observations BEGIN SELECT RAISE(ABORT,'append-only discovery_observations'); END;
CREATE TRIGGER immutable_discovery_observations_delete BEFORE DELETE ON discovery_observations BEGIN SELECT RAISE(ABORT,'append-only discovery_observations'); END;
CREATE TRIGGER immutable_runtime_configs_update BEFORE UPDATE ON runtime_configs BEGIN SELECT RAISE(ABORT,'append-only runtime_configs'); END;
CREATE TRIGGER immutable_runtime_configs_delete BEFORE DELETE ON runtime_configs BEGIN SELECT RAISE(ABORT,'append-only runtime_configs'); END;
CREATE TRIGGER immutable_suites_update BEFORE UPDATE ON suites BEGIN SELECT RAISE(ABORT,'append-only suites'); END;
CREATE TRIGGER immutable_suites_delete BEFORE DELETE ON suites BEGIN SELECT RAISE(ABORT,'append-only suites'); END;
CREATE TRIGGER immutable_cases_update BEFORE UPDATE ON cases BEGIN SELECT RAISE(ABORT,'append-only cases'); END;
CREATE TRIGGER immutable_cases_delete BEFORE DELETE ON cases BEGIN SELECT RAISE(ABORT,'append-only cases'); END;
CREATE TRIGGER immutable_suite_cases_update BEFORE UPDATE ON suite_cases BEGIN SELECT RAISE(ABORT,'append-only suite_cases'); END;
CREATE TRIGGER immutable_suite_cases_delete BEFORE DELETE ON suite_cases BEGIN SELECT RAISE(ABORT,'append-only suite_cases'); END;
CREATE TRIGGER immutable_protocols_update BEFORE UPDATE ON protocols BEGIN SELECT RAISE(ABORT,'append-only protocols'); END;
CREATE TRIGGER immutable_protocols_delete BEFORE DELETE ON protocols BEGIN SELECT RAISE(ABORT,'append-only protocols'); END;
CREATE TRIGGER immutable_environments_update BEFORE UPDATE ON environments BEGIN SELECT RAISE(ABORT,'append-only environments'); END;
CREATE TRIGGER immutable_environments_delete BEFORE DELETE ON environments BEGIN SELECT RAISE(ABORT,'append-only environments'); END;
CREATE TRIGGER immutable_runs_update BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'append-only runs'); END;
CREATE TRIGGER immutable_runs_delete BEFORE DELETE ON runs BEGIN SELECT RAISE(ABORT,'append-only runs'); END;
CREATE TRIGGER immutable_trials_update BEFORE UPDATE ON trials BEGIN SELECT RAISE(ABORT,'append-only trials'); END;
CREATE TRIGGER immutable_trials_delete BEFORE DELETE ON trials BEGIN SELECT RAISE(ABORT,'append-only trials'); END;
CREATE TRIGGER immutable_attempts_update BEFORE UPDATE ON attempts BEGIN SELECT RAISE(ABORT,'append-only attempts'); END;
CREATE TRIGGER immutable_attempts_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT,'append-only attempts'); END;
CREATE TRIGGER immutable_lifecycle_events_update BEFORE UPDATE ON lifecycle_events BEGIN SELECT RAISE(ABORT,'append-only lifecycle_events'); END;
CREATE TRIGGER immutable_lifecycle_events_delete BEFORE DELETE ON lifecycle_events BEGIN SELECT RAISE(ABORT,'append-only lifecycle_events'); END;
CREATE TRIGGER immutable_artifacts_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT,'append-only artifacts'); END;
CREATE TRIGGER immutable_artifacts_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT,'append-only artifacts'); END;
CREATE TRIGGER immutable_attempt_artifacts_update BEFORE UPDATE ON attempt_artifacts BEGIN SELECT RAISE(ABORT,'append-only attempt_artifacts'); END;
CREATE TRIGGER immutable_attempt_artifacts_delete BEFORE DELETE ON attempt_artifacts BEGIN SELECT RAISE(ABORT,'append-only attempt_artifacts'); END;
CREATE TRIGGER immutable_assessors_update BEFORE UPDATE ON assessors BEGIN SELECT RAISE(ABORT,'append-only assessors'); END;
CREATE TRIGGER immutable_assessors_delete BEFORE DELETE ON assessors BEGIN SELECT RAISE(ABORT,'append-only assessors'); END;
CREATE TRIGGER immutable_assessments_update BEFORE UPDATE ON assessments BEGIN SELECT RAISE(ABORT,'append-only assessments'); END;
CREATE TRIGGER immutable_assessments_delete BEFORE DELETE ON assessments BEGIN SELECT RAISE(ABORT,'append-only assessments'); END;
CREATE TRIGGER immutable_reviews_update BEFORE UPDATE ON reviews BEGIN SELECT RAISE(ABORT,'append-only reviews'); END;
CREATE TRIGGER immutable_reviews_delete BEFORE DELETE ON reviews BEGIN SELECT RAISE(ABORT,'append-only reviews'); END;
CREATE TRIGGER immutable_committed_results_update BEFORE UPDATE ON committed_results BEGIN SELECT RAISE(ABORT,'append-only committed_results'); END;
CREATE TRIGGER immutable_committed_results_delete BEFORE DELETE ON committed_results BEGIN SELECT RAISE(ABORT,'append-only committed_results'); END;
CREATE TRIGGER immutable_metric_definitions_update BEFORE UPDATE ON metric_definitions BEGIN SELECT RAISE(ABORT,'append-only metric_definitions'); END;
CREATE TRIGGER immutable_metric_definitions_delete BEFORE DELETE ON metric_definitions BEGIN SELECT RAISE(ABORT,'append-only metric_definitions'); END;
CREATE TRIGGER immutable_role_criteria_update BEFORE UPDATE ON role_criteria BEGIN SELECT RAISE(ABORT,'append-only role_criteria'); END;
CREATE TRIGGER immutable_role_criteria_delete BEFORE DELETE ON role_criteria BEGIN SELECT RAISE(ABORT,'append-only role_criteria'); END;
CREATE TRIGGER immutable_metric_results_update BEFORE UPDATE ON metric_results BEGIN SELECT RAISE(ABORT,'append-only metric_results'); END;
CREATE TRIGGER immutable_metric_results_delete BEFORE DELETE ON metric_results BEGIN SELECT RAISE(ABORT,'append-only metric_results'); END;
CREATE TRIGGER immutable_metric_members_update BEFORE UPDATE ON metric_members BEGIN SELECT RAISE(ABORT,'append-only metric_members'); END;
CREATE TRIGGER immutable_metric_members_delete BEFORE DELETE ON metric_members BEGIN SELECT RAISE(ABORT,'append-only metric_members'); END;
CREATE TRIGGER immutable_comparison_decisions_update BEFORE UPDATE ON comparison_decisions BEGIN SELECT RAISE(ABORT,'append-only comparison_decisions'); END;
CREATE TRIGGER immutable_comparison_decisions_delete BEFORE DELETE ON comparison_decisions BEGIN SELECT RAISE(ABORT,'append-only comparison_decisions'); END;
CREATE TRIGGER immutable_telemetry_update BEFORE UPDATE ON telemetry BEGIN SELECT RAISE(ABORT,'append-only telemetry'); END;
CREATE TRIGGER immutable_telemetry_delete BEFORE DELETE ON telemetry BEGIN SELECT RAISE(ABORT,'append-only telemetry'); END;
CREATE TRIGGER immutable_publication_records_update BEFORE UPDATE ON publication_records BEGIN SELECT RAISE(ABORT,'append-only publication_records'); END;
CREATE TRIGGER immutable_publication_records_delete BEFORE DELETE ON publication_records BEGIN SELECT RAISE(ABORT,'append-only publication_records'); END;
CREATE TRIGGER immutable_controller_identity_update BEFORE UPDATE ON controller_identity BEGIN SELECT RAISE(ABORT,'append-only controller_identity'); END;
CREATE TRIGGER immutable_controller_identity_delete BEFORE DELETE ON controller_identity BEGIN SELECT RAISE(ABORT,'append-only controller_identity'); END;
CREATE TRIGGER immutable_queue_snapshots_update BEFORE UPDATE ON queue_snapshots BEGIN SELECT RAISE(ABORT,'append-only queue_snapshots'); END;
CREATE TRIGGER immutable_queue_snapshots_delete BEFORE DELETE ON queue_snapshots BEGIN SELECT RAISE(ABORT,'append-only queue_snapshots'); END;
CREATE TRIGGER immutable_queue_items_update BEFORE UPDATE ON queue_items BEGIN SELECT RAISE(ABORT,'append-only queue_items'); END;
CREATE TRIGGER immutable_queue_items_delete BEFORE DELETE ON queue_items BEGIN SELECT RAISE(ABORT,'append-only queue_items'); END;
CREATE TRIGGER immutable_recovery_records_update BEFORE UPDATE ON recovery_records BEGIN SELECT RAISE(ABORT,'append-only recovery_records'); END;
CREATE TRIGGER immutable_recovery_records_delete BEFORE DELETE ON recovery_records BEGIN SELECT RAISE(ABORT,'append-only recovery_records'); END;
