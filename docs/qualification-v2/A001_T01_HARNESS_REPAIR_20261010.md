# Assistant-001 T01 harness repair — bounded source review

## Scope

This development-only repair leaves frozen Assistant-001 v1 files, R01 acceptance
criteria, calibration oracle, 15 historical model run folders and the running
Windows installation unchanged.

### Confirmed defect: contradictory permissions

The pinned generic Worker setup source says not to create or edit tests.
Every Assistant-001 task explicitly lists `tests/test_candidate.py` as a writable
path. The original task dispatch restated the allowed paths but did not tell the
model how to reconcile the apparently conflicting instruction.

**Repair:** Add an Assistant-001-specific clarification in the *task dispatch*
that only `tests/test_candidate.py` may be created/edited, never unrelated tests,
frozen assessor checks, or requirements. Leave the pinned generic setup
and its checksum unchanged. This resolves the instruction ambiguity without
widening the technical file scope.

### Evidence and failure interpretation

The inspected `assistant-001.zip` includes 15 T01 run summaries. Observed
outcomes include completed sessions whose work failed deterministic acceptance,
tool-transport incompatibilities, an unauthorized setup tool call, and output-token
limits. Some completed sessions never executed a file tool, leaving the starter
implementation unchanged. These should not be presented as equivalent failures.

**Repair:** Add `failure_attribution` as an additive case diagnostic:
`tool_transport_incompatible`, `tool_protocol_or_transport_failure`,
`setup_tool_boundary_violation`, `output_limit`, `resource_limit`,
`execution_blocked`, `session_incomplete_or_failed`,
`implementation_acceptance_failure`, `missing_handoff`, or
`authority_scope_violation`, as supported by the existing session and
independent acceptance record. Exception paths use
`project_runner_or_assessor_exception`. The original `status`,
`stop_reason`, `deterministic_passed`, `first_pass_passed` and assessor
checks remain unchanged. A diagnostic is **not** a new pass, scored test, or
determination of intrinsic model ability.

### Tool-call policy

The existing Ollama driver already classifies explicit provider HTTP 400
`does not support tools` responses as `tool_transport_incompatible` and
retains detailed provider/tool event evidence. No arbitrary JSON-looking model
text is converted into privileged tool calls. A model printing
`read_file(...)` as ordinary response text is evidence of **no executed tool
call**, not authority to execute it or a demonstrated transport defect.

### Acceptance and continuation

- Run `python -m unittest tests.test_assistant001 -v` with `PYTHONPATH=src`.
- Run deterministic full regression suite and existing frozen packet validation.
- No inference, graph work, model startup, generated-code execution or host
  deployment during this repair.
- Pull only after CI verification and inspection of the active Windows queue;
  **never update the running benchmark environment mid-run**.
- If investigating plain-text tool requests versus native transport later,
  schedule a separate nonproduction controlled compatibility test. Do not
  silently add protocol coercion, relax frozen requirements, increase token
  budgets, or replay the historical run evidence.
