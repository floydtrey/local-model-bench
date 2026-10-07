# Flash-Next all-role qualification campaign v1

This is a new campaign on **Benchmark Lab V2**, rooted at
`architecture/multi-runtime-tool-interface`, commit
`b01ec0a7cc693c8f4d731e13dedac613f2defba2`. It does not run the old role
qualification harness. The shared batteries, fixtures, deterministic evaluators,
and their repetition policy remain frozen.

**Initial state: setup implemented; real Flash-Next runtime/interface and all five
roles remain unqualified until their evidence is reviewed.** Local automated
tests use synthetic drivers/HTTP servers. They cannot qualify the Windows fork.

## Candidate and launch contract

| Setting | Pinned value |
| --- | --- |
| Candidate | Qwen3.8-Flash-Next UD-IQ3_XXS |
| Alias | C01 |
| Model entry | `C:\AI\FlashNext-Lab\models\Qwen3.8-Flash-Next\UD-IQ3_XXS\Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf` |
| Runtime | `C:\AI\FlashNext-Lab\build\cuda-13.3\bin\llama-server.exe` |
| Owner-verified fork revision | `27c54b4bbcefadedcec6397477cc2e866c1db716` |
| Context | 262144 tokens, one explicit parallel slot |
| Endpoint | `http://127.0.0.1:18081` |
| Environment | `GGML_CUDA_REGISTER_HOST=1`, `HF_HUB_OFFLINE=1` |

The server launch preserves every supplied flag:

```text
-ngl 99 -ncmoe 99 -fa on -ctk f16 -ctv f16 -t 8 -b 256 -ub 128
--no-sched-async-cpu --no-context-shift --predict -1
--reasoning-budget -1 --timeout -1 --jinja --reasoning auto
--reasoning-format deepseek --metrics
```

The launcher adds only the explicit model path, alias, context, single slot,
loopback host, and port. The exact argument vector and the two environment
overrides are preserved in each run's `runtime/launch.json`.

`--version` must report the supplied revision or an identifiable abbreviation of
it. The record distinguishes the observed abbreviation from the supplied full
pin. The executable and adjacent DLLs are hashed; every GGUF shard is checked
for existence/header and SHA-256 hashed. No artifact is downloaded or substituted.

The new qualification client deliberately specifies its own sampling and output
bounds: **8192 maximum output tokens per response**, temperature 0, seed 42,
top-p 1, no extra top-k/min-p filtering, and repeat penalty 1. These settings are
sealed in the effective request. They are not an assertion about historical
Flash-Next/Ollama request settings. Server `--predict -1` and `--timeout -1`
remain intact; client limits still bound the experiment. Server-default
`--reasoning auto` is preserved without disabling thinking or adding an output
form to role responses.

## First smoke: exact Windows commands

Use an isolated worktree so the current benchmark checkout can retain its branch
and any active work. For a first checkout of this branch:

```powershell
Set-Location C:\Projects\local-model-bench
git fetch origin benchmark/flashnext-all-roles-v1
git worktree add -b benchmark/flashnext-all-roles-v1 C:\Projects\local-model-bench-flashnext origin/benchmark/flashnext-all-roles-v1
Set-Location C:\Projects\local-model-bench-flashnext

powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage validate
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage smoke
```

If the local branch already exists, omit `-b` and use
`git worktree add C:\Projects\local-model-bench-flashnext benchmark/flashnext-all-roles-v1`.
If that worktree already exists, enter it and use the pull command below.

The wrapper uses the checkout's `.venv\Scripts\python.exe`, then `py.exe -3`,
then `python.exe`. Python 3.10+ and the standard library suffice. An existing
interpreter can be selected with `-PythonExe 'C:\path\to\python.exe'`. No pip
installation or model download is required by this campaign.

An optional **preflight only** command hashes the artifacts and captures the
host/runtime identities without loading a model:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage preflight
```

Every command that creates evidence prints its full directory. Successful
inference commands end with `RUN_DIR=...`. Runs live under
`local-state\flashnext-all-roles-v1\<unique-run-id>\` and are ignored by Git.
They may include private canonical Governor documents and raw host observations.

### What the first smoke does

1. Verify the frozen battery/source hashes, all three GGUF shards, executable,
   adjacent DLLs, and binary-reported fork revision.
2. Capture **two V2 host profiles** and require their stable facts hashes to agree.
3. Refuse to attach to an occupied port. Launch and own one pinned server process.
4. Preserve server stdout/stderr, health, model listing, properties and metrics.
   Verify alias C01, one slot, effective context 262144 and the exposed Jinja
   template before the first scored request.
5. Run three exact accepted cases as a separately identified diagnostic
   projection: L0 `structured-transformation`, L1 `evidence-traceability`, and
   L2 `read-transform-write`. L2 exercises native read/write tool calls and the
   assistant/tool-result round trip through existing BL-6 authority.
6. Stop the owned server. Create a passing gate only when all three deterministic
   checks pass and native tool transport is observed. A passed smoke qualifies
   this bounded interface path for further measurement; it assigns no role.

The entire inference smoke has a **600-second budget including server startup**.
Artifact hashing and host preflight are separate preparation. Ordinary later
cases/tasks have 600-second budgets. Responses that hit the token limit or context
truncation are recorded as truncated, never silently accepted as complete.

There is no automatic continuation from smoke to the 22-case screen or all roles.

## Shared screen and repetitions

After a passing smoke, copy its exact `RUN_DIR` value:

```powershell
$SmokeRun = 'C:\Projects\local-model-bench-flashnext\local-state\flashnext-all-roles-v1\REPLACE-WITH-SMOKE-RUN'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage shared-screen -SmokeRun $SmokeRun
```

This runs the unchanged **9 L0 + 5 L1 + 8 L2 = 22 observations**, with one trial
per accepted case. L2 keeps its accepted 3/4/5 tool-call profile limits; the role
tool budget does not change them. The optional shared qualification phase uses
the existing three-trial policy, producing **66 observations**:

```powershell
$SharedRun = 'C:\Projects\local-model-bench-flashnext\local-state\flashnext-all-roles-v1\REPLACE-WITH-SHARED-SCREEN-RUN'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage shared-qualification -SmokeRun $SmokeRun -SharedRun $SharedRun
```

Shared-screen completion records correctness independently. A low deterministic
score does not itself eliminate a candidate from later role testing. Operational
driver/parser errors stop execution with raw evidence intact. A changed model,
runtime, host, profile, source corpus, or behavior-bearing implementation cannot
reuse an earlier smoke gate.

## Role-specific qualification

Start with a bounded role screen after the shared screen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage roles -SharedRun $SharedRun -Role planner -Phase screen
```

The same command accepts `governor`, `worker`, `tester`, or `reviewer`. Governor
requires the **actual local canonical documents**; for example, if your existing
Governor checkout is `C:\Projects\governor`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\campaigns\run-flashnext-all-roles.ps1 -Stage roles -SharedRun $SharedRun -Role governor -Phase screen -GovernorRoot C:\Projects\governor
```

An explicit `-Role all` runs the five roles in Planner/Governor/Worker/Tester/
Reviewer order. `-Phase qualification` runs three fresh repetitions. Neither is
the default. Do not start that larger command until the smoke and shared evidence
are available for the exact current setup.

A complete role pass contains 23 cases; three repetitions contain 69 case
observations before any dependency skips. Each role case has at most 40 tool
calls and 48 model turns, including setup and any permitted repair. These role
limits do not change the accepted shared L2 budgets. Missing Governor documents
at `GovernorRoot\docs\LAW.md`, `STATE.md`, or `GENERAL_INTENT.md` block its cases.

| Role | Reused coverage | What constitutes evidence |
| --- | --- | --- |
| Planner | All six historical intent fixtures | Exact role setup followed by intent; full prose retained for human review, including AMBIGUOUS/BLOCKED and bounded task decisions |
| Governor | Packets A-D and fixture Project Intent | Original intent, plan and real Law/State/General Intent; packet D's invented storage preference remains a substantive contrast |
| Worker | Fixture 01 Task 1; Intent04 fixture 02 Tasks 1-3 | Actual changed files, frozen deterministic verifiers, independent tests, task scope and accepted handoff; one established same-session repair where applicable |
| Tester | Historical cases A/C/D | Real test commands and output; distinguish correct code, a production defect, and a faulty test; independently check whether generated/modified tests are valid |
| Reviewer | Current main `native-lab` prompt/packet and source-based cases | Full task/evidence review with explicit provisional status; candidate verdict is advisory and is not independent test execution |

`sources/local-model-bench/SOURCE_MANIFEST.json` pins all 62 copied assets to
`benchmark/worker-qualification-v1` commit
`fce91a7fa409aecd824a3fa1229724b0aab56812`. It records original paths, exact bytes,
SHA-256 and Git blob identities. This imports source fixtures, not the old runtime
or qualification branch machinery.

`sources/deepseek-lab/SOURCE_MANIFEST.json` pins Reviewer sources to main commit
`e8bf69e664504fc54fbb94a00131b52e0a9c0de9`. The current `native-lab` Reviewer is
explicitly unqualified/provisional. The isolated `repair/native-lab` variant is
not substituted. Derived Reviewer contrast cases are labeled as new campaign
fixtures, not historical model qualifications.

The original role prompts and their setup/task order are preserved. Planner,
Governor, Worker and Tester receive tool-free role setup before dispatch. The
Reviewer packet follows its actual native-lab dispatch contract. Role final
responses remain natural prose; only already-established status/handoff markers
are interpreted for routing. A matching status marker cannot by itself qualify
a role.

Tester B/E/F were only planned in the historical branch and are not invented or
reported as covered. Tester A/C/D form a representative screen, not a complete
six-case battery. Text-role correctness remains pending human review. Repetition
adds consistency evidence; it never promotes a candidate automatically.

### Role execution boundary

Role tools use a separate declared neutral surface: exact-scope `read_file` and
`write_file`, plus a fixed no-argument `run_tests` where the source task requires
testing. Every call is normalized by the same native llama.cpp adapter. Models
cannot select an arbitrary command line. Worker changes cannot modify tests or
assessor helpers. Tester changes are limited to the declared fixture tests; its
production files remain read-only. Candidate-created test code is inspected for
the narrow pricing fixture contract before execution, and unsupported test
constructs remain interface-blocked rather than intrinsic model failures.

The file boundary reuses BL-6. Test execution is a declared campaign extension,
not a claim of OS filesystem/network isolation or qualification through the full
DSH/ACP pipeline. Independent deterministic checks remain outside candidate
authority. One unqualified role does not become the sole judge of another.

## Evidence and performance interpretation

The V2 content-addressed `evidence/records/` tree retains host/runtime/model,
effective configuration, interface, benchmark, trial, execution binding, manifest,
raw normalized traces, case results, evaluations, telemetry and aggregates.
Role conversations use the explicitly versioned additive `role_execution_trace`
record; they do not masquerade as the existing intrinsic/shared-tool trace formats.
Raw HTTP request/response bytes are written **before parsing**, including malformed
JSON, HTTP errors and partial bodies. Sidecar hashes are retained in observations.
Server logs and GET observations are preserved as well.

`gate.json`, `measurements.json`, and their CSV views are derived campaign indexes
over that evidence. They do not replace raw V2 records. Inspect all four tool
dimensions: semantic selection, arguments, parser/protocol compatibility, and
end-to-end result. A tool-shaped text response cannot execute a tool. A parser or
transport error cannot be relabeled an intrinsic model failure.

Performance reporting keeps these quantities separate:

| Measurement | Interpretation |
| --- | --- |
| Process start to ready | New-process startup/model load; OS file-cache state remains unmeasured |
| First request / warm-resident | Fresh conversation after load versus later requests while the same model process remains resident |
| Case/task wall seconds | Observed elapsed execution time, including the task's tool loop |
| Prompt/output/reasoning tokens | Provider counts only; unavailable counts remain null |
| Generation tokens/second | Provider generation timing/counts; never relabeled whole-request wall throughput |
| Output tokens per wall second | Separate end-to-end rate including prompt/tool/wait overhead |
| Output words/characters/bytes | Verbosity, separated from reasoning and token counts |
| CPU/RAM/VRAM/GPU/power | Sampled V2 telemetry with availability status; shared-device observations are not attributed exclusively to this process |
| Tool calls / retries / truncation | Actual tool behavior and limits, separate from correctness |

Flash-Next's historical raw speed advantage over Qwen3.8 27B is a motivation for
this campaign, not a fresh measurement. No new 27B comparison is fabricated.
Compare matching task/configuration/interface evidence using generation rate,
output volume, total latency, and resource footprint together. Long output can
consume a raw generation advantage. Different context/cache/sampler settings must
remain visible in any comparison.

## Setup verification

The setup passed the full repository suite: **270 tests, no failures or skips**.
The suite includes the real HTTP adapter, accepted V2 evaluators/tool harness,
three-case smoke, all 22 shared cases, historical role protocols and fixtures,
and gate rejection of incomplete or altered evidence. These tests use synthetic
local HTTP endpoints and fixture drivers; they load no model and establish no
Flash-Next runtime or role qualification.

To reproduce the dependency-free checks from a POSIX checkout:

```bash
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m localbench.v2.flashnext_campaign validate
```

The Reviewer packet parity test uses Node when available; it was available for
the recorded setup test run. Full JSON Schema standards-engine validation was
not available in the setup environment. Contract tests and a bounded structural
schema audit passed; that audit is not reported as full schema validation.

## Updating or pushing this branch

Inside the Flash-Next worktree:

```powershell
git pull --ff-only origin benchmark/flashnext-all-roles-v1
```

To publish additional local commits on this branch:

```powershell
git push -u origin benchmark/flashnext-all-roles-v1
```

Do not commit the ignored raw run directories or canonical private Governor
snapshots inadvertently. The requested setup branch contains code, configuration,
pinned source fixtures and synthetic tests only.
