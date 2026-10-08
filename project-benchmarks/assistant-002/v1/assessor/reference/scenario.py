"""Calibration solution; never substitute for a candidate's implementation."""
import hashlib
import re
from datetime import timedelta
from .event_contract import canonical, identifier, instant, normalize_event

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _keys(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("Invalid fields")


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid integer range")
    return value


def _key(value):
    if type(value) is not str or not _KEY.fullmatch(value):
        raise ValueError("Invalid scenario or entry key")
    return value


def normalize_scenario(raw: dict) -> dict:
    _keys(raw, ('schema_version', 'scenario_id', 'start_at', 'duration_ms', 'events', 'checkpoints'))
    _int(raw['schema_version'], 1, 1)
    scenario_id = _key(raw['scenario_id'])
    start = instant(raw['start_at'])
    duration = _int(raw['duration_ms'], 0, 86400000)
    try:
        start + timedelta(milliseconds=duration)
    except OverflowError as exc:
        raise ValueError("Scenario clock overflow") from exc
    if type(raw['events']) is not list or len(raw['events']) > 256:
        raise ValueError("Invalid events list")
    if type(raw['checkpoints']) is not list or not 1 <= len(raw['checkpoints']) <= 64:
        raise ValueError("Invalid checkpoints list")
    entries, keys, count = [], set(), 0
    for item in raw['events']:
        _keys(item, ('key', 'at_ms', 'event'), ('delay_ms', 'duplicate_after_ms', 'drop'))
        key = _key(item['key'])
        if key in keys:
            raise ValueError("Duplicate entry key")
        keys.add(key)
        at = _int(item['at_ms'], 0, duration)
        delay = _int(item.get('delay_ms', 0), 0, duration)
        offsets = item.get('duplicate_after_ms', [])
        if type(offsets) is not list or len(offsets) > 8:
            raise ValueError("Invalid duplicates list")
        previous = 0
        for offset in offsets:
            _int(offset, 1, duration)
            if offset <= previous:
                raise ValueError("Duplicate offsets must be strictly increasing")
            previous = offset
        if at + delay + previous > duration:
            raise ValueError("Delivery exceeds duration")
        drop = item.get('drop', False)
        if type(drop) is not bool:
            raise ValueError("Invalid drop flag")
        event = normalize_event(item['event'])
        count += 0 if drop else 1 + len(offsets)
        entries.append(dict(key=key, at_ms=at, event=event, delay_ms=delay,
                            duplicate_after_ms=list(offsets), drop=drop))
    if count > 1000:
        raise ValueError("Too many scheduled deliveries")
    checkpoints, previous = [], -1
    for item in raw['checkpoints']:
        _keys(item, ('at_ms', 'expected_ids'))
        at = _int(item['at_ms'], 0, duration)
        if at <= previous:
            raise ValueError("Checkpoints must be strictly time ordered")
        previous = at
        ids = item['expected_ids']
        if type(ids) is not list or len(ids) > 1000:
            raise ValueError("Invalid expected IDs")
        ids = [identifier(value) for value in ids]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate expected ID")
        checkpoints.append(dict(at_ms=at, expected_ids=sorted(ids)))
    return dict(schema_version=1, scenario_id=scenario_id,
                start_at=start.isoformat(timespec='microseconds').replace('+00:00', 'Z'),
                duration_ms=duration, events=entries, checkpoints=checkpoints)


def scenario_digest(raw: dict) -> str:
    return hashlib.sha256(canonical(normalize_scenario(raw)).encode('utf-8')).hexdigest()
