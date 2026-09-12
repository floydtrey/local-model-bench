# Benchmark Lab V2 Effective Configuration

**Status:** BL-4 construction contract

**Model execution:** not required

## Purpose

A benchmark score is only comparable when behavior-bearing settings are known before execution. Benchmark Lab V2 therefore separates:

1. a canonical benchmark configuration request;
2. runtime/model identity;
3. provider/backend adapter resolution; and
4. the sealed EffectiveRuntimeConfig actually assigned to a trial.

No scored V2 trial may inherit an unknown behavior-bearing provider default after its TrialIdentity has been sealed.

## Canonical configuration

The canonical request uses schema:

`benchmark-lab-runtime-config:v3`

It records provider-neutral intent in three areas.

### Generation

Required explicit values:

- context target;
- maximum output tokens;
- response-format mode/schema.
- reasoning mode and optional effort.

Reasoning is never inherited from the provider. `enabled` records deliberate use,
with an explicit effort when the runtime exposes one; `disabled` records deliberate
suppression; and `unsupported` records that the selected artifact has no mapped
reasoning control. An effort is valid only with `enabled`.

Lab-owned defaults, when omitted, are materialized into the sealed configuration rather than left to the provider:

- temperature `0.0`;
- seed `42`;
- top-p `1.0`;
- top-k `null`;
- repeat penalty `null`;
- stop list `[]`.

The EffectiveRuntimeConfig records exactly which defaults were applied.

### Execution

Required explicit values:

- request timeout;
- model residency policy;
- network policy.

Lab-owned defaults:

- retries `0`;
- retry delay `0`;
- concurrency `1`.

These values matter to reliability, latency, and resource comparisons and therefore cannot remain implicit.

### Tool surface

Every configuration explicitly records:

- tool-surface ID;
- ordered tool IDs;
- maximum tool calls;
- exact tool-schema SHA-256 or null when there are no tools.

Strict tool-enabled comparisons require an exact tool-schema digest.

## Adapter resolution

Provider/runtime adapters translate the canonical settings into the exact request or launch configuration their backend will consume.

The adapter supplies:

- `adapter_id`;
- resolution status: `exact`, `degraded`, or `unresolved`;
- the fully materialized backend/provider request settings;
- any deviations from the canonical request.

This resolved request is stored inside the sealed EffectiveRuntimeConfig.

Benchmark Lab does not accept an adapter label such as `ollama` as proof that a setting was honored. The adapter implementation and later capability qualification must demonstrate that the backend actually consumes the sealed settings.

## Strict versus exploratory mode

### Strict

Use for comparable scored qualification runs.

Strict mode rejects:

- degraded or unresolved adapter translation;
- any adapter deviation;
- unknown tool schema for a tool-enabled trial;
- a requested context larger than a known model-declared limit;
- missing required behavior-bearing settings;
- unknown configuration fields that could be typos.

### Exploratory

Use when investigating a model/runtime that cannot yet satisfy the exact shared contract.

Exploratory mode may preserve a degraded adapter mapping or an over-limit requested context, but the deviations are sealed into the configuration. Those results must not be silently pooled with strict apples-to-apples scores.

## Case-specific configuration

A RunManifest may contain multiple EffectiveRuntimeConfigs.

Each TrialIdentity binds:

- one BenchmarkInput;
- one exact case ID;
- one exact EffectiveRuntimeConfig;
- one trial ordinal/repeat group;
- one comparison layer.

This is deliberate. A JSON-structured case and a free-text repair case may require different response-format or output settings. Those differences are legitimate only when they are explicit before execution.

The runner must not perform a hidden V1-style merge of case options into model options after the manifest is sealed.

### Reusing a presealed campaign configuration

`ConfigurationBinding` normally derives an EffectiveRuntimeConfig logical ID from
the configuration profile ID. A campaign that seals its configuration matrix
before execution may instead supply both `effective_logical_id` and
`expected_effective_config`. The runner resolves the configuration under that
predeclared logical ID and blocks before model execution unless the resulting
reference exactly matches the expected content-addressed identity.

The profile ID still selects the configuration required by a benchmark case; it
does not replace the separately sealed configuration identity.

## Relationship to provider defaults

V1 allowed some defaults to be supplied inside provider code or by the provider process itself. That remains valid historical behavior for V1 reproduction.

V2 does not treat those historical defaults as qualification-grade evidence. A V2 adapter must expose the exact effective provider request/launch settings or mark the resolution degraded/unresolved.

## BL-4 acceptance boundary

The construction layer is complete when deterministic tests demonstrate that:

- required settings cannot disappear into provider defaults;
- lab defaults become explicit sealed values;
- behavior changes change the EffectiveRuntimeConfig digest;
- strict mode rejects degraded mappings;
- exploratory mode preserves deviations;
- each planned trial can bind its exact case-specific configuration.

Actual Ollama/llama.cpp/model execution is not required to implement this contract. Provider-specific adapter qualification happens before scored model campaigns.
