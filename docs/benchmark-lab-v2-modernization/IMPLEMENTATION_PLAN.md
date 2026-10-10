# Benchmark Lab v2 modernization — implementation plan v1

## Scope and checkpoint

Stage A only: inactive versioned SQLite storage inside `localbench`, schema/migrations, constraints, dictionary, ownership/provenance, verified backup/restore, deterministic tests and compatibility planning. Existing runners, assessors, T13 projection, Tkinter and queue/process ownership remain operational and unchanged. No API/UI, scheduler, inference, candidate execution, bulk history import, remote integration, public export or cutover is implemented. B–F require later controller authorization. This checkpoint remains subject to independent critical-defect review; passing tests does not constitute architectural acceptance.

## Verified baseline and native options

Base: `development/t16-standalone-results-20261009` at `4f55b18dd7a0a82447edef4a6c4281899f295c8c`. GitHub compare verifies it is 272 commits ahead of main, 92 ahead of the old architecture plan, 16 ahead of T05–T12 integration and 8 ahead of T13, with zero commits behind each. Choosing the earlier architecture branch would discard newer qualification/reporting infrastructure. Additional GitHub comparisons verify native Ollama, telemetry, effective-config binding, multi-runtime interface, batch4 Worker and batch5 Tester/Reviewer branches are ancestors. Older role/worker qualification branches diverge from main; their source inventory was inspected separately. The current campaign source manifest pins Worker branch fce91a7... and 62 imported source fixtures; each copied Git blob matches both the manifest and original tree. Historical DSH launchers were intentionally not imported, and are not introduced by Stage A.

Inspected source: `queue_gui/core.py`, `process.py`, `app.py`, `results.py`; v2 `contracts.py`, `records.py`, `orchestrator.py`, `configuration.py`, `reporting.py`, `report_adapter.py`, `metric_projection.py`, `validation_adapter.py`, role trace and telemetry; qualification Planner/Governor/Worker/verification contracts and assessors; Assistant campaign/CLI; v1 evaluation; evidence schemas; T13/T16 implementation records, technical integration record, metric catalog and current backlog; CI and package configuration.

Existing capabilities: hash-sealed versioned model/runtime/config/host/suite/trial/manifest/case/evaluation records, exclusive evidence-file writes with fsync and read verification, event logs, repetition reporting, L0/L1/L2 pack/execution/evaluator contracts, bounded tools and containment, observed telemetry, T05–T12 role protocols and review/authorization boundaries, ASSISTANT-001/002 versioned project packets and acceptance, T13 metric catalog revision 1.1.0 (16 definitions), conservative read-only historical adapters, T15 deterministic regressions and T16 read-only Results. Queue JSON v1/v2 has per-item settings, atomic replacement, crash recovery to paused/interrupted, single active item and native instance/process custody. Ollama discovery observes installed tags independently of results.

Verified gap: these stores do not provide cross-entity transactional relational storage, schema migrations or consistent DB+artifact backup. SQLite extends storage in the existing Python package. Existing sealed artifacts and T13 definitions remain authoritative; SQLite does not replace an evaluator or own execution. No separate service or independent state owner is introduced. Native file configuration remains authoritative until a later explicit cutover.

Live checkout read-only audit: clean at `7e8c958df6ef290987c687d5c89f3581bace39c4`, one commit beyond the chosen base. It adds `report_tree.see(keys[0])` and a real-widget scroll regression. Stage A does not change those files. The GUI fix must be carried forward and retested before any later installation update; do not reset the live branch to this Stage A branch. Its backup bundle currently verifies and contains that exact commit.

Backup verification on 2026-10-09: 7,421 ZIP entries / 55,795,857 manifest bytes; ZIP CRC and every archived size/SHA-256 match; all three bundles verify against available Git prerequisites. Archived queue v1 is Paused with 14 items. The baseline bundle protects `6624945...`; separate before/fix bundles protect `4f55b18...` and `7e8c958...`. Private audit records stay outside GitHub. Current live data and original backup evidence were not modified.

Read-only genuine observations include v1 manifest/case/evaluation output, older five-role summaries/packages and a located Qwen 9B five-role archive with 22 result rows and a T13 projection. Archive presence is an observation, not controlled model qualification. No private report contents, prompts, candidates or evidence files are committed.

## Database design before implementation

Use SQLite WAL, synchronous FULL, foreign_keys ON, busy timeout and explicit BEGIN IMMEDIATE transaction boundaries. WAL is not a power-loss guarantee; filesystem/controller cache and Windows flush/rename behavior impose limits. Migration SQL and checksums are immutable; application_id/user_version and a ledger identify the schema. Unknown newer or altered histories fail closed. A migration batch rolls back entirely.

Identity/version entities: source snapshots/mappings/import exceptions; immutable model identities; independent installed-model discovery observations; runtime configurations keyed by full canonical content with no name-based merging; versioned suite/case membership/protocol/assessor/metric/role criteria; environments/runs; planned case trials and explicitly linked repair attempts; separate execution, assessment and review history; resource observations; external artifact references and hashes; versioned metric populations/comparison decisions/public approvals; singleton existing-controller identity, queue snapshots and recovery records. Foreign keys and cross-binding triggers preserve run/config/suite/case/trial/assessment lineage. Append-only records preserve supersession and audit history. Queue records are storage only, with no claim/start/dispatch loop.

## Runtime and Web System dependencies

Native installed Python 3.12.10 links affected SQLite 3.49.1. First Stage A CI inventory also found affected SQLite 3.40.1 (Windows 3.10), 3.49.1 (Windows 3.12) and 3.45.1 (Linux 3.10/3.12). Operational connection defaults to fail closed; isolated schema validation explicitly opts into test-only mode. Reuse and verify a patched native Python/SQLite runtime before B operational wiring. WAL+FULL and one scheduler do not establish safe multi-connection operation. See the compatibility/recovery record for version boundaries, primary documentation and limitations.

The separate FloydsLab Web System owns shared service registration, health reporting, remote authentication, private navigation and eventual publication integration contracts. Coordination is tracked at [Web System issue #1](https://github.com/floydtrey/floydslab-web-system/issues/1). Root reviewed contract 0.1.0 at exact commit 2cdd0855b2145b7022a45251d69fc7fa213a8928 and recorded limited technical acceptance of REG-01/HEALTH-01/AUTH-01/NAV-01/CTRL-01/PUB-01 ownership/security/directory principles. Matching limited principles acceptance is recorded in revision 0.1.1 at commit 6c60050769474a6fcb4e5a24dc6ff38ba32aaeb8. Root read/compared the recording and verified only acceptance records changed; issue #1 contains both acknowledgments. Formal fields, endpoints, authentication profile, actions, publication payloads and deployment are not agreed. No issue comment grants production or deployment authority. Benchmark Lab retains its database, engine, queue, results, review workflow and internal API. No Cloudflare routing, authentication platform or general Control Center is built here. The root controller owns detailed interface negotiations; review compatibility and propose necessary changes before detailed agreement. Remote integration is not authorized until contract agreement and the relevant stages are ready.

## Acceptance gates

1. Implement schema + checksum migration runner in `src/localbench/database_v2/`; no live callers.
2. Document every entity/relationship, writer/read ownership, identity/provenance/integrity rules and historical adapter mapping.
3. Implement portable consistent DB+external-artifact backup/restore to new destinations; verify before promotion; retain originals.
4. Deterministic tests cover migration replay/tamper/newer rejection, transactional rollback, durability pragmas, keys/lineage, outcomes, config separation, integrity and backup/restore failures.
5. GitHub CI on Windows/Linux Python 3.10/3.12 runs Stage A tests and the unchanged supported deterministic/frozen-source/Tk regressions. No models or inference.
6. Commit bounded payloads through GitHub API; draft PR targets T16 development. Do not merge or pull into live. Report exact head/CI and remaining limits.

## Future publishing/authority contract (not active in A)

Scheduled → started → execution completed/interrupted → evidence finalized → assessment completed/unavailable → result committed → review pending/completed. A per-case publication transaction links exact finalized artifact hashes, attempt and assessment; successful results require evidence and a PASS assessment. Required evidence must be finalized and verified before DB commit. Recovery checks unpublished snapshots and committed references; preserves completed cases and honestly marks incomplete cases. It never invents assessment, reruns automatically or advances dependent Worker steps. Resume/rerun requires Owner authorization.

Stages B–F must reuse existing controller/process owners. Local admin/authenticated remote Owner control is separate from private viewer/public visitor reads; authorization is server-side. Technical review cannot confer execution permission. Public data requires a separately versioned sanitized dataset and explicit approval; public visibility cannot grant execution authority.

## Sequence and status

| Stage | Dependency / deliverable | Status |
|---|---|---|
| A | Storage foundation and verified recovery primitives | Implemented/verified at 339afc2; focused review passed; root final documentation acknowledgment |
| B | Per-case durable publication/recovery using A and existing owners | Corrected/verified at3fb8d7b5; root acceptance/C authorization pending |
| C | Local API and events with one controller | Not started |
| D | Responsive web Results/control UI | Not started |
| E | Historical import verification and sanitized publication | Not started |
| F | Windows acceptance and explicit cutover; preserve GUI fix | Not started |

Do not interpret this future sequence as approval to start B–F. Tkinter stays operational through F acceptance.

## Verification and final correctness check

Implementation checkpoint `29cc6b6852bd73788af055858cd6de3428b496f0` passed four [Stage A jobs](https://github.com/floydtrey/local-model-bench/actions/runs/38022451495) (30 tests, runtime inventory and installed-package checks) and four [full qualification jobs](https://github.com/floydtrey/local-model-bench/actions/runs/38022451565) (582 discovered tests; inherited platform skips 1 Windows / 3 Linux, with required real Tk retained). A final native SQLite audit demonstrated that nonnumeric text can satisfy ordinary numeric CHECK comparisons. Additive migration 4 closes that storage-type gap with integer count guards, finite numeric score guards and an atomic existing-row audit. The schema-5 corrected head has 38 Stage A tests; its exact check results are linked from [draft PR #10](https://github.com/floydtrey/local-model-bench/pull/10). This is a Stage A correctness change, with no runner, API or architectural expansion. Current CI is the source of final-head verification; independent architecture acceptance remains pending.

## Independent review corrections

The schema-3 checkpoint was blocked for (1) INSERT OR REPLACE bypass of append-only delete triggers, (2) nullable parent-index bypass of same-trial immediate repair lineage, and (3) restore destinations beneath the source backup invalidating the retained original. Additive migration 5 provides insert-conflict guards for primary/alternate unique identities, exact nonnull repair binding and atomic prior-row audits. Supported connections verify recursive_triggers ON. Backup/restore rejects resolved source/destination overlap before directory creation, with byte-hash/tree preservation tests. Windows SQLite 3.40.1 also exposed a finite decimal-boundary difference in migration 4; migration 5 uses portable arithmetic finite checks. No earlier migration checksum changes. All changes stay within Stage A. Fresh exact-head targeted/full CI and focused independent re-review gate checkpoint acceptance. Root handles any isolated source pull only after review and blocking fixes pass.

## Final verified checkpoint

Code head: `339afc237ae832aa439fb023dce7a5c9fdfbbe5d`. All four [Stage A push jobs](https://github.com/floydtrey/local-model-bench/actions/runs/38023495885) and four [Stage A PR jobs](https://github.com/floydtrey/local-model-bench/actions/runs/38023498334) passed 38 tests and five packaged migrations. The [full qualification matrix](https://github.com/floydtrey/local-model-bench/actions/runs/38023495815/attempts/2) is green with 590 discovered tests per supported job, unchanged platform skips (1 Windows / 3 Linux), real Tk and authored annotation/frozen-source checks retained. The [existing deterministic PR workflow](https://github.com/floydtrey/local-model-bench/actions/runs/38023498324) passed both jobs; its merge tree equals the reviewed code tree.

Full qualification Windows 3.12 initially hit the unchanged 15-second Node packet-byte fixture timeout (job 114129319912), while the same-tree PR Windows run passed it. One bounded failed-job retry at unchanged head passed all 590 tests plus remaining checks (job 114130472445); no test/assertion/timeout/frozen bytes changed. This failure/retry is preserved in STATUS.md. Root-reported focused Astra Extra High re-review passes all three former blockers with no new blocking findings. Original four migration blobs remain unchanged.

This final update changes only status/plan documentation. It reuses the exact verified code head rather than rerunning passed tests for prose. Root verifies the documentation-only diff and owns final checkpoint acknowledgment/isolated pull. PR remains draft/unmerged; no live change or B–F work occurred. Patched operational SQLite, publishing/recovery content checks and detailed remote integration remain later-stage gates.


## Corrected Stage B checkpoint
B's completed native boundaries, schema10 append-only capture/assessed revisions and global events are regression-verified at3fb8d7b5a428a57cdb37b4d2d185c2f8c7ee8bdc. Earlier d6a7caf greenCI did not establish required capture publication; root reviewed that gap and the same-DB correction. Latest projection includes pending capture BEFORE next case with no fabricated score/PASS. Later native assessment preserves same case/trial/attempt and immutable history; no rerun/inflation/scorer/controller. See STATUS.md, STAGE_B_HANDOFF.md and the single final NATIVE_PRODUCER_CONTRACT.md for exact source/runtime/55 B/38 A/645 full checks and native CLI/custody/cursor/recovery limits. Root owns independent acceptance/isolated pull and C–E coordination; this worker stops after B. Final acknowledgment changes docs only, no live/merge/cutover action.
