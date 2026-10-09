# T02 — Evaluation tracks, disclosures, authority, and result contracts (v1)

**Status:** Specification complete for batch 1; **not connected to any model launcher or GUI**.  
**Scope:** additive qualification-v2 design for ASSISTANT-001/v1 and ASSISTANT-002/v1. This does not modify or supersede either frozen v1 packet or the existing 23-case historical role suite.  
**Companion controller-metadata registry:** [EVALUATION_MODES_V1.json](EVALUATION_MODES_V1.json). Registry keys describe assessor/controller behavior; they are **not a required JSON format for candidate model outputs**.

## 1. Core principles and source precedence

1. The projects' existing `PROJECT_INTENT.md`, `CONTRACT.md`, and v1 `packet.json` are the released benchmark specification. V1 `TASKS.md` is an authored **fixed Worker sequence**, not a Planner-produced plan or live Governor approval. No existing task/requirement/acceptance evaluator is rewritten in batch 1.
2. A new v2 `REFERENCE_PLAN.md` is a **withheld comparison oracle** for independent Planner qualification, and (after human approval of its authority wrapper) the common plan for controlled Worker qualification. It is not a product change and cannot expand the v1 contract.
3. Candidate model claims and Governor response prose **never authorize** code execution, release, changed scope, exceptions, external access, deployment, model assignment, or revised Law. The deterministic controller and operator authorization remain separate; Law outranks applicable Intent, and Intent cannot create authority.
4. A Governor case may stipulate a **clearly labeled synthetic authority condition** to make otherwise ambiguous cases comparable. A simulated grant authorizes only answering a simulated case, never operating production tools. The current canonical Governor `LAW.md`, `STATE.md`, `GENERAL_INTENT.md` must be read from the operator's private governance root and hashed at dispatch; no private text is committed to the public benchmark repository.
5. The existing direct-Ollama project runner and the native DeepSeek Harness (DSH) are **distinct transports**. They do not become equivalent because they use the same model name. Installed native DSH version/configuration, startup state, model setting, role prompts, tool transport and release-gate provenance must be verified before any native integration trial. This spec does **not** imply that the native backend is qualified.
6. Explicit consent to run generated Python on the host is **not** an OS or network sandbox. Candidate code belongs in a disposable and preferably OS-isolated execution environment. No production KC, HA, cameras, notifications, finance or databases are authorized by this contract.
7. Preserve free-prose handoffs. The existing Tester/Reviewer verdict conventions may remain, but do not demand that Planner/Worker/Governor generate a new rigid result JSON. Structured records belong to the trusted assessor, not to the candidate.

## 2. Mutually exclusive evaluation tracks

| Track | Unit measured | Input to role | Downstream transition | Permitted transport | Interpret as |
| --- | --- | --- | --- | --- | --- |
| `controlled_role_qualification` | One Planner, Governor, Worker, Tester, or Reviewer **independent** case | Vetted fixed case and source snapshot according to role matrix | Candidate Planner/Governor verdict **never** feeds controlled Worker; an individual role verdict is reviewed on its own | Direct-Ollama currently exists; native DSH would need a separately verified adapter | Individual role competence, **not** end-to-end pipeline reliability |
| `native_pipeline_integration` | One actual released project pipeline | Original released intent and actual prior-role artifacts | Native DSH Planner → Governor → Worker tasks → Tester → bounded repairs → Reviewer under trusted owner-origin release; stop or escalate on unsafe/missing authority | **Native DSH only**, after T14 provenance and adapter qualification | Actual multi-role interaction and error propagation; not an independent Planner/Worker rank |

Neither track substitutes an independent reference implementation after a candidate fails. The historical five-role screen/qualification and A001/A002 direct-Ollama Worker commands remain unchanged and separately labeled **legacy/scaffolded**. No current CLI flag is assigned to these v2 track names until a tested adapter is installed.

### Controlled Worker submodes (different estimands)

| Worker submode | Common across all model trials | Allowed to vary | Meaning |
| --- | --- | --- | --- |
| `isolated_task` | Task contract, approved reference plan + Governor constraints, **identical prevalidated prerequisite workspace bytes**, assigned task, scope and permitted tools | Candidate's implementation and free-prose handoff, exact runtime identity | Ability to perform a particular task given correct starting prerequisites |
| `cumulative_project` | **Initial** starter bytes, approved full plan/constraints, cumulative requirement sequence, task order and tool scope | Actual prior implementation, test changes, and handoff produced by **that candidate** | Ability to complete the entire sequential project and recover through its own prior code |

For isolated T02+, a trusted prerequisite seed may include a *correct implementation of previous requirements* but **must not contain the assigned task's solution**. Its trust/provenance and file hashes belong to the assessor and must be identical across compared models. It is not the hidden assessor reference exposed as a tool path. A failed cumulative stage blocks the following stages; it is never repaired with gold code merely to let the same candidate continue. Thus an isolated task score and a cumulative project score must never be collapsed into one metric.

### Repetitions are not independent projects

Historical Screen executes one fresh trial and Qualification three. Same temperature/seed and repeated fixtures measure observed repeatability, not independent statistical reliability. The 79 A001 / 96 A002 cumulative checks do not represent 175 independent projects or independent model decisions. Record task, project, case and repeat group separately.

## 3. Candidate-visible information matrix

The registry's `role_inputs` maps source **categories**. They describe a future allowlist, not a replacement for restricting the actual filesystem, tool paths, file contents and imports. `required` means a candidate must receive the category before execution; `optional` means the controller can omit it; every other category is denied unless a new reviewed contract authorizes it. `prohibited` highlights especially dangerous leaks.

| Role | Must receive | Explicitly withhold | Special notes |
| --- | --- | --- | --- |
| **Planner** | Objective/project intent, entire *candidate-visible* contract, unsolved starter code and nonanswer architecture facts | Original `TASKS.md`; assessor-only `REFERENCE_PLAN.md`; scoring/ruling oracles; assessor and reference solutions; mutation labels; hidden tests; another model's plan | **Two known leaks exist today:** current project Planner probe joins `TASKS.md` in `DOCS` and separately copies it into the workspace exposed via file snapshot. T05 must close both plus tools/metadata transitive exposures; do not merely delete one paragraph. Existing scaffolded probes stay labeled as such. |
| **Governor** | Original project intent/contract, exact **frozen plan case**, canonical governance snapshot, explicit simulation conditions | Expected approve/deny/escalate answer, decision rationale oracle, hidden assessor checks, fabricated Owner approval | Freeze case input; never compare decisions made against different Law/State bytes as equivalent. Valid simulation assumptions must be visible and marked simulated. |
| **Worker** | Project intent/contract, operator-reviewed full reference plan, trusted applicable Governor guidance, exactly assigned task, bounded tool/file authority, starting workspace; previous Worker handoff if applicable | Assessor checks/reference solution, another candidate Governor's response as authorization, hidden tests, unapproved exceptions | A task authorizes only its writable scope; previous prose is context, not new permission. Initial source identity is fixed by the chosen submode. |
| **Tester** | Contract, assigned task, actual code and its current hash, authorized test-only tools | Expected verdict, mutation labels, reference solution/assessor internals | Worker defects may justify correct FAIL. Test-only file changes are assessed separately; no production-code modifications. |
| **Reviewer** | Contract, current code/hash, legitimate test/implementation evidence, exact assigned task | Gold verdict, mutation labels, assessor source/code | Candidate and Tester claims are evidence to evaluate, not authority or substitutes for actual test records. Reviewer remains read-only. |

**Integration path:** no Planner receives the withheld reference plan. Governor receives the actual Planner plan, Worker receives that **unchanged** plan plus actual Governor guidance under the recorded owner-origin release, and downstream stages get actual prior artifacts. The pipeline must record that the inputs came from the model rather than the benchmark oracle. Wrong upstream work is supposed to affect integrated outcomes; cite the originating stage rather than blaming the next role automatically.

### Explicit leakage surfaces to defend (T05)

Check at least: assembled prompt text; source document concatenations; candidate workspace copy; public README or similar files that quote the task sequence; tool-readable files; listings/file names, symlinks and ancestor paths; saved session history; cached shared directories; copied reference test fixture; screenshots/attachments or tool retrieval paths. The **category validator** introduced in this batch only checks claimed disclosure categories and cannot inspect these bytes; tests and actual sandbox/visible-file filtering are T05 obligations.

## 4. Run identity, comparison requirements, and provenance

The trusted controller must record an **input manifest** *before* dispatch. Every substantive input is identified by source type, path/reference, content SHA-256, origin and authority, visibility, and immutable revision. Required identities:

- Project packet ID + v1 manifest hash; run track + controlled role or actual pipeline; Worker submode if applicable; scenario/case/task ID; ordinal and fresh-session identity.
- Exact intent/contract/assigned task/full approved plan hashes; applicable Governor guidance/ruling and **private governance snapshot hash**; whether the case is simulation or owner-origin execution.
- Starting workspace digest and per-file digest set. For isolated task, hash the trusted prerequisite seed; for cumulative project, record each predecessor's actual code and final prose hashes. Never replace a candidate artifact with gold on continuation.
- Executable transport and effective runtime identity (`direct_ollama` vs `native_dsh`), installed DSH commit/build when applicable, model exact identifier/digest/quantization/context/output/reasoning/keepalive/timeout, role prompt/tool schema hashes and host/environment evidence.
- Source and produced artifact hashes for assessor results, test commands/results, human judgment references, and review workbook. Compare the **exact source that was tested**, not a newer file.

**Input equivalence** is the equality of substantive canonical reference/intent/assigned task/seed hashes and declared allowed tool authority, not a promise that absolute workspace paths, timestamps, temporary run IDs or native process/environment bytes are identical. Record those differing envelopes explicitly. If a material input, canonical governance revision, target code hash or runtime differs, label the trials incomparable (or separately grouped), never silently average.

An assessor must never accept a model's claim to have executed tests without independent tool-execution evidence. Exit code zero indicates the runner finished, not that a role earned PASS or is ready for Assistant deployment.

## 5. Authority, approval and fail-closed stages

**Authority sources allowed by design:** (a) a *trusted operator-reviewed benchmark fixture* authorizing only a simulated qualification action within a disposable scope, or (b) an *authenticated native owner-origin release receipt* matching the exact plan/scope/version for a true native pipeline trial. Candidate plan, Governor APPROVE text, assistant final message, repository membership, and `-AllowHostExecution` are **not** authority sources.

- If Law/Intent or required permission is absent or ambiguous: **escalate/block**, do not infer consent. A valid `simulation_conditions` fixture documents assumptions and restricts itself to offline decision comparison.
- If Governor denies/escalates in the integrated native workflow: preserve evidence and stop/escalate; never reinterpret a positive-sounding sentence as an owner-granted permission.
- If a controlled Planner/Governor candidate fails: record that role's failure; still use the fixed reference input for any separately authorized Worker qualification run. Do not feed the failed candidate plan into the Worker.
- If a cumulative Worker stage fails deterministic acceptance, has unauthorized changes, or lacks usable handoff: mark successors **prerequisite_blocked**. A separately authorized isolated task run is allowed only from a frozen verified seed.
- Tester PASS requires executed applicable evidence; false-green or missing execution is not a demonstrated valid PASS. Reviewer PASS is advisory and subject to independently verified hashes.
- If the native DSH installation/config/tool surface differs from the tested source or cannot be inspected: block a native integration claim, do not relabel direct-Ollama runs as native.

**Final role/case review:** `PASS`, `FAIL`, `BLOCKED`, `NOT_ASSESSED`. Planner semantic equivalence and Governor substantive rulings require human adjudication; deterministic cases and assessor checks assist but cannot alone confer role assignments. Raw observations (process exit, tool errors, model response, acceptance checks) are distinct fields from reviewer judgment.

## 6. Failure attribution rules

| Classification | Required evidence / interpretation |
| --- | --- |
| Candidate requirement failure | Specific output contradicts candidate-visible R/S contract or named behavior, at the **correct assessed file hash** |
| Planner reference leak | Any withheld fixed sequence/plan/oracle reached the Planner by prompt, workspace, tools or carryover — **block qualification**, do not score the answer |
| Governor unsafe approval / false denial / failed escalation | Compare actual ruling and constraints against scenario oracle with matching governance snapshot; unsafe approval is separately critical |
| Tool authority/scope violation | Captured denied call or unauthorized file change; report independently of model semantic correctness |
| Prerequisite blocked | A previous task failed; successors were **not attempted** and are not individually scored FAIL |
| Harness/transport/test-infrastructure error | Failed Ollama/DSH transport, untested tooling, subprocess/timeout, broken assessor or fixture; preserve evidence, do not invent reasoning failure |
| Artifact/evidence mismatch | Code changed since test run, input hash changed, stale capture, missing command evidence; label BLOCKED/incomparable as appropriate |
| Human-review pending | Automated checks ran but plan equivalence, authority reasoning or final code quality not yet reviewed |

A repair is a *separate attempt* with explicit budget, identity and evidence. Do not relabel repaired work as an unassisted first-pass success. Native DSH's existing bounded repair stage is integration behavior, not a license to inject a reference fix during independent qualification.

## 7. Machine-readable mode metadata and what it does **not** do

`EVALUATION_MODES_V1.json` is a versioned **controller metadata** contract. Its exact known track, role, transport and Worker-mode IDs are enumerated so later adapters can reject invalid choices without guesswork. New Python helper `localbench.qualification_v2.contract` validates the static registry and a requested selection or declared disclosure categories. The helper performs **no tool access, model request, file exposure, code execution, owner authorization, task dispatch or DSH release**. In particular, a valid metadata selection is **not** permission to launch.

T05 will enforce real file/prompt disclosure; T07–T09 will add reviewed authority/ruling/reference sources; T10 will realize the Worker modes; T13 will persist the provenance and attribution; T14/T15 will validate native runtime launch and all safety boundaries; T16 adds GUI controls after those runners exist.

## 8. T02 acceptance tests and negative controls

1. Registry accepts only the two named tracks; five controlled roles; one actual pipeline role; native DSH only for integration. Unknown track/role/transport/Worker-mode or invalid combination fails before any run.
2. Planner declared input cannot include `fixed_worker_tasks`, `reference_plan`, expected Governor decision, assessor checks/reference or hidden test. Missing project intent, contract or starter fails the pure manifest validator. **This does not close real byte-level leakage until T05.**
3. Governor candidate cannot receive expected rulings, and Worker cannot receive hidden assessors or a candidate Governor verdict as authority. No candidate role obtains new authority by an output label.
4. Mode registry says candidate Python is **not OS sandboxed**, production access and automatic promotion are false, and native execution requires installed-provenance check.
5. Baseline guard verifies **frozen v1 documents/packet manifests and historical accepted role-suite bytes** against the T01 Git blob identities. It deliberately does **not** freeze executable implementation files that must be extended for v2.
6. All tests run without Ollama, DSH, production services, external network or created model trial. Only `tests/test_qualification_v2_contract.py` covers this phase; additional plan trace validation arrives in T03/T04.

## 9. Review/approval status

**Prepared and tested as design:** This document specifies the authority boundary; it does not grant approval to release model-generated code or mark a reference plan approved. Both T03/T04 reference-plan documents will explicitly carry `OWNER_REVIEW_PENDING`; final authorized Worker handoffs and per-case Governor oracles are later milestones (T07–T09). No model qualifications or production integration are established by completing batch 1.
