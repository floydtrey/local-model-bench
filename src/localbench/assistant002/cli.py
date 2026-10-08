"""ASSISTANT-002 entrypoint; delegates model execution and review to existing code."""
from __future__ import annotations
import argparse
from functools import partial
import json
import math
from pathlib import Path
import shutil
import sys
from uuid import uuid4
from localbench.assistant001.assessment import assess
from localbench.assistant001.campaign import run_probe, run_worker_chain
from . import packet as api
from .packet import digest, prepare, read_run, repository_root, snapshot, validate_packet, write_json


def parser():
    result=argparse.ArgumentParser(description='ASSISTANT-002: deterministic event simulation and replay benchmark')
    result.add_argument('action',nargs='?',default='validate',choices=('validate','prepare','self-test','assess','run','probe','interop'))
    result.add_argument('--repo-root',type=Path,default=repository_root())
    for name in ('output-root','run-dir','input-run','journal-run','governor-root','plan-file'):
        result.add_argument('--'+name,type=Path)
    result.add_argument('--model')
    result.add_argument('--role',choices=('planner','governor','tester','reviewer'))
    result.add_argument('--through',choices=[f'T0{i}' for i in range(1,7)],default='T01')
    result.add_argument('--task',choices=[f'T0{i}' for i in range(1,7)],default='T06')
    result.add_argument('--phase',choices=('screen','qualification'),default='screen')
    result.add_argument('--context-tokens',type=int,default=32768)
    result.add_argument('--max-output-tokens',type=int,default=8192)
    result.add_argument('--timeout-seconds',type=float,default=600)
    result.add_argument('--keep-alive-seconds',type=float,default=3600)
    result.add_argument('--allow-host-execution',action='store_true',help='Acknowledge candidate Python is not OS-sandboxed')
    return result


def interop(run, journal_run, *, repo, allow_host_execution=False):
    if not allow_host_execution:
        raise ValueError('interop requires --allow-host-execution')
    from localbench.assistant001.packet import read_run as read_journal_run
    read_run(run,repo); read_journal_run(journal_run,repo)
    run, journal_run=Path(run).resolve(),Path(journal_run).resolve()
    original=snapshot(journal_run/'workspace')
    dependency=run/'pair-inputs'/uuid4().hex
    shutil.copytree(journal_run/'workspace',dependency,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    result,evidence=assess(run,'T06',repo=repo,allow_host_execution=True,packet_api=api,
                          assessor_args=('--journal-workspace',str(dependency)))
    copy_unchanged=snapshot(dependency)==original
    source_unchanged=snapshot(journal_run/'workspace')==original
    if not (copy_unchanged and source_unchanged):
        result.update(passed=False,status='journal_changed_during_interop')
    result['pair']=dict(journal_run=str(journal_run),journal_source_sha256=original,
                       tested_copy=str(dependency),copy_unchanged=copy_unchanged,
                       source_unchanged=source_unchanged,
                       interpretation='joint candidate result; not standalone model qualification')
    write_json(evidence/'assessment.json',result)
    return result,evidence


def main(argv=None, *, sessions_factory=None, export=None):
    args=parser().parse_args(argv)
    try:
        packet,packet_hash=validate_packet(args.repo_root)
        if args.action=='validate':
            print(json.dumps(dict(packet=packet['packet_id'],packet_sha256=packet_hash,
                tasks=len(packet['tasks']),acceptance_checks=len(api.expected_check_ids('T06',args.repo_root)),
                status='integrity-verified',model_calls=0,candidate_code_executed=False),indent=2))
            return 0
        if args.action=='prepare':
            run=prepare(args.output_root,repo=args.repo_root)
            print(f'WORKSPACE={run / "workspace"}\nRUN_DIR={run}',flush=True)
            return 0
        if args.action=='self-test':
            from .calibration import self_test
            result=self_test(args.repo_root); print(json.dumps(result,indent=2))
            return 0 if result['passed'] else 1
        if args.action in ('assess','interop'):
            if args.run_dir is None: raise ValueError('Provide --run-dir')
            if args.action=='interop':
                if args.journal_run is None: raise ValueError('interop requires --journal-run')
                result,evidence=interop(args.run_dir,args.journal_run,repo=args.repo_root,
                                        allow_host_execution=args.allow_host_execution)
            else:
                result,evidence=assess(args.run_dir,args.task,repo=args.repo_root,
                    allow_host_execution=args.allow_host_execution,packet_api=api)
            print(f'ASSESSMENT_DIR={evidence}\nRUN_DIR={args.run_dir.resolve()}',flush=True)
            print(json.dumps({k:result.get(k) for k in ('passed','status','planned','executed')},indent=2))
            return 0 if result['passed'] else 1
        if not args.model or args.model.startswith('-'):
            raise ValueError('Provide an installed --model tag')
        if args.context_tokens<1 or args.max_output_tokens<1 or not math.isfinite(args.timeout_seconds) or args.timeout_seconds<=0 or not math.isfinite(args.keep_alive_seconds):
            raise ValueError('Invalid token/time settings')
        if (args.action=='run' or args.role=='tester') and not args.allow_host_execution:
            raise ValueError('Candidate Python execution requires --allow-host-execution')
        if args.action=='probe':
            if args.role is None or args.input_run is None: raise ValueError('probe requires --role and --input-run')
            if args.phase!='screen': raise ValueError('Role probes are advisory single trials')
            read_run(args.input_run,args.repo_root)
            if args.role=='governor' and (args.governor_root is None or args.plan_file is None):
                raise ValueError('Governor needs canonical --governor-root and actual --plan-file')
        if sessions_factory is None:
            from localbench.assistant001.runtime import OllamaSessions
            sessions_factory=OllamaSessions
        if export is None:
            from localbench.assistant001.cli import review_package
            export=review_package
        run=prepare(args.output_root,repo=args.repo_root,label=args.action)
        print(f'RUN_DIR={run}',flush=True)
        write_json(run/'runner-inputs.json',dict(model=args.model,phase=args.phase,through=args.through,
            role=args.role,context_tokens=args.context_tokens,max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,keep_alive_seconds=args.keep_alive_seconds,
            host_execution_acknowledged=args.allow_host_execution,runner_sha256=snapshot(Path(__file__).parent),
            shared_engine_sha256={name:digest(Path(__file__).parents[1]/'assistant001'/name)
                                  for name in ('assessment.py','campaign.py','runtime.py')},
            repetition_note='temperature 0 / seed 42; repeated rollouts, not independent statistical samples'))
        sessions=sessions_factory(args.repo_root,run,args.model,context_tokens=args.context_tokens,
            max_output_tokens=args.max_output_tokens,timeout_seconds=args.timeout_seconds,
            keep_alive_seconds=args.keep_alive_seconds)
        if args.action=='probe':
            summary=run_probe(run,args.input_run,sessions,role=args.role,repo=args.repo_root,
                governor_root=args.governor_root,plan_file=args.plan_file,
                allow_host_execution=args.allow_host_execution,packet_api=api)
            row=summary['results'][0]
            passed=row['status']=='success' and row['scope']['passed'] and row['source_unchanged']
        else:
            results=[]
            repetitions=1 if args.phase=='screen' else 3
            for ordinal in range(1,repetitions+1):
                trial=run if ordinal==1 else prepare(run/'repetitions',repo=args.repo_root,label=f'r{ordinal}')
                results.append(run_worker_chain(trial,sessions,through=args.through,repo=args.repo_root,
                    ordinal=ordinal,allow_host_execution=True,packet_api=api,
                    assessor=partial(assess,packet_api=api)))
                write_json(run/'repetition-progress.json',dict(finished=ordinal,planned=repetitions))
            passed=all(r['passed'] for r in results)
            summary=dict(campaign='assistant-002-v1',track='fixed-plan-worker-chain',phase=args.phase,
                repetitions=repetitions,results=[row for result in results for row in result['results']],
                planned_cases=sum(r['planned_cases'] for r in results),
                completed_cases=sum(r['completed_cases'] for r in results),passed=passed,
                qualification_status='human-review-pending',os_sandbox=False)
        write_json(run/'summary.json',summary)
        export(run,summary,args.model,args.phase,args.context_tokens)
        print(f'RUN_DIR={run}',flush=True)
        return 0 if passed else 1
    except (ValueError,OSError,RuntimeError) as exc:
        print(f'BLOCKED: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
