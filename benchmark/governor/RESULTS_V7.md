# Governor Qualification Results — v7

## Purpose

Governor qualification tests whether a model can independently review a Planner-produced plan against Law, General Intent, and Project Intent, then pass only the relevant missing intent to bounded Workers.

The Governor must not rewrite the approved plan. Deterministic software retains the original Planner output and attaches Governor-produced intent guidance to the corresponding Worker task.

## Prompt direction

The best-performing prompt direction was the short conversational Governor prompt rather than the longer contract-style versions.

The short prompt explains why the Governor exists:
- projects lose the original goal as bounded tasks move between Workers;
- the task plan already tells the Worker what to do;
- full project intent can cause Workers to continue beyond their bounded stopping point;
- the Governor should therefore validate the plan and extract only the relevant intent context that the Worker would otherwise be missing.

This substantially reduced runtime compared with earlier Governor prompt versions while preserving useful behavior.

## Reasoning configuration

The normal Governor baseline remains reasoning off where explicitly supported.

Reasoning-on Planner testing with Intent 06 did not justify enabling reasoning globally:
- Qwen3.5 9B over-reasoned and returned AMBIGUOUS after producing roughly 8K output tokens.
- Qwen3.8 27B exhausted the 600-second wall clock without producing a usable plan.
- Qwen3.6 35B produced a usable plan, but the extra reasoning cost was large and still introduced a false prerequisite.

Conclusion: reasoning should remain a model/role-specific qualification variable, not a global default.

## Test packets

### Packet A — simple
Configurable report-title change.

### Packet B — medium
Batch CSV export.

### Packet C — hard
Cooperative job cancellation across repository, queue, worker, service, and API boundaries.

### Packet D — contextual storage
A deliberately noisy, harder intent for an always-aware assistant storage backend.

Packet D intentionally included many future-system details that were outside the bounded objective: Home Assistant, cameras, Alexa, Toyota controls, smart glasses, VR dashboards, facial recognition, alarms, weather, and reasoning-model selection.

The actual bounded goal was only the backend storage component.

The Planner-produced Packet D plan contained a plausible but important defect: Task 1 assumed that General Intent already contained a storage-engine preference. The source intent explicitly stated that no storage engine was preselected and that choosing the implementation approach was part of the bounded engineering work.

This made Packet D a strong Governor discriminator: a Governor had to independently compare the plan against original intent rather than merely summarize or approve a plausible-looking plan.

## Qwen3.8 27B result

Candidate: `qwen3.8:27b-32k-compare`  
Configuration: 32K context, 8K max output, reasoning off.

Observed behavior across the four packets:

- Packet A: correct approval, bounded output, no major invention.
- Packet B: correct approval and preservation of the important implementation constraints.
- Packet C: correct approval while preserving the architectural intent behind cooperative cancellation.
- Packet D: correctly detected the Planner's false storage-preference prerequisite and blocked the flawed plan.

The main residual weakness is formatting/semantic discipline: on easier packets it can still restate some task content instead of limiting guidance entirely to context that is missing from the task itself.

Operationally, the concise prompt reduced Qwen3.8 Governor runtime into roughly the 70–90 second range per packet in v7, far below the roughly 200-second-class behavior seen under earlier prompt versions.

## Qwen3.5 9B result

Qwen3.5 remained attractive for speed but was not reliable enough on the harder Governor conditions.

- Packet A: substantively correct decision, but guidance repeated task content.
- Packet B: correct decision, but poor intent extraction; much of the task specification was pushed into ALL guidance.
- Packet C: unusable output consisting essentially of only `ALL`.
- Packet D: approved a plan that should have been blocked and failed to independently catch the plan/intent conflict.

Its failure pattern is directly relevant to the Governor role: it degraded when the job required preserving useful intent across bounded tasks and independently detecting plan drift.

## Other notable v7 observations

- Muse Glimmer caught the central Packet D conflict very well, but runtime was extremely high.
- North Mini Code also caught the Packet D problem and was operationally faster than Muse.
- Laguna XS noticed the issue but added unsupported legal/escalation interpretation.
- Qwen3.6 35B detected the false prerequisite but incorrectly treated storage-engine selection as a protected legal decision.
- Qwen3.6 27B, Qwen3-Coder 30B, GPT-OSS 20B, and Gemma4 12B did not reliably catch the Packet D plan/intent conflict.
- Granite4.2 30B and Nemotron 3.5 Lightning 30B did not produce reliable Governor results under the current runtime/prompt path and should be treated as runtime/compatibility failures rather than substantive Governor judgments.

## Current Governor candidate

Qwen3.8 27B, reasoning off, is the current Governor candidate for the next stage.

The basis is consistency rather than isolated quality:
- it handled the simple, medium, and hard valid plans correctly;
- it independently rejected the deliberately flawed Packet D plan;
- it avoided the severe latency of the strongest slower alternatives;
- it remained substantially more reliable than Qwen3.5 9B on the harder cases.

This is a working role assignment for continued qualification, not a permanent exclusion of other models.

## Benchmark lessons

1. A conversational role prompt that explains why the Governor exists performs better operationally than a long enforcement contract.
2. Hard tests need plausible Planner mistakes, not merely larger plans.
3. Packet D should remain in future Governor regression testing.
4. Reasoning-on should not be enabled by default; it must demonstrate role-specific value.
5. Governor evaluation must check both decision correctness and whether extracted intent is genuinely missing context rather than rewritten task instructions.
6. Deterministic software should preserve the original Planner plan and attach Governor guidance; the Governor should never be relied on to reproduce the plan faithfully.
