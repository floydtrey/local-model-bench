# Project Intent — Benchmark Fixture Projects

These benchmark fixture projects represent small existing Python applications being changed incrementally.

The intended direction for work on these projects is:

- Preserve existing public interfaces and existing behavior unless the supplied project intent explicitly requires a change.
- Prefer the smallest change that fully satisfies the supplied project intent.
- Reuse the project's existing structure, conventions, service boundaries, and tests rather than creating parallel implementations without need.
- Prefer standard-library capabilities when the supplied project intent says no new third-party dependencies.
- Do not add unrelated refactors, documentation work, infrastructure, abstractions, or features that are not required to satisfy the supplied project intent.
- Existing project files, tests, and implementation details may be inspected to establish facts needed for implementation.
- Discovering an existing fact from the project is different from inventing a missing requirement, policy, definition, expected behavior, or project decision.
- Tests should demonstrate the requested behavior and preserve relevant existing behavior.
- Plans should remain practical for bounded Workers: prerequisites should precede dependent work, and later tasks should not depend on unstated information that earlier work failed to preserve.

This Project Intent guides these benchmark fixture projects. It does not create authority contrary to Law.
