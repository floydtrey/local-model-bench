/** Flag the second unchanged call and stop the third, including interleaved calls. */
import { createHash } from 'node:crypto';
function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
}
export class ToolProgressGuard {
  constructor() { this.window = []; this.stopped = null; }
  resetForInput() { if (!this.stopped) this.window = []; }
  observe(name, args, outcome) {
    if (this.stopped) return this.stopped;
    const digest = value => createHash('sha256').update(canonical(value)).digest('hex');
    const call = digest({ name, args }), result = digest(outcome);
    this.window.push({ call, result }); if (this.window.length > 32) this.window.shift();
    // A changed response to the same arguments starts a new unchanged-result streak.
    const changedAt = this.window.findLastIndex(entry => entry.call === call && entry.result !== result);
    const occurrences = this.window.slice(changedAt + 1).filter(entry => entry.call === call && entry.result === result).length;
    if (occurrences >= 3) {
      this.stopped = { action: 'stop', tool: name, occurrences, lookbackCalls: 32 };
      return this.stopped;
    }
    if (occurrences === 2) return { action: 'warn', tool: name, occurrences, lookbackCalls: 32 };
    return null;
  }
}
