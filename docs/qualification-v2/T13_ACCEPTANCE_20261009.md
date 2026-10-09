# T13 acceptance — 2026-10-09

**State: COMPLETE.** All material T13 reporting conditions, local deterministic verification and the supported Windows/Linux matrix passed. This accepts the reporting contract; no actual model qualification is claimed.

Development branch: `development/t13-reporting-contract-20261009`.
Inspected starting commit: `f0dbb035e5c03c2e9fb8f2dee9572f15e5cb7660`.
Verified implementation commit: `e1c41b6ceb55dbff7825066ff56a01b9f036329f`; the following acceptance commit changes documentation only.
Separate workspace: the task's `development` clone. Permanent installation was inspected read-only at `6624945ba7f9cca99071b4fc07a37e958770bca1`, branch `local/flashnext-startup-safe-20261009`, clean.

The [implementation contract](T13_REPORTING_IMPLEMENTATION.md), [versioned catalog](METRIC_CATALOG_V1.json), and [metric report schema](../../schemas/v2/metric-report.schema.json) define the delivered behavior. Existing `metric_projection`, `report_adapter`, `flashnext_review`, V2 sealed reports and T05–T12 assessment outputs were extended. No alternative reporting system was built.

## Material acceptance matrix

All test references below are in `tests/test_qualification_v2_metrics.py` unless noted.

| Requirement | Deterministic evidence |
|---|---|
| 1. Genuine scored PASS/FAIL, including 0/5 | `test_genuine_pass_fail_and_zero_of_five` |
| 2. Missing legacy fields | `test_missing_legacy_fields_never_zero_or_pass`; legacy adapter fixtures |
| 3–4. Untested vision/long-context | `test_vision_and_long_context_remain_not_tested`; catalog has no membership |
| 5. Blocked downstream Worker | `test_blocked_downstream_worker_is_not_an_attempt_or_failure`; existing Worker chain tests |
| 6. Pending human review | `test_pending_review_preserves_independent_assessed_pass`, `test_substantive_human_record_is_supported_and_hash_bound` |
| 7–8. Unsupported/not-attempted | `test_unsupported_and_not_attempted_have_no_score` |
| 9. Separate model configurations | `test_configurations_are_distinct_comparable_series`, `test_every_material_configuration_field_separates_series` |
| 10. Track/Worker modes | `test_tracks_worker_modes_and_authority_are_incompatible`, `test_comparison_pairs_explain_incompatibility` |
| 11. Suite/rubric changes | `test_changed_suite_and_rubric_are_excluded_but_discoverable` |
| 12. First FAIL / repaired PASS | `test_first_fail_repair_pass_is_one_final_success`, `test_invalid_repair_lineage_and_missing_first_attempt_are_excluded` |
| 13. Repeated trials | `test_repeated_trials_do_not_inflate_case_count`, `test_undeclared_repeats_and_duplicate_attempts_are_excluded` |
| 14. Cumulative 79/96 checks | `test_cumulative_79_and_96_checks_do_not_become_case_denominator`; both Assistant legacy fixtures |
| 15. Correct Tester FAIL | `test_tester_correct_fail_on_defective_code_is_success`; existing historical/controlled Tester regressions |
| 16. Stale evidence / changed artifact | `test_stale_hash_and_changed_artifact_are_excluded`, `test_rehashed_changed_artifact_cannot_match_original_identity`; sealed-record tampering fixtures |
| 17. Missing evidence | `test_missing_evidence_is_discoverable_and_not_zero`, `test_unrelated_hashed_file_is_not_an_assessment`; missing raw aggregate execution fixture |
| 18. Contradictory outcomes | `test_contradictions_preserve_execution_and_assessment`, `test_changed_summary_cannot_override_assessment` |
| 19. Role coverage / provisional review | `test_role_suitability_requires_coverage_and_review_and_no_automatic_assignment`, `test_expected_planner_block_is_success_only_with_review_and_executed_case`; source-eligibility and role-identity gate fixtures |
| 20. Exact JSON/CSV/XLSX links | `ExportParityTests` in `test_qualification_v2_metric_writer.py`: all new sheets/cells compared with CSV and JSON, relative-reference re-export, oversized-cell preservation |
| Existing source identity and membership | `test_catalog_uses_real_evaluator_and_case_memberships`; actual sealed V2 repetition and hash-checked role event/configuration fixtures in `test_qualification_v2_legacy_reports.py` |
| Historical formats and no overwrite | Historical role / A001 / A002 / qualification / sealed aggregate adapter tests; original bytes and workbook paths preserved |
| GUI lifecycle / existing queue | New close-during-discovery ownership regression plus all existing real Tk/queue/process tests |
| Frozen v1 and T05–T12 | Full existing regression suite, both packet validators, Planner/Governor/Worker/Tester/Reviewer validation/calibration commands |

## Verification record

- Initial targeted baseline: 11 inherited metric/writer tests passed.
- Final targeted reporting: 37 metric/writer tests plus 11 legacy/sealed-adapter tests passed, no skips/failures.
- Initial full local Windows Python 3.12 regression: 514 tests, no failures, two existing platform skips.
- Final full local Windows Python 3.12 regression at `e1c41b6`: **524 tests, 0 failures, 2 existing platform skips** (Windows symlink privilege and POSIX-only process groups), 145.350 seconds. Real Tk tests all ran.
- Local queue-specific run: 69 tests, no failures; one POSIX-only process-group skip.
- Separate validations: A001/A002 frozen manifests passed; Planner 10 and Governor 16 authored annotation controls passed; both Worker handoffs validated; 36 Tester/Reviewer cases and 108 annotation controls passed. These validate authored material and record consistency, not independent human certification or live model outcomes.
- No benchmark providers, Flash-Next runtime, production services or actual model inference were used. Runtime tests use deterministic fakes; approved authored candidate fixtures are exercised locally.

CI acceptance requires **Windows and Linux × Python 3.10 and 3.12**. The workflow now explicitly requires real Tk on both systems (Linux uses Xvfb), runs reporting fixtures first, runs the complete suite and existing calibration commands, and retains transcripts. No tests or Windows jobs were disabled to make the earlier failure disappear.

Initial implementation `f43e484041fe6c94f6775ca89b95b60240b222a4` passed all four jobs in [run 37987551678](https://github.com/floydtrey/local-model-bench/actions/runs/37987551678). Final provenance/role-eligibility hardening at `e1c41b6ceb55dbff7825066ff56a01b9f036329f` then passed the entire matrix in [run 37988938887](https://github.com/floydtrey/local-model-bench/actions/runs/37988938887):

| Supported configuration | Targeted reporting | Full suite | Failures | Existing platform skips |
|---|---:|---:|---:|---:|
| [Windows / Python 3.10](https://github.com/floydtrey/local-model-bench/actions/runs/37988938887/job/114017872081) | 48 | 524 | 0 | 1 |
| [Windows / Python 3.12](https://github.com/floydtrey/local-model-bench/actions/runs/37988938887/job/114017872424) | 48 | 524 | 0 | 1 |
| [Linux / Python 3.10](https://github.com/floydtrey/local-model-bench/actions/runs/37988938887/job/114017872318) | 48 | 524 | 0 | 3 |
| [Linux / Python 3.12](https://github.com/floydtrey/local-model-bench/actions/runs/37988938887/job/114017872258) | 48 | 524 | 0 | 3 |

Windows skips the POSIX process-group test. Linux skips the Windows junction, actual Windows PowerShell wrapper and native PowerShell routing tests. The corresponding platform executes each test; **no Tk tests are skipped**. All packet validation, calibration and canonical-handoff steps also passed. CI artifacts retain full test transcripts for 14 days; Actions job logs provide the linked verification record. The final documentation-only branch commit receives the same complete matrix, reported in the task completion message.

## Role and capability limits

The catalog defines all six general categories, all five roles, and all five Assistant categories. Minimum role coverage is Planner 4, Governor 28, Worker 12 per mode, Tester 16, Reviewer 20. Each role has material requirements, critical gates, false-positive/false-negative conditions and mandatory substantive review. No calibrated percentage threshold was invented. A complete, reviewed battery can support a descriptive evidence label, never automatic assignment.

Vision and long-context are Not tested. Tool selection and agent error recovery have insufficient coverage. Bounded multi-step actions, permission boundaries and short-context evidence accuracy have explicit existing source mappings. A001/A002 code implementation checks remain separate observations. None of these limitations prevent completion of the reporting contract; they must remain visible to T16.

## Installation boundary and safe later integration

No file in `C:\Projects\local-model-bench-flashnext` was changed. Its startup repair is preserved. A final read-only inspection confirmed the same clean branch and HEAD. The development history includes permanent commit `6624945`; the complete diff from that commit confirms no changes to frozen packets, role source packets or Flash-Next runtime/startup files.

Integration can be performed separately by the owner:

1. Inspect the permanent branch and `git status --short --branch`. If there are local changes or new commits, preserve and review them first.
2. Save a safety branch at its current HEAD, then fetch the development branch from origin.
3. Check that permanent HEAD is an ancestor of the **verified implementation/final branch commit** named in the completion report. Use `git merge --ff-only <verified-commit>` only when that check succeeds. If it refuses, stop and inspect divergence; do not reset, clean, force, or replace files.
4. Run deterministic validation using that checkout's `src` on `PYTHONPATH`. Leave Flash-Next suspended.

T14, T16 and T19 remain unstarted. T16 can consume the new exports; it must preserve nulls, provisional labels, separate units/configurations and evidence links. Existing real Worker seed/authority and Tester/Reviewer artifact-compatibility limitations remain outside T13 and have not been silently resolved.
