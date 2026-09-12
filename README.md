# Local Model Bench

A Windows-friendly benchmark harness for running fixed JSON or Markdown prompt suites against local chat models. It processes one model at a time, writes each case immediately, resumes interrupted runs, and stays quiet unless `--verbose` is requested.

This project is independent of Worker Lab. Put it in its own folder or Git repository; it neither imports nor edits Worker Lab.

## Construction Lab repeat rounds

Round 0 evidence under `local-state/construction-lab/runs/` is immutable. Repeat
rounds use a new label, fresh fixture clones, and a separately labelled evidence
tree. The three fixture tasks, their prompts, accepted commands, and the bounded
tool authority are unchanged.

Prepare a round with the desired model order. `-Reset` may rebuild only a clone
that this script previously marked as a disposable Construction Lab workspace;
it refuses unmarked or mismatched directories. Round labels must start with a
letter or digit and may contain only letters, digits, periods, underscores, and
hyphens.

```powershell
.\tools\construction\prepare-construction-workspaces.ps1 `
  -RoundLabel "round-1" `
  -Models @("gpt-oss:20b", "qwen3.5:9b")
```

Run the same three-task battery using that exact order:

```powershell
.\tools\construction\run-construction-batch.ps1 `
  -RoundLabel "round-1" `
  -Models @("gpt-oss:20b", "qwen3.5:9b")
```

Evidence is written below `runs/round-1/`; every task gets a unique
timestamped directory, with a numeric suffix if a name collision occurs. Each
batch includes its round label, model order, task order, comparison files, and
per-task telemetry. Before making any model call, the batch verifies each clone's
marker, fixture commit, round identity, and clean starting state. Reusing a label
is allowed only with `-Reset` during preparation, and still creates new evidence
rather than overwriting prior runs.

Create a separate review bundle for that round with:

```powershell
.\tools\construction\create-construction-review-bundle.ps1 -RoundLabel "round-1"
```

This produces `construction-lab-review-bundle-round-1.zip` and refuses to
replace an existing bundle.

### Model-aware llama.cpp interface

Construction Lab supports an explicitly labeled model-aware llama.cpp
interface for models whose correct tool intent is serialized in a qualified
text transport instead of provider-native `tool_calls`. This interface is never
enabled as an Ollama fallback. It has a separate provider/profile identity,
preserves every raw response and normalization decision, validates recovered
calls against the offered JSON Schemas, and still executes exclusively through
the existing bounded Construction authority surface.

Prepare the exact model alias as a normal disposable round workspace, then use
`tools/construction/run-construction-llama-cpp.ps1`. The wrapper owns one
loopback-only server process, uses a random process-scoped API key, hashes the
server and every GGUF shard, runs the task battery, and stops only the process
it created. Native and normalized scores remain separate execution interfaces.

## Planning round 2 (current)

The current decision run is a 90-call planning and task-contract benchmark: 18 cases per model across five models. Nine independent scenarios each have a `PLAN` turn followed by a preserved-context `TASK_CREATE` turn. Context resets between scenarios and models.

| Order | Model | Runtime | Purpose |
|---:|---|---|---|
| 1 | Vera / Qwen2.5 3B Instruct Q4_K_M | managed llama.cpp | Exact Mine Tracker structured-output candidate |
| 2 | `qwen2.5-coder:7b` | Ollama | Current planning baseline |
| 3 | `deepseek-coder:6.7b-instruct` | Ollama | Repair-oriented comparison |
| 4 | `qwen2.5-coder:14b` | Ollama | Same-family scale test |
| 5 | `phi4:14b` | Ollama | Independent reasoning/planning challenger |

The nine scenarios cover crash-safe import, SQLite migration ordering, missing product decisions, authority conflict, evidence-led repair, concurrent filesystem claims, structured-provider compatibility, backward-compatible API evolution, and unattended Windows orchestration.

Vera is loaded directly from `C:\MineTrackerAI\models\qwen2.5-3b-instruct-q4_k_m.gguf`. The config pins its SHA-256 and starts a loopback-only `llama-server` with a random session API key. The harness stops only the server process it created.

After Phi-4 finishes downloading, start the complete preflight and background run:

```powershell
.\scripts\run-planning-round.ps1
```

The script validates the 90-call packet, verifies all five models, starts the run in the background, and prints the exact watcher command. The run uses [configs/planning-round-2.json](configs/planning-round-2.json) and [suites/planning-round-2.json](suites/planning-round-2.json); it does not modify the original smoke suite or results.

Every response must be an exact JSON plan or task set. When the run completes, the harness automatically writes:

- `evaluation.json` with every weighted check;
- `evaluation.csv` for filtering and Git diffs;
- `evaluation.md` with a model summary and case table.

The deterministic score measures completion, JSON contract adherence, correct ready/blocked decisions, exact requirement declaration, traceability, item identity, dependency validity, and scenario-specific semantic anchors. It intentionally does not claim to replace human review of technical judgment.

### Qwen 14B native-JSON retest

The completed 90-call run showed that Qwen 14B returned all 18 otherwise
parseable objects inside Markdown fences. A separate configuration now repeats
only those 18 cases using Ollama's native JSON mode. It does not alter the
completed run or its canonical evaluation:

```powershell
.\scripts\run-qwen14-json-retest.ps1
```

Watch the printed run path with `scripts\watch-status.ps1`. This retest keeps the
same prompt suite, seed, context, output limit, and case order so the structured
output setting is the intended variable.

### Scope-withdrawal probe

No installed comparison model is scheduled for removal. The two-case
[`scope-withdrawal`](suites/scope-withdrawal.json) probe tests whether a model can
plan and task a forward decommission of a deeply integrated, unreleased product
capability while preserving shared infrastructure and placing irreversible data
cleanup behind approval. Its all-model configuration uses native JSON for Ollama
models and leaves Vera's managed llama.cpp path unchanged:

```powershell
.\scripts\run-unattended.ps1 -Config .\configs\scope-withdrawal-all-models.json
```

This probe is prepared but intentionally separate from the Qwen 14B retest.

## Original 16 GB smoke baseline

The original config compared three model families in roughly the same local-memory class. Its completed results remain reproducible even though StarCoder2 is not included in planning round 2:

| Model | Ollama library download | Why it is in the baseline |
|---|---:|---|
| `qwen2.5-coder:7b` | 4.7 GB | Strong coding-oriented baseline |
| `deepseek-coder:6.7b-instruct` | 3.8 GB | Different family, explicitly instruction-tuned |
| `starcoder2:7b` | 4.0 GB | Different training lineage and useful contrast |

Optional stretch test: `qwen2.5-coder:14b` is a 9.0 GB download. It can fit in 16 GB system RAM at its default quantization, but Windows, the context cache, and other applications share that memory, so expect more paging or CPU inference on some laptops. Start with a 4K context, close memory-heavy applications, and add the 14B model only after the baseline works. Do not use the 20 GB Qwen 32B download on a 16 GB machine.

The size and tag checks were verified against the current Ollama library pages on 2026-08-29:

- <https://ollama.com/library/qwen2.5-coder>
- <https://ollama.com/library/deepseek-coder>
- <https://ollama.com/library/starcoder2>

Model quality depends on the suite. The baseline is intentionally a comparison set, not a claim that every included model is current best-in-class.

The included smoke benchmark has eight cases per model (24 requests across the three-model baseline): build, diagnose, two-turn repair, two-turn planning/task creation, review, and refusal. These cases verify the workflow and provide an initial behavioral comparison; they are not a substitute for a larger scored benchmark packet.

## Windows setup

Prerequisites:

- Windows 10 22H2 or newer
- Python 3.10 or newer
- Enough disk space for the models, results, and Ollama itself (about 17 GB for this baseline plus working space)

1. Install Ollama using the native Windows installer from <https://ollama.com/download/windows>. The official documentation says the installer does not require administrator rights and serves the local API at `http://localhost:11434`.
2. Open a new PowerShell window in this project.
3. Create the isolated Python environment and validate the examples:

   ```powershell
   .\scripts\bootstrap.ps1
   ```

4. Download every Ollama model in config order:

   ```powershell
   .\scripts\pull-models.ps1
   ```

   The script runs these verified commands:

   ```powershell
   ollama pull qwen2.5-coder:7b
   ollama pull deepseek-coder:6.7b-instruct
   ollama pull starcoder2:7b
   ```

   Optional 14B download:

   ```powershell
   ollama pull qwen2.5-coder:14b
   ```

5. Confirm the endpoint is reachable and every configured model is installed:

   ```powershell
   .\.venv\Scripts\python.exe -m localbench doctor --config .\configs\ollama-16gb.json
   ```

The harness itself uses only the Python standard library. Setup does not download Python packages; the editable install points the virtual environment at this source tree.

## Run a benchmark

The normal command prints nothing while requests are running. At completion it prints the result directory once.

```powershell
.\.venv\Scripts\python.exe -m localbench run --config .\configs\ollama-16gb.json
```

To watch case progress, add `--verbose`. To use files other than the config's `suites` list, repeat `--suite`:

```powershell
.\.venv\Scripts\python.exe -m localbench run `
  --config .\configs\ollama-16gb.json `
  --suite .\suites\my-repairs.json `
  --suite .\suites\my-reviews.md
```

Suite override paths are sorted by resolved path for repeatability. Models always run in the exact array order in the config, and cases run in file order. The outer loop is always model-first: all cases complete for model 1 before model 2 begins.

### Unattended/background run

```powershell
.\scripts\run-unattended.ps1
```

This launches a hidden background process and writes launcher logs under `logs/`. Actual responses and run state go directly under `results/`; the console log is not the source of truth. Prevent Windows from sleeping if the laptop is not configured to remain awake while plugged in.

The launcher also prints an exact command for an optional progress bar. Open another PowerShell window in this project and run that command, or watch the newest run automatically:

```powershell
.\scripts\watch-status.ps1
```

The bar reads `checkpoint.json`; it does not contact or slow the model. It shows completed cases, total cases, the current model/case, and the final manifest status. For a one-time text status instead of a continuously updating bar, use:

```powershell
.\scripts\watch-status.ps1 -Once
```

## Context behavior

The default is isolated context: each case sends only its own messages. No model conversation state is trusted between requests.

Preserved context is opt-in per case:

```json
{
  "id": "follow-up-2",
  "context": {"mode": "preserve", "group": "repair-session-a"},
  "prompt": "Now add the regression test."
}
```

Cases with the same group preserve successful request/assistant history within the same suite and model. Groups never cross suite or model boundaries. A failed case is not added to history, so a later turn continues from the last successful turn. On resume, history is rebuilt from saved case files before the next request.

The included smoke suite uses this behavior twice: once for a repair follow-up, and once for a `PLAN` case followed by a `TASK_CREATE` case. The task-creation prompt receives that model's saved plan and asks it to produce ordered, independently actionable briefs with scope, dependencies, acceptance criteria, and tests.

For completely explicit multi-message input, use `messages` instead of `prompt`:

```json
{
  "id": "explicit-dialogue",
  "messages": [
    {"role": "system", "content": "You are reviewing Python."},
    {"role": "user", "content": "Find the concrete defect only."}
  ]
}
```

See [suites/sample.json](suites/sample.json), [suites/sample.md](suites/sample.md), and [schemas/suite.schema.json](schemas/suite.schema.json).

### Markdown format

Each case starts with an exact level-two heading:

```markdown
## Case: unique-case-id
<!-- localbench
{"tags": ["REVIEW"], "context": {"mode": "isolated"}}
-->

Everything here becomes the prompt, including fenced code.
```

The JSON metadata comment is optional. A `localbench` JSON comment before the first case can set `suite_id`, `name`, and `defaults`; see the included Markdown sample.

## Configuration and provider abstraction

The config lists providers separately from the ordered models. Native Ollama uses `/api/chat` and records its detailed nanosecond timings, token counts, digest, quantization, parameter size, and model size when available.

For Ollama structured output, put `"format": "json"` or a JSON Schema object in
the model or case `options`. The provider sends `format` at the top level of the
Ollama chat request while keeping generation settings such as `temperature`,
`num_ctx`, and `num_predict` inside Ollama's `options` object. Invalid format
types are rejected before the request is sent.

The `openai_compatible` provider uses `/v1/models` and `/v1/chat/completions`, which supports local servers such as LM Studio and Jan:

```json
{
  "providers": {
    "local-server": {
      "type": "openai_compatible",
      "base_url": "http://localhost:1234/v1"
    }
  },
  "models": [
    {
      "id": "my-local-model",
      "provider": "local-server",
      "name": "the-model-id-reported-by-the-server",
      "options": {"temperature": 0, "seed": 42, "max_tokens": 1024}
    }
  ]
}
```

If an endpoint needs a key, set `api_key_env` to an environment-variable name. Do not put a credential value in the config. Effective configs saved with runs are also recursively redacted for common credential fields. See [configs/openai-compatible.example.json](configs/openai-compatible.example.json) and [schemas/config.schema.json](schemas/config.schema.json).

The `llama_cpp` provider owns a temporary llama-server process for one exact GGUF. It verifies an optional SHA-256 before loading, requires a loopback URL with an explicit port, creates a random in-memory API key, disables the Web UI, records model/runtime metadata, and captures a bounded server-log tail on shutdown. See the Vera provider in [configs/planning-round-2.json](configs/planning-round-2.json).

## Result layout

Every run is self-contained and safe to inspect or commit:

```text
results/
  20260829T153000Z-a1b2c3d4/
    manifest.json
    checkpoint.json
    summary.csv
    evaluation.json
    evaluation.csv
    evaluation.md
    inputs/
      config.json
      001-sample-json-....normalized.json
    models/
      001-qwen25-coder-7b-.../
        model.json
        summary.json
        unload.json
        cases/
          0001-sample-json-...--build-slugify-....json
```

- `manifest.json` records host/runtime data, input hashes, exact model/suite ordering, timestamps, and final run state.
- `model.json` captures the configured model, provider runtime version, and model metadata. Ollama supplies digest, file size, parameter size, and quantization when available.
- Each case file contains the complete sent messages/options, full assistant text, raw provider response, normalized token/timing/throughput fields, all failed retry attempts, and the terminal error when applicable.
- `summary.csv` is a flat, Git-diffable index for quick comparison. It does not replace the full JSON records.
- `checkpoint.json` names the current case and records terminal-case totals and percentage for the progress watcher.
- `evaluation.json`, `.csv`, and `.md` distinguish deterministic answer-contract results from provider transport success.

The case contract is documented in [schemas/result.schema.json](schemas/result.schema.json). Missing provider metadata is written as JSON `null`; it is never estimated. For OpenAI-compatible providers without server timing fields, throughput uses output tokens divided by client wall time and therefore includes transport overhead.

## Resuming and failure safety

Each terminal case is written to a temporary file, flushed, and atomically renamed. If the process is interrupted during a request, that one case has no terminal result and is sent again on resume. Successful or terminal-error cases are skipped.

Resume directly:

```powershell
.\.venv\Scripts\python.exe -m localbench run `
  --config .\configs\ollama-16gb.json `
  --resume .\results\20260829T153000Z-a1b2c3d4
```

Or resume in the background:

```powershell
.\scripts\run-unattended.ps1 -Resume .\results\20260829T153000Z-a1b2c3d4
```

The harness refuses to resume if the config hash, suite hashes, or deterministic suite order changed. Use `--rerun-errors` to retry cases already saved with `status: "error"`. A killed process may leave the manifest marked `running`; this is expected and does not affect resume safety.

Per-case provider failures are captured after the configured retry count and the run continues. Ctrl+C marks the run `interrupted`. An unexpected harness-level exception marks it `failed` and stores a bounded traceback in the manifest.

If all configured work is attempted but one or more cases end in error, the manifest status is `completed_with_errors` and the command exits with code 1. This makes background schedulers and CI jobs notice the run without discarding any usable results.

## Commit results for later review

Results are intentionally not ignored. Logs, virtual environments, temporary files, and launcher PID records are ignored.

For a new standalone repository:

```powershell
git init
git add README.md pyproject.toml src configs schemas suites scripts .gitignore LICENSE
git commit -m "Add local model benchmark harness"
```

After a run, inspect its size and commit the selected run:

```powershell
git add results\20260829T153000Z-a1b2c3d4
git commit -m "Add local model benchmark results"
```

Raw model output can contain sensitive text copied from prompts or generated by the model. Review prompt suites and results before pushing to a public remote. Large suites can also make Git history heavy; commit selected benchmark runs rather than every experiment.

Configured API-key values are redacted from retained HTTP and malformed-response
error bodies before those errors reach result files. Non-sensitive provider
status and response diagnostics are preserved. This does not make arbitrary
prompt or model output safe to publish; review those separately.

## Useful commands

Validate without contacting a model:

```powershell
.\.venv\Scripts\python.exe -m localbench validate --config .\configs\ollama-16gb.json
```

Give a run a stable ID (the directory must not already exist):

```powershell
.\.venv\Scripts\python.exe -m localbench run --config .\configs\ollama-16gb.json --run-id laptop-baseline-01
```

Run the automated tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Rebuild evaluation reports without contacting any model:

```powershell
.\.venv\Scripts\python.exe -m localbench evaluate --run .\results\RUN-DIRECTORY
```

Capture a non-destructive partial report while a run is active:

```powershell
.\.venv\Scripts\python.exe -m localbench evaluate --run .\results\RUN-DIRECTORY --snapshot partial-45
```

This writes three reports under `RUN-DIRECTORY\snapshots\partial-45\`. Snapshot
names are safe identifiers and existing snapshot directories are never
overwritten. Omitting `--snapshot` retains the canonical report behavior.

## Real-task validation

Prompt benchmarks screen planning and contract behavior; they do not prove that
a model can safely change a repository. Reproducible implementation tasks live in
[`validation-packets/`](validation-packets/README.md). Each task identifies an
exact archived baseline, candidate-visible scope, assessor-only tests, hard
failures, and a deterministic scoring rubric. These packets never operate on
Worker Lab or another product repository in place.

## Current Ollama references

- Windows install, requirements, model storage, and API address: <https://docs.ollama.com/windows>
- Native chat response fields: <https://docs.ollama.com/api/chat>
- Installed-model metadata: <https://docs.ollama.com/api/tags>
- OpenAI-compatible endpoints: <https://docs.ollama.com/api/openai-compatibility>
