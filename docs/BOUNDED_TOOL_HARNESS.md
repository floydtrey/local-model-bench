# Benchmark Lab V2 — Neutral Bounded-Tool Harness V1

**Construction task:** BL-6

**Status:** implementation contract; real model execution remains disabled during construction

## Purpose

The BL-6 harness provides a deliberately small, Benchmark-Lab-owned tool loop between raw prompt-only model evaluation and the future ACL system harness.

Its purpose is diagnostic isolation. A candidate that performs well without tools but poorly through this harness is showing a tool-protocol/harness-retention problem before ACL-specific authority, retrieval, dispatch, and verification are introduced.

The harness does **not** import ACL authority or ACL worker code.

## Versioned contracts

Harness version:

`benchmark-lab-bounded-tool-harness:v1`

Trace payload version:

`benchmark-lab-tool-trace:v1`

Tool surface:

`lab-bounded-files:v1`

The exact tool definitions receive `BOUNDED_FILE_TOOL_SCHEMA_SHA256`. An EffectiveRuntimeConfig used with BL-6 must bind that exact surface ID, canonical tool ordering, schema digest, and a positive `max_tool_calls` value before execution.

## Tool surface

V1 exposes exactly two tools.

### `read_file`

Input:

```json
{
  "path": "relative/path.txt"
}
```

The path must be an explicitly authorized readable file path.

Successful results include exact UTF-8 content, byte length, and SHA-256.

### `write_file`

Input:

```json
{
  "path": "relative/path.txt",
  "content": "replacement bytes encoded as UTF-8",
  "expected_sha256": null
}
```

`expected_sha256=null` means the caller expects to create a currently missing file.

When replacing an existing file, the current file SHA-256 must be supplied. A mismatch produces a deterministic `stale_write` result and no write occurs.

Writes use a temporary file, flush/fsync, and atomic replacement.

## Explicitly absent tools

BL-6 does not expose:

- shell or arbitrary process execution;
- Git operations;
- network access;
- directory enumeration;
- recursive filesystem access;
- publication/deployment;
- approval/authority tools;
- arbitrary host commands.

An unknown tool request is recorded, denied, and not executed.

## File-scope authority

The harness receives explicit relative-path allowlists for readable and writable files.

Paths are portable forward-slash relative paths. The path contract rejects:

- absolute paths;
- `..` traversal;
- dot segments;
- backslash path syntax;
- colon/alternate-stream style syntax;
- `.git` path components;
- control characters;
- link/junction path components that could redirect access outside the intended workspace.

The harness records only relative scope paths in trace evidence. The disposable absolute workspace path is intentionally not part of the trace so equivalent executions in different temporary directories can have equivalent trace identity.

Existing hard-linked files cannot be written through the tool because changing that inode could mutate data outside the declared path namespace.

## Authorization versus execution result

A tool request has two distinct outcomes.

First, the harness records a `tool_authorization` decision.

Examples of authorization denial reasons include:

- `tool_not_exposed`;
- `invalid_arguments`;
- `invalid_path`;
- `path_not_readable`;
- `path_not_writable`;
- `unsafe_workspace_path`.

A denied request is never executed. The denial is returned to the model driver as a tool result so future benchmark evaluators can distinguish:

- no authority violation;
- attempted violation followed by recovery;
- repeated authority violations.

Second, an authorized tool can still produce an ordinary execution failure such as:

- `file_missing`;
- `not_utf8`;
- `stale_write`;
- `target_exists_expected_creation`;
- `target_missing`;
- `hardlink_write_forbidden`.

Authorization failures and execution failures are therefore not collapsed into one error class.

## Provider-neutral model-turn contract

BL-6 does not call Ollama, OpenAI-compatible endpoints, llama.cpp, Pydantic AI, or any other provider directly.

A model/provider adapter is represented by a callable driver receiving a normalized `ModelTurnRequest` and returning a normalized `ModelTurnResponse`.

The request contains:

- case ID;
- model-turn ordinal;
- normalized conversation state;
- any case context-asset descriptors supplied by the future orchestration layer;
- the exact neutral tool definitions.

A response contains optional assistant content plus zero or more normalized `ToolCall` objects. A response with no tool calls is terminal and must contain assistant content.

Construction tests use deterministic fake drivers only.

## Normalized event stream

Every execution produces ordered events. Current event types include:

- `model_request`;
- `model_response`;
- `model_error`;
- `protocol_error`;
- `tool_request`;
- `tool_authorization`;
- `tool_result`;
- `limit_reached`;
- `terminal_output`.

Each event has:

- contiguous sequence number;
- event type;
- normalized payload;
- SHA-256 over the event body.

The complete event stream is stored inside a sealed V2 `tool_execution_trace` evidence record.

## Workspace evidence

The trace records both initial and final snapshots of every path in the declared read/write scope.

Each path records:

- relative path;
- `file` or `missing` state;
- SHA-256 when present;
- byte size when present.

Each snapshot also receives its own deterministic digest.

Because read results contain exact content and write requests contain exact replacement content, the event stream plus content-addressed starting fixtures is sufficient to reconstruct what the neutral harness attempted and changed.

## Trace summary

The sealed trace summary records:

- execution status;
- stop reason;
- model-turn count;
- requested tool-call count;
- authorized call count;
- denied call count;
- successful tool execution count;
- failed tool execution count;
- terminal output digest when present.

A high-level score is deliberately not produced by the harness. BL-5B evaluators consume the resulting evidence later.

## Tool-call limit

`max_tool_calls` is already part of the sealed BL-4 EffectiveRuntimeConfig.

BL-6 enforces that tool-call count locally because it is intrinsic to the neutral tool loop. If the candidate asks for another call after the sealed maximum, the extra call is not executed, `limit_reached` is recorded, and the harness returns `resource_limit`.

## BL-7 boundary — important non-claims

BL-6 does **not** yet claim to enforce the full real-task sandbox.

Specifically, BL-6 does not by itself enforce:

- wall-clock timeout;
- provider-process custody;
- child-process cleanup;
- provider/task network isolation;
- CPU/RAM/VRAM resource limits;
- execution-attempt limits outside the neutral tool loop;
- assessor-process isolation.

Those are BL-7 responsibilities.

A configuration value such as `network_policy=disabled` is therefore not qualification-grade proof that network access was actually prevented until BL-7 supplies an enforcement backend.

## Context assets

BL-6 acceptance does not define the final context-asset materialization mechanism. The synthetic stop-gate fixture uses no external context assets.

The later V2 orchestrator must materialize BL-5A content-addressed assets according to their declared delivery mode without making operational source locators part of candidate-visible behavior. Until that orchestration boundary is implemented and tested, context-asset-bearing L2 tasks are not qualification-ready merely because the tool loop exists.

## Deterministic construction tests

`tests/test_v2_tool_harness.py` validates at least:

- successful multi-turn read/write execution;
- complete normalized trace generation;
- trace validation and event digests;
- equivalent trace identity across different disposable root locations;
- traversal denial;
- unknown-tool denial;
- stale-write rejection without mutation;
- max-tool-call enforcement;
- tool-schema binding failure;
- malformed driver-result protocol failure.

These are engineering tests of the measuring instrument. They are not scored model benchmark cases.

## BL-6 stop gate

BL-6 is acceptable when a deterministic fake model can complete a disposable bounded file task through this neutral harness, the complete replayable evidence survives validation, authority violations fail closed, and the complete repository regression suite passes on both Windows and Ubuntu.

No real model call is required or permitted for this construction gate.
