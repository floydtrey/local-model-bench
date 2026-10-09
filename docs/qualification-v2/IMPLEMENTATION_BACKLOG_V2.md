# Controlled Role Qualification v2 — Audited Task Backlog

**Status:** T01 complete; T02–T18 not started. **Revised:** 2026-10-08 following the [T01 source audit](T01_CURRENT_IMPLEMENTATION_AUDIT.md).  
**Authoritative implementation backlog:** This file supersedes the earlier chat-only 18-task outline. Task IDs have not been renumbered. No implementation beyond T01 is claimed by publishing this task list.

## Key audit decisions (binding to the proposed implementation)

1. **Do not rebuild what already works.** Existing 23-case historical role battery, Assistant-001/002 fixed six-task Worker campaigns, 79/96 independent acceptance checks, original role prompts, V2 Ollama execution/assessor/review writer, and mixed-benchmark GUI remain baselines. Keep frozen v1 packets unchanged.
2. **Two evaluation tracks; three Worker-relevant modes.** CONTROLLED_ROLE_QUALIFICATION tests each role against separately reviewed input. Its Worker assessments include ISOLATED_TASK (identical verified preconditions) and CUMULATIVE_PROJECT (identical initial intent/plan but each model's own predecessor code). NATIVE_PIPELINE_INTEGRATION deliberately uses real preceding role outputs.
3. **Blind Planner means truly blind.** The current project Planner probe exposes TASKS.md in the DOCS prompt AND again in its copied workspace. Neither visible path, metadata nor tool access may leak the fixed plan or assessor oracle into the new independent Planner mode. Keep old scaffolded probes labeled separately.
4. **Governor compares, but cannot authorize by prose.** Freeze substantive approvals/denials/escalations against exact canonical governance snapshots and explicit simulation assumptions. Governor candidate outputs are evaluation evidence, not permits. Actual owner-origin release and deterministic scope enforcement remain separate. Canonical governance bytes must not enter the public repository.
5. **Same reference plan is necessary but not sufficient for comparable Worker outcomes.** Independent per-task qualification needs identical starting code; end-to-end Worker continuation intentionally varies by candidate. Never insert the gold solution after a failed model task to pretend that the same candidate completed the project.
6. **The native DSH full-pipeline backend already exists in a separate development branch.** T14 is a read-only installed-version/provenance reconciliation followed by a thin adapter, safe validation and qualification of the existing native Planner→Governor→Worker→Tester→Repair→Reviewer release flow—not a second engine. The currently installed host/process has not been verified by T01.
7. **Preserve role and review truthfulness.** No exact-phrase plan matcher, no implied pass from CLI exit 0, no automatic promotion/role assignment, no assumption that generated Python is OS-sandboxed. Report evidence gaps, wrong authority and wrong transport distinctly.
8. **Source/provenance boundary.** Public repo stores test case metadata, references and hashes. Private Governor and DSH sources and owner credentials are never copied into it; case-specific canonical governance snapshots belong in access-controlled run evidence.

**Definition of complete:** Each task needs its described acceptance evidence, not a model's self-report. Implementation code must pass its relevant regressions and support human review. Real-model tests are T17, not implied by earlier deterministic CI.

## Updated scope and dependency overview

| ID | Revised work item | Priority / size | Prerequisites | Status |
|---|---|---|---|---|
| T01 | Source audit and baseline evidence | P0 · Completed | — | COMPLETE |
| T02 | Freeze evaluation-mode, authority and disclosure contracts | P0 · Medium | T01 | NOT STARTED |
| T03 | Derive ASSISTANT-001 reference plan from existing tasks | P0 · Small | T02 | NOT STARTED — reuse v1 task decomposition |
| T04 | Derive ASSISTANT-002 reference plan from existing tasks | P0 · Small | T02 | NOT STARTED — reuse v1 task decomposition |
| T05 | Make project Planner qualification genuinely independent | P0 · Medium | T03, T04 | NOT STARTED |
| T06 | Build semantic Planner equivalence assessment | P0 · Medium | T05 | NOT STARTED |
| T07 | Create frozen project Governor decisions and authority conditions | P0 · Large | T02, T03, T04 | NOT STARTED |
| T08 | Evaluate Governor rulings and constraint extraction independently | P0 · Medium | T07 | NOT STARTED |
| T09 | Build canonical reference Worker handoffs with separate authority | P0 · Medium | T03, T04, T08 | NOT STARTED |
| T10 | Add isolated Worker task qualification alongside existing project chains | P0 · Large | T09 | NOT STARTED |
| T11 | Extend Tester qualification with controlled implementation fixtures | P1 · Medium | T02, T10 | NOT STARTED |
| T12 | Extend Reviewer qualification with evidence-grounded cases | P1 · Medium | T10, T11 | NOT STARTED |
| T13 | Extend evidence schema and failure attribution without replacing review writer | P0 · Medium | T06, T08, T10, T11, T12 | NOT STARTED |
| T14 | Verify and adapt the existing native DSH full pipeline for integration trials | P0 · Large | T02, T09, T13 | NOT STARTED — native source exists; installed state unverified |
| T15 | Regression-test authority, isolation, parity and failure propagation | P0 · Large | T05, T08, T10, T11, T12, T13, T14 | NOT STARTED |
| T16 | Extend the existing GUI to select evaluation track and role | P1 · Medium | T14, T15 | NOT STARTED — original GUI already supports three benchmarks |
| T17 | Pilot actual models on frozen role cases and the native integration chain | P0 · Medium | T15, T16 | NOT STARTED — no real model runs for this change |
| T18 | Freeze v2 qualification release with human-reviewed results | P1 · Small–medium | T17 | NOT STARTED |

## Execution milestones and stop gates

| Milestone | Included tasks | Go/no-go evidence |
|---|---|---|
| M0 · Baseline | T01 | Source implementation map + prior CI and Git blob snapshot recorded; installed DSH still unverified |
| M1 · Ground truth and independent comparisons | T02–T08 | v2 mode/authority matrix; separate reference plans; blind Planner leakage tests; human-reviewed Governor case outcomes |
| M2 · Canonical Worker and downstream roles | T09–T13 | reviewed reference Worker handoffs; independent-isolated vs cumulative Worker separation; Tester/Reviewer oracles; inherited evidence writer |
| M3 · Native pipeline and safety proof | T14–T15 | installed DSH provenance verified; existing DSH releases/dispatchers exercised with fakes; old v1 and GUI regressions pass |
| M4 · Interface and genuine model results | T16–T18 | new modes in same GUI; real-model screen and bounded native integration pilot; frozen v2 release with reviewed evidence |

**Critical gate:** Do not promote an integration test to PASS if the local native DSH installation, authorization origin or model/runtime configuration differs from what was actually tested. T03–T13 may progress in the benchmark repo while native installation reconciliation awaits T14.

## Detailed tasks

## Scope, authority contracts and project references

*T01–T04 · preserve the already-passing baseline; derive independently reviewed reference plans*

### T01 — Audit current benchmark and role handoff paths
**Status:** COMPLETE — source-audited · **Priority:** P0 · **Complexity:** Completed · **Dependencies:** None  
**Where:** local-model-bench: docs/qualification-v2/

**Reuse:** Both frozen project packets, historical role campaign, V2 assessment/review stack, mixed-queue GUI; separately sourced Governor and native DSH development pipeline.

**Bounded work:** Performed source audit and recorded the Git baseline and prior CI evidence. Windows-installed DSH/runtime/governance state remains deliberately unverified; it becomes an explicit prerequisite of T14.

**Acceptance:** The implementation map and baseline lock exist; the commit changes documentation only. No assertion of successful live-model or installed-DSH qualification.

**Change from the pre-audit list:** Completed; revealed Planner reference leakage in two places, advisory governance, direct-Ollama vs native DSH split and advanced DSH development pipeline.

### T02 — Freeze evaluation-mode, authority and disclosure contracts
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T01  
**Where:** local-model-bench: docs/qualification-v2/; additive contract and tests only

**Reuse:** T01 map, frozen v1 manifests/role packets, existing benchmark human-review semantics, Governor authority boundaries, DSH release design.

**Bounded work:** Define two top-level evaluation tracks: CONTROLLED_ROLE_QUALIFICATION (Planner, Governor, Worker, Tester, Reviewer independently) and NATIVE_PIPELINE_INTEGRATION (actual upstream outputs). Within Worker qualification distinguish ISOLATED_TASK (identical prevalidated prerequisite snapshot) from CUMULATIVE_PROJECT (same initial starter and plan, each model's real predecessor artifacts). Specify which input is candidate-visible versus assessor/owner-only; exact version/hashes, session/tool/sandbox scope, run/authority origins, human review, abort/block and failure attribution. Explicitly distinguish V2 direct-Ollama vs native DSH transport and require inspected installed-Dsh provenance before live native qualification. Define a protected-v1-file regression gate, not a blanket hash freeze on code that must be extended.

**Acceptance:** Published input/disclosure matrix and run-mode schemas distinguish these paths and fail closed on unknown modes. No model verdict grants owner authority, no integration result is labeled standalone role qualification, no human-oracle leak is authorized, and all v1 packets remain unchanged.

**Change from the pre-audit list:** Originally a generic track definition. Expanded to handle transport provenance, per-task vs chained-worker comparability, private governance and simulated vs real authority.

### T03 — Derive ASSISTANT-001 reference plan from existing tasks
**Status:** NOT STARTED — reuse v1 task decomposition · **Priority:** P0 · **Complexity:** Small · **Dependencies:** T02  
**Where:** project-benchmarks/assistant-001/qualification-v2/

**Reuse:** ASSISTANT-001/v1 PROJECT_INTENT, CONTRACT R01–R06, TASKS T01–T06 and existing independent acceptance tests.

**Bounded work:** Prepare a separate human-reviewed REFERENCE_PLAN and requirement/task traceability matrix from the already-frozen Worker sequence. Explain necessary ordering, allowed alternative decompositions, authorized file scopes, error cases, restart/expiry hazards and outcome-based acceptance. Retain exact v1 semantics; do not rewrite or mark the old TASKS as Planner-generated or Governor-approved.

**Acceptance:** 100% of R01–R06 material outcomes and critical invariants map to reference plan requirements; a reviewer can identify missing/unsafe steps. Reference is assessor-only for independent Planner and has its own content hash and review status.

**Change from the pre-audit list:** Reduced from writing a new plan to organizing and independently reviewing the plan already embodied in v1.

### T04 — Derive ASSISTANT-002 reference plan from existing tasks
**Status:** NOT STARTED — reuse v1 task decomposition · **Priority:** P0 · **Complexity:** Small · **Dependencies:** T02  
**Where:** project-benchmarks/assistant-002/qualification-v2/

**Reuse:** ASSISTANT-002/v1 PROJECT_INTENT, CONTRACT S01–S06, TASKS T01–T06, 96 checks, eight scenarios and pinned A001 dependency.

**Bounded work:** Prepare separately reviewed reference plan and S01–S06 traceability mapping. Capture virtual-time vs event-time, duplicate/dropped deliveries, checkpoint at-least-once semantics, authoritative expected observations, late/same-time behavior, CLI and journal-pair interoperability. No new project architecture or changed acceptance rules.

**Acceptance:** S01–S06 and all critical failure classes trace to reference plan deliverables; journal input dependency and seed provenance are explicit. The reference never appears in an independent Planner's input.

**Change from the pre-audit list:** Reduced from designing a new simulator plan to referencing the validated v1 contract and dependency.

## Independent Planner and Governor comparisons

*T05–T08 · prevent answer contamination, pin governance inputs and evaluate decisions*

### T05 — Make project Planner qualification genuinely independent
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T03, T04  
**Where:** local-model-bench: new qualification packet adapter/fixtures/tests, not v1 packet mutation

**Reuse:** role_prompt and task_prompt conventions, existing project starter source and project intent/contract.

**Bounded work:** Create an explicit Planner-visible allowlist and separate read-only starting-code view. Withhold TASKS.md, REFERENCE_PLAN.md, reference decisions, assessor code and reference implementations. Eliminate indirect leakage through workspace snapshots, copied README instructions, metadata, file names and any tool-readable directories. Preserve the existing scaffolded Planner probe as a distinctly labeled historical mode; do not silently change old trials. Planner may inspect genuine code stubs and released problem requirements, not a pre-solved plan.

**Acceptance:** Disclosure tests attempt prompt, workspace-file, tool-visible and metadata access and fail if the fixed task sequence/reference oracle is visible. Controlled Planner starts from identical task input and source snapshot across models. Existing scaffolded probe continues working as a separate mode.

**Change from the pre-audit list:** CRITICAL correction: T01 demonstrated TASKS.md was included both directly in DOCS and indirectly in the candidate workspace snapshot.

### T06 — Build semantic Planner equivalence assessment
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T05  
**Where:** local-model-bench: additive qualification rubric/assessor/review records

**Reuse:** v1 outcome-based acceptance criteria, six historical Planner intent cases and human-review writer.

**Bounded work:** Score material requirement coverage, feasible dependencies, atomic/bounded tasks, executable acceptance, scope restraint, risks, uncertainty management and required outputs. Compare to independently reviewed plan by objective rather than exact headings/task count. Calibrate with a valid differently decomposed plan, a critical omission, a scope-expanding plan and a correctly BLOCKED ambiguous plan; retain free-prose outputs and an auditable human verdict.

**Acceptance:** An alternate valid plan can pass; missing material behavior or forbidden operations cannot pass by matching labels. Judgment contains requirement-level evidence and severity; an automated similarity score alone never marks a Planner qualified.

**Change from the pre-audit list:** Existing historical Planner evaluation is manual and cannot serve as a project-specific equivalence oracle.

### T07 — Create frozen project Governor decisions and authority conditions
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Large · **Dependencies:** T02, T03, T04  
**Where:** local-model-bench: project-specific v2 case metadata; private run evidence for canonical governance bytes

**Reuse:** Historical four Governor packets, source-backed LAW/STATE/GENERAL_INTENT loader and separate Governor authority corpus.

**Bounded work:** Build independent ASSISTANT-001/002 cases spanning valid approval, prohibited action, owner-only exception, missing approval/identity, conflicting Law versus Intent, unsafe external transfer, scope drift, fabricated prior approval and genuine uncertainty. Provide owner/human-reviewed expected APPROVE, DENY or ESCALATE outcomes and required rationale/constraints. Freeze scenario assumptions and exact canonical Law/State/General Intent bytes per comparison group: hash evidence and retain private contents outside the public repo. Do not assume unresolved owner identity or protected assignments have been resolved; conditional simulation permissions must be explicitly labeled as simulation.

**Acceptance:** Each scenario has stable ID, exact plan and governance snapshot provenance, reasoned expected decision/constraints and human review. A fake Owner approval fails; ambiguous real authority escalates; docs drift blocks a comparison instead of changing its ground truth.

**Change from the pre-audit list:** The existing project Governor probe accepts arbitrary plan/doc inputs, not a frozen project decision oracle; no simulation decision may be confused with production permission.

### T08 — Evaluate Governor rulings and constraint extraction independently
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T07  
**Where:** local-model-bench: additive Governor assessment and review records

**Reuse:** Actual governor cases from historical role campaign; project run_probe and evidence writer.

**Bounded work:** Present frozen plans and matching governance snapshots identically to each candidate. Evaluate decision category, grounded reasons, required escalation, retained task-specific conditions, prohibited inferred authority and refusal to rewrite the plan. Count unsafe approval as critical independently of other successful cases; report erroneous denial and false escalation separately. Preserve full natural-language verdict for human review; never treat generated approval as an executable permission token.

**Acceptance:** Correct APPROVE/DENY/ESCALATE and material constraints are distinguishable from blanket deny or token matching; decision/justification and evidence hashes are reviewed. Controlled Worker input remains unchanged when candidate Governor gives the wrong answer.

**Change from the pre-audit list:** Current project Governor is advisory and does not supply an approved, independently validated handoff.

## Canonical Worker inputs and controlled downstream roles

*T09–T12 · distinguish identical task inputs from model-specific continuation artifacts*

### T09 — Build canonical reference Worker handoffs with separate authority
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T03, T04, T08  
**Where:** project-benchmarks/assistant-001|002/qualification-v2/ + shared handoff assembler

**Reuse:** v1 project task scopes, same task prompts, canonical governance case constraints, historical Worker approved-plan examples.

**Bounded work:** For each T01–T06 project task, build versioned input bundle: project intent, immutable full reference plan, exact assigned task, scope/tools, relevant Governor restrictions, accepted exceptions if explicitly authorized, acceptance requirements, starting workspace identity and previous handoff slot. Identify origin of authority separately: a trusted operator-approved benchmark authorization or explicitly simulated scenario authority; never model-generated Governor prose. Record pending-human-approval until the reference bundle has been reviewed.

**Acceptance:** Task bundles and plan hash are identical for like-for-like model comparisons; reference version/authorization is traceable. No unapproved exception or Governor-candidate output enters canonical Worker intent. Human review is required before labeling a reference bundle approved.

**Change from the pre-audit list:** The current Worker receives fixed task+contract+predecessor, but lacks a separate explicitly approved plan/Governor guidance/authority record.

### T10 — Add isolated Worker task qualification alongside existing project chains
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Large · **Dependencies:** T09  
**Where:** local-model-bench: new controlled Worker mode/fixtures; reuse assistant001.campaign and assessment

**Reuse:** Working six-step cumulative chain, frozen starters, exact file-scope checks, current Worker's accepted predecessor gating and no-gold-continuation semantics.

**Bounded work:** Implement TWO separately reported Worker trial modes. ISOLATED_TASK: each model starts from the same independently prevalidated prerequisites/seed snapshot with the assigned task unsolved; seed excludes the target task's solution and is not injected as feedback after failure. CUMULATIVE_PROJECT: each model starts from the same raw starter and canonical six-task plan, then preserves its own real previous code, tests and handoffs; failures block successors without replacement. Hash the initial/seed/prior-code inputs, implement fresh-session and failure classifications, retain original v1 runner as historical comparison.

**Acceptance:** Isolated comparisons have identical input hashes across models for the same task; cumulative runs preserve model-produced predecessors and do not claim later workspaces remain byte-identical. A failed stage is not filled with assessor/reference code; v1 behavior and historical runs remain unchanged.

**Change from the pre-audit list:** A common plan does NOT imply common starting code for later sequential tasks. Both measurements are necessary to avoid unfairly attributing upstream implementation differences.

### T11 — Extend Tester qualification with controlled implementation fixtures
**Status:** NOT STARTED · **Priority:** P1 · **Complexity:** Medium · **Dependencies:** T02, T10  
**Where:** local-model-bench: additive v2 Tester fixtures and evaluation; historical cases preserved

**Reuse:** Historical Tester cases A/C/D, reference-correct/defective fixtures, project Tester run_probe and captured independent acceptance.

**Bounded work:** Add known-good and single/multiple-known-defect candidates, shallow/false-green tests, broken test infrastructure, missing coverage, and actual Worker code snapshots from the two projects. Tester may run/repair tests within authorized file scope but must not edit implementation. Evaluate correctness of PASS/FAIL/BLOCKED plus usefulness/validity of new tests and evidence. Avoid automatically equating a bad Worker artifact with a bad Tester.

**Acceptance:** A correct FAIL on deliberately broken code is scored as successful Tester behavior. False PASS on a critical defect, unauthorized implementation changes or fabricated execution are failures. Environment failures remain BLOCKED/attributed, not model defect by default.

**Change from the pre-audit list:** Project Tester probe uses arbitrary Worker artifacts without frozen known-good/bad comparison; historical controlled cases already provide a reusable precedent.

### T12 — Extend Reviewer qualification with evidence-grounded cases
**Status:** NOT STARTED · **Priority:** P1 · **Complexity:** Medium · **Dependencies:** T10, T11  
**Where:** local-model-bench: additive Reviewer fixtures and rubric

**Reuse:** Historical six Reviewer contrast packets, DSH final Reviewer prompt, project Reviewer probe's existing code-hash matching metadata.

**Bounded work:** Create known accepted, defective, fabricated-claim, stale-code-hash, scope-drift, missing-test, contradictory-evidence, blocked-infrastructure and post-repair fixtures. Reviewer gets real code and bounded evidence, read-only; it may not assume Tester/Worker prose is proof. Evaluate PASS/FAIL/BLOCKED against a human-reviewed oracle, including explicit uncertainty when evidence is inadequate.

**Acceptance:** Reviewer catches contradictory/stale evidence, recognizes genuinely sufficient proof, does not edit artifacts or invent tests and correctly reports blocked evidence. Outputs remain advisory; no role assignment or action authority from first-line PASS.

**Change from the pre-audit list:** Current synthetic reviewer cases and project probes are useful but do not independently score complete Assistant project evidence across known truth conditions.

## Evidence, existing DSH integration and regressions

*T13–T15 · extend known tooling, do not build a second orchestrator*

### T13 — Extend evidence schema and failure attribution without replacing review writer
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T06, T08, T10, T11, T12  
**Where:** local-model-bench: additive fields/adapters to V2 review/records and qualification reports

**Reuse:** flashnext_review CSV/XLSX/JSON, trial identifiers, raw model/config/role events, file and assessor SHA snapshots, output/telemetry.

**Bounded work:** Record evaluation_track and worker_mode, actual runtime transport (direct Ollama vs native DSH), base model/digest/quantization/config, pinned reference/intent/governance hashes, initial/prerequisite workspace identity, case and acceptance refs, actual prior artifact refs, first-pass/repair stats, human adjudication and origin-of-authority. Distinguish candidate error, upstream-blocked, tooling/schema, deterministic scope denial, observed test failure, missing evidence and harness error. Expose non-equivalence rather than aggregating incompatible runs. Preserve historical report fields and schema readers.

**Acceptance:** A reviewer can reconstruct each candidate's exact supplied inputs, approval source and tested code hashes; duplicate and stale evidence cannot be silently counted. Old reports/GUI remain readable; missing evaluation evidence produces PENDING/BLOCKED rather than an invented PASS.

**Change from the pre-audit list:** Existing reporting is rich, but lacks substantive role-oracle verdicts, track identity and defensible cross-harness failure attribution.

### T14 — Verify and adapt the existing native DSH full pipeline for integration trials
**Status:** NOT STARTED — native source exists; installed state unverified · **Priority:** P0 · **Complexity:** Large · **Dependencies:** T02, T09, T13  
**Where:** deepseek-lab native harness (owner-authorized changes only) + thin local-model-bench adapter

**Reuse:** DSH development source has release-bound Planner/Governor, WorkerDispatcher, Tester, Repair Worker and final Reviewer with saved handoffs and evidence. Native queue/owner release must remain the only execution authority.

**Bounded work:** FIRST compare the local installed DSH checkout/process, running version/branch, models, profiles and canonical Governor files against reviewed development source; capture provenance privately and stop if out of sync. Identify supported native release/plan/dispatcher interfaces and wire controlled test packets without bypassing owner-origin release authority or changing hashes after approval. For INTEGRATION use actual Planner plan and Governor advice under the existing safe controller gates, then actual Worker/Tester/repair/Reviewer outputs; no replacement Planner plan in this mode. Use existing native pipeline/verification dispatchers; do NOT recreate them in Python/GUI or treat a Governor approval word as owner permission. Verify native run status and actual tool evidence.

**Acceptance:** One synthetic/no-inference native release trial traverses the existing stage boundaries with reproducible trace and correct block/deny/repair/stop paths, or reports a concrete installed-version/integration blocker. No duplicate controller, no forged release receipt, and no claim of live full-pipeline qualification without actual model evidence.

**Change from the pre-audit list:** Formerly 'implement full pipeline'; audit found it implemented on a separate DSH development branch. The new work is provenance reconciliation, safe adapter integration and qualification rather than rebuilding orchestration.

### T15 — Regression-test authority, isolation, parity and failure propagation
**Status:** NOT STARTED · **Priority:** P0 · **Complexity:** Large · **Dependencies:** T05, T08, T10, T11, T12, T13, T14  
**Where:** local-model-bench tests/workflows; DSH native test files as required

**Reuse:** Prior Windows/Linux Python tests, native DSH node synthetic tests, GUI native PowerShell routing fixtures and acceptance calibrations.

**Bounded work:** Add focused tests for direct/indirect reference leaks, version drift, forged Governor grants, wrong plan/role, task-seed contamination, stale prerequisite hash, inherited bad code, no-gold continuation, false passing oracles, invalid reviewer evidence, missed test commands, runtime/transport mismatches, OS/tool failure, interrupted checkpoint/pause and refusal to auto-retry. Run original role battery/Assistant-001/002 GUI regressions and new code tests on supported Windows/Linux interpreters. Native DSH tests should use controller fakes before any real-model pilot.

**Acceptance:** Deliberately injected critical faults are detected and attributed; both new tracks/Worker submodes remain distinguishable; old frozen packets are byte-identical to the recorded baseline; all applicable CI jobs pass. A missing installed-native verification remains a blocker, not a skipped PASS.

**Change from the pre-audit list:** Existing tests cover component execution, not v2 authority/comparability/leakage or native-Dsh integration semantics.

## GUI, real-model pilots and release

*T16–T18 · add modes to existing queue only after the CLI contracts work*

### T16 — Extend the existing GUI to select evaluation track and role
**Status:** NOT STARTED — original GUI already supports three benchmarks · **Priority:** P1 · **Complexity:** Medium · **Dependencies:** T14, T15  
**Where:** local-model-bench: queue_gui/core.py, app.py, existing PowerShell proxy + tests

**Reuse:** Current three-benchmark selector; dynamic project tasks; per-entry saved phase/model/settings; native Windows PowerShell arg forwarding; pause/stop/close/recovery and review workbook.

**Bounded work:** Once v2 runner flags/contracts pass CLI tests, extend per-item selection to controlled role cases, isolated Worker task, cumulative Worker chain or native DSH pipeline integration. Show the currently selected role/case/plan/track and runtime provenance, not just T01–T06; support explicit comparison reports. Retain existing legacy selections and saved queue-state migration. Warn/confirm candidate host execution; do not automatically enable sandboxless code, native releases, production devices or permissions.

**Acceptance:** Two different tasks/tracks for one model are safely queued, restored and routed through supported existing CLI/native adapters. Old queues migrate; initial launch, pause/stop and abandoned session recovery work; Windows UI/PowerShell tests pass with no live model calls.

**Change from the pre-audit list:** A project selector already exists; only qualification mode/role selection, truthful outputs and new-runner routing remain.

### T17 — Pilot actual models on frozen role cases and the native integration chain
**Status:** NOT STARTED — no real model runs for this change · **Priority:** P0 · **Complexity:** Medium · **Dependencies:** T15, T16  
**Where:** User's Windows benchmark/DSH host; disposable workloads; local-state evidence only

**Reuse:** Screen/Qualification model queue, validated per-task packet IDs, independent acceptance and native DSH release/Tester/review runner.

**Bounded work:** Begin with independent Planner and Governor comparisons using two candidate configurations against identical snapshots, then one canonical isolated Worker task, a full progressive Worker chain, known-good/known-bad Tester/Reviewer cases, and a bounded two-task native DSH integration release. Inspect failures manually between steps rather than looping arbitrary patches; record hardware, runtime, quantization, context, wall-clock, generation, tool tests and observer overhead separately. Use known-safe disposable workspace/VM for untrusted generated Python and explicit owner approval for native release.

**Acceptance:** Evidence shows same-case, same-reference independent role comparisons and a separately labeled end-to-end trial. Model failure vs bad upstream artifact vs DSH/harness/tool failure is attributable. Human role review is recorded; repeats are described as repeatability, not statistical independence; no automatic model promotion.

**Change from the pre-audit list:** Without real candidate runs neither v1 machinery nor v2 roles are genuinely qualified. DSH branch existence/CI cannot substitute for installed/real-model verification.

### T18 — Freeze v2 qualification release with human-reviewed results
**Status:** NOT STARTED · **Priority:** P1 · **Complexity:** Small–medium · **Dependencies:** T17  
**Where:** local-model-bench: versioned v2 release docs/manifests and completion evidence

**Reuse:** T01 baseline record, v1 manifests, available run/CI evidence, v2 artifacts and review workbook.

**Bounded work:** Version and freeze exact project references, governance scenario conditions/hashes (not private canonical bytes in public repo), case inventory, reference plan/Worker handoff IDs, evaluation rubric, runtime/transport contract, model settings, known deviations, support/stop conditions, Windows launcher and human review verdicts. Confirm baseline protected files remain unchanged or clearly versioned if an exception was authorized.

**Acceptance:** A separate reviewer can reproduce screen/qualification selections without reconstructing old chats; project v1 remains runnable; deployment/role assignment requires explicit later owner decision; any missing evidence is recorded as a limitation, not silently passed.

**Change from the pre-audit list:** Release now explicitly covers multi-track provenance and DSH verification, not simply packaging more cases.
## Implementation boundaries / avoid-regression checklist

- Preserve `project-benchmarks/assistant-001/v1/`, `project-benchmarks/assistant-002/v1/`, the accepted historical role suite and prompts. New references live under versioned `qualification-v2/` subfolders and new shared qualification modules. Original `TASKS.md` stays the **fixed Worker plan**, not an independently produced Planner result.
- The baseline JSON is **observational**, not a branch-protection hook. T02/T15 must define/enforce protected-input comparisons while allowing reviewed additive changes to implementation files; do not require all executable files to retain historical hashes.
- The existing `localbench.assistant001.campaign`, `localbench.assistant002` packet adapter and V2 evidence writer are first-class reuse targets. Native DSH `release-pipeline` / verification dispatchers remain in their own repo/runtime.
- Generator output and reference oracle are separate. Candidate planners receive no `TASKS.md` via direct prompt, snapshot, filesystem read or file metadata. Governor references are fixed within comparison groups; Workers get a controller/human-reviewed reference, never a candidate's unconstrained output.
- Simulated conditional permissions are **not** production authority. Private Law/State/General Intent content is loaded from the operator's governance root and hashed in restricted evidence; no owner identity is inferred from public GitHub access.
- Accept natural-language Planner/Worker/Tester/Reviewer handoffs; evaluation records are structured independently. Include human review for semantic planning, correct governance rulings and Reviewer judgments.
- Candidate Python execution remains **not OS/network sandboxed**. Record explicit approval and use disposable environments; no live cameras, KC writes, Home Assistant actions or production deployment.
- The historical 23-case role screen, GUI queue persistence and existing A001/A002 screen/qualification commands must remain usable. New DSH qualification is additive and separately identifiable.

## Audit-derived changes to earlier assumptions

- **Earlier:** Build a new full five-role pipeline in T14. **Now:** Reconcile the native DSH development branch with installed reality, reuse release/verification dispatchers and qualify the existing pipeline.
- **Earlier:** Remove a reference task list from the Planner prompt. **Now:** Remove both prompt and workspace exposure, including indirect file/metadata/tool routes.
- **Earlier:** All Workers receiving one plan are fully comparable. **Now:** The isolated-task mode has identical source prerequisites; the cumulative-project mode separately reports model-specific prerequisite artifacts.
- **Earlier:** Governor's plan review and handoff generation is largely missing. **Now:** It already generates advisory review; the missing elements are frozen scenario truth, comparative scoring, and a trusted, separately authorized reference handoff.
- **Earlier:** Tester/Reviewer case sets need construction from scratch. **Now:** Extend proven historical fixtures and current project probes, preserving their originals.
- **Earlier:** A new GUI project selector is necessary. **Now:** The GUI already selects the three benchmark types; only controlled role/track selection and native integration routing remain.
- **Earlier:** Existing review writer may need replacement. **Now:** Extend the existing artifact writer with reference hashes, mode IDs and attribution without breaking v1 fields.
- **Earlier:** Source CI implies native readiness. **Now:** Treat installed Windows DSH provenance and a genuine real-model full pipeline as unverified until T14/T17 provide evidence.

## Next authorized implementation unit

**T02 only.** Define mode/authority/disclosure contracts and acceptance checks. It must not change frozen v1 packets, initiate model execution, deploy a DSH process, or decide owner authority without an explicit source. T03 and T04 can then proceed using already-built project task sequences.
