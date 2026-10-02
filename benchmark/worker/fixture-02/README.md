# Worker Qualification Fixture 02 — Inventory CLI

This disposable Python project is the implementation fixture for Planner Intent 04 / Governor Plan B.

Current behavior:
- `inventory.service.list_items(include_inactive=False)` is the existing inventory lookup/filtering API.
- the CLI has an existing `list` subcommand;
- normal CLI results go to stdout;
- errors go to stderr;
- the project uses only the Python standard library.

The Worker qualification runner injects the canonical original intent and approved plan from the existing Planner/Governor benchmark sources. Do not add task-specific instructions to this fixture.
