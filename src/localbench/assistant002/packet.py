"""ASSISTANT-002 packet adapter for the existing project benchmark engine."""
from __future__ import annotations
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4
from localbench.assistant001.packet import digest, repository_root, scope_diff, snapshot, write_json

PACKET_ID = 'assistant-002-v1'
DOCS = ('PROJECT_INTENT.md', 'CONTRACT.md', 'TASKS.md')


def packet_root(repo=None):
    return Path(repo or repository_root()) / 'project-benchmarks/assistant-002/v1'


def validate_packet(repo=None):
    root=packet_root(repo)
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    actual=snapshot(root); actual.pop('manifest.json',None)
    if manifest.get('packet_id')!=PACKET_ID or actual!=manifest.get('files'):
        raise ValueError('ASSISTANT-002 packet integrity mismatch')
    for relative, expected in manifest.get('dependencies',{}).items():
        if digest(Path(repo or repository_root())/relative)!=expected:
            raise ValueError('Pinned journal calibration dependency changed: '+relative)
    packet=json.loads((root/'packet.json').read_text(encoding='utf-8'))
    if [t['id'] for t in packet['tasks']]!=[f'T0{i}' for i in range(1,7)]:
        raise ValueError('Invalid fixed task sequence')
    return packet,digest(root/'manifest.json')


def expected_check_ids(task, repo=None):
    """Load trusted test metadata before executing any candidate Python."""
    if task not in [f'T0{i}' for i in range(1,7)]:
        raise ValueError('Unknown task')
    source=packet_root(repo)/'assessor/checks.py'
    spec=importlib.util.spec_from_file_location('assistant002_check_inventory',source)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return sorted(name for name in dir(module.Acceptance) if name.startswith('test_')
                  and getattr(module.Acceptance,name).stage<=int(task[-1]))


def prepare(output_root=None, *, repo=None, label='candidate'):
    repo=Path(repo or repository_root()).resolve()
    packet, packet_hash=validate_packet(repo)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}',label):
        raise ValueError('Invalid run label')
    output=Path(output_root or repo/'local-state/assistant-002').resolve()
    frozen=repo/'project-benchmarks'
    if output==frozen or frozen in output.parents:
        raise ValueError('Output must be outside frozen benchmark packets')
    output.mkdir(parents=True,exist_ok=True)
    run=output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+label+'-'+uuid4().hex[:8])
    run.mkdir(exist_ok=False)
    shutil.copytree(packet_root(repo)/'starter',run/'workspace',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for doc in DOCS:
        shutil.copyfile(packet_root(repo)/doc,run/'workspace'/doc)
    write_json(run/'run.json',dict(packet_id=PACKET_ID,packet_sha256=packet_hash,
        created_at=datetime.now(timezone.utc).isoformat(),candidate_initial_sha256=snapshot(run/'workspace'),
        qualification_status='human-review-pending',os_sandbox=False))
    return run


def read_run(run, repo=None):
    run=Path(run).resolve(); packet, packet_hash=validate_packet(repo)
    record=json.loads((run/'run.json').read_text(encoding='utf-8'))
    if record.get('packet_id')!=PACKET_ID or record.get('packet_sha256')!=packet_hash:
        raise ValueError('Run does not match this frozen Assistant-002 packet')
    workspace=run/'workspace'
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError('Missing or invalid candidate workspace')
    snapshot(workspace)
    return record,packet


def task_prompt(run, task, previous_handoff, repo=None):
    packet,_=validate_packet(repo)
    spec=next((t for t in packet['tasks'] if t['id']==task),None)
    if spec is None: raise ValueError('Unknown task')
    text=(packet_root(repo)/'TASKS.md').read_text(encoding='utf-8')
    span=text.split(f'## {task}:',1)[1].split('\n## T',1)[0]
    return (f'# {PACKET_ID} / {task}\n\n## {task}:'+span+'\n'+
        '\n'.join((packet_root(repo)/doc).read_text(encoding='utf-8') for doc in DOCS[:2])+
        '\n## Actual predecessor handoff\n'+(previous_handoff or 'First task; no predecessor.')+
        '\n## Isolated candidate workspace\n'+str(Path(run)/'workspace')+
        '\nRead existing files first. Use only the exposed bounded file tools and run_tests. '
        'run_tests takes no arguments and runs the visible unittest suite. '
        'Only these paths may change: '+', '.join(spec['writable_paths'])+
        '. Keep a useful free-prose handoff with actual tests, limitations and next-task guidance. '
        'The event_contract helper is supplied and protected. Do not implement Journal.\n')
