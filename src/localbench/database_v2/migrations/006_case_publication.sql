CREATE TABLE case_publication_intents (
 attempt_id TEXT PRIMARY KEY NOT NULL REFERENCES attempts(id),
 envelope_json TEXT NOT NULL CHECK(json_valid(envelope_json)),
 envelope_sha256 TEXT NOT NULL CHECK(length(envelope_sha256)=64 AND envelope_sha256 NOT GLOB '*[^0-9a-f]*'),
 CHECK(json_extract(envelope_json,'$.envelope.attempt_id')=attempt_id)
);
CREATE TABLE case_projection_inputs (
 result_id TEXT PRIMARY KEY NOT NULL REFERENCES committed_results(id),
 row_json TEXT NOT NULL CHECK(json_valid(row_json)),
 row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64 AND row_sha256 NOT GLOB '*[^0-9a-f]*')
);
CREATE TABLE case_commit_events (
 sequence INTEGER PRIMARY KEY CHECK(typeof(sequence)='integer' AND sequence>=1),
 id TEXT NOT NULL UNIQUE,
 result_id TEXT NOT NULL UNIQUE REFERENCES committed_results(id)
);
CREATE TABLE case_event_receipts (
 event_id TEXT NOT NULL REFERENCES case_commit_events(id),
 consumer TEXT NOT NULL CHECK(length(consumer)>0),
 PRIMARY KEY(event_id,consumer)
);
CREATE TABLE case_recovery_observations (
 id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES attempts(id),
 observation_json TEXT NOT NULL CHECK(json_valid(observation_json)),
 CHECK(json_extract(observation_json,'$.attempt_id')=attempt_id),
 CHECK(json_extract(observation_json,'$.execution_permission')=0)
);
CREATE TRIGGER publication_intent_binding BEFORE INSERT ON case_publication_intents BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM attempts a JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id
 WHERE a.id=NEW.attempt_id AND json_extract(NEW.envelope_json,'$.envelope.trial_id')=t.id
 AND json_extract(NEW.envelope_json,'$.envelope.run_id')=r.id
 AND json_extract(NEW.envelope_json,'$.envelope.case_id')=t.case_id
 AND json_extract(NEW.envelope_json,'$.envelope.config_id')=r.config_id
 AND json_extract(NEW.envelope_json,'$.envelope.source_id')=a.source_id)
 THEN RAISE(ABORT,'publication identity mismatch') END;
END;
CREATE TRIGGER case_event_sequence BEFORE INSERT ON case_commit_events BEGIN
 SELECT CASE WHEN NEW.sequence != (SELECT coalesce(max(sequence),0)+1 FROM case_commit_events)
 THEN RAISE(ABORT,'noncontiguous publication cursor') END;
END;
CREATE TRIGGER immutable_case_publication_intents_update BEFORE UPDATE ON case_publication_intents BEGIN SELECT RAISE(ABORT,'append-only publication intent'); END;
CREATE TRIGGER immutable_case_publication_intents_delete BEFORE DELETE ON case_publication_intents BEGIN SELECT RAISE(ABORT,'append-only publication intent'); END;
CREATE TRIGGER immutable_case_publication_intents_replace BEFORE INSERT ON case_publication_intents WHEN EXISTS(SELECT 1 FROM case_publication_intents WHERE attempt_id=NEW.attempt_id) BEGIN SELECT RAISE(ABORT,'immutable publication intent conflict'); END;
CREATE TRIGGER immutable_case_projection_inputs_update BEFORE UPDATE ON case_projection_inputs BEGIN SELECT RAISE(ABORT,'append-only projection input'); END;
CREATE TRIGGER immutable_case_projection_inputs_delete BEFORE DELETE ON case_projection_inputs BEGIN SELECT RAISE(ABORT,'append-only projection input'); END;
CREATE TRIGGER immutable_case_projection_inputs_replace BEFORE INSERT ON case_projection_inputs WHEN EXISTS(SELECT 1 FROM case_projection_inputs WHERE result_id=NEW.result_id) BEGIN SELECT RAISE(ABORT,'immutable projection input conflict'); END;
CREATE TRIGGER immutable_case_commit_events_update BEFORE UPDATE ON case_commit_events BEGIN SELECT RAISE(ABORT,'append-only commit event'); END;
CREATE TRIGGER immutable_case_commit_events_delete BEFORE DELETE ON case_commit_events BEGIN SELECT RAISE(ABORT,'append-only commit event'); END;
CREATE TRIGGER immutable_case_commit_events_replace BEFORE INSERT ON case_commit_events WHEN EXISTS(SELECT 1 FROM case_commit_events WHERE sequence=NEW.sequence OR id=NEW.id OR result_id=NEW.result_id) BEGIN SELECT RAISE(ABORT,'immutable commit event conflict'); END;
CREATE TRIGGER immutable_case_event_receipts_update BEFORE UPDATE ON case_event_receipts BEGIN SELECT RAISE(ABORT,'append-only event receipt'); END;
CREATE TRIGGER immutable_case_event_receipts_delete BEFORE DELETE ON case_event_receipts BEGIN SELECT RAISE(ABORT,'append-only event receipt'); END;
CREATE TRIGGER immutable_case_event_receipts_replace BEFORE INSERT ON case_event_receipts WHEN EXISTS(SELECT 1 FROM case_event_receipts WHERE event_id=NEW.event_id AND consumer=NEW.consumer) BEGIN SELECT RAISE(ABORT,'immutable event receipt conflict'); END;
CREATE TRIGGER immutable_case_recovery_observations_update BEFORE UPDATE ON case_recovery_observations BEGIN SELECT RAISE(ABORT,'append-only recovery observation'); END;
CREATE TRIGGER immutable_case_recovery_observations_delete BEFORE DELETE ON case_recovery_observations BEGIN SELECT RAISE(ABORT,'append-only recovery observation'); END;
CREATE TRIGGER immutable_case_recovery_observations_replace BEFORE INSERT ON case_recovery_observations WHEN EXISTS(SELECT 1 FROM case_recovery_observations WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'immutable recovery observation conflict'); END;
