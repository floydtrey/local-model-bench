-- Existing native conversations can contain first-pass/repair phases or
-- transport attempts inside one canonical execution attempt. Preserve those
-- observations separately; they are neither new trials nor a second controller.
CREATE TABLE native_attempt_observations (
 id TEXT PRIMARY KEY NOT NULL,
 attempt_id TEXT NOT NULL REFERENCES attempts(id),
 ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal>=1),
 kind TEXT NOT NULL CHECK(kind IN ('first_pass','repair','transport_attempt')),
 parent_id TEXT, parent_ordinal INTEGER,
 source_id TEXT NOT NULL REFERENCES sources(id),
 artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 observations_json TEXT NOT NULL CHECK(json_valid(observations_json)),
 UNIQUE(attempt_id,ordinal), UNIQUE(id,attempt_id,ordinal),
 CHECK((kind!='repair' AND parent_id IS NULL AND parent_ordinal IS NULL) OR
       (kind='repair' AND ordinal>1 AND parent_id IS NOT NULL AND parent_ordinal=ordinal-1)),
 FOREIGN KEY(parent_id,attempt_id,parent_ordinal) REFERENCES native_attempt_observations(id,attempt_id,ordinal)
);
CREATE TRIGGER native_attempt_evidence BEFORE INSERT ON native_attempt_observations BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM attempts a WHERE a.id=NEW.attempt_id AND a.source_id=NEW.source_id)
 THEN RAISE(ABORT,'native attempt provenance mismatch') END;
 SELECT CASE WHEN NEW.ordinal != (SELECT coalesce(max(ordinal),0)+1 FROM native_attempt_observations WHERE attempt_id=NEW.attempt_id)
 THEN RAISE(ABORT,'noncontiguous native attempt observations') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id
 WHERE aa.attempt_id=NEW.attempt_id AND ar.id=NEW.artifact_id AND ar.integrity='verified' AND aa.purpose='native_attempt')
 THEN RAISE(ABORT,'native attempt observation lacks exact evidence') END;
 SELECT CASE WHEN NEW.kind='repair' AND NOT EXISTS(SELECT 1 FROM native_attempt_observations p
 WHERE p.id=NEW.parent_id AND p.attempt_id=NEW.attempt_id AND p.ordinal=NEW.parent_ordinal
 AND p.kind IN ('first_pass','repair') AND json_extract(p.observations_json,'$.deterministic_passed')=0)
 THEN RAISE(ABORT,'native repair lacks explicit failed native parent') END;
END;
CREATE TRIGGER immutable_native_attempt_observations_update BEFORE UPDATE ON native_attempt_observations BEGIN SELECT RAISE(ABORT,'append-only native attempt observation'); END;
CREATE TRIGGER immutable_native_attempt_observations_delete BEFORE DELETE ON native_attempt_observations BEGIN SELECT RAISE(ABORT,'append-only native attempt observation'); END;
CREATE TRIGGER immutable_native_attempt_observations_replace BEFORE INSERT ON native_attempt_observations WHEN EXISTS(SELECT 1 FROM native_attempt_observations WHERE id=NEW.id OR (attempt_id=NEW.attempt_id AND ordinal=NEW.ordinal)) BEGIN SELECT RAISE(ABORT,'immutable native attempt conflict'); END;
