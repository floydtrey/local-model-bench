"""Per-case storage extension. Native callers own execution and assessment.

No scheduler, inference, evaluator, server, or queue mutation lives here. Recovery
only verifies/replays already prepared publications; it never runs a candidate.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from localbench.v2.contracts import canonical_json_bytes
from .backup import _safe_path, _hash
from .store import DatabaseError, transaction, validate_schema, wal_runtime_safe, migrations

VERSION = 'benchmark-case-publication:v1'
from .publication_read import PublicationReader, PROJECTION_VERSION, _json, stable_id


def _insert(con, table, values):
    columns = tuple(values)
    identity = 'id' if 'id' in values else {'case_publication_intents':'attempt_id',
                                          'case_projection_inputs':'result_id'}[table]
    row = con.execute('SELECT ' + ','.join(columns) + ' FROM ' + table +
                      ' WHERE ' + identity+'=?', (values[identity],)).fetchone()
    expected = tuple(values.values())
    if row is not None:
        if row != expected:
            raise DatabaseError('Immutable publication replay differs: ' + table)
        return
    con.execute('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', expected)


def _sync_directory(path):
    # Windows has no portable directory fsync. Reconciliation verifies metadata
    # and hashes after restart; this is not a physical power-loss guarantee.
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class CasePublisher(PublicationReader):
    def __init__(self, con, artifact_root, *, clock, notify=None, fault=None,
                 validation_only=False):
        if not validation_only and not wal_runtime_safe():
            raise DatabaseError('Publication requires a patched operational SQLite runtime')
        if validate_schema(con)!=len(migrations()):
            raise DatabaseError('Publication requires the fully migrated authoritative schema')
        for pragma, expected in [('foreign_keys', 1), ('recursive_triggers', 1),
                                  ('journal_mode', 'wal'), ('synchronous', 2)]:
            if con.execute('PRAGMA '+pragma).fetchone()[0] != expected:
                raise DatabaseError('Publication connection lacks '+pragma)
        self.con = con
        self.root = Path(artifact_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock, self.notify = clock, notify
        self.fault = fault or (lambda boundary: None)

    def _boundary(self, name):
        self.fault(name)

    def _event(self, attempt, stage, source, detail=None):
        sequence = self.con.execute('SELECT coalesce(max(sequence),0)+1 FROM lifecycle_events WHERE attempt_id=?', (attempt,)).fetchone()[0]
        _insert(self.con, 'lifecycle_events', dict(id=stable_id('lifecycle', attempt, sequence),
            attempt_id=attempt, sequence=sequence, occurred_at=self.clock(), stage=stage,
            source_id=source, detail_json=_json(detail or {})))

    def schedule(self, *, attempt_id, trial_id, source_id, attempt_index=1,
                 parent_id=None, observations=None):
        values = dict(id=attempt_id, trial_id=trial_id, attempt_index=attempt_index,
            parent_id=parent_id, parent_index=attempt_index-1 if parent_id else None,
            source_id=source_id, execution_status='scheduled', observations_json=_json(observations or {}))
        with transaction(self.con):
            existed = self.con.execute('SELECT 1 FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            _insert(self.con, 'attempts', values)
            if not existed:
                self._event(attempt_id, 'scheduled', source_id)
        self._boundary('scheduled')

    def started(self, attempt_id):
        source = self._attempt(attempt_id)[1]
        with transaction(self.con):
            self._event(attempt_id, 'started', source)
        self._boundary('started')


    def artifact(self, attempt_id, purpose, data, *, required=True, media_type='application/json'):
        """Seal exact bytes in the app's artifact root, never rewrite native files."""
        if not isinstance(data, bytes) or not purpose:
            raise ValueError('Artifact needs exact bytes and an explicit purpose')
        digest = sha256(data).hexdigest()
        relative = 'publication/'+stable_id('attempt', attempt_id)+'/'+digest+'.bin'
        path = _safe_path(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if path.read_bytes() != data:
                raise DatabaseError('Existing finalized artifact differs')
            with path.open('rb+') as stream:
                os.fsync(stream.fileno())
        _sync_directory(path.parent)
        if _hash(path) != (digest, len(data)):
            raise DatabaseError('Finalized artifact read verification failed')
        return dict(id=stable_id('artifact', relative), relative_path=relative,
                    sha256=digest, byte_count=len(data), media_type=media_type,
                    purpose=purpose, required=int(required))

    def executed(self, attempt_id, artifacts, *, interrupted=False, detail=None, publication_row=None):
        """Called after native output/tool capture; never infer from exit code."""
        binding = self._attempt(attempt_id)
        snapshot=None
        if publication_row is not None:
            if any(publication_row.get(k) is not None for k in ('assessed_outcome','score','maximum_score')):
                raise DatabaseError('Capture cannot fabricate native assessment/score')
            envelope=dict(attempt_id=attempt_id,trial_id=binding[0],run_id=binding[3],
                case_id=binding[4],config_id=binding[5],source_id=binding[1],
                row=publication_row,artifacts=list(artifacts))
            snapshot=self.artifact(attempt_id,'capture_publication_snapshot',canonical_json_bytes(envelope))
            publication_id=stable_id('case-capture',attempt_id,snapshot['sha256'])
            prior=self.con.execute("SELECT id FROM case_publication_revisions WHERE attempt_id=? AND stage='capture'",(attempt_id,)).fetchone()
            if prior:
                if prior[0]!=publication_id: raise DatabaseError('Immutable native capture replay differs')
                self._verify([*artifacts,snapshot],attempt_id)
                return publication_id
            artifacts=[*artifacts,snapshot]
        self._verify(artifacts, attempt_id)
        with transaction(self.con):
            for artifact in artifacts:
                self._record_artifact(attempt_id, binding[1], artifact)
            self._event(attempt_id, 'execution_interrupted' if interrupted else 'execution_completed',
                        binding[1], detail)
            if snapshot is not None:
                self._append_revision(publication_id,attempt_id,'capture',None,snapshot['id'],publication_row,artifacts)
                self._boundary('during_capture_transaction')
                self._boundary('before_capture_commit')
                self._verify(artifacts,attempt_id)
        self._boundary('execution_recorded')
        if snapshot is not None:
            self._boundary('after_capture_commit')
            return publication_id

    def _append_revision(self, identity, attempt, stage, result, snapshot, row, artifacts):
        revision=self.con.execute('SELECT coalesce(max(revision),0)+1 FROM case_publication_revisions WHERE attempt_id=?',(attempt,)).fetchone()[0]
        encoded=_json(row)
        _insert(self.con,'case_publication_revisions',dict(id=identity,attempt_id=attempt,revision=revision,
            stage=stage,result_id=result,snapshot_artifact_id=snapshot,row_json=encoded,
            row_sha256=sha256(encoded.encode()).hexdigest(),artifacts_json=_json(artifacts)))
        sequence=self.con.execute('SELECT coalesce(max(sequence),0)+1 FROM case_publication_events').fetchone()[0]
        _insert(self.con,'case_publication_events',dict(sequence=sequence,id=identity))


    def _record_artifact(self, attempt, source, artifact):
        values = {k: artifact[k] for k in ('id','relative_path','sha256','byte_count','media_type')}
        existing = self.con.execute('SELECT source_id,verified_at FROM artifacts WHERE id=?', (artifact['id'],)).fetchone()
        values.update(source_id=source, integrity='verified', verified_at=existing[1] if existing else self.clock())
        _insert(self.con, 'artifacts', values)
        relation = (attempt, artifact['id'], artifact['purpose'], artifact['required'])
        row = self.con.execute('SELECT attempt_id,artifact_id,purpose,required FROM attempt_artifacts WHERE attempt_id=? AND artifact_id=? AND purpose=?', relation[:3]).fetchone()
        if row is None:
            self.con.execute('INSERT INTO attempt_artifacts VALUES(?,?,?,?)', relation)
        elif row != relation:
            raise DatabaseError('Artifact binding replay differs')


    def prepare(self, attempt_id, *, outcome, artifacts, assessment=None,
                assessments=(), native_attempts=(), projection_row=None, detail=None):
        """Prepare recoverable immutable bytes before the result transaction.

        assessment is an exact native assessment mapping, not a scoring request.
        Caller supplies source/protocol/assessor/artifact bindings. Unknown and
        interrupted outcomes retain exact observations without invented scores.
        """
        binding = self._attempt(attempt_id)
        if outcome not in ('PASS','FAIL','BLOCKED','UNKNOWN','UNSUPPORTED','INCOMPLETE','NOT_TESTED'):
            raise ValueError('Unsupported result outcome')
        if assessment is not None:
            if assessment['attempt_id'] != attempt_id or assessment['protocol_id'] != binding[6] or assessment['source_id'] != binding[1]:
                raise DatabaseError('Assessment exact identity mismatch')
            if assessment['outcome'] != outcome and not (outcome == 'UNKNOWN' and assessment['outcome'] == 'NOT_ASSESSED'):
                raise DatabaseError('Assessment/result contradiction')
        artifacts = self._all_artifacts(attempt_id, artifacts, include_snapshot=False)
        envelope = dict(version=VERSION, attempt_id=attempt_id, trial_id=binding[0],
            run_id=binding[3], case_id=binding[4], config_id=binding[5], source_id=binding[1],
            outcome=outcome, assessment=assessment, assessments=list(assessments), native_attempts=list(native_attempts), artifacts=list(artifacts),
            projection_row=projection_row, detail=detail or {})
        snapshot = self.artifact(attempt_id, 'result_snapshot', canonical_json_bytes(envelope))
        self._verify([*artifacts, snapshot], attempt_id)
        self._boundary('evidence_written')
        encoded = _json(dict(envelope=envelope, snapshot=snapshot))
        with transaction(self.con):
            _insert(self.con, 'case_publication_intents', dict(attempt_id=attempt_id,
                envelope_json=encoded, envelope_sha256=sha256(encoded.encode()).hexdigest()))
        self._boundary('publication_prepared')
        return stable_id('result', attempt_id)


    def commit(self, attempt_id):
        envelope,snapshot,binding,artifacts = self._prepared(attempt_id)
        result = stable_id('result', attempt_id)
        existing = self.con.execute('SELECT id FROM committed_results WHERE attempt_id=?', (attempt_id,)).fetchone()
        if existing:
            if existing[0] != result:
                raise DatabaseError('Different result already committed')
            return result
        self._boundary('before_assessment_commit')
        with transaction(self.con):
            for artifact in artifacts:
                self._record_artifact(attempt_id, binding[1], artifact)
            self._event(attempt_id, 'evidence_finalized', binding[1])
            assessment = envelope['assessment']
            all_assessments={a['id']:a for a in envelope.get('assessments',[])}
            if assessment: all_assessments[assessment['id']]=assessment
            for native_assessment in all_assessments.values():
                if native_assessment['attempt_id'] != attempt_id or native_assessment['protocol_id'] != binding[6] or native_assessment['source_id'] != binding[1]:
                    raise DatabaseError('Native assessment exact binding mismatch')
                if native_assessment['artifact_id'] not in {a['id'] for a in envelope['artifacts'] if a['purpose']=='assessment'}:
                    raise DatabaseError('Assessment evidence not bound to publication')
                _insert(self.con, 'assessments', native_assessment)
            for observation in envelope.get('native_attempts',[]):
                if observation['attempt_id']!=attempt_id or observation['source_id']!=binding[1]:
                    raise DatabaseError('Native attempt observation identity mismatch')
                _insert(self.con,'native_attempt_observations',observation)
            self._event(attempt_id, 'assessment_completed' if assessment and assessment['outcome']!='NOT_ASSESSED' else 'assessment_unavailable', binding[1])
            _insert(self.con, 'committed_results', dict(id=result, attempt_id=attempt_id,
                assessment_id=assessment['id'] if assessment else None, outcome=envelope['outcome'],
                source_id=binding[1], committed_at=self.clock(), snapshot_artifact_id=snapshot['id']))
            self._event(attempt_id, 'result_committed', binding[1], {'result_id': result})
            for native_assessment in all_assessments.values():
                self.con.execute('INSERT INTO case_result_assessments VALUES(?,?)',(result,native_assessment['id']))
                _insert(self.con, 'reviews', dict(id=stable_id('review', result, native_assessment['id']),
                    assessment_id=native_assessment['id'], source_id=binding[1], kind='technical',
                    status='pending', identity_verified=0, recorded_at=self.clock(),
                    binding_json=_json({'result_id':result,'execution_permission':False})))
            self._event(attempt_id, 'review_pending', binding[1], {'execution_permission':False})
            _insert(self.con, 'case_projection_inputs', dict(result_id=result,
                row_json=_json(envelope['projection_row']), row_sha256=sha256(canonical_json_bytes(envelope['projection_row'])).hexdigest()))
            sequence = self.con.execute('SELECT coalesce(max(sequence),0)+1 FROM case_commit_events').fetchone()[0]
            _insert(self.con, 'case_commit_events', dict(sequence=sequence, id=stable_id('case-committed', result), result_id=result))
            self._append_revision(stable_id('case-committed',result),attempt_id,'assessed',result,
                                  snapshot['id'],envelope['projection_row'],artifacts)
            self._boundary('during_transaction')
            self._boundary('before_db_commit')
            # Verify again at the actual success boundary. A file disappearing
            # during a transaction must not leave a committed success behind.
            self._verify(artifacts, attempt_id)
        self._boundary('after_db_commit')
        # Optional notification delivery is deliberately separate from COMMIT.
        return result


    def deliver(self, consumer='native-callback'):
        """At-least-once after commit; callback deduplicates stable event IDs."""
        if self.notify is None:
            return []
        delivered = []
        for event in self.events():
            if self.con.execute('SELECT 1 FROM case_publication_receipts WHERE event_id=? AND consumer=?', (event['id'],consumer)).fetchone():
                continue
            self._boundary('before_notify')
            self.notify(event)
            self._boundary('after_notify')
            with transaction(self.con):
                self.con.execute('INSERT INTO case_publication_receipts(event_id,consumer) VALUES(?,?)', (event['id'], consumer))
                # Retain compatibility receipts for the original final-only seam.
                if self.con.execute('SELECT 1 FROM case_commit_events WHERE id=?',(event['id'],)).fetchone():
                    self.con.execute('INSERT INTO case_event_receipts(event_id,consumer) VALUES(?,?)',(event['id'],consumer))
            delivered.append(event['id'])
        return delivered


    def record_review(self, assessment_id, *, review_bytes, reviewer, kind='technical',
                      supersedes_id=None, identity_verified=False):
        """Append already completed native review evidence, never execution consent."""
        if kind not in ('technical','human','reference') or not reviewer:
            raise ValueError('Completed review needs an explicit kind and reviewer')
        row=self.con.execute('SELECT attempt_id,source_id FROM assessments WHERE id=?',(assessment_id,)).fetchone()
        if row is None: raise DatabaseError('Review has no exact committed assessment')
        attempt,source=row
        if not self.con.execute('SELECT 1 FROM case_result_assessments WHERE assessment_id=?',(assessment_id,)).fetchone():
            raise DatabaseError('Review assessment has not been committed')
        if supersedes_id is not None and self.con.execute('SELECT assessment_id FROM reviews WHERE id=?',(supersedes_id,)).fetchone() != (assessment_id,):
            raise DatabaseError('Review supersession crosses assessments')
        artifact=self.artifact(attempt,'review',review_bytes)
        review_id=stable_id('completed-review',assessment_id,artifact['sha256'],reviewer,kind,supersedes_id)
        prior=self.con.execute('SELECT recorded_at FROM reviews WHERE id=?',(review_id,)).fetchone()
        with transaction(self.con):
            self._record_artifact(attempt,source,artifact)
            _insert(self.con,'reviews',dict(id=review_id,assessment_id=assessment_id,source_id=source,
                artifact_id=artifact['id'],supersedes_id=supersedes_id,kind=kind,status='completed',
                reviewer=reviewer,identity_verified=int(identity_verified),recorded_at=prior[0] if prior else self.clock(),
                binding_json=_json({'assessment_id':assessment_id,'review_sha256':artifact['sha256'],
                    'execution_permission':False})))
            if not prior: self._event(attempt,'review_completed',source,{'review_id':review_id,'execution_permission':False})
        return review_id

    def export(self, destination, *, catalog=None, metadata=None):
        """Replace a derived snapshot atomically; committed DB survives failures."""
        destination = Path(destination)
        resolved=destination.resolve()
        for _,_,dbpath in self.con.execute('PRAGMA database_list'):
            if dbpath and resolved in {Path(dbpath).resolve(),Path(dbpath+'-wal').resolve(),Path(dbpath+'-shm').resolve()}:
                raise DatabaseError('Projection export cannot replace authoritative database files')
        if resolved.is_relative_to(self.root/'publication'):
            raise DatabaseError('Projection export cannot replace immutable evidence')
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_bytes(self.projection(catalog=catalog, metadata=metadata))
        fd, temporary = tempfile.mkstemp(prefix=destination.name+'.pending-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._boundary('during_report_export')
            os.replace(temporary, destination)
            _sync_directory(destination.parent)
            self._boundary('after_report_replace')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def recover(self, *, reconcile_prepared=False):
        """Audit publication integrity; never resume execution or advance queue.

        Exact prepared transactions may be replayed explicitly by the native
        owner. Scheduled/started cases are recorded as incomplete/interrupted.
        Committed outcome history is preserved, with corruption visible beside it.
        """
        observations = []
        for attempt, state in self.con.execute('SELECT id,execution_status FROM attempt_execution_state ORDER BY id').fetchall():
            committed = self.con.execute('SELECT id FROM committed_results WHERE attempt_id=?', (attempt,)).fetchone()
            intent = self.con.execute('SELECT 1 FROM case_publication_intents WHERE attempt_id=?', (attempt,)).fetchone()
            capture = self.con.execute("SELECT 1 FROM case_publication_revisions WHERE attempt_id=? AND stage='capture'",(attempt,)).fetchone()
            disposition, reason = ('preserved', None) if committed else ('preserved','capture_published_assessment_pending') if capture else ('incomplete', 'no_prepared_publication')
            try:
                for relative,digest,size in self.con.execute('SELECT ar.relative_path,ar.sha256,ar.byte_count FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE aa.attempt_id=?', (attempt,)):
                    if _hash(_safe_path(self.root,relative)) != (digest,size):
                        raise DatabaseError('Stored artifact integrity mismatch')
                if intent:
                    self._prepared(attempt)
                    if reconcile_prepared and not committed:
                        self.commit(attempt)
                        disposition, reason = 'preserved', 'replayed_exact_prepared_publication'
                    elif not committed:
                        disposition, reason = 'owner_action_required', 'prepared_publication_pending'
                elif state == 'started':
                    disposition, reason = 'interrupted', 'native_execution_did_not_finalize'
            except (OSError, ValueError, DatabaseError) as exc:
                disposition, reason = 'evidence_unavailable', str(exc)
            observation = dict(attempt_id=attempt, disposition=disposition, reason=reason,
                               committed_result_id=committed[0] if committed else None,
                               execution_permission=False)
            prefix='publication/'+stable_id('attempt',attempt)
            directory=self.root/prefix
            indexed={r[0] for r in self.con.execute('SELECT ar.relative_path FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE aa.attempt_id=?',(attempt,))}
            orphans=[]
            if directory.exists():
                for path in sorted(directory.glob('*.bin')):
                    relative=path.relative_to(self.root).as_posix()
                    if relative in indexed: continue
                    try:
                        digest,_=_hash(_safe_path(self.root,relative))
                        if path.stem!=digest: raise DatabaseError('Partial/corrupt unindexed evidence')
                        orphans.append({'relative_path':relative,'integrity':'verified_unindexed'})
                    except (OSError,ValueError,DatabaseError):
                        orphans.append({'relative_path':relative,'integrity':'corrupt_or_unavailable'})
                        observation['disposition']='evidence_unavailable'
                        observation['reason']='partial_or_corrupt_unindexed_evidence'
            observation['unindexed_artifacts']=orphans
            encoded = _json(observation)
            with transaction(self.con):
                _insert(self.con, 'case_recovery_observations', dict(id=stable_id('recovery', observation),
                    attempt_id=attempt, observation_json=encoded))
            observations.append(observation)
        return observations
