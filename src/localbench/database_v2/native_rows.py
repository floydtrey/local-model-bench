"""Storage callback for native v1/Assistant/controlled-role case boundaries.

The native Owner registers exact planned trial/configuration bindings before
dispatch. This module does not invent missing legacy identities or own a run.
"""
from pathlib import Path
import json
from hashlib import sha256
import stat

from localbench.v2.contracts import canonical_json_bytes, EvidenceRef
from localbench.v2.metric_projection import assessed_outcome, contradictions, inspect_evidence, human_review_state
from localbench.v2.report_adapter import normalize_rows
from .backup import _safe_path
from .publication import stable_id
from .store import DatabaseError


def _native_path(root, path):
    """Canonicalize Windows short aliases after rejecting links on original path."""
    original=Path(path).absolute()
    for part in (*reversed(original.parents),original):
        if part.is_symlink() or part.exists() and getattr(part.lstat(),'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise DatabaseError('Link-like native evidence path')
    resolved=original.resolve()
    if not resolved.is_relative_to(root): raise DatabaseError('Native evidence escapes declared run root')
    return _safe_path(root,resolved.relative_to(root).as_posix())


class NativeRowPublisher:
    def __init__(self, publisher, *, report_path=None, catalog=None, origin='controlled'):
        self.pub, self.report_path, self.catalog = publisher, report_path, catalog
        self.post_commit_errors=[]
        self.origin=origin

    def plan_sealed_case(self, *, key, manifest, trial, case_definition, input_bytes, input_version, evidence_store):
        """Record the existing native sealed plan, before its first session call."""
        from .native_v2 import NativeV2Publisher
        if trial.reference.to_dict() not in manifest.to_dict()['payload']['trials']:
            raise DatabaseError('Native sealed plan/trial mismatch')
        NativeV2Publisher(self.pub,evidence_store,origin=self.origin).plan(manifest=manifest,
            case_definitions=[case_definition],pack_source=input_bytes,input_version=input_version,native_row_key=key)

    def register(self, key, *, trial_id, source_id, case_id, assessment_binding=None, configuration_binding=None):
        """Bind a native key to an existing exact trial; never merge by case name."""
        planned=self.pub.con.execute('SELECT c.logical_id,r.config_id FROM trials t JOIN cases c ON c.id=t.case_id JOIN runs r ON r.id=t.run_id WHERE t.id=?',(trial_id,)).fetchone()
        if planned is None or planned[0]!=case_id: raise DatabaseError('Native registration differs from exact relational case')
        if configuration_binding is not None and configuration_binding.get('config_id')!=planned[1]:
            raise DatabaseError('Native registration configuration differs from exact trial')
        self.pub.schedule(attempt_id=stable_id('native-row-attempt',key),trial_id=trial_id,source_id=source_id,
            observations={'native_key':list(key),'native_case_id':case_id,'assessment_binding':assessment_binding or {},
                          'configuration_binding':configuration_binding})

    def _binding(self,key):
        attempt=stable_id('native-row-attempt',key)
        found=self.pub.con.execute('SELECT observations_json FROM attempts WHERE id=?',(attempt,)).fetchone()
        if not found: raise DatabaseError('Native case has no pre-registered exact trial/configuration binding')
        observation=json.loads(found[0])
        if observation['native_key'] != list(key): raise DatabaseError('Native publication key differs')
        return attempt,observation

    def started(self, *, key):
        attempt,_=self._binding(key); self.pub.started(attempt)

    def completed(self, *, key, row, native_root, artifact_paths=(), native_attempts=(), sealed_records=(), evidence_store=None):
        attempt,binding=self._binding(key)
        if row.get('case_id') != binding['native_case_id']:
            raise DatabaseError('Native row differs from registered exact case')
        root=Path(native_root).resolve()
        paths=set(Path(p).absolute() for p in artifact_paths)
        for name in ('assessment_file','evidence_directory','session_evidence_directory'):
            if row.get(name): paths.add(Path(row[name]).absolute())
        for ref in row.get('evidence_refs',[]):
            path=Path(ref['path'])
            paths.add(path.absolute() if path.is_absolute() else (root/path).absolute())
        files=set()
        for path in paths:
            safe=_native_path(root,path)
            if safe.is_dir(): files.update(safe.rglob('*'))
            else: files.add(safe)
        artifacts=[self.pub.artifact(attempt,'case',canonical_json_bytes(row))]
        pending=list(sealed_records); seen=set(); sealed_evaluations=[]
        def references(value):
            if isinstance(value,dict):
                if set(value)=={'record_type','logical_id','sha256'}: yield EvidenceRef.from_dict(value)
                else:
                    for item in value.values(): yield from references(item)
            elif isinstance(value,list):
                for item in value: yield from references(item)
        while pending:
            record=pending.pop(0)
            if evidence_store is None: raise DatabaseError('Native sealed evidence store unavailable')
            loaded=evidence_store.load(record.reference)
            data=evidence_store.path_for(record).read_bytes()
            if loaded.reference!=record.reference or data!=canonical_json_bytes(record.to_dict()):
                raise DatabaseError('Native sealed record bytes/identity mismatch')
            if record.sha256 in seen: continue
            if record.record_type=='case_result' and record.payload['case_id']!=binding['native_case_id']:
                raise DatabaseError('Native sealed case differs from registered identity')
            seen.add(record.sha256)
            purpose='execution' if record.record_type in ('role_execution_trace','tool_execution_trace','intrinsic_execution_trace') else 'case' if record.record_type=='case_result' else 'assessment' if record.record_type=='evaluation_result' else 'sealed_record'
            artifact=self.pub.artifact(attempt,purpose,data); artifacts.append(artifact)
            if record.record_type=='evaluation_result':
                if dict(record.payload['case'])!=row.get('records',{}).get('case_result'):
                    raise DatabaseError('Native sealed evaluation references another case')
                sealed_evaluations.append((record,artifact))
            pending.extend(evidence_store.load(ref) for ref in references(record.to_dict()['payload']) if ref.sha256 not in seen)
        copied={}
        missing=[]
        capture_manifest=[]
        for path in sorted(files):
            safe=_native_path(root,path)
            relative=safe.relative_to(root).as_posix()
            if safe.is_dir(): continue
            try: data=safe.read_bytes()
            except FileNotFoundError:
                missing.append(relative); continue
            purpose='assessment' if row.get('assessment_file') and safe==Path(row['assessment_file']).resolve() else 'native_file:'+relative
            artifact=self.pub.artifact(attempt,purpose,data)
            artifacts.append(artifact); copied[str(safe)]=artifact
            capture_manifest.append({'native_relative_path':relative,'artifact_id':artifact['id'],
                'sha256':artifact['sha256'],'byte_count':artifact['byte_count'],'purpose':purpose})
        if any(item['purpose'].startswith('native_file:') for item in capture_manifest):
            artifacts.append(self.pub.artifact(attempt,'capture',canonical_json_bytes(capture_manifest)))
        artifacts=list({(a['id'],a['purpose']):a for a in artifacts}.values())
        self.pub.executed(attempt,artifacts,detail={'native_execution_status':row.get('execution_status',row.get('status'))})
        normalized=normalize_rows([row])[0]
        _,reasons=inspect_evidence(normalized,root)
        reasons+=contradictions(normalized)
        configuration=binding['configuration_binding']
        if not configuration or not configuration.get('row_fields'):
            reasons.append('native_configuration_binding_unavailable')
        elif any(canonical_json_bytes(normalized.get(k))!=canonical_json_bytes(v) for k,v in configuration['row_fields'].items()):
            reasons.append('native_configuration_binding_mismatch')
        assessment_path=Path(row['assessment_file']).resolve() if row.get('assessment_file') else None
        assessment_data=json.loads((self.pub.root/copied[str(assessment_path)]['relative_path']).read_bytes()) if assessment_path and str(assessment_path) in copied else None
        if missing: reasons.append('native_capture_missing:'+','.join(missing))
        for ref in normalized.get('evidence_refs',[]):
            path=Path(ref['path']); path=path.absolute() if path.is_absolute() else (root/path).absolute()
            artifact=copied.get(str(path))
            if artifact is None or artifact['sha256'] != ref.get('sha256'):
                reasons.append('native_copied_evidence_hash_mismatch')
        exact=binding['assessment_binding']
        if assessment_data is not None:
            if exact:
                if any(canonical_json_bytes(assessment_data.get(k))!=canonical_json_bytes(v) for k,v in exact.items() if not k.startswith('_')):
                    reasons.append('exact_native_assessment_binding_mismatch')
            elif assessment_data.get('case_id') != row['case_id']:
                reasons.append('missing_exact_native_assessment_binding')
        outcome={'passed':'PASS','failed':'FAIL','blocked':'BLOCKED'}.get(assessed_outcome(normalized),'UNKNOWN')
        execution=normalized.get('execution_status',row.get('status'))
        if execution in ('blocked','unsupported','not_tested','interrupted','resource_limit'):
            outcome={'blocked':'BLOCKED','unsupported':'UNSUPPORTED','not_tested':'NOT_TESTED',
                     'interrupted':'INCOMPLETE','resource_limit':'INCOMPLETE'}[execution]
        elif execution in ('error','protocol_failure'): outcome='UNKNOWN'
        if reasons or assessment_data is None:
            if outcome not in ('BLOCKED','UNSUPPORTED','NOT_TESTED','INCOMPLETE'): outcome='UNKNOWN'
            normalized['adapter_exclusion_reason']=';'.join(reasons) or 'native_assessment_unavailable'
        assessment=None
        if assessment_data is not None and outcome in ('PASS','FAIL','BLOCKED'):
            protocol=self.pub._attempt(attempt)[6]
            assessor=exact.get('_assessor_id')
            # Assessor selection is pre-registered native provenance, never guessed.
            if assessor is None:
                outcome='UNKNOWN'; normalized['adapter_exclusion_reason']='native_assessor_identity_unavailable'
            else:
                assessment=dict(id=stable_id('native-assessment',attempt),attempt_id=attempt,assessor_id=assessor,
                    protocol_id=protocol,source_id=self.pub._attempt(attempt)[1],artifact_id=copied[str(assessment_path)]['id'],
                    outcome=outcome,detail_json=json.dumps(assessment_data,sort_keys=True),
                    acceptance_checks=row.get('acceptance_check_count'),check_unit=row.get('acceptance_check_unit'))
        for ref in normalized.get('evidence_refs',[]):
            original=str(Path(ref['path']).resolve())
            if original in copied: ref['path']=copied[original]['relative_path']
        normalized.pop('source_evidence_root',None)
        supplementary=[]
        for record,artifact in sealed_evaluations:
            evaluator=evidence_store.load(EvidenceRef.from_dict(record.payload['evaluator'])).payload
            assessor=stable_id('assessor',evaluator['evaluator_id'],evaluator['version'],evaluator['implementation_sha256'])
            if not self.pub.con.execute('SELECT 1 FROM assessors WHERE id=?',(assessor,)).fetchone():
                raise DatabaseError('Native sealed evaluator has no registered exact assessor')
            supplementary.append(dict(id=stable_id('assessment',attempt,record.sha256),attempt_id=attempt,assessor_id=assessor,
                protocol_id=self.pub._attempt(attempt)[6],source_id=self.pub._attempt(attempt)[1],artifact_id=artifact['id'],
                outcome={'pass':'PASS','fail':'FAIL','review':'NOT_ASSESSED','not_scored':'NOT_ASSESSED'}[record.payload['verdict']],
                score=record.payload['score'],maximum_score=record.payload['maximum_score'],acceptance_checks=len(record.payload['checks']),
                check_unit='native_evaluator_checks',detail_json=json.dumps(record.to_dict(),sort_keys=True)))
        if assessment is None and outcome=='UNKNOWN':
            assessment=next((a for a in supplementary if a['outcome']=='NOT_ASSESSED'),None)
        observations=[]
        supplied=list(native_attempts)
        if not supplied and isinstance(row.get('attempts'),list):
            supplied=[{'kind':'transport_attempt','observations':item} for item in row['attempts']]
        for index,item in enumerate(supplied,1):
            data=canonical_json_bytes(item['observations'])
            if item.get('evidence_path'):
                path=_native_path(root,item['evidence_path']); data=path.read_bytes()
                if canonical_json_bytes(json.loads(data))!=canonical_json_bytes(item['observations']):
                    raise DatabaseError('Native attempt evidence differs from owner observation')
            artifact=self.pub.artifact(attempt,'native_attempt',data)
            artifacts.append(artifact)
            identity=stable_id('native-phase',attempt,index)
            parent=stable_id('native-phase',attempt,index-1) if item['kind']=='repair' else None
            observations.append(dict(id=identity,attempt_id=attempt,ordinal=index,kind=item['kind'],
                parent_id=parent,parent_ordinal=index-1 if parent else None,source_id=self.pub._attempt(attempt)[1],
                artifact_id=artifact['id'],observations_json=json.dumps(item['observations'],sort_keys=True)))
            if item['kind'] in ('first_pass','repair'):
                normalized.setdefault('evidence_refs',[]).append({'kind':item['kind'],'path':artifact['relative_path'],'sha256':artifact['sha256']})
        artifacts=list({(a['id'],a['purpose']):a for a in artifacts}.values())
        normalized['native_attempt_observation_ids']=[item['id'] for item in observations]
        normalized['native_attempt_observation_count']=len(observations)
        self.pub.prepare(attempt,outcome=outcome,artifacts=artifacts,assessment=assessment,assessments=supplementary,native_attempts=observations,projection_row=normalized)
        result=self.pub.commit(attempt)
        if assessment is not None and human_review_state(normalized)=='recorded':
            review=normalized['human_adjudication']
            self.pub.record_review(assessment['id'],review_bytes=canonical_json_bytes(review),
                reviewer=review['reviewer'],kind='human',identity_verified=False)
        for operation in (self.pub.deliver,lambda:self.pub.export(self.report_path,catalog=self.catalog) if self.report_path else None):
            try: operation()
            except Exception as exc: self.post_commit_errors.append({'result_id':result,'error':str(exc)})
        return result
