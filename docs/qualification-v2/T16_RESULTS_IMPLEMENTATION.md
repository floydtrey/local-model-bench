# Standalone Results delivery — T15 / T16

Benchmark Lab is an independent model evaluation application. The operational DSH Lab is separate. The [corrected backlog and dependency graph](IMPLEMENTATION_BACKLOG_V2.md) preserve T01–T13 and visibly defer T14. T16 depends on accepted T13 reporting; T15 validates standalone regressions. T17 model runs retain their own authorization, hardware and containment gates. Neither native DSH integration nor optional T19 capability expansion gates the GUI or standalone release.

## Delivered phases

| Phase | Delivered behavior | Sequential local verification |
|---|---|---|
| R0 | Results tab inside the existing Tk application; read-only package/legacy adapter, exact case rows, original workbook paths and safe artifact inspection | 76 targeted queue/GUI tests passed before R1; commit `850cbda` |
| R1 | Six capability groups, separate horizontal bars per configuration/population, five-role suitability matrix using T13 criteria | 79 tests passed before R2; commit `3e8b99b` |
| R2 | Five Assistant dimensions, seven filters, T13 comparison exclusions, exact case/attempt/artifact drill-down | 85 tests passed before R3; commit `39601ba` |
| R3 | Queue-to-Results and Results-to-queue navigation using exact saved run directories; recovery and persistence unchanged | 88 tests passed before R4; commit `cc77046` |
| R4 | Actual Tk clicks, resize/scroll, report validation, legacy/repair/repetition/coverage fixtures, required Tk in Windows/Linux CI | 96 targeted tests and 551 full local tests passed; final CI acceptance recorded separately |

The targeted Windows suite has one existing POSIX-only skip. The full local Windows Python 3.12 suite has two existing platform skips: the POSIX process-group test and a symlink privilege test (Windows junction coverage still runs). No Results widget test is skipped. New tests fail on Tk callback exceptions. The final layout correction was followed by another 96-test pass; the supported CI matrix runs the full final revision.

## Reused implementation and boundaries

- `queue_gui/app.py` remains the only application and owns the original queue, process controls, persistence, recovery and workbook opening. Its new notebook contains Queue and Results.
- `queue_gui/results.py` reads T13 `qualification-v2/metrics:v2` exports and uses `report_adapter.normalize_legacy_report` and the existing T13 status/configuration helpers for historical data. It checks identities and score field consistency; it never evaluates candidate answers or calculates a replacement metric.
- `queue_gui/results_view.py` provides report selection, filters, case/evidence navigation and saved queue links. All loaded state is ephemeral. It writes no result database, queue schema or source report.
- `queue_gui/results_charts.py` draws the writer's values with Tk Canvas. Role criteria and suitability come from the report. Cross-report compatibility uses T13 `compare_series`, retains saved exclusions, and rejects differing metric/catalog versions. No combined or universal score is calculated.
- `flashnext_review.py`, `metric_projection.py`, `report_adapter.py`, the metric catalog, assessors, role interfaces, runners and frozen benchmark packets are unchanged.

## Using Results

Use the existing `tools/gui/benchmark-queue.py` / Windows launcher and select **Results**. The existing application startup still performs its local model-list discovery; opening Results does not start inference or queue execution.

1. **Load reports** selects existing JSON or case CSV files. A CSV next to `review-package.json` uses that authoritative package. **Discover saved reports** searches this checkout's `local-state` and `results` folders. **Load saved queue reports** uses the existing queue's recorded run directories. No operational DSH discovery occurs.
2. Select one or several report rows. An unselected report list shows all loaded reports. Each saved metric population and model configuration keeps its own row and denominator. Selecting a queue run with no report shows no results for that run.
3. Select a capability bar, a role cell or an Assistant metric label. The selected-result panel shows the exact versioned metric, suite/rubric, configuration, numerator/denominator, first-pass/repair outcomes, failures/blocks, review and comparison exclusions. **Case rows** lists its contributing and excluded rows separately; select a row for its full case/run/trial/attempt/artifact identity.
4. **Inspect selected artifact** reads only the exact recorded file and verifies its current SHA-256. It displays text inside Tk, including generated source, without executing or shell-opening it. Missing paths are reported; no similarly named file is substituted. A changed file is marked stale. Large previews are truncated at 2 MB while hashing the whole file.
5. **Review workbook** opens the original XLSX through the existing application opener. **Run folder** opens the original directory. **Queue entry** selects the unique saved queue item with the same resolved run directory. Ambiguous or absent links remain unavailable; model names never identify a queue item.

Filters cover suite/version, role, evaluation track, Worker mode, exact model configuration, runtime identity and human review. They select **whole exported metric populations**. If a filter matches only part of a population, that metric is hidden rather than recomputed; matching case rows remain inspectable. Reset filters to restore all populations. The Comparisons view explains incompatibilities and provides separate left/right evidence navigation. Matrix and case tables support horizontal scrolling; capability bars adapt to available width.

## Truthful coverage and historical limits

Untested vision and long-context recall have no bars or scores. General tool selection and agent error recovery remain insufficient coverage under the current catalog. Correct recovery software is not treated as observed agent recovery. Role statuses retain pending review, insufficient evidence, critical conditions and reference-review gates; no role is assigned automatically.

Six existing all-role packages in the permanent checkout were successfully read without writes: 18, 18, 23, 23, 23 and 18 case rows, each with an existing original workbook. These packages predate T13 metric exports. Their raw outcomes and available identities are shown; missing suite/rubric/configuration/review data remain unknown. Historical percentages are not silently promoted into current capability scores. Original CSVs and workbooks remain accessible. Producing new authoritative metric exports, if needed, is the accepted T13 writer/adapter's job, with missing evidence preserved as exclusions.

Charts show saved report-time measurements. Artifact inspection separately reports current file integrity. Synthetic GUI fixtures demonstrate behavior only; they do not qualify a real model. No real inference or untrusted generated-code execution occurred in this delivery.

## Acceptance evidence

`tests/results_fixtures.py` creates synthetic case evidence using the unchanged T13 writer and released catalog. `tests/test_queue_gui_results.py` tests the real Tk widgets and exact report/row identities. It covers pass/fail and zero, unknown legacy data, absent vision/long-context, provisional role criteria, pending reviews, incompatible Worker modes, repairs, repeated trials, cumulative check counts, correct Tester FAIL on defective code, blocked successors, insufficient/missing/stale evidence, unavailable runtime, not-attempted cases, exact artifact navigation, original workbook access and queue persistence/recovery.

The full inherited suite supplies standalone T15 coverage: independent Planner disclosure (`test_qualification_v2_planner`), Governor boundaries (`test_qualification_v2_governor`), canonical/sequential Worker inputs and failure propagation (`test_qualification_v2_worker`), Tester/Reviewer evidence (`test_qualification_v2_verification`), runtime/tool compatibility (`test_v2_*`), reporting/export parity (`test_qualification_v2_metric*`, `test_qualification_v2_legacy_reports`), and existing CLI/queue/process behavior. Both frozen packet validators and the Planner/Governor/Worker/Tester/Reviewer validation/calibration commands passed. These are deterministic implementation checks, not new human semantic certification or execution authorization.

## Permanent installation and future integration

The work is in a separate clone on `development/t16-standalone-results-20261009`, based on verified T13 `7f9b25c56a4cdd000cc94a8fbf31b50a30310ac1`. Architecture correction was committed first as `7f1b51cc93ed8dc69a52ebe57e774e4ecc308e61` and its dependency graph checked before GUI work.

`C:\Projects\local-model-bench-flashnext` remains on `local/flashnext-startup-safe-20261009` at `6624945ba7f9cca99071b4fc07a37e958770bca1`, clean and unmodified. That commit is an ancestor of T13 and this branch, preserving the machine-specific startup repair. No Flash-Next launch, tuning, repair or inference was performed.

A separate safe installation stage should first recheck its status and ancestry, preserve its machine branch and local queue/run evidence, and make a recovery ref/backup before integration. Only after review should it integrate the verified Results branch while retaining the startup repair. Use the deterministic fixture/GUI regressions and saved-report inspection for smoke testing; keep Flash-Next suspended and do not start any model. Do not reset, clean or overwrite machine-specific state. Reassess ancestry if the installation advances rather than assuming the recorded fast-forward relationship still holds.

R0–R4 introduce no outstanding execution-harness dependency. Actual model validation (T17), standalone release acceptance (T18), authorized isolated Worker seeds/containment, and optional future capability batteries remain separate. Deferred native DSH integration (T14) is not completed and is not a blocker.
