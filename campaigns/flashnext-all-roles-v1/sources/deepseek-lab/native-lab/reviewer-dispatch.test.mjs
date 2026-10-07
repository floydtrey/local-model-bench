import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {WorkerDispatcher,QUALIFIED_WORKER_MODEL} from './worker-dispatch.mjs';
import {ReviewerDispatcher,parseReviewerVerdict} from './reviewer-dispatch.mjs';

const sha=value=>createHash('sha256').update(value).digest('hex');
async function fixture(workerModel=QUALIFIED_WORKER_MODEL,reviewerModel=QUALIFIED_WORKER_MODEL){
 const root=await mkdtemp(join(tmpdir(),'lab-reviewer-')),runsRoot=join(root,'runs'),source=join(root,'submitted'),workspaceRoot=join(root,'workspaces'),workspace=join(workspaceRoot,'job'),testEvidenceRoot=join(root,'test-evidence');
 for(const dir of [runsRoot,source,workspaceRoot,workspace,testEvidenceRoot])await mkdir(dir);
 const intent='Add a title field without changing rendering yet.\n',plan='Task 1: Add title field.\nTask 2: Update rendering.\n',guidance='ALL: preserve existing behavior.\n',file=join(workspace,'config.py');await writeFile(file,'title = None\n');
 await writeFile(join(source,'PROJECT_INTENT.md'),intent);const run=join(runsRoot,'plan');await mkdir(run);await writeFile(join(run,'planner-plan.md'),plan);await writeFile(join(run,'governor-guidance.md'),guidance);await writeFile(join(run,'run.json'),JSON.stringify({run,state:'awaiting-owner-review'}));
 const config={runsRoot,baseRolePatch:join(root,'base.yml'),endpoint:'http://127.0.0.1:11434',wallSecondsPerRole:300,models:{chat:'chat',planner:'planner',governor:'governor'},worker:{model:workerModel},reviewer:{model:reviewerModel}};await writeFile(config.baseRolePatch,'base');
 const workerPatchPath=join(root,'worker.yml'),workerRolePath=join(root,'worker-role.md'),reviewerRolePath=join(root,'reviewer-role.md');await writeFile(workerPatchPath,'worker');await writeFile(workerRolePath,'Worker role');await writeFile(reviewerRolePath,'Reviewer role');
 const item={id:randomUUID(),draft:randomUUID(),revision:1,run,state:'completed',resultState:'awaiting-owner-review',config:JSON.stringify({...config,allowedWorkspace:source,inputHashes:{intent:sha(intent)}})};
 const released={id:randomUUID(),origin:'owner-intent-release',state:'released',itemId:item.id,draft:item.draft,revision:1,intentSha256:sha(intent),configSha256:sha(item.config),workerPatchSha256:sha('worker'),baseRolePatchSha256:sha('base'),rolePromptSha256:sha('Worker role'),workspaceRoot:await realpath(workspaceRoot),workspace:await realpath(workspace),model:workerModel,toolScope:workerModel===QUALIFIED_WORKER_MODEL?'qualified-worker-workspace-write':'worker-workspace-write'};
 const store={item:id=>id===item.id?item:undefined,revision:()=>({sha:sha(intent)}),release:()=>released},workerCalls=[],reviewCalls=[];
 const prepare=async home=>mkdir(home,{recursive:true}),fetchImpl=async url=>({ok:true,json:async()=>url.endsWith('/api/tags')?{models:[{name:workerModel},{name:reviewerModel}]}:{models:[]}});
 const worker=new WorkerDispatcher({store,config,root:join(root,'worker-claims'),workspaceRoot,workerPatchPath,rolePromptPath:workerRolePath,prepare,fetchImpl,turn:async req=>{workerCalls.push(req);if(req.sessionId){await writeFile(file,'title = "Report"\n');return{sessionId:req.sessionId,final:'Handoff note: title added; I ran tests.'};}return{sessionId:'worker-session',final:'WORKER_READY'};}});
 const reviewer=new ReviewerDispatcher({worker,config,root:join(root,'reviews'),rolePromptPath:reviewerRolePath,testEvidenceRoot,prepare,fetchImpl,turn:async req=>{reviewCalls.push(req);return{sessionId:req.sessionId??'reviewer-session',final:req.sessionId?'PASS\nObserved the title field and test result.':'REVIEWER_READY'};}});
 const task={itemId:item.id,taskIndex:1,planStart:0,planEnd:Buffer.byteLength('Task 1: Add title field.\n')};
 const completeWorker=async()=>{await worker.stageTask(task);return worker.dispatch(item.id,1);};
 return{root,item,released,run,workspace,file,testEvidenceRoot,worker,reviewer,workerCalls,reviewCalls,completeWorker,task};
}

test('Reviewer uses released Worker changes and actual captured tests in a separate read-only session',async()=>{
 const f=await fixture();await assert.rejects(f.reviewer.stageReview({itemId:f.item.id,taskIndex:1}),/ENOENT/);await f.completeWorker();
 const stdoutPath=join(f.testEvidenceRoot,'tests.stdout.txt'),stderrPath=join(f.testEvidenceRoot,'tests.stderr.txt');await writeFile(stdoutPath,'2 tests passed\n');await writeFile(stderrPath,'');
 const binding=await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1,testEvidence:[{name:'existing tests',command:'python -m unittest',exitCode:0,stdoutPath,stderrPath}]});
 const packet=await readFile(join(f.reviewer.dir(f.item.id,1),'packet.md'),'utf8');assert.ok(packet.includes('title = "Report"'));assert.ok(packet.includes('2 tests passed'));assert.ok(packet.includes('Worker final response (claim, not independent evidence)'));
 const result=await f.reviewer.dispatch(f.item.id,1);assert.equal(result.state,'reviewed-unverified');assert.equal(result.verdict,'PASS');assert.equal(result.testsSupplied,1);assert.equal(result.releaseId,f.released.id);assert.equal(f.reviewCalls.length,2);assert.equal(f.reviewCalls[0].workerPatch,undefined);assert.equal(f.reviewCalls[1].sessionId,'reviewer-session');assert.notEqual(f.reviewCalls[1].sessionId,'worker-session');assert.equal(binding.packetSha256,sha(packet));
 await assert.rejects(f.reviewer.dispatch(f.item.id,1),/EEXIST/);
});
test('Reviewer can use a distinct installed model pinned before its one-use claim',async()=>{
 const f=await fixture('synthetic-worker:1','synthetic-reviewer:2');await f.completeWorker();
 const binding=await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1}),result=await f.reviewer.dispatch(f.item.id,1);
 assert.equal(binding.model,'synthetic-reviewer:2');assert.equal(result.model,'synthetic-reviewer:2');
 assert.deepEqual(f.reviewCalls.map(c=>c.model),['synthetic-reviewer:2','synthetic-reviewer:2']);
});

test('Reviewer verdict normalization accepts exact markers only',()=>{
 for(const [value,expected] of [['PASS\nReason','PASS'],['**PASS**\nReason','PASS'],['## **FAIL**\nReason','FAIL'],['BLOCKED:\nReason','BLOCKED'],['NOT PASS\nReason','BLOCKED'],['"PASS"\nReason','BLOCKED'],['**PASS** but blocked\nReason','BLOCKED'],['PASSING\nReason','BLOCKED'],['PASS?\nReason','BLOCKED'],['**PASS\nReason','BLOCKED']])assert.equal(parseReviewerVerdict(value.replaceAll('\\n','\n')),expected,value);
});
test('Markdown-bold first-line PASS is recorded as an advisory PASS',async()=>{
 const f=await fixture();await f.completeWorker();f.reviewer.turn=async req=>({sessionId:req.sessionId??'reviewer-session',final:req.sessionId?'**PASS**\nTool and file evidence supports the task.':'REVIEWER_READY'});await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1});const result=await f.reviewer.dispatch(f.item.id,1);assert.equal(result.modelVerdict,'PASS');assert.equal(result.verdict,'PASS');assert.equal(result.state,'reviewed-unverified');
});
test('Worker test claims are labeled as unverified when no actual test capture exists',async()=>{
 const f=await fixture();await f.completeWorker();await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1});const packet=await readFile(join(f.reviewer.dir(f.item.id,1),'packet.md'),'utf8');assert.ok(packet.includes('No independently captured test result'));assert.ok(packet.includes('I ran tests.'));const result=await f.reviewer.dispatch(f.item.id,1);assert.equal(result.testsSupplied,0);assert.equal(result.state,'reviewed-unverified');
});

test('stale release, failed Worker, changed workspace, and out-of-root test capture block Reviewer',async()=>{
 for(const mutation of ['release','failed','workspace','testPath']){const f=await fixture();await f.completeWorker();if(mutation==='release')f.released.id=randomUUID();if(mutation==='failed'){const path=join(f.worker.dir(f.item.id,1),'attempt','run.json'),record=JSON.parse(await readFile(path,'utf8'));record.state='failed';await writeFile(path,JSON.stringify(record));}if(mutation==='workspace')await writeFile(f.file,'title = "Changed again"\n');
  const testEvidence=mutation==='testPath'?[{name:'fake',command:'echo fake',exitCode:0,stdoutPath:f.file,stderrPath:f.file}]:[];await assert.rejects(f.reviewer.stageReview({itemId:f.item.id,taskIndex:1,testEvidence}));assert.equal(f.reviewCalls.length,0);}
});

test('native Worker tool results enter the Reviewer packet and remain bound',async()=>{
 const f=await fixture();const result=await f.completeWorker();const dispatchDir=join(result.run,'dispatch');await mkdir(dispatchDir);const log=join(dispatchDir,'stdout.jsonl');await writeFile(log,'llm-ollama: plugin active; 1 profile(s)\n'+JSON.stringify({type:'tool_result',callId:'read-1',status:'completed',result:'hex=61 6c 70 68 61 0a'})+'\n');
 await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1});const packet=await readFile(join(f.reviewer.dir(f.item.id,1),'packet.md'),'utf8');assert.match(packet,/Native Worker tool capture/);assert.match(packet,/hex=61 6c 70 68 61 0a/);assert.match(packet,/not an independent test/);
 await writeFile(log,JSON.stringify({type:'tool_result',callId:'read-1',status:'completed',result:'changed'})+'\n');await assert.rejects(f.reviewer.dispatch(f.item.id,1),/Reviewer evidence changed/);assert.equal(f.reviewCalls.length,0);
});
test('malformed JSONL event after startup preamble is rejected',async()=>{
 const f=await fixture();const result=await f.completeWorker();const dispatchDir=join(result.run,'dispatch');await mkdir(dispatchDir);await writeFile(join(dispatchDir,'stdout.jsonl'),'llm-ollama: plugin active; 1 profile(s)\n'+JSON.stringify({type:'tool_result',callId:'read-1',status:'completed',result:'ok'})+'\nmalformed event\n');await assert.rejects(f.reviewer.stageReview({itemId:f.item.id,taskIndex:1}),/malformed JSONL event/);assert.equal(f.reviewCalls.length,0);
});
test('concurrent Reviewer dispatch is one use and restart cannot replay it',async()=>{
 const f=await fixture();await f.completeWorker();await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1});let release;const held=new Promise(done=>release=done);f.reviewer.turn=async req=>{f.reviewCalls.push(req);if(!req.sessionId)await held;return{sessionId:req.sessionId??'reviewer-session',final:req.sessionId?'BLOCKED\nMissing evidence.':'REVIEWER_READY'};};
 const a=f.reviewer.dispatch(f.item.id,1),b=f.reviewer.dispatch(f.item.id,1);setTimeout(release,20);const outcomes=await Promise.allSettled([a,b]);assert.equal(outcomes.filter(o=>o.status==='fulfilled').length,1);assert.equal(outcomes.filter(o=>o.status==='rejected').length,1);assert.equal(f.reviewCalls.filter(c=>c.sessionId).length,1);const restarted=new ReviewerDispatcher({...f.reviewer});await assert.rejects(restarted.dispatch(f.item.id,1),/EEXIST/);
});

test('Reviewer stop and inference failure retain the original Worker evidence',async()=>{
 for(const mode of ['stop','failure']){const f=await fixture();await f.completeWorker();await f.reviewer.stageReview({itemId:f.item.id,taskIndex:1});f.reviewer.turn=async req=>{f.reviewCalls.push(req);if(!req.sessionId)return{sessionId:'reviewer-session',final:'REVIEWER_READY'};if(mode==='stop'){await new Promise(done=>req.signal.addEventListener('abort',done,{once:true}));throw Error('Owned Reviewer settled.');}throw Error('Reviewer provider failed.');};const controller=new AbortController(),running=f.reviewer.dispatch(f.item.id,1,controller.signal);if(mode==='stop')setTimeout(()=>controller.abort(),20);const result=await running;assert.equal(result.state,mode==='stop'?'stopped':'failed');const saved=JSON.parse(await readFile(join(result.run,'run.json'),'utf8'));assert.equal(saved.state,result.state);assert.equal(saved.releaseId,f.released.id);assert.equal(await readFile(f.file,'utf8'),'title = "Report"\n');}
});
