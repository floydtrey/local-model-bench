# ASSISTANT-001/v1 — Persistent Event Journal benchmark

An additive, real-project benchmark for the future Assistant. A successful Worker
can produce a reusable standard-library Python/SQLite component, not just a toy
patch. The original 23-case role battery, its CLI, prompts, evaluators and GUI are
unchanged. This is a separate campaign, not another entry silently added to Screen.

## What is delivered

- PROJECT_INTENT.md and CONTRACT.md: released requirements and explicit decisions.
- TASKS.md / packet.json: six bounded cumulative implementation tasks.
- starter/: intentionally incomplete library, CLI and public tests.
- assessor/checks.py: independent behavior tests, kept outside candidate view.
- assessor/reference/: calibration implementation, never used as model continuation.
- REVIEW_RUBRICS.md: separate model/role and artifact review criteria.
- manifest.json: frozen byte hashes for every packet file except itself.
- A new CLI using the existing V2 Ollama driver, role conversation, bounded file/test
  tools, identity/configuration records and standardized review-package writer.

| Task | Deliverable | Independent checks |
|---|---|---|
| T01 | Strict event validation and canonicalization | Field types, timestamps, UTC offsets, JSON bytes/depth, invalid values and detached copies |
| T02 | SQLite journal lifecycle and IDs | Idempotency, conflicting duplicates, restart/process-exit persistence, corrupt DB preservation and connection behavior |
| T03 | Bounded history | Ordering, tie-breaking, combined filters, pagination and time-bound semantics |
| T04 | Current-state projection | Late events, future events, exact TTL boundary, no stale resurrection, source/type isolation and replay |
| T05 | Atomic batch ingestion | Rollback, internal/existing duplicates, bounds, restart consistency and usable connection after rejection |
| T06 | CLI, tests and documentation | Real subprocess invocation, JSON output/errors, atomic JSONL import, Unicode and public/candidate tests |

A full assessment runs 79 checks. Earlier stages run only their cumulative subset.
These are acceptance checks, not 79 independent projects or model decisions.

## Safety boundary

Validation and preparation do not contact Ollama or execute candidate code.
Self-test runs only the trusted reference and deliberately mutated fixtures.
Real Worker/Tester trials and independent candidate assessment execute Python.
The file tools restrict exposed paths, but Python is **not an OS/network sandbox**.
An isolated folder is not a security boundary. Use a disposable VM for untrusted
code. `-AllowHostExecution` is an explicit acknowledgement, not sandbox enablement.
Only synthetic events and disposable databases are supplied. No production services
are contacted by the packet. The runner's Ollama connection is fixed to loopback.

## Windows: validate before a model run

From the existing checkout:

```powershell
Set-Location C:\Projects\local-model-bench-flashnext
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 -Action validate
```

No model is started. Calibrate the tests with the trusted reference, ten known
behavioral defects and the unsolved starter:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 -Action self-test
```

The launcher prefers `.venv\Scripts\python.exe`, then `py.exe -3`, then
`python.exe`; `-PythonExe` overrides that choice. Python 3.10+; no new pip packages.

## First bounded model run: T01 only

This command DOES run the named model and candidate Python. Select an installed
candidate, and use the host-execution acknowledgement only after reviewing the
boundary above:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 `
  -Action run -Model gemma3:12b -Through T01 -Phase screen `
  -AllowHostExecution
```

Nothing automatically starts T02. A run emits `RUN_DIR=` before inference so even
partial failures can be located. Defaults match the generic Ollama campaign:
32768 context tokens, 8192 max output tokens, 600 seconds per role task, 3600-second
keep-alive. Parameters: `-ContextTokens`, `-MaxOutputTokens`, `-TimeoutSeconds`,
`-KeepAliveSeconds`. No total-model timeout is added. Independent acceptance has
its own 120-second watchdog and bounded output. Model/tool activity appears live;
the reused Ollama transport returns whole responses, not token-by-token streaming.

## Complete fixed-plan Worker project

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 `
  -Action run -Model gemma3:12b -Through T06 -Phase screen `
  -AllowHostExecution
```

Each stage uses a fresh role conversation, the actual preceding workspace, and
the full actual preceding final response. A stage must pass cumulative acceptance,
respect scope and provide a nonempty handoff before its successor starts. Failed
successors are recorded as blocked; no gold code or another model repairs them.
There is no assessor-guided repair loop in v1. Public-test self-correction within a
task is allowed and visible. Model residency is unchanged; fresh conversation does
not imply model unload. Human handoff-quality review remains required.

`-Through T03`, for example, runs T01–T03 from a fresh starter; it does not isolate
T03 with a pre-solved predecessor. `-Phase qualification` repeats the selected
chain three times using separate fresh workspaces. Same temperature/seed; not
independent statistical samples. No implicit resume or overwriting of prior trials.

This fixed-plan chain tests implementation handoffs. It is NOT an autonomous
Planner → Governor → Worker → Tester → Reviewer project controller.

## Prepare, inspect, or assess an external candidate

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 -Action prepare
```

Use the printed WORKSPACE only with a separately controlled harness. Do not give
the model the full benchmark repository or the assessor/reference directory.
After it changes the candidate workspace, independently assess cumulative T01–T06:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 `
  -Action assess -RunDir 'C:\path\to\the\printed-run' -Task T06 `
  -AllowHostExecution
```

Each assessment writes a new evidence directory and hashes the exact code tested.
It never overwrites earlier results. Do not compare manual repairs with untouched
model trials without recording the intervention and changed artifact identity.

## Planner, Governor, Tester and Reviewer probes

All probes are single advisory trials. They do not auto-approve downstream work.
Start with the prepared run as source for Planner. It receives actual starter
contents and released requirements; no reference implementation.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-001.ps1 `
  -Action probe -Role planner -Model 'YOUR_INSTALLED_MODEL' `
  -InputRun 'C:\path\to\prepared-run'
```

Governor additionally requires `-GovernorRoot C:\Projects\governor` and
`-PlanFile 'C:\path\to\planner-run\roles\planner\final.txt'`. The exact supplied
plan and governance bytes are captured with hashes; missing governance is blocked.
No fabricated or inferred authorization is inserted.

For Tester or Reviewer, point `-InputRun` at an actual implementation run.
Tester may change only `tests/test_candidate.py` in a NEW copy and run the fixed
public unittest tool; it requires `-AllowHostExecution`. Reviewer is read-only
and receives code, real Worker claims, independent result metadata and exact
artifact-hash matching status. No verdict is auto-scored from a keyword. Evaluate
these probes with REVIEW_RUBRICS.md; an implementation defect is not automatically
a Tester/Reviewer failure. Original implementation runs stay unchanged.

## Evidence and interpretation

Default output root: `<checkout>\local-state\assistant-001`. Use `-OutputRoot` to
choose another location. Each trial contains:

```text
run.json                          packet identity, initial file hashes
runner-inputs.json                settings and runner implementation hashes
runtime-observation.json          observed model/runtime metadata
workspace/                        actual candidate implementation
roles/worker/T01/...              raw setup, dispatch, events, final, handoff link
assessments/T01-.../              independent checks, exit status and code hashes
summary.json                      first-pass acceptance and blocked successors
review/review-package.xlsx        existing standardized review writer
review/review-package.json
review/case-results.csv
review/role-summary.csv
```

Standalone prepare/assess actions do not generate a workbook; run/probe actions do.
For qualification, additional fresh trial workspaces are under repetitions/ and
the top-level review package aggregates their rows. Raw evidence stays authoritative.
Exit 0 for Worker chains means all attempted stages accepted pending HUMAN review,
not production qualification. Probe exit 0 means operational completion with scope
intact, not substantive correctness. Exit 1 = candidate not accepted; exit 2 =
blocked setup/infrastructure. Partial evidence is retained.

The queue GUI still wraps the original all-role CLI. It does not silently run this
new project. Use this dedicated launcher until a separately reviewed campaign
selector is added. No leaderboard or automatic role/model assignment is introduced.

## Benchmark validity and deferred scope

The ten negative controls cover boolean probability coercion, ignored ID conflicts,
missing commits, dropped filters, arrival-order state, TTL boundary errors, source
fusion, future-event interference, confidence-based precedence and partial batch
commits. A control counts as caught only when its designated behavioral check
fails—not when the assessor crashes or an import is broken.

The reference is test calibration, not a benchmarked model output or production
Assistant component. No candidate has been qualified by building this packet.
App-exit persistence is checked; abrupt power loss, disk failure, simultaneous
writers, migrations, retention, resource/concurrency, actuator actions and real
Observer/KC/HA integration are explicitly deferred. All tests are open source:
assessor isolation reduces answer exposure during a trial, not public benchmark
contamination or malicious same-interpreter tampering.

## Developer checks

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'src')
py -3 -m unittest discover -s tests -p 'test_assistant001*.py' -v
```

The tests use controlled fixtures/fake sessions and verify acceptance calibration,
packet integrity, candidate-only materialization, actual handoff routing, predecessor
blocking, no implicit repair and preserved source artifacts. Windows CI also checks
the PowerShell launcher and compatibility with the existing review-package writer.
Never regenerate manifest.json to hide an unexpected source change. Released
requirements/fixtures need a new version before collecting comparative results.

Technical references consulted for the design (requirements remain project choices):
Python sqlite3 transaction/connection documentation, Python datetime aware-time
semantics, and SQLite atomic-commit documentation. SQLite connection context managers
do not close the connection; timestamp parsing support differs across Python versions.
- https://docs.python.org/3/library/sqlite3.html
- https://docs.python.org/3/library/datetime.html
- https://sqlite.org/atomiccommit.html
