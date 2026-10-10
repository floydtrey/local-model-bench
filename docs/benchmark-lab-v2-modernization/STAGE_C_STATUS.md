# Stage C1 source checkpoint status

Prepared 2026-10-10. C1 implementation and fresh source qualification are complete within isolated development/fixture scope. Tested code head is725b12dcd194b9dbf768b3dd250cdbb9681eb774; the final acknowledgment is the documentation-only commit containing this update. Root independent review remains pending. This is not operational or deployed acceptance.

Based on accepted B documentation e1affdf610f3c7c040615b465af5eaf7cda47cee / tested B code3fb8d7b5a428a57cdb37b4d2d185c2f8c7ee8bdc. Same canonical development/benchmark-lab-v2-modernization-20261009 branch and draft PR11; no separate branch/controller/service or live checkout was created.

Delivered C1: optional FastAPI factory and strict versioned envelopes, default denied private access, Python-only isolated fixture injection, transport-only liveness, conservative scoped health, shared B passive projection/event methods, nonrecovering bounded queue snapshot reader and exact native capture/assessment cursor/binding surfaces. No controls or auth endpoints. [C1_API_CONTRACT.md](C1_API_CONTRACT.md) is the detailed development interface and dependency/coverage/bounds/reset contract.

Private full Python3.15.0/SQLite3.53.4 and the complete14-wheel API stack passed offline hash installation and pip check; [runtime record](C1_RUNTIME_QUALIFICATION.md) names exact versions, digests, primary sources and failures/limits. Seven independent runtime fixtures pass, including real Tk and ephemeral Uvicorn asyncio/h11/SSE. The final source API suite passes21 tests; passive native suite adds5 tests. Retained B publication suite passes55 tests with default operational gate. The local full snapshot passes670 discovered tests before the one added Uvicorn test; final API21 includes that added test. Two inherited local Windows skips are POSIX process group and symlink privilege; required real Tk passes. Fresh CI will run the complete671-test final tree with API dependencies installed.

## Exact source checks and final handoff

All six workflows and17 jobs on tested head725b12d passed:

- [C1 PR runtime/API/full Windows](https://github.com/floydtrey/local-model-bench/actions/runs/38064635682), job114249683051:14 locked wheels/offline install/pip check;21 API tests;5 passive reads;671 full tests, one inherited POSIX process-group skip. Required native Tk runs.
- [C1 push runtime/API/full Windows](https://github.com/floydtrey/local-model-bench/actions/runs/38064631508), job114249670837: same exact stack and21/5/671 tests, one inherited skip.
- [B PR](https://github.com/floydtrey/local-model-bench/actions/runs/38064635692): all five jobs pass. Patched job114249683057 verifies full Python3.15.0/SQLite3.53.4,55 publication/38 storage/671 full tests and installed10-migration package. It intentionally has no API extra, so its22 skips are21 new optional API tests plus the inherited POSIX skip; the separate mandatory C1 jobs run all21 API tests.
- [A PR](https://github.com/floydtrey/local-model-bench/actions/runs/38064635671): all four38-test schema/package jobs pass.
- [Retained foundation matrix](https://github.com/floydtrey/local-model-bench/actions/runs/38064631492): all four Windows/Linux Python3.10/3.12 jobs pass671 discovered tests, real Tk/frozen/annotation/calibration guards retained. Base environments skip21 optional API tests in addition to the unchanged platform skips1 Windows/3 Linux; no inherited test was disabled.
- [Deterministic PR](https://github.com/floydtrey/local-model-bench/actions/runs/38064635684): both supported jobs pass.

PR merge-file tree56f34d20d124b7e6276bb0fa403e2faa78943b06 equals the tested source tree by every blob/path/mode. All original migrations1–10 remain the accepted B blobs. Code gate changes include API envelopes in each SSE frame and explicit optional-test path coverage; there was no unchanged-head retry to hide a failure. Initial fixture/harness issues remain recorded above and in the runtime record. Final documentation changes do not alter tested source, lock, schemas or gates and do not repeat passed tests for prose.

Root can now review this completed checkpoint and pull only into its independent clone after acceptance. No other source writer or live/shared Git action was used. The original preparation report and private runtime follow-up remain retained; binaries/wheels/raw transcripts remain local, not uploaded.

Initial wrong-working-directory/missing snapshot fixture failures were corrected in the local harness only. An authorized isolated run outside the ordinary Windows sandbox resolved strict native path-resolution denial without modifying any native containment guard. No passing assertion, SQLite gate, frozen source, original migration, model/case population or T13 scoring code was relaxed.

All original migrations1–10 are unchanged. The shared read-method extraction preserves original B projection and integrity checks. Existing queue scheduling/process/launchers/recovery remain their native owners. C1 never constructs a CasePublisher writer for a GET and never opens/migrates/recovers a DB on GET.

DefaultDenyAll remains for installed private data, streams, downloads and effects. Fixture grants are not actual Owner acceptance. Source generation must rotate/rebind after any restore, including same-prefix history; restore is not implemented here. Health TTL/skew/aggregation/trust remain unaccepted; consumer inability is unknown coverage. Source metadata does not establish installed version. Auth reuse proposal ae987c0 remains investigative only and contract0.1.1 principles-only remains unchanged.

Next proposed increment is C2: extract existing Tk coordination into ONE native reusable controller with the legacy facade, preserving QueueState/ProcessRunner/instance lock, immutable per-item settings, recovery and close/stop behavior. C2 and C3 typed CLI publisher activation require root review and their own source gates. D/E/F, actual identity/grants, model/host-code execution, live installation/runtime changes, remote routing, publication and cutover remain deferred. Stop at C1 handoff.
