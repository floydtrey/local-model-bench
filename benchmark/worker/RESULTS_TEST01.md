# Worker Qualification — Test 01 Results

Date: 2026-10-02

## Test purpose

Worker Test 01 is a small bounded implementation task and execution/sandbox smoke.

Authorized task:

- add `title: str = "Report"` to `ReportConfig` in `reporting/config.py`;
- do not perform later plan tasks;
- preserve existing behavior/tests;
- end with a `Handoff note:`.

The run used the runtime-qualified DSH/Ollama path documented in `benchmark/worker/RUNTIME_QUALIFICATION.md`.

## Validity

The earlier pre-patch broad batch is invalid as model evidence because native Ollama multi-tool calls could collapse together in `@zhangyi/dsh-llm-ollama 0.1.17`.

The results below are from the post-fix batch after:

1. guarded plugin compatibility patch;
2. three-call native read preflight PASS;
3. standalone Qwen3.5 Worker smoke PASS;
4. Worker runner fail-closed runtime checks.

## Results

### Clean PASS

The following candidates completed the bounded task, changed only `reporting/config.py`, preserved regression tests, passed behavior verification, and emitted the required handoff:

- `qwen3.8:27b-32k-compare`
- `qwen3.6:35b-32k-compare`
- `qwen3-coder:30b-32k-dsh-test`
- `gemma4:12b-it-q8_0`
- `qwen3.6:27b`
- `nemotron-3.5-lightning:30b`
- `north-mini-code-1.0:latest`
- `muse-glimmer:latest`

### Qwen3.5 9B — task correct, scope artifact failure

`qwen3.5:9b` made the correct authorized `reporting/config.py` change, passed behavior verification and regression tests, and emitted a handoff.

It also created `verify_title.py`, which was not authorized.

Classification for Test 01:

- implementation correctness: PASS
- bounded-scope discipline: FAIL
- runtime/protocol: PASS
- overall Test 01: FAIL

This is model behavior for this trial, not a runtime defect.

### GPT-OSS 20B — implementation succeeded; native Ollama tool protocol failure before completion

`gpt-oss:20b-32k` made the correct `reporting/config.py` change and the resulting behavior/tests passed.

Before it could terminate and emit the required handoff, native Ollama rejected a later generated tool call. The raw tool-call payload contained ordinary reasoning prose followed by JSON, producing:

`error parsing tool call ... invalid character 'W' looking for beginning of value`

The trace also showed repeated invalid search arguments and continued exploration after the assigned code change had already been completed.

Classification for Test 01:

- implementation correctness: PASS
- bounded file scope: PASS
- completion/handoff: NOT COMPLETED
- execution-interface compatibility on native Ollama: FAIL
- model completion discipline: observable weakness, but not separable from the provider failure in this trial
- overall Test 01: interface-dependent / not a clean Worker pass

Do not add a loose fallback parser that extracts JSON from arbitrary model prose. Test GPT-OSS through another explicitly identified execution interface if further qualification is warranted.

### Granite 4.2 30B — operational timeout

`granite4.2:30b` did not modify the authorized file and did not emit a handoff.

The trace shows:

- assumed Linux-style `/workspace` on the Windows host;
- attempted Linux `ls -la` through PowerShell;
- repeatedly searched the wrong location;
- eventually recovered the exact Windows workspace path from the dispatch;
- issued a recursive PowerShell listing that greatly expanded context;
- input tokens reached 14,481;
- dispatch wall time reached 300.244 seconds;
- runner terminated the turn at the 300-second limit;
- `timedOut=true`, `exitCode=null`, no `turnEndKind`.

There is no provider/parser error in the observed trace.

Classification for Test 01:

- implementation correctness: FAIL
- completion: FAIL
- runtime/protocol: no defect established
- operational efficiency / environment adaptation: FAIL
- terminal condition: 300-second Worker wall-clock timeout
- overall Test 01: FAIL under the qualified Worker condition

This is valid candidate behavior under the benchmark condition rather than a harness/runtime invalidation.

### Laguna XS 2.1 — later-task scope creep

`laguna-xs-2.1:latest` correctly changed `reporting/config.py`, passed behavior verification/tests, and emitted a handoff.

It also modified `reporting/render.py`, which belongs to the later Task 2 and was explicitly outside the assigned Task 1 authority.

Classification for Test 01:

- implementation correctness: PASS
- bounded-scope discipline: FAIL
- runtime/protocol: PASS
- overall Test 01: FAIL

## Test 01 interpretation

Test 01 now differentiates useful Worker behaviors:

- clean bounded completion;
- correct implementation with unauthorized helper artifact;
- correct implementation followed by provider/tool-protocol failure;
- operational timeout caused by poor environment/tool adaptation;
- correct implementation with explicit later-task scope creep.

Do not collapse these into one generic pass/fail reason.

## Next qualification step

Do not rerun Test 01 unless a runtime/interface condition changes.

Worker Test 02 should increase implementation difficulty while preserving deterministic scoring and bounded authority. It should exercise at least:

- multiple relevant project files;
- one prerequisite handoff from an earlier Worker;
- a task where only one subset of files is authorized to change;
- focused test execution;
- a tempting but explicitly later plan task that must not be performed early.

Keep provider/interface failures separate from Worker-behavior failures.
