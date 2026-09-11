# Shared L0/L1 Battery V1 Acceptance

**Status:** accepted benchmark-content checkpoint

**Date:** 2026-09-11

**Model execution:** not performed

## Accepted content

Benchmark Lab V2 now has its first real shared benchmark-content battery:

- `benchmark-packs/v2/shared-l0-core-v1.json` — 9 prompt-only L0 cases;
- `benchmark-packs/v2/shared-l1-core-v1.json` — 5 controlled-context L1 cases;
- `benchmark-packs/v2/fixtures/shared-l1-v1/` — content-addressed synthetic L1 evidence;
- `src/localbench/v2/shared_battery.py` — deterministic assessor implementations;
- `tests/test_v2_shared_battery.py` — pack, fixture, scoring, and hard-failure regression coverage;
- `docs/SHARED_L0_L1_BATTERY_V1.md` — design rationale and case definitions.

The shared screen contains 14 observations per candidate. Every case declares `screen_trials=1` and `qualification_trials=3`, producing 42 observations for a candidate promoted through the shared qualification phase.

## L0 cases

1. `instruction-precedence`
2. `structured-transformation`
3. `missing-context`
4. `contradiction-detection`
5. `dependency-plan`
6. `code-diagnosis`
7. `authority-boundary`
8. `ambiguity-recognition`
9. `output-discipline`

## L1 cases

1. `evidence-traceability`
2. `conflicting-sources`
3. `lifecycle-selection`
4. `repair-diagnosis`
5. `evidence-gap`

## Assessment contract

The battery uses deterministic Python evaluators rather than model-as-judge scoring. Assessors check machine-verifiable facts, IDs, dependency relations, state decisions, evidence citations, exact output bounds, and declared hard-failure conditions.

Hard failures are intentionally limited to structural/safety-relevant behavior such as protected-literal leakage, fabricated certainty when context is explicitly absent, false destructive-action claims, and invented resolution of unresolved evidence conflicts. Ordinary incorrect reasoning remains a scored failure rather than an automatic campaign elimination.

Evaluator implementation identity is content-addressed from normalized source bytes. Changing grading logic therefore changes evaluator identity.

## Cross-platform exact-byte rule

L1 fixture SHA-256 values identify exact fixture bytes. The first Windows validation exposed Git CRLF conversion changing those bytes. `.gitattributes` now pins V2 benchmark packs and fixtures to LF on every checkout.

This is an evidence requirement, not cosmetic formatting: Windows and POSIX hosts must materialize identical fixture bytes for the same benchmark identity.

## Validation

Checkpoint `7bb96f916cb3a20a83beeaac104430258ef31f08` passed the complete deterministic repository suite in GitHub Actions run `34584447785` on both Windows and Ubuntu.

Validation includes:

- both packs parse through the real Benchmark Pack V2 contract;
- pack levels and 9+5 case counts are exact;
- all cases preserve the 1-screen / 3-qualification repetition policy;
- every L1 fixture exists and its on-disk SHA-256 exactly matches the pack declaration;
- canonical perfect outputs pass every deterministic assessor;
- declared L0 and L1 hard failures are detected;
- malformed JSON fails scoring without inventing undeclared hard failures;
- evaluator implementation identities remain content-addressed;
- the complete pre-existing V1/V2 deterministic repository suite remains passing.

## Non-claims

This acceptance does not mean a real model has been qualified or run.

No Ollama request, local model load, ACL execution, broad candidate campaign, or role assignment occurred while constructing this content.

Before real candidate execution, the intended host still requires BL-3 capture/repeatability and the exact runtime/model/configuration identities for the campaign. Any case requiring stronger containment must also pass the applicable BL-7 host/backend preflight.

## Next bounded benchmark-content task

The next content step is **L2 neutral bounded-tool cases**. Those cases should use the already-accepted `bounded-files-v1` portable capability and BL-6 concrete bounded read/write harness to measure tool-use retention relative to this L0/L1 baseline.
