# Stage C1 local passive API contract

Revision benchmark-api:v1. Development implementation only, prepared 2026-10-10. Stage B dependency: accepted corrected code 3fb8d7b5a428a57cdb37b4d2d185c2f8c7ee8bdc and final documentation e1affdf610f3c7c040615b465af5eaf7cda47cee. The canonical [native producer contract](NATIVE_PRODUCER_CONTRACT.md) remains authoritative for publication, assessment and cursor meaning.

The optional in-package app factory exposes passive observations and existing native publication reads. It contains no execution/controller loop, command handler, login, model discovery/inference, publication activation or restore operation. Default policy denies every private read before calling native ports. Transport liveness is the only unprotected response. No installed-data allowance, actual principal or operational authority is implemented.

## Ownership and package boundary

The base localbench package still has no runtime dependencies. Optional api dependencies are the qualified FastAPI 0.143.0, Pydantic 2.14.0 and Uvicorn 0.54.0; the complete Windows CPython 3.15 x64 lock is requirements/api-windows-cp315.lock. Starlette 1.7.0 and Pydantic core 2.50.0 resolved natively. No Authlib, JOSE, HTTPX, Node server, broker, queue, scorer or identity store was added.

Six existing read methods move from CasePublisher to its shared PublicationReader base. Publisher behavior stays in the same owner and uses those methods; the passive reader exposes no publication, export, notification, review or recovery effects. Events gain an optional SQL limit without changing the publisher's default complete-history behavior. Latest binding reads use exact relational IDs, not names or paths. T13 projection code, catalogs, assessors, original migrations 1–10, native launchers, queue scheduling and ProcessRunner remain unchanged.

NativeReadPort accepts an already-open query-only connection and approved artifact/queue source, supplied outside request handling. No GET opens a DB, creates directories, changes schema, checks processes, recovers evidence or dispatches work. Connections must support the calling thread and be dedicated to serialized reads; a read transaction closes with rollback even on failure. Opening a SQLite WAL reader can maintain shared-memory sidecars, so physical connection opening/rebinding is a native-owner responsibility outside GET. This is not a promise of sidecar-free live attachment or an operational deployment mechanism.

## Implemented routes and proposed grants

| GET route | Fixture admission scope | Function and effect classification |
| --- | --- | --- |
| /api/v1/liveness | None | Transport-only fact; no source, installed version, DB, private data or readiness claim |
| /api/v1/health | health.read | Passive, bounded prerequisite/schema observation; no hashing, recovery or inference |
| /api/v1/publications | results.read | Complete bounded latest native attempt projection, capture and assessed states |
| /api/v1/queue | queue.read | Existing JSON validation with recover=False; no custody/process inference |
| /api/v1/events/cases | events.read and results.read | Finite page from B's global revision stream |
| /api/v1/streams/cases | events.read and results.read | Finite native SSE batch from the same revision stream; reconnect uses Last-Event-ID |

These scope names are a fixture/development contract, not agreed operational grants. All non-GET methods return 405. No control, callback, token, actor, arbitrary file/path, evidence download or raw log route exists. Only events/cases accepts an after query; unexpected query fields and GET bodies are rejected. OpenAPI/Swagger/Redoc web routes are disabled.

## Wire types and nullability

DTOs forbid unknown envelope fields and type coercion, reject nonfinite numbers, and preserve explicit nulls. Native row JSON retains its source schema and values; no transport denominator, score or eligibility is calculated. Consumers must honor both API and native schema revisions. Native projection must be benchmark-case-publication:v2 with nonnegative integer counts, an exact high-water and matching canonical bindings.

| Object | Required fields and types | Nullable fields and semantics |
| --- | --- | --- |
| Liveness | schema_version = benchmark-api:v1; transport_alive: bool = true | None; conveys only a responding handler |
| SourceIdentity | source_id/generation: bounded opaque strings; mode: development or fixture | software_commit: exact 40-hex SHA or null; deployment_commit is always null in C1 |
| Common private envelope | schema_version, boot_id: UUID string; source: SourceIdentity; received_at: aware UTC timestamp | Installed/deployed identity is never inferred from source or branch |
| PublicationSnapshot | high_water: nonnegative revision sequence; cursor: opaque string; native: unchanged publication object; bindings: exact latest canonical identities; evidence_check = native_current_files; count_units | Native pending/unknown outcomes, score, maximum_score, configuration observations and review data retain null; null never becomes zero or PASS |
| Latest binding | publication_id, sequence, revision, stage, attempt_id, trial_id, case_id, run_id, configuration_id, protocol_id | result_id is null for capture and a string for assessed; case_id here is the canonical DB case identity, distinct from a source row's display ID |
| Event | sequence/revision: positive integers; id/attempt_id: strings; stage: capture or assessed | result_id: null for capture; producer_event_time is null because B's event table supplies no event timestamp |
| EventPage | common envelope, high_water, cursor, has_more: bool, events: array of Event | No event-count-as-case-count conversion |
| StreamEvent | common envelope, cursor, event: Event; SSE id equals cursor | producer_event_time: null; receipt is API emission receipt, not native event creation |
| QueueSnapshot | common envelope, native_schema_version: original version integer, content_sha256: hash of exact saved bytes, native: validated normalized JSON, custody = unknown | owner_observed_at: null; a saved Running/PID is not current process custody |
| Observation | scope/status/coverage/reason_code/method_revision/source/required_for; received_at; values: JSON map; producer_outcome | observed_at/expires_at/sample_started_at/sample_ended_at may be null; sample interval must be complete and ordered or absent |
| Health | common envelope, observations array, freshness_policy = unaccepted | aggregate_status: null; no global status is synthesized |

published_attempts counts canonical latest attempts. committed_results counts assessed publications. high_water counts publication revisions. A single attempt can contribute capture and assessed events without creating another case/trial/attempt; native rows/checks/retries/repair observations are separate units. bindings preserve exact IDs. Source case/run/config/review/repair/protocol data in native rows remains unchanged; transport adds no automatic qualification, role assignment or universal score. T13 metrics are not recomputed on GET.

## Durable cursors and consistent snapshots

Opaque cursor payload has version benchmark-case-cursor:v1, scope case_publication, source_id, generation, sequence and event_id. It is a position, not an authorization capability. Sequence zero has null event_id. Every other cursor must match the native stable event at that exact sequence. Reject wrong/unsupported source/version/generation, future sequence, missing/changed anchor and malformed cursor with 409 cursor_reset_required; clients refetch the snapshot and resume after its high-water.

Projection, exact bindings, event high-water and anchor are read within one native read transaction. A subsequent replay reads strictly after that high-water. B's global case_publication_events is canonical; legacy final-only case_commit_events is not used. Capture has assessment pending and null assessed outcome/score; later native assessment updates the latest projection under the same identities. Original immutable revision records remain retained.

The native owner must rotate source generation and rebind the read port on EVERY restore/import replacement, even when restored history shares an identical prefix. Anchor/high-water checks catch divergent or truncated history, but cannot identify all equivalent-prefix restores. API boot_id changes per factory; durable source generation can survive a normal restart only if the same authoritative source is confirmed. No restore endpoint or automatic identity store is added.

Event pages contain at most 500 native revisions and report has_more. A page cursor identifies its last returned event. Native SSE sends the same IDs/fields and a cursor as SSE id. HTTP admission and cursor checks happen before headers; synthetic authority is checked before every emitted event. The stream ends after the bounded batch. Delivery/reconnect is at least once, so clients deduplicate source/generation/stable event ID and sequence. C1 supplies no continuous subscription or immediate operational revocation guarantee.

Queue/terminal/resource notifications are ephemeral and are NOT mixed into this durable stream. Future ephemeral streams need their own boot generation, sequence, retention/reset/refetch and dedup contract. There is no cross-source causal ordering claim or second journal.

## Health scopes and dependency matrix

| Function | Required dependencies for stated coverage | Optional or excluded dependencies |
| --- | --- | --- |
| Transport liveness | Responding API handler | DB, queue owner, runtime, identity provider, evidence and resource sensors excluded |
| Health private observation | Accepted admission; configured native read port for DB coverage | Queue/process, model runtime and resources are not checked; missing observations remain unknown |
| Publication reads | results.read; approved query-only current schema10 connection on patched SQLite; exact original artifact root and bounded available evidence | Runtime/model loading, execution owner, external routing and auth provider are not probed |
| Durable events | events.read plus results.read; approved current query-only DB and matching source cursor | Artifact hashing, assessment execution, receipts/notification delivery, queue owner and inference excluded |
| Saved queue observation | queue.read; exact approved bounded saved JSON | Process probes/lock acquisition/recovery are excluded; current owner status remains unknown |

Health scope values: api_transport, database_reads, queue_owner, model_runtime, resources. Proposed normalized statuses are healthy/degraded/unavailable/unknown. C1 sets status AND coverage to unknown because health freshness/TTL/skew policies have not been accepted. coverage_reason distinguishes an observed check from not_checked, missing, denied, expired, invalid or timeout. producer_outcome independently distinguishes ready/failed/not_observed. A fresh producer-observed SQLite/schema prerequisite failure is preserved as failed; consumer denial/timeout/error is not proof that a required function failed. No API response claims whole-system health from a PID, queue state, HTTP response or model unload state.

reason_code is allowlisted: transport_alive, native_read_ready, freshness_policy_unset, not_observed, reader_missing, reader_denied, reader_timeout, reader_failed, observation_expired, observation_invalid. C1 uses freshness_policy_unset for observed checks because accepted expiry is absent. Raw exception text, paths, prompts, logs, actors and credentials never enter health/error reasons.

observed_at is the native check's production observation time, not an event's creation time. received_at is API receipt; Web adds its own receipt. Expiry and sample interval are explicitly null when unavailable. All declared dates are aware UTC; no accepted TTL, skew tolerance, polling interval or overloaded-resource threshold is hard-coded. Future acceptance must declare each function's expiry and required versus optional dependencies before healthy/degraded/unavailable normalization. Paused/idle/stopped/unloaded is state, not inherently unhealthy.

## Bounds and enforcement

Read serialization lock budget: 250 ms. DB connection busy timeout must be bounded by the native caller (fixtures use 250 ms). Snapshot maximum: 500 canonical attempts, 16 MiB total actual linked artifact bytes checked before unchanged native integrity reads, and 4 MiB native response bytes. Exceeding a population bound fails the entire read; it never drops rows or changes a metric population. Events: 500 plus one lookahead; queue JSON: 1 MiB; query: 4 KiB; opaque cursor: 2 KiB. These are local technical load bounds, not accepted Web health timing values. Large/missing/corrupt evidence remains unknown or read-unavailable; no inference, recovery, export or expensive integrity work is triggered by health.

Error response detail is a safe code: identity_unavailable/identity_invalid (401), grant_denied (403), cursor_reset_required (409), reader_unavailable/native_read_unavailable (503), query_fields_invalid/get_body_rejected (400), read_only_api (405). No error decides assessed outcome. Default denial occurs before port invocation. Fixture validators are injected only in Python via create_fixture_app with fixture SourceIdentity; there is no HTTP actor/header-to-grant conversion or CLI bypass. Fixtures demonstrate implementation behavior, not operational identity/security acceptance.

TrustedHost permits loopback hostnames for this development transport. It is not an exact scheme/host/port Origin fence. No CORS grants, sessions, cookies, Bearer validator or provider trust profile exist. Operational authority, exact authority/origin, resource TLS, mutation CSRF, token purpose/issuer/audience/person/assurance mapping, expiry/skew and stream/download revocation still require a reviewed mechanism. All private installed data remains denied until that gate. Nothing here transfers queue authority or admits a monitoring client as Owner.

## Deferred integrations

[Web authentication reuse proposal 0.1.0](https://github.com/floydtrey/floydslab-web-system/blob/ae987c0ac86b42189a1f7343e1efee4f4872b77d/docs/AUTHENTICATION_REUSE_PROPOSAL.md) is compatible investigative scope only, as reviewed in issue comment6098742676. No client/provider/grant is selected and no auth dependencies/callbacks are added. Contract0.1.1 remains principles-only; TTLs and concrete operational trust remain unaccepted.

C2 can separately extract existing Tk coordination into one reusable native controller with a legacy facade, preserving scheduler/recovery/process custody. C3 can separately add typed opt-in publisher settings to existing CLI/allowlisted launchers and retain ProcessRunner. Both require root review before expansion. UI/D, historical import/E, public sanitized publication, actual login, private access, live runtime install, queue/model execution, remote routing and Stage F cutover remain separate gates.
