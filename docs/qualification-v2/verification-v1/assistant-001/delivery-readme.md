# Persistent event journal

Run with Python 3.10 or later from this directory. Only the standard library is
required. All database paths must be explicit, with an existing parent directory.

Save this single line as UTF-8 `events.jsonl`:

```json
{"event_id":"evt-1","source":"sensor","type":"presence","entity":"door","timestamp":"2026-10-07T18:30:00Z","confidence":0.5,"data":{}}
```

```text
python -m assistant_journal --db journal.sqlite ingest --input events.jsonl
python -m assistant_journal --db journal.sqlite count
python -m assistant_journal --db journal.sqlite get --event-id evt-1
python -m assistant_journal --db journal.sqlite history --limit 10 --source sensor
python -m assistant_journal --db journal.sqlite state --as-of 2026-10-07T18:31:00Z
python -m assistant_journal --db journal.sqlite append --help
python -m unittest discover -s tests -v
```

`append --event-json JSON` accepts one event as a command-line JSON argument.
Quote that argument according to your shell. `ingest` avoids shell quoting and
accepts at most 1,000 nonblank lines atomically. Any invalid event or conflicting
ID rolls back the whole batch. Success emits JSON on stdout and exits 0; errors
emit JSON on stderr, leave stdout empty and exit 2 without raw payloads/tracebacks.

Event IDs are global. An identical canonical retry is a duplicate; a different
payload under an existing ID raises a conflict and never overwrites evidence.
Appends commit before returning. Reopen the same database to retain observations;
corruption is an error, never permission to reset it. This is application-level
restart persistence, not a power-loss durability guarantee.

TTL defaults to 300 seconds from event time. `state` requires an explicit replay
clock. It separates source/entity/type, selects the newest eligible observation,
and excludes it at exact expiry without restoring older evidence. Future events
cannot suppress eligible older observations. Empty state means unknown, not
proof of household absence. History retains expired and future observations.

Public tests are preserved. Candidate tests add focused validation checks; their
coverage is not evidence of every contract behavior. Use independent acceptance
evidence and source review for complete acceptance. Running Python here provides
no OS or network sandbox. No services, live devices, model calls or deployment
are part of this package.
