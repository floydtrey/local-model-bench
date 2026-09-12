# Benchmark Lab Multi-Runtime Tool Interface Plan

## Status

Accepted implementation direction after the first live L2 tool-harness smoke test.

This document defines the architecture boundary for comparing a model across multiple runtime/parser/harness combinations without weakening Benchmark Lab's existing authority, evidence, containment, or deterministic evaluation controls.

## Problem

The first live `read-only-evidence-answer` L2 smoke run demonstrated that a model can select the semantically correct tool and arguments while failing a provider-specific structured tool-call transport.

Observed example:

- model: Qwen2.5-Coder 7B
- intended operation: `read_file("facts.txt")`
- semantic selection: correct
- provider/runtime: Ollama native chat tools
- observed provider result: tool-shaped JSON in ordinary assistant content
- observed structured `message.tool_calls`: absent

This must not be collapsed into a single "model cannot use tools" result.

## Core invariant

Benchmark Lab owns the experiment.

The bounded tool harness owns authority.

The deterministic evaluator owns task correctness.

Runtime, parser, and compatibility layers are measured execution variables.

External runtimes or agent frameworks MUST NOT acquire authority merely because they can parse a model-produced tool request.

## Stable boundary

The provider-neutral boundary remains the existing normalized `ToolCall` contract used by BL-6.

Conceptually:

```text
TaskDefinition
    |
ModelInvocation
    |
Runtime / parser / compatibility adapter
    |
RawInteraction evidence
    |
Normalized ToolCall
    |
BL-6 bounded authority
    |
Tool execution
    |
ToolResult evidence
    |
Model terminal response
    |
Deterministic evaluator
```

No runtime-specific parser may bypass BL-6 or directly execute workspace actions.

## Execution interface identity

Every tool-enabled qualification should identify the execution interface independently from model identity.

An execution interface identity describes at least:

- runtime/backend kind;
- runtime evidence reference;
- model evidence reference;
- adapter identifier;
- tool-call transport mode;
- parser identifier and parser mode;
- whether parsing is provider-native, model-aware, prompt-based, or unavailable;
- raw interaction evidence policy;
- normalized tool-call contract;
- whether malformed calls fail closed;
- whether direct tool execution by the backend is forbidden.

The execution interface is a measured variable. It is not part of durable model identity.

## Required measurement dimensions

Tool-enabled results must preserve separate dimensions for:

1. semantic tool selection;
2. argument correctness;
3. protocol/parser compatibility;
4. end-to-end task success.

These dimensions are independent of ordinary deterministic evaluator scoring and must not silently overwrite it.

Performance/resource measurements remain separate:

- cold load/startup time;
- warm-resident task time;
- total wall time;
- retries;
- tokens/sec where available;
- CPU;
- system RAM;
- VRAM;
- GPU utilization;
- GPU power;
- estimated energy;
- infrastructure/driver failures.

## Runtime/parser matrix

The lab should be able to compare combinations rather than only models.

Initial target matrix for Qwen2.5-Coder:

```text
Qwen2.5-Coder 7B
    Ollama native tools
    llama.cpp model-aware function calling
    vLLM + Hermes parser
    SGLang + qwen25 parser
    optional prompt-based compatibility adapter
```

Other models use only relevant combinations. A model is not required to be forced through every provider-specific protocol.

## Fairness rule

Fairness means:

- same underlying task;
- same allowed authority;
- same workspace scope;
- same evidence requirements;
- same deterministic evaluator;
- same resource accounting policy;
- explicitly documented execution interface.

Fairness does not require every model to use the same provider-specific serialization protocol.

## Parser safety policy

A compatibility parser MUST:

- produce the same normalized `ToolCall` shape expected by BL-6;
- preserve raw model/provider evidence;
- identify the parser/adapter that produced the normalized call;
- reject malformed or ambiguous calls rather than guess;
- never reinterpret arbitrary assistant prose as an executable tool call;
- never execute a tool directly;
- never expand workspace authority;
- never hide provider/runtime incompatibility.

Prompt-based tool calling may be tested, but only as an explicit execution-interface mode. It must not be silently enabled as a fallback.

## External framework policy

External runtimes/frameworks may be:

1. used intact as an external backend;
2. wrapped behind an adapter;
3. selectively reused when a small component is uniquely valuable;
4. used only as an independent comparison harness;
5. rejected when overlap or authority ownership is excessive.

The current intended disposition is:

- Ollama: retain as native baseline;
- llama.cpp: first alternate backend to qualify;
- vLLM: canonical model-aware parser/server control where practical;
- SGLang: additional model-aware server control where useful;
- Qwen-Agent: study/wrap parser/function-call layer only if needed;
- OpenHands: independent comparison harness, not ACL/BL authority owner.

## First implementation sequence

### Slice MI-1 — execution-interface evidence foundation

Add a provider-neutral execution-interface descriptor and deterministic sealed evidence helper. No runtime behavior changes.

Acceptance:

- model, runtime, parser, and adapter identities are separately represented;
- malformed modes fail closed;
- direct backend tool execution is explicitly forbidden by the contract;
- existing Ollama behavior is unchanged.

### Slice MI-2 — bind execution interface to L2 execution

Attach the execution-interface reference to L2 execution bindings and traces.

Acceptance:

- every tool-enabled run identifies its exact execution interface;
- old evidence remains readable;
- no authority moves outside BL-6.

### Slice MI-3 — compatibility observations

Record the four independent dimensions: semantic selection, argument correctness, parser/protocol compatibility, and end-to-end success.

Acceptance:

- an Ollama serialization failure can coexist with evidence of correct semantic tool selection;
- the ordinary evaluator verdict is not rewritten by compatibility metadata.

### Slice MI-4 — alternate backend adapter

Implement the first alternate backend, initially llama.cpp, behind the normalized model-turn boundary.

Acceptance:

- same L2 task and BL-6 authority;
- raw provider response preserved;
- normalized tool calls identical in shape to existing BL-6 input;
- no loose JSON/prose execution fallback.

### Slice MI-5 — cross-interface reporting

Report results by `model × runtime × parser/interface` with cold/warm and telemetry dimensions.

## Do not do

- Do not add a loose JSON parser to the Ollama adapter.
- Do not silently reinterpret assistant text as tool calls.
- Do not change BL-6 workspace authority.
- Do not copy an entire external framework into this repository.
- Do not score provider compatibility as identical to semantic model capability.
- Do not eliminate Qwen2.5-Coder based on the preserved Ollama smoke result.
- Do not run the full L2 campaign until at least one alternate execution interface is qualified.
