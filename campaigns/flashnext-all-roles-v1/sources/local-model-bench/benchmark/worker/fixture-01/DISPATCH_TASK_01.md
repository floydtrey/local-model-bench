# Worker Dispatch — Qualification Test 01

## Original project intent
See `PROJECT_INTENT.md` in this dispatch and workspace.

## Full approved plan
See `APPROVED_PLAN.md` in this dispatch and workspace.

## Assigned task
**Task 1 only — Add configuration field.**

Add a public `title: str` field to `ReportConfig` with default value `"Report"` so existing `ReportConfig()` callers remain valid.

Acceptance condition: `ReportConfig()` exposes `title == "Report"`, and callers may construct `ReportConfig(title="Custom")`.

## Governor intent guidance
ALL: Preserve existing public interfaces and existing behavior unless the supplied project intent explicitly requires a change. Prefer the smallest change that fully satisfies the supplied project intent. Reuse the project's existing structure and conventions. Do not add unrelated refactors, dependencies, documentation, infrastructure, abstractions, or features.

## Prerequisite handoff
No prerequisite handoff; this is the first task.

## Authority boundary
You are authorized to execute Task 1 only. Tasks 2 and 3 are visible for context but are not authorized in this run. Do not modify rendering behavior or add the later regression tests.
