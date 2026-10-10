# Stage A status — version 2

**Implementation and verification complete at code head `339afc237ae832aa439fb023dce7a5c9fdfbbe5d`.** Focused Astra Extra High re-review resolved all three original blockers and found no new blocking defects. Root retains checkpoint acknowledgment and isolated-pull ownership. This final record changes documentation only; source, migrations, tests and workflows remain pinned to the reviewed code head.

## Delivered scope

The inactive `localbench.database_v2` module implements schema version 5 with 35 relational tables, versioned provenance, immutable identities/history, foreign and cross-binding constraints, canonical identity replay, explicit transactions and checksum migrations. SQLite backup API snapshots and external artifact verification/restore use new destinations. Existing engine, runners, assessors, T13/T16, native configuration/discovery, queue/process owners and Tkinter remain unchanged.

Five migrations ship in the installed package: `001_entities.sql`, `002_constraints.sql`, `003_execution_observations.sql`, `004_storage_types.sql`, `005_review_integrity.sql`. The original four migration Git blobs/checksums were retained. The dictionary, architecture/implementation plan and compatibility/recovery contract document all entities, ownership, historic formats, provenance, integrity, backup/restore and later publishing/security dependencies.

No B–F implementation, live persistence, second scheduler, model/inference start, generated candidate execution, bulk historical import, API/UI, remote integration or public export occurred. Source commits were made through GitHub API; no source checkout was cloned or pulled. Root handles an isolated pull only after the final checkpoint and documentation diff are accepted. PR remains draft and unmerged.

## Final verification

| Gate | Evidence | Result at reviewed code head |
|---|---|---|
| Stage A push matrix | [run 38023495885](https://github.com/floydtrey/local-model-bench/actions/runs/38023495885) | Four Windows/Linux Python 3.10/3.12 jobs; 38 tests each, runtime inventory and five installed-package migrations passed |
| Stage A PR matrix | [run 38023498334](https://github.com/floydtrey/local-model-bench/actions/runs/38023498334) | Same four targeted jobs passed; GitHub PR merge tree matches reviewed implementation tree |
| Full qualification/frozen-source/Tk matrix | [run 38023495815, attempt 2](https://github.com/floydtrey/local-model-bench/actions/runs/38023495815/attempts/2) | Four supported jobs passed; 590 discovered tests each, unchanged platform skips: 1 Windows / 3 Linux; required real Tk, authored annotations/calibration and frozen-source checks retained |
| Existing deterministic PR workflow | [run 38023498324](https://github.com/floydtrey/local-model-bench/actions/runs/38023498324) | Windows/Linux Python 3.12 passed, including 590-test Windows run |
| Focused independent review | Root-reported Astra Extra High re-review of exact code head above | All 38 tests plus independent replacement, lineage, overlap, numeric and migration rollback probes passed; no blocking findings |

The first full qualification Windows 3.12 job `114129319912` had one error: unchanged `test_python_reviewer_packet_matches_original_javascript_bytes` exceeded its original 15-second Node subprocess timeout. It ran 590 tests with one error and one expected skip; no database test failed. Its exact frozen test blob remains unchanged, and the same fixture passed in the separate PR Windows job at the same source tree. Only the failed job was requested for bounded rerun at the unchanged code head. Retry job `114130472445` passed the complete gate; successful prior matrix jobs are carried forward. No timeout, assertion, test or frozen bytes were weakened.

## Review corrections and reproduced guarantees

- Replacement inserts cannot rewrite committed evidence, runtime configurations or result identity. Connections verify recursive triggers ON; insert-conflict guards also reject primary/alternate UNIQUE replacement when a raw caller disables recursive triggers. Regressions preserve referenced PASS evidence and unreferenced historical alternate-key records, verify foreign keys/schema and back up retained evidence without an unavailable artifact.
- Repairs require a non-null parent index and exact same-trial immediate predecessor with a failed assessment. Null cross-run/trial parents and skipped predecessors are rejected; valid contiguous repair succeeds. Invalid preexisting schema-4 lineage aborts the additive migration without rewriting rows/version/ledger.
- Backup/restore resolves paths and rejects overlap in both directions, including aliases and staging beneath the retained source, before any directory creation. Rejected restores leave byte hashes and the full source tree unchanged and verifiable. Safe sibling restore verifies both copies. Nested backup cannot write into the original artifact root.
- Numeric storage guards reject nonnumeric counts/scores and nonfinite values. A Windows SQLite 3.40.1 decimal-limit difference exposed during the first numeric correction is resolved by migration 5's portable arithmetic finite checks; all supported versions pass. Invalid existing data rolls back the entire pending migration batch.

## Runtime and durability limits

| Native runtime observed | Linked SQLite | Operational WAL policy |
|---|---|---|
| Installed Windows Python 3.12.10 | 3.49.1 | Gated |
| CI Windows Python 3.10.11 | 3.40.1 | Gated |
| CI Windows Python 3.12.10 | 3.49.1 | Gated |
| CI Linux Python 3.10.22 / 3.12.15 | 3.45.1 | Gated |

Default operational connection refuses these affected WAL runtimes; isolated tests explicitly use `validation_only=True`. That flag/raw connections remain caller-policy bypasses, not deployment permission. Verify a patched native SQLite distribution (3.51.3+, 3.50.7 or 3.44.6 backport) and intended connection/checkpoint topology before B/C operational wiring. One controller does not imply one connection. No live runtime was changed.

WAL + synchronous FULL does not prove power-loss safety on arbitrary Windows filesystem/device caches. Flushed new-file copies, SQLite consistent backup and new-destination rename are tested; arbitrary directory-rename durability, malicious concurrent path replacement and authenticated backup provenance are not claimed. Artifact byte/content binding, complete publication transitions, restart reconciliation and server-side authorization remain explicit later-stage responsibilities. Negative/blocked results may be committed honestly; process exit code never establishes qualification.

## Compatibility and retained evidence

Read-only audits covered native formats/owners and genuine v1, historical role and T13 observations, including the Qwen 9B five-role archive. Private reports/prompts/candidates/evidence were not published. Sixty-two imported older Worker source fixtures match their pinned source Git blobs. Historical DSH launchers stay separate. T13's case/attempt/check units, blocked/unknown/null handling, first-pass/repair separation, configuration eligibility and independent Tester success semantics remain authoritative.

The original installation backup was currently verified: 7,421 archived files / 55,795,857 manifest bytes, every archived size/SHA-256, ZIP CRC and all three Git bundles pass. Its archived 14-item paused queue is a historical snapshot. Current live queue/process status observations belong to the Owner and do not establish assessed outcomes; no queue action was taken.

The last read-only Git audit observed a clean checkout at protected GUI-fix commit `7e8c958df6ef290987c687d5c89f3581bace39c4`. Its Results scroll fix/regression are protected by the verified dedicated bundle and must be carried/retested before later cutover. Stage A's integration base remains T16 `4f55b18dd7a0a82447edef4a6c4281899f295c8c`; live checkout was not reset or altered.

## Web System dependency and next stage

[Web System issue #1](https://github.com/floydtrey/floydslab-web-system/issues/1) tracks coordination. Proposal 0.1.0 is pinned at `2cdd0855b2145b7022a45251d69fc7fa213a8928`; matching limited ownership/security/directory principles acceptance is recorded in 0.1.1 at `6c60050769474a6fcb4e5a24dc6ff38ba32aaeb8`, verified by root with both acknowledgments. Formal fields/endpoints/authentication profiles/control actions/publication payload/deployment are not agreed.

Benchmark Lab retains DB, engine, queue, results, scoring, reviews, internal API and native app. Web System retains shared service directory/Control Center/Cloudflare/authentication/navigation architecture. No Web System repository edits or remote implementation occurred. Issue comments confer no execution/deployment authority.

After root checkpoint acceptance and explicit later-stage authorization, B can implement per-case publication/recovery through existing owners, with patched-runtime verification first. Preserve completed cases, mark incomplete evidence honestly, never auto-rerun/invent assessment/advance dependent Worker steps, and require Owner authorization for resume/rerun. Complete collection import and remote integration remain deferred. Stop after A.

## Owner activity protection

The Owner subsequently reported actively running benchmark tests. No further live/shared-Git operations are performed. Live processes, queue, settings, results and installation stay untouched. Any later root-owned source pull must be an independent clone beneath the controller chat's work directory, never the live checkout or its shared Git metadata. Current queue changes are Owner activity and process status is not assessed outcome.


## Stage B corrective gate in progress
Canonical B source at d6a7caf899bdea5623323158774c1f88274c640a had green48 B/38 A/638 full tests, but root identified a required behavior gap: capture_completed was absent from published partial projection/global events until separate assessment. That checkpoint is NOT accepted as complete; C implementation remains gated. A final documentation acknowledgment was not committed when approval review hit the usage limit.

The authorized minimal correction adds immutable same-DB publication revisions/events via migration10, immediate verified capture visibility and notification with pending/unavailable assessment and null score/outcome, and later native assessed revision under the same identities. Defaults/native owners/live runtime remain unchanged. No new controller/service/broker/assessor or execution is introduced. Positive native two-case-before-second-start, pending restart, late assessment without rerun/inflation, corruption, rollback, dedup and old-event/receipt upgrade tests pass locally in the isolated full patched Windows runtime (54 tests before the full-tree crash matrix). Fresh exact-head CI and root acceptance remain mandatory. Native producer contract and dictionary describe corrected semantics; no merge/cutover/live change is authorized by this record.
