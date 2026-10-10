"""Opt-in storage adapter at existing sealed V2 native case boundaries."""
from hashlib import sha256
import json

from localbench.v2.contracts import EvidenceRef, SealedEvidence, canonical_json_bytes
from .publication import CasePublisher, _insert, _json, stable_id
from .store import DatabaseError, record_identity, transaction


class NativeV2Publisher:
    """Native manifests/assessors remain owners; this adapter only publishes.

    One relational run per exact manifest/configuration, retaining the full native
    manifest. Multiple evaluator records are preserved individually as artifacts;
    the case disposition is a conservative fold of their existing verdicts, with
    no new score. Role review verdicts remain NOT_ASSESSED/UNKNOWN.
    """
    def __init__(self, publisher, evidence_store, *, origin='controlled',
                 report_path=None, catalog=None, metadata=None):
        if not isinstance(publisher, CasePublisher):
            raise TypeError('Native publisher requires CasePublisher')
        if origin not in ('controlled','synthetic_test'):
            raise ValueError('Native execution cannot masquerade as historical import')
        self.pub, self.store, self.origin = publisher, evidence_store, origin
        self.report_path, self.catalog, self.metadata = report_path, catalog, metadata
        self.post_commit_errors = []

    def _load(self, reference):
        ref = reference.reference if isinstance(reference,SealedEvidence) else EvidenceRef.from_dict(reference)
        record = self.store.load(ref)
        data = self.store.path_for(ref).read_bytes()
        if data != canonical_json_bytes(record.to_dict()):
            raise DatabaseError('Native sealed artifact byte/identity mismatch')
        return record

    def _source(self, record):
        data = canonical_json_bytes(record.to_dict())
        sid = 'source-'+record.sha256
        _insert(self.pub.con,'sources',dict(id=sid,kind='native_v2',format_version=record.schema_version,
            location='records/'+record.record_type+'/'+record.sha256+'.json',sha256=sha256(data).hexdigest(),
            captured_at='native-sealed-identity',producer_version='native-v2-publication:v1',
            metadata_json=_json({'reference':record.reference.to_dict()})))
        return sid

    def plan(self, *, manifest, case_definitions):
        manifest = self._load(manifest)
        payload = manifest.to_dict()['payload']
        model = self._load(payload['model'])
        host = self._load(payload['host'])
        benchmarks = {r['sha256']:self._load(r) for r in payload['benchmarks']}
        configs = {r['sha256']:self._load(r) for r in payload['effective_configs']}
        evaluators = [self._load(r) for r in payload['evaluators']]
        trials = [self._load(r) for r in payload['trials']]
        # Defining all trials before any start permits honest incomplete recovery.
        definitions = {str(c['case_id']):c for c in case_definitions}
        if len(definitions) != len(case_definitions):
            raise DatabaseError('Duplicate exact native case definition')
        with transaction(self.pub.con):
            source = self._source(manifest)
            model_source = self._source(model)
            record_identity(self.pub.con,'models',id=model.sha256,source_id=model_source,
                version=model.schema_version,payload=model.to_dict())
            environment_source = self._source(host)
            _insert(self.pub.con,'environments',dict(id=host.sha256,source_id=environment_source,
                version=host.schema_version,facts_json=_json(host.to_dict()),captured_at=host.payload['captured_at']))
            protocol = stable_id('protocol',manifest.sha256)
            _insert(self.pub.con,'protocols',dict(id=protocol,name='native-manifest',version='1',
                source_id=source,track='native_sealed_v2',definition_json=_json(payload['harness_source'])))
            for purpose in ('execution','case'):
                if not self.pub.con.execute('SELECT 1 FROM protocol_evidence_requirements WHERE protocol_id=? AND purpose=?',(protocol,purpose)).fetchone():
                    self.pub.con.execute('INSERT INTO protocol_evidence_requirements VALUES(?,?,?)',(protocol,purpose,1))
            for config in configs.values():
                if config.to_dict()['payload']['model'] != model.reference.to_dict() or config.to_dict()['payload']['runtime'] != payload['runtime']:
                    raise DatabaseError('Native configuration/model mismatch')
                record_identity(self.pub.con,'runtime_configs',id=config.sha256,source_id=self._source(config),
                    model_id=model.sha256,version=config.schema_version,payload=config.to_dict())
            for evaluator in evaluators:
                ep = evaluator.to_dict()['payload']
                aid = stable_id('assessor',ep['evaluator_id'],ep['version'],ep['implementation_sha256'])
                prior = self.pub.con.execute('SELECT definition_json FROM assessors WHERE id=?',(aid,)).fetchone()
                if prior and prior[0] != _json(ep):
                    raise DatabaseError('Native assessor identity conflict')
                if not prior:
                    _insert(self.pub.con,'assessors',dict(id=aid,name=ep['evaluator_id'],version=ep['version'],
                        implementation_sha256=ep['implementation_sha256'],source_id=self._source(evaluator),definition_json=_json(ep)))
            for benchmark in benchmarks.values():
                bp = benchmark.to_dict()['payload']
                bs = self._source(benchmark)
                _insert(self.pub.con,'suites',dict(id=benchmark.sha256,name=bp['suite_id'],version=benchmark.schema_version,
                    source_id=bs,definition_json=_json(benchmark.to_dict())))
                for position,case_id in enumerate(bp['case_ids'],1):
                    if case_id not in definitions:
                        raise DatabaseError('Native manifest lacks exact case definition')
                    definition = definitions[case_id]
                    cid = stable_id('case',benchmark.sha256,case_id)
                    _insert(self.pub.con,'cases',dict(id=cid,logical_id=case_id,version='native-case:v1',source_id=bs,
                        input_sha256=sha256(canonical_json_bytes(definition)).hexdigest(),definition_json=_json(definition)))
                    if not self.pub.con.execute('SELECT 1 FROM suite_cases WHERE suite_id=? AND case_id=? AND position=?',(benchmark.sha256,cid,position)).fetchone():
                        self.pub.con.execute('INSERT INTO suite_cases VALUES(?,?,?)',(benchmark.sha256,cid,position))
            for trial in trials:
                tp = trial.to_dict()['payload']
                benchmark = benchmarks[tp['benchmark']['sha256']]
                if tp['benchmark'] != benchmark.reference.to_dict() or tp['effective_config'] != configs[tp['effective_config']['sha256']].reference.to_dict():
                    raise DatabaseError('Native trial/config/benchmark reference mismatch')
                run = stable_id('run',manifest.sha256,benchmark.sha256,tp['effective_config']['sha256'])
                _insert(self.pub.con,'runs',dict(id=run,source_id=source,suite_id=benchmark.sha256,
                    protocol_id=protocol,config_id=tp['effective_config']['sha256'],environment_id=host.sha256,
                    created_at='native-manifest-sealed',origin=self.origin,manifest_json=_json(manifest.to_dict())))
                count = max(t.payload['ordinal'] for t in trials if t.payload['case_id']==tp['case_id'] and t.payload['benchmark']['sha256']==benchmark.sha256)
                tid = stable_id('trial',manifest.sha256,trial.sha256)
                _insert(self.pub.con,'trials',dict(id=tid,run_id=run,suite_id=benchmark.sha256,
                    case_id=stable_id('case',benchmark.sha256,tp['case_id']),ordinal=tp['ordinal'],
                    planned_trials=count,repeat_group=tp['repeat_group'] or tid,source_id=source))
        for trial in trials:
            observation = dict(native_manifest=manifest.reference.to_dict(),native_trial=trial.reference.to_dict(),
                native_case_id=trial.payload['case_id'],expected_evaluators=[r for r in payload['evaluators'] if any(
                    self._load(r).payload['evaluator_id']==e.get('evaluator_id') for e in definitions[trial.payload['case_id']].get('evaluators',[]))])
            self.pub.schedule(attempt_id=self.attempt(manifest,trial),trial_id=stable_id('trial',manifest.sha256,trial.sha256),
                source_id=source,observations=observation)

    @staticmethod
    def attempt(manifest, trial):
        return stable_id('attempt',manifest.sha256,trial.sha256)

    def started(self, *, manifest, trial):
        self.pub.started(self.attempt(manifest,trial))

    def _capture(self, manifest, trial, records):
        attempt = self.attempt(manifest,trial)
        artifacts=[]
        seen=set()
        def references(value):
            if isinstance(value,dict):
                if set(value)=={'record_type','logical_id','sha256'}:
                    yield value
                else:
                    for item in value.values(): yield from references(item)
            elif isinstance(value,list):
                for item in value: yield from references(item)
        pending=list(records)
        while pending:
            purpose,record=pending.pop(0)
            loaded = self._load(record)
            key=(purpose,loaded.sha256)
            if key in seen: continue
            seen.add(key)
            artifacts.append(self.pub.artifact(attempt,purpose,canonical_json_bytes(loaded.to_dict())))
            for reference in references(loaded.to_dict()['payload']):
                if ('native_record',reference['sha256']) not in seen:
                    pending.append(('native_record',self._load(reference)))
        return artifacts

    def executed(self, *, manifest, trial, case_record, execution_records):
        self._case_binding(manifest,trial,case_record)
        artifacts=self._capture(manifest,trial,[('case',case_record),*[('execution',r) for r in execution_records]])
        self.pub.executed(self.attempt(manifest,trial),artifacts,
            detail={'native_case':case_record.reference.to_dict(),'native_status':case_record.payload['status']})

    def _case_binding(self, manifest, trial, case_record):
        cp=case_record.to_dict()['payload']; tp=trial.to_dict()['payload']
        if cp['manifest']!=manifest.reference.to_dict() or cp['trial']!=trial.reference.to_dict() or cp['case_id']!=tp['case_id'] or cp['benchmark']!=tp['benchmark']:
            raise DatabaseError('Native case exact binding mismatch')

    def completed(self, *, manifest, trial, case_record, evaluations, unavailable=None):
        self._case_binding(manifest,trial,case_record)
        attempt=self.attempt(manifest,trial)
        observations=json.loads(self.pub.con.execute('SELECT observations_json FROM attempts WHERE id=?',(attempt,)).fetchone()[0])
        for evaluation in evaluations:
            if evaluation.payload['case'] != case_record.reference.to_dict():
                raise DatabaseError('Native evaluation references another case')
        expected={_json(r) for r in observations['expected_evaluators']}
        observed={_json(e.to_dict()['payload']['evaluator']) for e in evaluations}
        verdicts={e.payload['verdict'] for e in evaluations}
        status=case_record.payload['status']
        outcome = ('BLOCKED' if status=='blocked' else 'UNKNOWN')
        if status=='success' and unavailable is None and expected and observed==expected and len(evaluations)==len(expected):
            outcome='FAIL' if 'fail' in verdicts else 'PASS' if verdicts=={'pass'} else 'UNKNOWN'
        elif status=='protocol_failure':
            outcome='UNKNOWN'
        artifacts=self._capture(manifest,trial,[('assessment',e) for e in evaluations])
        native_assessments=[]
        for evaluation in evaluations:
            ep=self._load(evaluation.payload['evaluator']).payload
            artifact=self.pub.artifact(attempt,'assessment',canonical_json_bytes(evaluation.to_dict()))
            native_outcome={'pass':'PASS','fail':'FAIL','review':'NOT_ASSESSED','not_scored':'NOT_ASSESSED'}[evaluation.payload['verdict']]
            native_assessments.append(dict(id=stable_id('assessment',attempt,evaluation.sha256),attempt_id=attempt,
                assessor_id=stable_id('assessor',ep['evaluator_id'],ep['version'],ep['implementation_sha256']),
                protocol_id=self.pub._attempt(attempt)[6],source_id=self.pub._attempt(attempt)[1],
                artifact_id=artifact['id'],outcome=native_outcome,
                score=evaluation.payload['score'],maximum_score=evaluation.payload['maximum_score'],
                acceptance_checks=len(evaluation.payload['checks']),check_unit='native_evaluator_checks',
                detail_json=_json({'native_evaluation':evaluation.reference.to_dict(),
                    'native_verdict':evaluation.payload['verdict'],'unavailable':unavailable})))
        assessment=next((a for a in native_assessments if a['outcome']==outcome or outcome=='UNKNOWN' and a['outcome']=='NOT_ASSESSED'),None)
        from localbench.v2.report_adapter import normalize_sealed_case
        rows=normalize_sealed_case(case_record,manifest,trial,evaluations,evidence_root=self.store.root,
                                  unavailable=unavailable)
        all_artifacts=self.pub._all_artifacts(attempt,artifacts)
        paths={sha256((self.pub.root/a['relative_path']).read_bytes()).hexdigest():a for a in all_artifacts}
        for row in rows:
            for ref in row.get('evidence_refs',[]):
                if ref.get('sha256') in paths:
                    ref['path']=str(self.pub.root/paths[ref['sha256']]['relative_path'])
            row['publication_attempt_id']=attempt
        self.pub.prepare(attempt,outcome=outcome,artifacts=artifacts,assessment=assessment,assessments=native_assessments,projection_row=rows,
                         detail={'unavailable':unavailable})
        result=self.pub.commit(attempt)
        # These errors are observable and retryable, never report a DB rollback.
        for operation in (self.pub.deliver, lambda:self.pub.export(self.report_path,catalog=self.catalog,metadata=self.metadata) if self.report_path else None):
            try: operation()
            except Exception as exc: self.post_commit_errors.append({'result_id':result,'error':str(exc)})
        return result
