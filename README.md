# Construction Lab Fixtures v1

Disposable, deterministic project corpus for Benchmark Lab construction testing.

This branch is intentionally project-only. Clone it independently for each candidate model so every model starts from identical bytes.

## Projects

- `projects/repair-calculator` — diagnose and repair a defect without changing unrelated behavior.
- `projects/add-report-feature` — implement a requested feature across an existing small application.
- `projects/remove-legacy-mode` — remove obsolete behavior and its tests/references while preserving supported behavior.

## Rules

- Python standard library only.
- No network access required.
- Each project has a deterministic `python -m unittest discover -s tests` verification command.
- Project source is deliberately imperfect; do not fix the fixtures on this branch.
- Benchmark Lab should clone/copy a fresh workspace per model and task.

See `construction-manifest.json` for machine-readable task definitions.
