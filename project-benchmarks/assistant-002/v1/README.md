# ASSISTANT-002/v1 — Event Simulator and Replay

The second real Assistant project benchmark. It builds an offline simulator that
can feed reproducible event sequences into a Journal, query it at explicit virtual
times, report missing/unexpected observations and recover from saved progress.
The delivered candidate could later drive Observer/Home Assistant integration tests;
it does not connect to those systems now.

## Package and test set

Six cumulative Worker tasks build the candidate from intentional stubs:

| Task | Build | Distinct failure modes covered |
| --- | --- | --- |
| T01 | Strict scenario normalization and identity | Invalid inputs, defaults, canonical hashing, bounds and detached data |
| T02 | Delivery schedule | Delay/drop/retransmission, stable ties, immutable event IDs |
| T03 | Virtual replay over injected sink | Exact clock, due-event boundary, sink errors and acknowledged progress |
| T04 | Checkpoint recovery | Foreign/corrupt progress, equal-time partial recovery, lost receipts and at-least-once retry |
| T05 | Expected-observation evaluation | Missing AND unexpected evidence, complete reports, journal interoperability |
| T06 | CLI, tests and documentation | Offline compilation/JSONL, optional journal run, distinct errors/mismatches, Unicode |

The final acceptance suite has **96 checks**, including eight authored household
scenarios. The suite is cumulative; they are not 96 independent projects. Twelve
behaviorally defective reference variants verify that the assessor detects the
intended bugs. The reference and unsolved-starter controls make 14 calibration
controls in total. No actual candidate model is qualified by these self-tests.

The eight scenarios are door reconnect duplicates, late observations, expired latest
presence, future-clock skew, sensor disagreement, dropped presence, delayed delivery
and a quiet room. Their expected observations are authored JSON, not generated from
the implementation being scored. Changes require a new frozen packet version before
comparative candidate runs.

## Why this is different from Assistant-001

Assistant-001 stores immutable events and projects current observations. Assistant-002
controls WHEN an event reaches that journal, including deliberate repeats and missing
transmissions, then checks what the journal reports. Event timestamp and delivery time
are intentionally separate. Simulator replay uses no wall clock, sleeping, randomness,
threads, notifications or model reasoning.

The read-only event_contract.py helper is supplied from the pinned A001 normalizer;
UPSTREAM.json identifies the exact bytes and the docstring-only change. This reduces
repeated validation work. It is an explicit supplied dependency, not a model-produced
A001 implementation. No Journal or simulator reference is exposed in candidate view.

## Existing infrastructure is reused

The launcher calls `python -m localbench.assistant002`. It uses the existing
`assistant001.campaign` Worker/probe engine, `assistant001.assessment` watchdog,
`assistant001.runtime.OllamaSessions`, original V2 role prompts/tools and the existing
review-package writer. Two shared engine modules now accept an optional packet
adapter; omitted adapters retain A001 behavior and original A001 tests remain CI
regressions. Frozen A001 requirements, its 79 acceptance checks, old five-role batteries,
GUI and generic all-role CLI are unchanged. There is no second inference harness.

The inherited raw event label `assistant001_effective_config` identifies the reused
runtime implementation, not the packet being scored; case IDs and campaign metadata
identify Assistant-002 explicitly. Runner inputs also retain shared-engine hashes.

The GUI has NOT acquired a project selector. It still launches the original all-role
battery. Use the dedicated launcher for this project.

## Pull and validate (no inference)

```powershell
Set-Location C:\Projects\local-model-bench-flashnext
git switch benchmark/flashnext-all-roles-v1
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-002.ps1 -Action validate
```

Validate verifies packet/dependency hashes and the frozen check inventory. It does
not run a model or candidate code. The default launcher action is also validate.

Calibrate the reference, twelve known defects and unsolved starter:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-002.ps1 -Action self-test
```

Self-test runs only trusted fixtures and disposable databases. No downloads,
Ollama calls, production services or real household data are used.

## One bounded real-model trial

Choose an installed tool-capable Ollama tag. This command DOES start the selected
model and executes its generated Python:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-002.ps1 `
  -Action run -Model 'YOUR_INSTALLED_MODEL' -Through T01 -Phase screen `
  -AllowHostExecution
```

`-Through T06` runs the full six-task chain from a fresh starter. A failed task
blocks successors. Each accepted handoff is the actual previous model response and
workspace, not reference code. No mandatory handoff heading, hidden repair, implicit
resume or automatic promotion. `-Phase qualification` runs three fresh chains,
not three continuations of the same partly solved workspace.

Defaults: 32768 context, 8192 max output, 600 seconds per role task and 3600-second
keep-alive. Override using `-ContextTokens`, `-MaxOutputTokens`, `-TimeoutSeconds`
and `-KeepAliveSeconds`. The assessor has a separate 120-second limit. Wall time
includes controller/assessment overhead, not just generation. The reused Ollama
transport emits whole model responses; activity events are live, not token streaming.

**Host execution is not an OS/network sandbox.** Bounded file tools are not security
isolation for generated Python. Use a disposable VM for untrusted code. The explicit
acknowledgement does not enable isolation or authorize access to production data.
The simulator itself needs no network; only the benchmark controller contacts local
Ollama. This remains a fixed-plan Worker chain plus advisory role probes, not a
fully autonomous governed five-role project controller.

## Prepared workspace and independent assessment

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-002.ps1 -Action prepare
```

Only the printed WORKSPACE is candidate-visible. It includes starter, contract,
fixed tasks, public examples and protected helper, not assessor/reference code.
Use it with another controlled harness, then assess without launching a model:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-002.ps1 `
  -Action assess -RunDir 'C:\path\to\assistant002-run' -Task T06 `
  -AllowHostExecution
```

Each assessment creates new evidence and records pre/post artifact hashes. Scope
violations block before execution; missing inventory rows cannot be counted as a
complete pass. Baseline simulator assessment combines spy sinks with the pinned
A001 reference Journal. That Journal is calibration evidence, not a candidate model.

## Test two actual model-produced components together

After individual code review/acceptance, select an Assistant-002 run and an
Assistant-001 run. This copies the Journal into a separate dependency workspace,
uses it instead of the reference, runs the final simulator checks and records hashes
for the pair. It does not alter either source implementation or deploy anything.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-assistant-002.ps1 `
  -Action interop `
  -RunDir 'C:\path\to\assistant002-run' `
  -JournalRun 'C:\path\to\assistant001-run' `
  -AllowHostExecution
```

A mismatch here belongs to the pair until investigated. The command is not a
substitute for full standalone A001 acceptance. File hashes verify tested versus
source copies; they are not malicious-code containment or an authenticity guarantee.

## Advisory role probes

`-Action probe -Role planner -Model TAG -InputRun RUN` evaluates actual starter/code
and disclosed requirements. It is scaffolded by TASKS.md, not blind plan generation.
Governor requires `-GovernorRoot C:\Projects\governor` and an actual `-PlanFile`.
Tester requires `-AllowHostExecution`, can change only tests/test_candidate.py in a
new copy, and runs visible tests. Reviewer is read-only. None of these probes turn
prose into Owner authorization or launch the next role automatically. Use the
separate REVIEW_RUBRICS.md, especially when the implementation itself is defective.

## What usable candidate output looks like

From a completed candidate workspace (not the benchmark repository):

```powershell
python -m assistant_simulator validate --input scenarios\door-reconnect.json
python -m assistant_simulator schedule --input scenarios\late-observation.json
python -m assistant_simulator jsonl --input scenarios\door-reconnect.json
```

`run --input scenarios\door-reconnect.json --db C:\Disposable\events.sqlite3`
requires the separately supplied assistant_journal package on the Python import path.
It uses that explicit database without resetting it. A nonempty database can correctly
produce unexpected observations. JSONL emits normalized events, not delivery-time
metadata; use Replay/evaluate_scenario for time-aware testing. Checkpoint records
are JSON-serializable; the caller owns atomic checkpoint-file storage. A receipt
lost after append may cause redelivery with the SAME event ID. The journal's duplicate
handling makes that safe; the simulator does not promise exactly-once delivery.

## Outputs and interpretation

Default: `<checkout>\local-state\assistant-002`. `-OutputRoot` chooses another folder.
RUN_DIR is printed before model calls. Run/probe outputs reuse:
`review/review-package.xlsx`, `review/review-package.json`, `review/case-results.csv`
and `review/role-summary.csv`. Prepare/assess/interop do not generate new workbooks;
independent assessment JSON, stdout/stderr and code hashes are their evidence.
Run inputs, raw role events, exact dispatches/finals and accepted handoff links remain
available. Qualification retains each fresh repetition and aggregates the review rows.

Exit 0 for a Worker campaign means deterministic acceptance pending human review;
for a probe it means operational completion with scope intact. Neither means production
qualification. Candidate CLI uses exit 1 for expectation mismatch, 2 for errors.
Benchmark CLI uses 1 for nonacceptance and 2 for blocked setup. Critical failures
are reported individually, not averaged away with validation successes.

## Deterministic development checks

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'src')
py -3 -m unittest discover -s tests -p 'test_assistant002*.py' -v
py -3 -m unittest discover -s tests -p 'test_assistant001*.py' -v
```

Mandatory CI uses Windows/Linux and Python 3.10/3.12, including the old A001 suite,
new packet tests, real journal-pair fixtures, fresh repetition workspaces, original
review writer and Windows launcher. All model sessions in CI are controlled fakes.
Reference code calibrates tests only and must never fill in a failed model's task.
No concurrency/hardware claims, real notifications, random faults, retention changes,
production integration, unattended services or automatic code promotion are included.

Technical design references: Python's datetime/timedelta documentation for explicit
aware-time arithmetic and json documentation for canonical serialization controls.
The project's ordering, checkpoint and fault policies are declared design choices.
- https://docs.python.org/3/library/datetime.html
- https://docs.python.org/3/library/json.html
