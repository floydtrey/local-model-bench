/** Reuse native history for loop detection; no alternate scheduler or log. */

import {runtime} from '../compaction-trial/runtime.mjs';

import {installGovernance} from './native-governance.mjs';
import {ToolProgressGuard} from './tool-progress-guard.mjs';

import {installRepetitionGuard} from './repetition-guard.mjs';

const {createUserMessage,HarnessError,LlmError}=await runtime('dsh-llm');

export const planningTools=new Set(['read','read_image','glob','grep','skill','web_fetch','web_search','ask_user_question','exit_plan_mode',

  'get_goal','list_agents','job_list','job_output','job_kill','interrupt_agent','kc_checkpoint','kc_task_update','kc_evidence',

  'mcp__kc__kc_get_source','mcp__kc__kc_read_excerpt','mcp__kc__kc_recall','mcp__kc__kc_search']);

export function assertPlanningTool(events,name) {

  const active=events.findLast(e=>e.type==='plan/mode')?.data.active===true;

  if(active&&!planningTools.has(name))throw new HarnessError('LAB_PLAN_READ_ONLY: this call did not start because formal plan mode is active. Its purpose is review before implementation. Use inspection and exit_plan_mode; if that route is unavailable, ask the owner in chat to switch mode. Owner agreement on scope is distinct from the mode transition. See ${USERPROFILE}/.dsh/LAB-CONTROLS.md section 6.','LAB_PLAN_READ_ONLY');

}

export function replayProgress(events) {

  const start=events.findLastIndex(e=>e.type==='user/message'&&e.data.source?.kind==='user');

  const calls=new Map(),guard=new ToolProgressGuard();let warning=null,consecutiveErrors=0;
  for(const e of events.slice(start+1)) {

    if(e.type==='tool/call') {try{calls.set(e.data.callId,{name:e.data.name,args:JSON.parse(e.data.arguments)});}catch{}}

    if(e.type==='tool/result') {

      const call=calls.get(e.data.message?.source?.callId);if(!call)continue;

      const blocks=e.data.message.content.map(({toolCallId,...b})=>b);

      consecutiveErrors=blocks.some(b=>b.isError===true)?consecutiveErrors+1:0;

      const feedback=guard.observe(call.name,call.args,blocks);

      if(feedback?.action==='warn')warning=feedback;

    }

  }

  return {guard,warning,consecutiveErrors};
}

export const name='lab-native-progress';

export const inject=['sessions'];

export function apply(ctx) {
  installGovernance(ctx);
  const owned=new Set(),warned=new WeakMap();

  installRepetitionGuard(ctx,id=>owned.has(id),async()=>{});

  const assertProgress=agent=>{

    const state=replayProgress(agent.session.snapshotEvents());

    if(state.consecutiveErrors>=4)throw new LlmError('KC_TOOL_FAILURE_STOP: four consecutive tool errors without a successful tool result. Automatic continuation stopped; review the errors before giving a new instruction.','KC_TOOL_FAILURE_STOP');

    if(state.guard.stopped)throw new LlmError(`KC_TOOL_REPETITION_STOP: ${state.guard.stopped.tool} returned the same result three times. Automatic continuation stopped; review before giving a new instruction.`,'KC_TOOL_REPETITION_STOP');

    return state;

  };

  ctx.on('agent/pre-step',async({agent},next)=>{

    const accepted=await next();if(accepted.kind!=='enter')return accepted;

    owned.add(agent.session.id);

    // A newly admitted human message begins a new attempt; queued input is still owned by Harness.

    if(accepted.messages.some(m=>m.source?.kind==='user'))return accepted;

    const state=assertProgress(agent);

    if(state.warning) {

      const marker=JSON.stringify(state.warning);

      if(warned.get(agent)!==marker) {

        warned.set(agent,marker);

        accepted.messages.push(createUserMessage({source:{kind:'plugin',plugin:name},content:[{type:'text',text:

          `KC_TOOL_REPEAT_WARNING: ${state.warning.tool} returned an unchanged result twice. Use available evidence; a third unchanged repeat stops automatic continuation.`}]}));

      }

    }

    return accepted;

  });

  ctx.on('tools/execute',async(exec,next)=>{

    assertPlanningTool(exec.agent.session.snapshotEvents(),exec.name);

    assertProgress(exec.agent);return next();

  });

}

