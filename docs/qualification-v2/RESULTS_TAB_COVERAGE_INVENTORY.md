# Results tab: existing evidence and capability coverage inventory

**Audit type:** Read-only source inspection for qualification-v2 backlog planning. **Source:** `floydtrey/local-model-bench`, branch `benchmark/flashnext-all-roles-v1`, commit `478c158ed48709a4a4ede2f8541c9bafb980596d`. **Date:** 2026-10-08.  
**Execution claim:** No Results tab, new capability battery, live model run, local `local-state` inventory or Windows/runtime compatibility experiment was performed by this documentation change.

## 1. Existing ownership boundaries — reuse, do not replace

| Existing source | Verified function | First Results-tab use |
| --- | --- | --- |
| `src/localbench/queue_gui/app.py`, `core.py`, `process.py` | Tkinter benchmark selection, one-process-at-a-time queue, live stdout/stderr, `RUN_DIR`, persisted queue settings, recovery, open review workbook | Add a **Results tab inside this same GUI**, with a read-only report adapter. Do not change queue process ownership, start a second server or introduce a state database. |
| `src/localbench/v2/flashnext_review.py` | Owns `review-package.json`, `case-results.csv`, `role-summary.csv`, XLSX, plus recovery/performance views | **Extend this writer** to emit versioned case membership/metrics; do not independently compute new authoritative scores in the GUI. Existing documents continue to load. |
| `src/localbench/v2/reporting.py`, `schemas/v2/aggregate-report.schema.json` | Repeated-trial aggregate evidence, per-evaluator verdicts/scored values, evaluator refs, normalized score, planned versus observed trials, separate raw evidence | Reuse aggregate score evidence only with its exact evaluator/suite identity. An aggregate over repeated attempts is **not a count of independent cases**. |
| `src/localbench/assistant001/cli.py`, `assistant002/cli.py`, `assistant001/campaign.py` | Actual direct-Ollama fixed-plan Worker execution and advisory probes; original runner emits `summary.json`, `runner-inputs.json`, run evidence | Read already-produced artifacts, including per-task pass/blocked and first-pass flags. Do not reclassify CLI exit code as a role PASS. |
| `campaigns/flashnext-all-roles-v1/role-suite.json` | Frozen Planner/Governor/Worker/Tester/Reviewer case registry with advisory/human-reviewed outcomes | Five-role case registry for drilldown and provisional suitability views. No automatic assignment or hidden standard inferred from case counts. |
| `benchmark-packs/v2/shared-l0-core-v1.json`, `shared-l1-core-v1.json`, `shared-l2-core-v1.json` | Released, tagged synthetic text and bounded-tool cases | Candidate capability-category sources **only after an explicit reviewed category/case mapping and scoring rule**. |

**Current GUI state:** It currently has no Results tab; it displays queue item, model, status/exit, task, elapsed time and run folder, plus terminal and workbook-opening actions. Stored local report directories are not indexed into a chart. No actual model scores were verified here. Having a pack file or CI validation is **not** evidence that a given model ran it.

## 2. Existing case inventory (distinct IDs versus acceptance checks)

| Family | Defined units | Source behavior and limits |
| --- | ---: | --- |
| Shared L0 (prompt only) | **9 distinct cases** | Instruction precedence, structured transform, missing context, contradiction, dependency plan, code diagnosis, authority, ambiguity, output discipline. Minimum context in these cases: 2,048 tokens. No tools/images. |
| Shared L1 (controlled textual evidence) | **5 distinct cases** | Traceability, conflicting sources, lifecycle/current selection, repair diagnosis, evidence gap. Small **inline UTF-8 text** assets; minimum context 4,096 tokens. Not a long-context recall battery. |
| Shared L2 (bounded file tools) | **8 distinct cases** | Transform/write, evidence read, safe update, minimal code repair, multifile synthesis, missing-file block, scope restraint, no-op. Tests bounded read/write protocols and evidence-based tool use; not full open-ended multi-tool routing. Minimum context 4,096 tokens. |
| Historic all-role suite | **23 distinct cases** | Planner 6; Governor 4; Worker 4; Tester 3; Reviewer 6. Some evaluated deterministically; Planner/Governor/Reviewer correctness requires human review. Tester-known-bad cases can validly produce model verdict FAIL while the **Tester itself succeeds**. |
| ASSISTANT-001 Worker project | **6 bounded cumulative tasks** | 79 **cumulative acceptance checks**, including generated invalid-input checks. Scoring a task is not equivalent to 79 independent case outcomes. Project has real work and persistence/repair risks. |
| ASSISTANT-002 Worker project | **6 bounded cumulative tasks** | 96 **cumulative acceptance checks** including eight authored simulator scenario fixtures. These cases assess the produced simulator's correct code behavior; they do **not** directly prove that an AI model can autonomously recover from a tool failure. |

Screen 1 and qualification 3 repetitions increase **attempts**, not unique case IDs. Across the 22 shared prompts, the 23 historic role cases and 12 Worker tasks, scope and execution mode differ; **never sum these numbers into an overall intelligence score**.

## 3. Requested capability charts — current evidence and honest display

| Desired capability | Relevant currently authored evidence | Honest initial chart treatment | What still needs test expansion or approval |
| --- | --- | --- | --- |
| Reasoning | L0 `contradiction-detection`, `dependency-plan`; L1 `conflicting-sources`; independent Planner scoring planned | Potentially chart **narrow, versioned source/rubric-defined** reasoning submetrics if actual assessed case reports exist. Never call a generic heuristic “reasoning percent”. | T13 metric membership/score basis; T06 and T07–08 reviewed role decisions; T19 adds calibrated targeted cases when needed. |
| Coding | L0 `code-diagnosis`; L2 `minimal-code-repair`; four historical Worker cases; A001/A002 Worker task outcomes | Existing evaluated file/task outcomes and **per-case diagnostic/code-repair** results can appear with precise scope and provisional labels. | Reviewed full implementation scoring, isolated vs cumulative Worker mode, role evidence from T10–T12. |
| Vision | **No image/vision cases in inventoried L0/L1/L2 packs or historic/Assistant project suites.** Current inspected V2 Ollama and llama.cpp request adapters pass **string** messages and inline UTF-8 context assets, not an image-message path. | **Not tested — no bar, no percent.** Mark **Unsupported** only for a specific runtime/configuration independently verified unable to accept required image input; lack of tests alone is not proof model lacks vision. | T19: inspect required image-capable adapter, exact model/runtime input support, synthetic assets, versioned tests and calibrated scoring, then T13 export. |
| Tool use | L2 eight case suite; model tool-call traces and scope checks; historical Worker tool execution | Can show specific bounded-tool case evidence and tool failures with exact denominator if corresponding evaluated reports exist. | Separate semantic tool-choice/route cases from mere count of tool calls (T19), and versioned category/scoring mapping (T13). |
| Instruction following | L0 `instruction-precedence`, `output-discipline`, `structured-transformation` and role scope checks | Versioned narrow instruction-following outcome if evaluated; note format/scope-specific nature. | T19 targeted calibrated instruction hierarchy and instruction drift cases; human review where required. |
| Long-context recall | Shared L0 text tasks use min 2K, L1/L2 min 4K; L2 “retention-pair” tags are short bounded-tool retention probes | **Not tested — no bar, no percent.** Evidence retrieval of a short snippet is **not** long-context recall. | T19 calibrated long-context input retention/recall tests with verified context length, controlled distractors, positional swaps, truncation tests and token-budget provenance. |

No category gets a score solely because a candidate model is installed, a role case is *defined*, or the GUI has a slot for it. Bars display only eligible **evaluated** cases under a reviewed scoring source and versioned category membership. Failed/blocked/unknown must remain distinguishable; a “0%” requires genuine scored attempts, not absent data.

## 4. Assistant-specific panels — reuse or new evidence

| Requested panel | Existing relevant source(s) | Truthful display scope |
| --- | --- | --- |
| Multi-step tasks | Historical Intent04 Worker sequence; A001/A002 six-stage projects | Task completion and blocked-successor trace from actual runs; identify original-case vs project task denominator, per-task first-pass versus final. |
| Tool selection | L2 chosen read/write actions, model tool-call traces | Bounded tool correctness and restraint can be displayed; **not yet** a general multi-tool semantic router/selector score. |
| Error recovery | L1 repair diagnosis, L2 minimal code repair, A002 checkpoint-replay implementation checks, historical worker repair flags | Separate *model repair behavior* from *code that correctly implements recovery*. Never blend them into one metric without a reviewed rubric. |
| Permission boundaries | L0 authority-boundary, L2 scope-restraint, historical Governor decision cases | Case outcome, actual denied tool attempts and critical unsafe approvals (once reviewed); a refusal may be correct, not a failed execution. |
| Evidence accuracy | L1 evidence-traceability/conflicting-sources/lifecycle, Reviewer evidence contrasts and hash-matching project probes | Grounded response/correct evidence identification; distinguish candidate claims and independent executed command/evaluation evidence. |

## 5. First Results-tab data versus future v2 and new tests

**Available from EXISTING STORED REPORTS when they are present in the user's checkout** (new read-only GUI loader required): model string, role and case IDs, suite/run label if recorded, screen/qualification phase, ordinal, execution status/stop reason, measured token/runtime/tool/retry counts, deterministic pass where actually assessed, first-pass/repair flags, review-required flag, output run directory, workbook link, and underlying per-case evidence. Some earlier reports lack model digest, quantization, suite/rubric version or explicit track: treat each as **Unknown / not eligible for cross-configuration aggregate**, not zero or automatic PASS. A developer must inspect individual run formats before mapping.

**Requires T13 reviewed report normalization:** publish metric dictionary, category membership, numerator/denominator (unique case grain), suite/evaluator version, source and evidence refs, config/runtime comparison key, first-pass vs repaired outcomes, distinct failed/blocked/not-attempted/not-tested/unsupported/review-pending states. The GUI consumes these exports read-only.

**Requires T06/T08/T10–T12 v2 assessment:** genuinely assessed Planner/Governor equivalence, isolated-vs-cumulative Worker measurement, controlled Tester/Reviewer truth labels, and versioned suitability matrix rules. In the interim, suitability cells should say `Provisional — review pending` or `Not assessed`, with case counts, not a newly invented “Qualified”.

**Requires T19 new cases:** vision, true long-context recall and any uncovered high-quality general tool selection/reasoning/instruction-following use cases. Until then relevant categories explicitly say `Not tested` with no bar or score. **T19 is not a prerequisite to the first Results tab, T16 completion, pilot T17 or release T18.**

**No universal intelligence score. No automatic model assignment.** A zero-capable/unsupported runtime is not the same as a model tested and failing. Local `local-state` may contain private evidence; the Results tab should open trusted local run references, not upload raw context or publish private governance content.

## 6. Test fixture inventory required by T13/T15/T16 (not implemented by this planning update)

1. Mixed-case outcomes: distinct scoped `PASS`, `FAIL`, `BLOCKED`, `NOT_ATTEMPTED`, `NOT_TESTED`, `UNSUPPORTED` and `PENDING_REVIEW` with source-specific evidence.
2. Legacy record missing rubric/category, quantization, metric and human decision → null/unknown, never `0` or `PASS`.
3. Untested vision and long-context cases → no bar and no fabricated denominator; runtime may be eligible, but test absent.
4. Blocked downstream A001/A002 tasks → count only tasks actually assessed; preserve blocked status, excluded from incorrect-model isolated-task failures.
5. Pending human review on Governor/Planner/Reviewer → provisional matrix, no earned final suitablity.
6. Incompatible suite/rubric version or mixed Worker mode/transport/context/role input → clear reason and exclusion from combined percentage, while original case rows remain accessible.
7. Tester correctly FAILs a known-defective implementation → **Tester success**, not a zero score based on the underlying code defect.
8. Duplicate/repeated attempts or 79/96 cumulative checks → distinct-case denominators, separate attempt/check counts, no inflated sample size.
9. First-pass FAIL then bounded-repair PASS → separate first-pass and final-after-repair rates, evidence retains both attempts.
10. Clicking any chart bar, matrix cell or case row must resolve **exact suite/case/ordinal/artifact hash and source evidence**, or report evidence unavailable without opening a mismatched case.

This document inventories **defined cases and supported code paths**, not completed model metrics. Future Results UX/metric implementations belong in the existing Tk GUI and shared JSON/CSV/XLSX writer, not an additional dashboard/backend/database.
