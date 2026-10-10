CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE sources (
    id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, format_version TEXT,
    location TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    captured_at TEXT NOT NULL, producer_version TEXT, metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    UNIQUE(kind, location, sha256)
);
CREATE TABLE import_mappings (
    id TEXT PRIMARY KEY NOT NULL, version TEXT NOT NULL, implementation_sha256 TEXT NOT NULL,
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)), source_id TEXT NOT NULL REFERENCES sources(id),
    UNIQUE(id, version)
);
CREATE TABLE import_records (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    mapping_id TEXT NOT NULL REFERENCES import_mappings(id), source_pointer TEXT NOT NULL,
    target_kind TEXT, target_id TEXT, status TEXT NOT NULL CHECK(status IN ('planned','imported','excluded','unavailable')),
    unknown_fields_json TEXT NOT NULL CHECK(json_valid(unknown_fields_json)),
    UNIQUE(source_id, mapping_id, source_pointer)
);
CREATE TABLE import_exceptions (
    id TEXT PRIMARY KEY NOT NULL, import_id TEXT NOT NULL REFERENCES import_records(id),
    reason TEXT NOT NULL, detail_json TEXT NOT NULL CHECK(json_valid(detail_json))
);
CREATE TABLE models (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    version TEXT NOT NULL, identity_json TEXT NOT NULL CHECK(json_valid(identity_json)),
    identity_sha256 TEXT NOT NULL UNIQUE CHECK(length(identity_sha256)=64 AND identity_sha256 NOT GLOB '*[^0-9a-f]*')
);
CREATE TABLE discovery_observations (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    model_id TEXT REFERENCES models(id), observed_at TEXT NOT NULL, installation TEXT NOT NULL,
    tag TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('present','absent','unavailable')),
    observation_json TEXT NOT NULL CHECK(json_valid(observation_json))
);
CREATE TABLE runtime_configs (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    model_id TEXT NOT NULL REFERENCES models(id), version TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'),
    UNIQUE(model_id, config_sha256), UNIQUE(id, model_id)
);
CREATE TABLE suites (
    id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id), definition_json TEXT NOT NULL CHECK(json_valid(definition_json)),
    UNIQUE(name, version, source_id)
);
CREATE TABLE cases (
    id TEXT PRIMARY KEY NOT NULL, logical_id TEXT NOT NULL, version TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id), input_sha256 TEXT NOT NULL,
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)), UNIQUE(logical_id, version, source_id)
);
CREATE TABLE suite_cases (
    suite_id TEXT NOT NULL REFERENCES suites(id), case_id TEXT NOT NULL REFERENCES cases(id),
    position INTEGER NOT NULL CHECK(position>=1), PRIMARY KEY(suite_id,case_id), UNIQUE(suite_id,position)
);
CREATE TABLE protocols (
    id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id), track TEXT NOT NULL,
    role TEXT, worker_mode TEXT CHECK(worker_mode IN ('ISOLATED','CUMULATIVE') OR worker_mode IS NULL),
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)), UNIQUE(name,version,source_id)
);
CREATE TABLE environments (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id), version TEXT NOT NULL,
    facts_json TEXT NOT NULL CHECK(json_valid(facts_json)), captured_at TEXT NOT NULL
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    suite_id TEXT NOT NULL REFERENCES suites(id), protocol_id TEXT NOT NULL REFERENCES protocols(id),
    config_id TEXT NOT NULL REFERENCES runtime_configs(id), environment_id TEXT NOT NULL REFERENCES environments(id),
    created_at TEXT NOT NULL, origin TEXT NOT NULL CHECK(origin IN ('controlled','historical_observation','synthetic_test')),
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)), UNIQUE(id,suite_id)
);
CREATE TABLE trials (
    id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL, suite_id TEXT NOT NULL, case_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=1), planned_trials INTEGER NOT NULL CHECK(planned_trials>=ordinal),
    repeat_group TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    FOREIGN KEY(run_id,suite_id) REFERENCES runs(id,suite_id),
    FOREIGN KEY(suite_id,case_id) REFERENCES suite_cases(suite_id,case_id),
    UNIQUE(run_id,case_id,ordinal), UNIQUE(id,run_id)
);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY NOT NULL, trial_id TEXT NOT NULL REFERENCES trials(id),
    attempt_index INTEGER NOT NULL CHECK(attempt_index>=1), parent_id TEXT, parent_index INTEGER,
    source_id TEXT NOT NULL REFERENCES sources(id),
    execution_status TEXT NOT NULL CHECK(execution_status IN ('scheduled','started','completed','interrupted','blocked','unsupported','not_tested')),
    exit_code INTEGER, started_at TEXT, finished_at TEXT, observations_json TEXT NOT NULL CHECK(json_valid(observations_json)),
    CHECK((attempt_index=1 AND parent_id IS NULL AND parent_index IS NULL) OR
          (attempt_index>1 AND parent_id IS NOT NULL AND parent_index=attempt_index-1)),
    FOREIGN KEY(parent_id,trial_id,parent_index) REFERENCES attempts(id,trial_id,attempt_index),
    UNIQUE(trial_id,attempt_index), UNIQUE(id,trial_id,attempt_index)
);
CREATE TABLE lifecycle_events (
    id TEXT PRIMARY KEY NOT NULL, attempt_id TEXT NOT NULL REFERENCES attempts(id),
    sequence INTEGER NOT NULL CHECK(sequence>=1), occurred_at TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('scheduled','started','execution_completed','execution_interrupted','evidence_finalized','assessment_completed','assessment_unavailable','result_committed','review_pending','review_completed')),
    source_id TEXT NOT NULL REFERENCES sources(id), detail_json TEXT NOT NULL CHECK(json_valid(detail_json)),
    UNIQUE(attempt_id,sequence)
);
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    relative_path TEXT NOT NULL UNIQUE CHECK(length(relative_path)>0 AND substr(relative_path,1,1)!='/' AND
       instr(relative_path,':')=0 AND instr(relative_path,char(92))=0 AND
       instr('/'||relative_path||'/','/../')=0 AND instr('/'||relative_path||'/','/./')=0 AND instr(relative_path,'//')=0),
    sha256 TEXT CHECK(sha256 IS NULL OR (length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*')),
    byte_count INTEGER CHECK(byte_count>=0), media_type TEXT NOT NULL,
    integrity TEXT NOT NULL CHECK(integrity IN ('verified','missing','unverifiable','corrupt')),
    verified_at TEXT, CHECK(integrity!='verified' OR (sha256 IS NOT NULL AND byte_count IS NOT NULL AND verified_at IS NOT NULL))
);
CREATE TABLE attempt_artifacts (
    attempt_id TEXT NOT NULL REFERENCES attempts(id), artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    purpose TEXT NOT NULL, required INTEGER NOT NULL CHECK(required IN (0,1)), PRIMARY KEY(attempt_id,artifact_id,purpose)
);
CREATE TABLE protocol_evidence_requirements (
    protocol_id TEXT NOT NULL REFERENCES protocols(id), purpose TEXT NOT NULL,
    minimum_count INTEGER NOT NULL CHECK(minimum_count>=1), PRIMARY KEY(protocol_id,purpose)
);
CREATE TABLE assessors (
    id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
    implementation_sha256 TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)), UNIQUE(name,version,implementation_sha256)
);
CREATE TABLE assessments (
    id TEXT PRIMARY KEY NOT NULL, attempt_id TEXT NOT NULL REFERENCES attempts(id),
    assessor_id TEXT NOT NULL REFERENCES assessors(id), protocol_id TEXT NOT NULL REFERENCES protocols(id),
    source_id TEXT NOT NULL REFERENCES sources(id), artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    outcome TEXT NOT NULL CHECK(outcome IN ('PASS','FAIL','BLOCKED','NOT_ASSESSED','UNSUPPORTED','INCOMPLETE','NOT_TESTED')),
    score REAL, maximum_score REAL, acceptance_checks INTEGER CHECK(acceptance_checks>=0), check_unit TEXT,
    implementation_truth TEXT, candidate_decision TEXT,
    detail_json TEXT NOT NULL CHECK(json_valid(detail_json)),
    CHECK(score IS NULL OR (outcome IN ('PASS','FAIL') AND maximum_score IS NOT NULL AND score>=0 AND score<=maximum_score)),
    CHECK(maximum_score IS NULL OR maximum_score>=0),
    CHECK(acceptance_checks IS NULL OR check_unit IS NOT NULL), UNIQUE(id,attempt_id)
);
CREATE TABLE reviews (
    id TEXT PRIMARY KEY NOT NULL, assessment_id TEXT NOT NULL REFERENCES assessments(id),
    source_id TEXT NOT NULL REFERENCES sources(id), artifact_id TEXT REFERENCES artifacts(id),
    supersedes_id TEXT REFERENCES reviews(id), kind TEXT NOT NULL CHECK(kind IN ('technical','human','reference')),
    status TEXT NOT NULL CHECK(status IN ('pending','completed','unavailable')), reviewer TEXT,
    identity_verified INTEGER NOT NULL CHECK(identity_verified IN (0,1)), recorded_at TEXT NOT NULL,
    binding_json TEXT NOT NULL CHECK(json_valid(binding_json)), CHECK(status!='completed' OR artifact_id IS NOT NULL)
);
CREATE TABLE committed_results (
    id TEXT PRIMARY KEY NOT NULL, attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
    assessment_id TEXT, outcome TEXT NOT NULL CHECK(outcome IN ('PASS','FAIL','BLOCKED','UNKNOWN','UNSUPPORTED','INCOMPLETE','NOT_TESTED')),
    source_id TEXT NOT NULL REFERENCES sources(id), committed_at TEXT NOT NULL,
    snapshot_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    FOREIGN KEY(assessment_id,attempt_id) REFERENCES assessments(id,attempt_id),
    CHECK(outcome NOT IN ('PASS','FAIL') OR assessment_id IS NOT NULL)
);
CREATE TABLE metric_definitions (
    id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id), kind TEXT NOT NULL CHECK(kind IN ('capability','assistant','role_suitability')),
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)), UNIQUE(name,version,source_id)
);
CREATE TABLE role_criteria (
    id TEXT PRIMARY KEY NOT NULL, metric_id TEXT NOT NULL REFERENCES metric_definitions(id), role TEXT NOT NULL,
    version TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id), criteria_json TEXT NOT NULL CHECK(json_valid(criteria_json))
);
CREATE TABLE metric_results (
    id TEXT PRIMARY KEY NOT NULL, metric_id TEXT NOT NULL REFERENCES metric_definitions(id),
    run_id TEXT NOT NULL REFERENCES runs(id), config_id TEXT NOT NULL REFERENCES runtime_configs(id),
    source_id TEXT NOT NULL REFERENCES sources(id), projection_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('measured','partial','not_tested','insufficient_coverage','unavailable','insufficient_evidence','pending_review','unsupported','blocked','not_attempted')),
    numerator INTEGER CHECK(numerator>=0), denominator INTEGER CHECK(denominator>=0), percentage REAL,
    population_json TEXT NOT NULL CHECK(json_valid(population_json)),
    CHECK(numerator IS NULL OR (denominator IS NOT NULL AND numerator<=denominator)),
    CHECK(percentage IS NULL OR (status='measured' AND denominator>0 AND numerator IS NOT NULL AND
      abs(percentage-100.0*numerator/denominator)<0.00000001))
);
CREATE TABLE metric_members (
    metric_result_id TEXT NOT NULL REFERENCES metric_results(id), case_id TEXT NOT NULL REFERENCES cases(id),
    result_id TEXT NOT NULL REFERENCES committed_results(id), disposition TEXT NOT NULL,
    PRIMARY KEY(metric_result_id,result_id)
);
CREATE TABLE comparison_decisions (
    id TEXT PRIMARY KEY NOT NULL, left_metric_id TEXT NOT NULL REFERENCES metric_results(id),
    right_metric_id TEXT NOT NULL REFERENCES metric_results(id), source_id TEXT NOT NULL REFERENCES sources(id),
    policy_version TEXT NOT NULL, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
    reasons_json TEXT NOT NULL CHECK(json_valid(reasons_json) AND json_type(reasons_json)='array'),
    CHECK(left_metric_id!=right_metric_id), CHECK(eligible=0 OR json_array_length(reasons_json)=0)
);
CREATE TABLE telemetry (
    id TEXT PRIMARY KEY NOT NULL, attempt_id TEXT NOT NULL REFERENCES attempts(id),
    source_id TEXT NOT NULL REFERENCES sources(id), version TEXT NOT NULL, observed_at TEXT NOT NULL,
    artifact_id TEXT REFERENCES artifacts(id), measurements_json TEXT NOT NULL CHECK(json_valid(measurements_json)),
    availability TEXT NOT NULL CHECK(availability IN ('observed','unavailable','partial'))
);
CREATE TABLE publication_records (
    id TEXT PRIMARY KEY NOT NULL, dataset_version TEXT NOT NULL, sanitizer_version TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id), approved_by TEXT NOT NULL, approved_at TEXT NOT NULL,
    public_artifact_id TEXT NOT NULL REFERENCES artifacts(id), approval_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    supersedes_id TEXT REFERENCES publication_records(id), manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json))
);
CREATE TABLE controller_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), name TEXT NOT NULL CHECK(name='existing-queue-process-controller'),
    source_id TEXT NOT NULL REFERENCES sources(id)
);
CREATE TABLE queue_snapshots (
    id TEXT PRIMARY KEY NOT NULL, controller_id INTEGER NOT NULL REFERENCES controller_identity(singleton),
    source_id TEXT NOT NULL REFERENCES sources(id), version TEXT NOT NULL, captured_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('Idle','Running','Paused','Stopped','Complete')),
    state_json TEXT NOT NULL CHECK(json_valid(state_json))
);
CREATE TABLE queue_items (
    snapshot_id TEXT NOT NULL REFERENCES queue_snapshots(id), item_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position>=1),
    config_id TEXT REFERENCES runtime_configs(id), run_id TEXT REFERENCES runs(id),
    state TEXT NOT NULL CHECK(state IN ('Waiting','Running','Complete','Failed','Interrupted')),
    observations_json TEXT NOT NULL CHECK(json_valid(observations_json)), PRIMARY KEY(snapshot_id,item_id), UNIQUE(snapshot_id,position)
);
CREATE TABLE recovery_records (
    id TEXT PRIMARY KEY NOT NULL, controller_id INTEGER NOT NULL REFERENCES controller_identity(singleton),
    source_id TEXT NOT NULL REFERENCES sources(id), run_id TEXT REFERENCES runs(id), attempt_id TEXT REFERENCES attempts(id),
    queue_snapshot_id TEXT REFERENCES queue_snapshots(id), observed_at TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('preserved','incomplete','interrupted','evidence_unavailable','owner_action_required')),
    detail_json TEXT NOT NULL CHECK(json_valid(detail_json))
);
