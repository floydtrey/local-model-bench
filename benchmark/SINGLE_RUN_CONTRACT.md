# Role Qualification v1 — single-run contract

One invocation runs exactly one fresh DSH session.

## Inputs

Required:

- `candidate_patch` — DSH model/provider configuration for one candidate.
- `runtime_kind` — provider/runtime family. v1 uses persistent native `ollama`; alternate providers such as Flash-Next are added only when qualified.
- `model_id` — exact runtime model ID/tag used for prerequisite verification.
- `expected_context_window` — expected effective Ollama context for verification; it does not control the request.
- `role_prompt` — exact role prompt text file.
- `package` — exact intent/package text file.
- `output_dir` — empty or new directory for this run.

Optional test-only input:

- `wall_clock_seconds` — defaults to 600. May be lowered only for launcher qualification tests.

## Execution

The runner must:

- use the isolated Role Qualification v1 DSH overlay;
- create one fresh durable DSH session;
- send the role prompt as turn 1;
- capture that session's native DSH id;
- resume that exact session and send the package as turn 2;
- require the persistent candidate runtime named by `runtime_kind` to be reachable and verify `model_id` is available;
- enforce one outer wall-clock deadline covering runtime startup plus DSH execution;
- never retry the model request automatically;
- never score, rewrite, summarize, warn, or otherwise alter the model run;
- never start, stop, or reconfigure the persistent Ollama service;
- verify the effective Ollama context after the run and reject a mismatch as runtime configuration error.

## Outputs

The output directory must preserve:

- `role-prompt.txt` — exact bytes used for the role prompt;
- `package.txt` — exact bytes used for the intent/package;
- `candidate-patch.yml` — exact candidate configuration used;
- `session` — native DSH session evidence containing both turns;
- `role-turn.jsonl` / `role-turn.stderr.txt` — headless evidence for role assignment;
- `intent-turn.jsonl` / `intent-turn.stderr.txt` — headless evidence for the resumed intent turn;
- `reasoning.txt` — reasoning extracted after the run when present;
- `final.txt` — final assistant text extracted after the run when present;
- `observations.json` — passive post-run observations only;
- `run.json` — factual run metadata.

`run.json` records at minimum:

- start time;
- end time;
- total wall-clock seconds;
- DSH exit code when available;
- terminal condition: `completed`, `wall_clock`, or `runtime_error`;
- native DSH stop reason when available;
- candidate model/provider identity.

## Boundary

The only run-time benchmark guard in v1 is the outer wall clock.

All other guardrail logic is observational and runs only after model execution has ended.
