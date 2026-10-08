"""Small, deliberately straightforward oracle for acceptance-test calibration."""
import json
import sqlite3
from datetime import timedelta
from .validation import EventConflictError, canonical, identifier, instant, normalize_event

class Journal:
    def __init__(self, db_path):
        self._db = sqlite3.connect(str(db_path), timeout=5)
        try:
            self._db.execute("CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            self._db.commit()
        except BaseException:
            self._db.close()
            raise
        self._closed = False

    def _open(self):
        if self._closed:
            raise ValueError("Journal is closed")

    def _append(self, event):
        body = canonical(event)
        previous = self._db.execute("SELECT body FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
        if previous is not None:
            if previous[0] != body:
                raise EventConflictError("Event ID conflicts with existing evidence")
            return False
        self._db.execute("INSERT INTO events VALUES (?, ?)", (event["event_id"], body))
        return True

    def append(self, event: dict) -> bool:
        self._open()
        normalized = normalize_event(event)
        with self._db:
            return self._append(normalized)

    def get(self, event_id: str) -> dict | None:
        self._open()
        identifier(event_id)
        row = self._db.execute("SELECT body FROM events WHERE event_id=?", (event_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def count(self) -> int:
        self._open()
        return self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self) -> None:
        if not self._closed:
            self._db.close()
            self._closed = True

    def _events(self):
        return [json.loads(row[0]) for row in self._db.execute("SELECT body FROM events")]

    def history(self, *, limit=100, offset=0, source=None, entity=None,
                event_type=None, since=None, until=None) -> list[dict]:
        self._open()
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError("Invalid pagination")
        for value in (source, entity, event_type):
            if value is not None:
                identifier(value)
        start = instant(since) if since is not None else None
        end = instant(until) if until is not None else None
        if start is not None and end is not None and start > end:
            raise ValueError("Reversed bounds")
        result = [e for e in self._events()
                  if (source is None or e["source"] == source)
                  and (entity is None or e["entity"] == entity)
                  and (event_type is None or e["type"] == event_type)
                  and (start is None or instant(e["timestamp"]) >= start)
                  and (end is None or instant(e["timestamp"]) < end)]
        result.sort(key=lambda e: (e["timestamp"], e["event_id"]))
        return result[offset:offset + limit]

    def current_state(self, *, as_of: str) -> list[dict]:
        self._open()
        now = instant(as_of)
        latest = {}
        for event in self._events():
            if instant(event["timestamp"]) > now:
                continue
            key = (event["source"], event["entity"], event["type"])
            previous = latest.get(key)
            if previous is None or (event["timestamp"], event["event_id"]) > (previous["timestamp"], previous["event_id"]):
                latest[key] = event
        return [e for _, e in sorted(latest.items())
                if now < instant(e["timestamp"]) + timedelta(seconds=e["ttl_seconds"])]

    def append_many(self, events: list[dict]) -> list[bool]:
        self._open()
        if type(events) is not list or len(events) > 1000:
            raise ValueError("Batch must contain at most 1000 events")
        normalized = [normalize_event(e) for e in events]
        with self._db:
            return [self._append(e) for e in normalized]
