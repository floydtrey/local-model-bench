/** Interrupted-effect review using the native tool and command journal only. */

import {runtime} from '../compaction-trial/runtime.mjs';

import {planningTools} from './native-progress-plugin.mjs';
import {installPermissionBoundary,permissionFact} from './native-permission-boundary.mjs';
const {HarnessError,createUserMessage}=await runtime('dsh-llm');

const effectTools=new Set(['write','edit','pwsh','bash','subagent','subagent_fork','workflow','ralph','send_message','mcp__kc__kc_remember','mcp__kc__kc_store_memory']);

function textOf(result) {return (result.data.message?.content??[]).flatMap(b=>b.content??[]).filter(b=>b.type==='text').map(b=>b.text).join('\n');}

function knownPreflightFailure(result,call) {

  if(['INVALID_ARGS','LAB_PLAN_READ_ONLY','LAB_UNCERTAIN_EFFECT','LAB_INTENT_NOT_DURABLE','LAB_PERMISSION_BOUNDARY'].includes(result.data.error?.code))return true;
  const text=textOf(result);
  // dsh-tool-subagent rejects these routes/arguments before spawn dispatch.
  if(['subagent','subagent_fork'].includes(call.data.name)&&/^Error: (?:child LLM route "[^"\r\n]+" is not allowed for this Session|child LLM `provider` and `model` must be supplied together|child model selection is disabled for this tool instance)$/.test(text.trim()))return true;
  if(['edit','write'].includes(call.data.name)&&['FS_NOT_OBSERVED','FS_STALE_VERSION','FS_NOT_REGULAR_FILE'].includes(result.data.error?.code))return true;

  // Installed dsh-fs-local throws these before constructing or writing replacement bytes.

  if(call.data.name==='edit'&&(/^Error: old_string (?:was not found in |must be a non-empty string|and new_string must differ|matched \d+ times in )/.test(text)||['FS_EDIT_NOT_FOUND','FS_AMBIGUOUS_EDIT'].includes(result.data.error?.code)))return true;

  return /^Error: (?:\[sandbox: file access denied under (?:read-only|workspace-write) mode\]|invalid (?:arguments:|escalation:|timeoutMs:|command:|description:)|sandbox escalation to .* is not strictly wider than this call's current .* mode)/.test(text);

}

export function unresolvedEffects(events,{executingStep=null}={}) {

  const calls=new Map(),results=new Map(),commands=new Map(),reviewed=new Set();

  for(const e of events) {

    if(e.type==='tool/call'&&effectTools.has(e.data.name))calls.set(e.data.callId,e);

    if(e.type==='tool/result')results.set(e.data.message?.source?.callId,e);

    if(e.type==='command/run'&&e.data.name==='lab-reconcile')commands.set(e.data.commandId,e);

    if(e.type==='command/done'&&e.data.kind==='success') {

      const command=commands.get(e.data.commandId);

      const id=command?.data.args?.trim().split(/\s+/)[0];

      if(id&&calls.has(id)&&command.seq>calls.get(id).seq)reviewed.add(id);

    }

  }

  const unknown=[];

  for(const [id,call]of calls) {
    if(reviewed.has(id))continue;
    if(events.some(e=>{const f=permissionFact(e);return f?.callId===id&&f.phase==='not-started';}))continue;
    const result=results.get(id);

    if(!result) {

      if(executingStep&&call.data.turn===executingStep.turn&&call.data.step===executingStep.step)continue;

      unknown.push({callId:id,tool:call.data.name,reason:'No durable tool result'});continue;

    }

    const failed=result.data.message.content.some(b=>b.isError===true);

    // A normal nonzero exit is a completed failed operation (e.g. a failing test),

    // not an interrupted operation. Keep failure distinct from unknown execution.

    const interrupted=/\[(?:timed out after|killed by signal:)/.test(textOf(result));

    if((failed&&!knownPreflightFailure(result,call))||interrupted)unknown.push({callId:id,tool:call.data.name,reason:failed?'Tool failed; partial effects not ruled out':'Command interrupted; inspect effects'});

  }

  return unknown;

}

export const name='lab-native-effects';

export const inject=['sessions','commands'];
// Only observational tools qualify. Planning tools also include writes/control actions.
const observationalTools=new Set(['read','read_image','glob','grep','web_search','web_fetch',
  'mcp__kc__kc_get_source','mcp__kc__kc_read_excerpt','mcp__kc__kc_recall','mcp__kc__kc_search']);
export async function inspectUnresolvedEffects(events,{parentId,readSession,executingStep=null}={}) {
  const unknown=unresolvedEffects(events,{executingStep});
  if(!readSession||!parentId)return unknown;
  const retained=[];
  for(const item of unknown) {
    if(item.tool!=='subagent'){retained.push(item);continue;}
    const call=events.find(e=>e.type==='tool/call'&&e.data.callId===item.callId);
    const result=events.find(e=>e.type==='tool/result'&&e.data.message?.source?.callId===item.callId);
    try {
      if(!result)throw new Error('unfinished parent call');
      const args=JSON.parse(call.data.arguments);
      if(args.run_in_background===true)throw new Error('background delegation');
      const catalogs=events.filter(e=>e.type==='subagent/catalog'&&e.seq>call.seq&&e.seq<result.seq);
      if(catalogs.length!==1||catalogs[0].data.mode!=='one-shot'||catalogs[0].data.label!==args.description)throw new Error('ambiguous child');
      // Concurrent delegations cannot be attributed by the catalog interval alone.
      const overlapping=events.filter(e=>e.type==='tool/call'&&['subagent','subagent_fork'].includes(e.data.name)&&e.data.callId!==item.callId).some(e=>{
        const end=events.find(r=>r.type==='tool/result'&&r.data.message?.source?.callId===e.data.callId);
        return e.seq<result.seq&&(!end||end.seq>call.seq);
      });
      if(overlapping)throw new Error('overlapping delegation');
      const child=await readSession(catalogs[0].data.childId);
      if(child.session.id!==catalogs[0].data.childId||child.session.parentSession!==parentId||child.session.origin!=='subagent'||child.inheritedEventCount!==0)throw new Error('unexpected child identity');
      const log=child.events;
      const end=log.findLast(e=>e.type==='turn/end');
      if(!end||!['completed','error'].includes(end.data.reason?.kind)||log.some(e=>e.seq>end.seq&&['turn/start','tool/call'].includes(e.type)))throw new Error('child not settled');
      if(log.some(e=>['subagent/catalog','command/run'].includes(e.type)))throw new Error('child delegated or ran command');
      for(const tool of log.filter(e=>e.type==='tool/call')) {
        if(!observationalTools.has(tool.data.name))throw new Error('potential effect');
        const receipt=log.find(e=>e.type==='tool/result'&&e.data.message?.source?.callId===tool.data.callId);
        if(!receipt||receipt.seq<tool.seq||['TOOL_OUTCOME_UNKNOWN','TOOL_NOT_STARTED'].includes(receipt.data.error?.code))throw new Error('incomplete receipt');
      }
      // A failed observational worker is a known failure, not an unknown mutation.
    } catch {retained.push(item);}
  }
  return retained;
}
export function apply(ctx) {
  installPermissionBoundary(ctx,{HarnessError,createUserMessage});
  const warned=new WeakMap();
  const inspect=(agent,executingStep=null)=>inspectUnresolvedEffects(agent.session.snapshotEvents(),{
    parentId:agent.session.id,executingStep,
    readSession:ctx.get('sessionQuery')?.readSession.bind(ctx.get('sessionQuery'))});
  ctx.effect(()=>ctx.commands.register({name:'lab-reconcile',description:'Record your inspection of an uncertain tool action; does not retry it or grant permissions.',input:{hint:'<call-id> <what you verified>'},

    handler:async invocation=>{

      if(invocation.agent.status==='running')return{kind:'error',text:'Stop and wait for the native session to become idle before recording an inspection.'};

      const [id,...words]=invocation.rawInput.trim().split(/\s+/);

      if(words.join(' ').length<12)return{kind:'error',text:'Provide the exact call ID and a concrete note describing the effects you inspected.'};

      if(!(await inspect(invocation.agent)).some(x=>x.callId===id))return{kind:'error',text:'That call is not an unresolved action in this session.'};
      return{kind:'success',text:`Inspection recorded for ${id}. No action was retried and permissions are unchanged. Resume the native goal explicitly when ready.`};

    }}));

  ctx.on('agent/pre-step',async({agent},next)=>{

    const accepted=await next();if(accepted.kind!=='enter')return accepted;

    const unknown=await inspect(agent);
    if(unknown.length) {

      ctx.get('goals')?.disarm(agent);

      const marker=JSON.stringify(unknown);

      if(warned.get(agent)!==marker){warned.set(agent,marker);accepted.messages.push(createUserMessage({source:{kind:'plugin',plugin:name},content:[{type:'text',text:

        `Uncertain prior effects: ${marker}. Do not retry mutations. Inspect using read-only tools and report evidence. The user can record their inspection with /lab-reconcile <call-id> <what they verified>. This does not authorize broader access.`}]}));}

    }

    return accepted;

  });

  ctx.on('tools/execute',async(exec,next)=>{

    const events=exec.agent.session.snapshotEvents();

    const unknown=await inspect(exec.agent,events.findLast(e=>e.type==='step/start')?.data);
    if(unknown.length&&!planningTools.has(exec.name))throw new HarnessError(`LAB_UNCERTAIN_EFFECT: inspect and reconcile ${unknown.map(x=>x.callId).join(', ')} before another mutation.`,'LAB_UNCERTAIN_EFFECT');

    if(!effectTools.has(exec.name))return next();

    if(await ctx.sessions.flush(exec.agent.session)!==true)throw new HarnessError('Native tool intent could not be persisted; action was not started.','LAB_INTENT_NOT_DURABLE');

    return next();

  });

}

