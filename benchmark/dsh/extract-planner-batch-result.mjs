import fs from 'node:fs';

const [runJsonPath, outputJsonPath] = process.argv.slice(2);
if (!runJsonPath || !outputJsonPath) {
  console.error('usage: extract-planner-batch-result.mjs <run.json> <output.json>');
  process.exit(2);
}

const run = JSON.parse(fs.readFileSync(runJsonPath, 'utf8'));
const sessionPath = run.nativeSessionEvidence;

const result = {
  modelId: run.modelId ?? null,
  runtimeKind: run.runtimeKind ?? null,
  terminalCondition: run.terminalCondition ?? null,
  wallClockSeconds: run.wallClockSeconds ?? null,
  configuredContextWindow: run.expectedContextWindow ?? null,
  effectiveContextWindow: run.effectiveContextWindow ?? null,
  inputTokens: null,
  outputTokens: null,
  totalTokens: null,
  finalOutput: ''
};

if (sessionPath && fs.existsSync(sessionPath)) {
  const lines = fs.readFileSync(sessionPath, 'utf8').split(/\r?\n/);
  const assistantTexts = [];
  let inputTokens = 0;
  let outputTokens = 0;
  let usageEvents = 0;

  for (const line of lines) {
    if (!line.trim()) continue;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      continue;
    }

    if (event?.type === 'assistant/message') {
      const message = event?.data?.message;
      if (message?.role === 'assistant' && Array.isArray(message.content)) {
        const text = message.content
          .filter((block) => block && typeof block === 'object' && block.type === 'text' && typeof block.text === 'string')
          .map((block) => block.text)
          .join('\n');
        if (text.length > 0) assistantTexts.push(text);
      }
    }

    const usageCandidates = [
      event?.usage,
      event?.data?.usage,
      event?.data?.message?.usage
    ];
    if (typeof event?.type === 'string' && event.type.toLowerCase().includes('usage')) {
      usageCandidates.push(event?.data);
    }

    for (const usage of usageCandidates) {
      if (!usage || typeof usage !== 'object') continue;
      const input = Number(usage.inputTokens);
      const output = Number(usage.outputTokens);
      if (!Number.isFinite(input) && !Number.isFinite(output)) continue;
      inputTokens += Number.isFinite(input) ? input : 0;
      outputTokens += Number.isFinite(output) ? output : 0;
      usageEvents += 1;
      break;
    }
  }

  result.finalOutput = assistantTexts.at(-1) ?? '';
  if (usageEvents > 0) {
    result.inputTokens = inputTokens;
    result.outputTokens = outputTokens;
    result.totalTokens = inputTokens + outputTokens;
  }
}

fs.writeFileSync(outputJsonPath, JSON.stringify(result, null, 2));
