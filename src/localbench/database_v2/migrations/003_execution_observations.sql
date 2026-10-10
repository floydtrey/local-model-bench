-- Keep immutable attempt identity; later native lifecycle observations supply execution state.
CREATE VIEW attempt_execution_state AS
SELECT a.id, coalesce(
 (SELECT CASE e.stage WHEN 'scheduled' THEN 'scheduled' WHEN 'started' THEN 'started'
    WHEN 'execution_completed' THEN 'completed' WHEN 'execution_interrupted' THEN 'interrupted' END
  FROM lifecycle_events e WHERE e.attempt_id=a.id AND e.stage IN ('scheduled','started','execution_completed','execution_interrupted')
  ORDER BY e.sequence DESC LIMIT 1), a.execution_status) AS execution_status
FROM attempts a;
CREATE TRIGGER lifecycle_sequence BEFORE INSERT ON lifecycle_events BEGIN
 SELECT CASE WHEN NEW.sequence != coalesce((SELECT max(sequence)+1 FROM lifecycle_events WHERE attempt_id=NEW.attempt_id),1)
 THEN RAISE(ABORT,'noncontiguous lifecycle sequence') END;
END;
CREATE TRIGGER execution_transition BEFORE INSERT ON lifecycle_events WHEN NEW.stage IN ('scheduled','started','execution_completed','execution_interrupted') BEGIN
 SELECT CASE WHEN NOT (
   (NEW.stage='scheduled' AND (SELECT execution_status FROM attempts WHERE id=NEW.attempt_id)='scheduled' AND
     NOT EXISTS(SELECT 1 FROM lifecycle_events WHERE attempt_id=NEW.attempt_id)) OR
   (NEW.stage='started' AND (SELECT execution_status FROM attempt_execution_state WHERE id=NEW.attempt_id)='scheduled') OR
   (NEW.stage IN ('execution_completed','execution_interrupted') AND (SELECT execution_status FROM attempt_execution_state WHERE id=NEW.attempt_id)='started'))
 THEN RAISE(ABORT,'invalid or terminal execution transition') END;
END;
DROP TRIGGER assessment_protocol;
CREATE TRIGGER assessment_protocol BEFORE INSERT ON assessments BEGIN
 SELECT CASE WHEN NEW.protocol_id != (SELECT r.protocol_id FROM attempts a JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id WHERE a.id=NEW.attempt_id)
 THEN RAISE(ABORT,'assessment protocol mismatch') END;
 SELECT CASE WHEN NEW.outcome IN ('PASS','FAIL') AND (SELECT execution_status FROM attempt_execution_state WHERE id=NEW.attempt_id)!='completed'
 THEN RAISE(ABORT,'uncompleted execution cannot earn PASS/FAIL') END;
 SELECT CASE WHEN (SELECT integrity FROM artifacts WHERE id=NEW.artifact_id)!='verified'
 THEN RAISE(ABORT,'assessment artifact unverified') END;
END;
DROP TRIGGER result_integrity;
CREATE TRIGGER result_integrity BEFORE INSERT ON committed_results BEGIN
 SELECT CASE WHEN NEW.assessment_id IS NOT NULL AND NEW.outcome IN ('PASS','FAIL','BLOCKED','UNSUPPORTED','INCOMPLETE','NOT_TESTED') AND
   NEW.outcome != (SELECT outcome FROM assessments WHERE id=NEW.assessment_id)
 THEN RAISE(ABORT,'result assessment contradiction') END;
 SELECT CASE WHEN (SELECT integrity FROM artifacts WHERE id=NEW.snapshot_artifact_id)!='verified'
 THEN RAISE(ABORT,'unverified result snapshot') END;
 SELECT CASE WHEN NEW.outcome='PASS' AND (
   (SELECT execution_status FROM attempt_execution_state WHERE id=NEW.attempt_id)!='completed' OR
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
CREATE TRIGGER hash_case_input BEFORE INSERT ON cases WHEN length(NEW.input_sha256)!=64 OR NEW.input_sha256 GLOB '*[^0-9a-f]*'
BEGIN SELECT RAISE(ABORT,'invalid case input hash'); END;
CREATE TRIGGER hash_assessor_implementation BEFORE INSERT ON assessors WHEN length(NEW.implementation_sha256)!=64 OR NEW.implementation_sha256 GLOB '*[^0-9a-f]*'
BEGIN SELECT RAISE(ABORT,'invalid assessor implementation hash'); END;
CREATE TRIGGER hash_mapping_implementation BEFORE INSERT ON import_mappings WHEN length(NEW.implementation_sha256)!=64 OR NEW.implementation_sha256 GLOB '*[^0-9a-f]*'
BEGIN SELECT RAISE(ABORT,'invalid mapping implementation hash'); END;
CREATE TRIGGER review_integrity BEFORE INSERT ON reviews WHEN NEW.status='completed' BEGIN
 SELECT CASE WHEN (SELECT integrity FROM artifacts WHERE id=NEW.artifact_id)!='verified'
 THEN RAISE(ABORT,'completed review requires verified evidence') END;
END;
CREATE TRIGGER separate_public_approval BEFORE INSERT ON publication_records WHEN NEW.public_artifact_id=NEW.approval_artifact_id
BEGIN SELECT RAISE(ABORT,'dataset and approval must be independent artifacts'); END;
