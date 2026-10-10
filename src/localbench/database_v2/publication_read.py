"""Shared native publication reads; no scheduler, writer, recovery or rescoring."""
from hashlib import sha256
import json
from pathlib import Path
from localbench.v2.contracts import canonical_json_bytes
from .backup import _safe_path, _hash
from .store import DatabaseError, validate_schema, wal_runtime_safe, migrations

PROJECTION_VERSION = 'benchmark-case-publication:v2'

def _json(value):
    return canonical_json_bytes(value).decode('utf-8')

def stable_id(kind, *parts):
    return kind + '-' + sha256(canonical_json_bytes(parts)).hexdigest()

class PublicationReader:
    def __init__(self, con, artifact_root):
        if not wal_runtime_safe():
            raise DatabaseError('Publication reads require patched SQLite')
        if validate_schema(con) != len(migrations()):
            raise DatabaseError('Publication reads require the current native schema')
        if con.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise DatabaseError('Reader connection must already be query-only')
        self.con = con
        self.root = Path(artifact_root).resolve()

    def _attempt(self, attempt):
        row = self.con.execute('SELECT a.trial_id,a.source_id,s.execution_status,t.run_id,t.case_id,r.config_id,r.protocol_id FROM attempts a JOIN attempt_execution_state s ON s.id=a.id JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id WHERE a.id=?', (attempt,)).fetchone()
        if row is None:
            raise DatabaseError('Unknown exact attempt identity')
        return row


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


    def _all_artifacts(self, attempt, supplied, *, include_snapshot=True):
        items = {(a['id'],a['purpose']):a for a in supplied}
        for row in self.con.execute('SELECT ar.id,ar.relative_path,ar.sha256,ar.byte_count,ar.media_type,aa.purpose,aa.required FROM attempt_artifacts aa JOIN artifacts ar ON ar.id=aa.artifact_id WHERE aa.attempt_id=?', (attempt,)):
            artifact = dict(zip(('id','relative_path','sha256','byte_count','media_type','purpose','required'),row))
            if not include_snapshot and artifact['purpose']=='result_snapshot': continue
            key = (artifact['id'],artifact['purpose'])
            if key in items and items[key] != artifact:
                raise DatabaseError('Previously captured artifact binding differs')
            items[key] = artifact
        return list(items.values())


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


    def event_high_water(self):
        return self.con.execute('SELECT coalesce(max(sequence),0) FROM case_publication_events').fetchone()[0]

    def event_anchor(self, sequence):
        if sequence == 0:
            return None
        row = self.con.execute('SELECT id FROM case_publication_events WHERE sequence=?', (sequence,)).fetchone()
        return row[0] if row else None

    def latest_bindings(self):
        columns=('publication_id','sequence','revision','stage','result_id','attempt_id',
                 'trial_id','case_id','run_id','configuration_id','protocol_id')
        return [dict(zip(columns,row)) for row in self.con.execute(
            'SELECT p.id,e.sequence,p.revision,p.stage,p.result_id,p.attempt_id,a.trial_id,t.case_id,t.run_id,r.config_id,r.protocol_id '
            'FROM case_publication_revisions p JOIN case_publication_events e ON e.id=p.id '
            'JOIN attempts a ON a.id=p.attempt_id JOIN trials t ON t.id=a.trial_id JOIN runs r ON r.id=t.run_id '
            'WHERE p.revision=(SELECT max(q.revision) FROM case_publication_revisions q WHERE q.attempt_id=p.attempt_id) ORDER BY e.sequence')]

    def events(self, *, after=0, limit=None):
        if type(after) is not int or after < 0 or limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('Native event bounds must be nonnegative/positive integers')
        query='SELECT e.sequence,e.id,p.result_id,p.attempt_id,p.revision,p.stage FROM case_publication_events e JOIN case_publication_revisions p ON p.id=e.id WHERE e.sequence>? ORDER BY e.sequence'
        params=(after,)
        if limit is not None:
            query+=' LIMIT ?'
            params+=(limit,)
        return [dict(sequence=r[0],id=r[1],result_id=r[2],attempt_id=r[3],revision=r[4],stage=r[5])
            for r in self.con.execute(query,params)]


    def projection(self, *, catalog=None, metadata=None):
        """Latest append-only publication per attempt; T13 remains the scorer."""
        rows = []
        latest=self.con.execute('SELECT p.row_json,p.row_sha256,p.attempt_id,p.stage,p.artifacts_json,p.snapshot_artifact_id,p.result_id FROM case_publication_revisions p JOIN case_publication_events e ON e.id=p.id WHERE p.revision=(SELECT max(q.revision) FROM case_publication_revisions q WHERE q.attempt_id=p.attempt_id) ORDER BY e.sequence').fetchall()
        for encoded,digest,attempt,stage,artifact_json,snapshot,result_id in latest:
            if sha256(encoded.encode()).hexdigest() != digest:
                raise DatabaseError('Projection input hash mismatch')
            row = json.loads(encoded)
            publication_rows = row if isinstance(row,list) else [row]
            try:
                if stage=='assessed': self._prepared(attempt)
                else:
                    artifacts=json.loads(artifact_json)
                    self._verify(artifacts,attempt)
                    snap=next(a for a in artifacts if a['id']==snapshot)
                    envelope=json.loads(_safe_path(self.root,snap['relative_path']).read_bytes())
                    if envelope['attempt_id']!=attempt or _json(envelope['row'])!=encoded:
                        raise DatabaseError('Capture publication snapshot/identity mismatch')
            except (OSError,ValueError,DatabaseError) as exc:
                publication_rows = [dict(r,publication_integrity='evidence_unavailable',adapter_exclusion_reason=str(exc)) if r is not None else None for r in publication_rows]
            rows.extend(publication_rows)
        result = dict(schema_version=PROJECTION_VERSION, committed_results=sum(r[6] is not None for r in latest),
                      published_attempts=len(latest),rows=rows,
                      cursor=max((e['sequence'] for e in self.events()), default=0))
        if catalog is not None:
            from localbench.v2.metric_projection import project_metrics
            result['metrics'] = project_metrics([r for r in rows if r is not None], metadata or {}, catalog, evidence_root=self.root)
        return result
