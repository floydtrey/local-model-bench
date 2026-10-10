"""Schema/storage primitives, intentionally unwired from live owners.

Operational WAL use requires a WAL-reset-bug patched linked SQLite runtime.
validation_only is an explicit test/offline-schema escape hatch, never an
operational concurrency policy. One queue controller does not mean one DB writer.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sqlite3

from localbench.v2.contracts import canonical_json_bytes

APPLICATION_ID = 0x424C5632


class DatabaseError(RuntimeError):
    pass


def wal_runtime_safe(version=None):
    version = tuple(version or sqlite3.sqlite_version_info)
    return (version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0)
            or (3, 44, 6) <= version < (3, 45, 0))


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def digest(self):
        return sha256(self.sql.encode('utf-8')).hexdigest()


def migrations():
    return tuple(Migration(int(p.name.split('_')[0]), p.name, p.read_text(encoding='utf-8'))
                 for p in sorted((Path(__file__).parent / 'migrations').glob('*.sql')))


def connect(path, *, validation_only=False):
    """Open a DB with explicit durability pragmas; do not dispatch any work.

    Unsupported SQLite is gated before touching a file. Offline deterministic
    schema/backup validation may opt in on new isolated scratch databases.
    Production callers must never set validation_only.
    """
    if not validation_only and not wal_runtime_safe():
        raise DatabaseError('Operational WAL storage requires SQLite 3.51.3+, 3.50.7 or 3.44.6 backport; linked runtime is ' + sqlite3.sqlite_version)
    con = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    try:
        validate_schema(con)
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=5000')
        mode = con.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        con.execute('PRAGMA synchronous=FULL')
        if mode != 'wal' or con.execute('PRAGMA synchronous').fetchone()[0] != 2 or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise DatabaseError('Durability/foreign key configuration unavailable')
        migrate(con)
        return con
    except BaseException:
        con.close()
        raise


@contextmanager
def transaction(con):
    if con.in_transaction:
        raise DatabaseError('Nested or implicit transaction is not supported')
    con.execute('BEGIN IMMEDIATE')
    try:
        yield con
        con.execute('COMMIT')
    except BaseException:
        if con.in_transaction:
            con.execute('ROLLBACK')
        raise


def _statements(sql):
    statement = ''
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement
            statement = ''
    if statement.strip():
        raise DatabaseError('Incomplete migration SQL')


def validate_schema(con, chain=None):
    chain = tuple(chain if chain is not None else migrations())
    if not chain or [m.version for m in chain] != list(range(1, len(chain)+1)):
        raise DatabaseError('Migration chain must be contiguous from one')
    app = con.execute('PRAGMA application_id').fetchone()[0]
    version = con.execute('PRAGMA user_version').fetchone()[0]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if not tables and app == 0 and version == 0:
        return 0
    if app != APPLICATION_ID or version > len(chain) or 'schema_migrations' not in tables:
        raise DatabaseError('Foreign or newer database schema')
    rows = con.execute('SELECT version,name,sha256 FROM schema_migrations ORDER BY version').fetchall()
    expected = [(m.version, m.name, m.digest) for m in chain[:version]]
    if rows != expected or version < 1:
        raise DatabaseError('Migration ledger/version/checksum mismatch')
    return version


def migrate(con, chain=None):
    """All pending DDL and ledger changes commit together; never executescript."""
    chain = tuple(chain if chain is not None else migrations())
    with transaction(con):
        version = validate_schema(con, chain)
        for migration in chain[version:]:
            for statement in _statements(migration.sql):
                con.execute(statement)
            con.execute('INSERT INTO schema_migrations(version,name,sha256) VALUES(?,?,?)',
                        (migration.version, migration.name, migration.digest))
            con.execute('PRAGMA user_version=' + str(migration.version))
        con.execute('PRAGMA application_id=' + str(APPLICATION_ID))


def record_identity(con, table, *, id, source_id, version, payload, model_id=None):
    """Canonical full-content identities; exact replay only, never merge by tag.

    Reuses existing evidence canonicalization. Payload should retain the entire
    existing sealed identity/config envelope, including unknown observations.
    """
    if table not in ('models', 'runtime_configs'):
        raise ValueError('Identity table not supported')
    encoded = canonical_json_bytes(payload).decode('utf-8')
    digest = sha256(encoded.encode('utf-8')).hexdigest()
    if table == 'models':
        columns = ('id','source_id','version','identity_json','identity_sha256')
        values = (id,source_id,version,encoded,digest)
    else:
        if model_id is None:
            raise ValueError('runtime configuration needs model identity')
        columns = ('id','source_id','model_id','version','config_json','config_sha256')
        values = (id,source_id,model_id,version,encoded,digest)
    existing = con.execute('SELECT ' + ','.join(columns) + ' FROM ' + table + ' WHERE id=?', (id,)).fetchone()
    if existing is not None:
        if existing != values:
            raise DatabaseError('Immutable identity replay differs')
        return digest
    con.execute('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in values)+')',values)
    return digest
