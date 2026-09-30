/** Explicit, evidence-bound task updates. No semantic extraction or permission grants. */
import { createHash } from 'node:crypto';
const hash = text => createHash('sha256').update(text).digest('hex');
const kinds = new Set(['objective', 'constraint', 'decision', 'progress', 'question', 'next_action']);
export const MAX_ACTIVE_ITEMS = 32;
export const MAX_ACTIVE_HISTORY = 64;
export const MAX_HISTORY_EVENTS = 96;

export function applyTaskUpdates(messages, history = [], updates = []) {
  if (!Array.isArray(updates) || !Array.isArray(history) || history.length + updates.length > MAX_HISTORY_EVENTS) {
    throw new Error('Task history exceeds the bounded segment limit');
  }
  const events = [...history];
  for (const update of updates) {
    if (!update || Object.keys(update).some(key => !['kind', 'key', 'message_index', 'quote', 'supersedes'].includes(key)) ||
        !kinds.has(update.kind) || typeof update.key !== 'string' || !/^[a-z0-9_-]{1,40}$/.test(update.key) ||
        !Number.isInteger(update.message_index) || typeof update.quote !== 'string' ||
        !update.quote.trim() || update.quote.length > 600) throw new Error('Invalid task update');
    const source = messages[update.message_index];
    if (!source || !source.content.includes(update.quote)) throw new Error('Task update lacks exact source evidence');
    const origin = source.role === 'user' && source.source_kind === 'user' ? 'user_statement' : 'agent_report';
    if (['objective', 'constraint', 'decision'].includes(update.kind) && origin !== 'user_statement') {
      throw new Error('An agent report cannot establish user instructions');
    }
    const event = { kind: update.kind, key: update.key, message_index: update.message_index,
      quote: update.quote, origin, message_sha256: hash(source.content), supersedes: update.supersedes ?? null };
    event.id = hash(JSON.stringify(event));
    if (events.some(item => item.id === event.id)) continue;
    const current = [...events].reverse().find(item => item.kind === event.kind && item.key === event.key);
    if (current) {
      if (event.supersedes !== current.id || event.message_index <= current.message_index) {
        throw new Error('A correction must explicitly supersede the current item with later evidence');
      }
      if (current.origin === 'user_statement' && origin !== 'user_statement') throw new Error('Agent cannot replace user statement');
    } else if (event.supersedes !== null) throw new Error('Unknown superseded task item');
    events.push(event);
    if (new Set(events.map(item => `${item.kind}:${item.key}`)).size > MAX_ACTIVE_ITEMS)
      throw new Error('Active task facts exceed the 32-item bound; facts cannot be silently dropped');
  }
  return events;
}

/** Deterministic rebasing; the caller must archive the complete input before publishing. */
export function compactTaskHistory(messages, history) {
  taskView(messages, history);
  const byKey = new Map();
  for (const event of history) {
    const key = `${event.kind}:${event.key}`, recent = byKey.get(key) ?? [];
    recent.push(event.id); if (recent.length > 2) recent.shift(); byKey.set(key, recent);
  }
  const selected = new Set([...byKey.values()].flat()), ids = new Map();
  let compacted = [];
  for (const event of history.filter(event => selected.has(event.id))) {
    compacted = applyTaskUpdates(messages, compacted, [{ kind: event.kind, key: event.key,
      message_index: event.message_index, quote: event.quote, supersedes: ids.get(event.supersedes) ?? null }]);
    ids.set(event.id, compacted.at(-1).id);
  }
  return compacted;
}

export function taskView(messages, history) {
  // Replay validates stored events too, rather than trusting stored authority labels.
  const replayed = applyTaskUpdates(messages, [], history.map(event => ({
    kind: event.kind, key: event.key, message_index: event.message_index, quote: event.quote,
    supersedes: event.supersedes,
  })));
  if (JSON.stringify(replayed) !== JSON.stringify(history)) throw new Error('Task history integrity mismatch');
  const replaced = new Set(history.map(event => event.supersedes).filter(Boolean));
  return history.filter(event => !replaced.has(event.id)).map(event => ({
    ...event,
    replaces: event.supersedes ? history.find(previous => previous.id === event.supersedes).quote : null,
  }));
}
