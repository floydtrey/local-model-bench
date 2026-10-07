import {readFile,writeFile,mkdir,copyFile,realpath,stat} from 'node:fs/promises';
import {join,relative,sep} from 'node:path';
import {createHash} from 'node:crypto';
import {prepareHome} from './profile.mjs';
import {nativeTurn} from './pipeline.mjs';
import {workspaceSnapshot} from './worker-dispatch.mjs';

const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const save=(path,value,options)=>writeFile(path,JSON.stringify(value,null,2)+'\n',options);
const check=(ok,message)=>{if(!ok)throw Error(message);};
const within=(root,path)=>{const rel=relative(root,path);return rel&&rel!=='..'&&!rel.startsWith('..'+sep);};

export function parseReviewerVerdict(final){const first=String(final).split(/\r?\n/,1)[0];const match=/^\s*(?:#{1,6}\s+)?(?:\*\*(PASS|FAIL|BLOCKED)\*\*|(PASS|FAIL|BLOCKED))\s*:?\s*$/i.exec(first);return(match?.[1]??match?.[2])?.toUpperCase()??'BLOCKED';}

export function reviewerPacket({intent,plan,guidance,task,workerFinal,changes,tests,workspace,execution}){
 const changed=changes.map(c=>`### ${c.path}\nStatus: ${c.status}\nSHA-256: ${c.sha256??'absent'}\n${c.content===undefined?'Content unavailable or not text.':`Current content:\n\`\`\`\n${c.content}\n\`\`\``}`).join('\n\n');
 const checks=tests.length?tests.map(t=>`### ${t.name}\nCommand: ${t.command}\nExit code: ${t.exitCode}\nStdout SHA-256: ${t.stdoutSha256}\nStderr SHA-256: ${t.stderrSha256}\nStdout:\n${t.stdout}\nStderr:\n${t.stderr}`).join('\n\n'):'No independently captured test result was supplied. Worker prose is not test evidence.';
 return `# Reviewer evidence packet\n\n## Original released intent\n${intent}\n\n## Full Planner plan (unchanged)\n${plan}\n\n## Assigned task (exact plan span)\n${task}\n\n## Governor guidance (advisory)\n${guidance}\n\n## Isolated workspace\n${workspace}\n\n## Observed Worker file changes\n${changed||'No file changes observed.'}\n\n## Native Worker tool capture (execution evidence, not an independent test)\n${execution||'No native tool calls or results were captured.'}\n\n## Independently captured existing-test evidence\n${checks}\n\n## Worker final response (claim, not independent evidence)\n${workerFinal}\n`;
}

export class ReviewerDispatcher{
 constructor({worker,config,root,rolePromptPath,testEvidenceRoot=join(root,'test-evidence'),turn=nativeTurn,prepare=prepareHome,fetchImpl=fetch,onEvent=()=>{}}){Object.assign(this,{worker,config,root,rolePromptPath,testEvidenceRoot,turn,prepare,fetchImpl,onEvent});this.active=new Map();}
 dir(itemId,taskIndex){this.worker.dir(itemId,taskIndex);return join(this.root,itemId,'tasks',String(taskIndex).padStart(3,'0'));}
 async evidence(itemId,taskIndex){
  const source=await this.worker.source(itemId),{released,workspace}=await this.worker.release(itemId,source),workerDir=this.worker.dir(itemId,taskIndex);
  const bindingBytes=await readFile(join(workerDir,'binding.json')),binding=JSON.parse(bindingBytes),runBytes=await readFile(join(workerDir,'attempt','run.json')),result=JSON.parse(runBytes);
  check(binding.releaseId===released.id&&result.releaseId===released.id&&binding.itemId===itemId&&binding.taskIndex===taskIndex&&result.taskIndex===taskIndex&&binding.workspace===workspace&&result.workspace===workspace,'Worker evidence is not bound to the released task and workspace.');
  check(result.state==='execution-finished'&&typeof result.handoff==='string','Worker task has not finished; Reviewer cannot infer completion.');
  const current=await workspaceSnapshot(workspace);check(JSON.stringify(current)===JSON.stringify(result.workspaceFilesAfter),'Worker workspace changed after its recorded result.');
  const task=await readFile(join(workerDir,'task.md'),'utf8');check(sha(task)===binding.taskSha256&&source.bytes.plan.subarray(binding.planStart,binding.planEnd).equals(Buffer.from(task)),'Worker task no longer matches the unchanged plan span.');
  return{source,released,workspace,binding,bindingBytes,result,runBytes,task,current};
 }
 async stageReview({itemId,taskIndex,testEvidence=[]}){
  check(Array.isArray(testEvidence)&&testEvidence.length<=20,'Provide at most 20 trusted existing-test results.');const e=await this.evidence(itemId,taskIndex),dir=this.dir(itemId,taskIndex);await mkdir(dir,{recursive:true});
  const changes=[];let evidenceIncomplete=false;for(const path of new Set([...Object.keys(e.result.workspaceFilesBefore),...Object.keys(e.result.workspaceFilesAfter)]).values()){
   const before=e.result.workspaceFilesBefore[path],after=e.result.workspaceFilesAfter[path];if(before===after)continue;
   const status=before===undefined?'created':after===undefined?'deleted':'changed';let content;
   if(after!==undefined){const bytes=await readFile(join(e.workspace,path));check(sha(bytes)===after,'Changed file differs from Worker result.');if(bytes.length<=65536&&Buffer.from(bytes.toString('utf8')).equals(bytes))content=bytes.toString('utf8');else evidenceIncomplete=true;}
   changes.push({path,status,sha256:after,content});
  }
  check(changes.length<=50,'Too many changed files for this bounded Reviewer packet.');
  const tests=[],evidenceRoot=testEvidence.length?await realpath(this.testEvidenceRoot):null;for(const t of testEvidence){check(typeof t.name==='string'&&t.name&&typeof t.command==='string'&&Number.isInteger(t.exitCode),'Invalid trusted test result.');const stdoutPath=await realpath(t.stdoutPath),stderrPath=await realpath(t.stderrPath);check(within(evidenceRoot,stdoutPath)&&within(evidenceRoot,stderrPath)&&(await stat(stdoutPath)).isFile()&&(await stat(stderrPath)).isFile(),'Test capture must be a file under the dedicated evidence root.');const stdout=await readFile(stdoutPath),stderr=await readFile(stderrPath);check(stdout.length<=65536&&stderr.length<=65536,'Test output exceeds Reviewer packet limit.');tests.push({name:t.name,command:t.command,exitCode:t.exitCode,stdout:stdout.toString('utf8'),stderr:stderr.toString('utf8'),stdoutSha256:sha(stdout),stderrSha256:sha(stderr)});}
  const capturePath=join(this.worker.dir(itemId,taskIndex),'attempt','dispatch','stdout.jsonl');let captureBytes;try{captureBytes=await readFile(capturePath);}catch(error){if(error.code!=='ENOENT')throw error;captureBytes=Buffer.alloc(0);}const events=[];let started=false;for(const line of captureBytes.toString('utf8').split(/\r?\n/)){if(!line.trim())continue;if(!started&&line.startsWith('llm-ollama: plugin active;'))continue;started=true;check(line.trim().startsWith('{'),'Worker tool capture has malformed JSONL event.');try{events.push(JSON.parse(line));}catch{throw Error('Worker tool capture has malformed JSONL event.');}}const toolEvents=events.filter(row=>row.type==='tool_call'||row.type==='tool_result').map(row=>JSON.stringify(row)).join('\n');check(Buffer.byteLength(toolEvents)<=65536,'Worker tool capture exceeds 64 KiB.');
  const packet=reviewerPacket({intent:e.source.bytes.intent.toString('utf8'),plan:e.source.bytes.plan.toString('utf8'),guidance:e.source.bytes.guidance.toString('utf8'),task:e.task,workerFinal:e.result.handoff,changes,tests,workspace:e.workspace,execution:toolEvents});check(Buffer.byteLength(packet)<=262144,'Reviewer evidence packet exceeds 256 KiB.');
  const binding={itemId,taskIndex,model:this.config.reviewer.model,releaseId:e.released.id,releaseSha256:sha(JSON.stringify(e.released)),workerBindingSha256:sha(e.bindingBytes),workerResultSha256:sha(e.runBytes),workerToolLogSha256:sha(captureBytes),workspaceFiles:e.current,packetSha256:sha(packet),rolePromptSha256:sha(await readFile(this.rolePromptPath)),evidenceIncomplete,testEvidence:tests.map(({name,command,exitCode,stdoutSha256,stderrSha256})=>({name,command,exitCode,stdoutSha256,stderrSha256})),createdAt:new Date().toISOString(),interpretation:'Reviewer assessment is advisory, not independent task acceptance.'};
  await save(join(dir,'binding.json'),binding,{flag:'wx'});await writeFile(join(dir,'packet.md'),packet,{flag:'wx'});return binding;
 }
 async dispatch(itemId,taskIndex,signal=new AbortController().signal){
  const dir=this.dir(itemId,taskIndex),binding=JSON.parse(await readFile(join(dir,'binding.json'),'utf8')),packet=await readFile(join(dir,'packet.md'),'utf8'),e=await this.evidence(itemId,taskIndex);
  check(binding.itemId===itemId&&binding.taskIndex===taskIndex&&binding.model===this.config.reviewer.model&&binding.releaseId===e.released.id&&binding.releaseSha256===sha(JSON.stringify(e.released)),'Reviewer release or model changed.');
  check(binding.workerBindingSha256===sha(e.bindingBytes)&&binding.workerResultSha256===sha(e.runBytes)&&binding.workerToolLogSha256===sha(await readFile(join(this.worker.dir(itemId,taskIndex),'attempt','dispatch','stdout.jsonl')).catch(error=>{if(error.code!=='ENOENT')throw error;return Buffer.alloc(0)}))&&binding.packetSha256===sha(packet)&&binding.rolePromptSha256===sha(await readFile(this.rolePromptPath))&&JSON.stringify(binding.workspaceFiles)===JSON.stringify(e.current),'Reviewer evidence changed before dispatch.');
  const run=join(dir,'attempt');await mkdir(run,{recursive:false});await save(join(dir,'dispatch-claim.json'),{itemId,taskIndex,releaseId:e.released.id,claimedAt:new Date().toISOString()},{flag:'wx'});
  const record={state:'starting',itemId,taskIndex,releaseId:e.released.id,workerRun:e.result.run,workspace:e.workspace,model:binding.model,run,packetSha256:binding.packetSha256,testsSupplied:binding.testEvidence.length,startedAt:new Date().toISOString(),interpretation:'Reviewer verdict is advisory; no task acceptance or repair authority.'};
  const update=async(state,reason)=>{record.state=state;if(reason)record.reason=reason;await save(join(run,'run.json'),record);};this.active.set(`${itemId}:${taskIndex}`,record);await update('starting');
  try{
   signal.throwIfAborted();const config={...this.config,models:{...this.config.models,reviewer:binding.model}},home=join(run,'dsh-home');await this.prepare(home,config);await copyFile(config.baseRolePatch,join(home,'role.patch.yml'));const role=await readFile(this.rolePromptPath,'utf8');await writeFile(join(run,'reviewer-role.md'),role);await save(join(run,'config-snapshot.json'),config);
   const tagsResponse=await this.fetchImpl(config.endpoint+'/api/tags',{signal:AbortSignal.any([signal,AbortSignal.timeout(5000)])});check(tagsResponse.ok,`Ollama tags HTTP ${tagsResponse.status}`);const tags=await tagsResponse.json();check(tags.models?.some(m=>m.name===binding.model),'Configured Reviewer model is missing; no substitution or pull.');
   const deadline=Date.now()+config.wallSecondsPerRole*1000,remaining=()=>{const seconds=(deadline-Date.now())/1000;check(seconds>0,'Reviewer deadline reached before handoff.');return{...config,wallSecondsPerRole:seconds};};
   await update('role');const assigned=await this.turn({config:remaining(),home,workspace:e.workspace,dir:join(run,'role'),model:binding.model,releaseId:e.released.id,taskIndex,onEvent:event=>this.onEvent({role:'reviewer',phase:'role',taskIndex,event}),prompt:role+'\n\nThis turn establishes your read-only Reviewer role only. Do not inspect files or begin review yet. Reply exactly: REVIEWER_READY\n',signal});check(assigned.final.trim()==='REVIEWER_READY','Reviewer role establishment did not return REVIEWER_READY.');check(assigned.sessionId!==e.result.sessionId,'Reviewer must have a separate native session from Worker.');record.sessionId=assigned.sessionId;
   await update('review');const reviewed=await this.turn({config:remaining(),home,workspace:e.workspace,dir:join(run,'review'),model:binding.model,releaseId:e.released.id,taskIndex,onEvent:event=>this.onEvent({role:'reviewer',phase:'review',taskIndex,event}),prompt:packet,sessionId:assigned.sessionId,signal});record.sessionId=reviewed.sessionId;record.final=reviewed.final;record.modelVerdict=parseReviewerVerdict(reviewed.final);record.verdict=binding.evidenceIncomplete&&record.modelVerdict==='PASS'?'BLOCKED':record.modelVerdict;record.testsSupplied=binding.testEvidence.length;record.completedAt=new Date().toISOString();await update('reviewed-unverified',binding.evidenceIncomplete?'Some changed file content was unavailable; PASS cannot be grounded.':'Reviewer verdict recorded; separate acceptance is not established.');
  }catch(error){await update(signal.aborted?'stopped':'failed',error.message);}finally{record.endedAt=new Date().toISOString();await save(join(run,'run.json'),record);this.active.delete(`${itemId}:${taskIndex}`);}return record;
 }
}
