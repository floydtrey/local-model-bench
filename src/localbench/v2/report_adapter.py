"""Read-only adapters into the existing review writer; source evidence is immutable."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import EvidenceRef, SealedEvidence, sha256_json

ADAPTER_VERSION = 'qualification-v2/legacy-read-adapter:v2'
# These identities are emitted by the existing source adapters, not inferred from tags.
QUALIFICATION_SOURCES = {
    'qualification-v2-planner': ('qualification-v2/blind-planner-input-v1', '1', 'qualification-v2/planner-equivalence-v1'),
    'qualification-v2-governor': ('qualification-v2/governor-input-v1', '1', 'qualification-v2/governor-adjudication-v2'),
    'qualification-v2-verification': ('qualification-v2/verification-cases-v2', '2', 'qualification-v2/verification-adjudication-v2'),
}
NULL_FIELDS = ('suite_id', 'suite_version', 'rubric_id', 'rubric_version', 'model_identity',
               'runtime_identity', 'human_adjudication', 'human_review_status', 'worker_mode',
               'first_pass_passed', 'repair_attempted', 'repair_passed', 'assessed_outcome')
JSON_FIELDS = ('model_identity', 'runtime_identity', 'comparison_protocol', 'artifact_sha256',
               'critical_failures', 'failure_classifications', 'source_case_ids', 'evidence_refs')


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f'invalid run report: {exc}') from exc
    if not isinstance(value, dict):
        raise ValueError('run report must be an object')
    return value


def file_reference(path, kind, **fields):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'kind': kind, **fields}


def bind_current_assessment(row, run, campaign):
    """Called only by an existing assessor immediately after writing its result."""
    source = QUALIFICATION_SOURCES[campaign]
    path = Path(row['assessment_file'])
    assessment = _read(path)
    row.update(suite_id=source[0], suite_version=source[1], rubric_id=source[2],
               run_id=Path(run).name, trial_id=Path(run).name,
               attempt_id=path.parent.name, attempt_index=1,
               human_adjudication=assessment.get('human_adjudication'),
               reference_sha256=row.get('reference_bundle_sha256') or row.get('rubric_sha256'),
               assessor_version=assessment.get('schema_version'),
               evidence_version=assessment.get('schema_version'),
               authority_assumptions={'scope': 'benchmark_only_no_role_assignment'},
               evidence_refs=[file_reference(path, 'assessment')])
    candidate = path.parent / 'candidate.txt'
    if candidate.is_file():
        row['evidence_refs'].append(file_reference(candidate, 'candidate'))
    return row


def _resolve_record_identity(row):
    """Resolve available sealed identities without replacing missing legacy facts."""
    directory = row.get('configuration_evidence_directory')
    if not directory:
        return
    def load(ref):
        reference = EvidenceRef.from_dict(ref)
        path = Path(directory) / 'records' / reference.record_type / (reference.sha256 + '.json')
        record = SealedEvidence.from_dict(_read(path))
        if record.reference != reference:
            raise ValueError('identity evidence mismatch')
        row['evidence_refs'] = list(row.get('evidence_refs') or []) + [file_reference(path, reference.record_type, sealed_reference=ref)]
        return record.to_dict()['payload']
    try:
        original = row.get('runtime_identity')
        wrapper = original if isinstance(original, dict) else {}
        runtime_ref = wrapper.get('runtime') or (wrapper if wrapper.get('record_type') == 'runtime_profile' else None)
        model_ref = wrapper.get('model') or row.get('model_identity')
        if runtime_ref:
            row['source_runtime_identity'] = original
            row['runtime_identity'] = load(runtime_ref)
        if isinstance(model_ref, dict) and model_ref.get('record_type') == 'model_identity':
            row['source_model_identity'] = model_ref
            row['model_identity'] = load(model_ref)
        protocol = row.get('comparison_protocol')
        if isinstance(protocol, dict) and isinstance(protocol.get('effective_config'), dict):
            config = protocol['effective_config']
            row['effective_config_observations'] = config
            row['effective_settings'] = config.get('settings')
            row['context_tokens'] = (config.get('settings') or {}).get('generation', {}).get('context_tokens')
        session_directory = row.get('session_evidence_directory') or row.get('evidence_directory')
        events_path = Path(session_directory) / 'events.jsonl' if session_directory else None
        if events_path and events_path.is_file():
            observed = []
            for ordinal, line in enumerate(events_path.read_bytes().splitlines(), 1):
                event = json.loads(line)
                digest = event.pop('event_sha256', None)
                if event.get('sequence') != ordinal or sha256_json(event) != digest:
                    raise ValueError('role event integrity mismatch')
                if event.get('event_type') == 'assistant001_effective_config':
                    config = load(event['payload'])
                    if (runtime_ref and config['runtime'] != runtime_ref
                            or isinstance(model_ref, dict) and model_ref.get('record_type') == 'model_identity'
                            and config['model'] != model_ref):
                        raise ValueError('effective configuration identity mismatch')
                    observed.append(config)
            if observed:
                row['evidence_refs'].append(file_reference(events_path, 'role_events'))
                row['effective_configuration_observations'] = observed
                inputs_path = Path(directory).parent / 'runner-inputs.json'
                inputs = _read(inputs_path) if inputs_path.is_file() else {}
                budget = inputs.get('timeout_seconds')
                normalized = []
                for config in observed:
                    # Same policy as the existing Governor comparison: observed
                    # remaining call time is retained, while identity uses the
                    # original case budget when that budget is actually recorded.
                    value = json.loads(json.dumps(config))
                    if type(budget) in (int, float) and budget > 0:
                        value.get('limits', {})['timeout_seconds'] = budget
                        value.get('settings', {}).get('adapter_resolution', {}).get('effective_request', {})['timeout_seconds'] = budget
                    if value not in normalized:
                        normalized.append(value)
                row['effective_settings'] = normalized
                contexts = {c.get('settings', {}).get('generation', {}).get('context_tokens') for c in observed}
                row['context_tokens'] = next(iter(contexts)) if len(contexts) == 1 else None
                if inputs_path.is_file():
                    row['evidence_refs'].append(file_reference(inputs_path, 'runner_inputs'))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        row['adapter_exclusion_reason'] = str(exc)


def normalize_rows(rows, metadata=None, *, source_path=None, source_root=None):
    """Keep original fields; add only documented aliases or verified source identities."""
    metadata = metadata or {}
    if source_root is None and source_path:
        source_root = Path(source_path).parent
    result = []
    for original in rows:
        if not isinstance(original, dict) or not isinstance(original.get('case_id'), str):
            raise ValueError('invalid case row in report')
        row = {**metadata, **original}
        if isinstance(row.get('evidence_refs'), list):
            row['evidence_refs'] = list(row['evidence_refs'])
        for key in NULL_FIELDS:
            row.setdefault(key, None)
        for key in JSON_FIELDS:
            value = row.get(key)
            if isinstance(value, str) and value[:1] in ('{', '['):
                try:
                    row[key] = json.loads(value)
                except ValueError:
                    pass
        if row.get('execution_status') is None:
            row['execution_status'] = row.get('status')
        if row.get('assessed_outcome') is None:
            row['assessed_outcome'] = row.get('assessment_outcome')
        if row.get('track') is None:
            row['track'] = row.get('evaluation_track')
        if isinstance(row.get('track'), str):
            row['track'] = row['track'].lower()
        if isinstance(row.get('worker_mode'), str):
            row['worker_mode'] = row['worker_mode'].upper()
        if row.get('campaign') in ('assistant-001-v1', 'assistant-002-v1') and row.get('role') == 'worker':
            row.setdefault('acceptance_check_unit', 'cumulative_checks_at_task')
            if source_root:
                identity_path = Path(source_root) / 'runtime-identity.json'
                if identity_path.is_file() and row.get('runtime_identity') is None:
                    row['runtime_identity'] = _read(identity_path)
                    row['configuration_evidence_directory'] = str(Path(source_root) / 'evidence')
        source = QUALIFICATION_SOURCES.get(row.get('campaign'))
        # A campaign string alone cannot retroactively supply an absent rubric.
        if source and row.get('rubric_version') == source[2]:
            row['suite_id'] = row.get('suite_id') or source[0]
            row['suite_version'] = row.get('suite_version') or source[1]
            row['rubric_id'] = row.get('rubric_id') or source[2]
        if source_path:
            row['source_report'] = str(source_path)
            row.setdefault('source_evidence_root', str(Path(source_path).resolve().parent))
        _resolve_record_identity(row)
        result.append(row)
    return result


def _aggregate_rows(payload, evidence_root, source_path):
    """Expand exact sealed case/evaluator/trial references, not aggregate percentages."""
    root = Path(evidence_root) if evidence_root else None
    def load(ref):
        if root is None:
            raise ValueError('sealed evidence root unavailable')
        reference = EvidenceRef.from_dict(ref)
        path = root / 'records' / reference.record_type / (reference.sha256 + '.json')
        record = SealedEvidence.from_dict(_read(path))
        if record.reference != reference:
            raise ValueError('evidence reference mismatch')
        return record.to_dict()['payload'], file_reference(path, reference.record_type, sealed_reference=ref)

    results = []
    for aggregate in payload['cases']:
        fallback = {'case_id': aggregate['case_id'], 'source_aggregate': aggregate,
                    'planned_trial_count': aggregate.get('planned_trials'),
                    'observed_trial_count': aggregate.get('observed_trials'),
                    'repeat_group': aggregate.get('repeat_group'), 'source_report': str(source_path),
                    'execution_status': None, 'assessed_outcome': None, 'evidence_refs': []}
        try:
            case_rows = []
            benchmark, benchmark_ref = load(payload['benchmark'])
            manifest, manifest_ref = load(payload['manifest'])
            model, model_ref = load(manifest['model'])
            runtime, runtime_ref = load(manifest['runtime'])
            evaluations = [load(ref) for ref in aggregate['evidence']['evaluation_results']]
            cases = [load(ref) for ref in aggregate['evidence']['case_results']]
            bindings = [load(ref) for ref in manifest.get('execution_bindings', [])]
            for case, case_ref in cases:
                if case['case_id'] != aggregate['case_id'] or case['manifest'] != payload['manifest'] or case['benchmark'] != payload['benchmark']:
                    raise ValueError('aggregate case binding mismatch')
                trial, trial_ref = load(case['trial'])
                if trial['case_id'] != case['case_id'] or trial['benchmark'] != payload['benchmark']:
                    raise ValueError('trial binding mismatch')
                config, config_ref = load(trial['effective_config'])
                if config['model'] != manifest['model'] or config['runtime'] != manifest['runtime']:
                    raise ValueError('configuration binding mismatch')
                bound = [(b, ref) for b, ref in bindings if b['trial'] == case['trial']]
                if len(bound) != 1:
                    raise ValueError('missing or ambiguous execution binding')
                binding, binding_ref = bound[0]
                execution_refs = []
                execution = case.get('execution_evidence') or {}
                if execution.get('primary'):
                    _, execution_ref = load(execution['primary'])
                    execution_refs.append(execution_ref)
                else:
                    raise ValueError('missing primary execution evidence')
                matched = [(ev, ref) for ev, ref in evaluations if ev['case'] == case_ref['sealed_reference']]
                # Preserve unevaluated cases as unknown, and different evaluators separately.
                for ev, evref in matched or [(None, None)]:
                    rubric, rubref = load(ev['evaluator']) if ev else ({}, None)
                    refs = [benchmark_ref, manifest_ref, model_ref, runtime_ref, case_ref, trial_ref, config_ref, binding_ref] + execution_refs
                    if evref:
                        refs += [evref, rubref]
                    suite_version = None
                    locator = benchmark.get('source_locator')
                    if locator:
                        candidate = Path(locator)
                        if not candidate.is_absolute():
                            candidate = Path(__file__).resolve().parents[3] / candidate
                        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == benchmark['source_sha256']:
                            pack = _read(candidate)
                            suite_version = pack.get('pack_version')
                            refs.append(file_reference(candidate, 'suite'))
                    case_rows.append({**fallback, 'source_aggregate': None, 'suite_id': benchmark['suite_id'],
                        'suite_version': suite_version, 'rubric_id': rubric.get('evaluator_id'),
                        'rubric_version': rubric.get('version'), 'rubric_sha256': ev['evaluator']['sha256'] if ev else None,
                        'assessor_version': rubric.get('implementation_sha256'), 'evidence_version': 'benchmark-lab-evidence:v2',
                        'execution_status': case['status'], 'assessed_outcome': ev.get('verdict') if ev else None,
                        'human_review_required': rubric.get('requires_human_review'),
                        'model_identity': model, 'runtime_identity': runtime,
                        'effective_settings': config['settings'], 'context_tokens': config['settings'].get('generation', {}).get('context_tokens'),
                        'track': trial['layer'], 'comparison_protocol': {'repetition_phase': payload['repetition_phase'], 'harness_source': manifest['harness_source']},
                        'authority_assumptions': {'layer': trial['layer'], 'execution_mode': binding['execution_mode'],
                                                  'containment': binding.get('containment')},
                        'execution_binding': binding, 'run_id': payload['manifest']['logical_id'],
                        'trial_id': case['trial']['logical_id'], 'trial_ordinal': trial['ordinal'], 'ordinal': trial['ordinal'],
                        'attempt_id': case_ref['sealed_reference']['logical_id'], 'attempt_index': 1,
                        'input_sha256': benchmark['source_sha256'], 'reference_sha256': benchmark['source_sha256'],
                        'artifact_sha256': case_ref['sealed_reference']['sha256'], 'evidence_refs': refs,
                        'acceptance_check_count': len(ev.get('checks', [])) if ev else None,
                        'acceptance_check_unit': 'evaluator_checks_in_trial',
                        'assessment_check_score': {k: ev.get(k) for k in ('score', 'maximum_score', 'checks')} if ev else None,
                        'critical_failures': ev.get('hard_failures') if ev else None})
            results.extend(case_rows)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            results.append({**fallback, 'adapter_exclusion_reason': str(exc)})
    return normalize_rows(results)


def normalize_sealed_case(case_record, manifest, trial, evaluations, *, evidence_root, unavailable=None):
    """Use the existing T13 exact-reference adapter at a native per-case boundary.

    This envelope supplies reference lists, never a fabricated aggregate score.
    Missing evaluation/metadata stays explicit. It does not claim suite completion.
    """
    payload = {'benchmark': case_record.payload['benchmark'],
        'manifest': manifest.reference.to_dict(),
        'repetition_phase': manifest.payload['harness_source'].get('repetition_phase', 'single'),
        'cases': [{'case_id': case_record.payload['case_id'],
            'repeat_group': trial.payload['repeat_group'], 'planned_trials': None,
            'observed_trials': 1, 'evidence': {
                'case_results': [case_record.reference.to_dict()],
                'evaluation_results': [e.reference.to_dict() for e in evaluations]}}]}
    rows = _aggregate_rows(payload, evidence_root, 'native-per-case-publication')
    if unavailable is not None:
        for row in rows:
            row['adapter_exclusion_reason'] = 'native_assessment_unavailable:' + str(unavailable)
    return rows


def normalize_legacy_report(path: Path, *, evidence_root=None) -> dict[str, Any]:
    """Read historical, Assistant, qualification and sealed V2 aggregate reports."""
    path, raw = Path(path), _read(path)
    sealed = raw.get('schema_version') == 'benchmark-lab-evidence:v2'
    if sealed:
        record = SealedEvidence.from_dict(raw)
        if record.record_type != 'aggregate_report':
            raise ValueError('unsupported sealed report type')
        payload = record.to_dict()['payload']
    else:
        payload = raw
    if payload.get('report_version') == 'benchmark-lab-aggregate-report:v1':
        kind, metadata = 'v2-aggregate-report', {'repetition_phase': payload.get('repetition_phase')}
        rows = _aggregate_rows(payload, evidence_root, path)
    elif raw.get('schema_version') == 'flashnext-role-review-package:v1':
        kind, metadata = 'historical-role-review', raw.get('metadata') or {}
        normalized = raw.get('qualification_v2_metrics', {})
        rows = normalized.get('case_details', raw.get('case_results'))
    elif raw.get('campaign') in ('assistant-001-v1', 'assistant-002-v1', *QUALIFICATION_SOURCES):
        kind = 'qualification-role' if raw['campaign'] in QUALIFICATION_SOURCES else 'assistant-worker-project'
        metadata = {k: v for k, v in raw.items() if k not in ('results', 'review_package')}
        rows = raw.get('results')
    else:
        raise ValueError('unsupported legacy report schema')
    if not isinstance(rows, list) or not isinstance(metadata, dict):
        raise ValueError('invalid report shape')
    rows = normalize_rows(rows, metadata, source_path=path)
    return {'schema_version': ADAPTER_VERSION, 'source_kind': kind, 'source_path': str(path),
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'metadata': metadata, 'cases': rows, 'raw_report': raw,
            'review_package': raw.get('review_package'),
            'legacy_fields_unknown': True, 'role_qualification': None}


def write_normalized_review(source: Path, output_dir: Path, *, evidence_root=None):
    """Export through the original writer into a new directory; never edit the input."""
    from .flashnext_review import write_review_package
    normalized = normalize_legacy_report(source, evidence_root=evidence_root)
    if Path(source).resolve().is_relative_to(Path(output_dir).resolve() / 'review'):
        raise ValueError('source report must remain outside the new review output')
    return write_review_package(output_dir=Path(output_dir),
        summary={**normalized['metadata'], 'results': normalized['cases']},
        profile=normalized['metadata'], shared_run=None, phase='read-only-normalization')
