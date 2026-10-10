-- JSON number zero is not the native boolean false. Preserve exact types when
-- deciding whether an observed native repair has an explicitly failed parent.
CREATE TABLE _native_repair_audit (bad INTEGER CHECK(bad=0));
INSERT INTO _native_repair_audit SELECT count(*) FROM native_attempt_observations n WHERE n.kind='repair'
 AND NOT EXISTS(SELECT 1 FROM native_attempt_observations p WHERE p.id=n.parent_id
 AND p.attempt_id=n.attempt_id AND p.ordinal=n.parent_ordinal AND p.kind IN ('first_pass','repair')
 AND json_type(p.observations_json,'$.deterministic_passed')='false');
DROP TABLE _native_repair_audit;
DROP TRIGGER native_attempt_evidence;
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
 AND p.kind IN ('first_pass','repair') AND json_type(p.observations_json,'$.deterministic_passed')='false')
 THEN RAISE(ABORT,'native repair lacks explicit failed boolean parent') END;
END;
