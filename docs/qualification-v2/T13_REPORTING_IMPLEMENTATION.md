# T13 reporting: first implementation slice and remaining acceptance work

**Branch:** `development/t13-reporting-contract-20261009`. **Scope:** additive metric catalog, evidence-linked projection, and legacy-compatible writer outputs. No new dashboard, run scheduler, or model inference.

## Implemented in this slice

- `METRIC_CATALOG_V1.json`: versioned capability/role/Assistant metric IDs with explicit source suite, version, scoring basis, case membership and human-review policy. Vision and long-context recall have **no** eligible cases and must remain **Not tested**. Role suitability has no automatic threshold and cannot be marked qualified.
- `src/localbench/v2/metric_projection.py`: case-level status classification and conservative projection. A score requires matching suite/rubric version, actual independent deterministic assessment, evidence reference and known model/runtime identity. Missing legacy fields stay unknown; blocked/pending cases do not become 0%; repeated trials without an explicit selection policy are excluded; incompatible configurations are excluded with a reason. Counts are distinct case IDs, not repeated trials or cumulative acceptance checks.
- Existing `flashnext_review.py` remains authoritative for its original case/role/JSON/CSV/XLSX outputs. It now adds `qualification_v2_metrics` to the original JSON schema, `metric-summary.csv`, and a `Metric Summary` workbook sheet, without overwriting raw evidence or changing the old schema-version string.
- Deterministic tests cover missing legacy fields, genuine scored cases, incompatible identities, blocked cases, correct Tester FAIL on defective code, repeated attempts, and writer JSON/CSV/XLSX parity.

## Explicit limits: do not misrepresent as full T13 acceptance

- The first catalog maps narrow **shared L0/L2 case IDs** only. The historical five-role cases, Assistant-001/002 project tasks and the new T05–T12 qualification cases are not automatically assigned capability percentages. They require reviewed per-case scoring and explicit adapter provenance.
- The current role writer's historical case rows lack a consistent `suite_id`, `suite_version`, `rubric_version`, and model/runtime identity. Therefore historical rows should remain **unscored** until the runner emits authoritative versions or a reviewed read-only legacy adapter can reconstruct them without guessing.
- T13 still needs versioned role suitability minimum coverage/critical gates, separate attempt/first-pass/repair policy, status taxonomy and comparison grouping across mixed suites, a full Assistant-specific metric mapping, normalized support for the V2 aggregate-report and Assistant project summary formats, and wider deterministic fixture coverage. The T13 task remains **IN PROGRESS**, not COMPLETE, until those acceptance criteria pass.
- The T16 Results tab has not been built. The GUI continues to operate as before.
- Nothing here authorizes generated-code execution or qualifies any model. Flash-Next remains suspended.

## Next implementation unit

Extend the normalized writer adapters for controlled qualification and Assistant summaries; define complete metric numerator/denominator and repeated-trial policy; implement case-based suitability criteria and cross-configuration comparison groups; add T15 negative fixtures. Then test T13's full contract before T16-R0 UI.
