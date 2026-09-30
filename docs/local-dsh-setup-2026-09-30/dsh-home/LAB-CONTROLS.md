# Lab control reference

This describes the deployed lab-native composition. It is an operational reference, not an additional owner-policy source. Owner policy and precedence are in `${USERPROFILE}/.dsh/AGENTS.md`. Current runtime results take precedence over an older description of control state. Report a mismatch rather than pretending either source grants permission.

## 1. What runs and where

The active preset is `${USERPROFILE}/.dsh/.agent-presets/lab-native/agent.cordis.yml`. The host profile uses the shipped bundles declared in `${USERPROFILE}/.dsh/profiles/web/package.json`, plus `cordis.patch.yml`; the empty `cordis.yml` is not an inventory of all installed capabilities.

Installed Harness packages and their README contracts live under `${USERPROFILE}/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/`. This is an installed distribution, not a guaranteed source checkout or development build tree. The main package is version 0.1.5-rc.2 at this revision. Check the installed version when auditing later.

Custom implementation directory: `C:/KC/integrations/deepseek/real-harness/`:
- `native-progress-plugin.mjs` and `tool-progress-guard.mjs`: tool-failure and repeated-call handling.
- `repetition-guard.mjs`: streaming repetition detection.
- `native-effect-guard.mjs`: uncertain effects and native intent persistence.
- `native-permission-boundary.mjs`: recorded denial and owner permission review.
- `native-governance.mjs`: Lab-specific prompt/tool guidance and failure explanations through native hooks; no permission grant or execution controller.
- `native-memory-plugin.mjs`: native KC checkpoint/task/evidence tools.
- `native-result-review.mjs`: review and acceptance of particular file bytes.

Tool descriptions in the current request contain their exact argument contracts. Package docs explain native behavior; the Lab's scoped guidance identifies additional active controls. Credential stores and unrelated documents are not sources for these contracts; use the paths above to find the governing sources.

## 2. Ordinary failures

`FS_NOT_FOUND` means the path was not found; it is not proof access was denied. Check the known source path and use read/glob/grep as needed. `INVALID_ARGS` means that call was not dispatched; correct the arguments. A normal nonzero test exit means the test failed; inspect its result and repair within scope.

Some failed effectful calls have uncertain partial effects. The effect guard can require inspection even when the error is not a permission violation. Its exact state is reported separately. Do not infer that all failed calls are safe to repeat.

## 3. Permission denial

First distinguish native denial from a recorded Lab permission boundary.

The Lab records structured shell sandbox denials and applicable native pre-execution refusals. A shell denial may occur after partial execution; a pre-execution refusal means that call did not start. A pending Lab boundary applies across the native parent/child session family. It prevents shell execution, writes, delegation and other tools outside its inspection list until owner review.

While that boundary is active, available inspection/stop tools are `read`, `read_image`, `glob`, `grep`, `get_goal`, `list_agents`, `job_list`, `job_output`, `job_kill` and `interrupt_agent`. Other controls may further restrict a call. `ask_user_question`, skill loading and KC tools are currently blocked by this boundary; ask the owner in ordinary chat. Their absence from the list is current implementation, not an assertion that they are inherently unsafe.

“Ordinary chat” means a plain assistant text response in this conversation, with no tool call. State the recorded denial key, what happened, known or uncertain effects and the decision needed. The owner can reply here and use the review command; the blocked question tool is not required to communicate.

The owner uses `/lab-permission-review <session-id:call-id> <effects inspected and authorized next action>` in the idle root session. The key comes from the recorded denial. The implementation currently requires a review note of at least 24 characters. This records review and clears that custom boundary; it neither broadens the native sandbox nor runs a retry. An explicit owner instruction is then needed to resume stopped work. The agent cannot submit this command as its own approval.

If no Lab boundary or other stop is active and the native tool supports escalation, a real denial can support one exact-operation retry using the narrowest sufficient `sandbox_permissions` and its required `justification`; the native approval mechanism decides whether it may run. An explicit owner rejection remains binding until the owner explicitly revises that decision. A generic native escalation hint does not clear a Lab guard. File-tool denials and shell denials do not necessarily create identical Lab state; use the actual result/state.

If the answerer is unavailable, asking through the same unavailable channel will not fix it. Explain the failed approval route in chat. Owner intent can require a supported configuration change; prose alone does not change native permissions.

## 4. Uncertain effects

`LAB_UNCERTAIN_EFFECT` identifies calls with missing, interrupted or ambiguous results. It preserves the distinction between failure and unknown effects. Read-only inspection and the guard's permitted planning/evidence tools remain available unless another guard also restricts them.

The owner uses `/lab-reconcile <call-id> <what you verified>` in the idle affected session after inspecting effects. Its note currently requires at least 12 characters. This records inspection, does not retry the operation, and does not clear a separate permission boundary. Read the reported state before resuming. `/lab-review` fingerprints files and `/lab-accept` accepts reviewed bytes; neither replaces reconciliation, permission review or behavioral testing.

## 5. Progress stops and model responses

The existing progress implementation stops after four consecutive tool-level errors, or three identical tool/argument/result combinations within a 32-call lookback since the last admitted user instruction. A changed result for the same tool/arguments resets that repetition streak; calls to other tools do not. A second identical result produces a warning. These are current numeric heuristics, not proof that a task is impossible or that the owner forbids it. On such a stop, automatic tool execution is halted; report the cause. A new explicit owner instruction begins a new progress attempt but does not clear permission or uncertain-effect state. The owner may ask to revise these heuristics; the model must not evade them by changing irrelevant arguments or spawning a worker.

Here, changing irrelevant arguments means making a cosmetic change solely to avoid recognizing the same failed action, such as adding whitespace to a command while attempting the same denied write. Correcting an invalid parameter or a genuinely wrong path based on new evidence is ordinary recovery when the current controls permit that next call. Once a stop is active, a better argument does not by itself reopen execution. Explain the correction and use the applicable recovery route.

Streaming repetition is a separate stop and has no automatic retry. A normal provider stop containing only reasoning or blank text enters Harness's existing EMPTY_RESPONSE retry policy. Output-length termination remains a length termination. Neither a retry nor a normal finish proves the assigned task was successfully completed.

## 6. Planning, goals and work in the background

Ordinary discussion is not formal plan mode. In formal plan mode the active guard restricts tools; user agreement about the plan and the native mode transition are distinct. Use `exit_plan_mode` for the formal review, or ask the owner to change mode if that route is unavailable. After the mode transition, act within the owner's actual authorization.

Goals use their native ID/revision and configured lifecycle. A goal's minimum rounds before accepting `blocked` is a runtime eligibility check, not an instruction to repeat forbidden actions or manufacture work. Report an actual blocker immediately even if that status update is not yet eligible. A resumed goal can be disarmed; resume only when the owner authorizes continuation and applicable guards are resolved.

This preset currently exposes foreground shell and subagent execution; background launching is disabled for those tools. Job-management tools may still inspect existing jobs. When waiting on an existing relevant job and no independent work remains, use its native wait/output mechanism. For delegation, spawn starts with a task prompt; fork carries completed parent history. Supply enough context for the chosen mechanism. Catalog listing may require selecting a provider to list its model IDs.

## 7. Storage and limits

`kc_checkpoint` takes no arguments and saves/verifies native session evidence through the existing KC integration; it does not approve work. `kc_task_update` requires an exact source quote, kind and key; matching later corrections supersede the earlier value. `kc_evidence` addresses this session's archive; revision -1 means current. Use returned references and tool results rather than assuming a relationship to other MCP KC scopes or graph builds.

Model token/context settings, instruction-byte budgets, tool-result truncation and KC recovery-summary limits are separate configuration facts. A limit being configured does not establish that it is necessary or that a particular stop hit it. Inspect the effective request and result before drawing that conclusion. This documentation rebuild changes none of those limits.

## Verified observational child failure (2026-09-25)

The effect guard now inspects the existing native child journal for a failed serial foreground one-shot subagent. When attribution is unambiguous and the settled child has only completed observational tool receipts, it is a known worker failure rather than an uncertain project mutation. Shell/write/control/unknown tools, delegation, missing records, concurrent ambiguity, and interrupted children retain the guard. This does not declare the research successful, repair search connectivity, increase retry limits, or clear permission denials. Source: owner requested diagnosis/fix of call_p556ij42; classification is an assistant implementation choice verified against that recorded run. Use native sessionQuery; no separate state store.

