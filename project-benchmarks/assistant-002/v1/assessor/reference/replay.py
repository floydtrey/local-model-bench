"""Reference virtual replay; commits progress only after confirmed append."""
from copy import deepcopy
from datetime import timedelta
from .event_contract import instant
from .scenario import normalize_scenario, scenario_digest
from .schedule import compile_schedule


class Replay:
    def __init__(self, raw: dict, sink):
        self._scenario = normalize_scenario(raw)
        self._digest = scenario_digest(self._scenario)
        self._schedule = compile_schedule(self._scenario)
        self._sink = sink
        self._cursor = self._clock = self._inserted = self._duplicates = 0

    def advance(self, to_ms: int) -> dict:
        if type(to_ms) is not int or not self._clock <= to_ms <= self._scenario['duration_ms']:
            raise ValueError("Invalid virtual time")
        completed = []
        while self._cursor < len(self._schedule):
            record = self._schedule[self._cursor]
            if record['at_ms'] > to_ms:
                break
            inserted = self._sink.append(deepcopy(record['event']))
            if type(inserted) is not bool:
                raise ValueError("Sink append must return bool")
            self._cursor += 1
            self._inserted += int(inserted)
            self._duplicates += int(not inserted)
            self._clock = record['at_ms']
            completed.append(dict(delivery_id=record['delivery_id'], event_id=record['event']['event_id'],
                                  at_ms=record['at_ms'], inserted=inserted))
        self._clock = to_ms
        at = instant(self._scenario['start_at']) + timedelta(milliseconds=to_ms)
        as_of = at.isoformat(timespec='microseconds').replace('+00:00', 'Z')
        state = deepcopy(self._sink.current_state(as_of=as_of))
        return dict(at_ms=to_ms, as_of=as_of, deliveries=completed, state=state)

    def checkpoint(self) -> dict:
        return dict(schema_version=1, scenario_sha256=self._digest, cursor=self._cursor,
                    current_ms=self._clock, inserted=self._inserted, duplicates=self._duplicates)

    @classmethod
    def from_checkpoint(cls, raw: dict, sink, saved: dict):
        result = cls(raw, sink)
        if type(saved) is not dict or saved.keys() != result.checkpoint().keys():
            raise ValueError("Invalid checkpoint fields")
        for key in ('schema_version', 'cursor', 'current_ms', 'inserted', 'duplicates'):
            if type(saved[key]) is not int or saved[key] < 0:
                raise ValueError("Invalid checkpoint integer")
        if saved['schema_version'] != 1 or saved['scenario_sha256'] != result._digest:
            raise ValueError("Foreign checkpoint")
        cursor, clock = saved['cursor'], saved['current_ms']
        if cursor > len(result._schedule) or clock > result._scenario['duration_ms']:
            raise ValueError("Checkpoint exceeds scenario bounds")
        if saved['inserted'] + saved['duplicates'] != cursor:
            raise ValueError("Checkpoint counts do not match cursor")
        if cursor and result._schedule[cursor - 1]['at_ms'] > clock:
            raise ValueError("Consumed delivery is after checkpoint clock")
        if cursor < len(result._schedule) and result._schedule[cursor]['at_ms'] < clock:
            raise ValueError("Pending delivery predates checkpoint clock")
        result._cursor, result._clock = cursor, clock
        result._inserted, result._duplicates = saved['inserted'], saved['duplicates']
        return result
