-- SQLite affinity is not strict typing: text can pass numeric CHECK comparisons.
-- Audit existing rows before installing insert guards; failure rolls back migration.
CREATE TEMP TABLE stage_a_type_guard (valid INTEGER CHECK(valid=1));
INSERT INTO stage_a_type_guard SELECT CASE WHEN (version IS NULL OR typeof(version)='integer') AND (sha256 IS NULL OR typeof(sha256)='text') THEN 1 ELSE 0 END FROM schema_migrations;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (position IS NULL OR typeof(position)='integer') THEN 1 ELSE 0 END FROM suite_cases;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (ordinal IS NULL OR typeof(ordinal)='integer') AND (planned_trials IS NULL OR typeof(planned_trials)='integer') THEN 1 ELSE 0 END FROM trials;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (attempt_index IS NULL OR typeof(attempt_index)='integer') AND (parent_index IS NULL OR typeof(parent_index)='integer') AND (exit_code IS NULL OR typeof(exit_code)='integer') THEN 1 ELSE 0 END FROM attempts;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (sequence IS NULL OR typeof(sequence)='integer') THEN 1 ELSE 0 END FROM lifecycle_events;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (byte_count IS NULL OR typeof(byte_count)='integer') AND (sha256 IS NULL OR typeof(sha256)='text') THEN 1 ELSE 0 END FROM artifacts;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (required IS NULL OR typeof(required)='integer') THEN 1 ELSE 0 END FROM attempt_artifacts;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (minimum_count IS NULL OR typeof(minimum_count)='integer') THEN 1 ELSE 0 END FROM protocol_evidence_requirements;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (acceptance_checks IS NULL OR typeof(acceptance_checks)='integer') AND (score IS NULL OR (typeof(score) IN ('integer','real') AND abs(score)<=1.7976931348623157e308)) AND (maximum_score IS NULL OR (typeof(maximum_score) IN ('integer','real') AND abs(maximum_score)<=1.7976931348623157e308)) THEN 1 ELSE 0 END FROM assessments;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (identity_verified IS NULL OR typeof(identity_verified)='integer') THEN 1 ELSE 0 END FROM reviews;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (numerator IS NULL OR typeof(numerator)='integer') AND (denominator IS NULL OR typeof(denominator)='integer') AND (percentage IS NULL OR (typeof(percentage) IN ('integer','real') AND abs(percentage)<=1.7976931348623157e308)) THEN 1 ELSE 0 END FROM metric_results;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (eligible IS NULL OR typeof(eligible)='integer') THEN 1 ELSE 0 END FROM comparison_decisions;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (singleton IS NULL OR typeof(singleton)='integer') THEN 1 ELSE 0 END FROM controller_identity;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (position IS NULL OR typeof(position)='integer') THEN 1 ELSE 0 END FROM queue_items;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (sha256 IS NULL OR typeof(sha256)='text') THEN 1 ELSE 0 END FROM sources;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (implementation_sha256 IS NULL OR typeof(implementation_sha256)='text') THEN 1 ELSE 0 END FROM import_mappings;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (identity_sha256 IS NULL OR typeof(identity_sha256)='text') THEN 1 ELSE 0 END FROM models;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (config_sha256 IS NULL OR typeof(config_sha256)='text') THEN 1 ELSE 0 END FROM runtime_configs;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (input_sha256 IS NULL OR typeof(input_sha256)='text') THEN 1 ELSE 0 END FROM cases;
INSERT INTO stage_a_type_guard SELECT CASE WHEN (implementation_sha256 IS NULL OR typeof(implementation_sha256)='text') THEN 1 ELSE 0 END FROM assessors;
DROP TABLE stage_a_type_guard;
CREATE TRIGGER typed_schema_migrations_insert BEFORE INSERT ON schema_migrations WHEN NOT ((NEW.version IS NULL OR typeof(NEW.version)='integer') AND (NEW.sha256 IS NULL OR typeof(NEW.sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in schema_migrations'); END;
CREATE TRIGGER typed_suite_cases_insert BEFORE INSERT ON suite_cases WHEN NOT ((NEW.position IS NULL OR typeof(NEW.position)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in suite_cases'); END;
CREATE TRIGGER typed_trials_insert BEFORE INSERT ON trials WHEN NOT ((NEW.ordinal IS NULL OR typeof(NEW.ordinal)='integer') AND (NEW.planned_trials IS NULL OR typeof(NEW.planned_trials)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in trials'); END;
CREATE TRIGGER typed_attempts_insert BEFORE INSERT ON attempts WHEN NOT ((NEW.attempt_index IS NULL OR typeof(NEW.attempt_index)='integer') AND (NEW.parent_index IS NULL OR typeof(NEW.parent_index)='integer') AND (NEW.exit_code IS NULL OR typeof(NEW.exit_code)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in attempts'); END;
CREATE TRIGGER typed_lifecycle_events_insert BEFORE INSERT ON lifecycle_events WHEN NOT ((NEW.sequence IS NULL OR typeof(NEW.sequence)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in lifecycle_events'); END;
CREATE TRIGGER typed_artifacts_insert BEFORE INSERT ON artifacts WHEN NOT ((NEW.byte_count IS NULL OR typeof(NEW.byte_count)='integer') AND (NEW.sha256 IS NULL OR typeof(NEW.sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in artifacts'); END;
CREATE TRIGGER typed_attempt_artifacts_insert BEFORE INSERT ON attempt_artifacts WHEN NOT ((NEW.required IS NULL OR typeof(NEW.required)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in attempt_artifacts'); END;
CREATE TRIGGER typed_protocol_evidence_requirements_insert BEFORE INSERT ON protocol_evidence_requirements WHEN NOT ((NEW.minimum_count IS NULL OR typeof(NEW.minimum_count)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in protocol_evidence_requirements'); END;
CREATE TRIGGER typed_assessments_insert BEFORE INSERT ON assessments WHEN NOT ((NEW.acceptance_checks IS NULL OR typeof(NEW.acceptance_checks)='integer') AND (NEW.score IS NULL OR (typeof(NEW.score) IN ('integer','real') AND abs(NEW.score)<=1.7976931348623157e308)) AND (NEW.maximum_score IS NULL OR (typeof(NEW.maximum_score) IN ('integer','real') AND abs(NEW.maximum_score)<=1.7976931348623157e308)))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in assessments'); END;
CREATE TRIGGER typed_reviews_insert BEFORE INSERT ON reviews WHEN NOT ((NEW.identity_verified IS NULL OR typeof(NEW.identity_verified)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in reviews'); END;
CREATE TRIGGER typed_metric_results_insert BEFORE INSERT ON metric_results WHEN NOT ((NEW.numerator IS NULL OR typeof(NEW.numerator)='integer') AND (NEW.denominator IS NULL OR typeof(NEW.denominator)='integer') AND (NEW.percentage IS NULL OR (typeof(NEW.percentage) IN ('integer','real') AND abs(NEW.percentage)<=1.7976931348623157e308)))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in metric_results'); END;
CREATE TRIGGER typed_comparison_decisions_insert BEFORE INSERT ON comparison_decisions WHEN NOT ((NEW.eligible IS NULL OR typeof(NEW.eligible)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in comparison_decisions'); END;
CREATE TRIGGER typed_controller_identity_insert BEFORE INSERT ON controller_identity WHEN NOT ((NEW.singleton IS NULL OR typeof(NEW.singleton)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in controller_identity'); END;
CREATE TRIGGER typed_queue_items_insert BEFORE INSERT ON queue_items WHEN NOT ((NEW.position IS NULL OR typeof(NEW.position)='integer'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in queue_items'); END;
CREATE TRIGGER typed_sources_insert BEFORE INSERT ON sources WHEN NOT ((NEW.sha256 IS NULL OR typeof(NEW.sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in sources'); END;
CREATE TRIGGER typed_import_mappings_insert BEFORE INSERT ON import_mappings WHEN NOT ((NEW.implementation_sha256 IS NULL OR typeof(NEW.implementation_sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in import_mappings'); END;
CREATE TRIGGER typed_models_insert BEFORE INSERT ON models WHEN NOT ((NEW.identity_sha256 IS NULL OR typeof(NEW.identity_sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in models'); END;
CREATE TRIGGER typed_runtime_configs_insert BEFORE INSERT ON runtime_configs WHEN NOT ((NEW.config_sha256 IS NULL OR typeof(NEW.config_sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in runtime_configs'); END;
CREATE TRIGGER typed_cases_insert BEFORE INSERT ON cases WHEN NOT ((NEW.input_sha256 IS NULL OR typeof(NEW.input_sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in cases'); END;
CREATE TRIGGER typed_assessors_insert BEFORE INSERT ON assessors WHEN NOT ((NEW.implementation_sha256 IS NULL OR typeof(NEW.implementation_sha256)='text'))
BEGIN SELECT RAISE(ABORT,'invalid numeric/hash storage type in assessors'); END;

