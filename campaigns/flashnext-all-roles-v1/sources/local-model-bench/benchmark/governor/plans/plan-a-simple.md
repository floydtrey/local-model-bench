**Task list for adding an optional report title**

| # | Task | Pre-conditions | Acceptance condition |
|---|------|----------------|----------------------|
| 1 | **Add `title` field to `ReportConfig`**<br>`src/reporting/config.py` | `ReportConfig` is already a dataclass with no `title` field. | `ReportConfig` now defines `title: str = 'Report'`. <br>Instantiating `ReportConfig()` without arguments still works and returns an object where `config.title == 'Report'`. |
| 2 | **Modify `render_report` to use the title**<br>`src/reporting/render.py` | The function currently hard-codes `"Report"` as the first line. | `render_report` now writes `config.title` as the first output line. <br>All subsequent output lines are unchanged. |
| 3 | **Update tests to cover default and custom titles**<br>`tests/test_render.py` | Existing tests assert that the first line is `"Report"`. | Two new tests: <br>• `test_default_title` – verifies that `render_report(data, ReportConfig())` produces a report whose first line is `"Report"`. <br>• `test_custom_title` – verifies that `render_report(data, ReportConfig(title="Custom"))` produces a report whose first line is `"Custom"`. <br>All other output lines remain identical to the current behavior. |

**Order of execution**

1. Edit `src/reporting/config.py` (Task 1).
2. Edit `src/reporting/render.py` (Task 2).
3. Edit `tests/test_render.py` (Task 3).

**No other changes are required.** All tasks rely only on the information provided in the project and do not introduce new dependencies or assumptions.
