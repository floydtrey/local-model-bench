"""Calibration CLI. Its messages deliberately do not echo supplied event content."""
import argparse
import json
import sys
from .journal import Journal

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid command arguments")


def main(argv=None) -> int:
    journal = None
    try:
        parser = Parser(description="Local observation journal")
        parser.add_argument("--db", required=True)
        commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
        commands.add_parser("append").add_argument("--event-json", required=True)
        commands.add_parser("ingest").add_argument("--input", required=True)
        commands.add_parser("get").add_argument("--event-id", required=True)
        commands.add_parser("count")
        commands.add_parser("state").add_argument("--as-of", required=True)
        history = commands.add_parser("history")
        history.add_argument("--limit", type=int, default=100)
        history.add_argument("--offset", type=int, default=0)
        for name in ("source", "entity", "event-type", "since", "until"):
            history.add_argument("--" + name)
        args = parser.parse_args(argv)
        journal = Journal(args.db)
        if args.command == "append":
            result = {"inserted": journal.append(json.loads(args.event_json))}
        elif args.command == "ingest":
            from pathlib import Path
            with Path(args.input).open(encoding="utf-8") as stream:
                rows = []
                for line in stream:
                    if line.strip():
                        rows.append(json.loads(line))
                        if len(rows) > 1000:
                            raise ValueError("Batch too large")
            flags = journal.append_many(rows)
            result = {"inserted": sum(flags), "duplicates": len(flags) - sum(flags)}
        elif args.command == "get":
            result = journal.get(args.event_id)
        elif args.command == "count":
            result = {"count": journal.count()}
        elif args.command == "state":
            result = journal.current_state(as_of=args.as_of)
        else:
            result = journal.history(**{k: getattr(args, k) for k in
                                        ("limit", "offset", "source", "entity", "event_type", "since", "until")})
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps({"error": "Invalid request or unavailable journal"}), file=sys.stderr)
        return 2
    finally:
        if journal is not None:
            journal.close()
