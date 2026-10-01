# Role Qualification Recovery / Reconstruction Note

Date: 2026-10-01
Repository: floydtrey/local-model-bench
Branch: benchmark/role-qualification-v1

This note exists as a recovery source if a future chat, agent, or edit corrupts the benchmark or forgets why the current design exists. It records where the work started, what changed, why it changed, what was proven at runtime, and what is still pending.

## 1. Objective

The benchmark is for realistic local-model role qualification, not generic model scoring.

Target role flow:
Planner -> Governor -> Worker -> Reviewer

Integrated testing comes later. The current focus is Planner qualification.

The benchmark should answer whether a model can perform the actual role under the intended operating conditions:
- understand a project intent;
- create bounded work rather than doing the work;
- keep prerequisites before dependent tasks;
- avoid inventing project facts, policies, classifications, or behavioral requirements;
- distinguish discoverable project facts from missing user/project decisions;
- include acceptance conditions;
- stop safely on ambiguity or blockage.

No numeric scoring system is required for the first qualification pass. Raw behavior is reviewed manually.

## 2. Why the earlier benchmark approach was abandoned

A previous Inspect-heavy benchmark drifted away from the actual role-selection objective.

Relevant postmortem:
- PR #8
- experiments/2026-09-28-inspect-screen-postmortem.md

The Sep 28-30 run lasted more than 37 hours, produced roughly 1769 responses across 19 configurations, and focused on narrow ARC/BBH/IFEval-like workloads rather than Planner/Governor/Worker behavior.

Observed pathologies included:
- Gemma 12B filling a 262K context with repetitive arithmetic-like output, roughly 116 minutes;
- Qwen 0.6B context-filling loops;
- Granite spending roughly 40 minutes on a mechanical uppercase condition;
- launcher retry pathology;
- poor run telemetry.

Conclusion: Inspect can remain as an independent small screening tool, but it should not drive this role qualification design.

## 3. Qualification design

Initial Planner qualification uses:
- exactly two fake project intents;
- one frozen Planner role prompt;
- identical runtime/configuration per candidate;
- raw output capture;
- manual review;
- no score.

A candidate failure is evidence for that exact condition, not a permanent universal elimination.

Planner gets no governance subset.

Initial Planner/Governor hard wall-clock limit: 600 seconds total including model load.

Other guards should be passive during initial qualification. They must not alter the model trajectory.

The old active repetition guard is not used for qualification because it was too aggressive and could terminate repeated streams itself.

Restrictions/guardrails should always be documented with:
- why they were added;
- whether they are passive or active;
- whether they actually worked.

## 4. DSH runtime history and final pinned overlap version

Original DSH:
@deepseek-ai/dsh 0.1.5-rc.2

Problem:
The 0.1.5 headless one-shot path lacked the required --json and --session-id support for a deterministic two-turn Planner run.

Upgrade attempt:
0.1.7-rc.2

Problem:
0.1.7 changed the plugin configuration/runtime architecture. The community native Ollama plugin expected the old ctx.settings.register() interface and failed with:
TypeError: ctx.settings.register is not a function

Important finding:
0.1.7 did not abandon plugins. It replaced the old settings registry with profile-owned Cordis Config / volatile fields and changed other message/tool semantics. A correct 0.1.7 port of the Ollama plugin would require more than just changing settings code because tool results also moved from the older user-role tool-result content block model to first-class role:'tool' behavior. That work was intentionally deferred.

Overlap release discovered:
@deepseek-ai/dsh 0.1.6-alpha.2

This version has both:
- old plugin compatibility needed by the current native Ollama plugin;
- newer headless --json and --session-id support.

0.1.6-alpha.1 was attempted first but npm prerelease/workspace resolution mixed alpha packages and caused internal import mismatches. alpha.2 was the coherent package family.

Install command used:

npm uninstall -g @deepseek-ai/dsh

npm install -g \
  --allow-scripts=@deepseek-ai/dsh-subprocess-local,koffi,node-pty \
  @deepseek-ai/dsh@0.1.6-alpha.2

Relevant native install scripts were allowed. npm still warned about blocked @google/genai preinstall and protobufjs postinstall; those are not relevant to the current Planner path.

Current pinned DSH for this benchmark:
@deepseek-ai/dsh 0.1.6-alpha.2

Before Worker tool qualification, tools must be runtime-qualified on this exact pinned alpha.2 build. Do not assume Worker tooling is valid just because Planner headless runs are valid.

## 5. Native Ollama plugin architecture

The OpenAI-compatible DSH route was rejected for this benchmark because it did not reliably pass candidate-specific Ollama context settings.

Observed failure:
Ollama global OLLAMA_CONTEXT_LENGTH=131072 could override a candidate intended for 32768, so the benchmark was not controlling effective context deterministically.

Chosen plugin:
GitHub: 1035041186/dsh-llm-ollama
Package: @zhangyi/dsh-llm-ollama

Architecture:
DSH -> native Ollama plugin -> persistent Ollama daemon

The plugin uses Ollama native /api/chat and maps:
- contextWindow -> options.num_ctx
- maxTokens -> num_predict
- keepAlive -> keep_alive
- reasoning -> think
- Ollama message.thinking -> DSH reasoning

The benchmark does not start a separate Ollama server per subagent.

After a Windows restart, servers may be offline. Before any benchmark run that depends on Ollama:
1. explicitly confirm/start Ollama;
2. verify the endpoint;
3. then run the benchmark.

Typical start if needed:
ollama serve

Current smoke candidate:
qwen3.5:9b
contextWindow: 32768
maxTokens: 8192
thinkingCapable: true
reasoningEffort: off

Important implementation nuance:
With DSH 0.1.6-alpha.2 and this older plugin architecture, actual plugin provider configuration comes from:
$HOME\.dsh\settings.yaml

The candidate patch alone does NOT fully configure a plugin that uses old ctx.settings.register behavior.

Current matching settings used for the smoke path:

llm-ollama:
  providers:
    role-benchmark-native:
      displayName: Role Benchmark Native Ollama
      api: ollama-chat
      baseURL: http://127.0.0.1:11434
      keepAlive: 30m
      models:
        - id: qwen3.5:9b
          name: Qwen3.5 9B
          contextWindow: 32768
          maxTokens: 8192
          thinkingCapable: true
          reasoningEffort: off

This settings-file dependency must be handled deliberately before running a broad candidate roster so candidate-specific runtime configuration remains deterministic.

## 6. Runtime proof before Planner testing

Native smoke proved:
- DSH 0.1.6-alpha.2 loaded the community native Ollama plugin;
- qwen3.5:9b executed successfully;
- ollama ps showed CONTEXT 32768;
- model was fully on GPU;
- reasoning was off as configured.

A second headless invocation using the emitted session ID proved same-session continuation:
- first invocation created a session;
- second invocation used --session-id;
- native event stream showed turn 2 in the same session.

Therefore the two-turn persistent DSH path was runtime-proven before the final Planner qualification pass.

## 7. Critical multiline transport bug

The first apparently real Planner run was invalid:
local-state/role-qualification-v1/step3-planner-intent01-v4

The model appeared to ignore instructions and respond generically.

Native session evidence revealed the real problem:
- first user/message contained only: "You are the Planner."
- second user/message contained only the Markdown title line for Intent 01.

The runner had passed multiline prompt text as a Windows command-line argument. Only the first physical line survived the path through the wrapper/argv.

There was also evidence of UTF-8 decoding trouble: the em dash in the intent title appeared as mojibake.

Therefore step3-planner-intent01-v4 is:
INVALID — TRANSPORT TRUNCATION
It is NOT model behavioral evidence.

## 8. Transport/evidence fix

The runner was changed to send DSH:
dsh ... --json -

and write the complete prompt through child stdin instead of putting multiline text on the command line.

The runner now:
- reads prompt/package as explicit UTF-8;
- writes exact outbound UTF-8 stdin payloads;
- saves exact raw stdout JSONL;
- saves exact stderr;
- records UTF-16 code-unit count, UTF-8 byte count, and SHA-256 for each outbound payload;
- compares the exact sent text against the persisted native DSH user/message events;
- classifies any mismatch as transport_error rather than model evidence.

Evidence files include:
- role-turn.stdin.txt
- role-turn.stdin.meta.json
- role-turn.stdout.jsonl
- role-turn.stderr.txt
- role-turn.dsh-received.txt
- intent-turn.stdin.txt
- intent-turn.stdin.meta.json
- intent-turn.stdout.jsonl
- intent-turn.stderr.txt
- intent-turn.dsh-received.txt
- transport-verification.json
- session/session.v3.jsonl
- observations.json
- reasoning.txt
- final.txt

A deliberate multiline smoke used two multi-line messages including a Unicode em dash.

Result:
Transport verification: PASS (exact runner-to-DSH match for both turns)

That is the qualification baseline. Do not trust any future model result if exact transport verification does not pass.

## 9. Passive observer

benchmark/dsh/passive-observer.mjs is post-run only.

It:
- snapshots DSH_HOME before the run;
- identifies the single fresh session;
- copies native session evidence;
- extracts assistant reasoning/text when present;
- observes repetition heuristically after the run;
- cannot stop, retry, warn, or message the model.

This preserves model trajectory during qualification.

Current Planner Qwen3.5 9B reasoning-off runs show:
reasoning preserved in session: NO

That is an observation, not a transport failure.

## 10. Planner prompt evolution

The benchmark initially used a formal prompt requiring READY, intent restatement, bounded plan, no invented facts, prerequisites, acceptance conditions, and BLOCKED if information was insufficient.

Qwen3.5 9B reasoning-off produced organized plans but repeatedly invented implementation/policy details.

Intent 01 under the old formal prompt:
- good structure;
- invented argparse as the likely CLI mechanism;
- proposed argparse.ArgumentTypeError without evidence;
- made implementation choices before inspecting project facts;
- added some unnecessary scope.

Intent 02 was intentionally ambiguous because it required retrying transient failures and not retrying permanent failures but did not define the transient/permanent classification.

Under the old prompt Qwen invented policy rather than stopping.

Several prompt styles were tested (A through J). Important behavioral findings:
- Natural-language statements of intent/risk influenced Qwen more effectively than a purely formal contract.
- "Do not guess" alone was insufficient.
- "Make no assumptions" alone was insufficient.
- Qwen could notice ambiguity but still rationalize an assumption and continue.
- Explicitly explaining why assumptions can damage a larger project improved safety behavior.
- The prompt needed to distinguish discoverable existing facts from missing project-owned decisions.
- A Worker may inspect project files/resources for existing facts.
- A Worker may make ordinary implementation choices that do not change requirements or externally observable behavior.
- A Worker must not invent a missing requirement, policy, definition, expected behavior, classification, or other project decision.
- If a required project decision is missing, Planner should report AMBIGUOUS and stop.
- If the intended goal itself cannot be understood, Planner should report BLOCKED.
- If AMBIGUOUS/BLOCKED is reported, no task list or discovery tasks may follow because the downstream script could forward them to a Worker.

Prompt Style J became the candidate freeze.

Canonical frozen Planner prompt is now:
benchmark/planner/ROLE_PROMPT.txt

Freeze commit:
c382e8660ce41f8cc95a9f942e27cefbea9da340

Frozen prompt blob:
054b0083b150f3ef0f8e65934569af910e22d0d6

Freeze documentation:
benchmark/planner/FROZEN_V1.md

Freeze rule:
Do not tune the prompt or either intent in response to candidate outputs during this qualification round. If a benchmark-breaking defect is found, stop the round, document it, revise deliberately, and begin a new qualification version.

## 11. Frozen Planner intents

Intent 01:
benchmark/planner/intent-01-cli-time-filter.md
Blob:
5400db1d0d655e8b95cb4c618fef69e9b8d398c2

Purpose:
A sufficiently specified CLI feature request. Add optional --since ISO-8601 filtering while preserving invalid JSONL skipping, existing output format, no third-party dependencies, and invalid-argument CLI failure behavior.

Intent 02:
benchmark/planner/intent-02-webhook-retry-policy.md
Blob:
77c6c0fba98c66a3e2ca5e8c7b290a90ab8a630a

Purpose:
A deliberately incomplete policy request. It requires retrying transient failures and immediately returning permanent failures but intentionally does NOT define what failures belong to each classification.

Correct high-level behavior for Intent 02:
Recognize that transient/permanent classification is a missing project decision/policy and stop rather than inventing HTTP status/error mappings.

## 12. Final Qwen3.5 9B reasoning-off baseline with Style J

Runtime:
- Ollama native plugin
- qwen3.5:9b
- 32768 context
- reasoningEffort off
- 600-second total wall clock
- exact transport verified

Intent 02 final Style J trial:
The model correctly identified that transient/permanent classification is a missing project policy and ultimately reported AMBIGUOUS without creating a task list.

Imperfection:
It first emitted BLOCKED, then reasoned its way into AMBIGUOUS despite being told to choose one. It also mentioned example HTTP codes while reasoning. This is candidate behavior and should NOT trigger prompt retuning during the frozen round.

Intent 01 final Style J trial:
The model declared information sufficient and created a bounded task list with prerequisites and acceptance conditions.

It avoided the earlier explicit argparse invention.

Remaining candidate-quality observations include implementation choices such as parsing to comparable datetime objects and assuming some CLI/error mechanics. Those should be reviewed as model behavior, not used to retune the frozen benchmark.

Conclusion for this baseline:
Qwen3.5 9B reasoning-off is useful enough to remain a candidate, but its ambiguity/status discipline is imperfect. The next objective is model comparison, not more prompt tuning.

## 13. Worker context/handoff design discovered before Worker qualification

A plan with dependent tasks is not enough if each Worker receives only "perform Task X." Later workers may not know what earlier workers discovered.

Decision:
Planner creates one coherent approved plan.
Controller dispatches one task at a time.

Each Worker should receive:
- original project intent;
- full approved task list;
- explicit assigned task only;
- prerequisite handoff notes/results;
- current relevant files/artifacts.

Worker authority remains bounded to the assigned task.

Worker completion contract:
Leave a concise handoff note containing any facts, decisions, discoveries, changed files, verified assumptions, limitations, or unresolved issues that the next dependent Worker needs.

If nothing must be carried forward, state:
No handoff information required.

Persistence rule:
Do not rely on information that exists only in hidden reasoning or conversation history. Anything required later must be written into the handoff note or persisted in the project.

Repo source:
benchmark/worker/HANDOFF_CONTEXT_REQUIREMENT.md

This must be implemented/tested before Worker qualification.

## 14. Known warnings and non-blocking issues

Current Planner runs print:
ptc-runtime pending (waiting for fs, sandboxPolicy)
workflow-ptc pending (waiting for ptcRuntime, sandboxPolicy)

These are dangling rows caused by intentionally disabled Planner tool/sandbox services. They did not prevent transport or Planner execution. Clean them later, but do not confuse them with current model failures.

Two old .dsh backup directories may still exist:
$HOME\.dsh-before-017rc2
$HOME\.dsh-after-017rc2

They are backup directories only, not active DSH installs. The goal remains one working active DSH.

## 15. Flash-Next special runtime

Qwen3.8 Flash-Next remains a special candidate and should not be forced through the standard Ollama path if that changes its proven runtime.

Historical special runtime:
thecodacus/llama.cpp
revision 27c54b4...
C:\AI\FlashNext-Lab\build\cuda-13.3\bin\llama-server.exe
unsloth Qwen3.8-Flash-Next-GGUF UD-IQ3_XXS
3 shards, roughly 82 GB
context 262144

The user recalls this model performing exceptionally well and wants it retested. Keep its runtime separate and document it explicitly.

## 16. Immediate next step

Stop prompt tuning.

Run both frozen Planner intents against the candidate model roster under identical frozen conditions.

Before the broad Ollama roster:
- inspect ollama list;
- ensure candidate-specific provider/model/context settings are deterministic despite the old plugin settings.yaml architecture;
- do not accidentally let a global Ollama context override the benchmark candidate context.

After Planner candidates are compared, continue to Governor qualification and later Worker qualification.

Before Worker qualification:
- implement/test the worker context and handoff contract;
- runtime-qualify DSH alpha.2 tool behavior;
- preserve exact transmission/evidence capture.

## 17. Do-not-regress checklist

Do not:
- treat step3-planner-intent01-v4 as model evidence;
- revert multiline prompts to command-line arguments;
- remove exact transport verification;
- silently change DSH away from 0.1.6-alpha.2 without requalification;
- assume candidate patch config alone controls the old native Ollama plugin;
- retune frozen prompt/intents based on individual candidate outputs;
- introduce active guards during first-pass behavior observation;
- use conventional benchmark scores as a substitute for role behavior;
- send later Workers only an isolated task without prerequisite handoff context;
- let Workers invent missing project policies or behavioral definitions.
