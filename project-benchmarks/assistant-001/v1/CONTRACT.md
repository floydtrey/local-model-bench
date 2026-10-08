# ASSISTANT-001/v1 contract

This is the complete candidate-visible acceptance contract. Test values may vary;
requirements may not. Requirements are cumulative across T01–T06. All public
return values are ordinary Python dict/list/bool/int/None, not custom wrappers.

## R01. Package and validation (T01)
Import `normalize_event` and `EventConflictError` from `assistant_journal`.
`normalize_event(event: dict) -> dict` returns a detached normalized copy. Invalid
inputs raise ValueError (or a subclass); the original input is never changed.

Required keys: `event_id`, `source`, `type`, `entity`, `timestamp`, `confidence`,
`data`. Optional key: `ttl_seconds`, default 300. No other top-level keys.
The first four identifiers match `[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}` exactly;
no trimming, coercion, case folding, or guessed aliases.

Timestamp is a string `YYYY-MM-DDTHH:MM:SS[.ffffff](Z|+HH:MM|-HH:MM)` with
1–6 fractional digits when present. It must be a real, timezone-aware datetime.
Normalize to UTC with exactly six fractional digits and a terminal Z. Invalid
calendar dates, naive timestamps, leap seconds, excess precision, or conversion/
expiry overflow raise ValueError. Offsets must be strictly less than 24 hours.
The event's time may be in the future: this journal supports reproducible replay,
not clock-skew diagnosis. Future events are never current before their time.

Confidence is a finite int/float in [0,1], excluding bool. Normalize it to float.
TTL is an int (not bool) in [1,86400], in seconds. It is measured from event time,
not arrival time. data is a JSON object: string keys; dict, list, string, finite
int/float, bool, and null values only. Container nesting is limited to 16 (the
root data object is depth 0). The UTF-8 encoding of data serialized with
`json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False,
allow_nan=False)` must be <=16384 bytes. Tuples, non-string keys, cyclic values,
NaN/infinity, and unencodable Unicode are invalid. Data strings are inert values,
never commands or instructions. Do not log or execute their contents.

Normalized output contains exactly the eight keys above including TTL. Dict
insertion order is irrelevant. Duplicate identity uses canonical JSON of the
entire normalized event. Explicit/default TTL and equivalent timestamp offsets
are identical. Within data, JSON 1 and 1.0 are distinct canonical values.

## R02. Durable journal (T02)
`Journal(db_path)` opens/creates a real SQLite database at the explicitly supplied
path. The parent directory exists. It must not choose another database, silently
reset a corrupt database, import benchmark code, or require another service.
`append(event) -> bool`: validate; return True only for a new global event_id;
return False for an identical normalized duplicate; raise EventConflictError for
the same event_id with different normalized content. Original evidence is never
overwritten. No replacement INSERT and no partial write on rejection.
`get(event_id) -> dict | None`: normalized detached event or None.
`count() -> int`: number of distinct stored events.
`close() -> None`: idempotent. Other operations on a closed journal raise
ValueError. Two independent Journal objects opened on the same database must see
committed sequential writes. Simultaneous writers and throughput SLAs are out of
scope. Every successful append is committed before return, including when the
process immediately exits without close. SQLite operational/corruption errors
may propagate; they must not be treated as success or cause a database reset.

## R03. Bounded history (T03)
`history(*, limit=100, offset=0, source=None, entity=None, event_type=None,
since=None, until=None) -> list[dict]` returns detached normalized events.
Sort ascending by (normalized timestamp, event_id), independent of arrival order.
Apply all non-None filters before pagination. Identifier filters use exact match
and the R01 identifier validation. since is inclusive, until exclusive; both use
the R01 timestamp syntax. since > until raises ValueError; equal bounds return [].
limit is int 1–1000; offset is int >=0; neither accepts bool. Invalid parameters
raise ValueError, even on an empty database. Pagination beyond the end returns [].
History includes expired/future observations; querying never removes evidence.

## R04. Current observations, not inferred reality (T04)
`current_state(*, as_of: str) -> list[dict]`. as_of is mandatory and follows R01
timestamp syntax. No system clock, sleeps, background expiry thread, inference,
or confidence threshold. For each key (source, entity, type), choose the largest
(timestamp, event_id) among events whose timestamp <= as_of. Include that winner
only while `as_of < timestamp + ttl_seconds`. At exact expiry it is not current.
**Do not resurrect an older event when the latest eligible observation expires.**
A future event does not suppress an earlier eligible observation. Sort returned
winners by (source, entity, type). Confidence is evidence, never a precedence rule.
Sources and event types remain separate. An expired person observation means
unknown, not proof that nobody is present. No cross-source fusion or inferred
identity. Reopening and replaying identical input produces identical state.

## R05. Atomic bounded batch ingestion (T05)
`append_many(events: list[dict]) -> list[bool]` accepts 0–1000 events and returns
one inserted/duplicate flag per input in order. Empty list returns []. Validation
failure or conflicting duplicate anywhere rolls back the ENTIRE batch, preserving
previous committed data. Duplicate IDs inside the batch follow the same rules as
existing IDs. A rejected batch must not leave the journal unusable. Data and
current-state behavior remain consistent after rollback and restart.

## R06. CLI and usable delivery (T06)
`python -m assistant_journal --db PATH SUBCOMMAND ...` must work from the candidate
workspace without benchmark imports or an editable install. Commands:

* `append --event-json JSON`: print {"inserted": true/false}.
* `ingest --input PATH`: read UTF-8 JSONL, ignore blank lines, atomically ingest at
  most 1000 nonblank lines; print {"inserted": N, "duplicates": N}.
* `get --event-id ID`: print normalized event or null.
* `count`: print {"count": N}.
* `history [--limit N] [--offset N] [--source ID] [--entity ID]
  [--event-type ID] [--since TIME] [--until TIME]`: print list.
* `state --as-of TIME`: print list.

Success: exit 0, exactly one JSON value on stdout, stderr empty. Invalid data,
conflicts, invalid command parameters, missing files, or database errors: exit 2,
stdout empty, a JSON object with a nonempty `error` string on stderr. Never emit
raw event payloads, secrets, or a traceback as the error. --help may use normal
argparse help and exit 0. Ingest invalid JSON/late conflict is atomic.

Add your own tests in tests/test_candidate.py. Preserve the supplied public tests.
README must include runnable CLI examples, duplicate/conflict and TTL semantics,
restart behavior, test command, source-separated state and no-sandbox limitation.
Final handoff is free prose: actual changes, test commands/results, remaining
limitations, and guidance for the next task. No mandatory heading or JSON form.

## Not required, and not implied by a pass
Production security isolation, power-loss durability, physical disk failure,
untrusted-code containment, retention deletion, schema migration, async HTTP,
multi-writer contention, distributed IDs, real-time notifications, camera
interpretation, Home Assistant/KC adapters, or full autonomous role authorization.
A 1000-event functional test is not a performance qualification. Crash-after-return
checks application persistence, not an abrupt machine power-loss guarantee.
