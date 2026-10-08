"""Reference delivery compiler. IDs identify transmissions, not new events."""
from copy import deepcopy
from .scenario import normalize_scenario


def compile_schedule(raw: dict) -> list[dict]:
    scenario = normalize_scenario(raw)
    ordered = []
    for index, entry in enumerate(scenario['events']):
        if entry['drop']:
            continue
        for copy_index, offset in enumerate([0, *entry['duplicate_after_ms']]):
            at = entry['at_ms'] + entry['delay_ms'] + offset
            record = dict(delivery_id=f"{entry['key']}/{copy_index}", at_ms=at,
                          event=deepcopy(entry['event']))
            ordered.append((at, index, copy_index, record))
    ordered.sort(key=lambda row: row[:3])
    return [row[3] for row in ordered]
