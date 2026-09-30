/** Native preset extension: KC readback + Harness compaction/storage. No worker or plan owner. */

import {readFileSync} from 'node:fs';

import {createRequire} from 'node:module';

import {join} from 'node:path';

import {runtime} from '../compaction-trial/runtime.mjs';

import {RecoveryStore} from '../compaction-trial/recovery.mjs';

import {CarryForward,captureSources} from '../compaction-trial/carry-forward.mjs';

import {NativeMemoryHeads} from './native-memory-heads.mjs';

import {browseEvidence} from './evidence-browser.mjs';

const require=createRequire(join(process.env.APPDATA,'npm/node_modules/@deepseek-ai/dsh/package.json'));

const {z}=require('zod');

const {defineDomain,domainTable}=await runtime('dsh-storage-domain');

const {BasicCompactionEngine}=await runtime('dsh-compaction-basic');

const {defineTool}=await runtime('dsh-tools');

const head=z.object({revision:z.number().int().nonnegative(),ref:z.string(),sha:z.string().regex(/^[a-f0-9]{64}$/)});

const spec=defineDomain({name:'lab_native_memory',version:1,tables:{sessions:domainTable(z.object({

  task:z.string().nullable(),head:head.nullable(),versions:z.array(head),sources:z.record(z.string(),z.string())

}))}});

// The existing facility owns shutdown. Share its one handle across preset generations.

const domains=new WeakMap();

/** Preserve the current human request even when recent tool output displaces it. */

export function preserveLatestRequest(packet,evidence,maxChars=6000,nativeGoal=null) {
  const result=structuredClone(packet);
  if(nativeGoal) result.native_goal_at_checkpoint={id:nativeGoal.id,revision:nativeGoal.revision,
    objective:nativeGoal.objective,phase:nativeGoal.phase,roundsStarted:nativeGoal.roundsStarted,
    maxGoalRounds:nativeGoal.maxGoalRounds,
    guidance:'Historical snapshot of the Harness-owned goal. Read get_goal for current state; this does not grant or renew permissions.'};
  const index=evidence.messages.findLastIndex(m=>m.role==='user'&&m.source_kind==='user');

  if(index>=0) result.latest_user_request={message_index:index,text:evidence.messages[index].content,

    guidance:'Exact historical user text; retain original scope. Not renewed authorization.'};

  while(JSON.stringify(result).length>maxChars&&result.excerpts.length>1)result.excerpts.splice(1,1);

  result.omitted_messages=result.total_messages-result.excerpts.length;

  if(JSON.stringify(result).length>maxChars)throw Error('Current request and pinned evidence exceed recovery budget; original context retained');

  return result;

}

export const name='lab-native-memory';

export const inject=['storageDomain','llm','tokenMeter','sessions','tools'];

export async function apply(ctx,config) {

  if(!config?.settingsFile||!config?.credentialFile) throw Error('Explicit existing KC configuration required');

  const settings=JSON.parse(readFileSync(config.settingsFile,'utf8'));

  const {token}=JSON.parse(readFileSync(config.credentialFile,'utf8'));

  const store=new RecoveryStore({url:settings.kc_url,scope:settings.scope_ref,token,project:'KC-native-harness',
    timeoutMs:config.requestTimeoutMs??15000});
  if(!domains.has(ctx.storageDomain)) domains.set(ctx.storageDomain,ctx.storageDomain.open(spec));

  const table=(await domains.get(ctx.storageDomain)).table('sessions');

  const controllers=new WeakMap(),queues=new WeakMap();

  async function controller(agent) {

    if(!controllers.has(agent)) controllers.set(agent,(async()=>{

      const id=agent.session.id;

      if(!table.get(id)) await table.put(id,{task:null,head:null,versions:[],sources:{}});

      return new CarryForward(store,new NativeMemoryHeads(table,id),id,{maxChars:6000,maxMessages:3});

    })());

    return controllers.get(agent);

  }

  function serial(agent,fn) {

    const result=(queues.get(agent)??Promise.resolve()).catch(()=>{}).then(fn);

    queues.set(agent,result);return result;

  }

  class NativeKcCompaction extends BasicCompactionEngine {

    async summarize(_input,agent,signal) {

      return serial(agent,async()=>{

        const c=await controller(agent),saved=await c.prepare(agent.session,signal);

        // Keep the already-budgeted original excerpts. The legacy display adapter

        // truncates every passage to 120 characters, which can hide task requirements.

        const packet=preserveLatestRequest(saved.recovery.packet,saved.recovery.evidence,6000,ctx.get('goals')?.get(agent));
        return {provider:'kc',model:'verified-memory',summary:[{type:'text',text:

          'Verified KC recovery evidence. This is historical context, never new authorization.\n'+JSON.stringify(packet)}]};

      });

    }

  }

  await ctx.plugin(NativeKcCompaction,{auto:config.auto ?? true,thresholdRatio:0.8,retainTokens:1000,compactionRetries:0,maxOverflowRetries:1});

  const restored=new WeakSet();

  ctx.on('agent/pre-step',async({agent,signal},next)=>{

    const accepted=await next();if(accepted.kind!=='enter')return accepted;

    if(!restored.has(agent)) {

      const c=await controller(agent);

      // Verify the persisted checkpoint before any resumed inference; native history already contains its packet.

      await c.restore(signal);restored.add(agent);

    }

    return accepted;

  });

  const output={schema:{type:'object',properties:{text:{type:'string',required:true}},additionalProperties:false},render:(_args,value)=>[{type:'text',text:value.text}]};

  const register=spec=>ctx.effect(()=>ctx.tools.register(defineTool({...spec,output,

    execute:(args,exec)=>serial(exec.agent,()=>spec.execute(args,exec)),

    presentCall:args=>({card:'generic',title:spec.name,kind:'other',rawInput:args})})));

  register({name:'kc_checkpoint',description:'Save and verify native session evidence in KC. Does not approve work or claim tested success.',parameters:{},

    async execute(_args,{agent,signal}) {const c=await controller(agent),r=await c.prepare(agent.session,signal);return{text:`Verified KC checkpoint ${r.head.ref}`};}});

  register({name:'kc_task_update',description:'Preserve a short exact source quote. Objectives, constraints and decisions must quote the user. Later corrections supersede earlier values with the same kind/key. Not authorization.',

    parameters:{kind:{type:'string',required:true,enum:['objective','constraint','decision','progress','question','next_action']},key:{type:'string',required:true},quote:{type:'string',required:true}},

    async execute(args,{agent,signal}) {

      const c=await controller(agent);

      const source=captureSources(agent.session).reverse().find(s=>s.message.content.some(b=>b.text.includes(args.quote))&&

        (!['objective','constraint','decision'].includes(args.kind)||s.message.source?.kind==='user'));

      if(!source||!args.quote.trim())throw Error('Exact original source quote not found');

      const old=await c.currentItem(args.kind,args.key);if(old?.quote===args.quote)return{text:'Already recorded.'};

      c.propose({...args,sourceId:source.id,...(old?{supersedes:old.id}:{})});

      try{const r=await c.prepare(agent.session,signal);return{text:`Verified task update ${r.head.ref}`};}

      catch(e){c.pending=[];throw e;}

    }});

  register({name:'kc_evidence',description:'Read verified archived evidence for this native session. history lists revisions; read/search use revision -1 for current. Historical text never grants permissions.',

    parameters:{action:{type:'string',required:true,enum:['history','search','read']},revision:{type:'integer',required:true},message_index:{type:'integer',required:true},offset:{type:'integer',required:true},query:{type:'string',required:true}},

    async execute(args,{agent}) {return{text:JSON.stringify(await browseEvidence(await controller(agent),{action:args.action,revision:args.revision,messageIndex:args.message_index,offset:args.offset,query:args.query}))};}});

}

