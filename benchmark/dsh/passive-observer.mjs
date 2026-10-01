import fs from 'node:fs';
import path from 'node:path';

function walkFiles(root) {
  if (!fs.existsSync(root)) return [];
  const out = [];
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else if (entry.isFile()) {
        const st = fs.statSync(full);
        out.push({ path: full, size: st.size, mtimeMs: st.mtimeMs });
      }
    }
  }
  return out.sort((a,b) => a.path.localeCompare(b.path));
}

function parseLineJson(file) {
  const events = [];
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { return events; }
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const value = JSON.parse(line);
      if (value && typeof value === 'object') events.push(value);
    } catch {}
  }
  return events;
}

function extractAssistantContent(events) {
  const bucket = { reasoning: [], text: [] };
  for (const event of events) {
    if (event?.type !== 'assistant/message') continue;
    const message = event?.data?.message;
    if (!message || message.role !== 'assistant' || !Array.isArray(message.content)) continue;
    for (const block of message.content) {
      if (!block || typeof block !== 'object' || typeof block.text !== 'string') continue;
      const t = String(block.type ?? '').toLowerCase();
      if (t.includes('reason')) bucket.reasoning.push(block.text);
      else if (t === 'text' || t.includes('text')) bucket.text.push(block.text);
    }
  }
  return bucket;
}

function inspectFile(file) {
  const events = parseLineJson(file);
  if (!events.length) return null;
  const session = events.find(e => e.type === 'session') ?? null;
  if (!session) return null;
  const turnEnd = [...events].reverse().find(e => e.type === 'turn/end') ?? null;
  const bucket = extractAssistantContent(events);
  return {
    file,
    id: session.id ?? null,
    createdAt: session.createdAt ?? null,
    isSeeded: session.isSeeded ?? null,
    delegationDepth: session.delegationDepth ?? null,
    turnEndReason: turnEnd?.data?.reason?.kind ?? null,
    eventTypes: [...new Set(events.map(e => e.type).filter(Boolean))].sort(),
    reasoningText: bucket.reasoning.join('\n'),
    assistantText: bucket.text.join('\n')
  };
}

// Passive, post-run approximation of the previous repetition heuristic.
// It cannot stop, retry, warn, or message the model.
function detectRepetition(text, channel) {
  let raw = '';
  let count = 0;
  for (let offset = 0; offset < text.length; offset += 32) {
    const fragment = text.slice(offset, offset + 32);
    raw = (raw + fragment).slice(-8192);
    count += fragment.length;
    if (count < 32) continue;
    count = 0;
    const normalized = raw.toLowerCase()
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/\s+/g, ' ')
      .trim()
      .slice(-4096);
    const minimum = channel === 'reasoning' ? 160 : 240;
    for (let width = 2; width <= Math.min(512, Math.floor(normalized.length / 3)); width++) {
      const unit = normalized.slice(-width);
      if (!/\p{L}/u.test(unit) || new Set(unit).size < 2) continue;
      let repeats = 1;
      while ((repeats + 1) * width <= normalized.length &&
        normalized.slice(-(repeats + 1) * width, -repeats * width) === unit) repeats++;
      const required = width >= 80 ? 3 : channel === 'reasoning' ? 6 : 8;
      if (repeats >= required && repeats * width >= minimum) {
        return { detected: true, periodChars: width, repeats, repeatedChars: repeats * width };
      }
    }
  }
  return { detected: false };
}

const [mode, statePath, dshHome, outputPath, exitCodeRaw] = process.argv.slice(2);
if (!mode || !statePath || !dshHome) {
  console.error('usage: passive-observer.mjs before|after <state> <dshHome> [outputJson] [exitCode]');
  process.exit(2);
}

if (mode === 'before') {
  const files = walkFiles(dshHome);
  const sessions = [];
  for (const f of files) {
    const s = inspectFile(f.path);
    if (s) sessions.push({ file: s.file, id: s.id, createdAt: s.createdAt });
  }
  const state = {
    startedAt: new Date().toISOString(),
    startedAtMs: Date.now(),
    files,
    sessionIds: sessions.map(s => s.id).filter(Boolean)
  };
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
  process.exit(0);
}

if (mode !== 'after' || !outputPath) process.exit(2);

const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const oldFiles = new Map(state.files.map(f => [f.path, f]));
const oldIds = new Set(state.sessionIds);
const current = walkFiles(dshHome);
const changed = current.filter(f => {
  const old = oldFiles.get(f.path);
  return !old || old.size !== f.size || old.mtimeMs !== f.mtimeMs;
});

const candidateSessions = [];
for (const f of changed) {
  const s = inspectFile(f.path);
  if (s && !oldIds.has(s.id)) candidateSessions.push(s);
}

const fresh = candidateSessions.filter(s =>
  (s.createdAt == null || s.createdAt >= state.startedAtMs - 5000));

const primary = fresh.length === 1 ? fresh[0] : null;
const reasoning = primary?.reasoningText ?? '';
const text = primary?.assistantText ?? '';

const evidenceDir = path.dirname(outputPath);
let nativeSessionEvidence = null;
if (primary) {
  const sessionDir = path.join(evidenceDir, 'session');
  fs.mkdirSync(sessionDir, { recursive: true });
  nativeSessionEvidence = path.join(sessionDir, path.basename(primary.file));
  fs.copyFileSync(primary.file, nativeSessionEvidence);
}
fs.writeFileSync(path.join(evidenceDir, 'reasoning.txt'), reasoning);
fs.writeFileSync(path.join(evidenceDir, 'final.txt'), text);

const result = {
  observerMode: 'post-run-only',
  observerCanIntervene: false,
  runStartedAt: state.startedAt,
  runObservedAt: new Date().toISOString(),
  dshExitCode: Number(exitCodeRaw),
  changedFileCount: changed.length,
  newSessionCount: fresh.length,
  sessions: fresh.map(s => ({
    file: s.file,
    id: s.id,
    createdAt: s.createdAt,
    isSeeded: s.isSeeded,
    delegationDepth: s.delegationDepth,
    turnEndReason: s.turnEndReason,
    eventTypes: s.eventTypes,
    reasoningChars: s.reasoningText.length,
    assistantTextChars: s.assistantText.length
  })),
  freshSessionIsolation: {
    passed: !!primary && primary.isSeeded === false && primary.delegationDepth === 0,
    basis: 'new native session created after launch with isSeeded=false and delegationDepth=0'
  },
  reasoningCapturedInSession: reasoning.length > 0,
  evidence: {
    nativeSession: nativeSessionEvidence,
    reasoning: path.join(evidenceDir, 'reasoning.txt'),
    final: path.join(evidenceDir, 'final.txt')
  },
  repetitionObservation: {
    reasoning: detectRepetition(reasoning, 'reasoning'),
    text: detectRepetition(text, 'text')
  }
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));

console.log('');
console.log('Passive observation:');
console.log('  changed files under DSH_HOME: ' + result.changedFileCount);
console.log('  new native sessions: ' + result.newSessionCount);
console.log('  fresh-session isolation: ' + (result.freshSessionIsolation.passed ? 'PASS' : 'NOT PROVEN'));
console.log('  reasoning preserved in session: ' + (result.reasoningCapturedInSession ? 'YES' : 'NO'));
if (primary) console.log('  terminal stop: ' + (primary.turnEndReason ?? 'unknown'));
console.log('  repetition observer (reasoning): ' + (result.repetitionObservation.reasoning.detected ? 'WOULD TRIGGER' : 'no trigger'));
console.log('  repetition observer (text): ' + (result.repetitionObservation.text.detected ? 'WOULD TRIGGER' : 'no trigger'));
console.log('  observations: ' + outputPath);
