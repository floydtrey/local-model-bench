/** Lab-specific documentation through native assembly/result hooks. No permissions or state store. */
import {permissionBoundary,inspectionTools} from './native-permission-boundary.mjs';
export const POLICY='${USERPROFILE}/.dsh/AGENTS.md';
export const CONTROLS='${USERPROFILE}/.dsh/LAB-CONTROLS.md';
const packages='${USERPROFILE}/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/';
const escalation='After a real native denial, an exact-operation escalation is available only if no Lab permission/uncertain-effect stop is active and the owner has not rejected that action. Follow '+CONTROLS+' section 3. A native approval grants access only to that call; it does not clear a Lab guard. Omit sandbox_permissions and justification for ordinary calls.';
export const pwshDescription='Execute the supplied PowerShell script in a fresh pwsh process. Pass the script itself, for example Get-Location; do not add pwsh -Command merely to invoke this tool. Use workdir for the working directory; process state does not persist between calls. Use native Windows paths and $env:NAME for environment variables. Nonzero exits report a command/test failure; a sandbox denial is reported separately. An interrupted command may have partial effects. Long output is truncated to its tail, with the full output file path returned when available. Background launching is disabled in this Lab preset; a supplied timeout must be positive. In read-only sandbox mode PowerShell can use ConstrainedLanguage, which restricts .NET/COM operations. Confined processes can also encounter named-pipe restrictions; diagnose the actual result rather than inferring that every EPERM is a permission rejection. A structured shell sandbox denial activates the Lab permission boundary: inspect permitted evidence and ask the owner in ordinary chat for the review described in '+CONTROLS+' section 3. '+escalation;
export function rewriteAssembly(assembly){
 const result=structuredClone(assembly);
 result.sections=result.sections.map(section=>{
  if(section.name==='harness:source')return {...section,text:'Installed Harness distribution: ${USERPROFILE}/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/. Package documentation and implementation are under '+packages+'. This is not a guaranteed development checkout. The current workspace comes from runtime context, not this install path.'};
  if(section.name==='app:web-surface')return {...section,text:'The current application is the existing DeepSeek Harness Web GUI. Its local URL is provided by runtime $env:DSH_WEB_URL; the owner may access it through the configured remote address. No browser DOM or screenshot is implicitly available. Inspect installed packaging and supported extension/reload mechanisms before changing this application; a separate server does not update the existing GUI.'};
  if(section.name==='tool:read')return {...section,text:'Use native read for ordinary text inspection. Its line numbers and framing are presentation, not file bytes. Use offset/limit to read further. For byte-exact operations or facts the tool cannot expose, use an authorized appropriate tool; native read is a workflow preference, not a prohibition on authorized shell inspection.'};
  if(section.name==='tool:goal')return {...section,text:section.text+' The minimum-round check governs when the blocked status update is accepted; it does not require repeating an invalid action, hiding a blocker, or inventing work. Report the blocker when discovered. A user request to resume does not clear permission or uncertain-effect guards; resolve those states through their documented mechanism before effectful continuation.'};
  return section;
 });
 result.tools=result.tools.map(tool=>{
  if(tool.name==='pwsh')tool.description=pwshDescription;
  if(tool.parameters?.properties?.sandbox_permissions){
   tool.parameters.properties.sandbox_permissions.description='One-shot wider mode for the same genuinely denied operation, subject to native approval and current Lab guards. '+escalation;
  }
  if(tool.name==='ask_user_question')tool.description+=' If the Lab permission boundary blocks this tool or the answerer is unavailable, explain the decision needed in ordinary chat. A response clarifies user intent; it does not itself change sandbox permissions or guard state.';
  if(tool.name==='list_subagent_models')tool.description+=' A provider such as ollama is not a model. Use the provider parameter to list that provider’s model IDs when the first result lists providers only; do not infer that unlisted models are unavailable until the catalog is queried at the appropriate level.';
  if(tool.name==='kc_checkpoint')tool.description='Takes no arguments. Save and read back native session evidence in the existing KC integration. Returns a verified checkpoint reference; does not prove functional success, approve work or build the graph.';
  return tool;
 });
 return result;
}
function boundaries(ctx,session){
 const seen=new Set();
 while(session?.header?.parentSession){if(seen.has(session.id))return null;seen.add(session.id);session=ctx.sessions.get(session.header.parentSession);}
 return session?permissionBoundary(session.snapshotEvents()):null;
}
export function guidanceFor(exec,result,pending){
 if(result.value?.sandbox?.denied===true || pending?.length){
  const keys=pending?.map(f=>f.key).join(', ');
  return 'Lab permission review is required'+(keys?' for '+keys:'')+'. '+(result.value?.sandbox?.denied===true?'This command reached execution; its partial effects remain to be inspected. ':'Use the recorded outcome to distinguish a pre-execution refusal from partial execution. ')+
   'Intent: respect the owner’s access decision and avoid repeating unknown effects. Currently permitted inspection/stop tools: '+[...inspectionTools].join(', ')+'. Ask the owner in ordinary chat; ask_user_question is currently blocked by this boundary. The owner can review in the idle root session with /lab-permission-review <session-id:call-id> <effects inspected and authorized next action>. Review does not grant broader native access or run a retry. See '+CONTROLS+' section 3.';
 }
 if(result.error?.code==='FS_NOT_FOUND')return 'The requested path was not found; this result is not a permission denial. Use the absolute source path from the instruction frame or '+POLICY+' section 1, then inspect relevant locations with read/glob/grep.';
 if(result.error?.code==='INVALID_ARGS')return 'This call was rejected before dispatch because its arguments did not match the tool contract. Correct those arguments using the current schema. No effects occurred from this rejected call; other outstanding guard state is unchanged.';
 if(result.error?.code==='LAB_UNCERTAIN_EFFECT')return 'The unresolved issue is the previous operation’s effects, not proof the task is unauthorized. Inspect permitted evidence and ask for the owner’s /lab-reconcile review described in '+CONTROLS+' section 4; permission review is separate.';
 return null;
}
export function installGovernance(ctx){
 ctx.on('system-prompt/assemble',async(_assembly,_context,next)=>rewriteAssembly(await next()));
 ctx.on('tools/post-execute',async(exec,result,next)=>{
  const decision=await next();if(decision.kind!=='accept'||Object.hasOwn(decision,'value'))return decision;
  const pending=exec.agent?boundaries(ctx,exec.agent.session):[];
  const feedback=guidanceFor(exec,result,pending);if(!feedback)return decision;
  const original=decision.content??result.content??[];
  const content=original.map(block=>{
   if(block.type!=='text'||!(pending?.length||result.value?.sandbox?.denied===true))return block;
   // Remove only the contradictory native guidance line; preserve the denial marker and actual error/output.
   return {...block,text:block.text.split('\n').filter(line=>!/^\[sandbox: escalation available — retry this exact (?:command|operation) once with sandbox_permissions .*\]$/.test(line)).join('\n')};
  });
  return {...decision,content:[...content,{type:'text',text:feedback}]};
 });
}
