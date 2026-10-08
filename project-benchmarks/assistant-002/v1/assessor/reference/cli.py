"""Reference CLI. Journal import is lazy; no real-time services are involved."""
import argparse
import json
from pathlib import Path
import sys
from .event_contract import canonical
from .scenario import normalize_scenario, scenario_digest
from .schedule import compile_schedule
from .evaluate import evaluate_scenario


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid command arguments")


def main(argv=None) -> int:
    journal = None
    try:
        parser = Parser()
        parser.add_argument('command', choices=('validate', 'schedule', 'jsonl', 'run'))
        parser.add_argument('--input', type=Path, required=True)
        parser.add_argument('--db')
        args = parser.parse_args(argv)
        if (args.command == 'run') != (args.db is not None):
            raise ValueError("Database is required only for run")
        raw = json.loads(args.input.read_text(encoding='utf-8'))
        scenario = normalize_scenario(raw)
        schedule = compile_schedule(scenario)
        code = 0
        if args.command == 'run':
            from assistant_journal import Journal
            journal = Journal(args.db)
            result = evaluate_scenario(scenario, journal)
            journal.close()
            journal = None
            code = 0 if result['passed'] else 1
            text = canonical(result) + '\n'
        elif args.command == 'jsonl':
            text = ''.join(canonical(row['event']) + '\n' for row in schedule)
        elif args.command == 'schedule':
            text = canonical(schedule) + '\n'
        else:
            text = canonical(dict(scenario_id=scenario['scenario_id'],
                                  scenario_sha256=scenario_digest(scenario), deliveries=len(schedule))) + '\n'
        sys.stdout.write(text)
        return code
    except Exception:
        sys.stderr.write('{"error":"Invalid scenario, command or unavailable journal"}\n')
        return 2
    finally:
        if journal is not None:
            try:
                journal.close()
            except Exception:
                pass
