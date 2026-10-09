# Batch 1 acceptance and handoff — T02, T03, T04

**Date:** 2026-10-08  
**Repository:** `floydtrey/local-model-bench`, branch `benchmark/flashnext-all-roles-v1`  
**Original audited baseline:** `79d422ee4c037ac305fd2f15c06eadf5302d0972`; audit `a4f3087d06677d37a742c732ea3d98e7f6b0307f`.  
**Batch starting commit:** `5de272e3fe059c5cccfa6ff6dec638507073bd41`.  
**T02 commit:** `2c0366f11ddba8e80f2716641000f07bb496e04e`.  
**T03 commit:** `ecbd5974abf6ffe7019bcfad0d1ae9a528c54a51`.  
**T04 commit:** `ba43cf815bcff6d42faf087e18bf729835db6d5e`.  
**Combined regression-test commit:** `7e66a8074c2ed113e4338decd234d34791466990`.

## Result and approval boundary

| Task | Implementation output | Verification | Authorization/review status |
| --- | --- | --- | --- |
| **T02** | [Mode/authority/disclosure contract](T02_EVALUATION_AND_AUTHORITY_CONTRACT.md), [machine-readable design registry](EVALUATION_MODES_V1.json), pure fail-closed `src/localbench/qualification_v2/contract.py` and seven new tests | Track/role/transport/Worker-mode combinations, invalid source categories, tampered registry, frozen v1 documents; four CI configurations passed | **COMPLETE as design + pure metadata validation**; real workspace disclosure/DSH runtime execution not connected by this task |
| **T03** | [ASSISTANT-001 reference plan](../../project-benchmarks/assistant-001/qualification-v2/REFERENCE_PLAN.md) and [R01–R06 traceability](../../project-benchmarks/assistant-001/qualification-v2/TRACEABILITY.json) | Six requirements mapped across six original tasks, exact writable scopes, 45 named decorated assessor methods and 79 cumulative frozen acceptance checks; SHA evidence checked | **DRAFT COMPLETE — OWNER_REVIEW_PENDING**; no authority granted |
| **T04** | [ASSISTANT-002 reference plan](../../project-benchmarks/assistant-002/qualification-v2/REFERENCE_PLAN.md) and [S01–S06 traceability](../../project-benchmarks/assistant-002/qualification-v2/TRACEABILITY.json) | Six requirements mapped across six original tasks, exact writable scopes, 44 named decorated assessor methods, 96 cumulative checks, all eight authored scenarios and pinned read-only A001 helper hash | **DRAFT COMPLETE — OWNER_REVIEW_PENDING**; no authority granted |

**Only a separately recorded owner/human review can approve the reference documents for Worker authorization or label substantive Planner/Governor comparison decisions final.** A completed code review/test is not an implicit release receipt. Both reference plans remain assessor-only for blind Planner trials, regardless of their visibility to a human reading this repository.

## Evidence from deterministic CI

- [Batch 1 foundation tests, four OS/Python configurations — success](https://github.com/floydtrey/local-model-bench/actions/runs/37869157006). Matrix: Windows + Ubuntu, Python 3.10 + 3.12.
- Every matrix job ran the original `python -m localbench.assistant001 validate` and `python -m localbench.assistant002 validate` against their unchanged frozen manifests/dependencies.
- Each matrix job then ran **11 new focused tests**, including positive mode selection, negative forged authority/forbidden-category cases, tampered metadata, immutable v1 Git blob check, source/requirement/assessor trace verification, mutation of plan trace, and both original `prepare` routines on disposable workspaces.
- The preparation tests specifically verify `REFERENCE_PLAN.md`, `TRACEABILITY.json`, and `assessor` are **absent** from the existing v1 starter workspace. The same tests explicitly acknowledge that old v1 workspace still **contains TASKS.md**; T05 must enforce the new blind Planner mode rather than pretending the old probe is blind.
- The v1 source-protection test pins eight frozen packet/role-suite inputs; the packet CLI validates full v1 manifests. Executable infrastructure modules are **not** blanket-frozen, so additive v2 adapters can be implemented later.
- Tests used only standard-library static inspection, digest calculations, stored fixtures and disposable temporary directories. **No model, installed DSH, camera, KC, HA or production database was run.**

## Material design decisions

1. **Keep original fixed Worker task plans:** user-authored v1 `TASKS.md` is retained and remains available to existing Worker trials; it is **not** a valid independent Planner input.
2. **No circular scoring:** Planner must not see either reference plan or v1 task list, including via copied workspace, tools, metadata or history. Governor must not see its expected rulings. Worker in controlled trials receives only a separately authorized reference plan/handoff.
3. **Model-vs-model fairness:** `isolated_task` requires identical prevalidated source/prerequisite code, while `cumulative_project` begins with identical starter/plan but intentionally preserves each model's own predecessor output. Both are reported separately.
4. **Two transports:** direct-Ollama baseline vs native DSH are explicitly different. No automatic native run/DSH release or owner-auth override has been introduced.
5. **Source and behavior frozen:** R01–R06 and S01–S06 semantic contracts, v1 acceptance suites, historical role packet source, prior GUI and queue launchers remain unchanged. New reference plans are siblings under `qualification-v2/`, **outside** the frozen `v1/` folders.
6. **No forced model answer forms:** the mode registry and source traces are controller/assessor records, not new JSON response obligations for candidate Planners, Workers or Governors.

## Cross-checks and open gates before T05/T06

| Gate | State | Required future proof |
| --- | --- | --- |
| Frozen original A001/A002 packets and roles | **PASS** — CI validates both packet manifests and source blobs | Keep CI enabled for every future v2 change |
| T02 known-mode metadata validation | **PASS** — pure contract module + negative cases | Later runner/GUI must actually consult reviewed mode contracts; a successful `validate_selection` is *not* launch authorization |
| T03/T04 plan/requirement coverage | **PASS** — six of six requirement groups and original task scopes in each trace | Human/Owner review must approve reference semantics before official grading or Worker handoff |
| New reference inadvertently copied to existing v1 candidate workspace | **PASS** — absent from both prepare workspaces | T05 must close known leak of *original* v1 TASKS.md to independent Planner via prompt and workspace; later test ancillary tool/metadata surfaces |
| Native DSH installed provenance and full five-role qualification | **NOT VERIFIED** | T14/T17; private DSH development source is not proof of installed working release |
| Real model accuracy or Planner/Governor grade | **NOT EVALUATED** | T05–T08 plus T17 and human review |
| OS/network isolation of generated candidate Python | **NOT PROVIDED** | Explicit host execution acknowledgement remains necessary; use disposable OS-isolated environment |

## Handoff to next batch

**Next tasks:** T05 → T06. Reuse `localbench.qualification_v2.contract` (pure mode/disclosure metadata checks), both assessor-only reference/trace packages and the existing project `prepare`, `role_prompt`, `run_probe` implementation **as historical comparison**. Do not modify the frozen v1 Planner experience in place. Build a new independent Planner packet whose complete tool-readable workspace excludes `v1/TASKS.md`, reference plans, hidden assessor code, scoring oracles and other candidates' answers. Tests must cover *both* the known prompt inclusion and workspace-copy leak.

After T05 proves no leak, T06 can evaluate model-generated plans semantically against withheld R/S requirement traceability; nonidentical plans can be correct. Real model runs and human-approved scoring are separate gates. The Governor decision oracle and canonical authorized Worker handoffs remain T07–T09, not silently satisfied by these draft plans.
