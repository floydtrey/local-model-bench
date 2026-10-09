# Integration and validation completion — technical audit v1

The T05–T12 correction and substantive calibration review is complete. The
permanent Windows benchmark installation was directly updated and validated on
2026-10-09. This completes repository/installation work within the authorized
scope; it does not release any model or generated code for execution.

## Exact revisions and ancestry

- Starting Batch 5: `331ec1a2c37cc030e7eb3636f3d0cc35df7b1e8d`.
- Technical corrections: `394276e7bb7a8a634f51ee7cbeb9c9b033bc0b49` on
  `development/t05-t12-technical-audit-20261009`.
- **Final audited executable integration:**
  `40a2c8d292f5b6ebfbb9c317e3c068e8ef1cf487` on
  `development/t05-t12-integration-20261009`.
- Merge parents: correction commit `394276e7bb7a8a634f51ee7cbeb9c9b033bc0b49`
  and permanent repair history `da2fb728135b58370e87cb91711f44f5225f8a62`.
- Batch 4 `dbee96628d6ed9248f0ed747d02aeed940a8ddd5`, Worker implementation
  `065579d5fa5418efd52aebcacd145664d5e474cd`, Governor
  `1d52238139785ad14e5e34efb25d57e9dba93a14`, Planner
  `c5cd427a94af453fdaf13ce31bb302a9b0dbd255`, and baseline
  `dd04a8883ea18fc49f135320b65a7f4551f98c7d` are already ancestors.

No earlier batch was blindly cherry-picked, no branch was force-pushed, and the
permanent checkout was not reset. Only the missing repair history was merged
into the reviewed Batch 5 descendant. Subsequent commits contain audit evidence
and report completion only; the executable/test/fixture source is identical to
the exact integration commit above. The containing Git commit identifies the
final report revision. The final installation receipt in the rollback directory
records the full installed HEAD including that report revision.

## Deterministic results

| Revision / environment | Tests | Skips | Failures | Outcome |
|---|---:|---:|---:|---|
| Corrected qualification subset, local Windows Python 3.12.10 | 82 | 1 | 0 | PASS |
| Correction checkout, full local Windows suite | 474 | 2 | 0 | PASS |
| Combined staging, full local Windows suite | 475 | 2 | 0 | PASS |
| Permanent installation, full local Windows suite | 475 | 2 | 0 | PASS |
| Correction CI, Windows Python 3.10 and 3.12, each | 474 | 1 | 0 | PASS |
| Correction CI, Linux Python 3.10 and 3.12, each | 459 | 4 | 0 | PASS |
| Integration CI, Windows Python 3.12 | 475 | 1 | 0 | PASS |
| Integration CI, Windows Python 3.10, initial attempt | 475 | 1 | 1 | Timing failure retained |
| Integration CI, Windows Python 3.10, one unchanged retry | 475 | 1 | 0 | PASS |
| Integration CI, Linux Python 3.10 and 3.12, each | 460 | 4 | 0 | PASS |

All runs had zero test errors. These are repeated suites/environments, not
independent benchmark sample counts. The extra integration test comes from the
preserved startup-repair history. All 10 Planner, 16 Governor and 108 Batch 5
controls validate; no model was run. Both original packet validators, both
canonical Worker bundle validators and all qualification CLI validators passed.
The permanent installation passed eight validation/calibration commands plus
three CLI help checks. The full Windows suite exercises real Tk widgets with
fake discovery/runners, CLI routing, queue persistence and the existing writer.

CI sources:

- [Correction matrix, all four jobs passed](https://github.com/floydtrey/local-model-bench/actions/runs/37932017544),
  exact commit `394276e7bb7a8a634f51ee7cbeb9c9b033bc0b49`.
- [Integration matrix, all four jobs passed after one failed-job retry](https://github.com/floydtrey/local-model-bench/actions/runs/37932114240),
  exact commit `40a2c8d292f5b6ebfbb9c317e3c068e8ef1cf487`.
- [Initial Windows 3.10 failure](https://github.com/floydtrey/local-model-bench/actions/runs/37932114240/job/113825117271)
  and [unchanged successful retry](https://github.com/floydtrey/local-model-bench/actions/runs/37932114240/job/113827097335).

The first Windows 3.10 integration job failed only
`test_total_deadline_cuts_off_dripping_response_and_keeps_received_prefix`:
3.235 seconds exceeded its 0.8-second wall-time assertion. That existing loopback
driver/test was unchanged by this audit. A single rerun of the failed job at the
same commit passed all 475 tests. The underlying cause of that timing variability
was not established; this is retained as a regression reliability limitation,
not silently reclassified as an initial pass. No assertion was weakened and no
Flash-Next driver, runtime binary or configuration was repaired or retuned.

Local skips: symlink privilege unavailable (the Windows junction test passed),
and POSIX process groups inapplicable. Windows CI permits symlinks and skips only
the POSIX test. Linux CI skips the Windows junction test, the Tk class without a
display, the Windows PowerShell wrapper test and native PowerShell routing.
Its lower test count reflects the skipped Tk class; it is not missing
qualification coverage. Individual job/log hashes and counts are in
[validation-results.json](validation-results.json).

## Frozen sources, repair and historical evidence

Post-install verification found **zero mismatches** in:

- 129 protected v1/historical tracked files.
- Four machine-specific startup-repair files.
- Both external repair artifacts (`llama.dll` and `llama-mmap.cpp`).
- All 6,845 pre-existing result/local-state files; no additional result/state
  files appeared. The live instance lock was excluded from both inventories.

The stored 14-item queue loads read-only as Paused. No state was saved or resumed.
Original frozen packet hashes remain A001
`377ee1d5f94fd4e3d66748c668955dcc9fc5e208c59db252f64684d366e3b779`
and A002 `6de6aea144785440e78bc6e93b918869f108ee21bba0583332fde084cc5d694d`.

The four preserved machine files are
`campaigns/flashnext-all-roles-v1/README.md`,
`campaigns/flashnext-all-roles-v1/runtime-profile.json`,
`src/localbench/v2/flashnext_runtime.py`, and
`tests/test_v2_flashnext_runtime.py`. Their exact pre/post hashes, the two external
artifact hashes and protected source hashes are in
[source-baseline.json](source-baseline.json). These four files differ from the
upstream Batch 5 tree because its branch lacked the existing repair; their bytes
in the permanent installation did not change. The [changed file inventory](changed-files.json)
lists the 109 revised qualification source/artifact/document paths separately.

## Reference and revised fixture identities

| Artifact | SHA-256 |
|---|---|
| A001 reference plan | `6fb716721af1f31d0a543edfa5925693aef20466db94731d0dca337f5879b288` |
| A002 reference plan | `e93213973c03d09a2f9016b209ac903f3370e166d61829f5b7c549b730acab7f` |
| A001 canonical Worker bundle | `0c09c14df5cd2f27e17dc2d65b2892982b1db9ddfd67bf1bc3d8767af90b6fdc` |
| A002 canonical Worker bundle | `4e770f2ddb6e4ec19886561a339dbb2d03b673c666ed2bd5ea2532bb353e3b17` |
| Planner control manifest | `69a78e7dfeab4ae40ffa12b5dc4c436f2bb9b5bb7dbcb0c28686260c8db1b228` |
| Governor freeze | `b988d25522bff6217c31a7b2dd910c425d48b6858f93cf2fc13c49fd72385293` |
| Governor control manifest | `2ed45bf6733f7ba1b8f08fc223cf8289afdb14c00c65c1a0f7c5b0be78bf2a3e` |
| Verification v2 freeze | `e70683bab99a24ff436337d53d1297c5922dea1d75461963967927448a0a3185` |

## Permanent installation and rollback

`C:\Projects\local-model-bench-flashnext` remains on
`local/flashnext-startup-safe-20261009`. It was clean at `da2fb72`, updated with
`git merge --ff-only` to the verified integration, then directly validated.
The final report-only revision is also fast-forwarded to that installation.

The existing `safety/flashnext-startup-repair-20261009` still points to
`ef07fd6b61caf143802c8c74a4ca5133ff932d1f`. Both bundles in the existing
`C:\Projects\benchmark-backups\reconcile-20261009-040542` backup verified as
complete Git histories.

A new pre-update rollback point was created and verified:

- Branch: `safety/t05-t12-preintegration-20261009-124633z` at
  `da2fb728135b58370e87cb91711f44f5225f8a62`.
- Directory: `C:\Projects\benchmark-backups\t05-t12-preintegration-20261009-124633Z`.
- Contents: verified complete Git bundle, tracked-tree ZIP, empty clean-tree/index
  patches, source/runtime/evidence inventories, original queue copy, hashed backup
  manifest, and final installation receipt.

Recover the old revision in a **separate** checkout if needed:

```powershell
git -C C:\Projects\local-model-bench-flashnext worktree add --detach C:\Projects\local-model-bench-t05-t12-rollback safety/t05-t12-preintegration-20261009-124633z
```

Use a fresh destination path. Do not reset the live checkout or replace its queue
or result directories. Flash-Next remained suspended throughout; its patched
runtime/profile are preserved exactly.

## Controlled-trial readiness

Planner, synthetic Governor and read-only Reviewer materials are technically
ready for separately authorized controlled trials. Worker handoffs/mode mechanics
are technically suitable, but isolated seeds are missing. Untrusted Worker/Tester
Python requires verified containment and a specific execution release. Real
Worker artifact compatibility remains provisional. The 14 blocked / 2 provisional
readiness records are listed individually in the decision ledger; they are not
unreviewed cases disguised by passing tests.

The Owner still controls candidate/environment selection and actual execution,
disclosure, exceptions and deployment releases. Individual technical benchmark
case approval has already been delegated and completed. No model qualification,
independent human signoff, production governance verification, T13/T16/T19 work or
real-model inference is claimed.
