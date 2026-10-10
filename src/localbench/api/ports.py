"""Passive native ports. Caller owns approved source/connection lifecycle."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import threading

from localbench.database_v2.publication_read import PublicationReader
from localbench.database_v2.store import DatabaseError, validate_schema, migrations, wal_runtime_safe
from localbench.database_v2.backup import _safe_path
from localbench.queue_gui.core import read_state_snapshot
from localbench.v2.contracts import canonical_json_bytes

class ReadLimitError(DatabaseError):
    pass

class PrerequisiteFailed(DatabaseError):
    pass

class ResetRequired(ValueError):
    pass

class NativeReadPort:
    """Only an already-open query-only connection; never opens/migrates a DB on GET.

    This is not an owner/controller or authorization provider. The connection
    must be supplied outside request handling and usable on the calling thread.
    SQLite may maintain WAL shared memory when a connection is opened; connection
    opening/restore/rebinding belongs to the approved native owner, not this API.
    """
    def __init__(self, reader: PublicationReader, source, *, queue_path=None):
        self.reader, self.source = reader, source
        self.queue_path = Path(queue_path) if queue_path is not None else None
        self._lock = threading.Lock()

    @contextmanager
    def _snapshot(self):
        if not self._lock.acquire(timeout=0.25):
            raise TimeoutError('Native reader busy')
        con=self.reader.con
        begun=False
        try:
            if con.in_transaction or con.execute('PRAGMA query_only').fetchone()[0]!=1:
                raise DatabaseError('Dedicated reader connection required')
            if not wal_runtime_safe():
                raise PrerequisiteFailed('Patched SQLite required')
            con.execute('BEGIN'); begun=True
            try:
                schema_version=validate_schema(con)
            except DatabaseError:
                raise PrerequisiteFailed('Native schema validation failed') from None
            if schema_version!=len(migrations()):
                raise PrerequisiteFailed('Current native schema required')
            yield con
        finally:
            try:
                if begun: con.execute('ROLLBACK')
            finally:
                self._lock.release()

    def publications(self):
        with self._snapshot() as con:
            count=con.execute('SELECT count(DISTINCT attempt_id) FROM case_publication_revisions').fetchone()[0]
            if count>500: raise ReadLimitError('Snapshot population bound')
            # Bound actual bytes before invoking unchanged native integrity/projection reads.
            total=0
            for relative, in con.execute('SELECT DISTINCT a.relative_path FROM artifacts a JOIN attempt_artifacts aa ON aa.artifact_id=a.id JOIN case_publication_revisions p ON p.attempt_id=aa.attempt_id'):
                try: total+=_safe_path(self.reader.root,relative).stat().st_size
                except (OSError,DatabaseError): continue  # Native projection reports unavailable evidence.
                if total>16*1024*1024: raise ReadLimitError('Evidence read bound')
            native=self.reader.projection()
            if len(canonical_json_bytes(native))>4*1024*1024: raise ReadLimitError('Snapshot response bound')
            bindings=self.reader.latest_bindings()
            high=native['cursor']
            anchor=self.reader.event_anchor(high)
            return native,bindings,high,anchor

    def events(self, after, event_id):
        with self._snapshot():
            high=self.reader.event_high_water()
            if after>high or self.reader.event_anchor(after)!=event_id:
                raise ResetRequired('Cursor no longer belongs to source history')
            events=self.reader.events(after=after,limit=501)
            return events[:500],len(events)>500,high

    def health(self):
        # Schema/prerequisite checks only; no artifacts, projection, recovery or probes.
        try:
            with self._snapshot() as con:
                return {'schema_version':con.execute('PRAGMA user_version').fetchone()[0],
                        'sqlite_version':__import__('sqlite3').sqlite_version,
                        'producer_outcome':'ready'}
        except PrerequisiteFailed:
            return {'schema_version':None,'sqlite_version':__import__('sqlite3').sqlite_version,
                    'producer_outcome':'failed'}

    def queue(self):
        if self.queue_path is None: raise FileNotFoundError('No queue observation source')
        return read_state_snapshot(self.queue_path,maximum_bytes=1024*1024)
