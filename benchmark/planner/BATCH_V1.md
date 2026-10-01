# Planner Screening Batch v1

This batch supports staged Planner candidate screening. Round 1 used intents 01-02. The current runner default is Round 2: intents 03-05 (simple, medium, hard plan-quality cases).

Frozen inputs:
- `benchmark/planner/ROLE_PROMPT.txt`
Round 1 inputs:
- `benchmark/planner/intent-01-cli-time-filter.md`
- `benchmark/planner/intent-02-webhook-retry-policy.md`

Round 2 inputs:
- `benchmark/planner/intent-03-config-default.md`
- `benchmark/planner/intent-04-batch-export.md`
- `benchmark/planner/intent-05-job-cancellation.md`

Candidate roster:
- `benchmark/planner/candidates.csv`

Runner:
- `benchmark/run-planner-batch.cmd`
- `benchmark/run-planner-batch.ps1`

## Result layout

The normal result surface is intentionally small:

```text
local-state/role-qualification-v1/planner-screen-v1/
  intent-01/ ... existing Round 1 results
  intent-02/ ... existing Round 1 results
  intent-03/
    <model>.md
    summary.csv
  intent-04/
    <model>.md
    summary.csv
  intent-05/
    <model>.md
    summary.csv
```

Each model Markdown file contains only the model name and its final Planner response.

Each `summary.csv` records:
- model ID
- runtime
- reasoning setting
- advertised model context, when Ollama reports it
- configured context
- effective loaded context
- total wall-clock seconds
- input tokens
- output tokens
- total tokens
- output tokens divided by whole-run wall time
- model size in bytes
- terminal condition
- UTC timestamp

The output-token rate is deliberately named `overall_output_tok_per_sec`: it is not pure generation speed because wall time includes model/runtime overhead and both benchmark turns.

## Internal evidence

The existing single-run machinery still performs its diagnostic/evidence work in a temporary scratch directory. The batch runner does not copy that transport/debug clutter into the comparison result folders. Scratch data is removed after extraction.

## Resume behavior

Use `-Resume` to continue a partial long-running batch. A model/intent pair is skipped only when both its Markdown output and its summary row already exist. Summary rows are replaced by model ID rather than duplicated when a run is repeated.

## Candidate configuration

`candidates.csv` columns:

```text
model_id,file_name,context_window,max_tokens,thinking_capable,reasoning_effort
```

`file_name` must be Windows-safe and is used for the model's `.md` result file.

The batch runner temporarily writes the native Ollama provider entry required by the pinned DSH/plugin combination, then restores the original `~/.dsh/settings.yaml` in a `finally` block.

Flash-Next and other special runtimes are not part of this native-Ollama batch and should be run separately.
