# Independent Planner qualification: T05–T06

> **2026-10-09 technical audit supersedes the earlier review-pending checkpoint below.** All ten controls and both project packet variants have now received delegated AI technical review. Eight controls were corrected for bounded task evidence, project-specific helper scope and material omission/expansion judgments. Alternative valid decompositions remain acceptable. This is AI technical approval, not independent human certification, model qualification or Owner execution authorization. See the [audit report](technical-audit-20261009/AUDIT_REPORT.md) and [complete decisions](technical-audit-20261009/CASE_CONTROL_DECISIONS.md).

This additive interface uses the existing `assistant001.runtime.OllamaSessions`,
`RoleConversation`, Ollama identity/configuration evidence, and
`flashnext_review` JSON/CSV/XLSX writer. It does not introduce an execution engine,
service, state store, project runner or downstream-role dispatcher.

## Audited starting point

Audited branch `benchmark/flashnext-all-roles-v1` at `370e8e0`. The latest backlog
included the Results-tab expansion and left T05–T06 unstarted. Inspection found
the historical `assistant001.campaign.role_prompt` includes all `DOCS`, including
`TASKS.md`, plus the copied workspace. Its README, contract headings and stub
exceptions also disclose fixed task numbering. A002 `UPSTREAM.json` identifies an
assessor reference source. These are valid historical scaffolded probes, not
independent planning measurements.

The historical `assistant001`/`assistant002` probe commands, their prompts,
runtime, packet adapters, v1 packets and source manifests remain unchanged. New
reports explicitly identify `planner_mode=independent_blind`; do not pool their
results with `advisory-role-probe` or the six historical Planner intent cases.

## Candidate boundary

Each project's `qualification-v2/PLANNER_PACKET.json` pins a finite input allowlist,
input hashes, source lineage and the original v1 manifest identity. Its manifest
hash is pinned in the adapter. It is controller metadata and is never dispatched.
The separately versioned `planner-input-v1/` contains an audited derivation of:

- Released intent and contract, with task-sequence references removed.
- Genuine starting code and supplied public examples, with task numbers removed
  from unimplemented-stub messages and scaffold instructions.
- A002's published scenarios and read-only event-validation helper. The helper
  is byte-identical to the supplied v1 dependency; no Journal implementation is included.
- A new planning README with no task plan or assessor pointers.

Outcome rules, limits and interfaces remain the same. Original source files are
never rewritten. The contract's requirement IDs remain visible: requirements are
the problem, not a required task decomposition. Runtime does not glob the source
repository to select inputs. Extra repository files cannot become candidate files.

`prepare` creates a fresh workspace and exact `prompt.txt` containing the complete
allowlisted view. Run metadata contains only case/input identities and hashes,
not assessor content. Before dispatch, the adapter reconstructs the expected
packet and checks exact workspace contents, prompt and metadata. Symlinks,
Windows junctions/reparse paths (including ancestors), injected files and changed
contents are rejected. Candidate input hashes do not depend on local paths,
timestamps, model names or preparation IDs.

The Planner inspects the entire view **inline, with no tools**. The session gets
`workspace=None` and no writable paths. This matters because the existing role
tool surface includes `run_tests`, even for a nominally read-only file scope.
Unsolicited list/read/write/test calls are denied by the existing role engine.
No filesystem paths, controller metadata, assessor references, traces or checks
are passed in context assets. Each invocation creates a fresh RoleConversation;
Ollama process keep-alive does not reuse conversation messages.

This is a prompt/tool disclosure boundary for this adapter, not OS containment
against a malicious inference server or a concurrent host administrator. It does
not claim to prevent prior model training contamination. Do not manually expose
the repository, run-evidence tree or assessor folder to an external agent and
label that trial equivalent. Prepared files are read-only to the candidate because
the candidate has no file capability; host file permissions are not the boundary.

## Cases and semantic review

There are two versioned cases per project:

| Suffix | Candidate input | Appropriate substantive outcome |
|---|---|---|
| `complete` | Full intent, public contract and starting code | A plan covering all R01–R06 or S01–S06, with any feasible decomposition |
| `missing-goal` | Background interfaces only; intent explicitly absent; no public test/scenario work order | Stop for the missing goal and supply no actionable tasks |

The missing-goal case is a separate counterfactual. It does not change the
complete project's released requirements. The historical role setup distinguishes
`AMBIGUOUS` for a missing policy/decision from `BLOCKED` for an unclear goal.
Reviewers interpret the explanation in context; no literal keyword match grants
credit. A correctly stopped case receives assessed outcome `BLOCKED`, retaining
the candidate's interpreted disposition separately. Refusing a fully specified
complete case does not automatically earn BLOCKED credit.

The assessor reuses T03/T04 `TRACEABILITY.json` positive outcomes and critical
failure classes for the six material groups, plus the full public contract and
assessor-only reference plan. It records hashes and the unchanged
`OWNER_REVIEW_PENDING` reference status. The rubric covers dependencies, bounded
tasks, executable acceptance, scope, risks, uncertainty and delivery. The plan
does not need reference headings, task IDs, a particular task count, JSON, or a
phrase template. Review against behavior, including negative cases, not lexical
similarity. An unresolved material omission or unsafe scope is major/critical
and prevents PASS regardless of other coverage.

`assessment.json` separates:

- **Execution:** success, error, resource limit, blocked transport, or imported text.
- **Diagnostics:** output presence, session completion, authority violations and
  record validation. Three checks concern one case; they are not three challenges.
- **Assessed outcome:** `NOT_ASSESSED` until a human records PASS, FAIL or BLOCKED.
- **Human adjudication:** reviewer declaration, time, case/input/output/rubric
  bindings, each requirement/dimension's status/severity/rationale and exact text
  evidence. Missing behavior can be documented as an absence without fabricated quotes.

Evidence spans use zero-based Python Unicode character offsets `[start,end)`
into the exact saved `candidate.txt`, with an identical `quote`. They are not
UTF-8 byte offsets. An adjudication from another input, candidate, case or rubric
is rejected. Records must cover every material group and dimension. A blocked
case requires a justified uncertainty, blocked requirement groups, and a human
finding that no actionable tasks follow. Review files are never model input.

The executable validator checks consistency and evidence bindings, not the truth
of a human's semantic judgment or identity. It cannot establish that an excerpt
actually satisfies its cited requirement. Only an actual reviewer should submit
`human_declared` records. The imported plan path supports reviewing external free
prose, but records `execution_status=imported` and excludes it from runtime
comparisons. A human may assess its plan quality without inventing an inference run.

The inherited writer includes additive outcome/binding/evidence columns; legacy
missing fields stay null/blank. `deterministic_passed` and `first_pass_passed`
remain unknown for semantic Planner quality even after a human verdict.
Captured runs retain model/runtime/host/interface references, effective
configuration records and transcript links in the existing evidence tree.
Comparison eligibility also requires matching input/case/rubric and inspected
runtime/configuration; a successful transport status alone proves no capability.

## Deterministic calibration and remaining human work

`planner-calibration/` contains ten authored controls: two substantially different
decompositions (three and eight units), a critical omission, scope expansion and
a correct blocked response for each project. Their annotations are explicitly
`calibration_fixture`, cannot be submitted as human reviews, and remain
`HUMAN_REVIEW_PENDING`. The offline command validates bindings and expected
record consistency, and proves a defect/blocked record cannot simply be relabeled
PASS. It also inventories the original six Planner cases without modifying or
rescoring them. **It does not algorithmically prove the controls' semantic quality.**

Human calibration must independently read those controls against the source
contract and reference, verify each evidence mapping and expected judgment,
record disagreements and rationale, and version any corrections before claiming
an accepted semantic calibration. No genuine model has been qualified here.

## Commands

From the repository root, make the package importable with an editable install
or set `PYTHONPATH=src` (`$env:PYTHONPATH='src'` in PowerShell).

```text
python -m localbench.assistant001 validate
python -m localbench.assistant002 validate
python -m unittest discover -s tests -p "test_qualification_v2*.py" -v
python -m localbench.qualification_v2 calibrate
python -m unittest discover -s tests -v
```

Prepare without inference or candidate code execution:

```text
python -m localbench.qualification_v2 prepare --project assistant-001 --output-root local-state/planner-v2
python -m localbench.qualification_v2 prepare --project assistant-002 --case missing-goal --output-root local-state/planner-v2
```

Use the printed run directory. Importing an existing plan produces an unassessed
record, a review template and the existing review package:

```text
python -m localbench.qualification_v2 assess --run-dir RUN_DIR --plan-file PLAN.txt
python -m localbench.qualification_v2 assess --run-dir RUN_DIR --plan-file PLAN.txt --review-file COMPLETED_HUMAN_REVIEW.json
```

For a captured model output, omit `--plan-file`. Each assessment writes a new
directory and preserves earlier records. Exit 0 means the requested records were
written, not that the plan passed.

Optional real inference requires explicit operator consent. No real-model test
was part of implementation or deterministic CI. After consent, a fresh prepared
run can use:

```text
python -m localbench.qualification_v2 run --run-dir RUN_DIR --model INSTALLED_TAG --allow-model-inference
```

This route enables no host-code execution and accepts no execution flag, input
plan or review material. It does not launch any Worker, Governor, Tester, Reviewer
or project. A run cannot be reused for another session. Use the runtime context
options only after confirming the model can receive the complete packet; no
local input truncation is permitted and runtime failures remain execution evidence.

## Authority and status

Owner acceptance of A001/A002 as useful benchmark designs permits this benchmark
work. It does not sign a canonical Worker authorization, authorize deployment,
approve generated code, or assign model roles. T09 still owns formal authority
and reference versioning. T05 is implemented with deterministic isolation tests.
T06's rubric, record workflow and authored controls are implemented; substantive
human calibration/signoff is pending. T13's broader reporting contract, GUI
Results work and all later task dependencies remain separate.
