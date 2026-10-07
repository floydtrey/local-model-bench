# Worker Context Handoff Requirement

Store this requirement before Worker qualification so dependent tasks do not lose context.

## Dispatch context

The controller should dispatch one task at a time. Each Worker should receive:

- the original project intent;
- the full approved task list;
- the specific task assigned to that Worker;
- prerequisite handoff notes/results from completed dependent tasks;
- current relevant files and artifacts.

The Worker is authorized to execute only the assigned task unless explicitly told otherwise.

## Worker completion handoff

At the end of the assigned task, the Worker must leave a concise handoff note containing any facts, decisions, discoveries, changed files, verified assumptions, limitations, or unresolved issues that a Worker performing the next dependent task would need.

Do not repeat irrelevant details.

If nothing needs to be carried forward, state:

`No handoff information required.`

## Persistence rule

Do not rely on information that exists only in model reasoning or conversation history. Anything required by a later task must be written into the handoff note or persisted in the project.

This requirement should be implemented and tested before Worker qualification.
