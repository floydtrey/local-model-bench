# Approved Plan

## Task 1 — Add configuration field
Add a public `title: str` field to `ReportConfig` with default value `"Report"` so existing `ReportConfig()` callers remain valid.

Acceptance condition: `ReportConfig()` exposes `title == "Report"`, and callers may construct `ReportConfig(title="Custom")`.

## Task 2 — Use configured title in rendering
Prerequisite: Task 1.

Update `render_report` so its first output line uses `config.title`. Preserve the function signature and every subsequent output line.

Acceptance condition: default configuration preserves the existing output; a custom title changes only the first line.

## Task 3 — Add regression tests
Prerequisite: Tasks 1 and 2.

Add tests covering the default title, a custom title, and preservation of all later lines.

Acceptance condition: all existing and new tests pass.
