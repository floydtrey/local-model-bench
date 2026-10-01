# Planner Intent 03 — configurable report title

A small Python reporting tool renders a text report from a configuration object.

Current project facts:
- Report rendering code: `src/reporting/render.py`
- Configuration model: `src/reporting/config.py`
- Existing tests: `tests/test_render.py`
- The public function `render_report(data, config)` returns the complete report as a string.
- The first output line is currently hard-coded as `Report`.
- `ReportConfig` is a dataclass and currently has no title field.
- Existing callers instantiate `ReportConfig()` without arguments.
- The output after the first line must not change.

Requested change:
Add an optional report title to `ReportConfig`. The field must be named `title` and default to `Report`. `render_report` must use `config.title` as the first output line.

Constraints:
- Existing `ReportConfig()` callers must continue to work unchanged.
- Do not add third-party dependencies.
- Do not change the `render_report(data, config)` signature.
- Preserve every output line after the title.
- Add or update tests covering the default title and a custom title.
