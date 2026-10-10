-- Append-only publication of completed capture BEFORE separately invoked
-- assessment. Existing final result/intent/event history is never rewritten.
CREATE TABLE case_publication_revisions (
 id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES attempts(id),
 revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>=1),
 stage TEXT NOT NULL CHECK(stage IN ('capture','assessed')),
 result_id TEXT REFERENCES committed_results(id),
 snapshot_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 row_json TEXT NOT NULL CHECK(json_valid(row_json)),
 row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64 AND row_sha256 NOT GLOB '*[^0-9a-f]*'),
 artifacts_json TEXT NOT NULL CHECK(json_valid(artifacts_json) AND json_type(artifacts_json)='array'),
 UNIQUE(attempt_id,revision),
 CHECK((stage='capture' AND result_id IS NULL) OR (stage='assessed' AND result_id IS NOT NULL))
);
CREATE UNIQUE INDEX publication_capture_once ON case_publication_revisions(attempt_id) WHERE stage='capture';
CREATE UNIQUE INDEX publication_assessed_once ON case_publication_revisions(attempt_id) WHERE stage='assessed';
CREATE TABLE case_publication_events (
 sequence INTEGER PRIMARY KEY CHECK(typeof(sequence)='integer' AND sequence>=1),
 id TEXT NOT NULL UNIQUE REFERENCES case_publication_revisions(id)
);
CREATE TABLE case_publication_receipts (
 event_id TEXT NOT NULL REFERENCES case_publication_events(id),
 consumer TEXT NOT NULL CHECK(length(consumer)>0),
 PRIMARY KEY(event_id,consumer)
);
-- Retain existing final cursor/event IDs and consumer receipts on upgrade.
INSERT INTO case_publication_revisions
 SELECT e.id,r.attempt_id,1,'assessed',r.id,r.snapshot_artifact_id,p.row_json,p.row_sha256,'[]'
 FROM case_commit_events e JOIN committed_results r ON r.id=e.result_id
 JOIN case_projection_inputs p ON p.result_id=r.id;
INSERT INTO case_publication_events SELECT sequence,id FROM case_commit_events;
INSERT INTO case_publication_receipts SELECT event_id,consumer FROM case_event_receipts;
CREATE TRIGGER publication_revision_binding BEFORE INSERT ON case_publication_revisions BEGIN
 SELECT CASE WHEN NEW.revision!=(SELECT coalesce(max(revision),0)+1 FROM case_publication_revisions WHERE attempt_id=NEW.attempt_id)
 THEN RAISE(ABORT,'noncontiguous publication revision') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM attempt_artifacts aa JOIN artifacts a ON a.id=aa.artifact_id
 WHERE aa.attempt_id=NEW.attempt_id AND a.id=NEW.snapshot_artifact_id AND a.integrity='verified')
 THEN RAISE(ABORT,'publication snapshot attempt/integrity mismatch') END;
 SELECT CASE WHEN NEW.stage='assessed' AND NOT EXISTS(SELECT 1 FROM committed_results r
 WHERE r.id=NEW.result_id AND r.attempt_id=NEW.attempt_id AND r.snapshot_artifact_id=NEW.snapshot_artifact_id)
 THEN RAISE(ABORT,'publication result attempt/snapshot mismatch') END;
 SELECT CASE WHEN NEW.stage='capture' AND EXISTS(SELECT 1 FROM case_publication_revisions WHERE attempt_id=NEW.attempt_id AND stage='assessed')
 THEN RAISE(ABORT,'cannot append capture after assessed publication') END;
 SELECT CASE WHEN NEW.stage='capture' AND (json_type(NEW.row_json)!='object'
 OR coalesce(json_extract(NEW.row_json,'$.assessment_state'),'missing') NOT IN ('pending','unavailable')
 OR coalesce(json_type(NEW.row_json,'$.assessed_outcome'),'missing')!='null'
 OR coalesce(json_type(NEW.row_json,'$.score'),'missing')!='null'
 OR coalesce(json_type(NEW.row_json,'$.maximum_score'),'missing')!='null')
 THEN RAISE(ABORT,'capture publication cannot fabricate assessment/score') END;
END;
CREATE TRIGGER publication_event_sequence BEFORE INSERT ON case_publication_events BEGIN
 SELECT CASE WHEN NEW.sequence!=(SELECT coalesce(max(sequence),0)+1 FROM case_publication_events)
 THEN RAISE(ABORT,'noncontiguous publication event cursor') END;
END;
CREATE TRIGGER immutable_case_publication_revisions_update BEFORE UPDATE ON case_publication_revisions BEGIN SELECT RAISE(ABORT,'append-only publication revision'); END;
CREATE TRIGGER immutable_case_publication_revisions_delete BEFORE DELETE ON case_publication_revisions BEGIN SELECT RAISE(ABORT,'append-only publication revision'); END;
CREATE TRIGGER immutable_case_publication_revisions_replace BEFORE INSERT ON case_publication_revisions WHEN EXISTS(SELECT 1 FROM case_publication_revisions WHERE id=NEW.id OR (attempt_id=NEW.attempt_id AND (revision=NEW.revision OR stage=NEW.stage))) BEGIN SELECT RAISE(ABORT,'immutable publication revision conflict'); END;
CREATE TRIGGER immutable_case_publication_events_update BEFORE UPDATE ON case_publication_events BEGIN SELECT RAISE(ABORT,'append-only publication event'); END;
CREATE TRIGGER immutable_case_publication_events_delete BEFORE DELETE ON case_publication_events BEGIN SELECT RAISE(ABORT,'append-only publication event'); END;
CREATE TRIGGER immutable_case_publication_events_replace BEFORE INSERT ON case_publication_events WHEN EXISTS(SELECT 1 FROM case_publication_events WHERE sequence=NEW.sequence OR id=NEW.id) BEGIN SELECT RAISE(ABORT,'immutable publication event conflict'); END;
CREATE TRIGGER immutable_case_publication_receipts_update BEFORE UPDATE ON case_publication_receipts BEGIN SELECT RAISE(ABORT,'append-only publication receipt'); END;
CREATE TRIGGER immutable_case_publication_receipts_delete BEFORE DELETE ON case_publication_receipts BEGIN SELECT RAISE(ABORT,'append-only publication receipt'); END;
CREATE TRIGGER immutable_case_publication_receipts_replace BEFORE INSERT ON case_publication_receipts WHEN EXISTS(SELECT 1 FROM case_publication_receipts WHERE event_id=NEW.event_id AND consumer=NEW.consumer) BEGIN SELECT RAISE(ABORT,'immutable publication receipt conflict'); END;
