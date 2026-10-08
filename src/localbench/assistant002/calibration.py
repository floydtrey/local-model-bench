"""Reference and behavioral negative controls, never candidate continuation."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from .packet import packet_root, validate_packet

# Each mutation must trigger the designated ASSERTION, not an unrelated crash.
MUTATIONS = (
 ('bool-duration','scenario.py',"type(value) is not int", "not isinstance(value, int)",'T01','test_reject_bool_duration'),
 ('delay-ignored','schedule.py',"entry['at_ms'] + entry['delay_ms'] + offset", "entry['at_ms'] + offset",'T02','test_duplicates_preserve_event_identity'),
 ('drop-ignored','schedule.py',"if entry['drop']:", 'if False:','T02','test_drop_removes_all_copies'),
 ('alphabetical-ties','schedule.py','ordered.sort(key=lambda row: row[:3])',"ordered.sort(key=lambda row: (row[0], row[3]['delivery_id']))",'T02','test_delivery_order_is_not_event_time_or_key_order'),
 ('duplicate-aliasing','schedule.py',"event=deepcopy(entry['event'])", "event=entry['event']",'T02','test_duplicate_records_and_input_are_independent'),
 ('boundary-deferred','replay.py',"if record['at_ms'] > to_ms:","if record['at_ms'] >= to_ms:",'T03','test_checkpoint_boundary_delivers_before_query'),
 ('clock-shifted','replay.py','timedelta(milliseconds=to_ms)','timedelta(milliseconds=to_ms + 1)','T03','test_checkpoint_boundary_delivers_before_query'),
 ('foreign-checkpoint-accepted','replay.py',"saved['scenario_sha256'] != result._digest",'False','T04','test_checkpoint_changed_scenario_or_expectations_rejected'),
 ('duplicate-observations-hidden','evaluate.py','if len(set(ids)) != len(ids):','if False:','T05','test_duplicate_observed_ids_not_silently_hidden'),
 ('tail-not-delivered','evaluate.py',"if scenario['checkpoints'][-1]['at_ms'] != scenario['duration_ms']:",'if False:','T05','test_reports_all_mismatches_then_drains_later_events'),
 ('unexpected-state-ignored','evaluate.py','passed=not missing and not unexpected','passed=not missing','T05','test_unexpected_only_is_failure'),
 ('checkpoint-counts-ignored','replay.py',"if saved['inserted'] + saved['duplicates'] != cursor:",'if False:','T04','test_checkpoint_invalid_fields_counts_bounds_and_clock'),
)


def install_reference(workspace, repo=None):
    workspace=Path(workspace); root=packet_root(repo)
    shutil.copytree(root/'starter',workspace,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for path in (root/'assessor/reference').glob('*.py'):
        shutil.copyfile(path,workspace/'assistant_simulator'/path.name)
    (workspace/'tests/test_candidate.py').write_text(
        'import unittest\nfrom assistant_simulator import normalize_scenario\n'
        'class CalibrationTest(unittest.TestCase):\n    def test_invalid_input(self):\n'
        '        with self.assertRaises(ValueError): normalize_scenario(None)\n',encoding='utf-8')
    return workspace


def check_workspace(workspace, task, result_path, repo=None, case=None):
    command=[sys.executable,'-I','-B',str(packet_root(repo)/'assessor/checks.py'),
        '--workspace',str(workspace),'--task',task,'--result',str(result_path)]
    if case: command += ['--case',case]
    process=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,timeout=45)
    return process.returncode,json.loads(Path(result_path).read_text(encoding='utf-8'))


def self_test(repo=None):
    validate_packet(repo)
    rows=[]
    with tempfile.TemporaryDirectory(prefix='a002-calibration-') as folder:
        root=Path(folder); reference=install_reference(root/'reference',repo)
        code,result=check_workspace(reference,'T06',root/'reference.json',repo)
        rows.append(dict(name='reference',passed=code==0 and result['passed'],
                         checks_executed=result.get('executed'),
                         failures=[r for r in result.get('checks',[]) if not r['passed']]))
        for name,file,before,after,task,case in MUTATIONS:
            workspace=root/name; shutil.copytree(reference,workspace)
            path=workspace/'assistant_simulator'/file; text=path.read_text(encoding='utf-8')
            if text.count(before)!=1: raise ValueError('Mutation target changed: '+name)
            path.write_text(text.replace(before,after),encoding='utf-8')
            code,result=check_workspace(workspace,task,root/(name+'.json'),repo,case)
            observed=[r for r in result.get('checks',[]) if r['case_id']==case and not r['passed']]
            rows.append(dict(name=name,passed=code==1 and result['status']=='completed' and
                len(observed)==1 and 'AssertionError' in observed[0]['diagnostics'],
                required_failure=case,observed_failures=[r['case_id'] for r in observed]))
        starter=root/'starter';shutil.copytree(packet_root(repo)/'starter',starter)
        code,result=check_workspace(starter,'T01',root/'starter.json',repo)
        rows.append(dict(name='unsolved-starter-rejected',passed=code==1 and not result['passed']))
    return dict(packet_id='assistant-002-v1',passed=all(r['passed'] for r in rows),checks=rows,
                real_models_started=0,production_services_contacted=0)
