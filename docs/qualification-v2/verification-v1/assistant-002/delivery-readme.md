# Offline event simulator

Use Python 3.10 or later and the standard library from this directory:

```text
python -m assistant_simulator validate --input scenarios/door-reconnect.json
python -m assistant_simulator schedule --input scenarios/door-reconnect.json
python -m assistant_simulator jsonl --input scenarios/door-reconnect.json
python -m unittest discover -s tests -v
```

These three CLI commands need no Journal installation. `jsonl` emits one canonical
event per delivery, including duplicate transmissions and a final LF per line;
it is batch input, not timed replay metadata. An empty schedule emits no lines.

For a separately provided compatible `assistant_journal` package on the Python
import path, use `python -m assistant_simulator run --input
scenarios/door-reconnect.json --db journal.sqlite` as a single command. `run`
lazily opens that explicit database and always closes the Journal it owns. It
does not install dependencies or reset a pre-existing database to force success.
Success exits 0, expectation mismatch exits 1 with the complete report, and
input/dependency/sink errors exit 2 with JSON stderr and empty stdout. Normal
results have empty stderr; errors do not echo raw payloads or tracebacks.

Scenario delivery times are virtual; no sleeps or real devices are involved.
An event's original timestamp remains separate from its delivery time. Delays
shift delivery, duplicates retain event IDs/content, and drop removes all copies.
Equal delivery times retain authored entry and copy ordering. The supplied
read-only event_contract defines event validation; the simulator does not clone
the Journal. Library Replay uses an injected sink and never owns or closes it.

Replay checkpoints bind the entire scenario, cursor, clock and counts. The caller
must persist checkpoints atomically and restore the last saved checkpoint into
the same persistent sink. Delivery after a crash is at least once: an append
committed before checkpoint persistence may be retried as a duplicate. This is
not exactly-once delivery or recovery into a fresh empty sink. Append failures
retain earlier confirmed progress; state-query failures do not undo deliveries.
There is no transaction spanning all sink calls.

Expected observations remain authored facts for comparison. Missing/unexpected
sets report discrepancies; no observations means unknown, not proof of absence.
Public tests remain unchanged; focused candidate tests are not complete acceptance
evidence. Review source and matching independent checks for the whole contract.
Executing Python provides no OS/network sandbox, production security, live
household actions, model inference or deployment authority.
