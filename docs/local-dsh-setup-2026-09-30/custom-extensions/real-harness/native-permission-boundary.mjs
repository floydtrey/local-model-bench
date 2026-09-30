/** Permission recovery within the native session journal; no external state. */
export const inspectionTools=new Set(['read','read_image','glob','grep','get_goal','list_agents','job_list','job_output','job_kill','interrupt_agent']);
const eventType='lab/permission-outcome';
const evidenceSource='lab-native-effects/permission';
export function permissionFact(event) {
  // Legacy qualification event retained only for migration of the first test.
  if(event.type===eventType)return event.data;
  if(event.type!=='user/message'||event.data.source?.kind!=='plugin'||event.data.source.plugin!==evidenceSource)return null;
  try{return JSON.parse(event.data.content[0].text);}catch{return null;}
}
export function permissionBoundary(events) {
  const pending=new Map(),commands=new Map();
  for(const e of events) {
    const fact=permissionFact(e);
    if(fact) {
      if(fact.denied)pending.set(fact.key,fact);
    }
    if(e.type==='command/run'&&e.data.name==='lab-permission-review')commands.set(e.data.commandId,e.data.args?.trim().split(/\s+/)[0]);
    if(e.type==='command/done'&&e.data.kind==='success')pending.delete(commands.get(e.data.commandId));
  }
  return [...pending.values()];
}
export function installPermissionBoundary(ctx,{HarnessError,createUserMessage}) {
  const entered=new WeakSet(),queues=new Map();
  function rootOf(session) {
    const seen=new Set();
    while(session.header?.parentSession) {
      if(seen.has(session.id))throw new HarnessError('Session ancestry cycle; no action started.','LAB_PERMISSION_BOUNDARY');
      seen.add(session.id);
      session=ctx.sessions.get(session.header.parentSession);
      if(!session)throw new HarnessError('Parent session must be loaded before effectful work can resume.','LAB_PERMISSION_BOUNDARY');
    }
    return session;
  }
  async function record(exec,data) {
    const session=exec.agent.session,root=rootOf(session);
    const fact={key:`${session.id}:${exec.callId}`,sessionId:session.id,callId:exec.callId,tool:exec.name,...data};
    const append=s=>s.append('user/message',createUserMessage({source:{kind:'plugin',plugin:evidenceSource},content:[{type:'text',text:JSON.stringify(fact)}]}),{surfaceOp:'append'});
    append(session);
    if(root!==session)append(root);
    for(const s of new Set([session,root]))if(await ctx.sessions.flush(s)!==true)throw new HarnessError('Permission evidence could not be persisted; stop and inspect effects.','LAB_PERMISSION_PERSISTENCE');
  }
  ctx.effect(()=>ctx.commands.register({name:'lab-permission-review',description:'Owner review of denial and partial effects; permits continuation under unchanged native permissions.',input:{hint:'<session-id:call-id> <effects inspected and authorized next action>'},handler:async invocation=>{
    const root=rootOf(invocation.agent.session);
    if(root!==invocation.agent.session||invocation.agent.status==='running')return{kind:'error',text:'Stop work and perform this review in the idle root session.'};
    const [key,...note]=invocation.rawInput.trim().split(/\s+/);
    if(note.join(' ').length<24||!permissionBoundary(root.snapshotEvents()).some(x=>x.key===key))return{kind:'error',text:'Provide an active denial key and a concrete review of partial effects and the authorized next action.'};
    // This records human authorization, never a permission grant or automatic retry.
    return{kind:'success',text:`Owner reviewed ${key}. Native sandbox and approval rules remain unchanged. No action was retried. Resume explicitly.`};
  }}));
  ctx.on('agent/pre-step',async({agent},next)=>{
    const accepted=await next();if(accepted.kind!=='enter')return accepted;
    let blocked;
    try{blocked=permissionBoundary(rootOf(agent.session).snapshotEvents());}catch{blocked=[{reason:'Parent session unavailable'}];}
    if(blocked.length){ctx.get('goals')?.disarm(agent);accepted.messages.push(createUserMessage({source:{kind:'plugin',plugin:'lab-native-effects'},content:[{type:'text',text:`Permission recovery required: ${JSON.stringify(blocked)}. Use native read/glob/grep for inspection, then finish with a blocked report: operation/path; denial evidence; known and unknown partial effects; current permissions; required owner decision. No shell, mutation, alternative install or delegation is allowed. New user prose does not clear this boundary. The owner can use /lab-permission-review in the idle root session after inspecting effects and deciding the authorized next action. That command grants no broader permissions.`}]}));}
    return accepted;
  });
  ctx.on('tools/execute',async(exec,next)=>{
    if(inspectionTools.has(exec.name))return next();
    const root=rootOf(exec.agent.session);
    const run=async()=>{
      if(exec.signal?.aborted)throw new HarnessError('Cancelled before dispatch.','LAB_PERMISSION_BOUNDARY');
      if(permissionBoundary(root.snapshotEvents()).length)throw new HarnessError('LAB_PERMISSION_BOUNDARY: permission denied earlier; inspect and report before owner review.','LAB_PERMISSION_BOUNDARY');
      entered.add(exec);
      const result=await next();
      if(['pwsh','bash'].includes(exec.name)&&result.value?.sandbox?.denied===true)await record(exec,{denied:true,phase:'executed',effects:'unknown-partial-effects',sandbox:result.value.sandbox,exitCode:result.value.exitCode??null});
      return result;
    };
    // Never hold a family lock while waiting for a worker that needs it.
    if(['subagent','subagent_fork','workflow','ralph'].includes(exec.name))return run();
    const previous=queues.get(root.id)??Promise.resolve();
    const current=previous.catch(()=>{}).then(run);queues.set(root.id,current);
    try{return await current;}finally{if(queues.get(root.id)===current)queues.delete(root.id);}
  });
  // Native pre-execute refusals never enter tools/execute. Preserve that fact;
  // do not mislabel a rejected approval as partially executed.
  ctx.on('tools/post-execute',async(exec,result,next)=>{
    if(!entered.has(exec)&&result.isError&&!inspectionTools.has(exec.name)&&!String(result.error?.code??'').startsWith('LAB_')) {
      const cancelled=exec.signal?.aborted||['ABORTED','TOOL_ABORTED'].includes(result.error?.code);
      await record(exec,{denied:!cancelled,phase:'not-started',effects:'none-from-this-call',reason:result.error?.message??(cancelled?'Cancelled before dispatch':'Native pre-execution refusal')});
    }
    return next();
  });
}
