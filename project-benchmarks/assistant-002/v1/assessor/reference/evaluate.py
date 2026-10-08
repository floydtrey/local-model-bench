"""Reference expectation comparison, with errors distinct from mismatches."""
from .event_contract import identifier
from .scenario import normalize_scenario, scenario_digest
from .replay import Replay


def evaluate_scenario(raw: dict, sink) -> dict:
    scenario = normalize_scenario(raw)
    replay = Replay(scenario, sink)
    checks = []
    for checkpoint in scenario['checkpoints']:
        observation = replay.advance(checkpoint['at_ms'])
        try:
            ids = [identifier(e['event_id']) for e in observation['state']]
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid journal observation") from exc
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate observed event IDs")
        expected = checkpoint['expected_ids']
        missing = sorted(set(expected) - set(ids))
        unexpected = sorted(set(ids) - set(expected))
        checks.append(dict(at_ms=checkpoint['at_ms'], as_of=observation['as_of'],
                           expected_ids=list(expected), observed_ids=sorted(ids),
                           missing=missing, unexpected=unexpected, passed=not missing and not unexpected))
    if scenario['checkpoints'][-1]['at_ms'] != scenario['duration_ms']:
        replay.advance(scenario['duration_ms'])
    progress = replay.checkpoint()
    return dict(scenario_id=scenario['scenario_id'], scenario_sha256=scenario_digest(scenario),
                passed=all(check['passed'] for check in checks), delivered=progress['cursor'],
                inserted=progress['inserted'], duplicates=progress['duplicates'], checks=checks)
