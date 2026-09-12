# Construction Lab v1

## Purpose

Construction Lab moves Benchmark Lab from isolated tool-transport qualification to real bounded project work. Candidate models receive disposable project copies and may inspect, create, modify, delete, and test project files through a constrained authority surface.

The design goal is to measure practical worker behavior without granting the model general host authority.

## Fixture source

Fixture corpus branch:

`construction-lab-fixtures-v1`

Pinned fixture commit for v1:

`429ef04722093bf9f355a48b4d236a119f3b03e6`

The branch contains only the disposable project corpus plus `construction-manifest.json`. It is intended to be cloned separately for each candidate model. Acceptance test files are readable but not writable; the removal task may delete only the specifically obsolete test file named by its bounded scope.

Initial tasks:

1. `repair-calculator-average` — diagnose and repair a regression.
2. `add-json-report` — implement a requested feature, including an authorized new file if useful.
3. `remove-legacy-mode` — remove obsolete code and tests using real file deletion.

All fixtures use the Python standard library only.

## Candidate isolation

`tools/construction/prepare-construction-workspaces.ps1` creates one independent clone per model under:

`local-state/construction-lab/workspaces/<model>/`

Every clone must resolve to the pinned fixture commit before it is accepted. A mismatched clone is deleted and the preparation step fails closed.

Models are not given Git as a tool. Repository metadata remains present only for operator-side provenance and post-run inspection.

## Construction authority surface

Construction Lab adds an additive surface rather than changing historical BL-6 behavior:

- `read_file(path)`
- `write_file(path, content, expected_sha256)`
- `delete_file(path, expected_sha256)`
- `run_command(command_id)`

The file tools use exact predeclared relative paths. Existing-file writes and deletions require the current SHA-256 returned by `read_file`. Traversal, absolute paths, `.git`, link-like paths, and paths outside the workspace remain forbidden.

`run_command` never accepts shell text or arbitrary argv from the model. The model supplies only an opaque task-authorized `command_id`.

## Test execution containment

The tower runner defaults to Docker-backed command execution.

The predeclared test command runs in a container with:

- `--network none`
- CPU limit
- memory limit
- PID limit
- read-only container filesystem
- a small isolated `/tmp`
- project directory mounted read-only
- no implicit image pulls during a benchmark (`--pull never`)

The model therefore cannot turn modified Python source into a host-level command escape through the test runner. All project mutations still occur through the Construction Lab file authority.

`--command-backend host` exists only as an explicit operator override for trusted diagnostic use. It is not the benchmark default.

## Model interaction

`tools/construction/run-construction-task.py` performs a real multi-turn interaction through one explicitly selected execution interface:

1. provide task prompt, exact authorized paths, tool schemas, and authorized command IDs;
2. normalize only formats permitted by the content-addressed exact-model transport profile;
3. execute calls through `ConstructionWorkspace`;
4. return real file contents, SHA-256 values, mutation results, and test stdout/stderr to the model;
5. allow the model to iterate until it sends a terminal response or reaches a hard limit;
6. independently rerun the task acceptance commands after the model stops;
7. compare initial/final snapshots and enforce task acceptance gates.

Ollama remains locked to the `openai_native` profile. Alternate OpenAI-compatible
providers require an explicit profile and are recorded as a distinct execution
interface. Ordinary assistant prose is never promoted to an executable call.

The initial compatibility profile for Qwen2.5 accepts only whole-response native
calls, exact `<tool_call>`, `<function_call>`, or `<tools>` blocks, fenced JSON, or
plain JSON. The recovered name must identify an offered tool and the arguments must
pass that tool's JSON Schema. Malformed, ambiguous, oversized, excessively nested,
unknown-model, unknown-tool, and no-tools calls fail closed as protocol failures.
The normalizer never executes tools or expands Construction Lab authority.

`tools/construction/run-construction-llama-cpp.ps1` owns one loopback-only
`llama-server` process for an alternate-interface batch. It generates a random
process-scoped API key, hashes the executable and every GGUF shard, captures the
server version and redacted launch arguments, runs the selected task battery, and
stops only the process it created.

## Evidence captured

Each task run stores:

- initial snapshot;
- baseline verification result;
- every provider request;
- every raw provider response;
- the content-addressed provider/parser/profile/tool-schema identity;
- llama.cpp executable and model-shard provenance for managed runs;
- every normalization decision, source format, and validation error;
- normalized tool calls and tool results;
- final snapshot;
- independent assessor verification;
- aggregate provider token/duration counts;
- wall-clock time;
- authority-denial count;
- number of test invocations;
- changed paths;
- acceptance checks and final pass/fail result.

When a task is launched through `tools/construction/run-construction-batch.ps1`, the batch also stores `telemetry.csv` beside the task evidence. The sampler records UTC timestamp, total CPU utilization, available/total physical memory, NVIDIA GPU utilization, VRAM usage, GPU power draw, and GPU temperature every two seconds when those host metrics are available. Telemetry is observational only and is not part of the model authority path or acceptance decision.

Output root:

`local-state/construction-lab/runs/`

## Acceptance

v1 acceptance requires all of the following:

- required assessor commands pass;
- required deleted paths are actually missing;
- changed-path count stays inside the task budget;
- no authority-denied tool attempts occurred;
- the model reaches a normal terminal response rather than a runner/output/turn limit.

A model may make ordinary coding mistakes, run failing tests, repair its work, and continue. Those attempts are preserved as efficiency and reliability evidence rather than hidden.

## Batch behavior

`tools/construction/run-construction-batch.ps1` runs the selected task battery sequentially for each candidate. With Ollama, the model stays resident across that model's tasks and is unloaded before the next candidate. A managed llama.cpp wrapper owns residency for its complete batch. This captures practical warm-task throughput while preventing candidates from competing for VRAM.

The batch emits JSON and CSV comparison evidence and attaches per-task runtime telemetry when the sampler can collect it. Telemetry collection is best effort; missing host metrics never grant authority, change model inputs, or manufacture a benchmark pass/fail.

## Review bundles

`tools/construction/create-construction-review-bundle.ps1` creates an operator review archive containing each selected model workspace's Git status, tracked diff, complete changed-file list, baseline/current copies for tracked changes and untracked files, and the latest run evidence for the selected tasks. Deleted files are represented explicitly, and files that did not exist in the fixture baseline are marked as new rather than silently omitted.

The default archive is:

`construction-lab-review-bundle.zip`

The review bundle is operator-side evidence only; models never receive Git or archive access through this utility.

## Non-goals for v1

Construction Lab v1 does not:

- expose arbitrary PowerShell, CMD, Bash, or Python execution to the model;
- grant the model Git operations;
- grant network access to model-authored code;
- permit filesystem access outside the selected disposable project;
- change historical BL-6 evidence semantics;
- silently or heuristically parse arbitrary assistant prose.

Future versions can add larger projects, hidden assessor suites, bounded Git operations, dependency installation fixtures, or more complex build commands after this surface has been qualified.
