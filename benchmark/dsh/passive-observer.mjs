import fs from 'node:fs';
import path from 'node:path';

function walkJsonl(root) {
  if (!fs.existsSync(root)) return [];
  const out = [];
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else if (entry.isFile() && entry.name.endsWith('.jsonl')) out.push(full);
    }
  }
  return out.sort();
}

function parseJsonl(file) {
  const events = [];
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch {}
  }
  return events;
}

// Offline copy of the prior streaming repetition heuristic.
// It observes completed output only and cannot cancel or message the model.
function detectRepetition(text, channel = 'combined') {
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

const [mode, statePath, dshHome, consoleLog, outputPath, exitCodeRaw] = process.argv.slice(2);
if (!mode || !statePath || !dshHome) {
  console.error('usage: passive-observer.mjs before|after <state> <dshHome> [consoleLog] [outputJson] [exitCode]');
  process.exit(2);
}

const sessionRoot = path.join(dshHome, 'sessions');

if (mode === 'before') {
  const state = {
    startedAt: new Date().toISOString(),
    existingSessions: walkJsonl(sessionRoot)
  };
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
  process.exit(0);
}

if (mode !== 'after' || !consoleLog || !outputPath) process.exit(2);

const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const before = new Set(state.existingSessions);
const current = walkJsonl(sessionRoot);
const newFiles = current.filter(f => !before.has(f));

const sessions = newFiles.map(file => {
  const events = parseJsonl(file);
  const session = events.find(e => e.type === 'session') ?? null;
  const turnEnd = [...events].reverse().find(e => e.type === 'turn/end') ?? null;
  return {
    file,
    id: session?.id ?? null,
    isSeeded: session?.isSeeded ?? null,
    delegationDepth: session?.delegationDepth ?? null,
    turnEndReason: turnEnd?.data?.reason?.kind ?? null,
    eventTypes: [...new Set(events.map(e => e.type).filter(Boolean))].sort()
  };
});

const consoleText = fs.existsSync(consoleLog) ? fs.readFileSync(consoleLog, 'utf8') : '';
const result = {
  observerMode: 'post-run-only',
  observerCanIntervene: false,
  runStartedAt: state.startedAt,
  runObservedAt: new Date().toISOString(),
  dshExitCode: Number(exitCodeRaw),
  newSessionCount: sessions.length,
  sessions,
  freshSessionIsolation: {
    passed: sessions.length === 1 &&
      sessions[0].isSeeded === false &&
      sessions[0].delegationDepth === 0,
    basis: 'new session JSONL created after launch with isSeeded=false and delegationDepth=0'
  },
  reasoningVisibleInConsole: consoleText.includes('dsh: reasoning:'),
  legacyRepetitionHeuristic: detectRepetition(consoleText)
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
console.log('');
console.log('Passive observation:');
console.log('  new session files: ' + result.newSessionCount);
console.log('  fresh-session isolation: ' + (result.freshSessionIsolation.passed ? 'PASS' : 'NOT PROVEN'));
console.log('  reasoning captured: ' + (result.reasoningVisibleInConsole ? 'YES' : 'NO'));
console.log('  legacy repetition heuristic: ' + (result.legacyRepetitionHeuristic.detected ? 'WOULD TRIGGER' : 'no trigger'));
if (sessions.length === 1) console.log('  terminal stop: ' + (sessions[0].turnEndReason ?? 'unknown'));
console.log('  observations: ' + outputPath);
