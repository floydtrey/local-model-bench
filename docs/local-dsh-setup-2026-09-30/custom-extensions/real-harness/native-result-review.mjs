/** Human-only file review receipts in the existing native command journal. */
import {open,realpath} from 'node:fs/promises';
import {resolve,relative,isAbsolute} from 'node:path';
import {createHash} from 'node:crypto';
import {unresolvedEffects} from './native-effect-guard.mjs';

export async function fingerprint(cwd,input) {
  if(!cwd||!input||isAbsolute(input)||input.includes(':'))throw Error('Use a workspace-relative file path.');
  const root=await realpath(cwd),path=await realpath(resolve(root,input));
  const rel=relative(root,path);
  if(!rel||rel==='..'||rel.startsWith('..\\')||rel.startsWith('../')||isAbsolute(rel))throw Error('File must stay inside this workspace.');
  const handle=await open(path,'r');
  try {
    const before=await handle.stat();
    if(!before.isFile()||before.size>64*1024*1024)throw Error('Review requires a regular file of at most 64 MiB.');
    const digest=createHash('sha256');let bytes=0;
    for await(const chunk of handle.createReadStream({autoClose:false})) {
      bytes+=chunk.length;if(bytes>64*1024*1024)throw Error('File grew beyond the review limit.');digest.update(chunk);
    }
    const after=await handle.stat();
    if(before.size!==after.size||before.mtimeMs!==after.mtimeMs||before.ctimeMs!==after.ctimeMs||bytes!==after.size)throw Error('File changed during review; inspect it again.');
    return {path:rel.replaceAll('\\','/'),bytes,sha256:digest.digest('hex')};
  } finally {await handle.close();}
}
export function reviewed(events,file) {
  return events.some(e=>{
    if(e.type!=='command/done'||e.data.kind!=='success')return false;
    const call=events.find(x=>x.type==='command/run'&&x.data.commandId===e.data.commandId&&x.data.name==='lab-review');
    if(!call)return false;
    try{const receipt=JSON.parse(e.data.text);return receipt.kind==='artifact-review'&&receipt.path===file.path&&receipt.sha256===file.sha256;}catch{return false;}
  });
}
export const name='lab-native-result-review';
export const inject=['commands'];
export function apply(ctx) {
  for(const accept of [false,true])ctx.effect(()=>ctx.commands.register({
    name:accept?'lab-accept':'lab-review',
    description:accept?'Accept the exact file version you reviewed; does not authorize more execution.':'Fingerprint a file for exact owner review; does not accept it or claim tests passed.',
    input:{hint:accept?'<reviewed SHA256> <workspace-relative file path>':'<workspace-relative file path>'},
    handler:async invocation=>{
      try {
        if(invocation.agent.status==='running')throw Error('Wait for this session to become idle before reviewing or accepting a result.');
        const input=invocation.rawInput.trim(),match=accept?/^([a-f0-9]{64})\s+(.+)$/i.exec(input):null;
        if(accept&&!match)throw Error('Supply the reviewed SHA256 followed by the workspace-relative file path.');
        const events=invocation.agent.session.snapshotEvents();
        if(accept&&unresolvedEffects(events).length)throw Error('Inspect and reconcile uncertain effects before accepting a result.');
        if(accept&&events.findLast(e=>e.type==='plan/mode')?.data.active===true)throw Error('Finish native plan review before accepting a result.');
        const file=await fingerprint(invocation.agent.session.header.cwd,accept?match[2]:input);
        if(accept&&(file.sha256!==match[1].toLowerCase()||!reviewed(events,file)))throw Error('This exact file version has not been reviewed, or it changed. Use /lab-review again.');
        return {kind:'success',text:JSON.stringify({kind:accept?'artifact-accepted':'artifact-review',...file,
          interpretation:accept?'Owner acceptance of these exact bytes only. Not a test certificate, broader permission, or acceptance of future edits.':'Inspect this file and actual tests before accepting. This receipt is not proof of correctness.'})};
      }catch(e){return{kind:'error',text:e.message};}
    }
  }));
}
