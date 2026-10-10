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
from .store import DatabaseError, transaction, validate_schema, wal_runtime_safe

VERSION = 'benchmark-case-publication:v1'


def _json(value):
    return canonical_json_bytes(value).decode('utf-8')


def stable_id(kind, *parts):
    return kind + '-' + sha256(canonical_json_bytes(parts)).hexdigest()


def _insert(con, table, values):
    columns = tuple(values)
    row = con.execute('SELECT ' + ','.join(columns) + ' FROM ' + table +
                      ' WHERE ' + ' AND '.join(k+'=?' for k in columns[:1]),
                      (values[columns[0]],)).fetchone()
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


class CasePublisher:
    def __init__(self, con, artifact_root, *, clock, notify=None, fault=None,
                 validation_only=False):
        if not validation_only and not wal_runtime_safe():
            raise DatabaseError('Publication requires a patched operational SQLite runtime')
        validate_schema(con)
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

    def _attempt(self, attempt):
        row = self.con.execute('SELECT a.trial_id,a.source_id,s.execution_status,t.run_id,t.case_id,r.config_id,r.protocol_id FROM attempts a JOIN attempt_execution_state s ON s.id=a.id JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id WHERE a.id=?', (attempt,)).fetchone()
        if row is None:
            raise DatabaseError('Unknown exact attempt identity')
        return row

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

    def executed(self, attempt_id, artifacts, *, interrupted=False, detail=None):
        """Called after native output/tool capture; never infer from exit code."""
        binding = self._attempt(attempt_id)
        self._verify(artifacts, attempt_id)
        with transaction(self.con):
            for artifact in artifacts:
                self._record_artifact(attempt_id, binding[1], artifact)
            self._event(attempt_id, 'execution_interrupted' if interrupted else 'execution_completed',
                        binding[1], detail)
        self._boundary('execution_recorded')

    def _verify(self, artifacts, attempt):
        seen = set()
        prefix = 'publication/'+stable_id('attempt', attempt)+'/'
        for artifact in artifacts:
            if not artifact['relative_path'].startswith(prefix):
                raise DatabaseError('Artifact path/attempt identity mismatch')
            path = _safe_path(self.root, artifact['relative_path'])
            if _hash(path) != (artifact['sha256'], artifact['byte_count']):
                raise DatabaseError('Artifact bytes/hash mismatch')
            identity = (artifact['id'], artifact['purpose'])
            if identity in seen or artifact['id'] != stable_id('artifact', artifact['relative_path']):
                raise DatabaseError('Artifact identity duplicate/mismatch')
            seen.add(identity)

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

    def _all_artifacts(self, attempt, supplied):
        items = {(a['id'],a['purpose']):a for a in supplied}
        for row in self.con.execute('SELECT ar.id,ar.relative_path,ar.sha256,ar.byte_count,ar.media_type,aa.purpose,aa.required FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE aa.attempt_id=?', (attempt,)):
            artifact = dict(zip(('id','relative_path','sha256','byte_count','media_type','purpose','required'),row))
            key = (artifact['id'],artifact['purpose'])
            if key in items and items[key] != artifact:
                raise DatabaseError('Previously captured artifact binding differs')
            items[key] = artifact
        return list(items.values())

    def prepare(self, attempt_id, *, outcome, artifacts, assessment=None,
                projection_row=None, detail=None):
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
        artifacts = self._all_artifacts(attempt_id, artifacts)
        envelope = dict(version=VERSION, attempt_id=attempt_id, trial_id=binding[0],
            run_id=binding[3], case_id=binding[4], config_id=binding[5], source_id=binding[1],
            outcome=outcome, assessment=assessment, artifacts=list(artifacts),
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

    def _prepared(self, attempt_id):
        row = self.con.execute('SELECT envelope_json,envelope_sha256 FROM case_publication_intents WHERE attempt_id=?', (attempt_id,)).fetchone()
        if row is None or sha256(row[0].encode()).hexdigest() != row[1]:
            raise DatabaseError('Missing/corrupt structured publication intent')
        prepared = json.loads(row[0])
        envelope, snapshot = prepared['envelope'], prepared['snapshot']
        binding = self._attempt(attempt_id)
        if (envelope['attempt_id'], envelope['trial_id'], envelope['run_id'], envelope['case_id'], envelope['config_id'], envelope['source_id']) != (attempt_id,binding[0],binding[3],binding[4],binding[5],binding[1]):
            raise DatabaseError('Publication exact identity mismatch')
        artifacts = self._all_artifacts(attempt_id, [*envelope['artifacts'], snapshot])
        self._verify(artifacts, attempt_id)
        if _safe_path(self.root,snapshot['relative_path']).read_bytes() != canonical_json_bytes(envelope):
            raise DatabaseError('Snapshot bytes differ from structured publication')
        return envelope,snapshot,binding,artifacts

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
            if assessment:
                if assessment['artifact_id'] not in {a['id'] for a in envelope['artifacts'] if a['purpose']=='assessment'}:
                    raise DatabaseError('Assessment evidence not bound to publication')
                _insert(self.con, 'assessments', assessment)
            self._event(attempt_id, 'assessment_completed' if assessment and assessment['outcome']!='NOT_ASSESSED' else 'assessment_unavailable', binding[1])
            _insert(self.con, 'committed_results', dict(id=result, attempt_id=attempt_id,
                assessment_id=assessment['id'] if assessment else None, outcome=envelope['outcome'],
                source_id=binding[1], committed_at=self.clock(), snapshot_artifact_id=snapshot['id']))
            self._event(attempt_id, 'result_committed', binding[1], {'result_id': result})
            if assessment:
                _insert(self.con, 'reviews', dict(id=stable_id('review', result),
                    assessment_id=assessment['id'], source_id=binding[1], kind='technical',
                    status='pending', identity_verified=0, recorded_at=self.clock(),
                    binding_json=_json({'result_id':result,'execution_permission':False})))
            self._event(attempt_id, 'review_pending', binding[1], {'execution_permission':False})
            _insert(self.con, 'case_projection_inputs', dict(result_id=result,
                row_json=_json(envelope['projection_row']), row_sha256=sha256(canonical_json_bytes(envelope['projection_row'])).hexdigest()))
            sequence = self.con.execute('SELECT coalesce(max(sequence),0)+1 FROM case_commit_events').fetchone()[0]
            _insert(self.con, 'case_commit_events', dict(sequence=sequence, id=stable_id('case-committed', result), result_id=result))
            self._boundary('during_transaction')
            self._boundary('before_db_commit')
        self._boundary('after_db_commit')
        # Optional notification delivery is deliberately separate from COMMIT.
        return result

    def events(self, *, after=0):
        return [dict(sequence=r[0], id=r[1], result_id=r[2]) for r in self.con.execute('SELECT sequence,id,result_id FROM case_commit_events WHERE sequence>? ORDER BY sequence', (after,))]

    def deliver(self, consumer='native-callback'):
        """At-least-once after commit; callback deduplicates stable event IDs."""
        if self.notify is None:
            return []
        delivered = []
        for event in self.events():
            if self.con.execute('SELECT 1 FROM case_event_receipts WHERE event_id=? AND consumer=?', (event['id'],consumer)).fetchone():
                continue
            self._boundary('before_notify')
            self.notify(event)
            self._boundary('after_notify')
            with transaction(self.con):
                self.con.execute('INSERT INTO case_event_receipts(event_id,consumer) VALUES(?,?)', (event['id'], consumer))
            delivered.append(event['id'])
        return delivered

    def projection(self, *, catalog=None, metadata=None):
        """Rebuild from committed rows only; T13 retains metric/coverage policy."""
        rows = []
        for encoded,digest,attempt in self.con.execute('SELECT p.row_json,p.row_sha256,r.attempt_id FROM case_projection_inputs p JOIN case_commit_events e ON e.result_id=p.result_id JOIN committed_results r ON r.id=p.result_id ORDER BY e.sequence'):
            if sha256(encoded.encode()).hexdigest() != digest:
                raise DatabaseError('Projection input hash mismatch')
            row = json.loads(encoded)
            try:
                self._prepared(attempt)
            except (OSError,ValueError,DatabaseError) as exc:
                if row is not None:
                    row = dict(row,publication_integrity='evidence_unavailable',adapter_exclusion_reason=str(exc))
            rows.append(row)
        result = dict(schema_version=VERSION, committed_results=len(rows), rows=rows,
                      cursor=max((e['sequence'] for e in self.events()), default=0))
        if catalog is not None:
            from localbench.v2.metric_projection import project_metrics
            result['metrics'] = project_metrics([r for r in rows if r is not None], metadata or {}, catalog, evidence_root=self.root)
        return result

    def export(self, destination, *, catalog=None, metadata=None):
        """Replace a derived snapshot atomically; committed DB survives failures."""
        destination = Path(destination)
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
            disposition, reason = ('preserved', None) if committed else ('incomplete', 'no_prepared_publication')
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
            encoded = _json(observation)
            with transaction(self.con):
                _insert(self.con, 'case_recovery_observations', dict(id=stable_id('recovery', observation),
                    attempt_id=attempt, observation_json=encoded))
            observations.append(observation)
        return observations
