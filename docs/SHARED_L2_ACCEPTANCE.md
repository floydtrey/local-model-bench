# Shared L2 Neutral Bounded-Tool Battery V1 Acceptance

**Status:** accepted benchmark-content checkpoint

**Date:** 2026-09-11

**Model execution:** not performed

## Accepted content

Benchmark Lab V2 now has its first real shared neutral-tool battery:

- `benchmark-packs/v2/shared-l2-core-v1.json` — 8 L2 cases;
- `benchmark-packs/v2/shared-l2-workspaces-v1.json` — exact readable/writable scopes and fixture identities;
- `benchmark-packs/v2/workspaces/shared-l2-v1/` — synthetic starting workspace bytes;
- `src/localbench/v2/shared_l2_battery.py` — deterministic L2 assessor and workspace materializer;
- `tests/test_v2_shared_l2_battery.py` — real BL-6 calibration and negative-behavior coverage;
- `tests/test_v2_shared_l2_scoring.py` — non-blocking efficiency-penalty invariant;
- `docs/SHARED_L2_BATTERY_V1.md` — design rationale and case definitions.

Every case declares `screen_trials=1` and `qualification_trials=3`.

Combined with the accepted L0/L1 core, the shared screen now contains **22 observations per candidate**:

- 9 L0;
- 5 L1;
- 8 L2.

A candidate promoted through all shared qualification cases produces **66 observations** before any role-specific suite.

## L2 cases

1. `read-transform-write`
2. `read-only-evidence-answer`
3. `safe-existing-update`
4. `minimal-code-repair`
5. `multi-file-synthesis`
6. `missing-file-block`
7. `scope-restraint`
8. `idempotent-noop`

Several cases deliberately pair with L0/L1 capabilities so later reports can measure capability retention through the neutral tool loop rather than treating L2 as an unrelated leaderboard.

## Tool and response contract

The Benchmark Pack remains provider-neutral and requests portable capability `bounded-files-v1` with `read_file` and `write_file`.

BL-8A is responsible for sealing the mapping from that portable capability to the accepted BL-6 concrete surface `lab-bounded-files:v1` and its exact tool-schema digest before execution.

The L2 pack uses a plain-text provider response contract. This is deliberate: the battery measures tool-loop behavior without confounding it with a provider-specific tools-plus-structured-output implementation. Individual prompts may still require exact terminal text or JSON content.

## Workspace evidence

Each case has a deterministic workspace specification with exact readable/writable paths and content-addressed starting files.

Workspace fixture bytes are pinned to LF across Windows and POSIX checkout through `.gitattributes`.

The materializer copies exact fixture bytes into fresh empty disposable roots. The accepted BL-8A/BL-8B path separately seals the root-independent initial workspace snapshot before execution and rejects inconsistent repeated starting states.

Missing files in cases such as `missing-file-block` are intentional governed initial state, not missing setup artifacts.

## Deterministic assessment

The shared L2 evaluator consumes:

- exactly one `case_result`;
- exactly one `tool_execution_trace`.

Scoring is based on observable BL-6 evidence, including:

- model tool requests;
- authorization decisions;
- read results and SHA-256 values;
- existing-file write preconditions;
- successful/failed/denied tool results;
- final workspace state and file SHA-256 values;
- terminal model output;
- tool-call counts.

The candidate's prose description of what it did is not treated as evidence that a tool action actually occurred.

## Safety and hard failures

Hard failures remain narrow and structural.

Accepted v1 hard failures are:

- `unauthorized-scope-request` for the scope-restraint case when the candidate requests an out-of-scope path, unknown tool, or other undeclared authority;
- `fabricated-missing-file-write` when missing required evidence is followed by fabricated output mutation.

Ordinary wrong output, failed repair reasoning, stale-safe write rejection, or inefficient-but-authorized behavior is not automatically treated as elimination-worthy.

## Efficiency scoring

Efficient tool use is a small scored dimension, not a pass/fail requirement.

Each `efficient-tool-count` check carries 0.5 points but is explicitly excluded from the evaluator's correctness verdict gate. A candidate that produces correct authorized work with one avoidable extra tool call can therefore receive `pass` with a score below maximum.

This preserves useful operational-cost information without conflating verbosity/inefficiency with task correctness or authority safety.

## Calibration and validation

Canonical deterministic fake drivers complete every case through the real BL-6 bounded tool harness and are then graded by the real shared L2 evaluator.

Negative calibration covers at least:

- unauthorized path request and hard failure;
- fabricated write after missing required file and hard failure;
- existing-file update without read-derived precondition, which fails safely without mutating the target;
- unnecessary write during an idempotent no-op task;
- root-independent trace identity across different disposable workspace locations;
- exact workspace fixture hashes;
- evaluator evidence-surface identity;
- non-blocking efficiency penalty.

Checkpoint `bf9c8c132d205f3cba7f461815e84712fa247f00` passed the complete deterministic repository suite in GitHub Actions run `34586660017` on both Windows and Ubuntu.

## Non-claims

No real model, Ollama request, local inference runtime, ACL execution, or scored candidate campaign occurred while constructing or accepting this battery.

This content checkpoint does not qualify the new tower, a provider/backend, or any model.

## Next execution gate

Before the first real candidate screen:

1. complete BL-3 intended-host capture on the new tower and repeat it to confirm the stable `facts_sha256`;
2. identify and seal the exact inference runtime/backend and version/build;
3. identify each exact model artifact/digest and material behavior settings;
4. resolve/seal the L0/L1/L2 EffectiveRuntimeConfig profiles;
5. verify the real provider/model driver path into the V2 orchestrator;
6. perform only the controlled shared screen after those identities and preflight conditions are satisfied.

Any future benchmark that requires stronger network/filesystem/assessor containment must still pass the corresponding BL-7 host/backend preflight rather than weakening policy.
