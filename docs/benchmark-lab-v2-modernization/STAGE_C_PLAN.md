# Stage C bounded source implementation plan

Prepared 2026-10-10. Root accepted B corrected code3fb8d7b5a428a57cdb37b4d2d185c2f8c7ee8bdc/final documentatione1affdf610f3c7c040615b465af5eaf7cda47cee and authorized C1 on the same modernization branch/PR11. No live action, model or Stage F cutover is authorized by this source plan.

| Increment | Scope and gate |
| --- | --- |
| C1 | Qualified private runtime/API extra; same-package app factory, strict transport DTOs, shared native passive reader, DenyAll and isolated fixtures, transport-only liveness, unknown health coverage, nonrecovering queue snapshots, exact B capture/assessment projection and source-scoped durable cursor. Stop at checked-in tested handoff for root review. |
| C2 | Proposed extraction of EXISTING Tk coordination into ONE reusable native controller with legacy UI facade/headless fixtures. Retain queue/process/settings/persistence/recovery and lock ownership. Not authorized by C1; root review first. |
| C3 | Proposed typed opt-in private publisher settings in EXISTING CLI/parsers/allowlisted launchers and command builder, using the same native publisher and ProcessRunner. No alternate runner or independent controls. Root review first. |

[C1_API_CONTRACT.md](C1_API_CONTRACT.md) specifies implemented passive interfaces, typed fields/nulls/units, source/boot identity, cursor snapshot/replay/reset, health dependency/coverage semantics and bounds. [NATIVE_PRODUCER_CONTRACT.md](NATIVE_PRODUCER_CONTRACT.md) remains canonical for B storage/publication meaning. C1 leaves migrations, T13/assessors/catalogs and native engine behavior intact.

Private installed-data access and effects remain denied. A real Owner/person/grants profile, exact browser/Origin/TLS/session/revocation policy and operational acceptance are still unagreed. Auth reuse proposal ae987c0 is investigative only; contract0.1.1 principles-only is unchanged. D UI, E historical import/sanitization/public approval, F runtime deployment/scroll-fix preservation/cutover, model runs and remote routing retain separate gates.
