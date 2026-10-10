"""Consistent SQLite backup API snapshot plus hash-checked external artifacts.

No live restoration, no source modification, no execution of archived content.
Hashes establish integrity, not authenticity of an untrusted backup manifest.
"""
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import stat

from .store import DatabaseError, validate_schema, migrations

BACKUP_VERSION = 'benchmark-database-backup:v1'


def _safe_path(root, relative):
    p = PurePosixPath(relative)
    if not isinstance(relative, str) or not relative or p.is_absolute() or str(p)!=relative or any(x in ('.','..') for x in p.parts) or ':' in relative or '\\' in relative:
        raise DatabaseError('Noncanonical artifact path')
    root = Path(root).resolve()
    result = root.joinpath(*p.parts)
    current = root
    for part in p.parts:
        current = current / part
        attributes = getattr(current.lstat(), 'st_file_attributes', 0) if current.exists() else 0
        if current.is_symlink() or current.is_file() and current != result or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
            raise DatabaseError('Link-like artifact path')
    if not result.resolve().is_relative_to(root):
        raise DatabaseError('Artifact escapes root')
    return result


def _hash(path):
    digest = sha256()
    size = 0
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_verified(source, destination, expected, byte_count):
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256()
    size = 0
    with source.open('rb') as src, destination.open('xb') as dst:
        for chunk in iter(lambda: src.read(1024*1024), b''):
            dst.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    if digest.hexdigest() != expected or size != byte_count:
        raise DatabaseError('Artifact size/hash mismatch during copy')


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)


def _inspect_db(path):
    db = _readonly(path)
    try:
        version = validate_schema(db)
        if version != len(migrations()):
            raise DatabaseError('Backup schema must be fully migrated')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
            raise DatabaseError('SQLite integrity/foreign-key check failed')
        return db.execute("SELECT id,relative_path,sha256,byte_count,integrity FROM artifacts ORDER BY id").fetchall()
    finally:
        db.close()


def _stage(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination, Path(tempfile.mkdtemp(prefix=destination.name+'.pending-', dir=destination.parent))


def _reject_overlap(source, destination):
    """Reject both directions and resolved aliases before staging/mkdir."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise DatabaseError('Source and destination roots overlap')


def _promote(stage, destination):
    # No claim of arbitrary Windows rename metadata durability. Destination is
    # new, callers verify/reconcile after restart; source backup always remains.
    if destination.exists():
        raise FileExistsError(destination)
    os.rename(stage, destination)


def backup(con, artifact_root, destination):
    """Snapshot committed DB with backup API, then copy its immutable artifacts.

    Caller must not have an open transaction. Missing/unverifiable historical
    references stay explicitly unavailable; they cannot become verified evidence.
    """
    if con.in_transaction:
        raise DatabaseError('Backup requires committed transaction boundary')
    _reject_overlap(artifact_root, destination)
    destination, stage = _stage(destination)
    try:
        dbpath = stage / 'database.sqlite3'
        target = sqlite3.connect(dbpath)
        try:
            con.backup(target)
            target.execute('PRAGMA journal_mode=DELETE')
            target.commit()
        finally:
            target.close()
        with dbpath.open('rb+') as stream:
            os.fsync(stream.fileno())
        artifacts = _inspect_db(dbpath)
        entries = [{'path':'database.sqlite3','sha256':_hash(dbpath)[0],'bytes':dbpath.stat().st_size}]
        unavailable = []
        for id, path, digest, size, integrity in artifacts:
            if integrity != 'verified':
                unavailable.append({'id':id,'integrity':integrity})
                continue
            source = _safe_path(artifact_root,path)
            output = _safe_path(stage, 'artifacts/'+path)
            _copy_verified(source, output, digest, size)
            entries.append({'path':'artifacts/'+path,'sha256':digest,'bytes':size})
        manifest = {'version':BACKUP_VERSION,'schema_version':len(migrations()),'files':entries,'unavailable_artifacts':unavailable}
        with (stage/'manifest.json').open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(manifest,stream,sort_keys=True,indent=2,allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        verify_backup(stage)
        _promote(stage,destination)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify_backup(directory):
    directory = Path(directory).resolve()
    manifest_path = _safe_path(directory, 'manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('version')!=BACKUP_VERSION or manifest.get('schema_version')!=len(migrations()):
        raise DatabaseError('Unsupported backup/schema version')
    entries = manifest.get('files')
    if not isinstance(entries,list):
        raise DatabaseError('Invalid backup manifest')
    paths = [x['path'] for x in entries]
    if len(paths)!=len(set(paths)) or 'database.sqlite3' not in paths:
        raise DatabaseError('Duplicate or absent database backup entry')
    for entry in entries:
        if _hash(_safe_path(directory,entry['path']))!=(entry['sha256'],entry['bytes']):
            raise DatabaseError('Backup file integrity mismatch')
    artifacts = _inspect_db(_safe_path(directory,'database.sqlite3'))
    expected = {'database.sqlite3':next(x for x in entries if x['path']=='database.sqlite3')}
    unavailable = []
    for id,path,digest,size,integrity in artifacts:
        if integrity=='verified':
            expected['artifacts/'+path]={'path':'artifacts/'+path,'sha256':digest,'bytes':size}
        else:
            unavailable.append({'id':id,'integrity':integrity})
    if sorted(entries,key=lambda x:x['path'])!=sorted(expected.values(),key=lambda x:x['path']) or manifest.get('unavailable_artifacts')!=unavailable:
        raise DatabaseError('Artifact registry/manifest mismatch')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != set(paths)|{'manifest.json'}:
        raise DatabaseError('Unexpected or missing backup files')
    return manifest


def restore(directory, destination):
    """Restore into a NEW root: database.sqlite3 plus artifacts/. Never live."""
    _reject_overlap(directory, destination)
    manifest = verify_backup(directory)
    destination, stage = _stage(destination)
    try:
        for entry in manifest['files']:
            _copy_verified(_safe_path(directory,entry['path']),_safe_path(stage,entry['path']),entry['sha256'],entry['bytes'])
        # Copy and revalidate manifest so a source mutation during copy fails closed.
        data = _safe_path(directory,'manifest.json').read_bytes()
        with (stage/'manifest.json').open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        verify_backup(stage)
        _promote(stage,destination)
        return destination
    finally:
        if stage.exists():
            shutil.rmtree(stage)
