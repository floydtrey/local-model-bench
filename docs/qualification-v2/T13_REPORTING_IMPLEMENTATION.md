# T13 — Reporting contract and metric normalization

**State:** COMPLETE. All material reporting conditions and the supported Windows/Linux Python 3.10/3.12 matrix passed; see the [acceptance record](T13_ACCEPTANCE_20261009.md) for the exact implementation commit, 524-test regressions and CI links. This completes the reporting contract, not model qualification or additional capability coverage.

**Ownership:** The existing runners execute, the existing assessors decide outcomes, and `flashnext_review.write_review_package` exports authoritative review packages. `metric_projection` derives declared aggregations only. `report_adapter` reads existing files. No GUI Results tab, dashboard, database, backend, scheduler, inference, new agent capability battery, or role assignment was added.

## Audit of the inherited implementation

| Inherited component | Reused | Defect or gap corrected |
|---|---|---|
| `METRIC_CATALOG_V1.json` | All 16 metric IDs | The shared evaluator ID/version did not match the released L0/L1/L2 evaluators. Multi-file text synthesis was incorrectly included as coding. Role criteria and Assistant definitions were placeholders. |
| `metric_projection.py` | Case projection and conservative null semantics | Mixed configurations were discarded instead of separate series; incomplete identity was accepted; counts were row counts; repetitions/repair policy was absent; evidence directories were accepted without checking files; excluded cases disappeared from metric detail; dictionary human reviews were not recognized. |
| `report_adapter.py` | Read-only legacy loading | V2 aggregate and controlled qualification formats were absent; many original fields and workbook links were dropped; exact source provenance was incomplete. |
| `flashnext_review.py` | Existing JSON/CSV/XLSX implementation and paths | Projection consumed serialized cells instead of original records; export omitted first/repair, membership, configuration, coverage, eligibility and detailed exclusions. |
| Existing T05–T12 assessors | Verdicts and authority boundaries | Added report identities and hashes immediately after existing assessment writes; no semantic evaluator or execution rules replaced. |
| Queue GUI | Existing queue/process/event ownership | Discovery retained the Tk app in a background closure; fixture teardown left closed interpreter cycles for later collection. See the isolated lifecycle correction below. |

## Version and inventory

The catalog retains its `qualification-v2/metric-catalog:v1` container with definition revision **1.1.0**. The corrected, additive projection is `qualification-v2/metrics:v2`; the read adapter is `qualification-v2/legacy-read-adapter:v2`. The original outer `flashnext-role-review-package:v1` and its columns remain intact. The report embeds the catalog revision and SHA-256; definitions include source and rubric paths, exact IDs, objectives, authority, minimum coverage, exclusions, evidence policy and aggregation/comparison rules.

| Metric | Exact scope / coverage |
|---|---|
| Reasoning | L0 contradiction-detection and dependency-plan (2 cases) |
| Coding | Separate L0 code-diagnosis and L2 minimal-code-repair series (1 case each); no blended coding percentage |
| Vision | **Not tested**, no cases or score |
| Tool use | The 8 released bounded file-tool L2 cases |
| Instruction following | L0 instruction-precedence, structured-transformation and output-discipline (3) |
| Long-context recall | **Not tested**, no cases or score |
| Planner suitability | 4 controlled cases: complete and missing-goal for both projects |
| Governor suitability | 28 controlled frozen-governance cases |
| Worker suitability | 12 controlled project task slots; isolated and cumulative modes remain separate |
| Tester suitability | 16 controlled implementation/testing cases |
| Reviewer suitability | 20 controlled evidence-review cases |
| Assistant multi-step tasks | 3 L2 ordered file-action cases: read-transform-write, safe-existing-update, multi-file-synthesis; this is bounded execution, not autonomous project planning |
| Assistant tool selection | **Insufficient coverage** for general competing-tool selection; no score |
| Assistant error recovery | **Insufficient coverage** for agent recovery from failed tools; no score |
| Assistant permission boundaries | Separate L0 authority-boundary and L2 scope-restraint series |
| Assistant evidence accuracy | L1 evidence-traceability, conflicting-sources, lifecycle-selection, evidence-gap (4) |

There are 16 metric definitions and 18 source projections before splitting configurations. A001/A002 implementation acceptance and the historical role battery stay available as their own evidence. Implementation of checkpoint/replay logic does not earn an agent error-recovery score. Historical text tags never manufacture suite versions or capabilities. Vision/long-context and the remaining capability gaps belong to T19, which was not started.

## Independent execution, outcome and adjudication

Every normalized case retains original source fields alongside `execution_status`, `normalized_assessed_outcome`, `human_review_state` and `normalized_status`. Process success is never sufficient for assessed PASS. Infrastructure failures remain unknown model outcomes. Explicit blocked/unattempted/unsupported/not-tested states remain visible even if a contradictory source also claims PASS; the contradiction is excluded with a reason.

Required substantive human review must be a declared review record bound to input, candidate and rubric hashes, and match the assessment artifact. A bare `approved`, `recorded`, or `not_required` string cannot bypass required review. Declarations are not authenticated human identity or independent certification. Candidate review and reference review remain separate. A source explicitly marked comparison-ineligible remains provisional after candidate review; a mismatched role cannot support another role's criterion. A declared reference approval needs matching, hashed substantive reference-review evidence before the strongest descriptive role label is available.

A Tester correctly deciding FAIL on defective implementation retains a successful Tester assessed outcome. The underlying implementation truth and candidate decision are separate fields. The Planner rubric's validated, justified BLOCKED disposition on a missing-goal case supports the role criterion while the original BLOCKED outcome remains preserved. This exception is explicit in catalog membership; ordinary blocked execution never scores.

## Units and aggregation

- `planned_cases`: declared metric/source membership size; `distinct_cases`: observed distinct case IDs.
- `distinct_evaluated_cases`: observed independent PASS/FAIL assessments, even when substantive review still gates final scoring.
- `attempted_cases`: unique cases with observed execution; `attempt_count`: actual executed attempt rows. Blocked, waiting, unsupported and not-attempted rows do not add attempts.
- Status case lists preserve observations, including failed first attempts. `final_passed_cases` and `final_failed_cases` preserve the final eligible case classification.
- `repeated_trials`: extra fresh trial identities beyond one per case; never added to the case denominator.
- `acceptance_checks`: per-row check observations with their own unit. `acceptance_check_count` at the combined metric level remains null: cumulative observations cannot be summed as independent challenges. **79 A001 / 96 A002 checks are never case denominators.**
- Numerator: distinct eligible cases succeeding under the declared policy. Denominator: distinct eligible assessed cases. No eligible denominator means null, not 0. A real 0/5 is 0%.
- Published capability sources require all their listed cases before displaying a percentage. Partial exact numerator/denominator and coverage/exclusions remain visible, but percentage is withheld. Role suitability has no percentage at any coverage.

**Repetitions:** `all_predeclared_trials_pass`. A case contributes one success only if all its predeclared fresh trials succeed. One failed trial yields one failed case, never a new challenge. Trial IDs, ordinal population, repeat group and planned count must be complete and unambiguous. Undeclared repetitions, missing trials, duplicate identities and unresolved outcomes are excluded; no best-trial selection.

**Repairs:** Attempts must be contiguous and explicitly linked within one run/trial. The initial attempt determines first pass; the final attempt determines the final result. A failed initial attempt followed by a successful repair earns one final success and one repaired success, never two successes. Repair rate uses only distinct repaired cases; first-pass rate uses distinct eligible cases. Collapsed legacy repair fields are accepted only with both initial and repair evidence. A final result with unknown first-pass/repair history retains null first-pass and repair rates; claimed repairs without required provenance are excluded from scoring.

## Identity, eligibility and evidence

Configuration series retain exact model name/digest/quantization, runtime/version/transport, context and effective settings when observed. Available sealed model/runtime references and per-turn effective configurations are resolved read-only from hash-checked event logs. All observed configurations remain in the report. As in the existing Governor comparison, a recorded original case timeout budget supplies configuration identity while exact diminishing per-call timeouts remain in the observations; no missing budget is invented. Unknown legacy values remain unknown and ineligible, including unspecified quantization. No model name is parsed to invent a digest or settings.

Compatibility requires the same metric/source/rubric versions, evaluation track, role, mode, protocol, authority assumptions, assessor/evidence versions and complete case population with matching per-case input/reference/rubric hashes. Different model configurations remain separate series and may share a comparison group. Different protocols, versions, modes or material inputs get explicit exclusions. `comparisons` describes pairwise reasons; there is no combined configuration score.

All normalized rows remain in `case_details`, including unmatched versions and excluded cases. `case_refs` connects each metric to exact row/case/run/trial/attempt, files and hashes. Files are checked for absence and SHA-256 mismatch; source assessment outcomes and review bindings cannot be overridden by summary claims. Artifact/candidate hash mismatches invalidate eligibility. Relative references require an explicit source root, preserved across re-exports. No historical report or evidence is modified.

V2 aggregate reports are expanded using their sealed original case/evaluator/trial/configuration/execution references. Their trial-average percentages are not converted to case results. Missing or tampered sealed records leave a discoverable unknown case. Source pack versions are reconstructed only from a hash-matching original pack; otherwise they remain unknown.

## Exports and compatibility

Existing paths/sheets/columns remain: `review-package.json`, `case-results.csv`, `role-summary.csv`, `review-package.xlsx`, Model Summary, Role Scorecard, Case Results, Controller Recovery, Performance. The inherited metric CSV and Metric Summary are extended. Added projections are `normalized-cases.csv`, `metric-cases.csv`, `metric-comparisons.csv`, and matching workbook sheets. Nested values use deterministic JSON cells; nulls are blank, not zero. Oversized new projection values exceeding Excel's 32,767 UTF-16-unit cell limit are losslessly continued in `<column>__part2`, `__part3`, etc., in both CSV and XLSX; concatenate those parts before parsing JSON. Existing values that fit a cell retain their exact column representation. The complete JSON object remains authoritative. JSON includes full normalized detail and versioned metrics.

`normalize_legacy_report(path, evidence_root=...)` supports historical role packages, Assistant summaries, qualification summaries and raw/sealed V2 aggregate reports. It preserves original fields and workbook references. `write_normalized_review(source, new_output, evidence_root=...)` uses the same existing writer, refuses existing output and leaves the source untouched. The GUI remains a future read-only consumer.

## GUI lifecycle correction (outside reporting, isolated regression scope)

[Failed Windows 3.10 run](https://github.com/floydtrey/local-model-bench/actions/runs/37976683704) aborted during `test_reopen_preserves_completed_and_waiting_evidence_without_auto_run` with `Tcl_AsyncDelete: async handler deleted by the wrong thread`. The GUI code predates T13 (last change `79d422e`); the other three jobs passed. This is a pre-existing lifetime hazard exposed intermittently by allocation/collection timing, not evidence of a model-report scoring failure.

Two mechanisms were found: model discovery captured `self` (and therefore the Tk interpreter) in its daemon thread; test fixtures retained closed apps through a bound discovery callback/test-instance cycle. A background allocation can collect an unreachable Tcl interpreter on the wrong thread. [Python's Tk threading model](https://docs.python.org/3/library/tkinter.html#threading-model) and [CPython issue 39093](https://bugs.python.org/issue39093) describe this ownership hazard.

The correction uses a module-level discovery function receiving only the callable and event queue, and explicitly releases closed fixtures/collects their cycles on the owner thread before later workers run. Queue scheduling, process ownership, close semantics and Windows coverage are retained. A deterministic ownership probe reports baseline `worker_retains_owner=True`, corrected `False`; the real-widget regression closes while discovery is blocked and proves the app is released before the worker resumes. The old CI log contains no deallocation stack, so its exact doomed object cannot be identified retrospectively. The demonstrated hazards and full acceptance matrix, rather than a lucky rerun, support the correction.

## Boundaries

T05–T12 assessor decisions, frozen v1 packets, historical source artifacts, queue commands and the permanent Windows installation are preserved. Changes to producer rows only add provenance/check counts. Flash-Next remains suspended; no runtime/startup/transport changes or troubleshooting were performed. T14, T16 and T19 were not started. Existing T10 real-seed and T11/T12 real-artifact/human-review limitations remain visible and do not become fabricated reporting scores.
