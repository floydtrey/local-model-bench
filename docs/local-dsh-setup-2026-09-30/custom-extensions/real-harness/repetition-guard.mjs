/** Bounded, model-independent streaming repetition detection. No model calls. */
export const REPETITION_CODE = 'KC_REPETITION_STOP';

export class RepetitionDetector {
  constructor() { this.buffers = new Map(); this.counts = new Map(); }
  push(channel, text, final = false) {
    // Scan fixed-size slices so one large provider chunk cannot hide an earlier loop.
    for (let offset = 0; offset < text.length || (final && offset === 0); offset += 32) {
      const fragment = text.slice(offset, offset + 32);
      const raw = ((this.buffers.get(channel) ?? '') + fragment).slice(-8192);
      this.buffers.set(channel, raw);
      const count = (this.counts.get(channel) ?? 0) + fragment.length;
      if (count < 32 && !final) { this.counts.set(channel, count); continue; }
      this.counts.set(channel, 0);
      const normalized = raw.toLowerCase().replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').trim().slice(-4096);
      const minimum = channel === 'reasoning' ? 160 : 240;
      for (let width = 2; width <= Math.min(512, Math.floor(normalized.length / 3)); width++) {
        const unit = normalized.slice(-width);
        if (!/\p{L}/u.test(unit) || new Set(unit).size < 2) continue;
        let repeats = 1;
        while ((repeats + 1) * width <= normalized.length &&
          normalized.slice(-(repeats + 1) * width, -repeats * width) === unit) repeats++;
        const required = width >= 80 ? 3 : channel === 'reasoning' ? 6 : 8;
        if (repeats >= required && repeats * width >= minimum) return { channel, periodChars: width, repeats };
      }
      if (!fragment.length) break;
    }
    return null;
  }
}

export async function* guardStream(source, onStop = async () => {}) {
  const detector = new RepetitionDetector();
  const streamed = new Set();
  let detected;
  for await (const chunk of source) {
    if (chunk.type === 'reasoning-delta' || chunk.type === 'text-delta') {
      const channel = chunk.type === 'reasoning-delta' ? 'reasoning' : 'text';
      streamed.add(`${channel}:${chunk.index}`);
      detected = detector.push(channel, chunk.text);
    } else if (chunk.type === 'block-end' && ['reasoning', 'text'].includes(chunk.block.type)) {
      const channel = chunk.block.type;
      detected = detector.push(channel, streamed.has(`${channel}:${chunk.index}`) ? '' : chunk.block.text, true);
    } else if (chunk.type === 'finish') {
      detected = detector.push('reasoning', '', true) ?? detector.push('text', '', true);
    }
    if (detected) break; // IteratorClose reaches the provider's cancellation/finally path before reporting.
    yield chunk;
  }
  if (detected) {
    await onStop(detected);
    yield { type: 'finish', reason: { kind: 'error', failure: { code: REPETITION_CODE,
      message: `KC stopped repetitive ${detected.channel} output. No automatic retry was started. The last verified KC checkpoint is unchanged; review the task before continuing.` } } };
  }
}

export function installRepetitionGuard(ctx, ownsSession, audit) {
  ctx.on('llm/stream', async function* (options, next) {
    if (!options.sessionId || options.purpose || !ownsSession(options.sessionId)) { yield* next(); return; }
    yield* guardStream(next(), details => audit({ event: 'repetition-stopped', session: options.sessionId, ...details }));
  });
  // Explicitly refuse automatic retry even when a deployment installs a retry policy.
  ctx.on('agent/request-error', (event, next) => event.failure.code === REPETITION_CODE ? undefined : next());
}
