/** Checkpoint metadata in Harness's existing storage domain, scoped by native session. */
export class NativeMemoryHeads {
  constructor(table, sessionId) { this.table = table; this.sessionId = sessionId; }
  record() { return this.table.get(this.sessionId); }
  get(task) { const r=this.record(); return r?.task === task ? r.head : null; }
  sourceHash(task, source) { const r=this.record(); return r?.task === task ? r.sources[source] : undefined; }
  versions(task, before=-1) {
    if(!Number.isInteger(before)||before < -1) throw Error('Invalid history cursor');
    const r=this.record();return r?.task===task ? r.versions.filter(v=>before===-1||v.revision<before).slice(-10).reverse() : [];
  }
  version(task,revision) { const r=this.record();return r?.task===task ? r.versions.find(v=>v.revision===revision) : undefined; }
  async publish(task,expected,next,sources=[],onPublished) {
    if(onPublished) throw Error('Native memory does not support external transaction callbacks');
    const result=await this.table.update(this.sessionId,record=>{
      if(record.task!==null&&record.task!==task) throw Error('Native session memory binding changed');
      if(JSON.stringify(record.head)!==JSON.stringify(expected)) throw Error('Task head changed; reload before retrying');
      const hashes={...record.sources};
      for(const {id,sha} of sources) {
        if(hashes[id]&&hashes[id]!==sha) throw Error('Stable source identity was reused with different content');
        hashes[id]=sha;
      }
      const head={revision:(expected?.revision??-1)+1,ref:next.version_ref,sha:next.sha256};
      return {task,head,versions:[...record.versions,head],sources:hashes};
    });
    return result.head;
  }
}
