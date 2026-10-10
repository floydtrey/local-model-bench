CREATE TABLE case_result_assessments (
 result_id TEXT NOT NULL REFERENCES committed_results(id),
 assessment_id TEXT NOT NULL REFERENCES assessments(id),
 PRIMARY KEY(result_id,assessment_id)
);
CREATE TRIGGER case_assessment_binding BEFORE INSERT ON case_result_assessments BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM committed_results r JOIN assessments a ON a.attempt_id=r.attempt_id WHERE r.id=NEW.result_id AND a.id=NEW.assessment_id)
 THEN RAISE(ABORT,'case assessment attempt mismatch') END;
END;
CREATE TRIGGER immutable_case_result_assessments_update BEFORE UPDATE ON case_result_assessments BEGIN SELECT RAISE(ABORT,'append-only assessment membership'); END;
CREATE TRIGGER immutable_case_result_assessments_delete BEFORE DELETE ON case_result_assessments BEGIN SELECT RAISE(ABORT,'append-only assessment membership'); END;
CREATE TRIGGER immutable_case_result_assessments_replace BEFORE INSERT ON case_result_assessments WHEN EXISTS(SELECT 1 FROM case_result_assessments WHERE result_id=NEW.result_id AND assessment_id=NEW.assessment_id) BEGIN SELECT RAISE(ABORT,'immutable assessment membership conflict'); END;
