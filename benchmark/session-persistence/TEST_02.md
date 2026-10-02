# Session Context Test 02 — Two Sessions vs One Role-Switched Session

## Purpose

Measure the context/token cost and role-contamination behavior of two architectures using the same local model:

1. **Two-session architecture:** a persistent Worker session and a persistent Reviewer session.
2. **Single-session architecture:** one persistent session whose role is temporarily switched Worker → Reviewer → Worker.

Test 01 already proved that separate DSH sessions survive model unload/reload without cross-session leakage. Test 02 measures whether separate role sessions keep the Worker's resumed context smaller and cleaner, and what that costs in total tokens.

## Model

`qwen3.5:9b`, 32K context, 8K max output, reasoning off.

## Shared fixture

Both architectures use `benchmark/session-persistence/context-fixture-02.md`.

## Sequence

### Architecture A — two persistent sessions

- A1: create Worker session with fixture and worker marker.
- A2: Worker completes bounded checkpoint 1.
- R1: create separate Reviewer session with the same fixture plus artifact 1.
- A3: resume Worker with review outcome 1; verify Worker identity.
- A4: Worker completes bounded checkpoint 2.
- R2: resume Reviewer with artifact 2; do not resend the full fixture.
- A5: resume Worker with review outcome 2; verify Worker identity.

### Architecture B — one role-switched session

- S1: create Worker session with the same fixture and worker marker.
- S2: Worker completes bounded checkpoint 1.
- S3: in the same session, temporarily switch to Reviewer and review artifact 1.
- S4: switch back to Worker with review outcome 1; verify Worker identity.
- S5: Worker completes bounded checkpoint 2.
- S6: temporarily switch to Reviewer again and review artifact 2.
- S7: switch back to Worker with review outcome 2; verify Worker identity.

## Measurements

For every turn record:
- DSH session id
- input tokens
- output tokens
- wall time
- terminal condition
- final text

Derived measurements:
- Worker return input tokens after review cycle 1
- Worker return input tokens after review cycle 2
- total input/output tokens for each architecture
- cumulative wall time
- whether the Worker response contains Reviewer-only marker text
- whether each session retained the required role marker

## Interpretation

The test does **not** assume that two sessions use fewer total tokens. A separate Reviewer session may require its own initial context. The important questions are:

1. Does the Worker session stay materially smaller when Reviewer history is kept out of it?
2. Does the single-session architecture accumulate Reviewer instructions/history on every return to Worker?
3. Does either architecture show role contamination?
4. What is the total token tradeoff across repeated role switches?

A successful result provides measured architecture data; it does not require either architecture to be cheaper overall.
