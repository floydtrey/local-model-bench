"""Assessor calibration only. Never materialized into candidate workspaces."""
import json
import math
import re
from datetime import datetime, timedelta, timezone

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")
_FIELDS = {"event_id", "source", "type", "entity", "timestamp", "confidence", "data", "ttl_seconds"}

class EventConflictError(ValueError):
    """An immutable event ID conflicts with previously stored evidence."""


def identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid identifier")
    return value


def instant(value):
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise ValueError("Invalid timestamp")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError("Invalid timestamp offset")
    try:
        # datetime.fromisoformat before Python 3.11 does not accept terminal Z.
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Invalid timestamp") from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _json_value(value, depth=0, ancestors=None):
    ancestors = set() if ancestors is None else ancestors
    if type(value) in (dict, list):
        if depth > 16 or id(value) in ancestors:
            raise ValueError("JSON nesting or cycle")
        ancestors.add(id(value))
        if type(value) is dict:
            if any(type(k) is not str for k in value):
                raise ValueError("JSON keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _json_value(child, depth + 1, ancestors)
        ancestors.remove(id(value))
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite JSON number")
    elif value is not None and type(value) not in (str, int, bool):
        raise ValueError("Unsupported JSON value")


def normalize_event(event: dict) -> dict:
    if type(event) is not dict or not (_FIELDS - {"ttl_seconds"}) <= event.keys() or event.keys() - _FIELDS:
        raise ValueError("Invalid event fields")
    result = {name: identifier(event[name]) for name in ("event_id", "source", "type", "entity")}
    stamp = instant(event["timestamp"])
    confidence = event["confidence"]
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1 or not math.isfinite(confidence):
        raise ValueError("Invalid confidence")
    ttl = event.get("ttl_seconds", 300)
    if type(ttl) is not int or not 1 <= ttl <= 86400:
        raise ValueError("Invalid TTL")
    try:
        stamp + timedelta(seconds=ttl)
    except OverflowError as exc:
        raise ValueError("Expiry overflow") from exc
    if type(event["data"]) is not dict:
        raise ValueError("Data must be an object")
    try:
        _json_value(event["data"])
        encoded = canonical(event["data"])
        if len(encoded.encode("utf-8")) > 16384:
            raise ValueError("Data too large")
        data = json.loads(encoded)
    except (TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError("Invalid JSON data") from exc
    result.update(timestamp=stamp.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                  confidence=float(confidence), ttl_seconds=ttl, data=data)
    return result
