-- Additive correction for independent review P1 replacement/P1 lineage and
-- cross-version finite numeric checks. Original migration checksums stay fixed.
CREATE TEMP TABLE stage_a_integrity_guard (valid INTEGER CHECK(valid=1));
INSERT INTO stage_a_integrity_guard SELECT CASE WHEN
 (attempt_index=1 AND parent_id IS NULL AND parent_index IS NULL) OR
 (attempt_index>1 AND parent_index IS NOT NULL AND parent_index=attempt_index-1 AND
  EXISTS(SELECT 1 FROM attempts p WHERE p.id=a.parent_id AND p.trial_id=a.trial_id AND p.attempt_index=a.attempt_index-1))
 THEN 1 ELSE 0 END FROM attempts a;
INSERT INTO stage_a_integrity_guard SELECT CASE WHEN
 (score IS NULL OR (typeof(score) IN ('integer','real') AND coalesce(score-score=0,0)=1)) AND
 (maximum_score IS NULL OR (typeof(maximum_score) IN ('integer','real') AND coalesce(maximum_score-maximum_score=0,0)=1))
 THEN 1 ELSE 0 END FROM assessments;
INSERT INTO stage_a_integrity_guard SELECT CASE WHEN percentage IS NULL OR
 (typeof(percentage) IN ('integer','real') AND coalesce(percentage-percentage=0,0)=1)
 THEN 1 ELSE 0 END FROM metric_results;
INSERT INTO stage_a_integrity_guard SELECT CASE WHEN
 EXISTS(SELECT 1 FROM artifacts WHERE id=cr.snapshot_artifact_id AND integrity='verified') AND
 EXISTS(SELECT 1 FROM assessments WHERE id=cr.assessment_id AND attempt_id=cr.attempt_id AND outcome='PASS') AND
 EXISTS(SELECT 1 FROM attempt_execution_state WHERE id=cr.attempt_id AND execution_status='completed') AND
 EXISTS(SELECT 1 FROM attempt_artifacts WHERE attempt_id=cr.attempt_id AND required=1) AND
 NOT EXISTS(SELECT 1 FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id
            WHERE aa.attempt_id=cr.attempt_id AND aa.required=1 AND ar.integrity!='verified')
 THEN 1 ELSE 0 END FROM committed_results cr WHERE cr.outcome='PASS';
DROP TABLE stage_a_integrity_guard;
CREATE TRIGGER exact_repair_parent BEFORE INSERT ON attempts WHEN NEW.attempt_index>1 BEGIN
 SELECT CASE WHEN NEW.parent_index IS NULL OR NEW.parent_id IS NULL OR NEW.parent_index!=NEW.attempt_index-1 OR
 NOT EXISTS(SELECT 1 FROM attempts p WHERE p.id=NEW.parent_id AND p.trial_id=NEW.trial_id AND p.attempt_index=NEW.attempt_index-1)
 THEN RAISE(ABORT,'repair must bind nonnull same-trial immediate predecessor') END;
END;
CREATE TRIGGER finite_assessment_score BEFORE INSERT ON assessments BEGIN
 SELECT CASE WHEN (NEW.score IS NOT NULL AND coalesce(NEW.score-NEW.score=0,0)!=1) OR
 (NEW.maximum_score IS NOT NULL AND coalesce(NEW.maximum_score-NEW.maximum_score=0,0)!=1)
 THEN RAISE(ABORT,'nonfinite assessment score') END;
END;
CREATE TRIGGER finite_metric_percentage BEFORE INSERT ON metric_results WHEN NEW.percentage IS NOT NULL AND coalesce(NEW.percentage-NEW.percentage=0,0)!=1
BEGIN SELECT RAISE(ABORT,'nonfinite metric percentage'); END;
CREATE TRIGGER no_replacement_schema_migrations BEFORE INSERT ON schema_migrations WHEN
 EXISTS(SELECT 1 FROM schema_migrations WHERE version=NEW.version)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in schema_migrations'); END;
CREATE TRIGGER no_replacement_sources BEFORE INSERT ON sources WHEN
 EXISTS(SELECT 1 FROM sources WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM sources WHERE kind=NEW.kind AND location=NEW.location AND sha256=NEW.sha256)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in sources'); END;
CREATE TRIGGER no_replacement_import_mappings BEFORE INSERT ON import_mappings WHEN
 EXISTS(SELECT 1 FROM import_mappings WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in import_mappings'); END;
CREATE TRIGGER no_replacement_import_records BEFORE INSERT ON import_records WHEN
 EXISTS(SELECT 1 FROM import_records WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM import_records WHERE source_id=NEW.source_id AND mapping_id=NEW.mapping_id AND source_pointer=NEW.source_pointer)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in import_records'); END;
CREATE TRIGGER no_replacement_import_exceptions BEFORE INSERT ON import_exceptions WHEN
 EXISTS(SELECT 1 FROM import_exceptions WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in import_exceptions'); END;
CREATE TRIGGER no_replacement_models BEFORE INSERT ON models WHEN
 EXISTS(SELECT 1 FROM models WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM models WHERE identity_sha256=NEW.identity_sha256)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in models'); END;
CREATE TRIGGER no_replacement_discovery_observations BEFORE INSERT ON discovery_observations WHEN
 EXISTS(SELECT 1 FROM discovery_observations WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in discovery_observations'); END;
CREATE TRIGGER no_replacement_runtime_configs BEFORE INSERT ON runtime_configs WHEN
 EXISTS(SELECT 1 FROM runtime_configs WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM runtime_configs WHERE model_id=NEW.model_id AND config_sha256=NEW.config_sha256)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in runtime_configs'); END;
CREATE TRIGGER no_replacement_suites BEFORE INSERT ON suites WHEN
 EXISTS(SELECT 1 FROM suites WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM suites WHERE name=NEW.name AND version=NEW.version AND source_id=NEW.source_id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in suites'); END;
CREATE TRIGGER no_replacement_cases BEFORE INSERT ON cases WHEN
 EXISTS(SELECT 1 FROM cases WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM cases WHERE logical_id=NEW.logical_id AND version=NEW.version AND source_id=NEW.source_id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in cases'); END;
CREATE TRIGGER no_replacement_suite_cases BEFORE INSERT ON suite_cases WHEN
 EXISTS(SELECT 1 FROM suite_cases WHERE suite_id=NEW.suite_id AND case_id=NEW.case_id) OR
 EXISTS(SELECT 1 FROM suite_cases WHERE suite_id=NEW.suite_id AND position=NEW.position)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in suite_cases'); END;
CREATE TRIGGER no_replacement_protocols BEFORE INSERT ON protocols WHEN
 EXISTS(SELECT 1 FROM protocols WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM protocols WHERE name=NEW.name AND version=NEW.version AND source_id=NEW.source_id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in protocols'); END;
CREATE TRIGGER no_replacement_environments BEFORE INSERT ON environments WHEN
 EXISTS(SELECT 1 FROM environments WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in environments'); END;
CREATE TRIGGER no_replacement_runs BEFORE INSERT ON runs WHEN
 EXISTS(SELECT 1 FROM runs WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in runs'); END;
CREATE TRIGGER no_replacement_trials BEFORE INSERT ON trials WHEN
 EXISTS(SELECT 1 FROM trials WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM trials WHERE run_id=NEW.run_id AND case_id=NEW.case_id AND ordinal=NEW.ordinal)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in trials'); END;
CREATE TRIGGER no_replacement_attempts BEFORE INSERT ON attempts WHEN
 EXISTS(SELECT 1 FROM attempts WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM attempts WHERE trial_id=NEW.trial_id AND attempt_index=NEW.attempt_index)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in attempts'); END;
CREATE TRIGGER no_replacement_lifecycle_events BEFORE INSERT ON lifecycle_events WHEN
 EXISTS(SELECT 1 FROM lifecycle_events WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM lifecycle_events WHERE attempt_id=NEW.attempt_id AND sequence=NEW.sequence)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in lifecycle_events'); END;
CREATE TRIGGER no_replacement_artifacts BEFORE INSERT ON artifacts WHEN
 EXISTS(SELECT 1 FROM artifacts WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM artifacts WHERE relative_path=NEW.relative_path)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in artifacts'); END;
CREATE TRIGGER no_replacement_attempt_artifacts BEFORE INSERT ON attempt_artifacts WHEN
 EXISTS(SELECT 1 FROM attempt_artifacts WHERE attempt_id=NEW.attempt_id AND artifact_id=NEW.artifact_id AND purpose=NEW.purpose)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in attempt_artifacts'); END;
CREATE TRIGGER no_replacement_protocol_evidence_requirements BEFORE INSERT ON protocol_evidence_requirements WHEN
 EXISTS(SELECT 1 FROM protocol_evidence_requirements WHERE protocol_id=NEW.protocol_id AND purpose=NEW.purpose)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in protocol_evidence_requirements'); END;
CREATE TRIGGER no_replacement_assessors BEFORE INSERT ON assessors WHEN
 EXISTS(SELECT 1 FROM assessors WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM assessors WHERE name=NEW.name AND version=NEW.version AND implementation_sha256=NEW.implementation_sha256)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in assessors'); END;
CREATE TRIGGER no_replacement_assessments BEFORE INSERT ON assessments WHEN
 EXISTS(SELECT 1 FROM assessments WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in assessments'); END;
CREATE TRIGGER no_replacement_reviews BEFORE INSERT ON reviews WHEN
 EXISTS(SELECT 1 FROM reviews WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in reviews'); END;
CREATE TRIGGER no_replacement_committed_results BEFORE INSERT ON committed_results WHEN
 EXISTS(SELECT 1 FROM committed_results WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM committed_results WHERE attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in committed_results'); END;
CREATE TRIGGER no_replacement_metric_definitions BEFORE INSERT ON metric_definitions WHEN
 EXISTS(SELECT 1 FROM metric_definitions WHERE id=NEW.id) OR
 EXISTS(SELECT 1 FROM metric_definitions WHERE name=NEW.name AND version=NEW.version AND source_id=NEW.source_id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in metric_definitions'); END;
CREATE TRIGGER no_replacement_role_criteria BEFORE INSERT ON role_criteria WHEN
 EXISTS(SELECT 1 FROM role_criteria WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in role_criteria'); END;
CREATE TRIGGER no_replacement_metric_results BEFORE INSERT ON metric_results WHEN
 EXISTS(SELECT 1 FROM metric_results WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in metric_results'); END;
CREATE TRIGGER no_replacement_metric_members BEFORE INSERT ON metric_members WHEN
 EXISTS(SELECT 1 FROM metric_members WHERE metric_result_id=NEW.metric_result_id AND result_id=NEW.result_id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in metric_members'); END;
CREATE TRIGGER no_replacement_comparison_decisions BEFORE INSERT ON comparison_decisions WHEN
 EXISTS(SELECT 1 FROM comparison_decisions WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in comparison_decisions'); END;
CREATE TRIGGER no_replacement_telemetry BEFORE INSERT ON telemetry WHEN
 EXISTS(SELECT 1 FROM telemetry WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in telemetry'); END;
CREATE TRIGGER no_replacement_publication_records BEFORE INSERT ON publication_records WHEN
 EXISTS(SELECT 1 FROM publication_records WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in publication_records'); END;
CREATE TRIGGER no_replacement_controller_identity BEFORE INSERT ON controller_identity WHEN
 EXISTS(SELECT 1 FROM controller_identity WHERE singleton=NEW.singleton)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in controller_identity'); END;
CREATE TRIGGER no_replacement_queue_snapshots BEFORE INSERT ON queue_snapshots WHEN
 EXISTS(SELECT 1 FROM queue_snapshots WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in queue_snapshots'); END;
CREATE TRIGGER no_replacement_queue_items BEFORE INSERT ON queue_items WHEN
 EXISTS(SELECT 1 FROM queue_items WHERE snapshot_id=NEW.snapshot_id AND item_id=NEW.item_id) OR
 EXISTS(SELECT 1 FROM queue_items WHERE snapshot_id=NEW.snapshot_id AND position=NEW.position) OR
 (NEW.state='Running' AND EXISTS(SELECT 1 FROM queue_items WHERE snapshot_id=NEW.snapshot_id AND state='Running'))
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in queue_items'); END;
CREATE TRIGGER no_replacement_recovery_records BEFORE INSERT ON recovery_records WHEN
 EXISTS(SELECT 1 FROM recovery_records WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable identity/unique conflict in recovery_records'); END;

